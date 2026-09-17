// interiors.js: office at night, courtroom, classroom, parliament hemicycle and the generic void stage.
import * as THREE from 'three';
import {
  std, glow, box, cyl, rng, textTex, halo, lightPool, lightCone, lightShaft, makeHaze, makeSteam,
  concreteTex, wetRoughTex, woodTex, facadeTex, canvasTex,
} from './lib3d.js';
import { makeSetBase, V, floor, wall, addPractical, tfeuBook, printout, deskLamp, chair, tube } from './setkit.js';

function cityWindowTex() {
  return canvasTex(1024, 512, (g, w, h) => {
    const grd = g.createLinearGradient(0, 0, 0, h);
    grd.addColorStop(0, '#0c0d10'); grd.addColorStop(0.6, '#2a1f14'); grd.addColorStop(1, '#4a3018');
    g.fillStyle = grd; g.fillRect(0, 0, w, h);
    const r = rng(8);
    for (let i = 0; i < 40; i++) {
      const bw = 30 + r() * 60, bh = 80 + r() * 300, x = r() * w;
      g.fillStyle = '#07080a'; g.fillRect(x, h - bh, bw, bh);
      for (let k = 0; k < bh / 10; k++) {
        if (r() < 0.3) {
          g.fillStyle = r() < 0.7 ? `rgba(255,${160 + r() * 60 | 0},90,${0.4 + r() * 0.6})` : 'rgba(120,220,215,0.7)';
          g.fillRect(x + 3 + r() * (bw - 8), h - bh + 4 + k * 10, 3, 4);
        }
      }
    }
  });
}

