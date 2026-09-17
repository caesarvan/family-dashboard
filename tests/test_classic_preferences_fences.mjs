import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Execute the actual classic module with a small DOM adapter. No copied fence or save logic.
const source=fs.readFileSync(new URL('../static/product-shell.js',import.meta.url),'utf8');
const fixture={theme:'forest',density:'comfortable',homeView:'today',colorMode:'dark',revision:0};
const settle=async()=>{for(let n=0;n<8;n++)await new Promise(resolve=>setImmediate(resolve));};
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
class Element {
  constructor(){this.children=[];this.listeners=new Map();this.style={};this.dataset={};this.isConnected=true;this.hidden=false;this.disabled=false;this.value='';this._text='';}
  set textContent(value){this._text=value;this.children=[];}
  get textContent(){return this._text;}
  setAttribute(){}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  addEventListener(type,listener){if(!this.listeners.has(type))this.listeners.set(type,new Set());this.listeners.get(type).add(listener);}
  removeEventListener(type,listener){this.listeners.get(type)?.delete(listener);}
  emit(type,event={}){for(const fn of [...(this.listeners.get(type)||[])])fn(event);}
}
function createForm(){
  const form=new Element(),button=new Element(),error=new Element(),footer=new Element();
  form.elements={density:new Element(),homeView:new Element()};
  form.radios=['forest','light','ocean'].map(value=>{const radio=new Element();radio.value=value;Object.defineProperty(radio,'checked',{get(){return form.theme===value;},set(checked){if(checked)form.theme=value;}});return radio;});
  form.theme='forest';form.elements.density.value='comfortable';form.elements.homeView.value='today';
  form.querySelector=selector=>{
    if(selector==='[type=submit]')return button;
    if(selector==='.error')return error;
    if(selector==='.dialog-footer')return footer;
    if(selector==='[name=theme]:checked')return form.radios.find(item=>item.checked);
    const match=selector.match(/^\[name=theme\]\[value=(\w+)\]$/);if(match)return form.radios.find(item=>item.value===match[1]);
    throw new Error(`Unexpected form query: ${selector}`);
  };
  form.querySelectorAll=selector=>{assert.equal(selector,'input,select');return [...form.radios,...Object.values(form.elements)];};
  form.insertBefore=node=>{form.recovery=node;};form.before=node=>{form.standby=node;};
  form.button=button;form.error=error;return form;
}
function harness(){
  const document=new Element(),window=new Element(),dialog=new Element();document.hidden=false;document.documentElement={dataset:{}};dialog.open=false;
  let form=null,bootCalls=0,current={...fixture};const calls=[];
  document.querySelector=selector=>selector==='#dialog'?dialog:selector==='#ps-preferences-form'?(form?.isConnected?form:null):null;
  document.createElement=()=>new Element();
  const ctx={window,document,navigator:{onLine:true},AbortController,setTimeout,clearTimeout,setInterval:()=>0,
    user:{role:'member',householdId:'house-a',id:'member-a',auth_version:1},csrf:'csrf-a',isTV:false,isDemo:false,data:null,
    location:{hash:''},renderBoard(){},renderLogin(){},canEdit:()=>true,toast(){},
    openModal(){if(form)form.isConnected=false;form=createForm();dialog.open=true;},
    closeModal(){dialog.open=false;dialog.emit('close');},boot(){bootCalls++;},
  };
  dialog.replaceChildren=()=>{if(form)form.isConnected=false;};
  const me=()=>({user:{...ctx.user},csrf:ctx.csrf});
  let transport=async(path,options)=>{
    if(path==='/me')return me();
    if(path==='/preferences'&&options.method==='PUT'){const body=JSON.parse(options.body);current={...current,...body.changes,revision:current.revision+1};return {...current};}
    if(path==='/preferences')return {...current};
    throw new Error(`Unexpected API: ${path}`);
  };
  ctx.api=(path,options={})=>{calls.push({path,...options});return transport(path,options);};
  vm.createContext(ctx);
  vm.runInContext(source.replace('  root.ProductShell=', '  root.__test={fetchPreferences,preferencesRequest,mapActor,getEpoch:()=>preferencesEpoch,prime:()=>{prefIdentity=mapActor();}};\n  root.ProductShell='),ctx,{filename:'static/product-shell.js'});
  window.__test.prime();
  return {ctx,window,document,dialog,calls,me,get form(){return form;},get bootCalls(){return bootCalls;},
    get current(){return current;},set current(value){current={...value};},set transport(value){transport=value;},
    async open(){window.ProductShell.openPreferences();await settle();},
    hidden(value){document.hidden=value;document.emit('visibilitychange');},
    offline(value){ctx.navigator.onLine=!value;window.emit(value?'offline':'online');},
    async submit(){await form.onsubmit({preventDefault(){}});await settle();},
    change(key,value){if(key==='theme')form.theme=value;else form.elements[key].value=value;form.emit('change');},
    click(label){const control=form.recovery.children.find(node=>node.textContent===label);assert.ok(control,`Missing ${label}`);control.onclick();},
    puts(){return calls.filter(call=>call.method==='PUT');},
  };
}

