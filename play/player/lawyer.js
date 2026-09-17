// lawyer.js: "Who Wants to Be a Lawyer?" show mode. A game-show ladder of 15 questions hosted by an
// original character, "the Registrar" — warm, dry-witted, never a real host or catchphrase.
//
// This module is self-contained (no imports) so its pure logic — pickQuestions, pollJury, fiftyFifty,
// rungAfterWrong — can be unit tested in plain Node without a DOM. All document/localStorage access
// happens lazily, inside functions, never at module load time.

// ---------- constants ----------

export const RUNG_TITLES = {
  0: 'Bar Hopeful',
  1: 'Law Student',
  2: 'Moot Court Rookie',
  3: 'Seminar Star',
  4: 'Research Assistant',
  5: 'LLB Graduate',
  6: 'Paralegal',
  7: 'Trainee Solicitor',
  8: 'Junior Associate',
  9: 'Associate',
  10: 'Barrister',
  11: 'Senior Associate',
  12: 'Partner',
  13: 'Advocate General',
  14: 'Judge',
  15: 'Supreme Court Justice',
};

export const SAFE_RUNGS = new Set([5, 10]);
const TOTAL_RUNGS = 15;
// CognitioFlow: the ladder is as long as the pack can fill (a course with nine usable cards gets nine rungs).
let showRungs = TOTAL_RUNGS;
const LETTERS = ['A', 'B', 'C', 'D'];

// ---------- small pure helpers ----------

function shuffleWith(arr, rng) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function levelFor(rung) { return rung <= 5 ? 1 : rung <= 10 ? 2 : 3; }

/** Non-negative integers summing exactly to `total`, proportional to `weights` (largest-remainder method). */
function largestRemainder(total, weights) {
  if (total <= 0 || !weights.length) return weights.map(() => 0);
  const wsum = weights.reduce((a, b) => a + b, 0) || weights.length;
  const raw = weights.map((w) => (w / wsum) * total);
  const floors = raw.map(Math.floor);
  const used = floors.reduce((a, b) => a + b, 0);
  let remainder = total - used;
  const order = raw.map((r, i) => [r - Math.floor(r), i]).sort((a, b) => b[0] - a[0]);
  const out = floors.slice();
  let oi = 0;
  while (remainder > 0 && order.length) { out[order[oi % order.length][1]]++; remainder--; oi++; }
  return out;
}

function keysOf(question) {
  const keys = Array.isArray(question?.options) ? question.options.map((o) => o?.key).filter(Boolean) : [];
  return keys.length === 4 ? keys : LETTERS.slice();
}

// ---------- pure, testable exports ----------

/**
 * Pick 15 questions for one play-through. Rungs 1-5 draw level 1, 6-10 level 2, 11-15 level 3;
 * falls back to the nearest level if a level runs short. Prefers questions not in `seenIds`
 * (the last 3 plays), but will reuse them rather than leave a rung empty.
 */
export function pickQuestions(pack, seenIds = [], rng = Math.random) {
  const all = (Array.isArray(pack?.questions) ? pack.questions : []).filter((q) => q && q.id);
  const seen = new Set(seenIds || []);
  const byLevel = { 1: [], 2: [], 3: [] };
  for (const q of all) {
    const lvl = [1, 2, 3].includes(q.level) ? q.level : 1;
    byLevel[lvl].push(q);
  }
  const pools = {};
  for (const lvl of [1, 2, 3]) {
    const unseen = shuffleWith(byLevel[lvl].filter((q) => !seen.has(q.id)), rng);
    const wasSeen = shuffleWith(byLevel[lvl].filter((q) => seen.has(q.id)), rng);
    pools[lvl] = [...unseen, ...wasSeen];
  }
  const used = new Set();
  const picks = [];
  for (let rung = 1; rung <= TOTAL_RUNGS; rung++) {
    const target = levelFor(rung);
    const tryOrder = [target, ...[1, 2, 3].filter((l) => l !== target).sort((a, b) => Math.abs(a - target) - Math.abs(b - target))];
    let chosen = null;
    for (const lvl of tryOrder) {
      const idx = pools[lvl].findIndex((q) => !used.has(q.id));
      if (idx !== -1) { chosen = pools[lvl][idx]; break; }
    }
    if (chosen) { used.add(chosen.id); picks.push(chosen); }
  }
  return picks;
}

