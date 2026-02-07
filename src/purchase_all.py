#!/usr/bin/env python3
"""
통합 구매 스크립트 - 한 번의 로그인으로 모든 작업 수행
잔액 확인 → (필요시 충전) → 로또 구매
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

# .env loading is handled by login module import

AUTO_GAMES = int(environ.get('AUTO_GAMES', '0'))
MANUAL_NUMBERS = json.loads(environ.get('MANUAL_NUMBERS', '[]'))


def get_balance(page: Page) -> dict:
    """마이페이지에서 예치금 잔액과 구매가능 금액을 조회합니다."""
    page.goto("https://www.dhlottery.co.kr/mypage/home", timeout=60000, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=30000)

    print(f"📍 Current URL: {page.url}")

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


def buy_lotto645(page: Page, auto_games: int, manual_numbers: list) -> bool:
    """로또 6/45를 구매합니다."""
    # Navigate to game page
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
        return False

    # Verify payment amount
    time.sleep(1)
    payment_amount_el = page.locator("#payAmt")
    payment_text = payment_amount_el.inner_text().strip()
    payment_amount = int(re.sub(r'[^0-9]', '', payment_text))
    expected_amount = total_games * 1000

    if payment_amount != expected_amount:
        print(f'❌ Error: Payment mismatch (Expected {expected_amount}, Displayed {payment_amount})')
        return False

    # Purchase
    page.click("#btnBuy")

    # Confirm purchase popup
    page.click("#popupLayerConfirm input[value='확인']")

    # Check for purchase limit
    time.sleep(3)

    limit_popup = page.locator("#recommend720Plus")
    if limit_popup.is_visible():
        print("❌ Error: Weekly purchase limit exceeded.")
        content = limit_popup.locator(".cont1").inner_text()
        print(f"   Message: {content.strip()}")
        return False

    print(f'✅ Lotto 6/45: All {total_games} games purchased successfully!')
    return True


def run(playwright: Playwright) -> None:
    """메인 실행 함수 - 한 번의 로그인으로 모든 작업 수행"""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    try:
        # Step 1: Login (한 번만)
        print("=" * 40)
        print("🔐 Logging in...")
        login(page)

        # Step 2: Check balance
        print("=" * 40)
        print("💰 Checking balance...")
        balance_info = get_balance(page)
        print(f"💰 예치금 잔액: {balance_info['deposit_balance']:,}원")
        print(f"🛒 구매가능: {balance_info['available_amount']:,}원")

        # Step 3: Check if we have enough balance
        total_games = AUTO_GAMES + len(MANUAL_NUMBERS)
        required_amount = total_games * 1000

        if total_games == 0:
            print("⚠️  No games configured. Set AUTO_GAMES or MANUAL_NUMBERS in .env")
            return

        if balance_info['available_amount'] < required_amount:
            print(f"❌ Insufficient balance. Need {required_amount:,}원, have {balance_info['available_amount']:,}원")
            return

        # Step 4: Buy Lotto 645
        print("=" * 40)
        print("🎫 Buying Lotto 645...")
        success = buy_lotto645(page, AUTO_GAMES, MANUAL_NUMBERS)

        if success:
            print("=" * 40)
            print("✅ All tasks completed successfully!")
        else:
            print("=" * 40)
            print("❌ Purchase failed!")

    except Exception as e:
        print(f"❌ Error: {e}")
        page.screenshot(path="debug_error.png")
        print("📸 Screenshot saved: debug_error.png")
        raise
    finally:
        context.close()
        browser.close()


if __name__ == "__main__":
    with sync_playwright() as playwright:
        run(playwright)
