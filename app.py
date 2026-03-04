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
# Check API key
# ------------------------
if not os.getenv("OPENROUTER_API_KEY"):
    st.error("OPENROUTER_API_KEY fehlt in Streamlit Secrets")
    st.stop()

# ------------------------
# Setup
# ------------------------
config = AgentConfig()
memory = AgentMemory(config.memory_db_path)

st.title("🧠 Cloud Manus Agent")
st.caption("PLAN → RESEARCH → EXECUTE → FINAL (mit sichtbarer Aktivität)")

with st.sidebar:
    st.header("⚙️ Einstellungen")

    model = st.text_input("Model", value=os.getenv("OPENAI_MODEL", config.model))
    max_loops = st.slider("Max loops", 1, 20, int(config.max_loops))
    max_tool_calls = st.slider("Max tool calls", 1, 20, int(getattr(config, "max_tool_calls", 4)))

    config.model = model
    config.max_loops = int(max_loops)
    config.max_tool_calls = int(max_tool_calls)

    st.divider()
    if st.button("Logout"):
        st.session_state.auth = False
        st.rerun()

agent = ManusAgent(config, memory=memory)

left, right = st.columns([0.40, 0.60], gap="large")

# ------------------------
# LEFT: Runs + Activity
# ------------------------
with left:
    st.subheader("📜 Runs")

    runs = memory.get_runs(limit=30)
    run_ids = [r[0] for r in runs] if runs else []

    selected_run = None
    if run_ids:
        selected_run = st.selectbox("Run auswählen", run_ids, format_func=lambda rid: f"Run #{rid}")
    else:
        st.info("Noch keine Runs.")

    st.divider()
    st.subheader("🔎 Aktivität")

    if selected_run:
        events = memory.get_events(selected_run, limit=300)
        for ts, kind, data in events[-120:]:
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
        st.caption("Wähle einen Run aus, um die Timeline zu sehen.")

# ------------------------
# RIGHT: Task + Output
# ------------------------
with right:
    st.subheader("Aufgabe")
    goal = st.text_area("Was soll der Agent tun?", height=140)

    start = st.button("Start Agent")
    if start:
        if not goal.strip():
            st.warning("Bitte Aufgabe eingeben.")
            st.stop()

        run_id = memory.add_run(goal, "")
        status = st.status("🧠 Agent arbeitet...", expanded=True)
        status.write("PLAN → RESEARCH → EXECUTE → FINAL")

        try:
            result = agent.run(goal, run_id=run_id)
            status.update(label="✅ Fertig", state="complete", expanded=False)
        except Exception as e:
            status.update(label="❌ Fehler", state="error", expanded=True)
            st.error(f"Agent Fehler: {e}")
            st.stop()

        st.subheader("Plan")
        st.json(result.get("plan", {}))

        st.subheader("Result")
        if result.get("result"):
            st.write(result["result"])
        else:
            st.warning("Kein Ergebnistext zurückgegeben.")

        if result.get("sources"):
            with st.expander("Quellen"):
                for s in result["sources"]:
                    st.write(f"- {s.get('title','Quelle')}: {s.get('url')}")

        if result.get("assumptions"):
            with st.expander("Annahmen"):
                for a in result["assumptions"]:
                    st.write(f"- {a}")

        st.rerun()
