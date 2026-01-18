"""
XP Award Calculator for Virtual DM

This module handles:
- Monster XP lookup by Challenge Rating
- Encounter XP calculation with multipliers
- Quest/Milestone XP calculation
- Encounter difficulty assessment
"""

import json
import os
import re
from typing import Dict, Any, List, Optional, Tuple


# ============================================================
# DATA LOADING
# ============================================================

_MONSTER_XP_CACHE: Optional[Dict] = None


def _get_monster_xp_path() -> str:
    """Get path to monster_xp.json."""
    base_dir = os.path.dirname(__file__)
    return os.path.join(base_dir, "..", "data", "monster_xp.json")


def load_monster_xp_data() -> Dict:
    """
    Load monster XP data from data/monster_xp.json.
    Returns dict with cr_to_xp, encounter_multipliers, difficulty_thresholds, etc.
    """
    global _MONSTER_XP_CACHE
    
    if _MONSTER_XP_CACHE is not None:
        return _MONSTER_XP_CACHE
    
    try:
        with open(_get_monster_xp_path(), "r", encoding="utf-8") as f:
            _MONSTER_XP_CACHE = json.load(f)
        return _MONSTER_XP_CACHE
    except Exception as e:
        # Fallback to basic CR->XP mapping
        _MONSTER_XP_CACHE = {
            "cr_to_xp": {
                "0": 10, "1/8": 25, "1/4": 50, "1/2": 100,
                "1": 200, "2": 450, "3": 700, "4": 1100, "5": 1800,
                "6": 2300, "7": 2900, "8": 3900, "9": 5000, "10": 5900,
                "11": 7200, "12": 8400, "13": 10000, "14": 11500, "15": 13000,
                "16": 15000, "17": 18000, "18": 20000, "19": 22000, "20": 25000
            },
            "encounter_multipliers": {},
            "difficulty_thresholds": {},
            "quest_xp_guidelines": {}
        }
        return _MONSTER_XP_CACHE


# ============================================================
# CR PARSING AND XP LOOKUP
# ============================================================

def parse_cr(cr_string: str) -> str:
    """
    Parse a Challenge Rating string into a normalized format.
    Handles: "1/4", "0.25", "1/2 (50 XP)", "10 (5,900 XP)", etc.
    """
    if not cr_string:
        return "0"
    
    cr_str = str(cr_string).strip()
    
    # Extract CR from "CR (XP)" format like "10 (5,900 XP)"
    match = re.match(r'^([\d/]+(?:\.\d+)?)', cr_str)
    if match:
        cr_str = match.group(1)
    
    # Convert decimal to fraction
    if '.' in cr_str:
        try:
            val = float(cr_str)
            if val == 0.125:
                return "1/8"
            elif val == 0.25:
                return "1/4"
            elif val == 0.5:
                return "1/2"
            else:
                return str(int(val)) if val == int(val) else cr_str
        except ValueError:
            pass
    
    return cr_str


def get_xp_for_cr(cr: str) -> int:
    """
    Get XP value for a Challenge Rating.
    
    Args:
        cr: Challenge Rating as string (e.g., "1/4", "5", "10")
        
    Returns:
        XP value for that CR
    """
    data = load_monster_xp_data()
    cr_to_xp = data.get("cr_to_xp", {})
    
    cr_normalized = parse_cr(cr)
    
    # Direct lookup
    if cr_normalized in cr_to_xp:
        return cr_to_xp[cr_normalized]
    
    # Try as integer
    try:
        cr_int = int(cr_normalized)
        if str(cr_int) in cr_to_xp:
            return cr_to_xp[str(cr_int)]
    except ValueError:
        pass
    
    # Default to 0 XP for unknown CR
    return 0


def extract_xp_from_challenge_string(challenge_str: str) -> int:
    """
    Extract XP value directly from a Challenge string like "10 (5,900 XP)".
    Falls back to CR lookup if XP not found in string.
    """
    if not challenge_str:
        return 0
    
    # Try to extract XP from parentheses
    match = re.search(r'\(([0-9,]+)\s*XP\)', challenge_str, re.IGNORECASE)
    if match:
        xp_str = match.group(1).replace(',', '')
        try:
            return int(xp_str)
        except ValueError:
            pass
    
    # Fall back to CR lookup
    return get_xp_for_cr(challenge_str)


# ============================================================
# ENCOUNTER XP CALCULATION
# ============================================================

