#!/usr/bin/env python3
"""텔레그램 인라인 버튼 봇 (long-polling).

버튼으로 다음을 수행:
  - 💰 구매            → 2단계 확인 후 purchase_all.py 실행 (실제 구매)
  - 🎯 당첨확인         → check_winning.py 실행
  - ⚙️ 구매 개수 설정    → 645/720 매수(0~5) 설정 후 settings.json 저장

콜백을 상시 수신해야 하므로 별도 컨테이너(lotto-bot)로 24시간 상주한다.
구매/확인은 같은 이미지에서 subprocess 로 실행하여, 각 스크립트가 자체 Telegram 알림을 보낸다.
"""
import json
import subprocess
import urllib.parse
import urllib.request
from os import environ

import settings as settings_store

TOKEN = environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = str(environ.get('TELEGRAM_CHAT_ID', ''))
API = f"https://api.telegram.org/bot{TOKEN}"

_proc = None  # 실행 중인 구매/확인 subprocess (동시 실행 방지)


# ---------------------------------------------------------------- Telegram API
def _post(method: str, payload: dict) -> dict:
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            f"{API}/{method}", data=data,
            headers={'Content-Type': 'application/json'}, method='POST',
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print(f"⚠️ {method} 실패: {e}")
        return {}


def _get(method: str, params: dict) -> dict:
    try:
        url = f"{API}/{method}?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=params.get('timeout', 30) + 15) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print(f"⚠️ {method} 실패: {e}")
        return {}


def _ack(cq_id: str, text: str = '', alert: bool = False):
    payload = {'callback_query_id': cq_id}
    if text:
        payload['text'] = text
        payload['show_alert'] = alert
    _post('answerCallbackQuery', payload)


def _send(text: str, kb: dict):
    _post('sendMessage', {'chat_id': CHAT_ID, 'text': text,
                          'parse_mode': 'HTML', 'reply_markup': kb})


def _edit(chat_id, mid, text: str, kb: dict):
    _post('editMessageText', {'chat_id': chat_id, 'message_id': mid,
                              'text': text, 'parse_mode': 'HTML', 'reply_markup': kb})


# ------------------------------------------------------------------- UI 구성
def _menu_text(s: dict) -> str:
    return (
        "🎰 <b>로또 자동구매</b>\n\n"
        f"현재 설정: 로또6/45 <b>{s['auto_games']}</b>매 / 연금720+ <b>{s['lotto720_games']}</b>매\n\n"
        "메뉴를 선택하세요."
    )


def _menu_kb() -> dict:
    return {'inline_keyboard': [
        [{'text': '💰 구매', 'callback_data': 'buy'},
         {'text': '🎯 당첨확인', 'callback_data': 'check'}],
        [{'text': '⚙️ 구매 개수 설정', 'callback_data': 'settings'}],
    ]}


def _settings_ui(s: dict):
    text = (
        "⚙️ <b>구매 개수 설정</b>\n\n"
        f"로또6/45: <b>{s['auto_games']}</b>매\n"
        f"연금720+: <b>{s['lotto720_games']}</b>매\n\n"
        "버튼으로 매수(0~5)를 선택하세요. (✅ = 현재값)"
    )

    def row(prefix, cur):
        return [{'text': (f'✅{i}' if i == cur else str(i)),
                 'callback_data': f'{prefix}_{i}'} for i in range(6)]

    kb = {'inline_keyboard': [
        [{'text': '━━ 로또6/45 매수 ━━', 'callback_data': 'noop'}],
        row('set645', s['auto_games']),
        [{'text': '━━ 연금720+ 매수 ━━', 'callback_data': 'noop'}],
        row('set720', s['lotto720_games']),
        [{'text': '⬅️ 메뉴', 'callback_data': 'menu'}],
    ]}
    return text, kb


def _buy_confirm_ui(s: dict):
    total = (s['auto_games'] + s['lotto720_games']) * 1000
    text = (
        "💰 <b>구매 확인</b>\n\n"
        f"로또6/45 <b>{s['auto_games']}</b>매 + 연금720+ <b>{s['lotto720_games']}</b>매\n"
        f"예상 금액: <b>{total:,}</b>원 (실제 예치금 사용)\n\n"
        "정말 구매할까요?"
    )
    kb = {'inline_keyboard': [[
        {'text': '✅ 확인', 'callback_data': 'buy_confirm'},
        {'text': '❌ 취소', 'callback_data': 'menu'},
    ]]}
    return text, kb


