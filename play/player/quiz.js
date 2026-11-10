// quiz.js: examination rounds (shuffled options, SUSTAINED / OVERRULED, consequences, retry), the IRAC reveal,
// and the verdict (closing argument, case outcome vs advocate score, claims & sources, epilogue).
import { el } from './ui.js';
import { shuffle } from './data.js';
import { PRODUCE_KINDS, gradeProduce } from './grade.js';

const $ = (s) => document.querySelector(s);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const LETTERS = ['A', 'B', 'C', 'D', 'E', 'F'];

export const SCORE_FIRST = 100;
export const SCORE_LATER = 40;

function focusFirst(root) {
  const f = root.querySelector('[data-autofocus]') || root.querySelector('button');
  f?.focus({ preventScroll: true });
}

/** Resolve with the value passed to one of the given buttons. */
function choose(root, keyMap = {}) {
  return new Promise((resolve) => {
    const onKey = (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const v = keyMap[e.key.toUpperCase()];
      if (v !== undefined) { e.preventDefault(); cleanup(); resolve(v); }
    };
    const onClick = (e) => {
      const b = e.target.closest('[data-value]');
      if (b && root.contains(b) && !b.disabled) { cleanup(); resolve(b.dataset.value); }
    };
    const cleanup = () => { document.removeEventListener('keydown', onKey); root.removeEventListener('click', onClick); };
    document.addEventListener('keydown', onKey);
    root.addEventListener('click', onClick);
  });
}

/** Four IRAC panels revealed one after another. */
export function iracBlock(ui, irac, { heading = '', reduced = false } = {}) {
  const parts = [['I', 'Issue', irac.issue], ['R', 'Rule', irac.rule], ['A', 'Application', irac.application], ['C', 'Conclusion', irac.conclusion]].filter((p) => p[2]);
  const wrap = el('div', { class: 'irac' },
    heading ? el('h3', { class: 'irac-heading', text: heading }) : null,
    el('div', { class: 'irac-grid' }, parts.map(([l, name, text], i) => el('section', { class: `irac-panel${reduced ? ' is-in' : ''}`, style: `--d:${i}`, 'aria-label': name },
      el('div', { class: 'irac-letter', 'aria-hidden': 'true', text: l }),
      el('h4', { class: 'irac-name', text: name }),
      el('p', { class: 'irac-text' }, ui.rich(text))))));
  if (!reduced) requestAnimationFrame(() => wrap.querySelectorAll('.irac-panel').forEach((p, i) => setTimeout(() => p.classList.add('is-in'), 120 + i * 420)));
  return wrap;
}

async function stamp(panel, kind, audio, reduced) {
  const s = el('div', { class: `stamp stamp-${kind.toLowerCase()}`, role: 'status', text: kind === 'SUSTAINED' ? 'Sustained' : 'Overruled' });
  panel.append(s);
  audio?.sting('stamp');
  await sleep(reduced ? 80 : 140);
  audio?.sting(kind === 'SUSTAINED' ? 'sustained' : 'overruled');
  await sleep(reduced ? 500 : 1300);
  return s;
}

/**
 * One examination round. Returns {firstTry, attempts, wrongKeys}.
 */
