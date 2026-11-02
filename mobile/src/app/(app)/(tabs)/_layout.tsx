import { Tabs } from 'expo-router';
import { useMemo } from 'react';

import { TabBar } from '@/components/TabBar';
import { useFeatures, useMyInvestments } from '@/lib/queries';
import { colors } from '@/theme/tokens';

export default function TabsLayout() {
  const { wallet, investments } = useFeatures();
  const mine = useMyInvestments();
  // The Wallet tab only exists with the wallet switched on. Invest likewise (no "opens soon"
  // placeholder tab), except for customers who already hold investments.
  const invest = investments || (mine.data?.length ?? 0) > 0;
  const hidden = useMemo(
    () => new Set([...(wallet ? [] : ['wallet']), ...(invest ? [] : ['invest'])]),
    [wallet, invest],
  );
  return (
    <Tabs
      tabBar={(props) => <TabBar {...props} hidden={hidden} />}
      screenOptions={{
        headerShown: false,
        // A short slide between tabs.
        animation: 'shift',
        sceneStyle: { backgroundColor: colors.surface },
      }}>
      <Tabs.Screen name="index" options={{ title: 'Home' }} />
      <Tabs.Screen name="loans" options={{ title: 'Loans' }} />
      <Tabs.Screen name="invest" options={{ title: 'Invest', href: invest ? undefined : null }} />
      <Tabs.Screen name="wallet" options={{ title: 'Wallet', href: wallet ? undefined : null }} />
      <Tabs.Screen name="profile" options={{ title: 'Profile' }} />
    </Tabs>
  );
}
