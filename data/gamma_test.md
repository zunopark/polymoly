// python check_gamma_api.py tags
태그                             결과
------------------------------------------------------------
  nba                           ★  5개 이벤트, 123개 마켓
  nhl                           ★  5개 이벤트, 68개 마켓
  nhl-hockey                       0개 이벤트, 0개 마켓
  hockey                        ★  5개 이벤트, 68개 마켓
  ice-hockey                       0개 이벤트, 0개 마켓
  soccer                        ★  5개 이벤트, 203개 마켓
  epl                           ★  5개 이벤트, 120개 마켓
  premier-league                ★  5개 이벤트, 21개 마켓
  english-premier-league           0개 이벤트, 0개 마켓
  football                      ★  5개 이벤트, 69개 마켓
  sports                        ★  5개 이벤트, 183개 마켓

★ = 이벤트 있음 → gamma_tag 후보

// python check_gamma_api.py events nba
원본 JSON (첫 번째 이벤트):
{
  "id": "27830",
  "ticker": "2026-nba-champion",
  "slug": "2026-nba-champion",
  "title": "2026 NBA Champion",
  "description": "This market is to predict the winner of the 2025–26 NBA Finals.",
  "resolutionSource": "",
  "startDate": "2025-06-23T16:04:37.82012Z",
  "creationDate": "2025-06-23T16:04:37.820118Z",
  "endDate": "2026-07-01T00:00:00Z",
  "image": "https://polymarket-upload.s3.us-east-2.amazonaws.com/nba-finals-points-leader-7g2ZEZvMXxLb.jpg",
  "icon": "https://polymarket-upload.s3.us-east-2.amazonaws.com/nba-finals-points-leader-7g2ZEZvMXxLb.jpg",
  "active": true,
  "closed": false,
  "archived": false,
  "new": false,
  "featured": false,
  "restricted": true,
  "liquidity": 16960858.7794,
  "volume": 283194467.451469,
  "openInterest": 0,
  "sortBy": "price",
  "createdAt": "2025-06-19T18:23:26.785626Z",
  "updatedAt": "2026-02-25T09:11:07.713811Z",
  "competitive": 0.9765386587241522,
  "volume24hr": 4452307.970234999,
  "volume1wk": 17792407.096126013,
  "volume1mo": 86021770.90397805,
  "volume1yr": 281227028.2284735,
  "enableOrderBook": true,
  "liquidityClob": 16960858.7794,
  "negRisk": true,
  "negRiskMarketID": "0x11e9a09023ace3097de216497c6fc01a57a57d63df7370543f288b40251dda00",
  "commentCount": 209,
  "markets": [
    {
      "id": "553856",
      "question": "Will the Oklahoma City Thunder win the 2026 NBA Finals?",
      "conditionId": "0x22e7b5e35423e76842dd3a5e1a21d13793811080d5e7b2896d0c001bd5e97d54",
      "slug": "will-the-oklahoma-city-thunder-win-the-2026-nba-finals",
      "resolutionSource": "",
      "endDate": "2026-07-01T00:00:00Z",
      "liquidity": "329332.041",
      "startDate": "2025-06-23T16:01:57.928832Z",
      "image": "https://polymarket-upload.s3.us-east-2.amazonaws.com/nba-finals-points-leader-7g2ZEZvMXxLb.jpg",
      "icon": "https://polymarket-upload.s3.us-east-2.amazonaws.com/nba-finals-points-leader-7g2ZEZvMXxLb.jpg",
      "description": "This market will resolve to “Yes” if the Oklahoma City Thunder win the 2026 NBA Finals. Otherwise, this market will resolve to “No”.\n\nThis market will resolve to “No” if it becomes impossible for this team to win the 2026 NBA Finals based off the rules of the NBA.\n\nThe resolution source for this market will be information from the NBA.",
      "outcomes": "[\"Yes\", \"No\"]",
      "outcomePrices": "[\"0.345\", \"0.655\"]",
      "volume": "4229791.618637",
      "active": true,
      "closed": false,
      "marketMakerAddress": "",
      "createdAt": "2025-06-19T18:23:27.644782Z",
      "updatedAt": "2026-02-25T09:13:11.925565Z",
      "new": false,
      "featured": false,
      "submitted_by": "0x91430CaD2d3975766499717fA0D66A78D814E5c5",
      "archived": false,
      "resolvedBy": "0x2F5e3684cb1F318ec51b00Edba38d79Ac2c0aA9d",
      "restricted": true,
      "groupItemTitle": "Oklahoma City Thunder",
      "groupItemThreshold": "0",
      "questionID": "0x11e9a09023ace3097de216497c6fc01a57a57d63df7370543f288b40251dda00",
      "enableOrder
  ... (truncated)

── _is_win_loss_market 필터 결과 ──
  전체 1797개 마켓 중 통과: 459개  /  제외: 1338개

  [제외된 마켓 질문 샘플]
    - Will the Oklahoma City Thunder win the 2026 NBA Finals?
    - Will the Oklahoma City Thunder win the NBA Western Conference Finals?
    - Will the Atlanta Hawks make the NBA Playoffs?
    - Will the Boston Celtics make the NBA Playoffs?
    - Will the Brooklyn Nets make the NBA Playoffs?
    - Will the Charlotte Hornets make the NBA Playoffs?
    - Will the Chicago Bulls make the NBA Playoffs?
    - Will the Cleveland Cavaliers make the NBA Playoffs?
    - Will the Dallas Mavericks make the NBA Playoffs?
    - Will the Denver Nuggets make the NBA Playoffs?

  [통과한 마켓 질문 샘플]
    + Will the Houston Rockets win the 2026 NBA Finals?
    + Will the New Orleans Pelicans win the 2026 NBA Finals?
    + Will the Toronto Raptors win the 2026 NBA Finals?
    + Will the Chicago Bulls win the 2026 NBA Finals?
    + Will the Cleveland Cavaliers win the 2026 NBA Finals?
    + Will the New York Knicks win the 2026 NBA Finals?
    + Will the Minnesota Timberwolves win the 2026 NBA Finals?
    + Will the Phoenix Suns win the 2026 NBA Finals?
    + Will the Boston Celtics win the 2026 NBA Finals?
    + Will the Indiana Pacers win the 2026 NBA Finals?

── 토큰 구조 확인 ──
  질문: Will the Houston Rockets win the 2026 NBA Finals?
  clobTokenIds: ["50705248713323657762767401378286601907820885259053704401453562452183494476631", "90032510016992035908144344334497034888131477599689435939081777415620747474258"]
  outcomes:     ["Yes", "No"]

── gameStartTime 포맷 샘플 ──
  raw: '2026-01-05 02:30:00+00'
  raw: '2026-01-08 00:30:00+00'
  raw: '2026-01-08 01:00:00+00'



// python check_gamma_api.py events nhl
원본 JSON (첫 번째 이벤트):
{
  "id": "27829",
  "ticker": "2026-nhl-stanley-cup-champion",
  "slug": "2026-nhl-stanley-cup-champion",
  "title": "2026 NHL Stanley Cup Champion ",
  "description": "This market is to predict the winner of the 2025–26 NHL Stanley Cup championship.",
  "resolutionSource": "",
  "startDate": "2025-06-23T16:02:40.856098Z",
  "creationDate": "2025-06-23T16:02:40.856096Z",
  "endDate": "2026-06-30T00:00:00Z",
  "image": "https://polymarket-upload.s3.us-east-2.amazonaws.com/stanley-cup-champion-2026-05M0VRODAaEb.jpg",
  "icon": "https://polymarket-upload.s3.us-east-2.amazonaws.com/stanley-cup-champion-2026-05M0VRODAaEb.jpg",
  "active": true,
  "closed": false,
  "archived": false,
  "new": false,
  "featured": false,
  "restricted": true,
  "liquidity": 3086865.91792,
  "volume": 36356697.686612,
  "openInterest": 0,
  "sortBy": "price",
  "createdAt": "2025-06-19T18:02:50.359238Z",
  "updatedAt": "2026-02-25T09:14:38.797034Z",
  "competitive": 0.9280206317546852,
  "volume24hr": 409462.01665000006,
  "volume1wk": 5640609.57280299,
  "volume1mo": 29081325.921733923,
  "volume1yr": 36131039.39879292,
  "enableOrderBook": true,
  "liquidityClob": 3086865.91792,
  "negRisk": true,
  "negRiskMarketID": "0x7faa974ff857682d64433d5c4dfba46ff51415a68cbd5bd1994248df2d561200",
  "commentCount": 20,
  "markets": [
    {
      "id": "553824",
      "question": "Will the Carolina Hurricanes win the 2026 NHL Stanley Cup?",
      "conditionId": "0xf7b5491e70b477d451afe7d9c1fde4bf1a927e69ff289d294b96df164f6c10f0",
      "slug": "will-the-carolina-hurricanes-win-the-2026-nhl-stanley-cup",
      "resolutionSource": "",
      "endDate": "2026-06-30T00:00:00Z",
      "liquidity": "90509.0316",
      "startDate": "2025-06-23T16:00:27.271901Z",
      "image": "https://polymarket-upload.s3.us-east-2.amazonaws.com/stanley-cup-champion-2026-05M0VRODAaEb.jpg",
      "icon": "https://polymarket-upload.s3.us-east-2.amazonaws.com/stanley-cup-champion-2026-05M0VRODAaEb.jpg",
      "description": "This market will resolve to “Yes” if the Carolina Hurricanes win the 2026 NHL Stanley Cup. Otherwise, this market will resolve to “No”.\n\nThis market will resolve to “No” if it becomes impossible for this team to win the 2026 NHL Stanley Cup based off the rules of the NHL.\n\nThe resolution source for this market will be information from the NHL.\n",
      "outcomes": "[\"Yes\", \"No\"]",
      "outcomePrices": "[\"0.11\", \"0.89\"]",
      "volume": "124370.887885",
      "active": true,
      "closed": false,
      "marketMakerAddress": "",
      "createdAt": "2025-06-19T18:02:51.278733Z",
      "updatedAt": "2026-02-25T09:13:59.923086Z",
      "new": false,
      "featured": false,
      "submitted_by": "0x91430CaD2d3975766499717fA0D66A78D814E5c5",
      "archived": false,
      "resolvedBy": "0x2F5e3684cb1F318ec51b00Edba38d79Ac2c0aA9d",
      "restricted": true,
      "groupItemTitle": "Carolina Hurricanes",
      "groupItemThreshold": "0",
      "questionID": "0x7faa974ff857682d
  ... (truncated)

  ── _is_win_loss_market 필터 결과 ──
  전체 1062개 마켓 중 통과: 859개  /  제외: 203개

  [제외된 마켓 질문 샘플]
    - Will the Boston Bruins make the NHL Playoffs?
    - Will the Buffalo Sabres make the NHL Playoffs?
    - Will the Florida Panthers make the NHL Playoffs?
    - Will the Montreal Canadiens make the NHL Playoffs?
    - Will the Ottawa Senators make the NHL Playoffs?
    - Will the Tampa Bay Lightning make the NHL Playoffs?
    - Will the Toronto Maple Leafs make the NHL Playoffs?
    - Will the Carolina Hurricanes make the NHL Playoffs?
    - Will the Columbus Blue Jackets make the NHL Playoffs?
    - Will the New York Islanders make the NHL Playoffs?

  [통과한 마켓 질문 샘플]
    + Will the Carolina Hurricanes win the 2026 NHL Stanley Cup?
    + Will the Dallas Stars win the 2026 NHL Stanley Cup?
    + Will the Columbus Blue Jackets win the 2026 NHL Stanley Cup?
    + Will the Nashville Predators win the 2026 NHL Stanley Cup?
    + Will the Florida Panthers win the 2026 NHL Stanley Cup?
    + Will the Edmonton Oilers win the 2026 NHL Stanley Cup?
    + Will the Calgary Flames win the 2026 NHL Stanley Cup?
    + Will the Colorado Avalanche win the 2026 NHL Stanley Cup?
    + Will the Vegas Golden Knights win the 2026 NHL Stanley Cup?
    + Will the San Jose Sharks win the 2026 NHL Stanley Cup?

── 토큰 구조 확인 ──
  질문: Will the Carolina Hurricanes win the 2026 NHL Stanley Cup?
  clobTokenIds: ["79397003434468715775480922117285203652110865791390656395657957066470661722480", "40473977441010332007887229299980126707900816205713676157646215720073415416624"]
  outcomes:     ["Yes", "No"]

── gameStartTime 포맷 샘플 ──
  raw: '2026-03-08 00:00:00+00'
  raw: '2026-02-26 00:00:00+00'
  raw: '2026-02-26 00:30:00+00'

// python check_gamma_api.py events soccer

총 50개 이벤트

원본 JSON (첫 번째 이벤트):
{
  "id": "26313",
  "ticker": "2026-fifa-world-cup-which-countries-qualify",
  "slug": "2026-fifa-world-cup-which-countries-qualify",
  "title": "2026 FIFA World Cup: Which countries qualify?",
  "description": "This is a market on which teams will qualify for the 2026 FIFA World Cup. ",
  "resolutionSource": "",
  "startDate": "2025-06-09T12:22:20.935868Z",
  "creationDate": "2025-06-09T12:22:20.935865Z",
  "endDate": "2026-04-12T00:00:00Z",
  "image": "https://polymarket-upload.s3.us-east-2.amazonaws.com/2026-fifa-world-cup-which-countries-qualify-_JWD7xspmdXY.png",
  "icon": "https://polymarket-upload.s3.us-east-2.amazonaws.com/2026-fifa-world-cup-which-countries-qualify-_JWD7xspmdXY.png",
  "active": true,
  "closed": false,
  "archived": false,
  "new": false,
  "featured": false,
  "restricted": true,
  "liquidity": 66687.62983,
  "volume": 794498.634921,
  "openInterest": 0,
  "sortBy": "price",
  "createdAt": "2025-06-08T02:11:18.302464Z",
  "updatedAt": "2026-02-25T09:14:34.56332Z",
  "competitive": 0.9999000099990001,
  "volume24hr": 599.601431,
  "volume1wk": 55091.677143,
  "volume1mo": 103351.619815,
  "volume1yr": 790278.9149210003,
  "enableOrderBook": true,
  "liquidityClob": 66687.62983,
  "negRisk": false,
  "commentCount": 31,
  "markets": [
    {
      "id": "550694",
      "question": "Will Italy qualify for the 2026 FIFA World Cup?",
      "conditionId": "0xd8c3fff562711af557abca5e7367dbb892b1d79419b039b6f185e49f21ec6f71",
      "slug": "will-italy-qualify-for-the-2026-fifa-world-cup",
      "resolutionSource": "",
      "endDate": "2026-04-12T00:00:00Z",
      "liquidity": "3002.3767",
      "startDate": "2025-06-09T12:21:53.041794Z",
      "image": "https://polymarket-upload.s3.us-east-2.amazonaws.com/2026-fifa-world-cup-which-countries-qualify-_JWD7xspmdXY.png",
      "icon": "https://polymarket-upload.s3.us-east-2.amazonaws.com/2026-fifa-world-cup-which-countries-qualify-_JWD7xspmdXY.png",
      "description": "This is a market on which teams will qualify for the 2026 FIFA World Cup.\n\nIf at any point it becomes impossible for this team to qualify for the FIFA World Cup based on the rules of FIFA (e.g. they cannot reach the required number of points to advance from its group or qualify for playoffs), this market will resolve immediately to “No”.\n\nIf the 2026 FIFA World Cup is permanently canceled or the qualifying stage has not been completed by September 30, 2026, 11:59 PM this market will resolve to “No”.\n\nThe resolution source for this market will be FIFA.  (https://www.fifa.com/en/tournaments/mens/worldcup).",
      "outcomes": "[\"Yes\", \"No\"]",
      "outcomePrices": "[\"0.62\", \"0.38\"]",
      "volume": "203694.724082",
      "active": true,
      "closed": false,
      "marketMakerAddress": "",
      "createdAt": "2025-06-08T02:11:19.124909Z",
      "updatedAt": "2026-02-25T09:17:08.576495Z",
      "new": false,
      "featured": false,
      "submitted_by": "0x91430CaD2d3975766499717fA0D66A78D814E5c5",
  ... (truncated)

  ── _is_win_loss_market 필터 결과 ──
  전체 1189개 마켓 중 통과: 542개  /  제외: 647개

  [제외된 마켓 질문 샘플]
    - Will Italy qualify for the 2026 FIFA World Cup?
    - Will Netherlands qualify for the 2026 FIFA World Cup?
    - Will Belgium qualify for the 2026 FIFA World Cup?
    - Will Croatia qualify for the 2026 FIFA World Cup?
    - Will Colombia qualify for the 2026 FIFA World Cup?
    - Will Uruguay qualify for the 2026 FIFA World Cup?
    - Will Saudi Arabia qualify for the 2026 FIFA World Cup?
    - Will Australia qualify for the 2026 FIFA World Cup?
    - Will Oman qualify for the 2026 FIFA World Cup?
    - Will Sweden qualify for the 2026 FIFA World Cup?

  [통과한 마켓 질문 샘플]
    + Will Spain win the 2026 FIFA World Cup?
    + Will New Zealand win the 2026 FIFA World Cup?
    + Will Switzerland win the 2026 FIFA World Cup?
    + Will England win the 2026 FIFA World Cup?
    + Will Team AM win the 2026 FIFA World Cup?
    + Will France win the 2026 FIFA World Cup?
    + Will South Korea win the 2026 FIFA World Cup?
    + Will Haiti win the 2026 FIFA World Cup?
    + Will Brazil win the 2026 FIFA World Cup?
    + Will Jordan win the 2026 FIFA World Cup?

── 토큰 구조 확인 ──
  질문: Will Spain win the 2026 FIFA World Cup?
  clobTokenIds: ["4394372887385518214471608448209527405727552777602031099972143344338178308080", "112680630004798425069810935278212000865453267506345451433803052322987302357330"]
  outcomes:     ["Yes", "No"]

── gameStartTime 포맷 샘플 ──
  raw: '2025-12-19 17:30:00+00'
  raw: '2025-12-21 14:50:00+00'
  raw: '2025-12-21 17:30:00+00'