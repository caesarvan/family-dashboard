import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Banner, BottomNavigation, Button, Divider, IconButton, Menu, Surface, Text, useTheme } from 'react-native-paper';
import type { ItemKind, RouteName } from '../lib/types';

type Action = () => void | Promise<void>;
export type AppShellProps = {
  route: RouteName; title: string; name: string; householdName: string;
  onNavigate: (route: RouteName) => void; onCreate: (kind: ItemKind) => void;
  onRefresh: Action; onLogout: Action; refreshing: boolean; offline: boolean;
  children: ReactNode; onLegacy: (fragment: string) => void;
};
const navigation: { key: RouteName; title: string; focusedIcon: string; unfocusedIcon: string }[] = [
  { key: 'home', title: '首页', focusedIcon: 'home', unfocusedIcon: 'home-outline' },
  { key: 'calendar', title: '日程', focusedIcon: 'calendar', unfocusedIcon: 'calendar-outline' },
  { key: 'tasks', title: '待办', focusedIcon: 'checkbox-marked-circle', unfocusedIcon: 'checkbox-blank-circle-outline' },
  { key: 'shopping', title: '采购', focusedIcon: 'shopping', unfocusedIcon: 'shopping-outline' },
  { key: 'more', title: '更多', focusedIcon: 'dots-horizontal-circle', unfocusedIcon: 'dots-horizontal' },
];
const desktopNavigation: { key: RouteName; title: string; label?: string }[] = [
  ...navigation.filter(item => item.key !== 'more'),
  { key: 'trips', title: '旅行' }, { key: 'photos', title: '相册' },
  { key: 'assistant', title: '家庭助理', label: '助理' },
];
const creation: { kind: ItemKind; title: string; icon: string }[] = [
  { kind: 'tasks', title: '添加待办', icon: 'checkbox-marked-circle-plus-outline' },
  { kind: 'events', title: '添加安排', icon: 'calendar-plus' },
  { kind: 'shopping', title: '添加采购', icon: 'cart-plus' },
  { kind: 'trips', title: '计划旅行', icon: 'airplane' },
];
// Paper's initial hide animation can close a freshly opened menu after navigation.
const menuTheme = { animation: { scale: 0 } };
/** Layout only. The parent owns identity, authorized data and persistence. */
export default function AppShell(props: AppShellProps) {
  const { width } = useWindowDimensions();
  const wide = width >= 1040;
  const theme = useTheme(); const insets = useSafeAreaInsets();
  const scroll = useRef<ScrollView>(null);
  const [menu, setMenu] = useState<'create' | 'account' | 'more' | null>(null);
  const { route, onNavigate, onLegacy } = props;
  useEffect(() => { setMenu(null); scroll.current?.scrollTo({ y: 0, animated: false }); }, [route, props.name, props.householdName]);
  useEffect(() => { setMenu(null); }, [wide]);
  const navigate = (next: RouteName) => { setMenu(null); onNavigate(next); };
  const legacy = (fragment: string) => { setMenu(null); onLegacy(fragment); };
  const tabIndex = navigation.findIndex(item => item.key === route);
  return (
    <View style={[styles.frame, { backgroundColor: theme.colors.background, paddingTop: insets.top }]}>
      <Surface elevation={0} style={[styles.headerSurface, { backgroundColor: theme.colors.background }]}>
        <View style={[styles.header, { paddingHorizontal: wide ? 24 : 12, minHeight: wide ? 72 : 64 }]}>
          {wide ? <Button mode="text" onPress={() => navigate('home')} accessibilityLabel="家庭中枢首页"
            icon={({ color }) => <MaterialCommunityIcons name="home-outline" size={24} color={color} />}
            textColor={theme.colors.onSurface} labelStyle={styles.brandLabel} style={styles.brand}>家庭中枢</Button> :
            <View style={styles.mobileHeading}>
              {tabIndex < 0 ? <IconButton icon="arrow-left" size={22} onPress={() => navigate('more')} accessibilityLabel="返回更多功能" style={styles.iconButton} /> :
                <MaterialCommunityIcons name="home-outline" size={24} color={theme.colors.onSurface} accessibilityElementsHidden />}
              <View style={styles.headerCopy}>
                <Text variant="titleSmall" numberOfLines={1}>{route === 'home' ? props.householdName || '我们的家' : props.title}</Text>
                {route === 'home' ? <Text variant="bodySmall" numberOfLines={1} style={{ color: theme.colors.onSurfaceVariant }}>家庭中枢</Text> : null}
              </View>
            </View>}
          {wide ? <View style={styles.navigation}>
            {desktopNavigation.map(item => <Button key={item.key} mode="text" compact onPress={() => navigate(item.key)} accessibilityLabel={item.title}
              accessibilityState={{ selected: route === item.key }} textColor={route === item.key ? theme.colors.onSurface : theme.colors.onSurfaceVariant}
              style={[styles.navButton, route === item.key && { backgroundColor: theme.colors.primaryContainer }]}
              labelStyle={styles.navLabel}>{item.label || item.title}</Button>)}
            <Menu theme={menuTheme} visible={menu === 'more'} onDismiss={() => setMenu(null)} contentStyle={styles.menu}
              anchor={<Button mode="text" compact icon="chevron-down" textColor={theme.colors.onSurfaceVariant}
                accessibilityLabel="更多功能" accessibilityState={{ expanded: menu === 'more' }} style={styles.navButton}
                contentStyle={styles.reverse} labelStyle={styles.navLabel} onPress={() => setMenu('more')}>更多</Button>}>
              <Menu.Item title="家庭资金" leadingIcon="wallet-outline" onPress={() => navigate('finance')} />
              <Menu.Item title="家庭物品" leadingIcon="package-variant-closed" onPress={() => navigate('inventory')} />
              <Menu.Item title="足迹地图" leadingIcon="map-outline" onPress={() => navigate('map')} />
              <Divider /><Menu.Item title="全部工具与设置" leadingIcon="view-grid-outline" onPress={() => navigate('more')} />
            </Menu>
          </View> : null}
          <View style={styles.headerActions}>
            <IconButton icon="refresh" size={20} onPress={props.onRefresh} disabled={props.refreshing} loading={props.refreshing} accessibilityLabel="刷新家庭数据" style={styles.iconButton} />
            <Menu theme={menuTheme} visible={menu === 'create'} onDismiss={() => setMenu(null)} anchor={wide ? (
              <Button mode="contained" icon="plus" onPress={() => setMenu('create')} style={styles.button} contentStyle={styles.buttonContent}>新建</Button>
            ) : <IconButton icon="plus" mode="contained" containerColor={theme.colors.primary} iconColor={theme.colors.onPrimary} size={21} onPress={() => setMenu('create')} accessibilityLabel="新建记录" style={[styles.iconButton, styles.button]} />} contentStyle={styles.menu}>
              {creation.map(item => <Menu.Item key={item.kind} title={item.title} leadingIcon={item.icon} onPress={() => { setMenu(null); props.onCreate(item.kind); }} />)}
            </Menu>
            <Menu theme={menuTheme} visible={menu === 'account'} onDismiss={() => setMenu(null)} anchor={
              <IconButton icon="account-circle-outline" size={23} onPress={() => setMenu('account')} accessibilityLabel={`${props.name}，账户菜单`} style={styles.iconButton} />
            } contentStyle={styles.menu}>
              <Menu.Item title={props.name || '我的账户'} disabled /><Menu.Item title={props.householdName || '我们的家'} disabled />
              <Divider /><Menu.Item title="连接与账户" leadingIcon="link-variant" onPress={() => legacy('connections')} />
              <Menu.Item title="家庭设置" leadingIcon="cog-outline" onPress={() => legacy('settings')} />
              <Divider /><Menu.Item title="退出登录" leadingIcon="logout" onPress={() => { setMenu(null); void props.onLogout(); }} />
            </Menu>
          </View>
        </View>
      </Surface>
      {props.offline ? <Banner visible actions={[{ label: '重新读取', onPress: props.onRefresh, disabled: props.refreshing }]}>
        连接暂时不可用。请刷新后核对最新内容。
      </Banner> : null}
      <ScrollView ref={scroll} style={styles.contentScroll} contentContainerStyle={styles.scrollContent} keyboardShouldPersistTaps="handled">
        <View style={[styles.content, { paddingHorizontal: wide ? 24 : 16, paddingTop: wide ? 32 : 20 }]}>{props.children}</View>
      </ScrollView>
      {!wide ? <BottomNavigation.Bar navigationState={{ index: tabIndex >= 0 ? tabIndex : 4, routes: navigation }}
        getAccessibilityLabel={({ route: item }) => item.title} onTabPress={({ route: next }) => navigate(next.key)}
        activeColor={theme.colors.onSurface} inactiveColor={theme.colors.onSurfaceVariant}
        shifting={false} labeled safeAreaInsets={{ bottom: insets.bottom, left: insets.left, right: insets.right }}
        style={[styles.bottomBar, { borderColor: theme.colors.outlineVariant, backgroundColor: theme.colors.surface }]} /> : null}
    </View>
  );
}
const styles = StyleSheet.create({
  frame: { flex: 1, minHeight: 0 }, headerSurface: { alignItems: 'center' },
  header: { width: '100%', maxWidth: 1328, flexDirection: 'row', alignItems: 'center', gap: 14 },
  brand: { borderRadius: 999, flexShrink: 0, marginLeft: -10 },
  brandLabel: { fontSize: 20, lineHeight: 28, fontWeight: '600', letterSpacing: -0.5, marginHorizontal: 8 },
  navigation: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 2 },
  navButton: { borderRadius: 999, minWidth: 52 }, navLabel: { fontSize: 14, marginHorizontal: 12, marginVertical: 10 },
  reverse: { flexDirection: 'row-reverse' },
  mobileHeading: { flex: 1, minWidth: 0, flexDirection: 'row', alignItems: 'center', gap: 8 }, headerCopy: { flex: 1, minWidth: 0, gap: 1 },
  headerActions: { flexDirection: 'row', alignItems: 'center', gap: 2 }, iconButton: { margin: 0 },
  button: { borderRadius: 999 }, buttonContent: { minHeight: 40 }, menu: { borderRadius: 20, minWidth: 210 },
  contentScroll: { flex: 1 }, scrollContent: { flexGrow: 1, alignItems: 'center' },
  content: { width: '100%', maxWidth: 1328, paddingBottom: 40 }, bottomBar: { borderTopWidth: 1 },
});
