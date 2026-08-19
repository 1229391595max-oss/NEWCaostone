# BizPulse CAPTSONE Frontend Visual Migration Design

Status: Approved direction — amendment ready for user review

Approved on: 2026-08-15 (America/Chicago)

Amended on: 2026-08-15 (America/Chicago)

Document revision: 1.1

Target repository: `/Users/maxli/Desktop/NEWCaostone`

Read-only visual reference: `/Users/maxli/Desktop/CAPTSONE`

## 1. Outcome

Move the established CAPTSONE frontend visual language into NEWCaostone while
preserving NEWCaostone's current behavior, security boundaries, routes, data
flows, and feature set. Close the bounded presentation-layer gaps found in the
current implementation audit so that the redesigned interface does not preserve
known misleading, inconsistent, or inaccessible behavior.

The selected direction is **A: Product Theater / CAPTSONE extension**:

- warm off-white surfaces;
- violet focus and selection states;
- compact analytical cards;
- a 56px icon navigation rail;
- a restrained top bar and contextual subnavigation;
- shared status badges, evidence drawer, filters, tables, and chart treatments;
- premium public and sign-in entries built around four timed product visuals.

This is a visual and presentation-layer redesign plus a bounded frontend quality
closure. It may introduce shared display formatters, complete language-state
handling, wire existing logout/session-end APIs into visible controls, remove
nonfunctional navigation labels, and repair documented accessibility behavior.
It is not permission to replace working business behavior, change an API or
database contract, weaken access control, alter the viewer/operator boundary,
change authoritative calculations, configure a secret, make a paid provider
request, or deploy anything.

## 2. Authority And Compatibility

This design is a focused visual overlay on the approved product design:

- `docs/superpowers/specs/2026-08-13-newcaostone-demo-single-operator-design-v0.2.0.md`

If this document conflicts with that design on data, security, AI authority,
session isolation, or business behavior, the approved `v0.2.0` contract remains
authoritative. This document is authoritative for the visual and public-copy
decisions listed here.

The CAPTSONE visual reference was inspected at immutable commit:

- `3af1c6bc20e9b925b148d05b6da4f4301310c293`

The inspected tracked frontend files were clean relative to that commit. The
principal visual references are:

- `bizpulse/frontend/assets/styles.css`;
- `bizpulse/frontend/index.html`;
- `bizpulse/frontend/welcome.html`;
- `bizpulse/frontend/login.html`;
- `bizpulse/frontend/assets/views.mjs`;
- the feature view modules under `bizpulse/frontend/assets/features/`.

The first NEWCaostone implementation snapshot inspected during visual design
was:

- `c4e6427fccc4352b367206da720cb702808ae26f`

Another task is actively advancing that implementation line. The implementation
plan must refresh the exact target commit and current tests before editing. It
must preserve newer behavior rather than resetting the target to this snapshot.

The expanded frontend audit refreshed the active implementation content at:

- `c1010d23b2ec4bfac851afc1617ea49083906493`.

During this amendment, the adjacent branch advanced to detached attestation
child `323e9c934936f713dc4422b8c2aa7364a81ff389`. The only tree change after
`c1010d2` is the candidate's attestation JSON; the inspected frontend content is
unchanged. That attestation records the `c1010d2` candidate as locally verified
(`522 passed` plus its declared frontend/browser gates) and explicitly not CI
verified, deployed, hosted verified, Azure-Demo-accepted, or Production-ready.

Its no-AI work makes an absent Chat service safe and visible; it does not
configure an OpenAI Key. The separate read-only current-status record describes
an older Azure revision as online and healthy but AI-disabled, with hosted
acceptance incomplete. These are dated design inputs, not permanent release
authority; implementation and release work must refresh Git, the current
attestation, and hosted state again.

## 3. Confirmed Decisions

The user approved all of the following:

1. Scope **B**: redesign the authenticated/viewer application plus the public
   welcome and sign-in pages.
2. Visual direction **A**: extend the CAPTSONE product-workbench style.
3. The public entry and sign-in page use a shared four-slide timed product
   showcase with restrained effects and product visuals. The sign-in form stays
   fixed and usable while only its supporting visual changes.
4. Public-facing `Operator sign in` becomes `Sign in`; Chinese copy is `登录`.
5. User-facing references to `Course Demo` are removed wherever the same safety
   boundary can be communicated with `Preview`, `Synthetic Data`, or equivalent
   plain-language copy.
