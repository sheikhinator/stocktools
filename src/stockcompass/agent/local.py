"""Offline models: browse and download GGUF models, fetch the llama.cpp runtime once, and run the model on this PC.

After the one-time downloads everything works without internet and no data leaves the computer.
Also finds Ollama / LM Studio if the user already runs them, and offers offline speech-to-text (whisper.cpp).
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path

from stockcompass.paths import data_dir

from .providers import _open

PORT = 18080
HF = "https://huggingface.co"

# Tested families that follow instructions and call tools reasonably well at small sizes.
CATALOGUE = [
    {"id": "qwen2.5-3b", "name": "Qwen 2.5 3B Instruct", "repo": "bartowski/Qwen2.5-3B-Instruct-GGUF", "file": "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
     "gb": 1.9, "ram": 6, "note": "Best small all-rounder. Good with tables and tools. Recommended for most PCs."},
    {"id": "qwen2.5-7b", "name": "Qwen 2.5 7B Instruct", "repo": "bartowski/Qwen2.5-7B-Instruct-GGUF", "file": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
     "gb": 4.7, "ram": 10, "note": "Noticeably smarter analysis; needs 16 GB RAM for comfort."},
    {"id": "qwen3-4b", "name": "Qwen 3 4B", "repo": "Qwen/Qwen3-4B-GGUF", "file": "Qwen3-4B-Q4_K_M.gguf",
     "gb": 2.5, "ram": 7, "note": "Newer reasoning model; thinks before answering."},
    {"id": "llama3.2-3b", "name": "Llama 3.2 3B Instruct", "repo": "bartowski/Llama-3.2-3B-Instruct-GGUF", "file": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
     "gb": 2.0, "ram": 6, "note": "Meta's small model; fast."},
    {"id": "llama3.1-8b", "name": "Llama 3.1 8B Instruct", "repo": "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF", "file": "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
     "gb": 4.9, "ram": 10, "note": "Strong general model with tool use."},
    {"id": "phi3.5-mini", "name": "Phi 3.5 mini", "repo": "bartowski/Phi-3.5-mini-instruct-GGUF", "file": "Phi-3.5-mini-instruct-Q4_K_M.gguf",
     "gb": 2.4, "ram": 6, "note": "Microsoft's small model; good at reasoning over numbers."},
    {"id": "gemma2-2b", "name": "Gemma 2 2B", "repo": "bartowski/gemma-2-2b-it-GGUF", "file": "gemma-2-2b-it-Q4_K_M.gguf",
     "gb": 1.7, "ram": 4, "note": "Smallest; for older laptops. Limited tool use."},
]
WHISPER_MODELS = [
    {"id": "base.en", "name": "Whisper base (English)", "url": f"{HF}/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin", "mb": 148},
    {"id": "small.en", "name": "Whisper small (English, more accurate)", "url": f"{HF}/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin", "mb": 488},
]


def models_dir() -> Path:
    p = data_dir() / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def runtime_dir() -> Path:
    p = data_dir() / "runtime"
    p.mkdir(parents=True, exist_ok=True)
    return p


HF_TOKEN = {"value": ""}      # set by the agent service from the Hugging Face key (gated models, higher limits)


def _hf_headers() -> dict:
    return {"Authorization": f"Bearer {HF_TOKEN['value']}"} if HF_TOKEN["value"] else {}


def _get_json(url: str, timeout: float = 30):
    h = {"User-Agent": "StockCompass/0.4", "Accept": "application/json"}
    if url.startswith(HF):
        h.update(_hf_headers())
    req = urllib.request.Request(url, headers=h)
    with _open(req, timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ------------------------------------------------------------------------------------------------ browsing
def search_hf(query: str, limit: int = 30, mode: str = "gguf", sort: str = "") -> list[dict]:
    """mode 'gguf': files to download and run on this PC. mode 'online': chat models served by Hugging Face
    Inference Providers (run through the Hugging Face key, nothing to download)."""
    params = {"limit": limit, "direction": "-1", "sort": sort or ("downloads" if query else "trendingScore")}
    if query:
        params["search"] = query
    if mode == "online":
        params.update({"inference_provider": "all", "pipeline_tag": "text-generation"})
    else:
        params["filter"] = "gguf"
    try:
        rows = _get_json(f"{HF}/api/models?{urllib.parse.urlencode(params)}")
    except Exception:
        if params.get("sort") == "trendingScore":        # older API: fall back to downloads
            params["sort"] = "downloads"
            rows = _get_json(f"{HF}/api/models?{urllib.parse.urlencode(params)}")
        else:
            raise
    return [{"repo": r.get("id") or r.get("modelId"), "downloads": r.get("downloads"), "likes": r.get("likes"),
             "updated": (r.get("lastModified") or r.get("createdAt") or "")[:10], "gated": bool(r.get("gated")),
             "mode": mode} for r in rows]


def repo_files(repo: str) -> list[dict]:
    rows = _get_json(f"{HF}/api/models/{repo}/tree/main")
    out = []
    for r in rows:
        path = r.get("path") or ""
        if path.lower().endswith(".gguf") and "mmproj" not in path.lower():
            size = (r.get("lfs") or {}).get("size") or r.get("size") or 0
            q = re.search(r"(IQ\d_[A-Z]+|Q\d_K(_[SML])?|Q\d_[01]|Q\d|BF16|F16)", path, re.I)
            out.append({"file": path, "gb": round(size / 1e9, 2), "quant": q.group(0).upper() if q else ""})
    return sorted(out, key=lambda x: x["gb"])


def installed() -> list[dict]:
    extra = _extra_paths()
    files = sorted(models_dir().glob("*.gguf")) + [Path(p) for p in extra if Path(p).exists()]
    return [{"file": f.name, "path": str(f), "gb": round(f.stat().st_size / 1e9, 2),
             "name": next((c["name"] for c in CATALOGUE if c["file"] == f.name), f.stem)} for f in files]


def _extra_file() -> Path:
    return models_dir() / "linked.json"


def _extra_paths() -> list[str]:
    try:
        return json.loads(_extra_file().read_text())
    except Exception:
        return []


def link_file(path: str) -> dict:
    """Use a .gguf the user already has without copying it."""
    p = Path(path)
    if not p.exists() or p.suffix.lower() != ".gguf":
        raise ValueError("Pick a .gguf model file.")
    paths = [x for x in _extra_paths() if x != str(p)] + [str(p)]
    _extra_file().write_text(json.dumps(paths))
    return {"ok": True, "file": p.name}


def delete_model(path: str) -> dict:
    p = Path(path)
    if p.parent == models_dir() and p.exists():
        p.unlink()
    _extra_file().write_text(json.dumps([x for x in _extra_paths() if x != str(p)]))
    return {"ok": True}


# ------------------------------------------------------------------------------------------------ downloads
class Downloads:
    def __init__(self):
        self.jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self, url: str, dest: Path, name: str, after=None, headers: dict | None = None) -> str:
        for j in self.jobs.values():
            if j["dest"] == str(dest) and j["status"] == "running":
                return j["id"]
        jid = uuid.uuid4().hex[:8]
        job = {"id": jid, "name": name, "url": url, "dest": str(dest), "total": 0, "done": 0, "status": "running", "error": "",
               "started": time.time(), "speed": 0.0}
        self.jobs[jid] = job
        job["_headers"] = headers or {}
        threading.Thread(target=self._run, args=(job, after), daemon=True).start()
        return jid

    def cancel(self, jid: str):
        if jid in self.jobs:
            self.jobs[jid]["status"] = "cancelled"

    def _run(self, job, after):
        dest = Path(job["dest"])
        part = dest.with_suffix(dest.suffix + ".part")
        try:
            have = part.stat().st_size if part.exists() else 0
            headers = {"User-Agent": "StockCompass/0.4", **job.get("_headers", {})}
            if have:
                headers["Range"] = f"bytes={have}-"
            req = urllib.request.Request(job["url"], headers=headers)
            with _open(req, 60) as r:
                total = int(r.headers.get("Content-Length") or 0)
                if r.status == 206:
                    job["total"] = have + total
                else:
                    have = 0
                    job["total"] = total
                job["done"] = have
                t0, d0 = time.time(), have
                with open(part, "ab" if have else "wb") as f:
                    while True:
                        if job["status"] == "cancelled":
                            return
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        job["done"] += len(chunk)
                        dt = time.time() - t0
                        if dt > 1:
                            job["speed"] = (job["done"] - d0) / dt
            part.replace(dest)
            if after:
                after(dest)
            job["status"] = "done"
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)

    def list(self) -> list[dict]:
        return [{k: v for k, v in j.items() if not k.startswith("_")} | {"pct": round(j["done"] / j["total"] * 100, 1) if j["total"] else 0}
                for j in self.jobs.values()]


DOWNLOADS = Downloads()


def download_model(repo: str, file: str) -> str:
    url = f"{HF}/{repo}/resolve/main/{urllib.parse.quote(file)}?download=true"
    return DOWNLOADS.start(url, models_dir() / Path(file).name, Path(file).name, headers=_hf_headers())


# ------------------------------------------------------------------------------------------------ llama.cpp runtime
def _asset_pattern(kind: str, variant: str = "cpu") -> str:
    sysname, arch = platform.system(), platform.machine().lower()
    if kind == "whisper":
        return r"whisper-bin-x64\.zip$" if sysname == "Windows" else r"$^"
    if sysname == "Windows":
        if variant == "gpu":
            return r"bin-win-vulkan-x64\.zip$"        # Vulkan: NVIDIA, AMD and Intel graphics, no CUDA install needed
        return r"bin-win-cpu-x64\.zip$" if "arm" not in arch else r"bin-win-cpu-arm64\.zip$"
    if variant == "gpu" and sysname == "Linux":
        return r"bin-ubuntu-vulkan-x64\.zip$"
    if sysname == "Darwin":
        return r"bin-macos-arm64\.zip$" if "arm" in arch else r"bin-macos-x64\.zip$"
    return r"bin-ubuntu-x64\.zip$"


def _exe(name: str) -> str:
    return name + (".exe" if sys.platform == "win32" else "")


def find_exe(kind: str) -> Path | None:
    names = ["llama-server"] if kind == "llama" else ["whisper-cli", "main", "whisper"]
    for n in names:
        hits = list((runtime_dir() / kind).rglob(_exe(n)))
        if hits:
            return hits[0]
    if kind == "llama" and shutil.which("llama-server"):
        return Path(shutil.which("llama-server"))
    return None


def runtime_variant() -> str:
    try:
        return (runtime_dir() / "llama" / "variant.txt").read_text().strip() or "cpu"
    except OSError:
        return "cpu"


def runtime_status() -> dict:
    return {"llama": str(find_exe("llama") or ""), "whisper": str(find_exe("whisper") or ""), "variant": runtime_variant(),
            "cores": os.cpu_count() or 4}


def install_runtime(kind: str = "llama", variant: str = "cpu") -> str:
    """Download the latest llama.cpp (or whisper.cpp) release for this PC from GitHub. variant 'gpu' = Vulkan build."""
    repo = "ggml-org/llama.cpp" if kind == "llama" else "ggml-org/whisper.cpp"
    rel = _get_json(f"https://api.github.com/repos/{repo}/releases/latest")
    pat = re.compile(_asset_pattern(kind, variant), re.I)
    asset = next((a for a in rel.get("assets") or [] if pat.search(a["name"])), None)
    if not asset:
        raise RuntimeError(f"No {kind} build for this system in {repo} {rel.get('tag_name')}.")
    target = runtime_dir() / kind
    zpath = runtime_dir() / asset["name"]

    def unpack(p: Path):
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(p) as z:
            z.extractall(target)
        p.unlink(missing_ok=True)
        if kind == "llama":
            (target / "variant.txt").write_text(variant)
        if sys.platform != "win32":
            for f in target.rglob("*"):
                if f.is_file() and not f.suffix:
                    f.chmod(0o755)

    label = f"{kind}.cpp runtime {rel.get('tag_name')}" + (" (GPU)" if variant == "gpu" and kind == "llama" else "")
    return DOWNLOADS.start(asset["browser_download_url"], zpath, label, after=unpack)


class Server:
    """The built-in offline model: llama-server on 127.0.0.1:18080 (OpenAI-compatible, with tool calling)."""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.model: str = ""
        self.log: list[str] = []
        self.started = 0.0

    def status(self) -> dict:
        alive = bool(self.proc and self.proc.poll() is None)
        ready = False
        if alive:
            try:
                with _open(urllib.request.Request(f"http://127.0.0.1:{PORT}/health"), 2) as r:
                    ready = r.status == 200
            except Exception:
                ready = False
        return {"running": alive, "ready": ready, "model": Path(self.model).name if self.model else "", "path": self.model,
                "port": PORT, "log": self.log[-8:], "since": self.started, "gpu": "-ngl" in (getattr(self, "args", None) or []),
                "fast": "-fa" in (getattr(self, "args", None) or [])}

    def start(self, model_path: str, ctx: int = 8192, threads: int | None = None) -> dict:
        """Start llama-server tuned for speed. Newer/older llama.cpp builds accept different flags, so fall back
        step by step if the server refuses to start; a GPU build that fails falls back to the CPU."""
        exe = find_exe("llama")
        if not exe:
            raise RuntimeError("The offline runtime is not installed yet. Click 'Install offline runtime' first.")
        self.stop()
        cores = os.cpu_count() or 4
        t = threads or (max(2, cores // 2) if cores >= 8 else max(2, cores - 1))   # physical cores ≈ half the logical ones
        base = [str(exe), "-m", model_path, "--host", "127.0.0.1", "--port", str(PORT), "-c", str(ctx), "--jinja",
                "-t", str(t), "-tb", str(cores), "-np", "1"]
        speed = ["-b", "2048", "-ub", "512", "--cache-reuse", "256"]
        gpu = ["-ngl", "99"] if runtime_variant() == "gpu" else []
        attempts = [base + speed + gpu + ["-fa", "on"], base + speed + gpu + ["-fa"], base + speed + gpu, base + gpu, base]
        if gpu:
            attempts += [base + speed, base]
        flags = 0x08000000 if sys.platform == "win32" else 0        # CREATE_NO_WINDOW
        for args in attempts:
            self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(exe.parent),
                                         creationflags=flags, text=True, encoding="utf-8", errors="replace")
            self.model, self.log, self.started, self.args = model_path, [], time.time(), args
            threading.Thread(target=self._pump, daemon=True).start()
            for _ in range(30):                      # a bad flag makes it exit within a second or two
                if self.proc.poll() is not None:
                    break
                time.sleep(0.1)
            if self.proc.poll() is None:
                break
        return self.status()

    def _pump(self):
        p = self.proc
        if not p or not p.stdout:
            return
        for line in p.stdout:
            self.log.append(line.rstrip()[:300])
            if len(self.log) > 400:
                self.log = self.log[-200:]

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


SERVER = Server()


# ------------------------------------------------------------------------------------------------ other local apps
def detect_local() -> dict:
    out = {}
    try:
        tags = _get_json("http://localhost:11434/api/tags", 2)
        out["ollama"] = [m["name"] for m in tags.get("models") or []]
    except Exception:
        out["ollama"] = None
    for pid, url in (("lmstudio", "http://localhost:1234/v1/models"), ("jan", "http://localhost:1337/v1/models")):
        try:
            out[pid] = [m["id"] for m in _get_json(url, 2).get("data") or []]
        except Exception:
            out[pid] = None
    return out


def ollama_pull(name: str) -> str:
    """Ask a local Ollama to download a model, and follow its progress like our own downloads."""
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "name": f"Ollama: {name}", "url": "", "dest": "", "total": 0, "done": 0, "status": "running", "error": "",
           "started": time.time(), "speed": 0.0}
    DOWNLOADS.jobs[jid] = job

    def run():
        try:
            req = urllib.request.Request("http://localhost:11434/api/pull", data=json.dumps({"name": name, "stream": True}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with _open(req, 3600) as r:
                for line in r:
                    if job["status"] == "cancelled":
                        return
                    ev = json.loads(line.decode("utf-8") or "{}")
                    if ev.get("error"):
                        raise RuntimeError(ev["error"])
                    job["total"] = ev.get("total") or job["total"]
                    job["done"] = ev.get("completed") or job["done"]
            job["status"] = "done"
        except Exception as e:
            job["status"], job["error"] = "error", str(e)

    threading.Thread(target=run, daemon=True).start()
    return jid


# ------------------------------------------------------------------------------------------------ offline speech
def whisper_models() -> list[dict]:
    return [dict(m, installed=(models_dir() / Path(m["url"]).name).exists()) for m in WHISPER_MODELS]


def download_whisper(mid: str) -> str:
    m = next(x for x in WHISPER_MODELS if x["id"] == mid)
    return DOWNLOADS.start(m["url"], models_dir() / Path(m["url"]).name, m["name"])


def transcribe_offline(wav: bytes) -> str:
    exe = find_exe("whisper")
    model = next((models_dir() / Path(m["url"]).name for m in WHISPER_MODELS if (models_dir() / Path(m["url"]).name).exists()), None)
    if not exe or not model:
        raise RuntimeError("Offline voice needs the whisper runtime and a whisper model (Agent → Offline models → Voice).")
    tmp = runtime_dir() / f"voice-{uuid.uuid4().hex[:6]}.wav"
    tmp.write_bytes(wav)
    try:
        flags = 0x08000000 if sys.platform == "win32" else 0
        r = subprocess.run([str(exe), "-m", str(model), "-f", str(tmp), "-nt", "-np", "-l", "en"], capture_output=True, text=True,
                           timeout=180, creationflags=flags, encoding="utf-8", errors="replace")
        return " ".join(ln.strip() for ln in r.stdout.splitlines() if ln.strip()).strip()
    finally:
        tmp.unlink(missing_ok=True)
