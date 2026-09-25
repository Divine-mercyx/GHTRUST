/** Every API error has `{detail, code, errors, request_id}` (docs/mobile-app-handoff.md → Errors). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly errors: string[] = [],
    readonly requestId?: string,
    readonly retryAfter?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** Codes after which the stored session is useless: go back to sign-in. */
export const SESSION_ENDED = new Set([
  'SESSION_REVOKED',
  'ACCOUNT_INACTIVE',
  'REFRESH_TOKEN_INVALID',
  'REFRESH_TOKEN_REUSED',
]);

/**
 * Customer wording for every code the API can return. The server's own `detail`
 * text is written for developers and is never shown: anything not listed here
 * falls back to wording by HTTP status, then to the caller's fallback.
 */
const COPY: Record<string, string> = {
  // Connectivity (client-side codes)
  NETWORK: "We couldn't connect to GH Trust. Check your internet connection and try again.",
  TIMEOUT: 'This is taking longer than usual. Check your connection and try again.',
  // Sign-up / sign-in
  OTP_INVALID: "That code isn't right. Check the SMS and try again.",
  OTP_EXPIRED: 'That code has expired. Request a new one.',
  OTP_ATTEMPTS_EXCEEDED: 'Too many wrong codes. Request a new one.',
  SMS_UNAVAILABLE: "We couldn't send your code right now. Please try again in a few minutes.",
  ACCOUNT_EXISTS: 'You already have a GH Trust account. Sign in with your phone number instead.',
  ACCOUNT_RESTRICTED: "We can't open an account for you in the app. Please visit a GH Trust branch.",
  ACCOUNT_INACTIVE: 'Your account is not active. Please contact GH Trust.',
  BVN_NOT_FOUND: "We couldn't find that BVN. Check the 11 digits and try again.",
  KYC_UNAVAILABLE: "We couldn't verify your BVN right now. Please try again shortly.",
  TOKEN_INVALID: 'Please sign in again to continue.',
  SESSION_REVOKED: 'You were signed out. Please sign in again.',
  SESSION_IDLE_TIMEOUT: 'You were signed out after a period of inactivity. Please sign in again.',
  REFRESH_TOKEN_INVALID: 'Please sign in again to continue.',
  REFRESH_TOKEN_REUSED: 'For your security you were signed out. Please sign in again.',
  PERMISSION_DENIED: "This isn't available on your account.",
  // Platform
  RATE_LIMITED: 'Too many attempts. Please wait a moment and try again.',
  APP_UPDATE_REQUIRED: 'Please update GH Trust to continue.',
  MAINTENANCE_MODE: 'GH Trust is undergoing maintenance. Please try again shortly.',
  IDEMPOTENCY_IN_PROGRESS: 'Your previous request is still being processed. Please wait a moment.',
  IDEMPOTENCY_KEY_REUSED: 'Something went wrong with that request. Please try again.',
  // Money
  INSUFFICIENT_FUNDS: "Your wallet balance isn't enough for this payment. Add money and try again.",
  PAYOUT_ACCOUNT_REQUIRED: 'Add a bank account for payouts first.',
  PAYMENT_PROVIDER_ERROR: 'Our payment service is temporarily unavailable. Please try again shortly.',
  BANK_ACCOUNT_UNVERIFIED: "We couldn't verify this account. Check the bank and account number and try again.",
  LOAN_NOT_REPAYABLE: "This loan can't take repayments right now. Please contact GH Trust.",
  // Loan applications
  APPLICATION_INCOMPLETE: 'Your application is missing some details. Check each step and try again.',
  APPLICATION_NOT_EDITABLE: "This application can't be changed any more. Only documents we've asked you to replace can be uploaded.",
  INVALID_STATUS_TRANSITION: "This application can't be changed right now.",
  DOCUMENT_TYPE_NOT_ALLOWED: "This document isn't needed for your application.",
  DOCUMENT_INVALID: "We couldn't read that file. Upload a clear PDF, JPG or PNG under 10 MB.",
  DOCUMENTS_NOT_VERIFIED: 'Your documents are still being reviewed.',
  // Generic codes the server uses when nothing more specific applies
  PAYLOAD_TOO_LARGE: 'That file is too large. Please use one under 10 MB.',
  UNSUPPORTED_MEDIA_TYPE: 'That file type isn’t supported. Use a PDF, JPG or PNG.',
  NOT_IMPLEMENTED: "This isn't available yet.",
};

function byStatus(status: number): string | null {
  if (status === 0) return COPY.NETWORK;
  if (status === 400 || status === 422) return "Some of the details aren't right. Please check them and try again.";
  if (status === 401) return COPY.TOKEN_INVALID;
  if (status === 403) return COPY.PERMISSION_DENIED;
  if (status === 404) return "We couldn't find that. It may have changed. Go back and try again.";
  if (status === 409) return 'This has changed since you opened it. Go back and try again.';
  if (status === 413) return COPY.PAYLOAD_TOO_LARGE;
  if (status === 415) return COPY.UNSUPPORTED_MEDIA_TYPE;
  if (status === 429) return COPY.RATE_LIMITED;
  if (status === 501) return COPY.NOT_IMPLEMENTED;
  if (status >= 500) return 'Something went wrong on our side. Please try again in a moment.';
  return null;
}

/**
 * Developer diagnostics go to the Metro terminal only (console.log, not warn/error,
 * which would pop LogBox toasts over the app in development).
 */
function logForDevelopers(error: unknown) {
  if (!__DEV__) return;
  if (error instanceof ApiError) {
    console.log(`[api] ${error.status} ${error.code}: ${error.message}${error.requestId ? ` (request ${error.requestId})` : ''}`);
  } else if (error) {
    console.log('[app] error', error);
  }
}

/** A message that is safe to show a customer, whatever went wrong. */
export function messageFor(error: unknown, fallback = 'Something went wrong. Please try again.'): string {
  logForDevelopers(error);
  if (!(error instanceof ApiError)) return fallback;
  return COPY[error.code] ?? byStatus(error.status) ?? fallback;
}
