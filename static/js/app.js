/* ============================================================
 * 文件: app.js
 * 项目: 健康数据监控（health-monitor）
 * 说明: 全部逻辑与事件绑定（HTML 内禁止内联 script/on*）
 * ============================================================ */
'use strict';

// ── 工具 ──

function escapeHtml(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function $(id) { return document.getElementById(id); }

function showToast(msg, type) {
  const el = $('toast');
  el.textContent = msg;
  el.className = 'toast ' + (type || '');
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => { el.className = 'toast hidden'; }, 3000);
}

async function api(path, opts) {
  const options = opts || {};
  options.headers = Object.assign({}, options.headers || {});
  if (options.body && !(options.body instanceof FormData)) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
  }
  const resp = await fetch(path, options);
  let payload = null;
  try { payload = await resp.json(); } catch (_) { /* 空响应 */ }
  if (resp.status === 401 && payload && payload.detail) {
    showLoginView();
    throw new Error(payload.detail.message || '未登录');
  }
  if (!resp.ok) {
    const detail = payload && payload.detail;
    const msg = detail ? (detail.message || '请求失败') : ('HTTP ' + resp.status);
    throw new Error(msg);
  }
  return payload;
}

// ── 全局状态 ──

const state = {
  site: null,
  authed: false,
  exams: [],
};

let currentRoute = '#/';

// ── 站点信息 / 登录 ──

async function loadSiteInfo() {
  const p = await api('/api/site-info');
  state.site = p.data;
  $('brand-title').textContent = state.site.title;
  $('brand-tagline').textContent = state.site.tagline;
  $('login-title').textContent = state.site.title;
  $('login-tagline').textContent = state.site.tagline;
  document.title = state.site.title;
}

function showLoginView() {
  state.authed = false;
  $('login-view').classList.remove('hidden');
  $('main-view').classList.add('hidden');
  $('logout-btn').classList.add('hidden');
  renderLogin();
}

function showMainView() {
  state.authed = true;
  $('login-view').classList.add('hidden');
  $('main-view').classList.remove('hidden');
  $('logout-btn').classList.remove('hidden');
  route();
}

function renderLogin() {
  $('login-form').innerHTML =
    '<form id="login-form-el">' +
    '<label for="login-username">用户名</label>' +
    '<input id="login-username" name="username" autocomplete="username" required>' +
    '<label for="login-password">密码</label>' +
    '<input id="login-password" name="password" type="password" autocomplete="current-password" required>' +
    '<div class="form-actions">' +
    '<button type="submit" class="btn" id="login-submit">登录</button>' +
    '</div>' +
    '</form>';
  $('login-form-el').addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = $('login-username').value.trim();
    const password = $('login-password').value;
    if (!username || !password) return;
    try {
      await api('/api/login', { method: 'POST', body: { username, password } });
      showToast('登录成功', 'success');
      showMainView();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });
}

async function init() {
  try {
    await loadSiteInfo();
  } catch (_) { /* 站点信息失败也继续渲染 */ }
  if (state.site && state.site.auth_enabled) {
    showLoginView();
  } else {
    showMainView();
  }
  $('logout-btn').addEventListener('click', async () => {
    try { await api('/api/logout', { method: 'POST' }); } catch (_) {}
    showLoginView();
  });
}

// ── 哈希路由 ──

function route() {
  let hash = location.hash || '#/';
  if (!hash.startsWith('#')) hash = '#/';
  currentRoute = hash;
  updateNav();
  const parts = hash.slice(1).split('/').filter(Boolean); // ['exam','3']
  const content = $('content');
  content.classList.remove('wide');
  if (!state.authed) { content.innerHTML = ''; return; }

  if (parts.length === 0) { renderDashboard(content); return; }
  const head = parts[0];
  if (head === 'exams' || head === 'exam') {
    // 兼容历史链接 #/exam/{id}（旧版上传/列表生成），统一走体检详情
    if (parts.length >= 2) { renderExam(content, parts[1]); return; }
    renderExams(content);
    return;
  }
  if (head === 'body') { renderBody(content); return; }
  if (head === 'body3d') { renderBody3d(content); return; }
  if (head === 'settings') { renderSettings(content); return; }
  if (head === 'backup') { renderBackup(content); return; }
  renderDashboard(content);
}

