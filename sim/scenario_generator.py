"""
Randomized Scenario Generator for RL Training.

Generates diverse combat scenarios with random:
- Party compositions (4 members with random races, classes, stats)
- Enemy groups (varied types and counts based on CR budget)
- Grid layouts and terrain

Uses actual SRD monster data and proper D&D CR calculations.
"""

import numpy as np
from typing import Dict, List, Tuple, Optional, Any
import random
import json
import os
import re
from pathlib import Path

from sim.state import GameState, Grid, GridCell, Actor, Position


# =============================================================================
# CR / XP CALCULATIONS (D&D 5e Rules)
# =============================================================================

# CR to XP mapping (from DMG)
CR_TO_XP = {
    "0": 10,
    "1/8": 25,
    "1/4": 50,
    "1/2": 100,
    "1": 200,
    "2": 450,
    "3": 700,
    "4": 1100,
    "5": 1800,
    "6": 2300,
    "7": 2900,
    "8": 3900,
    "9": 5000,
    "10": 5900,
    "11": 7200,
    "12": 8400,
    "13": 10000,
    "14": 11500,
    "15": 13000,
    "16": 15000,
    "17": 18000,
    "18": 20000,
    "19": 22000,
    "20": 25000,
    "21": 33000,
    "22": 41000,
    "23": 50000,
    "24": 62000,
    "25": 75000,
    "26": 90000,
    "27": 105000,
    "28": 120000,
    "29": 135000,
    "30": 155000,
}

# XP thresholds per character level (Easy, Medium, Hard, Deadly)
XP_THRESHOLDS = {
    1: (25, 50, 75, 100),
    2: (50, 100, 150, 200),
    3: (75, 150, 225, 400),
    4: (125, 250, 375, 500),
    5: (250, 500, 750, 1100),
    6: (300, 600, 900, 1400),
    7: (350, 750, 1100, 1700),
    8: (450, 900, 1400, 2100),
    9: (550, 1100, 1600, 2400),
    10: (600, 1200, 1900, 2800),
    11: (800, 1600, 2400, 3600),
    12: (1000, 2000, 3000, 4500),
    13: (1100, 2200, 3400, 5100),
    14: (1250, 2500, 3800, 5700),
    15: (1400, 2800, 4300, 6400),
    16: (1600, 3200, 4800, 7200),
    17: (2000, 3900, 5900, 8800),
    18: (2100, 4200, 6300, 9500),
    19: (2400, 4900, 7300, 10900),
    20: (2800, 5700, 8500, 12700),
}

# Encounter multipliers based on number of monsters
ENCOUNTER_MULTIPLIERS = [
    (1, 1.0),
    (2, 1.5),
    (3, 2.0),
    (6, 2.0),
    (7, 2.5),
    (10, 2.5),
    (11, 3.0),
    (14, 3.0),
    (15, 4.0),
]


def parse_cr(cr_string: str) -> float:
    """Parse CR string to float value."""
    if not cr_string:
        return 0.0
    
    # Extract just the CR number (e.g., "10 (5,900 XP)" -> "10")
    match = re.match(r"([\d/]+)", cr_string.strip())
    if not match:
        return 0.0
    
    cr = match.group(1)
    
    if "/" in cr:
        num, denom = cr.split("/")
        return int(num) / int(denom)
    return float(cr)


def cr_to_xp(cr_string: str) -> int:
    """Convert CR string to XP value."""
    # Extract just the CR part
    match = re.match(r"([\d/]+)", str(cr_string).strip())
    if not match:
        return 0
    
    cr = match.group(1)
    return CR_TO_XP.get(cr, 0)


def get_encounter_multiplier(num_monsters: int) -> float:
    """Get XP multiplier based on number of monsters."""
    for threshold, multiplier in reversed(ENCOUNTER_MULTIPLIERS):
        if num_monsters >= threshold:
            return multiplier
    return 1.0


def calculate_party_xp_threshold(party_level: int, party_size: int, difficulty: str) -> int:
    """Calculate XP threshold for a party."""
    difficulty_idx = {"easy": 0, "medium": 1, "hard": 2, "deadly": 3}.get(difficulty, 1)
    
    level = max(1, min(20, party_level))
    threshold_per_char = XP_THRESHOLDS[level][difficulty_idx]
    
    return threshold_per_char * party_size


