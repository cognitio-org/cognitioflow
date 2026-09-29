// lib3d.js: shared procedural building blocks (textures, materials, atmospheric effects).
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

export const PALETTE = {
  asphalt: 0x1c1d1f, smog: 0x6b6a62, sodium: 0xd99a3e, teal: 0x3fb6b0, red: 0xb3372f, paper: 0xe8e1cf, gold: 0xffcc00,
};

export function rng(seed = 1) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function hash(str) {
  let h = 2166136261;
  for (const ch of String(str)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return h >>> 0;
}

const FONT_HEAD = "'Oswald', 'Arial Narrow', sans-serif";
const FONT_BODY = "'IBM Plex Sans', 'Helvetica Neue', Arial, sans-serif";

export function canvasTex(w, h, draw, { repeat = [1, 1], srgb = true, aniso = 4 } = {}) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const g = c.getContext('2d');
  draw(g, w, h);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(repeat[0], repeat[1]);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = aniso;
  return t;
}

const cache = new Map();
function cached(key, make) {
  if (!cache.has(key)) cache.set(key, make());
  return cache.get(key);
}

function blotches(g, w, h, r, n, colors, alpha, rand) {
  for (let i = 0; i < n; i++) {
    const x = rand() * w, y = rand() * h, rad = r * (0.3 + rand());
    const grd = g.createRadialGradient(x, y, 0, x, y, rad);
    const col = colors[Math.floor(rand() * colors.length)];
    grd.addColorStop(0, `rgba(${col},${alpha * (0.4 + rand() * 0.6)})`);
    grd.addColorStop(1, `rgba(${col},0)`);
    g.fillStyle = grd;
    g.fillRect(x - rad, y - rad, rad * 2, rad * 2);
  }
}

function speckle(g, w, h, n, rand, a = 0.12) {
  for (let i = 0; i < n; i++) {
    const v = rand() > 0.5 ? 255 : 0;
    g.fillStyle = `rgba(${v},${v},${v},${a * rand()})`;
    g.fillRect(rand() * w, rand() * h, 1 + rand() * 2, 1 + rand() * 2);
  }
}

export function concreteTex(base = '#55544f', seed = 3, seams = 256) {
  return cached(`concrete${base}${seed}${seams}`, () => canvasTex(512, 512, (g, w, h) => {
    const r = rng(seed);
    g.fillStyle = base; g.fillRect(0, 0, w, h);
    blotches(g, w, h, 80, 60, ['0,0,0', '255,250,235', '40,45,30'], 0.12, r);
    speckle(g, w, h, 6000, r);
    g.strokeStyle = 'rgba(0,0,0,0.35)'; g.lineWidth = 2;
    for (let x = 0; x <= w; x += seams) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke(); }
    for (let y = 0; y <= h; y += seams) { g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke(); }
    g.strokeStyle = 'rgba(0,0,0,0.25)'; g.lineWidth = 1;
    for (let i = 0; i < 8; i++) {
      let x = r() * w, y = r() * h; g.beginPath(); g.moveTo(x, y);
      for (let k = 0; k < 8; k++) { x += (r() - 0.5) * 40; y += (r() - 0.5) * 40; g.lineTo(x, y); }
      g.stroke();
    }
  }));
}

/** Roughness map with glossy puddles (dark = wet). */
export function wetRoughTex(seed = 7, lift = 0) {
  return cached(`wet${seed}-${lift}`, () => canvasTex(512, 512, (g, w, h) => {
    const r = rng(seed);
    g.fillStyle = 'rgb(150,150,150)'; g.fillRect(0, 0, w, h);
    blotches(g, w, h, 90, 40, ['20,20,20'], 0.9, r);
    blotches(g, w, h, 40, 60, ['10,10,10'], 0.8, r);
    speckle(g, w, h, 4000, r, 0.3);
    // lift the glossiest puddles for scenes lit by a low sun, whose glint would otherwise blow out
    if (lift) { g.fillStyle = `rgba(150,150,150,${lift})`; g.fillRect(0, 0, w, h); }
  }, { srgb: false }));
}

export function asphaltTex(seed = 11) {
  return cached(`asphalt${seed}`, () => canvasTex(512, 512, (g, w, h) => {
    const r = rng(seed);
    g.fillStyle = '#26272a'; g.fillRect(0, 0, w, h);
    speckle(g, w, h, 16000, r, 0.18);
    blotches(g, w, h, 70, 40, ['0,0,0', '60,55,45'], 0.25, r);
    g.strokeStyle = 'rgba(10,10,10,0.6)'; g.lineWidth = 3;
    for (let i = 0; i < 5; i++) {
      let x = r() * w, y = r() * h; g.beginPath(); g.moveTo(x, y);
      for (let k = 0; k < 10; k++) { x += (r() - 0.5) * 50; y += r() * 30; g.lineTo(x, y); }
      g.stroke();
    }
  }));
}

export function brickTex(base = [92, 58, 46], seed = 5) {
  return cached(`brick${base}${seed}`, () => canvasTex(512, 512, (g, w, h) => {
    const r = rng(seed);
    g.fillStyle = '#2e2a26'; g.fillRect(0, 0, w, h);
    const bw = 64, bh = 24;
    for (let row = 0; row * bh < h; row++) {
      for (let col = -1; col * bw < w; col++) {
        const x = col * bw + (row % 2 ? bw / 2 : 0), y = row * bh;
        const v = 0.75 + r() * 0.35;
        g.fillStyle = `rgb(${base[0] * v | 0},${base[1] * v | 0},${base[2] * v | 0})`;
        g.fillRect(x + 2, y + 2, bw - 4, bh - 4);
      }
    }
    blotches(g, w, h, 90, 30, ['0,0,0', '30,30,20'], 0.35, r);
    speckle(g, w, h, 5000, r);
  }));
}

