"use client";

import { api, apiWithTotal, COOKIE_TRANSPORT, downloadFile, query } from "./api";
import type {
  AdminSettings,
  OnboardingReport,
  ApplicationDetail,
  ApplicationSummary,
  ApplicationWorkflowState,
  AuditLogEntry,
  Branch,
  ContributionGroup,
  CustomerDetail,
  CustomerSummary,
  Dashboard,
  GlobalAuditLogEntry,
  Loan,
  LoanDetail,
  LoanProduct,
  OtpSentResponse,
  Page,
  PaymentTransaction,
  PermissionGroup,
  Repayment,
  RepaymentChannel,
  Role,
  SavingsProduct,
  StaffAuthResponse,
  StaffProfile,
  TransactionSummary,
  Workflow,
  WorkflowStageInput,
} from "./types";

const V1 = "/api/v1";
const json = (body: unknown) => JSON.stringify(body);

export const authApi = {
  requestOtp: (phone: string) =>
    api<OtpSentResponse>(`${V1}/admin/auth/login/request-otp`, { method: "POST", body: json({ phone }), auth: false }),
  resendOtp: (phone: string) =>
    api<OtpSentResponse>(`${V1}/admin/auth/login/resend-otp`, { method: "POST", body: json({ phone }), auth: false }),
  /** Sets the httpOnly refresh cookie; the body carries only the access token. */
  verifyOtp: (phone: string, otp: string) =>
    api<StaffAuthResponse>(`${V1}/admin/auth/login/verify-otp`, {
      method: "POST",
      body: json({ phone, otp, device: { platform: "web", device_name: "Staff portal (browser)" } }),
      auth: false,
      ...COOKIE_TRANSPORT,
    }),
  me: () => api<StaffProfile>(`${V1}/admin/auth/me`),
  /** Real activity: restarts the server's idle clock. */
  activity: () =>
    api<{ effective_idle_minutes: number; last_activity_at: string; idle_expires_at: string }>(
      `${V1}/admin/auth/activity`,
      { method: "POST" },
    ),
};

export interface SecuritySettings {
  staff_idle_minutes: number;
  min_minutes: number;
  max_minutes: number;
  updated_at: string | null;
  updated_by_name: string | null;
  my_idle_minutes: number | null;
  effective_idle_minutes: number;
  can_edit: boolean;
}

export const securityApi = {
  get: () => api<SecuritySettings>(`${V1}/admin/settings/security`),
  setOrg: (minutes: number) =>
    api<SecuritySettings>(`${V1}/admin/settings/security`, { method: "PUT", body: json({ staff_idle_minutes: minutes }) }),
  setMine: (minutes: number | null) =>
    api<SecuritySettings>(`${V1}/admin/auth/me/session-timeout`, { method: "PUT", body: json({ minutes }) }),
};

export const onboardingApi = {
  report: (days: number) => api<OnboardingReport>(`${V1}/admin/onboarding${query({ days })}`),
};

export const dashboardApi = {
  get: () => api<Dashboard>(`${V1}/admin/dashboard`),
  exportDemographics: () => downloadFile(`${V1}/admin/dashboard/demographics/export`, "gh-trust-demographics.csv"),
};

export const applicationsApi = {
  list: (params: { status?: string; product_code?: string; search?: string; limit?: number; offset?: number } = {}) =>
    apiWithTotal<ApplicationSummary[]>(`${V1}/admin/loans/applications${query(params)}`),
  get: (id: string) => api<ApplicationDetail>(`${V1}/admin/loans/applications/${id}`),
  workflow: (id: string) => api<ApplicationWorkflowState>(`${V1}/admin/loans/applications/${id}/workflow`),
  auditLog: (id: string) => api<AuditLogEntry[]>(`${V1}/admin/loans/applications/${id}/audit-log`),
  stageAction: (id: string, action: "approved" | "rejected", note?: string) =>
    api<ApplicationDetail>(`${V1}/admin/loans/applications/${id}/stage-action`, {
      method: "POST",
      body: json({ action, note }),
    }),
  updateTerms: (
    id: string,
    body: { approved_amount?: string; tenure_months?: number; repayment_cadence?: string },
  ) => api<ApplicationDetail>(`${V1}/admin/loans/applications/${id}/status`, { method: "PATCH", body: json(body) }),
  reject: (id: string, note: string) =>
    api<ApplicationDetail>(`${V1}/admin/loans/applications/${id}/status`, {
      method: "PATCH",
      body: json({ status: "rejected", note }),
    }),
  verifyDocument: (id: string, documentId: string, status: "verified" | "rejected", rejectionNote?: string) =>
    api<ApplicationDetail>(`${V1}/admin/loans/applications/${id}/documents/${documentId}/verify`, {
      method: "PATCH",
      body: json({ status, rejection_note: rejectionNote }),
    }),
  downloadDocument: (id: string, documentId: string, fileName: string) =>
    downloadFile(`${V1}/admin/loans/applications/${id}/documents/${documentId}/download`, fileName),
  disburse: (id: string, note?: string) =>
    api<ApplicationDetail>(`${V1}/admin/loans/applications/${id}/disburse`, { method: "POST", body: json({ note }) }),
  recordManualDisbursement: (id: string, body: { external_reference: string; disbursed_on?: string; note?: string }) =>
    api<ApplicationDetail>(`${V1}/admin/loans/applications/${id}/disbursements/manual`, {
      method: "POST",
      body: json(body),
    }),
};

