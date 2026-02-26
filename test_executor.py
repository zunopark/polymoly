"""
test_executor.py - 폴리마켓 매수 실행 검증 스크립트

단계:
  [1] CLOB 클라이언트 초기화 + 자격증명 확인 (USDC 잔고 조회)
  [2] Gamma API — NBA 마켓 조회
  [3] CLOB 오더북 — 매수 후보 마켓 선정 (ask 가격 + 유동성)
  [4] FOK 매수 실행 (dry-run 기본 / --confirm 플래그 시 실제 실행)

사용법:
  python test_executor.py              # dry-run (실제 주문 안 함)
  python test_executor.py --confirm    # 실제 FOK 매수 ($5)
  python test_executor.py --confirm --amount 10  # 금액 지정
"""

import asyncio
import os
import ssl
import sys
from datetime import datetime, timezone

import aiohttp
from dotenv import load_dotenv

load_dotenv()

SEP = "=" * 65
SUB = "-" * 65


def header(title: str) -> None:
    print(f"\n{SEP}\n  {title}\n{SEP}")


def ok(msg: str)   -> None: print(f"  ✅ {msg}")
def warn(msg: str) -> None: print(f"  ⚠️  {msg}")
def info(msg: str) -> None: print(f"  ℹ️  {msg}")
def fail(msg: str) -> None: print(f"  ❌ {msg}")


def _make_connector() -> aiohttp.TCPConnector:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    return aiohttp.TCPConnector(ssl=ctx)


# ── [1] CLOB 클라이언트 초기화 ──────────────────────────────

def init_clob_client():
    """py-clob-client L2 클라이언트 초기화."""
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
    from config import CLOB_HOST, CHAIN_ID

    key        = os.getenv("PRIVATE_KEY")
    funder     = os.getenv("FUNDER_ADDRESS")
    api_key    = os.getenv("POLY_API_KEY")
    secret     = os.getenv("POLY_SECRET")
    passphrase = os.getenv("POLY_PASSPHRASE")
    sig_type   = int(os.getenv("POLY_SIGNATURE_TYPE", "1"))

    missing = [k for k, v in {
        "PRIVATE_KEY": key, "FUNDER_ADDRESS": funder,
        "POLY_API_KEY": api_key, "POLY_SECRET": secret,
        "POLY_PASSPHRASE": passphrase,
    }.items() if not v]

    if missing:
        fail(f".env 미설정: {', '.join(missing)}")
        return None

    creds = ApiCreds(
        api_key=api_key,
        api_secret=secret,
        api_passphrase=passphrase,
    )
    client = ClobClient(
        host           = CLOB_HOST,
        chain_id       = CHAIN_ID,
        key            = key,
        funder         = funder,
        signature_type = sig_type,
        creds          = creds,
    )
    return client


async def test_credentials(client) -> dict | None:
    """자격증명 검증 + USDC 잔고 조회."""
    from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

    header("[1] CLOB 클라이언트 초기화 + 자격증명 확인")

    try:
        # API 키 목록으로 L2 인증 확인
        api_keys = await asyncio.to_thread(client.get_api_keys)
        ok(f"L2 인증 성공 (API 키 {len(api_keys.get('apiKeys', []))}개)")
    except Exception as e:
        fail(f"L2 인증 실패: {e}")
        info("PRIVATE_KEY / POLY_SIGNATURE_TYPE / POLY_API_KEY 확인 필요")
        return None

    try:
        # USDC 잔고 조회
        balance_resp = await asyncio.to_thread(
            client.get_balance_allowance,
            BalanceAllowanceParams(asset_type=AssetType.COLLATERAL),
        )
        balance = float(balance_resp.get("balance", 0)) / 1e6   # USDC.e는 6 decimals
        # 응답 구조: {"allowances": {"0x교환소주소": "금액", ...}}
        allowances_dict = balance_resp.get("allowances", {})
        total_allowance = sum(int(v) for v in allowances_dict.values()) / 1e6 if allowances_dict else 0
        ok(f"USDC 잔고: ${balance:.2f}  |  허용 한도: {'무제한' if total_allowance > 1e20 else f'${total_allowance:.2f}'} ({len(allowances_dict)}개 거래소)")

        if balance < 5:
            warn(f"USDC 잔고 ${balance:.2f} — $5 미만이라 실제 매수 불가")

        return {"balance": balance, "allowances": allowances_dict}

    except Exception as e:
        warn(f"잔고 조회 실패 (주문은 가능할 수 있음): {e}")
        return {"balance": None, "allowance": None}