/**
 * Simulated jury poll. The correct option gets ~70/55/40% on levels 1/2/3 (with jitter), the rest
 * split randomly across the remaining options. Always returns {A,B,C,D} summing to exactly 100.
 */
export function pollJury(question, level, rng = Math.random) {
  const keys = keysOf(question);
  const correctKey = keys.includes(question?.answer) ? question.answer : keys[0];
  const baseByLevel = { 1: 70, 2: 55, 3: 40 };
  const base = baseByLevel[level] || baseByLevel[1];
  const jitter = Math.round((rng() - 0.5) * 14); // +/-7
  const correctPct = Math.min(92, Math.max(28, base + jitter));
  const others = keys.filter((k) => k !== correctKey);
  const pct = { [correctKey]: correctPct };
  if (others.length) {
    const weights = others.map(() => 0.3 + rng());
    const shares = largestRemainder(100 - correctPct, weights);
    others.forEach((k, i) => { pct[k] = shares[i]; });
  } else {
    pct[correctKey] = 100;
  }
  const out = {};
  for (const k of LETTERS) out[k] = pct[k] ?? 0;
  return out;
}

/** Returns the two wrong option keys to remove for the 50:50 lifeline. Never removes the answer. */
export function fiftyFifty(question, rng = Math.random) {
  const keys = keysOf(question);
  const correctKey = keys.includes(question?.answer) ? question.answer : keys[0];
  const wrong = shuffleWith(keys.filter((k) => k !== correctKey), rng);
  return wrong.slice(0, 2);
}

/** The safe rung reached after a wrong answer at `rung` (the last safe rung strictly below it, or 0). */
export function rungAfterWrong(rung) {
  let last = 0;
  for (const safe of SAFE_RUNGS) if (safe < rung && safe > last) last = safe;
  return last;
}

// ---------- localStorage (seen ids) ----------

function loadSeenPlays(key) {
  try {
    const raw = JSON.parse(localStorage.getItem(key) || '[]');
    return Array.isArray(raw) ? raw.filter((p) => Array.isArray(p)) : [];
  } catch { return []; }
}

function saveSeenPlays(key, plays, newIds) {
  try {
    const next = [...plays, newIds].slice(-3);
    localStorage.setItem(key, JSON.stringify(next));
  } catch { /* storage unavailable */ }
}

// ---------- DOM helpers (lazy: only touched inside functions) ----------

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return e;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function richOrText(ui, text) {
  if (ui?.rich) return ui.rich(text);
  return document.createTextNode(String(text ?? ''));
}

function citesNode(cites) {
  if (!cites?.length) return null;
  return el('div', { class: 'lw-cites' }, cites.map((c) => {
    const src = c?.source || c?.file || c?.key || 'Source';
    const label = c?.page != null && c.page !== '' ? `${src} · p.${c.page}` : String(src);
    return el('span', { class: 'lw-cite', text: label });
  }));
}

function optionsText(q) {
  return (q.options || []).map((o) => `${o.key}) ${o.text}`).join('\n');
}

// ---------- original host lines ----------

function hostLineFor(rung, q) {
  const topic = q?.topic ? ` on ${q.topic}` : '';
  if (rung === 1) return `Right then, counsel. A warm-up question${topic}. Try not to cite the wrong century.`;
  if (rung === 5) return `This one locks in your first safe rung. No pressure. Well — some.`;
  if (rung === 10) return `Second safe rung. Miss this and you still leave with something. Best make it count anyway.`;
  if (rung === showRungs) return `The last rung${topic}. Answer this and I will personally stop doubting you.`;
  if (rung > 10) return `We're deep in the reporters now${topic}. Take your time.`;
  if (rung > 5) return `Getting warmer, counsel${topic}. Or is that just the studio lights.`;
  return `Question ${rung}${topic}. The bench is listening.`;
}