def calculate_encounter_difficulty(monsters: List[Dict], party_level: int, party_size: int) -> str:
    """Calculate encounter difficulty rating."""
    if not monsters:
        return "trivial"
    
    # Sum base XP
    total_xp = sum(cr_to_xp(m.get("Challenge", "0")) for m in monsters)
    
    # Apply multiplier
    multiplier = get_encounter_multiplier(len(monsters))
    adjusted_xp = total_xp * multiplier
    
    # Compare to thresholds
    for difficulty in ["deadly", "hard", "medium", "easy"]:
        threshold = calculate_party_xp_threshold(party_level, party_size, difficulty)
        if adjusted_xp >= threshold:
            return difficulty
    
    return "trivial"


# =============================================================================
# MONSTER DATA LOADING AND PARSING
# =============================================================================

_MONSTERS_CACHE: Optional[List[Dict]] = None


def load_srd_monsters() -> List[Dict]:
    """Load and cache SRD monsters."""
    global _MONSTERS_CACHE
    
    if _MONSTERS_CACHE is not None:
        return _MONSTERS_CACHE
    
    # Find the data directory
    project_root = Path(__file__).parent.parent
    monsters_path = project_root / "data" / "SRD_Monsters.json"
    
    if not monsters_path.exists():
        print(f"Warning: SRD_Monsters.json not found at {monsters_path}")
        _MONSTERS_CACHE = []
        return _MONSTERS_CACHE
    
    with open(monsters_path, "r", encoding="utf-8") as f:
        _MONSTERS_CACHE = json.load(f)
    
    return _MONSTERS_CACHE


def parse_hp(hp_string: str) -> Tuple[int, str]:
    """Parse HP string like '135 (18d10 + 36)' -> (135, '18d10+36')"""
    if not hp_string:
        return (10, "2d8")
    
    match = re.match(r"(\d+)\s*\(([^)]+)\)", hp_string)
    if match:
        avg_hp = int(match.group(1))
        dice = match.group(2).replace(" ", "")
        return (avg_hp, dice)
    
    # Try just a number
    try:
        return (int(hp_string), "1d8")
    except:
        return (10, "2d8")


def parse_ac(ac_string: str) -> int:
    """Parse AC string like '17 (Natural Armor)' -> 17"""
    if not ac_string:
        return 10
    
    match = re.match(r"(\d+)", ac_string)
    if match:
        return int(match.group(1))
    return 10


def parse_speed(speed_string: str) -> int:
    """Parse speed string like '30 ft., fly 60 ft.' -> 30 (base walking speed)"""
    if not speed_string:
        return 30
    
    match = re.match(r"(\d+)\s*ft", speed_string)
    if match:
        return int(match.group(1))
    return 30


def parse_ability_score(value: str) -> int:
    """Parse ability score string to int."""
    try:
        return int(value)
    except:
        return 10


