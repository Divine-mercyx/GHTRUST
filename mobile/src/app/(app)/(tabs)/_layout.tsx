import { Tabs } from 'expo-router';
import { useMemo } from 'react';

import { TabBar } from '@/components/TabBar';
import { useFeatures } from '@/lib/queries';
import { colors } from '@/theme/tokens';

export default function TabsLayout() {
  const { wallet } = useFeatures();
  // The Wallet tab only exists with the wallet switched on.
  const hidden = useMemo(() => new Set(wallet ? [] : ['wallet']), [wallet]);
  return (
    <Tabs
      tabBar={(props) => <TabBar {...props} hidden={hidden} />}
      screenOptions={{
        headerShown: false,
        sceneStyle: { backgroundColor: colors.surface },
      }}>
      <Tabs.Screen name="index" options={{ title: 'Home' }} />
      <Tabs.Screen name="loans" options={{ title: 'Loans' }} />
      <Tabs.Screen name="invest" options={{ title: 'Invest' }} />
      <Tabs.Screen name="wallet" options={{ title: 'Wallet', href: wallet ? undefined : null }} />
      <Tabs.Screen name="profile" options={{ title: 'Profile' }} />
    </Tabs>
  );
}
