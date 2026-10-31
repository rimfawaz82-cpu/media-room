// محرك العرض الثلاثي الأبعاد: الكوب، البوكس، الإضافات
import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';
import { RoomEnvironment } from './vendor/RoomEnvironment.js';

const CM = 1 / 9;            // وحدة المشهد = ٩ سم (قطر الماغ تقريباً)
const TAU = Math.PI * 2;

// ---------- أدوات صغيرة ----------
function rng(seed) {          // عشوائي ثابت حتى ما ترقص الزخرفة مع كل تعديل
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}
function luminance(hex) {
  const c = new THREE.Color(hex);
  return 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b;
}
export function contrastOn(hex) { return luminance(hex) > 0.55 ? '#2b2b2b' : '#ffffff'; }
function shade(hex, amt) {
  const c = new THREE.Color(hex);
  const hsl = {}; c.getHSL(hsl);
  c.setHSL(hsl.h, hsl.s, Math.min(1, Math.max(0, hsl.l + amt)));
  return '#' + c.getHexString();
}
const imgCache = new Map();
function getImage(src, onload) {
  if (!src) return null;
  let im = imgCache.get(src);
  if (!im) { im = new Image(); im.onload = onload; im.src = src; imgCache.set(src, im); }
  return im.complete && im.naturalWidth ? im : null;
}

// ---------- أشكال الكوب ----------
const SHAPES = {
  mug:    { H: 1.05, r: (t) => 0.48 - 0.012 * Math.pow(1 - t, 6), handle: true,  coffee: true },
  latte:  { H: 0.86, r: (t) => 0.34 + 0.2 * Math.pow(t, 0.75),     handle: true,  coffee: true },
  travel: { H: 1.40, r: (t) => 0.35 + 0.07 * t,                     handle: false, coffee: false, lid: true },
  glass:  { H: 1.10, r: (t) => 0.41 + 0.05 * t,                     handle: false, coffee: false, glass: true },
};

// ---------- رسم الزخرفة على الكوب ----------
function drawPattern(ctx, W, H, type, color, seed = 7) {
  if (!type || type === 'none') return;
  const R = rng(seed);
  ctx.save();
  ctx.fillStyle = color; ctx.strokeStyle = color;
  const heart = (x, y, s, rot = 0) => {
    ctx.save(); ctx.translate(x, y); ctx.rotate(rot); ctx.scale(s / 32, s / 32);
    ctx.beginPath(); ctx.moveTo(0, 10);
    ctx.bezierCurveTo(-26, -8, -12, -30, 0, -14);
    ctx.bezierCurveTo(12, -30, 26, -8, 0, 10); ctx.fill(); ctx.restore();
  };
  const star = (x, y, s, rot = 0) => {
    ctx.save(); ctx.translate(x, y); ctx.rotate(rot); ctx.beginPath();
    for (let i = 0; i < 10; i++) {
      const rr = i % 2 ? s * 0.42 : s; const a = (i / 10) * TAU - Math.PI / 2;
      ctx.lineTo(Math.cos(a) * rr, Math.sin(a) * rr);
    }
    ctx.closePath(); ctx.fill(); ctx.restore();
  };
  const flower = (x, y, s, rot = 0) => {
    ctx.save(); ctx.translate(x, y); ctx.rotate(rot);
    for (let i = 0; i < 5; i++) {
      ctx.rotate(TAU / 5); ctx.beginPath(); ctx.ellipse(0, -s * 0.55, s * 0.32, s * 0.5, 0, 0, TAU); ctx.fill();
    }
    ctx.globalCompositeOperation = 'destination-out';
    ctx.beginPath(); ctx.arc(0, 0, s * 0.22, 0, TAU); ctx.fill(); ctx.restore();
  };
  if (type === 'stripes') {
    const n = 9, bw = H / (n * 2);
    for (let i = 0; i < n; i++) ctx.fillRect(0, i * bw * 2 + bw * 0.5, W, bw * 0.55);
  } else if (type === 'dots') {
    const step = H / 6;
    for (let y = step / 2, row = 0; y < H; y += step, row++)
      for (let x = (row % 2) * step / 2; x < W + step; x += step) { ctx.beginPath(); ctx.arc(x, y, step * 0.13, 0, TAU); ctx.fill(); }
  } else {
    const count = type === 'confetti' ? 140 : 70;
    for (let i = 0; i < count; i++) {
      const x = R() * W, y = R() * H, s = H * (0.035 + R() * 0.05), rot = (R() - 0.5) * 1.2;
      if (type === 'hearts') heart(x, y, s, rot);
      else if (type === 'stars') star(x, y, s * 0.7, rot);
      else if (type === 'flowers') flower(x, y, s * 0.8, rot);
      else if (type === 'confetti') {
        ctx.save(); ctx.translate(x, y); ctx.rotate(R() * TAU);
        ctx.fillStyle = ['#f2a541', '#c2405a', '#7c9a83', '#5b8bd9', color][i % 5];
        ctx.fillRect(-s * 0.5, -s * 0.15, s, s * 0.3); ctx.restore();
      }
    }
  }
  ctx.restore();
}

