import { Platform } from 'react-native';

import { api, request } from './client';
import { GATE_PLATFORM, APP_VERSION } from './config';
import type {
  CardTopUp,
  Investment,
  InvestmentPlan,
  AppConfig,
  Application,
  ApplicationSummary,
  ApprovalRequired,
  ApprovalStatus,
  ApproveResult,
  AuthTokens,
  Bank,
  DeviceInfo,
  Loan,
  LoanDetail,
  LoanProduct,
  OtpSent,
  Page,
  PendingApproval,
  Profile,
  ProfilePhoto,
  DeletionCheck,
  AccountDeleted,
  Repayment,
  ResolvedAccount,
  SelfieRequired,
  Session,
  StepUpdate,
  Faqs,
  LegalDocument,
  LegalDocumentSummary,
  LoanOffer,
  NotificationPage,
  PayoutAccountSaved,
  SupportTicket,
  TicketCategory,
  TicketRelated,
  TransactionDirection,
  Wallet,
  WalletFundSession,
  WalletTransaction,
  WalletTransactionPage,
  Withdrawal,
  UpdateContact,
} from './types';

export const appConfig = () =>
  api.get<AppConfig>('/app/config', { auth: false, query: { platform: GATE_PLATFORM, version: APP_VERSION } });

export const auth = {
  registerBvn: (bvn: string) => api.post<OtpSent>('/auth/register/bvn', { bvn }, { auth: false }),
  /** With selfie checks on, returns `selfie_required` instead of tokens. */
  verifyRegistration: (bvn: string, otp: string, device: DeviceInfo) =>
    api.post<AuthTokens | SelfieRequired>('/auth/register/verify-otp', { bvn, otp, device }, { auth: false }),
  /** The live face capture: the main frame plus other frames from the same capture. */
  registrationSelfie: (
    registration_token: string,
    selfie_image: string,
    liveness_frames: string[],
    device: DeviceInfo,
  ) =>
    api.post<AuthTokens>(
      '/auth/register/selfie',
      { registration_token, selfie_image, liveness_frames, device },
      { auth: false, timeoutMs: 60_000 },
    ),
  resendRegistration: (bvn: string) => api.post<OtpSent>('/auth/register/resend-otp', { bvn }, { auth: false }),
  requestLogin: (phone: string) => api.post<OtpSent>('/auth/login/request-otp', { phone }, { auth: false }),
  /** A new phone while another is signed in gets `approval_required` instead of tokens. */
  verifyLogin: (phone: string, otp: string, device: DeviceInfo) =>
    api.post<AuthTokens | ApprovalRequired>('/auth/login/verify-otp', { phone, otp, device }, { auth: false }),
  pinSignIn: (device: DeviceInfo, pin: string) =>
    api.post<AuthTokens>(
      '/auth/login/pin',
      { device_id: device.device_id, device_token: device.device_token, pin, device },
      { auth: false },
    ),
  resendLogin: (phone: string) => api.post<OtpSent>('/auth/login/resend-otp', { phone }, { auth: false }),
  me: () => api.get<Profile>('/auth/me'),
  /** Email and home address only; identity fields come from the BVN record. */
  updateContact: (body: UpdateContact) => api.patch<Profile>('/auth/me', body),
  photo: () => api.get<ProfilePhoto>('/auth/me/photo'),
  setPhoto: (image: string) => api.put<Profile>('/auth/me/photo', { image }, { timeoutMs: 60_000 }),
  removePhoto: () => api.delete<Profile>('/auth/me/photo'),
  deletionCheck: () => api.get<DeletionCheck>('/auth/me/account-deletion'),
  deleteAccount: (pin: string) =>
    api.delete<AccountDeleted>('/auth/me', { body: { pin, confirmation: 'DELETE' } }),
  sessions: () => api.get<Session[]>('/auth/sessions'),
  revokeSession: (id: string) => api.delete<void>(`/auth/sessions/${id}`),
  logout: (forgetDevice = false) =>
    api.post<void>('/auth/logout', undefined, { query: { forget_device: forgetDevice || undefined } }),
  logoutAll: () => api.post<void>('/auth/logout-all'),
};

