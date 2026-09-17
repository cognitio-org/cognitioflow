// ui.js: the HTML overlay. Library, HUD, title cards, captions, typewriter subtitles, citation chips,
// case file (PDA), letterbox, toasts, loading, media backdrop, arrival HUD.
import { splitInlineCites, getProgress, APP_COURSE } from './data.js';

const $ = (sel, root = document) => root.querySelector(sel);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function el(tag, attrs = {}, ...kids) {
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

let tipSeq = 0;

export class UI {
  constructor({ reduced = false, audio = null } = {}) {
    this.reduced = reduced;
    this.audio = audio;
    this.app = $('#app');
    this.sources = {};
    this.waiters = new Set();
    this.aspect = 2.39;
    this.factCount = 0;
    this.typing = null;
    document.addEventListener('keydown', (e) => this.onKey(e));
    $('#stage').addEventListener('click', () => this.advance());
    $('#subtitle').addEventListener('click', (e) => { if (!e.target.closest('button')) this.advance(); });
    $('#casefileBtn').addEventListener('click', () => this.toggleCaseFile());
    $('#casefileClose').addEventListener('click', () => this.toggleCaseFile(false));
    for (const tab of document.querySelectorAll('.cf-tab')) tab.addEventListener('click', () => this.caseTab(tab.dataset.tab));
    window.addEventListener('resize', () => this.layout());
    this.layout();
  }

  setReduced(r) { this.reduced = r; }

  onKey(e) {
    const tag = e.target?.tagName || '';
    const interactive = /^(BUTTON|A|INPUT|SELECT|TEXTAREA|SUMMARY)$/.test(tag);
    if ((e.key === ' ' || e.key === 'Enter') && !interactive && this.waiters.size) {
      e.preventDefault();
      this.advance();
    }
    if (e.key.toLowerCase() === 'c' && !interactive && !e.metaKey && !e.ctrlKey && this.app.dataset.screen === 'play') this.toggleCaseFile();
    if (e.key === 'Escape' && !$('#casefile').hidden) { this.toggleCaseFile(false); e.stopPropagation(); }
  }

  // ---------- screens ----------

  showScreen(name) {
    this.app.dataset.screen = name;
    $('#library').hidden = name !== 'library';
    $('#hud').hidden = name !== 'play';
    if (name !== 'play') {
      this.hideSubtitle();
      this.clearCaptions();
      $('#casefile').hidden = true;
      $('#exam').hidden = true;
      $('#verdict').hidden = true;
      $('#arrivalHud').hidden = true;
      $('#titlecard').replaceChildren();
    }
    this.letterbox(name === 'library' ? 0 : 2.39);
  }

  setHud({ title, course, phase }) {
    if (title != null) $('#hudTitle').textContent = title;
    if (course != null) $('#hudCourse').textContent = course;
    if (phase != null) $('#hudPhase').textContent = phase;
  }

  // ---------- letterbox ----------

  /** aspect 0 = no bars. Returns the visible height in px. */
  letterbox(aspect) {
    this.aspect = aspect;
    return this.layout();
  }

  layout() {
    const w = window.innerWidth, h = window.innerHeight;
    let a = this.aspect;
    if (a && w / h < 1.1) a = Math.max(0.9, Math.min(a, w / (h * 0.62)));
    const vis = a ? Math.min(h, w / a) : h;
    const bar = Math.max(0, (h - vis) / 2);
    document.documentElement.style.setProperty('--bar', `${bar}px`);
    document.documentElement.style.setProperty('--vis', `${vis}px`);
    this.visH = vis;
    this.onLayout?.(vis);
    return vis;
  }

  // ---------- library ----------

  renderLibrary(entries, onOpen) {
    const grid = $('#libraryGrid');
    grid.replaceChildren();
    if (!entries.length) {
      grid.append(el('p', { class: 'lib-empty', text: APP_COURSE ? 'No Case Docket games for this course yet. Pick another course in CognitioFlow, or play the 2D courtroom from your notes.' : 'No cases found. Run build_index.py in the games folder.' }));
      return;
    }
    const byCourse = new Map();
    for (const e of entries) {
      if (!byCourse.has(e.course)) byCourse.set(e.course, []);
      byCourse.get(e.course).push(e);
    }
    let n = 0;
    for (const [course, list] of byCourse) {
      for (const e of list) {
        n++;
        const prog = getProgress(e.id);
        const rounds = e.rounds || 0;
        const max = rounds * 100;
        const status = prog?.completed
          ? el('div', { class: `lib-status ${prog.won ? 'is-won' : 'is-done'}` },
            el('span', { class: 'lib-stamp', text: prog.won ? 'Case won' : 'Closed' }),
            el('span', { class: 'lib-best', text: max ? `Best ${prog.best} / ${prog.max || max}` : `Played ${prog.plays}×` }))
          : el('div', { class: 'lib-status is-new' }, el('span', { class: 'lib-stamp', text: 'Open case' }));
        const card = el('article', { class: 'lib-card', style: `--i:${n}` },
          el('div', { class: 'lib-top' },
            el('span', { class: 'lib-course', text: course }),
            el('span', { class: 'lib-no', text: `Case ${String(n).padStart(3, '0')}` })),
          el('h3', { class: 'lib-title', text: e.title }),
          el('p', { class: 'lib-logline', text: e.logline }),
          el('div', { class: 'lib-meta' },
            el('span', { text: rounds ? `${rounds} examination round${rounds === 1 ? '' : 's'}` : 'Story only' }),
            e.isFixture ? el('span', { class: 'lib-tag', text: 'fixture' }) : null),
          status,
          el('button', { class: 'btn btn-primary lib-play', type: 'button', onclick: () => onOpen(e), 'aria-label': `Take the case: ${e.title}` },
            prog?.completed ? 'Replay case' : 'Take the case', el('span', { class: 'btn-arrow', 'aria-hidden': 'true', text: '→' })));
        grid.append(card);
      }
    }
  }

  // ---------- title cards, captions ----------

  async titleCard({ kicker = '', slug = '', title = '' }, hold = 2600) {
    const tc = $('#titlecard');
    const card = el('div', { class: 'tc' },
      kicker ? el('div', { class: 'tc-kicker', text: kicker }) : null,
      el('div', { class: 'tc-slug', text: slug }),
      el('div', { class: 'tc-rule', 'aria-hidden': 'true' }),
      title ? el('div', { class: 'tc-title', text: title }) : null);
    tc.replaceChildren(card);
    this.audio?.sting('clang');
    await sleep(this.reduced ? Math.min(hold, 1600) : hold);
    card.classList.add('is-out');
    await sleep(this.reduced ? 50 : 600);
    if (card.parentNode) card.remove();
  }

  async bigTitle(text) {
    const tc = $('#titlecard');
    const card = el('div', { class: 'tc tc-big' }, el('div', { class: 'tc-hero', text }));
    tc.replaceChildren(card);
    await sleep(3200);
    card.classList.add('is-out');
    await sleep(700);
    if (card.parentNode) card.remove();
  }

  caption(text, ms = 5200) {
    const box = $('#captions');
    const c = el('p', { class: 'cap', text });
    box.append(c);
    while (box.children.length > 3) box.firstElementChild.remove();
    setTimeout(() => { c.classList.add('is-out'); setTimeout(() => c.remove(), 800); }, ms);
  }

  clearCaptions() { $('#captions').replaceChildren(); }

  // ---------- citation chips ----------

  setSources(sources) { this.sources = sources || {}; }

  chip(cite) {
    if (!cite) return null;
    const src = this.sources[cite.key];
    const id = `tip${++tipSeq}`;
    const file = src?.file || 'Source not listed in this case';
    return el('button', { class: 'chip', type: 'button', 'aria-describedby': id, 'data-key': cite.key },
      cite.label,
      el('span', { class: 'chip-tip', role: 'tooltip', id },
        el('strong', { text: file }),
        src?.kind ? el('span', { text: src.kind }) : null,
        src?.note ? el('em', { text: src.note }) : null));
  }

  chips(list) {
    if (!list?.length) return null;
    return el('span', { class: 'chips' }, list.map((c) => this.chip(c)));
  }

  /** Text with inline "[L1 p.22]" turned into chips. */
  rich(text) {
    const frag = document.createDocumentFragment();
    for (const p of splitInlineCites(text)) {
      if (p.cite) frag.append(this.chip(p.cite));
      else frag.append(document.createTextNode(p.text.replace(/,\s*$/, (m) => m)));
    }
    return frag;
  }

  // ---------- subtitles ----------

  advance() {
    if (this.typing) { this.typing.finish(); return; }
    for (const w of [...this.waiters]) w('advance');
  }

  /** Resolve every pending wait (used by Skip). */
  cancelWaits() {
    if (this.typing) this.typing.finish();
    for (const w of [...this.waiters]) w('skip');
  }

  wait(timeoutMs = 0) {
    return new Promise((resolve) => {
      let timer = null;
      const done = (why) => { this.waiters.delete(done); if (timer) clearTimeout(timer); resolve(why); };
      this.waiters.add(done);
      if (timeoutMs) timer = setTimeout(() => done('timeout'), timeoutMs);
    });
  }

  /** Show a dialogue line with a typewriter reveal, then wait for Space/Enter/click (or auto after `autoMs`). */
  async say({ speaker, line, cites = [], vo = false, isPlayer = false }, { autoMs = 0 } = {}) {
    const box = $('#subtitle');
    box.hidden = false;
    const name = $('#subSpeaker');
    const displayName = isPlayer ? `You${/v\.?o/i.test(speaker) ? ' (V.O.)' : ''}` : speaker;
    name.textContent = displayName;
    name.classList.toggle('is-player', isPlayer);
    const lineEl = $('#subLine');
    lineEl.classList.toggle('is-vo', vo);
    const chipsEl = $('#subCites');
    chipsEl.replaceChildren();
    const hint = $('#subHint');
    hint.classList.remove('is-ready');
    // stage directions in parentheses render as quiet italics
    const parts = String(line).split(/(\([^)]*\))/g).filter(Boolean);
    lineEl.replaceChildren();
    const spans = parts.map((p) => {
      const s = el('span', { class: /^\(/.test(p) ? 'dir' : '' });
      s.dataset.full = p;
      lineEl.append(s);
      return s;
    });
    lineEl.setAttribute('aria-label', `${displayName}: ${line}`);
    const total = parts.reduce((a, p) => a + p.length, 0);
    let finished = false;
    await new Promise((resolve) => {
      const finish = () => {
        if (finished) return;
        finished = true;
        spans.forEach((s) => { s.textContent = s.dataset.full; });
        this.typing = null;
        resolve();
      };
      this.typing = { finish };
      if (this.reduced) { finish(); return; }
      const cps = 52;
      const start = performance.now();
      let lastTick = 0;
      const tick = (now) => {
        if (finished) return;
        const n = Math.floor(((now - start) / 1000) * cps);
        let left = n;
        for (const s of spans) {
          const f = s.dataset.full;
          s.textContent = f.slice(0, Math.max(0, Math.min(f.length, left)));
          left -= f.length;
        }
        if (n - lastTick >= 6) { lastTick = n; this.audio?.sting('tick'); }
        if (n >= total) finish(); else requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
    const c = this.chips(cites);
    if (c) chipsEl.append(c);
    hint.classList.add('is-ready');
    const words = String(line).split(/\s+/).length;
    const why = await this.wait(autoMs ? Math.max(autoMs, words * 330 + 1200) : 0);
    return why;
  }

  hideSubtitle() { $('#subtitle').hidden = true; if (this.typing) this.typing.finish(); }

  /** A "Continue" prompt in the subtitle area. */
  async prompt(label = 'Continue') {
    const box = $('#subtitle');
    box.hidden = false;
    $('#subSpeaker').textContent = '';
    $('#subLine').replaceChildren(el('span', { class: 'prompt', text: label }));
    $('#subCites').replaceChildren();
    $('#subHint').classList.add('is-ready');
    return this.wait();
  }

  // ---------- case file ----------

  resetCaseFile(game) {
    this.factCount = 0;
    $('#cfFacts').replaceChildren();
    $('#cfCaseTitle').textContent = game.title;
    $('#cfCourse').textContent = `${game.course} · ${game.id}`;
    const goal = $('#cfGoal');
    goal.replaceChildren(el('p', {}, this.rich(game.learning_goal || '')));
    if (game.logline) goal.prepend(el('p', { class: 'cf-logline', text: game.logline }));
    const src = $('#cfSources');
    src.replaceChildren(...Object.entries(game.sources).map(([k, v]) => el('li', {},
      el('span', { class: 'cf-key', text: k }),
      el('span', { class: 'cf-file', text: v.file }),
      v.kind ? el('span', { class: 'cf-kind', text: v.kind }) : null,
      v.note ? el('span', { class: 'cf-note', text: v.note }) : null)));
    $('#cfBadge').textContent = '0';
    this.caseTab('facts');
  }

  addFact(text, { group = '', cites = [], quiet = false } = {}) {
    const list = $('#cfFacts');
    if ([...list.querySelectorAll('.cf-fact-text')].some((n) => n.dataset.raw === text)) return;
    if (group && list.dataset.group !== group) {
      list.dataset.group = group;
      list.append(el('li', { class: 'cf-group', text: group }));
    }
    const t = el('span', { class: 'cf-fact-text' }, this.rich(text));
    t.dataset.raw = text;
    list.append(el('li', { class: 'cf-fact' }, t, this.chips(cites)));
    this.factCount++;
    const badge = $('#cfBadge');
    badge.textContent = String(this.factCount);
    if (!quiet) {
      const btn = $('#casefileBtn');
      btn.classList.remove('is-ping');
      void btn.offsetWidth;
      btn.classList.add('is-ping');
      this.audio?.sting('file');
    }
  }

  caseTab(name) {
    for (const t of document.querySelectorAll('.cf-tab')) {
      const on = t.dataset.tab === name;
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
    }
    for (const p of document.querySelectorAll('.cf-panel')) p.hidden = p.dataset.panel !== name;
  }

  toggleCaseFile(force) {
    const cf = $('#casefile');
    const open = force ?? cf.hidden;
    cf.hidden = !open;
    $('#casefileBtn').setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) {
      this.lastFocus = document.activeElement;
      $('#casefileClose').focus();
      this.onCaseFile?.(true);
    } else {
      this.onCaseFile?.(false);
      if (this.lastFocus && document.contains(this.lastFocus)) this.lastFocus.focus();
    }
  }

  // ---------- misc ----------

  toast(msg, ms = 3200) {
    const t = $('#toast');
    t.textContent = msg;
    t.classList.add('is-on');
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => t.classList.remove('is-on'), ms);
  }

  loading(on, label = 'Loading set') {
    const l = $('#loading');
    clearTimeout(this.loadTimer);
    if (on) this.loadTimer = setTimeout(() => { l.hidden = false; $('#loadingLabel').textContent = label; }, 250);
    else l.hidden = true;
  }

  showMedia(media) {
    const m = $('#media');
    m.replaceChildren();
    if (!media) { m.hidden = true; return; }
    const node = media.type === 'video'
      ? el('video', { src: media.url, autoplay: true, muted: true, loop: true, playsinline: true, 'aria-hidden': 'true' })
      : el('img', { src: media.url, alt: '', class: this.reduced ? '' : 'kenburns' });
    if (node.tagName === 'VIDEO') { node.muted = true; node.play?.().catch(() => {}); }
    m.append(node);
    m.hidden = false;
  }

  arrivalHud(on, { destination = '' } = {}) {
    const a = $('#arrivalHud');
    a.hidden = !on;
    if (on) $('#arrivalDest').textContent = destination ? `Objective: enter the ${destination.toLowerCase()}` : 'Objective: reach the lit entrance';
  }

  arrivalProgress(p) { $('#arrivalBar').style.setProperty('--p', p.toFixed(3)); }
}
