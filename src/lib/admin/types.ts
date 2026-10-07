/**
 * Response shapes of the GH Trust staff API (the schemas.py files under backend/app/modules).
 * Money fields arrive as decimal strings; format with `money()` from ./format.
 */

export type Money = string;

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// ── Auth / team ───────────────────────────────────────────────────────────

export interface Role {
  id: string;
  name: string;
  description: string | null;
  permissions: string[];
  is_system: boolean;
}

export interface StaffProfile {
  id: string;
  full_name: string;
  email: string;
  phone: string;
  status: string;
  is_super_admin: boolean;
  role: Role | null;
  permissions: string[];
}

export interface OtpSentResponse {
  message: string;
  phone_masked: string;
  expires_in: number;
  purpose: string;
}

export interface StaffAuthResponse {
  access_token: string;
  /** Always null for the portal: the refresh token is delivered as an httpOnly cookie. */
  refresh_token: string | null;
  expires_in: number;
  refresh_expires_in: number;
  session_id: string;
  staff: StaffProfile;
}

export interface PermissionGroup {
  label: string;
  permissions: string[];
}

// ── Loans: products, applications, workflow ───────────────────────────────

export interface LoanProduct {
  id: string;
  code: string;
  name: string;
  description: string | null;
  is_active: boolean;
  processing_fee_pct: Money;
  interest_rate_pct_monthly: Money;
  max_tenure_days: number | null;
  default_penalty_pct_daily: Money | null;
  repayment_cadence_options: string[];
  required_document_types: string[];
  workflow_steps: string[];
  eligibility_rules: Record<string, unknown>;
}

export type ApplicationStatus =
  | "draft"
  | "submitted"
  | "under_review"
  | "documents_incomplete"
  | "approved"
  | "offer_sent"
  | "offer_accepted"
  | "product_gate_pending"
  | "processing_fee_paid"
  | "ready_to_disburse"
  | "disbursed"
  | "rejected"
  | "withdrawn"
  | "expired";

export interface ApplicationSummary {
  id: string;
  customer_id: string;
  applicant_name: string | null;
  product_code: string;
  product_name: string;
  status: ApplicationStatus;
  channel: string | null;
  branch: string | null;
  account_number: string | null;
  current_stage_name: string | null;
  stage_progress_pct: number | null;
  approver_role_name: string | null;
  pipeline_stages: { name: string; status: string }[];
  requested_amount: Money | null;
  approved_amount: Money | null;
  submitted_at: string | null;
  created_at: string;
}

export interface ApplicationDocument {
  id: string;
  document_type: string;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  status: "pending" | "verified" | "rejected";
  uploaded_by: string;
  rejection_note: string | null;
  created_at: string;
}

export interface DocumentChecklistItem {
  document_type: string;
  label: string;
  required: boolean;
  uploaded: boolean;
  status: "pending" | "verified" | "rejected" | null;
  document_id: string | null;
}

export interface LoanOfferInstallment {
  installment: number;
  due_date: string;
  amount: Money;
}

/** Same shape as the customer mobile offer (estimated dates from today). */
export interface LoanOfferPreview {
  principal: Money;
  tenure_months: number;
  cadence: string;
  installments: number;
  total_repayable: Money;
  total_interest: Money;
  processing_fee: Money;
  total_cost_of_credit: Money;
  first_payment: Money;
  schedule: LoanOfferInstallment[];
}

export interface ApplicationDetail {
  id: string;
  customer_id: string;
  product_code: string;
  product_name: string;
  status: ApplicationStatus;
  channel: string;
  step: number;
  total_steps: number;
  branch: string;
  requested_amount: Money | null;
  approved_amount: Money | null;
  repayment_cadence: string | null;
  approved_tenure_months: number | null;
  tenure_months: number | null;
  universal_form: Record<string, unknown>;
  product_data: Record<string, unknown>;
  submitted_at: string | null;
  assigned_officer_id: string | null;
  rejection_reason: string | null;
  guarantors: {
    id: string;
    full_name: string;
    phone: string | null;
    bvn: string | null;
    id_type: string | null;
    id_number: string | null;
    relationship: string | null;
    address: string | null;
  }[];
  collaterals: {
    id: string;
    collateral_type: string;
    description: string;
    estimated_value: Money | null;
    custody_status: string;
    affidavit_reference: string | null;
  }[];
  documents: ApplicationDocument[];
  document_checklist: DocumentChecklistItem[];
}

