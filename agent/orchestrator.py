import os
import json
from openai import OpenAI

from .prompts import SYSTEM_PROMPT, PLANNER_PROMPT

class ManusAgent:
    def __init__(self, config):
        self.config = config

        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY fehlt (Streamlit Secrets).")

        # OpenRouter: OpenAI-kompatible API unter /api/v1
        # Auth via Bearer Token
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                # optional, empfohlen:
                "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", ""),
                "X-OpenRouter-Title": os.getenv("OPENROUTER_APP_NAME", "Cloud Manus"),
            },
        )

    def _safe_json(self, s: str):
        try:
            return json.loads(s)
        except Exception:
            a = s.find("{")
            b = s.rfind("}")
            if a != -1 and b != -1 and b > a:
                return json.loads(s[a:b+1])
            return {"plan": [{"step": 1, "title": "Plan", "details": "Konnte JSON nicht parsen"}]}

    def create_plan(self, goal: str):
        resp = self.client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": PLANNER_PROMPT},
                {"role": "user", "content": goal},
            ],
        )
        return self._safe_json(resp.choices[0].message.content)

    def run(self, goal: str):
        plan = self.create_plan(goal)

        resp = self.client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": goal},
            ],
        )

        return {"plan": plan, "result": resp.choices[0].message.content}
