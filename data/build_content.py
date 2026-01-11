"""
Unified Content Builder for AI-DM

Converts text files into JSON for:
- Classes (from ClassInfo/*.txt)
- Races (from RaceInfo/*.txt) 
- Spells (from SpellInfo/*.txt)

Usage:
    python build_content.py --classes    # Build classes only
    python build_content.py --races      # Build races only
    python build_content.py --spells     # Build spells only
    python build_content.py --all        # Build everything
"""

import os
import json
import re
import argparse
from copy import deepcopy
from pathlib import Path

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

DATA_DIR = Path(__file__).parent
CLASS_INFO_DIR = DATA_DIR / "ClassInfo"
RACE_INFO_DIR = DATA_DIR / "RaceInfo"
SPELL_INFO_DIR = DATA_DIR / "SpellInfo"

OUTPUT_CLASSES = DATA_DIR / "SRD_Classes.json"
OUTPUT_RACES = DATA_DIR / "SRD_Races.json"
OUTPUT_SPELLS = DATA_DIR / "SRD_Spells.json"


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def read_file_safe(path: str) -> str:
    """Read file with encoding fallback."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="cp1252", errors="replace") as f:
            return f.read()


def split_list_field(value: str) -> list:
    """Turn 'Dexterity, Intelligence' into ['Dexterity', 'Intelligence']."""
    if not value:
        return []
    parts = []
    for chunk in value.replace(" and ", ",").split(","):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts


def clean_item(item: str) -> str:
    """Clean up tokens."""
    item = item.strip()
    if item.endswith("."):
        item = item[:-1]
    lower = item.lower()
    for prefix in ("plus the ", "plus ", "and ", "the "):
        if lower.startswith(prefix):
            item = item[len(prefix):]
            break
    return item.strip()


def parse_key_value_line(line: str, prefix: str) -> str:
    """Extract value from '* Key: Value' format."""
    if line.startswith(prefix):
        return line.split(":", 1)[1].strip() if ":" in line else ""
    return None


# ---------------------------------------------------------
# CLASS BUILDING
# ---------------------------------------------------------

def make_empty_levels():
    """Create the 1-20 level structure."""
    level_template = {
        "features_at_level": [],
        "resource_changes": "",
        "spell_slots_by_level": {},
        "cantrips_known": 0,
        "spells_known": 0,
        "spells_prepared": 0,
        "asi_or_feat": "",
        "subclass_features": "",
        "scaling_changes": ""
    }
    return {str(lvl): deepcopy(level_template) for lvl in range(1, 21)}


# Standard spell slot progression tables
FULL_CASTER_SLOTS = {
    1:  {"1": 2},
    2:  {"1": 3},
    3:  {"1": 4, "2": 2},
    4:  {"1": 4, "2": 3},
    5:  {"1": 4, "2": 3, "3": 2},
    6:  {"1": 4, "2": 3, "3": 3},
    7:  {"1": 4, "2": 3, "3": 3, "4": 1},
    8:  {"1": 4, "2": 3, "3": 3, "4": 2},
    9:  {"1": 4, "2": 3, "3": 3, "4": 3, "5": 1},
    10: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2},
    11: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1},
    12: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1},
    13: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1},
    14: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1},
    15: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1, "8": 1},
    16: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1, "8": 1},
    17: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1, "8": 1, "9": 1},
    18: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 1, "7": 1, "8": 1, "9": 1},
    19: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 2, "7": 1, "8": 1, "9": 1},
    20: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 2, "7": 2, "8": 1, "9": 1},
}

HALF_CASTER_SLOTS = {
    2:  {"1": 2},
    3:  {"1": 3},
    4:  {"1": 3},
    5:  {"1": 4, "2": 2},
    6:  {"1": 4, "2": 2},
    7:  {"1": 4, "2": 3},
    8:  {"1": 4, "2": 3},
    9:  {"1": 4, "2": 3, "3": 2},
    10: {"1": 4, "2": 3, "3": 2},
    11: {"1": 4, "2": 3, "3": 3},
    12: {"1": 4, "2": 3, "3": 3},
    13: {"1": 4, "2": 3, "3": 3, "4": 1},
    14: {"1": 4, "2": 3, "3": 3, "4": 1},
    15: {"1": 4, "2": 3, "3": 3, "4": 2},
    16: {"1": 4, "2": 3, "3": 3, "4": 2},
    17: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 1},
    18: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 1},
    19: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2},
    20: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2},
}


def normalize_bab(bab_raw: str) -> str:
    """Normalize BAB string to standard format."""
    bab_raw = bab_raw.lower().strip()
    if "full" in bab_raw or bab_raw == "1":
        return "full"
    elif "¾" in bab_raw or "3/4" in bab_raw or "three-fourth" in bab_raw or "three-quarter" in bab_raw:
        return "3/4"
    elif "½" in bab_raw or "1/2" in bab_raw or "half" in bab_raw:
        return "1/2"
    elif "¼" in bab_raw or "1/4" in bab_raw or "one-fourth" in bab_raw or "quarter" in bab_raw:
        return "1/4"
    return bab_raw


def parse_class_file(path: str) -> dict:
    """Parse a class text file into JSON structure."""
    raw = read_file_safe(path).replace("\r", "\n")
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    
    # Basic info - handle "Class: Wizard" format
    name = lines[0] if lines else "Unknown"
    if name.lower().startswith("class:"):
        name = name.split(":", 1)[1].strip()
    
    class_data = {
        "name": name,
        "role": "",
        "hit_die": "",
        "primary_abilities": [],
        "saving_throws": [],
        "armor_proficiencies": [],
        "weapon_proficiencies": [],
        "tool_proficiencies": [],
        "skill_list": [],
        "skill_choices": [],
        "caster_type": "",
        "spellcasting_ability": "",
        "subclass_name": "",
        "subclass_level": "",
        "resource_type": "",
        "levels": make_empty_levels(),
        "base_attack_bonus": "",
        "skill_points_per_level": "",
    }
    
    for ln in lines:
        ln_lower = ln.lower()
        
        # Role
        if ln.startswith("Role:"):
            class_data["role"] = ln.split(":", 1)[1].strip()
        
        # Hit Dice - multiple formats
        elif "hit dice:" in ln_lower or "hit die:" in ln_lower:
            val = ln.split(":", 1)[1].strip()
            # Extract just the die (e.g., "d10 per Fighter level" -> "d10")
            match = re.search(r'd\d+', val)
            if match:
                class_data["hit_die"] = match.group(0)
            else:
                class_data["hit_die"] = val
        
        # Armor proficiencies
        elif ln_lower.startswith("- armor:") or ln_lower.startswith("* armor:") or ln_lower.startswith("armor:"):
            class_data["armor_proficiencies"] = [clean_item(x) for x in split_list_field(ln.split(":", 1)[1])]
        
        # Weapon proficiencies
        elif ln_lower.startswith("- weapons:") or ln_lower.startswith("* weapons:") or ln_lower.startswith("weapons:"):
            class_data["weapon_proficiencies"] = [clean_item(x) for x in split_list_field(ln.split(":", 1)[1])]
        
        # Tool proficiencies
        elif ln_lower.startswith("- tools:") or ln_lower.startswith("* tools:") or ln_lower.startswith("tools:"):
            class_data["tool_proficiencies"] = [clean_item(x) for x in split_list_field(ln.split(":", 1)[1])]
        
        # Skills
        elif ln_lower.startswith("- skills:") or ln_lower.startswith("* skills:") or ln_lower.startswith("skills:"):
            if "class skills:" not in ln_lower:
                class_data["skill_list"] = split_list_field(ln.split(":", 1)[1])
        elif "class skills:" in ln_lower:
            class_data["skill_list"] = split_list_field(ln.split(":", 1)[1])
        
        # Primary Stats / Saving Throws (used for determining good saves)
        elif "primary stat" in ln_lower:
            class_data["primary_abilities"] = split_list_field(ln.split(":", 1)[1])
        elif "saving throws:" in ln_lower and "primary" not in class_data.get("primary_abilities", []):
            class_data["primary_abilities"] = split_list_field(ln.split(":", 1)[1])
        
        # Spellcasting Ability
        elif "spellcasting ability:" in ln_lower:
            class_data["spellcasting_ability"] = ln.split(":", 1)[1].strip()
        
        # Caster Progression
        elif "caster progression:" in ln_lower:
            prog = ln.split(":", 1)[1].strip().lower()
            if "full" in prog:
                class_data["caster_type"] = "full"
            elif "half" in prog:
                class_data["caster_type"] = "half"
            elif "third" in prog:
                class_data["caster_type"] = "third"
        
        # Base Attack Bonus
        elif "base attack bonus" in ln_lower and ":" in ln:
            parts = ln.split(":", 1)
            if len(parts) > 1:
                bab_raw = parts[1].strip()
                class_data["base_attack_bonus"] = normalize_bab(bab_raw)
        
        # Skill Points per Level
        elif "skill points per level:" in ln_lower:
            class_data["skill_points_per_level"] = ln.split(":", 1)[1].strip()
    
    # Detect spellcasting from features if not explicitly set
    raw_lower = raw.lower()
    if not class_data["caster_type"]:
        if "spellcasting" in raw_lower:
            # Check for clues about caster type
            if "wizard" in name.lower() or "sorcerer" in name.lower() or "cleric" in name.lower() or "druid" in name.lower() or "bard" in name.lower():
                class_data["caster_type"] = "full"
            elif "paladin" in name.lower() or "ranger" in name.lower():
                class_data["caster_type"] = "half"
            elif "warlock" in name.lower():
                class_data["caster_type"] = "pact"  # Special pact magic
    
    # Detect spellcasting ability if not set
    if not class_data["spellcasting_ability"] and class_data["caster_type"]:
        if "intelligence" in raw_lower and ("wizard" in name.lower() or "artificer" in name.lower()):
            class_data["spellcasting_ability"] = "Intelligence"
        elif "charisma" in raw_lower and ("sorcerer" in name.lower() or "bard" in name.lower() or "paladin" in name.lower() or "warlock" in name.lower()):
            class_data["spellcasting_ability"] = "Charisma"
        elif "wisdom" in raw_lower and ("cleric" in name.lower() or "druid" in name.lower() or "ranger" in name.lower()):
            class_data["spellcasting_ability"] = "Wisdom"
    
    # Apply spell slots based on caster type
    if class_data["caster_type"] == "full":
        for lvl, slots in FULL_CASTER_SLOTS.items():
            class_data["levels"][str(lvl)]["spell_slots_by_level"] = slots.copy()
    elif class_data["caster_type"] == "half":
        for lvl, slots in HALF_CASTER_SLOTS.items():
            class_data["levels"][str(lvl)]["spell_slots_by_level"] = slots.copy()
    
    return class_data


def build_classes():
    """Build all classes from text files."""
    if not CLASS_INFO_DIR.exists():
        print(f"Creating {CLASS_INFO_DIR}...")
        CLASS_INFO_DIR.mkdir(exist_ok=True)
        return []
    
    class_files = list(CLASS_INFO_DIR.glob("*.txt"))
    classes = []
    
    for path in class_files:
        try:
            class_data = parse_class_file(str(path))
            classes.append(class_data)
            print(f"  Parsed: {class_data['name']}")
        except Exception as e:
            print(f"  Error parsing {path.name}: {e}")
    
    return classes


# ---------------------------------------------------------
# RACE BUILDING
# ---------------------------------------------------------

def parse_race_file(path: str) -> dict:
    """
    Parse a race text file.
    
    Expected format:
    ```
    Elf
    
    Speed: 30
    Size: Medium
    
    Ability Bonuses:
    * DEX +2
    
    Traits:
    * Darkvision: You can see in dim light within 60 feet.
    * Fey Ancestry: You have advantage on saving throws against being charmed.
    
    Languages: Common, Elvish
    
    Subraces:
    * High Elf: INT +1, Cantrip
    * Wood Elf: WIS +1, Fleet of Foot
    ```
    """
    raw = read_file_safe(path).replace("\r", "\n")
    lines = [ln for ln in raw.splitlines()]
    
    name = lines[0].strip() if lines else "Unknown"
    
    race_data = {
        "name": name,
        "speed": 30,
        "size": "Medium",
        "ability_bonuses": [],
        "traits": [],
        "languages": [],
        "subraces": []
    }
    
    current_section = None
    
    for ln in lines[1:]:
        ln_stripped = ln.strip()
        
        if not ln_stripped:
            continue
        
        # Section headers
        if ln_stripped.startswith("Speed:"):
            try:
                race_data["speed"] = int(re.search(r"(\d+)", ln_stripped).group(1))
            except:
                pass
        elif ln_stripped.startswith("Size:"):
            race_data["size"] = ln_stripped.split(":", 1)[1].strip()
        elif ln_stripped.startswith("Ability Bonuses:"):
            current_section = "abilities"
        elif ln_stripped.startswith("Traits:"):
            current_section = "traits"
        elif ln_stripped.startswith("Languages:"):
            race_data["languages"] = split_list_field(ln_stripped.split(":", 1)[1])
            current_section = None
        elif ln_stripped.startswith("Subraces:"):
            current_section = "subraces"
        elif ln_stripped.startswith("* "):
            item = ln_stripped[2:]
            
            if current_section == "abilities":
                # Parse "DEX +2" format
                match = re.match(r"(\w+)\s*([+-]?\d+)", item)
                if match:
                    race_data["ability_bonuses"].append({
                        "name": match.group(1).upper(),
                        "bonus": int(match.group(2))
                    })
            elif current_section == "traits":
                # Parse "Darkvision: Description" format
                if ":" in item:
                    trait_name, trait_desc = item.split(":", 1)
                    race_data["traits"].append({
                        "name": trait_name.strip(),
                        "description": trait_desc.strip()
                    })
                else:
                    race_data["traits"].append({"name": item, "description": ""})
            elif current_section == "subraces":
                # Parse "High Elf: INT +1, Cantrip" format
                if ":" in item:
                    subrace_name, subrace_features = item.split(":", 1)
                    race_data["subraces"].append({
                        "name": subrace_name.strip(),
                        "features": subrace_features.strip()
                    })
    
    return race_data


def build_races():
    """Build all races from text files."""
    if not RACE_INFO_DIR.exists():
        print(f"Creating {RACE_INFO_DIR}...")
        RACE_INFO_DIR.mkdir(exist_ok=True)
        
        # Create example template
        example = """Elf

