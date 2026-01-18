"""
Batch Training with Randomized Scenarios.

Trains the RL agent across diverse, randomly generated combat scenarios
to improve generalization.
"""

import os
import sys
import time
import json
import csv
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np

# Check for training dependencies
try:
    import gymnasium as gym
    from gymnasium import spaces
    from stable_baselines3 import DQN, PPO
    from stable_baselines3.common.callbacks import BaseCallback, CheckpointCallback, EvalCallback
    from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv
    from stable_baselines3.common.monitor import Monitor
    TRAINING_DEPS_AVAILABLE = True
except ImportError as e:
    print(f"Training dependencies not available: {e}")
    print("Install with: pip install -r train/requirements-train.txt")
    TRAINING_DEPS_AVAILABLE = False
    sys.exit(1)

from sim.env import CombatEnv
from sim.scenario_generator import ScenarioGenerator, generate_scenario
from ai.schema import TOTAL_ACTIONS, ObservationSpec


# =============================================================================
# RANDOMIZED ENVIRONMENT WRAPPER
# =============================================================================

class RandomizedCombatEnv(gym.Env):
    """
    Gymnasium environment that randomizes scenarios each episode.
    """
    
    def __init__(
        self,
        seed: int = 42,
        party_size: int = 4,
        party_level_range: tuple = (1, 3),
        difficulties: list = None,
        grid_size_range: tuple = (12, 18),
        max_steps: int = 100
    ):
        super().__init__()
        
        self.seed_base = seed
        self.party_size = party_size
        self.party_level_range = party_level_range
        self.difficulties = difficulties or ["easy", "medium", "hard"]
        self.grid_size_range = grid_size_range
        self.max_steps = max_steps
        
        # Generator for scenarios
        self.generator = ScenarioGenerator(
            seed=seed,
            party_size=party_size,
            party_level_range=party_level_range,
            difficulties=self.difficulties,
            grid_size_range=grid_size_range
        )
        
        # Inner combat environment (will be reset each episode)
        self.inner_env: CombatEnv = None
        self.episode_count = 0
        self.step_count = 0
        
        # Action and observation spaces
        self.action_space = spaces.Discrete(TOTAL_ACTIONS)
        self.observation_space = spaces.Box(
            low=-1.0,
            high=1.0,
            shape=(ObservationSpec.TOTAL_SIZE,),
            dtype=np.float32
        )
        
        # Track metrics
        self.episode_rewards = []
        self.episode_lengths = []
        self.win_rate_history = []
    
    def reset(self, seed=None, options=None):
        """Reset with a new random scenario."""
        if seed is not None:
            self.seed_base = seed
            self.generator.base_seed = seed
        
        # Generate new scenario
        scenario_seed = self.seed_base + self.episode_count
        state = self.generator.generate(seed=scenario_seed)
        
        # Create new inner environment with this state
        self.inner_env = CombatEnv(seed=scenario_seed)
        
        # Properly initialize the environment
        from sim.mechanics import DiceRoller
        self.inner_env.roller = DiceRoller(scenario_seed)
        self.inner_env.state = state
        self.inner_env.state.rng = np.random.default_rng(scenario_seed)
        self.inner_env.step_count = 0
        
        # Find first enemy in initiative order
        self.inner_env._advance_to_enemy_turn()
        
        self.episode_count += 1
        self.step_count = 0
        
        obs = self.inner_env._get_observation()
        inner_info = self.inner_env._get_info()
        info = {
            "scenario_seed": scenario_seed,
            "party_size": len(state.party),
            "enemy_count": len(state.enemies),
            "difficulty": "random",
            "action_mask": inner_info.get("action_mask", np.ones(TOTAL_ACTIONS, dtype=bool))
        }
        
        return obs, info
    
    def step(self, action):
        """Execute action in current scenario."""
        if self.inner_env is None:
            raise RuntimeError("Environment not initialized. Call reset() first.")
        
        self.step_count += 1
        
        obs, reward, done, truncated, info = self.inner_env.step(action)
        
        # Truncate if max steps reached
        if self.step_count >= self.max_steps:
            truncated = True
        
        # Add action mask to info
        inner_info = self.inner_env._get_info()
        info["action_mask"] = inner_info.get("action_mask", np.ones(TOTAL_ACTIONS, dtype=bool))
        
        return obs, reward, done, truncated, info
    
    def render(self, mode="human"):
        """Render current state."""
        if self.inner_env:
            return self.inner_env.render_text()
        return "No environment initialized"
    
    def close(self):
        """Clean up."""
        if self.inner_env:
            self.inner_env = None


