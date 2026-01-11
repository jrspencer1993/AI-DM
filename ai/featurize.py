"""
Featurization: Convert game state to fixed-size numeric observation vector.

This module is completely independent of Streamlit.
"""

import numpy as np
from typing import Dict, List, Any, Optional
import re
import json
import os

from ai.schema import (
    ObservationSpec, CONDITION_NAMES, NUM_CONDITIONS, TRAIT_FLAG_NAMES, NUM_TRAIT_FLAGS,
    MAX_HP, MAX_AC, MAX_SPEED, MAX_GRID_DIM, MAX_ROUND,
    MAX_DISTANCE, MAX_DAMAGE, MAX_TO_HIT, MAX_DC,
    MAX_TARGETS, MAX_ATTACKS, MAX_SPELLS, MAX_ABILITIES,
    LOCAL_GRID_RADIUS, LOCAL_GRID_SIZE
)


def clamp(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    """Clamp value to range."""
    return max(min_val, min(max_val, value))


def scale(value: float, max_value: float, min_value: float = 0.0) -> float:
    """Scale value to [0, 1] range."""
    if max_value == min_value:
        return 0.0
    return clamp((value - min_value) / (max_value - min_value))


def parse_damage_dice(damage_str: str) -> float:
    """Parse damage dice string to average damage."""
    if not damage_str:
        return 0.0
    
    # Handle strings like "2d6+3", "1d8", "3d6-1"
    match = re.match(r"(\d+)d(\d+)(?:([+\-])(\d+))?", str(damage_str).replace(" ", ""))
    if match:
        num_dice = int(match.group(1))
        die_size = int(match.group(2))
        modifier = 0
        if match.group(3) and match.group(4):
            modifier = int(match.group(4))
            if match.group(3) == "-":
                modifier = -modifier
        return num_dice * (die_size + 1) / 2 + modifier
    
    # Try parsing as plain number
    try:
        return float(damage_str)
    except:
        return 3.5  # Default 1d6 average


def get_grid_distance(pos1: Dict, pos2: Dict) -> int:
    """Calculate Chebyshev distance between positions."""
    if not pos1 or not pos2:
        return 999
    dx = abs(pos1.get("x", 0) - pos2.get("x", 0))
    dy = abs(pos1.get("y", 0) - pos2.get("y", 0))
    return max(dx, dy)


def extract_trait_flags(enemy: Dict) -> List[bool]:
    """Extract trait flags from enemy traits string."""
    flags = [False] * NUM_TRAIT_FLAGS
    
    traits_str = enemy.get("traits", "")
    if not traits_str:
        return flags
    
    traits_lower = str(traits_str).lower()
    
    for i, trait_name in enumerate(TRAIT_FLAG_NAMES):
        # Check if trait name appears in traits string
        if trait_name.replace("_", " ") in traits_lower or trait_name in traits_lower:
            flags[i] = True
    
    return flags


def is_ability_available(ability: Dict, enemy: Dict) -> bool:
    """Check if an ability is available (not on cooldown, has uses)."""
    # Check recharge
    recharge = ability.get("recharge")
    if recharge:
        # Check if recharged
        recharge_state = enemy.get("ability_recharge", {})
        ability_name = ability.get("name", "")
        if not recharge_state.get(ability_name, True):
            return False
    
    # Check uses per day/rest
    uses = ability.get("uses")
    if uses is not None:
        uses_state = enemy.get("ability_uses", {})
        ability_name = ability.get("name", "")
        remaining = uses_state.get(ability_name, uses)
        if remaining <= 0:
            return False
    
    return True


def count_allies_adjacent_to_target(state: Dict, enemy_idx: int, target_pos: Dict) -> int:
    """Count enemy allies adjacent to target (for pack tactics)."""
    count = 0
    enemies = state.get("enemies", [])
    
    for i, other_enemy in enumerate(enemies):
        if i == enemy_idx:
            continue
        if int(other_enemy.get("hp", 0)) <= 0:
            continue
        
        other_pos = other_enemy.get("pos", {})
        dist = get_grid_distance(other_pos, target_pos)
        if dist <= 1:  # Adjacent
            count += 1
    
    return count


def featurize_state(
    state: Dict[str, Any],
    active_enemy_idx: int
) -> np.ndarray:
    """
    Convert game state to fixed-size observation vector.
    
    Args:
        state: Game state dict containing grid, party, enemies, combat info
        active_enemy_idx: Index of the enemy whose turn it is
        
    Returns:
        np.float32 array of size ObservationSpec.TOTAL_SIZE
    """
    obs = np.zeros(ObservationSpec.TOTAL_SIZE, dtype=np.float32)
    
    grid = state.get("grid", {})
    party = state.get("party", [])
    enemies = state.get("enemies", [])
    
    # Get active enemy
    if active_enemy_idx < 0 or active_enemy_idx >= len(enemies):
        return obs  # Return zeros if invalid
    
    enemy = enemies[active_enemy_idx]
    enemy_pos = enemy.get("pos", {"x": 0, "y": 0})
    
    square_size = grid.get("square_size_ft", 5)
    
    # ==========================================================================
    # A) GLOBAL STATE (4 values)
    # ==========================================================================
    idx = ObservationSpec.GLOBAL_START
    obs[idx] = scale(state.get("round", 1), MAX_ROUND)
    obs[idx + 1] = 1.0 if state.get("in_combat", False) else 0.0
    obs[idx + 2] = scale(grid.get("width", 20), MAX_GRID_DIM)
    obs[idx + 3] = scale(grid.get("height", 20), MAX_GRID_DIM)
    
    # ==========================================================================
    # B) ENEMY SELF STATE (30 values)
    # ==========================================================================
    idx = ObservationSpec.SELF_START
    
    # HP percentage
    max_hp = int(enemy.get("max_hp", enemy.get("hp", 10)))
    current_hp = int(enemy.get("hp", 10))
    obs[idx] = clamp(current_hp / max(1, max_hp))
    
    # AC (scaled)
    obs[idx + 1] = scale(int(enemy.get("ac", 10)), MAX_AC)
    
    # Speed (scaled)
    speed_ft = int(enemy.get("speed_ft", 30))
    obs[idx + 2] = scale(speed_ft, MAX_SPEED)
    
    # Position (scaled)
    obs[idx + 3] = scale(enemy_pos.get("x", 0), MAX_GRID_DIM)
    obs[idx + 4] = scale(enemy_pos.get("y", 0), MAX_GRID_DIM)
    
    # Action economy (4 flags)
    action_economy = state.get("action_economy", {})
    obs[idx + 5] = 1.0 if action_economy.get("standard", True) else 0.0
    obs[idx + 6] = 1.0 if action_economy.get("move", True) else 0.0
    obs[idx + 7] = 1.0 if action_economy.get("bonus", False) else 0.0
    obs[idx + 8] = 1.0 if action_economy.get("reaction", True) else 0.0
    
    # Movement remaining (scaled) - NEW
    movement_used = state.get("movement_used", 0)
    max_move = speed_ft // square_size
    movement_remaining = max(0, max_move - movement_used)
    obs[idx + 9] = scale(movement_remaining, max_move) if max_move > 0 else 0.0
    
    # Conditions (10 flags)
    conditions = enemy.get("conditions", [])
    if isinstance(conditions, str):
        conditions = [conditions]
    for i, cond_name in enumerate(CONDITION_NAMES):
        obs[idx + 10 + i] = 1.0 if cond_name in conditions else 0.0
    
    # Trait flags (10 flags) - EXPANDED
    trait_flags = extract_trait_flags(enemy)
    for i, flag in enumerate(trait_flags):
        obs[idx + 20 + i] = 1.0 if flag else 0.0
    
    # ==========================================================================
    # C) LOCAL TERRAIN (11x11 around enemy)
    # ==========================================================================
    idx = ObservationSpec.TERRAIN_START
    cells = grid.get("cells", [])
    grid_width = grid.get("width", 20)
    grid_height = grid.get("height", 20)
    
    TILES = {
        "open": {"move_cost": 1, "blocked": False},
        "wall": {"move_cost": 999, "blocked": True},
        "difficult": {"move_cost": 2, "blocked": False},
        "water": {"move_cost": 999, "blocked": True},
    }
    
    ex, ey = enemy_pos.get("x", 0), enemy_pos.get("y", 0)
    
    for local_y in range(-LOCAL_GRID_RADIUS, LOCAL_GRID_RADIUS + 1):
        for local_x in range(-LOCAL_GRID_RADIUS, LOCAL_GRID_RADIUS + 1):
            world_x = ex + local_x
            world_y = ey + local_y
            
            local_idx = (local_y + LOCAL_GRID_RADIUS) * (2 * LOCAL_GRID_RADIUS + 1) + (local_x + LOCAL_GRID_RADIUS)
            base_idx = idx + local_idx * ObservationSpec.TERRAIN_FEATURES_PER_CELL
            
            # Out of bounds = blocked
            if world_x < 0 or world_x >= grid_width or world_y < 0 or world_y >= grid_height:
                obs[base_idx] = 1.0      # blocked
                obs[base_idx + 1] = 1.0  # max move cost
                obs[base_idx + 2] = 0.0  # no hazard
            else:
                cell = cells[world_y][world_x] if world_y < len(cells) and world_x < len(cells[world_y]) else {"tile": "open"}
                if isinstance(cell, dict):
                    tile_type = cell.get("tile", "open")
                    hazard = cell.get("hazard")
                else:
                    tile_type = "open"
                    hazard = None
                
                tile_info = TILES.get(tile_type, TILES["open"])
                obs[base_idx] = 1.0 if tile_info["blocked"] else 0.0
                obs[base_idx + 1] = scale(tile_info["move_cost"], 999, 1)
                obs[base_idx + 2] = 1.0 if hazard else 0.0
    
    # ==========================================================================
    # D) TARGET SLOTS (up to 6 party members, 8 features each)
    # ==========================================================================
    idx = ObservationSpec.TARGETS_START
    
    # Get alive party members sorted by distance
    alive_party = []
    for i, p in enumerate(party):
        if int(p.get("hp", 0)) > 0:
            p_pos = p.get("pos", {"x": 0, "y": 0})
            dist = get_grid_distance(enemy_pos, p_pos)
            alive_party.append((i, p, dist))
    
    alive_party.sort(key=lambda x: x[2])  # Sort by distance
    
    # Get enemy's best melee range
    attacks = enemy.get("attacks", [])
    best_melee_range = 1
    for atk in attacks:
        atk_type = atk.get("attack_type", "melee")
        if atk_type == "melee" or atk_type == "both":
            atk_range = atk.get("range", 5)
            if isinstance(atk_range, str):
                match = re.search(r"(\d+)", atk_range)
                atk_range = int(match.group(1)) if match else 5
            range_squares = max(1, int(atk_range) // square_size)
            best_melee_range = max(best_melee_range, range_squares)
    
    # Movement budget
    max_move = speed_ft // square_size
    
    for slot in range(MAX_TARGETS):
        base_idx = idx + slot * ObservationSpec.TARGET_FEATURES
        
        if slot < len(alive_party):
            party_idx, target, dist = alive_party[slot]
            t_pos = target.get("pos", {"x": 0, "y": 0})
            
            # HP percentage
            t_max_hp = int(target.get("max_hp", target.get("hp", 10)))
            t_hp = int(target.get("hp", 10))
            obs[base_idx] = clamp(t_hp / max(1, t_max_hp))
            
            # AC (scaled)
            obs[base_idx + 1] = scale(int(target.get("ac", 10)), MAX_AC)
            
            # Distance (scaled)
            obs[base_idx + 2] = scale(dist, MAX_DISTANCE)
            
            # Reachable this turn (can move + attack)
            reachable = dist <= max_move + best_melee_range
            obs[base_idx + 3] = 1.0 if reachable else 0.0
            
            # In melee range now
            obs[base_idx + 4] = 1.0 if dist <= best_melee_range else 0.0
            
            # Expected damage estimate (best attack)
            best_dmg = 0.0
            for atk in attacks:
                avg_dmg = parse_damage_dice(atk.get("damage", "1d6"))
                best_dmg = max(best_dmg, avg_dmg)
            obs[base_idx + 5] = scale(best_dmg, MAX_DAMAGE)
            
            # Ally adjacent to target (for pack tactics) - NEW
            allies_adjacent = count_allies_adjacent_to_target(state, active_enemy_idx, t_pos)
            obs[base_idx + 6] = min(1.0, allies_adjacent / 3.0)  # Scale 0-3 allies
            
            # Threat level (based on target's damage potential) - NEW
            target_attacks = target.get("attacks", [])
            target_best_dmg = 0.0
            for tatk in target_attacks:
                tdmg = parse_damage_dice(tatk.get("damage", "1d6"))
                target_best_dmg = max(target_best_dmg, tdmg)
            obs[base_idx + 7] = scale(target_best_dmg, MAX_DAMAGE)
    
    # ==========================================================================
    # E) ATTACK OPTIONS (6 attacks, 4 features each)
    # ==========================================================================
    idx = ObservationSpec.ATTACKS_START
    
    for slot in range(MAX_ATTACKS):
        base_idx = idx + slot * ObservationSpec.ATTACK_FEATURES
        
        if slot < len(attacks):
            atk = attacks[slot]
            
            # Range (scaled)
            atk_range = atk.get("range", 5)
            if isinstance(atk_range, str):
                match = re.search(r"(\d+)", atk_range)
                atk_range = int(match.group(1)) if match else 5
            obs[base_idx] = scale(atk_range / square_size, MAX_DISTANCE)
            
            # Average damage (scaled)
            avg_dmg = parse_damage_dice(atk.get("damage", "1d6"))
            obs[base_idx + 1] = scale(avg_dmg, MAX_DAMAGE)
            
            # To-hit (scaled)
            to_hit = atk.get("to_hit", 0)
            obs[base_idx + 2] = scale(to_hit, MAX_TO_HIT, -5)
            
            # Is ranged (0 or 1) - NEW
            atk_type = atk.get("attack_type", "melee")
            obs[base_idx + 3] = 1.0 if atk_type == "ranged" else 0.0
    
    # ==========================================================================
    # F) SPELL OPTIONS (6 spells, 5 features each)
    # ==========================================================================
    idx = ObservationSpec.SPELLS_START
    
    spells = enemy.get("spells", [])
    
    for slot in range(MAX_SPELLS):
        base_idx = idx + slot * ObservationSpec.SPELL_FEATURES
        
        if slot < len(spells):
            spell = spells[slot]
            
            # Type (0 = attack, 1 = save)
            spell_type = spell.get("type", "attack")
            obs[base_idx] = 0.0 if spell_type == "attack" else 1.0
            
            # Range (scaled)
            spell_range = spell.get("range", 30)
            if isinstance(spell_range, str):
                match = re.search(r"(\d+)", spell_range)
                spell_range = int(match.group(1)) if match else 30
            obs[base_idx + 1] = scale(spell_range / square_size, MAX_DISTANCE)
            
            # Average damage (scaled)
            avg_dmg = parse_damage_dice(spell.get("damage", ""))
            obs[base_idx + 2] = scale(avg_dmg, MAX_DAMAGE)
            
            # DC or to-hit (scaled)
            if spell_type == "save":
                dc = spell.get("dc", 13)
                obs[base_idx + 3] = scale(dc, MAX_DC)
            else:
                to_hit = spell.get("to_hit", 5)
                obs[base_idx + 3] = scale(to_hit, MAX_TO_HIT, -5)
            
            # Is available (not on cooldown) - NEW
            obs[base_idx + 4] = 1.0  # Spells always available for now
    
    # ==========================================================================
    # G) ABILITY OPTIONS (6 abilities, 5 features each) - NEW
    # ==========================================================================
    idx = ObservationSpec.ABILITIES_START
    
    # Get abilities list (distinct from ability scores dict)
    enemy_abilities = enemy.get("special_abilities", enemy.get("abilities_list", []))
    if isinstance(enemy_abilities, dict):
        enemy_abilities = []  # Abilities dict is ability scores, not special abilities
    
    for slot in range(MAX_ABILITIES):
        base_idx = idx + slot * ObservationSpec.ABILITY_FEATURES
        
        if slot < len(enemy_abilities):
            ability = enemy_abilities[slot]
            
            # Type (0 = attack, 1 = save, 2 = utility)
            ability_type = ability.get("type", "attack")
            if ability_type == "attack":
                obs[base_idx] = 0.0
            elif ability_type == "save":
                obs[base_idx] = 0.5
            else:
                obs[base_idx] = 1.0
            
            # Range (scaled)
            ability_range = ability.get("range", 30)
            if isinstance(ability_range, str):
                match = re.search(r"(\d+)", ability_range)
                ability_range = int(match.group(1)) if match else 30
            obs[base_idx + 1] = scale(ability_range / square_size, MAX_DISTANCE)
            
            # Average damage (scaled)
            avg_dmg = parse_damage_dice(ability.get("damage", ""))
            obs[base_idx + 2] = scale(avg_dmg, MAX_DAMAGE)
            
            # DC (scaled)
            dc = ability.get("dc", 13)
            obs[base_idx + 3] = scale(dc, MAX_DC)
            
            # Is available (recharge ready, has uses)
            available = is_ability_available(ability, enemy)
            obs[base_idx + 4] = 1.0 if available else 0.0
    
    # ==========================================================================
    # H) ALLY AWARENESS (up to 4 allies, 3 features each) - NEW
    # ==========================================================================
    idx = ObservationSpec.ALLIES_START
    
    # Get other alive enemies sorted by distance
    allies = []
    for i, other_enemy in enumerate(enemies):
        if i == active_enemy_idx:
            continue
        if int(other_enemy.get("hp", 0)) > 0:
            other_pos = other_enemy.get("pos", {"x": 0, "y": 0})
            dist = get_grid_distance(enemy_pos, other_pos)
            allies.append((i, other_enemy, dist))
    
    allies.sort(key=lambda x: x[2])
    
    for slot in range(ObservationSpec.MAX_ALLIES):
        base_idx = idx + slot * ObservationSpec.ALLY_FEATURES
        
        if slot < len(allies):
            _, ally, dist = allies[slot]
            
            # Distance (scaled)
            obs[base_idx] = scale(dist, MAX_DISTANCE)
            
            # HP percentage
            ally_max_hp = int(ally.get("max_hp", ally.get("hp", 10)))
            ally_hp = int(ally.get("hp", 10))
            obs[base_idx + 1] = clamp(ally_hp / max(1, ally_max_hp))
            
            # Is alive
            obs[base_idx + 2] = 1.0
    
    return obs


def featurize_from_session_state(session_state: Dict[str, Any], active_enemy_idx: int) -> np.ndarray:
    """
    Create observation from Streamlit session_state format.
    
    This is a convenience wrapper that extracts relevant fields.
    """
    state = {
        "grid": session_state.get("grid", {}),
        "party": session_state.get("party", []),
        "enemies": session_state.get("enemies", []),
        "round": session_state.get("combat_round", 1),
        "in_combat": session_state.get("in_combat", False),
        "action_economy": session_state.get("action_economy", {}),
        "movement_used": session_state.get("movement_used", 0),
    }
    return featurize_state(state, active_enemy_idx)
