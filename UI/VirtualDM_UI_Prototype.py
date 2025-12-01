import os
import json
import random
import re
from datetime import datetime
from typing import Tuple, Dict, Any, List

import streamlit as st

# ---------------- Page Config ----------------
st.set_page_config(page_title="Virtual DM – Session Manager", layout="wide")

# ---------------- SRD Database ----------------
# reminder: keep the SRD file at ../data/SRD_Monsters.json relative to this UI file.
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "data"))
SRD_CANDIDATES = ["SRD_Monsters.json", "SRD_Monsters.txt"]  # accepts either

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

def load_srd_monsters():
    """
    Loads SRD monsters once per session into st.session_state.srd_enemies.
    Tolerant schema: accepts common 5e keys and normalizes to the fields our UI uses.
    """
    if "srd_enemies" in st.session_state:
        return
    path = _resolve_srd_path()
    try:
        if not path:
            st.session_state.srd_enemies = []
            return
        # 'utf-8-sig' handles BOM if saved from Notepad
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if not isinstance(data, list):
            data = []
        # normalize each entry
        st.session_state.srd_enemies = [_norm_monster(m) for m in data if isinstance(m, dict) and m.get("name")]
    except Exception as e:
        # reminder: JSON must be an array of objects; avoid trailing commas.
        st.session_state.srd_enemies = []
        st.warning(f"Failed to load SRD: {e}")

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
        roll = random.randint(1,20) + dm
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
    st.session_state.turn_index += 1
    if st.session_state.turn_index >= order_len:
        st.session_state.turn_index = 0
        st.session_state.combat_round += 1

def end_combat():
    st.session_state.in_combat = False
    st.session_state.initiative_order = []
    st.session_state.combat_round = 0
    st.session_state.turn_index = 0

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


def resolve_attack(text: str) -> str | None:
    """
    Attempt to resolve an attack based on the current actor's stats and the text command.
    Returns a descriptive string if handled, or None if this is not an attack action.
    """
    kind, idx, actor = get_current_actor()
    if not actor:
        return None  # no active combatant (e.g., combat not started)

    info = parse_player_command(text, st.session_state.party, st.session_state.enemies)
    if info["type"] != "attack":
        return None  # not an attack; caller can fall back to other logic

    # find target
    ti = info["target_idx"]
    if ti is None or ti < 0 or ti >= len(st.session_state.enemies):
        return f"{actor.get('name','The attacker')} tries to attack, but I can't find that target among the enemies."

    target = st.session_state.enemies[ti]

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

    att_name = chosen.get("name", "attack")
    to_hit = int(chosen.get("to_hit", 0))
    d_expr = chosen.get("damage", "1d6")

    d20 = roll_d20()
    total = d20 + to_hit
    ac = int(target.get("ac", 10))

    lines = []
    lines.append(f"{actor.get('name','The attacker')} attacks {target.get('name','the target')} with {att_name}!")
    lines.append(f"Attack roll: d20 ({d20}) + {to_hit} = **{total}** vs AC {ac}.")

    if d20 == 1:
        lines.append("Critical miss (natural 1).")
        return "\n".join(lines)

    if total >= ac:
        dmg_total, breakdown = roll_damage_expr(d_expr)
        try:
            target["hp"] = max(0, int(target.get("hp", 0)) - int(dmg_total))
        except Exception:
            # reminder: if HP is missing or non-numeric, just report damage and move on
            pass
        lines.append(f"Hit! {target.get('name','The target')} takes **{dmg_total}** damage ({breakdown}).")
        if isinstance(target.get("hp"), int):
            lines.append(f"{target.get('name','The target')} is now at **{target['hp']} HP**.")
    else:
        lines.append("Miss.")

    return "\n".join(lines)

def _get_skill_mod(actor: dict, skill_name: str) -> int:
    """
    Compute the modifier for a given skill using the actor's abilities,
    explicit skill bonuses when present, and proficiency.
    """
    # quick mapping; we can extend this later once we have a full skill JSON
    SKILL_TO_ABILITY = {
        "Athletics": "STR",
        "Acrobatics": "DEX",
        "Stealth": "DEX",
        "Sleight of Hand": "DEX",
        "Perception": "WIS",
        "Insight": "WIS",
        "Survival": "WIS",
        "Arcana": "INT",
        "History": "INT",
        "Investigation": "INT",
        "Religion": "INT",
        "Nature": "INT",
        "Deception": "CHA",
        "Intimidation": "CHA",
        "Performance": "CHA",
        "Persuasion": "CHA",
    }

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