# =============================================================================
# CUSTOM CALLBACKS
# =============================================================================

class TrainingMetricsCallback(BaseCallback):
    """
    Callback to track and log training metrics.
    """
    
    def __init__(self, log_dir: str, verbose: int = 1):
        super().__init__(verbose)
        self.log_dir = log_dir
        self.metrics_file = os.path.join(log_dir, "training_metrics.csv")
        self.episode_rewards = []
        self.episode_lengths = []
        self.wins = 0
        self.losses = 0
        self.total_episodes = 0
        
        # Create log directory
        os.makedirs(log_dir, exist_ok=True)
        
        # Initialize CSV
        with open(self.metrics_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "timestep", "episode", 
                "reward", "length", "win", "loss",
                "avg_reward_100", "win_rate_100"
            ])
    
    def _on_step(self) -> bool:
        # Check for episode end
        for info in self.locals.get("infos", []):
            if "episode" in info:
                ep_reward = info["episode"]["r"]
                ep_length = info["episode"]["l"]
                
                self.episode_rewards.append(ep_reward)
                self.episode_lengths.append(ep_length)
                self.total_episodes += 1
                
                # Track wins/losses
                is_win = info.get("enemy_won", False)
                is_loss = info.get("party_won", False)
                if is_win:
                    self.wins += 1
                if is_loss:
                    self.losses += 1
                
                # Calculate rolling stats
                recent_rewards = self.episode_rewards[-100:]
                avg_reward = np.mean(recent_rewards)
                
                recent_wins = sum(1 for i, r in enumerate(self.episode_rewards[-100:]) 
                                 if r > 0)  # Positive reward = likely win
                win_rate = recent_wins / len(recent_rewards) if recent_rewards else 0
                
                # Log to CSV
                with open(self.metrics_file, "a", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        datetime.now().isoformat(),
                        self.num_timesteps,
                        self.total_episodes,
                        ep_reward,
                        ep_length,
                        1 if is_win else 0,
                        1 if is_loss else 0,
                        avg_reward,
                        win_rate
                    ])
                
                if self.verbose >= 1 and self.total_episodes % 100 == 0:
                    print(f"Episode {self.total_episodes}: "
                          f"Reward={ep_reward:.2f}, "
                          f"Avg100={avg_reward:.2f}, "
                          f"WinRate={win_rate:.2%}")
        
        return True


class ActionMaskCallback(BaseCallback):
    """
    Callback to apply action masking during training.
    
    Note: This is a workaround for SB3's limited action masking support.
    For production, consider using sb3-contrib's MaskablePPO.
    """
    
    def __init__(self, verbose: int = 0):
        super().__init__(verbose)
    
    def _on_step(self) -> bool:
        # Action masking is handled in the environment's step function
        # by penalizing invalid actions
        return True


# =============================================================================
# TRAINING FUNCTIONS
# =============================================================================

def make_env(rank: int, seed: int, **kwargs):
    """Create a single environment instance."""
    def _init():
        env = RandomizedCombatEnv(seed=seed + rank, **kwargs)
        env = Monitor(env)
        return env
    return _init