6. NEWCaostone's current functionality remains intact.
7. User-facing numeric values use no more than two fractional digits unless a
   stronger semantic rule applies. BRL currency always shows two digits; counts
   remain integers. Backend Decimal values, API payloads, calculations, source
   records, formulas, and evidence authority remain unchanged.
8. The language control performs an actual English/Chinese switch on the public
   entry, sign-in page, application shell, feature copy, status labels, and safe
   error messages. It does not merely change the document language attribute.
9. The operator application exposes `Sign out` through the existing protected
   logout contract. The public viewer exposes a clearly named session-end action
   through its existing Demo-session contract.
10. Navigation presents only working destinations. `Product Opportunities`,
    `Favorites`, and `Operating Advice` are not shown as inert pseudo-controls.
11. The requested final Azure Demo must have Ask BizPulse enabled with a
    dedicated server-side OpenAI Key. The Key never appears in HTML, browser
    state, logs, source control, or a user-entered field. Secret configuration,
    Azure mutation, and any paid smoke remain a separately authorized release
    operation; this document records the acceptance dependency but does not
    authorize it.

## 4. Approaches Considered

### 4.1 Selected: Visual-system adapter plus bounded UI closure

Apply CAPTSONE tokens, shell geometry, card density, status treatments, and
evidence patterns to NEWCaostone's existing DOM and feature modules. Add one
isolated Product Theater component, reuse it on the public and sign-in pages,
and package its local visual assets once. In the same frontend batch, centralize
display-only numeric formatting, complete language behavior, wire the existing
session-exit endpoints, remove inert navigation labels, and close the
accessibility gaps that directly affect the redesigned components.

This provides the strongest visual continuity while keeping current state,
effects, API clients, routes, and feature contracts in place. It also avoids
polishing broken interaction affordances into a more convincing but still
misleading interface.

### 4.2 Rejected: Dark cinematic entry with a light application

A black-violet public entry has more immediate visual impact, but it creates an
unnecessary stylistic break at sign-in and makes the public page feel more like
a separate campaign site.

### 4.3 Rejected: Copy the CAPTSONE frontend wholesale

A whole-frontend copy would overwrite or omit NEWCaostone capabilities such as
the public release boundary, new-product forecast, Profit Bridge, Ask BizPulse,
and the current Action Card flow. It is explicitly outside scope.

### 4.4 Rejected: Full historical feature parity in this batch

Building Product Opportunities, Favorites, Operating Advice, a new AI budget
status API, or a dedicated AI forecast-intake workflow would require new product
contracts, persistence/API decisions, and separate acceptance evidence. Those
are not presentation repairs and would make this design too large to implement
and verify safely as one frontend migration.

The current inert labels for those destinations are removed. A later product
design may reintroduce a destination only after it has a reachable route,
working state/effects/data-source chain, tests, and a safe synthetic-data
contract.

### 4.5 Rejected: Cosmetic-only migration

A CSS-only pass would leave a false language switch, no visible operator logout,
raw six-place forecast values, inaccessible drawer/tab behavior, and inert
navigation labels. It does not meet the amended quality bar.

### 4.6 Current implementation audit

The audit distinguishes implementation from runtime enablement and hosted
acceptance:

| Surface | Audited state | This design's treatment |
|---|---|---|
| Viewer/operator sessions, import workflow, version publish, Overview, Sales, Inventory, Profit, deterministic Forecast, Profit Bridge, Ask BizPulse, and Action Inbox/Action Cards | Implemented in the active local line; hosted acceptance remains separate | Preserve reducers, effects, APIs, permissions, and business behavior while restyling |
| Public Product Theater and advanced sign-in presentation | Not implemented | Implement one shared four-slide timed experience, with a fixed usable form on `/login` |
| `Operator sign in` and Course-specific public wording | Still present in current HTML | Apply the approved `Sign in`, `Preview`, and `Synthetic Data` copy map |
| Public/sign-in language control | Only changes `html.lang`; current public catalogs are incomplete | Implement one shared, persistent language state and translated static/dynamic copy |
| Operator logout | Backend route exists; no application control reaches it | Add a protected `Sign out` control without changing the endpoint |
| Product Opportunities, Favorites, Operating Advice | Inert labels or inconsistent placeholders; no working destination | Remove from current navigation and record as deferred product work |
| Numeric presentation | BRL metrics are mostly two-place; forecast scores/factors/backtests, structured Chat facts, Action details, and some chart labels may expose raw precision | Use a shared display-only formatting contract across every user-facing numeric surface |
| AI availability | Ask BizPulse backend and enabled-state path exist; current hosted configuration is AI-disabled and the adjacent task is hardening the disabled projection | Preserve both available and unavailable UI states; require a separately authorized server-Key enablement before final Azure Demo acceptance |
| Dedicated AI forecast input structuring | Not present; the current forecast is deterministic and `Ask about this` is the available explanation handoff when Chat is enabled | Preserve the deterministic forecast; defer a new AI intake workflow to a separate product design |
| Operator AI budget/system status | Full UI/API projection is not present | Show the existing availability state only; defer new budget/status data contracts |
| Evidence drawer, forecast tabs, line-chart summary | Known non-blocking accessibility gaps | Close focus/Escape/restore behavior, tab semantics, keyboard behavior, and accessible value summaries |

