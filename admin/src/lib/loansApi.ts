import { apiFetch, API_BASE, ApiError } from './api'

export type InterestMethod = 'flat' | 'reducing_balance' | 'one_off'

export interface LoanProduct {
  id: string
  code: string
  name: string
  description: string | null
  is_active: boolean
  processing_fee_pct: string
  interest_rate_pct_monthly: string
  /** one_off: the rate is charged once for the whole loan (LPO financing), not per month. */
  interest_method?: InterestMethod
  max_tenure_days?: number | null
  repayment_cadence_options?: string[]
  required_document_types?: string[]
  workflow_steps?: string[]
}

export interface LoanProductInput {
  code: string
  name: string
  description?: string | null
  interest_rate_pct_monthly: string
  processing_fee_pct: string
  interest_method: InterestMethod
  max_tenure_days: number | null
  default_penalty_pct_daily: string | null
  repayment_cadence_options: string[]
  required_document_types: string[]
  workflow_steps: string[]
}

export interface WorkflowStage {
  id: string
  sort_order: number
  name: string
  slug: string
  description: string | null
  approver_role_id: string
  approver_role_name: string | null
}

export interface Workflow {
  id: string
  product_id: string
  version: number
  is_published: boolean
  published_at: string | null
  stages: WorkflowStage[]
}

export interface ApplicationSummary {
  id: string
  customer_id: string
  applicant_name: string | null
  product_code: string
  product_name: string
  status: string
  channel: string | null
  branch: string | null
  account_number: string | null
  current_stage_name: string | null
  stage_progress_pct: number | null
  approver_role_name: string | null
  pipeline_stages?: { name: string; status: string }[]
  requested_amount: string | null
  approved_amount: string | null
  submitted_at: string | null
  offer_accepted_at?: string | null
  created_at: string
}

export interface ApplicationDetail extends ApplicationSummary {
  channel: string
  step: number
  total_steps: number
  branch: string
  repayment_cadence: string | null
  universal_form: Record<string, unknown>
  product_data: Record<string, unknown>
  rejection_reason: string | null
  guarantors: { id: string; full_name: string; phone: string | null }[]
  documents: { id: string; document_type: string; file_name: string; status: string }[]
}

export interface StageDecision {
  id: string
  stage_id: string
  stage_name: string | null
  staff_id: string
  staff_name: string | null
  action: 'approved' | 'rejected'
  note: string | null
  entered_at: string
  decided_at: string
  duration_seconds: number
}

export interface PipelineStage {
  id: string
  sort_order: number
  name: string
  approver_role_name: string | null
  status: 'completed' | 'current' | 'upcoming' | 'rejected'
}

export interface ApplicationWorkflowState {
  workflow_id: string | null
  workflow_version: number | null
  current_stage: WorkflowStage | null
  current_stage_entered_at: string | null
  pipeline_stages: PipelineStage[]
  stage_decisions: StageDecision[]
  processing_duration_seconds: number | null
  submitted_at: string | null
  offer_accepted_at?: string | null
  approved_at: string | null
  rejected_at: string | null
  disbursed_at: string | null
}

export interface AuditLogEntry {
  id: string
  event_type: string
  actor_type: string
  actor_id: string | null
  actor_label: string | null
  message: string | null
  event_metadata: Record<string, unknown>
  ip_address: string | null
  created_at: string
}

export interface Role {
  id: string
  name: string
  description: string | null
}

export interface WorkflowStageInput {
  name: string
  slug?: string
  description?: string
  approver_role_id: string
}