# ── [2] NBA 마켓 조회 ────────────────────────────────────────

async def test_markets(session: aiohttp.ClientSession):
    from core.matcher import fetch_nba_poly_markets

    header("[2] Gamma API — NBA 마켓 조회")

    try:
        markets = await fetch_nba_poly_markets(session)
    except Exception as e:
        fail(f"Gamma API 오류: {e}")
        return []

    if not markets:
        warn("조회된 NBA 마켓 없음")
        return []

    ok(f"마켓 {len(markets)}개 조회")
    print()
    print(f"  {'질문':<40} {'홈팀':<14} {'원정팀':<14} {'시작까지'}")
    print(f"  {SUB}")
    for m in markets[:10]:
        hrs = (m.game_start_time - datetime.now(timezone.utc)).total_seconds() / 3600
        print(f"  {m.question:<40} {m.home_short:<14} {m.away_short:<14} +{hrs:.1f}h")
    if len(markets) > 10:
        info(f"... 외 {len(markets) - 10}개")

    return markets


# ── [3] 오더북 조회 + 매수 후보 선정 ────────────────────────

async def select_target(
    session: aiohttp.ClientSession,
    client,
    markets,
) -> dict | None:
    """마켓별 CLOB 오더북 조회 → 매수 후보 1개 선정."""
    from config import CLOB_HOST

    header("[3] CLOB 오더북 — 매수 후보 선정")

    print(f"  {'마켓':<40} {'토큰':<5} {'ask':>7} {'유동성':>9}  tick  neg_risk")
    print(f"  {SUB}")

    candidates = []

    for m in markets[:8]:
        for label, token_id in [("YES", m.yes_token_id), ("NO", m.no_token_id)]:
            # 오더북 조회
            try:
                async with session.get(
                    f"{CLOB_HOST}/book",
                    params={"token_id": token_id},
                ) as resp:
                    resp.raise_for_status()
                    book = await resp.json()
            except Exception as e:
                print(f"  {m.question:<40}  오더북 오류: {e}")
                continue

            asks = book.get("asks", [])
            if not asks:
                continue

            # CLOB 오더북: asks는 내림차순(비쌈→쌈) → asks[-1]이 최저 ask(매수 최적가)
            best_ask = float(asks[-1]["price"])
            shares   = sum(float(a["size"]) for a in asks[-3:])

            # tick_size, neg_risk 조회
            try:
                tick = await asyncio.to_thread(client.get_tick_size, token_id)
                neg  = await asyncio.to_thread(client.get_neg_risk, token_id)
            except Exception:
                tick, neg = "?", "?"

            print(
                f"  {m.question:<40} {label:<5} {best_ask:>7.3f} {shares:>9.1f}"
                f"  {tick}  {neg}"
            )

            if best_ask < 0.60 and shares >= 20:
                candidates.append({
                    "market":    m,
                    "label":     label,
                    "token_id":  token_id,
                    "best_ask":  best_ask,
                    "shares":    shares,
                    "tick_size": tick,
                    "neg_risk":  neg,
                })

    print()
    if not candidates:
        warn("ask < 0.60 + 유동성 >= 20 조건 충족 마켓 없음")
        return None

    # ask 가장 낮은 것 선택 (가장 저렴한 = 갭이 클 가능성)
    target = sorted(candidates, key=lambda x: x["best_ask"])[0]
    ok(
        f"매수 후보 선정: {target['market'].question}  "
        f"{target['label']}  ask={target['best_ask']:.3f}  "
        f"유동성={target['shares']:.0f}"
    )
    return target


# ── [4] FOK 매수 실행 ────────────────────────────────────────

