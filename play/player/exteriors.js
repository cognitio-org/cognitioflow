// exteriors.js: the arrival street (with a destination building styled after the case's first set) and the customs yard.
import * as THREE from 'three';
import {
  std, glow, box, cyl, rng, textTex, halo, lightPool, lightCone, makeRain, makeSteam, makeHaze, neonSign,
  asphaltTex, wetRoughTex, concreteTex, brickTex, facadeTex, corrugatedTex,
} from './lib3d.js';
import { makeSetBase, V, streetLamp, floor, addPractical } from './setkit.js';

const DEST = {
  customs_yard: { label: 'CUSTOMS', sub: 'IMPORT · EXPORT · CONTROL', style: 'customs' },
  office: { label: 'LAW OFFICES', sub: 'CHAMBERS · FLOORS 2–9', style: 'tower' },
  courtroom: { label: 'DISTRICT COURT', sub: 'PUBLIC ENTRANCE', style: 'court' },
  parliament: { label: 'PARLIAMENT', sub: 'VISITORS', style: 'parliament' },
  classroom: { label: 'FACULTY OF LAW', sub: 'LECTURE HALLS', style: 'faculty' },
  street: { label: 'DISTRICT COURT', sub: 'PUBLIC ENTRANCE', style: 'court' },
  generic: { label: 'CHAMBERS', sub: 'ENTRANCE', style: 'block' },
};

function car(parent, x, z, rotY, color, seed, lit = false) {
  const r = rng(seed);
  const g = new THREE.Group();
  const paint = std(color, { roughness: 0.25, metalness: 0.6, envMapIntensity: 1.2, flatShading: true });
  const glass = std(0x0b0d10, { roughness: 0.05, metalness: 0.9, envMapIntensity: 1.5 });
  const tire = std(0x0a0a0a, { roughness: 0.9 });
  box(1.8, 0.62, 4.4, paint, 0, 0.55, 0, g);
  const cab = box(1.6, 0.52, 2.2, glass, 0, 1.12, -0.2 + r() * 0.2, g);
  cab.scale.x = 0.98;
  box(1.62, 0.06, 2.0, paint, 0, 1.4, cab.position.z, g);
  for (const [a, b] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
    const w = cyl(0.33, 0.33, 0.24, 10, tire, 0.86 * a, 0.33, 1.4 * b, g);
    w.rotation.z = Math.PI / 2;
  }
  const tail = glow(0xb3372f, lit ? 5 : 1.2);
  for (const s of [-1, 1]) box(0.36, 0.1, 0.03, tail, 0.65 * s, 0.72, -2.21, g);
  const head = glow(0xfff1d8, lit ? 8 : 0.4);
  for (const s of [-1, 1]) box(0.32, 0.12, 0.03, head, 0.6 * s, 0.68, 2.21, g);
  if (lit) {
    for (const s of [-1, 1]) { const h = halo(0xfff1d8, 1.4, 1.2); h.position.set(0.6 * s, 0.68, 2.35); g.add(h); }
    const pool = lightPool(3, 0xfff1d8, 0.4, 2.2);
    pool.position.set(0, 0.03, 6);
    g.add(pool);
  }
  g.position.set(x, 0, z);
  g.rotation.y = rotY;
  parent.add(g);
  return g;
}

