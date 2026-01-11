"""
Observation and Action Schema for RL Combat Environment.

Defines fixed-size numeric observation vectors and discrete action space.
"""

from dataclasses import dataclass
from typing import Dict, List, Any
import math

# =============================================================================
# ACTION SPACE CONSTANTS
# =============================================================================

MAX_TARGETS = 6          # Maximum party members to consider as targets
MAX_ATTACKS = 6          # Maximum attacks per enemy
MAX_SPELLS = 6           # Maximum spells per enemy
MAX_ABILITIES = 6        # Maximum special abilities per enemy
LOCAL_GRID_RADIUS = 5    # 5 => 11x11 local grid (121 tiles)
LOCAL_GRID_SIZE = (2 * LOCAL_GRID_RADIUS + 1) ** 2  # 121

# Action type IDs
ACTION_MOVE = 0
ACTION_ATTACK = 1
ACTION_SPELL_ATTACK = 2
ACTION_SPELL_SAVE = 3
ACTION_ABILITY = 4       # NEW: Special abilities (breath weapon, etc.)
ACTION_DODGE = 5
ACTION_DASH = 6          # NEW: Double movement
ACTION_DISENGAGE = 7     # NEW: No opportunity attacks
ACTION_END_TURN = 8

# Action space size calculation:
# - Move: LOCAL_GRID_SIZE (121)
# - Attack: MAX_TARGETS * MAX_ATTACKS (36)
# - Spell Attack: MAX_TARGETS * MAX_SPELLS (36)
# - Spell Save: MAX_TARGETS * MAX_SPELLS (36)
# - Ability: MAX_TARGETS * MAX_ABILITIES (36)
# - Dodge: 1
# - Dash: 1
# - Disengage: 1
# - End Turn: 1
# Total: 121 + 36 + 36 + 36 + 36 + 1 + 1 + 1 + 1 = 269

MOVE_ACTION_START = 0
MOVE_ACTION_END = LOCAL_GRID_SIZE  # 0-120

ATTACK_ACTION_START = MOVE_ACTION_END
ATTACK_ACTION_END = ATTACK_ACTION_START + MAX_TARGETS * MAX_ATTACKS  # 121-156

SPELL_ATTACK_ACTION_START = ATTACK_ACTION_END
SPELL_ATTACK_ACTION_END = SPELL_ATTACK_ACTION_START + MAX_TARGETS * MAX_SPELLS  # 157-192

SPELL_SAVE_ACTION_START = SPELL_ATTACK_ACTION_END
SPELL_SAVE_ACTION_END = SPELL_SAVE_ACTION_START + MAX_TARGETS * MAX_SPELLS  # 193-228

ABILITY_ACTION_START = SPELL_SAVE_ACTION_END
ABILITY_ACTION_END = ABILITY_ACTION_START + MAX_TARGETS * MAX_ABILITIES  # 229-264

DODGE_ACTION = ABILITY_ACTION_END      # 265
DASH_ACTION = DODGE_ACTION + 1         # 266
DISENGAGE_ACTION = DASH_ACTION + 1     # 267
END_TURN_ACTION = DISENGAGE_ACTION + 1 # 268

TOTAL_ACTIONS = END_TURN_ACTION + 1    # 269


# =============================================================================
# OBSERVATION SCHEMA
# =============================================================================

# Key trait flags for observation
TRAIT_FLAG_NAMES = [
    "pack_tactics",      # Bonus when ally near target
    "multiattack",       # Can make multiple attacks
    "spellcasting",      # Has spells
    "reach",             # Extended melee reach
    "nimble_escape",     # Bonus action disengage/hide
    "aggressive",        # Bonus action move toward enemy
    "reckless",          # Can attack recklessly
    "flyby",             # No opportunity attacks
    "regeneration",      # Regains HP
    "magic_resistance",  # Resists spells
]
NUM_TRAIT_FLAGS = len(TRAIT_FLAG_NAMES)


