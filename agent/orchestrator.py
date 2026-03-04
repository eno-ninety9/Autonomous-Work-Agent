import os
import json
from openai import OpenAI

from .prompts import SYSTEM_PROMPT, PLANNER_PROMPT, TOOL_PROTOCOL
from .tools import TOOLS

class ManusAgent:
    def __init__(self, config, memory=None):
        self.config = config

        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY fehlt (Streamlit Secrets).")

        self.client = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", ""),
                "X-OpenRouter-Title": os.getenv("OPENROUTER_APP_NAME", "Cloud Manus"),
            },
        )
        self.memory = memory

    def _safe_json(self, s: str):
        try:
            return json.loads(s)
        except Exception:
            a = s.find("{")
            b = s.rfind("}")
            if a != -1 and b != -1 and b > a:
                return json.loads(s[a:b+1])
            raise ValueError(f"Konnte JSON nicht parsen: {s[:200]}")

    def _try_json(self, s: str):
    try:
        return self._safe_json(s)
    except Exception:
        return None

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

    def run(self, goal: str, run_id: int = None):
        plan = self.create_plan(goal)
        if self.memory and run_id:
            self.memory.add_event(run_id, "plan", plan)

        # Start conversation for tool-loop
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": TOOL_PROTOCOL},
            {"role": "user", "content": f"Aufgabe: {goal}\n\nPlan: {json.dumps(plan, ensure_ascii=False)}"},
        ]

        max_steps = self.config.max_loops
        sources = []

        for step in range(max_steps):
            resp = self.client.chat.completions.create(
                model=self.config.model,
                messages=messages,
            )
            txt = resp.choices[0].message.content
            obj = self._try_json(txt)

            # FALLBACK: Wenn das Model kein JSON liefert, gib den Text trotzdem aus
            if obj is None:
                if self.memory and run_id:
                    self.memory.add_event(run_id, "model_text_fallback", {"text": txt[:2000]})
                return {
                    "plan": plan,
                    "result": txt,
                    "sources": sources,
                    "assumptions": ["Model returned non-JSON; fallback used."],
                }

            if obj.get("action") == "tool":
                name = obj.get("name")
                args = obj.get("args", {})
                reason = obj.get("reason", "")

                if self.memory and run_id:
                    self.memory.add_event(run_id, "tool_request", {"name": name, "args": args, "reason": reason})

                fn = TOOLS.get(name)
                if not fn:
                    tool_out = {"error": f"Unknown tool: {name}"}
                else:
                    try:
                        tool_out = fn(**args)
                    except TypeError:
                        tool_out = {"error": f"Bad args for tool {name}", "args": args}
                    except Exception as e:
                        tool_out = {"error": str(e)}

                # collect sources for nicer output
                if name == "web_search":
                    for r in tool_out.get("results", []):
                        if r.get("url"):
                            sources.append({"title": r.get("title") or "Source", "url": r["url"]})

                if self.memory and run_id:
                    self.memory.add_event(run_id, "tool_result", {"name": name, "output": tool_out})

                messages.append({"role": "assistant", "content": txt})
                messages.append({"role": "user", "content": f"TOOL_RESULT {name}: {json.dumps(tool_out, ensure_ascii=False)}"})
                continue

            if obj.get("action") == "final":
                # merge sources (dedupe)
                final_sources = obj.get("sources") or sources
                # dedupe by url
                seen = set()
                deduped = []
                for s in final_sources:
                    u = s.get("url")
                    if not u or u in seen:
                        continue
                    seen.add(u)
                    deduped.append(s)

                result = {
                    "plan": plan,
                    "result": obj.get("answer", ""),
                    "sources": deduped,
                    "assumptions": obj.get("assumptions", []),
                }
                if self.memory and run_id:
                    self.memory.add_event(run_id, "final", result)
                return result

            # If model returns unexpected JSON, push it back
            messages.append({"role": "assistant", "content": txt})
            messages.append({"role": "user", "content": "Das JSON war nicht im Protokoll. Bitte antworte exakt im TOOL_PROTOCOL."})

        # fallback if loop exceeded
        return {
            "plan": plan,
            "result": "⚠️ Abgebrochen: max_loops erreicht.",
            "sources": sources,
            "assumptions": ["max_loops erreicht"],
        }