function updateNav() {
  const map = [
    ['#/', '仪表盘'],
    ['#/exams', '体检记录'],
    ['#/body3d', '3D 大屏'],
    ['#/body', '身体数据'],
    ['#/settings', '模型设置'],
    ['#/backup', '备份'],
  ];
  const active = map.find(([href]) => currentRoute === href || (href !== '#/' && currentRoute.startsWith(href)));
  const nav = $('topnav');
  for (const a of nav.querySelectorAll('a')) {
    a.classList.remove('active');
    if (active && a.getAttribute('href') === active[0]) a.classList.add('active');
  }
}

function link(href, text, cls) {
  return '<a class="btn ' + (cls || 'btn-ghost') + ' btn-sm" href="' + href + '">' + escapeHtml(text) + '</a>';
}

// ── 仪表盘 ──

async function renderDashboard(content) {
  content.innerHTML = '<div class="card"><h2>总览</h2><div class="muted">加载中…</div></div>';
  let exams = [];
  let bodyRecords = [];
  let metricTotal = 0;
  let overviewParts = [];
  try {
    const ep = await api('/api/exams');
    exams = ep.data.items || [];
    metricTotal = exams.reduce((n, e) => n + (e.metric_count || 0), 0);
    try {
      const bp = await api('/api/body-records');
      bodyRecords = bp.data.items || [];
    } catch (_) {}
    try {
      const ov = await api('/api/body3d/overview?mode=abnormal');
      overviewParts = ov.data.parts || [];
    } catch (_) { /* 大屏数据可选，失败不阻塞仪表盘 */ }
    state.exams = exams;
  } catch (err) {
    content.innerHTML = '<div class="card"><h2>总览</h2><p class="muted">' + escapeHtml(err.message) + '</p></div>';
    return;
  }

  const recent = exams.slice(0, 5);
  const abnormalCount = overviewParts.length;
  const abnormalNames = overviewParts.slice(0, 6).map((p) =>
    '<span class="part-chip ' + escapeHtml(p.severity || '') + '">' + escapeHtml(p.name) + '</span>'
  ).join('');

  const html =
    '<div class="card">' +
      '<h2>总览</h2>' +
      '<div class="stat-grid">' +
        '<div class="stat"><div class="stat-label">体检记录</div><div class="stat-num">' + exams.length + '</div></div>' +
        '<div class="stat"><div class="stat-label">解析指标</div><div class="stat-num">' + metricTotal + '</div></div>' +
        '<div class="stat"><div class="stat-label">身体数据</div><div class="stat-num">' + bodyRecords.length + '</div></div>' +
        (exams.length ? '<div class="stat"><div class="stat-label">最近体检</div><div class="stat-num">' + escapeHtml(exams[0].exam_date) + '</div></div>' : '') +
      '</div>' +
    '</div>' +
    '<div class="card">' +
      '<h2>上传体检图片</h2>' +
      '<form id="upload-form">' +
        '<div class="form-row">' +
          '<div><label for="up-date">体检日期</label><input id="up-date" type="date"></div>' +
          '<div class="grow-2"><label for="up-hospital">医院</label><input id="up-hospital" placeholder="医院名称（可选）"></div>' +
        '</div>' +
        '<label for="up-note">备注</label><textarea id="up-note" placeholder="备注（可选）"></textarea>' +
        '<label for="up-files">图片（可多选，每张 = 一条记录）</label>' +
        '<input id="up-files" type="file" accept="image/*" multiple>' +
        '<div class="form-actions"><button type="submit" class="btn">上传并 OCR 识别</button></div>' +
      '</form>' +
      '<div id="upload-result" class="mt-16"></div>' +
    '</div>' +
    '<div class="card">' +
      '<div class="flex-between"><h2>最近体检</h2>' + link('#/exams', '查看全部') + '</div>' +
      (recent.length ? recent.map(examListItem).join('') : '<p class="muted">暂无记录，先上传一张体检图片。</p>') +
    '</div>' +
    '<div class="card body3d-card">' +
      '<div class="flex-between">' +
        '<h2>3D 人体大屏</h2>' +
        link('#/body3d', '进入大屏', 'btn-sm') +
      '</div>' +
      '<p class="muted">异常部位会在 3D 人体上高亮标注，点击部位查看异常指标与历次检查记录。</p>' +
      '<div class="body3d-preview">' +
        (abnormalCount
          ? '<div class="flex-between"><span class="muted">当前异常部位：' + abnormalCount + ' 个</span>' + abnormalNames + '</div>'
          : '<span class="muted">暂无异常部位（全部指标在参考区间内）。</span>') +
      '</div>' +
    '</div>';

  content.innerHTML = html;
  bindUploadForm();
}

