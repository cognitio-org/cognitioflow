# Handoff — CognitioFlow AI workflow

**For:** Cosmos
**From:** the coordinator session, 2026-09-18
**Scope:** the agent fleet that builds CognitioFlow. **Not the website itself.** Nothing here
describes app features; it describes the machine that produces them.

No secrets appear in this document. Where a credential is needed, the path to it is named and the
value is not.

---

## 1. Read this before trusting anything

An earlier handoff in this project marked several things "built ✅" that did not work, and one
status line in it ("ALLMS is the source of truth") cost a full day of work aimed at the wrong
application. So: **every claim below was verified by running something on 2026-09-18**, and where
a thing is unverified it says so.

Two corrections already on the record, both mine:

- I twice reported this app had "zero CSS and no design system". Wrong. There are no `.css`
  *files*, which is a different statement. A considered system exists inside `static/index.html`.
- I reported a swarm run as "verified" when `--run-checks` was off. See §7.

---

## 2. Where the code lives

| Piece | Path | Versioned? |
|---|---|---|
| Swarm runner, optimizer, plans, Mission Control | `~/my_swarm_project` | **NO — not a git repo** |
| Daemons, dispatcher, metrics, boards | `~/.cognitio` | **NO** |
| The product it serves | `~/dev/cognitioflow` → `cognitio-org/cognitioflow` | yes |
| Predecessor app, do not confuse | `~/dev/ALLMS` → `cognitio-org/ALLMS` | yes |

**Risk, stated plainly:** the two directories that hold the entire AI workflow are not under
version control. A mistaken `rm` is unrecoverable. Two sets of work were already lost this way
earlier in the project (a Chrome extension and eight course rubrics, both rebuilt from scratch on
2026-09-18). Putting `~/my_swarm_project` and `~/.cognitio` under git is the single highest-value
task in this handoff and is not yet done.

---

## 3. The lanes

Work flows: **You → Coordinator → (Claude agents ∥ Swarm) → acceptance checks → PR → merge →
deploy → live site.**

- **Coordinator** — an interactive Claude Code session. Writes plans, reviews diffs, decides.
  Expensive; use least.
- **Swarm** — `swarm_run.py`, driving local Ollama models (`qwen2.5-coder:7b`, `:14b`) and free
  OpenRouter models (`nex-n2.5-pro:free`, `nex-n2.5-mini:free`). Free; use most. Also wired for
  Groq (`openai/gpt-oss-120b`) but **dark — no key** at `~/.config/swarm/groq_key`.
- **Claude subagents** — spawned for review, audit and verification, never for bulk writing.
- **Daemons** — three launchd agents, described in §5.

**Routing rule that matters:** a plan whose header says `Private: yes` may only run on local
models. Course material must not leave the machine. `swarm_run.py` enforces this; do not weaken it.

**Mode is automatic, not a switch.** Under 80% of the Claude plan window the swarm reports
"Claude codes normally"; at 80% it routes work to local Qwen to protect the remaining budget.
Utilisation was **83–84%** at the time of writing, read live from a `rate_limit_event` in a
headless run — note that `swarm_mode_state/usage.json` lagged at 76%, so **the cached file is not
authoritative**.

---

## 4. Requested fixes

### 4.1 Mission Control typing (P1, not reproduced)

`~/my_swarm_project/swarm_mission.py` — the full-screen terminal app. The owner reports typing
does not work. **I could not reproduce it and my first attempt to do so was itself wrong.**

What is established:
- Key handling (`handle_key`, ~line 535), the input buffer, and the renderer (`_chat_input_line`,
  ~line 759) all read correctly in source. There is a comment recording a *previous* fix for `i`
  appearing to be a dead key.
- The headless path works. Running the exact argv the app spawns —
  `claude -p "<prompt>" --output-format stream-json --verbose` from the project directory with
  `CLAUDECODE` removed from the environment — returned a correct answer in ~7 s.
- My "zero events in 15 s" test was invalid: `start_talk` queues events and delivers them only via
  `drain_queue()`, which the TUI calls and my test did not.

**Therefore the suspect is the event drain or the redraw, not keystroke reading.** Before changing
anything, get from the owner which of these he sees:
1. Press `i`, no `›` prompt appears at all.
2. Prompt appears, characters do not echo as typed.
3. Types fine, presses Enter, nothing ever returns. ← most likely; points at the drain.

### 4.2 Local swarms on tap

The `SWARM LOCAL` and `SWARM CLOUD` lanes render as `○ local · ○ local-strong` with no detail.
They should show: which model is loaded, whether Ollama answers at `127.0.0.1:11434`, and the plan
each is currently running. `swarm_live.snapshot()` already returns nodes, edges and capacity, so
this is presentation, not new plumbing.