Backend refinements already recorded elsewhere—such as storage-failure HTTP
semantics or additional persistence fault-injection coverage—remain valid
follow-up work, but they are not silently pulled into this frontend design.

## 5. Visual System

### 5.1 Core tokens

Use the CAPTSONE palette as the application-wide base:

| Role | Value |
|---|---|
| Page surface | `#f6f5f1` |
| Navigation/subtle surface | `#efeee8` |
| Card surface | `#ffffff` |
| Primary text | `#1f1f1d` |
| Secondary text | `#5f5e5a` |
| Muted text | `#8a8983` |
| Border | `#e3e1d8` |
| Strong border | `#cfcdc3` |
| Primary violet | `#534ab7` |
| Violet tint | `#eeedfe` |
| Success | `#0f6e56` / `#e1f5ee` |
| Warning | `#854f0b` / `#faeeda` |
| Danger | `#a32d2d` / `#fcebeb` |

Use the existing system font stack. Typography should remain compact and
operational inside the application; the public entry may use larger display
type while retaining the same family.

### 5.2 Shape, depth, and density

- Application cards use 8-10px radii and fine borders.
- Public-entry showcase frames may use 16-20px radii and restrained depth.
- Shadows remain subtle inside the application and stronger only around the
  public product frame and evidence drawer.
- Data density follows CAPTSONE: four KPI cards may share one desktop row;
  analytical cards use 12-16px internal spacing.
- Violet indicates selection, focus, and primary action. It does not encode a
  business result.
- Green, amber, and red retain semantic meaning for positive/ready, warning, and
  critical states.

### 5.3 Charts and imagery

Charts are analytical, not decorative. Each chart must use data already
available to the current feature and must preserve missing/partial/unknown
states.

The public and sign-in pages share four product-effect visuals made only from
synthetic data:

1. Today Overview: revenue, ROAS, contribution profit, trend, and one priority
   signal.
2. Profit Bridge: period-over-period waterfall and reconciliation state.
3. New Product Forecast: low/base/high ranges for 7/30/90 days.
4. Ask BizPulse: one question, concise answer, linked facts, sources, and
   limitations.

These visuals should be local SVG or optimized WebP assets. Do not use stock
photography, real product imagery, real business data, remote image CDNs, or an
external icon CDN. The first slide is available immediately; later visuals may
be lazy-loaded. `/` and `/login` reuse the same asset URLs rather than shipping
duplicate artwork. The compressed shared visual budget should remain below 500
KiB in total unless measurement demonstrates a justified exception.

### 5.4 Numeric display contract

Formatting is a presentation concern. Every view model and chart that exposes a
user-facing number uses one shared formatter boundary instead of locally calling
`toFixed`, interpolating a raw Decimal string, or relying on default
`Intl.NumberFormat` behavior.

| Semantic value | Display rule | Example |
|---|---|---|
| BRL currency and signed BRL deltas | Exactly two fractional digits | `R$ 1,234.50`, `−R$ 42.10` |
| Integer counts, quantities, orders, and unit forecasts | No fractional digits; reject non-integer authority where an integer is required | `168 units` |
| Ratios, scores, multipliers, and ordinary decimals | Zero to two fractional digits | `0.99`, `1.2×` |
| Percentages backed by a known ratio contract | Multiply by 100 and show two fractional digits plus `%` | WAPE `0.05` → `5.00%` |
| Days and coverage values | Zero to two fractional digits | `2 days`, `3.25 days` |
| Missing, invalid, partial, or unknown values | Preserve the current explicit unavailable/unknown state; never coerce to zero | `Unavailable` |

