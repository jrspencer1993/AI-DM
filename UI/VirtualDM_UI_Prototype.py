import random
import streamlit as st

st.set_page_config(page_title="Virtual DM – Prototype", layout="wide")

# ---------- Session State ----------
def _init_state():
    ss = st.session_state
    ss.setdefault("chat_log", [])            # [(speaker, text)]
    ss.setdefault("world_log", "Quest...")
    ss.setdefault("npc_text", "NPC: ...")
    ss.setdefault("player_text", "Player: ...")
    ss.setdefault("encounters", [
        {"name": "Fighter", "hp": 32},
        {"name": "Goblin", "hp": 12},
        {"name": "Wizard", "hp": 18},
    ])
    ss.setdefault("difficulty", "Normal")
    ss.setdefault("spawn_choice", "Goblin")

_init_state()

# ---------- Top Bar ----------
top_l, top_c, top_r1, top_r2, top_r3 = st.columns([6,1,1,1,1])
with top_l:
    st.markdown("### **Emerald Spire — Session 3**")
with top_r1:
    if st.button("Save"):
        st.toast("Saved session (placeholder).")
with top_r2:
    if st.button("Load"):
        st.toast("Loaded session (placeholder).")
with top_r3:
    if st.button("Settings"):
        st.toast("Settings (placeholder).")

st.divider()

# ---------- Three-column main content ----------
left, mid, right = st.columns([4,5,4])

# ===== LEFT: Narrative =====
with left:
    st.markdown("#### **NARRATIVE**")

    st.text_area("NPC", key="npc_text", height=150, label_visibility="collapsed")
    st.text_area("Player", key="player_text", height=120, label_visibility="collapsed")

    btn_l, btn_c, btn_r = st.columns([1,1,2])
    with btn_l:
        if st.button("Approve"):
            st.success("Narrative approved (placeholder).")
    with btn_c:
        if st.button("Edit"):
            st.info("Edit acknowledged (placeholder).")
    with btn_r:
        if st.button("Regenerate"):
            st.session_state.npc_text = "NPC: The goblin snarls and charges!"
            st.toast("Regenerated NPC line.")

# ===== MIDDLE: Encounter Tracker + Dice =====
with mid:
    st.markdown("#### **ENCOUNTER TRACKER**")

    # Character cards
    for idx, unit in enumerate(st.session_state.encounters):
        card = st.container(border=True)
        cols = card.columns([1,5,2])
        with cols[0]:
            st.checkbox("", key=f"ct_{idx}", value=False)
        with cols[1]:
            st.markdown(f"**{unit['name']}**")
        with cols[2]:
            # HP stepper
            new_hp = st.number_input("HP", value=unit["hp"], key=f"hp_{idx}", step=1, label_visibility="collapsed")
            unit["hp"] = int(new_hp)

    # Dice Rolls / Mini-Map placeholder
    box = st.container(border=True)
    with box:
        st.markdown("**Dice Rolls / Mini-Map** *(prototype)*")
        atk_col1, atk_col2, atk_col3, atk_col4 = st.columns([2,2,2,3])
        with atk_col1:
            mod = st.number_input("Attack Mod", value=5, step=1)
        with atk_col2:
            target = st.number_input("Target AC", value=15, step=1)
        with atk_col3:
            roll_btn = st.button("Roll Attack")
        with atk_col4:
            st.caption("Uses d20 + mod vs AC")

        if roll_btn:
            d20 = random.randint(1,20)
            total = d20 + int(mod)
            hit = total >= int(target)
            result = f"→ d20 ({d20:+}) + {mod} = **{total}**  — {'**Hit!**' if hit else '**Miss**'}"
            st.session_state.chat_log.append(("SYSTEM", result))
            st.success(result)

# ===== RIGHT: GM Controls + World Log =====
with right:
    st.markdown("#### **GAME MASTER CONTROLS**")
    with st.container(border=True):
        st.selectbox("Spawn NPC", ["Goblin", "Bandit", "Wolf", "Cultist"], key="spawn_choice")
        st.selectbox("Difficulty", ["Story", "Easy", "Normal", "Hard", "Deadly"], key="difficulty")
        if st.button("Apply"):
            st.toast(f"Spawn '{st.session_state.spawn_choice}', Difficulty: {st.session_state.difficulty}")

    st.markdown("#### **WORLD LOG**")
    st.text_area("", key="world_log", height=300, label_visibility="collapsed")

st.divider()

# ---------- Bottom: Chat ----------
st.markdown("#### **CHAT**")
chat_box = st.container(border=True)
with chat_box:
    chat_cols = st.columns([6,1])
    with chat_cols[0]:
        user_msg = st.text_input("Type a message (e.g., 'I attack!')", key="chat_input")
    with chat_cols[1]:
        send = st.button("Send")

    if send and user_msg.strip():
        st.session_state.chat_log.append(("Player1", user_msg.strip()))
        # Placeholder DM reply
        reply = f"DM: '{user_msg.strip()}' → d20 roll placeholder. (Real AI comes in Milestone 2)"
        st.session_state.chat_log.append(("DM", reply))
        st.session_state.chat_input = ""

    # Render chat history
    for speaker, text in st.session_state.chat_log[-50:]:
        st.markdown(f"**{speaker}:** {text}")