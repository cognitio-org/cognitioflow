// human.js: low-poly, realistic-proportion characters built from primitives, with optional Blender glTF replacements.
import * as THREE from 'three';
import { std, rimify, box, cyl, hash, rng, textTex } from './lib3d.js';

// Wardrobe by canonical speaker key. Unknown speakers get a generated muted outfit.
const ROSTER = {
  trainee: { role: 'player', height: 1.75, suit: 0x26282c, shirt: 0xd9d6cc, tie: 0x5a1f1c, hair: 0x1a1512, skin: 0xc49a7c, briefcase: true, hairStyle: 'tied' },
  maren: { role: 'client', height: 1.70, suit: 0x1f2a44, shirt: 0x6c6c6a, legs: 0x151518, hair: 0x9a7b4f, skin: 0xd8b095, coat: true, hairStyle: 'bob', female: true },
  dijk: { role: 'official', height: 1.85, suit: 0x1c2433, shirt: 0x1c2433, vest: 0xb8c928, hair: 0x3a2e24, skin: 0xcfa384, cap: true, build: 1.12, tablet: true },
  haan: { role: 'counsel', height: 1.80, gown: 0x0d0d0f, shirt: 0xeeeeee, hair: 0xb8b8b4, skin: 0xd2a88c, bands: true, glasses: true },
  judge: { role: 'judge', height: 1.65, gown: 0x0b0b0d, trim: 0x2a0f18, shirt: 0xe8e8e8, hair: 0x9d9a96, skin: 0xd9b39a, hairStyle: 'bun', female: true },
  clerk: { role: 'clerk', height: 1.72, suit: 0x3a3a36, shirt: 0xcfcfc6, hair: 0x2b211b, skin: 0xb88a6a, lanyard: true },
};

const ROLE_WORDS = [
  [/judge|president|justice|bench|chair/, 'judge'],
  [/counsel|advocate|agent|haan|lawyer|prosecutor/, 'counsel'],
  [/clerk|usher|registrar|secretary|halvorsen/, 'clerk'],
  [/officer|customs|official|inspector|minister|commissioner/, 'official'],
];

export function profileFor(key, speakerName = '') {
  if (ROSTER[key]) return { key, ...ROSTER[key] };
  const r = rng(hash(key));
  const name = `${key} ${speakerName}`.toLowerCase();
  let role = 'client';
  for (const [re, ro] of ROLE_WORDS) if (re.test(name)) { role = ro; break; }
  const female = r() < 0.5;
  const suits = [0x2b2f36, 0x3b342c, 0x2c3a3a, 0x3a2c2c, 0x33363b, 0x464038];
  const hairs = [0x1c1612, 0x3b2a1e, 0x6d5236, 0x9a8a78, 0x2a2420];
  const skins = [0xd8b095, 0xc49a7c, 0x9c6e52, 0x7a5040, 0xe0bca2];
  const base = {
    key, role, female, height: female ? 1.64 + r() * 0.1 : 1.74 + r() * 0.12,
    suit: suits[Math.floor(r() * suits.length)], shirt: 0xcfcac0,
    hair: hairs[Math.floor(r() * hairs.length)], skin: skins[Math.floor(r() * skins.length)],
    hairStyle: female ? (r() < 0.5 ? 'bob' : 'bun') : 'short', coat: r() < 0.4,
  };
  if (role === 'judge') Object.assign(base, { gown: 0x0b0b0d, trim: 0x2a0f18 });
  if (role === 'counsel') Object.assign(base, { gown: 0x0d0d0f, bands: true });
  if (role === 'clerk') Object.assign(base, { lanyard: true });
  return base;
}

const matCache = new Map();
function mat(color, o = {}) {
  const k = `${color}|${JSON.stringify(o)}`;
  if (!matCache.has(k)) matCache.set(k, rimify(std(color, { flatShading: true, roughness: 0.85, ...o })));
  return matCache.get(k);
}

function limb(r1, r2, len, m, parent) {
  const g = new THREE.Mesh(new THREE.CylinderGeometry(r1, r2, len, 7), m);
  g.geometry.translate(0, -len / 2, 0);
  g.castShadow = true;
  parent.add(g);
  return g;
}

