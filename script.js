/**
 * TEFAS Terminal — Dashboard, fon grafiği (dönem zoom), istatistik tablosu.
 * manifest.json: fonlar[].stats.{6M,YTD,1Y,3Y,5Y}.{sharpe,sortino,alpha,max_drawdown}
 */

const CHART_MAX_POINTS = 260;

const PERIOD_LABELS = {
  "6M": "6 ay",
  YTD: "YTD",
  "1Y": "1 yıl",
  "3Y": "3 yıl",
  "5Y": "5 yıl",
};

const NEDEN_TR = {
  bes_yildan_kisa: "5 yıldan kısa geçmiş",
  cekim_basarisiz: "veri çekilemedi",
};

let manifest = null;
let selectedPeriod = "5Y";
let currentView = "dashboard";
let activeFundMeta = null;
/** @type {{ t: number[], p: number[] } | null} */
let fullSeriesCache = null;
let chartInstance = null;
let tableSortKey = "sharpe";

async function fetchJson(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) return null;
  try {
    return await r.json();
  } catch {
    return null;
  }
}

async function loadManifest() {
  const candidates = ["data/manifest.json", "manifest.json"];
  for (const u of candidates) {
    const m = await fetchJson(u);
    if (m && Array.isArray(m.fonlar) && m.fonlar.length > 0) return m;
  }
  return null;
}

function parseRowDate(v) {
  if (v == null || v === "") return null;
  if (typeof v === "number") {
    const ms = v > 1e12 ? v : v * 1000;
    const d = new Date(ms);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  const s = String(v).trim();
  if (/^\d{10,13}$/.test(s)) {
    const n = parseInt(s, 10);
    const ms = n > 1e12 ? n : n * 1000;
    const d = new Date(ms);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  const m = s.match(/^(\d{2})\.(\d{2})\.(\d{4})/);
  if (m) {
    const d = new Date(parseInt(m[3], 10), parseInt(m[2], 10) - 1, parseInt(m[1], 10));
    return Number.isNaN(d.getTime()) ? null : d;
  }
  const iso = s.slice(0, 10);
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  return null;
}

function parseRowPrice(row) {
  const keys = ["FIYAT", "fiyat", "price", "Price"];
  for (const k of keys) {
    const x = row[k];
    if (x == null || x === "" || x === "-") continue;
    const n = typeof x === "number" ? x : parseFloat(String(x).replace(",", "."));
    if (!Number.isNaN(n) && n > 0) return n;
  }
  return null;
}

function formatLabelTr(d) {
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const yy = String(d.getFullYear()).slice(-2);
  return `${dd}.${mm}.${yy}`;
}

function downsampleSeries(labels, values, maxPts) {
  if (labels.length <= maxPts) return { labels, values };
  const step = Math.ceil(labels.length / maxPts);
  const nl = [];
  const nv = [];
  for (let i = 0; i < labels.length; i += step) {
    nl.push(labels[i]);
    nv.push(values[i]);
  }
  const li = labels.length - 1;
  if (nl[nl.length - 1] !== labels[li]) {
    nl.push(labels[li]);
    nv.push(values[li]);
  }
  return { labels: nl, values: nv };
}

function buildFullSeriesFromBundle(bundle) {
  const rows = Array.isArray(bundle.veri) ? bundle.veri : [];
  const byDay = new Map();
  for (const row of rows) {
    const dt = parseRowDate(row.TARIH ?? row.tarih ?? row.date);
    const price = parseRowPrice(row);
    if (!dt || price == null) continue;
    const key = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
    byDay.set(key, { dt, price });
  }
  const sorted = Array.from(byDay.values()).sort((a, b) => a.dt - b.dt);
  if (sorted.length === 0) return null;
  return {
    t: sorted.map((x) => x.dt.getTime()),
    p: sorted.map((x) => x.price),
  };
}

function periodStartMs(lastMs, period) {
  const end = new Date(lastMs);
  end.setHours(0, 0, 0, 0);
  if (period === "6M") {
    const s = new Date(end);
    s.setMonth(s.getMonth() - 6);
    return s.getTime();
  }
  if (period === "YTD") return new Date(end.getFullYear(), 0, 1).getTime();
  if (period === "1Y") {
    const s = new Date(end);
    s.setFullYear(s.getFullYear() - 1);
    return s.getTime();
  }
  if (period === "3Y") {
    const s = new Date(end);
    s.setFullYear(s.getFullYear() - 3);
    return s.getTime();
  }
  if (period === "5Y") {
    const s = new Date(end);
    s.setFullYear(s.getFullYear() - 5);
    return s.getTime();
  }
  return 0;
}

function sliceSeriesByPeriod(full, period) {
  if (!full || !full.t.length) return null;
  const last = full.t[full.t.length - 1];
  const cut = periodStartMs(last, period);
  const idx = [];
  for (let i = 0; i < full.t.length; i++) {
    if (full.t[i] >= cut) idx.push(i);
  }
  if (idx.length < 2) return null;
  const p0 = full.p[idx[0]];
  if (!p0 || p0 <= 0) return null;
  const labels = [];
  const values = [];
  for (const i of idx) {
    labels.push(formatLabelTr(new Date(full.t[i])));
    values.push(Number(((full.p[i] / p0) * 100).toFixed(4)));
  }
  const totalReturn = ((values[values.length - 1] - 100) / 100) * 100;
  return { labels, values, totalReturn };
}

function setChartArea(showChart) {
  const cv = document.getElementById("returnChart");
  const ph = document.getElementById("chartPlaceholder");
  if (!cv || !ph) return;
  cv.classList.toggle("hidden", !showChart);
  ph.classList.toggle("hidden", showChart);
}

function renderChart(labels, values, datasetLabel) {
  const ctx = document.getElementById("returnChart");
  if (!ctx) return;
  if (chartInstance) {
    chartInstance.destroy();
    chartInstance = null;
  }
  const grid = "rgba(255,255,255,0.06)";
  const tick = "#7d8fa3";
  chartInstance = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: datasetLabel || "Baz 100",
          data: values,
          borderColor: "#5ee9b5",
          backgroundColor: "rgba(94, 233, 181, 0.1)",
          borderWidth: 2,
          fill: true,
          tension: 0.22,
          pointRadius: 0,
          pointHoverRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: "index" },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#161d28",
          titleColor: "#e6edf3",
          bodyColor: "#9ae6b4",
          borderColor: "rgba(255,255,255,0.08)",
          borderWidth: 1,
          padding: 10,
        },
      },
      scales: {
        x: {
          grid: { color: grid },
          ticks: { color: tick, maxRotation: 0, autoSkip: true, maxTicksLimit: 14 },
        },
        y: {
          grid: { color: grid },
          ticks: { color: tick, callback: (v) => v.toFixed(0) },
        },
      },
    },
  });
}

