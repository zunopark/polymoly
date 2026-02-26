"""
core/odds_fetcher.py - Pinnacle NBA 배당 수집

Odds API에서 Pinnacle 배당을 가져와 정배(1.5 이하) 경기만 반환.
크레딧 소비: 경기 수 × 1 (Pinnacle 단일 북메이커)

크레딧 제어:
  - 매 호출 후 잔여 크레딧을 data/credits.json에 저장
  - 잔여 < CREDITS_MIN_RESERVE → InsufficientCreditsError 발생 (호출 차단)
  - 잔여 < CREDITS_WARNING_THRESHOLD → 경고 로그 (main.py에서 Telegram 알림)
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

from config import (
    ODDS_API_BASE, ODDS_BOOKMAKERS, ODDS_SPORT, MAX_PINNACLE_ODDS,
    CREDITS_MIN_RESERVE, CREDITS_WARNING_THRESHOLD, CREDITS_STATE_PATH,
    DAILY_MAX_API_CALLS,
)

load_dotenv()
log = logging.getLogger(__name__)


# ── 크레딧 예외 ──────────────────────────────────────────────

class InsufficientCreditsError(Exception):
    """잔여 크레딧 부족 — Odds API 호출 차단."""
    def __init__(self, remaining: int):
        self.remaining = remaining
        super().__init__(
            f"[odds_fetcher] 잔여 크레딧 {remaining} < 최솟값 {CREDITS_MIN_RESERVE} — 호출 차단"
        )


class DailyLimitReachedError(Exception):
    """일일 Odds API 호출 한도 초과 — 자정까지 대기."""
    def __init__(self, count: int, limit: int):
        self.count = count
        self.limit = limit
        super().__init__(
            f"[odds_fetcher] 일일 호출 한도 도달: {count}/{limit} — 자정 이후 재개"
        )


# ── 크레딧 상태 파일 I/O ─────────────────────────────────────

def _load_state() -> dict:
    """credits.json 전체 상태 로드. 파일 없으면 빈 dict."""
    try:
        return json.loads(Path(CREDITS_STATE_PATH).read_text())
    except Exception:
        return {}


def _load_credits() -> int | None:
    """마지막으로 저장된 잔여 크레딧 로드. 파일 없으면 None."""
    state = _load_state()
    try:
        return int(state["remaining"])
    except (KeyError, TypeError, ValueError):
        return None


def _save_credits(remaining: int, used: int, daily_date: str, daily_calls: int) -> None:
    """잔여/사용 크레딧 + 일일 호출 횟수를 JSON 파일에 저장."""
    path = Path(CREDITS_STATE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "remaining":   remaining,
        "used":        used,
        "daily_date":  daily_date,
        "daily_calls": daily_calls,
        "updated_at":  datetime.now(timezone.utc).isoformat(),
    }, indent=2))


def load_credits() -> int | None:
    """마지막으로 저장된 잔여 크레딧 반환 (외부 크레딧 상태 확인용)."""
    return _load_credits()


@dataclass
class PinnacleGame:
    """단일 NBA 경기 + Pinnacle h2h 배당."""
    game_id:       str
    home_team:     str       # Odds API 전체 팀명 (예: "Miami Heat")
    away_team:     str
    commence_time: datetime  # UTC
    home_odds:     float     # Pinnacle 소수 배당
    away_odds:     float

    @property
    def favorite_is_home(self) -> bool:
        """홈팀이 정배(낮은 배당)이면 True."""
        return self.home_odds <= self.away_odds

    @property
    def favorite_team(self) -> str:
        return self.home_team if self.favorite_is_home else self.away_team

    @property
    def favorite_odds(self) -> float:
        return min(self.home_odds, self.away_odds)

    @property
    def favorite_prob(self) -> float:
        """임플라이드 확률 (소수). 예: 1.4배당 → 0.714"""
        return round(1 / self.favorite_odds, 4)

    def hours_until_start(self) -> float:
        return (self.commence_time - datetime.now(timezone.utc)).total_seconds() / 3600

    def __str__(self) -> str:
        return (
            f"[NBA] {self.home_team} vs {self.away_team} | "
            f"정배: {self.favorite_team} "
            f"({self.favorite_odds:.2f}배 / {self.favorite_prob:.1%}) | "
            f"시작: {self.hours_until_start():.1f}h 후"
        )


async def fetch_nba_games(session: aiohttp.ClientSession) -> list[PinnacleGame]:
    """Pinnacle NBA 경기 배당 수집.

    Returns:
        정배(MAX_PINNACLE_ODDS 이하) 팀이 있는 경기 목록.

    Raises:
        InsufficientCreditsError: 잔여 크레딧이 CREDITS_MIN_RESERVE 미만일 때.
    """
    api_key = os.getenv("ODDS_API_KEY")
    if not api_key:
        raise ValueError("[odds_fetcher] ODDS_API_KEY 미설정")

    # 사전 크레딧 체크 (저장된 이전 값 기준)
    state  = _load_state()
    cached = state.get("remaining")
    if cached is not None and int(cached) < CREDITS_MIN_RESERVE:
        raise InsufficientCreditsError(int(cached))

    # 일일 호출 횟수 체크
    today      = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_calls  = state.get("daily_calls", 0) if state.get("daily_date") == today else 0
    if day_calls >= DAILY_MAX_API_CALLS:
        raise DailyLimitReachedError(day_calls, DAILY_MAX_API_CALLS)

    url = f"{ODDS_API_BASE}/sports/{ODDS_SPORT}/odds"
    params = {
        "apiKey":     api_key,
        "bookmakers": ODDS_BOOKMAKERS,
        "markets":    "h2h",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }

    async with session.get(url, params=params) as resp:
        remaining_str = resp.headers.get("x-requests-remaining", "")
        used_str      = resp.headers.get("x-requests-used", "")
        resp.raise_for_status()
        raw_games: list[dict] = await resp.json()

    # 크레딧 파싱 + 저장 (일일 호출 횟수 +1)
    try:
        remaining = int(remaining_str)
        used      = int(used_str)
        _save_credits(remaining, used, today, day_calls + 1)
        log.info(
            f"[odds_fetcher] 크레딧: 사용={used:,}, 남은={remaining:,} "
            f"| 오늘 호출: {day_calls + 1}/{DAILY_MAX_API_CALLS}"
        )

        if remaining < CREDITS_MIN_RESERVE:
            raise InsufficientCreditsError(remaining)
        if remaining < CREDITS_WARNING_THRESHOLD:
            log.warning(
                f"[odds_fetcher] ⚠️ 크레딧 경고: 잔여 {remaining:,} "
                f"(경고 임계값 {CREDITS_WARNING_THRESHOLD:,})"
            )
    except InsufficientCreditsError:
        raise
    except (ValueError, TypeError):
        log.debug(f"[odds_fetcher] 크레딧 헤더 파싱 실패: remaining='{remaining_str}' used='{used_str}'")

    games = _parse(raw_games)
    log.info(f"[odds_fetcher] NBA {len(raw_games)}경기 → 정배 {len(games)}경기")
    return games


def _parse(raw_games: list[dict]) -> list[PinnacleGame]:
    """Odds API 응답 파싱 → 정배 있는 PinnacleGame 리스트."""
    result = []

    for raw in raw_games:
        try:
            commence_time = datetime.fromisoformat(
                raw["commence_time"].replace("Z", "+00:00")
            )
        except (KeyError, ValueError):
            log.warning(f"[odds_fetcher] 시간 파싱 실패: {raw.get('commence_time')}")
            continue

        pinnacle = _find_pinnacle(raw.get("bookmakers", []))
        if pinnacle is None:
            continue

        home_team = raw.get("home_team", "")
        away_team = raw.get("away_team", "")
        home_odds, away_odds = _extract_h2h(pinnacle, home_team, away_team)

        if home_odds is None or away_odds is None:
            log.debug(f"[odds_fetcher] 배당 없음: {home_team} vs {away_team}")
            continue

        # 두 팀 중 하나라도 MAX_PINNACLE_ODDS 이하여야 함
        if min(home_odds, away_odds) > MAX_PINNACLE_ODDS:
            continue

        game = PinnacleGame(
            game_id=raw.get("id", ""),
            home_team=home_team,
            away_team=away_team,
            commence_time=commence_time,
            home_odds=home_odds,
            away_odds=away_odds,
        )
        result.append(game)
        log.debug(str(game))

    return result


def _find_pinnacle(bookmakers: list[dict]) -> dict | None:
    for bm in bookmakers:
        if bm.get("key") == "pinnacle":
            return bm
    return None


def _extract_h2h(
    pinnacle: dict,
    home_team: str,
    away_team: str,
) -> tuple[float | None, float | None]:
    """h2h 마켓에서 홈/원정 배당 추출."""
    for market in pinnacle.get("markets", []):
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
