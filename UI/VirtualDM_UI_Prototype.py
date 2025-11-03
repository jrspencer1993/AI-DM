import random
import re
import csv
from datetime import datetime
import streamlit as st

st.set_page_config(page_title="Virtual DM – Week 3", layout="wide")

# ---------------- Bestiary (SRD-style, trimmed) ----------------
BESTIARY = {
    "Goblin": {
        "name": "Goblin", "size": "Small", "type": "Humanoid (Goblinoid)", "alignment": "Neutral Evil",
        "ac": 15, "hp": 7, "hit_dice": "2d6", "speed": "30 ft.",
        "abilities": {"STR": 8, "DEX": 14, "CON": 10, "INT": 10, "WIS": 8, "CHA": 8},
        "saves": {}, "skills": {"Stealth": "+6"}, "senses": "Darkvision 60 ft.", "languages": "Common, Goblin", "cr": "1/4",
        "traits": [
            ("Nimble Escape", "The goblin can take the Disengage or Hide action as a bonus action.")
        ],
        "actions": [
            ("Scimitar", {"to_hit": +4, "reach": "5 ft.", "targets": "one", "damage": "1d6+2 slashing"}),
            ("Shortbow", {"to_hit": +4, "range": "80/320 ft.", "targets": "one", "damage": "1d6+2 piercing"})
        ]
    },
    "Bandit": {
        "name": "Bandit", "size": "Medium", "type": "Humanoid (Any)", "alignment": "Any non-lawful",
        "ac": 12, "hp": 11, "hit_dice": "2d8+2", "speed": "30 ft.",
        "abilities": {"STR": 11, "DEX": 12, "CON": 12, "INT": 10, "WIS": 10, "CHA": 10},
        "saves": {}, "skills": {}, "senses": "Passive Perception 10", "languages": "Any one (usually Common)", "cr": "1/8",
        "traits": [],
        "actions": [
            ("Scimitar", {"to_hit": +3, "reach": "5 ft.", "targets": "one", "damage": "1d6+1 slashing"}),
            ("Light Crossbow", {"to_hit": +3, "range": "80/320 ft.", "targets": "one", "damage": "1d8+1 piercing"})
        ]
    },
    "Wolf": {
        "name": "Wolf", "size": "Medium", "type": "Beast", "alignment": "Unaligned",
        "ac": 13, "hp": 11, "hit_dice": "2d8+2", "speed": "40 ft.",
        "abilities": {"STR": 12, "DEX": 15, "CON": 12, "INT": 3, "WIS": 12, "CHA": 6},
        "saves": {}, "skills": {"Perception": "+3", "Stealth": "+4"}, "senses": "Passive Perception 13", "languages": "-", "cr": "1/4",
        "traits": [
            ("Keen Hearing and Smell", "The wolf has a +2 bonus to Perception checks that rely on hearing or smell."),
            ("Pack Tactics", "The wolf deals +2 to attack rolls if an ally is within 5 feet of the target.")
        ],
        "actions": [
            ("Bite", {"to_hit": +4, "reach": "5 ft.", "targets": "one", "damage": "2d4+2 piercing"})
        ]
    },
    "Skeleton": {
        "name": "Skeleton", "size": "Medium", "type": "Undead", "alignment": "Lawful Evil",
        "ac": 13, "hp": 13, "hit_dice": "2d8+4", "speed": "30 ft.",
        "abilities": {"STR": 10, "DEX": 14, "CON": 15, "INT": 6, "WIS": 8, "CHA": 5},
        "saves": {}, "skills": {}, "senses": "Darkvision 60 ft.", "languages": "Understands creator's languages", "cr": "1/4",
        "traits": [("Undead Fortitude (Suggestion)", "On 0 HP, roll to avoid destruction: DM adjudication in this prototype.")],
        "actions": [
            ("Shortsword", {"to_hit": +4, "reach": "5 ft.", "targets": "one", "damage": "1d6+2 piercing"}),
            ("Shortbow", {"to_hit": +4, "range": "80/320 ft.", "targets": "one", "damage": "1d6+2 piercing"})
        ]
    },
    "Orc": {
        "name": "Orc", "size": "Medium", "type": "Humanoid (Orc)", "alignment": "Chaotic Evil",
        "ac": 13, "hp": 15, "hit_dice": "2d8+6", "speed": "30 ft.",
        "abilities": {"STR": 16, "DEX": 12, "CON": 16, "INT": 7, "WIS": 11, "CHA": 10},
        "saves": {}, "skills": {"Intimidation": "+2"}, "senses": "Darkvision 60 ft.", "languages": "Orc", "cr": "1/2",
        "traits": [("Aggressive", "As a bonus action, the orc can move up to its speed toward a hostile creature it can see.")],
        "actions": [
            ("Greataxe", {"to_hit": +5, "reach": "5 ft.", "targets": "one", "damage": "1d12+3 slashing"}),
            ("Javelin (melee)", {"to_hit": +5, "reach": "5 ft.", "targets": "one", "damage": "1d6+3 piercing"}),
            ("Javelin (ranged)", {"to_hit": +5, "range": "30/120 ft.", "targets": "one", "damage": "1d6+3 piercing"})
        ]
    },
    "Ogre": {
        "name": "Ogre", "size": "Large", "type": "Giant", "alignment": "Chaotic Evil",
        "ac": 11, "hp": 59, "hit_dice": "7d10+21", "speed": "40 ft.",
        "abilities": {"STR": 19, "DEX": 8, "CON": 16, "INT": 5, "WIS": 7, "CHA": 7},
        "saves": {}, "skills": {}, "senses": "Darkvision 60 ft.", "languages": "Common, Giant", "cr": "2",
        "traits": [],
        "actions": [
            ("Greatclub", {"to_hit": +6, "reach": "5 ft.", "targets": "one", "damage": "2d8+4 bludgeoning"}),
            ("Javelin", {"to_hit": +6, "range": "30/120 ft.", "targets": "one", "damage": "2d6+4 piercing"})
        ]
    },
}

