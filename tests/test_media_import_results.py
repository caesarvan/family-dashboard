"""Synthetic images/transport, real SQLite engine and member API; no cloud IO."""
import json
import secrets

import pytest

from household_media import IMAGE_FAILURES, MediaLibrary
from media_images import MediaImageError
from media_import_worker import IMAGE_ERROR_CODES
from test_household_media import (env, offline, create, selected, session, preview, confirm, stage)
from test_journey_documents import login
from test_media_import_worker import Engine, job, worker, png
from test_google_photos_picker import Response, item, session as picker_session


def listing(env,items):
    client,headers,imported,_=create(env)
    engine=env[1]
    assert engine.complete(engine.claim_next(),session(env))
    assert engine.complete(engine.claim_next(),items)
    return client,headers,imported['id']


def read(client,uid):
    response=client.get('/api/media/imports/'+uid)
    assert response.status_code==200,response.json
    return response.json


def row(engine,uid):
    with engine.transaction() as con:
        return dict(con.execute('SELECT * FROM media_imports WHERE id=?',(uid,)).fetchone())


@pytest.mark.parametrize('ready_count',[3,4])
def test_ten_photo_results_survive_subset_confirm_cleanup_replay_and_restart(env,ready_count):
    photos=[selected('private-provider-'+str(n)) for n in range(10)]
    client,headers,uid=listing(env,photos);engine=env[1]
    initial=read(client,uid)['import']
    assert initial['counts']=={'selected':10,'ready':0,'skipped':0,'failed':0,'pending':10,'saved':0,'unselected':None}
    errors=list(IMAGE_FAILURES)
    for n in range(10):
        work=engine.claim_next();assert work['action']=='download'
        if n<ready_count:
            assert engine.complete(work,{'mediaId':work['media']['id'],'manifest':photos,'preview':preview()})
        else:
            assert engine.fail(work,errors[n-ready_count])
    before=read(client,uid)
    assert before['import']['counts']=={'selected':10,'ready':ready_count,'skipped':0,'failed':10-ready_count,'pending':0,'saved':0,'unselected':None}
    results=before['import']['results']
    assert [entry['position'] for entry in results]==list(range(1,11))
    assert all(set(entry)<= {'position','status','error'} for entry in results)
    assert [entry['error']['code'] for entry in results[ready_count:]]==errors[:10-ready_count]
    payload={'revision':before['import']['revision'],'confirmRequestId':secrets.token_hex(16),
        'itemIds':[entry['id'] for entry in before['items'][:3]],'consentVersion':'media-v1','persistSelected':True}
    first=client.post('/api/media/imports/'+uid+'/confirm',json=payload,headers=headers)
    assert first.status_code==200,first.json
    summary=first.json['import']
    assert summary['results']==results and summary['resultsState']=='known'
    assert summary['counts']=={**before['import']['counts'],'saved':3,'unselected':ready_count-3}
    cleanup=engine.claim_next();assert cleanup['action']=='cleanup'
    assert engine.complete(cleanup,None)
    after=read(client,uid)['import']
    assert (after['counts'],after['results'])==(summary['counts'],results)
    replay=client.post('/api/media/imports/'+uid+'/confirm',json=payload,headers=headers)
    assert replay.status_code==200 and replay.json['replayed']
    assert replay.json['import']==after
    persisted=row(engine,uid)
    assert persisted['manifest_cipher'] is None and persisted['session_cipher'] is None
    receipt=engine._open('import-context',persisted,persisted['context_cipher'])
    assert set(receipt)=={'consentVersion','confirmedAt','itemIds','resultSummary'}
    serialized=json.dumps(receipt)
    assert all(secret not in serialized for secret in ('private-provider-','private-synthetic-filename','mediaFile','sourceKey','subject','pickerUri'))
    assert b'resultSummary' not in persisted['context_cipher']
    restarted=MediaLibrary(env[0],clock=engine.clock)
    assert restarted._import_dto(persisted)['counts']==summary['counts']
    partner,_=login(env[0],2)
    assert partner.get('/api/media/imports/'+uid).status_code==404
    with engine.transaction() as con:
        assert con.execute("SELECT count(*) FROM media_items WHERE import_id=? AND state='ready'",(uid,)).fetchone()[0]==3