function examListItem(exam) {
  const badge = exam.metric_count > 0
    ? '<span class="badge badge-normal">' + exam.metric_count + ' 项指标</span>'
    : '<span class="badge">待录入</span>';
  return '<a class="list-item list-item-link" href="#/exams/' + exam.id + '">' +
    '<div class="title">' + escapeHtml(exam.exam_date) + '</div>' +
    '<div class="sub">' + escapeHtml(exam.hospital || '未填医院') + '</div>' +
    (exam.source ? '<div class="sub muted">' + escapeHtml(exam.source) + '</div>' : '') +
    badge +
    '<span class="muted">' + escapeHtml(exam.source_type) + '</span>' +
    '</a>';
}

function bindUploadForm() {
  const form = $('upload-form');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const files = $('up-files').files;
    if (!files.length) { showToast('请选择图片', 'error'); return; }
    const fd = new FormData();
    for (const f of files) fd.append('files', f);
    const date = $('up-date').value;
    if (date) fd.append('exam_date', date);
    fd.append('hospital', $('up-hospital').value.trim());
    fd.append('note', $('up-note').value.trim());
    const submitBtn = form.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    submitBtn.textContent = 'OCR 识别中…';
    const resultDiv = $('upload-result');
    resultDiv.innerHTML = '<p class="muted">正在处理 ' + files.length + ' 张图片（本地 OCR，请稍候）…</p>';
    try {
      const p = await api('/api/exams', { method: 'POST', body: fd });
      const items = p.data.results || [];
      resultDiv.innerHTML = items.map((it) => {
        const statusCls = it.status === 'created' ? 'badge badge-ok' : 'badge badge-abnormal';
        const body = it.status === 'created'
          ? '<a href="#/exams/' + it.id + '">查看详情</a>'
          : escapeHtml(it.message);
        return '<div class="list-item"><div class="title">' + escapeHtml(it.exam_date) + '</div>' +
          '<span class="' + statusCls + '">' + escapeHtml(it.status) + '</span>' +
          '<div class="sub">' + body + '</div></div>';
      }).join('');
      showToast('上传完成', 'success');
    } catch (err) {
      resultDiv.innerHTML = '<p class="muted" style="color:var(--danger)">' + escapeHtml(err.message) + '</p>';
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = '上传并 OCR 识别';
    }
  });
}

// ── 体检列表 ──

async function renderExams(content) {
  content.innerHTML = '<div class="card"><h2>体检记录</h2><div class="muted">加载中…</div></div>';
  let exams = [];
  try {
    const p = await api('/api/exams');
    exams = p.data.items || [];
    state.exams = exams;
  } catch (err) {
    content.innerHTML = '<div class="card"><h2>体检记录</h2><p class="muted">' + escapeHtml(err.message) + '</p></div>';
    return;
  }
  content.innerHTML =
    '<div class="card">' +
      '<div class="flex-between"><h2>体检记录（' + exams.length + '）</h2>' + link('#/', '上传图片') + '</div>' +
      (exams.length ? exams.map(examListItem).join('') : '<p class="muted">暂无记录。</p>') +
    '</div>';
}

// ── 体检详情 ──

