import { useEffect, useRef, useState } from 'react'
import { API_BASE, tokenStore } from './api'
import type { SupportMessage, TicketStatus } from './supportApi'

/**
 * Live support chat (backend: app/modules/support/realtime.py).
 *
 * Vercel can't proxy WebSockets, so on the deployed portal the socket goes straight to the
 * API host (VITE_WS_URL, or the Railway API by default). Locally it goes through the Vite proxy.
 * The access token is sent in the first frame. Reconnects with backoff; HTTP stays the fallback.
 */

const RAILWAY_WS = 'wss://ghtrust-production.up.railway.app'

function socketUrl(): string {
  const explicit = import.meta.env.VITE_WS_URL as string | undefined
  if (explicit) return `${explicit.replace(/\/$/, '')}/api/v1/ws/admin/support`
  if (API_BASE) return `${API_BASE.replace(/^http/, 'ws').replace(/\/$/, '')}/api/v1/ws/admin/support`
  const local = ['localhost', '127.0.0.1'].includes(location.hostname)
  if (local) return `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/v1/ws/admin/support`
  return `${RAILWAY_WS}/api/v1/ws/admin/support`
}

export type SupportEvent =
  | { type: 'message'; ticket_id: string; customer_id: string; status: TicketStatus; message: SupportMessage }
  | { type: 'typing'; ticket_id: string; customer_id: string; author: 'customer' | 'staff' }
  | { type: 'read'; ticket_id: string; customer_id: string; by: 'customer' | 'staff'; at: string }
  | { type: 'ticket'; ticket_id: string; customer_id: string; status: TicketStatus }

type Ack = { message: SupportMessage; status: TicketStatus }
type Pending = { resolve: (a: Ack) => void; reject: (e: Error) => void; timer: number }

export type SocketState = 'connecting' | 'live' | 'offline'

class SupportSocket {
  private ws: WebSocket | null = null
  private listeners = new Set<(e: SupportEvent) => void>()
  private stateListeners = new Set<(s: SocketState) => void>()
  private pending = new Map<string, Pending>()
  private attempts = 0
  private retryTimer: number | undefined
  private pingTimer: number | undefined
  private users = 0
  state: SocketState = 'offline'

  acquire() {
    this.users += 1
    if (this.users === 1) this.connect()
  }

  release() {
    this.users = Math.max(0, this.users - 1)
    if (this.users === 0) this.close()
  }

  on(listener: (e: SupportEvent) => void) {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  onState(listener: (s: SocketState) => void) {
    this.stateListeners.add(listener)
    return () => {
      this.stateListeners.delete(listener)
    }
  }

  get live() {
    return this.state === 'live'
  }

  /** Resolves when the server saved the message; rejects if it couldn't (use HTTP instead). */
  send(ticketId: string, body: string): Promise<Ack> {
    if (!this.live || !this.ws) return Promise.reject(new Error('offline'))
    const clientId = crypto.randomUUID()
    return new Promise<Ack>((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.pending.delete(clientId)
        reject(new Error('timeout'))
      }, 10_000)
      this.pending.set(clientId, { resolve, reject, timer })
      this.ws!.send(JSON.stringify({ type: 'send', ticket_id: ticketId, body, client_id: clientId }))
    })
  }

  typing(ticketId: string) {
    this.frame({ type: 'typing', ticket_id: ticketId })
  }

  read(ticketId: string) {
    this.frame({ type: 'read', ticket_id: ticketId })
  }

  private frame(data: object) {
    if (this.live && this.ws) this.ws.send(JSON.stringify(data))
  }

  private setState(s: SocketState) {
    this.state = s
    this.stateListeners.forEach((l) => l(s))
  }

  private connect() {
    const token = tokenStore.access
    if (!token || this.users === 0) return
    this.setState('connecting')
    let ws: WebSocket
    try {
      ws = new WebSocket(socketUrl())
    } catch {
      this.scheduleRetry()
      return
    }
    this.ws = ws
    ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token: tokenStore.access }))
    ws.onmessage = (ev) => {
      let data: { type?: string; client_id?: string; [k: string]: unknown }
      try {
        data = JSON.parse(String(ev.data))
      } catch {
        return
      }
      if (data.type === 'ready') {
        this.attempts = 0
        this.setState('live')
        window.clearInterval(this.pingTimer)
        this.pingTimer = window.setInterval(() => this.frame({ type: 'ping' }), 25_000)
        return
      }
      if (data.type === 'ack' || data.type === 'error') {
        const p = data.client_id ? this.pending.get(data.client_id) : undefined
        if (!p) return
        window.clearTimeout(p.timer)
        this.pending.delete(data.client_id!)
        if (data.type === 'ack') p.resolve({ message: data.message as SupportMessage, status: data.status as TicketStatus })
        else p.reject(new Error(String(data.message ?? data.code ?? 'error')))
        return
      }
      if (data.type === 'pong') return
      this.listeners.forEach((l) => l(data as SupportEvent))
    }
    ws.onclose = () => {
      if (this.ws !== ws) return
      this.ws = null
      window.clearInterval(this.pingTimer)
      this.pending.forEach((p) => {
        window.clearTimeout(p.timer)
        p.reject(new Error('disconnected'))
      })
      this.pending.clear()
      this.scheduleRetry()
    }
  }

  private scheduleRetry() {
    this.setState('offline')
    if (this.users === 0) return
    window.clearTimeout(this.retryTimer)
    // 1s, 2s, 4s … up to 30s, with jitter so a server restart isn't hit by everyone at once.
    const delay = Math.min(30_000, 1000 * 2 ** this.attempts) * (0.75 + Math.random() * 0.5)
    this.attempts += 1
    this.retryTimer = window.setTimeout(() => this.connect(), delay)
  }

  private close() {
    window.clearTimeout(this.retryTimer)
    window.clearInterval(this.pingTimer)
    const ws = this.ws
    this.ws = null
    ws?.close()
    this.setState('offline')
  }
}

export const supportSocket = new SupportSocket()

/** Keep the socket open while the component is mounted; returns its connection state. */
export function useSupportSocket(onEvent: (e: SupportEvent) => void): SocketState {
  const [state, setState] = useState<SocketState>(supportSocket.state)
  const handler = useRef(onEvent)
  handler.current = onEvent

  useEffect(() => {
    const offEvent = supportSocket.on((e) => handler.current(e))
    const offState = supportSocket.onState(setState)
    supportSocket.acquire()
    // Signed out and in again: reconnect with the new token.
    const offToken = tokenStore.subscribe((access) => {
      if (!access) supportSocket.release()
    })
    return () => {
      offEvent()
      offState()
      offToken()
      supportSocket.release()
    }
  }, [])

  return state
}
