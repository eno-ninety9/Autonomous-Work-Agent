import sqlite3
import json
import time


class AgentMemory:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()

    def _connect(self):
        # check_same_thread=False ist hilfreich bei Streamlit/Reruns
        con = sqlite3.connect(self.db_path, check_same_thread=False)
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        return con

    def init_db(self):
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS runs(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL,
                    goal TEXT,
                    final_answer TEXT
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    ts REAL,
                    kind TEXT,
                    data TEXT
                )
            """)
            con.commit()

    def add_run(self, goal, final_answer):
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO runs(ts, goal, final_answer) VALUES(?,?,?)",
                (time.time(), goal, final_answer)
            )
            con.commit()
            return cur.lastrowid

    def add_event(self, run_id, kind, data):
        with self._connect() as con:
            con.execute(
                "INSERT INTO events(run_id, ts, kind, data) VALUES(?,?,?,?)",
                (run_id, time.time(), kind, json.dumps(data, ensure_ascii=False))
            )
            con.commit()

    def get_runs(self, limit=20):
        with self._connect() as con:
            return con.execute(
                "SELECT id, ts, goal FROM runs ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()

    def get_events(self, run_id, limit=200):
        with self._connect() as con:
            rows = con.execute(
                "SELECT ts, kind, data FROM events WHERE run_id=? ORDER BY id ASC LIMIT ?",
                (run_id, limit)
            ).fetchall()

        out = []
        for ts, kind, data in rows:
            try:
                out.append((ts, kind, json.loads(data)))
            except Exception:
                out.append((ts, kind, {"raw": data}))
        return out
