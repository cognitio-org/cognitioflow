// grade.js: deterministic, AI-free grading math for the produce-type interaction kinds
// (spot / order / slot). The "generation effect" interactions the student *produces* an answer for,
// as opposed to the A–D "mcq" kind the student *recognises*.
//
// Every function here is PURE: it takes the player's response and the quiz's cached `answer` key and
// returns { score: 0..1, correct: bool, detail }. No DOM, no network, no model call, and NO imports —
// so the exact code that grades in the browser at play-time is unit-testable under `node --test`
// (data.js/ui.js touch `location`/`document` at load, which node has not; grade.js touches neither).
//
// The A–D path in quiz.js/data.js is untouched; these kinds carry an `answer` and NO `options`, which
// is what makes the studio's retrieval_density gate classify them as generation rather than recognition.

export const PRODUCE_KINDS = new Set(['spot', 'order', 'slot']);

// A produced answer "counts" as a correct act above this fraction. Partial credit still flows to the
// score below the mark; this only decides the firstTry / "sustained" badge.
export const PASS_MARK = 0.6;

const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);

/** Normalise a taxonomy id / tag for exact-match: NFC (macOS keyboards type NFD, which would silently
 *  miss a precomposed baked id), trim, lowercase, collapse internal whitespace. */
export function normTag(s) {
  return String(s == null ? '' : s).normalize('NFC').trim().toLowerCase().replace(/\s+/g, ' ');
}

/** Character-offset Jaccard overlap of two [start,end] ranges: |intersection| / |union|, 0..1. */
export function spanJaccard(a, b) {
  if (!a || !b) return 0;
  const [a0, a1] = [Math.min(a[0], a[1]), Math.max(a[0], a[1])];
  const [b0, b1] = [Math.min(b[0], b[1]), Math.max(b[0], b[1])];
  const inter = Math.max(0, Math.min(a1, b1) - Math.max(a0, b0));
  const union = (a1 - a0) + (b1 - b0) - inter;
  return union > 0 ? inter / union : 0;
}

/**
 * spot — free-range issue spotting + open-taxonomy tag.
 * response: { selections: [{ span: [start,end], tag: "<taxonomy-id>" }, ...] }
 * answer:   { issues: [{ id, spans: [[s,e],...] }], decoys: [[s,e]], threshold }
 *
 * A real issue is recalled iff some selection BOTH overlaps one of its spans at Jaccard ≥ threshold
 * AND carries its taxonomy id. Every selection that recalls no (still-unmatched) issue is a false
 * positive — this is what defeats "select the whole passage": it recalls all issues but piles on FPs.
 * score = clamp01( (recalledIssues − falsePositives) / totalIssues ).
 */
export function gradeSpot(response, answer) {
  const issues = (answer && answer.issues) || [];
  const threshold = Number.isFinite(answer && answer.threshold) ? answer.threshold : 0.7;
  const selections = (response && response.selections) || [];
  const total = issues.length;

  const matched = new Set();
  let contributing = 0; // selections that recalled a not-yet-matched issue
  for (const sel of selections) {
    const tag = normTag(sel && sel.tag);
    let hit = false;
    for (let i = 0; i < issues.length; i++) {
      if (matched.has(i)) continue;
      if (normTag(issues[i].id) !== tag) continue;
      const best = Math.max(0, ...(issues[i].spans || []).map((sp) => spanJaccard(sel.span, sp)));
      if (best >= threshold) { matched.add(i); hit = true; break; }
    }
    if (hit) contributing++;
  }
  const falsePositives = selections.length - contributing;
  const recalled = matched.size;
  const score = total ? clamp01((recalled - falsePositives) / total) : (selections.length ? 0 : 1);
  return { score, correct: score >= PASS_MARK, detail: { recalled, total, falsePositives } };
}

/**
 * order — assemble the governing test in the order the court applies it.
 * response: { order: ["e1","e3","e2"] }
 * answer:   { sequence: ["e1","e2","e3"], unordered?: bool }
 *
 * unordered → bag equality (Jaccard of the id sets, for tests whose elements have no doctrinal order).
 * ordered   → fraction of positions that match the canonical sequence (random order earns only the
 *             positions it happens to land, never the whole mark).
 */
export function gradeOrder(response, answer) {
  const seq = (answer && answer.sequence) || [];
  const ord = (response && response.order) || [];
  if (answer && answer.unordered) {
    const A = new Set(seq.map(String));
    const B = new Set(ord.map(String));
    let inter = 0;
    for (const x of B) if (A.has(x)) inter++;
    const union = new Set([...A, ...B]).size;
    const score = union ? inter / union : 1;
    return { score, correct: score >= 1, detail: { mode: 'bag', inter, union } };
  }
  const n = seq.length;
  let hits = 0;
  for (let i = 0; i < n; i++) if (String(ord[i]) === String(seq[i])) hits++;
  const score = n ? hits / n : (ord.length ? 0 : 1);
  const exact = ord.length === n && hits === n;
  return { score, correct: exact, detail: { mode: 'sequence', hits, n } };
}

/**
 * slot — bipartite fact→element mapping.
 * response: { assignments: { f1:"e1", f2:"e3", ... } }   (fact id → element id; omit = unassigned)
 * answer:   { key: { f1:"e1", f2:"e2", ... }, elements, facts }
 *
 * TP = facts mapped to their key element; FP = facts mapped to the wrong element (unassigned facts are
 * simply missed, not penalised). score = clamp01( (TP − FP) / |key| ). This is the design's
 * (TP − FP)/elements, denominated in key pairs and clamped to [0,1] (an element that legitimately takes
 * several facts can otherwise push the raw ratio out of range). Shotgun-assigning every fact to one
 * element earns its few TPs but eats an FP for each wrong guess.
 */
export function gradeSlot(response, answer) {
  const key = (answer && answer.key) || {};
  const asg = (response && response.assignments) || {};
  const pairs = Object.keys(key);
  let tp = 0, fp = 0;
  for (const f of Object.keys(asg)) {
    if (!(f in key)) { fp++; continue; }          // assigned a fact that is not in the key
    if (String(asg[f]) === String(key[f])) tp++; else fp++;
  }
  const score = pairs.length ? clamp01((tp - fp) / pairs.length) : (Object.keys(asg).length ? 0 : 1);
  return { score, correct: score >= PASS_MARK, detail: { tp, fp, total: pairs.length } };
}

/** Dispatch a produce-type response to its grader. Unknown kind → zero. */
export function gradeProduce(kind, response, answer) {
  if (kind === 'spot') return gradeSpot(response, answer);
  if (kind === 'order') return gradeOrder(response, answer);
  if (kind === 'slot') return gradeSlot(response, answer);
  return { score: 0, correct: false, detail: { error: `unknown kind ${kind}` } };
}
