"""
Heuristic Policy for Enemy AI.

Improved non-RL enemy policy that considers attacks, spells, abilities, and traits.
This policy can be used as a baseline for RL training comparison.
"""

import numpy as np
from typing import Dict, List, Any, Tuple, Optional
import json
import os
import re

from ai.schema import (
    MAX_TARGETS, MAX_ATTACKS, MAX_SPELLS, LOCAL_GRID_RADIUS,
    ACTION_MOVE, ACTION_ATTACK, ACTION_SPELL_ATTACK, ACTION_SPELL_SAVE,
    ACTION_DODGE, ACTION_END_TURN, ActionSpec, spec_to_action_index
)
from ai.actions import (
    get_sorted_targets, get_attack_range_squares, enumerate_valid_moves,
    action_mask, is_cell_blocked
)
from ai.featurize import get_grid_distance, parse_damage_dice


# Load trait and ability catalogs
def load_catalog(name: str) -> Dict:
    """Load a catalog JSON file."""
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    catalog_path = os.path.join(base_path, "data", "ai", f"{name}.json")
    
    if os.path.exists(catalog_path):
        with open(catalog_path, "r") as f:
            return json.load(f)
    return {}


TRAITS_CATALOG = None
ABILITY_CATALOG = None


def get_traits_catalog() -> Dict:
    global TRAITS_CATALOG
    if TRAITS_CATALOG is None:
        TRAITS_CATALOG = load_catalog("traits_catalog")
    return TRAITS_CATALOG


def get_ability_catalog() -> Dict:
    global ABILITY_CATALOG
    if ABILITY_CATALOG is None:
        ABILITY_CATALOG = load_catalog("ability_catalog")
    return ABILITY_CATALOG


def estimate_attack_utility(
    attack: Dict,
    target: Dict,
    distance: int,
    square_size: int,
    enemy: Dict
) -> float:
    """
    Estimate utility of an attack against a target.
    
    Considers: expected damage, hit probability, range, target HP.
    """
    # Get attack stats
    to_hit = attack.get("to_hit", 0)
    damage_str = attack.get("damage", "1d6")
    avg_damage = parse_damage_dice(damage_str)
    attack_range = get_attack_range_squares(attack, square_size)
    
    # Check if in range
    if distance > attack_range:
        return 0.0
    
    # Estimate hit probability (simplified)
    target_ac = int(target.get("ac", 10))
    needed_roll = target_ac - to_hit
    hit_prob = max(0.05, min(0.95, (21 - needed_roll) / 20))
    
    # Expected damage
    expected_damage = avg_damage * hit_prob
    
    # Bonus for potentially killing target
    target_hp = int(target.get("hp", 10))
    if expected_damage >= target_hp:
        expected_damage *= 1.5  # Kill bonus
    
    # Slight preference for ranged attacks when far
    attack_type = attack.get("attack_type", "melee")
    if attack_type == "ranged" and distance > 2:
        expected_damage *= 1.1
    
    return expected_damage


