"""
main.py - Polymarket 배당 역전 봇 (polymoly) 진입점

전략 플로우:
  1. [수집]  Odds API → Pinnacle NBA 배당 수집 (1.5 이하 정배 필터)
  2. [조회]  Gamma API → 폴리마켓 NBA 예정 경기 마켓 조회
  3. [매핑]  팀명 정규화 + 시간 매칭으로 동일 경기 식별
  4. [스캔]  4조건 검사 → 배당 역전 기회 감지
  5. [실행]  조건 충족 시 FOK 시장가 매수
  6. [모니터] 경기 종료 후 결과 감지 → 수익/손실 기록

폴링 주기: 1시간 (POLL_INTERVAL)
"""

import asyncio
import logging
import logging.handlers
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

from config import (
    POLL_INTERVAL, MAX_CONSECUTIVE_LOSSES, LOG_FILE, ERROR_LOG_FILE,
    CREDITS_WARNING_THRESHOLD,
)
from core.db import DB
from core.executor import Executor
from core.matcher import fetch_nba_poly_markets, load_team_mapping, match_games
from core.monitor import Monitor
from core.notifier import (
    notify_started, notify_stopped,
    notify_opportunity, notify_executed, notify_failed,
    notify_auto_stopped, notify_low_credits,
    notify_poll_start, notify_no_games, notify_no_markets,
    notify_no_matches, notify_no_opportunities,
    notify_error, notify_credits_warning, notify_daily_limit,
)
from core.odds_fetcher import fetch_nba_games, InsufficientCreditsError, DailyLimitReachedError, load_credits
from core.scanner import scan

load_dotenv()


# ── 로깅 설정 ────────────────────────────────────────────────

def setup_logging() -> None:
    Path("logs").mkdir(exist_ok=True)

    fmt     = "%(asctime)s [%(levelname)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(level=logging.INFO, format=fmt, datefmt=datefmt)

    fh = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(fmt, datefmt))

    eh = logging.handlers.RotatingFileHandler(
        ERROR_LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    eh.setLevel(logging.ERROR)
    eh.setFormatter(logging.Formatter(fmt, datefmt))

    root = logging.getLogger()
    root.addHandler(fh)
    root.addHandler(eh)


log = logging.getLogger(__name__)


# ── 메인 폴링 루프 ───────────────────────────────────────────

async def polling_loop(
    session:  aiohttp.ClientSession,
    executor: Executor,
    monitor:  Monitor,
    db:       DB,
) -> None:
    """Odds API + Gamma API 조회 → 갭 감지 → 매수 실행 루프."""
    team_mapping = load_team_mapping()
    log.info(f"[main] 팀 매핑 로드: {len(team_mapping)}팀")

    poll_count           = 0
    credits_warning_sent = False   # WARNING 알림은 세션당 1회만

    while True:
        if monitor._stopped:
            log.error("[main] 모니터 자동 중단 — 폴링 종료")
            break

        poll_count += 1
        log.info("=" * 60)
        log.info(f"[main] 폴링 #{poll_count}: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

        # 폴링 시작 알림 (보유 포지션 수 + 이전 저장된 크레딧 포함)
        active_positions   = len(db.get_active_token_ids())
        credits_before     = load_credits()
        await notify_poll_start(session, poll_count, active_positions, credits_before)

        try:
            # 1. Pinnacle NBA 배당 수집
            pinnacle_games = await fetch_nba_games(session)

            # 크레딧 경고 체크 (API 호출 직후 갱신된 값 기준, 세션당 1회)
            credits_now = load_credits()
            if (
                not credits_warning_sent
                and credits_now is not None
                and credits_now < CREDITS_WARNING_THRESHOLD
            ):
                await notify_credits_warning(session, credits_now, CREDITS_WARNING_THRESHOLD)
                credits_warning_sent = True

            if not pinnacle_games:
                log.info("[main] 정배 경기 없음 — 대기")
                await notify_no_games(session)
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # 2. 폴리마켓 NBA 마켓 조회
            poly_markets = await fetch_nba_poly_markets(session)
            if not poly_markets:
                log.info("[main] 폴리마켓 경기 없음 — 대기")
                await notify_no_markets(session)
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # 3. 경기 매핑
            matched = match_games(pinnacle_games, poly_markets, team_mapping)
            if not matched:
                log.info("[main] 매핑 성공 경기 없음 — 대기")
                await notify_no_matches(session, len(pinnacle_games), len(poly_markets))
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # 4. 배당 역전 감지
            opportunities = await scan(session, matched)

            if not opportunities:
                await notify_no_opportunities(session, len(matched))

            # 5. 매수 실행
            for opp in opportunities:
                if executor.has_position(opp.token_id):
                    log.debug(f"[main] 이미 포지션 보유: {opp.event_title}")
                    continue

                await notify_opportunity(session, opp)
                result = await executor.execute(opp)

                if result.success:
                    await notify_executed(session, result)
                elif result.status not in ("skipped",):
                    await notify_failed(session, result)

        except DailyLimitReachedError as e:
            log.warning(str(e))
            now      = datetime.now(timezone.utc)
            midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            wait_sec = (midnight - now).total_seconds()
            wait_hrs = wait_sec / 3600
            log.info(f"[main] 일일 한도 — {wait_hrs:.1f}시간 후(자정 UTC) 재개")
            await notify_daily_limit(session, e.count, e.limit, wait_hrs)
            await asyncio.sleep(wait_sec)
            continue
        except InsufficientCreditsError as e:
            log.error(str(e))
            await notify_low_credits(session, e.remaining)
            log.info("[main] Odds API 크레딧 소진 — 6시간 후 재시도")
            await asyncio.sleep(6 * 3600)
            continue
        except aiohttp.ClientError as e:
            log.error(f"[main] 네트워크 오류: {e} — 5분 후 재시도")
            await notify_error(session, "네트워크", str(e))
            await asyncio.sleep(300)
            continue
        except Exception as e:
            log.error(f"[main] 예상치 못한 오류: {e}", exc_info=True)
            await notify_error(session, "예상치 못한 오류", str(e))
            await asyncio.sleep(300)
            continue

        log.info(f"[main] 다음 폴링: {POLL_INTERVAL // 60}분 후")
        await asyncio.sleep(POLL_INTERVAL)


# ── 진입점 ───────────────────────────────────────────────────

async def main() -> None:
    setup_logging()
    log.info("=== polymoly 봇 시작 ===")

    db       = DB()
    executor = Executor(db)
    monitor  = Monitor(executor, db)

    async with aiohttp.ClientSession() as session:
        await notify_started(session)
        await executor.initialize()

        try:
            await asyncio.gather(
                polling_loop(session, executor, monitor, db),
                monitor.run(session),
            )
        except asyncio.CancelledError:
            log.info("[main] 종료 요청")
        except Exception as e:
            log.error(f"[main] 치명적 오류: {e}", exc_info=True)
        finally:
            consecutive = db.count_consecutive_losses()
            if consecutive >= MAX_CONSECUTIVE_LOSSES:
                await notify_auto_stopped(session, consecutive, db.get_stats())
            else:
                await notify_stopped(session, "봇 정상 종료")

    log.info("=== 봇 종료 ===")


if __name__ == "__main__":
    asyncio.run(main())
