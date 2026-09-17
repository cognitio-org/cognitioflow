// post.js: post-processing. Bloom, a late-2000s crime-drama grade, film grain, vignette, chromatic aberration, ACES.
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';

// Display-referred grade applied after tone mapping (acts like a LUT).
const GradeShader = {
  uniforms: {
    tDiffuse: { value: null },
    uTime: { value: 0 },
    uSat: { value: 0.62 },
    uTint: { value: new THREE.Color(1.05, 0.98, 0.86) },
    uShadowTint: { value: new THREE.Color(0.98, 1.03, 0.9) },
    uLift: { value: 0.035 },
    uContrast: { value: 1.06 },
    uGrain: { value: 0.055 },
    uVignette: { value: 0.95 },
    uCA: { value: 0.0016 },
    uSepia: { value: 0 },
    uDesat: { value: 0 },
    uFade: { value: 0 },
    uAspect: { value: 1.6 },
    uBand: { value: 1.0 },
  },
  vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: `
    uniform sampler2D tDiffuse; uniform float uTime, uSat, uLift, uContrast, uGrain, uVignette, uCA, uSepia, uDesat, uFade, uAspect, uBand;
    uniform vec3 uTint, uShadowTint;
    varying vec2 vUv;
    float hash(vec2 p){ p = fract(p * vec2(443.897, 441.423)); p += dot(p, p.yx + 19.19); return fract((p.x + p.y) * p.x); }
    void main(){
      vec2 c = vUv - 0.5;
      float r2 = dot(c * vec2(uAspect / 1.6, 1.0), c * vec2(uAspect / 1.6, 1.0));
      vec2 off = c * r2 * uCA * 6.0;
      vec3 col;
      col.r = texture2D(tDiffuse, vUv - off).r;
      col.g = texture2D(tDiffuse, vUv).g;
      col.b = texture2D(tDiffuse, vUv + off).b;
      float l = dot(col, vec3(0.2126, 0.7152, 0.0722));
      // saturation, then split-tone: green-yellow cast in shadows, warm sodium-amber overall
      col = mix(vec3(l), col, uSat * (1.0 - uDesat));
      col = mix(col * uShadowTint, col, smoothstep(0.0, 0.45, l));
      col *= uTint;
      // contrast around mid grey and lifted blacks, soft highlights
      col = (col - 0.45) * uContrast + 0.45;
      col = uLift + col * (1.0 - uLift);
      col = col / (1.0 + max(col - 0.85, 0.0) * 0.6);
      // flashback sepia
      vec3 sep = vec3(l) * vec3(1.07, 0.92, 0.72);
      col = mix(col, sep, uSepia);
      // vignette
      float v = smoothstep(0.85, 0.2, length(c * vec2(1.0, 0.85)) * uVignette * 1.1);
      col *= mix(0.45, 1.0, v);
      // grain (luma weighted, animated)
      float g = hash(vUv * vec2(1920.0, 1080.0) + fract(uTime * 13.7) * 91.0) - 0.5;
      col += g * uGrain * (0.6 + 0.8 * (1.0 - l));
      col *= 1.0 - uFade;
      gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
    }`,
};

export class Post {
  constructor(renderer, scene, camera) {
    this.renderer = renderer;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    const size = renderer.getSize(new THREE.Vector2());
    const rt = new THREE.WebGLRenderTarget(size.x, size.y, { type: THREE.HalfFloatType, samples: 0 });
    this.composer = new EffectComposer(renderer, rt);
    this.renderPass = new RenderPass(scene, camera);
    this.bloom = new UnrealBloomPass(new THREE.Vector2(size.x, size.y), 0.85, 0.72, 0.78);
    this.output = new OutputPass();
    this.grade = new ShaderPass(GradeShader);
    this.composer.addPass(this.renderPass);
    this.composer.addPass(this.bloom);
    this.composer.addPass(this.output);
    this.composer.addPass(this.grade);
    this.u = this.grade.uniforms;
    this.target = { desat: 0, sepia: 0, fade: 0, exposure: 1 };
    this.quality = 'high';
    this.reduced = false;
  }

  setScene(scene, camera) {
    this.renderPass.scene = scene;
    this.renderPass.camera = camera;
  }

  setQuality(q) {
    this.quality = q;
    const low = q === 'low';
    this.bloom.strength = low ? 0.7 : 0.85;
    this.u.uCA.value = low ? 0 : 0.0016;
    this.applyGrain();
  }

  setReduced(r) { this.reduced = r; this.applyGrain(); }
  applyGrain() { this.u.uGrain.value = this.reduced ? 0 : this.quality === 'low' ? 0.04 : 0.055; }

  setSize(w, h, pr) {
    this.composer.setPixelRatio(pr);
    this.composer.setSize(w, h);
    this.u.uAspect.value = w / Math.max(1, h);
  }

  render(dt, t) {
    const u = this.u;
    const k = 1 - Math.exp(-dt * 3);
    u.uDesat.value += (this.target.desat - u.uDesat.value) * k;
    u.uSepia.value += (this.target.sepia - u.uSepia.value) * k;
    u.uFade.value += (this.target.fade - u.uFade.value) * (1 - Math.exp(-dt * 5));
    this.renderer.toneMappingExposure += (this.target.exposure - this.renderer.toneMappingExposure) * k;
    u.uTime.value = t;
    this.composer.render(dt);
  }
}