def resolve_skill_check(text: str) -> str | None:
    """
    Attempt to resolve a basic skill check (grapple, jump, climb, stealth)
    based on the current actor. Returns a descriptive string if handled,
    or None if this is not a recognized skill-type action.
    """
    kind, idx, actor = get_current_actor()
    if not actor:
        return None  # no active combatant / no current actor

    info = parse_player_command(text, st.session_state.party, st.session_state.enemies)
    action_type = info.get("type")

    # map our simple action types to skill names
    if action_type == "grapple":
        skill = "Athletics"
        short_desc = "attempts to grapple the target"
    elif action_type == "jump":
        skill = "Athletics"
        short_desc = "tries to make a long jump"
    elif action_type == "climb":
        skill = "Athletics"
        short_desc = "tries to climb"
    elif action_type == "stealth":
        skill = "Stealth"
        short_desc = "attempts to move quietly and stay hidden"
    else:
        return None  # not something we currently treat as a skill check

    # simple DC heuristic for now; later attach this to terrain / examples
    DC_BANDS = {
        "very_easy": 5,
        "easy": 10,
        "medium": 15,
        "hard": 20,
        "very_hard": 25,
        "nearly_impossible": 30,
    }

    # start with 'medium' and nudge a bit randomly
    base_dc = DC_BANDS["medium"]
    dc_jitter = random.choice([-2, 0, 0, 2])  # mostly 15, sometimes 13 or 17
    dc = max(5, base_dc + dc_jitter)

    mod = _get_skill_mod(actor, skill)
    d20 = roll_d20()
    total = d20 + mod

    actor_name = actor.get("name", "The character")

    lines = []
    lines.append(f"{actor_name} {short_desc} (**{skill} check**, DC {dc}).")
    lines.append(f"Roll: d20 ({d20}) + {mod} = **{total}**.")

    if total >= dc:
        lines.append("Result: **Success**.")
    else:
        lines.append("Result: **Failure**.")

    return "\n".join(lines)

# ==== SRD mini-loaders for Builder (accept .json or .txt) ====
def _load_json_from_candidates(dir_path, names):
    for nm in names:
        p = os.path.join(dir_path, nm)
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                return data, p
            except Exception as e:
                st.warning(f"Failed to read {p}: {e}")
                return [], p
    return [], None

def load_srd_races():
    data, p = _load_json_from_candidates(DATA_DIR, ["SRD_Races.json", "SRD_Races.txt"])
    st.session_state["srd_races_path"] = p
    return data if isinstance(data, list) else []

def load_srd_backgrounds():
    data, p = _load_json_from_candidates(DATA_DIR, ["SRD_Backgrounds.json", "SRD_Backgrounds.txt"])
    st.session_state["srd_backgrounds_path"] = p
    return data if isinstance(data, list) else []

def load_srd_classes():
    data, p = _load_json_from_candidates(DATA_DIR, ["SRD_Classes.json", "SRD_Classes.txt"])
    st.session_state["srd_classes_path"] = p
    return data if isinstance(data, list) else []

def load_srd_feats():
    data, p = _load_json_from_candidates(DATA_DIR, ["SRD_Feats.json", "SRD_Feats.txt"])
    st.session_state["srd_feats_path"] = p
    return data if isinstance(data, list) else []

def load_srd_equipment():
    data, p = _load_json_from_candidates(DATA_DIR, ["SRD_Equipment.json", "SRD_Equipment.txt"])
    st.session_state["srd_equipment_path"] = p
    return data if isinstance(data, list) else []
    
# ==== Character Builder: small helpers + applicators ====

def _ability_mod(score: int) -> int:
    try:
        return (int(score) - 10) // 2
    except:
        return 0
    
