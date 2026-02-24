"""Telegram 알림 모듈"""
import json
import urllib.request
from datetime import datetime, timezone, timedelta
from os import environ


def _send_telegram(text: str):
    """Telegram 메시지를 전송합니다."""
    token = environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = environ.get('TELEGRAM_CHAT_ID', '')

    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set, skipping notification")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML',
    }

    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url, data=data,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        urllib.request.urlopen(req, timeout=10)
        print("Telegram notification sent")
    except Exception as e:
        print(f"Telegram notification failed: {e}")


def _kst_now() -> str:
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y-%m-%d %H:%M")


def send_purchase_notification(success: bool, numbers: list, balance: int,
                               details: str = '', lotto720_groups: list = None):
    """구매 결과를 Telegram으로 전송합니다."""
    icon = "✅" if success else "❌"
    status = "성공" if success else "실패"
    title = f"{icon} 로또 구매 {status}!"

    lines = [f"<b>{title}</b>", ""]

    # Lotto 6/45 numbers
    if numbers:
        lines.append("🎱 <b>로또 6/45</b>")
        for i, game in enumerate(numbers, 1):
            nums_str = '  '.join(str(n).zfill(2) for n in game)
            lines.append(f"  <b>{chr(64 + i)}</b>  <code>{nums_str}</code>")
        lines.append("")

    # Lotto 720+ groups
    if lotto720_groups:
        lines.append("🎫 <b>연금복권 720+</b>")
        for i, group in enumerate(lotto720_groups, 1):
            lines.append(f"  <b>{chr(64 + i)}</b>  {group}조 (자동)")
        lines.append("")

    lines.extend([
        f"💰 <b>잔액:</b> {balance:,}원",
        f"📅 <b>일시:</b> {_kst_now()}",
    ])

    if details:
        lines.append(f"📝 <b>상세:</b> {details}")

    _send_telegram('\n'.join(lines))


def send_error_notification(script: str, error: str):
    """스크립트 오류를 Telegram으로 전송합니다."""
    lines = [
        "<b>⚠️ 스크립트 오류</b>",
        "",
        f"📦 <b>스크립트:</b> {script}",
        f"📝 <b>오류:</b> {error}",
        f"📅 <b>일시:</b> {_kst_now()}",
    ]
    _send_telegram('\n'.join(lines))


def send_winning_notification(has_won: bool, results: list, total_prize: int, balance: int):
    """당첨 확인 결과를 Telegram으로 전송합니다."""
    if has_won:
        title = "🎉 로또 당첨!"
    else:
        title = "😢 로또 미당첨"

    lines = [f"<b>{title}</b>", ""]

    if has_won and total_prize > 0:
        lines.append(f"💵 <b>총 당첨금:</b> {total_prize:,}원")
        lines.append("")

    if results:
        for r in results:
            rank = r.get('rank', '미당첨')
            nums = r.get('numbers', [])
            prize = r.get('prize', 0)
            nums_str = '  '.join(str(n).zfill(2) for n in nums) if nums else '-'

            if rank != '미당첨':
                lines.append(f"🏆 <b>{rank}등</b>  <code>{nums_str}</code>")
                lines.append(f"    💵 당첨금: {prize:,}원")
            else:
                lines.append(f"  ❌ <code>{nums_str}</code> - 미당첨")

    lines.extend([
        "",
        f"💰 <b>잔액:</b> {balance:,}원",
        f"📅 <b>일시:</b> {_kst_now()}",
    ])

    _send_telegram('\n'.join(lines))
