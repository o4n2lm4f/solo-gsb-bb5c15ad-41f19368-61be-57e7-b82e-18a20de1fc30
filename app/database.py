"""SQLite 数据访问层。仅使用标准库 sqlite3。"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config

_write_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS standard_addresses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ext_id       TEXT UNIQUE NOT NULL,
    address      TEXT NOT NULL,
    city         TEXT DEFAULT '',
    state        TEXT DEFAULT '',
    postcode     TEXT DEFAULT '',
    norm_text    TEXT DEFAULT '',
    house_number TEXT,
    tokens_json  TEXT DEFAULT '[]',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS match_results (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id          TEXT DEFAULT '',
    raw_input          TEXT NOT NULL,
    city               TEXT DEFAULT '',
    state              TEXT DEFAULT '',
    postcode           TEXT DEFAULT '',
    house_number       TEXT,
    status             TEXT NOT NULL,
    reasons_json       TEXT DEFAULT '[]',
    chosen_standard_id INTEGER,
    reviewed           INTEGER DEFAULT 0,
    reviewed_action    TEXT DEFAULT '',
    reviewed_note      TEXT DEFAULT '',
    created_at         TEXT NOT NULL,
    reviewed_at        TEXT,
    FOREIGN KEY (chosen_standard_id) REFERENCES standard_addresses(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS match_candidates (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id INTEGER NOT NULL,
    rank      INTEGER NOT NULL,
    detail    TEXT NOT NULL,
    FOREIGN KEY (result_id) REFERENCES match_results(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_results_status ON match_results(status);
CREATE INDEX IF NOT EXISTS idx_candidates_result ON match_candidates(result_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_conn() -> sqlite3.Connection:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# 标准地址
# ---------------------------------------------------------------------------

def upsert_standard(ext_id: str, address: str, city: str = "", state: str = "",
                    postcode: str = "", norm=None) -> int:
    with _write_lock, get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO standard_addresses
                (ext_id, address, city, state, postcode,
                 norm_text, house_number, tokens_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(ext_id) DO UPDATE SET
                address=excluded.address, city=excluded.city, state=excluded.state,
                postcode=excluded.postcode, norm_text=excluded.norm_text,
                house_number=excluded.house_number, tokens_json=excluded.tokens_json
        """, (ext_id, address, city, state, postcode,
              norm.text, norm.house_number, json.dumps(norm.tokens), _now()))
        row = conn.execute("SELECT id FROM standard_addresses WHERE ext_id=?",
                           (ext_id,)).fetchone()
        return row["id"]


def count_standards() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM standard_addresses").fetchone()["c"]


def list_standards(limit: int = 100, offset: int = 0, q: str = "") -> dict:
    with get_conn() as conn:
        if q:
            like = f"%{q.lower()}%"
            total = conn.execute(
                "SELECT COUNT(*) AS c FROM standard_addresses "
                "WHERE lower(address) LIKE ? OR lower(ext_id) LIKE ?",
                (like, like)).fetchone()["c"]
            rows = conn.execute(
                "SELECT id, ext_id, address, city, state, postcode, house_number "
                "FROM standard_addresses WHERE lower(address) LIKE ? OR lower(ext_id) LIKE ? "
                "ORDER BY id LIMIT ? OFFSET ?", (like, like, limit, offset)).fetchall()
        else:
            total = conn.execute("SELECT COUNT(*) AS c FROM standard_addresses").fetchone()["c"]
            rows = conn.execute(
                "SELECT id, ext_id, address, city, state, postcode, house_number "
                "FROM standard_addresses ORDER BY id LIMIT ? OFFSET ?",
                (limit, offset)).fetchall()
        return {"total": total, "items": [dict(r) for r in rows]}


def delete_standard(std_id: int) -> bool:
    with _write_lock, get_conn() as conn:
        cur = conn.execute("DELETE FROM standard_addresses WHERE id=?", (std_id,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# 匹配结果
# ---------------------------------------------------------------------------

def save_result(source_id: str, raw_input: str, status: str, reasons: list[str],
                candidates: list[dict], fields: dict, house_number: str | None) -> int:
    with _write_lock, get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO match_results
                (source_id, raw_input, city, state, postcode, house_number,
                 status, reasons_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (source_id, raw_input, fields.get("city", ""), fields.get("state", ""),
              fields.get("postcode", ""), house_number,
              status, json.dumps(reasons, ensure_ascii=False), _now()))
        result_id = cur.lastrowid
        for rank, cand in enumerate(candidates):
            conn.execute(
                "INSERT INTO match_candidates (result_id, rank, detail) VALUES (?,?,?)",
                (result_id, rank, json.dumps(cand, ensure_ascii=False)))
        return result_id


def list_results(status: str = "", reviewed: int | None = None,
                 limit: int = 50, offset: int = 0) -> dict:
    sql = "FROM match_results WHERE 1=1"
    params: list = []
    if status:
        sql += " AND status=?"
        params.append(status)
    if reviewed is not None:
        sql += " AND reviewed=?"
        params.append(reviewed)
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS c " + sql, params).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * {sql} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [limit, offset]).fetchall()
        items: list[dict] = []
        for r in rows:
            d = dict(r)
            d["reasons"] = json.loads(d.pop("reasons_json"))
            best = conn.execute(
                "SELECT detail FROM match_candidates WHERE result_id=? ORDER BY rank LIMIT 1",
                (r["id"],)).fetchone()
            d["best_candidate"] = json.loads(best["detail"]) if best else None
            items.append(d)
        return {"total": total, "items": items}


def get_result(result_id: int) -> dict | None:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM match_results WHERE id=?", (result_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["reasons"] = json.loads(d.pop("reasons_json"))
        cands = conn.execute(
            "SELECT rank, detail FROM match_candidates WHERE result_id=? ORDER BY rank",
            (result_id,)).fetchall()
        d["candidates"] = [json.loads(c["detail"]) for c in cands]
        return d


def review_result(result_id: int, action: str, chosen_standard_id: int | None,
                  note: str) -> bool:
    """action: confirm(确认首条) / choose(选定候选) / reject(判定无匹配)。"""
    status = {"confirm": "confirmed", "choose": "confirmed",
              "reject": "rejected"}.get(action, action)
    with _write_lock, get_conn() as conn:
        cur = conn.execute("""
            UPDATE match_results SET reviewed=1, reviewed_action=?, status=?,
                chosen_standard_id=?, reviewed_note=?, reviewed_at=?
            WHERE id=?
        """, (action, status, chosen_standard_id, note, _now(), result_id))
        return cur.rowcount > 0


def stats() -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS c FROM match_results GROUP BY status"
        ).fetchall()
        status_counts = {r["status"]: r["c"] for r in rows}
        status_counts.setdefault("auto_matched", 0)
        status_counts.setdefault("needs_review", 0)
        status_counts.setdefault("no_match", 0)
        status_counts.setdefault("confirmed", 0)
        status_counts.setdefault("rejected", 0)
        total_results = conn.execute("SELECT COUNT(*) AS c FROM match_results").fetchone()["c"]
        total_standards = conn.execute("SELECT COUNT(*) AS c FROM standard_addresses").fetchone()["c"]
    return {
        "standard_count": total_standards,
        "result_count": total_results,
        "status_counts": status_counts,
        "pending_review": status_counts.get("needs_review", 0),
    }
