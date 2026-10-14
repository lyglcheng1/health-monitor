/*===============================================================
 * 文件: app.js
 * 项目: 人体解剖 3D 演示（demo-anatomy）
 * 说明: 加载 BodyParts3D 4.0 解剖网格（atlas.json + body-*.bin.gz）
 *       · 按 15 个系统合并渲染
 *       · 点击器官 → 高亮 + 相机飞行定位 + 详情
 *       · 下拉框快捷定位器官，左侧系统开关控制显隐
 * 数据格式: 每块 .bin 为按 atlas.parts 顺序拼接的段：
 *       positions: Float32Array(vertexCount*3)
 *       normals:   Int16Array(vertexCount*3)   量化为 [-32767,32767]
 *       indices:   Uint32Array(indexCount)
 *       part.positions/normals/indices 为各段字节偏移（4 字节对齐）
 *===============================================================*/

import * as THREE from 'three';
import { OrbitControls } from '../vendor/OrbitControls.js';

const ATLAS_URL = './models/atlas.json';

/* 系统（与 atlas.parts[].system 对应） */
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

/* 异常等级：严重 / 中度 / 轻度（颜色用于 3D 标记与统计面板） */
const SEVERITIES = {
  severe:   { label: '严重', color: 0xff4d4f },
  moderate: { label: '中度', color: 0xff9c40 },
  mild:     { label: '轻度', color: 0xffd666 },
};

/* 异常部位模拟数据（demo 用）。
 * 结构即未来后端 /api/abnormalities 的返回格式：
 *   conceptId: atlas 概念 ID（对应 3D 部件）
 *   severity:  严重程度
 *   issues:    异常指标列表
 *   records:   最近检查记录（倒序）
 *   note:      综合建议
 * 后续接入真实数据时，仅需用 fetch 替换本常量。 */
const ABNORMALITIES = [
  {
    conceptId: 'FMA7088', name: '心脏', severity: 'severe',
    issues: [
      { name: '总胆固醇', value: '6.8', unit: 'mmol/L', range: '2.8–5.2', status: '偏高' },
      { name: '低密度脂蛋白', value: '4.2', unit: 'mmol/L', range: '0.6–3.1', status: '偏高' },
    ],
    records: [
      { date: '2025-03-12', type: '年度体检', summary: '总胆固醇 6.8 mmol/L；心电图提示 ST-T 轻度改变', conclusion: '建议心血管内科随诊，1 个月后复查血脂' },
      { date: '2024-12-18', type: '门诊复查', summary: '总胆固醇 6.5 mmol/L；心电图未见明显异常', conclusion: '较上次略降，继续低脂饮食，半年后复查' },
      { date: '2024-09-05', type: '门诊复查', summary: '总胆固醇 6.2 mmol/L', conclusion: '较前次下降，继续低脂饮食' },
      { date: '2024-03-20', type: '年度体检', summary: '总胆固醇 6.9 mmol/L，首次发现偏高', conclusion: '建议控制饮食、适度运动' },
      { date: '2023-12-10', type: '年度体检', summary: '总胆固醇 6.7 mmol/L；甘油三酯 2.1 mmol/L 偏高', conclusion: '提示血脂异常，建议生活方式干预' },
    ],
    note: '近三次体检总胆固醇持续偏高，2025-03 心电图出现 ST-T 轻度改变，提示心血管风险上升，建议尽快专科随诊。',
  },
  {
    conceptId: 'FMA7197', name: '肝脏', severity: 'moderate',
    issues: [
      { name: 'ALT（谷丙转氨酶）', value: '72', unit: 'U/L', range: '9–50', status: '偏高' },
      { name: 'B 超', value: '轻度脂肪肝', unit: '', range: '正常：无脂肪浸润', status: '异常' },
    ],
    records: [
      { date: '2025-03-12', type: '年度体检', summary: 'ALT 72 U/L；B 超提示轻度脂肪肝', conclusion: '建议戒酒、控制体重，3 个月后复查肝功' },
      { date: '2024-09-15', type: '门诊复查', summary: 'ALT 62 U/L；B 超提示肝内脂肪沉积增多', conclusion: '建议控制体重，3 个月后复查' },
      { date: '2024-03-20', type: '年度体检', summary: 'ALT 58 U/L；B 超未见明显异常', conclusion: '建议低脂饮食，随访' },
      { date: '2023-09-22', type: '年度体检', summary: 'ALT 46 U/L，转氨酶正常；B 超未见异常', conclusion: '无异常发现' },
    ],
    note: 'ALT 持续升高并出现脂肪肝影像，考虑非酒精性脂肪性肝病可能，建议消化内科进一步评估。',
  },
  {
    conceptId: 'FMA7205', name: '左肾', severity: 'moderate',
    issues: [
      { name: 'B 超', value: '3mm 小结石', unit: '', range: '正常：无结石', status: '异常' },
    ],
    records: [
      { date: '2025-03-12', type: '年度体检', summary: '左肾见 3mm 强回声团，考虑结石', conclusion: '多饮水，6 个月后复查 B 超' },
      { date: '2024-03-20', type: '年度体检', summary: '双肾未见明显异常', conclusion: '无特殊处理' },
    ],
    note: '新发左肾小结石（3mm），目前无积水、无绞痛，建议每日饮水 2000ml 以上并定期复查。',
  },
  {
    conceptId: 'FMA7309', name: '右肺', severity: 'mild',
    issues: [
      { name: '胸片', value: '肺纹理增多', unit: '', range: '正常：肺纹理清晰', status: '轻度' },
    ],
    records: [
      { date: '2025-03-12', type: '年度体检', summary: '双肺纹理增多、增粗，以右肺为著', conclusion: '考虑与吸烟相关，建议戒烟、避免呼吸道感染' },
      { date: '2024-03-20', type: '年度体检', summary: '肺纹理稍增多', conclusion: '随访' },
    ],
    note: '长期吸烟者常见表现，暂未见实变影。建议戒烟并行肺功能检查。',
  },
  {
    conceptId: 'FMA7148', name: '胃', severity: 'mild',
    issues: [
      { name: '胃镜', value: '慢性浅表性胃炎', unit: '', range: '正常：黏膜光滑', status: '轻度' },
      { name: 'Hp（幽门螺杆菌）', value: '阴性', unit: '', range: '阴性', status: '正常' },
    ],
    records: [
      { date: '2025-01-08', type: '门诊胃镜', summary: '胃窦黏膜充血水肿，诊断慢性浅表性胃炎；Hp 阴性', conclusion: '规律饮食，避免辛辣刺激，1 年复查' },
    ],
    note: '慢性浅表性胃炎，Hp 阴性，症状轻微，以生活方式干预为主。',
  },
];

