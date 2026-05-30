#!/usr/bin/env python3
"""
당첨 확인 스크립트 - 최근 구매 내역의 당첨 결과를 확인하고 Telegram 알림 전송
- 645: 1~5등 당첨번호 + 내번호 + 당첨등수
- 720+: 당첨번호 + 내번호 + 당첨등수
"""
import re
import time
import urllib.request
import json as jsonlib
from os import environ
from playwright.sync_api import Playwright, sync_playwright, Page
from login import login
from notify import send_645_winning, send_720_winning, send_error_notification
import state as state_store


def get_balance(page: Page) -> int:
    """예치금 잔액을 조회합니다."""
    page.goto("https://www.dhlottery.co.kr/mypage/home", timeout=60000, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=30000)
    deposit_el = page.locator("#totalAmt")
    deposit_text = deposit_el.inner_text().strip()
    return int(re.sub(r'[^0-9]', '', deposit_text))


def get_645_winning_numbers(page: Page, draw_no: int = 0) -> dict:
    """645 당첨번호 조회.

    1순위: 공식 API (`getLottoNumber`)
    2순위: 결과 페이지 DOM 스크래핑 (`gameResult.do?method=byWin&drwNo=N`)
    """
    if not draw_no:
        draw_no = _calc_latest_645_drawno()

    for attempt_no in (draw_no, draw_no - 1):
        if attempt_no <= 0:
            continue

        # 1) API 시도
        api_result = _fetch_645_api(page, attempt_no)
        if api_result:
            return api_result

        # 2) DOM 스크래핑 fallback
        dom_result = _scrape_645_result_page(page, attempt_no)
        if dom_result:
            return dom_result

    return {'round': 0, 'winning': [], 'bonus': None, 'date': ''}


def _fetch_645_api(page: Page, draw_no: int) -> dict:
    """공식 API 호출. 실패/HTML 응답 시 None 반환."""
    try:
        result = page.evaluate(
            """async (drwNo) => {
                const r = await fetch(
                    `https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo=${drwNo}`,
                    { credentials: 'include' }
                );
                const text = await r.text();
                let parsed = null;
                try { parsed = JSON.parse(text); } catch (e) {}
                return { status: r.status, contentType: r.headers.get('content-type') || '', parsed };
            }""",
            draw_no,
        )
        if not isinstance(result, dict):
            return None
        parsed = result.get('parsed')
        if not parsed:
            print(f'  ↪ 645 API JSON 아님 ({draw_no}회) → DOM fallback')
            return None
        if parsed.get('returnValue') != 'success':
            print(f'  ↪ 645 API 미발표 ({draw_no}회) → DOM fallback')
            return None
        winning = [parsed.get(f'drwtNo{i}') for i in range(1, 7)]
        return {
            'round': int(parsed.get('drwNo') or draw_no),
            'winning': [int(n) for n in winning if n is not None],
            'bonus': int(parsed['bnusNo']) if parsed.get('bnusNo') else None,
            'date': parsed.get('drwNoDate', ''),
        }
    except Exception as e:
        print(f'  ↪ 645 API 호출 오류 ({draw_no}회): {e}')
        return None


def _scrape_645_result_page(page: Page, draw_no: int) -> dict:
    """결과 페이지 DOM에서 당첨번호 스크래핑. 여러 URL 패턴 시도."""
    urls_to_try = [
        f"https://www.dhlottery.co.kr/gameResult.do?method=byWin&drwNo={draw_no}",
        # drwNo 없이 → 최신 발표 회차로 이동
        "https://www.dhlottery.co.kr/gameResult.do?method=byWin",
        # 대체 URL
        f"https://dhlottery.co.kr/gameResult.do?method=byWin&drwNo={draw_no}",
        f"https://www.dhlottery.co.kr/lotto/result.do?drwNo={draw_no}",
    ]

    for url in urls_to_try:
        result = _try_scrape_645(page, url, draw_no)
        if result:
            return result
    return None


