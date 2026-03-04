import os
import json
from openai import OpenAI

from .prompts import SYSTEM_PROMPT, PLANNER_PROMPT

class ManusAgent:
    def __init__(self, config):
        self.config = config
        # Wichtig: API-Key über Env/Secrets
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def _safe_json(self, s: str):
        try:
            return json.loads(s)
        except Exception:
            a = s.find("{")
            b = s.rfind("}")
            if a != -1 and b != -1 and b > a:
                return json.loads(s[a:b+1])
            # Fallback
            return {"plan": [{"step": 1, "title": "Do task", "details": "Could not parse plan JSON"}]}

    def create_plan(self, goal: str):
        resp = self.client.responses.create(
            model=self.config.model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": PLANNER_PROMPT},
                {"role": "user", "content": goal},
            ],
        )
        return self._safe_json(resp.output_text)

    def run(self, goal: str):
        plan = self.create_plan(goal)

        resp = self.client.responses.create(
            model=self.config.model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": goal},
            ],
        )

        return {"plan": plan, "result": resp.output_text}
