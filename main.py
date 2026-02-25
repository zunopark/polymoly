"""
Polymarket 배당 역전 봇 - 진입점 (polymoly)

전략 플로우:
  1. [수집]    Odds API로 ACTIVE_SPORTS 전체 Pinnacle 배당 수집 (종목별 임계값 필터)
  2. [조회]    Gamma API로 폴리마켓 예정 경기 마켓 목록 조회 (종목별 tag_slug)
  3. [매핑]    팀명 정규화 + 시간 매칭으로 동일 경기 식별
  4. [스캔]    배당 역전(갭 15센트+) 감지
  5. [실행]    조건 충족 시 폴리마켓 FOK 시장가 매수
  6. [모니터]  경기 종료 후 결과 감지 → 수익/손실 DB 기록

지원 종목: NBA (h2h, max 1.5), NHL (h2h, max 1.5), EPL (spreads, max 1.75)
크레딧: 폴링 1사이클 = ACTIVE_SPORTS 수 × 1크레딧

폴링 주기:
  경기 시작까지 남은 시간에 따라 동적으로 조정
  (24~6h: 4시간  /  6~2h: 2시간  /  2~1h: 30분)
"""

import asyncio
import logging
import logging.handlers
import os
from datetime import datetime, timezone

import aiohttp
from dotenv import load_dotenv

from config import (
    POLL_INTERVALS,
    DEFAULT_POLL_INTERVAL,
    BET_ENTRY_WINDOW_START_HRS,
    LOG_FILE,
    ERROR_LOG_FILE,
    MAX_CONSECUTIVE_LOSSES,
)
from core.db import DB
from core.executor import Executor
from core.matcher import fetch_upcoming_poly_markets, load_team_mapping, match_games
from core.monitor import Monitor
from core.notifier import (
    notify_started,
    notify_stopped,
    notify_opportunity,
    notify_executed,
    notify_failed,
    notify_auto_stopped,
)
from core.odds_fetcher import fetch_all_sports
from core.scanner import scan

load_dotenv()

# ── 로깅 설정 ───────────────────────────────────────────────

def setup_logging() -> None:
    """콘솔 + 파일 로깅 설정."""
    import pathlib
    pathlib.Path("logs").mkdir(exist_ok=True)

    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt=datefmt,
    )

    # 일반 로그 파일
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(fmt, datefmt))

    # 에러 전용 로그 파일
    error_handler = logging.handlers.RotatingFileHandler(
        ERROR_LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(fmt, datefmt))

    root = logging.getLogger()
    root.addHandler(file_handler)
    root.addHandler(error_handler)


log = logging.getLogger(__name__)


# ── 폴링 주기 계산 ──────────────────────────────────────────

def get_poll_interval(matched_games) -> int:
    """매핑된 경기 중 가장 빨리 시작하는 경기 기준으로 폴링 주기 결정.

    경기가 없으면 DEFAULT_POLL_INTERVAL 반환.
    """
    if not matched_games:
        return DEFAULT_POLL_INTERVAL

    min_hrs = min(g.pinnacle.hours_until_start() for g in matched_games)

    for hrs_min, hrs_max, interval in POLL_INTERVALS:
        if hrs_min <= min_hrs < hrs_max:
            return interval

    return DEFAULT_POLL_INTERVAL


# ── 메인 폴링 루프 ──────────────────────────────────────────

async def polling_loop(
    session: aiohttp.ClientSession,
    executor: Executor,
    monitor: Monitor,
    db: DB,
) -> None:
    """Odds API + 폴리마켓 조회 → 갭 감지 → 매수 실행 폴링 루프."""
    team_mapping = load_team_mapping()
    log.info(f"[main] 팀 매핑 로드 완료: {len(team_mapping)}팀")

    while True:
        # 연속 패배 한도 초과 시 중단
        if monitor._stopped:
            log.error("[main] 모니터링 자동 중단됨 — 폴링 루프 종료")
            break

        log.info("=" * 60)
        log.info(f"[main] 폴링 시작: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

        try:
            # 1. Odds API: 전체 활성 종목 Pinnacle 배당 수집
            pinnacle_games = await fetch_all_sports(session)

            if not pinnacle_games:
                log.info("[main] Pinnacle 정배 경기 없음 — 대기")
                await asyncio.sleep(DEFAULT_POLL_INTERVAL)
                continue

            # 2+3. 종목별 Gamma API 조회 + 경기 매핑
            matched_games: list = []
            for sport_id in {g.sport_id for g in pinnacle_games}:
                sport_pinnacle = [g for g in pinnacle_games if g.sport_id == sport_id]
                poly_markets = await fetch_upcoming_poly_markets(session, sport_id)
                if not poly_markets:
                    log.info(f"[main] 폴리마켓 {sport_id.upper()} 예정 경기 없음")
                    continue
                matched = match_games(sport_pinnacle, poly_markets, team_mapping)
                matched_games.extend(matched)

            if not matched_games:
                log.info("[main] 매핑 성공 경기 없음 — 대기")
                await asyncio.sleep(DEFAULT_POLL_INTERVAL)
                continue

            # 4. 배당 역전 감지
            opportunities = await scan(session, matched_games)

            # 5. 조건 충족 경기 매수 실행
            for opp in opportunities:
                # 이미 포지션 보유 중인 토큰 스킵
                if executor.has_position_for_token(opp.token_id):
                    log.debug(f"[main] 이미 포지션 보유: {opp.token_id[-8:]}")
                    continue

                # 텔레그램 알림 (쿨다운 중이면 매수 스킵)
                should_execute = await notify_opportunity(session, opp)
                if not should_execute:
                    continue

                result = await executor.execute(opp)
                if result.success:
                    await notify_executed(session, result)
                elif result.status not in ("skipped",):
                    await notify_failed(session, result)

            # 6. 다음 폴링 주기 계산
            interval = get_poll_interval(matched_games)
            log.info(f"[main] 다음 폴링: {interval // 60}분 후")
            await asyncio.sleep(interval)

        except aiohttp.ClientError as e:
            log.error(f"[main] 네트워크 오류: {e} — 5분 후 재시도")
            await asyncio.sleep(300)
        except Exception as e:
            log.error(f"[main] 예상치 못한 오류: {e}", exc_info=True)
            await asyncio.sleep(300)


# ── 진입점 ──────────────────────────────────────────────────

async def main() -> None:
    setup_logging()
    log.info("=== Polymarket 배당 역전 봇 (polymoly) 시작 ===")

    db       = DB()
    executor = Executor(db)
    monitor  = Monitor(executor, db)

    async with aiohttp.ClientSession() as session:
        # 봇 시작 알림
        await notify_started(session)

        # Executor L2 클라이언트 초기화
        await executor.initialize()

        # 폴링 루프 + 모니터링 루프 병렬 실행
        try:
            await asyncio.gather(
                polling_loop(session, executor, monitor, db),
                monitor.run(session),
            )
        except asyncio.CancelledError:
            log.info("[main] 봇 종료 요청")
        except Exception as e:
            log.error(f"[main] 치명적 오류: {e}", exc_info=True)
        finally:
            consecutive_losses = db.count_consecutive_losses()
            if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                stats = db.get_stats()
                await notify_auto_stopped(session, consecutive_losses, stats)
            else:
                await notify_stopped(session, "봇 종료")

    log.info("=== 봇 종료 ===")


if __name__ == "__main__":
    asyncio.run(main())