const state = {
  atlas: null,
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
  abnormalMeshes: [],         // { mesh, mat, conceptId, phase } 闪烁对象
  abnormalSprites: [],       // Sprite[] 头顶标注点
};

const dom = {
  canvasHost: document.getElementById('canvas-host'),
  hint: document.getElementById('hint'),
  progress: document.getElementById('progress'),
  organSelect: document.getElementById('organ-select'),
  sysList: document.getElementById('sys-list'),
  infoBody: document.getElementById('info-body'),
  statsDonut: document.getElementById('stats-donut'),
  statsTotal: document.getElementById('stat-total'),
  statsSevere: document.getElementById('stat-severe'),
  statsModerate: document.getElementById('stat-moderate'),
  statsMild: document.getElementById('stat-mild'),
};

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

/* 灯光（参考 human-atlas 原版） */
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

/** 从已解压的 chunk buffer 中按 part 元数据切片创建几何 */
function createPartGeometry(part, partIndex, buffer) {
  const geo = new THREE.BufferGeometry();
  geo.setAttribute(
    'position',
    new THREE.BufferAttribute(new Float32Array(buffer, part.positions, part.vertexCount * 3), 3)
  );
  // 法线为 Int16 量化值，normalized=true 让 GPU 自动除以 32767
  geo.setAttribute(
    'normal',
    new THREE.BufferAttribute(new Int16Array(buffer, part.normals, part.vertexCount * 3), 3, true)
  );
  geo.setIndex(new THREE.BufferAttribute(new Uint32Array(buffer, part.indices, part.indexCount), 1));
  geo.setAttribute('partIndex', new THREE.BufferAttribute(new Float32Array(part.vertexCount).fill(partIndex), 1));
  geo.computeBoundingSphere();
  return geo;
}