def roll_ability_scores_4d6_drop_lowest():
    """Roll 4d6 drop lowest, six times. Returns a list of six scores."""
    scores = []
    for _ in range(6):
        dice = sorted([random.randint(1, 6) for _ in range(4)])
        # drop the lowest die, sum the highest three
        scores.append(sum(dice[1:]))
    return scores

def compute_hp_level1(char: dict, class_blob: dict) -> int:
    hit_die = int(class_blob.get("hit_die", 8))  # default d8 if missing
    con_mod = _ability_mod(char.get("abilities", {}).get("CON", 10))
    return max(1, hit_die + con_mod)

def compute_ac_from_equipment(char: dict) -> int:
    # reminder: simple AC rules good enough for Week 3 demo; expand later
    armor_list = [x.lower() for x in (char.get("equipment") or []) if isinstance(x, str)]
    armor = ", ".join(armor_list)
    dex_mod = _ability_mod(char.get("abilities", {}).get("DEX", 10))
    ac = 10 + dex_mod  # default
    if "chain mail" in armor: ac = 16               # no DEX
    elif "scale mail" in armor: ac = 14 + min(dex_mod, 2)
    elif "studded leather" in armor: ac = 12 + dex_mod
    elif "leather armor" in armor or "leather" in armor: ac = 11 + dex_mod
    if "shield" in armor: ac += 2
    return ac

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
            # fallback: PB + STR for martial by default
            to_hit = _ability_mod(char.get("abilities", {}).get("STR", 10)) + int(char.get("proficiency_bonus", 2))
        dmg = a.get("damage", "1d6")
        norm.append({"name": nm, "to_hit": int(to_hit), "damage": dmg, "reach": a.get("reach"), "range": a.get("range")})
    if norm:
        char["attacks"] = norm
        char["default_attack_index"] = 0  # reminder: used by auto-actions later

def apply_race(char: dict, race: dict):
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
        # Our older “simple dict” format
        for k, v in ab.items():
            if k in char["abilities"]:
                char["abilities"][k] = int(char["abilities"][k]) + int(v)

    # --- Speed: API uses an int (e.g., 30) ---
    spd = race.get("speed")
    if isinstance(spd, int):
        char["speed"] = f"{spd} ft."
    elif isinstance(spd, str) and spd:
        char["speed"] = spd

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

    # --- Traits -> Features: API uses list of dicts with "name" ---
    feats = char.setdefault("features", [])
    traits = race.get("traits") or []
    for t in traits:
        if isinstance(t, dict):
            name = t.get("name")
        else:
            name = str(t)
        if name and name not in feats:
            feats.append(name)

def apply_background(char: dict, bg: dict):
    char["background"] = bg.get("name", "")
    char.setdefault("profs", {}).setdefault("skills", [])
    skills = set(char["profs"]["skills"])
    for s in (bg.get("skills") or []):
        skills.add(s)
    char["profs"]["skills"] = sorted(skills)
    # languages (simple concat)
    if bg.get("languages"):
        existing = set((char.get("languages") or "").split(", ")) if char.get("languages") else set()
        for l in bg["languages"]:
            if l:
                existing.add(l)
        char["languages"] = ", ".join(sorted(existing))
    # features
    feats = char.setdefault("features", [])
    for f in (bg.get("features") or []):
        if f not in feats:
            feats.append(f)

