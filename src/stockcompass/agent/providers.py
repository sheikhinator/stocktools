"""AI providers for the Agent: cloud services (free and paid) and models running on this PC.

Almost every service speaks the OpenAI "chat completions" format, so one client covers them; Anthropic has its
own Messages format. Only the standard library is used (urllib), so nothing extra has to be bundled.

Cloud providers receive the question and whatever data the agent reads to answer it. Local providers (the
built-in offline runtime, Ollama, LM Studio, Jan, llama.cpp) keep everything on this PC.
"""

from __future__ import annotations

import json
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Provider:
    id: str
    name: str
    base_url: str
    kind: str = "openai"                 # openai | anthropic
    free: str = ""                       # what is free, in plain words
    key_url: str = ""                    # where to get a key
    models: list[str] = field(default_factory=list)   # suggestions; the live list comes from the provider
    needs_key: bool = True
    local: bool = False
    tools: bool = True                   # function calling supported
    vision: bool = True
    transcribe: str | None = None        # speech-to-text model on the same key
    effort: str = "reasoning_effort"     # how reasoning effort is passed: reasoning_effort | openrouter | none
    headers: dict = field(default_factory=dict)
    note: str = ""
    needs_account: bool = False          # Cloudflare: account id goes into the URL

    def url(self, account: str = "") -> str:
        return self.base_url.replace("{account_id}", account or "").rstrip("/")