# ---------------- Utilities ----------------
def init_state():
    ss = st.session_state
    ss.setdefault("chat_log", [])
    ss.setdefault("world_log", "You descend into the Emerald Spire...")
    ss.setdefault("npc_text", "NPC: A raspy voice echoes: 'Turn back...'")
    ss.setdefault("player_text", "Player: We press on.")
    ss.setdefault("difficulty", "Normal")
    ss.setdefault("spawn_choice", "Goblin")
    ss.setdefault("encounters", [])  # list of dicts: name, hp, ac, src (bestiary key), id
    ss.setdefault("attack_attacker_idx", 0)
    ss.setdefault("attack_action_name", "")
    ss.setdefault("attack_target_ac", 15)
    ss.setdefault("session_id", datetime.now().strftime("%Y%m%d_%H%M%S"))

def roll_dice(expr: str) -> int:
    """
    Supports forms like: 2d6+3, d8+2, 1d12-1, 2d4, 7, etc.
    """
    expr = expr.strip().lower().replace(" ", "")
    m = re.fullmatch(r"(?:(\d*)d(\d+))?([+-]\d+)?", expr)
    if not m:
        return 0
    num = int(m.group(1)) if m.group(1) not in (None, "") else (1 if m.group(2) else 0)
    sides = int(m.group(2)) if m.group(2) else 0
    mod = int(m.group(3)) if m.group(3) else 0
    total = sum(random.randint(1, sides) for _ in range(num)) + mod
    return total

def attack_roll(to_hit_mod: int, target_ac: int) -> tuple[int, bool]:
    d20 = random.randint(1, 20)
    total = d20 + to_hit_mod
    return total, total >= target_ac

def save_session_csv():
    path = f"virtualdm_session_{st.session_state.session_id}.csv"
    rows = st.session_state.chat_log
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "speaker", "text"])
        for speaker, text in rows:
            writer.writerow([datetime.now().isoformat(timespec="seconds"), speaker, text])
    st.toast(f"Saved chat log → {path}")