export const loansApi = {
  list: (params: { status?: string; customer_id?: string; search?: string; limit?: number; offset?: number } = {}) =>
    api<Page<Loan>>(`${V1}/admin/loans/loans${query(params)}`),
  get: (id: string) => api<LoanDetail>(`${V1}/admin/loans/loans/${id}`),
  recordRepayment: (
    id: string,
    body: { amount: string; channel: Exclude<RepaymentChannel, "wallet">; reference: string; paid_at?: string; note?: string },
  ) => api<Repayment>(`${V1}/admin/loans/loans/${id}/repayments`, { method: "POST", body: json(body) }),
};

export const productsApi = {
  list: () => api<LoanProduct[]>(`${V1}/admin/loans/products`),
  setActive: (code: string, isActive: boolean) =>
    api<LoanProduct>(`${V1}/admin/loans/products/${code}`, { method: "PATCH", body: json({ is_active: isActive }) }),
  activeWorkflow: (code: string) => api<Workflow | null>(`${V1}/admin/loans/products/${code}/workflow/active`),
  workflows: (code: string) => api<Workflow[]>(`${V1}/admin/loans/products/${code}/workflows`),
  createWorkflow: (code: string, stages: WorkflowStageInput[]) =>
    api<Workflow>(`${V1}/admin/loans/products/${code}/workflows`, { method: "POST", body: json({ stages }) }),
  updateStages: (workflowId: string, stages: WorkflowStageInput[]) =>
    api<Workflow>(`${V1}/admin/loans/workflows/${workflowId}/stages`, { method: "PUT", body: json({ stages }) }),
  publish: (workflowId: string) => api<Workflow>(`${V1}/admin/loans/workflows/${workflowId}/publish`, { method: "POST" }),
};

export const customersApi = {
  list: (params: { search?: string; status?: string; limit?: number; offset?: number } = {}) =>
    api<CustomerSummary[]>(`${V1}/admin/customers${query(params)}`),
  /** Same list with the total match count (from X-Total-Count). */
  page: (params: { search?: string; status?: string; limit?: number; offset?: number } = {}) =>
    apiWithTotal<CustomerSummary[]>(`${V1}/admin/customers${query(params)}`),
  get: (id: string) => api<CustomerDetail>(`${V1}/admin/customers/${id}`),
};

export const teamApi = {
  listStaff: () => api<StaffProfile[]>(`${V1}/admin/staff`),
  createStaff: (body: { full_name: string; email: string; phone: string; role_id?: string | null }) =>
    api<StaffProfile>(`${V1}/admin/staff`, { method: "POST", body: json(body) }),
  updateStaff: (id: string, body: { full_name?: string; email?: string; phone?: string; role_id?: string | null }) =>
    api<StaffProfile>(`${V1}/admin/staff/${id}`, { method: "PATCH", body: json(body) }),
  activate: (id: string) => api<StaffProfile>(`${V1}/admin/staff/${id}/activate`, { method: "POST" }),
  deactivate: (id: string) => api<StaffProfile>(`${V1}/admin/staff/${id}/deactivate`, { method: "POST" }),
  listRoles: () => api<Role[]>(`${V1}/admin/roles`),
  createRole: (body: { name: string; description?: string; permissions: string[] }) =>
    api<Role>(`${V1}/admin/roles`, { method: "POST", body: json(body) }),
  updateRole: (id: string, body: { name?: string; description?: string; permissions?: string[] }) =>
    api<Role>(`${V1}/admin/roles/${id}`, { method: "PATCH", body: json(body) }),
  deleteRole: (id: string) => api<void>(`${V1}/admin/roles/${id}`, { method: "DELETE" }),
  permissionCatalog: () => api<{ groups: PermissionGroup[] }>(`${V1}/admin/permissions`),
};

export const settingsApi = {
  get: () => api<AdminSettings>(`${V1}/admin/settings`),
  branches: () => api<Branch[]>(`${V1}/admin/settings/branches`),
  auditLogs: (params: { event_type?: string; search?: string; limit?: number; offset?: number } = {}) =>
    apiWithTotal<GlobalAuditLogEntry[]>(`${V1}/admin/settings/audit-logs${query(params)}`),
};

export const paymentsApi = {
  transactions: (params: { status?: string; direction?: string; limit?: number; offset?: number } = {}) =>
    api<Page<PaymentTransaction>>(`${V1}/admin/payments/transactions${query(params)}`),
  summary: () => api<TransactionSummary>(`${V1}/admin/payments/transactions/summary`),
};

export const catalogApi = {
  savingsProducts: () => api<SavingsProduct[]>(`${V1}/savings/products`, { auth: false }),
  contributionGroups: () => api<ContributionGroup[]>(`${V1}/contributions/groups`, { auth: false }),
};