function building(parent, x, z, w, d, h, seed, facing) {
  const r = rng(seed);
  const walls = ['#3a3632', '#2f2c2a', '#433b33', '#2c2f31', '#3b332e'];
  const { map, emissive } = facadeTex(seed % 5, { cols: 6, rows: 10, lit: 0.18 + r() * 0.2, wall: walls[seed % walls.length] });
  const m = std(0xffffff, { map: map.clone(), emissiveMap: emissive.clone(), emissive: new THREE.Color(1.8, 1.6, 1.4), roughness: 0.85 });
  for (const t of [m.map, m.emissiveMap]) { t.repeat.set(Math.max(1, d / 16), Math.max(1, h / 26)); t.needsUpdate = true; }
  const b = box(w, h, d, m, x, h / 2, z, parent);
  b.castShadow = false;
  // cornice
  box(w + 0.3, 0.4, d + 0.3, std(0x24221f), x, h, z, parent).castShadow = false;
  // shopfront facing the street
  const sx = x + facing * (w / 2 + 0.02);
  const hue = [0xffb36b, 0x6fd3cc, 0xffd9a0, 0xe0e0d0][Math.floor(r() * 4)];
  if (r() < 0.75) {
    const shop = new THREE.Mesh(new THREE.PlaneGeometry(d * 0.7, 2.4), glow(hue, 0.9 + r()));
    shop.position.set(sx, 1.6, z);
    shop.rotation.y = facing > 0 ? Math.PI / 2 : -Math.PI / 2;
    parent.add(shop);
    const pool = lightPool(2.4, hue, 0.22, 1.8);
    pool.position.set(sx + facing * 1.6, 0.025, z);
    parent.add(pool);
    const awn = box(1.4, 0.08, d * 0.75, std([0x3b1c1a, 0x1e2d2c, 0x2a2a2a][seed % 3], { roughness: 0.7 }), sx + facing * 0.7, 3.1, z, parent);
    awn.rotation.z = facing * -0.25;
  } else {
    box(0.1, 2.8, d * 0.8, std(0x2a2826, { roughness: 0.4, metalness: 0.6 }), sx, 1.4, z, parent);
  }
  // fire escape
  if (r() < 0.5) {
    const metal = std(0x141414, { roughness: 0.6, metalness: 0.7 });
    for (let y = 5; y < h - 2; y += 3.2) box(0.9, 0.06, d * 0.4, metal, sx + facing * 0.45, y, z + d * 0.1, parent).castShadow = false;
  }
  return b;
}

