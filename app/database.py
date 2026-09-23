"""SQLite 持久化层 (database.py)

存储转子配置（槽位角度、禁用槽位）与历史配平方案（完整 JSON）。
数据库路径由环境变量 BALANCER_DB 覆盖，默认 /data/balancer.db。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = os.environ.get("BALANCER_DB", "/data/balancer.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    created_at  REAL NOT NULL,
    n_slots     INTEGER NOT NULL,
    request     TEXT NOT NULL,
    result      TEXT NOT NULL,
    u1_gmm      REAL NOT NULL,
    u2_gmm      REAL NOT NULL,
    grade       TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    path = DB_PATH
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def save_plan(name: str, request: dict, result: dict) -> int:
    m = result["metrics"]
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO plans
               (name, created_at, n_slots, request, result,
                u1_gmm, u2_gmm, grade)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name,
                time.time(),
                result["rotor"]["n_slots"],
                json.dumps(request, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False),
                m["u1_gmm"],
                m["u2_gmm"],
                m["grade"],
            ),
        )
        return int(cur.lastrowid)


def list_plans(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, name, created_at, n_slots,
                      u1_gmm, u2_gmm, grade
               FROM plans ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_plan(plan_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM plans WHERE id = ?", (plan_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["request"] = json.loads(d["request"])
        d["result"] = json.loads(d["result"])
        return d


def delete_plan(plan_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
        return cur.rowcount > 0
