"""The agent's own tables: conversations, long-term memory, logged promotions and an audit log of changes.

The whole Stock Compass database (every import, item and store) is the agent's knowledge base; it queries it
directly. Memory holds what the user tells it, what it concludes, and an automatic digest after every import,
so it can recall events across weeks ("what happened after the Wedding Gala leaflet?").
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime

from stockcompass.db import Database

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_chat (id VARCHAR PRIMARY KEY, title VARCHAR, created TIMESTAMP, updated TIMESTAMP,
    provider VARCHAR, model VARCHAR);
CREATE TABLE IF NOT EXISTS agent_msg (id VARCHAR PRIMARY KEY, chat_id VARCHAR, ts TIMESTAMP, role VARCHAR, data VARCHAR);
CREATE TABLE IF NOT EXISTS agent_memory (id VARCHAR PRIMARY KEY, ts TIMESTAMP, kind VARCHAR, text VARCHAR, tags VARCHAR,
    source VARCHAR, pinned BOOLEAN);
CREATE TABLE IF NOT EXISTS user_promo (code VARCHAR PRIMARY KEY, name VARCHAR, date_from DATE, date_to DATE, stores VARCHAR,
    items VARCHAR, note VARCHAR, created TIMESTAMP, source VARCHAR);
CREATE TABLE IF NOT EXISTS agent_log (ts TIMESTAMP, action VARCHAR, detail VARCHAR, chat_id VARCHAR);
"""


def ensure(db: Database):
    with db.lock:
        db.con.execute(SCHEMA)


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


# ------------------------------------------------------------------------------------------------ chats
def new_chat(db: Database, title: str = "New chat", provider: str = "", model: str = "") -> str:
    cid = uuid.uuid4().hex[:12]
    db.execute("INSERT INTO agent_chat VALUES (?,?,?,?,?,?)", [cid, title, now(), now(), provider, model])
    return cid


def chats(db: Database, limit: int = 200) -> list[dict]:
    return db.qd("SELECT id, title, updated, provider, model FROM agent_chat ORDER BY updated DESC LIMIT ?", [limit])


def rename_chat(db: Database, cid: str, title: str):
    db.execute("UPDATE agent_chat SET title=? WHERE id=?", [title[:120], cid])


def delete_chat(db: Database, cid: str):
    db.execute("DELETE FROM agent_msg WHERE chat_id=?", [cid])
    db.execute("DELETE FROM agent_chat WHERE id=?", [cid])


def add_msg(db: Database, cid: str, role: str, data: dict) -> str:
    mid = uuid.uuid4().hex[:14]
    # full-precision time keeps question and answer in order even within the same second
    db.execute("INSERT INTO agent_msg VALUES (?,?,?,?,?)", [mid, cid, datetime.now(), role, json.dumps(data, default=str)])
    db.execute("UPDATE agent_chat SET updated=? WHERE id=?", [now(), cid])
    return mid


def update_msg(db: Database, mid: str, data: dict):
    db.execute("UPDATE agent_msg SET data=? WHERE id=?", [json.dumps(data, default=str), mid])


def messages(db: Database, cid: str) -> list[dict]:
    rows = db.qd("SELECT id, ts, role, data FROM agent_msg WHERE chat_id=? ORDER BY ts, id", [cid])
    out = []
    for r in rows:
        d = json.loads(r["data"])
        d["_id"], d["_ts"], d["role"] = r["id"], r["ts"], r["role"]
        out.append(d)
    return out


# ------------------------------------------------------------------------------------------------ memory
def remember(db: Database, text: str, kind: str = "note", tags: str = "", source: str = "agent", pinned: bool = False) -> str:
    mid = uuid.uuid4().hex[:12]
    db.execute("INSERT INTO agent_memory VALUES (?,?,?,?,?,?,?)", [mid, now(), kind, text.strip()[:4000], tags, source, pinned])
    return mid


def forget(db: Database, mid: str):
    db.execute("DELETE FROM agent_memory WHERE id=?", [mid])


def memories(db: Database, limit: int = 500) -> list[dict]:
    return db.qd("SELECT * FROM agent_memory ORDER BY pinned DESC, ts DESC LIMIT ?", [limit])


_STOP = set("the a an and or of to in on for is are was were what whats how why who which with at by from this that it be as "
            "do does did we our us me my i you your status show tell give about than then there their".split())


def recall(db: Database, query: str, limit: int = 8) -> list[dict]:
    """Keyword search with a small recency bonus; pinned facts always count."""
    words = [w for w in re.findall(r"[a-z0-9]{2,}", (query or "").lower()) if w not in _STOP]
    rows = memories(db, 3000)
    scored = []
    t_now = now()
    for r in rows:
        txt = f"{r['text']} {r['tags'] or ''}".lower()
        hits = sum(1 for w in words if w in txt)
        if not hits and not r["pinned"]:
            continue
        age = max(0.0, (t_now - r["ts"]).days) if r["ts"] else 999
        scored.append((hits * 3 + (2 if r["pinned"] else 0) + max(0.0, 2 - age / 30), r))
    scored.sort(key=lambda x: -x[0])
    return [dict(id=r["id"], when=str(r["ts"])[:16], kind=r["kind"], text=r["text"], tags=r["tags"]) for _, r in scored[:limit]]


def log(db: Database, action: str, detail: dict | str, chat_id: str = ""):
    db.execute("INSERT INTO agent_log VALUES (?,?,?,?)", [now(), action, detail if isinstance(detail, str) else json.dumps(detail, default=str), chat_id])


# ------------------------------------------------------------------------------------------------ promotions logged by the user/agent
def promos(db: Database) -> list[dict]:
    return db.qd("SELECT * FROM user_promo ORDER BY date_from DESC NULLS LAST")


def save_promo(db: Database, code: str, name: str, date_from, date_to, stores: str = "", items: str = "", note: str = "", source: str = "agent"):
    db.execute("DELETE FROM user_promo WHERE code=?", [code])
    db.execute("INSERT INTO user_promo VALUES (?,?,?,?,?,?,?,?,?)", [code, name, date_from, date_to, stores, items, note, now(), source])


def delete_promo(db: Database, code: str) -> int:
    n = db.one("SELECT count(*) FROM user_promo WHERE code=?", [code], 0)
    db.execute("DELETE FROM user_promo WHERE code=?", [code])
    return n
