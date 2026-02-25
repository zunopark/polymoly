"""
core/monitor.py - 포지션 모니터링 (경기 종료 후 정산)

이 봇의 특성:
  - 경기 시작 후 손절 불가 → 경기 종료까지 홀딩
  - 경기 결과(Yes/No 확정)를 폴리마켓에서 감지해 수익/손실 기록
  - 연속 3패 시 자동 중단

경기 결과 감지 방법:
  CLOB REST API로 token_id의 best_bid 조회.
  - best_bid → 0.99~1.00: Yes 확정 (정배 팀 승리) → 승리
  - best_bid → 0.00~0.01: No 확정 (정배 팀 패배) → 패배
  - 그 외: 아직 미확정 → 계속 대기

모니터링 주기: MONITOR_INTERVAL (기본 10분)
"""

import asyncio
import logging
from datetime import datetime, timezone

import aiohttp

from config import MONITOR_INTERVAL, MAX_CONSECUTIVE_LOSSES, CLOB_HOST
from core.db import DB
from core.executor import Executor, ExecutionResult

log = logging.getLogger(__name__)

# Yes 확정으로 간주할 best_bid 임계값 (1달러 근접)
WIN_THRESHOLD  = 0.95
# No 확정으로 간주할 best_bid 임계값 (0달러 근접)
LOSS_THRESHOLD = 0.05


