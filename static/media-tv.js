/* Photo-only display. Every visible image requires a current short server lease. */
(() => {
  'use strict';
  const ID=/^[0-9a-f]{24}$/;
  const identity=()=>({user:typeof user==='undefined'?null:user,csrf:typeof csrf==='undefined'?'':csrf,
    isTV:typeof isTV==='undefined'?false:isTV,isDemo:typeof isDemo==='undefined'?false:isDemo});
  const key=value=>JSON.stringify([value.user?.role,value.user?.householdId,value.user?.id,value.user?.auth_version,value.csrf]);
  const member=value=>value.user?.role==='member'&&!value.isTV&&!value.isDemo;
  const television=value=>value.user?.role==='tv'&&value.isTV&&!value.isDemo;
  let display=null;
  const controls=new Set();

  async function json(path,{method='GET',payload,csrf='',tv=false,signal}={}) {
    const response=await fetch(path,{method,credentials:'same-origin',cache:'no-store',redirect:'error',signal,
      headers:{'Content-Type':'application/json',...(csrf?{'X-CSRF-Token':csrf}:{}),...(tv?{'X-Display-Mode':'tv'}:{})},
      ...(payload?{body:JSON.stringify(payload)}:{})});
    if(!response.ok){const error=new Error('request_failed');error.status=response.status;throw error;}
    return response.json();
  }
  function validState(value,id) {
    return value&&value.deviceId===id&&Number.isSafeInteger(value.revision)&&value.revision>=0
      &&['dashboard','photos'].includes(value.mode)&&typeof value.paused==='boolean'
      &&Number.isInteger(value.intervalSeconds)&&value.intervalSeconds>=5&&value.intervalSeconds<=120
      &&Number.isInteger(value.photoCount)&&value.photoCount>=0&&value.photoCount<=2000
      &&Number.isInteger(value.position)&&value.position>=0&&(value.photoCount===0||value.position<value.photoCount);
  }

  function mountControls(node,deviceId,context={}) {
    if(!node||!ID.test(deviceId))return ()=>{};
    const getIdentity=context.getIdentity||identity, first=getIdentity(), initial=key(first);
    if(!member(first)){node.replaceChildren();return ()=>{};}
    const state={node,disposed:false,busy:false,value:null,controller:null};
    controls.add(state);
    node.classList.add('media-tv-controls');
    node.innerHTML='<h3>这台电视的照片</h3><p>只播放已明确授权给这台电视的照片。开始播放不会新增共享或电视许可。</p>'+
      '<div class="media-tv-actions"><button type="button" data-playback="start">开始照片</button><button type="button" data-playback="dashboard">回到看板</button>'+
      '<button type="button" data-playback="pause">暂停</button><button type="button" data-playback="resume">继续</button>'+
      '<button type="button" data-playback="previous">上一张</button><button type="button" data-playback="next">下一张</button></div>'+
      '<label class="media-tv-interval">每张停留 <select aria-label="照片轮播间隔">'+[5,10,15,30,60,120].map(n=>`<option value="${n}">${n} 秒</option>`).join('')+'</select>'+
      '<button type="button" data-playback="interval">应用间隔</button></label><button type="button" data-playback="refresh">刷新播放状态</button><p role="status" aria-live="polite" data-playback-status>正在核对这台电视…</p>';
    const status=node.querySelector('[data-playback-status]');
    const active=()=>!state.disposed&&node.isConnected&&member(getIdentity())&&key(getIdentity())===initial;
    function dispose(neutral=false) {
      if(state.disposed)return;
      state.disposed=true;state.controller?.abort();clearInterval(state.watch);controls.delete(state);state.value=null;
      if(neutral)node.textContent='登录或家庭已变化，请重新打开电视设置。';
    }
    state.dispose=()=>dispose(true);
    function paint(message='') {
      if(!active()){dispose(true);return;}
      const value=state.value;
      for(const button of node.querySelectorAll('button')) {
        const action=button.dataset.playback;
        button.disabled=state.busy||(action!=='refresh'&&!value)
          ||(action==='start'&&value?.photoCount===0)
          ||(['pause','resume','previous','next'].includes(action)&&value?.mode!=='photos')
          ||(['previous','next'].includes(action)&&value?.photoCount===0)
          ||(action==='pause'&&value?.paused)||(action==='resume'&&value&&!value.paused);
      }
      if(value)node.querySelector('select').value=String(value.intervalSeconds);
      status.textContent=message||(value?`${value.photoCount} 张已授权照片 · ${value.mode==='dashboard'?'正在显示看板':value.paused?'照片已暂停':'照片轮播中'}${value.photoCount?' · 第 '+(value.position+1)+' 张':''}`:'暂时无法读取播放状态。');
    }
    async function verify(signal) {
      if(!active())throw new Error('identity_changed');
      const me=await json('/api/me',{signal});
      if(!active()||key({user:me.user,csrf:me.csrf||''})!==initial)throw new Error('identity_changed');
    }
    async function run(action='refresh') {
      if(state.busy||!active())return;
      state.busy=true;state.controller=new AbortController();
      const signal=state.controller.signal, timer=setTimeout(()=>state.controller?.abort(),7000);
      let sent=false;
      const interval=Number(node.querySelector('select').value);
      paint();
      try {
        await verify(signal);
        if(action!=='refresh') {
          if(!state.value)throw new Error('no_revision');
          sent=true;
          await json('/api/media-playback/devices/'+deviceId,{method:'PUT',csrf:first.csrf,signal,
            payload:{revision:state.value.revision,action,...(action==='interval'?{intervalSeconds:interval}:{})}});
        }
        const value=await json('/api/media-playback/devices/'+deviceId,{signal});
        await verify(signal);
        if(!validState(value,deviceId))throw new Error('invalid_response');
        state.value=value;
        paint(action==='refresh'?'':'电视播放指令已保存；屏幕会在下一次刷新时采用。');
      } catch(error) {
        if(!active()||error.message==='identity_changed'||error.status===401){dispose(true);return;}
        state.value=null;
        paint(error.status===409?'另一成员已更新播放状态。请刷新后再选择操作。':sent?
          '指令结果尚未确认；请刷新播放状态核对，不会自动重发。':'暂时无法连接或设备已撤销，请刷新核对。');
      } finally {
        clearTimeout(timer);state.busy=false;
        if(active()) {const message=status.textContent;paint(message);}
      }
    }
    node.addEventListener('click',event=>{
      const button=event.target.closest('[data-playback]');
      if(button&&node.contains(button)&&!button.disabled)void run(button.dataset.playback);
    });
    state.watch=setInterval(()=>{if(!active())dispose(true);},250);
    void run();
    return ()=>dispose();
  }

  function clearImage(d,message='正在重新核对照片权限…') {
    d.epoch++;d.request?.abort();d.request=null;d.deadline=0;d.imageKey='';
    d.image.removeAttribute('src');d.image.hidden=true;
    if(d.url)URL.revokeObjectURL(d.url);d.url=null;
    d.message.textContent=message;
  }
  function stopDisplay() {
    if(!display)return;
    const d=display;display=null;clearImage(d);clearInterval(d.watch);d.node.remove();
    document.body.classList.remove('media-tv-playing');
  }
  function ensureDisplay() {
    const current=identity();
    if(!television(current)){stopDisplay();return;}
    if(display&&display.identity===key(current))return;
    stopDisplay();
    const node=document.createElement('section');node.className='media-tv-screen';node.hidden=true;
    node.setAttribute('aria-label','已授权照片轮播');
    node.innerHTML='<img alt="已授权的精选照片" hidden><p role="status" aria-live="polite">正在核对照片权限…</p><span class="media-tv-progress"></span>';
    document.body.append(node);
    const d=display={node,image:node.querySelector('img'),message:node.querySelector('p'),progress:node.querySelector('span'),
      identity:key(current),deviceId:current.user.id,epoch:0,deadline:0,url:null,imageKey:'',busy:false,next:0,request:null};
    const active=()=>display===d&&television(identity())&&key(identity())===d.identity&&!document.hidden;
    async function poll() {
      if(d.busy||!active()||navigator.onLine===false)return;
      d.busy=true;const epoch=d.epoch,started=performance.now();
      d.request=new AbortController();const requestController=d.request;
      const timer=setTimeout(()=>requestController.abort(),5000);
      let pendingUrl=null;
      try {
        const value=await json('/api/media-tv/playback',{tv:true,signal:requestController.signal});
        if(!active()||epoch!==d.epoch)return;
        if(!validState(value,d.deviceId))throw new Error('invalid_state');
        const duration=Date.parse(value.validUntil)-Date.parse(value.serverTime);
        if(!Number.isFinite(duration)||duration<=0||duration>15000)throw new Error('invalid_lease');
        const deadline=started+duration;
        if(performance.now()>=deadline)throw new Error('expired');
        d.deadline=deadline;
        node.hidden=value.mode==='dashboard';document.body.classList.toggle('media-tv-playing',!node.hidden);
        if(node.hidden){clearImage(d);return;}
        d.progress.textContent=value.photoCount?`${value.position+1} / ${value.photoCount}${value.paused?' · 已暂停':''}`:'';
        const item=value.item;
        if(!item){clearImage(d,'没有可播放的已授权照片，请在手机上核对电视许可。');return;}
        if(!ID.test(item.id)||item.previewUrl!=='/api/media-tv/items/'+item.id+'/preview'||!Number.isSafeInteger(item.revision))throw new Error('invalid_item');
        const imageKey=item.id+':'+item.revision;
        if(imageKey===d.imageKey&&!d.image.hidden){d.message.textContent='';return;}
        d.image.removeAttribute('src');d.image.hidden=true;
        if(d.url)URL.revokeObjectURL(d.url);d.url=null;d.imageKey='';
        const response=await fetch(item.previewUrl,{credentials:'same-origin',cache:'no-store',redirect:'error',
          signal:requestController.signal,headers:{'X-Display-Mode':'tv'}});
        if(!response.ok||response.headers.get('Content-Type')?.split(';')[0]!=='image/jpeg')throw new Error('preview_unavailable');
        const blob=await response.blob();if(!blob.size||blob.size>2*1024*1024)throw new Error('invalid_image');
        if(!active()||epoch!==d.epoch||performance.now()>=d.deadline)return;
        pendingUrl=URL.createObjectURL(blob);const candidate=new Image();candidate.src=pendingUrl;
        await candidate.decode();
        if(!active()||epoch!==d.epoch||performance.now()>=d.deadline)return;
        d.image.src=pendingUrl;d.url=pendingUrl;pendingUrl=null;d.imageKey=imageKey;d.image.hidden=false;d.message.textContent='';
      } catch(_error) {
        if(display===d&&epoch===d.epoch)clearImage(d,'连接或照片许可暂不可用；旧照片已清除，恢复后重新核对。');
      } finally {
        if(pendingUrl)URL.revokeObjectURL(pendingUrl);
        clearTimeout(timer);d.busy=false;d.next=performance.now()+2000;
      }
    }
    d.watch=setInterval(()=>{
      if(display!==d)return;
      if(!television(identity())||key(identity())!==d.identity){stopDisplay();return;}
      if(document.hidden)return;
      if(d.deadline&&performance.now()>=d.deadline)clearImage(d,'照片许可已到期，正在重新核对。');
      if(performance.now()>=d.next)void poll();
    },100);
    void poll();
  }
  function clearForLifecycle() {if(display)clearImage(display,'画面已清除，返回后重新核对。');}
  window.addEventListener('offline',clearForLifecycle);
  window.addEventListener('pagehide',clearForLifecycle);
  document.addEventListener('visibilitychange',()=>{if(document.hidden)clearForLifecycle();else if(display)display.next=0;});
  window.addEventListener('online',()=>{if(display)display.next=0;});
  window.addEventListener('pageshow',()=>{clearForLifecycle();if(display)display.next=0;});
  window.MediaTV={mountControls,ensureDisplay,notifyIdentityChanged(){for(const c of controls)c.dispose();stopDisplay();}};
})();
