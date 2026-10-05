import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('steamgriddb_test', ROOT / 'plugin.py', submodule_search_locations=[str(ROOT)])
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)
client_module = sys.modules['steamgriddb_test.client']
Client = client_module.Client


class ProviderTests(unittest.TestCase):
    def test_reference_distinguishes_steam_and_sgdb_ids(self):
        cases = {'12': ('id', '12'), 'https://www.steamgriddb.com/game/12/grids': ('id', '12'),
                 'https://www.steamgriddb.com/steam/220': ('steam', '220'),
                 'https://store.steampowered.com/app/220/Half_Life_2/': ('steam', '220'),
                 'steam:220': ('steam', '220'), 'https://steamgriddb.com.evil/game/12': None,
                 '0': None, 'Half-Life 2': None}
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertEqual(client_module.game_reference(query), expected)

    def test_search_resolves_external_id_instead_of_treating_it_as_sgdb(self):
        client = Client('fake')
        with patch.object(client, 'request', return_value={'data': {'id': 99, 'name': 'Game'}}) as request:
            self.assertEqual(client.search('steam:220'), [{'id': 99, 'name': 'Game'}])
            request.assert_called_once_with('/games/steam/220')

    def test_search_encodes_title_and_ignores_malformed_entries(self):
        client = Client('fake')
        with patch.object(client, 'request', return_value={'data': [{'id': 1, 'name': 'A/B'}, None, {'name': 'Bad'}]}) as request:
            self.assertEqual(client.search('A/B'), [{'id': 1, 'name': 'A/B'}])
            request.assert_called_once_with('/search/autocomplete/A%2FB')

    def test_missing_key_does_not_make_request(self):
        with patch.object(client_module, 'build_opener') as opener:
            with self.assertRaisesRegex(client_module.MetadataError, 'API key'):
                Client().request('/games/id/1')
            opener.assert_not_called()

    def test_http_error_hides_credentials_and_explains_rate_limit(self):
        error = HTTPError('https://example.com', 429, 'secret', {}, None)
        with patch.object(client_module, 'build_opener') as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaisesRegex(client_module.MetadataError, 'rate limit') as caught:
                Client('secret').request('/games/id/1')
            self.assertNotIn('secret', str(caught.exception))

    def test_invalid_response_is_reported(self):
        with patch.object(client_module, 'build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = b'{"success": false}'
            with self.assertRaisesRegex(client_module.MetadataError, 'complete'):
                Client('fake').request('/games/id/1')

    def test_paging_deduplicates_caps_and_caches(self):
        client = Client('fake', image_limit=60)
        entries = [{'id': n, 'url': f'https://cdn.example.com/{n}.png', 'author': {'name': 'Artist'}} for n in range(50)]
        pages = [{'data': entries, 'total': 80}, {'data': entries[40:] + [{'id': n, 'url': f'https://cdn.example.com/{n}.png'} for n in range(50, 80)], 'total': 80}]
        with patch.object(client, 'request', side_effect=pages) as request:
            results = client.artwork(1, 'grids')
            self.assertEqual(len(results), 60)
            self.assertEqual(results[0]['label'], 'Cover 0 · Artist')
            self.assertEqual(client.artwork(1, 'grids'), results)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(request.call_args_list[1].args[1]['page'], 1)

    def test_unsafe_artwork_urls_are_skipped(self):
        client = Client('fake')
        with patch.object(client, 'request', return_value={'data': [{'url': 'file:///etc/passwd'}, {'url': 'http://example.com/a'}, {'url': 'https://cdn.example.com/a'}]}):
            self.assertEqual(len(client.artwork(1, 'icons')), 1)

    def test_missing_artwork_does_not_block_other_categories(self):
        provider = module.Provider()
        with patch.object(provider.client, 'request', side_effect=[client_module.NotFound('No icons'),
                {'data': [{'id': 1, 'url': 'https://cdn.example.com/logo.png'}]}]):
            self.assertEqual(provider.images(12, 'Icon')[0]['url'], 'https://cdn.example.com/logo.png')

    def test_metadata_only_returns_requested_supported_fields(self):
        provider = module.Provider()
        with patch.object(provider.client, 'game', return_value={'id': 12, 'name': 'The Game'}):
            self.assertEqual(provider.fetch(12, {'Name', 'Description'}), {'Name': 'The Game'})

    def test_image_mapping_and_hero_cache_reuse(self):
        provider = module.Provider()
        with patch.object(provider.client, 'artwork', side_effect=lambda game, kind: [{'url': kind}]) as artwork:
            self.assertEqual(provider.images(12, 'Icon'), [{'url': 'icons'}, {'url': 'logos'}])
            self.assertEqual(provider.images(12, 'HeaderImage'), [{'url': 'heroes'}])
            self.assertEqual(provider.images(12, 'BackgroundImage'), [{'url': 'heroes'}])
            self.assertEqual(provider.images(12, 'Unsupported'), [])

    def test_query_prioritizes_saved_sgdb_then_steam_associations(self):
        provider = module.Provider()
        self.assertEqual(provider.query({'Name': 'Title', 'MetadataIds': {'SteamGridDB': 12, 'Steam': 220}}), '12')
        self.assertEqual(provider.query({'Name': 'Title', 'MetadataIds': {'Steam': 220}}), 'steam:220')
        self.assertEqual(provider.query({'Name': 'Title'}), 'Title')

    def test_credentials_are_private_and_follow_xdg(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'XDG_CONFIG_HOME': root}):
            client_module.save_settings({'api_key': 'test-key', 'image_limit': 100})
            self.assertEqual(client_module.load_settings()['api_key'], 'test-key')
            self.assertEqual(client_module.settings_path().stat().st_mode & 0o777, 0o600)
            self.assertFalse(list(Path(root).rglob('.steamgriddb-*')))


if __name__ == '__main__':
    unittest.main()