# Researched September 2026. Free limits change often; the Test button shows what a key can really do.
PROVIDERS: list[Provider] = [
    Provider("openrouter", "OpenRouter", "https://openrouter.ai/api/v1",
             free="Free models (names end in ':free'): about 20 requests/min and 50/day; 1,000/day after a $10 top-up. No card needed.",
             key_url="https://openrouter.ai/keys", effort="openrouter",
             models=["openrouter/free", "openai/gpt-oss-20b:free", "google/gemma-4-31b-it:free", "nvidia/nemotron-3-super-120b-a12b:free",
                     "google/gemma-4-26b-a4b-it:free", "anthropic/claude-sonnet-5", "openai/gpt-5"],
             headers={"HTTP-Referer": "https://github.com/sheikhinator/stocktools", "X-Title": "Stock Compass"},
             note="One key reaches 400+ models from many companies."),
    Provider("groq", "Groq", "https://api.groq.com/openai/v1",
             free="Free tier: about 30 requests/min and 1,000/day per model. Very fast. Also free speech-to-text.",
             key_url="https://console.groq.com/keys", transcribe="whisper-large-v3-turbo",
             models=["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b", "llama-3.3-70b-versatile", "groq/compound"]),
    Provider("gemini", "Google Gemini (AI Studio)", "https://generativelanguage.googleapis.com/v1beta/openai",
             free="Free tier in Google AI Studio (limits per model, e.g. ~15 requests/min). Very long context.",
             key_url="https://aistudio.google.com/apikey",
             models=["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-pro-latest"],
             note="The '-latest' names always point at Google's current model, so they do not retire."),
    Provider("openai", "OpenAI (ChatGPT models)", "https://api.openai.com/v1",
             free="Paid (pay as you go).", key_url="https://platform.openai.com/api-keys", transcribe="whisper-1",
             models=["gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini"]),
    Provider("anthropic", "Anthropic (Claude)", "https://api.anthropic.com/v1", kind="anthropic",
             free="Paid (pay as you go).", key_url="https://console.anthropic.com/settings/keys", effort="anthropic",
             models=["claude-opus-5-5", "claude-sonnet-5", "claude-fable-5-1", "claude-haiku-4-5-20251001"]),
    Provider("mistral", "Mistral AI", "https://api.mistral.ai/v1",
             free="Free 'Experiment' plan with monthly credits.", key_url="https://console.mistral.ai/api-keys",
             models=["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest", "ministral-8b-latest"], effort="none"),
    Provider("github", "GitHub Models", "https://models.github.ai/inference",
             free="Free with any GitHub account (use a personal access token with 'models' permission). Daily limits per model.",
             key_url="https://github.com/settings/tokens",
             models=["openai/gpt-4.1", "openai/gpt-4.1-mini", "openai/gpt-4o-mini", "meta/Llama-3.3-70B-Instruct", "deepseek/DeepSeek-V3-0324"]),
    Provider("nvidia", "NVIDIA NIM", "https://integrate.api.nvidia.com/v1",
             free="Free for developers: about 40 requests/min.", key_url="https://build.nvidia.com/",
             models=["meta/llama-3.3-70b-instruct", "openai/gpt-oss-120b", "nvidia/nemotron-3-super-120b-a12b", "google/gemma-4-31b-it", "mistralai/mistral-nemotron"]),
    Provider("cerebras", "Cerebras", "https://api.cerebras.ai/v1",
             free="Trial credits (a card is needed for new accounts since Aug 2026). Extremely fast.",
             key_url="https://cloud.cerebras.ai/", models=["gpt-oss-120b", "gemma-4-31b", "llama3.1-8b"]),
    Provider("huggingface", "Hugging Face Inference", "https://router.huggingface.co/v1",
             free="$0.10 of free credit per month; thousands of open models.", key_url="https://huggingface.co/settings/tokens",
             models=["meta-llama/Llama-3.1-8B-Instruct", "Qwen/Qwen2.5-7B-Instruct", "google/gemma-3-4b-it", "microsoft/phi-4"]),
    Provider("cohere", "Cohere", "https://api.cohere.ai/compatibility/v1",
             free="Trial key: about 1,000 calls/month.", key_url="https://dashboard.cohere.com/api-keys",
             models=["command-a-03-2025", "command-r-plus", "command-r7b-12-2024"], effort="none"),
    Provider("sambanova", "SambaNova Cloud", "https://api.sambanova.ai/v1",
             free="Free tier with rate limits.", key_url="https://cloud.sambanova.ai/apis",
             models=["Meta-Llama-3.3-70B-Instruct", "DeepSeek-V3-0324", "Llama-4-Maverick-17B-128E-Instruct"], effort="none"),
    Provider("cloudflare", "Cloudflare Workers AI", "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
             free="10,000 'neurons' free every day.", key_url="https://dash.cloudflare.com/profile/api-tokens", needs_account=True,
             models=["@cf/meta/llama-3.3-70b-instruct-fp8-fast", "@cf/openai/gpt-oss-120b", "@cf/meta/llama-4-scout-17b-16e-instruct"],
             effort="none", note="Put your Cloudflare account id in the Account box."),
    Provider("zhipu", "Z.ai / Zhipu (GLM)", "https://open.bigmodel.cn/api/paas/v4",
             free="GLM 'Flash' models are free (1 request at a time).", key_url="https://open.bigmodel.cn/usercenter/apikeys",
             models=["glm-4.7-flash", "glm-4.5-flash", "glm-4.6v-flash"], effort="none"),
    Provider("modelscope", "ModelScope", "https://api-inference.modelscope.cn/v1",
             free="About 2,000 free requests/day.", key_url="https://modelscope.cn/my/myaccesstoken",
             models=["Qwen/Qwen3.5-27B", "Qwen/Qwen3.5-35B-A3B"], effort="none"),
    Provider("siliconflow", "SiliconFlow", "https://api.siliconflow.cn/v1",
             free="Some models free (e.g. Qwen3-8B).", key_url="https://cloud.siliconflow.cn/account/ak",
             models=["Qwen/Qwen3-8B", "deepseek-ai/DeepSeek-V3"], effort="none"),
    Provider("ollama_cloud", "Ollama Cloud", "https://ollama.com/v1",
             free="Free plan with session limits.", key_url="https://ollama.com/settings/keys",
             models=["gpt-oss:120b", "gpt-oss:20b", "qwen3.5:397b", "deepseek-v4-flash"]),
    Provider("ovh", "OVHcloud AI Endpoints", "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1",
             free="Works without a key at 2 requests/min; a free key raises it.", needs_key=False,
             key_url="https://endpoints.ai.cloud.ovh.net/", models=["gpt-oss-120b", "Meta-Llama-3_3-70B-Instruct", "Qwen3-32B"], effort="none"),
    Provider("llm7", "LLM7.io", "https://api.llm7.io/v1", free="Works without a key (about 10 requests/min).",
             needs_key=False, key_url="https://token.llm7.io/", models=["gpt-oss:20b", "mistral-small-3.1-24b-instruct"], effort="none"),
    Provider("together", "Together AI", "https://api.together.xyz/v1", free="Paid; a few free models.",
             key_url="https://api.together.ai/settings/api-keys",
             models=["meta-llama/Llama-3.3-70B-Instruct-Turbo-Free", "meta-llama/Llama-3.3-70B-Instruct-Turbo", "Qwen/Qwen2.5-72B-Instruct-Turbo"], effort="none"),
    Provider("deepseek", "DeepSeek", "https://api.deepseek.com/v1", free="Paid (very low prices).",
             key_url="https://platform.deepseek.com/api_keys", models=["deepseek-chat", "deepseek-reasoner"], effort="none"),
    Provider("xai", "xAI (Grok)", "https://api.x.ai/v1", free="Paid.", key_url="https://console.x.ai/",
             models=["grok-4", "grok-3-mini"]),
    Provider("fireworks", "Fireworks AI", "https://api.fireworks.ai/inference/v1", free="Paid; starter credit.",
             key_url="https://fireworks.ai/account/api-keys", models=["accounts/fireworks/models/llama-v3p3-70b-instruct"], effort="none"),
    Provider("dashscope", "Alibaba Qwen (DashScope)", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
             free="Free quota for new accounts.", key_url="https://modelstudio.console.alibabacloud.com/", models=["qwen-plus", "qwen-max", "qwen-turbo"], effort="none"),
    Provider("moonshot", "Moonshot (Kimi)", "https://api.moonshot.ai/v1", free="Paid; starter credit.",
             key_url="https://platform.moonshot.ai/console/api-keys", models=["kimi-k2-0905-preview", "moonshot-v1-32k"], effort="none"),
    Provider("perplexity", "Perplexity", "https://api.perplexity.ai", free="Paid.", key_url="https://www.perplexity.ai/settings/api",
             models=["sonar", "sonar-pro"], tools=False, effort="none", note="Web-search answers; cannot use Stock Compass tools."),
    # ---------------------------------------------------------------- on this PC
    Provider("offline", "Offline model (built in)", "http://127.0.0.1:18080/v1", needs_key=False, local=True,
             free="Runs on this PC. Nothing leaves the computer.", effort="none",
             note="Download and load a model in Agent → Offline models."),
    Provider("ollama", "Ollama (on this PC)", "http://localhost:11434/v1", needs_key=False, local=True, effort="none",
             free="Runs on this PC.", key_url="https://ollama.com/download"),
    Provider("lmstudio", "LM Studio (on this PC)", "http://localhost:1234/v1", needs_key=False, local=True, effort="none",
             free="Runs on this PC.", key_url="https://lmstudio.ai/"),
    Provider("jan", "Jan (on this PC)", "http://localhost:1337/v1", needs_key=False, local=True, effort="none",
             free="Runs on this PC.", key_url="https://jan.ai/"),
]
BY_ID = {p.id: p for p in PROVIDERS}


