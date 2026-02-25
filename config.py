"""
config.py - 전역 파라미터 중앙 관리

모든 튜닝 가능한 상수를 이 파일에서 관리.
core/ 모듈들은 이 파일에서 import해서 사용.
"""

# ── API 엔드포인트 ──────────────────────────────────────────
GAMMA_BASE  = "https://gamma-api.polymarket.com"
CLOB_HOST   = "https://clob.polymarket.com"
CHAIN_ID    = 137   # Polygon mainnet

ODDS_API_BASE   = "https://api.the-odds-api.com/v4"
ODDS_BOOKMAKERS = "pinnacle"
# regions 파라미터 불필요: bookmakers 직접 지정 시 1크레딧 고정 (docs 참고)

# ── 종목별 설정 ──────────────────────────────────────────────
# E스포츠: Odds API sports 목록에 esports 키 없음 → 지원 불가, 제외
#
# soccer spreads 주의:
#   spreads 배당은 핸디캡으로 균형화되어 항상 1.83~2.12 수준으로 수렴.
#   h2h 1.5 이하 기준이 spreads에서는 현실적으로 불가능.
#   max_pinnacle_odds를 1.75로 완화 적용 (핸디캡 후에도 한쪽이 유리한 경우만).
#   또한 0.5 단위 라인만 허용 (0.25/0.75 쿼터핸디는 이진 결과 미보장).
SPORTS_CONFIG: dict[str, dict] = {
    "nba": {
        "sport_key":          "basketball_nba",
        "markets":            "h2h",
        "gamma_tag":          "nba",
        "label":              "NBA",
        "max_pinnacle_odds":  1.5,
        "is_handicap":        False,
    },
    "nhl": {
        "sport_key":          "icehockey_nhl",
        "markets":            "h2h",
        "gamma_tag":          "nhl",
        "label":              "NHL",
        "max_pinnacle_odds":  1.5,
        "is_handicap":        False,
    },
    "epl": {
        "sport_key":          "soccer_epl",
        "markets":            "spreads",
        "gamma_tag":          "epl",
        "label":              "EPL",
        "max_pinnacle_odds":  1.75,      # spreads 특성 반영 완화값
        "is_handicap":        True,
    },
}

# 실제 운영할 종목 목록 (비활성화 시 여기서 제거)
ACTIVE_SPORTS = ["nba", "nhl", "epl"]

# ── 핵심 필터 조건 (CLAUDE.md §핵심 조건) ──────────────────
# max_pinnacle_odds는 종목별로 SPORTS_CONFIG에서 관리
MAX_POLYMARKET_PRICE = 0.50   # 폴리마켓 역배 기준 (이 미만만)
GAP_THRESHOLD        = 0.15   # 배당 역전 감지 임계값 (15센트)
MIN_LIQUIDITY_SHARES = 50     # 폴리마켓 최소 유동성 (shares)

# ── 베팅 진입 시간 창 ───────────────────────────────────────
BET_ENTRY_WINDOW_START_HRS = 24   # 경기 시작 N시간 전부터 모니터링
BET_ENTRY_WINDOW_END_HRS   = 1    # 경기 시작 N시간 전에 배팅 마감

# ── 베팅 금액 ───────────────────────────────────────────────
MAX_BET_USDC = 30   # 단일 베팅 최대 금액 (USDC)
MIN_BET_USDC = 5    # 단일 베팅 최소 금액 (USDC)
MAX_POSITIONS = 3   # 동시 최대 포지션 수

# 갭 크기별 베팅 금액 (센트 단위)
# [(gap_min, gap_max, bet_usdc), ...]  마지막 항목 = gap_max 이상
BET_SIZE_TIERS = [
    (0.15, 0.20, 10),   # 15~20센트 갭: $10
    (0.20, 0.30, 20),   # 20~30센트 갭: $20
    (0.30, 1.00, 30),   # 30센트 이상:  $30
]

# ── 폴링 주기 (실전 운영용) ────────────────────────────────
# 경기 시작까지 남은 시간에 따라 폴링 주기 조정
# [(hours_to_start_min, hours_to_start_max, poll_interval_secs)]
POLL_INTERVALS = [
    (6,  24, 14400),   # 6~24시간 전: 4시간마다 (14400초)
    (2,  6,  7200),    # 2~6시간 전: 2시간마다 (7200초)
    (1,  2,  1800),    # 1~2시간 전: 30분마다 (1800초)
]
DEFAULT_POLL_INTERVAL = 14400   # 위 조건 외: 4시간마다

# ── 손실 관리 ───────────────────────────────────────────────
MAX_CONSECUTIVE_LOSSES = 3   # 연속 N패 시 자동 중단

# ── 포지션 모니터링 주기 ────────────────────────────────────
MONITOR_INTERVAL = 600   # 포지션 상태 점검 주기 (초, 10분)

# ── 파일 경로 ───────────────────────────────────────────────
DB_PATH           = "data/positions.db"
TEAM_MAPPING_PATH = "data/team_mapping.json"
LOG_FILE          = "logs/bot.log"
ERROR_LOG_FILE    = "logs/error.log"
