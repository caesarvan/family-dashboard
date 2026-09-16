import { openLocal } from '../lib/navigation';
import React, { useEffect, useState } from 'react';
import { Platform, StyleSheet, View, type ViewStyle } from 'react-native';
import { Button, Card, Dialog, Divider, HelperText, Portal, SegmentedButtons, Text, TextInput, useTheme } from 'react-native-paper';
import { request } from '../lib/api';
import { useHousehold } from '../lib/household';
import { expoTokens } from '../ui/theme';

// The reference uses a sky wash only in its introductory hero.
const heroWash: ViewStyle & { backgroundImage?: string } = Platform.OS === 'web'
  ? { backgroundImage: `radial-gradient(ellipse at top, ${expoTokens.skyLight} 0%, ${expoTokens.canvas} 72%)` }
  : { backgroundColor: expoTokens.canvasSoft };

export default function LoginScreen() {
  const { login } = useHousehold(); const theme = useTheme();
  const [username, setUsername] = useState('member1'); const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const [spaceOpen,setSpaceOpen]=useState(false),[slug,setSlug]=useState('home');
  const [providers, setProviders] = useState<{id: string; configured: boolean; loginUrl: string}[]>([]);
  useEffect(() => { let active = true; request<{providers: typeof providers}>('/auth/providers').then(result => { if (active) setProviders(result.providers || []); }).catch(() => {}); return () => { active = false; }; }, []);
  async function submit() { if(busy)return; setBusy(true); setError(''); try { await login(username, password); setPassword(''); } catch (e) { setError(e instanceof Error ? e.message : '暂时无法登录'); } finally { setBusy(false); } }
  return <View style={[styles.page, { backgroundColor: theme.colors.background }]}>
    <View pointerEvents="none" accessible={false} style={[styles.wash, heroWash]} />
    <View style={styles.intro}><Text variant="labelLarge" style={{color: theme.colors.onSurfaceVariant}}>家庭中枢</Text><Text variant="headlineLarge" style={styles.title}>把日子放在一起。</Text><Text variant="bodyLarge">今天的安排、共同的计划，都在这里。</Text></View>
    <Card mode="outlined" style={styles.card}><Card.Content style={styles.content}>
      <Text variant="titleLarge">欢迎回家</Text>
      <SegmentedButtons value={username} onValueChange={value=>{if(!busy)setUsername(value);}} buttons={[{value:'member1',label:'成员一',disabled:busy},{value:'member2',label:'成员二',disabled:busy}]} />
      <TextInput outlineStyle={{borderRadius:8}} accessibilityLabel="登录密码" label="登录密码" mode="outlined" disabled={busy} value={password} onChangeText={setPassword} secureTextEntry autoComplete="current-password" onSubmitEditing={() => { if (!busy && password) void submit(); }} />
      {!!error && <HelperText type="error" accessibilityRole="alert">{error}</HelperText>}
      <Button mode="contained" loading={busy} disabled={busy || !password} onPress={submit}>进入家庭看板</Button>
      {providers.some(p=>p.configured) && <><Divider /><Text variant="bodySmall">也可以使用已绑定的账户登录</Text>{providers.filter(p=>p.configured && /^\/auth\/(microsoft|google)\/login$/.test(p.loginUrl)).map(provider=><Button key={provider.id} mode="outlined" onPress={()=>openLocal(provider.loginUrl)}>{provider.id==='microsoft'?'Microsoft':'Google'} 账户</Button>)}</>}
      <View style={styles.links}><Button compact onPress={()=>setSpaceOpen(true)}>切换家庭</Button><Button compact onPress={()=>openLocal('/tv')}>连接电视</Button></View>
    </Card.Content></Card>
    <Portal><Dialog visible={spaceOpen} onDismiss={()=>setSpaceOpen(false)} style={{maxWidth:440,width:'90%',alignSelf:'center'}}><Dialog.Title>切换家庭</Dialog.Title><Dialog.Content><TextInput outlineStyle={{borderRadius:8}} mode="outlined" accessibilityLabel="家庭入口名称" label="家庭入口名称" value={slug} onChangeText={setSlug} autoCapitalize="none"/><HelperText type="info">输入邀请时使用的家庭入口名称。</HelperText></Dialog.Content><Dialog.Actions><Button onPress={()=>setSpaceOpen(false)}>取消</Button><Button disabled={!/^[a-z0-9][a-z0-9-]{2,39}$/.test(slug)} onPress={()=>openLocal('/space/'+encodeURIComponent(slug))}>进入家庭</Button></Dialog.Actions></Dialog></Portal>
  </View>;
}
const styles=StyleSheet.create({page:{flex:1,minHeight:700,padding:24,justifyContent:'center',alignItems:'center',gap:32},wash:{position:'absolute',top:0,left:0,right:0,height:340},intro:{width:'100%',maxWidth:420,gap:12},title:{fontWeight:'600'},card:{width:'100%',maxWidth:420,borderRadius:12},content:{padding:24,gap:18},links:{flexDirection:'row',flexWrap:'wrap',justifyContent:'space-between'}});