def get(pid: str, custom: list[dict] | None = None) -> Provider | None:
    if pid in BY_ID:
        return BY_ID[pid]
    for c in custom or []:
        if c.get("id") == pid:
            return Provider(c["id"], c.get("name") or c["id"], c["base_url"], kind=c.get("kind") or "openai",
                            needs_key=bool(c.get("needs_key", True)), local=bool(c.get("local")), effort="none",
                            free=c.get("free") or "Your own endpoint.", models=c.get("models") or [])
    return None


# ------------------------------------------------------------------------------------------------ errors
MODEL_GONE = re.compile(r"not found|no longer|unavailable|not available|does not exist|decommission|deprecat|unknown model|"
                        r"invalid model|model_not_found|not supported|no endpoints|retired", re.I)


class ProviderError(Exception):
    def __init__(self, message: str, status: int = 0, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def _friendly(status: int, body: str, p: Provider) -> str:
    msg = body
    try:
        j = json.loads(body)
        if isinstance(j, list) and j:
            j = j[0]
        e = j.get("error", j)
        msg = e.get("message") if isinstance(e, dict) else str(e)
        msg = msg or body
    except (ValueError, AttributeError):
        pass
    msg = (msg or "").strip()[:400]
    if status in (401, 403):
        return f"{p.name} rejected the key ({status}). Check it in Agent → Models & keys. {msg}"
    if status == 402:
        return f"{p.name}: no credit left on this account. {msg}"
    if status == 404 or (status == 400 and MODEL_GONE.search(msg)):
        return f"{p.name}: this model is not available. {msg}"
    if status == 429:
        return f"{p.name}: rate limit or free quota used up. Wait a minute or pick another model. {msg}"
    if status >= 500:
        return f"{p.name} is having a problem right now ({status}). Try again or pick another provider. {msg}"
    return f"{p.name} error {status}: {msg}"


# ------------------------------------------------------------------------------------------------ HTTP
def _open(req: urllib.request.Request, timeout: float):
    ctx = ssl.create_default_context()
    try:
        import certifi  # present in most Python installs; the system store is used otherwise
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)


