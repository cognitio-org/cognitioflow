# Phase 21 — wow-UI repolish

Settled with Matej 2026-10-13 (decisions: ~/reports/cf-phase21-wowui-decisions.md). A cross-cutting **craft pass** over existing surfaces — NOT new features, NOT a rebrand. Elevate the current look (which already has real investment: the 3D statute book, paper/leather textures, `showcase.html` handoff, `--accent/--serif/--sans/--r`). Goal: students are *amazed* by the polish.

## Hard rules (CF UI contract — from repo CLAUDE.md, do not break)
- **Never touch `run.py`.** Styling is CSS tokens — change tokens, not scattered hex. `app.js` is read-only here. **Actual token locations (verified 2026-10-13, newer than CLAUDE.md's "index.html :root" note):** light `:root` in `static/app.css:4` (28 tokens: `--ink --graphite --rule --faint …`), dark override `@media(prefers-color-scheme:dark){:root}` in `static/app-after.css:58`, plus `static/library.css:6` (`--gilt --edge …` + its own dark block). index.html carries no inline tokens; it links app.css, book.css, app-after.css, library.css. The semantic (two-tier) layer is added on top of these existing base tokens, which keep working.
- **Keep every `id` and `data-*` hook** (`#fc #agenda #weekdir #ratings`, `data-nav data-mode data-r data-wk`…). **Preserve JS-written class names** (`wk`, `sess done`, `prov`, `prio`, `callout`, `noteview`) — grep the `<script>` before restyling a class. Don't touch `render()/chipify()/priomark()`.
- Tokens: two-tier (base palette → semantic roles); CSS-only light/dark; never hardcode a colour a token covers. **Keep every existing token name working (alias, don't rename).**
- **Design language is law:** ONE bold object (the Blackstone book), ONE accent used for meaning, **serif for content / sans for chrome**, sentence case. The **seven Blackstone tab colours map to legal function — never repurpose them.**
- Motion: **transform + opacity only**, 150–250ms, behind `@media (prefers-reduced-motion: reduce)`. Calm & purposeful (Matej) — and the contract's **"no idle motion"**: animation only in response to an action or an active load, never ambient/looping on a resting screen.
- No framework, no build step, no bundler, no `!important` wars. Only `marked` + `mermaid` vendored.
- Accessibility floor: contrast AA+, visible `:focus-visible` rings, ≥32px targets, no colour-only signals.
- Verify light + dark at 1440 and 1190 (sidebar collapses + book hides at 1300) and phone width; no horizontal scroll. One phase per PR; paste the acceptance checklist in the PR.

## Slices (ship + review each; swarm `cf` lane, Claude reviews the diff for id/hook preservation)
- **S1 — Token foundation + states (lowest risk, do first).** Audit existing tokens across `app.css`/`app-after.css`/`index.html`; consolidate into one two-tier `:root` system (base + semantic), keep every existing token name working (alias, don't rename). Add polished **empty / loading / skeleton / error** states for the dashboard lists and async panels. No visual identity change beyond consistency.
- **S2 — Dashboard + home.** Hierarchy, spacing rhythm, elevation scale, card hover/press micro-interactions, smoother tab/route transitions. Highest-traffic surface sets the tone.
- **S3 — Arena games (Phase 11).** Answer-reveal, FSRS rating feedback, question transitions — calm, reduced-motion-gated. Keep the game logic/ids intact.
- **S4 — Shared components + the Cases screen (Phase 20).** Apply the token system + states to the new Cases/MCQ surface so it's polished from day one (Matej: include now).

## Acceptance (per slice)
Before/after screenshots at 1440 + phone, light + dark. Grep proof that every id/`data-*` hook present before is present after. Pure CSS/markup-class diff; `app.js` untouched. Reversible.
