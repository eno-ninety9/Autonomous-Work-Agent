import os
import json
from typing import List, Dict, Any
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

    def create_plan(self, user_goal: str):
        resp = self.client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": PLANNER_PROMPT},
                {"role": "user", "content": user_goal},
            ],
        )
        txt = resp.choices[0].message.content
        plan = self._try_json(txt)
        if plan is None:
            plan = {
                "plan": [{"step": 1, "title": "Analyse", "details": "Plan konnte nicht als JSON gelesen werden."}],
                "research_queries": [],
                "success_criteria": ["Klare Antwort + Quellen"]
            }
        return plan

    def _quality_guess(self, url: str) -> str:
        u = (url or "").lower()
        if any(x in u for x in ["bremen.de", "bund.de", ".gov", ".eu", "bmwi", "bmwk", "deutschland.de"]):
            return "official"
        if any(x in u for x in ["kununu", "glassdoor", "indeed", "trustpilot", "google.com/maps"]):
            return "reviews"
        if any(x in u for x in ["zeit.de", "spiegel.de", "handelsblatt", "heise", "t3n", "faz.net", "n-tv", "tagesschau"]):
            return "media"
        if any(x in u for x in ["reddit", "forum", "gutefrage"]):
            return "forum"
        return "unknown"

    def run_chat(self, run_id: int, user_message: str, chat_history: List[Dict[str, str]]):
        """
        chat_history: list of {"role":"user|assistant", "content": "..."} from DB.
        Returns assistant markdown text.
        """
        plan = self.create_plan(user_message)
        if self.memory and run_id:
            self.memory.add_event(run_id, "plan", plan)

        # We seed the model with the chat history (short), and a research directive
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": TOOL_PROTOCOL},
        ]

        # include last N chat turns for context
        tail = chat_history[-12:] if len(chat_history) > 12 else chat_history
        for m in tail:
            if m["role"] in ("user", "assistant"):
                messages.append({"role": m["role"], "content": m["content"]})

        # add current user message with plan
        messages.append({
            "role": "user",
            "content": (
                f"Neue Nutzerfrage: {user_message}\n\n"
                f"Plan (JSON): {json.dumps(plan, ensure_ascii=False)}\n\n"
                "Arbeite nach dem Plan. Für Recherche: nutze web_search, dann lies 2-3 relevante Seiten "
                "mit read_webpage + extract_readable. Danach schreibe einen Report. "
                "Wenn die Frage klein ist (z.B. 'hallo'), antworte direkt ohne Tools."
            )
        })

        max_loops = int(getattr(self.config, "max_loops", 10))
        max_tool_calls = int(getattr(self.config, "max_tool_calls", 10))

        tool_calls = 0
        sources = []
        notes = []

        for step in range(max_loops):
            resp = self.client.chat.completions.create(
                model=self.config.model,
                messages=messages,
            )
            txt = resp.choices[0].message.content
            obj = self._try_json(txt)

            # Non-JSON fallback: accept as final assistant message
            if obj is None:
                if self.memory and run_id:
                    self.memory.add_event(run_id, "model_text_fallback", {"text": txt[:2000]})
                return txt

            if obj.get("action") == "tool":
                name = obj.get("name")
                args = obj.get("args", {}) or {}
                reason = obj.get("reason", "")

                tool_calls += 1
                if self.memory and run_id:
                    self.memory.add_event(run_id, "tool_request", {"name": name, "args": args, "reason": reason})

                # tool limit -> force final
                if tool_calls > max_tool_calls:
                    if self.memory and run_id:
                        self.memory.add_event(run_id, "forced_final", {"reason": "max_tool_calls"})
                    messages.append({"role": "assistant", "content": txt})
                    messages.append({"role": "user", "content": "Finalisiere jetzt (action='final'), keine weiteren Tools."})
                    continue

                fn = TOOLS.get(name)
                if not fn:
                    tool_out = {"error": f"Unknown tool: {name}"}
                else:
                    try:
                        tool_out = fn(**args)
                    except Exception as e:
                        tool_out = {"error": str(e), "tool": name, "args": args}

                # Collect sources
                if name == "web_search":
                    for r in tool_out.get("results", []):
                        u = r.get("url")
                        if u:
                            sources.append({
                                "title": r.get("title") or "Quelle",
                                "url": u,
                                "quality": self._quality_guess(u),
                                "snippet": r.get("snippet")
                            })

                # Collect notes from readable extractions
                if name == "extract_readable":
                    t = (tool_out.get("title") or "").strip()
                    text = (tool_out.get("text") or "").strip()
                    if text:
                        notes.append({
                            "title": t[:160],
                            "extract": text[:1200]
                        })

                if self.memory and run_id:
                    self.memory.add_event(run_id, "tool_result", {"name": name, "output": tool_out})

                messages.append({"role": "assistant", "content": txt})
                messages.append({
                    "role": "user",
                    "content": (
                        f"TOOL_RESULT {name}: {json.dumps(tool_out, ensure_ascii=False)}\n\n"
                        "Nächster Schritt: Ziehe Erkenntnisse daraus. "
                        "Wenn du web_search gemacht hast: wähle 2-3 beste URLs und lies sie mit "
                        "read_webpage -> extract_readable. "
                        "Wenn du genug hast: antworte mit action='final'."
                    )
                })
                continue

            if obj.get("action") == "final":
                answer = obj.get("answer", "") or ""
                final_sources = obj.get("sources") or []
                assumptions = obj.get("assumptions") or []
                artifacts = obj.get("artifacts") or []

                # If model didn't include sources, create from collected
                if not final_sources and sources:
                    final_sources = [{"title": s["title"], "url": s["url"], "quality": s["quality"]} for s in sources[:8]]

                # Create Markdown report and save
                os.makedirs(self.config.artifact_dir, exist_ok=True)
                report_path = os.path.join(self.config.artifact_dir, f"report_run_{run_id}.md")

                # Append research notes + sources
                md = []
                md.append(f"# Report (Run #{run_id})\n")
                md.append("## Antwort\n")
                md.append(answer.strip() or "_(leer)_")
                md.append("\n\n## Quellen\n")
                for s in final_sources[:12]:
                    md.append(f"- **{s.get('title','Quelle')}** ({s.get('quality','unknown')}): {s.get('url')}")
                if notes:
                    md.append("\n\n## Research Notes (Auszüge)\n")
                    for i, n in enumerate(notes[:10], 1):
                        md.append(f"### Note {i}: {n.get('title','')}\n")
                        md.append(n.get("extract",""))
                        md.append("")
                if assumptions:
                    md.append("\n\n## Annahmen / Unsicherheiten\n")
                    for a in assumptions:
                        md.append(f"- {a}")

                report_content = "\n".join(md).strip() + "\n"
                TOOLS["write_file"](report_path, report_content)

                # merge artifact info
                artifacts = artifacts + [{"path": report_path, "note": "Auto-generated report"}]

                if self.memory and run_id:
                    self.memory.add_event(run_id, "final", {
                        "answer": answer,
                        "sources": final_sources,
                        "assumptions": assumptions,
                        "artifacts": artifacts
                    })

                # Return the answer (chat output) + include report link text
                extra = f"\n\n---\n📄 Report gespeichert: `{report_path}`"
                return (answer.strip() + extra).strip()

            # unexpected JSON
            messages.append({"role": "assistant", "content": txt})
            messages.append({"role": "user", "content": "Bitte antworte exakt im TOOL_PROTOCOL (action=tool oder action=final)."})


        # loop ended -> final request
        if self.memory and run_id:
            self.memory.add_event(run_id, "forced_final", {"reason": "max_loops"})
        messages.append({"role": "user", "content": "Finalisiere jetzt (action='final'), keine Tools."})
        resp = self.client.chat.completions.create(model=self.config.model, messages=messages)
        txt = resp.choices[0].message.content
        obj = self._try_json(txt)
        if obj and obj.get("action") == "final":
            return (obj.get("answer", "") or "").strip() or "⚠️ (final leer)"
        return txt