export function woodTex(base = [150, 112, 72], seed = 9) {
  return cached(`wood${base}${seed}`, () => canvasTex(512, 512, (g, w, h) => {
    const r = rng(seed);
    const pw = 128;
    for (let p = 0; p < w / pw; p++) {
      const v = 0.85 + r() * 0.25;
      g.fillStyle = `rgb(${base[0] * v | 0},${base[1] * v | 0},${base[2] * v | 0})`;
      g.fillRect(p * pw, 0, pw, h);
      for (let k = 0; k < 40; k++) {
        const x = p * pw + r() * pw, amp = 2 + r() * 4, ph = r() * 6;
        g.strokeStyle = `rgba(40,20,5,${0.05 + r() * 0.12})`; g.lineWidth = 0.5 + r() * 1.5;
        g.beginPath();
        for (let y = 0; y <= h; y += 16) g.lineTo(x + Math.sin(y / 60 + ph) * amp, y);
        g.stroke();
      }
      g.fillStyle = 'rgba(0,0,0,0.35)'; g.fillRect(p * pw, 0, 2, h);
    }
  }));
}

export function corrugatedTex(color = '#6a3a2c', seed = 13) {
  return cached(`corr${color}${seed}`, () => canvasTex(256, 256, (g, w, h) => {
    const r = rng(seed);
    g.fillStyle = color; g.fillRect(0, 0, w, h);
    for (let x = 0; x < w; x += 16) {
      const grd = g.createLinearGradient(x, 0, x + 16, 0);
      grd.addColorStop(0, 'rgba(0,0,0,0.35)'); grd.addColorStop(0.5, 'rgba(255,255,255,0.12)'); grd.addColorStop(1, 'rgba(0,0,0,0.35)');
      g.fillStyle = grd; g.fillRect(x, 0, 16, h);
    }
    blotches(g, w, h, 40, 30, ['60,30,10', '0,0,0'], 0.3, r);
    speckle(g, w, h, 2000, r);
  }));
}

/** Facade windows: returns {map, emissive}. */
export function facadeTex(seed, { cols = 6, rows = 10, lit = 0.25, wall = '#3a3632' } = {}) {
  return cached(`facade${seed}${cols}${rows}${lit}${wall}`, () => {
    const r = rng(seed);
    const cells = [];
    for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) {
      const on = r() < lit;
      cells.push({ x, y, on, warm: r() < 0.75, dim: 0.4 + r() * 0.6, blind: r() * 0.6 });
    }
    const W = 512, H = 1024, cw = W / cols, ch = H / rows;
    const map = canvasTex(W, H, (g) => {
      g.fillStyle = wall; g.fillRect(0, 0, W, H);
      blotches(g, W, H, 120, 40, ['0,0,0', '80,70,50'], 0.25, rng(seed + 1));
      speckle(g, W, H, 5000, rng(seed + 2));
      for (const c of cells) {
        g.fillStyle = '#121416';
        g.fillRect(c.x * cw + cw * 0.2, c.y * ch + ch * 0.18, cw * 0.6, ch * 0.62);
        g.fillStyle = 'rgba(160,170,180,0.12)';
        g.fillRect(c.x * cw + cw * 0.2, c.y * ch + ch * 0.18, cw * 0.6, 3);
      }
    });
    const emissive = canvasTex(W, H, (g) => {
      g.fillStyle = '#000'; g.fillRect(0, 0, W, H);
      for (const c of cells) {
        if (!c.on) continue;
        const col = c.warm ? [255, 170, 90] : [150, 210, 220];
        const x = c.x * cw + cw * 0.2, y = c.y * ch + ch * 0.18, ww = cw * 0.6, hh = ch * 0.62;
        const grd = g.createLinearGradient(x, y, x, y + hh);
        grd.addColorStop(0, `rgba(${col},${0.5 * c.dim})`); grd.addColorStop(1, `rgba(${col},${c.dim})`);
        g.fillStyle = grd; g.fillRect(x, y, ww, hh);
        g.fillStyle = 'rgba(0,0,0,0.7)'; g.fillRect(x, y, ww, hh * c.blind);
      }
    });
    return { map, emissive };
  });
}

export function glowSpriteTex() {
  return cached('glow', () => canvasTex(128, 128, (g, w, h) => {
    const grd = g.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
    grd.addColorStop(0, 'rgba(255,255,255,1)'); grd.addColorStop(0.25, 'rgba(255,255,255,0.45)');
    grd.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grd; g.fillRect(0, 0, w, h);
  }, { srgb: false }));
}

export function smokeTex() {
  return cached('smoke', () => canvasTex(256, 256, (g, w, h) => {
    const r = rng(21);
    for (let i = 0; i < 24; i++) {
      const x = w / 2 + (r() - 0.5) * w * 0.4, y = h / 2 + (r() - 0.5) * h * 0.4, rad = w * (0.15 + r() * 0.25);
      const grd = g.createRadialGradient(x, y, 0, x, y, rad);
      grd.addColorStop(0, 'rgba(255,255,255,0.18)'); grd.addColorStop(1, 'rgba(255,255,255,0)');
      g.fillStyle = grd; g.fillRect(0, 0, w, h);
    }
  }, { srgb: false }));
}

