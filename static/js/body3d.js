/*===============================================================
 * 文件: body3d.js
 * 项目: 健康数据监控（health-monitor）
 * 说明: V0.3 3D 人体大屏（基于 demo-anatomy 渲染器适配）
 *       · 加载 BodyParts3D 4.0 解剖网格（atlas.json + body-*.bin.gz）
 *       · 从 /api/body3d/overview 拉取体检指标聚合结果
 *       · 异常部位：脉冲高亮 + 头顶标注 + 统计面板 + 部位清单
 *       · 仅异常 / 全部部位 两种模式
 *       · 支持 conceptIds 数组；'ALL'=全身，'SKELETAL'=骨骼系统
 * 数据格式与 demo-anatomy 一致（atlas 元数据见 demo-anatomy/js/app.js）
 *===============================================================*/

import * as THREE from 'three';
import { OrbitControls } from '/demo-anatomy/vendor/OrbitControls.js';

const ATLAS_URL = '/demo-anatomy/models/atlas.json';

/* 系统（与 atlas.parts[].system 对应，颜色同 demo） */
const SYSTEMS = [
  { id: 'skeletal',       label: '骨骼',   color: 0xe2d9ba },
  { id: 'muscular',       label: '肌肉',   color: 0xa85b50 },
  { id: 'cardiac',        label: '心脏',   color: 0xb96760 },
  { id: 'sensory',        label: '感官',   color: 0xb0c8ce },
  { id: 'arterial',       label: '动脉',   color: 0xc05245 },
  { id: 'venous',         label: '静脉',   color: 0x527c9f },
  { id: 'nervous',        label: '神经',   color: 0xd8b565 },
  { id: 'respiratory',    label: '呼吸',   color: 0xb98991 },
  { id: 'digestive',      label: '消化',   color: 0xb8916b },
  { id: 'urinary',        label: '泌尿',   color: 0xb47961 },
  { id: 'lymphatic',      label: '淋巴',   color: 0x879f7c },
  { id: 'endocrine',      label: '内分泌', color: 0xc5a09a },
  { id: 'reproductive',   label: '生殖',   color: 0xbda098 },
  { id: 'integumentary',  label: '体表',   color: 0xba9b7d },
  { id: 'connective',     label: '结缔',   color: 0xaec3bb },
];

/* 健康监控相关的器官快捷定位（conceptId -> 中文名） */
const ORGANS = [
  { id: 'FMA7088', zh: '心脏',     en: 'Heart' },
  { id: 'FMA7197', zh: '肝脏',     en: 'Liver' },
  { id: 'FMA7205', zh: '左肾',     en: 'Left kidney' },
  { id: 'FMA7204', zh: '右肾',     en: 'Right kidney' },
  { id: 'FMA7198', zh: '胰腺',     en: 'Pancreas' },
  { id: 'FMA50801', zh: '脑',      en: 'Brain' },
  { id: 'FMA7310', zh: '左肺',     en: 'Left lung' },
  { id: 'FMA7309', zh: '右肺',     en: 'Right lung' },
  { id: 'FMA7148', zh: '胃',       en: 'Stomach' },
  { id: 'FMA7196', zh: '脾',       en: 'Spleen' },
  { id: 'FMA7394', zh: '气管',     en: 'Trachea' },
  { id: 'FMA3734', zh: '主动脉',   en: 'Aorta' },
  { id: 'FMA7131', zh: '食管',     en: 'Esophagus' },
  { id: 'FMA7202', zh: '胆囊',     en: 'Gallbladder' },
  { id: 'FMA9604', zh: '肾上腺',   en: 'Adrenal gland' },
  { id: 'FMA15900', zh: '膀胱',    en: 'Urinary bladder' },
  { id: 'FMA9600', zh: '前列腺',   en: 'Prostate' },
  { id: 'FMA7210', zh: '睾丸',     en: 'Testis' },
  { id: 'FMA46565', zh: '颅骨',    en: 'Skull' },
];

/* 异常等级：严重 / 中度 / 轻度 */
const SEVERITIES = {
  severe:   { label: '严重', color: 0xff4d4f },
  moderate: { label: '中度', color: 0xff9c40 },
  mild:     { label: '轻度', color: 0xffd666 },
};

const state = {
  atlas: null,
  mode: 'abnormal',
  // 支持 ?mode=all 深链直达「全部部位」模式（便于大屏嵌入与调试）
  ...(() => {
    const m = new URLSearchParams(location.search).get('mode');
    return m === 'all' || m === 'abnormal' ? { mode: m } : {};
  })(),
  partIndexById: new Map(),   // part.id -> 数组下标
  partGeometry: new Map(),    // part 下标 -> BufferGeometry（高亮复用）
  systemGeos: new Map(),      // systemId -> BufferGeometry[]（合并前）
  systemMesh: new Map(),      // systemId -> Mesh（合并后）
  systemVisible: {},          // systemId -> boolean
  selectedConceptId: null,
  highlightGroup: null,
  flyTimer: null,
  loadedChunks: 0,
  abnormalityById: new Map(), // conceptId -> ABNORMALITIES 条目
  partByConceptId: new Map(), // conceptId -> overview part（全部模式下正常部位详情用）
  abnormalMeshes: [],         // { mesh, mat, conceptId, phase }
  abnormalSprites: [],        // Sprite[] 头顶标注点
};

const dom = {
  canvasHost: document.getElementById('canvas-host'),
  hint: document.getElementById('hint'),
  progress: document.getElementById('progress'),
  organSelect: document.getElementById('organ-select'),
  partList: document.getElementById('part-list'),
  modeToggle: document.getElementById('mode-toggle'),
  infoBody: document.getElementById('info-body'),
  statsDonut: document.getElementById('stats-donut'),
  statsTotal: document.getElementById('stat-total'),
  statsSevere: document.getElementById('stat-severe'),
  statsModerate: document.getElementById('stat-moderate'),
  statsMild: document.getElementById('stat-mild'),
  recordBtn: document.getElementById('record-btn'),
};