/** 将同一系统的多个 part 几何合并为单个几何（保留 partIndex 用于拾取） */
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
  // chunk 路径为相对 atlas.json 所在目录的路径（./body-*.bin.gz），
  // 以 atlas.json 的绝对地址为基准解析，demo 挂在子目录下也不会错。
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

  buildSidebar();
  buildOrganSelect();

  await Promise.all(state.atlas.chunks.map((_, ci) => loadChunk(ci).then(updateProgress)));
  buildSystemMeshes();
  initAbnormalities();
  onResize();
  fitAll();
  animate();

  /* 深链支持：?focus=<conceptId> 加载完成后自动定位器官 */
  const focusParam = new URLSearchParams(location.search).get('focus');
  if (focusParam && state.atlas.concepts.some((c) => c.id === focusParam)) {
    selectConcept(focusParam);
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

  /* 异常标注点（Sprite）优先拾取：点击标签直接定位异常部位 */
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

/** 概念对应的部件下标列表：优先取 concepts[].elements（顶层器官），否则取 conceptId 相同的部件 */
function conceptPartIndices(conceptId) {
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

/** 部件下标集合的包围盒（基于 atlas 元数据，免去额外 compute） */
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

/** 生成异常部位头顶标注 Sprite（圆点 + 中文名） */
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

/** 初始化异常部位：叠加脉冲发光网格 + 标注点 + 刷新统计面板 */
function initAbnormalities() {
  for (const ab of ABNORMALITIES) {
    const indices = conceptPartIndices(ab.conceptId);
    if (!indices.length) continue;
    const geos = indices.map((i) => state.partGeometry.get(i)).filter(Boolean);
    if (!geos.length) continue;
    state.abnormalityById.set(ab.conceptId, ab);

    /* 高亮网格：保留系统原色，用异常色做脉冲 emissive */
    const sysId = state.atlas.parts[indices[0]].system;
    const sys = SYSTEMS.find((s) => s.id === sysId);
    const mat = new THREE.MeshStandardMaterial({
      color: sys ? sys.color : 0xffffff,
      emissive: SEVERITIES[ab.severity].color,
      emissiveIntensity: 0,
      metalness: 0.05,
      roughness: 0.4,
      side: THREE.DoubleSide,
      depthWrite: false, // 依赖下方系统网格深度，叠加绘制不产生 z-fighting
    });
    const mesh = new THREE.Mesh(mergePartGeometries(geos), mat);
    mesh.renderOrder = 10;
    mesh.userData.conceptId = ab.conceptId;
    scene.add(mesh);

    /* 标注点：置于异常部位包围盒顶部上方 */
    const { min, max } = boundsOfIndices(indices);
    const top = new THREE.Vector3(
      min.x + (max.x - min.x) * 0.5,
      max.y + 0.035,
      min.z + (max.z - min.z) * 0.5
    );
    const sprite = makeMarkerSprite(ab, top);
    scene.add(sprite);

    state.abnormalMeshes.push({
      mesh, mat,
      conceptId: ab.conceptId,
      phase: state.abnormalMeshes.length * 1.7, // 各部位闪烁错开相位
    });
    state.abnormalSprites.push(sprite);
  }
  updateStats();
}

/** 更新左上角异常统计面板（数字卡片 + 环形图） */
function updateStats() {
  const counts = { severe: 0, moderate: 0, mild: 0 };
  for (const ab of ABNORMALITIES) {
    if (state.abnormalityById.has(ab.conceptId)) counts[ab.severity] += 1;
  }
  dom.statsTotal.textContent = String(counts.severe + counts.moderate + counts.mild);
  dom.statsSevere.textContent = String(counts.severe);
  dom.statsModerate.textContent = String(counts.moderate);
  dom.statsMild.textContent = String(counts.mild);
  renderDonutChart(counts);
}

/** 渲染异常概览环形图（严重程度占比），图例可点击定位 3D 部位 */
function renderDonutChart(counts) {
  const total = counts.severe + counts.moderate + counts.mild;
  dom.statsDonut.replaceChildren();

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const R = 38;              // 环半径（viewBox 0 0 100 100）
  const C = 2 * Math.PI * R;
  const GAP_DEG = 3;         // 弧段间隙角度
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

  // 背景轨道环
  const track = document.createElementNS(SVG_NS, 'circle');
  track.setAttribute('cx', '50');
  track.setAttribute('cy', '50');
  track.setAttribute('r', String(R));
  track.setAttribute('fill', 'none');
  track.setAttribute('stroke', 'rgba(148, 163, 184, 0.08)');
  track.setAttribute('stroke-width', '11');
  svg.appendChild(track);

  // 各等级弧段（顺时针拼接，顶部起点）
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

  // 中心文字：异常部位总数 + 标注
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

  // 图例（点击定位对应等级的第一个异常部位）
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
        const target = ABNORMALITIES.find(
          (ab) => ab.severity === lv.key && state.abnormalityById.has(ab.conceptId)
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

function buildSidebar() {
  const counts = new Map();
  for (const p of state.atlas.parts) {
    counts.set(p.system, (counts.get(p.system) || 0) + 1);
  }
  for (const sys of SYSTEMS) {
    const item = document.createElement('div');
    item.className = 'sys-item active';
    item.dataset.sys = sys.id;
    item.title = `${sys.label}（${sys.id}）`;

    const dot = document.createElement('span');
    dot.className = 'sys-dot';
    dot.style.background = '#' + sys.color.toString(16).padStart(6, '0');

    const name = document.createElement('span');
    name.className = 'sys-name';
    name.textContent = sys.label;

    const count = document.createElement('span');
    count.className = 'sys-count';
    count.textContent = String(counts.get(sys.id) || 0);

    item.append(dot, name, count);
    item.addEventListener('click', () => {
      const visible = state.systemVisible[sys.id] === true;
      state.systemVisible[sys.id] = !visible;
      const mesh = state.systemMesh.get(sys.id);
      if (mesh) mesh.visible = !visible;
      item.classList.toggle('active', !visible);
    });
    dom.sysList.appendChild(item);
  }
}

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
    if (id) dom.organSelect.value = ''; // 允许重复定位同一器官
  });
}

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
  } else {
    renderNormalDetail(conceptId);
  }
}

