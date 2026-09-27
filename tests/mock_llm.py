"""A fake AI provider for tests: speaks the OpenAI chat-completions and Anthropic messages formats (streaming),
and follows a small script so the agent's tool loop, approvals, charts and reports can be checked offline."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def plan(messages: list[dict]) -> dict:
    """Decide the next move from the conversation: a tool call or the final answer."""
    names_by_id = {tc["id"]: tc["function"]["name"] for m in messages if m.get("role") == "assistant"
                   for tc in m.get("tool_calls") or [] if isinstance(tc, dict) and "function" in tc}
    tools_done = [dict(m, name=m.get("name") or names_by_id.get(m.get("tool_call_id"))) for m in messages if m.get("role") == "tool"]
    user = next((m for m in reversed(messages) if m.get("role") == "user"), {})
    text = user.get("content") if isinstance(user.get("content"), str) else " ".join(
        p.get("text", "") for p in user.get("content") or [] if isinstance(p, dict))
    names = [m.get("name") for m in tools_done]
    text = text.split("[Question]")[-1]          # the agent puts a context note before the question
    if "promotion" in text.lower():
        if "add_promotion" not in names:
            return {"tool": "add_promotion", "args": {"code": "TST1", "name": "Test promo", "date_from": "2026-10-01", "date_to": "2026-10-10", "stores": "Emporium"}}
        return {"text": "Logged the promotion."}
    if "what is xyz" in text.lower():
        if "ask_user" not in names:
            return {"tool": "ask_user", "args": {"question": "What does the header XYZ mean?", "term": "XYZ", "options": ["Extra yield", "Something else"]}}
        ans = next(m for m in tools_done if m["name"] == "ask_user")["content"]
        return {"text": "Thanks, noted: " + ans}
    if "report" in text.lower():
        if "make_report" not in names:
            return {"tool": "make_report", "args": {"title": "Test report", "summary": "- **One** point", "formats": ["docx", "xlsx", "html"],
                                                     "sections": [{"heading": "Sales", "text": "Sales are **up**.", "chart": {"type": "bar", "title": "Sales", "labels": ["A", "B"], "series": [{"name": "PKR", "values": [1, 2]}]},
                                                                   "table": {"columns": ["Store", "Sales"], "rows": [["A", 1], ["B", 2]]}}]}}
        return {"text": "Report ready."}
    if "data_overview" not in names:
        return {"tool": "data_overview", "args": {}}
    if "chart" not in names:
        return {"tool": "chart", "args": {"type": "bar", "title": "Test chart", "labels": ["x", "y"], "series": [{"name": "v", "values": [3, 4]}], "unit": "int"}}
    return {"text": "## Answer\nAll good: **42** stores checked."}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.endswith("/models"):
            if self.headers.get("Authorization") == "Bearer bad" or self.headers.get("x-api-key") == "bad":
                return self._json({"error": {"message": "Invalid API key"}}, 401)
            return self._json({"data": [{"id": "gone-1"}, {"id": "busy-1"}, {"id": "text-embedding-3"}, {"id": "mock-1"}, {"id": "mock-notools"}]})
        self._json({}, 404)

    def _sse(self, events):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for ev in events:
            self.wfile.write(b"data: " + json.dumps(ev).encode() + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        if self.path.endswith("/audio/transcriptions"):
            ok = b'name="file"' in raw and b'name="model"' in raw
            return self._json({"text": "what is happening in the country"} if ok else {"error": {"message": "bad form"}}, 200 if ok else 400)
        body = json.loads(raw or b"{}")
        self.server.requests.append(body)
        if self.headers.get("Authorization") == "Bearer bad" or self.headers.get("x-api-key") == "bad":
            return self._json({"error": {"message": "Invalid API key"}}, 401)
        if self.path.endswith("/audio/transcriptions"):
            return self._json({"text": "what is happening in the country"})
        if self.path.endswith("/messages"):
            return self._anthropic(body)
        if body.get("model") == "gone-1":          # a retired model, answered the way Gemini does
            return self._json([{"error": {"code": 404, "message": "This model models/gone-1 is no longer available to new users."}}], 404)
        if body.get("model") == "gone-2":          # retired, and the error names the replacement
            return self._json({"error": {"message": "gone-2 is no longer available. Please update your code to use models/mock-1 for the latest features."}}, 404)
        if body.get("model") == "tpm-1":           # Groq-style tokens-per-minute limit: every second call is refused
            self.server.tpm = getattr(self.server, "tpm", 0) + 1
            if self.server.tpm % 2 == 0:
                return self._json({"error": {"message": "Rate limit reached for model `tpm-1` on tokens per minute (TPM): Limit 8000, Used 5068, Requested 6459. Please try again in 0.4s."}}, 429)
        if body.get("model") == "busy-1":
            return self._json({"error": {"message": "API rate limit exceeded"}}, 429)
        if body.get("tools") and body.get("model") == "mock-notools":
            return self._json({"error": {"message": "This model does not support tools"}}, 400)
        msgs = body["messages"]
        said = " ".join(m["content"] if isinstance(m.get("content"), str) else "" for m in msgs if m.get("role") == "user")
        if body.get("model") == "slow-1":           # a service that takes a long time to start answering
            import time as _t
            _t.sleep(6)
            body["model"] = "mock-1"
        if body.get("model") == "textcalls-1":     # writes its tool calls into the text, GLM style
            if "Result of data_overview" in said:
                out = "From the data: **42** stores checked."
            else:
                out = "Let me check the data.\n<tool_call>data_overview\n</tool_call>"
            return self._sse([{"choices": [{"delta": {"content": out[i:i + 7]}}]} for i in range(0, len(out), 7)]
                             + [{"choices": [{"delta": {}, "finish_reason": "stop"}]}])
        if body.get("model") == "long-1":          # stops at the length limit once
            if "Continue exactly where you stopped" in said:
                return self._sse([{"choices": [{"delta": {"content": " and the second half."}, "finish_reason": "stop"}]}])
            return self._sse([{"choices": [{"delta": {"content": "First half"}, "finish_reason": "length"}]}])
        if not body.get("tools"):
            return self._sse([{"choices": [{"delta": {"content": "Briefing answer. "}}]},
                              {"choices": [{"delta": {"content": "```chart\n{\"type\":\"hbar\",\"title\":\"T\",\"labels\":[\"a\"],\"series\":[{\"name\":\"n\",\"values\":[1]}]}\n```"}, "finish_reason": "stop"}]}])
        step = plan(msgs)
        if "tool" in step:
            args = json.dumps(step["args"])
            return self._sse([{"choices": [{"delta": {"reasoning": "thinking…"}}]},
                              {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c" + str(len(msgs)), "function": {"name": step["tool"], "arguments": args[:5]}}]}}]},
                              {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": args[5:]}}]}, "finish_reason": "tool_calls"}]}])
        words = step["text"].split(" ")
        return self._sse([{"choices": [{"delta": {"content": w + (" " if i < len(words) - 1 else "")}}]} for i, w in enumerate(words)]
                         + [{"choices": [{"delta": {}, "finish_reason": "stop"}]}])

    def _anthropic(self, body):
        msgs = []
        for m in body["messages"]:
            for b in m["content"]:
                if b["type"] == "tool_result":
                    msgs.append({"role": "tool", "name": body.get("_last_tool", "")})
                elif b["type"] == "tool_use":
                    body["_last_tool"] = b["name"]
                    msgs.append({"role": "tool_call", "name": b["name"]})
                elif b["type"] == "text" and m["role"] == "user":
                    msgs.append({"role": "user", "content": b["text"]})
        # name tool results after the call before them
        last = None
        for m in msgs:
            if m["role"] == "tool_call":
                last = m["name"]
            elif m["role"] == "tool":
                m["name"] = last
        step = plan([m for m in msgs if m["role"] != "tool_call"])
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        def ev(e):
            self.wfile.write(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode())
        ev({"type": "message_start", "message": {"usage": {"input_tokens": 10}}})
        if "tool" in step:
            ev({"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "tu1", "name": step["tool"]}})
            a = json.dumps(step["args"])
            ev({"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": a[:4]}})
            ev({"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": a[4:]}})
            ev({"type": "message_delta", "delta": {"stop_reason": "tool_use"}})
        else:
            ev({"type": "content_block_start", "index": 0, "content_block": {"type": "text"}})
            ev({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": step["text"]}})
            ev({"type": "message_delta", "delta": {"stop_reason": "end_turn"}})
        ev({"type": "message_stop"})


def serve() -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.requests = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