function destinationBuilding(set, destKind, z) {
  const info = DEST[destKind] || DEST.generic;
  const g = new THREE.Group();
  const conc = std(0xffffff, { map: concreteTex('#6a655c', 17, 128), roughness: 0.9 });
  const stone = std(0xb8b0a0, { map: concreteTex('#8f887a', 19, 512), roughness: 0.8 });
  const brick = std(0xffffff, { map: brickTex([96, 60, 44], 23), roughness: 0.9 });
  const warm = 0xffc27a;
  const face = z + 1.5; // front face z
  let doorW = 2.2, doorH = 3;
  switch (info.style) {
    case 'court':
    case 'parliament': {
      box(26, 16, 10, stone, 0, 8, z - 3.5, g);
      for (let i = 0; i < 4; i++) box(14 - i * 0.6, 0.25, 1.2 + (4 - i) * 0.6, stone, 0, 0.125 + i * 0.25, face + 1.8 - i * 0.3, g);
      box(15, 1.2, 3.2, stone, 0, 10.6, face + 0.2, g);
      const ped = new THREE.Mesh(new THREE.CylinderGeometry(0.01, 8.6, 2.8, 3, 1), stone);
      ped.rotation.z = Math.PI / 2; ped.rotation.y = Math.PI / 2; ped.scale.set(1, 1, 0.5);
      ped.position.set(0, 12.2, face + 0.4);
      g.add(ped);
      for (let i = -3; i <= 3; i++) { if (i === 0) continue; cyl(0.42, 0.48, 9.2, 10, stone, i * 2.1, 5.6, face + 1.2, g); }
      if (info.style === 'parliament') {
        const dome = new THREE.Mesh(new THREE.SphereGeometry(5, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2), std(0x55605a, { roughness: 0.4, metalness: 0.6 }));
        dome.position.set(0, 16, z - 3.5);
        g.add(dome);
      }
      doorW = 2.6; doorH = 4;
      break;
    }
    case 'tower': {
      box(18, 40, 12, std(0x1a1d20, { roughness: 0.15, metalness: 0.8, envMapIntensity: 1.2 }), 0, 20, z - 4.5, g);
      const { map, emissive } = facadeTex(8, { cols: 10, rows: 30, lit: 0.3, wall: '#15181b' });
      const skin = new THREE.Mesh(new THREE.PlaneGeometry(18, 34), std(0xffffff, { map, emissiveMap: emissive, emissive: new THREE.Color(1.6, 1.5, 1.3), roughness: 0.2, metalness: 0.5 }));
      skin.position.set(0, 23, face + 0.01);
      g.add(skin);
      const lobby = new THREE.Mesh(new THREE.PlaneGeometry(12, 5), glow(0xffd9a8, 1.4));
      lobby.position.set(0, 2.5, face + 0.02);
      g.add(lobby);
      for (let i = -3; i <= 3; i++) box(0.12, 5.4, 0.12, std(0x111111, { metalness: 0.8, roughness: 0.3 }), i * 2, 2.7, face + 0.08, g);
      break;
    }
    case 'customs': {
      box(20, 7, 10, conc, 0, 3.5, z - 3.5, g);
      box(22, 0.5, 6, std(0x2a2c2e, { roughness: 0.6, metalness: 0.5 }), 0, 5.2, face + 2.6, g);
      for (const s of [-1, 1]) cyl(0.18, 0.18, 5, 8, std(0xc9b43a, { roughness: 0.5 }), s * 9.5, 2.5, face + 5, g);
      for (let i = -3; i <= 3; i++) {
        const t = new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.04, 0.15), glow(0xeef2ea, 4));
        t.position.set(i * 3, 4.93, face + 2.6); g.add(t);
      }
      // barrier arm
      const bar = new THREE.Group();
      for (let i = 0; i < 8; i++) box(0.6, 0.12, 0.12, std(i % 2 ? 0xe8e1cf : 0xb3372f, { roughness: 0.5 }), -i * 0.6 - 0.3, 0, 0, bar);
      bar.position.set(7.5, 1.05, face + 6.5); bar.rotation.z = 0.05;
      g.add(bar);
      box(0.5, 1.1, 0.5, std(0x333333), 7.6, 0.55, face + 6.5, g);
      for (let i = 0; i < 5; i++) {
        const cone = cyl(0.02, 0.18, 0.6, 8, std(0xd26a1e, { roughness: 0.6 }), -6 + i * 0.9, 0.3, face + 7.5, g);
        cone.castShadow = true;
      }
      break;
    }
    case 'faculty': {
      box(24, 14, 10, brick, 0, 7, z - 3.5, g);
      for (let i = -4; i <= 4; i++) {
        if (i === 0) continue;
        const w = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 2.6), glow(i % 3 ? 0x1a1a1a : 0xffc27a, i % 3 ? 1 : 1.2));
        w.position.set(i * 2.4, 6.5, face + 0.02); g.add(w);
      }
      break;
    }
    default:
      box(22, 18, 10, conc, 0, 9, z - 3.5, g);
  }
  // doorway
  const doorGlow = new THREE.Mesh(new THREE.PlaneGeometry(doorW, doorH), glow(warm, 2.4));
  doorGlow.position.set(0, doorH / 2 + (info.style === 'court' || info.style === 'parliament' ? 1 : 0), face + 0.05);
  g.add(doorGlow);
  const frameM = std(0x2a2118, { roughness: 0.4, metalness: 0.5 });
  box(doorW + 0.4, 0.25, 0.3, frameM, 0, doorGlow.position.y + doorH / 2 + 0.12, face + 0.1, g);
  for (const s of [-1, 1]) box(0.2, doorH, 0.3, frameM, s * (doorW / 2 + 0.1), doorGlow.position.y, face + 0.1, g);
  const dh = halo(warm, 6, 0.5);
  dh.position.set(0, doorGlow.position.y, face + 0.6);
  g.add(dh);
  // sign
  const sign = new THREE.Mesh(new THREE.PlaneGeometry(9, 1.5), new THREE.MeshBasicMaterial({
    map: textTex([{ t: info.label, size: 150, weight: 600 }, { t: info.sub, size: 44, weight: 400, font: 'body', y: 215 }], { w: 1600, h: 280, color: '#f0e2c2' }),
    color: new THREE.Color(1.8, 1.7, 1.5), transparent: true,
  }));
  const signY = info.style === 'court' || info.style === 'parliament' ? 10.6 : info.style === 'customs' ? 6 : doorH + 1.3;
  sign.position.set(0, signY, face + (info.style === 'court' || info.style === 'parliament' ? 1.85 : info.style === 'customs' ? 5.62 : 0.1));
  g.add(sign);
  const pool = lightPool(4, warm, 0.5);
  pool.position.set(0, 0.04, face + 3);
  g.add(pool);
  set.group.add(g);
  addPractical(set, warm, 40, 14, V(0, 3, face + 2.5), { shadow: true });
  // flanking lamps
  for (const s of [-1, 1]) {
    const lamp = cyl(0.25, 0.25, 0.6, 10, glow(warm, 3), s * (doorW / 2 + 1.2), 2.6, face + 0.4, g);
    lamp.castShadow = false;
  }
  const stepped = info.style === 'court' || info.style === 'parliament';
  return { door: V(0, 0, face + (stepped ? 4.3 : info.style === 'customs' ? 1.2 : 0.9)), info };
}

