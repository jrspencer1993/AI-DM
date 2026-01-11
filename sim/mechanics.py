"""
Deterministic Combat Mechanics.

Provides dice rolling, damage calculation, and movement validation
with injectable RNG for reproducibility.
"""

import numpy as np
from typing import Dict, List, Tuple, Optional
import re
import heapq

from sim.state import GameState, Actor, Position, GridCell


# Tile definitions
TILES = {
    "open": {"move_cost": 1, "blocked": False},
    "wall": {"move_cost": 999, "blocked": True},
    "difficult": {"move_cost": 2, "blocked": False},
    "water": {"move_cost": 999, "blocked": True},
}


class DiceRoller:
    """Deterministic dice roller with injectable RNG."""
    
    def __init__(self, seed: int = None):
        self.rng = np.random.default_rng(seed)
    
    def roll(self, num_dice: int, die_size: int) -> int:
        """Roll multiple dice."""
        return sum(self.rng.integers(1, die_size + 1) for _ in range(num_dice))
    
    def d20(self) -> int:
        """Roll a d20."""
        return int(self.rng.integers(1, 21))
    
    def parse_and_roll(self, dice_str: str, crit: bool = False) -> int:
        """Parse dice string and roll."""
        if not dice_str:
            return 0
        
        match = re.match(r"(\d+)d(\d+)(?:([+\-])(\d+))?", str(dice_str).replace(" ", ""))
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
            
            total = self.roll(num_dice, die_size)
            return max(0, total + modifier)
        
        try:
            return int(dice_str)
        except:
            return self.roll(1, 6)


def get_tile_info(state: GameState, x: int, y: int) -> Dict:
    """Get tile information at position."""
    if x < 0 or x >= state.grid.width or y < 0 or y >= state.grid.height:
        return TILES["wall"]
    
    cell = state.grid.cells[y][x]
    return TILES.get(cell.tile, TILES["open"])


def is_blocked(state: GameState, x: int, y: int, exclude_actor: Actor = None) -> bool:
    """Check if position is blocked."""
    # Check bounds
    if x < 0 or x >= state.grid.width or y < 0 or y >= state.grid.height:
        return True
    
    # Check terrain
    tile_info = get_tile_info(state, x, y)
    if tile_info["blocked"]:
        return True
    
    # Check occupation
    for p in state.party:
        if p is not exclude_actor and p.pos.x == x and p.pos.y == y:
            return True
    
    for e in state.enemies:
        if e is not exclude_actor and e.pos.x == x and e.pos.y == y:
            return True
    
    return False


def get_distance(pos1: Position, pos2: Position) -> int:
    """Calculate Chebyshev distance."""
    return max(abs(pos1.x - pos2.x), abs(pos1.y - pos2.y))


def dijkstra_reachable(
    state: GameState,
    start: Position,
    max_cost: int,
    exclude_actor: Actor = None
) -> Dict[Tuple[int, int], int]:
    """
    Find all reachable cells from start position within max_cost.
    Returns dict of {(x, y): cost}.
    """
    pq = [(0, start.x, start.y)]
    visited = {}
    
    directions = [
        (-1, 0), (1, 0), (0, -1), (0, 1),
        (-1, -1), (-1, 1), (1, -1), (1, 1)
    ]
    
    while pq:
        cost, x, y = heapq.heappop(pq)
        
        if (x, y) in visited:
            continue
        visited[(x, y)] = cost
        
        for dx, dy in directions:
            nx, ny = x + dx, y + dy
            
            if (nx, ny) in visited:
                continue
            
            if is_blocked(state, nx, ny, exclude_actor):
                continue
            
            tile_info = get_tile_info(state, nx, ny)
            move_cost = tile_info["move_cost"]
            
            new_cost = cost + move_cost
            if new_cost <= max_cost:
                heapq.heappush(pq, (new_cost, nx, ny))
    
    return visited


def resolve_attack(
    attacker: Actor,
    target: Actor,
    attack: Dict,
    roller: DiceRoller
) -> Dict:
    """
    Resolve an attack roll.
    
    Returns result dict with: hit, damage, crit, details
    """
    to_hit = attack.get("to_hit", 0)
    target_ac = target.ac
    
    d20 = roller.d20()
    total = d20 + to_hit
    
    result = {
        "hit": False,
        "damage": 0,
        "crit": False,
        "crit_miss": False,
        "roll": d20,
        "total": total,
        "ac": target_ac,
    }
    
    if d20 == 1:
        result["crit_miss"] = True
        return result
    
    if d20 == 20:
        result["hit"] = True
        result["crit"] = True
    elif total >= target_ac:
        result["hit"] = True
    
    if result["hit"]:
        damage_str = attack.get("damage", "1d6")
        result["damage"] = roller.parse_and_roll(damage_str, crit=result["crit"])
    
    return result


