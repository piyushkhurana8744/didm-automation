"""Provider history imports external calls without local campaign side effects."""
from datetime import timedelta
from types import SimpleNamespace
import json

import httpx
from sqlalchemy import select

from app.db import SessionLocal, utcnow, CallAttempt
from app.saas.models import OutboundCall, OutboundSyncState, Agent
from app.saas.outbound import OutboundHistory
from app.saas.providers import SarvamAnalytics
from app.saas.intelligence import JobRetry
from tests.test_agents import world, register  # noqa: F401
from tests.test_saas import saas  # noqa: F401
from tests.test_campaign_recordings import WAV


def setup_history(world):
    agent = register(world.a)['id']
    s = world.app.state.settings
    s.sarvam_api_key, s.sarvam_org_id, s.sarvam_workspace_id = 'key', 'org', 'workspace'
    now = utcnow()
    attempt = {'attempt_id':'direct-attempt', 'channel_direction':'outbound',
        'user_contact':'+919876543210', 'connectivity_status':'connected',
        'start_datetime':(now-timedelta(minutes=5)).isoformat(), 'end_datetime':now.isoformat(),
        'duration_in_seconds':34.2, 'interaction_id':'20261118/interaction',
        'agent_variables':{'course':'Digital marketing'}}
    class Analytics:
        def list_outbound(self, app_id, start, end, offset):
            return {'items':[attempt], 'total':1}
        def conversation(self, sess):
            return {'original':[{'role':'user','text':'Namaste'}],
                    'english':[{'role':'user','text':'Hello'}]}
    service = OutboundHistory(s, Analytics())
    world.app.state.outbound_history = service
    return agent, service, attempt


def test_import_is_idempotent_and_does_not_touch_campaigns(world):
    agent, service, attempt = setup_history(world)
    service.run(world.a.id)
    with SessionLocal() as db:
        row = db.scalars(select(OutboundCall)).one()
        assert row.agent_id == agent and row.phone == attempt['user_contact']
        assert row.transcript['original'][0]['text'] == 'Namaste'
        assert not db.scalars(select(CallAttempt)).all()
        state = db.get(OutboundSyncState, agent)
        state.retry_at = utcnow()-timedelta(seconds=1)
        db.commit()
    service.run(world.a.id)
    result = world.a.owner.get(world.a.base+'/outbound-calls').json()
    assert result['total'] == 1 and result['items'][0]['variables']['course'] == 'Digital marketing'
    assert result['agents'][0]['last_synced_at']
    assert world.b.owner.get(world.b.base+'/outbound-calls').json()['total'] == 0
    assert world.a.trainee.get(world.a.base+'/outbound-calls').status_code == 403
    assert world.a.trainer.get(world.a.base+'/outbound-calls').status_code == 200
    assert world.a.owner.get(world.a.base+'/outbound-calls?q=missing').json()['total'] == 0
    assert world.a.owner.get(world.a.base+'/outbound-calls?status=failed').json()['total'] == 0


def test_recordings_are_tenant_scoped_and_provider_errors_are_clear(world):
    agent, service, _ = setup_history(world)
    service.run(world.a.id)
    call = world.a.owner.get(world.a.base+'/outbound-calls').json()['items'][0]
    path = f"/outbound-calls/calls/{call['id']}/recording"
    seen=[]
    def fetch(call, batch):
        seen.append(batch.provider_app_id)
        return WAV, 'audio/wav', call.raw_result['interaction_id']
    world.app.state.campaign_recordings.fetch = fetch
    assert world.b.owner.get(world.b.base+path).status_code == 404
    assert world.a.trainee.get(world.a.base+path).status_code == 403
    assert not seen
    response = world.a.owner.get(world.a.base+path)
    assert response.status_code == 200 and response.content == WAV
    assert response.headers['cache-control'] == 'private, no-store'
    assert seen == ['app-sales-1']
    world.app.state.campaign_recordings.fetch = lambda *args: None
    assert world.a.owner.get(world.a.base+path).status_code == 404


def test_pagination_resumes_fixed_window_and_pending_transcripts_retry(world):
    agent_id, service, attempt = setup_history(world)
    offsets=[]
    def pages(app, start, end, offset):
        offsets.append((offset, start, end))
        return {'items':[{**attempt,'attempt_id':f'call-{offset}'}], 'total':6}
    service.analytics.list_outbound = pages
    service.analytics.conversation = lambda sess: (_ for _ in ()).throw(JobRetry('transcript_not_ready','pending'))
    service.run(world.a.id)
    with SessionLocal() as db:
        state = db.get(OutboundSyncState, agent_id)
        assert state.offset == 5 and state.last_synced_at is None
        assert db.scalars(select(OutboundCall)).all()[0].transcript == {}
        state.retry_at = utcnow()-timedelta(seconds=1)
        for call in db.scalars(select(OutboundCall)):
            call.transcript_retry_at = utcnow()-timedelta(seconds=1)
        db.commit()
    service.analytics.conversation = lambda sess: {'english':[{'role':'agent','text':'Ready'}]}
    service.run(world.a.id)
    assert [x[0] for x in offsets] == [0,1,2,3,4,5]
    assert len({(x[1],x[2]) for x in offsets}) == 1
    with SessionLocal() as db:
        assert len(db.scalars(select(OutboundCall)).all()) == 6
        assert all(c.transcript for c in db.scalars(select(OutboundCall)))


def test_direction_validation_and_backoff(world):
    agent, service, attempt = setup_history(world)
    service.analytics.list_outbound = lambda *args: {'items':[{**attempt,'channel_direction':'inbound'}]}
    service.run(world.a.id)
    assert world.a.owner.get(world.a.base+'/outbound-calls').json()['total'] == 0
    with SessionLocal() as db:
        state=db.get(OutboundSyncState,agent);state.retry_at=utcnow()-timedelta(seconds=1);db.commit()
    calls=[]
    def fail(*args):
        calls.append(1)
        raise JobRetry('provider_rate_limited','',180)
    service.analytics.list_outbound=fail
    service.run(world.a.id);service.run(world.a.id)
    assert len(calls) == 1
    with SessionLocal() as db:
        state=db.get(OutboundSyncState,agent)
        assert state.error == 'provider_rate_limited'
        assert state.retry_at > utcnow()+timedelta(seconds=170)


def test_adapter_uses_documented_filter_and_exact_interaction():
    seen=[]
    def response(req):
        seen.append(req)
        assert req.headers['X-API-Key']=='key'
        if req.url.path.endswith('/attempts'):
            assert json.loads(req.url.params['filter_conditions']) == [
                {'field':'channel_direction','operator':'equals','value':'outbound'}]
            assert req.url.params['offset']=='100'
            return httpx.Response(200,json={'items':[],'total':0})
        return httpx.Response(200,json={'items':[
            {'interaction_id':'wrong','original_transcript':[{'text':'wrong'}]},
            {'interaction_id':'right','original_transcript':[{'role':'user','text':'Hindi'}]}]})
    adapter=SarvamAnalytics(SimpleNamespace(sarvam_api_key='key',sarvam_org_id='org',sarvam_workspace_id='ws'),
                            httpx.Client(transport=httpx.MockTransport(response)))
    adapter.list_outbound('agent',utcnow()-timedelta(days=1),utcnow(),100)
    sess=SimpleNamespace(provider_app_id='agent',provider_session_id='right',started_at=utcnow(),max_duration_seconds=60)
    assert adapter.conversation(sess)['original'][0]['text']=='Hindi'