/** 异常部位详情：异常指标 + 最近检查情况 + 综合建议 */
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

  const sysLabel = document.createElement('span');
  sysLabel.className = 'info-system';
  sysLabel.textContent = organMeta ? organMeta.en : concept ? concept.name : conceptId;
  dom.infoBody.appendChild(sysLabel);

  /* 异常指标 */
  const secIssues = document.createElement('section');
  secIssues.className = 'ab-section';
  const hIssues = document.createElement('h4');
  hIssues.textContent = '异常指标';
  secIssues.appendChild(hIssues);
  for (const issue of ab.issues) {
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
    rangeEl.textContent = issue.range;
    const flagEl = document.createElement('span');
    flagEl.className = 'flag';
    flagEl.textContent = issue.status;
    row.append(nameEl, valueEl, rangeEl, flagEl);
    secIssues.appendChild(row);
  }
  dom.infoBody.appendChild(secIssues);

  /* 检查记录：竖向时间轴，默认显示最近 3 条，可展开全部 */
  const RECORDS_PREVIEW = 3;
  const secRecords = document.createElement('section');
  secRecords.className = 'ab-section';
  const hRecords = document.createElement('h4');
  hRecords.textContent = `检查记录（${ab.records.length} 次）`;
  secRecords.appendChild(hRecords);

  const timeline = document.createElement('div');
  timeline.className = 'ab-timeline';
  ab.records.forEach((rec, i) => {
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
    conclusion.textContent = `▸ ${rec.conclusion}`;
    card.append(head, summary, conclusion);
    timeline.appendChild(card);
  });
  secRecords.appendChild(timeline);

  if (ab.records.length > RECORDS_PREVIEW) {
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'records-toggle';
    const arrow = document.createElement('span');
    arrow.className = 'toggle-arrow';
    toggle.append(arrow, document.createTextNode(`展开全部 ${ab.records.length} 条记录`));
    toggle.addEventListener('click', () => {
      const isOpen = toggle.classList.contains('open');
      const hidden = timeline.querySelectorAll('.record-hidden');
      hidden.forEach((el) => el.classList.toggle('record-hidden', isOpen));
      toggle.classList.toggle('open', !isOpen);
      toggle.lastChild.textContent = isOpen
        ? `展开全部 ${ab.records.length} 条记录`
        : '收起记录';
    });
    secRecords.appendChild(toggle);
  }
  dom.infoBody.appendChild(secRecords);

  /* 综合建议 */
  const note = document.createElement('div');
  note.className = 'ab-note';
  const strong = document.createElement('strong');
  strong.textContent = '健康建议：';
  note.append(strong, document.createTextNode(ab.note));
  dom.infoBody.appendChild(note);

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

/** 追加基础结构信息（部件数 / 三角面 / 尺寸） */
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
  /* 异常部位脉冲闪烁 */
  for (const item of state.abnormalMeshes) {
    const pulse = 0.5 + 0.5 * Math.sin(t * 2.6 + item.phase);
    item.mat.emissiveIntensity = 0.25 + 0.9 * pulse;
  }
  controls.update();
  renderer.render(scene, camera);
}

/* ─────────── 启动 ─────────── */

loadAll().catch((err) => {
  console.error(err);
  dom.hint.textContent = `模型加载失败：${err.message}`;
  dom.hint.classList.remove('hidden');
});