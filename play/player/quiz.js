// quiz.js: examination rounds (shuffled options, SUSTAINED / OVERRULED, consequences, retry), the IRAC reveal,
// and the verdict (closing argument, case outcome vs advocate score, claims & sources, epilogue).
import { el } from './ui.js';
import { shuffle } from './data.js';

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
export async function runRound({ ui, audio, stage, quiz, round, total, asker, reduced }) {
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