function bankLineFor(rung) {
  return `Rung ${rung} banked. ${RUNG_TITLES[rung]} is yours to keep, whatever happens next.`;
}

function introLine() {
  return 'Good evening, counsel. Fifteen questions stand between you and the bench. Answer well, or walk away while you still can.';
}

function endLineFor({ finalRung, walkedAway }) {
  const title = RUNG_TITLES[finalRung] || RUNG_TITLES[0];
  if (walkedAway) return `Wise, or cowardly — history will decide. You leave with ${title}.`;
  if (finalRung === showRungs) return `${showRungs} for ${showRungs}. I have nothing left to teach you. Congratulations, ${title}.`;
  if (finalRung === 0) return 'Overruled, and rather early. Back to the library with you.';
  return `Overruled. But ${title} is yours to keep — that's not nothing.`;
}

// ---------- show building blocks ----------

function buildShow(root, { reduced, lowQuality }) {
  const host = el('div', { class: 'lw-host', 'aria-live': 'polite' });
  host.hidden = true;
  const rungLabel = el('span', { class: 'lw-rung-label' });
  const question = el('h2', { class: 'lw-qtext', id: 'lwQuestion' });
  const options = el('div', { class: 'lw-options', role: 'group', 'aria-label': 'Choose your answer' });
  const jury = el('div', { class: 'lw-jury', 'aria-label': 'Jury poll' });
  jury.hidden = true;
  const tutorPanel = el('div', { class: 'lw-tutor-panel', 'aria-live': 'polite' });
  tutorPanel.hidden = true;
  const lockBtn = el('button', { class: 'lw-btn lw-btn-primary lw-lock', type: 'button' }, 'Lock in answer');
  lockBtn.disabled = true;
  const walkBtn = el('button', { class: 'lw-btn lw-btn-ghost lw-walk', type: 'button' }, 'Walk away');
  const lifeFifty = el('button', { class: 'lw-life', type: 'button', 'data-life': '5050' }, el('span', { class: 'lw-life-label', text: '50:50' }));
  const lifePoll = el('button', { class: 'lw-life', type: 'button', 'data-life': 'poll' }, el('span', { class: 'lw-life-label', text: 'Poll the Jury' }));
  const lifeTutor = el('button', { class: 'lw-life', type: 'button', 'data-life': 'tutor' }, el('span', { class: 'lw-life-label', text: 'Ask the Tutor' }));
  const ladder = el('ol', { class: 'lw-ladder-list', 'aria-label': 'Ladder' });
  const reveal = el('div', { class: 'lw-reveal glass', role: 'dialog', 'aria-label': 'Ruling' });
  reveal.hidden = true;
  const confirm = el('div', { class: 'lw-confirm glass', role: 'dialog', 'aria-label': 'Confirm' });
  confirm.hidden = true;
  const endCard = el('div', { class: 'lw-end glass' });
  endCard.hidden = true;

  const frame = el('div', { class: 'lw-frame' },
    el('header', { class: 'lw-topbar' }, el('span', { class: 'lw-kicker', text: 'Who Wants to Be a Lawyer?' })),
    host,
    el('div', { class: 'lw-layout' },
      el('div', { class: 'lw-main' },
        el('div', { class: 'lw-question-card glass' },
          el('div', { class: 'lw-qhead' }, rungLabel),
          question,
          options,
          jury,
          tutorPanel),
        el('div', { class: 'lw-actions' }, walkBtn, lockBtn)),
      el('aside', { class: 'lw-side' },
        el('h3', { class: 'lw-side-title', text: 'The ladder' }),
        ladder,
        el('div', { class: 'lw-lifelines' }, lifeFifty, lifePoll, lifeTutor))),
    reveal, confirm, endCard);

  const wrap = el('div', { class: 'lw-show' }, frame);
  wrap.dataset.reduced = String(!!reduced);
  wrap.dataset.lowq = String(!!lowQuality);
  root.append(wrap);

  return { wrap, host, rungLabel, question, options, optionsByKey: {}, jury, tutorPanel, lockBtn, walkBtn, lifeFifty, lifePoll, lifeTutor, ladder, reveal, confirm, endCard };
}