def _try_scrape_645(page: Page, url: str, draw_no: int) -> dict:
    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        time.sleep(1)
        # errorPage로 리다이렉트되면 즉시 스킵
        if 'errorPage' in page.url or 'error' in page.url.lower():
            print(f'  ↪ 645 결과 페이지 오류 리다이렉트 ({url})')
            return None
        page.screenshot(path=f"debug_645_result_{draw_no}.png")

        result = page.evaluate(r"""
            () => {
                let round = 0;
                const text = document.body.innerText || '';
                const roundM = text.match(/제\s*(\d{3,4})\s*회/);
                if (roundM) round = parseInt(roundM[1]);

                let date = '';
                const dateM = text.match(/(\d{4}[년.\-]\s*\d{1,2}[월.\-]\s*\d{1,2})/);
                if (dateM) date = dateM[1];

                // 모든 ball 셀렉터 후보
                const ballEls = document.querySelectorAll('span[class*="ball"]');
                const balls = [];
                ballEls.forEach(el => {
                    const n = parseInt((el.textContent || '').trim());
                    if (!isNaN(n) && n >= 1 && n <= 45) balls.push(n);
                });

                let winning = [];
                let bonus = null;
                if (balls.length >= 7) {
                    winning = balls.slice(0, 6);
                    bonus = balls[6];
                } else if (balls.length === 6) {
                    winning = balls;
                }

                // 텍스트 fallback: "당첨번호" 다음의 6개 + "보너스" 1개
                if (winning.length < 6) {
                    const cleanText = text.replace(/\s+/g, ' ');
                    const winM = cleanText.match(/당첨번호[^\d]{0,20}(\d{1,2})\D+(\d{1,2})\D+(\d{1,2})\D+(\d{1,2})\D+(\d{1,2})\D+(\d{1,2})/);
                    if (winM) {
                        winning = [winM[1], winM[2], winM[3], winM[4], winM[5], winM[6]].map(Number);
                    }
                    const bonusM = cleanText.match(/보너스[^\d]{0,20}(\d{1,2})/);
                    if (bonusM) bonus = parseInt(bonusM[1]);
                }

                return {
                    round, winning, bonus, date,
                    pageUrl: location.href,
                    title: document.title,
                    ballCount: balls.length,
                    bodyPreview: text.substring(0, 500),
                };
            }
        """)
        if result and result.get('winning') and len(result['winning']) >= 6:
            print(f'  ✅ 645 결과 페이지 스크래핑 성공 ({result["round"]}회)')
            return {
                'round': int(result['round'] or draw_no),
                'winning': [int(n) for n in result['winning'][:6]],
                'bonus': int(result['bonus']) if result.get('bonus') else None,
                'date': result.get('date', ''),
            }
        # 디버그: 페이지가 어떻게 보이는지
        print(f'  ↪ 645 결과 페이지 추출 실패 ({draw_no}회)')
        if result:
            print(f'     URL: {result.get("pageUrl")} title: "{result.get("title")}"')
            print(f'     ballCount={result.get("ballCount")}, body 미리보기: {result.get("bodyPreview", "")[:200]}')
        return None
    except Exception as e:
        print(f'  ↪ 645 결과 페이지 오류 ({draw_no}회): {e}')
        return None


def _calc_latest_645_drawno() -> int:
    """현재 KST 기준 가장 최근 토요일 추첨 회차 추정.

    1회 추첨일 = 2002-12-07 (토요일). API 실패 시 -1 회차 자동 fallback.
    """
    from datetime import date, datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).date()
    first_draw = date(2002, 12, 7)
    # 가장 최근 토요일 (오늘 포함)
    days_since_sat = (today.weekday() - 5) % 7  # Sat=0, Sun=1, Mon=2 ... Fri=6
    last_sat = today - timedelta(days=days_since_sat)
    weeks = (last_sat - first_draw).days // 7
    return weeks + 1


def _calc_latest_720_drawno() -> int:
    """현재 KST 기준 가장 최근 목요일 추첨 720+ 회차 추정.

    1회 추첨일 = 2020-05-07 (목요일). 예: 316회=2026-05-21, 317회=2026-05-28.
    결과 페이지·구매내역 회차 추출이 모두 실패할 때 '0회차' 방지용 fallback.
    """
    from datetime import date, datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).date()
    first_draw = date(2020, 5, 7)
    # 가장 최근 목요일 (오늘 포함)
    days_since_thu = (today.weekday() - 3) % 7  # Thu=0, Fri=1, ... Wed=6
    last_thu = today - timedelta(days=days_since_thu)
    if last_thu < first_draw:
        return 0
    weeks = (last_thu - first_draw).days // 7
    return weeks + 1