async function renderExam(content, id) {
  content.innerHTML = '<div class="card"><h2>体检详情</h2><div class="muted">加载中…</div></div>';
  let exam;
  try {
    const p = await api('/api/exams/' + id);
    exam = p.data;
  } catch (err) {
    content.innerHTML = '<div class="card"><h2>体检详情</h2><p class="muted">' + escapeHtml(err.message) + '</p></div>';
    return;
  }

  const html =
    '<div class="card">' +
      '<div class="flex-between">' +
        '<h2>体检记录 #' + exam.id + '</h2>' +
        '<span>' + link('#/exams', '返回列表') + ' <button type="button" class="btn btn-danger btn-sm" id="exam-delete">删除</button></span>' +
      '</div>' +
      '<div class="form-row mt-8">' +
        '<div><label>体检日期</label><input id="exam-date" type="date" value="' + escapeHtml(exam.exam_date) + '"></div>' +
        '<div style="flex:2;"><label>医院</label><input id="exam-hospital" value="' + escapeHtml(exam.hospital) + '"></div>' +
      '</div>' +
      '<label>来源/附件</label><input id="exam-source" value="' + escapeHtml(exam.source || '') + '" maxlength="500" placeholder="如：连云港第一人民医院20260930检查.pdf 第6/6页（检验报告单）">' +
      '<label>备注</label><textarea id="exam-note">' + escapeHtml(exam.note) + '</textarea>' +
      '<div class="form-actions"><button type="button" class="btn" id="exam-save">保存信息</button></div>' +
    '</div>' +
    '<div class="card exam-layout">' +
      '<div class="exam-image">' +
        '<h2>原始图片</h2>' +
        '<img id="exam-img" src="/api/exams/' + exam.id + '/image" alt="体检图片">' +
      '</div>' +
      '<div class="exam-ocr">' +
        '<h2>OCR 识别文本</h2>' +
        '<textarea id="exam-ocr-text">' + escapeHtml(exam.ocr_text) + '</textarea>' +
        '<div class="form-actions"><button type="button" class="btn" id="exam-ocr-save">保存 OCR</button></div>' +
        '<p class="muted">提示：后续 AI 提取功能会基于 OCR 文本自动生成指标，当前可手动录入。</p>' +
      '</div>' +
    '</div>' +
    '<div class="card">' +
      '<div class="flex-between"><h2>指标（' + (exam.metrics || []).length + '）</h2></div>' +
      '<div id="metric-summary" class="metric-summary"></div>' +
      '<div id="metric-list">' + metricsTable(exam.metrics || []) + '</div>' +
      '<div class="mt-16">' +
        '<h3 id="metric-form-title">添加指标</h3>' + metricFormHtml(exam.id) +
      '</div>' +
    '</div>';

  content.innerHTML = html;

  renderMetricSummary(exam.metrics || []);

  $('exam-save').addEventListener('click', async () => {
    try {
      await api('/api/exams/' + exam.id, {
        method: 'PUT',
        body: {
          exam_date: $('exam-date').value,
          hospital: $('exam-hospital').value.trim(),
          source: $('exam-source').value.trim(),
          note: $('exam-note').value,
        },
      });
      showToast('已保存', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });

  $('exam-ocr-save').addEventListener('click', async () => {
    try {
      await api('/api/exams/' + exam.id, {
        method: 'PUT',
        body: { ocr_text: $('exam-ocr-text').value },
      });
      showToast('OCR 已保存', 'success');
    } catch (err) { showToast(err.message, 'error'); }
  });

  $('exam-delete').addEventListener('click', async () => {
    if (!confirm('确定删除这条体检记录及其全部指标？')) return;
    try {
      await api('/api/exams/' + exam.id, { method: 'DELETE' });
      showToast('已删除', 'success');
      location.hash = '#/exams';
    } catch (err) { showToast(err.message, 'error'); }
  });

  bindMetricForm(exam.id);
}

function renderMetricSummary(metrics) {
  const el = $('metric-summary');
  if (!el) return;
  const total = metrics.length;
  const abnormal = metrics.filter((m) => m.abnormal).length;
  el.innerHTML = total
    ? '<span class="badge badge-normal">共 ' + total + ' 项</span> ' +
      (abnormal
        ? '<span class="badge badge-abnormal">异常 ' + abnormal + ' 项</span>'
        : '<span class="badge badge-ok">全部正常</span>')
    : '<span class="muted">暂无解析指标，可在下方手动录入（后续接入 AI 提取）。</span>';
}

function metricsTable(metrics) {
  if (!metrics.length) return '<p class="muted">暂无指标。</p>';
  const rows = metrics.map((m) => {
    const bad = m.abnormal;
    const badge = bad
      ? '<span class="badge badge-abnormal">异常</span>'
      : '<span class="badge badge-ok">正常</span>';
    const range = (m.ref_low || '') + (m.ref_high ? '~' + m.ref_high : '');
    return '<tr class="' + (bad ? 'row-abnormal' : '') + '">' +
      '<td><strong>' + escapeHtml(m.name) + '</strong></td>' +
      '<td class="num"><strong>' + escapeHtml(m.value_text) + '</strong></td>' +
      '<td>' + escapeHtml(m.unit) + '</td>' +
      '<td class="muted">' + escapeHtml(range) + '</td>' +
      '<td>' + badge + '</td>' +
      '<td>' + escapeHtml(m.body_part || '-') + '</td>' +
      '<td class="muted">' + escapeHtml(m.note || '') + '</td>' +
      '<td class="actions">' +
        '<button type="button" class="btn btn-ghost btn-sm" data-edit-metric="' + m.id + '">编辑</button> ' +
        '<button type="button" class="btn btn-danger btn-sm" data-del-metric="' + m.id + '">删</button>' +
      '</td>' +
      '</tr>';
  }).join('');
  return '<table><thead><tr><th>指标</th><th>数值</th><th>单位</th><th>参考范围</th><th>状态</th><th>身体部位</th><th>备注</th><th></th></tr></thead><tbody>' + rows + '</tbody></table>';
}

function metricFormHtml(examId) {
  return '<form id="metric-form">' +
    '<div class="metric-edit">' +
      '<input name="name" placeholder="指标名（如 谷丙转氨酶 ALT）" required>' +
      '<input name="value_text" placeholder="数值">' +
      '<input name="unit" placeholder="单位">' +
      '<input name="ref_low" placeholder="参考下限">' +
      '<input name="ref_high" placeholder="参考上限">' +
      '<input name="body_part" placeholder="身体部位（如 liver/kidney/heart）">' +
      '<input name="note" placeholder="备注">' +
      '<label class="checkbox-label"><input type="checkbox" name="abnormal"> 异常</label>' +
    '</div>' +
    '<div class="form-actions">' +
      '<button type="submit" class="btn" id="metric-submit">添加指标</button>' +
      '<button type="button" class="btn btn-ghost hidden" id="metric-cancel">取消编辑</button>' +
    '</div>' +
    '</form>';
}

function bindMetricForm(examId) {
  const form = $('metric-form');
  let editingId = null;

  function resetForm() {
    form.reset();
    editingId = null;
    $('metric-form-title').textContent = '添加指标';
    $('metric-submit').textContent = '添加指标';
    $('metric-cancel').classList.add('hidden');
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = formDataToObject(form);
    data.abnormal = form.querySelector('[name="abnormal"]').checked;
    try {
      if (editingId) {
        await api('/api/metrics/' + editingId, { method: 'PUT', body: data });
        showToast('已保存', 'success');
      } else {
        await api('/api/exams/' + examId + '/metrics', { method: 'POST', body: data });
        showToast('已添加', 'success');
      }
      resetForm();
      renderExam($('content'), examId);
    } catch (err) { showToast(err.message, 'error'); }
  });

  $('metric-cancel').addEventListener('click', resetForm);

  const editBtns = document.querySelectorAll('[data-edit-metric]');
  for (const btn of editBtns) {
    btn.addEventListener('click', () => {
      const tr = btn.closest('tr');
      if (!tr) return;
      const cells = tr.querySelectorAll('td');
      editingId = btn.dataset.editMetric;
      form.elements['name'].value = cells[0].textContent.trim();
      form.elements['value_text'].value = cells[1].textContent.trim();
      form.elements['unit'].value = cells[2].textContent.trim();
      const range = cells[3].textContent.trim();
      const m = range.match(/^([^~]*)(?:~([^~]*))?$/);
      form.elements['ref_low'].value = m ? m[1] : '';
      form.elements['ref_high'].value = m ? (m[2] || '') : '';
      form.elements['body_part'].value = cells[5].textContent.trim();
      form.elements['note'].value = cells[6].textContent.trim();
      form.elements['abnormal'].checked = tr.classList.contains('row-abnormal');
      $('metric-form-title').textContent = '编辑指标';
      $('metric-submit').textContent = '保存修改';
      $('metric-cancel').classList.remove('hidden');
    });
  }

  const delBtns = document.querySelectorAll('[data-del-metric]');
  for (const btn of delBtns) {
    btn.addEventListener('click', async () => {
      if (!confirm('删除该指标？')) return;
      try {
        await api('/api/metrics/' + btn.dataset.delMetric, { method: 'DELETE' });
        showToast('已删除', 'success');
        resetForm();
        renderExam($('content'), examId);
      } catch (err) { showToast(err.message, 'error'); }
    });
  }
}

function formDataToObject(form) {
  const data = {};
  for (const el of form.querySelectorAll('[name]')) {
    if (el.type === 'checkbox') continue;
    data[el.name] = el.value.trim();
  }
  return data;
}

// ── 日常身体数据 ──

async function renderBody(content) {
  content.innerHTML = '<div class="card"><h2>身体数据</h2><div class="muted">加载中…</div></div>';
  let records = [];
  try {
    const p = await api('/api/body-records');
    records = p.data.items || [];
  } catch (err) {
    content.innerHTML = '<div class="card"><h2>身体数据</h2><p class="muted">' + escapeHtml(err.message) + '</p></div>';
    return;
  }
  content.innerHTML =
    '<div class="card">' +
      '<h2>新增记录</h2>' +
      '<form id="body-form">' +
        '<div class="form-row">' +
          '<div><label>日期</label><input name="record_date" type="date" required></div>' +
          '<div><label>类型</label><select name="record_type" required>' +
            '<option value="weight">体重</option>' +
            '<option value="blood_pressure_high">血压（收缩压）</option>' +
            '<option value="blood_pressure_low">血压（舒张压）</option>' +
            '<option value="blood_glucose">血糖</option>' +
            '<option value="heart_rate">心率</option>' +
            '<option value="other">其他</option>' +
          '</select></div>' +
          '<div><label>数值</label><input name="value" type="number" step="any" required></div>' +
          '<div><label>单位</label><input name="unit" placeholder="kg / mmHg / mmol/L"></div>' +
          '<div class="grow-2"><label>备注</label><input name="note" placeholder="备注（可选）"></div>' +
        '</div>' +
        '<div class="form-actions"><button type="submit" class="btn">添加</button></div>' +
      '</form>' +
    '</div>' +
    '<div class="card">' +
      '<h2>历史记录（' + records.length + '）</h2>' +
      (records.length
        ? '<table><thead><tr><th>日期</th><th>类型</th><th>数值</th><th>单位</th><th>备注</th><th></th></tr></thead><tbody>' +
          records.map((r) => '<tr>' +
            '<td>' + escapeHtml(r.record_date) + '</td>' +
            '<td>' + escapeHtml(r.record_type) + '</td>' +
            '<td class="num"><strong>' + escapeHtml(String(r.value)) + '</strong></td>' +
            '<td>' + escapeHtml(r.unit) + '</td>' +
            '<td>' + escapeHtml(r.note) + '</td>' +
            '<td><button type="button" class="btn btn-danger btn-sm" data-del-body="' + r.id + '">删</button></td>' +
            '</tr>').join('') + '</tbody></table>'
        : '<p class="muted">暂无记录。</p>') +
    '</div>';
  $('body-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = formDataToObject($('body-form'));
    data.value = parseFloat(data.value);
    try {
      await api('/api/body-records', { method: 'POST', body: data });
      showToast('已添加', 'success');
      renderBody($('content'));
    } catch (err) { showToast(err.message, 'error'); }
  });
  const delBtns = document.querySelectorAll('[data-del-body]');
  for (const btn of delBtns) {
    btn.addEventListener('click', async () => {
      if (!confirm('删除该条记录？')) return;
      try {
        await api('/api/body-records/' + btn.dataset.delBody, { method: 'DELETE' });
        showToast('已删除', 'success');
        renderBody($('content'));
      } catch (err) { showToast(err.message, 'error'); }
    });
  }
}

