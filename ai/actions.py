"""
Action Space: Enumerate, validate, and apply actions.

This module handles the discrete action space for RL training.
"""

import numpy as np
from typing import Dict, List, Any, Tuple, Optional
import re
import copy
import json
import os

from ai.schema import (
    MAX_TARGETS, MAX_ATTACKS, MAX_SPELLS, MAX_ABILITIES, LOCAL_GRID_RADIUS,
    TOTAL_ACTIONS, ACTION_MOVE, ACTION_ATTACK, ACTION_SPELL_ATTACK,
    ACTION_SPELL_SAVE, ACTION_ABILITY, ACTION_DODGE, ACTION_DASH, 
    ACTION_DISENGAGE, ACTION_END_TURN,
    action_index_to_spec, spec_to_action_index, ActionSpec,
    MOVE_ACTION_START, MOVE_ACTION_END, ATTACK_ACTION_START, ATTACK_ACTION_END,
    SPELL_ATTACK_ACTION_START, SPELL_ATTACK_ACTION_END,
    SPELL_SAVE_ACTION_START, SPELL_SAVE_ACTION_END,
    ABILITY_ACTION_START, ABILITY_ACTION_END,
    DODGE_ACTION, DASH_ACTION, DISENGAGE_ACTION, END_TURN_ACTION
)
from ai.featurize import get_grid_distance, parse_damage_dice, is_ability_available


# Tile definitions
TILES = {
    "open": {"move_cost": 1, "blocked": False},
    "wall": {"move_cost": 999, "blocked": True},
    "difficult": {"move_cost": 2, "blocked": False},
    "water": {"move_cost": 999, "blocked": True},
}


# Load ability catalog for resolution
_ability_catalog = None

def get_ability_catalog() -> Dict:
    """Load ability catalog."""
    global _ability_catalog
    if _ability_catalog is None:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        catalog_path = os.path.join(base_path, "data", "ai", "ability_catalog.json")
        if os.path.exists(catalog_path):
            with open(catalog_path, "r") as f:
                _ability_catalog = json.load(f)
        else:
            _ability_catalog = {}
    return _ability_catalog


def get_sorted_targets(state: Dict, enemy_pos: Dict) -> List[Tuple[int, Dict, int]]:
    """Get alive party members sorted by distance."""
    party = state.get("party", [])
    targets = []
    
    for i, p in enumerate(party):
        if int(p.get("hp", 0)) > 0:
            p_pos = p.get("pos", {"x": 0, "y": 0})
            dist = get_grid_distance(enemy_pos, p_pos)
            targets.append((i, p, dist))
    
    targets.sort(key=lambda x: x[2])
    return targets[:MAX_TARGETS]


def is_cell_blocked(state: Dict, x: int, y: int, exclude_enemy_idx: int = -1) -> bool:
    """Check if a cell is blocked (terrain or occupied)."""
    grid = state.get("grid", {})
    cells = grid.get("cells", [])
    width = grid.get("width", 20)
    height = grid.get("height", 20)
    
    # Out of bounds
    if x < 0 or x >= width or y < 0 or y >= height:
        return True
    
    # Check terrain
    if y < len(cells) and x < len(cells[y]):
        cell = cells[y][x]
        if isinstance(cell, dict):
            tile_type = cell.get("tile", "open")
        else:
            tile_type = "open"
        
        tile_info = TILES.get(tile_type, TILES["open"])
        if tile_info["blocked"]:
            return True
    
    # Check occupation by party
    for p in state.get("party", []):
        p_pos = p.get("pos")
        if p_pos and p_pos.get("x") == x and p_pos.get("y") == y:
            return True
    
    # Check occupation by other enemies
    for i, e in enumerate(state.get("enemies", [])):
        if i == exclude_enemy_idx:
            continue
        e_pos = e.get("pos")
        if e_pos and e_pos.get("x") == x and e_pos.get("y") == y:
            return True
    
    return False