def test_skipped_and_duplicate_keep_processing_counts_separate_from_saved(env):
    c,h,detail,_=stage(env,items=[selected('existing')]);confirm(c,h,detail)
    photos=[selected('existing'),selected('non-photo','VIDEO')]
    c,h,uid=listing(env,photos)
    detail=read(c,uid)
    assert detail['import']['counts']=={'selected':2,'ready':1,'skipped':1,'failed':0,'pending':0,'saved':0,'unselected':None}
    assert detail['import']['results']==[{'position':1,'status':'duplicate'},
        {'position':2,'status':'skipped','error':{'code':'unsupported_type','message':'本次仅处理照片，已跳过非照片媒体。'}}]
    confirmed,_=confirm(c,h,detail)
    assert confirmed['import']['counts']['saved']==1 and confirmed['import']['counts']['unselected']==0


def test_legacy_confirmed_receipt_reports_only_known_saved_without_rewriting(env):
    c,h,detail,_=stage(env);confirm(c,h,detail);engine=env[1];uid=detail['import']['id']
    stored=row(engine,uid)
    receipt=engine._open('import-context',stored,stored['context_cipher']);receipt.pop('resultSummary')
    with engine.transaction(True) as con:
        con.execute('UPDATE media_imports SET context_cipher=? WHERE id=?',(engine._seal('import-context',stored,receipt),uid))
    before=row(engine,uid)
    result=read(c,uid)['import']
    assert result['resultsState']=='unknown' and result['results']==[]
    assert result['counts']=={'selected':None,'ready':None,'skipped':None,'failed':None,'pending':None,'saved':1,'unselected':None}
    assert row(engine,uid)==before  # read does not migrate old receipts
    with engine.transaction(True) as con:
        con.execute('UPDATE media_imports SET context_cipher=NULL WHERE id=?',(uid,))
    assert read(c,uid)['import']['counts']['saved'] is None


@pytest.mark.parametrize('cleanup_failure',[False,True])
def test_all_failed_terminal_cleanup_preserves_safe_summary(env,cleanup_failure):
    photos=[selected('provider-secret')];c,h,uid=listing(env,photos);engine=env[1]
    assert engine.fail(engine.claim_next(),'unsupported_format')
    before=read(c,uid)['import'];assert before['state']=='failed'
    cleanup=engine.claim_next();assert cleanup['action']=='cleanup'
    assert engine.fail(cleanup,'network') if cleanup_failure else engine.complete(cleanup,None)
    after=read(c,uid)['import']
    assert after['results']==before['results'] and after['counts']==before['counts']
    stored=row(engine,uid)
    assert stored['manifest_cipher'] is None and stored['session_cipher'] is None
    receipt=engine._open('import-context',stored,stored['context_cipher'])
    assert set(receipt)=={'resultSummary'} and 'provider-secret' not in json.dumps(receipt)


def test_cancel_preserves_partial_results_but_scope_removal_erases_receipt(env):
    photos=[selected('one'),selected('two')];c,h,uid=listing(env,photos);engine=env[1]
    assert engine.fail(engine.claim_next(),'invalid_image')
    before=read(c,uid)['import']
    assert c.delete('/api/media/imports/'+uid,json={'revision':before['revision']},headers=h).status_code==200
    after=read(c,uid)['import']
    assert after['state']=='cancelled' and after['counts']['pending']==1
    assert after['results']==before['results']
    with engine.transaction(True) as con:
        engine.on_account_authority_changed(con,env[3][1],'scope_revoked')
    stored=row(engine,uid)
    assert all(stored[key] is None for key in ('context_cipher','manifest_cipher','session_cipher'))
    assert read(c,uid)['import']['resultsState']=='unknown'


def test_corrupt_diagnostics_never_block_privacy_cleanup(env):
    photos=[selected('private')];c,h,uid=listing(env,photos);engine=env[1]
    with engine.transaction(True) as con:
        con.execute('UPDATE media_imports SET manifest_cipher=? WHERE id=?',(b'invalid-ciphertext',uid))
        engine.on_account_removed(con,env[3][1])
    stored=row(engine,uid)
    assert stored['state']=='cancelled' and stored['context_cipher'] is None and stored['manifest_cipher'] is None


@pytest.mark.parametrize('code',sorted(IMAGE_ERROR_CODES)+['unknown-private-decoder-message'])
def test_worker_preserves_only_allowed_decoder_code(png,code,capsys,caplog):
    engine=Engine(job())
    def failed(_raw,_mime):
        error=MediaImageError('invalid_image');error.code=code
        raise error
    run,_,_=worker(engine,picker_session(),{'mediaItems':[item()]},Response(png,mime='image/png'),sanitizer=failed)
    assert run.tick() and not engine.completed
    assert engine.failed[0][0]==(code if code in IMAGE_ERROR_CODES else 'unsupported_image')
    assert 'unknown-private-decoder-message' not in caplog.text+str(capsys.readouterr())
