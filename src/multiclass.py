"""
Multiclassing System for Virtual DM

This module handles:
- Character class list management (multiple classes with levels)
- Feature aggregation across classes
- Multiclass spell slot calculation
- Warlock pact magic (separate from normal slots)
- Migration from single-class to multiclass schema
"""

import json
import os
from typing import Dict, Any, List, Optional, Tuple
from math import floor


# ============================================================
# MULTICLASS RULES LOADING
# ============================================================

_MULTICLASS_RULES_CACHE: Optional[Dict] = None


def _get_multiclass_rules_path() -> str:
    """Get path to multiclass_rules.json."""
    base_dir = os.path.dirname(__file__)
    return os.path.join(base_dir, "..", "data", "multiclass_rules.json")


def load_multiclass_rules() -> Dict:
    """
    Load multiclass rules from data/multiclass_rules.json.
    Returns dict with caster contributions, spell slots, prerequisites, etc.
    """
    global _MULTICLASS_RULES_CACHE
    
    if _MULTICLASS_RULES_CACHE is not None:
        return _MULTICLASS_RULES_CACHE
    
    try:
        with open(_get_multiclass_rules_path(), "r", encoding="utf-8") as f:
            _MULTICLASS_RULES_CACHE = json.load(f)
        return _MULTICLASS_RULES_CACHE
    except Exception as e:
        # Fallback to minimal defaults
        _MULTICLASS_RULES_CACHE = {
            "max_total_level": 20,
            "allow_multiclass": True,
            "caster_contributions": {
                "full": {"caster_level_multiplier": 1.0, "classes": ["wizard", "sorcerer", "cleric", "druid", "bard"]},
                "half": {"caster_level_multiplier": 0.5, "classes": ["paladin", "ranger"]},
                "pact": {"separate_slots": True, "classes": ["warlock"]},
                "none": {"caster_level_multiplier": 0, "classes": ["fighter", "barbarian", "rogue", "monk"]}
            },
            "multiclass_spell_slots": {},
            "warlock_pact_slots": {},
            "multiclass_prerequisites": {},
            "multiclass_proficiencies": {}
        }
        return _MULTICLASS_RULES_CACHE


def get_max_total_level() -> int:
    """Get maximum total character level (sum of all class levels)."""
    rules = load_multiclass_rules()
    return rules.get("max_total_level", 20)


# ============================================================
# CHARACTER CLASS MANAGEMENT
# ============================================================

