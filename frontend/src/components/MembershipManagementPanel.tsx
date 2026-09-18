import React, { useState } from 'react';
import { View } from 'react-native';
import { Text } from 'react-native-paper';
import { membershipRequest } from '../lib/personalAccounts';
import { readMembers } from '../lib/householdMembers';
import { readHouseholds, readMemberships, roleLabel, stateLabel, type Membership } from '../lib/memberships';
import { SectionCard } from '../ui/components';
import { MembershipButton, MembershipFrame, membershipStyles, useMembershipPanel, type MembershipCommand, type MembershipJob, type MembershipPanelProps } from './PersonalAccountPanel';

export type MembershipManagementPanelProps = MembershipPanelProps & { onLeft?: () => void | Promise<void> };
export default function MembershipManagementPanel(props: MembershipManagementPanelProps) {
  const [members, setMembers] = useState<Membership[]>([]), [admin, setAdmin] = useState(false), [self, setSelf] = useState<Membership | null>(null);
  const [choice, setChoice] = useState<MembershipCommand | null>(null), [name, setName] = useState('');
  const clear = () => { setMembers([]); setAdmin(false); setSelf(null); setChoice(null); setName(''); };
  const load = async (job: MembershipJob) => {
    const user = job.identity.member.user; if (user?.role !== 'member') return () => { setMembers([]); setSelf(null); setAdmin(false); };
    const snapshot = readMembers(await membershipRequest('/members', job.signal), user.id, user.auth_version);
    const allowed = snapshot.members.find(m => m.id === user.id)?.householdRole === 'admin';
    const values = allowed ? readMemberships(await membershipRequest('/memberships?status=all', job.signal), user.householdId) : [];
    let mine: Membership | null = null;
    if (job.identity.account.account) {
      const homes = readHouseholds(await membershipRequest('/account/households', job.signal));
      const h = homes.memberships.find(h => h.householdId === user.householdId && h.memberId === user.id);
      if (h) mine = { id: h.id, householdId: h.householdId, memberId: h.memberId, memberName: h.memberName, householdRole: h.householdRole, revision: h.revision, state: 'active' };
    }
    return () => { setMembers(values); setAdmin(allowed); setSelf(mine); };
  };
  const panel = useMembershipPanel(props, !!choice, clear, load), user = panel.identity?.member.user;
  const choose = (m: Membership, leave: boolean) => {
    if (!user || panel.locked) return; setName(m.memberName);
    setChoice({ action: leave ? 'leave' : 'remove', scope: 'member', path: leave ? '/memberships/self/leave' : '/memberships/' + m.memberId + '/remove', targetId: m.memberId,
      body: { expectedRevision: m.revision, expectedAuthVersion: user.auth_version } });
  };
  return <MembershipFrame title="管理家庭成员关系" testID="membership-management-panel" panel={panel} onCompleted={result => {
    if ('state' in result && result.state === 'left') return props.onLeft?.();
  }}>
    <Text>退出或移除后，成员不能继续进入这个家；原来的私人资料与家庭记录会保留。</Text>
    {admin && <SectionCard title="家庭成员"><View style={membershipStyles.stack}>
      {members.map(member => <View key={member.id} testID={'membership-' + member.memberId} style={membershipStyles.stack}>
        <Text>{member.memberName} · {roleLabel(member.householdRole)} · {stateLabel(member.state)}</Text>
        {member.state === 'active' && member.memberId !== user?.id && <MembershipButton label={'移除成员：' + member.memberName} onPress={() => choose(member, false)} disabled={panel.locked || !!choice} />}
      </View>)}
    </View></SectionCard>}
    {self ? <SectionCard title="我的成员关系"><View style={membershipStyles.stack}>
      <Text>{self.memberName} · {roleLabel(self.householdRole)}</Text>
      <Text>最后一位管理员需要先由另一成员接任，才能退出。</Text>
      <MembershipButton label="退出这个家庭" onPress={() => choose(self, true)} disabled={panel.locked || !!choice} />
    </View></SectionCard> : <Text>自助退出需要先在“我的家庭账户”明确绑定本人身份。</Text>}
    {choice && <SectionCard title={choice.action === 'leave' ? '确认退出家庭？' : '确认移除成员？'}><View style={membershipStyles.stack}>
      <Text>{name}</Text><Text>这不会删除历史数据。再次加入需要新的有效邀请和本人确认，不会自动恢复管理员权限。</Text>
      <MembershipButton label={choice.action === 'leave' ? '确认退出家庭' : '确认移除成员'} primary disabled={panel.locked} onPress={() => { const c = choice; setChoice(null); void panel.write(c); }} />
      <MembershipButton label="取消" onPress={() => setChoice(null)} disabled={panel.locked} />
    </View></SectionCard>}
    <MembershipButton label="刷新成员关系" onPress={panel.refresh} disabled={panel.locked || !!choice} />
  </MembershipFrame>;
}