### 4.3 Toggle between agents and their models

A key that cycles the retry ladder for the next run, so a model can be forced without editing
`swarm_mode_state/config.json`. Must refuse to select a cloud model while a `Private: yes` plan is
queued.

### 4.4 Each agent's place in the workflow

The lane view working as its spec describes: a node per agent with status glyph, a one-line
"doing" ticker, and animated dots on active edges. Spec at
`~/my_swarm_project/SPEC_mission_control.md`, section T1.

### 4.5 Terminal styling

Owner's words: "sleazy terminal style" — read as a denser, more deliberate aesthetic. Constraint
from the spec and worth keeping: **stdlib only, ANSI, no `rich`/`textual`**, must work in 80×24
and restore the terminal on crash.

---

## 5. What was completed on 2026-09-18

All verified by running it.

| Thing | Path | What it does |
|---|---|---|
| **Dispatcher** | `~/.cognitio/dispatch.py` | Every 30 min: reads production, PR queue, swarm queue; runs the next plan on free models; marks a plan `SUSPECT` after 2 failures; **halts entirely** if the site is down or >7 days stale. Never merges. |
| **Release watcher** | `~/.cognitio/release-check.sh` | Hourly. Compares live `/health` against the newest tag; warns at 72% and 80% plan usage before the swarm takes over. |
| **To-do** | `~/.cognitio/todo.sh` | Daily 08:30. Only what a human can do. Deliberately does not merge or change settings. |
| **Delivery metrics** | `~/.cognitio/delivery-metrics.py` | Output metrics, not effort metrics — days since deploy, commits never served, product turn share. Writes `delivery-metrics.json`. |
| **Boards** | `~/.cognitio/cf`, `star.sh`, `road.sh`, `FLEET.md` | Terminal status. `cf` is the one to keep; the other two predate it and overlap. |
| **Optimizer ships** | `swarm_optimizer.py` | Built **by the swarm** from a plan, first-attempt pass in 313 s. Adds delivery terms above routing statistics. Product list overridable at `swarm_mode_state/products.json`. |

LaunchAgents: `eu.mgms.cognitio.dispatch`, `.release-check`, `.todo`.

### Plans queued, not yet run

In `~/my_swarm_project/swarm_tasks/`:

- `20260918-1321-printing-notes-survives-a-printer.md` — **highest value.** Printing notes is the
  owner's hard requirement and five things break on a real printer (§8).
- `20260918-1254-extract-design-system-to-css-file.md`
- `20260918-1254-ui-score-a-number-to-optimise.md`
- `20260918-1231-swarm-kinds-ui-and-content.md`
- `20260918-1226-board-examiner-scores-tutor-answers.md`
- `20260918-0010-ollama-fail-fast.md` (written by the peer session)

**Two plans are stale and marked `suspect` in `~/.cognitio/dispatch-state.json`** — `tutor-index`
and `llm-cache` are already implemented and live. Do not run them.

---

## 6. Relevant files

**Swarm core**
```
~/my_swarm_project/swarm_run.py            runner: list | models | use | escalation | report | run | watch
~/my_swarm_project/swarm_optimizer.py      measures the fleet; now includes delivery terms
~/my_swarm_project/swarm_live.py           snapshot() + start_talk(); backend for TUI and web
~/my_swarm_project/swarm_mission.py        the terminal app (§4.1)
~/my_swarm_project/swarm_dashboard.py      browser dashboard, --serve --open on 127.0.0.1:8765
~/my_swarm_project/SPEC_mission_control.md the spec both front ends implement
~/my_swarm_project/llm.py                  one call path for every model; response cache
~/my_swarm_project/tutor.py, tutor_eval.py the tutor and its evaluation harness
~/my_swarm_project/swarm_tasks/            plans
~/my_swarm_project/swarm_mode_state/       config.json, usage.json, optimizer.json, products.json
```

**Fleet control**
```
~/.cognitio/dispatch.py + dispatch-state.json
~/.cognitio/release-check.sh · todo.sh · delivery-metrics.py · cf
~/.cognitio/FLEET.md                       shared board; any session may read and write it
```

**Secrets — paths only, values not in this document**
```
~/.config/swarm/openrouter_key             present
~/.config/swarm/groq_key                   ABSENT — this is why cloud-groq is dark
GCP Secret Manager                         app secrets; never in the repo
```

---

## 7. Gotchas that have already cost time

1. **`--run-checks` is not the default.** `swarm_run.py run <plan>` does not execute a plan's
   acceptance checks unless asked. A "pass" without it means only that a model wrote something.
   The dispatcher now always passes it. **Treat any swarm pass recorded before 2026-09-18 12:35 as
   unverified.**
