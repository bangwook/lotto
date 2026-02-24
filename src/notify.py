"""Discord 웹훅 알림 모듈"""
import json
import urllib.request
from datetime import datetime, timezone, timedelta
from os import environ


def send_notification(success: bool, numbers: list, balance: int, details: str = ''):
    """구매 결과를 Discord 웹훅으로 전송합니다."""
    webhook_url = environ.get('DISCORD_WEBHOOK_URL', '')
    if not webhook_url:
        print("⚠️ DISCORD_WEBHOOK_URL 미설정, 알림 건너뜀")
        return

    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst).strftime("%Y-%m-%d %H:%M")

    color = 0x00C853 if success else 0xFF1744
    title = "✅ 로또 구매 성공!" if success else "❌ 로또 구매 실패"

    # Format numbers
    if numbers:
        numbers_text = ""
        for i, game in enumerate(numbers, 1):
            nums_str = '  '.join(str(n).zfill(2) for n in game)
            numbers_text += f"**{chr(64 + i)}**  `{nums_str}`\n"
    else:
        numbers_text = "번호 추출 실패"

    fields = [
        {"name": "🎱 구매 번호", "value": numbers_text, "inline": False},
        {"name": "💰 잔액", "value": f"{balance:,}원", "inline": True},
        {"name": "📅 일시", "value": now, "inline": True},
    ]

    if details:
        fields.append({"name": "📝 상세", "value": details, "inline": False})

    payload = {
        "embeds": [{
            "title": title,
            "color": color,
            "fields": fields,
        }]
    }

    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        urllib.request.urlopen(req, timeout=10)
        print("📨 Discord 알림 전송 완료")
    except Exception as e:
        print(f"⚠️ Discord 알림 전송 실패: {e}")