/* ─────────── 录制支持（自动旋转 + canvas 采集，供视频制作）───────────
 * · 点击「录制旋转」或 URL ?record=1（可带 &secs=N）自动录制 N 秒
 * · 用离屏 1280×720 渲染器采集 3D 场景，画面与主视图同步旋转
 * · 输出 WebM（VP9/VP8），供 ffmpeg 转码后嵌入 intro-video
 */
const RECORD_WIDTH = 1280;
const RECORD_HEIGHT = 720;
const RECORD_FPS = 30;
const RECORD_DEFAULT_SECS = 10;
const RECORD_QUERY = new URLSearchParams(location.search).get('record');
const RECORD_SECS = Number(new URLSearchParams(location.search).get('secs')) || RECORD_DEFAULT_SECS;

let recRenderer = null;      // 离屏 WebGLRenderer（仅录制用）
let recCamera = null;        // 录制专用相机（16:9，跟随主相机）
let recMediaRecorder = null;
let recChunks = [];
let recTimer = null;
let recTickTimer = null;
let recording = false;

/* ─────────── Three.js 场景 ─────────── */

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b1020);

const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 30);
camera.position.set(1.0, 1.1, 1.35);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.1;
dom.canvasHost.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.minDistance = 0.2;
controls.maxDistance = 3.5;
controls.target.set(0, 0.92, 0);
controls.update();

/* 灯光（同 demo） */
scene.add(new THREE.HemisphereLight(0xffffff, 0xa7acb2, 1.05));
const keyLight = new THREE.DirectionalLight(0xfffaf4, 2.3);
keyLight.position.set(-2, 4, 3);
scene.add(keyLight);
const rimLight = new THREE.DirectionalLight(0xe9f0ff, 1.8);
rimLight.position.set(2, 2, -3);
scene.add(rimLight);

/* 展示平台 */
const ground = new THREE.Mesh(
  new THREE.CircleGeometry(30, 96),
  new THREE.MeshStandardMaterial({ color: 0xd5d9dc, roughness: 1 })
);
ground.rotation.x = -Math.PI / 2;
ground.position.y = -0.019;
scene.add(ground);

const platform = new THREE.Mesh(
  new THREE.CylinderGeometry(0.68, 0.7, 0.028, 100),
  new THREE.MeshStandardMaterial({ color: 0xeeeeec, metalness: 0.12, roughness: 0.67 })
);
platform.position.y = -0.016;
scene.add(platform);

const ring = new THREE.Mesh(
  new THREE.RingGeometry(0.63, 0.632, 128),
  new THREE.MeshBasicMaterial({ color: 0x8c969f, transparent: true, opacity: 0.4, side: THREE.DoubleSide })
);
ring.rotation.x = -Math.PI / 2;
ring.position.y = 0.001;
scene.add(ring);

const innerRing = new THREE.Mesh(
  new THREE.RingGeometry(0.55, 0.551, 128),
  new THREE.MeshBasicMaterial({ color: 0xa4aeb8, transparent: true, opacity: 0.16, side: THREE.DoubleSide })
);
innerRing.rotation.x = -Math.PI / 2;
innerRing.position.y = 0.001;
scene.add(innerRing);

/* ─────────── 几何构建 ─────────── */

function createPartGeometry(part, partIndex, buffer) {
  const geo = new THREE.BufferGeometry();
  geo.setAttribute(
    'position',
    new THREE.BufferAttribute(new Float32Array(buffer, part.positions, part.vertexCount * 3), 3)
  );
  geo.setAttribute(
    'normal',
    new THREE.BufferAttribute(new Int16Array(buffer, part.normals, part.vertexCount * 3), 3, true)
  );
  geo.setIndex(new THREE.BufferAttribute(new Uint32Array(buffer, part.indices, part.indexCount), 1));
  geo.setAttribute('partIndex', new THREE.BufferAttribute(new Float32Array(part.vertexCount).fill(partIndex), 1));
  geo.computeBoundingSphere();
  return geo;
}

function mergePartGeometries(list) {
  let totalV = 0;
  let totalI = 0;
  for (const g of list) {
    totalV += g.attributes.position.count;
    totalI += g.index.count;
  }
  const pos = new Float32Array(totalV * 3);
  const norm = new Int16Array(totalV * 3);
  const partIdx = new Float32Array(totalV);
  const index = new Uint32Array(totalI);
  let vo = 0;
  let io = 0;
  for (const g of list) {
    pos.set(g.attributes.position.array, vo * 3);
    norm.set(g.attributes.normal.array, vo * 3);
    partIdx.set(g.attributes.partIndex.array, vo);
    const gi = g.index.array;
    for (let i = 0; i < gi.length; i++) index[io + i] = gi[i] + vo;
    vo += g.attributes.position.count;
    io += gi.length;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('normal', new THREE.BufferAttribute(norm, 3, true));
  geo.setAttribute('partIndex', new THREE.BufferAttribute(partIdx, 1));
  geo.setIndex(new THREE.BufferAttribute(index, 1));
  geo.computeBoundingSphere();
  return geo;
}

function makeSystemMaterial(sys) {
  const isSurface = sys.id === 'integumentary';
  return new THREE.MeshStandardMaterial({
    color: sys.color,
    metalness: 0.08,
    roughness: 0.53,
    side: THREE.DoubleSide,
    transparent: isSurface,
    opacity: isSurface ? 0.1 : 1,
    depthWrite: !isSurface,
  });
}

function buildSystemMeshes() {
  for (const sys of SYSTEMS) {
    const geos = state.systemGeos.get(sys.id);
    if (!geos || !geos.length) continue;
    const geo = mergePartGeometries(geos);
    const mat = makeSystemMaterial(sys);
    const mesh = new THREE.Mesh(geo, mat);
    mesh.frustumCulled = false;
    mesh.userData.system = sys.id;
    mesh.userData.baseMat = { transparent: mat.transparent, opacity: mat.opacity, depthWrite: mat.depthWrite };
    scene.add(mesh);
    state.systemMesh.set(sys.id, mesh);
  }
}

/* ─────────── 数据加载 ─────────── */

async function loadChunk(ci) {
  const chunk = state.atlas.chunks[ci];
  const atlasUrl = new URL(ATLAS_URL, location.href);
  const url = new URL(chunk.gzip || chunk.url, atlasUrl).href;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`加载分块 ${ci} 失败: HTTP ${res.status}`);
  const compressed = await res.arrayBuffer();
  let buffer;
  if (chunk.gzip && typeof DecompressionStream !== 'undefined') {
    const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream('gzip'));
    buffer = await new Response(stream).arrayBuffer();
  } else {
    buffer = compressed;
  }
  const parts = state.atlas.parts.filter((p) => p.chunk === ci);
  for (const part of parts) {
    const idx = state.partIndexById.get(part.id);
    const geo = createPartGeometry(part, idx, buffer);
    state.partGeometry.set(idx, geo);
    let list = state.systemGeos.get(part.system);
    if (!list) {
      list = [];
      state.systemGeos.set(part.system, list);
    }
    list.push(geo);
  }
}