// ── 模型设置 ──

async function renderSettings(content) {
  content.innerHTML = '<div class="card"><h2>模型设置</h2><div class="muted">加载中…</div></div>';
  let admin;
  try {
    const p = await api('/api/models/admin');
    admin = p.data;
  } catch (err) {
    content.innerHTML = '<div class="card"><h2>模型设置</h2><p class="muted">' + escapeHtml(err.message) + '</p></div>';
    return;
  }
  const customRows = (admin.items || []).filter((it) => it.custom);
  const defaultModel = admin.default || '';

  content.innerHTML =
    '<div class="card">' +
      '<h2>默认模型</h2>' +
      '<p>当前默认：<code>' + escapeHtml(defaultModel || '未配置') + '</code></p>' +
      (defaultModel
        ? '<p class="muted">用于 3D 大屏严重度判定等 AI 功能。</p>'
        : '<p class="muted">尚未启用任何模型。请在下方添加并启用一个自定义模型，3D 大屏严重度判定等 AI 功能才会生效；未配置时大屏自动按数量规则回退。</p>') +
    '</div>' +
    '<div class="card">' +
      '<h2>自定义模型（OpenAI 兼容 / Anthropic 端点）</h2>' +
      (customRows.length
        ? '<table><thead><tr><th>名称</th><th>端点</th><th>协议</th><th>密钥</th><th>启用</th><th></th></tr></thead><tbody>' +
          customRows.map((m) => '<tr>' +
            '<td>' + escapeHtml(m.name) + '</td>' +
            '<td class="muted">' + escapeHtml(m.base_url || '') + '</td>' +
            '<td>' + escapeHtml(m.protocol) + '</td>' +
            '<td>' + (m.has_key ? '<span class="badge badge-normal">已配置</span>' : '<span class="badge">未配置</span>') + '</td>' +
            '<td>' + (m.enabled ? '<span class="badge badge-ok">已启用</span>' : '<span class="badge">未启用</span>') + '</td>' +
            '<td>' +
              (m.enabled
                ? '<button type="button" class="btn btn-ghost btn-sm" data-disable="' + escapeHtml(m.name) + '@' + m.id + '">停用</button>'
                : '<button type="button" class="btn btn-sm" data-enable="' + escapeHtml(m.name) + '@' + m.id + '">启用</button>') +
              ' <button type="button" class="btn btn-ghost btn-sm" data-test="' + escapeHtml(m.name) + '@' + m.id + '">测试</button>' +
              ' <button type="button" class="btn btn-danger btn-sm" data-del-custom="' + m.id + '">删</button>' +
            '</td>' +
            '</tr>').join('') + '</tbody></table>'
        : '<p class="muted">暂无自定义模型。</p>') +
      '<div class="mt-16">' +
        '<h3>添加自定义模型</h3>' +
        '<form id="custom-model-form">' +
          '<div class="form-row">' +
            '<div><label>模型名</label><input name="name" placeholder="如 my-llm" required></div>' +
            '<div class="grow-2"><label>API 地址</label><input name="base_url" placeholder="https://api.example.com/v1" required></div>' +
            '<div><label>API Key（可空）</label><input name="api_key" type="password" placeholder="sk-..."></div>' +
            '<div><label>协议</label><select name="protocol"><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option></select></div>' +
          '</div>' +
          '<div class="form-actions">' +
            '<button type="submit" class="btn">添加</button>' +
            '<button type="button" class="btn btn-ghost" id="custom-detect">测试协议</button>' +
          '</div>' +
          '<div id="detect-result" class="muted mt-8"></div>' +
        '</form>' +
      '</div>' +
    '</div>';

  bindModelButtons(content);
}