Known semantic fields such as WAPE and interval coverage may be converted to a
percentage. Generic Chat facts, evidence values, or imported fields must not be
reinterpreted by label guessing. A generic numeric scalar may be rounded for
display, but its unit and scale remain exactly what the server supplied.

The display rule applies to KPI cards, chart labels and accessible summaries,
forecast analog scores/components/factors/backtest, inventory days, structured
Ask BizPulse facts, Action Card thresholds/impact/evidence/history, and release
presentation values. It does not apply to:

- backend Decimal arithmetic or quantization;
- API request/response contracts or persisted values;
- editable form values before submission;
- the exact import/workspace JSON preview;
- evidence formulas, source references, identifiers, version hashes, or digests;
- arbitrary AI prose, which must not be modified with a numeric regular
  expression.

Rounding occurs only at the final display boundary. Tests compare both the
formatted string and the untouched raw value so a presentation change cannot
silently become a calculation change.

## 6. Public Welcome Page

The `/` page is a product introduction and entry point, not a login form.

### 6.1 Desktop layout

- Top bar: BizPulse brand at left; language and `Sign in` at right.
- Left column: product eyebrow, headline, concise explanation, two actions, and
  a small synthetic-data boundary statement.
- Right column: the four-slide Product Theater.
- Primary action: `Try interactive preview` / `体验交互预览`.
- Secondary action: `Sign in` / `登录`.
- Boundary copy: `Synthetic workspace · No real customer data` with a concise
  Chinese equivalent.

Approved English headline:

> See the signal. Decide with evidence.

The supporting copy explains that BizPulse turns sales, advertising, inventory,
and cost data into an operating view and connects evidence to the next action.

### 6.2 Shared carousel behavior

The Product Theater on `/` and `/login` follows one controller and the same
four-slide sequence:

- Four slides in the order defined in section 5.3.
- Advance every 6 seconds.
- Pause on hover, keyboard focus within the carousel, manual interaction,
  document invisibility, or an inactive browser tab.
- A manual arrow, progress control, touch swipe, or keyboard action changes the
  slide and restarts the interval from zero after interaction ends.
- Show the slide number, title, and four progress indicators.
- Do not announce every automatic transition through an assertive live region.
- With `prefers-reduced-motion: reduce`, disable autoplay and 3D/perspective
  motion; show the first slide until the user changes it.
- If JavaScript is unavailable, the first visual and both primary links remain
  usable.

Animation is limited to crossfade, a small horizontal translation, subtle
gradient movement, and progress. No rapid zoom, continuous parallax, or looping
decorative particle field is allowed.

### 6.3 Responsive behavior

- At tablet width, reduce the copy-to-visual ratio without hiding content.
- At mobile width, stack copy above the visual.
- The effect frame loses perspective on small screens.
- Carousel controls remain at least 42px square.
- The public page must fit at 390px without horizontal scrolling.

## 7. Sign-In Page

The `/login` page remains a separate protected-entry screen.

### 7.1 Copy

- Page title and submit action: `Sign in` / `登录`.
- Do not show `Operator sign in` in the public interface.
- Supporting copy: `Use the configured account to open the private workspace.`
- The account field may retain its configured value and technical behavior, but
  visible copy should say `Account`, not emphasize the operator role.
- Provide a `Back to overview` link.

### 7.2 Layout

- Retain the BizPulse brand and CAPTSONE palette.
- Use a two-panel desktop composition: a fixed sign-in form and a compact
  version of the shared four-slide Product Theater.
- Keep the form title, fields, submit action, error region, and recovery link in
  a stable position. A timed visual change must never replace, cover, reset,
  submit, or move keyboard focus away from the form.
- Reuse the same slide order, 6-second interval, pause/resume rules, manual
  controls, reduced-motion behavior, synthetic boundary, and local assets from
  section 6.2. Do not create a second timer implementation.
- Keep the account and password fields, native autocomplete semantics, submit
  state, error region, and language control.
- On mobile, the compact carousel appears above the form, uses a fixed-height
  frame to prevent layout shift, and retains manual controls. Reduced-motion
  users receive the non-autoplay behavior defined in section 6.2.

The visual redesign must not change the existing login request, opaque cookie,
CSRF handling, redirect, account verification, or safe error behavior.

## 8. Application Shell

### 8.1 Desktop structure

- 56px fixed visual navigation rail with 42px controls.
- Violet BizPulse mark at the top.
- Six primary navigation controls with icons and accessible labels.
- Tooltips provide full labels on hover and keyboard focus.
- 64-66px header with page context, title, release/dataset state, freshness,
  language, and the relevant session/account action (`Sign out` for the operator
  or `End preview` for a viewer).