/** INT. warehouse office at night: glass box above a dark floor of bicycle boxes. */
export function buildOffice(q = {}) {
  const set = makeSetBase('office', { fog: 0x0e0d0c, density: 0.05, exposure: 1.05, bg: 0x050505 });
  const G = set.group;
  const hi = q.quality !== 'low';
  const Y = 3; // office floor height

  const wf = floor(30, 24, concreteTex('#3a3936', 61, 128), wetRoughTex(9), { roughness: 0.8, metalness: 0.2, repeat: [6, 5] });
  wf.position.set(0, 0, 6);
  G.add(wf);
  // box stacks on the warehouse floor (instanced)
  const bgeo = new THREE.BoxGeometry(0.9, 0.55, 0.3);
  const inst = new THREE.InstancedMesh(bgeo, std(0x5e4a33, { roughness: 0.95 }), 400);
  const m4 = new THREE.Matrix4();
  const r = rng(5);
  let n = 0;
  for (let row = 0; row < 5; row++) {
    for (let col = 0; col < 8; col++) {
      const bx = -9 + col * 2.4, bz = 5 + row * 2.6, hgt = 2 + Math.floor(r() * 5);
      for (let y = 0; y < hgt && n < 400; y++) {
        for (let k = 0; k < 2 && n < 400; k++) {
          m4.makeRotationY((r() - 0.5) * 0.08);
          m4.setPosition(bx + k * 0.95, 0.28 + y * 0.56, bz);
          inst.setMatrixAt(n++, m4);
        }
      }
    }
  }
  inst.count = n;
  inst.castShadow = true; inst.receiveShadow = true;
  G.add(inst);
  // warehouse racks and tubes
  const steel = std(0x2a2c2e, { roughness: 0.5, metalness: 0.7 });
  for (const x of [-12, 12]) for (let z = 3; z < 18; z += 3) cyl(0.08, 0.08, 7, 6, steel, x, 3.5, z, G);
  for (let z = 4; z < 18; z += 5) tube(set, G, (z % 2 ? -4 : 5), 7.2, z, 1.6, 0, z === 9 ? 0.1 : 0.01);
  addPractical(set, 0x9fc0c8, 4, 12, V(-4, 6.5, 9));

  // mezzanine structure
  box(6, 0.25, 5, std(0x2a2826, { roughness: 0.7 }), 0, Y - 0.125, 0, G);
  for (const [x, z] of [[-2.9, 2.4], [2.9, 2.4], [-2.9, -2.4], [2.9, -2.4]]) cyl(0.1, 0.1, Y, 8, steel, x, Y / 2, z, G);
  // stairs
  for (let i = 0; i < 12; i++) box(1, 0.05, 0.3, steel, 3.6, 0.25 * i + 0.1, 2.3 - i * 0.28, G);
  // railing
  box(6, 0.04, 0.04, steel, 0, Y + 1.0, 2.5, G);

  // office room: inward-facing walls
  const wallM = std(0x6f6a60, { roughness: 0.9, map: concreteTex('#8a857a', 71, 512) });
  G.add(wall(4.4, 2.8, wallM, V(0, Y + 1.4, -1.6), 0));
  G.add(wall(3.2, 2.8, wallM, V(-2.2, Y + 1.4, 0), Math.PI / 2));
  G.add(wall(3.2, 2.8, wallM, V(2.2, Y + 1.4, 0), -Math.PI / 2));
  const ceil = wall(4.4, 3.2, std(0x3a3935), V(0, Y + 2.8, 0), 0);
  ceil.rotation.x = Math.PI / 2;
  G.add(ceil);
  const ofl = floor(4.4, 3.2, woodTex([70, 55, 40], 3), null, { roughness: 0.6, repeat: [2, 2] });
  ofl.position.set(0, Y + 0.01, 0);
  G.add(ofl);
  // glass front with mullions
  const glassM = std(0x8fa3a8, { roughness: 0.05, metalness: 0.1, transparent: true, opacity: 0.12, envMapIntensity: 2, side: THREE.DoubleSide });
  const glassF = new THREE.Mesh(new THREE.PlaneGeometry(4.4, 2.8), glassM);
  glassF.position.set(0, Y + 1.4, 1.6);
  G.add(glassF);
  for (let x = -2.2; x <= 2.2; x += 1.1) box(0.05, 2.8, 0.05, steel, x, Y + 1.4, 1.6, G);
  // door frame on the right wall
  box(0.1, 2.2, 0.08, std(0x1a1a1a), 2.15, Y + 1.1, 0.35, G);
  box(0.1, 2.2, 0.08, std(0x1a1a1a), 2.15, Y + 1.1, 1.3, G);
  // back window with city glow
  const win = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 1.3), new THREE.MeshBasicMaterial({ map: cityWindowTex(), color: new THREE.Color(1.3, 1.25, 1.2) }));
  win.position.set(0.3, Y + 1.7, -1.58);
  G.add(win);
  for (let x = -1; x <= 1.6; x += 0.65) box(0.03, 1.3, 0.03, steel, x, Y + 1.7, -1.57, G);
  // blinds
  for (let y = 0; y < 5; y++) box(2.6, 0.02, 0.02, std(0x222222), 0.3, Y + 2.3 - y * 0.02, -1.55, G);
  addPractical(set, 0x6a8a9a, 1.2, 4, V(0.3, Y + 1.7, -1.1));

  // desk, chair, props
  const deskM = std(0xffffff, { map: woodTex([80, 58, 38], 4), roughness: 0.45 });
  const desk = new THREE.Group();
  box(1.6, 0.05, 0.8, deskM, 0, 0.74, 0, desk);
  for (const s of [-1, 1]) box(0.05, 0.72, 0.7, std(0x1a1a1a), s * 0.75, 0.36, 0, desk);
  desk.position.set(-0.4, Y, -0.25);
  G.add(desk);
  const top = Y + 0.765;
  tfeuBook(G, -0.55, top, -0.2, 0.1, true);
  printout(G, 'Case 26/62 – Van Gend & Loos – pp. 11-13', -0.05, top + 0.004, -0.15, -0.2, 5);
  deskLamp(set, G, -1.0, top, -0.5, 0.5);
  // coffee cups, pen
  for (const x of [0.25]) cyl(0.04, 0.035, 0.1, 10, std(0xe8e1cf, { roughness: 0.4 }), x, top + 0.05, -0.45, G);
  box(0.14, 0.01, 0.01, glow(0xffcc00, 1.2), 0.1, top + 0.006, 0.02, G);
  const chairM = std(0x1c1c1c, { roughness: 0.6 });
  chair(G, -0.4, Y, 0.45, Math.PI, chairM);
  // filing cabinet
  box(0.5, 1.3, 0.6, std(0x4a4d4f, { roughness: 0.5, metalness: 0.6 }), -1.85, Y + 0.65, -1.2, G);
  for (let i = 0; i < 6; i++) printout(G, '', -1.85 + (i % 2) * 0.04, Y + 1.31 + i * 0.01, -1.2, i, 20 + i);

  // warehouse cool fill and office glow seen from below
  const cool = new THREE.DirectionalLight(0x7fa0b8, 0.25);
  cool.position.set(3, 6, 12);
  G.add(cool);
  set.lights.fill = cool;
  set.lights.key = set.lights.practicals.find((l) => l.isSpotLight) || null;
  set.lights.hemi.intensity = 0.12;
  const officeGlow = halo(0xffb46b, 7, 0.18);
  officeGlow.position.set(0, Y + 1.4, 1.8);
  G.add(officeGlow);
  addPractical(set, 0xffb46b, 3, 5, V(0, Y + 2.2, 0.4));

  if (hi) {
    const dust = makeHaze(10, { x0: -10, x1: 10, y0: 1, y1: 6, z0: 3, z1: 16 }, 0x3a3630, 0.05, 10, 71);
    G.add(dust);
    set.updaters.push((t) => dust.update(t));
    const cup = makeSteam(10, { spread: 0.02, rise: 0.25, size: 0.18, opacity: 0.25, speed: 0.6, color: 0xcfc6b8 });
    cup.position.set(0.25, top + 0.1, -0.45);
    G.add(cup);
    set.updaters.push((t) => cup.update(t));
  }

  set.center.set(0, Y + 1.2, 0);
  set.slot('player', V(-0.4, Y, 0.45), Math.PI, 'seated');
  set.slot('client', V(1.75, Y, 0.85), -Math.PI / 2 - 0.3, 'lean');
  set.slot('official', V(1.2, Y, -0.9), -Math.PI / 2 - 0.6);
  set.slot('counsel', V(1.2, Y, -0.9), -Math.PI / 2 - 0.6);
  set.slot('clerk', V(-1.6, Y, 0.9), Math.PI / 2 + 0.5);
  set.slot('judge', V(-1.6, Y, 0.9), Math.PI / 2 + 0.5);
  set.slot('extra', V(1.0, Y, 1.1), Math.PI);
  set.anchor('book', V(-0.55, top + 0.02, -0.2), V(0, 1, 0.15), 0.3);
  set.anchor('printout', V(-0.05, top, -0.15), V(0, 1, 0.1), 0.3);
  set.anchor('desk', V(-0.4, top, -0.25), V(0, 0.4, 1), 1.2);
  set.anchor('office', V(0, Y + 1.3, 0.5), V(0, 0, 1), 4);
  set.anchor('door', V(2.1, Y + 1.2, 0.8), V(-1, 0, 0), 2);
  set.anchor('window', V(0.3, Y + 1.7, -1.5), V(0, 0, 1), 1.5);
  set.kw(/tfeu book|book open|fingertip|ribbon|phrase|highlighter/i, 'book');
  set.kw(/printout|judgment page|pages/i, 'printout');
  set.kw(/desk/i, 'desk');
  set.kw(/office|glass front|lit window/i, 'office');
  set.kw(/doorway|door frame/i, 'door');
  set.fromBelow = V(0, 1.6, 9); // for "from warehouse floor" shots
  return set;
}

