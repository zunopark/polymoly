# The Odds API v4 — 참고 문서

## 기본 정보

```
Host:    https://api.the-odds-api.com
Version: v4
인증:    모든 요청에 apiKey 쿼리 파라미터 필요
```

---

## 크레딧 소비 공식

```
크레딧 = 마켓 수 × 리전 수 × 경기 수
```

우리 봇 기준 (h2h 1개 × eu 1개 × Pinnacle 지정):
```
GET /odds 1회 = 1 크레딧
GET /sports = 0 크레딧 (무료)
GET /events = 0 크레딧 (무료)
GET /scores = 1 크레딧 (daysFrom 없을 때), 2 크레딧 (daysFrom 있을 때)
```

응답 헤더로 크레딧 현황 확인 가능:
```
x-requests-remaining  남은 크레딧
x-requests-used       사용한 크레딧
x-requests-last       마지막 호출 비용
```

---

## 우리 봇에서 사용할 엔드포인트 3개

---

### 1. GET /sports — 종목 목록 조회 (무료)

NBA sport_key 확인용. 크레딧 소비 없음.

```
GET https://api.the-odds-api.com/v4/sports/?apiKey={apiKey}
```

**우리 봇 관련 sport_key**
```
basketball_nba  → NBA
baseball_mlb    → MLB (추후 추가 예정)
```

**응답 예시**
```json
{
  "key": "basketball_nba",
  "group": "Basketball",
  "title": "NBA",
  "description": "US Basketball",
  "active": true,
  "has_outrights": false
}
```

---

### 2. GET /odds — 배당 조회 (핵심)

Pinnacle NBA 예정 경기 배당 수집. 봇의 핵심 호출.

```
GET https://api.the-odds-api.com/v4/sports/{sport}/odds
    ?apiKey={apiKey}
    &bookmakers=pinnacle
    &markets=h2h
    &oddsFormat=decimal
    &dateFormat=iso
```

**파라미터**

| 파라미터 | 값 | 설명 |
|---|---|---|
| sport | basketball_nba | NBA 고정 |
| apiKey | 환경변수 | ODDS_API_KEY |
| bookmakers | pinnacle | Pinnacle 단일 지정 (regions 대신 사용) |
| markets | h2h | 승/패 배당만 (moneyline) |
| oddsFormat | decimal | 소수 배당 (1.5, 2.0 형식) |
| dateFormat | iso | ISO 8601 시간 형식 |
| commenceTimeFrom | (선택) | 경기 시작 시간 필터 시작 |
| commenceTimeTo | (선택) | 경기 시작 시간 필터 종료 |

> bookmakers 파라미터로 Pinnacle을 직접 지정하면
> regions 파라미터 없이도 동작하고 크레딧이 1로 고정됨

**응답 구조**
```json
[
  {
    "id": "경기 고유 ID",
    "sport_key": "basketball_nba",
    "commence_time": "2024-01-15T00:10:00Z",
    "home_team": "Los Angeles Lakers",
    "away_team": "Boston Celtics",
    "bookmakers": [
      {
        "key": "pinnacle",
        "title": "Pinnacle",
        "last_update": "2024-01-14T20:00:00Z",
        "markets": [
          {
            "key": "h2h",
            "outcomes": [
              {
                "name": "Los Angeles Lakers",
                "price": 2.15
              },
              {
                "name": "Boston Celtics",
                "price": 1.75
              }
            ]
          }
        ]
      }
    ]
  }
]
```

**핵심 필드**
```
id             → 경기 ID (폴리마켓 매핑 키로 사용)
commence_time  → 경기 시작 시간 UTC (배팅 마감 기준)
home_team      → 홈팀 전체 이름 (팀명 정규화 필요)
away_team      → 원정팀 전체 이름 (팀명 정규화 필요)
price          → 소수 배당 (1.5 이하만 진입 대상)
```

**배당 → 임플라이드 확률 변환**
```python
implied_prob = 1 / price  # 소수 배당 기준
# 예) price=1.4 → 1/1.4 = 0.714 → 71.4센트
```

---

### 3. GET /scores — 경기 결과 조회

경기 종료 후 결과 확인 및 포지션 정산용.

```
GET https://api.the-odds-api.com/v4/sports/{sport}/scores
    ?apiKey={apiKey}
    &daysFrom=1
    &dateFormat=iso
```

**파라미터**

| 파라미터 | 값 | 설명 |
|---|---|---|
| sport | basketball_nba | NBA 고정 |
| daysFrom | 1~3 | 며칠 전 완료 경기까지 포함 |

**응답 구조**
```json
[
  {
    "id": "경기 ID",
    "commence_time": "2022-02-06T03:10:38Z",
    "completed": true,
    "home_team": "Sacramento Kings",
    "away_team": "Oklahoma City Thunder",
    "scores": [
      { "name": "Sacramento Kings", "score": "113" },
      { "name": "Oklahoma City Thunder", "score": "103" }
    ],
    "last_update": "2022-02-06T05:18:19Z"
  }
]
```

**핵심 필드**
```
id         → /odds 응답의 id와 동일 (매핑 키)
completed  → true이면 경기 종료
scores     → 팀별 최종 점수 (승패 판단용)
```

> scores가 null이면 경기 미시작 또는 데이터 미수집 상태

---

## Python 연동 예시

```python
import aiohttp
import os

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4"

# NBA Pinnacle 배당 조회
async def fetch_pinnacle_nba_odds(session):
    url = f"{BASE_URL}/sports/basketball_nba/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "bookmakers": "pinnacle",
        "markets": "h2h",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    async with session.get(url, params=params) as resp:
        # 크레딧 현황 확인
        remaining = resp.headers.get("x-requests-remaining")
        print(f"크레딧 잔여: {remaining}")
        return await resp.json()

# 배당 → 임플라이드 확률 변환
def to_implied_prob(decimal_odds: float) -> float:
    return round(1 / decimal_odds, 4)

# 경기 결과 조회
async def fetch_nba_scores(session, days_from=1):
    url = f"{BASE_URL}/sports/basketball_nba/scores"
    params = {
        "apiKey": ODDS_API_KEY,
        "daysFrom": days_from,
        "dateFormat": "iso",
    }
    async with session.get(url, params=params) as resp:
        return await resp.json()
```

---

## 주의사항

**Pinnacle 미포함 경기 처리**
Pinnacle이 배당을 제공하지 않는 경기는 bookmakers 배열이 비어있음.
반드시 bookmakers 배열 길이를 확인 후 처리.

```python
if not game.get("bookmakers"):
    continue  # Pinnacle 데이터 없는 경기 스킵
```

**경기 종료 판단**
commence_time이 현재 시각보다 이전이면 경기 시작된 상태.
completed 필드로 완전 종료 여부 확인.

**Rate Limit (429 에러)**
요청이 너무 빠르면 429 응답.
재시도 로직에 3~5초 간격 대기 필요.