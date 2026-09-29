# On-call console

Install with `npm ci`, then use `npm run dev` while the API runs on `127.0.0.1:8000`. Vite proxies `/api` to that backend. `npm run build` produces `dist/` for FastAPI to serve.

The console fetches its CSRF token from `/api/status` and includes it on writes. It never stores cloud credentials. Messages and tool results render as plain text. Only HTTPS links to Google Cloud's console or documentation are rendered as evidence links.

Desktop uses an incident sidebar, conversation, and evidence/activity context. At tablet widths the context moves below the conversation; on phones incidents become a horizontal selector. The display never infers health from connectivity or incident status.

Verification: run `npm run build`; use the integrated backend for end-to-end interaction checks. Check empty and disconnected states, new investigation, selecting an alert, asking a follow-up, tool activity, evidence, failed send with retained text, and closing with notes. Browser checks belong to the integrated application rather than fabricated production observations.