def parse_attack_from_action(action_text: str) -> Optional[Dict]:
    """
    Parse an attack from action HTML text.
    
    Example: '<em><strong>Bite.</strong></em> <em>Melee Weapon Attack:</em> +9 to hit, 
    reach 10 ft., one target. <em>Hit:</em> 12 (2d6 + 5) bludgeoning damage.'
    
    Also handles spell attacks and special melee attacks.
    """
    # Extract attack name
    name_match = re.search(r"<strong>([^<]+)</strong>", action_text)
    if not name_match:
        return None
    
    name = name_match.group(1).strip().rstrip(".")
    
    # Check if it's a weapon attack or spell attack
    is_melee = "Melee Weapon Attack" in action_text or "Melee Attack" in action_text
    is_ranged = "Ranged Weapon Attack" in action_text or "Ranged Attack" in action_text
    is_spell_attack = "Melee Spell Attack" in action_text or "Ranged Spell Attack" in action_text
    
    # Also check for attacks that just have "+X to hit" and "Hit:" patterns
    has_to_hit = re.search(r"\+\d+\s*to hit", action_text) is not None
    has_hit_damage = re.search(r"Hit:</em>", action_text) is not None or re.search(r"<em>Hit:</em>", action_text) is not None
    
    if not (is_melee or is_ranged or is_spell_attack or (has_to_hit and has_hit_damage)):
        return None
    
    # Extract to-hit bonus
    to_hit_match = re.search(r"\+(\d+)\s*to hit", action_text)
    to_hit = int(to_hit_match.group(1)) if to_hit_match else 0
    
    # Extract reach/range
    if is_ranged or "Ranged" in action_text:
        range_match = re.search(r"range\s*(\d+)(?:/\d+)?\s*ft", action_text)
        attack_range = int(range_match.group(1)) if range_match else 30
        attack_type = "ranged"
    else:
        reach_match = re.search(r"reach\s*(\d+)\s*ft", action_text)
        attack_range = int(reach_match.group(1)) if reach_match else 5
        attack_type = "melee"
    
    # Extract damage - try multiple patterns
    damage = "1d6"
    damage_match = re.search(r"Hit:</em>\s*\d+\s*\(([^)]+)\)", action_text)
    if damage_match:
        damage = damage_match.group(1).replace(" ", "")
    else:
        # Try alternate pattern without HTML
        damage_match = re.search(r"(\d+d\d+(?:\s*\+\s*\d+)?)", action_text)
        if damage_match:
            damage = damage_match.group(1).replace(" ", "")
    
    # Extract damage type
    damage_type_match = re.search(r"\)\s*(\w+)\s*damage", action_text)
    if not damage_type_match:
        damage_type_match = re.search(r"(\w+)\s*damage", action_text)
    damage_type = damage_type_match.group(1) if damage_type_match else "bludgeoning"
    
    return {
        "name": name,
        "to_hit": to_hit,
        "damage": damage,
        "damage_type": damage_type,
        "range": attack_range,
        "attack_type": attack_type
    }


def parse_ability_from_action(action_text: str, monster_name: str = "") -> Optional[Dict]:
    """
    Parse a special ability from action HTML text.
    
    Handles breath weapons, frightful presence, etc.
    """
    # Extract ability name
    name_match = re.search(r"<strong>([^<]+)</strong>", action_text)
    if not name_match:
        return None
    
    name = name_match.group(1).strip().rstrip(".")
    
    # Skip if it's a basic attack (already handled)
    if "Weapon Attack" in action_text:
        return None
    
    # Skip Multiattack (it's a meta-action)
    if name.lower() == "multiattack":
        return None
    
    ability = {
        "name": name,
        "description": re.sub(r"<[^>]+>", "", action_text)[:200],  # Strip HTML, truncate
        "type": "utility"
    }
    
    # Check for recharge
    recharge_match = re.search(r"Recharge\s*(\d+)[-–](\d+)", action_text)
    if recharge_match:
        ability["recharge"] = f"{recharge_match.group(1)}-{recharge_match.group(2)}"
    
    # Check for uses per day
    uses_match = re.search(r"\((\d+)/Day\)", action_text)
    if uses_match:
        ability["uses_per_day"] = int(uses_match.group(1))
    
    # Check for saving throw
    save_match = re.search(r"DC\s*(\d+)\s*(\w+)\s*saving throw", action_text)
    if save_match:
        ability["type"] = "save"
        ability["dc"] = int(save_match.group(1))
        ability["save"] = save_match.group(2).upper()[:3]
    
    # Check for damage
    damage_match = re.search(r"(\d+d\d+(?:\s*\+\s*\d+)?)\s*(\w+)?\s*damage", action_text)
    if damage_match:
        ability["damage"] = damage_match.group(1).replace(" ", "")
        if damage_match.group(2):
            ability["damage_type"] = damage_match.group(2)
    
    # Check for range
    range_match = re.search(r"(\d+)[- ]foot|(\d+)\s*ft", action_text)
    if range_match:
        ability["range"] = int(range_match.group(1) or range_match.group(2))
    
    # Detect breath weapons
    if "breath" in name.lower() or "breath" in action_text.lower():
        ability["type"] = "save"
        ability["is_breath_weapon"] = True
    
    # Detect frightful presence
    if "frightful" in name.lower():
        ability["type"] = "save"
        ability["condition"] = "frightened"
    
    return ability


def parse_traits_from_monster(traits_text: str) -> List[str]:
    """Extract trait names from traits HTML text."""
    if not traits_text:
        return []
    
    traits = []
    
    # Find all trait names
    for match in re.finditer(r"<strong>([^<]+)</strong>", traits_text):
        trait_name = match.group(1).strip().rstrip(".")
        # Normalize to snake_case
        trait_key = trait_name.lower().replace(" ", "_").replace("(", "").replace(")", "")
        traits.append(trait_key)
    
    return traits


