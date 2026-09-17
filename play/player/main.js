// main.js: boots the player and runs the flow Arrival → Briefing → Examination → Verdict → Epilogue.
import { loadIndex, loadPrefs, savePrefs, saveResult, findMedia, speakerKey } from './data.js';
import { UI } from './ui.js';
import { AudioEngine } from './audio.js';
import { Stage3D, Stage2D, webglAvailable } from './stage.js';
import { runRound, runVerdict, SCORE_FIRST } from './quiz.js';
import { profileFor } from './human.js';
import { runLawyerShow } from './lawyer.js';
import { APP_COURSE } from './data.js';

const $ = (s) => document.querySelector(s);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const params = new URLSearchParams(location.search);

// ---------- CognitioFlow host ----------
// Inside the app the player runs in an iframe overlay. Escape (when no panel or dialog is open) and the show's
// "Back to Arena" hand control back to the page; opened on its own, they go to the app's home.
const EMBEDDED = window.parent !== window;
function exitToApp() {
  if (EMBEDDED) window.parent.postMessage({ type: 'cf-play-exit' }, location.origin);
  else location.href = '/';
}
window.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape' || !APP_COURSE) return;
  const busy = !$('#soundPanel').hidden || !$('#casefile').hidden
    || document.querySelector('.lw-confirm:not([hidden]), .lw-reveal:not([hidden]), .lw-end:not([hidden])');
  if (!busy) { e.preventDefault(); exitToApp(); }
}, true);

const reducedMQ = window.matchMedia('(prefers-reduced-motion: reduce)');
let reduced = reducedMQ.matches || params.has('reduced');
const prefs = loadPrefs();
if (params.get('quality')) prefs.quality = params.get('quality');
const autoQuality = !params.get('quality') && !prefs.qualityLocked;

const audio = new AudioEngine(prefs);
const ui = new UI({ reduced, audio });
document.documentElement.classList.toggle('reduced', reduced);

let stage;
const use3D = webglAvailable() && !params.has('nowebgl');
function makeStage() {
  const container = $('#stage');
  const opts = {
    quality: prefs.quality === 'low' ? 'low' : 'high', autoQuality, reduced, audio,
    onQualityDrop: () => { prefs.quality = 'low'; syncQualityBtn(); ui.toast('Low quality enabled to keep the frame rate up'); },
    onLoading: (on) => ui.loading(on),
  };
  if (use3D) {
    try { return new Stage3D(container, opts); } catch (err) { console.warn('[main] WebGL stage failed, using 2D fallback', err); }
  }
  document.documentElement.classList.add('no-webgl');
  return new Stage2D(container, opts);
}
stage = makeStage();
ui.onLayout = (vis) => stage.setVisibleHeight(vis);
ui.layout();
ui.onCaseFile = () => {};

reducedMQ.addEventListener?.('change', (e) => {
  reduced = e.matches || params.has('reduced');
  document.documentElement.classList.toggle('reduced', reduced);
  ui.setReduced(reduced);
  stage.setReduced(reduced);
});

// unlock audio on the first gesture
const unlock = () => { audio.unlock(); };
window.addEventListener('pointerdown', unlock, { capture: true });
window.addEventListener('keydown', unlock, { capture: true });

// ---------- HUD controls ----------

function syncQualityBtn() {
  const b = $('#qualityBtn');
  b.querySelector('.hud-val').textContent = prefs.quality === 'low' ? 'Low' : 'High';
  b.setAttribute('aria-label', `Graphics quality: ${prefs.quality === 'low' ? 'Low' : 'High'}. Toggle.`);
}
$('#qualityBtn').addEventListener('click', () => {
  prefs.quality = prefs.quality === 'low' ? 'high' : 'low';
  prefs.qualityLocked = true;
  stage.autoQuality = false;
  stage.setQuality(prefs.quality);
  savePrefs(prefs);
  syncQualityBtn();
});
syncQualityBtn();

const voiceBtn = $('#voiceBtn');
function syncVoice() {
  voiceBtn.setAttribute('aria-pressed', prefs.voice ? 'true' : 'false');
  voiceBtn.querySelector('.hud-val').textContent = prefs.voice ? 'On' : 'Off';
}
if (!('speechSynthesis' in window)) voiceBtn.hidden = true;
voiceBtn.addEventListener('click', () => { prefs.voice = !prefs.voice; audio.setVoice(prefs.voice); savePrefs(prefs); syncVoice(); });
audio.setVoice(prefs.voice);
syncVoice();

