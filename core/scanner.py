"""
core/scanner.py - 배당 역전 감지 엔진

4가지 실행 조건 모두 충족해야 ArbitrageOpportunity 반환:
  조건 1: Pinnacle 배당 <= 1.5      (odds_fetcher에서 사전 필터링 완료)
  조건 2: 폴리마켓 현재가 < 50센트
  조건 3: 갭 >= 15센트               (Pinnacle 임플라이드 확률 - 폴리마켓 현재가)
  조건 4: 폴리마켓 유동성 >= 50 shares

매수 토큰:
  정배팀이 홈팀(폴리마켓 YES측) → YES 토큰 ask 가격 조회
  정배팀이 원정팀(폴리마켓 NO측) → NO 토큰 ask 가격 조회
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiohttp

from config import (
    MAX_POLYMARKET_PRICE,
    GAP_THRESHOLD,
    MIN_LIQUIDITY_SHARES,
    BET_ENTRY_WINDOW_HRS,
    BET_ENTRY_DEADLINE_HRS,
    BET_SIZE_TIERS,
    MAX_BET_USDC,
    CLOB_HOST,
)
from core.matcher import MatchedGame

log = logging.getLogger(__name__)


@dataclass
class ArbitrageOpportunity:
    """감지된 배당 역전 기회."""
    matched:          MatchedGame
    poly_price:       float        # 폴리마켓 매수 가격 (best ask)
    pinnacle_prob:    float        # Pinnacle 임플라이드 확률 (소수)
    gap_size:         float        # 갭 크기 = pinnacle_prob - poly_price
    liquidity_shares: float        # 가용 유동성
    bet_usdc:         float        # 갭 크기에 따른 베팅 금액
    detected_at:      datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # 편의 프로퍼티
    @property
    def game_id(self) -> str:
        return self.matched.pinnacle.game_id

    @property
    def token_id(self) -> str:
        return self.matched.buy_token_id

    @property
    def event_title(self) -> str:
        return self.matched.poly.question

    @property
    def favorite_team(self) -> str:
        return self.matched.pinnacle.favorite_team

    @property
    def buy_token_label(self) -> str:
        return self.matched.buy_token_label

    def __str__(self) -> str:
        hrs = self.matched.pinnacle.hours_until_start()
        return (
            f"[기회] {self.event_title}\n"
            f"  정배: {self.favorite_team} "
            f"({self.matched.pinnacle.favorite_odds:.2f}배 / {self.pinnacle_prob:.1%})\n"
            f"  폴리마켓 ask: {self.poly_price:.2f}  갭: {self.gap_size:.2f}  "
            f"유동성: {self.liquidity_shares:.0f}  베팅: ${self.bet_usdc:.0f}\n"
            f"  경기 시작까지: {hrs:.1f}h | 매수 토큰: {self.buy_token_label}"
        )


async def scan(
    session:       aiohttp.ClientSession,
    matched_games: list[MatchedGame],
) -> list[ArbitrageOpportunity]:
    """매핑된 경기 목록에서 4조건 충족 기회 탐색."""
    opportunities = []

    for m in matched_games:
        opp = await _check(session, m)
        if opp is not None:
            opportunities.append(opp)
            log.info(str(opp))

    log.info(f"[scanner] {len(matched_games)}경기 스캔 → 기회 {len(opportunities)}개")
    return opportunities


async def _check(
    session: aiohttp.ClientSession,
    m: MatchedGame,
) -> ArbitrageOpportunity | None:
    """단일 매핑 경기에 대해 4조건 검사."""
    game = m.pinnacle

    # 경기 진입 시간 체크
    hrs = game.hours_until_start()
    if hrs > BET_ENTRY_WINDOW_HRS:
        log.debug(f"[scanner] 진입 전 ({hrs:.1f}h): {game.home_team} vs {game.away_team}")
        return None
    if hrs < BET_ENTRY_DEADLINE_HRS:
        log.debug(f"[scanner] 마감 ({hrs:.1f}h): {game.home_team} vs {game.away_team}")
        return None

    # 폴리마켓 오더북 조회 (정배팀 매수 토큰)
    book = await _fetch_orderbook(session, m.buy_token_id)
    if book is None:
        return None

    best_ask, shares = _best_ask_and_shares(book)
    if best_ask is None:
        log.debug(f"[scanner] ask 없음: {m.poly.question}")
        return None

    pinnacle_prob = game.favorite_prob

    # 조건 2: 폴리마켓 현재가 < 50센트
    if best_ask >= MAX_POLYMARKET_PRICE:
        log.debug(f"[scanner] 폴리가 높음 ({best_ask:.2f}): {m.poly.question}")
        return None

    # 조건 3: 갭 >= 15센트
    gap = pinnacle_prob - best_ask
    if gap < GAP_THRESHOLD:
        log.debug(
            f"[scanner] 갭 부족 ({gap:.2f}): {m.poly.question} "
            f"(pinnacle={pinnacle_prob:.2f}, poly={best_ask:.2f})"
        )
        return None

    # 조건 4: 유동성 >= 50 shares
    if shares < MIN_LIQUIDITY_SHARES:
        log.debug(f"[scanner] 유동성 부족 ({shares:.0f}): {m.poly.question}")
        return None

    bet_usdc = _calc_bet(gap)

    return ArbitrageOpportunity(
        matched          = m,
        poly_price       = best_ask,
        pinnacle_prob    = pinnacle_prob,
        gap_size         = gap,
        liquidity_shares = shares,
        bet_usdc         = bet_usdc,
    )


async def _fetch_orderbook(
    session: aiohttp.ClientSession,
    token_id: str,
) -> dict | None:
    """CLOB REST API로 오더북 조회."""
    try:
        async with session.get(
            f"{CLOB_HOST}/book",
            params={"token_id": token_id},
        ) as resp:
            resp.raise_for_status()
            return await resp.json()
    except Exception as e:
        log.warning(f"[scanner] 오더북 조회 실패 {token_id[-8:]}: {e}")
        return None


def _best_ask_and_shares(book: dict) -> tuple[float | None, float]:
    """오더북에서 최저 ask 가격과 근방 유동성 추출.

    CLOB 오더북은 asks가 내림차순(비쌈→쌈) 정렬.
    asks[-1]이 최저 ask(매수자에게 유리한 가격).
    유동성은 최저 ask 근방 3개 호가 합산.
    """
    asks = book.get("asks", [])
    if not asks:
        return None, 0.0
    best  = asks[-1]
    price = best.get("price")
    if price is None:
        return None, 0.0
    shares = sum(float(a.get("size", 0)) for a in asks[-3:])
    return float(price), shares


def _calc_bet(gap: float) -> float:
    """갭 크기에 따른 베팅 금액 결정."""
    for g_min, g_max, amount in BET_SIZE_TIERS:
        if g_min <= gap < g_max:
            return float(amount)
    return float(MAX_BET_USDC)
