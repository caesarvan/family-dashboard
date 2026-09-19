import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync,existsSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {runInNewContext} from 'node:vm';
import {webcrypto} from 'node:crypto';

const require=createRequire(import.meta.url),ts=require('typescript'),root=resolve(dirname(fileURLToPath(import.meta.url)),'../src');
const clone=value=>JSON.parse(JSON.stringify(value));
function loader(mocks={},globals={}) {
  const cache=new Map();
  function load(path) {
    path=resolve(path);if(!existsSync(path))path+=existsSync(path+'.ts')?'.ts':'.tsx';
    if(cache.has(path))return cache.get(path);
    const exports={};cache.set(path,exports);
    const code=ts.transpileModule(readFileSync(path,'utf8'),{fileName:path,compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
    runInNewContext(code,{exports,require:name=>name in mocks?mocks[name]:load(resolve(dirname(path),name)),Date,Intl,Error,URL,URLSearchParams,TextEncoder,TextDecoder,AbortController,crypto:webcrypto,process:{env:{}},...globals});return exports;
  }return load;
}
const load=loader(),api=load(resolve(root,'lib/api.ts')),assistant=load(resolve(root,'lib/assistant.ts')),identity=load(resolve(root,'lib/sessionIdentity.ts')),documents=load(resolve(root,'lib/journeyDocuments.ts'));
const documentId='d'.repeat(32),photoId='a'.repeat(24),journeyId='1'.repeat(24),tripId='2'.repeat(24);
const journey={id:journeyId,tripId,title:'合成旅行'};
const docMatch=(patch={})=>({kind:'documents',id:documentId,title:'旧资料标题',filename:'old.pdf',mimeType:'application/pdf',revision:1,visibility:'private',journey,...patch});
const photoMatch=(patch={})=>({kind:'media',id:photoId,title:'旧照片说明',revision:1,visibility:'private',journey,...patch});
const page=(matches,offset=0,total=matches.length)=>({query:'凭证',matches,total,limit:20,offset,nextOffset:offset+matches.length<total?offset+matches.length:null});
const record=(patch={})=>({id:documentId,journeyId,owner:'alice',title:'当前资料标题',filename:'current.pdf',mimeType:'application/pdf',bytes:40,visibility:'private',segmentKey:'',unlinked:false,segmentMissing:false,createdAt:'2026-09-19T00:00:00Z',updatedAt:'2026-09-19T00:00:00Z',revision:2,canManage:true,downloadUrl:'/api/journey-documents/'+documentId+'/file',...patch});
const photo=(patch={})=>({id:photoId,revision:2,caption:'当前照片说明',width:800,height:600,previewUrl:'/api/media/items/'+photoId+'/preview',visibility:'private',canManage:true,createdAt:'2026-09-19T00:00:00Z',journey,...patch});
const session=()=>({user:{id:'alice',name:'合成本人',role:'member',householdId:'home',auth_version:1},csrf:'synthetic-csrf'});
const deferred=()=>{let release;return{promise:new Promise(resolve=>{release=resolve;}),release:()=>release()};};

test('document/media search metadata is strictly read and navigation keeps only original target identifiers',()=>{
  const wire=page([docMatch({owner:'SECRET',bytes:99,downloadUrl:'https://invalid.test/file'}),photoMatch({previewUrl:'https://invalid.test/photo'})]);
  const result=assistant.readAssistantSearch(wire,{query:' 凭证 ',offset:0});
  assert.equal(result.matches[0].filename,'old.pdf');assert(!('owner' in result.matches[0]));assert(!('bytes' in result.matches[0]));assert(!('downloadUrl' in result.matches[0]));assert(!('previewUrl' in result.matches[1]));
  assert.deepEqual(clone(assistant.assistantContentRequest(result.matches[0],1)),{kind:'documents',key:1,id:documentId,journeyId});
  assert.deepEqual(clone(assistant.assistantContentRequest(result.matches[1],2)),{kind:'media',key:2,id:photoId});
  assert.deepEqual(clone(assistant.assistantContentRequest(docMatch({journey:null}),3)),{kind:'documents',key:3,id:documentId});
  assert.equal(assistant.assistantContentRequest(docMatch({id:'../file'}),1),null);
  assert.equal(assistant.assistantContentRequest(photoMatch(),0),null);
});
test('invalid document IDs, ACL metadata, MIME, duplicate or contradictory pages cannot render as search hits',()=>{
  for(const patch of [{id:photoId},{revision:0},{visibility:'public'},{journey:undefined},{journey:{...journey,id:documentId}},{journey:null,visibility:'shared'},{mimeType:'text/html'},{filename:'../private.pdf'}])assert.throws(()=>assistant.readAssistantSearch(page([docMatch(patch)])));
  for(const wire of [page([docMatch(),docMatch()]),{...page([docMatch()]),total:2},{...page([docMatch()]),nextOffset:20},{...page([docMatch()]),offset:-1}])assert.throws(()=>assistant.readAssistantSearch(wire));
  assert.throws(()=>assistant.readAssistantSearch(page([docMatch()]),{query:'不同请求',offset:0}));
  assert.throws(()=>assistant.readAssistantSearch(page([docMatch()]),{query:'凭证',offset:20}));
});

// Real AssistantEntry/AssistantFlow, document panel/DocumentFence and photo
// screen/PhotoReadFence run together. Only Paper/native hosts, timers and HTTP
// transport are synthetic. This is not browser, database or cloud evidence.
function harness(options={}) {
  const f={session:session(),matches:[docMatch()],documents:[record()],photo:photo(),calls:[],mutations:[],gate:null,documentStatus:0,photoStatus:0,failMeAfterPhoto:false,photoReads:0,refreshes:0,...options};
  let holder,cursor=0,dirty=true,tree,serial=0,closed=false;
  const instances=new Map(),types=new Map(),effects=[],listeners=new Map(),timers=new Map();
  const events={addEventListener(key,fn){if(!listeners.has(key))listeners.set(key,new Set());listeners.get(key).add(fn);},removeEventListener(key,fn){listeners.get(key)?.delete(fn);}};
  const document={hidden:false,hasFocus:()=>true,...events},window={...events},navigator={onLine:true};
  const changed=(a,b)=>!a||!b||a.length!==b.length||a.some((v,i)=>v!==b[i]);
  const useState=initial=>{const h=holder,i=cursor++;if(!(i in h.values))h.values[i]=typeof initial==='function'?initial():initial;return[h.values[i],next=>{if(!h.dead){h.values[i]=typeof next==='function'?next(h.values[i]):next;dirty=true;}}];};
  const useRef=initial=>{const i=cursor++;if(!(i in holder.values))holder.values[i]={current:initial};return holder.values[i];};
  const useEffect=(fn,deps)=>{const h=holder,i=cursor++;if(changed(h.values[i],deps)){h.values[i]=deps;effects.push(()=>{h.cleanups[i]?.();if(!h.dead)h.cleanups[i]=fn();});}};
  const useCallback=(fn,deps)=>{const i=cursor++;if(!holder.values[i]||changed(holder.values[i].deps,deps))holder.values[i]={deps,fn};return holder.values[i].fn;};
  const react={useState,useRef,useEffect,useCallback,Fragment:'Fragment',createElement:(type,props,...children)=>({type,props:{...props,children:children.flat(Infinity).filter(n=>n!==null&&n!==undefined&&n!==false)}})};
  const household={user:clone(f.session.user),identityKey:identity.sessionIdentity(f.session),online:true,state:{people:[]},refresh:async()=>{f.refreshes++;},setNotice(){}};
  const search=offset=>page(clone(f.matches.slice(offset,offset+20)),offset,f.matches.length);
  async function request(path) {
    f.calls.push(path);let value;
    if(path==='/me'){if(f.failMeAfterPhoto&&f.photoReads)throw new api.ApiError('无法核对当前登录',0);value=clone(f.session);}
    else if(path==='/assistant/brief')value={modelConfigured:false};
    else if(path.startsWith('/assistant/search?')){const u=new URL('https://synthetic.invalid'+path);value=search(Number(u.searchParams.get('offset')));}
    else if(path.startsWith('/journey-documents')){
      if(f.documentStatus)throw new documents.DocumentError('资料已不可用，请返回搜索重新查询。',f.documentStatus);
      const scoped=new URL('https://synthetic.invalid'+path).searchParams.get('journeyId');
      if(scoped&&f.scopedDocumentStatus)throw new documents.DocumentError('原旅行已不可用',f.scopedDocumentStatus);
      value={journey:scoped?{id:scoped,title:journey.title,revision:1}:null,segments:[],journeys:[{id:journeyId,title:journey.title}],documents:clone(f.documents),limits:{maxFileBytes:5000000,formats:['pdf','jpg','jpeg','png','webp']}};
    }
    else if(path.startsWith('/media/items?'))value={items:[],total:0,hasMore:false};
    else if(path==='/media/items/'+photoId){f.photoReads++;if(f.photoStatus)throw new api.ApiError('照片已不可用',f.photoStatus);value={item:clone(f.photo)};}
    else if(path==='/media/items/'+photoId+'/tv-grants')value={revision:f.photo.revision,deviceIds:[]};
    else if(path==='/accounts')value={accounts:[]};else if(path==='/devices')value=[];else if(path==='/journeys')value={journeys:[]};else if(path.startsWith('/media/imports?'))value={items:[]};
    else throw new Error('Unexpected synthetic HTTP '+path);
    if(f.gate?.path===path)await f.gate.promise;
    return value;
  }
  household.mutate=async(path,method,body)=>{
    f.mutations.push({path,method,body:clone(body)});
    if(path==='/assistant/plan')return{mode:'local',id:null,summary:'只读搜索',actions:[],matches:search(0).matches,search:{...search(0),matches:undefined}};
    throw new Error('Unexpected synthetic business mutation '+path);
  };
  const paper=Object.fromEntries(['ActivityIndicator','Button','Chip','Divider','HelperText','Icon','Image','Text','TextInput','TouchableRipple','Portal','ProgressBar','SegmentedButtons'].map(k=>[k,k]));
  for(const [name,children]of Object.entries({Dialog:['Title','Content','Actions','ScrollArea'],Menu:['Item'],List:['Accordion','Item'],Card:['Content'],Checkbox:['Android','Item']}))paper[name]=Object.assign(name,...children.map(child=>({[child]:name+child})));
  paper.useTheme=()=>({colors:{error:'#b00',onSurfaceVariant:'#555',onSurface:'#111',primary:'#000',surface:'#fff',onSurfaceDisabled:'#888'}});
  const mocks={react,'react-native':{View:'View',Image:'Image',ScrollView:'ScrollView',Platform:{OS:'web'},StyleSheet:{create:x=>x},useWindowDimensions:()=>({width:390,height:844}),AppState:{currentState:'active',addEventListener:(_name,fn)=>{events.addEventListener('app',fn);return{remove:()=>events.removeEventListener('app',fn)};}},Linking:{}},'react-native-paper':paper,'expo-router':{useFocusEffect:fn=>useEffect(fn,[fn])},'../lib/household':{useHousehold:()=>household},'../lib/api':{...api,request},'./api':{...api,request},'../lib/journeyDocuments':{...documents,documentRequest:request},'../ui/components':{PageHeader:'PageHeader',SectionCard:'SectionCard',EmptyState:'EmptyState'},'../ui/theme':{useDisplayDensity:()=>({screenGap:16,sectionGap:12,tripGap:8})}};
  for(const name of ['./JourneyBriefPanel','./TripsScreen','../components/ExistingTripChangePanel','../components/AssistantFinanceQueryPanel','../components/PhotoJourneySuggestions'])mocks[name]={__esModule:true,default:'UnusedPanel'};
  const globals={document,window,navigator,setTimeout:fn=>{const id=++serial;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id),setInterval:fn=>{const id=++serial;timers.set(id,fn);return id;},clearInterval:id=>timers.delete(id)};
  const ui=loader(mocks,globals),Component=options.screen==='photos'?ui(resolve(root,'screens/PhotosScreen.tsx')).default:options.screen==='documents'?ui(resolve(root,'screens/JourneyDocumentsPanel.tsx')).default:ui(resolve(root,'screens/AssistantScreen.tsx')).AssistantScreen;
  const props={user:household.user,state:{people:[household.user]},onNavigate(){},onInventory(){},...(options.screen==='documents'?{onBack:()=>{f.back=true;}}:{})};
  function expand(node,path='root',seen=new Set()) {
    if(!node||typeof node!=='object')return node;if(Array.isArray(node))return node.map((n,i)=>expand(n,path+'.'+i,seen));
    if(typeof node.type==='function'){
      if(!types.has(node.type))types.set(node.type,types.size+1);const key=path+':'+types.get(node.type)+':'+(node.props.key??'');seen.add(key);
      if(!instances.has(key))instances.set(key,{values:[],cleanups:[],dead:false});holder=instances.get(key);cursor=0;
      return expand(node.type(node.props),key,seen);
    }
    return{...node,props:{...node.props,action:expand(node.props.action,path+'.action',seen),children:node.props.children.map((n,i)=>expand(n,path+'.'+(n?.props?.key??i),seen))}};
  }
  function render(){dirty=false;const seen=new Set();tree=expand(react.createElement(Component,props),'root',seen);for(const [key,h]of instances)if(!seen.has(key)){h.dead=true;h.cleanups.forEach(fn=>fn?.());instances.delete(key);}while(effects.length)effects.shift()();}
  async function flush(){for(let i=0;i<50;i++){if(dirty&&!closed)render();await new Promise(setImmediate);}assert(!dirty||closed,'render did not settle');}
  const hidden=n=>n?.props?.visible===false||n?.props?.style?.display==='none';
  function nodes(n=tree){if(!n||typeof n!=='object'||hidden(n))return[];if(Array.isArray(n))return n.flatMap(v=>nodes(v??null));return[n,...nodes(n.props.action??null),...n.props.children.flatMap(v=>nodes(v??null))];}
  function text(n=tree){if(typeof n==='string'||typeof n==='number')return String(n);if(!n||typeof n!=='object'||hidden(n))return'';return[n.props.title||'',n.props.description||'',...n.props.children.map(v=>text(v??null)),text(n.props.action??null)].join(' ');}
  const control=label=>nodes().filter(n=>(n.props.accessibilityLabel||n.props.label||text(n).trim().replace(/\s+/g,' '))===label&&(n.props.onPress||n.props.onChangeText));
  async function click(label){const found=control(label);assert.equal(found.length,1,label+'\n'+text());assert(!found[0].props.disabled,label+' disabled');found[0].props.onPress();await flush();}
  async function input(label,value){const found=control(label);assert.equal(found.length,1,label);assert(!found[0].props.disabled);found[0].props.onChangeText(value);await flush();}
  return{f,flush,click,input,nodes,text,control,household,props,
    async search(){await flush();await input('告诉助理你的需求','搜索：凭证');await click('整理并预览');},
    async emit(event){for(const fn of [...(listeners.get(event)||[])])fn({});await flush();},
    async offline(){navigator.onLine=false;household.online=false;for(const fn of [...(listeners.get('offline')||[])])fn({});dirty=true;await flush();},
    async online(){navigator.onLine=true;household.online=true;for(const fn of [...(listeners.get('online')||[])])fn({});dirty=true;await flush();},
    async switchMember(){f.session={user:{...f.session.user,id:'bob',name:'合成伙伴'},csrf:'new-csrf'};household.user=clone(f.session.user);household.identityKey=identity.sessionIdentity(f.session);props.user=household.user;props.state.people=[household.user];dirty=true;await flush();},
    close(){closed=true;for(const h of instances.values()){h.dead=true;h.cleanups.forEach(fn=>fn?.());}}};
}

test('real assistant page two opens current document metadata and returns to the same prompt/query/page',async t=>{
  const matches=Array.from({length:21},(_,i)=>docMatch({id:i===20?documentId:(i+1).toString(16).padStart(32,'0'),title:i===20?'第21份凭证':'凭证'+i}));
  const h=harness({matches});t.after(h.close);await h.search();await h.click('下一页');await h.click('查看资料 第21份凭证');
  assert(h.text().includes('当前资料标题'));assert(h.text().includes('current.pdf'));assert(!h.text().includes('old.pdf'));
  assert(h.f.calls.includes('/journey-documents?journeyId='+journeyId));assert(!h.f.calls.some(p=>p.endsWith('/file')));
  await h.click('返回资料搜索');assert.equal(h.control('告诉助理你的需求')[0].props.value,'搜索：凭证');assert.match(h.text(),/第\s+2\s+页/);
  assert.equal(h.f.calls.filter(p=>p==='/assistant/search?q=%E5%87%AD%E8%AF%81&limit=20&offset=20').length,2);assert.equal(h.f.mutations.length,1);
});
test('journey-null document search opens the freshly authorized personal library without implicit downloads',async t=>{
  const h=harness({matches:[docMatch({journey:null})],documents:[record({journeyId:null,unlinked:true})]});t.after(h.close);await h.search();await h.click('查看资料 旧资料标题');
  assert(h.f.calls.includes('/journey-documents'));assert(!h.f.calls.some(p=>p.startsWith('/journey-documents?')));assert(h.text().includes('当前资料标题'));assert(h.text().includes('未关联旅行'));assert(!h.f.calls.some(p=>p.endsWith('/file')));
});
test('partner shared document opens only currently authorized details without management or automatic file reads',async t=>{
  const h=harness({matches:[docMatch({visibility:'shared'})],documents:[record({owner:'bob',canManage:false,visibility:'shared'})]});t.after(h.close);await h.search();await h.click('查看资料 旧资料标题');
  assert(h.text().includes('伙伴共享，只可下载'));assert.equal(h.control('编辑资料').length,0);assert.equal(h.control('删除这份资料').length,0);assert.equal(h.control('下载资料').length,1);assert(!h.f.calls.some(p=>p.endsWith('/file')));
});
test('deleted original journey cannot redirect a targeted search hit into the personal orphan library',async t=>{
  const h=harness({scopedDocumentStatus:404,documents:[record({journeyId:null,unlinked:true})]});t.after(h.close);await h.search();await h.click('查看资料 旧资料标题');
  assert(h.text().includes('这份资料已移出原搜索范围'));assert(!h.f.calls.includes('/journey-documents'));
  assert(!h.nodes().some(n=>n.props.testID==='journey-document-detail'));assert.equal(h.control('下载资料').length,0);
  h.f.matches=[docMatch({journey:null})];await h.click('返回资料搜索');await h.click('查看资料 旧资料标题');
  assert(h.f.calls.includes('/journey-documents'));assert(h.text().includes('当前资料标题'));assert(h.text().includes('未关联旅行'));
});
test('standalone journey documents keep the existing personal-library recovery after original journey 404',async t=>{
  const h=harness({screen:'documents',scopedDocumentStatus:404,documents:[record({journeyId:null,unlinked:true})]});t.after(h.close);h.props.journeyId=journeyId;await h.flush();
  assert(h.f.calls.includes('/journey-documents?journeyId='+journeyId));assert(h.f.calls.includes('/journey-documents'));
  assert(h.text().includes('原旅行当前不可用，已读取你的资料库'));assert.equal(h.control('查看资料：当前资料标题').length,1);
});
for(const option of [{documents:[]},{documentStatus:403}])test('removed/revoked document target fails explicitly and can return to search '+JSON.stringify(option),async t=>{
  const h=harness(option);t.after(h.close);await h.search();await h.click('查看资料 旧资料标题');
  assert(!h.text().includes('当前资料标题'));assert.match(h.text(),/已移除|权限需要重新核对/);assert(!h.nodes().some(n=>n.props.testID==='journey-document-detail'));
  h.f.documents=[];h.f.matches=[];h.f.documentStatus=0;await h.click('返回资料搜索');assert(h.text().includes('没有找到当前可见的匹配记录'));
});
test('real photo entry re-reads the original item through PhotoReadFence and returns to original search',async t=>{
  const h=harness({matches:[photoMatch()]});t.after(h.close);await h.search();await h.click('查看照片 旧照片说明');
  assert.equal(h.control('照片说明')[0].props.value,'当前照片说明');assert(h.f.calls.includes('/media/items/'+photoId));
  assert(h.nodes().some(n=>n.type==='Image'&&n.props.source?.uri==='/api/media/items/'+photoId+'/preview'));
  // Header return is disabled while details are open; the dialog action is the
  // enabled return and keeps the same confirmation path for edited photos.
  const back=h.control('返回搜索').filter(n=>!n.props.disabled);assert.equal(back.length,1);back[0].props.onPress();await h.flush();
  assert(h.text().includes('搜索结果'));assert.equal(h.control('告诉助理你的需求')[0].props.value,'搜索：凭证');assert.equal(h.f.mutations.length,1);
});
test('photo edits require explicit discard before returning and search never grants sharing',async t=>{
  const h=harness({matches:[photoMatch()]});t.after(h.close);await h.search();await h.click('查看照片 旧照片说明');await h.input('照片说明','本人未保存文字');
  h.control('返回搜索').find(n=>!n.props.disabled).props.onPress();await h.flush();assert(h.text().includes('未保存的输入将丢弃'));assert.equal(h.control('照片说明')[0].props.value,'本人未保存文字');
  await h.click('确认');assert(h.text().includes('搜索结果'));assert.equal(h.f.mutations.length,1);
});
for(const option of [{photoStatus:404},{failMeAfterPhoto:true}])test('missing photo or final identity read failure cannot install a search snapshot '+JSON.stringify(option),async t=>{
  const h=harness({matches:[photoMatch()],...option});t.after(h.close);await h.search();await h.click('查看照片 旧照片说明');
  assert(!h.nodes().some(n=>n.type==='Image'));assert.equal(h.control('照片说明').length,0);assert.match(h.text(),/已移除|无法核对当前登录/);assert.equal(h.f.mutations.length,1);
});
test('photo detail response with another valid ID cannot replace the original search target',async t=>{
  const other='b'.repeat(24),h=harness({matches:[photoMatch()],photo:photo({id:other,previewUrl:'/api/media/items/'+other+'/preview'})});t.after(h.close);await h.search();await h.click('查看照片 旧照片说明');
  assert.match(h.text(),/与所选内容不一致/);assert(!h.nodes().some(n=>n.type==='Image'));assert.equal(h.control('照片说明').length,0);
});
test('photo is concealed offline and a revoked target is re-read before anything can reappear',async t=>{
  const h=harness({matches:[photoMatch()]});t.after(h.close);await h.search();await h.click('查看照片 旧照片说明');assert.equal(h.control('照片说明').length,1);
  await h.offline();assert(!h.nodes().some(n=>n.type==='Image'));assert.equal(h.control('照片说明').length,0);
  h.f.photoStatus=404;h.f.matches=[];await h.online();assert(h.text().includes('照片已移除或不再可见'));assert(!h.nodes().some(n=>n.type==='Image'));
  await h.click('返回搜索');assert(h.text().includes('没有找到当前可见的匹配记录'));assert.equal(h.f.mutations.length,1);
});
for(const screen of ['photos','documents'])test('optional search entry leaves standalone '+screen+' page at its original list',async t=>{
  const h=harness({screen});t.after(h.close);await h.flush();
  assert.equal(h.control('返回搜索').length,0);assert(!h.nodes().some(n=>n.props.testID==='journey-document-detail'));assert.equal(h.control('照片说明').length,0);assert(!h.f.calls.includes('/media/items/'+photoId));assert.equal(h.f.mutations.length,0);
});
for(const kind of ['documents','media'])test('late '+kind+' content after household member switch cannot reappear',async t=>{
  const wait=deferred(),path=kind==='documents'?'/journey-documents?journeyId='+journeyId:'/media/items/'+photoId;
  const h=harness({matches:[kind==='documents'?docMatch():photoMatch()],gate:{path,promise:wait.promise}});t.after(h.close);await h.search();await h.click(kind==='documents'?'查看资料 旧资料标题':'查看照片 旧照片说明');assert(h.f.calls.includes(path));
  h.f.matches=[];await h.switchMember();wait.release();await h.flush();
  assert(!h.text().includes('当前资料标题'));assert.equal(h.control('照片说明').length,0);assert(!h.nodes().some(n=>n.type==='Image'));assert.equal(h.control('告诉助理你的需求')[0].props.value,'');
});
test('late assistant search after member switch cannot restore old document results or counts',async t=>{
  const wait=deferred(),path='/assistant/search?q=%E5%87%AD%E8%AF%81&limit=20&offset=20';
  const h=harness({matches:Array.from({length:21},(_,i)=>docMatch({id:(i+1).toString(16).padStart(32,'0')})),gate:{path,promise:wait.promise}});t.after(h.close);await h.search();await h.click('下一页');
  h.f.matches=[];await h.switchMember();wait.release();await h.flush();assert(!h.text().includes('旧资料标题'));assert(!h.text().includes('搜索结果'));
});