export const loansApi = {
  listProducts: (token: string) =>
    apiFetch<LoanProduct[]>('/api/v1/admin/loans/products', {}, token),

  createProduct: (token: string, product: LoanProductInput) =>
    apiFetch<LoanProduct>('/api/v1/admin/loans/products', { method: 'POST', body: JSON.stringify(product) }, token),

  setProductActive: (token: string, productCode: string, isActive: boolean) =>
    apiFetch<LoanProduct>(`/api/v1/admin/loans/products/${productCode}`, {
      method: 'PATCH',
      body: JSON.stringify({ is_active: isActive }),
    }, token),

  listApplications: (token: string, params?: { status?: string; product_code?: string; limit?: number }) => {
    const q = new URLSearchParams()
    if (params?.status) q.set('status', params.status)
    if (params?.product_code) q.set('product_code', params.product_code)
    if (params?.limit) q.set('limit', String(params.limit))
    const qs = q.toString()
    return apiFetch<ApplicationSummary[]>(
      `/api/v1/admin/loans/applications${qs ? `?${qs}` : ''}`,
      {},
      token,
    )
  },

  getApplication: (token: string, id: string) =>
    apiFetch<ApplicationDetail>(`/api/v1/admin/loans/applications/${id}`, {}, token),

  getWorkflowState: (token: string, id: string) =>
    apiFetch<ApplicationWorkflowState>(`/api/v1/admin/loans/applications/${id}/workflow`, {}, token),

  getAuditLog: (token: string, id: string) =>
    apiFetch<AuditLogEntry[]>(`/api/v1/admin/loans/applications/${id}/audit-log`, {}, token),

  stageAction: (token: string, id: string, action: 'approved' | 'rejected', note?: string) =>
    apiFetch<ApplicationDetail>(`/api/v1/admin/loans/applications/${id}/stage-action`, {
      method: 'POST',
      body: JSON.stringify({ action, note }),
    }, token),

  disburse: (token: string, id: string, note?: string) =>
    apiFetch<ApplicationDetail>(`/api/v1/admin/loans/applications/${id}/disburse`, {
      method: 'POST',
      body: JSON.stringify({ note }),
    }, token),

  getActiveWorkflow: (token: string, productCode: string) =>
    apiFetch<Workflow | null>(`/api/v1/admin/loans/products/${productCode}/workflow/active`, {}, token),

  listWorkflows: (token: string, productCode: string) =>
    apiFetch<Workflow[]>(`/api/v1/admin/loans/products/${productCode}/workflows`, {}, token),

  createWorkflow: (token: string, productCode: string, stages: WorkflowStageInput[]) =>
    apiFetch<Workflow>(`/api/v1/admin/loans/products/${productCode}/workflows`, {
      method: 'POST',
      body: JSON.stringify({ stages }),
    }, token),

  updateWorkflowStages: (token: string, workflowId: string, stages: WorkflowStageInput[]) =>
    apiFetch<Workflow>(`/api/v1/admin/loans/workflows/${workflowId}/stages`, {
      method: 'PUT',
      body: JSON.stringify({ stages }),
    }, token),

  publishWorkflow: (token: string, workflowId: string) =>
    apiFetch<Workflow>(`/api/v1/admin/loans/workflows/${workflowId}/publish`, {
      method: 'POST',
    }, token),

  listRoles: (token: string) =>
    apiFetch<Role[]>('/api/v1/admin/roles', {}, token),

  verifyDocument: (
    token: string,
    applicationId: string,
    documentId: string,
    status: 'verified' | 'rejected',
    rejectionNote?: string,
  ) =>
    apiFetch<ApplicationDetail>(
      `/api/v1/admin/loans/applications/${applicationId}/documents/${documentId}/verify`,
      {
        method: 'PATCH',
        body: JSON.stringify({ status, rejection_note: rejectionNote }),
      },
      token,
    ),

  downloadDocument: async (
    token: string,
    applicationId: string,
    documentId: string,
    fileName: string,
  ) => {
    const res = await fetch(
      `${API_BASE}/api/v1/admin/loans/applications/${applicationId}/documents/${documentId}/download`,
      { headers: { Authorization: `Bearer ${token}` } },
    )
    if (!res.ok) {
      let message = res.statusText
      try {
        const data = await res.json()
        if (typeof data.detail === 'string') message = data.detail
      } catch {
        /* ignore */
      }
      throw new ApiError(message, res.status)
    }
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = fileName
    anchor.click()
    URL.revokeObjectURL(url)
  },
}

export function formatNaira(amount: string | number | null | undefined): string {
  if (amount == null) return '—'
  const n = typeof amount === 'string' ? parseFloat(amount) : amount
  return new Intl.NumberFormat('en-NG', { style: 'currency', currency: 'NGN', maximumFractionDigits: 0 }).format(n)
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`
  return `${(seconds / 86400).toFixed(1)}d`
}
