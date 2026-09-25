import { Stack } from 'expo-router';

import { colors, font } from '@/theme/tokens';

export default function AppLayout() {
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
      {/* title: what VoiceOver/TalkBack say on the back button of screens above ("Home, back"). */}
      <Stack.Screen name="(tabs)" options={{ headerShown: false, title: 'Home' }} />
      <Stack.Screen name="apply/index" options={{ title: 'Choose a loan' }} />
      <Stack.Screen name="apply/[id]" options={{ title: 'Loan application' }} />
      <Stack.Screen name="applications/[id]" options={{ title: 'Application' }} />
      <Stack.Screen name="loans/[id]" options={{ title: 'Loan' }} />
      <Stack.Screen name="devices" options={{ title: 'Signed-in devices' }} />
      <Stack.Screen
        name="repay/[id]"
        options={{ title: 'Make a repayment', presentation: 'formSheet', sheetAllowedDetents: [0.75, 1], sheetGrabberVisible: true }}
      />
      <Stack.Screen
        name="fund"
        options={{ title: 'Add money', presentation: 'formSheet', sheetAllowedDetents: [0.75, 1], sheetGrabberVisible: true }}
      />
    </Stack>
  );
}
