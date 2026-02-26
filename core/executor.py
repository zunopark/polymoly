"""
core/executor.py - 폴리마켓 FOK 시장가 매수 실행

ArbitrageOpportunity를 받아 CLOB에 FOK(Fill-Or-Kill) 매수 주문 실행.
주문 성공 시 SQLite에 포지션 기록.

주문 방식:
  - MarketOrderArgs: 시장가, amount(USDC 기준), worst_price(슬리피지 보호)
  - FOK: 즉시 전량 체결 or 전량 취소
  - py-clob-client는 동기 SDK → asyncio.to_thread()로 비동기 래핑
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    ApiCreds, MarketOrderArgs, OrderType, PartialCreateOrderOptions,
)
from py_clob_client.order_builder.constants import BUY

from config import CLOB_HOST, CHAIN_ID, MAX_POSITIONS
from core.db import DB
from core.scanner import ArbitrageOpportunity

load_dotenv()
log = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """주문 실행 결과."""
    success:     bool
    order_id:    str | None
    status:      str          # "matched" | "fok_cancelled" | "error" | "skipped"
    message:     str
    opportunity: ArbitrageOpportunity
    timestamp:   datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __str__(self) -> str:
        opp = self.opportunity
        tag = "✅" if self.success else "❌"
        return (
            f"{tag} [{self.status.upper()}] {opp.event_title}\n"
            f"  정배: {opp.favorite_team} | 매수: {opp.buy_token_label} "
            f"| ${opp.bet_usdc:.0f} @ {opp.poly_price:.2f}\n"
            f"  {self.message}"
        )


class Executor:
    """폴리마켓 주문 실행기."""

    def __init__(self, db: DB):
        self._db   = db
        self._client: ClobClient | None = None

    async def initialize(self) -> None:
        """CLOB L2 클라이언트 초기화."""
        await asyncio.to_thread(self._init_client)

    def _init_client(self) -> None:
        key         = os.getenv("PRIVATE_KEY")
        funder      = os.getenv("FUNDER_ADDRESS")
        api_key     = os.getenv("POLY_API_KEY")
        secret      = os.getenv("POLY_SECRET")
        passphrase  = os.getenv("POLY_PASSPHRASE")
        sig_type    = int(os.getenv("POLY_SIGNATURE_TYPE", "1"))

        if not all([key, funder, api_key, secret, passphrase]):
            raise ValueError("[executor] 폴리마켓 자격증명 미설정 (.env 확인)")

        creds = ApiCreds(
            api_key=api_key,
            api_secret=secret,
            api_passphrase=passphrase,
        )
        self._client = ClobClient(
            host=CLOB_HOST,
            chain_id=CHAIN_ID,
            key=key,
            funder=funder,
            signature_type=sig_type,
            creds=creds,
        )
        log.info("[executor] CLOB 클라이언트 초기화 완료")

    def has_position(self, token_id: str) -> bool:
        """해당 token_id의 포지션이 이미 있는지 확인."""
        return token_id in self._db.get_active_token_ids()

    async def execute(self, opp: ArbitrageOpportunity) -> ExecutionResult:
        """FOK 매수 주문 실행."""
        if self._client is None:
            return ExecutionResult(
                success=False, order_id=None, status="error",
                message="클라이언트 미초기화", opportunity=opp,
            )

        # 최대 포지션 수 체크
        active = len(self._db.get_active_token_ids())
        if active >= MAX_POSITIONS:
            log.info(f"[executor] 최대 포지션 도달 ({active}/{MAX_POSITIONS}) — 스킵")
            return ExecutionResult(
                success=False, order_id=None, status="skipped",
                message=f"최대 포지션 {MAX_POSITIONS}개 도달",
                opportunity=opp,
            )

        return await asyncio.to_thread(self._place_order, opp)

    def _place_order(self, opp: ArbitrageOpportunity) -> ExecutionResult:
        """동기 주문 실행 (to_thread에서 호출).

        올바른 시장가 주문 플로우:
          1. get_tick_size / get_neg_risk  →  주문 옵션 조회
          2. create_market_order(args, options)  →  EIP-712 서명
          3. post_order(signed, OrderType.FOK)   →  CLOB 제출
        """
        try:
            # 1. 마켓별 tick_size / neg_risk 조회 (없으면 주문 거부됨)
            tick_size = self._client.get_tick_size(opp.token_id)
            neg_risk  = self._client.get_neg_risk(opp.token_id)
            log.debug(
                f"[executor] 마켓 옵션: tick_size={tick_size}, neg_risk={neg_risk}"
            )

            order_args = MarketOrderArgs(
                token_id = opp.token_id,
                amount   = opp.bet_usdc,    # USDC 금액 (BUY 기준)
                side     = BUY,
                price    = opp.poly_price,  # worst-price: 슬리피지 상한
            )
            options = PartialCreateOrderOptions(
                tick_size=tick_size,
                neg_risk=neg_risk,
            )

            # 2. 서명
            signed_order = self._client.create_market_order(order_args, options)
            # 3. FOK 제출
            resp = self._client.post_order(signed_order, OrderType.FOK)

            order_id     = resp.get("orderID") or resp.get("order_id")
            status_field = resp.get("status", "")
            error_msg    = resp.get("errorMsg", "")

            # 성공: "matched"(즉시 체결) 또는 "delayed"(스포츠 마켓 3초 지연 후 체결)
            if status_field in ("matched", "delayed"):
                self._db.insert_bet(
                    game_id       = opp.game_id,
                    event_title   = opp.event_title,
                    token_id      = opp.token_id,
                    buy_label     = opp.buy_token_label,
                    favorite_team = opp.favorite_team,
                    pinnacle_odds = opp.matched.pinnacle.favorite_odds,
                    pinnacle_prob = opp.pinnacle_prob,
                    poly_price    = opp.poly_price,
                    gap_size      = opp.gap_size,
                    bet_usdc      = opp.bet_usdc,
                    order_id      = order_id,
                    commence_time = opp.matched.pinnacle.commence_time.isoformat(),
                )
                label = "체결" if status_field == "matched" else "지연 체결(3s)"
                log.info(
                    f"[executor] {label}: {opp.event_title} | "
                    f"{opp.buy_token_label} ${opp.bet_usdc:.0f} @ {opp.poly_price:.2f} | "
                    f"order_id={order_id}"
                )
                return ExecutionResult(
                    success=True, order_id=order_id, status=status_field,
                    message=f"{label} @ {opp.poly_price:.2f}",
                    opportunity=opp,
                )

            # FOK 미체결 (errorMsg 포함 출력)
            reason = error_msg or f"status={status_field}"
            log.warning(
                f"[executor] FOK 미체결: {opp.event_title} | {reason}"
            )
            return ExecutionResult(
                success=False, order_id=order_id, status="fok_cancelled",
                message=f"FOK 미체결 ({reason})",
                opportunity=opp,
            )

        except Exception as e:
            log.error(f"[executor] 주문 오류: {opp.event_title} — {e}", exc_info=True)
            return ExecutionResult(
                success=False, order_id=None, status="error",
                message=str(e), opportunity=opp,
            )
