import os
import sys
import json
import random
import re
import time
from datetime import datetime
from typing import Tuple, Dict, Any, List

import streamlit as st

import tracemalloc
tracemalloc.start()

# Add project root to path for ai/sim module imports
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Try to import AI logging module (optional - UI works without it)
try:
    from ai.logger import get_ui_logger, set_ui_logging_enabled
    AI_LOGGING_AVAILABLE = True
except ImportError:
    AI_LOGGING_AVAILABLE = False
    def get_ui_logger():
        return None
    def set_ui_logging_enabled(enabled):
        pass

# Import leveling system
try:
    from src.leveling import (
        award_xp, level_up_character, level_up_character_multiclass,
        migrate_character_xp, get_xp_progress, get_level_from_xp, 
        get_xp_for_level, get_hit_die_for_class, get_bab_for_level,
        calculate_hp_increase_for_class
    )
    LEVELING_AVAILABLE = True
except ImportError:
    LEVELING_AVAILABLE = False
    # Stub functions if module not available
    def award_xp(char, amount, reason="", source=""):
        return {"leveled_up": False, "amount": amount}
    def level_up_character(char, roll_hp=False, class_id=None):
        return {"success": False, "message": "Leveling module not available"}
    def level_up_character_multiclass(char, class_id, roll_hp=False):
        return {"success": False, "message": "Leveling module not available"}
    def migrate_character_xp(char):
        return False
    def get_xp_progress(char):
        return {"current_xp": 0, "current_level": 1, "progress_pct": 0}
    def get_level_from_xp(xp):
        return 1
    def get_xp_for_level(level):
        return 0
    def get_hit_die_for_class(cls):
        return 8
    def get_bab_for_level(cls, lvl):
        return lvl // 2
    def calculate_hp_increase_for_class(char, cls, roll_hp=False):
        return (5, "HP calculation unavailable")

# Import multiclass system
try:
    from src.multiclass import (
        migrate_to_multiclass, get_classes, get_total_level, get_class_level,
        get_primary_class, is_multiclass, get_class_summary,
        check_multiclass_prerequisites, get_multiclass_proficiencies,
        get_all_spell_slots, calculate_multiclass_bab,
        get_available_classes_for_multiclass, load_multiclass_rules
    )
    MULTICLASS_AVAILABLE = True
except ImportError:
    MULTICLASS_AVAILABLE = False

# Import XP awards calculator
try:
    from src.xp_awards import (
        calc_encounter_xp, assess_encounter_difficulty, calc_quest_xp,
        get_quest_types, get_xp_for_cr, extract_xp_from_challenge_string,
        get_difficulty_emoji, format_xp
    )
    XP_AWARDS_AVAILABLE = True
except ImportError:
    XP_AWARDS_AVAILABLE = False
    def calc_encounter_xp(monsters, party_size=4, apply_multiplier=False):
        return {"base_xp": 0, "monster_count": 0, "multiplier": 1.0, "adjusted_xp": 0, "xp_per_member": 0, "monsters_breakdown": []}
    def assess_encounter_difficulty(monsters, party_levels):
        return {"difficulty": "unknown", "adjusted_xp": 0, "base_xp": 0, "thresholds": {}, "margin": 0}
    def calc_quest_xp(quest_type, party_levels, custom_multiplier=1.0):
        return {"total_xp": 0, "xp_per_member": 0, "description": ""}
    def get_quest_types():
        return []
    def get_xp_for_cr(cr):
        return 0
    def extract_xp_from_challenge_string(s):
        return 0
    def get_difficulty_emoji(d):
        return "❓"
    def format_xp(xp):
        return str(xp)
    # Stub functions
    def migrate_to_multiclass(char):
        return False
    def get_classes(char):
        cls = char.get("class", "")
        lvl = char.get("level", 1)
        return [{"class_id": cls, "level": lvl}] if cls else []
    def get_total_level(char):
        return char.get("level", 1)
    def get_class_level(char, class_id):
        return char.get("level", 1) if char.get("class", "").lower() == class_id.lower() else 0
    def get_primary_class(char):
        return char.get("class", "")
    def is_multiclass(char):
        return False
    def get_class_summary(char):
        return f"{char.get('class', 'No class')} {char.get('level', 1)}"
    def check_multiclass_prerequisites(char, target_class):
        return True, "Prerequisites not checked"
    def get_multiclass_proficiencies(class_id):
        return {"armor": [], "weapons": [], "skills": 0}
    def get_all_spell_slots(char):
        return {"normal_slots": {}, "pact_slots": {}, "caster_level": 0}
    def calculate_multiclass_bab(char):
        return char.get("bab", 0)
    def get_available_classes_for_multiclass(char, all_classes):
        return [{"class_id": c, "can_add": True, "reason": "", "current_level": 0} for c in all_classes]
    def load_multiclass_rules():
        return {"max_total_level": 20}

# ==============
# PERFORMANCE UTILITIES
# ==============

_perf_timings = {}

def perf_timer(name: str):
    """Context manager for timing code blocks when performance debug is enabled."""
    class Timer:
        def __enter__(self):
            self.start = time.perf_counter()
            return self
        def __exit__(self, *args):
            elapsed = (time.perf_counter() - self.start) * 1000  # ms
            if st.session_state.get("perf_debug", False):
                _perf_timings[name] = elapsed
    return Timer()

def get_perf_timings() -> dict:
    """Return collected performance timings."""
    return _perf_timings.copy()

def clear_perf_timings():
    """Clear performance timings for new render."""
    global _perf_timings
    _perf_timings = {}

# ==============
# CACHED SRD LOADERS
# ==============
# These use st.cache_data to avoid re-parsing JSON files on every Streamlit rerun.
# The cached functions return pure data; session_state is updated by wrapper functions.

@st.cache_data(show_spinner=False)
def _cached_load_json(file_path: str) -> tuple:
    """
    Cached JSON file loader. Returns (data, path) tuple.
    Cache key is the file path - data is reloaded if file changes.
    """
    if not file_path or not os.path.exists(file_path):
        return None, file_path
    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            return json.load(f), file_path
    except Exception:
        return None, file_path

def _find_data_file(candidates: list) -> str | None:
    """Find first existing file from candidates list."""
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

# ==============
# CLASS FEATURE JSON SYSTEM
# ==============
# Load class features from JSON files in data/class_features/
# This allows easy editing of class features without modifying Python code.

_CLASS_FEATURES_CACHE = {}

def _get_class_features_path(class_name: str) -> str | None:
    """Get path to class features JSON file."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(base_dir, "data", "class_features", f"{class_name}.json"),
        os.path.join(base_dir, "data", "class_features", f"{class_name.lower()}.json"),
    ]
    return _find_data_file(candidates)

@st.cache_data(show_spinner=False)
def _load_class_features_json(class_name: str) -> dict | None:
    """Load class features from JSON file. Returns None if not found."""
    path = _get_class_features_path(class_name)
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading class features for {class_name}: {e}")
        return None

def get_class_features_data(class_name: str) -> dict | None:
    """Get class features data, using cache."""
    if class_name not in _CLASS_FEATURES_CACHE:
        _CLASS_FEATURES_CACHE[class_name] = _load_class_features_json(class_name)
    return _CLASS_FEATURES_CACHE[class_name]

def has_json_class_features(class_name: str) -> bool:
    """Check if a class has JSON-based features defined."""
    return get_class_features_data(class_name) is not None

def apply_class_features_from_json(char: dict, class_name: str, level: int, features: list, actions: list):
    """
    Apply class features from JSON data.
    
    Args:
        char: Character dict to modify
        class_name: Name of the class
        level: Current class level
        features: List to append feature descriptions to
        actions: List to append action dicts to
    
    Returns:
        True if features were applied from JSON, False if no JSON found
    """
    class_data = get_class_features_data(class_name)
    if not class_data:
        return False
    
    abilities = char.get("abilities", {})
    
    # Helper to get ability modifier
    def _mod(stat_name):
        return (abilities.get(stat_name, 10) - 10) // 2
    
    # Process class resources (like Martial Dice)
    class_resources = class_data.get("class_resources", {})
    for resource_key, resource_data in class_resources.items():
        resource_name = resource_data.get("name", resource_key)
        
        # Calculate amount based on level scaling
        base_amount = resource_data.get("base_amount", 0)
        amount = base_amount
        for scale in resource_data.get("scaling", []):
            if level >= scale["level"]:
                amount = scale["amount"]
        
        # Calculate die size if applicable
        die_size = None
        for scale in resource_data.get("die_size_scaling", []):
            if level >= scale["level"]:
                die_size = scale["die"]
        
        # Store on character
        if amount > 0:
            ensure_resource(char, resource_name, amount)
        if die_size:
            char[f"{resource_key}_die_size"] = die_size
    
    # Process derived stats (like maneuver DC)
    derived_stats = class_data.get("derived_stats", {})
    for stat_key, stat_data in derived_stats.items():
        if "formula" in stat_data:
            # Parse and evaluate formula
            formula = stat_data["formula"]
            # Simple formula evaluation for common patterns
            if "max(STR_mod, DEX_mod)" in formula:
                str_mod = _mod("STR")
                dex_mod = _mod("DEX")
                bab = int(char.get("bab", 0))
                value = 8 + max(str_mod, dex_mod) + bab
                char[stat_key] = value
        elif "base" in stat_data:
            # Scaling stat
            value = stat_data["base"]
            for scale in stat_data.get("scaling", []):
                if level >= scale["level"]:
                    value = scale["amount"]
            char[f"max_{stat_key}"] = value
    
    # Process level features
    levels_data = class_data.get("levels", {})
    for lvl in range(1, level + 1):
        lvl_key = str(lvl)
        if lvl_key not in levels_data:
            continue
        
        level_features = levels_data[lvl_key].get("features", [])
        for feature in level_features:
            feature_name = feature.get("name", "Unknown Feature")
            feature_type = feature.get("type", "passive")
            description = feature.get("description", "")
            
            # Skip if already added
            if any(feature_name in f for f in features):
                continue
            
            # Handle different feature types
            if feature_type == "class_feature":
                # Generic class feature with description
                # Build dynamic description if needed
                if "grants_resource" in feature:
                    res_key = feature["grants_resource"]
                    res_data = class_resources.get(res_key, {})
                    res_name = res_data.get("name", res_key)
                    amount = char.get("resources", {}).get(res_name, {}).get("current", 0)
                    die_size = char.get(f"{res_key}_die_size", "d6")
                    dc = char.get("maneuver_dc", 10)
                    max_known = char.get("max_maneuvers_known", 3)
                    desc = f"{res_name}: {amount} dice ({die_size}). {max_known} maneuvers known. DC {dc}."
                    features.append(desc)
                else:
                    features.append(f"{feature_name}: {description}")
                
                # Handle pending selections
                if "requires_selection" in feature:
                    sel = feature["requires_selection"]
                    sel_type = sel.get("type")
                    sel_count = sel.get("count", 1)
                    current_selections = char.get(f"{class_name.lower()}_{sel_type}", [])
                    if len(current_selections) < sel_count:
                        char[f"pending_{sel_type}"] = sel_count - len(current_selections)
            
            elif feature_type == "feat_grant":
                features.append(f"{feature_name}: {description}")
                if feature.get("grants_feat_choice"):
                    # Track pending feat choice
                    category = feature.get("feat_category", "any")
                    pending_key = f"pending_{category}"
                    char[pending_key] = char.get(pending_key, 0) + 1
            
            elif feature_type == "resource_action":
                # Feature that grants both a resource and an action
                res_data = feature.get("resource", {})
                res_name = res_data.get("name", feature_name)
                res_amount = res_data.get("amount", 1)
                
                # Check for scaling upgrades
                if feature_type == "resource_upgrade":
                    res_name = feature.get("resource", feature_name)
                    res_amount = feature.get("new_amount", 1)
                
                ensure_resource(char, res_name, res_amount)
                features.append(f"{feature_name}: {description}")
                
                # Add action if defined
                action_data = feature.get("action")
                if action_data and not any(a.get("name") == action_data.get("name") for a in actions):
                    action_entry = {
                        "name": action_data.get("name", feature_name),
                        "resource": res_name,
                        "action_type": action_data.get("action_type", "free"),
                        "description": action_data.get("description", description),
                    }
                    if action_data.get("grants_action"):
                        action_entry["grants_action"] = action_data["grants_action"]
                    if action_data.get("triggers_on"):
                        action_entry["triggers_on"] = action_data["triggers_on"]
                    actions.append(action_entry)
                
                # Set flags
                if "grants_flag" in feature:
                    char[feature["grants_flag"]] = True
            
            elif feature_type == "extra_attack":
                extra_attacks = feature.get("attacks", 1)
                char["extra_attack"] = extra_attacks
                total = feature.get("total_attacks", extra_attacks + 1)
                features.append(f"{feature_name}: Attack {total} times when you take the Attack action.")
            
            elif feature_type == "passive":
                features.append(f"{feature_name}: {description}")
                if "grants_flag" in feature:
                    char[feature["grants_flag"]] = True
                if "grants" in feature:
                    for key, value in feature["grants"].items():
                        char[key] = value
            
            elif feature_type == "passive_and_action":
                features.append(f"{feature_name}: {description}")
                # Apply passive grants
                if "passive" in feature:
                    for key, value in feature["passive"].items():
                        char[key] = value
                # Add action
                action_data = feature.get("action")
                if action_data and not any(a.get("name") == action_data.get("name") for a in actions):
                    actions.append({
                        "name": action_data.get("name", feature_name),
                        "action_type": action_data.get("action_type", "reaction"),
                        "description": action_data.get("description", ""),
                    })
            
            elif feature_type == "weapon_specialization":
                expertise_weapon = char.get("weapon_expertise")
                if expertise_weapon:
                    grants = feature.get("grants", {})
                    char["weapon_expertise_bonus"] = {
                        "weapon": expertise_weapon,
                        "attack_bonus": grants.get("attack_bonus", 0),
                        "reroll_ones": grants.get("reroll_ones", False),
                    }
                    features.append(f"{feature_name} ({expertise_weapon}): {description}")
                else:
                    char["pending_weapon_expertise"] = True
                    features.append(f"{feature_name}: ⚠️ Choose one weapon for expertise! (Pending selection)")
            
            elif feature_type == "weapon_specialization_upgrade":
                expertise_weapon = char.get("weapon_expertise", "chosen weapon")
                char[feature.get("grants_flag", "master_of_weaponry")] = True
                grants = feature.get("grants", {})
                if "weapon_expertise_bonus" in char:
                    char["weapon_expertise_bonus"]["damage_bonus"] = grants.get("damage_bonus", 0)
                    char["weapon_expertise_bonus"]["crit_bonus"] = grants.get("crit_bonus", "")
                features.append(f"{feature_name} ({expertise_weapon}): {description}")
            
            elif feature_type == "resource_upgrade":
                res_name = feature.get("resource", feature_name)
                new_amount = feature.get("new_amount", 1)
                ensure_resource(char, res_name, new_amount)
                features.append(f"{feature_name}: {description}")
            
            elif feature_type == "asi_or_feat":
                # Track ASI/feat opportunity
                char["pending_asi"] = char.get("pending_asi", 0) + 1
                # Don't add to features list - handled separately
            
            elif feature_type == "scaling_update":
                # These are handled by the resource/stat scaling above
                pass
    
    return True


# ==============
# ACTION SCHEMA 
# ==============
# Every action in the system MUST follow this schema so the UI can reason about it deterministically
#
# ACTION_SCHEMA = {
#     "name": str,
#     "type": "attack | save | utility | spell",
#     "action_type": "move | standard | quick | immediate",
#     "to_hit": int | None,         # for attacks
#     "dc": int | None,             # for saves
#     "save": "STR|DEX|CON|INT|WIS|CHA" | None,
#     "damage": "1d6+3" | None,
#     "damage_type": "slashing|fire|etc" | None,
#     "condition": "prone|stunned|etc" | None,
#     "range": int | None,
#     "description": str,
# }

# =========================
# EXAMPLE ACTIONS (SRD)
# =========================

MELEE_WEAPON_ATTACK = {
    "name": "Longsword",
    "type": "attack",
    "action_type": "standard",
    "to_hit": 5,
    "dc": None,
    "save": None,
    "damage": "1d8+3",
    "damage_type": "slashing",
    "condition": None,
    "range": 5,
    "description": "A melee weapon attack with a longsword.",
}

DODGE_ACTION = {
    "name": "Dodge",
    "type": "utility",
    "action_type": "standard",
    "to_hit": None,
    "dc": None,
    "save": None,
    "damage": None,
    "damage_type": None,
    "condition": None,
    "range": None,
    "description": "Until the start of your next turn, you gain +2 AC against attacks you can see.",
}

FIRE_BOLT = {
    "name": "Fire Bolt",
    "type": "spell",
    "action_type": "standard",
    "to_hit": 6,
    "dc": None,
    "save": None,
    "damage": "1d10",
    "damage_type": "fire",
    "condition": None,
    "range": 120,
    "description": "A mote of fire that deals fire damage on hit.",
}

# ==============
# TACTICAL GRID SYSTEM
# ==============
# D&D-style square grid map with terrain, movement, and positioning
# All terrain data is loaded from JSON files in data/terrain/

# Default fallback tiles if JSON fails to load
_DEFAULT_TILES = {
    "open":      {"id": "open", "name": "Open Ground", "move_cost": 1, "blocked": False, "blocks_los": False, "color": "#e8e8e8", "label": ""},
    "wall":      {"id": "wall", "name": "Wall", "move_cost": 999, "blocked": True, "blocks_los": True, "color": "#3a3a3a", "label": "█"},
    "difficult": {"id": "difficult", "name": "Difficult Terrain", "move_cost": 2, "blocked": False, "blocks_los": False, "color": "#a0a060", "label": "~"},
}

# Cached terrain data
_TILES_CACHE = None
_BIOMES_CACHE = None
_HAZARDS_CACHE = None

def _get_terrain_data_path(filename: str) -> str:
    """Get path to terrain data file."""
    base_dir = os.path.dirname(__file__)
    return os.path.join(base_dir, "..", "data", "terrain", filename)

def load_tiles() -> dict:
    """Load tile definitions from tiles.json. Returns dict keyed by tile id."""
    global _TILES_CACHE
    if _TILES_CACHE is not None:
        return _TILES_CACHE
    
    path = _get_terrain_data_path("tiles.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            tiles_list = data.get("tiles", [])
            _TILES_CACHE = {t["id"]: t for t in tiles_list if "id" in t}
            return _TILES_CACHE
    except Exception as e:
        # Fallback to defaults
        _TILES_CACHE = _DEFAULT_TILES
        return _TILES_CACHE

def load_biomes() -> list:
    """Load biome definitions from biomes.json. Returns list of biome dicts."""
    global _BIOMES_CACHE
    if _BIOMES_CACHE is not None:
        return _BIOMES_CACHE
    
    path = _get_terrain_data_path("biomes.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            _BIOMES_CACHE = data.get("biomes", [])
            return _BIOMES_CACHE
    except Exception:
        # Fallback to minimal default
        _BIOMES_CACHE = [{"id": "default", "name": "Default", "description": "Basic terrain", 
                          "tile_weights": {"open": 80, "wall": 10, "difficult": 10},
                          "densities": {"wall": 0.1, "difficult": 0.1, "water": 0},
                          "hazards": [], "hazard_chance": 0,
                          "cluster_style": {"walkers": 4, "steps_per_walker": 30}}]
        return _BIOMES_CACHE

def load_hazards() -> dict:
    """Load hazard definitions from hazards.json. Returns dict keyed by hazard id."""
    global _HAZARDS_CACHE
    if _HAZARDS_CACHE is not None:
        return _HAZARDS_CACHE
    
    path = _get_terrain_data_path("hazards.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            hazards_list = data.get("hazards", [])
            _HAZARDS_CACHE = {h["id"]: h for h in hazards_list if "id" in h}
            return _HAZARDS_CACHE
    except Exception:
        _HAZARDS_CACHE = {}
        return _HAZARDS_CACHE

def get_tile(tile_id: str) -> dict:
    """Get tile definition by id."""
    tiles = load_tiles()
    return tiles.get(tile_id, tiles.get("open", _DEFAULT_TILES["open"]))

def get_tile_ids() -> list:
    """Get ordered list of tile IDs for cycling in edit mode."""
    tiles = load_tiles()
    # Prefer a specific order: open, wall, difficult, water, then others
    preferred_order = ["open", "wall", "difficult", "water"]
    ordered = [tid for tid in preferred_order if tid in tiles]
    # Add any other tiles not in preferred order
    for tid in tiles:
        if tid not in ordered:
            ordered.append(tid)
    return ordered

def get_biome_names() -> list:
    """Get list of available biome names."""
    biomes = load_biomes()
    return [b.get("name", "Unknown") for b in biomes]

def get_biome_config(name: str) -> dict:
    """Get biome config by name."""
    biomes = load_biomes()
    for b in biomes:
        if b.get("name") == name:
            return b
    return biomes[0] if biomes else {}

def get_biome_config_by_id(biome_id: str) -> dict:
    """Get biome config by id."""
    biomes = load_biomes()
    for b in biomes:
        if b.get("id") == biome_id:
            return b
    return biomes[0] if biomes else {}

def get_hazard(hazard_id: str) -> dict:
    """Get hazard definition by id."""
    hazards = load_hazards()
    return hazards.get(hazard_id, {})

def get_hazard_names_for_biome(biome_name: str) -> list:
    """Get list of hazard names available for a biome."""
    biome = get_biome_config(biome_name)
    hazard_ids = biome.get("hazards", [])
    hazards = load_hazards()
    return [hazards[hid].get("name", hid) for hid in hazard_ids if hid in hazards]

def get_hazard_id_by_name(name: str) -> str | None:
    """Get hazard id by its display name."""
    hazards = load_hazards()
    for hid, h in hazards.items():
        if h.get("name") == name:
            return hid
    return None

# Compatibility alias for existing code
def get_terrain_names() -> list:
    """Get list of available terrain/biome names (alias for get_biome_names)."""
    return get_biome_names()

def get_terrain_config(name: str) -> dict:
    """Get terrain config by name (alias for get_biome_config)."""
    return get_biome_config(name)

def init_grid(width: int = 20, height: int = 20, square_size_ft: int = 5) -> dict:
    """Initialize an empty grid."""
    cells = [[{"tile": "open", "hazard": None} for _ in range(width)] for _ in range(height)]
    return {
        "width": width,
        "height": height,
        "square_size_ft": square_size_ft,
        "cells": cells,
        "biome": None,
        "seed": None,
    }

def ensure_grid():
    """Ensure grid exists in session state."""
    if "grid" not in st.session_state or st.session_state.grid is None:
        st.session_state.grid = init_grid()
    return st.session_state.grid

def get_effective_speed(actor: dict) -> int:
    """
    Calculate effective speed including all bonuses.
    Checks for Barbarian Fast Movement, Scout Fast Movement, etc.
    """
    # Base speed from character or default
    base_speed = actor.get("speed_ft", 30)
    
    # Parse speed string if needed
    if isinstance(base_speed, str):
        import re
        match = re.search(r"(\d+)", base_speed)
        base_speed = int(match.group(1)) if match else 30
    
    total_bonus = 0
    
    # Barbarian Fast Movement (+10 ft, not in heavy armor)
    barb_bonus = actor.get("barbarian_speed_bonus", 0)
    if barb_bonus > 0:
        # Check for heavy armor
        equipment_names = [x.lower() for x in (actor.get("equipment") or []) if isinstance(x, str)]
        srd_equipment = st.session_state.get("srd_equipment") or []
        wearing_heavy = False
        for eq_name in equipment_names:
            for item in srd_equipment:
                item_name = (item.get("name") or "").lower()
                if item_name == eq_name or eq_name in item_name or item_name in eq_name:
                    if item.get("armor_category") == "Heavy":
                        wearing_heavy = True
                        break
        if not wearing_heavy:
            total_bonus += barb_bonus
    
    # Scout Fast Movement (+10/+20 ft, light armor only)
    scout_bonus = actor.get("scout_fast_movement", 0)
    if scout_bonus > 0:
        equipment_names = [x.lower() for x in (actor.get("equipment") or []) if isinstance(x, str)]
        srd_equipment = st.session_state.get("srd_equipment") or []
        armor_is_light = True
        for eq_name in equipment_names:
            for item in srd_equipment:
                item_name = (item.get("name") or "").lower()
                if item_name == eq_name or eq_name in item_name or item_name in eq_name:
                    armor_cat = item.get("armor_category", "")
                    if armor_cat in ("Medium", "Heavy"):
                        armor_is_light = False
                        break
        if armor_is_light:
            total_bonus += scout_bonus
    
    # Monk Unarmored Movement bonus
    monk_bonus = actor.get("monk_speed_bonus", 0)
    if monk_bonus > 0:
        # Check for no armor
        equipment_names = [x.lower() for x in (actor.get("equipment") or []) if isinstance(x, str)]
        srd_equipment = st.session_state.get("srd_equipment") or []
        wearing_armor = False
        for eq_name in equipment_names:
            for item in srd_equipment:
                item_name = (item.get("name") or "").lower()
                if item_name == eq_name or eq_name in item_name or item_name in eq_name:
                    if item.get("armor_category") in ("Light", "Medium", "Heavy"):
                        wearing_armor = True
                        break
        if not wearing_armor:
            total_bonus += monk_bonus
    
    return base_speed + total_bonus


def ensure_actor_pos(actor: dict, default_x: int, default_y: int):
    """Ensure actor has a valid position, setting default if missing."""
    pos = actor.get("pos")
    if not isinstance(pos, dict) or "x" not in pos or "y" not in pos:
        actor["pos"] = {"x": default_x, "y": default_y}

    if "speed_ft" not in actor:
        actor["speed_ft"] = 30
    if "size" not in actor:
        actor["size"] = 1
    return actor


def auto_place_actors():
    """Auto-place actors without positions on the grid."""
    grid = ensure_grid()
    width = grid["width"]
    height = grid["height"]
    
    # Place party on left edge (column 0-1)
    party_y = 1
    for i, actor in enumerate(st.session_state.get("party", [])):
        if not isinstance(actor.get("pos"), dict) or "x" not in actor["pos"] or "y" not in actor["pos"]:
            x = i % 2  # Columns 0-1
            y = party_y + (i // 2)
            if y >= height - 1:
                y = height - 2
            ensure_actor_pos(actor, x, y)
    
    # Place enemies on right edge (columns width-2 to width-1)
    enemy_y = 1
    for i, actor in enumerate(st.session_state.get("enemies", [])):
        if not isinstance(actor.get("pos"), dict) or "x" not in actor["pos"] or "y" not in actor["pos"]:
            x = width - 1 - (i % 2)  # Columns width-1 to width-2
            y = enemy_y + (i // 2)
            if y >= height - 1:
                y = height - 2
            ensure_actor_pos(actor, x, y)

def get_cell(grid: dict, x: int, y: int) -> dict:
    """Get cell at position, or None if out of bounds."""
    if x < 0 or y < 0 or y >= grid["height"] or x >= grid["width"]:
        return None
    return grid["cells"][y][x]

def set_cell_tile(grid: dict, x: int, y: int, tile: str):
    """Set tile type at position."""
    if 0 <= x < grid["width"] and 0 <= y < grid["height"]:
        grid["cells"][y][x]["tile"] = tile

def set_cell_hazard(grid: dict, x: int, y: int, hazard: str | None):
    """Set hazard at position."""
    if 0 <= x < grid["width"] and 0 <= y < grid["height"]:
        grid["cells"][y][x]["hazard"] = hazard

def is_cell_blocked(grid: dict, x: int, y: int) -> bool:
    """Check if cell is blocked (wall, water, or out of bounds)."""
    cell = get_cell(grid, x, y)
    if cell is None:
        return True
    tile_id = cell.get("tile", "open")
    tile = get_tile(tile_id)
    return tile.get("blocked", False)

def get_move_cost(grid: dict, x: int, y: int) -> int:
    """Get movement cost for a cell."""
    cell = get_cell(grid, x, y)
    if cell is None:
        return 999
    tile_id = cell.get("tile", "open")
    tile = get_tile(tile_id)
    return tile.get("move_cost", 1)

def is_cell_occupied(x: int, y: int, exclude_actor: dict = None) -> bool:
    """Check if cell is occupied by any actor."""
    for actor in st.session_state.get("party", []):
        if actor is exclude_actor:
            continue
        pos = actor.get("pos")
        if pos and pos.get("x") == x and pos.get("y") == y:
            return True
    for actor in st.session_state.get("enemies", []):
        if actor is exclude_actor:
            continue
        pos = actor.get("pos")
        if pos and pos.get("x") == x and pos.get("y") == y:
            return True
    return False

def get_actor_at(x: int, y: int) -> tuple:
    """Get actor at position. Returns (kind, idx, actor) or (None, None, None)."""
    for i, actor in enumerate(st.session_state.get("party", [])):
        pos = actor.get("pos")
        if pos and pos.get("x") == x and pos.get("y") == y:
            return ("party", i, actor)
    for i, actor in enumerate(st.session_state.get("enemies", [])):
        pos = actor.get("pos")
        if pos and pos.get("x") == x and pos.get("y") == y:
            return ("enemy", i, actor)
    return (None, None, None)

def dijkstra_reachable(grid: dict, start_x: int, start_y: int, max_cost: int, exclude_actor: dict = None) -> dict:
    """
    Find all reachable cells from start position within max_cost.
    Returns dict of {(x,y): cost} for reachable cells.
    Uses Dijkstra's algorithm with terrain costs.
    """
    import heapq
    
    width = grid["width"]
    height = grid["height"]
    
    # Priority queue: (cost, x, y)
    pq = [(0, start_x, start_y)]
    visited = {}
    
    # 8-directional movement (including diagonals)
    directions = [
        (-1, 0), (1, 0), (0, -1), (0, 1),  # Cardinal
        (-1, -1), (-1, 1), (1, -1), (1, 1)  # Diagonal
    ]
    
    while pq:
        cost, x, y = heapq.heappop(pq)
        
        if (x, y) in visited:
            continue
        visited[(x, y)] = cost
        
        for dx, dy in directions:
            nx, ny = x + dx, y + dy
            
            if nx < 0 or ny < 0 or nx >= width or ny >= height:
                continue
            if (nx, ny) in visited:
                continue
            if is_cell_blocked(grid, nx, ny):
                continue
            
            # Diagonal movement uses destination tile cost
            move_cost = get_move_cost(grid, nx, ny)
            new_cost = cost + move_cost
            
            if new_cost <= max_cost:
                # Can only end on unoccupied squares (except start)
                if not is_cell_occupied(nx, ny, exclude_actor) or (nx == start_x and ny == start_y):
                    heapq.heappush(pq, (new_cost, nx, ny))
    
    return visited

def find_path(grid: dict, start_x: int, start_y: int, end_x: int, end_y: int, max_cost: int, exclude_actor: dict = None) -> list | None:
    """
    Find shortest path from start to end within max_cost.
    Returns list of (x, y) tuples or None if no valid path.
    Uses A* algorithm.
    """
    import heapq
    
    width = grid["width"]
    height = grid["height"]
    
    def heuristic(x, y):
        return max(abs(x - end_x), abs(y - end_y))  # Chebyshev distance
    
    # Priority queue: (f_score, g_score, x, y, path)
    start_h = heuristic(start_x, start_y)
    pq = [(start_h, 0, start_x, start_y, [(start_x, start_y)])]
    visited = set()
    
    directions = [
        (-1, 0), (1, 0), (0, -1), (0, 1),
        (-1, -1), (-1, 1), (1, -1), (1, 1)
    ]
    
    while pq:
        f, g, x, y, path = heapq.heappop(pq)
        
        if x == end_x and y == end_y:
            return path
        
        if (x, y) in visited:
            continue
        visited.add((x, y))
        
        for dx, dy in directions:
            nx, ny = x + dx, y + dy
            
            if nx < 0 or ny < 0 or nx >= width or ny >= height:
                continue
            if (nx, ny) in visited:
                continue
            if is_cell_blocked(grid, nx, ny):
                continue
            
            move_cost = get_move_cost(grid, nx, ny)
            new_g = g + move_cost
            
            if new_g > max_cost:
                continue
            
            # Cannot end on occupied square (unless it's the destination and empty)
            if nx == end_x and ny == end_y:
                if is_cell_occupied(nx, ny, exclude_actor):
                    continue
            
            new_f = new_g + heuristic(nx, ny)
            new_path = path + [(nx, ny)]
            heapq.heappush(pq, (new_f, new_g, nx, ny, new_path))
    
    return None

def generate_map(width: int, height: int, biome_name: str, seed: int) -> dict:
    """
    Generate a procedural map based on biome configuration from biomes.json.
    Uses random walkers for cluster generation with cluster_style settings.
    """
    import random as rng
    rng.seed(seed)
    
    # Initialize grid
    grid = init_grid(width, height)
    grid["biome"] = biome_name
    grid["seed"] = seed
    
    # Get biome config from JSON
    biome = get_biome_config(biome_name)
    if not biome:
        return grid
    
    # Get densities from biome config
    densities = biome.get("densities", {})
    wall_density = densities.get("wall", 0.1)
    difficult_density = densities.get("difficult", 0.15)
    water_density = densities.get("water", 0.0)
    hazard_chance = biome.get("hazard_chance", 0.05)
    hazard_ids = biome.get("hazards", [])
    
    # Get cluster style from biome
    cluster_style = biome.get("cluster_style", {"walkers": 5, "steps_per_walker": 35})
    num_walkers = cluster_style.get("walkers", 5)
    steps_per_walker = cluster_style.get("steps_per_walker", 35)
    
    # Calculate target counts
    total_cells = width * height
    target_walls = int(total_cells * wall_density)
    target_difficult = int(total_cells * difficult_density)
    target_water = int(total_cells * water_density)
    
    # Spawn safety zones (keep clear)
    spawn_cols_left = 2
    spawn_cols_right = 2
    
    def is_spawn_zone(x, y):
        return x < spawn_cols_left or x >= width - spawn_cols_right
    
    def is_tile_blocked(tile_id: str) -> bool:
        """Check if tile type is blocked using tiles.json data."""
        tile = get_tile(tile_id)
        return tile.get("blocked", False)
    
    def random_walker(tile_type: str, target_count: int):
        """Place tiles using random walker algorithm for natural clusters."""
        placed = 0
        attempts = 0
        max_attempts = target_count * 10
        
        # Cluster size range based on biome cluster_style
        min_cluster = max(2, steps_per_walker // 10)
        max_cluster = max(min_cluster + 2, steps_per_walker // 5)
        
        while placed < target_count and attempts < max_attempts:
            attempts += 1
            
            # Random starting point (avoid spawn zones for blocked tiles)
            if is_tile_blocked(tile_type):
                if width - spawn_cols_right - spawn_cols_left <= 0:
                    break
                start_x = rng.randint(spawn_cols_left, width - spawn_cols_right - 1)
            else:
                start_x = rng.randint(0, width - 1)
            start_y = rng.randint(0, height - 1)
            
            if is_spawn_zone(start_x, start_y) and is_tile_blocked(tile_type):
                continue
            
            # Random walk to create cluster
            cluster_size = rng.randint(min_cluster, max_cluster)
            x, y = start_x, start_y
            
            for _ in range(cluster_size):
                if placed >= target_count:
                    break
                
                if 0 <= x < width and 0 <= y < height:
                    cell = grid["cells"][y][x]
                    if cell["tile"] == "open" and not is_spawn_zone(x, y):
                        cell["tile"] = tile_type
                        placed += 1
                
                # Random walk direction
                dx = rng.choice([-1, 0, 1])
                dy = rng.choice([-1, 0, 1])
                x = max(0, min(width - 1, x + dx))
                y = max(0, min(height - 1, y + dy))
    
    # Generate terrain clusters
    if target_walls > 0:
        random_walker("wall", target_walls)
    if target_water > 0:
        random_walker("water", target_water)
    if target_difficult > 0:
        random_walker("difficult", target_difficult)
    
    # Sprinkle hazards on non-blocked tiles
    if hazard_ids and hazard_chance > 0:
        for y in range(height):
            for x in range(width):
                if is_spawn_zone(x, y):
                    continue
                cell = grid["cells"][y][x]
                tile = get_tile(cell["tile"])
                if not tile.get("blocked", False):
                    if rng.random() < hazard_chance:
                        cell["hazard"] = rng.choice(hazard_ids)
    
    # Ensure spawn zones are clear
    for y in range(height):
        for x in range(spawn_cols_left):
            grid["cells"][y][x] = {"tile": "open", "hazard": None}
        for x in range(width - spawn_cols_right, width):
            grid["cells"][y][x] = {"tile": "open", "hazard": None}
    
    return grid

def render_grid_html(grid: dict, selected_actor: dict | None, reachable: dict | None, 
                     show_coords: bool, edit_mode: bool) -> str:
    """
    Render grid as HTML canvas with JavaScript for interaction.
    Returns HTML string to be rendered via st.components.v1.html.
    """
    width = grid["width"]
    height = grid["height"]
    cell_size = 28  # pixels per cell
    canvas_width = width * cell_size + 2
    canvas_height = height * cell_size + 2
    
    # Build cell data as JSON using tiles.json
    cells_data = []
    for y in range(height):
        row = []
        for x in range(width):
            cell = grid["cells"][y][x]
            tile_id = cell.get("tile", "open")
            hazard = cell.get("hazard")
            tile = get_tile(tile_id)
            color = tile.get("color", "#e8e8e8")
            blocked = tile.get("blocked", False)
            row.append({
                "tile": tile_id,
                "color": color,
                "hazard": hazard,
                "blocked": blocked
            })
        cells_data.append(row)
    
    # Build actor data
    actors_data = []
    for i, actor in enumerate(st.session_state.get("party", [])):
        pos = actor.get("pos")
        if pos:
            actors_data.append({
                "kind": "party",
                "idx": i,
                "x": pos["x"],
                "y": pos["y"],
                "name": actor.get("name", f"PC{i+1}")[:6],
                "color": "#2060c0"
            })
    for i, actor in enumerate(st.session_state.get("enemies", [])):
        pos = actor.get("pos")
        if pos:
            actors_data.append({
                "kind": "enemy",
                "idx": i,
                "x": pos["x"],
                "y": pos["y"],
                "name": actor.get("name", f"E{i+1}")[:6],
                "color": "#c02020"
            })
    
    # Selected actor info
    sel_x, sel_y = -1, -1
    if selected_actor:
        kind = selected_actor.get("kind")
        idx = selected_actor.get("idx")
        if kind == "party" and idx < len(st.session_state.get("party", [])):
            pos = st.session_state.party[idx].get("pos")
            if pos:
                sel_x, sel_y = pos["x"], pos["y"]
        elif kind == "enemy" and idx < len(st.session_state.get("enemies", [])):
            pos = st.session_state.enemies[idx].get("pos")
            if pos:
                sel_x, sel_y = pos["x"], pos["y"]
    
    # Reachable cells
    reachable_set = list(reachable.keys()) if reachable else []
    
    html = f'''
<!DOCTYPE html>
<html>
<head>
<style>
body {{ margin: 0; padding: 0; font-family: Arial, sans-serif; }}
canvas {{ border: 1px solid #333; cursor: pointer; }}
#info {{ font-size: 11px; color: #666; margin-top: 4px; }}
</style>
</head>
<body>
<canvas id="grid" width="{canvas_width}" height="{canvas_height}"></canvas>
<div id="info">Click to select/move</div>
<script>
const CELL_SIZE = {cell_size};
const WIDTH = {width};
const HEIGHT = {height};
const cells = {json.dumps(cells_data)};
const actors = {json.dumps(actors_data)};
const selX = {sel_x};
const selY = {sel_y};
const reachable = new Set({json.dumps([[r[0], r[1]] for r in reachable_set])}.map(p => p[0] + "," + p[1]));
const showCoords = {str(show_coords).lower()};
const editMode = {str(edit_mode).lower()};

const canvas = document.getElementById("grid");
const ctx = canvas.getContext("2d");

function draw() {{
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    // Draw cells
    for (let y = 0; y < HEIGHT; y++) {{
        for (let x = 0; x < WIDTH; x++) {{
            const cell = cells[y][x];
            const px = x * CELL_SIZE + 1;
            const py = y * CELL_SIZE + 1;
            
            // Base color
            ctx.fillStyle = cell.color;
            ctx.fillRect(px, py, CELL_SIZE - 1, CELL_SIZE - 1);
            
            // Reachable highlight
            if (reachable.has(x + "," + y) && !cell.blocked) {{
                ctx.fillStyle = "rgba(100, 200, 100, 0.3)";
                ctx.fillRect(px, py, CELL_SIZE - 1, CELL_SIZE - 1);
            }}
            
            // Hazard indicator
            if (cell.hazard) {{
                ctx.fillStyle = "rgba(255, 100, 0, 0.4)";
                ctx.beginPath();
                ctx.arc(px + CELL_SIZE/2, py + CELL_SIZE/2, 4, 0, Math.PI * 2);
                ctx.fill();
            }}
            
            // Grid lines
            ctx.strokeStyle = "#999";
            ctx.lineWidth = 0.5;
            ctx.strokeRect(px, py, CELL_SIZE - 1, CELL_SIZE - 1);
            
            // Coordinates
            if (showCoords) {{
                ctx.fillStyle = "#666";
                ctx.font = "7px Arial";
                ctx.fillText(x + "," + y, px + 1, py + 8);
            }}
        }}
    }}
    
    // Draw selected cell highlight
    if (selX >= 0 && selY >= 0) {{
        const px = selX * CELL_SIZE + 1;
        const py = selY * CELL_SIZE + 1;
        ctx.strokeStyle = "#ffcc00";
        ctx.lineWidth = 3;
        ctx.strokeRect(px + 1, py + 1, CELL_SIZE - 3, CELL_SIZE - 3);
    }}
    
    // Draw actors
    for (const actor of actors) {{
        const px = actor.x * CELL_SIZE + 1;
        const py = actor.y * CELL_SIZE + 1;
        
        // Actor background
        ctx.fillStyle = actor.color;
        ctx.fillRect(px + 2, py + 2, CELL_SIZE - 5, CELL_SIZE - 5);
        
        // Actor name
        ctx.fillStyle = "#fff";
        ctx.font = "bold 8px Arial";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(actor.name, px + CELL_SIZE/2, py + CELL_SIZE/2);
    }}
}}

canvas.addEventListener("click", function(e) {{
    const rect = canvas.getBoundingClientRect();

    // Translate click position into canvas pixel space (handles CSS scaling)
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;

    const cx = (e.clientX - rect.left) * scaleX;
    const cy = (e.clientY - rect.top) * scaleY;

    const x = Math.floor(cx / CELL_SIZE);
    const y = Math.floor(cy / CELL_SIZE);
    
    if (x >= 0 && x < WIDTH && y >= 0 && y < HEIGHT) {{
        
        // Send click to Streamlit via query params
        const url = new URL(window.parent.location);
        url.searchParams.set("grid_click_x", x);
        url.searchParams.set("grid_click_y", y);
        url.searchParams.set("grid_click_t", Date.now());
        window.parent.history.replaceState({{}}, "", url);
        
        // Also update info
        const cell = cells[y][x];
        document.getElementById("info").textContent = 
            "Clicked: (" + x + "," + y + ") - " + cell.tile + 
            (cell.hazard ? " [" + cell.hazard + "]" : "");
    }}
}});

draw();
</script>
</body>
</html>
'''
    return html

# ==============
# ATTACK HELPERS
# ==============
# Unified helpers to read attack fields consistently across the codebase.
# Standardized fields: name, to_hit (int), damage (str), damage_type (str optional), reach (opt), range (opt), source (opt)

def get_attack_to_hit(a: dict) -> int:
    """
    Extract to_hit bonus from an attack dict.
    Supports both 'to_hit' and legacy 'attack_bonus' fields.
    Returns 0 if missing or invalid.
    """
    if not isinstance(a, dict):
        return 0
    val = a.get("to_hit")
    if val is None:
        val = a.get("attack_bonus")
    if val is None:
        val = a.get("bonus")
    if val is None:
        return 0
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str):
        s = val.strip()
        if s.startswith(("+", "-")) and s[1:].isdigit():
            return int(s)
        if s.isdigit():
            return int(s)
    return 0


def get_attack_damage(a: dict) -> str:
    """
    Extract damage string from an attack dict.
    Returns "—" if missing or invalid.
    """
    if not isinstance(a, dict):
        return "—"
    val = a.get("damage")
    if val is None:
        val = a.get("damage_dice")
    if val is None:
        return "—"
    if isinstance(val, str) and val.strip():
        return val.strip()
    return "—"


def get_attack_damage_type(a: dict) -> str:
    """
    Extract damage type string from an attack dict.
    Returns empty string if missing.
    """
    if not isinstance(a, dict):
        return ""
    val = a.get("damage_type") or a.get("damage_type_name") or ""
    return str(val).strip()


def normalize_attack(a: dict) -> dict:
    """
    Normalize an attack dict to ensure it has all standard fields.
    This creates a new dict with consistent field names.
    """
    if not isinstance(a, dict):
        return {"name": "Attack", "to_hit": 0, "damage": "—", "damage_type": "", "source": "unknown"}
    return {
        "name": a.get("name", "Attack"),
        "to_hit": get_attack_to_hit(a),
        "damage": get_attack_damage(a),
        "damage_type": get_attack_damage_type(a),
        "reach": a.get("reach"),
        "range": a.get("range"),
        "source": a.get("source", ""),
    }


# ==============
# STATE VALIDATION
# ==============

def debug_validate_state() -> list:
    """
    Validate session state for schema consistency.
    Returns a list of warning messages (empty if all valid).
    """
    warnings = []
    
    # Validate initiative_order entries
    for i, ent in enumerate(st.session_state.get("initiative_order", [])):
        kind = ent.get("kind")
        if kind not in {"party", "enemy"}:
            warnings.append(f"Initiative entry {i} has invalid kind '{kind}' (expected 'party' or 'enemy')")
    
    # Validate party attacks
    for pi, char in enumerate(st.session_state.get("party", [])):
        char_name = char.get("name", f"Party member {pi}")
        for ai, atk in enumerate(char.get("attacks", [])):
            if not isinstance(atk, dict):
                warnings.append(f"{char_name} attack {ai}: not a dict")
                continue
            if not atk.get("name"):
                warnings.append(f"{char_name} attack {ai}: missing 'name'")
            to_hit = atk.get("to_hit", atk.get("attack_bonus"))
            if to_hit is not None and not isinstance(to_hit, (int, float)):
                warnings.append(f"{char_name} attack '{atk.get('name', ai)}': to_hit is not an int")
            dmg = atk.get("damage")
            if dmg is not None and not isinstance(dmg, str):
                warnings.append(f"{char_name} attack '{atk.get('name', ai)}': damage is not a string")
    
    # Validate enemy attacks
    for ei, enemy in enumerate(st.session_state.get("enemies", [])):
        enemy_name = enemy.get("name", f"Enemy {ei}")
        for ai, atk in enumerate(enemy.get("attacks", [])):
            if not isinstance(atk, dict):
                warnings.append(f"{enemy_name} attack {ai}: not a dict")
                continue
            if not atk.get("name"):
                warnings.append(f"{enemy_name} attack {ai}: missing 'name'")
            to_hit = atk.get("to_hit", atk.get("attack_bonus"))
            if to_hit is not None and not isinstance(to_hit, (int, float)):
                warnings.append(f"{enemy_name} attack '{atk.get('name', ai)}': to_hit is not an int")
            dmg = atk.get("damage")
            if dmg is not None and not isinstance(dmg, str):
                warnings.append(f"{enemy_name} attack '{atk.get('name', ai)}': damage is not a string")
    
    return warnings


# ---------------- Page Config ----------------
st.set_page_config(page_title="Virtual DM – Session Manager", layout="wide")

# --- UI Scale ---
reading_mode = st.toggle("📖 Reading Mode", value=True, help="Bigger, more readable UI text.")

base_font = 20 if reading_mode else 17  # bump these up (your current 18/15 is still small)

st.markdown(f"""
<style>
/* Global text */
html, body, [class*="css"] {{
  font-size: {base_font}px !important;
}}

/* Make widget labels and help text scale nicely */
label, .stMarkdown, .stCaption, .stText, .stTooltipIcon {{
  font-size: {base_font}px !important;
}}

/* Buttons + inputs slightly larger */
.stButton button {{
  font-size: {base_font}px !important;
  padding: 0.45rem 0.8rem !important;
}}
.stTextInput input, .stNumberInput input, .stSelectbox select, .stTextArea textarea {{
  font-size: {base_font}px !important;
}}
</style>
""", unsafe_allow_html=True)

# ---------------- Sidebar: Navigation + Settings ----------------
with st.sidebar:
    st.markdown("# 🎲 Virtual DM")
    st.caption("Solo & Assisted Play")
    
    st.markdown("---")
    
    # Navigation
    st.markdown("### 📍 Navigation")
    
    # Determine current page based on boot_mode
    boot_mode = st.session_state.get("boot_mode")
    
    # Navigation buttons
    nav_col1, nav_col2, nav_col3 = st.columns(3)
    with nav_col1:
        if st.button("🏠", help="Session", use_container_width=True):
            st.session_state.boot_mode = None
            st.rerun()
    with nav_col2:
        if st.button("⚙️", help="Setup", use_container_width=True):
            st.session_state.boot_mode = "new"
            st.rerun()
    with nav_col3:
        is_running = boot_mode == "running"
        if st.button("⚔️", help="Running", use_container_width=True, disabled=not is_running):
            pass  # Already on running if enabled
    
    # Show current page indicator
    if boot_mode is None:
        st.info("📍 **Session** - Choose how to begin")
    elif boot_mode == "load":
        st.info("📍 **Loading** - Upload a session")
    elif boot_mode == "new":
        st.info("📍 **Setup** - Configure party & enemies")
    elif boot_mode == "running":
        st.success("📍 **Running** - Session active")
    
    st.markdown("---")
    
    # Quick Stats (when running)
    if boot_mode == "running":
        st.markdown("### Quick Stats")
        party_count = len(st.session_state.get("party", []))
        enemy_count = len(st.session_state.get("enemies", []))
        in_combat = st.session_state.get("in_combat", False)
        combat_round = st.session_state.get("combat_round", 0)
        
        stat_col1, stat_col2 = st.columns(2)
        with stat_col1:
            st.metric("Party", party_count)
        with stat_col2:
            st.metric("Enemies", enemy_count)
        
        if in_combat:
            st.metric("Combat Round", combat_round)
            # current_turn() defined later, check if available
            try:
                ent = current_turn()
                if ent:
                    st.caption(f"Turn: **{ent.get('name', 'Unknown')}**")
            except NameError:
                pass
        else:
            st.caption("Not in combat")
        
        st.markdown("---")
    
    # Session Actions
    st.markdown("### 💾 Session")
    
    if boot_mode == "running":
        # Export session - serialize_state() defined later
        try:
            data = serialize_state()
            st.download_button(
                "📥 Download Session",
                data=json.dumps(data, indent=2),
                file_name=f"virtualdm_session_{st.session_state.get('session_id', 'unknown')}.json",
                mime="application/json",
                use_container_width=True
            )
        except NameError:
            st.caption("Session export available after full load")
    
    # New/Load buttons
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button("🆕 New", use_container_width=True):
            st.session_state.boot_mode = "new"
            st.rerun()
    with btn_col2:
        if st.button("📂 Load", use_container_width=True):
            st.session_state.boot_mode = "load"
            st.rerun()
    
    st.markdown("---")
    
    # Settings Section
    with st.expander("⚙️ Settings", expanded=False):
        # Performance Debug Toggle
        perf_debug = st.toggle("🔍 Performance Debug", value=st.session_state.get("perf_debug", False), key="perf_debug_toggle")
        st.session_state["perf_debug"] = perf_debug
        
        if perf_debug:
            st.markdown("---")
            st.markdown("#### 📊 Performance Stats")
            
            # Clear timings at start of each render
            clear_perf_timings()
            
            # Memory stats from tracemalloc
            current, peak = tracemalloc.get_traced_memory()
            st.metric("Current Memory", f"{current / 1024 / 1024:.2f} MB")
            st.metric("Peak Memory", f"{peak / 1024 / 1024:.2f} MB")
            
            # Top memory allocations
            with st.expander("Top Memory Allocations", expanded=False):
                snapshot = tracemalloc.take_snapshot()
                top_stats = snapshot.statistics('lineno')[:10]
                for stat in top_stats:
                    st.caption(f"{stat.size / 1024:.1f} KB - {stat.traceback}")
            
            # Session state size estimate
            try:
                import sys
                state_size = sum(sys.getsizeof(v) for v in st.session_state.values())
                st.metric("Session State (shallow)", f"{state_size / 1024:.1f} KB")
            except:
                pass
            
            # Timing display placeholder - will be populated after render
            st.markdown("#### ⏱️ Function Timings")
            timing_placeholder = st.empty()
            
            # Store placeholder for later update
            st.session_state["_perf_timing_placeholder"] = timing_placeholder
    
    st.markdown("---")
    st.caption("Virtual DM v0.4")

# ---------------- SRD Database ----------------
# reminder: keep the SRD file at ../data/SRD_Monsters.json relative to this UI file.
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "data"))
SRD_CANDIDATES = ["SRD_Monsters.json", "SRD_Monsters.txt"]  # accepts either

def _read_json_file(path: str):
    """
    Small helper so all JSON loading uses the same encoding and error handling.
    """
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)

def _resolve_srd_path():
    for name in SRD_CANDIDATES:
        p = os.path.join(DATA_DIR, name)
        if os.path.exists(p):
            st.session_state["srd_path_resolved"] = p
            return p
    st.session_state["srd_path_resolved"] = None
    return None

# --- Normalizers so any 5e-style JSON maps to our simple fields ---
def _norm_action(a: dict) -> dict:
    """Normalize an SRD-style action or attack into {name,to_hit,damage,...}."""
    name = a.get("name", "Action")

    # to-hit: support several common field names
    to_hit = (
        a.get("to_hit")
        or a.get("attack_bonus")
        or a.get("bonus")
        or 0
    )
    if isinstance(to_hit, str):
        s = to_hit.strip()
        if s.startswith(("+", "-")) and s[1:].isdigit():
            to_hit = int(s)
        elif s.isdigit():
            to_hit = int(s)
        else:
            to_hit = 0

    # damage: support "damage", "damage_dice", or first entry of a damage list
    damage = a.get("damage") or a.get("damage_dice") or "1d6"
    if isinstance(damage, list) and damage:
        part = damage[0]
        if isinstance(part, dict):
            damage = part.get("dice") or part.get("damage_dice") or part.get("damage") or "1d6"
        else:
            damage = str(part)

    if not isinstance(damage, str):
        damage = "1d6"

    out = {
        "name": name,
        "to_hit": int(to_hit) if isinstance(to_hit, int) else 0,
        "damage": damage,
    }

    # optional reach / range if present
    if "reach" in a:
        out["reach"] = a["reach"]
    if "range" in a:
        out["range"] = a["range"]

    return out

def _norm_monster(m: dict) -> dict:
    # Top-level keys vary wildly between sources; normalize to the fields our UI expects.
    name = m.get("name", "Unknown")

    # AC / HP: prefer our simple keys, else map common SRD keys
    ac = m.get("ac", m.get("armor_class"))
    if isinstance(ac, list):  # sometimes armor_class is a list of dicts
        # pick first numeric or value
        if ac and isinstance(ac[0], dict):
            ac = ac[0].get("value") or ac[0].get("ac") or 10
    if not isinstance(ac, (int, float)):
        try: ac = int(ac)
        except: ac = 10

    hp = m.get("hp", m.get("hit_points", 10))
    try: hp = int(hp)
    except: hp = 10

    # Speed: some sources store as dict {"walk":"30 ft.", "fly":"60 ft."}
    speed = m.get("speed", "")
    if isinstance(speed, dict):
        # make a compact string like "30 ft. walk, 60 ft. fly"
        parts = []
        for k, v in speed.items():
            parts.append(f"{v} {k}")
        speed = ", ".join(parts) if parts else ""

    # Ability scores: accept "abilities" or {"strength": 10,...} or {"STR":10,...}
    abilities = m.get("abilities") or {}
    if not abilities:
        cand = {}
        for key_map in [
            ("STR", ["STR", "str", "strength"]),
            ("DEX", ["DEX", "dex", "dexterity"]),
            ("CON", ["CON", "con", "constitution"]),
            ("INT", ["INT", "int", "intelligence"]),
            ("WIS", ["WIS", "wis", "wisdom"]),
            ("CHA", ["CHA", "cha", "charisma"]),
        ]:
            out_key, aliases = key_map
            val = None
            for a in aliases:
                if a in m: val = m[a]; break
                if "ability_scores" in m and a in m["ability_scores"]: val = m["ability_scores"][a]; break
                if "stats" in m and a in m["stats"]: val = m["stats"][a]; break
            if val is not None:
                try: cand[out_key] = int(val)
                except: cand[out_key] = val
        abilities = cand or {"STR":10,"DEX":10,"CON":10,"INT":10,"WIS":10,"CHA":10}

    # Traits usually arrays of dicts; keep tolerant
    traits = m.get("traits") or m.get("special_abilities") or []
    traits_norm = []
    for t in traits:
        if isinstance(t, dict):
            tname = t.get("name", "Trait")
            ttxt = t.get("text") or t.get("desc") or ""
            traits_norm.append({"name": tname, "text": ttxt})
        elif isinstance(t, str):
            traits_norm.append({"name": "Trait", "text": t})

    # Actions
    actions_raw = m.get("actions", [])
    if isinstance(actions_raw, dict):  # some sources use dict keyed by action name
        actions_raw = [{"name": k, **(v if isinstance(v, dict) else {})} for k, v in actions_raw.items()]
    actions = [_norm_action(a) for a in actions_raw if isinstance(a, (dict,))]

    # Secondary fields (tolerant)
    size = m.get("size", m.get("monster_size", "—"))
    typ = m.get("type", "—")
    alignment = m.get("alignment", "—")
    hit_dice = m.get("hit_dice", m.get("hit_die", "—"))
    saves = m.get("saves", {}) or m.get("saving_throws", {})
    skills = m.get("skills", {})
    senses = m.get("senses", m.get("sense", "—"))
    languages = m.get("languages", "—")
    cr = m.get("cr", m.get("challenge_rating", "—"))

    return {
        "name": name,
        "size": size,
        "type": typ,
        "alignment": alignment,
        "ac": ac,
        "hp": hp,
        "hit_dice": hit_dice,
        "speed": speed,
        "abilities": abilities,
        "saves": saves,
        "skills": skills,
        "senses": senses,
        "languages": languages,
        "cr": cr,
        "traits": traits_norm,
        "actions": actions
    }

@st.cache_data(show_spinner=False)
def _cached_normalize_monsters(raw_json_tuple: tuple, _version: int = 3) -> list:
    """
    Cached monster normalization. Pure function - no session state access.
    Accepts tuple of JSON strings for hashability.
    Returns list of normalized monster dicts.
    _version param forces cache invalidation when code changes.
    """
    # Parse JSON strings back to dicts
    raw_data = [json.loads(s) for s in raw_json_tuple]
    
    if not isinstance(raw_data, list):
        return []

    def _first_int(val, default=0):
        if val is None:
            return default
        if isinstance(val, int):
            return val
        if isinstance(val, float):
            return int(val)
        s = str(val)
        m = re.search(r"-?\d+", s)
        return int(m.group(0)) if m else default

    def _extract_ac(mon: dict) -> int:
        ac = mon.get("ac", mon.get("armor_class", mon.get("armorClass")))
        if isinstance(ac, int):
            return ac
        if isinstance(ac, list) and ac:
            if isinstance(ac[0], dict):
                return _first_int(ac[0].get("value") or ac[0].get("ac"), 10)
            return _first_int(ac[0], 10)
        if isinstance(ac, dict):
            return _first_int(ac.get("value") or ac.get("ac"), 10)

        return _first_int(mon.get("Armor Class"), 10)

    def _extract_hp(mon: dict) -> int:
        if "hp" in mon:
            return _first_int(mon.get("hp"), 10)
        if "hit_points" in mon:
            return _first_int(mon.get("hit_points"), 10)
        return _first_int(mon.get("Hit Points"), 10)

    def _extract_abilities(mon: dict) -> dict:
        # accepts: {"abilities": {"STR":10...}} OR {"STR":10...} OR {"strength":10...}
        abil = mon.get("abilities") or mon.get("ability_scores") or {}
        out = {}

        def grab(key, aliases):
            if isinstance(abil, dict):
                for a in aliases:
                    if a in abil:
                        return abil[a]
            for a in aliases:
                if a in mon:
                    return mon[a]
            return None

        mapping = {
            "STR": ["STR", "str", "strength"],
            "DEX": ["DEX", "dex", "dexterity"],
            "CON": ["CON", "con", "constitution"],
            "INT": ["INT", "int", "intelligence"],
            "WIS": ["WIS", "wis", "wisdom"],
            "CHA": ["CHA", "cha", "charisma"],
        }

        for k, aliases in mapping.items():
            v = grab(k, aliases)
            out[k] = _first_int(v, 10) if v is not None else 10

        return out

    def _parse_skills_to_dict(skills_val) -> dict:
        """
        Accepts:
          - dict already (keep)
          - string like "Perception +2, Stealth +4"
        Returns dict of skill -> bonus int.
        """
        if isinstance(skills_val, dict):
            cleaned = {}
            for k, v in skills_val.items():
                cleaned[str(k)] = _first_int(v, 0)
            return cleaned

        if not skills_val:
            return {}

        s = str(skills_val)
        # split on commas
        parts = [p.strip() for p in s.split(",") if p.strip()]
        out = {}
        for p in parts:
            # match "Perception +2" or "Stealth +4"
            m = re.match(r"^(.+?)\s*([+\-]\d+)\s*$", p)
            if m:
                out[m.group(1).strip()] = int(m.group(2))
        return out

    def _parse_actions_text(actions_text: str) -> list[dict]:
        """
        Best-effort parse of SRD 'Actions' string into list of {name,to_hit,damage,range,attack_type}.
        Handles patterns like:
        'Scimitar. Melee Weapon Attack: +4 to hit, reach 5 ft... Hit: 5 (1d6 + 2) slashing damage.'
        'Shortbow. Ranged Weapon Attack: +4 to hit, range 80/320 ft... Hit: 5 (1d6 + 2) piercing damage.'
        """
        if not actions_text:
            return []

        txt = re.sub(r"<[^>]+>", " ", str(actions_text))
        txt = re.sub(r"\s+", " ", txt).strip()

        chunks = re.split(r"(?<=\.)\s(?=[A-Z][A-Za-z0-9''\- ]+\.)", txt)
        parsed = []

        for ch in chunks:
            mname = re.match(r"^([A-Z][A-Za-z0-9''\- ]+)\.", ch)
            if not mname:
                continue
            name = mname.group(1).strip()

            mto = re.search(r"([+\-]\d+)\s*to hit", ch, re.IGNORECASE)
            to_hit = int(mto.group(1)) if mto else 0

            mdmg = re.search(r"\((\d+d\d+\s*(?:[+\-]\s*\d+)?)\)", ch)
            dmg = mdmg.group(1).replace(" ", "") if mdmg else ""

            # Determine attack type (melee vs ranged)
            attack_type = "melee"
            if re.search(r"ranged\s+(weapon\s+)?attack", ch, re.IGNORECASE):
                attack_type = "ranged"
            elif re.search(r"melee\s+or\s+ranged", ch, re.IGNORECASE):
                attack_type = "both"
            
            # Extract range - look for "range X/Y ft" or "reach X ft"
            range_ft = 5  # default melee reach
            
            # Check for ranged attack range (e.g., "range 80/320 ft")
            range_match = re.search(r"range\s+(\d+)(?:/\d+)?\s*ft", ch, re.IGNORECASE)
            if range_match:
                range_ft = int(range_match.group(1))
            else:
                # Check for reach (e.g., "reach 10 ft")
                reach_match = re.search(r"reach\s+(\d+)\s*ft", ch, re.IGNORECASE)
                if reach_match:
                    range_ft = int(reach_match.group(1))

            parsed.append({
                "name": name, 
                "to_hit": to_hit, 
                "damage": dmg or "1d6",
                "range": range_ft,
                "attack_type": attack_type
            })
        return parsed

    def _extract_actions(mon: dict) -> list[dict]:
        # 5e API-ish: actions list of dicts
        actions = mon.get("actions")
        if isinstance(actions, list):
            out = []
            for a in actions:
                if not isinstance(a, dict):
                    continue
                name = a.get("name", "Action")

                # to-hit
                to_hit = a.get("to_hit")
                if to_hit is None:
                    to_hit = a.get("attack_bonus", a.get("bonus", 0))
                to_hit = _first_int(to_hit, 0)

                # damage
                dd = a.get("damage_dice") or ""
                db = a.get("damage_bonus", 0)
                if dd:
                    dbi = _first_int(db, 0)
                    if dbi != 0:
                        sign = "+" if dbi > 0 else "-"
                        dmg = f"{dd}{sign}{abs(dbi)}"
                    else:
                        dmg = str(dd)
                else:
                    dmg = a.get("damage") or a.get("damage_dice") or ""
                    if isinstance(dmg, dict):
                        dd2 = dmg.get("damage_dice") or dmg.get("dice") or ""
                        db2 = _first_int(dmg.get("damage_bonus") or dmg.get("bonus"), 0)
                        if dd2:
                            sign = "+" if db2 > 0 else "-"
                            dmg = f"{dd2}{sign}{abs(db2)}" if db2 else dd2
                        else:
                            dmg = ""
                    dmg = str(dmg) if dmg else ""

                # Extract range from action
                range_ft = a.get("range") or a.get("reach") or 5
                if isinstance(range_ft, str):
                    rm = re.search(r"(\d+)", range_ft)
                    range_ft = int(rm.group(1)) if rm else 5
                
                # Determine attack type
                attack_type = a.get("attack_type", "melee")
                desc = a.get("desc", a.get("description", ""))
                if "ranged" in str(desc).lower() or "ranged" in name.lower():
                    attack_type = "ranged"

                out.append({
                    "name": name,
                    "to_hit": int(to_hit),
                    "damage": (dmg or "1d6"),
                    "damage_type": a.get("damage_type") or a.get("damage_type_name") or "",
                    "range": int(range_ft),
                    "attack_type": attack_type,
                })
            return out

        # Text-ish SRD field
        return _parse_actions_text(mon.get("Actions", ""))

    normalized = []
    for mon in raw_data:
        if not isinstance(mon, dict):
            continue

        nm = mon.get("name") or mon.get("Name") or "Monster"

        ac = int(_extract_ac(mon))
        hp = int(_extract_hp(mon))
        abilities = _extract_abilities(mon)

        # skills & senses
        skills_raw = mon.get("skills") or mon.get("Skills") or {}
        skills = _parse_skills_to_dict(skills_raw)
        senses = mon.get("senses") or mon.get("Senses") or mon.get("sense") or ""

        actions = _extract_actions(mon)

        # attacks are derived from actions (for now: anything with a to_hit or damage)
        attacks = []
        for a in actions:
            if not isinstance(a, dict):
                continue
            if "name" not in a:
                continue
            attacks.append({
                "name": a.get("name", "Attack"),
                "to_hit": _first_int(a.get("to_hit"), _first_int(a.get("attack_bonus"), 0)),
                "damage": a.get("damage") or a.get("damage_dice") or "1d6",
                "damage_type": a.get("damage_type", "") or "",
                "range": a.get("range", 5),  # Include range for AI attack selection
                "attack_type": a.get("attack_type", "melee"),  # Include attack type (melee/ranged)
            })

        # Extract speed
        speed_raw = mon.get("Speed") or mon.get("speed") or "30 ft."
        speed_match = re.search(r"(\d+)\s*ft", str(speed_raw))
        speed_ft = int(speed_match.group(1)) if speed_match else 30
        
        # Extract challenge rating
        challenge = mon.get("Challenge") or mon.get("challenge") or mon.get("cr") or "0"
        
        # Extract traits (passive abilities)
        traits_raw = mon.get("Traits") or mon.get("traits") or ""
        traits = []
        if traits_raw:
            # Parse HTML-style traits text
            traits_text = re.sub(r"<[^>]+>", " ", str(traits_raw))
            traits_text = re.sub(r"\s+", " ", traits_text).strip()
            # Split on trait names (bold patterns)
            trait_chunks = re.split(r"(?<=\.)\s(?=[A-Z][A-Za-z0-9''\- ]+\.)", traits_text)
            for chunk in trait_chunks:
                trait_match = re.match(r"^([A-Z][A-Za-z0-9''\- ]+)\.\s*(.*)$", chunk, re.DOTALL)
                if trait_match:
                    traits.append({
                        "name": trait_match.group(1).strip(),
                        "description": trait_match.group(2).strip()
                    })
        
        # Extract damage resistances/immunities
        damage_resistances = mon.get("Damage Resistances") or mon.get("damage_resistances") or ""
        damage_immunities = mon.get("Damage Immunities") or mon.get("damage_immunities") or ""
        condition_immunities = mon.get("Condition Immunities") or mon.get("condition_immunities") or ""
        
        normalized.append({
            "name": nm,
            "ac": ac,
            "hp": hp,
            "max_hp": hp,
            "abilities": abilities,
            "skills": skills,
            "senses": str(senses) if senses is not None else "",
            "speed_ft": speed_ft,
            "challenge": str(challenge),
            "traits": traits,
            "damage_resistances": str(damage_resistances),
            "damage_immunities": str(damage_immunities),
            "condition_immunities": str(condition_immunities),
            "actions": actions,
            "attacks": attacks,
            # keep src copy for debugging / future parsing
            "_raw": mon,
        })

    return normalized

def load_srd_monsters():
    """
    Load SRD monsters from JSON and normalize into ONE consistent schema our app uses.
    Uses caching to avoid re-parsing on every Streamlit rerun.
    """
    with perf_timer("load_srd_monsters"):
        if "srd_enemies" in st.session_state and st.session_state.srd_enemies:
            return st.session_state.srd_enemies
        
    base_dir = os.path.dirname(__file__)
    candidates = [
        os.path.join(base_dir, "..", "data", "SRD_Monsters.json"),
        os.path.join(base_dir, "..", "data", "SRD_Monsters.txt"),
        os.path.join(base_dir, "SRD_Monsters.json"),
        os.path.join(base_dir, "SRD_Monsters.txt"),
    ]
    
    path = _find_data_file(candidates)
    st.session_state.srd_enemies_path = path or ""

    if not path:
        st.session_state.srd_enemies = []
        return []
    
    # Use cached JSON loader
    raw, _ = _cached_load_json(path)
    if raw is None:
        st.session_state.srd_enemies = []
        return []
    
    # Handle wrapped data
    if isinstance(raw, dict):
        raw = raw.get("monsters") or raw.get("data") or raw.get("results") or list(raw.values())
    
    if not isinstance(raw, list):
        st.session_state.srd_enemies = []
        return []
    
    # Use cached normalization (convert to tuple for hashability)
    # _version=3: Added range and attack_type to action parsing
    normalized = _cached_normalize_monsters(tuple(json.dumps(m) for m in raw), _version=3)
        
    st.session_state.srd_enemies = normalized
    return normalized

# ============== COMPANION & WILD SHAPE SYSTEM ==============

def parse_cr_to_float(cr_string: str) -> float:
    """Convert CR string like '1/4 (50 XP)' or '2 (450 XP)' to float."""
    if not cr_string:
        return 0.0
    # Extract just the CR part before any parentheses
    cr_part = cr_string.split("(")[0].strip()
    if "/" in cr_part:
        num, denom = cr_part.split("/")
        return float(num) / float(denom)
    try:
        return float(cr_part)
    except:
        return 0.0

def get_beasts_by_cr(max_cr: float, allow_fly: bool = True, allow_swim: bool = True) -> list:
    """Get all beasts up to a certain CR, optionally filtering by movement."""
    monsters = load_srd_monsters()
    beasts = []
    
    for m in monsters:
        meta = m.get("meta", "").lower()
        if "beast" not in meta:
            continue
        
        cr = parse_cr_to_float(m.get("challenge", m.get("Challenge", "0")))
        if cr > max_cr:
            continue
        
        speed = m.get("speed", "").lower()
        if not allow_fly and "fly" in speed:
            continue
        if not allow_swim and "swim" in speed:
            continue
        
        beasts.append(m)
    
    return sorted(beasts, key=lambda x: (parse_cr_to_float(x.get("challenge", x.get("Challenge", "0"))), x.get("name", "")))

def get_familiar_options() -> list:
    """Get valid familiar options (CR 0 beasts, typically small/tiny)."""
    monsters = load_srd_monsters()
    familiars = []
    
    # Standard familiar options
    familiar_names = ["Bat", "Cat", "Crab", "Frog", "Hawk", "Lizard", "Octopus", "Owl", "Poisonous Snake", 
                      "Quipper", "Rat", "Raven", "Sea Horse", "Spider", "Weasel"]
    
    for m in monsters:
        if m.get("name") in familiar_names:
            familiars.append(m)
    
    return familiars

def monster_to_companion(monster: dict, owner_name: str, companion_type: str = "companion", bonus_hp: int = 0) -> dict:
    """Convert a monster dict to a companion entity that can participate in combat."""
    
    # Parse HP
    hp_str = monster.get("hp", monster.get("Hit Points", "10"))
    hp_match = re.match(r"(\d+)", str(hp_str))
    base_hp = int(hp_match.group(1)) if hp_match else 10
    total_hp = base_hp + bonus_hp
    
    # Parse AC
    ac_str = monster.get("ac", monster.get("Armor Class", "10"))
    ac_match = re.match(r"(\d+)", str(ac_str))
    ac = int(ac_match.group(1)) if ac_match else 10
    
    # Parse speed
    speed_str = monster.get("speed", monster.get("Speed", "30 ft."))
    speed_match = re.search(r"(\d+)\s*ft", speed_str)
    speed = int(speed_match.group(1)) if speed_match else 30
    
    # Get stats
    def get_stat(key):
        val = monster.get(key, monster.get(key.upper(), "10"))
        try:
            return int(str(val).replace("(", "").replace(")", "").strip())
        except:
            return 10
    
    companion = {
        "name": f"{owner_name}'s {monster.get('name', 'Companion')}",
        "base_creature": monster.get("name", "Unknown"),
        "companion_type": companion_type,  # "familiar", "animal_companion", "wild_shape"
        "owner": owner_name,
        "hp": total_hp,
        "max_hp": total_hp,
        "ac": ac,
        "speed": speed,
        "speed_ft": speed,
        "cr": parse_cr_to_float(monster.get("challenge", monster.get("Challenge", "0"))),
        "size": 1,  # Grid squares
        "abilities": {
            "STR": get_stat("STR"),
            "DEX": get_stat("DEX"),
            "CON": get_stat("CON"),
            "INT": get_stat("INT"),
            "WIS": get_stat("WIS"),
            "CHA": get_stat("CHA"),
        },
        "attacks": [],
        "traits": monster.get("Traits", monster.get("traits", "")),
        "actions_text": monster.get("Actions", monster.get("actions", "")),
        "senses": monster.get("Senses", monster.get("senses", "")),
        "pos": None,  # Will be set when added to map
    }
    
    # Parse attacks from Actions text
    actions_text = companion["actions_text"]
    if actions_text:
        # Simple attack parsing
        attack_pattern = r"<em><strong>([^<]+)</strong></em>[^<]*<em>Melee Weapon Attack:</em>\s*\+(\d+)\s*to hit[^<]*<em>Hit:</em>\s*(\d+)\s*\(([^)]+)\)\s*(\w+)\s*damage"
        for match in re.finditer(attack_pattern, actions_text):
            atk_name, to_hit, avg_dmg, dice, dmg_type = match.groups()
            companion["attacks"].append({
                "name": atk_name.strip(),
                "to_hit": int(to_hit),
                "damage": dice,
                "damage_type": dmg_type,
                "reach": 5,
                "attack_type": "melee",
            })
        
        # Ranged attacks
        ranged_pattern = r"<em><strong>([^<]+)</strong></em>[^<]*<em>Ranged Weapon Attack:</em>\s*\+(\d+)\s*to hit[^<]*range\s*(\d+)[^<]*<em>Hit:</em>\s*(\d+)\s*\(([^)]+)\)\s*(\w+)\s*damage"
        for match in re.finditer(ranged_pattern, actions_text):
            atk_name, to_hit, range_ft, avg_dmg, dice, dmg_type = match.groups()
            companion["attacks"].append({
                "name": atk_name.strip(),
                "to_hit": int(to_hit),
                "damage": dice,
                "damage_type": dmg_type,
                "range": int(range_ft),
                "attack_type": "ranged",
            })
    
    # If no attacks parsed, add a basic attack based on creature
    if not companion["attacks"]:
        str_mod = (companion["abilities"]["STR"] - 10) // 2
        companion["attacks"].append({
            "name": "Natural Attack",
            "to_hit": str_mod + 2,  # Assume +2 proficiency
            "damage": "1d4",
            "damage_type": "bludgeoning",
            "reach": 5,
            "attack_type": "melee",
        })
    
    return companion

def create_animal_companion(owner: dict, creature_name: str) -> dict:
    """Create an animal companion for a Ranger."""
    monsters = load_srd_monsters()
    creature = next((m for m in monsters if m.get("name", "").lower() == creature_name.lower()), None)
    
    if not creature:
        # Default to Wolf
        creature = next((m for m in monsters if m.get("name") == "Wolf"), None)
    
    if not creature:
        return None
    
    # Calculate bonus HP from Ranger
    wis_mod = (owner.get("abilities", {}).get("WIS", 10) - 10) // 2
    lvl = owner.get("level", 1)
    bonus_hp = wis_mod + lvl
    
    companion = monster_to_companion(creature, owner.get("name", "Unknown"), "animal_companion", bonus_hp)
    return companion

def create_familiar(owner: dict, creature_name: str) -> dict:
    """Create a familiar for a Wizard."""
    monsters = load_srd_monsters()
    creature = next((m for m in monsters if m.get("name", "").lower() == creature_name.lower()), None)
    
    if not creature:
        # Default to Owl
        creature = next((m for m in monsters if m.get("name") == "Owl"), None)
    
    if not creature:
        return None
    
    # Familiar HP = Wizard level + INT mod
    int_mod = (owner.get("abilities", {}).get("INT", 10) - 10) // 2
    lvl = owner.get("level", 1)
    
    companion = monster_to_companion(creature, owner.get("name", "Unknown"), "familiar", 0)
    # Override HP for familiar
    companion["hp"] = lvl + int_mod
    companion["max_hp"] = lvl + int_mod
    
    # Familiars have special INT
    companion["abilities"]["INT"] = max(6, int_mod)
    
    return companion

def create_spirit_guide(owner: dict, totem_spirit: str) -> dict:
    """Create a Spirit Guide companion for a Shaman based on their Totem Spirit."""
    monsters = load_srd_monsters()
    
    # Map totem spirits to appropriate creatures (lowest CR versions)
    totem_creature_map = {
        "Bear": "Black Bear",      # CR 1/2
        "Eagle": "Eagle",          # CR 0
        "Wolf": "Wolf",            # CR 1/4
    }
    
    creature_name = totem_creature_map.get(totem_spirit, "Wolf")
    creature = next((m for m in monsters if m.get("name", "").lower() == creature_name.lower()), None)
    
    if not creature:
        # Fallback to Wolf
        creature = next((m for m in monsters if m.get("name") == "Wolf"), None)
    
    if not creature:
        return None
    
    # Calculate bonus HP from Shaman
    wis_mod = (owner.get("abilities", {}).get("WIS", 10) - 10) // 2
    lvl = owner.get("level", 1)
    bonus_hp = wis_mod + (lvl // 2)  # Half level + WIS mod bonus HP
    
    companion = monster_to_companion(creature, owner.get("name", "Unknown"), "spirit_guide", bonus_hp)
    
    # Spirit Guides are ethereal/spiritual - add special properties
    companion["is_spirit"] = True
    companion["creature_type"] = "Spirit"
    companion["special_traits"] = companion.get("special_traits", [])
    companion["special_traits"].append("Ethereal Nature: Can see into the Ethereal Plane. Cannot be grappled or restrained by non-magical means.")
    companion["special_traits"].append(f"Spirit Bond: If reduced to 0 HP, reforms after a long rest.")
    
    # Rename to reflect spiritual nature
    companion["name"] = f"Spirit {creature_name} ({owner.get('name', 'Shaman')}'s Guide)"
    
    return companion

def apply_wild_shape(druid: dict, beast_name: str) -> dict:
    """Apply Wild Shape transformation to a Druid. Returns the transformed state."""
    monsters = load_srd_monsters()
    beast = next((m for m in monsters if m.get("name", "").lower() == beast_name.lower()), None)
    
    if not beast:
        return None
    
    # Store original stats if not already stored
    if "wild_shape_original" not in druid:
        druid["wild_shape_original"] = {
            "hp": druid.get("hp", 1),
            "max_hp": druid.get("max_hp", 1),
            "ac": druid.get("ac", 10),
            "speed": druid.get("speed_ft", 30),
            "abilities": druid.get("abilities", {}).copy(),
            "attacks": druid.get("attacks", []).copy(),
        }
    
    # Parse beast stats
    hp_str = beast.get("hp", beast.get("Hit Points", "10"))
    hp_match = re.match(r"(\d+)", str(hp_str))
    beast_hp = int(hp_match.group(1)) if hp_match else 10
    
    ac_str = beast.get("ac", beast.get("Armor Class", "10"))
    ac_match = re.match(r"(\d+)", str(ac_str))
    beast_ac = int(ac_match.group(1)) if ac_match else 10
    
    speed_str = beast.get("speed", beast.get("Speed", "30 ft."))
    speed_match = re.search(r"(\d+)\s*ft", speed_str)
    beast_speed = int(speed_match.group(1)) if speed_match else 30
    
    def get_stat(key):
        val = beast.get(key, beast.get(key.upper(), "10"))
        try:
            return int(str(val).replace("(", "").replace(")", "").strip())
        except:
            return 10
    
    # Apply beast physical stats, keep mental stats
    druid["wild_shape_active"] = True
    druid["wild_shape_form"] = beast.get("name", "Unknown")
    druid["wild_shape_hp"] = beast_hp
    druid["wild_shape_max_hp"] = beast_hp
    
    # Temporarily override stats
    druid["hp"] = beast_hp
    druid["max_hp"] = beast_hp
    druid["ac"] = beast_ac
    druid["speed_ft"] = beast_speed
    
    # Replace physical abilities only
    original_abilities = druid["wild_shape_original"]["abilities"]
    druid["abilities"] = {
        "STR": get_stat("STR"),
        "DEX": get_stat("DEX"),
        "CON": get_stat("CON"),
        "INT": original_abilities.get("INT", 10),  # Keep mental
        "WIS": original_abilities.get("WIS", 10),  # Keep mental
        "CHA": original_abilities.get("CHA", 10),  # Keep mental
    }
    
    # Parse beast attacks
    beast_attacks = []
    actions_text = beast.get("Actions", beast.get("actions", ""))
    if actions_text:
        attack_pattern = r"<em><strong>([^<]+)</strong></em>[^<]*<em>Melee Weapon Attack:</em>\s*\+(\d+)\s*to hit[^<]*<em>Hit:</em>\s*(\d+)\s*\(([^)]+)\)\s*(\w+)\s*damage"
        for match in re.finditer(attack_pattern, actions_text):
            atk_name, to_hit, avg_dmg, dice, dmg_type = match.groups()
            beast_attacks.append({
                "name": atk_name.strip(),
                "to_hit": int(to_hit),
                "damage": dice,
                "damage_type": dmg_type,
                "reach": 5,
                "attack_type": "melee",
            })
    
    if not beast_attacks:
        str_mod = (druid["abilities"]["STR"] - 10) // 2
        beast_attacks.append({
            "name": "Natural Attack",
            "to_hit": str_mod + 2,
            "damage": "1d4",
            "damage_type": "bludgeoning",
            "reach": 5,
            "attack_type": "melee",
        })
    
    druid["attacks"] = beast_attacks
    
    return druid

def revert_wild_shape(druid: dict) -> dict:
    """Revert Wild Shape transformation."""
    if "wild_shape_original" not in druid:
        return druid
    
    original = druid["wild_shape_original"]
    
    # Restore original stats
    druid["hp"] = original["hp"]
    druid["max_hp"] = original["max_hp"]
    druid["ac"] = original["ac"]
    druid["speed_ft"] = original["speed"]
    druid["abilities"] = original["abilities"].copy()
    druid["attacks"] = original["attacks"].copy()
    
    # Clear wild shape state
    druid["wild_shape_active"] = False
    druid.pop("wild_shape_form", None)
    druid.pop("wild_shape_hp", None)
    druid.pop("wild_shape_max_hp", None)
    druid.pop("wild_shape_original", None)
    
    return druid

def get_companions_for_party() -> list:
    """Get all active companions from the party."""
    companions = []
    for member in st.session_state.get("party", []):
        if member.get("companions"):
            for comp in member["companions"]:
                companions.append(comp)
    return companions

def add_companion_to_party_member(party_idx: int, companion: dict):
    """Add a companion to a party member."""
    if "party" not in st.session_state or party_idx >= len(st.session_state.party):
        return
    
    member = st.session_state.party[party_idx]
    if "companions" not in member:
        member["companions"] = []
    
    # Check if companion already exists
    existing = next((c for c in member["companions"] if c.get("companion_type") == companion.get("companion_type")), None)
    if existing:
        # Replace existing companion of same type
        member["companions"] = [c for c in member["companions"] if c.get("companion_type") != companion.get("companion_type")]
    
    member["companions"].append(companion)

def remove_companion_from_party_member(party_idx: int, companion_name: str):
    """Remove a companion from a party member."""
    if "party" not in st.session_state or party_idx >= len(st.session_state.party):
        return
    
    member = st.session_state.party[party_idx]
    if "companions" in member:
        member["companions"] = [c for c in member["companions"] if c.get("name") != companion_name]


@st.cache_data(show_spinner=False)
def _cached_normalize_conditions(data_json: str) -> dict:
    """Cached condition normalization. Pure function."""
    data = json.loads(data_json)
    
    # supports multiple formats:
    # 1. {"conditions": [...]} - list under "conditions" key
    # 2. [...] - just a list
    # 3. {"prone": {...}, "stunned": {...}} - dict keyed by condition name
    
    if isinstance(data, dict) and "conditions" in data:
        conditions = data["conditions"]
    elif isinstance(data, list):
        conditions = data
    elif isinstance(data, dict):
        # Dict keyed by condition name - convert to list format
        conditions = list(data.values())
    else:
        conditions = []

    # normalize into a dict keyed by condition name
    out = {}
    for c in conditions or []:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or "").strip()
        if not name:
            continue
        out[name] = c
    return out

def load_srd_conditions():
    """
    Load SRD conditions from JSON. Uses caching.
    """
    with perf_timer("load_srd_conditions"):
        if "srd_conditions" in st.session_state and st.session_state["srd_conditions"]:
            return st.session_state["srd_conditions"]
        
        base_dir = os.path.dirname(__file__)
        candidates = [
            os.path.join(base_dir, "SRD_Conditions.json"),
            os.path.join(base_dir, "..", "data", "SRD_Conditions.json"),
        ]

        path = _find_data_file(candidates)
        
        if not path:
            st.session_state["srd_conditions"] = {}
            st.session_state["srd_conditions_path"] = None
            return {}

        data, _ = _cached_load_json(path)
        if data is None:
            st.session_state["srd_conditions"] = {}
            st.session_state["srd_conditions_path"] = path
            return {}

        out = _cached_normalize_conditions(json.dumps(data))
    st.session_state["srd_conditions"] = out
    st.session_state["srd_conditions_path"] = path
    return out

# ---------------- SRD Spells Loader ----------------

def _parse_spell_damage_from_description(desc: str) -> tuple:
    """
    Extract damage dice and type from spell description.
    Returns (damage_dice, damage_type) or (None, None) if not found.
    """
    if not desc:
        return None, None
    
    # Pattern: "takes XdY damage_type damage" or "XdY damage_type damage"
    damage_pattern = r'(\d+d\d+(?:\s*\+\s*\d+)?)\s+(\w+)\s+damage'
    match = re.search(damage_pattern, desc, re.IGNORECASE)
    if match:
        return match.group(1), match.group(2).capitalize()
    
    # Simpler pattern: just "XdY damage"
    simple_pattern = r'(\d+d\d+(?:\s*\+\s*\d+)?)\s+damage'
    match = re.search(simple_pattern, desc, re.IGNORECASE)
    if match:
        return match.group(1), None
    
    return None, None

def _parse_spell_save_from_description(desc: str) -> str | None:
    """
    Extract save type from spell description.
    Returns ability abbreviation (STR, DEX, etc.) or None.
    """
    if not desc:
        return None
    
    # Pattern: "Strength saving throw", "Dexterity save", etc.
    save_pattern = r'(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)\s+sav'
    match = re.search(save_pattern, desc, re.IGNORECASE)
    if match:
        ability_map = {
            "strength": "STR",
            "dexterity": "DEX", 
            "constitution": "CON",
            "intelligence": "INT",
            "wisdom": "WIS",
            "charisma": "CHA"
        }
        return ability_map.get(match.group(1).lower())
    return None

def _is_spell_attack(desc: str) -> bool:
    """Check if spell description indicates a spell attack roll."""
    if not desc:
        return False
    desc_lower = desc.lower()
    return "spell attack" in desc_lower or "make a ranged spell attack" in desc_lower or "make a melee spell attack" in desc_lower

def _parse_range_feet(range_str: str) -> int | None:
    """Extract numeric range in feet from range string."""
    if not range_str:
        return None
    match = re.search(r'(\d+)\s*(?:feet|ft)', range_str, re.IGNORECASE)
    if match:
        return int(match.group(1))
    if "touch" in range_str.lower():
        return 5
    if "self" in range_str.lower():
        return 0
    return None

def normalize_spell(raw: dict) -> dict:
    """
    Normalize a raw SRD spell into our standard action schema.
    Now uses the new comprehensive spell schema with full casting metadata.
    """
    desc = raw.get("description", "")
    
    # Use new schema fields if available, fall back to parsing for backward compat
    damage = raw.get("damage_dice")
    damage_type = raw.get("damage_type")
    if not damage:
        damage, damage_type = _parse_spell_damage_from_description(desc)
    
    # Use new save_type field or parse from description
    save = raw.get("save_type")
    if save == "none":
        save = None
    if not save:
        save = _parse_spell_save_from_description(desc)
    
    # Use new attack_type field or determine from description
    attack_type_raw = raw.get("attack_type", "none")
    is_attack = attack_type_raw != "none" or _is_spell_attack(desc)
    
    # Map casting_time_unit to our action_type
    action_type_map = {
        "action": "standard",
        "bonus": "quick",
        "reaction": "immediate",
        "minute": "standard",
        "hour": "standard",
    }
    casting_unit = raw.get("casting_time_unit", "action")
    action_type = action_type_map.get(casting_unit, "standard")
    
    # Determine spell type
    if is_attack:
        spell_type = "spell_attack"
    elif save:
        spell_type = "spell_save"
    else:
        spell_type = "spell_utility"
    
    # Use new range_value or parse
    range_feet = raw.get("range_value")
    if range_feet is None or range_feet < 0:
        range_feet = _parse_range_feet(raw.get("range", ""))
    
    # Components - use new structured format or legacy
    components_data = raw.get("components", {})
    if isinstance(components_data, dict):
        comp_parts = []
        if components_data.get("verbal"):
            comp_parts.append("V")
        if components_data.get("somatic"):
            comp_parts.append("S")
        if components_data.get("material"):
            comp_parts.append("M")
        components = ", ".join(comp_parts)
    elif isinstance(components_data, list):
        components = ", ".join(c.upper() for c in components_data)
    else:
        components = str(components_data)
    
    return {
        "name": raw.get("name", "Unknown Spell"),
        "level": raw.get("level", 0),
        "school": raw.get("school", "").capitalize(),
        
        # Casting time
        "casting_time": raw.get("casting_time", "action"),
        "casting_time_value": raw.get("casting_time_value", 1),
        "casting_time_unit": raw.get("casting_time_unit", "action"),
        "reaction_trigger": raw.get("reaction_trigger"),
        
        # Range
        "range": raw.get("range", "Self"),
        "range_type": raw.get("range_type", "self"),
        "range_feet": range_feet,
        
        # Components
        "components": components,
        "components_data": components_data if isinstance(components_data, dict) else None,
        "material": raw.get("material_component") or raw.get("material"),
        "material_cost": raw.get("material_cost", 0),
        "material_consumed": raw.get("material_consumed", False),
        
        # Duration
        "duration": raw.get("duration", "Instantaneous"),
        "duration_type": raw.get("duration_type", "instantaneous"),
        "duration_value": raw.get("duration_value", 0),
        "concentration": raw.get("concentration", False),
        "ritual": raw.get("ritual", False),
        "ritual_time_extra": raw.get("ritual_time_extra", 10 if raw.get("ritual") else 0),
        
        # Targeting
        "target_type": raw.get("target_type", "creature"),
        "target_count": raw.get("target_count", 1),
        "area_shape": raw.get("area_shape", "none"),
        "area_size": raw.get("area_size", 0),
        "requires_sight": raw.get("requires_sight", True),
        "requires_line_of_effect": raw.get("requires_line_of_effect", True),
        
        # Attack/Save
        "attack_type": attack_type_raw,
        "save": save,
        "save_effect": raw.get("save_effect", "none"),
        "dc": None,  # Computed from caster's spellcasting ability + proficiency
        "to_hit": None,  # Computed from caster's spellcasting ability + proficiency
        
        # Damage/Healing
        "damage": damage,
        "damage_type": damage_type,
        "healing_dice": raw.get("healing_dice"),
        
        # Scaling
        "cantrip_scaling": raw.get("cantrip_scaling"),
        "upcast_scaling": raw.get("upcast_scaling"),
        
        # Tags and description
        "tags": raw.get("tags", []),
        "description": desc,
        "classes": raw.get("classes", []),
        
        # Computed type
        "type": spell_type,
        "action_type": action_type,
    }

@st.cache_data(show_spinner=False)
def _cached_normalize_spells(spells_json_tuple: tuple) -> list:
    """Cached spell normalization. Pure function."""
    return [normalize_spell(json.loads(s)) for s in spells_json_tuple]

def load_srd_spells() -> list:
    """
    Load SRD spells from JSON and normalize into our spell schema.
    Uses caching for performance.
    """
    with perf_timer("load_srd_spells"):
        if "srd_spells" in st.session_state:
            return st.session_state["srd_spells"]
        
        data, path = _load_json_from_candidates(DATA_DIR, ["SRD_Spells.json"])
        st.session_state["srd_spells_path"] = path
        
        if not isinstance(data, list):
            st.session_state["srd_spells"] = []
            return []
        
        # Use cached normalization
        normalized = _cached_normalize_spells(tuple(json.dumps(s) for s in data))
        st.session_state["srd_spells"] = normalized
        return normalized

def get_spells_for_class(class_name: str, max_level: int = 1) -> tuple:
    """
    Get cantrips and leveled spells available to a class.
    Returns (cantrips, level_1_spells).
    """
    spells = load_srd_spells()
    class_lower = class_name.lower()
    
    cantrips = [s for s in spells if s["level"] == 0 and class_lower in [c.lower() for c in s.get("classes", [])]]
    level_1 = [s for s in spells if s["level"] == 1 and class_lower in [c.lower() for c in s.get("classes", [])]]
    
    return cantrips, level_1

def spell_to_action(spell: dict, caster: dict) -> dict:
    """
    Convert a normalized spell into an action that can be added to char['actions'].
    Computes to_hit and DC based on caster's spellcasting ability.
    """
    # Get spellcasting ability modifier
    spell_ability = caster.get("spellcasting_ability", "INT")
    ability_score = caster.get("abilities", {}).get(spell_ability, 10)
    ability_mod = (ability_score - 10) // 2
    
    # Proficiency bonus (assume +2 at level 1)
    prof_bonus = caster.get("proficiency_bonus", 2)
    
    # Compute to_hit for spell attacks
    to_hit = None
    if spell.get("type") == "spell_attack":
        to_hit = ability_mod + prof_bonus
    
    # Compute DC for spell saves
    dc = None
    if spell.get("save"):
        dc = 8 + ability_mod + prof_bonus
    
    # Calculate scaled damage for cantrips
    damage = spell.get("damage")
    caster_level = caster.get("level", 1)
    
    if spell.get("level") == 0 and spell.get("cantrip_scaling"):
        damage = get_scaled_cantrip_damage(spell, caster_level)
    
    return {
        "name": spell["name"],
        "type": spell["type"],
        "action_type": spell["action_type"],
        "to_hit": to_hit,
        "dc": dc,
        "save": spell.get("save"),
        "damage": damage,
        "damage_type": spell.get("damage_type"),
        "range": spell.get("range_feet") or 60,  # default 60ft for spells
        "description": spell.get("description", ""),
        "spell_level": spell.get("level", 0),
        "concentration": spell.get("concentration", False),
        "components": spell.get("components", ""),
        "healing_dice": spell.get("healing_dice"),
        "cantrip_scaling": spell.get("cantrip_scaling"),
        "upcast_scaling": spell.get("upcast_scaling"),
        "area_shape": spell.get("area_shape"),
        "area_size": spell.get("area_size"),
        "target_type": spell.get("target_type"),
        "target_count": spell.get("target_count"),
        "save_effect": spell.get("save_effect"),
        "tags": spell.get("tags", []),
    }

def get_scaled_cantrip_damage(spell: dict, caster_level: int) -> str:
    """
    Get the appropriate damage dice for a cantrip based on caster level.
    Uses the cantrip_scaling field from the new spell schema.
    
    Args:
        spell: Normalized spell dict with cantrip_scaling
        caster_level: Character's total level
    
    Returns:
        Damage dice string (e.g., "2d10" at level 5+)
    """
    base_damage = spell.get("damage")
    scaling = spell.get("cantrip_scaling")
    
    if not scaling:
        return base_damage
    
    # Find the highest threshold the caster meets
    # Scaling is dict like {"5": "2d10", "11": "3d10", "17": "4d10"}
    scaled_damage = base_damage
    
    for level_str, dice in sorted(scaling.items(), key=lambda x: int(x[0])):
        level_threshold = int(level_str)
        if caster_level >= level_threshold:
            # Handle beam-style scaling (e.g., "2x1d10" for Eldritch Blast)
            if "x" in dice:
                # Multiple beams - keep as-is for display, actual resolution handles multiple attacks
                scaled_damage = dice
            else:
                scaled_damage = dice
    
    return scaled_damage

def get_upcast_damage(spell: dict, base_level: int, cast_level: int) -> str:
    """
    Calculate damage when casting a spell at a higher level.
    
    Args:
        spell: Normalized spell dict with upcast_scaling
        base_level: The spell's base level (minimum slot required)
        cast_level: The slot level being used to cast
    
    Returns:
        Modified damage dice string
    """
    base_damage = spell.get("damage")
    scaling = spell.get("upcast_scaling")
    
    if not scaling or cast_level <= base_level:
        return base_damage
    
    levels_above = cast_level - base_level
    per_level = scaling.get("per_level")
    
    if per_level and base_damage:
        # Parse the per_level bonus (e.g., "+1d6")
        match = re.match(r"\+?(\d+d\d+)", per_level)
        if match:
            bonus_dice = match.group(1)
            # Parse base damage
            base_match = re.match(r"(\d+)d(\d+)", base_damage)
            if base_match:
                num_dice = int(base_match.group(1))
                die_size = base_match.group(2)
                
                # Parse bonus dice
                bonus_match = re.match(r"(\d+)d(\d+)", bonus_dice)
                if bonus_match:
                    bonus_num = int(bonus_match.group(1))
                    bonus_die = bonus_match.group(2)
                    
                    # If same die size, combine
                    if die_size == bonus_die:
                        total_dice = num_dice + (bonus_num * levels_above)
                        return f"{total_dice}d{die_size}"
                    else:
                        # Different die sizes - show as combined expression
                        extra_dice = bonus_num * levels_above
                        return f"{base_damage}+{extra_dice}d{bonus_die}"
    
    return base_damage

def get_upcast_healing(spell: dict, base_level: int, cast_level: int) -> str:
    """
    Calculate healing when casting a spell at a higher level.
    
    Args:
        spell: Normalized spell dict with upcast_scaling
        base_level: The spell's base level
        cast_level: The slot level being used
    
    Returns:
        Modified healing dice string
    """
    base_healing = spell.get("healing_dice")
    scaling = spell.get("upcast_scaling")
    
    if not scaling or cast_level <= base_level or not base_healing:
        return base_healing
    
    levels_above = cast_level - base_level
    per_level = scaling.get("per_level")
    
    if per_level:
        # Parse the per_level bonus
        match = re.match(r"\+?(\d+d\d+)", per_level)
        if match:
            bonus_dice = match.group(1)
            base_match = re.match(r"(\d+)d(\d+)", base_healing)
            if base_match:
                num_dice = int(base_match.group(1))
                die_size = base_match.group(2)
                
                bonus_match = re.match(r"(\d+)d(\d+)", bonus_dice)
                if bonus_match:
                    bonus_num = int(bonus_match.group(1))
                    bonus_die = bonus_match.group(2)
                    
                    if die_size == bonus_die:
                        total_dice = num_dice + (bonus_num * levels_above)
                        return f"{total_dice}d{die_size}"
    
    return base_healing

def get_upcast_targets(spell: dict, base_level: int, cast_level: int) -> int:
    """
    Calculate number of targets when upcasting.
    
    Args:
        spell: Normalized spell dict
        base_level: The spell's base level
        cast_level: The slot level being used
    
    Returns:
        Number of targets
    """
    base_targets = spell.get("target_count", 1)
    scaling = spell.get("upcast_scaling")
    
    if not scaling or cast_level <= base_level:
        return base_targets
    
    levels_above = cast_level - base_level
    targets_per_level = scaling.get("targets_per_level")
    
    if targets_per_level:
        match = re.match(r"\+?(\d+)", targets_per_level)
        if match:
            extra = int(match.group(1)) * levels_above
            return base_targets + extra
    
    return base_targets

# ---------------- Combat State + Initiative System ----------------

def init_combat_state():
    ss = st.session_state
    ss.setdefault("in_combat", False)
    ss.setdefault("combat_round", 0)
    ss.setdefault("initiative_order", [])
    ss.setdefault("turn_index", 0)

init_combat_state()

def _dex_mod_from_char(c):
    abil = c.get("abilities", {})
    try:
        return (int(abil.get("DEX", 10)) - 10) // 2
    except:
        return 0

def _dex_mod_from_enemy(e):
    dex = e.get("dex") or e.get("dexterity") or e.get("abilities", {}).get("DEX", 10)
    try:
        return (int(dex) - 10) // 2
    except:
        return 0

def roll_initiative_party():
    out = []
    for i, ch in enumerate(st.session_state.party):
        dm = _dex_mod_from_char(ch)
        init_bonus = 0
        
        # Primal Instinct (Barbarian 5+): +2 initiative while raging
        if ch.get("primal_instinct") and ch.get("is_raging"):
            init_bonus += ch.get("rage_initiative_bonus", 2)
        
        # Rogue's Reflexes (Rogue 12+): +DEX mod to initiative
        if ch.get("has_rogues_reflexes"):
            init_bonus += get_rogues_reflexes_initiative_bonus(ch)
        
        roll = random.randint(1,20) + dm + init_bonus
        
        # Relentless (Fighter 16+): Regain 1 martial die when rolling initiative with none remaining
        if ch.get("has_relentless"):
            martial_dice = ch.get("resources", {}).get("Martial Dice", {})
            current_dice = martial_dice.get("current", 0)
            if current_dice == 0:
                max_dice = martial_dice.get("max", 0)
                if max_dice > 0:
                    ch["resources"]["Martial Dice"]["current"] = 1
                    st.session_state.chat_log.append(
                        ("System", f"⚔️ {ch.get('name', 'Fighter')}'s **Relentless** triggers! Regained 1 Martial Die.")
                    )
        
        # Reset Relentless Rage DC at start of combat
        if ch.get("has_relentless_rage"):
            ch["relentless_rage_dc"] = 10
        
        # Reset reactions (including Rogue's Reflexes extra reactions)
        reset_reactions(ch)
        
        out.append({
            "name": ch.get("name","PC"),
            "kind": "party",
            "idx": i,
            "init": roll,
            "dex_mod": dm
        })
    return out

def roll_initiative_enemies():
    out = []
    for i, en in enumerate(st.session_state.enemies):
        dm = _dex_mod_from_enemy(en)
        roll = random.randint(1,20) + dm
        out.append({
            "name": en.get("name","Enemy"),
            "kind": "enemy",
            "idx": i,
            "init": roll,
            "dex_mod": dm
        })
    return out

def start_combat():
    pcs = roll_initiative_party()
    foes = roll_initiative_enemies()
    full = pcs + foes
    full.sort(key=lambda x: (x["init"], x["dex_mod"]), reverse=True)
    st.session_state.initiative_order = full
    st.session_state.in_combat = True
    st.session_state.combat_round = 1
    st.session_state.turn_index = 0
    st.session_state.combat_defeated_enemies = []  # Track defeated enemies for XP
    reset_actions_for_new_turn()

def current_turn():
    order = st.session_state.initiative_order
    idx = st.session_state.turn_index
    if not order: 
        return None
    if idx < 0 or idx >= len(order):
        return None
    return order[idx]

def next_turn():
    if not st.session_state.in_combat:
        return
    order_len = len(st.session_state.initiative_order)
    if order_len == 0:
        return
    
    # Before advancing, tick conditions on the current actor
    ent = current_turn()
    if ent:
        kind = ent.get("kind")
        idx = ent.get("idx")
        actor = None
        actor_name = ent.get("name", "Unknown")
        
        if kind == "party" and idx is not None and 0 <= idx < len(st.session_state.party):
            actor = st.session_state.party[idx]
        elif kind == "enemy" and idx is not None and 0 <= idx < len(st.session_state.enemies):
            actor = st.session_state.enemies[idx]
        
        if actor:
            messages = tick_end_of_turn(actor, actor_name)
            for msg in messages:
                st.session_state.chat_log.append(("System", msg))
    
    # Advance to next turn
    st.session_state.turn_index += 1
    if st.session_state.turn_index >= order_len:
        st.session_state.turn_index = 0
        st.session_state.combat_round += 1
    reset_actions_for_new_turn()

def end_combat(award_combat_xp: bool = True):
    """
    End the current combat encounter.
    
    Args:
        award_combat_xp: If True, calculate and award XP based on defeated enemies.
    """
    # Calculate combat XP before clearing state
    xp_awarded = 0
    if award_combat_xp and st.session_state.get("combat_defeated_enemies"):
        defeated = st.session_state.combat_defeated_enemies
        total_xp = sum(e.get("xp", 0) for e in defeated)
        
        # Split XP among living party members
        living_party = [c for c in st.session_state.party if c.get("hp", 0) > 0]
        if living_party and total_xp > 0:
            xp_per_member = total_xp // len(living_party)
            for char in living_party:
                result = award_xp(
                    char, 
                    xp_per_member, 
                    reason=f"Combat victory ({len(defeated)} enemies defeated)",
                    source="combat"
                )
                xp_awarded += xp_per_member
        
        # Clear defeated enemies list
        st.session_state.combat_defeated_enemies = []
    
    st.session_state.in_combat = False
    st.session_state.initiative_order = []
    st.session_state.combat_round = 0
    st.session_state.turn_index = 0
    
    return xp_awarded

def reset_actions_for_new_turn():
    """
    Reset the current actor's action availability at the start of each turn.
    Also resets movement tracking for Skirmish and similar abilities.
    """
    st.session_state["current_actions"] = {
        "move": True,
        "standard": True,
        "quick": True,
        "immediate": True,
    }
    # Reset movement tracking for Skirmish
    st.session_state["movement_this_turn"] = 0
    st.session_state["skirmish_active"] = False
    # Reset Extra Attack tracking
    st.session_state["attacks_remaining"] = 0
    
    # Reset Sneak Attack for the current actor
    kind, idx, actor = get_current_actor()
    if actor:
        reset_sneak_attack(actor)

def ensure_action_state():
    """
    Make sure current_actions exists; called by any logic that spends actions.
    """
    if "current_actions" not in st.session_state:
        reset_actions_for_new_turn()
    # Also ensure movement tracking exists
    st.session_state.setdefault("movement_this_turn", 0)
    st.session_state.setdefault("skirmish_active", False)


def track_movement(distance_ft: int):
    """
    Track movement distance for Skirmish and similar abilities.
    Call this whenever a character moves.
    """
    ensure_action_state()
    st.session_state["movement_this_turn"] = st.session_state.get("movement_this_turn", 0) + distance_ft
    # Skirmish activates after moving 10+ feet
    if st.session_state["movement_this_turn"] >= 10:
        st.session_state["skirmish_active"] = True


def get_movement_this_turn() -> int:
    """Get total movement distance this turn in feet."""
    ensure_action_state()
    return st.session_state.get("movement_this_turn", 0)


def is_skirmish_active() -> bool:
    """Check if Skirmish bonus is active (moved 10+ feet this turn)."""
    ensure_action_state()
    return st.session_state.get("skirmish_active", False)


def get_skirmish_damage_bonus(char: dict) -> str:
    """
    Get the Skirmish damage bonus dice for a Scout if active.
    Returns empty string if not a Scout or hasn't moved 10+ feet.
    """
    if not is_skirmish_active():
        return ""
    
    cls_name = char.get("class", "")
    if cls_name != "Scout":
        return ""
    
    return char.get("skirmish_damage", "")


def get_skirmish_ac_bonus(char: dict) -> int:
    """
    Get the Skirmish AC bonus for a Scout if active.
    Returns 0 if not a Scout or hasn't moved 10+ feet.
    """
    if not is_skirmish_active():
        return 0
    
    cls_name = char.get("class", "")
    if cls_name != "Scout":
        return 0
    
    return int(char.get("skirmish_ac_bonus", 0))


def can_spend(action_type: str) -> bool:
    """
    Check if the given action type is still available this turn.
    Valid action_type values: "move", "standard", "quick", "immediate"
    Returns True if available, False if already spent.
    """
    ensure_action_state()
    action_type = action_type.lower().strip()
    return st.session_state["current_actions"].get(action_type, False)


def spend(action_type: str) -> None:
    """
    Mark the given action type as spent for this turn.
    Valid action_type values: "move", "standard", "quick", "immediate"
    """
    ensure_action_state()
    action_type = action_type.lower().strip()
    if action_type in st.session_state["current_actions"]:
        st.session_state["current_actions"][action_type] = False


def regrant_action(action_type: str) -> None:
    """
    Regrant an action type (e.g., from Action Surge).
    Valid action_type values: "move", "standard", "quick", "immediate"
    """
    ensure_action_state()
    action_type = action_type.lower().strip()
    if action_type in st.session_state["current_actions"]:
        st.session_state["current_actions"][action_type] = True


def use_action_surge(actor: dict) -> str:
    """
    Use Action Surge to regain Standard action.
    Returns a message describing the result.
    """
    resources = actor.get("resources", {})
    action_surge = resources.get("Action Surge", {})
    current = action_surge.get("current", 0)
    
    if current <= 0:
        return f"{actor.get('name', 'Fighter')} has no Action Surge uses remaining!"
    
    # Spend the resource
    actor["resources"]["Action Surge"]["current"] = current - 1
    
    # Regrant the standard action
    regrant_action("standard")
    
    # Also reset attacks_remaining so they can take a full Attack action again
    set_attacks_remaining(0)
    
    return f"⚡ **{actor.get('name', 'Fighter')}** uses **Action Surge**! Standard action regained. ({current - 1} uses remaining)"


# ============ BARBARIAN RAGE FUNCTIONS ============

def is_raging(actor: dict) -> bool:
    """Check if the actor is currently raging."""
    return actor.get("is_raging", False)


def toggle_rage(actor: dict, activate: bool = True) -> str:
    """
    Activate or deactivate rage for a Barbarian.
    Returns a message describing the result.
    """
    name = actor.get("name", "Barbarian")
    
    if activate:
        # Check if already raging
        if actor.get("is_raging"):
            return f"{name} is already raging!"
        
        # Check rage uses
        resources = actor.get("resources", {})
        rage = resources.get("Rage", {})
        current = rage.get("current", 0)
        
        if current <= 0:
            return f"{name} has no Rage uses remaining!"
        
        # Spend the resource and activate rage
        actor["resources"]["Rage"]["current"] = current - 1
        actor["is_raging"] = True
        actor["rage_rounds_remaining"] = 10  # 1 minute = 10 rounds
        
        # Reset Defy Death for this rage
        if actor.get("has_defy_death"):
            actor["defy_death_used_this_rage"] = False
        
        rage_bonus = actor.get("rage_bonus", 2)
        return (
            f"🔥 **{name}** enters a **RAGE**! "
            f"(+{rage_bonus} STR/CON/WIS saves, +{rage_bonus} melee damage, -2 AC, resist B/P/S) "
            f"[{current - 1} uses remaining]"
        )
    else:
        # Deactivate rage
        if not actor.get("is_raging"):
            return f"{name} is not raging."
        
        actor["is_raging"] = False
        actor["rage_rounds_remaining"] = 0
        
        # Check for fatigue (unless level 11+)
        if not actor.get("no_rage_fatigue"):
            actor["is_fatigued"] = True
            return f"💨 **{name}**'s rage ends. They are now **fatigued** for the rest of the encounter."
        else:
            return f"💨 **{name}**'s rage ends."


def get_rage_attack_bonus(actor: dict) -> int:
    """Get the melee damage bonus from rage."""
    if not actor.get("is_raging"):
        return 0
    return actor.get("rage_bonus", 0)


def get_rage_ac_penalty(actor: dict) -> int:
    """Get the AC penalty from rage (-2)."""
    if not actor.get("is_raging"):
        return 0
    return -2


def get_rage_save_bonus(actor: dict, save_stat: str) -> int:
    """Get the save bonus from rage for STR, CON, or WIS saves."""
    if not actor.get("is_raging"):
        return 0
    if save_stat.upper() in ["STR", "CON", "WIS"]:
        return actor.get("rage_bonus", 0)
    return 0


def apply_rage_damage_reduction(actor: dict, damage: int, damage_type: str = "") -> tuple[int, str]:
    """
    Apply Thick Skinned damage reduction and B/P/S resistance while raging.
    Returns (reduced_damage, message).
    """
    if not actor.get("is_raging"):
        return damage, ""
    
    original = damage
    messages = []
    
    # Thick Skinned DR (all damage types)
    dr = actor.get("rage_damage_reduction", 0)
    if dr > 0:
        damage = max(0, damage - dr)
        messages.append(f"DR {dr}/-")
    
    # B/P/S Resistance (halve damage)
    bps_types = ["bludgeoning", "piercing", "slashing"]
    if damage_type.lower() in bps_types:
        damage = damage // 2
        messages.append(f"resist {damage_type}")
    
    if messages:
        msg = f" (Rage: {', '.join(messages)}: {original} → {damage})"
        return damage, msg
    
    return damage, ""


def check_relentless_rage(actor: dict) -> tuple[bool, str]:
    """
    Check if Relentless Rage triggers when dropped to 0 HP while raging.
    Returns (survived, message).
    """
    if not actor.get("is_raging") or not actor.get("has_relentless_rage"):
        return False, ""
    
    name = actor.get("name", "Barbarian")
    lvl = int(actor.get("level", 1))
    dc = actor.get("relentless_rage_dc", 10)
    
    # Roll CON save
    con_mod = _ability_mod(actor.get("abilities", {}).get("CON", 10))
    rage_bonus = actor.get("rage_bonus", 0)  # Rage bonus applies to CON saves
    roll = random.randint(1, 20)
    total = roll + con_mod + rage_bonus
    
    if total >= dc:
        # Success - drop to 2 × level HP
        new_hp = 2 * lvl
        actor["hp"] = new_hp
        actor["relentless_rage_dc"] = dc + 5  # Increase DC for next use
        
        return True, (
            f"💪 **{name}**'s **Relentless Rage** triggers! "
            f"CON save: d20({roll}) + {con_mod} + {rage_bonus} = **{total}** vs DC {dc} → **SUCCESS!** "
            f"HP becomes {new_hp}. (Next DC: {dc + 5})"
        )
    else:
        return False, (
            f"💀 **{name}**'s **Relentless Rage** fails! "
            f"CON save: d20({roll}) + {con_mod} + {rage_bonus} = **{total}** vs DC {dc} → **FAILED!**"
        )


def check_defy_death(actor: dict) -> tuple[bool, str]:
    """
    Check if Defy Death (Unstoppable Fury) triggers when dropped to 0 HP while raging.
    Returns (survived, message).
    """
    if not actor.get("is_raging") or not actor.get("has_defy_death"):
        return False, ""
    
    if actor.get("defy_death_used_this_rage"):
        return False, ""
    
    name = actor.get("name", "Barbarian")
    
    # Use Defy Death
    actor["defy_death_used_this_rage"] = True
    actor["hp"] = 1
    
    # Gain exhaustion
    exhaustion = actor.get("exhaustion_level", 0) + 1
    actor["exhaustion_level"] = exhaustion
    
    return True, (
        f"🔥 **{name}** uses **Defy Death**! "
        f"Dropped to 1 HP instead of 0. Gained 1 level of exhaustion (now {exhaustion})."
    )


def get_primal_champion_bonus(actor: dict, stat: str) -> int:
    """Get the Primal Champion bonus for STR or CON."""
    if not actor.get("primal_champion_applied"):
        return 0
    if stat.upper() == "STR":
        return actor.get("primal_champion_str_bonus", 0)
    if stat.upper() == "CON":
        return actor.get("primal_champion_con_bonus", 0)
    return 0


def should_rage_end(actor: dict) -> tuple[bool, str]:
    """
    Check if rage should end at end of turn.
    Endless Rage (level 14+): Rage only ends if unconscious or chosen.
    Returns (should_end, reason).
    """
    if not actor.get("is_raging"):
        return False, ""
    
    # Endless Rage prevents automatic ending
    if actor.get("endless_rage"):
        # Only ends if unconscious (HP <= 0)
        if actor.get("hp", 1) <= 0:
            return True, "unconscious"
        return False, ""
    
    # Normal rage duration check
    rounds = actor.get("rage_rounds_remaining", 0)
    if rounds <= 0:
        return True, "duration expired"
    
    return False, ""


def tick_rage_duration(actor: dict) -> str | None:
    """
    Tick down rage duration at end of turn.
    Returns message if rage ends, None otherwise.
    """
    if not actor.get("is_raging"):
        return None
    
    # Endless Rage doesn't tick down
    if actor.get("endless_rage"):
        return None
    
    rounds = actor.get("rage_rounds_remaining", 0)
    if rounds > 0:
        actor["rage_rounds_remaining"] = rounds - 1
        
        if rounds - 1 <= 0:
            # Rage ends
            result = toggle_rage(actor, activate=False)
            return result
    
    return None


def can_be_restrained(actor: dict) -> bool:
    """
    Check if actor can be restrained.
    Unyielding Force (Barbarian 16+) prevents restraint while raging.
    """
    if actor.get("has_unyielding_force") and actor.get("is_raging"):
        return False
    return True


def check_relentless_assault(actor: dict, killed_enemy: bool) -> tuple[bool, str]:
    """
    Check if Relentless Assault triggers after killing an enemy.
    Returns (can_attack, message).
    """
    if not killed_enemy:
        return False, ""
    
    if not actor.get("has_relentless_assault") or not actor.get("is_raging"):
        return False, ""
    
    name = actor.get("name", "Barbarian")
    return True, f"⚔️ **{name}**'s **Relentless Assault** triggers! Free melee attack against another creature within reach."


# ============ ROGUE SNEAK ATTACK MECHANICS ============

def get_sneak_attack_dice(actor: dict) -> int:
    """Get the number of Sneak Attack dice for a Rogue."""
    return actor.get("sneak_attack_dice", 0)


def can_sneak_attack(actor: dict, target: dict, has_attack_bonus: bool = False) -> tuple[bool, str]:
    """
    Check if Sneak Attack can be applied.
    Conditions:
    - Once per turn (not used yet this turn)
    - Target is flanked (ally within 5ft)
    - Target is denied DEX to AC (flat-footed, stunned, etc.)
    - Attacker has a situational bonus (+2 or better)
    - Using finesse or ranged weapon
    
    Returns (can_sneak, reason).
    """
    sneak_dice = get_sneak_attack_dice(actor)
    if sneak_dice <= 0:
        return False, "No Sneak Attack ability"
    
    # Check if already used this turn
    if actor.get("sneak_attack_used_this_turn"):
        return False, "Already used Sneak Attack this turn"
    
    # Check conditions
    reasons = []
    
    # Has situational attack bonus (+2 or better, replaces advantage)
    if has_attack_bonus:
        reasons.append("has attack bonus (+2)")
    
    # Target is flat-footed or denied DEX
    if target.get("is_flat_footed") or target.get("denied_dex_to_ac"):
        reasons.append("target denied DEX to AC")
    
    # Target is flanked (ally within 5ft)
    # Check if any ally is adjacent to target
    target_pos = target.get("pos")
    if target_pos:
        for ally in st.session_state.get("party", []):
            if ally == actor:
                continue
            if ally.get("hp", 0) <= 0:
                continue
            ally_pos = ally.get("pos")
            if ally_pos:
                distance = get_grid_distance(target_pos, ally_pos)
                if distance <= 1:  # Adjacent (within 5ft)
                    reasons.append("ally adjacent to target")
                    break
    
    if reasons:
        return True, ", ".join(reasons)
    
    return False, "No valid Sneak Attack condition (need +2 bonus, adjacent ally, or target denied DEX)"


def apply_sneak_attack(actor: dict, base_damage: int) -> tuple[int, str]:
    """
    Apply Sneak Attack damage.
    Returns (total_damage, breakdown_string).
    """
    sneak_dice = get_sneak_attack_dice(actor)
    if sneak_dice <= 0:
        return base_damage, ""
    
    # Roll sneak attack dice
    sneak_damage = 0
    rolls = []
    for _ in range(sneak_dice):
        roll = random.randint(1, 6)
        rolls.append(roll)
        sneak_damage += roll
    
    # Mark as used this turn
    actor["sneak_attack_used_this_turn"] = True
    
    breakdown = f"{sneak_dice}d6={sneak_damage} ({'+'.join(map(str, rolls))})"
    return base_damage + sneak_damage, f"Sneak Attack {breakdown}"


def reset_sneak_attack(actor: dict):
    """Reset Sneak Attack for a new turn."""
    actor["sneak_attack_used_this_turn"] = False


def use_uncanny_dodge(actor: dict, damage: int) -> tuple[int, str]:
    """
    Use Uncanny Dodge to halve incoming damage.
    Returns (reduced_damage, message).
    """
    if not actor.get("has_uncanny_dodge"):
        return damage, ""
    
    reduced = damage // 2
    name = actor.get("name", "Rogue")
    return reduced, f"⚡ **{name}** uses **Uncanny Dodge**! Damage halved: {damage} → {reduced}"


def check_evasion(actor: dict, save_succeeded: bool, damage: int) -> tuple[int, str]:
    """
    Apply Evasion or Improved Evasion to DEX save damage.
    Returns (final_damage, message).
    """
    name = actor.get("name", "Rogue")
    
    if actor.get("has_improved_evasion"):
        if save_succeeded:
            return 0, f"🎯 **{name}**'s **Improved Evasion**: Save succeeded - no damage!"
        else:
            return damage // 2, f"🎯 **{name}**'s **Improved Evasion**: Save failed - half damage ({damage} → {damage // 2})"
    
    if actor.get("has_evasion"):
        if save_succeeded:
            return 0, f"🎯 **{name}**'s **Evasion**: Save succeeded - no damage!"
        # Normal failure = full damage (Evasion only helps on success)
    
    return damage, ""


def get_stealthy_penalty(actor: dict) -> int:
    """Get the Perception penalty enemies take when trying to detect this Rogue."""
    if not actor.get("stealthy"):
        return 0
    return actor.get("stealthy_penalty", 0)


def get_agile_defense_bonus(actor: dict) -> int:
    """Get the Agile Defense AC bonus when dodging."""
    if not actor.get("has_agile_defense"):
        return 0
    
    # Check for light or no armor
    equipment_names = [x.lower() for x in (actor.get("equipment") or []) if isinstance(x, str)]
    srd_equipment = st.session_state.get("srd_equipment") or []
    armor_is_light = True
    for eq_name in equipment_names:
        for item in srd_equipment:
            item_name = (item.get("name") or "").lower()
            if item_name == eq_name or eq_name in item_name or item_name in eq_name:
                armor_cat = item.get("armor_category", "")
                if armor_cat in ("Medium", "Heavy"):
                    armor_is_light = False
                    break
    
    if armor_is_light:
        return actor.get("agile_defense_bonus", 0)
    return 0


def use_agile_defense(actor: dict) -> str:
    """
    Use Agile Defense to gain extra AC when dodging.
    Returns message describing the effect.
    """
    bonus = get_agile_defense_bonus(actor)
    if bonus <= 0:
        return f"{actor.get('name', 'Rogue')} cannot use Agile Defense (requires light or no armor)."
    
    # Set the agile defense active flag
    actor["agile_defense_active"] = True
    actor["agile_defense_ac_bonus"] = bonus
    
    name = actor.get("name", "Rogue")
    return f"🛡️ **{name}** takes the **Agile Defense** stance! +{bonus} AC until start of next turn."


# Cunning Strike effects
CUNNING_STRIKE_EFFECTS = {
    "poison": {
        "dice_cost": 1,
        "save": "CON",
        "effect": "Poisoned for 1 minute (1d6 poison damage per round)",
        "duration": "1 minute",
        "requires_improved": False,
    },
    "blind": {
        "dice_cost": 2,
        "save": "CON",
        "effect": "Blinded for 1 round",
        "duration": "1 round",
        "requires_improved": False,
    },
    "slow": {
        "dice_cost": 2,
        "save": "CON",
        "effect": "Speed halved for 1 minute",
        "duration": "1 minute",
        "requires_improved": False,
    },
    "disarm": {
        "dice_cost": 1,
        "save": "STR",
        "effect": "Drops held item",
        "duration": "instant",
        "requires_improved": False,
    },
    "trip": {
        "dice_cost": 1,
        "save": "DEX",
        "effect": "Knocked prone",
        "duration": "instant",
        "requires_improved": False,
    },
    # Improved Cunning Strike effects (Level 15+)
    "daze": {
        "dice_cost": 2,
        "save": "CON",
        "effect": "Dazed for 1 round (can't take reactions, -2 AC)",
        "duration": "1 round",
        "requires_improved": True,
    },
    "knock_out": {
        "dice_cost": 6,
        "save": "CON",
        "effect": "Unconscious for 1 minute (wakes if damaged or shaken awake)",
        "duration": "1 minute",
        "requires_improved": True,
    },
}


def can_use_cunning_strike(actor: dict, effect_name: str) -> tuple[bool, str]:
    """
    Check if Cunning Strike can be used with the specified effect.
    Returns (can_use, reason).
    """
    if not actor.get("has_cunning_strike"):
        return False, "No Cunning Strike ability"
    
    effect = CUNNING_STRIKE_EFFECTS.get(effect_name.lower())
    if not effect:
        return False, f"Unknown Cunning Strike effect: {effect_name}"
    
    # Check if effect requires Improved Cunning Strike
    if effect.get("requires_improved") and not actor.get("has_improved_cunning_strike"):
        return False, f"{effect_name.title()} requires Improved Cunning Strike (Level 15+)"
    
    sneak_dice = get_sneak_attack_dice(actor)
    if sneak_dice < effect["dice_cost"]:
        return False, f"Not enough Sneak Attack dice (need {effect['dice_cost']}, have {sneak_dice})"
    
    return True, ""


def get_max_cunning_strike_effects(actor: dict) -> int:
    """Get the maximum number of Cunning Strike effects that can be applied per Sneak Attack."""
    if actor.get("has_improved_cunning_strike"):
        return 2  # Improved Cunning Strike allows 2 effects
    return 1


def get_available_cunning_strike_effects(actor: dict) -> list[str]:
    """Get list of Cunning Strike effects available to this actor."""
    if not actor.get("has_cunning_strike"):
        return []
    
    has_improved = actor.get("has_improved_cunning_strike", False)
    available = []
    
    for name, effect in CUNNING_STRIKE_EFFECTS.items():
        if effect.get("requires_improved") and not has_improved:
            continue
        available.append(name)
    
    return available


def apply_cunning_strike(actor: dict, target: dict, effect_name: str) -> tuple[int, str]:
    """
    Apply a Cunning Strike effect, forgoing some Sneak Attack dice.
    Returns (dice_remaining, message).
    """
    effect = CUNNING_STRIKE_EFFECTS.get(effect_name.lower())
    if not effect:
        return get_sneak_attack_dice(actor), f"Unknown effect: {effect_name}"
    
    dc = actor.get("cunning_strike_dc", 15)
    save_type = effect["save"]
    
    # Roll the save for the target
    save_mod = 0
    if save_type == "CON":
        save_mod = _ability_mod(target.get("abilities", {}).get("CON", 10))
    elif save_type == "DEX":
        save_mod = _ability_mod(target.get("abilities", {}).get("DEX", 10))
    elif save_type == "STR":
        save_mod = _ability_mod(target.get("abilities", {}).get("STR", 10))
    
    roll = random.randint(1, 20)
    total = roll + save_mod
    
    dice_forfeited = effect["dice_cost"]
    dice_remaining = get_sneak_attack_dice(actor) - dice_forfeited
    
    name = actor.get("name", "Rogue")
    target_name = target.get("name", "Target")
    
    if total >= dc:
        msg = (f"🎯 **{name}** uses **Cunning Strike ({effect_name.title()})** (forfeits {dice_forfeited}d6)! "
               f"{target_name} {save_type} save: d20({roll}) + {save_mod} = {total} vs DC {dc} → **SAVED!**")
    else:
        msg = (f"🎯 **{name}** uses **Cunning Strike ({effect_name.title()})** (forfeits {dice_forfeited}d6)! "
               f"{target_name} {save_type} save: d20({roll}) + {save_mod} = {total} vs DC {dc} → **FAILED!** "
               f"Effect: {effect['effect']}")
        
        # Apply the effect to target
        target[f"cunning_strike_{effect_name}"] = True
        if effect["duration"] != "instant":
            target[f"cunning_strike_{effect_name}_duration"] = effect["duration"]
    
    return dice_remaining, msg


# ============ MOVING SHADOW MECHANICS ============

def get_stealth_speed_penalty(actor: dict) -> int:
    """
    Get the speed penalty when using Stealth.
    Moving Shadow removes this penalty.
    Returns 0 if no penalty, otherwise the penalty amount.
    """
    if actor.get("has_moving_shadow"):
        return 0  # No penalty - can move at full speed while stealthing
    return -10  # Standard penalty: -10 ft speed while stealthing


def can_stealth_while_observed(actor: dict) -> bool:
    """
    Check if actor can attempt Stealth while being observed.
    Moving Shadow allows this with cover/concealment.
    """
    return actor.get("has_moving_shadow", False)


# ============ ROGUE'S REFLEXES MECHANICS ============

def get_rogues_reflexes_initiative_bonus(actor: dict) -> int:
    """Get the Initiative bonus from Rogue's Reflexes."""
    if not actor.get("has_rogues_reflexes"):
        return 0
    return actor.get("rogues_reflexes_bonus", 0)


def get_reactions_per_round(actor: dict) -> int:
    """
    Get the number of reactions an actor can take per round.
    Rogue's Reflexes grants 2 reactions instead of 1.
    """
    if actor.get("has_rogues_reflexes"):
        return 2
    return 1


def reset_reactions(actor: dict):
    """Reset reactions at the start of a round."""
    max_reactions = get_reactions_per_round(actor)
    actor["reactions_remaining"] = max_reactions


def use_reaction(actor: dict) -> tuple[bool, str]:
    """
    Attempt to use a reaction.
    Returns (success, message).
    """
    remaining = actor.get("reactions_remaining", 1)
    if remaining <= 0:
        return False, f"{actor.get('name', 'Actor')} has no reactions remaining!"
    
    actor["reactions_remaining"] = remaining - 1
    max_reactions = get_reactions_per_round(actor)
    
    if max_reactions > 1:
        return True, f"({remaining - 1}/{max_reactions} reactions remaining)"
    return True, ""


# ============ MASTER OF DISGUISE MECHANICS ============

def get_disguise_bonus(actor: dict) -> int:
    """Get bonus to Disguise checks from Master of Disguise."""
    if actor.get("has_master_of_disguise"):
        return 10
    return 0


def get_disguise_time(actor: dict) -> str:
    """Get the time required to create a disguise."""
    if actor.get("has_master_of_disguise"):
        return "1 minute"
    return "1d3 × 10 minutes"


def can_take_10_on_disguise(actor: dict, is_threatened: bool = False) -> bool:
    """
    Check if actor can take 10 on Disguise checks.
    Master of Disguise allows taking 10 even when threatened.
    """
    if actor.get("has_master_of_disguise"):
        return True  # Always can take 10
    return not is_threatened  # Normal rules


# ============ TRICKSTER'S ESCAPE MECHANICS ============

def use_tricksters_escape(actor: dict) -> tuple[bool, str]:
    """
    Use Trickster's Escape to end conditions and teleport.
    Returns (success, message).
    """
    if not actor.get("has_tricksters_escape"):
        return False, "No Trickster's Escape ability"
    
    # Check resource
    resource = actor.get("resources", {}).get("Trickster's Escape", {})
    if resource.get("current", 0) <= 0:
        return False, "Trickster's Escape already used today"
    
    # Consume resource
    actor["resources"]["Trickster's Escape"]["current"] -= 1
    
    # End conditions
    conditions_ended = []
    for condition in ["grappled", "restrained", "incapacitated"]:
        if actor.get(condition):
            actor[condition] = False
            conditions_ended.append(condition)
    
    name = actor.get("name", "Rogue")
    
    if conditions_ended:
        cond_str = ", ".join(conditions_ended)
        msg = f"✨ **{name}** uses **Trickster's Escape**! Ends {cond_str} and teleports up to 30 ft!"
    else:
        msg = f"✨ **{name}** uses **Trickster's Escape**! Teleports up to 30 ft to an unoccupied space!"
    
    return True, msg


# ============ QUICK FINGERS MECHANICS ============

def can_use_quick_fingers(actor: dict) -> bool:
    """Check if actor has Quick Fingers ability."""
    return actor.get("has_quick_fingers", False)


def get_disable_device_speed_multiplier(actor: dict) -> float:
    """Get the speed multiplier for Disable Device (picking locks, disarming traps)."""
    if actor.get("has_quick_fingers"):
        return 2.0  # Double speed
    return 1.0


# ============ HIDE IN PLAIN SIGHT MECHANICS ============

def can_hide_without_cover(actor: dict) -> bool:
    """
    Check if actor can hide without cover or concealment.
    Hide in Plain Sight allows this.
    """
    return actor.get("has_hide_in_plain_sight", False)


def get_perception_penalty_to_find(actor: dict) -> int:
    """
    Get the penalty enemies have when trying to find this actor.
    Hide in Plain Sight gives -2 penalty (replaces disadvantage).
    Returns the penalty as a negative number.
    """
    if actor.get("has_hide_in_plain_sight"):
        return -2  # -2 penalty replaces disadvantage
    elif actor.get("has_moving_shadow"):
        return 0  # Moving Shadow doesn't give penalty, just allows hiding while observed
    return 0


# ============ INFILTRATOR'S EDGE MECHANICS ============

def get_infiltrators_edge_bonus(actor: dict, check_type: str) -> int:
    """
    Get bonuses from Infiltrator's Edge for various checks.
    Returns flat bonus (+2 replaces advantage).
    check_type: "trap", "secret_door", "perception_hidden", "magical_trap"
    """
    if not actor.get("has_infiltrators_edge"):
        return 0
    
    if check_type == "trap":
        return 2  # +2 on finding/disabling traps (replaces advantage)
    elif check_type == "secret_door":
        return 2  # +2 on finding secret doors (replaces advantage)
    elif check_type == "perception_hidden":
        return 5  # +5 to spot hidden creatures
    elif check_type == "magical_trap":
        return 2  # +2 to detect magical traps/wards (replaces advantage)
    
    return 0


def can_detect_magical_traps(actor: dict) -> bool:
    """Check if actor can detect magical traps and wards."""
    return actor.get("has_infiltrators_edge", False)


# ============ MASTER BURGLAR MECHANICS ============

def get_auto_success_disable_dc(actor: dict) -> int:
    """Get the DC threshold for automatic Disable Device success."""
    if actor.get("has_master_burglar"):
        return 30  # Auto-succeed on DC 30 or lower
    return 0  # No auto-success


def can_bypass_magical_locks(actor: dict) -> bool:
    """Check if actor can bypass magical locks (as Knock spell)."""
    return actor.get("has_master_burglar", False)


def permanently_disables_traps(actor: dict) -> bool:
    """Check if traps disabled by this actor cannot be reset."""
    return actor.get("has_master_burglar", False)


def check_disable_device_auto_success(actor: dict, dc: int) -> tuple[bool, str]:
    """
    Check if a Disable Device check automatically succeeds.
    Returns (auto_success, message).
    """
    threshold = get_auto_success_disable_dc(actor)
    if threshold > 0 and dc <= threshold:
        name = actor.get("name", "Rogue")
        msg = f"🔓 **{name}**'s **Master Burglar**: Automatic success on DC {dc} Disable Device!"
        return True, msg
    return False, ""


# ============ FLAT-FOOTED AND SURPRISE MECHANICS ============

def can_be_surprised(actor: dict) -> bool:
    """
    Check if an actor can be surprised.
    Primal Awareness (Barbarian 2+) prevents surprise.
    Primal Instinct while raging prevents surprise.
    """
    # Primal Awareness (Barbarian 2+)
    if actor.get("primal_awareness"):
        return False
    
    # Primal Instinct while raging (Barbarian 5+)
    if actor.get("primal_instinct") and actor.get("is_raging"):
        return False
    
    # Scout Wild Reflexes (if used)
    if actor.get("wild_reflexes_active"):
        return False
    
    return True


def loses_dex_to_ac_when_flatfooted(actor: dict) -> bool:
    """
    Check if an actor loses DEX to AC when flat-footed.
    Primal Awareness (Barbarian 2+) keeps DEX to AC even when flat-footed.
    """
    # Primal Awareness keeps DEX to AC
    if actor.get("primal_awareness"):
        return False
    
    return True


def get_flatfooted_ac(actor: dict) -> int:
    """
    Calculate AC when flat-footed (before acting in combat, or caught off-guard).
    Characters with Primal Awareness keep their full AC.
    """
    base_ac = actor.get("ac", 10)
    
    # Check if actor keeps DEX to AC
    if not loses_dex_to_ac_when_flatfooted(actor):
        return base_ac  # Keep full AC
    
    # Calculate AC without DEX bonus
    dex_mod = _ability_mod(actor.get("abilities", {}).get("DEX", 10))
    
    # Only remove positive DEX bonus
    if dex_mod > 0:
        return base_ac - dex_mod
    
    return base_ac


def get_enhanced_reflexes_bonus(actor: dict) -> int:
    """
    Get the Enhanced Reflexes AC bonus (Barbarian 3+).
    Returns CON modifier to add to AC as a reaction when flat-footed/surprised.
    """
    if not actor.get("enhanced_reflexes"):
        return 0
    
    con_mod = _ability_mod(actor.get("abilities", {}).get("CON", 10))
    return max(0, con_mod)


def use_enhanced_reflexes(actor: dict) -> tuple[int, str]:
    """
    Use Enhanced Reflexes reaction to add CON to AC.
    Returns (bonus, message).
    """
    if not actor.get("enhanced_reflexes"):
        return 0, ""
    
    bonus = get_enhanced_reflexes_bonus(actor)
    name = actor.get("name", "Barbarian")
    
    return bonus, f"⚡ **{name}** uses **Enhanced Reflexes**! +{bonus} AC vs this attack."


def can_use_indomitable(actor: dict) -> bool:
    """Check if actor can use Indomitable to reroll a failed save."""
    resources = actor.get("resources", {})
    indomitable = resources.get("Indomitable", {})
    return indomitable.get("current", 0) > 0


def use_indomitable(actor: dict, original_roll: int, save_stat: str, dc: int) -> tuple[bool, str]:
    """
    Use Indomitable to reroll a failed saving throw.
    Returns (success, message) where success indicates if the new roll passed.
    """
    resources = actor.get("resources", {})
    indomitable = resources.get("Indomitable", {})
    current = indomitable.get("current", 0)
    
    if current <= 0:
        return False, f"{actor.get('name', 'Fighter')} has no Indomitable uses remaining!"
    
    # Spend the resource
    actor["resources"]["Indomitable"]["current"] = current - 1
    
    # Reroll the save
    new_roll = random.randint(1, 20)
    save_mod = get_total_save(actor, save_stat)
    new_total = new_roll + save_mod
    success = new_total >= dc
    
    result = "**PASSED**" if success else "**FAILED**"
    msg = (f"🔄 **{actor.get('name', 'Fighter')}** uses **Indomitable**! "
           f"Rerolling {save_stat} save: d20({new_roll}) + {save_mod} = **{new_total}** vs DC {dc} → {result}")
    
    return success, msg


def can_use_indomitable_will(actor: dict, save_stat: str) -> bool:
    """
    Check if actor can use Indomitable Will to reroll a WIS or CHA save.
    Indomitable Will allows rerolling failed WIS and CHA saves once per attempt.
    """
    # Only works for WIS and CHA saves
    if save_stat.upper() not in ["WIS", "CHA", "WISDOM", "CHARISMA"]:
        return False
    
    # Check if they have the feature
    features = actor.get("features", [])
    has_indomitable_will = any("Indomitable Will" in f for f in features)
    
    return has_indomitable_will


def use_indomitable_will(actor: dict, original_roll: int, save_stat: str, dc: int) -> tuple[bool, str]:
    """
    Use Indomitable Will to reroll a failed WIS or CHA saving throw.
    This can be used once per attempt (no resource cost).
    Returns (success, message) where success indicates if the new roll passed.
    """
    # Reroll the save
    new_roll = random.randint(1, 20)
    save_mod = get_total_save(actor, save_stat)
    new_total = new_roll + save_mod
    success = new_total >= dc
    
    result = "**PASSED**" if success else "**FAILED**"
    msg = (f"💪 **{actor.get('name', 'Fighter')}** uses **Indomitable Will**! "
           f"Rerolling {save_stat} save: d20({new_roll}) + {save_mod} = **{new_total}** vs DC {dc} → {result}")
    
    return success, msg


def apply_damage_to_party_member(target: dict, target_idx: int, damage: int, damage_type: str = "") -> tuple[int, int, str]:
    """
    Apply damage to a party member, checking for various survival abilities.
    Returns (before_hp, after_hp, special_message).
    """
    before_hp = int(target.get("hp", 0))
    special_msgs = []
    
    # Apply Barbarian rage damage reduction and resistance
    if is_raging(target):
        damage, rage_msg = apply_rage_damage_reduction(target, damage, damage_type)
        if rage_msg:
            special_msgs.append(rage_msg)
    
    after_hp = max(0, before_hp - damage)
    
    # Check survival abilities when dropped to 0 HP
    if after_hp == 0:
        survived = False
        
        # Barbarian Relentless Rage (Level 6+) - check first
        if not survived and target.get("has_relentless_rage") and is_raging(target):
            survived, msg = check_relentless_rage(target)
            if survived:
                after_hp = target.get("hp", 1)
                special_msgs.append(msg)
        
        # Barbarian Defy Death (Level 16+) - if Relentless Rage failed or wasn't available
        if not survived and target.get("has_defy_death") and is_raging(target):
            survived, msg = check_defy_death(target)
            if survived:
                after_hp = target.get("hp", 1)
                special_msgs.append(msg)
        
        # Fighter Avatar of War (Level 18+)
        if not survived and target.get("has_avatar_of_war"):
            avatar_resource = target.get("resources", {}).get("Avatar of War", {})
            avatar_uses = avatar_resource.get("current", 0)
            
            if avatar_uses > 0:
                # Use Avatar of War
                target["resources"]["Avatar of War"]["current"] = avatar_uses - 1
                after_hp = 1
                survived = True
                
                # Grant +2 attack bonus until end of next turn
                target["avatar_of_war_attack_bonus"] = 2
                target["avatar_of_war_expires_round"] = st.session_state.get("combat_round", 1) + 1
                
                special_msgs.append(
                    f"⚔️ **{target.get('name', 'Fighter')}'s Avatar of War triggers!** "
                    f"Dropped to 1 HP instead of 0! (+2 attack until end of next turn)"
                )
    
    # Apply the final HP
    st.session_state.party[target_idx]["hp"] = after_hp
    
    special_msg = " ".join(special_msgs) if special_msgs else ""
    return before_hp, after_hp, special_msg


def can_use_unmatched_combatant(actor: dict) -> bool:
    """Check if actor can use Unmatched Combatant reroll."""
    resources = actor.get("resources", {})
    uc = resources.get("Unmatched Combatant", {})
    return uc.get("current", 0) > 0


def use_unmatched_combatant_reroll(actor: dict, roll_type: str, original_roll: int, dice_expr: str = "") -> tuple[int, str]:
    """
    Use Unmatched Combatant to reroll an attack, save, or damage roll.
    Returns (new_result, message).
    """
    resources = actor.get("resources", {})
    uc = resources.get("Unmatched Combatant", {})
    current = uc.get("current", 0)
    
    if current <= 0:
        return original_roll, f"{actor.get('name', 'Fighter')} has no Unmatched Combatant uses remaining!"
    
    # Spend the resource
    actor["resources"]["Unmatched Combatant"]["current"] = current - 1
    
    if roll_type == "damage" and dice_expr:
        new_result, breakdown = roll_damage_expr(dice_expr)
        msg = (f"🏆 **{actor.get('name', 'Fighter')}** uses **Unmatched Combatant**! "
               f"Rerolling damage: {dice_expr} → **{new_result}** ({breakdown})")
    else:
        new_result = random.randint(1, 20)
        msg = (f"🏆 **{actor.get('name', 'Fighter')}** uses **Unmatched Combatant**! "
               f"Rerolling d20: **{new_result}** (was {original_roll})")
    
    return new_result, msg


def explain_action_state() -> str:
    """
    Returns a human-readable string showing available actions.
    Example: "Move: ✅ Standard: ❌ Quick: ✅ Immediate: ✅"
    """
    ensure_action_state()
    ca = st.session_state["current_actions"]
    parts = []
    for action_type in ["move", "standard", "quick", "immediate"]:
        available = ca.get(action_type, False)
        icon = "✅" if available else "❌"
        label = action_type.capitalize()
        parts.append(f"{label}: {icon}")
    return " | ".join(parts)


def get_action_type_for_attack(action_obj: dict | None) -> str:
    """
    Determine what action type an attack/action requires.
    Checks the action_type field from ACTION_SCHEMA, defaults to "standard".
    """
    if not action_obj or not isinstance(action_obj, dict):
        return "standard"
    action_type = action_obj.get("action_type", "standard")
    if isinstance(action_type, str) and action_type.lower() in {"move", "standard", "quick", "immediate"}:
        return action_type.lower()
    return "standard"


# ==============
# CONDITIONS SYSTEM
# ==============
# Each actor has conditions: List[{"name": str, "duration_rounds": int|None, "source": str|None}]
# duration_rounds counts down at end of that actor's turn. None = indefinite.

def ensure_conditions(actor: dict) -> list:
    """
    Ensure the actor has a conditions list. Returns the list.
    """
    if "conditions" not in actor or not isinstance(actor.get("conditions"), list):
        actor["conditions"] = []
    return actor["conditions"]


def add_condition(actor: dict, name: str, duration_rounds: int | None = None, source: str | None = None) -> None:
    """
    Add a condition to an actor. If the condition already exists, update its duration.
    """
    conditions = ensure_conditions(actor)
    
    # Check if condition already exists
    for cond in conditions:
        if cond.get("name", "").lower() == name.lower():
            # Update existing condition
            cond["duration_rounds"] = duration_rounds
            cond["source"] = source
            return
    
    # Add new condition
    conditions.append({
        "name": name,
        "duration_rounds": duration_rounds,
        "source": source,
    })


def remove_condition(actor: dict, name: str) -> bool:
    """
    Remove a condition from an actor by name.
    Returns True if removed, False if not found.
    """
    conditions = ensure_conditions(actor)
    for i, cond in enumerate(conditions):
        if cond.get("name", "").lower() == name.lower():
            conditions.pop(i)
            return True
    return False


def actor_has_condition(actor: dict, name: str) -> bool:
    """
    Check if an actor has a specific condition.
    """
    conditions = ensure_conditions(actor)
    for cond in conditions:
        if cond.get("name", "").lower() == name.lower():
            return True
    return False


def get_condition_display(cond: dict) -> str:
    """
    Return a display string for a condition.
    Example: "Prone (2 rounds)" or "Poisoned (indefinite)"
    """
    name = cond.get("name", "Unknown")
    duration = cond.get("duration_rounds")
    source = cond.get("source")
    
    if duration is None:
        dur_str = "indefinite"
    elif duration == 1:
        dur_str = "1 round"
    else:
        dur_str = f"{duration} rounds"
    
    result = f"{name} ({dur_str})"
    if source:
        result += f" [from {source}]"
    return result


def tick_end_of_turn(actor: dict, actor_name: str) -> list:
    """
    Called at the end of an actor's turn to tick down condition durations.
    Returns a list of log messages for expired conditions.
    """
    conditions = ensure_conditions(actor)
    messages = []
    expired = []
    
    for cond in conditions:
        duration = cond.get("duration_rounds")
        if duration is not None:
            # Decrement duration
            new_duration = duration - 1
            if new_duration <= 0:
                # Condition expired
                expired.append(cond)
                messages.append(f"{actor_name}'s **{cond.get('name', 'condition')}** has expired.")
            else:
                cond["duration_rounds"] = new_duration
    
    # Remove expired conditions
    for exp in expired:
        conditions.remove(exp)
    
    return messages


def get_srd_condition_names() -> list:
    """
    Return a list of condition names from loaded SRD conditions.
    """
    srd_conds = st.session_state.get("srd_conditions", {})
    if isinstance(srd_conds, dict):
        return sorted(srd_conds.keys())
    return []


# ==============
# RANGE BAND POSITIONING
# ==============
# Lightweight positioning using range bands: engaged, near, far
# - engaged: melee range (<=5 ft)
# - near: close range (<=30 ft)
# - far: long range (>30 ft)

POSITION_BANDS = ["engaged", "near", "far"]
BAND_ORDER = {"engaged": 0, "near": 1, "far": 2}


def ensure_position_band(actor: dict) -> str:
    """
    Ensure the actor has a valid position_band. Returns the band.
    Default is "near".
    """
    band = actor.get("position_band", "near")
    if band not in POSITION_BANDS:
        band = "near"
        actor["position_band"] = band
    return band


def get_position_band(actor: dict) -> str:
    """
    Get the actor's current position band.
    """
    return ensure_position_band(actor)


def set_position_band(actor: dict, band: str) -> None:
    """
    Set the actor's position band.
    """
    if band in POSITION_BANDS:
        actor["position_band"] = band


def get_attack_max_band(attack: dict) -> str:
    """
    Determine the maximum range band an attack can reach based on its range.
    - range <= 5 (or None/melee): engaged only
    - range <= 30: near
    - range > 30: far
    """
    range_val = attack.get("range")
    reach_val = attack.get("reach")
    
    # Use reach if range not specified (melee weapons)
    if range_val is None:
        range_val = reach_val
    
    # Parse range if it's a string like "120 ft."
    if isinstance(range_val, str):
        import re
        m = re.search(r"(\d+)", range_val)
        range_val = int(m.group(1)) if m else None
    
    # Convert to int if possible
    if range_val is not None:
        try:
            range_val = int(range_val)
        except (ValueError, TypeError):
            range_val = None
    
    # Determine max band
    if range_val is None or range_val <= 5:
        return "engaged"  # melee range
    elif range_val <= 30:
        return "near"
    else:
        return "far"


def can_attack_at_band(attack: dict, target_band: str) -> bool:
    """
    Check if an attack can reach a target at the given band.
    """
    max_band = get_attack_max_band(attack)
    max_band_idx = BAND_ORDER.get(max_band, 0)
    target_band_idx = BAND_ORDER.get(target_band, 1)
    return target_band_idx <= max_band_idx


def get_relative_band(attacker: dict, target: dict) -> str:
    """
    Get the relative position band between attacker and target.
    For simplicity, we use the target's band as the relative distance.
    (In a more complex system, you'd track actual positions)
    """
    return get_position_band(target)


def explain_band_requirement(attack: dict) -> str:
    """
    Return a human-readable string explaining the attack's range requirement.
    """
    max_band = get_attack_max_band(attack)
    range_val = attack.get("range") or attack.get("reach")
    
    if max_band == "engaged":
        return "Melee (engaged only)"
    elif max_band == "near":
        return f"Range {range_val} (engaged or near)"
    else:
        return f"Range {range_val} (any band)"


def move_band(actor: dict, direction: str) -> tuple[bool, str]:
    """
    Move an actor one band in the given direction.
    direction: "closer" (toward engaged) or "away" (toward far)
    Returns (success, message).
    """
    current = get_position_band(actor)
    current_idx = BAND_ORDER.get(current, 1)
    
    if direction == "closer":
        if current_idx == 0:
            return False, "Already at engaged range, cannot move closer."
        new_idx = current_idx - 1
    elif direction == "away":
        if current_idx == 2:
            return False, "Already at far range, cannot move further away."
        new_idx = current_idx + 1
    else:
        return False, f"Invalid direction: {direction}"
    
    new_band = POSITION_BANDS[new_idx]
    actor["position_band"] = new_band
    return True, f"Moved from {current} to {new_band}."


def get_band_display(band: str) -> str:
    """
    Return a display string for a position band with icon.
    """
    icons = {"engaged": "⚔️", "near": "🏹", "far": "🔭"}
    return f"{icons.get(band, '•')} {band.capitalize()}"


# ==============
# ENEMY AI-LITE (Grid-Aware)
# ==============
# Simple enemy turn behavior using tactical grid.
# - Choose target: prefer closest reachable, then lowest HP party member
# - Move toward target if out of attack range
# - Choose attack: use first in-range attack

def get_grid_distance(pos1: dict, pos2: dict) -> int:
    """Calculate Chebyshev distance (diagonal movement allowed) between two positions."""
    if not pos1 or not pos2:
        return 999
    dx = abs(pos1.get("x", 0) - pos2.get("x", 0))
    dy = abs(pos1.get("y", 0) - pos2.get("y", 0))
    return max(dx, dy)

def get_attack_range_squares(attack: dict) -> int:
    """Get attack range in grid squares (assuming 5ft per square)."""
    grid = st.session_state.get("grid", {})
    square_size = grid.get("square_size_ft", 5)
    
    # Get range from attack - check multiple fields
    range_ft = attack.get("range") or attack.get("reach") or 5
    if isinstance(range_ft, str):
        # Parse "5 ft." or "30 ft."
        import re
        m = re.search(r"(\d+)", str(range_ft))
        range_ft = int(m.group(1)) if m else 5
    
    return max(1, int(range_ft) // square_size)

def is_target_in_attack_range(attacker: dict, target: dict, attack: dict) -> bool:
    """Check if target is within attack range on the grid."""
    attacker_pos = attacker.get("pos")
    target_pos = target.get("pos")
    
    if not attacker_pos or not target_pos:
        # Fall back to old band system if no grid positions
        target_band = get_position_band(target)
        return can_attack_at_band(attack, target_band)
    
    distance = get_grid_distance(attacker_pos, target_pos)
    attack_range = get_attack_range_squares(attack)
    
    return distance <= attack_range

def ai_choose_target(enemy: dict) -> tuple[int | None, dict | None]:
    """
    Choose a target for the enemy to attack.
    Prefers closest reachable target, then lowest current HP.
    Returns (target_idx, target_dict) or (None, None) if no valid targets.
    """
    party = st.session_state.get("party", [])
    if not party:
        return None, None
    
    # Filter to alive party members (HP > 0)
    alive = [(i, p) for i, p in enumerate(party) if int(p.get("hp", 0)) > 0]
    if not alive:
        return None, None
    
    enemy_pos = enemy.get("pos")
    
    if enemy_pos:
        # Sort by distance first, then HP
        def target_priority(item):
            idx, target = item
            target_pos = target.get("pos")
            distance = get_grid_distance(enemy_pos, target_pos) if target_pos else 999
            hp = int(target.get("hp", 0))
            return (distance, hp)
        
        alive.sort(key=target_priority)
    else:
        # Fall back to HP-based targeting
        random.shuffle(alive)
        alive.sort(key=lambda x: int(x[1].get("hp", 0)))
    
    return alive[0]


def estimate_attack_damage(attack: dict) -> float:
    """Estimate average damage from an attack's damage dice string."""
    dmg_str = attack.get("damage", "1d6")
    if not dmg_str:
        return 3.5  # default 1d6 average
    
    # Parse dice like "2d6+3" or "1d8+2"
    match = re.match(r"(\d+)d(\d+)(?:([+\-])(\d+))?", str(dmg_str).replace(" ", ""))
    if match:
        num_dice = int(match.group(1))
        die_size = int(match.group(2))
        modifier = 0
        if match.group(3) and match.group(4):
            modifier = int(match.group(4))
            if match.group(3) == "-":
                modifier = -modifier
        avg = num_dice * (die_size + 1) / 2 + modifier
        return avg
    return 3.5

def ai_choose_attack(enemy: dict, target: dict) -> tuple[dict | None, bool]:
    """
    Choose the best attack for the enemy to use against the target.
    Returns (attack_dict, needs_move) where needs_move indicates if enemy should move first.
    
    Logic:
    1. Evaluate ALL attacks (not just first one)
    2. Prefer in-range attacks over out-of-range
    3. Among in-range attacks, prefer highest damage
    4. If no attack in range, pick the one that would do most damage after moving
    """
    attacks = enemy.get("attacks", [])
    if not attacks:
        return None, False
    
    enemy_pos = enemy.get("pos")
    target_pos = target.get("pos")
    
    if enemy_pos and target_pos:
        distance = get_grid_distance(enemy_pos, target_pos)
        grid = st.session_state.get("grid", {})
        square_size = grid.get("square_size_ft", 5)
        distance_ft = distance * square_size
        
        # Categorize attacks by whether they're in range
        in_range_attacks = []
        out_of_range_attacks = []
        
        for atk in attacks:
            atk_range = atk.get("range", 5)
            atk_range_squares = max(1, atk_range // square_size)
            avg_damage = estimate_attack_damage(atk)
            
            if distance <= atk_range_squares:
                in_range_attacks.append((atk, avg_damage))
            else:
                out_of_range_attacks.append((atk, avg_damage, atk_range))
        
        # If we have in-range attacks, pick the highest damage one
        if in_range_attacks:
            in_range_attacks.sort(key=lambda x: x[1], reverse=True)
            best_attack = in_range_attacks[0][0]
            return best_attack, False
        
        # No in-range attacks - need to move
        # Pick the attack that would be best after moving
        # Prefer ranged attacks if target is far, melee if we can get close
        
        speed_ft = enemy.get("speed_ft", 30)
        max_move_squares = speed_ft // square_size
        
        # Can we get in melee range this turn?
        can_reach_melee = (distance - max_move_squares) <= 1
        
        best_attack = None
        best_score = -1
        
        for atk, avg_damage, atk_range in out_of_range_attacks:
            atk_range_squares = max(1, atk_range // square_size)
            
            # Can we get in range of this attack after moving?
            can_reach = (distance - max_move_squares) <= atk_range_squares
            
            # Score: prefer attacks we can reach, then by damage
            if can_reach:
                score = 1000 + avg_damage  # High base score for reachable attacks
            else:
                # Still might want ranged even if can't reach - closer is better
                score = avg_damage
            
            # Slight preference for ranged attacks when far away
            attack_type = atk.get("attack_type", "melee")
            if attack_type == "ranged" and distance > 2:
                score += 5
            
            if score > best_score:
                best_score = score
                best_attack = atk
        
        if best_attack:
            return best_attack, True
        
        # Fallback to first attack
        return attacks[0], True
    
    # Fall back to old band system (no grid positions)
    target_band = get_position_band(target)
    
    # Evaluate all attacks for band system
    in_range_attacks = []
    out_of_range_attacks = []
    
    for atk in attacks:
        avg_damage = estimate_attack_damage(atk)
        if can_attack_at_band(atk, target_band):
            in_range_attacks.append((atk, avg_damage))
        else:
            out_of_range_attacks.append((atk, avg_damage))
    
    if in_range_attacks:
        in_range_attacks.sort(key=lambda x: x[1], reverse=True)
        return in_range_attacks[0][0], False
    
    if out_of_range_attacks:
        out_of_range_attacks.sort(key=lambda x: x[1], reverse=True)
        return out_of_range_attacks[0][0], True
    
    return attacks[0], True


def ai_execute_move_closer(enemy: dict, enemy_name: str, target: dict = None) -> list[str]:
    """
    Execute a move action to get closer to target on the grid.
    Uses pathfinding to find best position within movement range.
    Returns list of log messages.
    """
    messages = []
    
    if not can_spend("move"):
        messages.append(f"{enemy_name} has no Move action available.")
        return messages
    
    enemy_pos = enemy.get("pos")
    grid = st.session_state.get("grid")
    
    # If no grid or position, fall back to band movement
    if not grid or not enemy_pos:
        success, msg = move_band(enemy, "closer")
        if success:
            spend("move")
            new_band = get_position_band(enemy)
            messages.append(f"{enemy_name} moves closer. {msg} (now at {new_band})")
        else:
            messages.append(f"{enemy_name} cannot move closer: {msg}")
        return messages
    
    # Get movement budget
    speed_ft = enemy.get("speed_ft", 30)
    square_size = grid.get("square_size_ft", 5)
    max_move = speed_ft // square_size
    
    # Find target position
    target_pos = target.get("pos") if target else None
    if not target_pos:
        # Find closest party member
        party = st.session_state.get("party", [])
        closest_dist = 999
        for p in party:
            p_pos = p.get("pos")
            if p_pos and int(p.get("hp", 0)) > 0:
                dist = get_grid_distance(enemy_pos, p_pos)
                if dist < closest_dist:
                    closest_dist = dist
                    target_pos = p_pos
    
    if not target_pos:
        messages.append(f"{enemy_name} has no target to move toward.")
        return messages
    
    # Find best position to move to (closest to target within movement range)
    start_x, start_y = enemy_pos["x"], enemy_pos["y"]
    target_x, target_y = target_pos["x"], target_pos["y"]
    
    # Get all reachable squares
    reachable = dijkstra_reachable(grid, start_x, start_y, max_move, enemy)
    
    if not reachable:
        messages.append(f"{enemy_name} cannot find a path to move.")
        return messages
    
    # Find the reachable square closest to target
    best_pos = None
    best_dist = get_grid_distance(enemy_pos, target_pos)
    
    for (rx, ry), cost in reachable.items():
        if rx == start_x and ry == start_y:
            continue  # Skip current position
        if is_cell_occupied(rx, ry, enemy):
            continue  # Skip occupied squares
        
        dist_to_target = get_grid_distance({"x": rx, "y": ry}, target_pos)
        if dist_to_target < best_dist:
            best_dist = dist_to_target
            best_pos = (rx, ry)
    
    if best_pos is None:
        messages.append(f"{enemy_name} is already as close as possible.")
        return messages
    
    # Execute the move
    old_x, old_y = start_x, start_y
    new_x, new_y = best_pos
    
    enemy["pos"] = {"x": new_x, "y": new_y}
    spend("move")
    
    distance_moved = get_grid_distance({"x": old_x, "y": old_y}, {"x": new_x, "y": new_y})
    messages.append(f"{enemy_name} moves from ({old_x},{old_y}) to ({new_x},{new_y}) [{distance_moved * square_size} ft]")
    
    return messages


def ai_execute_attack(enemy: dict, enemy_name: str, attack: dict, target_idx: int, target: dict) -> list[str]:
    """
    Execute an attack against the target.
    Returns list of log messages.
    """
    messages = []
    
    # Check action economy
    action_type = get_action_type_for_attack(attack)
    if not can_spend(action_type):
        messages.append(f"{enemy_name} has no {action_type.capitalize()} action available.")
        return messages
    
    # Validate range using grid if available
    if not is_target_in_attack_range(enemy, target, attack):
        enemy_pos = enemy.get("pos")
        target_pos = target.get("pos")
        if enemy_pos and target_pos:
            distance = get_grid_distance(enemy_pos, target_pos)
            attack_range = get_attack_range_squares(attack)
            grid = st.session_state.get("grid", {})
            square_size = grid.get("square_size_ft", 5)
            messages.append(f"{enemy_name} cannot reach {target.get('name', 'target')} with {attack.get('name', 'attack')} (distance: {distance * square_size} ft, range: {attack_range * square_size} ft).")
        else:
            # Fall back to band system
            target_band = get_position_band(target)
            max_band = get_attack_max_band(attack)
            messages.append(f"{enemy_name} cannot reach {target.get('name', 'target')} with {attack.get('name', 'attack')} (target at {target_band}, attack reaches {max_band}).")
        return messages
    
    # Spend the action
    spend(action_type)
    
    # Roll attack
    att_name = attack.get("name", "attack")
    to_hit = get_attack_to_hit(attack)
    # Use combat AC which includes Skirmish and other temporary bonuses
    target_ac = get_combat_ac(target)
    
    d20 = random.randint(1, 20)
    total = d20 + to_hit
    
    messages.append(f"{enemy_name} attacks {target.get('name', 'target')} with {att_name}!")
    messages.append(f"Attack roll: d20({d20}) + {to_hit} = **{total}** vs AC {target_ac}")
    
    # Critical miss
    if d20 == 1:
        messages.append("Critical miss (natural 1)!")
        return messages
    
    # Check hit
    if total >= target_ac:
        # Roll damage
        d_expr = get_attack_damage(attack)
        if d_expr == "—" or not d_expr:
            d_expr = "1d6"
        
        dmg_total, breakdown = roll_dice(d_expr)
        dmg_type = get_attack_damage_type(attack)
        
        # Apply damage with Avatar of War check
        before_hp, after_hp, special_msg = apply_damage_to_party_member(target, target_idx, dmg_total)
        
        hit_msg = f"**HIT!** {target.get('name', 'Target')} takes **{dmg_total}** damage ({breakdown})"
        if dmg_type:
            hit_msg += f" [{dmg_type}]"
        hit_msg += f". HP: {before_hp} → {after_hp}"
        messages.append(hit_msg)
        
        if special_msg:
            messages.append(special_msg)
        
        if after_hp == 0:
            messages.append(f"💀 {target.get('name', 'Target')} is down!")
    else:
        messages.append("**MISS!**")
    
    return messages


def ai_apply_passive_traits(enemy: dict, messages: list) -> list:
    """
    Apply passive traits that trigger at the start of a creature's turn or affect nearby creatures.
    Returns list of (target_idx, damage, damage_type) for any aura damage dealt.
    """
    aura_damage = []
    enemy_name = enemy.get("name", "Enemy")
    enemy_pos = enemy.get("pos")
    traits = enemy.get("traits", [])
    
    for trait in traits:
        trait_name = trait.get("name", "").lower() if isinstance(trait, dict) else str(trait).lower()
        trait_desc = trait.get("description", "") if isinstance(trait, dict) else str(trait)
        
        # Fire Form / Fiery Aura - damage creatures that touch or are adjacent
        if any(kw in trait_name for kw in ["fire form", "fiery", "heated body", "burning"]):
            # Find adjacent party members and deal fire damage
            if enemy_pos:
                for i, pc in enumerate(st.session_state.party):
                    pc_pos = pc.get("pos")
                    if pc_pos and get_grid_distance(enemy_pos, pc_pos) <= 1:
                        # Parse damage from trait description (e.g., "5 (1d10) fire damage")
                        dmg_match = re.search(r"(\d+)\s*\((\d+d\d+)\)", trait_desc)
                        if dmg_match:
                            avg_dmg = int(dmg_match.group(1))
                            dice_expr = dmg_match.group(2)
                            dmg, breakdown = roll_dice(dice_expr)
                            aura_damage.append((i, dmg, "fire"))
                            messages.append(f"🔥 {enemy_name}'s {trait.get('name', 'Fire Form')}: {pc.get('name', 'Target')} takes {dmg} fire damage ({breakdown})")
        
        # Cold Aura / Freezing Presence
        elif any(kw in trait_name for kw in ["cold aura", "freezing", "chill"]):
            if enemy_pos:
                for i, pc in enumerate(st.session_state.party):
                    pc_pos = pc.get("pos")
                    if pc_pos and get_grid_distance(enemy_pos, pc_pos) <= 1:
                        dmg_match = re.search(r"(\d+)\s*\((\d+d\d+)\)", trait_desc)
                        if dmg_match:
                            dice_expr = dmg_match.group(2)
                            dmg, breakdown = roll_dice(dice_expr)
                            aura_damage.append((i, dmg, "cold"))
                            messages.append(f"❄️ {enemy_name}'s {trait.get('name', 'Cold Aura')}: {pc.get('name', 'Target')} takes {dmg} cold damage ({breakdown})")
        
        # Lightning / Electric Aura
        elif any(kw in trait_name for kw in ["lightning", "electric", "shocking"]):
            if enemy_pos:
                for i, pc in enumerate(st.session_state.party):
                    pc_pos = pc.get("pos")
                    if pc_pos and get_grid_distance(enemy_pos, pc_pos) <= 1:
                        dmg_match = re.search(r"(\d+)\s*\((\d+d\d+)\)", trait_desc)
                        if dmg_match:
                            dice_expr = dmg_match.group(2)
                            dmg, breakdown = roll_dice(dice_expr)
                            aura_damage.append((i, dmg, "lightning"))
                            messages.append(f"⚡ {enemy_name}'s {trait.get('name', 'Lightning Aura')}: {pc.get('name', 'Target')} takes {dmg} lightning damage ({breakdown})")
    
    return aura_damage


def ai_check_special_abilities(enemy: dict, target: dict, distance_ft: int) -> dict | None:
    """
    Check if the enemy has special abilities (breath weapons, etc.) that should be used.
    Returns the special ability dict if one should be used, None otherwise.
    """
    actions = enemy.get("actions", [])
    
    for action in actions:
        action_name = action.get("name", "").lower()
        
        # Breath Weapon - check if recharged or available
        if "breath" in action_name:
            # Check recharge (format: "Breath Weapons (Recharge 5–6)" or similar)
            recharge_key = f"{enemy.get('name', 'Enemy')}_breath_recharge"
            if recharge_key not in st.session_state:
                st.session_state[recharge_key] = True  # Available at start
            
            if st.session_state[recharge_key]:
                # Prefer breath weapon if multiple targets in range or target has high HP
                target_hp = target.get("hp", 0)
                target_max_hp = target.get("max_hp", 1)
                if target_hp > target_max_hp * 0.5 or distance_ft <= 15:
                    return {
                        **action,
                        "is_special": True,
                        "special_type": "breath_weapon",
                        "recharge_key": recharge_key
                    }
        
        # Multiattack - flag it for multiple attack resolution
        if action_name == "multiattack":
            return {
                **action,
                "is_special": True,
                "special_type": "multiattack"
            }
    
    return None


def ai_resolve_enemy_turn() -> list[str]:
    """
    Resolve the current enemy's turn using AI-lite logic.
    Returns list of log messages.
    """
    messages = []
    
    # Get current actor
    ent = current_turn()
    if not ent or ent.get("kind") != "enemy":
        messages.append("Not an enemy's turn.")
        return messages
    
    idx = ent.get("idx")
    if idx is None or idx >= len(st.session_state.enemies):
        messages.append("Enemy not found.")
        return messages
    
    enemy = st.session_state.enemies[idx]
    enemy_name = enemy.get("name", "Enemy")
    
    enemy_pos = enemy.get("pos")
    pos_str = f" at ({enemy_pos['x']},{enemy_pos['y']})" if enemy_pos else ""
    messages.append(f"--- {enemy_name}'s Turn (AI){pos_str} ---")
    
    # Apply passive traits (fiery aura, etc.) at start of turn
    aura_damage = ai_apply_passive_traits(enemy, messages)
    for target_idx, damage, damage_type in aura_damage:
        if 0 <= target_idx < len(st.session_state.party):
            pc = st.session_state.party[target_idx]
            pc["hp"] = max(0, pc.get("hp", 0) - damage)
            if pc["hp"] == 0:
                messages.append(f"💀 {pc.get('name', 'Target')} is down from {damage_type} damage!")
    
    # Choose target
    target_idx, target = ai_choose_target(enemy)
    if target is None:
        messages.append(f"{enemy_name} has no valid targets.")
        return messages
    
    target_pos = target.get("pos")
    target_pos_str = f" at ({target_pos['x']},{target_pos['y']})" if target_pos else ""
    distance_ft = 0
    distance_str = ""
    if enemy_pos and target_pos:
        dist = get_grid_distance(enemy_pos, target_pos)
        grid = st.session_state.get("grid", {})
        sq_size = grid.get("square_size_ft", 5)
        distance_ft = dist * sq_size
        distance_str = f", distance: {distance_ft} ft"
    messages.append(f"Target: {target.get('name', 'Unknown')}{target_pos_str} (HP: {target.get('hp', '?')}{distance_str})")
    
    # Check for special abilities first (breath weapons, etc.)
    special_ability = ai_check_special_abilities(enemy, target, distance_ft)
    
    if special_ability and special_ability.get("special_type") == "breath_weapon":
        # Use breath weapon
        messages.append(f"🐉 {enemy_name} uses {special_ability.get('name', 'Breath Weapon')}!")
        
        # Parse damage from description
        desc = special_ability.get("description", "") or str(special_ability)
        dmg_match = re.search(r"(\d+d\d+(?:\s*\+\s*\d+)?)", desc)
        if dmg_match:
            dice_expr = dmg_match.group(1).replace(" ", "")
            dmg, breakdown = roll_dice(dice_expr)
            
            # Determine save type (usually DEX)
            save_type = "DEX"
            if "strength" in desc.lower():
                save_type = "STR"
            elif "constitution" in desc.lower():
                save_type = "CON"
            elif "wisdom" in desc.lower():
                save_type = "WIS"
            
            # Parse DC
            dc_match = re.search(r"DC\s*(\d+)", desc)
            save_dc = int(dc_match.group(1)) if dc_match else 13
            
            # Roll save for target
            target_mod = (target.get("abilities", {}).get(save_type, 10) - 10) // 2
            save_roll = random.randint(1, 20) + target_mod
            
            if save_roll >= save_dc:
                dmg = dmg // 2
                messages.append(f"{target.get('name', 'Target')} saves! ({save_roll} vs DC {save_dc}) - takes {dmg} damage (half)")
            else:
                messages.append(f"{target.get('name', 'Target')} fails save ({save_roll} vs DC {save_dc}) - takes {dmg} damage!")
            
            target["hp"] = max(0, target.get("hp", 0) - dmg)
            if target["hp"] == 0:
                messages.append(f"💀 {target.get('name', 'Target')} is down!")
        
        # Mark breath weapon as used (needs recharge)
        recharge_key = special_ability.get("recharge_key")
        if recharge_key:
            st.session_state[recharge_key] = False
        
        return messages
    
    # Check for Multiattack
    has_multiattack = special_ability and special_ability.get("special_type") == "multiattack"
    num_attacks = 1
    
    if has_multiattack:
        # Parse number of attacks from multiattack description
        ma_desc = special_ability.get("description", "") or str(special_ability)
        if "two" in ma_desc.lower():
            num_attacks = 2
        elif "three" in ma_desc.lower():
            num_attacks = 3
        elif "four" in ma_desc.lower():
            num_attacks = 4
        messages.append(f"🗡️ {enemy_name} uses Multiattack ({num_attacks} attacks)")
    
    # Choose attack - AI evaluates all available attacks
    attack, needs_move = ai_choose_attack(enemy, target)
    
    if attack is None:
        messages.append(f"{enemy_name} has no attacks defined.")
        return messages
    
    # Log attack choice with range info
    atk_name = attack.get("name", "attack")
    atk_range = attack.get("range", 5)
    atk_type = attack.get("attack_type", "melee")
    avg_dmg = estimate_attack_damage(attack)
    
    if needs_move:
        messages.append(f"Choosing {atk_name} ({atk_type}, range {atk_range} ft, ~{avg_dmg:.1f} avg dmg) - needs to move closer")
    else:
        messages.append(f"Choosing {atk_name} ({atk_type}, range {atk_range} ft, ~{avg_dmg:.1f} avg dmg) - in range!")
    
    # If needs move, try to move closer first
    if needs_move:
        move_msgs = ai_execute_move_closer(enemy, enemy_name, target)
        messages.extend(move_msgs)
        
        # Re-check if attack is now in range using grid
        if not is_target_in_attack_range(enemy, target, attack):
            enemy_pos = enemy.get("pos")
            target_pos = target.get("pos")
            if enemy_pos and target_pos:
                distance = get_grid_distance(enemy_pos, target_pos)
                attack_range = get_attack_range_squares(attack)
                messages.append(f"{enemy_name} is still out of range for {attack.get('name', 'attack')} (distance: {distance} squares, range: {attack_range} squares).")
            else:
                messages.append(f"{enemy_name} is still out of range for {attack.get('name', 'attack')}.")
            return messages
    
    # Execute attack(s)
    for attack_num in range(num_attacks):
        if num_attacks > 1:
            messages.append(f"--- Attack {attack_num + 1} of {num_attacks} ---")
        
        # Re-evaluate target for subsequent attacks (target might be down)
        if attack_num > 0:
            if target.get("hp", 0) <= 0:
                # Find new target
                new_target_idx, new_target = ai_choose_target(enemy)
                if new_target is None:
                    messages.append(f"{enemy_name} has no more valid targets.")
                    break
                target_idx = new_target_idx
                target = new_target
                messages.append(f"Switching target to {target.get('name', 'Unknown')}")
        
        attack_msgs = ai_execute_attack(enemy, enemy_name, attack, target_idx, target)
        messages.extend(attack_msgs)
    
    # Roll for breath weapon recharge at end of turn
    for action in enemy.get("actions", []):
        action_name = action.get("name", "").lower()
        if "breath" in action_name:
            recharge_key = f"{enemy_name}_breath_recharge"
            if recharge_key in st.session_state and not st.session_state[recharge_key]:
                # Roll for recharge (typically 5-6 on d6)
                recharge_roll = random.randint(1, 6)
                if recharge_roll >= 5:
                    st.session_state[recharge_key] = True
                    messages.append(f"🔄 {enemy_name}'s breath weapon recharges! (rolled {recharge_roll})")
                else:
                    messages.append(f"🔄 {enemy_name}'s breath weapon does not recharge (rolled {recharge_roll})")
    
    return messages

def get_current_actor():
    """
    Return (kind, idx, actor_dict) for whoever's turn it is,
    or (None, None, None) if there is no valid current actor.
    kind is "party" or "enemy".
    """
    ent = current_turn()
    if not ent:
        return None, None, None

    kind = ent.get("kind")
    idx = ent.get("idx")

    if kind == "party":
        if 0 <= idx < len(st.session_state.party):
            return kind, idx, st.session_state.party[idx]
    elif kind == "enemy":
        if 0 <= idx < len(st.session_state.enemies):
            return kind, idx, st.session_state.enemies[idx]

    return None, None, None


def parse_player_command(text: str, party: list, enemies: list) -> dict:
    """
    Very simple parser to detect high-level action type and target from free text.
    Example: 'I swing my longsword at goblin 1'
    """
    t = text.lower()

    # Detect action type
    if any(w in t for w in ["attack", "hit", "swing", "strike", "stab", "shoot", "fire at"]):
        action_type = "attack"
    elif any(w in t for w in ["grapple", "grab", "tackle"]):
        action_type = "grapple"
    elif any(w in t for w in ["jump", "leap"]):
        action_type = "jump"
    elif any(w in t for w in ["climb"]):
        action_type = "climb"
    elif any(w in t for w in ["hide", "sneak"]):
        action_type = "stealth"
    else:
        action_type = "other"

    # Try to find a target among enemies by name substring match
    target_idx = None
    target_name = None
    for i, e in enumerate(enemies):
        name = e.get("name", "")
        if not name:
            continue
        if name.lower() in t:
            target_idx = i
            target_name = name
            break

    # Weapon hint from simple keywords (can expand later)
    weapon_name = None
    for keyword in ["longsword", "sword", "bow", "dagger", "axe", "mace", "staff"]:
        if keyword in t:
            weapon_name = keyword
            break

    return {
        "type": action_type,
        "target_idx": target_idx,
        "target_name": target_name,
        "weapon_hint": weapon_name,
        "raw": text,
    }


def roll_d20() -> int:
    """Quick helper for a single d20 roll."""
    return random.randint(1, 20)


def roll_damage_expr(dice_expr: str) -> tuple[int, str]:
    """
    Uses the existing roll_dice() helper to roll a damage expression like '1d8+3'.
    Returns (total, breakdown_str).
    """
    total, breakdown = roll_dice(dice_expr)
    return total, breakdown


def get_total_attacks(actor: dict) -> int:
    """
    Get the total number of attacks a character can make with the Attack action.
    Includes Extra Attack from class features.
    """
    extra = actor.get("extra_attack", 0)
    if isinstance(extra, bool):
        extra = 1 if extra else 0
    return 1 + int(extra)


def get_attacks_remaining_this_turn() -> int:
    """Get how many attacks remain for the current Attack action."""
    ensure_action_state()
    return st.session_state.get("attacks_remaining", 0)


def set_attacks_remaining(count: int):
    """Set the number of attacks remaining."""
    ensure_action_state()
    st.session_state["attacks_remaining"] = count


def resolve_single_attack(actor: dict, target: dict, target_idx: int, chosen: dict, attack_num: int = 1, total_attacks: int = 1) -> list[str]:
    """
    Resolve a single attack roll and damage.
    Returns list of message lines.
    """
    lines = []
    
    att_name = chosen.get("name", "attack")
    to_hit = get_attack_to_hit(chosen)
    d_expr = get_attack_damage(chosen)
    if d_expr == "—":
        d_expr = "1d6"  # fallback for missing damage

    d20 = roll_d20()
    total = d20 + to_hit
    ac = get_combat_ac(target) if target in st.session_state.get("party", []) else int(target.get("ac", 10))

    attack_label = f"Attack {attack_num}/{total_attacks}" if total_attacks > 1 else "Attack"
    lines.append(f"**{attack_label}** with {att_name}: d20 ({d20}) + {to_hit} = **{total}** vs AC {ac}")

    if d20 == 1:
        lines.append("  → Critical miss (natural 1)!")
        return lines

    if total >= ac:
        dmg_total, breakdown = roll_damage_expr(d_expr)
        
        # Add Skirmish damage for Scouts who moved 10+ feet
        skirmish_dmg_dice = get_skirmish_damage_bonus(actor)
        skirmish_dmg = 0
        skirmish_breakdown = ""
        if skirmish_dmg_dice:
            # Check range for ranged attacks (Skirmish only applies within 30ft for ranged)
            attack_type = chosen.get("attack_type", "melee")
            apply_skirmish = True
            if "ranged" in attack_type.lower():
                # Check distance to target
                actor_pos = actor.get("pos")
                target_pos = target.get("pos")
                if actor_pos and target_pos:
                    grid = st.session_state.get("grid", {})
                    square_size = grid.get("square_size_ft", 5)
                    distance = get_grid_distance(actor_pos, target_pos) * square_size
                    if distance > 30:
                        apply_skirmish = False
            
            if apply_skirmish:
                skirmish_dmg, skirmish_breakdown = roll_damage_expr(skirmish_dmg_dice)
                dmg_total += skirmish_dmg
        
        # Critical hit on natural 20
        is_crit = (d20 == 20)
        if is_crit:
            # Double the dice damage (not modifiers in 3.5e, but we'll double total for simplicity)
            crit_bonus, _ = roll_damage_expr(d_expr)
            dmg_total += crit_bonus
            
            # Master of Weaponry: +1d6 on critical hits with expertise weapon
            expertise_crit = chosen.get("expertise_crit_bonus", "")
            if expertise_crit:
                expertise_crit_dmg, _ = roll_damage_expr(expertise_crit)
                dmg_total += expertise_crit_dmg
        
        # Rogue Sneak Attack
        sneak_attack_breakdown = ""
        sneak_attack_dmg = 0
        if get_sneak_attack_dice(actor) > 0:
            # Check if weapon is finesse or ranged (required for Sneak Attack)
            weapon_ability = chosen.get("ability", "STR")
            is_finesse_or_ranged = weapon_ability == "DEX" or chosen.get("range")
            
            if is_finesse_or_ranged:
                # Check Sneak Attack conditions
                # Crit gives +2 bonus (replaces advantage system)
                has_attack_bonus = (d20 == 20)
                can_sneak, sneak_reason = can_sneak_attack(actor, target, has_attack_bonus)
                
                if can_sneak:
                    dmg_total, sneak_attack_breakdown = apply_sneak_attack(actor, dmg_total)
                    sneak_attack_dmg = get_sneak_attack_dice(actor)  # For display
                    lines.append(f"  🗡️ **Sneak Attack!** ({sneak_reason})")
        
        try:
            before_hp = int(target.get("hp", 0))
            target["hp"] = max(0, before_hp - int(dmg_total))
            after_hp = target["hp"]
        except Exception:
            before_hp = "?"
            after_hp = "?"
        
        crit_text = " **CRITICAL HIT!**" if is_crit else ""
        
        # Build damage breakdown string
        damage_parts = [breakdown]
        if skirmish_dmg > 0:
            damage_parts.append(f"Skirmish {skirmish_breakdown}")
        if sneak_attack_breakdown:
            damage_parts.append(sneak_attack_breakdown)
        
        damage_breakdown = " + ".join(damage_parts)
        lines.append(f"  → **HIT!**{crit_text} {dmg_total} damage ({damage_breakdown}). HP: {before_hp} → {after_hp}")
        
        if after_hp == 0:
            lines.append(f"  💀 {target.get('name', 'Target')} is down!")
            
            # Track defeated enemy for XP
            if st.session_state.get("in_combat"):
                if "combat_defeated_enemies" not in st.session_state:
                    st.session_state.combat_defeated_enemies = []
                st.session_state.combat_defeated_enemies.append(target.copy())
            
            # Check for Relentless Assault (Barbarian 16+)
            can_assault, assault_msg = check_relentless_assault(actor, killed_enemy=True)
            if can_assault:
                lines.append(f"  {assault_msg}")
                # Grant a free attack (doesn't consume attacks_remaining)
                actor["relentless_assault_pending"] = True
    else:
        lines.append("  → Miss.")

    return lines


def resolve_attack(text: str) -> str | None:
    """
    Attempt to resolve an attack based on the current actor's stats and the text command.
    Supports Extra Attack - multiple attacks per Attack action.
    Returns a descriptive string if handled, or None if this is not an attack action.
    """
    kind, idx, actor = get_current_actor()
    if not actor:
        return None  # no active combatant (e.g., combat not started)

    info = parse_player_command(text, st.session_state.party, st.session_state.enemies)
    if info["type"] != "attack":
        return None  # not an attack; caller can fall back to other logic

    # Check if we have attacks remaining from a previous Attack action this turn
    attacks_remaining = get_attacks_remaining_this_turn()
    
    # If no attacks remaining, we need to spend a standard action to start a new Attack action
    if attacks_remaining <= 0:
        if not can_spend("standard"):
            return f"{actor.get('name','The attacker')} has already used a Standard action this turn."
        
        # Spend the action and set up attacks
        spend("standard")
        total_attacks = get_total_attacks(actor)
        set_attacks_remaining(total_attacks)
        attacks_remaining = total_attacks

    # find target
    ti = info["target_idx"]
    if ti is None or ti < 0 or ti >= len(st.session_state.enemies):
        return f"{actor.get('name','The attacker')} tries to attack, but I can't find that target among the enemies."

    target = st.session_state.enemies[ti]
    
    # Check if target is already down
    if int(target.get("hp", 0)) <= 0:
        return f"{target.get('name', 'The target')} is already down! Choose another target."

    # pick an attack from actor
    attacks = actor.get("attacks", [])
    if not attacks:
        return f"{actor.get('name','The attacker')} has no attacks defined."

    chosen = None
    if info["weapon_hint"]:
        for a in attacks:
            if info["weapon_hint"] in a.get("name", "").lower():
                chosen = a
                break
    if not chosen:
        # default to the primary / first attack
        idx_attack = actor.get("default_attack_index", 0)
        if 0 <= idx_attack < len(attacks):
            chosen = attacks[idx_attack]
        else:
            chosen = attacks[0]

    # Validate range band
    target_band = get_position_band(target)
    if not can_attack_at_band(chosen, target_band):
        max_band = get_attack_max_band(chosen)
        return (f"{actor.get('name','The attacker')} cannot attack {target.get('name','the target')} with {chosen.get('name','that attack')}! "
                f"Target is at **{target_band}** range, but this attack only reaches **{max_band}** range. "
                f"Use a Move action to get closer, or choose a different attack.")

    # Calculate attack number
    total_attacks = get_total_attacks(actor)
    attack_num = total_attacks - attacks_remaining + 1
    
    lines = []
    
    # Header for first attack
    if attack_num == 1:
        lines.append(f"**{actor.get('name','The attacker')}** takes the Attack action against **{target.get('name','the target')}**!")
        if total_attacks > 1:
            lines.append(f"*(Extra Attack: {total_attacks} attacks this action)*")
    
    # Resolve this attack
    attack_lines = resolve_single_attack(actor, target, ti, chosen, attack_num, total_attacks)
    lines.extend(attack_lines)
    
    # Decrement attacks remaining
    attacks_remaining -= 1
    set_attacks_remaining(attacks_remaining)
    
    # Notify about remaining attacks
    if attacks_remaining > 0:
        lines.append(f"")
        lines.append(f"*{attacks_remaining} attack(s) remaining. Type another attack command to continue.*")

    return "\n".join(lines)

# ---- Hybrid system skill list + ability mapping ----
SKILL_NAMES = [
    "Acrobatics",
    "Animal Handling",
    "Arcana",
    "Athletics",
    "Deception",
    "History",
    "Insight",
    "Intimidation",
    "Medicine",
    "Nature",
    "Perception",
    "Performance",
    "Persuasion",
    "Religion",
    "Sleight of Hand",
    "Stealth",
    "Survival",
    "Tinker",
    "Honor",
    "Tactics",
]

SKILL_TO_ABILITY: dict[str, str] = {
    "Acrobatics": "DEX",
    "Animal Handling": "WIS",
    "Arcana": "INT",
    "Athletics": "STR",
    "Deception": "CHA",
    "History": "INT",
    "Insight": "WIS",
    "Intimidation": "CHA",
    "Medicine": "WIS",
    "Nature": "INT",
    "Perception": "WIS",
    "Performance": "CHA",
    "Persuasion": "CHA",
    "Religion": "INT",
    "Sleight of Hand": "DEX",
    "Stealth": "DEX",
    "Survival": "WIS",
    "Tinker": "INT",
    "Honor": "CHA",
    "Tactics": "INT",
}

def _get_skill_mod(actor: dict, skill_name: str) -> int:
    """
    Compute the modifier for a given skill using the actor's abilities,
    explicit skill bonuses when present, and proficiency.
    """
    # quick mapping; we can extend this later once we have a full skill JSON

    abilities = actor.get("abilities", {})

    prof_bonus = int(actor.get("proficiency_bonus", 2))

    # if actor already has an explicit skill bonus, prefer that
    skills_blob = actor.get("skills", {})
    if isinstance(skills_blob, dict) and skill_name in skills_blob:
        try:
            return int(skills_blob[skill_name])
        except Exception:
            pass  # fall back to ability+prof below

    abil_key = SKILL_TO_ABILITY.get(skill_name)
    base = _ability_mod(abilities.get(abil_key, 10)) if abil_key else 0

    # see if they are proficient in that skill
    profs = actor.get("profs", {})
    prof_skills = []
    if isinstance(profs, dict):
        ps = profs.get("skills", [])
        if isinstance(ps, dict):
            prof_skills = list(ps.keys())
        elif isinstance(ps, list):
            prof_skills = ps

    if skill_name in prof_skills:
        return base + prof_bonus
    return base

def find_actor_from_message(msg: str):
    """Return (kind, index, blob) where kind is 'party' or 'enemy'."""
    low = msg.lower()

    # search enemies first if name is in text
    for idx, e in enumerate(st.session_state.get("enemies", [])):
        nm = str(e.get("name", "")).lower()
        if nm and nm in low:
            return "enemy", idx, e

    # then party
    for idx, c in enumerate(st.session_state.get("party", [])):
        nm = str(c.get("name", "")).lower()
        if nm and nm in low:
            return "party", idx, c

    # fall back to active turn entity
    ent = current_turn()
    if ent:
        if ent.get("kind") == "party":
            idx = ent.get("idx", 0)
            if 0 <= idx < len(st.session_state.get("party", [])):
                return "party", idx, st.session_state.party[idx]
        elif ent.get("kind") == "enemy":
            idx = ent.get("idx", 0)
            if 0 <= idx < len(st.session_state.get("enemies", [])):
                return "enemy", idx, st.session_state.enemies[idx]

    # final fallback: first party member
    if st.session_state.get("party"):
        return "party", 0, st.session_state.party[0]

    return None, None, None

def resolve_move_action(text: str) -> str | None:
    """
    Consume Move action when the current actor declares movement in chat.
    Supports range band movement: "move closer", "move away", "engage", "disengage"
    """
    kind, idx, actor = get_current_actor()
    if not actor:
        return None

    intent, ent = detect_intent(text)
    if intent != "move":
        return None

    # Enforce action economy using helpers
    if not can_spend("move"):
        return f"{actor.get('name','The character')} has already used a Move action this turn."

    # Determine movement direction from text
    t = text.lower()
    direction = None
    
    if any(word in t for word in ["closer", "advance", "engage", "close", "approach", "charge"]):
        direction = "closer"
    elif any(word in t for word in ["away", "retreat", "back", "disengage", "withdraw", "flee"]):
        direction = "away"
    
    actor_name = actor.get('name', 'The character')
    current_band = get_position_band(actor)
    
    if direction:
        # Attempt to move one band
        success, msg = move_band(actor, direction)
        if success:
            spend("move")
            new_band = get_position_band(actor)
            return f"{actor_name} uses a Move action: {msg} (now at **{get_band_display(new_band)}**)"
        else:
            # Don't spend the action if movement failed
            return f"{actor_name} cannot move: {msg}"
    else:
        # Generic movement without band change
        spend("move")
        where = ent.get("where") or "a new position"
        return f"{actor_name} uses a Move action to move to **{where}** (remains at **{get_band_display(current_band)}**)."

def resolve_skill_check(text: str) -> str | None:
    """
    Parse a chat message for a skill name and roll a skill check
    for the appropriate actor (PC or enemy). Consumes a Standard
    action for that actor's turn.
    """
    msg = text.strip()
    lower = msg.lower()

    # 1) detect which skill we're rolling
    skill = None
    for sk in SKILL_NAMES:
        if sk.lower() in lower:
            skill = sk
            break
    if not skill:
        return None  # not a skill check request

    # reminder: only the active combatant can roll during combat
    kind, idx, actor = get_current_actor()
    if not actor:
        return "No valid creature found to make that check."

    # 3) enforce Standard action economy using helpers
    if not can_spend("standard"):
        return f"{actor.get('name','The character')} has already used a Standard action this turn."

    # 4) choose a DC band (very rough heuristic for now)
    DC_BANDS = {
        "very_easy": 5,
        "easy": 10,
        "medium": 15,
        "hard": 20,
        "very_hard": 25,
        "nearly_impossible": 30,
    }
    base_dc = DC_BANDS["medium"]
    dc_jitter = random.choice([-2, 0, 0, 2])
    dc = max(5, base_dc + dc_jitter)

    # 5) compute modifier and roll
    mod = _get_skill_mod(actor, skill)
    d20 = roll_d20()
    total = d20 + mod

    # spend the Standard action
    spend("standard")

    actor_name = actor.get("name", "The character")
    lines = []
    lines.append(f"{actor_name} attempts a **{skill}** check (DC {dc}).")
    lines.append(f"Roll: d20 ({d20}) + {mod} = **{total}**.")

    if total >= dc:
        lines.append("Result: **Success**.")
    else:
        lines.append("Result: **Failure**.")

    return "\n".join(lines)

# ==== SRD mini-loaders for Builder (accept .json or .txt) ====
# These use the cached JSON loader for performance.

def _load_json_from_candidates(dir_path, names):
    """Load JSON from first existing file in candidates. Uses caching."""
    for nm in names:
        p = os.path.join(dir_path, nm)
        if os.path.exists(p):
            data, _ = _cached_load_json(p)
            if data is not None:
                return data, p
                return [], p
    return [], None

def load_srd_races():
    with perf_timer("load_srd_races"):
        if "srd_races" in st.session_state:
            return st.session_state["srd_races"]
        data, p = _load_json_from_candidates(DATA_DIR, ["SRD_Races.json", "SRD_Races.txt"])
        st.session_state["srd_races_path"] = p
        result = data if isinstance(data, list) else []
        st.session_state["srd_races"] = result
        return result

def load_srd_backgrounds():
    with perf_timer("load_srd_backgrounds"):
        if "srd_backgrounds" in st.session_state:
            return st.session_state["srd_backgrounds"]
        data, p = _load_json_from_candidates(DATA_DIR, ["SRD_Backgrounds.json", "SRD_Backgrounds.txt"])
        st.session_state["srd_backgrounds_path"] = p
        result = data if isinstance(data, list) else []
        st.session_state["srd_backgrounds"] = result
        return result

def load_srd_classes():
    with perf_timer("load_srd_classes"):
        if "srd_classes" in st.session_state:
            return st.session_state["srd_classes"]
        data, p = _load_json_from_candidates(DATA_DIR, ["SRD_Classes.json", "SRD_Classes.txt"])
        st.session_state["srd_classes_path"] = p
        
        if isinstance(data, dict) and "classes" in data:
            data = data["classes"]

        result = data if isinstance(data, list) else []
        st.session_state["srd_classes"] = result
        return result

def load_srd_feats():
    with perf_timer("load_srd_feats"):
        if "srd_feats" in st.session_state:
            return st.session_state["srd_feats"]
        data, p = _load_json_from_candidates(DATA_DIR, ["SRD_Feats.json", "SRD_Feats.txt"])
        st.session_state["srd_feats_path"] = p
        result = data if isinstance(data, list) else []
        st.session_state["srd_feats"] = result
        return result

def load_srd_equipment():
    with perf_timer("load_srd_equipment"):
        if "srd_equipment" in st.session_state:
            return st.session_state["srd_equipment"]
        data, p = _load_json_from_candidates(DATA_DIR, ["SRD_Equipment.json", "SRD_Equipment.txt"])
        st.session_state["srd_equipment_path"] = p

        if isinstance(data, list):
            st.session_state["srd_equipment"] = data
            return data
        else:
            st.session_state["srd_equipment"] = []
            return []

def load_srd_skills():
    """Load skills from SRD_Skills.json."""
    with perf_timer("load_srd_skills"):
        if "srd_skills" in st.session_state:
            return st.session_state["srd_skills"]
        data, p = _load_json_from_candidates(DATA_DIR, ["SRD_Skills.json", "SRD_Skills.txt"])
        st.session_state["srd_skills_path"] = p
        result = data if isinstance(data, list) else []
        st.session_state["srd_skills"] = result
        return result
    
# ==== Character Builder ====

def _ability_mod(score: int) -> int:
    try:
        return (int(score) - 10) // 2
    except:
        return 0


def get_effective_ability_score(char: dict, ability: str) -> int:
    """
    Get the effective ability score including all bonuses like Primal Champion.
    """
    base_score = int(char.get("abilities", {}).get(ability.upper(), 10))
    
    # Primal Champion (Barbarian 20): +4 STR and CON
    if ability.upper() == "STR":
        base_score += get_primal_champion_bonus(char, "STR")
    elif ability.upper() == "CON":
        base_score += get_primal_champion_bonus(char, "CON")
    
    return base_score


def get_effective_ability_mod(char: dict, ability: str) -> int:
    """
    Get the effective ability modifier including all bonuses.
    """
    return _ability_mod(get_effective_ability_score(char, ability))


def get_total_save(char: dict, save_stat: str) -> int:
    """
    Calculate total saving throw bonus for a stat.
    Total = ability modifier + class save bonus + rage bonus (if applicable)
    """
    # Use effective ability score (includes Primal Champion bonus)
    ability_mod = get_effective_ability_mod(char, save_stat)
    
    save_bonuses = char.get("save_bonuses", {})
    class_bonus = save_bonuses.get(save_stat, 0)
    
    # Barbarian Rage bonus to STR, CON, WIS saves
    rage_bonus = get_rage_save_bonus(char, save_stat)
    
    return ability_mod + class_bonus + rage_bonus


def format_save_display(char: dict) -> str:
    """Format saves for display, highlighting primary saves."""
    primary = char.get("primary_saves", [])
    parts = []
    for stat in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]:
        total = get_total_save(char, stat)
        sign = "+" if total >= 0 else ""
        if stat in primary:
            parts.append(f"**{stat}** {sign}{total}")
        else:
            parts.append(f"{stat} {sign}{total}")
    return " | ".join(parts)
    
def roll_ability_scores_4d6_drop_lowest():
    """Roll 4d6 drop lowest, six times. Returns a list of six scores."""
    scores = []
    for _ in range(6):
        dice = sorted([random.randint(1, 6) for _ in range(4)])
        # drop the lowest die, sum the highest three
        scores.append(sum(dice[1:]))
    return scores

def compute_hp_level1(char: dict, class_blob: dict) -> int:
    # reminder: some class JSON uses strings like "d6 per Bard level" — extract the number safely.
    raw = class_blob.get("hit_die", 8)
    if isinstance(raw, int):
        hit_die = raw
    else:
        m = re.search(r"(\d+)", str(raw))
        hit_die = int(m.group(1)) if m else 8  # fallback d8

    con_mod = _ability_mod(char.get("abilities", {}).get("CON", 10))
    return max(1, hit_die + con_mod)

def compute_ac_from_equipment(char: dict, include_combat_bonuses: bool = False) -> int:
    """
    Calculate AC from equipped armor using SRD armor data.
    
    Armor categories:
    - Light: base + full DEX mod
    - Medium: base + DEX mod (max +2)
    - Heavy: base only (no DEX)
    - Shield: +2 bonus
    
    If include_combat_bonuses is True, also includes temporary combat bonuses
    like Skirmish AC bonus for Scouts.
    """
    equipment_names = [x.lower() for x in (char.get("equipment") or []) if isinstance(x, str)]
    dex_mod = _ability_mod(char.get("abilities", {}).get("DEX", 10))
    
    # Default: unarmored (10 + DEX)
    base_ac = 10
    dex_bonus = dex_mod
    shield_bonus = 0
    
    # Look up armor in SRD data
    srd_equipment = st.session_state.get("srd_equipment") or []
    
    for eq_name in equipment_names:
        # Find matching equipment in SRD
        for item in srd_equipment:
            item_name = (item.get("name") or "").lower()
            if item_name == eq_name or eq_name in item_name or item_name in eq_name:
                eq_cat = item.get("equipment_category", "")
                
                if eq_cat == "Armor":
                    armor_class = item.get("armor_class", {})
                    armor_cat = item.get("armor_category", "")
                    
                    if armor_cat == "Shield":
                        # Shield adds +2
                        shield_bonus = armor_class.get("base", 2)
                    else:
                        # Regular armor
                        base_ac = armor_class.get("base", 10)
                        allows_dex = armor_class.get("dex_bonus", True)
                        max_dex = armor_class.get("max_bonus")
                        
                        if not allows_dex:
                            # Heavy armor - no DEX bonus
                            dex_bonus = 0
                        elif max_dex is not None:
                            # Medium armor - DEX capped at max_bonus
                            dex_bonus = min(dex_mod, max_dex)
                        else:
                            # Light armor - full DEX
                            dex_bonus = dex_mod
                    break
        
        # Also check for "shield" keyword even if not in SRD lookup
        if "shield" in eq_name and shield_bonus == 0:
            shield_bonus = 2
    
    total_ac = base_ac + dex_bonus + shield_bonus
    
    # Add combat bonuses if requested (Skirmish, Daisho, etc.)
    if include_combat_bonuses:
        # Scout Skirmish AC bonus (requires moving 10+ ft, light armor only)
        skirmish_ac = get_skirmish_ac_bonus(char)
        if skirmish_ac > 0:
            # Skirmish only works in light armor - check armor category
            armor_is_light = True  # Default to light if no armor
            for eq_name in equipment_names:
                for item in srd_equipment:
                    item_name = (item.get("name") or "").lower()
                    if item_name == eq_name or eq_name in item_name or item_name in eq_name:
                        armor_cat = item.get("armor_category", "")
                        if armor_cat in ("Medium", "Heavy"):
                            armor_is_light = False
                            break
            if armor_is_light:
                total_ac += skirmish_ac
        
        # Samurai Daisho bonus (+1 AC when wielding katana and wakizashi)
        if char.get("class") == "Samurai":
            weapons = [w.get("name", "").lower() for w in char.get("attacks", [])]
            has_katana = any("katana" in w or "bastard" in w for w in weapons)
            has_wakizashi = any("wakizashi" in w or "short sword" in w for w in weapons)
            if has_katana and has_wakizashi:
                total_ac += char.get("daisho_ac_bonus", 1)
    
    return total_ac


def get_combat_ac(char: dict) -> int:
    """
    Get the character's current AC including all combat bonuses.
    Use this during combat for accurate AC calculation.
    """
    base_ac = char.get("ac", 10)
    combat_bonus = 0
    
    # Scout Skirmish AC bonus
    skirmish_ac = get_skirmish_ac_bonus(char)
    if skirmish_ac > 0:
        # Check for light armor restriction
        equipment_names = [x.lower() for x in (char.get("equipment") or []) if isinstance(x, str)]
        srd_equipment = st.session_state.get("srd_equipment") or []
        armor_is_light = True
        for eq_name in equipment_names:
            for item in srd_equipment:
                item_name = (item.get("name") or "").lower()
                if item_name == eq_name or eq_name in item_name or item_name in eq_name:
                    armor_cat = item.get("armor_category", "")
                    if armor_cat in ("Medium", "Heavy"):
                        armor_is_light = False
                        break
        if armor_is_light:
            combat_bonus += skirmish_ac
    
    # Samurai Daisho bonus
    if char.get("class") == "Samurai":
        weapons = [w.get("name", "").lower() for w in char.get("attacks", [])]
        has_katana = any("katana" in w or "bastard" in w for w in weapons)
        has_wakizashi = any("wakizashi" in w or "short sword" in w for w in weapons)
        if has_katana and has_wakizashi:
            combat_bonus += char.get("daisho_ac_bonus", 1)
    
    # Barbarian Rage AC penalty (-2)
    if is_raging(char):
        combat_bonus += get_rage_ac_penalty(char)  # Returns -2
    
    return base_ac + combat_bonus

WEAPON_ABILITY_DEFAULT = {
    "melee": "STR",
    "ranged": "DEX"
}

def _find_equipment_by_name(name: str) -> dict | None:
    """
    Look up an equipment item by name from the loaded SRD equipment.
    """
    eq_list = st.session_state.get("srd_equipment") or []
    name_lower = (name or "").lower()
    for item in eq_list:
        if (item.get("name") or "").lower() == name_lower:
            return item
    return None

def _is_weapon_item(item: dict) -> bool:
    """
    Basic check if an equipment item is a weapon.
    Adjust this if your SRD_Equipment format differs.
    """
    if not isinstance(item, dict):
        return False
    cat = (item.get("equipment_category") or "").lower()
    wcat = (item.get("weapon_category") or "").lower()
    return "weapon" in cat or bool(wcat)

def _choose_weapon_ability(char: dict, weapon: dict) -> str:
    """
    Decide whether this weapon should use STR or DEX.
    If it has finesse or is ranged, prefer DEX; otherwise STR.
    """
    props = [ (p.get("name") or "").lower() if isinstance(p, dict) else str(p).lower()
              for p in (weapon.get("properties") or []) ]
    rng = (weapon.get("weapon_range") or "").lower()

    if "finesse" in props or "ranged" in rng:
        return "DEX"
    return "STR"

def build_attack_from_weapon(char: dict, weapon: dict) -> dict:
    """
    Build a simple attack dict from a weapon and character stats.
    Uses BAB (Base Attack Bonus) for attack rolls.
    """
    name = weapon.get("name", "Weapon")
    ability_key = _choose_weapon_ability(char, weapon)

    abilities = char.get("abilities") or {}
    ability_score = int(abilities.get(ability_key, 10))
    ability_bonus = _ability_mod(ability_score)

    # Use BAB instead of proficiency bonus
    bab = int(char.get("bab", 0))
    
    # Check weapon proficiency - if not proficient, -4 penalty (3.5e style)
    profs = (char.get("profs") or {}).get("weapons") or []
    wcat = (weapon.get("weapon_category") or "").lower()
    wname = name.lower()
    
    # Check if proficient with this weapon type or specific weapon
    is_proficient = False
    for p in profs:
        p_lower = p.lower()
        if p_lower in wcat or p_lower in wname or wcat in p_lower:
            is_proficient = True
            break
        # Handle "simple weapons" and "martial weapons"
        if "simple" in p_lower and "simple" in wcat:
            is_proficient = True
            break
        if "martial" in p_lower and "martial" in wcat:
            is_proficient = True
            break

    # BAB + ability mod, -4 if not proficient
    nonprof_penalty = 0 if is_proficient else -4
    to_hit = bab + ability_bonus + nonprof_penalty
    
    # Avatar of War attack bonus (Fighter 18+)
    avatar_bonus = char.get("avatar_of_war_attack_bonus", 0)
    if avatar_bonus > 0:
        # Check if the bonus has expired
        current_round = st.session_state.get("combat_round", 1)
        expires_round = char.get("avatar_of_war_expires_round", 0)
        if current_round <= expires_round:
            to_hit += avatar_bonus
        else:
            # Clear the expired bonus
            char["avatar_of_war_attack_bonus"] = 0
            char["avatar_of_war_expires_round"] = 0

    dmg = weapon.get("damage") or {}
    
    # Handle both formats: "damage_dice": "1d8" OR "dice_count": 1, "dice_value": 8
    damage_dice = dmg.get("damage_dice", "")
    if damage_dice:
        # Parse "1d8" format
        import re
        dice_match = re.match(r"(\d+)d(\d+)", damage_dice)
        if dice_match:
            dice_count = int(dice_match.group(1))
            dice_value = int(dice_match.group(2))
        else:
            dice_count = 1
            dice_value = 6
    else:
        dice_count = int(dmg.get("dice_count", 1))
        dice_value = int(dmg.get("dice_value", 6))
    
    # Get damage type - handle nested dict or string
    damage_type_data = dmg.get("damage_type", {})
    if isinstance(damage_type_data, dict):
        damage_type = damage_type_data.get("name", "bludgeoning")
    else:
        damage_type = str(damage_type_data) if damage_type_data else "bludgeoning"

    # simple "XdY+mod" string
    dmg_str = f"{dice_count}d{dice_value}"
    if ability_bonus != 0:
        sign = "+" if ability_bonus > 0 else "-"
        dmg_str += f"{sign}{abs(ability_bonus)}"

    # Determine reach/range based on weapon properties
    weapon_range = weapon.get("weapon_range", "").lower()
    properties = weapon.get("properties") or []
    property_names = [p.get("name", "").lower() if isinstance(p, dict) else str(p).lower() for p in properties]
    
    # Check if it's a ranged weapon
    is_ranged = weapon_range == "ranged" or "ranged" in wcat
    is_thrown = "thrown" in property_names
    has_reach = "reach" in property_names
    
    # Apply Weapon Expertise bonuses (Fighter level 6+)
    expertise_bonus = char.get("weapon_expertise_bonus", {})
    expertise_weapon = expertise_bonus.get("weapon", "").lower()
    has_expertise = expertise_weapon and expertise_weapon in name.lower()
    
    expertise_to_hit = 0
    expertise_damage = 0
    expertise_crit = ""
    expertise_reroll_ones = False
    
    if has_expertise:
        expertise_to_hit = expertise_bonus.get("attack_bonus", 0)
        expertise_damage = expertise_bonus.get("damage_bonus", 0)
        expertise_crit = expertise_bonus.get("crit_bonus", "")
        expertise_reroll_ones = expertise_bonus.get("reroll_ones", False)
        to_hit += expertise_to_hit
        
        # Add damage bonus to damage string
        if expertise_damage > 0:
            if "+" in dmg_str or "-" in dmg_str:
                # Parse existing modifier and add to it
                dmg_str = dmg_str.rstrip()
                if "+" in dmg_str:
                    base, mod = dmg_str.rsplit("+", 1)
                    new_mod = int(mod) + expertise_damage
                    dmg_str = f"{base}+{new_mod}"
                elif "-" in dmg_str:
                    base, mod = dmg_str.rsplit("-", 1)
                    new_mod = -int(mod) + expertise_damage
                    if new_mod >= 0:
                        dmg_str = f"{base}+{new_mod}"
                    else:
                        dmg_str = f"{base}{new_mod}"
            else:
                dmg_str = f"{dmg_str}+{expertise_damage}"
    
    # Barbarian Rage melee damage bonus
    rage_dmg_bonus = 0
    if is_raging(char) and not is_ranged:
        # Rage bonus only applies to melee attacks using Strength
        if ability_key == "STR":
            rage_dmg_bonus = get_rage_attack_bonus(char)
            if rage_dmg_bonus > 0:
                if "+" in dmg_str or "-" in dmg_str:
                    if "+" in dmg_str:
                        base, mod = dmg_str.rsplit("+", 1)
                        new_mod = int(mod) + rage_dmg_bonus
                        dmg_str = f"{base}+{new_mod}"
                    elif "-" in dmg_str:
                        base, mod = dmg_str.rsplit("-", 1)
                        new_mod = -int(mod) + rage_dmg_bonus
                        if new_mod >= 0:
                            dmg_str = f"{base}+{new_mod}"
                        else:
                            dmg_str = f"{base}{new_mod}"
                else:
                    dmg_str = f"{dmg_str}+{rage_dmg_bonus}"
    
    attack_dict = {
        "name": name,
        "ability": ability_key,
        "to_hit": to_hit,
        "damage": dmg_str,
        "damage_type": damage_type.lower(),
        "source": "weapon",
        "has_expertise": has_expertise,
        "expertise_crit_bonus": expertise_crit if has_expertise else "",
        "expertise_reroll_ones": expertise_reroll_ones,
        "rage_damage_bonus": rage_dmg_bonus  # Track for display
    }
    
    if is_ranged:
        # Get range from weapon data or default
        range_data = weapon.get("range") or {}
        if isinstance(range_data, dict):
            normal_range = range_data.get("normal", 80)
        else:
            normal_range = 80
        attack_dict["range"] = normal_range
    elif is_thrown:
        # Thrown weapons can be used in melee or ranged
        # SRD uses "throw_range" for thrown weapons
        throw_data = weapon.get("throw_range") or weapon.get("range") or {}
        if isinstance(throw_data, dict):
            normal_range = throw_data.get("normal", 20)
        else:
            normal_range = 20
        attack_dict["reach"] = 5  # Can still melee
        attack_dict["range"] = normal_range  # Or throw
    else:
        # Melee weapon - default 5ft reach, or 10ft if has Reach property
        attack_dict["reach"] = 10 if has_reach else 5
    
    return attack_dict

def refresh_attacks_from_equipment(char: dict):
    """
    Rebuild char['attacks'] from weapon-type equipment items.
    Keeps any non-weapon attacks if you already added them elsewhere.
    """
    eq_names = char.get("equipment") or []
    if isinstance(eq_names, str):
        eq_names = [eq_names]

    # keep non-weapon attacks so we don't wipe things like natural claws, spells-as-attacks, etc.
    existing = char.get("attacks") or []
    non_weapon_attacks = [a for a in existing if a.get("source") != "weapon"]

    weapon_attacks: list[dict] = []
    for ename in eq_names:
        item = _find_equipment_by_name(ename)
        if not item or not _is_weapon_item(item):
            continue
        weapon_attacks.append(build_attack_from_weapon(char, item))

    char["attacks"] = non_weapon_attacks + weapon_attacks

def set_default_attack_from_kit(char: dict, kit: dict|None):
    if not kit:
        return
    attacks_in = kit.get("attacks", [])
    norm = []
    for a in attacks_in:
        nm = a.get("name", "Attack")
        to_hit = a.get("to_hit")
        if isinstance(to_hit, str) and to_hit.startswith("+") and to_hit[1:].isdigit():
            to_hit = int(to_hit)
        if not isinstance(to_hit, int):
            # fallback: BAB + STR for martial by default
            to_hit = _ability_mod(char.get("abilities", {}).get("STR", 10)) + int(char.get("bab", 0))
        dmg = a.get("damage", "1d6")
        norm.append({"name": nm, "to_hit": int(to_hit), "damage": dmg, "reach": a.get("reach"), "range": a.get("range")})
    if norm:
        char["attacks"] = norm
        char["default_attack_index"] = 0  # reminder: used by auto-actions later

def sync_attacks_from_equipment(char: dict):
    """
    Look at char['equipment'], cross-reference against the loaded SRD equipment,
    and add weapon attacks into char['attacks'].

    This assumes st.session_state['srd_equipment'] is a list of items loaded
    from SRD_Equipment.json at startup.
    """
    eq_names = char.get("equipment") or []
    if isinstance(eq_names, str):
        eq_names = [eq_names]

    equip_db = st.session_state.get("srd_equipment") or []

    # Keep existing non-weapon attacks (natural attacks, spells, etc.)
    existing = char.get("attacks") or []
    non_weapon_attacks = [a for a in existing if a.get("source") != "weapon"]

    weapon_attacks = []

    # small helper for ability mod
    def _mod(score: int) -> int:
        return (int(score) - 10) // 2

    for eq_name in eq_names:
        name_lower = str(eq_name).strip().lower()
        item = None

        # FIRST: try exact match
        for e in equip_db:
            if str(e.get("name", "")).strip().lower() == name_lower:
                item = e
                break

        # SECOND: try contains-match (covers “long sword” → “Longsword”)
        if not item:
            for e in equip_db:
                if name_lower.replace(" ", "") in str(e.get("name", "")).replace(" ", "").lower():
                    item = e
                    break

        if not item:
            continue

        # detect if it's a weapon
        cat = str(item.get("equipment_category", "")).lower()
        wcat = str(item.get("weapon_category", "")).lower()
        if "weapon" not in cat and not wcat:
            continue  # not a weapon, skip

        # decide STR or DEX (simple finesse/ranged heuristic)
        props = []
        for p in (item.get("properties") or []):
            if isinstance(p, dict):
                props.append(str(p.get("name", "")).lower())
            else:
                props.append(str(p).lower())
        rng = str(item.get("weapon_range", "")).lower()

        if "finesse" in props or "ranged" in rng:
            ability_key = "DEX"
        else:
            ability_key = "STR"

        abilities = char.get("abilities") or {}
        ability_score = int(abilities.get(ability_key, 10))
        ability_bonus = _mod(ability_score)

        # Use BAB (Base Attack Bonus) instead of proficiency bonus
        bab = int(char.get("bab", 0))
        
        # Check weapon proficiency - if not proficient, -4 penalty (3.5e style)
        profs = (char.get("profs") or {}).get("weapons") or []
        weapon_prof = False
        if wcat:
            wcat_lower = wcat.lower()
            for p in profs:
                p_lower = str(p).lower()
                if p_lower in wcat_lower or wcat_lower in p_lower:
                    weapon_prof = True
                    break
                # Handle "simple weapons" and "martial weapons"
                if "simple" in p_lower and "simple" in wcat_lower:
                    weapon_prof = True
                    break
                if "martial" in p_lower and "martial" in wcat_lower:
                    weapon_prof = True
                    break

        # BAB + ability mod, -4 if not proficient
        nonprof_penalty = 0 if weapon_prof else -4
        to_hit = bab + ability_bonus + nonprof_penalty

        dmg = item.get("damage") or {}
        dice_count = int(dmg.get("dice_count", 1))
        dice_value = int(dmg.get("dice_value", 6))
        dtype = ""
        dt_field = dmg.get("damage_type")
        if isinstance(dt_field, dict):
            dtype = dt_field.get("name") or ""
        elif isinstance(dt_field, str):
            dtype = dt_field
        if not dtype:
            dtype = "bludgeoning"

        dmg_str = f"{dice_count}d{dice_value}"
        if ability_bonus != 0:
            sign = "+" if ability_bonus > 0 else "-"
            dmg_str += f"{sign}{abs(ability_bonus)}"

        weapon_attacks.append({
            "name": item.get("name", "Weapon"),
            "ability": ability_key,
            "to_hit": to_hit,
            "damage": dmg_str,
            "damage_type": dtype.lower(),
            "source": "weapon"
        })

    char["attacks"] = non_weapon_attacks + weapon_attacks

def apply_race(char: dict, race: dict):
    """
    Apply a race to a character, including:
    - Ability bonuses
    - Speed
    - Size
    - Darkvision
    - Languages
    - Proficiencies (skills, weapons, armor, tools)
    - Damage/condition resistances
    - Traits/features
    """
    char["race"] = race.get("name", "")

    # --- Ensure abilities exist ---
    if "abilities" not in char or not isinstance(char["abilities"], dict):
        char["abilities"] = {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10}

    # --- Ability bonuses: handle both dict and 5e-API-style list ---
    ab = race.get("ability_bonuses") or {}
    if isinstance(ab, list):
        # 5e API style:
        # "ability_bonuses": [{"name":"CON","bonus":2}, ...]
        for entry in ab:
            if not isinstance(entry, dict):
                continue
            key = entry.get("name")
            # sometimes nested: {"ability_score":{"name":"CON"}, "bonus":2}
            if not key and isinstance(entry.get("ability_score"), dict):
                key = entry["ability_score"].get("name")
            bonus = entry.get("bonus", 0)
            if key in char["abilities"]:
                char["abilities"][key] = int(char["abilities"][key]) + int(bonus)
    elif isinstance(ab, dict):
        #  Older "simple dict" format
        for k, v in ab.items():
            if k in char["abilities"]:
                char["abilities"][k] = int(char["abilities"][k]) + int(v)

    # --- Speed: API uses an int (e.g., 30) ---
    spd = race.get("speed")
    if isinstance(spd, int):
        char["speed"] = f"{spd} ft."
    elif isinstance(spd, str) and spd:
        char["speed"] = spd

    # --- Size ---
    size = race.get("size")
    if size:
        char["size"] = size

    # --- Darkvision ---
    darkvision = race.get("darkvision", 0)
    if darkvision > 0:
        char["darkvision"] = darkvision
    # Also check traits for darkvision
    for t in (race.get("traits") or []):
        if isinstance(t, dict):
            if t.get("darkvision_range"):
                char["darkvision"] = max(char.get("darkvision", 0), t["darkvision_range"])

    # --- Languages: API uses list of dicts with "name" ---
    langs_field = race.get("languages") or []
    new_langs = set()
    for l in langs_field:
        if isinstance(l, dict):
            name = l.get("name")
        else:
            name = str(l)
        if name:
            new_langs.add(name)

    existing_langs = set()
    if isinstance(char.get("languages"), str) and char["languages"]:
        existing_langs |= {part.strip() for part in char["languages"].split(",") if part.strip()}

    merged = existing_langs | new_langs
    if merged:
        char["languages"] = ", ".join(sorted(merged))

    # --- Track pending language choices ---
    lang_options = race.get("language_options", {})
    if lang_options and lang_options.get("choose", 0) > 0:
        char["pending_language_choice"] = lang_options.get("choose", 1)
        char["language_options"] = [opt.get("name", "") for opt in lang_options.get("from", [])]

    # --- Track pending ability choices (e.g., Half-Elf) ---
    ab_options = race.get("ability_bonus_options", {})
    if ab_options and ab_options.get("choose", 0) > 0:
        char["pending_ability_choice"] = ab_options.get("choose", 1)
        char["ability_choice_options"] = [opt.get("name", "") for opt in ab_options.get("from", [])]

    # --- Proficiencies ---
    profs = char.setdefault("profs", {})
    
    # Starting proficiencies from race
    starting_profs = race.get("starting_proficiencies") or []
    for p in starting_profs:
        if isinstance(p, dict):
            prof_name = p.get("name", "")
            prof_type = p.get("type", "").lower()
        else:
            prof_name = str(p)
            prof_type = "weapon"  # default
        
        if not prof_name:
            continue
            
        if prof_type == "skill" or "Skill:" in prof_name:
            skill_name = prof_name.replace("Skill: ", "").replace("Skill:", "").strip()
            skills = set(profs.setdefault("skills", []))
            skills.add(skill_name)
            profs["skills"] = sorted(skills)
        elif prof_type == "weapon":
            weapons = set(profs.setdefault("weapons", []))
            weapons.add(prof_name)
            profs["weapons"] = sorted(weapons)
        elif prof_type == "armor":
            armor = set(profs.setdefault("armor", []))
            armor.add(prof_name)
            profs["armor"] = sorted(armor)
        elif prof_type == "tool":
            tools = set(profs.setdefault("tools", []))
            tools.add(prof_name)
            profs["tools"] = sorted(tools)

    # --- Damage Resistances ---
    damage_res = race.get("damage_resistances") or []
    char_resistances = char.setdefault("damage_resistances", [])
    for dr in damage_res:
        if dr and dr not in char_resistances:
            char_resistances.append(dr)

    # --- Condition Resistances ---
    cond_res = race.get("condition_resistances") or []
    char_cond_res = char.setdefault("condition_resistances", [])
    for cr in cond_res:
        if cr and cr not in char_cond_res:
            char_cond_res.append(cr)

    # --- Traits -> Features: API uses list of dicts with "name" ---
    feats = char.setdefault("features", [])
    
    # Build lookup from race_traits (which has full descriptions)
    race_traits = race.get("race_traits") or []
    trait_desc_lookup = {}
    for rt in race_traits:
        if isinstance(rt, dict):
            name = rt.get("name", "")
            desc = rt.get("desc", "") or rt.get("description", "")
            if name:
                trait_desc_lookup[name] = desc
    
    traits = race.get("traits") or []
    for t in traits:
        if isinstance(t, dict):
            trait_name = t.get("name", "")
            # Handle both 'description' and 'desc' keys, and lookup from race_traits
            trait_desc = t.get("description", "") or t.get("desc", "") or trait_desc_lookup.get(trait_name, "")
            # Store as dict with description if available
            if trait_desc:
                feat_entry = {"name": trait_name, "description": trait_desc, "source": "race"}
            else:
                feat_entry = trait_name
        else:
            # String trait - try to find description in lookup
            trait_name = str(t)
            trait_desc = trait_desc_lookup.get(trait_name, "")
            if trait_desc:
                feat_entry = {"name": trait_name, "description": trait_desc, "source": "race"}
            else:
                feat_entry = trait_name
        
        # Check if already exists
        existing_names = []
        for f in feats:
            if isinstance(f, dict):
                existing_names.append(f.get("name", ""))
            else:
                existing_names.append(str(f))
        
        check_name = feat_entry.get("name") if isinstance(feat_entry, dict) else feat_entry
        if check_name and check_name not in existing_names:
            feats.append(feat_entry)
    
    # --- Store subrace options if available ---
    subraces = race.get("subraces") or []
    if subraces:
        char["available_subraces"] = subraces
    
    # --- Apply mechanical effects of racial traits ---
    apply_racial_trait_mechanics(char, race)


def apply_racial_trait_mechanics(char: dict, race: dict):
    """
    Apply mechanical effects of racial traits to a character.
    This handles things like:
    - Skill bonuses
    - Damage resistances
    - Special abilities (Breath Weapon, etc.)
    - Resources (uses per day)
    - Actions/Reactions
    """
    # Get all trait names from the character
    trait_names = set()
    for f in char.get("features", []):
        if isinstance(f, dict):
            trait_names.add(f.get("name", ""))
        else:
            trait_names.add(str(f))
    
    # Also check race_traits for descriptions
    race_traits = race.get("race_traits", [])
    trait_lookup = {}
    for rt in race_traits:
        if isinstance(rt, dict):
            trait_lookup[rt.get("name", "")] = rt.get("desc", "") or rt.get("description", "")
    
    abilities = char.get("abilities", {})
    level = char.get("level", 1)
    con_mod = (abilities.get("CON", 10) - 10) // 2
    int_mod = (abilities.get("INT", 10) - 10) // 2
    wis_mod = (abilities.get("WIS", 10) - 10) // 2
    cha_mod = (abilities.get("CHA", 10) - 10) // 2
    
    # Ensure containers exist
    char.setdefault("actions", [])
    char.setdefault("bonus_actions", [])
    char.setdefault("reactions", [])
    char.setdefault("damage_resistances", [])
    char.setdefault("condition_immunities", [])
    profs = char.setdefault("proficiencies", {})
    
    # ========== VISION TRAITS ==========
    if "Darkvision" in trait_names:
        char["darkvision"] = max(char.get("darkvision", 0), 60)
    
    if "Superior Darkvision" in trait_names:
        char["darkvision"] = max(char.get("darkvision", 0), 120)
    
    if "Deep Darkvision" in trait_names:
        char["darkvision"] = max(char.get("darkvision", 0), 120)
        char["deep_darkvision"] = True
    
    if "Low-Light Vision" in trait_names:
        char["low_light_vision"] = True
    
    # ========== RESISTANCE TRAITS ==========
    if "Hellish Resistance" in trait_names:
        if "fire" not in char["damage_resistances"]:
            char["damage_resistances"].append("fire")
    
    if "Cold Resistance" in trait_names:
        if "cold" not in char["damage_resistances"]:
            char["damage_resistances"].append("cold")
    
    if "Necrotic Resistance" in trait_names:
        if "necrotic" not in char["damage_resistances"]:
            char["damage_resistances"].append("necrotic")
    
    if "Damage Resistance" in trait_names:
        # Dragonborn - resistance based on ancestry (default to fire if not specified)
        ancestry = char.get("draconic_ancestry", "")
        ancestry_resistances = {
            "black": "acid", "copper": "acid",
            "blue": "lightning", "bronze": "lightning",
            "brass": "fire", "gold": "fire", "red": "fire",
            "green": "poison",
            "silver": "cold", "white": "cold",
        }
        res_type = ancestry_resistances.get(ancestry.lower(), "fire")
        if res_type not in char["damage_resistances"]:
            char["damage_resistances"].append(res_type)
    
    if "Heated Body" in trait_names:
        char["heated_body"] = True  # Deal fire damage when touched
        if "fire" not in char["damage_resistances"]:
            char["damage_resistances"].append("fire")
    
    if "Cold Weakness" in trait_names:
        char["cold_weakness"] = True  # Vulnerability to cold
    
    if "Stone Body" in trait_names:
        char["stone_body"] = True
        if "poison" not in char["damage_resistances"]:
            char["damage_resistances"].append("poison")
    
    # ========== SAVING THROW TRAITS ==========
    if "Fey Ancestry" in trait_names:
        char["fey_ancestry"] = True  # +2 vs charm, immune to magical sleep
        if "sleep" not in char.get("condition_immunities", []):
            char["condition_immunities"].append("sleep")
        char["charm_save_bonus"] = char.get("charm_save_bonus", 0) + 2
    
    if "Brave" in trait_names:
        char["brave"] = True  # +2 vs frightened
        char["fear_save_bonus"] = char.get("fear_save_bonus", 0) + 2
    
    if "Stubborn as Stone" in trait_names:
        char["stubborn_as_stone"] = True
        char["charm_save_bonus"] = char.get("charm_save_bonus", 0) + 2
        char["fear_save_bonus"] = char.get("fear_save_bonus", 0) + 2
        char["sleep_save_bonus"] = char.get("sleep_save_bonus", 0) + 2
    
    if "Unyielding" in trait_names:
        char["unyielding"] = True  # +2 vs being moved or knocked prone
    
    if "Deep Resilience" in trait_names:
        char["deep_resilience"] = True
        char["poison_save_bonus"] = char.get("poison_save_bonus", 0) + 2
    
    # ========== SKILL/ABILITY TRAITS ==========
    if "Keen Senses" in trait_names:
        skills = set(profs.setdefault("skills", []))
        skills.add("Perception")
        profs["skills"] = sorted(skills)
    
    if "Skill Versatility" in trait_names:
        # Humans get 2 extra skill proficiencies (handled in character creation)
        char["skill_versatility"] = True
    
    if "Prehensile Tail" in trait_names:
        char["prehensile_tail"] = True
        char["acrobatics_bonus"] = char.get("acrobatics_bonus", 0) + 2  # +2 to balance/climb
    
    if "Halfling Nimbleness" in trait_names:
        char["halfling_nimbleness"] = True  # Move through larger creatures
    
    if "Naturally Stealthy" in trait_names:
        char["naturally_stealthy"] = True  # Can hide behind larger creatures
    
    if "Silent Step" in trait_names:
        char["silent_step"] = True
        char["stealth_bonus"] = char.get("stealth_bonus", 0) + 2
    
    if "Umbral Awareness" in trait_names:
        char["umbral_awareness"] = True
        char["perception_bonus"] = char.get("perception_bonus", 0) + 2  # In darkness
    
    if "Snowborn Grace" in trait_names:
        char["snowborn_grace"] = True  # No movement penalty in snow/ice
    
    if "Agrarian Insight" in trait_names:
        char["agrarian_insight"] = True
        skills = set(profs.setdefault("skills", []))
        skills.add("Nature")
        profs["skills"] = sorted(skills)
    
    if "Underworld Lore" in trait_names:
        char["underworld_lore"] = True
        skills = set(profs.setdefault("skills", []))
        skills.add("Survival")  # Underground navigation
        profs["skills"] = sorted(skills)
    
    if "Stonecraft Instincts" in trait_names:
        char["stonecraft_instincts"] = True  # Detect stonework traps/hidden doors
    
    if "Barrow Sense" in trait_names:
        char["barrow_sense"] = True  # Sense undead within 30 ft
    
    # ========== WEAPON/ARMOR PROFICIENCY TRAITS ==========
    if "Elf Weapon Training" in trait_names:
        weapons = set(profs.setdefault("weapons", []))
        weapons.update(["longsword", "shortsword", "shortbow", "longbow"])
        profs["weapons"] = sorted(weapons)
    
    if "Shadow Elf Training" in trait_names:
        weapons = set(profs.setdefault("weapons", []))
        weapons.update(["rapier", "shortsword", "hand crossbow"])
        profs["weapons"] = sorted(weapons)
    
    if "Dwarven Armor Training" in trait_names:
        armor = set(profs.setdefault("armor", []))
        armor.update(["light armor", "medium armor"])
        profs["armor"] = sorted(armor)
    
    if "Primal Training" in trait_names:
        weapons = set(profs.setdefault("weapons", []))
        weapons.update(["javelin", "handaxe", "greataxe"])
        profs["weapons"] = sorted(weapons)
    
    # ========== HP/TOUGHNESS TRAITS ==========
    if "Dwarven Toughness" in trait_names:
        char["dwarven_toughness"] = True
        # +1 HP per level
        char["bonus_hp_per_level"] = char.get("bonus_hp_per_level", 0) + 1
    
    if "Hearty Constitution" in trait_names:
        char["hearty_constitution"] = True
        char["exhaustion_resistance"] = True
    
    if "Born of Iron" in trait_names:
        char["born_of_iron"] = True
        # Reduce physical damage by 1
        char["damage_reduction"] = char.get("damage_reduction", 0) + 1
    
    if "Relentless Endurance" in trait_names:
        char["relentless_endurance"] = True
        ensure_resource(char, "Relentless Endurance", 1, 1, "long_rest")
        # Add as a reaction
        if not any(a.get("name") == "Relentless Endurance" for a in char["reactions"] if isinstance(a, dict)):
            char["reactions"].append({
                "name": "Relentless Endurance",
                "type": "reaction",
                "description": "When reduced to 0 HP but not killed, drop to 1 HP instead. Once per long rest.",
                "resource": "Relentless Endurance",
                "source": "race"
            })
    
    # ========== ATTACK/DAMAGE TRAITS ==========
    if "Savage Attacks" in trait_names:
        char["savage_attacks"] = True  # Extra damage die on melee crit
    
    if "Gnashing Maw" in trait_names:
        char["gnashing_maw"] = True
        # Natural bite attack
        if not any(a.get("name") == "Bite" for a in char["actions"] if isinstance(a, dict)):
            char["actions"].append({
                "name": "Bite",
                "type": "melee",
                "damage": "1d6",
                "damage_type": "piercing",
                "description": "Natural bite attack using STR.",
                "source": "race"
            })
    
    if "Blood Frenzy" in trait_names:
        char["blood_frenzy"] = True  # +2 attack vs bloodied enemies
    
    if "Menacing Presence" in trait_names:
        char["menacing_presence"] = True
        skills = set(profs.setdefault("skills", []))
        skills.add("Intimidation")
        profs["skills"] = sorted(skills)
    
    # ========== SPECIAL ABILITY TRAITS ==========
    if "Lucky" in trait_names:
        char["halfling_lucky"] = True  # Reroll 1s on d20
        ensure_resource(char, "Lucky", 3, 3, "long_rest")
    
    if "Trance" in trait_names or "Gnomish Trance" in trait_names:
        char["trance"] = True  # 4 hours of meditation instead of 8 hours sleep
    
    if "Speak with Small Beasts" in trait_names:
        char["speak_with_small_beasts"] = True
    
    if "Natural Illusionist" in trait_names:
        char["natural_illusionist"] = True
        # Can cast Minor Illusion
        char.setdefault("cantrips_known", []).append("Minor Illusion")
    
    if "Infernal Legacy" in trait_names:
        char["infernal_legacy"] = True
        char.setdefault("cantrips_known", []).append("Thaumaturgy")
        # At level 3: Hellish Rebuke, At level 5: Darkness
        if level >= 3:
            char.setdefault("racial_spells", []).append({"name": "Hellish Rebuke", "uses": 1, "recharge": "long_rest"})
        if level >= 5:
            char.setdefault("racial_spells", []).append({"name": "Darkness", "uses": 1, "recharge": "long_rest"})
    
    if "Dark Elf Magic" in trait_names:
        char["dark_elf_magic"] = True
        char.setdefault("cantrips_known", []).append("Dancing Lights")
        if level >= 3:
            char.setdefault("racial_spells", []).append({"name": "Faerie Fire", "uses": 1, "recharge": "long_rest"})
        if level >= 5:
            char.setdefault("racial_spells", []).append({"name": "Darkness", "uses": 1, "recharge": "long_rest"})
    
    if "Winter Court Magic" in trait_names:
        char["winter_court_magic"] = True
        char.setdefault("cantrips_known", []).append("Ray of Frost")
        if level >= 3:
            char.setdefault("racial_spells", []).append({"name": "Fog Cloud", "uses": 1, "recharge": "long_rest"})
    
    if "Elven Magecraft" in trait_names:
        char["elven_magecraft"] = True
        # One wizard cantrip
        char["bonus_cantrip_choice"] = "wizard"
    
    if "Keen Mind" in trait_names:
        char["keen_mind"] = True
        char["arcana_bonus"] = char.get("arcana_bonus", 0) + 2
    
    if "Firestarter" in trait_names:
        char["firestarter"] = True
        char.setdefault("cantrips_known", []).append("Produce Flame")
    
    if "Ghost Light" in trait_names:
        char["ghost_light"] = True
        char.setdefault("cantrips_known", []).append("Light")
    
    if "Poison Affinity" in trait_names:
        char["poison_affinity"] = True
        if "poison" not in char["damage_resistances"]:
            char["damage_resistances"].append("poison")
    
    # ========== MISTSTEP AGILITY (Chichipi) ==========
    if "Miststep Agility" in trait_names:
        char["miststep_agility"] = True
        ensure_resource(char, "Miststep Agility", 1, 1, "long_rest")
        if not any(a.get("name") == "Miststep (Bonus)" for a in char.get("bonus_actions", []) if isinstance(a, dict)):
            char["bonus_actions"].append({
                "name": "Miststep (Bonus)",
                "type": "bonus_action",
                "description": "Take the Dash action as a bonus action. Once per long rest.",
                "resource": "Miststep Agility",
                "source": "race"
            })
    
    # ========== DRACONIC ANCESTRY / BREATH WEAPON ==========
    if "Draconic Ancestry" in trait_names:
        char["draconic_ancestry_trait"] = True
        uses = max(1, con_mod)
        ensure_resource(char, "Breath Weapon", uses, uses, "long_rest")
        
        # Determine damage based on level
        if level >= 17:
            breath_damage = "4d10"
        elif level >= 11:
            breath_damage = "3d10"
        elif level >= 5:
            breath_damage = "2d10"
        else:
            breath_damage = "2d6"
        
        # Get ancestry type for damage type
        ancestry = char.get("draconic_ancestry", "red").lower()
        ancestry_damage = {
            "black": ("acid", "5x30 ft line", "DEX"),
            "blue": ("lightning", "5x30 ft line", "DEX"),
            "brass": ("fire", "5x30 ft line", "DEX"),
            "bronze": ("lightning", "5x30 ft line", "DEX"),
            "copper": ("acid", "5x30 ft line", "DEX"),
            "gold": ("fire", "15 ft cone", "DEX"),
            "green": ("poison", "15 ft cone", "CON"),
            "red": ("fire", "15 ft cone", "DEX"),
            "silver": ("cold", "15 ft cone", "CON"),
            "white": ("cold", "15 ft cone", "CON"),
        }
        dmg_type, area, save = ancestry_damage.get(ancestry, ("fire", "15 ft cone", "DEX"))
        
        if not any(a.get("name") == "Breath Weapon" for a in char["actions"] if isinstance(a, dict)):
            char["actions"].append({
                "name": "Breath Weapon",
                "type": "action",
                "damage": breath_damage,
                "damage_type": dmg_type,
                "area": area,
                "save": save,
                "save_dc": f"8 + CON mod + 1/2 level",
                "description": f"Exhale {dmg_type} energy in a {area}. {save} save for half damage.",
                "resource": "Breath Weapon",
                "source": "race"
            })
    
    # ========== GNOME GADGETS ==========
    if "Clockwork Toy" in trait_names:
        char["clockwork_toy"] = True
        ensure_resource(char, "Clockwork Toy", 1, 1, "long_rest")
    
    if "Music Box" in trait_names:
        char["music_box"] = True
        ensure_resource(char, "Music Box", 1, 1, "long_rest")
    
    if "Signal Flare" in trait_names:
        char["signal_flare"] = True
        ensure_resource(char, "Signal Flare", 1, 1, "long_rest")
    
    if "Whirring Lens" in trait_names:
        char["whirring_lens"] = True
        ensure_resource(char, "Whirring Lens", 1, 1, "long_rest")
    
    if "Arcano-Mechanical Aptitude" in trait_names:
        char["arcano_mechanical_aptitude"] = True
        tools = set(profs.setdefault("tools", []))
        tools.add("Tinker's Tools")
        profs["tools"] = sorted(tools)
    
    # ========== GIANT ANCESTRY ==========
    if "Giant Ancestry" in trait_names:
        char["giant_ancestry"] = True
        char["powerful_build"] = True  # Count as Large for carrying capacity
    
    if "Large Form" in trait_names:
        char["large_form"] = True
        char["size"] = "Large"
    
    # ========== HALF-BREEDS ==========
    if "Dual Heritage" in trait_names or "Blood of Two Worlds" in trait_names:
        char["dual_heritage"] = True  # Count as both parent races
    
    # ========== LIGHT SENSITIVITY ==========
    if "Dazed by Light" in trait_names:
        char["dazed_by_light"] = True  # -2 in bright light


def apply_subrace(char: dict, subrace: dict):
    """
    Apply a subrace to a character, including:
    - Additional ability bonuses
    - Additional traits/features
    - Speed modifications
    - Additional proficiencies
    """
    if not subrace:
        return
    
    char["subrace"] = subrace.get("name", "")
    
    # --- Ensure abilities exist ---
    if "abilities" not in char or not isinstance(char["abilities"], dict):
        char["abilities"] = {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10}
    
    # --- Subrace ability bonuses ---
    ab = subrace.get("ability_bonuses") or []
    for entry in ab:
        if not isinstance(entry, dict):
            continue
        # Handle nested format: {"ability_score": {"name": "STR"}, "bonus": 1}
        if "ability_score" in entry and isinstance(entry["ability_score"], dict):
            key = entry["ability_score"].get("name", "").upper()
        else:
            # Handle simple format: {"name": "STR", "bonus": 1}
            key = entry.get("name", "").upper()
        bonus = entry.get("bonus", 0)
        if key in char["abilities"]:
            char["abilities"][key] = int(char["abilities"][key]) + int(bonus)
    
    # --- Subrace traits/features ---
    feats = char.setdefault("features", [])
    traits = subrace.get("traits") or []
    for t in traits:
        if isinstance(t, dict):
            trait_name = t.get("name", "")
            trait_desc = t.get("description", "")
            if trait_desc:
                feat_entry = {"name": trait_name, "description": trait_desc, "source": "subrace"}
            else:
                feat_entry = trait_name
        else:
            feat_entry = str(t)
        
        # Check if already exists
        existing_names = []
        for f in feats:
            if isinstance(f, dict):
                existing_names.append(f.get("name", ""))
            else:
                existing_names.append(str(f))
        
        check_name = feat_entry.get("name") if isinstance(feat_entry, dict) else feat_entry
        if check_name and check_name not in existing_names:
            feats.append(feat_entry)
    
    # --- Check for special subrace effects ---
    features_str = subrace.get("features", "").lower()
    
    # Speed modification (e.g., Wood Elf "Speed 35 ft")
    speed_match = re.search(r"speed\s*(?:increases?\s*to\s*)?(\d+)", features_str)
    if speed_match:
        char["speed"] = f"{speed_match.group(1)} ft."
    
    # HP per level (e.g., Hill Dwarf "Dwarven Toughness")
    if "hp per level" in features_str or "toughness" in features_str:
        char["subrace_hp_bonus"] = 1  # +1 HP per level
    
    # Superior Darkvision (e.g., Drow, Deep Gnome)
    if "superior darkvision" in features_str:
        char["darkvision"] = 120
    
    # Armor proficiency (e.g., Mountain Dwarf)
    if "armor proficiency" in features_str or "light and medium armor" in features_str:
        profs = char.setdefault("profs", {})
        armor = set(profs.setdefault("armor", []))
        armor.add("light")
        armor.add("medium")
        profs["armor"] = sorted(armor)
    
    # --- Apply mechanical effects of subrace traits ---
    apply_racial_trait_mechanics(char, subrace)


def apply_background(char: dict, bg: dict, ability_choices: list = None):
    """
    Apply a background to a character, including:
    - Ability bonuses (static and choice-based)
    - Skills (proficiencies)
    - Skill bonuses (if any)
    - Languages
    - Tool proficiencies
    - Equipment
    - Feature
    - Origin feat
    
    Args:
        char: Character dict to modify
        bg: Background data dict
        ability_choices: List of ability names chosen for ability_bonus_options
    """
    char["background"] = bg.get("name", "")
    
    # --- Ensure abilities exist ---
    if "abilities" not in char or not isinstance(char["abilities"], dict):
        char["abilities"] = {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10}
    
    # --- Apply static ability bonuses ---
    ab = bg.get("ability_bonuses", [])
    for entry in ab:
        if isinstance(entry, dict):
            key = entry.get("name", "").upper()
            bonus = entry.get("bonus", 0)
            if key in char["abilities"]:
                char["abilities"][key] = int(char["abilities"][key]) + int(bonus)
    
    # --- Apply ability bonus choices ---
    if ability_choices:
        ab_options = bg.get("ability_bonus_options", {})
        options_list = ab_options.get("from", [])
        option_bonuses = {opt.get("name", ""): opt.get("bonus", 1) for opt in options_list}
        for choice in ability_choices:
            if choice in char["abilities"]:
                char["abilities"][choice] += option_bonuses.get(choice, 1)
    
    # --- Store pending ability choices if not provided ---
    ab_options = bg.get("ability_bonus_options", {})
    if ab_options and ab_options.get("choose", 0) > 0 and not ability_choices:
        char["pending_bg_ability_choice"] = ab_options.get("choose", 1)
        char["bg_ability_choice_options"] = [opt.get("name", "") for opt in ab_options.get("from", [])]
    
    # --- Origin Feat ---
    origin_feat = bg.get("origin_feat")
    if origin_feat:
        char["origin_feat"] = origin_feat
        # Add to features list
        features = char.setdefault("features", [])
        feat_entry = {"name": f"Origin Feat: {origin_feat}", "description": f"Background feat from {bg.get('name', 'background')}", "source": "background"}
        existing_names = [f.get("name") if isinstance(f, dict) else f for f in features]
        if feat_entry["name"] not in existing_names:
            features.append(feat_entry)
    
    # Initialize proficiencies structure
    profs = char.setdefault("profs", {})
    
    # Apply skill proficiencies
    skills = set(profs.setdefault("skills", []))
    for s in (bg.get("skills") or []):
        if s:
            skills.add(s)
    profs["skills"] = sorted(skills)
    
    # Apply skill bonuses (some backgrounds give +2 to specific skills)
    skill_bonuses = bg.get("skill_bonuses", {})
    if skill_bonuses:
        char_skill_bonuses = char.setdefault("skill_bonuses", {})
        for skill_name, bonus in skill_bonuses.items():
            current = char_skill_bonuses.get(skill_name, 0)
            char_skill_bonuses[skill_name] = current + bonus
    
    # Apply tool proficiencies
    tools = set(profs.setdefault("tools", []))
    for t in (bg.get("tool_proficiencies") or []):
        if t:
            tools.add(t)
    profs["tools"] = sorted(tools)
    
    # Apply languages
    lang_count = bg.get("languages", 0)
    if isinstance(lang_count, int) and lang_count > 0:
        # Store number of languages to choose
        char["background_languages_to_choose"] = lang_count
    elif isinstance(lang_count, list):
        # Specific languages
        existing = set((char.get("languages") or "").split(", ")) if char.get("languages") else set()
        for l in lang_count:
            if l:
                existing.add(l)
        existing.discard("")
        char["languages"] = ", ".join(sorted(existing)) if existing else ""
    
    # Apply equipment
    equipment = char.setdefault("equipment", [])
    for item in (bg.get("equipment") or []):
        if isinstance(item, str) and item not in equipment:
            equipment.append(item)
        elif isinstance(item, dict):
            item_name = item.get("equipment", {}).get("name", "")
            if item_name and item_name not in equipment:
                equipment.append(item_name)
    
    # Apply feature
    feature = bg.get("feature", {})
    if feature:
        features = char.setdefault("features", [])
        feat_name = feature.get("name", "")
        feat_desc = feature.get("description", "")
        if feat_name:
            # Check if feature already exists
            existing_names = [f.get("name") if isinstance(f, dict) else f for f in features]
            if feat_name not in existing_names:
                features.append({
                    "name": feat_name,
                    "description": feat_desc,
                    "source": f"Background: {bg.get('name', '')}"
                })

def get_bab_for_level(bab_type: str, level: int) -> int:
    """
    Calculate Base Attack Bonus based on progression type and level.
    
    BAB Types:
    - "full": +1 per level (Fighter, Barbarian, Paladin, Ranger, Monk, Marshal, Spellblade)
    - "3/4": +3/4 per level (Rogue, Artificer)
    - "1/2": +1/2 per level (Cleric, Druid, Bard, Warlock, Wizard)
    - "1/4": +1/4 per level (Sorcerer)
    """
    bab_type = (bab_type or "").lower().strip()
    
    if bab_type in ("full", "1", "full bab", "+1"):
        return level
    elif bab_type in ("3/4", "¾", "three-quarter", "¾ bab"):
        return (level * 3) // 4
    elif bab_type in ("1/2", "½", "half", "half bab", "½ bab"):
        return level // 2
    elif bab_type in ("1/4", "¼", "quarter", "one-fourth", "¼ bab"):
        return level // 4
    else:
        # Default to 3/4 if not specified
        return (level * 3) // 4


def get_save_bonus_for_level(level: int) -> int:
    """
    Calculate save bonus for primary stats.
    Uses 3.5e-style progression: +2 at level 1, +1 every 2 levels after.
    """
    return 2 + (level // 2)


def apply_class_level1(char: dict, cls: dict, kit_idx: int = 0):
    """Apply a class to a character and recompute HP/AC/BAB/Saves."""
    # basic identity
    char["class"] = cls.get("name", "")
    char["level"] = 1
    char["proficiency_bonus"] = 2  # Keep for compatibility, but BAB is primary

    # make sure we have abilities to work with (needed for HP/AC)
    char.setdefault(
        "abilities",
        {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
    )
    
    # ---- BAB (Base Attack Bonus) ----
    bab_type = cls.get("base_attack_bonus", cls.get("bab_progression", "3/4"))
    char["bab_type"] = bab_type
    char["bab"] = get_bab_for_level(bab_type, 1)
    
    # ---- Save Bonuses ----
    # Primary abilities get the good save progression (+2 at level 1)
    # Other saves get +0 at level 1
    primary_abilities = cls.get("primary_abilities", [])
    # Normalize ability names to 3-letter codes
    primary_stats = []
    for ab in primary_abilities:
        ab_upper = ab.upper().strip()
        if ab_upper in ("STR", "STRENGTH"):
            primary_stats.append("STR")
        elif ab_upper in ("DEX", "DEXTERITY"):
            primary_stats.append("DEX")
        elif ab_upper in ("CON", "CONSTITUTION"):
            primary_stats.append("CON")
        elif ab_upper in ("INT", "INTELLIGENCE"):
            primary_stats.append("INT")
        elif ab_upper in ("WIS", "WISDOM"):
            primary_stats.append("WIS")
        elif ab_upper in ("CHA", "CHARISMA"):
            primary_stats.append("CHA")
    
    char["primary_saves"] = primary_stats
    save_bonus = get_save_bonus_for_level(1)
    char["save_bonuses"] = {
        "STR": save_bonus if "STR" in primary_stats else 0,
        "DEX": save_bonus if "DEX" in primary_stats else 0,
        "CON": save_bonus if "CON" in primary_stats else 0,
        "INT": save_bonus if "INT" in primary_stats else 0,
        "WIS": save_bonus if "WIS" in primary_stats else 0,
        "CHA": save_bonus if "CHA" in primary_stats else 0,
    }

    # proficiencies
    pr = char.setdefault("profs", {})
    for key, src in (
        ("saves", "primary_saves"),  # This now correctly uses primary_saves we just set
        ("armor", "armor_proficiencies"),
        ("weapons", "weapon_proficiencies"),
    ):
        pr.setdefault(key, [])
        cur = set(pr[key])
        # Try multiple field names for compatibility
        values = cls.get(src) or cls.get(src.replace("_proficiencies", "_profs")) or []
        for v in values:
            if v:
                cur.add(v)
        pr[key] = sorted(cur)
    
    # Also store primary saves in profs for display
    pr["saves"] = primary_stats.copy()

    # level 1 features
    feats = char.setdefault("features", [])
    for f in (cls.get("level_1_features") or []):
        if f not in feats:
            feats.append(f)

    # HP for level 1
    hp = compute_hp_level1(char, cls)
    char["hp"] = hp
    char["max_hp"] = hp

    # starting equipment kit
    kits = cls.get("starting_equipment_kits") or []
    kit = kits[kit_idx] if kits and 0 <= kit_idx < len(kits) else {}
    eq = set(char.get("equipment") or [])
    if kit.get("armor"):
        eq.add(kit["armor"])
    if kit.get("shield"):
        eq.add("Shield")
    if kit.get("focus"):
        eq.add(kit["focus"])
    for extra in (kit.get("extras") or []):
        eq.add(extra)
    char["equipment"] = sorted(eq)

    set_default_attack_from_kit(char, kit)

    # make sure any weapon equipment becomes attacks
    sync_attacks_from_equipment(char)

    char["ac"] = compute_ac_from_equipment(char)

def ensure_resource(char: dict, name: str, a: int, b: int | None = None, recharge: str | None = None):
    """
    Backward compatible:
      - ensure_resource(char, name, max_val)
      - ensure_resource(char, name, current, max_val, recharge)
    Ensures char['resources'][name] exists with current/max (+ optional recharge).
    """
    if b is None:
        # Old style: (max_val)
        current = None
        max_val = a
    else:
        # New style: (current, max_val, recharge)
        current = a
        max_val = b

    if max_val < 0:
        max_val = 0

    res = char.setdefault("resources", {})
    entry = res.get(name, {}) if isinstance(res.get(name, {}), dict) else {}

    # preserve existing current unless explicitly provided
    if current is None:
        current_val = entry.get("current", max_val)
    else:
        current_val = current

    entry_out = {
        "current": min(max(current_val, 0), max_val),
        "max": max_val,
    }

    # preserve existing recharge unless explicitly provided
    if recharge is not None:
        entry_out["recharge"] = recharge
    elif "recharge" in entry:
        entry_out["recharge"] = entry["recharge"]

    res[name] = entry_out

# ============== WARLOCK HELPER FUNCTIONS ==============

# Eldritch Invocations data
WARLOCK_INVOCATIONS = {
    "Agonizing Blast": {"prereq": "Eldritch Blast cantrip", "level": 1, "description": "Add CHA mod to Eldritch Blast damage."},
    "Armor of Shadows": {"prereq": None, "level": 1, "description": "Cast Mage Armor on yourself at will without slot."},
    "Beast Speech": {"prereq": None, "level": 1, "description": "Cast Speak with Animals at will."},
    "Beguiling Influence": {"prereq": None, "level": 1, "description": "Gain proficiency in Deception and Persuasion."},
    "Devil's Sight": {"prereq": None, "level": 1, "description": "See normally in darkness (magical/nonmagical) to 120 feet."},
    "Eldritch Sight": {"prereq": None, "level": 1, "description": "Cast Detect Magic at will."},
    "Eldritch Spear": {"prereq": "Eldritch Blast cantrip", "level": 1, "description": "Eldritch Blast range becomes 300 feet."},
    "Eyes of the Rune Keeper": {"prereq": None, "level": 1, "description": "Read all writing."},
    "Fiendish Vigor": {"prereq": None, "level": 1, "description": "Cast False Life on yourself at will as 1st-level."},
    "Mask of Many Faces": {"prereq": None, "level": 1, "description": "Cast Disguise Self at will."},
    "Misty Visions": {"prereq": None, "level": 1, "description": "Cast Silent Image at will."},
    "Repelling Blast": {"prereq": "Eldritch Blast cantrip", "level": 1, "description": "Eldritch Blast hits push target 10 feet."},
    "Thief of Five Fates": {"prereq": None, "level": 1, "description": "Cast Bane once using a warlock spell slot; regain after long rest."},
    "Mire the Mind": {"prereq": None, "level": 5, "description": "Cast Slow once using a warlock spell slot; regain after long rest."},
    "One with Shadows": {"prereq": None, "level": 5, "description": "In dim light/darkness, become invisible until you move/act."},
    "Sign of Ill Omen": {"prereq": None, "level": 5, "description": "Cast Bestow Curse once using a warlock spell slot; regain after long rest."},
    "Thirsting Blade": {"prereq": "Pact of the Blade", "level": 5, "description": "Attack twice with pact weapon when you take Attack action."},
    "Bewitching Whispers": {"prereq": None, "level": 7, "description": "Cast Compulsion once using a warlock spell slot; regain after long rest."},
    "Dreadful Word": {"prereq": None, "level": 7, "description": "Cast Confusion once using a warlock spell slot; regain after long rest."},
    "Sculptor of Flesh": {"prereq": None, "level": 7, "description": "Cast Polymorph once using a warlock spell slot; regain after long rest."},
    "Ascendant Step": {"prereq": None, "level": 9, "description": "Cast Levitate on yourself at will without slot."},
    "Minions of Chaos": {"prereq": None, "level": 9, "description": "Cast Conjure Elemental once using a warlock spell slot; regain after long rest."},
    "Otherworldly Leap": {"prereq": None, "level": 9, "description": "Cast Jump on yourself at will."},
    "Whispers of the Grave": {"prereq": None, "level": 9, "description": "Cast Speak with Dead at will."},
    "Lifedrinker": {"prereq": "Pact of the Blade", "level": 12, "description": "Pact weapon hits deal extra necrotic damage equal to CHA mod."},
    "Chains of Carceri": {"prereq": "Pact of the Chain", "level": 15, "description": "Cast Hold Monster at will on celestials, fiends, or elementals."},
    "Master of Myriad Forms": {"prereq": None, "level": 15, "description": "Cast Alter Self at will."},
    "Visions of Distant Realms": {"prereq": None, "level": 15, "description": "Cast Arcane Eye at will."},
    "Witch Sight": {"prereq": None, "level": 15, "description": "See true form of shapechangers/illusioned creatures within 30 feet."},
}

def _apply_warlock_invocations(char: dict, invocations: list, cha_mod: int, bab: int, lvl: int, features: list, actions: list):
    """Apply selected Warlock invocations to character."""
    for inv_name in invocations:
        inv_data = WARLOCK_INVOCATIONS.get(inv_name)
        if not inv_data:
            continue
        
        # Check level requirement
        if lvl < inv_data.get("level", 1):
            continue
        
        # Add feature if not already present
        feature_text = f"Invocation: {inv_name} - {inv_data['description']}"
        if not any(inv_name in f for f in features):
            features.append(feature_text)
        
        # Special handling for certain invocations
        if inv_name == "Agonizing Blast":
            char["agonizing_blast"] = True
        elif inv_name == "Eldritch Spear":
            char["eldritch_spear"] = True
        elif inv_name == "Repelling Blast":
            char["repelling_blast"] = True
        elif inv_name == "Thirsting Blade":
            char["thirsting_blade"] = True
        elif inv_name == "Lifedrinker":
            char["lifedrinker"] = True
        elif inv_name == "Devil's Sight":
            char["darkvision"] = 120
            char["devils_sight"] = True
        elif inv_name == "Armor of Shadows":
            # Add at-will Mage Armor action
            if not any(a.get("name") == "Mage Armor (At-Will)" for a in actions):
                actions.append({
                    "name": "Mage Armor (At-Will)",
                    "action_type": "action",
                    "description": "Cast Mage Armor on yourself without expending a spell slot.",
                })
        elif inv_name == "Fiendish Vigor":
            if not any(a.get("name") == "False Life (At-Will)" for a in actions):
                actions.append({
                    "name": "False Life (At-Will)",
                    "action_type": "action",
                    "description": "Cast False Life on yourself at 1st level without expending a spell slot.",
                })
        elif inv_name == "Mask of Many Faces":
            if not any(a.get("name") == "Disguise Self (At-Will)" for a in actions):
                actions.append({
                    "name": "Disguise Self (At-Will)",
                    "action_type": "action",
                    "description": "Cast Disguise Self without expending a spell slot.",
                })

def _apply_warlock_pact_boon(char: dict, pact_boon: str, cha_mod: int, lvl: int, features: list, actions: list):
    """Apply Warlock Pact Boon features."""
    if pact_boon == "Blade":
        if not any("Pact of the Blade" in f for f in features):
            features.append("Pact of the Blade: Create a pact weapon as an action. Counts as magical. Can bind a magic weapon.")
        if not any(a.get("name") == "Create Pact Weapon" for a in actions):
            actions.append({
                "name": "Create Pact Weapon",
                "action_type": "action",
                "description": "Create a pact weapon in your empty hand. Choose the form each time.",
            })
        char["pact_blade"] = True
        
    elif pact_boon == "Chain":
        if not any("Pact of the Chain" in f for f in features):
            features.append("Pact of the Chain: Cast Find Familiar as a ritual. Can be imp, pseudodragon, quasit, or sprite.")
        char["pact_chain"] = True
        
    elif pact_boon == "Tome":
        if not any("Pact of the Tome" in f for f in features):
            features.append("Pact of the Tome: Book of Shadows with 3 cantrips from any class. Cast at will.")
        char["pact_tome"] = True
        
    elif pact_boon == "Talisman":
        talisman_uses = max(1, cha_mod)
        ensure_resource(char, "Talisman", talisman_uses)
        if not any("Pact of the Talisman" in f for f in features):
            features.append(f"Pact of the Talisman: Wearer adds 1d4 to failed ability checks. {talisman_uses} uses/rest.")
        char["pact_talisman"] = True

def _apply_warlock_patron_feature(char: dict, patron: str, lvl: int, tier: str, cha_mod: int, features: list, actions: list):
    """Apply patron-specific features based on tier (touch, gift, favor, might, ascendance)."""
    
    if patron == "Fiend":
        if tier == "touch" and lvl >= 2:
            if not any("Infernal Resilience" in f for f in features):
                features.append("Infernal Resilience: Resistance to fire damage. Add CHA mod to fire damage rolls.")
            char.setdefault("damage_resistances", []).append("fire") if "fire" not in char.get("damage_resistances", []) else None
        elif tier == "gift" and lvl >= 6:
            if not any("Infernal Resistances" in f for f in features):
                features.append("Infernal Resistances: Resistance to fire. At 10th, also poison.")
            if lvl >= 10 and "poison" not in char.get("damage_resistances", []):
                char.setdefault("damage_resistances", []).append("poison")
        elif tier == "favor" and lvl >= 10:
            ensure_resource(char, "Hellish Wrath", 1)
            if not any("Hellish Wrath" in f for f in features):
                features.append(f"Hellish Wrath: Reaction when hit - deal 2d6 fire to attacker (DC {10 + cha_mod + lvl} save for half).")
        elif tier == "might" and lvl >= 14:
            if not any("Infernal Resurgence" in f for f in features):
                features.append("Infernal Resurgence: At half HP or lower, reaction to heal Warlock level HP. Cast Fireball 1/day.")
    
    elif patron == "Great Old One":
        if tier == "touch" and lvl >= 2:
            if not any("Mindwarp" in f for f in features):
                features.append("Mindwarp: Telepathy 30 feet with creatures that understand a language.")
            char["telepathy"] = 30
        elif tier == "gift" and lvl >= 6:
            if not any("Distorted Mind" in f for f in features):
                features.append("Distorted Mind: Resistance to psychic. At 10th, immunity to Charmed.")
            char.setdefault("damage_resistances", []).append("psychic") if "psychic" not in char.get("damage_resistances", []) else None
        elif tier == "favor" and lvl >= 10:
            if not any("Mental Manipulation" in f for f in features):
                features.append(f"Mental Manipulation: Action - creature within 30 ft makes DC {10 + cha_mod + lvl} WIS save or Charmed/Frightened 1 min.")
    
    elif patron == "Archfey":
        if tier == "touch" and lvl >= 2:
            fey_step_uses = max(1, cha_mod)
            ensure_resource(char, "Fey Step", fey_step_uses)
            if not any("Fey Step" in f for f in features):
                features.append(f"Fey Step: {fey_step_uses}/day, bonus action Misty Step.")
            if not any(a.get("name") == "Fey Step" for a in actions):
                actions.append({
                    "name": "Fey Step",
                    "resource": "Fey Step",
                    "action_type": "bonus",
                    "description": "Bonus Action: Cast Misty Step (teleport 30 ft).",
                })
        elif tier == "gift" and lvl >= 6:
            if not any("Veilwalker" in f for f in features):
                features.append("Veilwalker: Hide when lightly obscured. At 10th, leave no trace (Pass Without Trace).")
        elif tier == "favor" and lvl >= 10:
            if not any("Misty Escape" in f for f in features):
                features.append("Misty Escape: Reaction - Misty Step to avoid ranged attack, redirect to creature within 5 ft.")
    
    elif patron == "Celestial":
        if tier == "touch" and lvl >= 2:
            ensure_resource(char, "Healing Light", 1)
            if not any("Healing Light" in f for f in features):
                features.append(f"Healing Light: Bonus action, heal creature within 30 ft for 1d6+{cha_mod}. 1/long rest.")
            if not any(a.get("name") == "Healing Light" for a in actions):
                actions.append({
                    "name": "Healing Light",
                    "resource": "Healing Light",
                    "action_type": "bonus",
                    "description": f"Bonus Action: Heal a creature within 30 ft for 1d6+{cha_mod} HP.",
                })
        elif tier == "gift" and lvl >= 6:
            if not any("Sanctified Endurance" in f for f in features):
                features.append("Sanctified Endurance: Resistance to radiant. At 10th, gain temp HP when casting Light/Healing spells.")
            char.setdefault("damage_resistances", []).append("radiant") if "radiant" not in char.get("damage_resistances", []) else None
    
    elif patron == "Shadow":
        if tier == "touch" and lvl >= 2:
            if not any("Death's Whispers" in f for f in features):
                features.append("Death's Whispers: Speak with Dead at will (creatures dead within 1 hour).")
        elif tier == "gift" and lvl >= 6:
            if not any("Gravebound" in f for f in features):
                features.append("Gravebound: Resistance to necrotic. At 10th, resistance to B/P/S from nonmagical.")
            char.setdefault("damage_resistances", []).append("necrotic") if "necrotic" not in char.get("damage_resistances", []) else None
    
    elif patron == "Draconic":
        if tier == "touch" and lvl >= 2:
            dragon_type = char.get("warlock_dragon_type", "Fire")
            damage_by_level = {1: "1d6", 6: "2d6", 11: "3d6", 16: "4d6", 20: "5d6"}
            breath_damage = "1d6"
            for threshold, dmg in sorted(damage_by_level.items()):
                if lvl >= threshold:
                    breath_damage = dmg
            ensure_resource(char, "Breath Weapon", 1)
            if not any("Breath Weapon Invocation" in f for f in features):
                features.append(f"Breath Weapon: 15-ft cone or 30-ft line, {breath_damage} {dragon_type} damage. DC = 8 + CHA + level.")
            if not any(a.get("name") == "Breath Weapon" for a in actions):
                actions.append({
                    "name": "Breath Weapon",
                    "resource": "Breath Weapon",
                    "action_type": "action",
                    "damage": breath_damage,
                    "damage_type": dragon_type.lower(),
                    "save_dc": 8 + cha_mod + lvl,
                    "save_type": "DEX",
                    "description": f"Action: 15-ft cone or 30-ft line dealing {breath_damage} {dragon_type} damage (DC {8 + cha_mod + lvl} DEX save for half).",
                })


# ============== WIZARD SCHOOLS ==============

WIZARD_SCHOOLS = {
    "General": {"description": "Broad magical study. Learn extra spells."},
    "Abjuration": {"description": "Protective magic. Boost AC from abjuration spells."},
    "Conjuration": {"description": "Summoning and teleportation. Reaction teleport."},
    "Divination": {"description": "Knowledge and foresight. Fate-twisting dice."},
    "Enchantment": {"description": "Mind control. Daze attackers."},
    "Evocation": {"description": "Elemental destruction. Force attacks."},
    "Illusion": {"description": "Deception and trickery. Bonus illusion cantrips."},
    "Necromancy": {"description": "Death magic. Undead familiar."},
    "Transmutation": {"description": "Transformation. Gain temp HP."},
}

def _apply_wizard_school_feature(char: dict, school: str, lvl: int, int_mod: int, spell_dc: int, features: list, actions: list, tier: str = "specialization"):
    """Apply Wizard school-specific features."""
    
    if tier == "specialization":
        if not any(f"School: {school}" in f for f in features):
            features[:] = [f for f in features if "Magic School Specialization:" not in f]
            features.append(f"School: {school} - {WIZARD_SCHOOLS.get(school, {}).get('description', '')}")
        
        if school == "General":
            if not any("Broad Study" in f for f in features):
                features.append("Broad Study: Learn 1 extra spell per spell level (1st-5th).")
        
        elif school == "Abjuration":
            if not any("Abjuration Adept" in f for f in features):
                features.append("Abjuration Adept: +1 AC bonus from abjuration spells.")
        
        elif school == "Conjuration":
            ensure_resource(char, "Benign Transposition", max(1, int_mod))
            if not any("Benign Transposition" in f for f in features):
                features.append(f"Benign Transposition: {max(1, int_mod)}/day, reaction to teleport 15 ft.")
            if not any(a.get("name") == "Benign Transposition" for a in actions):
                actions.append({
                    "name": "Benign Transposition",
                    "resource": "Benign Transposition",
                    "action_type": "reaction",
                    "description": "Reaction: Teleport up to 15 ft to an unoccupied space you can see.",
                })
        
        elif school == "Divination":
            ensure_resource(char, "Portent", max(1, int_mod))
            if not any("Portent" in f for f in features):
                features.append(f"Portent: {max(1, int_mod)}/day, reaction to add d4 to any roll you can see.")
        
        elif school == "Enchantment":
            ensure_resource(char, "Hypnotic Gaze", max(1, int_mod))
            if not any("Hypnotic Gaze" in f for f in features):
                features.append(f"Hypnotic Gaze: {max(1, int_mod)}/day, reaction to daze attacker (WIS save DC {spell_dc}).")
        
        elif school == "Evocation":
            if not any("Evocation Savant" in f for f in features):
                evoc_damage = f"1d4" if lvl < 10 else f"1d6" if lvl < 14 else f"1d8"
                features.append(f"Evocation Savant: Reaction ranged force attack ({evoc_damage} + INT mod).")
            if not any(a.get("name") == "Force Bolt" for a in actions):
                evoc_damage = f"1d4" if lvl < 10 else f"1d6" if lvl < 14 else f"1d8"
                actions.append({
                    "name": "Force Bolt",
                    "action_type": "reaction",
                    "damage": f"{evoc_damage}+{int_mod}",
                    "damage_type": "force",
                    "range": 60,
                    "description": f"Reaction: Ranged force attack, {evoc_damage}+{int_mod} force damage.",
                })
        
        elif school == "Illusion":
            if not any("Improved Minor Illusion" in f for f in features):
                features.append("Improved Minor Illusion: Cast an illusion cantrip when casting illusion spells.")
        
        elif school == "Necromancy":
            if not any("Undead Familiar" in f for f in features):
                features.append("Undead Familiar: Your familiar becomes undead (immune to poison, disease, exhaustion).")
            char["familiar_undead"] = True
        
        elif school == "Transmutation":
            if not any("Transmuter's Stone" in f for f in features):
                features.append(f"Transmuter's Stone: Gain {int_mod} temp HP when casting transmutation spells.")
    
    elif tier == "mastery" and lvl >= 6:
        if school == "General":
            if not any("Expanded Study" in f for f in features):
                features.append("Expanded Study: Learn another spell of each level (1st-5th).")
        
        elif school == "Abjuration":
            ward_hp = 2 * lvl + int_mod
            char["arcane_ward_hp"] = ward_hp
            if not any("Arcane Ward" in f for f in features):
                features.append(f"Arcane Ward: {ward_hp} HP shield that absorbs damage. Recharges when casting abjuration.")
        
        elif school == "Conjuration":
            if not any("Minor Conjuration" in f for f in features):
                features.append("Minor Conjuration: Create nonmagical objects up to 3 ft on a side.")
        
        elif school == "Divination":
            char["third_eye"] = True
            char["truesight"] = 60
            if not any("Third Eye" in f for f in features):
                features.append("Third Eye: Gain Truesight 60 ft.")
        
        elif school == "Enchantment":
            if not any("Split Enchantment" in f for f in features):
                features.append("Split Enchantment: Single-target enchantments can target 2 creatures.")
        
        elif school == "Evocation":
            if not any("Empowered Evocation" in f for f in features):
                features.append(f"Empowered Evocation: Add +{int_mod} to one evocation spell damage roll.")
        
        elif school == "Illusion":
            if not any("Malleable Illusions" in f for f in features):
                features.append("Malleable Illusions: Alter long-duration illusions as an action.")
        
        elif school == "Necromancy":
            char.setdefault("damage_resistances", [])
            if "necrotic" not in char["damage_resistances"]:
                char["damage_resistances"].append("necrotic")
            if not any("Grim Harvest" in f for f in features):
                features.append("Grim Harvest: Resist necrotic. HP max can't be reduced.")
        
        elif school == "Transmutation":
            if not any("Master Transmuter" in f for f in features):
                features.append("Master Transmuter: Permanent object transmutation (within limits).")


# ============== MARSHAL MANEUVERS ==============

MARSHAL_MANEUVERS = {
    "Covering Advance": {
        "type": "bonus",
        "effect": "ally_movement",
        "targets": "all_allies",
        "description": "Allies in aura move 10 ft without provoking OA."
    },
    "Strike in Formation": {
        "type": "reaction",
        "timing": "on_hit",
        "effect": "ally_attack",
        "targets": "single_ally",
        "description": "Ally makes reaction attack on your hit target. Add martial die to their damage."
    },
    "Banner of Defiance": {
        "type": "bonus",
        "effect": "temp_hp",
        "targets": "all_allies",
        "description": "Allies in aura gain temp HP = CHA mod + martial die."
    },
    "Shield the Line": {
        "type": "reaction",
        "timing": "ally_attacked",
        "effect": "attack_penalty",
        "targets": "single_ally",
        "description": "Impose -CHA mod penalty on attack vs ally in aura."
    },
    "Break the Line": {
        "type": "action",
        "effect": "charge_and_prone",
        "targets": "multiple_allies",
        "save": "STR",
        "description": "Allies move in straight line. Enemies adjacent at end must STR save or prone."
    },
    "Phalanx Reposition": {
        "type": "reaction",
        "timing": "enemy_approach",
        "effect": "ally_shift",
        "targets": "single_ally",
        "description": "When enemy moves near ally, shift ally 5 ft without provoking."
    },
    "Mobile Defense": {
        "type": "reaction",
        "timing": "ally_moves",
        "effect": "ac_bonus",
        "targets": "single_ally",
        "description": "Ally gains +martial die AC while moving."
    },
    "Suppressive Volley": {
        "type": "action",
        "effect": "no_reactions",
        "targets": "single_enemy",
        "save": "WIS",
        "description": "Target WIS save or can't take Reactions until next turn."
    },
    "Inspiring Rally": {
        "type": "bonus",
        "effect": "save_reroll",
        "targets": "single_ally",
        "description": "Ally can reroll a failed saving throw, adding martial die to the new roll."
    },
    "Coordinated Strike": {
        "type": "reaction",
        "timing": "ally_hits",
        "effect": "bonus_damage",
        "targets": "single_ally",
        "description": "When ally hits, add martial die to their damage."
    },
}

def _apply_marshal_maneuvers(char: dict, maneuvers: list, die_size: str, cha_mod: int, lvl: int, aura_range: int, actions: list):
    """Apply selected Marshal maneuvers as actions."""
    save_dc = 8 + cha_mod + (lvl // 2)
    
    for maneuver_name in maneuvers:
        maneuver_data = MARSHAL_MANEUVERS.get(maneuver_name)
        if not maneuver_data:
            continue
        
        action_name = f"Marshal: {maneuver_name}"
        if any(a.get("name") == action_name for a in actions):
            continue
        
        mtype = maneuver_data.get("type", "action")
        effect = maneuver_data.get("effect", "")
        targets = maneuver_data.get("targets", "single_ally")
        
        action_entry = {
            "name": action_name,
            "resource": "Martial Dice",
            "action_type": mtype,
            "effect": effect,
            "targets": targets,
            "aura_range": aura_range,
            "cha_mod": cha_mod,
            "damage": f"1{die_size}" if "damage" in effect or "temp_hp" in effect else None,
            "description": f"{maneuver_data['description']} (Uses 1 Martial Die, {die_size}). Range: {aura_range} ft.",
        }
        
        # Add save info if applicable
        if maneuver_data.get("save"):
            action_entry["save_type"] = maneuver_data["save"]
            action_entry["save_dc"] = save_dc
        
        # Add timing for reactions
        if maneuver_data.get("timing"):
            action_entry["timing"] = maneuver_data["timing"]
        
        actions.append(action_entry)
    
    # Store available maneuvers on character
    char["available_marshal_maneuvers"] = maneuvers


# ============== PALADIN DIVINE VOWS ==============

PALADIN_DIVINE_VOWS = {
    "Conservation": {
        "description": "Sworn to preserve the natural world and uphold the natural order.",
        "features": [
            "Lay on Hands heals plants and fey.",
            "Speak with Animals at will.",
            "Divine Smite works on aberrations.",
        ],
    },
    "Protection": {
        "description": "Sworn to safeguard others, especially the weak and vulnerable.",
        "features": [
            "Reaction: Reduce ally damage within 30 ft by CHA mod + level (uses Divine Smite).",
            "+1 AC bonus.",
            "Divine Smite works on any creature that harmed an ally in the last minute.",
        ],
    },
    "Devotion": {
        "description": "Sworn to purity, justice, and protection of the innocent.",
        "features": [
            "Bonus to saves vs Illusion and Enchantment.",
            "Resistance to necrotic damage.",
            "Divine Smite works on chaotic creatures.",
        ],
    },
    "Vengeance": {
        "description": "Sworn to retribution and swift justice against evildoers.",
        "features": [
            "+CHA mod to attack rolls against evil creatures.",
            "Heal CHA mod HP when killing an evil creature.",
            "Divine Smite works on any creature that harms you.",
        ],
    },
}

def _apply_paladin_divine_vow(char: dict, vow: str, cha_mod: int, lvl: int, spell_dc: int, features: list, actions: list):
    """Apply Divine Vow-specific features."""
    vow_data = PALADIN_DIVINE_VOWS.get(vow, {})
    
    if not any(f"Divine Vow: {vow}" in f for f in features):
        features[:] = [f for f in features if "Divine Vow:" not in f]
        features.append(f"Divine Vow: {vow} - {vow_data.get('description', '')}")
    
    # Apply vow-specific features
    for feature_text in vow_data.get("features", []):
        if not any(feature_text[:20] in f for f in features):
            features.append(f"  • {feature_text}")
    
    # Add vow-specific actions
    if vow == "Protection":
        if not any(a.get("name") == "Protective Intervention" for a in actions):
            actions.append({
                "name": "Protective Intervention",
                "action_type": "reaction",
                "resource": "Divine Smite",
                "description": f"Reaction: When ally within 30 ft is hit, reduce damage by {cha_mod + lvl}.",
            })
        char["ac_bonus"] = char.get("ac_bonus", 0) + 1
    
    elif vow == "Devotion":
        char.setdefault("damage_resistances", [])
        if "necrotic" not in char["damage_resistances"]:
            char["damage_resistances"].append("necrotic")
    
    elif vow == "Vengeance":
        char["vengeance_attack_bonus"] = cha_mod


# ============== BARBARIAN PRIMAL TALENTS ==============

BARBARIAN_PRIMAL_TALENTS = {
    "Savage Leap": {"description": "Long jump without running start. +2 attack after 10 ft jump toward target."},
    "Beast Strike": {"description": "While raging, Shove attempt as part of melee attack."},
    "Ferocious Tenacity": {"description": "1/day while raging, CON save (DC 10 + half damage) to drop to 1 HP instead of 0."},
    "Brutal Roar": {"description": "1/day, bonus action roar. Enemies within 10 ft WIS save or Frightened until end of next turn."},
    "Scent": {"description": "Detect creatures within 30 ft by smell. Know direction of hidden creatures."},
    "Resilient Hide": {"description": "While raging and unarmored, add CON mod to AC."},
    "Deadly Momentum": {"description": "On kill, move half speed and make one attack. 1/turn."},
    "Quick Temper": {"description": "Enter rage as immediate action CON mod times per day."},
    "Improved Beast Strike": {"prerequisite": "Beast Strike", "description": "Beast Strike can knock prone AND push 5 ft."},
    "Steel Gut": {"description": "Eat spoiled/toxic food safely. +CON mod to saves vs ingested poison."},
    "Wound Rend": {"description": "While raging, crits cause bleeding (CON mod damage/turn until healed)."},
    "Terrifying Glare": {"description": "1/day while raging, action to frighten one creature for 1 minute."},
    "Raging Vitality": {"description": "While raging, gain level temp HP at start of each turn."},
    "Grasping Strike": {"description": "While raging, bonus action grapple after melee hit."},
}

def _apply_barbarian_primal_talents(char: dict, talents: list, str_mod: int, con_mod: int, lvl: int, features: list, actions: list):
    """Apply selected Barbarian primal talents."""
    save_dc = 8 + str_mod + con_mod
    
    for talent_name in talents:
        talent_data = BARBARIAN_PRIMAL_TALENTS.get(talent_name)
        if not talent_data:
            continue
        
        feature_name = f"Primal Talent: {talent_name}"
        if any(feature_name in f for f in features):
            continue
        
        features.append(f"{feature_name}: {talent_data['description']}")
        
        # Add actions for certain talents
        if talent_name == "Brutal Roar":
            ensure_resource(char, "Brutal Roar", 1)
            if not any(a.get("name") == "Brutal Roar" for a in actions):
                actions.append({
                    "name": "Brutal Roar",
                    "resource": "Brutal Roar",
                    "action_type": "bonus",
                    "save_dc": save_dc,
                    "save_type": "WIS",
                    "description": f"Bonus Action (while raging): Enemies within 10 ft make WIS save (DC {save_dc}) or Frightened until end of next turn.",
                })
        
        elif talent_name == "Terrifying Glare":
            ensure_resource(char, "Terrifying Glare", 1)
            if not any(a.get("name") == "Terrifying Glare" for a in actions):
                actions.append({
                    "name": "Terrifying Glare",
                    "resource": "Terrifying Glare",
                    "action_type": "action",
                    "save_dc": save_dc,
                    "save_type": "WIS",
                    "description": f"Action (while raging): One creature within 30 ft makes WIS save (DC {save_dc}) or Frightened for 1 minute.",
                })
        
        elif talent_name == "Ferocious Tenacity":
            ensure_resource(char, "Ferocious Tenacity", 1)
        
        elif talent_name == "Quick Temper":
            ensure_resource(char, "Quick Temper", max(1, con_mod))


# ============== CLERIC DOMAINS ==============

CLERIC_DOMAINS = {
    "Life": {
        "description": "Healing and protection of the living.",
        "bonus_proficiencies": ["heavy armor"],
        "domain_spells": {1: ["Bless", "Cure Wounds"], 3: ["Lesser Restoration", "Spiritual Weapon"], 
                         5: ["Beacon of Hope", "Revivify"], 7: ["Death Ward", "Guardian of Faith"], 
                         9: ["Mass Cure Wounds", "Raise Dead"]},
    },
    "Light": {
        "description": "Radiance, fire, and banishing darkness.",
        "bonus_proficiencies": [],
        "domain_spells": {1: ["Burning Hands", "Faerie Fire"], 3: ["Flaming Sphere", "Scorching Ray"],
                         5: ["Daylight", "Fireball"], 7: ["Guardian of Faith", "Wall of Fire"],
                         9: ["Flame Strike", "Scrying"]},
    },
    "War": {
        "description": "Battle, conquest, and martial prowess.",
        "bonus_proficiencies": ["heavy armor", "martial weapons"],
        "domain_spells": {1: ["Divine Favor", "Shield of Faith"], 3: ["Magic Weapon", "Spiritual Weapon"],
                         5: ["Crusader's Mantle", "Spirit Guardians"], 7: ["Freedom of Movement", "Stoneskin"],
                         9: ["Flame Strike", "Hold Monster"]},
    },
    "Knowledge": {
        "description": "Learning, secrets, and understanding.",
        "bonus_proficiencies": [],
        "domain_spells": {1: ["Command", "Identify"], 3: ["Augury", "Suggestion"],
                         5: ["Nondetection", "Speak with Dead"], 7: ["Arcane Eye", "Confusion"],
                         9: ["Legend Lore", "Scrying"]},
    },
    "Death": {
        "description": "Necrotic power and command over the dead.",
        "bonus_proficiencies": ["martial weapons"],
        "domain_spells": {1: ["False Life", "Ray of Sickness"], 3: ["Blindness/Deafness", "Ray of Enfeeblement"],
                         5: ["Animate Dead", "Vampiric Touch"], 7: ["Blight", "Death Ward"],
                         9: ["Antilife Shell", "Cloudkill"]},
    },
    "Tempest": {
        "description": "Storms, thunder, and lightning.",
        "bonus_proficiencies": ["heavy armor", "martial weapons"],
        "domain_spells": {1: ["Fog Cloud", "Thunderwave"], 3: ["Gust of Wind", "Shatter"],
                         5: ["Call Lightning", "Sleet Storm"], 7: ["Control Water", "Ice Storm"],
                         9: ["Destructive Wave", "Insect Plague"]},
    },
    "Trickery": {
        "description": "Deception, stealth, and misdirection.",
        "bonus_proficiencies": [],
        "domain_spells": {1: ["Charm Person", "Disguise Self"], 3: ["Mirror Image", "Pass without Trace"],
                         5: ["Blink", "Dispel Magic"], 7: ["Dimension Door", "Polymorph"],
                         9: ["Dominate Person", "Modify Memory"]},
    },
    "Nature": {
        "description": "Plants, animals, and the natural world.",
        "bonus_proficiencies": ["heavy armor"],
        "domain_spells": {1: ["Animal Friendship", "Speak with Animals"], 3: ["Barkskin", "Spike Growth"],
                         5: ["Plant Growth", "Wind Wall"], 7: ["Dominate Beast", "Grasping Vine"],
                         9: ["Insect Plague", "Tree Stride"]},
    },
}

def _apply_cleric_domain_feature(char: dict, domain: str, lvl: int, wis_mod: int, spell_dc: int, features: list, actions: list):
    """Apply domain-specific features based on level."""
    domain_data = CLERIC_DOMAINS.get(domain, {})
    
    # Level 1: Domain feature
    if domain == "Life":
        if not any("Disciple of Life" in f for f in features):
            features.append("Disciple of Life: Healing spells heal extra 2 + spell level HP.")
    elif domain == "Light":
        if not any("Warding Flare" in f for f in features):
            features.append(f"Warding Flare: {max(1, wis_mod)}/day, reaction to impose -2 penalty on attacker within 30 ft.")
    elif domain == "War":
        if not any("War Priest" in f for f in features):
            features.append(f"War Priest: {max(1, wis_mod)}/day, bonus action weapon attack after Attack action.")
    elif domain == "Knowledge":
        if not any("Blessings of Knowledge" in f for f in features):
            features.append("Blessings of Knowledge: Proficiency in 2 skills from Arcana, History, Nature, Religion.")
    elif domain == "Death":
        if not any("Reaper" in f for f in features):
            features.append("Reaper: Necromancy cantrips can target 2 creatures within 5 ft of each other.")
    elif domain == "Tempest":
        if not any("Wrath of the Storm" in f for f in features):
            features.append(f"Wrath of the Storm: {max(1, wis_mod)}/day, reaction when hit: 2d8 lightning/thunder (DEX save DC {spell_dc} for half).")
    elif domain == "Trickery":
        if not any("Blessing of the Trickster" in f for f in features):
            features.append("Blessing of the Trickster: Touch ally to give +2 bonus on Stealth for 1 hour.")
    elif domain == "Nature":
        if not any("Acolyte of Nature" in f for f in features):
            features.append("Acolyte of Nature: Learn one druid cantrip. Proficiency in Animal Handling, Nature, or Survival.")
    
    # Level 2: Channel Divinity option
    if lvl >= 2:
        if domain == "Life":
            if not any(a.get("name") == "Preserve Life" for a in actions):
                actions.append({
                    "name": "Preserve Life",
                    "resource": "Channel Divinity",
                    "action_type": "action",
                    "description": f"Action: Heal creatures within 30 ft, dividing {5 * lvl} HP among them (max half their HP).",
                })
        elif domain == "Light":
            if not any(a.get("name") == "Radiance of the Dawn" for a in actions):
                actions.append({
                    "name": "Radiance of the Dawn",
                    "resource": "Channel Divinity",
                    "action_type": "action",
                    "damage": f"2d10+{lvl}",
                    "damage_type": "radiant",
                    "save_dc": spell_dc,
                    "save_type": "CON",
                    "description": f"Action: Dispel magical darkness. Hostiles within 30 ft take 2d10+{lvl} radiant (CON save DC {spell_dc} for half).",
                })
        elif domain == "War":
            if not any(a.get("name") == "Guided Strike" for a in actions):
                actions.append({
                    "name": "Guided Strike",
                    "resource": "Channel Divinity",
                    "action_type": "free",
                    "description": "On attack roll: Add +10 to the roll.",
                })
        elif domain == "Knowledge":
            if not any(a.get("name") == "Knowledge of the Ages" for a in actions):
                actions.append({
                    "name": "Knowledge of the Ages",
                    "resource": "Channel Divinity",
                    "action_type": "action",
                    "description": "Action: Gain proficiency in any skill or tool for 10 minutes.",
                })
        elif domain == "Death":
            if not any(a.get("name") == "Touch of Death" for a in actions):
                actions.append({
                    "name": "Touch of Death",
                    "resource": "Channel Divinity",
                    "action_type": "free",
                    "damage": f"{5 + 2 * lvl}",
                    "damage_type": "necrotic",
                    "description": f"On melee hit: Deal extra {5 + 2 * lvl} necrotic damage.",
                })
        elif domain == "Tempest":
            if not any(a.get("name") == "Destructive Wrath" for a in actions):
                actions.append({
                    "name": "Destructive Wrath",
                    "resource": "Channel Divinity",
                    "action_type": "free",
                    "description": "When rolling lightning/thunder damage: Maximize the damage instead of rolling.",
                })
        elif domain == "Trickery":
            if not any(a.get("name") == "Invoke Duplicity" for a in actions):
                actions.append({
                    "name": "Invoke Duplicity",
                    "resource": "Channel Divinity",
                    "action_type": "action",
                    "description": f"Action: Create illusory duplicate within 30 ft for 1 min. Cast spells as if in its space. Allies get +2 bonus vs enemies within 5 ft of both.",
                })
        elif domain == "Nature":
            if not any(a.get("name") == "Charm Animals and Plants" for a in actions):
                actions.append({
                    "name": "Charm Animals and Plants",
                    "resource": "Channel Divinity",
                    "action_type": "action",
                    "save_dc": spell_dc,
                    "save_type": "WIS",
                    "description": f"Action: Beasts and plants within 30 ft make WIS save (DC {spell_dc}) or be charmed for 1 minute.",
                })
    
    # Level 6: Domain feature
    if lvl >= 6:
        if domain == "Life":
            if not any("Blessed Healer" in f for f in features):
                features.append("Blessed Healer: When you cast healing spell on another, heal yourself 2 + spell level HP.")
        elif domain == "Light":
            if not any("Improved Flare" in f for f in features):
                features.append("Improved Flare: Can use Warding Flare to protect allies within 30 ft.")
        elif domain == "War":
            if not any(a.get("name") == "War God's Blessing" for a in actions):
                actions.append({
                    "name": "War God's Blessing",
                    "resource": "Channel Divinity",
                    "action_type": "reaction",
                    "description": "Reaction: When ally within 30 ft attacks, grant +10 to their attack roll.",
                })
        elif domain == "Death":
            if not any("Inescapable Destruction" in f for f in features):
                features.append("Inescapable Destruction: Your necrotic damage ignores resistance.")
    
    # Level 9: Domain feature
    if lvl >= 9:
        if domain == "Tempest":
            if not any("Thunderbolt Strike" in f for f in features):
                features.append("Thunderbolt Strike: When you deal lightning damage to Large or smaller, push them 10 ft.")


# ============== SORCERER BLOODLINES & METAMAGIC ==============

SORCERER_METAMAGIC = {
    "Quickened Spell": {"cost": 2, "description": "Cast a spell with casting time of 1 action as a bonus action instead."},
    "Twinned Spell": {"cost": "spell_level", "description": "Target a second creature with a single-target spell. Cost = spell level (1 SP for cantrips)."},
    "Empowered Spell": {"cost": 1, "description": "Reroll up to CHA mod damage dice. Must use new rolls."},
    "Subtle Spell": {"cost": 1, "description": "Cast without verbal or somatic components."},
    "Distant Spell": {"cost": 1, "description": "Double the range of a spell (touch becomes 30 ft)."},
    "Extended Spell": {"cost": 1, "description": "Double the duration of a spell (max 24 hours)."},
    "Heightened Spell": {"cost": 3, "description": "One target has -2 penalty on first save against the spell."},
    "Careful Spell": {"cost": 1, "description": "Choose CHA mod creatures to auto-succeed on the spell's save."},
}

def _apply_sorcerer_metamagic(char: dict, metamagic_list: list, actions: list):
    """Apply selected Sorcerer metamagic options."""
    for meta_name in metamagic_list:
        meta_data = SORCERER_METAMAGIC.get(meta_name)
        if not meta_data:
            continue
        
        action_name = f"Metamagic: {meta_name}"
        if any(a.get("name") == action_name for a in actions):
            continue
        
        cost = meta_data.get("cost", 1)
        cost_str = f"{cost} SP" if isinstance(cost, int) else "Spell level SP"
        
        actions.append({
            "name": action_name,
            "resource": "Sorcery Points",
            "action_type": "free",
            "description": f"{meta_data['description']} (Cost: {cost_str})",
        })

def _apply_sorcerer_bloodline_feature(char: dict, bloodline: str, lvl: int, tier: str, cha_mod: int, dragon_type: str, spell_dc: int, features: list, actions: list):
    """Apply bloodline-specific features based on tier."""
    
    if bloodline == "Dragon":
        if tier == "minor" and lvl >= 1:
            # Dragon damage type mapping
            dragon_damage = {
                "Red": "fire", "Gold": "fire", "Brass": "fire",
                "Blue": "lightning", "Bronze": "lightning",
                "Black": "acid", "Copper": "acid",
                "Green": "poison",
                "White": "cold", "Silver": "cold",
            }
            damage_type = dragon_damage.get(dragon_type, "fire")
            
            if not any("Dragon's Resilience" in f for f in features):
                features.append(f"Dragon's Resilience: Resistance to {damage_type} damage.")
            char.setdefault("damage_resistances", [])
            if damage_type not in char["damage_resistances"]:
                char["damage_resistances"].append(damage_type)
            char["dragon_damage_type"] = damage_type
        
        elif tier == "manifestation" and lvl >= 6:
            damage_type = char.get("dragon_damage_type", "fire")
            breath_damage = f"{(lvl // 4) + 2}d6"
            ensure_resource(char, "Dragon's Breath", 1)
            
            if not any("Dragon's Breath" in f for f in features):
                features.append(f"Dragon's Breath: 15-ft cone/line, {breath_damage} {damage_type}. 1/day or 1 SP.")
            
            if not any(a.get("name") == "Dragon's Breath" for a in actions):
                actions.append({
                    "name": "Dragon's Breath",
                    "resource": "Dragon's Breath",
                    "action_type": "action",
                    "damage": breath_damage,
                    "damage_type": damage_type,
                    "save_dc": spell_dc,
                    "save_type": "DEX",
                    "description": f"Action: 15-ft cone or line dealing {breath_damage} {damage_type} (DC {spell_dc} DEX save for half).",
                })
        
        elif tier == "greater" and lvl >= 10:
            ensure_resource(char, "Draconic Presence", 1)
            if not any("Draconic Presence" in f for f in features):
                features.append(f"Draconic Presence: 2 SP, 10-ft aura for 1 min. CHA save (DC {spell_dc}) or Frightened.")
            
            if not any(a.get("name") == "Draconic Presence" for a in actions):
                actions.append({
                    "name": "Draconic Presence",
                    "resource": "Sorcery Points",
                    "action_type": "action",
                    "save_dc": spell_dc,
                    "save_type": "CHA",
                    "description": f"Action (2 SP): 10-ft aura for 1 min. Creatures entering/starting must make CHA save (DC {spell_dc}) or be Frightened.",
                })
        
        elif tier == "form" and lvl >= 14:
            cr_limit = lvl // 2
            if not any("Bloodline Form" in f for f in features):
                features.append(f"Bloodline Form: Transform into your dragon type (CR ≤ {cr_limit}) for {lvl} minutes.")
            char["minor_bloodline_immunity"] = True  # Upgrade resistance to immunity
        
        elif tier == "awakening" and lvl >= 18:
            if not any("Scales" in f for f in features):
                features.append("Scales: +2 Natural Armor bonus to AC.")
            if not any("Piercing Element" in f for f in features):
                features.append("Piercing Element: Your dragon damage type ignores resistance, treats immunity as resistance.")
            char["natural_armor_bonus"] = char.get("natural_armor_bonus", 0) + 2
    
    elif bloodline == "Fey":
        if tier == "minor" and lvl >= 1:
            if not any("Fey Resilience" in f for f in features):
                features.append("Fey Resilience: +2 to saves vs Charmed/Frightened. Immunity at L14.")
            char["fey_resilience"] = True
        
        elif tier == "manifestation" and lvl >= 6:
            ensure_resource(char, "Fey Step & Briars", 1)
            if not any("Fey Step & Briars" in f for f in features):
                features.append("Fey Step & Briars: Bonus Action Misty Step + Entangle. 1/day or 1 SP.")
            
            if not any(a.get("name") == "Fey Step & Briars" for a in actions):
                actions.append({
                    "name": "Fey Step & Briars",
                    "resource": "Fey Step & Briars",
                    "action_type": "bonus",
                    "description": "Bonus Action: Cast Misty Step + Entangle centered on origin or destination. 1/day or 1 SP.",
                })
        
        elif tier == "greater" and lvl >= 10:
            if not any("Tongue Twister" in f for f in features):
                features.append(f"Tongue Twister: 2 SP, Counterspell as reaction. Target can't cast verbal spells until end of next turn.")
            if not any("Witch Strike" in f for f in features):
                features.append("Witch Strike: 1 SP, cast Witch Bolt on all cursed creatures within 60 ft.")
        
        elif tier == "form" and lvl >= 14:
            if not any("Bloodline Form" in f for f in features):
                features.append(f"Bloodline Form: Transform into humanoid fey (CR ≤ {lvl // 2}) for {lvl} minutes.")
            char.setdefault("condition_immunities", []).append("charmed") if "charmed" not in char.get("condition_immunities", []) else None
        
        elif tier == "awakening" and lvl >= 18:
            if not any("Fey Nature" in f for f in features):
                features.append("Fey Nature: Immune to Charmed. No longer age or require food/water.")
            if not any("Beguiling Gaze" in f for f in features):
                features.append(f"Beguiling Gaze: {max(1, cha_mod)}/day, cast enchantment/illusion subtly (no V/S, target must see you).")
    
    elif bloodline == "Fiendish":
        if tier == "minor" and lvl >= 1:
            if not any("Infernal Resistance" in f for f in features):
                features.append("Infernal Resistance: Resistance to fire damage. Immunity at L14.")
            char.setdefault("damage_resistances", [])
            if "fire" not in char["damage_resistances"]:
                char["damage_resistances"].append("fire")
        
        elif tier == "manifestation" and lvl >= 6:
            ensure_resource(char, "Hellfire Empowerment", 1)
            if not any("Hellfire Empowerment" in f for f in features):
                features.append("Hellfire Empowerment: Bonus Action, next spell attack deals +2d6 fire. 1/day or 1 SP.")
            
            if not any(a.get("name") == "Hellfire Empowerment" for a in actions):
                actions.append({
                    "name": "Hellfire Empowerment",
                    "resource": "Hellfire Empowerment",
                    "action_type": "bonus",
                    "description": "Bonus Action: Next spell attack deals +2d6 fire damage. 1/day or 1 SP.",
                })
        
        elif tier == "greater" and lvl >= 10:
            if not any("Infernal Saturation" in f for f in features):
                features.append(f"Infernal Saturation: Add +{cha_mod} to one fire/necrotic damage roll per spell.")
            if not any("Hell-Tainted Spell" in f for f in features):
                features.append("Hell-Tainted Spell: 1 SP, change spell's damage type to fire or necrotic.")
        
        elif tier == "form" and lvl >= 14:
            fiend_type = char.get("sorcerer_fiend_type", "Devil")
            if not any("Bloodline Form" in f for f in features):
                features.append(f"Bloodline Form: Transform into {fiend_type} (CR ≤ {lvl // 2}) for {lvl} minutes.")
            char.setdefault("damage_immunities", []).append("fire") if "fire" not in char.get("damage_immunities", []) else None
        
        elif tier == "awakening" and lvl >= 18:
            if not any("Infernal Legacy" in f for f in features):
                features.append("Infernal Legacy: Resistance to fire and necrotic. Spells count as magical and silvered.")
            if not any("Consume Essence" in f for f in features):
                features.append("Consume Essence: Regain 1 SP when you reduce a creature to 0 HP with a spell (1/turn).")
            char.setdefault("damage_resistances", [])
            if "necrotic" not in char["damage_resistances"]:
                char["damage_resistances"].append("necrotic")


# ============== FIGHTER MANEUVERS ==============

FIGHTER_MANEUVERS = {
    "Focused Strike": {
        "type": "attack_modifier",
        "timing": "before_attack",
        "effect": "to_hit_bonus",
        "description": "Add martial die to an attack roll."
    },
    "Ambusher's Edge": {
        "type": "utility",
        "timing": "check",
        "skills": ["Stealth", "Initiative"],
        "description": "Add martial die to Stealth or Initiative check."
    },
    "Guarded Step": {
        "type": "defensive",
        "timing": "action",
        "effect": "swap_and_ac",
        "description": "Switch places with ally within 5ft. One gains AC = martial die until next turn."
    },
    "Brace for Impact": {
        "type": "reaction",
        "timing": "enemy_approach",
        "effect": "opportunity_attack_bonus",
        "description": "When creature moves into reach, attack and add die to damage."
    },
    "Tactical Command": {
        "type": "bonus",
        "timing": "bonus_action",
        "effect": "ally_attack",
        "description": "Direct ally to attack using reaction. Add die to their damage."
    },
    "Forceful Disarm": {
        "type": "attack_modifier",
        "timing": "on_hit",
        "effect": "damage_and_disarm",
        "save": "STR",
        "description": "Add die to damage. Target drops item on failed STR save."
    },
    "Trip Technique": {
        "type": "attack_modifier",
        "timing": "on_hit",
        "effect": "damage_and_prone",
        "save": "STR",
        "description": "Add die to damage. Large or smaller creature prone on failed STR save."
    },
    "Distracting Blow": {
        "type": "attack_modifier",
        "timing": "on_hit",
        "effect": "damage_and_debuff",
        "description": "Add die to damage. Next attacker gains +2 vs target."
    },
    "Sweeping Motion": {
        "type": "attack_modifier",
        "timing": "on_hit",
        "effect": "cleave",
        "description": "On hit, deal martial die to another creature within 5ft if roll would hit."
    },
    "Lunging Attack": {
        "type": "attack_modifier",
        "timing": "before_attack",
        "effect": "reach_and_damage",
        "reach_bonus": 5,
        "description": "Extend reach 5ft for one attack. Add die to damage."
    },
    "Parry Response": {
        "type": "reaction",
        "timing": "when_hit_melee",
        "effect": "damage_reduction",
        "description": "When hit by melee, reduce damage by die + DEX mod."
    },
    "Riposte Counter": {
        "type": "reaction",
        "timing": "when_missed_melee",
        "effect": "counterattack",
        "description": "When missed by melee, make attack and add die to damage."
    },
    "Commanding Presence": {
        "type": "utility",
        "timing": "check",
        "skills": ["Intimidation", "Persuasion", "Performance"],
        "description": "Add martial die to Intimidation, Persuasion, or Performance."
    },
    "Rallying Shout": {
        "type": "bonus",
        "timing": "bonus_action",
        "effect": "temp_hp",
        "description": "Give ally temp HP = die + CHA mod."
    },
    "Tactical Insight": {
        "type": "utility",
        "timing": "check",
        "skills": ["History", "Investigation", "Insight"],
        "description": "Add martial die to History, Investigation, or Insight check."
    },
    "Grappling Strike": {
        "type": "attack_modifier",
        "timing": "on_hit",
        "effect": "grapple_bonus",
        "description": "After melee hit, add die to Athletics check to grapple target."
    },
    "Precision Attack": {
        "type": "attack_modifier",
        "timing": "after_roll",
        "effect": "reroll_to_hit",
        "description": "After missing, add martial die to the attack roll (may turn miss into hit)."
    },
    "Menacing Attack": {
        "type": "attack_modifier",
        "timing": "on_hit",
        "effect": "damage_and_frighten",
        "save": "WIS",
        "description": "Add die to damage. Target frightened on failed WIS save until end of next turn."
    },
    "Pushing Attack": {
        "type": "attack_modifier",
        "timing": "on_hit",
        "effect": "damage_and_push",
        "save": "STR",
        "push_distance": 15,
        "description": "Add die to damage. Large or smaller pushed 15ft on failed STR save."
    },
}

# ============== KNIGHT MANEUVERS ==============

KNIGHT_MANEUVERS = {
    "Stalwart Wall": {
        "type": "attack_modifier",
        "timing": "on_opportunity_attack",
        "effect": "prevent_movement",
        "description": "On opportunity attack hit, target can't move until start of their next turn."
    },
    "Shield Bash": {
        "type": "bonus",
        "timing": "after_melee_attack",
        "effect": "shove_and_damage",
        "save": "STR",
        "extra_damage": "1d6",
        "damage_type": "bludgeoning",
        "description": "Bonus action after melee attack: shove creature within 5ft, deal 1d6 bludgeoning. STR save or prone."
    },
    "Zone of Defense": {
        "type": "action",
        "timing": "action",
        "effect": "difficult_terrain_aura",
        "area": 10,
        "description": "10ft radius around you becomes difficult terrain. Enemies provoke OA when leaving until your next turn."
    },
    "Brace": {
        "type": "reaction",
        "timing": "enemy_approach",
        "effect": "opportunity_attack_bonus",
        "description": "When creature moves into reach, make attack and add martial die to damage."
    },
    "Commander's Strike": {
        "type": "bonus",
        "timing": "on_attack_action",
        "effect": "ally_attack",
        "description": "Forgo one attack. Ally uses reaction to attack, adding martial die to damage."
    },
    "Commanding Presence": {
        "type": "utility",
        "timing": "check",
        "skills": ["Intimidation", "Performance", "Persuasion"],
        "description": "Add martial die to Intimidation, Performance, or Persuasion check."
    },
    "Jousting Charge": {
        "type": "attack_modifier",
        "timing": "on_charge",
        "effect": "damage_and_prone",
        "save": "STR",
        "requires_mounted": True,
        "min_move": 20,
        "description": "While mounted, move 20ft+ and hit: add martial die to damage. STR save or prone."
    },
    "Spirited Leap": {
        "type": "free",
        "timing": "on_mount_jump",
        "effect": "avoid_opportunity_attacks",
        "requires_mounted": True,
        "description": "When mount jumps/moves over obstacle, you and mount avoid OA for the turn."
    },
    "Trample the Fallen": {
        "type": "free",
        "timing": "on_knock_prone",
        "effect": "mount_attack",
        "requires_mounted": True,
        "description": "When you knock a creature prone while mounted, mount makes hoof attack adding martial die."
    },
    "Goading Attack": {
        "type": "attack_modifier",
        "timing": "on_hit",
        "effect": "damage_and_goad",
        "save": "WIS",
        "description": "Add martial die to damage. WIS save or target has -2 penalty vs others until your next turn."
    },
    "Lunging Attack": {
        "type": "attack_modifier",
        "timing": "before_attack",
        "effect": "reach_and_damage",
        "reach_bonus": 5,
        "description": "Extend reach 5ft for one attack. Add martial die to damage."
    },
    "Maneuvering Attack": {
        "type": "attack_modifier",
        "timing": "on_hit",
        "effect": "damage_and_ally_move",
        "description": "Add martial die to damage. Ally can use reaction to move half speed without OA."
    },
    "Rally": {
        "type": "bonus",
        "timing": "bonus_action",
        "effect": "temp_hp",
        "description": "Give ally temp HP = martial die + CHA mod."
    },
    "Sweeping Attack": {
        "type": "attack_modifier",
        "timing": "on_hit",
        "effect": "cleave",
        "description": "On hit, deal martial die to another creature within 5ft if roll would hit."
    },
    "Tactical Assessment": {
        "type": "utility",
        "timing": "check",
        "skills": ["Investigation", "History", "Insight"],
        "description": "Add martial die to Investigation, History, or Insight check."
    },
}

def _apply_knight_maneuvers(char: dict, maneuvers: list, die_size: str, dc: int, actions: list):
    """Apply selected Knight maneuvers as actions."""
    for maneuver_name in maneuvers:
        maneuver_data = KNIGHT_MANEUVERS.get(maneuver_name)
        if not maneuver_data:
            continue
        
        action_name = f"Knight: {maneuver_name}"
        if any(a.get("name") == action_name for a in actions):
            continue
        
        mtype = maneuver_data.get("type", "attack_modifier")
        timing = maneuver_data.get("timing", "on_hit")
        effect = maneuver_data.get("effect", "damage")
        
        # Determine action type based on maneuver type
        if mtype == "reaction":
            action_type = "reaction"
        elif mtype == "bonus":
            action_type = "bonus"
        elif mtype == "attack_modifier":
            action_type = "free"  # Used as part of an attack
        elif mtype == "action":
            action_type = "action"
        else:
            action_type = "free"
        
        # Build the action entry
        action_entry = {
            "name": action_name,
            "resource": "Martial Dice",
            "action_type": action_type,
            "maneuver_type": mtype,
            "timing": timing,
            "effect": effect,
            "damage": f"1{die_size}",
            "description": f"{maneuver_data['description']} (Uses 1 Martial Die, {die_size})",
        }
        
        # Add save DC if applicable
        if maneuver_data.get("save"):
            action_entry["save_type"] = maneuver_data["save"]
            action_entry["save_dc"] = dc
        
        # Add reach bonus if applicable
        if maneuver_data.get("reach_bonus"):
            action_entry["reach_bonus"] = maneuver_data["reach_bonus"]
        
        # Mark if requires mounted
        if maneuver_data.get("requires_mounted"):
            action_entry["requires_mounted"] = True
            action_entry["description"] += " (Requires being mounted)"
        
        actions.append(action_entry)

def _apply_knight_challenge(char: dict, challenge_damage: int, actions: list):
    """Add Knight's Challenge action."""
    action_name = "Knight's Challenge"
    if any(a.get("name") == action_name for a in actions):
        return
    
    actions.append({
        "name": action_name,
        "action_type": "bonus",
        "resource": None,
        "damage_bonus": challenge_damage,
        "duration": "1 minute",
        "description": f"Bonus action: Challenge a creature within 30ft. Gain +{challenge_damage} damage, +2 on attacks, target has -2 on saves vs your abilities. Lasts 1 min or until target drops to 0 HP.",
    })

def _apply_fighter_maneuvers(char: dict, maneuvers: list, die_size: str, dc: int, actions: list):
    """Apply selected Fighter maneuvers as actions."""
    for maneuver_name in maneuvers:
        maneuver_data = FIGHTER_MANEUVERS.get(maneuver_name)
        if not maneuver_data:
            continue
        
        action_name = f"Maneuver: {maneuver_name}"
        if any(a.get("name") == action_name for a in actions):
            continue
        
        mtype = maneuver_data.get("type", "attack_modifier")
        timing = maneuver_data.get("timing", "on_hit")
        effect = maneuver_data.get("effect", "damage")
        
        # Determine action type based on maneuver type
        if mtype == "reaction":
            action_type = "reaction"
        elif mtype == "bonus":
            action_type = "bonus"
        elif mtype == "attack_modifier":
            action_type = "free"  # Used as part of an attack
        else:
            action_type = "action"
        
        # Build the action entry
        action_entry = {
            "name": action_name,
            "resource": "Martial Dice",
            "action_type": action_type,
            "maneuver_type": mtype,
            "timing": timing,
            "effect": effect,
            "damage": f"1{die_size}",
            "description": f"{maneuver_data['description']} (Uses 1 Martial Die, {die_size})",
        }
        
        # Add save DC if applicable
        if maneuver_data.get("save"):
            action_entry["save_type"] = maneuver_data["save"]
            action_entry["save_dc"] = dc
        
        # Add reach bonus for Lunging Attack
        if maneuver_data.get("reach_bonus"):
            action_entry["reach_bonus"] = maneuver_data["reach_bonus"]
        
        # Add push distance for Pushing Attack
        if maneuver_data.get("push_distance"):
            action_entry["push_distance"] = maneuver_data["push_distance"]
        
        actions.append(action_entry)
    
    # Store available maneuvers on character for attack integration
    char["available_maneuvers"] = maneuvers


def grant_fighting_style(char: dict, style_number: int = 1):
    """
    Grant a pending fighting style choice to a character.
    
    Args:
        char: Character dict
        style_number: Which fighting style this is (1 for first, 2 for second, etc.)
    """
    # Track how many fighting styles have been granted vs chosen
    granted_key = f"fighting_styles_granted"
    chosen_key = f"fighting_styles_chosen"
    
    styles_granted = char.get(granted_key, 0)
    styles_chosen = len([f for f in char.get("feats", []) if f.startswith("Fighting Style:")])
    
    # Only grant if this style number hasn't been granted yet
    if style_number > styles_granted:
        char[granted_key] = style_number
        # If they haven't chosen all granted styles, add pending
        pending_styles = style_number - styles_chosen
        if pending_styles > 0:
            char["pending_fighting_style"] = pending_styles


def add_level1_class_resources_and_actions(char: dict):
    """
    For now: handle Barbarian, Bard, and Artificer level 1.
    Sets up resource pools (Rage, Bardic Performance, Crafting Reservoir)
    and adds simple class actions that the UI can display/use.
    """
    cls_name = (char.get("class") or "").strip()
    abilities = char.get("abilities", {})
    features = char.setdefault("features", [])
    actions = char.setdefault("actions", [])

    # ---- Barbarian ----
    if cls_name == "Barbarian":
        con_mod = _ability_mod(abilities.get("CON", 10))
        str_mod = _ability_mod(abilities.get("STR", 10))
        lvl = int(char.get("level", 1))
        
        # Rage uses scale with level: 1 at L1, +1 at L4, L8, L12, L16, L20
        rage_uses = 1
        if lvl >= 20:
            rage_uses = 999  # Unlimited (Primal Champion)
        elif lvl >= 16:
            rage_uses = 6
        elif lvl >= 12:
            rage_uses = 5
        elif lvl >= 8:
            rage_uses = 4
        elif lvl >= 4:
            rage_uses = 3
        
        # Rage bonus scales: +2 at L1, +3 at L9 (Empowered Rage), +4 at L16 (Unstoppable Fury)
        rage_bonus = 2
        if lvl >= 16:
            rage_bonus = 4
        elif lvl >= 9:
            rage_bonus = 3
        
        ensure_resource(char, "Rage", rage_uses)
        char["rage_bonus"] = rage_bonus
        char["is_raging"] = char.get("is_raging", False)  # Track active rage state
        
        # Initialize Relentless Rage DC tracker
        if "relentless_rage_dc" not in char:
            char["relentless_rage_dc"] = 10
        
        rage_desc = (
            f"Rage (Ex): {rage_uses if rage_uses < 999 else 'Unlimited'}/day, 1 minute. "
            f"+{rage_bonus} STR/CON checks & saves, +{rage_bonus} WIS saves, "
            f"+{rage_bonus} melee damage, -2 AC, resist B/P/S. "
            f"Cannot use CHA/DEX/INT skills (except Balance, Escape Artist, Intimidate, Ride), cast spells, or concentrate."
        )
        if not any("Rage (Ex)" in f for f in features):
            features.append(rage_desc)
        
        if not any(a.get("name") == "Rage" for a in actions):
            actions.append({
                "name": "Rage",
                "resource": "Rage",
                "action_type": "bonus",
                "toggles": "is_raging",  # Flag to track active state
                "description": (
                    f"Bonus Action: Enter rage for 1 minute. "
                    f"+{rage_bonus} to STR/CON/WIS saves, +{rage_bonus} melee damage, -2 AC, resist B/P/S. "
                    f"Fatigued when rage ends (unless L11+)."
                ),
            })
        
        if not any(a.get("name") == "End Rage" for a in actions):
            actions.append({
                "name": "End Rage",
                "action_type": "free",
                "requires": "is_raging",
                "description": "Free Action: End your rage early.",
            })
        
        # Fast Movement (Level 1)
        if not any("Fast Movement" in f for f in features):
            features.append("Fast Movement (Ex): +10 ft speed while not wearing heavy armor.")
        char["barbarian_speed_bonus"] = 10
        
        # Illiteracy (Level 1)
        if "is_literate" not in char:
            char["is_literate"] = False  # Default illiterate
        if not any("Illiteracy" in f for f in features):
            if char.get("is_literate"):
                features.append("Illiteracy (Removed): You spent 2 skill points to learn to read and write.")
            else:
                features.append("Illiteracy: Cannot read/write unless you spend 2 skill points. Gain +1 skill point/level while illiterate.")
                char["illiteracy_skill_bonus"] = 1  # Extra skill point per level
        
        # Primal Awareness at level 2+
        if lvl >= 2:
            char["primal_awareness"] = True  # Keep DEX to AC vs unseen, cannot be surprised
            if not any("Primal Awareness" in f for f in features):
                features.append("Primal Awareness (Ex): Keep DEX bonus to AC even when flat-footed or vs invisible attackers. Cannot be surprised.")
        
        # Primal Talents and Enhanced Reflexes at level 3+
        if lvl >= 3:
            # Calculate talents known: 1 at L3, +1 at L5, L7, L9, etc.
            talents_known = 1 + ((lvl - 3) // 2)
            char["max_primal_talents"] = talents_known
            
            selected_talents = char.get("barbarian_primal_talents", [])
            if len(selected_talents) < talents_known:
                char["pending_primal_talents"] = talents_known - len(selected_talents)
            
            # Apply selected talents
            _apply_barbarian_primal_talents(char, selected_talents, str_mod, con_mod, lvl, features, actions)
            
            # Enhanced Reflexes (Level 3)
            char["enhanced_reflexes"] = True
            if not any("Enhanced Reflexes" in f for f in features):
                features.append(f"Enhanced Reflexes (Ex): Reaction when flat-footed/surprised: add +{con_mod} AC vs the triggering attack.")
            
            if not any(a.get("name") == "Enhanced Reflexes" for a in actions):
                actions.append({
                    "name": "Enhanced Reflexes",
                    "action_type": "reaction",
                    "description": f"Reaction: When caught flat-footed or surprised, add +{con_mod} to AC against the triggering attack.",
                })
        
        # Extra Attack and Primal Instinct at level 5+
        if lvl >= 5:
            char["extra_attack"] = 1
            if not any("Extra Attack" in f for f in features):
                features.append("Extra Attack: Attack twice when you take the Attack action.")
            
            # Primal Instinct (Level 5)
            char["primal_instinct"] = True
            char["rage_initiative_bonus"] = 2
            if not any("Primal Instinct" in f for f in features):
                features.append("Primal Instinct (Ex): +2 to Initiative while raging. Cannot be surprised while raging.")
        
        # Relentless Rage at level 6+
        if lvl >= 6:
            char["has_relentless_rage"] = True
            if not any("Relentless Rage" in f for f in features):
                features.append(
                    f"Relentless Rage (Ex): At 0 HP while raging, DC {char.get('relentless_rage_dc', 10)} CON save "
                    f"to drop to {2 * lvl} HP instead. DC +5 each use, resets after rest."
                )
        
        # Thick Skinned at level 7+
        if lvl >= 7:
            dr_amount = 1 + con_mod
            if lvl >= 19:
                dr_amount += 4
            elif lvl >= 16:
                dr_amount += 3
            elif lvl >= 13:
                dr_amount += 2
            elif lvl >= 10:
                dr_amount += 1
            
            char["rage_damage_reduction"] = dr_amount
            if not any("Thick Skinned" in f for f in features):
                features.append(f"Thick Skinned (Ex): While raging, DR {dr_amount}/- (reduce all damage by {dr_amount}).")
        
        # Empowered Rage at level 9+ (already handled in rage_bonus calculation)
        if lvl >= 9 and lvl < 16:
            if not any("Empowered Rage" in f for f in features):
                features.append("Empowered Rage (Ex): Rage bonus increased to +3.")
        
        # Relentless Rage (Improved) - No fatigue at level 11+
        if lvl >= 11:
            char["no_rage_fatigue"] = True
            if not any("No Fatigue" in f for f in features):
                features.append("Relentless Rage (Improved): No longer fatigued when rage ends.")
        
        # Endless Rage at level 14+
        if lvl >= 14:
            char["endless_rage"] = True
            if not any("Endless Rage" in f for f in features):
                features.append("Endless Rage (Ex): Rage only ends if you fall unconscious or choose to end it.")
        
        # Unstoppable Fury at level 16+
        if lvl >= 16:
            char["unstoppable_fury"] = True
            char["has_defy_death"] = True  # Once per rage, drop to 1 HP instead of 0
            char["has_relentless_assault"] = True  # Extra attack on kill
            char["has_unyielding_force"] = True  # Cannot be restrained while raging
            
            if not any("Unstoppable Fury" in f for f in features):
                features.append(
                    "Unstoppable Fury (Ex): Rage bonus +4. "
                    "Relentless Assault: Free melee attack on kill. "
                    "Defy Death: 1/rage, drop to 1 HP instead of 0 (gain exhaustion). "
                    "Unyielding Force: Cannot be restrained while raging."
                )
            
            if not any(a.get("name") == "Relentless Assault" for a in actions):
                actions.append({
                    "name": "Relentless Assault",
                    "action_type": "free",
                    "requires": "is_raging",
                    "triggers_on": "reduce_to_0",
                    "description": "Free Action: When you reduce a creature to 0 HP with a melee attack, immediately make another melee attack against a different creature within reach.",
                })
        
        # Primal Champion at level 20
        if lvl >= 20:
            char["primal_champion"] = True
            # Apply +4 to STR and CON (these are permanent bonuses)
            if not char.get("primal_champion_applied"):
                char["primal_champion_str_bonus"] = 4
                char["primal_champion_con_bonus"] = 4
                char["primal_champion_applied"] = True
            
            if not any("Primal Champion" in f for f in features):
                features.append(
                    "Primal Champion (Ex): +4 STR and CON (already applied). "
                    "Unlimited rages per day (must rest between rages)."
                )

    # ---- Bard ----
    elif cls_name == "Bard":
        cha_mod = _ability_mod(abilities.get("CHA", 10))
        lvl = int(char.get("level", 1))
        
        # Performance Die scaling
        if lvl >= 15:
            performance_die = "d12"
        elif lvl >= 10:
            performance_die = "d10"
        elif lvl >= 5:
            performance_die = "d8"
        else:
            performance_die = "d6"
        char["performance_die"] = performance_die
        
        # Bardic Performance uses: CHA mod + half level (min 1)
        uses = max(1, cha_mod + (lvl // 2))
        ensure_resource(char, "Bardic Performance", uses)
        
        # ---- Level 1: Spellcasting ----
        char["caster_type"] = "full"
        char["spellcasting_ability"] = "CHA"
        spell_dc = 8 + cha_mod
        char["spell_save_dc"] = spell_dc
        char["spell_attack_mod"] = cha_mod
        if not any("Spellcasting" in f for f in features):
            features.append(
                f"Spellcasting: Cast Bard spells using CHA. Spell Save DC = 8 + spell level + CHA mod ({spell_dc} + spell level). "
                f"Use a Musical Instrument as spellcasting focus."
            )
        
        # ---- Level 1: Bardic Knowledge ----
        knowledge_bonus = max(1, lvl // 2)
        char["bardic_knowledge"] = True
        char["bardic_knowledge_bonus"] = knowledge_bonus
        char["bardic_knowledge_all_int"] = lvl >= 6
        if not any("Bardic Knowledge" in f for f in features):
            if lvl >= 6:
                features.append(
                    f"Bardic Knowledge: +{knowledge_bonus} to all Knowledge checks AND all INT-based skill checks."
                )
            else:
                features.append(
                    f"Bardic Knowledge: +{knowledge_bonus} to all Knowledge skill checks."
                )
        
        # ---- Level 1: Bardic Performance ----
        if not any("Bardic Performance" in f for f in features):
            features.append(
                f"Bardic Performance ({performance_die}): Bonus Action, affects creatures within 30 ft. "
                f"Choose: Inspire Courage (allies +{performance_die} vs fear), "
                f"Soothing Melody (allies gain {cha_mod}+{performance_die} temp HP), "
                f"Inspire Greatness (1 ally +{performance_die} to attacks), or "
                f"Harmony of Despair (enemies -{cha_mod}+{performance_die} to charm/fear saves)."
            )
        
        if not any(a.get("name") == "Bardic Performance" for a in actions):
            actions.append({
                "name": "Bardic Performance",
                "action_type": "bonus",
                "resource": "Bardic Performance",
                "description": f"Begin a performance ({performance_die}) affecting creatures within 30 ft until start of next turn.",
            })
        
        # ---- Level 3: Sonic Conductor ----
        if lvl >= 3:
            char["sonic_conductor"] = True
            sonic_dc = 8 + cha_mod + (lvl // 2)
            char["sonic_conductor_dc"] = sonic_dc
            if not any("Sonic Conductor" in f for f in features):
                features.append(
                    f"Sonic Conductor (choose one, can switch on level up): "
                    f"Sonic Disruption (1/day, 20ft pulse, DC {sonic_dc} CON or {lvl} thunder damage + -2 Concentration), "
                    f"Reverberation (thunder spells +{cha_mod} damage while performing), or "
                    f"Soundwave Shield (L6+, reaction to reduce ally damage by {cha_mod} and -2 to attacker)."
                )
            ensure_resource(char, "Sonic Disruption", 1)
            if not any(a.get("name") == "Sonic Disruption" for a in actions):
                actions.append({
                    "name": "Sonic Disruption",
                    "action_type": "free",
                    "resource": "Sonic Disruption",
                    "description": f"When starting Bardic Performance, 20ft sonic pulse. DC {sonic_dc} CON or {lvl} thunder + -2 Concentration.",
                })
        
        # ---- Level 4: Inspire Magic ----
        if lvl >= 4:
            char["inspire_magic"] = True
            if not any("Inspire Magic" in f for f in features):
                features.append(
                    f"Inspire Magic: Reaction when ally within 30 ft casts a spell. Expend Bardic Performance, "
                    f"roll {performance_die} and add to spell attack or increase save DC."
                )
            if not any(a.get("name") == "Inspire Magic" for a in actions):
                actions.append({
                    "name": "Inspire Magic",
                    "action_type": "reaction",
                    "resource": "Bardic Performance",
                    "description": f"Add {performance_die} to ally's spell attack or save DC.",
                })
        
        # ---- Level 5: Charming Melody ----
        if lvl >= 5:
            char["charming_melody"] = True
            charm_bonus = min(cha_mod, lvl)
            char["charming_melody_bonus"] = charm_bonus
            if not any("Charming Melody" in f for f in features):
                features.append(
                    f"Charming Melody: While performing, charm spells get +{charm_bonus} to save DC."
                )
        
        # ---- Level 6: Magical Secrets ----
        if lvl >= 6:
            char["magical_secrets"] = True
            secrets_count = 2
            if lvl >= 18:
                secrets_count = 6
            elif lvl >= 12:
                secrets_count = 4
            char["magical_secrets_count"] = secrets_count
            if not any("Magical Secrets" in f for f in features):
                features.append(
                    f"Magical Secrets: Learn {secrets_count} spells from any arcane spell list (count as Bard spells)."
                )
        
        # ---- Level 7: Counterperformance ----
        if lvl >= 7:
            char["counterperformance"] = True
            if not any("Counterperformance" in f for f in features):
                features.append(
                    f"Counterperformance: Reaction when ally within 30 ft is affected by charm/fear/sonic. "
                    f"Expend Bardic Performance, roll {performance_die}+{cha_mod}. If >= effect DC, negate it."
                )
            if not any(a.get("name") == "Counterperformance" for a in actions):
                actions.append({
                    "name": "Counterperformance",
                    "action_type": "reaction",
                    "resource": "Bardic Performance",
                    "description": f"Negate charm/fear/sonic on ally if {performance_die}+{cha_mod} >= DC.",
                })
        
        # ---- Level 9: Echoing Song ----
        if lvl >= 9:
            char["echoing_song"] = True
            if not any("Echoing Song" in f for f in features):
                features.append(
                    "Echoing Song: After casting thunder/sonic spell, reaction to recast on same or different target "
                    "within 30 ft (expends another spell slot). Once per spell."
                )
            if not any(a.get("name") == "Echoing Song" for a in actions):
                actions.append({
                    "name": "Echoing Song",
                    "action_type": "reaction",
                    "description": "Recast thunder/sonic spell on target within 30 ft (costs spell slot).",
                })
        
        # ---- Level 10: Improved Bardic Performance ----
        if lvl >= 10:
            char["improved_bardic_performance"] = True
            if not any("Improved Bardic Performance" in f for f in features):
                features.append(
                    f"Improved Bardic Performance: Performance Die increases to {performance_die}."
                )
        
        # ---- Level 14: Bardic Mastery ----
        if lvl >= 14:
            char["bardic_mastery"] = True
            if not any("Bardic Mastery" in f for f in features):
                features.append(
                    "Bardic Mastery: Performances that target one ally now affect ALL allies within 30 ft."
                )
        
        # ---- Level 15: Melodic Resilience ----
        if lvl >= 15:
            char["melodic_resilience"] = True
            if not any("Melodic Resilience" in f for f in features):
                features.append(
                    "Melodic Resilience: While performing, charmed/frightened allies within range can use "
                    "their reaction to end the condition (expends a Bardic Performance use)."
                )
        
        # ---- Level 20: Final Flourish ----
        if lvl >= 20:
            char["final_flourish"] = True
            if not any("Final Flourish" in f for f in features):
                features.append(
                    "Final Flourish: Bardic Performance now affects all allies within 60 ft. "
                    f"Performance Die is {performance_die}."
                )

    # ---- Artificer ----
    elif cls_name == "Artificer":
        int_mod = _ability_mod(abilities.get("INT", 10))
        lvl = int(char.get("level", 1))
        
        # Crafting Points scale with level (from the class table)
        crafting_points_by_level = {
            1: 2, 2: 3, 3: 3, 4: 4, 5: 4, 6: 5, 7: 5, 8: 6, 9: 6, 10: 7,
            11: 7, 12: 8, 13: 8, 14: 9, 15: 9, 16: 10, 17: 10, 18: 11, 19: 11, 20: 12
        }
        base_cp = crafting_points_by_level.get(lvl, 2)
        
        # Crafting Reservoir max = 2 × INT mod (minimum 2)
        reservoir_max = max(2, 2 * int_mod)
        ensure_resource(char, "Crafting Reservoir", reservoir_max)
        ensure_resource(char, "Crafting Points", base_cp)
        
        # Calculate gadget uses (INT mod, minimum 1)
        gadget_uses = max(1, int_mod)
        ensure_resource(char, "Gadget Uses", gadget_uses)

        # ---- Level 1 Features ----
        if not any("Crafting Reservoir" in f for f in features):
            features.append(
                f"Crafting Reservoir: Pool of {reservoir_max} points (2 × INT mod, min 2) used to craft/repair/infuse items. Refills after rest."
            )

        if not any("Infused Tools" in f for f in features):
            features.append(
                "Infused Tools: Spend 1 hour during rest to infuse a mundane item. Costs 1-2 CP. "
                "Weapon: +1 attack/damage (2 CP). Armor: +1 DEX saves (2 CP). Tools: +2 skill check (1 CP)."
            )
        
        if not any("Field Mechanic" in f for f in features):
            features.append(
                "Field Mechanic: Use Tinker skill to stabilize dying creatures or repair constructs. "
                "Can craft basic gadgets during rest."
            )

        # ---- Level 1 Actions ----
        if not any(a.get("name") == "Infused Tools" for a in actions):
            actions.append({
                "name": "Infused Tools",
                "resource": "Crafting Reservoir",
                "cost": 2,
                "action_type": "rest",
                "description": (
                    "Rest Action: Spend Crafting Reservoir points to infuse a weapon (+1 attack/damage, 2 CP), "
                    "armor (+1 DEX saves, 2 CP), or tools (+2 skill check, 1 CP) for 8 hours."
                ),
            })
        
        # Field Mechanic Gadgets
        if not any(a.get("name") == "Flash Canister" for a in actions):
            actions.append({
                "name": "Flash Canister",
                "resource": "Gadget Uses",
                "cost": 1,
                "action_type": "bonus",
                "save_dc": 8 + int_mod,
                "save_type": "DEX",
                "effect": "blinded",
                "description": (
                    f"Bonus Action: Throw up to 30 ft. Each creature within 10 ft must succeed on a "
                    f"DC {8 + int_mod} DEX save or be blinded until the start of their next turn."
                ),
            })
        
        if not any(a.get("name") == "Smoke Vial" for a in actions):
            actions.append({
                "name": "Smoke Vial",
                "resource": "Gadget Uses",
                "cost": 1,
                "action_type": "bonus",
                "description": (
                    "Bonus Action: Create a 10-foot-radius lightly obscured smoke cloud lasting 1 minute or until dispersed."
                ),
            })
        
        # ---- Level 2+ Features ----
        if lvl >= 2:
            if not any("Quick Repair" in f for f in features):
                features.append(
                    f"Quick Repair: During short rest, repair a construct within 5 ft, restoring {lvl + int_mod} HP."
                )
            
            # Explosive Gadgets
            if not any("Explosive Gadgets" in f for f in features):
                features.append(
                    "Explosive Gadgets: Can craft explosive devices during rest (Fireburst Charge, Shrapnel Bomb, Smoke Bomb)."
                )
            
            if not any(a.get("name") == "Fireburst Charge" for a in actions):
                actions.append({
                    "name": "Fireburst Charge",
                    "resource": "Crafting Reservoir",
                    "cost": 2,
                    "action_type": "action",
                    "damage": "2d6",
                    "damage_type": "fire",
                    "save_dc": 8 + int_mod,
                    "save_type": "DEX",
                    "range": 10,
                    "description": (
                        f"Action: Throw at target. Creatures in 10-ft radius must make DC {8 + int_mod} DEX save "
                        f"or take 2d6 fire damage (half on success)."
                    ),
                })
            
            if not any(a.get("name") == "Shrapnel Bomb" for a in actions):
                actions.append({
                    "name": "Shrapnel Bomb",
                    "resource": "Crafting Reservoir",
                    "cost": 2,
                    "action_type": "action",
                    "damage": "2d6",
                    "damage_type": "piercing",
                    "save_dc": 8 + int_mod,
                    "save_type": "DEX",
                    "range": 10,
                    "description": (
                        f"Action: Throw at target. Creatures in 10-ft radius must make DC {8 + int_mod} DEX save "
                        f"or take 2d6 piercing damage (half on success)."
                    ),
                })
        
        # ---- Level 3: Signature Invention ----
        if lvl >= 3:
            if not any("Signature Invention" in f for f in features):
                features.append(
                    "Signature Invention: Choose one - Personal Suit of Armor (AC = 10 + INT mod), "
                    "Mechanical Servant (HP = level, AC = 12 + INT mod, 1d6 attack), or "
                    "Cannon Weapon (1d6 damage, 120 ft range, uses INT for attack)."
                )
            
            # Check if invention is selected
            invention = char.get("signature_invention")
            if invention == "armor":
                char["ac"] = max(char.get("ac", 10), 10 + int_mod)
                if not any(a.get("name") == "Armor Reaction" for a in actions):
                    actions.append({
                        "name": "Armor Reaction",
                        "action_type": "reaction",
                        "description": "Reaction: Reduce damage from one attack by INT mod + level.",
                    })
            elif invention == "servant":
                # Mechanical Servant stats stored separately - uses INT + BAB for attacks
                bab = int(char.get("bab", 0))
                servant_data = {
                    "name": "Mechanical Servant",
                    "hp": lvl,
                    "max_hp": lvl,
                    "ac": 12 + int_mod,
                    "speed_ft": 30,
                    "attacks": [{
                        "name": "Mechanical Limbs",
                        "to_hit": int_mod + bab,
                        "damage": "1d6",
                        "damage_type": "bludgeoning",
                        "reach": 5,
                    }],
                }
                # Update or create servant (recalculates stats each refresh)
                if "mechanical_servant" in char:
                    char["mechanical_servant"].update(servant_data)
                else:
                    char["mechanical_servant"] = servant_data
            elif invention == "cannon":
                # Add cannon as an attack option - uses INT + BAB for to_hit
                bab = int(char.get("bab", 0))
                cannon_attack = {
                    "name": "Artificer Cannon",
                    "to_hit": int_mod + bab,
                    "damage": "1d6" if lvl < 10 else "1d10",
                    "damage_type": char.get("cannon_damage_type", "force"),
                    "range": 120,
                    "attack_type": "ranged",
                    "uses_int": True,
                }
                # Update or add cannon attack (recalculates to_hit each refresh)
                existing_cannon = next((a for a in char.get("attacks", []) if a.get("name") == "Artificer Cannon"), None)
                if existing_cannon:
                    existing_cannon.update(cannon_attack)
                else:
                    char.setdefault("attacks", []).append(cannon_attack)
        
        # ---- Level 4: Crafting Expertise ----
        if lvl >= 4:
            char["crafting_expertise"] = True
            expertise_bonus = 2 if lvl < 12 else 4
            char["crafting_expertise_bonus"] = expertise_bonus
            if not any("Crafting Expertise" in f for f in features):
                features.append(
                    f"Crafting Expertise: +{expertise_bonus} to all crafting and Tinker checks. "
                    f"Can identify magical items by examining them for 1 minute."
                )
        
        # ---- Level 5: Efficiency in Creation ----
        if lvl >= 5:
            char["efficiency_in_creation"] = True
            if not any("Efficiency in Creation" in f for f in features):
                features.append(
                    "Efficiency in Creation: Infusions cost 1 less CP (min 1). Crafting time halved. "
                    "Can maintain one additional infusion active at a time."
                )
        
        # ---- Level 6: Enhanced Explosives ----
        if lvl >= 6:
            char["enhanced_explosives"] = True
            if not any("Enhanced Explosives" in f for f in features):
                features.append(
                    f"Enhanced Explosives: Explosive gadgets deal +{int_mod} damage. "
                    f"Can delay detonation up to 1 minute. Radius increases by 5 ft."
                )
        
        # ---- Level 7: Improved Gadgets ----
        if lvl >= 7:
            char["improved_gadgets"] = True
            if not any("Improved Gadgets" in f for f in features):
                features.append(
                    f"Improved Gadgets: Gadget save DCs increase to {10 + int_mod}. "
                    f"Explosive gadgets deal an extra 1d6 damage."
                )
        
        # ---- Level 8: Modular Upgrade ----
        if lvl >= 8:
            char["modular_upgrade"] = True
            modular_slots = 1 if lvl < 16 else 2
            char["modular_upgrade_slots"] = modular_slots
            if not any("Modular Upgrade" in f for f in features):
                features.append(
                    f"Modular Upgrade ({modular_slots} slot{'s' if modular_slots > 1 else ''}): "
                    f"Add upgrades to your Signature Invention. Options: Enhanced Durability (+5 HP/+1 AC), "
                    f"Integrated Weapon (+1d4 damage), Swift Module (+10 ft speed), Stealth Plating (+2 on Stealth)."
                )
        
        # ---- Level 9: Invention Upgrade ----
        if lvl >= 9:
            char["invention_upgrade"] = True
            if not any("Invention Upgrade" in f for f in features):
                features.append(
                    "Invention Upgrade: Your Signature Invention gains a minor upgrade. "
                    "Armor: +1 AC. Servant: +5 HP, +1 to hit. Cannon: +1 damage die size (d8)."
                )
        
        # ---- Level 10: Masterwork Invention ----
        if lvl >= 10:
            char["has_masterwork_invention"] = True
            if not any("Masterwork Invention" in f for f in features):
                features.append(
                    "Masterwork Invention: Your Signature Invention improves. "
                    "Armor: DR 3/-, +2 AC. Servant: +10 HP, multiattack, fly 30 ft. "
                    "Cannon: 1d10 damage, choose damage type, 10 ft AoE option."
                )
            
            # Apply masterwork upgrades based on invention type
            invention = char.get("signature_invention")
            if invention == "armor":
                char["masterwork_armor_dr"] = 3
                char["masterwork_armor_ac_bonus"] = 2
            elif invention == "servant":
                if "mechanical_servant" in char:
                    char["mechanical_servant"]["max_hp"] = lvl + 10
                    char["mechanical_servant"]["hp"] = min(char["mechanical_servant"].get("hp", lvl), lvl + 10)
                    char["mechanical_servant"]["fly_speed"] = 30
                    char["mechanical_servant"]["multiattack"] = True
            elif invention == "cannon":
                # Cannon damage already upgraded to 1d10 at level 10 in the cannon creation code
                char["cannon_aoe_option"] = True
        
        # ---- Level 11: Reactive Adaptation ----
        if lvl >= 11:
            char["reactive_adaptation"] = True
            ensure_resource(char, "Reactive Adaptation", 1)
            if not any("Reactive Adaptation" in f for f in features):
                features.append(
                    "Reactive Adaptation (1/short rest): Reaction when you or ally within 30 ft takes damage, "
                    "grant resistance to that damage type until end of next turn."
                )
            
            if not any(a.get("name") == "Reactive Adaptation" for a in actions):
                actions.append({
                    "name": "Reactive Adaptation",
                    "action_type": "reaction",
                    "resource": "Reactive Adaptation",
                    "description": "Reaction: When you or ally within 30 ft takes damage, grant resistance to that damage type until end of next turn.",
                })
        
        # ---- Level 12: Master Explosive Tinkerer ----
        if lvl >= 12:
            char["master_explosive_tinkerer"] = True
            if not any("Master Explosive Tinkerer" in f for f in features):
                features.append(
                    f"Master Explosive Tinkerer: Explosive gadgets deal +{int_mod} damage and have +5 ft radius. "
                    f"Can craft 2 explosives during a short rest. Explosives ignore resistance to their damage type."
                )
        
        # ---- Level 13: Emergency Deployment Systems ----
        if lvl >= 13:
            char["emergency_deployment"] = True
            if not any("Emergency Deployment Systems" in f for f in features):
                features.append(
                    "Emergency Deployment Systems: Deploy gadgets as a reaction when you or ally is attacked. "
                    "Once per round, use a gadget without spending Gadget Uses when below half HP."
                )
            
            if not any(a.get("name") == "Emergency Deploy" for a in actions):
                actions.append({
                    "name": "Emergency Deploy",
                    "action_type": "reaction",
                    "description": "Reaction: Deploy a gadget when you or ally within 30 ft is attacked. Free gadget use when below half HP (1/round).",
                })
        
        # ---- Level 14: Master Artificer ----
        if lvl >= 14:
            char["master_artificer"] = True
            if not any("Master Artificer" in f for f in features):
                features.append(
                    f"Master Artificer: +{int_mod} to all Tinker checks. Can craft magic items up to Rare. "
                    f"Infusions last 24 hours instead of 8."
                )
        
        # ---- Level 15: Grandmaster Crafter ----
        if lvl >= 15:
            char["grandmaster_crafter"] = True
            if not any("Grandmaster Crafter" in f for f in features):
                features.append(
                    "Grandmaster Crafter: Craft uncommon magic items (5 CP, 1 week) or rare magic items (10 CP, 2 weeks). "
                    "Create up to 2 magical items per long rest. Infuse mundane items with 1st-level spell effects (1 CP, 24 hours)."
                )
        
        # ---- Level 16: Legendary Gadgeteer ----
        if lvl >= 16:
            char["legendary_gadgeteer"] = True
            if not any("Legendary Gadgeteer" in f for f in features):
                features.append(
                    "Legendary Gadgeteer: Prepare one Legendary Gadget per long rest (2 CP): "
                    "Mega Explosion (5d6 fire, 20ft, no save), Cluster Bomb (3×2d6 piercing, 10ft each), "
                    "or Blanket of Smoke (30ft heavy obscurement, 10 min)."
                )
            ensure_resource(char, "Legendary Gadget", 1)
            # Add Legendary Gadget action
            if not any(a.get("name") == "Deploy Legendary Gadget" for a in actions):
                actions.append({
                    "name": "Deploy Legendary Gadget",
                    "action_type": "standard",
                    "description": "Deploy your prepared Legendary Gadget: Mega Explosion (5d6 fire, 20ft, no save), "
                                   "Cluster Bomb (3×2d6 piercing, 10ft each), or Blanket of Smoke (30ft, 10 min).",
                })
        
        # ---- Level 17: Supreme Innovation ----
        if lvl >= 17:
            char["supreme_innovation"] = True
            if not any("Supreme Innovation" in f for f in features):
                features.append(
                    "Supreme Innovation: Your crafted items and Signature Invention are immune to non-magical damage. "
                    "They cannot be disassembled, dismantled, suppressed, or disabled by any non-magical means. "
                    "Mechanical Servant also benefits from this immunity."
                )
        
        # ---- Level 18: Legendary Item Crafting ----
        if lvl >= 18:
            char["legendary_item_crafting"] = True
            if not any("Legendary Item Crafting" in f for f in features):
                features.append(
                    "Legendary Item Crafting: Craft one Legendary Item (DM approval). Requires 1 week downtime, "
                    "5000 gp per power level, and 10 CP. Item is permanent but cannot be replicated. "
                    "Only one Legendary Item may be crafted per year (in-game time)."
                )
        
        # ---- Level 19: Peerless Engineer ----
        if lvl >= 19:
            char["peerless_engineer"] = True
            if not any("Peerless Engineer" in f for f in features):
                features.append(
                    f"Peerless Engineer: You cannot roll below 10 on Tinker or crafting checks. "
                    f"Gadgets regain all uses on short rest. Crafting Reservoir regains {int_mod} points on short rest."
                )
        
        # ---- Level 20: Grand Masterpiece ----
        if lvl >= 20:
            char["grand_masterpiece"] = True
            if not any("Grand Masterpiece" in f for f in features):
                features.append(
                    "Grand Masterpiece: Create one singular, unique masterpiece (choose one): "
                    "The Perfect Weapon (1d12 damage, choose type, ignores resistance/immunity, indestructible), "
                    "The Ultimate Armor (+3 AC, immune to 2 damage types, attune 3 extra items), or "
                    "The Grand Servant (Iron Golem stats, sentient, free will, own initiative)."
                )
            # Double reservoir as part of capstone
            reservoir_max = max(4, 4 * int_mod)
            char["resources"]["Crafting Reservoir"]["max"] = reservoir_max
        
        # Mark as non-caster (uses Crafting Points, not spell slots)
        char["caster_type"] = "artificer"  # Special marker for non-standard casting

    # ---- Fighter ----
    elif cls_name == "Fighter":
        lvl = int(char.get("level", 1))
        str_mod = _ability_mod(abilities.get("STR", 10))
        dex_mod = _ability_mod(abilities.get("DEX", 10))
        bab = int(char.get("bab", 0))
        maneuver_dc = 8 + max(str_mod, dex_mod) + bab
        
        # Try JSON-based features first
        if apply_class_features_from_json(char, "Fighter", lvl, features, actions):
            # JSON features applied successfully
            # Still need to apply maneuvers from selection (JSON doesn't handle this yet)
            char["maneuver_dc"] = maneuver_dc  # Ensure DC is set
            selected_maneuvers = char.get("fighter_maneuvers", [])
            die_size = char.get("martial_dice_die_size", "d6")
            _apply_fighter_maneuvers(char, selected_maneuvers, die_size, maneuver_dc, actions)
            grant_fighting_style(char, 1)
            # Skip the rest of the hardcoded Fighter section
            pass
        else:
            # Fallback to hardcoded features if JSON not available
            # Martial Dice pool - starts at 4d6, increases at 7, 9, and 15
            martial_dice_count = 4
            if lvl >= 15:
                martial_dice_count = 6
            elif lvl >= 9:
                martial_dice_count = 6  # Master Combatant adds 2
            elif lvl >= 7:
                martial_dice_count = 5
            
            ensure_resource(char, "Martial Dice", martial_dice_count)
            
            # Martial die size scales
            if lvl >= 15:
                die_size = "d12"
            elif lvl >= 11:
                die_size = "d10"
            elif lvl >= 7:
                die_size = "d8"
            else:
                die_size = "d6"
            
            char["martial_die_size"] = die_size
            char["maneuver_dc"] = maneuver_dc
            
            # Maneuvers known: 3 at L1, +2 at L3, L7, L15
            maneuvers_known = 3
            if lvl >= 3:
                maneuvers_known = 5
            if lvl >= 7:
                maneuvers_known = 7
            if lvl >= 15:
                maneuvers_known = 9
            
            char["max_maneuvers_known"] = maneuvers_known
            
            if not any("Combat Maneuvers" in f for f in features):
                features.append(f"Combat Maneuvers: {martial_dice_count} Martial Dice ({die_size}). {maneuvers_known} maneuvers known. DC {maneuver_dc}.")
            
            # Check if we need to select maneuvers
            selected_maneuvers = char.get("fighter_maneuvers", [])
            if len(selected_maneuvers) < maneuvers_known:
                char["pending_maneuvers"] = maneuvers_known - len(selected_maneuvers)
            
            # Apply selected maneuvers as actions
            _apply_fighter_maneuvers(char, selected_maneuvers, die_size, maneuver_dc, actions)
            
            # Fighting Style at level 1
            if not any("Fighting Style" in f for f in features):
                features.append("Fighting Style: Gain a Fighting Style feat of your choice.")
            grant_fighting_style(char, 1)
            
            # Action Surge at level 2+
            if lvl >= 2:
                action_surge_uses = 2 if lvl >= 17 else 1
                ensure_resource(char, "Action Surge", action_surge_uses)
                if not any("Action Surge" in f for f in features):
                    features.append(f"Action Surge: Take one additional action on your turn. {action_surge_uses} use(s) per rest.")
                if not any(a.get("name") == "Action Surge" for a in actions):
                    actions.append({
                        "name": "Action Surge",
                        "resource": "Action Surge",
                        "action_type": "free",
                        "grants_action": "standard",  # Special flag for action economy
                        "description": "Free Action: Regain your Standard action this turn. Can attack again with full Extra Attack.",
                    })
            
            # Extra Attack at level 5+
            if lvl >= 5:
                extra_attacks = 1
                if lvl >= 20:
                    extra_attacks = 3  # 4 total attacks
                elif lvl >= 11:
                    extra_attacks = 2  # 3 total attacks
                
                char["extra_attack"] = extra_attacks
                if not any("Extra Attack" in f for f in features):
                    total_attacks = extra_attacks + 1
                    features.append(f"Extra Attack: Attack {total_attacks} times when you take the Attack action.")
            
            # Weapon Expertise at level 6+
            if lvl >= 6:
                expertise_weapon = char.get("weapon_expertise")
                if expertise_weapon:
                    if not any("Weapon Expertise" in f for f in features):
                        features.append(f"Weapon Expertise ({expertise_weapon}): +1 to attack rolls with {expertise_weapon}. Reroll 1s on damage dice.")
                    char["weapon_expertise_bonus"] = {
                        "weapon": expertise_weapon,
                        "attack_bonus": 1,
                        "reroll_ones": True
                    }
                else:
                    char["pending_weapon_expertise"] = True
                    if not any("Weapon Expertise" in f for f in features):
                        features.append("Weapon Expertise: ⚠️ Choose one weapon for expertise! (Pending selection)")
            
            # Tactical Movement at level 7+
            if lvl >= 7:
                if not any("Tactical Movement" in f for f in features):
                    features.append("Tactical Movement: Dash through enemy squares. Reaction: Impose -2 to attack vs ally within 10ft.")
                
                # Add the reaction action
                if not any(a.get("name") == "Tactical Cover" for a in actions):
                    actions.append({
                        "name": "Tactical Cover",
                        "action_type": "reaction",
                        "description": "Reaction: When an ally within 10ft is attacked, impose -2 penalty on the attack roll.",
                    })
            
            # Master Combatant at level 9+
            if lvl >= 9:
                char["master_combatant"] = True  # Flag for die recovery mechanic
                if not any("Master Combatant" in f for f in features):
                    features.append("Master Combatant: +2 martial dice (included). Regain 1 martial die when maneuver roll is 5+.")
            
            # Indomitable at level 12+
            if lvl >= 12:
                ensure_resource(char, "Indomitable", 1)
                if not any("Indomitable" in f for f in features):
                    features.append("Indomitable: Reroll a failed saving throw once per day.")
                if not any(a.get("name") == "Indomitable" for a in actions):
                    actions.append({
                        "name": "Indomitable",
                        "resource": "Indomitable",
                        "action_type": "free",
                        "description": "Reroll a failed saving throw. Must use the new roll.",
                    })
            
            # Master of Weaponry at level 13+
            if lvl >= 13:
                expertise_weapon = char.get("weapon_expertise", "chosen weapon")
                char["master_of_weaponry"] = True
                if not any("Master of Weaponry" in f for f in features):
                    features.append(f"Master of Weaponry ({expertise_weapon}): +2 damage with {expertise_weapon}. +1d6 on critical hits.")
                # Update weapon expertise bonus
                if "weapon_expertise_bonus" in char:
                    char["weapon_expertise_bonus"]["damage_bonus"] = 2
                    char["weapon_expertise_bonus"]["crit_bonus"] = "1d6"
            
            # Indomitable Will at level 15+
            if lvl >= 15:
                if not any("Indomitable Will" in f for f in features):
                    features.append("Indomitable Will: Reroll failed WIS and CHA saves once per attempt.")
            
            # Relentless at level 16+
            if lvl >= 16:
                char["has_relentless"] = True  # Flag checked when rolling initiative
                if not any("Relentless" in f for f in features):
                    features.append("Relentless: Regain 1 martial die when rolling initiative with none remaining.")
            
            # Avatar of War at level 18+
            if lvl >= 18:
                ensure_resource(char, "Avatar of War", 1)
                char["has_avatar_of_war"] = True  # Flag checked when dropping to 0 HP
                if not any("Avatar of War" in f for f in features):
                    features.append("Avatar of War (1/day): When dropped to 0 HP, drop to 1 HP instead. +2 attack until end of next turn.")
                
                if not any(a.get("name") == "Avatar of War" for a in actions):
                    actions.append({
                        "name": "Avatar of War",
                        "resource": "Avatar of War",
                        "action_type": "free",
                        "triggers_on": "drop_to_0_hp",
                        "description": "When dropped to 0 HP: Instead drop to 1 HP and gain +2 to attack rolls until end of your next turn.",
                    })
            
            # Unmatched Combatant at level 20
            if lvl >= 20:
                ensure_resource(char, "Unmatched Combatant", 1)
                char["has_unmatched_combatant"] = True
                if not any("Unmatched Combatant" in f for f in features):
                    features.append("Unmatched Combatant: 4 attacks per Attack action. Once/day: Reroll any attack, save, or damage roll.")
                
                if not any(a.get("name") == "Unmatched Combatant Reroll" for a in actions):
                    actions.append({
                        "name": "Unmatched Combatant Reroll",
                        "resource": "Unmatched Combatant",
                        "action_type": "free",
                        "description": "Once per day: Reroll any attack roll, saving throw, or damage roll. Must use the new result.",
                    })
    
    # ---- Cleric ----
    elif cls_name == "Cleric":
        wis_mod = _ability_mod(abilities.get("WIS", 10))
        lvl = int(char.get("level", 1))
        spell_dc = 8 + wis_mod + lvl
        
        if not any("Spellcasting" in f for f in features):
            features.append(f"Spellcasting: Wisdom-based divine caster. Spell Save DC = {spell_dc}.")
        
        # --- Divine Domain (Level 1) ---
        domain = char.get("cleric_domain")
        if domain:
            if not any(f"Divine Domain: {domain}" in f for f in features):
                features[:] = [f for f in features if "Divine Domain:" not in f]
                features.append(f"Divine Domain: {domain} - Grants bonus spells and features.")
            
            # Apply domain features
            _apply_cleric_domain_feature(char, domain, lvl, wis_mod, spell_dc, features, actions)
        else:
            if not any("Divine Domain" in f for f in features):
                features.append("Divine Domain: Choose a domain that grants bonus spells and features.")
        
        # Channel Divinity at level 2+
        if lvl >= 2:
            channel_uses = 1
            if lvl >= 18:
                channel_uses = 3
            elif lvl >= 6:
                channel_uses = 2
            
            ensure_resource(char, "Channel Divinity", channel_uses)
            if not any("Channel Divinity" in f for f in features):
                features.append(f"Channel Divinity: {channel_uses} use(s). Invoke divine power for Turn Undead or domain feature.")
            if not any(a.get("name") == "Turn Undead" for a in actions):
                actions.append({
                    "name": "Turn Undead",
                    "resource": "Channel Divinity",
                    "action_type": "action",
                    "save_dc": spell_dc,
                    "save_type": "WIS",
                    "description": f"Action: Undead within 30 ft must make DC {spell_dc} WIS save or be turned for 1 minute.",
                })
        
        # Sacred Writ at level 5+
        if lvl >= 5:
            sacred_writ_uses = max(1, wis_mod)
            ensure_resource(char, "Sacred Writ", sacred_writ_uses)
            if not any("Sacred Writ" in f for f in features):
                features.append(f"Sacred Writ: {sacred_writ_uses}/day, reaction to let creature reroll save vs spell/magic.")
        
        # Sanctified Blows at level 7+
        if lvl >= 7:
            sanctified_choice = char.get("cleric_sanctified", "divine_strike")
            extra_dice = "2d8" if lvl >= 14 else "1d8"
            
            if sanctified_choice == "divine_strike":
                if not any("Divine Strike" in f for f in features):
                    features.append(f"Divine Strike: Once per turn on weapon hit, +{extra_dice} Necrotic or Radiant damage.")
            else:
                if not any("Potent Spellcasting" in f for f in features):
                    features.append(f"Potent Spellcasting: Add +{wis_mod} to Cleric cantrip damage.")
        
        # Divine Intervention at level 10+
        if lvl >= 10:
            ensure_resource(char, "Divine Intervention", 1)
            if not any("Divine Intervention" in f for f in features):
                features.append("Divine Intervention: Once/day, cast any Cleric spell ≤5th level without slot or components.")
            if not any(a.get("name") == "Divine Intervention" for a in actions):
                actions.append({
                    "name": "Divine Intervention",
                    "resource": "Divine Intervention",
                    "action_type": "action",
                    "description": "Action: Cast any Cleric spell of 5th level or lower without slot or material components.",
                })
        
        # Living Conduit at level 15+
        if lvl >= 15:
            ensure_resource(char, "Living Conduit", 1)
            if not any("Living Conduit" in f for f in features):
                features.append("Living Conduit: Once/day when reduced to 0 HP, stay conscious for 1 round.")
        
        # Greater Divine Intervention at level 20
        if lvl >= 20:
            if not any("Greater Divine Intervention" in f for f in features):
                features.append("Greater Divine Intervention: Can choose Wish with Divine Intervention (2d4 long rests cooldown).")
    
    # ---- Druid ----
    elif cls_name == "Druid":
        wis_mod = _ability_mod(abilities.get("WIS", 10))
        lvl = int(char.get("level", 1))
        spell_dc = 8 + wis_mod + lvl
        prepared_spells = max(1, wis_mod + lvl)
        
        if not any("Druidic" in f for f in features):
            features.append("Druidic: You know the secret language of druids.")
        
        if not any("Spellcasting" in f for f in features):
            features.append(f"Spellcasting: Wisdom-based. Prepare {prepared_spells} spells. DC {spell_dc}.")
        
        # Wild Shape uses and CR limits
        wild_shape_uses = 2
        if lvl >= 20:
            wild_shape_uses = 999  # Unlimited
        elif lvl >= 17:
            wild_shape_uses = 4
        elif lvl >= 5:
            wild_shape_uses = 3
        
        # CR limits
        if lvl >= 8:
            max_cr = lvl // 3
            cr_note = f"CR {max_cr}, fly/swim allowed"
        elif lvl >= 3:
            max_cr = 1
            cr_note = "CR 1, no fly"
        else:
            max_cr = 0.25
            cr_note = "CR 1/4, no fly/swim"
        
        char["wild_shape_max_cr"] = max_cr
        ensure_resource(char, "Wild Shape", wild_shape_uses)
        
        if not any("Wild Shape" in f for f in features):
            features.append(f"Wild Shape: {wild_shape_uses}/day. {cr_note}. Duration {lvl} hours.")
        
        if not any(a.get("name") == "Wild Shape" for a in actions):
            actions.append({
                "name": "Wild Shape",
                "resource": "Wild Shape",
                "action_type": "action",
                "description": f"Action: Transform into beast ({cr_note}) for up to {lvl} hours.",
            })
        
        # Wild Empathy at level 4+
        if lvl >= 4:
            if not any("Wild Empathy" in f for f in features):
                features.append("Wild Empathy: Influence beasts/fey/plants with Persuasion (WIS). +2 Animal Handling.")
        
        # Primal Strike at level 6+
        if lvl >= 6:
            char["primal_strike"] = True
            if not any("Primal Strike" in f for f in features):
                features.append("Primal Strike: Natural attacks in Wild Shape count as magical.")
        
        # Poison Immunity at level 7+
        if lvl >= 7:
            char.setdefault("condition_immunities", [])
            if "poisoned" not in char["condition_immunities"]:
                char["condition_immunities"].append("poisoned")
            if not any("Poison Immunity" in f for f in features):
                features.append("Poison Immunity: Immune to poison damage and poisoned condition.")
        
        # Elemental Wild Shape at level 8+
        if lvl >= 8:
            if not any(a.get("name") == "Elemental Wild Shape" for a in actions):
                actions.append({
                    "name": "Elemental Wild Shape",
                    "resource": "Wild Shape",
                    "cost": 2,
                    "action_type": "action",
                    "description": f"Action (2 uses): Transform into an elemental (max CR {max_cr}).",
                })
        
        # Nature's Ward at level 9+
        if lvl >= 9:
            char.setdefault("condition_immunities", [])
            if "diseased" not in char["condition_immunities"]:
                char["condition_immunities"].append("diseased")
            if not any("Nature's Ward" in f for f in features):
                features.append("Nature's Ward: Immune to disease.")
        
        # Call the Storm at level 10+
        if lvl >= 10:
            ensure_resource(char, "Call the Storm", 1)
            if not any("Call the Storm" in f for f in features):
                features.append(f"Call the Storm: 1/day, 1 min aura. Bonus Action: 4d10 lightning (DEX DC {spell_dc}) or 2d8 thunder + push/prone.")
            
            if not any(a.get("name") == "Call the Storm" for a in actions):
                actions.append({
                    "name": "Call the Storm",
                    "resource": "Call the Storm",
                    "action_type": "action",
                    "save_dc": spell_dc,
                    "description": f"Action: 1 min storm aura. Bonus Action: Lightning Bolt (4d10, DEX DC {spell_dc}) or Thunderclap (2d8, STR DC {spell_dc} or pushed/prone).",
                })
        
        # Verdant Step at level 11+
        if lvl >= 11:
            if not any("Verdant Step" in f for f in features):
                features.append("Verdant Step: Always under Freedom of Movement. Ignore non-magical difficult terrain.")
        
        # Dryadic Blessing at level 12+
        if lvl >= 12:
            if not any("Dryadic Blessing" in f for f in features):
                features.append("Dryadic Blessing: Wild Shape can become plant creatures.")
        
        # Voice of the Wild at level 13+
        if lvl >= 13:
            if not any("Voice of the Wild" in f for f in features):
                features.append("Voice of the Wild: Always speak with animals/plants. Use WIS for Persuasion with them.")
        
        # Nature's Resilience at level 14+
        if lvl >= 14:
            if not any("Nature's Resilience" in f for f in features):
                features.append(f"Nature's Resilience: In Wild Shape, resist B/P/S from nonmagical. Or +{wis_mod} temp HP/turn if already resistant.")
        
        # Primordial Tongue at level 15+
        if lvl >= 15:
            char["primordial_tongue"] = True
            char.setdefault("languages", [])
            if "Primordial" not in char["languages"]:
                char["languages"].append("Primordial")
            if not any("Primordial Tongue" in f for f in features):
                features.append(
                    "Primordial Tongue: Speak, read, and write Primordial. "
                    "Telepathically communicate within 30 ft with beasts, elementals, and plant creatures."
                )
        
        # Feystride at level 16+
        if lvl >= 16:
            feystride_uses = max(1, wis_mod)
            ensure_resource(char, "Feystride", feystride_uses)
            if not any("Feystride" in f for f in features):
                features.append(f"Feystride: {feystride_uses}/day, reaction to teleport 30 ft before attack/effect resolves.")
        
        # Wild Soul at level 17+
        if lvl >= 17:
            if not any("Wild Soul" in f for f in features):
                features.append("Wild Soul: In Wild Shape, use WIS for concentration. +2 saves vs spells/magic.")
        
        # Primal Spells at level 18+
        if lvl >= 18:
            if not any("Primal Spells" in f for f in features):
                features.append("Primal Spells: Cast 1 action/bonus action Druid spells while in Wild Shape.")
        
        # Elder Wildsoul at level 19+
        if lvl >= 19:
            if not any("Elder Wildsoul" in f for f in features):
                features.append(f"Elder Wildsoul: In Wild Shape, regain {wis_mod} HP at start of each turn (if above 0 HP).")
        
        # Archdruid at level 20
        if lvl >= 20:
            char["truesight"] = 60
            if not any("Archdruid" in f for f in features):
                features.append("Archdruid: Fey type. Immune to charm. Unlimited Wild Shape. Age 1 year per 10. Truesight 60 ft.")
    
    # ---- Monk ----
    elif cls_name == "Monk":
        wis_mod = _ability_mod(abilities.get("WIS", 10))
        dex_mod = _ability_mod(abilities.get("DEX", 10))
        lvl = int(char.get("level", 1))
        
        # Unarmored Defense
        monk_ac = 10 + dex_mod + wis_mod
        char["monk_unarmored_ac"] = monk_ac
        if not any("Unarmored Defense" in f for f in features):
            features.append(f"Unarmored Defense: AC = 10 + DEX mod + WIS mod (currently {monk_ac}) while unarmored.")
        
        # Martial Arts die scales
        if lvl >= 12:
            martial_die = "d12"
        elif lvl >= 8:
            martial_die = "d10"
        elif lvl >= 5:
            martial_die = "d8"
        else:
            martial_die = "d6"
        
        char["martial_arts_die"] = martial_die
        
        if not any("Martial Arts" in f for f in features):
            features.append(f"Martial Arts: Unarmed strikes deal {martial_die}. Bonus Action unarmed strike. Use DEX for unarmed/monk weapons.")
        
        if not any(a.get("name") == "Bonus Unarmed Strike" for a in actions):
            actions.append({
                "name": "Bonus Unarmed Strike",
                "action_type": "bonus",
                "damage": f"1{martial_die}",
                "damage_type": "bludgeoning",
                "to_hit": dex_mod + int(char.get("bab", 0)),
                "description": f"Bonus Action: Make an unarmed strike dealing 1{martial_die} + {dex_mod} damage.",
            })
        
        # Ki at level 2+
        if lvl >= 2:
            # Ki points = level + 1 (starts at 3 at L2)
            ki_points = lvl + 1
            ensure_resource(char, "Ki", ki_points)
            ki_dc = 10 + wis_mod
            char["ki_dc"] = ki_dc
            
            if not any("Ki Pool" in f for f in features):
                features.append(f"Ki Pool: {ki_points} Ki points. Ki save DC = {ki_dc}.")
            
            if not any(a.get("name") == "Flurry of Blows" for a in actions):
                actions.append({
                    "name": "Flurry of Blows",
                    "resource": "Ki",
                    "cost": 1,
                    "action_type": "bonus",
                    "damage": f"2{martial_die}",
                    "damage_type": "bludgeoning",
                    "description": f"Bonus Action (1 Ki): Make two unarmed strikes (2{martial_die} + {dex_mod * 2} damage total).",
                })
            
            if not any(a.get("name") == "Step of the Wind" for a in actions):
                actions.append({
                    "name": "Step of the Wind",
                    "resource": "Ki",
                    "cost": 1,
                    "action_type": "bonus",
                    "description": "Bonus Action (1 Ki): Disengage or Dash as a bonus action.",
                })
            
            if not any(a.get("name") == "Patient Defense" for a in actions):
                actions.append({
                    "name": "Patient Defense",
                    "resource": "Ki",
                    "cost": 1,
                    "action_type": "bonus",
                    "description": "Bonus Action (1 Ki): Dodge as a bonus action.",
                })
            
            # Unarmored Movement
            speed_bonus = 10
            if lvl >= 18:
                speed_bonus = 30
            elif lvl >= 14:
                speed_bonus = 25
            elif lvl >= 10:
                speed_bonus = 20
            elif lvl >= 6:
                speed_bonus = 15
            
            char["unarmored_speed_bonus"] = speed_bonus
            if not any("Unarmored Movement" in f for f in features):
                features.append(f"Unarmored Movement: +{speed_bonus} ft speed while unarmored.")
        
        # Deflect Missiles at level 3+
        if lvl >= 3:
            deflect_reduction = f"1d10 + {dex_mod} + {lvl}"
            if not any("Deflect Missiles" in f for f in features):
                features.append(f"Deflect Missiles: Reaction to reduce ranged attack damage by {deflect_reduction}. Catch and throw back for 1 Ki.")
            
            if not any(a.get("name") == "Deflect Missiles" for a in actions):
                actions.append({
                    "name": "Deflect Missiles",
                    "action_type": "reaction",
                    "description": f"Reaction: Reduce ranged attack damage by 1d10 + {dex_mod + lvl}. If reduced to 0, catch and spend 1 Ki to throw back.",
                })
            
            # Open Hand Technique
            if not any("Open Hand Technique" in f for f in features):
                features.append(f"Open Hand Technique: On Flurry hit, impose Addle (no OA), Push (STR save DC {ki_dc}), or Topple (DEX save DC {ki_dc}).")
        
        # Ki Blast at level 4+
        if lvl >= 4:
            if not any(a.get("name") == "Ki Blast" for a in actions):
                actions.append({
                    "name": "Ki Blast",
                    "resource": "Ki",
                    "cost": 1,
                    "action_type": "action",
                    "damage": f"1{martial_die}",
                    "damage_type": "force",
                    "range": 30,
                    "to_hit": dex_mod + int(char.get("bab", 0)),
                    "description": f"Action (1 Ki): Ranged attack, 30 ft, 1{martial_die} + {wis_mod} force damage.",
                })
            
            if not any("Slow Fall" in f for f in features):
                features.append(f"Slow Fall: Reaction to reduce falling damage by {5 * lvl}.")
            
            if not any("Still Mind" in f for f in features):
                features.append("+2 bonus on saves vs enchantment spells.")
        
        # Extra Attack and Stunning Strike at level 5+
        if lvl >= 5:
            char["extra_attack"] = 1
            if not any("Extra Attack" in f for f in features):
                features.append("Extra Attack: Attack twice when you take the Attack action.")
            
            if not any("Evasion" in f for f in features):
                features.append("Evasion: On successful DEX save for half damage, take no damage instead.")
            
            if not any(a.get("name") == "Stunning Strike" for a in actions):
                actions.append({
                    "name": "Stunning Strike",
                    "resource": "Ki",
                    "cost": 1,
                    "action_type": "free",
                    "save_dc": ki_dc,
                    "save_type": "CON",
                    "description": f"On melee hit (1 Ki): Target makes CON save (DC {ki_dc}) or is Stunned until end of your next turn.",
                })
        
        # Ki-Empowered Strikes at level 6+
        if lvl >= 6:
            char["magical_unarmed"] = True
            if not any("Ki-Empowered Strikes" in f for f in features):
                features.append("Ki-Empowered Strikes: Unarmed strikes count as magical.")
            
            ensure_resource(char, "Wholeness of Body", 1)
            if not any(a.get("name") == "Wholeness of Body" for a in actions):
                actions.append({
                    "name": "Wholeness of Body",
                    "resource": "Wholeness of Body",
                    "action_type": "action",
                    "description": f"Action: Regain {3 * lvl} HP. Once per rest.",
                })
        
        # Stillness of Mind at level 7+
        if lvl >= 7:
            if not any("Stillness of Mind" in f for f in features):
                features.append("Stillness of Mind: Reaction to end Charmed or Frightened on yourself.")
        
        # Purity of Body at level 8+
        if lvl >= 8:
            char.setdefault("condition_immunities", [])
            if "poisoned" not in char["condition_immunities"]:
                char["condition_immunities"].append("poisoned")
            if not any("Purity of Body" in f for f in features):
                features.append("Purity of Body: Immunity to poison and disease.")
        
        # Improved Evasion at level 9+
        if lvl >= 9:
            char["has_improved_evasion"] = True
            if not any("Improved Evasion" in f for f in features):
                features.append("Improved Evasion: Take half damage on failed DEX saves (none on success).")
        
        # Inner Purity at level 10+
        if lvl >= 10:
            char["has_inner_purity"] = True
            char.setdefault("condition_immunities", [])
            if "charmed" not in char["condition_immunities"]:
                char["condition_immunities"].append("charmed")
            if "frightened" not in char["condition_immunities"]:
                char["condition_immunities"].append("frightened")
            if not any("Inner Purity" in f for f in features):
                features.append("Inner Purity: Immune to Charmed and Frightened conditions. Your Ki purges all mental influence.")
        
        # Combat Reflexes at level 10+
        if lvl >= 10:
            if not any("Combat Reflexes" in f for f in features):
                features.append(f"Combat Reflexes: {max(1, dex_mod)} Opportunity Attacks per round without using reaction.")
        
        # Deflect Energy at level 13+
        if lvl >= 13:
            if not any("Deflect Energy" in f for f in features):
                features.append("Deflect Energy: Deflect Missiles works against any ranged damage type.")
        
        # Timeless Body at level 15+
        if lvl >= 15:
            if not any("Timeless Body" in f for f in features):
                features.append("Timeless Body: No longer age. No food/water needed. 4 hours meditation = long rest.")
        
        # Ki Shield at level 16+
        if lvl >= 16:
            if not any("Ki Shield" in f for f in features):
                features.append(f"Ki Shield: 30 ft bright light aura. Reaction when hit: deal {5 + wis_mod} radiant to attacker.")
        
        # Quivering Palm at level 17+
        if lvl >= 17:
            if not any(a.get("name") == "Quivering Palm" for a in actions):
                actions.append({
                    "name": "Quivering Palm",
                    "resource": "Ki",
                    "cost": 4,
                    "action_type": "free",
                    "save_dc": ki_dc,
                    "save_type": "CON",
                    "description": f"On unarmed hit (4 Ki): Set vibrations for {lvl} days. End as action: CON save (DC {ki_dc}) or 10d12 force (half on success).",
                })
        
        # Empty Body at level 18+
        if lvl >= 18:
            if not any(a.get("name") == "Empty Body" for a in actions):
                actions.append({
                    "name": "Empty Body",
                    "resource": "Ki",
                    "cost": 8,
                    "action_type": "action",
                    "description": "Action (8 Ki): Cast Astral Projection without material components (self only).",
                })
        
        # Perfect Self at level 20
        if lvl >= 20:
            char["blindsight"] = 60
            if not any("Perfect Self" in f for f in features):
                features.append("Perfect Self: Outsider type. Blindsight 60 ft. +4 DEX/WIS. Regain 4 Ki on initiative if at 0.")
    
    # ---- Paladin ----
    elif cls_name == "Paladin":
        cha_mod = _ability_mod(abilities.get("CHA", 10))
        lvl = int(char.get("level", 1))
        spell_dc = 8 + cha_mod + lvl
        
        # Lay on Hands pool
        lay_on_hands_pool = 5 * lvl
        ensure_resource(char, "Lay on Hands", lay_on_hands_pool)
        
        if not any("Lay on Hands" in f for f in features):
            features.append(f"Lay on Hands: Healing pool of {lay_on_hands_pool} HP. Restore as an action by touch.")
        
        if not any(a.get("name") == "Lay on Hands" for a in actions):
            actions.append({
                "name": "Lay on Hands",
                "resource": "Lay on Hands",
                "action_type": "action",
                "description": f"Action: Touch a creature to restore HP from your pool (max {lay_on_hands_pool}).",
            })
        
        if not any("Aura of Good" in f for f in features):
            features.append("Aura of Good: You emit an aura of good out to 10 feet.")
        
        if not any("Spellcasting" in f for f in features):
            features.append("Spellcasting: Charisma-based half-caster. Prepare spells after rest.")
        
        # Divine Smite and Fighting Style at level 2+
        if lvl >= 2:
            if not any("Divine Smite" in f for f in features):
                features.append("Divine Smite: Expend spell slot on hit for +2d8 radiant (+1d8 per slot level). Extra vs undead/fiends.")
            
            if not any(a.get("name") == "Divine Smite" for a in actions):
                actions.append({
                    "name": "Divine Smite",
                    "action_type": "free",
                    "resource": "Spell Slots",
                    "description": "On hit: Expend a spell slot for +2d8 radiant damage (+1d8 per slot level above 1st). Max 5d8.",
                })
            
            # Fighting Style at level 2
            if not any("Fighting Style" in f for f in features):
                features.append("Fighting Style: Gain a Fighting Style feat of your choice.")
            grant_fighting_style(char, 1)
        
        # Divine Health and Divine Vow at level 3+
        if lvl >= 3:
            if not any("Divine Health" in f for f in features):
                features.append("Divine Health: Immune to disease.")
            char.setdefault("condition_immunities", [])
            if "diseased" not in char["condition_immunities"]:
                char["condition_immunities"].append("diseased")
            
            # Divine Vow selection
            vow = char.get("paladin_divine_vow")
            if vow:
                _apply_paladin_divine_vow(char, vow, cha_mod, lvl, spell_dc, features, actions)
            else:
                if not any("Divine Vow" in f for f in features):
                    features.append("Divine Vow: Choose Conservation, Protection, Devotion, or Vengeance.")
                char["pending_divine_vow"] = True
        
        # Mounted Companion at level 4+
        if lvl >= 4:
            if not any("Mounted Companion" in f for f in features):
                mount_bonus = f"+{cha_mod}" if lvl >= 10 else ""
                features.append(f"Mounted Companion: War Horse that acts on your turn. {mount_bonus}")
        
        # Extra Attack at level 5+
        if lvl >= 5:
            char["extra_attack"] = 1
            if not any("Extra Attack" in f for f in features):
                features.append("Extra Attack: Attack twice when you take the Attack action.")
        
        # Aura of Protection at level 6+
        if lvl >= 6:
            aura_range = 30 if lvl >= 12 else 10  # Nimbus of Good at 12 increases to 30 ft
            char["aura_of_protection"] = True
            char["aura_range"] = aura_range
            if not any("Aura of Protection" in f for f in features):
                features.append(f"Aura of Protection: You and allies within {aura_range} ft add +{cha_mod} to saving throws.")
        
        # Restoring Touch at level 8+
        if lvl >= 8:
            char["restoring_touch"] = True
            if not any("Restoring Touch" in f for f in features):
                features.append(
                    "Restoring Touch: When using Lay on Hands, spend 5 HP from pool per condition to remove: "
                    "Blinded, Charmed, Deafened, Frightened, Paralyzed, or Stunned."
                )
        
        # Abjure Foes at level 9+
        if lvl >= 9:
            ensure_resource(char, "Abjure Foes", 1)
            char["abjure_foes_dc"] = spell_dc
            if not any("Abjure Foes" in f for f in features):
                features.append(
                    f"Abjure Foes: Action, target up to {max(1, cha_mod)} creatures within 60 ft. "
                    f"WIS DC {spell_dc} or Frightened for 1 min (can only move, action, OR bonus action)."
                )
            if not any(a.get("name") == "Abjure Foes" for a in actions):
                actions.append({
                    "name": "Abjure Foes",
                    "action_type": "action",
                    "resource": "Abjure Foes",
                    "save_dc": spell_dc,
                    "description": f"Target up to {max(1, cha_mod)} creatures within 60 ft. WIS DC {spell_dc} or Frightened.",
                })
        
        # Aura of Courage at level 10+
        if lvl >= 10:
            char["aura_of_courage"] = True
            if not any("Aura of Courage" in f for f in features):
                features.append(f"Aura of Courage: You and allies within {aura_range} ft are immune to Frightened.")
        
        # Radiant Strikes and Improved Divine Smite at level 11+
        if lvl >= 11:
            char["radiant_strikes"] = True
            char["improved_divine_smite"] = True
            if not any("Radiant Strikes" in f for f in features):
                features.append("Radiant Strikes: All melee hits deal +1d8 radiant damage automatically.")
            if not any("Improved Divine Smite" in f for f in features):
                features.append("Improved Divine Smite: Divine Smite deals an additional +1d8 radiant damage.")
        
        # Nimbus of Good at level 12+
        if lvl >= 12:
            char["nimbus_of_good"] = True
            if not any("Nimbus of Good" in f for f in features):
                features.append("Nimbus of Good: Your Aura of Good range increases to 30 feet.")
        
        # Divine Ward at level 13+
        if lvl >= 13:
            char["divine_ward"] = True
            if not any("Divine Ward" in f for f in features):
                features.append(
                    "Divine Ward: Instead of dealing damage, Divine Smite can grant you and allies in aura "
                    "temporary HP equal to the radiant damage it would have dealt."
                )
            if not any(a.get("name") == "Divine Ward" for a in actions):
                actions.append({
                    "name": "Divine Ward",
                    "action_type": "free",
                    "resource": "Spell Slots",
                    "description": "On hit: Use Divine Smite to grant temp HP instead of damage to you and allies in aura.",
                })
        
        # Cleansing Touch at level 14+
        if lvl >= 14:
            ensure_resource(char, "Cleansing Touch", max(1, cha_mod))
            if not any("Cleansing Touch" in f for f in features):
                features.append(f"Cleansing Touch: {max(1, cha_mod)}/day, action to end one spell on self or willing creature.")
        
        # Renewing Your Vow at level 15+
        if lvl >= 15:
            char["renewed_vow"] = True
            vow = char.get("paladin_divine_vow", "")
            if not any("Renewing Your Vow" in f for f in features):
                features.append(
                    f"Renewing Your Vow: Your {vow} vow strengthens with enhanced benefits."
                )
        
        # Aura of Safety at level 18+
        if lvl >= 18:
            char["aura_of_safety"] = True
            if not any("Aura of Safety" in f for f in features):
                features.append(
                    "Aura of Safety: Allies in aura cannot fail death saves or be reduced below 1 HP. "
                    "While you haven't attacked, aura acts as Sanctuary."
                )
        
        # Divine Ascension at level 20
        if lvl >= 20:
            char["divine_ascension"] = True
            ensure_resource(char, "Divine Radiance", 1)
            if not any("Divine Ascension" in f for f in features):
                features.append(
                    "Divine Ascension: Divine Smite 1/turn without spell slot (highest level). "
                    "Aura has Hallow effect. Bonus Action: Divine Radiance for CHA mod rounds "
                    "(resist all damage, radiant weapon attacks, max Divine Smite damage)."
                )
            if not any(a.get("name") == "Divine Radiance" for a in actions):
                actions.append({
                    "name": "Divine Radiance",
                    "action_type": "bonus",
                    "resource": "Divine Radiance",
                    "description": f"Enter divine state for {max(1, cha_mod)} rounds: resist all, radiant attacks, max smite damage.",
                })
    
    # ---- Ranger ----
    elif cls_name == "Ranger":
        wis_mod = _ability_mod(abilities.get("WIS", 10))
        lvl = int(char.get("level", 1))
        
        # --- Favored Enemy and Natural Explorer (Level 1) ---
        favored_enemy = char.get("ranger_favored_enemy", "Beasts")
        favored_terrain = char.get("ranger_favored_terrain", "Forest")
        
        if not any("Favored Enemy" in f for f in features):
            features.append(f"Favored Enemy ({favored_enemy}): +2 damage against {favored_enemy}.")
        
        if not any("Natural Explorer" in f for f in features):
            features.append(f"Natural Explorer ({favored_terrain}): Benefits in {favored_terrain} (no slow, can't get lost, stealth at normal pace).")
        
        if not any("Spellcasting" in f for f in features):
            features.append("Spellcasting: Wisdom-based half-caster.")
        
        # Fighting Style at level 2+
        if lvl >= 2:
            if not any("Fighting Style" in f for f in features):
                features.append("Fighting Style: Gain a Fighting Style feat.")
            grant_fighting_style(char, 1)
            
            if not any("Wild Empathy" in f for f in features):
                features.append(f"Wild Empathy: Influence beasts within 30 ft. DC = 10 + WIS mod ({10 + wis_mod}).")
        
        # Animal Companion at level 3+
        if lvl >= 3:
            max_companion_cr = max(1, lvl // 3)
            companion_type = char.get("ranger_companion_type", "Wolf")
            companion_bonus_hp = wis_mod + lvl
            
            char["animal_companion"] = {
                "type": companion_type,
                "max_cr": max_companion_cr,
                "bonus_hp": companion_bonus_hp,
            }
            
            # Create actual companion entity if not exists
            if "companions" not in char:
                char["companions"] = []
            
            existing_companion = next((c for c in char["companions"] if c.get("companion_type") == "animal_companion"), None)
            if not existing_companion or existing_companion.get("base_creature") != companion_type:
                # Create or update companion
                new_companion = create_animal_companion(char, companion_type)
                if new_companion:
                    char["companions"] = [c for c in char["companions"] if c.get("companion_type") != "animal_companion"]
                    char["companions"].append(new_companion)
                    char["pending_companion_selection"] = False
            elif not existing_companion:
                char["pending_companion_selection"] = True
            
            if not any("Animal Companion" in f for f in features):
                features.append(f"Animal Companion: {companion_type} (max CR {max_companion_cr}). +{companion_bonus_hp} bonus HP.")
            
            if not any("Tracking Mastery" in f for f in features):
                features.append(f"Tracking Mastery: +{lvl} to tracking checks. Track without obvious signs.")
        
        # Trapper's Expertise at level 4+
        if lvl >= 4:
            char["trappers_expertise"] = True
            char.setdefault("tool_proficiencies", [])
            if "Tinker's Tools" not in char["tool_proficiencies"]:
                char["tool_proficiencies"].append("Tinker's Tools")
            ensure_resource(char, "Create Trap", 1)
            if not any("Trapper's Expertise" in f for f in features):
                features.append(
                    "Trapper's Expertise: Proficiency with Tinker's Tools. 1/long rest, create a simple trap "
                    "(snare, pitfall, caltrops) lasting 24 hours. Trap deals damage or imposes conditions."
                )
        
        # Extra Attack at level 5+
        if lvl >= 5:
            char["extra_attack"] = 1
            if not any("Extra Attack" in f for f in features):
                features.append("Extra Attack: Attack twice when you take the Attack action.")
            
            if not any("Hunter's Stealth" in f for f in features):
                features.append(f"Hunter's Stealth: Hide while lightly obscured in favored terrain. -{lvl} to Perception vs you.")
        
        # Second Fighting Style and Improved Companion at level 6+
        if lvl >= 6:
            has_second_style = any("Fighting Style (2nd)" in f or "second Fighting Style" in f.lower() for f in features)
            if not has_second_style:
                features.append("Fighting Style (2nd): Gain a second Fighting Style feat of your choice.")
            grant_fighting_style(char, 2)
            
            if not any("Improved Companion" in f for f in features):
                features.append("Improved Companion: Companion gains Multiattack (2 attacks).")
        
        # Roving at level 7+
        if lvl >= 7:
            char["ranger_speed_bonus"] = 10
            if not any("Roving" in f for f in features):
                features.append("Roving: +10 ft speed. Gain Climb and Swim speed equal to your Speed.")
        
        # Advanced Bond at level 9+
        if lvl >= 9:
            ensure_resource(char, "Protective Sacrifice", 1)
            if not any("Advanced Bond" in f for f in features):
                features.append(f"Advanced Bond: 1/day, companion takes hit for you. Companion adds +{wis_mod} to checks/saves/attacks.")
            
            if not any(a.get("name") == "Protective Sacrifice" for a in actions):
                actions.append({
                    "name": "Protective Sacrifice",
                    "resource": "Protective Sacrifice",
                    "action_type": "reaction",
                    "description": "Reaction: When hit within 15 ft of companion, companion takes the hit instead.",
                })
        
        # Nature's Resilience at level 10+
        if lvl >= 10:
            char.setdefault("damage_resistances", [])
            if "poison" not in char["damage_resistances"]:
                char["damage_resistances"].append("poison")
            if not any("Nature's Resilience" in f for f in features):
                features.append("Nature's Resilience: Resistance to poison damage.")
        
        # Master Tracker at level 11+
        if lvl >= 11:
            if not any("Master Tracker" in f for f in features):
                features.append("Master Tracker: Track through any terrain/weather. Minimum 15 on tracking rolls.")
        
        # Swift Predator at level 14+
        if lvl >= 14:
            if not any(a.get("name") == "Swift Predator" for a in actions):
                actions.append({
                    "name": "Swift Predator",
                    "action_type": "action",
                    "description": "Action: You and companion Dash toward target, then each attack for +2d6 damage (+4d6 on crit).",
                })
        
        # Share Spells at level 15+
        if lvl >= 15:
            if not any("Share Spells" in f for f in features):
                features.append("Share Spells: Self-targeting spells also affect companion within 30 ft.")
        
        # Apex Predator at level 18+
        if lvl >= 18:
            ensure_resource(char, "Hunter's Frenzy", 1)
            if not any("Apex Predator" in f for f in features):
                features.append("Apex Predator: +1d6 damage when flanking with companion. Dash on killing blow.")
        
        # Nature's Fury at level 20
        if lvl >= 20:
            ensure_resource(char, "Hunting Frenzy", 1)
            char["ranger_speed_bonus"] = 30  # Upgrade from 10
            if not any("Nature's Fury" in f for f in features):
                features.append("Nature's Fury: +30 ft speed. 1/day Hunting Frenzy (Haste, +WIS to rolls, +3d6 damage, 1 HP save).")
            
            if not any(a.get("name") == "Hunting Frenzy" for a in actions):
                actions.append({
                    "name": "Hunting Frenzy",
                    "resource": "Hunting Frenzy",
                    "action_type": "action",
                    "description": f"Action: 1 min Haste (no concentration). You and companion add +{wis_mod} to attacks/saves/checks. +3d6 damage. Once drop to 1 HP instead of 0.",
                })
    
    # ---- Rogue ----
    elif cls_name == "Rogue":
        dex_mod = _ability_mod(abilities.get("DEX", 10))
        int_mod = _ability_mod(abilities.get("INT", 10))
        lvl = int(char.get("level", 1))
        
        # ===== SNEAK ATTACK (Level 1) =====
        # Dice scale: 1d6 at 1, 2d6 at 3, 3d6 at 5, etc. (every odd level)
        sneak_dice = (lvl + 1) // 2
        char["sneak_attack_dice"] = sneak_dice
        char["sneak_attack_used_this_turn"] = char.get("sneak_attack_used_this_turn", False)
        
        if not any("Sneak Attack" in f for f in features):
            features.append(
                f"Sneak Attack: +{sneak_dice}d6 damage once per turn when you have +2 bonus, "
                f"target is flanked, denied DEX to AC, or an ally is within 5ft of target."
            )
        
        # ===== THIEVES' CANT (Level 1) =====
        char["knows_thieves_cant"] = True
        if not any("Thieves' Cant" in f for f in features):
            features.append(
                "Thieves' Cant: You know the secret language and signs of rogues. "
                "Can convey hidden messages in normal conversation. Takes 4x longer to convey than plain speech."
            )
        
        # Add Thieves' Cant as a language
        languages = char.get("languages", "")
        if "Thieves' Cant" not in languages:
            if languages:
                char["languages"] = f"{languages}, Thieves' Cant"
            else:
                char["languages"] = "Thieves' Cant"
        
        # ===== STEALTHY (Level 2) =====
        if lvl >= 2:
            char["stealthy"] = True
            char["stealthy_penalty"] = dex_mod
            if not any("Stealthy" in f for f in features):
                features.append(
                    f"Stealthy: While hidden, enemies take -{dex_mod} penalty to Perception checks to detect you. "
                    f"You can attempt to hide as a bonus action."
                )
            
            if not any(a.get("name") == "Cunning Hide" for a in actions):
                actions.append({
                    "name": "Cunning Hide",
                    "action_type": "bonus",
                    "description": "Bonus Action: Attempt to hide if you have cover or concealment.",
                })
        
        # ===== EVASION (Level 3) =====
        if lvl >= 3:
            char["has_evasion"] = True
            if not any("Evasion" in f for f in features):
                features.append(
                    "Evasion: When you make a DEX save for half damage, take no damage on success, "
                    "half damage on failure."
                )
        
        # ===== CATLIKE CLIMBER (Level 3) =====
        if lvl >= 3:
            char["catlike_climber"] = True
            char["climb_speed"] = 20  # Gain climb speed
            if not any("Catlike Climber" in f for f in features):
                features.append(
                    "Catlike Climber: Gain climb speed 20 ft. You don't need free hands to climb. "
                    "You can make Climb checks in place of Acrobatics to reduce fall damage."
                )
        
        # ===== UNCANNY DODGE (Level 4) =====
        if lvl >= 4:
            char["has_uncanny_dodge"] = True
            if not any("Uncanny Dodge" in f for f in features):
                features.append(
                    "Uncanny Dodge: Reaction when hit by an attack you can see - halve the damage."
                )
            
            if not any(a.get("name") == "Uncanny Dodge" for a in actions):
                actions.append({
                    "name": "Uncanny Dodge",
                    "action_type": "reaction",
                    "description": "Reaction: When hit by an attack you can see, halve the damage.",
                })
        
        # ===== TRAP SENSE (Level 5) =====
        if lvl >= 5:
            trap_bonus = 1 + (lvl - 5) // 3  # +1 at 5, +2 at 8, +3 at 11, etc.
            char["trap_sense_bonus"] = trap_bonus
            if not any("Trap Sense" in f for f in features):
                features.append(
                    f"Trap Sense: +{trap_bonus} bonus to AC and Reflex saves vs traps. "
                    f"Automatically search for traps when within 10ft."
                )
        
        # ===== AGILE DEFENSE (Level 6) =====
        if lvl >= 6:
            char["has_agile_defense"] = True
            char["agile_defense_bonus"] = dex_mod
            if not any("Agile Defense" in f for f in features):
                features.append(
                    f"Agile Defense: While wearing light or no armor, add +{dex_mod} (DEX mod) to AC "
                    f"when you take the Dodge action or use Uncanny Dodge."
                )
            
            if not any(a.get("name") == "Agile Defense" for a in actions):
                actions.append({
                    "name": "Agile Defense",
                    "action_type": "standard",
                    "description": f"Standard Action: Take Dodge action with +{dex_mod} additional AC until start of next turn.",
                })
        
        # ===== IMPROVED EVASION (Level 7) =====
        if lvl >= 7:
            char["has_improved_evasion"] = True
            # Update evasion feature
            features[:] = [f for f in features if "Evasion:" not in f]
            features.append(
                "Improved Evasion: When you make a DEX save for half damage, take no damage on success, "
                "half damage on failure. Even unconscious, you still benefit."
            )
        
        # ===== CUNNING STRIKE (Level 8) =====
        if lvl >= 8:
            char["has_cunning_strike"] = True
            cunning_dc = 10 + lvl // 2 + dex_mod
            char["cunning_strike_dc"] = cunning_dc
            if not any("Cunning Strike" in f for f in features):
                features.append(
                    f"Cunning Strike: When you deal Sneak Attack damage, you can forgo dice to apply effects. "
                    f"DC {cunning_dc} CON save or: Poison (1d6, forgo 1d6), Blind (1 round, forgo 2d6), "
                    f"Slow (half speed, forgo 2d6), Disarm (forgo 1d6), Trip (forgo 1d6)."
                )
        
        # ===== SKILL MASTERY (Level 9) =====
        if lvl >= 9:
            if not any("Skill Mastery" in f for f in features):
                features.append(
                    "Skill Mastery: Choose skills equal to 3 + INT mod. You can take 10 on these skills "
                    "even when stress or distraction would normally prevent it."
                )
            
            mastery_count = 3 + int_mod
            char["skill_mastery_count"] = mastery_count
            selected_mastery = char.get("rogue_skill_mastery", [])
            if len(selected_mastery) < mastery_count:
                char["pending_skill_mastery"] = mastery_count - len(selected_mastery)
        
        # ===== MOVING SHADOW (Level 10) =====
        if lvl >= 10:
            char["has_moving_shadow"] = True
            if not any("Moving Shadow" in f for f in features):
                features.append(
                    "Moving Shadow: You can move at full speed while using Stealth without penalty. "
                    "You can use Stealth even while being observed if you have any cover or concealment."
                )
        
        # ===== SLIPPERY MIND (Level 11) =====
        if lvl >= 11:
            char["has_slippery_mind"] = True
            if not any("Slippery Mind" in f for f in features):
                features.append(
                    "Slippery Mind: If you fail a WIS save against enchantment, "
                    "you can reroll it 1 round later."
                )
        
        # ===== ROGUE'S REFLEXES (Level 12) =====
        if lvl >= 12:
            char["has_rogues_reflexes"] = True
            char["rogues_reflexes_bonus"] = dex_mod
            if not any("Rogue's Reflexes" in f for f in features):
                features.append(
                    f"Rogue's Reflexes: Add +{dex_mod} (DEX mod) to Initiative. "
                    f"You can take two reactions per round instead of one."
                )
        
        # ===== OPPORTUNIST (Level 13) =====
        if lvl >= 13:
            char["has_opportunist"] = True
            if not any("Opportunist" in f for f in features):
                features.append(
                    "Opportunist: Once per round, when an ally hits an adjacent foe, "
                    "you can make an attack of opportunity against that foe."
                )
            
            if not any(a.get("name") == "Opportunist Strike" for a in actions):
                actions.append({
                    "name": "Opportunist Strike",
                    "action_type": "reaction",
                    "description": "Reaction: When ally hits adjacent foe, make an attack of opportunity (can Sneak Attack).",
                })
        
        # ===== MASTER OF DISGUISE (Level 14) =====
        if lvl >= 14:
            char["has_master_of_disguise"] = True
            if not any("Master of Disguise" in f for f in features):
                features.append(
                    "Master of Disguise: You can create a disguise in 1 minute instead of 1d3×10 minutes. "
                    "Take 10 on Disguise checks even when threatened. +10 bonus to Disguise checks."
                )
        
        # ===== CRIPPLING STRIKE (Level 15) =====
        if lvl >= 15:
            char["has_crippling_strike"] = True
            if not any("Crippling Strike" in f for f in features):
                features.append(
                    "Crippling Strike: Sneak Attack deals 2 STR damage in addition to normal damage. "
                    "Target takes -1 attack and damage per 2 STR damage until healed."
                )
        
        # ===== IMPROVED CUNNING STRIKE (Level 15) =====
        if lvl >= 15:
            char["has_improved_cunning_strike"] = True
            # Update cunning strike feature
            features[:] = [f for f in features if "Cunning Strike:" not in f]
            cunning_dc = 10 + lvl // 2 + dex_mod
            char["cunning_strike_dc"] = cunning_dc
            features.append(
                f"Improved Cunning Strike: Apply two Cunning Strike effects per Sneak Attack (pay dice for each). "
                f"New effects: Daze (forgo 2d6, can't take reactions), Knock Out (forgo 6d6, unconscious 1 min)."
            )
        
        # ===== TRICKSTER'S ESCAPE (Level 16) =====
        if lvl >= 16:
            ensure_resource(char, "Trickster's Escape", 1)
            char["has_tricksters_escape"] = True
            if not any("Trickster's Escape" in f for f in features):
                features.append(
                    "Trickster's Escape (1/day): As a bonus action, end one effect causing grappled, restrained, "
                    "or incapacitated. Teleport up to 30 ft to an unoccupied space you can see."
                )
            
            if not any(a.get("name") == "Trickster's Escape" for a in actions):
                actions.append({
                    "name": "Trickster's Escape",
                    "action_type": "bonus",
                    "resource": "Trickster's Escape",
                    "description": "Bonus Action: End grappled/restrained/incapacitated. Teleport 30 ft.",
                })
        
        # ===== INFILTRATOR'S EDGE (Level 16) =====
        if lvl >= 16:
            char["has_infiltrators_edge"] = True
            if not any("Infiltrator's Edge" in f for f in features):
                features.append(
                    "Infiltrator's Edge: You have +2 bonus on checks to find or disable traps and secret doors. "
                    "You can detect magical traps and wards. +5 bonus to Perception to spot hidden creatures."
                )
        
        # ===== DEFENSIVE ROLL (Level 17) =====
        if lvl >= 17:
            ensure_resource(char, "Defensive Roll", 1)
            char["has_defensive_roll"] = True
            if not any("Defensive Roll" in f for f in features):
                features.append(
                    "Defensive Roll (1/day): When reduced to 0 HP by an attack, "
                    "make Reflex save (DC = damage dealt) to take half damage instead."
                )
            
            if not any(a.get("name") == "Defensive Roll" for a in actions):
                actions.append({
                    "name": "Defensive Roll",
                    "resource": "Defensive Roll",
                    "action_type": "reaction",
                    "triggers_on": "drop_to_0_hp",
                    "description": "Reaction: When reduced to 0 HP, Reflex save (DC = damage) to take half instead.",
                })
        
        # ===== QUICK FINGERS (Level 18) =====
        if lvl >= 18:
            char["has_quick_fingers"] = True
            if not any("Quick Fingers" in f for f in features):
                features.append(
                    "Quick Fingers: You can use Sleight of Hand, Disable Device, or Use Magic Device "
                    "as a bonus action. You can pick locks and disarm traps at double speed."
                )
            
            if not any(a.get("name") == "Quick Fingers" for a in actions):
                actions.append({
                    "name": "Quick Fingers",
                    "action_type": "bonus",
                    "description": "Bonus Action: Use Sleight of Hand, Disable Device, or Use Magic Device.",
                })
        
        # ===== MASTER STRIKE (Level 19) =====
        if lvl >= 19:
            char["has_master_strike"] = True
            master_dc = 10 + lvl // 2 + dex_mod
            char["master_strike_dc"] = master_dc
            if not any("Master Strike" in f for f in features):
                features.append(
                    f"Master Strike: When you deal Sneak Attack damage, target must make Fort save (DC {master_dc}) "
                    f"or be paralyzed for 1d6+1 rounds, or sleep for 1d6 hours, or die (your choice)."
                )
        
        # ===== HIDE IN PLAIN SIGHT (Level 19) =====
        if lvl >= 19:
            char["has_hide_in_plain_sight"] = True
            # Update Moving Shadow
            features[:] = [f for f in features if "Moving Shadow:" not in f]
            features.append(
                "Hide in Plain Sight: You can use Stealth even while being directly observed without "
                "cover or concealment. Enemies have -2 penalty on Perception checks to find you."
            )
        
        # ===== LEGENDARY THIEF (Level 20) =====
        if lvl >= 20:
            char["legendary_thief"] = True
            if not any("Legendary Thief" in f for f in features):
                features.append(
                    "Legendary Thief: You can take 20 on any skill check as a standard action. "
                    "Automatic success on Stealth vs non-magical detection."
                )
        
        # ===== MASTER BURGLAR (Level 20) =====
        if lvl >= 20:
            char["has_master_burglar"] = True
            if not any("Master Burglar" in f for f in features):
                features.append(
                    "Master Burglar: You automatically succeed on Disable Device checks DC 30 or lower. "
                    "You can bypass magical locks and wards as if you had Knock cast at will. "
                    "Traps you disable cannot be reset without being completely rebuilt."
                )
    
    # ---- Sorcerer ----
    elif cls_name == "Sorcerer":
        cha_mod = _ability_mod(abilities.get("CHA", 10))
        lvl = int(char.get("level", 1))
        spell_dc = 8 + cha_mod + lvl
        
        if not any("Spellcasting" in f for f in features):
            features.append("Spellcasting: Charisma-based innate caster. Spells known, not prepared.")
        
        # --- Sorcerous Bloodline (Level 1) ---
        bloodline = char.get("sorcerer_bloodline")
        if bloodline:
            dragon_type = char.get("sorcerer_dragon_type", "Fire")
            if not any(f"Sorcerous Bloodline: {bloodline}" in f for f in features):
                features[:] = [f for f in features if "Sorcerous Bloodline:" not in f]
                features.append(f"Sorcerous Bloodline: {bloodline} - Grants bonus spells and features.")
            
            # Minor Bloodline (Level 1)
            _apply_sorcerer_bloodline_feature(char, bloodline, lvl, "minor", cha_mod, dragon_type, spell_dc, features, actions)
        else:
            if not any("Sorcerous Bloodline" in f for f in features):
                features.append("Sorcerous Bloodline: Choose Dragon, Fey, or Fiendish bloodline for bonus spells and features.")
        
        # Sorcery Points at level 2+
        if lvl >= 2:
            sorcery_points = lvl
            ensure_resource(char, "Sorcery Points", sorcery_points)
            
            if not any("Font of Arcane Power" in f for f in features):
                features.append(f"Font of Arcane Power: {sorcery_points} Sorcery Points. Convert slots to points or vice versa.")
            
            if not any("Eschew Materials" in f for f in features):
                features.append("Eschew Materials: Cast spells without non-costly material components.")
            
            if not any(a.get("name") == "Convert Slot to Points" for a in actions):
                actions.append({
                    "name": "Convert Slot to Points",
                    "resource": "Spell Slots",
                    "action_type": "free",
                    "description": "Expend a spell slot to gain Sorcery Points equal to slot level.",
                })
            
            if not any(a.get("name") == "Create Spell Slot" for a in actions):
                actions.append({
                    "name": "Create Spell Slot",
                    "resource": "Sorcery Points",
                    "action_type": "bonus",
                    "description": "Bonus Action: Spend Sorcery Points to create a spell slot (2 SP = 1st, 3 SP = 2nd, 5 SP = 3rd, 6 SP = 4th, 7 SP = 5th).",
                })
        
        # Metamagic at level 3+
        if lvl >= 3:
            # Metamagic known: 1 at L3, +1 at L9, +1 at L15
            metamagic_known = 1
            if lvl >= 9:
                metamagic_known = 2
            if lvl >= 15:
                metamagic_known = 3
            
            char["max_metamagic_known"] = metamagic_known
            
            if not any("Metamagic" in f for f in features):
                features.append(f"Metamagic: {metamagic_known} metamagic option(s) known. Modify spells by spending Sorcery Points.")
            
            # Check if we need to select metamagic
            selected_metamagic = char.get("sorcerer_metamagic", [])
            if len(selected_metamagic) < metamagic_known:
                char["pending_metamagic"] = metamagic_known - len(selected_metamagic)
            
            # Apply selected metamagic
            _apply_sorcerer_metamagic(char, selected_metamagic, actions)
        
        # Bloodline Manifestation at level 6+
        if lvl >= 6 and bloodline:
            _apply_sorcerer_bloodline_feature(char, bloodline, lvl, "manifestation", cha_mod, char.get("sorcerer_dragon_type", "Fire"), spell_dc, features, actions)
        
        # Greater Bloodline Manifestation at level 10+
        if lvl >= 10 and bloodline:
            _apply_sorcerer_bloodline_feature(char, bloodline, lvl, "greater", cha_mod, char.get("sorcerer_dragon_type", "Fire"), spell_dc, features, actions)
        
        # Empowered Sorcery at level 12+
        if lvl >= 12:
            if not any("Empowered Sorcery" in f for f in features):
                features.append(f"Empowered Sorcery: Add +{cha_mod} to one damage roll of any spell you cast.")
        
        # Bloodline Form at level 14+
        if lvl >= 14 and bloodline:
            _apply_sorcerer_bloodline_feature(char, bloodline, lvl, "form", cha_mod, char.get("sorcerer_dragon_type", "Fire"), spell_dc, features, actions)
        
        # Pureblood Awakening at level 18+
        if lvl >= 18 and bloodline:
            _apply_sorcerer_bloodline_feature(char, bloodline, lvl, "awakening", cha_mod, char.get("sorcerer_dragon_type", "Fire"), spell_dc, features, actions)
        
        # Apotheosis at level 20
        if lvl >= 20:
            ensure_resource(char, "Apotheosis", 1)
            if not any("Apotheosis" in f for f in features):
                features.append(f"Apotheosis: Once/day, Bloodline Form with CR limit = level + CHA mod ({lvl + cha_mod}).")
    
    # ---- Warlock ----
    elif cls_name == "Warlock":
        cha_mod = _ability_mod(abilities.get("CHA", 10))
        lvl = int(char.get("level", 1))
        bab = int(char.get("bab", 0))
        
        if not any("Pact Magic" in f for f in features):
            features.append("Pact Magic: Charisma-based. Few slots but recharge on short rest. All slots same level.")
        
        # Pact slots scale differently - all same level
        if lvl >= 9:
            slot_level = 5
        elif lvl >= 7:
            slot_level = 4
        elif lvl >= 5:
            slot_level = 3
        elif lvl >= 3:
            slot_level = 2
        else:
            slot_level = 1
        
        pact_slots = 1 if lvl == 1 else 2
        if lvl >= 11:
            pact_slots = 3
        if lvl >= 17:
            pact_slots = 4
        
        ensure_resource(char, "Pact Slots", pact_slots)
        char["pact_slot_level"] = slot_level
        
        # --- Patron Selection (Level 1) ---
        patron = char.get("warlock_patron")
        if patron:
            if not any(f"Eldritch Pact: {patron}" in f for f in features):
                # Remove generic feature if exists
                features[:] = [f for f in features if "Eldritch Pact:" not in f]
                features.append(f"Eldritch Pact: {patron} - Your patron grants you power and features.")
        else:
            if not any("Eldritch Pact" in f for f in features):
                features.append("Eldritch Pact: Choose a patron (Fiend, Great Old One, Archfey, etc.) for features.")
        
        # --- Pact's Touch (Level 2) - Patron-specific feature ---
        if lvl >= 2 and patron:
            _apply_warlock_patron_feature(char, patron, lvl, "touch", cha_mod, features, actions)
        
        # --- Eldritch Invocations (Level 2+) ---
        if lvl >= 2:
            # Calculate invocations known
            invocations_by_level = {
                2: 2, 3: 2, 4: 2, 5: 3, 6: 3, 7: 4, 8: 4, 9: 5, 10: 5,
                11: 5, 12: 6, 13: 6, 14: 6, 15: 7, 16: 7, 17: 7, 18: 8, 19: 8, 20: 8
            }
            max_invocations = invocations_by_level.get(lvl, 2)
            
            if not any("Eldritch Invocations" in f for f in features):
                features.append(f"Eldritch Invocations: {max_invocations} invocations known. Modify abilities or grant at-will spells.")
            
            # Apply selected invocations
            selected_invocations = char.get("warlock_invocations", [])
            _apply_warlock_invocations(char, selected_invocations, cha_mod, bab, lvl, features, actions)
            
            # Check if we need to select more invocations
            current_count = len(selected_invocations)
            if current_count < max_invocations:
                # Set pending invocations
                char["pending_invocations"] = max_invocations - current_count
            
            # Magical Cunning
            ensure_resource(char, "Magical Cunning", 1)
            if not any("Magical Cunning" in f for f in features):
                features.append("Magical Cunning: 1-minute rite to regain half your Pact Slots (rounded up). Once per long rest.")
        
        # --- Pact Boon (Level 3) ---
        if lvl >= 3:
            pact_boon = char.get("warlock_pact_boon")
            if pact_boon:
                _apply_warlock_pact_boon(char, pact_boon, cha_mod, lvl, features, actions)
            else:
                if not any("Pact Boon" in f for f in features):
                    features.append("Pact Boon: Choose Blade, Chain, Tome, or Talisman for additional powers.")
                # Set pending pact boon choice
                char["pending_pact_boon"] = True
        
        # --- Pact's Gift (Level 6) ---
        if lvl >= 6 and patron:
            _apply_warlock_patron_feature(char, patron, lvl, "gift", cha_mod, features, actions)
        
        # --- Contact Patron (Level 9) ---
        if lvl >= 9:
            ensure_resource(char, "Contact Patron", 1)
            if not any("Contact Patron" in f for f in features):
                features.append("Contact Patron: Cast Contact Other Plane without slot to reach your patron. Auto-succeed save. 1/day.")
        
        # --- Pact's Favor (Level 10) ---
        if lvl >= 10 and patron:
            _apply_warlock_patron_feature(char, patron, lvl, "favor", cha_mod, features, actions)
        
        # --- Mystic Arcanum (Level 11+) ---
        if lvl >= 11:
            arcanum_spells = []
            if lvl >= 11:
                arcanum_spells.append("6th")
            if lvl >= 13:
                arcanum_spells.append("7th")
            if lvl >= 15:
                arcanum_spells.append("8th")
            if lvl >= 17:
                arcanum_spells.append("9th")
            
            if not any("Mystic Arcanum" in f for f in features):
                features.append(f"Mystic Arcanum: {', '.join(arcanum_spells)}-level spell(s) castable 1/day without slot.")
        
        # --- Pact's Might (Level 14) ---
        if lvl >= 14 and patron:
            _apply_warlock_patron_feature(char, patron, lvl, "might", cha_mod, features, actions)
        
        # --- Pact's Ascendance (Level 20) ---
        if lvl >= 20 and patron:
            _apply_warlock_patron_feature(char, patron, lvl, "ascendance", cha_mod, features, actions)
    
    # ---- Wizard ----
    elif cls_name == "Wizard":
        int_mod = _ability_mod(abilities.get("INT", 10))
        lvl = int(char.get("level", 1))
        spell_dc = 8 + int_mod + lvl
        prepared_spells = max(1, int_mod + lvl)
        
        if not any("Spellcasting" in f for f in features):
            features.append(f"Spellcasting: Intelligence-based. Spellbook. Prepare {prepared_spells} spells. DC {spell_dc}.")
        
        # Familiar
        familiar_hp = lvl + int_mod
        familiar_int = max(6, int_mod)
        familiar_type = char.get("wizard_familiar_type", "Owl")
        char["familiar"] = {"hp": familiar_hp, "int": familiar_int, "type": familiar_type}
        
        # Create actual familiar entity if not exists
        if "companions" not in char:
            char["companions"] = []
        
        existing_familiar = next((c for c in char["companions"] if c.get("companion_type") == "familiar"), None)
        if not existing_familiar or existing_familiar.get("base_creature") != familiar_type:
            # Create or update familiar
            new_familiar = create_familiar(char, familiar_type)
            if new_familiar:
                char["companions"] = [c for c in char["companions"] if c.get("companion_type") != "familiar"]
                char["companions"].append(new_familiar)
        
        if not any("Familiar" in f for f in features):
            features.append(f"Familiar ({familiar_type}): HP {familiar_hp}, INT {familiar_int}. Telepathy 100 ft. Deliver touch spells at L6.")
        
        if not any("Ritual Adept" in f for f in features):
            features.append("Ritual Adept: Cast ritual spells from spellbook without preparing them.")
        
        # School Specialization at level 3+
        if lvl >= 3:
            school = char.get("wizard_school")
            if school:
                _apply_wizard_school_feature(char, school, lvl, int_mod, spell_dc, features, actions)
            else:
                if not any("Magic School" in f for f in features):
                    features.append("Magic School Specialization: Choose a school for bonus features.")
                char["pending_wizard_school"] = True
        
        # School Mastery at level 6+
        if lvl >= 6 and char.get("wizard_school"):
            _apply_wizard_school_feature(char, char["wizard_school"], lvl, int_mod, spell_dc, features, actions, tier="mastery")
        
        # Spell Mastery at level 18+
        if lvl >= 18:
            if not any("Spell Mastery" in f for f in features):
                features.append("Spell Mastery: Choose one 1st and one 2nd level spell. Cast at will at lowest level.")
        
        # Arcane Mastery at level 20
        if lvl >= 20:
            if not any("Arcane Mastery" in f for f in features):
                features.append("Arcane Mastery: Spells of chosen school cast as 1 slot higher. Concentrate on 2 spells of different schools.")
    
    # ---- Spellblade ----
    elif cls_name == "Spellblade":
        int_mod = _ability_mod(abilities.get("INT", 10))
        lvl = int(char.get("level", 1))
        bab = int(char.get("bab", 0))
        
        if not any("Weapon Bond" in f for f in features):
            features.append("Weapon Bond: Summon bonded weapon as Bonus Action. Can't be disarmed. Use as spell focus.")
        
        if not any("Spellcasting" in f for f in features):
            features.append("Spellcasting: Intelligence-based half-caster. Prepare spells after rest.")
        
        if not any("Arcane Channeling" in f for f in features):
            features.append("Arcane Channeling: Deliver touch spells through weapon attacks.")
        
        if not any(a.get("name") == "Summon Bonded Weapon" for a in actions):
            actions.append({
                "name": "Summon Bonded Weapon",
                "action_type": "bonus",
                "description": "Bonus Action: Summon your bonded weapon to your hand.",
            })
        
        # Arcane Surge at level 3+
        if lvl >= 3:
            ensure_resource(char, "Arcane Surge", 1)
            if not any("Arcane Surge" in f for f in features):
                features.append("Arcane Surge: Once per day, empower yourself for 1 minute (+1d4 force on attacks, +1d6 on channeled spells).")
            
            if not any(a.get("name") == "Arcane Surge" for a in actions):
                actions.append({
                    "name": "Arcane Surge",
                    "resource": "Arcane Surge",
                    "action_type": "bonus",
                    "description": "Bonus Action: For 1 minute, +1d4 force damage on weapon attacks, +1d6 on channeled spells.",
                })
        
        # Arcane Deflection at level 4+
        if lvl >= 4:
            if not any("Arcane Deflection" in f for f in features):
                features.append(f"Arcane Deflection: Add +{int_mod} to AC against spell attacks targeting you.")
        
        # Blade of Power at level 5+
        if lvl >= 5:
            blade_bonus = 1
            if lvl >= 15:
                blade_bonus = 3
            elif lvl >= 10:
                blade_bonus = 2
            
            char["blade_of_power_bonus"] = blade_bonus
            if not any("Blade of Power" in f for f in features):
                features.append(f"Blade of Power: Bonded weapon grants +{blade_bonus} to attack and damage rolls.")
            
            # Armored Arcana
            if not any("Armored Arcana" in f for f in features):
                features.append("Armored Arcana: Proficiency with medium armor without hindering spellcasting.")
        
        # Enhanced Channeling at level 6+ (SPELL SLOT CONSUMPTION)
        if lvl >= 6:
            if not any("Enhanced Channeling" in f for f in features):
                features.append("Enhanced Channeling: When using Arcane Channeling, expend additional spell slot for +1d6 damage per slot level.")
            
            if not any(a.get("name") == "Enhanced Channeling" for a in actions):
                actions.append({
                    "name": "Enhanced Channeling",
                    "action_type": "free",
                    "resource": "Spell Slots",
                    "description": "On Arcane Channeling: Expend additional spell slot for +1d6 force damage per slot level expended.",
                    "consumes_spell_slot": True,
                    "slot_damage_per_level": "1d6",
                })
            
            # Extra Attack
            if not any("Extra Attack" in f for f in features):
                features.append("Extra Attack: Attack twice when taking the Attack action. Can replace one attack with a cantrip.")
            char["extra_attack"] = True
        
        # Arcane Absorption at level 8+
        if lvl >= 8:
            if not any("Arcane Absorption" in f for f in features):
                features.append("Arcane Absorption: When Arcane Deflection causes a spell to miss, heal HP equal to spell level.")
        
        # Touch of Destruction at level 9+
        if lvl >= 9:
            if not any("Touch of Destruction" in f for f in features):
                features.append(f"Touch of Destruction: On weapon hit with touch spell, deal +{int_mod} force damage.")
        
        # Arcane Reflection at level 10+
        if lvl >= 10:
            ensure_resource(char, "Arcane Reflection", 1)
            if not any("Arcane Reflection" in f for f in features):
                features.append("Arcane Reflection: Reaction to redirect spell requiring save to another target within range.")
            
            if not any(a.get("name") == "Arcane Reflection" for a in actions):
                actions.append({
                    "name": "Arcane Reflection",
                    "resource": "Arcane Reflection",
                    "action_type": "reaction",
                    "description": f"Reaction: Redirect a spell requiring a save to another creature. Use your spell save DC ({8 + int_mod + lvl}).",
                })
        
        # Ravaging Blade at level 12+
        if lvl >= 12:
            if not any("Ravaging Blade" in f for f in features):
                features.append("Ravaging Blade: On weapon hit, negate one magical shield effect (Shield, Mage Armor) for 1 turn.")
        
        # Improved Arcane Channeling at level 13+
        if lvl >= 13:
            if not any("Improved Arcane Channeling" in f for f in features):
                features.append("Improved Arcane Channeling: Cast touch spells as part of Attack action. Each hit delivers the spell.")
        
        # Spellstrike Mastery at level 15+ (SPELL SLOT CONSUMPTION)
        if lvl >= 15:
            if not any("Spellstrike Mastery" in f for f in features):
                features.append("Spellstrike Mastery: On melee hit, expend spell slot for +1d6 force damage per slot level.")
            
            if not any(a.get("name") == "Spellstrike Mastery" for a in actions):
                actions.append({
                    "name": "Spellstrike Mastery",
                    "action_type": "free",
                    "resource": "Spell Slots",
                    "description": "On melee hit: Expend spell slot for force damage equal to 1d6 per slot level.",
                    "consumes_spell_slot": True,
                    "slot_damage_per_level": "1d6",
                })
        
        # Arcane Sight at level 16+
        if lvl >= 16:
            char["truesight"] = 30
            if not any("Arcane Sight" in f for f in features):
                features.append("Arcane Sight: You gain Truesight within 30 feet.")
        
        # Arcane Barrier at level 17+
        if lvl >= 17:
            if not any("Arcane Barrier" in f for f in features):
                features.append("Arcane Barrier: After dispelling/countering, gain spell level bonus to saves vs spells and DR vs magical damage.")
        
        # Arcane Mastery at level 18+ (SPELL SLOT CONSUMPTION - 5th level+)
        if lvl >= 18:
            if not any("Arcane Mastery" in f for f in features):
                features.append("Arcane Mastery: Bonus Action, expend 5th+ slot to empower weapon for 1 min (+2d6 damage, 30ft range, knockback + stun).")
            
            if not any(a.get("name") == "Arcane Mastery" for a in actions):
                actions.append({
                    "name": "Arcane Mastery",
                    "action_type": "bonus",
                    "resource": "Spell Slots",
                    "description": f"Bonus Action: Expend 5th+ slot. For 1 min: +2d6 damage, 30ft weapon range, hits force CON save (DC {8 + int_mod + lvl}) or knockback 10ft + Stunned.",
                    "consumes_spell_slot": True,
                    "min_slot_level": 5,
                    "duration": "1 minute",
                })
        
        # Blade of the Arcane Master at level 20 (SPELL SLOT CONSUMPTION - 3rd level+)
        if lvl >= 20:
            ensure_resource(char, "Blade of Arcane Master", 1)
            if not any("Blade of the Arcane Master" in f for f in features):
                features.append("Blade of the Arcane Master: 1 min focus = +3 weapon, +2d6 force. Once/round, expend 3rd+ slot for +(slot level × 2) force.")
            
            if not any(a.get("name") == "Blade of the Arcane Master" for a in actions):
                actions.append({
                    "name": "Blade of the Arcane Master",
                    "resource": "Blade of Arcane Master",
                    "action_type": "action",
                    "description": "Action (1 min): For 1 hour, weapon is +3, +2d6 force. Once/round, expend 3rd+ slot for +(slot level × 2) force damage.",
                    "duration": "1 hour",
                })
            
            if not any(a.get("name") == "Arcane Master Strike" for a in actions):
                actions.append({
                    "name": "Arcane Master Strike",
                    "action_type": "free",
                    "resource": "Spell Slots",
                    "description": "Once/round during Blade of the Arcane Master: Expend 3rd+ slot for +(slot level × 2) force damage.",
                    "consumes_spell_slot": True,
                    "min_slot_level": 3,
                    "damage_formula": "slot_level * 2",
                })
    
    # ---- Knight ----
    elif cls_name == "Knight":
        cha_mod = _ability_mod(abilities.get("CHA", 10))
        str_mod = _ability_mod(abilities.get("STR", 10))
        lvl = int(char.get("level", 1))
        
        # Martial Die scales: d6 -> d8 at 6, d10 at 11, d12 at 16
        if lvl >= 16:
            die_size = "d12"
        elif lvl >= 11:
            die_size = "d10"
        elif lvl >= 6:
            die_size = "d8"
        else:
            die_size = "d6"
        
        # Martial Dice count: 4 base, +1 at 7 and 15
        martial_dice_count = 4
        if lvl >= 15:
            martial_dice_count = 6
        elif lvl >= 7:
            martial_dice_count = 5
        
        ensure_resource(char, "Martial Dice", martial_dice_count)
        char["knight_die_size"] = die_size
        
        # Maneuver DC
        maneuver_dc = 8 + cha_mod + char.get("proficiency_bonus", 2)
        char["maneuver_dc"] = maneuver_dc
        
        # Maneuvers known: 3 at L1, 5 at L3, 7 at L7, 9 at L15
        maneuvers_known = 3
        if lvl >= 15:
            maneuvers_known = 9
        elif lvl >= 7:
            maneuvers_known = 7
        elif lvl >= 3:
            maneuvers_known = 5
        
        char["max_knight_maneuvers"] = maneuvers_known
        
        # Challenge damage bonus: +2 at L1, +3 at L5, +4 at L10, +5 at L15, +6 at L20
        challenge_damage = 2
        if lvl >= 20:
            challenge_damage = 6
        elif lvl >= 15:
            challenge_damage = 5
        elif lvl >= 10:
            challenge_damage = 4
        elif lvl >= 5:
            challenge_damage = 3
        
        char["challenge_damage_bonus"] = challenge_damage
        
        if not any("Martial Die" in f for f in features):
            features.append(f"Martial Die: {martial_dice_count} dice ({die_size}). Add to attacks, damage, checks, saves, or fuel maneuvers.")
        
        # Check if we need to select maneuvers
        selected_maneuvers = char.get("knight_maneuvers", [])
        if len(selected_maneuvers) < maneuvers_known:
            char["pending_knight_maneuvers"] = maneuvers_known - len(selected_maneuvers)
        
        # Apply selected maneuvers
        _apply_knight_maneuvers(char, selected_maneuvers, die_size, maneuver_dc, actions)
        
        # Knight's Challenge
        if not any("Knight's Challenge" in f for f in features):
            features.append(f"Knight's Challenge: Bonus action, challenge a creature within 30ft. +{challenge_damage} damage, +2 on attacks, target has -2 on saves vs you.")
        _apply_knight_challenge(char, challenge_damage, actions)
        
        # Protection Fighting Style at level 1
        if not any("Protection Fighting Style" in f for f in features):
            features.append("Protection Fighting Style: Reaction when ally within 5ft is attacked, impose -2 penalty on the attack.")
        grant_fighting_style(char, 1)
        
        if not any(a.get("name") == "Protection" for a in actions):
            actions.append({
                "name": "Protection",
                "action_type": "reaction",
                "description": f"Reaction: When a creature within 5ft is attacked, impose -2 penalty on the attack roll. Can expend Martial Die to add result to ally's AC.",
            })
        
        # Mounted Companion at level 2+
        if lvl >= 2:
            if not any("Mounted Companion" in f for f in features):
                features.append("Mounted Companion: Gain a loyal War Horse mount. Mount can Dodge or Attack as free action on your turn.")
            
            if not any("Mounted Combat" in f for f in features):
                features.append("Mounted Combat: While mounted, make one melee attack as bonus action after Dash or Disengage.")
            
            # Create mount as a full combat companion (like Ranger's Animal Companion)
            # Mount HP scales: base 19 + 5 per Knight level above 2
            mount_bonus_hp = (lvl - 2) * 5 if lvl > 2 else 0
            mount_hp = 19 + mount_bonus_hp
            
            # Mount AC improves at higher levels
            mount_ac = 11
            if lvl >= 10:
                mount_ac = 13
            elif lvl >= 6:
                mount_ac = 12
            
            # Mount attack bonus scales with Knight level
            mount_attack_bonus = 6 + (lvl // 4)
            mount_damage_bonus = 4 + (lvl // 5)
            
            char["knight_mount"] = {
                "name": f"{char.get('name', 'Knight')}'s War Horse",
                "companion_type": "mount",
                "type": "beast",
                "size": "Large",
                "hp": mount_hp,
                "max_hp": mount_hp,
                "ac": mount_ac,
                "speed": 60,
                "abilities": {"STR": 18, "DEX": 12, "CON": 13, "INT": 2, "WIS": 12, "CHA": 7},
                "attacks": [
                    {"name": "Hooves", "to_hit": mount_attack_bonus, "damage": f"2d6+{mount_damage_bonus}", "damage_type": "bludgeoning"}
                ],
                "owner_name": char.get("name", "Knight"),
                "owner_class": "Knight",
                "special_actions": [
                    {"name": "Trample", "description": "If the horse moves 20+ ft straight toward a creature, it can make a Hooves attack as bonus action. Target must succeed DEX save or be knocked prone."},
                ],
                "traits": [
                    "Trampling Charge: Move 20+ ft straight, bonus Hooves attack, may knock prone.",
                    "War Trained: Does not flee from combat. +2 on saves vs frightened.",
                ],
            }
            char["has_mount_companion"] = True
            
            if not any(a.get("name") == "Mounted Strike" for a in actions):
                actions.append({
                    "name": "Mounted Strike",
                    "action_type": "bonus",
                    "requires_mounted": True,
                    "description": "Bonus action after Dash/Disengage while mounted: Make one melee weapon attack. Can expend Martial Die to add to attack or damage.",
                })
            
            if not any(a.get("name") == "Command Mount" for a in actions):
                actions.append({
                    "name": "Command Mount",
                    "action_type": "free",
                    "description": "Free action: Command mount to Dodge, Dash, Disengage, or Attack (Hooves).",
                })
        
        # Bulwark of Defense at level 3+
        if lvl >= 3:
            bulwark_dc = 8 + cha_mod + lvl
            char["bulwark_dc"] = bulwark_dc
            if not any("Bulwark of Defense" in f for f in features):
                features.append(f"Bulwark of Defense: Creatures within 5ft have movement halved unless they pass DEX save (DC {bulwark_dc}).")
        
        # Test of Mettle at level 4+
        if lvl >= 4:
            mettle_dc = 8 + cha_mod + lvl
            char["test_of_mettle_dc"] = mettle_dc
            if not any("Test of Mettle" in f for f in features):
                features.append(f"Test of Mettle: Action, force creature within 30ft to WIS save (DC {mettle_dc}) or attack only you until end of its next turn.")
            
            if not any(a.get("name") == "Test of Mettle" for a in actions):
                actions.append({
                    "name": "Test of Mettle",
                    "action_type": "action",
                    "save_type": "WIS",
                    "save_dc": mettle_dc,
                    "description": f"Action: Force creature within 30ft to WIS save (DC {mettle_dc}) or attack only you. Can expend Martial Die to increase DC.",
                })
        
        # Extra Attack at level 5+
        if lvl >= 5:
            char["extra_attack"] = 1
            if not any("Extra Attack" in f for f in features):
                features.append("Extra Attack: Attack twice when you take the Attack action.")
            
            if not any("Vigilant Defender" in f for f in features):
                features.append(f"Vigilant Defender: DC for enemies to avoid your OA via Disengage/Acrobatics increases by {lvl}.")
        
        # Shield Ally at level 6+
        if lvl >= 6:
            if not any("Shield Ally" in f for f in features):
                features.append(f"Shield Ally: Reaction when ally within 5ft is hit, reduce damage by {cha_mod} + Martial Die.")
            
            if not any(a.get("name") == "Shield Ally" for a in actions):
                actions.append({
                    "name": "Shield Ally",
                    "action_type": "reaction",
                    "resource": "Martial Dice",
                    "description": f"Reaction: When ally within 5ft is hit, reduce damage by {cha_mod} + Martial Die ({die_size}).",
                })
        
        # Chivalric Code at level 7+
        if lvl >= 7:
            if not any("Chivalric Code" in f for f in features):
                features.append("Chivalric Code: Reaction to reroll failed save vs charmed/frightened. Can add Martial Die to reroll.")
        
        # Call to Battle at level 8+
        if lvl >= 8:
            if not any("Call to Battle" in f for f in features):
                features.append("Call to Battle: Action, allies within 30ft can attempt save to end one magical effect. Can add Martial Die to each save.")
            
            if not any(a.get("name") == "Call to Battle" for a in actions):
                actions.append({
                    "name": "Call to Battle",
                    "action_type": "action",
                    "resource": "Martial Dice",
                    "description": "Action: All allies within 30ft who can hear you may attempt a save to end one magical effect. Expend Martial Die to add to each save.",
                })
        
        # Cavalier's Fury at level 9+
        if lvl >= 9:
            if not any("Cavalier's Fury" in f for f in features):
                features.append("Cavalier's Fury: While mounted, charge 20ft+ to make bonus action melee attack. Add Martial Die to damage.")
        
        # Gallant Defense at level 10+
        if lvl >= 10:
            gallant_uses = max(1, cha_mod)
            ensure_resource(char, "Gallant Defense", gallant_uses)
            if not any("Gallant Defense" in f for f in features):
                features.append(f"Gallant Defense ({gallant_uses}/long rest): Reaction when ally within 10ft would drop to 0 HP, become the attack's target instead.")
            
            if not any(a.get("name") == "Gallant Defense" for a in actions):
                actions.append({
                    "name": "Gallant Defense",
                    "action_type": "reaction",
                    "resource": "Gallant Defense",
                    "description": "Reaction: When ally within 10ft is hit by attack that would drop them to 0 HP, move to their space and become the target.",
                })
            
            # Second Fighting Style
            if not any("Second Fighting Style" in f for f in features):
                features.append("Second Fighting Style: Gain an additional Fighting Style feat.")
            grant_fighting_style(char, 2)
        
        # Martial Surge at level 11+
        if lvl >= 11:
            ensure_resource(char, "Martial Surge", 1)
            if not any("Martial Surge" in f for f in features):
                features.append("Martial Surge (1/rest): Regain 2 expended Martial Dice.")
            
            if not any(a.get("name") == "Martial Surge" for a in actions):
                actions.append({
                    "name": "Martial Surge",
                    "action_type": "free",
                    "resource": "Martial Surge",
                    "description": "Free action: Regain 2 expended Martial Dice.",
                })
        
        # Daunting Challenge at level 12+
        if lvl >= 12:
            daunting_dc = 8 + cha_mod
            if not any("Daunting Challenge" in f for f in features):
                features.append(f"Daunting Challenge: When using Knight's Challenge, expend Martial Die to force WIS save (DC {daunting_dc} + die) or Frightened for 1 min.")
        
        # Relentless Pursuit at level 13+
        if lvl >= 13:
            if not any("Relentless Pursuit" in f for f in features):
                features.append("Relentless Pursuit: Reaction when challenged target Dashes/Disengages, move half speed toward them and attack.")
            
            if not any(a.get("name") == "Relentless Pursuit" for a in actions):
                actions.append({
                    "name": "Relentless Pursuit",
                    "action_type": "reaction",
                    "description": "Reaction: When your challenged target Dashes or Disengages, move up to half your speed toward them without OA and make a weapon attack.",
                })
        
        # Shield of the Righteous at level 14+
        if lvl >= 14:
            if not any("Shield of the Righteous" in f for f in features):
                features.append(f"Shield of the Righteous: Reaction when taking damage, expend Martial Die to reduce damage by die + {cha_mod}.")
        
        # Heroic Intervention at level 15+
        if lvl >= 15:
            heroic_uses = max(1, cha_mod)
            ensure_resource(char, "Heroic Intervention", heroic_uses)
            if not any("Heroic Intervention" in f for f in features):
                features.append(f"Heroic Intervention ({heroic_uses}/long rest): Reaction when ally within 10ft is crit or drops to 0 HP, move adjacent and reduce damage by Martial Die + {cha_mod}.")
            
            if not any(a.get("name") == "Heroic Intervention" for a in actions):
                actions.append({
                    "name": "Heroic Intervention",
                    "action_type": "reaction",
                    "resource": "Heroic Intervention",
                    "description": f"Reaction: When ally within 10ft is crit or drops to 0 HP, move adjacent and reduce damage by {die_size} + {cha_mod}.",
                })
        
        # Bond of Loyalty at level 16+
        if lvl >= 16:
            if not any("Bond of Loyalty" in f for f in features):
                features.append(f"Bond of Loyalty: Action, expend Martial Die to grant all allies within 30ft temp HP = {cha_mod} + die.")
            
            if not any(a.get("name") == "Bond of Loyalty" for a in actions):
                actions.append({
                    "name": "Bond of Loyalty",
                    "action_type": "action",
                    "resource": "Martial Dice",
                    "description": f"Action: Expend Martial Die. All allies within 30ft gain temp HP = {cha_mod} + {die_size}.",
                })
        
        # Unshakable Presence at level 17+
        if lvl >= 17:
            if not any("Unshakable Presence" in f for f in features):
                features.append(f"Unshakable Presence: While conscious, allies within 10ft gain +{cha_mod} on saves vs fear and charm.")
        
        # Gallant Nature at level 18+
        if lvl >= 18:
            if not any("Gallant Nature" in f for f in features):
                features.append(f"Gallant Nature: Add {lvl} to Diplomacy checks with nobility/royalty. Immune to charmed and frightened.")
            char.setdefault("condition_immunities", [])
            if "Charmed" not in char["condition_immunities"]:
                char["condition_immunities"].append("Charmed")
            if "Frightened" not in char["condition_immunities"]:
                char["condition_immunities"].append("Frightened")
        
        # Challenge Mastery at level 19+
        if lvl >= 19:
            if not any("Challenge Mastery" in f for f in features):
                features.append("Challenge Mastery: You can have two Knight's Challenge effects active at the same time.")
            char["max_challenges"] = 2
        
        # Loyal Beyond Death at level 20
        if lvl >= 20:
            ensure_resource(char, "Loyal Beyond Death", 1)
            if not any("Loyal Beyond Death" in f for f in features):
                features.append(f"Loyal Beyond Death (1/day): When reduced to 0 HP but not killed, reaction to gain temp HP = {cha_mod} + Martial Die.")
            
            if not any(a.get("name") == "Loyal Beyond Death" for a in actions):
                actions.append({
                    "name": "Loyal Beyond Death",
                    "action_type": "reaction",
                    "resource": "Loyal Beyond Death",
                    "description": f"Reaction: When reduced to 0 HP (not killed), gain temp HP = {cha_mod} + {die_size}.",
                })
    
    # ---- Samurai ----
    elif cls_name == "Samurai":
        cha_mod = _ability_mod(abilities.get("CHA", 10))
        wis_mod = _ability_mod(abilities.get("WIS", 10))
        str_mod = _ability_mod(abilities.get("STR", 10))
        lvl = int(char.get("level", 1))
        
        # Ki Pool scales with level
        ki_pool = lvl + 1  # 2 at level 1, 3 at level 2, etc. capped at 20
        if lvl >= 19:
            ki_pool = 20
        
        ensure_resource(char, "Ki", ki_pool)
        char["ki_pool_max"] = ki_pool
        
        # Ki Save DC = 8 + 1/2 level + CHA mod
        ki_dc = 8 + (lvl // 2) + cha_mod
        char["ki_save_dc"] = ki_dc
        
        # Daisho Proficiency at level 1
        if not any("Daisho Proficiency" in f for f in features):
            features.append("Daisho Proficiency: Proficient with bastard sword (katana) as one-handed and short sword (wakizashi). +1 AC when wielding both; draw both as one action.")
        
        # Add Daisho AC bonus tracking
        char["daisho_ac_bonus"] = 1  # Applied when wielding both weapons
        
        # Fighting Style at level 1
        if not any("Fighting Style" in f for f in features):
            features.append("Fighting Style: Gain a Fighting Style feat of your choice.")
        grant_fighting_style(char, 1)
        
        # Menacing Glare at level 1
        if not any("Menacing Glare" in f for f in features):
            features.append(f"Menacing Glare: Demoralize lasts 1 extra round. Shaken targets take -{cha_mod} penalty to fear saves vs you.")
        
        # Ki Features at level 2+
        if lvl >= 2:
            if not any("Ki" in f for f in features):
                features.append(f"Ki: {ki_pool} Ki points. DC {ki_dc}. Flurry of Blows, Step of the Wind, Patient Defense (1 Ki each).")
            
            # Ki Smite
            if not any("Ki Smite" in f for f in features):
                features.append(f"Ki Smite: Spend 1 Ki on attack to add +{cha_mod} to attack roll and damage.")
            
            if not any(a.get("name") == "Ki Smite" for a in actions):
                actions.append({
                    "name": "Ki Smite",
                    "action_type": "free",
                    "resource": "Ki",
                    "cost": 1,
                    "description": f"When attacking, spend 1 Ki to add +{cha_mod} to attack roll and +{cha_mod} to damage.",
                })
            
            if not any(a.get("name") == "Flurry of Blows" for a in actions):
                actions.append({
                    "name": "Flurry of Blows",
                    "action_type": "bonus",
                    "resource": "Ki",
                    "cost": 1,
                    "description": "Bonus action: Spend 1 Ki to make two unarmed strikes.",
                })
            
            if not any(a.get("name") == "Step of the Wind" for a in actions):
                actions.append({
                    "name": "Step of the Wind",
                    "action_type": "bonus",
                    "resource": "Ki",
                    "cost": 1,
                    "description": "Bonus action: Spend 1 Ki to Disengage or Dash.",
                })
            
            if not any(a.get("name") == "Patient Defense" for a in actions):
                actions.append({
                    "name": "Patient Defense",
                    "action_type": "bonus",
                    "resource": "Ki",
                    "cost": 1,
                    "description": "Bonus action: Spend 1 Ki to Dodge.",
                })
        
        # Iron Will at level 3+
        if lvl >= 3:
            if not any("Iron Will" in f for f in features):
                features.append(f"Iron Will: Add +{cha_mod} (CHA mod) to Wisdom saving throws.")
            char["iron_will_bonus"] = cha_mod
            
            if not any("Tactical Discipline" in f for f in features):
                features.append("Tactical Discipline: On successful Tactics check, allies within 30ft gain +1 to attack or AC until your next turn.")
        
        # Breaking Stare at level 4+
        if lvl >= 4:
            if not any("Breaking Stare" in f for f in features):
                features.append("Breaking Stare: Spend 1 Ki to ignore target's WIS mod on Intimidate. Upgrades at 9th, 13th, 15th, 18th.")
            
            if not any(a.get("name") == "Breaking Stare" for a in actions):
                actions.append({
                    "name": "Breaking Stare",
                    "action_type": "free",
                    "resource": "Ki",
                    "cost": 1,
                    "description": "Spend 1 Ki: Ignore target's WIS mod on Intimidate check.",
                })
            
            # Ki Surge
            ki_surge_uses = 1 if lvl < 12 else 2
            ensure_resource(char, "Ki Surge", ki_surge_uses)
            ki_surge_heal = 2 * lvl
            
            if not any("Ki Surge" in f for f in features):
                features.append(f"Ki Surge ({ki_surge_uses}/rest): Bonus action, spend 1 Ki to heal {ki_surge_heal} HP.")
            
            if not any(a.get("name") == "Ki Surge" for a in actions):
                actions.append({
                    "name": "Ki Surge",
                    "action_type": "bonus",
                    "resource": "Ki Surge",
                    "cost": 1,
                    "description": f"Bonus action: Spend 1 Ki and 1 Ki Surge use to heal {ki_surge_heal} HP (2 × Samurai level).",
                })
        
        # Resolute Defense at level 5+
        if lvl >= 5:
            if not any("Resolute Defense" in f for f in features):
                features.append(f"Resolute Defense: Add +{wis_mod} (WIS mod) to AC vs attacks of opportunity while not frightened.")
            
            if not any("Code of Iron" in f for f in features):
                features.append("Code of Iron: Use Honor in place of WIS/CHA for saves vs enchantment/fear if you declared your code before combat.")
        
        # Staredown at level 6+
        if lvl >= 6:
            staredown_bonus = lvl // 2
            if not any("Staredown" in f for f in features):
                features.append(f"Staredown: +{staredown_bonus} to Intimidate. Demoralize as bonus action.")
            char["staredown_bonus"] = staredown_bonus
            
            if not any(a.get("name") == "Staredown (Demoralize)" for a in actions):
                actions.append({
                    "name": "Staredown (Demoralize)",
                    "action_type": "bonus",
                    "description": f"Bonus action: Demoralize a creature (Intimidate check +{staredown_bonus}).",
                })
        
        # Battlefield Focus and Ki Alacrity at level 7+
        if lvl >= 7:
            ensure_resource(char, "Battlefield Focus", 1)
            if not any("Battlefield Focus" in f for f in features):
                features.append(f"Battlefield Focus (1/day): Use Tactics check for Initiative. Add +{wis_mod} (WIS mod) to Initiative.")
            
            if not any("Ki Alacrity" in f for f in features):
                features.append("Ki Alacrity: +2 Initiative while you have at least 1 Ki point.")
            char["ki_alacrity_bonus"] = 2
        
        # Iaijutsu Reflexes at level 8+
        if lvl >= 8:
            if not any("Iaijutsu Reflexes" in f for f in features):
                features.append(f"Iaijutsu Reflexes: First round of combat, add +{wis_mod} (WIS mod) to Initiative for turn order.")
        
        # Honor-Bound Duelist at level 9+
        if lvl >= 9:
            if not any("Honor-Bound Duelist" in f for f in features):
                features.append("Honor-Bound Duelist: In a duel, use Honor for Intimidate. +2 saves vs opponent's abilities.")
        
        # Mass Staredown at level 10+
        if lvl >= 10:
            if not any("Mass Staredown" in f for f in features):
                features.append("Mass Staredown: Demoralize all visible creatures with one Intimidate check.")
            
            if not any(a.get("name") == "Mass Staredown" for a in actions):
                actions.append({
                    "name": "Mass Staredown",
                    "action_type": "action",
                    "description": "Action: Make one Intimidate check to demoralize all visible creatures (each rolls save separately).",
                })
        
        # Iaijutsu Cut at level 11+
        if lvl >= 11:
            if not any("Iaijutsu Cut" in f for f in features):
                features.append("Iaijutsu Cut: First turn of combat, draw weapon and attack as free action vs lower initiative foe. Double damage if target is surprised.")
            
            if not any(a.get("name") == "Iaijutsu Cut" for a in actions):
                actions.append({
                    "name": "Iaijutsu Cut",
                    "action_type": "free",
                    "description": "First turn: Draw weapon and attack foe with lower initiative. Double damage if surprised/hasn't acted.",
                })
        
        # Ki Roar at level 12+
        if lvl >= 12:
            if not any("Ki Roar" in f for f in features):
                features.append(f"Ki Roar: Action, spend 1 Ki. All enemies within 60ft make CHA save (DC {ki_dc}) or become Shaken.")
            
            if not any(a.get("name") == "Ki Roar" for a in actions):
                actions.append({
                    "name": "Ki Roar",
                    "action_type": "action",
                    "resource": "Ki",
                    "cost": 1,
                    "save_type": "CHA",
                    "save_dc": ki_dc,
                    "description": f"Action: Spend 1 Ki. Enemies within 60ft make CHA save (DC {ki_dc}) or become Shaken.",
                })
        
        # Unflinching at level 13+
        if lvl >= 13:
            if not any("Unflinching" in f for f in features):
                features.append("Unflinching: Immune to being frightened.")
            char.setdefault("condition_immunities", [])
            if "Frightened" not in char["condition_immunities"]:
                char["condition_immunities"].append("Frightened")
        
        # Improved Staredown at level 14+
        if lvl >= 14:
            if not any("Improved Staredown" in f for f in features):
                features.append("Improved Staredown: Demoralize as a free action once per round.")
        
        # Ki Focused Strikes at level 15+
        if lvl >= 15:
            if not any("Ki Focused Strikes" in f for f in features):
                features.append(f"Ki Focused Strikes: While you have 1+ Ki, add +{cha_mod} to damage with katana/wakizashi. Attacks count as magical.")
            char["ki_focused_damage_bonus"] = cha_mod
        
        # Duelist's Grace at level 16+
        if lvl >= 16:
            if not any("Duelist's Grace" in f for f in features):
                features.append("Duelist's Grace: +2 AC and saves when fighting 1-on-1 (no other creatures within 10ft).")
        
        # One Cut at level 17+
        if lvl >= 17:
            ensure_resource(char, "One Cut", 1)
            if not any("One Cut" in f for f in features):
                features.append("One Cut (1/encounter): On hit, declare One Cut to make it a critical. Natural 20 = triple damage instead.")
            
            if not any(a.get("name") == "One Cut" for a in actions):
                actions.append({
                    "name": "One Cut",
                    "action_type": "free",
                    "resource": "One Cut",
                    "description": "On hit: Declare One Cut to make it a critical hit (double damage). Natural 20 = triple damage.",
                })
        
        # Dominating Stare at level 18+
        if lvl >= 18:
            ensure_resource(char, "Intimidate Reroll", 1)
            if not any("Dominating Stare" in f for f in features):
                features.append("Dominating Stare: Shaken/frightened/panicked creatures take -2 to saves and contested checks vs you. Reroll 1 failed Intimidate/day.")
        
        # Kensei's Wrath at level 19+
        if lvl >= 19:
            if not any("Kensei's Wrath" in f for f in features):
                features.append("Kensei's Wrath: Bonus action, spend 2 Ki. Double crit range, Haste effect, resistance to all damage (except radiant/necrotic).")
            
            if not any(a.get("name") == "Kensei's Wrath" for a in actions):
                actions.append({
                    "name": "Kensei's Wrath",
                    "action_type": "bonus",
                    "resource": "Ki",
                    "cost": 2,
                    "description": "Bonus action: Spend 2 Ki. Double critical range, gain Haste, resistance to all damage except radiant/necrotic.",
                })
        
        # Frightful Presence at level 20
        if lvl >= 20:
            ensure_resource(char, "Frightful Presence", 1)
            frightful_dc = 20 + cha_mod
            if not any("Frightful Presence" in f for f in features):
                features.append(f"Frightful Presence: On drawing blade or killing, enemies within 30ft CHA save (DC {frightful_dc}). 4 HD or less = Panicked, 5-19 HD = Shaken. Add Samurai level to attack/damage vs frightened foes.")
            
            if not any(a.get("name") == "Frightful Presence" for a in actions):
                actions.append({
                    "name": "Frightful Presence",
                    "action_type": "free",
                    "resource": "Frightful Presence",
                    "save_type": "CHA",
                    "save_dc": frightful_dc,
                    "description": f"On draw/kill: Enemies within 30ft CHA save (DC {frightful_dc}). ≤4 HD = Panicked 4d6 rounds, 5-19 HD = Shaken 4d6 rounds. +{lvl} attack/damage vs frightened.",
                })
    
    # ---- Scout ----
    elif cls_name == "Scout":
        dex_mod = _ability_mod(abilities.get("DEX", 10))
        wis_mod = _ability_mod(abilities.get("WIS", 10))
        con_mod = _ability_mod(abilities.get("CON", 10))
        int_mod = _ability_mod(abilities.get("INT", 10))
        lvl = int(char.get("level", 1))
        
        # Skirmish damage scales with level
        if lvl >= 17:
            skirmish_dice = "5d6"
        elif lvl >= 13:
            skirmish_dice = "4d6"
        elif lvl >= 9:
            skirmish_dice = "3d6"
        elif lvl >= 5:
            skirmish_dice = "2d6"
        else:
            skirmish_dice = "1d6"
        
        # Skirmish AC bonus scales with level
        if lvl >= 19:
            skirmish_ac = 5
        elif lvl >= 15:
            skirmish_ac = 4
        elif lvl >= 11:
            skirmish_ac = 3
        elif lvl >= 7:
            skirmish_ac = 2
        else:
            skirmish_ac = 1
        
        char["skirmish_damage"] = skirmish_dice
        char["skirmish_ac_bonus"] = skirmish_ac
        
        # Skirmish at level 1
        if not any("Skirmish" in f for f in features):
            features.append(f"Skirmish: Move 10+ ft = +{skirmish_dice} damage and +{skirmish_ac} AC until next turn. Ranged within 30ft also applies.")
        
        # Agile Explorer at level 1
        if not any("Agile Explorer" in f for f in features):
            features.append("Agile Explorer: Ignore non-magical difficult terrain after moving 10ft. Climb/swim/crawl at 1.5x cost instead of 2x.")
        
        # Battle Fortitude at level 2+
        if lvl >= 2:
            if lvl >= 20:
                bf_bonus = 3
            elif lvl >= 11:
                bf_bonus = 2
            else:
                bf_bonus = 1
            
            char["battle_fortitude_bonus"] = bf_bonus
            
            if not any("Battle Fortitude" in f for f in features):
                features.append(f"Battle Fortitude: +{bf_bonus} to CON saves and Initiative (light armor only).")
            
            # Wild Reflexes
            ensure_resource(char, "Wild Reflexes", 1)
            if not any("Wild Reflexes" in f for f in features):
                features.append("Wild Reflexes (1/day): Reroll Initiative. Act normally when surprised.")
        
        # Fast Movement at level 3+
        if lvl >= 3:
            fast_move = 20 if lvl >= 11 else 10
            char["scout_fast_movement"] = fast_move
            
            if not any("Fast Movement" in f for f in features):
                features.append(f"Fast Movement: +{fast_move} ft speed (light armor only).")
            
            # Natural Explorer
            if not any("Natural Explorer" in f for f in features):
                features.append("Natural Explorer: Choose favored terrain (add level to related checks). Additional terrain at 6th and 10th.")
            
            # Trackless Step
            if not any("Trackless Step" in f for f in features):
                features.append("Trackless Step: Leave no trail in natural terrain. DC 20 to track you.")
        
        # Evasion at level 4+
        if lvl >= 4:
            if not any("Evasion" in f for f in features):
                features.append("Evasion: DEX save for half damage = no damage instead (light armor only).")
            char["has_evasion"] = True
            
            # Fighting Style
            if not any("Fighting Style" in f for f in features):
                features.append("Fighting Style: Gain a Fighting Style feat of your choice.")
            grant_fighting_style(char, 4)
        
        # Flawless Stride at level 5+
        if lvl >= 5:
            if not any("Flawless Stride" in f for f in features):
                features.append("Flawless Stride: Ignore all non-magical difficult terrain (not climbing/swimming).")
        
        # Camouflage at level 6+
        if lvl >= 6:
            if not any("Camouflage" in f for f in features):
                features.append("Camouflage: Use Stealth in natural terrain without cover (light armor only).")
        
        # Prey Sense at level 7+
        if lvl >= 7:
            if not any("Prey Sense" in f for f in features):
                features.append("Prey Sense: +2 bonus to track creatures you damaged in past hour. Know direction within 1 mile.")
        
        # Opportunistic Movement at level 8+
        if lvl >= 8:
            if not any("Opportunistic Movement" in f for f in features):
                features.append("Opportunistic Movement (1/round): After moving 10ft and hitting, move 5ft free without provoking.")
        
        # Mobile Scout at level 9+
        if lvl >= 9:
            if not any("Mobile Scout" in f for f in features):
                features.append("Mobile Scout: Full speed Stealth in natural terrain. Move through Large+ creature squares as difficult terrain.")
        
        # Terrain Mastery at level 10+
        if lvl >= 10:
            mastered_count = 2 if lvl >= 16 else 1
            if not any("Terrain Mastery" in f for f in features):
                features.append(f"Terrain Mastery ({mastered_count}): +5 Stealth/Perception, ignore magical difficult terrain, enemies can't use terrain vs you.")
        
        # Nimble Combatant at level 12+
        if lvl >= 12:
            if not any("Nimble Combatant" in f for f in features):
                features.append("Nimble Combatant: +1 AC vs opportunity attacks. Ignore prone movement penalty. Stand from prone = 5ft.")
        
        # Swift Ambush at level 14+
        if lvl >= 14:
            if not any("Swift Ambush" in f for f in features):
                features.append("Swift Ambush: Attack as part of Dash. Skirmish damage applies to all attacks after moving 10ft.")
        
        # Trail Lore at level 15+
        if lvl >= 15:
            if not any("Trail Lore" in f for f in features):
                features.append("Trail Lore: Perfectly recall paths traveled in past year. Leave hidden markers (DC 25 to notice).")
        
        # Free Movement at level 18+
        if lvl >= 18:
            if not any("Free Movement" in f for f in features):
                features.append("Free Movement: Constant freedom of movement effect (auto-escape grapples, ignore restraints/terrain). Light armor only.")
            char.setdefault("condition_immunities", [])
            for cond in ["Restrained", "Grappled"]:
                if cond not in char["condition_immunities"]:
                    char["condition_immunities"].append(cond)
        
        # Untouchable Hunter at level 20
        if lvl >= 20:
            if not any("Untouchable Hunter" in f for f in features):
                features.append("Untouchable Hunter: After moving 10ft and attacking, target can't react. Hide as bonus action. Double crit range vs surprised. Dash as bonus action. No opportunity attacks from movement.")
            
            if not any(a.get("name") == "Skirmish Attack" for a in actions):
                actions.append({
                    "name": "Skirmish Attack",
                    "action_type": "action",
                    "description": f"Attack after moving 10+ ft: +{skirmish_dice} damage. At 20th level: target can't react, Hide as bonus action.",
                })
            
            if not any(a.get("name") == "Swift Dash" for a in actions):
                actions.append({
                    "name": "Swift Dash",
                    "action_type": "bonus",
                    "description": "Dash as a bonus action. No opportunity attacks from movement.",
                })
    
    # ---- Marshal ----
    elif cls_name == "Marshal":
        cha_mod = _ability_mod(abilities.get("CHA", 10))
        lvl = int(char.get("level", 1))
        
        # Martial Die scales
        if lvl >= 15:
            die_size = "d12"
        elif lvl >= 11:
            die_size = "d10"
        elif lvl >= 7:
            die_size = "d8"
        else:
            die_size = "d6"
        
        # Marshal gets fewer dice but they're more versatile
        martial_dice_count = 2 + (lvl // 4)
        ensure_resource(char, "Martial Dice", martial_dice_count)
        
        char["marshal_die_size"] = die_size
        
        # Maneuvers known: 3 at L1, +2 at L3, L7, L15
        maneuvers_known = 3
        if lvl >= 3:
            maneuvers_known = 5
        if lvl >= 7:
            maneuvers_known = 7
        if lvl >= 15:
            maneuvers_known = 9
        
        char["max_marshal_maneuvers"] = maneuvers_known
        
        # Aura range scales
        aura_range = 30
        if lvl >= 20:
            aura_range = 120
        elif lvl >= 18:
            aura_range = 90
        elif lvl >= 7:
            aura_range = 60
        
        char["aura_range"] = aura_range
        
        if not any("Martial Die" in f for f in features):
            features.append(f"Martial Die: {martial_dice_count} dice ({die_size}). Add to attacks, damage, checks, saves, or fuel maneuvers.")
        
        # Check if we need to select maneuvers
        selected_maneuvers = char.get("marshal_maneuvers", [])
        if len(selected_maneuvers) < maneuvers_known:
            char["pending_marshal_maneuvers"] = maneuvers_known - len(selected_maneuvers)
        
        # Apply selected maneuvers
        _apply_marshal_maneuvers(char, selected_maneuvers, die_size, cha_mod, lvl, aura_range, actions)
        
        if not any("Fighting Style" in f for f in features):
            features.append("Fighting Style: Gain a Fighting Style feat.")
        grant_fighting_style(char, 1)
        
        # Minor Auras - number known increases
        minor_auras_known = 1
        if lvl >= 15:
            minor_auras_known = 4
        elif lvl >= 7:
            minor_auras_known = 3
        elif lvl >= 3:
            minor_auras_known = 2
        
        char["max_minor_auras"] = minor_auras_known
        
        if not any("Minor Auras" in f for f in features):
            features.append(f"Minor Auras: {minor_auras_known} known. +{max(0, cha_mod)} to allies within {aura_range} ft. Switch as Bonus Action.")
        
        if not any(a.get("name") == "Switch Aura" for a in actions):
            actions.append({
                "name": "Switch Aura",
                "action_type": "bonus",
                "description": f"Bonus Action: Switch your active Minor Aura to a different one. Range: {aura_range} ft.",
            })
        
        # Major Aura at level 2+
        if lvl >= 2:
            major_bonus = 1
            if lvl >= 18:
                major_bonus = 5
            elif lvl >= 14:
                major_bonus = 4
            elif lvl >= 10:
                major_bonus = 3
            elif lvl >= 6:
                major_bonus = 2
            
            char["major_aura_bonus"] = major_bonus
            if not any("Major Aura" in f for f in features):
                features.append(f"Major Aura: +{major_bonus} to attack, AC, DR, or saves for allies in {aura_range} ft.")
        
        # Aura of Courage at level 3+
        if lvl >= 3:
            if not any("Aura of Courage" in f for f in features):
                features.append(f"Aura of Courage: You and allies in {aura_range} ft are immune to Frightened.")
            
            if not any("Tactical Auras" in f for f in features):
                features.append("Tactical Auras: Maneuvers only affect creatures within your active auras.")
        
        # Extra Attack at level 5+
        if lvl >= 5:
            char["extra_attack"] = 1
            if not any("Extra Attack" in f for f in features):
                features.append("Extra Attack: Attack twice when you take the Attack action.")
        
        # Field Master at level 7+
        if lvl >= 7:
            if not any("Field Master" in f for f in features):
                features.append("Field Master: Maintain 2 Minor Auras and 1 Major Aura simultaneously.")
        
        # Tactical Mastery at level 9+ (every 2 levels)
        if lvl >= 9:
            masteries_known = 1 + ((lvl - 9) // 2)
            if lvl >= 17:
                masteries_known = 5
            elif lvl >= 15:
                masteries_known = 4
            elif lvl >= 13:
                masteries_known = 3
            elif lvl >= 11:
                masteries_known = 2
            
            char["max_tactical_masteries"] = masteries_known
            if not any("Tactical Mastery" in f for f in features):
                features.append(f"Tactical Mastery: {masteries_known} mastery(ies) known. Upgrade maneuvers/auras.")
        
        # Aura of the Battlelord at level 18+
        if lvl >= 18:
            if not any("Aura of the Battlelord" in f for f in features):
                features.append("Aura of the Battlelord: 2 Minor + 2 Major Auras. 90 ft range. Commanding Presence at will.")
        
        # Legendary Field Master at level 20
        if lvl >= 20:
            if not any("Legendary Field Master" in f for f in features):
                features.append("Legendary Field Master: 3 Minor + 2 Major Auras. 120 ft range. Bonus Action: grant ally one of your feats.")
    
    # ---- Swashbuckler ----
    elif cls_name == "Swashbuckler":
        dex_mod = _ability_mod(abilities.get("DEX", 10))
        cha_mod = _ability_mod(abilities.get("CHA", 10))
        int_mod = _ability_mod(abilities.get("INT", 10))
        lvl = int(char.get("level", 1))
        bab = int(char.get("bab", 0))
        
        # Determine Luck Die size based on level
        if lvl >= 20:
            luck_die = "d20"
            luck_die_max = 20
        elif lvl >= 16:
            luck_die = "d12"
            luck_die_max = 12
        elif lvl >= 12:
            luck_die = "d10"
            luck_die_max = 10
        elif lvl >= 8:
            luck_die = "d8"
            luck_die_max = 8
        elif lvl >= 4:
            luck_die = "d6"
            luck_die_max = 6
        else:
            luck_die = "d4"
            luck_die_max = 4
        
        char["luck_die"] = luck_die
        char["luck_die_max"] = luck_die_max
        
        # Calculate Luck Points (CHA mod, min 1, increases at certain levels)
        base_luck_points = max(1, cha_mod)
        # Additional luck points at levels 4, 7, 10, 13, 16, 19
        bonus_luck = 0
        if lvl >= 19:
            bonus_luck = 6
        elif lvl >= 16:
            bonus_luck = 5
        elif lvl >= 13:
            bonus_luck = 4
        elif lvl >= 10:
            bonus_luck = 3
        elif lvl >= 7:
            bonus_luck = 2
        elif lvl >= 4:
            bonus_luck = 1
        
        total_luck_points = base_luck_points + bonus_luck
        char["max_luck_points"] = total_luck_points
        ensure_resource(char, "Luck Points", total_luck_points)
        
        # --- Level 1 Features ---
        # Finesse Fighting
        char["finesse_fighting"] = True
        if not any("Finesse Fighting" in f for f in features):
            features.append("Finesse Fighting: Use DEX for attack rolls with light/one-handed piercing weapons. Add STR to damage if higher.")
        
        # Fighting Style (Dueling)
        if "Dueling" not in char.get("feats", []):
            char.setdefault("feats", []).append("Dueling")
        if not any("Fighting Style" in f for f in features):
            features.append("Fighting Style: Dueling - +2 damage when wielding a melee weapon in one hand and no other weapons.")
        
        # Luck Die
        if not any("Luck Die" in f for f in features):
            features.append(f"Luck Die ({luck_die}): Roll once per turn. 1 = auto-fail. 1-{luck_die_max//2} = subtract. >{luck_die_max//2} = add. Max = auto-succeed.")
        
        if not any(a.get("name") == "Roll Luck Die" for a in actions):
            actions.append({
                "name": "Roll Luck Die",
                "action_type": "free",
                "resource": "Luck Points",
                "description": f"Free Action (1/turn): Roll {luck_die}. Apply result to attack/damage/save/skill check.",
            })
        
        # --- Level 2 Features ---
        if lvl >= 2:
            # Canny Defense
            char["canny_defense"] = True
            if not any("Canny Defense" in f for f in features):
                features.append(f"Canny Defense: Add INT mod (+{int_mod}) to AC when wearing light/no armor, wielding one-handed melee, off-hand empty.")
            
            # Grace
            char["grace"] = True
            if not any("Grace" in f for f in features):
                features.append("Grace: +2 on DEX saving throws while you have at least 1 Luck Point.")
        
        # --- Level 3 Features ---
        if lvl >= 3:
            # Nimble Acrobat
            char["nimble_acrobat"] = True
            if not any("Nimble Acrobat" in f for f in features):
                features.append("Nimble Acrobat: Move through larger creatures' spaces. Add DEX to Acrobatics for tumbling/jumping. Ignore difficult terrain when moving 10+ ft.")
            
            # Parry
            if not any("Parry" in f for f in features):
                features.append(f"Parry: Reaction when hit by melee - roll {luck_die} + DEX mod ({dex_mod}) to reduce damage. Max roll = disarm attempt.")
            
            if not any(a.get("name") == "Parry" for a in actions):
                actions.append({
                    "name": "Parry",
                    "action_type": "reaction",
                    "description": f"Reaction: Reduce melee damage by {luck_die}+{dex_mod}. On max roll, attempt disarm.",
                })
            
            # Quick-Witted
            if "Insight" not in char.get("proficiencies", []):
                char.setdefault("proficiencies", []).append("Insight")
            if "Deception" not in char.get("proficiencies", []):
                char.setdefault("proficiencies", []).append("Deception")
            if not any("Quick-Witted" in f for f in features):
                features.append("Quick-Witted: Proficiency in Insight and Deception.")
            
            # Insightful Strike
            char["insightful_strike"] = True
            char["insightful_strike_bonus"] = int_mod
            if not any("Insightful Strike" in f for f in features):
                features.append(f"Insightful Strike: Add INT mod (+{int_mod}) to damage with finesse weapons (light/no armor). Not vs precision-immune.")
        
        # --- Level 4 Features ---
        if lvl >= 4:
            # Daring Strike
            if not any("Daring Strike" in f for f in features):
                features.append(f"Daring Strike: Bonus action, spend 1 Luck Point for extra {luck_die} damage. Max roll = target Frightened.")
            
            if not any(a.get("name") == "Daring Strike" for a in actions):
                actions.append({
                    "name": "Daring Strike",
                    "action_type": "bonus",
                    "resource": "Luck Points",
                    "description": f"Bonus Action: Spend 1 Luck Point. On melee hit, deal +{luck_die} damage. Max roll = target Frightened until end of its next turn.",
                })
            
            # Seductive Charm
            char["seductive_charm"] = True
            seductive_uses = max(1, cha_mod)
            ensure_resource(char, "Seductive Charm", seductive_uses)
            if not any("Seductive Charm" in f for f in features):
                features.append(f"Seductive Charm: {seductive_uses}/day, use Bluff to charm/seduce NPCs for secrets (Basic to Well-Guarded).")
            
            if not any(a.get("name") == "Seductive Charm" for a in actions):
                actions.append({
                    "name": "Seductive Charm",
                    "resource": "Seductive Charm",
                    "action_type": "action",
                    "description": "Action: Bluff check to extract secrets from attracted NPC. Fail by 5+ = suspicion. Natural 1 = hostility.",
                })
        
        # --- Level 5 Features ---
        if lvl >= 5:
            # Riposte
            char["riposte"] = True
            if not any("Riposte" in f for f in features):
                features.append("Riposte: Reaction when creature misses you with melee attack - make a melee attack against them.")
            
            if not any(a.get("name") == "Riposte" for a in actions):
                actions.append({
                    "name": "Riposte",
                    "action_type": "reaction",
                    "description": "Reaction: When a creature misses you with a melee attack, make a melee weapon attack against them.",
                })
            
            # Make My Own Luck
            char["make_my_own_luck"] = True
            ensure_resource(char, "Stored Luck Die", 1)
            if not any("Make My Own Luck" in f for f in features):
                features.append(f"Make My Own Luck: After rest, roll {luck_die} and store result. Use in place of any Luck Die roll within 24 hours.")
            
            if not any(a.get("name") == "Store Luck Die" for a in actions):
                actions.append({
                    "name": "Store Luck Die",
                    "resource": "Stored Luck Die",
                    "action_type": "special",
                    "description": f"After rest: Roll {luck_die} and note result. Use this result instead of rolling Luck Die once within 24 hours.",
                })
            
            # Lucky Reroll (formerly "Advantage or Disadvantage?")
            ensure_resource(char, "Reroll", 1)
            if not any("Lucky Reroll" in f for f in features):
                features.append("Lucky Reroll: 1/day, reroll any d20 roll. Must take second result.")
            
            if not any(a.get("name") == "Reroll" for a in actions):
                actions.append({
                    "name": "Reroll",
                    "resource": "Reroll",
                    "action_type": "free",
                    "description": "Free Action (1/day): Reroll any d20 roll. Must take the second result.",
                })
        
        # --- Level 6 Features ---
        if lvl >= 6:
            # Grace in Steel
            char["grace_in_steel"] = True
            if not any("Grace in Steel" in f for f in features):
                features.append("Grace in Steel: Luck abilities now work while wearing medium armor.")
            
            # Dazzling Feint
            if not any("Dazzling Feint" in f for f in features):
                features.append("Dazzling Feint: Bonus action to feint with CHA. Success = target Blinded until end of your next turn.")
            
            if not any(a.get("name") == "Dazzling Feint" for a in actions):
                actions.append({
                    "name": "Dazzling Feint",
                    "action_type": "bonus",
                    "description": f"Bonus Action: CHA-based feint. On success, target is Blinded until end of your next turn.",
                })
        
        # --- Level 7 Features ---
        if lvl >= 7:
            # Evasive Footwork (Evasion)
            char["evasion"] = True
            if not any("Evasive Footwork" in f for f in features):
                features.append("Evasive Footwork: Evasion - DEX save for half damage = no damage instead.")
            
            # Disarming Flourish
            if not any("Disarming Flourish" in f for f in features):
                features.append(f"Disarming Flourish: Bonus action, 1 Luck Point. Roll {luck_die}+CHA ({cha_mod}) to disarm. Max roll = also knock prone.")
            
            if not any(a.get("name") == "Disarming Flourish" for a in actions):
                actions.append({
                    "name": "Disarming Flourish",
                    "action_type": "bonus",
                    "resource": "Luck Points",
                    "description": f"Bonus Action: Spend 1 Luck Point. Roll {luck_die}+{cha_mod} to disarm target. Max roll = also knock prone.",
                })
        
        # --- Level 8 Features ---
        if lvl >= 8:
            # Precise Strike
            if lvl >= 20:
                precise_dice = "3d6"
            elif lvl >= 14:
                precise_dice = "2d6"
            else:
                precise_dice = "1d6"
            
            char["precise_strike"] = True
            char["precise_strike_dice"] = precise_dice
            if not any("Precise Strike" in f for f in features):
                features.append(f"Precise Strike: +{precise_dice} precision damage with finesse weapons (light/no armor). Not vs precision-immune.")
        
        # --- Level 9 Features ---
        if lvl >= 9:
            # Elusive Step (Uncanny Dodge)
            char["uncanny_dodge"] = True
            if not any("Elusive Step" in f for f in features):
                features.append("Elusive Step: Uncanny Dodge - Cannot be flanked or caught off-guard by visible creatures.")
            
            if not any(a.get("name") == "Uncanny Dodge" for a in actions):
                actions.append({
                    "name": "Uncanny Dodge",
                    "action_type": "reaction",
                    "description": "Reaction: Halve damage from an attack you can see.",
                })
            
            # Duelist's Wit
            ensure_resource(char, "Duelist's Wit", 1)
            if not any("Duelist's Wit" in f for f in features):
                features.append(f"Duelist's Wit: 1/short rest, add {luck_die} to any CHA-based skill or opposed check.")
            
            if not any(a.get("name") == "Duelist's Wit" for a in actions):
                actions.append({
                    "name": "Duelist's Wit",
                    "resource": "Duelist's Wit",
                    "action_type": "free",
                    "description": f"Free Action (1/short rest): Add {luck_die} to a CHA-based skill or opposed check.",
                })
        
        # --- Level 10 Features ---
        if lvl >= 10:
            # Deflection Mastery
            char["deflection_mastery"] = True
            if not any("Deflection Mastery" in f for f in features):
                features.append(f"Deflection Mastery: Reaction vs ranged attack within 30 ft. Roll {luck_die}. Above half = deflect (miss). Max = redirect to creature within 10 ft.")
            
            if not any(a.get("name") == "Deflection Mastery" for a in actions):
                actions.append({
                    "name": "Deflection Mastery",
                    "action_type": "reaction",
                    "description": f"Reaction: Roll {luck_die} vs ranged attack. >{luck_die_max//2} = deflect. Max = redirect to creature within 10 ft.",
                })
        
        # --- Level 12 Features ---
        if lvl >= 12:
            # Perfect Timing
            char["perfect_timing"] = True
            if not any("Perfect Timing" in f for f in features):
                features.append(f"Perfect Timing: Bonus action when missed by attack. Spend 1 Luck Point for opportunity attack. Max {luck_die} roll = regain Luck Point.")
            
            if not any(a.get("name") == "Perfect Timing" for a in actions):
                actions.append({
                    "name": "Perfect Timing",
                    "action_type": "bonus",
                    "resource": "Luck Points",
                    "description": f"Bonus Action (when missed): Spend 1 Luck Point. Make opportunity attack. If {luck_die} = max, regain the Luck Point.",
                })
        
        # --- Level 14 Features ---
        if lvl >= 14:
            # Death Defied
            char["death_defied"] = True
            if not any("Death Defied" in f for f in features):
                features.append(f"Death Defied: When reduced to 0 HP, spend 2 Luck Points to drop to 1 HP instead, heal {luck_die}, and Dodge as reaction.")
            
            if not any(a.get("name") == "Death Defied" for a in actions):
                actions.append({
                    "name": "Death Defied",
                    "action_type": "reaction",
                    "description": f"Reaction (at 0 HP): Spend 2 Luck Points. Drop to 1 HP, heal {luck_die}, take Dodge action.",
                })
            
            # Weakening Critical
            char["weakening_critical"] = True
            if not any("Weakening Critical" in f for f in features):
                features.append(f"Weakening Critical: On critical hit, roll {luck_die}. Reduce target's STR, DEX, or CON by result (min 1) for 1 minute.")
        
        # --- Level 16 Features ---
        if lvl >= 16:
            # Perfect Riposte
            char["perfect_riposte"] = True
            riposte_dc = 10 + (lvl // 2) + dex_mod
            char["perfect_riposte_dc"] = riposte_dc
            if not any("Perfect Riposte" in f for f in features):
                features.append(f"Perfect Riposte: When Riposte hits, target must make CON save DC {riposte_dc} or be Staggered (one action only) next turn.")
        
        # --- Level 17 Features ---
        if lvl >= 17:
            # Slippery Mind
            char["slippery_mind"] = True
            if not any("Slippery Mind" in f for f in features):
                features.append("Slippery Mind: If you fail a save vs enchantment, reroll after 1 round. One second chance only.")
        
        # --- Level 18 Features ---
        if lvl >= 18:
            # Supreme Grace
            char["supreme_grace"] = True
            if not any("Supreme Grace" in f for f in features):
                features.append("Supreme Grace: Add current Luck Points to all DEX-based skill checks and saving throws.")
        
        # --- Level 20 Features ---
        if lvl >= 20:
            # Master Duelist
            char["master_duelist"] = True
            if not any("Master Duelist" in f for f in features):
                features.append("Master Duelist: While 1+ Luck Points: Freedom of Movement, True Seeing, +2 on finesse melee attacks, 1/round auto-succeed DEX check/save, max Luck Die roll = regain 1 Luck Point.")
            
            char["freedom_of_movement"] = True
            char["truesight"] = 120
            char["master_duelist_bonus"] = 2  # +2 replaces advantage
    
    # ---- Shaman ----
    elif cls_name == "Shaman":
        wis_mod = _ability_mod(abilities.get("WIS", 10))
        con_mod = _ability_mod(abilities.get("CON", 10))
        cha_mod = _ability_mod(abilities.get("CHA", 10))
        lvl = int(char.get("level", 1))
        spell_dc = 8 + wis_mod + lvl
        
        # Get chosen totem spirit
        totem_spirit = char.get("shaman_totem_spirit", None)
        
        # --- Level 1 Features ---
        # Shaman Spellcasting
        prepared_spells = max(1, wis_mod + lvl)
        if not any("Shaman Spellcasting" in f for f in features):
            features.append(f"Shaman Spellcasting: Wisdom-based. Prepare {prepared_spells} spells. Spell DC {spell_dc}. Ritual casting.")
        
        # Totemic Magic - Totem Spirit selection
        if totem_spirit:
            # Apply totem bonus spells
            totem_spells = {
                "Bear": ["Barkskin", "Shield of Faith", "Enhance Ability", "Mirror Image", "Stoneskin", "Hold Person", "Stone Shape", "Guardian of Nature", "Wall of Stone", "Antilife Shell"],
                "Eagle": ["Thunderwave", "Feather Fall", "Fly", "Misty Step", "Call Lightning", "Wind Wall", "Greater Invisibility", "Storm Sphere", "Control Winds", "Destructive Wave"],
                "Wolf": ["Hunter's Mark", "Detect Magic", "Summon Beast", "Pass Without Trace", "Conjure Animals", "Haste", "Summon Greater Demon", "Grasping Vine", "Mass Cure Wounds", "Cloudkill"]
            }
            char["totem_bonus_spells"] = totem_spells.get(totem_spirit, [])
            if not any("Totemic Magic" in f for f in features):
                features.append(f"Totemic Magic ({totem_spirit}): Access to {totem_spirit} Spirit bonus spells.")
        else:
            char["pending_totem_spirit"] = True
            if not any("Totemic Magic" in f for f in features):
                features.append("Totemic Magic: ⚠️ Choose a Totem Spirit (Bear, Eagle, Wolf)!")
        
        # Spirit Guide - now includes a spirit animal companion
        turn_spirit_uses = max(1, 1 + wis_mod)
        ensure_resource(char, "Turn Spirit", turn_spirit_uses)
        
        # Create Spirit Guide companion based on totem spirit
        if totem_spirit:
            if "companions" not in char:
                char["companions"] = []
            
            # Check if spirit guide already exists
            existing_guide = next((c for c in char["companions"] if c.get("companion_type") == "spirit_guide"), None)
            totem_creature_map = {"Bear": "Black Bear", "Eagle": "Eagle", "Wolf": "Wolf"}
            expected_creature = totem_creature_map.get(totem_spirit, "Wolf")
            
            if not existing_guide or expected_creature.lower() not in existing_guide.get("name", "").lower():
                # Create or update spirit guide
                new_guide = create_spirit_guide(char, totem_spirit)
                if new_guide:
                    char["companions"] = [c for c in char["companions"] if c.get("companion_type") != "spirit_guide"]
                    char["companions"].append(new_guide)
            
            guide_name = totem_creature_map.get(totem_spirit, "Wolf")
            if not any("Spirit Guide" in f for f in features):
                features.append(f"Spirit Guide (Spirit {guide_name}): Ethereal companion that fights alongside you. Spiritual Guidance (commune with spirits), Turn Spirit ({turn_spirit_uses}/day), Ritual Aid (+2 on ritual checks). Reforms after long rest if defeated.")
        else:
            if not any("Spirit Guide" in f for f in features):
                features.append(f"Spirit Guide: ⚠️ Choose Totem Spirit for companion! Turn Spirit ({turn_spirit_uses}/day), Ritual Aid.")
        
        if not any(a.get("name") == "Turn Spirit" for a in actions):
            actions.append({
                "name": "Turn Spirit",
                "resource": "Turn Spirit",
                "action_type": "action",
                "description": f"Action: Spirits within 30 ft make WIS save DC {spell_dc} or are turned for 1 minute (flee, no actions).",
            })
        
        # Detect Spirits
        char["detect_spirits"] = True
        if not any("Detect Spirits" in f for f in features):
            features.append("Detect Spirits: Detect spirits within 60 ft radius - number, location, and hostility.")
        
        if not any(a.get("name") == "Detect Spirits" for a in actions):
            actions.append({
                "name": "Detect Spirits",
                "action_type": "action",
                "description": "Action: Detect spirits within 60 ft. Learn number, location, and whether hostile or benign.",
            })
        
        # --- Level 2 Features ---
        if lvl >= 2:
            # Spirit Sight
            char["spirit_sight"] = True
            char["see_invisible"] = True
            char["see_ethereal"] = 30
            if not any("Spirit Sight" in f for f in features):
                features.append("Spirit Sight: See invisible creatures, ethereal beings (30 ft), and true forms of spirits (unaffected by illusions/disguises).")
            
            # Divination Insight
            char["divination_insight"] = True
            ensure_resource(char, "Future Insight", 1)
            if not any("Divination Insight" in f for f in features):
                features.append("Divination Insight: Divination rituals cast in half time. Spirit Guide aids interpretation. Future Insight (1/long rest): +2 bonus on one roll within 10 min.")
            
            if not any(a.get("name") == "Future Insight" for a in actions):
                actions.append({
                    "name": "Future Insight",
                    "resource": "Future Insight",
                    "action_type": "free",
                    "description": "Free Action (1/long rest): After Divination ritual, gain +2 bonus on one ability check, saving throw, or attack roll within 10 minutes.",
                })
            
            # Chastise Spirits
            chastise_uses = max(1, 3 + cha_mod)
            chastise_damage = f"{lvl}d6"
            ensure_resource(char, "Chastise Spirits", chastise_uses)
            if not any("Chastise Spirits" in f for f in features):
                features.append(f"Chastise Spirits ({chastise_uses}/day): Deal {chastise_damage} damage to spirits/incorporeal within 30 ft (WIS save DC {10 + lvl + cha_mod} for half).")
            
            if not any(a.get("name") == "Chastise Spirits" for a in actions):
                actions.append({
                    "name": "Chastise Spirits",
                    "resource": "Chastise Spirits",
                    "action_type": "action",
                    "damage": chastise_damage,
                    "damage_type": "radiant",
                    "save_dc": 10 + lvl + cha_mod,
                    "save_type": "WIS",
                    "description": f"Action: Deal {chastise_damage} to spirits/incorporeal in 30 ft. WIS save DC {10 + lvl + cha_mod} for half. Affects Ethereal Plane.",
                })
        
        # --- Level 3 Features ---
        if lvl >= 3:
            # Spirit Blessing - aura range scales
            if lvl >= 15:
                blessing_range = 30
            elif lvl >= 9:
                blessing_range = 15
            else:
                blessing_range = 10
            
            char["spirit_blessing_range"] = blessing_range
            
            if totem_spirit == "Bear":
                char["spirit_blessing_bear"] = True
                if not any("Spirit Blessing" in f for f in features):
                    features.append(f"Spirit Blessing ({blessing_range} ft): Toughness - You and allies gain +{wis_mod} HP and resistance to poison damage.")
            elif totem_spirit == "Eagle":
                char["spirit_blessing_eagle"] = True
                if not any("Spirit Blessing" in f for f in features):
                    features.append(f"Spirit Blessing ({blessing_range} ft): Keen Vision - +1 ranged attack rolls, +{wis_mod} Perception at distance.")
            elif totem_spirit == "Wolf":
                char["spirit_blessing_wolf"] = True
                if not any("Spirit Blessing" in f for f in features):
                    features.append(f"Spirit Blessing ({blessing_range} ft): Pack Tactics - +1 attack vs enemies near allies, +{wis_mod} Survival tracking.")
            elif not any("Spirit Blessing" in f for f in features):
                features.append(f"Spirit Blessing ({blessing_range} ft): ⚠️ Choose Totem Spirit for blessing!")
        
        # --- Level 4 Features ---
        if lvl >= 4:
            # Totem Aspect
            if totem_spirit == "Bear":
                char["totem_aspect_bear"] = True
                temp_hp = lvl + con_mod
                if not any("Totem Aspect" in f for f in features):
                    features.append(f"Totem Aspect (Enduring Might): Gain {temp_hp} temp HP at start of first turn in combat.")
            elif totem_spirit == "Eagle":
                char["totem_aspect_eagle"] = True
                speed_bonus = 10 + (5 * ((lvl - 4) // 4))  # +10 at 4, +15 at 8, +20 at 12, etc.
                char["eagle_speed_bonus"] = speed_bonus
                if not any("Totem Aspect" in f for f in features):
                    features.append(f"Totem Aspect (Wind's Grace): +{speed_bonus} ft speed. Ignore difficult terrain.")
            elif totem_spirit == "Wolf":
                char["totem_aspect_wolf"] = True
                char["darkvision"] = max(char.get("darkvision", 0), 30)
                char["heightened_senses"] = 30
                if not any("Totem Aspect" in f for f in features):
                    features.append("Totem Aspect (Keen Senses): Darkvision 30 ft. Sense hidden creatures within 30 ft.")
            elif not any("Totem Aspect" in f for f in features):
                features.append("Totem Aspect: ⚠️ Choose Totem Spirit for aspect!")
        
        # --- Level 5 Features ---
        if lvl >= 5:
            # Greater Boon
            ensure_resource(char, "Greater Boon", 1)
            
            if totem_spirit == "Bear":
                if not any("Greater Boon" in f for f in features):
                    features.append(f"Greater Boon (Bear's Fury): 1/day, 1 min: +2 STR, +{lvl + con_mod} temp HP, +1d6 melee damage.")
            elif totem_spirit == "Eagle":
                if not any("Greater Boon" in f for f in features):
                    features.append(f"Greater Boon (Storm's Eye): 1/day, 1 min: Fly speed 60 ft. Allies in range +{wis_mod} DEX checks.")
            elif totem_spirit == "Wolf":
                if not any("Greater Boon" in f for f in features):
                    features.append("Greater Boon (Pack Leader's Command): 1/day, 1 min: Summon wolf pack (30 ft) that obeys your commands.")
            elif not any("Greater Boon" in f for f in features):
                features.append("Greater Boon: ⚠️ Choose Totem Spirit for boon!")
            
            if not any(a.get("name") == "Greater Boon" for a in actions):
                actions.append({
                    "name": "Greater Boon",
                    "resource": "Greater Boon",
                    "action_type": "bonus",
                    "description": f"Bonus Action (1/day): Activate your Totem Spirit's Greater Boon for 1 minute.",
                })
        
        # --- Level 6 Features ---
        if lvl >= 6:
            # Spirit Shield
            if totem_spirit == "Bear":
                char.setdefault("damage_resistances", []).extend(["bludgeoning_nonmagical", "piercing_nonmagical", "slashing_nonmagical"]) if "bludgeoning_nonmagical" not in char.get("damage_resistances", []) else None
                if not any("Spirit Shield" in f for f in features):
                    features.append("Spirit Shield (Bear): Resistance to B/P/S from non-magical attacks.")
            elif totem_spirit == "Eagle":
                if "lightning" not in char.get("damage_resistances", []):
                    char.setdefault("damage_resistances", []).append("lightning")
                if not any("Spirit Shield" in f for f in features):
                    features.append("Spirit Shield (Eagle): Resistance to lightning damage.")
            elif totem_spirit == "Wolf":
                if "piercing" not in char.get("damage_resistances", []):
                    char.setdefault("damage_resistances", []).append("piercing")
                if "necrotic" not in char.get("damage_resistances", []):
                    char.setdefault("damage_resistances", []).append("necrotic")
                if not any("Spirit Shield" in f for f in features):
                    features.append("Spirit Shield (Wolf): Resistance to piercing and necrotic damage.")
            
            # Totem Bond - additional blessings
            if totem_spirit == "Bear":
                char["totem_bond_bear"] = True
                if not any("Totem Bond" in f for f in features):
                    features.append(f"Totem Bond (Bear): Allies in aura resist necrotic. Toughness temp HP = {wis_mod} + {lvl}.")
            elif totem_spirit == "Eagle":
                char["totem_bond_eagle"] = True
                if not any("Totem Bond" in f for f in features):
                    features.append(f"Totem Bond (Eagle): Allies +{wis_mod} vs prone/grapple. Swift Strike: 1/encounter bonus action Dash/Disengage.")
            elif totem_spirit == "Wolf":
                char["totem_bond_wolf"] = True
                if not any("Totem Bond" in f for f in features):
                    features.append(f"Totem Bond (Wolf): Coordinated Strike: +{wis_mod} damage vs enemies near allies (1st attack/turn). Keen Smell: +{wis_mod} smell Perception.")
        
        # --- Level 8 Features ---
        if lvl >= 8:
            # Enhanced Totem Aspect
            if totem_spirit == "Bear":
                char["enhanced_totem_bear"] = True
                if not any("Enhanced Totem Aspect" in f for f in features):
                    features.append(f"Enhanced Totem Aspect (Bear): Temp HP lasts 1 hour. +{wis_mod} to STR checks/saves while you have temp HP.")
            elif totem_spirit == "Eagle":
                char["enhanced_totem_eagle"] = True
                char["eagle_speed_bonus"] = 20
                if not any("Enhanced Totem Aspect" in f for f in features):
                    features.append("Enhanced Totem Aspect (Eagle): +20 ft speed. Ignore difficult terrain for climbing/jumping.")
            elif totem_spirit == "Wolf":
                char["enhanced_totem_wolf"] = True
                char["heightened_senses"] = 60
                if not any("Enhanced Totem Aspect" in f for f in features):
                    features.append("Enhanced Totem Aspect (Wolf): Heightened Senses extends to 60 ft. Can sense Ethereal creatures.")
        
        # --- Level 9 Features ---
        if lvl >= 9:
            # Spirit Recall
            ensure_resource(char, "Spirit Recall", 1)
            if not any("Spirit Recall" in f for f in features):
                features.append(f"Spirit Recall (1/day): Recover spell slots (1st-3rd) OR heal {lvl} HP.")
            
            if not any(a.get("name") == "Spirit Recall" for a in actions):
                actions.append({
                    "name": "Spirit Recall",
                    "resource": "Spirit Recall",
                    "action_type": "bonus",
                    "description": f"Bonus Action (1/day): Recover expended spell slots (1st-3rd level) OR heal {lvl} HP.",
                })
        
        # --- Level 12 Features ---
        if lvl >= 12:
            # Totem Mastery - permanent aspect
            char["totem_mastery"] = True
            
            if totem_spirit == "Bear":
                char["hp_bonus"] = char.get("hp_bonus", 0) + wis_mod
                if not any("Totem Mastery" in f for f in features):
                    features.append(f"Totem Mastery (Bear): Max HP +{wis_mod}. +{wis_mod} STR saves while you have temp HP.")
            elif totem_spirit == "Eagle":
                if not any("Totem Mastery" in f for f in features):
                    features.append(f"Totem Mastery (Eagle): Permanent +20 ft speed. +{wis_mod} Acrobatics for movement/climbing/jumping.")
            elif totem_spirit == "Wolf":
                char["heightened_senses"] = 90
                if not any("Totem Mastery" in f for f in features):
                    features.append("Totem Mastery (Wolf): Heightened Senses 90 ft. Pinpoint hidden creatures unless they use Stealth.")
            
            # Greater Channeling
            ensure_resource(char, "Greater Channeling", 1)
            
            if totem_spirit == "Bear":
                if not any("Greater Channeling" in f for f in features):
                    features.append(f"Greater Channeling (Wrath of the Ancients): 1/day, 1 min: +2 STR checks/saves, +2d6 melee damage, attackers take {wis_mod} damage.")
            elif totem_spirit == "Eagle":
                if not any("Greater Channeling" in f for f in features):
                    features.append("Greater Channeling (Winds of Liberty): 1/day, 10 min: Fly 60 ft. Bonus action Dash/Disengage.")
            elif totem_spirit == "Wolf":
                if not any("Greater Channeling" in f for f in features):
                    features.append(f"Greater Channeling (Call of the Pack): 1/day, 10 min: Summon wolves (+{wis_mod} attack, 2d6 damage). Damaged creatures -{wis_mod} next attack.")
            
            if not any(a.get("name") == "Greater Channeling" for a in actions):
                actions.append({
                    "name": "Greater Channeling",
                    "resource": "Greater Channeling",
                    "action_type": "action",
                    "description": "Action (1/day): Activate your Totem Spirit's Greater Channeling ability.",
                })
            
            # Improved Spirit Shield
            if totem_spirit == "Bear":
                char["damage_immunities"] = char.get("damage_immunities", [])
                if "poison" not in char["damage_immunities"]:
                    char["damage_immunities"].append("poison")
                # Upgrade to all non-magical resistance
                if not any("Improved Spirit Shield" in f for f in features):
                    features.append("Improved Spirit Shield (Bear): Resistance to all non-magical damage. Immunity to poison.")
            elif totem_spirit == "Eagle":
                if "thunder" not in char.get("damage_resistances", []):
                    char.setdefault("damage_resistances", []).append("thunder")
                if not any("Improved Spirit Shield" in f for f in features):
                    features.append(f"Improved Spirit Shield (Eagle): Resist lightning/thunder. Reaction: Reduce ranged attack by 1d10+{wis_mod}+{lvl}. Miss = redirect.")
                
                if not any(a.get("name") == "Deflect Ranged" for a in actions):
                    actions.append({
                        "name": "Deflect Ranged",
                        "action_type": "reaction",
                        "description": f"Reaction: Reduce ranged attack roll by 1d10+{wis_mod}+{lvl}. If miss, redirect to creature in aura. Hit = +{wis_mod} lightning damage.",
                    })
            elif totem_spirit == "Wolf":
                if "psychic" not in char.get("damage_resistances", []):
                    char.setdefault("damage_resistances", []).append("psychic")
                if not any("Improved Spirit Shield" in f for f in features):
                    features.append(f"Improved Spirit Shield (Wolf): Resist necrotic/psychic. Allies taking these types heal {wis_mod // 2} HP.")
        
        # --- Level 14 Features ---
        if lvl >= 14:
            # Spirit Form
            ensure_resource(char, "Spirit Form", 1)
            char["spirit_form"] = True
            if not any("Spirit Form" in f for f in features):
                features.append("Spirit Form (1/day): Become partially ethereal. Pass through walls, resist physical damage, Truesight 60 ft.")
            
            if not any(a.get("name") == "Spirit Form" for a in actions):
                actions.append({
                    "name": "Spirit Form",
                    "resource": "Spirit Form",
                    "action_type": "action",
                    "description": "Action (1/day): Transform into spirit form. Pass through obstacles, resist physical damage, Truesight 60 ft.",
                })
        
        # --- Level 18 Features ---
        if lvl >= 18:
            # Avatar of the Totem
            char["avatar_of_totem"] = True
            spirit_form_duration = wis_mod  # minutes
            
            if totem_spirit == "Bear":
                if not any("Avatar of the Totem" in f for f in features):
                    features.append(f"Avatar of the Totem (Bear): Spirit Form grants: Allies in aura gain {wis_mod + lvl} temp HP/turn. +2d6 bludgeoning damage, +2 STR/CON.")
            elif totem_spirit == "Eagle":
                if not any("Avatar of the Totem" in f for f in features):
                    features.append(f"Avatar of the Totem (Eagle): Spirit Form grants: Fly 90 ft, immune to wind, Call Lightning at will, +2 DEX/WIS. Duration: {spirit_form_duration} min.")
            elif totem_spirit == "Wolf":
                if not any("Avatar of the Totem" in f for f in features):
                    features.append(f"Avatar of the Totem (Wolf): Spirit Form grants: 2 claw (2d6) + bite (2d6, grapple) attacks. Alpha's Howl (60 ft WIS save or Frightened). +30 ft speed. Duration: {spirit_form_duration} min.")
        
        # --- Level 20 Features ---
        if lvl >= 20:
            # Spirit Who Walks
            char["spirit_who_walks"] = True
            char["creature_type"] = "Fey"
            char["truesight"] = 120
            char["see_ethereal"] = 120
            char["damage_reduction"] = "5/cold iron"
            
            # Permanent immunities
            char.setdefault("condition_immunities", []).extend(["charmed", "frightened", "possessed"]) if "charmed" not in char.get("condition_immunities", []) else None
            if "necrotic" not in char.get("damage_resistances", []):
                char.setdefault("damage_resistances", []).append("necrotic")
            if "force" not in char.get("damage_resistances", []):
                char.setdefault("damage_resistances", []).append("force")
            
            ensure_resource(char, "Contact Other Plane", 1)
            
            if not any("Spirit Who Walks" in f for f in features):
                features.append("Spirit Who Walks: Fey type. Permanent Avatar form. DR 5/cold iron. Truesight 120 ft. Immune to charm/fear/possession by spirits/undead. Resist necrotic/force. Contact Other Plane 1/day (spirits only).")
    
    # ---- Favored Soul ----
    elif cls_name == "Favored Soul":
        cha_mod = _ability_mod(abilities.get("CHA", 10))
        wis_mod = _ability_mod(abilities.get("WIS", 10))
        lvl = int(char.get("level", 1))
        bab = int(char.get("bab", 0))
        spell_dc = 8 + cha_mod + bab
        
        # Get chosen domains
        domain1 = char.get("favored_soul_domain1")
        domain2 = char.get("favored_soul_domain2")
        domain3 = char.get("favored_soul_domain3")
        alignment = char.get("alignment", "Neutral")
        
        # Domain spell lists
        DOMAIN_SPELLS = {
            "Life": ["Bless", "Cure Wounds", "Lesser Restoration", "Spiritual Weapon", "Beacon of Hope", "Revivify", "Death Ward", "Guardian of Faith", "Mass Cure Wounds", "Greater Restoration"],
            "Light": ["Burning Hands", "Faerie Fire", "Flaming Sphere", "Scorching Ray", "Daylight", "Fireball", "Guardian of Faith", "Wall of Fire", "Flame Strike", "Scrying"],
            "War": ["Divine Favor", "Shield of Faith", "Magic Weapon", "Spiritual Weapon", "Crusader's Mantle", "Spirit Guardians", "Freedom of Movement", "Stoneskin", "Flame Strike", "Hold Monster"],
            "Nature": ["Animal Friendship", "Speak with Animals", "Barkskin", "Spike Growth", "Plant Growth", "Wind Wall", "Dominate Beast", "Grasping Vine", "Insect Plague", "Tree Stride"],
            "Trickery": ["Charm Person", "Disguise Self", "Mirror Image", "Pass Without Trace", "Blink", "Dispel Magic", "Dimension Door", "Polymorph", "Dominate Person", "Modify Memory"],
            "Tempest": ["Fog Cloud", "Thunderwave", "Gust of Wind", "Shatter", "Call Lightning", "Sleet Storm", "Control Water", "Ice Storm", "Destructive Wave", "Insect Plague"],
            "Knowledge": ["Command", "Identify", "Augury", "Suggestion", "Nondetection", "Speak with Dead", "Arcane Eye", "Confusion", "Legend Lore", "Scrying"],
            "Death": ["False Life", "Ray of Sickness", "Blindness/Deafness", "Ray of Enfeeblement", "Animate Dead", "Vampiric Touch", "Blight", "Death Ward", "Antilife Shell", "Cloudkill"],
        }
        
        # --- Level 1 Features ---
        # Divine Magic (Spellcasting)
        if not any("Divine Magic" in f for f in features):
            features.append(f"Divine Magic: Charisma-based full caster. Spells known (no preparation). Spell DC {spell_dc}. Spell Attack +{bab + cha_mod}.")
        
        # Divine Blessing (Domain 1)
        if domain1:
            char["domain1_spells"] = DOMAIN_SPELLS.get(domain1, [])
            if not any("Divine Blessing" in f for f in features):
                features.append(f"Divine Blessing ({domain1} Domain): Access to {domain1} domain spells and features.")
            _apply_favored_soul_domain_feature(char, domain1, lvl, cha_mod, wis_mod, spell_dc, features, actions, "1st")
        else:
            char["pending_domain1"] = True
            if not any("Divine Blessing" in f for f in features):
                features.append("Divine Blessing: ⚠️ Choose a Divine Domain (Life, Light, War, Nature, Trickery, Tempest, Knowledge, Death)!")
        
        # --- Level 2 Features ---
        if lvl >= 2:
            # Faith Healing
            if lvl >= 16:
                faith_healing = "2d8"
            elif lvl >= 11:
                faith_healing = "1d8"
            elif lvl >= 6:
                faith_healing = "1d4"
            else:
                faith_healing = "1"
            
            char["faith_healing"] = faith_healing
            if not any("Faith Healing" in f for f in features):
                features.append(f"Faith Healing: Touch to stabilize dying creature, or heal {faith_healing} HP if they share your deity's alignment.")
            
            if not any(a.get("name") == "Faith Healing" for a in actions):
                actions.append({
                    "name": "Faith Healing",
                    "action_type": "action",
                    "description": f"Action: Touch to stabilize dying creature or heal {faith_healing} HP (if same alignment).",
                })
            
            # Exalted or Vile Presence
            char["divine_presence"] = True
            presence_bonus = lvl
            if lvl >= 4:
                if not any("Exalted or Vile Presence" in f for f in features):
                    features.append(f"Exalted/Vile Presence: +{presence_bonus} to CHA checks with those sharing your alignment. Also applies to divine artifact checks.")
            else:
                if not any("Exalted or Vile Presence" in f for f in features):
                    features.append(f"Exalted/Vile Presence: +{presence_bonus} to CHA checks with members of your faith. Also applies to divine artifact checks.")
        
        # --- Level 3 Features ---
        if lvl >= 3:
            # Angel's Sight
            char["darkvision"] = max(char.get("darkvision", 0), 60)
            char["low_light_vision"] = True
            if lvl >= 10:
                char["see_through_magical_darkness"] = True
                if not any("Angel's Sight" in f for f in features):
                    features.append("Angel's Sight: Darkvision 60 ft, low-light vision. See through magical darkness.")
            else:
                if not any("Angel's Sight" in f for f in features):
                    features.append("Angel's Sight: Darkvision 60 ft, low-light vision.")
            
            # Deity's Weapon
            deity_weapon = char.get("deity_weapon", "Longsword")
            char["weapon_focus"] = deity_weapon
            if not any("Deity's Weapon" in f for f in features):
                features.append(f"Deity's Weapon ({deity_weapon}): Weapon Focus feat. Can imbue with divine light (20 ft radius).")
            
            if not any(a.get("name") == "Divine Light" for a in actions):
                actions.append({
                    "name": "Divine Light",
                    "action_type": "bonus",
                    "description": f"Bonus Action: Your {deity_weapon} radiates divine light in a 20 ft radius.",
                })
        
        # --- Level 4 Features ---
        if lvl >= 4:
            # Divine Favor
            ensure_resource(char, "Divine Favor", 1)
            if not any("Divine Favor" in f for f in features):
                features.append(f"Divine Favor (1/long rest): Add +{cha_mod} to initiative. Natural 20 = gain {cha_mod + lvl} temp HP.")
        
        # --- Level 5 Features ---
        if lvl >= 5:
            # Divine Resilience
            resistances_count = 1
            if lvl >= 15:
                resistances_count = 3
            elif lvl >= 10:
                resistances_count = 2
            
            char["divine_resilience_count"] = resistances_count
            current_resistances = char.get("divine_resistances", [])
            
            if len(current_resistances) < resistances_count:
                char["pending_divine_resistance"] = True
            
            if not any("Divine Resilience" in f for f in features):
                if current_resistances:
                    features.append(f"Divine Resilience: Resistance to {', '.join(current_resistances)}. ({resistances_count} total allowed)")
                else:
                    features.append(f"Divine Resilience: ⚠️ Choose {resistances_count} energy type(s) (fire, cold, lightning, acid, thunder)!")
        
        # --- Level 6 Features ---
        if lvl >= 6:
            # Divine Channeling
            channeling_uses = max(1, cha_mod)
            ensure_resource(char, "Divine Channeling", channeling_uses)
            
            channeling_choice = char.get("divine_channeling_choice")
            wrath_damage = f"{2 + ((lvl - 6) // 4)}d10"
            
            if channeling_choice == "Wrath of the Heavens":
                if not any("Divine Channeling" in f for f in features):
                    features.append(f"Divine Channeling ({channeling_uses}/day): Wrath of the Heavens - Ranged spell attack 60 ft, {wrath_damage} radiant/necrotic damage.")
                
                if not any(a.get("name") == "Wrath of the Heavens" for a in actions):
                    actions.append({
                        "name": "Wrath of the Heavens",
                        "resource": "Divine Channeling",
                        "action_type": "action",
                        "damage": wrath_damage,
                        "damage_type": "radiant",
                        "description": f"Action: Ranged spell attack (60 ft). Deal {wrath_damage} radiant or necrotic damage.",
                    })
            elif channeling_choice == "Sacred Shield":
                if not any("Divine Channeling" in f for f in features):
                    features.append(f"Divine Channeling ({channeling_uses}/day): Sacred Shield - Reaction to impose -{cha_mod} on attack vs ally within 10 ft, or +2 AC.")
                
                if not any(a.get("name") == "Sacred Shield" for a in actions):
                    actions.append({
                        "name": "Sacred Shield",
                        "resource": "Divine Channeling",
                        "action_type": "reaction",
                        "description": f"Reaction: Impose -{cha_mod} penalty on attack vs ally within 10 ft. If no adv/disadv, grant +2 AC instead.",
                    })
            elif channeling_choice == "Divine Healing":
                char["divine_healing_bonus"] = lvl
                if not any("Divine Channeling" in f for f in features):
                    features.append(f"Divine Channeling ({channeling_uses}/day): Divine Healing - Your healing spells restore +{lvl} additional HP.")
            else:
                char["pending_divine_channeling"] = True
                if not any("Divine Channeling" in f for f in features):
                    features.append(f"Divine Channeling ({channeling_uses}/day): ⚠️ Choose: Wrath of the Heavens, Sacred Shield, or Divine Healing!")
            
            # Expanded Divine Mandate (Domain 2)
            if domain2:
                char["domain2_spells"] = DOMAIN_SPELLS.get(domain2, [])
                if not any("Expanded Divine Mandate" in f for f in features):
                    features.append(f"Expanded Divine Mandate: {domain2} Domain added. Access to {domain2} domain spells.")
                _apply_favored_soul_domain_feature(char, domain2, lvl, cha_mod, wis_mod, spell_dc, features, actions, "1st")
            else:
                char["pending_domain2"] = True
            
            # Greater Blessing (Domain 1)
            if domain1:
                _apply_favored_soul_domain_feature(char, domain1, lvl, cha_mod, wis_mod, spell_dc, features, actions, "6th")
        
        # --- Level 7 Features ---
        if lvl >= 7:
            # Radiant Blessing
            radiant_uses = max(1, cha_mod)
            ensure_resource(char, "Radiant Blessing", radiant_uses)
            
            if not any("Radiant Blessing" in f for f in features):
                features.append(f"Radiant Blessing ({radiant_uses}/long rest): Bonus action, 1 min aura. You and chosen creatures within 30 ft gain {cha_mod} temp HP.")
            
            if not any(a.get("name") == "Radiant Blessing" for a in actions):
                actions.append({
                    "name": "Radiant Blessing",
                    "resource": "Radiant Blessing",
                    "action_type": "bonus",
                    "description": f"Bonus Action: 1 min aura. You and chosen creatures within 30 ft gain {cha_mod} temp HP. At L13: also cast Shield of Faith on them.",
                })
            
            # Divine Strike
            divine_strike_dice = "2d8" if lvl >= 14 else "1d8"
            char["divine_strike"] = divine_strike_dice
            if not any("Divine Strike" in f for f in features):
                features.append(f"Divine Strike: Once per turn, weapon hit deals +{divine_strike_dice} radiant or necrotic damage (your choice).")
            
            # Potent Spellcasting
            char["potent_spellcasting"] = wis_mod
            if not any("Potent Spellcasting" in f for f in features):
                features.append(f"Potent Spellcasting: Add +{wis_mod} (WIS) to cantrip damage.")
        
        # --- Level 8 Features ---
        if lvl >= 8:
            # Empowered Boon (Domain 1)
            if domain1:
                _apply_favored_soul_domain_feature(char, domain1, lvl, cha_mod, wis_mod, spell_dc, features, actions, "8th")
        
        # --- Level 10 Features ---
        if lvl >= 10:
            # Divine Power Surge
            char["divine_power_surge"] = True
            if "Good" in alignment:
                surge_type = "radiant"
            elif "Evil" in alignment:
                surge_type = "necrotic"
            else:
                surge_type = "radiant or necrotic"
            
            char["power_surge_type"] = surge_type
            if not any("Divine Power Surge" in f for f in features):
                features.append(f"Divine Power Surge: +{cha_mod} {surge_type} damage on spell/weapon damage rolls.")
        
        # --- Level 12 Features ---
        if lvl >= 12:
            # Wings of the Faithful
            char["fly_speed"] = 60
            if "Good" in alignment:
                wing_type = "feathered"
            elif "Evil" in alignment:
                wing_type = "bat-like"
            else:
                wing_type = "your choice"
            
            if not any("Wings of the Faithful" in f for f in features):
                features.append(f"Wings of the Faithful: Fly speed 60 ft. Wings appear {wing_type}.")
            
            # Expanded Divine Mandate (Domain 3)
            if domain3:
                char["domain3_spells"] = DOMAIN_SPELLS.get(domain3, [])
                _apply_favored_soul_domain_feature(char, domain3, lvl, cha_mod, wis_mod, spell_dc, features, actions, "1st")
            else:
                char["pending_domain3"] = True
        
        # --- Level 13 Features ---
        if lvl >= 13:
            # Shield of Faith with Radiant Blessing
            char["radiant_blessing_shield"] = True
        
        # --- Level 15 Features ---
        if lvl >= 15:
            # Holy Presence
            char["holy_presence"] = True
            if not any("Holy Presence" in f for f in features):
                features.append("Holy Presence: You are your own holy symbol. Cast Divine Focus spells without one.")
        
        # --- Level 17 Features ---
        if lvl >= 17:
            # Divine Intervention
            ensure_resource(char, "Divine Intervention", 1)
            if not any("Divine Intervention" in f for f in features):
                features.append("Divine Intervention (1/long rest): Choose Divine Smite (5d10 radiant + stun), Divine Shield (absorb 5×level damage), or Divine Healing (heal 5×level to all in 30 ft).")
            
            if not any(a.get("name") == "Divine Intervention" for a in actions):
                actions.append({
                    "name": "Divine Intervention",
                    "resource": "Divine Intervention",
                    "action_type": "action",
                    "description": f"Action (1/long rest): Divine Smite (+5d10 radiant, CON save or Stunned), Divine Shield ({5 * lvl} HP absorb), or Divine Healing (heal {5 * lvl} HP to all in 30 ft).",
                })
            
            # Divine Avatar (Domain 1)
            if domain1:
                _apply_favored_soul_domain_feature(char, domain1, lvl, cha_mod, wis_mod, spell_dc, features, actions, "17th")
        
        # --- Level 20 Features ---
        if lvl >= 20:
            # Ascendant Devotion
            char["ascendant_devotion"] = True
            char["creature_type"] = "Celestial"
            char["no_aging"] = True
            char.setdefault("condition_immunities", []).extend(["diseased", "poisoned"]) if "diseased" not in char.get("condition_immunities", []) else None
            
            # Divine Immunity based on Power Surge type
            surge_type = char.get("power_surge_type", "radiant")
            if surge_type and surge_type != "radiant or necrotic":
                char.setdefault("damage_immunities", []).append(surge_type) if surge_type not in char.get("damage_immunities", []) else None
            
            # Full domain mastery - apply all domain features
            if domain1:
                _apply_favored_soul_domain_feature(char, domain1, lvl, cha_mod, wis_mod, spell_dc, features, actions, "all")
            if domain2:
                _apply_favored_soul_domain_feature(char, domain2, lvl, cha_mod, wis_mod, spell_dc, features, actions, "all")
            if domain3:
                _apply_favored_soul_domain_feature(char, domain3, lvl, cha_mod, wis_mod, spell_dc, features, actions, "all")
            
            if not any("Ascendant Devotion" in f for f in features):
                features.append(f"Ascendant Devotion: Celestial type. No aging, immune to disease/poison. Immune to {surge_type} damage. Full mastery of all three domains.")

def _apply_favored_soul_domain_feature(char: dict, domain: str, lvl: int, cha_mod: int, wis_mod: int, spell_dc: int, features: list, actions: list, tier: str):
    """Apply Favored Soul domain-specific features based on tier (1st, 6th, 8th, 17th, all)."""
    
    if domain == "Life":
        if tier in ["1st", "all"]:
            char["bonus_healing"] = char.get("bonus_healing", 0) + 2 + (lvl // 4)
        if tier in ["6th", "all"] and lvl >= 6:
            char["blessed_healer"] = True
        if tier in ["8th", "all"] and lvl >= 8:
            char["divine_strike_life"] = True
        if tier in ["17th", "all"] and lvl >= 17:
            char["supreme_healing"] = True
    
    elif domain == "Light":
        if tier in ["1st", "all"]:
            char["warding_flare"] = True
            ensure_resource(char, "Warding Flare", max(1, wis_mod))
        if tier in ["6th", "all"] and lvl >= 6:
            char["improved_flare"] = True
        if tier in ["8th", "all"] and lvl >= 8:
            char["potent_spellcasting_light"] = True
        if tier in ["17th", "all"] and lvl >= 17:
            char["corona_of_light"] = True
    
    elif domain == "War":
        if tier in ["1st", "all"]:
            char["war_priest"] = True
            ensure_resource(char, "War Priest", max(1, wis_mod))
        if tier in ["6th", "all"] and lvl >= 6:
            ensure_resource(char, "Channel Divinity: Guided Strike", 1)
        if tier in ["8th", "all"] and lvl >= 8:
            char["divine_strike_war"] = True
        if tier in ["17th", "all"] and lvl >= 17:
            char["avatar_of_battle"] = True
    
    elif domain == "Nature":
        if tier in ["1st", "all"]:
            char["nature_acolyte"] = True
        if tier in ["6th", "all"] and lvl >= 6:
            char["dampen_elements"] = True
        if tier in ["8th", "all"] and lvl >= 8:
            char["divine_strike_nature"] = True
        if tier in ["17th", "all"] and lvl >= 17:
            char["master_of_nature"] = True
    
    elif domain == "Trickery":
        if tier in ["1st", "all"]:
            char["blessing_of_the_trickster"] = True
        if tier in ["6th", "all"] and lvl >= 6:
            ensure_resource(char, "Invoke Duplicity", 1)
        if tier in ["8th", "all"] and lvl >= 8:
            char["divine_strike_trickery"] = True
        if tier in ["17th", "all"] and lvl >= 17:
            char["improved_duplicity"] = True
    
    elif domain == "Tempest":
        if tier in ["1st", "all"]:
            char["wrath_of_the_storm"] = True
            ensure_resource(char, "Wrath of the Storm", max(1, wis_mod))
        if tier in ["6th", "all"] and lvl >= 6:
            char["thunderbolt_strike"] = True
        if tier in ["8th", "all"] and lvl >= 8:
            char["divine_strike_tempest"] = True
        if tier in ["17th", "all"] and lvl >= 17:
            char["stormborn"] = True
            char["fly_speed"] = max(char.get("fly_speed", 0), 60)
    
    elif domain == "Knowledge":
        if tier in ["1st", "all"]:
            char["blessings_of_knowledge"] = True
        if tier in ["6th", "all"] and lvl >= 6:
            ensure_resource(char, "Read Thoughts", 1)
        if tier in ["8th", "all"] and lvl >= 8:
            char["potent_spellcasting_knowledge"] = True
        if tier in ["17th", "all"] and lvl >= 17:
            char["visions_of_the_past"] = True
    
    elif domain == "Death":
        if tier in ["1st", "all"]:
            char["reaper"] = True
        if tier in ["6th", "all"] and lvl >= 6:
            ensure_resource(char, "Channel Divinity: Touch of Death", 1)
        if tier in ["8th", "all"] and lvl >= 8:
            char["divine_strike_death"] = True
        if tier in ["17th", "all"] and lvl >= 17:
            char["improved_reaper"] = True

def apply_feats(char: dict, feat_names: list[str]):
    feats = char.setdefault("feats", [])
    for f in feat_names:
        if f and f not in feats:
            feats.append(f)

# ---------------- Helpers: Session State ----------------
def init_state():
    ss = st.session_state
    ss.setdefault("boot_mode", None)  # "load" | "new" | "running"
    ss.setdefault("session_id", datetime.now().strftime("%Y%m%d_%H%M%S"))
    ss.setdefault("chat_log", [])      # list[tuple(speaker, text)]
    ss.setdefault("world_log", "You stand at the threshold of adventure.")
    ss.setdefault("party", [])         # list of character dicts
    ss.setdefault("enemies", [])       # list of enemy dicts
    ss.setdefault("difficulty", "Normal")
    ss.setdefault("npc_attitude", 50)  # tiny memory for talk replies
    ss.setdefault("last_topic", None)

def serialize_state() -> Dict[str, Any]:
    # Serialize grid data
    grid_data = None
    if "grid" in st.session_state and st.session_state.grid:
        grid = st.session_state.grid
        grid_data = {
            "width": grid.get("width", 20),
            "height": grid.get("height", 20),
            "square_size_ft": grid.get("square_size_ft", 5),
            "biome": grid.get("biome"),
            "seed": grid.get("seed"),
            "cells": grid.get("cells", []),
        }
    
    return {
        "session_id": st.session_state.session_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "chat_log": st.session_state.chat_log,
        "world_log": st.session_state.world_log,
        "party": st.session_state.party,
        "enemies": st.session_state.enemies,
        "difficulty": st.session_state.difficulty,
        "grid": grid_data,
        "dm_notes": st.session_state.get("dm_notes", ""),
    }

def _migrate_grid_cells(cells: list) -> list:
    """Migrate old grid cell formats to new format."""
    if not cells:
        return cells
    
    tiles = load_tiles()
    
    migrated = []
    for row in cells:
        new_row = []
        for cell in row:
            if isinstance(cell, dict):
                # Already new format
                if "tile" in cell:
                    new_row.append(cell)
                else:
                    # Unknown dict format
                    new_row.append({"tile": "open", "hazard": None})
            elif isinstance(cell, int):
                # Old int format: 0=open, 1=wall, 2=difficult
                tile_map = {0: "open", 1: "wall", 2: "difficult"}
                new_row.append({"tile": tile_map.get(cell, "open"), "hazard": None})
            elif isinstance(cell, str):
                # String tile name - validate against loaded tiles
                new_row.append({"tile": cell if cell in tiles else "open", "hazard": None})
            else:
                new_row.append({"tile": "open", "hazard": None})
        migrated.append(new_row)
    return migrated

def load_state_blob(blob: Dict[str, Any]):
    st.session_state.session_id = blob.get("session_id", datetime.now().strftime("%Y%m%d_%H%M%S"))
    st.session_state.chat_log = blob.get("chat_log", [])
    st.session_state.world_log = blob.get("world_log", "")
    st.session_state.party = blob.get("party", [])
    st.session_state.enemies = blob.get("enemies", [])
    st.session_state.difficulty = blob.get("difficulty", "Normal")
    st.session_state.dm_notes = blob.get("dm_notes", "")
    
    # Load grid data
    grid_data = blob.get("grid")
    if grid_data:
        cells = grid_data.get("cells", [])
        # Migrate old cell formats if needed
        cells = _migrate_grid_cells(cells)
        
        st.session_state.grid = {
            "width": grid_data.get("width", 20),
            "height": grid_data.get("height", 20),
            "square_size_ft": grid_data.get("square_size_ft", 5),
            "biome": grid_data.get("biome"),
            "seed": grid_data.get("seed"),
            "cells": cells,
        }
    else:
        # No grid in save - will be initialized on first access
        st.session_state.grid = None
    
    # Migrate party members to include XP and multiclass fields (backward compatibility)
    for char in st.session_state.party:
        migrate_character_xp(char)
        migrate_to_multiclass(char)

# ---------------- Dice + Dialogue Utilities ----------------
def roll_dice(expr: str) -> Tuple[int, str]:

    expr = expr.strip().lower().replace(" ", "")
    m = re.fullmatch(r"(?:(\d*)d(\d+))?([+-]\d+)?", expr)
    if not m:
        if (expr.isdigit()) or (expr.startswith("-") and expr[1:].isdigit()):
            val = int(expr); return val, f"{val} (flat)"
        return 0, f"Unrecognized dice: {expr}"

    num = int(m.group(1)) if m.group(1) not in (None, "") else (1 if m.group(2) else 0)
    sides = int(m.group(2)) if m.group(2) else 0
    mod = int(m.group(3)) if m.group(3) else 0

    rolls = [random.randint(1, sides) for _ in range(num)] if sides else []
    total = sum(rolls) + mod
    parts = "+".join(map(str, rolls)) if rolls else ""
    if mod != 0:
        parts = (parts + (f"{'+' if mod>0 else ''}{mod}")).lstrip("+")
    if parts == "":
        parts = str(total)
    return total, f"{parts} = {total}"

def extract_inline_rolls(text: str) -> List[str]:
    pattern = r"(?:(?<=/roll\s)|(?<=\broll\s))(\d*d\d+(?:[+-]\d+)?|\d{1,3}\b)"
    return [m.group(1) for m in re.finditer(pattern, text.lower())]

def detect_intent(text: str) -> Tuple[str, Dict]:
    t = text.strip().lower()
    if t.startswith("/roll") or t.startswith("roll "):
        dice = extract_inline_rolls(t)
        return "roll", {"dice": dice or ["d20"]}

    if any(k in t for k in ["attack", "strike", "shoot", "swing", "stab", "fire at"]):
        m = re.search(r"attack\s+the\s+([\w'-]+)|attack\s+([\w'-]+)", t)
        target = m.group(1) if m and m.group(1) else (m.group(2) if m else None)
        return "attack", {"target": target}

    if any(k in t for k in ["talk", "speak", "ask", "say", "negotiate", "persuade", "intimidate"]):
        m = re.search(r"(about|regarding)\s+(.+)$", t)
        topic = m.group(2) if m else None
        return "talk", {"topic": topic}

    if any(k in t for k in ["search", "investigate", "inspect", "look around", "examine", "perception"]):
        return "search", {}

    if any(k in t for k in ["cast", "spell", "ritual"]):
        m = re.search(r"cast\s+([a-z][a-z\s']+)", t)
        spell = m.group(1).strip() if m else None
        return "cast", {"spell": spell}

    if any(k in t for k in ["move", "go to", "run to", "advance to", "fall back", "retreat"]):
        m = re.search(r"(to|toward)\s+(.+)$", t)
        where = m.group(2).strip() if m else None
        return "move", {"where": where}

    return "other", {}

def reply_for(text: str) -> str:
    intent, ent = detect_intent(text)
    ss = st.session_state

    if intent == "roll":
        lines = []
        for d in ent.get("dice", ["d20"]):
            total, breakdown = roll_dice(d)
            lines.append(f"• {d}: {breakdown}")
        return "Rolls:\n" + "\n".join(lines)

    if intent == "attack":
        tgt = ent.get("target") or "the target"
        ac_note = ""
        for e in ss.enemies:
            if e.get("name", "").lower() == (ent.get("target") or "").lower():
                ac_note = f" (Target AC: {e.get('ac', '—')})"
                break
        return f"Make an attack roll against {tgt}{ac_note}. On a hit, roll weapon damage."

    if intent == "talk":
        topic = ent.get("topic")
        if topic:
            ss["last_topic"] = topic
            ss["npc_attitude"] = min(100, ss["npc_attitude"] + 2)
            return f"You discuss **{topic}**. The other side seems slightly more receptive (Attitude {ss['npc_attitude']}/100). What do you say next?"
        return "State your opening line or topic."

    if intent == "search":
        dc = random.choice([10, 12, 13, 15])
        return f"Make a Search/Perception check vs DC {dc}. State your modifier."

    if intent == "cast":
        spell = ent.get("spell") or "a spell"
        return f"You begin casting **{spell}**. Provide target and intended effect."

    if intent == "move":
        where = ent.get("where") or "a new position"
        return f"You move to **{where}**. Note marching order and pace."

    return "Action noted. Use: attack, talk, search, cast, move, or /roll XdY+Z."

# ---------------- Data Shapes ----------------
# Minimal D&D 5e sheet shape
EMPTY_CHAR = {
    "name": "",
    "ac": 10,
    "hp": 10,
    "speed": "30 ft.",
    "abilities": {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
    "skills": {},
    "senses": "",
    "languages": "",
    "attacks": [],  # list of {name, to_hit:int, damage:str, reach/range:opt}
    "resources": {}, 
    "actions": [],    
}

def coerce_5e_sheet(blob: Dict[str, Any]) -> Dict[str, Any]:
    """
    Accepts various 5e-like sheet JSON and maps to the minimal shape used here.
    Unknown fields ignored; missing fields set to defaults.
    """
    out = json.loads(json.dumps(EMPTY_CHAR))
    out["name"] = blob.get("name", out["name"])
    out["ac"] = blob.get("ac", blob.get("armor_class", out["ac"]))
    out["hp"] = blob.get("hp", blob.get("hit_points", out["hp"]))
    out["speed"] = blob.get("speed", out["speed"])

    abilities = blob.get("abilities") or blob.get("ability_scores") or {}
    for k in out["abilities"].keys():
        out["abilities"][k] = int(abilities.get(k, out["abilities"][k]))

    out["skills"] = blob.get("skills", out["skills"])
    out["senses"] = blob.get("senses", out["senses"])
    out["languages"] = blob.get("languages", out["languages"])

    attacks = []
    for atk in blob.get("attacks", []):
        attacks.append({
            "name": atk.get("name", "Attack"),
            "to_hit": int(atk.get("to_hit", 0)),
            "damage": atk.get("damage", "1d6"),
            "reach": atk.get("reach", None),
            "range": atk.get("range", None),
        })
    out["attacks"] = attacks
    return out

# ---------------- Init ----------------
init_state()
load_srd_monsters()  # reminder: SRD list is available even before choosing Load/New.
load_srd_conditions()

st.markdown("### Virtual DM — Session Manager")

# ==== Character Builder state ==== (Confirmed working)
def init_builder_state():
    ss = st.session_state
    ss.setdefault("builder_char", {
        "name": "", "level": 1, "class": "", "subclass": "", "race": "", "background": "",
        "ac": 10, "hp": 10, "speed": "30 ft.",
        "abilities": {"STR":10,"DEX":10,"CON":10,"INT":10,"WIS":10,"CHA":10},
        "proficiency_bonus": 2,
        "profs": {"saves": [], "skills": [], "weapons": [], "armor": []},
        "features": [],           # textual features
        "feats": [],
        "spells": {        # structured spell data
            "cantrips": [],      # list of names
            "leveled": {},       # {spell_level: [names]}
        },
        "equipment": [],
        "attacks": [],
        "default_attack_index": 0,
        "resources": {},          # e.g. Rage, Bardic Performance, Crafting Reservoir
        "actions": [],            # structured class actions the UI can show
    })

    ss.setdefault("builder_name", "")
    # 1..7 = Race, Abilities, Background, Class, Skills, Feats, Equipment
    ss.setdefault("builder_step", 1)
    # per-builder temporary store for skill ranks
    ss.setdefault("builder_skill_ranks", {})

init_builder_state()

# ---------------- Boot Flow ----------------
if st.session_state.boot_mode is None:
    st.markdown("# 🎲 Welcome to Virtual DM")
    st.markdown("Your virtual tabletop companion for solo play, DM assistance, and session management.")
    
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🆕 Start New Session")
        st.markdown("""
        Create a new adventure from scratch:
        - Build or import party members
        - Add enemies from the SRD bestiary
        - Configure your encounter
        """)
        if st.button("Start New Session", use_container_width=True, type="primary"):
            st.session_state.boot_mode = "new"
            st.rerun()
    
    with col2:
        st.markdown("### 📂 Load Previous Session")
        st.markdown("""
        Continue where you left off:
        - Upload a saved session JSON
        - Resume combat and exploration
        - Keep your party progress
        """)
        if st.button("Load Previous Session", use_container_width=True):
            st.session_state.boot_mode = "load"
            st.rerun()
    
    st.markdown("---")
    st.caption("Use the sidebar navigation to switch between pages at any time.")
    st.stop()

# ---------------- Load Session ----------------
if st.session_state.boot_mode == "load":
    st.markdown("# 📂 Load Session")
    st.markdown("Upload a previously saved Virtual DM session file to continue your adventure.")
    
    st.markdown("---")
    
    up = st.file_uploader("Upload a saved session (.json)", type=["json"])
    
    if up is None:
        st.info("👆 Select a `.json` session file to upload")
        st.caption("Session files are created using the 'Download Session' button during play.")
    else:
        try:
            blob = json.load(up)
            load_state_blob(blob)
            st.success("✅ Session loaded successfully!")
            st.balloons()
            st.session_state.boot_mode = "running"
            st.rerun()
        except Exception as e:
            st.error(f"❌ Could not load file: {e}")
            st.caption("Make sure you're uploading a valid Virtual DM session JSON file.")
    
    st.stop()

# ---------------- New Session: Character Entry ----------------
if st.session_state.boot_mode == "new":
    st.markdown("# ⚙️ Session Setup")
    st.markdown("Configure your party and enemies before beginning the session.")
    
    st.markdown("---")

    # Tabs for entry methods
    t_upload, t_paste, t_form, t_build = st.tabs(["Upload JSON", "Paste JSON", "Manual Entry", "Build Character"])

    with t_upload:
        up_chars = st.file_uploader("Upload one or more 5e character sheets", type=["json"], accept_multiple_files=True)
        if up_chars:
            added = 0
            for f in up_chars:
                try:
                    blob = json.load(f)
                    char = coerce_5e_sheet(blob)
                    if char.get("name"):
                        st.session_state.party.append(char)
                        added += 1
                except Exception as e:
                    st.warning(f"Failed to read {f.name}: {e}")
            if added:
                st.success(f"Added {added} character(s) to the party.")

    with t_paste:
        raw = st.text_area("Paste 5e JSON here (single character)", height=220)
        if st.button("Add Character From JSON"):
            try:
                blob = json.loads(raw)
                char = coerce_5e_sheet(blob)
                if char.get("name"):
                    st.session_state.party.append(char)
                    st.success(f"Added: {char['name']}")
                else:
                    st.warning("Name missing in JSON.")
            except Exception as e:
                st.error(f"Invalid JSON: {e}")

    with t_form:
        with st.form("char_form"):
            name = st.text_input("Name")
            colA, colB, colC, colD = st.columns(4)
            with colA:
                ac = st.number_input("AC", 0, 40, 10)
            with colB:
                hp = st.number_input("HP", 0, 500, 10)
            with colC:
                spd = st.text_input("Speed", value="30 ft.")
            with colD:
                lng = st.text_input("Languages", value="Common")

            st.markdown("**Abilities**")
            a1, a2, a3, a4, a5, a6 = st.columns(6)
            STR = a1.number_input("STR", 1, 30, 10)
            DEX = a2.number_input("DEX", 1, 30, 10)
            CON = a3.number_input("CON", 1, 30, 10)
            INT = a4.number_input("INT", 1, 30, 10)
            WIS = a5.number_input("WIS", 1, 30, 10)
            CHA = a6.number_input("CHA", 1, 30, 10)

            st.markdown("**Primary Attack**")
            atk_name = st.text_input("Attack Name", value="Weapon")
            atk_to_hit = st.number_input("To-Hit Bonus", -10, 20, 0)
            atk_damage = st.text_input("Damage Dice", value="1d6+0")

            submitted = st.form_submit_button("Add Character")
            if submitted:
                c = json.loads(json.dumps(EMPTY_CHAR))
                c["name"] = name
                c["ac"] = int(ac)
                c["hp"] = int(hp)
                c["speed"] = spd
                c["languages"] = lng
                c["abilities"] = {"STR": STR, "DEX": DEX, "CON": CON, "INT": INT, "WIS": WIS, "CHA": CHA}
                c["attacks"] = [{"name": atk_name, "to_hit": int(atk_to_hit), "damage": atk_damage}]
                if c["name"]:
                    st.session_state.party.append(c)
                    st.success(f"Added: {c['name']}")
                else:
                    st.warning("Name is required.")

    with t_build:
        st.markdown("### Build Character (Step-by-Step)")
        # reminder: these loaders already exist above; they accept .json or .txt

        races = load_srd_races()
        bgs = load_srd_backgrounds()
        classes = load_srd_classes()
        feats_db = load_srd_feats()
        equip_db = load_srd_equipment()

        c = st.session_state.builder_char
        step = st.session_state.builder_step
        total_steps = 7
        st.progress(step / float(total_steps), text=f"Step {step} of {total_steps}")

        # Sticky name across steps
        st.text_input("Character Name", key="builder_name")
        if st.session_state.builder_name:
            c["name"] = st.session_state.builder_name

        # convenience
        def _get_picked_race():
            r_pick = st.session_state.get("builder_race_pick", "")
            if not r_pick:
                return None, ""
            rb = next((r for r in races if r.get("name") == r_pick), None)
            return rb, r_pick

        # ------------------------------------------------------
        # STEP 1: Race
        # ------------------------------------------------------
        if step == 1:
            st.subheader("Step 1: Choose Race")
            
            # Build list of subrace names to exclude from main dropdown
            subrace_names = set()
            for r in races:
                for sr in r.get("subraces", []):
                    subrace_names.add(sr.get("name", ""))
            
            # Filter to only show base races (not subraces)
            base_races = [r for r in races if r.get("name", "") not in subrace_names]
            race_names = [r.get("name", "") for r in base_races]
            r_pick = st.selectbox("Race", race_names, key="builder_race_pick")

            if r_pick:
                race_data = next((r for r in races if r.get("name") == r_pick), {})
                
                # Check if this race has subraces
                subraces_list = race_data.get("subraces", [])
                subrace_data = None
                
                if subraces_list:
                    st.markdown("---")
                    st.markdown("### Choose Subrace")
                    subrace_name_options = [sr.get("name", "") for sr in subraces_list]
                    subrace_pick = st.selectbox("Subrace", subrace_name_options, key="builder_subrace_pick")
                    
                    if subrace_pick:
                        # Find the full subrace data from the races list
                        subrace_data = next((r for r in races if r.get("name") == subrace_pick), None)
                        if subrace_data:
                            st.success(f"Selected: {r_pick} ({subrace_pick})")
                        else:
                            st.warning(f"Subrace '{subrace_pick}' data not found in races list.")
                else:
                    # Clear subrace pick if base race has no subraces
                    if "builder_subrace_pick" in st.session_state:
                        del st.session_state["builder_subrace_pick"]
                
                # Show race details
                with st.expander("Race Details", expanded=True):
                    # ========== BASIC INFO SECTION ==========
                    st.markdown("### Basic Information")
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown(f"**Speed:** {race_data.get('speed', 30)} ft.")
                        # Extract actual size from size_description if size field is wrong
                        size_val = race_data.get('size', 'Medium')
                        size_desc = race_data.get('size_description', '')
                        if size_desc:
                            if 'Small' in size_desc:
                                size_val = 'Small'
                            elif 'Medium' in size_desc:
                                size_val = 'Medium'
                            elif 'Large' in size_desc:
                                size_val = 'Large'
                            elif 'Tiny' in size_desc:
                                size_val = 'Tiny'
                        st.markdown(f"**Size:** {size_val}")
                    
                    with col2:
                        if race_data.get("darkvision", 0) > 0:
                            st.markdown(f"**Darkvision:** {race_data.get('darkvision')} ft.")
                        # Age
                        age_info = race_data.get("age", "")
                        if age_info:
                            st.markdown(f"**Age:** {age_info[:100]}..." if len(age_info) > 100 else f"**Age:** {age_info}")
                    
                    # Alignment
                    alignment_info = race_data.get("alignment", "")
                    if alignment_info:
                        st.markdown(f"**Alignment:** {alignment_info[:150]}..." if len(alignment_info) > 150 else f"**Alignment:** {alignment_info}")
                    
                    # ========== ABILITY SCORE SECTION ==========
                    st.markdown("---")
                    st.markdown("### Ability Score Increases")
                    
                    # Show the descriptive text first
                    ability_score_text = race_data.get("ability_score_increase", "")
                    if ability_score_text:
                        st.info(ability_score_text)
                    
                    # Also show parsed bonuses
                    ab = race_data.get("ability_bonuses", [])
                    if ab:
                        bonus_parts = []
                        for b in ab:
                            if isinstance(b, dict):
                                # Handle nested format: {"ability_score": {"name": "STR"}, "bonus": 2}
                                if "ability_score" in b and isinstance(b["ability_score"], dict):
                                    stat_name = b["ability_score"].get("name", "")
                                    bonus_val = b.get("bonus", 0)
                                else:
                                    stat_name = b.get("name", "")
                                    bonus_val = b.get("bonus", 0)
                                if stat_name and bonus_val:
                                    bonus_parts.append(f"**{stat_name}** +{bonus_val}")
                        if bonus_parts:
                            st.markdown("**Bonuses:** " + ", ".join(bonus_parts))
                    
                    # Ability bonus options (choose your own)
                    ab_options = race_data.get("ability_bonus_options", {})
                    if ab_options and ab_options.get("choose", 0) > 0:
                        choose_count = ab_options.get("choose", 1)
                        options_list = ab_options.get("from", [])
                        option_names = [opt.get("name", "") for opt in options_list]
                        option_bonuses = {opt.get("name", ""): opt.get("bonus", 1) for opt in options_list}
                        
                        st.markdown(f"**Ability Choice:** Choose {choose_count} from the options below")
                        
                        # Let user make the choice here in Step 1
                        if choose_count == 1:
                            choice = st.selectbox(
                                f"Select ability (+{option_bonuses.get(option_names[0], 1) if option_names else 1}):",
                                option_names,
                                key="builder_race_ability_choice_1"
                            )
                            st.session_state["builder_ability_choices"] = [choice] if choice else []
                        else:
                            choices = st.multiselect(
                                f"Select {choose_count} abilities (+1 each):",
                                option_names,
                                max_selections=choose_count,
                                key="builder_race_ability_choices_multi"
                            )
                            st.session_state["builder_ability_choices"] = choices
                            if len(choices) < choose_count:
                                st.warning(f"Please select {choose_count} abilities. ({len(choices)} selected)")
                    
                    # ========== LANGUAGES SECTION ==========
                    st.markdown("---")
                    st.markdown("### Languages")
                    
                    # Show language description first
                    lang_desc = race_data.get("language_desc", "")
                    if lang_desc:
                        st.markdown(lang_desc)
                    else:
                        langs = race_data.get("languages", [])
                        if langs:
                            lang_names = []
                            for lang in langs:
                                if isinstance(lang, dict):
                                    lang_names.append(lang.get("name", ""))
                                else:
                                    lang_names.append(str(lang))
                            lang_names = [l for l in lang_names if l and l not in ["read", "write Common"]]
                            if lang_names:
                                st.markdown(f"You can speak, read, and write: **{', '.join(lang_names)}**")
                    
                    # ========== PROFICIENCIES SECTION ==========
                    profs = race_data.get("starting_proficiencies", [])
                    if profs:
                        st.markdown("---")
                        st.markdown("### Proficiencies")
                        
                        weapons = []
                        armor = []
                        tools = []
                        skills = []
                        other = []
                        
                        for p in profs:
                            prof_name = p.get("name", str(p)) if isinstance(p, dict) else str(p)
                            prof_type = p.get("type", "").lower() if isinstance(p, dict) else ""
                            
                            if prof_type == "weapon" or any(w in prof_name.lower() for w in ["sword", "bow", "axe", "crossbow", "dagger"]):
                                weapons.append(prof_name)
                            elif prof_type == "armor" or "armor" in prof_name.lower():
                                armor.append(prof_name)
                            elif prof_type == "tool" or "tools" in prof_name.lower():
                                tools.append(prof_name)
                            elif prof_type == "skill" or "Skill:" in prof_name:
                                skills.append(prof_name.replace("Skill: ", "").replace("Skill:", ""))
                            else:
                                other.append(prof_name)
                        
                        if weapons:
                            st.markdown(f"**Weapons:** {', '.join(weapons)}")
                        if armor:
                            st.markdown(f"**Armor:** {', '.join(armor)}")
                        if tools:
                            st.markdown(f"**Tools:** {', '.join(tools)}")
                        if skills:
                            st.markdown(f"**Skills:** {', '.join(skills)}")
                        if other:
                            st.markdown(f"**Other:** {', '.join(other)}")
                    
                    # ========== RESISTANCES SECTION ==========
                    dmg_res = race_data.get("damage_resistances", [])
                    cond_res = race_data.get("condition_resistances", [])
                    if dmg_res or cond_res:
                        st.markdown("---")
                        st.markdown("### Resistances & Immunities")
                        if dmg_res:
                            st.markdown(f"**Damage Resistances:** {', '.join(dmg_res)}")
                        if cond_res:
                            st.markdown(f"**Condition Resistances:** {', '.join(cond_res)}")
                    
                    # ========== RACIAL TRAITS SECTION ==========
                    race_traits = race_data.get("race_traits", [])
                    traits = race_data.get("traits", [])
                    
                    # Build a lookup from race_traits for descriptions
                    trait_desc_lookup = {}
                    for rt in race_traits:
                        if isinstance(rt, dict):
                            name = rt.get('name', '')
                            desc = rt.get('desc', '') or rt.get('description', '')
                            if name and len(name) < 50:  # Filter out lore paragraphs
                                trait_desc_lookup[name] = desc
                    
                    # Get trait names from traits list
                    trait_names_to_show = []
                    for t in traits:
                        if isinstance(t, dict):
                            name = t.get('name', '')
                        else:
                            name = str(t)
                        if name and len(name) < 50:  # Filter out lore paragraphs
                            trait_names_to_show.append(name)
                    
                    if trait_names_to_show or trait_desc_lookup:
                        st.markdown("---")
                        st.markdown("### Racial Traits")
                        
                        # Show traits from the traits list with descriptions from race_traits
                        shown_traits = set()
                        for trait_name in trait_names_to_show:
                            if trait_name in shown_traits:
                                continue
                            shown_traits.add(trait_name)
                            
                            trait_desc = trait_desc_lookup.get(trait_name, '')
                            if trait_desc:
                                # Clean up description - remove lore that got mixed in
                                if "\n" in trait_desc:
                                    trait_desc = trait_desc.split("\n")[0]
                                if len(trait_desc) > 400:
                                    trait_desc = trait_desc[:400] + "..."
                                st.markdown(f"**{trait_name}**")
                                st.markdown(f"> {trait_desc}")
                            else:
                                st.markdown(f"**{trait_name}**")
                        
                        # Also show any race_traits that weren't in traits list
                        for rt in race_traits:
                            if isinstance(rt, dict):
                                name = rt.get('name', '')
                                if name and name not in shown_traits and len(name) < 50:
                                    shown_traits.add(name)
                                    desc = rt.get('desc', '') or rt.get('description', '')
                                    if desc:
                                        if "\n" in desc:
                                            desc = desc.split("\n")[0]
                                        if len(desc) > 400:
                                            desc = desc[:400] + "..."
                                        st.markdown(f"**{name}**")
                                        st.markdown(f"> {desc}")
                                    else:
                                        st.markdown(f"**{name}**")
                
                # Show subrace details if a subrace is selected
                if subrace_data:
                    with st.expander("Subrace Details", expanded=True):
                        st.markdown(f"### {subrace_data.get('name', 'Subrace')}")
                        
                        # Subrace ability bonuses
                        sub_ab = subrace_data.get("ability_bonuses", [])
                        if sub_ab:
                            bonus_parts = []
                            for b in sub_ab:
                                if isinstance(b, dict):
                                    if "ability_score" in b and isinstance(b["ability_score"], dict):
                                        stat_name = b["ability_score"].get("name", "")
                                        bonus_val = b.get("bonus", 0)
                                    else:
                                        stat_name = b.get("name", "")
                                        bonus_val = b.get("bonus", 0)
                                    if stat_name and bonus_val:
                                        bonus_parts.append(f"**{stat_name}** +{bonus_val}")
                            if bonus_parts:
                                st.markdown("**Ability Bonuses:** " + ", ".join(bonus_parts))
                        
                        # Subrace traits
                        sub_traits = subrace_data.get("traits", [])
                        sub_race_traits = subrace_data.get("race_traits", [])
                        
                        if sub_traits or sub_race_traits:
                            st.markdown("**Subrace Traits:**")
                            
                            # Build trait description lookup
                            sub_trait_desc = {}
                            for rt in sub_race_traits:
                                if isinstance(rt, dict):
                                    name = rt.get('name', '')
                                    desc = rt.get('desc', '') or rt.get('description', '')
                                    if name:
                                        sub_trait_desc[name] = desc
                            
                            shown = set()
                            for t in sub_traits:
                                name = t.get('name', '') if isinstance(t, dict) else str(t)
                                if name and name not in shown:
                                    shown.add(name)
                                    desc = sub_trait_desc.get(name, '')
                                    if desc and len(desc) > 300:
                                        desc = desc[:300] + "..."
                                    if desc:
                                        st.markdown(f"- **{name}**: {desc}")
                                    else:
                                        st.markdown(f"- **{name}**")
                            
                            # Show any race_traits not in traits
                            for rt in sub_race_traits:
                                if isinstance(rt, dict):
                                    name = rt.get('name', '')
                                    if name and name not in shown:
                                        shown.add(name)
                                        desc = rt.get('desc', '') or rt.get('description', '')
                                        if desc and len(desc) > 300:
                                            desc = desc[:300] + "..."
                                        if desc:
                                            st.markdown(f"- **{name}**: {desc}")
                                        else:
                                            st.markdown(f"- **{name}**")
                        
                        # Store subrace data in session state for later use
                        st.session_state.builder_subrace_data = subrace_data
                else:
                    # Clear subrace data if no subrace selected
                    st.session_state.builder_subrace_data = None

            col = st.columns([1, 1])
            if col[0].button("Next: Ability Scores", type="primary"):
                if r_pick:
                    st.session_state.builder_step = 2
                    st.toast(f"Race selected: {r_pick}")
                    st.rerun()
                else:
                    st.warning("Please choose a race before continuing.")

            st.caption("SRD races source: " + str(st.session_state.get("srd_races_path", "(not found)")))

        # ------------------------------------------------------
        # STEP 2: Ability Scores (4d6, plus racial totals preview)
        # ------------------------------------------------------
        if step == 2:
            st.subheader("Step 2: Ability Scores")

            race_blob, r_pick = _get_picked_race()

            with st.expander("Ability Scores (4d6 drop lowest)", expanded=True):
                abilities = c.setdefault(
                    "abilities",
                    {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
                )

                if st.button("Roll 4d6 (drop lowest)", key="builder_roll_4d6"):
                    scores = roll_ability_scores_4d6_drop_lowest()
                    for key, val in zip(["STR", "DEX", "CON", "INT", "WIS", "CHA"], scores):
                        abilities[key] = val
                    st.toast(f"Rolled scores: {scores}")

                # BASE editable scores
                col1, col2, col3 = st.columns(3)
                abilities["STR"] = int(col1.number_input("STR (Base)", 3, 20, int(abilities.get("STR", 10)), key="builder_STR_base"))
                abilities["DEX"] = int(col2.number_input("DEX (Base)", 3, 20, int(abilities.get("DEX", 10)), key="builder_DEX_base"))
                abilities["CON"] = int(col3.number_input("CON (Base)", 3, 20, int(abilities.get("CON", 10)), key="builder_CON_base"))

                col4, col5, col6 = st.columns(3)
                abilities["INT"] = int(col4.number_input("INT (Base)", 3, 20, int(abilities.get("INT", 10)), key="builder_INT_base"))
                abilities["WIS"] = int(col5.number_input("WIS (Base)", 3, 20, int(abilities.get("WIS", 10)), key="builder_WIS_base"))
                abilities["CHA"] = int(col6.number_input("CHA (Base)", 3, 20, int(abilities.get("CHA", 10)), key="builder_CHA_base"))

                # --- compute racial bonuses without mutating the character ---
                race_bonus = {k: 0 for k in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]}
            
            if race_blob:
                ab = race_blob.get("ability_bonuses") or {}
                # 5e SRD style: list of {"ability_score": {"index": "con", "name": "CON"}, "bonus": 2}
                if isinstance(ab, list):
                    for entry in ab:
                        if not isinstance(entry, dict):
                            continue
                        key = None
                        if "name" in entry:
                            key = str(entry["name"]).upper()
                        if not key and isinstance(entry.get("ability_score"), dict):
                            as_obj = entry["ability_score"]
                            key = (as_obj.get("name") or as_obj.get("index") or "").upper()
                        bonus = int(entry.get("bonus", 0))
                        if key in race_bonus:
                            race_bonus[key] += bonus
                # simple dict style: {"STR": 2, "CON": 2}
                elif isinstance(ab, dict):
                    for k, v in ab.items():
                        key = str(k).upper()
                        if key in race_bonus:
                            race_bonus[key] += int(v)
                
                # Also add subrace bonuses to preview
                subrace_data = st.session_state.get("builder_subrace_data")
                if subrace_data:
                    sub_ab = subrace_data.get("ability_bonuses") or []
                    for entry in sub_ab:
                        if isinstance(entry, dict):
                            # Handle nested format: {"ability_score": {"name": "STR"}, "bonus": 1}
                            if "ability_score" in entry and isinstance(entry["ability_score"], dict):
                                key = entry["ability_score"].get("name", "").upper()
                            else:
                                # Handle simple format: {"name": "STR", "bonus": 1}
                                key = str(entry.get("name", "")).upper()
                            bonus = int(entry.get("bonus", 0))
                            if key in race_bonus:
                                race_bonus[key] += bonus

            # Check for ability choice options (e.g., "+1 to STR or WIS")
            ability_choice_bonus = {k: 0 for k in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]}
            if race_blob:
                ab_options = race_blob.get("ability_bonus_options", {})
                if ab_options and ab_options.get("choose", 0) > 0:
                    choose_count = ab_options.get("choose", 1)
                    options_list = ab_options.get("from", [])
                    
                    # Get unique ability names from options
                    option_names = list(set([opt.get("name", "") for opt in options_list]))
                    option_bonuses = {opt.get("name", ""): opt.get("bonus", 1) for opt in options_list}
                    
                    st.markdown("---")
                    st.markdown(f"**Racial Ability Choice:** Choose {choose_count} ability/abilities to increase")
                    
                    # Store choices in session state
                    choice_key = "builder_ability_choices"
                    if choice_key not in st.session_state:
                        st.session_state[choice_key] = []
                    
                    if choose_count == 1:
                        # Single choice - use radio or selectbox
                        choice = st.selectbox(
                            f"Choose one ability (+{option_bonuses.get(option_names[0], 1)}):",
                            option_names,
                            key="builder_ability_choice_1"
                        )
                        st.session_state[choice_key] = [choice] if choice else []
                        if choice:
                            ability_choice_bonus[choice] = option_bonuses.get(choice, 1)
                    else:
                        # Multiple choices - use multiselect
                        choices = st.multiselect(
                            f"Choose {choose_count} abilities (+1 each):",
                            option_names,
                            max_selections=choose_count,
                            key="builder_ability_choices_multi"
                        )
                        st.session_state[choice_key] = choices
                        for ch in choices:
                            ability_choice_bonus[ch] = option_bonuses.get(ch, 1)
                        
                        if len(choices) < choose_count:
                            st.warning(f"Please select {choose_count} abilities. ({len(choices)} selected)")

            # build totals for all six abilities first
            totals = {}
            for abbr in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]:
                base = int(abilities.get(abbr, 10))
                totals[abbr] = base + int(race_bonus.get(abbr, 0)) + int(ability_choice_bonus.get(abbr, 0))

            # now it's safe to reference all of them in the UI
            subrace_label = ""
            if st.session_state.get("builder_subrace_data"):
                subrace_label = " & Subrace"
            choice_label = ""
            if any(v > 0 for v in ability_choice_bonus.values()):
                choice_label = " + Choice"
            st.markdown(f"**Final Ability Totals (with Race{subrace_label}{choice_label})**")
            t1, t2, t3 = st.columns(3)
            t1.number_input("STR (Total)", 1, 30, totals["STR"], key="builder_STR_total", disabled=True)
            t2.number_input("DEX (Total)", 1, 30, totals["DEX"], key="builder_DEX_total", disabled=True)
            t3.number_input("CON (Total)", 1, 30, totals["CON"], key="builder_CON_total", disabled=True)

            t4, t5, t6 = st.columns(3)
            t4.number_input("INT (Total)", 1, 30, totals["INT"], key="builder_INT_total", disabled=True)
            t5.number_input("WIS (Total)", 1, 30, totals["WIS"], key="builder_WIS_total", disabled=True)
            t6.number_input("CHA (Total)", 1, 30, totals["CHA"], key="builder_CHA_total", disabled=True)

            # Navigation buttons
            col = st.columns([1, 1])
            if col[0].button("Back", key="abilities_back"):
                st.session_state.builder_step = 1
                st.rerun()

            if col[1].button("Apply Race & Continue to Background", type="primary"):
                if not r_pick or not race_blob:
                    st.warning("Please choose a race in Step 1 first.")
                else:
                    # Check if ability choices are required and made
                    ab_options = race_blob.get("ability_bonus_options", {})
                    if ab_options and ab_options.get("choose", 0) > 0:
                        choices = st.session_state.get("builder_ability_choices", [])
                        required = ab_options.get("choose", 1)
                        if len(choices) < required:
                            st.warning(f"Please select {required} ability/abilities for your racial bonus.")
                            st.stop()
                    
                    # apply_race mutates c["abilities"] to include these racial bonuses
                    apply_race(c, race_blob)
                    
                    # Apply ability choices
                    ability_choices = st.session_state.get("builder_ability_choices", [])
                    if ability_choices and race_blob.get("ability_bonus_options"):
                        options_list = race_blob["ability_bonus_options"].get("from", [])
                        option_bonuses = {opt.get("name", ""): opt.get("bonus", 1) for opt in options_list}
                        for choice in ability_choices:
                            if choice in c["abilities"]:
                                c["abilities"][choice] += option_bonuses.get(choice, 1)
                        # Clear the pending choice since we applied it
                        c.pop("pending_ability_choice", None)
                        c.pop("ability_choice_options", None)
                    
                    # Apply subrace if selected
                    subrace_data = st.session_state.get("builder_subrace_data")
                    if subrace_data:
                        apply_subrace(c, subrace_data)
                    
                    st.session_state.builder_step = 3
                    st.toast("Ability scores applied and race bonuses added.")
                    st.rerun()

        # ------------------------------------------------------
        # STEP 3: Background
        # ------------------------------------------------------
        if step == 3:
            st.subheader("Step 3: Choose Background")
            bg_names = [b.get("name", "") for b in bgs]
            b_pick = st.selectbox("Background", bg_names, key="builder_bg_pick")

            bg_ability_choices = []
            if b_pick:
                bg_blob = next((b for b in bgs if b.get("name") == b_pick), {})
                
                # Show background details
                with st.expander("Background Details", expanded=True):
                    st.markdown(f"**{bg_blob.get('name', '')}**")
                    st.caption(bg_blob.get("description", ""))
                    
                    # Ability Bonuses
                    ab_static = bg_blob.get("ability_bonuses", [])
                    ab_options = bg_blob.get("ability_bonus_options", {})
                    
                    if ab_static:
                        bonus_strs = [f"+{b.get('bonus', 1)} {b.get('name', '')}" for b in ab_static]
                        st.markdown(f"**Ability Bonus:** {', '.join(bonus_strs)}")
                    
                    if ab_options and ab_options.get("choose", 0) > 0:
                        opts = ab_options.get("from", [])
                        opt_strs = [f"+{o.get('bonus', 1)} {o.get('name', '')}" for o in opts]
                        st.markdown(f"**Ability Choice:** Choose {ab_options['choose']} from: {', '.join(opt_strs)}")
                    
                    # Skills
                    skills = bg_blob.get("skills", [])
                    if skills:
                        st.markdown(f"**Skills:** {', '.join(skills)}")
                    
                    # Languages
                    langs = bg_blob.get("languages", 0)
                    if langs:
                        st.markdown(f"**Languages:** {langs} of your choice")
                    
                    # Tools
                    tools = bg_blob.get("tool_proficiencies", [])
                    if tools:
                        st.markdown(f"**Tool Proficiencies:** {', '.join(tools)}")
                    
                    # Origin Feat
                    origin_feat = bg_blob.get("origin_feat")
                    if origin_feat:
                        st.markdown(f"**Origin Feat:** {origin_feat}")
                    
                    # Feature
                    feature = bg_blob.get("feature", {})
                    if feature:
                        st.markdown(f"**Feature - {feature.get('name', '')}:** {feature.get('description', '')}")
                
                # --- Handle ability bonus choices ---
                if ab_options and ab_options.get("choose", 0) > 0:
                    st.markdown("---")
                    num_choices = ab_options.get("choose", 1)
                    opts = ab_options.get("from", [])
                    opt_names = [o.get("name", "") for o in opts]
                    
                    st.markdown(f"**Choose {num_choices} Ability Score(s) to increase (from Background):**")
                    
                    cols = st.columns(num_choices)
                    for j in range(num_choices):
                        with cols[j]:
                            # Filter to prevent selecting same ability twice
                            available = [n for n in opt_names if n not in bg_ability_choices]
                            choice = st.selectbox(
                                f"Choice {j+1}",
                                [""] + sorted(available),
                                key=f"bg_ability_choice_{j}"
                            )
                            if choice:
                                bg_ability_choices.append(choice)

            col = st.columns([1, 1])
            if col[0].button("Back", key="bg_back"):
                st.session_state.builder_step = 2
                st.rerun()

            # Validate choices before allowing apply
            bg_blob = next((b for b in bgs if b.get("name") == b_pick), {}) if b_pick else {}
            ab_options = bg_blob.get("ability_bonus_options", {})
            needs_choice = ab_options.get("choose", 0) if ab_options else 0
            
            can_apply = True
            if needs_choice > 0 and len(bg_ability_choices) < needs_choice:
                st.warning(f"Please make {needs_choice} ability choice(s) for this background.")
                can_apply = False

            if col[1].button("Apply Background", type="primary", disabled=not can_apply):
                if b_pick:
                    apply_background(c, bg_blob, ability_choices=bg_ability_choices if bg_ability_choices else None)
                    st.session_state.builder_step = 4
                    st.toast(f"Background applied: {b_pick}")
                    st.rerun()

        # ------------------------------------------------------
        # STEP 4: Class
        # ------------------------------------------------------
        if step == 4:
            st.subheader("Step 4: Choose Class (Level 1)")
            cls_names = [x.get("name", "") for x in classes]
            c_pick = st.selectbox("Class", cls_names, key="builder_class_pick")
            kit_idx = 0

            if c_pick:
                c_blob = next((x for x in classes if x.get("name") == c_pick), None)
                kits = (c_blob or {}).get("starting_equipment_kits") or []
                if kits:
                    kit_labels = [k.get("name", f"Kit {i+1}") for i, k in enumerate(kits)]
                    kit_idx = st.selectbox(
                        "Starting Equipment",
                        list(range(len(kits))),
                        format_func=lambda i: kit_labels[i],
                        key="builder_class_kit_idx",
                    )
                
                # --------- Spellcasting Section ---------
                # Check if class has spellcasting at level 1
                spell_ability = (c_blob or {}).get("spellcasting_ability", "")
                levels_data = (c_blob or {}).get("levels", {})
                level_1_data = levels_data.get("1", {})
                cantrips_known = level_1_data.get("cantrips_known", 0)
                spells_known = level_1_data.get("spells_known", 0)
                
                has_spellcasting = bool(spell_ability) and (cantrips_known > 0 or spells_known > 0)
                
                if has_spellcasting:
                    st.markdown("---")
                    st.markdown(f"### 🔮 Spellcasting (Ability: **{spell_ability}**)")
                    
                    # Load spells for this class
                    available_cantrips, available_level1 = get_spells_for_class(c_pick, max_level=1)
                    
                    # Initialize spell selection state
                    if "builder_cantrips" not in st.session_state:
                        st.session_state.builder_cantrips = []
                    if "builder_spells_l1" not in st.session_state:
                        st.session_state.builder_spells_l1 = []
                    
                    # Cantrip selection
                    if cantrips_known > 0 and available_cantrips:
                        st.markdown(f"**Cantrips Known:** {cantrips_known}")
                        cantrip_names = [s["name"] for s in available_cantrips]
                        selected_cantrips = st.multiselect(
                            "Select Cantrips",
                            cantrip_names,
                            default=st.session_state.builder_cantrips[:cantrips_known],
                            max_selections=cantrips_known,
                            key="builder_cantrips_select",
                        )
                        st.session_state.builder_cantrips = selected_cantrips
                        
                        # Show cantrip details
                        if selected_cantrips:
                            with st.expander("Cantrip Details", expanded=False):
                                for name in selected_cantrips:
                                    spell = next((s for s in available_cantrips if s["name"] == name), None)
                                    if spell:
                                        dmg_info = f" | **Damage:** {spell['damage']} {spell.get('damage_type', '')}" if spell.get('damage') else ""
                                        save_info = f" | **Save:** {spell['save']}" if spell.get('save') else ""
                                        atk_info = " | **Spell Attack**" if spell.get('type') == 'spell_attack' else ""
                                        st.markdown(f"**{name}** ({spell['school']}){dmg_info}{save_info}{atk_info}")
                                        st.caption(spell.get('description', '')[:200] + "..." if len(spell.get('description', '')) > 200 else spell.get('description', ''))
                    
                    # Level 1 spell selection
                    if spells_known > 0 and available_level1:
                        st.markdown(f"**Level 1 Spells Known:** {spells_known}")
                        spell_l1_names = [s["name"] for s in available_level1]
                        selected_spells = st.multiselect(
                            "Select Level 1 Spells",
                            spell_l1_names,
                            default=st.session_state.builder_spells_l1[:spells_known],
                            max_selections=spells_known,
                            key="builder_spells_l1_select",
                        )
                        st.session_state.builder_spells_l1 = selected_spells
                        
                        # Show spell details
                        if selected_spells:
                            with st.expander("Spell Details", expanded=False):
                                for name in selected_spells:
                                    spell = next((s for s in available_level1 if s["name"] == name), None)
                                    if spell:
                                        dmg_info = f" | **Damage:** {spell['damage']} {spell.get('damage_type', '')}" if spell.get('damage') else ""
                                        save_info = f" | **Save:** {spell['save']}" if spell.get('save') else ""
                                        atk_info = " | **Spell Attack**" if spell.get('type') == 'spell_attack' else ""
                                        conc_info = " | ⚡ Concentration" if spell.get('concentration') else ""
                                        st.markdown(f"**{name}** ({spell['school']}){dmg_info}{save_info}{atk_info}{conc_info}")
                                        st.caption(spell.get('description', '')[:200] + "..." if len(spell.get('description', '')) > 200 else spell.get('description', ''))
                    
                    # Spell slots info
                    spell_slots = level_1_data.get("spell_slots_by_level", {})
                    if spell_slots:
                        slots_str = ", ".join(f"Level {k}: {v} slots" for k, v in spell_slots.items())
                        st.info(f"**Spell Slots at Level 1:** {slots_str}")
                
                with st.expander("Class Details", expanded=False):
                    st.write(c_blob or {})
                
                # ---- Artificer-specific options ----
                if c_pick == "Artificer":
                    st.markdown("---")
                    st.markdown("### ⚙️ Artificer Options")
                    st.info("Artificers use **Crafting Points** instead of spell slots. Your inventions are technology, not magic!")
                    
                    # Note about Signature Invention (level 3 feature)
                    st.caption("At level 3, you'll choose your **Signature Invention**: Personal Armor, Mechanical Servant, or Cannon Weapon.")
                    
                    # For now, let them pre-select if they want (stored for later)
                    with st.expander("Preview Signature Invention (Level 3)", expanded=False):
                        invention_choice = st.radio(
                            "Choose your invention path:",
                            ["armor", "servant", "cannon"],
                            format_func=lambda x: {
                                "armor": "⚔️ Personal Suit of Armor - AC = 10 + INT mod, damage reduction",
                                "servant": "🤖 Mechanical Servant - Autonomous companion, HP = level",
                                "cannon": "💥 Cannon Weapon - 1d6 damage, 120 ft range, uses INT"
                            }.get(x, x),
                            key="builder_artificer_invention",
                            horizontal=False,
                        )
                        # Note: widget key already stores value in session_state
                        
                        if invention_choice == "cannon":
                            st.selectbox(
                                "Cannon damage type:",
                                ["force", "piercing", "thunder", "fire", "cold", "lightning"],
                                key="builder_cannon_type"
                            )
                            # Note: widget key already stores value in session_state
                
                # ---- Cleric-specific options ----
                if c_pick == "Cleric":
                    st.markdown("---")
                    st.markdown("### ⛪ Cleric Options")
                    
                    # Domain Selection
                    st.markdown("**Choose Your Divine Domain:**")
                    domain_choice = st.selectbox(
                        "Divine Domain",
                        list(CLERIC_DOMAINS.keys()),
                        key="builder_cleric_domain",
                        help="Your domain grants bonus spells and special abilities."
                    )
                    
                    domain_data = CLERIC_DOMAINS.get(domain_choice, {})
                    st.caption(domain_data.get("description", ""))
                    
                    # Show domain spells
                    with st.expander("Domain Spells (always prepared)", expanded=False):
                        domain_spells = domain_data.get("domain_spells", {})
                        for level, spells in sorted(domain_spells.items()):
                            st.caption(f"**Level {level}:** {', '.join(spells)}")
                    
                    # Show bonus proficiencies
                    bonus_profs = domain_data.get("bonus_proficiencies", [])
                    if bonus_profs:
                        st.caption(f"**Bonus Proficiencies:** {', '.join(bonus_profs)}")
                
                # ---- Sorcerer-specific options ----
                if c_pick == "Sorcerer":
                    st.markdown("---")
                    st.markdown("### 🔥 Sorcerer Options")
                    
                    # Bloodline Selection
                    st.markdown("**Choose Your Bloodline:**")
                    bloodline_choice = st.selectbox(
                        "Sorcerous Bloodline",
                        ["Dragon", "Fey", "Fiendish"],
                        key="builder_sorcerer_bloodline",
                        help="Your bloodline shapes your magical abilities and grants unique features."
                    )
                    
                    bloodline_descriptions = {
                        "Dragon": "Draconic ancestry grants elemental resistance, breath weapon, and scales.",
                        "Fey": "Fey heritage grants charm resistance, Misty Step, and enchantment mastery.",
                        "Fiendish": "Infernal blood grants fire resistance, hellfire empowerment, and dark power."
                    }
                    st.caption(bloodline_descriptions.get(bloodline_choice, ""))
                    
                    # Dragon type selection for Dragon bloodline
                    if bloodline_choice == "Dragon":
                        dragon_type = st.selectbox(
                            "Dragon Type (determines damage type):",
                            ["Red", "Gold", "Brass", "Blue", "Bronze", "Black", "Copper", "Green", "White", "Silver"],
                            key="builder_sorcerer_dragon_type"
                        )
                        dragon_damage = {
                            "Red": "Fire", "Gold": "Fire", "Brass": "Fire",
                            "Blue": "Lightning", "Bronze": "Lightning",
                            "Black": "Acid", "Copper": "Acid",
                            "Green": "Poison",
                            "White": "Cold", "Silver": "Cold",
                        }
                        st.caption(f"Damage type: {dragon_damage.get(dragon_type, 'Fire')}")
                    
                    # Fiend type selection for Fiendish bloodline
                    if bloodline_choice == "Fiendish":
                        fiend_type = st.selectbox(
                            "Fiend Type:",
                            ["Devil", "Demon", "Yugoloth"],
                            key="builder_sorcerer_fiend_type"
                        )
                    
                    # Preview Metamagic (Level 3)
                    with st.expander("Preview Metamagic (Level 3)", expanded=False):
                        st.caption("At level 3, you'll choose 1 Metamagic option:")
                        for meta_name, meta_data in SORCERER_METAMAGIC.items():
                            cost = meta_data.get("cost", 1)
                            cost_str = f"{cost} SP" if isinstance(cost, int) else "Spell level SP"
                            st.markdown(f"- **{meta_name}** ({cost_str}): {meta_data['description']}")
                
                # ---- Warlock-specific options ----
                if c_pick == "Warlock":
                    st.markdown("---")
                    st.markdown("### 🌙 Warlock Options")
                    
                    # Patron Selection (Level 1)
                    st.markdown("**Choose Your Patron:**")
                    patron_choice = st.selectbox(
                        "Eldritch Patron",
                        ["Fiend", "Great Old One", "Archfey", "Celestial", "Shadow", "Draconic"],
                        key="builder_warlock_patron",
                        help="Your patron grants you power and shapes your abilities."
                    )
                    
                    patron_descriptions = {
                        "Fiend": "Devils, Demons - Fire resistance, dark bargains, infernal power.",
                        "Great Old One": "Eldritch horrors - Telepathy, psychic resistance, madness.",
                        "Archfey": "Powerful fey - Misty Step, charm, illusion magic.",
                        "Celestial": "Divine beings - Healing light, radiant resistance.",
                        "Shadow": "Death and darkness - Speak with dead, necrotic resistance.",
                        "Draconic": "Elder dragons - Breath weapon, draconic presence."
                    }
                    st.caption(patron_descriptions.get(patron_choice, ""))
                    
                    # Dragon type selection for Draconic patron
                    if patron_choice == "Draconic":
                        dragon_type = st.selectbox(
                            "Dragon Type (determines breath damage):",
                            ["Fire", "Cold", "Lightning", "Acid", "Poison"],
                            key="builder_warlock_dragon_type"
                        )
                    
                    # Preview of Pact Boon (Level 3)
                    with st.expander("Preview Pact Boon (Level 3)", expanded=False):
                        st.caption("At level 3, you'll choose a Pact Boon:")
                        pact_boon = st.radio(
                            "Pact Boon:",
                            ["Blade", "Chain", "Tome", "Talisman"],
                            format_func=lambda x: {
                                "Blade": "⚔️ Pact of the Blade - Create magical pact weapons",
                                "Chain": "🐉 Pact of the Chain - Powerful familiar (imp, pseudodragon, etc.)",
                                "Tome": "📖 Pact of the Tome - Book of Shadows with 3 cantrips from any class",
                                "Talisman": "🔮 Pact of the Talisman - Amulet that aids ability checks"
                            }.get(x, x),
                            key="builder_warlock_pact_boon",
                            horizontal=False,
                        )
                    
                    # Preview of Invocations (Level 2)
                    with st.expander("Preview Eldritch Invocations (Level 2)", expanded=False):
                        st.caption("At level 2, you'll choose 2 Eldritch Invocations. Here are some options:")
                        
                        # Show available invocations
                        invocation_options = [
                            ("Agonizing Blast", "Add CHA mod to Eldritch Blast damage (requires Eldritch Blast)"),
                            ("Armor of Shadows", "Cast Mage Armor on yourself at will"),
                            ("Devil's Sight", "See in magical/nonmagical darkness to 120 ft"),
                            ("Eldritch Sight", "Cast Detect Magic at will"),
                            ("Mask of Many Faces", "Cast Disguise Self at will"),
                            ("Repelling Blast", "Eldritch Blast pushes target 10 ft (requires Eldritch Blast)"),
                            ("Fiendish Vigor", "Cast False Life on yourself at will"),
                            ("Beast Speech", "Cast Speak with Animals at will"),
                        ]
                        
                        for inv_name, inv_desc in invocation_options:
                            st.markdown(f"- **{inv_name}**: {inv_desc}")

            col = st.columns([1, 1])
            if col[0].button("Back  ", key="class_back"):
                st.session_state.builder_step = 3
                st.rerun()

            if col[1].button("Apply Class", type="primary"):
                if c_pick:
                    cls_blob = next(x for x in classes if x.get("name") == c_pick)
                    apply_class_level1(
                        c,
                        cls_blob,
                        kit_idx=int(st.session_state.get("builder_class_kit_idx", 0)),
                    )
                    
                    # Store Artificer-specific choices before initializing resources
                    if c_pick == "Artificer":
                        c["signature_invention"] = st.session_state.get("builder_artificer_invention", "cannon")
                        c["cannon_damage_type"] = st.session_state.get("builder_cannon_type", "force")
                    
                    # Store Cleric-specific choices
                    if c_pick == "Cleric":
                        c["cleric_domain"] = st.session_state.get("builder_cleric_domain", "Life")
                        c["cleric_sanctified"] = "divine_strike"  # Default, can change at level 7
                    
                    # Store Sorcerer-specific choices
                    if c_pick == "Sorcerer":
                        c["sorcerer_bloodline"] = st.session_state.get("builder_sorcerer_bloodline", "Dragon")
                        c["sorcerer_dragon_type"] = st.session_state.get("builder_sorcerer_dragon_type", "Red")
                        c["sorcerer_fiend_type"] = st.session_state.get("builder_sorcerer_fiend_type", "Devil")
                        c["sorcerer_metamagic"] = []  # Will be selected at level 3
                    
                    # Store Warlock-specific choices
                    if c_pick == "Warlock":
                        c["warlock_patron"] = st.session_state.get("builder_warlock_patron", "Fiend")
                        c["warlock_pact_boon"] = st.session_state.get("builder_warlock_pact_boon", "Blade")
                        c["warlock_dragon_type"] = st.session_state.get("builder_warlock_dragon_type", "Fire")
                        c["warlock_invocations"] = []  # Will be selected at level 2
                    
                    # NEW: initialize level 1 class resources/actions for Barbarian, Bard, Artificer
                    add_level1_class_resources_and_actions(c)
                    
                    # --------- Apply Spellcasting ---------
                    spell_ability = cls_blob.get("spellcasting_ability", "")
                    if spell_ability:
                        c["spellcasting_ability"] = spell_ability
                        
                        # Get selected spells
                        selected_cantrips = st.session_state.get("builder_cantrips", [])
                        selected_spells_l1 = st.session_state.get("builder_spells_l1", [])
                        
                        # Load spell data
                        all_spells = load_srd_spells()
                        actions = c.setdefault("actions", [])
                        spells_list = c.setdefault("spells", [])
                        
                        # Add cantrips as actions (at-will)
                        for spell_name in selected_cantrips:
                            spell_data = next((s for s in all_spells if s["name"] == spell_name), None)
                            if spell_data:
                                spells_list.append(spell_name)
                                action = spell_to_action(spell_data, c)
                                action["at_will"] = True  # Cantrips are at-will
                                actions.append(action)
                        
                        # Add level 1 spells as actions (use spell slots)
                        for spell_name in selected_spells_l1:
                            spell_data = next((s for s in all_spells if s["name"] == spell_name), None)
                            if spell_data:
                                spells_list.append(spell_name)
                                action = spell_to_action(spell_data, c)
                                action["at_will"] = False  # Level 1+ spells use slots
                                actions.append(action)
                        
                        # Store spell slots
                        levels_data = cls_blob.get("levels", {})
                        level_1_data = levels_data.get("1", {})
                        spell_slots = level_1_data.get("spell_slots_by_level", {})
                        if spell_slots:
                            resources = c.setdefault("resources", {})
                            for lvl, slots in spell_slots.items():
                                resources[f"Spell Slot (Level {lvl})"] = {"current": slots, "max": slots}
                        
                        # Clear spell selection state for next character
                        st.session_state.builder_cantrips = []
                        st.session_state.builder_spells_l1 = []

                    st.session_state.builder_step = 5
                    st.rerun()
                else:
                    st.warning("Please choose a class before applying it.")

        # ------------------------------------------------------
        # STEP 5: Skills (uses class skill points + INT mod)
        # ------------------------------------------------------
        if step == 5:
            st.subheader("Step 5: Assign Skills")

            c_pick = st.session_state.get("builder_class_pick", "")
            cls_blob = next((x for x in classes if x.get("name") == c_pick), None) if c_pick else None

            if not cls_blob:
                st.warning("Please choose and apply a class in Step 4 first.")
            else:
                # --------- figure out the class's skill list ----------
                # Try several possible keys so we work with different JSON formats
                skill_list = []
                for key in ["skill_list", "skills", "class_skills", "trained_skills"]:
                    val = cls_blob.get(key)
                    if isinstance(val, list) and val:
                        skill_list = [str(s) for s in val]
                        break

                if not skill_list:
                    st.warning("This class has no skill list defined. "
                            "Check your SRD_Classes.json for a 'skill_list' or similar field.")
                else:
                    # --------- figure out how many skill points we have ----------
                    raw_sp = str(cls_blob.get("skill_points_per_level", "") or cls_blob.get("skill_points", "0"))
                    import re as _re
                    m = _re.search(r"(\d+)", raw_sp)
                    base_points = int(m.group(1)) if m else 0

                    # If the class JSON doesn't have skill points, use a fallback (e.g. 2 + INT)
                    if base_points == 0:
                        base_points = 2  # tweak this default

                    int_score = int(c.get("abilities", {}).get("INT", 10))
                    int_mod = _ability_mod(int_score)
                    total_points = max(1, base_points + int_mod)

                    st.markdown(
                        f"Class skill points: **{base_points} + INT mod ({int_mod:+d}) = {total_points}**"
                    )

                    # --------- rank inputs ----------
                    ranks_state = st.session_state.builder_skill_ranks
                    for sk in skill_list:
                        ranks_state.setdefault(sk, 0)

                    cols = st.columns(3)
                    spent = 0
                    for i, sk in enumerate(skill_list):
                        col = cols[i % 3]
                        current = int(ranks_state.get(sk, 0))
                        new_val = col.number_input(
                            sk,
                            min_value=0,
                            max_value=10,
                            value=current,
                            key=f"skill_rank_{sk}",
                        )
                        ranks_state[sk] = new_val
                        spent += new_val

                    st.markdown(f"**Skill points spent:** {spent} / {total_points}")
                    if spent > total_points:
                        st.error("You have spent more skill points than available.")

            col = st.columns([1, 1])
            if col[0].button("Back   ", key="skills_back"):
                st.session_state.builder_step = 4
                st.rerun()

            if col[1].button("Apply Skills", type="primary"):
                if not cls_blob:
                    st.warning("You must choose a class in Step 4 first.")
                else:
                    # recompute totals for validation
                    raw_sp = str(cls_blob.get("skill_points_per_level", "") or cls_blob.get("skill_points", "0"))
                    import re as _re
                    m = _re.search(r"(\d+)", raw_sp)
                    base_points = int(m.group(1)) if m else 0
                    if base_points == 0:
                        base_points = 2

                    int_score = int(c.get("abilities", {}).get("INT", 10))
                    int_mod = _ability_mod(int_score)
                    total_points = max(1, base_points + int_mod)

                    # same logic to discover skill list
                    skill_list = []
                    for key in ["skill_list", "skills", "class_skills", "trained_skills"]:
                        val = cls_blob.get(key)
                        if isinstance(val, list) and val:
                            skill_list = [str(s) for s in val]
                            break

                    ranks_state = st.session_state.builder_skill_ranks
                    spent = sum(int(ranks_state.get(sk, 0)) for sk in skill_list)

                    if spent > total_points:
                        st.error("Too many points spent; reduce some ranks before continuing.")
                    else:
                        # write to character
                        skills_dict = c.setdefault("skills", {})
                        prof_skills = set(c.setdefault("profs", {}).setdefault("skills", []))
                        for sk in skill_list:
                            r = int(ranks_state.get(sk, 0))
                            if r > 0:
                                skills_dict[sk] = r
                                prof_skills.add(sk)
                        c["profs"]["skills"] = sorted(prof_skills)
                        st.session_state.builder_step = 6
                        st.toast("Skills applied.")
                        st.rerun()

        # ------------------------------------------------------
        # STEP 6: Feats
        # ------------------------------------------------------
        if step == 6:
            st.subheader("Step 6: Choose Feats (Optional)")
            feat_names = [f.get("name", "") if isinstance(f, dict) else str(f) for f in feats_db]
            chosen = st.multiselect("Feats", feat_names, key="builder_feats_multi")

            col = st.columns([1, 1])
            if col[0].button("Back    ", key="feats_back"):
                st.session_state.builder_step = 5
                st.rerun()

            if col[1].button("Apply Feats", type="primary"):
                apply_feats(c, st.session_state.get("builder_feats_multi", []))
                st.session_state.builder_step = 7
                st.toast("Feats applied.")
                st.rerun()

        # ------------------------------------------------------
        # STEP 7: Equipment
        # ------------------------------------------------------
        if step == 7:
            st.subheader("Step 7: Add Equipment (Optional)")
            item_names = [i.get("name", "") if isinstance(i, dict) else str(i) for i in equip_db]
            extras = st.multiselect("Add items", item_names, key="builder_items_multi")

            if st.button("Add Items"):
                eq = set(c.get("equipment") or [])
                for it in extras:
                    if it:
                        eq.add(it)
                c["equipment"] = sorted(eq)
                c["ac"] = compute_ac_from_equipment(c)

                sync_attacks_from_equipment(c)

                st.toast("Items added.")

            col = st.columns([1, 1, 2])
            if col[0].button("Back     ", key="equip_back"):
                st.session_state.builder_step = 6
                st.rerun()

            if col[1].button("Reset Builder"):
                st.session_state.builder_char = {
                    "name": "",
                    "level": 1,
                    "class": "",
                    "subclass": "",
                    "race": "",
                    "background": "",
                    "ac": 10,
                    "hp": 10,
                    "speed": "30 ft.",
                    "abilities": {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
                    "proficiency_bonus": 2,
                    "profs": {"saves": [], "skills": [], "weapons": [], "armor": []},
                    "features": [],
                    "feats": [],
                    "spells": [],
                    "equipment": [],
                    "attacks": [],
                    "default_attack_index": 0,
                    "resources": {},   # NEW
                    "actions": [],   
                }
                st.session_state.builder_name = ""
                st.session_state.builder_step = 1
                st.session_state.builder_skill_ranks = {}
                st.toast("Cleared working character.")

            if col[2].button("Add to Party", type="primary"):
                if not c.get("name"):
                    st.warning("Please set a character name.")
                else:
                    st.session_state.party.append(json.loads(json.dumps(c)))
                    st.success(f"Added to party: {c['name']}")
                    # stay on setup page; builder remains for creating another character
            
        st.markdown("---")
        
        with st.expander("🔍 Character Preview (JSON)", expanded=False):
            st.json(st.session_state.builder_char)

        st.markdown("#### 👥 Current Party")
        if not st.session_state.party:
            st.info("🧙 No party members yet. Use the tabs above to add characters.")
        else:
            for i, c in enumerate(st.session_state.party):
                box = st.container(border=True)
                t1, t2, t3, t4 = box.columns([4, 2, 2, 2])

                with t1:
                    st.markdown(f"**{c.get('name','')}**")
                with t2:
                    c["ac"] = int(
                        st.number_input(
                            "AC", 0, 40, int(c.get("ac", 10)), key=f"run_p_ac_{i}"
                        )
                    )
                with t3:
                    c["hp"] = int(
                        st.number_input(
                            "HP", 0, 500, int(c.get("hp", 10)), key=f"run_p_hp_{i}"
                        )
                    )
                with t4:
                    if st.button("Remove", key=f"run_p_rm_{i}"):
                        del st.session_state.party[i]
                        st.rerun()

                # Determine if this party member is the active turn
                is_active_pc = False
                if st.session_state.in_combat:
                    ent = current_turn()
                    if ent and ent.get("kind") == "party" and ent.get("idx") == i:
                        is_active_pc = True

                # Attacks panel – always visible, but marked if it's not their turn
                with box.expander("Attacks"):
                    attacks = c.get("attacks", [])
                    if not attacks:
                        st.write("No attacks listed.")
                    else:
                        for a in attacks:
                            st.write(a)

                    if st.session_state.in_combat and not is_active_pc:
                        st.caption("Waiting for this character's turn.")

        st.markdown("#### Enemies")
        with st.container(border=True):
            
            # Manual entry
            e1, e2, e3, e4, e5 = st.columns([4, 2, 2, 2, 2])
            e_name = e1.text_input("Name", key="e_name")
            e_ac = e2.number_input("AC", 0, 40, 13, key="e_ac")
            e_hp = e3.number_input("HP", 0, 500, 11, key="e_hp")
            e_atk = e4.text_input("Attack (e.g., 'Bite', +4, '2d4+2')", key="e_atk")
            add_enemy = e5.button("Add Enemy")
            if add_enemy and e_name.strip():
                st.session_state.enemies.append(
                    {
                        "name": e_name.strip(),
                        "ac": int(e_ac),
                        "hp": int(e_hp),
                        "attacks": [{"name": e_atk or "Attack", "to_hit": 0, "damage": "1d6"}],
                    }
                )
                st.success(f"Enemy added: {e_name}")

            # From SRD with quantity
            st.markdown("---")
            st.markdown("**Add From SRD**")

            if not st.session_state.get("srd_enemies"):
                st.caption("SRD file not found at ../data/SRD_Monsters.json")
            else:
                srd_names = [m.get("name", "") for m in st.session_state.srd_enemies if m.get("name")]
                srd_name = st.selectbox("SRD Monster", srd_names, key="add_srd_name")
                qty = st.number_input("Quantity", 1, 20, 1, key="add_srd_qty")

                sb = next((m for m in st.session_state.srd_enemies if m.get("name") == srd_name), None)

                if st.button("Add SRD Enemy", type="primary", key="add_srd_enemy_btn"):
                    if sb:
                        for _ in range(int(qty)):
                            blob = json.loads(json.dumps(sb))  # safe deep copy
                            blob["src"] = sb.get("name", "Enemy")
                            blob["name"] = f"{sb.get('name','Enemy')} #{len(st.session_state.enemies)+1}"
                            blob["hp"] = int(blob.get("hp", 10))
                            blob["max_hp"] = int(blob.get("max_hp", blob["hp"]))
                            blob["ac"] = int(blob.get("ac", 10))
                            blob["_hydrated"] = True  # Mark as hydrated since it came from SRD
                            st.session_state.enemies.append(blob)

                        st.toast(f"Added {qty}× {sb.get('name','Enemy')}")
                        st.rerun()
                    else:
                        st.warning("No SRD monster selected.")
                        

    st.markdown("---")
    
    # Summary before beginning
    party_count = len(st.session_state.party)
    enemy_count = len(st.session_state.enemies)
    
    col1, col2, col3 = st.columns([2, 2, 2])
    with col1:
        st.metric("Party Members", party_count)
    with col2:
        st.metric("Enemies", enemy_count)
    with col3:
        if st.button("🚀 Begin Session", type="primary", use_container_width=True):
            if not st.session_state.party:
                st.warning("⚠️ Add at least one party member before beginning.")
            else:                                                             
                st.session_state.boot_mode = "running"
                st.balloons()
                st.rerun()
    
    if not st.session_state.party:
        st.caption("💡 Tip: You need at least one party member to begin a session.")

    st.stop() 

# ---------------- Running Session ----------------

# Refresh class features for all party members (ensures level-based features are applied)
for _pc in st.session_state.get("party", []):
    add_level1_class_resources_and_actions(_pc)

# Run state validation and show warnings if any issues found
_validation_warnings = debug_validate_state()
if _validation_warnings:
    with st.expander("⚠️ Schema Validation Warnings", expanded=False):
        for w in _validation_warnings:
            st.warning(w)

# ========== TOP HEADER BAR ==========
st.markdown(f"# ⚔️ Session: {st.session_state.session_id}")

# Combat status indicator
if st.session_state.in_combat:
    ent = current_turn()
    if ent:
        st.success(f"🎯 **Combat Active** — Round {st.session_state.combat_round} | Turn: **{ent['name']}** ({ent['kind']})")
    else:
        st.warning("⚠️ Combat active but no valid turn entry")
else:
    st.info("🕊️ **Exploration Mode** — Not in combat")

st.divider()

# ========== MAIN LAYOUT: LEFT (Party+Enemies) | CENTER (Map) | RIGHT (Tracker+Log) ==========
left_col, mid_col, tracker_col, roller_col = st.columns([1.15, 2.7, 1.35, 1.35], gap="small")

# ===== LEFT COLUMN: Party + Enemies =====
with left_col:
    # ========== PARTY SECTION ==========
    st.markdown("### 👥 Party")
    with st.container(height=320, border=False):
        if not st.session_state.party:
            st.info("🧙 No party members yet. Go to **Setup** to add characters.")
        else:
            for i, c in enumerate(st.session_state.party):
                box = st.container(border=True)
                t1, t2, t3, t4, t5 = box.columns([3, 2, 2, 2, 2])

                with t1:
                    st.markdown(f"**{c.get('name','')}**")
                with t2:
                    c["ac"] = int(
                        st.number_input(
                            "AC", 0, 40, int(c.get("ac", 10)), key=f"run_p_ac_{i}"
                        )
                    )
                with t3:
                    c["hp"] = int(
                        st.number_input(
                            "HP", 0, 500, int(c.get("hp", 10)), key=f"run_p_hp_{i}"
                        )
                    )
                with t4:
                    # Position band dropdown (only during combat)
                    if st.session_state.in_combat:
                        current_band = ensure_position_band(c)
                        band_idx = POSITION_BANDS.index(current_band) if current_band in POSITION_BANDS else 1
                        new_band = st.selectbox(
                            "Pos",
                            POSITION_BANDS,
                            index=band_idx,
                            key=f"run_p_band_{i}",
                            format_func=lambda b: get_band_display(b)
                        )
                        c["position_band"] = new_band
                    else:
                        st.caption("—")
                with t5:
                    if st.button("Remove", key=f"run_p_rm_{i}"):
                        del st.session_state.party[i]
                        st.rerun()

                # Is this the active turn PC?
                is_active_pc = False
                if st.session_state.in_combat:
                    ent = current_turn()
                    if ent and ent.get("kind") == "party" and ent.get("idx") == i:
                        is_active_pc = True

                # --- Attacks panel for this party member ---
                with box.expander("Attacks"):
                    attacks = c.get("attacks") or []
                    if not attacks:
                        st.caption("No attacks listed.")
                    else:
                        for a in attacks:
                            # Use helper functions for consistent field access
                            name = a.get("name", "Attack")
                            to_hit = get_attack_to_hit(a)
                            dmg = get_attack_damage(a)
                            dmg_type = get_attack_damage_type(a)
                            if dmg_type:
                                st.write(f"{name}: +{to_hit} to hit, {dmg} {dmg_type}")
                            else:
                                st.write(f"{name}: +{to_hit} to hit, {dmg}")

                    if st.session_state.in_combat and not is_active_pc:
                        st.caption("Waiting for this character's turn.")

                # --- Conditions panel for this party member ---
                with box.expander("Conditions"):
                    conditions = ensure_conditions(c)
                    
                    if not conditions:
                        st.caption("No active conditions.")
                    else:
                        for ci, cond in enumerate(conditions):
                            cond_col1, cond_col2 = st.columns([4, 1])
                            with cond_col1:
                                st.write(get_condition_display(cond))
                            with cond_col2:
                                if st.button("✖", key=f"rm_cond_p_{i}_{ci}"):
                                    conditions.pop(ci)
                                    st.rerun()
                    
                    # Add condition form
                    st.markdown("**Add Condition**")
                    srd_cond_names = get_srd_condition_names()
                    cond_options = srd_cond_names + ["(Custom)"]
                    
                    add_cond_col1, add_cond_col2 = st.columns([2, 1])
                    with add_cond_col1:
                        selected_cond = st.selectbox(
                            "Condition",
                            cond_options,
                            key=f"add_cond_sel_p_{i}",
                            label_visibility="collapsed"
                        )
                    with add_cond_col2:
                        cond_duration = st.number_input(
                            "Rounds",
                            min_value=0,
                            value=0,
                            key=f"add_cond_dur_p_{i}",
                            help="0 = indefinite"
                        )
                    
                    if selected_cond == "(Custom)":
                        custom_cond_name = st.text_input(
                            "Custom Condition Name",
                            key=f"add_cond_custom_p_{i}"
                        )
                    else:
                        custom_cond_name = None
                    
                    if st.button("Add Condition", key=f"add_cond_btn_p_{i}"):
                        cond_name = custom_cond_name if selected_cond == "(Custom)" else selected_cond
                        if cond_name:
                            dur = cond_duration if cond_duration > 0 else None
                            add_condition(c, cond_name, duration_rounds=dur)
                            st.toast(f"Added {cond_name} to {c.get('name', 'character')}")
                            st.rerun()
                        else:
                            st.warning("Please enter a condition name.")

                # --- Actions & Resources ---
                with box.expander("Actions & Resources"):
                    resources = c.get("resources", {}) or {}
                    if resources:
                        st.markdown("**Resources**")
                        for rname, rdata in resources.items():
                            rc1, rc2, rc3 = st.columns([3, 2, 2])
                            current = int(rdata.get("current", 0))
                            max_val = int(rdata.get("max", 0))

                            with rc1:
                                st.markdown(f"{rname}: **{current} / {max_val}**")
                            with rc2:
                                if st.button(
                                    f"Use {rname}", key=f"use_res_{i}_{rname}"
                                ):
                                    if current > 0:
                                        current -= 1
                                        st.session_state.party[i].setdefault(
                                            "resources", {}
                                        )[rname]["current"] = current
                                        st.toast(
                                            f"{c.get('name','')} uses {rname}! "
                                            f"({current}/{max_val} left)"
                                        )
                                    else:
                                        st.warning(
                                            f"{c.get('name','')} has no {rname} uses left."
                                        )
                            with rc3:
                                if st.button(
                                    "Reset", key=f"reset_res_{i}_{rname}"
                                ):
                                    st.session_state.party[i].setdefault(
                                        "resources", {}
                                    )[rname]["current"] = max_val
                                    st.toast(
                                        f"{rname} reset to full for {c.get('name','')}."
                                    )

                    actions = c.get("actions", []) or []
                    if actions:
                        st.markdown("**Actions**")
                        for action_idx, a in enumerate(actions):
                            action_name = a.get('name', 'Unnamed')
                            action_resource = a.get("resource")
                            
                            # Check if this is a Marshal maneuver (needs targeting)
                            is_marshal_maneuver = action_name.startswith("Marshal:")
                            
                            action_col1, action_col2 = st.columns([4, 1])
                            
                            with action_col1:
                                line = f"**{action_name}**"
                                if action_resource:
                                    line += f" _(uses {action_resource})_"
                                st.markdown(line)
                                if a.get("description"):
                                    st.caption(a["description"])
                            
                            with action_col2:
                                # Add Use button for usable actions
                                if is_marshal_maneuver or action_resource:
                                    can_use = True
                                    if action_resource:
                                        res_data = c.get("resources", {}).get(action_resource, {})
                                        can_use = res_data.get("current", 0) > 0
                                    
                                    if st.button("Use", key=f"use_action_{i}_{action_idx}", disabled=not can_use):
                                        # Handle Marshal maneuvers with targeting
                                        if is_marshal_maneuver:
                                            st.session_state[f"marshal_maneuver_active_{i}"] = action_name
                                            st.rerun()
                                        else:
                                            # Just consume the resource
                                            if action_resource:
                                                c.setdefault("resources", {}).setdefault(action_resource, {})["current"] -= 1
                                                st.toast(f"{c.get('name', '')} uses {action_name}!")
                                                st.rerun()
                            
                            # Marshal maneuver targeting UI
                            if st.session_state.get(f"marshal_maneuver_active_{i}") == action_name:
                                with st.container(border=True):
                                    st.markdown(f"**🎯 Target Selection for {action_name}**")
                                    
                                    # Get allies in range (all party members for now)
                                    aura_range = c.get("aura_range", 30)
                                    allies = [p.get("name", f"Ally {j}") for j, p in enumerate(st.session_state.get("party", [])) if j != i]
                                    
                                    maneuver_key = action_name.replace("Marshal: ", "")
                                    maneuver_data = MARSHAL_MANEUVERS.get(maneuver_key, {})
                                    
                                    # Different targeting based on maneuver type
                                    if "Allies" in maneuver_data.get("description", "") or "allies" in maneuver_data.get("description", "").lower():
                                        # Affects all allies - no selection needed
                                        st.info(f"This affects all allies within {aura_range} ft.")
                                        target_allies = allies
                                    else:
                                        # Single target selection
                                        target_allies = st.multiselect(
                                            "Select target(s):",
                                            allies,
                                            key=f"marshal_targets_{i}_{action_idx}"
                                        )
                                    
                                    col_apply, col_cancel = st.columns(2)
                                    with col_apply:
                                        if st.button("✅ Apply", key=f"apply_marshal_{i}_{action_idx}"):
                                            # Consume Martial Die
                                            c.setdefault("resources", {}).setdefault("Martial Dice", {})["current"] = max(0, c.get("resources", {}).get("Martial Dice", {}).get("current", 0) - 1)
                                            
                                            # Roll the martial die
                                            die_size = c.get("marshal_die_size", "d6")
                                            die_value = int(die_size[1:])
                                            roll = random.randint(1, die_value)
                                            
                                            # Apply effect based on maneuver
                                            effect_msg = f"{c.get('name', '')} uses {action_name}! Rolled {roll} on {die_size}."
                                            
                                            if "temp HP" in maneuver_data.get("description", ""):
                                                cha_mod = (c.get("abilities", {}).get("CHA", 10) - 10) // 2
                                                temp_hp = cha_mod + roll
                                                effect_msg += f" Allies gain {temp_hp} temp HP."
                                                # Apply temp HP to targets
                                                for ally_name in target_allies:
                                                    for p in st.session_state.get("party", []):
                                                        if p.get("name") == ally_name:
                                                            p["temp_hp"] = p.get("temp_hp", 0) + temp_hp
                                            
                                            elif "move" in maneuver_data.get("description", "").lower():
                                                effect_msg += f" Allies can move up to 10 ft without provoking."
                                            
                                            elif "AC" in maneuver_data.get("description", ""):
                                                effect_msg += f" Target gains +{roll} AC until next turn."
                                            
                                            st.toast(effect_msg)
                                            del st.session_state[f"marshal_maneuver_active_{i}"]
                                            st.rerun()
                                    
                                    with col_cancel:
                                        if st.button("❌ Cancel", key=f"cancel_marshal_{i}_{action_idx}"):
                                            del st.session_state[f"marshal_maneuver_active_{i}"]
                                            st.rerun()

                # --- XP & Leveling ---
                with box.expander("📈 XP & Leveling"):
                    # Migrate character to ensure XP and multiclass fields exist
                    migrate_character_xp(c)
                    migrate_to_multiclass(c)
                    
                    xp_info = get_xp_progress(c)
                    current_xp = xp_info["current_xp"]
                    current_level = get_total_level(c)
                    char_classes = get_classes(c)
                    class_summary = get_class_summary(c)
                    
                    # ========== CHARACTER SHEET SUMMARY ==========
                    st.markdown("#### 📋 Character Sheet")
                    
                    # Main stats row
                    stat_col1, stat_col2, stat_col3 = st.columns(3)
                    with stat_col1:
                        st.metric("Total Level", current_level)
                    with stat_col2:
                        st.metric("XP", f"{current_xp:,}")
                    with stat_col3:
                        st.metric("BAB", f"+{c.get('bab', 0)}")
                    
                    # Class breakdown
                    st.markdown(f"**Classes:** {class_summary}")
                    if len(char_classes) > 1:
                        for cls in char_classes:
                            cls_id = cls.get('class_id', '?')
                            cls_lvl = cls.get('level', 0)
                            hit_die = get_hit_die_for_class(cls_id)
                            st.caption(f"  • {cls_id} {cls_lvl} (d{hit_die} hit die)")
                    
                    # XP Progress bar
                    if not xp_info["at_max_level"]:
                        st.progress(
                            xp_info["progress_pct"] / 100.0,
                            text=f"{xp_info['xp_needed']:,} XP needed for level {xp_info['next_level']}"
                        )
                    else:
                        st.success("🏆 Maximum Level Reached!")
                    
                    # ========== LEVEL UP AVAILABLE INDICATOR ==========
                    if c.get("level_up_pending", False):
                        st.markdown("---")
                        st.markdown("### ⬆️ Level Up Available!")
                        st.info(f"**{c.get('name', 'Character')}** has enough XP to reach level {current_level + 1}!")
                        
                        # Initialize level up wizard state
                        wizard_key = f"lvlup_wizard_{i}"
                        if wizard_key not in st.session_state:
                            st.session_state[wizard_key] = {"step": 1, "selected_class": None, "hp_method": None}
                        
                        wizard_state = st.session_state[wizard_key]
                        
                        # Get available classes
                        all_class_names = [cls.get("name", "") for cls in load_srd_classes()]
                        available_classes = get_available_classes_for_multiclass(c, all_class_names)
                        
                        # Separate existing and new classes
                        existing_options = []
                        new_class_options = []
                        
                        for cls in available_classes:
                            cls_id = cls["class_id"]
                            if not cls_id:
                                continue
                            current_cls_level = cls["current_level"]
                            
                            if current_cls_level > 0:
                                existing_options.append({
                                    "id": cls_id,
                                    "label": f"📈 {cls_id} (Level {current_cls_level} → {current_cls_level + 1})",
                                    "new": False,
                                    "level": current_cls_level
                                })
                            elif cls["can_add"]:
                                new_class_options.append({
                                    "id": cls_id,
                                    "label": f"✨ {cls_id} (NEW - Multiclass into Level 1)",
                                    "new": True,
                                    "level": 0,
                                    "reason": cls["reason"]
                                })
                        
                        # ===== STEP 1: Choose Class =====
                        st.markdown("**Step 1: Choose Class to Level**")
                        
                        # Build combined options list
                        all_options = []
                        option_labels = []
                        
                        if existing_options:
                            st.caption("Continue existing class:")
                            for opt in existing_options:
                                all_options.append(opt)
                                option_labels.append(opt["label"])
                        
                        if new_class_options:
                            if existing_options:
                                option_labels.append("─── Multiclass Options ───")
                                all_options.append(None)  # Separator
                            for opt in new_class_options:
                                all_options.append(opt)
                                option_labels.append(opt["label"])
                        
                        if option_labels:
                            selected_idx = st.selectbox(
                                "Select class",
                                range(len(option_labels)),
                                format_func=lambda x: option_labels[x],
                                key=f"lvlup_class_select_{i}",
                                label_visibility="collapsed"
                            )
                            
                            selected_option = all_options[selected_idx] if selected_idx < len(all_options) else None
                            
                            # Skip separator
                            if selected_option is None:
                                st.warning("Please select a valid class option")
                            else:
                                selected_class = selected_option["id"]
                                is_new_class = selected_option["new"]
                                new_class_level = selected_option["level"] + 1
                                
                                # Show class info
                                hit_die = get_hit_die_for_class(selected_class)
                                con_mod = (c.get("abilities", {}).get("CON", 10) - 10) // 2
                                avg_hp = (hit_die // 2) + 1 + con_mod
                                
                                st.markdown("---")
                                st.markdown(f"**Step 2: HP Increase for {selected_class} Level {new_class_level}**")
                                
                                info_col1, info_col2 = st.columns(2)
                                with info_col1:
                                    st.caption(f"Hit Die: d{hit_die}")
                                    st.caption(f"CON Modifier: {'+' if con_mod >= 0 else ''}{con_mod}")
                                with info_col2:
                                    st.caption(f"Average HP: {avg_hp}")
                                    st.caption(f"Roll Range: {max(1, 1 + con_mod)} - {hit_die + con_mod}")
                                
                                # ===== STEP 2: HP Method =====
                                hp_method = st.radio(
                                    "Choose HP method:",
                                    ["average", "roll"],
                                    format_func=lambda x: f"📊 Take Average ({avg_hp} HP)" if x == "average" else f"🎲 Roll d{hit_die}",
                                    key=f"lvlup_hp_method_{i}",
                                    horizontal=True
                                )
                                
                                # ===== STEP 3: Preview Features =====
                                st.markdown("---")
                                st.markdown(f"**Step 3: Features at {selected_class} Level {new_class_level}**")
                                
                                # Look up class features for this level
                                srd_classes = load_srd_classes()
                                class_data = next((cls for cls in srd_classes if cls.get("name", "").lower() == selected_class.lower()), None)
                                
                                features_at_level = []
                                level_has_asi = False
                                if class_data:
                                    levels_data = class_data.get("levels", {})
                                    level_info = levels_data.get(str(new_class_level), {})
                                    features_at_level = level_info.get("features_at_level", [])
                                    level_has_asi = bool(level_info.get("asi_or_feat"))
                                    
                                    if features_at_level:
                                        for feat in features_at_level:
                                            if isinstance(feat, str):
                                                st.markdown(f"  • **{feat}**")
                                            elif isinstance(feat, dict):
                                                st.markdown(f"  • **{feat.get('name', 'Feature')}**")
                                                if feat.get("description"):
                                                    st.caption(f"    {feat.get('description')}")
                                    else:
                                        st.caption("No new features at this level.")
                                    
                                    # Show ASI/Feat if applicable
                                    if level_has_asi:
                                        st.markdown(f"  • **Ability Score Improvement or Feat**")
                                else:
                                    st.caption("Class data not found.")
                                
                                # If multiclassing, show proficiencies gained
                                if is_new_class:
                                    st.markdown("---")
                                    st.markdown(f"**Multiclass Proficiencies (from {selected_class}):**")
                                    mc_profs = get_multiclass_proficiencies(selected_class)
                                    
                                    if mc_profs.get("armor"):
                                        st.caption(f"  Armor: {', '.join(mc_profs['armor'])}")
                                    if mc_profs.get("weapons"):
                                        st.caption(f"  Weapons: {', '.join(mc_profs['weapons'])}")
                                    if mc_profs.get("skills", 0) > 0:
                                        st.caption(f"  Skills: Choose {mc_profs['skills']} skill(s)")
                                    if not any([mc_profs.get("armor"), mc_profs.get("weapons"), mc_profs.get("skills", 0)]):
                                        st.caption("  No additional proficiencies.")
                                
                                # ===== STEP 4: Apply Level Up =====
                                st.markdown("---")
                                st.markdown("**Step 4: Apply Level Up**")
                                
                                # Calculate skill points
                                from src.leveling import get_skill_points_for_level, is_asi_level, get_new_spells_at_level, is_caster_class
                                int_mod = (c.get("abilities", {}).get("INT", 10) - 10) // 2
                                skill_points = get_skill_points_for_level(selected_class, int_mod)
                                
                                # Barbarian Illiteracy bonus: +1 skill point while illiterate
                                if selected_class.lower() == "barbarian" and not c.get("is_literate", False):
                                    skill_points += 1
                                
                                # Check for spells
                                spell_info = get_new_spells_at_level(selected_class, selected_option["level"], new_class_level)
                                
                                # Summary of what will be gained
                                st.caption(f"**Summary of gains:**")
                                st.caption(f"  • HP: +{avg_hp if hp_method == 'average' else f'1d{hit_die}+{con_mod}'}")
                                st.caption(f"  • Skill Points: +{skill_points}")
                                
                                if spell_info["new_cantrips"] > 0:
                                    st.caption(f"  • New Cantrips: +{spell_info['new_cantrips']}")
                                if spell_info["new_spells"] > 0:
                                    st.caption(f"  • New Spells: +{spell_info['new_spells']} (max level {spell_info['max_spell_level']})")
                                if level_has_asi or is_asi_level(selected_class, new_class_level):
                                    st.caption(f"  • ASI/Feat: +1 choice")
                                
                                apply_col1, apply_col2 = st.columns([3, 1])
                                with apply_col1:
                                    st.caption(f"This will increase {c.get('name', 'Character')}'s {selected_class} to level {new_class_level}.")
                                with apply_col2:
                                    if st.button("✅ Apply", key=f"lvlup_apply_{i}", type="primary", use_container_width=True):
                                        roll_hp = (hp_method == "roll")
                                        result = level_up_character_multiclass(c, selected_class, roll_hp=roll_hp)
                                        
                                        if result["success"]:
                                            # Apply class features
                                            from src.leveling import apply_class_features
                                            if features_at_level:
                                                apply_class_features(c, features_at_level)
                                            
                                            # Clear wizard state
                                            if wizard_key in st.session_state:
                                                del st.session_state[wizard_key]
                                            
                                            # Show success message with pending choices
                                            from src.leveling import has_pending_choices, get_pending_summary
                                            pending = has_pending_choices(c)
                                            msg = f"🎉 {c.get('name', 'Character')} is now {get_class_summary(c)}! +{result['hp_gained']} HP"
                                            if pending["any"]:
                                                msg += f" — {get_pending_summary(c)}"
                                            st.toast(msg)
                                            
                                            if roll_hp:
                                                st.balloons()
                                            
                                            st.rerun()
                                        else:
                                            st.error(result.get("message", "Level up failed"))
                        else:
                            st.error("No classes available for level up. Check multiclass prerequisites.")
                    
                    # ========== PENDING CHOICES (Skill Points, Spells, ASI/Feat) ==========
                    from src.leveling import has_pending_choices, apply_skill_ranks, apply_spell_selection, apply_asi, apply_feat
                    pending = has_pending_choices(c)
                    
                    if pending["any"]:
                        st.markdown("---")
                        st.markdown("### 📋 Pending Level-Up Choices")
                        
                        # ===== BARBARIAN ILLITERACY =====
                        # Barbarians can spend 2 skill points to become literate
                        if c.get("class", "").lower() == "barbarian" and not c.get("is_literate", False):
                            skill_points_for_literacy = c.get("pending_skill_points", 0)
                            if skill_points_for_literacy >= 2:
                                with st.expander("📖 Learn to Read & Write (Barbarian)", expanded=False):
                                    st.info(
                                        "As a Barbarian, you are illiterate by default. "
                                        "You can spend **2 skill points** to learn to read and write. "
                                        "While illiterate, you gain +1 skill point per level."
                                    )
                                    if st.button("Spend 2 Skill Points to Become Literate", key=f"literacy_{i}"):
                                        c["is_literate"] = True
                                        c["pending_skill_points"] = skill_points_for_literacy - 2
                                        # Remove the bonus skill point feature
                                        c.pop("illiteracy_skill_bonus", None)
                                        # Update features
                                        features = c.get("features", [])
                                        # Remove old illiteracy feature and add new one
                                        c["features"] = [f for f in features if "Illiteracy" not in f]
                                        c["features"].append("Illiteracy (Removed): You spent 2 skill points to learn to read and write.")
                                        st.toast("📖 You have learned to read and write!")
                                        st.rerun()
                        
                        # ===== SKILL POINTS =====
                        if pending["skill_points"]:
                            with st.expander(f"🎯 Skill Points ({c.get('pending_skill_points', 0)} to allocate)", expanded=True):
                                skill_points_available = c.get("pending_skill_points", 0)
                                
                                # Get class skills
                                srd_classes = load_srd_classes()
                                char_classes = c.get("classes", [{"class_id": c.get("class", "fighter"), "level": c.get("level", 1)}])
                                class_skills = set()
                                for cc in char_classes:
                                    cls_data = next((cls for cls in srd_classes if cls.get("name", "").lower() == cc.get("class_id", "").lower()), None)
                                    if cls_data:
                                        class_skills.update(cls_data.get("skill_list", []))
                                
                                # All skills from SRD
                                all_skills = [s.get("name", "") for s in load_srd_skills()]
                                
                                # Current skill ranks
                                current_skills = c.get("skills", {})
                                max_ranks = c.get("level", 1) + 3  # Max ranks = level + 3
                                
                                # Skill allocation UI
                                skill_alloc_key = f"skill_alloc_{i}"
                                if skill_alloc_key not in st.session_state:
                                    st.session_state[skill_alloc_key] = {}
                                
                                alloc = st.session_state[skill_alloc_key]
                                total_allocated = sum(alloc.values())
                                remaining = skill_points_available - total_allocated
                                
                                st.caption(f"Points remaining: **{remaining}** / {skill_points_available}")
                                st.caption(f"Max ranks per skill: {max_ranks}")
                                
                                # Show class skills first, then others
                                st.markdown("**Class Skills:**")
                                skill_cols = st.columns(3)
                                col_idx = 0
                                for skill in sorted(class_skills):
                                    if skill in all_skills:
                                        current = current_skills.get(skill, 0)
                                        adding = alloc.get(skill, 0)
                                        with skill_cols[col_idx % 3]:
                                            new_val = st.number_input(
                                                f"{skill} ({current}+)",
                                                min_value=0,
                                                max_value=min(remaining + adding, max_ranks - current),
                                                value=adding,
                                                key=f"skill_{i}_{skill}",
                                                help=f"Current: {current}, Max: {max_ranks}"
                                            )
                                            alloc[skill] = new_val
                                        col_idx += 1
                                
                                # Cross-class skills (cost 2 points per rank)
                                with st.expander("Cross-Class Skills (2 points per rank)"):
                                    cross_class = [s for s in all_skills if s not in class_skills]
                                    skill_cols2 = st.columns(3)
                                    col_idx2 = 0
                                    for skill in sorted(cross_class):
                                        current = current_skills.get(skill, 0)
                                        adding = alloc.get(skill, 0)
                                        with skill_cols2[col_idx2 % 3]:
                                            new_val = st.number_input(
                                                f"{skill} ({current}+)",
                                                min_value=0,
                                                max_value=min((remaining + adding) // 2, (max_ranks // 2) - current),
                                                value=adding,
                                                key=f"skill_cc_{i}_{skill}",
                                                help=f"Current: {current}, Max: {max_ranks // 2} (cross-class)"
                                            )
                                            alloc[skill] = new_val * 2  # Double cost for cross-class
                                        col_idx2 += 1
                                
                                # Recalculate total
                                total_allocated = sum(alloc.values())
                                remaining = skill_points_available - total_allocated
                                
                                if st.button("Apply Skill Points", key=f"apply_skills_{i}", disabled=total_allocated == 0):
                                    # Convert allocation to actual ranks (cross-class already doubled in cost)
                                    actual_ranks = {}
                                    for skill, cost in alloc.items():
                                        if cost > 0:
                                            if skill in class_skills:
                                                actual_ranks[skill] = cost
                                            else:
                                                actual_ranks[skill] = cost // 2  # Cross-class gives half ranks
                                    
                                    result = apply_skill_ranks(c, actual_ranks)
                                    if result["success"]:
                                        st.session_state[skill_alloc_key] = {}
                                        st.toast(f"✅ Allocated {result['allocated']} skill points!")
                                        st.rerun()
                                    else:
                                        st.error(result["message"])
                        
                        # ===== CANTRIPS =====
                        if pending["cantrips"]:
                            with st.expander(f"✨ Cantrips ({c.get('pending_cantrips', 0)} to choose)", expanded=True):
                                cantrips_available = c.get("pending_cantrips", 0)
                                
                                # Get class spell list
                                char_classes = c.get("classes", [{"class_id": c.get("class", "wizard"), "level": 1}])
                                spell_classes = [cc.get("class_id", "").lower() for cc in char_classes]
                                
                                # Load all spells
                                all_spells = load_srd_spells()
                                cantrips = [s for s in all_spells if s.get("level", 0) == 0]
                                
                                # Filter to class cantrips
                                class_cantrips = []
                                for cantrip in cantrips:
                                    spell_classes_list = [sc.lower() for sc in cantrip.get("classes", [])]
                                    if any(sc in spell_classes_list for sc in spell_classes):
                                        class_cantrips.append(cantrip.get("name", ""))
                                
                                # Already known cantrips
                                known_cantrips = c.get("spells", {}).get("cantrips", [])
                                available_cantrips = [ct for ct in class_cantrips if ct not in known_cantrips]
                                
                                if available_cantrips:
                                    selected_cantrips = st.multiselect(
                                        f"Choose {cantrips_available} cantrip(s):",
                                        available_cantrips,
                                        max_selections=cantrips_available,
                                        key=f"cantrip_select_{i}"
                                    )
                                    
                                    if st.button("Learn Cantrips", key=f"learn_cantrips_{i}", disabled=len(selected_cantrips) == 0):
                                        result = apply_spell_selection(c, "cantrip", selected_cantrips)
                                        if result["success"]:
                                            st.toast(f"✅ Learned {len(selected_cantrips)} cantrip(s)!")
                                            st.rerun()
                                        else:
                                            st.error(result["message"])
                                else:
                                    st.caption("No more cantrips available to learn.")
                        
                        # ===== SPELLS =====
                        if pending["spells"]:
                            with st.expander(f"📖 Spells ({c.get('pending_spells', 0)} to choose)", expanded=True):
                                spells_available = c.get("pending_spells", 0)
                                max_spell_level = c.get("max_spell_level", 1)
                                
                                # Get class spell list
                                char_classes = c.get("classes", [{"class_id": c.get("class", "wizard"), "level": 1}])
                                spell_classes = [cc.get("class_id", "").lower() for cc in char_classes]
                                
                                # Load all spells
                                all_spells = load_srd_spells()
                                
                                # Filter to class spells of appropriate level
                                class_spells = []
                                for spell in all_spells:
                                    spell_level = spell.get("level", 0)
                                    if spell_level > 0 and spell_level <= max_spell_level:
                                        spell_classes_list = [sc.lower() for sc in spell.get("classes", [])]
                                        if any(sc in spell_classes_list for sc in spell_classes):
                                            class_spells.append(spell.get("name", ""))
                                
                                # Already known spells
                                known_spells = c.get("spells", {}).get("known", [])
                                available_spells = [sp for sp in class_spells if sp not in known_spells]
                                
                                if available_spells:
                                    st.caption(f"Max spell level: {max_spell_level}")
                                    selected_spells = st.multiselect(
                                        f"Choose {spells_available} spell(s):",
                                        sorted(available_spells),
                                        max_selections=spells_available,
                                        key=f"spell_select_{i}"
                                    )
                                    
                                    if st.button("Learn Spells", key=f"learn_spells_{i}", disabled=len(selected_spells) == 0):
                                        result = apply_spell_selection(c, "spell", selected_spells)
                                        if result["success"]:
                                            st.toast(f"✅ Learned {len(selected_spells)} spell(s)!")
                                            st.rerun()
                                        else:
                                            st.error(result["message"])
                                else:
                                    st.caption("No more spells available to learn.")
                        
                        # ===== ASI / FEAT =====
                        if pending["asi_or_feat"]:
                            with st.expander(f"⬆️ Ability Score Improvement / Feat ({c.get('pending_asi', 0)} choice(s))", expanded=True):
                                asi_choice = st.radio(
                                    "Choose:",
                                    ["asi", "feat"],
                                    format_func=lambda x: "📊 Ability Score Improvement (+2 to one / +1 to two)" if x == "asi" else "🏅 Feat",
                                    key=f"asi_choice_{i}",
                                    horizontal=True
                                )
                                
                                if asi_choice == "asi":
                                    abilities = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
                                    current_abilities = c.get("abilities", {})
                                    
                                    asi_method = st.radio(
                                        "Method:",
                                        ["+2_one", "+1_two"],
                                        format_func=lambda x: "+2 to one ability" if x == "+2_one" else "+1 to two abilities",
                                        key=f"asi_method_{i}",
                                        horizontal=True
                                    )
                                    
                                    if asi_method == "+2_one":
                                        ability1 = st.selectbox(
                                            "Increase by +2:",
                                            abilities,
                                            format_func=lambda x: f"{x} ({current_abilities.get(x, 10)} → {min(20, current_abilities.get(x, 10) + 2)})",
                                            key=f"asi_ability1_{i}"
                                        )
                                        ability2 = None
                                    else:
                                        col1, col2 = st.columns(2)
                                        with col1:
                                            ability1 = st.selectbox(
                                                "First +1:",
                                                abilities,
                                                format_func=lambda x: f"{x} ({current_abilities.get(x, 10)} → {min(20, current_abilities.get(x, 10) + 1)})",
                                                key=f"asi_ability1_{i}"
                                            )
                                        with col2:
                                            ability2 = st.selectbox(
                                                "Second +1:",
                                                [a for a in abilities if a != ability1],
                                                format_func=lambda x: f"{x} ({current_abilities.get(x, 10)} → {min(20, current_abilities.get(x, 10) + 1)})",
                                                key=f"asi_ability2_{i}"
                                            )
                                    
                                    if st.button("Apply ASI", key=f"apply_asi_{i}"):
                                        result = apply_asi(c, ability1, ability2)
                                        if result["success"]:
                                            st.toast(f"✅ {result['message']}")
                                            st.rerun()
                                        else:
                                            st.error(result["message"])
                                
                                else:  # Feat
                                    # Load feats
                                    feats = load_srd_feats()
                                    feat_names = [f.get("name", "") for f in feats]
                                    current_feats = c.get("feats", [])
                                    
                                    # Filter feats - exclude ones already taken (except repeatable ones)
                                    repeatable_feats = ["Elemental Adept", "Weapon Focus", "Weapon Specialization", 
                                                    "Greater Weapon Focus", "Greater Weapon Specialization"]
                                    available_feats = [f for f in feat_names if f not in current_feats or f in repeatable_feats]
                                    
                                    # Also check prerequisites
                                    char_abilities = c.get("abilities", {})
                                    char_bab = c.get("bab", 0)
                                    char_feats = c.get("feats", [])
                                    
                                    def check_prereqs(feat_data):
                                        prereqs = feat_data.get("prerequisites", [])
                                        if not prereqs:
                                            return True
                                        for prereq in prereqs:
                                            if isinstance(prereq, dict):
                                                for key, val in prereq.items():
                                                    if key in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]:
                                                        if char_abilities.get(key, 10) < val:
                                                            return False
                                                    elif key == "BAB":
                                                        if char_bab < val:
                                                            return False
                                                    elif key == "feat":
                                                        if val not in char_feats:
                                                            return False
                                                    elif key == "spellcasting":
                                                        # Check if character has any spellcasting
                                                        has_spells = bool(c.get("spells", {}).get("known") or c.get("spells", {}).get("cantrips"))
                                                        if val and not has_spells:
                                                            return False
                                        return True
                                    
                                    # Filter by prerequisites
                                    valid_feats = []
                                    for fname in available_feats:
                                        fdata = next((f for f in feats if f.get("name") == fname), None)
                                        if fdata and check_prereqs(fdata):
                                            valid_feats.append(fname)
                                    
                                    if valid_feats:
                                        selected_feat = st.selectbox(
                                            "Choose a feat:",
                                            sorted(valid_feats),
                                            key=f"feat_select_{i}"
                                        )
                                        
                                        # Show feat description
                                        feat_data = next((f for f in feats if f.get("name") == selected_feat), None)
                                        if feat_data:
                                            st.caption(feat_data.get("description", "No description available."))
                                            
                                            # Show prerequisites if any
                                            prereqs = feat_data.get("prerequisites", [])
                                            if prereqs:
                                                prereq_strs = []
                                                for p in prereqs:
                                                    if isinstance(p, dict):
                                                        for k, v in p.items():
                                                            prereq_strs.append(f"{k} {v}")
                                                if prereq_strs:
                                                    st.caption(f"**Prerequisites:** {', '.join(prereq_strs)}")
                                            
                                            # Show effects
                                            effects = feat_data.get("effects", {})
                                            if effects:
                                                effect_strs = []
                                                if "initiative_bonus" in effects:
                                                    effect_strs.append(f"+{effects['initiative_bonus']} Initiative")
                                                if "speed_bonus" in effects:
                                                    effect_strs.append(f"+{effects['speed_bonus']} ft. Speed")
                                                if "hp_bonus_per_level" in effects:
                                                    effect_strs.append(f"+{effects['hp_bonus_per_level']} HP/level")
                                                if "ac_bonus" in effects:
                                                    effect_strs.append(f"+{effects['ac_bonus']} AC")
                                                if effect_strs:
                                                    st.caption(f"**Effects:** {', '.join(effect_strs)}")
                                            
                                            # Handle ability increase choice
                                            ability_choice = None
                                            ability_increase = feat_data.get("ability_increase", {})
                                            if ability_increase and "choice" in ability_increase:
                                                choices = ability_increase["choice"]
                                                amount = ability_increase.get("amount", 1)
                                                ability_choice = st.selectbox(
                                                    f"Choose ability to increase (+{amount}):",
                                                    choices,
                                                    format_func=lambda x: f"{x} ({char_abilities.get(x, 10)} → {min(20, char_abilities.get(x, 10) + amount)})",
                                                    key=f"feat_ability_choice_{i}"
                                                )
                                            elif ability_increase:
                                                # Show fixed ability increases
                                                fixed_increases = []
                                                for ab, amt in ability_increase.items():
                                                    if ab in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]:
                                                        fixed_increases.append(f"+{amt} {ab}")
                                                if fixed_increases:
                                                    st.caption(f"**Ability Increase:** {', '.join(fixed_increases)}")
                                        
                                        if st.button("Take Feat", key=f"take_feat_{i}"):
                                            result = apply_feat(c, selected_feat, feat_data, ability_choice=ability_choice)
                                            if result["success"]:
                                                st.toast(f"✅ {result['message']}")
                                                st.rerun()
                                            else:
                                                st.error(result["message"])
                                    else:
                                        st.caption("No feats available (prerequisites not met or all taken).")
                        
                        # ===== FIGHTING STYLE =====
                        if pending.get("fighting_style"):
                            with st.expander(f"⚔️ Fighting Style ({c.get('pending_fighting_style', 0)} to choose)", expanded=True):
                                from src.leveling import get_available_fighting_styles, apply_fighting_style
                                
                                feats = load_srd_feats()
                                available_styles = get_available_fighting_styles(c, feats)
                                
                                if available_styles:
                                    style_names = [s["name"] for s in available_styles]
                                    selected_style = st.selectbox(
                                        "Choose a Fighting Style:",
                                        sorted(style_names),
                                        key=f"fighting_style_select_{i}"
                                    )
                                    
                                    # Show description
                                    style_data = next((s for s in available_styles if s["name"] == selected_style), None)
                                    if style_data:
                                        st.caption(style_data.get("description", ""))
                                        
                                        # Show effects
                                        effects = style_data.get("effects", {})
                                        if effects:
                                            effect_strs = []
                                            if "ranged_attack_bonus" in effects:
                                                effect_strs.append(f"+{effects['ranged_attack_bonus']} ranged attack")
                                            if "armor_ac_bonus" in effects:
                                                effect_strs.append(f"+{effects['armor_ac_bonus']} AC (in armor)")
                                            if "one_handed_damage_bonus" in effects:
                                                effect_strs.append(f"+{effects['one_handed_damage_bonus']} damage (one-handed)")
                                            if "thrown_damage_bonus" in effects:
                                                effect_strs.append(f"+{effects['thrown_damage_bonus']} thrown damage")
                                            if effect_strs:
                                                st.caption(f"**Effects:** {', '.join(effect_strs)}")
                                    
                                    if st.button("Choose Fighting Style", key=f"apply_fighting_style_{i}"):
                                        result = apply_fighting_style(c, selected_style, style_data)
                                        if result["success"]:
                                            st.toast(f"✅ {result['message']}")
                                            st.rerun()
                                        else:
                                            st.error(result["message"])
                                else:
                                    st.caption("You already have all available fighting styles.")
                        
                        # ===== BONUS FEAT =====
                        if pending.get("bonus_feat"):
                            with st.expander(f"🎖️ Bonus Feat ({c.get('pending_bonus_feat', 0)} to choose)", expanded=True):
                                from src.leveling import get_available_bonus_feats, apply_bonus_feat, check_feat_prerequisites
                                
                                feats = load_srd_feats()
                                available_bonus = get_available_bonus_feats(c, feats)
                                
                                # Sort by whether prerequisites are met
                                available_bonus.sort(key=lambda x: (not x["meets_prerequisites"], x["feat"]["name"]))
                                
                                if available_bonus:
                                    # Show feats with prerequisites met first
                                    valid_feats = [f for f in available_bonus if f["meets_prerequisites"]]
                                    invalid_feats = [f for f in available_bonus if not f["meets_prerequisites"]]
                                    
                                    st.markdown("**Feats you qualify for:**")
                                    if valid_feats:
                                        feat_options = [f["feat"]["name"] for f in valid_feats]
                                        selected_feat = st.selectbox(
                                            "Choose a feat:",
                                            feat_options,
                                            key=f"bonus_feat_select_{i}"
                                        )
                                        
                                        # Show feat details
                                        feat_entry = next((f for f in valid_feats if f["feat"]["name"] == selected_feat), None)
                                        if feat_entry:
                                            feat_data = feat_entry["feat"]
                                            st.caption(feat_data.get("description", ""))
                                            
                                            # Show prerequisites
                                            prereqs = feat_data.get("prerequisites", [])
                                            if prereqs:
                                                prereq_strs = []
                                                for p in prereqs:
                                                    if isinstance(p, dict):
                                                        for k, v in p.items():
                                                            prereq_strs.append(f"{k} {v}")
                                                if prereq_strs:
                                                    st.caption(f"✅ **Prerequisites:** {', '.join(prereq_strs)}")
                                            
                                            # Handle ability choice if needed
                                            ability_choice = None
                                            ability_increase = feat_data.get("ability_increase", {})
                                            if ability_increase and "choice" in ability_increase:
                                                choices = ability_increase["choice"]
                                                amount = ability_increase.get("amount", 1)
                                                char_abilities = c.get("abilities", {})
                                                ability_choice = st.selectbox(
                                                    f"Choose ability to increase (+{amount}):",
                                                    choices,
                                                    format_func=lambda x: f"{x} ({char_abilities.get(x, 10)} → {min(20, char_abilities.get(x, 10) + amount)})",
                                                    key=f"bonus_feat_ability_{i}"
                                                )
                                            
                                            if st.button("Take Bonus Feat", key=f"apply_bonus_feat_{i}"):
                                                result = apply_bonus_feat(c, selected_feat, feat_data, ability_choice)
                                                if result["success"]:
                                                    st.toast(f"✅ {result['message']}")
                                                    st.rerun()
                                                else:
                                                    st.error(result["message"])
                                    else:
                                        st.caption("No feats available that you qualify for.")
                                    
                                    # Show unavailable feats
                                    if invalid_feats:
                                        with st.expander("Feats you don't qualify for"):
                                            for f in invalid_feats[:10]:  # Show first 10
                                                st.markdown(f"**{f['feat']['name']}** - Missing: {', '.join(f['unmet_prerequisites'])}")
                                else:
                                    st.caption("No bonus feats available.")
                        
                        # ===== WARLOCK INVOCATIONS =====
                        if pending.get("invocations"):
                            with st.expander(f"🌙 Eldritch Invocations ({c.get('pending_invocations', 0)} to choose)", expanded=True):
                                invocations_to_choose = c.get("pending_invocations", 0)
                                current_invocations = c.get("warlock_invocations", [])
                                char_level = c.get("level", 1)
                                pact_boon = c.get("warlock_pact_boon", "")
                                
                                # Get available invocations based on level and prerequisites
                                available_invocations = []
                                for inv_name, inv_data in WARLOCK_INVOCATIONS.items():
                                    # Skip if already known
                                    if inv_name in current_invocations:
                                        continue
                                    
                                    # Check level requirement
                                    if char_level < inv_data.get("level", 1):
                                        continue
                                    
                                    # Check prerequisites
                                    prereq = inv_data.get("prereq")
                                    if prereq:
                                        if "Eldritch Blast" in prereq:
                                            # Check if character has Eldritch Blast
                                            known_cantrips = c.get("spells", {}).get("cantrips", [])
                                            if "Eldritch Blast" not in known_cantrips and "Eldritch Blast" not in c.get("spells", []):
                                                continue
                                        if "Pact of the Blade" in prereq and pact_boon != "Blade":
                                            continue
                                        if "Pact of the Chain" in prereq and pact_boon != "Chain":
                                            continue
                                        if "Pact of the Tome" in prereq and pact_boon != "Tome":
                                            continue
                                    
                                    available_invocations.append((inv_name, inv_data))
                                
                                if available_invocations:
                                    inv_names = [inv[0] for inv in available_invocations]
                                    
                                    selected_invocations = st.multiselect(
                                        f"Choose {invocations_to_choose} invocation(s):",
                                        inv_names,
                                        max_selections=invocations_to_choose,
                                        key=f"invocation_select_{i}"
                                    )
                                    
                                    # Show descriptions for selected
                                    if selected_invocations:
                                        for inv_name in selected_invocations:
                                            inv_data = WARLOCK_INVOCATIONS.get(inv_name, {})
                                            prereq_text = f" *(Requires: {inv_data.get('prereq')})*" if inv_data.get("prereq") else ""
                                            st.caption(f"**{inv_name}**: {inv_data.get('description', '')}{prereq_text}")
                                    
                                    if st.button("Learn Invocations", key=f"learn_invocations_{i}", 
                                            disabled=len(selected_invocations) != invocations_to_choose):
                                        # Apply invocations
                                        current_invocations.extend(selected_invocations)
                                        c["warlock_invocations"] = current_invocations
                                        c["pending_invocations"] = 0
                                        
                                        # Re-apply invocation effects
                                        add_level1_class_resources_and_actions(c)
                                        
                                        st.toast(f"✅ Learned {len(selected_invocations)} invocation(s)!")
                                        st.rerun()
                                else:
                                    st.caption("No invocations available (check prerequisites or level).")
                        
                        # ===== PACT BOON =====
                        if pending.get("pact_boon"):
                            with st.expander("📜 Pact Boon (Level 3)", expanded=True):
                                pact_options = ["Blade", "Chain", "Tome", "Talisman"]
                                
                                selected_pact = st.radio(
                                    "Choose your Pact Boon:",
                                    pact_options,
                                    format_func=lambda x: {
                                        "Blade": "⚔️ Pact of the Blade - Create magical pact weapons",
                                        "Chain": "🐉 Pact of the Chain - Enhanced familiar (imp, pseudodragon, etc.)",
                                        "Tome": "📖 Pact of the Tome - Book with 3 cantrips from any class",
                                        "Talisman": "🔮 Pact of the Talisman - Amulet that aids ability checks"
                                    }.get(x, x),
                                    key=f"pact_boon_select_{i}",
                                    horizontal=False
                                )
                                
                                if st.button("Choose Pact Boon", key=f"apply_pact_boon_{i}"):
                                    c["warlock_pact_boon"] = selected_pact
                                    c["pending_pact_boon"] = False
                                    
                                    # Apply pact boon effects
                                    add_level1_class_resources_and_actions(c)
                                    
                                    st.toast(f"✅ Chose Pact of the {selected_pact}!")
                                    st.rerun()
                        
                        # ===== FIGHTER MANEUVERS =====
                        if pending.get("maneuvers"):
                            with st.expander(f"⚔️ Combat Maneuvers ({c.get('pending_maneuvers', 0)} to choose)", expanded=True):
                                maneuvers_to_choose = c.get("pending_maneuvers", 0)
                                current_maneuvers = c.get("fighter_maneuvers", [])
                                
                                # Get available maneuvers
                                available_maneuvers = []
                                for maneuver_name, maneuver_data in FIGHTER_MANEUVERS.items():
                                    if maneuver_name not in current_maneuvers:
                                        available_maneuvers.append((maneuver_name, maneuver_data))
                                
                                if available_maneuvers:
                                    maneuver_names = [m[0] for m in available_maneuvers]
                                    
                                    selected_maneuvers = st.multiselect(
                                        f"Choose {maneuvers_to_choose} maneuver(s):",
                                        maneuver_names,
                                        max_selections=maneuvers_to_choose,
                                        key=f"maneuver_select_{i}"
                                    )
                                    
                                    # Show descriptions for selected
                                    if selected_maneuvers:
                                        st.markdown("**Selected Maneuvers:**")
                                        for m_name in selected_maneuvers:
                                            m_data = FIGHTER_MANEUVERS.get(m_name, {})
                                            st.caption(f"• **{m_name}** ({m_data.get('type', 'attack')}): {m_data.get('description', '')}")
                                    
                                    if st.button("Learn Maneuvers", key=f"learn_maneuvers_{i}", 
                                            disabled=len(selected_maneuvers) != maneuvers_to_choose):
                                        # Apply maneuvers
                                        current_maneuvers.extend(selected_maneuvers)
                                        c["fighter_maneuvers"] = current_maneuvers
                                        c["pending_maneuvers"] = 0
                                        
                                        # Re-apply maneuver actions
                                        add_level1_class_resources_and_actions(c)
                                        
                                        st.toast(f"✅ Learned {len(selected_maneuvers)} maneuver(s)!")
                                        st.rerun()
                                else:
                                    st.caption("All maneuvers already learned.")
                        
                        # ===== SORCERER METAMAGIC =====
                        if pending.get("metamagic"):
                            with st.expander(f"✨ Metamagic ({c.get('pending_metamagic', 0)} to choose)", expanded=True):
                                metamagic_to_choose = c.get("pending_metamagic", 0)
                                current_metamagic = c.get("sorcerer_metamagic", [])
                                
                                # Get available metamagic
                                available_metamagic = []
                                for meta_name, meta_data in SORCERER_METAMAGIC.items():
                                    if meta_name not in current_metamagic:
                                        available_metamagic.append((meta_name, meta_data))
                                
                                if available_metamagic:
                                    meta_names = [m[0] for m in available_metamagic]
                                    
                                    selected_metamagic = st.multiselect(
                                        f"Choose {metamagic_to_choose} metamagic option(s):",
                                        meta_names,
                                        max_selections=metamagic_to_choose,
                                        key=f"metamagic_select_{i}"
                                    )
                                    
                                    # Show descriptions for selected
                                    if selected_metamagic:
                                        st.markdown("**Selected Metamagic:**")
                                        for m_name in selected_metamagic:
                                            m_data = SORCERER_METAMAGIC.get(m_name, {})
                                            cost = m_data.get("cost", 1)
                                            cost_str = f"{cost} SP" if isinstance(cost, int) else "Spell level SP"
                                            st.caption(f"• **{m_name}** ({cost_str}): {m_data.get('description', '')}")
                                    
                                    if st.button("Learn Metamagic", key=f"learn_metamagic_{i}", 
                                            disabled=len(selected_metamagic) != metamagic_to_choose):
                                        # Apply metamagic
                                        current_metamagic.extend(selected_metamagic)
                                        c["sorcerer_metamagic"] = current_metamagic
                                        c["pending_metamagic"] = 0
                                        
                                        # Re-apply metamagic actions
                                        add_level1_class_resources_and_actions(c)
                                        
                                        st.toast(f"✅ Learned {len(selected_metamagic)} metamagic option(s)!")
                                        st.rerun()
                                else:
                                    st.caption("All metamagic options already learned.")
                        
                        # ===== WIZARD SCHOOL =====
                        if pending.get("wizard_school"):
                            with st.expander(f"📚 Arcane School (Choose 1)", expanded=True):
                                st.markdown("**Choose Your School of Magic:**")
                                
                                school_names = list(WIZARD_SCHOOLS.keys())
                                selected_school = st.selectbox(
                                    "Arcane School:",
                                    school_names,
                                    key=f"wizard_school_select_{i}"
                                )
                                
                                # Show school details
                                school_data = WIZARD_SCHOOLS.get(selected_school, {})
                                st.caption(school_data.get("description", ""))
                                
                                if st.button("Choose School", key=f"choose_school_{i}"):
                                    c["wizard_school"] = selected_school
                                    c["pending_wizard_school"] = False
                                    
                                    # Re-apply school effects
                                    add_level1_class_resources_and_actions(c)
                                    
                                    st.toast(f"✅ Specialized in {selected_school}!")
                                    st.rerun()
                        
                        # ===== PALADIN DIVINE VOW =====
                        if pending.get("divine_vow"):
                            with st.expander(f"⚔️ Divine Vow (Choose 1)", expanded=True):
                                st.markdown("**Choose Your Sacred Oath:**")
                                
                                vow_names = list(PALADIN_DIVINE_VOWS.keys())
                                selected_vow = st.selectbox(
                                    "Divine Vow:",
                                    vow_names,
                                    key=f"divine_vow_select_{i}"
                                )
                                
                                # Show vow details
                                vow_data = PALADIN_DIVINE_VOWS.get(selected_vow, {})
                                st.caption(vow_data.get("description", ""))
                                
                                st.markdown("**Features:**")
                                for feat in vow_data.get("features", []):
                                    st.caption(f"• {feat}")
                                
                                if st.button("Take Vow", key=f"take_vow_{i}"):
                                    c["paladin_divine_vow"] = selected_vow
                                    c["pending_divine_vow"] = False
                                    
                                    # Re-apply vow effects
                                    add_level1_class_resources_and_actions(c)
                                    
                                    st.toast(f"✅ Swore the Vow of {selected_vow}!")
                                    st.rerun()
                        
                        # ===== BARBARIAN PRIMAL TALENTS =====
                        if pending.get("primal_talents"):
                            with st.expander(f"💪 Primal Talents ({c.get('pending_primal_talents', 0)} to choose)", expanded=True):
                                talents_to_choose = c.get("pending_primal_talents", 0)
                                current_talents = c.get("barbarian_primal_talents", [])
                                
                                # Get available talents (check prerequisites)
                                available_talents = []
                                for talent_name, talent_data in BARBARIAN_PRIMAL_TALENTS.items():
                                    if talent_name not in current_talents:
                                        prereq = talent_data.get("prerequisite")
                                        if prereq is None or prereq in current_talents:
                                            available_talents.append((talent_name, talent_data))
                                
                                if available_talents:
                                    talent_names = [t[0] for t in available_talents]
                                    
                                    selected_talents = st.multiselect(
                                        f"Choose {talents_to_choose} primal talent(s):",
                                        talent_names,
                                        max_selections=talents_to_choose,
                                        key=f"primal_talent_select_{i}"
                                    )
                                    
                                    # Show descriptions for selected
                                    if selected_talents:
                                        st.markdown("**Selected Talents:**")
                                        for t_name in selected_talents:
                                            t_data = BARBARIAN_PRIMAL_TALENTS.get(t_name, {})
                                            prereq = t_data.get("prerequisite")
                                            prereq_str = f" (Requires: {prereq})" if prereq else ""
                                            st.caption(f"• **{t_name}**{prereq_str}: {t_data.get('description', '')}")
                                    
                                    if st.button("Learn Primal Talents", key=f"learn_talents_{i}", 
                                            disabled=len(selected_talents) != talents_to_choose):
                                        # Apply talents
                                        current_talents.extend(selected_talents)
                                        c["barbarian_primal_talents"] = current_talents
                                        c["pending_primal_talents"] = 0
                                        
                                        # Re-apply talent effects
                                        add_level1_class_resources_and_actions(c)
                                        
                                        st.toast(f"✅ Learned {len(selected_talents)} primal talent(s)!")
                                        st.rerun()
                                else:
                                    st.caption("All primal talents already learned or prerequisites not met.")
                        
                        # ===== MARSHAL MANEUVERS =====
                        if pending.get("marshal_maneuvers"):
                            with st.expander(f"🎖️ Marshal Maneuvers ({c.get('pending_marshal_maneuvers', 0)} to choose)", expanded=True):
                                maneuvers_to_choose = c.get("pending_marshal_maneuvers", 0)
                                current_maneuvers = c.get("marshal_maneuvers", [])
                                
                                # Get available maneuvers
                                available_maneuvers = []
                                for maneuver_name, maneuver_data in MARSHAL_MANEUVERS.items():
                                    if maneuver_name not in current_maneuvers:
                                        available_maneuvers.append((maneuver_name, maneuver_data))
                                
                                if available_maneuvers:
                                    maneuver_names = [m[0] for m in available_maneuvers]
                                    
                                    selected_maneuvers = st.multiselect(
                                        f"Choose {maneuvers_to_choose} maneuver(s):",
                                        maneuver_names,
                                        max_selections=maneuvers_to_choose,
                                        key=f"marshal_maneuver_select_{i}"
                                    )
                                    
                                    # Show descriptions for selected
                                    if selected_maneuvers:
                                        st.markdown("**Selected Maneuvers:**")
                                        for m_name in selected_maneuvers:
                                            m_data = MARSHAL_MANEUVERS.get(m_name, {})
                                            mtype = m_data.get("type", "action").capitalize()
                                            st.caption(f"• **{m_name}** ({mtype}): {m_data.get('description', '')}")
                                    
                                    if st.button("Learn Maneuvers", key=f"learn_marshal_maneuvers_{i}", 
                                            disabled=len(selected_maneuvers) != maneuvers_to_choose):
                                        # Apply maneuvers
                                        current_maneuvers.extend(selected_maneuvers)
                                        c["marshal_maneuvers"] = current_maneuvers
                                        c["pending_marshal_maneuvers"] = 0
                                        
                                        # Re-apply maneuver effects
                                        add_level1_class_resources_and_actions(c)
                                        
                                        st.toast(f"✅ Learned {len(selected_maneuvers)} maneuver(s)!")
                                        st.rerun()
                                else:
                                    st.caption("All marshal maneuvers already learned.")
                        
                        # ===== KNIGHT MANEUVERS =====
                        if pending.get("knight_maneuvers"):
                            with st.expander(f"🛡️ Knight Maneuvers ({c.get('pending_knight_maneuvers', 0)} to choose)", expanded=True):
                                maneuvers_to_choose = c.get("pending_knight_maneuvers", 0)
                                current_maneuvers = c.get("knight_maneuvers", [])
                                
                                # Get available maneuvers
                                available_maneuvers = []
                                for maneuver_name, maneuver_data in KNIGHT_MANEUVERS.items():
                                    if maneuver_name not in current_maneuvers:
                                        available_maneuvers.append((maneuver_name, maneuver_data))
                                
                                if available_maneuvers:
                                    maneuver_names = [m[0] for m in available_maneuvers]
                                    
                                    selected_maneuvers = st.multiselect(
                                        f"Choose {maneuvers_to_choose} maneuver(s):",
                                        maneuver_names,
                                        max_selections=maneuvers_to_choose,
                                        key=f"knight_maneuver_select_{i}"
                                    )
                                    
                                    # Show descriptions for selected
                                    if selected_maneuvers:
                                        st.markdown("**Selected Maneuvers:**")
                                        for m_name in selected_maneuvers:
                                            m_data = KNIGHT_MANEUVERS.get(m_name, {})
                                            requires_mounted = " (Mounted only)" if m_data.get("requires_mounted") else ""
                                            st.caption(f"• **{m_name}** ({m_data.get('type', 'attack')}){requires_mounted}: {m_data.get('description', '')}")
                                    
                                    if st.button("Learn Maneuvers", key=f"learn_knight_maneuvers_{i}", 
                                            disabled=len(selected_maneuvers) != maneuvers_to_choose):
                                        # Apply maneuvers
                                        current_maneuvers.extend(selected_maneuvers)
                                        c["knight_maneuvers"] = current_maneuvers
                                        c["pending_knight_maneuvers"] = 0
                                        
                                        # Re-apply maneuver effects
                                        add_level1_class_resources_and_actions(c)
                                        
                                        st.toast(f"✅ Learned {len(selected_maneuvers)} knight maneuver(s)!")
                                        st.rerun()
                                else:
                                    st.caption("All knight maneuvers already learned.")
                        
                        # ===== WEAPON EXPERTISE (Fighter Level 6) =====
                        if pending.get("weapon_expertise"):
                            with st.expander("⚔️ Weapon Expertise (Choose 1 Weapon)", expanded=True):
                                st.markdown("**Choose a weapon for Weapon Expertise:**")
                                st.caption("You gain +1 to attack rolls and can reroll 1s on damage dice with this weapon.")
                                
                                # Get weapons from equipment
                                equipment = c.get("equipment", [])
                                attacks = c.get("attacks", [])
                                
                                # Collect weapon names from attacks that are from weapons
                                weapon_names = []
                                for atk in attacks:
                                    if atk.get("source") == "weapon":
                                        weapon_names.append(atk.get("name", "Unknown"))
                                
                                # Also add common martial weapons if no weapons equipped
                                if not weapon_names:
                                    weapon_names = [
                                        "Longsword", "Greatsword", "Battleaxe", "Greataxe",
                                        "Warhammer", "Maul", "Rapier", "Scimitar", "Shortsword",
                                        "Longbow", "Shortbow", "Crossbow", "Halberd", "Glaive",
                                        "Pike", "Lance", "Flail", "Morningstar", "Trident"
                                    ]
                                
                                selected_weapon = st.selectbox(
                                    "Weapon:",
                                    weapon_names,
                                    key=f"weapon_expertise_select_{i}"
                                )
                                
                                if selected_weapon:
                                    st.success(f"✅ **{selected_weapon}**: +1 attack, reroll 1s on damage")
                                    
                                    if st.button("Confirm Weapon Expertise", key=f"confirm_expertise_{i}"):
                                        c["weapon_expertise"] = selected_weapon
                                        c["pending_weapon_expertise"] = False
                                        
                                        # Re-apply class features to update bonuses
                                        add_level1_class_resources_and_actions(c)
                                        
                                        # Refresh attacks to apply expertise bonus
                                        refresh_attacks_from_equipment(c)
                                        
                                        st.toast(f"✅ Gained Weapon Expertise with {selected_weapon}!")
                                        st.rerun()
                
                # ========== COMPANIONS & WILD SHAPE SECTION ==========
                companions = c.get("companions", [])
                wild_shape_active = c.get("wild_shape_active", False)
                
                # Show companions section if character has any or can have them
                char_class = c.get("class", "").lower()
                char_classes_list = [cc.get("class_id", "").lower() for cc in c.get("classes", [])]
                has_companion_class = "ranger" in char_classes_list or "wizard" in char_classes_list or char_class in ["ranger", "wizard"]
                has_wild_shape = "druid" in char_classes_list or char_class == "druid"
                
                if companions or has_companion_class or has_wild_shape:
                    with box.expander("🐾 Companions & Wild Shape"):
                        
                        # ===== WILD SHAPE (Druid) =====
                        if has_wild_shape:
                            st.markdown("#### 🌿 Wild Shape")
                            
                            if wild_shape_active:
                                # Currently in Wild Shape
                                form_name = c.get("wild_shape_form", "Unknown")
                                ws_hp = c.get("wild_shape_hp", c.get("hp", 1))
                                ws_max_hp = c.get("wild_shape_max_hp", ws_hp)
                                
                                st.success(f"**Currently transformed into: {form_name}**")
                                
                                ws_col1, ws_col2, ws_col3 = st.columns([2, 2, 2])
                                with ws_col1:
                                    st.metric("Beast HP", f"{ws_hp}/{ws_max_hp}")
                                with ws_col2:
                                    st.metric("AC", c.get("ac", 10))
                                with ws_col3:
                                    st.metric("Speed", f"{c.get('speed_ft', 30)} ft")
                                
                                # Show beast attacks
                                beast_attacks = c.get("attacks", [])
                                if beast_attacks:
                                    st.markdown("**Beast Attacks:**")
                                    for atk in beast_attacks:
                                        st.caption(f"• {atk.get('name', 'Attack')}: +{atk.get('to_hit', 0)} to hit, {atk.get('damage', '1d4')} {atk.get('damage_type', '')}")
                                
                                if st.button("🔄 Revert to Normal Form", key=f"revert_ws_{i}"):
                                    revert_wild_shape(c)
                                    st.toast(f"{c.get('name', 'Character')} reverts to their normal form!")
                                    st.rerun()
                            else:
                                # Can transform
                                ws_uses = c.get("resources", {}).get("Wild Shape", {}).get("current", 0)
                                max_cr = c.get("wild_shape_max_cr", 0.25)
                                druid_level = c.get("level", 1)
                                
                                # Determine restrictions
                                allow_fly = druid_level >= 8
                                allow_swim = druid_level >= 3
                                
                                st.caption(f"Uses: {ws_uses} | Max CR: {max_cr} | {'Fly allowed' if allow_fly else 'No fly'} | {'Swim allowed' if allow_swim else 'No swim'}")
                                
                                if ws_uses > 0:
                                    # Get available beasts
                                    available_beasts = get_beasts_by_cr(max_cr, allow_fly, allow_swim)
                                    beast_names = [b.get("name", "") for b in available_beasts]
                                    
                                    if beast_names:
                                        selected_beast = st.selectbox(
                                            "Transform into:",
                                            beast_names,
                                            key=f"ws_beast_select_{i}"
                                        )
                                        
                                        # Show preview
                                        selected_beast_data = next((b for b in available_beasts if b.get("name") == selected_beast), None)
                                        if selected_beast_data:
                                            preview_col1, preview_col2 = st.columns(2)
                                            with preview_col1:
                                                hp_str = selected_beast_data.get("Hit Points", selected_beast_data.get("hp", "10"))
                                                hp_match = re.match(r"(\d+)", str(hp_str))
                                                preview_hp = int(hp_match.group(1)) if hp_match else 10
                                                st.caption(f"HP: {preview_hp}")
                                                
                                                ac_str = selected_beast_data.get("Armor Class", selected_beast_data.get("ac", "10"))
                                                ac_match = re.match(r"(\d+)", str(ac_str))
                                                preview_ac = int(ac_match.group(1)) if ac_match else 10
                                                st.caption(f"AC: {preview_ac}")
                                            with preview_col2:
                                                st.caption(f"Speed: {selected_beast_data.get('Speed', selected_beast_data.get('speed', '30 ft.'))}")
                                                st.caption(f"STR: {selected_beast_data.get('STR', 10)} DEX: {selected_beast_data.get('DEX', 10)}")
                                        
                                        if st.button("🐻 Transform!", key=f"transform_ws_{i}"):
                                            apply_wild_shape(c, selected_beast)
                                            # Use a Wild Shape resource
                                            c.setdefault("resources", {}).setdefault("Wild Shape", {})["current"] = ws_uses - 1
                                            st.toast(f"{c.get('name', 'Character')} transforms into a {selected_beast}!")
                                            st.rerun()
                                    else:
                                        st.caption("No valid beast forms available.")
                                else:
                                    st.warning("No Wild Shape uses remaining. Rest to regain uses.")
                            
                            st.markdown("---")
                        
                        # ===== COMPANIONS (Ranger/Wizard) =====
                        if companions:
                            st.markdown("#### 🐺 Active Companions")
                            
                            for comp_idx, comp in enumerate(companions):
                                comp_type = comp.get("companion_type", "companion")
                                comp_name = comp.get("name", "Unknown")
                                comp_hp = comp.get("hp", 1)
                                comp_max_hp = comp.get("max_hp", comp_hp)
                                
                                comp_box = st.container(border=True)
                                with comp_box:
                                    comp_col1, comp_col2, comp_col3, comp_col4 = st.columns([3, 2, 2, 1])
                                    
                                    with comp_col1:
                                        icon = "🦉" if comp_type == "familiar" else "🐺"
                                        st.markdown(f"{icon} **{comp_name}**")
                                        st.caption(f"({comp.get('base_creature', 'Unknown')})")
                                    
                                    with comp_col2:
                                        new_hp = st.number_input(
                                            "HP",
                                            min_value=0,
                                            max_value=comp_max_hp,
                                            value=comp_hp,
                                            key=f"comp_hp_{i}_{comp_idx}"
                                        )
                                        comp["hp"] = new_hp
                                    
                                    with comp_col3:
                                        st.metric("AC", comp.get("ac", 10))
                                    
                                    with comp_col4:
                                        if st.button("❌", key=f"rm_comp_{i}_{comp_idx}"):
                                            c["companions"].remove(comp)
                                            st.rerun()
                                    
                                    # Show companion attacks
                                    comp_attacks = comp.get("attacks", [])
                                    if comp_attacks:
                                        st.markdown("**Attacks:**")
                                        for atk in comp_attacks:
                                            st.caption(f"• {atk.get('name', 'Attack')}: +{atk.get('to_hit', 0)} to hit, {atk.get('damage', '1d4')} {atk.get('damage_type', '')}")
                        
                        # ===== ADD COMPANION (if eligible) =====
                        if has_companion_class and not any(comp.get("companion_type") in ["animal_companion", "familiar"] for comp in companions):
                            st.markdown("#### ➕ Summon Companion")
                            
                            if "ranger" in char_classes_list or char_class == "ranger":
                                # Ranger Animal Companion selection
                                ranger_level = next((cc.get("level", 0) for cc in c.get("classes", []) if cc.get("class_id", "").lower() == "ranger"), c.get("level", 1))
                                if ranger_level >= 3:
                                    max_cr = max(1, ranger_level // 3)
                                    available_beasts = get_beasts_by_cr(max_cr, allow_fly=True, allow_swim=True)
                                    beast_names = [b.get("name", "") for b in available_beasts]
                                    
                                    selected_companion = st.selectbox(
                                        "Choose Animal Companion:",
                                        beast_names,
                                        key=f"select_animal_comp_{i}"
                                    )
                                    
                                    if st.button("🐺 Summon Companion", key=f"summon_comp_{i}"):
                                        new_comp = create_animal_companion(c, selected_companion)
                                        if new_comp:
                                            c.setdefault("companions", []).append(new_comp)
                                            c["ranger_companion_type"] = selected_companion
                                            st.toast(f"Summoned {new_comp.get('name', 'companion')}!")
                                            st.rerun()
                                else:
                                    st.caption("Reach Ranger level 3 to gain an Animal Companion.")
                            
                            if "wizard" in char_classes_list or char_class == "wizard":
                                # Wizard Familiar selection
                                familiar_options = get_familiar_options()
                                familiar_names = [f.get("name", "") for f in familiar_options]
                                
                                selected_familiar = st.selectbox(
                                    "Choose Familiar:",
                                    familiar_names,
                                    key=f"select_familiar_{i}"
                                )
                                
                                if st.button("🦉 Summon Familiar", key=f"summon_fam_{i}"):
                                    new_fam = create_familiar(c, selected_familiar)
                                    if new_fam:
                                        c.setdefault("companions", []).append(new_fam)
                                        c["wizard_familiar_type"] = selected_familiar
                                        st.toast(f"Summoned {new_fam.get('name', 'familiar')}!")
                                        st.rerun()
                    
                    # ========== AWARD XP SECTION ==========
                    st.markdown("---")
                    st.markdown("#### 🎁 Award XP")
                    
                    # XP Amount
                    xp_amount = st.number_input(
                        "XP Amount",
                        min_value=0,
                        value=0,
                        step=50,
                        key=f"award_xp_amt_{i}",
                        help="Amount of experience points to award"
                    )
                    
                    # Source dropdown and reason
                    xp_src_col, xp_reason_col = st.columns([1, 2])
                    with xp_src_col:
                        xp_source = st.selectbox(
                            "Source",
                            ["combat", "quest", "milestone", "roleplay", "manual"],
                            format_func=lambda x: {
                                "combat": "⚔️ Combat",
                                "quest": "📜 Quest",
                                "milestone": "🏆 Milestone",
                                "roleplay": "🎭 Roleplay",
                                "manual": "✏️ Manual"
                            }.get(x, x),
                            key=f"award_xp_src_{i}"
                        )
                    with xp_reason_col:
                        xp_reason = st.text_input(
                            "Reason/Description",
                            placeholder="e.g., Defeated goblin ambush",
                            key=f"award_xp_reason_{i}",
                            label_visibility="collapsed"
                        )
                    
                    # Award button
                    if st.button("Award XP", key=f"award_xp_btn_{i}", disabled=xp_amount <= 0, use_container_width=True):
                        result = award_xp(c, xp_amount, reason=xp_reason or xp_source.capitalize(), source=xp_source)
                        if result["leveled_up"]:
                            st.toast(f"🎉 {c.get('name', 'Character')} gained {xp_amount:,} XP and can now level up!")
                        else:
                            st.toast(f"✨ {c.get('name', 'Character')} gained {xp_amount:,} XP!")
                        st.rerun()
                    
                    # ========== XP HISTORY ==========
                    xp_log = c.get("xp_log", [])
                    if xp_log:
                        with st.expander("📜 XP History", expanded=False):
                            for entry in reversed(xp_log[-10:]):
                                ts = entry.get("timestamp", "")[:10]
                                amt = entry.get("amount", 0)
                                reason = entry.get("reason", "")
                                source = entry.get("source", "")
                                sign = "+" if amt >= 0 else ""
                                
                                source_icon = {
                                    "combat": "⚔️",
                                    "quest": "📜",
                                    "milestone": "🏆",
                                    "roleplay": "🎭",
                                    "manual": "✏️",
                                    "dm_award": "👑"
                                }.get(source, "•")
                                
                                st.caption(f"{source_icon} {ts}: {sign}{amt:,} XP — {reason}")

        # ========== ENEMIES SECTION (still in left_col) ==========
    st.markdown("### 👹 Enemies")
    with st.container(height=320, border=True):  
        if not st.session_state.enemies:
            st.info("🕊️ No enemies in encounter. Add enemies from Setup or use the controls below.")
            # reminder: if this grows large, consider paging or filters by type/CR.
        else:
            for i, e in enumerate(st.session_state.enemies):
                card = st.container(border=True)
                h1, h2, h3, h4, h5 = card.columns([3,2,2,2,2])
                with h1: st.markdown(f"**{e.get('name','')}**")
                with h2: e["ac"] = int(st.number_input("AC", 0, 40, int(e.get("ac",10)), key=f"e_ac_{i}"))
                with h3: e["hp"] = int(st.number_input("HP", 0, 500, int(e.get("hp",10)), key=f"e_hp_{i}"))
                with h4:
                    # Position band dropdown (only during combat)
                    if st.session_state.in_combat:
                        current_band = ensure_position_band(e)
                        band_idx = POSITION_BANDS.index(current_band) if current_band in POSITION_BANDS else 1
                        new_band = st.selectbox(
                            "Pos",
                            POSITION_BANDS,
                            index=band_idx,
                            key=f"e_band_{i}",
                            format_func=lambda b: get_band_display(b)
                        )
                        e["position_band"] = new_band
                    else:
                        st.caption("—")
                with h5:
                    if st.button("Remove", key=f"e_rm_{i}"):
                        # Track defeated enemy for XP calculation
                        if st.session_state.in_combat:
                            if "combat_defeated_enemies" not in st.session_state:
                                st.session_state.combat_defeated_enemies = []
                            st.session_state.combat_defeated_enemies.append(e.copy())
                        del st.session_state.enemies[i]
                        st.rerun()
                with card.expander("Stat & Actions"):
                    name = e.get("name", "Enemy")
                    ac = e.get("ac", 10)
                    hp = e.get("hp", 10)
                    st.write(f"{name}: AC {ac}, HP {hp}")

                    # Check if already hydrated - avoids expensive SRD lookup every render
                    is_hydrated = e.get("_hydrated", False)
                    
                    # Show Sync button if not hydrated
                    if not is_hydrated:
                        # Look up SRD entry (by name or src)
                        base_name = str(name).split("#")[0].strip()
                        srd = next(
                            (
                                m for m in st.session_state.get("srd_enemies", [])
                                if m.get("name") == name
                                or m.get("name") == e.get("src")
                                or m.get("name") == base_name
                            ),
                            None,
                        )

                        if srd:
                            if st.button("🔄 Sync From SRD", key=f"sync_srd_{i}"):
                                # Hydrate this encounter enemy from SRD
                                keep_name = e.get("name", srd.get("name", "Enemy"))
                                keep_conditions = e.get("conditions", [])
                                keep_position = e.get("position_band", "near")
                                st.session_state.enemies[i] = {
                                    **srd,
                                    "name": keep_name,
                                    "hp": int(e.get("hp", srd.get("hp", 10))),
                                    "max_hp": int(e.get("max_hp", srd.get("max_hp", srd.get("hp", 10)))),
                                    "ac": int(e.get("ac", srd.get("ac", 10))),
                                    "conditions": keep_conditions,
                                    "position_band": keep_position,
                                    "_hydrated": True,  # Mark as hydrated
                                }
                                st.toast(f"Synced {keep_name} from SRD")
                                st.rerun()
                            st.caption("Click to load full stats from SRD")
                        else:
                            st.caption("No SRD data found for this monster.")
                    
                    # Display actions/attacks if available (whether hydrated or not)
                    actions = e.get("actions", []) or []
                    attacks = e.get("attacks", []) or []

                    if actions:
                        st.markdown("**Actions**")
                        for a in actions:
                            nm = a.get("name", "Action")
                            desc = a.get("description", a.get("desc", ""))
                            if desc:
                                st.markdown(f"- **{nm}**: {desc}")
                            else:
                                st.markdown(f"- **{nm}**")

                    if attacks:
                        st.markdown("**Attacks**")
                        for a in attacks:
                            nm = a.get("name", "Attack")
                            th = get_attack_to_hit(a)
                            dmg = get_attack_damage(a)
                            dt = get_attack_damage_type(a)
                            line = f"- **{nm}** (+{th} to hit) — {dmg}"
                            if dt:
                                line += f" {dt}"
                            st.markdown(line)

                    specials = e.get("special_abilities", []) or []
                    if specials:
                        st.markdown("**Special Abilities**")
                        for sa in specials:
                            st.markdown(f"- **{sa.get('name','')}**: {sa.get('desc','')}")
                
                # --- Conditions panel for this enemy ---
                with card.expander("Conditions"):
                    conditions = ensure_conditions(e)
                    
                    if not conditions:
                        st.caption("No active conditions.")
                    else:
                        for ci, cond in enumerate(conditions):
                            cond_col1, cond_col2 = st.columns([4, 1])
                            with cond_col1:
                                st.write(get_condition_display(cond))
                            with cond_col2:
                                if st.button("✖", key=f"rm_cond_e_{i}_{ci}"):
                                    conditions.pop(ci)
                                    st.rerun()
                    
                    # Add condition form
                    st.markdown("**Add Condition**")
                    srd_cond_names = get_srd_condition_names()
                    cond_options = srd_cond_names + ["(Custom)"]
                    
                    add_cond_col1, add_cond_col2 = st.columns([2, 1])
                    with add_cond_col1:
                        selected_cond = st.selectbox(
                            "Condition",
                            cond_options,
                            key=f"add_cond_sel_e_{i}",
                            label_visibility="collapsed"
                        )
                    with add_cond_col2:
                        cond_duration = st.number_input(
                            "Rounds",
                            min_value=0,
                            value=0,
                            key=f"add_cond_dur_e_{i}",
                            help="0 = indefinite"
                        )
                    
                    if selected_cond == "(Custom)":
                        custom_cond_name = st.text_input(
                            "Custom Condition Name",
                            key=f"add_cond_custom_e_{i}"
                        )
                    else:
                        custom_cond_name = None
                    
                    if st.button("Add Condition", key=f"add_cond_btn_e_{i}"):
                        cond_name = custom_cond_name if selected_cond == "(Custom)" else selected_cond
                        if cond_name:
                            dur = cond_duration if cond_duration > 0 else None
                            add_condition(e, cond_name, duration_rounds=dur)
                            st.toast(f"Added {cond_name} to {e.get('name', 'enemy')}")
                            st.rerun()
                        else:
                            st.warning("Please enter a condition name.")
        
# ===== RIGHT COLUMN: Combat Tracker + Attack Roller =====
with tracker_col:
# ---------------- Combat / Turn Tracker ----------------
    with st.container(height=360, border=False):
        st.markdown("### ⚔️ Combat Tracker")

        cA, cB, cC, cD = st.columns([2,1,1,1])

        with cA:
            if not st.session_state.in_combat:
                if st.button("Start Combat (Roll Initiative)"):
                    if not st.session_state.party or not st.session_state.enemies:
                        st.warning("Need at least one party member and one enemy.")
                    else:
                        start_combat()
                        st.success("Combat started. Initiative rolled.")
            else:
                ent = current_turn()
                if ent:
                    st.markdown(
                        f"**Round {st.session_state.combat_round}** — "
                        f"Turn: **{ent['name']}** ({ent['kind']}, Init {ent['init']})"
                    )
                else:
                    st.markdown("Combat active, but no valid turn entry.")

        with cB:
            if st.session_state.in_combat and st.button("Next Turn"):
                # Prevent a pending map click from applying to the next turn owner
                if st.query_params.get("grid_click_t") is not None:
                    st.query_params.clear()
                next_turn()

        with cC:
            # Auto-resolve enemy turn button
            if st.session_state.in_combat:
                ent = current_turn()
                is_enemy_turn = ent and ent.get("kind") == "enemy"
                
                if st.button("🤖 Auto Enemy", disabled=not is_enemy_turn, help="Auto-resolve enemy turn"):
                    if is_enemy_turn:
                        # Get enemy info for logging
                        enemy_idx = ent.get("idx", 0)
                        enemy = st.session_state.enemies[enemy_idx] if enemy_idx < len(st.session_state.enemies) else None
                        
                        # Capture state snapshot for logging
                        state_snapshot = None
                        if st.session_state.get("ai_logging_enabled", False) and AI_LOGGING_AVAILABLE:
                            enemy_pos = enemy.get("pos") if enemy else None
                            targets = [p for p in st.session_state.party if int(p.get("hp", 0)) > 0]
                            nearest_dist = None
                            if enemy_pos and targets:
                                from ai.featurize import get_grid_distance
                                nearest_dist = min(get_grid_distance(enemy_pos, t.get("pos", {})) for t in targets)
                            state_snapshot = {
                                "round": st.session_state.get("combat_round", 1),
                                "enemy_hp": enemy.get("hp") if enemy else None,
                                "enemy_pos": enemy_pos,
                                "target_count": len(targets),
                                "nearest_target_dist": nearest_dist,
                            }
                        
                        # Execute AI turn
                        ai_messages = ai_resolve_enemy_turn()
                        
                        # Log all messages to chat
                        for msg in ai_messages:
                            st.session_state.chat_log.append(("System", msg))
                        
                        # Log to AI telemetry if enabled
                        if st.session_state.get("ai_logging_enabled", False) and AI_LOGGING_AVAILABLE and state_snapshot:
                            logger = get_ui_logger()
                            if logger:
                                logger.log_ui_decision(
                                    enemy_name=enemy.get("name", "Enemy") if enemy else "Unknown",
                                    enemy_idx=enemy_idx,
                                    state_snapshot=state_snapshot,
                                    action_chosen={"messages": ai_messages[:3]},  # First 3 messages summarize action
                                    outcome={"message_count": len(ai_messages)}
                                )
                        
                        # Show results in a toast
                        st.toast(f"Enemy turn resolved: {len(ai_messages)} actions")
                        st.rerun()

        with cD:
            if st.session_state.in_combat and st.button("End Combat"):
                xp_awarded = end_combat(award_combat_xp=True)
                if xp_awarded > 0:
                    st.success(f"Combat ended! Party awarded {xp_awarded:,} XP total.")
                else:
                    st.info("Combat ended.")

        # Initiative Order display
        if st.session_state.initiative_order:
            st.markdown("**Initiative Order**")
            for i, ent in enumerate(st.session_state.initiative_order):
                marker = "➡️" if (i == st.session_state.turn_index and st.session_state.in_combat) else ""
                st.write(f"{marker} {ent['name']} — Init {ent['init']} (DEX mod {ent['dex_mod']})")

        # Display action economy state during combat
        if st.session_state.in_combat:
            st.markdown("**Action Economy**")
            st.caption(explain_action_state())
        
        # AI Telemetry expander
        with st.expander("🤖 AI Telemetry", expanded=False):
            if AI_LOGGING_AVAILABLE:
                # Initialize logging state
                if "ai_logging_enabled" not in st.session_state:
                    st.session_state.ai_logging_enabled = False
                
                logging_enabled = st.toggle(
                    "Enable AI Logging",
                    value=st.session_state.ai_logging_enabled,
                    key="ai_logging_toggle",
                    help="Log enemy AI decisions to JSONL files for training data"
                )
                
                if logging_enabled != st.session_state.ai_logging_enabled:
                    st.session_state.ai_logging_enabled = logging_enabled
                    set_ui_logging_enabled(logging_enabled)
                    if logging_enabled:
                        st.success("AI logging enabled. Decisions will be saved to data/ai/rollout_logs/")
                    else:
                        st.info("AI logging disabled.")
                
                if st.session_state.ai_logging_enabled:
                    st.caption("📊 Logging active - enemy decisions are being recorded")
                    
                    # Show log directory
                    log_dir = os.path.join(_project_root, "data", "ai", "rollout_logs")
                    if os.path.exists(log_dir):
                        log_files = [f for f in os.listdir(log_dir) if f.endswith(".jsonl")]
                        st.caption(f"Log files: {len(log_files)} in data/ai/rollout_logs/")
            else:
                st.info("AI logging module not available. Install ai/ module for telemetry.")
                st.caption("The UI works fine without it - this is for RL training data collection.")

with roller_col:   
    # Attack Roller
    st.markdown("### 🎯 Attack Roller")

    # Only active during combat, and only for the active combatant (PC or enemy)
    ent = current_turn()
    if not (st.session_state.in_combat and ent):
        st.info("🎲 Attack Roller is only available during combat. Start combat to use this feature.")
    else:
            kind = ent.get("kind")
            idx = ent.get("idx")

            # Resolve attacker (party or enemy) + target list
            # NOTE: kind must be "party" or "enemy" (never "pc")
            att = None
            targets = []
            target_kind = None
            
            if kind == "party":
                if idx is None or idx >= len(st.session_state.party):
                    st.warning("Active party member not found in party list.")
                else:
                    att = st.session_state.party[idx]
                    targets = st.session_state.enemies
                    target_kind = "enemy"
            elif kind == "enemy":
                if idx is None or idx >= len(st.session_state.enemies):
                    st.warning("Active enemy not found in enemies list.")
                else:
                    att = st.session_state.enemies[idx]
                    targets = st.session_state.party
                    target_kind = "party"
            else:
                st.caption("Unknown active combatant type.")

            if att:
                # Display action economy state for this actor
                st.caption(f"**Actions Available:** {explain_action_state()}")
                
                # ===== ACTION SURGE (Fighter) =====
                action_surge_resource = att.get("resources", {}).get("Action Surge", {})
                action_surge_current = action_surge_resource.get("current", 0)
                if action_surge_current > 0 and not can_spend("standard"):
                    st.markdown("---")
                    col_surge1, col_surge2 = st.columns([3, 1])
                    with col_surge1:
                        st.warning(f"⚡ **Action Surge** available! ({action_surge_current} use{'s' if action_surge_current > 1 else ''} remaining)")
                    with col_surge2:
                        if st.button("Use Action Surge", key=f"action_surge_{kind}_{idx}"):
                            result = use_action_surge(att)
                            st.session_state.chat_log.append(("System", result))
                            st.toast(result)
                            st.rerun()
                    st.markdown("---")
                
                # ===== UNMATCHED COMBATANT (Fighter 20) =====
                unmatched_resource = att.get("resources", {}).get("Unmatched Combatant", {})
                unmatched_current = unmatched_resource.get("current", 0)
                if unmatched_current > 0:
                    # Store pending reroll state
                    if "pending_unmatched_reroll" not in st.session_state:
                        st.session_state.pending_unmatched_reroll = None
                    
                    with st.expander(f"🏆 **Unmatched Combatant** ({unmatched_current} use remaining)", expanded=False):
                        st.info("Once per day: Reroll any attack roll, saving throw, or damage roll. Must use the new result.")
                        st.caption("Use this when you want to reroll a bad result. The reroll will be applied to your next roll of that type.")
                
                # ===== BARBARIAN RAGE =====
                rage_resource = att.get("resources", {}).get("Rage", {})
                rage_current = rage_resource.get("current", 0)
                is_currently_raging = att.get("is_raging", False)
                
                if rage_current > 0 or is_currently_raging:
                    st.markdown("---")
                    col_rage1, col_rage2 = st.columns([3, 1])
                    with col_rage1:
                        if is_currently_raging:
                            rage_bonus = att.get("rage_bonus", 2)
                            rage_details = f"+{rage_bonus} melee damage, +{rage_bonus} STR/CON/WIS saves, -2 AC, resist B/P/S"
                            
                            # Show additional rage features
                            extra_features = []
                            if att.get("rage_damage_reduction", 0) > 0:
                                extra_features.append(f"DR {att['rage_damage_reduction']}/-")
                            if att.get("endless_rage"):
                                extra_features.append("Endless")
                            if att.get("has_unyielding_force"):
                                extra_features.append("Can't be restrained")
                            
                            if extra_features:
                                rage_details += f" | {', '.join(extra_features)}"
                            
                            st.success(f"🔥 **RAGING!** ({rage_details})")
                        else:
                            st.info(f"🔥 **Rage** available! ({rage_current} use{'s' if rage_current > 1 else ''} remaining)")
                    with col_rage2:
                        if is_currently_raging:
                            if st.button("End Rage", key=f"end_rage_{kind}_{idx}"):
                                result = toggle_rage(att, activate=False)
                                st.session_state.chat_log.append(("System", result))
                                st.toast(result)
                                st.rerun()
                        else:
                            if st.button("Enter Rage", key=f"start_rage_{kind}_{idx}"):
                                result = toggle_rage(att, activate=True)
                                st.session_state.chat_log.append(("System", result))
                                st.toast(result)
                                st.rerun()
                    st.markdown("---")
                
                # ===== RELENTLESS ASSAULT (Barbarian 16+) =====
                if att.get("relentless_assault_pending"):
                    st.warning("⚔️ **Relentless Assault!** You killed an enemy - make a free melee attack against another creature within reach!")
                    # List available melee targets
                    melee_targets = []
                    for ei, enemy in enumerate(st.session_state.get("enemies", [])):
                        if enemy.get("hp", 0) > 0:
                            melee_targets.append((ei, enemy.get("name", f"Enemy {ei+1}")))
                    
                    if melee_targets:
                        target_names = [t[1] for t in melee_targets]
                        selected_target = st.selectbox("Target for Relentless Assault:", target_names, key=f"relentless_target_{kind}_{idx}")
                        
                        if st.button("⚔️ Execute Relentless Assault", key=f"relentless_attack_{kind}_{idx}"):
                            # Find target index
                            target_idx = next((t[0] for t in melee_targets if t[1] == selected_target), 0)
                            target = st.session_state.enemies[target_idx]
                            
                            # Get a melee attack
                            melee_attacks = [a for a in (att.get("attacks") or []) if a.get("reach")]
                            if melee_attacks:
                                chosen_attack = melee_attacks[0]
                                lines = resolve_single_attack(att, target, target_idx, chosen_attack, 1, 1)
                                result_msg = "\n".join(lines)
                                st.session_state.chat_log.append(("System", f"**Relentless Assault:**\n{result_msg}"))
                                st.toast("⚔️ Relentless Assault executed!")
                            else:
                                st.session_state.chat_log.append(("System", "No melee attack available for Relentless Assault."))
                            
                            # Clear the pending flag
                            att["relentless_assault_pending"] = False
                            st.rerun()
                    else:
                        st.caption("No valid targets remaining.")
                        att["relentless_assault_pending"] = False
                    st.markdown("---")
                
                # reminder: enemies added from SRD are already normalized into our schema
                actions = att.get("attacks") or att.get("actions") or []
                action_names = [a.get("name", "Action") for a in actions] + ["(Custom)"]

                # Unique widget keys per-turn/actor so Streamlit never duplicates keys
                actor_key = f"{kind}_{idx}"

                act = st.selectbox(
                    "Action",
                    action_names,
                    key=f"atk_act_sel_{actor_key}",
                )
                
                # ===== MANEUVER SELECTION (Fighter/Marshal) =====
                available_maneuvers = att.get("available_maneuvers", [])
                selected_maneuver = None
                maneuver_data = None
                
                if available_maneuvers:
                    # Get attack-type maneuvers that can be used with this attack
                    attack_maneuvers = ["(None)"]
                    for m_name in available_maneuvers:
                        m_data = FIGHTER_MANEUVERS.get(m_name, {})
                        if m_data.get("type") == "attack_modifier":
                            attack_maneuvers.append(m_name)
                    
                    if len(attack_maneuvers) > 1:
                        # Check if we have martial dice available
                        martial_dice = att.get("resources", {}).get("Martial Dice", {}).get("current", 0)
                        die_size = att.get("fighter_die_size", att.get("marshal_die_size", "d6"))
                        
                        st.markdown("---")
                        st.markdown(f"**⚔️ Combat Maneuver** (Martial Dice: {martial_dice})")
                        
                        selected_maneuver = st.selectbox(
                            "Apply Maneuver:",
                            attack_maneuvers,
                            key=f"maneuver_sel_{actor_key}",
                            disabled=martial_dice <= 0
                        )
                        
                        if selected_maneuver and selected_maneuver != "(None)":
                            maneuver_data = FIGHTER_MANEUVERS.get(selected_maneuver, {})
                            st.caption(f"📜 {maneuver_data.get('description', '')} (Uses 1 Martial Die, {die_size})")
                            
                            # Show maneuver effects preview
                            if maneuver_data.get("reach_bonus"):
                                st.success(f"✅ +{maneuver_data['reach_bonus']} ft reach for this attack!")
                            if maneuver_data.get("effect") == "to_hit_bonus":
                                st.success(f"✅ Add {die_size} to attack roll!")
                            if "damage" in maneuver_data.get("effect", ""):
                                st.success(f"✅ Add {die_size} to damage!")
                            if maneuver_data.get("save"):
                                dc = att.get("maneuver_dc", 8 + (att.get("abilities", {}).get("STR", 10) - 10) // 2 + att.get("bab", 0))
                                st.info(f"🎯 Target must make DC {dc} {maneuver_data['save']} save or suffer additional effect!")
                        
                        st.markdown("---")
            
                # Determine action type and get action object
                aobj = None
                required_action_type = "standard"  # default for attacks

                if act == "(Custom)":
                    to_hit = st.number_input(
                        "To-Hit Bonus",
                        -10,
                        20,
                        0,
                        key=f"atk_custom_to_{actor_key}",
                    )
                    dmg = st.text_input(
                        "Damage Dice",
                        value="1d6",
                        key=f"atk_custom_dmg_{actor_key}",
                    )
                    dmg_type = st.text_input(
                        "Damage Type (optional)",
                        value="",
                        key=f"atk_custom_dt_{actor_key}",
                    )
                    # Custom attacks default to standard action
                    required_action_type = "standard"
                else:
                    aobj = next((a for a in actions if a.get("name") == act), None)
                    # Use helper functions for consistent field access
                    to_hit = get_attack_to_hit(aobj) if aobj else 0
                    dmg = get_attack_damage(aobj) if aobj else "1d6"
                    dmg_type = get_attack_damage_type(aobj) if aobj else ""
                    # Check if action has a specific action_type from ACTION_SCHEMA
                    required_action_type = get_action_type_for_attack(aobj)
            
                # Detect if this is a spell save action
                is_spell_save = aobj and aobj.get("save") and aobj.get("dc")
                is_spell_attack = aobj and aobj.get("type") == "spell_attack"
                spell_dc = aobj.get("dc") if aobj else None
                spell_save = aobj.get("save") if aobj else None
            
                # Show what action type this will consume and range info
                st.caption(f"This action requires: **{required_action_type.capitalize()}** action")
                
                # Show spell info if applicable
                if is_spell_save:
                    st.caption(f"🔮 **Spell Save:** DC {spell_dc} {spell_save}")
                elif is_spell_attack:
                    st.caption(f"🔮 **Spell Attack:** +{to_hit} to hit")
                
                # Show attack range requirement
                if aobj:
                    st.caption(f"Attack range: {explain_band_requirement(aobj)}")
                
                # Show attacker's current position
                attacker_band = get_position_band(att)
                st.caption(f"Your position: **{get_band_display(attacker_band)}**")

                if not targets:
                    st.caption("No valid targets available.")
                else:
                    # Target picker with position info
                    def format_target(i):
                        t = targets[i]
                        t_band = get_position_band(t)
                        return f"{t.get('name', f'Target #{i+1}')} ({t_band})"
                    
                    target_idx = st.selectbox(
                        "Target",
                        list(range(len(targets))),
                        format_func=format_target,
                        key=f"atk_target_{actor_key}",
                    )

                    target = targets[target_idx]
                    target_ac = int(target.get("ac", 10))
                    target_band = get_position_band(target)
                    st.caption(f"Target AC: {target_ac} | Position: **{get_band_display(target_band)}**")

                    # Check if the required action type is available
                    action_available = can_spend(required_action_type)
                    
                    # Check range band validity - use grid-based range check if available
                    attack_for_range = aobj if aobj else {"reach": 5}  # Custom attacks default to melee with 5ft reach
                    
                    # Apply maneuver reach bonus (e.g., Lunging Attack)
                    if selected_maneuver and selected_maneuver != "(None)" and maneuver_data:
                        reach_bonus = maneuver_data.get("reach_bonus", 0)
                        if reach_bonus > 0:
                            attack_for_range = dict(attack_for_range) if attack_for_range else {}
                            current_reach = attack_for_range.get("reach", 5)
                            attack_for_range["reach"] = current_reach + reach_bonus
                    
                    # Try grid-based range check first
                    att_pos = att.get("pos")
                    tgt_pos = target.get("pos")

                    has_grid_pos = (
                        isinstance(att_pos, dict) and "x" in att_pos and "y" in att_pos and
                        isinstance(tgt_pos, dict) and "x" in tgt_pos and "y" in tgt_pos
                    )

                    if has_grid_pos:
                        range_valid = is_target_in_attack_range(att, target, attack_for_range)
                    else:
                        range_valid = can_attack_at_band(attack_for_range, target_band)
                    
                    
                    # Button label changes based on action type
                    button_label = "Cast Spell" if (is_spell_save or is_spell_attack) else "Roll Attack"
                    
                    if not action_available:
                        st.error(f"❌ {required_action_type.capitalize()} action already used this turn!")
                        st.button(button_label, key=f"atk_roll_{actor_key}", disabled=True)
                    elif not range_valid:
                        attack_range = get_attack_range_squares(attack_for_range)
                        distance = get_grid_distance(att.get("pos"), target.get("pos"))
                        st.error(f"❌ Target is {distance} squares away, but this attack only reaches {attack_range} squares! Move closer or choose a different attack.")
                        st.button(button_label, key=f"atk_roll_{actor_key}", disabled=True)
                    elif st.button(button_label, key=f"atk_roll_{actor_key}"):
                        # Spend the action
                        spend(required_action_type)
                        
                        # ========== MANEUVER SETUP ==========
                        maneuver_to_hit_bonus = 0
                        maneuver_damage_bonus = 0
                        maneuver_die_roll = 0
                        maneuver_effect_text = ""
                        
                        if selected_maneuver and selected_maneuver != "(None)" and maneuver_data:
                            # Consume a Martial Die
                            martial_dice_res = att.get("resources", {}).get("Martial Dice", {})
                            if martial_dice_res.get("current", 0) > 0:
                                att.setdefault("resources", {}).setdefault("Martial Dice", {})["current"] -= 1
                                
                                # Roll the martial die
                                die_size = att.get("fighter_die_size", att.get("marshal_die_size", "d6"))
                                die_value = int(die_size[1:])
                                maneuver_die_roll = random.randint(1, die_value)
                                
                                st.info(f"⚔️ **{selected_maneuver}** - Martial Die: {die_size} → **{maneuver_die_roll}**")
                                
                                # Apply maneuver effects based on timing
                                effect = maneuver_data.get("effect", "")
                                timing = maneuver_data.get("timing", "on_hit")
                                
                                if timing == "before_attack":
                                    if effect == "to_hit_bonus":
                                        maneuver_to_hit_bonus = maneuver_die_roll
                                        st.success(f"✅ +{maneuver_die_roll} to attack roll!")
                                    elif effect == "reach_and_damage":
                                        maneuver_damage_bonus = maneuver_die_roll
                                        st.success(f"✅ +5 ft reach and +{maneuver_die_roll} damage on hit!")
                                elif timing == "on_hit":
                                    # These bonuses apply only if we hit
                                    maneuver_damage_bonus = maneuver_die_roll
                                    maneuver_effect_text = f" (+{maneuver_die_roll} from {selected_maneuver})"
                        
                        # ========== SPELL SAVE RESOLUTION ==========
                        if is_spell_save:
                            # Target makes saving throw
                            d20 = random.randint(1, 20)
                            
                            # Get target's save modifier (if available)
                            save_mod = get_total_save(target, spell_save) if target_kind == "party" else 0
                            if save_mod == 0:
                                target_abilities = target.get("abilities", {})
                                if spell_save and spell_save in target_abilities:
                                    save_mod = (int(target_abilities[spell_save]) - 10) // 2
                            
                            save_total = d20 + save_mod
                            save_success = save_total >= spell_dc
                            
                            st.write(
                                f"🎯 **{target.get('name', 'Target')}** makes a **{spell_save}** save: "
                                f"d20({d20}) + {save_mod} = **{save_total}** vs DC {spell_dc} → "
                                f"{'**SAVED!**' if save_success else '**FAILED!**'}"
                            )
                            
                            # ===== INDOMITABLE / INDOMITABLE WILL REROLL OPTIONS =====
                            if not save_success and target_kind == "party":
                                # Check for Indomitable Will (WIS/CHA saves, free reroll)
                                if can_use_indomitable_will(target, spell_save):
                                    if st.button(f"💪 Use Indomitable Will (reroll {spell_save} save)", key=f"indom_will_{target_idx}"):
                                        new_success, msg = use_indomitable_will(target, d20, spell_save, spell_dc)
                                        st.write(msg)
                                        st.session_state.chat_log.append(("System", msg))
                                        if new_success:
                                            save_success = True
                                
                                # Check for Indomitable (any save, uses resource)
                                if not save_success and can_use_indomitable(target):
                                    indom_uses = target.get("resources", {}).get("Indomitable", {}).get("current", 0)
                                    if st.button(f"🔄 Use Indomitable ({indom_uses} use{'s' if indom_uses > 1 else ''} left)", key=f"indom_{target_idx}"):
                                        new_success, msg = use_indomitable(target, d20, spell_save, spell_dc)
                                        st.write(msg)
                                        st.session_state.chat_log.append(("System", msg))
                                        if new_success:
                                            save_success = True
                            
                            st.session_state.chat_log.append(
                                (
                                    "System",
                                    f"{att.get('name','Caster')} casts {act} on {target.get('name','Target')} → "
                                    f"{spell_save} save: {save_total} vs DC {spell_dc} → {'SAVED' if save_success else 'FAILED'} "
                                    f"({required_action_type.capitalize()} action spent)",
                                )
                            )
                            
                            # Apply damage on failed save (or half on success for some spells)
                            if not save_success:
                                if dmg and dmg != "—":
                                    dmg_total, breakdown = roll_dice(dmg)
                                    st.write(f"💥 Damage: {dmg} → **{dmg_total}** ({breakdown})")
                                    if dmg_type:
                                        st.caption(f"Damage Type: {dmg_type}")
                                    
                                    # Apply damage
                                    if target_kind == "enemy":
                                        before = int(st.session_state.enemies[target_idx].get("hp", 0))
                                        after = max(0, before - int(dmg_total))
                                        st.session_state.enemies[target_idx]["hp"] = after
                                    else:
                                        before = int(st.session_state.party[target_idx].get("hp", 0))
                                        after = max(0, before - int(dmg_total))
                                        st.session_state.party[target_idx]["hp"] = after
                                    
                                    st.write(
                                        f"{target.get('name','Target')} takes **{dmg_total}** damage "
                                        f"and is now at **{after} HP** (was {before})."
                                    )
                                    
                                    st.session_state.chat_log.append(
                                        (
                                            "System",
                                            f"{att.get('name','Caster')} deals {dmg_total} {dmg_type or ''} damage to "
                                            f"{target.get('name','Target')} ({before} → {after} HP).",
                                        )
                                    )
                                else:
                                    st.write("Spell effect applied (no damage).")
                            else:
                                st.write("Target resists the spell effect!")
                        
                        # ========== SPELL ATTACK / REGULAR ATTACK RESOLUTION ==========
                        else:
                            d20 = random.randint(1, 20)
                            total = d20 + int(to_hit) + maneuver_to_hit_bonus
                            hit = total >= target_ac

                            attack_type = "🔮 Spell attack" if is_spell_attack else "To-Hit"
                            maneuver_str = f" + {maneuver_to_hit_bonus} (maneuver)" if maneuver_to_hit_bonus > 0 else ""
                            st.write(
                                f"{attack_type}: d20({d20}) + {to_hit}{maneuver_str} = **{total}** "
                                f"vs AC {target_ac} → {'**HIT**' if hit else '**MISS**'}"
                            )

                            st.session_state.chat_log.append(
                                (
                                    "System",
                                    f"{att.get('name','Attacker')} {'casts' if is_spell_attack else 'attacks'} {target.get('name','Target')} with {act}"
                                    f"{' using ' + selected_maneuver if selected_maneuver and selected_maneuver != '(None)' else ''} → "
                                    f"{total} vs AC {target_ac} → {'HIT' if hit else 'MISS'} "
                                    f"({required_action_type.capitalize()} action spent)",
                                )
                            )

                            if hit:
                                # Defensive: handle missing or invalid damage
                                if dmg == "—" or not dmg:
                                    st.write("Damage: **—** (no damage specified)")
                                    dmg_total = 0
                                else:
                                    base_dmg_total, breakdown = roll_dice(dmg)
                                    dmg_total = base_dmg_total + maneuver_damage_bonus
                                    
                                    if maneuver_damage_bonus > 0:
                                        st.write(f"Damage: {dmg} → {base_dmg_total} + {maneuver_damage_bonus} (maneuver) = **{dmg_total}**{maneuver_effect_text}")
                                    else:
                                        st.write(f"Damage: {dmg} → **{dmg_total}** ({breakdown})")
                                    
                                    if dmg_type:
                                        st.caption(f"Damage Type: {dmg_type}")
                                
                                # ========== MANEUVER SECONDARY EFFECTS ==========
                                if selected_maneuver and selected_maneuver != "(None)" and maneuver_data:
                                    effect = maneuver_data.get("effect", "")
                                    save_type = maneuver_data.get("save")
                                    
                                    if save_type:
                                        # Target must make a save
                                        dc = att.get("maneuver_dc", 8 + (att.get("abilities", {}).get("STR", 10) - 10) // 2 + att.get("bab", 0))
                                        save_roll = random.randint(1, 20)
                                        target_save_mod = (target.get("abilities", {}).get(save_type, 10) - 10) // 2
                                        save_total = save_roll + target_save_mod
                                        save_success = save_total >= dc
                                        
                                        st.write(f"🎯 {target.get('name', 'Target')} {save_type} save: d20({save_roll}) + {target_save_mod} = {save_total} vs DC {dc} → {'**SAVED**' if save_success else '**FAILED**'}")
                                        
                                        if not save_success:
                                            if "prone" in effect:
                                                add_condition(target, "Prone", duration_rounds=None)
                                                st.warning(f"💥 {target.get('name', 'Target')} is knocked **Prone**!")
                                            elif "disarm" in effect:
                                                st.warning(f"💥 {target.get('name', 'Target')} drops their weapon!")
                                            elif "frighten" in effect:
                                                add_condition(target, "Frightened", duration_rounds=1)
                                                st.warning(f"💥 {target.get('name', 'Target')} is **Frightened** until end of next turn!")
                                            elif "push" in effect:
                                                push_dist = maneuver_data.get("push_distance", 10)
                                                st.warning(f"💥 {target.get('name', 'Target')} is pushed {push_dist} ft!")
                                    
                                    # Cleave effect (Sweeping Motion)
                                    if effect == "cleave" and maneuver_die_roll > 0:
                                        st.info(f"⚔️ Sweeping Motion: Can deal {maneuver_die_roll} damage to another creature within 5ft if attack roll ({total}) would hit them.")

                                    # Apply damage to the correct list in session state
                                    if target_kind == "enemy":
                                        before = int(st.session_state.enemies[target_idx].get("hp", 0))
                                        after = max(0, before - int(dmg_total))
                                        st.session_state.enemies[target_idx]["hp"] = after
                                    else:
                                        before = int(st.session_state.party[target_idx].get("hp", 0))
                                        after = max(0, before - int(dmg_total))
                                        st.session_state.party[target_idx]["hp"] = after

                                    st.write(
                                        f"{target.get('name','Target')} takes **{dmg_total}** damage "
                                        f"and is now at **{after} HP** (was {before})."
                                    )

                                    st.session_state.chat_log.append(
                                        (
                                            "System",
                                            f"{att.get('name','Attacker')} deals {dmg_total} damage to "
                                            f"{target.get('name','Target')} ({before} → {after} HP).",
                                        )
                                    )

    # Chat Log
    with st.container(height=360, border=False):    
        st.markdown("### 💬 Chat Log")
        
        # Chat input at top
        c1, c2 = st.columns([6,1])
        with c1:
            user_msg = st.text_input(
                "Type a message (e.g., 'attack the goblin', '/roll 2d6+1')",
                key="chat_input",
                label_visibility="collapsed",
                placeholder="Type a message..."
            )
        with c2:
            send = st.button("Send", use_container_width=True)

        # Handle chat submission
        if send:
            msg = (user_msg or "").strip()
            if msg:
                st.session_state.chat_log.append(("Player", msg))

                # 1) Move intent (consumes Move action on the active turn)
                move_result = resolve_move_action(msg)
                if move_result is not None:
                    st.session_state.chat_log.append(("System", move_result))
                else:
                    # 2) Attack intent
                    result = resolve_attack(msg)
                    if result is not None:
                        st.session_state.chat_log.append(("System", result))
                    else:
                        # 3) Skill check intent
                        skill_result = resolve_skill_check(msg)
                        if skill_result is not None:
                            st.session_state.chat_log.append(("System", skill_result))
                        else:
                            # 4) Default DM reply
                            reply = reply_for(msg)
                            if not msg.lower().startswith("/roll") and "roll " in msg.lower():
                                more = extract_inline_rolls(msg)
                                if more:
                                    lines = []
                                    for d in more:
                                        t, br = roll_dice(d)
                                        lines.append(f"• {d}: {br}")
                                    reply += "\n\nInline rolls:\n" + "\n".join(lines)
                            st.session_state.chat_log.append(("DM", reply))

                st.rerun()

        # Chat message display
        chat_box = st.container(border=True, height=240)

        # Display chat messages
        if not st.session_state.chat_log:
            st.caption("💭 No messages yet. Type below to interact with the Virtual DM.")
        else:
            for speaker, text in st.session_state.chat_log[-30:]:
                if speaker == "System":
                    st.caption(f"🎲 {text}")
                elif speaker == "DM":
                    st.info(f"🎭 **DM:** {text}")
                elif speaker == "Player":
                    st.success(f"👤 **You:** {text}")
            else:
                st.markdown(f"**{speaker}:** {text}")

# ===== Middle COLUMN: TACTICAL MAP SECTION =====
with mid_col:
    st.markdown("### 🗺️ Tactical Map")

    # Initialize map state
    if "map_selected_actor" not in st.session_state:
        st.session_state.map_selected_actor = None
    if "map_edit_mode" not in st.session_state:
        st.session_state.map_edit_mode = False
    if "map_show_coords" not in st.session_state:
        st.session_state.map_show_coords = False
    if "map_last_click" not in st.session_state:
        st.session_state.map_last_click = None
    if "map_hazard_paint" not in st.session_state:
        st.session_state.map_hazard_paint = "None"
    
    if "last_grid_click_t" not in st.session_state:
        st.session_state.last_grid_click_t = None

    # Ensure grid exists
    ensure_grid()
    auto_place_actors()

    # Map controls
    map_ctrl_col1, map_ctrl_col2, map_ctrl_col3 = st.columns([2, 2, 2]) 

    with map_ctrl_col1:
        grid_width = st.number_input("Grid Width", min_value=5, max_value=30, value=st.session_state.grid.get("width", 20), key="map_width")
        grid_height = st.number_input("Grid Height", min_value=5, max_value=30, value=st.session_state.grid.get("height", 20), key="map_height")

    with map_ctrl_col2:
        square_size = st.selectbox("Square Size (ft)", [5, 10], index=0 if st.session_state.grid.get("square_size_ft", 5) == 5 else 1, key="map_square_size")
        terrain_names = get_terrain_names()
        current_biome = st.session_state.grid.get("biome") or (terrain_names[0] if terrain_names else "Forest")
        biome_idx = terrain_names.index(current_biome) if current_biome in terrain_names else 0
        selected_biome = st.selectbox("Encounter Biome", terrain_names, index=biome_idx, key="map_biome")

    with map_ctrl_col3:
        map_seed = st.number_input("Seed", min_value=0, max_value=999999, value=st.session_state.grid.get("seed") or 12345, key="map_seed")
        if st.button("🎲 Generate Map", key="map_generate"):
            new_grid = generate_map(grid_width, grid_height, selected_biome, map_seed)
            new_grid["square_size_ft"] = square_size
            st.session_state.grid = new_grid
            # Re-place actors on new grid
            for actor in st.session_state.get("party", []):
                actor["pos"] = None
            for actor in st.session_state.get("enemies", []):
                actor["pos"] = None
            auto_place_actors()
            st.toast(f"Generated {selected_biome} map (seed: {map_seed})")
            st.rerun()

        # Use callback to ensure edit mode state is set BEFORE click handling
        def on_edit_toggle():
            st.session_state.map_edit_mode = st.session_state.map_edit_toggle
        def on_coords_toggle():
            st.session_state.map_show_coords = st.session_state.map_coords_toggle
        
        st.toggle("✏️ Edit Mode", value=st.session_state.map_edit_mode, key="map_edit_toggle", on_change=on_edit_toggle)
        st.toggle("📍 Show Coords", value=st.session_state.map_show_coords, key="map_coords_toggle", on_change=on_coords_toggle)

        # --- Move click arming (only refresh when we are waiting for a move destination) ---
        if "awaiting_move_click" not in st.session_state:
            st.session_state.awaiting_move_click = False

            from streamlit_autorefresh import st_autorefresh

            # Only refresh while we're armed and waiting for the destination click
            if st.session_state.awaiting_move_click:
                st_autorefresh(interval=250, key="await_move_refresh", limit=40)

        # Only show/allow this in combat and not in edit mode
        if st.session_state.get("in_combat", False) and not st.session_state.get("map_edit_mode", False):
            # Optional: only arm if the current actor still has a move available
            can_arm = can_spend("move")

            if st.button("🏃 Move (Click Destination)", disabled=not can_arm, key="arm_move_click"):
                st.session_state.awaiting_move_click = True
                st.toast("Click a destination square within your movement range.", icon="🏃")

    # Handle grid clicks via query params
    # IMPORTANT: Check edit mode state BEFORE processing clicks to avoid race conditions
    try:
        query_params = st.query_params
        click_x = query_params.get("grid_click_x")
        click_y = query_params.get("grid_click_y")
        click_t = query_params.get("grid_click_t")
        
        if click_x is not None and click_y is not None and click_t is not None:
            click_x = int(click_x)
            click_y = int(click_y)
            click_key = f"{click_x},{click_y},{click_t}"
            
            if st.session_state.map_last_click != click_key:
                st.session_state.map_last_click = click_key

                # Always clear params after consuming a click so it can't apply to next actor/turn
                def _consume_click_params():
                    st.query_params.clear()

                # Force an immediate rerun after any click is processed so movement/selection updates instantly
                                
                grid = st.session_state.grid
                
                # Read edit mode from session state (set by callback, not widget return value)
                is_edit_mode = st.session_state.get("map_edit_mode", False)
                
                if is_edit_mode:
                    # Edit mode: cycle tile type or paint hazard
                    cell = get_cell(grid, click_x, click_y)
                    if cell:
                        hazard_paint = st.session_state.get("map_hazard_paint", "None")
                        
                        if hazard_paint and hazard_paint != "None":
                            # Paint hazard on non-blocked tiles
                            tile = get_tile(cell["tile"])
                            if not tile.get("blocked", False):
                                set_cell_hazard(grid, click_x, click_y, hazard_paint)
                                hazard_info = get_hazard(hazard_paint)
                                st.toast(f"Hazard at ({click_x},{click_y}) → {hazard_info.get('name', hazard_paint)}")
                            else:
                                st.warning("Cannot place hazard on blocked tile!")
                        else:
                            # Cycle tile type using tiles.json ordering
                            tile_order = get_tile_ids()
                            current_idx = tile_order.index(cell["tile"]) if cell["tile"] in tile_order else 0
                            next_idx = (current_idx + 1) % len(tile_order)
                            next_tile_id = tile_order[next_idx]
                            set_cell_tile(grid, click_x, click_y, next_tile_id)
                            # Clear hazard when changing to blocked tile
                            next_tile = get_tile(next_tile_id)
                            if next_tile.get("blocked", False):
                                set_cell_hazard(grid, click_x, click_y, None)
                            st.toast(f"Tile at ({click_x},{click_y}) → {next_tile.get('name', next_tile_id)}")
                        
                        # Clear query params
                        st.query_params.clear()
                        st.rerun()
                else:
                    # Normal mode: select actor or move
                    clicked_kind, clicked_idx, clicked_actor = get_actor_at(click_x, click_y)
                    
                    if clicked_actor is not None:
                        # Clicked on an actor - select it
                        st.session_state.map_selected_actor = {"kind": clicked_kind, "idx": clicked_idx}
                        st.toast(f"Selected: {clicked_actor.get('name', 'Actor')}")
                        st.query_params.clear()
                        st.rerun()
                    elif st.session_state.map_selected_actor:
                        # Clicked on empty cell - try to move selected actor
                        sel = st.session_state.map_selected_actor
                        sel_kind = sel.get("kind")
                        sel_idx = sel.get("idx")
                        
                        if sel_kind == "party" and sel_idx < len(st.session_state.party):
                            actor = st.session_state.party[sel_idx]
                        elif sel_kind == "enemy" and sel_idx < len(st.session_state.enemies):
                            actor = st.session_state.enemies[sel_idx]
                        else:
                            actor = None
                        
                        if actor:
                            pos = actor.get("pos", {})
                            start_x, start_y = pos.get("x", 0), pos.get("y", 0)
                            # Use effective speed for party members (includes Fast Movement, etc.)
                            speed_ft = get_effective_speed(actor) if sel_kind == "party" else actor.get("speed_ft", 30)
                            square_size_ft = grid.get("square_size_ft", 5)
                            max_squares = speed_ft // square_size_ft
                            
                            # Check if destination is valid
                            if is_cell_blocked(grid, click_x, click_y):
                                st.warning(f"Cannot move to ({click_x},{click_y}) - blocked terrain!")
                            elif is_cell_occupied(click_x, click_y, actor):
                                st.warning(f"Cannot move to ({click_x},{click_y}) - occupied!")
                            else:
                                # In combat: check movement cost and spend move action
                                if st.session_state.in_combat:
                                    # Check if move action available
                                    if not can_spend("move"):
                                        st.warning("No move action available this turn!")
                                    else:
                                        path = find_path(grid, start_x, start_y, click_x, click_y, max_squares, actor)
                                        if path is None:
                                            st.warning(f"Cannot reach ({click_x},{click_y}) - too far or no valid path!")
                                        else:
                                            # Valid move - execute it
                                            spend("move")
                                            actor["pos"] = {"x": click_x, "y": click_y}
                                            
                                            # Calculate distance moved for Skirmish tracking
                                            distance_squares = len(path) - 1  # path includes start
                                            distance_ft = distance_squares * square_size_ft
                                            track_movement(distance_ft)
                                            
                                            # Check for Skirmish activation
                                            skirmish_msg = ""
                                            if actor.get("class") == "Scout" and is_skirmish_active():
                                                skirmish_dmg = actor.get("skirmish_damage", "1d6")
                                                skirmish_ac = actor.get("skirmish_ac_bonus", 1)
                                                skirmish_msg = f" **Skirmish active!** (+{skirmish_dmg} damage, +{skirmish_ac} AC)"
                                            
                                            st.toast(f"{actor.get('name', 'Actor')} moved to ({click_x},{click_y}) [{distance_ft} ft]{skirmish_msg}")
                                            st.session_state.chat_log.append(
                                                ("System", f"{actor.get('name', 'Actor')} moves to ({click_x},{click_y}) [{distance_ft} ft]{skirmish_msg}")
                                            )
                                else:
                                    # Out of combat: free movement (still check path exists)
                                    path = find_path(grid, start_x, start_y, click_x, click_y, 999, actor)
                                    if path is None:
                                        st.warning(f"Cannot reach ({click_x},{click_y}) - no valid path!")
                                    else:
                                        actor["pos"] = {"x": click_x, "y": click_y}
                                        st.toast(f"{actor.get('name', 'Actor')} moved to ({click_x},{click_y})")
                        
                        st.query_params.clear()
                        st.rerun()
                    else:
                        # Clicked on empty cell with no actor selected - just clear params
                        st.query_params.clear()
    except Exception as e:
        # Log error for debugging but don't crash
        import traceback
        traceback.print_exc()
        st.query_params.clear()  # Always clear params on error to prevent stuck state

    # Calculate reachable squares for selected actor
    reachable = None

    # Default to whatever the user clicked
    selected_actor = st.session_state.map_selected_actor

    # If in combat, force selection to the current turn owner (unless editing the map)
    if st.session_state.get("in_combat", False) and not st.session_state.get("map_edit_mode", False):
        turn = current_turn()  # expects {"kind": "...", "idx": ...} or None
        if turn and turn.get("kind") in ("party", "enemy") and turn.get("idx") is not None:
            forced = {"kind": turn["kind"], "idx": turn["idx"]}
            if selected_actor != forced:
                st.session_state.map_selected_actor = forced
            selected_actor = forced

    # Now compute reachable based on the active selected actor (forced in combat)
    if selected_actor and not st.session_state.get("map_edit_mode", False):
        sel_kind = selected_actor.get("kind")
        sel_idx = selected_actor.get("idx")

        actor = None
        if sel_kind == "party" and sel_idx < len(st.session_state.get("party", [])):
            actor = st.session_state.party[sel_idx]
        elif sel_kind == "enemy" and sel_idx < len(st.session_state.get("enemies", [])):
            actor = st.session_state.enemies[sel_idx]

        if actor:
            pos = actor.get("pos", {})
            if pos:
                # Use effective speed for party members (includes Fast Movement, etc.)
                speed_ft = get_effective_speed(actor) if sel_kind == "party" else actor.get("speed_ft", 30)
                square_size_ft = st.session_state.grid.get("square_size_ft", 5)
                max_squares = max(0, speed_ft // square_size_ft)
                reachable = dijkstra_reachable(st.session_state.grid, pos["x"], pos["y"], max_squares, actor)

    # Render the grid
    import streamlit.components.v1 as components

    grid_html = render_grid_html(
        st.session_state.grid,
        st.session_state.map_selected_actor,
        reachable,
        st.session_state.map_show_coords,
        st.session_state.map_edit_mode
    )

    # Display grid
    map_col, info_col = st.columns([3, 1])

    with map_col:
        components.html(grid_html, height=st.session_state.grid["height"] * 28 + 40, scrolling=True)

    with info_col:
        st.markdown("**Selected Actor**")
        if st.session_state.map_selected_actor:
            sel = st.session_state.map_selected_actor
            sel_kind = sel.get("kind")
            sel_idx = sel.get("idx")
            
            actor = None
            if sel_kind == "party" and sel_idx < len(st.session_state.get("party", [])):
                actor = st.session_state.party[sel_idx]
            elif sel_kind == "enemy" and sel_idx < len(st.session_state.get("enemies", [])):
                actor = st.session_state.enemies[sel_idx]
            
            if actor:
                st.write(f"**{actor.get('name', 'Unknown')}**")
                # Show effective speed for party members
                effective_spd = get_effective_speed(actor) if sel_kind == "party" else actor.get("speed_ft", 30)
                base_spd = actor.get("speed_ft", 30)
                if effective_spd != base_spd:
                    st.caption(f"Speed: {effective_spd} ft (base {base_spd} ft)")
                else:
                    st.caption(f"Speed: {effective_spd} ft")
                pos = actor.get("pos", {})
                st.caption(f"Position: ({pos.get('x', '?')}, {pos.get('y', '?')})")
                
                if st.button("Deselect", key="map_deselect"):
                    st.session_state.map_selected_actor = None
                    st.rerun()
        else:
            st.caption("Click an actor to select")
        
        st.markdown("---")
        st.markdown("**Legend**")
        tiles = load_tiles()
        for tile_id in get_tile_ids()[:4]:  # Show first 4 tiles in legend
            tile_info = tiles.get(tile_id, {})
            st.markdown(f"<span style='background:{tile_info.get('color', '#ccc')};padding:2px 6px;'>{tile_info.get('name', tile_id)}</span>", unsafe_allow_html=True)
        st.caption("🟠 = Hazard")
        
        if st.session_state.map_edit_mode:
            st.markdown("---")
            st.markdown("**Edit Mode**")
            st.caption("Click tiles to cycle type")
            
            # Hazard painter - show hazard names from hazards.json
            biome = get_biome_config(st.session_state.grid.get("biome", "Forest"))
            hazard_ids = biome.get("hazards", []) if biome else []
            hazards_data = load_hazards()
            # Build options with display names
            hazard_options = ["None"]
            hazard_id_map = {}
            for hid in hazard_ids:
                if hid in hazards_data:
                    h_name = hazards_data[hid].get("name", hid)
                    hazard_options.append(h_name)
                    hazard_id_map[h_name] = hid
            
            selected_hazard_name = st.selectbox("Paint Hazard", hazard_options, key="map_hazard_paint_name")
            
            # Store the hazard ID (not name) for painting
            if selected_hazard_name != "None":
                st.session_state.map_hazard_paint = hazard_id_map.get(selected_hazard_name, selected_hazard_name)
                hazard_info = hazards_data.get(st.session_state.map_hazard_paint, {})
                st.caption(f"Click tiles to add: {hazard_info.get('description', '')[:50]}...")
            else:
                st.session_state.map_hazard_paint = "None"

# ========== BOTTOM SECTION: DM Panel ==========
st.divider()

dm_notes_col, tools_col, refs_col = st.columns([4, 6, 4])

# ---- DM Notes (separate from chat) ----
with dm_notes_col:
    st.markdown("### 📝 DM Notes")
    st.text_area(
        "Private notes (not shown in chat)",
        key="dm_notes",
        height=150,
        placeholder="Use this area for:\n• Session planning\n• NPC motivations\n• Plot hooks\n• Secret information"
    )
    

with tools_col:
    st.markdown("### 🧰 Tools")
    # Party XP Award section
    with st.expander("🎁 Award Party XP", expanded=False):
        st.caption("Award XP to all party members at once")
        
        # Show party XP summary
        if st.session_state.party:
            party_levels = []
            pending_levelups = []
            for char in st.session_state.party:
                migrate_character_xp(char)
                migrate_to_multiclass(char)
                char_name = char.get("name", "?")
                char_level = get_total_level(char)
                char_xp = char.get("xp_current", 0)
                party_levels.append(f"{char_name} (Lv{char_level})")
                if char.get("level_up_pending"):
                    pending_levelups.append(char_name)
            
            st.caption(f"Party: {', '.join(party_levels)}")
            if pending_levelups:
                st.warning(f"⬆️ Pending level ups: {', '.join(pending_levelups)}")
        
        # XP Amount
        party_xp_amt = st.number_input(
            "XP per member",
            min_value=0,
            value=0,
            step=100,
            key="party_xp_award_amt",
            help="Each party member receives this amount"
        )
        
        # Source and Reason
        party_src_col, party_reason_col = st.columns([1, 2])
        with party_src_col:
            party_xp_source = st.selectbox(
                "Source",
                ["quest", "milestone", "combat", "roleplay", "dm_award"],
                format_func=lambda x: {
                    "quest": "📜 Quest",
                    "milestone": "🏆 Milestone",
                    "combat": "⚔️ Combat",
                    "roleplay": "🎭 Roleplay",
                    "dm_award": "👑 DM Award"
                }.get(x, x),
                key="party_xp_award_src"
            )
        with party_reason_col:
            party_xp_reason = st.text_input(
                "Reason",
                placeholder="e.g., Completed the main quest",
                key="party_xp_award_reason",
                label_visibility="collapsed"
            )
        
        # Calculate total XP being awarded
        total_party_xp = party_xp_amt * len(st.session_state.party) if st.session_state.party else 0
        if party_xp_amt > 0 and st.session_state.party:
            st.caption(f"Total XP: {total_party_xp:,} ({party_xp_amt:,} × {len(st.session_state.party)} members)")
        
        if st.button("Award to All Party Members", key="party_xp_award_btn", disabled=party_xp_amt <= 0 or not st.session_state.party, use_container_width=True):
            level_ups = []
            for char in st.session_state.party:
                migrate_character_xp(char)
                result = award_xp(char, party_xp_amt, reason=party_xp_reason or party_xp_source.capitalize(), source=party_xp_source)
                if result["leveled_up"]:
                    level_ups.append(char.get("name", "Character"))
            
            if level_ups:
                st.toast(f"🎉 Awarded {party_xp_amt:,} XP! Level ups available: {', '.join(level_ups)}")
            else:
                st.toast(f"✨ Awarded {party_xp_amt:,} XP to each party member!")
            st.rerun()

    # Quick Add Enemy (in left column)
    with st.expander("➕ Quick Add Enemy", expanded=False):
        add_mode = st.radio("Add Mode", ["From SRD", "Manual"], horizontal=True, key="left_add_mode")
        
        if add_mode == "From SRD":
            if not st.session_state.get("srd_enemies"):
                st.warning("SRD bestiary not loaded.")
            else:
                srd_names = [m["name"] for m in st.session_state.srd_enemies]
                srd_pick = st.selectbox("Monster", srd_names, key="left_srd_pick")
                srd_qty = st.number_input("Quantity", 1, 10, 1, key="left_srd_qty")
                if st.button("Add", key="left_add_srd_btn"):
                    src = next((m for m in st.session_state.srd_enemies if m["name"] == srd_pick), None)
                    if src:
                        for i in range(int(srd_qty)):
                            blob = json.loads(json.dumps(src))
                            blob["name"] = f"{src['name']}" if srd_qty == 1 else f"{src['name']} #{i+1}"
                            blob["src"] = src["name"]
                            blob["_hydrated"] = True
                            st.session_state.enemies.append(blob)
                        st.toast(f"Added {srd_qty}× {srd_pick}")
                        st.rerun()
        else:
            e_name = st.text_input("Name", key="left_e_name")
            e_ac = st.number_input("AC", 0, 40, 13, key="left_e_ac")
            e_hp = st.number_input("HP", 0, 500, 11, key="left_e_hp")
            if st.button("Add", key="left_add_manual_btn"):
                if e_name.strip():
                    st.session_state.enemies.append({
                        "name": e_name.strip(),
                        "ac": int(e_ac),
                        "hp": int(e_hp),
                        "attacks": [{"name": "Attack", "to_hit": 0, "damage": "1d6"}]
                    })
                    st.toast(f"Added {e_name}")
                    st.rerun()

    # ========== ENCOUNTER XP CALCULATOR ==========
    with st.expander("🧮 Encounter XP Calculator", expanded=False):
        if not st.session_state.enemies:
            st.info("Add enemies to calculate encounter XP.")
        else:
            # Get party levels
            party_levels = []
            for char in st.session_state.party:
                migrate_character_xp(char)
                migrate_to_multiclass(char)
                party_levels.append(get_total_level(char))
            
            party_size = len(party_levels) if party_levels else 4
            
            # Calculate encounter XP
            encounter_result = calc_encounter_xp(
                st.session_state.enemies, 
                party_size=party_size,
                apply_multiplier=True
            )
            
            # Assess difficulty
            if party_levels:
                difficulty_result = assess_encounter_difficulty(
                    st.session_state.enemies,
                    party_levels
                )
                difficulty = difficulty_result["difficulty"]
                difficulty_emoji = get_difficulty_emoji(difficulty)
            else:
                difficulty = "unknown"
                difficulty_emoji = "❓"
                difficulty_result = {"thresholds": {}}
            
            # Display encounter summary
            st.markdown(f"### {difficulty_emoji} {difficulty.capitalize()} Encounter")
            
            # XP metrics
            xp_col1, xp_col2, xp_col3 = st.columns(3)
            with xp_col1:
                st.metric("Base XP", format_xp(encounter_result["base_xp"]))
            with xp_col2:
                st.metric("Adjusted XP", format_xp(encounter_result["adjusted_xp"]), 
                         help=f"×{encounter_result['multiplier']:.1f} multiplier for {encounter_result['monster_count']} monsters")
            with xp_col3:
                st.metric("XP per Member", format_xp(encounter_result["xp_per_member"]))
            
            # Monster breakdown
            st.markdown("**Monster Breakdown:**")
            for mon in encounter_result["monsters_breakdown"]:
                st.caption(f"  • {mon['name']}: {format_xp(mon['xp'])} XP")
            
            # Difficulty thresholds
            if party_levels and difficulty_result.get("thresholds"):
                thresholds = difficulty_result["thresholds"]
                st.markdown("**Party Difficulty Thresholds:**")
                threshold_text = f"Easy: {format_xp(thresholds.get('easy', 0))} | Medium: {format_xp(thresholds.get('medium', 0))} | Hard: {format_xp(thresholds.get('hard', 0))} | Deadly: {format_xp(thresholds.get('deadly', 0))}"
                st.caption(threshold_text)
            
            # Award XP button
            st.markdown("---")
            st.markdown("**Award Encounter XP to Party**")
            
            xp_to_award = encounter_result["xp_per_member"]
            st.caption(f"Each party member will receive {format_xp(xp_to_award)} XP")
            
            if st.button("🎁 Award Encounter XP", key="award_encounter_xp_btn", disabled=xp_to_award <= 0 or not st.session_state.party, use_container_width=True):
                level_ups = []
                enemy_names = [e.get("name", "Enemy") for e in st.session_state.enemies]
                reason = f"Defeated: {', '.join(enemy_names[:3])}" + ("..." if len(enemy_names) > 3 else "")
                
                for char in st.session_state.party:
                    migrate_character_xp(char)
                    result = award_xp(char, xp_to_award, reason=reason, source="combat")
                    if result["leveled_up"]:
                        level_ups.append(char.get("name", "Character"))
                
                if level_ups:
                    st.toast(f"🎉 Awarded {format_xp(xp_to_award)} XP each! Level ups: {', '.join(level_ups)}")
                else:
                    st.toast(f"✨ Awarded {format_xp(xp_to_award)} XP to each party member!")
                st.rerun()
    
    # ========== QUEST/MILESTONE XP ==========
    with st.expander("🏆 Quest & Milestone XP", expanded=False):
        st.markdown("Award XP for completing quests or reaching milestones.")
        
        # Get party info
        party_levels = []
        for char in st.session_state.party:
            migrate_character_xp(char)
            migrate_to_multiclass(char)
            party_levels.append(get_total_level(char))
        
        if not party_levels:
            party_levels = [1]  # Default for calculation preview
            st.caption("No party members - using level 1 for preview")
        
        # Quest type selection
        quest_types = get_quest_types()
        quest_options = {
            "minor": "📝 Minor (Simple task, fetch quest)",
            "moderate": "📋 Moderate (Multi-step quest, some danger)",
            "major": "📜 Major (Significant story quest)",
            "epic": "🏆 Epic (Campaign-defining quest)"
        }
        
        selected_quest = st.selectbox(
            "Quest Type",
            list(quest_options.keys()),
            format_func=lambda x: quest_options.get(x, x),
            key="quest_type_select"
        )
        
        # Custom multiplier
        custom_mult = st.slider(
            "XP Multiplier",
            min_value=0.5,
            max_value=2.0,
            value=1.0,
            step=0.1,
            key="quest_xp_mult",
            help="Adjust XP based on quest difficulty or party performance"
        )
        
        # Calculate quest XP
        quest_result = calc_quest_xp(selected_quest, party_levels, custom_mult)
        
        # Display
        quest_col1, quest_col2 = st.columns(2)
        with quest_col1:
            st.metric("Total Quest XP", format_xp(quest_result["total_xp"]))
        with quest_col2:
            st.metric("XP per Member", format_xp(quest_result["xp_per_member"]))
        
        st.caption(f"Based on party of {quest_result.get('party_size', len(party_levels))} at average level {quest_result.get('avg_party_level', 1):.1f}")
        
        # Reason input
        quest_reason = st.text_input(
            "Quest Description",
            placeholder="e.g., Rescued the village elder",
            key="quest_reason_input"
        )
        
        # Award button
        xp_to_award = quest_result["xp_per_member"]
        if st.button("🎁 Award Quest XP", key="award_quest_xp_btn", disabled=xp_to_award <= 0 or not st.session_state.party, use_container_width=True):
            level_ups = []
            reason = quest_reason or f"{selected_quest.capitalize()} quest completed"
            
            for char in st.session_state.party:
                migrate_character_xp(char)
                result = award_xp(char, xp_to_award, reason=reason, source="quest")
                if result["leveled_up"]:
                    level_ups.append(char.get("name", "Character"))
            
            if level_ups:
                st.toast(f"🎉 Awarded {format_xp(xp_to_award)} XP each! Level ups: {', '.join(level_ups)}")
            else:
                st.toast(f"✨ Awarded {format_xp(xp_to_award)} XP to each party member!")
            st.rerun()
                  
# ========== Bestiary Reference ==========
with refs_col:
    st.markdown("### 📖 Reference")

    with st.expander("🐉 Browse Bestiary", expanded=False):
        if not st.session_state.get("srd_enemies"):
            st.info("📚 SRD Bestiary not loaded. Check that SRD_Monsters.json exists in the data folder.")
        else:
            names = [m["name"] for m in st.session_state.srd_enemies]
            pick = st.selectbox("View statblock", names, key="bestiary_pick")
            sb = next((m for m in st.session_state.srd_enemies if m["name"] == pick), None)
            if sb:
                    # Tolerant full stat renderer
                    name = sb.get("name","Unknown")
                    size = sb.get("size","—"); typ = sb.get("type","—"); ali = sb.get("alignment","—")
                    ac = sb.get("ac","—"); hp = sb.get("hp","—"); hd = sb.get("hit_dice","—"); spd = sb.get("speed","—")
                    st.markdown(f"**{name}** — {size} {typ}, {ali}")
                    st.markdown(f"**Armor Class** {ac}  •  **Hit Points** {hp} ({hd})  •  **Speed** {spd}")

                    abil = sb.get("abilities", {})
                    if abil:
                        STR = abil.get("STR","—"); DEX = abil.get("DEX","—"); CON = abil.get("CON","—")
                        INT = abil.get("INT","—"); WIS = abil.get("WIS","—"); CHA = abil.get("CHA","—")
                        st.markdown(f"STR {STR}  |  DEX {DEX}  |  CON {CON}  |  INT {INT}  |  WIS {WIS}  |  CHA {CHA}")

                    saves = sb.get("saves", {}); skills = sb.get("skills", {})
                    s_saves  = ", ".join(f"{k} {v}" for k,v in saves.items()) if saves else "—"
                    s_skills = ", ".join(f"{k} {v}" for k,v in skills.items()) if skills else "—"
                    senses = sb.get("senses","—"); langs = sb.get("languages","—"); cr = sb.get("cr","—")
                    st.caption(f"Saves: {s_saves}  •  Skills: {s_skills}")
                    st.caption(f"Senses: {senses}  •  Languages: {langs}  •  CR: {cr}")

                    traits = sb.get("traits", [])
                    if traits:
                        with st.expander("Traits"):
                            for t in traits:
                                tname = t.get("name","Trait"); ttxt = t.get("text","")
                                st.markdown(f"- **{tname}.** {ttxt}")

                    actions = sb.get("actions", [])
                    if actions:
                        with st.expander("Actions"):
                            for a in actions:
                                nm = a.get("name","Action")
                                th = a.get("to_hit")
                                reach = a.get("reach"); rng = a.get("range")
                                targets = a.get("targets","one")
                                dmg = a.get("damage","—")
                                line = f"**{nm}.**"
                                if th is not None: line += f" +{th} to hit"
                                if reach: line += f", reach {reach}"
                                if rng:   line += f", range {rng}"
                                line += f"; {targets} target. Hit: {dmg}."
                                st.markdown(f"- {line}")

    # ---------------- Performance Debug: Display Timings ----------------
    if st.session_state.get("perf_debug", False):
        timings = get_perf_timings()
        placeholder = st.session_state.get("_perf_timing_placeholder")
        if placeholder and timings:
            with placeholder.container():
                for name, ms in sorted(timings.items(), key=lambda x: -x[1]):
                    st.caption(f"⏱️ {name}: {ms:.2f} ms")