export async function runRound(ctx) {
  const { quiz } = ctx;
  // Produce-type kinds (spot / order / slot) render their own surface over the calm overlay and are
  // graded deterministically; the A–D path below is unchanged for every existing (mcq) quiz.
  if (quiz && PRODUCE_KINDS.has(quiz.kind)) return runProduce(ctx);
  const { ui, audio, stage, round, total, asker, reduced } = ctx;
  const root = $('#exam');
  let attempts = 0;
  const wrongKeys = [];
  audio?.music('examination');
  stage.freeze(true);
  for (;;) {
    attempts++;
    const opts = shuffle(quiz.options);
    const keyMap = {};
    opts.forEach((o, i) => { keyMap[LETTERS[i]] = String(i); });
    const optionEls = opts.map((o, i) => el('button', { class: 'opt', type: 'button', 'data-value': String(i), style: `--i:${i}`, 'aria-keyshortcuts': LETTERS[i], ...(i === 0 ? { 'data-autofocus': true } : {}) },
      el('span', { class: 'opt-key', 'aria-hidden': 'true', text: LETTERS[i] }),
      el('span', { class: 'opt-text' }, el('span', { class: 'sr-only', text: `Option ${LETTERS[i]}: ` }), ui.rich(o.text))));
    const panel = el('div', { class: 'exam-panel glass', role: 'dialog', 'aria-modal': 'false', 'aria-labelledby': 'examQ' },
      el('div', { class: 'exam-head' },
        el('span', { class: 'exam-round', text: `Examination · Round ${round} of ${total}` }),
        attempts > 1 ? el('span', { class: 'exam-attempt', text: `Attempt ${attempts}` }) : null),
      el('p', { class: 'exam-asker', text: asker ? `${asker} puts the question` : 'The bench puts the question' }),
      el('h2', { class: 'exam-q', id: 'examQ' }, ui.rich(quiz.question)),
      el('div', { class: 'opts', role: 'group', 'aria-label': 'Your argument' }, optionEls),
      el('p', { class: 'exam-help', text: 'Pick your argument: press A–D, or select a card.' }));
    root.replaceChildren(panel);
    root.hidden = false;
    ui.hideSubtitle();
    focusFirst(panel);
    const idx = Number(await choose(panel, keyMap));
    const picked = opts[idx];
    audio?.sting('select');
    optionEls.forEach((b, i) => { b.disabled = true; b.classList.add(i === idx ? (picked.correct ? 'is-locked' : 'is-cracked') : 'is-dim'); });
    await stamp(panel, picked.correct ? 'SUSTAINED' : (picked.stamp === 'SUSTAINED' ? 'SUSTAINED' : 'OVERRULED'), audio, reduced);

    if (picked.correct) {
      stage.freeze(false);
      const hasOutcome = picked.outcome_title || picked.story || picked.teaching;
      const body = el('div', { class: 'exam-result glass is-right' },
        el('div', { class: 'exam-head' }, el('span', { class: 'exam-round', text: `Round ${round} · ${attempts === 1 ? `+${SCORE_FIRST}` : `+${SCORE_LATER}`}` })),
        hasOutcome && picked.outcome_title ? el('h2', { class: 'res-title', text: picked.outcome_title }) : null,
        hasOutcome && picked.story ? el('p', { class: 'res-story' }, ui.rich(picked.story)) : null,
        hasOutcome && picked.teaching ? el('div', { class: 'teach' }, el('h3', { text: 'Why it works' }), el('p', {}, ui.rich(picked.teaching)), ui.chips(picked.cites)) : null,
        iracBlock(ui, quiz.irac, { heading: 'The argument, in IRAC', reduced }),
        quiz.cites?.length ? el('div', { class: 'res-cites' }, el('span', { text: 'Sources' }), ui.chips(quiz.cites)) : null,
        el('div', { class: 'res-actions' }, el('button', { class: 'btn btn-primary', type: 'button', 'data-value': 'go', 'data-autofocus': true }, 'Continue', el('span', { class: 'btn-arrow', 'aria-hidden': 'true', text: '→' }))));
      root.replaceChildren(body);
      focusFirst(body);
      await choose(body, { ENTER: 'go' });
      root.hidden = true;
      return { firstTry: attempts === 1, attempts, wrongKeys, score: attempts === 1 ? SCORE_FIRST : SCORE_LATER };
    }

    wrongKeys.push(picked.key);
    const body = el('div', { class: 'exam-result glass is-wrong' },
      el('div', { class: 'exam-head' }, el('span', { class: 'exam-round', text: `Round ${round} · Consequence` })),
      el('h2', { class: 'res-title', text: picked.outcome_title || 'Overruled' }),
      picked.story ? el('p', { class: 'res-story' }, ui.rich(picked.story)) : null,
      picked.teaching ? el('div', { class: 'teach teach-wrong' }, el('h3', { text: 'Teaching card' }), el('p', {}, ui.rich(picked.teaching)), ui.chips(picked.cites)) : null,
      el('p', { class: 'res-note', text: 'A correct answer on a later attempt scores 40 instead of 100.' }),
      el('div', { class: 'res-actions' }, el('button', { class: 'btn btn-primary', type: 'button', 'data-value': 'retry', 'data-autofocus': true }, 'Rewind and argue again', el('span', { class: 'btn-arrow', 'aria-hidden': 'true', text: '↺' }))));
    root.replaceChildren(body);
    focusFirst(body);
    await choose(body, { R: 'retry' });
    audio?.music('examination');
  }
}

