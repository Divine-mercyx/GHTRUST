/**
 * Push notifications: permission, the Expo push token, and telling the API where to
 * send this phone's notifications.
 *
 * Push needs a development build (not Expo Go) on a real phone and the EAS project ID
 * (written to app.json by `eas init`); without them it's switched off quietly and the
 * in-app inbox still works.
 */
import Constants from 'expo-constants';
import * as Device from 'expo-device';
import { Platform } from 'react-native';

import { withLockPaused } from '@/auth/lockPolicy';

import { notifications } from '@/api/endpoints';
import { pushOptOut } from '@/auth/storage';
import { Notifications } from '@/lib/notificationsModule';
import { colors } from '@/theme/tokens';

export type PushState = 'on' | 'off' | 'blocked' | 'unsupported';

const projectId: string | undefined =
  Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId ?? undefined;

export const pushSupported = !!Notifications && Device.isDevice && !!projectId;

if (Notifications) {
  // Show notifications that arrive while the app is open, too.
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
    }),
  });
}

async function ensureChannel() {
  if (!Notifications || Platform.OS !== 'android') return;
  // The server sends on channelId "default".
  await Notifications.setNotificationChannelAsync('default', {
    name: 'Account updates',
    importance: Notifications.AndroidImportance.HIGH,
    lightColor: colors.cyan,
  });
}

async function registerToken(): Promise<void> {
  if (!Notifications) return;
  await ensureChannel();
  const { data } = await Notifications.getExpoPushTokenAsync({ projectId });
  await notifications.setPushToken(data);
}

/** Current state, without asking the customer anything. */
export async function pushState(): Promise<PushState> {
  if (!pushSupported || !Notifications) return 'unsupported';
  const { status, canAskAgain } = await Notifications.getPermissionsAsync();
  if (status !== 'granted') return canAskAgain ? 'off' : 'blocked';
  return (await pushOptOut.get()) ? 'off' : 'on';
}

/** Whether to offer notifications during setup (never asked, and not turned off before). */
export async function shouldOfferPush(): Promise<boolean> {
  if (!pushSupported || !Notifications) return false;
  const { status, canAskAgain } = await Notifications.getPermissionsAsync();
  return status !== 'granted' && canAskAgain;
}

/** Ask for permission if needed and start sending this phone's notifications. */
export async function enablePush(): Promise<PushState> {
  if (!pushSupported || !Notifications) return 'unsupported';
  await ensureChannel(); // Android 13+ shows the permission prompt once a channel exists
  let { status, canAskAgain } = await Notifications.getPermissionsAsync();
  const notifications = Notifications; // narrowed above; the closure below can't see that
  if (status !== 'granted' && canAskAgain) {
    ({ status, canAskAgain } = await withLockPaused(() => notifications.requestPermissionsAsync()));
  }
  if (status !== 'granted') return canAskAgain ? 'off' : 'blocked';
  await pushOptOut.set(false);
  await registerToken();
  return 'on';
}

/** Stop pushes to this phone (the inbox keeps filling). */
export async function disablePush(): Promise<void> {
  await pushOptOut.set(true);
  await notifications.removePushToken().catch(() => undefined);
}

/**
 * On each app start while signed in: tokens can change (reinstall, restore), and a new
 * sign-in is a new session, so re-send it. Silent: never prompts.
 */
export async function syncPushToken(): Promise<void> {
  if ((await pushState()) !== 'on') return;
  try {
    await registerToken();
  } catch {
    // Offline or the push service is unavailable: try again next start.
  }
}