/** Text label texture. */
export function textTex(lines, { w = 1024, h = 256, bg = null, color = '#fff', font = 'head', size = 120, align = 'center', weight = 600, glow = 0, border = null } = {}) {
  return canvasTex(w, h, (g) => {
    if (bg) { g.fillStyle = bg; g.fillRect(0, 0, w, h); }
    if (border) { g.strokeStyle = border; g.lineWidth = 10; g.strokeRect(8, 8, w - 16, h - 16); }
    const arr = Array.isArray(lines) ? lines : [lines];
    g.textAlign = align; g.textBaseline = 'middle';
    arr.forEach((ln, i) => {
      const L = typeof ln === 'string' ? { t: ln } : ln;
      const sz = L.size || size;
      g.font = `${L.weight || weight} ${sz}px ${L.font === 'body' || font === 'body' ? FONT_BODY : FONT_HEAD}`;
      g.fillStyle = L.color || color;
      if (glow) { g.shadowColor = L.color || color; g.shadowBlur = glow; }
      const x = align === 'center' ? w / 2 : align === 'left' ? 40 : w - 40;
      const y = L.y != null ? L.y : h / 2 + (i - (arr.length - 1) / 2) * sz * 1.15;
      g.fillText(L.t, x, y);
    });
  }, { aniso: 8 });
}

export function paperTex(title, { highlight = true, seed = 4 } = {}) {
  return canvasTex(512, 724, (g, w, h) => {
    const r = rng(seed);
    g.fillStyle = '#e8e1cf'; g.fillRect(0, 0, w, h);
    g.fillStyle = '#222'; g.font = `600 22px ${FONT_BODY}`; g.fillText(title || '', 40, 60);
    for (let y = 100; y < h - 40; y += 18) {
      const len = 0.6 + r() * 0.35;
      if (highlight && r() < 0.14) { g.fillStyle = 'rgba(255,204,0,0.75)'; g.fillRect(36, y - 9, (w - 80) * len, 14); }
      g.fillStyle = 'rgba(30,30,30,0.55)'; g.fillRect(40, y - 3, (w - 80) * len, 5);
    }
  });
}

// ---------- materials ----------

export const RIM = { color: { value: new THREE.Color(0x9fb8c8) }, strength: { value: 0.35 } };

export function rimify(mat) {
  mat.onBeforeCompile = (sh) => {
    sh.uniforms.uRimColor = RIM.color;
    sh.uniforms.uRimStrength = RIM.strength;
    sh.fragmentShader = 'uniform vec3 uRimColor;\nuniform float uRimStrength;\n' + sh.fragmentShader.replace(
      '#include <emissivemap_fragment>',
      `#include <emissivemap_fragment>
       { float rimF = 1.0 - clamp(abs(dot(normalize(normal), normalize(vViewPosition))), 0.0, 1.0);
         totalEmissiveRadiance += uRimColor * uRimStrength * pow(rimF, 2.6); }`);
  };
  mat.customProgramCacheKey = () => 'rim1';
  return mat;
}

export function std(color, o = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.8, metalness: 0, ...o });
}

/** Emissive-only material with HDR intensity (feeds bloom). */
export function glow(color, intensity = 3, o = {}) {
  const c = new THREE.Color(color).multiplyScalar(intensity);
  return new THREE.MeshBasicMaterial({ color: c, ...o });
}

export function box(w, h, d, mat, x = 0, y = 0, z = 0, parent = null) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
  m.position.set(x, y, z);
  m.castShadow = true; m.receiveShadow = true;
  if (parent) parent.add(m);
  return m;
}

export function cyl(rt, rb, h, seg, mat, x = 0, y = 0, z = 0, parent = null, open = false) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg, 1, open), mat);
  m.position.set(x, y, z);
  m.castShadow = true; m.receiveShadow = true;
  if (parent) parent.add(m);
  return m;
}

// ---------- environment ----------

export function makeEnvMap(renderer) {
  const pm = new THREE.PMREMGenerator(renderer);
  const s = new THREE.Scene();
  const sky = new THREE.Mesh(new THREE.SphereGeometry(50, 32, 16), new THREE.ShaderMaterial({
    side: THREE.BackSide,
    uniforms: {},
    vertexShader: 'varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);} ',
    fragmentShader: `varying vec3 vP; void main(){
      float y = vP.y;
      vec3 top = vec3(0.05,0.055,0.06); vec3 hor = vec3(0.35,0.24,0.13); vec3 bot = vec3(0.02,0.02,0.02);
      vec3 c = y > 0.0 ? mix(hor, top, pow(y, 0.5)) : mix(hor*0.4, bot, pow(-y,0.4));
      gl_FragColor = vec4(c,1.0);} `,
  }));
  s.add(sky);
  const add = (color, i, x, y, z, w, h) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: new THREE.Color(color).multiplyScalar(i), side: THREE.DoubleSide }));
    m.position.set(x, y, z); m.lookAt(0, 0, 0); s.add(m);
  };
  add(0xd99a3e, 6, 10, 8, -20, 3, 3); add(0xd99a3e, 6, -12, 8, 10, 3, 3); add(0xd99a3e, 5, 0, 9, 25, 4, 2);
  add(0x3fb6b0, 5, -18, 4, -8, 6, 1.2); add(0xb3372f, 4, 18, 5, 6, 4, 1);
  add(0xcfd8e0, 2, 0, 30, 0, 30, 30);
  const rt = pm.fromScene(s, 0.02);
  pm.dispose();
  return rt.texture;
}

// ---------- atmospheric effects ----------

