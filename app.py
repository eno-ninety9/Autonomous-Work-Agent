import os
import sys
import time
import streamlit as st

# ensure local imports work
ROOT = os.path.abspath(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.config import AgentConfig
from agent.memory import AgentMemory
from agent.orchestrator import ManusAgent

# ------------------------
# Streamlit page
# ------------------------

st.set_page_config(
    page_title="Cloud Manus",
    layout="wide"
)

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

        if pw == APP_PASSWORD:
            st.session_state.auth = True
            st.rerun()

        else:
            st.error("Falsches Passwort")

    st.stop()

# ------------------------
# Check API Key
# ------------------------

if not os.getenv("OPENROUTER_API_KEY"):
    st.error("OPENROUTER_API_KEY fehlt in Streamlit Secrets")
    st.stop()

# ------------------------
# Agent Setup
# ------------------------

config = AgentConfig()

memory = AgentMemory(config.memory_db_path)

agent = ManusAgent(config, memory=memory)

# ------------------------
# Sidebar Settings
# ------------------------

with st.sidebar:

    st.header("⚙️ Einstellungen")

    model = st.text_input(
        "Model",
        value=os.getenv("OPENAI_MODEL", config.model)
    )

    max_loops = st.slider(
        "Max loops",
        1,
        15,
        config.max_loops
    )

    config.model = model
    config.max_loops = max_loops

    st.divider()

    if st.button("Logout"):
        st.session_state.auth = False
        st.rerun()

# ------------------------
# Layout
# ------------------------

left, right = st.columns([0.35, 0.65])

# ------------------------
# LEFT PANEL
# ------------------------

with left:

    st.subheader("📜 Runs")

    runs = memory.get_runs()

    run_ids = [r[0] for r in runs]

    selected_run = None

    if run_ids:

        selected_run = st.selectbox(
            "Run auswählen",
            run_ids,
            format_func=lambda x: f"Run #{x}"
        )

    st.divider()

    if selected_run:

        st.subheader("🔎 Aktivität")

        events = memory.get_events(selected_run)

        for ts, kind, data in events[-60:]:

            t = time.strftime("%H:%M:%S", time.localtime(ts))

            if kind == "plan":

                st.write(f"**{t}** 🧠 Plan erstellt")

            elif kind == "tool_request":

                st.write(
                    f"**{t}** 🛠️ Tool: `{data.get('name')}`"
                )

            elif kind == "tool_result":

                st.write(
                    f"**{t}** ✅ Tool result: `{data.get('name')}`"
                )

            elif kind == "final":

                st.write(
                    f"**{t}** 🎉 Ergebnis erzeugt"
                )

# ------------------------
# RIGHT PANEL
# ------------------------

with right:

    st.subheader("Aufgabe")

    goal = st.text_area(
        "Was soll der Agent tun?",
        height=120
    )

    if st.button("Start Agent"):

        if not goal.strip():
            st.warning("Bitte Aufgabe eingeben")
            st.stop()

        # create run
        run_id = memory.add_run(goal, "")

        status = st.status(
            "🧠 Agent arbeitet...",
            expanded=True
        )

        status.write("PLAN → RESEARCH → EXECUTE")

        try:
            result = agent.run(goal, run_id=run_id)
            status.update(label="✅ Fertig", state="complete", expanded=False)
        except Exception as e:
            status.update(label="❌ Fehler", state="error", expanded=True)
            st.error(f"Agent Fehler: {e}")
            st.stop()



        status.update(
            label="✅ Fertig",
            state="complete"
        )

        st.subheader("Plan")

        st.json(result["plan"])

        st.subheader("Result")

        st.write(result["result"])

        if result.get("sources"):

            with st.expander("Quellen"):

                for s in result["sources"]:

                    st.write(
                        f"- {s.get('title','Quelle')} : {s.get('url')}"
                    )

        if result.get("assumptions"):

            with st.expander("Annahmen"):

                for a in result["assumptions"]:

                    st.write(f"- {a}")

        st.rerun()

