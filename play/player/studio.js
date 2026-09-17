// studio.js: procedural TV quiz-show studio ("Who Wants to Be a Lawyer?"), an original design.
// Dark circular stage, sodium-amber + neon-teal accents, raised centre dais with two facing seats,
// a ring of low-poly audience tiers fading into haze, a curved law-book backdrop with a light-strip
// scales-of-justice emblem, a slow-sweeping overhead light rig, and a 15-rung ladder light column.
import * as THREE from 'three';
import {
  std, glow, box, cyl, rng, canvasTex, halo, lightPool, lightCone, makeHaze, textTex,
} from './lib3d.js';
import { makeSetBase, V, floor, addPractical, chair } from './setkit.js';

/** Glossy concentric-ring studio floor, sodium/teal bands over a near-black base. */
function studioFloorTex(seed = 401) {
  return canvasTex(1024, 1024, (g, w, h) => {
    const cx = w / 2, cy = h / 2, maxR = w * 0.52;
    g.fillStyle = '#0e0f11';
    g.fillRect(0, 0, w, h);
    const r = rng(seed);
    const bands = 26;
    for (let i = bands; i >= 0; i--) {
      const rad = (i / bands) * maxR;
      const tier = i % 3;
      g.beginPath();
      g.arc(cx, cy, rad, 0, Math.PI * 2);
      g.fillStyle = tier === 0 ? 'rgba(217,154,62,0.09)' : tier === 1 ? 'rgba(63,182,176,0.07)' : 'rgba(10,10,11,0.85)';
      g.fill();
    }
    g.strokeStyle = 'rgba(255,255,255,0.05)';
    for (let rr = 18; rr < maxR; rr += 24) {
      g.lineWidth = 1 + r() * 1.4;
      g.beginPath(); g.arc(cx, cy, rr, 0, Math.PI * 2); g.stroke();
    }
    g.strokeStyle = 'rgba(0,0,0,0.35)';
    for (let a = 0; a < 28; a++) {
      const ang = (a / 28) * Math.PI * 2;
      g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + Math.cos(ang) * maxR, cy + Math.sin(ang) * maxR); g.stroke();
    }
    // bright centre ring under the hot seat
    g.strokeStyle = 'rgba(255,204,90,0.5)'; g.lineWidth = 4;
    g.beginPath(); g.arc(cx, cy, maxR * 0.14, 0, Math.PI * 2); g.stroke();
  });
}

/** Backdrop texture: stacked law-book spines, original colours only. */
function bookSpineTex(seed = 501) {
  return canvasTex(1536, 640, (g, w, h) => {
    const r = rng(seed);
    g.fillStyle = '#121110'; g.fillRect(0, 0, w, h);
    const cols = [[138, 44, 36], [28, 58, 82], [47, 74, 46], [92, 71, 38], [20, 42, 58], [58, 44, 26], [74, 31, 31], [32, 58, 58]];
    let x = 0;
    while (x < w) {
      const bw = 26 + r() * 48;
      const c = cols[Math.floor(r() * cols.length)];
      const v = 0.75 + r() * 0.35;
      g.fillStyle = `rgb(${c[0] * v | 0},${c[1] * v | 0},${c[2] * v | 0})`;
      g.fillRect(x, 0, bw, h);
      g.fillStyle = 'rgba(255,225,180,0.3)';
      const bands = 2 + Math.floor(r() * 2);
      for (let k = 0; k < bands; k++) g.fillRect(x + 3, h * 0.18 + k * (h / (bands + 1)) + r() * 10, bw - 6, 5);
      g.fillStyle = 'rgba(0,0,0,0.4)'; g.fillRect(x, 0, 2, h);
      g.fillStyle = 'rgba(255,255,255,0.06)'; g.fillRect(x + bw - 2, 0, 1, h);
      x += bw;
    }
    // soft shading top/bottom
    const shade = g.createLinearGradient(0, 0, 0, h);
    shade.addColorStop(0, 'rgba(0,0,0,0.55)'); shade.addColorStop(0.15, 'rgba(0,0,0,0)');
    shade.addColorStop(0.85, 'rgba(0,0,0,0)'); shade.addColorStop(1, 'rgba(0,0,0,0.6)');
    g.fillStyle = shade; g.fillRect(0, 0, w, h);
  });
}

