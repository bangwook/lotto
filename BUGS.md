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

## 작업 우선순위

1. BUG-1, BUG-3 (720 자동번호 N매 추출): `src/lotto720.py`
   - 자동번호 클릭 직후마다 직전 게임을 추출해 누적 → 추출 실패 케이스 제거
   - 사후 추출 실패 시에는 누적 결과를 그대로 사용
2. BUG-2 (720 당첨 조회): `src/check_winning.py`
   - 결과 페이지 실제 DOM/응답을 디버그 스크린샷으로 재확인 후 셀렉터·정규식 보강
   - 가능하면 JSON API fallback 추가
