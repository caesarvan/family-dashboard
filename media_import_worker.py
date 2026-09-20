"""One bounded Photos step per household turn; persistence belongs to MediaLibrary.

No SQL, token cache, remote URL storage, calendar sync or implicit confirmation.
An engine lease is a fence, never a substitute for current authorization.
"""
from __future__ import annotations

import logging
import os
import random
import signal
import time

from cloud_accounts import AccountBusy
from cloud_providers import ProviderError
from google_photos_picker import GooglePhotosPicker, PickerError
from media_images import MediaImageError, sanitize_media_preview
from household_media import MediaError, manifest_identity


MAX_ITEMS = 20
MAX_PAGES = 40
IMAGE_ERROR_CODES = frozenset({'invalid_input','input_too_large','unsupported_format','invalid_image',
    'multiple_frames','too_many_pixels','output_too_large','unsafe_decoder_configuration'})


def _manifest(items):
    """Compare stable public metadata by id, never expiring download URLs."""
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        return None
    result = {}
    for item in items:
        if (not isinstance(item, dict) or not isinstance(item.get('id'), str)
                or not item['id'] or item['id'] in result
                or not isinstance(item.get('mediaFile'), dict)
                or 'baseUrl' in item['mediaFile']):
            return None
        result[item['id']] = item
    return manifest_identity(list(result.values()))


class MediaImportWorker:
    """Engine v1: claim_next/validate_job/complete/fail/maintenance + accounts.

    Claim durably records create-attempted before returning a create job.
    complete/fail own all state, quota, ciphertext and authorization CAS writes.
    Every tick obtains a new credential and disposes its Picker capabilities.
    """
    def __init__(self, engine, *, picker_factory=GooglePhotosPicker,
                 sanitizer=sanitize_media_preview, video_tools=None, video_temp_root=None, jitter=None):
        self.engine = engine
        self.picker_factory = picker_factory
        self.sanitizer = sanitizer
        self.video_tools, self.video_temp_root = video_tools, video_temp_root
        self.jitter = jitter or (lambda: random.uniform(0, 5))

    def _fail(self, job, code, *, retryable=False, outcome_unknown=False, reauth=False):
        # The engine owns durable attempts, <=5 retries, original deadlines and
        # exponential backoff. This is only a bounded, nonnegative jitter floor.
        delay = (30 if code == 'rate_limited' else 5) + max(0, min(5, self.jitter()))
        self.engine.fail(job, code, retryable=retryable and job['action'] != 'create',
                         outcome_unknown=outcome_unknown, reauth=reauth,
                         retry_after=delay)

    def tick(self):
        """Run at most one claimed operation. True means claimed, not imported."""
        # claim_next includes the engine's bounded maintenance pass, even when
        # no new import is ready. Do not scan the same household twice here.
        job = self.engine.claim_next()
        if job is None:
            return False
        try:
            if not self.engine.validate_job(job):
                return True
            # CloudAccounts handles its own lock/refresh transaction. Never hold
            # an engine transaction around this call or retain a returned token.
            token = self.engine.accounts.photos_access_token(job['accountId'], job['owner'])
            if not self.engine.validate_job(job):
                return True
            with self.picker_factory(token) as picker:
                token = None
                action = job['action']
                if action == 'create':
                    session = picker.create_session(max_item_count=MAX_ITEMS)
                    # Even a revoked/expired job must hand a known session back
                    # for encrypted cleanup. Engine must not expose pickerUri
                    # or publish anything when the authorization CAS fails.
                    self.engine.complete(job, session)
                elif action == 'poll':
                    result = picker.get_session(job['session']['id'])
                    if self.engine.validate_job(job):
                        self.engine.complete(job, result)
                elif action == 'list':
                    result = picker.list_selected_media(job['session']['id'],
                                                        max_items=MAX_ITEMS, max_pages=MAX_PAGES)
                    if self.engine.validate_job(job):
                        self.engine.complete(job, result)
                elif action == 'download':
                    self._download(picker, job)
                elif action == 'cleanup':
                    self._cleanup(picker, job)
                else:
                    self._fail(job, 'worker_error')
        except PickerError as error:
            self._fail(job, error.code, retryable=error.retryable,
                       outcome_unknown=error.outcome_unknown, reauth=error.reauth)
        except MediaImageError as error:
            self._fail(job, error.code if isinstance(error.code,str) and error.code in IMAGE_ERROR_CODES else 'unsupported_image')
        except MediaError as error:
            self._fail(job,error.code)
        except AccountBusy:
            self._fail(job, 'unavailable', retryable=True)
        except ProviderError as error:
            reauth = bool(error.reauth)
            code = ('reauth' if reauth else
                    {403: 'forbidden', 404: 'not_found', 409: 'unavailable',
                     429: 'rate_limited'}.get(error.status, 'unavailable'))
            self._fail(job, code, retryable=not reauth and error.status not in (403, 404), reauth=reauth)
        except Exception:
            # Includes unknown create transport/commit outcomes. Never log the
            # exception, job, credential, filename, session URI or image bytes.
            self._fail(job, 'worker_error', outcome_unknown=job.get('action') == 'create')
        return True

    def _download(self, picker, job):
        session_id = job['session']['id']
        current = picker.list_selected_media(session_id, max_items=MAX_ITEMS, max_pages=MAX_PAGES)
        if not self.engine.validate_job(job):
            return
        original, observed = _manifest(job['manifest']), _manifest(current)
        media = job['media']
        media_identity = _manifest([media]) if isinstance(media,dict) else None
        if (original is None or observed != original or not isinstance(media, dict)
                or media_identity is None or observed.get(media.get('id')) != media_identity.get(media.get('id')) or media.get('type') not in ('PHOTO','VIDEO')):
            self._fail(job, 'selection_changed')
            return
        if media['type']=='VIDEO':
            refreshed = next(item for item in current if item['id']==media['id'])
            status = refreshed['mediaFile']['mediaFileMetadata'].get('videoMetadata',{}).get('processingStatus')
            if status in ('UNSPECIFIED','PROCESSING','FAILED'):
                self._fail(job,'video_not_ready')
                return
            self._download_video(picker,job,media,current,session_id)
            return
        downloaded = picker.download_media(session_id, media['id'], variant='preview', width=1600, height=1600)
        if not self.engine.validate_job(job):
            return
        preview = self.sanitizer(downloaded.data, downloaded.content_type)
        if not self.engine.validate_job(job):
            return
        # Engine rechecks current session/account/grant/fence and quota in a new
        # transaction and seals Preview + bound metadata into SQLite BLOBs.
        self.engine.complete(job, {'mediaId': media['id'], 'manifest': current, 'preview': preview})

    def _download_video(self,picker,job,media,current,session_id):
        from media_videos import MediaVideoError, VideoTools, sanitize_media_video
        config=getattr(getattr(self.engine,'app',None),'config',{})
        tools=self.video_tools or VideoTools(
            config.get('MEDIA_VIDEO_FFMPEG') or os.environ.get('MEDIA_VIDEO_FFMPEG',''),
            config.get('MEDIA_VIDEO_FFPROBE') or os.environ.get('MEDIA_VIDEO_FFPROBE',''))
        temporary=self.video_temp_root or config.get('MEDIA_VIDEO_TEMP_ROOT') or os.environ.get('MEDIA_VIDEO_TEMP_ROOT')
        downloaded=picker.download_media(session_id,media['id'],variant='video')
        if not self.engine.validate_job(job):
            return
        try:
            video=sanitize_media_video(downloaded.data,downloaded.content_type,tools=tools,temp_root=temporary)
            # Do not retain up to 100 MiB of source bytes through seal/SQLite.
            del downloaded
        except MediaVideoError as error:
            code=error.code if error.code in {'invalid_input','too_large','too_long','unsupported','invalid','timeout','tools_unavailable'} else 'invalid'
            self._fail(job,'video_'+code)
            return
        if self.engine.validate_job(job):
            self.engine.complete(job,{'mediaId':media['id'],'manifest':current,'preview':video.poster,'video':video})

    def _cleanup(self, picker, job):
        session_id = job['session']['id']
        try:
            if job['cleanupUnknown']:
                picker.get_session(session_id)
                # A previous DELETE's unknown result is never blindly retried.
                # A readable surviving session becomes unavailable and expires
                # remotely. Only 404 below establishes absence.
                self._fail(job, 'cleanup_unknown', outcome_unknown=True)
                return
            picker.delete_session(session_id)
        except PickerError as error:
            if error.code != 'not_found':
                raise
        self.engine.complete(job, None)


