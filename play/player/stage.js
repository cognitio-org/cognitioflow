// stage.js: the 3D stage (renderer, sets, cast, director, post, arrival controls) and a 2D fallback with the same API.
import * as THREE from 'three';
import { makeEnvMap, RIM } from './lib3d.js';
import { loadSet, castSet } from './sets.js';
import { Director, planShot } from './camera.js';
import { Post } from './post.js';
import { Human, profileFor } from './human.js';

export function webglAvailable() {
  try {
    const c = document.createElement('canvas');
    return !!(window.WebGL2RenderingContext && c.getContext('webgl2'));
  } catch { return false; }
}

const AMBIENT_FOR = { street: 'rain', customs_yard: 'yard', classroom: 'fluorescent', office: 'room', courtroom: 'room', parliament: 'room', generic: 'room' };

export class Stage3D {
  constructor(container, { quality = 'high', autoQuality = true, reduced = false, audio = null, onQualityDrop = null, onLoading = null } = {}) {
    this.kind3d = true;
    this.container = container;
    this.audio = audio;
    this.onQualityDrop = onQualityDrop;
    this.onLoading = onLoading || (() => {});
    this.reduced = reduced;
    this.autoQuality = autoQuality;
    const renderer = this.renderer = new THREE.WebGLRenderer({ antialias: false, powerPreference: 'high-performance', stencil: false });
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.domElement.className = 'stage-canvas';
    renderer.domElement.setAttribute('aria-hidden', 'true');
    container.appendChild(renderer.domElement);
    this.scene = new THREE.Scene();
    this.scene.environment = makeEnvMap(renderer);
    this.scene.environmentIntensity = 0.6;
    this.camera = new THREE.PerspectiveCamera(40, 16 / 9, 0.05, 400);
    this.camera.position.set(0, 1.6, 6);
    this.director = new Director(this.camera);
    this.director.reduced = reduced;
    this.post = new Post(renderer, this.scene, this.camera);
    this.post.setReduced(reduced);
    this.set = null;
    this.cast = new Map();
    this.mood = null;
    this.moodT = 0;
    this.clock = new THREE.Clock();
    this.time = 0;
    this.paused = false;
    this.visH = null;
    this.fpsLow = 0;
    this.frames = 0;
    this.fpsAcc = 0;
    this.keys = new Set();
    this.arrival = null;
    this.setQuality(quality);
    this.resize();
    this.loop = this.loop.bind(this);
    renderer.setAnimationLoop(this.loop);
    this._onKey = (e) => this.onKey(e);
    window.addEventListener('keydown', this._onKey);
    window.addEventListener('keyup', this._onKey);
    renderer.domElement.addEventListener('pointerdown', (e) => this.onPointer(e));
  }

  setQuality(q) {
    this.quality = q;
    this.renderer.shadowMap.enabled = q !== 'low';
    this.post.setQuality(q);
    this.resize();
  }

  setReduced(r) { this.reduced = r; this.director.reduced = r; this.post.setReduced(r); }

  setVisibleHeight(px) { this.visH = px; this.resize(); }

  resize() {
    const w = this.container.clientWidth || window.innerWidth;
    const h = this.container.clientHeight || window.innerHeight;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const pr = this.quality === 'low' ? Math.min(dpr, 1) * 0.7 : Math.min(dpr, 1.5);
    this.renderer.setPixelRatio(pr);
    this.renderer.setSize(w, h, false);
    this.post.setSize(w, h, pr);
    this.director.setViewport(w, h, this.visH || h);
    this.director.applyFov(this.director.cur.hfov || 40);
  }

  pause(p) { this.paused = p; this.renderer.domElement.style.visibility = p ? 'hidden' : ''; }

  disposeSet() {
    if (!this.set) return;
    this.scene.remove(this.set.group);
    this.set.dispose();
    this.set = null;
    this.cast = new Map();
  }

