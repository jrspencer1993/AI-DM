"""
JSONL Rollout Logger for RL Training Data.

Logs state -> action -> reward -> next_state -> done transitions.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Any, Optional
import numpy as np


class RolloutLogger:
    """
    Logger for RL training rollouts in JSONL format.
    """
    
    def __init__(self, log_dir: str = None, enabled: bool = True):
        """
        Initialize rollout logger.
        
        Args:
            log_dir: Directory to write logs. Defaults to data/ai/rollout_logs/
            enabled: Whether logging is active
        """
        self.enabled = enabled
        
        if log_dir is None:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            log_dir = os.path.join(base_path, "data", "ai", "rollout_logs")
        
        self.log_dir = log_dir
        self.current_file = None
        self.current_episode_id = None
        self.step_idx = 0
        self.seed = None
        
        # Ensure log directory exists
        if self.enabled:
            os.makedirs(self.log_dir, exist_ok=True)
    
    def start_episode(self, seed: int = None, episode_id: str = None):
        """Start a new episode."""
        if not self.enabled:
            return
        
        self.seed = seed
        self.step_idx = 0
        
        if episode_id is None:
            episode_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.current_episode_id = episode_id
        
        # Create new log file for this session
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"rollout_{timestamp}.jsonl"
        self.current_file = os.path.join(self.log_dir, filename)
    
    def log_step(
        self,
        obs: np.ndarray,
        action_index: int,
        action_dict: Dict,
        reward: float,
        reward_components: Dict,
        done: bool,
        truncated: bool,
        info: Dict,
        next_obs: np.ndarray = None
    ):
        """
        Log a single step.
        
        Args:
            obs: Observation vector before action
            action_index: Action taken (index)
            action_dict: Action details
            reward: Total reward
            reward_components: Breakdown of reward
            done: Episode done flag
            truncated: Episode truncated flag
            info: Additional info
            next_obs: Observation after action (optional)
        """
        if not self.enabled or self.current_file is None:
            return
        
        def convert_numpy(obj):
            """Convert numpy types to Python native types for JSON serialization."""
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, (np.integer, np.int64, np.int32)):
                return int(obj)
            elif isinstance(obj, (np.floating, np.float64, np.float32)):
                return float(obj)
            elif isinstance(obj, np.bool_):
                return bool(obj)
            elif isinstance(obj, dict):
                return {k: convert_numpy(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [convert_numpy(v) for v in obj]
            return obj
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "seed": convert_numpy(self.seed),
            "episode_id": self.current_episode_id,
            "step_idx": self.step_idx,
            "obs": obs.tolist() if isinstance(obs, np.ndarray) else obs,
            "action_index": int(action_index),
            "action_dict": convert_numpy(action_dict),
            "reward": float(reward),
            "reward_components": convert_numpy(reward_components),
            "done": bool(done),
            "truncated": bool(truncated),
            "info": {
                "action_type": info.get("action_type"),
                "action_valid": info.get("action_valid"),
            },
        }
        
        if next_obs is not None:
            entry["next_obs"] = next_obs.tolist() if isinstance(next_obs, np.ndarray) else next_obs
        
        # Write to file
        try:
            with open(self.current_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"Warning: Failed to write log entry: {e}")
        
        self.step_idx += 1
    
    def end_episode(self, final_info: Dict = None):
        """End current episode."""
        if not self.enabled:
            return
        
        if final_info and self.current_file:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "episode_id": self.current_episode_id,
                "type": "episode_end",
                "total_steps": self.step_idx,
                "final_info": final_info,
            }
            
            try:
                with open(self.current_file, "a") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception as e:
                print(f"Warning: Failed to write episode end: {e}")
        
        self.current_episode_id = None
        self.step_idx = 0
    
    def log_ui_decision(
        self,
        enemy_name: str,
        enemy_idx: int,
        state_snapshot: Dict,
        action_chosen: Dict,
        outcome: Dict
    ):
        """
        Log a decision made in the UI (for AI telemetry).
        
        This is a simplified log format for UI usage.
        """
        if not self.enabled:
            return
        
        # Ensure we have a file
        if self.current_file is None:
            self.start_episode()
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "ui_decision",
            "enemy_name": enemy_name,
            "enemy_idx": enemy_idx,
            "state": {
                "round": state_snapshot.get("round", 1),
                "enemy_hp": state_snapshot.get("enemy_hp"),
                "enemy_pos": state_snapshot.get("enemy_pos"),
                "target_count": state_snapshot.get("target_count", 0),
                "nearest_target_dist": state_snapshot.get("nearest_target_dist"),
            },
            "action": action_chosen,
            "outcome": outcome,
        }
        
        try:
            with open(self.current_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"Warning: Failed to write UI decision log: {e}")


# Global logger instance for UI
_ui_logger = None


def get_ui_logger() -> RolloutLogger:
    """Get or create the global UI logger."""
    global _ui_logger
    if _ui_logger is None:
        _ui_logger = RolloutLogger(enabled=False)  # Disabled by default
    return _ui_logger


def set_ui_logging_enabled(enabled: bool):
    """Enable or disable UI logging."""
    logger = get_ui_logger()
    logger.enabled = enabled
    if enabled and logger.current_file is None:
        logger.start_episode()
