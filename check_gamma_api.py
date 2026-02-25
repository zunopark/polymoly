"""
check_gamma_api.py - Polymarket Gamma API Response 구조 확인 스크립트

목적:
  1. 종목별 gamma_tag (tag_slug) 실제 값 확인
  2. 마켓 질문 패턴 확인 (_is_win_loss_market 필터 검증)
  3. clobTokenIds / outcomes 구조 확인 (토큰 매핑 검증)
  4. gameStartTime 포맷, negRisk, minTickSize 필드 확인

크레딧 소모 없음 (Gamma API는 무료 공개 API)

사용법:
  python check_gamma_api.py tags              # 폴리마켓 스포츠 태그 탐색
  python check_gamma_api.py events nba        # NBA 이벤트/마켓 목록
  python check_gamma_api.py events nhl        # NHL 이벤트/마켓 목록
  python check_gamma_api.py events soccer     # 축구(EPL) 이벤트/마켓 목록
  python check_gamma_api.py market <id>       # 특정 마켓 상세 조회
  python check_gamma_api.py raw <tag>         # tag_slug 원본 JSON (첫 이벤트)
"""

import asyncio
import json
import ssl
import sys
from datetime import datetime, timezone

import aiohttp

GAMMA_BASE = "https://gamma-api.polymarket.com"

# 확인할 후보 태그 목록 (tags 명령어에서 탐색)
CANDIDATE_TAGS = [
    "nba", "nhl", "nhl-hockey", "hockey", "ice-hockey",
    "soccer", "epl", "premier-league", "english-premier-league",
    "football", "sports",
]

# 봇 설정 종목별 현재 추정 태그
SPORT_TAGS = {
    "nba":    "nba",
    "nhl":    "nhl",
    "soccer": "soccer",
}


# ── 유틸 ────────────────────────────────────────────────────