export const security = {
  setPin: (pin: string) => api.post<Profile>('/auth/pin', { pin }),
  changePin: (current_pin: string, new_pin: string) => api.post<void>('/auth/pin/change', { current_pin, new_pin }),
  verifyPin: (pin: string) => api.post<void>('/auth/pin/verify', { pin }),
  resetPin: (bvn: string, new_pin: string) => api.post<Profile>('/auth/pin/reset', { bvn, new_pin }),
  setTransactionPin: (pin: string) => api.post<Profile>('/auth/transaction-pin', { pin }),
  changeTransactionPin: (current_pin: string, new_pin: string) =>
    api.post<void>('/auth/transaction-pin/change', { current_pin, new_pin }),
  resetTransactionPin: (login_pin: string, new_pin: string) =>
    api.post<void>('/auth/transaction-pin/reset', { login_pin, new_pin }),
  setBiometrics: (enabled: boolean, pin?: string) => api.post<void>('/auth/biometrics', { enabled, pin }),
};

/** Approving a sign-in on a new phone. */
export const approvals = {
  // On the signed-in phone
  pending: () => api.get<PendingApproval[]>('/auth/device-approvals/pending'),
  approve: (id: string, proof: { pin?: string; biometric?: boolean }) =>
    api.post<ApproveResult>(`/auth/device-approvals/${id}/approve`, proof),
  deny: (id: string) => api.post<void>(`/auth/device-approvals/${id}/deny`),
  // On the new phone
  status: (id: string, approval_secret: string) =>
    api.post<ApprovalStatus>(`/auth/device-approvals/${id}/status`, { approval_secret }, { auth: false }),
  complete: (id: string, approval_secret: string, code: string, device: DeviceInfo) =>
    api.post<AuthTokens>(
      `/auth/device-approvals/${id}/complete`,
      { approval_secret, code, device },
      { auth: false },
    ),
  lostPhone: (id: string, approval_secret: string, bvn: string, pin: string | undefined, device: DeviceInfo) =>
    api.post<AuthTokens>(
      `/auth/device-approvals/${id}/lost-phone`,
      { approval_secret, bvn, pin, device },
      { auth: false },
    ),
};

export const loans = {
  products: () => api.get<LoanProduct[]>('/loans/products'),
  applications: (status?: string) =>
    api.get<Page<ApplicationSummary>>('/loans/me/applications', { query: { status, limit: 50 } }),
  application: (id: string) => api.get<Application>(`/loans/me/applications/${id}`),
  createApplication: (product_code: string) =>
    api.post<Application>('/loans/me/applications', { product_code, channel: 'mobile' }),
  updateStep: (id: string, update: StepUpdate) => api.patch<Application>(`/loans/me/applications/${id}`, update),
  uploadDocument: async (
    id: string,
    documentType: string,
    file: { uri: string; name: string; type: string },
    onProgress?: (fraction: number) => void,
  ) => {
    const path = `/loans/me/applications/${id}/documents/${documentType}`;
    if (Platform.OS === 'web') {
      // Browsers need a real Blob; picker URIs there are blob:/data: URLs.
      const form = new FormData();
      form.append('file', await (await fetch(file.uri)).blob(), file.name);
      return request<Application>('POST', path, { form, timeoutMs: 120_000 });
    }
    // On phones the file is sent natively (see RequestOptions.file).
    return request<Application>('POST', path, { file: { field: 'file', ...file }, onProgress, timeoutMs: 120_000 });
  },
  submit: (id: string) => api.post<Application>(`/loans/me/applications/${id}/submit`),
  list: () => api.get<Page<Loan>>('/loans/me/loans', { query: { limit: 50 } }),
  detail: (id: string) => api.get<LoanDetail>(`/loans/me/loans/${id}`),
  repay: (id: string, amount: string, transactionPin: string, idempotencyKey: string) =>
    api.post<Repayment>(
      `/loans/me/loans/${id}/repayments`,
      { amount, transaction_pin: transactionPin },
      { idempotencyKey },
    ),
};