function makeHostSayer({ ui, hostEl, reduced }) {
  return async (line) => {
    if (ui?.say) { await ui.say({ speaker: 'The Registrar', line }); return; }
    hostEl.hidden = false;
    hostEl.replaceChildren(el('span', { class: 'lw-host-name', text: 'The Registrar' }), el('p', { class: 'lw-host-line' }, line));
    if (reduced) return;
    await new Promise((resolve) => {
      const ac = new AbortController();
      hostEl.addEventListener('click', () => { ac.abort(); resolve(); }, { signal: ac.signal });
      setTimeout(() => { ac.abort(); resolve(); }, Math.max(1200, String(line).split(/\s+/).length * 260));
    });
  };
}

function renderLadder(els, currentRung, state) {
  els.ladder.replaceChildren(...Array.from({ length: showRungs }, (_, i) => {
    const n = showRungs - i;
    const cls = ['lw-rung'];
    if (n === currentRung) cls.push('is-current');
    if (SAFE_RUNGS.has(n)) cls.push('is-safe');
    if (n <= state.bankedRung) cls.push('is-done');
    return el('li', { class: cls.join(' ') },
      el('span', { class: 'lw-rung-n', text: String(n) }),
      el('span', { class: 'lw-rung-title', text: RUNG_TITLES[n] }));
  }));
}

function renderOptions(els, q, ui) {
  els.optionsByKey = {};
  els.options.replaceChildren(...(q.options || []).map((o) => {
    const btn = el('button', { class: 'lw-opt', type: 'button', 'data-key': o.key, 'aria-keyshortcuts': o.key },
      el('span', { class: 'lw-opt-key', 'aria-hidden': 'true', text: o.key }),
      el('span', { class: 'lw-opt-text' }, richOrText(ui, o.text)));
    els.optionsByKey[o.key] = btn;
    return btn;
  }));
}

function setLifelineButtons(els, state, tutor) {
  els.lifeFifty.disabled = state.usedFifty;
  els.lifePoll.disabled = state.usedPoll;
  const tutorOk = !!tutor?.available;
  els.lifeTutor.disabled = state.usedTutor || !tutorOk;
  els.lifeTutor.title = tutorOk ? 'Ask the Tutor for a hint' : 'Tutor offline — the local server is not reachable';
  els.lifeTutor.classList.toggle('is-unavailable', !tutorOk);
}

function renderJury(els, pct, keys) {
  els.jury.hidden = false;
  els.jury.replaceChildren(...keys.map((k) => el('div', { class: 'lw-jury-row' },
    el('span', { class: 'lw-jury-key', text: k }),
    el('span', { class: 'lw-jury-track' }, el('span', { class: 'lw-jury-fill', style: `width:${pct[k]}%` })),
    el('span', { class: 'lw-jury-pct', text: `${pct[k]}%` }))));
}

function renderTutor(els, res, ui) {
  const sources = (res?.sources || []).map((s) => (typeof s === 'string' ? { source: s } : s));
  els.tutorPanel.replaceChildren(...[
    el('p', { class: 'lw-tutor-text' }, richOrText(ui, res?.text || 'No answer.')),
    citesNode(sources)].filter(Boolean));
}