  /** Load a set lazily (glTF if exported, else procedural) and cast it. */
  async loadScene({ kind, cast = [], destKind = null }) {
    this.onLoading(true);
    try {
      const set = await loadSet(kind, { quality: this.quality, reduced: this.reduced, destKind });
      this.disposeSet();
      this.set = set;
      this.scene.add(set.group);
      this.scene.background = set.bg;
      this.scene.fog = new THREE.FogExp2(set.fog.color, set.fog.density);
      this.cast = await castSet(set, cast);
      const lights = [set.lights.key, set.lights.fill, set.lights.hemi, set.lights.sun, ...set.lights.practicals, ...set.lights.sodium].filter(Boolean);
      for (const l of lights) if (l.userData.base == null) l.userData.base = l.intensity;
      this.mood = null;
      this.post.target.exposure = set.exposure;
      this.post.target.sepia = 0;
      this.post.target.desat = 0;
      this.audio?.setAmbient(AMBIENT_FOR[kind] || 'room');
      // compile shaders now to avoid a hitch on the first shot
      this.renderer.compile(this.scene, this.camera);
      return set;
    } finally {
      this.onLoading(false);
    }
  }

  playShot(shot, index = 0, { cut = false } = {}) {
    if (!this.set) return null;
    const plan = planShot(shot, this.set, this.cast, { reduced: this.reduced, index });
    this.director.play(plan, { cut: cut || this.reduced });
    this.mood = plan.mood;
    this.moodT = 0;
    this.post.target.sepia = plan.sepia ? 0.85 : 0;
    this.post.target.fade = plan.black ? 1 : 0;
    this.post.target.exposure = this.set.exposure * plan.mood.exposure;
    if (this.set.breath) this.set.breath.visible = /close/i.test(shot.size) && /breath/i.test(shot.subject);
    return plan;
  }

  /** A slow establishing move when a scene has no shots. */
  playEstablishing(index = 0) {
    return this.playShot({ size: 'Wide', angle: 'Eye level', movement: 'Slow push-in', lens: '28 mm', lighting: '', subject: '', duration_s: 12 }, index);
  }

  freeze(on) {
    if (on) this.director.freeze(); else this.director.unfreeze();
    for (const ch of this.cast.values()) ch.frozen = on;
    this.post.target.desat = on ? 0.2 : 0;
  }

  setSpeaker(key) {
    for (const [k, ch] of this.cast) ch.talking = k === key;
  }

  epilogueBeat() {
    if (this.set?.barrier) this.set.barrier.rotation.z = 1.35;
  }

  // ---------- arrival ----------

  /** Third-person walk to the door. Resolves when the door is reached or `skip()` is called. */
  startArrival() {
    const set = this.set;
    let lawyer = this.cast.get('trainee');
    if (!lawyer) {
      lawyer = new Human({ ...profileFor('trainee'), briefcase: true });
      set.group.add(lawyer.root);
      this.cast.set('trainee', lawyer);
    }
    const sp = set.spawn || { pos: new THREE.Vector3(0, 0, 8), rotY: Math.PI };
    lawyer.root.position.copy(sp.pos);
    lawyer.root.rotation.y = sp.rotY;
    lawyer.setPose('stand');
    if (lawyer.briefcase && lawyer.briefcase.parent !== lawyer.arms?.[1]?.hand && lawyer.arms) {
      const bc = lawyer.briefcase; bc.parent.remove(bc);
      bc.position.set(0, 0, 0); bc.rotation.set(0, Math.PI / 2, 0);
      lawyer.arms[1].hand.add(bc);
    }
    this.director.startFollow(lawyer);
    this.post.target.fade = 0;
    return new Promise((resolve) => {
      this.arrival = { lawyer, heading: sp.rotY, target: null, auto: false, resolve, stepAcc: 0 };
    });
  }

  skipArrival() { this.finishArrival(true); }

  finishArrival(skipped = false) {
    const a = this.arrival;
    if (!a) return;
    this.arrival = null;
    a.lawyer.speed = 0;
    this.director.mode = 'idle';
    a.resolve({ skipped });
  }

  autoWalk() { if (this.arrival && this.set?.door) { this.arrival.target = this.set.door.clone(); this.arrival.auto = true; } }

