import { useLocalSearchParams } from 'expo-router';
import HouseholdApp from '../screens/HouseholdApp';
export default function Screen() { const {section}=useLocalSearchParams<{section:string}>(); return <HouseholdApp screen={section}/>; }
