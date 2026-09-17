import { useEffect, useMemo } from 'react';
import { Stack, usePathname, useSegments } from 'expo-router';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { PaperProvider } from 'react-native-paper';
import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { HouseholdProvider, useHousehold } from '../lib/household';
import { makeTheme, type AppTheme } from '../ui/theme';
import { isTVRoute } from '../lib/tv';
function Appearance({ theme }: { theme: AppTheme }) {
  useEffect(() => {
    if (typeof document === 'undefined') return;
    // Native has no DOM. On web cover overscroll, browser form controls and the
    // area around the router; identity changes/logout use the default theme.
    const nodes = [document.documentElement, document.body];
    for (const node of nodes) {
      node.style.backgroundColor = theme.colors.background;
      node.style.colorScheme = theme.dark ? 'dark' : 'light';
    }
    return () => {
      for (const node of nodes) { node.style.backgroundColor = '#ffffff'; node.style.colorScheme = 'light'; }
    };
  }, [theme]);
  return <PaperProvider theme={theme} settings={{icon:props=><MaterialCommunityIcons {...props} name={props.name as any} />}}><Stack screenOptions={{headerShown:false, contentStyle:{backgroundColor:theme.colors.background}}}/></PaperProvider>;
}
function MemberAppearance() {
  const { user, preferences } = useHousehold();
  const colorMode = user?.role === 'member' ? preferences.colorMode : 'light';
  const density = user?.role === 'member' ? preferences.density : 'comfortable';
  const theme = useMemo(() => makeTheme(colorMode, density), [colorMode, density]);
  return <Appearance theme={theme} />;
}
function TVAppearance() {
  const theme = useMemo(() => makeTheme(), []);
  return <Appearance theme={theme} />;
}
export default function Layout() {
  const pathname = usePathname(), segments = useSegments();
  // The location check also covers the first browser render before route hydration.
  // A television must never mount the member provider, even for one effect turn.
  const television = segments[0] === 'tv' || isTVRoute(pathname)
    || (typeof window !== 'undefined' && isTVRoute(window.location.pathname));
  return <SafeAreaProvider>{television ? <TVAppearance /> : <HouseholdProvider><MemberAppearance /></HouseholdProvider>}</SafeAreaProvider>;
}