def print_header(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def _parse_gst(raw: str | None) -> str:
    """gameStartTime 문자열을 읽기 좋은 형태로 변환."""
    if not raw:
        return "(없음)"
    try:
        raw = raw.replace(" ", "T")
        if raw.endswith("+00"):
            raw = raw[:-3] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        hrs = (dt - now).total_seconds() / 3600
        return f"{dt.strftime('%m/%d %H:%M')} UTC ({hrs:+.1f}h)"
    except ValueError:
        return raw


def _is_win_loss_market(question: str) -> bool:
    """봇과 동일한 필터 로직 (matcher.py 미러)."""
    q_lower = question.lower()
    exclude = ["total", "points", "over", "under", "score", "spread"]
    for kw in exclude:
        if kw in q_lower:
            return False
    win_kws = ["beat", "win", "defeat"]
    for kw in win_kws:
        if kw in q_lower:
            return True
    return False


# ── SSL 컨텍스트 (사내 네트워크/VPN 대응) ──────────────────

def _make_session_kwargs() -> dict:
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    return {"connector": aiohttp.TCPConnector(ssl=ssl_ctx)}


# ── 1. tags — 후보 태그 탐색 ────────────────────────────────

async def cmd_tags(session: aiohttp.ClientSession) -> None:
    """CANDIDATE_TAGS 후보들을 실제로 조회해서 결과 유무 확인."""
    print_header("Gamma API 스포츠 태그 탐색")
    print(f"후보 태그 {len(CANDIDATE_TAGS)}개 조회 중...\n")

    results = []
    for tag in CANDIDATE_TAGS:
        params = {"tag_slug": tag, "active": "true", "closed": "false", "limit": 5}
        try:
            async with session.get(f"{GAMMA_BASE}/events", params=params) as resp:
                if resp.status != 200:
                    results.append((tag, 0, f"HTTP {resp.status}"))
                    continue
                events = await resp.json()
                count = len(events)
                # 마켓 총 개수
                market_count = sum(len(e.get("markets") or []) for e in events)
                results.append((tag, count, f"{count}개 이벤트, {market_count}개 마켓"))
        except Exception as e:
            results.append((tag, 0, f"오류: {e}"))

    print(f"{'태그':<30} {'결과'}")
    print("-" * 60)
    for tag, count, desc in results:
        marker = "  ★" if count > 0 else "   "
        print(f"  {tag:<28}{marker}  {desc}")

    print("\n★ = 이벤트 있음 → gamma_tag 후보")


# ── 2. events — 종목별 이벤트/마켓 목록 ────────────────────

async def cmd_events(session: aiohttp.ClientSession, tag: str) -> None:
    """특정 tag_slug의 이벤트 + 마켓 목록 출력."""
    print_header(f"Gamma API /events?tag_slug={tag}")

    params = {
        "tag_slug": tag,
        "active": "true",
        "closed": "false",
        "limit": 50,
    }

    async with session.get(f"{GAMMA_BASE}/events", params=params) as resp:
        if resp.status != 200:
            body = await resp.text()
            print(f"\n[오류] HTTP {resp.status}\n{body}")
            return
        events: list[dict] = await resp.json()

    now = datetime.now(timezone.utc)
    print(f"\n총 {len(events)}개 이벤트")

    if not events:
        print("  → 해당 태그의 이벤트 없음. 태그가 잘못됐을 수 있음.")
        print(f"  → 'python check_gamma_api.py tags' 로 올바른 태그를 탐색하세요.")
        return

    # 원본 JSON (첫 이벤트의 첫 마켓)
    first_event = events[0]
    first_markets = first_event.get("markets") or []
    print(f"\n원본 JSON (첫 번째 이벤트):")
    print(json.dumps(first_event, indent=2, ensure_ascii=False)[:3000])
    if len(json.dumps(first_event)) > 3000:
        print("  ... (truncated)")

    # 마켓별 요약
    print(f"\n── 마켓 목록 ──")
    all_questions = []
    for event in events:
        event_title = event.get("title", "(제목 없음)")
        for m in (event.get("markets") or []):
            question      = m.get("question", "")
            condition_id  = m.get("conditionId", "")[:12]
            gst_raw       = m.get("gameStartTime")
            gst           = _parse_gst(gst_raw)
            accepting     = "O" if m.get("acceptingOrders") else "X"
            neg_risk      = "Y" if m.get("negRisk") else "N"
            tick          = m.get("minTickSize", "?")
            passes_filter = "✓" if _is_win_loss_market(question) else "✗"
            all_questions.append((question, passes_filter))

            print(
                f"  [{passes_filter}] {question[:55]:<55}\n"
                f"       ID={condition_id}  시작={gst}\n"
                f"       acceptingOrders={accepting}  negRisk={neg_risk}  "
                f"tickSize={tick}  event={event_title[:30]}"
            )

    # 필터 통과 비율
    total    = len(all_questions)
    pass_cnt = sum(1 for _, f in all_questions if f == "✓")
    print(f"\n── _is_win_loss_market 필터 결과 ──")
    print(f"  전체 {total}개 마켓 중 통과: {pass_cnt}개  /  제외: {total - pass_cnt}개")

    # 제외된 질문 패턴 샘플
    excluded = [q for q, f in all_questions if f == "✗"]
    if excluded:
        print(f"\n  [제외된 마켓 질문 샘플]")
        for q in excluded[:10]:
            print(f"    - {q}")

    # 통과한 질문 패턴 샘플
    passed = [q for q, f in all_questions if f == "✓"]
    if passed:
        print(f"\n  [통과한 마켓 질문 샘플]")
        for q in passed[:10]:
            print(f"    + {q}")

    # 토큰 구조 확인 (첫 번째 통과 마켓)
    print(f"\n── 토큰 구조 확인 ──")
    found_token_sample = False
    for event in events:
        for m in (event.get("markets") or []):
            if not _is_win_loss_market(m.get("question", "")):
                continue
            raw_ids      = m.get("clobTokenIds")
            raw_outcomes = m.get("outcomes")
            print(f"  질문: {m.get('question')}")
            print(f"  clobTokenIds: {raw_ids}")
            print(f"  outcomes:     {raw_outcomes}")
            found_token_sample = True
            break
        if found_token_sample:
            break

    if not found_token_sample:
        print("  (통과 마켓 없음 — 필터 조건 재검토 필요)")

    # gameStartTime 포맷 샘플
    print(f"\n── gameStartTime 포맷 샘플 ──")
    shown = set()
    for event in events:
        for m in (event.get("markets") or []):
            gst_raw = m.get("gameStartTime")
            if gst_raw and gst_raw not in shown:
                print(f"  raw: {repr(gst_raw)}")
                shown.add(gst_raw)
            if len(shown) >= 3:
                break
        if len(shown) >= 3:
            break


# ── 3. market — 특정 마켓 상세 조회 ─────────────────────────

async def cmd_market(session: aiohttp.ClientSession, condition_id: str) -> None:
    """특정 conditionId 마켓의 상세 JSON 출력."""
    print_header(f"Gamma API /markets/{condition_id}")

    url = f"{GAMMA_BASE}/markets/{condition_id}"
    async with session.get(url) as resp:
        if resp.status == 404:
            print(f"\n[404] 마켓을 찾을 수 없음: {condition_id}")
            return
        if resp.status != 200:
            body = await resp.text()
            print(f"\n[오류] HTTP {resp.status}\n{body}")
            return
        market = await resp.json()

    print(f"\n원본 JSON:")
    print(json.dumps(market, indent=2, ensure_ascii=False))


# ── 4. raw — 원본 JSON 전체 출력 ────────────────────────────

async def cmd_raw(session: aiohttp.ClientSession, tag: str) -> None:
    """tag_slug로 조회한 첫 번째 이벤트 원본 JSON 전체 출력."""
    print_header(f"Gamma API Raw JSON — tag_slug={tag}")

    params = {"tag_slug": tag, "active": "true", "closed": "false", "limit": 3}
    async with session.get(f"{GAMMA_BASE}/events", params=params) as resp:
        if resp.status != 200:
            body = await resp.text()
            print(f"\n[오류] HTTP {resp.status}\n{body}")
            return
        events = await resp.json()

    if not events:
        print(f"\n  → tag_slug='{tag}' 이벤트 없음")
        return

    print(f"\n총 {len(events)}개 이벤트 조회됨 (최대 3개 표시)\n")
    for i, event in enumerate(events):
        print(f"\n{'─'*40} 이벤트 {i+1} {'─'*40}")
        print(json.dumps(event, indent=2, ensure_ascii=False))


# ── 진입점 ──────────────────────────────────────────────────

async def main() -> None:
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0].lower()

    async with aiohttp.ClientSession(**_make_session_kwargs()) as session:
        if cmd == "tags":
            await cmd_tags(session)

        elif cmd == "events":
            tag = args[1].lower() if len(args) > 1 else "nba"
            await cmd_events(session, tag)

        elif cmd == "market":
            if len(args) < 2:
                print("사용법: python check_gamma_api.py market <conditionId>")
                sys.exit(1)
            await cmd_market(session, args[1])

        elif cmd == "raw":
            tag = args[1].lower() if len(args) > 1 else "nba"
            await cmd_raw(session, tag)

        else:
            print(f"알 수 없는 명령: {cmd}")
            print("사용법: python check_gamma_api.py [tags|events|market|raw] [인자]")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
