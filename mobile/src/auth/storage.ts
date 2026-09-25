/**
 * Refresh token + install ID storage.
 *
 * Native: Keychain (iOS, this-device-only) / Keystore-backed storage (Android)
 * via expo-secure-store. Web (dev previews only): memory, never localStorage —
 * a refresh token is a 30-day credential.
 */
import * as Crypto from 'expo-crypto';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

const REFRESH_KEY = 'ghtrust.refresh_token';
const DEVICE_KEY = 'ghtrust.device_id';
const NAME_KEY = 'ghtrust.first_name';

const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

const memory = new Map<string, string>();
const native = Platform.OS !== 'web';

async function get(key: string): Promise<string | null> {
  if (!native) return memory.get(key) ?? null;
  try {
    return await SecureStore.getItemAsync(key, OPTIONS);
  } catch {
    return null; // e.g. keychain item from a restored backup on another device
  }
}

async function set(key: string, value: string): Promise<void> {
  if (!native) {
    memory.set(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value, OPTIONS);
}

async function remove(key: string): Promise<void> {
  if (!native) {
    memory.delete(key);
    return;
  }
  await SecureStore.deleteItemAsync(key, OPTIONS).catch(() => undefined);
}

export const tokenStore = {
  getRefresh: () => get(REFRESH_KEY),
  setRefresh: (token: string) => set(REFRESH_KEY, token),
  clear: async () => {
    await remove(REFRESH_KEY);
    await remove(NAME_KEY);
  },
  /** First name for the "Welcome back" unlock screen (not sensitive). */
  getName: () => get(NAME_KEY),
  setName: (name: string) => set(NAME_KEY, name),
};

let deviceId: string | null = null;

/** Stable per-install ID: signing in again on this device replaces its old session. */
export async function getDeviceId(): Promise<string> {
  if (deviceId) return deviceId;
  deviceId = (await get(DEVICE_KEY)) ?? Crypto.randomUUID();
  await set(DEVICE_KEY, deviceId);
  return deviceId;
}