// ---------------------------------------------------------------------------
// Produce-type rounds (spot / order / slot). The player PRODUCES an answer over an open space; the
// response is graded by pure set / sequence / bipartite math (grade.js) with no model and no network.
// Single attempt, then an elaborative cited reveal (desirable difficulty; no twitch retry loop).
// ---------------------------------------------------------------------------

/** Resolve with the first [matching] element clicked inside root. */
function awaitClick(root, selector) {
  return new Promise((resolve) => {
    const h = (e) => { const b = e.target.closest(selector); if (b && root.contains(b) && !b.disabled) { root.removeEventListener('click', h); resolve(b); } };
    root.addEventListener('click', h);
  });
}

/** Split a string into whitespace-delimited word tokens carrying their char offsets into that string. */
function tokenize(text) {
  const toks = [];
  const re = /\S+/g;
  let m;
  while ((m = re.exec(text))) toks.push({ s: m.index, e: m.index + m[0].length, w: m[0] });
  return toks;
}

async function runProduce({ ui, audio, stage, quiz, round, total, asker, reduced }) {
  const root = $('#exam');
  audio?.music('examination');
  stage.freeze(true);
  ui.hideSubtitle();
  const head = (extra) => el('div', { class: 'exam-head' },
    el('span', { class: 'exam-round', text: `Examination · Round ${round} of ${total}` }), extra || null);
  const asked = el('p', { class: 'exam-asker', text: asker ? `${asker} puts the task` : 'The bench puts the task' });

  let response;
  if (quiz.kind === 'spot') response = await spotPanel({ ui, root, quiz, head, asked });
  else if (quiz.kind === 'order') response = await orderPanel({ ui, root, quiz, head, asked });
  else response = await slotPanel({ ui, root, quiz, head, asked });

  const graded = gradeProduce(quiz.kind, response, quiz.answer);
  audio?.sting('select');
  const score = Math.round(graded.score * SCORE_FIRST);
  await produceResult({ ui, audio, root, quiz, graded, score, reduced });
  stage.freeze(false);
  return { firstTry: graded.correct, attempts: 1, wrongKeys: [], score };
}

