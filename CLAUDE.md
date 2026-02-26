# Polymarket Odds Arbitrage Bot

## 중요
- 코드 분석 및 수정은 serena 를 이용할 것.

## 프로젝트 개요
전통 배팅사이트(Pinnacle)의 배당과 폴리마켓 예측 시장의 배당을 비교하여
배당 역전 현상이 발생한 경기를 자동 감지하고 폴리마켓에서 매수를 실행하는 봇.

---

## 참고 문서
- `docs/polymarket/*` — 폴리마켓 시장 조회 API 연동 및 사용법
- `docs/odds-api/overview.md` — Odds API 연동 및 사용법

## odds-api team mapping
- data/team_mapping.json : odds-api 팀명 확인

---

## 핵심 전략
전통 배팅사이트는 전문 오즈메이커가 수십 년 데이터 기반으로 배당을 설정함.
폴리마켓은 사람들의 호가로 움직이기 때문에 초기 배당 설정이 다를 수 있음.
이 갭을 감지하여 폴리마켓에서 저평가된 쪽을 매수하는 전략.
Pinnacle에서는 정배(적중 확률이 높음)이나 폴리마켓에서는 역배인 경우를 노림.

---

## 실행 조건 (4가지 모두 충족해야 매수)

### 개발 완료 후 테스트 모니터링 운영(소액 매수)
| 조건 | 기준 | 설명 |
|------|------|------|
| 조건 1 | Pinnacle 배당 <= 1.7 | 실제 승리 확률 67% 이상인 강한 정배만 |
| 조건 2 | 폴리마켓 현재가 < 50센트 | 폴리마켓에서 역배 상태인 것만 |
| 조건 3 | 갭 >= 10센트 | 수수료/마진 제거 후에도 기댓값 플러스 |
| 조건 4 | 폴리마켓 Shares >= 30 | 유동성 확인, 슬리피지 방지 |

### 실제 운영
| 조건 | 기준 | 설명 |
|------|------|------|
| 조건 1 | Pinnacle 배당 <= 1.5 | 실제 승리 확률 67% 이상인 강한 정배만 |
| 조건 2 | 폴리마켓 현재가 < 50센트 | 폴리마켓에서 역배 상태인 것만 |
| 조건 3 | 갭 >= 15센트 | 수수료/마진 제거 후에도 기댓값 플러스 |
| 조건 4 | 폴리마켓 Shares >= 50 | 유동성 확인, 슬리피지 방지 |

---

## 전략 플로우

```
[1단계] Odds API → Pinnacle NBA 예정 경기 배당 수집
        배당 1.5 이하 경기만 필터링

[2단계] 폴리마켓 → 동일 경기 마켓 매핑
        팀명 정규화 + 경기 시간 매칭으로 동일 경기 식별

[3단계] 배당 역전 감지 (핵심 로직)
        Pinnacle 임플라이드 확률(센트) - 폴리마켓 현재가 >= 15센트
        폴리마켓 현재가 < 50센트 확인

[4단계] 유동성 필터
        폴리마켓 해당 마켓 Shares >= 50 확인

[5단계] 조건 모두 충족 시 폴리마켓 시장가 매수 실행
        갭 크기에 따라 베팅 금액 차등 적용
```

---

## 배당 변환 공식

```
임플라이드 확률(센트) = (1 / 배당) × 100

1.1배당 → 91센트  (기회 거의 없음)
1.2배당 → 83센트
1.3배당 → 77센트
1.4배당 → 71센트
1.5배당 → 67센트  ← 진입 하한선
1.6배당 → 63센트  (진입 안 함)
2.0배당 → 50센트  (동전 던지기, 제외)
```

---

## 핵심 파라미터

| 파라미터 | 값 | 설명 |
|---|---|---|
| MAX_PINNACLE_ODDS | 1.5 | Pinnacle 배당 상한선 |
| MAX_POLYMARKET_PRICE | 0.50 | 폴리마켓 역배 기준 (50센트 미만) |
| GAP_THRESHOLD | 0.15 | 최소 갭 크기 (15센트) |
| MIN_LIQUIDITY_SHARES | 50 | 폴리마켓 최소 유동성 |
| MAX_BET_USDC | 30 | 단일 베팅 최대 금액 |
| MIN_BET_USDC | 5 | 단일 베팅 최소 금액 |
| MAX_POSITIONS | 3 | 동시 최대 포지션 수 |
| BET_ENTRY_DEADLINE | 경기 시작 1시간 전 | 배팅 마감 시점 |

### 갭 크기별 베팅 금액
```
15~20센트 → $10~20
20~30센트 → $20~30
30센트 이상 → $30 (최대)
```

---

