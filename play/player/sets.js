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

// Blender writes glTF lights in physical units - candela for point and spot, lux for
// directional - and GLTFLoader.js:607 assigns them straight through, unconverted. The rest
// of this app was hand-tuned on a different scale entirely: interiors.js and studio.js set
// their practicals between 6 and 60 against ACESFilmic tone mapping at exposure 1. The
// courtroom's ceiling spot exports at 228,000 candela. Dropped in as-is, that is a white
// screen, so a set with real lights would look worse than one with none.
//
// Blender's own conversion is candela = watts * 683 / 4pi, and lux = watts * 683, so
// dividing by it recovers the wattage the set was authored at. The two gains after that are
// calibration, not physics: they put a 4200 W ceiling spot at 60, which is where studio.js
// puts its key by hand, and a 1.4 W/m2 sun at 1.2, which is what the fallback below used.
// Decay matches too - GLTFLoader sets decay 2, and so does addPractical in setkit.js.
const LUMENS_PER_WATT = 683;
const CD_PER_WATT = LUMENS_PER_WATT / (4 * Math.PI);
const GAIN_PUNCTUAL = 60 / 4200;
const GAIN_SUN = 1.2 / 1.4;

/** glTF's physical intensity in the scale the hand-built sets use. */
function appIntensity(light) {
  if (light.isDirectionalLight) return (light.intensity / LUMENS_PER_WATT) * GAIN_SUN;
  return (light.intensity / CD_PER_WATT) * GAIN_PUNCTUAL;
}

/** Which way a Blender empty points, in world space.
 *
 * Blender empties look down their local -Z, so this used to read local -Z (and, for marks,
 * local +Z). It does not survive the export. Blender's glTF exporter does not put the +Y-up
 * conversion on a root node - the loaded scene's root quaternion is identity - it bakes a
 * +90 degrees X rotation into every node's own rotation. An empty left unrotated in Blender
 * therefore arrives as quaternion (0.707, 0, 0, 0.707), and its Blender -Z has become the
 * node's local -Y.
 *
 * Reading -Z instead returned world +Y for an unrotated empty, so every cam_* anchor in the
 * courtroom resolved to "straight up" and every mark_* to rotY 0. The markers were all
 * present and the set loaded clean, which is why this survived: the shots were framed on the
 * ceiling and nobody had aimed the empties, so the two wrongs looked like one plain room.
 */
function facing(q) {
  return new THREE.Vector3(0, -1, 0).applyQuaternion(q);
}

/** Wrap a Blender set: use its empties for spawn, door, camera anchors and marks. */
function gltfSet(kind, gltf, q, destKind) {
  const interior = kind !== 'street' && kind !== 'customs_yard';
  const set = makeSetBase(kind, { interior, fog: kind === 'street' ? 0x4a4238 : 0x2a2620, density: interior ? 0.025 : 0.028 });
  const root = gltf.scene;
  root.traverse((o) => {
    if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; }
    if (o.isLight) {
      o.castShadow = q.quality !== 'low' && (o.isSpotLight || o.isDirectionalLight);
      o.intensity = appIntensity(o);
      o.userData.base = o.intensity;
      set.lights.practicals.push(o);
    }
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
    const fwd = facing(q4);
    const rotY = Math.atan2(fwd.x, fwd.z);
    if (/^spawn_lawyer/i.test(n)) set.spawn = { pos: tmp.clone(), rotY };
    else if (/^door_trigger/i.test(n)) set.door = tmp.clone();
    else if (/^cam_/i.test(n)) {
      set.anchors[n.toLowerCase()] = { pos: tmp.clone(), facing: fwd.clone(), h: 1, camera: true };
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
  // A DirectionalLight's shadow camera is orthographic and defaults to a 10x10 box. This
  // room is 25 m by 18 m, so almost none of it was inside the frustum - and geometry outside
  // a shadow frustum is not unlit, it is unshadowed, so the sun shone straight through the
  // walls and left a hard bright wedge across them. Fit the frustum to the set instead.
  // Near goes negative because a Blender set's sun usually sits inside the room.
  const radius = bb.getSize(new THREE.Vector3()).length() / 2;
  const mapSize = q.quality === 'high' ? 2048 : 1024;
  for (const l of set.lights.practicals) {
    if (!l.castShadow) continue;
    l.shadow.mapSize.set(mapSize, mapSize);
    // GLTFLoader leaves bias at 0, which on surfaces this large self-shadows into a mottled
    // checker across the floor and walls. normalBias is what actually clears it; bias alone
    // just trades the speckle for peter-panning at the skirtings.
    l.shadow.bias = -0.0008;
    l.shadow.normalBias = 0.035;
    if (!l.isDirectionalLight) continue;
    const c = l.shadow.camera;
    c.left = -radius; c.right = radius; c.top = radius; c.bottom = -radius;
    c.near = -radius * 2; c.far = radius * 4;
    c.updateProjectionMatrix();
  }

  // Hand the mood system something to hold on to. Without this every imported light is an
  // anonymous practical, so stage.js can only dim them all together and the key/fill/sun
  // curves in applyMood do nothing on a Blender set.
  set.lights.sun = set.lights.practicals.find((l) => l.isDirectionalLight) || null;
  const spots = set.lights.practicals.filter((l) => l.isSpotLight);
  set.lights.key = spots.sort((a, b) => b.userData.base - a.userData.base)[0] || null;
  set.lights.fill = set.lights.practicals.find((l) => l.isPointLight) || null;

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
