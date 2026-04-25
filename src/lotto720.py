#!/usr/bin/env python3
"""
연금복권 720+ 구매 모듈
설정된 개수만큼 랜덤 조를 선택하여 자동번호로 구매
"""
import random
import re
import time
from os import environ
from playwright.sync_api import Playwright, sync_playwright, Page
from login import login


def buy_lotto720(page: Page, num_games: int, dry_run: bool = False) -> dict:
    """
    연금복권 720+를 구매합니다.

    Args:
        page: 로그인된 Playwright Page 객체
        num_games: 구매할 매수 (1-5)
        dry_run: True이면 구매 직전까지만 진행 (테스트용)

    Returns:
        dict: {'success': bool, 'groups': list[int], 'numbers': list, 'details': str}
    """
    if num_games <= 0:
        return {'success': False, 'groups': [], 'numbers': [], 'details': '구매할 매수 없음'}

    # el.dhlottery.co.kr 서브도메인에 세션 쿠키 복사
    context = page.context
    cookies = context.cookies()
    new_cookies = []
    for cookie in cookies:
        if 'dhlottery.co.kr' in cookie.get('domain', ''):
            el_cookie = cookie.copy()
            el_cookie['domain'] = '.dhlottery.co.kr'
            new_cookies.append(el_cookie)
    if new_cookies:
        context.add_cookies(new_cookies)
        print(f'🍪 {len(new_cookies)}개 쿠키를 .dhlottery.co.kr 도메인으로 복사')

    # 720+ 게임 페이지 접근 시도 (여러 URL 순차 시도)
    direct_mode = False
    # 먼저 메인 사이트 경유 (referrer 설정)
    page.goto("https://www.dhlottery.co.kr/main", timeout=30000, wait_until="domcontentloaded")
    time.sleep(2)

    game_urls = [
        ("el.dhlottery.co.kr wrapper", "https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LP72"),
        ("el.dhlottery.co.kr direct", "https://el.dhlottery.co.kr/game/lottery720/game.do"),
    ]

    page_loaded = False
    for url_name, url in game_urls:
        print(f'📍 {url_name} 시도: {url}')
        try:
            page.goto(url, timeout=30000, wait_until="networkidle",
                       referer="https://www.dhlottery.co.kr/main")
        except Exception:
            page.goto(url, timeout=30000, wait_until="domcontentloaded",
                       referer="https://www.dhlottery.co.kr/main")
            time.sleep(3)
        current_url = page.url.lower()
        page_title = page.title() or ''
        page_text = page.inner_text('body')[:300] if page.locator('body').count() > 0 else ''

        # 간소화 페이지 또는 로그인/마이페이지로 리다이렉트된 경우 다음 URL 시도
        if '간소화' in page_title or '간소화' in page_text:
            print(f'  ⚠️ 간소화 페이지 → 다음 URL 시도')
            continue
        if '/login' in current_url or '/mypage' in current_url:
            print(f'  ⚠️ 리다이렉트됨 ({page.url}) → 다음 URL 시도')
            continue

        # JS가 iframe을 생성할 시간 대기
        time.sleep(5)

        # 디버그: 페이지 상태 출력
        page_title_dbg = page.title() or ''
        page_url_dbg = page.url
        has_iframe = page.locator("#ifrm_tab").count() > 0
        has_game_ui = page.locator(".lotto720_btn_auto_number, #curdeposit, .lpdeposit").first.count() > 0
        print(f'  📍 URL: {page_url_dbg}, title: {page_title_dbg}, iframe: {has_iframe}, gameUI: {has_game_ui}')

        if has_iframe or has_game_ui:
            direct_mode = not has_iframe
            page_loaded = True
            print(f'  ✅ 게임 페이지 로드 성공 ({"direct" if direct_mode else "iframe"} mode)')
            break

        # iframe이 없으면 페이지 내용 디버그
        body_text = page.inner_text('body')[:200] if page.locator('body').count() > 0 else ''
        print(f'  ⚠️ 게임 UI 없음. 페이지 내용: {body_text[:100]}')
        print(f'  → 다음 URL 시도')

    if not page_loaded:
        page.screenshot(path="debug_720_all_urls_fail.png")
        print('📸 Screenshot saved: debug_720_all_urls_fail.png')
        debug_info = {
            'url': page.url,
            'title': page.title(),
            'text': page.inner_text('body')[:300] if page.locator('body').count() > 0 else '',
        }
        print(f'🔍 최종 디버그: {debug_info}')
        return {
            'success': False, 'groups': [], 'numbers': [],
            'details': '720+ 게임 페이지 접근 불가 (간소화 모드). 모든 URL 시도 실패.',
        }

    if direct_mode:
        # Direct mode: 게임 UI가 페이지에 직접 로드됨
        frame = page  # page 자체를 frame처럼 사용

        try:
            page.locator("#curdeposit, .lpdeposit").first.wait_for(state="attached", timeout=30000)
        except Exception:
            page.screenshot(path="debug_720_direct_fail.png")
            print('📸 Screenshot saved: debug_720_direct_fail.png')
            return {
                'success': False, 'groups': [], 'numbers': [],
                'details': '직접 모드: 게임 페이지 콘텐츠 로딩 실패',
            }
    else:
        # Iframe mode: 기존 로직
        time.sleep(5)

        for attempt in range(3):
            try:
                page.locator("#ifrm_tab").wait_for(state="visible", timeout=15000)
                iframe_src = page.evaluate("""
                    () => {
                        const iframe = document.querySelector('#ifrm_tab');
                        return iframe ? iframe.src : '';
                    }
                """)
                if not iframe_src or iframe_src == 'about:blank':
                    print('⚠️ iframe src가 비어있음, 직접 설정 시도...')
                    page.evaluate("""
                        () => {
                            const iframe = document.querySelector('#ifrm_tab');
                            if (iframe) iframe.src = '/game/lottery720/game.do';
                        }
                    """)
                    time.sleep(3)
                break
            except Exception:
                if attempt < 2:
                    print(f'⚠️ iframe 로딩 대기 중... (시도 {attempt + 1}/3)')
                    page.screenshot(path=f"debug_720_attempt_{attempt}.png")
                    page.reload(wait_until="networkidle", timeout=60000)
                    time.sleep(5)
                else:
                    page.screenshot(path="debug_720_iframe_fail.png")
                    print('📸 Screenshot saved: debug_720_iframe_fail.png')
                    debug_info = page.evaluate("""
                        () => ({
                            iframeExists: !!document.querySelector('#ifrm_tab'),
                            pageTitle: document.title,
                            bodyText: document.body.innerText.substring(0, 500),
                        })
                    """)
                    print(f'🔍 디버그 정보: {debug_info}')
                    return {
                        'success': False, 'groups': [], 'numbers': [],
                        'details': f'iframe 로딩 실패. debug: {debug_info}',
                    }

        frame = page.frame_locator("#ifrm_tab")

        try:
            frame.locator("#curdeposit, .lpdeposit").first.wait_for(state="attached", timeout=30000)
        except Exception:
            page.screenshot(path="debug_720_content_fail.png")
            print('📸 Screenshot saved: debug_720_content_fail.png')
            page.reload(wait_until="networkidle", timeout=60000)
            time.sleep(3)
            try:
                page.locator("#ifrm_tab").wait_for(state="visible", timeout=15000)
                frame.locator("#curdeposit, .lpdeposit").first.wait_for(state="attached", timeout=30000)
            except Exception:
                return {
                    'success': False, 'groups': [], 'numbers': [],
                    'details': 'iframe 내부 콘텐츠 로딩 실패',
                }

    print('✅ Navigated to Lotto 720 Game Page')
    time.sleep(1)

    # Verify session
    user_id_val = frame.locator("input[name='USER_ID']").get_attribute("value")
    if not user_id_val:
        return {'success': False, 'groups': [], 'numbers': [], 'details': '세션 만료 (USER_ID 없음)'}

    # Check balance
    balance_val = frame.locator("#curdeposit").get_attribute("value")
    if not balance_val:
        balance_text = frame.locator(".lpdeposit").first.inner_text()
        balance_val = balance_text.replace(",", "").replace("원", "").strip()

    try:
        current_balance = int(balance_val)
    except ValueError:
        current_balance = 0

    required = num_games * 1000
    if current_balance < required:
        return {
            'success': False, 'groups': [], 'numbers': [],
            'details': f'잔액 부족 (필요: {required:,}원, 보유: {current_balance:,}원)',
        }

    # Dismiss popup if present
    try:
        if frame.locator("#popupLayerAlert").is_visible(timeout=2000):
            frame.locator("#popupLayerAlert").get_by_role("button", name="확인").click()
    except Exception:
        pass

    # Wait for game UI
    frame.locator(".lotto720_btn_auto_number").wait_for(state="visible", timeout=15000)

    # Remove pause layer popups
    _remove_pause_popups(page, direct_mode)

    # Select games with random groups
    groups = []
    for i in range(num_games):
        group = random.randint(1, 5)
        groups.append(group)

        selected = _select_group(page, group, direct_mode)
        if selected:
            print(f'✅ {group}조 선택됨')
        else:
            print(f'⚠️ {group}조 선택 실패, 기본값 사용')

        time.sleep(0.5)

        # Click auto number
        frame.locator(".lotto720_btn_auto_number").click(force=True)
        time.sleep(1)
        print(f'✅ 자동번호 {i + 1}/{num_games} 생성')

    # 자동 생성된 번호 추출 (confirm 전)
    numbers = _extract_720_numbers(page, direct_mode)

    # Confirm selection
    frame.locator(".lotto720_btn_confirm_number").click()
    time.sleep(2)

    print(f'💰 구매 금액: {num_games * 1000:,}원 ({num_games}매)')

    # Dry run: 구매 직전에서 중단
    if dry_run:
        page.screenshot(path="debug_720_dry_run.png")
        print(f'🧪 [DRY RUN] 구매 직전 중단. 조: {groups}, 금액: {num_games * 1000:,}원')
        print('📸 Screenshot saved: debug_720_dry_run.png')
        return {'success': True, 'groups': groups, 'numbers': numbers, 'details': 'dry_run - 구매 미실행'}

    # Purchase
    frame.locator("a:has-text('구매하기')").first.click()

    # Confirm popup
    confirm_popup = frame.locator("#lotto720_popup_confirm")
    confirm_popup.wait_for(state="visible", timeout=5000)
    confirm_popup.locator("a.btn_blue").click()

    time.sleep(2)
    print(f'✅ Lotto 720: {num_games}매 구매 완료! (조: {groups})')
    return {'success': True, 'groups': groups, 'numbers': numbers, 'details': ''}