export interface WorkflowStage {
  id: string;
  sort_order: number;
  name: string;
  slug: string;
  description: string | null;
  approver_role_id: string;
  approver_role_name: string | null;
}

export interface Workflow {
  id: string;
  product_id: string;
  version: number;
  is_published: boolean;
  published_at: string | null;
  stages: WorkflowStage[];
}

export interface WorkflowStageInput {
  name: string;
  description?: string;
  approver_role_id: string;
}

export interface StageDecision {
  id: string;
  stage_id: string;
  stage_name: string | null;
  staff_id: string;
  staff_name: string | null;
  action: "approved" | "rejected";
  note: string | null;
  entered_at: string;
  decided_at: string;
  duration_seconds: number;
}

export interface ApplicationWorkflowState {
  workflow_id: string | null;
  workflow_version: number | null;
  current_stage: WorkflowStage | null;
  current_stage_entered_at: string | null;
  pipeline_stages: {
    id: string;
    sort_order: number;
    name: string;
    approver_role_name: string | null;
    status: "completed" | "current" | "upcoming" | "rejected";
  }[];
  stage_decisions: StageDecision[];
  processing_duration_seconds: number | null;
  submitted_at: string | null;
  approved_at: string | null;
  rejected_at: string | null;
  disbursed_at: string | null;
}

export interface AuditLogEntry {
  id: string;
  event_type: string;
  actor_type: string;
  actor_id: string | null;
  actor_label: string | null;
  message: string | null;
  event_metadata: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
}

export interface GlobalAuditLogEntry extends AuditLogEntry {
  application_id: string;
}

// ── Loan book ─────────────────────────────────────────────────────────────

export type LoanStatus = "active" | "overdue" | "completed" | "written_off";

export interface Loan {
  id: string;
  customer_id: string;
  customer_name: string | null;
  application_id: string | null;
  product_type: string;
  principal: Money;
  total_interest: Money;
  total_repayable: Money;
  amount_paid: Money;
  outstanding: Money;
  principal_outstanding: Money;
  interest_rate: Money;
  interest_method: "flat" | "reducing_balance";
  repayment_cadence: string;
  installments_count: number;
  tenure_months: number;
  monthly_payment: Money;
  status: LoanStatus;
  disbursement_date: string | null;
  next_due_date: string | null;
  created_at: string;
}

export interface ScheduleItem {
  installment: number;
  due_date: string;
  amount: Money;
  principal: Money;
  interest: Money;
  principal_paid: Money;
  interest_paid: Money;
  amount_due: Money;
  status: "pending" | "partial" | "paid" | "overdue";
  paid_at: string | null;
}

export type RepaymentChannel = "wallet" | "bank_transfer" | "cash" | "remita" | "other";

export interface Repayment {
  id: string;
  loan_id: string;
  amount: Money;
  principal_amount: Money;
  interest_amount: Money;
  channel: RepaymentChannel;
  reference: string;
  paid_at: string;
  note: string | null;
}

export interface LoanDetail extends Loan {
  schedule: ScheduleItem[];
  repayments: Repayment[];
}

// ── Customers ─────────────────────────────────────────────────────────────

export interface CustomerSummary {
  id: string;
  account_number: string;
  full_name: string;
  bvn_masked: string;
  phone: string;
  email: string | null;
  gender: string | null;
  state_of_residence: string | null;
  branch: string;
  status: string;
  application_count: number;
  created_at: string;
}