def get_encounter_multiplier(monster_count: int, party_size: int = 4) -> float:
    """
    Get the encounter difficulty multiplier based on number of monsters.
    
    Args:
        monster_count: Number of monsters in the encounter
        party_size: Number of party members (affects multiplier brackets)
        
    Returns:
        Multiplier for adjusted XP (for difficulty calculation only)
    """
    if monster_count <= 0:
        return 1.0
    
    # Base multiplier brackets
    if monster_count == 1:
        multiplier = 1.0
    elif monster_count == 2:
        multiplier = 1.5
    elif monster_count <= 6:
        multiplier = 2.0
    elif monster_count <= 10:
        multiplier = 2.5
    elif monster_count <= 14:
        multiplier = 3.0
    else:
        multiplier = 4.0
    
    # Adjust for party size
    if party_size <= 2:
        # Small party: use next higher bracket
        if multiplier < 4.0:
            multiplier += 0.5
    elif party_size >= 6:
        # Large party: use next lower bracket
        if multiplier > 1.0:
            multiplier -= 0.5
    
    return multiplier


def calc_encounter_xp(
    monsters: List[Dict[str, Any]],
    party_size: int = 4,
    apply_multiplier: bool = False
) -> Dict[str, Any]:
    """
    Calculate total XP for an encounter.
    
    Args:
        monsters: List of monster dicts with "Challenge" or "cr" or "xp" field
        party_size: Number of party members
        apply_multiplier: If True, apply encounter multiplier to XP
                         (Note: RAW 5e awards base XP, multiplier is for difficulty only)
        
    Returns:
        Dict with:
        {
            "base_xp": int,           # Sum of individual monster XP
            "monster_count": int,     # Number of monsters
            "multiplier": float,      # Encounter multiplier
            "adjusted_xp": int,       # XP with multiplier applied
            "xp_per_member": int,     # XP per party member (base / party_size)
            "monsters_breakdown": list # XP per monster
        }
    """
    if not monsters:
        return {
            "base_xp": 0,
            "monster_count": 0,
            "multiplier": 1.0,
            "adjusted_xp": 0,
            "xp_per_member": 0,
            "monsters_breakdown": []
        }
    
    # Calculate XP for each monster
    monsters_breakdown = []
    total_xp = 0
    
    for monster in monsters:
        monster_name = monster.get("name", "Unknown")
        
        # Try to get XP from various fields
        xp = 0
        
        # Direct XP field
        if "xp" in monster and monster["xp"]:
            try:
                xp = int(monster["xp"])
            except (ValueError, TypeError):
                pass
        
        # Challenge field (e.g., "10 (5,900 XP)")
        if xp == 0 and "Challenge" in monster:
            xp = extract_xp_from_challenge_string(monster["Challenge"])
        
        # CR field
        if xp == 0 and "cr" in monster:
            xp = get_xp_for_cr(str(monster["cr"]))
        
        # challenge_rating field
        if xp == 0 and "challenge_rating" in monster:
            xp = get_xp_for_cr(str(monster["challenge_rating"]))
        
        monsters_breakdown.append({
            "name": monster_name,
            "xp": xp,
            "cr": monster.get("Challenge", monster.get("cr", "?"))
        })
        total_xp += xp
    
    monster_count = len(monsters)
    multiplier = get_encounter_multiplier(monster_count, party_size)
    adjusted_xp = int(total_xp * multiplier) if apply_multiplier else total_xp
    xp_per_member = adjusted_xp // party_size if party_size > 0 else adjusted_xp
    
    return {
        "base_xp": total_xp,
        "monster_count": monster_count,
        "multiplier": multiplier,
        "adjusted_xp": adjusted_xp,
        "xp_per_member": xp_per_member,
        "monsters_breakdown": monsters_breakdown
    }


# ============================================================
# ENCOUNTER DIFFICULTY ASSESSMENT
# ============================================================

def get_party_xp_thresholds(party_levels: List[int]) -> Dict[str, int]:
    """
    Calculate party XP thresholds for encounter difficulty.
    
    Args:
        party_levels: List of party member levels
        
    Returns:
        Dict with easy/medium/hard/deadly thresholds for the party
    """
    data = load_monster_xp_data()
    thresholds = data.get("difficulty_thresholds", {})
    
    party_thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
    
    for level in party_levels:
        level_str = str(min(20, max(1, level)))
        level_thresholds = thresholds.get(level_str, {"easy": 25, "medium": 50, "hard": 75, "deadly": 100})
        
        for difficulty in party_thresholds:
            party_thresholds[difficulty] += level_thresholds.get(difficulty, 0)
    
    return party_thresholds