/** INT. courtroom: pale oak, raised bench, dock, columns, window shafts. */
export function buildCourtroom(q = {}) {
  const set = makeSetBase('courtroom', { fog: 0x2a2620, density: 0.03, exposure: 1.0, bg: 0x0b0a09 });
  const G = set.group;
  const hi = q.quality !== 'low';
  const W = 14, D = 10, H = 6;
  const oak = std(0xffffff, { map: woodTex([150, 118, 80], 7), roughness: 0.5 });
  const darkOak = std(0xffffff, { map: woodTex([90, 62, 38], 8), roughness: 0.45 });
  const plaster = std(0xbdb6a8, { roughness: 0.95, map: concreteTex('#b9b1a2', 81, 1024) });

  const fl = floor(W, D, woodTex([96, 70, 48], 12), null, { roughness: 0.35, metalness: 0.05, env: 0.8, repeat: [5, 4] });
  G.add(fl);
  // panelled walls (lower oak, upper plaster)
  const walls = [
    [W, V(0, 0, -D / 2), 0], [W, V(0, 0, D / 2), Math.PI], [D, V(-W / 2, 0, 0), Math.PI / 2], [D, V(W / 2, 0, 0), -Math.PI / 2],
  ];
  for (const [w, p, ry] of walls) {
    const lower = wall(w, 2.2, oak, p.clone().setY(1.1), ry);
    const upper = wall(w, H - 2.2, plaster, p.clone().setY(2.2 + (H - 2.2) / 2), ry);
    const nudge = new THREE.Vector3(0, 0, 0.001).applyAxisAngle(new THREE.Vector3(0, 1, 0), ry);
    lower.position.add(nudge);
    G.add(lower, upper);
  }
  const ceil = wall(W, D, std(0x2a2724, { roughness: 1 }), V(0, H, 0), 0);
  ceil.rotation.x = Math.PI / 2;
  G.add(ceil);
  // ceiling light panel
  const panel = new THREE.Mesh(new THREE.PlaneGeometry(3, 6), glow(0xf2ead8, 1.6));
  panel.rotation.x = Math.PI / 2;
  panel.position.set(0, H - 0.02, -0.5);
  G.add(panel);
  const top = new THREE.SpotLight(0xf2e6d0, 30, 14, Math.PI / 3, 0.8, 1.5);
  top.position.set(0, H - 0.1, -0.5);
  top.target.position.set(0, 0, -0.5);
  top.castShadow = hi;
  top.shadow.mapSize.set(1024, 1024);
  G.add(top, top.target);
  top.userData.base = 30;
  set.lights.fill = top;

  // bench
  box(W, 0.6, 3, darkOak, 0, 0.3, -D / 2 + 1.5, G);
  const bench = box(6, 1.3, 0.6, darkOak, 0, 0.6 + 0.65, -D / 2 + 1.9, G);
  box(6.2, 0.08, 0.9, oak, 0, 1.94, -D / 2 + 1.85, G);
  // emblem (abstract, original)
  const emb = new THREE.Mesh(new THREE.RingGeometry(0.55, 0.62, 48), std(0xb08a3a, { metalness: 0.9, roughness: 0.3, side: THREE.DoubleSide }));
  emb.position.set(0, 3.9, -D / 2 + 0.02);
  G.add(emb);
  const embBar = box(0.06, 0.9, 0.02, std(0xb08a3a, { metalness: 0.9, roughness: 0.3 }), 0, 3.9, -D / 2 + 0.03, G);
  embBar.castShadow = false;
  // tall back panel behind judge
  box(3, 2.8, 0.1, darkOak, 0, 2.0, -D / 2 + 0.06, G);
  // judge's chair
  chair(G, 0, 0.6, -D / 2 + 1.05, 0, std(0x2a0f18, { roughness: 0.6 }));
  printout(G, 'Import Duty Act 2026', 0.8, 1.99, -D / 2 + 1.8, 0.3, 30);
  // counsel tables
  for (const s of [-1, 1]) {
    box(2.8, 0.06, 1.0, oak, s * 3, 0.76, -0.4, G);
    box(2.7, 0.7, 0.05, darkOak, s * 3, 0.38, -0.85, G);
    for (const x of [-0.6, 0.6]) chair(G, s * 3 + x, 0, 0.35, Math.PI, std(0x1c1a18));
  }
  tfeuBook(G, 2.6, 0.79, -0.4, 0.2, true);
  printout(G, 'Case 6/64 – Costa v ENEL – pp. 593-594', 3.2, 0.795, -0.35, -0.1, 7);
  printout(G, 'Import Duty Act 2026', -3.0, 0.795, -0.4, 0.2, 9);
  deskLamp(set, G, 3.9, 0.79, -0.7, -0.4);
  // dock / witness box
  const dock = new THREE.Group();
  box(1.6, 1.1, 0.06, darkOak, 0, 0.55, 0.8, dock);
  box(0.06, 1.1, 1.6, darkOak, -0.8, 0.55, 0, dock);
  box(0.06, 1.1, 1.6, darkOak, 0.8, 0.55, 0, dock);
  dock.position.set(-5.5, 0, -2.2);
  G.add(dock);
  // public benches
  for (let row = 0; row < 3; row++) for (const s of [-1, 1]) {
    box(4.6, 0.08, 0.45, oak, s * 3.2, 0.45, 2.2 + row * 1.0, G);
    box(4.6, 0.5, 0.05, oak, s * 3.2, 0.75, 2.45 + row * 1.0, G);
  }
  // bar rail
  box(10, 0.06, 0.06, darkOak, 0, 0.95, 1.4, G);
  // columns
  for (const z of [-3, 0, 3]) for (const s of [-1, 1]) {
    cyl(0.28, 0.32, H, 12, plaster, s * (W / 2 - 0.4), H / 2, z, G);
  }
  // windows on the right wall with sun shafts
  const sun = new THREE.DirectionalLight(0xffe0b0, 2.0);
  sun.position.set(14, 9, 3);
  sun.target.position.set(0, 0, -1);
  sun.castShadow = hi;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -10, right: 10, top: 10, bottom: -10, near: 1, far: 40 });
  G.add(sun, sun.target);
  set.lights.key = sun;
  set.lights.sun = sun;
  for (const z of [-2.5, 0.5, 3.2]) {
    const w = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 2.6), glow(0xfff0d8, 2.6));
    w.position.set(W / 2 - 0.01, 3.6, z);
    w.rotation.y = -Math.PI / 2;
    G.add(w);
    for (let k = -1; k <= 1; k++) box(0.04, 2.6, 0.04, std(0x222222), W / 2 - 0.02, 3.6, z + k * 0.45, G);
    const shaft = lightShaft(1.3, 2.4, 14, 0xffd9a0, 0.16);
    shaft.position.set(W / 2, 3.6, z);
    shaft.lookAt(W / 2 + 14, 3.6 + 9, z + 3); // box extends along -z, so aim back toward the sun
    G.add(shaft);
    set.updaters.push((t) => { shaft.material.uniforms.uTime.value = t; });
    set.shafts = (set.shafts || []).concat(shaft);
  }
  set.lights.hemi.color.set(0xd8cbb4);
  set.lights.hemi.groundColor.set(0x2a2016);
  set.lights.hemi.intensity = 0.5;
  addPractical(set, 0xffe2b8, 4, 10, V(0, 3, 3));

  if (hi) {
    const dust = makeHaze(12, { x0: -6, x1: 6, y0: 1.5, y1: 5, z0: -4, z1: 4 }, 0xb8a888, 0.05, 8, 91);
    G.add(dust);
    set.updaters.push((t) => dust.update(t));
  }

  set.center.set(0, 1.4, -1);
  set.slot('judge', V(0, 0.6, -D / 2 + 1.05), 0, 'benchSeated');
  set.slot('counsel', V(-3, 0, 0.1), Math.PI, 'handOnTable');
  set.slot('player', V(2.4, 0, 0.1), Math.PI, 'stand');
  set.slot('client', V(3.6, 0, 0.35), Math.PI, 'seated');
  set.slot('official', V(-2.4, 0, 0.35), Math.PI, 'seated');
  set.slot('clerk', V(-4.3, 0.6, -D / 2 + 1.6), Math.PI / 2 - 0.3, 'benchSeated');
  set.slot('client', V(-5.5, 0, -2.2), Math.PI / 2, 'stand');
  set.slot('extra', V(-3.2, 0, 2.2), Math.PI, 'seated');
  set.slot('extra', V(3.2, 0, 3.2), Math.PI, 'seated');
  set.anchor('bench', V(0, 1.8, -D / 2 + 1.9), V(0, 0, 1), 3);
  set.anchor('book', V(2.6, 0.82, -0.4), V(0, 1, 0.2), 0.3);
  set.anchor('printout', V(3.2, 0.8, -0.35), V(0, 1, 0.1), 0.3);
  set.anchor('tables', V(0, 0.9, -0.4), V(0, 0.3, 1), 7);
  set.anchor('room', V(0, 1.6, -1), V(0, 0, 1), 12);
  set.anchor('window', V(W / 2 - 0.5, 3, 0.5), V(-1, 0, 0), 3);
  set.anchor('backwall', V(0, 1.7, D / 2 - 0.3), V(0, 0, -1), 1);
  set.anchor('behindBench', V(0, 3.0, -D / 2 + 0.6), V(0, -0.3, 1), 1);
  set.kw(/tfeu book|book in foreground/i, 'book');
  set.kw(/printout|costa|however framed/i, 'printout');
  set.kw(/counsel tables|both tables/i, 'tables');
  set.kw(/court \d|courtroom|room|symmetr/i, 'room');
  set.kw(/bench/i, 'bench');
  return set;
}