function updateProgress() {
  state.loadedChunks += 1;
  const total = state.atlas.chunks.length;
  if (state.loadedChunks >= total) {
    dom.progress.textContent = '模型已就绪';
    dom.progress.dataset.state = 'ready';
    dom.hint.classList.add('hidden');
    dom.organSelect.disabled = false;
  } else {
    dom.progress.textContent = `模型加载 ${state.loadedChunks}/${total}`;
  }
}

async function loadAll() {
  const res = await fetch(ATLAS_URL);
  if (!res.ok) throw new Error(`加载 atlas.json 失败: HTTP ${res.status}`);
  state.atlas = await res.json();

  for (const sys of SYSTEMS) state.systemVisible[sys.id] = true;
  state.atlas.parts.forEach((p, i) => state.partIndexById.set(p.id, i));

  buildOrganSelect();

  await Promise.all(state.atlas.chunks.map((_, ci) => loadChunk(ci).then(updateProgress)));
  buildSystemMeshes();
  onResize();
  fitAll();
  animate();

  await loadOverview(state.mode);

  /* ?record=1 深链：模型与热点就绪后自动开始录制（视频制作用） */
  if (RECORD_QUERY !== null) {
    setTimeout(() => startRecording(), 1200);
  }
}

/* ─────────── 拾取与选择 ─────────── */

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let downPos = null;

renderer.domElement.addEventListener('pointerdown', (e) => {
  downPos = [e.clientX, e.clientY];
});

renderer.domElement.addEventListener('pointerup', (e) => {
  if (!downPos) return;
  const dx = e.clientX - downPos[0];
  const dy = e.clientY - downPos[1];
  downPos = null;
  if (dx * dx + dy * dy > 25) return; // 拖拽不触发
  pick(e);
});

function pick(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);

  /* 异常标注点（Sprite）优先拾取 */
  if (state.abnormalSprites.length) {
    const spriteHits = raycaster.intersectObjects(state.abnormalSprites, false);
    if (spriteHits.length) {
      selectConcept(spriteHits[0].object.userData.conceptId);
      return;
    }
  }

  const meshes = [...state.systemMesh.values()].filter((m) => m.visible);
  const hits = raycaster.intersectObjects(meshes, false);
  if (hits.length) {
    const hit = hits[0];
    const partIndex = hit.object.geometry.getAttribute('partIndex').getX(hit.face.a);
    const part = state.atlas.parts[partIndex];
    selectConcept(part.conceptId);
  } else {
    selectConcept(null);
  }
}

/** 概念对应的部件下标列表；'ALL'=全部部件，'SKELETAL'=骨骼系统 */
function conceptPartIndices(conceptId) {
  if (conceptId === 'ALL') {
    return state.atlas.parts.map((_, i) => i);
  }
  if (conceptId === 'SKELETAL') {
    const indices = [];
    state.atlas.parts.forEach((p, i) => {
      if (p.system === 'skeletal') indices.push(i);
    });
    return indices;
  }
  const concept = state.atlas.concepts.find((c) => c.id === conceptId);
  const indices = [];
  if (concept) {
    for (const elementId of concept.elements) {
      const idx = state.partIndexById.get(elementId);
      if (idx !== undefined) indices.push(idx);
    }
  }
  if (!indices.length) {
    state.atlas.parts.forEach((p, i) => {
      if (p.conceptId === conceptId) indices.push(i);
    });
  }
  return indices;
}

function selectConcept(conceptId) {
  state.selectedConceptId = conceptId;

  /* 清理旧高亮组 */
  if (state.highlightGroup) {
    scene.remove(state.highlightGroup);
    disposeObject(state.highlightGroup);
    state.highlightGroup = null;
  }

  applyFocus();

  if (conceptId) {
    const partIndices = conceptPartIndices(conceptId);
    if (partIndices.length) {
      buildHighlight(partIndices);
      flyToBounds(partIndices);
    }
  } else {
    fitAll();
  }

  updateInfo(conceptId);
}

function applyFocus() {
  const hasFocus = !!state.selectedConceptId;
  for (const mesh of state.systemMesh.values()) {
    const base = mesh.userData.baseMat;
    const mat = mesh.material;
    if (hasFocus) {
      mat.opacity = 0.08;
      mat.transparent = true;
      mat.depthWrite = false;
    } else {
      mat.opacity = base.opacity;
      mat.transparent = base.transparent;
      mat.depthWrite = base.depthWrite;
    }
  }
}

function buildHighlight(partIndices) {
  const group = new THREE.Group();
  const mat = new THREE.MeshStandardMaterial({
    color: 0x38bdf8,
    emissive: 0x0c4a6e,
    emissiveIntensity: 0.55,
    metalness: 0.05,
    roughness: 0.3,
    side: THREE.DoubleSide,
  });
  for (const i of partIndices) {
    const geo = state.partGeometry.get(i);
    if (!geo) continue;
    const mesh = new THREE.Mesh(geo, mat);
    mesh.userData.partIndex = i;
    group.add(mesh);
  }
  scene.add(group);
  state.highlightGroup = group;
}

