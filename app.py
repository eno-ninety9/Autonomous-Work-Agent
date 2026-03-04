import os
import sys
import time
import glob
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
st.caption("ChatGPT-Style Chat + Manus Research Inspector (Tasks/URLs/Preview/Files)")

# 3-column layout: left runs, middle chat, right inspector
col_left, col_chat, col_inspector = st.columns([0.28, 0.44, 0.28], gap="large")

# ------------------------
# LEFT: Runs + Activity timeline
# ------------------------
with col_left:
    st.subheader("📜 Runs")

    runs = memory.get_runs(limit=80)
    run_ids = [r[0] for r in runs] if runs else []

    if "selected_run" not in st.session_state:
        st.session_state.selected_run = run_ids[0] if run_ids else None

    c1, c2 = st.columns([0.7, 0.3])
    with c1:
        selected_run = st.selectbox(
            "Run auswählen",
            options=run_ids,
            index=run_ids.index(st.session_state.selected_run) if st.session_state.selected_run in run_ids else 0,
            format_func=lambda rid: f"Run #{rid}",
            disabled=(len(run_ids) == 0),
        ) if run_ids else None
    with c2:
        if st.button("➕ Neu"):
            new_id = memory.create_run("New chat")
            st.session_state.selected_run = new_id
            st.rerun()

    if selected_run:
        st.session_state.selected_run = selected_run

    st.divider()
    st.subheader("🔎 Aktivität")

    if st.session_state.selected_run:
        events = memory.get_events(st.session_state.selected_run, limit=800)
        for ts, kind, data in events[-160:]:
            t = time.strftime("%H:%M:%S", time.localtime(ts))
            if kind == "phase":
                st.write(f"**{t}** 🧭 Phase: `{data.get('value')}`")
            elif kind == "plan":
                st.write(f"**{t}** 🧩 Plan erstellt")
            elif kind == "tool_request":
                st.write(f"**{t}** 🛠️ Tool: `{data.get('name')}`")
            elif kind == "visit":
                st.write(f"**{t}** 🌐 Besuch: {data.get('url')}")
            elif kind == "preview":
                st.write(f"**{t}** 📄 Preview: {data.get('title','')[:60]}")
            elif kind == "final":
                st.write(f"**{t}** 🎉 Final")
            elif kind == "forced_final":
                st.write(f"**{t}** 🧨 Forced final ({data.get('reason')})")
            elif kind == "model_text_fallback":
                st.write(f"**{t}** ⚠️ Fallback (non-JSON)")
            else:
                st.write(f"**{t}** {kind}")
    else:
        st.info("Erstelle einen Run (➕ Neu).")

# ------------------------
# MIDDLE: Chat (ChatGPT-like)
# ------------------------
with col_chat:
    st.subheader("💬 Chat")

    run_id = st.session_state.selected_run
    if not run_id:
        st.info("Bitte links einen Run auswählen oder auf ➕ Neu klicken.")
        st.stop()

    raw_msgs = memory.get_messages(run_id, limit=400)
    chat_history = [{"role": role, "content": content} for _, role, content in raw_msgs]

    for m in chat_history:
        with st.chat_message("user" if m["role"] == "user" else "assistant"):
            st.markdown(m["content"])

    user_text = st.chat_input("Schreib eine Nachricht… (du kannst jederzeit nachfragen)")
    if user_text:
        memory.add_message(run_id, "user", user_text)
        with st.chat_message("user"):
            st.markdown(user_text)

        # Live inspector placeholders (right column will read from session_state)
        st.session_state.live_phase = "START"
        st.session_state.live_url = ""
        st.session_state.live_preview_title = ""
        st.session_state.live_preview_text = ""
        st.session_state.live_tasks = {}
        st.session_state.live_log = []

        def progress_cb(evt):
            # store latest info for inspector
            kind = evt.get("type")
            if kind == "phase":
                st.session_state.live_phase = evt.get("value", "")
            elif kind == "visit":
                st.session_state.live_url = evt.get("url", "")
            elif kind == "preview":
                st.session_state.live_preview_title = evt.get("title", "")
                st.session_state.live_preview_text = evt.get("text", "")
            elif kind == "task_counts":
                st.session_state.live_tasks = {
                    "plan_steps": evt.get("plan_steps"),
                    "search_tasks": evt.get("search_tasks"),
                    "pages_visited": evt.get("pages_visited"),
                    "extracts_made": evt.get("extracts_made"),
                    "notes": evt.get("notes"),
                }
            # log line
            line = f"{kind}: " + ", ".join([f"{k}={v}" for k, v in evt.items() if k not in ("type",)])
            st.session_state.live_log.append(line)
            st.session_state.live_log = st.session_state.live_log[-40:]  # keep last 40

        status = st.status("🧠 Agent arbeitet…", expanded=True)
        status.write("PLAN → SEARCH → READ → NOTES → REPORT")

        try:
            raw_msgs2 = memory.get_messages(run_id, limit=400)
            hist2 = [{"role": r, "content": c} for _, r, c in raw_msgs2]

            assistant_text = agent.run_chat(
                run_id=run_id,
                user_message=user_text,
                chat_history=hist2,
                progress_cb=progress_cb,
            )

            memory.add_message(run_id, "assistant", assistant_text)
            memory.update_run_final(run_id, assistant_text)

            status.update(label="✅ Fertig", state="complete", expanded=False)
        except Exception as e:
            status.update(label="❌ Fehler", state="error", expanded=True)
            st.error(f"Agent Fehler: {e}")
            st.stop()

        st.rerun()

