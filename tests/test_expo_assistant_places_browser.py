"""Preparation checks only: no Edge/product-browser or cloud execution."""
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from unittest.mock import patch

import pytest
from scripts import check_expo_assistant_places_browser as wrapper
from browser_expo_assistant_places_check import Run, PATH, choose_page_target
from test_journey_places import app, no_network
from test_journey_documents import login


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        return subprocess.check_output(['git','-c','user.name=Synthetic Tool Test',
            '-c','user.email=synthetic@example.invalid',*args],cwd=tmp_path).decode().strip()
    git('init','--quiet');(tmp_path/'frontend').mkdir();(tmp_path/'frontend/app.tsx').write_text('synthetic\n')
    git('add','--','frontend/app.tsx');git('commit','--quiet','-m','Synthetic baseline')
    head=git('rev-parse','HEAD');evidence={'sourceHead':head,'sourceTree':git('rev-parse',head+'^{tree}')}
    def change(name):
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('synthetic change\n')
        git('add','--',name);git('commit','--quiet','-m','Synthetic delta');return git('rev-parse','HEAD')
    return git,head,evidence,change


def test_exact_three_cases_and_deduplicated_selection():
    assert len(wrapper.CASES)==3 and sum(wrapper.CASE_SCREENSHOTS.values())==8
    assert wrapper.selected_cases(None)==wrapper.CASES
    assert wrapper.selected_cases([wrapper.CASES[2],wrapper.CASES[0],wrapper.CASES[2]])==(wrapper.CASES[2],wrapper.CASES[0])
    for value in ([],['unknown'],[wrapper.CASES[0],'unknown']):
        with pytest.raises(ValueError):wrapper.selected_cases(value)


def test_exclusive_output_preserves_existing_failure(tmp_path):
    with patch.object(wrapper,'datetime') as clock:
        clock.now.return_value=datetime(2026,9,20,tzinfo=timezone.utc)
        out=wrapper.exclusive_output(tmp_path);f=out/'failure.txt';f.write_text('original')
        with pytest.raises(FileExistsError):wrapper.exclusive_output(tmp_path)
        assert f.read_text()=='original'


def test_build_reuse_only_four_tool_paths(repo):
    git,head,evidence,change=repo
    assert wrapper.build_source_delta(git,head,evidence,head)==[]
    assert len(wrapper.BUILD_REUSE_PATHS)==4
    for name in sorted(wrapper.BUILD_REUSE_PATHS):assert name in wrapper.build_source_delta(git,change(name),evidence,head)


@pytest.mark.parametrize('name',['frontend/app.tsx','frontend/new.tsx','home_assistant.py','journey_places.py','docs/OTHER.md'])
def test_build_reuse_rejects_other_bytes(repo,name):
    git,head,evidence,change=repo
    with pytest.raises(AssertionError):wrapper.build_source_delta(git,change(name),evidence,head)


def test_build_reuse_rejects_wrong_tree_and_nonancestor(repo):
    git,head,evidence,change=repo
    with pytest.raises(AssertionError):wrapper.build_source_delta(git,head,{**evidence,'sourceTree':'0'*40},head)
    later=change(wrapper.HARNESS);current={'sourceHead':later,'sourceTree':git('rev-parse',later+'^{tree}')}
    with pytest.raises(AssertionError,match='ancestor'):wrapper.build_source_delta(git,head,current,later)


def actual_run(app,tmp_path):
    client,headers=login(app)
    run=Run.__new__(Run);run.folder=Path(app.config['DATA_DIR']);run.database=run.folder/'household.sqlite3'
    def get(ctx,path,status=200):
        response=ctx.get(path);assert response.status_code==status,response.json;return response.json
    def write(ctx,method,path,body,status=200):
        response=ctx.open(path,method=method,json=body,headers=headers)
        assert response.status_code==status,response.json;return response.json
    records=[]
    run.get,run.write=get,write;run.record=lambda name,value,*_:records.append((name,value))
    return run,client,headers,records


def test_real_pagination_fixture_is_outside_map_page_and_readonly(app,tmp_path):
    run,client,_,records=actual_run(app,tmp_path)
    journey,query,item=run.paged_fixture(client)
    assert len(records)==1 and records[0][0]=='fixture-page-binding'
    recorded=records[0][1]
    assert choose_page_target(recorded['search'],recorded['map'])['id']==item['id']
    assert item['journeyId']==journey['id'] and item['canManage'] and item['revision']==1
    before=run.snapshot();detail=client.get(PATH+'/'+item['id']).json['place']
    assert detail['id']==item['id'] and run.snapshot()==before
    # Snapshot has no retained SQLite connection and its values are safe hashes.
    assert all(len(v)==64 for v in before.values())
    with pytest.raises(AssertionError):choose_page_target(recorded['search'],{**recorded['map'],'items':[item]+recorded['map']['items'][1:]})


def test_real_shared_projection_and_revoke_are_not_fake_dtos(app,tmp_path):
    run,owner,headers,_=actual_run(app,tmp_path);journey=run.journey(owner)
    shared=run.place(owner,journey,'Synthetic shared',visibility='shared',coordinateDisclosure='coarse')
    partner,_=login(app,2);current=partner.get(PATH+'/'+shared['id']).json['place']
    assert current['id']==shared['id'] and not current['canManage'] and current['coordinatePrecision']=='approximate'
    assert current['coordinates']!=shared['coordinates']
    result=owner.patch(PATH+'/'+shared['id'],json={'revision':shared['revision'],'visibility':'private'},headers=headers)
    assert result.status_code==200 and partner.get(PATH+'/'+shared['id']).status_code==404
    assert partner.get('/api/assistant/search?q=Synthetic&limit=20&offset=0').json['total']==0


def test_snapshot_closes_sqlite_on_read_error(app,tmp_path):
    run,_,_,_=actual_run(app,tmp_path);real=sqlite3.connect;connections=[]
    class FailingConnection(sqlite3.Connection):
        def execute(self,*args,**kwargs):raise sqlite3.OperationalError('synthetic read failure')
    def connect(*args,**kwargs):
        con=real(*args,**kwargs,factory=FailingConnection);connections.append(con);return con
    with patch('browser_expo_assistant_places_check.sqlite3.connect',connect):
        with pytest.raises(sqlite3.OperationalError):run.snapshot()
    assert len(connections)==1
    with pytest.raises(sqlite3.ProgrammingError,match='closed'):connections[0].cursor()


def test_actual_https_fixture_starts_and_closes_without_browser(tmp_path):
    bundle=tmp_path/'synthetic-unused-export';bundle.mkdir()
    (bundle/'index.html').write_text('<!doctype html><title>Not browser acceptance</title>')
    out=tmp_path/'output';out.mkdir()
    report={'unexpectedProviderAttempts': [], 'harnessSha256': wrapper.sha(wrapper.ROOT/wrapper.HARNESS)}
    with ExitStack() as lifecycle:
        folder=Path(lifecycle.enter_context(tempfile.TemporaryDirectory(prefix='ap-init-',dir=tmp_path)))
        run=Run(wrapper.ROOT,bundle,folder,report,out,lifecycle)
        assert run.database_proof()['items']==[] and run.database_proof()['accounts']==0
        assert run.server is not None and run.thread.is_alive()
        assert run.application.config['ASSISTANT_PROVIDER']=='local'
        assert report['fixtureHashes'][wrapper.HARNESS]==report['harnessSha256']
        assert not report['unexpectedProviderAttempts']
    assert run.server is None and not run.thread.is_alive() and not folder.exists()
