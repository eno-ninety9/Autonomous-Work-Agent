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

    runs = memory.get_runs(limit=50)
    run_ids = [r[0] for r in runs] if runs else []

    # Default selected run
    if "selected_run" not in st.session_state and run_ids:
        st.session_state.selected_run = run_ids[0]

    selected_run = st.selectbox(
        "Run auswählen",
        options=run_ids,
        index=run_ids.index(st.session_state.selected_run) if run_ids and st.session_state.selected_run in run_ids else 0,
        format_func=lambda rid: f"Run #{rid}"
    ) if run_ids else None

    if selected_run:
        st.session_state.selected_run = selected_run

    st.divider()
    st.subheader("🔎 Aktivität")

    if selected_run:
        events = memory.get_events(selected_run, limit=300)
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
        st.caption("Noch keine Runs vorhanden.")

# ------------------------
# RIGHT: Task + Output
# ------------------------
with right:
    st.subheader("Aufgabe")
    goal = st.text_area("Was soll der Agent tun?", height=140)

    colA, colB = st.columns([0.25, 0.75])
    with colA:
        start = st.button("Start Agent")

    if start:
        if not goal.strip():
            st.warning("Bitte Aufgabe eingeben.")
            st.stop()

        run_id = memory.add_run(goal, "")
        st.session_state.selected_run = run_id

        status = st.status("🧠 Agent arbeitet...", expanded=True)
        status.write("PLAN → RESEARCH → EXECUTE → FINAL")

        try:
            result = agent.run(goal, run_id=run_id)
            final_text = result.get("result", "") or ""
            memory.update_run_final(run_id, final_text)
            status.update(label="✅ Fertig", state="complete", expanded=False)
        except Exception as e:
            status.update(label="❌ Fehler", state="error", expanded=True)
            st.error(f"Agent Fehler: {e}")
            st.stop()

        st.rerun()

    # --- Always show selected run output (Manus-like) ---
    st.divider()
    st.subheader("Result (ausgewählter Run)")

    if "selected_run" in st.session_state and st.session_state.selected_run:
        row = memory.get_run(st.session_state.selected_run)
        if row:
            _, ts, saved_goal, final_answer = row
            st.caption(f"Run #{st.session_state.selected_run} • {time.strftime('%d.%m.%Y %H:%M:%S', time.localtime(ts))}")
            with st.expander("Aufgabe (gespeichert)", expanded=False):
                st.write(saved_goal)

            if final_answer and final_answer.strip():
                st.write(final_answer)
            else:
                st.info("Noch kein Ergebnis gespeichert (oder Modell hat leer geantwortet).")
        else:
            st.info("Run nicht gefunden.")
    else:
        st.info("Starte einen Run oder wähle links einen aus.")
