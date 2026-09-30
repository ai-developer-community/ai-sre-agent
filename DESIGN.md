# Console design

## Direction

A minimal light operations console, as requested by the user. White workspace, pale grey incident sidebar, dark text and quiet dividers. Conversation leads; evidence and activity appear beside a selected incident. No decorative tagline, simulated telemetry or empty dashboard panels.

## Tokens

- Background `#ffffff`, sidebar `#f7f8fa`, primary text `#202328`.
- Secondary text `#646b75`, dividers `#e5e7eb`, links and focus `#294ec4`.
- Amber identifies open incidents; green identifies resolved incidents and an API connection, never inferred service health.
- System sans for the operator interface; monospace only for code and raw observations.
- Body text 14px, supporting UI 11–13px, page title 23px. Small controls use 6–8px corners; composer uses 12px.

## Layout

Desktop uses a 224px incident sidebar, a quiet Operations header, and a viewport-height conversation with a persistent composer. A selected incident adds a 260px evidence/activity column. Closed history uses a plain heading. The home dashboard shows real incident totals, active investigations and recent closed history. New investigation opens a conversation with suggested questions. Below 900px, context follows the conversation; below 600px, the incident list is bounded and the page scrolls normally.

## Behavior and safety

Polling, chat submission, CSRF, disabled run states, failed-send draft preservation and human closure remain unchanged. Monitoring payloads are retained behind a plain View button. Assistant Markdown renders headings, lists and code without raw HTML or image loading. Links are restricted to Google Cloud HTTPS hosts. Ordinary user messages remain literal text. Evidence JSON and tool details stay expandable. The internal service name is omitted from the header; the decorative footer tagline is removed.

## Accessibility and verification

Named controls, keyboard focus, plain detail buttons, text accompanying status colours, reduced motion and responsive wrapping. Desktop and mobile are checked against real cloud incident records. Message-rendering tests cover formatting, unsafe links, HTML/images, collapsed notifications and literal user text.

## Scope

This is a direct refinement of the existing console to the user's explicit light-mode brief. The previous incomplete concept-round metadata is historical; no new concept-comp workflow is claimed or repaired by this change.

## Incident attention and approved recovery

The dashboard shows active incidents, incidents needing attention, and investigations in progress. Completing triage leaves attention amber. A chat command prepares a named rollback proposal with explicit Approve and Deny buttons. Denial leaves traffic unchanged and the incident open. Execution shows Rolling back and Verifying recovery; only verified checkout probes produce the green Recovery verified result, with its observation time. Manually closed records remain labelled Closed. The existing light visual system is preserved.

## Shared React components

`components.jsx` owns Button, Notice, StatusBadge, Sidebar, ConsoleHeader, Conversation, RollbackCard, Composer and ContextPanel. `main.jsx` owns polling, selection and API mutations. Status labels come from `incident-state.js`. Evidence and Activity use simple selection buttons. Raw observations use View details buttons. Revision names are visible in approval cards. Chat messages use consistent spacing without divider lines. The decision card sits outside the scrolling message list so approval controls remain visible. The page avoids repeating the incident state in a banner, panel heading and footer.

## Visual polish

Lucide outline icons identify overview navigation, incident rows, chat authors, evidence/activity and approval decisions. The homepage uses one status banner and compact attention/investigation counts; investigation headers omit the repeated count strip. Unknown status uses a neutral surface. Incident rows and chat messages rely on spacing instead of repeated rules. The explicit Overview button returns home, and the breadcrumb identifies the current view. Status meaning, real observations and approval behavior are unchanged.
