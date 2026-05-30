# 🐛 알려진 버그 (Known Bugs)

작업 시작 시점 기록: 2026-05-09

---

## BUG-1. 연금복권 720+ 2매 이상 구매 시 메시지에 번호가 1개만 포함됨

- **증상**: `LOTTO720_GAMES=2` 이상으로 설정해 정상 구매되어도 Telegram 알림 메시지의 `🎫 선택 번호` 영역에 자동번호가 1게임만 표시되거나, 일부 게임은 `(자동)` 으로만 나오고 6자리 번호가 빠짐.
- **재현**:
  1. `LOTTO720_GAMES=2` (또는 그 이상)으로 `purchase_all.py` 실행
  2. 구매 자체는 성공하고 잔액도 정상 차감
  3. 알림 메시지에 A/B 두 줄이 나오긴 하지만 `numbers[0]` 만 채워지고 `numbers[1]` 이 비어 `B 〇조 (자동)` 으로만 표시
- **원인 추정**: `src/lotto720.py`의 `_extract_720_numbers()` / `_PENSION_NUM_EXTRACT_JS`가 자동번호를 N번 클릭한 뒤 **마지막 게임 1건**만 잡거나, "선택된 번호" 영역의 누적된 N게임을 모두 수집하지 못하고 중복 제거(`seen.has`)에 걸려 1건으로 줄어드는 케이스가 의심됨. 추출 결과 `numbers` 길이가 `num_games`보다 작은 채로 `notify`에 전달됨.
- **영향 범위**: `src/lotto720.py` (추출 로직), `src/notify.py:send_lotto720_notification` (groups 길이만큼 numbers 인덱싱).

## BUG-2. 720+ 당첨 조회가 항상 실패 (`get_720_winning_numbers` 모든 URL 실패)

- **증상**: `check_winning.py` 실행 시 720 당첨 조회 단계에서 시도하는 모든 URL이 실패해 `❌ 720+ 당첨번호 모든 URL 실패` 로그가 남고, 알림에는 `0회차` / `당첨번호 없음` 으로 전송됨.
- **재현**:
  1. `check_winning.py` 실행 (또는 `CHECK_TARGET=720`)
  2. 콘솔에 `🌐 720+ 결과 페이지 시도: ...` 가 후보 URL 수만큼 찍힌 뒤 모두 실패
- **원인 추정**:
  - 시도 URL 중 일부가 더 이상 유효하지 않거나(`gameResult.do?method=win720` 응답 구조 변경), 결과 페이지 DOM 구조가 바뀌어 `_PENSION_EXTRACT_JS`의 정규식/셀렉터(`1등|당첨번호`, `[1-5]\s*조`, `.win_result .num span` 등)가 매칭되지 않음.
  - 720+ 결과는 공식 JSON API(`common.do?method=getPension720Number&Round=...` 등) 호출이 가능할 수 있는데 현재는 DOM 스크래핑만 시도.
- **영향 범위**: `src/check_winning.py:get_720_winning_numbers`, `_PENSION_EXTRACT_JS`.

## BUG-3. 구매 매수와 메시지 내 번호 개수 불일치

- **요구사항**: 구매한 매수만큼의 번호가 알림 메시지에 모두 포함되어야 함. (예: `LOTTO720_GAMES=3` → A/B/C 3매 모두 6자리 번호가 표시)
- **현재 상태**: BUG-1과 같은 원인으로 720+에서 매수 < 표시 번호 수 발생. 645도 영수증 추출 실패 시 `manual_numbers`만 fallback되어 자동 게임 수만큼 빈 줄이 생길 수 있음(잠재적).
- **수용 기준 (Acceptance)**:
  - `LOTTO720_GAMES=N` 으로 구매 시 알림의 `🎫 선택 번호` 영역에 정확히 N줄이 출력되며, 모든 줄에 `〇조 D D D D D D` 6자리가 채워짐.
  - 645의 경우도 `auto_games + len(manual_numbers)` 와 메시지에 출력되는 게임 수가 일치.
- **영향 범위**: 위 BUG-1 + `src/purchase_all.py:buy_lotto645` 영수증/구매내역 fallback 추출.

## BUG-4. 로또 6/45 다매 구매 시 메시지 번호가 매수보다 적게 표시되는 케이스

- **증상**: `AUTO_GAMES=5` 또는 수동+자동 혼합 시, 알림의 `🎱 선택 번호` 영역에 일부 게임의 번호가 누락되거나 매수보다 적게 표시될 수 있음.
- **재현**:
  1. `AUTO_GAMES=5` 로 645 구매 (또는 수동 1매 + 자동 4매)
  2. 구매 자체는 성공
  3. 알림에 5게임이 모두 표시되어야 하는데 1~4게임만 나오는 경우 발생
