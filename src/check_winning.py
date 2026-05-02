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


def get_balance(page: Page) -> int:
    """예치금 잔액을 조회합니다."""
    page.goto("https://www.dhlottery.co.kr/mypage/home", timeout=60000, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=30000)
    deposit_el = page.locator("#totalAmt")
    deposit_text = deposit_el.inner_text().strip()
    return int(re.sub(r'[^0-9]', '', deposit_text))


def get_645_winning_numbers(page: Page, draw_no: int = 0) -> dict:
    """645 당첨번호 조회 - 공식 API 사용.

    https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo=N
    응답: drwtNo1..6, bnusNo, drwNo, drwNoDate, returnValue
    """
    if not draw_no:
        draw_no = _calc_latest_645_drawno()

    # page.evaluate fetch로 호출 - 로그인된 브라우저 세션 + 정상 IP 사용
    for attempt_no in (draw_no, draw_no - 1):
        if attempt_no <= 0:
            continue
        try:
            result = page.evaluate(
                """async (drwNo) => {
                    const r = await fetch(
                        `https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo=${drwNo}`,
                        { credentials: 'include', headers: { 'Accept': 'application/json' } }
                    );
                    const text = await r.text();
                    try { return JSON.parse(text); } catch (e) { return { _raw: text.slice(0, 200) }; }
                }""",
                attempt_no,
            )
            if not isinstance(result, dict):
                print(f'⚠️ 645 API 비정상 응답 ({attempt_no}회): {result}')
                continue
            if result.get('returnValue') != 'success':
                print(f'⚠️ 645 {attempt_no}회 미발표 (returnValue={result.get("returnValue")})')
                continue
            winning = [result.get(f'drwtNo{i}') for i in range(1, 7)]
            return {
                'round': int(result.get('drwNo') or attempt_no),
                'winning': [int(n) for n in winning if n is not None],
                'bonus': int(result['bnusNo']) if result.get('bnusNo') else None,
                'date': result.get('drwNoDate', ''),
            }
        except Exception as e:
            print(f'⚠️ 645 API 호출 실패 ({attempt_no}회): {e}')

    return {'round': 0, 'winning': [], 'bonus': None, 'date': ''}


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
        "https://dhlottery.co.kr/gameResult.do?method=win720",
        "https://www.dhlottery.co.kr/gameResult.do?method=win720",
        "https://dhlottery.co.kr/gameResult.do?method=byWin720",
        "https://www.dhlottery.co.kr/store/lottoryResult.do?method=byPension720",
        "https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LP72",
    ]

    for url in urls:
        try:
            print(f'🌐 720+ 결과 페이지 시도: {url}')
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            time.sleep(2)
            page.screenshot(path=f"debug_720_winning_{urls.index(url)}.png")

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
                print(f'  ⚠️ 추출 실패 또는 데이터 부족: {extracted}')
        except Exception as e:
            print(f'  ⚠️ 720+ {url} 실패: {e}')

    print('❌ 720+ 당첨번호 모든 URL 실패')
    return {'round': 0, 'group': '', 'winning': [], 'bonus': []}


