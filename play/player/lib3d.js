// lib3d.js: shared procedural building blocks (textures, materials, atmospheric effects).
import * as THREE from 'three';

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
export function wetRoughTex(seed = 7) {
  return cached(`wet${seed}`, () => canvasTex(512, 512, (g, w, h) => {
    const r = rng(seed);
    g.fillStyle = 'rgb(150,150,150)'; g.fillRect(0, 0, w, h);
    blotches(g, w, h, 90, 40, ['20,20,20'], 0.9, r);
    blotches(g, w, h, 40, 60, ['10,10,10'], 0.8, r);
    speckle(g, w, h, 4000, r, 0.3);
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
    vertexShader: `varying vec2 vUv; varying vec3 vN; varying vec3 vV;
      void main(){ vUv = uv; vec4 mv = modelViewMatrix*vec4(position,1.0);
        vN = normalize(normalMatrix*normal); vV = normalize(-mv.xyz); gl_Position = projectionMatrix*mv; }`,
    fragmentShader: `uniform vec3 uColor; uniform float uOpacity; varying vec2 vUv; varying vec3 vN; varying vec3 vV;
      void main(){ float f = pow(abs(dot(vN, vV)), 1.6); float fall = pow(vUv.y, 1.4);
        gl_FragColor = vec4(uColor * f * fall * uOpacity, 1.0); }`,
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
    vertexShader: `varying vec3 vL; varying vec3 vN; varying vec3 vV;
      void main(){ vL = position; vec4 mv = modelViewMatrix*vec4(position,1.0);
        vN = normalize(normalMatrix*normal); vV = normalize(-mv.xyz); gl_Position = projectionMatrix*mv; }`,
    fragmentShader: `uniform vec3 uColor; uniform float uOpacity; uniform float uTime; uniform float uLen; varying vec3 vL; varying vec3 vN; varying vec3 vV;
      void main(){ float f = pow(abs(dot(vN, vV)), 1.2);
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
    fragmentShader: `uniform vec3 uColor; varying float vA; void main(){ gl_FragColor = vec4(uColor * vA * 0.35, 1.0); }`,
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