def estimate_spell_utility(
    spell: Dict,
    target: Dict,
    distance: int,
    square_size: int,
    enemy: Dict
) -> float:
    """Estimate utility of a spell against a target."""
    spell_type = spell.get("type", "attack")
    damage_str = spell.get("damage", "")
    avg_damage = parse_damage_dice(damage_str) if damage_str else 0
    
    spell_range = spell.get("range", 30)
    if isinstance(spell_range, str):
        match = re.search(r"(\d+)", spell_range)
        spell_range = int(match.group(1)) if match else 30
    range_squares = max(1, spell_range // square_size)
    
    if distance > range_squares:
        return 0.0
    
    if spell_type == "attack":
        to_hit = spell.get("to_hit", 5)
        target_ac = int(target.get("ac", 10))
        needed_roll = target_ac - to_hit
        hit_prob = max(0.05, min(0.95, (21 - needed_roll) / 20))
        expected_damage = avg_damage * hit_prob
    else:
        # Save-based spell
        dc = spell.get("dc", 13)
        save_stat = spell.get("save", "DEX")
        abilities = target.get("abilities", {})
        stat_val = abilities.get(save_stat, 10)
        save_mod = (stat_val - 10) // 2
        
        # Probability of failing save
        needed_roll = dc - save_mod
        fail_prob = max(0.05, min(0.95, (needed_roll - 1) / 20))
        
        # Expected damage (full on fail, half on save)
        expected_damage = avg_damage * fail_prob + (avg_damage / 2) * (1 - fail_prob)
    
    # Bonus for potentially killing target
    target_hp = int(target.get("hp", 10))
    if expected_damage >= target_hp:
        expected_damage *= 1.5
    
    return expected_damage


def get_trait_modifiers(enemy: Dict) -> Dict:
    """Extract trait-based modifiers for decision making."""
    modifiers = {
        "prefer_ranged": False,
        "prefer_melee": False,
        "hit_and_run": False,
        "prefer_damage": False,
        "prefer_control": False,
        "reach_bonus": 0,
    }
    
    traits = enemy.get("traits", "")
    if isinstance(traits, str):
        traits_lower = traits.lower()
        
        # Check for common trait patterns
        if "skirmisher" in traits_lower or "nimble" in traits_lower:
            modifiers["hit_and_run"] = True
        if "brute" in traits_lower or "reckless" in traits_lower:
            modifiers["prefer_damage"] = True
        if "reach" in traits_lower:
            modifiers["reach_bonus"] = 1
    
    # Check against catalog
    catalog = get_traits_catalog()
    for trait_name, trait_info in catalog.items():
        if trait_name.lower() in str(traits).lower():
            for key, value in trait_info.get("modifiers", {}).items():
                if key in modifiers:
                    if isinstance(value, bool):
                        modifiers[key] = modifiers[key] or value
                    else:
                        modifiers[key] = modifiers[key] + value
    
    return modifiers


def heuristic_select_action(
    state: Dict,
    enemy_idx: int,
    rng: np.random.Generator = None
) -> int:
    """
    Select best action using heuristic policy.
    
    Returns action index from the discrete action space.
    """
    if rng is None:
        rng = np.random.default_rng()
    
    enemies = state.get("enemies", [])
    if enemy_idx >= len(enemies):
        from ai.schema import END_TURN_ACTION
        return END_TURN_ACTION
    
    enemy = enemies[enemy_idx]
    enemy_pos = enemy.get("pos", {"x": 0, "y": 0})
    
    grid = state.get("grid", {})
    square_size = grid.get("square_size_ft", 5)
    
    action_economy = state.get("action_economy", {})
    has_standard = action_economy.get("standard", True)
    has_move = action_economy.get("move", True)
    
    # Get valid action mask
    mask = action_mask(state, enemy_idx)
    
    # Get targets and options
    targets = get_sorted_targets(state, enemy_pos)
    attacks = enemy.get("attacks", [])[:MAX_ATTACKS]
    spells = enemy.get("spells", [])[:MAX_SPELLS]
    
    # Get trait modifiers
    trait_mods = get_trait_modifiers(enemy)
    
    # ==========================================================================
    # PHASE 1: Evaluate all attack/spell options
    # ==========================================================================
    best_attack_action = None
    best_attack_utility = 0.0
    
    if has_standard and targets:
        # Evaluate attacks
        for target_slot, (party_idx, target, dist) in enumerate(targets):
            for attack_slot, attack in enumerate(attacks):
                utility = estimate_attack_utility(attack, target, dist, square_size, enemy)
                
                # Apply trait modifiers
                attack_type = attack.get("attack_type", "melee")
                if trait_mods["prefer_melee"] and attack_type == "melee":
                    utility *= 1.2
                if trait_mods["prefer_ranged"] and attack_type == "ranged":
                    utility *= 1.2
                if trait_mods["prefer_damage"]:
                    utility *= 1.1
                
                if utility > best_attack_utility:
                    # Check if valid
                    from ai.schema import ATTACK_ACTION_START
                    action_idx = ATTACK_ACTION_START + target_slot * MAX_ATTACKS + attack_slot
                    if mask[action_idx]:
                        best_attack_utility = utility
                        best_attack_action = action_idx
        
        # Evaluate spell attacks
        for target_slot, (party_idx, target, dist) in enumerate(targets):
            for spell_slot, spell in enumerate(spells):
                if spell.get("type", "attack") == "attack":
                    utility = estimate_spell_utility(spell, target, dist, square_size, enemy)
                    
                    if utility > best_attack_utility:
                        from ai.schema import SPELL_ATTACK_ACTION_START
                        action_idx = SPELL_ATTACK_ACTION_START + target_slot * MAX_SPELLS + spell_slot
                        if mask[action_idx]:
                            best_attack_utility = utility
                            best_attack_action = action_idx
        
        # Evaluate spell saves
        for target_slot, (party_idx, target, dist) in enumerate(targets):
            for spell_slot, spell in enumerate(spells):
                if spell.get("type", "save") == "save":
                    utility = estimate_spell_utility(spell, target, dist, square_size, enemy)
                    
                    if trait_mods["prefer_control"]:
                        utility *= 1.2
                    
                    if utility > best_attack_utility:
                        from ai.schema import SPELL_SAVE_ACTION_START
                        action_idx = SPELL_SAVE_ACTION_START + target_slot * MAX_SPELLS + spell_slot
                        if mask[action_idx]:
                            best_attack_utility = utility
                            best_attack_action = action_idx
    
    # ==========================================================================
    # PHASE 2: If we have a good attack, use it
    # ==========================================================================
    if best_attack_action is not None and best_attack_utility > 0:
        return best_attack_action
    
    # ==========================================================================
    # PHASE 3: If no attack available, consider moving
    # ==========================================================================
    if has_move and targets:
        # Find best move to get in range of a target
        best_move_action = None
        best_move_score = -999
        
        valid_moves = enumerate_valid_moves(state, enemy_idx)
        ex, ey = enemy_pos.get("x", 0), enemy_pos.get("y", 0)
        
        # Find closest target
        closest_target = targets[0] if targets else None
        if closest_target:
            _, target, current_dist = closest_target
            target_pos = target.get("pos", {"x": 0, "y": 0})
            tx, ty = target_pos.get("x", 0), target_pos.get("y", 0)
            
            for dx, dy in valid_moves:
                new_x, new_y = ex + dx, ey + dy
                new_dist = max(abs(new_x - tx), abs(new_y - ty))
                
                # Score based on getting closer
                score = current_dist - new_dist
                
                # Hit-and-run: prefer staying at range
                if trait_mods["hit_and_run"] and not has_standard:
                    # If we've already attacked, move away
                    score = new_dist - current_dist
                
                if score > best_move_score:
                    best_move_score = score
                    from ai.schema import MOVE_ACTION_START
                    grid_size = 2 * LOCAL_GRID_RADIUS + 1
                    local_idx = (dy + LOCAL_GRID_RADIUS) * grid_size + (dx + LOCAL_GRID_RADIUS)
                    best_move_action = MOVE_ACTION_START + local_idx
        
        if best_move_action is not None and best_move_score > 0:
            return best_move_action
    
    # ==========================================================================
    # PHASE 4: Fallback to dodge or end turn
    # ==========================================================================
    from ai.schema import DODGE_ACTION, END_TURN_ACTION
    
    if has_standard and mask[DODGE_ACTION]:
        return DODGE_ACTION
    
    return END_TURN_ACTION


def heuristic_policy_full_turn(
    state: Dict,
    enemy_idx: int,
    rng: np.random.Generator = None,
    max_actions: int = 10
) -> List[int]:
    """
    Execute a full turn using heuristic policy.
    
    Returns list of action indices taken.
    """
    if rng is None:
        rng = np.random.default_rng()
    
    actions_taken = []
    current_state = state
    
    for _ in range(max_actions):
        action_idx = heuristic_select_action(current_state, enemy_idx, rng)
        actions_taken.append(action_idx)
        
        # Check if end turn
        from ai.schema import END_TURN_ACTION
        if action_idx == END_TURN_ACTION:
            break
        
        # Apply action to get next state
        from ai.actions import apply_action
        next_state, _, done, info = apply_action(current_state, enemy_idx, action_idx, rng)
        current_state = next_state
        
        if done:
            break
        
        # Check if no more actions available
        action_economy = current_state.get("action_economy", {})
        if not action_economy.get("standard", False) and not action_economy.get("move", False):
            break
    
    return actions_taken