## 파일 구조

```
polymarket-odds-bot/
├── CLAUDE.md
├── main.py              # 진입점, 전체 루프
├── config.py            # 파라미터 설정
├── .env
├── requirements.txt
├── core/
│   ├── odds_fetcher.py  # Odds API 호출, Pinnacle 배당 수집
│   ├── matcher.py       # 경기 매핑 (Odds API ↔ 폴리마켓)
│   ├── scanner.py       # 배당 역전 감지 엔진
│   ├── executor.py      # 폴리마켓 매수 실행
│   ├── monitor.py       # 포지션 모니터링
│   └── notifier.py      # 텔레그램 알림
├── data/
│   └── team_mapping.json  # 팀명 정규화 딕셔너리
└── docs/
    ├── polymarket/
    └── odds-api/
        └── overview.md
```

---

## 아래 환경변수 (.env) 세팅 완료

```
FUNDER_ADDRESS=
PRIVATE_KEY=
POLY_SIGNATURE_TYPE=
POLY_API_KEY=                                                                              
POLY_SECRET=                                                                          
POLY_PASSPHRASE=
ODDS_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

```

---

## 개발 상태

- [x] 프로젝트 초기 세팅
  - [x] config.py, requirements.txt, team_mapping.json (NBA 30팀)
  - [x] core/ 전체 파일 스켈레톤 작성 완료
- [x] 통합 테스트 (Odds API + Gamma API 실제 응답 검증)
  - [x] Pinnacle NBA 배당 수집 확인 (mock 검증 완료)
  - [x] 폴리마켓 NBA 마켓 조회 확인 ("X vs. Y" 형식 필터 검증 완료)
  - [x] 팀명 정규화 + 매핑 동작 확인 (mock 검증 완료)
  - [x] 갭 감지 동작 확인 (시뮬레이션 검증 완료)
  - [x] Odds API 호출 빈도 제어 (한 달 20,000 크레딧 제한)
- [x] 디버깅/모니터링 텔레그램 알림 추가
  - [x] 폴링 시작, 정배 없음, 마켓 없음, 매핑 실패, 기회 없음
  - [x] 크레딧 경고, 네트워크/예상치 못한 오류
  - [x] 포지션 정산 알림 (monitor.py notify_settled 연결 — 미호출 버그 수정)
- [ ] 폴리마켓 매수 실행 검증 (core/executor.py)
  - [x] executor.py 버그 수정 완료 (아래 참고)
  - [x] test_executor.py 작성 완료 (dry-run / --confirm 모드)
  - [ ] **SSL 문제로 테스트 중단** — py-clob-client L2 인증 호출 시 "Request exception!" 발생
  - [ ] SSL 해결 후: `python test_executor.py --confirm --amount 5` 로 실제 매수 테스트
- [ ] 소액으로 먼저 실전 운영 시작 (최대 배팅 금액 $10~30)
- [ ] db.py 배팅 기록 확인 기능 추가
- [ ] NHL 추가 (NBA 안정화 후)
- [ ] EPL 추가 (NBA 안정화 후)

---

## 현재 블로커: SSL / 네트워크 이슈

### 증상
`py-clob-client` 의 L2 인증 API 호출 (`get_api_keys`, `get_balance_allowance` 등)에서
`PolyApiException[status_code=None, error_message=Request exception!]` 발생.

### 원인 추정
- py-clob-client 내부는 `requests` 라이브러리 사용 (aiohttp 아님)
- test_integration.py 의 SSL 우회 (`ctx.check_hostname=False`) 가 적용되지 않음
- macOS VPN / 방화벽 / 지역 차단(Geoblock) 가능성

### 해결 방법 후보
1. **VPN 끄거나 켜기** — 지역 차단 여부 확인 (미국 IP 필요할 수 있음)
2. **requests SSL 우회 패치** — py-clob-client 내부 session에 `verify=False` 적용
   ```python
   import requests, urllib3
   urllib3.disable_warnings()
   requests.packages.urllib3.disable_warnings()
   # ClobClient 초기화 후:
   client._session.verify = False  # 내부 session 접근 가능 시
   ```
3. **환경 변수로 SSL 우회**
   ```bash
   PYTHONHTTPSVERIFY=0 python test_executor.py
   ```
4. **py-clob-client 소스 직접 확인** — session 생성 방식 파악 후 패치

### 다음 재개 시 순서
1. SSL 문제 해결
2. `python test_executor.py` (dry-run) → L2 인증 + 잔고 확인
3. `python test_executor.py --confirm --amount 5` → 실제 $5 FOK 매수
4. DB 기록 확인 (`data/positions.db`)
5. CLAUDE.md 체크박스 업데이트