def train_batch(
    total_timesteps: int = 100000,
    n_envs: int = 4,
    algorithm: str = "DQN",
    seed: int = 42,
    party_level_range: tuple = (1, 3),
    difficulties: list = None,
    save_dir: str = None,
    eval_freq: int = 5000,
    verbose: int = 1,
    resume_from: str = None
):
    """
    Train RL agent with randomized batch scenarios.
    
    Args:
        total_timesteps: Total training timesteps
        n_envs: Number of parallel environments
        algorithm: "DQN" or "PPO"
        seed: Random seed
        party_level_range: (min, max) party level
        difficulties: List of difficulties to sample
        save_dir: Directory to save models
        eval_freq: Evaluation frequency
        verbose: Verbosity level
        resume_from: Path to existing model to continue training from
    """
    print("=" * 60)
    if resume_from:
        print("BATCH TRAINING - RESUMING from previous model")
    else:
        print("BATCH TRAINING - Randomized Scenarios")
    print("=" * 60)
    print(f"Algorithm: {algorithm}")
    print(f"Total timesteps: {total_timesteps:,}")
    print(f"Parallel environments: {n_envs}")
    print(f"Party levels: {party_level_range}")
    print(f"Difficulties: {difficulties or ['easy', 'medium', 'hard']}")
    if resume_from:
        print(f"Resuming from: {resume_from}")
    print("=" * 60)
    
    # Setup directories
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if save_dir is None:
        save_dir = os.path.join(project_root, "data", "ai", "models", f"batch_{timestamp}")
    os.makedirs(save_dir, exist_ok=True)
    
    log_dir = os.path.join(save_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    checkpoint_dir = os.path.join(save_dir, "checkpoints")
    os.makedirs(checkpoint_dir, exist_ok=True)
    
    # Environment kwargs
    env_kwargs = {
        "party_level_range": party_level_range,
        "difficulties": difficulties or ["easy", "medium", "hard"],
        "grid_size_range": (12, 18),
        "max_steps": 100
    }
    
    # Create vectorized environments
    if n_envs > 1:
        # Use DummyVecEnv for simplicity (SubprocVecEnv has issues on Windows)
        envs = DummyVecEnv([make_env(i, seed, **env_kwargs) for i in range(n_envs)])
    else:
        envs = DummyVecEnv([make_env(0, seed, **env_kwargs)])
    
    # Create evaluation environment
    eval_env = DummyVecEnv([make_env(999, seed + 999, **env_kwargs)])
    
    # Create or load model
    if resume_from:
        # Load existing model and continue training
        print(f"\nLoading model from: {resume_from}")
        if algorithm.upper() == "PPO":
            model = PPO.load(resume_from, env=envs, verbose=verbose, tensorboard_log=log_dir)
        else:
            model = DQN.load(resume_from, env=envs, verbose=verbose, tensorboard_log=log_dir)
        print("Model loaded successfully! Continuing training...")
    else:
        # Create new model from scratch
        if algorithm.upper() == "PPO":
            model = PPO(
                "MlpPolicy",
                envs,
                learning_rate=3e-4,
                n_steps=2048,
                batch_size=64,
                n_epochs=10,
                gamma=0.99,
                gae_lambda=0.95,
                clip_range=0.2,
                ent_coef=0.01,
                verbose=verbose,
                seed=seed,
                tensorboard_log=log_dir
            )
        else:  # DQN
            model = DQN(
                "MlpPolicy",
                envs,
                learning_rate=1e-4,
                buffer_size=100000,
                learning_starts=1000,
                batch_size=64,
                tau=0.005,
                gamma=0.99,
                train_freq=4,
                gradient_steps=1,
                exploration_fraction=0.3,
                exploration_initial_eps=1.0,
                exploration_final_eps=0.05,
                verbose=verbose,
                seed=seed,
                tensorboard_log=log_dir
            )
    
    # Callbacks
    callbacks = [
        TrainingMetricsCallback(log_dir, verbose=verbose),
        CheckpointCallback(
            save_freq=max(eval_freq // n_envs, 1000),
            save_path=checkpoint_dir,
            name_prefix=f"{algorithm.lower()}_batch"
        ),
        EvalCallback(
            eval_env,
            best_model_save_path=os.path.join(save_dir, "best"),
            log_path=log_dir,
            eval_freq=max(eval_freq // n_envs, 1000),
            n_eval_episodes=10,
            deterministic=True
        )
    ]
    
    # Train
    print("\nStarting training...")
    start_time = time.time()
    
    try:
        model.learn(
            total_timesteps=total_timesteps,
            callback=callbacks,
            progress_bar=True
        )
    except KeyboardInterrupt:
        print("\nTraining interrupted by user")
    
    elapsed = time.time() - start_time
    print(f"\nTraining completed in {elapsed:.1f}s ({elapsed/60:.1f} min)")
    
    # Save final model
    final_model_path = os.path.join(save_dir, f"{algorithm.lower()}_batch_final.zip")
    model.save(final_model_path)
    print(f"Final model saved to: {final_model_path}")
    
    # Save training config
    config = {
        "algorithm": algorithm,
        "total_timesteps": total_timesteps,
        "n_envs": n_envs,
        "seed": seed,
        "party_level_range": party_level_range,
        "difficulties": difficulties or ["easy", "medium", "hard"],
        "training_time_seconds": elapsed,
        "timestamp": timestamp,
        "resumed_from": resume_from
    }
    config_path = os.path.join(save_dir, "training_config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    
    # Clean up
    envs.close()
    eval_env.close()
    
    return model, save_dir


def evaluate_batch_model(
    model_path: str,
    n_episodes: int = 100,
    seed: int = 12345,
    difficulties: list = None,
    verbose: int = 1
):
    """
    Evaluate a trained model on random scenarios.
    
    Args:
        model_path: Path to saved model
        n_episodes: Number of evaluation episodes
        seed: Random seed for evaluation
        difficulties: Difficulties to test
        verbose: Verbosity level
    """
    print("=" * 60)
    print("BATCH EVALUATION")
    print("=" * 60)
    print(f"Model: {model_path}")
    print(f"Episodes: {n_episodes}")
    print("=" * 60)
    
    # Load model
    if "ppo" in model_path.lower():
        model = PPO.load(model_path)
    else:
        model = DQN.load(model_path)
    
    # Create evaluation environment
    env = RandomizedCombatEnv(
        seed=seed,
        difficulties=difficulties or ["easy", "medium", "hard", "deadly"],
        max_steps=100
    )
    
    # Run evaluation
    results = {
        "total_reward": 0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "total_steps": 0,
        "by_difficulty": {}
    }
    
    for ep in range(n_episodes):
        obs, info = env.reset(seed=seed + ep)
        done = False
        ep_reward = 0
        ep_steps = 0
        
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, done, truncated, info = env.step(action)
            ep_reward += reward
            ep_steps += 1
            
            if truncated:
                done = True
        
        results["total_reward"] += ep_reward
        results["total_steps"] += ep_steps
        
        if info.get("enemy_won"):
            results["wins"] += 1
        elif info.get("party_won"):
            results["losses"] += 1
        else:
            results["draws"] += 1
        
        if verbose >= 2:
            print(f"Episode {ep + 1}: Reward={ep_reward:.2f}, Steps={ep_steps}")
    
    env.close()
    
    # Print summary
    print("\n" + "=" * 60)
    print("EVALUATION RESULTS")
    print("=" * 60)
    print(f"Episodes: {n_episodes}")
    print(f"Average Reward: {results['total_reward'] / n_episodes:.2f}")
    print(f"Average Steps: {results['total_steps'] / n_episodes:.1f}")
    print(f"Win Rate: {results['wins'] / n_episodes:.1%}")
    print(f"Loss Rate: {results['losses'] / n_episodes:.1%}")
    print(f"Draw Rate: {results['draws'] / n_episodes:.1%}")
    
    return results


# =============================================================================
# AUTO-FIND LATEST MODEL
# =============================================================================

def find_latest_model(models_dir: str = None, algorithm: str = "DQN") -> str | None:
    """
    Find the latest/best trained model automatically.
    
    Search order:
    1. Most recent batch folder's best/best_model.zip
    2. Most recent batch folder's *_final.zip
    3. Any .zip in most recent batch folder
    
    Returns path to model or None if not found.
    """
    if models_dir is None:
        models_dir = os.path.join(project_root, "data", "ai", "models")
    
    if not os.path.exists(models_dir):
        return None
    
    # Find all batch folders, sorted by name (timestamp) descending
    batch_folders = []
    for item in os.listdir(models_dir):
        item_path = os.path.join(models_dir, item)
        if os.path.isdir(item_path) and item.startswith("batch_"):
            batch_folders.append(item_path)
    
    if not batch_folders:
        return None
    
    # Sort by folder name (contains timestamp) - newest first
    batch_folders.sort(reverse=True)
    
    for folder in batch_folders:
        # Check for best model first
        best_model = os.path.join(folder, "best", "best_model.zip")
        if os.path.exists(best_model):
            return best_model
        
        # Check for final model
        alg_lower = algorithm.lower()
        final_model = os.path.join(folder, f"{alg_lower}_batch_final.zip")
        if os.path.exists(final_model):
            return final_model
        
        # Check for any .zip file
        for item in os.listdir(folder):
            if item.endswith(".zip"):
                return os.path.join(folder, item)
    
    return None


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Batch Training with Randomized Scenarios")
    parser.add_argument("--timesteps", type=int, default=100000, help="Total training timesteps")
    parser.add_argument("--envs", type=int, default=4, help="Number of parallel environments")
    parser.add_argument("--algorithm", type=str, default="DQN", choices=["DQN", "PPO"], help="RL algorithm")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--min-level", type=int, default=1, help="Minimum party level")
    parser.add_argument("--max-level", type=int, default=3, help="Maximum party level")
    parser.add_argument("--difficulties", type=str, nargs="+", default=["easy", "medium", "hard"],
                       help="Difficulties to sample from")
    parser.add_argument("--eval-freq", type=int, default=5000, help="Evaluation frequency")
    parser.add_argument("--eval-only", type=str, default=None, help="Path to model for evaluation only")
    parser.add_argument("--eval-episodes", type=int, default=100, help="Number of evaluation episodes")
    parser.add_argument("--resume", nargs="?", const="auto", default=None,
                       help="Continue from previous model. Use --resume for auto-detect or --resume PATH for specific model")
    parser.add_argument("--fresh", action="store_true", help="Force fresh training (ignore any existing models)")
    parser.add_argument("-v", "--verbose", type=int, default=1, help="Verbosity level")
    
    args = parser.parse_args()
    
    # Handle resume logic
    resume_path = None
    if args.resume and not args.fresh:
        if args.resume == "auto":
            # Auto-detect latest model
            resume_path = find_latest_model(algorithm=args.algorithm)
            if resume_path:
                print(f"Auto-detected latest model: {resume_path}")
            else:
                print("No previous model found. Starting fresh training.")
        else:
            # Use specified path
            resume_path = args.resume
            if not os.path.exists(resume_path):
                print(f"Warning: Specified model not found: {resume_path}")
                print("Starting fresh training instead.")
                resume_path = None
    
    if args.eval_only:
        # Evaluation mode
        evaluate_batch_model(
            model_path=args.eval_only,
            n_episodes=args.eval_episodes,
            seed=args.seed,
            difficulties=args.difficulties,
            verbose=args.verbose
        )
    else:
        # Training mode
        train_batch(
            total_timesteps=args.timesteps,
            n_envs=args.envs,
            algorithm=args.algorithm,
            seed=args.seed,
            party_level_range=(args.min_level, args.max_level),
            difficulties=args.difficulties,
            eval_freq=args.eval_freq,
            verbose=args.verbose,
            resume_from=resume_path
        )