/** INT. classroom / lecture room. */
export function buildClassroom(q = {}) {
  const set = makeSetBase('classroom', { fog: 0x1c1d1c, density: 0.035, exposure: 1.0, bg: 0x080808 });
  const G = set.group;
  const W = 12, D = 10, H = 3.8;
  const fl = floor(W, D, concreteTex('#4d4a44', 101, 256), null, { roughness: 0.5, repeat: [4, 4] });
  G.add(fl);
  const wm = std(0x8c8a80, { roughness: 0.95, map: concreteTex('#9a978c', 102, 1024) });
  G.add(wall(W, H, wm, V(0, H / 2, -D / 2), 0), wall(W, H, wm, V(0, H / 2, D / 2), Math.PI),
    wall(D, H, wm, V(-W / 2, H / 2, 0), Math.PI / 2), wall(D, H, wm, V(W / 2, H / 2, 0), -Math.PI / 2));
  const ceil = wall(W, D, std(0x3a3a38), V(0, H, 0), 0); ceil.rotation.x = Math.PI / 2; G.add(ceil);
  // blackboard with chalk
  const chalk = canvasTex(1024, 384, (g, w, h) => {
    g.fillStyle = '#1d2a24'; g.fillRect(0, 0, w, h);
    g.strokeStyle = 'rgba(230,230,220,0.6)'; g.lineWidth = 3;
    g.font = "48px 'IBM Plex Sans', sans-serif"; g.fillStyle = 'rgba(230,230,220,0.7)';
    g.fillText('ISSUE → RULE → APPLICATION → CONCLUSION', 40, 90);
    const r = rng(3);
    for (let i = 0; i < 8; i++) { g.beginPath(); g.moveTo(40, 150 + i * 25); g.lineTo(40 + r() * 800, 150 + i * 25 + r() * 4); g.stroke(); }
  });
  const board = new THREE.Mesh(new THREE.PlaneGeometry(5, 1.8), std(0xffffff, { map: chalk, roughness: 0.9 }));
  board.position.set(0, 1.9, -D / 2 + 0.02);
  G.add(board);
  box(1.6, 1.0, 0.6, std(0x3a3028), 0, 0.5, -D / 2 + 1.6, G);
  // desks (instanced)
  const deskM = std(0xffffff, { map: woodTex([130, 100, 70], 14), roughness: 0.6 });
  for (let row = 0; row < 4; row++) for (let col = -2; col <= 2; col++) {
    box(1.0, 0.04, 0.55, deskM, col * 1.9, 0.74, -1 + row * 1.6, G);
    chair(G, col * 1.9, 0, -0.45 + row * 1.6, Math.PI, std(0x2a2a2a));
  }
  tfeuBook(G, 0.2, 0.76, -1, 0, true);
  // fluorescent tubes
  for (const z of [-3, 0, 3]) for (const x of [-3, 3]) tube(set, G, x, H - 0.05, z, 1.8, 0, x > 0 && z === 0 ? 0.08 : 0.005);
  const fl1 = new THREE.DirectionalLight(0xdfe8e0, 0.8);
  fl1.position.set(0, H, 0); fl1.castShadow = q.quality !== 'low';
  G.add(fl1);
  set.lights.key = fl1;
  // windows
  for (const z of [-3, 0, 3]) {
    const w = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 1.8), glow(0x9fb3c8, 1.4));
    w.position.set(-W / 2 + 0.01, 2.1, z); w.rotation.y = Math.PI / 2;
    G.add(w);
  }
  set.lights.hemi.intensity = 0.5;
  addPractical(set, 0x9fb3c8, 4, 8, V(-4.5, 2, 0));
  set.center.set(0, 1.3, -1);
  set.slot('judge', V(0, 0, -D / 2 + 2.3), 0);
  set.slot('counsel', V(-2.2, 0, -D / 2 + 2.2), 0.4);
  set.slot('clerk', V(2.2, 0, -D / 2 + 2.2), -0.4);
  set.slot('player', V(0, 0, -0.45), Math.PI, 'seated');
  set.slot('client', V(1.9, 0, -0.45), Math.PI, 'seated');
  set.slot('official', V(-1.9, 0, 1.15), Math.PI, 'seated');
  set.slot('extra', V(1.9, 0, 1.15), Math.PI, 'seated');
  set.slot('extra', V(-3.8, 0, 2.75), Math.PI, 'seated');
  set.anchor('board', V(0, 1.9, -D / 2 + 0.1), V(0, 0, 1), 3);
  set.anchor('book', V(0.2, 0.78, -1), V(0, 1, 0.2), 0.3);
  set.anchor('room', V(0, 1.4, -1), V(0, 0, 1), 10);
  set.kw(/board|blackboard|whiteboard|slide/i, 'board');
  set.kw(/book|treaty|notes/i, 'book');
  set.kw(/room|hall|class/i, 'room');
  return set;
}

