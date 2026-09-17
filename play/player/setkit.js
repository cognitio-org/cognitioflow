// setkit.js: the common shape of a set, plus small reusable props.
import * as THREE from 'three';
import { std, box, cyl, textTex, paperTex, glow, halo, lightPool, lightCone, rimify } from './lib3d.js';

export function V(x, y, z) { return new THREE.Vector3(x, y, z); }

/** Base object every set builder fills in. */
export function makeSetBase(kind, { interior = true, fog = 0x2a2824, density = 0.02, exposure = 1, bg = 0x0a0a0b } = {}) {
  const group = new THREE.Group();
  group.name = `set_${kind}`;
  const hemi = new THREE.HemisphereLight(0x8f8a80, 0x1a1816, 0.35);
  group.add(hemi);
  return {
    kind, group, interior,
    anchors: {}, slots: {}, keywords: [],
    lights: { hemi, key: null, fill: null, practicals: [], sodium: [], sun: null },
    fog: { color: new THREE.Color(fog), density }, exposure, bg: new THREE.Color(bg),
    updaters: [],
    spawn: null, door: null, walkBounds: null,
    center: V(0, 1, 0),
    anchor(name, pos, facing = V(0, 0, 1), h = 0.3) { this.anchors[name] = { pos, facing: facing.clone().normalize(), h }; },
    slot(role, pos, rotY = 0, pose = 'stand') { (this.slots[role] ||= []).push({ pos, rotY, pose }); },
    kw(re, name) { this.keywords.push([re, name]); },
    update(t, dt, cam) { for (const u of this.updaters) u(t, dt, cam); },
    dispose() { disposeTree(group); },
  };
}

export function disposeTree(root) {
  root.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    const mats = Array.isArray(o.material) ? o.material : o.material ? [o.material] : [];
    for (const m of mats) {
      for (const v of Object.values(m)) if (v && v.isTexture && !v.userData?.shared) v.dispose();
      if (m.uniforms) for (const u of Object.values(m.uniforms)) if (u.value?.isTexture && !u.value.userData?.shared) u.value.dispose();
      m.dispose();
    }
  });
}

export function addPractical(set, color, intensity, dist, pos, { shadow = false, sodium = false } = {}) {
  const l = new THREE.PointLight(color, intensity, dist, 2);
  l.position.copy(pos);
  if (shadow) { l.castShadow = true; l.shadow.mapSize.set(512, 512); l.shadow.bias = -0.002; }
  set.group.add(l);
  l.userData.base = intensity;
  (sodium ? set.lights.sodium : set.lights.practicals).push(l);
  return l;
}

/** A sodium street lamp: pole, head, halo, cone, ground pool. */
export function streetLamp(set, x, z, { h = 7, arm = 1.6, dir = 1, color = 0xd99a3e, light = true, intensity = 30 } = {}) {
  const g = new THREE.Group();
  const metal = std(0x1d1e20, { roughness: 0.5, metalness: 0.6 });
  cyl(0.08, 0.12, h, 8, metal, 0, h / 2, 0, g);
  box(arm, 0.08, 0.08, metal, (arm / 2) * dir, h, 0, g);
  const head = box(0.5, 0.12, 0.26, metal, arm * dir, h - 0.05, 0, g);
  const bulb = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.03, 0.2), glow(color, 8));
  bulb.position.set(arm * dir, h - 0.12, 0);
  g.add(bulb);
  const hal = halo(color, 2.6, 1.1);
  hal.position.set(arm * dir, h - 0.2, 0);
  g.add(hal);
  const cone = lightCone(0.2, 2.8, h - 0.2, color, 0.16);
  cone.position.set(arm * dir, h - 0.12, 0);
  g.add(cone);
  const pool = lightPool(3.2, color, 0.35);
  pool.position.set(arm * dir, 0.02, 0);
  g.add(pool);
  g.position.set(x, 0, z);
  set.group.add(g);
  if (light) addPractical(set, color, intensity, 16, V(x + arm * dir, h - 0.4, z), { sodium: true });
  head.castShadow = false;
  g.userData = { bulb, hal, cone, pool };
  return g;
}

/** Floor with procedural PBR maps. */
export function floor(w, d, map, rough, { color = 0xffffff, roughness = 1, metalness = 0, env = 1, repeat = [4, 4] } = {}) {
  const m = std(color, { map: map?.clone(), roughnessMap: rough?.clone(), roughness, metalness, envMapIntensity: env });
  for (const t of [m.map, m.roughnessMap]) if (t) { t.repeat.set(...repeat); t.needsUpdate = true; }
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, d), m);
  mesh.rotation.x = -Math.PI / 2;
  mesh.receiveShadow = true;
  return mesh;
}

/** Inward-facing wall (invisible from outside, so cameras can sit beyond it). */
export function wall(w, h, material, pos, rotY) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), material);
  m.position.copy(pos);
  m.rotation.y = rotY;
  m.receiveShadow = true;
  return m;
}

