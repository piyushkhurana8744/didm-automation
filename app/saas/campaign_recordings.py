"""Authenticated access to Excel call audio retained by Sarvam.

Only the server contacts the documented recording API; provider keys and media links
never reach the browser. This does not depend on training recording settings.
"""
from types import SimpleNamespace

from .intelligence import JobGiveUp, JobRetry
from .providers import SarvamAnalytics, SarvamRecordingSource
from .recordings import MAX_RECORDING_BYTES, ALLOWED_CONTENT_TYPES, valid_audio_bytes


class CampaignRecordings:
    def __init__(self, settings, analytics=None, source=None):
        self.s = settings
        self.analytics = analytics or SarvamAnalytics(settings)
        self.source = source or SarvamRecordingSource(settings)

    def configured(self):
        return bool(self.s.sarvam_api_key and self.s.sarvam_org_id and self.s.sarvam_workspace_id)

    def fetch(self, call, batch):
        if not self.configured():
            raise JobRetry("not_configured", "Sarvam recording access is not configured.")
        sess = SimpleNamespace(
            provider_app_id=batch.provider_app_id,
            provider_attempt_id=call.attempt_id,
            provider_session_id=(call.raw_result or {}).get("interaction_id"),
            started_at=call.started_at, created_at=call.started_at,
            max_duration_seconds=max(call.duration or 0, 3600),
        )
        if not sess.provider_session_id:
            attempt = self.analytics.find_attempt(sess)
            sess.provider_session_id = (attempt or {}).get("interaction_id")
        if not sess.provider_session_id:
            return None
        url = self.source.fetch_url(sess, {})
        if not url:
            return None
        data, content_type = self.source.download(url, MAX_RECORDING_BYTES)
        if not data:
            return None
        content_type = (content_type or "").split(";")[0].strip().lower()
        if (len(data) > MAX_RECORDING_BYTES or content_type not in ALLOWED_CONTENT_TYPES
                or not valid_audio_bytes(data, content_type)):
            raise JobGiveUp("invalid_audio", "Sarvam did not return a valid audio recording.")
        return data, content_type, sess.provider_session_id