async function confirmWalk(els, state) {
  const title = RUNG_TITLES[state.bankedRung] || RUNG_TITLES[0];
  els.confirm.hidden = false;
  els.confirm.replaceChildren(
    el('p', { class: 'lw-confirm-text', text: `Walk away and keep ${title}?` }),
    el('div', { class: 'lw-confirm-actions' },
      el('button', { class: 'lw-btn lw-btn-ghost', type: 'button', 'data-value': 'stay' }, 'Stay in the room'),
      el('button', { class: 'lw-btn lw-btn-primary', type: 'button', 'data-value': 'walk' }, 'Walk away')));
  els.confirm.querySelector('[data-value="walk"]')?.focus();
  const val = await new Promise((resolve) => {
    const ac = new AbortController();
    els.confirm.addEventListener('click', (e) => {
      const b = e.target.closest('[data-value]');
      if (b) { ac.abort(); resolve(b.dataset.value); }
    }, { signal: ac.signal });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { ac.abort(); resolve('stay'); } }, { signal: ac.signal });
  });
  els.confirm.hidden = true;
  return val === 'walk';
}

async function revealAnswer({ els, q, rung, ui, audio, reduced, onReveal }, selectedKey) {
  const isCorrect = selectedKey === q.answer;
  onReveal?.(isCorrect); // before the ruling waits for a click, so leaving the show then still records the answer
  for (const o of q.options || []) {
    const btn = els.optionsByKey[o.key];
    if (!btn || btn.hidden) continue;
    if (o.key === q.answer) btn.classList.add('is-correct');
    else if (o.key === selectedKey) btn.classList.add('is-wrong');
    else btn.classList.add('is-dim');
  }
  audio?.sting?.('stamp');
  await sleep(reduced ? 60 : 160);
  audio?.sting?.(isCorrect ? 'sustained' : 'overruled');

  els.reveal.hidden = false;
  els.reveal.replaceChildren(
    el('div', { class: `lw-stamp ${isCorrect ? 'is-sustained' : 'is-overruled'}`, role: 'status', text: isCorrect ? 'Sustained' : 'Overruled' }),
    el('h3', { class: 'lw-reveal-title', text: isCorrect ? 'Correct — the bench agrees.' : 'Not this time.' }),
    q.explanation ? el('p', { class: 'lw-reveal-explain' }, richOrText(ui, q.explanation)) : null,
    q.quote ? el('blockquote', { class: 'lw-reveal-quote' }, richOrText(ui, `“${q.quote}”`)) : null,
    citesNode(q.cites),
    el('div', { class: 'lw-reveal-actions' }, el('button', { class: 'lw-btn lw-btn-primary', type: 'button', 'data-autofocus': true }, isCorrect && rung < showRungs ? 'Continue' : 'See the result')));
  els.reveal.querySelector('[data-autofocus]')?.focus();
  await new Promise((resolve) => {
    const ac = new AbortController();
    els.reveal.querySelector('button').addEventListener('click', () => { ac.abort(); resolve(); }, { signal: ac.signal });
    document.addEventListener('keydown', (e) => { if (e.key === 'Enter') { ac.abort(); resolve(); } }, { signal: ac.signal });
  });
  els.reveal.hidden = true;
  for (const o of q.options || []) els.optionsByKey[o.key]?.classList.remove('is-correct', 'is-wrong', 'is-dim');
  return isCorrect ? 'correct' : 'wrong';
}

