"""
check_odds_api.py - Odds API Response 구조 확인 스크립트

목적:
  실제 API 응답을 확인해서 team_mapping.json 및 매핑 로직을 보완.
  크레딧을 최소화하여 사용.

사용법:
  python check_odds_api.py sports          # 0크레딧 - 전체 종목 키 목록
  python check_odds_api.py odds nba        # 1크레딧 - NBA h2h 배당
  python check_odds_api.py odds nhl        # 1크레딧 - NHL h2h 배당
  python check_odds_api.py odds esports    # 1크레딧 - E스포츠 종목 목록 확인
  python check_odds_api.py odds soccer     # 1크레딧 - EPL asian_handicap 배당
  python check_odds_api.py scores nba      # 1크레딧 - NBA 최근 경기 결과
"""

import asyncio
import json
import os
import ssl
import sys
from datetime import datetime, timezone

import aiohttp
from dotenv import load_dotenv

load_dotenv()

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4"

# ── 종목 설정 ────────────────────────────────────────────────
SPORT_CONFIGS = {
    "nba": {
        "sport_key": "basketball_nba",
        "markets": "h2h",
        "label": "NBA",
    },
    "nhl": {
        "sport_key": "icehockey_nhl",
        "markets": "h2h",
        "label": "NHL",
    },
    "esports": {
        # E스포츠는 /sports로 키 목록 먼저 확인 필요
        # 여기서는 lol을 예시로 사용 (실제 키는 /sports 응답 확인 후 수정)
        "sport_key": "esports_lol",
        "markets": "h2h",
        "label": "E스포츠 (LoL - 키 확인 필요)",
    },
    "soccer": {
        # asian_handicap은 Odds API v4 유효 market 아님
        # spreads = 핸디캡/스프레드 마켓 (Pinnacle asian handicap 포함)
        "sport_key": "soccer_epl",
        "markets": "spreads",
        "label": "축구 EPL (Spreads/Handicap)",
    },
    "soccer_h2h": {
        # 축구 1X2 (승/무/패) — 구조 파악용, 실제 배팅에는 미사용
        "sport_key": "soccer_epl",
        "markets": "h2h",
        "label": "축구 EPL (1X2 h2h — 구조 확인용)",
    },
}


# ── 유틸 ────────────────────────────────────────────────────

def print_header(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_credits(headers) -> None:
    remaining = headers.get("x-requests-remaining", "?")
    used      = headers.get("x-requests-used", "?")
    last      = headers.get("x-requests-last", "?")
    print(f"\n[크레딧]  잔여: {remaining}  /  사용됨: {used}  /  이번 호출: {last}")


def to_implied_prob(decimal_odds: float) -> float:
    return round(1 / decimal_odds, 4)


# ── 1. GET /sports — 0크레딧 ────────────────────────────────

async def cmd_sports(session: aiohttp.ClientSession) -> None:
    """전체 종목 키 목록 조회 (0크레딧)."""
    print_header("GET /sports — 전체 종목 목록 (0크레딧)")

    url = f"{BASE_URL}/sports"
    params = {"apiKey": ODDS_API_KEY}

    async with session.get(url, params=params) as resp:
        print_credits(resp.headers)
        resp.raise_for_status()
        sports: list[dict] = await resp.json()

    # 우리 봇 관련 종목 먼저 출력
    target_keywords = ["basketball_nba", "icehockey_nhl", "esports", "soccer_epl", "soccer_spain", "soccer_germany", "soccer_france", "soccer_italy", "baseball_mlb"]

    print(f"\n총 {len(sports)}개 종목")

    print("\n── 봇 관련 종목 ──")
    for s in sports:
        key = s.get("key", "")
        if any(kw in key for kw in target_keywords):
            active = "활성" if s.get("active") else "비활성"
            print(f"  {key:<40} | {s.get('title', ''):<25} | {active}")

    print("\n── 전체 종목 키 목록 ──")
    for s in sports:
        active = "O" if s.get("active") else "X"
        print(f"  [{active}] {s.get('key', ''):<40} {s.get('title', '')}")


# ── 2. GET /odds — 1크레딧 ──────────────────────────────────

async def cmd_odds(session: aiohttp.ClientSession, sport_alias: str) -> None:
    """특정 종목 배당 조회 (1크레딧)."""
    config = SPORT_CONFIGS.get(sport_alias)
    if config is None:
        print(f"알 수 없는 종목: {sport_alias}")
        print(f"사용 가능: {list(SPORT_CONFIGS.keys())}")
        return

    sport_key = config["sport_key"]
    markets   = config["markets"]
    label     = config["label"]

    print_header(f"GET /odds — {label} ({markets}) — 1크레딧")

    url = f"{BASE_URL}/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "bookmakers": "pinnacle",
        "markets": markets,
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }

    async with session.get(url, params=params) as resp:
        print_credits(resp.headers)
        if resp.status == 422:
            body = await resp.text()
            print(f"\n[422 오류] sport_key '{sport_key}' 가 잘못됐거나 비활성 상태일 수 있음")
            print(f"응답: {body}")
            return
        resp.raise_for_status()
        games: list[dict] = await resp.json()

    now = datetime.now(timezone.utc)
    print(f"\n총 {len(games)}경기 (Pinnacle 데이터 포함)")

    if not games:
        print("  → 현재 예정된 경기 없음 (시즌 외 또는 Pinnacle 미제공)")
        return

    print(f"\n원본 JSON (첫 번째 경기):")
    print(json.dumps(games[0], indent=2, ensure_ascii=False))

    print(f"\n── 경기 요약 ({len(games)}경기) ──")
    for game in games:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        ct   = game.get("commence_time", "")
        hrs  = _hours_until(ct, now)

        bms = game.get("bookmakers", [])
        pinnacle = next((b for b in bms if b.get("key") == "pinnacle"), None)

        if pinnacle is None:
            print(f"  {away} @ {home} | {hrs:+.1f}h | [Pinnacle 없음]")
            continue

        outcomes = _get_outcomes(pinnacle, markets)
        odds_str = _format_outcomes(outcomes, markets)

        print(f"  {away} @ {home} | {hrs:+.1f}h | {odds_str}")

    # 팀명 목록 (team_mapping.json 보완용)
    print(f"\n── 팀명 목록 (team_mapping.json 보완용) ──")
    team_names = set()
    for game in games:
        team_names.add(game.get("home_team", ""))
        team_names.add(game.get("away_team", ""))
    for name in sorted(team_names):
        if name:
            print(f"  \"{name}\"")

    # 1.5 이하 정배 후보 필터
    print(f"\n── Pinnacle 1.5 이하 정배 후보 ──")
    found = 0
    for game in games:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        ct   = game.get("commence_time", "")
        hrs  = _hours_until(ct, now)

        bms = game.get("bookmakers", [])
        pinnacle = next((b for b in bms if b.get("key") == "pinnacle"), None)
        if not pinnacle:
            continue

        outcomes = _get_outcomes(pinnacle, markets)
        for outcome in outcomes:
            price = outcome.get("price", 999)
            name  = outcome.get("name", "")
            point = outcome.get("point")  # 핸디캡용
            if price <= 1.5:
                prob = to_implied_prob(price)
                point_str = f" (핸디 {point:+.1f})" if point is not None else ""
                print(
                    f"  {name}{point_str}: {price:.2f}배 → {prob:.1%} "
                    f"| vs {away if name == home else home} | {hrs:+.1f}h"
                )
                found += 1

    if found == 0:
        print("  → 현재 1.5 이하 경기 없음")


