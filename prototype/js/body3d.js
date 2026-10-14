/*===============================================================
 * 文件: body3d.js
 * 项目: 健康数据监控（health-monitor）V0.3 大屏原型
 * 说明: 静态原型交互 —— mock 数据渲染 + 部位切换 + 悬浮提示
 *===============================================================*/
(function () {
  "use strict";

  /* ── mock 数据（静态原型，仅用于效果预览） ── */
  var MOCK_PARTS = {
    heart: {
      name: "心脏",
      icon: "❤",
      abnormal: true,
      metrics: [
        { name: "收缩压", value: "152", unit: "mmHg", ref: "90–139", abnormal: true, arrow: "↑", date: "2026-09-28" },
        { name: "舒张压", value: "96", unit: "mmHg", ref: "60–89", abnormal: true, arrow: "↑", date: "2026-09-28" },
        { name: "心率", value: "78", unit: "次/分", ref: "60–100", abnormal: false, arrow: "", date: "2026-09-28" }
      ]
    },
    liver: {
      name: "肝脏",
      icon: "肝",
      abnormal: true,
      metrics: [
        { name: "ALT", value: "68", unit: "U/L", ref: "9–50", abnormal: true, arrow: "↑", date: "2026-09-28" },
        { name: "AST", value: "32", unit: "U/L", ref: "15–40", abnormal: false, arrow: "", date: "2026-09-28" },
        { name: "总胆红素", value: "22.4", unit: "μmol/L", ref: "3.4–20.5", abnormal: true, arrow: "↑", date: "2026-09-28" }
      ]
    },
    kidney: {
      name: "肾脏",
      icon: "肾",
      abnormal: true,
      metrics: [
        { name: "尿酸", value: "486", unit: "μmol/L", ref: "208–428", abnormal: true, arrow: "↑", date: "2026-09-28" },
        { name: "肌酐", value: "92", unit: "μmol/L", ref: "57–97", abnormal: false, arrow: "", date: "2026-09-28" },
        { name: "尿素氮", value: "5.6", unit: "mmol/L", ref: "3.1–8.0", abnormal: false, arrow: "", date: "2026-09-28" }
      ]
    },
    pancreas: {
      name: "胰腺",
      icon: "胰",
      abnormal: true,
      metrics: [
        { name: "空腹血糖", value: "7.2", unit: "mmol/L", ref: "3.9–6.1", abnormal: true, arrow: "↑", date: "2026-09-28" },
        { name: "糖化血红蛋白", value: "6.8", unit: "%", ref: "4.0–6.0", abnormal: true, arrow: "↑", date: "2026-09-28" }
      ]
    },
    thyroid: {
      name: "甲状腺",
      icon: "甲",
      abnormal: true,
      metrics: [
        { name: "TSH", value: "0.28", unit: "mIU/L", ref: "0.35–4.94", abnormal: true, arrow: "↓", date: "2026-09-28" },
        { name: "T3", value: "1.4", unit: "nmol/L", ref: "1.1–2.6", abnormal: false, arrow: "", date: "2026-09-28" },
        { name: "T4", value: "88", unit: "nmol/L", ref: "66–181", abnormal: false, arrow: "", date: "2026-09-28" }
      ]
    },
    bone: {
      name: "骨骼/关节",
      icon: "骨",
      abnormal: true,
      metrics: [
        { name: "血钙", value: "2.62", unit: "mmol/L", ref: "2.11–2.52", abnormal: true, arrow: "↑", date: "2026-09-28" },
        { name: "维生素D", value: "18", unit: "ng/mL", ref: "30–100", abnormal: true, arrow: "↓", date: "2026-09-28" }
      ]
    },
    blood: {
      name: "血液",
      icon: "血",
      abnormal: false,
      metrics: [
        { name: "白细胞", value: "6.2", unit: "×10⁹/L", ref: "3.5–9.5", abnormal: false, arrow: "", date: "2026-09-28" },
        { name: "红细胞", value: "5.0", unit: "×10¹²/L", ref: "4.3–5.8", abnormal: false, arrow: "", date: "2026-09-28" },
        { name: "血小板", value: "260", unit: "×10⁹/L", ref: "125–350", abnormal: false, arrow: "", date: "2026-09-28" }
      ]
    },
    whole_body: {
      name: "全身",
      icon: "全",
      abnormal: true,
      metrics: [
        { name: "BMI", value: "26.8", unit: "kg/m²", ref: "18.5–23.9", abnormal: true, arrow: "↑", date: "2026-09-25" },
        { name: "体重", value: "78.5", unit: "kg", ref: "—", abnormal: true, arrow: "↑", date: "2026-09-25" }
      ]
    }
  };

  var ICON_DEFAULT = "•";
  var screen = document.getElementById("big-screen");
  var svg = document.getElementById("body-svg");
  var tooltip = document.getElementById("tooltip");
  var currentMode = "abnormal";
  var currentPart = "heart";

  /* ── 工具 ── */
  function esc(str) {
    var div = document.createElement("div");
    div.textContent = String(str == null ? "" : str);
    return div.innerHTML;
  }

  function hasAbnormal(part) {
    return part.metrics.some(function (m) { return m.abnormal; });
  }

  function partIcon(key) {
    return MOCK_PARTS[key] && MOCK_PARTS[key].icon ? MOCK_PARTS[key].icon : ICON_DEFAULT;
  }

  /* ── 统计条 ── */
  function renderStats() {
    var totalMetrics = 0;
    var abnormalMetrics = 0;
    var involvedParts = 0;
    var latest = "";

    Object.keys(MOCK_PARTS).forEach(function (key) {
      var part = MOCK_PARTS[key];
      totalMetrics += part.metrics.length;
      if (hasAbnormal(part)) involvedParts += 1;
      part.metrics.forEach(function (m) {
        if (m.abnormal) abnormalMetrics += 1;
        if (m.date > latest) latest = m.date;
      });
    });

    document.getElementById("stat-exams").textContent = "12";
    document.getElementById("stat-metrics").textContent = String(totalMetrics);
    document.getElementById("stat-abnormal").textContent = String(abnormalMetrics);
    document.getElementById("stat-parts").textContent = String(involvedParts);
    document.getElementById("stat-latest").textContent = latest;
  }

  /* ── 左栏：异常指标列表 ── */
  function abnormalItems() {
    var items = [];
    Object.keys(MOCK_PARTS).forEach(function (key) {
      var part = MOCK_PARTS[key];
      part.metrics.forEach(function (m) {
        if (m.abnormal) items.push({ part: key, partName: part.name, abnormalPart: part.abnormal, metric: m });
      });
    });
    return items;
  }

  function renderAbnormalList() {
    var container = document.getElementById("abnormal-list");
    var items = abnormalItems();
    document.getElementById("ab-count").textContent = items.length + " 项";

    if (!items.length) {
      container.innerHTML = '<p class="placeholder">暂无异常指标 🎉</p>';
      return;
    }

    var html = items.map(function (item, idx) {
      var cls = "ab-item" + (item.part === currentPart ? " active" : "") + (item.abnormalPart ? "" : " normal-part");
      return (
        '<div class="' + cls + '" data-part="' + esc(item.part) + '" data-index="' + idx + '">' +
          '<span class="part-badge">' + esc(item.partName) + "</span>" +
          '<span class="ab-main">' +
            '<span class="ab-name">' + esc(item.metric.name) +
              (item.metric.arrow ? '<span class="arrow">' + esc(item.metric.arrow) + "</span>" : "") +
            "</span>" +
            '<span class="ab-sub">参考 ' + esc(item.metric.ref) + " · " + esc(item.metric.date) + "</span>" +
          "</span>" +
          '<span class="ab-value"><b>' + esc(item.metric.value) + "</b><span class=\"ab-unit\">" + esc(item.metric.unit) + "</span></span>" +
        "</div>"
      );
    }).join("");

    container.innerHTML = html;
  }

  /* ── 右栏：部位详情 ── */
  function renderPartDetail(key) {
    var part = MOCK_PARTS[key];
    if (!part) return;
    var detail = document.getElementById("part-detail");
    var abnormal = hasAbnormal(part);
    var cls = "detail-head" + (abnormal ? "" : " normal-part");

    var rows = part.metrics.map(function (m) {
      var mCls = m.abnormal ? "m-abnormal" : "m-normal";
      var arrow = m.arrow ? '<span class="arrow-' + (m.arrow === "↓" ? "down" : "up") + '"> ' + esc(m.arrow) + "</span>" : "";
      return (
        "<tr>" +
          "<td>" + esc(m.name) + "</td>" +
          '<td class="num ' + mCls + '">' + esc(m.value) + " " + esc(m.unit) + arrow + "</td>" +
          '<td class="ref">' + esc(m.ref) + "</td>" +
          '<td class="' + mCls + '">' + (m.abnormal ? "异常" : "正常") + "</td>" +
        "</tr>"
      );
    }).join("");

    detail.innerHTML =
      '<div class="' + cls + '">' +
        '<span class="detail-icon">' + esc(part.icon) + "</span>" +
        '<div class="detail-title"><h3>' + esc(part.name) + "</h3><p>异常映射部位 · " + esc(key) + "</p></div>" +
        '<span class="status-pill' + (abnormal ? "" : " ok") + '">' + (abnormal ? "有异常" : "正常") + "</span>" +
      "</div>" +
      '<table class="metric-table"><thead><tr><th>指标</th><th>结果</th><th>参考范围</th><th>状态</th></tr></thead><tbody>' +
        rows +
      "</tbody></table>" +
      '<div class="detail-foot">点击左侧异常指标或人体部位可切换查看。真实大屏将支持旋转 / 缩放。</div>';
  }

  /* ── 选中部位 ── */
  function selectPart(key) {
    currentPart = key;
    var parts = svg.querySelectorAll(".part");
    Array.prototype.forEach.call(parts, function (g) {
      var isCurrent = g.getAttribute("data-part") === key;
      g.classList.toggle("active", isCurrent);
    });
    renderAbnormalList();
    renderPartDetail(key);
  }

  /* ── 切换模式 ── */
  function setMode(mode) {
    currentMode = mode;
    screen.classList.toggle("mode-abnormal", mode === "abnormal");
    screen.classList.toggle("mode-all", mode === "all");
    var btns = document.querySelectorAll("#mode-toggle .seg-btn");
    Array.prototype.forEach.call(btns, function (b) {
      b.classList.toggle("active", b.getAttribute("data-mode") === mode);
    });
  }

  /* ── 悬浮提示 ── */
  function bindTooltip() {
    var parts = svg.querySelectorAll(".part");
    Array.prototype.forEach.call(parts, function (g) {
      var key = g.getAttribute("data-part");
      var part = MOCK_PARTS[key];
      if (!part) return;
      g.addEventListener("mousemove", function (e) {
        var ab = hasAbnormal(part);
        var first = part.metrics.filter(function (m) { return m.abnormal; })[0] || part.metrics[0];
        var html = "<b>" + esc(part.name) + "</b> · ";
        if (first) {
          html += esc(first.name) + " " + esc(first.value) + esc(first.unit);
          if (first.abnormal) html += ' <span class="tt-abnormal">' + esc(first.arrow) + " 异常</span>";
        }
        tooltip.innerHTML = html;
        tooltip.hidden = false;
        tooltip.style.left = e.clientX + 14 + "px";
        tooltip.style.top = e.clientY + 14 + "px";
      });
      g.addEventListener("mouseleave", function () {
        tooltip.hidden = true;
      });
      g.addEventListener("click", function () {
        selectPart(key);
      });
    });
  }

  /* ── 时钟 ── */
  function tick() {
    var now = new Date();
    function pad(n) { return n < 10 ? "0" + n : String(n); }
    document.getElementById("clock").textContent =
      pad(now.getHours()) + ":" + pad(now.getMinutes()) + ":" + pad(now.getSeconds());
  }

  /* ── 事件绑定 ── */
  function bindEvents() {
    var segBtns = document.querySelectorAll("#mode-toggle .seg-btn");
    Array.prototype.forEach.call(segBtns, function (btn) {
      btn.addEventListener("click", function () {
        setMode(btn.getAttribute("data-mode"));
      });
    });

    document.getElementById("abnormal-list").addEventListener("click", function (e) {
      var item = e.target.closest(".ab-item");
      if (item) selectPart(item.getAttribute("data-part"));
    });
  }

  /* ── 初始化 ── */
  function init() {
    // 体重/BMI 异常 → 全身光晕
    if (hasAbnormal(MOCK_PARTS.whole_body)) screen.classList.add("wb-abnormal");

    renderStats();
    renderAbnormalList();
    renderPartDetail(currentPart);
    setMode(currentMode);
    selectPart(currentPart);
    bindTooltip();
    bindEvents();
    tick();
    setInterval(tick, 1000);
  }

  document.addEventListener("DOMContentLoaded", init);
})();