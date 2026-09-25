import Ionicons from '@expo/vector-icons/Ionicons';
import { Tabs } from 'expo-router';
import { Platform, type ColorValue } from 'react-native';

import { useFeatures } from '@/lib/queries';
import { colors, font } from '@/theme/tokens';

type IconName = keyof typeof Ionicons.glyphMap;

function icon(name: IconName, active: IconName) {
  return function TabBarIcon({ color, focused }: { color: ColorValue; focused: boolean }) {
    return <Ionicons name={focused ? active : name} size={23} color={color as string} />;
  };
}

export default function TabsLayout() {
  const { wallet } = useFeatures();
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.navy,
        tabBarInactiveTintColor: colors.textFaint,
        tabBarLabelStyle: { fontFamily: font.semibold, fontSize: 11 },
        tabBarStyle: {
          backgroundColor: colors.card,
          borderTopColor: colors.border,
          ...(Platform.OS === 'android' ? { height: 64, paddingBottom: 8, paddingTop: 6 } : null),
        },
        sceneStyle: { backgroundColor: colors.surface },
      }}>
      <Tabs.Screen name="index" options={{ title: 'Home', tabBarIcon: icon('home-outline', 'home') }} />
      <Tabs.Screen name="loans" options={{ title: 'Loans', tabBarIcon: icon('document-text-outline', 'document-text') }} />
      <Tabs.Screen
        name="wallet"
        options={{ title: 'Wallet', href: wallet ? undefined : null, tabBarIcon: icon('wallet-outline', 'wallet') }}
      />
      <Tabs.Screen name="profile" options={{ title: 'Profile', tabBarIcon: icon('person-circle-outline', 'person-circle') }} />
    </Tabs>
  );
}
