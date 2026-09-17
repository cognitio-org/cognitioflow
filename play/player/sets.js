// sets.js: set registry, Blender glTF overrides, and casting characters into a set.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { findAsset } from './data.js';
import { makeRain, makeHaze } from './lib3d.js';
import { makeSetBase, V } from './setkit.js';
import { buildStreet, buildCustomsYard } from './exteriors.js';
import { buildOffice, buildCourtroom, buildClassroom, buildParliament, buildGeneric } from './interiors.js';
import { buildTvStudio } from './studio.js';
import { profileFor, makeCharacter } from './human.js';

export const SET_KINDS = ['customs_yard', 'office', 'courtroom', 'street', 'classroom', 'parliament', 'generic', 'tv_studio'];

const BUILDERS = {
  tv_studio: buildTvStudio,
  customs_yard: buildCustomsYard,
  office: buildOffice,
  courtroom: buildCourtroom,
  classroom: buildClassroom,
  parliament: buildParliament,
  generic: buildGeneric,
};

let loader = null;
function gltfLoader() {
  if (!loader) {
    loader = new GLTFLoader();
    loader.setMeshoptDecoder(MeshoptDecoder);
  }
  return loader;
}

/** Load games/assets/<kind>/<name>.glb if it exists; resolves null otherwise. */
export async function loadAsset(kind, name) {
  const url = await findAsset(kind, name);
  if (!url) return null;
  return gltfLoader().loadAsync(url);
}

/** Wrap a Blender set: use its empties for spawn, door, camera anchors and marks. */
function gltfSet(kind, gltf, q, destKind) {
  const interior = kind !== 'street' && kind !== 'customs_yard';
  const set = makeSetBase(kind, { interior, fog: kind === 'street' ? 0x4a4238 : 0x2a2620, density: interior ? 0.025 : 0.028 });
  const root = gltf.scene;
  root.traverse((o) => {
    if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; }
    if (o.isLight) { o.castShadow = q.quality !== 'low' && (o.isSpotLight || o.isDirectionalLight); set.lights.practicals.push(o); o.userData.base = o.intensity; }
  });
  set.group.add(root);
  set.group.updateMatrixWorld(true);
  const tmp = new THREE.Vector3();
  const q4 = new THREE.Quaternion();
  root.traverse((o) => {
    const n = o.name || '';
    if (!/^(spawn_|door_trigger|cam_|mark_)/i.test(n)) return;
    o.getWorldPosition(tmp);
    o.getWorldQuaternion(q4);
    const fwd = new THREE.Vector3(0, 0, 1).applyQuaternion(q4);
    const rotY = Math.atan2(fwd.x, fwd.z);
    if (/^spawn_lawyer/i.test(n)) set.spawn = { pos: tmp.clone(), rotY };
    else if (/^door_trigger/i.test(n)) set.door = tmp.clone();
    else if (/^cam_/i.test(n)) {
      // Blender cameras/empties look down their local -Z.
      const look = new THREE.Vector3(0, 0, -1).applyQuaternion(q4);
      set.anchors[n.toLowerCase()] = { pos: tmp.clone(), facing: look, h: 1, camera: true };
      const word = n.slice(4).toLowerCase().replace(/[._\d]+$/, '');
      if (word) set.kw(new RegExp(word.replace(/_/g, '[ _-]?'), 'i'), n.toLowerCase());
    } else if (/^mark_/i.test(n)) {
      const role = n.slice(5).toLowerCase().replace(/[._\d]+$/, '');
      set.slot(role === 'lawyer' ? 'player' : role, tmp.clone(), rotY);
    }
  });
  if (gltf.animations?.length) {
    const mixer = new THREE.AnimationMixer(root);
    for (const c of gltf.animations) mixer.clipAction(c).play();
    set.updaters.push((t, dt) => mixer.update(dt));
  }
  const bb = new THREE.Box3().setFromObject(root);
  bb.getCenter(set.center);
  set.center.y = Math.min(set.center.y, bb.min.y + 1.4);
  // fallback lighting if the export has none
  if (!set.lights.practicals.length) {
    const key = new THREE.DirectionalLight(0xffe0b8, 1.2);
    key.position.set(6, 10, 6);
    key.castShadow = q.quality !== 'low';
    set.group.add(key);
    set.lights.key = key;
  }
  if (kind === 'street') {
    if (!q.reduced) {
      const rain = makeRain(q.quality === 'low' ? 1500 : 4000);
      set.group.add(rain);
      set.updaters.push((t, dt, cam) => rain.update(t, cam));
    }
    set.spawn ||= { pos: V(0, 0, bb.max.z - 2), rotY: Math.PI };
    set.door ||= V(0, 0, bb.min.z + 3);
    set.walkBounds = { x0: bb.min.x + 1, x1: bb.max.x - 1, z0: Math.min(set.door.z, set.spawn.pos.z) - 0.5, z1: Math.max(set.door.z, set.spawn.pos.z) + 3 };
    set.destination = { label: '', sub: '' };
  }
  const haze = makeHaze(8, { x0: bb.min.x, x1: bb.max.x, y0: bb.min.y + 1, y1: bb.min.y + 5, z0: bb.min.z, z1: bb.max.z }, 0x8a7a62, 0.05, 12);
  set.group.add(haze);
  set.updaters.push((t) => haze.update(t));
  // default marks around the centre if the export has none
  const c = set.center;
  const def = [['player', 1, 1.5, Math.PI], ['client', -1, 1.2, Math.PI], ['judge', 0, -2.5, 0], ['counsel', -2, -0.5, Math.PI / 2], ['clerk', 2, -0.5, -Math.PI / 2], ['official', -2.5, 1.5, 2], ['extra', 2.5, 1.5, -2]];
  for (const [role, x, z, ry] of def) if (!set.slots[role]) set.slot(role, V(c.x + x, bb.min.y, c.z + z), ry);
  set.anchor('room', c.clone(), V(0, 0, 1), Math.max(4, bb.max.x - bb.min.x));
  set.glb = true;
  return set;
}

