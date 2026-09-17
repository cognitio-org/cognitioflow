// camera.js: turns screenplay shots into camera keyframes, plays them with easing, handheld noise and the quiz push-in.
import * as THREE from 'three';

const V = (x = 0, y = 0, z = 0) => new THREE.Vector3(x, y, z);
const UP = V(0, 1, 0);
const DEG = Math.PI / 180;
const REF_ASPECT = 2.39;

export const ease = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x));
const easeInOut = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);

/** Lens text -> horizontal FOV in degrees (36 mm-wide sensor). */
export function lensToHFov(lens, size = '') {
  const m = String(lens).match(/(\d+(?:\.\d+)?)\s*mm/i);
  let mm = m ? parseFloat(m[1]) : NaN;
  if (!Number.isFinite(mm)) {
    const s = size.toLowerCase();
    mm = /extreme wide/.test(s) ? 21 : /wide/.test(s) ? 28 : /close|insert/.test(s) ? 85 : 40;
  }
  if (/macro/i.test(lens)) mm = Math.max(mm, 90);
  return 2 * Math.atan(18 / mm) / DEG;
}

function vfovFromH(hfovDeg, aspect) {
  return 2 * Math.atan(Math.tan((hfovDeg * DEG) / 2) / aspect) / DEG;
}

/** Vertical extent (m) framed by a shot size. */
function sizeExtent(size) {
  const s = size.toLowerCase();
  if (/black/.test(s)) return 2;
  if (/extreme close|ecu|macro/.test(s)) return 0.2;
  if (/insert/.test(s)) return 0.42;
  if (/medium close|mcu/.test(s)) return 0.8;
  if (/close/.test(s)) return 0.48;
  if (/extreme wide|establishing|ews/.test(s)) return 13;
  if (/medium[- ]wide|two-shot|two shot|cowboy/.test(s)) return 2.6;
  if (/wide|long|full/.test(s)) return 5.5;
  if (/medium/.test(s)) return 1.3;
  return 1.8;
}

function focusFor(size) {
  const s = size.toLowerCase();
  if (/close|mcu|ecu/.test(s) && !/insert/.test(s)) return /medium close/.test(s) ? 'chest' : 'head';
  if (/medium|two|over/.test(s) && !/wide/.test(s)) return 'chest';
  return 'body';
}

function numberBefore(str, unitRe) {
  const m = str.match(new RegExp(`(\\d+(?:\\.\\d+)?)\\s*(${unitRe})`, 'i'));
  if (!m) return null;
  const v = parseFloat(m[1]);
  return /^cm$/i.test(m[2]) ? v / 100 : v;
}

function charPoint(ch, focus) {
  if (focus === 'head') return ch.headPos(V()).add(V(0, -0.04, 0));
  if (focus === 'chest') return ch.chestPos(V()).add(V(0, 0.1, 0));
  const p = ch.root.getWorldPosition(V());
  return p.add(V(0, 1.0 * (ch.k || 1), 0));
}

/** Find what a shot is about: characters and set anchors mentioned in its subject, in order. */
export function resolveSubjects(shot, set, cast) {
  const text = `${shot.subject}`;
  const hits = [];
  for (const [key, ch] of cast) {
    const words = new Set([key]);
    for (const w of String(ch.speaker || '').toLowerCase().replace(/\(.*?\)/g, '').split(/[^a-zà-ÿ]+/)) if (w.length > 2 && !['the', 'officer', 'judge', 'mr', 'mrs', 'ms'].includes(w)) words.add(w);
    if (key === 'trainee') { words.add('trainee'); words.add('lawyer'); words.add('you'); }
    if (key === 'judge') words.add('judge');
    let best = -1;
    for (const w of words) {
      const m = text.toLowerCase().search(new RegExp(`\\b${w.replace(/[.*+?^${}()|[\]\\]/g, '')}\\b`));
      if (m >= 0 && (best < 0 || m < best)) best = m;
    }
    if (best >= 0) hits.push({ idx: best, ch, key });
  }
  const tabletHit = text.search(/tablet|duty notice|€|notice fills/i);
  if (tabletHit >= 0) {
    for (const [, ch] of cast) if (ch.tablet) { hits.push({ idx: tabletHit - 0.5, prop: 'tablet', ch }); break; }
  }
  for (const [re, name] of set.keywords) {
    const m = text.search(re);
    if (m >= 0 && set.anchors[name]) hits.push({ idx: m, anchor: set.anchors[name], name });
  }
  hits.sort((a, b) => a.idx - b.idx);
  return hits;
}

