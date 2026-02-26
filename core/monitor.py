"""
core/monitor.py - 포지션 모니터링 (경기 종료 후 결과 감지)

폴링 방식으로 보유 포지션의 토큰 가격을 주기적으로 확인.
  - best_bid >= 0.95  → 승리 (토큰 가격 1달러에 수렴)
  - best_bid <= 0.05  → 패배 (토큰 가격 0달러에 수렴)
  - 그 외             → 경기 미종료, 대기

연속 3패 시 자동 중단 플래그 설정 → 폴링 루프 종료.
"""

import asyncio
import logging

import aiohttp

from config import MAX_CONSECUTIVE_LOSSES, CLOB_HOST
from core.db import DB
from core.executor import Executor
from core.notifier import notify_settled

log = logging.getLogger(__name__)

MONITOR_INTERVAL = 600    # 10분마다 포지션 점검
WIN_THRESHOLD    = 0.95   # 이 이상 → 승리
LOSS_THRESHOLD   = 0.05   # 이 이하 → 패배


class Monitor:
    """보유 포지션 모니터링 및 결과 정산."""

    def __init__(self, executor: Executor, db: DB):
        self._executor = executor
        self._db       = db
        self._stopped  = False

    async def run(self, session: aiohttp.ClientSession) -> None:
        """10분 간격으로 보유 포지션 상태 확인."""
        log.info("[monitor] 포지션 모니터링 시작")
        while not self._stopped:
            await asyncio.sleep(MONITOR_INTERVAL)
            await self._check_all(session)

    async def _check_all(self, session: aiohttp.ClientSession) -> None:
        pending = self._db.get_pending_bets()
        if not pending:
            return

        log.info(f"[monitor] 보유 포지션 {len(pending)}개 점검")

        for bet in pending:
            await self._check_one(session, bet)

        # 연속 패배 체크
        consecutive = self._db.count_consecutive_losses()
        if consecutive >= MAX_CONSECUTIVE_LOSSES:
            log.error(f"[monitor] 연속 {consecutive}패 — 봇 자동 중단")
            self._stopped = True

    async def _check_one(
        self, session: aiohttp.ClientSession, bet: dict
    ) -> None:
        token_id = bet["token_id"]
        bet_id   = bet["id"]
        bet_usdc = bet["bet_usdc"]

        bid = await self._fetch_best_bid(session, token_id)
        if bid is None:
            return

        if bid >= WIN_THRESHOLD:
            # 승리: 매수 금액 × (1 / poly_price) 만큼 수익
            pnl = round(bet_usdc * (1 / bet["poly_price"]) - bet_usdc, 2)
            self._db.settle_bet(bet_id, "win", pnl)
            log.info(
                f"[monitor] 🏆 승리: {bet['event_title']} | P&L=+${pnl:.2f}"
            )
            await notify_settled(session, bet["event_title"], "win", pnl)

        elif bid <= LOSS_THRESHOLD:
            # 패배: 베팅 금액 전액 손실
            pnl = -round(bet_usdc, 2)
            self._db.settle_bet(bet_id, "loss", pnl)
            log.info(
                f"[monitor] 💀 패배: {bet['event_title']} | P&L=-${bet_usdc:.2f}"
            )
            await notify_settled(session, bet["event_title"], "loss", pnl)

    async def _fetch_best_bid(
        self, session: aiohttp.ClientSession, token_id: str
    ) -> float | None:
        """CLOB REST API로 best_bid 조회."""
        try:
            async with session.get(
                f"{CLOB_HOST}/book",
                params={"token_id": token_id},
            ) as resp:
                resp.raise_for_status()
                book = await resp.json()
            bids = book.get("bids", [])
            if not bids:
                return None
            return float(bids[0].get("price", 0))
        except Exception as e:
            log.warning(f"[monitor] 오더북 조회 실패 {token_id[-8:]}: {e}")
            return None
