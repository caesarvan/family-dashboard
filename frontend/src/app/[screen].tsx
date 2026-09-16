import { useLocalSearchParams } from 'expo-router';
import HouseholdApp from '../screens/HouseholdApp';
export default function Screen() { const {screen}=useLocalSearchParams<{screen:string}>(); return <HouseholdApp screen={screen}/>; }
