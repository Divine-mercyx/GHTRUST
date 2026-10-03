import { useQuery } from '@tanstack/react-query';
import { router, Stack } from 'expo-router';
import { useEffect, useRef } from 'react';

import { approvals } from '@/api/endpoints';
import { setupFlow, usePinReset, useSetupFlow } from '@/lib/flags';
import { setMonitoringUser } from '@/lib/monitoring';
import { usePushNotifications } from '@/lib/usePushNotifications';
import { useMe } from '@/lib/queries';
import { colors, font } from '@/theme/tokens';

/** While the app is open, check for sign-ins on new phones waiting for this one to approve. */
const APPROVAL_POLL_MS = 5000;

export default function AppLayout() {
  const me = useMe();
  const setupActive = useSetupFlow();
  const resetting = usePinReset();
  const needsPin = me.data ? !me.data.login_pin_set : false;
  const needsSetup = setupActive || needsPin || resetting;
  // Terms / Privacy come first: nothing else in the app until they're accepted.
  const needsConsent = (me.data?.legal_pending?.length ?? 0) > 0;

  // Once started, setup stays on screen until the customer finishes its optional steps.
  useEffect(() => {
    if (needsPin || resetting) setupFlow.start();
  }, [needsPin, resetting]);

  const ready = !needsSetup && !needsConsent;
  usePendingApprovals(ready);
  const customerId = me.data?.id ?? null;
  useEffect(() => {
    setMonitoringUser(customerId);
    return () => setMonitoringUser(null);
  }, [customerId]);
  usePushNotifications(ready);

  return (
    <Stack
      screenOptions={{
        headerShadowVisible: false,
        headerStyle: { backgroundColor: colors.surface },
        headerTintColor: colors.navy,
        headerTitleStyle: { fontFamily: font.bold, fontSize: 17 },
        headerBackButtonDisplayMode: 'minimal',
        contentStyle: { backgroundColor: colors.surface },
      }}>
      <Stack.Protected guard={needsConsent}>
        <Stack.Screen name="legal-consent" options={{ headerShown: false, gestureEnabled: false, animation: 'fade' }} />
      </Stack.Protected>
      <Stack.Protected guard={needsSetup && !needsConsent}>
        <Stack.Screen name="security-setup" options={{ headerShown: false, gestureEnabled: false, animation: 'fade' }} />
      </Stack.Protected>
      <Stack.Protected guard={ready}>
        {/* title: what VoiceOver/TalkBack say on the back button of screens above ("Home, back"). */}
        <Stack.Screen name="(tabs)" options={{ headerShown: false, title: 'Home' }} />
        <Stack.Screen name="apply/index" options={{ title: 'Choose a loan' }} />
        <Stack.Screen name="apply/[id]" options={{ title: 'Loan application' }} />
        <Stack.Screen name="applications/[id]" options={{ title: 'Application' }} />
        <Stack.Screen name="applications/[id]/offer" options={{ title: 'Your loan offer' }} />
        <Stack.Screen name="loans/[id]" options={{ title: 'Loan' }} />
        <Stack.Screen name="devices" options={{ title: 'Signed-in devices' }} />
        <Stack.Screen name="edit-contact" options={{ title: 'Contact details' }} />
        <Stack.Screen name="security" options={{ title: 'Security' }} />
        <Stack.Screen name="pin/[action]" options={{ title: '', presentation: 'modal' }} />
        <Stack.Screen
          name="approve-device/[id]"
          options={{ title: '', presentation: 'fullScreenModal', gestureEnabled: false, headerShown: false }}
        />
        <Stack.Screen
          name="repay/[id]"
          options={{ title: 'Make a repayment', presentation: 'formSheet', sheetAllowedDetents: [0.75, 1], sheetGrabberVisible: true }}
        />
        <Stack.Screen
          name="fund"
          options={{ title: 'Add money', presentation: 'formSheet', sheetAllowedDetents: [0.75, 1], sheetGrabberVisible: true }}
        />
        <Stack.Screen name="withdraw" options={{ title: 'Withdraw' }} />
        <Stack.Screen name="payout-account" options={{ title: 'Bank account' }} />
        <Stack.Screen name="transactions/index" options={{ title: 'Transactions' }} />
        <Stack.Screen name="transactions/[id]" options={{ title: 'Receipt' }} />
        <Stack.Screen name="notifications" options={{ title: 'Notifications' }} />
        <Stack.Screen name="support/index" options={{ title: 'Help & support' }} />
        <Stack.Screen name="support/new" options={{ title: 'Report a problem' }} />
        <Stack.Screen name="support/[id]" options={{ title: 'Your request' }} />
        <Stack.Screen name="delete-account" options={{ title: 'Delete account' }} />
      </Stack.Protected>
    </Stack>
  );
}

function usePendingApprovals(enabled: boolean) {
  const shown = useRef(new Set<string>());
  const pending = useQuery({
    queryKey: ['approvals'],
    queryFn: approvals.pending,
    enabled,
    refetchInterval: APPROVAL_POLL_MS,
    staleTime: 0,
    retry: false,
  });
  useEffect(() => {
    const next = pending.data?.find((a) => !shown.current.has(a.id));
    if (!next) return;
    shown.current.add(next.id);
    router.push({ pathname: '/approve-device/[id]', params: { id: next.id } });
  }, [pending.data]);
}