/** spot — free-range (word-granular) issue spotting + open-taxonomy tagging. */
async function spotPanel({ ui, root, quiz, head, asked }) {
  // Match the offsets baked offline: strip CR (a Windows checkout shifts every offset by 1 per line)
  // and NFC-normalise (§/—/smart quotes and macOS NFD input otherwise drift from the baked span).
  const text = String(quiz.text || quiz.question || '').replace(/\r\n?/g, '\n').normalize('NFC');
  const toks = tokenize(text);
  const selected = new Set();                 // indices of selected tokens
  const picks = [];                            // committed {span,tag,label}
  let tag = null;                              // current taxonomy pick {id,label}

  const tokEls = toks.map((t, i) => el('span', { class: 'tok', tabindex: '0', role: 'button', 'aria-pressed': 'false', 'data-i': String(i), text: t.w }));
  const factEl = el('p', { class: 'spot-text', id: 'factpattern', 'aria-label': 'Fact pattern — select the words that raise an issue' });
  tokEls.forEach((tEl, i) => { factEl.append(tEl); if (i < tokEls.length - 1) factEl.append(document.createTextNode(' ')); });

  const toggle = (i) => {
    if (selected.has(i)) selected.delete(i); else selected.add(i);
    tokEls[i].classList.toggle('is-sel', selected.has(i));
    tokEls[i].setAttribute('aria-pressed', selected.has(i) ? 'true' : 'false');
  };
  factEl.addEventListener('click', (e) => { const t = e.target.closest('.tok'); if (t) toggle(Number(t.dataset.i)); });
  factEl.addEventListener('keydown', (e) => { if ((e.key === ' ' || e.key === 'Enter') && e.target.classList.contains('tok')) { e.preventDefault(); toggle(Number(e.target.dataset.i)); } });

  const taxoList = el('ul', { class: 'taxo', role: 'listbox', 'aria-label': 'Issue taxonomy' });
  const tagInput = el('input', { class: 'spot-tag', type: 'text', autocomplete: 'off', spellcheck: 'false', placeholder: 'Name the issue (type 3+ letters)…', 'aria-label': 'Name the issue' });
  const renderTaxo = () => {
    const q = tagInput.value.trim().toLowerCase();
    taxoList.replaceChildren();
    if (q.length < 3) return;                 // no suggestions until 3 chars (recall, not recognition)
    for (const t of quiz.answer.taxonomy) {
      if (!`${t.label} ${t.id}`.toLowerCase().includes(q)) continue;
      taxoList.append(el('li', { class: 'taxo-opt', role: 'option', tabindex: '0', 'data-id': t.id, text: t.label }));
    }
  };
  tagInput.addEventListener('input', renderTaxo);
  const chooseTag = (id, label) => { tag = { id, label }; tagInput.value = label; taxoList.replaceChildren(); };
  taxoList.addEventListener('click', (e) => { const o = e.target.closest('.taxo-opt'); if (o) chooseTag(o.dataset.id, o.textContent); });
  taxoList.addEventListener('keydown', (e) => { if ((e.key === 'Enter' || e.key === ' ') && e.target.classList.contains('taxo-opt')) { e.preventDefault(); chooseTag(e.target.dataset.id, e.target.textContent); } });

  const picksEl = el('ul', { class: 'picks', 'aria-label': 'Issues you have spotted' });
  const renderPicks = () => {
    picksEl.replaceChildren(...picks.map((p, i) => el('li', { class: 'pick' },
      el('span', { class: 'pick-tag', text: p.label }),
      el('span', { class: 'pick-quote', text: `“${text.slice(p.span[0], p.span[1])}”` }),
      el('button', { class: 'pick-x', type: 'button', 'data-rm': String(i), 'aria-label': `Remove ${p.label}` }, '×'))));
  };
  picksEl.addEventListener('click', (e) => { const b = e.target.closest('[data-rm]'); if (b) { picks.splice(Number(b.dataset.rm), 1); renderPicks(); } });

  const addBtn = el('button', { class: 'btn btn-ghost', type: 'button', 'data-add': true }, 'Add this issue');
  const msg = el('p', { class: 'spot-msg', role: 'status' });
  const panel = el('div', { class: 'exam-panel produce glass', role: 'group', 'aria-labelledby': 'examQ' },
    head(), asked,
    el('h2', { class: 'exam-q', id: 'examQ' }, ui.rich(quiz.question)),
    factEl,
    el('div', { class: 'spot-tagrow' }, tagInput, addBtn), taxoList, msg,
    el('h3', { class: 'picks-h', text: 'Spotted issues' }), picksEl,
    el('div', { class: 'res-actions' }, el('button', { class: 'btn btn-primary', type: 'button', 'data-value': 'submit', 'data-spot': true, 'data-autofocus': true }, 'Submit to the bench')));
  panel.addEventListener('click', (e) => {
    if (!e.target.closest('[data-add]')) return;
    if (!selected.size || !tag) { msg.textContent = !tag ? 'Name the issue first.' : 'Select the words that raise it.'; return; }
    const idx = [...selected];
    const span = [Math.min(...idx.map((i) => toks[i].s)), Math.max(...idx.map((i) => toks[i].e))];
    picks.push({ span, tag: tag.id, label: tag.label });
    selected.clear(); tokEls.forEach((tEl) => { tEl.classList.remove('is-sel'); tEl.setAttribute('aria-pressed', 'false'); });
    tag = null; tagInput.value = ''; msg.textContent = ''; renderPicks();
  });
  root.replaceChildren(panel); root.hidden = false;
  (panel.querySelector('[data-autofocus]') || panel).focus?.({ preventScroll: true });
  await awaitClick(panel, '[data-spot]');
  root.hidden = true;
  return { selections: picks.map((p) => ({ span: p.span, tag: p.tag })) };
}

