"""
core/notifier.py - 텔레그램 알림

주요 알림:
  - 봇 시작/중단
  - 배당 역전 기회 감지
  - 매수 체결/실패
  - 경기 결과 (승/패)
  - 연속 3패 자동 중단
"""

import logging
import os
import time
from datetime import datetime, timezone

import aiohttp
from dotenv import load_dotenv

from core.scanner import ArbitrageOpportunity

load_dotenv()
log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# 동일 token_id 재알림 억제 쿨다운 (초)
NOTIFY_COOLDOWN_SECS = 60.0
_notified_at: dict[str, float] = {}


async def _send(session: aiohttp.ClientSession, text: str) -> None:
    """텔레그램 메시지 전송 공통 헬퍼."""
    if not BOT_TOKEN or not CHAT_ID:
        return
    url = f"{TELEGRAM_API}/bot{BOT_TOKEN}/sendMessage"
    try:
        async with session.post(url, json={"chat_id": CHAT_ID, "text": text}) as resp:
            result = await resp.json()
            if not result.get("ok"):
                log.error(f"[notifier] 전송 실패: {result}")
    except aiohttp.ClientError as e:
        log.error(f"[notifier] 네트워크 오류: {e}")


async def notify_started(session: aiohttp.ClientSession) -> None:
    """봇 시작 알림."""
    await _send(session, "Polymarket 배당 역전 봇 시작됨")


async def notify_stopped(
    session: aiohttp.ClientSession,
    reason: str,
) -> None:
    """봇 중단 알림."""
    await _send(session, f"봇 자동 중단\n사유: {reason}")


async def notify_opportunity(
    session: aiohttp.ClientSession,
    opp: ArbitrageOpportunity,
) -> bool:
    """배당 역전 기회 감지 알림.

    Returns:
        True  — 알림 전송 (매수 진행 가능)
        False — 쿨다운 중 → 매수 스킵
    """
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("[notifier] 텔레그램 미설정. 알림 생략 (매수는 진행).")
        return True

    now = time.monotonic()
    if now - _notified_at.get(opp.token_id, 0.0) < NOTIFY_COOLDOWN_SECS:
        log.debug(f"[notifier] 쿨다운 중 — {opp.token_id[-8:]} 재알림 생략")
        return False

    _notified_at[opp.token_id] = now

    hrs = opp.hours_until_start
    bet_estimate = _calc_bet_estimate(opp.gap_size)

    text = (
        f"배당 역전 감지 — 매수 시도 중...\n"
        f"\n"
        f"경기: {opp.event_title}\n"
        f"마켓: {opp.question}\n"
        f"\n"
        f"정배 팀: {opp.favorite_team}\n"
        f"  Pinnacle: {opp.pinnacle_odds:.2f}배 → {opp.pinnacle_prob:.1%}\n"
        f"  폴리마켓 ask: {opp.poly_price:.2f}\n"
        f"  갭: {opp.gap_size:.2f}  (유동성: {opp.liquidity_shares:.0f} shares)\n"
        f"\n"
        f"예상 베팅: ${bet_estimate:.0f}\n"
        f"경기 시작까지: {hrs:.1f}시간"
    )
    await _send(session, text)
    return True


async def notify_executed(
    session: aiohttp.ClientSession,
    result,   # ExecutionResult
) -> None:
    """FOK BUY 체결 성공 알림."""
    opp = result.opportunity
    order_short = (result.order_id or "")[-12:]
    text = (
        f"매수 체결\n"
        f"\n"
        f"경기: {opp.event_title}\n"
        f"마켓: {opp.question}\n"
        f"정배: {opp.favorite_team} ({opp.pinnacle_odds:.2f}배)\n"
        f"\n"
        f"체결가: {result.price:.3f}  금액: ${result.bet_usdc:.0f}\n"
        f"주문: ...{order_short}"
    )
    await _send(session, text)


async def notify_failed(
    session: aiohttp.ClientSession,
    result,   # ExecutionResult
) -> None:
    """FOK BUY 실패 알림."""
    opp = result.opportunity
    status_label = {
        "fok_cancelled": "FOK 미체결",
        "error": "주문 오류",
    }.get(result.status, result.status)

    text = (
        f"{status_label}\n"
        f"\n"
        f"경기: {opp.event_title}\n"
        f"마켓: {opp.question}\n"
        f"사유: {result.message}"
    )
    await _send(session, text)


async def notify_result(
    session: aiohttp.ClientSession,
    event_title: str,
    question: str,
    outcome: str,
    poly_price: float,
    bet_usdc: float,
    pnl_usdc: float,
) -> None:
    """경기 결과 및 손익 알림."""
    outcome_label = "승리 (Win)" if outcome == "win" else "패배 (Loss)"
    pnl_sign = "+" if pnl_usdc >= 0 else ""

    text = (
        f"경기 결과: {outcome_label}\n"
        f"\n"
        f"경기: {event_title}\n"
        f"마켓: {question}\n"
        f"\n"
        f"진입가: {poly_price:.3f}  베팅: ${bet_usdc:.0f}\n"
        f"손익: {pnl_sign}{pnl_usdc:.2f} USDC"
    )
    await _send(session, text)


async def notify_auto_stopped(
    session: aiohttp.ClientSession,
    consecutive_losses: int,
    stats: dict,
) -> None:
    """연속 패배로 인한 자동 중단 알림."""
    text = (
        f"봇 자동 중단 — 연속 {consecutive_losses}패\n"
        f"\n"
        f"전략 재검토 후 재시작 필요\n"
        f"\n"
        f"전체 통계:\n"
        f"  총 베팅: {stats.get('total', 0)}회\n"
        f"  승/패: {stats.get('wins', 0)}/{stats.get('losses', 0)}\n"
        f"  총 손익: ${stats.get('total_pnl', 0):+.2f} USDC"
    )
    await _send(session, text)


def _calc_bet_estimate(gap_size: float) -> float:
    """갭 크기로 예상 베팅 금액 계산 (notifier 전용)."""
    from config import BET_SIZE_TIERS
    for gap_min, gap_max, bet in BET_SIZE_TIERS:
        if gap_min <= gap_size < gap_max:
            return float(bet)
    return float(BET_SIZE_TIERS[-1][2])