/** Additive volumetric-looking light cone, apex at the object origin, pointing down -Y. */
export function lightCone(rTop, rBottom, height, color, opacity = 0.2) {
  const geo = new THREE.CylinderGeometry(rTop, rBottom, height, 28, 8, true);
  geo.translate(0, -height / 2, 0);
  const mat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
    uniforms: { uColor: { value: new THREE.Color(color) }, uOpacity: { value: opacity } },
    vertexShader: `varying vec2 vUv; varying vec3 vN; varying vec3 vV; varying float vD;
      void main(){ vUv = uv; vec4 mv = modelViewMatrix*vec4(position,1.0); vD = -mv.z;
        vN = normalize(normalMatrix*normal); vV = normalize(-mv.xyz); gl_Position = projectionMatrix*mv; }`,
    fragmentShader: `uniform vec3 uColor; uniform float uOpacity; varying vec2 vUv; varying vec3 vN; varying vec3 vV; varying float vD;
      void main(){ float f = pow(abs(dot(vN, vV)), 1.6); float fall = pow(vUv.y, 1.4);
        float near = smoothstep(0.8, 5.0, vD);
        gl_FragColor = vec4(uColor * f * fall * near * uOpacity, 1.0); }`,
  });
  const m = new THREE.Mesh(geo, mat);
  m.renderOrder = 5;
  return m;
}

/** A slanted light shaft (sun through a window). */
export function lightShaft(w, h, len, color, opacity = 0.18) {
  const geo = new THREE.BoxGeometry(w, h, len, 1, 1, 8);
  geo.translate(0, 0, -len / 2);
  const mat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
    uniforms: { uColor: { value: new THREE.Color(color) }, uOpacity: { value: opacity }, uTime: { value: 0 } },
    vertexShader: `varying vec3 vL; varying vec3 vN; varying vec3 vV; varying float vD;
      void main(){ vL = position; vec4 mv = modelViewMatrix*vec4(position,1.0); vD = -mv.z;
        vN = normalize(normalMatrix*normal); vV = normalize(-mv.xyz); gl_Position = projectionMatrix*mv; }`,
    fragmentShader: `uniform vec3 uColor; uniform float uOpacity; uniform float uTime; uniform float uLen; varying vec3 vL; varying vec3 vN; varying vec3 vV; varying float vD;
      void main(){ float f = pow(abs(dot(vN, vV)), 1.2) * smoothstep(0.8, 4.0, vD);
        float along = clamp(-vL.z / ${len.toFixed(2)}, 0.0, 1.0);
        float fall = (1.0 - along) * smoothstep(0.0, 0.08, along);
        float dust = 0.85 + 0.15 * sin(vL.x * 9.0 + uTime * 0.7) * sin(vL.y * 7.0 - uTime * 0.5);
        gl_FragColor = vec4(uColor * f * fall * dust * uOpacity, 1.0); }`,
  });
  return new THREE.Mesh(geo, mat);
}

/** Soft additive pool of light on the ground. */
export function lightPool(radius, color, intensity = 0.6, stretch = 1) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(radius * 2, radius * 2 * stretch), new THREE.MeshBasicMaterial({
    map: glowSpriteTex(), color: new THREE.Color(color).multiplyScalar(intensity),
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  }));
  m.rotation.x = -Math.PI / 2;
  m.renderOrder = 2;
  return m;
}

/** Glow halo sprite (bloom helper). */
export function halo(color, size, intensity = 1.5) {
  const s = new THREE.Sprite(new THREE.SpriteMaterial({
    map: glowSpriteTex(), color: new THREE.Color(color).multiplyScalar(intensity),
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  }));
  s.scale.set(size, size, 1);
  s.renderOrder = 6;
  return s;
}

/** GPU rain streaks that wrap around the camera. */
export function makeRain(count = 3000, area = 30, height = 16) {
  const pos = new Float32Array(count * 6);
  const end = new Float32Array(count * 2);
  const r = rng(99);
  for (let i = 0; i < count; i++) {
    const x = (r() - 0.5) * area, y = r() * height, z = (r() - 0.5) * area;
    pos.set([x, y, z, x, y, z], i * 6);
    end[i * 2] = 0; end[i * 2 + 1] = 1;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('aEnd', new THREE.BufferAttribute(end, 1));
  const mat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: { value: 0 }, uCam: { value: new THREE.Vector3() }, uColor: { value: new THREE.Color(0.55, 0.52, 0.45) } },
    vertexShader: `uniform float uTime; uniform vec3 uCam; attribute float aEnd; varying float vA;
      void main(){ vec3 p = position;
        p.y = mod(p.y - uTime * 11.0, ${height.toFixed(1)});
        p.xz = mod(p.xz - uCam.xz + ${(area / 2).toFixed(1)}, ${area.toFixed(1)}) - ${(area / 2).toFixed(1)} + uCam.xz;
        p.y -= aEnd * 0.45; p.x += aEnd * 0.06;
        vA = 1.0 - aEnd * 0.8;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0); }`,
    fragmentShader: `uniform vec3 uColor; varying float vA; void main(){ gl_FragColor = vec4(uColor * vA * 0.24, 1.0); }`,
  });
  const lines = new THREE.LineSegments(geo, mat);
  lines.frustumCulled = false;
  lines.update = (t, cam) => { mat.uniforms.uTime.value = t; mat.uniforms.uCam.value.copy(cam.position); };
  return lines;
}

