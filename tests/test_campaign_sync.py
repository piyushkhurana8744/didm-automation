from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from app.db import Batch, CallAttempt, SessionLocal, utcnow
from app.saas.campaign_sync import CampaignSync
from app.saas.intelligence import JobRetry
from tests.test_automation import env, result  # noqa: F401


def setup_call(env):
    from app.excel_leads import DatabaseLeadSheet, save_upload
    _, auto, _, _, *_ = env([], whatsapp_enabled=False)
    auto.sheet = DatabaseLeadSheet()
    save_upload([{'name':'A','phone':'9000000001','call':'YES'}])
    auto.start_batch(1)
    with SessionLocal() as db:
        call = db.scalars(select(CallAttempt)).one()
        db.get(Batch,call.batch_id).provider_app_id = 'pinned-app'
        db.commit()
        return auto, call.id


def completed():
    return {'attempt_id':'att-1','status':'connected','duration':33,
            'interaction_id':'20261116/interaction','end_datetime':(utcnow()-timedelta(seconds=1)).isoformat(),
            'final_agent_variables':{'disposition':'interested','call_summary':'Interested in course'}}


def test_missing_webhook_recovers_result_then_late_transcript_without_repeating_followup(env):
    auto, call_id = setup_call(env)
    auto._whatsapp_followup = Mock(return_value='disabled')
    provider = SimpleNamespace(find_attempt=Mock(return_value=completed()),
        fetch=Mock(side_effect=JobRetry('transcript_not_ready')))
    sync = CampaignSync(auto, provider)
    sync.run()
    with SessionLocal() as db:
        call=db.get(CallAttempt,call_id)
        assert call.state=='done' and call.summary=='Interested in course' and call.duration==33
        assert not db.get(Batch,call.batch_id).active
    provider.fetch.side_effect=None
    provider.fetch.return_value=[{'role':'agent','en_text':'Hello'}]
    sync.run()
    auto.handle_result({**result('att-1',2), 'interaction_transcript': None})
    with SessionLocal() as db:
        call=db.get(CallAttempt,call_id)
        assert call.raw_result['interaction_transcript'][0]['en_text']=='Hello'
    assert auto._whatsapp_followup.call_count==1
    provider.find_attempt.reset_mock()
    sync.run()
    provider.find_attempt.assert_not_called()


@pytest.mark.parametrize('ended,status', [(None,'connected'), ('bad','connected'),
    ((utcnow()+timedelta(hours=1)).isoformat(),'connected'),
    ((utcnow()-timedelta(seconds=1)).isoformat(),'in_progress')])
def test_incomplete_provider_result_never_ends_call(env,ended,status):
    auto,call_id=setup_call(env)
    provider=SimpleNamespace(find_attempt=lambda sess:{**completed(),'end_datetime':ended,'status':status})
    CampaignSync(auto,provider).run()
    with SessionLocal() as db:
        assert db.get(CallAttempt,call_id).state=='calling'


def test_provider_backoff_and_simulation_skip(env):
    auto,call_id=setup_call(env)
    provider=SimpleNamespace(find_attempt=Mock(side_effect=JobRetry('provider_rate_limited',retry_after=120)))
    sync=CampaignSync(auto,provider)
    sync.run();sync.run()
    assert provider.find_attempt.call_count==1
    with SessionLocal() as db:
        db.get(CallAttempt,call_id).dry_run=True;db.commit()
    sync.retry_at=utcnow()-timedelta(seconds=1)
    sync.run()
    assert provider.find_attempt.call_count==1
