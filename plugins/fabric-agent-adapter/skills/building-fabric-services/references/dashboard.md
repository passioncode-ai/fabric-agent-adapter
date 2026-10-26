# Dashboard principles

The dashboard is where the operator decides; it must stay truthful when parts of the
service are not.

1. **Same origin, static assets.** HTML shell plus hashed `app.js`/`app.css` from a
   whitelist; no inline script; a strict CSP. Nothing from a CDN: the page must work
   offline on a plane.
2. **State first, then detail.** The top of every page answers "is it working, and
   does it need me?": the same `status`, `degraded` and attention tiles the
   well-known document publishes, so the page and Fabric Dashboards never disagree.
3. **Calm refresh.** Poll the page's own API every 5 s while visible, back off when
   hidden, and pause while a field is focused, a form has unsaved input or a dialog is
   open. Replace a region only when its data changed; keep focus, scroll and open
   sections.
4. **Partial failure stays partial.** Load panels independently (`Promise.allSettled`);
   a failed panel shows its own one-sentence error and a retry, and the rest render.
5. **Every error is a sentence and an action.** "Store listing push failed: App Store
   Connect rejected the key. Settings → Keys", never a status code, a stack trace or a
   blank area. Show when data was last fresh.
6. **Server down is a state, not a crash.** When the API stops answering, keep the
   last data greyed with "Service not answering since 17:02", and recover by itself
   when it returns.
7. **Approvals show the diff and its hash.** Any write the operator approves shows
   before → after and the hash the service will verify at apply time.
8. **Every button has an agent twin** (contract DEC-0121 AP-1). Each action the page lets a
   person take (approve, reject, choose, edit, pause, resume, cancel, retry, send, publish,
   restore, set a policy) is a tool with the same effect, checks, audit record and an
   idempotency key, declared in the well-known document's action table; a `relayed` action
   takes the operator's decision from their agent as from a click. Never answer an agent
   "open the dashboard" for an action the page offers, except a step only a person can take, which answers
   `human-step-required` with its link (AP-4; [interop](interop.md#actions)).
9. **Theme and width.** Build the page from the dashboard kit: its seven AA themes, light and
   dark, follow `prefers-color-scheme` and the host's `fabric_appearance` cookie, and its layout
   holds from 360 CSS px inside a host pane (`fabric-dashboard/0.1`, DEC-0036;
   [the dashboard kit reference](dashboard-kit.md)). Never encode meaning by colour alone.
10. **Links into the page are stable.** Event `link`s point at hash routes that survive
   a reload (`/dashboard#/approvals/77`) so a notification opens the exact item.
11. **No second browser tab required.** With Fabric Dashboards installed, the page is
    shown inside it and opens only there: its `open_link`, opened with `fallback=never`
    ([dashboard links](dashboard-links.md)); do not open windows or tabs on your own; use
    in-page dialogs.
