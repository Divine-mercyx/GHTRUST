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
const INTRO_KEY = 'ghtrust.intro_seen';
const DEVICE_TOKEN_KEY = 'ghtrust.device_token';
const BIOMETRIC_KEY = 'ghtrust.biometric';
const PUSH_OFF_KEY = 'ghtrust.push_off';
const LOCK_AFTER_KEY = 'ghtrust.lock_after_ms';

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
  /** End the session. The name stays for "Welcome back" while the phone is still trusted. */
  clear: async () => {
    await remove(REFRESH_KEY);
  },
  /** First name for the "Welcome back" unlock screen (not sensitive). */
  getName: () => get(NAME_KEY),
  setName: (name: string) => set(NAME_KEY, name),

  /**
   * Proof this phone is trusted: with it, the customer signs back in here with their PIN
   * instead of an SMS code. Survives sign-out; only "Not you?" (forget) removes it.
   */
  getDeviceToken: () => get(DEVICE_TOKEN_KEY),
  setDeviceToken: (token: string) => set(DEVICE_TOKEN_KEY, token),
  forgetDevice: async () => {
    await remove(DEVICE_TOKEN_KEY);
    await remove(NAME_KEY);
    await remove(BIOMETRIC_KEY);
    await remove(LOCK_AFTER_KEY);
  },

  /** The customer chose to unlock with Face ID / fingerprint on this phone. */
  getBiometric: async () => (await get(BIOMETRIC_KEY)) === '1',
  setBiometric: (on: boolean) => (on ? set(BIOMETRIC_KEY, '1') : remove(BIOMETRIC_KEY)),

  /** How long the app may be away before it locks (see lockPolicy.ts); raw stored value. */
  getLockAfter: () => get(LOCK_AFTER_KEY),
  setLockAfter: (ms: number) => set(LOCK_AFTER_KEY, String(ms)),
};

/** The customer switched push notifications off in the app (the OS permission may still be on). */
export const pushOptOut = {
  get: async () => (await get(PUSH_OFF_KEY)) === '1',
  set: (off: boolean) => (off ? set(PUSH_OFF_KEY, '1') : remove(PUSH_OFF_KEY)),
};

/** Whether this install has seen the first-launch intro (kept across sign-outs). */
export const introFlag = {
  get: async () => (await get(INTRO_KEY)) === '1',
  set: () => set(INTRO_KEY, '1'),
};

let deviceId: string | null = null;

/** Stable per-install ID: signing in again on this device replaces its old session. */
export async function getDeviceId(): Promise<string> {
  if (deviceId) return deviceId;
  deviceId = (await get(DEVICE_KEY)) ?? Crypto.randomUUID();
  await set(DEVICE_KEY, deviceId);
  return deviceId;
}
