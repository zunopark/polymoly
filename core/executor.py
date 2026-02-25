"""
core/executor.py - 폴리마켓 FOK 시장가 매수 실행

역할:
  ArbitrageOpportunity를 받아 폴리마켓 CLOB에 FOK BUY 주문 실행.
  갭 크기에 따라 베팅 금액 차등 적용 (BET_SIZE_TIERS).
  주문 성공 시 SQLite에 포지션 기록.

주문 전략:
  - FOK(Fill-Or-Kill): 즉시 전량 체결 or 전량 취소
  - amount: 갭 크기별 베팅 금액 (BET_SIZE_TIERS)
  - price(worst-price): 감지된 poly_price로 설정 (슬리피지 보호)

py-clob-client는 동기(sync) SDK → asyncio.to_thread()로 비동기 래핑.
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderType, MarketOrderArgs, PartialCreateOrderOptions
from py_clob_client.order_builder.constants import BUY

from config import (
    CLOB_HOST, CHAIN_ID,
    MAX_BET_USDC, MIN_BET_USDC, MAX_POSITIONS,
    BET_SIZE_TIERS,
)
from core.scanner import ArbitrageOpportunity
from core.db import DB

load_dotenv()
log = logging.getLogger(__name__)


# ── 데이터 구조 ─────────────────────────────────────────────

@dataclass
class ExecutionResult:
    """주문 실행 결과."""
    success: bool
    order_id: str | None
    status: str       # "matched" | "delayed" | "fok_cancelled" | "error" | "skipped"
    message: str
    opportunity: ArbitrageOpportunity
    bet_usdc: float
    price: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __str__(self) -> str:
        ts = self.timestamp.strftime("%H:%M:%S")
        opp = self.opportunity
        if self.success:
            return (
                f"[{ts}] 주문 {self.status.upper()}\n"
                f"  마켓: {opp.question}\n"
                f"  체결가: {self.price:.3f}  금액: ${self.bet_usdc:.2f}\n"
                f"  주문 ID: {self.order_id}"
            )
        return (
            f"[{ts}] 주문 실패 ({self.status})\n"
            f"  마켓: {opp.question}\n"
            f"  사유: {self.message}"
        )


# ── 갭 크기별 베팅 금액 계산 ────────────────────────────────

def calc_bet_size(gap_size: float) -> float:
    """갭 크기에 따라 베팅 금액 결정.

    BET_SIZE_TIERS 기준:
      15~20센트: $10
      20~30센트: $20
      30센트 이상: $30
    """
    for gap_min, gap_max, bet in BET_SIZE_TIERS:
        if gap_min <= gap_size < gap_max:
            return float(bet)
    # 마지막 티어 이상
    last_bet = BET_SIZE_TIERS[-1][2]
    return float(last_bet)


# ── Executor 클래스 ─────────────────────────────────────────

class Executor:
    """
    ArbitrageOpportunity를 받아 FOK 시장가 매수를 실행하는 엔진.

    사용법 (main.py):
        executor = Executor(db)
        await executor.initialize()
        result = await executor.execute(opp)
    """

    def __init__(self, db: DB):
        self._db = db
        self._client: ClobClient | None = None
        self._neg_risk_cache: dict[str, bool] = {}
        self._open_positions: dict[str, ExecutionResult] = {}   # order_id → result
        self._initialized = False

    # ── 초기화 ────────────────────────────────────────────────

    def _build_client(self) -> ClobClient:
        """L2 ClobClient 초기화 (동기)."""
        private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
        funder      = os.getenv("FUNDER_ADDRESS")
        sig_type    = int(os.getenv("POLY_SIGNATURE_TYPE", "1"))
        api_key     = os.getenv("POLY_API_KEY")
        secret      = os.getenv("POLY_SECRET")
        passphrase  = os.getenv("POLY_PASSPHRASE")

        missing = [k for k, v in {
            "POLYMARKET_PRIVATE_KEY": private_key,
            "FUNDER_ADDRESS": funder,
            "POLY_API_KEY": api_key,
            "POLY_SECRET": secret,
            "POLY_PASSPHRASE": passphrase,
        }.items() if not v]

        if missing:
            raise EnvironmentError(f"[executor] .env 미설정: {', '.join(missing)}")

        creds = ApiCreds(
            api_key=api_key,
            api_secret=secret,
            api_passphrase=passphrase,
        )
        return ClobClient(
            host=CLOB_HOST,
            chain_id=CHAIN_ID,
            key=private_key,
            creds=creds,
            signature_type=sig_type,
            funder=funder,
        )

    async def initialize(self) -> None:
        """비동기 초기화 — main.py 시작 시 1회 호출."""
        if self._initialized:
            return
        self._client = await asyncio.to_thread(self._build_client)
        self._initialized = True
        log.info("[executor] L2 클라이언트 초기화 완료")

    # ── 동기 헬퍼 (to_thread에서 실행) ───────────────────────

    def _get_neg_risk(self, token_id: str) -> bool:
        """neg_risk 조회 — 캐시 우선, 없으면 SDK 호출."""
        if token_id not in self._neg_risk_cache:
            result = self._client.get_neg_risk(token_id)
            if isinstance(result, dict):
                neg_risk = result.get("neg_risk", False)
            else:
                neg_risk = bool(result)
            self._neg_risk_cache[token_id] = neg_risk
        return self._neg_risk_cache[token_id]

    def _submit_fok_order(
        self,
        token_id: str,
        amount_usdc: float,
        worst_price: float,
        tick_size: str,
        neg_risk: bool,
    ) -> dict:
        """동기: FOK 시장가 매수 주문 생성 + 제출."""
        signed_order = self._client.create_market_order(
            MarketOrderArgs(
                token_id=token_id,
                side=BUY,
                amount=amount_usdc,
                price=worst_price,
            ),
            PartialCreateOrderOptions(
                tick_size=tick_size,
                neg_risk=neg_risk,
            ),
        )
        return self._client.post_order(signed_order, OrderType.FOK)

    # ── 포지션 관리 ────────────────────────────────────────────

    @property
    def open_positions(self) -> dict:
        return dict(self._open_positions)

    def position_count(self) -> int:
        return len(self._open_positions)

    def has_position_for_token(self, token_id: str) -> bool:
        return any(
            r.opportunity.token_id == token_id
            for r in self._open_positions.values()
        )

    def record_position(self, result: ExecutionResult) -> None:
        if result.order_id:
            self._open_positions[result.order_id] = result
            log.info(
                f"[executor] 포지션 기록: {result.order_id[-8:]}  "
                f"현재 {self.position_count()}/{MAX_POSITIONS}개"
            )

    def close_position(self, order_id: str) -> None:
        removed = self._open_positions.pop(order_id, None)
        if removed:
            log.info(
                f"[executor] 포지션 종료: {order_id[-8:]}  "
                f"남은 포지션 {self.position_count()}개"
            )

    # ── 메인 진입점 ────────────────────────────────────────────

    async def execute(self, opp: ArbitrageOpportunity) -> ExecutionResult:
        """
        ArbitrageOpportunity를 받아 FOK 매수 주문 실행.

        Returns:
            ExecutionResult — 성공/실패 모두 반환, 예외 없음
        """
        if not self._initialized:
            await self.initialize()

        token_id = opp.token_id

        # ── 사전 검사 1: 포지션 한도 ──────────────────────────
        if self.position_count() >= MAX_POSITIONS:
            msg = f"포지션 한도 초과 ({self.position_count()}/{MAX_POSITIONS})"
            log.warning(f"[executor] {msg}")
            return ExecutionResult(
                success=False, order_id=None,
                status="skipped", message=msg,
                opportunity=opp, bet_usdc=0, price=opp.poly_price,
            )

        # ── 사전 검사 2: 동일 토큰 중복 매수 방지 ─────────────
        if self.has_position_for_token(token_id):
            msg = f"이미 보유 중인 토큰 ({token_id[-8:]})"
            log.debug(f"[executor] {msg} — 스킵")
            return ExecutionResult(
                success=False, order_id=None,
                status="skipped", message=msg,
                opportunity=opp, bet_usdc=0, price=opp.poly_price,
            )

        # ── 베팅 금액 결정 (갭 크기별 차등) ──────────────────
        bet_usdc  = calc_bet_size(opp.gap_size)
        tick_size = opp.tick_size

        log.info(
            f"[executor] 주문 준비 | {opp.question}\n"
            f"  poly_ask={opp.poly_price:.3f}  갭={opp.gap_size:.3f}  "
            f"금액=${bet_usdc:.0f}  tick={tick_size}"
        )

        try:
            neg_risk = await asyncio.to_thread(self._get_neg_risk, token_id)
            response = await asyncio.to_thread(
                self._submit_fok_order,
                token_id,
                bet_usdc,
                opp.poly_price,
                tick_size,
                neg_risk,
            )
        except Exception as e:
            msg = str(e)
            log.error(f"[executor] 주문 오류: {msg}")
            return ExecutionResult(
                success=False, order_id=None,
                status="error", message=msg,
                opportunity=opp, bet_usdc=bet_usdc, price=opp.poly_price,
            )

        # ── 응답 해석 ─────────────────────────────────────────
        order_id     = response.get("orderID") or response.get("order_id")
        status       = response.get("status", "unknown")
        error_msg    = response.get("errorMsg", "")
        success_flag = response.get("success", True)

        is_success = success_flag and status in ("matched", "delayed")

        if error_msg == "FOK_ORDER_NOT_FILLED_ERROR":
            result = ExecutionResult(
                success=False, order_id=order_id,
                status="fok_cancelled",
                message="FOK 체결 실패 — 갭 소멸 또는 유동성 부족",
                opportunity=opp, bet_usdc=bet_usdc, price=opp.poly_price,
            )
        elif not is_success or error_msg:
            result = ExecutionResult(
                success=False, order_id=order_id,
                status=status or "error",
                message=error_msg or f"예상치 못한 응답: {response}",
                opportunity=opp, bet_usdc=bet_usdc, price=opp.poly_price,
            )
        else:
            result = ExecutionResult(
                success=True, order_id=order_id,
                status=status, message="",
                opportunity=opp, bet_usdc=bet_usdc, price=opp.poly_price,
            )
            self.record_position(result)
            # SQLite 기록
            await asyncio.to_thread(
                self._db.insert_bet,
                game_id=opp.game_id,
                event_title=opp.event_title,
                question=opp.question,
                token_id=token_id,
                favorite_team=opp.favorite_team,
                pinnacle_odds=opp.pinnacle_odds,
                pinnacle_prob=opp.pinnacle_prob,
                poly_price=opp.poly_price,
                gap_size=opp.gap_size,
                bet_usdc=bet_usdc,
                order_id=order_id,
                commence_time=opp.commence_time.isoformat(),
            )

        log.info(str(result))
        return result