/** Rising steam / breath particles. */
export function makeSteam(count = 40, { spread = 0.5, rise = 3, size = 2.2, color = 0x9a958a, opacity = 0.35, speed = 0.3 } = {}) {
  const pos = new Float32Array(count * 3);
  const seed = new Float32Array(count);
  const r = rng(count * 7 + 3);
  for (let i = 0; i < count; i++) {
    pos.set([(r() - 0.5) * spread, 0, (r() - 0.5) * spread], i * 3);
    seed[i] = r();
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1));
  const mat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: { uTime: { value: 0 }, uMap: { value: smokeTex() }, uColor: { value: new THREE.Color(color) }, uOpacity: { value: opacity }, uScale: { value: 300 } },
    vertexShader: `uniform float uTime; uniform float uScale; attribute float aSeed; varying float vLife;
      void main(){ float life = fract(uTime * ${speed.toFixed(3)} + aSeed); vLife = life;
        vec3 p = position; p.y += life * ${rise.toFixed(2)}; p.x += sin(life * 3.0 + aSeed * 6.0) * 0.4 * life;
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_PointSize = uScale * ${size.toFixed(2)} * (0.3 + life) / -mv.z;
        gl_Position = projectionMatrix * mv; }`,
    fragmentShader: `uniform sampler2D uMap; uniform vec3 uColor; uniform float uOpacity; varying float vLife;
      void main(){ vec4 t = texture2D(uMap, gl_PointCoord); float a = t.a * uOpacity * sin(vLife * 3.14159);
        gl_FragColor = vec4(uColor, a); }`,
  });
  const pts = new THREE.Points(geo, mat);
  pts.frustumCulled = false;
  pts.renderOrder = 7;
  pts.update = (t) => { mat.uniforms.uTime.value = t; };
  return pts;
}

/** Drifting haze sprites around a region. */
export function makeHaze(n, region, color = 0x8f8676, opacity = 0.07, size = 14, seed = 31) {
  const g = new THREE.Group();
  const r = rng(seed);
  for (let i = 0; i < n; i++) {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: smokeTex(), color, transparent: true, opacity, depthWrite: false, fog: true }));
    s.position.set(region.x0 + r() * (region.x1 - region.x0), region.y0 + r() * (region.y1 - region.y0), region.z0 + r() * (region.z1 - region.z0));
    const k = size * (0.6 + r() * 0.8);
    s.scale.set(k, k * 0.5, 1);
    s.userData = { base: s.position.clone(), ph: r() * 6.28, sp: 0.05 + r() * 0.1 };
    s.renderOrder = 4;
    g.add(s);
  }
  g.update = (t) => {
    for (const s of g.children) {
      const u = s.userData;
      s.position.x = u.base.x + Math.sin(t * u.sp + u.ph) * 2;
      s.position.y = u.base.y + Math.sin(t * u.sp * 0.7 + u.ph) * 0.3;
    }
  };
  return g;
}

/** Neon sign: text plane plus halo and a subtle flicker. */
export function neonSign(text, color, { w = 3, h = 0.8, flicker = 0.02, seed = 1 } = {}) {
  const g = new THREE.Group();
  const tex = textTex(text, { w: 1024, h: 256, color: '#fff', size: 150, weight: 500, glow: 18 });
  const mat = new THREE.MeshBasicMaterial({ map: tex, color: new THREE.Color(color).multiplyScalar(2.6), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(w, h), mat);
  g.add(plane);
  const back = new THREE.Mesh(new THREE.PlaneGeometry(w * 1.05, h * 1.1), std(0x0c0c0e, { roughness: 0.6 }));
  back.position.z = -0.03;
  g.add(back);
  const hal = halo(color, w * 1.4, 0.35);
  hal.position.z = 0.1;
  g.add(hal);
  const r = rng(seed);
  const base = mat.color.clone();
  g.update = (t) => {
    const f = r() < flicker ? 0.25 : 1;
    mat.color.copy(base).multiplyScalar(f * (0.95 + Math.sin(t * 50 + seed) * 0.05));
  };
  return g;
}

// ---------- batching ----------

/**
 * Collects static geometry by material and merges it into one mesh per material, so a street of
 * detailed facades costs a few dozen draw calls rather than several hundred.
 */
export class Batcher {
  constructor() { this.groups = new Map(); this._m = new THREE.Matrix4(); this._q = new THREE.Quaternion(); this._e = new THREE.Euler(); }
  /** Add a geometry (consumed) with a transform. rot is [x,y,z] euler or a number for Y. */
  add(geo, mat, x = 0, y = 0, z = 0, rot = 0, scale = null) {
    const e = Array.isArray(rot) ? this._e.set(rot[0], rot[1], rot[2], rot[3] || 'XYZ') : this._e.set(0, rot, 0, 'XYZ');
    this._m.compose(new THREE.Vector3(x, y, z), this._q.setFromEuler(e), scale ? new THREE.Vector3(...scale) : new THREE.Vector3(1, 1, 1));
    const g = geo.index ? geo.toNonIndexed() : geo;
    g.applyMatrix4(this._m);
    for (const k of Object.keys(g.attributes)) if (!['position', 'normal', 'uv'].includes(k)) g.deleteAttribute(k);
    if (!g.attributes.uv) g.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(g.attributes.position.count * 2), 2));
    const entry = this.groups.get(mat) || { geos: [], shadow: true };
    entry.geos.push(g);
    this.groups.set(mat, entry);
    return g;
  }
  box(w, h, d, mat, x, y, z, rot = 0) { return this.add(new THREE.BoxGeometry(w, h, d), mat, x, y, z, rot); }
  cyl(rt, rb, h, seg, mat, x, y, z, rot = 0) { return this.add(new THREE.CylinderGeometry(rt, rb, h, seg), mat, x, y, z, rot); }
  /** A plane facing +Z (before rot) whose UVs are in world units / uvScale, for tiling facades. */
  plane(w, h, mat, x, y, z, rot = 0, uvScale = null, uvOff = [0, 0]) {
    const g = new THREE.PlaneGeometry(w, h);
    if (uvScale) {
      const uv = g.attributes.uv;
      for (let i = 0; i < uv.count; i++) uv.setXY(i, uvOff[0] + uv.getX(i) * w / uvScale[0], uvOff[1] + uv.getY(i) * h / uvScale[1]);
    }
    return this.add(g, mat, x, y, z, rot);
  }
  flush(parent, { castShadow = true, receiveShadow = true } = {}) {
    const out = [];
    for (const [mat, { geos }] of this.groups) {
      if (!geos.length) continue;
      const merged = mergeGeometries(geos, false);
      for (const g of geos) g.dispose();
      const m = new THREE.Mesh(merged, mat);
      m.castShadow = castShadow && !mat.isMeshBasicMaterial && !mat.transparent;
      m.receiveShadow = receiveShadow && !mat.isMeshBasicMaterial;
      parent.add(m);
      out.push(m);
    }
    this.groups.clear();
    return out;
  }
}

