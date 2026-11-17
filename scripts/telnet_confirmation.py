"""Bounded UI confirmations for isolated acceptance clients, never game code."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def confirm_menu(command, limit=12):
    messages = [json.loads((ROOT / 'starroute_bbs/locales' / (lang + '.json')).read_text(
        encoding='utf8'))['ui'] for lang in ('ja', 'en')]
    normalize = lambda value: ''.join(value.split())
    result = command('y')
    for _ in range(limit):
        text = normalize(result)
        if any(normalize(m['review_remaining']) in text for m in messages):
            command('>')
        elif any(normalize(m['price_changed']) in text for m in messages):
            print('CONFIRM price changed: review replacement quote', flush=True)
        else:
            return result
        result = command('y')
    raise AssertionError('confirmation did not settle within the bounded review limit')