def calc_645_rank(my_numbers: list, winning: list, bonus: int) -> str:
    """645 등수 계산"""
    if not winning or len(winning) < 6:
        return '미당첨'
    matches = sum(1 for n in my_numbers if n in winning)
    has_bonus = bonus in my_numbers if bonus else False

    if matches == 6:
        return '1'
    elif matches == 5 and has_bonus:
        return '2'
    elif matches == 5:
        return '3'
    elif matches == 4:
        return '4'
    elif matches == 3:
        return '5'
    return '미당첨'


def get_720_winning_numbers(page: Page) -> dict:
    """720+ 최근 회차 당첨번호 조회. 다중 URL을 시도하고 본문 텍스트에서 패턴 매칭."""
    urls = [
        # 모바일 결과 페이지 - HTML 단순해 파싱 유리, 최우선
        "https://m.dhlottery.co.kr/gameResult.do?method=win720",
        "https://dhlottery.co.kr/gameResult.do?method=win720",
        "https://www.dhlottery.co.kr/gameResult.do?method=win720",
        "https://www.dhlottery.co.kr/gameResult.do?method=byWin720",
        "https://dhlottery.co.kr/gameResult.do?method=byWin720",
        "https://www.dhlottery.co.kr/gameResult.do?method=pensionWin",
        "https://www.dhlottery.co.kr/store/lottoryResult.do?method=byPension720",
        "https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LP72",
    ]

    last_debug = None
    for idx, url in enumerate(urls):
        try:
            print(f'🌐 720+ 결과 페이지 시도: {url}')
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            time.sleep(2)
            page.screenshot(path=f"debug_720_winning_{idx}.png")

            # errorPage 리다이렉트면 즉시 다음 URL
            cur = page.url.lower()
            if 'errorpage' in cur or '/error' in cur:
                print(f'  ↪ 오류 페이지 리다이렉트({page.url}) → 다음 URL')
                continue

            extracted = page.evaluate(_PENSION_EXTRACT_JS)
            if extracted and extracted.get('winning') and len(extracted['winning']) >= 6:
                extracted['winning'] = [int(n) for n in extracted['winning'][:6]]
                if extracted.get('bonus'):
                    extracted['bonus'] = [int(n) for n in extracted['bonus'][:6]]
                else:
                    extracted['bonus'] = []
                print(f'✅ 720+ 당첨번호 추출 성공: {extracted}')
                return extracted
            else:
                last_debug = extracted
                # 상세 로그 + 전체 body 텍스트를 파일로 저장 (실제 DOM 구조 확인용)
                try:
                    title = page.title() or ''
                    body_full = page.evaluate(
                        "() => (document.body && document.body.innerText || '')"
                    )
                    print(f'  ⚠️ 추출 실패. title="{title}", body 미리보기: {body_full[:200]}')
                    try:
                        with open(f"debug_720_winning_body_{idx}.txt", "w", encoding="utf-8") as f:
                            f.write(f"URL: {page.url}\nTITLE: {title}\n\n{body_full}")
                    except Exception:
                        pass
                except Exception:
                    print(f'  ⚠️ 추출 실패: {extracted}')
        except Exception as e:
            print(f'  ⚠️ 720+ {url} 실패: {e}')

    print(f'❌ 720+ 당첨번호 모든 URL 실패. 마지막 디버그: {last_debug}')
    return {'round': 0, 'group': '', 'winning': [], 'bonus': []}


