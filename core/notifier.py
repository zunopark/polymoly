"""
core/notifier.py - 텔레그램 알림

주요 알림:
  - 봇 시작 / 중단
  - 기회 감지 (배당 역전 발생)
  - 매수 체결 / 실패
  - 결과 정산 (승/패)
  - 연속 패배 자동 중단

Telegram Bot API: POST https://api.telegram.org/bot{TOKEN}/sendMessage
"""

import logging
import os
from datetime import datetime, timezone

import aiohttp
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


async def _send(session: aiohttp.ClientSession, text: str) -> None:
    """텔레그램 메시지 전송. 실패 시 로그만 남기고 계속 진행."""
    token   = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        log.debug("[notifier] 텔레그램 미설정 — 알림 스킵")
        return

    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

    try:
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                log.warning(f"[notifier] 텔레그램 오류 {resp.status}: {body[:200]}")
    except Exception as e:
        log.warning(f"[notifier] 전송 실패: {e}")


# ── 알림 함수 ────────────────────────────────────────────────

async def notify_started(session: aiohttp.ClientSession) -> None:
    await _send(session, "🟢 <b>polymoly 봇 시작</b>\nPolymarket 배당 역전 모니터링 시작.")


async def notify_stopped(session: aiohttp.ClientSession, reason: str = "") -> None:
    await _send(session, f"🔴 <b>봇 중단</b>\n{reason}")


async def notify_opportunity(
    session: aiohttp.ClientSession,
    opp,   # ArbitrageOpportunity (순환 import 방지로 타입 힌트 생략)
) -> None:
    """배당 역전 기회 감지 알림."""
    text = (
        f"⚡ <b>기회 감지</b>\n"
        f"마켓: {opp.event_title}\n"
        f"정배: {opp.favorite_team} ({opp.matched.pinnacle.favorite_odds:.2f}배 / {opp.pinnacle_prob:.1%})\n"
        f"폴리마켓: {opp.poly_price:.2f}  갭: {opp.gap_size:.2f}\n"
        f"유동성: {opp.liquidity_shares:.0f}  베팅: ${opp.bet_usdc:.0f}\n"
        f"매수: {opp.buy_token_label}"
    )
    await _send(session, text)


async def notify_executed(session: aiohttp.ClientSession, result) -> None:
    """매수 체결 알림."""
    opp = result.opportunity
    text = (
        f"✅ <b>매수 체결</b>\n"
        f"마켓: {opp.event_title}\n"
        f"정배: {opp.favorite_team} | 매수: {opp.buy_token_label}\n"
        f"금액: ${opp.bet_usdc:.0f} @ {opp.poly_price:.2f}\n"
        f"order_id: {result.order_id}"
    )
    await _send(session, text)


async def notify_failed(session: aiohttp.ClientSession, result) -> None:
    """매수 실패 알림."""
    opp = result.opportunity
    text = (
        f"❌ <b>매수 실패</b> [{result.status}]\n"
        f"마켓: {opp.event_title}\n"
        f"{result.message}"
    )
    await _send(session, text)


async def notify_settled(
    session: aiohttp.ClientSession,
    event_title: str,
    outcome: str,
    pnl: float,
) -> None:
    """경기 결과 정산 알림."""
    icon = "🏆" if outcome == "win" else "💀"
    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
    text = (
        f"{icon} <b>정산</b> [{outcome.upper()}]\n"
        f"마켓: {event_title}\n"
        f"P&L: {pnl_str}"
    )
    await _send(session, text)


async def notify_auto_stopped(
    session: aiohttp.ClientSession,
    consecutive_losses: int,
    stats: dict,
) -> None:
    """연속 패배 자동 중단 알림."""
    text = (
        f"🚨 <b>연속 {consecutive_losses}패 — 봇 자동 중단</b>\n"
        f"총 베팅: {stats.get('total', 0)}회 | "
        f"승: {stats.get('wins', 0)} / 패: {stats.get('losses', 0)}\n"
        f"총 P&L: ${stats.get('total_pnl', 0):+.2f}"
    )
    await _send(session, text)


async def notify_low_credits(
    session: aiohttp.ClientSession,
    remaining: int,
    used: int = 0,
) -> None:
    """Odds API 크레딧 부족 경고 알림."""
    text = (
        f"⚠️ <b>Odds API 크레딧 부족</b>\n"
        f"잔여: {remaining:,} / 사용: {used:,}\n"
        f"크레딧이 최솟값 이하로 떨어져 Odds API 호출을 중단합니다.\n"
        f"다음 월 결제 후 봇을 재시작하세요."
    )
    await _send(session, text)


# ── 디버깅/모니터링 알림 ──────────────────────────────────────

async def notify_poll_start(
    session: aiohttp.ClientSession,
    cycle_num: int,
    active_positions: int = 0,
    credits_remaining: int | None = None,
) -> None:
    """폴링 사이클 시작 알림."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    credits_str = f"{credits_remaining:,}" if credits_remaining is not None else "미확인"
    text = (
        f"📊 <b>폴링 #{cycle_num}</b>  {now}\n"
        f"보유 포지션: {active_positions}개  |  잔여 크레딧: {credits_str}"
    )
    await _send(session, text)


async def notify_no_games(session: aiohttp.ClientSession) -> None:
    """Odds API 정배 경기 없음."""
    await _send(
        session,
        "ℹ️ <b>정배 경기 없음</b>\nNBA 경기 없는 날이거나 전부 비등 배당.",
    )


async def notify_no_markets(session: aiohttp.ClientSession) -> None:
    """Gamma API 폴리마켓 마켓 없음."""
    await _send(
        session,
        "⚠️ <b>폴리마켓 마켓 없음</b>\nGamma API에서 NBA 마켓 조회 결과 없음.",
    )


async def notify_no_matches(
    session: aiohttp.ClientSession,
    n_pinnacle: int,
    n_poly: int,
) -> None:
    """Pinnacle ↔ 폴리마켓 경기 매핑 실패."""
    await _send(
        session,
        f"⚠️ <b>매핑 실패</b>\n"
        f"Pinnacle {n_pinnacle}경기 ↔ 폴리마켓 {n_poly}마켓\n"
        f"팀명 정규화 또는 시간 매칭 문제일 수 있음.",
    )


async def notify_no_opportunities(
    session: aiohttp.ClientSession,
    n_matched: int,
) -> None:
    """스캔 완료 — 조건 미충족으로 기회 없음."""
    await _send(
        session,
        f"ℹ️ <b>기회 없음</b>\n{n_matched}경기 스캔 완료 — 갭/유동성 조건 미충족.",
    )


async def notify_error(
    session: aiohttp.ClientSession,
    context: str,
    error_msg: str,
) -> None:
    """오류 발생 알림 (네트워크 / 예상치 못한 오류)."""
    await _send(
        session,
        f"❌ <b>오류 [{context}]</b>\n{error_msg}",
    )


async def notify_credits_warning(
    session: aiohttp.ClientSession,
    remaining: int,
    threshold: int,
) -> None:
    """Odds API 크레딧 경고 (Warning 수준, 아직 호출 차단 아님)."""
    await _send(
        session,
        f"⚠️ <b>크레딧 경고</b>\n"
        f"잔여: {remaining:,} (경고 임계값: {threshold:,})\n"
        f"조만간 크레딧이 소진될 수 있습니다.",
    )