export const wallet = {
  summary: () => api.get<Wallet>('/wallet'),
  fundCard: (amount: string, idempotencyKey: string) =>
    api.post<CardTopUp>('/wallet/fund/card', { amount }, { idempotencyKey }),
  cardTopUp: (reference: string) => api.get<CardTopUp>(`/wallet/fund/card/${encodeURIComponent(reference)}`),
  fund: (amount: string, idempotencyKey: string) =>
    api.post<WalletFundSession>('/wallet/fund', { amount }, { idempotencyKey }),
  transactions: (params: { direction?: TransactionDirection; cursor?: string; limit?: number } = {}) =>
    api.get<WalletTransactionPage>('/wallet/transactions', { query: params }),
  transaction: (id: string) => api.get<WalletTransaction>(`/wallet/transactions/${encodeURIComponent(id)}`),
  savePayoutAccount: (
    account: { bank_code: string; bank_name: string; account_number: string; account_name: string },
    transactionPin: string,
  ) => api.post<PayoutAccountSaved>('/wallet/payout-account', { ...account, transaction_pin: transactionPin }),
  withdraw: (amount: string, transactionPin: string, idempotencyKey: string) =>
    api.post<Withdrawal>('/wallet/withdraw', { amount, transaction_pin: transactionPin }, { idempotencyKey }),
};

export const notifications = {
  list: (offset = 0, limit = 30) => api.get<NotificationPage>('/notifications', { query: { offset, limit } }),
  unreadCount: () => api.get<{ unread_count: number }>('/notifications/unread-count'),
  markRead: (ids?: string[]) => api.post<{ unread_count: number }>('/notifications/read', { ids }),
  setPushToken: (token: string) => api.put<void>('/notifications/push-token', { token }),
  removePushToken: () => api.delete<void>('/notifications/push-token'),
};

export const legal = {
  list: () => api.get<LegalDocumentSummary[]>('/legal', { auth: false }),
  document: (slug: string) => api.get<LegalDocument>(`/legal/${slug}`, { auth: false }),
  accept: (documents: Record<string, string>) =>
    api.post<{ legal_pending: string[] }>('/legal/accept', { documents }),
  offer: (applicationId: string) => api.get<LoanOffer>(`/loans/me/applications/${applicationId}/offer`),
  acceptOffer: (applicationId: string, termsHash: string, transactionPin: string) =>
    api.post<LoanOffer>(`/loans/me/applications/${applicationId}/offer/accept`, {
      terms_hash: termsHash,
      transaction_pin: transactionPin,
    }),
};

export const support = {
  faqs: () => api.get<Faqs>('/support/faqs', { auth: false }),
  tickets: () => api.get<SupportTicket[]>('/support/tickets'),
  ticket: (id: string) => api.get<SupportTicket>(`/support/tickets/${id}`),
  create: (ticket: { category: TicketCategory; message: string; related_type?: TicketRelated; related_id?: string }) =>
    api.post<SupportTicket>('/support/tickets', ticket),
  reply: (id: string, body: string) => api.post<SupportTicket>(`/support/tickets/${id}/messages`, { body }),
  read: (id: string) => api.post<SupportTicket>(`/support/tickets/${id}/read`),
};

export const investments = {
  plans: () => api.get<InvestmentPlan[]>('/investments/plans'),
  mine: () => api.get<Investment[]>('/investments/me'),
  invest: (planId: string, amount: string, transactionPin: string, idempotencyKey: string) =>
    api.post<Investment>(
      '/investments/me',
      { plan_id: planId, amount, transaction_pin: transactionPin },
      { idempotencyKey },
    ),
};

export const banks = {
  list: () => api.get<Bank[]>('/banks'),
  resolve: (bank_code: string, account_number: string) =>
    api.post<ResolvedAccount>('/banks/resolve', { bank_code, account_number }),
};
