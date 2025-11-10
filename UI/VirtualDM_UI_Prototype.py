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
SRD_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "SRD_Monsters.json")

def load_srd_monsters():
    """
    Load SRD monsters once per session into st.session_state.srd_enemies.
    Tolerant schema: entries may be minimal; renderer guards missing fields.
    """
    if "srd_enemies" in st.session_state:
        return
    try:
        with open(SRD_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                st.session_state.srd_enemies = [m for m in data if isinstance(m, dict) and m.get("name")]
            else:
                st.session_state.srd_enemies = []
    except Exception:
        st.session_state.srd_enemies = []

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
# Minimal D&D 5e sheet shape used here
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
    t_upload, t_paste, t_form = st.tabs(["Upload JSON", "Paste JSON", "Manual Entry"])

    with t_upload:
        up_chars = st.file_uploader("Upload one or more 5e character sheets", type=["json"], accept_multiple_files=True)
        if up_chars:
            added = 0
            for f in up_chars:
                try:
                    blob = json.load(f)
                    char = coerce_5e_sheet(blob)
                    if char.get("name"):
                        st.session_state.party.append(char); added += 1
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
            with colA: ac = st.number_input("AC", 0, 40, 10)
            with colB: hp = st.number_input("HP", 0, 500, 10)
            with colC: spd = st.text_input("Speed", value="30 ft.")
            with colD: lng = st.text_input("Languages", value="Common")

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

    st.markdown("#### Current Party")
    if not st.session_state.party:
        st.info("No party members yet.")
    else:
        for i, c in enumerate(st.session_state.party):
            box = st.container(border=True)
            h1, h2, h3, h4 = box.columns([4,2,2,2])
            with h1: st.markdown(f"**{c.get('name','')}**")
            with h2: c["ac"] = int(st.number_input("AC", 0, 40, int(c.get("ac",10)), key=f"p_ac_{i}"))
            with h3: c["hp"] = int(st.number_input("HP", 0, 500, int(c.get("hp",10)), key=f"p_hp_{i}"))
            with h4:
                if st.button("Remove", key=f"p_rm_{i}"):
                    del st.session_state.party[i]
                    st.experimental_rerun()
            with box.expander("Details"):
                a = c.get("abilities", {})
                st.write(f"Speed: {c.get('speed','')}")
                st.write("Abilities:", a)
                st.write("Attacks:", c.get("attacks", []))

    st.markdown("#### Enemies")
    with st.container(border=True):
        # Manual entry (kept)
        e1, e2, e3, e4, e5 = st.columns([4,2,2,2,2])
        e_name = e1.text_input("Name", key="e_name")
        e_ac = e2.number_input("AC", 0, 40, 13, key="e_ac")
        e_hp = e3.number_input("HP", 0, 500, 11, key="e_hp")
        e_atk = e4.text_input("Attack (e.g., 'Bite', +4, '2d4+2')", key="e_atk")
        add_enemy = e5.button("Add Enemy")
        if add_enemy and e_name.strip():
            st.session_state.enemies.append({
                "name": e_name.strip(),
                "ac": int(e_ac),
                "hp": int(e_hp),
                "attacks": [{"name": e_atk or "Attack", "to_hit": 0, "damage": "1d6"}]
            })
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
                        st.session_state.enemies.append({
                            "name": f"{src['name']}" if srd_count == 1 else f"{src['name']} #{i+1}",
                            "ac": int(src.get("ac", 10)),
                            "hp": int(src.get("hp", 10)),
                            "attacks": src.get("attacks", [])
                        })
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
                    del st.session_state.party[i]; st.experimental_rerun()
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
                    del st.session_state.enemies[i]; st.experimental_rerun()
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
            st.session_state.chat_log.append(("Player", msg))
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
            st.session_state.chat_input = ""
        # reminder: for very long sessions, consider paging or showing last N per “turn”.
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