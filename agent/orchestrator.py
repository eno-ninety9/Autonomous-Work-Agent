import os
import json
from typing import List, Dict, Any, Callable, Optional
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
        if any(x in u for x in [".gov", ".eu", "bremen.de", "bund.de"]):
            return "official"
        if any(x in u for x in ["kununu", "glassdoor", "indeed", "trustpilot", "google.com/maps"]):
            return "reviews"
        if any(x in u for x in ["zeit.de", "spiegel.de", "handelsblatt", "heise", "t3n", "faz.net", "tagesschau"]):
            return "media"
        if any(x in u for x in ["reddit", "forum", "gutefrage"]):
            return "forum"
        return "unknown"

    def run_chat(
        self,
        run_id: int,
        user_message: str,
        chat_history: List[Dict[str, str]],
        progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> str:
        """
        progress_cb bekommt Live-Events:
        {"type":"phase","value":"SEARCH"} etc.
        {"type":"visit","url": "..."}
        {"type":"preview","title": "...", "text": "..."}
        {"type":"task_counts", ...}
        """

        def emit(kind: str, data: Dict[str, Any]):
            if self.memory and run_id:
                self.memory.add_event(run_id, kind, data)
            if progress_cb:
                progress_cb({"type": kind, **data})

        # ---- PLAN
        emit("phase", {"value": "PLAN"})
        plan = self.create_plan(user_message)
        emit("plan", {"plan": plan})

        # ---- task counters
        tasks = {
            "plan_steps": len(plan.get("plan", [])),
            "search_tasks": 0,
            "pages_visited": 0,
            "extracts_made": 0,
            "notes": 0,
        }
        emit("task_counts", tasks)

        # seed messages
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": TOOL_PROTOCOL},
        ]

        tail = chat_history[-12:] if len(chat_history) > 12 else chat_history
        for m in tail:
            if m["role"] in ("user", "assistant"):
                messages.append({"role": m["role"], "content": m["content"]})

        # directive: do multi-step research
        pages_to_read = int(getattr(self.config, "pages_to_read", 3))
        search_results = int(getattr(self.config, "search_results", 6))

        messages.append({
            "role": "user",
            "content": (
                f"Neue Nutzerfrage: {user_message}\n\n"
                f"Plan (JSON): {json.dumps(plan, ensure_ascii=False)}\n\n"
                "Arbeite nach dem Plan.\n"
                f"- Nutze zuerst web_search (max_results={search_results}).\n"
                f"- Wähle dann {pages_to_read} gute URLs und lies sie mit read_webpage -> extract_readable.\n"
                "- Sammle Notizen/Belege.\n"
                "- Antworte am Ende mit action='final' im TOOL_PROTOCOL.\n"
                "Wenn die Frage trivial ist (z.B. 'hallo'), antworte direkt ohne Tools."
            )
        })

        max_loops = int(getattr(self.config, "max_loops", 10))
        max_tool_calls = int(getattr(self.config, "max_tool_calls", 10))

        tool_calls = 0
        sources: List[Dict[str, Any]] = []
        notes: List[Dict[str, Any]] = []

        # ---- LOOP
        for step in range(max_loops):
            resp = self.client.chat.completions.create(
                model=self.config.model,
                messages=messages,
            )
            txt = resp.choices[0].message.content
            obj = self._try_json(txt)

            if obj is None:
                emit("model_text_fallback", {"text": txt[:2000]})
                return txt

            if obj.get("action") == "tool":
                name = obj.get("name")
                args = obj.get("args", {}) or {}
                reason = obj.get("reason", "")

                tool_calls += 1
                emit("tool_request", {"name": name, "args": args, "reason": reason, "tool_calls": tool_calls})

                if tool_calls > max_tool_calls:
                    emit("forced_final", {"reason": "max_tool_calls"})
                    messages.append({"role": "assistant", "content": txt})
                    messages.append({"role": "user", "content": "Finalisiere jetzt (action='final'), keine weiteren Tools."})
                    continue

                fn = TOOLS.get(name)
                if not fn:
                    tool_out = {"error": f"Unknown tool: {name}"}
                else:
                    try:
                        # --- emit phase changes
                        if name == "web_search":
                            emit("phase", {"value": "SEARCH"})
                            tasks["search_tasks"] += 1
                            emit("task_counts", tasks)

                        if name == "read_webpage":
                            emit("phase", {"value": "READ"})
                            url = args.get("url", "")
                            if url:
                                emit("visit", {"url": url})
                            tasks["pages_visited"] += 1
                            emit("task_counts", tasks)

                        if name == "extract_readable":
                            emit("phase", {"value": "NOTES"})

                        tool_out = fn(**args)
                    except Exception as e:
                        tool_out = {"error": str(e), "tool": name, "args": args}

                # collect sources from web_search
                if name == "web_search":
                    for r in tool_out.get("results", []):
                        u = r.get("url")
                        if u:
                            sources.append({
                                "title": r.get("title") or "Quelle",
                                "url": u,
                                "quality": self._quality_guess(u),
                                "snippet": r.get("snippet") or ""
                            })

                # collect readable notes
                if name == "extract_readable":
                    tasks["extracts_made"] += 1
                    title = (tool_out.get("title") or "").strip()
                    text = (tool_out.get("text") or "").strip()
                    if text:
                        preview = "\n".join(text.splitlines()[:40])  # first ~40 lines
                        emit("preview", {"title": title[:160], "text": preview[:4000]})
                        notes.append({"title": title[:160], "extract": text[:2500]})
                        tasks["notes"] = len(notes)
                        emit("task_counts", tasks)

                emit("tool_result", {"name": name, "output_meta": {"keys": list(tool_out.keys())}})

                messages.append({"role": "assistant", "content": txt})
                messages.append({
                    "role": "user",
                    "content": (
                        f"TOOL_RESULT {name}: {json.dumps(tool_out, ensure_ascii=False)}\n\n"
                        "Anweisung:\n"
                        "- Wenn web_search: wähle 2-3 beste URLs und lies sie mit read_webpage -> extract_readable.\n"
                        "- Wenn genug Infos: antworte mit action='final'.\n"
                        "- Sonst: maximal 1 weiteren Toolcall und dann finalisieren.\n"
                    )
                })
                continue

            if obj.get("action") == "final":
                emit("phase", {"value": "REPORT"})
                answer = (obj.get("answer") or "").strip()

                final_sources = obj.get("sources") or []
                assumptions = obj.get("assumptions") or []
                artifacts = obj.get("artifacts") or []

                # if model forgot sources, use collected
                if not final_sources and sources:
                    final_sources = [
                        {"title": s["title"], "url": s["url"], "quality": s["quality"]}
                        for s in sources[:12]
                    ]

                # save markdown report
                os.makedirs(self.config.artifact_dir, exist_ok=True)
                report_path = os.path.join(self.config.artifact_dir, f"report_run_{run_id}.md")

                md = []
                md.append(f"# Report (Run #{run_id})\n")
                md.append("## Antwort\n")
                md.append(answer if answer else "_(leer)_")
                md.append("\n\n## Task-Übersicht\n")
                md.append(f"- Plan Steps: {tasks['plan_steps']}")
                md.append(f"- Search Tasks: {tasks['search_tasks']}")
                md.append(f"- Pages visited: {tasks['pages_visited']}")
                md.append(f"- Extracts made: {tasks['extracts_made']}")
                md.append(f"- Notes: {tasks['notes']}")
                md.append("\n\n## Quellen\n")
                for s in final_sources[:12]:
                    md.append(f"- **{s.get('title','Quelle')}** ({s.get('quality','unknown')}): {s.get('url')}")
                if notes:
                    md.append("\n\n## Research Notes (Auszüge)\n")
                    for i, n in enumerate(notes[:12], 1):
                        md.append(f"### Note {i}: {n.get('title','')}\n")
                        md.append(n.get("extract", ""))
                        md.append("")
                if assumptions:
                    md.append("\n\n## Annahmen / Unsicherheiten\n")
                    for a in assumptions:
                        md.append(f"- {a}")

                report_content = "\n".join(md).strip() + "\n"
                TOOLS["write_file"](report_path, report_content)

                artifacts = artifacts + [{"path": report_path, "note": "Auto-generated report"}]

                emit("final", {
                    "answer": answer,
                    "sources": final_sources,
                    "assumptions": assumptions,
                    "artifacts": artifacts,
                    "tasks": tasks,
                })

                extra = f"\n\n---\n📄 Report gespeichert: `{report_path}`"
                return (answer + extra).strip()

            # Unexpected JSON
            messages.append({"role": "assistant", "content": txt})
            messages.append({"role": "user", "content": "Bitte antworte exakt im TOOL_PROTOCOL (action=tool oder action=final)."})


        emit("forced_final", {"reason": "max_loops"})
        messages.append({"role": "user", "content": "Finalisiere jetzt (action='final'), keine Tools."})
        resp = self.client.chat.completions.create(model=self.config.model, messages=messages)
        txt = resp.choices[0].message.content
        obj = self._try_json(txt)
        if obj and obj.get("action") == "final":
            return (obj.get("answer", "") or "").strip() or "⚠️ (final leer)"
        return txt
