from playlite.providers import MetadataProvider
from playlite.sorting_name import sorting_name
from .client import Client, game_reference, load_settings, save_settings
from urllib.parse import urlsplit


class Provider(MetadataProvider):
    query_hint = 'Game name, SteamGridDB ID/URL, Steam URL, or steam:APP_ID'
    image_types = frozenset(('Icon', 'CoverImage', 'HeaderImage', 'BackgroundImage'))

    def __init__(self):
        self.client = Client(**load_settings())

    def create_settings(self, parent=None):
        from PyQt6.QtWidgets import QWidget, QFormLayout, QLineEdit, QSpinBox, QLabel
        widget = QWidget(parent)
        form = QFormLayout(widget)
        widget.original_settings = load_settings()
        widget.api_key = QLineEdit(widget.original_settings['api_key'])
        widget.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        widget.image_limit = QSpinBox()
        widget.image_limit.setRange(10, 200)
        widget.image_limit.setValue(widget.original_settings['image_limit'])
        form.addRow('API key', widget.api_key)
        form.addRow('Images per category', widget.image_limit)
        help_text = QLabel('<a href="https://www.steamgriddb.com/profile/preferences/api">Get a SteamGridDB API key</a>. '
                           'Provides basic game names and links, plus covers, heroes, icons, and logos. '
                           'Hero images are available as headers and backgrounds; logos appear under icons. '
                           'Static artwork only. The image limit keeps searches manageable.')
        help_text.setWordWrap(True)
        help_text.setOpenExternalLinks(True)
        form.addRow(help_text)
        return widget

    def save_settings(self, widget):
        values = {'api_key': widget.api_key.text().strip(), 'image_limit': widget.image_limit.value()}
        if values != widget.original_settings:
            save_settings(values)
            widget.original_settings = values
            self.client = Client(**values)

    def search(self, query):
        return self.client.search(query)

    def linked_query(self, game):
        return next((link.get('Url') for link in game.get('Links') or []
                     if game_reference(link.get('Url', '')) and
                     urlsplit(link.get('Url', '')).hostname in ('steamgriddb.com', 'www.steamgriddb.com')), None)

    def query(self, game):
        saved = (game.get('MetadataIds') or {}).get('SteamGridDB')
        if saved:
            return str(saved)
        linked = self.linked_query(game)
        if linked:
            return linked
        steam_id = (game.get('MetadataIds') or {}).get('Steam') or game.get('SteamId')
        if steam_id and game_reference(str(steam_id)):
            return f'steam:{steam_id}'
        return next((link['Url'] for link in game.get('Links') or []
                     if game_reference(link.get('Url', ''))), game.get('Name', ''))

    def is_exact_query(self, query, result_id=None):
        reference = game_reference(query)
        return bool(reference and (reference[0] == 'steam' or result_id is None or reference[1] == str(result_id)))

    def fetch(self, game_id, fields):
        game = self.client.game(game_id)
        result = {'Name': game['name'], 'SortingName': sorting_name(game['name']),
                  'Links': [{'Name': 'SteamGridDB', 'Url': f'https://www.steamgriddb.com/game/{game["id"]}'}]}
        return {key: value for key, value in result.items() if key in fields}

    def images(self, game_id, image_type):
        categories = {'Icon': ('icons', 'logos'), 'CoverImage': ('grids',),
                      'HeaderImage': ('heroes',), 'BackgroundImage': ('heroes',)}
        return [candidate for category in categories.get(image_type, ())
                for candidate in self.client.artwork(game_id, category)]
