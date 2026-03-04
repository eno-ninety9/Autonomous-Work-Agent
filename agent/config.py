from pydantic import BaseModel
import os

class AgentConfig(BaseModel):
    # OpenRouter / OpenAI-compatible model name
    model: str = os.getenv("OPENAI_MODEL", "openrouter/free")

    # loop controls (UI overrides these)
    max_loops: int = int(os.getenv("MAX_LOOPS", "6"))
    max_tool_calls: int = int(os.getenv("MAX_TOOL_CALLS", "4"))

    # storage
    artifact_dir: str = os.getenv("ARTIFACT_DIR", "artifacts")
    memory_db_path: str = os.getenv("MEMORY_DB_PATH", "memory.sqlite3")