def _remove_pause_popups(page: Page, direct_mode: bool):
    """일시정지 팝업 제거"""
    if direct_mode:
        page.evaluate("""
            () => {
                ['#pause_layer_pop_02', '#ele_pause_layer_pop02',
                 '.pause_layer_pop', '.pause_bg'].forEach(sel => {
                    document.querySelectorAll(sel).forEach(el => {
                        el.style.display = 'none';
                        el.style.visibility = 'hidden';
                        el.style.pointerEvents = 'none';
                    });
                });
            }
        """)
    else:
        page.evaluate("""
            () => {
                const iframe = document.querySelector('#ifrm_tab');
                if (iframe && iframe.contentDocument) {
                    const doc = iframe.contentDocument;
                    ['#pause_layer_pop_02', '#ele_pause_layer_pop02',
                     '.pause_layer_pop', '.pause_bg'].forEach(sel => {
                        doc.querySelectorAll(sel).forEach(el => {
                            el.style.display = 'none';
                            el.style.visibility = 'hidden';
                            el.style.pointerEvents = 'none';
                        });
                    });
                }
            }
        """)


def _select_group(page: Page, group: int, direct_mode: bool) -> bool:
    """조 선택"""
    if direct_mode:
        return page.evaluate(f"""
            () => {{
                const allElements = document.querySelectorAll('a, label, span, button, li, div');
                for (const el of allElements) {{
                    if (el.textContent.trim() === '{group}조') {{ el.click(); return true; }}
                }}
                const inputs = document.querySelectorAll('input[type="radio"], input[type="button"]');
                for (const input of inputs) {{
                    if (input.value === '{group}') {{ input.click(); return true; }}
                }}
                const dataEls = document.querySelectorAll('[data-val="{group}"], [data-value="{group}"]');
                if (dataEls.length > 0) {{ dataEls[0].click(); return true; }}
                return false;
            }}
        """)
    else:
        return page.evaluate(f"""
            () => {{
                const iframe = document.querySelector('#ifrm_tab');
                if (!iframe || !iframe.contentDocument) return false;
                const doc = iframe.contentDocument;
                const allElements = doc.querySelectorAll('a, label, span, button, li, div');
                for (const el of allElements) {{
                    if (el.textContent.trim() === '{group}조') {{ el.click(); return true; }}
                }}
                const inputs = doc.querySelectorAll('input[type="radio"], input[type="button"]');
                for (const input of inputs) {{
                    if (input.value === '{group}') {{ input.click(); return true; }}
                }}
                const dataEls = doc.querySelectorAll('[data-val="{group}"], [data-value="{group}"]');
                if (dataEls.length > 0) {{ dataEls[0].click(); return true; }}
                return false;
            }}
        """)


