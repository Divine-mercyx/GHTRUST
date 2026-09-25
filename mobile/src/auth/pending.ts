/**
 * The OTP step in progress. Kept in memory, not in route params, so a BVN or
 * phone number never ends up in a URL, deep link or navigation log.
 */
type Common = {
  phoneMasked: string;
  expiresIn: number;
  /** Test mode only (dev build + backend in development with mocked SMS). */
  devCode?: string | null;
};

export type PendingOtp = ({ mode: 'register'; bvn: string } | { mode: 'login'; phone: string }) & Common;

/** The server only echoes codes in local development; the app only uses them in dev builds. */
export const testModeCode = (code: string | null | undefined) => (__DEV__ && code ? code : null);

let pending: PendingOtp | null = null;

export const pendingOtp = {
  get: () => pending,
  set: (value: PendingOtp) => {
    pending = value;
  },
  clear: () => {
    pending = null;
  },
};