/** One rung: renders options, lifelines, waits for lock-in or walk-away. Returns 'correct'|'wrong'|'walk'. */
function playRound(ctx) {
  const { els, q, level, state, tutor, audio } = ctx;
  const keys = (q.options || []).map((o) => o.key);
  let selected = null;
  let locked = false;
  let busy = false;

  renderOptions(els, q, ctx.ui);
  setLifelineButtons(els, state, tutor);
  els.lockBtn.disabled = true;
  els.lockBtn.textContent = 'Lock in answer';
  els.walkBtn.disabled = false;
  els.jury.hidden = true;
  els.jury.replaceChildren();
  els.tutorPanel.hidden = true;
  els.tutorPanel.replaceChildren();

  return new Promise((resolve) => {
    const ac = new AbortController();
    const { signal } = ac;
    const finish = (val) => { ac.abort(); resolve(val); };

    const selectKey = (key) => {
      if (locked || busy || !keys.includes(key)) return;
      const btn = els.optionsByKey[key];
      if (!btn || btn.hidden) return;
      selected = key;
      for (const k of keys) els.optionsByKey[k]?.classList.toggle('is-selected', k === key);
      els.lockBtn.disabled = false;
      els.lockBtn.textContent = `Lock in ${key}?`;
    };

    for (const k of keys) {
      els.optionsByKey[k]?.addEventListener('click', () => selectKey(k), { signal });
    }

    els.lockBtn.addEventListener('click', async () => {
      if (!selected || locked || busy) return;
      locked = true;
      els.walkBtn.disabled = true;
      for (const k of keys) if (els.optionsByKey[k]) els.optionsByKey[k].disabled = true;
      audio?.sting?.('select');
      const outcome = await revealAnswer(ctx, selected);
      finish(outcome);
    }, { signal });

    els.walkBtn.addEventListener('click', async () => {
      if (locked || busy) return;
      busy = true;
      const ok = await confirmWalk(els, state);
      busy = false;
      if (ok) finish('walk');
    }, { signal });

    els.lifeFifty.addEventListener('click', () => {
      if (locked || busy || state.usedFifty) return;
      state.usedFifty = true;
      els.lifeFifty.disabled = true;
      const remove = fiftyFifty(q, Math.random);
      for (const key of remove) {
        const btn = els.optionsByKey[key];
        if (!btn) continue;
        btn.hidden = true;
        if (selected === key) { selected = null; els.lockBtn.disabled = true; els.lockBtn.textContent = 'Lock in answer'; }
      }
      audio?.sting?.('file');
    }, { signal });

    els.lifePoll.addEventListener('click', () => {
      if (locked || busy || state.usedPoll) return;
      state.usedPoll = true;
      els.lifePoll.disabled = true;
      renderJury(els, pollJury(q, level, Math.random), keys.filter((k) => !els.optionsByKey[k]?.hidden));
      audio?.sting?.('file');
    }, { signal });

    els.lifeTutor.addEventListener('click', async () => {
      if (locked || busy || state.usedTutor || !tutor?.available) return;
      state.usedTutor = true;
      els.lifeTutor.disabled = true;
      els.tutorPanel.hidden = false;
      els.tutorPanel.replaceChildren(el('p', { class: 'lw-tutor-text', text: 'Asking the tutor…' }));
      try {
        const res = await tutor.ask(q.question, optionsText(q));
        renderTutor(els, res, ctx.ui);
      } catch {
        els.tutorPanel.replaceChildren(el('p', { class: 'lw-tutor-text', text: 'The tutor could not be reached.' }));
      }
    }, { signal });

    document.addEventListener('keydown', (e) => {
      if (locked || busy) return;
      const k = e.key.toUpperCase();
      if (LETTERS.includes(k)) { e.preventDefault(); selectKey(k); }
      else if (e.key === 'Enter' && selected) { e.preventDefault(); els.lockBtn.click(); }
    }, { signal });
  });
}

async function showEndCard(els, { rung, title, correct, walkedAway }) {
  els.endCard.hidden = false;
  els.endCard.replaceChildren(
    el('p', { class: 'lw-end-kicker', text: walkedAway ? 'Walked away' : rung === showRungs ? 'Case closed — the top of the bar' : 'Overruled' }),
    el('h2', { class: 'lw-end-title', text: title }),
    el('p', { class: 'lw-end-line', text: `${correct} of ${showRungs} answered correctly.` }),
    el('div', { class: 'lw-end-actions' }, el('button', { class: 'lw-btn lw-btn-primary', type: 'button', 'data-autofocus': true }, 'Continue')));
  els.endCard.querySelector('[data-autofocus]')?.focus();
  await new Promise((resolve) => {
    const ac = new AbortController();
    els.endCard.querySelector('button').addEventListener('click', () => { ac.abort(); resolve(); }, { signal: ac.signal });
    document.addEventListener('keydown', (e) => { if (e.key === 'Enter') { ac.abort(); resolve(); } }, { signal: ac.signal });
  });
  els.endCard.hidden = true;
}