function fitFont(ctx, text, family, maxW, maxH, weight = 700) {
  let size = maxH;
  ctx.font = `${weight} ${size}px ${family}`;
  const w = ctx.measureText(text).width;
  if (w > maxW) size = Math.floor(size * maxW / w);
  ctx.font = `${weight} ${size}px ${family}`;
  return size;
}

function paintCup(canvas, cfg, aspect, onImage) {
  const W = 2048, H = Math.round(W / aspect);
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, W, H);
  const isGlass = cfg.shape === 'glass';
  if (!isGlass) { ctx.fillStyle = cfg.color; ctx.fillRect(0, 0, W, H); }

  const accent = cfg.patternColor || (isGlass ? '#ffffff' : (luminance(cfg.color) > 0.55 ? shade(cfg.textColor, 0.12) : shade(cfg.color, 0.25)));
  ctx.globalAlpha = isGlass ? 0.85 : 0.7;
  if (cfg.patternImg) {
    const im = getImage(cfg.patternImg, onImage);
    if (im) { const th = H / 3, tw = th * im.width / im.height; for (let y = 0; y < H; y += th) for (let x = 0; x < W; x += tw) ctx.drawImage(im, x, y, tw, th); }
  } else drawPattern(ctx, W, H, cfg.pattern, accent, 11);
  ctx.globalAlpha = 1;

  const cx = W / 2;
  const hasText = (cfg.text || '').trim() || (cfg.line2 || '').trim() || cfg.sticker || cfg.stickerImg;
  if (hasText && cfg.pattern !== 'none' && !isGlass) {   // هالة ناعمة ورا الكتابة
    const g = ctx.createRadialGradient(cx, H / 2, H * 0.1, cx, H / 2, W * 0.2);
    g.addColorStop(0, cfg.color); g.addColorStop(0.7, cfg.color); g.addColorStop(1, cfg.color + '00');
    ctx.fillStyle = g; ctx.fillRect(cx - W * 0.22, 0, W * 0.44, H);
  }

  let y = H * 0.5;
  const sticker = cfg.stickerImg ? getImage(cfg.stickerImg, onImage) : null;
  const hasSticker = sticker || cfg.sticker;
  const t1 = (cfg.text || '').trim(), t2 = (cfg.line2 || '').trim();
  const blocks = (hasSticker ? 0.3 : 0) + (t1 ? 0.24 : 0) + (t2 ? 0.11 : 0);
  y = H * (0.5 - blocks / 2);
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.direction = 'rtl';
  if (sticker) { const s = H * 0.28, sw = s * sticker.width / sticker.height; ctx.drawImage(sticker, cx - sw / 2, y, sw, s); y += H * 0.3; }
  else if (cfg.sticker) { ctx.font = `${Math.round(H * 0.22)}px "Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif`; ctx.fillText(cfg.sticker, cx, y + H * 0.15); y += H * 0.3; }
  ctx.fillStyle = cfg.textColor;
  if (t1) { fitFont(ctx, t1, cfg.font, W * 0.36, H * 0.2); ctx.fillText(t1, cx, y + H * 0.12); y += H * 0.24; }
  if (t2) { fitFont(ctx, t2, cfg.font, W * 0.34, H * 0.085, 500); ctx.globalAlpha = 0.85; ctx.fillText(t2, cx, y + H * 0.055); ctx.globalAlpha = 1; }

  if (cfg.backText) {   // ضهر الكوب: لمسة صغيرة (على خط الدرزة)
    fitFont(ctx, cfg.backText, cfg.font, W * 0.16, H * 0.07, 500);
    ctx.fillStyle = cfg.textColor; ctx.globalAlpha = 0.7;
    ctx.fillText(cfg.backText, 0, H * 0.82); ctx.fillText(cfg.backText, W, H * 0.82); ctx.globalAlpha = 1;
  }
}

