"""
DQN Training Script for Enemy Tactics.

This script trains a DQN agent to play as enemies in combat.
Requires: pip install -r requirements-train.txt
"""

import os
import sys
import numpy as np
from datetime import datetime

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

try:
    import gymnasium as gym
    from stable_baselines3 import DQN
    from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback
    from stable_baselines3.common.monitor import Monitor
except ImportError as e:
    print("Error: Training dependencies not installed.")
    print("Run: pip install -r train/requirements-train.txt")
    print(f"Missing: {e}")
    sys.exit(1)

from sim.env import CombatGymEnv


def make_env(seed: int = None, scenario_config: dict = None):
    """Create and wrap environment."""
    if CombatGymEnv is None:
        raise RuntimeError("Gymnasium not available")
    
    env = CombatGymEnv(
        seed=seed,
        scenario_config=scenario_config or {},
        max_steps=100,
        party_policy="simple"
    )
    return Monitor(env)


class MaskedDQN(DQN):
    """DQN with action masking support."""
    
    def predict(self, observation, state=None, episode_start=None, deterministic=False):
        """Override predict to apply action masking."""
        # Get Q-values
        obs_tensor = self.policy.obs_to_tensor(observation)[0]
        
        with self.policy.device:
            q_values = self.policy.q_net(obs_tensor)
        
        q_values = q_values.cpu().numpy()
        
        # Apply action mask if available
        if hasattr(self, '_current_mask') and self._current_mask is not None:
            # Set invalid actions to very negative value
            q_values[~self._current_mask] = -1e9
        
        if deterministic:
            action = np.argmax(q_values, axis=1)
        else:
            # Epsilon-greedy with masking
            if np.random.random() < self.exploration_rate:
                if hasattr(self, '_current_mask') and self._current_mask is not None:
                    valid_actions = np.where(self._current_mask)[0]
                    action = np.array([np.random.choice(valid_actions)])
                else:
                    action = np.array([self.action_space.sample()])
            else:
                action = np.argmax(q_values, axis=1)
        
        return action, state
    
    def set_action_mask(self, mask: np.ndarray):
        """Set current action mask."""
        self._current_mask = mask


def train(
    total_timesteps: int = 50000,
    seed: int = 42,
    scenario_config: dict = None,
    save_path: str = None,
    log_path: str = None
):
    """
    Train DQN agent.
    
    Args:
        total_timesteps: Total training steps
        seed: Random seed
        scenario_config: Scenario configuration
        save_path: Path to save model
        log_path: Path for tensorboard logs
    """
    print("=" * 60)
    print("DQN Training for Enemy Tactics")
    print("=" * 60)
    
    # Setup paths
    if save_path is None:
        save_path = os.path.join(project_root, "data", "ai", "models")
    os.makedirs(save_path, exist_ok=True)
    
    if log_path is None:
        log_path = os.path.join(project_root, "data", "ai", "logs")
    os.makedirs(log_path, exist_ok=True)
    
    # Default scenario
    if scenario_config is None:
        scenario_config = {
            "num_party": 2,
            "num_enemies": 2,
            "grid_width": 15,
            "grid_height": 15,
        }
    
    print(f"\nScenario: {scenario_config}")
    print(f"Total timesteps: {total_timesteps}")
    print(f"Seed: {seed}")
    
    # Create environments
    print("\nCreating environments...")
    train_env = make_env(seed=seed, scenario_config=scenario_config)
    eval_env = make_env(seed=seed + 1000, scenario_config=scenario_config)
    
    print(f"Observation space: {train_env.observation_space}")
    print(f"Action space: {train_env.action_space}")
    
    # Create model
    print("\nCreating DQN model...")
    model = DQN(
        "MlpPolicy",
        train_env,
        learning_rate=1e-4,
        buffer_size=50000,
        learning_starts=1000,
        batch_size=64,
        tau=0.005,
        gamma=0.99,
        train_freq=4,
        gradient_steps=1,
        target_update_interval=1000,
        exploration_fraction=0.3,
        exploration_initial_eps=1.0,
        exploration_final_eps=0.05,
        verbose=1,
        seed=seed,
        tensorboard_log=log_path,
    )
    
    # Callbacks
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    eval_callback = EvalCallback(
        eval_env,
        best_model_save_path=os.path.join(save_path, f"best_{timestamp}"),
        log_path=log_path,
        eval_freq=5000,
        n_eval_episodes=10,
        deterministic=True,
        render=False,
    )
    
    checkpoint_callback = CheckpointCallback(
        save_freq=10000,
        save_path=os.path.join(save_path, f"checkpoints_{timestamp}"),
        name_prefix="dqn_enemy",
    )
    
    # Train
    print("\nStarting training...")
    try:
        model.learn(
            total_timesteps=total_timesteps,
            callback=[eval_callback, checkpoint_callback],
            progress_bar=True,
        )
    except KeyboardInterrupt:
        print("\nTraining interrupted by user.")
    
    # Save final model
    final_path = os.path.join(save_path, f"dqn_enemy_policy_{timestamp}.zip")
    model.save(final_path)
    print(f"\nModel saved to: {final_path}")
    
    # Also save as latest
    latest_path = os.path.join(save_path, "dqn_enemy_policy.zip")
    model.save(latest_path)
    print(f"Latest model saved to: {latest_path}")
    
    # Cleanup
    train_env.close()
    eval_env.close()
    
    print("\n" + "=" * 60)
    print("Training complete!")
    print("=" * 60)
    
    return model


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Train DQN enemy policy")
    parser.add_argument("--timesteps", type=int, default=50000, help="Total training timesteps")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--party", type=int, default=2, help="Number of party members")
    parser.add_argument("--enemies", type=int, default=2, help="Number of enemies")
    
    args = parser.parse_args()
    
    scenario_config = {
        "num_party": args.party,
        "num_enemies": args.enemies,
        "grid_width": 15,
        "grid_height": 15,
    }
    
    train(
        total_timesteps=args.timesteps,
        seed=args.seed,
        scenario_config=scenario_config,
    )


if __name__ == "__main__":
    main()
