/**
 * Splash screen control that is safe in every runtime.
 *
 * Expo Go ships its own splash handling: `setOptions` is unsupported there and
 * logs a warning, so it only runs in development/production builds. Every call
 * is fire-and-forget: a splash failure must never block app start-up.
 */
import Constants, { ExecutionEnvironment } from 'expo-constants';
import * as SplashScreen from 'expo-splash-screen';
import { Platform } from 'react-native';

const inExpoGo = Constants.executionEnvironment === ExecutionEnvironment.StoreClient;
const native = Platform.OS === 'ios' || Platform.OS === 'android';

let hidden = false;

/** Call once at module load: keep the splash up until the first real screen is ready. */
export function holdSplash() {
  if (!native) return;
  SplashScreen.preventAutoHideAsync().catch(() => undefined);
  if (!inExpoGo) SplashScreen.setOptions({ duration: 250, fade: true });
}

export function hideSplash() {
  if (!native || hidden) return;
  hidden = true;
  SplashScreen.hideAsync().catch(() => undefined);
}