function applyPeriodToChart() {
  const hint = document.getElementById("chartPeriodHint");
  if (hint) hint.textContent = PERIOD_LABELS[selectedPeriod] || selectedPeriod;

  if (!fullSeriesCache) return;
  const sliced = sliceSeriesByPeriod(fullSeriesCache, selectedPeriod);
  const retEl = document.getElementById("mockReturn");

  if (!sliced) {
    setChartArea(false);
    if (chartInstance) {
      chartInstance.destroy();
      chartInstance = null;
    }
    const ph = document.getElementById("chartPlaceholder");
    if (ph) {
      ph.textContent = "Seçilen dönem için yeterli veri yok.";
      ph.classList.remove("hidden");
    }
    if (retEl) {
      retEl.textContent = "—";
      retEl.classList.remove("positive", "negative");
    }
    return;
  }

  const { labels: dl, values: dv } = downsampleSeries(sliced.labels, sliced.values, CHART_MAX_POINTS);
  const sign = sliced.totalReturn >= 0 ? "+" : "";
  if (retEl) {
    retEl.textContent = `${sign}${sliced.totalReturn.toFixed(2)}% (${PERIOD_LABELS[selectedPeriod] || selectedPeriod}, baz 100)`;
    retEl.classList.remove("positive", "negative");
    retEl.classList.add(sliced.totalReturn >= 0 ? "positive" : "negative");
  }
  setChartArea(true);
  document.getElementById("chartPlaceholder").textContent = "";
  renderChart(dl, dv, `Baz 100 — ${PERIOD_LABELS[selectedPeriod] || selectedPeriod}`);
}

async function loadFundBundle(fundMeta) {
  const path = fundMeta.dosya || `data/${fundMeta.kod}_tefas.json`;
  return await fetchJson(path);
}

function emptySeriesMessage(fundMeta) {
  return (
    fundMeta.placeholderMessage ||
    "Bu fon için grafik oluşturulamadı (dosya yok veya boş veri)."
  );
}