# ── 3. GET /scores — 1크레딧 ────────────────────────────────

async def cmd_scores(session: aiohttp.ClientSession, sport_alias: str) -> None:
    """최근 경기 결과 조회 (1크레딧)."""
    config = SPORT_CONFIGS.get(sport_alias)
    if config is None:
        print(f"알 수 없는 종목: {sport_alias}")
        return

    sport_key = config["sport_key"]
    label     = config["label"]

    print_header(f"GET /scores — {label} 최근 결과 — 1크레딧")

    url = f"{BASE_URL}/sports/{sport_key}/scores"
    params = {
        "apiKey": ODDS_API_KEY,
        "daysFrom": 1,
        "dateFormat": "iso",
    }

    async with session.get(url, params=params) as resp:
        print_credits(resp.headers)
        resp.raise_for_status()
        scores: list[dict] = await resp.json()

    completed = [s for s in scores if s.get("completed")]
    ongoing   = [s for s in scores if not s.get("completed")]

    print(f"\n총 {len(scores)}경기 (완료: {len(completed)}, 진행중/예정: {len(ongoing)})")

    print(f"\n원본 JSON (첫 번째 완료 경기):")
    if completed:
        print(json.dumps(completed[0], indent=2, ensure_ascii=False))
    else:
        print("  완료된 경기 없음")

    print(f"\n── 완료된 경기 결과 ──")
    for game in completed:
        home   = game.get("home_team", "")
        away   = game.get("away_team", "")
        sc     = game.get("scores") or []
        sc_map = {s["name"]: s["score"] for s in sc}
        home_s = sc_map.get(home, "?")
        away_s = sc_map.get(away, "?")
        print(f"  {away} {away_s} - {home_s} {home} (홈)")


# ── 헬퍼 ────────────────────────────────────────────────────

def _hours_until(commence_time: str, now: datetime) -> float:
    try:
        ct = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        return (ct - now).total_seconds() / 3600
    except Exception:
        return 0.0


def _get_outcomes(pinnacle: dict, markets: str) -> list[dict]:
    for m in pinnacle.get("markets", []):
        if m.get("key") == markets:
            return m.get("outcomes", [])
    return []


def _format_outcomes(outcomes: list[dict], markets: str) -> str:
    parts = []
    for o in outcomes:
        name  = o.get("name", "")
        price = o.get("price", 0)
        point = o.get("point")
        if point is not None:
            parts.append(f"{name}({point:+.1f}): {price:.2f}")
        else:
            parts.append(f"{name}: {price:.2f}")
    return "  |  ".join(parts)


# ── 진입점 ──────────────────────────────────────────────────

async def main() -> None:
    if not ODDS_API_KEY:
        print("[오류] .env에 ODDS_API_KEY 가 설정되지 않았습니다.")
        sys.exit(1)

    args = sys.argv[1:]

    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0].lower()

    # 자체 서명 인증서 환경(사내 네트워크/VPN) 대응 — 테스트 스크립트 전용
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=connector) as session:
        if cmd == "sports":
            await cmd_sports(session)

        elif cmd == "odds":
            sport = args[1].lower() if len(args) > 1 else "nba"
            await cmd_odds(session, sport)

        elif cmd == "scores":
            sport = args[1].lower() if len(args) > 1 else "nba"
            await cmd_scores(session, sport)

        else:
            print(f"알 수 없는 명령: {cmd}")
            print("사용법: python check_odds_api.py [sports|odds|scores] [종목]")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
