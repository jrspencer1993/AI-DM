"""
XP and Leveling System for Virtual DM

This module handles:
- XP thresholds and level calculation
- Awarding XP with logging
- Level-up operations (HP increase, BAB updates, skill ranks, spells, features, ASI/feats)
"""

import json
import os
import random
import re
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

# ============================================================
# XP TABLE LOADING
# ============================================================

_XP_TABLE_CACHE: Optional[Dict[int, int]] = None
_MAX_LEVEL: int = 20


def _get_xp_table_path() -> str:
    """Get path to xp_table.json."""
    base_dir = os.path.dirname(__file__)
    return os.path.join(base_dir, "..", "data", "xp_table.json")


def load_xp_table() -> Dict[int, int]:
    """
    Load XP thresholds from data/xp_table.json.
    Returns dict mapping level (int) to XP required (int).
    """
    global _XP_TABLE_CACHE, _MAX_LEVEL
    
    if _XP_TABLE_CACHE is not None:
        return _XP_TABLE_CACHE
    
    try:
        with open(_get_xp_table_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        
        thresholds = data.get("xp_thresholds", {})
        _MAX_LEVEL = data.get("max_level", 20)
        
        # Convert string keys to int
        _XP_TABLE_CACHE = {int(k): v for k, v in thresholds.items()}
        return _XP_TABLE_CACHE
    
    except Exception as e:
        # Fallback to default D&D 5e thresholds
        _XP_TABLE_CACHE = {
            1: 0, 2: 300, 3: 900, 4: 2700, 5: 6500,
            6: 14000, 7: 23000, 8: 34000, 9: 48000, 10: 64000,
            11: 85000, 12: 100000, 13: 120000, 14: 140000, 15: 165000,
            16: 195000, 17: 225000, 18: 265000, 19: 305000, 20: 355000
        }
        _MAX_LEVEL = 20
        return _XP_TABLE_CACHE


def get_max_level() -> int:
    """Get maximum character level."""
    load_xp_table()  # Ensure loaded
    return _MAX_LEVEL


# ============================================================
# LEVEL CALCULATION
# ============================================================

def get_level_from_xp(xp: int) -> int:
    """
    Calculate character level from current XP total.
    
    Args:
        xp: Current experience points
        
    Returns:
        Character level (1-20)
    """
    xp_table = load_xp_table()
    max_level = get_max_level()
    
    # Find highest level where XP >= threshold
    level = 1
    for lvl in range(1, max_level + 1):
        if xp >= xp_table.get(lvl, 0):
            level = lvl
        else:
            break
    
    return level


def get_xp_for_level(level: int) -> int:
    """
    Get XP required to reach a specific level.
    
    Args:
        level: Target level (1-20)
        
    Returns:
        XP threshold for that level
    """
    xp_table = load_xp_table()
    return xp_table.get(level, 0)


def get_xp_to_next_level(xp: int) -> Tuple[int, int]:
    """
    Calculate XP needed to reach next level.
    
    Args:
        xp: Current experience points
        
    Returns:
        Tuple of (xp_needed, next_level_threshold)
        Returns (0, current_threshold) if at max level
    """
    current_level = get_level_from_xp(xp)
    max_level = get_max_level()
    
    if current_level >= max_level:
        return 0, get_xp_for_level(max_level)
    
    next_threshold = get_xp_for_level(current_level + 1)
    return next_threshold - xp, next_threshold


# ============================================================
# XP AWARDING
# ============================================================

def award_xp(character: Dict[str, Any], amount: int, reason: str = "", source: str = "") -> Dict[str, Any]:
    """
    Award XP to a character and check for level up.
    
    Args:
        character: Character dict to modify
        amount: XP amount to award (can be negative for penalties)
        reason: Description of why XP was awarded
        source: Source of XP (e.g., "combat", "quest", "roleplay")
        
    Returns:
        Dict with award details:
        {
            "old_xp": int,
            "new_xp": int,
            "amount": int,
            "old_level": int,
            "new_level": int,
            "leveled_up": bool,
            "levels_gained": int
        }
    """
    # Ensure XP fields exist
    old_xp = character.get("xp_current", 0)
    old_level = character.get("level", 1)
    
    # If character has no XP tracking yet, initialize from level
    if "xp_current" not in character:
        # Set XP to minimum for current level
        old_xp = get_xp_for_level(old_level)
        character["xp_current"] = old_xp
    
    # Award XP (minimum 0)
    new_xp = max(0, old_xp + amount)
    character["xp_current"] = new_xp
    
    # Calculate new level
    new_level = get_level_from_xp(new_xp)
    levels_gained = new_level - old_level
    leveled_up = levels_gained > 0
    
    # Update level tracking
    character["level_total"] = new_level
    
    # Set pending flag if leveled up
    if leveled_up:
        character["level_up_pending"] = True
        # Track how many level-ups are pending
        character["levels_pending"] = character.get("levels_pending", 0) + levels_gained
    
    # Log the XP award
    if "xp_log" not in character:
        character["xp_log"] = []
    
    log_entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "amount": amount,
        "reason": reason,
        "source": source,
        "old_xp": old_xp,
        "new_xp": new_xp,
        "old_level": old_level,
        "new_level": new_level,
    }
    character["xp_log"].append(log_entry)
    
    return {
        "old_xp": old_xp,
        "new_xp": new_xp,
        "amount": amount,
        "old_level": old_level,
        "new_level": new_level,
        "leveled_up": leveled_up,
        "levels_gained": levels_gained,
    }


# ============================================================
# LEVEL UP OPERATIONS
# ============================================================

# Hit die by class (d6/d8/d10/d12)
HIT_DIE_BY_CLASS = {
    "barbarian": 12,
    "fighter": 10,
    "knight": 10,
    "paladin": 10,
    "ranger": 10,
    "marshal": 10,
    "samurai": 10,
    "cleric": 8,
    "druid": 8,
    "monk": 8,
    "rogue": 8,
    "bard": 8,
    "warlock": 8,
    "artificer": 8,
    "spellblade": 8,
    "scout": 8,
    "sorcerer": 6,
    "wizard": 6,
}

# BAB progression rates
BAB_PROGRESSION = {
    "full": lambda lvl: lvl,           # +1 per level
    "3/4": lambda lvl: (lvl * 3) // 4, # +3/4 per level
    "half": lambda lvl: lvl // 2,      # +1/2 per level
    "1/4": lambda lvl: lvl // 4,       # +1/4 per level
}

# Class to BAB type mapping
CLASS_BAB_TYPE = {
    "barbarian": "full",
    "fighter": "full",
    "knight": "full",
    "paladin": "full",
    "ranger": "full",
    "marshal": "full",
    "samurai": "full",
    "scout": "full",
    "monk": "3/4",
    "rogue": "3/4",
    "cleric": "half",
    "druid": "half",
    "bard": "half",
    "warlock": "half",
    "artificer": "half",
    "spellblade": "half",
    "sorcerer": "1/4",
    "wizard": "1/4",
}

# Skill points per level by class (base value, add INT mod)
CLASS_SKILL_POINTS = {
    "barbarian": 4,
    "bard": 6,
    "cleric": 4,
    "druid": 4,
    "favored soul": 4,
    "fighter": 2,
    "knight": 4,
    "marshal": 4,
    "monk": 4,
    "paladin": 2,
    "ranger": 6,
    "rogue": 8,
    "samurai": 4,
    "scout": 6,
    "shaman": 4,
    "sorcerer": 4,
    "spellblade": 4,
    "swashbuckler": 4,
    "warlock": 4,
    "wizard": 4,
    "artificer": 4,
}

# ASI/Feat levels (standard D&D progression)
ASI_LEVELS = [4, 8, 12, 16, 19]

# Fighter gets extra ASIs
FIGHTER_ASI_LEVELS = [4, 6, 8, 12, 14, 16, 19]

# Rogue gets extra ASI
ROGUE_ASI_LEVELS = [4, 8, 10, 12, 16, 19]


def _ability_mod(score: int) -> int:
    """Calculate ability modifier from score."""
    return (score - 10) // 2


def get_hit_die_for_class(class_name: str) -> int:
    """Get hit die size for a class."""
    return HIT_DIE_BY_CLASS.get(class_name.lower(), 8)