def apply_class_level1(char: dict, cls: dict, kit_idx: int = 0):
    """Apply a 5e-style level 1 class to a character and recompute HP/AC."""
    # basic identity
    char["class"] = cls.get("name", "")
    char["level"] = 1
    char["proficiency_bonus"] = 2

    # make sure we have abilities to work with (needed for HP/AC)
    char.setdefault(
        "abilities",
        {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
    )

    # proficiencies
    pr = char.setdefault("profs", {})
    for key, src in (
        ("saves", "primary_saves"),
        ("armor", "armor_profs"),
        ("weapons", "weapon_profs"),
    ):
        pr.setdefault(key, [])
        cur = set(pr[key])
        for v in (cls.get(src) or []):
            cur.add(v)
        pr[key] = sorted(cur)

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

    # set up a default attack from that kit 
    set_default_attack_from_kit(char, kit)

    # AC from equipment + DEX
    char["ac"] = compute_ac_from_equipment(char)

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
    return {
        "session_id": st.session_state.session_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "chat_log": st.session_state.chat_log,
        "world_log": st.session_state.world_log,
        "party": st.session_state.party,
        "enemies": st.session_state.enemies,
        "difficulty": st.session_state.difficulty,
    }

def load_state_blob(blob: Dict[str, Any]):
    st.session_state.session_id = blob.get("session_id", datetime.now().strftime("%Y%m%d_%H%M%S"))
    st.session_state.chat_log = blob.get("chat_log", [])
    st.session_state.world_log = blob.get("world_log", "")
    st.session_state.party = blob.get("party", [])
    st.session_state.enemies = blob.get("enemies", [])
    st.session_state.difficulty = blob.get("difficulty", "Normal")

# ---------------- Dice + Dialogue Utilities ----------------
def roll_dice(expr: str) -> Tuple[int, str]:
    """
    Supports: 2d6+3, d20+5, 1d8-1, 2d4, plain number. Returns (total, breakdown).
    """
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
    "attacks": []  # list of {name, to_hit:int, damage:str, reach/range:opt}
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
        "features": [], "feats": [], "spells": [], "equipment": [],
        "attacks": [], "default_attack_index": 0
    })
    ss.setdefault("builder_name", "")
    ss.setdefault("builder_step", 1)  # 1..5 Race, Background, Class, Feats, Equipment

init_builder_state()

# ---------------- Boot Flow ----------------
if st.session_state.boot_mode is None:
    st.info("Choose how to begin:")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Load Previous Session", use_container_width=True):
            st.session_state.boot_mode = "load"
    with c2:
        if st.button("Start New Session", use_container_width=True):
            st.session_state.boot_mode = "new"
    st.stop()

# ---------------- Load Session ----------------
if st.session_state.boot_mode == "load":
    st.subheader("Load Previous Session")
    up = st.file_uploader("Upload a saved session (.json)", type=["json"])
    if up is not None:
        try:
            blob = json.load(up)
            load_state_blob(blob)
            st.success("Session loaded.")
            st.session_state.boot_mode = "running"
        except Exception as e:
            st.error(f"Could not load file: {e}")
    st.stop()