def render_statblock(sb):
    st.markdown(f"**{sb['name']}** — {sb['size']} {sb['type']}, {sb['alignment']}")
    st.markdown(f"**Armor Class** {sb['ac']}  •  **Hit Points** {sb['hp']} ({sb['hit_dice']})  •  **Speed** {sb['speed']}")
    # Abilities
    a = sb["abilities"]
    st.markdown(
        f"STR {a['STR']}  |  DEX {a['DEX']}  |  CON {a['CON']}  |  INT {a['INT']}  |  WIS {a['WIS']}  |  CHA {a['CHA']}"
    )
    # Extras
    saves = ", ".join(f"{k} {v}" for k, v in sb["saves"].items()) if sb["saves"] else "—"
    skills = ", ".join(f"{k} {v}" for k, v in sb["skills"].items()) if sb["skills"] else "—"
    st.caption(f"Saves: {saves}  •  Skills: {skills}")
    st.caption(f"Senses: {sb['senses']}  •  Languages: {sb['languages']}  •  CR: {sb['cr']}")
    if sb["traits"]:
        with st.expander("Traits"):
            for name, txt in sb["traits"]:
                st.markdown(f"- **{name}.** {txt}")
    if sb["actions"]:
        with st.expander("Actions"):
            for name, data in sb["actions"]:
                line = f"**{name}.** +{data['to_hit']} to hit"
                if "reach" in data: line += f", reach {data['reach']}"
                if "range" in data: line += f", range {data['range']}"
                line += f"; {data.get('targets','one')} target. Hit: {data['damage']}."
                st.markdown(f"- {line}")

# ---------------- Init ----------------
init_state()

# ---------------- Top Bar ----------------
top_l, top_sp, top_r1, top_r2, top_r3 = st.columns([6,1,1,1,1])
with top_l:
    st.markdown("### **Emerald Spire — Week 3 Demo**")
with top_r1:
    if st.button("Save"):
        save_session_csv()
with top_r2:
    if st.button("Load"):
        st.toast("Loading is omitted in this prototype.")
with top_r3:
    if st.button("Settings"):
        st.toast("Settings (placeholder).")

st.divider()

# ---------------- Three-column main content ----------------
left, mid, right = st.columns([4,5,4])

# ===== LEFT: Narrative =====
with left:
    st.markdown("#### **NARRATIVE**")
    st.text_area("NPC", key="npc_text", height=150, label_visibility="collapsed")
    st.text_area("Player", key="player_text", height=120, label_visibility="collapsed")

    btn_l, btn_c, btn_r = st.columns([1,1,2])
    with btn_l:
        if st.button("Approve"):
            st.success("Narrative approved.")
            st.session_state.chat_log.append(("SYSTEM", "Narrative approved."))
    with btn_c:
        if st.button("Edit"):
            st.info("Edit acknowledged.")
    with btn_r:
        if st.button("Regenerate"):
            st.session_state.npc_text = "NPC: The goblin snarls and charges!"
            st.toast("Regenerated NPC line.")

