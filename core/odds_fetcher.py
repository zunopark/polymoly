"""
core/odds_fetcher.py - Odds API 호출, Pinnacle 배당 수집 (다종목)

지원 종목: config.ACTIVE_SPORTS 기준 (NBA, NHL, EPL)
E스포츠: Odds API sports 목록에 esports 키 없음 → 지원 불가

마켓별 처리:
  h2h (NBA, NHL): outcomes 2개, point 없음
  spreads (EPL):  outcomes 2개 + point(핸디캡 라인)
                  0.5 단위 라인만 허용 (이진 결과 보장)
                  0.0 (Draw No Bet), 0.25/0.75 쿼터핸디 제외

크레딧 소비:
  docs: bookmakers=pinnacle 직접 지정 시 1크레딧/종목 고정
  3종목 동시 조회: 3크레딧/폴링 사이클
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiohttp
from dotenv import load_dotenv

from config import ODDS_API_BASE, ODDS_BOOKMAKERS, SPORTS_CONFIG, ACTIVE_SPORTS

load_dotenv()
log = logging.getLogger(__name__)


# ── 데이터 구조 ─────────────────────────────────────────────

@dataclass
class PinnacleTeamOdds:
    """단일 팀의 Pinnacle 배당 정보."""
    name: str            # 팀 전체 이름 (예: "Los Angeles Lakers")
    odds: float          # Pinnacle 배당 (예: 1.4)
    implied_prob: float  # 임플라이드 확률 (예: 0.714) = 1 / odds
    handicap_point: float | None = None  # spreads 전용: 핸디캡 라인 (예: -0.5)


@dataclass
class PinnacleGame:
    """단일 경기 + Pinnacle 배당."""
    sport_id: str            # config SPORTS_CONFIG 키 (예: "nba", "nhl", "epl")
    game_id: str             # Odds API 경기 고유 ID
    commence_time: datetime  # 경기 시작 시간 (UTC)
    home_team: str
    away_team: str
    home_odds: PinnacleTeamOdds
    away_odds: PinnacleTeamOdds
    max_odds: float = field(default=1.5)  # 종목별 정배 기준 (SPORTS_CONFIG에서 주입)

    @property
    def favorite(self) -> PinnacleTeamOdds | None:
        """max_odds 이하인 정배 팀 반환. 없으면 None."""
        if self.home_odds.odds <= self.max_odds:
            return self.home_odds
        if self.away_odds.odds <= self.max_odds:
            return self.away_odds
        return None

    @property
    def underdog(self) -> PinnacleTeamOdds | None:
        fav = self.favorite
        if fav is None:
            return None
        return self.away_odds if fav is self.home_odds else self.home_odds

    def hours_until_start(self) -> float:
        now = datetime.now(timezone.utc)
        return (self.commence_time - now).total_seconds() / 3600

    def __str__(self) -> str:
        fav = self.favorite
        fav_str = (
            f"{fav.name} ({fav.odds:.2f}배"
            + (f", 핸디 {fav.handicap_point:+.1f}" if fav.handicap_point is not None else "")
            + f", {fav.implied_prob:.1%})"
            if fav else "없음"
        )
        hrs = self.hours_until_start()
        sport_cfg = SPORTS_CONFIG.get(self.sport_id, {})
        return (
            f"[{sport_cfg.get('label', self.sport_id)}] "
            f"{self.home_team} vs {self.away_team} "
            f"| 시작: {hrs:.1f}h 후 | 정배: {fav_str}"
        )


# ── Odds API 호출 ───────────────────────────────────────────

async def fetch_all_sports(
    session: aiohttp.ClientSession,
) -> list[PinnacleGame]:
    """ACTIVE_SPORTS의 모든 종목 배당을 수집. 총 N크레딧 (종목 수만큼).

    Returns:
        전체 종목의 PinnacleGame 리스트 (정배 있는 경기만).
    """
    api_key = os.getenv("ODDS_API_KEY")
    if not api_key:
        raise ValueError("[odds_fetcher] ODDS_API_KEY 미설정")

    all_games: list[PinnacleGame] = []

    for sport_id in ACTIVE_SPORTS:
        cfg = SPORTS_CONFIG.get(sport_id)
        if cfg is None:
            log.warning(f"[odds_fetcher] SPORTS_CONFIG에 없는 종목: {sport_id}")
            continue
        games = await _fetch_sport(session, api_key, sport_id, cfg)
        all_games.extend(games)

    log.info(f"[odds_fetcher] 전체 {len(all_games)}경기 수집 (정배 기준 충족)")
    return all_games


async def _fetch_sport(
    session: aiohttp.ClientSession,
    api_key: str,
    sport_id: str,
    cfg: dict,
) -> list[PinnacleGame]:
    """단일 종목 배당 조회 (1크레딧)."""
    sport_key = cfg["sport_key"]
    markets   = cfg["markets"]
    label     = cfg["label"]
    max_odds  = cfg["max_pinnacle_odds"]

    url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"
    params = {
        "apiKey":     api_key,
        "bookmakers": ODDS_BOOKMAKERS,
        "markets":    markets,
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }

    log.info(f"[odds_fetcher] {label} 조회 중... (markets={markets})")
    async with session.get(url, params=params) as resp:
        remaining = resp.headers.get("x-requests-remaining", "?")
        used      = resp.headers.get("x-requests-used", "?")
        log.info(f"[odds_fetcher] {label} 크레딧 사용={used}, 남은={remaining}")
        resp.raise_for_status()
        raw_games: list[dict] = await resp.json()

    is_handicap = cfg.get("is_handicap", False)
    games = _parse_games(raw_games, sport_id, max_odds, is_handicap)
    log.info(
        f"[odds_fetcher] {label}: 전체 {len(raw_games)}경기 중 "
        f"정배 충족 {len(games)}경기"
    )
    return games


# ── 파싱 ────────────────────────────────────────────────────

def _parse_games(
    raw_games: list[dict],
    sport_id: str,
    max_odds: float,
    is_handicap: bool,
) -> list[PinnacleGame]:
    """Odds API 응답 파싱 → PinnacleGame 리스트 (정배 존재 경기만)."""
    result: list[PinnacleGame] = []

    for raw in raw_games:
        game_id      = raw.get("id", "")
        home_team    = raw.get("home_team", "")
        away_team    = raw.get("away_team", "")
        commence_raw = raw.get("commence_time", "")

        try:
            commence_time = datetime.fromisoformat(
                commence_raw.replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            log.warning(f"[odds_fetcher] 시간 파싱 실패: {commence_raw}")
            continue

        pinnacle_data = _find_pinnacle(raw.get("bookmakers", []))
        if pinnacle_data is None:
            log.debug(f"[odds_fetcher] Pinnacle 없음: {home_team} vs {away_team}")
            continue

        if is_handicap:
            home_odds_val, away_odds_val, home_point, away_point = \
                _extract_spreads_odds(pinnacle_data, home_team, away_team)
        else:
            home_odds_val, away_odds_val = \
                _extract_h2h_odds(pinnacle_data, home_team, away_team)
            home_point = away_point = None

        if home_odds_val is None or away_odds_val is None:
            log.debug(f"[odds_fetcher] 배당 파싱 실패: {home_team} vs {away_team}")
            continue

        home_odds = PinnacleTeamOdds(
            name=home_team,
            odds=home_odds_val,
            implied_prob=round(1 / home_odds_val, 4),
            handicap_point=home_point,
        )
        away_odds = PinnacleTeamOdds(
            name=away_team,
            odds=away_odds_val,
            implied_prob=round(1 / away_odds_val, 4),
            handicap_point=away_point,
        )

        game = PinnacleGame(
            sport_id=sport_id,
            game_id=game_id,
            commence_time=commence_time,
            home_team=home_team,
            away_team=away_team,
            home_odds=home_odds,
            away_odds=away_odds,
            max_odds=max_odds,
        )

        if game.favorite is not None:
            result.append(game)
            log.debug(str(game))

    return result


def _find_pinnacle(bookmakers: list[dict]) -> dict | None:
    for bm in bookmakers:
        if bm.get("key") == "pinnacle":
            return bm
    return None


def _extract_h2h_odds(
    pinnacle_data: dict,
    home_team: str,
    away_team: str,
) -> tuple[float | None, float | None]:
    """h2h 마켓에서 홈/원정 배당 추출. (NBA, NHL)"""
    for market in pinnacle_data.get("markets", []):
        if market.get("key") != "h2h":
            continue
        home_price = away_price = None
        for outcome in market.get("outcomes", []):
            name  = outcome.get("name", "")
            price = outcome.get("price")
            if price is None:
                continue
            if name == home_team:
                home_price = float(price)
            elif name == away_team:
                away_price = float(price)
        return home_price, away_price
    return None, None


def _extract_spreads_odds(
    pinnacle_data: dict,
    home_team: str,
    away_team: str,
) -> tuple[float | None, float | None, float | None, float | None]:
    """spreads 마켓에서 홈/원정 배당 + 핸디캡 라인 추출. (EPL)

    0.5 단위 라인만 허용 (이진 결과 보장):
      허용: ±0.5, ±1.0, ±1.5, ±2.0 ...
      제외: 0.0 (Draw No Bet), ±0.25/±0.75 (쿼터핸디, 부분 환불 가능)

    Returns:
      (home_price, away_price, home_point, away_point)
      조건 미충족 시 (None, None, None, None)
    """
    for market in pinnacle_data.get("markets", []):
        if market.get("key") != "spreads":
            continue

        home_price = away_price = None
        home_point = away_point = None

        for outcome in market.get("outcomes", []):
            name  = outcome.get("name", "")
            price = outcome.get("price")
            point = outcome.get("point")
            if price is None or point is None:
                continue
            if name == home_team:
                home_price = float(price)
                home_point = float(point)
            elif name == away_team:
                away_price = float(price)
                away_point = float(point)

        if home_price is None or away_price is None:
            return None, None, None, None

        # 0.5 단위 라인 필터: point % 0.5 == 0 이고 0이 아닌 경우만
        if home_point is not None and not _is_clean_handicap(home_point):
            log.debug(
                f"[odds_fetcher] 쿼터핸디 제외 ({home_point:+.2f}): "
                f"{home_team} vs {away_team}"
            )
            return None, None, None, None

        return home_price, away_price, home_point, away_point

    return None, None, None, None


def _is_clean_handicap(point: float) -> bool:
    """0.5 단위 정수 핸디캡인지 확인 (이진 결과 보장).

    허용: ±0.5, ±1.0, ±1.5, ±2.0 (abs % 0.5 == 0 이고 0이 아님)
    제외: 0.0 (Draw No Bet), ±0.25, ±0.75, ±0.8, ±1.2 (쿼터핸디)
    """
    abs_point = abs(point)
    if abs_point == 0.0:
        return False
    remainder = round(abs_point % 0.5, 6)
    return remainder < 0.01
