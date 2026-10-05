/**
 * Live support chat (backend: app/modules/support/realtime.py).
 *
 * One WebSocket while a conversation is on screen: messages arrive instantly, with typing and
 * read receipts. It sends the access token in its first frame, reconnects with backoff, drops
 * while the app is in the background and comes back on return. If it isn't connected, the
 * screen sends over HTTP as before; nothing depends on the socket being up.
 */
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';

import { getAccessToken, newIdempotencyKey, refreshSession } from '@/api/client';
import { API_ORIGIN } from '@/api/config';
import type { SupportMessage, SupportTicket } from '@/api/types';
import { keys } from '@/lib/queries';

const URL = `${API_ORIGIN.replace(/^http/, 'ws')}/api/v1/ws/support`;
const SIGN_IN_AGAIN = 4401;

type Status = SupportTicket['status'];
type Ack = { message: SupportMessage; status: Status };
type ServerFrame =
  | { type: 'ready' | 'pong' }
  | { type: 'ack'; client_id: string; ticket_id: string; status: Status; message: SupportMessage }
  | { type: 'error'; client_id?: string; code: string; message?: string }
  | { type: 'message'; ticket_id: string; status: Status; message: SupportMessage }
  | { type: 'typing'; ticket_id: string; author: 'customer' | 'staff' }
  | { type: 'read'; ticket_id: string; by: 'customer' | 'staff'; at: string }
  | { type: 'ticket'; ticket_id: string; status: Status };

export type ChatState = 'connecting' | 'live' | 'offline';

/** Adds a message to the cached conversation (once, even if it arrives twice). */
function withMessage(t: SupportTicket | undefined, m: SupportMessage, status: Status): SupportTicket | undefined {
  if (!t || t.messages?.some((x) => x.id === m.id)) return t;
  return {
    ...t,
    status,
    messages: [...(t.messages ?? []), m],
    awaiting_reply: m.author === 'customer',
    reply: m.author === 'staff' ? m.body : t.reply,
  };
}

