import { apiFetch } from './api'

export type TicketStatus = 'open' | 'in_progress' | 'resolved'

export interface SupportMessage {
  id: string
  author: 'customer' | 'staff'
  author_name: string
  body: string
  created_at: string
  read_at?: string | null
}

export interface SupportTicket {
  id: string
  reference: string
  category: string
  message: string
  related_type: string | null
  related_id: string | null
  status: TicketStatus
  reply: string | null
  replied_at: string | null
  created_at: string
  updated_at: string
  awaiting_reply: boolean
  messages: SupportMessage[]
  customer_id: string
  customer_name: string
  customer_phone: string
  app_version: string | null
  platform: string | null
  device_name: string | null
  resolved_at: string | null
}

export interface TicketPage {
  items: SupportTicket[]
  total: number
  open: number
}

export const supportApi = {
  list: (token: string, status?: TicketStatus) =>
    apiFetch<TicketPage>(`/api/v1/admin/support/tickets${status ? `?status=${status}` : ''}`, {}, token),
  update: (token: string, id: string, body: { status?: TicketStatus; reply?: string }) =>
    apiFetch<SupportTicket>(`/api/v1/admin/support/tickets/${id}`, { method: 'PATCH', body: JSON.stringify(body) }, token),
  read: (token: string, id: string) =>
    apiFetch<SupportTicket>(`/api/v1/admin/support/tickets/${id}/read`, { method: 'POST' }, token),
}
