#!/usr/bin/env python3
"""
당첨 확인 스크립트 - 최근 구매 내역의 당첨 결과를 확인하고 Telegram 알림 전송
"""
import re
import time
from os import environ
from playwright.sync_api import Playwright, sync_playwright, Page
from login import login
from notify import send_winning_notification, send_error_notification


def get_balance(page: Page) -> int:
    """예치금 잔액을 조회합니다."""
    page.goto("https://www.dhlottery.co.kr/mypage/home", timeout=60000, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=30000)
    deposit_el = page.locator("#totalAmt")
    deposit_text = deposit_el.inner_text().strip()
    return int(re.sub(r'[^0-9]', '', deposit_text))


def check_winning(page: Page) -> list:
    """최근 구매 내역의 당첨 결과를 확인합니다."""
    page.goto(
        "https://www.dhlottery.co.kr/mypage/lottoBuyListView.do",
        timeout=60000, wait_until="domcontentloaded",
    )
    page.wait_for_load_state("networkidle", timeout=30000)

    # Click search button to load results
    try:
        search_btn = page.locator("input[value='조회'], button:has-text('조회')")
        if search_btn.first.is_visible(timeout=3000):
            search_btn.first.click()
            page.wait_for_load_state("networkidle", timeout=15000)
            time.sleep(2)
    except Exception:
        pass

    page.screenshot(path="debug_winning_check.png")
    print(f"Current URL: {page.url}")

    # Extract results from the purchase history table
    results = page.evaluate("""
        () => {
            const results = [];

            const rows = document.querySelectorAll(
                '.tbl_data tbody tr, table.tbl_data_round tbody tr, #tblBuyList tbody tr'
            );

            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length < 3) continue;

                const nums = [];
                row.querySelectorAll('span[class*="ball"]').forEach(el => {
                    const n = parseInt(el.textContent.trim());
                    if (!isNaN(n) && n >= 1 && n <= 45) nums.push(n);
                });

                const rowText = row.textContent;

                let rank = '미당첨';
                const rankMatch = rowText.match(/(\\d)등/);
                if (rankMatch) rank = rankMatch[1];

                let prize = 0;
                for (let i = cells.length - 1; i >= 0; i--) {
                    const text = cells[i].textContent.trim();
                    const m = text.match(/([\\d,]+)원/);
                    if (m) {
                        const val = parseInt(m[1].replace(/,/g, ''));
                        if (val > 0 && val !== nums.length) {
                            prize = val;
                            break;
                        }
                    }
                }

                if (nums.length === 6) {
                    results.push({ numbers: nums, rank: rank, prize: prize });
                }
            }

            return results;
        }
    """)

    return results


def run(playwright: Playwright) -> None:
    """메인 실행 함수"""
    import os
    use_headless = os.environ.get('FORCE_HEADLESS') == '1'
    browser = playwright.chromium.launch(
        headless=use_headless,
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
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        window.chrome = { runtime: {} };
    """)

    try:
        print("=" * 40)
        print("Logging in...")
        login(page)

        print("=" * 40)
        print("Checking winning results...")
        results = check_winning(page)

        print("=" * 40)
        print("Checking balance...")
        balance = get_balance(page)

        has_won = any(r.get('rank') != '미당첨' for r in results)
        total_prize = sum(r.get('prize', 0) for r in results if r.get('rank') != '미당첨')

        if has_won:
            print(f"Prize: {total_prize:,} won")
        else:
            print("No winning this time")

        for r in results:
            print(f"  {r['numbers']} -> {r['rank']} ({r['prize']:,} won)")

        print(f"Balance: {balance:,} won")

        send_winning_notification(
            has_won=has_won,
            results=results,
            total_prize=total_prize,
            balance=balance,
        )

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