/** order — assemble the governing test from a shuffled bank. */
async function orderPanel({ ui, root, quiz, head, asked }) {
  const source = quiz.answer.bank.length ? quiz.answer.bank : quiz.answer.sequence.map((id) => ({ id, label: id }));
  // Derange: never present the canonical order, so submitting untouched cannot score full marks.
  let bank = shuffle(source);
  if (!quiz.answer.unordered) {
    let guard = 0;
    while (bank.length > 1 && guard++ < 24 && bank.every((b, i) => b.id === quiz.answer.sequence[i])) bank = shuffle(source);
  }
  const list = el('ol', { class: 'order-list', id: 'irac-rule', 'aria-label': 'Order the elements of the test' });
  const render = () => {
    list.replaceChildren(...bank.map((b, i) => el('li', { class: 'order-row', 'data-id': b.id },
      el('span', { class: 'order-num', 'aria-hidden': 'true', text: String(i + 1) }),
      el('span', { class: 'order-label' }, ui.rich(b.label)),
      el('span', { class: 'order-moves' },
        el('button', { class: 'mv', type: 'button', 'data-up': String(i), 'aria-label': `Move “${b.label}” up`, disabled: i === 0 }, '↑'),
        el('button', { class: 'mv', type: 'button', 'data-down': String(i), 'aria-label': `Move “${b.label}” down`, disabled: i === bank.length - 1 }, '↓')))));
  };
  list.addEventListener('click', (e) => {
    const u = e.target.closest('[data-up]'); const d = e.target.closest('[data-down]');
    if (u) { const i = Number(u.dataset.up); [bank[i - 1], bank[i]] = [bank[i], bank[i - 1]]; render(); }
    else if (d) { const i = Number(d.dataset.down); [bank[i + 1], bank[i]] = [bank[i], bank[i + 1]]; render(); }
  });
  render();
  const panel = el('div', { class: 'exam-panel produce glass', role: 'group', 'aria-labelledby': 'examQ' },
    head(), asked,
    el('h2', { class: 'exam-q', id: 'examQ' }, ui.rich(quiz.question)),
    list,
    el('div', { class: 'res-actions' }, el('button', { class: 'btn btn-primary', type: 'button', 'data-value': 'submit', 'data-order': true, 'data-autofocus': true }, 'Submit the test')));
  root.replaceChildren(panel); root.hidden = false;
  (panel.querySelector('[data-autofocus]') || panel).focus?.({ preventScroll: true });
  await awaitClick(panel, '[data-order]');
  root.hidden = true;
  return { order: bank.map((b) => b.id) };
}

/** slot — map each salient fact onto the element it satisfies. */
async function slotPanel({ ui, root, quiz, head, asked }) {
  const assignments = {};
  const rows = quiz.answer.facts.map((f) => {
    const sel = el('select', { class: 'slot-sel', 'aria-label': `Element satisfied by: ${f.label}` },
      el('option', { value: '', text: '— choose an element —' }),
      ...quiz.answer.elements.map((eEl) => el('option', { value: eEl.id, text: eEl.label })));
    sel.addEventListener('change', () => { if (sel.value) assignments[f.id] = sel.value; else delete assignments[f.id]; });
    return el('div', { class: 'slot-row', 'data-slot': f.id }, el('span', { class: 'slot-fact' }, ui.rich(f.label)), sel);
  });
  const panel = el('div', { class: 'exam-panel produce glass', role: 'group', 'aria-labelledby': 'examQ' },
    head(), asked,
    el('h2', { class: 'exam-q', id: 'examQ' }, ui.rich(quiz.question)),
    el('div', { class: 'slot-grid' }, rows),
    el('div', { class: 'res-actions' }, el('button', { class: 'btn btn-primary', type: 'button', 'data-value': 'submit', 'data-slot-submit': true, 'data-autofocus': true }, 'Submit the application')));
  root.replaceChildren(panel); root.hidden = false;
  (panel.querySelector('[data-autofocus]') || panel).focus?.({ preventScroll: true });
  await awaitClick(panel, '[data-slot-submit]');
  root.hidden = true;
  return { assignments };
}

