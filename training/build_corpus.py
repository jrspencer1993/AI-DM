#!/usr/bin/env python3
"""
build_corpus.py — Generate training corpora from SRD data.

This script normalizes SRD monsters and extracts actions into canonical schemas
for use in training language models. It mirrors the normalization logic used
in the UI to ensure consistency.

Usage:
    python training/build_corpus.py

Outputs (written to /training/out/):
    - monsters.normalized.json
    - actions.normalized.jsonl
    - rules.snapshot.json
    - prompts_samples.jsonl
"""

import os
import json
import re
from datetime import datetime

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "out")

SRD_CANDIDATES = [
    os.path.join(DATA_DIR, "SRD_Monsters.json"),
    os.path.join(DATA_DIR, "SRD_Monsters.txt"),
]


def ensure_output_dir():
    """Create the output directory if it doesn't exist."""
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"Created output directory: {OUTPUT_DIR}")


def load_srd_monsters():
    """
    Load SRD monsters from JSON file.
    Returns (list of raw monster dicts, path used) or ([], None) if not found.
    """
    for path in SRD_CANDIDATES:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    raw = json.load(f)
                # Handle wrapped formats
                if isinstance(raw, dict):
                    raw = (
                        raw.get("monsters")
                        or raw.get("data")
                        or raw.get("results")
                        or list(raw.values())
                    )
                if isinstance(raw, list):
                    return raw, path
            except Exception as e:
                print(f"Warning: Failed to load {path}: {e}")
    return [], None


# ---------------------------------------------------------------------------
# Normalization helpers (mirrored from UI)
# ---------------------------------------------------------------------------
def _first_int(val, default=0):
    """Extract the first integer from a value."""
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
    """Extract AC from various SRD formats."""
    ac = mon.get("ac", mon.get("armor_class", mon.get("armorClass", mon.get("Armor Class"))))
    if isinstance(ac, int):
        return ac
    if isinstance(ac, list) and ac:
        if isinstance(ac[0], dict):
            return _first_int(ac[0].get("value") or ac[0].get("ac"), 10)
        return _first_int(ac[0], 10)
    if isinstance(ac, dict):
        return _first_int(ac.get("value") or ac.get("ac"), 10)
    return _first_int(ac, 10)


def _extract_hp(mon: dict) -> int:
    """Extract HP from various SRD formats."""
    if "hp" in mon:
        return _first_int(mon.get("hp"), 10)
    if "hit_points" in mon:
        return _first_int(mon.get("hit_points"), 10)
    return _first_int(mon.get("Hit Points"), 10)


def _extract_abilities(mon: dict) -> dict:
    """Extract ability scores from various SRD formats."""
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
    """Parse skills from dict or string format."""
    if isinstance(skills_val, dict):
        return {str(k): _first_int(v, 0) for k, v in skills_val.items()}
    if not skills_val:
        return {}
    s = str(skills_val)
    parts = [p.strip() for p in s.split(",") if p.strip()]
    out = {}
    for p in parts:
        m = re.match(r"^(.+?)\s*([+\-]\d+)\s*$", p)
        if m:
            out[m.group(1).strip()] = int(m.group(2))
    return out


def _parse_actions_text(actions_text: str) -> list:
    """Parse SRD 'Actions' text field into action dicts."""
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

        # Extract damage type
        dtype_match = re.search(r"(\w+)\s+damage", ch, re.IGNORECASE)
        dtype = dtype_match.group(1).lower() if dtype_match else ""

        # Extract description (the full chunk minus the name)
        desc = ch[len(name) + 1:].strip() if len(ch) > len(name) + 1 else ""

        parsed.append({
            "name": name,
            "to_hit": to_hit,
            "damage": dmg or "1d6",
            "damage_type": dtype,
            "description": desc,
        })
    return parsed


def _extract_actions(mon: dict) -> list:
    """Extract and normalize actions from a monster dict."""
    actions = mon.get("actions")
    if isinstance(actions, list):
        out = []
        for a in actions:
            if not isinstance(a, dict):
                continue
            name = a.get("name", "Action")

            to_hit = a.get("to_hit")
            if to_hit is None:
                to_hit = a.get("attack_bonus", a.get("bonus", 0))
            to_hit = _first_int(to_hit, 0)

            # Damage handling
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

            out.append({
                "name": name,
                "to_hit": int(to_hit),
                "damage": dmg or "1d6",
                "damage_type": a.get("damage_type") or a.get("damage_type_name") or "",
                "description": a.get("desc") or a.get("description") or "",
            })
        return out

    # Text-based SRD field
    return _parse_actions_text(mon.get("Actions", ""))