def get_bab_for_level(class_name: str, level: int) -> int:
    """Calculate BAB for a class at a given level."""
    bab_type = CLASS_BAB_TYPE.get(class_name.lower(), "half")
    calc = BAB_PROGRESSION.get(bab_type, BAB_PROGRESSION["half"])
    return calc(level)


def get_skill_points_for_level(class_name: str, int_mod: int) -> int:
    """
    Calculate skill points gained at a level for a class.
    
    Args:
        class_name: Class gaining the level
        int_mod: Character's INT modifier
        
    Returns:
        Number of skill points to allocate (minimum 1)
    """
    base = CLASS_SKILL_POINTS.get(class_name.lower(), 4)
    return max(1, base + int_mod)


def get_asi_levels_for_class(class_name: str) -> List[int]:
    """Get the levels at which a class gets ASI/Feat."""
    class_lower = class_name.lower()
    if class_lower == "fighter":
        return FIGHTER_ASI_LEVELS
    elif class_lower == "rogue":
        return ROGUE_ASI_LEVELS
    else:
        return ASI_LEVELS


def is_asi_level(class_name: str, class_level: int) -> bool:
    """Check if a class level grants an ASI/Feat."""
    asi_levels = get_asi_levels_for_class(class_name)
    return class_level in asi_levels