- A contextual subnavigation row appears only where a feature has secondary
  pages.
- Main content uses the compact CAPTSONE card grid.
- A shared evidence drawer opens from the right and restores focus to its
  invoker when closed.

### 8.2 Primary-route mapping

| Navigation label | Existing capability retained |
|---|---|
| Data Workspace / Data & Evidence | Operator import, mapping, standardization, preview, commit, release controls; viewer read-only release information |
| Today Overview | Current release KPIs, trends, readiness, anomalies, and linked evidence |
| Sales & Advertising | Current deterministic sales/advertising metrics, charts, comparisons, coverage, and evidence |
| Inventory & Replenishment | Current inventory risk and replenishment surfaces, including Ask BizPulse context handoff |
| Profit & Cost | Current profit facts, Profit Bridge, reconciliation, evidence, and Ask BizPulse context handoff |
| AI Decision Center | Ask BizPulse, New Product Forecast, and Action Inbox (existing Action Cards) |

Ask BizPulse remains the default AI Decision Center subpage. New Product
Forecast and Action Inbox remain sibling subpages, not new primary navigation
items. Individual records within Action Inbox remain Action Cards.

### 8.3 Shared presentation components

The following concepts receive one visual treatment across features:

- metric card;
- status badge (`measured`, `derived`, `partial`, `unknown`, `unavailable`);
- filter bar and context chip;
- chart card and chart caption;
- data table and horizontal-scroll boundary;
- empty, loading, unavailable, and safe-error state;
- action card and immutable revision/history block;
- evidence button and evidence drawer;
- primary, secondary, text, and destructive controls;
- AI availability notice and disabled composer state.

Implementation should prefer adding classes or presentation wrappers around
existing views. It must not replace reducers, effects, view-models, API clients,
or data-source classes solely to obtain the new look.

### 8.4 Responsive behavior

- At 820px and below, KPI grids reduce to two columns and analytical split views
  become one column.
- At 560px and below, KPI grids become one column, the rail narrows to 48px,
  controls remain at least 42px, and the evidence drawer occupies the width to
  the right of the rail.
- Long tables use a labeled horizontal-scroll region rather than compressing
  values into unreadable columns.
- Feature actions wrap without changing their DOM or keyboard order.

### 8.5 Session-exit controls

Session exit is a visible application-shell capability, not a decorative link.

For an operator:

1. `Sign out` sends the existing same-origin `POST /api/operator/logout` request
   with the current operator CSRF token.
2. The control disables and exposes a polite pending status while the request is
   in flight.
3. A successful response clears only the browser's operator CSRF state and
   redirects to `/`.
4. An already-expired session clears stale browser state and redirects to
   `/login` without claiming a successful server mutation.
5. Other failures keep the user on the page, re-enable the control, and render a
   safe localized error.

For a viewer, `End preview` uses the existing Demo-session deletion contract and
viewer CSRF token, clears only viewer session state after a successful or
already-expired result, and redirects to `/`. It replaces ambiguous wording that
suggests only Chat history is ending when the underlying action ends the viewer
session. Neither control changes cookie flags, server expiry, CSRF validation,
or session isolation.

## 9. Viewer And Operator Boundaries

The same shell serves both modes, but visual similarity must not imply equal
authority.

### Viewer

- Starts at Today Overview.
- Shows the exact pinned synthetic release.
- Data Workspace is labeled Data & Evidence and remains read-only.
- Viewer Action Card changes remain session-scoped simulations.
- No upload, publish, export, or outcome-recording authority is introduced.

### Operator

- Retains the complete Data Workspace import and release controls.
- Retains approved Action Card export and outcome-recording capabilities.
- Retains the current protected route, account session, CSRF, and authorization
  checks.

The redesign must not hide disabled authority through styling. Unavailable
actions remain absent or explicitly disabled according to the current contract.

### 9.1 AI runtime and Key boundary

Ask BizPulse has two legitimate presentation states:

- **Available:** the authenticated availability projection reports `available`;
  recommended questions and free text are enabled; evidence, limitations,
  saved Q&A, and Action-draft behavior remain server-authoritative.
- **Unavailable:** the authenticated projection reports `unavailable`; the page
  stays readable, recommended questions are absent, input/submit controls are
  disabled, and a concise localized explanation is visible. Mutations continue
  to fail closed.