test('hidden aborts the actual preferences transport and ignores even an unabortable late response',async()=>{
  const h=harness(),late=deferred();h.transport=()=>late.promise;
  const request=h.window.__test.preferencesRequest('/preferences');const outcome=assert.rejects(request,error=>error.preferencesDiscarded===true);
  h.hidden(true);assert.equal(h.calls[0].signal.aborted,true);h.transport=async path=>path==='/me'?h.me():fixture;h.hidden(false);late.resolve(fixture);await outcome;
  assert.equal(h.bootCalls,0);
});
test('form remains concealed until fresh identity is checked after the GET',async()=>{
  const h=harness(),after=deferred();let count=0;
  h.transport=async path=>path==='/me'?(++count===2?after.promise:h.me()):fixture;
  await h.open();assert.equal(h.form.hidden,true);assert.equal(h.form.button.disabled,true);
  after.resolve(h.me());await settle();assert.equal(h.form.hidden,false);assert.equal(h.form.button.disabled,false);
});
test('same-identity offline and background retain the draft and only resume through fresh GETs',async()=>{
  const h=harness();await h.open();h.change('density','compact');
  h.offline(true);assert.equal(h.form.hidden,true);assert.equal(h.form.style.display,'none');
  h.offline(false);await settle();assert.equal(h.form.hidden,false);assert.equal(h.form.elements.density.value,'compact');
  h.hidden(true);h.hidden(false);await settle();assert.equal(h.form.elements.density.value,'compact');assert.equal(h.puts().length,0);
  assert.deepEqual(h.calls.filter(call=>call.path!=='/dashboard-layout').slice(-3).map(call=>call.path),['/me','/preferences','/me']);
});
test('changed revision after resume requires explicit comparison and rebases only edited fields',async()=>{
  const h=harness();await h.open();h.change('density','compact');h.hidden(true);
  h.current={...fixture,homeView:'week',revision:1};h.hidden(false);await settle();assert.equal(h.form.button.disabled,true);
  h.click('保留我的草稿');assert.equal(h.form.elements.density.value,'compact');assert.equal(h.form.elements.homeView.value,'week');assert.equal(h.puts().length,0);
  await h.submit();assert.deepEqual(JSON.parse(h.puts()[0].body),{revision:1,changes:{density:'compact'}});assert.equal(h.current.colorMode,'dark');
});
test('old finally cannot release the new resume read busy state',async()=>{
  const h=harness(),old=deferred(),fresh=deferred();let phase='old';
  h.transport=async path=>path==='/me'?(phase==='fresh'?fresh.promise:h.me()):old.promise;
  await h.open();h.hidden(true);phase='fresh';h.hidden(false);old.resolve(fixture);await settle();
  assert.equal(h.form.hidden,true);assert.equal(h.form.button.disabled,true);assert.equal(h.form.standby.textContent,'正在核对本人外观');
  h.transport=async path=>path==='/me'?h.me():fixture;fresh.resolve(h.me());await settle();assert.equal(h.form.hidden,false);assert.equal(h.form.button.disabled,false);
});
test('stale 401 after suspend cannot invalidate the current editor or start authentication',async()=>{
  const h=harness(),old=deferred();h.transport=()=>old.promise;await h.open();h.hidden(true);
  h.transport=async path=>path==='/me'?h.me():fixture;h.hidden(false);await settle();
  old.reject(Object.assign(new Error('stale denied'),{status:401}));await settle();assert.equal(h.bootCalls,0);assert.equal(h.dialog.open,true);assert.equal(h.form.hidden,false);
});
test('fresh identity mismatch after resume clears the old form instead of restoring its draft',async()=>{
  const h=harness();await h.open();h.change('theme','ocean');h.hidden(true);
  h.transport=async()=>({user:{...h.ctx.user,id:'member-b'},csrf:'csrf-b'});h.hidden(false);await settle();
  assert.equal(h.dialog.open,false);assert.equal(h.form.isConnected,false);assert.equal(h.bootCalls,1);assert.equal(h.puts().length,0);
});
test('a sent PUT remains uncertain across suspend; resume and explicit adoption never replay it',async()=>{
  const h=harness(),lost=deferred();await h.open();h.change('density','compact');
  h.transport=async(path,options)=>{
    if(path==='/me')return h.me();
    if(options.method==='PUT'){h.current={...fixture,density:'compact',revision:1};return lost.promise;}
    return h.current;
  };
  const pending=h.form.onsubmit({preventDefault(){}});await settle();assert.equal(h.puts().length,1);
  h.hidden(true);h.hidden(false);await settle();assert.equal(h.form.button.disabled,true);
  h.click('使用已保存设置');assert.equal(h.form.elements.density.value,'compact');assert.equal(h.form.button.disabled,false);
  lost.resolve({...h.current});await pending;assert.equal(h.puts().length,1);assert.equal(h.dialog.open,true);
});
test('failed preflight preserves editable draft without creating an uncertain PUT',async()=>{
  const h=harness();await h.open();h.change('homeView','around');h.transport=async()=>{throw new Error('offline before PUT');};
  await h.submit();assert.equal(h.puts().length,0);assert.equal(h.form.button.disabled,false);assert.equal(h.form.elements.homeView.value,'around');
  assert.equal(h.form.recovery.children.length,0);
});
test('closing then opening a new form discards a late identity error from the old editor',async()=>{
  const h=harness(),old=deferred();h.transport=()=>old.promise;await h.open();h.ctx.closeModal();
  h.transport=async path=>path==='/me'?h.me():fixture;await h.open();const newForm=h.form;
  old.reject(Object.assign(new Error('old forbidden'),{status:403}));await settle();
  assert.equal(h.form,newForm);assert.equal(newForm.hidden,false);assert.equal(h.bootCalls,0);
});
test('pagehide conceals retained draft; ordinary initial pageshow cannot cancel a current load',async()=>{
  const h=harness(),initial=deferred();h.transport=()=>initial.promise;await h.open();const signal=h.calls[0].signal;
  h.window.emit('pageshow',{persisted:false});assert.equal(signal.aborted,false);
  h.transport=async path=>path==='/me'?h.me():fixture;initial.resolve(h.me());await settle();h.change('theme','ocean');
  h.window.emit('pagehide');assert.equal(h.form.hidden,true);h.window.emit('pageshow',{persisted:true});await settle();assert.equal(h.form.hidden,false);assert.equal(h.form.theme,'ocean');
});
