import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readCalendarState,readCalendarPreview,readCalendarComparison,publicationActions,publicationStatus,publishedEventRange,validQueueReceipt} from '../frontend/src/lib/calendarPublish.ts';

const event=()=>({id:'event1',revision:1,title:'合成日程',start:'2028-03-01T00:00:00+08:00',end:'2028-03-03T00:00:00+08:00',allDay:true,location:'合成城市',note:''});
const source=()=>({id:'source1',name:'合成日历',accountId:'account1',provider:'google',accountName:'合成成员',writeAuthorized:false});
const row=()=>({id:'publication1',entityId:'event1',sourceId:'source1',provider:'google',status:'published',error:'',reviewRequired:0,localRevision:1,updatedAt:'2028-02-01',localChangesPending:false});
const snapshot=()=>({journeyId:'journey1',events:[event()],sources:[source()],publications:[row()],note:'确认后持续同步'});
test('read state binds journey and preserves pending local changes independently of cloud status',()=>{
 const value=snapshot();value.publications[0].localChangesPending=true;
 assert.match(publicationStatus(readCalendarState(value,'journey1').publications[0]),/等待云端确认/);
 assert.throws(()=>readCalendarState(value,'journey2'));
});
test('state rejects malformed events, duplicate bindings and unreliable grant types',()=>{
 for(const mutate of [s=>s.events[0].end='nonsense',s=>s.events[0].revision=0,s=>s.events.push({...s.events[0]}),s=>s.sources.push({...s.sources[0]}),s=>s.sources[0].writeAuthorized='yes',s=>s.publications[0].localChangesPending=undefined,s=>s.publications.push({...s.publications[0]})]){
  const value=snapshot();mutate(value);assert.throws(()=>readCalendarState(value,'journey1'));
 }
});
test('deleted local event can still expose its existing publication for safe stop',()=>{
 const value=snapshot();value.publications[0].entityId='deleted';value.publications[0].status='local_deleted';value.publications[0].localChangesPending=null;
 assert.deepEqual(publicationActions(readCalendarState(value,'journey1').publications[0]),[]);
});
test('first pending queue has no last published hash and accepts null comparison',()=>{
 const value=snapshot();Object.assign(value.publications[0],{status:'pending',localRevision:null,localChangesPending:null});
 assert.equal(publicationStatus(readCalendarState(value,'journey1').publications[0]),'等待同步');
 value.publications[0].status='needs_authorization';assert.match(publicationStatus(readCalendarState(value,'journey1').publications[0]),/等待日历写入授权/);
});
test('missing local event does not imply last successful remote event is still up to date',()=>{
 const value=snapshot();Object.assign(value.publications[0],{entityId:'missing',localChangesPending:null});
 assert.match(publicationStatus(readCalendarState(value,'journey1').publications[0]),/待核对/);
});
test('review flag prevents retry/resume even when paused',()=>{
 const value={...row(),status:'paused',reviewRequired:1};assert.deepEqual(publicationActions(value),['review']);
 assert.match(publicationStatus(value),/时间变化/);
 assert.deepEqual(publicationActions({...value,status:'needs_review'}),['review','pause']);
});
test('ordinary conflict and paused records offer only their permitted actions',()=>{
 assert.deepEqual(publicationActions({...row(),status:'conflict'}),['conflict','pause']);
 assert.deepEqual(publicationActions({...row(),status:'paused'}),['resume']);
 assert.deepEqual(publicationActions({...row(),status:'retry'}),['retry','pause']);
 assert.deepEqual(publicationActions({...row(),status:'future-status'}),[]);
});
test('preview requires exact selected source and bounded valid event list',()=>{
 const value={events:[event()],source:source(),previewToken:'signed',note:'only preview'};
 assert.equal(readCalendarPreview(value,'source1').source.writeAuthorized,false);
 assert.throws(()=>readCalendarPreview(value,'other'));
 assert.throws(()=>readCalendarPreview({...value,events:[]},'source1'));
 assert.throws(()=>readCalendarPreview({...value,previewToken:''},'source1'));
});
test('absent remote only allowed for explicit time review, never conflict overwrite',()=>{
 const value={local:event(),remote:null,previous:null,previewToken:'signed',note:'review'};
 assert.equal(readCalendarComparison(value,true).remote,null);
 assert.throws(()=>readCalendarComparison(value,false));
 assert.throws(()=>readCalendarComparison({...value,previous:{title:'bad'}},true));
});
test('all-day uses exclusive end and timed display retains explicit timezone',()=>{
 assert.equal(publishedEventRange(event()),'2028-03-01 — 2028-03-02 · 全天');
 assert.equal(publishedEventRange({...event(),end:'2028-03-02T00:00:00+08:00'}),'2028-03-01 · 全天');
 assert.match(publishedEventRange({...event(),allDay:false}),/\+08:00/);
});
test('queue receipt is acceptance, requires exact boolean and publication IDs',()=>{
 assert.equal(validQueueReceipt({queued:true,publicationIds:['pub1'],needsAuthorization:true}),true);
 for(const value of [{queued:true},{queued:false,publicationIds:['pub1'],needsAuthorization:false},{queued:true,publicationIds:[],needsAuthorization:false},{queued:true,publicationIds:['../leak'],needsAuthorization:false}])assert.equal(validQueueReceipt(value),false);
});