2. **The retry ladder blames the model, never the plan.** One run burned 3,603 s re-dialling a
   dead Ollama endpoint. The dispatcher's `SUSPECT_AFTER = 2` is the mitigation;
   `20260918-0010-ollama-fail-fast.md` is the proper fix and is unrun.
3. **`cognitioflow` is the product. `ALLMS` is the predecessor** — last deployed 2026-03-20, still
   serving `v4.0.26`, and `lusdiscere.com` points at it. Measuring the fleet against ALLMS
   produced "182 days since deploy, 0% product share"; against cognitioflow the same metrics read
   0 days and 43.9%.
4. **A draft PR cannot merge** — not by a human, not by auto-merge, not by any robot. Nine
   approved, passing PRs sat in draft. Auto-merge is already enabled on the repo; the draft
   checkbox was the only blocker.
5. **Plan validator rejects heredocs** inside an `## Acceptance checks` block. Use
   `python3 -c "..."` one-liners.
6. **Talking to Mission Control is not free.** Each message spawns a full Claude Code session; a
   one-word reply measured **$0.26**. The lanes and toggles are free; the chat is not.

---

## 8. Acceptance criteria

### 4.1 Typing
- Pressing `i` shows a `›` prompt within one refresh cycle (2 s).
- Typed characters echo.
- Enter produces a streaming assistant reply in the chat pane, or a visible error in the status
  line within 30 s. **Silence is a failure.**
- `Esc` clears and exits input without sending. Terminal is restored on `q` and on crash.

### 4.2 Local swarms on tap
- Each swarm node shows its model id and reachability.
- A node running a plan shows that plan's title, truncated, and elapsed time.
- Ollama unreachable renders as an explicit unreachable state, never as idle.

### 4.3 Model toggle
- A key cycles the ladder for the next run; the new ladder is visible before it runs.
- Selecting a cloud model is **refused** while a `Private: yes` plan is queued, with a stated
  reason.

### 4.4 Lanes
- Seven lanes render in 80×24 and degrade by hiding detail, never by breaking the frame.
- Colour is never the only signal; every status also has a glyph.

### General
- Stdlib only. `grep -rE "import (rich|textual)" swarm_mission.py` returns nothing.
- No secret value appears in any file added or changed.

---

## 9. Test commands

```bash
# Mission Control renders one static frame (safe inside another agent session)
cd ~/my_swarm_project && python3 swarm_mission.py --once --width 92 --height 34

# stdlib-only constraint
grep -rE "import (rich|textual|blessed|urwid)" ~/my_swarm_project/swarm_mission.py && echo FAIL || echo OK

# the headless path the chat depends on
cd ~/dev/cognitioflow && env -u CLAUDECODE /usr/bin/env claude -p "say only the word OK" \
  --output-format stream-json --verbose | tail -1 | python3 -c "import json,sys; print(json.load(sys.stdin)['result'])"

# swarm state, models, ladder, pending plans
cd ~/my_swarm_project && python3 swarm_run.py list
python3 swarm_run.py models

# run a plan WITH its acceptance checks — never omit --run-checks
python3 swarm_run.py run swarm_tasks/<plan>.md --run-checks --parallel 1

# optimizer, including the delivery terms
python3 swarm_optimizer.py && python3 -c "import json;d=json.load(open('swarm_mode_state/optimizer.json'));print(json.dumps(d['metrics'].get('shipping'),indent=1))"

# fleet delivery metrics (exits non-zero language in its own output, not its status)
python3 ~/.cognitio/delivery-metrics.py

# dispatcher, one tick, verbose
python3 ~/.cognitio/dispatch.py && tail -5 ~/.cognitio/dispatch.log

# daemons registered
launchctl list | grep eu.mgms.cognitio

# the print fixes, once that plan runs
cd ~/dev/cognitioflow
grep -c "print-color-adjust:exact" static/index.html      # must be >= 1
python3 -c "h=open('static/index.html').read(); assert 'body.printing *{visibility:hidden}' in h; print('print block scoped')"

# secret scan on anything you add
git diff --stat && git grep -nE "sk-ant-|AIza|BEGIN [A-Z ]*PRIVATE KEY" -- . || echo "clean"
```

---

## 10. Suggested order

1. Get the reproduction detail for §4.1 from the owner. Do not guess.
2. Put `~/my_swarm_project` and `~/.cognitio` under git. Nothing else here is safe until this is
   done.
3. Run `20260918-1321-printing-notes-survives-a-printer.md`. It serves the owner's daily
   requirement and is the only queued plan he would feel tomorrow morning.
4. Then §4.2, §4.4, §4.3 in that order — presentation first, behaviour last.
5. `20260918-0010-ollama-fail-fast.md`, to stop the ladder burning hours on a dead endpoint.

**The rule everything is judged by:** merged is not shipped. Only the live site counts.
