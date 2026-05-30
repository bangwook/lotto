# 로또 자동화 프로젝트 작업 인계서

> **목적**: 작업 환경 이전 시 컨텍스트 인계용
> **마지막 업데이트**: 2026-05-02

## 프로젝트 개요
- **목적**: 동행복권(dhlottery.co.kr) 로또 6/45 + 연금복권 720+ 자동 구매 + 당첨 확인
- **스택**: Playwright (Python 3.9) + Docker + Synology NAS
- **알림**: Telegram Bot

## 실행 환경

### Synology NAS Docker (현재 운영)
- **위치**: `/volume1/docker/lotto/lotto-main`
- **SSH**: `ssh <ID>@dsm.wookhome.myds.me -p 6248`
- **권한**: `sudo -i` 필요 (root 전환)
- **git 미설치** → 코드 업데이트는 `wget` 사용

### 코드 업데이트 명령어 (한 줄, NAS bash에 붙여넣기)
```bash
cd /volume1/docker/lotto/lotto-main && for f in src/check_winning.py src/notify.py src/purchase_all.py src/lotto720.py src/login.py src/bot.py src/settings.py Dockerfile entrypoint.sh docker-compose.yml; do wget -O $f https://raw.githubusercontent.com/bangwook/lotto/main/$f; done && chmod +x entrypoint.sh
```

### Docker 서비스
| 서비스 | 용도 |
|--------|------|
| `lotto-all` | 645 + 720 전체 구매 |
| `lotto-645` | 645만 구매 |
| `lotto-720` | 720+만 구매 |
| `lotto-check` | 645 + 720 당첨 확인 |
| `lotto-check-645` | 645 당첨 확인만 |
| `lotto-check-720` | 720+ 당첨 확인만 |
| `lotto-bot` | **텔레그램 버튼 봇 (상시 실행, restart: unless-stopped)** |

### 텔레그램 버튼 봇 (`lotto-bot`, `src/bot.py`)
- long-polling 으로 콜백 수신. 버튼: 💰구매(2단계 확인 후 `purchase_all.py` 실행) / 🎯당첨확인(`check_winning.py` 실행) / ⚙️구매 개수 설정(645·720 매수 0~5).
- 설정은 `state/settings.json` 에 저장(`src/settings.py`). `purchase_all.py` 가 이 파일을 우선 읽고, 없으면 env(`AUTO_GAMES`/`LOTTO720_GAMES`) 기본값 사용 → 스케줄 구매에도 동일 적용.
- 모든 알림(`notify.py`)에 "🎰 메뉴 열기" 버튼이 붙어 어느 메시지에서도 메뉴 진입 가능.
- `TELEGRAM_CHAT_ID` 와 일치하는 채팅만 응답(타인 조작 차단). 재시작 시 밀린 업데이트는 폐기(오발주 방지).
- 기동: `docker-compose up -d --build lotto-bot` (백그라운드 상주). 중지: `docker-compose stop lotto-bot`.

### 실행 방법
```bash
# 첫 빌드 또는 코드 변경 후
docker-compose up --build <서비스명>

# 일반 실행 (빠름)
docker-compose up <서비스명>
```

## Synology 작업 스케줄러
| 작업 | 일정 | 명령어 (사용자 root) |
|------|------|---------------------|
| 로또 구매 | 매주 금요일 22:00 | `cd /volume1/docker/lotto/lotto-main && docker-compose up lotto-all` |
| 645 당첨 확인 | 매주 토요일 22:00 | `cd /volume1/docker/lotto/lotto-main && docker-compose up lotto-check-645` |
| 720+ 당첨 확인 | 매주 목요일 22:00 | `cd /volume1/docker/lotto/lotto-main && docker-compose up lotto-check-720` |

## 환경변수 (.env.docker)
```
USER_ID=동행복권아이디
PASSWD=동행복권비밀번호
AUTO_GAMES=5              # 645 자동 구매 매수
MANUAL_NUMBERS=[]         # 645 수동 번호 (JSON 배열)
LOTTO720_GAMES=1          # 720+ 자동 구매 매수
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=909384117
PURCHASE_TARGET=all       # all/645/720 (compose에서 override)
CHECK_TARGET=all          # all/645/720 (compose에서 override)
```

## 핵심 기술적 발견 (재현 시 필수)

### 1. 비밀번호 입력
```python
# ❌ 작동 안 함 (keyboard 이벤트 미발생)
page.fill("#inpUserPswdEncn", PASSWD)

# ✅ 작동
page.locator("#inpUserPswdEncn").press_sequentially(PASSWD, delay=100)
```

### 2. headless 감지 우회 (필수)
```python
# 1. browser launch
browser = playwright.chromium.launch(
    headless=False,  # Xvfb 가상 디스플레이 + headed
    ignore_default_args=['--enable-automation'],
    args=['--disable-blink-features=AutomationControlled', '--no-sandbox'],
)

# 2. context
context = browser.new_context(
    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...',
    viewport={'width': 1920, 'height': 1080},
    locale='ko-KR',
)

# 3. init script (페이지 로드 전)
page.add_init_script("""
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    window.chrome = { runtime: {} };
""")
```

