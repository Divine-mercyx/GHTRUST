import {
  Montserrat_400Regular,
  Montserrat_500Medium,
  Montserrat_600SemiBold,
  Montserrat_700Bold,
  Montserrat_800ExtraBold,
  useFonts,
} from '@expo-google-fonts/montserrat';
import { focusManager, QueryClientProvider } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useState } from 'react';
import { AppState, Platform } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { SessionProvider, useSession } from '@/auth/session';
import { BlockingScreen } from '@/components/BlockingScreen';
import { makeQueryClient, useAppConfig } from '@/lib/queries';
import { hideSplash, holdSplash } from '@/lib/splash';
import { colors } from '@/theme/tokens';

holdSplash();

// Expo Router renders this for any render error below the root layout.
export { CrashScreen as ErrorBoundary } from '@/components/CrashScreen';

// Refetch stale data when the app returns to the foreground.
if (Platform.OS !== 'web') {
  AppState.addEventListener('change', (state) => focusManager.setFocused(state === 'active'));
}

export default function RootLayout() {
  const [queryClient] = useState(makeQueryClient);
  const [fontsLoaded, fontError] = useFonts({
    Montserrat_400Regular,
    Montserrat_500Medium,
    Montserrat_600SemiBold,
    Montserrat_700Bold,
    Montserrat_800ExtraBold,
  });

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <QueryClientProvider client={queryClient}>
          <SessionProvider>
            <StatusBar style="dark" />
            <Shell ready={fontsLoaded || !!fontError} />
          </SessionProvider>
        </QueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

function Shell({ ready }: { ready: boolean }) {
  const { status, gate, clearGate } = useSession();
  const config = useAppConfig();
  const booting = !ready || status === 'loading';

  useEffect(() => {
    if (!booting) hideSplash();
  }, [booting]);

  // Never leave the splash up if start-up stalls (e.g. slow secure storage).
  useEffect(() => {
    const failsafe = setTimeout(hideSplash, 6000);
    return () => clearTimeout(failsafe);
  }, []);

  if (booting) return null;

  if (config.data?.update_required || gate?.code === 'APP_UPDATE_REQUIRED') {
    return <BlockingScreen kind="update" platform={config.data?.platform} />;
  }
  if (config.data?.maintenance.enabled || gate?.code === 'MAINTENANCE_MODE') {
    return (
      <BlockingScreen
        kind="maintenance"
        message={config.data?.maintenance.message}
        onRetry={() => {
          clearGate();
          config.refetch();
        }}
      />
    );
  }

  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: colors.surface },
        animation: 'fade',
      }}>
      <Stack.Protected guard={status === 'signedIn'}>
        <Stack.Screen name="(app)" />
      </Stack.Protected>
      <Stack.Protected guard={status === 'locked'}>
        <Stack.Screen name="unlock" />
      </Stack.Protected>
      <Stack.Protected guard={status === 'signedOut'}>
        <Stack.Screen name="(auth)" />
      </Stack.Protected>
    </Stack>
  );
}
