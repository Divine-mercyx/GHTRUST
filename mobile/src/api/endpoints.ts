import { Platform } from 'react-native';

import { api, request } from './client';
import { GATE_PLATFORM, APP_VERSION } from './config';
import type {
  AppConfig,
  Application,
  ApplicationSummary,
  AuthTokens,
  Bank,
  DeviceInfo,
  Loan,
  LoanDetail,
  LoanProduct,
  OtpSent,
  Page,
  Profile,
  Repayment,
  ResolvedAccount,
  Session,
  StepUpdate,
  Wallet,
  WalletFundSession,
} from './types';

export const appConfig = () =>
  api.get<AppConfig>('/app/config', { auth: false, query: { platform: GATE_PLATFORM, version: APP_VERSION } });

export const auth = {
  registerBvn: (bvn: string) => api.post<OtpSent>('/auth/register/bvn', { bvn }, { auth: false }),
  verifyRegistration: (bvn: string, otp: string, device: DeviceInfo) =>
    api.post<AuthTokens>('/auth/register/verify-otp', { bvn, otp, device }, { auth: false }),
  resendRegistration: (bvn: string) => api.post<OtpSent>('/auth/register/resend-otp', { bvn }, { auth: false }),
  requestLogin: (phone: string) => api.post<OtpSent>('/auth/login/request-otp', { phone }, { auth: false }),
  verifyLogin: (phone: string, otp: string, device: DeviceInfo) =>
    api.post<AuthTokens>('/auth/login/verify-otp', { phone, otp, device }, { auth: false }),
  resendLogin: (phone: string) => api.post<OtpSent>('/auth/login/resend-otp', { phone }, { auth: false }),
  me: () => api.get<Profile>('/auth/me'),
  sessions: () => api.get<Session[]>('/auth/sessions'),
  revokeSession: (id: string) => api.delete<void>(`/auth/sessions/${id}`),
  logout: () => api.post<void>('/auth/logout'),
  logoutAll: () => api.post<void>('/auth/logout-all'),
};

export const loans = {
  products: () => api.get<LoanProduct[]>('/loans/products'),
  applications: (status?: string) =>
    api.get<Page<ApplicationSummary>>('/loans/me/applications', { query: { status, limit: 50 } }),
  application: (id: string) => api.get<Application>(`/loans/me/applications/${id}`),
  createApplication: (product_code: string) =>
    api.post<Application>('/loans/me/applications', { product_code, channel: 'mobile' }),
  updateStep: (id: string, update: StepUpdate) => api.patch<Application>(`/loans/me/applications/${id}`, update),
  uploadDocument: async (id: string, documentType: string, file: { uri: string; name: string; type: string }) => {
    const form = new FormData();
    if (Platform.OS === 'web') {
      // Browsers need a real Blob; picker URIs there are blob:/data: URLs.
      form.append('file', await (await fetch(file.uri)).blob(), file.name);
    } else {
      // React Native's FormData takes {uri, name, type} file parts.
      form.append('file', file as unknown as Blob);
    }
    return request<Application>('POST', `/loans/me/applications/${id}/documents/${documentType}`, {
      form,
      timeoutMs: 90_000,
    });
  },
  submit: (id: string) => api.post<Application>(`/loans/me/applications/${id}/submit`),
  list: () => api.get<Page<Loan>>('/loans/me/loans', { query: { limit: 50 } }),
  detail: (id: string) => api.get<LoanDetail>(`/loans/me/loans/${id}`),
  repay: (id: string, amount: string, idempotencyKey: string) =>
    api.post<Repayment>(`/loans/me/loans/${id}/repayments`, { amount }, { idempotencyKey }),
};

export const wallet = {
  summary: () => api.get<Wallet>('/wallet'),
  fund: (amount: string, idempotencyKey: string) =>
    api.post<WalletFundSession>('/wallet/fund', { amount }, { idempotencyKey }),
};

export const banks = {
  list: () => api.get<Bank[]>('/banks'),
  resolve: (bank_code: string, account_number: string) =>
    api.post<ResolvedAccount>('/banks/resolve', { bank_code, account_number }),
};
