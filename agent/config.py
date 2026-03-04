from pydantic import BaseModel
import os

class AgentConfig(BaseModel):
    model: str = os.getenv("OPENAI_MODEL", "openrouter/free")

    # loops + tool calls (UI überschreibt)
    max_loops: int = int(os.getenv("MAX_LOOPS", "10"))
    max_tool_calls: int = int(os.getenv("MAX_TOOL_CALLS", "10"))

    # research defaults
    search_results: int = int(os.getenv("SEARCH_RESULTS", "6"))
    pages_to_read: int = int(os.getenv("PAGES_TO_READ", "3"))

    artifact_dir: str = os.getenv("ARTIFACT_DIR", "artifacts")
    memory_db_path: str = os.getenv("MEMORY_DB_PATH", "memory.sqlite3")
