import re
import time
from .otsconfig import config
from .api.spotify import spotify_get_token, spotify_get_liked_songs, spotify_get_your_episodes, spotify_get_album_tracks, spotify_get_playlist_data, spotify_get_playlist_items, spotify_get_artist_albums, spotify_get_show_episodes
from .api.soundcloud import soundcloud_parse_url, soundcloud_get_set_items
from .runtimedata import get_logger, parsing, download_queue, pending
from .accounts import get_account_token


logger = get_logger('gui.main_ui')

SOUNDCLOUD_URL_REGEX = re.compile(r"https://soundcloud.com/[-\w:/]+")
SPOTIFY_URL_REGEX = re.compile(r"^(https?://)?open\.spotify\.com/(intl-([a-zA-Z]+)/|)(?P<Type>track|album|artist|playlist|episode|show)/(?P<ID>[0-9a-zA-Z]{22})(\?si=.+?)?$")
#QOBUZ_INTERPRETER_URL_REGEX = re.compile(r"https?://www\.qobuz\.com/\w\w-\w\w/interpreter/[-\w]+/([-\w]+)")
#YOUTUBE_URL_REGEX = re.compile(r"https://www\.youtube\.com/watch\?v=[-\w]")

def parse_url(url):
    accounts = config.get('accounts')
    account_service = accounts[config.get('parsing_acc_sn')]['service']
    if account_service == 'soundcloud' and re.match(SOUNDCLOUD_URL_REGEX, url):
        item_type, item_id = soundcloud_parse_url(url)
        item_service = "soundcloud"
    elif account_service == 'spotify' and re.match(SPOTIFY_URL_REGEX, url):
        match = re.search(SPOTIFY_URL_REGEX, url)
        item_id = match.group("ID")
        item_type = match.group("Type")
        item_service = "spotify"
    # Spotify Liked Songs
    elif account_service == 'spotify' and url == 'https://open.spotify.com/collection/tracks':
        item_id = None
        item_type = 'liked_songs'
        item_service = "spotify"
    # Spotify Your Episodes
    elif account_service == 'spotify' and url == 'https://open.spotify.com/collection/your-episodes':
        item_id = None
        item_type = 'your_episodes'
        item_service = "spotify"
    else:
        logger.info(f'Invalid Url: {url}')
        return False
    parsing[item_id] = {
        'item_url': url, 
        'item_service': item_service,
        'item_type': item_type, 
        'item_id': item_id
    }

def parsingworker():
    time.sleep(8)
    while True:
        if parsing:
            item_id = next(iter(parsing))
            item = parsing.pop(item_id)

            if item_id in pending or item_id in download_queue:
                logger.info(f"Item Already Parsed: {item}")
                continue
            else:
                logger.info(f"Parsing: {item}")

                current_service = item['item_service']
                current_type = item['item_type']
                current_id = item['item_id']
                token = get_account_token()
                
                if current_service == "spotify":
                    if current_type == "track":
                        pending[item_id] = {
                            'item_service': current_service,
                            'item_type': current_type,
                            'item_id': item_id,
                            'is_playlist_item': False,
                            }
                        continue

                    elif current_type == "album":
                        tracks = spotify_get_album_tracks(token, current_id)
                        for index, track in enumerate(tracks):
                            item_id = track['id']
                            pending[item_id] = {
                                'item_service': 'spotify',
                                'item_type': 'track',
                                'item_id': item_id,
                                'is_playlist_item': False,
                                }
                        continue

                    elif current_type == "playlist":
                        items = spotify_get_playlist_items(token, current_id)
                        playlist_name, playlist_by = spotify_get_playlist_data(token, current_id)
                        for index, item in enumerate(items):
                            item_id = item['track']['id']
                            item_type = item['track']['type']
                            pending[item_id] = {
                                'item_service': 'spotify',
                                'item_type': item_type,
                                'item_id': item_id,
                                'is_playlist_item': True,
                                'playlist_name': playlist_name,
                                'playlist_by': playlist_by
                                }
                        continue

                    elif current_type == "artist":
                        album_urls = spotify_get_artist_albums(token, current_id)
                        for index, album_url in enumerate(album_urls):
                            parse_url(album_url)
                        continue

                    elif current_type == "episode":
                        pending[item_id] = {
                            'item_service': current_service,
                            'item_type': current_type,
                            'item_id': item_id,
                            'is_playlist_item': False,
                            }
                        continue

                    elif current_type in ['show', 'audiobook']:
                        episode_urls = spotify_get_show_episodes(token, current_id)
                        for index, episode_url in enumerate(episode_urls):
                            parse_url(episode_url)
                        continue

                    elif current_type == "liked_songs":
                        tracks = spotify_get_liked_songs(token)
                        for index, track in enumerate(tracks):
                            item_id = track['track']['id']
                            pending[item_id] = {
                                'item_service': 'spotify',
                                'item_type': 'track',
                                'item_id': item_id,
                                'is_playlist_item': True,
                                'playlist_name': 'Liked Songs',
                                'playlist_by': 'me'
                                }
                        continue

                    elif current_type == "your_episodes":
                        tracks = spotify_get_your_episodes(token)
                        for index, track in enumerate(tracks):
                            item_id = track['show']['id']
                            pending[item_id] = {
                                'item_service': 'spotify',
                                'item_type': 'episode',
                                'item_id': item_id,
                                'is_playlist_item': True,
                                'playlist_name': 'Your Episodes',
                                'playlist_by': 'me'
                                }
                        continue

                elif current_service == "soundcloud":

                    if current_type == "track":
                        pending[item_id] = {
                            'item_service': current_service,
                            'item_type': current_type,
                            'item_id': item_id,
                            'is_playlist_item': False,
                            }
                        time.sleep(4)
                        continue

                    if current_type in ["album", "playlist"]:
                        # Items are added to pending in function to avoid complexity
                        soundcloud_get_set_items(token, item['item_url'])

        else:
            time.sleep(4)
