from pydantic import BaseModel
import os

class AgentConfig(BaseModel):
    model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    tool_budget: int = int(os.getenv("TOOL_BUDGET", "10"))
    max_loops: int = int(os.getenv("MAX_LOOPS", "6"))
    artifact_dir: str = os.getenv("ARTIFACT_DIR", "artifacts")

    memory_db_path: str = os.getenv("MEMORY_DB_PATH", "memory.sqlite3")