def normalize_monster(raw: Dict) -> Dict:
    """Convert raw SRD monster data to normalized format."""
    avg_hp, hp_dice = parse_hp(raw.get("Hit Points", ""))
    
    monster = {
        "name": raw.get("name", "Unknown"),
        "cr": raw.get("Challenge", "0"),
        "cr_numeric": parse_cr(raw.get("Challenge", "0")),
        "xp": cr_to_xp(raw.get("Challenge", "0")),
        "hp": avg_hp,
        "hp_dice": hp_dice,
        "ac": parse_ac(raw.get("Armor Class", "")),
        "speed_ft": parse_speed(raw.get("Speed", "")),
        "abilities": {
            "STR": parse_ability_score(raw.get("STR", "10")),
            "DEX": parse_ability_score(raw.get("DEX", "10")),
            "CON": parse_ability_score(raw.get("CON", "10")),
            "INT": parse_ability_score(raw.get("INT", "10")),
            "WIS": parse_ability_score(raw.get("WIS", "10")),
            "CHA": parse_ability_score(raw.get("CHA", "10")),
        },
        "attacks": [],
        "special_abilities": [],
        "traits": [],
    }
    
    # Parse actions
    actions_text = raw.get("Actions", "")
    if actions_text:
        # Split by paragraph
        for para in re.split(r"</p>\s*<p>", actions_text):
            # Try to parse as attack
            attack = parse_attack_from_action(para)
            if attack:
                monster["attacks"].append(attack)
            else:
                # Try to parse as ability
                ability = parse_ability_from_action(para, monster["name"])
                if ability:
                    monster["special_abilities"].append(ability)
    
    # Parse traits
    traits_text = raw.get("Traits", "")
    if traits_text:
        monster["traits"] = parse_traits_from_monster(traits_text)
    
    # Ensure at least one attack
    if not monster["attacks"]:
        # Default unarmed strike
        str_mod = (monster["abilities"]["STR"] - 10) // 2
        monster["attacks"].append({
            "name": "Slam",
            "to_hit": max(0, str_mod + 2),
            "damage": f"1d4+{max(0, str_mod)}",
            "range": 5,
            "attack_type": "melee"
        })
    
    return monster


def is_combat_appropriate(raw: Dict) -> bool:
    """
    Filter out non-combat-appropriate creatures.
    
    Excludes: beasts with no meaningful attacks, swarms that need special handling,
    aquatic-only creatures, etc.
    """
    name = raw.get("name", "").lower()
    meta = raw.get("meta", "").lower()
    
    # Exclude certain creature types that don't make sense in land combat
    exclude_names = [
        "sea horse", "reef shark", "hunter shark", "giant sea horse",
        "killer whale", "octopus", "giant octopus", "quipper",
        "deer", "frog", "giant frog", "rat", "bat", "cat", "goat",
        "hawk", "owl", "raven", "weasel", "crab", "scorpion",
        "spider", "centipede", "lizard", "snake",  # Tiny beasts
        "swarm",  # Swarms need special handling
        "commoner", "noble", "guard",  # Basic NPCs
    ]
    
    for exclude in exclude_names:
        if exclude in name:
            return False
    
    # Require at least one attack
    actions = raw.get("Actions", "")
    if not actions or "attack" not in actions.lower():
        return False
    
    # Exclude purely aquatic creatures (swim speed only)
    speed = raw.get("Speed", "")
    if "swim" in speed.lower() and "ft." not in speed.split(",")[0]:
        return False
    
    return True


def get_monsters_by_cr_range(min_cr: float, max_cr: float, combat_only: bool = True) -> List[Dict]:
    """Get all monsters within a CR range."""
    raw_monsters = load_srd_monsters()
    
    monsters = []
    for raw in raw_monsters:
        cr = parse_cr(raw.get("Challenge", "0"))
        if min_cr <= cr <= max_cr:
            if combat_only and not is_combat_appropriate(raw):
                continue
            monsters.append(normalize_monster(raw))
    
    return monsters


# =============================================================================
# RACE DATA
# =============================================================================

