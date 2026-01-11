"""
Gym-like Combat Environment.

Provides a standard RL interface for training enemy tactics.
"""

import numpy as np
from typing import Dict, Tuple, Optional, Any
import copy

from sim.state import GameState, create_simple_scenario, state_to_ai_dict
from sim.mechanics import DiceRoller, party_simple_turn
from ai.schema import TOTAL_ACTIONS, END_TURN_ACTION, get_observation_size
from ai.featurize import featurize_state
from ai.actions import action_mask, apply_action


class CombatEnv:
    """
    Gym-like combat environment for RL training.
    
    The environment simulates combat from the perspective of enemies.
    Each step represents one enemy action.
    """
    
    def __init__(
        self,
        seed: int = None,
        scenario_config: Dict = None,
        max_steps: int = 100,
        party_policy: str = "simple"  # "simple" or "passive"
    ):
        """
        Initialize combat environment.
        
        Args:
            seed: Random seed for reproducibility
            scenario_config: Configuration for scenario generation
            max_steps: Maximum steps before truncation
            party_policy: How party members act ("simple" = attack nearest, "passive" = do nothing)
        """
        self.seed_value = seed
        self.scenario_config = scenario_config or {}
        self.max_steps = max_steps
        self.party_policy = party_policy
        
        # State
        self.state: Optional[GameState] = None
        self.roller: Optional[DiceRoller] = None
        self.current_enemy_idx: int = 0
        self.step_count: int = 0
        
        # Observation and action space info
        self.observation_size = get_observation_size()
        self.action_size = TOTAL_ACTIONS
    
    def reset(self, seed: int = None) -> Tuple[np.ndarray, Dict]:
        """
        Reset environment to initial state.
        
        Returns:
            (observation, info)
        """
        if seed is not None:
            self.seed_value = seed
        
        self.roller = DiceRoller(self.seed_value)
        self.step_count = 0
        
        # Create scenario
        num_party = self.scenario_config.get("num_party", 2)
        num_enemies = self.scenario_config.get("num_enemies", 2)
        grid_width = self.scenario_config.get("grid_width", 15)
        grid_height = self.scenario_config.get("grid_height", 15)
        
        self.state = create_simple_scenario(
            num_party=num_party,
            num_enemies=num_enemies,
            grid_width=grid_width,
            grid_height=grid_height
        )
        
        # Find first enemy in initiative
        self._advance_to_enemy_turn()
        
        obs = self._get_observation()
        info = self._get_info()
        
        return obs, info
    
    def step(self, action_index: int) -> Tuple[np.ndarray, float, bool, bool, Dict]:
        """
        Execute one action.
        
        Args:
            action_index: Index of action to take
            
        Returns:
            (observation, reward, done, truncated, info)
        """
        if self.state is None:
            raise RuntimeError("Environment not reset")
        
        self.step_count += 1
        
        # Convert state to dict format for AI modules
        state_dict = state_to_ai_dict(self.state)
        state_dict["action_economy"] = self.state.action_economy.to_dict()
        
        # Apply action
        next_state_dict, reward_components, done, info = apply_action(
            state_dict,
            self.current_enemy_idx,
            action_index,
            self.roller.rng
        )
        
        # Update state from dict
        self._update_state_from_dict(next_state_dict)
        
        # Calculate reward
        reward = self._calculate_reward(reward_components, done)
        
        # Check for end turn action or no actions left
        if action_index == END_TURN_ACTION or self._should_end_turn():
            self._end_current_turn()
        
        # Check if combat is over
        if self.state.is_combat_over():
            done = True
            winner = self.state.get_winner()
            if winner == "enemies":
                reward += 10.0  # Enemies win bonus
            else:
                reward -= 10.0  # Party wins penalty
        
        # Check truncation
        truncated = self.step_count >= self.max_steps
        
        # Get new observation
        obs = self._get_observation()
        info = self._get_info()
        info["reward_components"] = reward_components
        
        return obs, reward, done, truncated, info
    
    def _get_observation(self) -> np.ndarray:
        """Get current observation vector."""
        if self.state is None:
            return np.zeros(self.observation_size, dtype=np.float32)
        
        state_dict = state_to_ai_dict(self.state)
        return featurize_state(state_dict, self.current_enemy_idx)
    
    def _get_info(self) -> Dict:
        """Get info dict including action mask."""
        if self.state is None:
            return {"action_mask": np.zeros(self.action_size, dtype=bool)}
        
        state_dict = state_to_ai_dict(self.state)
        state_dict["action_economy"] = self.state.action_economy.to_dict()
        
        mask = action_mask(state_dict, self.current_enemy_idx)
        
        return {
            "action_mask": mask,
            "current_enemy_idx": self.current_enemy_idx,
            "round": self.state.round,
            "step_count": self.step_count,
        }
    
    def _calculate_reward(self, reward_components: Dict, done: bool) -> float:
        """Calculate total reward from components."""
        reward = 0.0
        
        # Damage dealt to party
        reward += reward_components.get("damage_dealt", 0) / 10.0
        
        # Kill bonus
        reward += reward_components.get("kills", 0) * 5.0
        
        # Damage taken (would need to track this)
        reward -= reward_components.get("damage_taken", 0) / 10.0
        
        # Step penalty
        reward += reward_components.get("step_penalty", -0.2)
        
        # Invalid action penalty
        if reward_components.get("invalid_action", False):
            reward -= 1.0
        
        return reward
    
    def _should_end_turn(self) -> bool:
        """Check if current turn should end."""
        ae = self.state.action_economy
        return not ae.standard and not ae.move
    
    def _end_current_turn(self) -> None:
        """End current turn and advance."""
        self.state.advance_turn()
        self._advance_to_enemy_turn()
    
    def _advance_to_enemy_turn(self) -> None:
        """Advance initiative until an enemy's turn."""
        max_iterations = len(self.state.initiative_order) * 2 + 1
        
        for _ in range(max_iterations):
            if self.state.is_combat_over():
                break
            
            current = self.state.get_current_actor()
            if current is None:
                break
            
            if current["kind"] == "enemy":
                self.current_enemy_idx = current["idx"]
                # Reset action economy for new turn
                self.state.action_economy.reset()
                break
            else:
                # Party member turn - execute simple policy
                if self.party_policy == "simple":
                    party_idx = current["idx"]
                    party_simple_turn(self.state, party_idx, self.roller)
                
                self.state.advance_turn()
    
    def _update_state_from_dict(self, state_dict: Dict) -> None:
        """Update internal state from dict."""
        # Update party HP
        for i, p_dict in enumerate(state_dict.get("party", [])):
            if i < len(self.state.party):
                self.state.party[i].hp = p_dict.get("hp", self.state.party[i].hp)
                if "pos" in p_dict:
                    self.state.party[i].pos.x = p_dict["pos"].get("x", 0)
                    self.state.party[i].pos.y = p_dict["pos"].get("y", 0)
        
        # Update enemy HP and positions
        for i, e_dict in enumerate(state_dict.get("enemies", [])):
            if i < len(self.state.enemies):
                self.state.enemies[i].hp = e_dict.get("hp", self.state.enemies[i].hp)
                if "pos" in e_dict:
                    self.state.enemies[i].pos.x = e_dict["pos"].get("x", 0)
                    self.state.enemies[i].pos.y = e_dict["pos"].get("y", 0)
        
        # Update action economy
        ae_dict = state_dict.get("action_economy", {})
        self.state.action_economy.standard = ae_dict.get("standard", True)
        self.state.action_economy.move = ae_dict.get("move", True)
        self.state.action_economy.bonus = ae_dict.get("bonus", False)
        self.state.action_economy.reaction = ae_dict.get("reaction", True)
    
    def render_text(self) -> str:
        """Render current state as text for debugging."""
        if self.state is None:
            return "Environment not reset"
        
        lines = []
        lines.append(f"=== Round {self.state.round} ===")
        lines.append(f"Current enemy: {self.current_enemy_idx}")
        lines.append("")
        
        lines.append("Party:")
        for i, p in enumerate(self.state.party):
            status = "ALIVE" if p.hp > 0 else "DOWN"
            lines.append(f"  {p.name}: HP {p.hp}/{p.max_hp} at ({p.pos.x},{p.pos.y}) [{status}]")
        
        lines.append("")
        lines.append("Enemies:")
        for i, e in enumerate(self.state.enemies):
            status = "ALIVE" if e.hp > 0 else "DOWN"
            marker = " <--" if i == self.current_enemy_idx else ""
            lines.append(f"  {e.name}: HP {e.hp}/{e.max_hp} at ({e.pos.x},{e.pos.y}) [{status}]{marker}")
        
        lines.append("")
        ae = self.state.action_economy
        lines.append(f"Actions: Standard={ae.standard}, Move={ae.move}")
        
        return "\n".join(lines)