function bindModelButtons(content) {
  const btns = content.querySelectorAll('[data-enable], [data-disable], [data-test], [data-del-custom]');
  for (const btn of btns) {
    btn.addEventListener('click', async () => {
      const value = btn.dataset.enable || btn.dataset.disable || btn.dataset.test || '';
      const action = btn.dataset.enable ? 'enable' : (btn.dataset.disable ? 'disable' : 'test');
      try {
        if (action === 'test') {
          const p = await api('/api/models/' + encodeURIComponent(value) + '/test', { method: 'POST' });
          const d = p.data;
          showToast(d.ok ? '连通成功（' + d.latency_ms + 'ms）' : d.message, d.ok ? 'success' : 'error');
          return;
        }
        if (btn.dataset.delCustom) {
          if (!confirm('删除该自定义模型？')) return;
          await api('/api/models/custom/' + btn.dataset.delCustom, { method: 'DELETE' });
          showToast('已删除', 'success');
        } else {
          await api('/api/models/' + encodeURIComponent(value) + '/' + action, { method: 'POST' });
          showToast(action === 'enable' ? '已启用' : '已停用', 'success');
        }
        renderSettings(content);
      } catch (err) { showToast(err.message, 'error'); }
    });
  }

  const form = $('custom-model-form');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = formDataToObject(form);
    data.protocol = form.querySelector('[name="protocol"]').value;
    try {
      const p = await api('/api/models/custom', { method: 'POST', body: data });
      showToast('已添加模型 ' + p.data.name, 'success');
      renderSettings(content);
    } catch (err) { showToast(err.message, 'error'); }
  });

  $('custom-detect').addEventListener('click', async () => {
    const data = formDataToObject(form);
    const resultDiv = $('detect-result');
    resultDiv.innerHTML = '正在探测…';
    try {
      const p = await api('/api/models/custom/detect', { method: 'POST', body: data });
      resultDiv.innerHTML = (p.data.results || []).map((r) =>
        '<div>' + escapeHtml(r.protocol) + '：' + escapeHtml(r.endpoint_url) + ' → ' +
        (r.ok ? '<span class="text-success">OK ' + r.latency_ms + 'ms</span>' : '<span class="text-danger">' + escapeHtml(r.message) + '</span>') + '</div>'
      ).join('');
    } catch (err) {
      resultDiv.innerHTML = '<span class="text-danger">' + escapeHtml(err.message) + '</span>';
    }
  });
}

