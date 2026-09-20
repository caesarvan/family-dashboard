/* Classic controls and explicit modern-TV upgrade entry; no classic media playback. */
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

  // Classic display does not implement the acknowledged media-time protocol.
  // Keep its dashboard usable and offer the same-origin modern TV entry.
  function stopDisplay() {
    if(!display)return;
    const d=display;display=null;d.request?.abort();clearInterval(d.watch);
    d.image?.removeAttribute('src');if(d.url)URL.revokeObjectURL(d.url);
    d.node.remove();document.body.classList.remove('media-tv-playing');
  }
  function ensureDisplay() {
    const current=identity();
    if(!television(current)||document.hidden){stopDisplay();return;}
    if(display&&display.identity===key(current))return;
    stopDisplay();
    const node=document.createElement('aside');node.setAttribute('aria-label','相册播放升级提示');
    node.style.cssText='position:fixed;bottom:16px;left:16px;right:16px;z-index:50;padding:12px 18px;background:#18212d;color:#fff;border-radius:12px;font-size:16px;line-height:1.5';
    node.append(document.createTextNode('经典电视页不再播放相册。照片和视频请使用新版电视页：'));
    const link=document.createElement('a');link.href='/app/tv';link.textContent='打开新版电视页';link.style.color='#9dd8ff';node.append(link);
    document.body.append(node);display={node,identity:key(current)};
  }
  window.addEventListener('offline',stopDisplay);
  window.addEventListener('pagehide',stopDisplay);
  document.addEventListener('visibilitychange',()=>document.hidden?stopDisplay():ensureDisplay());
  window.addEventListener('online',ensureDisplay);
  window.addEventListener('pageshow',ensureDisplay);
  window.MediaTV={mountControls,ensureDisplay,notifyIdentityChanged(){for(const c of controls)c.dispose();stopDisplay();}};
})();