// ---------- the show ----------

/**
 * Runs the full "Who Wants to Be a Lawyer?" show inside `root`. Resolves to
 * {rung, title, correct, lifelinesUsed, walkedAway}.
 */
export async function runLawyerShow({ pack, stage, audio, ui, root, reduced = false, lowQuality = false, tutor = null, onAnswer = null } = {}) {
  if (!root) throw new Error('runLawyerShow: root element is required');
  const course = String(pack?.course || pack?.id || 'course');
  const seenKey = `cf.lawyer.seen.${course}`;
  const seenPlays = loadSeenPlays(seenKey);
  const questions = pickQuestions(pack, seenPlays.flat(), Math.random);
  showRungs = Math.max(1, Math.min(TOTAL_RUNGS, questions.length));

  root.replaceChildren();
  const els = buildShow(root, { reduced, lowQuality });
  const say = makeHostSayer({ ui, hostEl: els.host, reduced });

  try {
    await stage?.loadScene?.({ kind: 'tv_studio', cast: [{ key: 'registrar', speaker: 'The Registrar' }, { key: 'trainee', speaker: 'You' }] });
  } catch { /* studio set not available yet; keep working without a stage */ }
  try { stage?.setSpeaker?.('registrar'); } catch { /* no stage */ }
  audio?.music?.('examination');

  await say(introLine());

  const state = { bankedRung: 0, usedFifty: false, usedPoll: false, usedTutor: false };
  let finalRung = 0;
  let correctCount = 0;
  let walkedAway = false;

  for (let i = 0; i < questions.length; i++) {
    const rung = i + 1;
    const q = questions[i];
    const level = [1, 2, 3].includes(q.level) ? q.level : levelFor(rung);
    renderLadder(els, rung, state);
    els.rungLabel.textContent = `Rung ${rung} of ${showRungs} · ${RUNG_TITLES[rung]}`;
    els.question.replaceChildren(richOrText(ui, q.question));
    try { stage?.freeze?.(true); } catch { /* no stage */ }
    await say(hostLineFor(rung, q));

    const before = { ...state };
    const onReveal = (correct) => {
      if (!onAnswer) return;
      const helped = state.usedFifty !== before.usedFifty || state.usedPoll !== before.usedPoll || state.usedTutor !== before.usedTutor;
      try { onAnswer({ question: q, correct, helped }); } catch { /* the host app's bookkeeping must not stop the show */ }
    };
    const outcome = await playRound({ els, q, rung, level, state, ui, audio, tutor, reduced, onReveal });
    try { stage?.freeze?.(false); } catch { /* no stage */ }

    if (outcome === 'walk') { walkedAway = true; finalRung = state.bankedRung; correctCount = state.bankedRung; break; }
    if (outcome === 'wrong') { finalRung = rungAfterWrong(rung); correctCount = state.bankedRung; break; }

    state.bankedRung = rung;
    correctCount = rung;
    if (rung === showRungs) { finalRung = showRungs; break; }
    if (SAFE_RUNGS.has(rung)) await say(bankLineFor(rung));
  }

  const title = RUNG_TITLES[finalRung] || RUNG_TITLES[0];
  await say(endLineFor({ finalRung, walkedAway }));
  await showEndCard(els, { rung: finalRung, title, correct: correctCount, walkedAway });

  saveSeenPlays(seenKey, seenPlays, questions.map((q) => q.id));
  try { stage?.setSpeaker?.(null); } catch { /* no stage */ }

  return {
    rung: finalRung,
    title,
    correct: correctCount,
    lifelinesUsed: { fiftyFifty: state.usedFifty, pollJury: state.usedPoll, askTutor: state.usedTutor },
    walkedAway,
  };
}
