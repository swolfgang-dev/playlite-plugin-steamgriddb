"""SteamGridDB API v2 client; credentials remain in the user's config directory."""
import json
import os
from pathlib import Path
import re
from threading import RLock
from time import monotonic
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from playlite.metadata import MetadataError

API = 'https://www.steamgriddb.com/api/v2'


class NotFound(MetadataError):
    pass


def settings_path():
    return Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'playlite/steamgriddb.json'


def load_settings():
    try:
        values = json.loads(settings_path().read_text())
        if not isinstance(values, dict):
            values = {}
    except (OSError, ValueError):
        values = {}
    key = values.get('api_key', '')
    limit = values.get('image_limit', 50)
    return {'api_key': key if isinstance(key, str) else '',
            'image_limit': max(10, min(200, limit)) if isinstance(limit, int) else 50}


def save_settings(values):
    destination = settings_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    descriptor, name = tempfile.mkstemp(dir=destination.parent, prefix='.steamgriddb-')
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(values, stream)
        os.replace(name, destination)
    finally:
        Path(name).unlink(missing_ok=True)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        # Never send the bearer credential to a redirected host.
        return None


def game_reference(query):
    query = str(query).strip()
    if query.isascii() and query.isdigit() and int(query) > 0:
        return ('id', str(int(query)))
    parsed = urlsplit(query)
    if parsed.scheme == 'https' and parsed.hostname in ('steamgriddb.com', 'www.steamgriddb.com'):
        match = re.fullmatch(r'/(game|steam)/(\d+)(?:/(?:grids|heroes|logos|icons))?/?', parsed.path)
        if match and int(match[2]) > 0:
            return ('id' if match[1] == 'game' else 'steam', str(int(match[2])))
    if parsed.scheme == 'https' and parsed.hostname == 'store.steampowered.com':
        match = re.match(r'^/app/(\d+)(?:/|$)', parsed.path)
        if match and int(match[1]) > 0:
            return ('steam', str(int(match[1])))
    match = re.fullmatch(r'steam:(\d+)', query, re.I)
    if match and int(match[1]) > 0:
        return ('steam', str(int(match[1])))
    return None


class Client:
    def __init__(self, api_key='', image_limit=50):
        self.api_key = api_key.strip()
        self.image_limit = image_limit
        self.cache = {}
        self.lock = RLock()

    def request(self, endpoint, parameters=None):
        if not self.api_key:
            raise MetadataError('Add your SteamGridDB API key in Settings → Plugins → Metadata → SteamGridDB.')
        url = API + endpoint + ('?' + urlencode(parameters) if parameters else '')
        request = Request(url, headers={'Authorization': 'Bearer ' + self.api_key,
                                        'User-Agent': 'Playlite SteamGridDB/1.0', 'Accept': 'application/json'})
        try:
            with build_opener(NoRedirect()).open(request, timeout=20) as response:
                data = response.read(4 * 1024 * 1024 + 1)
        except HTTPError as error:
            if error.code == 404:
                raise NotFound('SteamGridDB could not find this game or artwork.') from None
            messages = {401: 'SteamGridDB authentication failed. Check your API key.',
                        403: 'SteamGridDB access denied. Check your API key.',
                        404: 'SteamGridDB could not find this game or artwork.',
                        429: 'SteamGridDB rate limit reached. Try again shortly.'}
            raise MetadataError(messages.get(error.code, f'SteamGridDB request failed (HTTP {error.code}).')) from None
        except (OSError, ValueError):
            raise MetadataError('Could not connect to SteamGridDB. Check your network connection.') from None
        if len(data) > 4 * 1024 * 1024:
            raise MetadataError('SteamGridDB response is too large.')
        try:
            result = json.loads(data)
        except (ValueError, UnicodeError):
            raise MetadataError('SteamGridDB returned an invalid response.') from None
        if not isinstance(result, dict) or result.get('success') is not True or 'data' not in result:
            raise MetadataError('SteamGridDB could not complete this request.')
        return result

    def game(self, game_id, platform='id'):
        reference = game_reference(str(game_id))
        if not reference or reference[0] != 'id' or platform not in ('id', 'steam'):
            raise MetadataError('Enter a valid SteamGridDB game ID.')
        data = self.request(f'/games/{platform}/{reference[1]}')['data']
        if not isinstance(data, dict) or not isinstance(data.get('id'), int) or not isinstance(data.get('name'), str):
            raise MetadataError('SteamGridDB returned invalid game details.')
        return data

    def search(self, query):
        query = str(query).strip()
        if not query:
            return []
        reference = game_reference(query)
        if reference:
            data = [self.game(reference[1], reference[0])]
        else:
            data = self.request('/search/autocomplete/' + quote(query, safe=''))['data']
        if not isinstance(data, list):
            raise MetadataError('SteamGridDB returned invalid search results.')
        return [{'id': entry['id'], 'name': entry['name']} for entry in data
                if isinstance(entry, dict) and isinstance(entry.get('id'), int)
                and isinstance(entry.get('name'), str)]

    def artwork(self, game_id, category):
        return self.artwork_batch(game_id, category)[0]

    def artwork_batch(self, game_id, category, batch=0):
        if not isinstance(batch, int) or batch < 0:
            raise ValueError("Invalid artwork batch.")
        if category not in ('grids', 'heroes', 'logos', 'icons'):
            raise ValueError('Unsupported artwork category.')
        reference = game_reference(str(game_id))
        if not reference or reference[0] != 'id':
            raise MetadataError('Enter a valid SteamGridDB game ID.')
        target = self.image_limit * (batch + 1)
        with self.lock:
            candidates, seen = [], set()
            exhausted = False
            page = 0
            while True:
                key = (reference[1], category, page)
                cached = self.cache.get(key)
                if cached and monotonic() - cached[0] < 300:
                    response = cached[1]
                else:
                    try:
                        response = self.request(f'/{category}/game/{reference[1]}',
                                                {'page': page, 'limit': 50, 'types': 'static'})
                    except NotFound:
                        response = {'data': [], 'total': page * 50}
                    if len(self.cache) >= 64:
                        self.cache.pop(next(iter(self.cache)))
                    self.cache[key] = (monotonic(), response)
                entries = response['data']
                if not isinstance(entries, list):
                    raise MetadataError('SteamGridDB returned invalid artwork.')
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    url = entry.get('url')
                    if not isinstance(url, str) or urlsplit(url).scheme != 'https' or not urlsplit(url).hostname:
                        continue
                    if url in seen:
                        continue
                    seen.add(url)
                    author = entry.get('author') or {}
                    name = author.get('name', '') if isinstance(author, dict) else ''
                    label = {'grids': 'Cover', 'heroes': 'Hero', 'logos': 'Logo', 'icons': 'Icon'}[category]
                    candidate = {'url': url, 'label': f'{label} {entry.get("id", "")}' + (f' · {name}' if name else '')}
                    if isinstance(entry.get('thumb'), str) and entry['thumb'].startswith('https://'):
                        candidate['thumbnail'] = entry['thumb']
                    candidates.append(candidate)
                total = response.get('total')
                if len(entries) < 50 or (isinstance(total, int) and (page + 1) * 50 >= total):
                    exhausted = True
                if exhausted or len(candidates) >= target:
                    break
                page += 1
            start = batch * self.image_limit
            return candidates[start:target], len(candidates) > target or not exhausted