# --------------------------------------------------------------- 실행 제어
def _is_running() -> bool:
    return _proc is not None and _proc.poll() is None


def _spawn(script: str, extra_env: dict) -> bool:
    global _proc
    if _is_running():
        return False
    env = dict(environ)
    env.update(extra_env)
    _proc = subprocess.Popen(['python', f'src/{script}'], env=env)
    return True


# ----------------------------------------------------------------- 라우팅
def _route(data: str, cq_id: str, chat_id, mid):
    s = settings_store.load()

    if data == 'noop':
        _ack(cq_id)
        return

    if data == 'menu':
        _edit(chat_id, mid, _menu_text(s), _menu_kb())
        _ack(cq_id)
        return

    if data == 'settings':
        text, kb = _settings_ui(s)
        _edit(chat_id, mid, text, kb)
        _ack(cq_id)
        return

    if data.startswith('set645_'):
        s = settings_store.save(auto_games=int(data.split('_')[1]))
        text, kb = _settings_ui(s)
        _edit(chat_id, mid, text, kb)
        _ack(cq_id, f"645 {s['auto_games']}매 저장")
        return

    if data.startswith('set720_'):
        s = settings_store.save(lotto720_games=int(data.split('_')[1]))
        text, kb = _settings_ui(s)
        _edit(chat_id, mid, text, kb)
        _ack(cq_id, f"720 {s['lotto720_games']}매 저장")
        return

    if data == 'buy':
        if s['auto_games'] == 0 and s['lotto720_games'] == 0:
            _ack(cq_id, '매수가 0입니다. 먼저 개수를 설정하세요.', alert=True)
            return
        text, kb = _buy_confirm_ui(s)
        _edit(chat_id, mid, text, kb)
        _ack(cq_id)
        return

    if data == 'buy_confirm':
        if s['auto_games'] == 0 and s['lotto720_games'] == 0:
            _ack(cq_id, '매수가 0입니다.', alert=True)
            return
        if not _spawn('purchase_all.py', {
            'PURCHASE_TARGET': 'all',
            'AUTO_GAMES': str(s['auto_games']),
            'LOTTO720_GAMES': str(s['lotto720_games']),
            'MANUAL_NUMBERS': '[]',
        }):
            _ack(cq_id, '이미 실행 중입니다.', alert=True)
            return
        _edit(chat_id, mid,
              f"🛒 구매를 시작합니다 (645 {s['auto_games']}매 / 720 {s['lotto720_games']}매)\n"
              "완료되면 결과 알림이 옵니다.", _menu_kb())
        _ack(cq_id, '구매 실행')
        return

    if data == 'check':
        if not _spawn('check_winning.py', {'CHECK_TARGET': 'all'}):
            _ack(cq_id, '이미 실행 중입니다.', alert=True)
            return
        _edit(chat_id, mid, "🎯 당첨 확인을 시작합니다.\n완료되면 결과 알림이 옵니다.", _menu_kb())
        _ack(cq_id, '당첨확인 실행')
        return

    _ack(cq_id)


def _handle(upd: dict):
    if 'callback_query' in upd:
        cq = upd['callback_query']
        msg = cq.get('message', {})
        if str(msg.get('chat', {}).get('id')) != CHAT_ID:
            _ack(cq['id'])
            return
        _route(cq.get('data', ''), cq['id'], msg['chat']['id'], msg['message_id'])
    elif 'message' in upd:
        msg = upd['message']
        if str(msg.get('chat', {}).get('id')) != CHAT_ID:
            return
        # 아무 메시지/명령이나 받으면 메뉴 표시
        _send(_menu_text(settings_store.load()), _menu_kb())


def main():
    if not TOKEN or not CHAT_ID:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정 - 봇 종료")
        return
    print("🤖 lotto-bot 시작 (long-polling)")

    # 시작 시 밀린 업데이트(재시작 전 눌린 버튼 등) 폐기 → 재시작에 따른 오발주 방지
    offset = None
    backlog = _get('getUpdates', {'timeout': 0})
    results = backlog.get('result', [])
    if results:
        offset = results[-1]['update_id'] + 1

    _send(_menu_text(settings_store.load()), _menu_kb())

    while True:
        params = {'timeout': 50}
        if offset is not None:
            params['offset'] = offset
        resp = _get('getUpdates', params)
        for upd in resp.get('result', []):
            offset = upd['update_id'] + 1
            try:
                _handle(upd)
            except Exception as e:
                print(f"⚠️ 업데이트 처리 오류: {e}")


if __name__ == "__main__":
    main()