// ── 备份 ──

async function renderBackup(content) {
  content.innerHTML = '<div class="card"><h2>备份</h2><div class="muted">加载中…</div></div>';
  let items = [];
  try {
    const p = await api('/api/backup');
    items = p.data.items || [];
  } catch (err) {
    content.innerHTML = '<div class="card"><h2>备份</h2><p class="muted">' + escapeHtml(err.message) + '</p></div>';
    return;
  }
  content.innerHTML =
    '<div class="card">' +
      '<h2>一键备份</h2>' +
      '<p class="muted">备份包含数据库（体检/指标/身体数据/模型配置）与上传图片原件。</p>' +
      '<form id="backup-create-form" class="flex-between backup-create-form">' +
        '<input name="label" placeholder="备注（可选，如 2026-09 体检前）">' +
        '<button type="submit" class="btn">立即备份</button>' +
      '</form>' +
    '</div>' +
    '<div class="card">' +
      '<h2>从备份还原</h2>' +
      '<p class="muted">上传在其他机器导出的备份包（自动校验并入库），或直接还原下列备份。</p>' +
      '<form id="backup-upload-form">' +
        '<input type="file" id="backup-file" accept=".tar.gz">' +
        '<div class="form-actions"><button type="submit" class="btn">上传备份包</button></div>' +
      '</form>' +
    '</div>' +
    '<div class="card">' +
      '<h2>备份清单（' + items.length + '）</h2>' +
      (items.length
        ? '<table><thead><tr><th>文件名</th><th>时间</th><th>大小</th><th>类型</th><th>记录数</th><th></th></tr></thead><tbody>' +
          items.map((it) => '<tr>' +
            '<td class="muted">' + escapeHtml(it.filename) + (it.corrupt ? ' <span class="badge badge-abnormal">损坏</span>' : '') + '</td>' +
            '<td>' + escapeHtml(it.created_at || '-') + '</td>' +
            '<td>' + escapeHtml(fmtSize(it.size_bytes)) + '</td>' +
            '<td>' + (it.kind === 'safety' ? '<span class="badge">safety</span>' : '<span class="badge badge-normal">手动</span>') + '</td>' +
            '<td class="muted">' + (it.counts ? '体检 ' + (it.counts.exams || 0) + ' · 指标 ' + (it.counts.metrics || 0) + ' · 身体 ' + (it.counts.body_records || 0) : '-') + '</td>' +
            '<td>' +
              '<a class="btn btn-ghost btn-sm" href="/api/backup/' + encodeURIComponent(it.filename) + '">下载</a>' +
              ' <button type="button" class="btn btn-sm" data-restore="' + escapeHtml(it.filename) + '">还原</button>' +
              ' <button type="button" class="btn btn-danger btn-sm" data-del-backup="' + escapeHtml(it.filename) + '">删</button>' +
            '</td>' +
            '</tr>').join('') + '</tbody></table>'
        : '<p class="muted">暂无备份。</p>') +
    '</div>';

  $('backup-create-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const label = $('backup-create-form').querySelector('[name="label"]').value.trim();
    try {
      await api('/api/backup', { method: 'POST', body: { label } });
      showToast('备份完成', 'success');
      renderBackup(content);
    } catch (err) { showToast(err.message, 'error'); }
  });

  $('backup-upload-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const file = $('backup-file').files[0];
    if (!file) { showToast('请选择备份文件', 'error'); return; }
    const fd = new FormData();
    fd.append('file', file);
    try {
      await api('/api/backup/upload', { method: 'POST', body: fd });
      showToast('上传成功（校验通过）', 'success');
      renderBackup(content);
    } catch (err) { showToast(err.message, 'error'); }
  });

  const delBtns = content.querySelectorAll('[data-del-backup]');
  for (const btn of delBtns) {
    btn.addEventListener('click', async () => {
      if (!confirm('删除该备份文件？')) return;
      try {
        await api('/api/backup/' + encodeURIComponent(btn.dataset.delBackup), { method: 'DELETE' });
        showToast('已删除', 'success');
        renderBackup(content);
      } catch (err) { showToast(err.message, 'error'); }
    });
  }

  const restoreBtns = content.querySelectorAll('[data-restore]');
  for (const btn of restoreBtns) {
    btn.addEventListener('click', async () => {
      if (!confirm('用该备份还原当前数据？还原前会自动生成 safety 快照，旧库保留在 data/ 下。')) return;
      try {
        const p = await api('/api/backup/restore', { method: 'POST', body: { filename: btn.dataset.restore } });
        showToast('还原完成：体检 ' + p.data.exams + ' 条', 'success');
      } catch (err) { showToast(err.message, 'error'); }
    });
  }
}

function fmtSize(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  let n = bytes;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return n.toFixed(1) + ' ' + units[i];
}

// ── 3D 人体大屏 ──

function renderBody3d(content) {
  content.classList.add('wide');
  content.innerHTML =
    '<div class="body3d-embed">' +
      '<iframe id="body3d-frame" src="/static/body3d.html" title="3D 人体大屏"></iframe>' +
    '</div>';
}

// ── 启动 ──

window.addEventListener('hashchange', route);
document.addEventListener('DOMContentLoaded', init);