/** Build a set: the Blender export when present, else the procedural one. */
export async function loadSet(kind, q = {}) {
  const k = SET_KINDS.includes(kind) ? kind : 'generic';
  try {
    const gltf = await loadAsset('sets', k);
    if (gltf) return gltfSet(k, gltf, q, q.destKind);
  } catch (err) {
    console.warn(`[sets] ${k}.glb failed, using procedural`, err);
  }
  if (k === 'street') return buildStreet(q.destKind || 'courtroom', q);
  return BUILDERS[k](q);
}

/**
 * Place characters for a scene. `cast` is [{key, speaker}]; returns Map key -> character.
 * Roles come from the roster (trainee = player); each role takes the next free slot of that role, then 'extra'.
 */
export async function castSet(set, cast) {
  const used = {};
  const out = new Map();
  const take = (role) => {
    const list = set.slots[role] || [];
    const i = used[role] || 0;
    if (i < list.length) { used[role] = i + 1; return list[i]; }
    return null;
  };
  for (const c of cast) {
    const prof = profileFor(c.key, c.speaker);
    if (c.key === 'trainee') { prof.role = 'player'; prof.briefcase = true; }
    const slot = take(prof.role) || take('extra') || take('client') || take('counsel') || { pos: set.center.clone().add(V(out.size * 0.9 - 1.5, -set.center.y, 2)), rotY: Math.PI, pose: 'stand' };
    const ch = await makeCharacter(prof, loadAsset);
    ch.root.position.copy(slot.pos);
    ch.root.rotation.y = slot.rotY || 0;
    ch.setPose(slot.pose || 'stand');
    if (ch.briefcase && slot.pose && slot.pose !== 'stand') {
      // put the briefcase down beside a seated or leaning lawyer
      const bc = ch.briefcase;
      bc.parent.remove(bc);
      bc.position.set(0.45, 0.35, 0.1);
      bc.rotation.set(0, 0.3, 0);
      ch.root.add(bc);
    }
    ch.key = c.key;
    ch.speaker = c.speaker;
    set.group.add(ch.root);
    out.set(c.key, ch);
  }
  return out;
}