@dataclass
class ObservationSpec:
    """Defines the observation vector structure."""
    
    # A) Global state (4 values)
    GLOBAL_START = 0
    GLOBAL_SIZE = 4  # round_number, is_in_combat, grid_width, grid_height
    
    # B) Enemy self state (30 values) - EXPANDED
    SELF_START = GLOBAL_START + GLOBAL_SIZE
    # hp_pct, ac, speed, pos_x, pos_y, 
    # actions (4: standard, move, bonus, reaction),
    # movement_remaining (1),
    # conditions (10),
    # trait_flags (10)
    SELF_SIZE = 30
    
    # C) Local terrain (11x11 = 121 cells * 3 features = 363 values)
    TERRAIN_START = SELF_START + SELF_SIZE
    TERRAIN_FEATURES_PER_CELL = 3  # blocked, move_cost, hazard
    TERRAIN_SIZE = LOCAL_GRID_SIZE * TERRAIN_FEATURES_PER_CELL
    
    # D) Target slots (6 targets * 8 features = 48 values) - EXPANDED
    TARGETS_START = TERRAIN_START + TERRAIN_SIZE
    # hp_pct, ac, distance, reachable, in_melee, expected_dmg, 
    # ally_adjacent (for pack tactics), threat_level
    TARGET_FEATURES = 8
    TARGETS_SIZE = MAX_TARGETS * TARGET_FEATURES
    
    # E) Attack options (6 attacks * 4 features = 24 values) - EXPANDED
    ATTACKS_START = TARGETS_START + TARGETS_SIZE
    # range, avg_damage, to_hit, is_ranged
    ATTACK_FEATURES = 4
    ATTACKS_SIZE = MAX_ATTACKS * ATTACK_FEATURES
    
    # F) Spell options (6 spells * 5 features = 30 values) - EXPANDED
    SPELLS_START = ATTACKS_START + ATTACKS_SIZE
    # type, range, avg_damage, dc_or_to_hit, is_available
    SPELL_FEATURES = 5
    SPELLS_SIZE = MAX_SPELLS * SPELL_FEATURES
    
    # G) Ability options (6 abilities * 5 features = 30 values) - NEW
    ABILITIES_START = SPELLS_START + SPELLS_SIZE
    # type, range, avg_damage, dc, is_available (recharge ready)
    ABILITY_FEATURES = 5
    ABILITIES_SIZE = MAX_ABILITIES * ABILITY_FEATURES
    
    # H) Ally awareness (up to 4 allies * 3 features = 12 values) - NEW
    ALLIES_START = ABILITIES_START + ABILITIES_SIZE
    MAX_ALLIES = 4
    ALLY_FEATURES = 3  # distance, hp_pct, is_alive
    ALLIES_SIZE = MAX_ALLIES * ALLY_FEATURES
    
    # Total observation size
    TOTAL_SIZE = ALLIES_START + ALLIES_SIZE


# Common conditions for one-hot encoding
CONDITION_NAMES = [
    "blinded", "charmed", "deafened", "frightened", "grappled",
    "incapacitated", "invisible", "paralyzed", "poisoned", "prone"
]
NUM_CONDITIONS = len(CONDITION_NAMES)

# Scaling constants for normalization
MAX_HP = 500
MAX_AC = 30
MAX_SPEED = 120
MAX_GRID_DIM = 30
MAX_ROUND = 100
MAX_DISTANCE = 50
MAX_DAMAGE = 100
MAX_TO_HIT = 20
MAX_DC = 25


def get_observation_size() -> int:
    """Return total observation vector size."""
    return ObservationSpec.TOTAL_SIZE


def get_action_size() -> int:
    """Return total action space size."""
    return TOTAL_ACTIONS


@dataclass
class ActionSpec:
    """Describes a single action in the discrete action space."""
    action_type: int  # ACTION_MOVE, ACTION_ATTACK, etc.
    target_slot: int = -1  # For attacks/spells/abilities
    attack_slot: int = -1  # For attacks
    spell_slot: int = -1   # For spells
    ability_slot: int = -1 # For abilities
    move_offset: tuple = (0, 0)  # For moves (dx, dy from center)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type,
            "target_slot": self.target_slot,
            "attack_slot": self.attack_slot,
            "spell_slot": self.spell_slot,
            "ability_slot": self.ability_slot,
            "move_offset": self.move_offset,
        }


