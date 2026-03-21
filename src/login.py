#!/usr/bin/env python3
from os import environ
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import Page, Playwright

# Robustly match .env file
def load_environment():
    """
    .env 파일을 찾아 로드합니다.
    우선순위:
    1. src/ 상위 디렉토리 (프로젝트 루트)
    2. 현재 작업 디렉토리
    """
    # 1. Check project root (relative to this file)
    project_root = Path(__file__).resolve().parent.parent
    env_path = project_root / '.env'
    
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        return

    # 2. Check current working directory
    cwd_env = Path.cwd() / '.env'
    if cwd_env.exists():
        load_dotenv(dotenv_path=cwd_env)
        return
        
    # 3. Last fallback: try default load_dotenv (searches up tree)
    load_dotenv()

load_environment()

USER_ID = environ.get('USER_ID')
PASSWD = environ.get('PASSWD')


def login(page: Page) -> None:
    """
    동행복권 사이트에 로그인합니다.

    Args:
        page: Playwright Page 객체 (호출자가 생성하여 주입)

    Raises:
        ValueError: USER_ID 또는 PASSWD 환경변수가 없을 경우
        Exception: 로그인 실패 시
    """
    if not USER_ID or not PASSWD:
        raise ValueError("❌ USER_ID or PASSWD not found in environment variables.")

    print('Starting login process...')
    page.goto("https://www.dhlottery.co.kr/login", timeout=60000, wait_until="domcontentloaded")

    # Debug: 로그인 페이지 스크린샷
    page.screenshot(path="debug_login_page.png")
    print("📸 Screenshot saved: debug_login_page.png")

    page.locator("#inpUserId").fill(USER_ID)

    # Password: use press_sequentially() to trigger keydown/keypress/keyup events.
    # The site's security plugin encrypts keystrokes via keyboard event handlers.
    # fill() bypasses these events, sending unencrypted password which the server rejects.
    pwd_field = page.locator("#inpUserPswdEncn")
    pwd_field.click()
    pwd_field.press_sequentially(PASSWD, delay=100)

    page.click("#btnLogin")

    # Wait for login to complete
    page.wait_for_load_state("networkidle")

    # securityLoginCheck.do 등 중간 리다이렉트 페이지 대기
    if "securityLoginCheck" in page.url or "loginCheck" in page.url:
        print(f"📍 Security check page: {page.url}, waiting for redirect...")
        try:
            page.wait_for_url(lambda url: "login" not in url.lower(), timeout=15000)
            page.wait_for_load_state("networkidle")
        except Exception:
            # 리다이렉트가 안 끝나면 메인 페이지로 직접 이동
            print("⚠️ 리다이렉트 타임아웃, 메인 페이지로 직접 이동...")
            page.goto("https://www.dhlottery.co.kr/main", timeout=60000, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")

    # Debug: 로그인 후 스크린샷
    page.screenshot(path="debug_after_login.png")
    print(f"📍 After login URL: {page.url}")
    print("📸 Screenshot saved: debug_after_login.png")

    # 로그인 성공 여부 확인 - 로그인 입력 페이지에 여전히 있는지 체크
    # securityLoginCheck.do는 로그인 성공 후 중간 페이지이므로 제외
    current_url = page.url.lower()
    is_login_page = "login" in current_url and "check" not in current_url
    if is_login_page:
        # 에러 메시지 확인
        error_el = page.locator(".err_msg, .error, #loginFailMsg")
        if error_el.count() > 0:
            error_text = error_el.first.inner_text()
            raise Exception(f"❌ Login failed: {error_text}")
        raise Exception("❌ Login failed: Still on login page")

    print('✅ Logged in successfully')

