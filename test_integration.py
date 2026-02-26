"""
test_integration.py - 통합 테스트 스크립트

크레딧 소비 없는 기본 모드 (default):
  - Gamma API 실시간 조회 (무료)
  - CLOB 오더북 실시간 조회 (무료)
  - Odds API 대신 Gamma 조회 결과 기반 mock 데이터 사용 → 매핑 100% 일치 보장

크레딧 소비 모드 (--live):
  - Odds API 실제 호출 (NBA 경기 수만큼 크레딧 소비)
  - 실제 Pinnacle 배당 + 실제 폴리마켓 가격으로 갭 감지

사용법:
  python test_integration.py          # 크레딧 0 소비 (권장)
  python test_integration.py --live   # Odds API 실제 호출
"""

import asyncio
import ssl
import sys
from datetime import datetime, timezone

import aiohttp
from dotenv import load_dotenv

load_dotenv()

# ── 출력 헬퍼 ────────────────────────────────────────────────

SEP = "=" * 65
SUB = "-" * 65


def header(title: str) -> None:
    print(f"\n{SEP}\n  {title}\n{SEP}")


def ok(msg: str)   -> None: print(f"  ✅ {msg}")
def warn(msg: str) -> None: print(f"  ⚠️  {msg}")
def info(msg: str) -> None: print(f"  ℹ️  {msg}")
def fail(msg: str) -> None: print(f"  ❌ {msg}")


# ── SSL 컨텍스트 (macOS VPN/방화벽 대응) ────────────────────

def _make_connector() -> aiohttp.TCPConnector:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    return aiohttp.TCPConnector(ssl=ctx)


# ── [1] Gamma API 테스트 ─────────────────────────────────────

async def test_gamma(session: aiohttp.ClientSession):
    from core.matcher import fetch_nba_poly_markets

    header("[1] Gamma API — 폴리마켓 NBA 마켓 조회 (무료)")

    try:
        markets = await fetch_nba_poly_markets(session)
    except Exception as e:
        fail(f"Gamma API 오류: {e}")
        return []

    if not markets:
        warn("조회된 마켓 없음 (NBA 경기가 없는 날일 수 있음)")
        return []

    ok(f"마켓 {len(markets)}개 조회 완료")
    print()
    print(f"  {'질문':<38} {'홈팀':<16} {'원정팀':<16} {'시작까지'}")
    print(f"  {SUB}")
    for m in markets[:12]:
        hrs = (m.game_start_time - datetime.now(timezone.utc)).total_seconds() / 3600
        print(
            f"  {m.question:<38} "
            f"{m.home_short:<16} {m.away_short:<16} "
            f"+{hrs:.1f}h"
        )
    if len(markets) > 12:
        info(f"... 외 {len(markets) - 12}개")

    print()
    m0 = markets[0]
    print(f"  [토큰 구조 샘플 — '{m0.question}']")
    print(f"  YES token: {m0.yes_token_id[:24]}...")
    print(f"  NO  token: {m0.no_token_id[:24]}...")

    return markets


# ── [2-A] Odds API 실제 호출 ─────────────────────────────────

async def test_odds_live(session: aiohttp.ClientSession):
    from core.odds_fetcher import fetch_nba_games

    header("[2] Odds API — Pinnacle 배당 실제 호출 (⚠️ 크레딧 소비)")

    try:
        games = await fetch_nba_games(session)
    except Exception as e:
        fail(f"Odds API 오류: {e}")
        return []

    if not games:
        warn("정배 경기 없음 (오늘 NBA 경기 없거나 전부 비등)")
        return []

    ok(f"정배 경기 {len(games)}개")
    print()
    print(f"  {'홈팀':<26} {'원정팀':<26} {'정배팀':<20} {'배당':>6} {'확률':>7} {'시작':>6}")
    print(f"  {SUB}")
    for g in games:
        print(
            f"  {g.home_team:<26} {g.away_team:<26} "
            f"{g.favorite_team:<20} "
            f"{g.favorite_odds:>6.2f} {g.favorite_prob:>7.1%} "
            f"{g.hours_until_start():>5.1f}h"
        )
    return games


# ── [2-B] Mock 데이터 (폴리마켓 실제 마켓 기반) ──────────────

