// audio.js: original 8-bit courtroom-drama score synthesised live (pulse lead, triangle bass, noise drums),
// stings, rain/traffic/room ambience, and the speechSynthesis "Read aloud" hook.

const NOTE = (() => {
  const names = { C: 0, 'C#': 1, Db: 1, D: 2, 'D#': 3, Eb: 3, E: 4, F: 5, 'F#': 6, Gb: 6, G: 7, 'G#': 8, Ab: 8, A: 9, 'A#': 10, Bb: 10, B: 11 };
  return (n) => {
    if (n == null || n === '.' || n === '-') return null;
    const m = /^([A-G][#b]?)(-?\d)$/.exec(n);
    if (!m) return null;
    const midi = (parseInt(m[2], 10) + 1) * 12 + names[m[1]];
    return 440 * Math.pow(2, (midi - 69) / 12);
  };
})();

const seq = (s) => s.trim().split(/\s+/);

// Cues. Each track is a list of steps (16th notes unless noted); '.' is a rest, '-' holds the previous note.
const CUES = {
  arrival: {
    bpm: 90, steps: 32,
    bass: seq('A1 . A1 . C2 . A1 . G1 . G1 . E1 . G1 . A1 . A1 . C2 . D2 . E2 . D2 . C2 . G1 .'),
    lead: seq('. . . . . . . . E4 - - - - - - - . . . . . . . . D4 - - - C4 - B3 -'),
    leadDuty: 0.125, leadVol: 0.05,
    kick: '1.......1..1....1.......1..1....',
    hat: '..x...x...x...x...x...x...x...x.',
    snare: '....x.......x.......x.......x...',
  },
  briefing: {
    bpm: 100, steps: 32,
    bass: seq('A1 - - - - - - - F1 - - - - - - - C2 - - - - - - - G1 - - - - - - -'),
    lead: seq('A3 C4 E4 A4 E4 C4 A3 C4 F3 A3 C4 F4 C4 A3 F3 A3 C3 E3 G3 C4 G3 E3 C3 E3 G3 B3 D4 G4 D4 B3 G3 B3'),
    leadDuty: 0.25, leadVol: 0.028,
    kick: '................................',
    hat: '................................',
    snare: '................................',
  },
  examination: {
    bpm: 112, steps: 32,
    bass: seq('A1 A1 . A1 A1 . A1 . Bb1 Bb1 . Bb1 Bb1 . Bb1 . B1 B1 . B1 B1 . B1 . C2 C2 . C2 D2 . E2 .'),
    lead: seq('E5 . F5 . E5 . F5 . E5 . F5 . E5 . F5 . F5 . F#5 . F5 . F#5 . G5 . G#5 . A5 . . .'),
    leadDuty: 0.125, leadVol: 0.022,
    kick: '1.......1.......1.......1...1...',
    hat: 'x.x.x.x.x.x.x.x.x.x.x.x.x.x.x.x.',
    snare: '................................',
  },
  verdict_won: {
    bpm: 132, steps: 16, once: true,
    bass: seq('C2 . C2 . G1 . G1 . C2 - - - - - - -'),
    lead: seq('G4 C5 E5 G5 - . E5 G5 C6 - - - - - - -'),
    leadDuty: 0.25, leadVol: 0.06,
    kick: '1...1...1.......', hat: '..x...x.........', snare: '....x...x.......',
  },
  verdict_lost: {
    bpm: 72, steps: 16, once: true,
    bass: seq('D2 - - - E1 - - - A1 - - - - - - -'),
    lead: seq('F4 - A4 - G#4 - B4 - A4 - - - C4 - - -'),
    leadDuty: 0.5, leadVol: 0.045,
    kick: '1.......1.......', hat: '................', snare: '................',
  },
};

export class AudioEngine {
  constructor(prefs = {}) {
    this.prefs = { music: 0.6, sfx: 0.8, muted: false, ...prefs };
    this.ctx = null;
    this.cue = null;
    this.pendingCue = null;
    this.step = 0;
    this.nextTime = 0;
    this.timer = null;
    this.ambient = null;
    this.pendingAmbient = null;
    this.voices = [];
    this.voiceOn = !!prefs.voice;
    this.reduced = false;
    if ('speechSynthesis' in window) {
      const load = () => { this.voices = window.speechSynthesis.getVoices() || []; };
      load();
      try { window.speechSynthesis.addEventListener('voiceschanged', load); } catch { /* old browsers */ }
    }
  }

  /** Create the AudioContext on the first user gesture. */
  unlock() {
    if (this.ctx) { if (this.ctx.state === 'suspended') this.ctx.resume(); return; }
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    const ctx = this.ctx = new AC();
    this.master = ctx.createGain();
    this.master.connect(ctx.destination);
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -14; comp.ratio.value = 3;
    comp.connect(this.master);
    this.musicBus = ctx.createGain();
    this.sfxBus = ctx.createGain();
    this.musicBus.connect(comp);
    this.sfxBus.connect(comp);
    // a touch of room on the music
    const delay = ctx.createDelay(); delay.delayTime.value = 0.28;
    const fb = ctx.createGain(); fb.gain.value = 0.22;
    const wet = ctx.createGain(); wet.gain.value = 0.18;
    const lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 2400;
    this.musicBus.connect(delay); delay.connect(lp); lp.connect(fb); fb.connect(delay); lp.connect(wet); wet.connect(comp);
    this.waves = {};
    for (const d of [0.125, 0.25, 0.5]) this.waves[d] = this.pulseWave(d);
    this.noiseBuf = this.makeNoise(false);
    this.metalBuf = this.makeNoise(true);
    this.applyVolumes();
    this.timer = setInterval(() => this.schedule(), 25);
    if (this.pendingCue) { const c = this.pendingCue; this.pendingCue = null; this.music(c); }
    if (this.pendingAmbient) { const a = this.pendingAmbient; this.pendingAmbient = null; this.setAmbient(a); }
  }

  pulseWave(duty) {
    const n = 32;
    const real = new Float32Array(n), imag = new Float32Array(n);
    for (let k = 1; k < n; k++) real[k] = (2 / (k * Math.PI)) * Math.sin(k * Math.PI * duty);
    return this.ctx.createPeriodicWave(real, imag);
  }

  makeNoise(periodic) {
    const len = this.ctx.sampleRate * (periodic ? 0.5 : 2);
    const buf = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
    const d = buf.getChannelData(0);
    if (periodic) {
      // NES-style short-period LFSR noise: metallic
      let reg = 1;
      const period = 12;
      let v = 0;
      for (let i = 0; i < len; i++) {
        if (i % period === 0) { const bit = (reg ^ (reg >> 6)) & 1; reg = (reg >> 1) | (bit << 14); v = reg & 1 ? 1 : -1; }
        d[i] = v;
      }
    } else {
      for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    }
    return buf;
  }

  applyVolumes() {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    this.master.gain.setTargetAtTime(this.prefs.muted ? 0 : 1, t, 0.05);
    this.musicBus.gain.setTargetAtTime(this.prefs.music, t, 0.05);
    this.sfxBus.gain.setTargetAtTime(this.prefs.sfx, t, 0.05);
  }

  setVolumes(p) { Object.assign(this.prefs, p); this.applyVolumes(); }

  // ---------- instruments ----------

  tone(freq, t, dur, { wave = 'square', duty = 0.5, vol = 0.05, bus = this.musicBus, slideTo = null, attack = 0.004, release = 0.05 } = {}) {
    const ctx = this.ctx;
    const o = ctx.createOscillator();
    if (wave === 'pulse') o.setPeriodicWave(this.waves[duty] || this.waves[0.5]);
    else o.type = wave;
    o.frequency.setValueAtTime(freq, t);
    if (slideTo) o.frequency.exponentialRampToValueAtTime(slideTo, t + dur);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(vol, t + attack);
    g.gain.setValueAtTime(vol, t + Math.max(attack, dur - release));
    g.gain.linearRampToValueAtTime(0, t + dur);
    o.connect(g); g.connect(bus);
    o.start(t); o.stop(t + dur + 0.02);
  }

  noise(t, dur, { vol = 0.05, type = 'highpass', freq = 6000, q = 0.7, metal = false, bus = this.musicBus, decay = true } = {}) {
    const ctx = this.ctx;
    const s = ctx.createBufferSource();
    s.buffer = metal ? this.metalBuf : this.noiseBuf;
    s.loop = true;
    const f = ctx.createBiquadFilter(); f.type = type; f.frequency.value = freq; f.Q.value = q;
    const g = ctx.createGain();
    g.gain.setValueAtTime(vol, t);
    if (decay) g.gain.exponentialRampToValueAtTime(0.0008, t + dur);
    s.connect(f); f.connect(g); g.connect(bus);
    s.start(t, Math.random()); s.stop(t + dur + 0.02);
  }

  kick(t, bus) { this.tone(150, t, 0.16, { wave: 'triangle', vol: 0.32, slideTo: 42, bus }); }
  snare(t, bus) { this.noise(t, 0.14, { vol: 0.12, type: 'bandpass', freq: 1800, q: 0.8, bus }); this.tone(220, t, 0.06, { wave: 'triangle', vol: 0.08, slideTo: 120, bus }); }
  hat(t, bus) { this.noise(t, 0.035, { vol: 0.05, type: 'highpass', freq: 7000, metal: true, bus }); }

  // ---------- sequencer ----------

  music(name) {
    if (!this.ctx) { this.pendingCue = name; return; }
    const cue = CUES[name] || null;
    if (cue === this.cue) return;
    if (this.cue && this.cueGain) {
      const g = this.cueGain;
      g.gain.setTargetAtTime(0, this.ctx.currentTime, 0.25);
      setTimeout(() => g.disconnect(), 1500);
    }
    this.cue = cue;
    if (!cue) return;
    this.cueGain = this.ctx.createGain();
    this.cueGain.gain.value = 1;
    this.cueGain.connect(this.musicBus);
    this.step = 0;
    this.nextTime = this.ctx.currentTime + 0.08;
  }

  schedule() {
    const ctx = this.ctx;
    const cue = this.cue;
    if (!ctx || !cue) return;
    const stepDur = 60 / cue.bpm / 4;
    while (this.nextTime < ctx.currentTime + 0.12) {
      const i = this.step % cue.steps;
      const t = this.nextTime;
      const bus = this.cueGain;
      const holdLen = (arr, idx) => { let n = 1; while (arr[(idx + n) % cue.steps] === '-' && n < cue.steps) n++; return n; };
      const b = NOTE(cue.bass[i]);
      if (b) this.tone(b, t, stepDur * holdLen(cue.bass, i) * 0.95, { wave: 'triangle', vol: 0.2, bus });
      const l = NOTE(cue.lead[i]);
      if (l) this.tone(l, t, stepDur * holdLen(cue.lead, i) * 0.9, { wave: 'pulse', duty: cue.leadDuty, vol: cue.leadVol, bus, release: 0.08 });
      if (cue.kick[i] === '1') this.kick(t, bus);
      if (cue.snare[i] === 'x') this.snare(t, bus);
      if (cue.hat[i] === 'x') this.hat(t, bus);
      this.step++;
      this.nextTime += stepDur;
      if (cue.once && this.step >= cue.steps) { this.cue = null; break; }
    }
  }

  // ---------- stings ----------

  sting(name) {
    if (!this.ctx) return;
    const t = this.ctx.currentTime + 0.02;
    const bus = this.sfxBus;
    switch (name) {
      case 'sustained': {
        [[523.25, 0], [659.25, 0.09], [783.99, 0.18]].forEach(([f, d]) => {
          this.tone(f, t + d, d === 0.18 ? 0.55 : 0.12, { wave: 'pulse', duty: 0.25, vol: 0.09, bus });
          this.tone(f * 2, t + d, 0.1, { wave: 'pulse', duty: 0.125, vol: 0.03, bus });
        });
        this.tone(130.81, t, 0.6, { wave: 'triangle', vol: 0.2, bus });
        break;
      }
      case 'overruled': {
        this.tone(164.81, t, 0.28, { wave: 'pulse', duty: 0.5, vol: 0.1, bus });
        this.tone(116.54, t + 0.3, 0.6, { wave: 'pulse', duty: 0.5, vol: 0.1, bus, slideTo: 104 });
        this.tone(82.41, t, 0.28, { wave: 'triangle', vol: 0.25, bus });
        this.tone(58.27, t + 0.3, 0.7, { wave: 'triangle', vol: 0.25, bus });
        this.noise(t + 0.3, 0.25, { vol: 0.08, type: 'lowpass', freq: 600, bus });
        break;
      }
      case 'clang': {
        // two heavy chiptune hits: pitch-dropped triangle body, inharmonic square partials, filtered noise
        for (const [d, base] of [[0, 1], [0.42, 0.84]]) {
          const tt = t + d;
          this.tone(190 * base, tt, 0.9, { wave: 'triangle', vol: 0.45, slideTo: 38 * base, bus, attack: 0.002, release: 0.6 });
          this.tone(311 * base, tt, 0.5, { wave: 'pulse', duty: 0.5, vol: 0.06, slideTo: 290 * base, bus, attack: 0.002, release: 0.45 });
          this.tone(439 * base, tt, 0.45, { wave: 'pulse', duty: 0.125, vol: 0.05, slideTo: 420 * base, bus, attack: 0.002, release: 0.4 });
          this.tone(622 * base, tt, 0.3, { wave: 'pulse', duty: 0.25, vol: 0.03, bus, attack: 0.002, release: 0.28 });
          this.noise(tt, 0.5, { vol: 0.3, type: 'lowpass', freq: 1400, bus });
          this.noise(tt, 0.2, { vol: 0.08, type: 'bandpass', freq: 3200, metal: true, bus });
        }
        break;
      }
      case 'tick':
        this.tone(1760, t, 0.03, { wave: 'pulse', duty: 0.125, vol: 0.025, bus });
        break;
      case 'select':
        this.tone(880, t, 0.05, { wave: 'pulse', duty: 0.25, vol: 0.04, bus });
        this.tone(1318.5, t + 0.05, 0.08, { wave: 'pulse', duty: 0.25, vol: 0.04, bus });
        break;
      case 'stamp':
        this.noise(t, 0.18, { vol: 0.35, type: 'lowpass', freq: 500, bus });
        this.tone(90, t, 0.15, { wave: 'triangle', vol: 0.3, slideTo: 40, bus });
        break;
      case 'file':
        this.tone(660, t, 0.04, { wave: 'pulse', duty: 0.125, vol: 0.03, bus });
        this.tone(990, t + 0.05, 0.05, { wave: 'pulse', duty: 0.125, vol: 0.03, bus });
        break;
      case 'step':
        this.noise(t, 0.06, { vol: 0.05, type: 'bandpass', freq: 900, q: 1.5, bus });
        break;
      default:
    }
  }

  // ---------- ambience ----------

  setAmbient(kind) {
    if (!this.ctx) { this.pendingAmbient = kind; return; }
    if (this.ambient?.kind === kind) return;
    if (this.ambient) {
      const old = this.ambient;
      old.gain.gain.setTargetAtTime(0, this.ctx.currentTime, 0.5);
      setTimeout(() => { old.nodes.forEach((n) => { try { n.stop(); } catch { /* already stopped */ } }); old.gain.disconnect(); }, 3000);
    }
    if (!kind) { this.ambient = null; return; }
    const ctx = this.ctx;
    const gain = ctx.createGain();
    gain.gain.value = 0;
    gain.connect(this.sfxBus);
    const nodes = [];
    const src = (type, freq, q, vol) => {
      const s = ctx.createBufferSource();
      s.buffer = this.noiseBuf; s.loop = true;
      const f = ctx.createBiquadFilter(); f.type = type; f.frequency.value = freq; f.Q.value = q;
      const g = ctx.createGain(); g.gain.value = vol;
      s.connect(f); f.connect(g); g.connect(gain);
      s.start(0, Math.random() * 1.5);
      nodes.push(s);
      return { f, g };
    };
    if (kind === 'rain') {
      src('bandpass', 4200, 0.4, 0.18);
      src('highpass', 8000, 0.5, 0.05);
      const traffic = src('lowpass', 180, 0.8, 0.5);
      const lfo = ctx.createOscillator(); lfo.frequency.value = 0.07;
      const lg = ctx.createGain(); lg.gain.value = 0.35;
      lfo.connect(lg); lg.connect(traffic.g.gain);
      lfo.start(); nodes.push(lfo);
    } else if (kind === 'yard') {
      src('lowpass', 260, 0.7, 0.35);
      src('bandpass', 1200, 0.3, 0.03);
      const hum = ctx.createOscillator(); hum.type = 'sawtooth'; hum.frequency.value = 50;
      const hf = ctx.createBiquadFilter(); hf.type = 'lowpass'; hf.frequency.value = 120;
      const hg = ctx.createGain(); hg.gain.value = 0.03;
      hum.connect(hf); hf.connect(hg); hg.connect(gain); hum.start(); nodes.push(hum);
    } else {
      src('lowpass', 220, 0.6, 0.22);
      const hum = ctx.createOscillator(); hum.type = 'sine'; hum.frequency.value = 100;
      const hg = ctx.createGain(); hg.gain.value = kind === 'fluorescent' ? 0.012 : 0.005;
      hum.connect(hg); hg.connect(gain); hum.start(); nodes.push(hum);
    }
    gain.gain.setTargetAtTime(1, ctx.currentTime, 1.0);
    this.ambient = { kind, gain, nodes };
  }

  // ---------- speech ----------

  setVoice(on) {
    this.voiceOn = on;
    if (!on && 'speechSynthesis' in window) window.speechSynthesis.cancel();
  }

  speak(text, speakerKey = '', { female = false } = {}) {
    if (!this.voiceOn || !('speechSynthesis' in window) || !text) return;
    const syn = window.speechSynthesis;
    syn.cancel();
    const clean = String(text).replace(/\([^)]*\)/g, ' ').replace(/\[[^\]]*\]/g, ' ').replace(/\s+/g, ' ').trim();
    if (!clean) return;
    const u = new SpeechSynthesisUtterance(clean);
    const en = this.voices.filter((v) => /^en/i.test(v.lang));
    const pool = en.length ? en : this.voices;
    let h = 0;
    for (const ch of speakerKey) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    if (pool.length) {
      const pref = pool.filter((v) => (female ? /female|samantha|victoria|karen|moira|tessa|fiona|zira|serena/i : /male|daniel|alex|fred|oliver|george|david|arthur/i).test(v.name));
      const list = pref.length ? pref : pool;
      u.voice = list[h % list.length];
    }
    u.pitch = 0.8 + ((h % 7) / 7) * 0.45 + (female ? 0.1 : -0.05);
    u.rate = 0.96 + ((h >> 3) % 5) * 0.02;
    u.volume = Math.min(1, this.prefs.muted ? 0 : 0.9);
    syn.speak(u);
  }

  stopSpeech() { if ('speechSynthesis' in window) window.speechSynthesis.cancel(); }
}