def calculate_hp_increase(character: Dict[str, Any], roll_hp: bool = False) -> Tuple[int, str]:
    """
    Calculate HP increase for gaining a level.
    
    Args:
        character: Character dict
        roll_hp: If True, roll hit die. If False, use average.
        
    Returns:
        Tuple of (hp_gained, description)
    """
    class_name = character.get("class", "fighter")
    hit_die = get_hit_die_for_class(class_name)
    
    # Get CON modifier
    abilities = character.get("abilities", {})
    con_score = abilities.get("CON", 10)
    con_mod = _ability_mod(con_score)
    
    if roll_hp:
        # Roll the hit die
        roll = random.randint(1, hit_die)
        hp_gained = max(1, roll + con_mod)  # Minimum 1 HP per level
        desc = f"Rolled d{hit_die}: {roll} + CON mod ({con_mod}) = {hp_gained} HP"
    else:
        # Use average (rounded up)
        avg = (hit_die // 2) + 1
        hp_gained = max(1, avg + con_mod)
        desc = f"Average d{hit_die}: {avg} + CON mod ({con_mod}) = {hp_gained} HP"
    
    return hp_gained, desc


def calculate_hp_increase_for_class(character: Dict[str, Any], class_name: str, roll_hp: bool = False) -> Tuple[int, str]:
    """
    Calculate HP increase for gaining a level in a specific class.
    
    Args:
        character: Character dict
        class_name: Class gaining the level
        roll_hp: If True, roll hit die. If False, use average.
        
    Returns:
        Tuple of (hp_gained, description)
    """
    hit_die = get_hit_die_for_class(class_name)
    
    # Get CON modifier
    abilities = character.get("abilities", {})
    con_score = abilities.get("CON", 10)
    con_mod = _ability_mod(con_score)
    
    if roll_hp:
        roll = random.randint(1, hit_die)
        hp_gained = max(1, roll + con_mod)
        desc = f"Rolled d{hit_die}: {roll} + CON mod ({con_mod}) = {hp_gained} HP ({class_name})"
    else:
        avg = (hit_die // 2) + 1
        hp_gained = max(1, avg + con_mod)
        desc = f"Average d{hit_die}: {avg} + CON mod ({con_mod}) = {hp_gained} HP ({class_name})"
    
    return hp_gained, desc


# ============================================================
# SPELL PROGRESSION
# ============================================================

# Spells known/prepared by class and level (for classes that learn spells)
# Format: {class: {level: {"cantrips": int, "spells_known": int, "max_spell_level": int}}}
SPELL_PROGRESSION = {
    "bard": {
        1: {"cantrips": 2, "spells_known": 4, "max_spell_level": 1},
        2: {"cantrips": 2, "spells_known": 5, "max_spell_level": 1},
        3: {"cantrips": 2, "spells_known": 6, "max_spell_level": 2},
        4: {"cantrips": 3, "spells_known": 7, "max_spell_level": 2},
        5: {"cantrips": 3, "spells_known": 8, "max_spell_level": 3},
        6: {"cantrips": 3, "spells_known": 9, "max_spell_level": 3},
        7: {"cantrips": 3, "spells_known": 10, "max_spell_level": 4},
        8: {"cantrips": 3, "spells_known": 11, "max_spell_level": 4},
        9: {"cantrips": 3, "spells_known": 12, "max_spell_level": 5},
        10: {"cantrips": 4, "spells_known": 14, "max_spell_level": 5},
        11: {"cantrips": 4, "spells_known": 15, "max_spell_level": 6},
        12: {"cantrips": 4, "spells_known": 15, "max_spell_level": 6},
        13: {"cantrips": 4, "spells_known": 16, "max_spell_level": 7},
        14: {"cantrips": 4, "spells_known": 18, "max_spell_level": 7},
        15: {"cantrips": 4, "spells_known": 19, "max_spell_level": 8},
        16: {"cantrips": 4, "spells_known": 19, "max_spell_level": 8},
        17: {"cantrips": 4, "spells_known": 20, "max_spell_level": 9},
        18: {"cantrips": 4, "spells_known": 22, "max_spell_level": 9},
        19: {"cantrips": 4, "spells_known": 22, "max_spell_level": 9},
        20: {"cantrips": 4, "spells_known": 22, "max_spell_level": 9},
    },
    "sorcerer": {
        1: {"cantrips": 4, "spells_known": 2, "max_spell_level": 1},
        2: {"cantrips": 4, "spells_known": 3, "max_spell_level": 1},
        3: {"cantrips": 4, "spells_known": 4, "max_spell_level": 2},
        4: {"cantrips": 5, "spells_known": 5, "max_spell_level": 2},
        5: {"cantrips": 5, "spells_known": 6, "max_spell_level": 3},
        6: {"cantrips": 5, "spells_known": 7, "max_spell_level": 3},
        7: {"cantrips": 5, "spells_known": 8, "max_spell_level": 4},
        8: {"cantrips": 5, "spells_known": 9, "max_spell_level": 4},
        9: {"cantrips": 5, "spells_known": 10, "max_spell_level": 5},
        10: {"cantrips": 6, "spells_known": 11, "max_spell_level": 5},
        11: {"cantrips": 6, "spells_known": 12, "max_spell_level": 6},
        12: {"cantrips": 6, "spells_known": 12, "max_spell_level": 6},
        13: {"cantrips": 6, "spells_known": 13, "max_spell_level": 7},
        14: {"cantrips": 6, "spells_known": 13, "max_spell_level": 7},
        15: {"cantrips": 6, "spells_known": 14, "max_spell_level": 8},
        16: {"cantrips": 6, "spells_known": 14, "max_spell_level": 8},
        17: {"cantrips": 6, "spells_known": 15, "max_spell_level": 9},
        18: {"cantrips": 6, "spells_known": 15, "max_spell_level": 9},
        19: {"cantrips": 6, "spells_known": 15, "max_spell_level": 9},
        20: {"cantrips": 6, "spells_known": 15, "max_spell_level": 9},
    },
    "warlock": {
        1: {"cantrips": 2, "spells_known": 2, "max_spell_level": 1},
        2: {"cantrips": 2, "spells_known": 3, "max_spell_level": 1},
        3: {"cantrips": 2, "spells_known": 4, "max_spell_level": 2},
        4: {"cantrips": 3, "spells_known": 5, "max_spell_level": 2},
        5: {"cantrips": 3, "spells_known": 6, "max_spell_level": 3},
        6: {"cantrips": 3, "spells_known": 7, "max_spell_level": 3},
        7: {"cantrips": 3, "spells_known": 8, "max_spell_level": 4},
        8: {"cantrips": 3, "spells_known": 9, "max_spell_level": 4},
        9: {"cantrips": 3, "spells_known": 10, "max_spell_level": 5},
        10: {"cantrips": 4, "spells_known": 10, "max_spell_level": 5},
        11: {"cantrips": 4, "spells_known": 11, "max_spell_level": 5},
        12: {"cantrips": 4, "spells_known": 11, "max_spell_level": 5},
        13: {"cantrips": 4, "spells_known": 12, "max_spell_level": 5},
        14: {"cantrips": 4, "spells_known": 12, "max_spell_level": 5},
        15: {"cantrips": 4, "spells_known": 13, "max_spell_level": 5},
        16: {"cantrips": 4, "spells_known": 13, "max_spell_level": 5},
        17: {"cantrips": 4, "spells_known": 14, "max_spell_level": 5},
        18: {"cantrips": 4, "spells_known": 14, "max_spell_level": 5},
        19: {"cantrips": 4, "spells_known": 15, "max_spell_level": 5},
        20: {"cantrips": 4, "spells_known": 15, "max_spell_level": 5},
    },
    "wizard": {
        1: {"cantrips": 3, "spells_known": 6, "max_spell_level": 1},  # Spellbook spells
        2: {"cantrips": 3, "spells_known": 8, "max_spell_level": 1},
        3: {"cantrips": 3, "spells_known": 10, "max_spell_level": 2},
        4: {"cantrips": 4, "spells_known": 12, "max_spell_level": 2},
        5: {"cantrips": 4, "spells_known": 14, "max_spell_level": 3},
        6: {"cantrips": 4, "spells_known": 16, "max_spell_level": 3},
        7: {"cantrips": 4, "spells_known": 18, "max_spell_level": 4},
        8: {"cantrips": 4, "spells_known": 20, "max_spell_level": 4},
        9: {"cantrips": 4, "spells_known": 22, "max_spell_level": 5},
        10: {"cantrips": 5, "spells_known": 24, "max_spell_level": 5},
        11: {"cantrips": 5, "spells_known": 26, "max_spell_level": 6},
        12: {"cantrips": 5, "spells_known": 28, "max_spell_level": 6},
        13: {"cantrips": 5, "spells_known": 30, "max_spell_level": 7},
        14: {"cantrips": 5, "spells_known": 32, "max_spell_level": 7},
        15: {"cantrips": 5, "spells_known": 34, "max_spell_level": 8},
        16: {"cantrips": 5, "spells_known": 36, "max_spell_level": 8},
        17: {"cantrips": 5, "spells_known": 38, "max_spell_level": 9},
        18: {"cantrips": 5, "spells_known": 40, "max_spell_level": 9},
        19: {"cantrips": 5, "spells_known": 42, "max_spell_level": 9},
        20: {"cantrips": 5, "spells_known": 44, "max_spell_level": 9},
    },
    "cleric": {
        # Clerics prepare spells, cantrips known listed
        1: {"cantrips": 3, "max_spell_level": 1},
        2: {"cantrips": 3, "max_spell_level": 1},
        3: {"cantrips": 3, "max_spell_level": 2},
        4: {"cantrips": 4, "max_spell_level": 2},
        5: {"cantrips": 4, "max_spell_level": 3},
        6: {"cantrips": 4, "max_spell_level": 3},
        7: {"cantrips": 4, "max_spell_level": 4},
        8: {"cantrips": 4, "max_spell_level": 4},
        9: {"cantrips": 4, "max_spell_level": 5},
        10: {"cantrips": 5, "max_spell_level": 5},
        11: {"cantrips": 5, "max_spell_level": 6},
        12: {"cantrips": 5, "max_spell_level": 6},
        13: {"cantrips": 5, "max_spell_level": 7},
        14: {"cantrips": 5, "max_spell_level": 7},
        15: {"cantrips": 5, "max_spell_level": 8},
        16: {"cantrips": 5, "max_spell_level": 8},
        17: {"cantrips": 5, "max_spell_level": 9},
        18: {"cantrips": 5, "max_spell_level": 9},
        19: {"cantrips": 5, "max_spell_level": 9},
        20: {"cantrips": 5, "max_spell_level": 9},
    },
    "druid": {
        # Druids prepare spells, cantrips known listed
        1: {"cantrips": 2, "max_spell_level": 1},
        2: {"cantrips": 2, "max_spell_level": 1},
        3: {"cantrips": 2, "max_spell_level": 2},
        4: {"cantrips": 3, "max_spell_level": 2},
        5: {"cantrips": 3, "max_spell_level": 3},
        6: {"cantrips": 3, "max_spell_level": 3},
        7: {"cantrips": 3, "max_spell_level": 4},
        8: {"cantrips": 3, "max_spell_level": 4},
        9: {"cantrips": 3, "max_spell_level": 5},
        10: {"cantrips": 4, "max_spell_level": 5},
        11: {"cantrips": 4, "max_spell_level": 6},
        12: {"cantrips": 4, "max_spell_level": 6},
        13: {"cantrips": 4, "max_spell_level": 7},
        14: {"cantrips": 4, "max_spell_level": 7},
        15: {"cantrips": 4, "max_spell_level": 8},
        16: {"cantrips": 4, "max_spell_level": 8},
        17: {"cantrips": 4, "max_spell_level": 9},
        18: {"cantrips": 4, "max_spell_level": 9},
        19: {"cantrips": 4, "max_spell_level": 9},
        20: {"cantrips": 4, "max_spell_level": 9},
    },
    "paladin": {
        # Half caster, starts at level 2
        1: {"cantrips": 0, "max_spell_level": 0},
        2: {"cantrips": 0, "max_spell_level": 1},
        3: {"cantrips": 0, "max_spell_level": 1},
        4: {"cantrips": 0, "max_spell_level": 1},
        5: {"cantrips": 0, "max_spell_level": 2},
        6: {"cantrips": 0, "max_spell_level": 2},
        7: {"cantrips": 0, "max_spell_level": 2},
        8: {"cantrips": 0, "max_spell_level": 2},
        9: {"cantrips": 0, "max_spell_level": 3},
        10: {"cantrips": 0, "max_spell_level": 3},
        11: {"cantrips": 0, "max_spell_level": 3},
        12: {"cantrips": 0, "max_spell_level": 3},
        13: {"cantrips": 0, "max_spell_level": 4},
        14: {"cantrips": 0, "max_spell_level": 4},
        15: {"cantrips": 0, "max_spell_level": 4},
        16: {"cantrips": 0, "max_spell_level": 4},
        17: {"cantrips": 0, "max_spell_level": 5},
        18: {"cantrips": 0, "max_spell_level": 5},
        19: {"cantrips": 0, "max_spell_level": 5},
        20: {"cantrips": 0, "max_spell_level": 5},
    },
    "ranger": {
        # Half caster, starts at level 2
        1: {"cantrips": 0, "spells_known": 0, "max_spell_level": 0},
        2: {"cantrips": 0, "spells_known": 2, "max_spell_level": 1},
        3: {"cantrips": 0, "spells_known": 3, "max_spell_level": 1},
        4: {"cantrips": 0, "spells_known": 3, "max_spell_level": 1},
        5: {"cantrips": 0, "spells_known": 4, "max_spell_level": 2},
        6: {"cantrips": 0, "spells_known": 4, "max_spell_level": 2},
        7: {"cantrips": 0, "spells_known": 5, "max_spell_level": 2},
        8: {"cantrips": 0, "spells_known": 5, "max_spell_level": 2},
        9: {"cantrips": 0, "spells_known": 6, "max_spell_level": 3},
        10: {"cantrips": 0, "spells_known": 6, "max_spell_level": 3},
        11: {"cantrips": 0, "spells_known": 7, "max_spell_level": 3},
        12: {"cantrips": 0, "spells_known": 7, "max_spell_level": 3},
        13: {"cantrips": 0, "spells_known": 8, "max_spell_level": 4},
        14: {"cantrips": 0, "spells_known": 8, "max_spell_level": 4},
        15: {"cantrips": 0, "spells_known": 9, "max_spell_level": 4},
        16: {"cantrips": 0, "spells_known": 9, "max_spell_level": 4},
        17: {"cantrips": 0, "spells_known": 10, "max_spell_level": 5},
        18: {"cantrips": 0, "spells_known": 10, "max_spell_level": 5},
        19: {"cantrips": 0, "spells_known": 11, "max_spell_level": 5},
        20: {"cantrips": 0, "spells_known": 11, "max_spell_level": 5},
    },
    "spellblade": {
        # Half caster with cantrips
        1: {"cantrips": 2, "spells_known": 0, "max_spell_level": 0},
        2: {"cantrips": 2, "spells_known": 2, "max_spell_level": 1},
        3: {"cantrips": 2, "spells_known": 3, "max_spell_level": 1},
        4: {"cantrips": 2, "spells_known": 3, "max_spell_level": 1},
        5: {"cantrips": 2, "spells_known": 4, "max_spell_level": 2},
        6: {"cantrips": 2, "spells_known": 4, "max_spell_level": 2},
        7: {"cantrips": 2, "spells_known": 5, "max_spell_level": 2},
        8: {"cantrips": 3, "spells_known": 5, "max_spell_level": 2},
        9: {"cantrips": 3, "spells_known": 6, "max_spell_level": 3},
        10: {"cantrips": 3, "spells_known": 6, "max_spell_level": 3},
        11: {"cantrips": 3, "spells_known": 7, "max_spell_level": 3},
        12: {"cantrips": 3, "spells_known": 7, "max_spell_level": 3},
        13: {"cantrips": 3, "spells_known": 8, "max_spell_level": 4},
        14: {"cantrips": 4, "spells_known": 8, "max_spell_level": 4},
        15: {"cantrips": 4, "spells_known": 9, "max_spell_level": 4},
        16: {"cantrips": 4, "spells_known": 9, "max_spell_level": 4},
        17: {"cantrips": 4, "spells_known": 10, "max_spell_level": 5},
        18: {"cantrips": 4, "spells_known": 10, "max_spell_level": 5},
        19: {"cantrips": 4, "spells_known": 11, "max_spell_level": 5},
        20: {"cantrips": 4, "spells_known": 11, "max_spell_level": 5},
    },
}


def get_spell_progression(class_name: str, class_level: int) -> Dict[str, Any]:
    """
    Get spell progression info for a class at a level.
    
    Returns:
        {
            "cantrips": int,
            "spells_known": int or None (if prepared caster),
            "max_spell_level": int,
            "is_prepared_caster": bool
        }
    """
    class_lower = class_name.lower()
    
    if class_lower not in SPELL_PROGRESSION:
        return {"cantrips": 0, "spells_known": 0, "max_spell_level": 0, "is_prepared_caster": False}
    
    level_data = SPELL_PROGRESSION[class_lower].get(class_level, {})
    
    # Prepared casters (cleric, druid, paladin) don't have spells_known
    is_prepared = class_lower in ["cleric", "druid", "paladin"]
    
    return {
        "cantrips": level_data.get("cantrips", 0),
        "spells_known": level_data.get("spells_known"),
        "max_spell_level": level_data.get("max_spell_level", 0),
        "is_prepared_caster": is_prepared
    }


def get_new_spells_at_level(class_name: str, old_level: int, new_level: int) -> Dict[str, int]:
    """
    Calculate how many new spells can be learned when leveling up.
    
    Returns:
        {
            "new_cantrips": int,
            "new_spells": int,
            "max_spell_level": int
        }
    """
    old_prog = get_spell_progression(class_name, old_level)
    new_prog = get_spell_progression(class_name, new_level)
    
    new_cantrips = new_prog["cantrips"] - old_prog["cantrips"]
    
    # For known casters, calculate new spells
    if new_prog["spells_known"] is not None and old_prog["spells_known"] is not None:
        new_spells = new_prog["spells_known"] - old_prog["spells_known"]
    elif new_prog["spells_known"] is not None:
        new_spells = new_prog["spells_known"]
    else:
        new_spells = 0
    
    return {
        "new_cantrips": max(0, new_cantrips),
        "new_spells": max(0, new_spells),
        "max_spell_level": new_prog["max_spell_level"],
        "is_prepared_caster": new_prog["is_prepared_caster"]
    }


def is_caster_class(class_name: str) -> bool:
    """Check if a class has spellcasting."""
    return class_name.lower() in SPELL_PROGRESSION


# ============================================================
# COMPREHENSIVE LEVEL UP
# ============================================================

def level_up_character(character: Dict[str, Any], roll_hp: bool = False, class_id: str = None) -> Dict[str, Any]:
    """
    Apply level-up changes to a character (single class version for backward compatibility).
    
    For multiclass support, use level_up_character_multiclass() instead.
    
    This function:
    - Increases character level
    - Adds HP based on hit die + CON
    - Updates BAB
    - Clears level_up_pending flag
    
    Args:
        character: Character dict to modify
        roll_hp: If True, roll hit die for HP. If False, use average.
        class_id: Optional class to level up (for multiclass). If None, uses primary class.
        
    Returns:
        Dict with level-up details:
        {
            "old_level": int,
            "new_level": int,
            "hp_gained": int,
            "hp_description": str,
            "old_bab": int,
            "new_bab": int,
            "skill_points": int,
            "new_spells": dict,
            "is_asi_level": bool,
            "features_gained": list,
            "success": bool,
            "message": str
        }
    """
    # Check if level up is pending
    if not character.get("level_up_pending", False):
        return {
            "success": False,
            "message": "No level up pending for this character.",
            "old_level": character.get("level", 1),
            "new_level": character.get("level", 1),
            "hp_gained": 0,
            "hp_description": "",
            "old_bab": character.get("bab", 0),
            "new_bab": character.get("bab", 0),
            "skill_points": 0,
            "new_spells": {},
            "is_asi_level": False,
            "features_gained": [],
        }
    
    old_level = character.get("level", 1)
    new_level = character.get("level_total", old_level + 1)
    
    # Ensure we're actually gaining levels
    if new_level <= old_level:
        new_level = old_level + 1
    
    # Determine which class to use for HP
    if class_id:
        class_name = class_id
    else:
        class_name = character.get("class", "fighter")
    
    # Calculate HP increase for each level gained
    total_hp_gained = 0
    hp_descriptions = []
    
    for lvl in range(old_level + 1, new_level + 1):
        hp_gained, desc = calculate_hp_increase_for_class(character, class_name, roll_hp)
        total_hp_gained += hp_gained
        hp_descriptions.append(f"Level {lvl}: {desc}")
    
    # Apply HP increase
    old_hp = character.get("hp", 10)
    old_max_hp = character.get("max_hp", old_hp)
    
    character["max_hp"] = old_max_hp + total_hp_gained
    character["hp"] = old_hp + total_hp_gained  # Heal for the new HP
    
    # Update BAB - for multiclass, sum BAB from all classes
    old_bab = character.get("bab", 0)
    
    # Check if multiclass
    if "classes" in character and isinstance(character["classes"], list):
        # Multiclass BAB calculation
        new_bab = 0
        for cls in character["classes"]:
            cls_id = cls.get("class_id", "").lower()
            cls_level = cls.get("level", 0)
            bab_type = CLASS_BAB_TYPE.get(cls_id, "half")
            calc = BAB_PROGRESSION.get(bab_type, BAB_PROGRESSION["half"])
            new_bab += calc(cls_level)
    else:
        new_bab = get_bab_for_level(class_name, new_level)
    
    character["bab"] = new_bab
    
    # Calculate skill points
    int_mod = _ability_mod(character.get("abilities", {}).get("INT", 10))
    skill_points = get_skill_points_for_level(class_name, int_mod)
    
    # Track pending skill points
    character["pending_skill_points"] = character.get("pending_skill_points", 0) + skill_points
    
    # Calculate new spells (if caster)
    new_spells_info = get_new_spells_at_level(class_name, old_level, new_level)
    
    # Track pending spell selections
    if new_spells_info["new_cantrips"] > 0:
        character["pending_cantrips"] = character.get("pending_cantrips", 0) + new_spells_info["new_cantrips"]
    if new_spells_info["new_spells"] > 0:
        character["pending_spells"] = character.get("pending_spells", 0) + new_spells_info["new_spells"]
    character["max_spell_level"] = new_spells_info["max_spell_level"]
    
    # Check for ASI/Feat
    asi_level = is_asi_level(class_name, new_level)
    if asi_level:
        character["pending_asi"] = character.get("pending_asi", 0) + 1
    
    # Update level
    character["level"] = new_level
    character["level_total"] = new_level
    
    # Decrement pending levels
    levels_pending = character.get("levels_pending", 1)
    if levels_pending > 1:
        character["levels_pending"] = levels_pending - 1
    else:
        # Clear pending flag only when all levels are processed
        character["level_up_pending"] = False
        character.pop("levels_pending", None)
    
    # Log the level up
    if "level_up_log" not in character:
        character["level_up_log"] = []
    
    character["level_up_log"].append({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "old_level": old_level,
        "new_level": new_level,
        "hp_gained": total_hp_gained,
        "old_bab": old_bab,
        "new_bab": new_bab,
        "class_leveled": class_name,
        "skill_points": skill_points,
        "is_asi_level": asi_level,
    })
    
    return {
        "success": True,
        "message": f"Leveled up from {old_level} to {new_level}!",
        "old_level": old_level,
        "new_level": new_level,
        "hp_gained": total_hp_gained,
        "hp_description": "\n".join(hp_descriptions),
        "old_bab": old_bab,
        "new_bab": new_bab,
        "class_leveled": class_name,
        "skill_points": skill_points,
        "new_spells": new_spells_info,
        "is_asi_level": asi_level,
        "features_gained": [],  # Populated by UI from class data
    }


def level_up_character_multiclass(character: Dict[str, Any], class_id: str, roll_hp: bool = False) -> Dict[str, Any]:
    """
    Apply level-up changes to a specific class in a multiclass character.
    
    This function:
    - Increments the specified class level
    - Adds HP based on that class's hit die + CON
    - Updates total BAB across all classes
    - Calculates skill points
    - Calculates new spells (if caster)
    - Checks for ASI/Feat
    - Clears level_up_pending flag
    
    Args:
        character: Character dict to modify
        class_id: The class to gain a level in
        roll_hp: If True, roll hit die for HP. If False, use average.
        
    Returns:
        Dict with level-up details
    """
    # Check if level up is pending
    if not character.get("level_up_pending", False):
        return {
            "success": False,
            "message": "No level up pending for this character.",
            "old_level": character.get("level", 1),
            "new_level": character.get("level", 1),
            "hp_gained": 0,
            "hp_description": "",
            "old_bab": character.get("bab", 0),
            "new_bab": character.get("bab", 0),
            "skill_points": 0,
            "new_spells": {},
            "is_asi_level": False,
            "features_gained": [],
        }
    
    # Ensure multiclass format
    if "classes" not in character or not isinstance(character["classes"], list):
        # Migrate from legacy format
        legacy_class = character.get("class", "")
        legacy_level = character.get("level", 1)
        if legacy_class:
            character["classes"] = [{"class_id": legacy_class, "level": legacy_level}]
        else:
            character["classes"] = []
    
    old_total_level = sum(c.get("level", 0) for c in character["classes"])
    old_bab = character.get("bab", 0)
    
    # Find or add the class
    class_found = False
    old_class_level = 0
    for cls in character["classes"]:
        if cls.get("class_id", "").lower() == class_id.lower():
            old_class_level = cls.get("level", 0)
            cls["level"] = old_class_level + 1
            class_found = True
            break
    
    if not class_found:
        # Adding a new class
        character["classes"].append({"class_id": class_id, "level": 1})
        old_class_level = 0
    
    new_class_level = old_class_level + 1
    new_total_level = old_total_level + 1
    
    # Calculate HP increase for this class
    hp_gained, hp_desc = calculate_hp_increase_for_class(character, class_id, roll_hp)
    
    # Apply HP increase
    old_hp = character.get("hp", 10)
    old_max_hp = character.get("max_hp", old_hp)
    
    character["max_hp"] = old_max_hp + hp_gained
    character["hp"] = old_hp + hp_gained
    
    # Calculate new total BAB
    new_bab = 0
    for cls in character["classes"]:
        cls_id = cls.get("class_id", "").lower()
        cls_level = cls.get("level", 0)
        bab_type = CLASS_BAB_TYPE.get(cls_id, "half")
        calc = BAB_PROGRESSION.get(bab_type, BAB_PROGRESSION["half"])
        new_bab += calc(cls_level)
    
    character["bab"] = new_bab
    
    # Calculate skill points for this class
    int_mod = _ability_mod(character.get("abilities", {}).get("INT", 10))
    skill_points = get_skill_points_for_level(class_id, int_mod)
    
    # Track pending skill points
    character["pending_skill_points"] = character.get("pending_skill_points", 0) + skill_points
    
    # Calculate new spells (if caster)
    new_spells_info = get_new_spells_at_level(class_id, old_class_level, new_class_level)
    
    # Track pending spell selections
    if new_spells_info["new_cantrips"] > 0:
        character["pending_cantrips"] = character.get("pending_cantrips", 0) + new_spells_info["new_cantrips"]
    if new_spells_info["new_spells"] > 0:
        character["pending_spells"] = character.get("pending_spells", 0) + new_spells_info["new_spells"]
    if new_spells_info["max_spell_level"] > character.get("max_spell_level", 0):
        character["max_spell_level"] = new_spells_info["max_spell_level"]
    
    # Check for ASI/Feat at the CLASS level (not total level)
    asi_level = is_asi_level(class_id, new_class_level)
    if asi_level:
        character["pending_asi"] = character.get("pending_asi", 0) + 1
    
    # Update level totals
    character["level"] = new_total_level
    character["level_total"] = new_total_level
    
    # Decrement pending levels
    levels_pending = character.get("levels_pending", 1)
    if levels_pending > 1:
        character["levels_pending"] = levels_pending - 1
    else:
        # Clear pending flag only when all levels are processed
        character["level_up_pending"] = False
        character.pop("levels_pending", None)
    
    # Log the level up
    if "level_up_log" not in character:
        character["level_up_log"] = []
    
    character["level_up_log"].append({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "old_level": old_total_level,
        "new_level": new_total_level,
        "class_leveled": class_id,
        "old_class_level": old_class_level,
        "new_class_level": new_class_level,
        "hp_gained": hp_gained,
        "old_bab": old_bab,
        "new_bab": new_bab,
        "skill_points": skill_points,
        "is_asi_level": asi_level,
    })
    
    return {
        "success": True,
        "message": f"Gained level in {class_id}! (Total level: {new_total_level})",
        "old_level": old_total_level,
        "new_level": new_total_level,
        "class_leveled": class_id,
        "old_class_level": old_class_level,
        "new_class_level": new_class_level,
        "hp_gained": hp_gained,
        "hp_description": hp_desc,
        "old_bab": old_bab,
        "new_bab": new_bab,
        "skill_points": skill_points,
        "new_spells": new_spells_info,
        "is_asi_level": asi_level,
        "features_gained": [],  # Populated by UI from class data
    }


# ============================================================
# SKILL RANK APPLICATION
# ============================================================

def apply_skill_ranks(character: Dict[str, Any], skill_allocations: Dict[str, int]) -> Dict[str, Any]:
    """
    Apply skill rank allocations to a character.
    
    Args:
        character: Character dict to modify
        skill_allocations: Dict mapping skill name to ranks to add
        
    Returns:
        Result dict with success status and details
    """
    pending = character.get("pending_skill_points", 0)
    total_to_spend = sum(skill_allocations.values())
    
    if total_to_spend > pending:
        return {
            "success": False,
            "message": f"Not enough skill points. Have {pending}, trying to spend {total_to_spend}.",
            "allocated": 0
        }
    
    # Initialize skills dict if needed
    skills = character.setdefault("skills", {})
    
    # Apply allocations
    for skill_name, ranks in skill_allocations.items():
        if ranks > 0:
            current = skills.get(skill_name, 0)
            skills[skill_name] = current + ranks
    
    # Reduce pending points
    character["pending_skill_points"] = pending - total_to_spend
    
    return {
        "success": True,
        "message": f"Allocated {total_to_spend} skill points.",
        "allocated": total_to_spend,
        "remaining": pending - total_to_spend
    }


# ============================================================
# SPELL SELECTION APPLICATION
# ============================================================

def apply_spell_selection(character: Dict[str, Any], spell_type: str, spells: List[str]) -> Dict[str, Any]:
    """
    Apply spell selections to a character.
    
    Args:
        character: Character dict to modify
        spell_type: "cantrip" or "spell"
        spells: List of spell names to add
        
    Returns:
        Result dict with success status
    """
    if spell_type == "cantrip":
        pending = character.get("pending_cantrips", 0)
        if len(spells) > pending:
            return {
                "success": False,
                "message": f"Too many cantrips. Can select {pending}, trying to add {len(spells)}."
            }
        
        # Add cantrips
        char_spells = character.setdefault("spells", {})
        cantrips = char_spells.setdefault("cantrips", [])
        for spell in spells:
            if spell not in cantrips:
                cantrips.append(spell)
        
        character["pending_cantrips"] = pending - len(spells)
        
    elif spell_type == "spell":
        pending = character.get("pending_spells", 0)
        if len(spells) > pending:
            return {
                "success": False,
                "message": f"Too many spells. Can select {pending}, trying to add {len(spells)}."
            }
        
        # Add spells
        char_spells = character.setdefault("spells", {})
        known = char_spells.setdefault("known", [])
        for spell in spells:
            if spell not in known:
                known.append(spell)
        
        character["pending_spells"] = pending - len(spells)
    
    return {
        "success": True,
        "message": f"Added {len(spells)} {spell_type}(s)."
    }


# ============================================================
# ASI/FEAT APPLICATION
# ============================================================

def apply_asi(character: Dict[str, Any], ability1: str, ability2: str = None) -> Dict[str, Any]:
    """
    Apply an Ability Score Improvement.
    
    Args:
        character: Character dict to modify
        ability1: First ability to increase (+1 or +2 if ability2 is None)
        ability2: Optional second ability to increase (+1 each)
        
    Returns:
        Result dict with success status
    """
    pending = character.get("pending_asi", 0)
    if pending <= 0:
        return {"success": False, "message": "No ASI pending."}
    
    abilities = character.setdefault("abilities", {})
    
    if ability2:
        # +1 to two abilities
        old1 = abilities.get(ability1, 10)
        old2 = abilities.get(ability2, 10)
        abilities[ability1] = min(20, old1 + 1)
        abilities[ability2] = min(20, old2 + 1)
        msg = f"+1 {ability1} ({old1} → {abilities[ability1]}), +1 {ability2} ({old2} → {abilities[ability2]})"
    else:
        # +2 to one ability
        old = abilities.get(ability1, 10)
        abilities[ability1] = min(20, old + 2)
        msg = f"+2 {ability1} ({old} → {abilities[ability1]})"
    
    character["pending_asi"] = pending - 1
    
    # Recalculate derived stats
    _recalculate_derived_stats(character)
    
    return {"success": True, "message": msg}


def apply_feat(character: Dict[str, Any], feat_name: str, feat_data: Dict[str, Any] = None, 
               ability_choice: str = None, consume_asi: bool = True) -> Dict[str, Any]:
    """
    Apply a feat to a character with all mechanical effects.
    
    Args:
        character: Character dict to modify
        feat_name: Name of the feat
        feat_data: Optional feat data dict with bonuses/effects
        ability_choice: For feats with ability choice, which ability to increase
        consume_asi: Whether to consume a pending ASI (False for bonus feats)
        
    Returns:
        Result dict with success status and applied effects
    """
    if consume_asi:
        pending = character.get("pending_asi", 0)
        if pending <= 0:
            return {"success": False, "message": "No ASI/Feat pending."}
    
    feats = character.setdefault("feats", [])
    
    # Check if already has feat (some feats can be taken multiple times)
    repeatable_feats = ["Elemental Adept", "Weapon Focus", "Weapon Specialization", 
                        "Greater Weapon Focus", "Greater Weapon Specialization"]
    if feat_name in feats and feat_name not in repeatable_feats:
        return {"success": False, "message": f"Already has feat: {feat_name}"}
    
    feats.append(feat_name)
    
    if consume_asi:
        character["pending_asi"] = character.get("pending_asi", 1) - 1
    
    applied_effects = []
    
    # Apply feat bonuses if provided
    if feat_data:
        abilities = character.setdefault("abilities", {})
        
        # Handle ability score increases from feats
        ability_increase = feat_data.get("ability_increase", {})
        if ability_increase:
            if "choice" in ability_increase:
                # Feat gives choice of ability to increase
                if ability_choice and ability_choice in ability_increase["choice"]:
                    amount = ability_increase.get("amount", 1)
                    old = abilities.get(ability_choice, 10)
                    abilities[ability_choice] = min(20, old + amount)
                    applied_effects.append(f"+{amount} {ability_choice}")
            else:
                # Specific ability increases
                for ability, amount in ability_increase.items():
                    if ability in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]:
                        old = abilities.get(ability, 10)
                        abilities[ability] = min(20, old + amount)
                        applied_effects.append(f"+{amount} {ability}")
        
        # Handle effects
        effects = feat_data.get("effects", {})
        if effects:
            feat_effects = character.setdefault("feat_effects", {})
            feat_effects[feat_name] = effects
            
            # Apply specific mechanical effects
            
            # Speed bonus
            if "speed_bonus" in effects:
                speed_str = character.get("speed", "30 ft.")
                try:
                    current_speed = int(speed_str.replace(" ft.", "").replace("ft", ""))
                except:
                    current_speed = 30
                new_speed = current_speed + effects["speed_bonus"]
                character["speed"] = f"{new_speed} ft."
                applied_effects.append(f"+{effects['speed_bonus']} ft. speed")
            
            # Initiative bonus
            if "initiative_bonus" in effects:
                current_init = character.get("initiative_bonus", 0)
                character["initiative_bonus"] = current_init + effects["initiative_bonus"]
                applied_effects.append(f"+{effects['initiative_bonus']} initiative")
            
            # HP bonus
            if "hp_bonus_per_level" in effects:
                level = character.get("level", 1)
                hp_bonus = effects["hp_bonus_per_level"] * level
                character["max_hp"] = character.get("max_hp", 10) + hp_bonus
                character["hp"] = character.get("hp", 10) + hp_bonus
                applied_effects.append(f"+{hp_bonus} HP")
            
            if "hp_bonus" in effects:
                hp_bonus = effects["hp_bonus"]
                character["max_hp"] = character.get("max_hp", 10) + hp_bonus
                character["hp"] = character.get("hp", 10) + hp_bonus
                applied_effects.append(f"+{hp_bonus} HP")
            
            # AC bonus
            if "ac_bonus" in effects:
                character["feat_ac_bonus"] = character.get("feat_ac_bonus", 0) + effects["ac_bonus"]
                applied_effects.append(f"+{effects['ac_bonus']} AC")
            
            # Save bonuses
            for save_type in ["will_save_bonus", "reflex_save_bonus", "fortitude_save_bonus"]:
                if save_type in effects:
                    save_key = f"feat_{save_type}"
                    character[save_key] = character.get(save_key, 0) + effects[save_type]
                    applied_effects.append(f"+{effects[save_type]} {save_type.replace('_bonus', '')}")
            
            # Skill bonuses
            if "skill_bonuses" in effects:
                char_skill_bonuses = character.setdefault("skill_bonuses", {})
                for skill, bonus in effects["skill_bonuses"].items():
                    char_skill_bonuses[skill] = char_skill_bonuses.get(skill, 0) + bonus
                    applied_effects.append(f"+{bonus} {skill}")
            
            # Armor proficiencies
            if "armor_proficiency" in effects:
                profs = character.setdefault("profs", {})
                armor_profs = set(profs.setdefault("armor", []))
                armor_types = effects["armor_proficiency"]
                if isinstance(armor_types, str):
                    armor_types = [armor_types]
                for armor in armor_types:
                    armor_profs.add(armor)
                    applied_effects.append(f"Proficiency: {armor} armor")
                profs["armor"] = sorted(armor_profs)
            
            # Shield proficiency
            if effects.get("shield_proficiency"):
                profs = character.setdefault("profs", {})
                armor_profs = set(profs.setdefault("armor", []))
                armor_profs.add("shield")
                profs["armor"] = sorted(armor_profs)
                applied_effects.append("Proficiency: shields")
            
            # Weapon proficiencies
            if "weapon_proficiencies" in effects:
                # Mark that character needs to choose weapons
                character["pending_weapon_proficiencies"] = character.get("pending_weapon_proficiencies", 0) + effects["weapon_proficiencies"]
                applied_effects.append(f"Choose {effects['weapon_proficiencies']} weapon proficiencies")
            
            # Skill proficiencies
            if "skill_proficiencies" in effects:
                character["pending_skill_proficiencies"] = character.get("pending_skill_proficiencies", 0) + effects["skill_proficiencies"]
                applied_effects.append(f"Choose {effects['skill_proficiencies']} skill proficiencies")
            
            # Languages
            if "languages" in effects:
                if isinstance(effects["languages"], int):
                    character["pending_languages"] = character.get("pending_languages", 0) + effects["languages"]
                    applied_effects.append(f"Choose {effects['languages']} languages")
                elif isinstance(effects["languages"], list):
                    existing = set((character.get("languages") or "").split(", ")) if character.get("languages") else set()
                    for lang in effects["languages"]:
                        existing.add(lang)
                    existing.discard("")
                    character["languages"] = ", ".join(sorted(existing))
                    applied_effects.append(f"Languages: {', '.join(effects['languages'])}")
            
            # Luck points
            if "luck_points" in effects:
                character["luck_points"] = effects["luck_points"]
                character["luck_points_max"] = effects["luck_points"]
                applied_effects.append(f"{effects['luck_points']} luck points")
            
            # Damage resistance
            if "damage_resistance" in effects:
                resistances = character.setdefault("damage_resistances", [])
                res_types = effects["damage_resistance"]
                if isinstance(res_types, list):
                    for r in res_types:
                        if r not in resistances:
                            resistances.append(r)
                            applied_effects.append(f"Resistance: {r}")
            
            # Critical range
            if "critical_range" in effects:
                character["critical_range"] = min(character.get("critical_range", 20), effects["critical_range"])
                applied_effects.append(f"Critical on {effects['critical_range']}-20")
    
    # Recalculate derived stats
    _recalculate_derived_stats(character)
    
    result_msg = f"Gained feat: {feat_name}"
    if applied_effects:
        result_msg += f" ({', '.join(applied_effects)})"
    
    return {"success": True, "message": result_msg, "applied_effects": applied_effects}


def _recalculate_derived_stats(character: Dict[str, Any]):
    """Recalculate stats derived from abilities."""
    abilities = character.get("abilities", {})
    
    # Recalculate HP if CON changed
    con_mod = _ability_mod(abilities.get("CON", 10))
    # Note: Full HP recalculation would need level history, 
    # so we just note that CON mod changed
    
    # Recalculate AC if DEX changed (basic unarmored)
    # This is simplified - full AC calc should consider armor
    dex_mod = _ability_mod(abilities.get("DEX", 10))


def check_feat_prerequisites(character: Dict[str, Any], feat_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check if a character meets the prerequisites for a feat.
    
    Args:
        character: Character dict to check
        feat_data: Feat data dict with prerequisites
        
    Returns:
        Dict with "met" bool and "reasons" list of unmet prereqs
    """
    prereqs = feat_data.get("prerequisites", [])
    if not prereqs:
        return {"met": True, "reasons": []}
    
    abilities = character.get("abilities", {})
    feats = character.get("feats", [])
    bab = character.get("bab", 0)
    level = character.get("level", 1)
    
    unmet = []
    
    for prereq in prereqs:
        if isinstance(prereq, dict):
            for key, value in prereq.items():
                # Ability score prerequisite
                if key in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]:
                    if abilities.get(key, 10) < value:
                        unmet.append(f"{key} {value}+ (have {abilities.get(key, 10)})")
                
                # Feat prerequisite
                elif key == "feat":
                    if value not in feats:
                        unmet.append(f"Feat: {value}")
                
                # BAB prerequisite
                elif key == "BAB":
                    if bab < value:
                        unmet.append(f"BAB +{value}+ (have +{bab})")
                
                # Level prerequisite
                elif key == "level":
                    if level < value:
                        unmet.append(f"Level {value}+ (have {level})")
                
                # Caster level prerequisite
                elif key == "caster_level":
                    caster_lvl = character.get("caster_level", 0)
                    if caster_lvl < value:
                        unmet.append(f"Caster Level {value}+ (have {caster_lvl})")
                
                # Spellcasting prerequisite
                elif key == "spellcasting":
                    if not character.get("caster_type"):
                        unmet.append("Spellcasting ability")
                
                # Class prerequisite
                elif key == "class":
                    char_classes = [cc.get("class_id", "").lower() for cc in character.get("classes", [])]
                    if isinstance(value, str):
                        if value.lower() not in char_classes:
                            unmet.append(f"Class: {value}")
                    elif isinstance(value, list):
                        if not any(v.lower() in char_classes for v in value):
                            unmet.append(f"Class: {' or '.join(value)}")
                
                # Proficiency prerequisite
                elif key == "proficiency":
                    profs = character.get("profs", {})
                    weapon_profs = profs.get("weapons", [])
                    armor_profs = profs.get("armor", [])
                    all_profs = weapon_profs + armor_profs
                    if value not in all_profs:
                        unmet.append(f"Proficiency: {value}")
        
        elif isinstance(prereq, str):
            # String prerequisite - could be a feat name or description
            if prereq not in feats:
                unmet.append(prereq)
    
    return {"met": len(unmet) == 0, "reasons": unmet}


def get_available_fighting_styles(character: Dict[str, Any], all_feats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Get fighting style feats available to a character (ones they don't already have).
    
    Args:
        character: Character dict
        all_feats: List of all feats from SRD_Feats.json
        
    Returns:
        List of available fighting style feats
    """
    current_feats = character.get("feats", [])
    
    available = []
    for feat in all_feats:
        if feat.get("is_fighting_style"):
            # Check if character already has this fighting style
            if feat["name"] not in current_feats:
                available.append(feat)
    
    return available


def apply_fighting_style(character: Dict[str, Any], style_name: str, 
                         style_data: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Apply a fighting style feat to a character.
    
    Args:
        character: Character dict to modify
        style_name: Name of the fighting style feat
        style_data: Optional feat data dict
        
    Returns:
        Result dict with success status
    """
    pending = character.get("pending_fighting_style", 0)
    if pending <= 0:
        return {"success": False, "message": "No fighting style choice pending."}
    
    # Use apply_feat with consume_asi=False since this is a bonus feat
    result = apply_feat(character, style_name, style_data, consume_asi=False)
    
    if result["success"]:
        character["pending_fighting_style"] = pending - 1
    
    return result


def get_available_bonus_feats(character: Dict[str, Any], all_feats: List[Dict[str, Any]], 
                               feat_type: str = None) -> List[Dict[str, Any]]:
    """
    Get bonus feats available to a character based on prerequisites.
    
    Args:
        character: Character dict
        all_feats: List of all feats from SRD_Feats.json
        feat_type: Optional filter for feat type (e.g., "combat", "item_creation")
        
    Returns:
        List of available feats with prerequisite check results
    """
    current_feats = character.get("feats", [])
    
    # Feats that can be taken multiple times
    repeatable_feats = ["Elemental Adept", "Weapon Focus", "Weapon Specialization",
                        "Greater Weapon Focus", "Greater Weapon Specialization",
                        "Spell Focus", "Greater Spell Focus"]
    
    available = []
    for feat in all_feats:
        # Skip fighting styles for general bonus feat selection
        if feat.get("is_fighting_style"):
            continue
        
        feat_name = feat.get("name", "")
        
        # Filter by type if specified
        if feat_type:
            if feat_type == "combat":
                # Combat feats typically affect attacks, AC, or combat actions
                effects = feat.get("effects", {})
                is_combat = any(k in effects for k in [
                    "attack_bonus", "damage_bonus", "ac_bonus", "critical_range",
                    "ranged_attack_bonus", "melee_attack_bonus", "two_weapon",
                    "power_attack", "cleave", "great_cleave", "improved_critical"
                ]) or "combat" in feat.get("description", "").lower()
                if not is_combat:
                    continue
        
        # Check if already has feat (unless repeatable)
        if feat_name in current_feats and feat_name not in repeatable_feats:
            continue
        
        # Check prerequisites
        prereq_check = check_feat_prerequisites(character, feat)
        
        available.append({
            "feat": feat,
            "meets_prerequisites": prereq_check["met"],
            "unmet_prerequisites": prereq_check["reasons"]
        })
    
    return available


def apply_bonus_feat(character: Dict[str, Any], feat_name: str,
                     feat_data: Dict[str, Any] = None,
                     ability_choice: str = None) -> Dict[str, Any]:
    """
    Apply a bonus feat to a character (from class feature, not ASI).
    
    Args:
        character: Character dict to modify
        feat_name: Name of the feat
        feat_data: Optional feat data dict
        ability_choice: For feats with ability choice
        
    Returns:
        Result dict with success status
    """
    pending = character.get("pending_bonus_feat", 0)
    if pending <= 0:
        return {"success": False, "message": "No bonus feat choice pending."}
    
    # Check prerequisites
    if feat_data:
        prereq_check = check_feat_prerequisites(character, feat_data)
        if not prereq_check["met"]:
            return {
                "success": False, 
                "message": f"Prerequisites not met: {', '.join(prereq_check['reasons'])}"
            }
    
    # Use apply_feat with consume_asi=False since this is a bonus feat
    result = apply_feat(character, feat_name, feat_data, ability_choice, consume_asi=False)
    
    if result["success"]:
        character["pending_bonus_feat"] = pending - 1
    
    return result


# ============================================================
# FEATURE APPLICATION
# ============================================================

def apply_class_features(character: Dict[str, Any], features: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Apply class features to a character.
    
    Args:
        character: Character dict to modify
        features: List of feature dicts to add
        
    Returns:
        Result dict with success status
    """
    char_features = character.setdefault("features", [])
    added = []
    
    for feat in features:
        feat_name = feat.get("name") if isinstance(feat, dict) else str(feat)
        
        # Check if already has feature
        existing_names = [f.get("name") if isinstance(f, dict) else str(f) for f in char_features]
        if feat_name not in existing_names:
            if isinstance(feat, dict):
                char_features.append(feat)
            else:
                char_features.append({"name": feat_name, "description": ""})
            added.append(feat_name)
    
    return {
        "success": True,
        "message": f"Added {len(added)} feature(s).",
        "features_added": added
    }


# ============================================================
# CHARACTER SCHEMA MIGRATION
# ============================================================

def migrate_character_xp(character: Dict[str, Any]) -> bool:
    """
    Migrate a character to include XP fields if missing.
    
    Args:
        character: Character dict to migrate
        
    Returns:
        True if migration was performed, False if already up-to-date
    """
    migrated = False
    
    # Ensure level exists
    if "level" not in character:
        character["level"] = 1
        migrated = True
    
    # Initialize XP from level if not present
    if "xp_current" not in character:
        level = character.get("level", 1)
        character["xp_current"] = get_xp_for_level(level)
        migrated = True
    
    # Ensure level_total matches calculated level
    if "level_total" not in character:
        character["level_total"] = get_level_from_xp(character["xp_current"])
        migrated = True
    
    # Ensure level_up_pending exists
    if "level_up_pending" not in character:
        # Check if there's a pending level up
        current_level = character.get("level", 1)
        calculated_level = get_level_from_xp(character["xp_current"])
        character["level_up_pending"] = calculated_level > current_level
        migrated = True
    
    # Ensure xp_log exists
    if "xp_log" not in character:
        character["xp_log"] = []
        migrated = True
    
    return migrated


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def get_xp_progress(character: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get XP progress information for a character.
    
    Returns:
        Dict with progress info:
        {
            "current_xp": int,
            "current_level": int,
            "next_level": int,
            "xp_for_current": int,
            "xp_for_next": int,
            "xp_needed": int,
            "progress_pct": float (0-100),
            "at_max_level": bool
        }
    """
    migrate_character_xp(character)  # Ensure fields exist
    
    current_xp = character.get("xp_current", 0)
    current_level = character.get("level", 1)
    max_level = get_max_level()
    
    xp_for_current = get_xp_for_level(current_level)
    
    if current_level >= max_level:
        return {
            "current_xp": current_xp,
            "current_level": current_level,
            "next_level": max_level,
            "xp_for_current": xp_for_current,
            "xp_for_next": xp_for_current,
            "xp_needed": 0,
            "progress_pct": 100.0,
            "at_max_level": True,
        }
    
    next_level = current_level + 1
    xp_for_next = get_xp_for_level(next_level)
    xp_needed = xp_for_next - current_xp
    
    # Calculate progress percentage within current level
    level_xp_range = xp_for_next - xp_for_current
    xp_into_level = current_xp - xp_for_current
    progress_pct = (xp_into_level / level_xp_range * 100) if level_xp_range > 0 else 0
    
    return {
        "current_xp": current_xp,
        "current_level": current_level,
        "next_level": next_level,
        "xp_for_current": xp_for_current,
        "xp_for_next": xp_for_next,
        "xp_needed": xp_needed,
        "progress_pct": min(100.0, max(0.0, progress_pct)),
        "at_max_level": False,
    }


def has_pending_choices(character: Dict[str, Any]) -> Dict[str, bool]:
    """
    Check what pending choices a character has after leveling up.
    
    Returns:
        Dict with pending choice flags
    """
    return {
        "skill_points": character.get("pending_skill_points", 0) > 0,
        "cantrips": character.get("pending_cantrips", 0) > 0,
        "spells": character.get("pending_spells", 0) > 0,
        "asi_or_feat": character.get("pending_asi", 0) > 0,
        "fighting_style": character.get("pending_fighting_style", 0) > 0,
        "bonus_feat": character.get("pending_bonus_feat", 0) > 0,
        "invocations": character.get("pending_invocations", 0) > 0,
        "pact_boon": character.get("pending_pact_boon", False),
        "metamagic": character.get("pending_metamagic", 0) > 0,
        "primal_talents": character.get("pending_primal_talents", 0) > 0,
        "maneuvers": character.get("pending_maneuvers", 0) > 0,
        "wizard_school": character.get("pending_wizard_school", False),
        "divine_vow": character.get("pending_divine_vow", False),
        "marshal_maneuvers": character.get("pending_marshal_maneuvers", 0) > 0,
        "knight_maneuvers": character.get("pending_knight_maneuvers", 0) > 0,
        "weapon_expertise": character.get("pending_weapon_expertise", False),
        "any": any([
            character.get("pending_skill_points", 0) > 0,
            character.get("pending_cantrips", 0) > 0,
            character.get("pending_spells", 0) > 0,
            character.get("pending_asi", 0) > 0,
            character.get("pending_fighting_style", 0) > 0,
            character.get("pending_bonus_feat", 0) > 0,
            character.get("pending_invocations", 0) > 0,
            character.get("pending_pact_boon", False),
            character.get("pending_metamagic", 0) > 0,
            character.get("pending_primal_talents", 0) > 0,
            character.get("pending_maneuvers", 0) > 0,
            character.get("pending_wizard_school", False),
            character.get("pending_divine_vow", False),
            character.get("pending_marshal_maneuvers", 0) > 0,
            character.get("pending_knight_maneuvers", 0) > 0,
            character.get("pending_weapon_expertise", False),
        ])
    }


def get_pending_summary(character: Dict[str, Any]) -> str:
    """Get a human-readable summary of pending choices."""
    pending = []
    
    sp = character.get("pending_skill_points", 0)
    if sp > 0:
        pending.append(f"{sp} skill point(s)")
    
    cantrips = character.get("pending_cantrips", 0)
    if cantrips > 0:
        pending.append(f"{cantrips} cantrip(s)")
    
    spells = character.get("pending_spells", 0)
    if spells > 0:
        pending.append(f"{spells} spell(s)")
    
    asi = character.get("pending_asi", 0)
    if asi > 0:
        pending.append(f"{asi} ASI/Feat")
    
    invocations = character.get("pending_invocations", 0)
    if invocations > 0:
        pending.append(f"{invocations} invocation(s)")
    
    if character.get("pending_pact_boon"):
        pending.append("Pact Boon")
    
    metamagic = character.get("pending_metamagic", 0)
    if metamagic > 0:
        pending.append(f"{metamagic} metamagic")
    
    primal = character.get("pending_primal_talents", 0)
    if primal > 0:
        pending.append(f"{primal} primal talent(s)")
    
    maneuvers = character.get("pending_maneuvers", 0)
    if maneuvers > 0:
        pending.append(f"{maneuvers} maneuver(s)")
    
    marshal_maneuvers = character.get("pending_marshal_maneuvers", 0)
    if marshal_maneuvers > 0:
        pending.append(f"{marshal_maneuvers} marshal maneuver(s)")
    
    knight_maneuvers = character.get("pending_knight_maneuvers", 0)
    if knight_maneuvers > 0:
        pending.append(f"{knight_maneuvers} knight maneuver(s)")
    
    if not pending:
        return "No pending choices"
    
    return "Pending: " + ", ".join(pending)