def make_mock_games(poly_markets):
    """폴리마켓 마켓 기반 mock PinnacleGame 생성.

    - 실제 Gamma 마켓의 game_start_time 그대로 사용 → 시간 매칭 보장
    - 팀명도 폴리마켓 약칭 그대로 사용 → team_mapping 불필요 (스킵)
    - 배당은 테스트용 고정값 (일부는 1.5 이하, 일부는 초과)

    주의: 팀명이 약칭이라 team_mapping.json 불필요.
          match_games()가 home_short를 직접 비교하므로 매핑 정상 동작.
    """
    from core.odds_fetcher import PinnacleGame
    from config import MAX_PINNACLE_ODDS

    # 경기별 mock 배당: 홈팀 odds / 원정팀 odds
    # 일부는 1.5 이하로 만들어 정배 필터 통과, 일부는 초과
    MOCK_ODDS_MAP = {
        # 정배 통과 (1.5 이하)
        0: (1.35, 3.10),   # 첫 번째 경기: 홈팀 강세
        1: (1.45, 2.70),   # 두 번째 경기: 홈팀 약세 정배
        2: (2.30, 1.42),   # 세 번째 경기: 원정팀 정배
        # 정배 미통과 (1.5 초과 → 필터에서 제외됨)
        3: (1.72, 2.15),
        4: (1.88, 2.00),
    }

    games = []
    for i, m in enumerate(poly_markets[:5]):
        h_odds, a_odds = MOCK_ODDS_MAP.get(i, (1.80, 2.05))
        if min(h_odds, a_odds) > MAX_PINNACLE_ODDS:
            continue   # 정배 없는 경기는 제외

        games.append(PinnacleGame(
            game_id       = f"mock_{i:03d}",
            home_team     = m.home_short,   # 폴리마켓 약칭 = 정규화 없이 직접 매칭
            away_team     = m.away_short,
            commence_time = m.game_start_time,
            home_odds     = h_odds,
            away_odds     = a_odds,
        ))

    return games


async def test_odds_mock(poly_markets):
    header("[2] Odds API — Mock 데이터 사용 (크레딧 소비 없음)")

    if not poly_markets:
        warn("폴리마켓 마켓 없음 — mock 생성 불가")
        return []

    games = make_mock_games(poly_markets)

    if not games:
        warn("정배 조건(1.5 이하) 통과 mock 경기 없음")
        return []

    ok(f"mock 정배 경기 {len(games)}개 생성 (폴리마켓 실제 마켓 기반)")
    print()
    print(f"  {'홈팀':<18} {'원정팀':<18} {'정배팀':<18} {'배당':>6} {'확률':>7}")
    print(f"  {SUB}")
    for g in games:
        print(
            f"  {g.home_team:<18} {g.away_team:<18} "
            f"{g.favorite_team:<18} "
            f"{g.favorite_odds:>6.2f} {g.favorite_prob:>7.1%}"
        )
    print()
    info("mock 모드: 팀명이 폴리마켓 약칭과 동일 → team_mapping 불필요")

    return games


# ── [3] 매핑 테스트 ─────────────────────────────────────────

async def test_matching(pinnacle_games, poly_markets, live_mode: bool):
    from core.matcher import load_team_mapping, match_games

    header("[3] 경기 매핑 — Pinnacle ↔ 폴리마켓")

    if not pinnacle_games or not poly_markets:
        warn("데이터 없음 — 매핑 스킵")
        return []

    # live 모드: 실제 team_mapping 사용 / mock 모드: 빈 딕셔너리 (팀명이 이미 약칭)
    team_mapping = load_team_mapping() if live_mode else {}
    mode_str = f"team_mapping {len(team_mapping)}팀" if live_mode else "직접 약칭 매칭 (mock)"
    info(mode_str)

    matched = match_games(pinnacle_games, poly_markets, team_mapping)

    print()
    if not matched:
        warn("매핑된 경기 없음")
        if live_mode:
            print()
            print("  [진단] 팀명 정규화 결과:")
            from core.matcher import normalize
            for g in pinnacle_games[:4]:
                h_s = normalize(g.home_team, team_mapping)
                a_s = normalize(g.away_team, team_mapping)
                print(f"    '{g.home_team}' → '{h_s}'  /  '{g.away_team}' → '{a_s}'")
            print()
            print("  [진단] 폴리마켓 마켓 샘플:")
            for m in poly_markets[:4]:
                print(f"    home='{m.home_short}'  away='{m.away_short}'")
        return []

    ok(f"매핑 성공: {len(pinnacle_games)}경기 중 {len(matched)}경기")
    print()
    print(f"  {'Pinnacle':<32} {'폴리마켓 마켓':<38} {'매수':<5} {'정배'}")
    print(f"  {SUB}")
    for m in matched:
        p = m.pinnacle
        print(
            f"  {p.home_team+' vs '+p.away_team:<32} "
            f"{m.poly.question:<38} "
            f"{m.buy_token_label:<5} "
            f"{p.favorite_team}({p.favorite_odds:.2f})"
        )

    return matched