The final requested Azure Demo state is the available state. It requires a
dedicated OpenAI Key in a server-side Azure secret, the server-owned AI flag,
all approved budget/rate limits, and the fixed product model configuration. The
browser receives only bounded availability and answer projections. It never
receives, stores, logs, requests, or lets the user enter the Key.

Frontend implementation verifies both states locally with deterministic fake
providers and no secret. Actual secret creation/update, enabling the hosted
flag, immutable-image/config publication, and any bounded paid provider smoke
belong to a separate hash-bound release authorization. A reachable URL or a
safe unavailable page does not satisfy the AI-enabled acceptance condition.

## 10. User-Facing Copy Migration

Reduce course-specific language without hiding the synthetic and non-production
boundary.

| Current or historical UI copy | Approved UI copy |
|---|---|
| `Operator sign in` | `Sign in` |
| `Try public Demo` | `Try interactive preview` |
| `Course Demo` | Omit, or use `Preview` when a noun is required |
| `Synthetic Demo Data` | `Synthetic Data` |
| `Demo snapshot` | `Preview snapshot` or exact release freshness |
| `Demo session` | `Preview session` |
| `Built-in Demo` | `Load sample data` when the action is user-visible |

Internal API paths, Python names, database names, error-code identifiers, tests,
and migration history containing `demo` or `course_demo` remain unchanged in
this visual migration. Renaming them would create risk without improving the
user experience and requires a separate approved refactor.

No copy may imply real-market validation, a Production environment, live
provider access, or real customer data. `Synthetic Data`, the pinned release,
and the Preview boundary remain visible where they affect interpretation.

### 10.1 Language behavior

English and Chinese are two complete UI catalogs, not simultaneous hard-coded
sentences and not a document-attribute-only toggle.

- One shared language controller supplies `get`, `set`, `toggle`, and translated
  lookup behavior to `/`, `/login`, `/demo`, and `/app`.
- The selection is stored in session-scoped browser storage so it survives
  navigation among those pages without becoming a durable account preference.
- Changing language updates `document.documentElement.lang`, static
  `data-i18n` nodes, dynamically rendered feature text, safe errors, pending
  states, status labels, chart captions, accessible names, and session actions.
- New keys must exist in both catalogs. Missing keys fail a frontend test and
  fall back to English at runtime without exposing `undefined` or a raw key.
- Business identifiers, evidence aliases, formula versions, source references,
  API error-code identifiers, hashes, and imported source values are not
  translated. Evidence states receive localized display labels while retaining
  their raw machine value.
- The selected language changes presentation only. It cannot change an API
  route, request payload, calculation, dataset version, session, or authority.

The language switch remains keyboard reachable and at least 42px in its compact
control dimension. Public/loading/sign-in error messages use the selected
catalog rather than overwriting a translated button with fixed English text.

## 11. Data And Interaction Flow

The presentation layer follows the existing flows:

```text
GET /
  -> static public story and local carousel visuals
  -> Try interactive preview uses the existing session-creation flow
  -> redirect to /demo only after a valid viewer session

GET /login
  -> existing account/password form
  -> existing POST /api/operator/login
  -> redirect to /app only after a valid protected session

GET /demo or /app
  -> existing runtime-session controller
  -> existing PublicDataSource or OperatorDataSource
  -> existing state/effects/view-models/views
  -> new visual classes, shared i18n/display formatters, and presentation wrappers

Operator Sign out
  -> existing POST /api/operator/logout with operator CSRF
  -> clear operator browser token after success/expiry handling
  -> redirect to / or /login according to the resolved session state

Viewer End preview
  -> existing DELETE /api/demo/sessions with viewer CSRF
  -> clear viewer browser token after success/expiry handling
  -> redirect to /
```

The carousel performs no business-data request and stores no account, session,
or business state. Product-effect visuals contain fixed synthetic presentation
data only.

## 12. Error And Degraded States

- If a later carousel asset fails, retain the gradient stage, slide title, and
  explanatory text; do not block either entry action.
- If carousel JavaScript fails, show the first slide as a static visual.
- Existing preview-session creation errors remain safe, visible, and do not
  redirect.
- Existing sign-in pending, invalid-credential, unavailable, and retry behavior
  remains fail-safe; its user-facing text becomes fully localized.
- Existing feature loading, empty, partial, unknown, and unavailable states must
  remain distinguishable after restyling.
- Safe error codes map to a concise localized primary message. A bounded
  technical code may remain available for support, but a raw identifier is not
  the only explanation shown to a normal user.