def _headers(p: Provider, key: str) -> dict:
    h = {"Content-Type": "application/json", "User-Agent": "StockCompass/0.5"}
    if p.kind == "anthropic":
        h["x-api-key"] = key
        h["anthropic-version"] = "2023-06-01"
    elif key:
        h["Authorization"] = f"Bearer {key}"
    h.update(p.headers)
    return h


def http_json(method: str, url: str, headers: dict, body: dict | None = None, timeout: float = 60, p: Provider | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _open(req, timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        raise ProviderError(_friendly(e.code, raw, p) if p else f"HTTP {e.code}: {raw[:300]}", e.code, raw)
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
        where = p.name if p else url
        raise ProviderError(f"Cannot reach {where}: {getattr(e, 'reason', e)}. "
                            + ("Is it running on this PC?" if p and p.local else "Check the internet connection."))


def _sse(resp, stop: threading.Event | None):
    """Yield the JSON payload of every server-sent event line."""
    buf = b""
    while True:
        if stop is not None and stop.is_set():
            return
        chunk = resp.readline()
        if not chunk:
            break
        line = chunk.strip()
        if not line or line.startswith(b":"):
            continue
        if line.startswith(b"data:"):
            payload = line[5:].strip()
            if payload == b"[DONE]":
                return
            buf = payload
            try:
                yield json.loads(buf.decode("utf-8"))
            except ValueError:
                continue
        elif line.startswith(b"{"):          # some local servers stream bare JSON lines
            try:
                yield json.loads(line.decode("utf-8"))
            except ValueError:
                continue


# ------------------------------------------------------------------------------------------------ messages
# Internal format (close to OpenAI):
#   {"role": "system"|"user"|"assistant"|"tool", "content": str | [{"type":"text","text":..} |
#    {"type":"image","media_type":..,"data": base64}], "tool_calls": [{"id","name","args"}], "tool_call_id": .., "name": ..}

def _to_openai(msgs: list[dict], vision: bool) -> list[dict]:
    out = []
    for m in msgs:
        c = m.get("content")
        if isinstance(c, list):
            parts = []
            for part in c:
                if part.get("type") == "image":
                    if vision:
                        parts.append({"type": "image_url", "image_url": {"url": f"data:{part['media_type']};base64,{part['data']}"}})
                    else:
                        parts.append({"type": "text", "text": "[an image was attached; this model cannot see images]"})
                else:
                    parts.append({"type": "text", "text": part.get("text", "")})
            c = parts if any(pp["type"] != "text" for pp in parts) else "\n\n".join(pp["text"] for pp in parts)
        o = {"role": m["role"], "content": c if c is not None else ""}
        if m["role"] == "assistant" and m.get("tool_calls"):
            o["tool_calls"] = [{"id": tc["id"], "type": "function",
                                "function": {"name": tc["name"], "arguments": json.dumps(tc.get("args") or {})}}
                               for tc in m["tool_calls"]]
            if not c:
                o["content"] = None
        if m["role"] == "tool":
            o["tool_call_id"] = m["tool_call_id"]
        out.append(o)
    return out


def _to_anthropic(msgs: list[dict]) -> tuple[str, list[dict]]:
    system = "\n\n".join(m["content"] for m in msgs if m["role"] == "system" and isinstance(m["content"], str))
    out: list[dict] = []

    def push(role, blocks):
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": list(blocks)})

    for m in msgs:
        r = m["role"]
        if r == "system":
            continue
        c = m.get("content")
        blocks = []
        if isinstance(c, list):
            for part in c:
                if part.get("type") == "image":
                    blocks.append({"type": "image", "source": {"type": "base64", "media_type": part["media_type"], "data": part["data"]}})
                elif part.get("text"):
                    blocks.append({"type": "text", "text": part["text"]})
        elif c:
            blocks.append({"type": "text", "text": c})
        if r == "assistant":
            for tc in m.get("tool_calls") or []:
                blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc.get("args") or {}})
            if blocks:
                push("assistant", blocks)
        elif r == "tool":
            push("user", [{"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": c if isinstance(c, str) else json.dumps(c)}])
        else:
            if blocks:
                push("user", blocks)
    return system, out


def _tools_openai(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
            for t in tools]


def _tools_anthropic(tools: list[dict]) -> list[dict]:
    return [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]


REASONING_MODEL = re.compile(r"(^|/)(o\d|gpt-5|gpt-oss|deepseek-r|qwen3|gemini-2\.5|gemini-3|grok-3-mini|grok-4|magistral)", re.I)
EFFORT_TOKENS = {"low": 1500, "medium": 4000, "high": 8000}
THINK_BUDGET = {"medium": 3000, "high": 10000}