function latteArt() {
  const c = document.createElement('canvas'); c.width = c.height = 256;
  const x = c.getContext('2d');
  const g = x.createRadialGradient(128, 128, 20, 128, 128, 128);
  g.addColorStop(0, '#a0673f'); g.addColorStop(0.8, '#6b3e22'); g.addColorStop(1, '#4a2914');
  x.fillStyle = g; x.fillRect(0, 0, 256, 256);
  x.fillStyle = '#f3e3cf'; x.translate(128, 136); x.scale(2.6, 2.6);
  x.beginPath(); x.moveTo(0, 18); x.bezierCurveTo(-34, -6, -16, -34, 0, -14); x.bezierCurveTo(16, -34, 34, -6, 0, 18); x.fill();
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

// ---------- الإضافات جوّا البوكس ----------
function std(color, rough = 0.6, extra = {}) { return new THREE.MeshStandardMaterial({ color, roughness: rough, ...extra }); }
function shadowAll(o) { o.traverse((m) => { if (m.isMesh) { m.castShadow = true; m.receiveShadow = true; } }); return o; }

function makeAddon(kind, opts = {}) {
  const g = new THREE.Group();
  if (kind === 'chocolate') {
    const base = new THREE.Mesh(new THREE.BoxGeometry(0.62, 0.1, 0.42), std('#c9a14a', 0.3, { metalness: 0.7 }));
    base.position.y = 0.05; g.add(base);
    const ch = std('#3b2115', 0.45);
    for (let i = 0; i < 3; i++) for (let j = 0; j < 2; j++) {
      const s = new THREE.Mesh(new THREE.SphereGeometry(0.085, 20, 14), ch);
      s.scale.y = 0.8; s.position.set(-0.19 + i * 0.19, 0.16, -0.1 + j * 0.2); g.add(s);
    }
    g.userData.size = 0.62;
  } else if (kind === 'rose') {
    const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.014, 0.9, 8), std('#3f6b3a'));
    stem.position.y = 0.45; g.add(stem);
    const leaf = new THREE.Mesh(new THREE.SphereGeometry(0.07, 12, 8), std('#4d7d44'));
    leaf.scale.set(1, 0.25, 0.5); leaf.position.set(0.06, 0.45, 0); leaf.rotation.z = 0.5; g.add(leaf);
    const petal = std('#b3122e', 0.5, { side: THREE.DoubleSide });
    for (let i = 0; i < 9; i++) {
      const p = new THREE.Mesh(new THREE.SphereGeometry(0.11 - i * 0.006, 16, 10, 0, Math.PI * 1.2, 0, Math.PI * 0.6), petal);
      p.rotation.set(-0.2, (i / 9) * TAU * 1.6, 0); p.position.y = 0.92 + i * 0.006; g.add(p);
    }
    const bud = new THREE.Mesh(new THREE.SphereGeometry(0.06, 14, 10), petal); bud.position.y = 0.98; g.add(bud);
    g.rotation.set(Math.PI / 2 - 0.15, 0, 0); g.userData.size = 1.05; g.userData.lie = true;
  } else if (kind === 'card') {
    const c = document.createElement('canvas'); c.width = 512; c.height = 360;
    const x = c.getContext('2d'); x.fillStyle = '#fffaf2'; x.fillRect(0, 0, 512, 360);
    x.strokeStyle = '#d4af37'; x.lineWidth = 8; x.strokeRect(16, 16, 480, 328);
    x.fillStyle = '#5a3a2e'; x.textAlign = 'center'; x.direction = 'rtl';
    x.font = '700 44px "El Messiri", serif';
    const msg = (opts.message || 'من القلب ♥').slice(0, 60);
    const words = msg.split(' '); let line = '', yy = 120; const lines = [];
    for (const w of words) { const t = line ? line + ' ' + w : w; if (x.measureText(t).width > 420 && line) { lines.push(line); line = w; } else line = t; }
    lines.push(line); lines.slice(0, 3).forEach((l, i) => x.fillText(l, 256, yy + i * 64 - (lines.length - 1) * 20));
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
    const card = new THREE.Mesh(new THREE.BoxGeometry(0.56, 0.4, 0.01), [std('#fffaf2'), std('#fffaf2'), std('#fffaf2'), std('#fffaf2'), std('#ffffff', 0.8, { map: tex }), std('#fffaf2')]);
    card.position.y = 0.26; card.rotation.x = -0.35; g.add(card);
    g.userData.size = 0.56; g.userData.cardTex = tex;
  } else if (kind === 'candle') {
    const jar = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.36, 32, 1, true),
      new THREE.MeshPhysicalMaterial({ color: '#ffffff', transmission: 0.9, roughness: 0.08, thickness: 0.05, transparent: true, side: THREE.DoubleSide }));
    jar.position.y = 0.18; g.add(jar);
    const wax = new THREE.Mesh(new THREE.CylinderGeometry(0.185, 0.185, 0.26, 32), std('#f4ead8', 0.9)); wax.position.y = 0.13; g.add(wax);
    const wick = new THREE.Mesh(new THREE.CylinderGeometry(0.006, 0.006, 0.05), std('#222')); wick.position.y = 0.285; g.add(wick);
    const flame = new THREE.Mesh(new THREE.SphereGeometry(0.03, 12, 10), new THREE.MeshBasicMaterial({ color: '#ffcf6b' }));
    flame.scale.y = 1.9; flame.position.y = 0.33; g.add(flame);
    const light = new THREE.PointLight('#ffb347', 0.6, 1.5); light.position.y = 0.4; g.add(light);
    g.userData.flame = flame; g.userData.light = light; g.userData.size = 0.42;
  } else if (kind === 'teddy') {
    const fur = std('#a8774f', 0.95), dark = std('#5a3a24', 0.8), muzz = std('#e6cfae', 0.95);
    const body = new THREE.Mesh(new THREE.SphereGeometry(0.2, 24, 18), fur); body.scale.set(1, 1.1, 0.9); body.position.y = 0.21; g.add(body);
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.15, 24, 18), fur); head.position.y = 0.5; g.add(head);
    for (const s of [-1, 1]) {
      const ear = new THREE.Mesh(new THREE.SphereGeometry(0.055, 14, 10), fur); ear.position.set(s * 0.11, 0.62, 0); g.add(ear);
      const eye = new THREE.Mesh(new THREE.SphereGeometry(0.018, 10, 8), dark); eye.position.set(s * 0.05, 0.53, 0.135); g.add(eye);
      const arm = new THREE.Mesh(new THREE.SphereGeometry(0.07, 14, 10), fur); arm.scale.y = 1.5; arm.position.set(s * 0.2, 0.25, 0.04); g.add(arm);
      const leg = new THREE.Mesh(new THREE.SphereGeometry(0.08, 14, 10), fur); leg.position.set(s * 0.11, 0.06, 0.12); g.add(leg);
    }
    const m = new THREE.Mesh(new THREE.SphereGeometry(0.06, 14, 10), muzz); m.scale.z = 0.7; m.position.set(0, 0.47, 0.13); g.add(m);
    const nose = new THREE.Mesh(new THREE.SphereGeometry(0.02, 10, 8), dark); nose.position.set(0, 0.49, 0.175); g.add(nose);
    const heart = new THREE.Mesh(new THREE.SphereGeometry(0.05, 12, 8), std('#c2405a', 0.5)); heart.scale.z = 0.4; heart.position.set(0, 0.25, 0.18); g.add(heart);
    g.userData.size = 0.46;
  } else if (kind === 'cookies') {
    const dough = std('#c98f4e', 0.95), chip = std('#3b2115', 0.6);
    for (let i = 0; i < 3; i++) {
      const c = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.15, 0.045, 24), dough);
      c.position.set((i - 1) * 0.04, 0.03 + i * 0.05, 0); c.rotation.z = (i - 1) * 0.08; g.add(c);
      for (let k = 0; k < 5; k++) {
        const d = new THREE.Mesh(new THREE.SphereGeometry(0.018, 8, 6), chip);
        const a = k * 1.3 + i, rr = 0.04 + (k % 3) * 0.03;
        d.position.set(c.position.x + Math.cos(a) * rr, c.position.y + 0.024, Math.sin(a) * rr); g.add(d);
      }
    }
    g.userData.size = 0.34;
  } else {   // إضافة جديدة من لوحة التحكم: علبة صغيرة
    const b = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.24, 0.34), std(opts.color || '#e8b4c4', 0.5)); b.position.y = 0.12; g.add(b);
    g.userData.size = 0.36;
  }
  return shadowAll(g);
}