# ---------------- New Session: Character Entry ----------------
if st.session_state.boot_mode == "new":
    st.subheader("New Session Setup")
    st.caption("Upload 5e character sheets (.json), paste JSON, or fill the form to add party members. Then add enemies if needed.")

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
        st.progress(step / 5.0, text=f"Step {step} of 5")

        # Sticky name across steps
        st.text_input("Character Name", key="builder_name")
        if st.session_state.builder_name:
            c["name"] = st.session_state.builder_name

        # STEP 1: Race + Ability Scores
        if step == 1:
            st.subheader("Step 1: Choose Race")
            race_names = [r.get("name", "") for r in races]
            r_pick = st.selectbox("Race", race_names, key="builder_race_pick")

            if r_pick:
                with st.expander("Race Details", expanded=False):
                    st.write(next((r for r in races if r.get("name") == r_pick), {}))

            # Ability Scores: roll 4d6 drop lowest or edit manually
            with st.expander("Ability Scores (4d6 drop lowest)", expanded=False):
                abilities = c.setdefault(
                    "abilities",
                    {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
                )

                if st.button("Roll 4d6 (drop lowest)", key="builder_roll_4d6"):
                    scores = roll_ability_scores_4d6_drop_lowest()
                    for key, val in zip(["STR", "DEX", "CON", "INT", "WIS", "CHA"], scores):
                        abilities[key] = val
                    st.toast(f"Rolled scores: {scores}")

                col1, col2, col3 = st.columns(3)
                abilities["STR"] = int(col1.number_input("STR", 3, 20, int(abilities.get("STR", 10)), key="builder_STR"))
                abilities["DEX"] = int(col2.number_input("DEX", 3, 20, int(abilities.get("DEX", 10)), key="builder_DEX"))
                abilities["CON"] = int(col3.number_input("CON", 3, 20, int(abilities.get("CON", 10)), key="builder_CON"))

                col4, col5, col6 = st.columns(3)
                abilities["INT"] = int(col4.number_input("INT", 3, 20, int(abilities.get("INT", 10)), key="builder_INT"))
                abilities["WIS"] = int(col5.number_input("WIS", 3, 20, int(abilities.get("WIS", 10)), key="builder_WIS"))
                abilities["CHA"] = int(col6.number_input("CHA", 3, 20, int(abilities.get("CHA", 10)), key="builder_CHA"))

            if st.button("Apply Race", type="primary"):
                if r_pick:
                    apply_race(c, next(r for r in races if r.get("name") == r_pick))
                    st.session_state.builder_step = 2
                    st.toast(f"Race applied: {r_pick}")
                    st.rerun()

            st.caption("SRD races source: " + str(st.session_state.get("srd_races_path", "(not found)")))

        # STEP 2: Background
        if step == 2:
            st.subheader("Step 2: Choose Background")
            bg_names = [b.get("name", "") for b in bgs]
            b_pick = st.selectbox("Background", bg_names, key="builder_bg_pick")

            if b_pick:
                with st.expander("Background Details", expanded=False):
                    st.write(next((b for b in bgs if b.get("name") == b_pick), {}))

            col = st.columns([1, 1])
            if col[0].button("Back"):
                st.session_state.builder_step = 1
                st.rerun()

            if col[1].button("Apply Background", type="primary"):
                if b_pick:
                    apply_background(c, next(b for b in bgs if b.get("name") == b_pick))
                    st.session_state.builder_step = 3
                    st.toast(f"Background applied: {b_pick}")
                    st.rerun()

        # STEP 3: Class
        if step == 3:
            st.subheader("Step 3: Choose Class (Level 1)")
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
                with st.expander("Class Details", expanded=False):
                    st.write(c_blob or {})

            col = st.columns([1, 1])
            if col[0].button("Back  ", key="class_back"):
                st.session_state.builder_step = 2
                st.rerun()

            if col[1].button("Apply Class", type="primary"):
                if c_pick:
                    apply_class_level1(
                        c,
                        next(x for x in classes if x.get("name") == c_pick),
                        kit_idx=int(st.session_state.get("builder_class_kit_idx", 0)),
                    )
                    st.session_state.builder_step = 4
                    st.toast(f"Class applied: {c_pick}")
                    st.rerun()

        # STEP 4: Feats
        if step == 4:
            st.subheader("Step 4: Choose Feats (Optional)")
            feat_names = [f.get("name", "") if isinstance(f, dict) else str(f) for f in feats_db]
            chosen = st.multiselect("Feats", feat_names, key="builder_feats_multi")

            col = st.columns([1, 1])
            if col[0].button("Back   ", key="feats_back"):
                st.session_state.builder_step = 3
                st.rerun()

            if col[1].button("Apply Feats", type="primary"):
                apply_feats(c, st.session_state.get("builder_feats_multi", []))
                st.session_state.builder_step = 5
                st.toast("Feats applied.")
                st.rerun()

        # STEP 5: Equipment
        if step == 5:
            st.subheader("Step 5: Add Equipment (Optional)")
            item_names = [i.get("name", "") if isinstance(i, dict) else str(i) for i in equip_db]
            extras = st.multiselect("Add items", item_names, key="builder_items_multi")

            if st.button("Add Items"):
                eq = set(c.get("equipment") or [])
                for it in extras:
                    if it:
                        eq.add(it)
                c["equipment"] = sorted(eq)
                c["ac"] = compute_ac_from_equipment(c)
                st.toast("Items added.")

            col = st.columns([1, 1, 2])
            if col[0].button("Back    ", key="equip_back"):
                st.session_state.builder_step = 4

            if col[1].button("Reset Builder"):
                # reminder: keep a quick way to clear if users want to start fresh
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
                }
                st.session_state.builder_name = ""
                st.session_state.builder_step = 1
                st.toast("Cleared working character.")

            if col[2].button("Add to Party", type="primary"):
                if not c.get("name"):
                    st.warning("Please set a character name.")
                else:
                    st.session_state.party.append(json.loads(json.dumps(c)))  # deep copy
                    st.success(f"Added to party: {c['name']}")
                    # stay on setup page; builder remains for creating another character

        st.markdown("---")
        st.markdown("#### Preview")
        st.json(st.session_state.builder_char)

        st.markdown("#### Current Party")
        if not st.session_state.party:
            st.info("No party members yet.")
        else:
            for i, c in enumerate(st.session_state.party):
                box = st.container(border=True)
                h1, h2, h3, h4 = box.columns([4, 2, 2, 2])
                with h1:
                    st.markdown(f"**{c.get('name','')}**")
                with h2:
                    c["ac"] = int(st.number_input("AC", 0, 40, int(c.get("ac", 10)), key=f"p_ac_{i}"))
                with h3:
                    c["hp"] = int(st.number_input("HP", 0, 500, int(c.get("hp", 10)), key=f"p_hp_{i}"))
                with h4:
                    if st.button("Remove", key=f"p_rm_{i}"):
                        del st.session_state.party[i]
                        st.rerun()
                with box.expander("Details"):
                    a = c.get("abilities", {})
                    st.write(f"Speed: {c.get('speed','')}")
                    st.write("Abilities:", a)
                    st.write("Attacks:", c.get("attacks", []))

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
                names = [m["name"] for m in st.session_state.srd_enemies]
                srd_name = st.selectbox("SRD Creature", names, key="new_add_srd_name")
                srd_count = st.number_input("Count", 1, 20, 1, key="new_add_srd_count")
                if st.button("Add From SRD", key="new_add_srd_btn"):
                    src = next((m for m in st.session_state.srd_enemies if m["name"] == srd_name), None)
                    if src:
                        for i in range(int(srd_count)):
                            st.session_state.enemies.append(
                                {
                                    "name": f"{src['name']}" if srd_count == 1 else f"{src['name']} #{i+1}",
                                    "ac": int(src.get("ac", 10)),
                                    "hp": int(src.get("hp", 10)),
                                    "attacks": src.get("attacks", []),
                                }
                            )
                        st.success(f"Added {int(srd_count)} × {srd_name}")

    if st.button("Begin Session", type="primary"):
        if not st.session_state.party:
            st.warning("Add at least one party member.")
        else:                                                             
            st.session_state.boot_mode = "running"

    st.stop() 