# ------------------------------------------------------------------------------------------------ chat
@dataclass
class Reply:
    text: str = ""
    thinking: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    stop: str = ""
    usage: dict = field(default_factory=dict)


def chat(p: Provider, key: str, model: str, msgs: list[dict], tools: list[dict] | None = None, effort: str = "medium",
         on_text: Callable[[str], None] | None = None, on_thinking: Callable[[str], None] | None = None,
         stop: threading.Event | None = None, account: str = "", timeout: float = 180, max_tokens: int | None = None) -> Reply:
    """One model turn, streamed. Retries once without optional extras a provider does not accept."""
    extras = {"effort": p.effort != "none", "tools": bool(tools) and p.tools}
    last: ProviderError | None = None
    for _attempt in range(3):
        try:
            if p.kind == "anthropic":
                return _chat_anthropic(p, key, model, msgs, tools if extras["tools"] else None, effort if extras["effort"] else None,
                                       on_text, on_thinking, stop, timeout, max_tokens)
            return _chat_openai(p, key, model, msgs, tools if extras["tools"] else None, effort if extras["effort"] else None,
                                on_text, on_thinking, stop, account, timeout, max_tokens)
        except ProviderError as e:
            last = e
            body = (e.body or str(e)).lower()
            if e.status in (400, 422) and extras["effort"] and re.search(r"reason|effort|thinking|budget", body):
                extras["effort"] = False
                continue
            if e.status in (400, 404, 422) and extras["tools"] and re.search(r"tool|function", body):
                extras["tools"] = False
                raise ToolsUnsupported(str(e)) from e
            raise
    raise last  # pragma: no cover


class ToolsUnsupported(ProviderError):
    pass


