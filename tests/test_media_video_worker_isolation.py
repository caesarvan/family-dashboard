"""Real queue/SQLite commit fences; decoder IPC boundary is an explicit stub.

Linux Unix sockets, codec correctness and container limits are separate tests.
"""
import weakref

import pytest

import media_video_transport as transport
import media_videos
from google_photos_picker import DownloadedMedia
from media_import_worker import MediaImportWorker
from test_media_video_memory import env, staged_video


def no_local(*args, **kwargs):
    pytest.fail('Configured isolation must never call the credential-bearing local decoder')


class Picker:
    def __init__(self):
        self.downloads = []

    def download_media(self, session, uid, *, variant):
        assert variant == 'video'
        value = DownloadedMedia(b'synthetic source bytes', 'video/mp4', 'private-source.mp4', variant)
        self.downloads.append(weakref.ref(value))
        return value


@pytest.mark.parametrize('setting', ['config', 'environment'])
def test_private_socket_selected_and_original_queue_commits_after_dropping_source(env, monkeypatch, setting):
    c, _, imported, job, record, video = staged_video(env)
    monkeypatch.delenv('MEDIA_VIDEO_SOCKET', raising=False)
    if setting == 'config':
        env[0].config['MEDIA_VIDEO_SOCKET'] = '/decoder-private/video.sock'
        monkeypatch.setenv('MEDIA_VIDEO_SOCKET', '/wrong-ambient/video.sock')
    else:
        monkeypatch.setenv('MEDIA_VIDEO_SOCKET', '/decoder-private/video.sock')
    monkeypatch.setattr(media_videos, 'sanitize_media_video', no_local)
    picker, calls = Picker(), []

    def remote(raw, mime, **options):
        assert raw == b'synthetic source bytes' and mime == 'video/mp4'
        assert options == {'socket_path': '/decoder-private/video.sock', 'timeout': 900}
        calls.append(True)
        return video

    monkeypatch.setattr(transport, 'sanitize_remote_media_video', remote)
    complete = env[1].complete

    def checked_complete(work, value):
        assert picker.downloads[0]() is None
        return complete(work, value)

    monkeypatch.setattr(env[1], 'complete', checked_complete)
    MediaImportWorker(env[1], video_tools=media_videos.VideoTools('/unused/ffmpeg', '/unused/ffprobe'))._download_video(
        picker, job, record, [record], job['session']['id'])
    detail = c.get('/api/media/imports/' + imported['id']).json
    assert calls == [True] and detail['import']['state'] == 'awaiting_confirmation'
    assert len(detail['items']) == 1 and detail['items'][0]['item']['visibility'] == 'private'
    with env[1].transaction() as con:
        assert con.execute('SELECT count(*) FROM media_video_cache').fetchone()[0] == 1


@pytest.mark.parametrize('code', ['tools_unavailable', 'timeout', 'invalid'])
def test_remote_failure_has_fixed_item_error_without_local_fallback_or_retry(env, monkeypatch, code):
    c, _, imported, job, record, _ = staged_video(env)
    env[0].config['MEDIA_VIDEO_SOCKET'] = '/decoder-private/video.sock'
    monkeypatch.setattr(media_videos, 'sanitize_media_video', no_local)
    calls = []

    def remote(*args, **kwargs):
        calls.append(True)
        raise media_videos.MediaVideoError(code)

    monkeypatch.setattr(transport, 'sanitize_remote_media_video', remote)
    MediaImportWorker(env[1], jitter=lambda: 0)._download_video(Picker(), job, record, [record], job['session']['id'])
    detail = c.get('/api/media/imports/' + imported['id']).json
    assert calls == [True] and not detail['items']
    failures = [item for item in detail['import']['results'] if item['status'] == 'failed']
    assert len(failures) == 1 and failures[0]['error']['code'] == 'video_' + code
    with env[1].transaction() as con:
        assert con.execute('SELECT count(*) FROM media_video_cache').fetchone()[0] == 0


def test_cancelled_import_cannot_commit_a_late_remote_result(env, monkeypatch):
    c, headers, imported, job, record, video = staged_video(env)
    env[0].config['MEDIA_VIDEO_SOCKET'] = '/decoder-private/video.sock'
    monkeypatch.setattr(media_videos, 'sanitize_media_video', no_local)

    def remote(*args, **kwargs):
        revision = c.get('/api/media/imports/' + imported['id']).json['import']['revision']
        assert c.delete('/api/media/imports/' + imported['id'], headers=headers,
                        json={'revision': revision}).status_code == 200
        return video

    monkeypatch.setattr(transport, 'sanitize_remote_media_video', remote)
    MediaImportWorker(env[1])._download_video(Picker(), job, record, [record], job['session']['id'])
    detail = c.get('/api/media/imports/' + imported['id']).json
    assert detail['import']['state'] == 'cancelled' and not detail['items']
    with env[1].transaction() as con:
        assert con.execute('SELECT count(*) FROM media_video_cache').fetchone()[0] == 0