export function useSupportChat(ticketId: string) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<ChatState>('connecting');
  const [staffTyping, setStaffTyping] = useState(false);
  const ws = useRef<WebSocket | null>(null);
  const pending = useRef(new Map<string, { resolve: (a: Ack) => void; reject: (e: Error) => void }>());
  const lastTyping = useRef(0);

  useEffect(() => {
    let closed = false;
    let attempts = 0;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let ping: ReturnType<typeof setInterval> | undefined;
    let typingTimer: ReturnType<typeof setTimeout> | undefined;

    const update = (fn: (t: SupportTicket | undefined) => SupportTicket | undefined) => {
      queryClient.setQueryData<SupportTicket>(keys.ticket(ticketId), fn);
    };

    const onFrame = (f: ServerFrame) => {
      switch (f.type) {
        case 'ready':
          attempts = 0;
          setState('live');
          clearInterval(ping);
          ping = setInterval(() => ws.current?.send(JSON.stringify({ type: 'ping' })), 25_000);
          return;
        case 'ack':
        case 'error': {
          const p = f.client_id ? pending.current.get(f.client_id) : undefined;
          if (!p) return;
          pending.current.delete(f.client_id!);
          if (f.type === 'ack') p.resolve({ message: f.message, status: f.status });
          else p.reject(new Error(f.message ?? f.code));
          return;
        }
        case 'message':
          queryClient.invalidateQueries({ queryKey: keys.tickets });
          if (f.ticket_id !== ticketId) return;
          setStaffTyping(false);
          update((t) => withMessage(t, f.message, f.status));
          return;
        case 'typing':
          if (f.ticket_id !== ticketId || f.author !== 'staff') return;
          setStaffTyping(true);
          clearTimeout(typingTimer);
          typingTimer = setTimeout(() => setStaffTyping(false), 5000);
          return;
        case 'read':
          if (f.ticket_id !== ticketId || f.by !== 'staff') return;
          update((t) =>
            t && {
              ...t,
              messages: t.messages?.map((m) => (m.author === 'customer' && !m.read_at ? { ...m, read_at: f.at } : m)),
            },
          );
          return;
        case 'ticket':
          if (f.ticket_id === ticketId) update((t) => t && { ...t, status: f.status });
          queryClient.invalidateQueries({ queryKey: keys.tickets });
          return;
      }
    };

    const failPending = () => {
      pending.current.forEach((p) => p.reject(new Error('disconnected')));
      pending.current.clear();
    };

    const connect = () => {
      if (closed || AppState.currentState !== 'active') return;
      const token = getAccessToken();
      if (!token) return schedule();
      setState('connecting');
      const socket = new WebSocket(URL);
      ws.current = socket;
      socket.onopen = () => socket.send(JSON.stringify({ type: 'auth', token }));
      socket.onmessage = (ev) => {
        try {
          onFrame(JSON.parse(String(ev.data)) as ServerFrame);
        } catch {
          /* ignore a malformed frame */
        }
      };
      socket.onclose = (ev) => {
        if (ws.current !== socket) return;
        ws.current = null;
        clearInterval(ping);
        failPending();
        setState('offline');
        // Token expired while connected: refresh it, then reconnect straight away.
        if (ev.code === SIGN_IN_AGAIN) {
          refreshSession()
            .then((ok) => ok && connect())
            .catch(() => schedule());
          return;
        }
        schedule();
      };
    };

    const schedule = () => {
      if (closed) return;
      clearTimeout(retry);
      // 1s, 2s, 4s … 30s, with jitter.
      const delay = Math.min(30_000, 1000 * 2 ** attempts) * (0.75 + Math.random() * 0.5);
      attempts += 1;
      retry = setTimeout(connect, delay);
    };

    const disconnect = () => {
      clearTimeout(retry);
      clearInterval(ping);
      const socket = ws.current;
      ws.current = null;
      socket?.close();
      failPending();
      setState('offline');
    };

    const sub = AppState.addEventListener('change', (next) => {
      if (next === 'active') {
        attempts = 0;
        if (!ws.current) connect();
        // Catch up on anything sent while we were away.
        queryClient.invalidateQueries({ queryKey: keys.ticket(ticketId) });
      } else {
        disconnect();
      }
    });

    connect();
    return () => {
      closed = true;
      sub.remove();
      clearTimeout(typingTimer);
      disconnect();
    };
  }, [ticketId, queryClient]);

  const live = state === 'live';

  return {
    state,
    live,
    staffTyping,
    /** Resolves when the server has saved it. Rejects when offline, so the caller uses HTTP. */
    send(body: string): Promise<Ack> {
      const socket = ws.current;
      if (!live || !socket) return Promise.reject(new Error('offline'));
      const clientId = newIdempotencyKey();
      return new Promise<Ack>((resolve, reject) => {
        const timer = setTimeout(() => {
          pending.current.delete(clientId);
          reject(new Error('timeout'));
        }, 10_000);
        pending.current.set(clientId, {
          resolve: (a) => {
            clearTimeout(timer);
            update(a);
            resolve(a);
          },
          reject: (e) => {
            clearTimeout(timer);
            reject(e);
          },
        });
        socket.send(JSON.stringify({ type: 'send', ticket_id: ticketId, body, client_id: clientId }));
      });

      function update(a: Ack) {
        queryClient.setQueryData<SupportTicket>(keys.ticket(ticketId), (t) => withMessage(t, a.message, a.status));
        queryClient.invalidateQueries({ queryKey: keys.tickets });
      }
    },
    typing() {
      const now = Date.now();
      if (!live || now - lastTyping.current < 2500) return;
      lastTyping.current = now;
      ws.current?.send(JSON.stringify({ type: 'typing', ticket_id: ticketId }));
    },
    read() {
      if (live) ws.current?.send(JSON.stringify({ type: 'read', ticket_id: ticketId }));
    },
  };
}
