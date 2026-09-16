import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Banner, BottomNavigation, Button, Divider, Drawer, IconButton, Menu, Surface, Text, useTheme } from 'react-native-paper';
import type { ItemKind, RouteName, ThemeName } from '../lib/types';

type Action = () => void | Promise<void>;
export type AppShellProps = {
  route: RouteName;
  title: string;
  name: string;
  householdName: string;
  onNavigate: (route: RouteName) => void;
  onCreate: (kind: ItemKind) => void;
  onRefresh: Action;
  onLogout: Action;
  refreshing: boolean;
  offline: boolean;
  children: ReactNode;
  themeMode: ThemeName;
  onThemeChange: (name: ThemeName) => void | Promise<void>;
  onLegacy: (fragment: string) => void;
};

const navigation: { key: RouteName; title: string; focusedIcon: string; unfocusedIcon: string }[] = [
  { key: 'home', title: '首页', focusedIcon: 'home', unfocusedIcon: 'home-outline' },
  { key: 'calendar', title: '日程', focusedIcon: 'calendar', unfocusedIcon: 'calendar-outline' },
  { key: 'tasks', title: '待办', focusedIcon: 'checkbox-marked-circle', unfocusedIcon: 'checkbox-blank-circle-outline' },
  { key: 'shopping', title: '采购', focusedIcon: 'shopping', unfocusedIcon: 'shopping-outline' },
  { key: 'more', title: '更多', focusedIcon: 'dots-horizontal-circle', unfocusedIcon: 'dots-horizontal' },
];
const creation: { kind: ItemKind; title: string; icon: string }[] = [
  { kind: 'tasks', title: '添加待办', icon: 'checkbox-marked-circle-plus-outline' },
  { kind: 'events', title: '添加安排', icon: 'calendar-plus' },
  { kind: 'shopping', title: '添加采购', icon: 'cart-plus' },
  { kind: 'trips', title: '计划旅行', icon: 'airplane' },
];
const appearances: { key: ThemeName; title: string; icon: string }[] = [
  { key: 'light', title: '晨光白', icon: 'white-balance-sunny' },
  { key: 'forest', title: '暖绿森林', icon: 'leaf' },
  { key: 'ocean', title: '海岸蓝', icon: 'waves' },
];