def normalize_monster(mon: dict) -> dict:
    """Normalize a raw SRD monster into the canonical schema."""
    if not isinstance(mon, dict):
        return None

    name = mon.get("name") or mon.get("Name") or "Monster"
    ac = _extract_ac(mon)
    hp = _extract_hp(mon)
    abilities = _extract_abilities(mon)

    skills_raw = mon.get("skills") or mon.get("Skills") or {}
    skills = _parse_skills_to_dict(skills_raw)
    senses = mon.get("senses") or mon.get("Senses") or mon.get("sense") or ""

    actions = _extract_actions(mon)

    # Attacks derived from actions
    attacks = []
    for a in actions:
        if not isinstance(a, dict) or "name" not in a:
            continue
        attacks.append({
            "name": a.get("name", "Attack"),
            "to_hit": _first_int(a.get("to_hit"), _first_int(a.get("attack_bonus"), 0)),
            "damage": a.get("damage") or a.get("damage_dice") or "1d6",
            "damage_type": a.get("damage_type", "") or "",
        })

    return {
        "name": name,
        "ac": ac,
        "hp": hp,
        "max_hp": hp,
        "abilities": abilities,
        "skills": skills,
        "senses": str(senses) if senses is not None else "",
        "actions": actions,
        "attacks": attacks,
    }


def action_to_canonical(action: dict, monster_name: str) -> dict:
    """
    Convert a normalized action to the canonical ACTION_SCHEMA format.
    """
    name = action.get("name", "Action")
    to_hit = action.get("to_hit", 0)
    damage = action.get("damage", "")
    damage_type = action.get("damage_type", "")
    description = action.get("description", "")

    # Determine action type
    if to_hit or damage:
        action_type_val = "attack"
    else:
        action_type_val = "utility"

    # Extract range from description if present
    range_val = None
    range_match = re.search(r"reach\s*(\d+)\s*ft", description, re.IGNORECASE)
    if range_match:
        range_val = int(range_match.group(1))
    else:
        range_match = re.search(r"range\s*(\d+)", description, re.IGNORECASE)
        if range_match:
            range_val = int(range_match.group(1))

    # Check for save-based effects
    dc = None
    save = None
    dc_match = re.search(r"DC\s*(\d+)\s*(STR|DEX|CON|INT|WIS|CHA|Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)", description, re.IGNORECASE)
    if dc_match:
        dc = int(dc_match.group(1))
        save_map = {
            "str": "STR", "strength": "STR",
            "dex": "DEX", "dexterity": "DEX",
            "con": "CON", "constitution": "CON",
            "int": "INT", "intelligence": "INT",
            "wis": "WIS", "wisdom": "WIS",
            "cha": "CHA", "charisma": "CHA",
        }
        save = save_map.get(dc_match.group(2).lower(), dc_match.group(2).upper())

    # Check for conditions
    condition = None
    condition_keywords = ["prone", "stunned", "frightened", "charmed", "paralyzed", "poisoned", "restrained", "blinded", "deafened", "grappled"]
    for cond in condition_keywords:
        if cond in description.lower():
            condition = cond
            break

    return {
        "monster_name": monster_name,
        "name": name,
        "type": action_type_val,
        "action_type": "standard",
        "to_hit": to_hit if to_hit else None,
        "dc": dc,
        "save": save,
        "damage": damage if damage else None,
        "damage_type": damage_type if damage_type else None,
        "condition": condition,
        "range": range_val,
        "description": description,
    }