export function tfeuBook(parent, x, y, z, rotY = 0, open = true) {
  const g = new THREE.Group();
  const cover = std(0x14264f, { roughness: 0.6 });
  const pages = std(0xe8e1cf, { roughness: 0.9 });
  if (open) {
    for (const s of [-1, 1]) {
      box(0.16, 0.012, 0.24, cover, 0.082 * s, 0, 0, g);
      const p = box(0.15, 0.02, 0.23, pages, 0.08 * s, 0.014, 0, g);
      p.material = new THREE.MeshStandardMaterial({ map: paperTex('', { highlight: s > 0, seed: 12 + s }), roughness: 0.9 });
    }
    const rib = new THREE.Mesh(new THREE.BoxGeometry(0.012, 0.003, 0.3), glow(0xffcc00, 1.6));
    rib.position.set(0.03, 0.027, 0.02);
    g.add(rib);
    const tabs = [0xb3372f, 0x3fb6b0, 0xd99a3e, 0x6f8f4a];
    tabs.forEach((c, i) => box(0.02, 0.004, 0.03, std(c), -0.165, 0.02, -0.08 + i * 0.05, g));
  } else {
    box(0.16, 0.04, 0.24, cover, 0, 0.02, 0, g);
    const lbl = new THREE.Mesh(new THREE.PlaneGeometry(0.1, 0.03), new THREE.MeshBasicMaterial({ map: textTex('TFEU', { color: '#ffcc00', size: 170 }), transparent: true }));
    lbl.rotation.x = -Math.PI / 2; lbl.position.y = 0.041;
    g.add(lbl);
  }
  g.position.set(x, y, z);
  g.rotation.y = rotY;
  parent.add(g);
  return g;
}

export function printout(parent, title, x, y, z, rotY = 0, seed = 3) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(0.21, 0.297), new THREE.MeshStandardMaterial({ map: paperTex(title, { seed }), roughness: 0.9 }));
  m.rotation.set(-Math.PI / 2, 0, rotY);
  m.position.set(x, y, z);
  m.receiveShadow = true;
  parent.add(m);
  for (let i = 1; i < 4; i++) {
    const s = m.clone();
    s.material = std(0xdcd5c2);
    s.position.y -= i * 0.002;
    s.rotation.z += (i % 2 ? 1 : -1) * 0.05 * i;
    parent.add(s);
  }
  return m;
}

export function deskLamp(set, parent, x, y, z, rotY = 0, color = 0xffb46b) {
  const g = new THREE.Group();
  const metal = std(0x1a1a1a, { roughness: 0.4, metalness: 0.7 });
  cyl(0.08, 0.09, 0.02, 12, metal, 0, 0.01, 0, g);
  const arm = cyl(0.01, 0.01, 0.42, 6, metal, 0, 0.22, -0.02, g);
  arm.rotation.x = 0.2;
  const shade = cyl(0.03, 0.09, 0.12, 12, std(0x1e3a2a, { roughness: 0.35, metalness: 0.4, side: THREE.DoubleSide }), 0, 0.42, 0.06, g, true);
  shade.rotation.x = 0.5;
  const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.025, 8, 6), glow(color, 10));
  bulb.position.set(0, 0.39, 0.09);
  g.add(bulb);
  g.position.set(x, y, z);
  g.rotation.y = rotY;
  parent.add(g);
  const spot = new THREE.SpotLight(color, 14, 6, Math.PI / 3, 0.5, 2);
  spot.position.set(x, y + 0.4, z);
  spot.target.position.set(x, y, z + 0.3);
  spot.castShadow = true;
  spot.shadow.mapSize.set(1024, 1024);
  spot.shadow.bias = -0.0015;
  set.group.add(spot, spot.target);
  spot.userData.base = 14;
  set.lights.practicals.push(spot);
  const pool = lightPool(0.9, color, 0.25);
  pool.position.set(x, y + 0.003, z + 0.25);
  parent.add(pool);
  return g;
}

export function chair(parent, x, y, z, rotY, m) {
  const g = new THREE.Group();
  box(0.46, 0.05, 0.46, m, 0, 0.46, 0, g);
  box(0.46, 0.5, 0.05, m, 0, 0.72, -0.21, g);
  for (const [a, b] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) box(0.04, 0.46, 0.04, m, 0.2 * a, 0.23, 0.2 * b, g);
  g.position.set(x, y, z);
  g.rotation.y = rotY;
  parent.add(g);
  return g;
}

/** Fluorescent tube with flicker. */
export function tube(set, parent, x, y, z, len = 1.4, rotY = 0, flicker = 0.02) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(len, 0.04, 0.08), glow(0xdfe8e0, 3));
  m.position.set(x, y, z);
  m.rotation.y = rotY;
  parent.add(m);
  const base = m.material.color.clone();
  let off = 0;
  set.updaters.push((t) => {
    if (off > 0) off -= 1 / 60;
    else if (Math.random() < flicker) off = Math.random() * 0.2;
    m.material.color.copy(base).multiplyScalar(off > 0 ? 0.15 : 1);
  });
  return m;
}

export function rimChar(m) { return rimify(m); }