async def execute_buy(client, target: dict, amount: float, confirm: bool) -> None:
    from py_clob_client.clob_types import (
        MarketOrderArgs, OrderType, PartialCreateOrderOptions,
    )
    from py_clob_client.order_builder.constants import BUY
    from core.db import DB

    header(f"[4] FOK 매수 {'실행' if confirm else 'DRY-RUN'}")

    m        = target["market"]
    token_id = target["token_id"]
    label    = target["label"]
    ask      = target["best_ask"]
    tick     = target["tick_size"]
    neg      = target["neg_risk"]

    print(f"  마켓:     {m.question}")
    print(f"  매수:     {label}  (token_id: {token_id[:24]}...)")
    print(f"  최저 ask: {ask:.4f}  →  worst-price (슬리피지 상한)")
    print(f"  금액:     ${amount:.2f} USDC")
    print(f"  tick_size: {tick}  /  neg_risk: {neg}")
    print()

    if not confirm:
        warn("DRY-RUN 모드 — 실제 주문 없음. --confirm 플래그로 실제 실행 가능.")
        return

    print("  주문 제출 중...")

    try:
        order_args = MarketOrderArgs(
            token_id = token_id,
            amount   = amount,
            side     = BUY,
            price    = ask,      # worst-price 슬리피지 보호
        )
        options = PartialCreateOrderOptions(
            tick_size = tick,
            neg_risk  = neg,
        )

        signed_order = await asyncio.to_thread(
            client.create_market_order, order_args, options
        )
        resp = await asyncio.to_thread(
            client.post_order, signed_order, OrderType.FOK
        )

    except Exception as e:
        fail(f"주문 오류: {e}")
        return

    order_id     = resp.get("orderID") or resp.get("order_id", "")
    status_field = resp.get("status", "")
    error_msg    = resp.get("errorMsg", "")
    success      = resp.get("success", True)

    print()
    print(f"  ── 응답 ──────────────────────────────────────")
    print(f"  success:    {success}")
    print(f"  status:     {status_field}")
    print(f"  orderID:    {order_id}")
    print(f"  errorMsg:   {error_msg or '(없음)'}")
    print(f"  takingAmt:  {resp.get('takingAmount', '')}")
    print(f"  makingAmt:  {resp.get('makingAmount', '')}")
    print()

    if status_field in ("matched", "delayed"):
        ok(f"{'체결 완료' if status_field == 'matched' else '지연 체결 (3초 후 처리)'}  order_id={order_id}")

        # DB 기록
        db = DB()
        bet_id = db.insert_bet(
            game_id       = f"test_{m.condition_id[:8]}",
            event_title   = m.question,
            token_id      = token_id,
            buy_label     = label,
            favorite_team = label,
            pinnacle_odds = 0.0,
            pinnacle_prob = 0.0,
            poly_price    = ask,
            gap_size      = 0.0,
            bet_usdc      = amount,
            order_id      = order_id,
            commence_time = m.game_start_time.isoformat(),
        )
        ok(f"DB 기록 완료 (bet_id={bet_id})")

    elif error_msg:
        fail(f"주문 거부: {error_msg}")
    else:
        warn(f"예상치 못한 상태: {status_field}")


# ── 메인 ─────────────────────────────────────────────────────

async def main(confirm: bool, amount: float) -> None:
    print(SEP)
    mode = f"CONFIRM (실제 매수 ${amount:.0f})" if confirm else "DRY-RUN (주문 없음)"
    print(f"  test_executor  |  {mode}")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(SEP)

    # CLOB 클라이언트 초기화
    client = init_clob_client()
    if client is None:
        fail("클라이언트 초기화 실패 — .env 확인")
        return

    async with aiohttp.ClientSession(connector=_make_connector()) as session:

        # [1] 자격증명 확인
        cred_info = await test_credentials(client)
        if cred_info is None:
            return

        if confirm and cred_info.get("balance") is not None:
            if cred_info["balance"] < amount:
                fail(f"USDC 잔고 ${cred_info['balance']:.2f} < ${amount:.0f} — 매수 불가")
                return
            if not cred_info.get("allowances"):
                warn("allowance 미설정 — 주문이 거부될 수 있음")

        # [2] 마켓 조회
        markets = await test_markets(session)
        if not markets:
            return

        # [3] 매수 후보 선정
        target = await select_target(session, client, markets)
        if target is None:
            return

        # [4] 매수 실행 (or dry-run)
        await execute_buy(client, target, amount, confirm)

    print()
    print(SEP)
    print("  테스트 완료")
    print(SEP)


if __name__ == "__main__":
    confirm = "--confirm" in sys.argv
    amount  = 5.0
    for i, arg in enumerate(sys.argv):
        if arg == "--amount" and i + 1 < len(sys.argv):
            amount = float(sys.argv[i + 1])

    asyncio.run(main(confirm, amount))