export interface CustomerDetail {
  id: string;
  account_number: string;
  bvn_masked: string;
  first_name: string;
  last_name: string;
  middle_name: string | null;
  full_name: string;
  gender: string | null;
  date_of_birth: string | null;
  title: string | null;
  phone: string;
  phone_secondary: string | null;
  email: string | null;
  residential_address: string | null;
  state_of_residence: string | null;
  lga_of_residence: string | null;
  state_of_origin: string | null;
  lga_of_origin: string | null;
  nationality: string | null;
  marital_status: string | null;
  enrollment_bank: string | null;
  enrollment_branch: string | null;
  level_of_account: string | null;
  name_on_card: string | null;
  branch: string;
  status: string;
  phone_verified: boolean;
  last_login_at: string | null;
  created_at: string;
  stats: {
    total_applications: number;
    active_applications: number;
    disbursed_count: number;
    total_disbursed_amount: number;
  };
  loan_applications: ApplicationSummary[];
}

// ── Dashboard / settings ──────────────────────────────────────────────────

export interface DemographicBucket {
  label: string;
  count: number;
  percentage: number;
}

export interface Dashboard {
  total_applications: number;
  status_counts: { status: ApplicationStatus; count: number }[];
  pending_review_count: number;
  total_disbursed_amount: number;
  loan_book_amount: number;
  recent_applications: ApplicationSummary[];
  pending_queue: ApplicationSummary[];
  daily_submissions: { date: string; count: number }[];
  product_mix: { product_code: string; product_name: string; count: number; percentage: number }[];
  demographics: {
    total_applicants: number;
    gender: DemographicBucket[];
    age_buckets: DemographicBucket[];
    state_of_residence: DemographicBucket[];
    state_of_origin: DemographicBucket[];
  };
}

export interface AdminSettings {
  app_name: string;
  app_env: string;
  debug: boolean;
  default_branch: string;
  dojah_enabled: boolean;
  dojah_mock: boolean;
  sms_mock: boolean;
  rate_limits_active: boolean;
  otp_expire_seconds: number;
  max_upload_size_mb: number;
}

export interface Branch {
  name: string;
  customer_count: number;
}

// ── Payments ──────────────────────────────────────────────────────────────

export interface PaymentTransaction {
  id: string;
  provider: string;
  provider_reference: string;
  direction: "inbound" | "outbound";
  channel: string;
  amount: Money;
  currency: string;
  status: "pending" | "completed" | "failed" | "reversed";
  customer_id: string | null;
  customer_name: string | null;
  application_id: string | null;
  withdrawal_id: string | null;
  failure_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface TransactionSummary {
  total: number;
  by_status: Record<string, number>;
  completed_inbound_amount: Money;
  completed_outbound_amount: Money;
}

// ── Other products (read-only for now) ────────────────────────────────────

export interface SavingsProduct {
  id: string;
  name: string;
  product_type: string;
  interest_rate: Money;
  min_deposit: Money;
  description: string | null;
  is_active: boolean;
}

export interface ContributionGroup {
  id: string;
  name: string;
  leader_id: string;
  leader_name: string;
  member_count: number;
  target_amount: Money;
  collected_amount: Money;
  cycle: number;
  branch: string;
  next_meeting: string | null;
  status: string;
  service_fee_percent: Money;
}

/** GET /admin/onboarding: sign-up funnel and face-check performance (pilot tuning). */
export interface OnboardingReport {
  days: number;
  since: string;
  funnel: { key: string; label: string; count: number; rate_from_start: number | null }[];
  face_checks: {
    attempts: number;
    scored_attempts: number;
    passed: number;
    pass_rate: number | null;
    customers: number;
    first_try_pass_rate: number | null;
    cooldowns: number;
    outcomes: { outcome: string; label: string; count: number }[];
    threshold: number;
    threshold_simulation: OnboardingSimulationPoint[];
    score_histogram: { label: string; count: number }[];
    liveness_min: number | null;
    liveness_simulation: OnboardingSimulationPoint[];
  };
}

export interface OnboardingSimulationPoint {
  value: number;
  pass_rate: number | null;
  current: boolean;
}