# 720+ 결과 페이지 추출 JS (iframe / 페이지 본문 모두 지원)
_PENSION_EXTRACT_JS = r"""
() => {
    // iframe이 있으면 우선 시도, 없으면 현재 document 사용
    const docs = [];
    const iframe = document.querySelector(
        '#ifrm_tab, iframe[src*="pension720"], iframe[src*="LP72"], iframe[src*="720"]'
    );
    if (iframe && iframe.contentDocument) docs.push(iframe.contentDocument);
    docs.push(document);

    for (const doc of docs) {
        const text = (doc.body && doc.body.innerText) || '';
        if (!text) continue;

        // 회차: "제 N 회"
        let round = 0;
        const roundM = text.match(/제\s*(\d{2,4})\s*회/);
        if (roundM) round = parseInt(roundM[1]);

        let group = '';
        let winning = [];
        const cleanText = text.replace(/\s+/g, ' ');

        // 패턴 1: "1등|당첨번호" 인근에 "N조 6digits" (간격/연결 모두 허용)
        let win1Match = cleanText.match(
            /(?:1등|당첨\s*번호|1등번호|당첨\s*번호)[^\n]{0,120}?([1-5])\s*조[^\d]{0,15}((?:\d[\s, ]*){6,8})/
        );
        if (win1Match) {
            group = win1Match[1];
            const digits = win1Match[2].replace(/[^\d]/g, '').slice(0, 6);
            if (digits.length === 6) winning = [...digits].map(Number);
        }

        // 패턴 2: "N조 6digits" (당첨/1등 키워드 없이, 가장 먼저 나오는 6자리)
        if (!winning.length) {
            const m = cleanText.match(/([1-5])\s*조[^\d]{0,10}((?:\d[\s, ]*){6,})/);
            if (m) {
                const digits = m[2].replace(/[^\d]/g, '').slice(0, 6);
                if (digits.length === 6) {
                    group = m[1];
                    winning = [...digits].map(Number);
                }
            }
        }

        // 패턴 3: 셀렉터 기반 ball 추출
        if (!winning.length) {
            const ballEls = doc.querySelectorAll(
                '.win_result .num span, .num720 span, .pension_num span, ' +
                'span[class*="ball720"], span[class*="num720"], .winnum span, ' +
                '.lpwinnum span, .pension_winnum span, ' +
                '.win720 .num span, .win720 span, .winning_num span, ' +
                '.lottoNum720 span, .pen_winnum span'
            );
            const digits = [];
            ballEls.forEach(el => {
                const t = (el.textContent || '').trim();
                if (/^\d$/.test(t)) digits.push(Number(t));
            });
            if (digits.length >= 6) {
                winning = digits.slice(0, 6);
                // 조 추출 시도
                const groupEl = doc.querySelector(
                    '.group, .win_group, [class*="group"], .lp_group, .winGroup'
                );
                if (groupEl) {
                    const gm = (groupEl.textContent || '').match(/([1-5])\s*조/);
                    if (gm) group = gm[1];
                }
            }
        }

        // 패턴 4: 단일 6자리 시퀀스 (마지막 안전망) - "추첨" 또는 "당첨" 인근의 6자리
        if (!winning.length) {
            const m = cleanText.match(
                /(?:추첨|당첨|1등|결과)[^\d]{0,80}((?:\d[\s, ]*){6,8})/
            );
            if (m) {
                const digits = m[1].replace(/[^\d]/g, '').slice(0, 6);
                if (digits.length === 6) winning = [...digits].map(Number);
            }
        }

        // 2등 보너스 (각 조 동일 6자리, 조만 다름)
        const bonus = [];
        if (winning.length === 6) {
            const win2Match = cleanText.match(
                /2등[^\n]{0,60}?((?:\d[\s, ]*){6,8})/
            );
            if (win2Match) {
                const d2 = win2Match[1].replace(/[^\d]/g, '').slice(0, 6);
                if (d2.length === 6) for (const c of d2) bonus.push(Number(c));
            }
            if (!bonus.length) {
                // 2등은 1등과 번호 동일, 조만 모든 조이므로 winning 그대로 사용
                bonus.push(...winning);
            }
        }

        if (winning.length === 6) {
            return { round, group, winning, bonus };
        }
    }

    return { round: 0, group: '', winning: [], bonus: [] };
}
"""


def calc_720_rank(my_group: str, my_digits: list, win_group: str, win_digits: list) -> str:
    """720+ 등수 계산 (간이)"""
    if not win_digits or len(win_digits) < 6:
        return '미당첨'
    if my_group == win_group and my_digits == win_digits:
        return '1'
    # 6자리 일치 + 조 다름
    if my_digits == win_digits:
        return '2'
    # 뒤 5자리 일치
    if my_digits[-5:] == win_digits[-5:]:
        return '3'
    # 뒤 4자리 일치
    if my_digits[-4:] == win_digits[-4:]:
        return '4'
    # 뒤 3자리 일치
    if my_digits[-3:] == win_digits[-3:]:
        return '5'
    return '미당첨'