# 720+ 결과 페이지 추출 JS (iframe / 페이지 본문 모두 지원)
_PENSION_EXTRACT_JS = r"""
() => {
    // iframe이 있으면 우선 시도, 없으면 현재 document 사용
    const docs = [];
    const iframe = document.querySelector('#ifrm_tab, iframe[src*="pension720"], iframe[src*="LP72"]');
    if (iframe && iframe.contentDocument) docs.push(iframe.contentDocument);
    docs.push(document);

    for (const doc of docs) {
        const text = (doc.body && doc.body.innerText) || '';
        if (!text) continue;

        // 회차: "제 N 회"
        let round = 0;
        const roundM = text.match(/제\s*(\d{2,4})\s*회/);
        if (roundM) round = parseInt(roundM[1]);

        // 1등 패턴: "N조 D D D D D D" 또는 "N조 DDDDDD"
        let group = '';
        let winning = [];
        const cleanText = text.replace(/\s+/g, ' ');

        // 패턴 1: "1등 ... 조 ... 번호"
        const win1Match = cleanText.match(/(?:1등|당첨번호)[\s\S]{0,30}?([1-5])\s*조[\s,]*([\d\s]{6,30})/);
        if (win1Match) {
            group = win1Match[1];
            const digits = win1Match[2].replace(/[^\d]/g, '').slice(0, 6);
            if (digits.length === 6) winning = [...digits].map(Number);
        }

        // 패턴 2: 단순 "N조 6자리"
        if (!winning.length) {
            const m = cleanText.match(/([1-5])\s*조\s+(\d)\s*(\d)\s*(\d)\s*(\d)\s*(\d)\s*(\d)/);
            if (m) {
                group = m[1];
                winning = [m[2], m[3], m[4], m[5], m[6], m[7]].map(Number);
            }
        }

        // 패턴 3: 라벨 박스 셀렉터 - 회차 페이지의 일반적 구조
        if (!winning.length) {
            const ballEls = doc.querySelectorAll(
                '.win_result .num span, .num720 span, .pension_num span, ' +
                'span[class*="ball720"], span[class*="num720"], .winnum span, ' +
                '.lpwinnum span, .pension_winnum span'
            );
            const digits = [];
            ballEls.forEach(el => {
                const t = (el.textContent || '').trim();
                if (/^\d$/.test(t)) digits.push(Number(t));
            });
            if (digits.length >= 6) {
                winning = digits.slice(0, 6);
                // 조 추출 시도
                const groupEl = doc.querySelector('.group, .win_group, [class*="group"]');
                if (groupEl) {
                    const gm = (groupEl.textContent || '').match(/([1-5])\s*조/);
                    if (gm) group = gm[1];
                }
            }
        }

        // 2등 보너스 (각 조 동일 6자리, 조만 다름) - 패턴: "2등 ... 6자리"
        const bonus = [];
        if (winning.length === 6) {
            const win2Match = cleanText.match(/2등[\s\S]{0,40}?(\d)\s*(\d)\s*(\d)\s*(\d)\s*(\d)\s*(\d)/);
            if (win2Match) {
                for (let i = 1; i <= 6; i++) bonus.push(Number(win2Match[i]));
            } else if (winning.length === 6) {
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

    # 645 티켓 모달에서 정확한 번호 추출 (자릿수 패딩이 적용됨)
    if lotto645:
        _enrich_645_from_ticket_modals(page, lotto645)

    return {'lotto645': lotto645, 'lotto720': lotto720}


def _enrich_645_from_ticket_modals(page: Page, lotto645: list) -> None:
    """ledger의 각 645 항목 클릭 → 티켓 보기 모달에서 번호 추출하여 entry['numbers'] 채움.

    raw 텍스트("63045 06832 ...")는 자릿수 패딩 없는 발권 코드이며, 실제 번호는
    모달의 "A 자동 5 17 25 33 35 36" 행에 패딩되어 표시된다.
    """
    print(f'🔍 645 티켓 모달에서 번호 추출 시도 ({len(lotto645)}건)...')

    for idx, entry in enumerate(lotto645):
        if entry.get('numbers'):
            continue
        try:
            # idx번째 645 행의 클릭 가능 요소 찾기
            opened = page.evaluate(f"""
                (idx) => {{
                    let count = 0;
                    const lines = document.querySelectorAll('tr, li, div');
                    for (const el of lines) {{
                        const t = (el.textContent || '').trim();
                        if (!t.startsWith('로또6/45')) continue;
                        if (count === idx) {{
                            // 클릭 트리거 후보: 자기 자신 또는 자식 a/button
                            const trigger = el.querySelector('a, button, [onclick]') || el;
                            trigger.click();
                            return true;
                        }}
                        count++;
                    }}
                    return false;
                }}
            """, idx)
            if not opened:
                print(f'  ⚠️ #{idx + 1} 클릭 트리거 못 찾음')
                continue

            time.sleep(1.2)  # 모달 애니메이션
            page.screenshot(path=f"debug_645_ticket_{idx}.png")

            numbers = page.evaluate(r"""
                () => {
                    const games = [];
                    const seen = new Set();
                    const addGame = (nums) => {
                        if (nums.length < 6) return;
                        const game = nums.slice(0, 6);
                        const key = game.join(',');
                        if (seen.has(key)) return;
                        seen.add(key);
                        games.push(game);
                    };

                    // 1) 텍스트 패턴: "A 자동/수동/반자동 N N N N N N"
                    const lines = (document.body.innerText || '').split('\n');
                    for (const ln of lines) {
                        const m = ln.trim().match(/^([A-J])\s*(?:자동|수동|반자동)\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})/);
                        if (m) {
                            const nums = [m[2], m[3], m[4], m[5], m[6], m[7]].map(Number);
                            if (nums.every(n => n >= 1 && n <= 45) && new Set(nums).size === 6) {
                                addGame(nums);
                            }
                        }
                    }

                    // 2) ball 셀렉터 (DOM 기반)
                    if (games.length === 0) {
                        document.querySelectorAll('tr, li, .game, .game_row, [class*="num"]').forEach(row => {
                            const nums = [];
                            row.querySelectorAll('span[class*="ball"]').forEach(el => {
                                const n = parseInt((el.textContent || '').trim());
                                if (!isNaN(n) && n >= 1 && n <= 45) nums.push(n);
                            });
                            if (nums.length >= 6 && nums.length <= 8) addGame(nums);
                        });
                    }

                    return games;
                }
            """)

            if numbers:
                entry['numbers'] = numbers
                print(f'  ✅ #{idx + 1}: {len(numbers)}게임 추출 - {numbers}')
            else:
                print(f'  ⚠️ #{idx + 1}: 모달에서 번호 추출 실패')

            # 모달 닫기
            closed = False
            for sel in ('.btn_close', '.close', '.modal_close', '[aria-label="close"]',
                        '[aria-label="닫기"]', 'button[title="닫기"]', '.pop_close'):
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=500):
                        btn.click(force=True, timeout=2000)
                        closed = True
                        break
                except Exception:
                    continue
            if not closed:
                try:
                    page.keyboard.press('Escape')
                except Exception:
                    pass
            time.sleep(0.5)
        except Exception as e:
            print(f'  ⚠️ #{idx + 1} 처리 중 오류: {e}')
            try:
                page.keyboard.press('Escape')
            except Exception:
                pass
            time.sleep(0.5)


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

        if check_target in ('all', '645'):
            print("=" * 40)
            print("🎯 645 당첨번호 조회...")
            ledger_round_645 = purchases['lotto645'][0].get('round', 0) if purchases['lotto645'] else 0
            win645 = get_645_winning_numbers(page, draw_no=ledger_round_645)
            print(f"  {win645['round']}회: {win645['winning']} + 보너스 {win645['bonus']}")

        if check_target in ('all', '720'):
            print("=" * 40)
            print("🎯 720+ 당첨번호 조회...")
            win720 = get_720_winning_numbers(page)
            print(f"  {win720['round']}회: {win720['group']}조 {win720['winning']}")

        print("=" * 40)
        print("Checking balance...")
        balance = get_balance(page)
        print(f"💰 잔액: {balance:,}원")

        # 645 결과 계산 및 알림
        if check_target in ('all', '645') and purchases['lotto645']:
            results_645 = []
            ledger_round = purchases['lotto645'][0].get('round', 0)

            for p in purchases['lotto645']:
                numbers = p['numbers']  # 티켓 모달에서 추출됨

                # 구매내역의 등수 우선, 미당첨/미추첨이면 직접 계산
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

        # 720 결과 계산 및 알림
        if check_target in ('all', '720') and purchases['lotto720']:
            results_720 = []
            ledger_round_720 = purchases['lotto720'][0].get('round', 0)

            for p in purchases['lotto720']:
                digits = p['digits']  # ledger에서 "3조 068907" 형식 파싱됨

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
                round_no=win720['round'] or ledger_round_720,
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
