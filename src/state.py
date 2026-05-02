"""구매 시점에 추출한 번호를 파일로 영속화하여 당첨 확인 단계에서 재사용한다.

ledger 페이지의 645 텍스트는 자릿수 패딩 없는 발권 코드이고, 모달 클릭으로
실제 번호를 가져오는 방식은 봇 검출로 자동화 환경에서 동작하지 않는다.
구매 직후 영수증에서 추출한 구조화된 번호를 회차와 함께 저장.
"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


_STATE_DIR = Path('/app/state') if Path('/app/state').exists() else Path(__file__).resolve().parent.parent / 'state'
_STATE_FILE = _STATE_DIR / 'last_purchase.json'

_MAX_GAMES = 10  # 안전벨트


def _kst_iso() -> str:
    return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')


def _load() -> dict:
    if not _STATE_FILE.exists():
        return {}
    try:
        return json.loads(_STATE_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save(data: dict) -> None:
    """알려진 키만 보존, 컴팩트 JSON으로 직렬화."""
    clean = {k: data[k] for k in ('lotto645', 'lotto720') if k in data}
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(
        json.dumps(clean, ensure_ascii=False, separators=(',', ':')),
        encoding='utf-8',
    )


def _slim_games(numbers: list) -> list:
    out = []
    for g in numbers or []:
        digits = [int(n) for n in g if isinstance(n, (int, str)) and str(n).isdigit()]
        if len(digits) >= 6:
            out.append(digits[:6])
        if len(out) >= _MAX_GAMES:
            break
    return out


def save_645(round_no: int, numbers: list) -> None:
    """645 구매 결과 저장 - 같은 키 덮어쓰기. round_no=0이면 저장하지 않음."""
    if not round_no or not numbers:
        return
    games = _slim_games(numbers)
    if not games:
        return
    data = _load()
    data['lotto645'] = {
        'round': int(round_no),
        'numbers': games,
        'purchased_at': _kst_iso(),
    }
    _save(data)
    print(f'💾 state 저장: 645 {round_no}회 {len(games)}게임')


def save_720(round_no: int, groups: list, numbers: list) -> None:
    if not groups:
        return
    data = _load()
    data['lotto720'] = {
        'round': int(round_no) if round_no else 0,
        'groups': [int(g) for g in groups[:_MAX_GAMES]],
        'numbers': _slim_games(numbers or []),
        'purchased_at': _kst_iso(),
    }
    _save(data)
    print(f'💾 state 저장: 720+ {round_no}회 조={groups}')


def load_645(round_no: int) -> list:
    """저장된 645 번호 중 회차가 일치하면 반환, 없으면 빈 리스트."""
    data = _load().get('lotto645')
    if not data:
        return []
    if round_no and data.get('round') != int(round_no):
        return []
    return [list(g) for g in data.get('numbers', [])]


def load_720(round_no: int) -> dict:
    data = _load().get('lotto720')
    if not data:
        return {}
    if round_no and data.get('round') and data['round'] != int(round_no):
        return {}
    return {
        'groups': list(data.get('groups', [])),
        'numbers': [list(g) for g in data.get('numbers', [])],
    }