def resolve_spell_attack(
    attacker: Actor,
    target: Actor,
    spell: Dict,
    roller: DiceRoller
) -> Dict:
    """Resolve a spell attack roll."""
    to_hit = spell.get("to_hit", 5)
    target_ac = target.ac
    
    d20 = roller.d20()
    total = d20 + to_hit
    
    result = {
        "hit": False,
        "damage": 0,
        "crit": False,
        "crit_miss": False,
        "roll": d20,
        "total": total,
        "ac": target_ac,
    }
    
    if d20 == 1:
        result["crit_miss"] = True
        return result
    
    if d20 == 20:
        result["hit"] = True
        result["crit"] = True
    elif total >= target_ac:
        result["hit"] = True
    
    if result["hit"]:
        damage_str = spell.get("damage", "1d6")
        result["damage"] = roller.parse_and_roll(damage_str, crit=result["crit"])
    
    return result


def resolve_spell_save(
    attacker: Actor,
    target: Actor,
    spell: Dict,
    roller: DiceRoller
) -> Dict:
    """Resolve a spell save."""
    dc = spell.get("dc", 13)
    save_stat = spell.get("save", "DEX")
    
    stat_val = target.abilities.get(save_stat, 10)
    save_mod = (stat_val - 10) // 2
    
    d20 = roller.d20()
    total = d20 + save_mod
    
    saved = total >= dc
    
    damage_str = spell.get("damage", "1d6")
    full_damage = roller.parse_and_roll(damage_str)
    
    if saved:
        damage = full_damage // 2
    else:
        damage = full_damage
    
    return {
        "saved": saved,
        "damage": damage,
        "roll": d20,
        "total": total,
        "dc": dc,
        "save_stat": save_stat,
    }


def apply_damage(target: Actor, damage: int) -> Dict:
    """Apply damage to target. Returns info about the damage."""
    old_hp = target.hp
    target.hp = max(0, old_hp - damage)
    
    return {
        "damage": damage,
        "old_hp": old_hp,
        "new_hp": target.hp,
        "downed": target.hp <= 0 and old_hp > 0,
    }


def resolve_ability(
    attacker: Actor,
    target: Actor,
    ability: Dict,
    roller: DiceRoller
) -> Dict:
    """
    Resolve a special ability (breath weapon, etc.).
    
    Abilities can be attack-type or save-type.
    """
    ability_type = ability.get("type", "save")
    
    result = {
        "ability_name": ability.get("name", "ability"),
        "ability_type": ability_type,
        "damage": 0,
        "condition_applied": None,
    }
    
    if ability_type == "attack":
        # Attack roll ability
        to_hit = ability.get("to_hit", 5)
        target_ac = target.ac
        
        d20 = roller.d20()
        total = d20 + to_hit
        
        result["roll"] = d20
        result["total"] = total
        result["ac"] = target_ac
        
        if d20 == 1:
            result["hit"] = False
            result["crit_miss"] = True
        elif d20 == 20 or total >= target_ac:
            result["hit"] = True
            result["crit"] = (d20 == 20)
            
            damage_str = ability.get("damage", "2d6")
            result["damage"] = roller.parse_and_roll(damage_str, crit=result["crit"])
        else:
            result["hit"] = False
    
    else:  # Save-based
        dc = ability.get("dc", 13)
        save_stat = ability.get("save", "DEX")
        
        stat_val = target.abilities.get(save_stat, 10)
        save_mod = (stat_val - 10) // 2
        
        d20 = roller.d20()
        total = d20 + save_mod
        
        result["dc"] = dc
        result["save_stat"] = save_stat
        result["roll"] = d20
        result["total"] = total
        result["saved"] = (total >= dc)
        
        damage_str = ability.get("damage", "")
        if damage_str:
            full_damage = roller.parse_and_roll(damage_str)
            if result["saved"]:
                result["damage"] = full_damage // 2
            else:
                result["damage"] = full_damage
        
        # Apply condition if failed save
        condition = ability.get("condition")
        if condition and not result["saved"]:
            if condition not in target.conditions:
                target.conditions.append(condition)
                result["condition_applied"] = condition
    
    return result


