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
import { noteActivity } from '@/auth/lockPolicy';
import { PrivacyCover } from '@/components/PrivacyCover';
import { AnimatedSplash } from '@/components/AnimatedSplash';
import { BlockingScreen } from '@/components/BlockingScreen';
import { loadIntro, useIntroSeen } from '@/lib/intro';
import { initMonitoring, withMonitoring } from '@/lib/monitoring';
import { makeQueryClient, useAppConfig } from '@/lib/queries';
import { protectAppSwitcher } from '@/lib/useSecureScreen';
import { hideSplash, holdSplash } from '@/lib/splash';
import { colors, font } from '@/theme/tokens';

initMonitoring();
protectAppSwitcher();
holdSplash();
loadIntro();

// Expo Router renders this for any render error below the root layout.
export { CrashScreen as ErrorBoundary } from '@/components/CrashScreen';

// Refetch stale data when the app returns to the foreground.
if (Platform.OS !== 'web') {
  AppState.addEventListener('change', (state) => focusManager.setFocused(state === 'active'));
}

export default withMonitoring(RootLayout);

function RootLayout() {
  const [queryClient] = useState(makeQueryClient);
  const [fontsLoaded, fontError] = useFonts({
    Montserrat_400Regular,
    Montserrat_500Medium,
    Montserrat_600SemiBold,
    Montserrat_700Bold,
    Montserrat_800ExtraBold,
  });

  return (
    // Any touch counts as activity for the inactivity lock (lockPolicy.ts).
    <GestureHandlerRootView style={{ flex: 1 }} onTouchStart={noteActivity}>
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
  const introSeen = useIntroSeen();
  const [splashDone, setSplashDone] = useState(false);
  const booting = !ready || status === 'loading' || introSeen === null;

  // The animated splash starts on the native splash's last frame, so hand over as soon as
  // it can draw (fonts loaded); it then covers the rest of start-up itself.
  useEffect(() => {
    if (ready) hideSplash();
  }, [ready]);

  // Never leave the splash up if start-up stalls (e.g. slow secure storage).
  useEffect(() => {
    const failsafe = setTimeout(hideSplash, 6000);
    return () => clearTimeout(failsafe);
  }, []);

  return (
    <>
      {booting ? null : <Screens status={status} gate={gate} clearGate={clearGate} config={config} />}
      {ready && !splashDone ? <AnimatedSplash ready={!booting} onDone={() => setSplashDone(true)} /> : null}
      {status === 'signedIn' || status === 'locked' ? <PrivacyCover /> : null}
    </>
  );
}

function Screens({
  status,
  gate,
  clearGate,
  config,
}: Pick<ReturnType<typeof useSession>, 'status' | 'gate' | 'clearGate'> & { config: ReturnType<typeof useAppConfig> }) {
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
      {/* Terms and Privacy open from sign-up as well as from inside the app. */}
      <Stack.Screen
        name="legal/[slug]"
        options={{
          headerShown: true,
          animation: 'slide_from_right',
          headerShadowVisible: false,
          headerStyle: { backgroundColor: colors.surface },
          headerTintColor: colors.navy,
          headerTitleStyle: { fontFamily: font.bold, fontSize: 17 },
          headerBackButtonDisplayMode: 'minimal',
        }}
      />
    </Stack>
  );
}
