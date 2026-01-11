"""
Headless Episode Runner.

Run combat episodes without UI for evaluation and data collection.
"""

import numpy as np
from typing import Dict, List, Callable, Optional, Any
import time

from sim.env import CombatEnv
from sim.state import state_to_ai_dict
from ai.policy_heuristic import heuristic_select_action
from ai.logger import RolloutLogger
from ai.schema import END_TURN_ACTION, action_index_to_spec


def run_episode(
    env: CombatEnv,
    policy_fn: Callable[[Dict, int, np.random.Generator], int],
    seed: int = None,
    logger: RolloutLogger = None,
    verbose: bool = False
) -> Dict:
    """
    Run a single episode.
    
    Args:
        env: Combat environment
        policy_fn: Function that takes (state_dict, enemy_idx, rng) and returns action_index
        seed: Random seed
        logger: Optional rollout logger
        verbose: Print step details
        
    Returns:
        Episode statistics dict
    """
    obs, info = env.reset(seed=seed)
    
    if logger:
        logger.start_episode(seed=seed)
    
    total_reward = 0.0
    steps = 0
    damage_dealt = 0.0
    damage_taken = 0.0
    kills = 0
    invalid_actions = 0
    
    done = False
    truncated = False
    
    while not done and not truncated:
        # Get action from policy
        state_dict = state_to_ai_dict(env.state)
        state_dict["action_economy"] = env.state.action_economy.to_dict()
        
        action_idx = policy_fn(state_dict, env.current_enemy_idx, env.roller.rng)
        
        if verbose:
            spec = action_index_to_spec(action_idx)
            print(f"Step {steps}: Enemy {env.current_enemy_idx} -> Action {action_idx} ({spec.action_type})")
        
        # Take step
        next_obs, reward, done, truncated, step_info = env.step(action_idx)
        
        # Log
        if logger:
            logger.log_step(
                obs=obs,
                action_index=action_idx,
                action_dict=action_index_to_spec(action_idx).to_dict(),
                reward=reward,
                reward_components=step_info.get("reward_components", {}),
                done=done,
                truncated=truncated,
                info=step_info,
                next_obs=next_obs
            )
        
        # Accumulate stats
        total_reward += reward
        steps += 1
        
        rc = step_info.get("reward_components", {})
        damage_dealt += rc.get("damage_dealt", 0)
        damage_taken += rc.get("damage_taken", 0)
        kills += rc.get("kills", 0)
        if rc.get("invalid_action", False):
            invalid_actions += 1
        
        obs = next_obs
        
        if verbose and (done or truncated):
            print(f"Episode ended: done={done}, truncated={truncated}")
            print(env.render_text())
    
    if logger:
        logger.end_episode({
            "total_reward": total_reward,
            "steps": steps,
            "winner": env.state.get_winner() if env.state else None,
        })
    
    return {
        "total_reward": total_reward,
        "steps": steps,
        "damage_dealt": damage_dealt,
        "damage_taken": damage_taken,
        "kills": kills,
        "invalid_actions": invalid_actions,
        "winner": env.state.get_winner() if env.state else None,
        "done": done,
        "truncated": truncated,
    }


def run_n_episodes(
    env: CombatEnv,
    policy_fn: Callable,
    n_episodes: int = 10,
    base_seed: int = None,
    logger: RolloutLogger = None,
    verbose: bool = False
) -> Dict:
    """
    Run multiple episodes and aggregate statistics.
    
    Returns:
        Aggregated statistics dict
    """
    all_results = []
    
    for i in range(n_episodes):
        seed = base_seed + i if base_seed is not None else None
        
        if verbose:
            print(f"\n=== Episode {i+1}/{n_episodes} (seed={seed}) ===")
        
        result = run_episode(
            env=env,
            policy_fn=policy_fn,
            seed=seed,
            logger=logger,
            verbose=verbose
        )
        all_results.append(result)
    
    # Aggregate
    total_rewards = [r["total_reward"] for r in all_results]
    steps_list = [r["steps"] for r in all_results]
    damage_dealt_list = [r["damage_dealt"] for r in all_results]
    kills_list = [r["kills"] for r in all_results]
    invalid_list = [r["invalid_actions"] for r in all_results]
    
    enemy_wins = sum(1 for r in all_results if r["winner"] == "enemies")
    party_wins = sum(1 for r in all_results if r["winner"] == "party")
    
    return {
        "n_episodes": n_episodes,
        "avg_reward": np.mean(total_rewards),
        "std_reward": np.std(total_rewards),
        "avg_steps": np.mean(steps_list),
        "avg_damage_dealt": np.mean(damage_dealt_list),
        "avg_kills": np.mean(kills_list),
        "avg_invalid_actions": np.mean(invalid_list),
        "enemy_win_rate": enemy_wins / n_episodes,
        "party_win_rate": party_wins / n_episodes,
        "all_results": all_results,
    }


def heuristic_policy_wrapper(state_dict: Dict, enemy_idx: int, rng: np.random.Generator) -> int:
    """Wrapper for heuristic policy that matches the policy_fn signature."""
    return heuristic_select_action(state_dict, enemy_idx, rng)


def random_policy(state_dict: Dict, enemy_idx: int, rng: np.random.Generator) -> int:
    """Random policy that selects uniformly from valid actions."""
    from ai.actions import action_mask
    
    mask = action_mask(state_dict, enemy_idx)
    valid_actions = np.where(mask)[0]
    
    if len(valid_actions) == 0:
        return END_TURN_ACTION
    
    return int(rng.choice(valid_actions))


def main():
    """Run evaluation with heuristic policy."""
    print("=" * 60)
    print("Combat Simulation Runner")
    print("=" * 60)
    
    # Create environment
    env = CombatEnv(
        seed=42,
        scenario_config={
            "num_party": 2,
            "num_enemies": 2,
            "grid_width": 15,
            "grid_height": 15,
        },
        max_steps=100,
        party_policy="simple"
    )
    
    # Create logger
    logger = RolloutLogger(enabled=True)
    
    print("\nRunning 10 episodes with heuristic policy...")
    start_time = time.time()
    
    results = run_n_episodes(
        env=env,
        policy_fn=heuristic_policy_wrapper,
        n_episodes=10,
        base_seed=42,
        logger=logger,
        verbose=False
    )
    
    elapsed = time.time() - start_time
    
    print(f"\nResults ({elapsed:.2f}s):")
    print(f"  Average Reward: {results['avg_reward']:.2f} ± {results['std_reward']:.2f}")
    print(f"  Average Steps: {results['avg_steps']:.1f}")
    print(f"  Average Damage Dealt: {results['avg_damage_dealt']:.1f}")
    print(f"  Average Kills: {results['avg_kills']:.2f}")
    print(f"  Average Invalid Actions: {results['avg_invalid_actions']:.2f}")
    print(f"  Enemy Win Rate: {results['enemy_win_rate']*100:.1f}%")
    print(f"  Party Win Rate: {results['party_win_rate']*100:.1f}%")
    
    print("\n" + "=" * 60)
    print("Running 10 episodes with random policy for comparison...")
    
    random_results = run_n_episodes(
        env=env,
        policy_fn=random_policy,
        n_episodes=10,
        base_seed=42,
        verbose=False
    )
    
    print(f"\nRandom Policy Results:")
    print(f"  Average Reward: {random_results['avg_reward']:.2f} ± {random_results['std_reward']:.2f}")
    print(f"  Enemy Win Rate: {random_results['enemy_win_rate']*100:.1f}%")
    
    print("\n" + "=" * 60)
    print("Done!")


if __name__ == "__main__":
    main()