- Sign-out or preview-end failure does not clear a still-valid session, redirect
  as if successful, or leave its control permanently disabled.
- Real or operator requests must never fall back silently to showcase numbers.
- When AI service is unavailable, the current restricted projection remains a
  valid page state: recommended prompts are absent, input and submit controls
  remain disabled, and the bilingual availability explanation remains visible.
- No visual implementation may suppress a console or network error merely to
  make browser acceptance pass.
- Formatting failure renders an explicit unavailable state; it never displays
  `NaN`, `Infinity`, an empty metric, or a coerced zero.

## 13. Accessibility

- Preserve semantic headings, landmarks, form labels, table semantics, and
  source-order keyboard navigation.
- Interactive targets are at least 42px in both dimensions.
- Every icon-only control has an accessible name and visible focus state.
- Status never relies on color alone.
- Carousel controls support keyboard use and reduced motion.
- Automatic slide changes do not steal focus or repeatedly announce content.
- Drawer opening moves focus to its heading or first control; closing restores
  focus to the invoker. While open, focus stays within the modal, a scrim blocks
  background pointer interaction, and Escape closes the drawer when allowed by
  the current interaction contract. The dialog has an accessible name.
- Forecast horizon controls use `tablist`, `tab`, and `tabpanel` semantics,
  synchronize `aria-selected` and `tabindex`, and support Left/Right, Home, and
  End keys without changing the underlying forecast state.
- Line, bar, segmented, interval, and waterfall charts expose a bounded textual
  value summary in addition to visual marks. The accessible summary uses the
  same two-place display formatter as visible labels.
- Verify contrast for text, focus, badges, and charts against their final
  backgrounds.

## 14. Verification Design

### 14.1 Static and unit checks

- Token values and shell geometry match this design.
- Public source contains no visible `Operator sign in` or `Course Demo` copy.
- Approved copy exists in both English and Chinese catalogs.
- The shared public/sign-in carousel advances at 6 seconds and handles pause,
  resume, manual reset, document visibility, keyboard control, touch intent,
  and reduced motion through one controller.
- Carousel code performs no application API request.
- Missing visual assets preserve the entry actions and safe boundary copy.
- Login tests retain the existing request body, field values, focus, pending
  state, safe error, successful redirect, and language behavior across timed
  and manual slide changes.
- Every English catalog key has a Chinese counterpart; public, login, shell,
  dynamically rendered feature text, errors, accessible names, and session
  actions react to the same selected language.
- Display formatter tests cover BRL, signed BRL, counts, ordinary decimals,
  known percentages, days, null/unknown/invalid values, negative values, and
  values with more than six source decimal places. They also assert that the raw
  source value is untouched.
- Forecast, Action Card, Ask BizPulse structured facts, Inventory, Profit, and
  chart tests contain representative over-precision fixtures and assert the
  two-place presentation contract.
- The exact workspace JSON preview, form values, evidence formulas, identifiers,
  and hashes retain source precision and content.
- Operator `Sign out` and viewer `End preview` tests cover pending, success,
  already-expired, CSRF failure, server failure, browser-token cleanup, and
  redirect behavior.
- AI Decision Center tests assert that only Ask BizPulse, New Product Forecast,
  and Action Inbox are presented as destinations; no inert historical feature
  label appears.
- Evidence-drawer and forecast-tab tests cover focus containment, Escape,
  invoker focus restoration, tab roles, selection state, and keyboard movement.
- Existing viewer/operator state, effects, view-model, and feature tests remain
  green without weakening assertions.

### 14.2 Browser acceptance

Verify at 1280px, 820px, and 390px:

- public entry layout, four slides, manual controls, pause behavior, and both
  entry actions;
- sign-in layout, four timed/manual slides, stable form geometry and values,
  keyboard order, error state, language switch, and successful protected
  redirect;
- viewer and operator shells;
- all six primary routes and the three AI Decision Center subpages;
- operator Sign out and viewer End preview, including a safe failed request;
- English/Chinese persistence while navigating `/`, `/login`, `/demo`, and
  `/app` in their legal session contexts;
- representative money, ratio, percentage, days, Chat fact, Action, and chart
  labels with no unintended value longer than two fractional digits;
- evidence drawer, long table scrolling, loading/empty/unavailable states, and
  the no-AI restricted state;
- an AI-available local acceptance path with a deterministic fake provider, in
  addition to the unavailable path; the actual Azure-Key check remains a
  separate release gate;