function disposeObject(obj) {
  obj.traverse((child) => {
    if (child.isMesh) {
      child.geometry?.dispose?.();
      if (Array.isArray(child.material)) child.material.forEach((m) => m.dispose());
      else child.material?.dispose?.();
    }
  });
}

/* ─────────── 相机飞行 ─────────── */

function overallBounds() {
  let min = new THREE.Vector3(Infinity, Infinity, Infinity);
  let max = new THREE.Vector3(-Infinity, -Infinity, -Infinity);
  for (const p of state.atlas.parts) {
    const a = new THREE.Vector3().fromArray(p.bounds[0]);
    const b = new THREE.Vector3().fromArray(p.bounds[1]);
    min.min(a).min(b);
    max.max(a).max(b);
  }
  return { min, max, center: min.clone().add(max).multiplyScalar(0.5), size: max.clone().sub(min) };
}

function flyToBounds(partIndices) {
  let min = new THREE.Vector3(Infinity, Infinity, Infinity);
  let max = new THREE.Vector3(-Infinity, -Infinity, -Infinity);
  for (const i of partIndices) {
    const p = state.atlas.parts[i];
    const a = new THREE.Vector3().fromArray(p.bounds[0]);
    const b = new THREE.Vector3().fromArray(p.bounds[1]);
    min.min(a).min(b);
    max.max(a).max(b);
  }
  const center = min.clone().add(max).multiplyScalar(0.5);
  const size = max.clone().sub(min);
  const radius = Math.max(size.length() * 0.9, 0.4);
  flyCameraTo(center, radius);
}

function fitAll() {
  const { center, size } = overallBounds();
  flyCameraTo(center, size.length() * 1.15);
}

function flyCameraTo(center, radius) {
  const dir = new THREE.Vector3().subVectors(camera.position, controls.target).normalize();
  const endPos = center.clone().add(dir.multiplyScalar(radius));
  const startPos = camera.position.clone();
  const startTarget = controls.target.clone();
  const endTarget = center.clone();
  const duration = 800;
  const t0 = performance.now();
  if (state.flyTimer) cancelAnimationFrame(state.flyTimer);

  function tick(now) {
    const t = Math.min(1, (now - t0) / duration);
    const e = 1 - Math.pow(1 - t, 3); // easeOutCubic
    camera.position.lerpVectors(startPos, endPos, e);
    controls.target.lerpVectors(startTarget, endTarget, e);
    controls.update();
    if (t < 1) state.flyTimer = requestAnimationFrame(tick);
    else state.flyTimer = null;
  }
  state.flyTimer = requestAnimationFrame(tick);
}

/* ─────────── 异常部位叠加 ─────────── */

function boundsOfIndices(indices) {
  let min = new THREE.Vector3(Infinity, Infinity, Infinity);
  let max = new THREE.Vector3(-Infinity, -Infinity, -Infinity);
  for (const i of indices) {
    const p = state.atlas.parts[i];
    min.min(new THREE.Vector3().fromArray(p.bounds[0]));
    max.max(new THREE.Vector3().fromArray(p.bounds[1]));
  }
  return { min, max };
}

function makeMarkerSprite(ab, topPos) {
  const color = SEVERITIES[ab.severity].color;
  const hex = '#' + color.toString(16).padStart(6, '0');
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 96;
  const ctx = canvas.getContext('2d');
  const cx = 22, cy = 48, r = 17;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fillStyle = hex;
  ctx.shadowColor = hex;
  ctx.shadowBlur = 16;
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.lineWidth = 3;
  ctx.strokeStyle = 'rgba(255,255,255,0.85)';
  ctx.stroke();
  ctx.font = 'bold 36px "Microsoft YaHei", sans-serif';
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'left';
  ctx.fillStyle = '#ffffff';
  ctx.shadowColor = 'rgba(0,0,0,0.85)';
  ctx.shadowBlur = 6;
  ctx.fillText(ab.name, cx + r + 14, cy);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true }));
  sprite.scale.set(0.24, 0.09, 1);
  sprite.position.copy(topPos);
  sprite.userData.conceptId = ab.conceptId;
  return sprite;
}

/** 后端 overview parts → 异常条目列表（每个 conceptId 展开一条） */
function overviewToAbnormalities(parts) {
  const list = [];
  for (const part of parts) {
    if (!part.abnormal) continue;
    for (const cid of part.conceptIds || []) {
      list.push({
        conceptId: cid,
        name: part.name,
        severity: part.severity,
        severityReason: part.severity_reason || '',
        issues: part.issues || [],
        records: part.records || [],
        note: part.note || '',
        key: part.key,
      });
    }
  }
  return list;
}

/** 清除旧异常标注（切模式时重建） */
function clearAbnormalities() {
  for (const item of state.abnormalMeshes) {
    scene.remove(item.mesh);
    disposeObject(item.mesh);
  }
  for (const sp of state.abnormalSprites) scene.remove(sp);
  state.abnormalMeshes = [];
  state.abnormalSprites = [];
  state.abnormalityById.clear();
  dom.partList.replaceChildren();
  dom.statsDonut.replaceChildren();
}

