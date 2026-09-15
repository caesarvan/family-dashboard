/* A routing address selects a space; authentication remains separate per family. */
window.HouseholdSpaces = (() => {
  async function open() {
    const current = await api('/spaces/current');
    openModal('家庭空间', `<div class="info-box"><strong>${esc(current.name)}</strong><p>每个家庭有独立的日程、清单、财务、图片和第三方账户绑定。</p><p>本家庭入口：<a href="${esc(current.entry)}">${esc(location.origin + current.entry)}</a></p></div>
      <form id="space-switch"><label class="field"><span>前往另一个家庭</span><input name="slug" required pattern="[a-z][a-z0-9-]{2,31}" placeholder="例如 home"></label><button class="btn secondary" type="submit">进入家庭登录页</button></form>
      ${current.canInvite ? '<hr><h3>邀请新家庭体验</h3><p class="help">生成一次性邀请码，有效期 7 天。请自行交给受邀家庭；邀请码只用于创建新空间，不提供本家庭访问权。</p><button class="btn" id="space-invite">生成邀请码</button><div id="space-invite-result"></div>' : ''}
      <div class="dialog-footer"><button class="btn secondary" id="space-redeem-open">使用邀请码创建家庭</button></div>`, true);
    document.querySelector('#space-switch').onsubmit = e => {e.preventDefault(); location.href = '/space/' + encodeURIComponent(new FormData(e.currentTarget).get('slug'))};
    document.querySelector('#space-redeem-open').onclick = redeem;
    const invite = document.querySelector('#space-invite');
    if (invite) invite.onclick = async () => {
      invite.disabled = true;
      try {const value = await write('/spaces/invitations', 'POST'); document.querySelector('#space-invite-result').innerHTML = `<label class="field"><span>一次性邀请码（请妥善传递）</span><input readonly value="${esc(value.invitation)}"></label>`}
      catch (e) {toast(e.message, true)} finally {invite.disabled = false}
    };
  }
  function redeem() {
    openModal('创建你的家庭空间', `<p class="help">使用管理员提供的邀请码。原有家庭的数据不会复制到新空间。</p><form id="space-create">
      ${field('邀请码','invitation','','text','required maxlength="100" autocomplete="off"')}
      ${field('家庭名称','name','','text','required maxlength="40"')}
      ${field('家庭地址','slug','','text','required pattern="[a-z][a-z0-9-]{2,31}" placeholder="例如 sunny-home"')}
      ${field('成员一密码','MEMBER1_PASSWORD','','password','required minlength="12" maxlength="128" autocomplete="new-password"')}
      ${field('成员二密码','MEMBER2_PASSWORD','','password','required minlength="12" maxlength="128" autocomplete="new-password"')}
      <p class="help">登录账号分别为 member1 和 member2。每位成员登录后可修改姓名和密码。请只保存密码到自己的密码管理器。</p><p class="error" role="alert"></p><button class="btn" type="submit">创建独立空间</button></form>`, true);
    document.querySelector('#space-create').onsubmit = async e => {
      e.preventDefault();const f=e.currentTarget,b=f.querySelector('button');b.disabled=true;
      try {const result=await write('/spaces/redeem','POST',Object.fromEntries(new FormData(f)));location.href=result.entry}
      catch(err){f.querySelector('.error').textContent=err.message;b.disabled=false}
    };
  }
  document.addEventListener('click', e => {
    const el=e.target.closest('[data-household-open],[data-household-redeem]');if(!el)return;
    if(el.hasAttribute('data-household-redeem'))redeem();else open().catch(err=>toast(err.message,true));
  });
  return {open, redeem};
})();
