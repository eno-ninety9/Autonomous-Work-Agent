import sqlite3
import json
import time

class AgentMemory:

    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("""
            CREATE TABLE IF NOT EXISTS runs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                goal TEXT,
                result TEXT
            )
            """)

    def add_run(self, goal, result):
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                "INSERT INTO runs(ts,goal,result) VALUES(?,?,?)",
                (time.time(), goal, result)
            )

    def get_runs(self, limit=20):
        with sqlite3.connect(self.db_path) as con:
            return con.execute(
                "SELECT id,ts,goal FROM runs ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()