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
        dict: {'success': bool, 'groups': list[int], 'details': str}
    """
    if num_games <= 0:
        return {'success': False, 'groups': [], 'details': '구매할 매수 없음'}

    # el.dhlottery.co.kr 서브도메인에 세션 쿠키 복사
    # 로그인은 www.dhlottery.co.kr에서 이루어지므로 el. 도메인에 쿠키가 없을 수 있음
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

    # Navigate to the wrapper page
    page.goto(
        "https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LP72",
        timeout=60000, wait_until="networkidle",
    )

    # Wait for iframe to be created and its src to be set by JS
    time.sleep(5)

    # iframe이 보이지 않으면 src를 직접 설정 후 재시도
    for attempt in range(3):
        try:
            page.locator("#ifrm_tab").wait_for(state="visible", timeout=15000)
            # iframe src가 비어있으면 직접 설정
            iframe_src = page.evaluate("""
                () => {
                    const iframe = document.querySelector('#ifrm_tab');
                    return iframe ? iframe.src : '';
                }
            """)
            if not iframe_src or iframe_src == 'about:blank':
                print(f'⚠️ iframe src가 비어있음, 직접 설정 시도...')
                page.evaluate("""
                    () => {
                        const iframe = document.querySelector('#ifrm_tab');
                        if (iframe) {
                            iframe.src = '/game/lottery720/game.do';
                        }
                    }
                """)
                time.sleep(3)
            break
        except Exception:
            if attempt < 2:
                print(f'⚠️ iframe 로딩 대기 중... (시도 {attempt + 1}/3)')
                page.screenshot(path=f"debug_720_attempt_{attempt}.png")
                # iframe이 없으면 페이지 구조 디버깅
                page.evaluate("""
                    () => {
                        const iframe = document.querySelector('#ifrm_tab');
                        console.log('iframe exists:', !!iframe);
                        if (iframe) {
                            console.log('iframe src:', iframe.src);
                            console.log('iframe display:', iframe.style.display);
                            console.log('iframe dimensions:', iframe.offsetWidth, iframe.offsetHeight);
                        }
                    }
                """)
                page.reload(wait_until="networkidle", timeout=60000)
                time.sleep(5)
            else:
                page.screenshot(path="debug_720_iframe_fail.png")
                print('📸 Screenshot saved: debug_720_iframe_fail.png')
                # 마지막 시도: 디버그 정보 출력
                debug_info = page.evaluate("""
                    () => {
                        const iframe = document.querySelector('#ifrm_tab');
                        return {
                            iframeExists: !!iframe,
                            iframeSrc: iframe ? iframe.src : 'N/A',
                            iframeDisplay: iframe ? iframe.style.display : 'N/A',
                            pageTitle: document.title,
                            bodyText: document.body.innerText.substring(0, 500),
                        };
                    }
                """)
                print(f'🔍 디버그 정보: {debug_info}')
                return {
                    'success': False, 'groups': [],
                    'details': f'iframe #ifrm_tab 로딩 실패 (3회 시도). debug: {debug_info}',
                }

    frame = page.frame_locator("#ifrm_tab")

    # Wait for iframe content
    try:
        frame.locator("#curdeposit, .lpdeposit").first.wait_for(state="attached", timeout=30000)
    except Exception:
        page.screenshot(path="debug_720_content_fail.png")
        print('📸 Screenshot saved: debug_720_content_fail.png')
        # 한 번 더 재시도
        page.reload(wait_until="networkidle", timeout=60000)
        time.sleep(3)
        try:
            page.locator("#ifrm_tab").wait_for(state="visible", timeout=15000)
            frame.locator("#curdeposit, .lpdeposit").first.wait_for(state="attached", timeout=30000)
        except Exception:
            return {
                'success': False, 'groups': [],
                'details': 'iframe 내부 콘텐츠 로딩 실패',
            }

    print('✅ Navigated to Lotto 720 Game Frame')

    time.sleep(1)

    # Verify session
    user_id_val = frame.locator("input[name='USER_ID']").get_attribute("value")
    if not user_id_val:
        return {'success': False, 'groups': [], 'details': '세션 만료 (USER_ID 없음)'}

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
            'success': False, 'groups': [],
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
    page.evaluate("""
        () => {
            const iframe = document.querySelector('#ifrm_tab');
            if (iframe && iframe.contentDocument) {
                const doc = iframe.contentDocument;
                [
                    '#pause_layer_pop_02', '#ele_pause_layer_pop02',
                    '.pause_layer_pop', '.pause_bg'
                ].forEach(sel => {
                    doc.querySelectorAll(sel).forEach(el => {
                        el.style.display = 'none';
                        el.style.visibility = 'hidden';
                        el.style.pointerEvents = 'none';
                    });
                });
            }
        }
    """)

    # Select games with random groups
    groups = []
    for i in range(num_games):
        group = random.randint(1, 5)
        groups.append(group)

        # Select the specific group in the iframe
        selected = page.evaluate(f"""
            () => {{
                const iframe = document.querySelector('#ifrm_tab');
                if (!iframe || !iframe.contentDocument) return false;
                const doc = iframe.contentDocument;

                // Strategy 1: Click element with exact text "N조"
                const allElements = doc.querySelectorAll('a, label, span, button, li, div');
                for (const el of allElements) {{
                    const text = el.textContent.trim();
                    if (text === '{group}조') {{
                        el.click();
                        return true;
                    }}
                }}

                // Strategy 2: Radio/input with value
                const inputs = doc.querySelectorAll('input[type="radio"], input[type="button"]');
                for (const input of inputs) {{
                    if (input.value === '{group}') {{
                        input.click();
                        return true;
                    }}
                }}

                // Strategy 3: data attribute
                const dataEls = doc.querySelectorAll('[data-val="{group}"], [data-value="{group}"]');
                if (dataEls.length > 0) {{
                    dataEls[0].click();
                    return true;
                }}

                return false;
            }}
        """)

        if selected:
            print(f'✅ {group}조 선택됨')
        else:
            print(f'⚠️ {group}조 선택 실패, 기본값 사용')

        time.sleep(0.5)

        # Click auto number
        frame.locator(".lotto720_btn_auto_number").click(force=True)
        time.sleep(1)
        print(f'✅ 자동번호 {i + 1}/{num_games} 생성')

    # Confirm selection
    frame.locator(".lotto720_btn_confirm_number").click()
    time.sleep(2)

    # 구매 금액은 num_games * 1000으로 고정 (잔액 검증은 위에서 완료)
    print(f'💰 구매 금액: {num_games * 1000:,}원 ({num_games}매)')

    # Dry run: 구매 직전에서 중단
    if dry_run:
        page.screenshot(path="debug_720_dry_run.png")
        print(f'🧪 [DRY RUN] 구매 직전 중단. 조: {groups}, 금액: {num_games * 1000:,}원')
        print('📸 Screenshot saved: debug_720_dry_run.png')
        return {'success': True, 'groups': groups, 'details': 'dry_run - 구매 미실행'}

    # Purchase
    frame.locator("a:has-text('구매하기')").first.click()

    # Confirm popup
    confirm_popup = frame.locator("#lotto720_popup_confirm")
    confirm_popup.wait_for(state="visible", timeout=5000)
    confirm_popup.locator("a.btn_blue").click()

    time.sleep(2)
    print(f'✅ Lotto 720: {num_games}매 구매 완료! (조: {groups})')
    return {'success': True, 'groups': groups, 'details': ''}


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