def get_purchases(page: Page) -> dict:
    """구매내역에서 645/720 최근 게임 추출"""
    page.goto(
        "https://www.dhlottery.co.kr/mypage/mylotteryledger",
        timeout=60000, wait_until="domcontentloaded",
    )
    page.wait_for_load_state("networkidle", timeout=30000)
    time.sleep(2)

    # 검색 버튼 클릭하여 데이터 로드
    try:
        search_btn = page.locator('button:has-text("검색"), input[value="검색"], a:has-text("검색")').first
        search_btn.click(force=True, timeout=5000)
        print('✅ 검색 버튼 클릭')
        page.wait_for_load_state("networkidle", timeout=15000)
        time.sleep(2)
    except Exception as e:
        print(f'⚠️ 검색 버튼 클릭 실패: {e}')

    page.screenshot(path="debug_ledger.png")
    print(f"Current URL: {page.url}")

    # 페이지 텍스트를 라인 단위로 파싱
    # 형식 (각 항목이 9줄):
    #   날짜 / 복권명 / 회차 / 선택번호 / 매수 / 당첨결과 / 당첨금 / 추첨일자 / 인증여부
    body_text = page.inner_text('body')
    lines = [ln.strip() for ln in body_text.split('\n')]

    lotto720 = []
    lotto645 = []

    for i, line in enumerate(lines):
        # 720+ 항목 시작 (복권명 줄)
        if line == '연금복권720+' and i + 4 < len(lines):
            round_line = lines[i + 1]
            num_line = lines[i + 2]
            # quantity_line = lines[i + 3]  # 매수
            result_line = lines[i + 4] if i + 4 < len(lines) else ''

            # 720+ 메뉴 항목 (필터 영역)이면 스킵
            if not round_line.isdigit():
                continue

            # 선택번호 파싱: "3조 068907"
            m = re.match(r'(\d)조\s*(\d{6})', num_line)
            if not m:
                continue

            group, digits = m.group(1), m.group(2)
            rank_match = re.search(r'(\d)등', result_line)
            rank = rank_match.group(1) if rank_match else ('미추첨' if '미추첨' in result_line else '미당첨')

            lotto720.append({
                'round': int(round_line),
                'group': group,
                'digits': [int(d) for d in digits],
                'rank': rank,
            })

        # 645 항목 시작
        elif line == '로또6/45' and i + 4 < len(lines):
            round_line = lines[i + 1]
            num_line = lines[i + 2]
            result_line = lines[i + 4] if i + 4 < len(lines) else ''

            if not round_line.isdigit():
                continue

            rank_match = re.search(r'(\d)등', result_line)
            rank = rank_match.group(1) if rank_match else ('미추첨' if '미추첨' in result_line else '미당첨')

            lotto645.append({
                'round': int(round_line),
                'raw_numbers': num_line,
                'numbers': [],
                'rank': rank,
            })

    print(f'🎫 720+ 항목: {len(lotto720)}, 645 항목: {len(lotto645)}')
    if lotto720:
        print(f'  720 샘플: {lotto720[0]}')
    if lotto645:
        print(f'  645 샘플: {lotto645[0]}')

    return {'lotto645': lotto645, 'lotto720': lotto720}