  arrivalProgress() {
    if (!this.arrival || !this.set?.door || !this.set.spawn) return 0;
    const d0 = this.set.spawn.pos.distanceTo(this.set.door);
    return 1 - Math.min(1, this.arrival.lawyer.root.position.distanceTo(this.set.door) / Math.max(d0, 0.01));
  }

  onKey(e) {
    const k = e.key.toLowerCase();
    const map = { w: 'f', arrowup: 'f', s: 'b', arrowdown: 'b', a: 'l', arrowleft: 'l', d: 'r', arrowright: 'r', shift: 'run' };
    const m = map[k];
    if (!m) return;
    if (!this.arrival) { if (e.type === 'keyup') this.keys.delete(m); return; }
    if (e.target && /input|textarea|select/i.test(e.target.tagName)) return;
    if (e.type === 'keydown') { this.keys.add(m); if (m !== 'run') this.arrival.target = null; if (k.startsWith('arrow')) e.preventDefault(); }
    else this.keys.delete(m);
  }

  onPointer(e) {
    if (!this.arrival) return;
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, this.camera);
    const hit = new THREE.Vector3();
    if (ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), hit)) {
      // taps far up the street or on the building walk to the door
      if (this.set.door && (hit.distanceTo(this.set.door) < 6 || ray.ray.direction.y > -0.05)) hit.copy(this.set.door);
      this.arrival.target = hit;
    }
  }

  updateArrival(dt) {
    const a = this.arrival;
    const set = this.set;
    const L = a.lawyer;
    const run = this.keys.has('run');
    let fwd = 0, turn = 0;
    if (this.keys.has('f')) fwd += 1;
    if (this.keys.has('b')) fwd -= 0.6;
    if (this.keys.has('l')) turn += 1;
    if (this.keys.has('r')) turn -= 1;
    if (a.target && !fwd && !turn) {
      const to = a.target.clone().sub(L.root.position); to.y = 0;
      if (to.length() < 0.25) a.target = null;
      else {
        const want = Math.atan2(to.x, to.z);
        let diff = want - a.heading;
        diff = Math.atan2(Math.sin(diff), Math.cos(diff));
        a.heading += diff * Math.min(1, dt * 6);
        fwd = Math.abs(diff) < 1.2 ? 1 : 0.2;
      }
    }
    a.heading += turn * dt * 2.2;
    const speedWant = fwd * (run ? 3.4 : 1.7);
    L.speed += (speedWant - L.speed) * Math.min(1, dt * 6);
    L.root.rotation.y = a.heading;
    const dir = new THREE.Vector3(Math.sin(a.heading), 0, Math.cos(a.heading));
    const p = L.root.position;
    p.addScaledVector(dir, L.speed * dt);
    const b = set.walkBounds;
    if (b) { p.x = Math.min(b.x1, Math.max(b.x0, p.x)); p.z = Math.min(b.z1, Math.max(b.z0, p.z)); }
    for (const c of set.colliders || []) {
      const dx = p.x - c.x, dz = p.z - c.z;
      if (Math.abs(dx) < c.hw && Math.abs(dz) < c.hd) {
        if (c.hw - Math.abs(dx) < c.hd - Math.abs(dz)) p.x = c.x + Math.sign(dx || 1) * c.hw;
        else p.z = c.z + Math.sign(dz || 1) * c.hd;
      }
    }
    if (set.kind === 'street' && !set.glb) p.y = Math.abs(p.x) > 5.1 && p.z > -23 ? 0.15 : 0;
    if (Math.abs(L.speed) > 0.3) {
      a.stepAcc += dt * Math.abs(L.speed) * 1.3;
      if (a.stepAcc > 1) { a.stepAcc = 0; this.audio?.sting('step'); }
    }
    if (set.door) {
      const d = Math.hypot(p.x - set.door.x, p.z - set.door.z);
      if (d < 1.7) this.finishArrival(false);
    }
  }

  // ---------- library backdrop ----------

  async showBackdrop(destKind = 'courtroom') {
    await this.loadScene({ kind: 'street', cast: [], destKind });
    this.director.mode = 'shots';
    this.backdrop = true;
    this.director.play({
      from: { pos: new THREE.Vector3(-2.5, 2.2, 14), target: new THREE.Vector3(0.5, 2.6, -20) },
      to: { pos: new THREE.Vector3(1.5, 1.7, 2), target: new THREE.Vector3(0, 2.4, -30) },
      hfov: 58, hfovEnd: 56, duration: 60, hold: 0, handheld: 0.05, mood: { key: 1, fill: 1, prac: 1, hemi: 1, fog: 1, exposure: 1, rim: [0.62, 0.72, 0.78], rimS: 0.35 },
    }, { cut: true });
    this.post.target.fade = 0;
  }

  // ---------- frame ----------

  applyMood(dt) {
    const set = this.set;
    const m = this.mood || { key: 1, fill: 1, prac: 1, hemi: 1, fog: 1, rim: [0.62, 0.72, 0.78], rimS: 0.35 };
    this.moodT += dt;
    const k = 1 - Math.exp(-dt * 2.5);
    const lerpI = (l, mul) => { if (l) l.intensity += (l.userData.base * mul - l.intensity) * k; };
    let sunMul = m.key;
    if (m.sunRamp) sunMul *= 1 + (m.sunRamp[1] - 1) * Math.min(1, this.moodT / 3);
    lerpI(set.lights.key, set.lights.key === set.lights.sun ? sunMul : m.key);
    if (set.lights.sun && set.lights.sun !== set.lights.key) lerpI(set.lights.sun, sunMul);
    lerpI(set.lights.fill, m.fill);
    lerpI(set.lights.hemi, m.hemi);
    for (const l of set.lights.practicals) if (l !== set.lights.key) lerpI(l, m.prac);
    const plan = this.director.plan;
    const fade = m.sodiumFade && plan ? Math.max(0, 1 - this.director.elapsed / plan.duration) : 1;
    for (const l of set.lights.sodium) l.intensity = l.userData.base * (m.sodiumFade ? fade : 1) * (this.mood ? 1 : 1);
    if (this.scene.fog) this.scene.fog.density += (set.fog.density * m.fog - this.scene.fog.density) * k;
    RIM.color.value.r += (m.rim[0] - RIM.color.value.r) * k;
    RIM.color.value.g += (m.rim[1] - RIM.color.value.g) * k;
    RIM.color.value.b += (m.rim[2] - RIM.color.value.b) * k;
    RIM.strength.value += (m.rimS - RIM.strength.value) * k;
  }

  loop() {
    const dt = Math.min(0.1, this.clock.getDelta());
    if (this.paused) return;
    this.time += dt;
    const t = this.time;
    if (this.set) {
      if (this.arrival) this.updateArrival(dt);
      const frozen = this.director.frozen;
      if (!frozen) this.set.update(t, dt, this.camera);
      for (const ch of this.cast.values()) ch.update(dt, t);
      this.applyMood(dt);
    }
    this.director.update(dt, t);
    this.post.render(dt, t);
    this.monitorFps(dt);
  }

  monitorFps(dt) {
    if (!this.autoQuality || this.quality === 'low') return;
    this.frames++;
    this.fpsAcc += dt;
    if (this.fpsAcc >= 0.5) {
      const fps = this.frames / this.fpsAcc;
      this.frames = 0; this.fpsAcc = 0;
      if (fps < 40 && !document.hidden) this.fpsLow += 0.5; else this.fpsLow = 0;
      if (this.fpsLow >= 3) {
        this.fpsLow = 0;
        this.setQuality('low');
        this.onQualityDrop?.();
      }
    }
  }
}

