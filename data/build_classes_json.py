import os
import json
from copy import deepcopy

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

CLASS_INFO_DIR = r"C:\Users\Broke\OneDrive\Desktop\AIDM\AI-DM\data\ClassInfo"
OUTPUT_JSON_PATH = r"C:\Users\Broke\OneDrive\Desktop\AIDM\AI-DM\data\SRD_Classes.json"


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def make_empty_levels():
    """Create the 1–20 level structure with your desired fields."""
    level_template = {
        "features_at_level": [],
        "resource_changes": "",
        "spell_slots_by_level": {},  # e.g. {"1": 4, "2": 3}
        "cantrips_known": 0,
        "spells_known": 0,
        "spells_prepared": 0,
        "asi_or_feat": "",
        "subclass_features": "",
        "scaling_changes": ""
    }
    return {str(lvl): deepcopy(level_template) for lvl in range(1, 21)}


def split_list_field(value: str):
    """Turn 'Dexterity, Intelligence' into ['Dexterity', 'Intelligence']."""
    if not value:
        return []
    parts = []
    # Normalize ' and ' to comma separation as well
    for chunk in value.replace(" and ", ",").split(","):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts


def clean_prof_item(item: str) -> str:
    """Clean up proficiency tokens like 'plus the longsword', 'and whip.' -> 'whip'."""
    item = item.strip()
    # Strip trailing periods
    if item.endswith("."):
        item = item[:-1]

    lower = item.lower()
    for prefix in ("plus the ", "plus ", "and ", "the "):
        if lower.startswith(prefix):
            item = item[len(prefix):]
            break

    return item.strip()


# ---------------------------------------------------------
# Bard-specific progression (features + spellcasting)
# ---------------------------------------------------------