/** Layout only. The parent owns identity, authorized data, forms and persistence. */
export default function AppShell(props: AppShellProps) {
  const { width } = useWindowDimensions();
  const wide = width >= 960;
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const scroll = useRef<ScrollView>(null);
  const [menu, setMenu] = useState<'create' | 'theme' | 'account' | null>(null);
  const { route, onNavigate, onLegacy } = props;
  useEffect(() => {
    setMenu(null);
    scroll.current?.scrollTo({ y: 0, animated: false });
  }, [route, props.name, props.householdName]);
  const navigate = (next: RouteName) => { setMenu(null); onNavigate(next); };
  const legacy = (fragment: string) => { setMenu(null); onLegacy(fragment); };
  const border = { borderColor: theme.colors.outlineVariant };
  const tabIndex = navigation.findIndex(item => item.key === route);

  return (
    <View style={[styles.frame, { backgroundColor: theme.colors.background, paddingTop: insets.top }]}>
      {wide ? (
        <Surface elevation={0} style={[styles.sidebar, border, { backgroundColor: theme.colors.surface }]}>
          <View style={styles.brand}>
            <MaterialCommunityIcons name="home-outline" size={26} color={theme.colors.onSurface} accessibilityElementsHidden />
            <Text variant="titleLarge">家庭中枢</Text>
          </View>
          <View style={[styles.household, { backgroundColor: theme.colors.surfaceVariant }]}>
            <Text variant="titleSmall" numberOfLines={2}>{props.householdName || '我们的家'}</Text>
            <Text variant="bodySmall" numberOfLines={1} style={{ color: theme.colors.onSurfaceVariant }}>{props.name}</Text>
          </View>
          <ScrollView style={styles.navScroll} contentContainerStyle={styles.navContent} showsVerticalScrollIndicator={false}>
            <Text variant="labelMedium" style={[styles.groupLabel, { color: theme.colors.onSurfaceVariant }]}>日常</Text>
            {navigation.filter(item => item.key !== 'more').map(item => (
              <Drawer.Item key={item.key} label={item.title} icon={item.unfocusedIcon} active={route === item.key}
                onPress={() => navigate(item.key)} style={styles.drawerItem} accessibilityLabel={item.title} />
            ))}
            <Drawer.Item label="家庭物品" icon="package-variant-closed" onPress={() => legacy('inventory')} style={styles.drawerItem} />
            <Divider style={styles.divider} />
            <Text variant="labelMedium" style={[styles.groupLabel, { color: theme.colors.onSurfaceVariant }]}>计划与记录</Text>
            <Drawer.Item label="旅行" icon="airplane" active={route === 'trips'} onPress={() => navigate('trips')} style={styles.drawerItem} />
            <Drawer.Item label="相册" icon="image-multiple-outline" onPress={() => legacy('photos')} style={styles.drawerItem} />
            <Drawer.Item label="足迹地图" icon="map-outline" onPress={() => legacy('map')} style={styles.drawerItem} />
            <Drawer.Item label="家庭财务" icon="wallet-outline" active={route === 'finance'} onPress={() => navigate('finance')} style={styles.drawerItem} />
          </ScrollView>
          <Divider />
          <Drawer.Item label="家庭助理" icon="creation-outline" onPress={() => legacy('assistant')} style={styles.drawerItem} />
          <Drawer.Item label="更多功能" icon="dots-horizontal" active={route === 'more'} onPress={() => navigate('more')} style={styles.drawerItem} />
        </Surface>
      ) : null}
      <View style={styles.main}>
        <Surface elevation={0} style={[styles.header, border, { backgroundColor: theme.colors.background, paddingHorizontal: wide ? 28 : 12 }]}>
          <View style={styles.headerCopy}>
            {wide ? <Text variant="bodySmall" numberOfLines={1} style={{ color: theme.colors.onSurfaceVariant }}>{props.householdName || '我们的家'}</Text> : null}
            <Text variant="titleSmall" numberOfLines={1}>{props.title}</Text>
          </View>
          <View style={styles.headerActions}>
            <IconButton icon="refresh" size={21} onPress={props.onRefresh} disabled={props.refreshing} loading={props.refreshing} accessibilityLabel="刷新家庭数据" style={styles.iconButton} />
            <Menu visible={menu === 'create'} onDismiss={() => setMenu(null)} anchor={wide ? (
              <Button mode="contained" icon="plus" onPress={() => setMenu('create')} style={styles.button} contentStyle={styles.buttonContent}>新建</Button>
            ) : (
              <IconButton icon="plus" mode="contained" containerColor={theme.colors.primary} iconColor={theme.colors.onPrimary} size={22} onPress={() => setMenu('create')} accessibilityLabel="新建记录" style={[styles.iconButton, styles.button]} />
            )} contentStyle={styles.menu}>
              {creation.map(item => <Menu.Item key={item.kind} title={item.title} leadingIcon={item.icon} onPress={() => { setMenu(null); props.onCreate(item.kind); }} />)}
            </Menu>
            <Menu visible={menu === 'theme'} onDismiss={() => setMenu(null)} anchor={
              <IconButton icon={theme.dark ? 'weather-night' : 'white-balance-sunny'} size={21} onPress={() => setMenu('theme')} accessibilityLabel="更换主题" style={styles.iconButton} />
            } contentStyle={styles.menu}>
              {appearances.map(item => <Menu.Item key={item.key} title={item.title} leadingIcon={item.icon}
                trailingIcon={props.themeMode === item.key ? 'check' : undefined}
                accessibilityLabel={`${item.title}${props.themeMode === item.key ? '，当前主题' : ''}`}
                onPress={() => { setMenu(null); void props.onThemeChange(item.key); }} />)}
            </Menu>
            <Menu visible={menu === 'account'} onDismiss={() => setMenu(null)} anchor={
              <IconButton icon="account-circle-outline" size={24} onPress={() => setMenu('account')} accessibilityLabel={`${props.name}，账户菜单`} style={styles.iconButton} />
            } contentStyle={styles.menu}>
              <Menu.Item title={props.name || '我的账户'} disabled />
              <Divider />
              <Menu.Item title="连接与账户" leadingIcon="link-variant" onPress={() => legacy('connections')} />
              <Menu.Item title="家庭设置" leadingIcon="cog-outline" onPress={() => legacy('settings')} />
              <Divider />
              <Menu.Item title="退出登录" leadingIcon="logout" onPress={() => { setMenu(null); void props.onLogout(); }} />
            </Menu>
          </View>
        </Surface>
        <Banner visible={props.offline} actions={[{ label: '重新读取', onPress: props.onRefresh, disabled: props.refreshing }]}>
          连接暂时不可用。请刷新后核对最新内容。
        </Banner>
        <ScrollView ref={scroll} style={styles.contentScroll} contentContainerStyle={styles.scrollContent} keyboardShouldPersistTaps="handled">
          <View style={[styles.content, { paddingHorizontal: wide ? 28 : 16, paddingTop: wide ? 24 : 16 }]}>
            {props.children}
          </View>
        </ScrollView>
        {!wide ? <BottomNavigation.Bar navigationState={{ index: tabIndex >= 0 ? tabIndex : 4, routes: navigation }}
          getAccessibilityLabel={({ route: item }) => item.title}
          onTabPress={({ route: next }) => navigate(next.key)}
          activeColor={theme.colors.onSurface} inactiveColor={theme.colors.onSurfaceVariant}
          shifting={false} labeled safeAreaInsets={{ bottom: insets.bottom, left: insets.left, right: insets.right }}
          style={[styles.bottomBar, border, { backgroundColor: theme.colors.surface }]} /> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  frame: { flex: 1, flexDirection: 'row', minHeight: 0 },
  sidebar: { width: 232, paddingHorizontal: 10, paddingTop: 22, paddingBottom: 12, borderRightWidth: 1 },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 14, marginBottom: 24 },
  household: { marginHorizontal: 8, padding: 12, borderRadius: 10, gap: 3, marginBottom: 18 },
  navScroll: { flex: 1 },
  navContent: { paddingBottom: 16 },
  groupLabel: { marginHorizontal: 18, marginBottom: 8, marginTop: 4 },
  drawerItem: { borderRadius: 8, marginHorizontal: 0, marginVertical: 2 },
  divider: { marginVertical: 16, marginHorizontal: 8 },
  main: { flex: 1, minWidth: 0, minHeight: 0 },
  header: { minHeight: 64, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, borderBottomWidth: 1 },
  headerCopy: { flex: 1, minWidth: 0, gap: 2 },
  headerActions: { flexDirection: 'row', alignItems: 'center', gap: 2 },
  iconButton: { margin: 0 },
  button: { borderRadius: 8 },
  buttonContent: { minHeight: 42 },
  menu: { borderRadius: 12, minWidth: 200 },
  contentScroll: { flex: 1 },
  scrollContent: { flexGrow: 1, alignItems: 'center' },
  content: { width: '100%', maxWidth: 1200, paddingBottom: 28 },
  bottomBar: { borderTopWidth: 1 },
});