def run(playwright: Playwright) -> None:
    """메인 실행 함수"""
    import os
    use_headless = os.environ.get('FORCE_HEADLESS') == '1'
    check_target = os.environ.get('CHECK_TARGET', 'all').lower()  # 'all', '645', '720'
    print(f'🎯 확인 대상: {check_target}')
    browser = playwright.chromium.launch(
        headless=use_headless,
        ignore_default_args=['--enable-automation'],
        args=['--disable-blink-features=AutomationControlled', '--no-sandbox', '--disable-dev-shm-usage'],
    )
    context = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        viewport={'width': 1920, 'height': 1080},
        locale='ko-KR',
    )
    page = context.new_page()
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        window.chrome = { runtime: {} };
    """)

    try:
        print("=" * 40)
        print("Logging in...")
        login(page)

        print("=" * 40)
        print("📋 구매내역 조회...")
        purchases = get_purchases(page)
        print(f"  645: {len(purchases['lotto645'])}게임, 720: {len(purchases['lotto720'])}게임")

        # CHECK_TARGET에 따라 필요한 당첨번호만 조회
        win645 = {'round': 0, 'winning': [], 'bonus': None}
        win720 = {'round': 0, 'group': '', 'winning': [], 'bonus': []}

        # 모든 게임이 '미추첨' 상태면 당첨번호 조회 자체를 생략 (추첨 전)
        all_pending_645 = bool(purchases['lotto645']) and all(
            p.get('rank') == '미추첨' for p in purchases['lotto645']
        )
        all_pending_720 = bool(purchases['lotto720']) and all(
            p.get('rank') == '미추첨' for p in purchases['lotto720']
        )

        if check_target in ('all', '645'):
            if all_pending_645:
                print("=" * 40)
                print("⏳ 645 모든 게임이 미추첨 → 당첨번호 조회 생략")
            else:
                print("=" * 40)
                print("🎯 645 당첨번호 조회...")
                ledger_round_645 = purchases['lotto645'][0].get('round', 0) if purchases['lotto645'] else 0
                win645 = get_645_winning_numbers(page, draw_no=ledger_round_645)
                print(f"  {win645['round']}회: {win645['winning']} + 보너스 {win645['bonus']}")

        if check_target in ('all', '720'):
            if all_pending_720:
                print("=" * 40)
                print("⏳ 720+ 모든 게임이 미추첨 → 당첨번호 조회 생략")
            else:
                print("=" * 40)
                print("🎯 720+ 당첨번호 조회...")
                win720 = get_720_winning_numbers(page)
                print(f"  {win720['round']}회: {win720['group']}조 {win720['winning']}")

        print("=" * 40)
        print("Checking balance...")
        balance = get_balance(page)
        print(f"💰 잔액: {balance:,}원")

        # 645 결과 계산 및 알림
        sent_645 = False
        if check_target in ('all', '645') and purchases['lotto645']:
            results_645 = []
            ledger_round = purchases['lotto645'][0].get('round', 0)
            saved_numbers = state_store.load_645(ledger_round)
            if saved_numbers:
                print(f'📂 state에서 645 번호 복원: {len(saved_numbers)}게임 (round={ledger_round})')
            else:
                print(f'⚠️ state에 645 round={ledger_round} 데이터 없음 - raw 텍스트로 표시')

            for idx, p in enumerate(purchases['lotto645']):
                # state 우선 사용 (ledger raw 텍스트는 자릿수 패딩 없는 발권 코드)
                numbers = p['numbers']
                if not numbers and idx < len(saved_numbers):
                    numbers = saved_numbers[idx]

                rank = p.get('rank', '미당첨')
                if rank in ('미당첨', '미추첨') and numbers and win645['winning']:
                    calc_rank = calc_645_rank(numbers, win645['winning'], win645['bonus'])
                    if calc_rank != '미당첨':
                        rank = calc_rank
                results_645.append({
                    'numbers': numbers,
                    'raw_numbers': p.get('raw_numbers', ''),
                    'rank': rank,
                })
            send_645_winning(
                round_no=win645['round'] or ledger_round,
                winning=win645['winning'],
                bonus=win645['bonus'],
                my_games=results_645,
                balance=balance,
            )
            print(f'✅ 645 알림 전송')
            sent_645 = True

        # 720 결과 계산 및 알림
        if check_target in ('all', '720') and purchases['lotto720']:
            # 전체 확인 시 645 알림과 720 알림이 텔레그램에서 다닥다닥 붙지 않도록 간격
            if sent_645:
                time.sleep(3)
            results_720 = []
            ledger_round_720 = purchases['lotto720'][0].get('round', 0)
            saved_720 = state_store.load_720(ledger_round_720)
            saved_720_numbers = saved_720.get('numbers', []) if saved_720 else []

            for idx, p in enumerate(purchases['lotto720']):
                digits = p['digits']
                if not digits and idx < len(saved_720_numbers):
                    digits = saved_720_numbers[idx]

                # 구매내역의 등수 우선, 없으면 계산
                rank = p.get('rank', '미당첨')
                if rank in ('미당첨', '미추첨') and digits and win720['winning']:
                    calc_rank = calc_720_rank(p['group'], digits, win720['group'], win720['winning'])
                    if calc_rank != '미당첨':
                        rank = calc_rank
                results_720.append({
                    'group': p['group'],
                    'digits': digits,
                    'rank': rank,
                })
            send_720_winning(
                round_no=win720['round'] or ledger_round_720 or _calc_latest_720_drawno(),
                win_group=win720['group'],
                win_digits=win720['winning'],
                my_games=results_720,
                balance=balance,
            )
            print(f'✅ 720 알림 전송')

        if not purchases['lotto645'] and not purchases['lotto720']:
            print('⚠️ 구매내역 없음')

    except Exception as e:
        print(f"Error: {e}")
        page.screenshot(path="debug_error.png")
        send_error_notification("당첨 확인", str(e))
        raise
    finally:
        context.close()
        browser.close()


if __name__ == "__main__":
    with sync_playwright() as playwright:
        run(playwright)
