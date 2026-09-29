// exteriors.js: the arrival street (with a destination building styled after the case's first set) and the customs yard.
import * as THREE from 'three';
import {
  std, glow, box, cyl, rng, textTex, halo, lightPool, makeRain, makeSteam, makeHaze, neonSign,
  asphaltTex, wetRoughTex, concreteTex, corrugatedTex, Batcher, skyDome, pavingTex, ashlarTex,
  facadeTex2, shopTex, glowSpriteTex,
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

const PI = Math.PI;

// ---------- cars ----------

let CAR_GEO = null;
/** Side-profile sedan, extruded: body, glasshouse and wheel geometry shared by every car. */
function carGeometry() {
  if (CAR_GEO) return CAR_GEO;
  const body = new THREE.Shape();
  // profile in (length, height), length runs rear (-) to front (+)
  const pts = [[-2.25, 0.3], [-2.3, 0.72], [-2.18, 0.9], [-1.2, 0.96], [1.05, 0.96], [2.05, 0.84], [2.3, 0.7], [2.28, 0.3],
    [1.75, 0.3], [1.72, 0.52], [1.28, 0.64], [0.9, 0.52], [0.86, 0.3], [-0.92, 0.3], [-0.96, 0.52], [-1.34, 0.64], [-1.76, 0.52], [-1.8, 0.3]];
  body.moveTo(...pts[0]); for (const p of pts.slice(1)) body.lineTo(...p); body.closePath();
  const bodyGeo = new THREE.ExtrudeGeometry(body, { depth: 1.74, bevelEnabled: true, bevelThickness: 0.05, bevelSize: 0.05, bevelSegments: 2 });
  bodyGeo.translate(0, 0, -0.87);
  const cab = new THREE.Shape();
  const cp = [[-1.2, 0.94], [-0.78, 1.36], [0.42, 1.38], [1.02, 0.94]];
  cab.moveTo(...cp[0]); for (const p of cp.slice(1)) cab.lineTo(...p); cab.closePath();
  const cabGeo = new THREE.ExtrudeGeometry(cab, { depth: 1.5, bevelEnabled: true, bevelThickness: 0.04, bevelSize: 0.04, bevelSegments: 1 });
  cabGeo.translate(0, 0, -0.75);
  const roof = new THREE.BoxGeometry(1.14, 0.05, 1.48);
  roof.translate(-0.18, 1.41, 0);
  for (const g of [bodyGeo, cabGeo, roof]) g.rotateY(-PI / 2); // length along +z
  const wheel = new THREE.CylinderGeometry(0.34, 0.34, 0.24, 14);
  wheel.rotateZ(PI / 2);
  const hub = new THREE.CylinderGeometry(0.19, 0.19, 0.25, 10);
  hub.rotateZ(PI / 2);
  CAR_GEO = { bodyGeo, cabGeo, roof, wheel, hub };
  return CAR_GEO;
}

function car(parent, x, z, rotY, color, seed, lit = false) {
  const G = carGeometry();
  const g = new THREE.Group();
  const paint = std(color, { roughness: 0.28, metalness: 0.55, envMapIntensity: 1.3 });
  const glass = std(0x0a0c0f, { roughness: 0.06, metalness: 0.9, envMapIntensity: 1.6 });
  const tire = std(0x0b0b0b, { roughness: 0.9 });
  const chrome = std(0x8a8c8e, { roughness: 0.25, metalness: 0.9 });
  const add = (geo, m, px = 0, py = 0, pz = 0) => { const mesh = new THREE.Mesh(geo, m); mesh.position.set(px, py, pz); mesh.castShadow = true; mesh.receiveShadow = true; g.add(mesh); return mesh; };
  add(G.bodyGeo, paint);
  add(G.cabGeo, glass);
  add(G.roof, paint);
  for (const [a, b] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
    add(G.wheel, tire, 0.84 * a, 0.34, 1.32 * b);
    add(G.hub, chrome, 0.85 * a, 0.34, 1.32 * b);
  }
  // bumpers and plates
  box(1.7, 0.1, 0.08, chrome, 0, 0.42, 2.34, g);
  box(1.7, 0.1, 0.08, chrome, 0, 0.42, -2.34, g);
  const tail = glow(0xb3372f, lit ? 5 : 1.4);
  for (const s of [-1, 1]) box(0.34, 0.12, 0.04, tail, 0.62 * s, 0.76, -2.33, g).castShadow = false;
  const head = glow(0xfff1d8, lit ? 9 : 0.35);
  for (const s of [-1, 1]) box(0.3, 0.12, 0.04, head, 0.6 * s, 0.72, 2.34, g).castShadow = false;
  if (lit) {
    for (const s of [-1, 1]) { const h = halo(0xfff1d8, 1.4, 1.2); h.position.set(0.6 * s, 0.72, 2.45); g.add(h); }
    const pool = lightPool(3, 0xfff1d8, 0.4, 2.2);
    pool.position.set(0, 0.03, 6);
    g.add(pool);
  }
  g.position.set(x, 0, z);
  g.rotation.y = rotY;
  parent.add(g);
  return g;
}

// ---------- city blocks ----------

const WALL_COLS = [0x5a3a30, 0x6e6454, 0x45423e, 0x46322a, 0x645846];
const SHOP_HUES = [[255, 196, 130], [150, 220, 210], [255, 214, 160], [230, 228, 210]];
const AWNINGS = [0x4a1f1c, 0x1e3534, 0x2c2a26, 0x3d3522];

function streetMaterials(hi) {
  const M = {
    side: WALL_COLS.map((c) => std(c, { roughness: 0.92 })),
    facade: WALL_COLS.map((c, v) => {
      const { map, emissive } = facadeTex2(v, v + 3, 0.3);
      return std(0xffffff, { map, emissiveMap: emissive, emissive: new THREE.Color(1.7, 1.5, 1.3), roughness: 0.85 });
    }),
    base: std(0xffffff, { map: ashlarTex(47, [74, 70, 64], 6), roughness: 0.8 }),
    trim: std(0x8e8678, { roughness: 0.75 }),
    darkTrim: std(0x2b2926, { roughness: 0.6 }),
    metal: std(0x121314, { roughness: 0.55, metalness: 0.7 }),
    door: std(0x231c16, { roughness: 0.55 }),
    shop: SHOP_HUES.map((h, i) => {
      const { map, emissive } = shopTex(i + 1, h);
      return std(0xffffff, { map, emissiveMap: emissive, emissive: new THREE.Color(0.95, 0.76, 0.52), roughness: 0.15, metalness: 0.3 });
    }),
    band: [std(0x1c2624, { roughness: 0.5 }), std(0x2a1a17, { roughness: 0.5 }), std(0x1d1d20, { roughness: 0.5 })],
    awning: AWNINGS.map((c) => std(c, { roughness: 0.8, side: THREE.DoubleSide })),
    pool: SHOP_HUES.map((h) => new THREE.MeshBasicMaterial({ map: glowSpriteTex(), color: new THREE.Color(h[0] / 255, h[1] / 255, h[2] / 255).multiplyScalar(0.22), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })),
    tank: std(0x3a2c22, { roughness: 0.9 }),
    sky: std(0x16181c, { roughness: 1, fog: false }),
    skyWin: null,
  };
  const { emissive } = facadeTex2(2, 99, 0.22);
  M.skyWin = std(0x1a1c20, { emissiveMap: emissive, emissive: new THREE.Color(0.9, 0.75, 0.6), roughness: 1, fog: false });
  M.hi = hi;
  return M;
}

/**
 * One city block. `face` is the side that looks onto the street: 'x-', 'x+' or 'z+'.
 * Everything goes into the batcher, so a block is a handful of merged meshes however detailed it is.
 */
function block(B, M, { cx, cz, w, d, floors, face, seed, shop = true }) {
  const r = rng(seed * 17 + 5);
  const v = seed % WALL_COLS.length;
  const h = 4.4 + floors * 3.2;
  const rot = face === 'x-' ? -PI / 2 : face === 'x+' ? PI / 2 : 0;
  const L = face === 'z+' ? w : d;
  const hn = face === 'z+' ? d / 2 : w / 2;
  const ux = Math.cos(rot), uz = -Math.sin(rot), nx = Math.sin(rot), nz = Math.cos(rot);
  const P = (u, n) => [cx + ux * u + nx * (hn + n), cz + uz * u + nz * (hn + n)];
  const at = (u, y, n) => { const [x, z] = P(u, n); return [x, y, z]; };

  B.box(w, h, d, M.side[v], cx, h / 2, cz);
  // upper facade, UVs in metres so bays line up across buildings
  B.plane(L, floors * 3.2, M.facade[v], ...at(0, 4.4 + floors * 1.6, 0.02), rot, [24, 25.6], [((seed * 3) % 8) / 8, ((seed * 5) % 8) / 8]);
  // string course, cornice, parapet
  B.box(L + 0.2, 0.3, 0.4, M.trim, ...at(0, 4.35, 0.05), rot);
  B.box(L + 0.3, 0.22, 0.5, M.trim, ...at(0, h - 0.2, 0.05), rot);
  B.box(L + 0.7, 0.4, 0.8, M.trim, ...at(0, h + 0.1, 0.1), rot);
  B.box(L, 0.9, 0.3, M.side[v], ...at(0, h + 0.75, -0.15), rot);
  // ground floor
  B.plane(L, 4.1, M.base, ...at(0, 0.15 + 2.05, 0.015), rot, [4, 4]);
  for (const s of [-1, 1]) B.box(0.55, 4.2, 0.3, M.trim, ...at(s * (L / 2 - 0.28), 2.25, 0.1), rot);
  const doorU = L / 2 - 1.4;
  B.plane(1.2, 2.5, M.door, ...at(doorU, 1.4, 0.03), rot);
  B.box(1.5, 0.14, 0.2, M.trim, ...at(doorU, 2.72, 0.08), rot);
  if (shop) {
    const k = Math.floor(r() * M.shop.length);
    const sw = L - 3.2, su = -L / 2 + 0.7 + sw / 2;
    B.plane(sw, 2.7, M.shop[k], ...at(su, 1.6, 0.03), rot);
    B.box(sw + 0.3, 0.12, 0.12, M.darkTrim, ...at(su, 2.98, 0.08), rot);
    B.box(sw + 0.3, 0.3, 0.2, M.darkTrim, ...at(su, 0.3, 0.08), rot);
    for (let i = 1; i < 3; i++) B.box(0.08, 2.7, 0.08, M.darkTrim, ...at(su - sw / 2 + (sw * i) / 3, 1.6, 0.07), rot);
    B.box(L - 1.1, 0.7, 0.14, M.band[seed % 3], ...at(-0.2, 3.5, 0.1), rot);
    if (r() < 0.55) {
      const aw = M.awning[seed % M.awning.length];
      B.box(sw + 0.4, 0.05, 1.5, aw, ...at(su, 3.02, 0.8), [0.32, rot, 0, 'YXZ']);
      B.box(sw + 0.4, 0.3, 0.03, aw, ...at(su, 2.66, 1.52), rot);
    }
    const pool = new THREE.PlaneGeometry(4.6, 3.4);
    B.add(pool, M.pool[k], ...at(su, 0.17, 1.6), [-PI / 2, rot, 0, 'YXZ']);
  } else {
    for (const u of [-L / 4, -L / 4 - 2]) if (Math.abs(u) < L / 2 - 1) B.plane(1.1, 1.6, M.darkTrim, ...at(u, 2.2, 0.03), rot);
  }
  // fire escape
  if (M.hi && floors >= 3 && r() < 0.45) {
    const fu = -L / 2 + 3.6;
    for (let k = 0; k < floors - 1; k++) {
      const y = 4.4 + k * 3.2 + 0.55;
      B.box(3.2, 0.05, 1.1, M.metal, ...at(fu, y, 0.55), rot);
      B.box(3.2, 0.04, 0.04, M.metal, ...at(fu, y + 1, 1.08), rot);
      for (const du of [-1.6, -0.5, 0.5, 1.6]) B.box(0.03, 1, 0.03, M.metal, ...at(fu + du, y + 0.5, 1.08), rot);
      B.box(0.04, 3.2, 0.04, M.metal, ...at(fu + 1.2, y + 1.6, 0.9), rot);
    }
  }
  // roof clutter for the silhouette
  const [rx, rz] = P((r() - 0.5) * L * 0.4, -hn * 0.6);
  if (r() < 0.4) {
    for (const [a, b] of [[-0.7, -0.7], [0.7, -0.7], [-0.7, 0.7], [0.7, 0.7]]) B.box(0.08, 1.4, 0.08, M.metal, rx + a, h + 0.7, rz + b);
    B.cyl(1.1, 1.1, 2.2, 12, M.tank, rx, h + 2.5, rz);
    B.cyl(0.05, 1.2, 0.8, 12, M.tank, rx, h + 4, rz);
  } else {
    B.box(1.4, 0.9, 1.0, M.darkTrim, rx, h + 0.45, rz);
    B.box(0.5, 1.8, 0.5, M.side[v], rx + 2, h + 0.9, rz - 1);
  }
  return h;
}

/** Distant skyline: dark silhouettes with scattered lit windows, never fogged out. */
function skyline(B, M, seed) {
  const r = rng(seed);
  for (let i = 0; i < 26; i++) {
    const x = -130 + i * 10 + r() * 4, z = -120 - r() * 40, w = 8 + r() * 8, h = 22 + r() * 45;
    B.box(w, h, 8, M.sky, x, h / 2, z);
    B.plane(w, h - 2, M.skyWin, x, h / 2, z + 4.01, 0, [24, 25.6], [r(), r()]);
    if (r() < 0.2) B.box(0.3, 8, 0.3, M.sky, x, h + 4, z);
  }
  // behind the camera, the other way down the street
  for (let i = 0; i < 12; i++) {
    const x = -60 + i * 11 + r() * 4, z = 70 + r() * 30, w = 9 + r() * 6, h = 18 + r() * 30;
    B.box(w, h, 8, M.sky, x, h / 2, z);
    B.plane(w, h - 2, M.skyWin, x, h / 2, z - 4.01, PI, [24, 25.6], [r(), r()]);
  }
}

function tree(B, mats, x, z, seed) {
  const r = rng(seed);
  B.box(1.1, 0.04, 1.1, mats.metal, x, 0.17, z);
  B.cyl(0.09, 0.14, 3.2, 7, mats.bark, x, 1.75, z);
  for (let i = 0; i < 4; i++) {
    const a = (i / 4) * PI * 2 + r();
    B.cyl(0.03, 0.06, 1.6, 5, mats.bark, x + Math.cos(a) * 0.35, 3.4, z + Math.sin(a) * 0.35, [Math.sin(a) * 0.5, 0, -Math.cos(a) * 0.5]);
  }
  for (let i = 0; i < 5; i++) {
    const a = r() * PI * 2, d = 0.3 + r() * 0.6;
    const s = 0.8 + r() * 0.6;
    B.add(new THREE.IcosahedronGeometry(1, 0), mats.leaf, x + Math.cos(a) * d, 3.9 + r() * 1.3, z + Math.sin(a) * d, [r(), r(), r()], [s, s * 0.8, s]);
  }
}

// ---------- the destination ----------

function destinationBuilding(set, destKind, z, M) {
  const info = DEST[destKind] || DEST.generic;
  const g = new THREE.Group();
  const B = new Batcher();
  const stoneTex = ashlarTex(49, [158, 148, 130], 8);
  const stone = std(0xffffff, { map: stoneTex, roughness: 0.78 });
  const stonePlain = std(0xa89e8a, { roughness: 0.8 });
  const stoneDark = std(0x6c655a, { roughness: 0.8 });
  const conc = std(0xffffff, { map: concreteTex('#6a655c', 17, 128), roughness: 0.9 });
  const bronze = std(0x3a2a18, { roughness: 0.35, metalness: 0.8 });
  const warm = 0xffc27a;
  const face = z + 1.5; // front face z
  let doorW = 2.2, doorH = 3, doorY = 0;
  const litWin = glow(0xffc88a, 1.25);
  const darkWin = std(0x14171a, { roughness: 0.1, metalness: 0.6, envMapIntensity: 1.4 });
  const tallWindow = (x, y, w, h, lit) => {
    B.plane(w, h, lit ? litWin : darkWin, x, y, face + 0.03);
    B.box(w + 0.3, 0.18, 0.3, stonePlain, x, y - h / 2 - 0.09, face + 0.1);
    B.box(w + 0.5, 0.3, 0.35, stonePlain, x, y + h / 2 + 0.25, face + 0.12);
    B.box(0.06, h, 0.06, M.darkTrim, x, y, face + 0.06);
    for (let k = 1; k < 3; k++) B.box(w, 0.05, 0.05, M.darkTrim, x, y - h / 2 + (h * k) / 3, face + 0.06);
  };
  switch (info.style) {
    case 'court':
    case 'parliament': {
      B.box(26, 16, 10, stonePlain, 0, 8, z - 3.5);
      B.plane(26, 16, stone, 0, 8, face + 0.01, 0, [6, 6]);
      B.box(26.4, 1.0, 0.5, stoneDark, 0, 0.5, face + 0.2);
      B.box(26.6, 0.5, 0.7, stonePlain, 0, 15.9, face + 0.3);
      B.box(26.2, 0.9, 0.3, stonePlain, 0, 16.6, face + 0.1);
      const rw = rng(3);
      for (const x of [-11.6, -9.4, 9.4, 11.6]) {
        tallWindow(x, 4.2, 1.3, 3.2, rw() < 0.6);
        tallWindow(x, 10.4, 1.3, 3.0, rw() < 0.4);
      }
      // steps
      for (let i = 0; i < 4; i++) B.box(14 - i * 0.6, 0.25, 1.2 + (4 - i) * 0.6, stonePlain, 0, 0.125 + i * 0.25, face + 1.8 - i * 0.3);
      // cheek walls with lanterns
      for (const s of [-1, 1]) B.box(0.8, 1.3, 3.6, stoneDark, s * 7.4, 0.65, face + 1.8);
      // colonnade
      const colGeo = () => new THREE.CylinderGeometry(0.4, 0.46, 8.5, 16);
      for (let i = -3; i <= 3; i++) {
        if (i === 0) continue;
        const x = i * 2.1;
        B.box(1.1, 0.3, 1.1, stonePlain, x, 1.15, face + 1.2);
        B.add(colGeo(), stone, x, 1.3 + 4.25, face + 1.2);
        B.box(1.05, 0.25, 1.05, stonePlain, x, 9.95, face + 1.2);
        B.box(1.2, 0.18, 1.2, stonePlain, x, 10.17, face + 1.2);
      }
      // entablature: architrave, frieze, cornice
      B.box(14.6, 0.55, 2.9, stonePlain, 0, 10.53, face + 0.3);
      B.box(14.4, 0.8, 2.8, stonePlain, 0, 11.2, face + 0.28);
      B.box(15.4, 0.35, 3.3, stonePlain, 0, 11.77, face + 0.3);
      // pediment
      const ped = new THREE.Shape();
      ped.moveTo(-7.7, 0); ped.lineTo(7.7, 0); ped.lineTo(0, 2.6); ped.closePath();
      const pedGeo = new THREE.ExtrudeGeometry(ped, { depth: 3.2, bevelEnabled: false });
      B.add(pedGeo, stonePlain, 0, 11.94, face - 1.3);
      const tym = new THREE.Shape();
      tym.moveTo(-6.6, 0); tym.lineTo(6.6, 0); tym.lineTo(0, 2.0); tym.closePath();
      B.add(new THREE.ShapeGeometry(tym), stoneDark, 0, 12.2, face + 1.92);
      // round window in the tympanum, lit
      const oc = new THREE.Mesh(new THREE.CircleGeometry(0.5, 24), glow(0xffc88a, 1.1));
      oc.position.set(0, 12.95, face + 1.93);
      g.add(oc);
      if (info.style === 'parliament') {
        const dome = new THREE.Mesh(new THREE.SphereGeometry(5, 24, 12, 0, PI * 2, 0, PI / 2), std(0x55605a, { roughness: 0.4, metalness: 0.6 }));
        dome.position.set(0, 17, z - 3.5);
        g.add(dome);
        B.cyl(5.2, 5.2, 1.2, 24, stonePlain, 0, 16.6, z - 3.5);
      }
      doorW = 2.6; doorH = 4; doorY = 1;
      // transom over the door
      B.plane(2.6, 0.9, litWin, 0, doorY + doorH + 0.7, face + 0.03);
      B.box(3.2, 0.2, 0.3, stonePlain, 0, doorY + doorH + 1.25, face + 0.1);
      break;
    }
    case 'tower': {
      box(18, 40, 12, std(0x1a1d20, { roughness: 0.15, metalness: 0.8, envMapIntensity: 1.2 }), 0, 20, z - 4.5, g);
      const { map, emissive } = facadeTex2(2, 8, 0.35);
      const skin = std(0xffffff, { map, emissiveMap: emissive, emissive: new THREE.Color(1.6, 1.5, 1.3), roughness: 0.3, metalness: 0.4 });
      B.plane(18, 34, skin, 0, 23, face + 0.01, 0, [24, 25.6]);
      B.plane(12, 5, glow(0xffd9a8, 1.2), 0, 2.5, face + 0.02);
      for (let i = -3; i <= 3; i++) B.box(0.12, 5.4, 0.12, M.metal, i * 2, 2.7, face + 0.08);
      B.box(19, 0.4, 3, M.darkTrim, 0, 5.6, face + 1.3);
      break;
    }
    case 'customs': {
      B.box(20, 7, 10, conc, 0, 3.5, z - 3.5);
      // ribbon windows, some lit
      for (let i = -4; i <= 4; i++) B.plane(1.8, 1.4, i % 3 ? darkWin : litWin, i * 2.1, 4.1, face + 0.02);
      B.box(20.2, 0.25, 0.25, stonePlain, 0, 3.3, face + 0.1);
      B.box(20.4, 0.4, 0.4, stonePlain, 0, 7.1, face + 0.1);
      B.box(22, 0.5, 6, std(0x2a2c2e, { roughness: 0.6, metalness: 0.5 }), 0, 5.2, face + 2.6);
      for (const s of [-1, 1]) B.cyl(0.18, 0.18, 5, 8, std(0xc9b43a, { roughness: 0.5 }), s * 9.5, 2.5, face + 5);
      const tubeM = glow(0xeef2ea, 4);
      for (let i = -3; i <= 3; i++) B.box(1.8, 0.04, 0.15, tubeM, i * 3, 4.93, face + 2.6);
      const bar = new THREE.Group();
      for (let i = 0; i < 8; i++) box(0.6, 0.12, 0.12, std(i % 2 ? 0xe8e1cf : 0xb3372f, { roughness: 0.5 }), -i * 0.6 - 0.3, 0, 0, bar);
      bar.position.set(7.5, 1.05, face + 6.5); bar.rotation.z = 0.05;
      g.add(bar);
      B.box(0.5, 1.1, 0.5, std(0x333333), 7.6, 0.55, face + 6.5);
      const coneM = std(0xd26a1e, { roughness: 0.6 });
      for (let i = 0; i < 5; i++) B.cyl(0.02, 0.18, 0.6, 8, coneM, -6 + i * 0.9, 0.3, face + 7.5);
      break;
    }
    case 'faculty': {
      const brick = std(0xffffff, { map: facadeTex2(0, 12, 0.35).map, emissiveMap: facadeTex2(0, 12, 0.35).emissive, emissive: new THREE.Color(1.5, 1.35, 1.2), roughness: 0.9 });
      B.box(24, 14, 10, M.side[0], 0, 7, z - 3.5);
      B.plane(24, 14, brick, 0, 7, face + 0.01, 0, [24, 25.6]);
      B.box(24.6, 0.5, 0.7, stonePlain, 0, 14, face + 0.2);
      break;
    }
    default: {
      B.box(22, 18, 10, M.side[2], 0, 9, z - 3.5);
      B.plane(22, 14, M.facade[2], 0, 11, face + 0.01, 0, [24, 25.6]);
      B.plane(22, 4, stone, 0, 2, face + 0.01, 0, [6, 6]);
    }
  }
  // doorway: a warm open door with bronze leaves swung in, frame and brass plaque
  const doorGlow = new THREE.Mesh(new THREE.PlaneGeometry(doorW, doorH), glow(warm, 1.9));
  doorGlow.position.set(0, doorH / 2 + doorY, face + 0.04);
  g.add(doorGlow);
  B.box(doorW + 0.5, 0.3, 0.35, bronze, 0, doorY + doorH + 0.15, face + 0.12);
  for (const s of [-1, 1]) B.box(0.25, doorH, 0.35, bronze, s * (doorW / 2 + 0.12), doorY + doorH / 2, face + 0.12);
  const dh = halo(warm, 5, 0.35);
  dh.position.set(0, doorGlow.position.y, face + 0.6);
  g.add(dh);
  // name: incised on the frieze for the stepped buildings, a lit fascia elsewhere
  const stepped = info.style === 'court' || info.style === 'parliament';
  const sign = new THREE.Mesh(new THREE.PlaneGeometry(stepped ? 11 : 9, stepped ? 0.75 : 1.5), new THREE.MeshBasicMaterial({
    map: textTex(stepped ? [{ t: info.label, size: 88, weight: 500 }] : [{ t: info.label, size: 150, weight: 600 }, { t: info.sub, size: 44, weight: 400, font: 'body', y: 215 }],
      { w: 1600, h: stepped ? 110 : 280, color: stepped ? '#efe4cc' : '#f0e2c2' }),
    color: new THREE.Color(stepped ? 1.25 : 1.8, stepped ? 1.18 : 1.7, stepped ? 1.05 : 1.5), transparent: true, depthWrite: false,
  }));
  const signY = stepped ? 11.2 : info.style === 'customs' ? 6 : doorH + 1.3;
  sign.position.set(0, signY, face + (stepped ? 1.69 : info.style === 'customs' ? 5.62 : 0.1));
  g.add(sign);
  if (stepped) {
    const plaque = new THREE.Mesh(new THREE.PlaneGeometry(1.5, 0.42), new THREE.MeshBasicMaterial({
      map: textTex([{ t: info.sub, size: 70, weight: 500 }], { w: 600, h: 168, bg: '#2a2014', color: '#e0b870', border: '#8a6a38' }),
      color: new THREE.Color(1.1, 1.05, 0.95),
    }));
    plaque.position.set(2.4, doorY + 2.2, face + 0.05);
    g.add(plaque);
  }
  const pool = lightPool(4.5, warm, 0.4);
  pool.position.set(0, 0.04 + (stepped ? 1.01 : 0), face + (stepped ? 1.2 : 3));
  g.add(pool);
  // lanterns: on the cheek walls for a stepped front, beside the door otherwise
  const lanternM = glow(warm, 2.6);
  const lanterns = stepped ? [[-7.4, 1.3, face + 3.2], [7.4, 1.3, face + 3.2]] : [[-(doorW / 2 + 1.2), 2.2, face + 0.35], [doorW / 2 + 1.2, 2.2, face + 0.35]];
  for (const [x, y, zz] of lanterns) {
    if (stepped) B.cyl(0.07, 0.09, 1.6, 8, M.metal, x, y + 0.8, zz);
    const ly = stepped ? y + 1.9 : y;
    B.box(0.42, 0.06, 0.42, M.metal, x, ly + 0.36, zz);
    B.box(0.3, 0.5, 0.3, lanternM, x, ly, zz);
    const lh = halo(warm, 1.6, 0.7); lh.position.set(x, ly, zz + 0.05); g.add(lh);
    const lp = lightPool(1.8, warm, 0.18); lp.position.set(x, (stepped ? 1.31 : 0.03), zz + 0.5); g.add(lp);
  }
  B.flush(g);
  set.group.add(g);
  addPractical(set, warm, 34, 14, V(0, 3 + doorY, face + 2.5));
  if (stepped && M.hi) addPractical(set, 0xffd2a0, 26, 18, V(0, 6, face + 7));
  return { door: V(0, 0, face + (stepped ? 4.3 : info.style === 'customs' ? 1.2 : 0.9)), info };
}

/** The arrival street. `destKind` styles the building at the end. */
export function buildStreet(destKind = 'courtroom', q = {}) {
  const set = makeSetBase('street', { interior: false, fog: 0x34332f, density: 0.019, exposure: 1.1, bg: 0x2a2a2a });
  const G = set.group;
  const hi = q.quality !== 'low';
  const M = streetMaterials(hi);
  M.bark = std(0x2a211a, { roughness: 0.9 });
  M.leaf = std(0x2e3524, { roughness: 0.85, flatShading: true });
  M.kerb = std(0x7c776d, { roughness: 0.7 });
  const B = new Batcher();

  // sky
  const sky = skyDome({ octaves: hi ? 4 : 2 });
  G.add(sky);
  set.updaters.push((t, dt, cam) => sky.update(q.reduced ? 0 : t, cam));

  // road, gutters, kerbs and pavements
  const road = floor(10, 88, asphaltTex(), wetRoughTex(), { roughness: 1, metalness: 0.3, env: 1.4, repeat: [2, 18] });
  road.position.set(0, 0, 21);
  G.add(road);
  const gutter = std(0x121212, { roughness: 0.12, metalness: 0.4, envMapIntensity: 1.5 });
  for (const s of [-1, 1]) {
    const walk = floor(4, 88, pavingTex(), wetRoughTex(3), { roughness: 0.95, metalness: 0.15, env: 1, repeat: [2, 44] });
    walk.position.set(s * 7, 0.15, 21);
    G.add(walk);
    B.box(0.3, 0.16, 88, M.kerb, s * 5.1, 0.08, 21);
    B.plane(0.4, 88, gutter, s * 4.75, 0.004, 21, [-PI / 2, 0, 0]);
  }
  // cross street at the end
  const cross = floor(120, 9, asphaltTex(), wetRoughTex(), { roughness: 1, metalness: 0.3, env: 1.4, repeat: [24, 2] });
  cross.position.set(0, 0.005, -27.5);
  G.add(cross);
  const farWalk = floor(120, 4, pavingTex(), wetRoughTex(3), { roughness: 0.95, metalness: 0.15, env: 1, repeat: [60, 2] });
  farWalk.position.set(0, 0.15, -34);
  G.add(farWalk);
  B.box(120, 0.16, 0.3, M.kerb, 0, 0.08, -31.9);
  // markings
  const paint = std(0xc9c3b0, { roughness: 0.6 });
  for (let z = 28; z > -21; z -= 4.5) B.box(0.14, 0.01, 2.2, paint, 0, 0.01, z);
  for (const s of [-1, 1]) B.box(0.1, 0.01, 44, paint, s * 4.3, 0.01, 0);
  for (let x = -4; x <= 4; x += 1) B.box(0.55, 0.012, 3, paint, x, 0.012, -21.1);
  B.box(4.3, 0.012, 0.35, paint, 2.15, 0.012, -19.2);
  // manholes and drains
  const iron = std(0x1a1a1a, { roughness: 0.35, metalness: 0.8 });
  for (const [x, z] of [[1.6, 3], [-1.2, -12]]) B.cyl(0.45, 0.45, 0.02, 18, iron, x, 0.01, z);
  for (let z = 10; z > -20; z -= 9) for (const s of [-1, 1]) B.box(0.35, 0.02, 0.8, iron, s * 4.8, 0.012, z);

  // buildings down both sides, then the cross-street row, then the skyline
  let seed = 3;
  for (const s of [-1, 1]) {
    let z = 34;
    while (z > -23) {
      let d = [6, 9, 12][(seed * 7) % 3];
      if (z - d < -23) d = Math.max(3, z + 23);
      const floors = 3 + ((seed * 5) % 5);
      block(B, M, { cx: s * 13, cz: z - d / 2, w: 8, d: d - 0.1, floors, face: s < 0 ? 'x+' : 'x-', seed: seed++, shop: z < 26 });
      z -= d;
    }
    for (let x = 14; x < 60; x += 12) block(B, M, { cx: s * (x + 5.5), cz: -38, w: 11.8, d: 10, floors: 3 + ((seed * 3) % 5), face: 'z+', seed: seed++, shop: x < 30 });
  }
  skyline(B, M, 7);

  const dest = destinationBuilding(set, destKind, -34, M);
  set.door = dest.door;
  set.destination = dest.info;

  // trees
  let ti = 0;
  for (const [x, z] of [[-7.4, 0.5], [7.4, 6], [-7.4, -10.5], [7.4, -16], [-7.4, 12], [7.4, 17]]) tree(B, M, x, z, 60 + ti++);

  // street furniture: bollards at the crossing, a bench, bins
  for (const s of [-1, 1]) for (let i = 0; i < 3; i++) B.cyl(0.1, 0.12, 0.9, 8, M.metal, s * (5.5 + i * 0.9), 0.6, -22.4);
  B.box(1.8, 0.06, 0.5, std(0x3a2b1e, { roughness: 0.7 }), -8.2, 0.62, -4.5, PI / 2);
  B.box(1.8, 0.5, 0.06, std(0x3a2b1e, { roughness: 0.7 }), -8.45, 0.9, -4.5, PI / 2);
  for (const [x, z] of [[8.2, 1.5], [-8.2, -14]]) B.cyl(0.28, 0.25, 0.9, 10, std(0x23302b, { roughness: 0.5, metalness: 0.3 }), x, 0.6, z);

  // lamps
  let li = 0;
  for (let z = 6; z > -26; z -= 11) {
    streetLamp(set, -5.6, z, { dir: 1, light: hi || li % 2 === 0 });
    streetLamp(set, 5.6, z - 5.5, { dir: -1, light: hi || li % 2 === 1 });
    li++;
  }
  streetLamp(set, 5.6, 17, { dir: -1, light: hi });
  // one dead lamp for grit
  const dead = streetLamp(set, -5.6, 17, { dir: 1, light: false });
  dead.userData.bulb.material.color.setScalar(0.1);
  dead.userData.hal.visible = false; dead.userData.cone.visible = false; dead.userData.pool.visible = false;

  // neon, mounted over the shop fascias
  const signs = [
    ['HOTEL', 0x3fb6b0, -8.85, 5.6, 0, 3.2],
    ['24H', 0xb3372f, 8.85, 4.6, -4, 1.6],
    ['PHARMACY', 0x6fcf7a, -8.85, 4.6, -11, 3.6],
    ['NOODLES', 0xd99a3e, 8.85, 4.8, -14, 3.2],
    ['LAUNDRY', 0x3fb6b0, 8.85, 4.6, 7, 3.2],
    ['BAR', 0xc4506a, -8.85, 5, -19, 1.8],
  ];
  signs.forEach(([t, c, x, y, z, w], i) => {
    const n = neonSign(t, c, { w, h: w * 0.28, seed: i + 1, flicker: i === 2 ? 0.08 : 0.01 });
    n.position.set(x, y, z);
    n.rotation.y = x < 0 ? PI / 2 : -PI / 2;
    G.add(n);
    set.updaters.push((tt) => n.update(tt));
    const pool = lightPool(2.4, c, 0.14, 1.4);
    pool.position.set(x + (x < 0 ? 1.8 : -1.8), 0.17, z);
    G.add(pool);
  });
  addPractical(set, 0x3fb6b0, 10, 10, V(-7, 4, 0));
  addPractical(set, 0xb3372f, 6, 8, V(7, 3.5, -4));

  B.flush(G);

  // parked cars
  car(G, -3.7, 2, 0, 0x3a3f44, 1);
  car(G, -3.7, -9, PI, 0x5a2a24, 2);
  car(G, 3.7, -2, PI, 0x2b3530, 3);
  car(G, 3.7, -16, 0, 0x6b6a62, 4);
  set.colliders = [[-3.7, 2], [-3.7, -9], [3.7, -2], [3.7, -16]].map(([x, z]) => ({ x, z, hw: 1.3, hd: 2.6 }));
  for (const [x, z] of [[-7.4, 0.5], [7.4, 6], [-7.4, -10.5], [7.4, -16], [-7.4, 12], [7.4, 17]]) set.colliders.push({ x, z, hw: 0.45, hd: 0.45 });
  // passing car on the cross street
  const mover = car(G, -60, -26, PI / 2, 0x1c1d1f, 9, true);
  set.updaters.push((t) => {
    const cyc = (t % 14) / 14;
    mover.position.x = -60 + cyc * 120;
  });

  // steam vents
  for (const [x, z] of [[-1.5, -8], [2.4, -19]]) {
    cyl(0.5, 0.5, 0.03, 16, std(0x151515, { roughness: 0.4, metalness: 0.8 }), x, 0.015, z, G);
    const st = makeSteam(hi ? 36 : 16, { spread: 0.6, rise: 4, size: 3, opacity: 0.22, speed: 0.2 });
    st.position.set(x, 0.1, z);
    G.add(st);
    set.updaters.push((t) => st.update(t));
  }

  // rain and haze
  if (!q.reduced) {
    const rain = makeRain(hi ? 3000 : 1200);
    G.add(rain);
    set.updaters.push((t, dt, cam) => rain.update(t, cam));
  }
  if (hi) {
    const haze = makeHaze(12, { x0: -9, x1: 9, y0: 3, y1: 8, z0: -32, z1: 12 }, 0x8a7a62, 0.04, 16);
    G.add(haze);
    set.updaters.push((t) => haze.update(t));
  }

  // cool moonlit key for silhouettes and shadows, a cool sky fill, warm bounce from the street
  const key = new THREE.DirectionalLight(0xa4b4c8, 0.55);
  key.position.set(-14, 22, 6);
  key.castShadow = hi;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.bias = -0.0005;
  key.shadow.normalBias = 0.03;
  Object.assign(key.shadow.camera, { left: -22, right: 22, top: 26, bottom: -26, far: 70 });
  key.target.position.set(0, 0, -10);
  G.add(key, key.target);
  set.lights.key = key;
  set.lights.hemi.color.set(0x56606e);
  set.lights.hemi.groundColor.set(0x2a2218);
  set.lights.hemi.intensity = 0.6;

  set.spawn = { pos: V(1.2, 0, 8), rotY: PI };
  set.walkBounds = { x0: -8.2, x1: 8.2, z0: set.door.z - 0.5, z1: 12 };
  set.center.set(0, 1.5, -10);
  set.anchor('door', set.door.clone().add(V(0, 1.4, 0)), V(0, 0, 1), 3);
  set.kw(/entrance|door|court|building/i, 'door');
  set.slot('player', V(1.2, 0, 8), PI);
  set.slot('client', V(-1.5, 0, set.door.z + 2.5), 0);
  set.slot('clerk', V(1.2, 0, set.door.z + 2.2), -0.3);
  set.slot('extra', V(-6.5, 0.15, -4), PI / 2);
  set.slot('extra', V(6.8, 0.15, -12), -PI / 2);
  return set;
}

/** EXT. customs yard at dawn: containers, truck, booth, barrier, floodlights, haze. */
export function buildCustomsYard(q = {}) {
  const set = makeSetBase('customs_yard', { interior: false, fog: 0x6f7a7c, density: 0.02, exposure: 0.9, bg: 0x6f7c82 });
  const G = set.group;
  const hi = q.quality !== 'low';

  const ground = floor(90, 90, concreteTex('#5a5954', 41, 128), wetRoughTex(5, 0.45), { roughness: 0.9, metalness: 0.15, env: 1.1, repeat: [14, 14] });
  G.add(ground);

  // truck: trailer along x at z=-7, rear doors at +x
  const white = std(0xd9d7cf, { roughness: 0.55, flatShading: true });
  const trailer = new THREE.Group();
  const sideTex = textTex('KADE FREIGHT', { w: 2048, h: 256, color: '#1a2d55', size: 170, weight: 700 });
  // Alpha-tested, not blended: blended, this decal fed the bloom a frame-filling white blob under the dawn sun.
  const sideM = new THREE.MeshStandardMaterial({ map: sideTex, alphaTest: 0.4, roughness: 0.6, polygonOffset: true, polygonOffsetFactor: -2 });
  box(12, 2.7, 2.5, white, 0, 2.55, 0, trailer);
  for (const s of [-1, 1]) {
    const lbl = new THREE.Mesh(new THREE.PlaneGeometry(9, 1.1), sideM);
    lbl.position.set(0, 2.7, s * 1.265);
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
  // yard markings, and ship-to-shore cranes on the skyline rather than bare pillars
  const Y = new Batcher();
  const yellow = std(0xc9a93a, { roughness: 0.6 });
  for (let x = -16; x <= 16; x += 3.2) Y.box(0.12, 0.01, 5.5, yellow, x, 0.012, 7.5);
  Y.box(36, 0.01, 0.15, yellow, 0, 0.012, 4.6);
  Y.box(0.2, 0.01, 30, yellow, 12.5, 0.012, -5);
  const craneM = std(0x4a4f54, { roughness: 0.7, metalness: 0.4, fog: true });
  for (let i = 0; i < 3; i++) {
    const cx = -34 + i * 30, cz = -70 - i * 6, ch = 34 + i * 4;
    for (const s of [-1, 1]) for (const t of [-1, 1]) Y.box(1, ch, 1, craneM, cx + s * 5, ch / 2, cz + t * 6);
    Y.box(12, 1.2, 1.2, craneM, cx, ch * 0.55, cz - 6); Y.box(12, 1.2, 1.2, craneM, cx, ch * 0.55, cz + 6);
    Y.box(1.6, 1.6, 50, craneM, cx, ch + 0.8, cz + 8);
    Y.box(0.3, 12, 0.3, craneM, cx, ch + 6, cz);
    Y.box(4, 3, 3, craneM, cx, ch - 1.5, cz + 4);
  }
  Y.flush(G);

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
  // High enough that its mirror image lands behind the camera: at 4 m it lit a glare patch on the
  // wet yard that the bloom turned into a white blob in the middle of every wide shot.
  const rimL = new THREE.DirectionalLight(0xffd9a8, 0.45);
  rimL.position.set(-10, 14, -20);
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

  const haze = makeHaze(hi ? 12 : 6, { x0: -20, x1: 20, y0: 1, y1: 6, z0: -22, z1: 4 }, 0xb8c2c8, 0.05, 18, 51);
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
