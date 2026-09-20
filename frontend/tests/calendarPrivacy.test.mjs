import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
import { calendarPrivacy, calendarPrivacyPayload, calendarVisibilityLabel } from '../src/lib/calendarPrivacy.ts';
const member={id:'member1',role:'member',name:'本人',householdId:'one',auth_version:1};
const event=(patch={})=>({id:'original-id',revision:7,title:'私人原始标题',owner:'member2',start:'2027-01-02T10:00:00+08:00',end:'2027-01-02T11:00:00+08:00',visibility:'private',createdBy:'member1',...patch});
const copy=value=>JSON.parse(JSON.stringify(value));
class ApiError extends Error { constructor(message, status, code='') { super(message); this.status=status; this.code=code; } }

// Real TSX with synthetic Paper hosts/HTTP; not browser or backend acceptance.
function editor(options = {}) {
  const ts = createRequire(import.meta.url)('typescript');
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
  const calls = [], instances = new Map(), effects = [], modules = new Map();
  let holder, cursor = 0, dirty = true, tree, dismissed = 0;
  const React = {
    createElement(type, props, ...children) { return { type, props: { ...props, children: children.flat(Infinity).filter(x => x !== false && x != null) } }; },
    Fragment: 'Fragment',
    useState(initial) { const h = holder, i = cursor++; if (!(i in h)) h[i] = typeof initial === 'function' ? initial() : initial; return [h[i], value => { h[i] = typeof value === 'function' ? value(h[i]) : value; dirty = true; }]; },
    useRef(value) { const i = cursor++; return holder[i] ||= { current: value }; },
    useEffect(fn, deps) { const i = cursor++; if (!holder[i]) { holder[i] = deps; effects.push(fn); } },
  };
  const state = { events: options.item ? [options.item] : [], tasks: [], people: [{id:'member1',name:'本人'},{id:'member2',name:'伴侣'}], sync: {} };
  const notices=[]; const household = { state, user: member, identityKey: 'session-one', online: true, stateVerified: true, focus: 'member2', refresh: async () => {}, setNotice(message) {notices.push(message);}, mutate: async (path, method, body) => {
    calls.push({ path, method, body }); if(options.mutate)return options.mutate(path,method,body); if (options.failure !== undefined) throw new ApiError(options.message || '服务器拒绝此操作', options.failure, options.code); return {};
  } };
  const paper = Object.fromEntries(['Button', 'Text', 'TextInput', 'HelperText', 'IconButton', 'Portal', 'Image', 'Icon', 'TouchableRipple'].map(name => [name, name]));
  paper.Dialog = { Title: 'DialogTitle', ScrollArea: 'DialogScroll', Actions: 'DialogActions', Content: 'DialogContent' };
  paper.List = { Accordion: 'Accordion', Icon: 'ListIcon' }; paper.Menu = { Item: 'MenuItem' }; paper.Checkbox = { Item: 'CheckboxItem' };
  paper.SegmentedButtons = 'SegmentedButtons'; paper.useTheme = () => ({ colors: {} });
  const mocks = { react: React, 'react-native': { View: 'View', Image: 'Image', ScrollView: 'ScrollView', Platform: { OS: 'web' }, StyleSheet: { create: value => value } },
    'react-native-paper': paper, 'expo-image-picker': {}, 'expo-image-manipulator': {}, '../lib/household': { useHousehold: () => household }, '../lib/api': { ApiError } };
  function load(file) {
    if (!existsSync(file)) file += existsSync(file + '.ts') ? '.ts' : '.tsx';
    if (modules.has(file)) return modules.get(file);
    const exports = {}; modules.set(file, exports);
    const code = ts.transpileModule(readFileSync(file, 'utf8'), { fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
    runInNewContext(code, { exports, require: name => mocks[name] || load(resolve(dirname(file), name)), Date, Intl, Error }); return exports;
  }
  const ItemEditor = load(resolve(root, 'ui/ItemEditor.tsx')).default;
  function expand(node, path = 'root') {
    if (node == null || node === false || typeof node !== 'object') return node;
    if (Array.isArray(node)) return node.map((child, i) => expand(child, path + i));
    if (typeof node.type === 'function') {
      const key = path + node.type.name; if (!instances.has(key)) instances.set(key, []);
      const previous = holder, old = cursor; holder = instances.get(key); cursor = 0;
      const result = node.type(node.props); holder = previous; cursor = old; return expand(result, key);
    }
    return { ...node, props: { ...node.props, anchor: expand(node.props.anchor, path + '.anchor'), children: node.props.children.map((child, i) => expand(child, path + '.' + (child?.props?.key ?? i))) } };
  }
  async function flush() { for (let i = 0; i < 12; i++) { if (dirty) { dirty = false; tree = expand(React.createElement(ItemEditor, { kind: 'events', item: options.item, onDismiss() { dismissed++; } })); while (effects.length) effects.shift()(); } await new Promise(setImmediate); } assert(!dirty); }
  const nodes = node => !node || typeof node !== 'object' ? [] : Array.isArray(node) ? node.flatMap(nodes) : [node, ...nodes(node.props.anchor), ...nodes(node.props.children)];
  const text = node => node == null || node === false ? '' : typeof node !== 'object' ? String(node) : Array.isArray(node) ? node.map(text).join(' ') : text(node.props.children);
  function find(label) { const found = nodes(tree).filter(node => (node.props.accessibilityLabel || node.props.label || text(node.props.children)) === label && (node.props.onPress || node.props.onChangeText)); assert.equal(found.length, 1, label); return found[0].props; }
  return { flush, calls, find, text: () => text(tree), state, household, notices, nodes:()=>nodes(tree), update(patch) {Object.assign(household,patch);dirty=true;}, force(){dirty=true;}, dismissed: () => dismissed,
    async click(label) { const control = find(label); assert(!control.disabled, label); control.onPress(); await flush(); },
    async input(label, value) { const control = find(label); assert(!control.disabled, label); control.onChangeText(value); await flush(); } };
}

test('new defaults private; owner/focus are never access control; legacy and managed remain shared',()=>{
  assert.equal(calendarPrivacy(undefined,member).visibility,'private');
  assert.equal(calendarPrivacy(event(),member).canChange,true);
  assert.equal(calendarPrivacy(event(),{...member,id:'member2'}).canChange,false);
  assert.equal(calendarPrivacy(event({journeyId:'manual-link'}),member).canChange,true);
  for(const patch of [{},{sync:{provider:'google'}},{journeyId:'journey'},{travelTiming:{}}]){
    const value=event({visibility:undefined,createdBy:undefined,...patch});
    assert.equal(calendarPrivacy(value,member).visibility,'shared');
    assert.equal(calendarPrivacy(value,member).canChange,false);
    assert.deepEqual(calendarPrivacyPayload(value,member,'shared'),{});
  }
  assert.equal(calendarPrivacy(event({sync:{}}),member).canChange,false);
});
test('only creator can send a scope; createdBy never enters writes; malformed scope fails closed',()=>{
  assert.deepEqual(calendarPrivacyPayload(undefined,member,'private'),{visibility:'private'});
  assert.deepEqual(calendarPrivacyPayload(event(),member,'shared'),{visibility:'shared'});
  assert.deepEqual(calendarPrivacyPayload(event({visibility:'shared'}),{...member,id:'member2'},'shared'),{});
  assert.throws(()=>calendarPrivacyPayload(event({visibility:'shared'}),{...member,id:'member2'},'private'));
  assert.throws(()=>calendarPrivacyPayload(undefined,{...member,role:'tv'},'private'));
  for(const patch of [{visibility:'unknown'},{createdBy:''},{createdBy:42},{createdBy:[]},{visibility:undefined}]){
    assert.equal(calendarVisibilityLabel(event(patch)),'可见范围待核对');
    assert.throws(()=>calendarPrivacyPayload(event(patch),member,'private'));
  }
});
test('real editor creates private with current member as owner even when focused on partner',async()=>{
  const h=editor();await h.flush();await h.input('名称','新安排');
  assert.equal(h.find('日程可见范围：仅自己')['aria-checked'],true);
  await h.click('保存');const b=h.calls[0].body;
  assert.equal(h.calls[0].method,'POST');assert.equal(b.owner,'member1');assert.equal(b.visibility,'private');assert(!('createdBy' in b));
});
test('changing responsible member or choosing together never changes explicit visibility',async()=>{
  for(const owner of ['member2','shared']){
    const h=editor();await h.flush();await h.input('名称','分配负责人');
    const control=h.nodes().find(n=>n.type==='SegmentedButtons');assert(control);control.props.onValueChange(owner);await h.flush();
    assert.equal(h.find('日程可见范围：仅自己')['aria-checked'],true);await h.click('保存');
    assert.equal(h.calls[0].body.owner,owner);assert.equal(h.calls[0].body.visibility,'private');
  }
});
test('real creator editor explicitly shares original ID/revision and can later make private',async()=>{
  for(const [before,label,wanted] of [['private','家庭共享','shared'],['shared','仅自己','private']]){
    const h=editor({item:event({visibility:before})});await h.flush();await h.click('日程可见范围：'+label);await h.click('保存');
    assert.equal(h.calls[0].path,'/items/events/original-id');assert.equal(h.calls[0].method,'PATCH');
    assert.equal(h.calls[0].body.revision,7);assert.equal(h.calls[0].body.visibility,wanted);assert(!('createdBy' in h.calls[0].body));
  }
});
test('collaborator and legacy editor keep shared scope without sending privacy metadata',async()=>{
  for(const item of [event({visibility:'shared',createdBy:'member2'}),event({visibility:undefined,createdBy:undefined})]){
    const h=editor({item});await h.flush();assert.match(h.text(),/家庭共享/);
    assert.equal(h.nodes().filter(n=>n.props.accessibilityLabel==='日程可见范围：仅自己').length,0);
    await h.input('名称','家庭协作修改');await h.click('保存');
    assert(!('visibility' in h.calls[0].body));assert(!('createdBy' in h.calls[0].body));assert.equal(h.calls[0].body.revision,7);
  }
});
test('revision conflict preserves unsaved title and explicit scope without automatic retry',async()=>{
  const h=editor({item:event(),failure:409});await h.flush();await h.input('名称','保留我的草稿');await h.click('日程可见范围：家庭共享');await h.click('保存');
  assert.equal(h.find('名称').value,'保留我的草稿');assert.equal(h.find('日程可见范围：家庭共享')['aria-checked'],true);
  assert.match(h.text(),/你的输入仍在/);assert.equal(h.calls.length,1);assert.equal(h.dismissed(),0);
});
for(const status of [0,503])test('unknown result '+status+' freezes scope and inputs across periodic state refresh',async()=>{
  const h=editor({item:event(),failure:status});await h.flush();await h.click('日程可见范围：家庭共享');await h.click('保存');
  h.update({state:{...h.state,events:[event({revision:8,visibility:'shared'})]}});await h.flush();
  assert.equal(h.find('名称').disabled,true);assert.equal(h.find('日程可见范围：仅自己').disabled,true);assert.equal(h.find('保存').disabled,true);
  assert.equal(h.find('日程可见范围：家庭共享')['aria-checked'],true);assert.equal(h.calls.length,1);
});
test('identity change hides title immediately, including reused member IDs in another household',async()=>{
  const h=editor({item:event()});await h.flush();const staleSave=h.find('保存').onPress;
  h.update({identityKey:'session-two',user:{...member,householdId:'two'},state:{...h.state,events:[event()]}});await h.flush();
  assert(!h.text().includes('私人原始标题'));assert.equal(h.nodes().filter(n=>n.props.label==='名称').length,0);
  await staleSave();assert.equal(h.calls.length,0);
});
test('fresh server withdrawal and hidden-ID 404 conceal details and cannot resurrect old snapshot',async()=>{
  for(const remote of [false,true]){
    const h=editor({item:event(),...(remote?{failure:404,code:'calendar_event_unavailable'}:{})});await h.flush();
    if(remote)await h.click('保存');else{h.update({state:{...h.state,events:[]}});await h.flush();}
    assert(!h.text().includes('私人原始标题'));assert.match(h.text(),/不在当前可见范围/);
    h.update({state:{...h.state,events:[event({revision:9})]}});await h.flush();
    assert.equal(h.nodes().filter(n=>n.props.label==='名称').length,0);
  }
});
test('late old-session success cannot dismiss or announce saved under a new identity',async()=>{
  let resolveWrite;const pending=new Promise(resolve=>{resolveWrite=resolve;});
  const h=editor({item:event(),mutate:()=>pending});await h.flush();await h.click('保存');
  h.update({identityKey:'other',user:{...member,id:'member2'}});await h.flush();resolveWrite({});await h.flush();
  assert.equal(h.calls.length,1);assert.equal(h.dismissed(),0);assert.deepEqual(h.notices,[]);
});
test('uncertain identity read conceals draft then restores it only for same confirmed session',async()=>{
  const h=editor({item:event()});await h.flush();await h.input('名称','留在内存的草稿');await h.click('日程可见范围：家庭共享');
  const staleSave=h.find('保存').onPress;
  h.update({stateVerified:false,online:false});await h.flush();assert.match(h.text(),/草稿暂时隐藏/);
  assert.equal(h.nodes().filter(n=>n.props.label==='名称').length,0);await staleSave();assert.equal(h.calls.length,0);
  h.update({stateVerified:true,online:true});await h.flush();assert.equal(h.find('名称').value,'留在内存的草稿');
  assert.equal(h.find('日程可见范围：家庭共享')['aria-checked'],true);
});
test('successful POST followed by failed identity refresh stays frozen after recovery',async()=>{
  const h=editor();h.household.refresh=async()=>{h.update({stateVerified:false});};
  await h.flush();await h.input('名称','已提交的安排');await h.click('保存');assert.equal(h.calls.length,1);
  assert.match(h.text(),/草稿暂时隐藏/);h.update({stateVerified:true});await h.flush();
  assert.equal(h.find('保存').disabled,true);assert.match(h.text(),/已收到保存成功响应/);assert.equal(h.calls.length,1);
});
test('root editor snapshot is bound at creation and gated before identity cleanup effects',()=>{
  const source=readFileSync(new URL('../src/screens/HouseholdApp.tsx',import.meta.url),'utf8');
  assert.match(source,/setEditor\(\{kind,item,key:Date\.now\(\),identity:actor\}\)/);
  assert.match(source,/editor&&editor\.identity===actor&&<ItemEditor/);
});

// Execute the real provider hook. Transport and preference/layout parsers are
// substitutes, isolating the /me -> /state -> /me admission lifecycle.
function provider() {
  const ts=createRequire(import.meta.url)('typescript'), file=new URL('../src/lib/household.tsx',import.meta.url);
  let slots=[],cursor=0,current,dirty=true,meQueue=[],state= {events:[event()],people:[member]},calls=[];
  const React={createContext:()=>({}),createElement:()=>null,useContext:()=>null,
    useState(initial){const i=cursor++;if(!(i in slots))slots[i]=initial;return[slots[i],value=>{slots[i]=typeof value==='function'?value(slots[i]):value;dirty=true;}];},
    useRef(value){const i=cursor++;return slots[i]||=( {current:value});},useCallback:fn=>fn,useEffect:()=>{}};
  const request=async path=>{calls.push(path);if(path==='/me'){const value=meQueue.shift();if(value instanceof Error)throw value;return await value;}
    if(path==='/state')return state;if(path==='/preferences')return{revision:1};return{revision:1,order:[],hidden:[]};};
  const mocks={'react':React,'react-native':{AppState:{currentState:'active'}},'./api':{ApiError,request},
    './homeLayout':{acceptHomeLayout:(_old,next)=>next},'./preferences':{acceptPreferences:(_old,next)=>next,readPreferences:value=>value},
    './sessionIdentity.ts':{sessionIdentity:s=>JSON.stringify([s.user?.role,s.user?.householdId,s.user?.id,s.user?.auth_version,s.csrf])}};
  const exports={};const code=ts.transpileModule(readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  runInNewContext(code+'\nexports.testHook=useHouseholdState;', {exports,require:name=>{assert(name in mocks,name);return mocks[name];},Error,AbortController});
  function render(){cursor=0;current=exports.testHook();dirty=false;return current;}
  return {ApiError,render,queue(values){meQueue=values;},get value(){if(dirty)render();return current;},calls};
}
const session={user:member,csrf:'csrf-one'};
test('provider admits private calendar only after both session reads; normal refresh does not flicker',async()=>{
  const h=provider();h.render();assert.equal(h.value.stateVerified,false);
  h.queue([session,session]);await h.value.refresh();assert.equal(h.value.stateVerified,true);
  assert.deepEqual(h.calls,['/me','/state','/preferences','/dashboard-layout','/me']);
  let release;h.queue([new Promise(resolve=>{release=resolve;}),session]);const pending=h.value.refresh();
  assert.equal(h.value.stateVerified,true);release(session);await pending;assert.equal(h.value.stateVerified,true);
});
for(const tail of [false,true])test('provider '+(tail?'tail':'first')+' identity 429 hides cached state until confirmed recovery',async()=>{
  const h=provider();h.render();h.queue([session,session]);await h.value.refresh();const snapshot=h.value.state;
  h.queue(tail?[session,new h.ApiError('synthetic read failure',429)]:[new h.ApiError('synthetic read failure',429)]);await h.value.refresh();
  assert.equal(h.value.stateVerified,false);assert.equal(h.value.state,snapshot);
  h.queue([session,session]);await h.value.refresh();assert.equal(h.value.stateVerified,true);
});
test('provider rejects second-session mismatch without installing private snapshot',async()=>{
  const h=provider();h.render();h.queue([session,session]);await h.value.refresh();
  h.queue([session,{user:{...member,householdId:'another'},csrf:'new'}]);await h.value.refresh();
  assert.equal(h.value.stateVerified,false);assert.equal(h.value.state,null);
});

for(const item of [undefined,event()])test('preflight identity 404 preserves '+(item?'existing':'new')+' draft and sends no mutation until explicit retry',async()=>{
  const p=provider();p.render();p.queue([session,session]);await p.value.refresh();
  const h=editor({item,mutate:(...args)=>p.value.mutate(...args)});
  h.update(p.value);await h.flush();await h.input('名称','身份恢复后保留草稿');await h.click('日程可见范围：家庭共享');
  const before=p.calls.length;p.queue([new ApiError('身份暂不可核验',404)]);await h.click('保存');
  assert.deepEqual(p.calls.slice(before),['/me']);assert.equal(p.value.stateVerified,false);
  h.update(p.value);await h.flush();assert.match(h.text(),/草稿暂时隐藏/);
  p.queue([session,session]);await p.value.refresh();h.update(p.value);await h.flush();
  assert.equal(h.find('名称').value,'身份恢复后保留草稿');assert.equal(h.find('日程可见范围：家庭共享')['aria-checked'],true);
  assert.equal(h.find('保存').disabled,false);assert.equal(p.calls.filter(path=>path.startsWith('/items/')).length,0);
  p.queue([session,session,session]);await h.click('保存');
  assert.deepEqual(p.calls.filter(path=>path.startsWith('/items/')),['/items/events'+(item?'/original-id':'')]);
});