# ---------------- Running Session ----------------
# Top bar
top_l, top_sp, top_r1, top_r2, top_r3 = st.columns([6,1,1,1,1])
with top_l:
    st.markdown(f"### Session: {st.session_state.session_id}")
with top_r1:
    # Export full session JSON (restores state later)
    data = serialize_state()
    st.download_button("Download Session JSON",
                       data=json.dumps(data, indent=2),
                       file_name=f"virtualdm_session_{st.session_state.session_id}.json",
                       mime="application/json")
with top_r2:
    if st.button("New"):
        st.session_state.boot_mode = "new"
with top_r3:
    if st.button("Load"):
        st.session_state.boot_mode = "load"

st.divider()

# Main columns
left, mid, right = st.columns([4,5,4])

# ===== LEFT: Narrative / Party =====
with left:
    st.markdown("#### Narrative")
    st.text_area("World Notes", key="world_log", height=160)
    st.markdown("#### Party")
    if not st.session_state.party:
        st.caption("No party members.")
    else:
        for i, c in enumerate(st.session_state.party):
            box = st.container(border=True)
            t1, t2, t3, t4 = box.columns([4,2,2,2])
            with t1: st.markdown(f"**{c.get('name','')}**")
            with t2: c["ac"] = int(st.number_input("AC", 0, 40, int(c.get("ac",10)), key=f"run_p_ac_{i}"))
            with t3: c["hp"] = int(st.number_input("HP", 0, 500, int(c.get("hp",10)), key=f"run_p_hp_{i}"))
            with t4:
                if st.button("Remove", key=f"run_p_rm_{i}"):
                    del st.session_state.party[i]; st.rerun()
            with box.expander("Attacks"):
                attacks = c.get("attacks", [])
                if not attacks:
                    st.write("No attacks listed.")
                else:
                    for a in attacks:
                        st.write(a)

