"""
config.py - 전역 파라미터 중앙 관리

모든 튜닝 가능한 상수를 이 파일에서 관리.
core/ 모듈들은 이 파일에서 import 해서 사용.
"""

# ── API 엔드포인트 ──────────────────────────────────────────
GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_HOST  = "https://clob.polymarket.com"
CHAIN_ID   = 137   # Polygon mainnet

ODDS_API_BASE   = "https://api.the-odds-api.com/v4"
ODDS_BOOKMAKERS = "pinnacle"
ODDS_SPORT      = "basketball_nba"   # MLB 추가 예정

# ── 실행 조건 (4가지 모두 충족해야 매수) ────────────────────
MAX_PINNACLE_ODDS    = 1.55   # 배당 상한선
MAX_POLYMARKET_PRICE = 0.50   # 폴리마켓 역배 기준 (50센트 미만)
GAP_THRESHOLD        = 0.15   # 최소 갭 크기
MIN_LIQUIDITY_SHARES = 30     # 최소 유동성 (shares)

# ── 경기 진입 시간 ───────────────────────────────────────────
BET_ENTRY_WINDOW_HRS   = 24   # 경기 시작 최대 N시간 전까지만 진입
BET_ENTRY_DEADLINE_HRS = 1    # 경기 시작 N시간 전 마감 (이 이하면 스킵)

# ── 베팅 금액 ────────────────────────────────────────────────
MAX_BET_USDC = 30
MIN_BET_USDC = 5
MAX_POSITIONS = 5

# 갭 크기별 베팅 금액 [(gap_min, gap_max, usdc)]
BET_SIZE_TIERS = [
    (0.15, 0.20, 10),   # 15~20센트 → $10
    (0.20, 0.30, 20),   # 20~30센트 → $20
    (0.30, 1.00, 30),   # 30센트 이상 → $30
]

# ── 손실 관리 ────────────────────────────────────────────────
MAX_CONSECUTIVE_LOSSES = 3   # 연속 N패 시 자동 중단

# ── 폴링 주기 (초) ───────────────────────────────────────────
POLL_INTERVAL = 3600   # 기본 1시간

# ── Odds API 크레딧 제어 ─────────────────────────────────────
CREDITS_WARNING_THRESHOLD = 50     # 잔여 이하면 텔레그램 경고 발송
CREDITS_MIN_RESERVE       = 10     # 잔여 이하면 Odds API 호출 중단
DAILY_MAX_API_CALLS       = 100    # 하루 최대 Odds API 호출 횟수

# ── 파일 경로 ────────────────────────────────────────────────
DB_PATH           = "data/positions.db"
TEAM_MAPPING_PATH = "data/team_mapping.json"
CREDITS_STATE_PATH = "data/credits.json"
LOG_FILE          = "logs/bot.log"
ERROR_LOG_FILE    = "logs/error.log"