def apply_bard_progression(class_data: dict) -> None:
    """
    Populate Bard levels with:
      - features_at_level
      - scaling_changes (Performance Die upgrades)
      - cantrips_known
      - spells_known
      - spell_slots_by_level
    based on the Bard tables provided.
    """
    if class_data.get("name", "").lower() != "bard":
        return

    levels = class_data["levels"]

    # Features by level (from your Bard Features table)
    bard_features_by_level = {
        1: ["Spellcasting", "Bardic Knowledge", "Bardic Performance"],
        2: [],
        3: ["Sonic Conductor"],
        4: ["Inspire Magic"],
        5: ["Charming Melody"],
        6: ["Magical Secrets"],
        7: ["Counterperformance"],
        8: [],
        9: ["Echoing Song"],
        10: ["Improved Bardic Performance"],
        11: [],
        12: ["Magical Secrets"],
        13: [],
        14: ["Bardic Mastery"],
        15: ["Melodic Resilience"],
        16: [],
        17: [],
        18: ["Magical Secrets"],
        19: [],
        20: ["Final Flourish"],
    }

    # Performance Die by level
    bard_perf_die = {}
    for lvl in range(1, 21):
        if lvl <= 4:
            bard_perf_die[lvl] = "D6"
        elif lvl <= 9:
            bard_perf_die[lvl] = "D8"
        elif lvl <= 14:
            bard_perf_die[lvl] = "D10"
        else:
            bard_perf_die[lvl] = "D12"

    # Spell progression table (Level / Cantrips / Spells Known / 1st–9th slots)
    bard_spells = {
        1:  {"cantrips": 2, "known": 4,  "slots": {"1": 2}},
        2:  {"cantrips": 2, "known": 5,  "slots": {"1": 2}},
        3:  {"cantrips": 2, "known": 6,  "slots": {"1": 3, "2": 2}},
        4:  {"cantrips": 3, "known": 7,  "slots": {"1": 3, "2": 2}},
        5:  {"cantrips": 3, "known": 8,  "slots": {"1": 4, "2": 3, "3": 1}},
        6:  {"cantrips": 3, "known": 9,  "slots": {"1": 4, "2": 3, "3": 1}},
        7:  {"cantrips": 3, "known": 10, "slots": {"1": 4, "2": 3, "3": 2, "4": 1}},
        8:  {"cantrips": 3, "known": 11, "slots": {"1": 4, "2": 3, "3": 2, "4": 1}},
        9:  {"cantrips": 3, "known": 12, "slots": {"1": 4, "2": 3, "3": 3, "4": 2, "5": 1}},
        10: {"cantrips": 3, "known": 13, "slots": {"1": 4, "2": 3, "3": 3, "4": 2, "5": 1}},
        11: {"cantrips": 3, "known": 14, "slots": {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1}},
        12: {"cantrips": 3, "known": 15, "slots": {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1}},
        13: {"cantrips": 3, "known": 16, "slots": {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 2, "7": 1}},
        14: {"cantrips": 3, "known": 17, "slots": {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 2, "7": 1}},
        15: {"cantrips": 3, "known": 18, "slots": {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 3, "7": 1, "8": 1}},
        16: {"cantrips": 3, "known": 19, "slots": {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 3, "7": 1, "8": 1}},
        17: {"cantrips": 4, "known": 20, "slots": {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 3, "7": 1, "8": 1, "9": 1}},
        18: {"cantrips": 4, "known": 21, "slots": {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 3, "7": 1, "8": 1, "9": 1}},
        19: {"cantrips": 4, "known": 22, "slots": {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 3, "7": 2, "8": 1, "9": 1}},
        20: {"cantrips": 4, "known": 24, "slots": {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 3, "7": 2, "8": 1, "9": 1}},
    }

    # Fill in the data
    prev_die = None
    for lvl in range(1, 21):
        lvl_str = str(lvl)
        entry = levels[lvl_str]

        # Features at this level
        feats = bard_features_by_level.get(lvl, [])
        entry["features_at_level"].extend(feats)

        # Performance Die scaling
        die = bard_perf_die.get(lvl)
        if die is not None:
            if prev_die is not None and die != prev_die:
                # Only record when it changes from the last die
                if entry["scaling_changes"]:
                    entry["scaling_changes"] += "; "
                entry["scaling_changes"] += f"Performance Die becomes {die}"
            prev_die = die

        # Spellcasting progression
        if lvl in bard_spells:
            sdata = bard_spells[lvl]
            entry["cantrips_known"] = sdata["cantrips"]
            entry["spells_known"] = sdata["known"]
            entry["spell_slots_by_level"] = {
                str(k): v for k, v in sdata["slots"].items()
            }

    # Bard-specific meta fields
    class_data["resource_type"] = "Bardic Performance"
    # Bard is a full caster in your system
    if not class_data.get("caster_type"):
        class_data["caster_type"] = "full"


# ---------------------------------------------------------
# Parsing of a single class file (header section)
# ---------------------------------------------------------

