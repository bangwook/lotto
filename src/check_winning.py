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


def get_645_winning_numbers(page: Page) -> dict:
    """645 최근 회차 당첨번호 조회 (1~5등)"""
    try:
        # 동행복권 645 결과 조회 페이지
        page.goto(
            "https://www.dhlottery.co.kr/gameResult.do?method=byWin",
            timeout=30000, wait_until="networkidle",
        )
        time.sleep(1)
        page.screenshot(path="debug_645_winning.png")

        result = page.evaluate("""
            () => {
                // 회차
                const round_el = document.querySelector('.win_result strong, .num_box strong, h4 strong');
                const round_text = round_el ? round_el.textContent.trim() : '';
                const round_match = round_text.match(/(\\d+)/);
                const round = round_match ? parseInt(round_match[1]) : 0;

                // 1등 6자리 + 보너스
                const balls = [];
                document.querySelectorAll('.win_result .num span, .nums .ball, .num.win span, span[class*="ball"]').forEach(el => {
                    const n = parseInt(el.textContent.trim());
                    if (!isNaN(n) && n >= 1 && n <= 45) balls.push(n);
                });

                // 1등 번호 6개, 보너스 1개
                const winning = balls.slice(0, 6);
                const bonus = balls[6] || null;

                return { round, winning, bonus };
            }
        """)
        return result
    except Exception as e:
        print(f'⚠️ 645 당첨번호 조회 실패: {e}')
        return {'round': 0, 'winning': [], 'bonus': None}


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
    """720+ 최근 회차 당첨번호 조회"""
    try:
        page.goto(
            "https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LP72",
            timeout=30000, wait_until="networkidle",
        )
        time.sleep(2)
        page.screenshot(path="debug_720_winning.png")

        # iframe 내부에서 추출
        result = page.evaluate("""
            () => {
                const iframe = document.querySelector('#ifrm_tab');
                const doc = iframe?.contentDocument || document;

                // 회차
                let round = 0;
                doc.querySelectorAll('strong, h4, h3, .round').forEach(el => {
                    const m = el.textContent.match(/제\\s*(\\d+)\\s*회/);
                    if (m && !round) round = parseInt(m[1]);
                });

                // 1등 당첨번호: 조 + 6자리
                // 2등 보너스: 6자리
                const text = doc.body.innerText;
                const lines = text.split('\\n').map(s => s.trim()).filter(Boolean);

                let group = '';
                const winning = [];
                const bonus = [];

                // "N조" 다음에 6개 숫자 (1등)
                for (let i = 0; i < lines.length; i++) {
                    const m = lines[i].match(/^(\\d)$/);
                    if (m && lines[i-1] === '조') {
                        group = m[1];
                        for (let j = i + 1; j < Math.min(i + 7, lines.length); j++) {
                            const n = parseInt(lines[j]);
                            if (!isNaN(n) && n >= 0 && n <= 9) winning.push(n);
                            else break;
                        }
                        break;
                    }
                }

                return { round, group, winning, bonus };
            }
        """)
        return result
    except Exception as e:
        print(f'⚠️ 720+ 당첨번호 조회 실패: {e}')
        return {'round': 0, 'group': '', 'winning': [], 'bonus': []}


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
    page.screenshot(path="debug_ledger.png")
    print(f"Current URL: {page.url}")

    # 645와 720 구매내역 추출
    data = page.evaluate("""
        () => {
            const lotto645 = [];
            const lotto720 = [];

            // 모든 행 검사
            const rows = document.querySelectorAll('tr, li');
            for (const row of rows) {
                const text = row.textContent;
                const balls = [...row.querySelectorAll('span[class*="ball"]')]
                    .map(el => parseInt(el.textContent.trim()))
                    .filter(n => !isNaN(n));

                if (balls.length === 0) continue;

                // 645 식별: 6개 ball, 모두 1-45 범위
                const valid645 = balls.filter(n => n >= 1 && n <= 45);
                if (valid645.length >= 6 && valid645.length <= 7) {
                    // 회차/등수 추출
                    const rankMatch = text.match(/(\\d)등/);
                    const roundMatch = text.match(/(\\d+)\\s*회/);
                    lotto645.push({
                        numbers: valid645.slice(0, 6),
                        rank: rankMatch ? rankMatch[1] : '미당첨',
                        round: roundMatch ? parseInt(roundMatch[1]) : 0,
                    });
                    continue;
                }

                // 720 식별: 1자리 숫자 7개 (조 + 6자리)
                const valid720 = balls.filter(n => n >= 0 && n <= 9);
                if (valid720.length === 7) {
                    const rankMatch = text.match(/(\\d)등/);
                    const roundMatch = text.match(/(\\d+)\\s*회/);
                    lotto720.push({
                        group: String(valid720[0]),
                        digits: valid720.slice(1, 7),
                        rank: rankMatch ? rankMatch[1] : '미당첨',
                        round: roundMatch ? parseInt(roundMatch[1]) : 0,
                    });
                }
            }

            return { lotto645, lotto720 };
        }
    """)
    return data


def run(playwright: Playwright) -> None:
    """메인 실행 함수"""
    import os
    use_headless = os.environ.get('FORCE_HEADLESS') == '1'
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

        print("=" * 40)
        print("🎯 645 당첨번호 조회...")
        win645 = get_645_winning_numbers(page)
        print(f"  {win645['round']}회: {win645['winning']} + 보너스 {win645['bonus']}")

        print("=" * 40)
        print("🎯 720+ 당첨번호 조회...")
        win720 = get_720_winning_numbers(page)
        print(f"  {win720['round']}회: {win720['group']}조 {win720['winning']}")

        print("=" * 40)
        print("Checking balance...")
        balance = get_balance(page)
        print(f"💰 잔액: {balance:,}원")

        # 645 결과 계산 및 알림
        if purchases['lotto645']:
            results_645 = []
            for p in purchases['lotto645']:
                rank = calc_645_rank(p['numbers'], win645['winning'], win645['bonus'])
                results_645.append({
                    'numbers': p['numbers'],
                    'rank': rank,
                })
            send_645_winning(
                round_no=win645['round'],
                winning=win645['winning'],
                bonus=win645['bonus'],
                my_games=results_645,
                balance=balance,
            )
            print(f'✅ 645 알림 전송')

        # 720 결과 계산 및 알림
        if purchases['lotto720']:
            results_720 = []
            for p in purchases['lotto720']:
                rank = calc_720_rank(p['group'], p['digits'], win720['group'], win720['winning'])
                results_720.append({
                    'group': p['group'],
                    'digits': p['digits'],
                    'rank': rank,
                })
            send_720_winning(
                round_no=win720['round'],
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