# ── [4] 갭 스캔 테스트 ───────────────────────────────────────

async def test_scan(session: aiohttp.ClientSession, matched_games):
    from core.scanner import _fetch_orderbook, _best_ask_and_shares
    from config import MAX_POLYMARKET_PRICE, GAP_THRESHOLD, MIN_LIQUIDITY_SHARES

    header("[4] 갭 스캔 — CLOB 오더북 실시간 조회 (무료)")

    if not matched_games:
        warn("매핑된 경기 없음 — 스캔 스킵")
        return

    print(f"  기준: 폴리가 < {MAX_POLYMARKET_PRICE}  |  갭 >= {GAP_THRESHOLD}  |  유동성 >= {MIN_LIQUIDITY_SHARES}")
    print()
    print(f"  {'마켓':<38} {'토큰':<5} {'폴리가':>7} {'Pinnacle':>9} {'갭':>7} {'유동성':>8}  판정")
    print(f"  {SUB}")

    opportunities = []
    for m in matched_games:
        g    = m.pinnacle
        book = await _fetch_orderbook(session, m.buy_token_id)

        if book is None:
            print(f"  {m.poly.question:<38}  오더북 조회 실패")
            continue

        best_ask, shares = _best_ask_and_shares(book)
        if best_ask is None:
            print(f"  {m.poly.question:<38}  ask 없음")
            continue

        gap   = g.favorite_prob - best_ask
        c2    = best_ask < MAX_POLYMARKET_PRICE
        c3    = gap >= GAP_THRESHOLD
        c4    = shares >= MIN_LIQUIDITY_SHARES
        all_ok = c2 and c3 and c4

        fails = "".join([
            "" if c2 else " ✗폴리가높음",
            "" if c3 else " ✗갭부족",
            "" if c4 else " ✗유동성부족",
        ])
        verdict = "🎯 기회!" if all_ok else fails.strip()

        print(
            f"  {m.poly.question:<38} {m.buy_token_label:<5} "
            f"{best_ask:>7.3f} {g.favorite_prob:>9.3f} {gap:>+7.3f} "
            f"{shares:>8.0f}  {verdict}"
        )

        if all_ok:
            opportunities.append((m, best_ask, gap, shares))

    print()
    if opportunities:
        ok(f"기회 {len(opportunities)}개 감지!")
        for m, price, gap, shares in opportunities:
            g = m.pinnacle
            from core.scanner import _calc_bet
            bet = _calc_bet(gap)
            print(
                f"    → {m.poly.question}\n"
                f"       정배: {g.favorite_team} ({g.favorite_odds:.2f}배 / {g.favorite_prob:.1%})\n"
                f"       폴리: {price:.3f}  갭: {gap:+.3f}  유동성: {shares:.0f}  "
                f"매수: {m.buy_token_label}  베팅: ${bet:.0f}"
            )
    else:
        info("현재 기회 없음 (갭 조건 미충족 — 정상 상태)")


# ── [5] 갭 감지 시뮬레이션 ──────────────────────────────────