RACES = {
    "Human": {"stat_bonuses": {"STR": 1, "DEX": 1, "CON": 1, "INT": 1, "WIS": 1, "CHA": 1}, "speed": 30},
    "Elf": {"stat_bonuses": {"DEX": 2}, "speed": 30},
    "Dwarf": {"stat_bonuses": {"CON": 2}, "speed": 25},
    "Halfling": {"stat_bonuses": {"DEX": 2}, "speed": 25},
    "Dragonborn": {"stat_bonuses": {"STR": 2, "CHA": 1}, "speed": 30},
    "Gnome": {"stat_bonuses": {"INT": 2}, "speed": 25},
    "Half-Elf": {"stat_bonuses": {"CHA": 2, "DEX": 1, "CON": 1}, "speed": 30},
    "Half-Orc": {"stat_bonuses": {"STR": 2, "CON": 1}, "speed": 30},
    "Tiefling": {"stat_bonuses": {"CHA": 2, "INT": 1}, "speed": 30},
}

# =============================================================================
# CLASS DATA
# =============================================================================

CLASSES = {
    "Fighter": {
        "hit_die": 10,
        "primary_stat": "STR",
        "save_proficiencies": ["STR", "CON"],
        "armor_class_base": 16,
        "attacks": [
            {"name": "Longsword", "to_hit": 5, "damage": "1d8+3", "range": 5, "attack_type": "melee"},
        ],
    },
    "Rogue": {
        "hit_die": 8,
        "primary_stat": "DEX",
        "save_proficiencies": ["DEX", "INT"],
        "armor_class_base": 14,
        "attacks": [
            {"name": "Shortsword", "to_hit": 5, "damage": "1d6+3", "range": 5, "attack_type": "melee"},
            {"name": "Shortbow", "to_hit": 5, "damage": "1d6+3", "range": 80, "attack_type": "ranged"},
        ],
    },
    "Wizard": {
        "hit_die": 6,
        "primary_stat": "INT",
        "save_proficiencies": ["INT", "WIS"],
        "armor_class_base": 12,
        "attacks": [
            {"name": "Dagger", "to_hit": 2, "damage": "1d4", "range": 5, "attack_type": "melee"},
        ],
        "spells": [
            {"name": "Fire Bolt", "type": "attack", "to_hit": 5, "damage": "1d10", "range": 120},
            {"name": "Magic Missile", "type": "auto", "damage": "3d4+3", "range": 120},
        ],
    },
    "Cleric": {
        "hit_die": 8,
        "primary_stat": "WIS",
        "save_proficiencies": ["WIS", "CHA"],
        "armor_class_base": 18,
        "attacks": [
            {"name": "Mace", "to_hit": 4, "damage": "1d6+2", "range": 5, "attack_type": "melee"},
        ],
        "spells": [
            {"name": "Sacred Flame", "type": "save", "dc": 13, "save": "DEX", "damage": "1d8", "range": 60},
            {"name": "Guiding Bolt", "type": "attack", "to_hit": 5, "damage": "4d6", "range": 120},
        ],
    },
    "Barbarian": {
        "hit_die": 12,
        "primary_stat": "STR",
        "save_proficiencies": ["STR", "CON"],
        "armor_class_base": 14,
        "attacks": [
            {"name": "Greataxe", "to_hit": 5, "damage": "1d12+3", "range": 5, "attack_type": "melee"},
        ],
    },
    "Ranger": {
        "hit_die": 10,
        "primary_stat": "DEX",
        "save_proficiencies": ["STR", "DEX"],
        "armor_class_base": 15,
        "attacks": [
            {"name": "Shortsword", "to_hit": 5, "damage": "1d6+3", "range": 5, "attack_type": "melee"},
            {"name": "Longbow", "to_hit": 5, "damage": "1d8+3", "range": 150, "attack_type": "ranged"},
        ],
    },
    "Paladin": {
        "hit_die": 10,
        "primary_stat": "STR",
        "save_proficiencies": ["WIS", "CHA"],
        "armor_class_base": 18,
        "attacks": [
            {"name": "Longsword", "to_hit": 5, "damage": "1d8+3", "range": 5, "attack_type": "melee"},
        ],
    },
    "Warlock": {
        "hit_die": 8,
        "primary_stat": "CHA",
        "save_proficiencies": ["WIS", "CHA"],
        "armor_class_base": 13,
        "attacks": [
            {"name": "Dagger", "to_hit": 2, "damage": "1d4", "range": 5, "attack_type": "melee"},
        ],
        "spells": [
            {"name": "Eldritch Blast", "type": "attack", "to_hit": 5, "damage": "1d10", "range": 120},
        ],
    },
}