# Gymnasium wrapper for compatibility with stable-baselines3
try:
    import gymnasium as gym
    from gymnasium import spaces
    
    class CombatGymEnv(gym.Env):
        """Gymnasium-compatible wrapper for CombatEnv."""
        
        metadata = {"render_modes": ["text"]}
        
        def __init__(
            self,
            seed: int = None,
            scenario_config: Dict = None,
            max_steps: int = 100,
            party_policy: str = "simple"
        ):
            super().__init__()
            
            self.env = CombatEnv(
                seed=seed,
                scenario_config=scenario_config,
                max_steps=max_steps,
                party_policy=party_policy
            )
            
            self.observation_space = spaces.Box(
                low=-1.0,
                high=1.0,
                shape=(self.env.observation_size,),
                dtype=np.float32
            )
            
            self.action_space = spaces.Discrete(self.env.action_size)
        
        def reset(self, seed=None, options=None):
            obs, info = self.env.reset(seed=seed)
            return obs, info
        
        def step(self, action):
            return self.env.step(action)
        
        def render(self):
            return self.env.render_text()
        
        def get_action_mask(self) -> np.ndarray:
            """Get current action mask for masked action selection."""
            info = self.env._get_info()
            return info.get("action_mask", np.ones(self.env.action_size, dtype=bool))

except ImportError:
    # Gymnasium not installed - that's fine for UI usage
    CombatGymEnv = None
