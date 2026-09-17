import { Stack, usePathname, useSegments } from 'expo-router';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { PaperProvider } from 'react-native-paper';
import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { HouseholdProvider } from '../lib/household';
import { makeTheme } from '../ui/theme';
import { isTVRoute } from '../lib/tv';
function Appearance() {
  return <PaperProvider theme={makeTheme()} settings={{icon:props=><MaterialCommunityIcons {...props} name={props.name as any} />}}><Stack screenOptions={{headerShown:false}}/></PaperProvider>;
}
export default function Layout() {
  const pathname = usePathname(), segments = useSegments();
  // The location check also covers the first browser render before route hydration.
  // A television must never mount the member provider, even for one effect turn.
  const television = segments[0] === 'tv' || isTVRoute(pathname)
    || (typeof window !== 'undefined' && isTVRoute(window.location.pathname));
  return <SafeAreaProvider>{television ? <Appearance /> : <HouseholdProvider><Appearance /></HouseholdProvider>}</SafeAreaProvider>;
}