/** The arrival street. `destKind` styles the building at the end. */
export function buildStreet(destKind = 'courtroom', q = {}) {
  const set = makeSetBase('street', { interior: false, fog: 0x4a4238, density: 0.028, exposure: 1.05, bg: 0x2a261f });
  const G = set.group;
  const hi = q.quality !== 'low';

  const road = floor(10, 90, asphaltTex(), wetRoughTex(), { roughness: 0.9, metalness: 0.35, env: 1.3, repeat: [2, 18] });
  road.position.set(0, 0, -20);
  G.add(road);
  for (const s of [-1, 1]) {
    const walk = floor(4, 90, concreteTex('#4b4843', 29, 128), wetRoughTex(3), { roughness: 0.9, metalness: 0.2, env: 1, repeat: [1, 22] });
    walk.position.set(s * 7, 0.15, -20);
    G.add(walk);
    box(0.25, 0.16, 90, std(0x5a5750, { roughness: 0.7 }), s * 5.05, 0.08, -20, G).castShadow = false;
  }
  // cross street at the end
  const cross = floor(90, 9, asphaltTex(), wetRoughTex(), { roughness: 0.9, metalness: 0.35, env: 1.3, repeat: [18, 2] });
  cross.position.set(0, 0.005, -27.5);
  G.add(cross);
  // lane markings
  const paint = std(0xb8b2a0, { roughness: 0.5 });
  for (let z = 8; z > -22; z -= 4) box(0.14, 0.01, 2, paint, 0, 0.01, z, G).castShadow = false;
  for (let x = -4; x <= 4; x += 1) box(0.5, 0.01, 2.6, paint, x, 0.012, -22.6, G).castShadow = false;

  // buildings
  let seed = 3;
  for (const s of [-1, 1]) {
    for (let z = 12; z > -24; ) {
      const d = 7 + (seed * 13 % 6);
      const h = 10 + (seed * 7 % 18);
      building(G, s * (9 + 4), z - d / 2, 8, d - 0.3, h, seed++, -s);
      z -= d;
    }
    for (let x = 14; x < 50; x += 11) building(G, s * x + s * 5, -38, 10, 10, 14 + (x % 9), seed++, 0);
  }
  // distant skyline
  for (let i = 0; i < 14; i++) {
    const h = 30 + ((i * 37) % 40);
    building(G, -70 + i * 11, -95 - (i % 3) * 8, 10, 10, h, 40 + i, 0);
  }

  const dest = destinationBuilding(set, destKind, -34);
  set.door = dest.door;
  set.destination = dest.info;

  // lamps
  let li = 0;
  for (let z = 6; z > -26; z -= 11) {
    streetLamp(set, -5.6, z, { dir: 1, light: hi || li % 2 === 0 });
    streetLamp(set, 5.6, z - 5.5, { dir: -1, light: hi || li % 2 === 1 });
    li++;
  }
  // one dead lamp for grit
  streetLamp(set, -5.6, 17, { dir: 1, light: false }).userData.bulb.material.color.setScalar(0.1);

  // neon
  const signs = [
    ['HOTEL', 0x3fb6b0, -8.3, 5.5, 0, 3.2],
    ['24H', 0xb3372f, 8.3, 4, -4, 1.6],
    ['PHARMACY', 0x6fcf7a, -8.3, 3.8, -11, 3.6],
    ['NOODLES', 0xd99a3e, 8.3, 4.2, -14, 3.2],
    ['LAUNDRY', 0x3fb6b0, 8.3, 3.8, 7, 3.2],
    ['BAR', 0xc4506a, -8.3, 4.5, -19, 1.8],
  ];
  signs.forEach(([t, c, x, y, z, w], i) => {
    const n = neonSign(t, c, { w, h: w * 0.28, seed: i + 1, flicker: i === 2 ? 0.08 : 0.01 });
    n.position.set(x, y, z);
    n.rotation.y = x < 0 ? Math.PI / 2 : -Math.PI / 2;
    G.add(n);
    set.updaters.push((tt) => n.update(tt));
    const pool = lightPool(2.2, c, 0.18, 1.5);
    pool.position.set(x + (x < 0 ? 1.6 : -1.6), 0.17, z);
    G.add(pool);
  });
  addPractical(set, 0x3fb6b0, 10, 10, V(-7, 4, 0));
  addPractical(set, 0xb3372f, 6, 8, V(7, 3.5, -4));

  // parked cars
  car(G, -3.8, 2, 0, 0x3a3f44, 1);
  car(G, -3.8, -9, Math.PI, 0x5a2a24, 2);
  car(G, 3.8, -2, Math.PI, 0x2b3530, 3);
  car(G, 3.8, -16, 0, 0x6b6a62, 4);
  set.colliders = [[-3.8, 2], [-3.8, -9], [3.8, -2], [3.8, -16]].map(([x, z]) => ({ x, z, hw: 1.3, hd: 2.6 }));
  // passing car on the cross street
  const mover = car(G, -60, -26, Math.PI / 2, 0x1c1d1f, 9, true);
  set.updaters.push((t) => {
    const cyc = (t % 14) / 14;
    mover.position.x = -60 + cyc * 120;
  });

  // steam vents
  for (const [x, z] of [[-1.5, -8], [2.4, -19]]) {
    cyl(0.5, 0.5, 0.03, 16, std(0x151515, { roughness: 0.4, metalness: 0.8 }), x, 0.015, z, G);
    const st = makeSteam(hi ? 40 : 18, { spread: 0.6, rise: 4, size: 3, opacity: 0.3, speed: 0.2 });
    st.position.set(x, 0.1, z);
    G.add(st);
    set.updaters.push((t) => st.update(t));
  }

  // rain and haze
  if (!q.reduced) {
    const rain = makeRain(hi ? 4000 : 1500);
    G.add(rain);
    set.updaters.push((t, dt, cam) => rain.update(t, cam));
  }
  const haze = makeHaze(hi ? 16 : 8, { x0: -10, x1: 10, y0: 2, y1: 7, z0: -32, z1: 10 }, 0x8a7a62, 0.06, 16);
  G.add(haze);
  set.updaters.push((t) => haze.update(t));

  // moonless sky key: cold dim directional for silhouettes and shadows
  const key = new THREE.DirectionalLight(0x9aa6b0, 0.35);
  key.position.set(-10, 20, 10);
  key.castShadow = hi;
  key.shadow.mapSize.set(1024, 1024);
  Object.assign(key.shadow.camera, { left: -20, right: 20, top: 20, bottom: -20, far: 60 });
  key.target.position.set(0, 0, -10);
  G.add(key, key.target);
  set.lights.key = key;
  set.lights.hemi.color.set(0x6b6258);
  set.lights.hemi.groundColor.set(0x16140f);
  set.lights.hemi.intensity = 0.45;

  set.spawn = { pos: V(1.2, 0, 8), rotY: Math.PI };
  set.walkBounds = { x0: -8.2, x1: 8.2, z0: set.door.z - 0.5, z1: 12 };
  set.center.set(0, 1.5, -10);
  set.anchor('door', set.door.clone().add(V(0, 1.4, 0)), V(0, 0, 1), 3);
  set.kw(/entrance|door|court|building/i, 'door');
  set.slot('player', V(1.2, 0, 8), Math.PI);
  set.slot('client', V(-1.5, 0, set.door.z + 2.5), 0);
  set.slot('clerk', V(1.2, 0, set.door.z + 2.2), -0.3);
  set.slot('extra', V(-6.5, 0.15, -4), Math.PI / 2);
  set.slot('extra', V(6.8, 0.15, -12), -Math.PI / 2);
  return set;
}