async def test_sim(matched_games):
    """가상 CLOB 가격으로 갭 감지 → ArbitrageOpportunity 생성 흐름 검증.

    실제 CLOB 호출 없음. 정배팀을 폴리마켓이 역배로 가격 책정하는
    시나리오를 가상으로 재현해 scanner 로직과 베팅 금액 산출 확인.
    """
    from core.scanner import ArbitrageOpportunity, _calc_bet
    from config import MAX_POLYMARKET_PRICE, GAP_THRESHOLD, MIN_LIQUIDITY_SHARES

    header("[5] 갭 감지 시뮬레이션 (가상 CLOB 가격)")

    if not matched_games:
        warn("매핑된 경기 없음 — 시뮬레이션 스킵")
        return

    m = matched_games[0]
    g = m.pinnacle

    info(f"경기: {m.poly.question}")
    info(f"정배: {g.favorite_team}  배당={g.favorite_odds:.2f}  Pinnacle확률={g.favorite_prob:.1%}")
    info(f"매수 토큰: {m.buy_token_label} ({m.buy_token_id[:20]}...)")
    print()

    # 시나리오: 고정 폴리마켓 ask 가격으로 각 조건 검증
    # (Pinnacle 확률 높이에 관계없이 일정한 결과를 보여주기 위해 절대값 사용)
    scenarios = [
        (0.40, 500, "강한 역배 (ask=0.40)"),        # 조건 2·3·4 통과 예상
        (0.47, 120, "약한 역배 (ask=0.47)"),        # prob ≥ 0.62이면 통과
        (0.52, 200, "폴리가 높음 (ask=0.52)"),      # 조건 2 실패
        (0.44,  30, "유동성 부족 (shares=30)"),     # 조건 4 실패
    ]

    print(f"  {'시나리오':<30} {'폴리가':>7} {'갭':>8} {'유동성':>8}  판정")
    print(f"  {SUB}")

    opportunity = None
    for poly_ask, shares, label in scenarios:
        poly_ask = round(max(0.01, min(0.99, poly_ask)), 3)
        gap      = g.favorite_prob - poly_ask

        c2 = poly_ask < MAX_POLYMARKET_PRICE
        c3 = gap >= GAP_THRESHOLD
        c4 = shares >= MIN_LIQUIDITY_SHARES
        all_ok = c2 and c3 and c4

        if all_ok:
            bet     = _calc_bet(gap)
            verdict = f"🎯 기회! → ${bet:.0f} 베팅"
            if opportunity is None:
                opportunity = ArbitrageOpportunity(
                    matched          = m,
                    poly_price       = poly_ask,
                    pinnacle_prob    = g.favorite_prob,
                    gap_size         = gap,
                    liquidity_shares = shares,
                    bet_usdc         = bet,
                )
        else:
            reasons = "".join([
                "" if c2 else "✗폴리가높음 ",
                "" if c3 else "✗갭부족 ",
                "" if c4 else "✗유동성부족",
            ])
            verdict = reasons.strip()

        print(f"  {label:<30} {poly_ask:>7.3f} {gap:>+8.3f} {shares:>8.0f}  {verdict}")

    print()

    if opportunity:
        ok("기회 감지 성공 — ArbitrageOpportunity 내용:")
        for line in str(opportunity).split("\n"):
            print(f"    {line}")
        print()
        info("베팅 금액 테이블 확인:")
        for g_min, g_max, amount in [(0.15, 0.20, 10), (0.20, 0.30, 20), (0.30, 1.00, 30)]:
            print(f"    갭 {g_min:.2f}~{g_max:.2f} → ${amount}")
    else:
        warn("시뮬레이션에서 기회 조건 통과 없음 — 파라미터 재확인 필요")


# ── 메인 ─────────────────────────────────────────────────────

async def main(live: bool) -> None:
    print(SEP)
    mode = "LIVE (Odds API 실제 호출 — 크레딧 소비)" if live else "MOCK (크레딧 소비 없음)"
    print(f"  polymoly 통합 테스트  |  {mode}")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(SEP)

    async with aiohttp.ClientSession(connector=_make_connector()) as session:

        # [1] Gamma API (항상 실시간, 무료)
        poly_markets = await test_gamma(session)

        # [2] Odds API (live or mock)
        if live:
            pinnacle_games = await test_odds_live(session)
        else:
            pinnacle_games = await test_odds_mock(poly_markets)

        # [3] 매핑
        matched = await test_matching(pinnacle_games, poly_markets, live_mode=live)

        # [4] 갭 스캔 (CLOB 오더북, 항상 실시간, 무료)
        await test_scan(session, matched)

        # [5] 갭 감지 시뮬레이션 (가상 CLOB 가격, 무료)
        await test_sim(matched)

    print()
    print(SEP)
    print("  테스트 완료")
    print(SEP)


if __name__ == "__main__":
    live_mode = "--live" in sys.argv
    asyncio.run(main(live_mode))
