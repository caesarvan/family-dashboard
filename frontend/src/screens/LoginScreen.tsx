import { openLocal } from '../lib/navigation';
import React, { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { Button, Card, Dialog, Divider, HelperText, Icon, Portal, SegmentedButtons, Text, TextInput, useTheme } from 'react-native-paper';
import { request } from '../lib/api';
import { useHousehold } from '../lib/household';
import WelcomeVisual from '../ui/WelcomeVisual';
import PersonalAccountPanel from '../components/PersonalAccountPanel';
import MembershipInvitationsPanel from '../components/MembershipInvitationsPanel';

export default function LoginScreen({ authError = '', onPendingChange }: { authError?: string; onPendingChange?: (pending: boolean) => void } = {}) {
  const { login, refresh } = useHousehold(); const theme = useTheme();
  const { width, height } = useWindowDimensions(); const wide = width >= 960;
  const [username, setUsername] = useState('member1'); const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const [spaceOpen,setSpaceOpen]=useState(false),[slug,setSlug]=useState('home');
  const [accountPage, setAccountPage] = useState<'account' | 'invitation' | null>(null);
  const [providers, setProviders] = useState<{id: string; configured: boolean; loginUrl: string}[]>([]);
  useEffect(() => { let active = true; request<{providers: typeof providers}>('/auth/providers').then(result => { if (active) setProviders(result.providers || []); }).catch(() => {}); return () => { active = false; }; }, []);
  async function submit() { if(busy)return; setBusy(true); setError(''); try { await login(username, password); setPassword(''); } catch (e) { setError(e instanceof Error ? e.message : '暂时无法登录'); } finally { setBusy(false); } }
  if(accountPage)return <ScrollView style={{backgroundColor:theme.colors.background}} contentContainerStyle={{padding:24,width:'100%',maxWidth:760,alignSelf:'center'}} keyboardShouldPersistTaps="handled">
    {accountPage==='account'?<PersonalAccountPanel onBack={()=>setAccountPage(null)} onPendingChange={onPendingChange} onIdentityChanged={refresh}/>
      :<MembershipInvitationsPanel onBack={()=>setAccountPage(null)} onPendingChange={onPendingChange} onJoined={async()=>{await refresh();setAccountPage('account');}}/>}
  </ScrollView>;
  return <ScrollView style={{ backgroundColor: theme.colors.background }} contentContainerStyle={[styles.page, { minHeight: height }, wide && styles.pageWide]} keyboardShouldPersistTaps="handled">
    <View style={styles.brand}><Icon source="home-outline" size={26} /><Text variant="titleMedium">家庭中枢</Text></View>
    <View style={[styles.layout, wide && styles.layoutWide]}>
    <View style={[styles.intro, wide && styles.introWide]}>
      <Text accessibilityRole="header" style={[styles.title, wide && styles.titleWide]}>把日子{wide ? '\n' : ''}放在一起。</Text>
      <Text variant="bodyLarge" style={[styles.description, { color: theme.colors.onSurfaceVariant }]}>今天的安排、共同的计划，都在这里。</Text>
      {wide && <View style={styles.visual}><WelcomeVisual /></View>}
    </View>
    <Card mode="contained" style={[styles.card, { backgroundColor: theme.colors.surfaceVariant }, wide && styles.cardWide]}><Card.Content style={[styles.content, wide && styles.contentWide]}>
      <View style={styles.formHeading}><Text variant="headlineSmall" style={styles.formTitle}>欢迎回家</Text><Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>选择成员，继续今天的生活。</Text></View>
      <Button mode="contained" style={styles.pill} contentStyle={styles.primaryContent} disabled={busy} onPress={()=>setAccountPage('account')}>我的家庭账户</Button>
      <Button mode="outlined" style={styles.pill} contentStyle={styles.primaryContent} disabled={busy} onPress={()=>setAccountPage('invitation')}>使用邀请加入家庭</Button>
      <Divider/><Text variant="bodySmall">已有家庭成员账号</Text>
      <SegmentedButtons value={username} onValueChange={value=>{if(!busy)setUsername(value);}} buttons={[{value:'member1',label:'成员一',disabled:busy},{value:'member2',label:'成员二',disabled:busy}]} />
      <TextInput outlineStyle={{borderRadius:8}} accessibilityLabel="登录密码" label="登录密码" mode="outlined" disabled={busy} value={password} onChangeText={setPassword} secureTextEntry autoComplete="current-password" onSubmitEditing={() => { if (!busy && password) void submit(); }} />
      {!!(error || authError) && <HelperText type="error" accessibilityRole="alert">{error || authError}</HelperText>}
      <Button mode="contained" style={styles.pill} contentStyle={styles.primaryContent} loading={busy} disabled={busy || !password} onPress={submit}>进入家庭看板</Button>
      {providers.some(p=>p.configured) && <><Divider /><Text variant="bodySmall">也可以使用已绑定的账户登录</Text>{providers.filter(p=>p.configured && /^\/auth\/(microsoft|google)\/login$/.test(p.loginUrl)).map(provider=><Button key={provider.id} mode="outlined" style={styles.pill} onPress={()=>openLocal(provider.loginUrl)}>{provider.id==='microsoft'?'Microsoft':'Google'} 账户</Button>)}</>}
      <View style={styles.links}><Button compact onPress={()=>setSpaceOpen(true)}>切换家庭</Button><Button compact onPress={()=>openLocal('/tv')}>连接电视</Button></View>
    </Card.Content></Card></View>
    <Portal><Dialog visible={spaceOpen} onDismiss={()=>setSpaceOpen(false)} style={{maxWidth:440,width:'90%',alignSelf:'center'}}><Dialog.Title>切换家庭</Dialog.Title><Dialog.Content><TextInput outlineStyle={{borderRadius:8}} mode="outlined" accessibilityLabel="家庭入口名称" label="家庭入口名称" value={slug} onChangeText={setSlug} autoCapitalize="none"/><HelperText type="info">输入邀请时使用的家庭入口名称。</HelperText></Dialog.Content><Dialog.Actions><Button onPress={()=>setSpaceOpen(false)}>取消</Button><Button disabled={!/^[a-z0-9][a-z0-9-]{2,39}$/.test(slug)} onPress={()=>openLocal('/space/'+encodeURIComponent(slug))}>进入家庭</Button></Dialog.Actions></Dialog></Portal>
  </ScrollView>;
}
const styles=StyleSheet.create({
  page: { flexGrow: 1, paddingHorizontal: 20, paddingVertical: 28, alignItems: 'center', justifyContent: 'center', gap: 32 },
  pageWide: { paddingHorizontal: 48, paddingVertical: 44, gap: 48 },
  brand: { width: '100%', maxWidth: 1120, flexDirection: 'row', alignItems: 'center', gap: 8 },
  layout: { width: '100%', maxWidth: 480, gap: 28 }, layoutWide: { maxWidth: 1120, flexDirection: 'row', alignItems: 'center', gap: 88 },
  intro: { minWidth: 0, gap: 14 }, introWide: { flex: 1, gap: 22 },
  title: { fontSize: 32, lineHeight: 40, fontWeight: '600', letterSpacing: -0.8 }, titleWide: { fontSize: 48, lineHeight: 54, letterSpacing: -1.2 },
  description: { maxWidth: 390 }, visual: { marginTop: 8 },
  card: { width: '100%', borderRadius: 28 }, cardWide: { width: 430, borderRadius: 40 },
  content: { paddingHorizontal: 20, paddingVertical: 24, gap: 18 }, contentWide: { paddingHorizontal: 32, paddingVertical: 36, gap: 22 },
  formHeading: { gap: 8, marginBottom: 4 }, formTitle: { fontSize: 24, lineHeight: 32, fontWeight: '600' },
  pill: { borderRadius: 999 }, primaryContent: { minHeight: 44 },
  links: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', gap: 4 },
});