# ===== MIDDLE: Encounter + Attack Roller + Chat =====
with mid:
    st.markdown("#### Encounter")
    if not st.session_state.enemies:
        st.caption("No enemies. Add on the right or below in setup.")
        # reminder: if this grows large, consider paging or filters by type/CR.
    else:
        for i, e in enumerate(st.session_state.enemies):
            card = st.container(border=True)
            h1, h2, h3, h4 = card.columns([4,2,2,2])
            with h1: st.markdown(f"**{e.get('name','')}**")
            with h2: e["ac"] = int(st.number_input("AC", 0, 40, int(e.get("ac",10)), key=f"e_ac_{i}"))
            with h3: e["hp"] = int(st.number_input("HP", 0, 500, int(e.get("hp",10)), key=f"e_hp_{i}"))
            with h4:
                if st.button("Remove", key=f"e_rm_{i}"):
                    del st.session_state.enemies[i]; st.rerun()
            with card.expander("Stat & Actions"):
                # Show SRD stat if present
                sb = next((m for m in st.session_state.get("srd_enemies", []) if m.get("name") == e.get("name") or m.get("name") == e.get("src")), None)
                if sb:
                    # tolerant renderer
                    name = sb.get("name","Unknown"); ac = sb.get("ac","—"); hp = sb.get("hp","—")
                    st.write(f"{name}: AC {ac}, HP {hp}")
                    # reminder: JSON entries may be partial; for full block see Bestiary browser.
                else:
                    st.write(e)

    # ---------------- Combat / Turn Tracker (ADD-ONLY) ----------------
st.markdown("### Combat Tracker")

cA, cB, cC = st.columns([2,1,1])

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
        next_turn()

with cC:
    if st.session_state.in_combat and st.button("End Combat"):
        end_combat()
        st.info("Combat ended.")

if st.session_state.initiative_order:
    st.markdown("**Initiative Order**")
    for i, ent in enumerate(st.session_state.initiative_order):
        marker = "➡️" if (i == st.session_state.turn_index and st.session_state.in_combat) else ""
        st.write(f"{marker} {ent['name']} — Init {ent['init']} (DEX mod {ent['dex_mod']})")

    st.markdown("#### Attack Roller")
    # Choose attacker (from enemies for now; could add PCs later)
    attackers = [(f"{idx+1}. {e['name']}", idx) for idx, e in enumerate(st.session_state.enemies)]
    if attackers:
        label_list = [lab for lab, _ in attackers]
        atk_choice = st.selectbox("Attacker", label_list)
        idx = dict(attackers)[atk_choice]
        att = st.session_state.enemies[idx]

        # Actions from SRD if available
        sb = next((m for m in st.session_state.get("srd_enemies", []) if m.get("name") == att.get("name") or m.get("name") == att.get("src")), None)
        actions = sb.get("actions", []) if sb else []
        action_names = [a.get("name","Action") for a in actions] + (["(Custom)"] if True else [])
        act = st.selectbox("Action", action_names, key="atk_act_sel")

        if act == "(Custom)":
            to_hit = st.number_input("To-Hit Bonus", -10, 20, 0, key="atk_custom_to")
            dmg = st.text_input("Damage Dice", value="1d6", key="atk_custom_dmg")
        else:
            aobj = next((a for a in actions if a.get("name")==act), None)
            to_hit = int(aobj.get("to_hit", 0)) if aobj else 0
            dmg = aobj.get("damage", "1d6") if aobj else "1d6"

        target_ac = st.number_input("Target AC", 0, 40, 13, key="atk_target_ac")
        if st.button("Roll Attack"):
            d20 = random.randint(1,20)
            total = d20 + to_hit
            hit = total >= int(target_ac)
            st.write(f"To-Hit: d20({d20}) + {to_hit} = **{total}** vs AC {target_ac} → {'**HIT**' if hit else '**MISS**'}")
            st.session_state.chat_log.append(("System", f"{att.get('name','Attacker')} attacks → {total} vs AC {target_ac} → {'HIT' if hit else 'MISS'}"))
            if hit:
                dmg_total, breakdown = roll_dice(dmg)
                st.write(f"Damage: {dmg} → **{dmg_total}** ({breakdown})")
                st.session_state.chat_log.append(("System", f"Damage: {dmg} → {dmg_total} ({breakdown})"))
    else:
        st.caption("No attackers available.")

    st.markdown("#### Chat")
    chat_box = st.container(border=True)
    with chat_box:
        c1, c2 = st.columns([6,1])
        with c1:
            user_msg = st.text_input("Type a message (e.g., 'attack the goblin', '/roll 2d6+1', 'talk about surrender')", key="chat_input")
        with c2:
            send = st.button("Send")
        if send and (msg := user_msg.strip()):
            # always record the player's message first
            st.session_state.chat_log.append(("Player", msg))

            # 1) First try to auto-resolve as a combat attack using the current actor
            result = resolve_attack(msg)

            if result is not None:
                st.session_state.chat_log.append(("System", result))
                # reminder: you can call next_turn() here later for auto-advance
            else:
                # 2) If it's not an attack, see if it looks like a skill-based action
                skill_result = resolve_skill_check(msg)

                if skill_result is not None:
                    st.session_state.chat_log.append(("System", skill_result))
                else:
                    # 3) Fall back to the normal DM-style dialogue / utility behavior
                    reply = reply_for(msg)

                    # inline rolls not using '/roll'
                    if not msg.lower().startswith("/roll") and "roll " in msg.lower():
                        more = extract_inline_rolls(msg)
                        if more:
                            lines = []
                            for d in more:
                                t, br = roll_dice(d)
                                lines.append(f"• {d}: {br}")
                            reply += "\n\nInline rolls:\n" + "\n".join(lines)

                    st.session_state.chat_log.append(("DM", reply))
            
        # reminder: for very long sessions, consider paging or showing last N per “turn”. 
        # this already is being an issue and needs resolved next. Stop forgetting.
        for speaker, text in st.session_state.chat_log[-60:]:
            if "\n" in text:
                st.markdown(f"**{speaker}:**\n{text}")
            else:
                st.markdown(f"**{speaker}:** {text}")