def _chat_openai(p, key, model, msgs, tools, effort, on_text, on_thinking, stop, account, timeout, max_tokens) -> Reply:
    body: dict = {"model": model, "messages": _to_openai(msgs, p.vision), "stream": True}
    if tools:
        body["tools"] = _tools_openai(tools)
        body["tool_choice"] = "auto"
    if max_tokens:
        body["max_tokens"] = max_tokens
    if effort and REASONING_MODEL.search(model or ""):
        if p.effort == "openrouter":
            body["reasoning"] = {"effort": effort}
        elif p.effort == "reasoning_effort":
            body["reasoning_effort"] = effort
    if p.id in ("openai", "openrouter", "groq"):
        body["stream_options"] = {"include_usage": True}
    req = urllib.request.Request(p.url(account) + "/chat/completions", data=json.dumps(body).encode(),
                                 headers=_headers(p, key), method="POST")
    rep = Reply()
    calls: dict[int, dict] = {}
    try:
        with _open(req, timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "text/event-stream" not in ctype and "ndjson" not in ctype:
                j = json.loads(resp.read().decode("utf-8") or "{}")    # server ignored stream=true
                ch = (j.get("choices") or [{}])[0]
                msg = ch.get("message") or {}
                rep.text = msg.get("content") or ""
                if rep.text and on_text:
                    on_text(rep.text)
                for i, tc in enumerate(msg.get("tool_calls") or []):
                    calls[i] = {"id": tc.get("id"), "name": tc["function"]["name"], "args": tc["function"].get("arguments") or ""}
                rep.stop = ch.get("finish_reason") or ""
                rep.usage = j.get("usage") or {}
            else:
                for ev in _sse(resp, stop):
                    if ev.get("error"):
                        raise ProviderError(_friendly(500, json.dumps(ev), p), 500, json.dumps(ev))
                    if ev.get("usage"):
                        rep.usage = ev["usage"]
                    for ch in ev.get("choices") or []:
                        d = ch.get("delta") or ch.get("message") or {}
                        th = d.get("reasoning") or d.get("reasoning_content")
                        if th:
                            rep.thinking += th
                            if on_thinking:
                                on_thinking(th)
                        if d.get("content"):
                            rep.text += d["content"]
                            if on_text:
                                on_text(d["content"])
                        for tc in d.get("tool_calls") or []:
                            i = tc.get("index", len(calls))
                            c = calls.setdefault(i, {"id": None, "name": "", "args": ""})
                            if tc.get("id"):
                                c["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                c["name"] += fn["name"]
                            if fn.get("arguments"):
                                c["args"] += fn["arguments"] if isinstance(fn["arguments"], str) else json.dumps(fn["arguments"])
                        if ch.get("finish_reason"):
                            rep.stop = ch["finish_reason"]
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        raise ProviderError(_friendly(e.code, raw, p), e.code, raw)
    except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
        raise ProviderError(f"Cannot reach {p.name}: {getattr(e, 'reason', e)}. "
                            + ("Is it running on this PC?" if p.local else "Check the internet connection."))
    for i in sorted(calls):
        c = calls[i]
        args = c["args"]
        try:
            args = json.loads(args) if isinstance(args, str) and args.strip() else (args or {})
        except ValueError:
            args = {"_raw": args}
        rep.tool_calls.append({"id": c["id"] or f"call_{uuid.uuid4().hex[:10]}", "name": c["name"], "args": args})
    return rep


def _chat_anthropic(p, key, model, msgs, tools, effort, on_text, on_thinking, stop, timeout, max_tokens) -> Reply:
    system, amsgs = _to_anthropic(msgs)
    budget = THINK_BUDGET.get(effort or "")
    body: dict = {"model": model, "messages": amsgs, "stream": True,
                  "max_tokens": max_tokens or (budget + 8000 if budget else 8000)}
    if system:
        body["system"] = system
    if tools:
        body["tools"] = _tools_anthropic(tools)
    if budget:
        body["thinking"] = {"type": "enabled", "budget_tokens": budget}
    req = urllib.request.Request(p.url() + "/messages", data=json.dumps(body).encode(), headers=_headers(p, key), method="POST")
    rep = Reply()
    blocks: dict[int, dict] = {}
    try:
        with _open(req, timeout) as resp:
            for ev in _sse(resp, stop):
                t = ev.get("type")
                if t == "error":
                    raise ProviderError(_friendly(500, json.dumps(ev), p), 500, json.dumps(ev))
                if t == "content_block_start":
                    b = ev["content_block"]
                    blocks[ev["index"]] = {"type": b["type"], "id": b.get("id"), "name": b.get("name"), "json": ""}
                elif t == "content_block_delta":
                    d = ev["delta"]
                    if d["type"] == "text_delta":
                        rep.text += d["text"]
                        if on_text:
                            on_text(d["text"])
                    elif d["type"] == "thinking_delta":
                        rep.thinking += d["thinking"]
                        if on_thinking:
                            on_thinking(d["thinking"])
                    elif d["type"] == "input_json_delta":
                        blocks[ev["index"]]["json"] += d["partial_json"]
                elif t == "message_delta":
                    rep.stop = (ev.get("delta") or {}).get("stop_reason") or rep.stop
                    rep.usage.update(ev.get("usage") or {})
                elif t == "message_start":
                    rep.usage.update((ev.get("message") or {}).get("usage") or {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        raise ProviderError(_friendly(e.code, raw, p), e.code, raw)
    except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
        raise ProviderError(f"Cannot reach {p.name}: {getattr(e, 'reason', e)}. Check the internet connection.")
    for i in sorted(blocks):
        b = blocks[i]
        if b["type"] == "tool_use":
            try:
                args = json.loads(b["json"]) if b["json"] else {}
            except ValueError:
                args = {"_raw": b["json"]}
            rep.tool_calls.append({"id": b["id"], "name": b["name"], "args": args})
    return rep


# ------------------------------------------------------------------------------------------------ models / test / speech
def model_error(e: Exception) -> bool:
    """The model itself is the problem (retired, renamed, not free any more, busy): another model may work."""
    if not isinstance(e, ProviderError) or isinstance(e, ToolsUnsupported):
        return False
    if e.status in (404, 429, 503, 529):
        return True
    return e.status in (400, 422, 500) and bool(MODEL_GONE.search(f"{e} {e.body}"))


def rate_limited(e: Exception) -> bool:
    return isinstance(e, ProviderError) and (e.status == 429 or bool(re.search(r"rate.?limit|quota|too many", str(e), re.I)))


def retry_after(e: Exception) -> float | None:
    """Seconds the provider asks us to wait ('try again in 26.45s', 'retryDelay': '26s', 'retry after 12 seconds')."""
    t = f"{e} {getattr(e, 'body', '')}"
    m = re.search(r"(?:try again|retry)[^0-9]{0,20}(?:(\d+)m)?(\d+(?:\.\d+)?)\s*(s|sec|second|ms)", t, re.I) or \
        re.search(r'"retryDelay"\s*:\s*"(?:(\d+)m)?(\d+(?:\.\d+)?)(s)"', t)
    if not m:
        return None
    v = float(m.group(2)) / (1000 if m.group(3).lower() == "ms" else 1) + 60 * float(m.group(1) or 0)
    return min(v, 600.0)


def token_limit(e: Exception) -> tuple[int, int] | None:
    """(limit, requested) from a tokens-per-minute error, e.g. Groq: 'Limit 8000, Used 5068, Requested 6459'."""
    t = f"{e} {getattr(e, 'body', '')}"
    m = re.search(r"Limit\s*:?\s*(\d+).{0,40}?Requested\s*:?\s*(\d+)", t, re.I | re.S)
    if m and re.search(r"token|TPM", t, re.I):
        return int(m.group(1)), int(m.group(2))
    return None


def suggested_model(e: Exception) -> str | None:
    """The replacement a provider names in its error ('Please update your code to use models/gemini-3.8-flash',
    'use this slug instead: x/y')."""
    t = f"{e} {getattr(e, 'body', '')}"
    for m in re.finditer(r"(?:use|instead:?|switch to|replaced by)\s+(?:the\s+)?(?:model\s+)?['`\"]?(?:models/)?([A-Za-z0-9][\w./:-]*[\w])", t, re.I):
        cand = m.group(1)
        if cand.lower() in ("the", "a", "this", "another", "it") or not re.search(r"[-./]", cand) or cand.startswith(("http", "www")):
            continue
        return cand
    return None


MODEL_INFO: dict[str, dict] = {}     # provider id -> {model id: {"tools": bool|None, "free": bool|None}} from the live list

_NOT_CHAT = re.compile(r"embed|whisper|tts|speech|audio|transcri|image|dall-?e|imagen|veo|vision-only|moderation|guard|rerank|"
                       r"bge-|e5-|clip|sdxl|flux|stable-diffusion|ocr|lyria|native-audio|computer-use|robotics|aqa", re.I)


def list_models(p: Provider, key: str, account: str = "") -> list[str]:
    j = http_json("GET", p.url(account) + "/models", _headers(p, key), timeout=20, p=p)
    data = j.get("data") if isinstance(j, dict) else j
    if data is None and isinstance(j, dict):
        data = j.get("models") or j.get("result") or []
    ids, info = [], {}
    for m in data or []:
        mid = m.get("id") or m.get("name") if isinstance(m, dict) else str(m)
        if not mid:
            continue
        mid = mid.replace("models/", "") if p.id == "gemini" else mid
        ids.append(mid)
        if isinstance(m, dict):
            sp = m.get("supported_parameters")
            pr = m.get("pricing") or {}
            free = None
            if pr:
                try:
                    free = float(pr.get("prompt") or 0) == 0 and float(pr.get("completion") or 0) == 0
                except (TypeError, ValueError):
                    free = None
            info[mid] = {"tools": ("tools" in sp) if isinstance(sp, list) else None,
                         "free": free if free is not None else (mid.endswith(":free") or None)}
    MODEL_INFO[p.id] = info
    return sorted(set(ids))


def _version(mid: str) -> tuple:
    return tuple(float(x) for x in re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)", mid)[:2]) or (0.0,)


def candidates(p: Provider, live: list[str], first: str | None = None, free_only: bool | None = None) -> list[str]:
    """Models to try, best first: the chosen one, the suggested ones that the provider still lists, then the best of the
    live list (chat models only; tool-capable and free first on OpenRouter; newest 'flash' first on Gemini)."""
    info = MODEL_INFO.get(p.id, {})
    live_set = set(live or [])
    out: list[str] = []

    def add(m):
        if m and m not in out:
            out.append(m)

    add(first)
    for m in p.models:
        if not live_set or m in live_set or m.endswith("-latest") or m == "openrouter/free":
            add(m)
    if free_only is None:
        free_only = p.id == "openrouter"
    pool = [m for m in live or [] if not _NOT_CHAT.search(m)]
    if free_only:
        pool = [m for m in pool if (info.get(m) or {}).get("free") or m.endswith(":free")]

    def score(m):
        i = info.get(m) or {}
        low = m.lower()
        s = 0.0
        s += 3 if i.get("tools") else (0 if i.get("tools") is False else 1)
        s += 2 if re.search(r"instruct|chat|flash|gpt|llama-3\.3|qwen3|gemma|mistral|deepseek|command|glm|kimi|nemotron", low) else 0
        s -= 2 if re.search(r"preview|exp|beta|tuning|base|-lite-|nano|mini-tts|thinking-exp|1b|3b\b", low) else 0
        if p.id == "gemini":
            s += 3 if "flash" in low else 0
            s += _version(low)[0] / 10
        return -s

    for m in sorted(pool, key=score):
        add(m)
    return out


def test(p: Provider, key: str, model: str | None = None, account: str = "") -> dict:
    """Check a provider end to end: key accepted, model list, one short answer, tool calling."""
    out = {"provider": p.id, "ok": False, "steps": []}
    t0 = time.time()
    models: list[str] = []
    try:
        models = list_models(p, key, account)
        out["steps"].append({"step": "models", "ok": True, "detail": f"{len(models)} models available"})
    except ProviderError as e:
        out["steps"].append({"step": "models", "ok": False, "detail": str(e)})
        if e.status in (401, 403) or not model and not p.models:
            out["error"] = str(e)
            return out
    out["models"] = models[:400]
    tries = candidates(p, models, model)[:6] or [model or ""]
    wanted = tries[0]
    errors, busy = [], 0
    for m in list(tries):
        if m not in tries[:8]:
            continue
        try:
            t1 = time.time()
            r = chat(p, key, m, [{"role": "user", "content": "Reply with the single word OK."}], effort="low",
                     account=account, timeout=60, max_tokens=400)
            model = m
            note = f" (switched from {wanted}: {errors[0][1][:120]})" if m != wanted and errors else ""
            out["steps"].append({"step": "chat", "ok": bool(r.text.strip() or r.thinking),
                                 "detail": f"answered '{r.text.strip()[:40]}' in {time.time() - t1:.1f}s{note}"})
            if m != wanted:
                out["switched_from"] = wanted
            break
        except ProviderError as e:
            errors.append((m, str(e)))
            busy += rate_limited(e)
            if not model_error(e) or (busy >= 2 and busy == len(errors)):   # limits are often per account
                break
            sug = suggested_model(e)
            if sug and sug not in tries and not (p.id == "openrouter" and not sug.endswith(":free")):
                tries.insert(tries.index(m) + 1, sug)
    else:
        model = None
    out["model"] = model or wanted
    if not model:
        last = errors[-1][1] if errors else "no model answered"
        if busy and busy == len(errors):
            out["busy"] = True
            last = f"{p.name} is busy: every model tried hit the free rate limit. Try again in a minute. ({last[:160]})"
        elif len(errors) > 1:
            last = f"Tried {len(errors)} models ({', '.join(m for m, _ in errors)}); none answered. Last error: {last[:200]}"
        out["steps"].append({"step": "chat", "ok": False, "detail": last})
        out["error"] = last
        return out
    if p.tools:
        tool = {"name": "get_total", "description": "Returns the total sales.", "parameters": {"type": "object", "properties": {}, "required": []}}
        try:
            r = chat(p, key, model, [{"role": "user", "content": "Call the get_total tool."}], tools=[tool], effort="low",
                     account=account, timeout=60, max_tokens=400)
            ok = bool(r.tool_calls)
            out["steps"].append({"step": "tools", "ok": ok, "detail": "can use Stock Compass tools" if ok else "answered without using tools (will use data briefings instead)"})
            out["tools"] = ok
        except ToolsUnsupported:
            out["steps"].append({"step": "tools", "ok": False, "detail": "this model cannot use tools (will use data briefings instead)"})
            out["tools"] = False
        except ProviderError as e:
            out["steps"].append({"step": "tools", "ok": False, "detail": str(e)})
    out["ok"] = all(s["ok"] for s in out["steps"] if s["step"] == "chat")
    out["seconds"] = round(time.time() - t0, 1)
    return out


def transcribe(p: Provider, key: str, wav: bytes, model: str | None = None, account: str = "", language: str | None = "en") -> str:
    """Speech to text through an OpenAI-style /audio/transcriptions endpoint."""
    boundary = "----sc" + uuid.uuid4().hex
    fields = {"model": model or p.transcribe or "whisper-1", "response_format": "json"}
    if language:
        fields["language"] = language
    body = b""
    for k, v in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"voice.wav\"\r\n"
             f"Content-Type: audio/wav\r\n\r\n").encode() + wav + f"\r\n--{boundary}--\r\n".encode()
    h = _headers(p, key)
    h["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(p.url(account) + "/audio/transcriptions", data=body, headers=h, method="POST")
    try:
        with _open(req, 120) as r:
            j = json.loads(r.read().decode("utf-8") or "{}")
            return (j.get("text") or "").strip()
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        raise ProviderError(_friendly(e.code, raw, p), e.code, raw)
    except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
        raise ProviderError(f"Cannot reach {p.name}: {getattr(e, 'reason', e)}")
