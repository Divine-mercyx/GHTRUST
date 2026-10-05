# Live support chat

Customers and staff chat in a support request in real time: messages appear instantly, with a typing indicator
and "Seen" receipts. The HTTP routes still work as the fallback; they publish the same live events, so a reply
sent either way reaches the other side at once.

## How it connects

| Who | Socket | Auth |
|---|---|---|
| App | `wss://<api>/api/v1/ws/support` | first frame `{"type":"auth","token":"<access token>"}` |
| Portal | `wss://<api>/api/v1/ws/admin/support` | same, staff token; needs `support:read` (`support:respond` to reply) |

The token goes in the first frame because browsers can't put headers on a WebSocket. A bad or expired token
closes the socket with code 4401. The app then refreshes its session and reconnects.

**Vercel can't proxy WebSockets**, so the deployed portal connects straight to the API host:
`wss://ghtrust-production.up.railway.app` by default, or `VITE_WS_URL` if it is set at build time. Locally, the
Vite dev server proxies `/api` WebSockets to `localhost:8000`.

Both clients reconnect with backoff (1 s, 2 s, 4 s … 30 s), ping every 25 s, and the app disconnects while in the
background. The portal shows a **Live / Connecting / Offline** badge.

## Protocol

Client → server: `send {ticket_id, body, client_id}`, `typing {ticket_id}`, `read {ticket_id}`, `ping`.

Server → client: `ready`, `ack {client_id, message}` (the message was saved), `error {client_id, code}`,
`message`, `typing`, `read {by, at}`, `ticket {status}`, `pong`.

Customers only reach their own requests. Staff see every request. Customers see replies from "GH Trust support";
staff see the colleague's name.

## Several API workers

The API runs `WEB_CONCURRENCY` processes, so events go through Redis pub/sub (channel `support:events`) to reach
sockets held by the other processes. Each process also delivers its own events directly, so chat still works
within one process if pub/sub is down. No extra Railway setup is needed beyond the existing Redis.

Code: `backend/app/modules/support/realtime.py`, `admin/src/lib/supportSocket.ts`,
`mobile/src/lib/supportSocket.ts`. Tests: `backend/tests/integration/test_support_realtime.py`.
