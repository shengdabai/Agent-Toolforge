"""agent-memory-core: cross-session structured memory.

Pure-Python (stdlib only) core. Stores natural-language facts in SQLite,
auto-extracts entities, and recalls facts by keyword-overlap relevance with a
recency tie-break.

Public API:
    Memory(db_path)
        .add_fact(text, ts=None) -> int
        .recall(query, limit=5, entity=None) -> list[dict]
        .entities_of(fact_id) -> list[str]
        .close()
"""
from __future__ import annotations

import math
import re
import sqlite3
import time
from typing import List, Optional

# A "word" token: letters/digits/underscore runs. Used for both query
# tokenization and fact tokenization so overlap scoring is symmetric.
# ASCII behaviour is unchanged. Non-ASCII letters are words too (so "café" or
# "Москва" can be recalled), and each CJK/kana/hangul character is its own
# token because those scripts have no spaces — otherwise such facts were stored
# successfully but could never be recalled.
_CJK = "\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff"
_WORD_RE = re.compile("[%s]|[^\\W%s]+" % (_CJK, _CJK))

# Entity extraction patterns.
_QUOTED_RE = re.compile(r'"([^"]+)"')
_BACKTICK_RE = re.compile(r"`([^`]+)`")
# Capitalized token: starts uppercase, followed by word chars (handles
# multi-word run? No — single token; multi-word entities come from quotes).
_CAP_TOKEN_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\b")


def _tokenize(text: str) -> List[str]:
    """Lowercased word tokens for overlap scoring."""
    return [m.group(0).lower() for m in _WORD_RE.finditer(text)]


def _extract_entities(text: str) -> List[str]:
    """Deterministically extract entities, de-duplicated, order-stable.

    Rules:
      - text inside double quotes,
      - text inside backticks,
      - capitalized single tokens.
    Quoted/backticked spans are removed before capitalized-token scanning so a
    capitalized word inside a quote is not double-counted as a bare entity.
    """
    found: List[str] = []
    seen = set()

    def _add(raw: str) -> None:
        cleaned = raw.strip().strip("\"'`.,;:!?()[]{}")
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            found.append(cleaned)

    masked = text
    for span in _QUOTED_RE.findall(text):
        _add(span)
    for span in _BACKTICK_RE.findall(text):
        _add(span)
    # Mask the quoted/backticked regions so their internal capitalized words
    # are not re-extracted as standalone entities.
    masked = _QUOTED_RE.sub(" ", masked)
    masked = _BACKTICK_RE.sub(" ", masked)
    for span in _CAP_TOKEN_RE.findall(masked):
        _add(span)
    return found


class Memory:
    """SQLite-backed structured fact store."""

    def __init__(self, db_path: str):
        if not db_path or not isinstance(db_path, str):
            raise ValueError("db_path must be a non-empty string")
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        try:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    id   INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    ts   REAL NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    fact_id INTEGER NOT NULL,
                    entity  TEXT NOT NULL,
                    FOREIGN KEY (fact_id) REFERENCES facts(id)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_entities_lower "
                "ON entities (entity)"
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            raise RuntimeError(f"Failed to initialize schema: {exc}") from exc

    def add_fact(self, text: str, ts: Optional[float] = None) -> int:
        """Store a fact, auto-extract entities, return the new fact id."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError("fact text must be a non-empty string")
        if ts is None:
            ts = time.time()
        try:
            ts = float(ts)
        except (TypeError, ValueError) as exc:
            raise ValueError("ts must be a number") from exc
        if not math.isfinite(ts):
            # NaN is stored by SQLite as NULL (misleading constraint error) and
            # inf/NaN break the deterministic recency ordering.
            raise ValueError("ts must be a finite number")

        try:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO facts (text, ts) VALUES (?, ?)", (text, ts)
            )
            fact_id = cur.lastrowid
            for entity in _extract_entities(text):
                cur.execute(
                    "INSERT INTO entities (fact_id, entity) VALUES (?, ?)",
                    (fact_id, entity),
                )
            self._conn.commit()
            return int(fact_id)
        except sqlite3.Error as exc:
            self._conn.rollback()
            raise RuntimeError(f"Failed to add fact: {exc}") from exc

    def entities_of(self, fact_id: int) -> List[str]:
        """Return the extracted entities for one fact, insertion order."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT entity FROM entities WHERE fact_id = ? ORDER BY rowid",
            (int(fact_id),),
        )
        return [row["entity"] for row in cur.fetchall()]

    def recall(
        self,
        query: str,
        limit: int = 5,
        entity: Optional[str] = None,
    ) -> List[dict]:
        """Recall facts ranked by keyword overlap, recency tie-break."""
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValueError("limit must be a positive integer")

        query_tokens = set(_tokenize(query))
        if not query_tokens:
            return []

        cur = self._conn.cursor()
        if entity is not None:
            # Case-insensitive entity filter.
            cur.execute(
                """
                SELECT DISTINCT f.id, f.text, f.ts
                FROM facts f
                JOIN entities e ON e.fact_id = f.id
                WHERE LOWER(e.entity) = LOWER(?)
                """,
                (entity,),
            )
        else:
            cur.execute("SELECT id, text, ts FROM facts")
        rows = cur.fetchall()

        scored = []
        for row in rows:
            fact_tokens = set(_tokenize(row["text"]))
            score = len(query_tokens & fact_tokens)
            if score <= 0:
                continue
            scored.append(
                {
                    "id": int(row["id"]),
                    "text": row["text"],
                    "ts": float(row["ts"]),
                    "score": score,
                    "entities": self.entities_of(row["id"]),
                }
            )

        # score desc, ts desc, id desc — fully deterministic.
        scored.sort(key=lambda r: (r["score"], r["ts"], r["id"]), reverse=True)
        return scored[:limit]

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> "Memory":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
