"""구매 개수 설정 영속화.

텔레그램 봇(`bot.py`)이 버튼으로 설정하고, 구매 스크립트(`purchase_all.py`)가 읽는다.
파일이 없으면 환경변수(AUTO_GAMES / LOTTO720_GAMES)를 기본값으로 사용하므로,
봇을 쓰지 않는 기존 스케줄 구매 동작은 그대로 유지된다.
"""
import json
from os import environ
from pathlib import Path

_STATE_DIR = Path('/app/state') if Path('/app/state').exists() \
    else Path(__file__).resolve().parent.parent / 'state'
_SETTINGS_FILE = _STATE_DIR / 'settings.json'

_KEYS = ('auto_games', 'lotto720_games')


def load() -> dict:
    """현재 구매 개수 설정. 파일 없으면 환경변수 기본값."""
    cfg = {
        'auto_games': int(environ.get('AUTO_GAMES', '0') or 0),
        'lotto720_games': int(environ.get('LOTTO720_GAMES', '0') or 0),
    }
    try:
        data = json.loads(_SETTINGS_FILE.read_text(encoding='utf-8'))
        for k in _KEYS:
            if k in data:
                cfg[k] = int(data[k])
    except Exception:
        pass
    return cfg


def save(auto_games: int = None, lotto720_games: int = None) -> dict:
    """전달된 값만 갱신하여 저장. 0~5 범위로 클램프."""
    cfg = load()
    if auto_games is not None:
        cfg['auto_games'] = max(0, min(5, int(auto_games)))
    if lotto720_games is not None:
        cfg['lotto720_games'] = max(0, min(5, int(lotto720_games)))
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(
        json.dumps({k: cfg[k] for k in _KEYS}, ensure_ascii=False),
        encoding='utf-8',
    )
    return cfg
