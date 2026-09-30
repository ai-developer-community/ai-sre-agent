# Console design

## Direction

A restrained dark operations console, matching the user's requested recording surface. Product clarity leads: an incident ledger on the left, conversation in the center, evidence and tool activity on the right. No simulated telemetry or dashboard filler.

## Tokens

- Background `#111513`, sidebar `#151a17`, conversation `#181e1a`.
- Primary text `#e4e9e5`, secondary text `#9ca99f`.
- Human action accent `#c5e6ab`; active incidents use amber `#e1b975`.
- Borders `#2b332e`; compact controls use 5–9px corners, workspace 10px.
- System sans text for operator familiarity; monospace reserved for tool JSON.

## Layout

Desktop uses a 244px incident sidebar and flexible main region. Main content has a conversation and 300px context panel. Below 850px, context follows chat. Below 600px, sidebar becomes a horizontal incident selector. The conversation scrolls independently on desktop, preserving the input and evidence context.

## Behavior

Polling refreshes incident and tool records. No false health indicator: the service bar explicitly says health requires a fresh investigation. The composer disables while the selected investigation is queued or running. Resolved incidents remain readable. Evidence links open only approved Google Cloud HTTPS destinations; message and tool content renders as text. Failed sends preserve the question. Incident closure uses inline resolution notes.

## Accessibility

Named inputs, explicit button labels, keyboard focus outlines, responsive text wrapping, reduced-motion support, and text accompanying all status colors. Muted text maintains legibility against dark surfaces. Generated activity is presented as tool actions, never private model reasoning.

## Execution scope

This minimalist demo was built directly in code from the user's pinned operations-console brief. A direction seed was invoked and returned a degraded result without challengers; the full direction-roll decision workflow and FORM contract were omitted. The delivered interface is therefore reviewed against the concrete user brief and live browser behavior, rather than claiming a completed concept-selection process or an approved image comp.

Desktop layout uses a viewport-height flex column: actual banner, header and service-bar heights determine the remaining workspace height. Conversation content scrolls inside that remaining space, keeping the composer and Send button visible. At tablet and phone widths, the page uses normal vertical scrolling and the context panel follows the conversation.
