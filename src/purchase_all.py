#!/usr/bin/env python3
"""
통합 구매 스크립트 - 한 번의 로그인으로 모든 작업 수행
잔액 확인 → 로또 6/45 구매 → 연금복권 720+ 구매 → Telegram 알림
"""
import json
import re
import sys
import time
from os import environ
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import Playwright, sync_playwright, Page
from login import login
from lotto720 import buy_lotto720
from notify import send_purchase_notification, send_error_notification, send_lotto645_notification, send_lotto720_notification

# .env loading is handled by login module import

AUTO_GAMES = int(environ.get('AUTO_GAMES', '0'))
MANUAL_NUMBERS = json.loads(environ.get('MANUAL_NUMBERS', '[]'))
LOTTO720_GAMES = int(environ.get('LOTTO720_GAMES', '0'))
PURCHASE_TARGET = environ.get('PURCHASE_TARGET', 'all')  # 'all', '645', '720'


def get_balance(page: Page) -> dict:
    """마이페이지에서 예치금 잔액과 구매가능 금액을 조회합니다."""
    page.goto("https://www.dhlottery.co.kr/mypage/home", timeout=60000, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=30000)

    print(f"📍 Current URL: {page.url}")

    # 로그인 페이지로 리다이렉트된 경우 재로그인
    if "login" in page.url.lower() and "check" not in page.url.lower():
        print("⚠️ 세션 만료 감지, 재로그인 시도...")
        login(page)
        page.goto("https://www.dhlottery.co.kr/mypage/home", timeout=60000, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=30000)
        print(f"📍 재로그인 후 URL: {page.url}")

    deposit_el = page.locator("#totalAmt")
    deposit_text = deposit_el.inner_text().strip()

    available_el = page.locator("#divCrntEntrsAmt")
    available_text = available_el.inner_text().strip()

    deposit_balance = int(re.sub(r'[^0-9]', '', deposit_text))
    available_amount = int(re.sub(r'[^0-9]', '', available_text))

    return {
        'deposit_balance': deposit_balance,
        'available_amount': available_amount
    }


def extract_game_numbers(page: Page) -> list:
    """선택된 게임 번호를 페이지에서 추출합니다."""
    try:
        games = page.evaluate("""
            () => {
                const games = [];

                // 645 전용 ball 셀렉터 (span[class*="num"]은 너무 넓어서 제외)
                const selector = 'span[class*="ball"], .ball_645, .ballnum';

                // 방법 1: 테이블 행 단위로 추출
                const rows = document.querySelectorAll(
                    '#tblNum tbody tr, .tbl_display tbody tr, #reportRow tr, .tbl_data tbody tr, #popReceipt tr'
                );
                for (const row of rows) {
                    const nums = [];
                    row.querySelectorAll(selector).forEach(el => {
                        const n = parseInt(el.textContent.trim());
                        if (!isNaN(n) && n >= 1 && n <= 45) nums.push(n);
                    });
                    // 6개 이상이면 앞 6개 사용 (행에 보너스 번호 등 추가 요소 가능)
                    if (nums.length >= 6) games.push(nums.slice(0, 6));
                }

                // 방법 2: 전체 ball 요소에서 6개씩 묶어서 추출
                if (games.length === 0) {
                    let current = [];
                    document.querySelectorAll(selector).forEach(el => {
                        const n = parseInt(el.textContent.trim());
                        if (!isNaN(n) && n >= 1 && n <= 45) {
                            current.push(n);
                            if (current.length === 6) {
                                games.push([...current]);
                                current = [];
                            }
                        }
                    });
                }

                return games;
            }
        """)
        return games if games else []
    except Exception as e:
        print(f"⚠️ 번호 추출 실패: {e}")
        return []