/** Procedural character. */
export class Human {
  constructor(profile) {
    this.p = profile;
    const P = profile;
    const k = (P.height || 1.75) / 1.78;
    const b = P.build || (P.female ? 0.92 : 1);
    this.k = k;
    const root = this.root = new THREE.Group();
    root.name = `human_${P.key}`;
    const body = this.body = new THREE.Group();
    body.scale.setScalar(k);
    root.add(body);

    const skin = mat(P.skin);
    const suit = mat(P.gown || P.suit || 0x2b2f36);
    const legsM = mat(P.legs || P.suit || P.gown || 0x222222);
    const shirt = mat(P.shirt || 0xdddddd);
    const hairM = mat(P.hair || 0x222222, { roughness: 0.95 });
    const shoe = mat(0x0c0c0c, { roughness: 0.35 });

    // hips and legs
    const hips = this.hips = new THREE.Group();
    hips.position.y = 0.93;
    body.add(hips);
    cyl(0.16 * b, 0.17 * b, 0.18, 8, legsM, 0, 0, 0, hips).scale.z = 0.62;
    this.legs = [-1, 1].map((s) => {
      const hip = new THREE.Group();
      hip.position.set(0.09 * s * b, -0.04, 0);
      hips.add(hip);
      limb(0.072 * b, 0.056, 0.45, legsM, hip);
      const knee = new THREE.Group();
      knee.position.y = -0.45;
      hip.add(knee);
      limb(0.054, 0.04, 0.43, legsM, knee);
      const foot = box(0.095, 0.065, 0.27, shoe, 0, -0.45, 0.05, knee);
      foot.castShadow = true;
      return { hip, knee };
    });

    // torso
    const torso = this.torso = new THREE.Group();
    torso.position.y = 0.05;
    hips.add(torso);
    const chest = this.chest = new THREE.Group();
    torso.add(chest);
    const tor = cyl(0.205 * b, 0.155 * b, 0.52, 8, suit, 0, 0.26, 0, chest);
    tor.scale.z = 0.6;
    if (P.female) { const bust = cyl(0.17 * b, 0.17 * b, 0.14, 8, suit, 0, 0.36, 0.02, chest); bust.scale.z = 0.72; }
    if (!P.gown) {
      // shirt V and tie
      const v = new THREE.Mesh(new THREE.CircleGeometry(0.06, 3), shirt);
      v.position.set(0, 0.44, 0.124 * b); v.rotation.z = Math.PI / 2 + Math.PI / 6; v.scale.set(1.3, 0.7, 1);
      chest.add(v);
      if (P.tie) box(0.03, 0.2, 0.01, mat(P.tie), 0, 0.37, 0.126 * b, chest);
      if (P.coat) { const skirt = cyl(0.17 * b, 0.21 * b, 0.42, 8, suit, 0, -0.16, 0, torso, true); skirt.scale.z = 0.66; skirt.material = suit; }
    } else {
      const gown = cyl(0.2 * b, 0.33 * b, 1.18, 9, suit, 0, -0.2, 0, torso, true);
      gown.scale.z = 0.7;
      if (P.trim) { const t = cyl(0.207 * b, 0.207 * b, 0.05, 9, mat(P.trim), 0, 0.5, 0, chest); t.scale.z = 0.62; }
      if (P.bands) { box(0.05, 0.1, 0.01, shirt, 0, 0.44, 0.125, chest); }
    }
    if (P.vest) {
      const vest = cyl(0.215 * b, 0.17 * b, 0.46, 8, mat(P.vest, { roughness: 0.7 }), 0, 0.25, 0, chest);
      vest.scale.z = 0.64;
      const strip = mat(0xd8d8d0, { roughness: 0.3, metalness: 0.4 });
      for (const y of [0.12, 0.3]) { const s = cyl(0.218 * b, 0.2 * b, 0.035, 8, strip, 0, y, 0, chest); s.scale.z = 0.65; }
    }
    if (P.lanyard) box(0.05, 0.07, 0.01, mat(0xe8e1cf), 0, 0.22, 0.128, chest);

    // neck and head
    cyl(0.045, 0.052, 0.1, 6, skin, 0, 0.56, 0, chest);
    const head = this.head = new THREE.Group();
    head.position.y = 0.6;
    chest.add(head);
    const skull = new THREE.Mesh(new THREE.IcosahedronGeometry(0.098, 1), skin);
    skull.scale.set(0.86, 1.14, 1.0);
    skull.position.y = 0.11;
    skull.castShadow = true;
    head.add(skull);
    const jaw = new THREE.Mesh(new THREE.IcosahedronGeometry(0.07, 0), skin);
    jaw.position.set(0, 0.05, 0.02); jaw.scale.set(0.95, 0.8, 1.05);
    head.add(jaw);
    box(0.022, 0.04, 0.03, skin, 0, 0.1, 0.1, head); // nose
    const eyeM = mat(0x0a0a0a, { roughness: 0.3 });
    for (const s of [-1, 1]) box(0.022, 0.01, 0.01, eyeM, 0.034 * s, 0.13, 0.088, head);
    for (const s of [-1, 1]) box(0.012, 0.035, 0.025, skin, 0.086 * s, 0.11, 0, head); // ears
    if (P.glasses) {
      const gm = mat(0xcfd6da, { roughness: 0.1, metalness: 0.8 });
      box(0.11, 0.004, 0.004, gm, 0, 0.132, 0.095, head);
    }
    // hair
    const hair = new THREE.Mesh(new THREE.IcosahedronGeometry(0.104, 1), hairM);
    hair.position.set(0, 0.14, -0.012);
    hair.scale.set(0.9, 1.02, 1.04);
    head.add(hair);
    const style = P.hairStyle || (P.female ? 'bob' : 'short');
    if (style === 'bob') {
      const bob = cyl(0.1, 0.11, 0.14, 8, hairM, 0, 0.08, -0.02, head, false);
      bob.scale.z = 1.0;
    } else if (style === 'bun') {
      const bun = new THREE.Mesh(new THREE.IcosahedronGeometry(0.045, 0), hairM);
      bun.position.set(0, 0.17, -0.1);
      head.add(bun);
    } else if (style === 'tied') {
      const tail = new THREE.Mesh(new THREE.IcosahedronGeometry(0.035, 0), hairM);
      tail.position.set(0, 0.1, -0.115); tail.scale.set(1, 1.6, 1);
      head.add(tail);
    }
    if (P.cap) {
      const capM = mat(0x121620);
      cyl(0.108, 0.108, 0.07, 8, capM, 0, 0.22, -0.01, head);
      box(0.15, 0.012, 0.08, capM, 0, 0.19, 0.1, head);
    }

    // arms
    const sleeve = P.gown ? mat(P.gown) : suit;
    this.arms = [-1, 1].map((s) => {
      const sh = new THREE.Group();
      sh.position.set(0.215 * s * b, 0.48, 0);
      chest.add(sh);
      limb(P.gown ? 0.07 : 0.05 * b, P.gown ? 0.075 : 0.043 * b, 0.3, sleeve, sh);
      const el = new THREE.Group();
      el.position.y = -0.3;
      sh.add(el);
      limb(P.gown ? 0.065 : 0.042 * b, 0.034, 0.27, sleeve, el);
      const hand = new THREE.Group();
      hand.position.y = -0.28;
      el.add(hand);
      box(0.045, 0.09, 0.028, skin, 0, -0.04, 0, hand);
      return { sh, el, hand, side: s };
    });

    if (P.briefcase) this.addBriefcase();
    if (P.tablet) this.addTablet();

    this.phase = Math.random() * 10;
    this.pose = 'stand';
    this.walkPhase = 0;
    this.speed = 0;
    this.talking = false;
    this.frozen = false;
    this.facing = new THREE.Vector3(0, 0, 1);
  }