def parse_class_file(path: str) -> dict:
    # Try UTF-8 first, then fall back to Windows-1252 (cp1252) with replacement
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="cp1252", errors="replace") as f:
            raw = f.read()

    # Normalize Windows line endings
    raw = raw.replace("\r", "\n")

    # Strip lines & drop empty ones
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]

    # ----------------------------------------------
    # Basic info
    # ----------------------------------------------
    name = lines[0]  # First line should be class name (e.g. "Bard")
    role = ""
    hit_die = ""

    armor = ""
    weapons = ""
    tools = ""
    skills = ""
    spellcasting_ability = ""

    primary_stat = ""
    secondary_stat = ""
    caster_prog = ""
    bab_progression = ""
    skill_points_per_level = ""

    for ln in lines:
        if ln.startswith("Role:"):
            role = ln.split(":", 1)[1].strip()

        # Hit Dice line under Hit Points
        if ln.startswith("* Hit Dice:"):
            hit_die = ln.split(":", 1)[1].strip()

        # Proficiencies
        if ln.startswith("* Armor:"):
            armor = ln.split(":", 1)[1].strip()
        if ln.startswith("* Weapons:"):
            weapons = ln.split(":", 1)[1].strip()
        if ln.startswith("* Tools:"):
            tools = ln.split(":", 1)[1].strip()
        if ln.startswith("* Base Attack Bonus:"):
            bab_progression = ln.split(":", 1)[1].strip()
        if ln.startswith("* Caster Progression:"):
            caster_prog = ln.split(":", 1)[1].strip()
        if ln.startswith("* Skill Points per Level:"):
            skill_points_per_level = ln.split(":", 1)[1].strip()

        # Primary / Secondary stats for the class
        if ln.startswith("* Primary Stat:"):
            primary_stat = ln.split(":", 1)[1].strip()
        if ln.startswith("* Secondary Stat:"):
            secondary_stat = ln.split(":", 1)[1].strip()

        # Skills
        if ln.startswith("* Skills:"):
            skills = ln.split(":", 1)[1].strip()

        # Spellcasting Ability
        if ln.startswith("* Spellcasting Ability:"):
            spellcasting_ability = ln.split(":", 1)[1].strip()

    # Split raw strings into lists
    armor_list = [clean_prof_item(x) for x in split_list_field(armor)]
    weapon_list = [clean_prof_item(x) for x in split_list_field(weapons)]

    # Tools: special-case the "Three musical instruments..." line
    tool_list = []
    if tools:
        if tools.lower().startswith("three musical instruments"):
            tool_list = ["Three musical instruments of your choice"]
        else:
            tool_list = [clean_prof_item(x) for x in split_list_field(tools)]

    skill_list = split_list_field(skills)

    # Combine primary + secondary stats into primary_abilities list
    primary_list = split_list_field(primary_stat)
    secondary_list = split_list_field(secondary_stat)

    # Deduplicate while preserving order
    seen = set()
    primary_abilities = []
    for stat in primary_list + secondary_list:
        if stat not in seen:
            seen.add(stat)
            primary_abilities.append(stat)

    # Derive caster_type from caster_prog if possible
    caster_type = ""
    if caster_prog:
        lower = caster_prog.lower()
        if "full" in lower:
            caster_type = "full"
        elif "half" in lower:
            caster_type = "half"
        elif "third" in lower or "1/3" in lower:
            caster_type = "third"

    # ----------------------------------------------
    # Initialize class JSON structure
    # ----------------------------------------------
    class_data = {
        "name": name,
        "role": role,
        "hit_die": hit_die,              # e.g. "d6 per Bard level"
        "primary_abilities": primary_abilities,
        # Not using saving throws in this system right now
        "saving_throws": [],
        "armor_proficiencies": armor_list,
        "weapon_proficiencies": weapon_list,
        "tool_proficiencies": tool_list,
        "skill_list": skill_list,
        "skill_choices": [],             # not defined in the text yet
        "caster_type": caster_type,
        "spellcasting_ability": spellcasting_ability,
        "subclass_name": "",
        "subclass_level": "",
        "resource_type": "",             # may be set by class-specific logic
        "levels": make_empty_levels(),
        # Bonus meta fields (useful for your hybrid system)
        "base_attack_bonus": bab_progression,
        "skill_points_per_level": skill_points_per_level,
    }

    # Apply any class-specific progressions (right now only Bard is defined)
    apply_bard_progression(class_data)

    return class_data


# ---------------------------------------------------------
# Main: process all class files in ClassInfo
# ---------------------------------------------------------

def main():
    if not os.path.isdir(CLASS_INFO_DIR):
        raise FileNotFoundError(f"ClassInfo folder not found: {CLASS_INFO_DIR}")

    class_files = [
        os.path.join(CLASS_INFO_DIR, f)
        for f in os.listdir(CLASS_INFO_DIR)
        if f.lower().endswith(".txt")
    ]

    classes = []
    for path in class_files:
        try:
            class_data = parse_class_file(path)
            classes.append(class_data)
            print(f"Parsed class from: {os.path.basename(path)} (name: {class_data['name']})")
        except Exception as e:
            print(f"Error parsing {path}: {e}")

    output = {"classes": classes}

    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\nWrote {len(classes)} classes to {OUTPUT_JSON_PATH}")


if __name__ == "__main__":
    main()