async function selectFund(fundMeta) {
  activeFundMeta = fundMeta;
  document.getElementById("emptyState").classList.add("hidden");
  document.getElementById("panelContent").classList.remove("hidden");

  document.getElementById("fundCodeBadge").textContent = fundMeta.kod;

  const bundle = await loadFundBundle(fundMeta);
  if (!bundle) {
    fullSeriesCache = null;
    document.getElementById("fundName").textContent = fundMeta.ad || fundMeta.kod;
    document.getElementById("dataSourceTag").textContent = "Dosya yok";
    document.getElementById("mockReturn").textContent = "—";
    document.getElementById("mockReturn").classList.remove("positive", "negative");
    document.getElementById("chartCardTitle").textContent = "Grafik";
    document.getElementById("panelFootnote").innerHTML = emptySeriesMessage(fundMeta);
    if (chartInstance) {
      chartInstance.destroy();
      chartInstance = null;
    }
    setChartArea(false);
    document.getElementById("chartPlaceholder").textContent =
      "JSON yüklenemedi. Yerel sunucu kullanın (py -m http.server 8080).";
    document.getElementById("chartPlaceholder").classList.remove("hidden");
    return;
  }

  const displayName =
    (bundle.fon_unvan && String(bundle.fon_unvan).trim()) || fundMeta.ad || fundMeta.kod;
  document.getElementById("fundName").textContent = displayName;

  let tag = `${bundle.baslangic || ""} → ${bundle.bitis || ""}`;
  if (fundMeta.durum === "veri_eksik") {
    const nk = bundle.neden;
    const nt = nk ? NEDEN_TR[nk] || nk : "";
    tag = `Veri eksik${nt ? ` · ${nt}` : ""}`;
  }
  document.getElementById("dataSourceTag").textContent = tag;

  document.getElementById("chartCardTitle").textContent = "Baz 100 — pay fiyatı (TEFAS)";

  const foot = document.getElementById("panelFootnote");
  const src = bundle.kaynak ? ` Kaynak: ${bundle.kaynak}.` : "";
  foot.innerHTML = `Dönem düğmeleri grafiği seçilen aralığa göre yeniden ölçekler (baz 100, dönemin ilk günü = 100).${src}`;

  fullSeriesCache = buildFullSeriesFromBundle(bundle);
  if (!fullSeriesCache) {
    if (chartInstance) {
      chartInstance.destroy();
      chartInstance = null;
    }
    setChartArea(false);
    document.getElementById("chartPlaceholder").textContent =
      "Kayıtlarda geçerli fiyat/tarih bulunamadı.";
    document.getElementById("chartPlaceholder").classList.remove("hidden");
    document.getElementById("mockReturn").textContent = "—";
    return;
  }

  applyPeriodToChart();
}

function renderFundList() {
  const list = document.getElementById("fundList");
  const countEl = document.getElementById("fundCount");
  if (!list || !manifest) return;
  list.innerHTML = "";
  const fonlar = [...manifest.fonlar].sort((a, b) => String(a.kod).localeCompare(String(b.kod)));
  countEl.textContent = `${fonlar.length} fon`;

  fonlar.forEach((f) => {
    const li = document.createElement("li");
    li.className = "fund-item";
    if (f.durum === "veri_eksik") li.classList.add("fund-item--eksik");
    li.setAttribute("role", "button");
    li.setAttribute("tabindex", "0");
    const badge =
      f.durum === "veri_eksik"
        ? `<span class="fund-item__badge" title="${escapeHtml(f.neden || "")}">Veri eksik</span>`
        : "";
    li.innerHTML = `
      <span class="fund-item__code">${escapeHtml(f.kod)}</span>
      <div class="fund-item__col">
        <span class="fund-item__name">${escapeHtml(f.ad || f.kod)}</span>
        ${badge}
      </div>
    `;
    const meta = { kod: f.kod, ad: f.ad, dosya: f.dosya, durum: f.durum, neden: f.neden };
    const activate = () => {
      document.querySelectorAll(".fund-item").forEach((el) => el.classList.remove("active"));
      li.classList.add("active");
      selectFund(meta);
    };
    li.addEventListener("click", activate);
    li.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        activate();
      }
    });
    list.appendChild(li);
  });
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showManifestError() {
  const list = document.getElementById("fundList");
  const countEl = document.getElementById("fundCount");
  if (countEl) countEl.textContent = "0 fon";
  if (list)
    list.innerHTML = `<li class="fund-list__error">
    <strong>manifest bulunamadı.</strong><br />
    <code>py tefas_scraper.py</code> veya <code>py tefas_scraper.py --manifest-yenile</code><br />
    Sunucu: <code>py -m http.server 8080</code>
  </li>`;
}

function syncNavActive() {
  document.querySelectorAll(".terminal-nav__link").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.route === currentView);
  });
}

function showView(route) {
  currentView = route;
  syncNavActive();
  document.getElementById("view-dashboard").classList.toggle("hidden", route !== "dashboard");
  document.getElementById("view-analiz").classList.toggle("hidden", route !== "analiz");
  document.getElementById("view-karsilastirma").classList.toggle("hidden", route !== "karsilastirma");
  if (route === "karsilastirma") renderStatsTable();
  if (route === "analiz" && activeFundMeta && fullSeriesCache) applyPeriodToChart();
}