/** A stylised scales-of-justice emblem made of glowing light strips (original, abstract). */
function scalesEmblem(color1 = 0xd99a3e, color2 = 0x3fb6b0) {
  const g = new THREE.Group();
  box(0.07, 3.2, 0.05, glow(color1, 3.2), 0, 1.6, 0, g);
  box(2.6, 0.07, 0.05, glow(color1, 3.2), 0, 3.1, 0, g);
  const dot = new THREE.Mesh(new THREE.SphereGeometry(0.09, 10, 8), glow(0xffe6b0, 4));
  dot.position.set(0, 3.1, 0.03);
  g.add(dot);
  for (const s of [-1, 1]) {
    box(0.03, 0.7, 0.03, glow(color2, 2.4), s * 1.3, 2.72, 0, g);
    const pan = new THREE.Mesh(new THREE.TorusGeometry(0.42, 0.028, 8, 28), glow(color2, 2.6));
    pan.rotation.x = Math.PI / 2;
    pan.position.set(s * 1.3, 2.34, 0);
    g.add(pan);
  }
  // base plinth strip
  box(0.9, 0.06, 0.06, glow(color1, 2.2), 0, 0.05, 0, g);
  return g;
}

/** Procedural TV studio for the quiz-show mode. Same signature/shape as the interior builders. */
export function buildTvStudio(opts = {}) {
  const q = opts || {};
  const set = makeSetBase('tv_studio', { fog: 0x0a0908, density: 0.032, exposure: 1.05, bg: 0x050506 });
  const G = set.group;
  const hi = q.quality !== 'low';
  const reduced = !!q.reduced;

  const DAIS_Y = 0.45;
  const HOST_Z = -1.3, GUEST_Z = 1.3;

  // ---------- floor ----------
  const fl = floor(30, 30, studioFloorTex(), null, { roughness: 0.28, metalness: 0.35, env: 1.4, repeat: [1, 1] });
  G.add(fl);

  // ---------- centre dais ----------
  const daisM = std(0x141416, { roughness: 0.4, metalness: 0.5 });
  cyl(3.6, 3.8, DAIS_Y, hi ? 48 : 28, daisM, 0, DAIS_Y / 2, 0, G);
  const rim = new THREE.Mesh(new THREE.TorusGeometry(3.62, 0.03, 8, hi ? 72 : 36), glow(0xd99a3e, 2.4));
  rim.rotation.x = Math.PI / 2;
  rim.position.y = DAIS_Y + 0.02;
  G.add(rim);
  const hotPool = lightPool(1.6, 0xffcc5a, 0.32);
  hotPool.position.set(0, DAIS_Y + 0.01, 0);
  G.add(hotPool);
  for (const a of [0, Math.PI]) addPractical(set, 0xd99a3e, 3.2, 5, V(Math.sin(a) * 3.4, DAIS_Y + 0.15, Math.cos(a) * 3.4), { sodium: true });

  // seats: host (registrar) and contestant, facing each other
  const seatM = std(0x1c1c1e, { roughness: 0.55 });
  chair(G, 0, DAIS_Y, HOST_Z, 0, seatM);
  chair(G, 0, DAIS_Y, GUEST_Z, Math.PI, seatM);

  // ---------- backdrop: stacked law-book spines behind the host ----------
  const backdropR = 12;
  const backdropGeo = new THREE.CylinderGeometry(backdropR, backdropR, 5.2, hi ? 56 : 28, 1, true, Math.PI * 0.55, Math.PI * 0.9);
  const backdrop = new THREE.Mesh(backdropGeo, std(0xffffff, { map: bookSpineTex(), roughness: 0.85, side: THREE.BackSide }));
  backdrop.position.set(0, 2.6, 0);
  G.add(backdrop);

  const emblem = scalesEmblem();
  emblem.position.set(0, 3.9, -backdropR + 0.35);
  G.add(emblem);
  addPractical(set, 0x3fb6b0, 3, 8, V(0, 4.5, -backdropR + 1.4));

  // ---------- ladder light column (15 rungs) ----------
  const ladderX = 5.4, ladderZ = -1.9;
  const ladderGroup = new THREE.Group();
  ladderGroup.position.set(ladderX, 0, ladderZ);
  G.add(ladderGroup);
  box(0.5, 0.08, 0.34, std(0x0e0e0f, { roughness: 0.6, metalness: 0.5 }), 0, 0.04, 0, ladderGroup);
  const RUNGS = 15;
  const rungH = 0.3, rungGap = 0.05;
  const ladderMats = [];
  const ladderColors = [];
  for (let i = 0; i < RUNGS; i++) {
    const tier = i < 5 ? 0 : i < 10 ? 1 : 2;
    const c = tier === 0 ? 0xd99a3e : tier === 1 ? 0x3fb6b0 : 0xb3372f;
    ladderColors.push(new THREE.Color(c));
    const mat = new THREE.MeshBasicMaterial({ color: new THREE.Color(c).multiplyScalar(0.1) });
    ladderMats.push(mat);
    const y = 0.14 + i * (rungH + rungGap);
    box(0.06, rungH, 0.36, std(0x0e0e0f, { roughness: 0.6 }), -0.22, y, 0, ladderGroup);
    const seg = new THREE.Mesh(new THREE.BoxGeometry(0.32, rungH - 0.03, 0.03), mat);
    seg.position.set(0, y, 0.155);
    ladderGroup.add(seg);
    const label = new THREE.Mesh(new THREE.PlaneGeometry(0.24, rungH - 0.08), new THREE.MeshBasicMaterial({
      map: textTex(String(i + 1), { w: 128, h: 128, color: '#f4ecd8', size: 90 }), transparent: true, depthWrite: false,
    }));
    label.position.set(0, y, 0.175);
    ladderGroup.add(label);
    if (i === 4 || i === 9) {
      const safeMark = new THREE.Mesh(new THREE.RingGeometry(0.19, 0.22, 16), glow(0xffcc00, 1.8, { side: THREE.DoubleSide }));
      safeMark.position.set(0, y, 0.18);
      ladderGroup.add(safeMark);
    }
  }
  addPractical(set, 0xffe0a0, 1.6, 4, V(ladderX, 3.2, ladderZ + 0.4));

  /** Light rungs 0..15 from the bottom; 0 clears the ladder. */
  function setLadder(rung) {
    const n = Math.max(0, Math.min(RUNGS, rung | 0));
    for (let i = 0; i < RUNGS; i++) {
      const on = i < n;
      ladderMats[i].color.copy(ladderColors[i]).multiplyScalar(on ? 3.4 : 0.1);
    }
    set.userData.rung = n;
  }

  // ---------- audience ring, fading into haze ----------
  const tierCount = hi ? 4 : 2;
  const seatGeo = new THREE.BoxGeometry(0.5, 0.8, 0.5);
  const audMat = std(0x141416, { roughness: 0.8 });
  const audInst = new THREE.InstancedMesh(seatGeo, audMat, 900);
  const m4 = new THREE.Matrix4();
  const ar = rng(701);
  let ac = 0;
  for (let t = 0; t < tierCount; t++) {
    const rad = 6.2 + t * 1.6, y = t * 0.5;
    const riser = new THREE.Mesh(new THREE.CylinderGeometry(rad + 0.8, rad + 0.8, y + 0.5, hi ? 40 : 24, 1, true), std(0x0c0c0d, { roughness: 0.9 }));
    riser.position.y = y / 2;
    G.add(riser);
    const n = Math.floor(rad * (hi ? 3.4 : 2.0));
    for (let i = 0; i < n && ac < 900; i++) {
      const a = (i / n) * Math.PI * 2;
      const x = Math.cos(a) * rad, z = Math.sin(a) * rad;
      m4.makeRotationY(Math.PI - a + (ar() - 0.5) * 0.1);
      m4.setPosition(x, y + 0.4, z);
      audInst.setMatrixAt(ac++, m4);
    }
  }
  audInst.count = ac;
  audInst.castShadow = false; audInst.receiveShadow = true;
  G.add(audInst);
  set.slot('extra', V(6.6, 0.6, 3.4), Math.PI * 1.15);
  set.slot('extra', V(-6.6, 0.6, 3.4), -Math.PI * 1.15);

  if (hi) {
    const haze = makeHaze(16, { x0: -13, x1: 13, y0: 0.4, y1: 5.5, z0: -13, z1: 13 }, 0x4a463c, 0.06, 12, 811);
    G.add(haze);
    set.updaters.push((t) => haze.update(t));
  }

  // ---------- overhead light rig ----------
  const rigY = 6.6;
  const fixtureCount = hi ? 6 : 3;
  const overheadPivots = [];
  const overheadHalos = [];
  for (let i = 0; i < fixtureCount; i++) {
    const a = (i / fixtureCount) * Math.PI * 2;
    const rad = 2.7;
    const x = Math.cos(a) * rad, z = Math.sin(a) * rad;
    const color = i % 2 === 0 ? 0xd99a3e : 0x3fb6b0;
    const pivot = new THREE.Group();
    pivot.position.set(x, rigY, z);
    G.add(pivot);
    box(0.3, 0.16, 0.3, std(0x18181a, { roughness: 0.5, metalness: 0.6 }), 0, 0, 0, pivot);
    const cone = lightCone(0.1, 2.0, 3.8, color, hi ? 0.15 : 0.08);
    cone.position.set(0, -0.06, 0);
    pivot.add(cone);
    const hal = halo(color, 0.55, 1.6);
    hal.position.set(0, -0.1, 0);
    pivot.add(hal);
    hal.userData.base = new THREE.Color(color).multiplyScalar(1.6);
    overheadHalos.push(hal);
    overheadPivots.push({ pivot, base: a });
    const spot = new THREE.SpotLight(color, hi ? 12 : 6, 12, Math.PI / 6, 0.6, 1.4);
    spot.position.set(x, rigY - 0.1, z);
    spot.target.position.set(0, DAIS_Y + 0.5, 0);
    spot.castShadow = false;
    G.add(spot, spot.target);
    spot.userData.base = hi ? 12 : 6;
    (i % 2 === 0 ? set.lights.sodium : set.lights.practicals).push(spot);
  }
  if (hi && !reduced) {
    set.updaters.push((t) => {
      for (const { pivot, base } of overheadPivots) {
        pivot.rotation.z = Math.sin(t * 0.15 + base * 3) * 0.35;
        pivot.rotation.x = Math.cos(t * 0.11 + base * 2) * 0.12;
      }
    });
  }

  // main key + cool fill
  const key = new THREE.SpotLight(0xffe6c0, hi ? 46 : 26, 16, Math.PI / 5, 0.55, 1.4);
  key.position.set(0, rigY, 0);
  key.target.position.set(0, DAIS_Y + 0.9, 0);
  key.castShadow = hi;
  if (hi) key.shadow.mapSize.set(1024, 1024);
  G.add(key, key.target);
  key.userData.base = hi ? 46 : 26;
  set.lights.key = key;

  const fill = new THREE.DirectionalLight(0x6fa8a8, 0.35);
  fill.position.set(-6, 5, -4);
  G.add(fill);
  set.lights.fill = fill;
  set.lights.hemi.intensity = 0.18;

  // ---------- pulse cues ----------
  const baseRimColor = rim.material.color.clone();
  const baseHotPoolColor = hotPool.material.color.clone();
  // Kept as no-op closures once finished (never spliced mid-iteration: `set.update` runs
  // `updaters` with a plain for-of, and self-removal there skips whatever shifts into its
  // slot). Pulses are rare (a few per game), so idle closures are not a cost concern.
  function pulse(kind) {
    const color = kind === 'correct' ? new THREE.Color(0x3fb6b0) : kind === 'final' ? new THREE.Color(0xffcc00) : new THREE.Color(0xb3372f);
    const dur = kind === 'final' ? 2.4 : 0.9;
    let t0 = null;
    let done = false;
    const fn = (t) => {
      if (done) return;
      if (t0 == null) t0 = t;
      const u = Math.min(1, (t - t0) / dur);
      const k = Math.sin(u * Math.PI);
      rim.material.color.copy(color).multiplyScalar(1 + k * 3.5);
      hotPool.material.color.copy(color).multiplyScalar(0.3 + k * 1.4);
      for (const hAlo of overheadHalos) hAlo.material.color.copy(color).multiplyScalar(0.5 + k * 1.6);
      if (u >= 1) {
        rim.material.color.copy(baseRimColor);
        hotPool.material.color.copy(baseHotPoolColor);
        for (const hAlo of overheadHalos) hAlo.material.color.copy(hAlo.userData.base);
        done = true;
      }
    };
    set.updaters.push(fn);
  }

  set.userData = { setLadder, pulse, rung: 0 };
  setLadder(0);

  // ---------- slots, center, anchors ----------
  set.center.set(0, 1.65, 0);
  set.slot('host', V(0, DAIS_Y, HOST_Z), 0, 'benchSeated');
  set.slot('clerk', V(0, DAIS_Y, HOST_Z), 0, 'benchSeated');
  set.slot('judge', V(0, DAIS_Y, HOST_Z), 0, 'benchSeated');
  set.slot('contestant', V(0, DAIS_Y, GUEST_Z), Math.PI, 'seated');
  set.slot('player', V(0, DAIS_Y, GUEST_Z), Math.PI, 'seated');
  set.slot('client', V(0, DAIS_Y, GUEST_Z), Math.PI, 'seated');

  set.anchor('wide', V(0, 2.0, 0), V(0, 0.05, 1), 9);
  set.anchor('host', V(0, DAIS_Y + 1.3, HOST_Z), V(0, 0, 1), 0.5);
  set.anchor('contestant', V(0, DAIS_Y + 1.3, GUEST_Z), V(0, 0, -1), 0.5);
  set.anchor('two-shot', V(0, DAIS_Y + 1.2, 0), V(1, 0, 0), 2.8);
  set.anchor('ladder', V(ladderX, 2.6, ladderZ), V(-1, 0, 0.3).normalize(), 4);
  set.anchor('audience', V(0, 3.4, 9), V(0, 0, -1), 6);

  set.kw(/registrar|host/i, 'host');
  set.kw(/contestant|hot seat|player/i, 'contestant');
  set.kw(/two-shot|face to face|both/i, 'two-shot');
  set.kw(/ladder|rung|climb|prize|level/i, 'ladder');
  set.kw(/audience|crowd|tiers|gallery/i, 'audience');
  set.kw(/wide|studio|stage/i, 'wide');

  return set;
}
