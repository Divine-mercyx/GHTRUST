/**
 * App lock: a saved session only opens after the device owner proves
 * presence (Face ID / fingerprint, or the device passcode as fallback).
 */
import * as LocalAuthentication from 'expo-local-authentication';
import { Platform } from 'react-native';

/** Background time after which the app locks again (matches the staff portal). */
export const RELOCK_AFTER_MS = 5 * 60 * 1000;

export type LockKind = 'face' | 'fingerprint' | 'passcode' | 'none';

export async function lockKind(): Promise<LockKind> {
  if (Platform.OS === 'web') return 'none';
  try {
    const level = await LocalAuthentication.getEnrolledLevelAsync();
    if (level === LocalAuthentication.SecurityLevel.NONE) return 'none';
    if (level === LocalAuthentication.SecurityLevel.SECRET) return 'passcode';
    const types = await LocalAuthentication.supportedAuthenticationTypesAsync();
    return types.includes(LocalAuthentication.AuthenticationType.FACIAL_RECOGNITION) ? 'face' : 'fingerprint';
  } catch {
    return 'none';
  }
}

export async function unlock(): Promise<boolean> {
  const result = await LocalAuthentication.authenticateAsync({
    promptMessage: 'Unlock GH Trust',
    cancelLabel: 'Cancel',
    fallbackLabel: 'Use passcode',
  });
  return result.success;
}