/** INT. parliament hemicycle. */
export function buildParliament(q = {}) {
  const set = makeSetBase('parliament', { fog: 0x1a1a22, density: 0.025, exposure: 1.0, bg: 0x07070a });
  const G = set.group;
  const fl = floor(40, 40, concreteTex('#2e2d33', 111, 256), null, { roughness: 0.4, metalness: 0.2, repeat: [8, 8] });
  G.add(fl);
  const seatM = std(0x2a3a5a, { roughness: 0.6 });
  const deskM = std(0xffffff, { map: woodTex([120, 90, 60], 15), roughness: 0.5 });
  const seatGeo = new THREE.BoxGeometry(0.55, 0.9, 0.55);
  const tiers = 7;
  let count = 0;
  const seats = new THREE.InstancedMesh(seatGeo, seatM, 600);
  const m4 = new THREE.Matrix4();
  for (let t = 0; t < tiers; t++) {
    const rad = 6 + t * 1.5, y = t * 0.45;
    const tierRing = new THREE.Mesh(new THREE.RingGeometry(rad - 0.75, rad + 0.75, 64, 1, Math.PI * 0.05, Math.PI * 0.9), deskM);
    tierRing.rotation.x = -Math.PI / 2;
    tierRing.position.y = y + 0.01;
    // riser
    const riser = new THREE.Mesh(new THREE.CylinderGeometry(rad + 0.75, rad + 0.75, y + 0.01, 64, 1, true, Math.PI * 0.55, Math.PI * 0.9), std(0x1e1e24));
    riser.position.y = y / 2;
    G.add(tierRing, riser);
    const n = Math.floor(rad * 2.4);
    for (let i = 0; i < n && count < 600; i++) {
      const a = Math.PI * 0.08 + (i / (n - 1)) * Math.PI * 0.84;
      const x = Math.cos(a) * rad, z = -Math.sin(a) * rad;
      m4.makeRotationY(Math.PI / 2 - a + Math.PI);
      m4.setPosition(x, y + 0.45, -z);
      seats.setMatrixAt(count++, m4);
    }
  }
  seats.count = count;
  seats.castShadow = true;
  G.add(seats);
  // podium and backdrop
  box(1.4, 1.2, 0.8, deskM, 0, 0.6, -1.2, G);
  box(4, 0.8, 1.2, deskM, 0, 1.0, -3.2, G);
  box(4.2, 0.5, 1.4, std(0x1e1e24), 0, 0.25, -3.2, G);
  const back = new THREE.Mesh(new THREE.PlaneGeometry(18, 9), std(0x23242c, { roughness: 0.8 }));
  back.position.set(0, 4.5, -5);
  G.add(back);
  const ring = new THREE.Mesh(new THREE.RingGeometry(1.4, 1.52, 64), glow(0xd99a3e, 1.4, { side: THREE.DoubleSide }));
  ring.position.set(0, 5.5, -4.95);
  G.add(ring);
  for (const x of [-6, 6]) {
    const banner = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 6), std(0x2a3a5a, { roughness: 0.9, side: THREE.DoubleSide }));
    banner.position.set(x, 4.5, -4.9);
    G.add(banner);
  }
  const key = new THREE.SpotLight(0xffe2c0, 60, 30, Math.PI / 5, 0.6, 1.2);
  key.position.set(0, 14, 6); key.target.position.set(0, 0, -1);
  key.castShadow = q.quality !== 'low';
  G.add(key, key.target);
  key.userData.base = 60;
  set.lights.key = key;
  const cone = lightCone(0.4, 4, 14, 0xffe2c0, 0.08);
  cone.position.set(0, 14, 6);
  cone.lookAt(0, 0, -1); cone.rotateX(-Math.PI / 2);
  G.add(cone);
  set.lights.hemi.intensity = 0.3;
  addPractical(set, 0x6f8fcf, 8, 20, V(0, 8, -8));
  const haze = makeHaze(10, { x0: -12, x1: 12, y0: 3, y1: 9, z0: -4, z1: 10 }, 0x606070, 0.05, 14, 121);
  G.add(haze);
  set.updaters.push((t) => haze.update(t));
  set.center.set(0, 1.5, 1);
  set.slot('judge', V(0, 1.4, -3.4), 0, 'stand');
  set.slot('player', V(0, 0, -0.6), 0, 'stand');
  set.slot('counsel', V(-3, 0.9, 5.9), Math.PI, 'stand');
  set.slot('official', V(-1.2, 0, -2.1), 0.2, 'stand');
  set.slot('client', V(3, 0.9, 5.9), Math.PI, 'stand');
  set.slot('clerk', V(1.6, 1.4, -3.4), 0, 'stand');
  set.slot('extra', V(-5, 1.35, 7.5), Math.PI + 0.5, 'stand');
  set.anchor('podium', V(0, 1.5, -1.2), V(0, 0, 1), 2);
  set.anchor('hemicycle', V(0, 2, 6), V(0, 0.2, -1), 14);
  set.anchor('room', V(0, 2, 2), V(0, 0.2, -1), 16);
  set.kw(/podium|lectern|speaker/i, 'podium');
  set.kw(/hemicycle|chamber|seats|benches|mep|members/i, 'hemicycle');
  return set;
}