/** 应用异常列表：脉冲网格 + 标注点 + 统计 + 部位清单 */
function applyAbnormalities(abList) {
  for (const ab of abList) {
    const indices = conceptPartIndices(ab.conceptId);
    if (!indices.length) continue;
    const geos = indices.map((i) => state.partGeometry.get(i)).filter(Boolean);
    if (!geos.length) continue;
    state.abnormalityById.set(ab.conceptId, ab);

    const sysId = state.atlas.parts[indices[0]].system;
    const sys = SYSTEMS.find((s) => s.id === sysId);
    const mat = new THREE.MeshStandardMaterial({
      color: sys ? sys.color : 0xffffff,
      emissive: SEVERITIES[ab.severity].color,
      emissiveIntensity: 0,
      metalness: 0.05,
      roughness: 0.4,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const mesh = new THREE.Mesh(mergePartGeometries(geos), mat);
    mesh.renderOrder = 10;
    mesh.userData.conceptId = ab.conceptId;
    scene.add(mesh);

    /* 同一 conceptId（如 'ALL' 被血液/全身共用）只放一个标注点，避免重叠 */
    const alreadyMarked = state.abnormalSprites.some((sp) => sp.userData.conceptId === ab.conceptId);
    if (!alreadyMarked) {
      const { min, max } = boundsOfIndices(indices);
      const top = new THREE.Vector3(
        min.x + (max.x - min.x) * 0.5,
        max.y + 0.035,
        min.z + (max.z - min.z) * 0.5
      );
      const sprite = makeMarkerSprite(ab, top);
      scene.add(sprite);
      state.abnormalSprites.push(sprite);
    }

    state.abnormalMeshes.push({
      mesh, mat,
      conceptId: ab.conceptId,
      phase: state.abnormalMeshes.length * 1.7,
    });
  }
  updateStats();
}

/** 左栏部位清单（异常模式：仅异常部位；全部模式：所有部位） */
function buildPartList(parts) {
  dom.partList.replaceChildren();
  if (!parts.length) {
    const p = document.createElement('p');
    p.className = 'muted';
    p.textContent = state.mode === 'abnormal' ? '暂无异常部位' : '暂无部位数据';
    dom.partList.appendChild(p);
    return;
  }
  for (const part of parts) {
    const item = document.createElement('div');
    const hasData = !!(part.issues && part.issues.length);
    item.className = 'part-item' + (part.abnormal ? ' abnormal' : ' normal');
    item.title = part.abnormal
      ? `点击定位${part.name}（${SEVERITIES[part.severity].label}）`
      : hasData
        ? `点击查看${part.name}指标`
        : `点击查看${part.name}结构`;
    const dot = document.createElement('span');
    dot.className = 'part-dot';
    if (part.abnormal) {
      dot.style.background = '#' + SEVERITIES[part.severity].color.toString(16).padStart(6, '0');
    } else if (hasData) {
      dot.style.background = 'var(--ok)';
    } else {
      dot.style.background = 'var(--text-3)';
    }
    const name = document.createElement('span');
    name.className = 'part-name';
    name.textContent = part.name;
    const count = document.createElement('span');
    count.className = 'part-count';
    if (part.abnormal) count.textContent = `${(part.issues || []).length} 项`;
    else if (hasData) count.textContent = '正常';
    else count.textContent = '暂无数据';
    item.append(dot, name, count);
    item.addEventListener('click', () => {
      const ids = part.conceptIds || [];
      if (ids.length) selectConcept(ids[0]);
    });
    dom.partList.appendChild(item);
  }
}

/** 拉取 overview 数据并按模式重建标注与清单 */
async function loadOverview(mode) {
  try {
    const res = await fetch(`/api/body3d/overview?mode=${encodeURIComponent(mode)}`);
    if (res.status === 401) {
      dom.hint.textContent = '请先在主界面登录后再打开 3D 大屏';
      dom.hint.classList.remove('hidden');
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const payload = await res.json();
    const parts = (payload.data && payload.data.parts) || [];

    clearAbnormalities();
    state.mode = mode;
    state.partByConceptId = new Map();
    for (const part of parts) {
      for (const cid of part.conceptIds || []) {
        if (!state.partByConceptId.has(cid)) state.partByConceptId.set(cid, part);
      }
    }
    buildPartList(parts);
    applyAbnormalities(overviewToAbnormalities(parts));
    dom.hint.classList.add('hidden');
  } catch (err) {
    console.error(err);
    dom.hint.textContent = `大屏数据加载失败：${err.message}`;
    dom.hint.classList.remove('hidden');
  }
}

/* ─────────── 异常概览统计 ─────────── */

function updateStats() {
  const counts = { severe: 0, moderate: 0, mild: 0 };
  // 按 body_part（key）去重统计，与左栏部位清单保持一致：
  // 左右肾同属「肾脏」一个部位，不因 conceptIds 展开而重复计数
  const seenKeys = new Set();
  for (const ab of state.abnormalityById.values()) {
    if (seenKeys.has(ab.key)) continue;
    seenKeys.add(ab.key);
    counts[ab.severity] += 1;
  }
  dom.statsTotal.textContent = String(counts.severe + counts.moderate + counts.mild);
  dom.statsSevere.textContent = String(counts.severe);
  dom.statsModerate.textContent = String(counts.moderate);
  dom.statsMild.textContent = String(counts.mild);
  renderDonutChart(counts);
}

function renderDonutChart(counts) {
  const total = counts.severe + counts.moderate + counts.mild;
  dom.statsDonut.replaceChildren();

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const R = 38;
  const C = 2 * Math.PI * R;
  const GAP_DEG = 3;
  const GAP_LEN = (GAP_DEG * Math.PI / 180) * R;
  const LEVELS = [
    { key: 'severe',   label: '严重', color: 'var(--severe)' },
    { key: 'moderate', label: '中度', color: 'var(--moderate)' },
    { key: 'mild',     label: '轻度', color: 'var(--mild)' },
  ];

  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', 'donut-chart');
  svg.setAttribute('viewBox', '0 0 100 100');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', `异常严重程度分布，共 ${total} 个异常部位`);

  const track = document.createElementNS(SVG_NS, 'circle');
  track.setAttribute('cx', '50');
  track.setAttribute('cy', '50');
  track.setAttribute('r', String(R));
  track.setAttribute('fill', 'none');
  track.setAttribute('stroke', 'rgba(148, 163, 184, 0.08)');
  track.setAttribute('stroke-width', '11');
  svg.appendChild(track);

  let offset = 0;
  for (const lv of LEVELS) {
    const n = counts[lv.key];
    if (!n) continue;
    const frac = n / total;
    const segLen = Math.max(frac * C - GAP_LEN, 0.5);
    const arc = document.createElementNS(SVG_NS, 'circle');
    arc.setAttribute('cx', '50');
    arc.setAttribute('cy', '50');
    arc.setAttribute('r', String(R));
    arc.setAttribute('fill', 'none');
    arc.setAttribute('stroke', lv.color);
    arc.setAttribute('stroke-width', '11');
    arc.setAttribute('stroke-dasharray', `${segLen} ${C - segLen}`);
    arc.setAttribute('stroke-dashoffset', String(-offset));
    arc.setAttribute('transform', 'rotate(-90 50 50)');
    arc.classList.add('donut-seg', lv.key);
    svg.appendChild(arc);
    offset += frac * C;
  }

  const totalText = document.createElementNS(SVG_NS, 'text');
  totalText.setAttribute('x', '50');
  totalText.setAttribute('y', '53');
  totalText.setAttribute('class', 'donut-total');
  totalText.textContent = String(total || 0);
  svg.appendChild(totalText);

  const cap = document.createElementNS(SVG_NS, 'text');
  cap.setAttribute('x', '50');
  cap.setAttribute('y', '65');
  cap.setAttribute('class', 'donut-cap');
  cap.textContent = '异常部位';
  svg.appendChild(cap);

  dom.statsDonut.appendChild(svg);

  const legend = document.createElement('ul');
  legend.className = 'donut-legend';
  for (const lv of LEVELS) {
    const n = counts[lv.key];
    const li = document.createElement('li');
    li.className = `legend-item ${lv.key}`;
    const dot = document.createElement('span');
    dot.className = 'legend-dot';
    const nameEl = document.createElement('span');
    nameEl.className = 'l-name';
    nameEl.textContent = lv.label;
    const countEl = document.createElement('span');
    countEl.className = 'l-count';
    countEl.textContent = String(n);
    const pctEl = document.createElement('span');
    pctEl.className = 'l-pct';
    pctEl.textContent = n ? `${Math.round((n / total) * 100)}%` : '0%';
    li.append(dot, nameEl, countEl, pctEl);

    if (n) {
      li.title = `点击定位${lv.label}异常部位`;
      li.addEventListener('click', () => {
        const target = [...state.abnormalityById.values()].find(
          (ab) => ab.severity === lv.key
        );
        if (target) selectConcept(target.conceptId);
      });
    } else {
      li.style.cursor = 'default';
      li.style.opacity = '0.4';
    }
    legend.appendChild(li);
  }
  dom.statsDonut.appendChild(legend);
}

/* ─────────── UI 构建 ─────────── */

function buildOrganSelect() {
  const first = document.createElement('option');
  first.value = '';
  first.textContent = '选择器官定位…';
  dom.organSelect.appendChild(first);

  for (const organ of ORGANS) {
    const hasConcept = state.atlas.concepts.some((c) => c.id === organ.id);
    if (!hasConcept) continue;
    const option = document.createElement('option');
    option.value = organ.id;
    option.textContent = `${organ.zh} · ${organ.en}`;
    dom.organSelect.appendChild(option);
  }
  dom.organSelect.disabled = true;

  dom.organSelect.addEventListener('change', () => {
    const id = dom.organSelect.value;
    selectConcept(id || null);
    if (id) dom.organSelect.value = '';
  });
}

dom.modeToggle.addEventListener('click', (e) => {
  const btn = e.target.closest('.mode-btn');
  if (!btn || btn.classList.contains('active')) return;
  for (const b of dom.modeToggle.querySelectorAll('.mode-btn')) {
    b.classList.toggle('active', b === btn);
  }
  loadOverview(btn.dataset.mode);
});

/* 初始化：按 URL ?mode= 同步活动按钮（默认 abnormal） */
dom.modeToggle.querySelectorAll('.mode-btn').forEach((b) => {
  b.classList.toggle('active', b.dataset.mode === state.mode);
});

/* ─────────── 详情面板 ─────────── */

function updateInfo(conceptId) {
  dom.infoBody.replaceChildren();

  if (!conceptId) {
    const p = document.createElement('p');
    p.className = 'muted';
    p.textContent = '点击任意器官查看详情；或从上方下拉框快捷定位。';
    dom.infoBody.appendChild(p);
    return;
  }

  const ab = state.abnormalityById.get(conceptId);
  if (ab) {
    renderAbnormalDetail(ab, conceptId);
    return;
  }
  const part = state.partByConceptId.get(conceptId);
  if (part) {
    renderPartDetail(part, conceptId);
    return;
  }
  renderNormalDetail(conceptId);
}

function renderIssuesSection(issues) {
  const sec = document.createElement('section');
  sec.className = 'ab-section';
  const h = document.createElement('h4');
  h.textContent = '指标';
  sec.appendChild(h);
  if (!issues || !issues.length) {
    const p = document.createElement('p');
    p.className = 'muted';
    p.textContent = '暂无指标数据';
    sec.appendChild(p);
    return sec;
  }
  for (const issue of issues) {
    const row = document.createElement('div');
    row.className = 'ab-issue';
    const nameEl = document.createElement('span');
    nameEl.className = 'name';
    nameEl.textContent = issue.name;
    const valueEl = document.createElement('span');
    valueEl.className = 'value';
    valueEl.textContent = issue.unit ? `${issue.value} ${issue.unit}` : issue.value;
    const rangeEl = document.createElement('span');
    rangeEl.className = 'range';
    rangeEl.textContent = issue.range || '';
    const flagEl = document.createElement('span');
    flagEl.className = 'flag';
    /* 正常/异常不同颜色；偏高 ↑、偏低 ↓ */
    const arrow = issue.status === '偏高' ? '↑ ' : issue.status === '偏低' ? '↓ ' : '';
    flagEl.textContent = arrow + (issue.status || '');
    if (issue.status === '偏高') flagEl.classList.add('status-high');
    else if (issue.status === '偏低') flagEl.classList.add('status-low');
    else if (issue.status === '异常') flagEl.classList.add('status-abnormal');
    else if (issue.status === '正常') flagEl.classList.add('status-normal');
    row.append(nameEl, valueEl, rangeEl, flagEl);
    sec.appendChild(row);
  }
  return sec;
}

function renderRecordsSection(records) {
  const RECORDS_PREVIEW = 3;
  const sec = document.createElement('section');
  sec.className = 'ab-section';
  const h = document.createElement('h4');
  h.textContent = `检查记录（${records.length} 次）`;
  sec.appendChild(h);

  const timeline = document.createElement('div');
  timeline.className = 'ab-timeline';
  records.forEach((rec, i) => {
    const card = document.createElement('div');
    card.className = 'ab-record';
    if (i >= RECORDS_PREVIEW) card.classList.add('record-hidden');
    const head = document.createElement('div');
    head.className = 'head';
    const date = document.createElement('span');
    date.className = 'date';
    date.textContent = rec.date;
    const type = document.createElement('span');
    type.textContent = rec.type;
    head.append(date, type);
    const summary = document.createElement('div');
    summary.className = 'summary';
    summary.textContent = rec.summary;
    const conclusion = document.createElement('div');
    conclusion.className = 'conclusion';
    conclusion.textContent = rec.conclusion ? `▸ ${rec.conclusion}` : '';
    card.append(head, summary, conclusion);
    timeline.appendChild(card);
  });
  sec.appendChild(timeline);

  if (records.length > RECORDS_PREVIEW) {
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'records-toggle';
    const arrow = document.createElement('span');
    arrow.className = 'toggle-arrow';
    toggle.append(arrow, document.createTextNode(`展开全部 ${records.length} 条记录`));
    toggle.addEventListener('click', () => {
      const isOpen = toggle.classList.contains('open');
      const hidden = timeline.querySelectorAll('.record-hidden');
      hidden.forEach((el) => el.classList.toggle('record-hidden', isOpen));
      toggle.classList.toggle('open', !isOpen);
      toggle.lastChild.textContent = isOpen
        ? `展开全部 ${records.length} 条记录`
        : '收起记录';
    });
    sec.appendChild(toggle);
  }
  return sec;
}

function appendBaseInfo(conceptId) {
  const parts = conceptPartIndices(conceptId).map((i) => state.atlas.parts[i]);
  let triangles = 0;
  let min = [Infinity, Infinity, Infinity];
  let max = [-Infinity, -Infinity, -Infinity];
  for (const p of parts) {
    triangles += p.indexCount / 3;
    for (let i = 0; i < 3; i++) {
      min[i] = Math.min(min[i], p.bounds[0][i], p.bounds[1][i]);
      max[i] = Math.max(max[i], p.bounds[0][i], p.bounds[1][i]);
    }
  }
  const size = max.map((v, i) => (v - min[i]).toFixed(3));

  const rows = [
    ['部件数', `${parts.length}`],
    ['三角面', `${triangles.toLocaleString()}`],
    ['尺寸 (cm)', `${size.join(' × ')}`],
  ];
  for (const [k, v] of rows) {
    const row = document.createElement('div');
    row.className = 'info-row';
    const kEl = document.createElement('span');
    kEl.textContent = k;
    const vEl = document.createElement('span');
    vEl.textContent = v;
    row.append(kEl, vEl);
    dom.infoBody.appendChild(row);
  }
}

/** 异常部位详情：异常指标 + 检查记录 + 综合建议 */
function renderAbnormalDetail(ab, conceptId) {
  const organMeta = ORGANS.find((o) => o.id === conceptId);
  const concept = state.atlas.concepts.find((c) => c.id === conceptId);
  const sev = SEVERITIES[ab.severity];

  const name = document.createElement('h3');
  name.className = 'info-name';
  name.textContent = ab.name;
  const badge = document.createElement('span');
  badge.className = `ab-badge ${ab.severity}`;
  badge.textContent = sev.label;
  name.appendChild(badge);
  dom.infoBody.appendChild(name);

  if (ab.severityReason) {
    const reason = document.createElement('div');
    reason.className = 'severity-reason';
    reason.textContent = `AI 判定：${ab.severityReason}`;
    dom.infoBody.appendChild(reason);
  }

  const sysLabel = document.createElement('span');
  sysLabel.className = 'info-system';
  if (ab.conceptId === 'ALL' || ab.conceptId === 'SKELETAL') {
    sysLabel.textContent = ab.name;
  } else {
    sysLabel.textContent = organMeta ? organMeta.en : concept ? concept.name : conceptId;
  }
  dom.infoBody.appendChild(sysLabel);

  dom.infoBody.appendChild(renderIssuesSection(ab.issues));
  if (ab.records && ab.records.length) {
    dom.infoBody.appendChild(renderRecordsSection(ab.records));
  }
  if (ab.note) {
    const note = document.createElement('div');
    note.className = 'ab-note';
    const strong = document.createElement('strong');
    strong.textContent = '健康建议：';
    note.append(strong, document.createTextNode(ab.note));
    dom.infoBody.appendChild(note);
  }

  appendBaseInfo(conceptId);
}

/** 全部模式下的正常/异常部位详情：展示该部位全部指标 */
function renderPartDetail(part, conceptId) {
  const sev = part.abnormal ? SEVERITIES[part.severity] : null;

  const name = document.createElement('h3');
  name.className = 'info-name';
  name.textContent = part.name;
  if (sev) {
    const badge = document.createElement('span');
    badge.className = `ab-badge ${part.severity}`;
    badge.textContent = sev.label;
    name.appendChild(badge);
  } else {
    const badge = document.createElement('span');
    badge.className = 'ab-badge ok';
    badge.textContent = (part.issues && part.issues.length) ? '正常' : '暂无数据';
    name.appendChild(badge);
  }
  dom.infoBody.appendChild(name);

  const sysLabel = document.createElement('span');
  sysLabel.className = 'info-system';
  sysLabel.textContent = part.name;
  dom.infoBody.appendChild(sysLabel);

  dom.infoBody.appendChild(renderIssuesSection(part.issues || []));
  if (part.records && part.records.length) {
    dom.infoBody.appendChild(renderRecordsSection(part.records));
  }
  if (part.note) {
    const note = document.createElement('div');
    note.className = 'ab-note';
    const strong = document.createElement('strong');
    strong.textContent = part.abnormal ? '健康建议：' : '说明：';
    note.append(strong, document.createTextNode(part.note));
    dom.infoBody.appendChild(note);
  }

  appendBaseInfo(conceptId);
}

/** 正常部位详情：基础结构信息 */
function renderNormalDetail(conceptId) {
  const parts = conceptPartIndices(conceptId).map((i) => state.atlas.parts[i]);
  const organMeta = ORGANS.find((o) => o.id === conceptId);
  const concept = state.atlas.concepts.find((c) => c.id === conceptId);
  const systemSet = new Set(parts.map((p) => p.system));

  const name = document.createElement('h3');
  name.className = 'info-name';
  name.textContent = organMeta
    ? `${organMeta.zh} ${organMeta.en}`
    : concept
      ? concept.name
      : conceptId;
  dom.infoBody.appendChild(name);

  const sysLabel = document.createElement('span');
  sysLabel.className = 'info-system';
  sysLabel.textContent = [...systemSet]
    .map((s) => SYSTEMS.find((x) => x.id === s)?.label || s)
    .join(' / ');
  dom.infoBody.appendChild(sysLabel);

  appendBaseInfo(conceptId);

  const note = document.createElement('p');
  note.className = 'info-note';
  note.textContent = '数据来源 BodyParts3D 4.0（CC BY 4.0），网格经 meshoptimizer 简化。';
  dom.infoBody.appendChild(note);
}

/* ─────────── 渲染循环 / 自适应 ─────────── */

function onResize() {
  const w = dom.canvasHost.clientWidth;
  const h = dom.canvasHost.clientHeight;
  if (!w || !h) return;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
}

window.addEventListener('resize', onResize);

function animate() {
  requestAnimationFrame(animate);
  const t = performance.now() * 0.001;
  for (const item of state.abnormalMeshes) {
    const pulse = 0.5 + 0.5 * Math.sin(t * 2.6 + item.phase);
    item.mat.emissiveIntensity = 0.25 + 0.9 * pulse;
  }
  controls.update();
  renderer.render(scene, camera);
  if (recording && recRenderer && recCamera) {
    syncRecCamera();
    recRenderer.render(scene, recCamera);
  }
}

/* ─────────── 录制旋转（自动旋转 + canvas 采集）─────────── */

function syncRecCamera() {
  if (!recCamera) return;
  recCamera.position.copy(camera.position);
  recCamera.up.copy(camera.up);
  recCamera.lookAt(controls.target);
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function startRecording() {
  if (recording) return;
  if (!state.atlas) {
    dom.hint.textContent = '模型尚未就绪，请稍候再试';
    dom.hint.classList.remove('hidden');
    return;
  }

  recording = true;

  /* 离屏 1280×720 渲染器：只采集 3D 场景，不含页面 UI */
  recRenderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  recRenderer.setPixelRatio(1);
  recRenderer.setSize(RECORD_WIDTH, RECORD_HEIGHT);
  recRenderer.outputColorSpace = THREE.SRGBColorSpace;
  recRenderer.toneMapping = THREE.ACESFilmicToneMapping;
  recRenderer.toneMappingExposure = renderer.toneMappingExposure;

  recCamera = new THREE.PerspectiveCamera(45, RECORD_WIDTH / RECORD_HEIGHT, 0.01, 30);
  syncRecCamera();

  /* 自动旋转：autoRotateSpeed 6 ≈ 10 秒/圈（默认 2 = 30 秒/圈） */
  controls.autoRotate = true;
  controls.autoRotateSpeed = 6.0;

  const stream = recRenderer.domElement.captureStream(RECORD_FPS);
  const mimeType = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm']
    .find((t) => typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(t));
  recChunks = [];
  recMediaRecorder = new MediaRecorder(
    stream,
    mimeType ? { mimeType, videoBitsPerSecond: 8_000_000 } : undefined
  );
  recMediaRecorder.ondataavailable = (e) => {
    if (e.data && e.data.size) recChunks.push(e.data);
  };
  recMediaRecorder.onstop = () => {
    const blob = new Blob(recChunks, { type: recMediaRecorder.mimeType || 'video/webm' });
    downloadBlob(blob, `body3d-rotate-${RECORD_WIDTH}x${RECORD_HEIGHT}-${Date.now()}.webm`);
  };
  recMediaRecorder.start();

  /* UI 反馈：按钮变红 + 倒计时 */
  dom.recordBtn.classList.add('recording');
  setRecLabel(`录制中 ${RECORD_SECS}s`);
  let remain = RECORD_SECS;
  recTickTimer = setInterval(() => {
    remain -= 1;
    if (remain >= 0) setRecLabel(`录制中 ${remain}s`);
  }, 1000);

  recTimer = setTimeout(stopRecording, RECORD_SECS * 1000);
}

function setRecLabel(text) {
  const label = dom.recordBtn.querySelector('.rec-label');
  if (label) label.textContent = text;
}

function stopRecording() {
  if (!recording) return;
  recording = false;
  clearTimeout(recTimer);
  clearInterval(recTickTimer);

  controls.autoRotate = false;

  if (recMediaRecorder && recMediaRecorder.state !== 'inactive') {
    try { recMediaRecorder.stop(); } catch (e) { /* 已停止则忽略 */ }
  }

  /* 等 MediaRecorder 收尾后再释放离屏渲染器 */
  setTimeout(() => {
    if (recRenderer) {
      recRenderer.dispose();
      recRenderer = null;
      recCamera = null;
      recMediaRecorder = null;
      recChunks = [];
    }
  }, 800);

  dom.recordBtn.classList.remove('recording');
  setRecLabel('录制旋转');
}

dom.recordBtn.addEventListener('click', () => {
  if (recording) stopRecording();
  else startRecording();
});

/* ─────────── 启动 ─────────── */

loadAll().catch((err) => {
  console.error(err);
  dom.hint.textContent = `模型加载失败：${err.message}`;
  dom.hint.classList.remove('hidden');
});