def get_classes(character: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Get the list of classes for a character.
    Returns list of {"class_id": str, "level": int} dicts.
    
    Handles both new multiclass format and legacy single-class format.
    """
    # New format: character["classes"] is a list
    if "classes" in character and isinstance(character["classes"], list):
        return character["classes"]
    
    # Legacy format: character["class"] is a string, character["level"] is int
    legacy_class = character.get("class", "")
    legacy_level = character.get("level", 1)
    
    if legacy_class:
        return [{"class_id": legacy_class, "level": legacy_level}]
    
    return []


def get_total_level(character: Dict[str, Any]) -> int:
    """
    Get total character level (sum of all class levels).
    """
    classes = get_classes(character)
    return sum(c.get("level", 0) for c in classes)


def get_class_level(character: Dict[str, Any], class_id: str) -> int:
    """
    Get the level in a specific class.
    Returns 0 if character doesn't have that class.
    """
    class_id_lower = class_id.lower()
    for c in get_classes(character):
        if c.get("class_id", "").lower() == class_id_lower:
            return c.get("level", 0)
    return 0


def get_primary_class(character: Dict[str, Any]) -> Optional[str]:
    """
    Get the primary class (highest level, or first if tied).
    Returns None if no classes.
    """
    classes = get_classes(character)
    if not classes:
        return None
    
    # Check for explicit primary_class_id
    if character.get("primary_class_id"):
        return character["primary_class_id"]
    
    # Otherwise, return highest level class
    sorted_classes = sorted(classes, key=lambda c: c.get("level", 0), reverse=True)
    return sorted_classes[0].get("class_id") if sorted_classes else None


def has_class(character: Dict[str, Any], class_id: str) -> bool:
    """Check if character has a specific class."""
    return get_class_level(character, class_id) > 0


def add_class(character: Dict[str, Any], class_id: str, level: int = 1) -> bool:
    """
    Add a new class to the character or increment existing class level.
    Returns True if successful, False if would exceed max level.
    """
    rules = load_multiclass_rules()
    max_level = rules.get("max_total_level", 20)
    
    current_total = get_total_level(character)
    if current_total + level > max_level:
        return False
    
    # Ensure classes list exists
    if "classes" not in character or not isinstance(character["classes"], list):
        # Migrate from legacy format if needed
        migrate_to_multiclass(character)
    
    # Check if class already exists
    for c in character["classes"]:
        if c.get("class_id", "").lower() == class_id.lower():
            c["level"] = c.get("level", 0) + level
            _update_level_total(character)
            return True
    
    # Add new class
    character["classes"].append({"class_id": class_id, "level": level})
    _update_level_total(character)
    return True


def increment_class_level(character: Dict[str, Any], class_id: str) -> Dict[str, Any]:
    """
    Increment a class level by 1.
    Returns result dict with success status and details.
    """
    rules = load_multiclass_rules()
    max_level = rules.get("max_total_level", 20)
    
    current_total = get_total_level(character)
    if current_total >= max_level:
        return {
            "success": False,
            "message": f"Already at maximum level ({max_level})",
            "old_level": current_total,
            "new_level": current_total
        }
    
    # Ensure multiclass format
    migrate_to_multiclass(character)
    
    class_id_lower = class_id.lower()
    found = False
    old_class_level = 0
    
    for c in character["classes"]:
        if c.get("class_id", "").lower() == class_id_lower:
            old_class_level = c.get("level", 0)
            c["level"] = old_class_level + 1
            found = True
            break
    
    if not found:
        # Adding a new class at level 1
        character["classes"].append({"class_id": class_id, "level": 1})
        old_class_level = 0
    
    _update_level_total(character)
    
    return {
        "success": True,
        "message": f"Gained level in {class_id}",
        "class_id": class_id,
        "old_class_level": old_class_level,
        "new_class_level": old_class_level + 1,
        "old_total_level": current_total,
        "new_total_level": current_total + 1
    }


def _update_level_total(character: Dict[str, Any]):
    """Update the level_total field based on classes."""
    character["level_total"] = get_total_level(character)
    # Also update legacy "level" field for compatibility
    character["level"] = character["level_total"]


# ============================================================
# SCHEMA MIGRATION
# ============================================================

def migrate_to_multiclass(character: Dict[str, Any]) -> bool:
    """
    Migrate a character from legacy single-class format to multiclass format.
    Returns True if migration was performed, False if already in new format.
    """
    # Already has multiclass format
    if "classes" in character and isinstance(character["classes"], list):
        # Ensure level_total is set
        if "level_total" not in character:
            character["level_total"] = get_total_level(character)
        return False
    
    # Migrate from legacy format
    legacy_class = character.get("class", "")
    legacy_level = character.get("level", 1)
    
    if legacy_class:
        character["classes"] = [{"class_id": legacy_class, "level": legacy_level}]
    else:
        character["classes"] = []
    
    character["level_total"] = legacy_level
    
    # Set primary class to the original class
    if legacy_class:
        character["primary_class_id"] = legacy_class
    
    return True


def is_multiclass(character: Dict[str, Any]) -> bool:
    """Check if character has multiple classes."""
    classes = get_classes(character)
    return len(classes) > 1


# ============================================================
# FEATURE AGGREGATION
# ============================================================

def get_features_for_character(character: Dict[str, Any], class_data: Dict[str, Dict] = None) -> List[Dict[str, Any]]:
    """
    Aggregate features from all classes up to their respective levels.
    
    Args:
        character: Character dict
        class_data: Optional dict mapping class_id to class definition (from SRD_Classes.json)
                   If not provided, returns features already stored on character.
    
    Returns:
        List of feature dicts with source class info, avoiding duplicates by feature name.
    """
    features = []
    seen_features = set()
    
    classes = get_classes(character)
    
    for class_entry in classes:
        class_id = class_entry.get("class_id", "")
        class_level = class_entry.get("level", 0)
        
        if class_data and class_id in class_data:
            cls = class_data[class_id]
            levels = cls.get("levels", {})
            
            # Collect features from level 1 to class_level
            for lvl in range(1, class_level + 1):
                level_data = levels.get(str(lvl), {})
                level_features = level_data.get("features_at_level", [])
                
                for feat in level_features:
                    if isinstance(feat, str):
                        feat_name = feat
                        feat_dict = {"name": feat, "source_class": class_id, "source_level": lvl}
                    elif isinstance(feat, dict):
                        feat_name = feat.get("name", str(feat))
                        feat_dict = {**feat, "source_class": class_id, "source_level": lvl}
                    else:
                        continue
                    
                    # Avoid duplicates by feature name
                    if feat_name not in seen_features:
                        seen_features.add(feat_name)
                        features.append(feat_dict)
    
    # Also include any features already on the character
    char_features = character.get("features", [])
    for feat in char_features:
        if isinstance(feat, str):
            if feat not in seen_features:
                seen_features.add(feat)
                features.append({"name": feat, "source_class": "character", "source_level": 0})
        elif isinstance(feat, dict):
            feat_name = feat.get("name", str(feat))
            if feat_name not in seen_features:
                seen_features.add(feat_name)
                features.append(feat)
    
    return features


# ============================================================
# CASTER LEVEL & SPELL SLOTS
# ============================================================

def get_caster_type(class_id: str) -> str:
    """
    Get the caster type for a class (full/half/third/pact/none).
    """
    rules = load_multiclass_rules()
    contributions = rules.get("caster_contributions", {})
    
    class_lower = class_id.lower()
    
    for caster_type, data in contributions.items():
        classes = data.get("classes", [])
        if class_lower in [c.lower() for c in classes]:
            return caster_type
    
    return "none"


def calculate_caster_level(character: Dict[str, Any]) -> int:
    """
    Calculate combined caster level for multiclass spell slots.
    Warlock levels do NOT contribute (they use separate pact slots).
    """
    rules = load_multiclass_rules()
    contributions = rules.get("caster_contributions", {})
    
    caster_level = 0.0
    
    for class_entry in get_classes(character):
        class_id = class_entry.get("class_id", "")
        class_level = class_entry.get("level", 0)
        caster_type = get_caster_type(class_id)
        
        if caster_type == "pact":
            # Warlock doesn't contribute to combined caster level
            continue
        
        type_data = contributions.get(caster_type, {})
        multiplier = type_data.get("caster_level_multiplier", 0)
        
        caster_level += class_level * multiplier
    
    return floor(caster_level)


def get_multiclass_spell_slots(character: Dict[str, Any]) -> Dict[str, int]:
    """
    Get spell slots based on combined caster level.
    Returns dict mapping spell level (str) to number of slots.
    """
    caster_level = calculate_caster_level(character)
    
    if caster_level <= 0:
        return {}
    
    rules = load_multiclass_rules()
    slot_table = rules.get("multiclass_spell_slots", {})
    
    # Cap at 20
    caster_level = min(caster_level, 20)
    
    return slot_table.get(str(caster_level), {})


def get_warlock_pact_slots(character: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get warlock pact magic slots (separate from normal slots).
    Returns {"slots": int, "slot_level": int} or empty dict if no warlock levels.
    """
    warlock_level = get_class_level(character, "warlock")
    
    if warlock_level <= 0:
        return {}
    
    rules = load_multiclass_rules()
    pact_table = rules.get("warlock_pact_slots", {})
    
    return pact_table.get(str(warlock_level), {"slots": 1, "slot_level": 1})


def get_all_spell_slots(character: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get all spell slots for a character, including both normal and pact slots.
    
    Returns:
        {
            "normal_slots": {spell_level: count, ...},
            "pact_slots": {"slots": int, "slot_level": int} or {},
            "caster_level": int
        }
    """
    return {
        "normal_slots": get_multiclass_spell_slots(character),
        "pact_slots": get_warlock_pact_slots(character),
        "caster_level": calculate_caster_level(character)
    }


# ============================================================
# MULTICLASS PREREQUISITES
# ============================================================

def check_multiclass_prerequisites(character: Dict[str, Any], target_class: str) -> Tuple[bool, str]:
    """
    Check if a character meets the prerequisites to multiclass into a class.
    
    Args:
        character: Character dict with abilities
        target_class: Class ID to multiclass into
        
    Returns:
        Tuple of (can_multiclass: bool, reason: str)
    """
    rules = load_multiclass_rules()
    prereqs = rules.get("multiclass_prerequisites", {})
    
    target_lower = target_class.lower()
    class_prereqs = prereqs.get(target_lower, {})
    
    if not class_prereqs:
        # No prerequisites defined - allow
        return True, "No prerequisites required"
    
    abilities = character.get("abilities", {})
    
    # Check each prerequisite
    missing = []
    or_ability = class_prereqs.get("or")
    
    for ability, required in class_prereqs.items():
        if ability == "or":
            continue
        
        score = abilities.get(ability, 10)
        
        if score < required:
            # Check if there's an "or" alternative
            if or_ability:
                alt_score = abilities.get(or_ability, 10)
                if alt_score >= required:
                    continue  # Met via alternative
            missing.append(f"{ability} {required}+ (have {score})")
    
    if missing:
        return False, f"Missing prerequisites: {', '.join(missing)}"
    
    return True, "Prerequisites met"


def get_multiclass_proficiencies(class_id: str) -> Dict[str, Any]:
    """
    Get proficiencies gained when multiclassing INTO a class.
    These are different from starting class proficiencies.
    """
    rules = load_multiclass_rules()
    profs = rules.get("multiclass_proficiencies", {})
    return profs.get(class_id.lower(), {"armor": [], "weapons": [], "skills": 0})


# ============================================================
# BAB CALCULATION FOR MULTICLASS
# ============================================================

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
    "paladin": "full",
    "ranger": "full",
    "marshal": "full",
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


def calculate_multiclass_bab(character: Dict[str, Any]) -> int:
    """
    Calculate BAB for a multiclass character.
    BAB from each class is calculated separately and summed.
    """
    total_bab = 0
    
    for class_entry in get_classes(character):
        class_id = class_entry.get("class_id", "").lower()
        class_level = class_entry.get("level", 0)
        
        bab_type = CLASS_BAB_TYPE.get(class_id, "half")
        calc = BAB_PROGRESSION.get(bab_type, BAB_PROGRESSION["half"])
        
        total_bab += calc(class_level)
    
    return total_bab


# ============================================================
# HIT POINTS FOR MULTICLASS
# ============================================================

# Hit die by class
HIT_DIE_BY_CLASS = {
    "barbarian": 12,
    "fighter": 10,
    "paladin": 10,
    "ranger": 10,
    "marshal": 10,
    "cleric": 8,
    "druid": 8,
    "monk": 8,
    "rogue": 8,
    "bard": 8,
    "warlock": 8,
    "artificer": 8,
    "spellblade": 8,
    "sorcerer": 6,
    "wizard": 6,
}


def get_hit_die_for_class(class_id: str) -> int:
    """Get hit die size for a class."""
    return HIT_DIE_BY_CLASS.get(class_id.lower(), 8)


def calculate_hp_increase_for_class(character: Dict[str, Any], class_id: str, roll_hp: bool = False) -> Tuple[int, str]:
    """
    Calculate HP increase for gaining a level in a specific class.
    
    Args:
        character: Character dict
        class_id: Class gaining the level
        roll_hp: If True, roll hit die. If False, use average.
        
    Returns:
        Tuple of (hp_gained, description)
    """
    import random
    
    hit_die = get_hit_die_for_class(class_id)
    
    # Get CON modifier
    abilities = character.get("abilities", {})
    con_score = abilities.get("CON", 10)
    con_mod = (con_score - 10) // 2
    
    if roll_hp:
        roll = random.randint(1, hit_die)
        hp_gained = max(1, roll + con_mod)
        desc = f"Rolled d{hit_die}: {roll} + CON mod ({con_mod}) = {hp_gained} HP ({class_id})"
    else:
        avg = (hit_die // 2) + 1
        hp_gained = max(1, avg + con_mod)
        desc = f"Average d{hit_die}: {avg} + CON mod ({con_mod}) = {hp_gained} HP ({class_id})"
    
    return hp_gained, desc


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def get_class_summary(character: Dict[str, Any]) -> str:
    """
    Get a human-readable summary of character classes.
    E.g., "Fighter 5 / Wizard 3" or "Rogue 10"
    """
    classes = get_classes(character)
    if not classes:
        return "No class"
    
    parts = [f"{c.get('class_id', '?')} {c.get('level', 0)}" for c in classes]
    return " / ".join(parts)


def get_available_classes_for_multiclass(character: Dict[str, Any], all_classes: List[str]) -> List[Dict[str, Any]]:
    """
    Get list of classes available for multiclassing, with prerequisite status.
    
    Args:
        character: Character dict
        all_classes: List of all class IDs
        
    Returns:
        List of {"class_id": str, "can_add": bool, "reason": str, "current_level": int}
    """
    result = []
    
    for class_id in all_classes:
        can_add, reason = check_multiclass_prerequisites(character, class_id)
        current_level = get_class_level(character, class_id)
        
        result.append({
            "class_id": class_id,
            "can_add": can_add,
            "reason": reason,
            "current_level": current_level
        })
    
    return result
