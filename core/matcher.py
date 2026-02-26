"""
core/matcher.py - Gamma API 조회 + 경기 매핑 (Odds API ↔ 폴리마켓)

폴리마켓 NBA 마켓 형식:
  "Heat vs. 76ers"     → YES = Heat(홈팀) 승, NO = 76ers(원정팀) 승
  "Wizards vs. Hawks"  → YES = Wizards 승, NO = Hawks 승

매핑 로직:
  1. Gamma API tag_slug=nba 로 예정 경기 마켓 조회
  2. "TeamA vs. TeamB" 형식 (순수 승/패 마켓만) 필터
  3. team_mapping.json 으로 팀명 정규화 (예: "Miami Heat" → "Heat")
  4. 팀명 + 경기 시간(±3h) 으로 매칭

매수 토큰 결정:
  - 정배팀이 홈팀(YES측) → YES 토큰 매수
  - 정배팀이 원정팀(NO측) → NO 토큰 매수
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiohttp

from config import GAMMA_BASE, TEAM_MAPPING_PATH
from core.odds_fetcher import PinnacleGame

log = logging.getLogger(__name__)


# ── 데이터 구조 ─────────────────────────────────────────────

@dataclass
class PolymarketMarket:
    """폴리마켓 단일 NBA 승/패 마켓."""
    condition_id:    str
    question:        str       # 예: "Heat vs. 76ers"
    game_start_time: datetime
    home_short:      str       # 질문 앞팀 약칭 (예: "Heat")
    away_short:      str       # 질문 뒷팀 약칭 (예: "76ers")
    yes_token_id:    str       # YES = 홈팀(앞팀) 승리
    no_token_id:     str       # NO  = 원정팀(뒷팀) 승리


@dataclass
class MatchedGame:
    """매핑 완료된 경기: Pinnacle 정보 + 폴리마켓 마켓."""
    pinnacle: PinnacleGame
    poly:     PolymarketMarket

    @property
    def buy_yes(self) -> bool:
        """정배팀이 홈팀(YES측)이면 True."""
        return self.pinnacle.favorite_is_home

    @property
    def buy_token_id(self) -> str:
        return self.poly.yes_token_id if self.buy_yes else self.poly.no_token_id

    @property
    def buy_token_label(self) -> str:
        return "YES" if self.buy_yes else "NO"

    def __str__(self) -> str:
        return (
            f"[MATCH] {self.pinnacle.home_team} vs {self.pinnacle.away_team}\n"
            f"  폴리마켓: {self.poly.question}\n"
            f"  정배: {self.pinnacle.favorite_team} "
            f"({self.pinnacle.favorite_odds:.2f}배) | 매수: {self.buy_token_label}"
        )


# ── 팀명 정규화 ─────────────────────────────────────────────

def load_team_mapping() -> dict[str, str]:
    """team_mapping.json 로드. 없으면 빈 딕셔너리."""
    try:
        with open(TEAM_MAPPING_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except FileNotFoundError:
        log.warning(f"[matcher] {TEAM_MAPPING_PATH} 없음 — 팀명 정규화 스킵")
        return {}
    except json.JSONDecodeError as e:
        log.error(f"[matcher] team_mapping.json 파싱 오류: {e}")
        return {}


def normalize(full_name: str, mapping: dict[str, str]) -> str:
    """Odds API 전체 팀명 → 폴리마켓 약칭. 매핑 없으면 원본 반환."""
    return mapping.get(full_name, full_name)


# ── Gamma API 조회 ───────────────────────────────────────────

async def fetch_nba_poly_markets(
    session: aiohttp.ClientSession,
) -> list[PolymarketMarket]:
    """Gamma API에서 NBA 예정 경기 승/패 마켓 조회.

    조건:
      - tag_slug=nba, active=true, closed=false
      - acceptingOrders=true
      - 순수 팀 vs 팀 마켓만 (_is_matchup 필터)
      - game_start_time > now (아직 시작 전)
    """
    params = {
        "tag_slug": "nba",
        "active":   "true",
        "closed":   "false",
        "limit":    200,
    }

    async with session.get(f"{GAMMA_BASE}/events", params=params) as resp:
        resp.raise_for_status()
        events: list[dict] = await resp.json()

    now = datetime.now(timezone.utc)
    markets: list[PolymarketMarket] = []

    for event in events:
        for raw in (event.get("markets") or []):
            if not raw.get("acceptingOrders"):
                continue

            question = raw.get("question", "").strip()
            if not _is_matchup(question):
                continue

            gst = _parse_gst(raw)
            if gst is None or gst <= now:
                continue

            home_short, away_short = _split_teams(question)
            if not home_short or not away_short:
                continue

            yes_id, no_id = _extract_token_ids(raw)
            if not yes_id or not no_id:
                continue

            markets.append(PolymarketMarket(
                condition_id    = raw.get("conditionId", ""),
                question        = question,
                game_start_time = gst,
                home_short      = home_short,
                away_short      = away_short,
                yes_token_id    = yes_id,
                no_token_id     = no_id,
            ))

    log.info(f"[matcher] 폴리마켓 NBA 마켓 {len(markets)}개 조회")
    return markets


def _is_matchup(question: str) -> bool:
    """순수 팀 대 팀 승/패 마켓인지 판별.

    통과:  "Heat vs. 76ers"
    제외:  "Will..." / "O/U" / "Spread" / 콜론 포함 세부 마켓
           "X vs. Y: 1H Moneyline" 등 세부 마켓은 콜론(:)으로 식별
    """
    q = question.lower()
    if q.startswith("will "):
        return False
    if any(kw in q for kw in ("o/u", "spread", "over", "under", "total", "points")):
        return False
    if " vs" not in q:
        return False
    # "X vs. Y: 세부정보" 형식 제외 (1H Moneyline, O/U 등)
    # 순수 "X vs. Y" 는 콜론 없음
    if ":" in question:
        return False
    return True


def _split_teams(question: str) -> tuple[str, str]:
    """'Heat vs. 76ers' → ('Heat', '76ers')"""
    parts = re.split(r"\s+vs\.?\s+", question, flags=re.IGNORECASE)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", ""


def _parse_gst(raw: dict) -> datetime | None:
    """gameStartTime 문자열 → UTC datetime."""
    s = raw.get("gameStartTime")
    if not s:
        return None
    try:
        s = s.replace(" ", "T")
        if s.endswith("+00"):
            s = s[:-3] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except ValueError:
        return None


def _extract_token_ids(raw: dict) -> tuple[str, str]:
    """clobTokenIds에서 YES(index 0) / NO(index 1) token_id 추출."""
    raw_ids      = raw.get("clobTokenIds")
    raw_outcomes = raw.get("outcomes")
    if not raw_ids or not raw_outcomes:
        return "", ""

    ids = json.loads(raw_ids) if isinstance(raw_ids, str) else raw_ids
    if len(ids) < 2:
        return "", ""

    return str(ids[0]), str(ids[1])


# ── 핵심 매핑 함수 ───────────────────────────────────────────

def match_games(
    pinnacle_games: list[PinnacleGame],
    poly_markets:   list[PolymarketMarket],
    team_mapping:   dict[str, str],
) -> list[MatchedGame]:
    """Pinnacle 경기 목록 ↔ 폴리마켓 마켓 목록 매핑.

    매핑 조건:
      1. 홈/원정 팀 약칭이 폴리마켓 마켓 팀명에 모두 포함
      2. 경기 시작 시간 ±3시간 이내
    매핑 실패 시 스킵 (오매핑으로 인한 잘못된 베팅 방지).
    """
    results: list[MatchedGame] = []

    for game in pinnacle_games:
        home_s = normalize(game.home_team, team_mapping)
        away_s = normalize(game.away_team, team_mapping)

        market = _find_market(poly_markets, home_s, away_s, game.commence_time)
        if market is None:
            log.debug(
                f"[matcher] 매핑 실패: {game.home_team} vs {game.away_team} "
                f"(home_s={home_s}, away_s={away_s})"
            )
            continue

        matched = MatchedGame(pinnacle=game, poly=market)
        results.append(matched)
        log.info(str(matched))

    log.info(f"[matcher] {len(pinnacle_games)}경기 중 {len(results)}경기 매핑 성공")
    return results


def _find_market(
    markets:       list[PolymarketMarket],
    home_s:        str,
    away_s:        str,
    commence_time: datetime,
    tol_hrs:       float = 3.0,
) -> PolymarketMarket | None:
    """단일 Pinnacle 경기에 매칭되는 폴리마켓 마켓 반환."""
    tol  = timedelta(hours=tol_hrs)
    hits = []

    for m in markets:
        # 팀명 매칭: 홈/원정 약칭이 폴리마켓 마켓의 home_short/away_short에 포함
        market_text = f"{m.home_short} {m.away_short}".lower()
        if home_s.lower() not in market_text or away_s.lower() not in market_text:
            continue

        # 시간 매칭: ±3시간
        if abs(m.game_start_time - commence_time) > tol:
            continue

        hits.append(m)

    if len(hits) == 1:
        return hits[0]

    if len(hits) > 1:
        log.warning(
            f"[matcher] 복수 매칭 ({len(hits)}개) — 스킵: {home_s} vs {away_s}"
        )
    return None