Speed: 30
Size: Medium

Ability Bonuses:
* DEX +2

Traits:
* Darkvision: You can see in dim light within 60 feet of you as if it were bright light.
* Fey Ancestry: You have resistance to being charmed, and magic can't put you to sleep.
* Trance: Elves don't need to sleep. Instead, they meditate deeply for 4 hours a day.

Languages: Common, Elvish

Subraces:
* High Elf: INT +1, One wizard cantrip
* Wood Elf: WIS +1, Speed increases to 35 feet
* Dark Elf (Drow): CHA +1, Superior Darkvision
"""
        with open(RACE_INFO_DIR / "_EXAMPLE_Elf.txt", "w") as f:
            f.write(example)
        print(f"  Created example template: _EXAMPLE_Elf.txt")
        return []
    
    race_files = [f for f in RACE_INFO_DIR.glob("*.txt") if not f.name.startswith("_")]
    races = []
    
    for path in race_files:
        try:
            race_data = parse_race_file(str(path))
            races.append(race_data)
            print(f"  Parsed: {race_data['name']}")
        except Exception as e:
            print(f"  Error parsing {path.name}: {e}")
    
    return races


# ---------------------------------------------------------
# SPELL BUILDING
# ---------------------------------------------------------

def parse_spell_file(path: str) -> list:
    """
    Parse a spell text file containing multiple spells.
    
    Expected format (one spell per block, separated by blank lines):
    ```
    Fireball
    Level: 3
    School: Evocation
    Classes: Sorcerer, Wizard
    Casting Time: 1 action
    Range: 150 feet
    Components: V, S, M (a tiny ball of bat guano and sulfur)
    Duration: Instantaneous
    Description: A bright streak flashes from your pointing finger...
    Damage: 8d6 fire
    Save: DEX half
    
    Magic Missile
    Level: 1
    ...
    ```
    """
    raw = read_file_safe(path).replace("\r", "\n")
    
    # Split into spell blocks (separated by double newlines or more)
    blocks = re.split(r"\n\s*\n", raw)
    
    spells = []
    
    for block in blocks:
        lines = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
        if not lines:
            continue
        
        spell = {
            "name": lines[0],
            "level": 0,
            "school": "",
            "classes": [],
            "actionType": "action",
            "concentration": False,
            "ritual": False,
            "range": "",
            "components": [],
            "material": "",
            "duration": "",
            "description": "",
            "damage": "",
            "save": "",
            "to_hit": False
        }
        
        desc_lines = []
        in_description = False
        
        for ln in lines[1:]:
            if ln.startswith("Level:"):
                try:
                    spell["level"] = int(ln.split(":", 1)[1].strip())
                except:
                    pass
            elif ln.startswith("School:"):
                spell["school"] = ln.split(":", 1)[1].strip().lower()
            elif ln.startswith("Classes:"):
                spell["classes"] = [c.strip().lower() for c in ln.split(":", 1)[1].split(",")]
            elif ln.startswith("Casting Time:"):
                ct = ln.split(":", 1)[1].strip().lower()
                if "bonus" in ct:
                    spell["actionType"] = "bonus"
                elif "reaction" in ct:
                    spell["actionType"] = "reaction"
                elif "minute" in ct or "hour" in ct:
                    spell["actionType"] = ct
                else:
                    spell["actionType"] = "action"
            elif ln.startswith("Range:"):
                spell["range"] = ln.split(":", 1)[1].strip()
            elif ln.startswith("Components:"):
                comp_str = ln.split(":", 1)[1].strip()
                if "V" in comp_str.upper():
                    spell["components"].append("v")
                if "S" in comp_str.upper():
                    spell["components"].append("s")
                if "M" in comp_str.upper():
                    spell["components"].append("m")
                    # Extract material
                    mat_match = re.search(r"\(([^)]+)\)", comp_str)
                    if mat_match:
                        spell["material"] = mat_match.group(1)
            elif ln.startswith("Duration:"):
                dur = ln.split(":", 1)[1].strip()
                spell["duration"] = dur
                if "concentration" in dur.lower():
                    spell["concentration"] = True
            elif ln.startswith("Ritual:"):
                spell["ritual"] = "yes" in ln.lower() or "true" in ln.lower()
            elif ln.startswith("Damage:"):
                spell["damage"] = ln.split(":", 1)[1].strip()
            elif ln.startswith("Save:"):
                spell["save"] = ln.split(":", 1)[1].strip()
            elif ln.startswith("Attack:") or ln.startswith("To Hit:"):
                spell["to_hit"] = True
            elif ln.startswith("Description:"):
                in_description = True
                desc_part = ln.split(":", 1)[1].strip()
                if desc_part:
                    desc_lines.append(desc_part)
            elif in_description or (not any(ln.startswith(k) for k in 
                    ["Level:", "School:", "Classes:", "Casting", "Range:", 
                     "Components:", "Duration:", "Ritual:", "Damage:", "Save:", "Attack:"])):
                desc_lines.append(ln)
        
        spell["description"] = " ".join(desc_lines)
        
        if spell["name"] and spell["name"] != "Unknown":
            spells.append(spell)
    
    return spells


def build_spells():
    """Build all spells from text files."""
    if not SPELL_INFO_DIR.exists():
        print(f"Creating {SPELL_INFO_DIR}...")
        SPELL_INFO_DIR.mkdir(exist_ok=True)
        
        # Create example template
        example = """Fireball
