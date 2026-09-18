import React, { useState } from 'react';
import { View } from 'react-native';
import { Text, TextInput } from 'react-native-paper';
import { membershipRequest } from '../lib/personalAccounts';
import { readMembers } from '../lib/householdMembers';
import { readCurrentHousehold, readInvitationCreated, readInvitations, readJoinPreview, type Invitation, type JoinPreview, type Membership, type MembershipResult } from '../lib/memberships';
import { SectionCard } from '../ui/components';
import { MembershipButton, MembershipFrame, membershipStyles, useMembershipPanel, type MembershipCommand, type MembershipJob, type MembershipPanelProps } from './PersonalAccountPanel';

export type MembershipInvitationsPanelProps = MembershipPanelProps & { onJoined?: (membership: Membership) => void | Promise<void> };
const invitationLabel = (state: Invitation['state']) => ({ pending: '有效', used: '已使用', revoked: '已撤销', expired: '已到期', invalid: '已失效' })[state];
export default function MembershipInvitationsPanel(props: MembershipInvitationsPanelProps) {
  const [invitations, setInvitations] = useState<Invitation[]>([]), [admin, setAdmin] = useState(false);
  const [householdSlug, setSlug] = useState(''), [token, setToken] = useState(''), [join, setJoin] = useState<JoinPreview | null>(null);
  const [createdToken, setCreatedToken] = useState(''), [choice, setChoice] = useState<MembershipCommand | null>(null);
  const [login, setLogin] = useState(''), [password, setPassword] = useState('');
  const [home, setHome] = useState<{ name: string; slug: string } | null>(null);
  const clear = () => { setInvitations([]); setAdmin(false); setSlug(''); setToken(''); setJoin(null); setCreatedToken(''); setChoice(null); setLogin(''); setPassword(''); setHome(null); };
  const load = async (job: MembershipJob) => {
    const user = job.identity.member.user; let values: Invitation[] = [], allowed = false, currentHome = null;
    if (user?.role === 'member') {
      const members = readMembers(await membershipRequest('/members', job.signal), user.id, user.auth_version);
      allowed = members.members.find(m => m.id === user.id)?.householdRole === 'admin';
      currentHome = readCurrentHousehold(await membershipRequest('/spaces/current', job.signal), user.householdId);
      if (allowed) values = readInvitations(await membershipRequest('/member-invitations', job.signal));
    }
    return () => { setInvitations(values); setAdmin(allowed); setHome(currentHome); };
  };
  const panel = useMembershipPanel(props, !!(householdSlug || token || join || choice || createdToken || login || password), clear, load), identity = panel.identity;
  async function inspect() { await panel.run(async job => {
    const preview = readJoinPreview(await panel.checked(job, () => membershipRequest('/account/invitations/inspect', job.signal,
      { method: 'POST', csrf: job.identity.account.csrf, payload: { householdSlug, token } })));
    if (job.current()) { setJoin(preview); panel.setMessage('请核对家庭名称，再明确加入。'); }
  }); }
  async function complete(result: MembershipResult) {
    if ('state' in result && 'memberId' in result && result.state === 'active') await props.onJoined?.(result);
    if ('invitation' in result) {
      const created = readInvitationCreated(result); setCreatedToken(created.token || '');
      if (!created.token) panel.setMessage('原邀请码不能再次显示。需要新邀请码时，请先明确撤销旧邀请。');
    }
  }
  const confirm = () => { if (!choice || panel.locked) return; const c = choice; setChoice(null); void panel.write(c); };
  const accountFields = (recovery = false) => <View style={membershipStyles.stack}>
    <Text>已有个人账户可直接登录。创建新账户需要先核对有效邀请；登录后重新核对邀请再加入。</Text>
    <TextInput mode="outlined" label="个人账号" accessibilityLabel="个人账号" autoCapitalize="none" autoCorrect={false} value={login} onChangeText={v => { setLogin(v); setChoice(null); }} disabled={panel.busy} maxLength={64} />
    <TextInput mode="outlined" label="个人密码" accessibilityLabel="个人密码" secureTextEntry value={password} onChangeText={v => { setPassword(v); setChoice(null); }} disabled={panel.busy} maxLength={128} />
    <Text variant="bodySmall">账号为 3–64 位小写字母、数字或 . _ -；密码至少 12 个字符。</Text>
    <MembershipButton label="登录个人账户" onPress={() => void panel.authenticate(login, password)} disabled={panel.busy || !login || !password} />
    {!recovery && <MembershipButton label="创建个人账户" disabled={panel.locked || !join || !login || !password}
      onPress={() => setChoice({ action: 'register', scope: 'account', path: '/account/register', login, body: { login, password, eligibilityToken: join!.eligibilityToken } })} />}
  </View>;
  return <MembershipFrame title="邀请与加入家庭" testID="membership-invitations-panel" panel={panel} onCompleted={complete}
    recovery={panel.handle?.action === 'register' && !identity?.account.account ? accountFields(true) : null}>
    {admin && <SectionCard title="邀请加入这个家"><View style={membershipStyles.stack}>
      {home && <><Text>{home.name}</Text><Text selectable>家庭地址简称：{home.slug}</Text></>}
      <Text>新成员以普通成员身份加入。只把邀请码交给你要邀请的人。</Text>
      <MembershipButton label="创建邀请码" disabled={panel.locked || !!choice || !!token || !!join || !!createdToken} onPress={() => setChoice({ action: 'invite', scope: 'member', path: '/member-invitations',
        body: { expectedAuthVersion: identity!.member.user!.auth_version } })} />
      {!!createdToken && <View testID="membership-invitation-secret" style={membershipStyles.stack}>
        <Text>邀请码仅在此显示一次，离开或隐藏页面后会清空。</Text><Text selectable style={membershipStyles.wrap}>{createdToken}</Text>
        <MembershipButton label="复制邀请码" disabled={panel.locked} onPress={() => {
          if (typeof navigator !== 'undefined' && navigator.clipboard) void navigator.clipboard.writeText(createdToken).then(() => { if (panel.current()) panel.setMessage('邀请码已复制。'); }, () => panel.setError('复制未完成，可以选中上方邀请码复制。'));
          else panel.setMessage('请选中上方邀请码复制。');
        }} />
        <MembershipButton label="我已保存邀请码" onPress={() => setCreatedToken('')} disabled={panel.locked} />
      </View>}
      {invitations.map(invitation => <View key={invitation.id} testID={'member-invitation-' + invitation.id} style={membershipStyles.stack}>
        <Text>{invitationLabel(invitation.state)} · 到期 {invitation.expiresAt}</Text>
        {invitation.state === 'pending' && <MembershipButton label={'撤销邀请：' + invitation.id.slice(-6)} disabled={panel.locked || !!choice || !!token || !!createdToken}
          onPress={() => setChoice({ action: 'revoke', scope: 'member', path: '/member-invitations/' + invitation.id + '/revoke', targetId: invitation.id, body: { expectedRevision: invitation.revision } })} />}
      </View>)}
    </View></SectionCard>}
    <SectionCard title="加入受邀家庭"><View style={membershipStyles.stack}>
      <TextInput mode="outlined" label="家庭地址简称" accessibilityLabel="家庭地址简称" autoCapitalize="none" autoCorrect={false} value={householdSlug} onChangeText={v => { setSlug(v); setJoin(null); setChoice(null); }} disabled={panel.locked} maxLength={32} />
      <TextInput mode="outlined" label="邀请码" accessibilityLabel="邀请码" secureTextEntry value={token} onChangeText={v => { setToken(v); setJoin(null); setChoice(null); }} disabled={panel.locked} maxLength={2048} />
      <MembershipButton label="核对邀请" onPress={() => void inspect()} disabled={panel.locked || !token || !householdSlug} primary />
      {join && <View testID="membership-join-preview" style={membershipStyles.stack}>
        <Text>{join.household.name}</Text><Text>加入后为普通成员，私人资料仍各自保管。</Text>
        {identity?.account.account ? <MembershipButton label="加入这个家庭" disabled={panel.locked} onPress={() => setChoice({ action: 'accept', scope: 'account', path: '/account/invitations/accept', targetId: join.household.id, body: { joinTicket: join.joinTicket } })} />
          : <Text>请先登录或创建个人账户，再重新核对邀请。</Text>}
      </View>}
      {!identity?.account.account && accountFields()}
    </View></SectionCard>
    {choice && <SectionCard title="确认操作"><View style={membershipStyles.stack}>
      <Text>{choice.action === 'accept' ? '确认加入上方家庭？不会自动切换当前家庭。' : choice.action === 'revoke' ? '撤销后，这份尚未使用的邀请码不能继续加入家庭。' : choice.action === 'register' ? '创建个人账户。完成后重新核对邀请码，再明确加入家庭。' : '创建一份有效期为七天的普通成员邀请？'}</Text>
      <MembershipButton label="确认继续" onPress={confirm} disabled={panel.locked} primary /><MembershipButton label="取消" onPress={() => setChoice(null)} disabled={panel.locked} />
    </View></SectionCard>}
    <MembershipButton label="清空未提交内容" onPress={() => { clear(); panel.refresh(); }} disabled={panel.locked} />
  </MembershipFrame>;
}
