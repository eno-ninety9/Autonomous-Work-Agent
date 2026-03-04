import os
import sys
import time
import streamlit as st

ROOT = os.path.abspath(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.config import AgentConfig
from agent.memory import AgentMemory
from agent.orchestrator import ManusAgent

st.set_page_config(page_title="Cloud Manus", layout="wide")

# ------------------------
# Login
# ------------------------
APP_PASSWORD = os.getenv("APP_PASSWORD")

if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Login")
    pw = st.text_input("Passwort", type="password")
    if st.button("Login"):
        if APP_PASSWORD and pw == APP_PASSWORD:
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("Falsches Passwort")
    st.stop()

# ------------------------
# Key check
# ------------------------
if not os.getenv("OPENROUTER_API_KEY"):
    st.error("OPENROUTER_API_KEY fehlt in Streamlit Secrets")
    st.stop()

# ------------------------
# Setup
# ------------------------
config = AgentConfig()
memory = AgentMemory(config.memory_db_path)

with st.sidebar:
    st.header("⚙️ Einstellungen")
    model = st.text_input("Model", value=os.getenv("OPENAI_MODEL", config.model))
    max_loops = st.slider("Max loops", 1, 30, int(config.max_loops))
    max_tool_calls = st.slider("Max tool calls", 1, 30, int(config.max_tool_calls))
    search_results = st.slider("Search results", 3, 12, int(config.search_results))
    pages_to_read = st.slider("Pages to read", 1, 6, int(config.pages_to_read))

    config.model = model
    config.max_loops = int(max_loops)
    config.max_tool_calls = int(max_tool_calls)
    config.search_results = int(search_results)
    config.pages_to_read = int(pages_to_read)

    st.divider()
    if st.button("Logout"):
        st.session_state.auth = False
        st.rerun()

agent = ManusAgent(config, memory=memory)

st.title("🧠 Cloud Manus Agent")
st.caption("Research v2 • Chat + Aktivität + Quellen + Report")

left, right = st.columns([0.38, 0.62], gap="large")

# ------------------------
# LEFT: Runs + Activity
# ------------------------
with left:
    st.subheader("📜 Runs")

    runs = memory.get_runs(limit=60)
    run_ids = [r[0] for r in runs] if runs else []

    if "selected_run" not in st.session_state:
        st.session_state.selected_run = run_ids[0] if run_ids else None

    col1, col2 = st.columns([0.7, 0.3])
    with col1:
        selected_run = st.selectbox(
            "Run auswählen",
            options=run_ids,
            index=run_ids.index(st.session_state.selected_run) if st.session_state.selected_run in run_ids else 0,
            format_func=lambda rid: f"Run #{rid}",
            disabled=(len(run_ids) == 0),
        ) if run_ids else None

    with col2:
        if st.button("➕ Neu"):
            new_id = memory.create_run("New chat")
            st.session_state.selected_run = new_id
            st.rerun()

    if selected_run:
        st.session_state.selected_run = selected_run

    st.divider()
    st.subheader("🔎 Aktivität")

    if st.session_state.selected_run:
        events = memory.get_events(st.session_state.selected_run, limit=500)
        for ts, kind, data in events[-140:]:
            t = time.strftime("%H:%M:%S", time.localtime(ts))
            if kind == "plan":
                st.write(f"**{t}** 🧩 Plan erstellt")
            elif kind == "tool_request":
                st.write(f"**{t}** 🛠️ Tool: `{data.get('name','?')}`")
            elif kind == "tool_result":
                st.write(f"**{t}** ✅ Tool result: `{data.get('name','?')}`")
            elif kind == "forced_final":
                st.write(f"**{t}** 🧨 Forced final ({data.get('reason')})")
            elif kind == "final":
                st.write(f"**{t}** 🎉 Final")
            elif kind == "model_text_fallback":
                st.write(f"**{t}** ⚠️ Fallback (non-JSON)")
            else:
                st.write(f"**{t}** {kind}")
    else:
        st.info("Erstelle einen neuen Run (➕ Neu).")

# ------------------------
# RIGHT: Chat
# ------------------------
with right:
    st.subheader("💬 Chat")

    run_id = st.session_state.selected_run
    if not run_id:
        st.info("Bitte links einen Run auswählen oder auf ➕ Neu klicken.")
        st.stop()

    # render chat history
    raw_msgs = memory.get_messages(run_id, limit=300)
    chat_history = []
    for ts, role, content in raw_msgs:
        chat_history.append({"role": role, "content": content})

    for m in chat_history:
        with st.chat_message("user" if m["role"] == "user" else "assistant"):
            st.markdown(m["content"])

    # chat input
    user_text = st.chat_input("Schreib eine Nachricht… (du kannst jederzeit nachfragen)")
    if user_text:
        # save user message
        memory.add_message(run_id, "user", user_text)

        # show immediately
        with st.chat_message("user"):
            st.markdown(user_text)

        status = st.status("🧠 Agent arbeitet…", expanded=True)
        status.write("PLAN → SEARCH → READ → NOTES → REPORT")

        try:
            # agent needs history INCLUDING new message (re-read from DB)
            raw_msgs2 = memory.get_messages(run_id, limit=300)
            hist2 = [{"role": r, "content": c} for _, r, c in raw_msgs2]

            assistant_text = agent.run_chat(run_id=run_id, user_message=user_text, chat_history=hist2)

            # save assistant message
            memory.add_message(run_id, "assistant", assistant_text)

            # also store run final_answer as last assistant message for convenience
            memory.update_run_final(run_id, assistant_text)

            status.update(label="✅ Fertig", state="complete", expanded=False)

        except Exception as e:
            status.update(label="❌ Fehler", state="error", expanded=True)
            st.error(f"Agent Fehler: {e}")
            st.stop()

        st.rerun()