const soundPanel = $('#soundPanel');
$('#soundBtn').addEventListener('click', () => {
  soundPanel.hidden = !soundPanel.hidden;
  $('#soundBtn').setAttribute('aria-expanded', String(!soundPanel.hidden));
  if (!soundPanel.hidden) $('#musicVol').focus();
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !soundPanel.hidden) { soundPanel.hidden = true; $('#soundBtn').focus(); } });
$('#musicVol').value = String(Math.round(prefs.music * 100));
$('#sfxVol').value = String(Math.round(prefs.sfx * 100));
$('#muteChk').checked = !!prefs.muted;
function syncSound() {
  prefs.music = Number($('#musicVol').value) / 100;
  prefs.sfx = Number($('#sfxVol').value) / 100;
  prefs.muted = $('#muteChk').checked;
  audio.setVolumes(prefs);
  savePrefs(prefs);
  $('#soundBtn').querySelector('.hud-val').textContent = prefs.muted ? 'Muted' : 'On';
}
for (const id of ['musicVol', 'sfxVol', 'muteChk']) $(`#${id}`).addEventListener('input', syncSound);
syncSound();
document.addEventListener('keydown', (e) => {
  if (e.key.toLowerCase() === 'm' && !/INPUT|TEXTAREA/.test(e.target.tagName) && !e.metaKey && !e.ctrlKey) {
    $('#muteChk').checked = !$('#muteChk').checked; syncSound();
    ui.toast(prefs.muted ? 'Sound muted' : 'Sound on', 1400);
  }
});

let session = null;
$('#skipBtn').addEventListener('click', () => skip());
function skip() {
  if (!session) return;
  session.skipScene = true;
  if (stage.arrival) stage.skipArrival();
  ui.cancelWaits();
  session.wake?.();
}
$('#exitBtn').addEventListener('click', () => toLibrary());
$('#arrivalSkip').addEventListener('click', () => skip());
$('#arrivalAuto').addEventListener('click', () => stage.autoWalk());

// ---------- library ----------

let entries = [];

async function toLibrary() {
  if (session) session.dead = true;
  session = null;
  audio.stopSpeech();
  ui.cancelWaits();
  if (stage.arrival) stage.skipArrival();
  ui.showMedia(null);
  stage.pause(false);
  stage.freeze(false);
  ui.showScreen('library');
  ui.renderLibrary(entries, (e) => play(e.game));
  audio.music('arrival');
  await stage.showBackdrop(entries[0]?.game?.scenes.find((s) => s.phase !== 'arrival')?.set || 'courtroom');
  $('#library h1')?.focus({ preventScroll: true });
}

// ---------- flow helpers ----------

class Session {
  constructor(game) {
    this.game = game;
    this.skipScene = false;
    this.dead = false;
    this.wake = null;
  }
  check() { if (this.dead) throw new Error('session-ended'); }
  /** Sleep that can be cut short by skip or by the shot runner. */
  nap(ms) {
    return new Promise((resolve) => {
      const t = setTimeout(done, ms);
      function done() { clearTimeout(t); resolve(); }
      this.wake = done;
    });
  }
}

const PHASE_LABEL = { arrival: 'Arrival', briefing: 'Case briefing', examination: 'Examination', verdict: 'Verdict', epilogue: 'Epilogue', scene: 'Scene' };

function slugText(slug) {
  return [slug.int_ext && `${slug.int_ext.replace(/\.?$/, '.')}`, slug.place, slug.time && `– ${slug.time}`].filter(Boolean).join(' ');
}

/** Characters for a scene: dialogue speakers (not voice-over-only) plus roster names in the action lines. */
function castFor(game, scene) {
  const speakers = new Map();
  for (const sc of game.scenes) for (const d of sc.dialogue) if (!speakers.has(d.key)) speakers.set(d.key, d.speaker);
  const present = new Map();
  for (const d of scene.dialogue) if (!d.vo && !present.has(d.key)) present.set(d.key, d.speaker);
  const action = scene.action.join(' ');
  for (const [key, name] of speakers) {
    if (present.has(key)) continue;
    const words = [key, ...String(name).toLowerCase().replace(/\(.*?\)/g, '').split(/\s+/).filter((w) => w.length > 2 && !['the', 'judge', 'officer'].includes(w))];
    if (words.some((w) => new RegExp(`\\b${w.replace(/[^a-z]/g, '')}\\b`, 'i').test(action)) || (key === 'trainee' && /\b(trainee|you|lawyer)\b/i.test(action))) present.set(key, name);
  }
  return [...present].map(([key, speaker]) => ({ key, speaker }));
}