def check_ability_recharge(actor: Actor, ability_name: str, roller: DiceRoller) -> bool:
    """
    Check if a recharge ability recharges.
    
    Returns True if it recharged.
    """
    # Get recharge state
    recharge_state = getattr(actor, 'ability_recharge', {})
    if not isinstance(recharge_state, dict):
        recharge_state = {}
    
    # If already available, no need to recharge
    if recharge_state.get(ability_name, True):
        return True
    
    # Roll for recharge (typically 5-6 on d6)
    roll = roller.roll(1, 6)
    if roll >= 5:
        recharge_state[ability_name] = True
        actor.ability_recharge = recharge_state
        return True
    
    return False


def process_start_of_turn(actor: Actor, roller: DiceRoller) -> List[str]:
    """
    Process start-of-turn effects (recharge, regeneration, etc.).
    
    Returns list of effect messages.
    """
    messages = []
    
    # Check ability recharges
    recharge_state = getattr(actor, 'ability_recharge', {})
    if isinstance(recharge_state, dict):
        for ability_name, available in list(recharge_state.items()):
            if not available:
                if check_ability_recharge(actor, ability_name, roller):
                    messages.append(f"{ability_name} recharged!")
    
    # Check regeneration trait
    traits = getattr(actor, 'traits', '')
    if 'regeneration' in str(traits).lower():
        regen_amount = 10  # Default regeneration
        if actor.hp > 0 and actor.hp < actor.max_hp:
            old_hp = actor.hp
            actor.hp = min(actor.max_hp, actor.hp + regen_amount)
            messages.append(f"Regeneration heals {actor.hp - old_hp} HP")
    
    return messages


def party_simple_turn(state: GameState, party_idx: int, roller: DiceRoller) -> Dict:
    """
    Execute a simple party member turn (attack nearest enemy).
    
    Returns action result dict.
    """
    if party_idx >= len(state.party):
        return {"action": "none", "reason": "invalid_index"}
    
    party_member = state.party[party_idx]
    
    if party_member.hp <= 0:
        return {"action": "none", "reason": "unconscious"}
    
    # Find nearest alive enemy
    nearest_enemy = None
    nearest_dist = 999
    nearest_idx = -1
    
    for i, enemy in enumerate(state.enemies):
        if enemy.hp > 0:
            dist = get_distance(party_member.pos, enemy.pos)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_enemy = enemy
                nearest_idx = i
    
    if nearest_enemy is None:
        return {"action": "none", "reason": "no_targets"}
    
    # Get best attack
    attacks = party_member.attacks
    if not attacks:
        return {"action": "none", "reason": "no_attacks"}
    
    attack = attacks[0]
    attack_range = attack.get("range", 5)
    if isinstance(attack_range, str):
        match = re.search(r"(\d+)", attack_range)
        attack_range = int(match.group(1)) if match else 5
    range_squares = max(1, attack_range // state.grid.square_size_ft)
    
    # Move if needed
    moved = False
    if nearest_dist > range_squares:
        # Find position to move to
        max_move = party_member.speed_ft // state.grid.square_size_ft
        reachable = dijkstra_reachable(state, party_member.pos, max_move, party_member)
        
        best_pos = None
        best_dist = nearest_dist
        
        for (rx, ry), cost in reachable.items():
            if rx == party_member.pos.x and ry == party_member.pos.y:
                continue
            if is_blocked(state, rx, ry, party_member):
                continue
            
            new_dist = max(abs(rx - nearest_enemy.pos.x), abs(ry - nearest_enemy.pos.y))
            if new_dist < best_dist:
                best_dist = new_dist
                best_pos = (rx, ry)
        
        if best_pos:
            party_member.pos.x, party_member.pos.y = best_pos
            moved = True
            nearest_dist = best_dist
    
    # Attack if in range
    if nearest_dist <= range_squares:
        result = resolve_attack(party_member, nearest_enemy, attack, roller)
        
        if result["hit"]:
            dmg_info = apply_damage(nearest_enemy, result["damage"])
            return {
                "action": "attack",
                "moved": moved,
                "target_idx": nearest_idx,
                "attack_name": attack.get("name", "attack"),
                "hit": True,
                "damage": result["damage"],
                "crit": result["crit"],
                "target_downed": dmg_info["downed"],
            }
        else:
            return {
                "action": "attack",
                "moved": moved,
                "target_idx": nearest_idx,
                "attack_name": attack.get("name", "attack"),
                "hit": False,
                "crit_miss": result.get("crit_miss", False),
            }
    
    return {
        "action": "move_only",
        "moved": moved,
        "reason": "out_of_range",
    }