Level: 3
School: Evocation
Classes: Sorcerer, Wizard
Casting Time: 1 action
Range: 150 feet
Components: V, S, M (a tiny ball of bat guano and sulfur)
Duration: Instantaneous
Damage: 8d6 fire
Save: DEX half
Description: A bright streak flashes from your pointing finger to a point you choose within range and then blossoms with a low roar into an explosion of flame. Each creature in a 20-foot-radius sphere centered on that point must make a Dexterity saving throw. A target takes 8d6 fire damage on a failed save, or half as much damage on a successful one.

Magic Missile
Level: 1
School: Evocation
Classes: Sorcerer, Wizard
Casting Time: 1 action
Range: 120 feet
Components: V, S
Duration: Instantaneous
Damage: 3d4+3 force
Description: You create three glowing darts of magical force. Each dart hits a creature of your choice that you can see within range. A dart deals 1d4+1 force damage to its target. The darts all strike simultaneously, and you can direct them to hit one creature or several.
"""
        with open(SPELL_INFO_DIR / "_EXAMPLE_Spells.txt", "w") as f:
            f.write(example)
        print(f"  Created example template: _EXAMPLE_Spells.txt")
        return []
    
    spell_files = [f for f in SPELL_INFO_DIR.glob("*.txt") if not f.name.startswith("_")]
    all_spells = []
    
    for path in spell_files:
        try:
            spells = parse_spell_file(str(path))
            all_spells.extend(spells)
            print(f"  Parsed {len(spells)} spells from: {path.name}")
        except Exception as e:
            print(f"  Error parsing {path.name}: {e}")
    
    return all_spells


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build content JSON files from text sources")
    parser.add_argument("--classes", action="store_true", help="Build classes")
    parser.add_argument("--races", action="store_true", help="Build races")
    parser.add_argument("--spells", action="store_true", help="Build spells")
    parser.add_argument("--all", action="store_true", help="Build everything")
    parser.add_argument("--merge", action="store_true", help="Merge with existing JSON instead of replacing")
    
    args = parser.parse_args()
    
    # Default to --all if nothing specified
    if not (args.classes or args.races or args.spells or args.all):
        args.all = True
    
    print("=" * 60)
    print("AI-DM Content Builder")
    print("=" * 60)
    
    if args.all or args.classes:
        print("\nBuilding Classes...")
        classes = build_classes()
        if classes:
            output = {"classes": classes}
            with open(OUTPUT_CLASSES, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2)
            print(f"  Wrote {len(classes)} classes to {OUTPUT_CLASSES.name}")
    
    if args.all or args.races:
        print("\nBuilding Races...")
        races = build_races()
        if races:
            with open(OUTPUT_RACES, "w", encoding="utf-8") as f:
                json.dump(races, f, indent=2)
            print(f"  Wrote {len(races)} races to {OUTPUT_RACES.name}")
    
    if args.all or args.spells:
        print("\nBuilding Spells...")
        spells = build_spells()
        if spells:
            with open(OUTPUT_SPELLS, "w", encoding="utf-8") as f:
                json.dump(spells, f, indent=2)
            print(f"  Wrote {len(spells)} spells to {OUTPUT_SPELLS.name}")
    
    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
