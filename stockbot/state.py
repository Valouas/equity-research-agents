"""Historique local et rotation de l'univers. Aucune donnée n'est envoyée ailleurs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class State:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS universe (
                symbol TEXT PRIMARY KEY,
                name TEXT, country TEXT, exchange TEXT, isin TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                last_attempt TEXT, last_success TEXT,
                last_error TEXT
            );
            CREATE TABLE IF NOT EXISTS analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL, recorded_at TEXT NOT NULL,
                result TEXT NOT NULL, run_id TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS analyses_by_symbol
                ON analyses(symbol, id DESC);
            CREATE TABLE IF NOT EXISTS bot_meta (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            """
        )

    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM bot_meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO bot_meta(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def upsert_universe(self, items: list[dict], replace_active: bool = False) -> int:
        """Une liste globale complète peut désactiver les anciens titres, sans effacer l'historique."""
        if not items:
            return 0
        # Un ISIN permet de dédoubler certaines cotations d'un même titre.
        # Les ADR/classes distinctes ont parfois un autre ISIN et restent visibles.
        seen_isins: set[str] = set()
        clean: list[dict] = []
        for item in items:
            if not item.get("symbol"):
                continue
            isin = str(item.get("isin") or "").strip()
            if isin and isin in seen_isins:
                continue
            if isin:
                seen_isins.add(isin)
            clean.append(item)
        with self.db:
            if replace_active:
                self.db.execute("UPDATE universe SET active=0")
            for item in clean:
                self.db.execute(
                    """INSERT INTO universe(symbol,name,country,exchange,isin,active)
                    VALUES (?,?,?,?,?,1) ON CONFLICT(symbol) DO UPDATE SET
                    name=excluded.name, country=excluded.country,
                    exchange=excluded.exchange, isin=excluded.isin, active=1""",
                    (item["symbol"], item.get("name", ""), item.get("country", ""),
                     item.get("exchange", ""), item.get("isin", "")),
                )
        return len(clean)

    def universe_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM universe WHERE active=1").fetchone()[0]

    def queue(self, limit: int, priorities: list[str] | None = None) -> list[str]:
        # Les erreurs tournent aussi : un titre inaccessible ne bloque pas tout le scan.
        rows = self.db.execute(
            "SELECT symbol FROM universe WHERE active=1 "
            "ORDER BY COALESCE(last_attempt,''), symbol LIMIT ?", (limit,)
        ).fetchall()
        base = [row[0] for row in rows]
        preferred = []
        for symbol in dict.fromkeys(priorities or []):
            active = self.db.execute("SELECT 1 FROM universe WHERE symbol=? AND active=1", (symbol,)).fetchone()
            if active:
                preferred.append(symbol)
        preferred = preferred[:max(0, limit // 5)]
        return list(dict.fromkeys(preferred + base))[:limit]

    def record(self, symbol: str, run_id: str, result: dict) -> None:
        now = utc_now()
        with self.db:
            self.db.execute(
                "UPDATE universe SET last_attempt=?,last_success=?,last_error=NULL WHERE symbol=?",
                (now, now, symbol),
            )
            self.db.execute(
                "INSERT INTO analyses(symbol,recorded_at,result,run_id) VALUES(?,?,?,?)",
                (symbol, now, json.dumps(result, ensure_ascii=False, allow_nan=False), run_id),
            )

    def queue_subset(self, symbols: list[str], limit: int) -> list[str]:
        """Une liste explicite limitée tourne aussi lors des exécutions suivantes."""
        attempts = {row[0]: row[1] or "" for row in self.db.execute(
            "SELECT symbol,last_attempt FROM universe WHERE active=1"
        )}
        requested = list(dict.fromkeys(symbols))
        return sorted(requested, key=lambda symbol: attempts.get(symbol, ""))[:limit]

    def fail(self, symbol: str, message: str) -> None:
        with self.db:
            self.db.execute(
                "UPDATE universe SET last_attempt=?,last_error=? WHERE symbol=?",
                (utc_now(), message[:300], symbol),
            )

    def latest_results(self, max_age_days: int) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        rows = self.db.execute(
            """SELECT a.result FROM analyses a JOIN
            (SELECT symbol, MAX(id) AS latest_id FROM analyses GROUP BY symbol) b
            ON a.id=b.latest_id JOIN universe u ON u.symbol=a.symbol WHERE u.active=1"""
        ).fetchall()
        results = []
        for row in rows:
            result = json.loads(row[0])
            try:
                retrieved = datetime.fromisoformat(result["retrieved_at"].replace("Z", "+00:00"))
                if retrieved.tzinfo is None:
                    retrieved = retrieved.replace(tzinfo=timezone.utc)
                if retrieved >= cutoff:
                    results.append(result)
            except (KeyError, ValueError, TypeError):
                # Une date de récupération inconnue n'est pas une donnée fraîche.
                continue
        return results

    def close(self) -> None:
        self.db.close()