/** EXT. customs yard at dawn: containers, truck, booth, barrier, floodlights, haze. */
export function buildCustomsYard(q = {}) {
  const set = makeSetBase('customs_yard', { interior: false, fog: 0x7d8a8f, density: 0.035, exposure: 1.0, bg: 0x6f7c82 });
  const G = set.group;
  const hi = q.quality !== 'low';

  const ground = floor(90, 90, concreteTex('#5a5954', 41, 128), wetRoughTex(5), { roughness: 0.85, metalness: 0.3, env: 1.2, repeat: [14, 14] });
  G.add(ground);

  // truck: trailer along x at z=-7, rear doors at +x
  const white = std(0xd9d7cf, { roughness: 0.55, flatShading: true });
  const trailer = new THREE.Group();
  const sideTex = textTex('KADE FREIGHT', { w: 2048, h: 256, color: '#1a2d55', size: 170, weight: 700 });
  const sideM = new THREE.MeshStandardMaterial({ map: sideTex, transparent: true, roughness: 0.6 });
  box(12, 2.7, 2.5, white, 0, 2.55, 0, trailer);
  for (const s of [-1, 1]) {
    const lbl = new THREE.Mesh(new THREE.PlaneGeometry(9, 1.1), sideM);
    lbl.position.set(0, 2.7, s * 1.26);
    if (s < 0) lbl.rotation.y = Math.PI;
    trailer.add(lbl);
  }
  // open rear: dark interior + doors swung
  const inner = new THREE.Mesh(new THREE.PlaneGeometry(2.3, 2.5), std(0x16140f));
  inner.position.set(6.01, 2.55, 0); inner.rotation.y = Math.PI / 2;
  trailer.add(inner);
  for (const s of [-1, 1]) {
    const door = box(0.05, 2.6, 1.2, white, 6.05 + 0.6, 2.55, s * 1.25 + s * 0.02, trailer);
    door.rotation.y = s * 1.3;
    door.position.set(6.05 + 0.25, 2.55, s * 1.85);
  }
  const boxTex = textTex([{ t: 'MADE IN GERMANIA', size: 70, weight: 600 }], { w: 512, h: 256, bg: '#8a6c4a', color: '#2a1d10' });
  const boxM = [std(0x7d6143), std(0x7d6143), std(0x86694a), std(0x86694a), new THREE.MeshStandardMaterial({ map: boxTex, roughness: 0.9 }), new THREE.MeshStandardMaterial({ map: boxTex, roughness: 0.9 })];
  const bgeo = new THREE.BoxGeometry(0.9, 0.55, 0.3);
  const r = rng(77);
  for (let i = 0; i < 18; i++) {
    const b = new THREE.Mesh(bgeo, boxM);
    b.rotation.y = Math.PI / 2;
    b.position.set(5.6 - (i % 3) * 0.35, 1.5 + Math.floor(i / 6) * 0.56, -0.8 + (i % 6) * 0.32);
    trailer.add(b);
  }
  // cab
  const cab = new THREE.Group();
  box(2.2, 2.6, 2.45, white, 0, 2.1, 0, cab);
  box(0.05, 1.0, 2.1, std(0x0a0c0e, { roughness: 0.05, metalness: 0.9 }), -1.12, 2.7, 0, cab);
  for (const s of [-1, 1]) box(0.05, 0.25, 0.4, glow(0xfff1d8, 3), -1.12, 1.2, s * 0.9, cab);
  cab.position.set(-7.4, 0, 0);
  trailer.add(cab);
  const tire = std(0x0b0b0b, { roughness: 0.9 });
  for (const x of [-8, -4, 3.5, 4.8]) for (const s of [-1, 1]) { const w = cyl(0.5, 0.5, 0.35, 12, tire, x, 0.5, s * 1.05, trailer); w.rotation.x = Math.PI / 2; }
  box(11.5, 0.3, 1.8, std(0x1a1a1a), 0, 1.05, 0, trailer);
  trailer.position.set(0, 0, -7);
  G.add(trailer);
  const cabLights = lightPool(4, 0xfff1d8, 0.35, 1);
  cabLights.position.set(-12, 0.03, -7);
  G.add(cabLights);

  // pallet of unloaded boxes by the rear doors
  const pallet = new THREE.Group();
  box(1.2, 0.14, 1.0, std(0x6b5236), 0, 0.07, 0, pallet);
  for (let i = 0; i < 6; i++) {
    const b = new THREE.Mesh(bgeo, boxM);
    b.position.set(-0.2 + (i % 2) * 0.45, 0.42 + Math.floor(i / 2) * 0.56, 0);
    b.rotation.y = (i % 2 ? 0.05 : -0.04);
    b.castShadow = true;
    pallet.add(b);
  }
  pallet.position.set(7.8, 0, -5.2);
  G.add(pallet);

  // containers
  const conCols = ['#5b3328', '#2b4550', '#6b5a2a', '#3a3f45', '#4b2c2a'];
  const cgeo = new THREE.BoxGeometry(6.1, 2.6, 2.44);
  for (let i = 0; i < 14; i++) {
    const m = std(0xffffff, { map: corrugatedTex(conCols[i % 5], i), roughness: 0.7, metalness: 0.3 });
    m.map = m.map.clone(); m.map.repeat.set(6, 1); m.map.needsUpdate = true;
    const c = new THREE.Mesh(cgeo, m);
    const stack = Math.floor(i / 5);
    c.position.set(-14 + (i % 5) * 6.4, 1.3 + stack * 2.6, -16 - (stack === 2 ? 3 : 0));
    if (i >= 10) { c.position.set(-18, 1.3 + (i - 10) % 2 * 2.6, 2 - (i - 10) * 2.6); c.rotation.y = Math.PI / 2; }
    c.castShadow = true; c.receiveShadow = true;
    G.add(c);
  }

  // booth
  const booth = new THREE.Group();
  const glass = std(0x9fb3c8, { roughness: 0.05, metalness: 0.2, transparent: true, opacity: 0.25, envMapIntensity: 1.5 });
  box(2.4, 0.2, 2.4, std(0x3a3a3a), 0, 2.9, 0, booth);
  box(2.2, 1.0, 2.2, std(0x6a6a66), 0, 0.5, 0, booth);
  box(2.2, 1.8, 2.2, glass, 0, 1.95, 0, booth).castShadow = false;
  const interior = new THREE.Mesh(new THREE.BoxGeometry(2.0, 1.6, 2.0), glow(0xffc27a, 0.6, { transparent: true, opacity: 0.5 }));
  interior.position.y = 1.9;
  booth.add(interior);
  booth.position.set(-6.5, 0, -1);
  G.add(booth);
  addPractical(set, 0xffc27a, 12, 8, V(-6.5, 2, 0.3));
  const bk = halo(0xffc27a, 4, 0.4); bk.position.set(-6.5, 2, 0.2); G.add(bk);

  // barrier
  const bar = new THREE.Group();
  for (let i = 0; i < 12; i++) box(0.6, 0.12, 0.12, std(i % 2 ? 0xe8e1cf : 0xb3372f, { roughness: 0.5 }), i * 0.6 + 0.3, 0, 0, bar);
  bar.position.set(-5.2, 1.05, 3.5);
  G.add(bar);
  box(0.5, 1.1, 0.5, std(0x333333), -5.2, 0.55, 3.5, G);
  set.barrier = bar;

  // floodlights (sodium)
  for (const [x, z, dir] of [[-11, 7, 1], [11, 7, -1], [-11, -12, 1], [12, -12, -1]]) {
    const l = streetLamp(set, x, z, { h: 10, arm: 1.2, dir, intensity: 70 });
    l.scale.setScalar(1);
  }

  // fence and distant structures
  const fenceM = std(0x2a2c2e, { roughness: 0.5, metalness: 0.7, wireframe: false });
  for (let x = -40; x <= 40; x += 3) cyl(0.04, 0.04, 2.6, 5, fenceM, x, 1.3, -24, G).castShadow = false;
  box(80, 0.04, 0.04, fenceM, 0, 2.5, -24, G);
  box(80, 0.04, 0.04, fenceM, 0, 1.3, -24, G);
  for (let i = 0; i < 6; i++) box(1.2, 30 + i * 4, 1.2, std(0x3a3f45), -30 + i * 14, 15 + i * 2, -60, G).castShadow = false;

  // dawn light
  const sun = new THREE.DirectionalLight(0xaec3d8, 0.9);
  sun.position.set(30, 6, -30);
  sun.castShadow = hi;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -25, right: 25, top: 20, bottom: -20, near: 1, far: 100 });
  sun.target.position.set(0, 0, -3);
  G.add(sun, sun.target);
  set.lights.key = sun;
  set.lights.sun = sun;
  set.lights.hemi.color.set(0x9fb3c8);
  set.lights.hemi.groundColor.set(0x2b2f33);
  set.lights.hemi.intensity = 0.55;
  const rimL = new THREE.DirectionalLight(0xffd9a8, 0.6);
  rimL.position.set(-10, 4, -20);
  G.add(rimL);
  set.lights.fill = rimL;

  // dawn sky dome
  const sky = new THREE.Mesh(new THREE.SphereGeometry(150, 24, 12), new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    vertexShader: 'varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);} ',
    fragmentShader: `varying vec3 vP; void main(){ float y = max(vP.y, 0.0);
      vec3 hor = vec3(0.62,0.58,0.5); vec3 top = vec3(0.32,0.38,0.44);
      float sunGlow = pow(max(dot(vP, normalize(vec3(0.7,0.08,-0.7))), 0.0), 8.0);
      vec3 c = mix(hor, top, pow(y, 0.6)) + vec3(0.9,0.55,0.25) * sunGlow * 0.6;
      gl_FragColor = vec4(c, 1.0); }`,
  }));
  G.add(sky);

  const haze = makeHaze(hi ? 22 : 10, { x0: -20, x1: 20, y0: 0.5, y1: 5, z0: -20, z1: 8 }, 0xb8c2c8, 0.08, 18, 51);
  G.add(haze);
  set.updaters.push((t) => haze.update(t));

  // breath for close-ups
  const breath = makeSteam(18, { spread: 0.04, rise: 0.35, size: 0.35, opacity: 0.2, speed: 1.0, color: 0xdfe4e8 });
  G.add(breath);
  set.breath = breath;
  set.updaters.push((t) => breath.update(t));

  set.center.set(0, 1.5, -2);
  set.slot('official', V(-1.1, 0, 1.4), Math.PI / 2 - 0.25, 'holdTablet');
  set.slot('client', V(0.9, 0, 1.6), -Math.PI / 2 + 0.2, 'stand');
  set.slot('player', V(2.4, 0, 3.2), -Math.PI / 2 - 0.4, 'stand');
  set.slot('clerk', V(-3.5, 0, 0.5), Math.PI / 2);
  set.slot('counsel', V(3.5, 0, 0.2), -Math.PI / 2);
  set.slot('judge', V(-3.5, 0, 3), Math.PI / 2);
  set.slot('extra', V(-8, 0, 2), Math.PI / 3);
  set.anchor('truck', V(0, 2.2, -7), V(0, 0, 1), 6);
  set.anchor('booth', V(-6.5, 1.8, -1), V(1, 0, 0.6), 2);
  set.anchor('boxes', V(7.8, 1.3, -5.2), V(0, 1, 0), 0.8);
  set.anchor('lettering', V(-1, 2.7, -5.7), V(0, 0, 1), 1.5);
  set.anchor('barrier', V(-2, 1.1, 3.5), V(0, 0, 1), 3);
  set.anchor('yard', V(0, 1.2, -3), V(0.3, 0, 1), 10);
  set.kw(/truck|lettering|trailer door|doors open/i, 'truck');
  set.kw(/bicycle box|boxes|trailer interior|made in/i, 'boxes');
  set.kw(/booth/i, 'booth');
  set.kw(/barrier/i, 'barrier');
  return set;
}