# ------------------------
# RIGHT: Manus Inspector (Live tasks, URLs, preview, files)
# ------------------------
with col_inspector:
    st.subheader("🧪 Inspector")

    tabs = st.tabs(["Live", "Tasks", "Sources", "Preview", "Files"])

    run_id = st.session_state.selected_run

    # Load events for sources/files
    events = memory.get_events(run_id, limit=800) if run_id else []

    # Collect sources + artifacts from latest final event
    final_payload = None
    for ts, kind, data in reversed(events):
        if kind == "final":
            final_payload = data
            break

    sources = (final_payload or {}).get("sources", []) if isinstance(final_payload, dict) else []
    artifacts = (final_payload or {}).get("artifacts", []) if isinstance(final_payload, dict) else []

    with tabs[0]:
        phase = st.session_state.get("live_phase", "")
        url = st.session_state.get("live_url", "")
        st.markdown(f"**Phase:** `{phase}`" if phase else "**Phase:** _(idle)_")
        if url:
            st.markdown(f"**Aktuelle URL:** {url}")
        log = st.session_state.get("live_log", [])
        if log:
            st.markdown("**Live Log**")
            st.code("\n".join(log[-25:]))
        else:
            st.caption("Starte eine Nachricht, um Live-Events zu sehen.")

    with tabs[1]:
        t = st.session_state.get("live_tasks") or {}
        if any(v is not None for v in t.values()):
            st.metric("Plan Steps", t.get("plan_steps") or 0)
            st.metric("Search Tasks", t.get("search_tasks") or 0)
            st.metric("Pages visited", t.get("pages_visited") or 0)
            st.metric("Extracts", t.get("extracts_made") or 0)
            st.metric("Notes", t.get("notes") or 0)
        elif final_payload and isinstance(final_payload, dict) and final_payload.get("tasks"):
            ft = final_payload["tasks"]
            st.metric("Plan Steps", ft.get("plan_steps", 0))
            st.metric("Search Tasks", ft.get("search_tasks", 0))
            st.metric("Pages visited", ft.get("pages_visited", 0))
            st.metric("Extracts", ft.get("extracts_made", 0))
            st.metric("Notes", ft.get("notes", 0))
        else:
            st.caption("Noch keine Task-Zähler vorhanden (starte eine Anfrage).")

    with tabs[2]:
        if sources:
            for s in sources[:20]:
                title = s.get("title", "Quelle")
                url = s.get("url", "")
                quality = s.get("quality", "unknown")
                st.markdown(f"- **{title}** `({quality})`  \n  {url}")
        else:
            st.caption("Noch keine Quellen gespeichert (erst nach einer Recherche).")

    with tabs[3]:
        title = st.session_state.get("live_preview_title", "")
        text = st.session_state.get("live_preview_text", "")
        if title or text:
            st.markdown(f"**Preview:** {title}")
            st.text_area("Extrahierter Inhalt (Auszug)", value=text, height=260)
        else:
            st.caption("Preview erscheint, sobald der Agent eine Seite gelesen + extrahiert hat.")

    with tabs[4]:
        if artifacts:
            st.markdown("**Artifacts**")
            for a in artifacts:
                path = a.get("path")
                note = a.get("note", "")
                st.markdown(f"- `{path}` — {note}")
                if path and os.path.exists(path) and path.endswith(".md"):
                    with st.expander(f"Öffnen: {os.path.basename(path)}"):
                        try:
                            content = open(path, "r", encoding="utf-8").read()
                            st.text_area("Inhalt", value=content, height=260)
                        except Exception as e:
                            st.error(f"Konnte Datei nicht lesen: {e}")
        else:
            # show existing reports if any
            if os.path.isdir(config.artifact_dir):
                md_files = sorted(glob.glob(os.path.join(config.artifact_dir, "report_run_*.md")))[-10:]
                if md_files:
                    st.markdown("**Gefundene Reports**")
                    for f in reversed(md_files):
                        st.markdown(f"- `{f}`")
                else:
                    st.caption("Noch keine Reports gespeichert.")
            else:
                st.caption("Artifacts-Ordner existiert noch nicht.")
