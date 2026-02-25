"""
core/scanner.py - 배당 역전 감지 엔진

전략 플로우 (CLAUDE.md §핵심 조건):
  조건 1: Pinnacle 배당 1.5 이하         → odds_fetcher.py에서 사전 필터링
  조건 2: 폴리마켓 현재가 50센트 미만     → best_ask < MAX_POLYMARKET_PRICE
  조건 3: 갭 15센트 이상                  → pinnacle_prob - poly_price >= GAP_THRESHOLD
  조건 4: 경기 시작 1시간 전까지          → hours_until_start >= BET_ENTRY_WINDOW_END_HRS
  조건 5: 폴리마켓 유동성 Shares 50 이상  → available_shares >= MIN_LIQUIDITY_SHARES

호출 위치:
  main.py의 폴링 루프에서 match_games() 결과로 scan() 호출.

폴리마켓 가격 조회:
  CLOB REST API GET /price?token_id=...&side=BUY
  또는 orderbook REST API GET /book?token_id=...
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiohttp

from config import (
    MAX_POLYMARKET_PRICE,
    GAP_THRESHOLD,
    MIN_LIQUIDITY_SHARES,
    BET_ENTRY_WINDOW_END_HRS,
    BET_ENTRY_WINDOW_START_HRS,
    CLOB_HOST,
)
from core.matcher import MatchedGame

log = logging.getLogger(__name__)


# ── 데이터 구조 ─────────────────────────────────────────────

@dataclass
class ArbitrageOpportunity:
    """감지된 배당 역전 기회."""
    sport_id: str             # 종목 ID (예: "nba", "nhl", "epl")
    game_id: str              # Odds API 경기 ID
    event_title: str          # 폴리마켓 event_title
    question: str             # 폴리마켓 마켓 질문
    token_id: str             # 매수 대상 YES token_id
    favorite_team: str        # 정배 팀 이름
    pinnacle_odds: float      # Pinnacle 배당
    pinnacle_prob: float      # Pinnacle 임플라이드 확률 (예: 0.714)
    poly_price: float         # 폴리마켓 현재 ask 가격 (예: 0.45)
    gap_size: float           # 갭 크기 = pinnacle_prob - poly_price
    liquidity_shares: float   # 가용 유동성 (shares)
    commence_time: datetime   # 경기 시작 시간
    neg_risk: bool
    tick_size: str
    handicap_point: float | None = None  # EPL spreads 전용 핸디캡 라인
    detected_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def hours_until_start(self) -> float:
        now = datetime.now(timezone.utc)
        return (self.commence_time - now).total_seconds() / 3600

    def __str__(self) -> str:
        hrs   = self.hours_until_start
        h_str = (f" 핸디({self.handicap_point:+.1f})" if self.handicap_point is not None else "")
        return (
            f"[ARBIT/{self.sport_id.upper()}] {self.event_title}\n"
            f"  마켓: {self.question}\n"
            f"  정배: {self.favorite_team}{h_str} "
            f"(Pinnacle {self.pinnacle_odds:.2f}배 → {self.pinnacle_prob:.1%})\n"
            f"  폴리마켓 ask: {self.poly_price:.2f}  "
            f"갭: {self.gap_size:.2f}  유동성: {self.liquidity_shares:.0f} shares\n"
            f"  경기 시작까지: {hrs:.1f}시간"
        )


# ── CLOB REST API 호출 ──────────────────────────────────────

async def fetch_orderbook(
    session: aiohttp.ClientSession,
    token_id: str,
) -> dict | None:
    """CLOB REST API로 특정 토큰의 오더북 조회.

    Returns:
        오더북 dict. 실패 시 None.
    """
    url = f"{CLOB_HOST}/book"
    params = {"token_id": token_id}

    try:
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json()
    except aiohttp.ClientError as e:
        log.warning(f"[scanner] 오더북 조회 실패 {token_id[-8:]}: {e}")
        return None


def _extract_best_ask_and_liquidity(
    orderbook: dict,
) -> tuple[float | None, float]:
    """오더북에서 최저 ask 가격과 해당 레벨의 available_shares 추출.

    Returns:
        (best_ask, available_shares)
        best_ask: 최저 ask 가격. 없으면 None.
        available_shares: 해당 ask 레벨의 수량. 없으면 0.0.
    """
    asks = orderbook.get("asks", [])
    if not asks:
        return None, 0.0

    # asks는 낮은 가격순 정렬되어 있어야 함
    best = asks[0]
    price = best.get("price")
    size  = best.get("size", 0)

    if price is None:
        return None, 0.0

    return float(price), float(size)


# ── 핵심 스캔 함수 ──────────────────────────────────────────

async def scan(
    session: aiohttp.ClientSession,
    matched_games: list[MatchedGame],
) -> list[ArbitrageOpportunity]:
    """매핑된 경기 목록에서 배당 역전 기회 감지.

    5가지 조건 모두 충족하는 경기만 ArbitrageOpportunity로 반환.

    Args:
        session: aiohttp.ClientSession
        matched_games: matcher.match_games() 반환값

    Returns:
        조건 충족 기회 목록. 없으면 빈 리스트.
    """
    opportunities: list[ArbitrageOpportunity] = []

    for matched in matched_games:
        opp = await _check_one(session, matched)
        if opp is not None:
            opportunities.append(opp)
            log.info(str(opp))

    log.info(
        f"[scanner] {len(matched_games)}경기 스캔 → "
        f"기회 {len(opportunities)}개 발견"
    )
    return opportunities


async def _check_one(
    session: aiohttp.ClientSession,
    matched: MatchedGame,
) -> ArbitrageOpportunity | None:
    """단일 매핑 경기에 대해 5가지 조건 검사.

    조건 불충족 시 None 반환.
    """
    game   = matched.pinnacle
    market = matched.poly_market

    # ── 조건 4: 경기 시작 시간 창 확인 ───────────────────────
    hrs_until = game.hours_until_start()
    if hrs_until < BET_ENTRY_WINDOW_END_HRS:
        log.debug(
            f"[scanner] 시간창 마감 ({hrs_until:.1f}h < {BET_ENTRY_WINDOW_END_HRS}h): "
            f"{game.home_team} vs {game.away_team}"
        )
        return None
    if hrs_until > BET_ENTRY_WINDOW_START_HRS:
        log.debug(
            f"[scanner] 모니터링 시작 전 ({hrs_until:.1f}h > {BET_ENTRY_WINDOW_START_HRS}h): "
            f"{game.home_team} vs {game.away_team}"
        )
        return None

    # ── 정배 팀 확인 (조건 1은 odds_fetcher에서 이미 필터링) ──
    favorite = game.favorite
    if favorite is None:
        return None

    # Yes 토큰 확인 (정배 팀이 이기면 Yes가 1달러)
    yes_token = market.yes_token
    if yes_token is None:
        log.warning(f"[scanner] Yes 토큰 없음: {market.question}")
        return None

    # ── 폴리마켓 오더북 조회 ─────────────────────────────────
    orderbook = await fetch_orderbook(session, yes_token.token_id)
    if orderbook is None:
        return None

    best_ask, liquidity_shares = _extract_best_ask_and_liquidity(orderbook)

    if best_ask is None:
        log.debug(f"[scanner] ask 없음: {market.question}")
        return None

    # ── 조건 2: 폴리마켓 현재가 50센트 미만 ─────────────────
    if best_ask >= MAX_POLYMARKET_PRICE:
        log.debug(
            f"[scanner] 폴리마켓가 너무 높음 ({best_ask:.2f} >= {MAX_POLYMARKET_PRICE}): "
            f"{market.question}"
        )
        return None

    # ── 조건 3: 갭 15센트 이상 ───────────────────────────────
    gap = favorite.implied_prob - best_ask
    if gap < GAP_THRESHOLD:
        log.debug(
            f"[scanner] 갭 부족 ({gap:.2f} < {GAP_THRESHOLD}): "
            f"{market.question} "
            f"(pinnacle={favorite.implied_prob:.2f}, poly={best_ask:.2f})"
        )
        return None

    # ── 조건 5: 폴리마켓 유동성 Shares 50 이상 ───────────────
    if liquidity_shares < MIN_LIQUIDITY_SHARES:
        log.debug(
            f"[scanner] 유동성 부족 ({liquidity_shares:.0f} < {MIN_LIQUIDITY_SHARES}): "
            f"{market.question}"
        )
        return None

    # ── 5가지 조건 모두 충족 → 기회 생성 ─────────────────────
    return ArbitrageOpportunity(
        sport_id=game.sport_id,
        game_id=game.game_id,
        event_title=market.event_title,
        question=market.question,
        token_id=yes_token.token_id,
        favorite_team=favorite.name,
        pinnacle_odds=favorite.odds,
        pinnacle_prob=favorite.implied_prob,
        poly_price=best_ask,
        gap_size=gap,
        liquidity_shares=liquidity_shares,
        commence_time=game.commence_time,
        neg_risk=market.neg_risk,
        tick_size=market.tick_size,
        handicap_point=favorite.handicap_point,
    )