// ---------- sky ----------

/** Dusk sky dome: graded zenith-to-horizon, a warm city glow low down and slow cloud banks. */
export function skyDome({ zenith = 0x0f141b, mid = 0x28303a, horizon = 0x46433e, glow = 0x7a5a36, glowAmt = 0.6, clouds = 0.35, radius = 300, octaves = 4 } = {}) {
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: {
      uZ: { value: new THREE.Color(zenith) }, uM: { value: new THREE.Color(mid) }, uH: { value: new THREE.Color(horizon) },
      uG: { value: new THREE.Color(glow) }, uGA: { value: glowAmt }, uC: { value: clouds }, uTime: { value: 0 },
    },
    vertexShader: 'varying vec3 vP; void main(){ vP = normalize(position); vec4 p = projectionMatrix*modelViewMatrix*vec4(position,1.0); gl_Position = p.xyww; }',
    fragmentShader: `uniform vec3 uZ, uM, uH, uG; uniform float uGA, uC, uTime; varying vec3 vP;
      float h(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
      float n(vec2 p){ vec2 i = floor(p), f = fract(p); f = f*f*(3.0-2.0*f);
        return mix(mix(h(i), h(i+vec2(1,0)), f.x), mix(h(i+vec2(0,1)), h(i+vec2(1,1)), f.x), f.y); }
      float fbm(vec2 p){ float a = 0.5, s = 0.0; for (int i = 0; i < ${octaves}; i++){ s += a*n(p); p *= 2.03; a *= 0.5; } return s; }
      void main(){
        float y = vP.y;
        float t = clamp(y, 0.0, 1.0);
        vec3 c = mix(uH, uM, smoothstep(0.0, 0.18, t));
        c = mix(c, uZ, smoothstep(0.15, 0.75, t));
        c += uG * uGA * exp(-max(y, 0.0) * 9.0);
        vec2 q = vP.xz / max(0.12, y + 0.18) * 1.6 + vec2(uTime * 0.004, 0.0);
        float cl = smoothstep(0.45, 0.85, fbm(q));
        c = mix(c, c * 0.7 + uG * 0.10, cl * uC * smoothstep(0.02, 0.25, y));
        if (y < 0.0) c = uH * mix(1.0, 0.55, clamp(-y * 4.0, 0.0, 1.0));
        gl_FragColor = vec4(c, 1.0);
      }`,
  });
  const m = new THREE.Mesh(new THREE.SphereGeometry(radius, 32, 16), mat);
  m.renderOrder = -10;
  m.frustumCulled = false;
  m.update = (t, cam) => { mat.uniforms.uTime.value = t; if (cam) m.position.copy(cam.position); };
  return m;
}

// ---------- richer procedural surfaces ----------

/** Square paving slabs with worn joints and damp patches. */
export function pavingTex(seed = 41, base = [92, 90, 86]) {
  return cached(`paving${seed}${base}`, () => canvasTex(512, 512, (g, w, h) => {
    const r = rng(seed);
    g.fillStyle = '#26251f'; g.fillRect(0, 0, w, h);
    const n = 4, s = w / n;
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const v = 0.82 + r() * 0.3;
      g.fillStyle = `rgb(${base[0] * v | 0},${base[1] * v | 0},${base[2] * v | 0})`;
      g.fillRect(x * s + 3, y * s + 3, s - 6, s - 6);
    }
    blotches(g, w, h, 70, 40, ['20,18,14', '60,58,50'], 0.3, r);
    speckle(g, w, h, 7000, r, 0.14);
  }));
}

/** Dressed stone in coursed blocks (ashlar). */
export function ashlarTex(seed = 43, base = [150, 142, 126], courses = 8) {
  return cached(`ashlar${seed}${base}${courses}`, () => canvasTex(512, 512, (g, w, h) => {
    const r = rng(seed);
    const ch = h / courses;
    g.fillStyle = `rgb(${base[0] * 0.55 | 0},${base[1] * 0.55 | 0},${base[2] * 0.55 | 0})`; g.fillRect(0, 0, w, h);
    for (let row = 0; row < courses; row++) {
      let x = row % 2 ? -ch : 0;
      while (x < w) {
        const bw = ch * (1.6 + r() * 1.4);
        const v = 0.86 + r() * 0.2;
        g.fillStyle = `rgb(${base[0] * v | 0},${base[1] * v | 0},${base[2] * v | 0})`;
        g.fillRect(x + 2, row * ch + 2, bw - 4, ch - 4);
        g.fillStyle = 'rgba(255,255,255,0.08)'; g.fillRect(x + 2, row * ch + 2, bw - 4, 3);
        x += bw;
      }
    }
    blotches(g, w, h, 90, 30, ['30,28,22', '0,0,0'], 0.22, r);
    // rain streaks
    for (let i = 0; i < 40; i++) { g.fillStyle = `rgba(20,18,14,${0.05 + r() * 0.08})`; g.fillRect(r() * w, 0, 2 + r() * 4, h * (0.3 + r() * 0.7)); }
    speckle(g, w, h, 5000, r, 0.1);
  }));
}

