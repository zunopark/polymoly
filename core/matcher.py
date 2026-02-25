"""
core/matcher.py - 경기 매핑 로직 (Odds API ↔ 폴리마켓)

문제:
  Odds API:  "Los Angeles Lakers vs Boston Celtics"
  폴리마켓:  "Will the Lakers beat the Celtics?"

접근 방식:
  1. team_mapping.json으로 팀 전체명 → 약칭 정규화
  2. 폴리마켓 경기 제목에 양 팀 약칭이 모두 포함되는지 확인
  3. 경기 시작 시간 ±3시간 이내인지 확인 (오매핑 방지)
  4. 매핑 실패 시 해당 경기 스킵 (잘못된 베팅 방지)

다종목 지원:
  fetch_upcoming_poly_markets(session, sport_id) 로 종목별 태그 사용.
  SPORTS_CONFIG[sport_id]["gamma_tag"] → Gamma API tag_slug 파라미터.

폴리마켓 경기 조회:
  Gamma API /events?tag_slug={gamma_tag}&active=true&closed=false
  gameStartTime이 아직 시작 전인 마켓만 필터링

반환:
  MatchedGame 리스트 — Pinnacle 게임 + 폴리마켓 토큰 정보 매핑 완료
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiohttp

from config import GAMMA_BASE, TEAM_MAPPING_PATH, SPORTS_CONFIG
from core.odds_fetcher import PinnacleGame

log = logging.getLogger(__name__)


# ── 데이터 구조 ─────────────────────────────────────────────

@dataclass
class PolymarketToken:
    """폴리마켓 마켓의 단일 outcome 토큰."""
    token_id: str    # CLOB token_id
    outcome: str     # "Yes" | "No"


@dataclass
class PolymarketMarket:
    """폴리마켓 단일 마켓 정보."""
    condition_id: str
    question: str           # 예: "Will the Lakers beat the Celtics?"
    event_title: str        # 예: "Lakers vs Celtics"
    game_start_time: datetime | None
    tokens: list[PolymarketToken]   # [yes_token, no_token]
    neg_risk: bool
    tick_size: str

    @property
    def yes_token(self) -> PolymarketToken | None:
        """Yes 토큰 반환."""
        for t in self.tokens:
            if t.outcome.lower() == "yes":
                return t
        return None


@dataclass
class MatchedGame:
    """매핑 완료된 경기: Pinnacle 정보 + 폴리마켓 마켓."""
    pinnacle: PinnacleGame
    poly_market: PolymarketMarket

    def __str__(self) -> str:
        fav = self.pinnacle.favorite
        fav_str = f"{fav.name} ({fav.odds:.2f})" if fav else "?"
        return (
            f"[MATCH] {self.pinnacle.home_team} vs {self.pinnacle.away_team}\n"
            f"  폴리마켓: {self.poly_market.question}\n"
            f"  정배: {fav_str}"
        )


# ── 팀명 정규화 ─────────────────────────────────────────────

def load_team_mapping() -> dict[str, str]:
    """team_mapping.json 로드. 파일 없으면 빈 딕셔너리 반환."""
    try:
        with open(TEAM_MAPPING_PATH, encoding="utf-8") as f:
            data = json.load(f)
        # _comment 등 메타 키 제거
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except FileNotFoundError:
        log.warning(f"[matcher] {TEAM_MAPPING_PATH} 없음. 팀명 정규화 스킵.")
        return {}
    except json.JSONDecodeError as e:
        log.error(f"[matcher] team_mapping.json 파싱 오류: {e}")
        return {}


def normalize_team_name(full_name: str, mapping: dict[str, str]) -> str:
    """전체 팀명 → 폴리마켓 약칭 정규화.

    매핑에 없으면 전체 이름 그대로 반환.
    예: "Los Angeles Lakers" → "Lakers"
    """
    return mapping.get(full_name, full_name)


# ── 폴리마켓 경기 조회 ──────────────────────────────────────

async def fetch_upcoming_poly_markets(
    session: aiohttp.ClientSession,
    sport_id: str = "nba",
) -> list[PolymarketMarket]:
    """Gamma API로 특정 종목의 예정 경기(시작 전) 마켓 목록 조회.

    종목별 gamma_tag는 SPORTS_CONFIG에서 읽음.
    주의: NHL/EPL의 실제 Gamma tag_slug는 폴리마켓 확인 후 보완 필요.

    조건:
      - tag_slug={gamma_tag}
      - active=true, closed=false
      - acceptingOrders=true (주문 수락 중)
      - gameStartTime > now (아직 시작 안 한 경기)

    Returns:
        PolymarketMarket 리스트
    """
    cfg      = SPORTS_CONFIG.get(sport_id, {})
    tag_slug = cfg.get("gamma_tag", sport_id)

    params = {
        "tag_slug": tag_slug,
        "active": "true",
        "closed": "false",
        "limit": 100,
    }

    async with session.get(f"{GAMMA_BASE}/events", params=params) as resp:
        resp.raise_for_status()
        events: list[dict] = await resp.json()

    label = cfg.get("label", sport_id)
    now   = datetime.now(timezone.utc)
    markets: list[PolymarketMarket] = []

    for event in events:
        event_title = event.get("title", "")
        for raw_market in (event.get("markets") or []):
            if not raw_market.get("acceptingOrders"):
                continue
            gst = _parse_game_start_time(raw_market)
            # 아직 시작 전인 경기만
            if gst is None or gst <= now:
                continue

            # 승/패 이진 마켓만 (Question이 "Will X beat Y?" 패턴)
            question = raw_market.get("question", "")
            if not _is_win_loss_market(question):
                continue

            tokens = _extract_tokens(raw_market)
            if not tokens:
                continue

            market = PolymarketMarket(
                condition_id=raw_market.get("conditionId", ""),
                question=question,
                event_title=event_title,
                game_start_time=gst,
                tokens=tokens,
                neg_risk=bool(raw_market.get("negRisk", False)),
                tick_size=str(raw_market.get("minTickSize") or "0.01"),
            )
            markets.append(market)

    log.info(f"[matcher] 폴리마켓 {label} 예정 경기 마켓 {len(markets)}개 조회 완료")
    return markets


def _parse_game_start_time(market: dict) -> datetime | None:
    """gameStartTime 문자열 → UTC datetime. 없거나 파싱 실패 시 None."""
    raw = market.get("gameStartTime")
    if not raw:
        return None
    try:
        raw = raw.replace(" ", "T")
        if raw.endswith("+00"):
            raw = raw[:-3] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _is_win_loss_market(question: str) -> bool:
    """승/패 이진 마켓인지 판별.

    폴리마켓 NBA 승/패 마켓은 "Will X beat Y?" 또는 "Will the X win?" 패턴.
    토탈 포인트, 핸디캡 등 다른 마켓 제외.
    """
    q_lower = question.lower()
    # 포인트 토탈, 핸디캡, 시즌 전체 마켓 제외 키워드
    # "finals/playoffs/champion/cup/qualify" 추가: 챔피언십·플레이오프 시즌 마켓 제외
    exclude_keywords = [
        "total", "points", "over", "under", "score", "spread",
        "finals", "playoffs", "champion", "cup", "qualify",
    ]
    for kw in exclude_keywords:
        if kw in q_lower:
            return False
    # 승/패 판별 키워드
    win_keywords = ["beat", "win", "defeat"]
    for kw in win_keywords:
        if kw in q_lower:
            return True
    return False


def _extract_tokens(market: dict) -> list[PolymarketToken]:
    """마켓에서 (token_id, outcome) 쌍 추출."""
    import json as _json
    raw_ids = market.get("clobTokenIds")
    raw_outcomes = market.get("outcomes")
    if not raw_ids or not raw_outcomes:
        return []
    ids = _json.loads(raw_ids) if isinstance(raw_ids, str) else raw_ids
    outcomes = _json.loads(raw_outcomes) if isinstance(raw_outcomes, str) else raw_outcomes
    return [
        PolymarketToken(token_id=tid, outcome=out)
        for tid, out in zip(ids, outcomes)
        if isinstance(tid, str) and tid
    ]


# ── 핵심 매핑 함수 ──────────────────────────────────────────

def match_games(
    pinnacle_games: list[PinnacleGame],
    poly_markets: list[PolymarketMarket],
    team_mapping: dict[str, str],
) -> list[MatchedGame]:
    """Pinnacle 경기 목록과 폴리마켓 마켓 목록을 매핑.

    매핑 조건:
      1. 양 팀 약칭이 폴리마켓 질문 또는 event_title에 모두 포함
      2. 경기 시작 시간 ±3시간 이내 (오매핑 방지)

    매핑 실패 시 해당 경기 스킵 (오매핑으로 인한 잘못된 베팅 방지).
    """
    results: list[MatchedGame] = []

    for game in pinnacle_games:
        home_short = normalize_team_name(game.home_team, team_mapping)
        away_short = normalize_team_name(game.away_team, team_mapping)

        matched_market = _find_matching_market(
            poly_markets,
            home_short,
            away_short,
            game.commence_time,
        )

        if matched_market is None:
            log.debug(
                f"[matcher] 매핑 실패 스킵: {game.home_team} vs {game.away_team} "
                f"(home_short={home_short}, away_short={away_short})"
            )
            continue

        matched = MatchedGame(pinnacle=game, poly_market=matched_market)
        results.append(matched)
        log.info(str(matched))

    log.info(f"[matcher] {len(pinnacle_games)}경기 중 {len(results)}경기 매핑 성공")
    return results


def _find_matching_market(
    poly_markets: list[PolymarketMarket],
    home_short: str,
    away_short: str,
    commence_time: datetime,
    time_tolerance_hrs: float = 3.0,
) -> PolymarketMarket | None:
    """단일 Pinnacle 경기에 매칭되는 폴리마켓 마켓 반환.

    Args:
        poly_markets: 전체 폴리마켓 마켓 목록
        home_short: 홈 팀 약칭
        away_short: 원정 팀 약칭
        commence_time: Odds API 경기 시작 시간 (UTC)
        time_tolerance_hrs: 경기 시간 허용 오차 (시간)

    Returns:
        매칭 마켓. 없거나 복수 매칭 시 None.
    """
    tolerance = timedelta(hours=time_tolerance_hrs)
    candidates: list[PolymarketMarket] = []

    for market in poly_markets:
        # 팀명 매칭: question 또는 event_title에 양 팀 약칭 포함 여부
        search_text = f"{market.question} {market.event_title}".lower()
        if home_short.lower() not in search_text:
            continue
        if away_short.lower() not in search_text:
            continue

        # 시간 매칭
        if market.game_start_time is None:
            continue
        time_diff = abs(market.game_start_time - commence_time)
        if time_diff > tolerance:
            continue

        candidates.append(market)

    if len(candidates) == 1:
        return candidates[0]

    if len(candidates) > 1:
        log.warning(
            f"[matcher] 복수 매칭 ({len(candidates)}개) — 스킵: "
            f"{home_short} vs {away_short}"
        )
        return None

    return None
