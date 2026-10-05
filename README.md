# SteamGridDB for Playlite

Basic game names and links, plus community artwork from [SteamGridDB](https://www.steamgriddb.com/).

## Setup

1. Install SteamGridDB from **Settings → Plugins → Available**, then restart Playlite.
2. Generate an API key in your [SteamGridDB account preferences](https://www.steamgriddb.com/profile/preferences/api).
3. Open **Settings → Plugins → Metadata → SteamGridDB**, enter your key, and save.

## Usage

Select SteamGridDB in **Download metadata** or **Download images**. Search by title, SteamGridDB game ID or game URL, Steam store URL, or `steam:APP_ID`. A plain numeric ID always means a SteamGridDB ID. Saved SteamGridDB and Steam associations are used automatically.

- **Icon:** icons and transparent logos.
- **Cover:** grids, including portrait and landscape covers.
- **Header / Background:** hero images.

Use Playlite's artwork, shape, and resolution filters to narrow results. The API key and image limit are stored locally in `$XDG_CONFIG_HOME/playlite/steamgriddb.json` (default `~/.config/playlite/steamgriddb.json`), with owner-only file permissions. Static artwork only; searches load up to 50 images per category by default, configurable from 10 to 200.

SteamGridDB provides limited game metadata: this plugin supplies names, sorting names, and a SteamGridDB link. Use another metadata provider for descriptions, genres, and other details.

## Development

Requires Playlite. Run `python3 -m unittest discover -s tests -v` with Playlite on `PYTHONPATH`. Build packages with `python3 tools/build_release.py`; publish with `python3 tools/publish_distribution.py v1.0.0`.

API reference: https://www.steamgriddb.com/api/v2