def assess_encounter_difficulty(
    monsters: List[Dict[str, Any]],
    party_levels: List[int]
) -> Dict[str, Any]:
    """
    Assess the difficulty of an encounter for a party.
    
    Args:
        monsters: List of monster dicts
        party_levels: List of party member levels
        
    Returns:
        Dict with:
        {
            "difficulty": str,        # "trivial", "easy", "medium", "hard", "deadly"
            "adjusted_xp": int,       # XP with encounter multiplier
            "thresholds": dict,       # Party thresholds
            "margin": int             # How far above/below threshold
        }
    """
    party_size = len(party_levels)
    encounter = calc_encounter_xp(monsters, party_size, apply_multiplier=True)
    adjusted_xp = encounter["adjusted_xp"]
    
    thresholds = get_party_xp_thresholds(party_levels)
    
    # Determine difficulty
    if adjusted_xp >= thresholds["deadly"]:
        difficulty = "deadly"
        margin = adjusted_xp - thresholds["deadly"]
    elif adjusted_xp >= thresholds["hard"]:
        difficulty = "hard"
        margin = adjusted_xp - thresholds["hard"]
    elif adjusted_xp >= thresholds["medium"]:
        difficulty = "medium"
        margin = adjusted_xp - thresholds["medium"]
    elif adjusted_xp >= thresholds["easy"]:
        difficulty = "easy"
        margin = adjusted_xp - thresholds["easy"]
    else:
        difficulty = "trivial"
        margin = adjusted_xp - thresholds["easy"]
    
    return {
        "difficulty": difficulty,
        "adjusted_xp": adjusted_xp,
        "base_xp": encounter["base_xp"],
        "thresholds": thresholds,
        "margin": margin
    }


# ============================================================
# QUEST/MILESTONE XP
# ============================================================

def calc_quest_xp(
    quest_type: str,
    party_levels: List[int],
    custom_multiplier: float = 1.0
) -> Dict[str, Any]:
    """
    Calculate suggested XP for a quest/milestone.
    
    Args:
        quest_type: "minor", "moderate", "major", or "epic"
        party_levels: List of party member levels
        custom_multiplier: Optional multiplier for fine-tuning
        
    Returns:
        Dict with:
        {
            "quest_type": str,
            "base_xp_per_level": int,
            "total_xp": int,
            "xp_per_member": int,
            "description": str
        }
    """
    data = load_monster_xp_data()
    guidelines = data.get("quest_xp_guidelines", {})
    
    quest_info = guidelines.get(quest_type.lower(), {"xp_per_level": 50, "description": "Custom quest"})
    xp_per_level = quest_info.get("xp_per_level", 50)
    description = quest_info.get("description", "")
    
    # Calculate average party level
    avg_level = sum(party_levels) / len(party_levels) if party_levels else 1
    
    # Base XP = xp_per_level * average level * party size
    party_size = len(party_levels)
    total_xp = int(xp_per_level * avg_level * party_size * custom_multiplier)
    xp_per_member = total_xp // party_size if party_size > 0 else total_xp
    
    return {
        "quest_type": quest_type,
        "base_xp_per_level": xp_per_level,
        "total_xp": total_xp,
        "xp_per_member": xp_per_member,
        "description": description,
        "avg_party_level": avg_level,
        "party_size": party_size
    }


def get_quest_types() -> List[Dict[str, Any]]:
    """
    Get list of available quest types with descriptions.
    """
    data = load_monster_xp_data()
    guidelines = data.get("quest_xp_guidelines", {})
    
    result = []
    for quest_type, info in guidelines.items():
        # Skip non-dict entries (like "description" key)
        if not isinstance(info, dict):
            continue
        result.append({
            "type": quest_type,
            "description": info.get("description", ""),
            "xp_per_level": info.get("xp_per_level", 50)
        })
    
    return result


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def format_xp(xp: int) -> str:
    """Format XP with comma separators."""
    return f"{xp:,}"


def get_difficulty_color(difficulty: str) -> str:
    """Get a color code for difficulty level."""
    colors = {
        "trivial": "#888888",
        "easy": "#4CAF50",
        "medium": "#FFC107",
        "hard": "#FF9800",
        "deadly": "#F44336"
    }
    return colors.get(difficulty.lower(), "#888888")


def get_difficulty_emoji(difficulty: str) -> str:
    """Get an emoji for difficulty level."""
    emojis = {
        "trivial": "😴",
        "easy": "😊",
        "medium": "😐",
        "hard": "😰",
        "deadly": "💀"
    }
    return emojis.get(difficulty.lower(), "❓")