function askerFor(scene) {
  const non = scene.dialogue.filter((d) => d.key !== 'trainee' && d.key !== 'narrator');
  const last = non[non.length - 1];
  if (!last) return '';
  return last.speaker.replace(/\(.*?\)/g, '').trim().toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

function speakLine(d) {
  const prof = profileFor(d.key, d.speaker);
  audio.speak(d.line, d.key, { female: !!prof.female });
}

/** Runs shots in order until stopped; `next()` moves on early. */
function shotRunner(s, scene, shots, { startIndex = 0, loopLast = true } = {}) {
  const r = { idx: startIndex - 1, stopped: false, plan: null, startedAt: 0, done: null };
  let wake = null;
  r.next = () => wake?.();
  r.stop = () => { r.stopped = true; wake?.(); };
  r.elapsedFrac = () => (r.plan ? (performance.now() - r.startedAt) / 1000 / r.plan.duration : 1);
  r.done = (async () => {
    if (!shots.length) { stage.playEstablishing(0); return; }
    while (!r.stopped && !s.dead) {
      if (r.idx >= shots.length - 1) {
        if (!loopLast) break;
        await new Promise((res) => { wake = res; });
        continue;
      }
      r.idx++;
      const shot = shots[r.idx];
      r.plan = stage.playShot(shot, r.idx);
      r.startedAt = performance.now();
      if (r.plan?.caption) ui.caption(r.plan.caption, 5500);
      if (r.plan?.titleCard) ui.bigTitle(r.plan.titleCard);
      await new Promise((res) => {
        const t = setTimeout(res, (r.plan?.duration || 4) * 1000);
        wake = () => { clearTimeout(t); res(); };
      });
    }
  })();
  return r;
}

// ---------- phases ----------

async function runArrival(s, arrivalScene, destKind) {
  const game = s.game;
  ui.setHud({ phase: PHASE_LABEL.arrival });
  const cast = arrivalScene ? castFor(game, arrivalScene) : [];
  if (!cast.some((c) => c.key === 'trainee')) cast.unshift({ key: 'trainee', speaker: 'You' });
  await stage.loadScene({ kind: 'street', cast, destKind });
  s.check();
  ui.showMedia(null);
  stage.pause(false);
  ui.letterbox(2.0);
  const arrivalDone = stage.startArrival();
  audio.music('arrival');
  const dest = stage.set?.destination?.label || '';
  const slug = arrivalScene ? slugText(arrivalScene.slug) : `EXT. CITY STREET – NIGHT`;
  ui.titleCard({ kicker: `${game.course} · ${PHASE_LABEL.arrival}`, slug, title: game.title }, 3000);
  ui.arrivalHud(true, { destination: dest });
  const prog = setInterval(() => ui.arrivalProgress(stage.arrivalProgress()), 120);
  if (params.get('walk')) setTimeout(() => stage.autoWalk(), Number(params.get('walk')) * 1000);

  // arrival dialogue plays over the walk, auto-advancing
  let arrived = false;
  const lines = arrivalScene ? arrivalScene.dialogue.slice() : [];
  let li = 0;
  const talk = (async () => {
    await sleep(3200);
    if (arrivalScene) arrivalScene.action.forEach((a, i) => { setTimeout(() => { if (!arrived) ui.caption(a, 6000); }, i * 2600); ui.addFact(a, { group: arrivalScene.title, quiet: i > 0 }); });
    while (li < lines.length && !arrived && !s.dead) {
      const d = lines[li++];
      stage.setSpeaker(d.key);
      speakLine(d);
      if (d.key !== 'trainee') ui.addFact(`${d.speaker}: ${d.line}`, { group: arrivalScene.title, cites: d.cites, quiet: true });
      await ui.say({ ...d, isPlayer: d.key === 'trainee' }, { autoMs: 3000 });
    }
  })();
  const res = await arrivalDone;
  arrived = true;
  clearInterval(prog);
  ui.arrivalHud(false);
  stage.setSpeaker(null);
  s.check();
  ui.cancelWaits();
  await talk;
  // lines not heard yet: play them at the door, player-paced
  if (li < lines.length && !res.skipped && !s.skipScene) {
    stage.playEstablishing(1);
    while (li < lines.length && !s.skipScene) {
      const d = lines[li++];
      stage.setSpeaker(d.key);
      speakLine(d);
      if (d.key !== 'trainee') ui.addFact(`${d.speaker}: ${d.line}`, { group: arrivalScene.title, cites: d.cites, quiet: true });
      await ui.say({ ...d, isPlayer: d.key === 'trainee' });
    }
  } else if (arrivalScene) {
    for (const d of lines) if (d.key !== 'trainee') ui.addFact(`${d.speaker}: ${d.line}`, { group: arrivalScene.title, cites: d.cites, quiet: true });
  }
  ui.hideSubtitle();
  s.skipScene = false;
  stage.post && (stage.post.target.fade = 1);
  await sleep(reduced ? 50 : 450);
}

async function playScene(s, scene, i, round, totalRounds, { jumpToQuiz = false, auto = false } = {}) {
  const game = s.game;
  s.skipScene = false;
  const phase = scene.phase || (scene.quiz ? 'examination' : 'scene');
  ui.setHud({ phase: `${PHASE_LABEL[phase] || 'Scene'} · ${scene.title}` });
  const media = await findMedia(game, scene);
  const cast = castFor(game, scene);
  await stage.loadScene({ kind: scene.set, cast });
  s.check();
  ui.showMedia(media);
  stage.pause(!!media);
  ui.letterbox(2.39);
  if (stage.post) stage.post.target.fade = 0;
  audio.music(phase === 'examination' ? 'examination' : 'briefing');

  const freezeIdx = scene.quiz ? Math.max(0, scene.shots.findIndex((x) => /freeze/i.test(x.movement))) : -1;
  const preShots = scene.quiz && freezeIdx >= 0 && /freeze/i.test(scene.shots[freezeIdx]?.movement || '') ? scene.shots.slice(0, freezeIdx) : scene.shots.slice(0, scene.quiz ? -1 : undefined);
  const quizShot = scene.quiz ? (scene.shots[freezeIdx >= 0 && /freeze/i.test(scene.shots[freezeIdx]?.movement || '') ? freezeIdx : scene.shots.length - 1] || null) : null;
  const shots = preShots.length ? preShots : scene.shots;
  const runner = shotRunner(s, scene, jumpToQuiz ? [] : shots, { loopLast: true });

  const title = ui.titleCard({ kicker: `${PHASE_LABEL[phase] || 'Scene'}${scene.quiz ? ` · Round ${round} of ${totalRounds}` : ''}`, slug: slugText(scene.slug), title: scene.title });
  scene.action.forEach((a, k) => {
    ui.addFact(a, { group: scene.title, quiet: k > 0 });
    if (!jumpToQuiz) setTimeout(() => { if (!s.dead && !s.skipScene) ui.caption(a, 6500); }, 2900 + k * 2800);
  });
  await title;
  s.check();

  if (!jumpToQuiz) {
    for (const d of scene.dialogue) {
      if (s.skipScene || s.dead) break;
      if (runner.elapsedFrac() > 0.55) runner.next();
      stage.setSpeaker(d.key);
      speakLine(d);
      if (phase === 'briefing' && d.key !== 'trainee') ui.addFact(`${d.speaker}: ${d.line}`, { group: scene.title, cites: d.cites, quiet: true });
      await ui.say({ ...d, isPlayer: d.key === 'trainee' }, { autoMs: auto ? 2500 : 0 });
    }
    stage.setSpeaker(null);
    audio.stopSpeech();
  }
  s.check();

  if (scene.quiz) {
    runner.stop();
    ui.hideSubtitle();
    if (quizShot) stage.playShot(quizShot, 99);
    else stage.playEstablishing(2);
    await sleep(reduced ? 200 : 1400);
    s.check();
    stage.freeze(true);
    const r = await runRound({ ui, audio, stage, quiz: scene.quiz, round, total: totalRounds, asker: askerFor(scene), reduced });
    s.check();
    stage.freeze(false);
    audio.music('briefing');
    if (scene.epilogueShots.length) {
      stage.epilogueBeat();
      s.skipScene = false;
      const ep = shotRunner(s, scene, scene.epilogueShots, { loopLast: false });
      const correct = scene.quiz.options.find((o) => o.correct);
      if (correct?.story) ui.caption(correct.story, 7000);
      await Promise.race([ep.done, ui.prompt('Continue')]);
      ep.stop();
      ui.hideSubtitle();
    }
    return { ...r, quiz: scene.quiz };
  }

  // scenes without a question: let the remaining shots play, or continue on demand
  if (!s.skipScene && runner.idx < shots.length - 1) {
    const fin = (async () => { while (!runner.stopped && runner.idx < shots.length - 1) await sleep(200); await sleep(1500); })();
    await Promise.race([fin, ui.prompt('Continue')]);
  } else if (!s.skipScene) {
    await ui.prompt('Continue');
  }
  runner.stop();
  ui.hideSubtitle();
  return null;
}

async function play(game, { at = null, sceneIdx = 0, quiz = false, verdict = false, auto = false } = {}) {
  if (session) session.dead = true;
  ui.cancelWaits();
  const s = session = new Session(game);
  ui.showScreen('play');
  ui.setSources(game.sources);
  ui.resetCaseFile(game);
  for (const f of game.case_file) ui.addFact(f, { group: 'Case file', quiet: true });
  ui.setHud({ title: game.title, course: game.course });
  const idx = entries.findIndex((e) => e.id === game.id);
  const next = entries[idx + 1] || null;
  try {
    const scenes = game.scenes;
    const arrivalScene = scenes[0]?.phase === 'arrival' ? scenes[0] : null;
    const body = scenes.filter((x) => x !== arrivalScene);
    const destKind = (body.find((x) => x.set !== 'street') || body[0] || { set: 'courtroom' }).set;
    const totalRounds = body.filter((x) => x.quiz).length;
    const results = [];

    if (verdict) {
      for (const sc of body) if (sc.quiz) results.push({ firstTry: true, attempts: 1, wrongKeys: [], score: SCORE_FIRST, quiz: sc.quiz });
      const last = body[body.length - 1];
      await stage.loadScene({ kind: last?.set || 'courtroom', cast: last ? castFor(game, last) : [] });
      stage.playEstablishing(0);
    } else {
      if (!at || at === 'arrival') await runArrival(s, arrivalScene, destKind);
      let round = 0;
      for (let i = 0; i < body.length; i++) {
        const sc = body[i];
        if (sc.quiz) round++;
        if (at === 'scene' && i < sceneIdx) {
          if (sc.quiz) results.push({ firstTry: true, attempts: 1, wrongKeys: [], score: SCORE_FIRST, quiz: sc.quiz });
          sc.action.forEach((a) => ui.addFact(a, { group: sc.title, quiet: true }));
          continue;
        }
        const r = await playScene(s, sc, i, round, totalRounds, { jumpToQuiz: quiz && i === sceneIdx, auto });
        if (r) results.push(r);
      }
    }
    s.check();
    ui.setHud({ phase: PHASE_LABEL.verdict });
    ui.hideSubtitle();
    stage.freeze(false);
    const out = await runVerdict({
      ui, audio, game, results, reduced,
      hasNext: !!next,
      onNext: () => { if (next) play(next.game); },
      onLibrary: () => toLibrary(),
    });
    saveResult(game.id, out.score, out.max, out.won);
  } catch (err) {
    if (err.message !== 'session-ended') {
      console.error(err);
      ui.toast('Something went wrong in this case. Returning to the docket.');
      await sleep(1500);
      toLibrary();
    }
  }
}

// ---------- "Who Wants to Be a Lawyer?" inside CognitioFlow (?mode=lawyer&course=<id>) ----------

const courseApi = (path) => `/api/courses/${encodeURIComponent(APP_COURSE)}${path}`;

async function apiJSON(url, body) {
  const res = await fetch(url, body === undefined ? { credentials: 'same-origin' }
    : { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch { /* not JSON */ }
    throw new Error(res.status === 401 ? 'You are signed out. Sign in to CognitioFlow again.' : msg);
  }
  return res.json();
}

function loadStyles(hrefs) {
  return Promise.all(hrefs.map((href) => new Promise((resolve) => {
    const link = Object.assign(document.createElement('link'), { rel: 'stylesheet', href: new URL(href, import.meta.url).href });
    link.onload = link.onerror = resolve;
    document.head.append(link);
  })));
}

/** A dialog in the show's own look. Resolves with the value of the button pressed. */
function showDialog(root, { kicker, title, line, buttons }) {
  const box = document.createElement('div');
  box.className = 'lw-end glass';
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-label', title);
  const mk = (tag, cls, text) => Object.assign(document.createElement(tag), { className: cls, textContent: text });
  const actions = mk('div', 'lw-end-actions', '');
  box.append(mk('p', 'lw-end-kicker', kicker || ''), mk('h2', 'lw-end-title', title), mk('p', 'lw-end-line', line || ''), actions);
  root.append(box);
  return new Promise((resolve) => {
    for (const [value, label, primary] of buttons) {
      const b = mk('button', `lw-btn ${primary ? 'lw-btn-primary' : 'lw-btn-ghost'}`, label);
      b.type = 'button';
      b.addEventListener('click', () => { box.remove(); resolve(value); });
      actions.append(b);
    }
    actions.querySelector('.lw-btn-primary')?.focus();
  });
}

async function runShowMode() {
  document.documentElement.classList.add('is-ready');
  await loadStyles(['./lawyer.css', './app.css']);
  ui.showScreen('show');
  ui.letterbox(0);
  const root = Object.assign(document.createElement('div'), { id: 'lawyerRoot', className: 'lw-root' });
  $('#app').append(root);

  ui.loading(true, 'Writing questions from your cards');
  let pack = null;
  let signedIn = false;
  try {
    signedIn = !!(await apiJSON('/api/config')).email;
    pack = await apiJSON(courseApi('/lawyer-pack'));
  } catch (err) {
    ui.loading(false);
    await showDialog(root, { kicker: 'Who Wants to Be a Lawyer?', title: 'The show could not start', line: err.message, buttons: [['back', 'Back to Arena', true]] });
    return exitToApp();
  }
  ui.loading(false);
  if (!pack.questions?.length) {
    await showDialog(root, {
      kicker: pack.course, title: 'No questions yet',
      line: 'The show is built from your own cards. Make some in Recall first, then come back.',
      buttons: [['back', 'Back to Arena', true]],
    });
    return exitToApp();
  }

  const tutor = {
    available: signedIn,
    // The app's lifeline: one sentence pointing at the rule, never the answer (POST /api/courses/{cid}/hint).
    async ask(question, optionsText) {
      const options = String(optionsText || '').split('\n').filter(Boolean).map((l) => l.replace(/^[A-D]\)\s*/, ''));
      const r = await apiJSON(courseApi('/hint'), { question, options });
      return { text: r.hint, sources: [] };
    },
  };
  // A miss comes back through the app's scheduler, as in the 2D ladder; a right answer only counts if no lifeline carried it.
  const onAnswer = ({ question, correct, helped }) => {
    if (!question.card_id || (correct && helped)) return;
    apiJSON(`/api/cards/${encodeURIComponent(question.card_id)}/review`, { rating: correct ? 2 : 0 }).catch(() => {});
  };
  // Keep the studio camera moving: the show loads the set, then gets a slow establishing shot.
  const showStage = {
    loadScene: async (opts) => { const set = await stage.loadScene(opts); stage.playEstablishing(0); return set; },
    setSpeaker: (key) => stage.setSpeaker(key),
    freeze: (on) => stage.freeze(on),
  };

  for (;;) {
    await runLawyerShow({
      pack, stage: showStage, audio, root, reduced, tutor, onAnswer,
      ui: { rich: (t) => ui.rich(t) }, // host lines use the show's own box, above the set
      lowQuality: prefs.quality === 'low',
    });
    const again = await showDialog(root, {
      kicker: pack.course, title: 'Another round?', line: 'Any question you missed is already back in your Recall queue.',
      buttons: [['back', 'Back to Arena', false], ['again', 'Play again', true]],
    });
    if (again !== 'again') return exitToApp();
  }
}

// ---------- boot ----------

async function boot() {
  try { await Promise.race([document.fonts.ready, sleep(1500)]); } catch { /* fonts API missing */ }
  if (params.get('mode') === 'lawyer' && APP_COURSE) return runShowMode();
  entries = await loadIndex();
  const wanted = params.get('game');
  const entry = wanted && entries.find((e) => e.id === wanted);
  document.documentElement.classList.add('is-ready');
  if (entry) {
    ui.renderLibrary(entries, (e) => play(e.game));
    const at = params.get('at');
    play(entry.game, {
      at,
      sceneIdx: Number(params.get('scene') || 0),
      quiz: params.has('quiz'),
      verdict: at === 'verdict',
      auto: params.has('auto'),
    });
  } else {
    await toLibrary();
  }
}

boot().catch((err) => {
  console.error(err);
  $('#libraryGrid').replaceChildren(Object.assign(document.createElement('p'), { className: 'lib-empty', textContent: `Could not load the case docket: ${err.message}` }));
});

// expose for debugging
window.__player = { get stage() { return stage; }, ui, audio, play: (id) => play(entries.find((e) => e.id === id)?.game) };
void speakerKey;