function syncPeriodButtons() {
  document.querySelectorAll(".period-toolbar .period-btn").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.period === selectedPeriod);
  });
}

function setPeriod(p) {
  selectedPeriod = p;
  syncPeriodButtons();
  if (currentView === "analiz") applyPeriodToChart();
  if (currentView === "karsilastirma") renderStatsTable();
}

function numOrNull(v) {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : parseFloat(v);
  return Number.isFinite(n) ? n : null;
}

function formatRatio(v) {
  if (v == null || !Number.isFinite(v)) return { html: '<span class="cell-missing">—</span>', sort: null };
  return { html: v.toFixed(3), sort: v };
}

function formatAlphaCell(v) {
  if (v == null || !Number.isFinite(v)) return { html: '<span class="cell-missing">—</span>', sort: null };
  const pct = (v * 100).toFixed(2);
  const cls = v >= 0 ? "alpha-pos" : "alpha-neg";
  const sign = v >= 0 ? "+" : "";
  return { html: `<span class="${cls}">${sign}${pct}%</span>`, sort: v };
}

function formatMaxDdCell(v) {
  if (v == null || !Number.isFinite(v)) return { html: '<span class="cell-missing">—</span>', sort: null };
  const pct = (v * 100).toFixed(2);
  return { html: `<span class="alpha-neg">${pct}%</span>`, sort: v };
}

function renderStatsTable() {
  const tbody = document.getElementById("statsTableBody");
  const hint = document.getElementById("tableBenchmarkHint");
  if (!tbody || !manifest) return;

  const b = manifest.benchmarks || {};
  const rf = b.risksiz_faiz_yillik != null ? `Risksiz (yıllık): %${(Number(b.risksiz_faiz_yillik) * 100).toFixed(0)}` : "";
  const xu = b.xu100_son != null ? ` · ${b.bist100_ticker || "XU100"} son: ${Number(b.xu100_son).toFixed(2)}` : "";
  const us = b.usdtry_son != null ? ` · USD/TRY: ${Number(b.usdtry_son).toFixed(4)}` : "";
  if (hint) hint.textContent = `${rf}${xu}${us}`.trim() || (b.aciklama || "");

  document.querySelectorAll(".stats-table__th--sortable").forEach((th) => {
    th.classList.toggle("is-sorted", th.dataset.sort === tableSortKey);
  });

  const rows = manifest.fonlar.map((f) => {
    const st = (f.stats && f.stats[selectedPeriod]) || {};
    return {
      kod: f.kod,
      sharpe: numOrNull(st.sharpe),
      sortino: numOrNull(st.sortino),
      alpha: numOrNull(st.alpha),
      max_drawdown: numOrNull(st.max_drawdown),
    };
  });

  rows.sort((a, b) => {
    if (tableSortKey === "kod") return String(b.kod).localeCompare(String(a.kod));
    const va = a[tableSortKey];
    const vb = b[tableSortKey];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    return vb - va;
  });

  tbody.innerHTML = rows
    .map((r) => {
      const sh = formatRatio(r.sharpe);
      const so = formatRatio(r.sortino);
      const al = formatAlphaCell(r.alpha);
      const dd = formatMaxDdCell(r.max_drawdown);
      return `<tr>
      <td>${escapeHtml(r.kod)}</td>
      <td>${sh.html}</td>
      <td>${so.html}</td>
      <td>${al.html}</td>
      <td>${dd.html}</td>
    </tr>`;
    })
    .join("");
}

function wirePeriodToolbars() {
  document.querySelectorAll(".period-toolbar .period-btn").forEach((btn) => {
    btn.addEventListener("click", () => setPeriod(btn.dataset.period));
  });
}

function wireNav() {
  document.querySelectorAll("[data-route]").forEach((el) => {
    el.addEventListener("click", () => showView(el.dataset.route));
  });
}

function wireTableSort() {
  document.querySelectorAll(".stats-table__th--sortable").forEach((th) => {
    th.addEventListener("click", () => {
      tableSortKey = th.dataset.sort || "sharpe";
      renderStatsTable();
    });
  });
}

async function init() {
  manifest = await loadManifest();
  wireNav();
  wirePeriodToolbars();
  wireTableSort();
  syncPeriodButtons();
  showView("dashboard");

  if (!manifest) {
    showManifestError();
    return;
  }
  renderFundList();
}

document.addEventListener("DOMContentLoaded", init);