/** The elaborative, cited reveal after a produce round: score, the model key, IRAC. */
async function produceResult({ ui, audio, root, quiz, graded, score, reduced }) {
  const pass = graded.correct;
  audio?.sting(pass ? 'sustained' : 'overruled');
  const a = quiz.answer;
  let modelKey = null;
  if (quiz.kind === 'spot') modelKey = el('ul', { class: 'key-list' }, a.issues.map((it) => el('li', {}, el('span', { class: 'pick-tag', text: it.label }))));
  else if (quiz.kind === 'order') modelKey = el('ol', { class: 'key-list' }, a.sequence.map((id) => { const b = a.bank.find((x) => x.id === id); return el('li', {}, ui.rich(b ? b.label : id)); }));
  else modelKey = el('ul', { class: 'key-list' }, Object.entries(a.key).map(([f, e]) => { const fo = a.facts.find((x) => x.id === f); const eo = a.elements.find((x) => x.id === e); return el('li', {}, el('span', { class: 'slot-fact', text: fo ? fo.label : f }), el('span', { class: 'key-arrow', 'aria-hidden': 'true', text: ' → ' }), el('span', { class: 'slot-elem', text: eo ? eo.label : e })); }));

  const body = el('div', { class: `exam-result produce-result glass ${pass ? 'is-right' : 'is-wrong'}`, id: 'debrief' },
    el('div', { class: 'exam-head' }, el('span', { class: 'exam-round', text: `${pass ? 'Sustained' : 'Overruled'} · +${score}` })),
    quiz.teaching ? el('div', { class: 'teach' }, el('h3', { text: 'Why it works' }), el('p', {}, ui.rich(quiz.teaching)), ui.chips(quiz.cites)) : null,
    el('div', { class: 'model-key' }, el('h3', { text: 'The answer the bench expected' }), modelKey),
    quiz.irac && Object.values(quiz.irac).some(Boolean) ? iracBlock(ui, quiz.irac, { heading: 'The argument, in IRAC', reduced }) : null,
    quiz.cites?.length ? el('div', { class: 'res-cites' }, el('span', { text: 'Sources' }), ui.chips(quiz.cites)) : null,
    el('div', { class: 'res-actions' }, el('button', { class: 'btn btn-primary', type: 'button', 'data-value': 'go', 'data-autofocus': true }, 'Continue', el('span', { class: 'btn-arrow', 'aria-hidden': 'true', text: '→' }))));
  root.replaceChildren(body); root.hidden = false;
  (body.querySelector('[data-autofocus]') || body).focus?.({ preventScroll: true });
  await awaitClick(body, '[data-value="go"]');
  root.hidden = true;
}

function outcomeOf(game, score, max) {
  const text = game.verdict?.outcome || '';
  if (/\b(lost|lose|loses|dismissed|fails?|against the client|rejected)\b/i.test(text)) return { won: false, text };
  if (/\b(won|wins?|granted|succeeds?|in favour|upheld for|allowed)\b/i.test(text)) return { won: true, text };
  return { won: max ? score / max >= 0.6 : true, text };
}