// ---------- 2D fallback ----------

const BG2D = {
  street: 'radial-gradient(ellipse at 50% 70%, #6a4a26 0%, #2a2118 40%, #0d0c0b 80%)',
  customs_yard: 'linear-gradient(180deg, #56636b 0%, #7d8a8f 45%, #3a3c3c 46%, #1f2123 100%)',
  office: 'radial-gradient(ellipse at 35% 55%, #8a5a2a 0%, #2a1c12 35%, #060606 75%)',
  courtroom: 'linear-gradient(180deg, #3b3226 0%, #6b5436 50%, #2a2016 51%, #120e0a 100%)',
  classroom: 'linear-gradient(180deg, #34383a 0%, #4d524f 55%, #222 56%, #111 100%)',
  parliament: 'radial-gradient(ellipse at 50% 30%, #3a3f5a 0%, #15161f 60%, #07070a 100%)',
  generic: 'radial-gradient(ellipse at 50% 60%, #3a2f22 0%, #121110 55%, #050505 100%)',
};

/** Same interface as Stage3D, drawn with CSS so the story and quiz flow still work without WebGL. */
export class Stage2D {
  constructor(container, { reduced = false, audio = null } = {}) {
    this.kind3d = false;
    this.container = container;
    this.audio = audio;
    this.reduced = reduced;
    this.el = document.createElement('div');
    this.el.className = 'stage2d';
    this.el.setAttribute('aria-hidden', 'true');
    this.el.innerHTML = '<div class="s2-bg"></div><div class="s2-cast"></div><div class="s2-grain"></div>';
    container.appendChild(this.el);
    this.bg = this.el.querySelector('.s2-bg');
    this.castEl = this.el.querySelector('.s2-cast');
    this.cast = new Map();
    this.arrival = null;
  }
  setQuality() {}
  setReduced(r) { this.reduced = r; }
  setVisibleHeight() {}
  resize() {}
  pause(p) { this.el.style.visibility = p ? 'hidden' : ''; }
  async loadScene({ kind, cast = [] }) {
    this.bg.style.background = BG2D[kind] || BG2D.generic;
    this.castEl.innerHTML = '';
    this.cast = new Map();
    cast.forEach((c, i) => {
      const d = document.createElement('div');
      d.className = `s2-figure${c.key === 'trainee' ? ' is-player' : ''}`;
      d.style.left = `${18 + (i * 64) / Math.max(1, cast.length - 1 || 1)}%`;
      d.dataset.key = c.key;
      this.castEl.appendChild(d);
      this.cast.set(c.key, d);
    });
    this.audio?.setAmbient(kind === 'street' ? 'rain' : kind === 'customs_yard' ? 'yard' : 'room');
  }
  playShot(shot, index = 0) {
    const s = String(shot.size).toLowerCase();
    const scale = /close|insert/.test(s) ? 1.25 : /medium/.test(s) ? 1.1 : 1;
    this.el.classList.toggle('is-black', /^\s*black\s*$/i.test(shot.size));
    this.el.classList.toggle('is-sepia', /sepia|flashback/i.test(`${shot.size} ${shot.movement}`));
    this.bg.style.transform = `scale(${scale}) translateX(${(index % 2 ? -1 : 1) * 2}%)`;
    const titleM = String(shot.subject).match(/title card[^"“]*["“]([^"”]+)["”]/i);
    const capM = String(shot.subject).match(/caption:\s*["“]([^"”]+)["”]/i);
    return { duration: Math.max(1, shot.duration_s || 4), titleCard: titleM ? titleM[1] : null, caption: capM ? capM[1] : null, freeze: /freeze/i.test(shot.movement) };
  }
  playEstablishing() { return this.playShot({ size: 'Wide', movement: '', subject: '', duration_s: 12 }); }
  freeze(on) { this.el.classList.toggle('is-frozen', on); }
  setSpeaker(key) { for (const [k, d] of this.cast) d.classList.toggle('is-talking', k === key); }
  epilogueBeat() {}
  startArrival() { return new Promise((resolve) => { this.arrival = { resolve }; }); }
  autoWalk() { this.finishArrival(false); }
  skipArrival() { this.finishArrival(true); }
  finishArrival(skipped) { const a = this.arrival; this.arrival = null; a?.resolve({ skipped }); }
  arrivalProgress() { return 0; }
  async showBackdrop() { await this.loadScene({ kind: 'street', cast: [] }); }
  get director() { return { elapsed: 0, done: true }; }
}