### 3. Xvfb 가상 디스플레이 (entrypoint.sh)
```bash
#!/bin/bash
rm -f /tmp/.X99-lock
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
sleep 2
export DISPLAY=:99
exec "${@:-python src/purchase_all.py}"
```

### 4. 720+ 그룹 선택 (네이티브 클릭 필수)
```python
# JS evaluate click() → 페이지 이벤트 안 됨, "모든 조" 유지로 5매 구매됨
# Playwright 네이티브 클릭 사용
group_locator = frame.get_by_text(f'{group}조', exact=True).first
group_locator.click(force=True, timeout=5000)
```

### 5. 720+ 다이얼로그 자동 수락
```python
# "모든조 구매 시 1,2등 동시 당첨..." 메시지는 일반 안내 (5매 의미 아님)
# 그룹 선택만 정확히 했다면 accept하면 됨
page.on("dialog", lambda d: d.accept())
```

### 6. 720+ iframe URL
- `/game/pension720/game.jsp` (`/game/lottery720/game.do` 아님)

### 7. Telegram HTML 이스케이프
```python
import html
def _escape(text): return html.escape(str(text))
# details 등 사용자 입력 메시지에 적용 (400 Bad Request 방지)
```

## 사이트 동작 메모

### 동행복권 판매 시간
- **645**: 매일 06:00 ~ 자정 (토요일 20:00까지, 추첨 20:45)
- **720+**: 비슷한 시간대 (목요일 추첨)
- **점검**: 자정 ~ 06:00 (구매 불가)

### 차단성 팝업 메시지
- "현재 시간은 판매시간이 아닙니다" → 점검 중
- "회차정보가 존재하지 않습니다" → 추첨 직후 다음 회차 미등록
- 텔레그램 메시지에 정확히 표시되도록 처리됨

### 구매내역 페이지 (mylotteryledger)
- URL: `https://www.dhlottery.co.kr/mypage/mylotteryledger`
- **검색 버튼 클릭 필수** (안 하면 빈 페이지)
- 데이터 형식 (라인별 9줄):
  ```
  날짜 / 복권명 / 회차 / 번호 / 매수 / 당첨결과 / 당첨금 / 추첨일자 / 인증여부
  ```
- 720 형식: "3조 068907"
- 645 형식: "63045 06832 35556 71920 59365 11766" (자릿수 패딩 없음)

## 알림 요구사항

### 구매 알림
- **645 성공**: 구매한 모든 번호 표시
- **645 실패**: 실패 사유 표시 (판매시간, 회차 등)
- **720+ 성공**: 구매한 조 + 번호 표시
- **720+ 실패**: 실패 사유 표시
- **독립 실행**: 645 실패해도 720은 시도, 알림 각각 전송

### 당첨 확인 알림
- **645**: 당첨번호 + 보너스 + 내 번호 + 등수 (1~5등 또는 미당첨)
- **720+**: 당첨조/번호 + 내 번호 + 등수
- 645/720 별도 메시지

### 테스트
- 메시지에 `[테스트]` 접두사 부착

## 미해결 / 개선 필요

### 1. 645 raw 번호 파싱
- **현상**: 구매내역에 "63045 06832 35556 71920 59365 11766"처럼 자릿수 패딩 없이 표시
- **문제**: 6게임 × 6번호로 정확히 분리 불가능 (모호한 자릿수)
- **현재 처리**: raw 텍스트 그대로 메시지 표시
- **개선 방향**:
  - 옵션 A: 구매 직후 영수증 페이지에서 추출 (자릿수 패딩 있을 가능성)
  - 옵션 B: 각 게임의 돋보기 아이콘 클릭 → 상세 페이지에서 추출
  - 옵션 C: 동행복권 API 직접 호출

### 2. 당첨번호 페이지 셀렉터
- **현상**: `get_645_winning_numbers`, `get_720_winning_numbers` 함수가 0회차/빈 배열 반환
- **이유**: 셀렉터 추측에 의존, 실제 DOM과 안 맞음
- **현재 처리**: 구매내역의 회차로 fallback (당첨번호 자체는 표시 안 됨)
- **개선 방향**: 추첨일(목/토) 이후 실제 페이지 DOM 확인하여 셀렉터 수정
  - 645: `https://www.dhlottery.co.kr/gameResult.do?method=byWin`
  - 720+: `https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LP72`

### 3. 720+ 자동번호 셀렉터
- **현상**: 자동번호 클릭 후 6자리 추출이 실패하기도 함
- **이유**: iframe 내부 DOM 구조 미확인
- **현재 처리**: 다양한 셀렉터 시도 + 페이지 텍스트 파싱 fallback
- **개선 방향**: iframe 내부 페이지(`/game/pension720/game.jsp`) HTML 분석

## 디버그 스크린샷 위치
NAS: `/volume1/docker/lotto/lotto-main/debug_*.png`
- `debug_login_page.png`, `debug_after_login.png`
- `debug_645_*.png`, `debug_720_*.png`
- `debug_after_purchase.png`, `debug_ledger.png`

## Git
- **Repo**: https://github.com/bangwook/lotto
- **Branch**: main
- 커밋 메시지에 `Co-Authored-By: Claude Opus 4.6` 자동 추가

## 사용자 선호
- 한국어 사용
- 결과는 Telegram으로 받음
- 짧고 명확한 응답 선호