def buy_lotto645(page: Page, auto_games: int, manual_numbers: list) -> dict:
    """로또 6/45를 구매합니다. 결과를 dict로 반환합니다."""
    page.goto("https://ol.dhlottery.co.kr/olotto/game/game645.do", timeout=60000, wait_until="domcontentloaded")
    print('✅ Navigated to Lotto 6/45 page')

    page.wait_for_load_state("networkidle")

    # Remove popup layers
    page.evaluate("""
        () => {
            const selectors = [
                '#pause_layer_pop_02',
                '#ele_pause_layer_pop02',
                '.pause_layer_pop',
                '.pause_bg'
            ];
            selectors.forEach(selector => {
                const elements = document.querySelectorAll(selector);
                elements.forEach(el => {
                    el.style.display = 'none';
                    el.style.visibility = 'hidden';
                    el.style.pointerEvents = 'none';
                });
            });
        }
    """)

    # Dismiss popup if present
    try:
        popup_alert = page.locator("#popupLayerAlert")
        if popup_alert.is_visible(timeout=2000):
            popup_alert.get_by_role("button", name="확인").click(force=True, timeout=5000)
            print('✅ Dismissed popup alert')
    except Exception as e:
        print(f'⚠️  Popup handling: {str(e)}')

    # Manual numbers
    if manual_numbers and len(manual_numbers) > 0:
        for game in manual_numbers:
            for number in game:
                page.click(f'label[for="check645num{number}"]', force=True)
            page.click("#btnSelectNum")
            print(f'✅ Manual game added: {game}')

    # Automatic games
    if auto_games > 0:
        page.click("#num2")
        page.select_option("#amoundApply", str(auto_games))
        page.click("#btnSelectNum")
        print(f'✅ Automatic game(s) added: {auto_games}')

    # Check if any games were added
    total_games = len(manual_numbers) + auto_games
    if total_games == 0:
        print('⚠️  No games to purchase!')
        return {'success': False, 'numbers': [], 'details': '구매할 게임 없음'}

    # 구매 전 번호 추출은 스킵 (DOM에 번호가 즉시 반영되지 않음)
    # 구매 완료 후 영수증에서 추출
    numbers = []

    # Verify payment amount
    payment_amount_el = page.locator("#payAmt")
    payment_text = payment_amount_el.inner_text().strip()
    payment_amount = int(re.sub(r'[^0-9]', '', payment_text))
    expected_amount = total_games * 1000

    if payment_amount != expected_amount:
        msg = f'결제 금액 불일치 (예상: {expected_amount}, 표시: {payment_amount})'
        print(f'❌ Error: {msg}')
        return {'success': False, 'numbers': numbers, 'details': msg}

    # Purchase
    page.click("#btnBuy")

    # Confirm purchase popup
    page.click("#popupLayerConfirm input[value='확인']")

    # Check for purchase limit
    time.sleep(3)

    limit_popup = page.locator("#recommend720Plus")
    if limit_popup.is_visible():
        content = limit_popup.locator(".cont1").inner_text()
        msg = f'주간 구매 한도 초과: {content.strip()}'
        print(f"❌ Error: {msg}")
        return {'success': False, 'numbers': numbers, 'details': msg}

    # 구매 완료 후 영수증에서 번호 추출
    print('🔄 구매 완료 후 번호 추출...')
    time.sleep(2)
    numbers = page.evaluate("""
        () => {
            const games = [];
            // 영수증/결과 영역의 모든 컨테이너 탐색
            // 각 게임 행을 찾아서 번호 추출
            const containers = document.querySelectorAll(
                '#popReceipt .tbl_data tbody tr, ' +
                '#reportRow tr, ' +
                '.tbl_display tbody tr, ' +
                '.selected_list li, ' +
                '.game_list li, ' +
                '.nums'
            );
            for (const row of containers) {
                const nums = [];
                row.querySelectorAll('span.ball, span[class*="ball"]').forEach(el => {
                    const n = parseInt(el.textContent.trim());
                    if (!isNaN(n) && n >= 1 && n <= 45) nums.push(n);
                });
                if (nums.length >= 6) games.push(nums.slice(0, 6));
            }

            // 대안: 영수증 내 ball 요소를 6개씩 묶기
            if (games.length === 0) {
                // 영수증 팝업 또는 결과 영역 내에서만 검색
                const receiptArea = document.querySelector('#popReceipt, #reportRow, .tbl_display, .result_area');
                if (receiptArea) {
                    let current = [];
                    receiptArea.querySelectorAll('span.ball, span[class*="ball"]').forEach(el => {
                        const n = parseInt(el.textContent.trim());
                        if (!isNaN(n) && n >= 1 && n <= 45) {
                            current.push(n);
                            if (current.length === 6) {
                                games.push([...current]);
                                current = [];
                            }
                        }
                    });
                }
            }

            // 마지막 대안: 페이지 전체 디버그 (어떤 영역에 번호가 있는지)
            if (games.length === 0) {
                const allBalls = document.querySelectorAll('span.ball, span[class*="ball"]');
                const validNums = [];
                allBalls.forEach(el => {
                    const n = parseInt(el.textContent.trim());
                    if (!isNaN(n) && n >= 1 && n <= 45) {
                        validNums.push({ n, parent: el.parentElement?.className || '', grandparent: el.parentElement?.parentElement?.className || '' });
                    }
                });
                console.log('DEBUG ball parents:', JSON.stringify(validNums.slice(0, 12)));
            }

            return games;
        }
    """)
    if numbers:
        print(f'🎱 추출된 번호: {numbers}')
    else:
        # 디버그: 구매 후 페이지에서 번호가 있는 영역 찾기
        debug = page.evaluate("""
            () => {
                const allBalls = document.querySelectorAll('span.ball, span[class*="ball"]');
                const valid = [];
                allBalls.forEach(el => {
                    const n = parseInt(el.textContent.trim());
                    if (!isNaN(n) && n >= 1 && n <= 45) {
                        valid.push({
                            num: n,
                            parentClass: el.parentElement?.className || '',
                            parentId: el.parentElement?.id || '',
                            gpClass: el.parentElement?.parentElement?.className || '',
                            gpId: el.parentElement?.parentElement?.id || '',
                        });
                    }
                });
                return valid.slice(0, 18);
            }
        """)
        print(f'🔍 번호 요소 디버그 (상위 {len(debug)}개): {debug}')
    if not numbers and manual_numbers:
        numbers = [list(game) for game in manual_numbers]

    print(f'✅ Lotto 6/45: All {total_games} games purchased successfully!')
    return {'success': True, 'numbers': numbers, 'details': ''}