- **원인 추정**:
  - `purchase_all.py:buy_lotto645` 는 구매 후 `popReceipt`/`pop_data` 등의 영수증 팝업에서 번호를 추출.
  - 영수증 팝업 셀렉터/타이밍이 어긋나면 일부만 추출되거나 0게임 추출.
  - fallback인 구매내역 페이지(`mylotteryledger`)도 동일 셀렉터에 의존하여 부족한 결과를 가져올 수 있음.
  - 최종 fallback은 `manual_numbers` 만 사용 → 자동 게임 부분이 빈 채로 알림 전송.
- **수정 방향**:
  - 구매 *직전* 에 선택 영역(`#selectNumArea`, `#reportRow`, `#tblNum` 등)에서 선택된 게임을 1차 추출하여 보관 (가장 신뢰도 높음).
  - 영수증/구매내역 추출이 부족하거나 실패하면 1차 추출 결과로 보강.
  - 결과적으로 `auto_games + len(manual_numbers)` 게임 수와 일치.
- **영향 범위**: `src/purchase_all.py:buy_lotto645`, `src/notify.py:send_lotto645_notification` (이미 정상, 입력만 보정).

---

## BUG-5. Dockerfile `apt-key` 사용으로 NAS 빌드 실패 → 2026-05-15 22:00 정기 구매 전체 실패

- **증상**: Synology 작업 스케줄러로 `docker-compose up --build lotto-all` 실행 시 빌드 단계 `[lotto-all 3/8]` 에서 exit code 127, `/bin/sh: 1: apt-key: not found` 로 종료. 컨테이너가 시작조차 안 되어 Telegram 알림 미발송.
- **재현**:
  1. `docker-compose up --build lotto-all`
  2. apt 패키지 설치 단계 진행 후 `apt-key add -` 호출 시점에 실패
- **원인**: `addc574 chore(docker): Google Chrome stable 설치 추가` 커밋에서 `apt-key add -` 사용. python:3.9-slim 베이스가 Debian 13(trixie) 로 업그레이드되면서 `apt-key` 가 제거됨. 게다가 코드(`purchase_all.py`, `check_winning.py`)에 `channel="chrome"` 설정이 없어 설치한 google-chrome-stable 자체가 미사용 상태였음.
- **수정**: Dockerfile 에서 google-chrome 설치 블록 전체 제거. `xvfb/xauth/fonts-noto-cjk/ca-certificates` 만 남김. Playwright 번들 chromium 그대로 사용.
- **영향 범위**: `Dockerfile`. 차후 실 Chrome 도입 필요 시 `apt-key` 대신 `/etc/apt/keyrings/` + `signed-by=` 방식으로 재추가하고 코드에 `channel="chrome"` 도 함께 설정해야 함.

---

## 2026-05-29 재보고 (사용자) + 근본 원인 분석

사용자 재보고: ① 720 당첨 확인 실패(BUG-2 지속), ② 645 구매 후 알림에 번호가 **1게임만** 전송됨(BUG-4 지속). commit `2969681` 의 DOM 셀렉터 보강만으로는 해결 안 됨.

### BUG-4 근본 원인 (645 알림 번호 1개)
- 645 자동 구매의 **권위 있는 번호 소스**는 구매 AJAX 응답 `https://ol.dhlottery.co.kr/olotto/game/execBuy.do` 의 `result.arrGameChoiceNum` 배열임. 각 원소 = 게임 1건(번호 6개 + 끝자리 모드숫자 1=수동/2=반자동/3=자동). 매수만큼 항상 정확히 들어옴.
- 현재 코드는 이 응답을 **전혀 안 보고** 영수증 팝업 DOM 스크래핑에만 의존.
- 영수증 추출의 1차(row) 패스 셀렉터에 `'table tr'`, `'#tblNum tr'`, `.tbl_display tr` 등 **페이지 전역 테이블**이 포함됨 → 게임 페이지에 남아있는 무관한 테이블(예: 최근 당첨번호 위젯) 한 행(6볼)을 잡아 `games=1` 로 조기 확정 → 더 정확한 컨테이너/전역 패스가 `if games.length===0` 가드로 **스킵**됨 → 1게임만 반환.
- **수정**: `buy_lotto645` 에서 `#btnBuy` 클릭 전 `execBuy.do` 응답을 캡처 → `arrGameChoiceNum` 파싱(권위 소스). `len==total_games` & 각 게임 6개 1~45 검증 통과 시 우선 사용. 미달 시에만 기존 DOM/ledger/pre_purchase fallback. (검증 게이트로 절대 악화 없음)

### BUG-2 근본 원인 (720 당첨 조회)
- 결과 페이지는 `https://(www.)dhlottery.co.kr/gameResult.do?method=win720` (예: 296회 `1조667975` = 1조 + 667975). 모바일 `https://m.dhlottery.co.kr/gameResult.do?method=win720` 가 HTML 단순해 파싱 유리.
- 정규식 자체는 `N조DDDDDD` 콤팩트 포맷을 처리 가능해 보이나, 후보 URL/세션/리다이렉트 또는 실제 DOM 차이로 추출 0건. 라이브 DOM 미확인이 근본 블로커(메모리 기재대로).
- **수정**: 모바일 win720 URL 우선 추가 + 추출 실패 시 body 텍스트를 `debug_720_winning_body_*.txt` 로 저장(다음 실행에서 실제 구조 확인). 여전히 실패하면 NAS 디버그 산출물 필요.

