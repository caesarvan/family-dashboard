import { Stack } from 'expo-router';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { PaperProvider } from 'react-native-paper';
import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { HouseholdProvider } from '../lib/household';
import { makeTheme } from '../ui/theme';
function Appearance() {
  return <PaperProvider theme={makeTheme()} settings={{icon:props=><MaterialCommunityIcons {...props} name={props.name as any} />}}><Stack screenOptions={{headerShown:false}}/></PaperProvider>;
}
export default function Layout() { return <SafeAreaProvider><HouseholdProvider><Appearance/></HouseholdProvider></SafeAreaProvider>; }