def run(playwright: Playwright) -> None:
    """메인 실행 함수 - 한 번의 로그인으로 모든 작업 수행"""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        viewport={'width': 1920, 'height': 1080},
    )
    page = context.new_page()

    current_balance = 0

    try:
        # Step 1: Login
        print("=" * 40)
        print("🔐 Logging in...")
        login(page)

        # Step 2: Check balance
        print("=" * 40)
        print("💰 Checking balance...")
        balance_info = get_balance(page)
        current_balance = balance_info['deposit_balance']
        print(f"💰 예치금 잔액: {balance_info['deposit_balance']:,}원")
        print(f"🛒 구매가능: {balance_info['available_amount']:,}원")

        # Step 3: Calculate required amounts per target
        buy_645 = PURCHASE_TARGET in ('all', '645')
        buy_720 = PURCHASE_TARGET in ('all', '720')

        lotto645_games = (AUTO_GAMES + len(MANUAL_NUMBERS)) if buy_645 else 0
        lotto645_cost = lotto645_games * 1000
        lotto720_cost = (LOTTO720_GAMES * 1000) if buy_720 else 0
        total_required = lotto645_cost + lotto720_cost

        print(f"🎯 구매 대상: {PURCHASE_TARGET} (645: {lotto645_games}게임, 720: {LOTTO720_GAMES if buy_720 else 0}매)")

        if lotto645_games == 0 and (not buy_720 or LOTTO720_GAMES == 0):
            print("⚠️  No games configured.")
            send_error_notification(
                "로또 구매",
                "구매할 게임이 설정되지 않았습니다 (AUTO_GAMES / MANUAL_NUMBERS / LOTTO720_GAMES)",
            )
            return

        if balance_info['available_amount'] < total_required:
            msg = f"잔액 부족 (필요: {total_required:,}원, 보유: {balance_info['available_amount']:,}원)"
            print(f"❌ {msg}")
            send_error_notification("로또 구매", msg)
            return

        # Step 4: Buy Lotto 6/45 (with separate notification)
        if lotto645_games > 0:
            print("=" * 40)
            print("🎫 Buying Lotto 6/45...")
            lotto645_success = False
            lotto645_numbers = []
            lotto645_details = ''

            try:
                purchase_result = buy_lotto645(page, AUTO_GAMES, MANUAL_NUMBERS)
                lotto645_numbers = purchase_result['numbers']
                lotto645_success = purchase_result['success']
                lotto645_details = purchase_result.get('details', '')
            except Exception as e:
                print(f"❌ 로또 6/45 구매 중 오류: {e}")
                lotto645_details = str(e)
                # 스크린샷 저장 시도 (실패해도 무시)
                try:
                    page.screenshot(path="debug_lotto645_error.png")
                except Exception:
                    print("⚠️ 스크린샷 저장 실패")

            # Re-check balance after 6/45 purchase (실패해도 무시)
            try:
                post_645_balance = get_balance(page)
                current_balance = post_645_balance['deposit_balance']
            except Exception:
                print("⚠️ 잔액 조회 실패, 이전 잔액 사용")

            # 6/45 알림 전송 (반드시 실행)
            try:
                send_lotto645_notification(
                    success=lotto645_success,
                    numbers=lotto645_numbers,
                    balance=current_balance,
                    details=lotto645_details,
                )
            except Exception as e:
                print(f"❌ 6/45 알림 전송 실패: {e}")

        # Step 5: Buy Lotto 720+ (with separate notification)
        if buy_720 and LOTTO720_GAMES > 0:
            print("=" * 40)
            print(f"🎫 Buying Lotto 720+ ({LOTTO720_GAMES}매)...")
            lotto720_success = False
            lotto720_groups = []
            lotto720_details = ''

            lotto720_numbers = []

            try:
                lotto720_result = buy_lotto720(page, LOTTO720_GAMES)
                lotto720_groups = lotto720_result.get('groups', [])
                lotto720_numbers = lotto720_result.get('numbers', [])
                lotto720_success = lotto720_result['success']
                lotto720_details = lotto720_result.get('details', '')
            except Exception as e:
                print(f"❌ 연금복권 720+ 구매 중 오류: {e}")
                lotto720_details = str(e)
                # 스크린샷 저장 시도 (실패해도 무시)
                try:
                    page.screenshot(path="debug_lotto720_error.png")
                except Exception:
                    print("⚠️ 스크린샷 저장 실패")

            # Re-check balance after 720+ purchase (실패해도 무시)
            try:
                post_720_balance = get_balance(page)
                current_balance = post_720_balance['deposit_balance']
            except Exception:
                print("⚠️ 잔액 조회 실패, 이전 잔액 사용")

            # 720+ 알림 전송 (반드시 실행)
            try:
                send_lotto720_notification(
                    success=lotto720_success,
                    groups=lotto720_groups,
                    balance=current_balance,
                    details=lotto720_details,
                    numbers=lotto720_numbers,
                )
            except Exception as e:
                print(f"❌ 720+ 알림 전송 실패: {e}")

        print("=" * 40)
        print("✅ All tasks completed!")

    except Exception as e:
        print(f"❌ Error: {e}")
        # 스크린샷 저장 시도 (실패해도 무시)
        try:
            page.screenshot(path="debug_error.png")
            print("📸 Screenshot saved: debug_error.png")
        except Exception:
            print("⚠️ 스크린샷 저장 실패")
        # 에러 알림 전송 (실패해도 무시)
        try:
            send_error_notification("로또 구매", str(e))
        except Exception as notify_err:
            print(f"❌ 에러 알림 전송 실패: {notify_err}")
        raise
    finally:
        context.close()
        browser.close()


if __name__ == "__main__":
    with sync_playwright() as playwright:
        run(playwright)