// ---------- الاستوديو ----------
export function createStudio(host) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  host.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(renderer), 0.04).texture;

  const camera = new THREE.PerspectiveCamera(32, 1, 0.05, 100);
  camera.position.set(0.6, 1.6, 4.2);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = 0.08;
  controls.minDistance = 1.6; controls.maxDistance = 9;
  controls.maxPolarAngle = Math.PI * 0.49; controls.enablePan = false;
  controls.autoRotateSpeed = 1.2;

  scene.add(new THREE.HemisphereLight('#fff6ee', '#e9d9cc', 0.6));
  const key = new THREE.DirectionalLight('#fff3e6', 1.6);
  key.position.set(3, 6, 4); key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048); key.shadow.radius = 6; key.shadow.bias = -0.0004;
  Object.assign(key.shadow.camera, { left: -4, right: 4, top: 4, bottom: -4, near: 1, far: 20 });
  scene.add(key);
  const rim = new THREE.DirectionalLight('#ffd9e2', 0.7); rim.position.set(-4, 3, -3); scene.add(rim);

  // منصة العرض
  const pedestalMat = std('#f3e7dc', 0.85);
  const pedestal = new THREE.Mesh(new THREE.CylinderGeometry(2.9, 3.0, 0.24, 96), pedestalMat);
  pedestal.position.y = -0.12; pedestal.receiveShadow = true; scene.add(pedestal);
  const ring = new THREE.Mesh(new THREE.TorusGeometry(2.92, 0.012, 8, 128), std('#d4af37', 0.25, { metalness: 0.9 }));
  ring.rotation.x = Math.PI / 2; ring.position.y = 0.002; scene.add(ring);

  const world = new THREE.Group(); scene.add(world);
  const cupHolder = new THREE.Group(); world.add(cupHolder);
  const boxHolder = new THREE.Group(); world.add(boxHolder);

  const cupCanvas = document.createElement('canvas');
  const cupTex = new THREE.CanvasTexture(cupCanvas);
  cupTex.colorSpace = THREE.SRGBColorSpace; cupTex.anisotropy = 8;
  const latteTex = latteArt();

  let cupCfg = null, cupShapeBuilt = null, cupParts = null;
  let boxCfg = null, boxParts = null;
  let view = 'cup';
  const anim = { lid: 0, lidTarget: 0, boxScale: 0, boxScaleTarget: 0, cupPos: new THREE.Vector3(), cupPosTarget: new THREE.Vector3(), cupScale: 1, cupScaleTarget: 1 };
  let camAnim = null;
  const flames = [];

  // ----- بناء الكوب -----
  function buildCup(shapeId) {
    cupHolder.clear();
    const S = SHAPES[shapeId] || SHAPES.mug;
    const N = 48, pts = [];
    for (let i = 0; i < N; i++) { const t = i / (N - 1); pts.push(new THREE.Vector2(S.r(t), t * S.H)); }
    const glaze = new THREE.MeshPhysicalMaterial({ color: '#ffffff', roughness: 0.32, clearcoat: 0.7, clearcoatRoughness: 0.15 });
    let bodyMat, decal = null;
    if (S.glass) {
      bodyMat = new THREE.MeshPhysicalMaterial({ color: '#ffffff', transmission: 0.95, roughness: 0.04, thickness: 0.08, ior: 1.5, transparent: true, side: THREE.DoubleSide });
      const dpts = pts.map((p) => new THREE.Vector2(p.x + 0.003, p.y));
      decal = new THREE.Mesh(new THREE.LatheGeometry(dpts, 96), new THREE.MeshStandardMaterial({ map: cupTex, transparent: true, roughness: 0.4, depthWrite: false }));
      decal.rotation.y = Math.PI;
    } else {
      bodyMat = new THREE.MeshPhysicalMaterial({ map: cupTex, roughness: 0.28, clearcoat: 0.8, clearcoatRoughness: 0.12 });
    }
    const body = new THREE.Mesh(new THREE.LatheGeometry(pts, 96), bodyMat);
    body.rotation.y = Math.PI;                 // نص الصورة (u=0.5) لقدّام
    const group = new THREE.Group(); group.add(body); if (decal) group.add(decal);

    const inner = pts.map((p) => new THREE.Vector2(Math.max(0.01, p.x - 0.035), p.y)).filter((p, i) => i > 2);
    const innerMat = S.glass ? null : glaze.clone();
    if (!S.glass) {
      const innerMesh = new THREE.Mesh(new THREE.LatheGeometry(inner, 64), innerMat); innerMesh.material.side = THREE.BackSide; group.add(innerMesh);
      const floor = new THREE.Mesh(new THREE.CircleGeometry(inner[0].x, 48), innerMat); floor.rotation.x = -Math.PI / 2; floor.position.y = inner[0].y; group.add(floor);
    }
    const topR = S.r(1) - 0.0175;
    const rim = new THREE.Mesh(new THREE.TorusGeometry(topR, 0.0185, 12, 96), S.glass ? bodyMat : glaze.clone());
    rim.rotation.x = Math.PI / 2; rim.position.y = S.H; group.add(rim);
    const base = new THREE.Mesh(new THREE.CircleGeometry(S.r(0), 48), S.glass ? bodyMat : glaze.clone());
    base.rotation.x = Math.PI / 2; base.position.y = 0.002; group.add(base);

    let handle = null;
    if (S.handle) {
      const arc = Math.PI * 1.15;
      handle = new THREE.Mesh(new THREE.TorusGeometry(0.25, 0.052, 20, 64, arc), glaze.clone());
      handle.rotation.z = -arc / 2; handle.scale.set(0.85, 1, 1);
      const hy = S.H * 0.52; handle.position.set((S.r(0.3) + S.r(0.75)) / 2 + 0.03, hy, 0); group.add(handle);
    }
    if (S.coffee) {
      const lvl = 0.86, cr = S.r(lvl) - 0.034;
      const coffee = new THREE.Mesh(new THREE.CircleGeometry(cr, 48), new THREE.MeshPhysicalMaterial({ map: latteTex, roughness: 0.2, clearcoat: 1 }));
      coffee.rotation.x = -Math.PI / 2; coffee.rotation.z = Math.PI; coffee.position.y = S.H * lvl; group.add(coffee);
    }
    let lid = null;
    if (S.lid) {
      lid = new THREE.Group();
      const lm = std('#2b2b2b', 0.55);
      const l1 = new THREE.Mesh(new THREE.CylinderGeometry(S.r(1) + 0.012, S.r(1) + 0.012, 0.09, 64), lm); l1.position.y = 0.045; lid.add(l1);
      const l2 = new THREE.Mesh(new THREE.CylinderGeometry(S.r(1) - 0.03, S.r(1) + 0.0, 0.06, 64), lm); l2.position.y = 0.12; lid.add(l2);
      const sip = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.02, 0.03), std('#111')); sip.position.set(0, 0.152, S.r(1) * 0.55); lid.add(sip);
      lid.position.y = S.H - 0.01; group.add(lid);
      rim.visible = false;
    }
    shadowAll(group);
    if (decal) decal.castShadow = false;
    cupHolder.add(group);
    const avgR = (S.r(0) + S.r(0.5) + S.r(1)) / 3;
    cupParts = { group, body, glaze, innerMat, handle, lid, S, aspect: (TAU * avgR) / S.H };
    cupShapeBuilt = shapeId;
  }

  function setCup(cfg) {
    cupCfg = { ...cfg };
    if (cupShapeBuilt !== cfg.shape) buildCup(cfg.shape);
    paintCup(cupCanvas, cupCfg, cupParts.aspect, () => setCup(cupCfg));
    cupTex.needsUpdate = true;
    const tint = cfg.shape === 'glass' ? '#ffffff' : cfg.color;
    const insideTint = cfg.shape === 'glass' ? '#ffffff' : (cfg.innerColor || '#ffffff');
    cupParts.glaze.color.set(tint);
    cupParts.group.traverse((m) => { if (m.isMesh && m !== cupParts.body && m.material !== cupParts.innerMat && m.material.type === 'MeshPhysicalMaterial' && !m.material.map && !m.material.transmission) m.material.color.set(cfg.handleColor || tint); });
    if (cupParts.innerMat) cupParts.innerMat.color.set(insideTint);
    const rough = luminance(cfg.color) < 0.12 ? 0.6 : 0.28;   // الأسود مطفي
    if (cfg.shape !== 'glass') { cupParts.body.material.roughness = rough; cupParts.body.material.clearcoat = rough > 0.5 ? 0.1 : 0.8; }
    layout();
  }

  // ----- بناء البوكس -----
  function canvasTex(w, h, draw) {
    const c = document.createElement('canvas'); c.width = w; c.height = h; draw(c.getContext('2d'), w, h);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8; return t;
  }
  function paperTex(hex) {   // ملمس ورق كرتون خفيف
    return canvasTex(256, 256, (x, w, h) => {
      x.fillStyle = hex; x.fillRect(0, 0, w, h);
      const R = rng(3);
      for (let i = 0; i < 2600; i++) { x.fillStyle = `rgba(${R() > 0.5 ? '255,255,255' : '0,0,0'},${0.025 + R() * 0.03})`; x.fillRect(R() * w, R() * h, 1 + R() * 2, 1); }
    });
  }

  function buildBox(cfg) {
    boxHolder.clear(); flames.length = 0;
    boxParts = null;
    if (!cfg || !cfg.w) return;
    const w = cfg.w * CM, h = cfg.h * CM, d = cfg.d * CM, lidH = 0.24, gap = 0.03, overlap = 0.12;
    const color = cfg.color, ribbon = cfg.ribbon;
    const paper = paperTex(color);
    const outside = std('#ffffff', 0.78, { map: paper });
    const inside = std(shade(color, 0.12), 0.9, { side: THREE.DoubleSide });
    const hidden = new THREE.MeshBasicMaterial({ visible: false });
    const ink = ribbon || contrastOn(color);
    const front = std('#ffffff', 0.75, {
      map: canvasTex(1024, Math.round(1024 * h / w), (x, W, H) => {
        x.fillStyle = color; x.fillRect(0, 0, W, H);
        x.textAlign = 'center'; x.textBaseline = 'middle'; x.direction = 'rtl'; x.fillStyle = ink;
        if (cfg.to) { fitFont(x, 'إلى ' + cfg.to, '"El Messiri", serif', W * 0.7, H * 0.26); x.fillText('إلى ' + cfg.to, W / 2, H * 0.45); }
        x.globalAlpha = 0.75; fitFont(x, cfg.shopName || '', '"Lalezar", sans-serif', W * 0.4, H * 0.1, 400);
        x.fillText(cfg.shopName || '', W / 2, H * (cfg.to ? 0.72 : 0.5)); x.globalAlpha = 1;
      }),
    });
    const bodyGroup = new THREE.Group();
    // جدران البوكس (BoxGeometry: +x,-x,+y,-y,+z,-z)
    const walls = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), [outside, outside, hidden, outside, front, outside]);
    walls.position.y = h / 2; bodyGroup.add(walls);
    const liner = new THREE.Mesh(new THREE.BoxGeometry(w - 0.02, h - 0.01, d - 0.02), [inside, inside, hidden, inside, inside, inside]);
    liner.material = liner.material.map((m) => (m === inside ? new THREE.MeshStandardMaterial({ color: shade(color, 0.1), roughness: 0.9, side: THREE.BackSide }) : m));
    liner.position.y = h / 2 + 0.005; bodyGroup.add(liner);
    // ورق مقصوص (حشوة)
    const shredGeo = new THREE.BoxGeometry(0.16, 0.006, 0.022);
    const shredColor = new THREE.Color(ribbon || shade(color, 0.25));
    const count = Math.round(260 * w * d);
    const shred = new THREE.InstancedMesh(shredGeo, std('#ffffff', 0.8), count);
    const R = rng(5), m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler();
    for (let i = 0; i < count; i++) {
      e.set((R() - 0.5) * 1.4, R() * TAU, (R() - 0.5) * 1.4); q.setFromEuler(e);
      m4.compose(new THREE.Vector3((R() - 0.5) * (w - 0.12), 0.02 + R() * 0.14, (R() - 0.5) * (d - 0.12)), q, new THREE.Vector3(1, 1, 1));
      shred.setMatrixAt(i, m4);
      shred.setColorAt(i, shredColor.clone().offsetHSL(0, 0, (R() - 0.5) * 0.12));
    }
    shred.receiveShadow = true;
    const fill = new THREE.Group(); fill.add(shred);
    const filler = new THREE.Mesh(new THREE.BoxGeometry(w - 0.03, 1, d - 0.03), std(ribbon || shade(color, 0.25), 0.95));
    filler.position.y = -0.5; fill.add(filler); bodyGroup.add(fill);
    shadowAll(walls);

    // الغطا مع مفصّلة من ورا
    const lidPivot = new THREE.Group(); lidPivot.position.set(0, h - overlap + lidH, -(d / 2 + gap));
    const lidMesh = new THREE.Mesh(new THREE.BoxGeometry(w + gap * 2, lidH, d + gap * 2), [outside, outside, outside, hidden, outside, outside]);
    lidMesh.material = lidMesh.material.map((m) => (m === hidden ? hidden : m));
    lidMesh.position.set(0, -lidH / 2, d / 2 + gap); lidPivot.add(lidMesh);
    const lidIn = new THREE.Mesh(new THREE.BoxGeometry(w + gap * 2 - 0.01, lidH - 0.005, d + gap * 2 - 0.01), new THREE.MeshStandardMaterial({ color: shade(color, 0.1), roughness: 0.9, side: THREE.BackSide }));
    lidIn.position.copy(lidMesh.position); lidPivot.add(lidIn);
    let bow = null;
    if (ribbon) {
      const rm = std(ribbon, 0.35, { metalness: luminance(ribbon) > 0.4 && ribbon !== '#ffffff' ? 0.5 : 0.05, side: THREE.DoubleSide });
      const bw = 0.14, t = 0.008;
      const rx = new THREE.Mesh(new THREE.BoxGeometry(w + gap * 2 + t * 2, lidH + t, bw), [rm, rm, rm, hidden, rm, rm]);
      rx.position.copy(lidMesh.position); rx.position.y += t / 2; lidPivot.add(rx);
      const rz = new THREE.Mesh(new THREE.BoxGeometry(bw, lidH + t, d + gap * 2 + t * 2), [rm, rm, rm, hidden, rm, rm]);
      rz.position.copy(rx.position); lidPivot.add(rz);
      bow = new THREE.Group();
      for (const s of [-1, 1]) {
        const loop = new THREE.Mesh(new THREE.TorusGeometry(0.15, 0.035, 12, 40), rm);
        loop.scale.set(1.25, 0.65, 0.5); loop.position.set(s * 0.17, 0.08, 0); loop.rotation.z = s * 0.35; bow.add(loop);
        const tail = new THREE.Mesh(new THREE.BoxGeometry(0.09, 0.008, 0.36), rm);
        tail.position.set(s * 0.08, 0.01, 0.17); tail.rotation.y = s * 0.45; bow.add(tail);
      }
      const knot = new THREE.Mesh(new THREE.SphereGeometry(0.07, 20, 14), rm); knot.scale.set(1, 0.8, 0.9); knot.position.y = 0.06; bow.add(knot);
      bow.position.set(0, lidMesh.position.y + lidH / 2 + t, lidMesh.position.z);
      lidPivot.add(bow);
    }
    shadowAll(lidPivot);
    bodyGroup.add(lidPivot);

    // الإضافات
    const items = new THREE.Group(); bodyGroup.add(items);
    (cfg.addons || []).forEach((a) => {
      const it = makeAddon(a.kind, { message: cfg.message, color: cfg.color });
      it.userData.id = a.id; items.add(it);
      if (it.userData.flame) flames.push(it.userData);
    });
    boxHolder.add(bodyGroup);
    boxParts = { w, h, d, lidPivot, bow, items, bodyGroup, fill, filler };
  }

  function setBox(cfg) {
    const k = JSON.stringify(cfg);
    if (boxCfg && JSON.stringify(boxCfg) === k) return;
    const sizeChanged = !boxCfg || boxCfg.w !== cfg.w || boxCfg.d !== cfg.d;
    boxCfg = JSON.parse(k);
    buildBox(boxCfg);
    if (sizeChanged && boxParts) anim.boxScale = Math.min(anim.boxScale, 0.85);
    layout();
  }

  // ترتيب الكوب والإضافات جوّا البوكس
  function layout() {
    const inBox = boxParts && view !== 'cup';
    anim.boxScaleTarget = inBox ? 1 : 0;
    anim.lidTarget = view === 'gift' ? 0 : -1.95;
    if (!inBox) { anim.cupPosTarget.set(0, 0, 0); anim.cupScaleTarget = 1; return; }
    const { w, d, items } = boxParts;
    const S = cupParts ? cupParts.S : SHAPES.mug;
    const cupR = S.r(0.5);
    const list = items.children;
    const fitScale = Math.min(1, (boxParts.h - 0.1) / (S.H + (S.lid ? 0.16 : 0)));
    anim.cupScaleTarget = fitScale;
    // حشوة عالية متل البوكسات الحقيقية: الكوب بيطلّ من فوق، والإضافات بتبين
    const floor = Math.max(0.02, Math.min(boxParts.h * 0.5, boxParts.h - (S.H + (S.lid ? 0.16 : 0)) * fitScale - 0.14));
    boxParts.fill.position.y = floor; boxParts.filler.scale.y = floor + 0.02; boxParts.filler.position.y = -(floor + 0.02) / 2 + 0.02;
    items.position.y = floor;
    const cupW = (cupR * 2 + (S.handle ? 0.3 : 0)) * fitScale;
    let cupX = list.length ? -w / 2 + cupW / 2 + 0.12 : 0;
    if (list.length && cupW + 0.5 > w) cupX = 0;
    anim.cupPosTarget.set(cupX - (S.handle ? 0.12 * fitScale : 0), floor + 0.1, list.length && cupX === 0 ? -d / 2 + cupR + 0.12 : 0);
    // شبكة للإضافات بالمساحة الباقية
    const freeX0 = cupX === 0 ? -w / 2 + 0.15 : cupX + cupW / 2 + 0.08, freeX1 = w / 2 - 0.12;
    const freeZ0 = cupX === 0 ? anim.cupPosTarget.z + cupR + 0.08 : -d / 2 + 0.15, freeZ1 = d / 2 - 0.12;
    const cols = Math.max(1, Math.round((freeX1 - freeX0) / 0.55)), rows = Math.max(1, Math.ceil(list.length / cols));
    list.forEach((it, i) => {
      const c = i % cols, r = Math.floor(i / cols);
      const x = freeX0 + (c + 0.5) * (freeX1 - freeX0) / cols;
      const z = freeZ0 + (r + 0.5) * (freeZ1 - freeZ0) / rows;
      const s = Math.min(1, ((freeX1 - freeX0) / cols) / (it.userData.size + 0.06), ((freeZ1 - freeZ0) / rows) / (it.userData.size + 0.06));
      it.scale.setScalar(it.userData.lie ? Math.min(1, (d - 0.3) / it.userData.size) : Math.max(0.55, s));
      it.position.set(x, it.userData.lie ? 0.16 : 0.08, it.userData.lie ? -0.5 * it.userData.size * it.scale.x : z);
      if (!it.userData.lie) it.rotation.y = (i % 2 ? -1 : 1) * 0.25;
    });
  }

  // ----- الكاميرا -----
  function focus(immediate) {
    let target, pos;
    const S = cupParts ? cupParts.S : SHAPES.mug;
    if (view === 'cup' || !boxParts) {
      target = new THREE.Vector3(0, S.H * 0.5, 0);
      pos = new THREE.Vector3(0.9, S.H * 0.5 + 1.0, 3.4 + S.H * 0.6);
    } else {
      const span = Math.max(boxParts.w, boxParts.d);
      target = new THREE.Vector3(0, boxParts.h * 0.4, 0);
      const dist = 3.2 + span * 1.7;
      pos = new THREE.Vector3(dist * 0.25, boxParts.h + dist * (view === 'gift' ? 0.5 : 0.78), dist * 0.8);
    }
    if (immediate) { camera.position.copy(pos); controls.target.copy(target); camAnim = null; }
    else camAnim = { pos, target };
  }
  controls.addEventListener('start', () => { camAnim = null; idle = 0; controls.autoRotate = false; });
  let idle = 0;

  function setView(v, immediate) { view = v; layout(); focus(immediate); idle = 0; controls.autoRotate = false; }

  function openGift() { anim.lidTarget = -1.95; anim.bowPop = 1; }
  function closeGift() { anim.lidTarget = 0; }

  function resize() {
    const r = host.getBoundingClientRect();
    if (!r.width || !r.height) return;
    renderer.setSize(r.width, r.height, false);
    camera.aspect = r.width / r.height; camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(host); resize();

  const clock = new THREE.Clock();
  function tick() {
    const dt = Math.min(clock.getDelta(), 0.05), t = clock.elapsedTime;
    const k = 1 - Math.pow(0.0015, dt);
    anim.boxScale += (anim.boxScaleTarget - anim.boxScale) * k;
    boxHolder.visible = anim.boxScale > 0.01;
    const bs = anim.boxScale;
    boxHolder.scale.setScalar(0.6 + 0.4 * bs);
    boxHolder.position.y = (1 - bs) * -0.4;
    if (boxParts) {
      anim.lid += (anim.lidTarget - anim.lid) * (1 - Math.pow(0.02, dt));
      boxParts.lidPivot.rotation.x = anim.lid;
      if (boxParts.bow) {
        anim.bowPop = Math.max(0, (anim.bowPop || 0) - dt * 1.5);
        boxParts.bow.scale.setScalar(1 + Math.sin(anim.bowPop * Math.PI * 3) * 0.12 * anim.bowPop);
      }
    }
    anim.cupPos.lerp(anim.cupPosTarget, k);
    anim.cupScale += (anim.cupScaleTarget - anim.cupScale) * k;
    cupHolder.position.copy(anim.cupPos);
    if (boxHolder.visible && view !== 'cup') cupHolder.position.multiplyScalar(boxHolder.scale.x).add(new THREE.Vector3(0, boxHolder.position.y, 0));
    cupHolder.scale.setScalar(anim.cupScale * (view !== 'cup' && boxHolder.visible ? boxHolder.scale.x : 1));
    if (view === 'cup') cupHolder.position.y += Math.sin(t * 1.4) * 0.015;
    for (const f of flames) { const s = 1 + Math.sin(t * 18) * 0.08 + Math.sin(t * 7.3) * 0.06; f.flame.scale.set(s, 1.9 * s, s); f.light.intensity = 0.5 * s; }
    if (camAnim) {
      camera.position.lerp(camAnim.pos, 1 - Math.pow(0.01, dt));
      controls.target.lerp(camAnim.target, 1 - Math.pow(0.01, dt));
      if (camera.position.distanceTo(camAnim.pos) < 0.01) camAnim = null;
    }
    idle += dt; if (idle > 5 && !controls.autoRotate) controls.autoRotate = true;
    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(tick);
  }
  focus(true); tick();

  function snapshot() { return renderer.domElement.toDataURL('image/png'); }
  function spin() { idle = 6; controls.autoRotate = true; }

  return { setCup, setBox, setView, openGift, closeGift, snapshot, spin, get view() { return view; } };
}
