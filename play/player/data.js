// data.js: loading the game index and game JSON, normalising it, progress storage, media override lookup.

// Everything is resolved relative to this module, so the player works when embedded under another path.
export const PLAYER_BASE = new URL('./', import.meta.url);
export const GAMES_BASE = new URL('../', import.meta.url);

// CognitioFlow: the player runs inside the app with ?course=<course id>. The game list comes from the app's
// signed-in docket endpoint (only that course's games) and there are no fixtures. Renders are still skipped
// in-app; glTF sets are not — they ship in play/assets/ and findAsset reads a manifest rather than probing,
// so the app can load them without paying for lookups that 404.
export const APP_COURSE = new URLSearchParams(location.search).get('course') || '';
const IN_APP = !!APP_COURSE;

const FIXTURES = IN_APP ? {} : {
  'w1-direct-effect-supremacy': new URL('./fixtures/w1.json', import.meta.url).href,
};

const SETS = ['customs_yard', 'office', 'courtroom', 'street', 'classroom', 'parliament', 'generic', 'tv_studio'];

async function fetchJSON(url) {
  const res = await fetch(url, { cache: 'no-cache', credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return res.json();
}

/** Library entries: index.json plus any fixture not covered by it. */
export async function loadIndex() {
  let list = [];
  try {
    const indexUrl = IN_APP ? `/api/courses/${encodeURIComponent(APP_COURSE)}/docket` : new URL('index.json', GAMES_BASE).href;
    const data = await fetchJSON(indexUrl);
    if (Array.isArray(data)) list = data.filter((g) => g && g.id && g.path);
  } catch (err) {
    console.warn('[data] index.json unavailable, using fixtures only', err);
  }
  const entries = list.map((g) => ({ ...g, url: new URL(g.path, GAMES_BASE).href, fixture: FIXTURES[g.id] || null }));
  for (const [id, url] of Object.entries(FIXTURES)) {
    if (!entries.some((e) => e.id === id)) entries.push({ id, url, fixture: null, isFixture: true });
  }
  // Fill in course/title/logline for the cards (games are small, so fetch them all).
  await Promise.all(entries.map(async (e) => {
    try {
      const g = await loadGameFrom(e);
      e.course = g.course; e.title = g.title; e.logline = g.logline; e.rounds = g.scenes.filter((s) => s.quiz).length;
      e.game = g;
    } catch (err) {
      e.error = String(err);
    }
  }));
  return entries.filter((e) => e.game);
}

async function loadGameFrom(entry) {
  try {
    return normaliseGame(await fetchJSON(entry.url));
  } catch (err) {
    if (entry.fixture) {
      console.warn(`[data] ${entry.url} failed, falling back to fixture`, err);
      return normaliseGame(await fetchJSON(entry.fixture));
    }
    throw err;
  }
}

// ---------- normalisation ----------

const CITE_RE = /\[?\s*([A-Z][A-Z0-9]{0,5})\s+p{1,2}\.\s*([0-9]+(?:\s*[-–]\s*[0-9]+)?)\s*\]?/;
const INLINE_CITE_RE = /\[([A-Z][A-Z0-9]{0,5})\s+p{1,2}\.\s*([0-9]+(?:\s*[-–]\s*[0-9]+)?)\]/g;

export function parseCite(c) {
  if (!c) return null;
  if (typeof c === 'object') {
    const key = c.key || c.source || c.KEY;
    const page = c.page ?? c.p ?? '';
    return key ? { key: String(key), page: String(page), label: page !== '' ? `${key} p.${page}` : String(key) } : null;
  }
  const s = String(c).trim();
  const m = s.match(CITE_RE);
  if (m) return { key: m[1], page: m[2].replace(/\s+/g, ''), label: `${m[1]} p.${m[2].replace(/\s+/g, '')}` };
  const key = s.replace(/[[\]]/g, '').split(/\s+/)[0];
  return key ? { key, page: '', label: s.replace(/[[\]]/g, '') } : null;
}

function cites(list) {
  if (!list) return [];
  const arr = Array.isArray(list) ? list : String(list).split(/[;,]\s*(?=\[?[A-Z])/);
  const out = [];
  const seen = new Set();
  for (const c of arr) {
    const p = parseCite(c);
    if (p && !seen.has(p.label)) { seen.add(p.label); out.push(p); }
  }
  return out;
}

/** Split text into [{text}|{cite}] parts, so inline "[L1 p.22]" becomes a chip. */
export function splitInlineCites(text) {
  const parts = [];
  let last = 0;
  const s = String(text ?? '');
  for (const m of s.matchAll(INLINE_CITE_RE)) {
    if (m.index > last) parts.push({ text: s.slice(last, m.index) });
    parts.push({ cite: parseCite(m[0]) });
    last = m.index + m[0].length;
  }
  if (last < s.length) parts.push({ text: s.slice(last) });
  return parts;
}

function str(v) { return v == null ? '' : String(v); }

/** Canonical speaker key used for casting: "JUDGE DE WIT" -> judge, "TRAINEE (V.O.)" -> trainee. */
export function speakerKey(name) {
  const s = str(name).toLowerCase().replace(/\(.*?\)/g, '').replace(/[^a-z\s.]/g, ' ').trim();
  if (!s) return 'narrator';
  if (/\b(trainee|you|player|counsel for kade)\b/.test(s)) return 'trainee';
  if (/\bjudge\b/.test(s)) return 'judge';
  const words = s.replace(/\b(mr|mrs|ms|dr|officer|prof)\.?\s*/g, '').split(/\s+/).filter(Boolean);
  return words[0] || 'narrator';
}

export function isVoiceOver(name) { return /\bV\.?\s?O\.?\b/i.test(str(name)); }

function normShot(s, i) {
  const d = Number(s?.duration_s);
  return {
    n: str(s?.n ?? i + 1),
    size: str(s?.size), angle: str(s?.angle), movement: str(s?.movement),
    lens: str(s?.lens), lighting: str(s?.lighting), subject: str(s?.subject),
    duration_s: Number.isFinite(d) && d > 0 ? d : 4,
    afterQuiz: /after (the )?correct/i.test(`${s?.size} ${s?.angle} ${s?.subject}`),
  };
}

function normOption(o, i) {
  return {
    key: str(o?.key || 'ABCD'[i] || String(i + 1)).toUpperCase(),
    text: str(o?.text),
    correct: !!o?.correct,
    outcome_title: str(o?.outcome_title),
    story: str(o?.story),
    teaching: str(o?.teaching),
    cites: cites(o?.cites),
    stamp: /overrul/i.test(str(o?.stamp)) ? 'OVERRULED' : /sustain/i.test(str(o?.stamp)) ? 'SUSTAINED' : (o?.correct ? 'SUSTAINED' : 'OVERRULED'),
  };
}

function normQuiz(q, sceneIdx) {
  if (!q || !Array.isArray(q.options) || !q.options.length) return null;
  const irac = q.irac || {};
  return {
    id: str(q.id || `q${sceneIdx + 1}`),
    question: str(q.question),
    options: q.options.map(normOption),
    irac: { issue: str(irac.issue), rule: str(irac.rule), application: str(irac.application), conclusion: str(irac.conclusion) },
    cites: cites(q.cites),
  };
}

function normScene(s, i) {
  const slug = s?.slug || {};
  const set = SETS.includes(s?.set) ? s.set : 'generic';
  const shots = (Array.isArray(s?.shots) ? s.shots : []).map(normShot);
  return {
    id: str(s?.id || `s${i + 1}`),
    title: str(s?.title || `Scene ${i + 1}`),
    slug: typeof slug === 'string' ? { int_ext: '', place: slug, time: '' } : { int_ext: str(slug.int_ext), place: str(slug.place), time: str(slug.time) },
    set,
    action: (Array.isArray(s?.action) ? s.action : s?.action ? [s.action] : []).map(str).filter(Boolean),
    dialogue: (Array.isArray(s?.dialogue) ? s.dialogue : []).map((d) => ({
      speaker: str(d?.speaker || ''), key: speakerKey(d?.speaker), vo: isVoiceOver(d?.speaker),
      line: str(d?.line), cites: cites(d?.cites),
    })).filter((d) => d.line),
    shots: shots.filter((x) => !x.afterQuiz),
    epilogueShots: shots.filter((x) => x.afterQuiz),
    quiz: normQuiz(s?.quiz, i),
    phase: PHASES.includes(str(s?.phase).toLowerCase()) ? str(s.phase).toLowerCase() : '',
  };
}

const PHASES = ['arrival', 'briefing', 'examination', 'verdict', 'epilogue', 'scene'];

/** Fill in phases when the JSON has none: first scene = briefing (or arrival if it is a street exterior), quiz scenes = examination. */
function inferPhases(scenes) {
  scenes.forEach((sc, i) => {
    if (sc.phase) return;
    const ext = /ext/i.test(sc.slug.int_ext);
    const streety = /street|backstreet|road|alley|outside|pavement|sidewalk/i.test(sc.slug.place) || sc.shots.some((x) => /third-person|player-driven/i.test(`${x.size} ${x.movement}`));
    if (i === 0 && ext && streety) sc.phase = 'arrival';
    else if (sc.quiz) sc.phase = 'examination';
    else if (i === 0 || (i === 1 && scenes[0].phase === 'arrival')) sc.phase = 'briefing';
    else sc.phase = 'scene';
  });
  return scenes;
}

function normIrac(x) {
  return { issue: str(x?.issue), rule: str(x?.rule), application: str(x?.application), conclusion: str(x?.conclusion) };
}

export function normaliseGame(g) {
  if (!g || !Array.isArray(g.scenes)) throw new Error('Game JSON has no scenes');
  const sources = {};
  for (const [k, v] of Object.entries(g.sources || {})) {
    sources[k] = typeof v === 'string' ? { file: v, kind: '', note: '' } : { file: str(v?.file || v?.name), kind: str(v?.kind), note: str(v?.note) };
  }
  return {
    id: str(g.id), course: str(g.course), title: str(g.title), logline: str(g.logline),
    learning_goal: str(g.learning_goal), takeaway: str(g.takeaway || g.verdict?.takeaway || ''),
    sources,
    bible: { palette: g.bible?.palette || [], mood: str(g.bible?.mood), notes: (g.bible?.notes || []).map(str) },
    scenes: inferPhases(g.scenes.map(normScene)),
    case_file: (Array.isArray(g.case_file) ? g.case_file : []).map(str).filter(Boolean),
    verdict: g.verdict ? {
      outcome: str(g.verdict.outcome),
      irac: (Array.isArray(g.verdict.irac) ? g.verdict.irac : g.verdict.irac ? [g.verdict.irac] : []).map(normIrac),
      takeaway: str(g.verdict.takeaway),
    } : null,
    checks: (g.checks || []).map((c, i) => ({ n: c?.n ?? i + 1, claim: str(c?.claim), cites: cites(c?.cites) })),
    removed: (g.removed || []).map(str),
    coordinator_notes: (g.coordinator_notes || []).map(str),
  };
}

// ---------- progress ----------

const PROGRESS_KEY = 'lawquiz.progress.v1';
const PREFS_KEY = 'lawquiz.prefs.v1';

function readStore(key) {
  try { return JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch { return {}; }
}
function writeStore(key, val) {
  try { localStorage.setItem(key, JSON.stringify(val)); } catch { /* storage unavailable */ }
}

export function getProgress(id) { return readStore(PROGRESS_KEY)[id] || null; }

export function saveResult(id, score, max, won) {
  const all = readStore(PROGRESS_KEY);
  const prev = all[id] || { best: 0, completed: false, plays: 0 };
  all[id] = {
    best: Math.max(prev.best || 0, score), max,
    completed: true, won: !!(prev.won || won),
    plays: (prev.plays || 0) + 1, last: new Date().toISOString(),
  };
  writeStore(PROGRESS_KEY, all);
  return all[id];
}

export function loadPrefs() {
  return { quality: 'auto', music: 0.6, sfx: 0.8, muted: false, voice: false, ...readStore(PREFS_KEY) };
}
export function savePrefs(p) { writeStore(PREFS_KEY, p); }

// ---------- media override ----------

const mediaCache = new Map();

async function exists(url) {
  try {
    const res = await fetch(url, { method: 'HEAD', cache: 'no-cache' });
    const type = res.headers.get('content-type') || '';
    return res.ok && !type.includes('text/html');
  } catch { return false; }
}

/** Returns {type:'video'|'image', url} if a Blender render was dropped in for this scene, else null. */
export async function findMedia(game, scene) {
  if (IN_APP) return null;
  const key = `${game.course}/${game.id}/${scene.id}`;
  if (mediaCache.has(key)) return mediaCache.get(key);
  const base = new URL(`${encodeURIComponent(game.course)}/media/${encodeURIComponent(game.id)}/${encodeURIComponent(scene.id)}`, GAMES_BASE).href;
  let found = null;
  if (await exists(`${base}.mp4`)) found = { type: 'video', url: `${base}.mp4` };
  else if (await exists(`${base}.webp`)) found = { type: 'image', url: `${base}.webp` };
  else if (await exists(`${base}.png`)) found = { type: 'image', url: `${base}.png` };
  mediaCache.set(key, found);
  return found;
}

// ---------- Blender glTF assets ----------

// Under the player mount (/play/player) so the app actually serves it — /play/assets is not mounted.
// The -v1 suffix opts into PlayerFiles' immutable cache; rename the folder when the contents change.
export const ASSETS_BASE = new URL('assets-v1/', PLAYER_BASE);
const assetCache = new Map();

/** Assets that exist, as {kind: [name, …]}. One fetch, cached; {} when there is no manifest yet.
 *
 * This replaces a HEAD probe per asset. The probe is why findAsset used to bail out on `IN_APP`:
 * in the app nothing was ever there, so every scene paid for requests that could only 404. A
 * manifest costs one request whatever the context, so assets can now load in the app as well as
 * in the standalone player — which is the whole point of putting them in `play/assets/`.
 */
let assetIndex = null;
function assetManifest() {
  if (!assetIndex) {
    assetIndex = fetch(new URL('index.json', ASSETS_BASE).href, { cache: 'no-cache' })
      .then((r) => (r.ok ? r.json() : {}))
      .catch(() => ({}));
  }
  return assetIndex;
}

/** URL of play/assets/<kind>/<name>.glb when the manifest lists it, else null. */
export async function findAsset(kind, name) {
  const key = `${kind}/${name}`;
  if (!assetCache.has(key)) {
    assetCache.set(key, assetManifest().then((index) => {
      const names = Array.isArray(index?.[kind]) ? index[kind] : [];
      return names.includes(name) ? new URL(`${kind}/${name}.glb`, ASSETS_BASE).href : null;
    }));
  }
  return assetCache.get(key);
}

/** Fisher-Yates shuffle (returns a new array). */
export function shuffle(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}
