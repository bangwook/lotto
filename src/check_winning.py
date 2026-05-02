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


def _detect_645_modal(page: Page) -> bool:
    """티켓 모달이 열렸는지 감지. 실제 모달 컨텐츠 키워드만으로 판정."""
    try:
        return page.evaluate(r"""
            () => {
                const text = (document.body.innerText || '');
                // 티켓 모달에만 존재하는 고유 키워드 조합
                // (메뉴/필터에는 없는 단어)
                if (text.includes('발행일') && text.includes('추첨일')) return true;
                if (text.includes('지급기한')) return true;
                if (text.includes('티켓 보기')) return true;
                return false;
            }
        """) or False
    except Exception:
        return False


def _enrich_645_from_ticket_modals(page: Page, lotto645: list) -> None:
    """ledger의 각 645 행 클릭 → 티켓 모달에서 번호 추출하여 entry['numbers'] 채움.

    실제 ledger 행은 li.whl-row. clickable 자식이 없으면 행 자체 또는 자손 모두에
    Playwright 실제 마우스 이벤트 발사 (JS .click()은 일부 이벤트만 트리거).
    """
    print(f'🔍 645 티켓 모달에서 번호 추출 시도 ({len(lotto645)}건)...')

    # 행 식별 + 풀 자식 디버그
    debug_info = page.evaluate(r"""
        () => {
            const selectors = [
                'li.whl-row', 'li[class*="whl-row"]',
                'tr.whl-row', 'li[class*="row"]:not([class*="header"]):not([class*="title"])',
            ];
            let rows = [];
            let usedSel = '';
            for (const sel of selectors) {
                rows = [...document.querySelectorAll(sel)].filter(r => (r.textContent || '').includes('로또6/45'));
                if (rows.length > 0) { usedSel = sel; break; }
            }

            const samples = rows.slice(0, 2).map(row => {
                const allDesc = [...row.querySelectorAll('*')];
                const descSummary = allDesc.map(el => ({
                    tag: el.tagName,
                    cls: ((el.className || '') + '').substring(0, 50),
                    text: (el.textContent || '').trim().substring(0, 30),
                    onclick: (el.getAttribute('onclick') || '').substring(0, 50),
                    cursor: getComputedStyle(el).cursor,
                    dataAttrs: [...el.attributes].filter(a => a.name.startsWith('data-')).map(a => `${a.name}=${a.value}`).join(' ').substring(0, 80),
                }));

                // 특수 태그 (img/svg/button/a/i) 추출
                const special = [...row.querySelectorAll('img, svg, button, a, i, [data-action], [data-target], [data-toggle]')]
                    .map(el => ({
                        tag: el.tagName,
                        cls: ((el.className || '') + '').substring(0, 50),
                        text: (el.textContent || '').trim().substring(0, 30),
                        outer: (el.outerHTML || '').substring(0, 200),
                    }));

                return {
                    tag: row.tagName,
                    cls: ((row.className || '') + '').substring(0, 60),
                    htmlFull: (row.outerHTML || '').substring(0, 3000),
                    descCount: allDesc.length,
                    descendants: descSummary,
                    special,
                };
            });

            window.__lotto645Rows = rows;
            return { count: rows.length, usedSel, samples };
        }
    """)
    print(f'  🔬 행 후보 {debug_info["count"]}개 (셀렉터: {debug_info.get("usedSel", "")})')
    for i, s in enumerate(debug_info.get('samples', [])):
        print(f'    행 {i}: <{s["tag"]}.{s["cls"]}> 자손 {s["descCount"]}개')
        print(f'    행 {i} 풀 HTML: {s["htmlFull"]}')
        print(f'    행 {i} 자손 전체:')
        for d in s.get('descendants', []):
            cursor = d.get('cursor', '')
            cur_marker = ' [pointer]' if cursor == 'pointer' else ''
            data = f' data="{d["dataAttrs"]}"' if d.get('dataAttrs') else ''
            print(f'      ▸ {d["tag"]}.{d["cls"]} text="{d["text"]}"{cur_marker}{data}')
        print(f'    행 {i} 특수 태그 (img/svg/button/a/i/data-*): {len(s.get("special", []))}개')
        for sp in s.get('special', []):
            print(f'      ✦ {sp["tag"]}.{sp["cls"]} text="{sp["text"]}"')
            print(f'        outer: {sp["outer"]}')

    for idx, entry in enumerate(lotto645):
        if entry.get('numbers'):
            continue

        opened = False
        # Playwright의 li.whl-row 행 자체를 click 시도
        try:
            row_locator = page.locator('li.whl-row').nth(idx)
            url_before = page.url

            # 시도 1: 행 자체 (Playwright 실제 마우스 이벤트)
            for trial_name, trial_fn in (
                ('row.click', lambda: row_locator.click(force=True, timeout=3000)),
                ('row.dblclick', lambda: row_locator.dblclick(force=True, timeout=3000)),
                ('row hover+click', lambda: (row_locator.hover(timeout=2000), row_locator.click(force=True, timeout=3000))),
            ):
                try:
                    trial_fn()
                    time.sleep(1.2)
                    url_after = page.url
                    if url_after != url_before:
                        print(f'  📍 #{idx + 1} {trial_name}: URL 변경 {url_before} → {url_after}')
                        url_before = url_after
                    if _detect_645_modal(page):
                        print(f'  ✅ #{idx + 1} {trial_name} 으로 모달 열림')
                        opened = True
                        break
                    else:
                        print(f'  ⚠️ #{idx + 1} {trial_name}: 모달 미감지')
                except Exception as e:
                    print(f'  ⚠️ #{idx + 1} {trial_name} 실패: {e}')

            # 시도 2: cursor:pointer 인 자손에 클릭
            if not opened:
                pointer_idx_list = page.evaluate(
                    """(idx) => {
                        const row = (window.__lotto645Rows || [])[idx];
                        if (!row) return [];
                        const all = [...row.querySelectorAll('*')];
                        const result = [];
                        all.forEach((el, i) => {
                            if (getComputedStyle(el).cursor === 'pointer') {
                                result.push({ i, tag: el.tagName, cls: ((el.className || '') + '').substring(0, 40) });
                            }
                        });
                        return result;
                    }""",
                    idx,
                )
                for p in pointer_idx_list:
                    try:
                        clicked = page.evaluate(
                            """([rowIdx, descIdx]) => {
                                const row = (window.__lotto645Rows || [])[rowIdx];
                                if (!row) return false;
                                const desc = row.querySelectorAll('*')[descIdx];
                                if (!desc) return false;
                                desc.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
                                desc.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                                desc.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                                desc.click();
                                return true;
                            }""",
                            [idx, p['i']],
                        )
                        if not clicked:
                            continue
                        time.sleep(1.2)
                        if _detect_645_modal(page):
                            print(f'  ✅ #{idx + 1} pointer descendant {p["tag"]}.{p["cls"]} 클릭으로 모달 열림')
                            opened = True
                            break
                    except Exception:
                        continue
        except Exception as e:
            print(f'  ⚠️ #{idx + 1} 행 locator 오류: {e}')

        if not opened:
            print(f'  ❌ #{idx + 1}: 모달이 열리지 않음')
            continue

        page.screenshot(path=f"debug_645_ticket_{idx}.png")

        extract_result = page.evaluate(r"""
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

                // 1) 단일 라인: "A 자동 N N N N N N"
                const fullText = document.body.innerText || '';
                const lines = fullText.split('\n');
                for (const ln of lines) {
                    const m = ln.trim().match(/^([A-J])\s*(?:자동|수동|반자동)\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})/);
                    if (m) {
                        const nums = [m[2], m[3], m[4], m[5], m[6], m[7]].map(Number);
                        if (nums.every(n => n >= 1 && n <= 45) && new Set(nums).size === 6) addGame(nums);
                    }
                }

                // 2) 멀티라인: 각 게임이 여러 줄로 분리된 경우 (A\n자동\n5\n17\n25\n...)
                if (games.length === 0) {
                    for (let i = 0; i < lines.length - 12; i++) {
                        const lab = lines[i].trim();
                        if (!/^[A-J]$/.test(lab)) continue;
                        // 다음 1~3줄 안에 자동/수동/반자동
                        let mode = '';
                        let startIdx = -1;
                        for (let j = 1; j <= 3 && i + j < lines.length; j++) {
                            const t = lines[i + j].trim();
                            if (/^(자동|수동|반자동)$/.test(t)) {
                                mode = t;
                                startIdx = i + j + 1;
                                break;
                            }
                        }
                        if (!mode) continue;
                        // 다음 6줄에서 숫자 추출
                        const nums = [];
                        for (let j = startIdx; j < startIdx + 12 && nums.length < 6; j++) {
                            const t = (lines[j] || '').trim();
                            const n = parseInt(t);
                            if (!isNaN(n) && n >= 1 && n <= 45 && /^\d+$/.test(t)) nums.push(n);
                        }
                        if (nums.length === 6 && new Set(nums).size === 6) addGame(nums);
                    }
                }

                // 3) DOM 기반: ball 셀렉터
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

                // 4) 일반 셀렉터: 모달 영역 안에서 1-45 숫자 6개씩 묶기
                if (games.length === 0) {
                    const modalArea = document.querySelector('[class*="modal"]:not([style*="display: none"]), [class*="popup"]:not([style*="display: none"]), [class*="layer"]:not([style*="display: none"])') || document.body;
                    let cur = [];
                    modalArea.querySelectorAll('span, td, li, div').forEach(el => {
                        if (el.children.length > 0) return; // leaf only
                        const t = (el.textContent || '').trim();
                        if (/^\d{1,2}$/.test(t)) {
                            const n = parseInt(t);
                            if (n >= 1 && n <= 45) {
                                cur.push(n);
                                if (cur.length === 6) {
                                    if (new Set(cur).size === 6) addGame(cur);
                                    cur = [];
                                }
                            }
                        }
                    });
                }

                // 디버그: 모달 텍스트 미리보기
                return {
                    games,
                    bodyPreview: fullText.substring(0, 600),
                };
            }
        """)

        numbers = extract_result.get('games', []) if isinstance(extract_result, dict) else []
        if numbers:
            entry['numbers'] = numbers
            print(f'  ✅ #{idx + 1}: {len(numbers)}게임 추출 - {numbers}')
        else:
            print(f'  ⚠️ #{idx + 1}: 모달은 열렸으나 번호 추출 실패')
            preview = extract_result.get('bodyPreview', '') if isinstance(extract_result, dict) else ''
            print(f'     모달 텍스트 미리보기: {preview[:400]}')

        # 모달 닫기
        closed = False
        for sel in ('.btn_close', '.close', '.modal_close', '[aria-label="close"]',
                    '[aria-label="닫기"]', 'button[title="닫기"]', '.pop_close',
                    'button:has-text("닫기")', 'a:has-text("닫기")'):
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