/** Abstract void stage with a glowing grid. */
export function buildGeneric(q = {}) {
  const set = makeSetBase('generic', { fog: 0x14130f, density: 0.04, exposure: 1.0, bg: 0x050505 });
  const G = set.group;
  const grid = new THREE.Mesh(new THREE.PlaneGeometry(80, 80), new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 } },
    vertexShader: 'varying vec3 vW; void main(){ vec4 w = modelMatrix*vec4(position,1.0); vW = w.xyz; gl_Position = projectionMatrix*viewMatrix*w; }',
    fragmentShader: `uniform float uTime; varying vec3 vW;
      void main(){ vec2 g = abs(fract(vW.xz - 0.5) - 0.5) / fwidth(vW.xz);
        float line = 1.0 - min(min(g.x, g.y), 1.0);
        float d = length(vW.xz);
        float fade = exp(-d * 0.09);
        float pulse = 0.6 + 0.4 * sin(d * 0.8 - uTime * 1.2);
        vec3 base = vec3(0.035, 0.034, 0.03);
        vec3 c = base + vec3(0.85, 0.6, 0.25) * line * fade * pulse * 0.9;
        gl_FragColor = vec4(c, 1.0); }`,
  }));
  grid.rotation.x = -Math.PI / 2;
  G.add(grid);
  set.updaters.push((t) => { grid.material.uniforms.uTime.value = t; });
  // plinth + monoliths
  const dark = std(0x121214, { roughness: 0.25, metalness: 0.6 });
  cyl(3.2, 3.4, 0.2, 48, dark, 0, 0.1, 0, G);
  const ringM = glow(0xd99a3e, 2.2);
  const ring = new THREE.Mesh(new THREE.TorusGeometry(3.3, 0.015, 6, 96), ringM);
  ring.rotation.x = Math.PI / 2; ring.position.y = 0.21;
  G.add(ring);
  const r = rng(131);
  for (let i = 0; i < 9; i++) {
    const a = (i / 9) * Math.PI * 2 + 0.3, rad = 9 + r() * 6, h = 3 + r() * 8;
    box(0.8 + r(), h, 0.8 + r(), dark, Math.cos(a) * rad, h / 2, Math.sin(a) * rad, G);
  }
  // filing-rack silhouettes for record rooms
  for (let i = 0; i < 6; i++) box(0.4, 2.6, 3, std(0x1c1b19, { roughness: 0.7 }), -6 + i * 2.4, 1.3, -6, G);
  const key = new THREE.SpotLight(0xf2e2c8, 50, 20, Math.PI / 7, 0.5, 1.5);
  key.position.set(2, 9, 4); key.target.position.set(0, 0.5, 0);
  key.castShadow = q.quality !== 'low';
  G.add(key, key.target);
  key.userData.base = 50;
  set.lights.key = key;
  const cone = lightCone(0.3, 3.4, 9.5, 0xf2e2c8, 0.12);
  cone.position.set(2, 9, 4);
  cone.lookAt(0, 0.5, 0); cone.rotateX(-Math.PI / 2);
  G.add(cone);
  const rimL = new THREE.SpotLight(0x3fb6b0, 40, 20, Math.PI / 6, 0.6, 1.5);
  rimL.position.set(-5, 4, -6); rimL.target.position.set(0, 1, 0);
  G.add(rimL, rimL.target);
  set.lights.fill = rimL;
  set.lights.hemi.intensity = 0.15;
  const haze = makeHaze(12, { x0: -10, x1: 10, y0: 0.5, y1: 5, z0: -10, z1: 8 }, 0x5a5448, 0.06, 14, 141);
  G.add(haze);
  set.updaters.push((t) => haze.update(t));
  set.center.set(0, 1.3, 0);
  set.slot('player', V(0.9, 0.2, 1.2), Math.PI + 0.6);
  set.slot('client', V(-0.9, 0.2, 0.6), 2.0);
  set.slot('judge', V(0, 0.2, -1.6), 0);
  set.slot('counsel', V(-1.6, 0.2, -0.6), 1.2);
  set.slot('clerk', V(1.8, 0.2, -0.8), -0.9);
  set.slot('official', V(-2.2, 0.2, 1.4), 2.2);
  set.slot('extra', V(2.4, 0.2, 1.6), -2.4);
  set.anchor('stage', V(0, 1.2, 0), V(0, 0.2, 1), 6);
  set.anchor('racks', V(0, 1.4, -6), V(0, 0, 1), 5);
  set.kw(/rack|filing|ledger|shelf|record/i, 'racks');
  return set;
}
