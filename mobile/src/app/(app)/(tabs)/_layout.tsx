import Ionicons from '@expo/vector-icons/Ionicons';
import { Tabs } from 'expo-router';
import { type ColorValue } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

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
  // Size the bar ourselves: the default 49pt clips Montserrat's labels, and a fixed height
  // ignores the home indicator / Android gesture bar under edge-to-edge.
  const { bottom } = useSafeAreaInsets();
  const padBottom = Math.max(bottom, 8);
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
          // 54pt of content (icon + label) above the inset.
          height: 4 + 54 + padBottom,
          paddingTop: 4,
          paddingBottom: padBottom,
        },
        sceneStyle: { backgroundColor: colors.surface },
      }}>
      <Tabs.Screen name="index" options={{ title: 'Home', tabBarIcon: icon('home-outline', 'home') }} />
      <Tabs.Screen name="loans" options={{ title: 'Loans', tabBarIcon: icon('document-text-outline', 'document-text') }} />
      <Tabs.Screen name="invest" options={{ title: 'Invest', tabBarIcon: icon('trending-up-outline', 'trending-up') }} />
      <Tabs.Screen
        name="wallet"
        options={{ title: 'Wallet', href: wallet ? undefined : null, tabBarIcon: icon('wallet-outline', 'wallet') }}
      />
      <Tabs.Screen name="profile" options={{ title: 'Profile', tabBarIcon: icon('person-circle-outline', 'person-circle') }} />
    </Tabs>
  );
}
