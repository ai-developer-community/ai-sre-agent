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

Desktop uses a 232px incident sidebar, compact service metadata, and a viewport-height conversation with a persistent composer. A selected incident adds a 280px evidence/activity column. The empty state is a single column with three suggested questions. Below 900px, context follows the conversation; below 600px, incidents become a horizontal selector and the page scrolls normally.

## Behavior and safety

Polling, chat submission, CSRF, disabled run states, failed-send draft preservation and human closure remain unchanged. Monitoring payloads are retained behind a native disclosure. Assistant Markdown renders headings, lists and code without raw HTML or image loading. Links are restricted to Google Cloud HTTPS hosts. Ordinary user messages remain literal text. Evidence JSON and tool details stay expandable. The model name remains visible; the decorative footer tagline is removed.

## Accessibility and verification

Named controls, keyboard focus, native disclosure controls, text accompanying status colours, reduced motion and responsive wrapping. Desktop and mobile are checked against real cloud incident records. Message-rendering tests cover formatting, unsafe links, HTML/images, collapsed notifications and literal user text.

## Scope

This is a direct refinement of the existing console to the user's explicit light-mode brief. The previous incomplete concept-round metadata is historical; no new concept-comp workflow is claimed or repaired by this change.