# ===== RIGHT: Controls =====
with right:
    st.markdown("#### Controls")
    st.selectbox("Difficulty", ["Story", "Easy", "Normal", "Hard", "Deadly"], key="difficulty")

    st.markdown("#### Add Enemy")
    with st.container(border=True):
        mode = st.radio("Add Mode", ["Manual", "From SRD"], horizontal=True, key="add_mode")

        if mode == "Manual":
            e1, e2 = st.columns([2,2])
            name = e1.text_input("Name", key="add_e_name")
            ac = e2.number_input("AC", 0, 40, 13, key="add_e_ac")
            e3, e4 = st.columns([2,2])
            hp = e3.number_input("HP", 0, 500, 11, key="add_e_hp")
            atk_name = e4.text_input("Attack Name", value="Attack", key="add_e_atk")
            e5, e6 = st.columns([2,2])
            to_hit = e5.number_input("To-Hit", -10, 20, 0, key="add_e_to")
            dmg = e6.text_input("Damage", value="1d6+0", key="add_e_dmg")

            if st.button("Add"):
                if name.strip():
                    st.session_state.enemies.append({
                        "name": name.strip(),
                        "ac": int(ac),
                        "hp": int(hp),
                        "attacks": [{"name": atk_name, "to_hit": int(to_hit), "damage": dmg}]
                    })
                    st.success(f"Added enemy: {name.strip()}")

        else:
            if not st.session_state.get("srd_enemies"):
                st.warning("SRD list not found (../data/SRD_Monsters.json).")
            else:
                names = [m["name"] for m in st.session_state.srd_enemies]
                srd_name = st.selectbox("SRD Creature", names, key="add_srd_name")
                count = st.number_input("Count", 1, 20, 1, key="add_srd_count")
                if st.button("Add From SRD"):
                    src = next((m for m in st.session_state.srd_enemies if m["name"] == srd_name), None)
                    if src:
                        for i in range(int(count)):
                            st.session_state.enemies.append({
                                "name": f"{src['name']}" if count == 1 else f"{src['name']} #{i+1}",
                                "ac": int(src.get("ac", 10)),
                                "hp": int(src.get("hp", 10)),
                                "attacks": src.get("attacks", [])
                            })
                        st.success(f"Added {int(count)} × {srd_name}")
                # reminder: Consider adding type/CR filters once SRD grows.

    st.markdown("#### Bestiary")
    with st.expander("Browse Monsters", expanded=False):
        if not st.session_state.get("srd_enemies"):
            st.caption("SRD not found.")
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