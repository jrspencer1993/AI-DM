"""
Evaluation Script for Enemy Policies.

Compares trained RL policy against heuristic baseline.
"""

import os
import sys
import numpy as np
from typing import Dict, Callable

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from sim.env import CombatEnv
from sim.runner import run_n_episodes, heuristic_policy_wrapper, random_policy
from ai.schema import END_TURN_ACTION
from ai.actions import action_mask


def load_trained_policy(model_path: str = None):
    """
    Load trained DQN policy.
    
    Returns a policy function compatible with run_episode.
    """
    if model_path is None:
        model_path = os.path.join(project_root, "data", "ai", "models", "dqn_enemy_policy.zip")
    
    if not os.path.exists(model_path):
        print(f"Warning: Model not found at {model_path}")
        return None
    
    try:
        from stable_baselines3 import DQN
        model = DQN.load(model_path)
        
        def trained_policy(state_dict: Dict, enemy_idx: int, rng: np.random.Generator) -> int:
            """Policy function using trained model."""
            from ai.featurize import featurize_state
            
            obs = featurize_state(state_dict, enemy_idx)
            
            # Get action mask
            mask = action_mask(state_dict, enemy_idx)
            
            # Get Q-values and mask invalid actions
            obs_tensor = model.policy.obs_to_tensor(obs.reshape(1, -1))[0]
            with model.policy.device:
                q_values = model.policy.q_net(obs_tensor)
            q_values = q_values.cpu().numpy().flatten()
            
            # Mask invalid actions
            q_values[~mask] = -1e9
            
            # Select best valid action
            action = int(np.argmax(q_values))
            
            return action
        
        return trained_policy
        
    except ImportError:
        print("Warning: stable-baselines3 not installed, cannot load trained model")
        return None
    except Exception as e:
        print(f"Warning: Failed to load model: {e}")
        return None


def evaluate_policies(
    policies: Dict[str, Callable],
    n_episodes: int = 50,
    seed: int = 42,
    scenario_config: Dict = None,
    verbose: bool = False
) -> Dict[str, Dict]:
    """
    Evaluate multiple policies.
    
    Args:
        policies: Dict of policy_name -> policy_fn
        n_episodes: Episodes per policy
        seed: Base random seed
        scenario_config: Scenario configuration
        verbose: Print per-episode details
        
    Returns:
        Dict of policy_name -> results
    """
    if scenario_config is None:
        scenario_config = {
            "num_party": 2,
            "num_enemies": 2,
            "grid_width": 15,
            "grid_height": 15,
        }
    
    results = {}
    
    for name, policy_fn in policies.items():
        print(f"\nEvaluating: {name}")
        print("-" * 40)
        
        env = CombatEnv(
            seed=seed,
            scenario_config=scenario_config,
            max_steps=100,
            party_policy="simple"
        )
        
        policy_results = run_n_episodes(
            env=env,
            policy_fn=policy_fn,
            n_episodes=n_episodes,
            base_seed=seed,
            verbose=verbose
        )
        
        results[name] = policy_results
        
        print(f"  Average Reward: {policy_results['avg_reward']:.2f} ± {policy_results['std_reward']:.2f}")
        print(f"  Average Steps: {policy_results['avg_steps']:.1f}")
        print(f"  Average Damage Dealt: {policy_results['avg_damage_dealt']:.1f}")
        print(f"  Average Kills: {policy_results['avg_kills']:.2f}")
        print(f"  Invalid Actions: {policy_results['avg_invalid_actions']:.2f}")
        print(f"  Enemy Win Rate: {policy_results['enemy_win_rate']*100:.1f}%")
        print(f"  Party Win Rate: {policy_results['party_win_rate']*100:.1f}%")
    
    return results


def print_comparison(results: Dict[str, Dict]):
    """Print comparison table."""
    print("\n" + "=" * 80)
    print("POLICY COMPARISON")
    print("=" * 80)
    
    # Header
    print(f"{'Policy':<20} {'Reward':>12} {'Win Rate':>12} {'Damage':>12} {'Steps':>10}")
    print("-" * 80)
    
    for name, r in results.items():
        reward = f"{r['avg_reward']:.2f}±{r['std_reward']:.2f}"
        win_rate = f"{r['enemy_win_rate']*100:.1f}%"
        damage = f"{r['avg_damage_dealt']:.1f}"
        steps = f"{r['avg_steps']:.1f}"
        
        print(f"{name:<20} {reward:>12} {win_rate:>12} {damage:>12} {steps:>10}")
    
    print("=" * 80)
    
    # Find best
    best_name = max(results.keys(), key=lambda k: results[k]['avg_reward'])
    print(f"\nBest policy by reward: {best_name}")
    
    best_win_name = max(results.keys(), key=lambda k: results[k]['enemy_win_rate'])
    print(f"Best policy by win rate: {best_win_name}")


def main():
    """Main evaluation entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Evaluate enemy policies")
    parser.add_argument("--episodes", type=int, default=50, help="Episodes per policy")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--model", type=str, default=None, help="Path to trained model")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Enemy Policy Evaluation")
    print("=" * 60)
    
    # Build policy dict
    policies = {
        "Heuristic": heuristic_policy_wrapper,
        "Random": random_policy,
    }
    
    # Try to load trained model
    trained = load_trained_policy(args.model)
    if trained is not None:
        policies["Trained DQN"] = trained
    
    # Run evaluation
    results = evaluate_policies(
        policies=policies,
        n_episodes=args.episodes,
        seed=args.seed,
        verbose=args.verbose
    )
    
    # Print comparison
    print_comparison(results)
    
    print("\nEvaluation complete!")


if __name__ == "__main__":
    main()