class Monitor:
    """
    오픈 포지션 모니터링 + 경기 종료 후 수익/손실 기록.

    사용법 (main.py):
        monitor = Monitor(executor, db)
        await monitor.run(session)
    """

    def __init__(self, executor: Executor, db: DB):
        self._executor = executor
        self._db = db
        self._stopped = False  # 연속 3패 시 True → 루프 종료

    async def run(self, session: aiohttp.ClientSession) -> None:
        """모니터링 루프. main()의 asyncio.gather에 포함해 실행."""
        log.info("[monitor] 포지션 모니터링 시작")

        # DB에 pending 베팅이 있으면 in-memory 포지션으로 복구
        await self._restore_pending_positions()

        tick = 0
        while not self._stopped:
            await asyncio.sleep(MONITOR_INTERVAL)
            tick += 1

            try:
                await self._check_all(session)
            except Exception as e:
                log.error(f"[monitor] 점검 오류: {e}")

            # 5분마다 상태 로그
            if tick % (300 // MONITOR_INTERVAL) == 0:
                pos = self._executor.position_count()
                stats = await asyncio.to_thread(self._db.get_stats)
                log.info(
                    f"[monitor] 정상 운영 중 | 오픈 포지션 {pos}개 | "
                    f"통계: {stats}"
                )

        log.warning("[monitor] 자동 중단 — 연속 패배 한도 초과")

    async def _restore_pending_positions(self) -> None:
        """봇 재시작 시 DB의 pending 베팅을 in-memory 포지션으로 복구.

        실제 ExecutionResult 객체를 완전히 복원하기 어려우므로
        로그로만 남기고 별도 처리하지 않음.
        (폴링 루프가 DB pending 베팅을 직접 점검하도록 설계)
        """
        pending = await asyncio.to_thread(self._db.get_pending_bets)
        if pending:
            log.info(f"[monitor] DB에 미정산 베팅 {len(pending)}개 발견 — 모니터링 재개")
            for bet in pending:
                log.info(
                    f"  └ bet_id={bet['id']} | {bet['event_title']} | "
                    f"order_id={bet.get('order_id', 'N/A')}"
                )

    async def _check_all(self, session: aiohttp.ClientSession) -> None:
        """오픈 포지션 + DB pending 베팅 전체 점검."""
        # in-memory 오픈 포지션 점검
        for order_id, result in self._executor.open_positions.items():
            await self._check_position(session, order_id, result)

        # DB pending 중 in-memory에 없는 것도 점검 (재시작 복구)
        pending_bets = await asyncio.to_thread(self._db.get_pending_bets)
        in_memory_order_ids = set(self._executor.open_positions.keys())

        for bet in pending_bets:
            if bet.get("order_id") and bet["order_id"] not in in_memory_order_ids:
                await self._check_db_bet(session, bet)

    async def _check_position(
        self,
        session: aiohttp.ClientSession,
        order_id: str,
        result: ExecutionResult,
    ) -> None:
        """in-memory 포지션 점검 → 경기 결과 확인."""
        opp      = result.opportunity
        token_id = opp.token_id

        outcome = await self._detect_outcome(session, token_id)
        if outcome is None:
            log.debug(
                f"[monitor] 미확정 | {opp.question} | "
                f"시작까지 {opp.hours_until_start:.1f}h"
            )
            return

        # 수익/손실 계산
        shares  = result.bet_usdc / result.price
        if outcome == "win":
            pnl = round((1.0 - result.price) * shares, 2)
        else:
            pnl = round(-result.bet_usdc, 2)

        log.info(
            f"[monitor] 경기 결과: {outcome.upper()} | {opp.question}\n"
            f"  진입가={result.price:.3f}  베팅=${result.bet_usdc:.0f}  "
            f"P&L=${pnl:+.2f}"
        )

        # DB 정산
        bet = await asyncio.to_thread(self._db.get_bet_by_order_id, order_id)
        if bet:
            await asyncio.to_thread(
                self._db.settle_bet, bet["id"], outcome, pnl
            )

        # in-memory에서 제거
        self._executor.close_position(order_id)

        # 연속 패배 체크
        await self._check_consecutive_losses()

    async def _check_db_bet(
        self,
        session: aiohttp.ClientSession,
        bet: dict,
    ) -> None:
        """DB pending 베팅 (in-memory에 없는 것) 점검."""
        token_id = bet.get("token_id")
        if not token_id:
            return

        outcome = await self._detect_outcome(session, token_id)
        if outcome is None:
            return

        bet_usdc   = bet.get("bet_usdc", 0)
        poly_price = bet.get("poly_price", 0)

        shares = bet_usdc / poly_price if poly_price > 0 else 0
        if outcome == "win":
            pnl = round((1.0 - poly_price) * shares, 2)
        else:
            pnl = round(-bet_usdc, 2)

        await asyncio.to_thread(
            self._db.settle_bet, bet["id"], outcome, pnl
        )
        log.info(
            f"[monitor] DB 베팅 정산: bet_id={bet['id']} | "
            f"{outcome.upper()} | P&L=${pnl:+.2f}"
        )

        await self._check_consecutive_losses()

    async def _detect_outcome(
        self,
        session: aiohttp.ClientSession,
        token_id: str,
    ) -> str | None:
        """CLOB REST API로 토큰 현재가 조회 → 경기 결과 판별.

        Returns:
            "win"  — Yes 확정 (best_bid >= WIN_THRESHOLD)
            "loss" — No 확정  (best_bid <= LOSS_THRESHOLD)
            None   — 아직 미확정
        """
        url = f"{CLOB_HOST}/book"
        params = {"token_id": token_id}

        try:
            async with session.get(url, params=params) as resp:
                resp.raise_for_status()
                book = await resp.json()
        except aiohttp.ClientError as e:
            log.warning(f"[monitor] 오더북 조회 실패 {token_id[-8:]}: {e}")
            return None

        bids = book.get("bids", [])
        if not bids:
            return None

        best_bid = float(bids[0].get("price", 0))

        if best_bid >= WIN_THRESHOLD:
            return "win"
        if best_bid <= LOSS_THRESHOLD:
            return "loss"
        return None

    async def _check_consecutive_losses(self) -> None:
        """연속 패배 횟수 확인 → 한도 초과 시 봇 중단."""
        count = await asyncio.to_thread(self._db.count_consecutive_losses)
        if count >= MAX_CONSECUTIVE_LOSSES:
            log.error(
                f"[monitor] 연속 {count}패 감지 — 봇 자동 중단. 전략 재검토 필요."
            )
            self._stopped = True
