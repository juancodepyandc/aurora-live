"""Public discovery monitor, standard-library only, usable on Linux/macOS/Windows."""
import argparse
import datetime
import json
from pathlib import Path
import re
import urllib.request

URL_PATTERN = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com/?\Z')


def valid_url(url):
    return isinstance(url, str) and bool(URL_PATTERN.fullmatch(url))


def probe(url):
    if not valid_url(url):
        return False
    try:
        with urllib.request.urlopen(url.rstrip('/') + '/api/health', timeout=10) as response:
            if response.status != 200:
                return False
            data = json.loads(response.read(65537))
        return isinstance(data, dict) and data.get('ok') is True and data.get('service') == 'aurora-bridge'
    except (OSError, ValueError):
        return False


def update(repo, mode='auto', url=None, checker=probe):
    repo = Path(repo)
    previous = {}
    try:
        previous = json.loads((repo / 'status.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    if url is None:
        url = previous.get('candidate_url') or (repo / 'tunnel.txt').read_text(encoding='utf-8').strip()
    if url and not valid_url(url):
        raise ValueError('Invalid public tunnel URL')
    online = mode != 'closed' and checker(url)
    state = 'online' if online else 'offline'
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.isoformat(timespec='seconds')
    try:
        checked = datetime.datetime.fromisoformat(previous['checked_at'])
        if (previous.get('state') == state and previous.get('candidate_url') == url
                and 0 <= (now - checked).total_seconds() < 240):
            stamp = previous['checked_at']
    except (KeyError, TypeError, ValueError):
        pass
    # Keep the candidate for recovery, never expose it as a usable link offline.
    record = {'state': state, 'candidate_url': url, 'checked_at': stamp,
              'check_scope': 'public aurora-bridge health; not inference readiness'}
    block = (f'🟢 **En ligne** — [Ouvrir Aurora]({url})' if online else
             '🔴 **Hors ligne** — le serveur public ne répond pas ou a été arrêté.')
    block += f'\n\n_Dernière vérification : {stamp}. État vérifié à cet instant, pas une garantie continue. '
    block += 'Contrôle GitHub prévu toutes les 5 minutes ; des retards sont possibles._'
    path = repo / 'README.md'
    source = path.read_text(encoding='utf-8')
    replaced, count = re.subn(r'<!--STATUS-->.*?<!--/STATUS-->',
                             '<!--STATUS-->\n' + block + '\n<!--/STATUS-->', source, flags=re.S)
    if count != 1:
        raise ValueError('Exactly one README status block required')
    path.write_text(replaced, encoding='utf-8')
    (repo / 'tunnel.txt').write_text(url.rstrip('/') + '\n' if online else '', encoding='utf-8')
    (repo / 'status.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return state


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--mode', choices=['auto', 'open', 'closed'], default='auto')
    parser.add_argument('--url')
    args = parser.parse_args()
    print(update(args.repo, args.mode, args.url))
