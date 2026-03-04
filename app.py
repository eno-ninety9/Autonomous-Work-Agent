import os
import sys
import streamlit as st

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

st.write("ROOT:", ROOT)
st.write("sys.path[0:5]:", sys.path[:5])
st.write("Root files:", os.listdir(ROOT))
st.write("Agent dir exists?:", os.path.isdir(os.path.join(ROOT, "agent")))
if os.path.isdir(os.path.join(ROOT, "agent")):
    st.write("Agent dir files:", os.listdir(os.path.join(ROOT, "agent")))

# STOP here so we can see output before import crash
st.stop()

from agent.config import AgentConfig
from agent.orchestrator import ManusAgent
from agent.memory import AgentMemory


st.set_page_config(page_title="Cloud Manus",layout="wide")

st.title("🧠 Cloud Manus Agent")


# Passwort Login
PASSWORD = os.getenv("APP_PASSWORD")

if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:

    pw = st.text_input("Passwort",type="password")

    if st.button("Login"):

        if pw == PASSWORD:
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("Falsches Passwort")

    st.stop()


config = AgentConfig()

agent = ManusAgent(config)

memory = AgentMemory(config.memory_db_path)


left,right = st.columns([1,2])


with left:

    st.subheader("History")

    runs = memory.get_runs()

    for r in runs:
        st.write(r[2])


with right:

    goal = st.text_area("Aufgabe")

    if st.button("Start Agent"):

        result = agent.run(goal)

        memory.add_run(goal,result["result"])

        st.subheader("Plan")
        st.json(result["plan"])

        st.subheader("Result")

        st.write(result["result"])