def get_attack_range_squares(attack: Dict, square_size: int = 5) -> int:
    """Get attack range in grid squares."""
    range_ft = attack.get("range", 5)
    if isinstance(range_ft, str):
        match = re.search(r"(\d+)", range_ft)
        range_ft = int(match.group(1)) if match else 5
    return max(1, int(range_ft) // square_size)


def get_movement_budget(state: Dict, enemy: Dict) -> int:
    """Get remaining movement in squares."""
    grid = state.get("grid", {})
    speed_ft = int(enemy.get("speed_ft", 30))
    square_size = grid.get("square_size_ft", 5)
    max_move = speed_ft // square_size
    
    # Account for movement already used
    movement_used = state.get("movement_used", 0)
    return max(0, max_move - movement_used)


def enumerate_valid_moves(state: Dict, enemy_idx: int, dash: bool = False) -> List[Tuple[int, int]]:
    """Get list of valid move destinations (dx, dy offsets)."""
    enemies = state.get("enemies", [])
    if enemy_idx >= len(enemies):
        return []
    
    enemy = enemies[enemy_idx]
    enemy_pos = enemy.get("pos", {"x": 0, "y": 0})
    ex, ey = enemy_pos.get("x", 0), enemy_pos.get("y", 0)
    
    # Get movement budget
    max_move = get_movement_budget(state, enemy)
    if dash:
        max_move *= 2  # Dash doubles movement
    
    valid_moves = []
    
    for dy in range(-LOCAL_GRID_RADIUS, LOCAL_GRID_RADIUS + 1):
        for dx in range(-LOCAL_GRID_RADIUS, LOCAL_GRID_RADIUS + 1):
            if dx == 0 and dy == 0:
                continue  # Can't move to current position
            
            # Check if within movement range (Chebyshev distance)
            move_dist = max(abs(dx), abs(dy))
            if move_dist > max_move:
                continue
            
            # Check if destination is valid
            dest_x, dest_y = ex + dx, ey + dy
            if not is_cell_blocked(state, dest_x, dest_y, enemy_idx):
                valid_moves.append((dx, dy))
    
    return valid_moves


def action_mask(state: Dict, enemy_idx: int) -> np.ndarray:
    """
    Generate action mask for valid actions.
    
    Returns boolean array of size TOTAL_ACTIONS where True = valid action.
    """
    mask = np.zeros(TOTAL_ACTIONS, dtype=bool)
    
    enemies = state.get("enemies", [])
    if enemy_idx >= len(enemies):
        mask[END_TURN_ACTION] = True
        return mask
    
    enemy = enemies[enemy_idx]
    enemy_pos = enemy.get("pos", {"x": 0, "y": 0})
    
    grid = state.get("grid", {})
    square_size = grid.get("square_size_ft", 5)
    
    # Get action economy
    action_economy = state.get("action_economy", {})
    has_standard = action_economy.get("standard", True)
    has_move = action_economy.get("move", True)
    has_bonus = action_economy.get("bonus", False)
    
    # Get targets
    targets = get_sorted_targets(state, enemy_pos)
    
    # Get attacks, spells, and abilities
    attacks = enemy.get("attacks", [])[:MAX_ATTACKS]
    spells = enemy.get("spells", [])[:MAX_SPELLS]
    # Get special abilities (distinct from ability scores dict)
    abilities = enemy.get("special_abilities", enemy.get("abilities_list", []))
    if isinstance(abilities, dict):
        abilities = []
    abilities = abilities[:MAX_ABILITIES]
    
    # ==========================================================================
    # MOVE ACTIONS
    # ==========================================================================
    if has_move:
        valid_moves = enumerate_valid_moves(state, enemy_idx)
        for dx, dy in valid_moves:
            local_idx = (dy + LOCAL_GRID_RADIUS) * (2 * LOCAL_GRID_RADIUS + 1) + (dx + LOCAL_GRID_RADIUS)
            mask[MOVE_ACTION_START + local_idx] = True
    
    # ==========================================================================
    # ATTACK ACTIONS
    # ==========================================================================
    if has_standard and targets:
        for target_slot, (party_idx, target, dist) in enumerate(targets):
            for attack_slot, attack in enumerate(attacks):
                attack_range = get_attack_range_squares(attack, square_size)
                if dist <= attack_range:
                    action_idx = ATTACK_ACTION_START + target_slot * MAX_ATTACKS + attack_slot
                    mask[action_idx] = True
    
    # ==========================================================================
    # SPELL ATTACK ACTIONS
    # ==========================================================================
    if has_standard and targets:
        for target_slot, (party_idx, target, dist) in enumerate(targets):
            for spell_slot, spell in enumerate(spells):
                spell_type = spell.get("type", "attack")
                if spell_type == "attack":
                    spell_range = spell.get("range", 30)
                    if isinstance(spell_range, str):
                        match = re.search(r"(\d+)", spell_range)
                        spell_range = int(match.group(1)) if match else 30
                    range_squares = max(1, spell_range // square_size)
                    if dist <= range_squares:
                        action_idx = SPELL_ATTACK_ACTION_START + target_slot * MAX_SPELLS + spell_slot
                        mask[action_idx] = True
    
    # ==========================================================================
    # SPELL SAVE ACTIONS
    # ==========================================================================
    if has_standard and targets:
        for target_slot, (party_idx, target, dist) in enumerate(targets):
            for spell_slot, spell in enumerate(spells):
                spell_type = spell.get("type", "save")
                if spell_type == "save":
                    spell_range = spell.get("range", 30)
                    if isinstance(spell_range, str):
                        match = re.search(r"(\d+)", spell_range)
                        spell_range = int(match.group(1)) if match else 30
                    range_squares = max(1, spell_range // square_size)
                    if dist <= range_squares:
                        action_idx = SPELL_SAVE_ACTION_START + target_slot * MAX_SPELLS + spell_slot
                        mask[action_idx] = True
    
    # ==========================================================================
    # ABILITY ACTIONS (NEW)
    # ==========================================================================
    if has_standard and targets:
        for target_slot, (party_idx, target, dist) in enumerate(targets):
            for ability_slot, ability in enumerate(abilities):
                # Check if ability is available (recharge, uses)
                if not is_ability_available(ability, enemy):
                    continue
                
                ability_range = ability.get("range", 30)
                if isinstance(ability_range, str):
                    match = re.search(r"(\d+)", ability_range)
                    ability_range = int(match.group(1)) if match else 30
                range_squares = max(1, ability_range // square_size)
                
                if dist <= range_squares:
                    action_idx = ABILITY_ACTION_START + target_slot * MAX_ABILITIES + ability_slot
                    mask[action_idx] = True
    
    # ==========================================================================
    # DODGE ACTION
    # ==========================================================================
    if has_standard:
        mask[DODGE_ACTION] = True
    
    # ==========================================================================
    # DASH ACTION (NEW)
    # ==========================================================================
    if has_standard:
        # Dash uses standard action to double movement
        mask[DASH_ACTION] = True
    
    # ==========================================================================
    # DISENGAGE ACTION (NEW)
    # ==========================================================================
    if has_standard:
        mask[DISENGAGE_ACTION] = True
    
    # ==========================================================================
    # END TURN (always valid)
    # ==========================================================================
    mask[END_TURN_ACTION] = True
    
    return mask


def apply_action(
    state: Dict,
    enemy_idx: int,
    action_index: int,
    rng: np.random.Generator = None
) -> Tuple[Dict, Dict, bool, Dict]:
    """
    Apply an action and return the new state.
    
    Args:
        state: Current game state
        enemy_idx: Index of acting enemy
        action_index: Action to take
        rng: Random number generator for dice rolls
        
    Returns:
        (next_state, reward_components, done, info)
    """
    if rng is None:
        rng = np.random.default_rng()
    
    # Deep copy state
    next_state = copy.deepcopy(state)
    
    reward_components = {
        "damage_dealt": 0.0,
        "damage_taken": 0.0,
        "kills": 0,
        "invalid_action": False,
        "step_penalty": -0.2,
        "condition_applied": False,
    }
    
    info = {
        "action_type": "unknown",
        "action_valid": True,
        "action_details": {},
    }
    
    enemies = next_state.get("enemies", [])
    party = next_state.get("party", [])
    
    if enemy_idx >= len(enemies):
        reward_components["invalid_action"] = True
        info["action_valid"] = False
        return next_state, reward_components, False, info
    
    enemy = enemies[enemy_idx]
    enemy_pos = enemy.get("pos", {"x": 0, "y": 0})
    
    grid = next_state.get("grid", {})
    square_size = grid.get("square_size_ft", 5)
    
    action_economy = next_state.get("action_economy", {})
    
    # Get action spec
    spec = action_index_to_spec(action_index)
    
    # Get targets
    targets = get_sorted_targets(next_state, enemy_pos)
    attacks = enemy.get("attacks", [])[:MAX_ATTACKS]
    spells = enemy.get("spells", [])[:MAX_SPELLS]
    # Get special abilities (distinct from ability scores dict)
    abilities = enemy.get("special_abilities", enemy.get("abilities_list", []))
    if isinstance(abilities, dict):
        abilities = []
    abilities = abilities[:MAX_ABILITIES]
    
    # ==========================================================================
    # MOVE ACTION
    # ==========================================================================
    if spec.action_type == ACTION_MOVE:
        info["action_type"] = "move"
        dx, dy = spec.move_offset
        dest_x = enemy_pos.get("x", 0) + dx
        dest_y = enemy_pos.get("y", 0) + dy
        
        if not action_economy.get("move", True):
            reward_components["invalid_action"] = True
            info["action_valid"] = False
        elif is_cell_blocked(next_state, dest_x, dest_y, enemy_idx):
            reward_components["invalid_action"] = True
            info["action_valid"] = False
        else:
            enemy["pos"] = {"x": dest_x, "y": dest_y}
            # Track movement used
            move_dist = max(abs(dx), abs(dy))
            next_state["movement_used"] = next_state.get("movement_used", 0) + move_dist
            
            # Check if movement exhausted
            max_move = get_movement_budget(state, enemy)
            if next_state["movement_used"] >= max_move:
                action_economy["move"] = False
            
            info["action_details"] = {"from": enemy_pos, "to": enemy["pos"], "distance": move_dist}
    
    # ==========================================================================
    # ATTACK ACTION
    # ==========================================================================
    elif spec.action_type == ACTION_ATTACK:
        info["action_type"] = "attack"
        target_slot = spec.target_slot
        attack_slot = spec.attack_slot
        
        if not action_economy.get("standard", True):
            reward_components["invalid_action"] = True
            info["action_valid"] = False
        elif target_slot >= len(targets):
            reward_components["invalid_action"] = True
            info["action_valid"] = False
        elif attack_slot >= len(attacks):
            reward_components["invalid_action"] = True
            info["action_valid"] = False
        else:
            party_idx, target, dist = targets[target_slot]
            attack = attacks[attack_slot]
            attack_range = get_attack_range_squares(attack, square_size)
            
            if dist > attack_range:
                reward_components["invalid_action"] = True
                info["action_valid"] = False
            else:
                # Roll attack
                action_economy["standard"] = False
                to_hit = attack.get("to_hit", 0)
                target_ac = int(target.get("ac", 10))
                
                d20 = rng.integers(1, 21)
                total = d20 + to_hit
                
                info["action_details"] = {
                    "attack_name": attack.get("name", "attack"),
                    "target_name": target.get("name", "target"),
                    "roll": d20,
                    "total": total,
                    "ac": target_ac,
                }
                
                if d20 == 1:
                    info["action_details"]["result"] = "critical_miss"
                elif d20 == 20 or total >= target_ac:
                    damage_str = attack.get("damage", "1d6")
                    damage = roll_damage(damage_str, rng, crit=(d20 == 20))
                    
                    old_hp = int(party[party_idx].get("hp", 0))
                    new_hp = max(0, old_hp - damage)
                    party[party_idx]["hp"] = new_hp
                    
                    reward_components["damage_dealt"] = damage
                    
                    if new_hp <= 0 and old_hp > 0:
                        reward_components["kills"] = 1
                    
                    info["action_details"]["result"] = "hit"
                    info["action_details"]["damage"] = damage
                else:
                    info["action_details"]["result"] = "miss"
    
    # ==========================================================================
    # SPELL ATTACK ACTION
    # ==========================================================================
    elif spec.action_type == ACTION_SPELL_ATTACK:
        info["action_type"] = "spell_attack"
        target_slot = spec.target_slot
        spell_slot = spec.spell_slot
        
        if not action_economy.get("standard", True):
            reward_components["invalid_action"] = True
            info["action_valid"] = False
        elif target_slot >= len(targets):
            reward_components["invalid_action"] = True
            info["action_valid"] = False
        elif spell_slot >= len(spells):
            reward_components["invalid_action"] = True
            info["action_valid"] = False
        else:
            party_idx, target, dist = targets[target_slot]
            spell = spells[spell_slot]
            spell_range = spell.get("range", 30)
            if isinstance(spell_range, str):
                match = re.search(r"(\d+)", spell_range)
                spell_range = int(match.group(1)) if match else 30
            range_squares = max(1, spell_range // square_size)
            
            if dist > range_squares:
                reward_components["invalid_action"] = True
                info["action_valid"] = False
            else:
                action_economy["standard"] = False
                to_hit = spell.get("to_hit", 5)
                target_ac = int(target.get("ac", 10))
                
                d20 = rng.integers(1, 21)
                total = d20 + to_hit
                
                info["action_details"] = {
                    "spell_name": spell.get("name", "spell"),
                    "target_name": target.get("name", "target"),
                    "roll": d20,
                    "total": total,
                    "ac": target_ac,
                }
                
                if d20 == 1:
                    info["action_details"]["result"] = "critical_miss"
                elif d20 == 20 or total >= target_ac:
                    damage_str = spell.get("damage", "1d6")
                    damage = roll_damage(damage_str, rng, crit=(d20 == 20))
                    
                    old_hp = int(party[party_idx].get("hp", 0))
                    new_hp = max(0, old_hp - damage)
                    party[party_idx]["hp"] = new_hp
                    
                    reward_components["damage_dealt"] = damage
                    
                    if new_hp <= 0 and old_hp > 0:
                        reward_components["kills"] = 1
                    
                    info["action_details"]["result"] = "hit"
                    info["action_details"]["damage"] = damage
                else:
                    info["action_details"]["result"] = "miss"
    
    # ==========================================================================
    # SPELL SAVE ACTION
    # ==========================================================================
    elif spec.action_type == ACTION_SPELL_SAVE:
        info["action_type"] = "spell_save"
        target_slot = spec.target_slot
        spell_slot = spec.spell_slot
        
        if not action_economy.get("standard", True):
            reward_components["invalid_action"] = True
            info["action_valid"] = False
        elif target_slot >= len(targets):
            reward_components["invalid_action"] = True
            info["action_valid"] = False
        elif spell_slot >= len(spells):
            reward_components["invalid_action"] = True
            info["action_valid"] = False
        else:
            party_idx, target, dist = targets[target_slot]
            spell = spells[spell_slot]
            spell_range = spell.get("range", 30)
            if isinstance(spell_range, str):
                match = re.search(r"(\d+)", spell_range)
                spell_range = int(match.group(1)) if match else 30
            range_squares = max(1, spell_range // square_size)
            
            if dist > range_squares:
                reward_components["invalid_action"] = True
                info["action_valid"] = False
            else:
                action_economy["standard"] = False
                dc = spell.get("dc", 13)
                save_stat = spell.get("save", "DEX")
                
                abilities_dict = target.get("abilities", {})
                stat_val = abilities_dict.get(save_stat, 10)
                save_mod = (stat_val - 10) // 2
                
                d20 = rng.integers(1, 21)
                total = d20 + save_mod
                
                info["action_details"] = {
                    "spell_name": spell.get("name", "spell"),
                    "target_name": target.get("name", "target"),
                    "dc": dc,
                    "save": save_stat,
                    "roll": d20,
                    "total": total,
                }
                
                damage_str = spell.get("damage", "1d6")
                full_damage = roll_damage(damage_str, rng)
                
                if total >= dc:
                    damage = full_damage // 2
                    info["action_details"]["result"] = "saved"
                else:
                    damage = full_damage
                    info["action_details"]["result"] = "failed"
                
                old_hp = int(party[party_idx].get("hp", 0))
                new_hp = max(0, old_hp - damage)
                party[party_idx]["hp"] = new_hp
                
                reward_components["damage_dealt"] = damage
                
                if new_hp <= 0 and old_hp > 0:
                    reward_components["kills"] = 1
                
                info["action_details"]["damage"] = damage
    
    # ==========================================================================
    # ABILITY ACTION (NEW)
    # ==========================================================================
    elif spec.action_type == ACTION_ABILITY:
        info["action_type"] = "ability"
        target_slot = spec.target_slot
        ability_slot = spec.ability_slot
        
        if not action_economy.get("standard", True):
            reward_components["invalid_action"] = True
            info["action_valid"] = False
        elif target_slot >= len(targets):
            reward_components["invalid_action"] = True
            info["action_valid"] = False
        elif ability_slot >= len(abilities):
            reward_components["invalid_action"] = True
            info["action_valid"] = False
        else:
            party_idx, target, dist = targets[target_slot]
            ability = abilities[ability_slot]
            
            # Check availability
            if not is_ability_available(ability, enemy):
                reward_components["invalid_action"] = True
                info["action_valid"] = False
            else:
                ability_range = ability.get("range", 30)
                if isinstance(ability_range, str):
                    match = re.search(r"(\d+)", ability_range)
                    ability_range = int(match.group(1)) if match else 30
                range_squares = max(1, ability_range // square_size)
                
                if dist > range_squares:
                    reward_components["invalid_action"] = True
                    info["action_valid"] = False
                else:
                    action_economy["standard"] = False
                    
                    # Resolve ability based on type
                    ability_type = ability.get("type", "save")
                    
                    info["action_details"] = {
                        "ability_name": ability.get("name", "ability"),
                        "target_name": target.get("name", "target"),
                        "ability_type": ability_type,
                    }
                    
                    if ability_type == "attack":
                        # Attack roll ability
                        to_hit = ability.get("to_hit", 5)
                        target_ac = int(target.get("ac", 10))
                        
                        d20 = rng.integers(1, 21)
                        total = d20 + to_hit
                        
                        info["action_details"]["roll"] = d20
                        info["action_details"]["total"] = total
                        info["action_details"]["ac"] = target_ac
                        
                        if d20 == 1:
                            info["action_details"]["result"] = "critical_miss"
                        elif d20 == 20 or total >= target_ac:
                            damage_str = ability.get("damage", "2d6")
                            damage = roll_damage(damage_str, rng, crit=(d20 == 20))
                            
                            old_hp = int(party[party_idx].get("hp", 0))
                            new_hp = max(0, old_hp - damage)
                            party[party_idx]["hp"] = new_hp
                            
                            reward_components["damage_dealt"] = damage
                            
                            if new_hp <= 0 and old_hp > 0:
                                reward_components["kills"] = 1
                            
                            info["action_details"]["result"] = "hit"
                            info["action_details"]["damage"] = damage
                        else:
                            info["action_details"]["result"] = "miss"
                    
                    else:  # Save-based ability
                        dc = ability.get("dc", 13)
                        save_stat = ability.get("save", "DEX")
                        
                        abilities_dict = target.get("abilities", {})
                        stat_val = abilities_dict.get(save_stat, 10)
                        save_mod = (stat_val - 10) // 2
                        
                        d20 = rng.integers(1, 21)
                        total = d20 + save_mod
                        
                        info["action_details"]["dc"] = dc
                        info["action_details"]["save"] = save_stat
                        info["action_details"]["roll"] = d20
                        info["action_details"]["total"] = total
                        
                        damage_str = ability.get("damage", "")
                        if damage_str:
                            full_damage = roll_damage(damage_str, rng)
                            
                            if total >= dc:
                                damage = full_damage // 2
                                info["action_details"]["result"] = "saved"
                            else:
                                damage = full_damage
                                info["action_details"]["result"] = "failed"
                            
                            old_hp = int(party[party_idx].get("hp", 0))
                            new_hp = max(0, old_hp - damage)
                            party[party_idx]["hp"] = new_hp
                            
                            reward_components["damage_dealt"] = damage
                            
                            if new_hp <= 0 and old_hp > 0:
                                reward_components["kills"] = 1
                            
                            info["action_details"]["damage"] = damage
                        
                        # Apply condition if any
                        condition = ability.get("condition")
                        if condition and total < dc:
                            target_conditions = party[party_idx].get("conditions", [])
                            if isinstance(target_conditions, str):
                                target_conditions = [target_conditions]
                            if condition not in target_conditions:
                                target_conditions.append(condition)
                                party[party_idx]["conditions"] = target_conditions
                                reward_components["condition_applied"] = True
                                info["action_details"]["condition_applied"] = condition
                    
                    # Handle recharge
                    recharge = ability.get("recharge")
                    if recharge:
                        ability_name = ability.get("name", "")
                        recharge_state = enemy.get("ability_recharge", {})
                        recharge_state[ability_name] = False  # Now needs recharge
                        enemy["ability_recharge"] = recharge_state
                    
                    # Handle uses
                    uses = ability.get("uses")
                    if uses is not None:
                        ability_name = ability.get("name", "")
                        uses_state = enemy.get("ability_uses", {})
                        current_uses = uses_state.get(ability_name, uses)
                        uses_state[ability_name] = max(0, current_uses - 1)
                        enemy["ability_uses"] = uses_state
    
    # ==========================================================================
    # DODGE ACTION
    # ==========================================================================
    elif spec.action_type == ACTION_DODGE:
        info["action_type"] = "dodge"
        if not action_economy.get("standard", True):
            reward_components["invalid_action"] = True
            info["action_valid"] = False
        else:
            action_economy["standard"] = False
            enemy["dodging"] = True
            info["action_details"] = {"effect": "dodging until next turn"}
    
    # ==========================================================================
    # DASH ACTION (NEW)
    # ==========================================================================
    elif spec.action_type == ACTION_DASH:
        info["action_type"] = "dash"
        if not action_economy.get("standard", True):
            reward_components["invalid_action"] = True
            info["action_valid"] = False
        else:
            action_economy["standard"] = False
            enemy["dashing"] = True
            # Reset movement used to allow double movement
            next_state["movement_used"] = 0
            action_economy["move"] = True  # Re-enable move action
            info["action_details"] = {"effect": "can move again this turn"}
    
    # ==========================================================================
    # DISENGAGE ACTION (NEW)
    # ==========================================================================
    elif spec.action_type == ACTION_DISENGAGE:
        info["action_type"] = "disengage"
        if not action_economy.get("standard", True):
            reward_components["invalid_action"] = True
            info["action_valid"] = False
        else:
            action_economy["standard"] = False
            enemy["disengaging"] = True
            info["action_details"] = {"effect": "no opportunity attacks this turn"}
    
    # ==========================================================================
    # END TURN ACTION
    # ==========================================================================
    else:
        info["action_type"] = "end_turn"
    
    # Update action economy in state
    next_state["action_economy"] = action_economy
    
    # Check for combat end
    done = False
    
    party_alive = any(int(p.get("hp", 0)) > 0 for p in party)
    if not party_alive:
        done = True
        reward_components["combat_won"] = True
    
    enemies_alive = any(int(e.get("hp", 0)) > 0 for e in enemies)
    if not enemies_alive:
        done = True
        reward_components["combat_lost"] = True
    
    return next_state, reward_components, done, info


def roll_damage(damage_str: str, rng: np.random.Generator, crit: bool = False) -> int:
    """Roll damage dice."""
    if not damage_str:
        return 0
    
    match = re.match(r"(\d+)d(\d+)(?:([+\-])(\d+))?", str(damage_str).replace(" ", ""))
    if match:
        num_dice = int(match.group(1))
        die_size = int(match.group(2))
        modifier = 0
        if match.group(3) and match.group(4):
            modifier = int(match.group(4))
            if match.group(3) == "-":
                modifier = -modifier
        
        if crit:
            num_dice *= 2
        
        total = sum(rng.integers(1, die_size + 1) for _ in range(num_dice))
        return max(0, total + modifier)
    
    try:
        return int(damage_str)
    except:
        return rng.integers(1, 7)  # Default 1d6