- no unexpected horizontal scroll, broken local asset, uncaught exception,
  console error, or new external network dependency.

### 14.3 Visual review

Capture deterministic synthetic screenshots for the public entry, sign-in,
Today Overview, Profit Bridge, Ask BizPulse, Forecast, Action Inbox, and a mobile
screen. Compare hierarchy, spacing, copy, focus, truncation, and evidence
visibility. Screenshot similarity alone does not replace behavior tests.

### 14.4 Implementation batches

The later implementation plan should keep the work reviewable in this order:

1. Shared tokens, local icon symbols, language controller/catalogs, and numeric
   display formatters with focused tests.
2. Shared public/sign-in Product Theater and assets, fixed sign-in form, public
   entry redesign, copy, and real language switching.
3. Application rail/header, operator/viewer session exits, focus styles, and
   removal of inert AI Decision Center destinations.
4. Existing feature presentation migration, numeric formatting, chart summaries,
   evidence drawer, and forecast-tab accessibility.
5. Full frontend regression, local real-browser acceptance in AI-available and
   AI-unavailable modes, deterministic screenshots, and documentation closeout.

Each batch starts from the latest active implementation commit, preserves newer
changes from the adjacent task, and records implementation/local/hosted evidence
separately. The design branch must never reset or overwrite that task's line.

## 15. Non-Goals

This design does not authorize or include:

- copying the CAPTSONE frontend repository wholesale;
- backend, database, migration, API, algorithm, calculation, or AI-provider
  integration changes;
- changing viewer/operator permissions, cookie/security policy, session
  lifetime, CSRF rules, or server-side session semantics;
- renaming internal `demo` or `course_demo` code paths;
- implementing Product Opportunities, Favorites, or Operating Advice before
  those destinations have approved product and data contracts;
- adding a dedicated AI forecast-intake workflow, a new AI budget/system-status
  API, or a second forecasting authority alongside the deterministic forecast;
- rounding stored/API values, changing backend precision, or rewriting exact
  workspace JSON, formulas, identifiers, hashes, evidence records, or AI prose;
- adding live market imagery, real product images, or real business data;
- adding a new framework, build system, external icon library, or image CDN;
- creating or changing an OpenAI Key, enabling a hosted AI flag, making a paid
  provider request, changing Azure, deploying, publishing, or making Production
  claims. Those are separate release operations even though an enabled
  server-side Key is a final Azure Demo acceptance dependency;
- changing the current active implementation task's release evidence.

## 16. Completion Definition

The visual migration is complete only when:

1. The public welcome and sign-in pages match the approved Direction A and copy;
   the sign-in form remains stable and usable while its supporting visual turns.
2. The shared four-slide showcase operates on both pages and satisfies timing,
   pause, manual-control, reduced-motion, accessibility, asset, and
   synthetic-data constraints.
3. The application shell and all current feature surfaces use the CAPTSONE
   visual system without losing current behavior.
4. English and Chinese are complete, test-covered presentation states across
   public, sign-in, viewer, operator, dynamic feature, error, status, and
   accessibility copy.
5. User-facing values follow the shared two-place display contract while raw
   values, calculations, payloads, source previews, and evidence remain exact.
6. Operator `Sign out` and viewer `End preview` work through the existing
   protected contracts, and the navigation contains no inert historical
   destination.
7. The redesigned carousel, evidence drawer, forecast tabs, charts, and session
   controls satisfy the keyboard, focus, reduced-motion, and accessible-summary
   requirements in this document.
8. Viewer/operator authority and both AI-available and AI-unavailable boundaries
   remain intact; local acceptance verifies both with deterministic providers.
9. Focused tests, the full frontend regression, and local real-browser
   acceptance are green against the refreshed implementation commit.
10. Documentation reports implementation, local verification, hosted state,
    Azure Demo acceptance, and Production readiness separately.

Frontend completion alone is not Azure Demo acceptance. The requested final
Azure Demo is accepted only after a separately authorized, hash-bound release
proves that the approved immutable build is live, the server-side OpenAI Key and
AI flag are configured without client exposure, the authenticated availability
projection is `available`, and one bounded live Ask BizPulse smoke succeeds with
its evidence and safety boundaries intact. A deterministic local fake, an
AI-disabled hosted page, a reachable URL, or a documentation update cannot
substitute for that evidence.

This amendment is ready for user review before a separate implementation plan.
No product code, external system, or deployment is changed by reviewing this
document.
