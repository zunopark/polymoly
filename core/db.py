"""
core/db.py - SQLite 포지션 및 배팅 기록 관리

테이블:
  bets    - 체결된 배팅 기록 (진입 정보)
  results - 경기 결과 및 수익/손실 기록

모든 메서드는 동기(sync). 비동기 컨텍스트에서는 asyncio.to_thread()로 호출.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import DB_PATH

log = logging.getLogger(__name__)


class DB:
    """SQLite 배팅 기록 관리."""

    def __init__(self, db_path: str = DB_PATH):
        self._path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS bets (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id       TEXT NOT NULL,
                    event_title   TEXT NOT NULL,
                    token_id      TEXT NOT NULL,
                    buy_label     TEXT NOT NULL,      -- "YES" | "NO"
                    favorite_team TEXT NOT NULL,
                    pinnacle_odds REAL NOT NULL,
                    pinnacle_prob REAL NOT NULL,
                    poly_price    REAL NOT NULL,
                    gap_size      REAL NOT NULL,
                    bet_usdc      REAL NOT NULL,
                    order_id      TEXT,
                    commence_time TEXT NOT NULL,
                    bet_at        TEXT NOT NULL,
                    outcome       TEXT DEFAULT 'pending',  -- "win" | "loss" | "pending"
                    pnl_usdc      REAL DEFAULT NULL,
                    settled_at    TEXT DEFAULT NULL
                );

                CREATE TABLE IF NOT EXISTS results (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    bet_id     INTEGER NOT NULL REFERENCES bets(id),
                    order_id   TEXT NOT NULL,
                    outcome    TEXT NOT NULL,
                    pnl_usdc   REAL NOT NULL,
                    settled_at TEXT NOT NULL
                );
            """)
        log.info(f"[db] SQLite 초기화: {self._path}")

    # ── 베팅 기록 ────────────────────────────────────────────

    def insert_bet(
        self,
        game_id:       str,
        event_title:   str,
        token_id:      str,
        buy_label:     str,
        favorite_team: str,
        pinnacle_odds: float,
        pinnacle_prob: float,
        poly_price:    float,
        gap_size:      float,
        bet_usdc:      float,
        order_id:      str | None,
        commence_time: str,
    ) -> int:
        """베팅 기록 삽입. 삽입된 row ID 반환."""
        bet_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO bets
                  (game_id, event_title, token_id, buy_label, favorite_team,
                   pinnacle_odds, pinnacle_prob, poly_price, gap_size,
                   bet_usdc, order_id, commence_time, bet_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id, event_title, token_id, buy_label, favorite_team,
                    pinnacle_odds, pinnacle_prob, poly_price, gap_size,
                    bet_usdc, order_id, commence_time, bet_at,
                ),
            )
        log.info(f"[db] 베팅 삽입: bet_id={cur.lastrowid} | {event_title}")
        return cur.lastrowid

    def settle_bet(self, bet_id: int, outcome: str, pnl_usdc: float) -> None:
        """베팅 결과 정산."""
        settled_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE bets SET outcome=?, pnl_usdc=?, settled_at=? WHERE id=?",
                (outcome, pnl_usdc, settled_at, bet_id),
            )
            conn.execute(
                """
                INSERT INTO results (bet_id, order_id, outcome, pnl_usdc, settled_at)
                SELECT id, order_id, ?, ?, ? FROM bets WHERE id=?
                """,
                (outcome, pnl_usdc, settled_at, bet_id),
            )
        log.info(f"[db] 정산: bet_id={bet_id} | {outcome} | P&L=${pnl_usdc:+.2f}")

    # ── 조회 ─────────────────────────────────────────────────

    def get_pending_bets(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM bets WHERE outcome='pending' ORDER BY bet_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_active_token_ids(self) -> set[str]:
        """현재 보유 중인 포지션의 token_id 집합."""
        rows = self.get_pending_bets()
        return {r["token_id"] for r in rows}

    def count_consecutive_losses(self) -> int:
        """최근 결과에서 연속 패배 횟수."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT outcome FROM bets
                WHERE outcome IN ('win', 'loss')
                ORDER BY settled_at DESC
                LIMIT 10
                """
            ).fetchall()
        count = 0
        for row in rows:
            if row["outcome"] == "loss":
                count += 1
            else:
                break
        return count

    def get_stats(self) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN outcome='win'  THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN outcome='loss' THEN 1 ELSE 0 END) AS losses,
                    SUM(CASE WHEN outcome='pending' THEN 1 ELSE 0 END) AS pending,
                    ROUND(SUM(COALESCE(pnl_usdc, 0)), 2) AS total_pnl
                FROM bets
                """
            ).fetchone()
        return dict(row) if row else {}