const FACADES = [
  { wall: [98, 58, 44], brick: true, frame: '#d8cfbd', sill: '#b7ad98' },   // red brick, pale trim
  { wall: [120, 108, 90], brick: false, frame: '#3a332b', sill: '#8d8373' }, // buff render, dark frames
  { wall: [70, 66, 62], brick: false, frame: '#b9b2a4', sill: '#9a9386' },   // grey concrete
  { wall: [72, 48, 38], brick: true, frame: '#2b2622', sill: '#8a7c68' },   // dark brick
  { wall: [104, 92, 72], brick: false, frame: '#e2d9c6', sill: '#c7bda8' }, // sandstone
];

/**
 * Upper-floor facade tile: 8 bays x 8 floors, each bay 3 m wide and 3.2 m tall (so UV scale 24 x 25.6).
 * Returns {map, emissive}. Windows have reveals, sills, lintels and two-pane sashes; lit ones glow
 * warm behind half-drawn blinds, a few cool with television light.
 */
export function facadeTex2(variant = 0, seed = 1, lit = 0.28) {
  return cached(`facade2-${variant}-${seed}-${lit}`, () => {
    const F = FACADES[variant % FACADES.length];
    const r = rng(seed * 31 + variant);
    const cols = 8, rows = 8, W = 1024, H = 1024, cw = W / cols, ch = H / rows;
    const cells = [];
    for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) {
      cells.push({ x, y, on: r() < lit, warm: r() < 0.82, dim: 0.45 + r() * 0.55, blind: 0.1 + r() * 0.5, curtain: r() < 0.4 });
    }
    const win = (c) => ({ x: c.x * cw + cw * 0.27, y: c.y * ch + ch * 0.2, w: cw * 0.46, h: ch * 0.56 });
    const map = canvasTex(W, H, (g) => {
      const rr = rng(seed + 7);
      g.fillStyle = `rgb(${F.wall})`; g.fillRect(0, 0, W, H);
      if (F.brick) {
        const bh = 9, bw = 26;
        for (let row = 0; row * bh < H; row++) for (let col = -1; col * bw < W; col++) {
          const v = 0.8 + rr() * 0.32;
          g.fillStyle = `rgb(${F.wall[0] * v | 0},${F.wall[1] * v | 0},${F.wall[2] * v | 0})`;
          g.fillRect(col * bw + (row % 2 ? bw / 2 : 0) + 1, row * bh + 1, bw - 2, bh - 2);
        }
      }
      blotches(g, W, H, 140, 50, ['0,0,0', '60,55,45'], 0.22, rr);
      // floor bands
      for (let y = 0; y < rows; y++) { g.fillStyle = 'rgba(0,0,0,0.18)'; g.fillRect(0, y * ch + ch - 6, W, 6); }
      for (const c of cells) {
        const o = win(c);
        g.fillStyle = F.sill; g.fillRect(o.x - 8, o.y - 14, o.w + 16, 12);       // lintel
        g.fillStyle = F.sill; g.fillRect(o.x - 10, o.y + o.h, o.w + 20, 8);      // sill
        g.fillStyle = 'rgba(0,0,0,0.45)'; g.fillRect(o.x - 10, o.y + o.h + 8, o.w + 20, 6); // sill shadow
        g.fillStyle = F.frame; g.fillRect(o.x - 4, o.y - 2, o.w + 8, o.h + 4);
        // glass: dark, with a faint sky reflection at the top
        const grd = g.createLinearGradient(0, o.y, 0, o.y + o.h);
        grd.addColorStop(0, '#39414a'); grd.addColorStop(0.35, '#161a1f'); grd.addColorStop(1, '#0c0e10');
        g.fillStyle = grd; g.fillRect(o.x, o.y, o.w, o.h);
        g.fillStyle = 'rgba(0,0,0,0.55)'; g.fillRect(o.x, o.y, o.w, 6); g.fillRect(o.x, o.y, 5, o.h); // reveal shadow
        g.fillStyle = F.frame; g.fillRect(o.x + o.w / 2 - 2, o.y, 4, o.h); g.fillRect(o.x, o.y + o.h * 0.42, o.w, 4);
      }
    });
    const emissive = canvasTex(W, H, (g) => {
      g.fillStyle = '#000'; g.fillRect(0, 0, W, H);
      for (const c of cells) {
        if (!c.on) continue;
        const o = win(c);
        const col = c.warm ? [255, 176, 96] : [140, 190, 215];
        const grd = g.createRadialGradient(o.x + o.w / 2, o.y + o.h * 0.75, 2, o.x + o.w / 2, o.y + o.h * 0.6, o.h);
        grd.addColorStop(0, `rgba(${col},${c.dim})`); grd.addColorStop(1, `rgba(${col},${c.dim * 0.35})`);
        g.fillStyle = grd; g.fillRect(o.x, o.y, o.w, o.h);
        g.fillStyle = 'rgba(0,0,0,0.75)'; g.fillRect(o.x, o.y, o.w, o.h * c.blind);            // blind
        if (c.curtain) { g.fillStyle = 'rgba(0,0,0,0.5)'; g.fillRect(o.x, o.y, o.w * 0.18, o.h); g.fillRect(o.x + o.w * 0.82, o.y, o.w * 0.18, o.h); }
        g.fillStyle = '#000'; g.fillRect(o.x + o.w / 2 - 2, o.y, 4, o.h); g.fillRect(o.x, o.y + o.h * 0.42, o.w, 4);
      }
    });
    return { map, emissive };
  });
}

