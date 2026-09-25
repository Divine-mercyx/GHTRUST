import Constants from 'expo-constants';
import { Platform } from 'react-native';

/**
 * API origin. Set EXPO_PUBLIC_API_URL for staging/production builds.
 *
 * In development it defaults to port 8000 on the machine running Metro, so a
 * phone on the same Wi-Fi (Expo Go) reaches your local backend without config.
 * The backend must listen on 0.0.0.0 for that (see mobile/README.md). Both the real
 * backend and backend/scripts/dev_server.py use port 8000.
 */
const DEV_PORT = 8000;

function devOrigin(): string {
  if (Platform.OS === 'web') return `http://localhost:${DEV_PORT}`;
  const host = Constants.expoConfig?.hostUri?.split(':')[0];
  if (host) return `http://${host}:${DEV_PORT}`;
  return Platform.OS === 'android' ? `http://10.0.2.2:${DEV_PORT}` : `http://localhost:${DEV_PORT}`;
}

export const API_ORIGIN = (process.env.EXPO_PUBLIC_API_URL || devOrigin()).replace(/\/+$/, '');
export const API_BASE = `${API_ORIGIN}/api/v1`;

export const APP_VERSION = Constants.expoConfig?.version ?? '1.0.0';

/** The version gate only knows ios/android; web previews report as android. */
export const GATE_PLATFORM: 'ios' | 'android' = Platform.OS === 'ios' ? 'ios' : 'android';