---

## 2026-05-31 재보고 (사용자)

### BUG-6. 당첨확인 645 번호가 state 대신 raw 긴 숫자로 표시 (단일/전체 공통)
- **증상**: `lotto-check-645`(및 all) 실행 시 645 내번호가 구매 시 저장한 번호가 아니라 구매내역의 자릿수 패딩 없는 발권 코드(예 "63045 06832 35556 71920 59365 11766")로 표시됨.
- **원인**: `docker-compose.yml` 의 당첨확인 서비스 3종(`lotto-check`, `lotto-check-645`, `lotto-check-720`)에 `./state:/app/state` 볼륨 마운트 누락. 구매 서비스만 마운트되어 있어 `state_store.load_645()` 가 컨테이너 로컬 빈 `/app/state` 를 읽음 → raw 텍스트 fallback.
- **수정**: 당첨확인 3종에 `volumes: - ./state:/app/state` 추가. (이미지 재빌드 불필요, compose 갱신 후 재실행만)

### BUG-7. 전체 당첨확인 시 645/720 텔레그램 메시지가 다닥다닥 붙음
- **수정**: `check_winning.py:run()` 에서 645 알림 후 `sent_645` 플래그로 720 알림 직전 `time.sleep(3)` 삽입 (전체 확인일 때만 간격).

### 720 당첨 조회 실패 (BUG-2 지속)
- 720-only 메시지는 여전히 "당첨 조회 실패". 모바일 URL + body 덤프 추가했으나 라이브 DOM 미확인이 블로커. 다음 실행 후 `debug_720_winning_body_*.txt` 필요.

### BUG-8. 645 당첨번호 조회 전부 실패 (2026-05-31 lotto-check 로그)
- **증상**: `645 API JSON 아님` + 모든 `gameResult.do?method=byWin` URL 에러 리다이렉트 → `0회: []`. 645 메시지에 당첨번호/등수 안 나옴. (state 볼륨 수정으로 내번호는 정상 복원됨.)
- **원인 추정**: ① 페이지 컨텍스트 `fetch(getLottoNumber)` 가 headless/리다이렉트로 HTML 응답, ② 구버전 `gameResult.do?method=byWin` 경로가 에러로 리다이렉트(사이트가 `/lt645/result` 등 신경로로 이전 정황).
- **수정 1차**: `_fetch_645_api_direct()` 추가 — 브라우저 밖 urllib 직접 호출(UA/Referer/X-Requested-With 헤더). 한국 IP(NAS)에서 정상 JSON 기대. 실패 시 ctype/body 일부 로그. 페이지 fetch 실패 로그도 body 스니펫 출력하도록 보강.
- **남은 확인**: 직접 호출도 실패하면 로그의 `body[:120]` 로 차단/신경로 판단. 추첨일(토 20:45) 이전 실행이면 미발표가 정상.

### BUG-9. 645 2매 구매했는데 당첨확인에 1게임만 표시
- **증상**: 645 2매 구매 후 `lotto-check` 에 1게임만 조회됨. 로그 `645: 1게임`, `state 복원 1게임`.
- **원인**: ① 표시 루프가 `purchases['lotto645']`(구매내역 항목 수) 기준 → 다매가 1행으로 묶이면 1개만. ② round 1226 state 에 1게임만 저장(구매가 execBuy 수정 전 구코드로 실행됐을 가능성, 또는 execBuy 게이트 미통과 fallback).
- **수정 1차**: 표시 루프를 `max(len(ledger), len(state))` 기준으로 변경 → state 에 매수만큼 있으면 전부 표시. `get_purchases` 에 `debug_ledger_body.txt` 덤프 추가(다매 라인 구조 확인용).
- **남은 확인**: round 1226 은 state 가 1게임뿐이라 2번째 실제 번호 복구 불가(구매 시점 저장 누락). `state/last_purchase.json` 내용과 다음 구매(execBuy 적용 후) 결과로 검증 필요.

---

## 작업 우선순위

1. BUG-5 (Dockerfile apt-key): 수정 완료 → NAS `docker-compose build --no-cache lotto-all` 후 재실행 검증
2. BUG-1, BUG-3 (720 자동번호 N매 추출): `src/lotto720.py`
   - 자동번호 클릭 직후마다 직전 게임을 추출해 누적 → 추출 실패 케이스 제거
   - 사후 추출 실패 시에는 누적 결과를 그대로 사용
3. BUG-2 (720 당첨 조회): `src/check_winning.py`
   - 결과 페이지 실제 DOM/응답을 디버그 스크린샷으로 재확인 후 셀렉터·정규식 보강
   - 가능하면 JSON API fallback 추가