class StopRequest:
    def __init__(self):
        self.requested = False

    def signal(self, _number, _frame):
        self.requested = True

    def wait(self, seconds):
        until = time.monotonic() + seconds
        while not self.requested:
            remaining = until - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(.05, remaining))


class MediaScheduler:
    """Sorted rotating household cursor; one household/one step per tick.

    No executor: at most one image is decoded in this process. A failing or busy
    household advances the cursor too. A stop drains only the entered step.
    """
    def __init__(self, platform, *, stop=None, worker_factory=MediaImportWorker):
        self.platform, self.stop, self.worker_factory = platform, stop or StopRequest(), worker_factory
        self.cursor = ''

    def tick(self):
        if self.stop.requested:
            return False
        try:
            households = {h['id']: h for h in self.platform.households()}
            if not households or self.stop.requested:
                return False
            ids = sorted(households)
            uid = next((key for key in ids if key > self.cursor), ids[0])
            self.cursor = uid
            application = self.platform.child(households[uid])
            if self.stop.requested:
                return False
            engine = application.extensions['household_media']
            return self.worker_factory(engine).tick()
        except Exception:
            logging.error('Media worker step unavailable; private details omitted')
            return False


def main():
    # Import app only for the dedicated entry point, never during worker tests.
    from app import create_app
    stop, handlers = StopRequest(), {}
    try:
        for number in (signal.SIGTERM, signal.SIGINT):
            handlers[number] = signal.signal(number, stop.signal)
        app = create_app()
        scheduler = MediaScheduler(app.extensions['household_platform'], stop=stop)
        while not stop.requested:
            scheduler.tick()
            stop.wait(1)
    finally:
        for number, handler in handlers.items():
            signal.signal(number, handler)


if __name__ == '__main__':
    main()