def generate_prompt_samples(normalized_monsters: list) -> list:
    """
    Generate instruction-style training samples.
    """
    samples = []

    # Sample A: Normalize a monster
    if normalized_monsters:
        sample_monster = normalized_monsters[0]
        samples.append({
            "instruction": "Normalize this SRD monster into the canonical schema.",
            "input": {
                "name": sample_monster["name"],
                "ac": sample_monster["ac"],
                "hp": sample_monster["hp"],
                "abilities": sample_monster["abilities"],
            },
            "output": sample_monster,
        })

    # Sample B: Extract actions
    if normalized_monsters and normalized_monsters[0].get("actions"):
        monster = normalized_monsters[0]
        actions = monster.get("actions", [])
        if actions:
            samples.append({
                "instruction": "Extract actions from this monster into ACTION_SCHEMA format.",
                "input": {
                    "monster_name": monster["name"],
                    "actions": actions,
                },
                "output": [
                    action_to_canonical(a, monster["name"]) for a in actions
                ],
            })

    # Sample C: Resolve attack (hybrid rules placeholder)
    samples.append({
        "instruction": "Given attacker and target, resolve an attack roll and damage using hybrid rules (no advantage/disadvantage, use flat modifiers).",
        "input": {
            "attacker": {
                "name": "Fighter",
                "attack": {"name": "Longsword", "to_hit": 5, "damage": "1d8+3"},
            },
            "target": {
                "name": "Goblin",
                "ac": 15,
                "hp": 7,
            },
            "modifiers": {
                "cover_bonus": 2,
                "flanking_bonus": 0,
            },
        },
        "output": {
            "attack_roll": "d20 + 5 + 0 (modifiers) vs AC 17 (15 + 2 cover)",
            "result": "If roll >= 17: Hit. Roll 1d8+3 damage.",
            "notes": "Hybrid rules: flat +2 AC for cover instead of advantage/disadvantage.",
        },
    })

    return samples


def write_outputs(normalized_monsters: list, canonical_actions: list, samples: list):
    """Write all output files."""
    ensure_output_dir()

    # monsters.normalized.json
    monsters_path = os.path.join(OUTPUT_DIR, "monsters.normalized.json")
    with open(monsters_path, "w", encoding="utf-8") as f:
        json.dump(normalized_monsters, f, indent=2)
    print(f"  Written: {monsters_path}")

    # actions.normalized.jsonl
    actions_path = os.path.join(OUTPUT_DIR, "actions.normalized.jsonl")
    with open(actions_path, "w", encoding="utf-8") as f:
        for action in canonical_actions:
            f.write(json.dumps(action) + "\n")
    print(f"  Written: {actions_path}")

    # rules.snapshot.json
    rules_path = os.path.join(OUTPUT_DIR, "rules.snapshot.json")
    rules = {
        "version": "0.4.0",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "no_advantage_disadvantage": True,
        "flat_modifier_range": [-2, 2],
        "notes": "Hybrid rules: use flat modifiers instead of advantage/disadvantage mechanics.",
    }
    with open(rules_path, "w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2)
    print(f"  Written: {rules_path}")

    # prompts_samples.jsonl
    prompts_path = os.path.join(OUTPUT_DIR, "prompts_samples.jsonl")
    with open(prompts_path, "w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample) + "\n")
    print(f"  Written: {prompts_path}")


def main():
    """Main entry point."""
    print("=" * 60)
    print("Training Corpus Builder")
    print("=" * 60)

    # Load SRD monsters
    print("\nLoading SRD monsters...")
    raw_monsters, srd_path = load_srd_monsters()

    if not raw_monsters:
        print("ERROR: No SRD monster data found.")
        print(f"Searched paths: {SRD_CANDIDATES}")
        return

    print(f"  Source: {srd_path}")
    print(f"  Raw monsters loaded: {len(raw_monsters)}")

    # Normalize monsters
    print("\nNormalizing monsters...")
    normalized_monsters = []
    for mon in raw_monsters:
        norm = normalize_monster(mon)
        if norm:
            normalized_monsters.append(norm)
    print(f"  Normalized monsters: {len(normalized_monsters)}")

    # Extract canonical actions
    print("\nExtracting canonical actions...")
    canonical_actions = []
    for mon in normalized_monsters:
        monster_name = mon.get("name", "Unknown")
        for action in mon.get("actions", []):
            canonical = action_to_canonical(action, monster_name)
            canonical_actions.append(canonical)
    print(f"  Actions extracted: {len(canonical_actions)}")

    # Generate prompt samples
    print("\nGenerating prompt samples...")
    samples = generate_prompt_samples(normalized_monsters)
    print(f"  Samples generated: {len(samples)}")

    # Write outputs
    print("\nWriting output files...")
    write_outputs(normalized_monsters, canonical_actions, samples)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Monsters loaded:    {len(raw_monsters)}")
    print(f"  Monsters normalized:{len(normalized_monsters)}")
    print(f"  Actions extracted:  {len(canonical_actions)}")
    print(f"  Training samples:   {len(samples)}")
    print(f"  Output directory:   {OUTPUT_DIR}")
    print("\nDone!")


if __name__ == "__main__":
    main()
