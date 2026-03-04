import os
import json
from openai import OpenAI

from .prompts import SYSTEM_PROMPT, PLANNER_PROMPT, TOOL_PROTOCOL
from .tools import TOOLS

class ManusAgent:
    def __init__(self, config, memory=None):
        self.config = config
        self.memory = memory

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

    def _safe_json(self, s: str):
        try:
            return json.loads(s)
        except Exception:
            a = s.find("{")
            b = s.rfind("}")
            if a != -1 and b != -1 and b > a:
                return json.loads(s[a:b+1])
            raise ValueError(f"Konnte JSON nicht parsen: {s[:300]}")

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
        txt = resp.choices[0].message.content
        plan = self._try_json(txt)
        if plan is None:
            # fallback plan (still proceed)
            plan = {
                "plan": [{"step": 1, "title": "Analyse", "details": "Plan konnte nicht als JSON gelesen werden."}],
                "success_criteria": ["Eine umsetzbare Empfehlung mit Schritten, Kostenhinweisen und Quellen"],
                "research_queries": []
            }
        return plan

    def _finalize_from_messages(self, messages, plan, sources, run_id):
        """Force the model to return a final JSON answer."""
        messages = messages + [{
            "role": "user",
            "content": (
                "FINALISIERE JETZT. Antworte mit action='final' im TOOL_PROTOCOL. "
                "Keine weiteren Tools. Gib konkrete Schritte, ToDos, Kosten/Zeitschätzung, "
                "Genehmigungen/Netzanschluss-Hinweise und eine Quellenliste."
            )
        }]

        resp = self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
        )
        txt = resp.choices[0].message.content
        obj = self._try_json(txt)

        if obj and obj.get("action") == "final":
            final_sources = obj.get("sources") or sources
            # dedupe
            seen = set()
            deduped = []
            for s in final_sources:
                u = (s or {}).get("url")
                if not u or u in seen:
                    continue
                seen.add(u)
                deduped.append({"title": (s or {}).get("title", "Quelle"), "url": u})

            result = {
                "plan": plan,
                "result": obj.get("answer", ""),
                "sources": deduped,
                "assumptions": obj.get("assumptions", []),
            }
            if self.memory and run_id:
                self.memory.add_event(run_id, "final", result)
            return result

        # fallback: show raw text
        fallback = {
            "plan": plan,
            "result": txt,
            "sources": sources,
            "assumptions": ["Model returned non-JSON final; raw text used."],
        }
        if self.memory and run_id:
            self.memory.add_event(run_id, "model_text_fallback", {"text": txt[:2000]})
        return fallback

    def run(self, goal: str, run_id: int = None):
        plan = self.create_plan(goal)
        if self.memory and run_id:
            self.memory.add_event(run_id, "plan", plan)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": TOOL_PROTOCOL},
            {"role": "user", "content": f"Aufgabe: {goal}\n\nPlan: {json.dumps(plan, ensure_ascii=False)}"},
        ]

        max_steps = int(getattr(self.config, "max_loops", 6))
        max_tool_calls = int(getattr(self.config, "max_tool_calls", 4))

        tool_calls = 0
        sources = []
        last_tool = None
        consecutive_same_tool = 0

        for step in range(max_steps):
            resp = self.client.chat.completions.create(
                model=self.config.model,
                messages=messages,
            )
            txt = resp.choices[0].message.content

            obj = self._try_json(txt)

            # If model ignored JSON protocol -> stop and return text
            if obj is None:
                if self.memory and run_id:
                    self.memory.add_event(run_id, "model_text_fallback", {"text": txt[:2000]})
                return {
                    "plan": plan,
                    "result": txt,
                    "sources": sources,
                    "assumptions": ["Model returned non-JSON; fallback used."],
                }

            # TOOL CALL
            if obj.get("action") == "tool":
                name = obj.get("name")
                args = obj.get("args", {}) or {}
                reason = obj.get("reason", "")

                tool_calls += 1

                # track repeated tool calls
                if name == last_tool:
                    consecutive_same_tool += 1
                else:
                    consecutive_same_tool = 0
                last_tool = name

                if self.memory and run_id:
                    self.memory.add_event(run_id, "tool_request", {"name": name, "args": args, "reason": reason})

                # prevent endless searching:
                # - if tool limit reached OR same tool repeated too much -> force final
                if tool_calls > max_tool_calls or consecutive_same_tool >= 2:
                    if self.memory and run_id:
                        self.memory.add_event(run_id, "forced_final", {
                            "reason": "tool_limit_or_repeat",
                            "tool_calls": tool_calls,
                            "max_tool_calls": max_tool_calls,
                            "consecutive_same_tool": consecutive_same_tool
                        })
                    return self._finalize_from_messages(messages, plan, sources, run_id)

                fn = TOOLS.get(name)
                if not fn:
                    tool_out = {"error": f"Unknown tool: {name}"}
                else:
                    try:
                        tool_out = fn(**args)
                    except Exception as e:
                        tool_out = {"error": str(e), "tool": name, "args": args}

                # collect sources from web_search
                if name in ("web_search", "search", "ddg_search"):
                    for r in tool_out.get("results", []):
                        u = r.get("url") or r.get("href")
                        if u:
                            sources.append({"title": r.get("title") or "Quelle", "url": u})

                if self.memory and run_id:
                    self.memory.add_event(run_id, "tool_result", {"name": name, "output": tool_out})

                # feed back tool result, and instruct next step
                messages.append({"role": "assistant", "content": txt})
                messages.append({
                    "role": "user",
                    "content": (
                        f"TOOL_RESULT {name}: {json.dumps(tool_out, ensure_ascii=False)}\n\n"
                        "Anweisung: Extrahiere jetzt die wichtigsten Fakten/Optionen. "
                        "Wenn du genug hast: antworte mit action='final'. "
                        "Wenn nicht: höchstens EIN weiteres Tool verwenden und dann finalisieren."
                    )
                })
                continue

            # FINAL
            if obj.get("action") == "final":
                final_sources = obj.get("sources") or sources

                # dedupe sources
                seen = set()
                deduped = []
                for s in final_sources:
                    u = (s or {}).get("url")
                    if not u or u in seen:
                        continue
                    seen.add(u)
                    deduped.append({"title": (s or {}).get("title", "Quelle"), "url": u})

                result = {
                    "plan": plan,
                    "result": obj.get("answer", ""),
                    "sources": deduped,
                    "assumptions": obj.get("assumptions", []),
                }
                if self.memory and run_id:
                    self.memory.add_event(run_id, "final", result)
                return result

            # Unexpected JSON -> steer back
            messages.append({"role": "assistant", "content": txt})
            messages.append({"role": "user", "content": "Bitte antworte exakt im TOOL_PROTOCOL (action=tool oder action=final)."})


        # if loop ended without final -> force final
        if self.memory and run_id:
            self.memory.add_event(run_id, "forced_final", {"reason": "max_loops_reached"})
        return self._finalize_from_messages(messages, plan, sources, run_id)