def _extract_720_numbers(page: Page, direct_mode: bool) -> list:
    """720+ 자동 생성된 번호 추출"""
    try:
        js_body = """
            const games = [];
            const rows = doc.querySelectorAll('.selected_game_list tr, .game_list tr, .tbl_number tbody tr');
            for (const row of rows) {
                const nums = [];
                row.querySelectorAll('span[class*="ball"], span[class*="num"], .num').forEach(el => {
                    const n = parseInt(el.textContent.trim());
                    if (!isNaN(n) && n >= 0 && n <= 9) nums.push(n);
                });
                if (nums.length >= 6) games.push(nums.slice(0, 7));
            }
            if (games.length === 0) {
                let current = [];
                doc.querySelectorAll('.ball720, span[class*="ball"], .lotto720_num span').forEach(el => {
                    const n = parseInt(el.textContent.trim());
                    if (!isNaN(n) && n >= 0 && n <= 9) {
                        current.push(n);
                        if (current.length === 7) { games.push([...current]); current = []; }
                    }
                });
            }
            return games;
        """

        if direct_mode:
            numbers = page.evaluate(f"() => {{ const doc = document; {js_body} }}")
        else:
            numbers = page.evaluate(f"""
                () => {{
                    const iframe = document.querySelector('#ifrm_tab');
                    if (!iframe || !iframe.contentDocument) return [];
                    const doc = iframe.contentDocument;
                    {js_body}
                }}
            """)

        if numbers:
            print(f'🎱 추출된 번호: {numbers}')
        else:
            print('⚠️ 720+ 번호 추출 실패 (빈 배열)')
        return numbers or []
    except Exception as e:
        print(f'⚠️ 720+ 번호 추출 오류: {e}')
        return []


def run(playwright: Playwright, dry_run: bool = False) -> None:
    """독립 실행용"""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    try:
        login(page)
        num_games = int(environ.get('LOTTO720_GAMES', '1'))
        if num_games <= 0:
            print("LOTTO720_GAMES not set")
            return
        result = buy_lotto720(page, num_games, dry_run=dry_run)
        print(f"Result: {result}")
    except Exception as e:
        print(f"Error: {e}")
        page.screenshot(path="debug_error.png")
        raise
    finally:
        context.close()
        browser.close()


if __name__ == "__main__":
    import sys
    dry_run = '--dry-run' in sys.argv
    if dry_run:
        print('🧪 DRY RUN 모드: 구매 직전까지만 진행합니다')
    with sync_playwright() as playwright:
        run(playwright, dry_run=dry_run)