def action_index_to_spec(action_index: int) -> ActionSpec:
    """Convert action index to ActionSpec."""
    if action_index < MOVE_ACTION_END:
        # Move action
        local_idx = action_index - MOVE_ACTION_START
        grid_size = 2 * LOCAL_GRID_RADIUS + 1
        dy = local_idx // grid_size - LOCAL_GRID_RADIUS
        dx = local_idx % grid_size - LOCAL_GRID_RADIUS
        return ActionSpec(action_type=ACTION_MOVE, move_offset=(dx, dy))
    
    elif action_index < ATTACK_ACTION_END:
        # Attack action
        local_idx = action_index - ATTACK_ACTION_START
        target_slot = local_idx // MAX_ATTACKS
        attack_slot = local_idx % MAX_ATTACKS
        return ActionSpec(action_type=ACTION_ATTACK, target_slot=target_slot, attack_slot=attack_slot)
    
    elif action_index < SPELL_ATTACK_ACTION_END:
        # Spell attack action
        local_idx = action_index - SPELL_ATTACK_ACTION_START
        target_slot = local_idx // MAX_SPELLS
        spell_slot = local_idx % MAX_SPELLS
        return ActionSpec(action_type=ACTION_SPELL_ATTACK, target_slot=target_slot, spell_slot=spell_slot)
    
    elif action_index < SPELL_SAVE_ACTION_END:
        # Spell save action
        local_idx = action_index - SPELL_SAVE_ACTION_START
        target_slot = local_idx // MAX_SPELLS
        spell_slot = local_idx % MAX_SPELLS
        return ActionSpec(action_type=ACTION_SPELL_SAVE, target_slot=target_slot, spell_slot=spell_slot)
    
    elif action_index < ABILITY_ACTION_END:
        # Ability action
        local_idx = action_index - ABILITY_ACTION_START
        target_slot = local_idx // MAX_ABILITIES
        ability_slot = local_idx % MAX_ABILITIES
        return ActionSpec(action_type=ACTION_ABILITY, target_slot=target_slot, ability_slot=ability_slot)
    
    elif action_index == DODGE_ACTION:
        return ActionSpec(action_type=ACTION_DODGE)
    
    elif action_index == DASH_ACTION:
        return ActionSpec(action_type=ACTION_DASH)
    
    elif action_index == DISENGAGE_ACTION:
        return ActionSpec(action_type=ACTION_DISENGAGE)
    
    else:
        return ActionSpec(action_type=ACTION_END_TURN)


def spec_to_action_index(spec: ActionSpec) -> int:
    """Convert ActionSpec to action index."""
    if spec.action_type == ACTION_MOVE:
        dx, dy = spec.move_offset
        grid_size = 2 * LOCAL_GRID_RADIUS + 1
        local_idx = (dy + LOCAL_GRID_RADIUS) * grid_size + (dx + LOCAL_GRID_RADIUS)
        return MOVE_ACTION_START + local_idx
    
    elif spec.action_type == ACTION_ATTACK:
        return ATTACK_ACTION_START + spec.target_slot * MAX_ATTACKS + spec.attack_slot
    
    elif spec.action_type == ACTION_SPELL_ATTACK:
        return SPELL_ATTACK_ACTION_START + spec.target_slot * MAX_SPELLS + spec.spell_slot
    
    elif spec.action_type == ACTION_SPELL_SAVE:
        return SPELL_SAVE_ACTION_START + spec.target_slot * MAX_SPELLS + spec.spell_slot
    
    elif spec.action_type == ACTION_ABILITY:
        return ABILITY_ACTION_START + spec.target_slot * MAX_ABILITIES + spec.ability_slot
    
    elif spec.action_type == ACTION_DODGE:
        return DODGE_ACTION
    
    elif spec.action_type == ACTION_DASH:
        return DASH_ACTION
    
    elif spec.action_type == ACTION_DISENGAGE:
        return DISENGAGE_ACTION
    
    else:
        return END_TURN_ACTION
