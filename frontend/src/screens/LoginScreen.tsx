import React, { useEffect, useState } from 'react';
import { Linking, StyleSheet, View } from 'react-native';
import { Button, Card, Divider, HelperText, SegmentedButtons, Text, TextInput, useTheme } from 'react-native-paper';
import { request } from '../lib/api';
import { useHousehold } from '../lib/household';

export default function LoginScreen() {
  const { login } = useHousehold(); const theme = useTheme();
  const [username, setUsername] = useState('member1'); const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const [providers, setProviders] = useState<{id: string; configured: boolean; loginUrl: string}[]>([]);
  useEffect(() => { let active = true; request<{providers: typeof providers}>('/auth/providers').then(result => { if (active) setProviders(result.providers || []); }).catch(() => {}); return () => { active = false; }; }, []);
  async function submit() { setBusy(true); setError(''); try { await login(username, password); setPassword(''); } catch (e) { setError(e instanceof Error ? e.message : '暂时无法登录'); } finally { setBusy(false); } }
  return <View style={[styles.page, { backgroundColor: theme.colors.background }]}>
    <View style={styles.intro}><Text variant="labelLarge" style={{color: theme.colors.onSurfaceVariant}}>家庭中枢</Text><Text variant="headlineLarge" style={styles.title}>把日子放在一起。</Text><Text variant="bodyLarge">今天的安排、共同的计划，都在这里。</Text></View>
    <Card mode="outlined" style={styles.card}><Card.Content style={styles.content}>
      <Text variant="titleLarge">欢迎回家</Text>
      <SegmentedButtons value={username} onValueChange={setUsername} buttons={[{value:'member1',label:'成员一'},{value:'member2',label:'成员二'}]} />
      <TextInput label="登录密码" mode="outlined" value={password} onChangeText={setPassword} secureTextEntry autoComplete="current-password" onSubmitEditing={() => { if (!busy && password) void submit(); }} />
      {!!error && <HelperText type="error" accessibilityRole="alert">{error}</HelperText>}
      <Button mode="contained" loading={busy} disabled={busy || !password} onPress={submit}>进入家庭看板</Button>
      {providers.some(p=>p.configured) && <><Divider /><Text variant="bodySmall">也可以使用已绑定的账户登录</Text>{providers.filter(p=>p.configured && /^\/auth\/(microsoft|google)\/login$/.test(p.loginUrl)).map(provider=><Button key={provider.id} mode="outlined" onPress={()=>Linking.openURL(provider.loginUrl)}>{provider.id==='microsoft'?'Microsoft':'Google'} 账户</Button>)}</>}
      <View style={styles.links}><Button compact onPress={()=>Linking.openURL('/classic#household')}>切换家庭</Button><Button compact onPress={()=>Linking.openURL('/tv')}>连接电视</Button></View>
    </Card.Content></Card>
  </View>;
}
const styles=StyleSheet.create({page:{flex:1,minHeight:700,padding:24,justifyContent:'center',alignItems:'center',gap:32},intro:{width:'100%',maxWidth:420,gap:12},title:{fontWeight:'700'},card:{width:'100%',maxWidth:420,borderRadius:16},content:{padding:24,gap:18},links:{flexDirection:'row',flexWrap:'wrap',justifyContent:'space-between'}});
