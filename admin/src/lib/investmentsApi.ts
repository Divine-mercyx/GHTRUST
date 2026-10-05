import { apiFetch } from './api'

export type Risk = 'low' | 'medium' | 'high'

export interface InvestmentPlan {
  id: string
  name: string
  description: string | null
  min_amount: string
  max_amount: string | null
  return_rate: string
  tenure_months: number
  risk: Risk
  is_active: boolean
  image_url: string | null
  active_investors: number
  active_amount: string
  created_at: string
}

export interface PlanInput {
  name: string
  description: string | null
  min_amount: string
  max_amount: string | null
  return_rate: string
  tenure_months: number
  risk: Risk
  is_active: boolean
}

export interface Holding {
  id: string
  reference: string | null
  customer_id: string
  customer_name: string
  plan_name: string
  amount: string
  return_rate: string
  projected_return: string
  start_date: string
  maturity_date: string
  status: 'active' | 'paid_out'
  paid_out_at: string | null
}

export interface HoldingsPage {
  items: Holding[]
  total: number
  active_amount: string
  due_in_30_days: string
}

const base = '/api/v1/admin/investments'

export const investmentsApi = {
  plans: (token: string) => apiFetch<InvestmentPlan[]>(`${base}/plans`, {}, token),
  create: (token: string, body: PlanInput) =>
    apiFetch<InvestmentPlan>(`${base}/plans`, { method: 'POST', body: JSON.stringify(body) }, token),
  update: (token: string, id: string, body: Partial<PlanInput>) =>
    apiFetch<InvestmentPlan>(`${base}/plans/${id}`, { method: 'PATCH', body: JSON.stringify(body) }, token),
  setImage: (token: string, id: string, image: string) =>
    apiFetch<InvestmentPlan>(`${base}/plans/${id}/image`, { method: 'PUT', body: JSON.stringify({ image }) }, token),
  removeImage: (token: string, id: string) =>
    apiFetch<InvestmentPlan>(`${base}/plans/${id}/image`, { method: 'DELETE' }, token),
  holdings: (token: string, status?: 'active' | 'paid_out', offset = 0) =>
    apiFetch<HoldingsPage>(
      `${base}/holdings?limit=50&offset=${offset}${status ? `&status=${status}` : ''}`,
      {},
      token,
    ),
}