  addBriefcase() {
    const leather = mat(0x2a1b12, { roughness: 0.45 });
    const brass = mat(0xb08a3a, { roughness: 0.3, metalness: 0.9 });
    const g = this.briefcase = new THREE.Group();
    box(0.44, 0.31, 0.1, leather, 0, -0.2, 0, g);
    box(0.44, 0.012, 0.102, brass, 0, -0.07, 0, g);
    box(0.12, 0.02, 0.02, leather, 0, -0.03, 0, g);
    for (const s of [-1, 1]) box(0.03, 0.02, 0.105, brass, 0.14 * s, -0.08, 0, g);
    g.rotation.y = Math.PI / 2;
    this.arms[1].hand.add(g);
  }

  addTablet() {
    const g = this.tablet = new THREE.Group();
    box(0.26, 0.18, 0.012, mat(0x0c0c0e, { roughness: 0.3 }), 0, 0, 0, g);
    const tex = textTex([
      { t: 'IMPORT DUTY ACT 2026 – NEDERLANDA', size: 30, y: 60, color: '#e8e1cf', font: 'body', weight: 600 },
      { t: '€ 4 800', size: 150, y: 200, color: '#ff5a4a', weight: 700 },
    ], { w: 768, h: 512, bg: '#1d2328' });
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.24, 0.16), new THREE.MeshBasicMaterial({ map: tex, color: new THREE.Color(1.6, 1.6, 1.6) }));
    screen.position.z = 0.007;
    g.add(screen);
    g.position.set(0, -0.1, 0.06);
    g.rotation.set(-0.3, 0, 0);
    this.arms[0].hand.add(g);
    this.tabletScreen = screen;
  }

  setPose(name) { this.pose = name; }

  /** World position helpers used by the camera director. */
  headPos(out = new THREE.Vector3()) { return this.head.getWorldPosition(out).add(new THREE.Vector3(0, 0.12 * this.k, 0)); }
  chestPos(out = new THREE.Vector3()) { return this.chest.getWorldPosition(out).add(new THREE.Vector3(0, 0.3 * this.k, 0)); }
  handPos(i = 0, out = new THREE.Vector3()) { return this.arms[i].hand.getWorldPosition(out); }
  worldFacing(out = new THREE.Vector3()) { return out.set(0, 0, 1).applyQuaternion(this.root.quaternion); }

  update(dt, t) {
    if (this.frozen) return;
    const ph = t + this.phase;
    const [L, R] = this.legs;
    const [AL, AR] = this.arms;
    const reset = (g) => g.rotation.set(0, 0, 0);
    [L.hip, L.knee, R.hip, R.knee, AL.sh, AL.el, AR.sh, AR.el, this.torso, this.head].forEach(reset);
    this.hips.position.y = 0.93;
    this.body.position.set(0, 0, 0);

    const breath = Math.sin(ph * 1.4) * 0.012;
    this.chest.scale.set(1 + breath * 0.5, 1 + breath, 1 + breath);
    this.head.rotation.y = Math.sin(ph * 0.3) * 0.12;
    this.head.rotation.x = Math.sin(ph * 0.21) * 0.04;

    if (this.speed > 0.05) {
      this.walkPhase += dt * this.speed * 5.2;
      const w = this.walkPhase, a = Math.min(1, this.speed / 1.6);
      L.hip.rotation.x = Math.sin(w) * 0.5 * a;
      R.hip.rotation.x = -Math.sin(w) * 0.5 * a;
      L.knee.rotation.x = Math.max(0, -Math.cos(w)) * 0.9 * a;
      R.knee.rotation.x = Math.max(0, Math.cos(w)) * 0.9 * a;
      this.hips.position.y = 0.93 - Math.abs(Math.cos(w)) * 0.03 * a;
      AL.sh.rotation.x = -Math.sin(w) * 0.4 * a;
      AL.el.rotation.x = -0.25 * a;
      AR.sh.rotation.x = this.briefcase ? Math.sin(w) * 0.12 * a : Math.sin(w) * 0.4 * a;
      AR.el.rotation.x = this.briefcase ? 0 : -0.25 * a;
      this.torso.rotation.y = Math.sin(w) * 0.06 * a;
      this.torso.rotation.x = 0.04 * a;
      AL.sh.rotation.z = -0.08; AR.sh.rotation.z = 0.08 + (this.briefcase ? 0.1 : 0);
      return;
    }

    AL.sh.rotation.z = -0.07; AR.sh.rotation.z = 0.07 + (this.briefcase ? 0.1 : 0);
    const sway = Math.sin(ph * 0.5) * 0.015;
    this.hips.rotation.z = sway;
    switch (this.pose) {
      case 'seated':
        this.hips.position.y = 0.5;
        L.hip.rotation.x = R.hip.rotation.x = -Math.PI / 2;
        L.knee.rotation.x = R.knee.rotation.x = Math.PI / 2;
        AL.sh.rotation.x = AR.sh.rotation.x = -0.7;
        AL.el.rotation.x = AR.el.rotation.x = -0.6;
        this.torso.rotation.x = 0.12;
        break;
      case 'holdTablet':
        AL.sh.rotation.x = -0.9; AL.el.rotation.x = -0.9; AL.sh.rotation.z = 0.15;
        break;
      case 'phone':
        AR.sh.rotation.x = -0.4; AR.sh.rotation.z = 0.9; AR.el.rotation.x = -2.3;
        this.head.rotation.z = 0.12;
        break;
      case 'coffee':
        AL.sh.rotation.x = AR.sh.rotation.x = -0.35;
        AL.el.rotation.x = AR.el.rotation.x = -1.2;
        break;
      case 'lean':
        this.hips.rotation.z = 0.08; this.torso.rotation.z = -0.1;
        AR.sh.rotation.x = -0.35; AR.el.rotation.x = -1.2;
        AL.sh.rotation.x = -0.35; AL.el.rotation.x = -1.1;
        break;
      case 'handOnTable':
        AL.sh.rotation.x = -0.45; AL.el.rotation.x = -0.2;
        this.torso.rotation.x = 0.08;
        break;
      case 'benchSeated':
        this.hips.position.y = 0.5;
        L.hip.rotation.x = R.hip.rotation.x = -Math.PI / 2;
        L.knee.rotation.x = R.knee.rotation.x = Math.PI / 2;
        AL.sh.rotation.x = AR.sh.rotation.x = -0.9; AL.el.rotation.x = AR.el.rotation.x = -0.5;
        break;
      default:
        L.hip.rotation.x = 0.02; R.hip.rotation.x = -0.02;
    }
    if (this.talking) {
      this.head.rotation.x += Math.sin(t * 7) * 0.035;
      const arm = this.pose === 'phone' || this.pose === 'holdTablet' ? (this.pose === 'phone' ? AL : AR) : AR;
      if (!(this.briefcase && arm === AR && this.pose === 'stand')) {
        arm.sh.rotation.x += -0.25 + Math.sin(t * 2.3) * 0.12;
        arm.el.rotation.x += -0.6 + Math.sin(t * 3.1) * 0.15;
      }
    }
  }
}

