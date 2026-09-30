# Light console verification

30 September 2026. Scope: simplify the existing console, use light mode, remove the decorative footer tagline.

- **Chat and closure: pass.** Sent a clearly labelled UI smoke-test message through the browser to the hosted agent. Received its acknowledgement, then saved resolution notes and closed that test record. No service-health claim was made. Existing operational incidents were not closed.
- **Evidence and activity: pass.** Opened the real checkout incident, inspected its seven evidence records and fourteen tool events, and exercised the closure form with cancel.
- **Desktop layout: pass.** At 1280×720 the composer bottom was 675.5px, inside the viewport. Conversation scrolls independently. New investigations omit the empty context panel.
- **Mobile layout: pass.** At 390×844, document scroll width equals the viewport width. Incidents scroll horizontally inside their selector; context follows the conversation.
- **Message rendering: pass.** Four automated tests check Markdown formatting, Google Cloud link restrictions, blocked HTML and remote images, collapsed notifications, and literal user text.
- **Build: pass.** React production build succeeds. Browser reported no errors or warnings during the checked flows.
- **Tagline: removed.** The footer retains the configured provider/model only.

Commands: `npm test --prefix frontend`, `npm run build --prefix frontend`, `git diff --check`. CI runs the new rendering tests alongside existing backend tests.

The design detector reported no code findings. Its historical incomplete concept-round metadata predates this refinement and was not changed. The user's explicit light-mode brief and real browser checks determine this change's design direction.