/** Shopfront: glazing with a lit interior, shelving silhouettes and a stall riser. {map, emissive}. */
export function shopTex(seed = 1, hue = [255, 196, 130]) {
  return cached(`shop${seed}${hue}`, () => {
    const r = rng(seed);
    const W = 512, H = 256;
    const shelves = [];
    for (let i = 0; i < 7; i++) shelves.push({ x: r() * W, w: 30 + r() * 80, h: 60 + r() * 90 });
    const map = canvasTex(W, H, (g) => {
      g.fillStyle = '#0d0f11'; g.fillRect(0, 0, W, H);
      g.fillStyle = '#26221d'; g.fillRect(0, H - 40, W, 40);
      g.fillStyle = '#1b1815'; for (const x of [0, W / 3, (2 * W) / 3, W - 8]) g.fillRect(x, 0, 8, H);
    });
    const emissive = canvasTex(W, H, (g) => {
      const grd = g.createLinearGradient(0, 0, 0, H);
      grd.addColorStop(0, `rgba(${hue},0.95)`); grd.addColorStop(0.7, `rgba(${hue},0.55)`); grd.addColorStop(1, 'rgba(0,0,0,1)');
      g.fillStyle = grd; g.fillRect(0, 0, W, H - 40);
      g.fillStyle = 'rgba(0,0,0,0.7)';
      for (const s of shelves) g.fillRect(s.x, H - 40 - s.h, s.w, s.h);
      g.fillStyle = 'rgba(0,0,0,0.85)'; for (const x of [0, W / 3, (2 * W) / 3, W - 8]) g.fillRect(x, 0, 8, H);
      g.fillRect(0, H - 40, W, 40);
    });
    return { map, emissive };
  });
}

/** Raised-and-fielded oak panelling: 2 x 1 panels per tile. */
export function panelTex(base = [120, 84, 52], seed = 51) {
  return cached(`panel${base}${seed}`, () => canvasTex(512, 512, (g, w, h) => {
    const wood = woodTex(base, seed).image;
    g.drawImage(wood, 0, 0, w, h);
    const px = 30, py = 34;
    for (let i = 0; i < 2; i++) {
      const x = i * (w / 2) + px, y = py, pw = w / 2 - px * 2, ph = h - py * 2;
      // bevel: light top/left, dark bottom/right
      g.fillStyle = 'rgba(0,0,0,0.45)'; g.fillRect(x - 6, y - 6, pw + 12, ph + 12);
      g.drawImage(wood, x, y, pw, ph, x, y, pw, ph);
      g.fillStyle = 'rgba(255,230,190,0.14)'; g.fillRect(x, y, pw, 8); g.fillRect(x, y, 8, ph);
      g.fillStyle = 'rgba(0,0,0,0.3)'; g.fillRect(x, y + ph - 8, pw, 8); g.fillRect(x + pw - 8, y, 8, ph);
      const fx = x + 26, fy = y + 26, fw = pw - 52, fh = ph - 52;
      g.fillStyle = 'rgba(0,0,0,0.22)'; g.fillRect(fx, fy + fh - 4, fw, 4); g.fillRect(fx + fw - 4, fy, 4, fh);
      g.fillStyle = 'rgba(255,230,190,0.1)'; g.fillRect(fx, fy, fw, 4); g.fillRect(fx, fy, 4, fh);
    }
  }));
}

/** Narrow oak floorboards with staggered butt joints (8 boards across a tile). */
export function parquetTex(base = [128, 92, 60], seed = 53) {
  return cached(`boards${base}${seed}`, () => canvasTex(512, 512, (g, w, h) => {
    const r = rng(seed);
    const wood = woodTex(base, seed).image;
    const bw = w / 8;
    for (let i = 0; i < 8; i++) {
      let y = -r() * h;
      while (y < h) {
        const len = h * (0.45 + r() * 0.5);
        const v = 0.8 + r() * 0.3;
        g.filter = `brightness(${v})`;
        g.drawImage(wood, (r() * 3 | 0) * bw, 0, bw, h, i * bw, y, bw, len);
        g.filter = 'none';
        g.fillStyle = 'rgba(20,10,4,0.7)'; g.fillRect(i * bw, y, bw, 2);
        y += len;
      }
      g.fillStyle = 'rgba(20,10,4,0.6)'; g.fillRect(i * bw, 0, 2, h);
    }
    blotches(g, w, h, 90, 20, ['0,0,0', '255,220,170'], 0.06, r);
  }));
}

/** Warm limewash plaster. */
export function plasterTex(base = '#b7ab96', seed = 55) {
  return cached(`plaster${base}${seed}`, () => canvasTex(512, 512, (g, w, h) => {
    const r = rng(seed);
    g.fillStyle = base; g.fillRect(0, 0, w, h);
    blotches(g, w, h, 120, 60, ['255,248,230', '80,70,55'], 0.1, r);
    speckle(g, w, h, 3000, r, 0.06);
  }));
}

/** Low-pile carpet with a border. */
export function carpetTex(base = [92, 30, 30], border = [150, 118, 60]) {
  return cached(`carpet${base}${border}`, () => canvasTex(256, 512, (g, w, h) => {
    const r = rng(57);
    g.fillStyle = `rgb(${base})`; g.fillRect(0, 0, w, h);
    speckle(g, w, h, 9000, r, 0.12);
    g.strokeStyle = `rgb(${border})`; g.lineWidth = 6;
    g.beginPath(); g.moveTo(18, 0); g.lineTo(18, h); g.moveTo(w - 18, 0); g.lineTo(w - 18, h); g.stroke();
    g.lineWidth = 2; g.beginPath(); g.moveTo(30, 0); g.lineTo(30, h); g.moveTo(w - 30, 0); g.lineTo(w - 30, h); g.stroke();
  }));
}