# ===== MIDDLE: Encounter Tracker + Attack Roller =====
with mid:
    st.markdown("#### **ENCOUNTER TRACKER**")

    # Creature cards
    if not st.session_state.encounters:
        st.caption("No creatures in the encounter. Use 'Game Master Controls' to spawn.")

    for idx, unit in enumerate(st.session_state.encounters):
        card = st.container(border=True)
        header = card.columns([5,2,2,2])
        with header[0]:
            st.markdown(f"**{unit['name']}**")
            st.caption(f"AC {unit['ac']} • HP {unit['hp']} • Source: {unit['src']}")
        with header[1]:
            new_hp = st.number_input("HP", value=int(unit["hp"]), key=f"hp_{idx}", step=1, label_visibility="collapsed")
            unit["hp"] = int(new_hp)
        with header[2]:
            if st.button("View", key=f"view_{idx}"):
                st.session_state.chat_log.append(("SYSTEM", f"Viewed statblock: {unit['name']}"))
                st.toast(f"Viewing {unit['name']}")
        with header[3]:
            if st.button("Remove", key=f"del_{idx}"):
                del st.session_state.encounters[idx]
                st.experimental_rerun()

        # Inline statblock preview
        with card.expander("Statblock", expanded=False):
            sb = BESTIARY.get(unit["src"])
            if sb:
                render_statblock(sb)
            else:
                st.write("No statblock found.")

    st.markdown("#### **ATTACK ROLLER**")
    if st.session_state.encounters:
        col1, col2 = st.columns([3,3])
        with col1:
            attacker_idx = st.selectbox(
                "Attacker",
                options=list(range(len(st.session_state.encounters))),
                format_func=lambda i: f"{i+1}. {st.session_state.encounters[i]['name']}",
                key="attack_attacker_idx"
            )
        with col2:
            target_ac = st.number_input("Target AC", value=int(st.session_state.attack_target_ac), step=1, key="attack_target_ac")

        # Actions from the attacker's statblock
        attacker = st.session_state.encounters[attacker_idx]
        sb = BESTIARY.get(attacker["src"])
        action_names = [a[0] for a in sb["actions"]] if sb and sb.get("actions") else []
        act_col1, act_col2 = st.columns([3,1])
        with act_col1:
            action_name = st.selectbox("Action", options=action_names, key="attack_action_name")
        with act_col2:
            roll_btn = st.button("Roll Attack")

        if roll_btn and action_name:
            # Find the action
            action = next((a for a in sb["actions"] if a[0] == action_name), None)
            if action:
                to_hit = action[1]["to_hit"]
                dmg_expr = action[1]["damage"]
                total, is_hit = attack_roll(to_hit, int(st.session_state.attack_target_ac))
                line = f"{attacker['name']} uses **{action_name}** → d20+{to_hit} = **{total}** vs AC {st.session_state.attack_target_ac} — {'**Hit!**' if is_hit else '**Miss**'}"
                st.success(line) if is_hit else st.warning(line)
                st.session_state.chat_log.append(("DM", line))
                if is_hit:
                    dmg = 0
                    # Extract the first dice expression e.g., 2d6+3 from the text "2d6+3 piercing"
                    m = re.match(r"([0-9]*d[0-9]+(?:[+-][0-9]+)?)", dmg_expr.replace(" ", ""))
                    if m:
                        dmg = roll_dice(m.group(1))
                    dmg_line = f"Damage: **{dmg}** ({dmg_expr})"
                    st.info(dmg_line)
                    st.session_state.chat_log.append(("DM", dmg_line))
            else:
                st.error("Action not found for attacker.")

# ===== RIGHT: GM Controls + World Log + Bestiary Viewer =====
with right:
    st.markdown("#### **GAME MASTER CONTROLS**")
    with st.container(border=True):
        st.selectbox("Monster", sorted(BESTIARY.keys()), key="spawn_choice")
        st.selectbox("Difficulty", ["Story", "Easy", "Normal", "Hard", "Deadly"], key="difficulty")
        if st.button("Add to Encounter"):
            src = st.session_state.spawn_choice
            sb = BESTIARY[src]
            entry = {
                "name": sb["name"],
                "hp": sb["hp"],
                "ac": sb["ac"],
                "src": src,
                "id": f"{src}-{random.randint(1000,9999)}"
            }
            st.session_state.encounters.append(entry)
            st.toast(f"Spawned {src} (AC {sb['ac']}, HP {sb['hp']})")

    st.markdown("#### **WORLD LOG**")
    st.text_area("", key="world_log", height=240, label_visibility="collapsed")

    st.markdown("#### **BESTIARY**")
    with st.expander("Browse Monsters", expanded=False):
        pick = st.selectbox("View statblock", sorted(BESTIARY.keys()), key="bestiary_pick")
        render_statblock(BESTIARY[pick])

st.divider()

# ---------------- Bottom: Chat ----------------
st.markdown("#### **CHAT**")
chat_box = st.container(border=True)
with chat_box:
    chat_cols = st.columns([6,1])
    with chat_cols[0]:
        user_msg = st.text_input("Type a message (e.g., 'I attack the goblin!')", key="chat_input")
    with chat_cols[1]:
        send = st.button("Send")

    if send and user_msg.strip():
        st.session_state.chat_log.append(("Player1", user_msg.strip()))
        # Simple rule-based reply (no ML yet)
        text = user_msg.lower()
        if "attack" in text or "hit" in text:
            reply = "DM: Roll to hit. Declare your target and weapon."
        elif "talk" in text or "speak" in text or "ask" in text:
            reply = "DM: The NPC eyes you warily—what do you say?"
        elif "search" in text or "investigate" in text or "look" in text:
            reply = "DM: Make a check; tell me where and how you search."
        else:
            reply = "DM: Noted. What do you do next?"
        st.session_state.chat_log.append(("DM", reply))
        st.session_state.chat_input = ""

    # Render chat history (last 50)
    for speaker, text in st.session_state.chat_log[-50:]:
        st.markdown(f"**{speaker}:** {text}")