# =============================================================================
# GENERATOR FUNCTIONS
# =============================================================================

def roll_stats(rng: np.random.Generator) -> Dict[str, int]:
    """Roll 4d6 drop lowest for each stat."""
    stats = {}
    for stat in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]:
        rolls = sorted([rng.integers(1, 7) for _ in range(4)])
        stats[stat] = sum(rolls[1:])
    return stats


def roll_hp_from_dice(dice_string: str, rng: np.random.Generator) -> int:
    """Roll HP from dice string like '18d10+36'."""
    # Parse dice string
    match = re.match(r"(\d+)d(\d+)([+-]\d+)?", dice_string.replace(" ", ""))
    if not match:
        return 10
    
    num_dice = int(match.group(1))
    die_size = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0
    
    total = sum(rng.integers(1, die_size + 1) for _ in range(num_dice)) + modifier
    return max(1, total)


def generate_party_member(
    rng: np.random.Generator,
    level: int = 1,
    position: Position = None
) -> Actor:
    """Generate a random party member."""
    race_name = rng.choice(list(RACES.keys()))
    class_name = rng.choice(list(CLASSES.keys()))
    
    race = RACES[race_name]
    char_class = CLASSES[class_name]
    
    # Roll stats
    base_stats = roll_stats(rng)
    
    # Apply racial bonuses
    abilities = base_stats.copy()
    for stat, bonus in race.get("stat_bonuses", {}).items():
        abilities[stat] = abilities.get(stat, 10) + bonus
    
    # Calculate HP
    hit_die = char_class["hit_die"]
    hp = hit_die + (abilities["CON"] - 10) // 2
    for _ in range(level - 1):
        hp += rng.integers(1, hit_die + 1) + (abilities["CON"] - 10) // 2
    hp = max(1, hp)
    
    # Calculate AC
    ac = char_class["armor_class_base"]
    if class_name in ["Rogue", "Ranger", "Warlock"]:
        ac += min(2, (abilities["DEX"] - 10) // 2)
    elif class_name == "Barbarian":
        ac = 10 + (abilities["DEX"] - 10) // 2 + (abilities["CON"] - 10) // 2
    
    # Get attacks with proper to-hit
    attacks = []
    for atk in char_class.get("attacks", []):
        attack = atk.copy()
        if atk.get("attack_type") == "ranged":
            attack["to_hit"] = 2 + (abilities["DEX"] - 10) // 2
        else:
            primary = char_class["primary_stat"]
            attack["to_hit"] = 2 + (abilities[primary] - 10) // 2
        attacks.append(attack)
    
    spells = char_class.get("spells", [])
    
    name = f"{race_name} {class_name}"
    
    return Actor(
        name=name,
        hp=hp,
        max_hp=hp,
        ac=ac,
        speed_ft=race.get("speed", 30),
        pos=position or Position(0, 0),
        abilities=abilities,
        attacks=attacks,
        spells=spells,
        conditions=[],
        traits="",
    )


def generate_enemy_from_monster(
    monster: Dict,
    rng: np.random.Generator,
    position: Position = None,
    index: int = 0
) -> Actor:
    """Generate an enemy from normalized monster data."""
    # Roll HP
    hp = roll_hp_from_dice(monster["hp_dice"], rng)
    
    # Build traits string
    traits_str = ",".join(monster.get("traits", []))
    
    return Actor(
        name=f"{monster['name']} {index + 1}" if index > 0 else monster['name'],
        hp=hp,
        max_hp=hp,
        ac=monster["ac"],
        speed_ft=monster.get("speed_ft", 30),
        pos=position or Position(0, 0),
        abilities=monster.get("abilities", {}).copy(),
        attacks=[a.copy() for a in monster.get("attacks", [])],
        spells=[],
        conditions=[],
        traits=traits_str,
        special_abilities=[a.copy() for a in monster.get("special_abilities", [])]
    )


def select_encounter_monsters(
    rng: np.random.Generator,
    party_level: int,
    party_size: int,
    target_difficulty: str = "medium"
) -> List[Dict]:
    """
    Select monsters for an encounter based on CR budget.
    
    Uses proper D&D encounter building rules.
    """
    # Calculate XP budget
    xp_budget = calculate_party_xp_threshold(party_level, party_size, target_difficulty)
    
    # Determine CR range to search
    # Party level roughly maps to appropriate CR
    max_cr = party_level + 2  # Can handle slightly higher CR
    min_cr = max(0, party_level - 3)  # Don't go too low
    
    # For deadly encounters, allow higher CR
    if target_difficulty == "deadly":
        max_cr = party_level + 4
    
    # Get available monsters
    available = get_monsters_by_cr_range(min_cr, max_cr)
    
    if not available:
        # Fallback: get any low-CR monsters
        available = get_monsters_by_cr_range(0, 2)
    
    if not available:
        return []
    
    # Build encounter
    selected = []
    remaining_budget = xp_budget
    max_monsters = 8  # Cap to prevent huge encounters
    
    # Sort by XP descending for better selection
    available_sorted = sorted(available, key=lambda m: m["xp"], reverse=True)
    
    while remaining_budget > 0 and len(selected) < max_monsters:
        # Calculate effective budget considering multiplier
        multiplier = get_encounter_multiplier(len(selected) + 1)
        effective_budget = remaining_budget / multiplier
        
        # Find monsters that fit
        candidates = [m for m in available_sorted if m["xp"] <= effective_budget]
        
        if not candidates:
            break
        
        # Randomly select from candidates (weighted toward higher CR)
        weights = np.array([m["xp"] for m in candidates], dtype=float)
        weights = weights / weights.sum()
        
        monster = rng.choice(candidates, p=weights)
        selected.append(monster)
        
        # Recalculate remaining budget
        total_xp = sum(m["xp"] for m in selected)
        multiplier = get_encounter_multiplier(len(selected))
        adjusted_xp = total_xp * multiplier
        remaining_budget = xp_budget - adjusted_xp
    
    return selected


def generate_grid(
    rng: np.random.Generator,
    width: int = 15,
    height: int = 15,
    wall_density: float = 0.1,
    difficult_density: float = 0.15
) -> Grid:
    """Generate a random combat grid."""
    grid = Grid(width=width, height=height)
    
    for y in range(height):
        for x in range(width):
            roll = rng.random()
            if roll < wall_density:
                grid.cells[y][x] = GridCell(tile="wall")
            elif roll < wall_density + difficult_density:
                grid.cells[y][x] = GridCell(tile="difficult")
            else:
                grid.cells[y][x] = GridCell(tile="open")
    
    # Clear spawn areas
    for y in range(height):
        for x in range(3):
            grid.cells[y][x] = GridCell(tile="open")
        for x in range(width - 3, width):
            grid.cells[y][x] = GridCell(tile="open")
    
    return grid


def generate_scenario(
    rng: np.random.Generator,
    party_size: int = 4,
    party_level: int = 1,
    difficulty: str = "medium",
    grid_width: int = 15,
    grid_height: int = 15
) -> GameState:
    """
    Generate a complete random combat scenario.
    
    Args:
        rng: Random number generator
        party_size: Number of party members (default 4)
        party_level: Party level (default 1)
        difficulty: "easy", "medium", "hard", or "deadly"
        grid_width: Grid width
        grid_height: Grid height
        
    Returns:
        Complete GameState ready for combat
    """
    state = GameState()
    
    # Generate grid
    state.grid = generate_grid(rng, grid_width, grid_height)
    
    # Generate party
    for i in range(party_size):
        y_pos = grid_height // 2 - party_size // 2 + i
        y_pos = max(1, min(grid_height - 2, y_pos))
        position = Position(x=1, y=y_pos)
        
        member = generate_party_member(rng, level=party_level, position=position)
        state.party.append(member)
    
    # Select monsters based on CR budget
    monsters = select_encounter_monsters(rng, party_level, party_size, difficulty)
    
    # Generate enemies
    for i, monster in enumerate(monsters):
        y_pos = grid_height // 2 - len(monsters) // 2 + i
        y_pos = max(1, min(grid_height - 2, y_pos))
        position = Position(x=grid_width - 2, y=y_pos)
        
        enemy = generate_enemy_from_monster(monster, rng, position, i)
        state.enemies.append(enemy)
    
    # Generate initiative order
    all_actors = []
    for i, p in enumerate(state.party):
        init_roll = rng.integers(1, 21) + (p.abilities.get("DEX", 10) - 10) // 2
        all_actors.append({"kind": "party", "idx": i, "init": init_roll, "name": p.name})
    
    for i, e in enumerate(state.enemies):
        init_roll = rng.integers(1, 21) + (e.abilities.get("DEX", 10) - 10) // 2
        all_actors.append({"kind": "enemy", "idx": i, "init": init_roll, "name": e.name})
    
    all_actors.sort(key=lambda x: x["init"], reverse=True)
    state.initiative_order = all_actors
    
    state.in_combat = True
    state.round = 1
    state.turn_index = 0
    
    return state


class ScenarioGenerator:
    """
    Scenario generator for batch training.
    
    Generates diverse combat scenarios using SRD monster data
    and proper CR calculations.
    """
    
    def __init__(
        self,
        seed: int = None,
        party_size: int = 4,
        party_level_range: Tuple[int, int] = (1, 3),
        difficulties: List[str] = None,
        grid_size_range: Tuple[int, int] = (12, 20)
    ):
        self.base_seed = seed or 42
        self.party_size = party_size
        self.party_level_range = party_level_range
        self.difficulties = difficulties or ["easy", "medium", "hard", "deadly"]
        self.grid_size_range = grid_size_range
        
        self.scenario_count = 0
        
        # Pre-load monsters
        load_srd_monsters()
    
    def generate(self, seed: int = None) -> GameState:
        """Generate a random scenario."""
        if seed is None:
            seed = self.base_seed + self.scenario_count
        
        rng = np.random.default_rng(seed)
        self.scenario_count += 1
        
        party_level = rng.integers(self.party_level_range[0], self.party_level_range[1] + 1)
        difficulty = rng.choice(self.difficulties)
        grid_size = rng.integers(self.grid_size_range[0], self.grid_size_range[1] + 1)
        
        return generate_scenario(
            rng=rng,
            party_size=self.party_size,
            party_level=party_level,
            difficulty=difficulty,
            grid_width=grid_size,
            grid_height=grid_size
        )
    
    def generate_batch(self, count: int, base_seed: int = None) -> List[GameState]:
        """Generate multiple scenarios."""
        if base_seed is not None:
            self.base_seed = base_seed
            self.scenario_count = 0
        
        return [self.generate() for _ in range(count)]


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    print("Testing Scenario Generator with SRD Monsters")
    print("=" * 60)
    
    # Test monster loading
    monsters = load_srd_monsters()
    print(f"Loaded {len(monsters)} monsters from SRD")
    
    # Show CR distribution
    cr_counts = {}
    for m in monsters:
        cr = parse_cr(m.get("Challenge", "0"))
        cr_counts[cr] = cr_counts.get(cr, 0) + 1
    
    print(f"\nCR Distribution (sample):")
    for cr in sorted(cr_counts.keys())[:10]:
        print(f"  CR {cr}: {cr_counts[cr]} monsters")
    
    # Test scenario generation
    print("\n" + "=" * 60)
    generator = ScenarioGenerator(seed=42, party_level_range=(1, 5))
    
    for i in range(5):
        state = generator.generate()
        
        # Calculate actual difficulty
        monster_xp = sum(
            cr_to_xp(e.abilities.get("cr", "0")) if isinstance(e.abilities.get("cr"), str) 
            else 0 for e in state.enemies
        )
        
        print(f"\nScenario {i + 1}:")
        print(f"  Grid: {state.grid.width}x{state.grid.height}")
        print(f"  Party ({len(state.party)}):")
        for p in state.party:
            print(f"    - {p.name}: HP {p.hp}, AC {p.ac}")
        print(f"  Enemies ({len(state.enemies)}):")
        for e in state.enemies:
            abilities_str = ""
            if hasattr(e, 'special_abilities') and e.special_abilities:
                abilities_str = f" [Abilities: {len(e.special_abilities)}]"
            print(f"    - {e.name}: HP {e.hp}, AC {e.ac}, Attacks: {len(e.attacks)}{abilities_str}")
            # Show attacks
            for atk in e.attacks[:2]:  # Show first 2
                print(f"        {atk['name']}: +{atk['to_hit']} to hit, {atk['damage']} dmg")
    
    print("\n" + "=" * 60)
    print("Scenario generation OK!")
