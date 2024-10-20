import os
from librespot.audio.decoders import AudioQuality, VorbisOnlyAudioQuality
from librespot.metadata import TrackId, EpisodeId
#from .spotify.api import get_item_metadata, get_episode_info, get_track_lyrics, check_premium
#from .utils.utils import re_init_session, fetch_account_uuid, sanitize_data
from .runtimedata import get_logger, download_queue, download_queue_gui, downloads_status, downloaded_data, failed_downloads, cancel_list, \
    session_pool, thread_pool
from .otsconfig import config
from .post_download import convert_audio_format, set_audio_tags, set_music_thumbnail
import traceback
from PyQt6.QtCore import QThread, pyqtSignal
from .api.spotify import spotify_get_token, spotify_get_track_metadata, spotify_get_episode_metadata, spotify_format_track_path, spotify_format_episode_path, spotify_get_lyrics
from .api.soundcloud import soundcloud_get_token, soundcloud_get_track_metadata, soundcloud_format_track_path
#, soundcloud_download_track
import time
import requests

from .accounts import get_account_token

import re
import os
import subprocess
import requests
import threading

from .runtimedata import parsing, download_queue, pending, failed, completed, cancelled


logger = get_logger("spotify.downloader")


def sanitize_data(value, allow_path_separators=False, escape_quotes=False):
    logger.info(
        f'Sanitising string: "{value}"; '
        f'Allow path separators: {allow_path_separators}'
        )
    if value is None:
        return ''
    char = config.get("illegal_character_replacement")
    if os.name == 'nt':
        value = value.replace('\\', char)
        value = value.replace('/', char)
        value = value.replace(':', char)
        value = value.replace('*', char)
        value = value.replace('?', char)
        value = value.replace('"', char)
        value = value.replace('<', char)
        value = value.replace('>', char)
        value = value.replace('|', char)
    else:
        value = value.replace('/', char)
    return value


class DownloadWorker(QThread):
    progress = pyqtSignal(dict, str, int)
    def __init__(self, gui=False):
        self.gui = gui
        super().__init__()


    def run(self):
        while True:
            if download_queue:
                item = download_queue.pop(next(iter(download_queue)))
                item_service = item['item_service']
                item_type = item['item_type']
                item_id = item['item_id']
                # Move item to bottom of download list after processing
                download_queue[item_id] = item
                try:
                    if item['gui']['status_label'].text() in (
                        self.tr("Cancelled"),
                        self.tr("Failed"),
                        self.tr("Unavailable"),
                        self.tr("Downloaded"),
                        self.tr("Already Exists")
                    ):                        
                        time.sleep(1)
                        continue
                except (RuntimeError, OSError):
                    # Item likely cleared from download queue.
                    continue
                if self.gui:
                    self.progress.emit(item, self.tr("Downloading"), 0)

                token = get_account_token()

                try:
                    item_metadata = globals()[f"{item_service}_get_{item_type}_metadata"](token, item_id)
                    
                    item_path = globals()[f"{item_service}_format_{item_type}_path"](item_metadata, item['is_playlist_item'], item['playlist_name'], item['playlist_by'])

                except Exception:
                    logger.error(
                        f"Metadata fetching failed for track by id '{item_id}', {traceback.format_exc()}")
                    continue

                dl_root = config.get("download_root")
                file_path = os.path.join(dl_root, item_path)

                os.makedirs(os.path.dirname(file_path), exist_ok=True)

                item['file_path'] = file_path
                
                # Skip file if exists under different extension
                file_directory = os.path.dirname(file_path)
                base_file_path = os.path.splitext(os.path.basename(file_path))[0]

                try:
                    files_in_directory = os.listdir(file_directory)  # Attempt to list files  
                    matching_files = [file for file in files_in_directory if file.startswith(base_file_path) and not file.endswith('.lrc')]
                    
                    if matching_files:
                        if self.gui:
                            if item['gui']['status_label'].text() == self.tr("Downloading"):
                                self.progress.emit(item, self.tr("Already Exists"), 100)  # Emit progress
                        logger.info(f"File already exists, Skipping download for track by id '{item_id}'")
                        time.sleep(1)
                        continue
                except FileNotFoundError:
                    logger.info(f"File does not already exist.")

                if not item_metadata['is_playable']:
                    logger.error(f"Track is unavailable, track id '{item_id}'")
                    if self.gui:
                        self.progress.emit([item_id, self.tr("Unavailable"), [0, 100]])
                    continue

                # Downloading the file here is necessary to animate progress bar through pyqtsignal.
                # Could at some point just update the item manually inside the api file by passing
                # item['gui']['progressbar'] and self.gui into a download_track function.
                try:
                    if item_service == "spotify":
                        if item_type == "track":
                            audio_key = TrackId.from_base62(item_id)
                        elif item_type == "episode":
                            audio_key = EpisodeId.from_base62(item_id)

                        quality = AudioQuality.HIGH
                        if token.get_user_attribute("type") == "premium" and item_type == 'track':
                            quality = AudioQuality.VERY_HIGH

                        stream = token.content_feeder().load(audio_key, VorbisOnlyAudioQuality(quality), False, None)

                        total_size = stream.input_stream.size
                        downloaded = 0
                        _CHUNK_SIZE = config.get("chunk_size")

                        with open(file_path, 'wb') as file:
                            while downloaded < total_size:
                                data = stream.input_stream.stream().read(_CHUNK_SIZE)
                                downloaded += len(data)
                                if len(data) != 0:
                                    file.write(data)
                                    if self.gui:
                                        self.progress.emit(item, self.tr("Downloading"), int((downloaded / total_size) * 100))
                                if len(data) == 0:
                                    break  # Exit if no more data is being read  
                        default_format = ".ogg"
                        bitrate = "320k" if quality == AudioQuality.VERY_HIGH else "160k"

                    elif item_service == "soundcloud":
                        command = ["ffmpeg", "-i", f"{item_metadata['file_url']}", "-c", "copy", file_path]
                        if os.name == 'nt':
                            subprocess.check_call(command, shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
                        else:
                            subprocess.check_call(command, shell=False)


                        default_format = ".mp3"
                        bitrate = "128k"

                except (RuntimeError):
                    # Likely Ratelimit
                    logger.info("Download failed: {item}")
                    self.progress.emit(item, self.tr("Failed"), 0)
                    continue

                # Convert File Format
                if self.gui:
                    self.progress.emit(item, self.tr("Converting"), 99)
                convert_audio_format(file_path, bitrate, default_format)

                # Set Audio Tags
                if self.gui:
                    self.progress.emit(item, self.tr("Embedding Metadata"), 99)
                set_audio_tags(file_path, item_metadata, item_id)

                # Thumbnail
                if self.gui:
                    self.progress.emit(item, self.tr("Setting Thumbnail"), 99)
                set_music_thumbnail(file_path, item_metadata['image_url'])

                # Lyrics
                if item_service == "spotify":
                    if self.gui:
                        self.progress.emit(item, self.tr("Getting Lyrics"), 99)
                    globals()[f"{item_service}_get_lyrics"](token, item_id, item_type, item_metadata, file_path)

                if self.gui:
                    self.progress.emit(item, self.tr("Downloaded"), 100)
            else:

                time.sleep(3)