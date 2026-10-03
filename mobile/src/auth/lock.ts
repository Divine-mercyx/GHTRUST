/**
 * App lock: a saved session only opens with the customer's 6-digit sign-in PIN, or with
 * Face ID / fingerprint if they chose to turn that on for this phone.
 */
import * as LocalAuthentication from 'expo-local-authentication';
import { Platform } from 'react-native';

// When the app locks again is the customer's choice: see lockPolicy.ts.

export type BiometricKind = 'face' | 'fingerprint';

/** What this phone offers for biometrics right now (hardware present and enrolled), if anything. */
export async function biometricKind(): Promise<BiometricKind | null> {
  if (Platform.OS === 'web') return null;
  try {
    const [hardware, enrolled] = await Promise.all([
      LocalAuthentication.hasHardwareAsync(),
      LocalAuthentication.isEnrolledAsync(),
    ]);
    if (!hardware || !enrolled) return null;
    const types = await LocalAuthentication.supportedAuthenticationTypesAsync();
    const face = types.includes(LocalAuthentication.AuthenticationType.FACIAL_RECOGNITION);
    const fingerprint = types.includes(LocalAuthentication.AuthenticationType.FINGERPRINT);
    if (Platform.OS === 'android') {
      // Android picks the sensor itself, and on phones with both it shows the fingerprint
      // prompt; many phones also report camera face unlock that apps can't use at all.
      // So only call it face unlock when the phone has nothing else.
      if (fingerprint) return 'fingerprint';
      return face ? 'face' : null;
    }
    if (face) return 'face';
    if (fingerprint) return 'fingerprint';
    return null;
  } catch {
    return null;
  }
}

export function biometricName(kind: BiometricKind): string {
  if (kind === 'face') return Platform.OS === 'ios' ? 'Face ID' : 'face unlock';
  return Platform.OS === 'ios' ? 'Touch ID' : 'fingerprint';
}

/** Ask for a biometric check only; the PIN is the fallback, never the phone's passcode. */
export async function checkBiometric(promptMessage: string): Promise<boolean> {
  try {
    const result = await LocalAuthentication.authenticateAsync({
      promptMessage,
      cancelLabel: 'Use PIN',
      disableDeviceFallback: true,
    });
    return result.success;
  } catch {
    return false;
  }
}