/** Verdict: closing argument, CASE WON / LOST with advocate score, claims & sources, epilogue. */
export async function runVerdict({ ui, audio, game, results, reduced, onNext, onLibrary, hasNext }) {
  const root = $('#verdict');
  root.hidden = false;
  const score = results.reduce((a, r) => a + r.score, 0);
  const max = results.length * SCORE_FIRST;

  // 1. closing argument
  const iracs = game.verdict?.irac?.length ? game.verdict.irac.map((x, i) => ({ irac: x, label: game.verdict.irac.length > 1 ? `Issue ${i + 1}` : '' }))
    : results.map((r, i) => ({ irac: r.quiz.irac, label: results.length > 1 ? `Round ${i + 1}` : '' }));
  for (let i = 0; i < iracs.length; i++) {
    const { irac, label } = iracs[i];
    if (!Object.values(irac).some(Boolean)) continue;
    const panel = el('div', { class: 'verdict-panel glass' },
      el('div', { class: 'exam-head' }, el('span', { class: 'exam-round', text: `Closing argument${label ? ` · ${label}` : ''}` }), iracs.length > 1 ? el('span', { class: 'exam-attempt', text: `${i + 1} / ${iracs.length}` }) : null),
      iracBlock(ui, irac, { reduced }),
      el('div', { class: 'res-actions' }, el('button', { class: 'btn btn-primary', type: 'button', 'data-value': 'go', 'data-autofocus': true }, i < iracs.length - 1 ? 'Next issue' : 'Hear the verdict', el('span', { class: 'btn-arrow', 'aria-hidden': 'true', text: '→' }))));
    root.replaceChildren(panel);
    focusFirst(panel);
    await choose(panel, {});
  }

  // 2. result card
  const out = outcomeOf(game, score, max);
  audio?.sting('clang');
  audio?.music(out.won ? 'verdict_won' : 'verdict_lost');
  const rows = results.map((r, i) => el('li', { class: `vr-row ${r.firstTry ? 'is-first' : 'is-later'}` },
    el('span', { class: 'vr-n', text: `Round ${i + 1}` }),
    el('span', { class: 'vr-q' }, ui.rich(r.quiz.question)),
    el('span', { class: 'vr-res', text: r.firstTry ? 'Sustained first time' : `Sustained on attempt ${r.attempts}` }),
    el('span', { class: 'vr-pts', text: `+${r.score}` })));
  const checks = el('details', { class: 'drawer' },
    el('summary', {}, `Claims & sources (${game.checks.length})`),
    el('ol', { class: 'checks' }, game.checks.map((c) => el('li', {}, el('span', { class: 'check-claim' }, ui.rich(c.claim)), ui.chips(c.cites)))),
    game.removed.length ? el('div', { class: 'removed' }, el('h4', { text: 'Removed during checking' }), el('ul', {}, game.removed.map((r) => el('li', {}, ui.rich(r))))) : null);
  const card = el('div', { class: `result glass ${out.won ? 'is-won' : 'is-lost'}` },
    el('p', { class: 'result-kicker', text: game.title }),
    el('h2', { class: 'result-title', text: out.won ? 'Case won' : 'Case lost' }),
    out.text && out.text.split(/\s+/).length > 2 ? el('p', { class: 'result-outcome' }, ui.rich(out.text)) : null,
    el('div', { class: 'result-scores' },
      el('div', { class: 'score-box' }, el('span', { class: 'score-label', text: 'Case outcome' }), el('span', { class: 'score-val', text: out.won ? 'Won' : 'Lost' })),
      el('div', { class: 'score-box' }, el('span', { class: 'score-label', text: 'Advocate score' }), el('span', { class: 'score-val', text: max ? `${score}` : '—' }), max ? el('span', { class: 'score-max', text: `/ ${max}` }) : null)),
    rows.length ? el('ol', { class: 'vr-list' }, rows) : null,
    checks,
    el('div', { class: 'res-actions' }, el('button', { class: 'btn btn-primary', type: 'button', 'data-value': 'go', 'data-autofocus': true }, 'Continue', el('span', { class: 'btn-arrow', 'aria-hidden': 'true', text: '→' }))));
  root.replaceChildren(card);
  focusFirst(card);
  await choose(card.querySelector('.res-actions'), {});

  // 3. epilogue
  const takeaway = game.verdict?.takeaway || game.takeaway || results[results.length - 1]?.quiz.irac.conclusion || '';
  const epi = el('div', { class: 'epilogue glass' },
    el('p', { class: 'result-kicker', text: 'For the exam' }),
    el('p', { class: 'epi-line' }, ui.rich(takeaway)),
    el('div', { class: 'res-actions' },
      hasNext ? el('button', { class: 'btn btn-primary', type: 'button', 'data-value': 'next', 'data-autofocus': true }, 'Next case', el('span', { class: 'btn-arrow', 'aria-hidden': 'true', text: '→' })) : null,
      el('button', { class: `btn ${hasNext ? 'btn-ghost' : 'btn-primary'}`, type: 'button', 'data-value': 'library', ...(hasNext ? {} : { 'data-autofocus': true }) }, 'Case docket')));
  root.replaceChildren(epi);
  focusFirst(epi);
  const v = await choose(epi, {});
  root.hidden = true;
  if (v === 'next') onNext?.(); else onLibrary?.();
  return { score, max, won: out.won };
}