// ---------- glTF characters ----------

/** Wraps a Blender character (with optional idle/walk clips) behind the Human interface. */
export class GltfHuman {
  constructor(gltf, profile) {
    this.p = profile;
    this.root = new THREE.Group();
    const model = gltf.scene;
    model.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
    this.root.add(model);
    const bb = new THREE.Box3().setFromObject(model);
    this.height = Math.max(0.5, bb.max.y - bb.min.y);
    this.k = this.height / 1.78;
    this.mixer = new THREE.AnimationMixer(model);
    this.clips = {};
    for (const c of gltf.animations || []) this.clips[c.name.toLowerCase()] = this.mixer.clipAction(c);
    this.current = null;
    this.play('idle');
    this.speed = 0; this.talking = false; this.frozen = false; this.pose = 'stand';
    this.headBone = null;
    model.traverse((o) => { if (!this.headBone && /head/i.test(o.name)) this.headBone = o; });
  }
  play(name) {
    const a = this.clips[name];
    if (!a || a === this.current) return;
    a.reset().fadeIn(0.25).play();
    if (this.current) this.current.fadeOut(0.25);
    this.current = a;
  }
  setPose(p) { this.pose = p; }
  headPos(out = new THREE.Vector3()) {
    if (this.headBone) return this.headBone.getWorldPosition(out);
    return this.root.getWorldPosition(out).add(new THREE.Vector3(0, this.height * 0.94, 0));
  }
  chestPos(out = new THREE.Vector3()) { return this.root.getWorldPosition(out).add(new THREE.Vector3(0, this.height * 0.75, 0)); }
  handPos(i, out = new THREE.Vector3()) { return this.root.getWorldPosition(out).add(new THREE.Vector3(0, this.height * 0.5, 0.2)); }
  worldFacing(out = new THREE.Vector3()) { return out.set(0, 0, 1).applyQuaternion(this.root.quaternion); }
  update(dt) {
    if (this.frozen) return;
    this.play(this.speed > 0.05 ? 'walk' : 'idle');
    if (this.current && this.clips.walk === this.current) this.current.timeScale = Math.max(0.4, this.speed / 1.4);
    this.mixer.update(dt);
  }
}

const CHAR_FILE_BY_ROLE = { player: 'lawyer', judge: 'judge', clerk: 'clerk', client: 'client', counsel: 'lawyer', official: 'clerk' };

/** Build a character: glTF if the Blender export exists for this role, else procedural. */
export async function makeCharacter(profile, loadAsset) {
  const file = CHAR_FILE_BY_ROLE[profile.role];
  if (file && loadAsset) {
    try {
      const gltf = await loadAsset('characters', file);
      if (gltf) return new GltfHuman(gltf, profile);
    } catch (err) {
      console.warn('[human] glTF character failed, using procedural', err);
    }
  }
  return new Human(profile);
}
