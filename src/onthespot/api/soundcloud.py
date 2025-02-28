import re
import requests
from ..otsconfig import config
from ..runtimedata import get_logger, account_pool, pending
from ..utils import make_call, conv_list_format

SOUNDCLOUD_BASE = "https://api-v2.soundcloud.com"

SOUNDCLOUD_CLIENT_ID = "AADp6RRMinJzmrc26qh92jqzJOF69SwF"
SOUNDCLOUD_APP_VERSION = "1728640498"
SOUNDCLOUD_APP_LOCALE = "en"

logger = get_logger("worker.utility")

def soundcloud_parse_url(url):
        headers = {}
        headers["user-agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/77.0.3865.90 Safari/537.36"

        params = {}
        params["client_id"] = SOUNDCLOUD_CLIENT_ID
        params["app_version"] = SOUNDCLOUD_APP_VERSION
        params["app_locale"] = SOUNDCLOUD_APP_LOCALE
        params["url"] = url

        resp = requests.get(f"{SOUNDCLOUD_BASE}/resolve", headers=headers, params=params).json()

        item_id = str(resp["id"])
        item_type = resp["kind"]
        return item_type, item_id

def soundcloud_login_user(account):

    # Add support for logging in
    if account['uuid'] == 'public_soundcloud':
        response = requests.get("https://soundcloud.com")


        page_text = response.text

        client_id_url_match = re.finditer(
            r"<script\s+crossorigin\s+src=\"([^\"]+)\"",
                page_text,
            )

        *_, client_id_url_match = client_id_url_match

        #if client_id_url_match:
            #logger.info("Found client_id_url:", client_id_url_match.group(1))  # Access the captured group  
        #else:
            #logger.info(f"Failed to fetch free soundcloud client_id: {response.status_code}")

        client_id_url = client_id_url_match.group(1)

        app_version_match = re.search(
            r'<script>window\.__sc_version="(\d+)"</script>',
            page_text,
        )
        if app_version_match is None:
            raise Exception("Could not find app version in %s" % client_id_url)

        app_version = app_version_match.group(1)

        response2 = requests.get(client_id_url)

        page_text2 = response2.text

        client_id_match = re.search(r'client_id:\s*"(\w+)"', page_text2)
        assert client_id_match is not None  
        client_id = client_id_match.group(1)

        accounts = config.get('accounts') 
        # Remove public from list
        accounts = [account for account in accounts if account["uuid"] != "public_soundcloud"]

        new_user = {
            "uuid": "public_soundcloud",
            "service": "soundcloud",
            "active": True,
            "login": {
                "client_id": client_id,
                "app_version": app_version,
                "app_locale": "en",
            }
        }
        accounts.insert(0, new_user)

        config.set_('accounts', accounts)
        config.update()

        account_pool.append({
            "uuid": "public_soundcloud",
            "username": client_id,
            "service": "soundcloud",
            "status": "active",
            "account_type": "public",
            "bitrate": "128k",
            "login": {
                "client_id": client_id,
                "app_version": app_version,
                "app_locale": "en",
            }
        })


        logger.info(f"Refreshed SoundCloud tokens as {client_id} {app_version}")
        return True

def soundcloud_get_token(parsing_index):
    accounts = config.get("accounts")
    client_id = accounts[parsing_index]['login']["client_id"]
    app_version = accounts[parsing_index]['login']["app_version"]
    app_locale = accounts[parsing_index]['login']["app_locale"]
    return {"client_id": client_id, "app_version": app_version, "app_locale": app_locale}

def soundcloud_get_search_results(token, search_term, content_types):
    headers = {}
    headers["user-agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/77.0.3865.90 Safari/537.36"

    params = {}
    params["client_id"] = token['client_id']
    params["app_version"] = token['app_version']
    params["app_locale"] = token['app_locale']
    params["q"] = search_term

    track_url = f"{SOUNDCLOUD_BASE}/search/tracks"
    playlist_url = f"{SOUNDCLOUD_BASE}/search/playlists"

    track_search = requests.get(track_url, headers=headers, params=params).json()
    playlist_search = requests.get(playlist_url, headers=headers, params=params).json()

    search_results = []
    for track in track_search['collection']:
        search_results.append({
            'item_id': track['id'],
            'item_name': track['title'],
            'item_by': track['user']['username'],
            'item_type': "track",
            'item_service': "soundcloud",
            'item_url': track['permalink_url'],
            'item_thumbnail_url': track["artwork_url"]
        })
    for playlist in playlist_search['collection']:
        search_results.append({
            'item_id': playlist['id'],
            'item_name': playlist['title'],
            'item_by': playlist['user']['username'],
            'item_type': "playlist",
            'item_service': "soundcloud",
            'item_url': playlist['permalink_url'],
            'item_thumbnail_url': playlist["artwork_url"]
        })

    logger.info(search_results)
    return search_results


def soundcloud_get_set_items(token, url):
    headers = {}
    headers["user-agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/77.0.3865.90 Safari/537.36"

    params = {}
    params["client_id"] = token['client_id']
    params["app_version"] = token['app_version']
    params["app_locale"] = token['app_locale']
    params["url"] = url

    tracks = []
    try:
        set_data = requests.get(f"{SOUNDCLOUD_BASE}/resolve", headers=headers, params=params).json()

        for track in set_data.get('tracks'):
            pending[track.get('id')] = {
                'item_url': track.get('permalink_url'), 
                'item_service': 'soundcloud',
                'item_type': 'track', 
                'item_id': track.get('id'),
                'is_playlist_item': not set_data['is_album'],
                'playlist_name': set_data['title'],
                'playlist_by': set_data['user']['username']
            }
    except (TypeError, KeyError):
        logger.info(f"Failed to parse tracks for set: {url}")

def soundcloud_get_track_metadata(token, item_id):
    headers = {}
    headers["user-agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/77.0.3865.90 Safari/537.36"

    params = {}
    params["client_id"] = token['client_id']
    params["app_version"] = token['app_version']
    params["app_locale"] = token['app_locale']

    track_data = make_call(f"{SOUNDCLOUD_BASE}/tracks/{item_id}", headers=headers, params=params)
    track_file = requests.get(track_data["media"]["transcodings"][0]["url"], headers=headers, params=params).json()
    track_webpage = requests.get(f"{track_data['permalink_url']}/albums").text
    # Parse album webpage
    start_index = track_webpage.find('<h2>Appears in albums</h2>')
    if start_index != -1:
        album_href = re.search(r'href="([^"]*)"', track_webpage[start_index:])
        if album_href:
            params["url"] = f"https://soundcloud.com{album_href.group(1)}"
            album_data = requests.get(f"{SOUNDCLOUD_BASE}/resolve", headers=headers, params=params).json()

    info = {}

    # Many soundcloud songs are missing publisher metadata, parse if exists.

    # Artists
    artists = []
    for item in track_data.get('publisher_metadata', {}).get('artist', '').split(','):
        artists.append(item.strip())
    artists = conv_list_format(artists)
    if artists == '':
        artists = track_data.get('user', {}).get('username', '')
    # Track Number
    try:
        total_tracks = album_data['track_count']
        track_number = 0
        for track in album_data['tracks']:
            track_number = track_number + 1
            if track['id'] == track_data['id']:
                break
    except (KeyError, TypeError):
        total_tracks = '1'
        track_number = '1'
    # Album Name
    try:
        album_name = track_data['publisher_metadata']['album_name']
    except (KeyError, TypeError):
        start_index = track_webpage.find('<h2>Appears in albums</h2>')
        if start_index != -1:
            a_tag_match = re.search(r'<a[^>]*>(.*?)</a>', track_webpage[start_index:])
            if a_tag_match:
                album_name = a_tag_match.group(1)
        if album_name.startswith("Users who like"):
            album_name = track_data['title']

    publisher_metadata = track_data.get('publisher_metadata')
    copyright = [item.strip() for item in publisher_metadata.get('c_line', '').split(',')] if publisher_metadata and publisher_metadata.get('c_line') else ""
    copyright = conv_list_format(copyright)

    info['image_url'] = track_data.get("artwork_url", "")
    info['description'] = str(track_data.get("description", ""))
    info['genre'] = conv_list_format([track_data.get('genre', [])])

    label = track_data.get('label_name', "")
    if label:
        info['label'] = label
    info['item_url'] = track_data.get('permalink_url', "")

    release_date = track_data.get("release_date", "")
    last_modified = track_data.get("last_modified", "")
    info['release_year'] = release_date.split("-")[0] if release_date else last_modified.split("-")[0]

    info['title'] = track_data.get("title", "")
    info['track_number'] = track_number
    info['total_tracks'] = total_tracks
    info['file_url'] = track_file.get("url", "")
    info['length'] = str(track_data.get("media", {}).get("transcodings", [{}])[0].get("duration", 0))
    info['artists'] = artists
    info['album_name'] = album_name
    info['album_artists'] = track_data.get('user', {}).get('username', '')
    info['explicit'] = publisher_metadata.get('explicit', False) if publisher_metadata else False
    info['copyright'] = copyright
    info['is_playable'] = track_data.get('streamable', '')

    return info