function lateral(dir) { return V().crossVectors(dir, UP).normalize(); }

/** Build keyframes for one shot. */
export function planShot(shot, set, cast, { reduced = false, index = 0 } = {}) {
  const size = shot.size || '';
  const angle = (shot.angle || '').toLowerCase();
  const move = (shot.movement || '').toLowerCase();
  const subj = shot.subject || '';
  const hfov = lensToHFov(shot.lens, size);
  const vref = vfovFromH(hfov, REF_ASPECT);
  const hits = resolveSubjects(shot, set, cast);
  const focus = focusFor(size);
  let extent = sizeExtent(size);

  // subject point, facing and the "other" character
  let target, facing;
  const chars = hits.filter((h) => h.ch && !h.prop);
  const primary = hits[0];
  const insertLike = /insert|extreme close/.test(size.toLowerCase());
  if (primary?.prop === 'tablet') {
    const tab = primary.ch.tablet;
    target = tab.getWorldPosition(V());
    facing = V(0, 0, 1).applyQuaternion(tab.getWorldQuaternion(new THREE.Quaternion())).normalize();
    extent = Math.min(extent, 0.35);
  } else if (primary?.anchor && (insertLike || !chars.length || primary.idx < (chars[0]?.idx ?? 1e9))) {
    target = primary.anchor.pos.clone();
    facing = primary.anchor.facing.clone();
    if (!/wide/.test(size.toLowerCase())) extent = Math.min(extent, Math.max(primary.anchor.h, 0.3));
    else extent = Math.max(extent, primary.anchor.h);
  } else if (chars.length >= 2 && /two|profile|left.*right|both/i.test(`${size} ${angle} ${subj}`)) {
    const a = charPoint(chars[0].ch, 'chest'), b = charPoint(chars[1].ch, 'chest');
    target = a.clone().lerp(b, 0.5);
    const across = b.clone().sub(a); across.y = 0;
    facing = V().crossVectors(UP, across).normalize();
    // face the side the two characters are looking toward on average
    const avg = chars[0].ch.worldFacing(V()).add(chars[1].ch.worldFacing(V()));
    if (avg.dot(facing) < 0) facing.negate();
    extent = Math.max(extent, a.distanceTo(b) * 0.9 / REF_ASPECT * 1.9);
  } else if (chars.length) {
    target = charPoint(chars[0].ch, focus);
    facing = chars[0].ch.worldFacing(V());
  } else {
    const a = set.anchors.room || set.anchors.stage || set.anchors.office || set.anchors.yard;
    target = a ? a.pos.clone() : set.center.clone();
    facing = a ? a.facing.clone() : V(0, 0, 1);
  }
  facing.y = Math.max(-0.2, Math.min(facing.y, 1));
  if (facing.lengthSq() < 1e-4) facing.set(0, 0, 1);
  facing.normalize();

  let dist = extent / (2 * Math.tan((vref * DEG) / 2));
  if (set.interior) dist = Math.min(dist, 10);
  dist = Math.max(dist, 0.25);

  // azimuth
  const flat = V(facing.x, 0, facing.z);
  if (flat.lengthSq() < 1e-4) flat.set(0, 0, 1);
  flat.normalize();
  let dir = flat.clone();
  const side = index % 2 ? 1 : -1;
  if (/profile|90°/.test(angle)) dir.applyAxisAngle(UP, (Math.PI / 2) * side);
  else if (!/centred|centered|symmetr/.test(`${angle} ${size.toLowerCase()}`)) dir.applyAxisAngle(UP, 0.32 * side);

  let pos;
  let fixedPos = false;
  const topDown = /top-down|top down|overhead|bird/.test(angle) || facing.y > 0.9;
  if (topDown) {
    const tilt = (numberBefore(angle, '°') || 4) * DEG;
    pos = target.clone().add(V(0, dist * Math.cos(tilt), 0)).add(flat.clone().multiplyScalar(dist * Math.sin(tilt) + 0.02));
  } else {
    pos = target.clone().add(dir.clone().multiplyScalar(dist));
    // height and pitch
    const deg = (angle.match(/(\d+(?:\.\d+)?)\s*°\s*(down|up)/) || [])[1];
    const heightM = /(crane )?height|eye level \(|^\s*(low|high),?\s*\d/.test(angle) ? numberBefore(angle.replace(/\d+\s*m back/, ''), 'm\\b') : null;
    if (/eye level/.test(angle)) pos.y = target.y;
    let pitch = 0;
    if (deg) pitch = parseFloat(deg) * DEG * (/up/.test(angle) ? -1 : 1);
    else if (/slightly high/.test(angle)) pitch = 12 * DEG;
    else if (/high/.test(angle)) pitch = 26 * DEG;
    else if (/slightly low/.test(angle)) pitch = -6 * DEG;
    else if (/low/.test(angle)) pitch = -12 * DEG;
    if (pitch) pos.y = target.y + Math.tan(pitch) * dist;
    if (heightM != null && !/eye level/.test(angle)) {
      const groundY = set.center.y - 1.2;
      pos.y = Math.max(groundY + heightM, pos.y > target.y ? pos.y : groundY + heightM);
      if (/crane|high/.test(angle)) pos.y = groundY + Math.max(heightM, 0.5) + (target.y - (set.center.y)) * 0.2;
    }
  }

  // special vantage points
  const otsName = angle.match(/behind (?:the )?([a-z]+)/);
  if (/over-the-shoulder|over the shoulder|\bots\b|behind/.test(angle) && !topDown) {
    let other = null;
    if (otsName) for (const [key, ch] of cast) {
      if (key.includes(otsName[1]) || String(ch.speaker).toLowerCase().includes(otsName[1]) || (otsName[1] === 'trainee' && key === 'trainee')) other = ch;
    }
    if (/behind the bench/.test(angle) && set.anchors.behindBench) {
      pos = set.anchors.behindBench.pos.clone();
      target = (set.anchors.tables || set.anchors.room).pos.clone();
      fixedPos = true;
    } else if (/booth glass/.test(angle) && set.anchors.booth) {
      pos = set.anchors.booth.pos.clone().add(V(1.3, 0, 0.9));
      fixedPos = true;
    } else {
      if (!other) {
        const primaryCh = chars[0]?.ch;
        let best = Infinity;
        for (const [, ch] of cast) {
          if (ch === primaryCh) continue;
          const d = ch.root.position.distanceTo(primaryCh ? primaryCh.root.position : target);
          if (d < best) { best = d; other = ch; }
        }
      }
      if (other && other !== chars[0]?.ch) {
        const sh = other.headPos(V());
        const toSub = target.clone().sub(sh); toSub.y = 0; toSub.normalize();
        const lat = lateral(toSub);
        pos = sh.clone().addScaledVector(toSub, -0.75).addScaledVector(lat, 0.38 * side).add(V(0, 0.08, 0));
        if (!chars.length || chars[0].ch === other) target = sh.clone().addScaledVector(toSub, 3);
        fixedPos = true;
      }
    }
  }
  if (/from the back wall/.test(angle) && set.anchors.backwall) { pos = set.anchors.backwall.pos.clone(); fixedPos = true; }
  if (/warehouse floor/.test(angle) && set.fromBelow) { pos = set.fromBelow.clone(); fixedPos = true; }
  if (/wide reverse|reverse/.test(`${size} ${angle}`.toLowerCase()) && set.anchors.behindBench && !fixedPos) { pos = set.anchors.behindBench.pos.clone(); target = set.anchors.room.pos.clone(); fixedPos = true; }
  // Blender camera anchors override when the shot mentions them
  if (primary?.anchor?.camera) {
    pos = primary.anchor.pos.clone();
    target = pos.clone().add(primary.anchor.facing.clone().multiplyScalar(5));
    fixedPos = true;
  }
  const floorY = set.center.y - 1.3;
  if (pos.y < floorY + 0.25) pos.y = floorY + 0.25;

  const from = { pos, target: target.clone() };
  const to = { pos: pos.clone(), target: target.clone() };
  const view = target.clone().sub(pos);
  const vd = view.length();
  const vdir = view.clone().normalize();
  const lat = lateral(V(vdir.x, 0, vdir.z).normalize());
  const amount = numberBefore(move, 'cm|m\\b');
  let hold = 0;
  const holdM = move.match(/(\d+(?:\.\d+)?)\s*s hold/);
  if (holdM) hold = parseFloat(holdM[1]);

  if (/crane/.test(move)) {
    const endH = move.match(/to\s+(\d+(?:\.\d+)?)\s*m/);
    const endY = endH ? floorY + 1.3 + parseFloat(endH[1]) - 1.3 : pos.y - 3;
    if (/descent|down|lower/.test(move)) { to.pos.y = Math.min(endY, pos.y); } else { to.pos.y = Math.max(endY, pos.y + 2); }
    to.pos.addScaledVector(vdir, vd * 0.15);
  } else if (/push|dolly in|move in|creep|in\b/.test(move) && !/pull|out/.test(move)) {
    const a = amount != null ? Math.min(amount, vd * 0.5) : vd * 0.08;
    to.pos.addScaledVector(vdir, Math.max(a, 0.03));
  } else if (/pull|dolly out|move out|back/.test(move)) {
    const a = amount != null ? amount : vd * 0.1;
    to.pos.addScaledVector(vdir, -a);
  }
  if (/track|truck|lateral|slide|crab/.test(move)) {
    const a = (amount != null ? amount : 0.6) * (/left/.test(move) ? -1 : 1);
    to.pos.addScaledVector(lat, a);
    to.target.addScaledVector(lat, a * (/follow/.test(move) ? 1 : 0.7));
  }
  if (/arc|orbit/.test(move)) {
    const a = (/left/.test(move) ? -1 : 1) * (amount != null ? Math.min(0.35, amount / Math.max(vd, 0.5)) : 0.18);
    const rel = to.pos.clone().sub(target).applyAxisAngle(UP, a);
    to.pos.copy(target).add(rel);
  }
  if (/pan/.test(move)) {
    const a = (/left/.test(move) ? -1 : 1) * vd * 0.15;
    from.target.addScaledVector(lat, -a / 2);
    to.target.addScaledVector(lat, a / 2);
  }
  const handheld = /handheld|noise|shaky/.test(move);
  const strengthDeg = handheld ? (numberBefore(move, '°') || 0.35) : (set.interior ? 0.07 : 0.05);

  const black = /^\s*black\s*$/i.test(size) || /over black/i.test(subj);
  const titleM = subj.match(/title card[^"“]*["“]([^"”]+)["”]/i);
  const capM = subj.match(/caption:\s*["“]([^"”]+)["”]/i);
  return {
    n: shot.n,
    from, to,
    hfov, hfovEnd: /zoom in|push/.test(move) ? hfov * 0.97 : hfov,
    duration: Math.max(1, shot.duration_s || 4),
    hold,
    handheld: reduced ? 0 : strengthDeg,
    freeze: /freeze/.test(move),
    black,
    titleCard: titleM ? titleM[1] : null,
    caption: capM ? capM[1] : null,
    sepia: /sepia|flashback/i.test(`${size} ${move} ${shot.lighting}`),
    mood: moodFromLighting(shot.lighting || '', set),
    speakerFocus: chars[0]?.key || null,
    cut: reduced,
  };
}

/** Lighting keywords -> light rig multipliers. */
export function moodFromLighting(text, set) {
  const t = String(text).toLowerCase();
  const m = { key: 1, fill: 1, prac: 1, hemi: 1, fog: 1, exposure: 1, rim: [0.62, 0.72, 0.78], rimS: 0.35, sodiumFade: false, sunRamp: null, gold: false };
  if (/dawn|sunrise/.test(t)) { m.rim = [0.7, 0.78, 0.9]; m.fog = 1.15; }
  if (/night|near-black|world 0\.0/.test(t)) { m.hemi = 0.6; m.exposure = 0.95; }
  if (/tungsten|warm|3200|lamp|practical/.test(t)) { m.rim = [1.0, 0.7, 0.42]; m.prac = 1.25; }
  if (/fluorescent|flicker/.test(t)) { m.fill = 1.25; m.rim = [0.7, 0.85, 0.75]; }
  if (/shaft|sun|window|diagonal/.test(t)) { m.key = 1.25; }
  if (/silhouette|backlight|underexposed|only/.test(t)) { m.key = 0.55; m.hemi = 0.55; m.rimS = 0.8; m.exposure = 0.9; }
  if (/neon/.test(t)) { m.rim = [0.3, 0.8, 0.78]; m.rimS = 0.6; }
  if (/flat daylight|overcast|soft/.test(t)) { m.hemi = 1.5; m.key = 0.85; }
  if (/gold|#ffcc00|#ffe58a/.test(t)) { m.rim = [1.0, 0.78, 0.2]; m.rimS = 0.7; m.gold = true; }
  if (/rim/.test(t)) m.rimS = Math.max(m.rimS, 0.6);
  if (/haze|fog|smog|volumetric/.test(t)) m.fog = 1.3;
  if (/fading to 0|switching off|fade.*sodium|sodium.*fad/.test(t)) m.sodiumFade = true;
  const ramp = t.match(/strength\s*(\d+(?:\.\d+)?)\s*→\s*(\d+(?:\.\d+)?)/);
  if (ramp) m.sunRamp = [1, parseFloat(ramp[2]) / parseFloat(ramp[1])];
  return m;
}

/** Plays shot plans on a PerspectiveCamera. */
export class Director {
  constructor(camera) {
    this.cam = camera;
    this.plan = null;
    this.t = 0;
    this.blend = 0;
    this.blendDur = 0.9;
    this.prev = { pos: camera.position.clone(), target: V(0, 1, -1), hfov: 40 };
    this.cur = { pos: camera.position.clone(), target: V(0, 1, -1), hfov: 40 };
    this.frozen = false;
    this.freezeT = 0;
    this.visAspect = REF_ASPECT;
    this.fullOverVis = 1;
    this.mode = 'idle';
    this.follow = null;
    this.reduced = false;
    this.driftT = Math.random() * 100;
  }

  setViewport(w, h, visH) {
    this.visAspect = w / Math.max(1, visH);
    this.fullOverVis = h / Math.max(1, visH);
    this.cam.aspect = w / Math.max(1, h);
  }

  applyFov(hfov) {
    let vvis = vfovFromH(hfov, this.visAspect);
    vvis = Math.min(Math.max(vvis, 5), 72);
    const full = 2 * Math.atan(Math.tan((vvis * DEG) / 2) * this.fullOverVis) / DEG;
    this.cam.fov = Math.min(full, 110);
    this.cam.updateProjectionMatrix();
  }

  play(plan, { cut = false } = {}) {
    this.prev = { pos: this.cur.pos.clone(), target: this.cur.target.clone(), hfov: this.cur.hfov };
    this.plan = plan;
    this.t = 0;
    this.blend = cut || plan.cut || this.mode !== 'shots' ? 1 : 0;
    this.frozen = false;
    this.freezeT = 0;
    this.mode = 'shots';
  }

  get elapsed() { return this.t; }
  get done() { return !this.plan || this.t >= this.plan.duration; }

  freeze() { this.frozen = true; this.freezeT = 0; }
  unfreeze() { this.frozen = false; }

  /** Third-person follow for Arrival. */
  startFollow(character, { offset = V(0.55, 1.75, -3.1), look = V(0, 1.5, 3) } = {}) {
    this.mode = 'follow';
    this.follow = { ch: character, offset, look, pos: null, target: null };
  }

  update(dt, t) {
    const cam = this.cam;
    if (this.mode === 'follow' && this.follow) {
      const f = this.follow;
      const root = f.ch.root;
      const q = root.quaternion;
      const want = f.offset.clone().applyQuaternion(q).add(root.position);
      const look = f.look.clone().applyQuaternion(q).add(root.position);
      if (!f.pos) { f.pos = want.clone(); f.target = look.clone(); }
      const k = 1 - Math.exp(-dt * 3.2);
      f.pos.lerp(want, k);
      f.target.lerp(look, 1 - Math.exp(-dt * 5));
      cam.position.copy(f.pos);
      if (!this.reduced) {
        const moving = f.ch.speed > 0.1 ? 1 : 0.35;
        cam.position.y += Math.sin(t * 5.2) * 0.02 * moving;
        cam.position.x += Math.sin(t * 2.6) * 0.015 * moving;
      }
      cam.lookAt(f.target);
      if (!this.reduced) cam.rotateZ(Math.sin(t * 0.7) * 0.006);
      this.cur.pos.copy(cam.position); this.cur.target.copy(f.target);
      this.cur.hfov = 62;
      this.applyFov(62);
      return;
    }
    if (!this.plan) return;
    const p = this.plan;
    if (!this.frozen) this.t += dt;
    else this.freezeT += dt;
    const span = Math.max(0.01, p.duration - p.hold);
    const u = this.frozen ? Math.min(1, (this.t - p.hold) / span) : easeInOut(Math.min(1, Math.max(0, (this.t - p.hold) / span)));
    const pos = p.from.pos.clone().lerp(p.to.pos, this.reduced ? 0 : u);
    const target = p.from.target.clone().lerp(p.to.target, this.reduced ? 0 : u);
    let hfov = p.hfov + (p.hfovEnd - p.hfov) * u;
    if (this.frozen && !this.reduced) {
      const k = ease(Math.min(1, this.freezeT / 12)) * 0.07;
      pos.lerp(target, k);
      hfov *= 1 - k * 0.3;
    }
    if (this.blend < 1) {
      this.blend = Math.min(1, this.blend + dt / this.blendDur);
      const b = easeInOut(this.blend);
      pos.lerpVectors(this.prev.pos, pos, b);
      target.lerpVectors(this.prev.target, target, b);
      hfov = this.prev.hfov + (hfov - this.prev.hfov) * b;
    }
    cam.position.copy(pos);
    cam.lookAt(target);
    if (p.handheld > 0 && !this.frozen) {
      this.driftT += dt;
      const s = p.handheld * DEG;
      const d = this.driftT;
      cam.rotateX((Math.sin(d * 1.3) * 0.6 + Math.sin(d * 3.7) * 0.3 + Math.sin(d * 7.1) * 0.1) * s);
      cam.rotateY((Math.sin(d * 1.1 + 2) * 0.6 + Math.sin(d * 2.9) * 0.3 + Math.sin(d * 6.3) * 0.1) * s);
      cam.rotateZ(Math.sin(d * 0.9 + 1) * s * 0.4);
    }
    this.cur.pos.copy(pos); this.cur.target.copy(target); this.cur.hfov = hfov;
    this.applyFov(hfov);
  }
}
