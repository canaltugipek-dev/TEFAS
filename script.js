/**
 * TEFAS Terminal — Dashboard, fon grafiği (dönem zoom), istatistik tablosu.
 * manifest.json: fonlar[].stats.{6M,YTD,1Y,3Y,5Y}.{sharpe,sortino,alpha,max_drawdown}
 */

const CHART_MAX_POINTS = 260;
/** Python tefas_scraper.compute_period_stats ile uyumlu */
const TRADING_DAYS_METRICS = 252;
const MIN_OBS_METRICS = 20;

const PERIOD_LABELS = {
  "6M": "6 ay",
  YTD: "YTD",
  "1Y": "1 yıl",
  "3Y": "3 yıl",
  "5Y": "5 yıl",
  SPECIFIC: "Spesifik aralık",
};

const NEDEN_TR = {
  bes_yildan_kisa: "5 yıldan kısa geçmiş",
  cekim_basarisiz: "veri çekilemedi",
};
const BANK_MANAGER_PATTERNS = [
  "AK PORTFOY",
  "IS PORTFOY",
  "TEB PORTFOY",
  "QNB PORTFOY",
  "DENIZ PORTFOY",
  "GARANTI PORTFOY",
  "YAPI KREDI PORTFOY",
  "ZIRAAT PORTFOY",
  "HALK PORTFOY",
  "VAKIF PORTFOY",
  "KUVEYT TURK PORTFOY",
  "ALBARAKA PORTFOY",
  "TURKIYE FINANS PORTFOY",
  "ING PORTFOY",
  "SEKER PORTFOY",
  "FIBA PORTFOY",
  "ODEA PORTFOY",
  "HSBC PORTFOY",
  "BURGAN PORTFOY",
  "EMLAK PORTFOY",
  "BANKA",
  "BANK ",
  "KATILIM",
];
const INDEX_FUND_PATTERNS = [
  "ENDEKS",
  "BIST ",
  "BIST100",
  "BIST 100",
  "BIST30",
  "BIST 30",
  "BIST50",
  "BIST 50",
];

function normalizeManagerText(s) {
  const trMap = {
    İ: "I",
    I: "I",
    ı: "I",
    Ş: "S",
    ş: "S",
    Ğ: "G",
    ğ: "G",
    Ü: "U",
    ü: "U",
    Ö: "O",
    ö: "O",
    Ç: "C",
    ç: "C",
  };
  return String(s || "")
    .replace(/[İIışŞğĞüÜöÖçÇ]/g, (ch) => trMap[ch] || ch)
    .toUpperCase();
}

function isBankManagedFund(name) {
  const n = normalizeManagerText(name);
  return BANK_MANAGER_PATTERNS.some((token) => n.includes(token));
}

function isIndexEquityFund(name) {
  const n = normalizeManagerText(name);
  return INDEX_FUND_PATTERNS.some((token) => n.includes(token));
}

let manifest = null;
let selectedPeriod = "1Y";
let currentView = "dashboard";
let statsTableRenderToken = 0;
let activeFundMeta = null;
/** @type {{ t: number[], p: number[] } | null} */
let fullSeriesCache = null;
let chartInstance = null;
let tableSortKey = "sharpe";
let fundSearchQuery = "";
const compareSeriesCache = new Map();
let compareRenderToken = 0;
let benchmarks = null;
let selectedBenchmark = "none";

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

async function loadBenchmarks() {
  const candidates = ["data/benchmarks.json", "benchmarks.json"];
  for (const u of candidates) {
    const b = await fetchJson(u);
    if (b && b.series) return b;
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

function ymdLocalFromDate(d) {
  if (!d || Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function parseDateInputLocalStartMs(isoYmd) {
  const p = String(isoYmd)
    .slice(0, 10)
    .split("-")
    .map((x) => parseInt(x, 10));
  if (p.length !== 3 || p.some((x) => Number.isNaN(x))) return NaN;
  const d = new Date(p[0], p[1] - 1, p[2], 0, 0, 0, 0);
  return d.getTime();
}

function parseDateInputLocalEndInclusive(isoYmd) {
  const p = String(isoYmd)
    .slice(0, 10)
    .split("-")
    .map((x) => parseInt(x, 10));
  if (p.length !== 3 || p.some((x) => Number.isNaN(x))) return NaN;
  const d = new Date(p[0], p[1] - 1, p[2], 23, 59, 59, 999);
  return d.getTime();
}

function readGlobalSpecificRangeFromInputs() {
  const startEl = document.querySelector(".js-specific-start");
  const endEl = document.querySelector(".js-specific-end");
  if (!startEl || !endEl) return null;
  const s = String(startEl.value || "").trim();
  const e = String(endEl.value || "").trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s) || !/^\d{4}-\d{2}-\d{2}$/.test(e)) return null;
  const startMs = parseDateInputLocalStartMs(s);
  const endMs = parseDateInputLocalEndInclusive(e);
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || startMs > endMs) return null;
  return { startMs, endMs, startIso: s, endIso: e };
}

function setAllSpecificDateInputs(startIso, endIso) {
  document.querySelectorAll(".js-specific-start").forEach((el) => {
    el.value = startIso;
  });
  document.querySelectorAll(".js-specific-end").forEach((el) => {
    el.value = endIso;
  });
}

function ensureGlobalSpecificDatesDefault() {
  const starts = document.querySelectorAll(".js-specific-start");
  const ends = document.querySelectorAll(".js-specific-end");
  if (!starts.length || !ends.length) return;
  if (starts[0].value && ends[0].value) return;
  let endStr = "";
  let startStr = "";
  if (fullSeriesCache && fullSeriesCache.t.length) {
    const lastMs = fullSeriesCache.t[fullSeriesCache.t.length - 1];
    const lastD = new Date(lastMs);
    endStr = ymdLocalFromDate(lastD);
    const startD = new Date(lastMs);
    startD.setFullYear(startD.getFullYear() - 1);
    startStr = ymdLocalFromDate(startD);
  } else if (manifest && manifest.guncelleme) {
    const g = String(manifest.guncelleme).slice(0, 10);
    if (/^\d{4}-\d{2}-\d{2}$/.test(g)) {
      endStr = g;
      const d = new Date(parseInt(g.slice(0, 4), 10), parseInt(g.slice(5, 7), 10) - 1, parseInt(g.slice(8, 10), 10));
      d.setFullYear(d.getFullYear() - 1);
      startStr = ymdLocalFromDate(d);
    }
  }
  if (endStr && startStr) setAllSpecificDateInputs(startStr, endStr);
}

function getPeriodHintText() {
  if (selectedPeriod !== "SPECIFIC") return PERIOD_LABELS[selectedPeriod] || selectedPeriod;
  const r = readGlobalSpecificRangeFromInputs();
  if (!r) return PERIOD_LABELS.SPECIFIC || "Spesifik";
  const ps = r.startIso.split("-").map((x) => parseInt(x, 10));
  const pe = r.endIso.split("-").map((x) => parseInt(x, 10));
  const sd = new Date(ps[0], ps[1] - 1, ps[2]);
  const ed = new Date(pe[0], pe[1] - 1, pe[2]);
  return `${formatLabelTr(sd)}–${formatLabelTr(ed)}`;
}

function isoYmdLocalFromMs(ms) {
  const d = new Date(ms);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function annualPolicyDecimalFromBench(bench, isoYmd) {
  if (!bench || !isoYmd) return null;
  const yPct = Number(bench.risksiz_faiz_yillik) * 100;
  const pPct = politikOranTcmbBul(
    bench.politika_faizi_degisimleri,
    bench.politika_faizi_ay_sonu,
    isoYmd,
    yPct
  );
  if (pPct != null && Number.isFinite(pPct)) return pPct / 100;
  const rf = Number(bench.risksiz_faiz_yillik);
  return Number.isFinite(rf) ? rf : null;
}

function linearRegressionSlopeIntercept(xs, ys) {
  const n = xs.length;
  if (n < 2 || n !== ys.length) return { slope: 0, intercept: 0 };
  let sx = 0;
  let sy = 0;
  let sxx = 0;
  let sxy = 0;
  for (let i = 0; i < n; i++) {
    sx += xs[i];
    sy += ys[i];
    sxx += xs[i] * xs[i];
    sxy += xs[i] * ys[i];
  }
  const denom = n * sxx - sx * sx;
  if (Math.abs(denom) < 1e-18) return { slope: 0, intercept: 0 };
  const slope = (n * sxy - sx * sy) / denom;
  const intercept = (sy - slope * sx) / n;
  return { slope, intercept };
}

/**
 * Python compute_period_stats ile aynı mantık: fon + BIST100 günlük getiri, TCMB politika faizi
 * (manifest) günlük bileşik risksiz, CAPM alpha (günlük intercept yıllandırılmış).
 */
function computeStatsForSpecificWindow(fundSeries, bench) {
  const out = { sharpe: null, sortino: null, alpha: null, max_drawdown: null };
  if (!fundSeries || !fundSeries.t || fundSeries.t.length < 2 || !bench) return out;
  const r = readGlobalSpecificRangeFromInputs();
  if (!r) return out;

  const idx = [];
  for (let i = 0; i < fundSeries.t.length; i++) {
    if (fundSeries.t[i] >= r.startMs && fundSeries.t[i] <= r.endMs) idx.push(i);
  }
  if (idx.length < MIN_OBS_METRICS) return out;

  const bs = getBenchmarkSeriesByKey("bist100");
  if (!bs || !bs.t || bs.t.length < 2) return out;

  const tRaw = idx.map((i) => fundSeries.t[i]);
  const pRaw = idx.map((i) => fundSeries.p[i]);
  const mRaw = tRaw.map((t) => benchmarkValueAsOf(bs, t));
  let lastM = null;
  for (let i = 0; i < mRaw.length; i++) {
    if (mRaw[i] != null && Number.isFinite(mRaw[i]) && mRaw[i] > 0) lastM = mRaw[i];
    else if (lastM != null) mRaw[i] = lastM;
  }
  let nextM = null;
  for (let i = mRaw.length - 1; i >= 0; i--) {
    if (mRaw[i] != null && Number.isFinite(mRaw[i]) && mRaw[i] > 0) nextM = mRaw[i];
    else if (nextM != null) mRaw[i] = nextM;
  }

  const tArr = [];
  const pArr = [];
  const mArr = [];
  for (let i = 0; i < pRaw.length; i++) {
    const pv = pRaw[i];
    const mv = mRaw[i];
    if (pv > 0 && mv != null && Number.isFinite(mv) && mv > 0) {
      tArr.push(tRaw[i]);
      pArr.push(pv);
      mArr.push(mv);
    }
  }
  if (tArr.length < MIN_OBS_METRICS) return out;

  const rfConst = Number(bench.risksiz_faiz_yillik);
  const constD =
    Number.isFinite(rfConst) && rfConst > 0 ? Math.pow(1 + rfConst, 1 / TRADING_DAYS_METRICS) - 1 : 0;

  const retF = [];
  const retM = [];
  const rfAt = [];
  for (let i = 1; i < pArr.length; i++) {
    if (pArr[i - 1] <= 0 || pArr[i] <= 0) continue;
    if (mArr[i - 1] <= 0 || mArr[i] <= 0) continue;
    const isoEnd = isoYmdLocalFromMs(tArr[i]);
    const annDec = annualPolicyDecimalFromBench(bench, isoEnd);
    const dec = annDec != null && Number.isFinite(annDec) ? annDec : rfConst;
    const rfD =
      dec != null && Number.isFinite(dec) && dec > 0
        ? Math.pow(1 + dec, 1 / TRADING_DAYS_METRICS) - 1
        : constD;
    retF.push(pArr[i] / pArr[i - 1] - 1);
    retM.push(mArr[i] / mArr[i - 1] - 1);
    rfAt.push(rfD);
  }

  if (retF.length < MIN_OBS_METRICS) return out;

  const excess = retF.map((rv, j) => rv - rfAt[j]);
  const mean = excess.reduce((a, b) => a + b, 0) / excess.length;
  const variance = excess.reduce((a, e) => a + (e - mean) ** 2, 0) / Math.max(1, excess.length - 1);
  const std = Math.sqrt(Math.max(variance, 0));
  if (std > 1e-12) {
    out.sharpe = Number(((Math.sqrt(TRADING_DAYS_METRICS) * mean) / std).toFixed(6));
  }

  const negExc = excess.map((e) => Math.min(0, e));
  const ddev = Math.sqrt(negExc.reduce((a, e) => a + e * e, 0) / negExc.length);
  if (ddev > 1e-12) {
    out.sortino = Number(((Math.sqrt(TRADING_DAYS_METRICS) * mean) / ddev).toFixed(6));
  }

  const xm = retM.map((rm, j) => rm - rfAt[j]);
  const yv = excess;
  const xmF = [];
  const yvF = [];
  for (let j = 0; j < xm.length; j++) {
    if (Number.isFinite(xm[j]) && Number.isFinite(yv[j])) {
      xmF.push(xm[j]);
      yvF.push(yv[j]);
    }
  }
  const { intercept } = linearRegressionSlopeIntercept(xmF, yvF);
  if (Number.isFinite(intercept) && xmF.length >= MIN_OBS_METRICS) {
    out.alpha = Number((Math.pow(1 + intercept, TRADING_DAYS_METRICS) - 1).toFixed(6));
  }

  const p0 = pArr[0];
  if (p0 > 0) {
    let peak = 1;
    let minDd = 0;
    for (let i = 0; i < pArr.length; i++) {
      const px = pArr[i] / p0;
      if (px > peak) peak = px;
      const dd = px / peak - 1;
      if (dd < minDd) minDd = dd;
    }
    out.max_drawdown = Number(minDd.toFixed(6));
  }

  return out;
}

function sliceSeriesByCustomRange(full, startMs, endMs) {
  if (!full || !full.t.length) return null;
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || startMs > endMs) return null;
  const idx = [];
  for (let i = 0; i < full.t.length; i++) {
    if (full.t[i] >= startMs && full.t[i] <= endMs) idx.push(i);
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
  return { labels, values, totalReturn, t: idx.map((i) => full.t[i]) };
}

function sliceFundSeriesForSelectedPeriod(full) {
  if (!full || !full.t.length) return null;
  if (selectedPeriod === "SPECIFIC") {
    ensureGlobalSpecificDatesDefault();
    const r = readGlobalSpecificRangeFromInputs();
    if (!r) return null;
    return sliceSeriesByCustomRange(full, r.startMs, r.endMs);
  }
  return sliceSeriesByPeriod(full, selectedPeriod);
}

function seriesReturnForSelectedPeriodSlice(series) {
  if (!series || !series.t || series.t.length < 2) return null;
  if (selectedPeriod === "SPECIFIC") {
    ensureGlobalSpecificDatesDefault();
    const r = readGlobalSpecificRangeFromInputs();
    if (!r) return null;
    const s = sliceSeriesByCustomRange(series, r.startMs, r.endMs);
    return s ? s.totalReturn : null;
  }
  const s = sliceSeriesByPeriod(series, selectedPeriod);
  return s ? s.totalReturn : null;
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
  return { labels, values, totalReturn, t: idx.map((i) => full.t[i]) };
}

function setChartArea(showChart) {
  const cv = document.getElementById("returnChart");
  const ph = document.getElementById("chartPlaceholder");
  if (!cv || !ph) return;
  cv.classList.toggle("hidden", !showChart);
  ph.classList.toggle("hidden", showChart);
}

function renderChart(labels, datasets) {
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
      datasets,
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      spanGaps: false,
      interaction: { intersect: false, mode: "index" },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#161d28",
          titleColor: "#e6edf3",
          bodyColor: "#9dcae8",
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

function benchmarkRowsToSeries(rows) {
  if (!Array.isArray(rows) || rows.length === 0) return null;
  const points = [];
  rows.forEach((r) => {
    const dt = parseRowDate(r.tarih);
    const val = numOrNull(r.deger);
    if (!dt || val == null || val <= 0) return;
    points.push({ t: dt.getTime(), p: val });
  });
  points.sort((a, b) => a.t - b.t);
  if (points.length < 2) return null;
  return { t: points.map((x) => x.t), p: points.map((x) => x.p) };
}

function getBenchmarkSeriesByKey(key) {
  if (!benchmarks || !benchmarks.series) return null;
  if (key === "usd") return benchmarkRowsToSeries(benchmarks.series.usdtry || []);
  if (key === "bist100") return benchmarkRowsToSeries(benchmarks.series.bist100 || []);
  if (key === "tufe") return benchmarkRowsToSeries(benchmarks.series.tufe_index || []);
  return null;
}

/** Seri zaman damgasi <= tMs olan son gozlem (aylik TUFEda gunluk fon tarihleri icin zorunlu). */
function benchmarkValueAsOf(bs, tMs) {
  if (!bs || !bs.t || bs.t.length === 0) return null;
  const t = Number(tMs);
  if (!Number.isFinite(t)) return null;
  if (t < bs.t[0]) return bs.p[0];
  const last = bs.t.length - 1;
  if (t >= bs.t[last]) return bs.p[last];
  let lo = 0;
  let hi = last;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (bs.t[mid] <= t) {
      ans = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  if (ans < 0) return bs.p[0];
  const v = bs.p[ans];
  return v != null && Number.isFinite(v) && v > 0 ? v : null;
}

function buildBenchmarkOverlayValues(key, fundPeriodTimes) {
  const bs = getBenchmarkSeriesByKey(key);
  if (!bs || !Array.isArray(fundPeriodTimes) || fundPeriodTimes.length < 2) return null;
  const raw = fundPeriodTimes.map((t) => benchmarkValueAsOf(bs, t));
  const first = raw.find((v) => v != null && Number.isFinite(v) && v > 0);
  if (first == null) return null;
  return raw.map((v) =>
    v == null || !Number.isFinite(v) || v <= 0 ? null : Number(((v / first) * 100).toFixed(4))
  );
}

function seriesReturnPct(series, period) {
  const sliced = sliceSeriesByPeriod(series, period);
  if (!sliced) return null;
  return sliced.totalReturn;
}

function setSummaryValue(elId, pct) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (pct == null || !Number.isFinite(pct)) {
    el.textContent = "—";
    el.classList.remove("positive", "negative");
    return;
  }
  const sign = pct >= 0 ? "+" : "";
  el.textContent = `${sign}${pct.toFixed(2)}%`;
  el.classList.remove("positive", "negative");
  el.classList.add(pct >= 0 ? "positive" : "negative");
}

function applyPeriodToChart() {
  const hint = document.getElementById("chartPeriodHint");
  if (fullSeriesCache && selectedPeriod === "SPECIFIC") ensureGlobalSpecificDatesDefault();
  if (hint) hint.textContent = getPeriodHintText();

  if (!fullSeriesCache) return;
  const sliced = sliceFundSeriesForSelectedPeriod(fullSeriesCache);
  const retEl = document.getElementById("mockReturn");
  const periodHint = getPeriodHintText();

  if (!sliced) {
    setChartArea(false);
    if (chartInstance) {
      chartInstance.destroy();
      chartInstance = null;
    }
    const ph = document.getElementById("chartPlaceholder");
    if (ph) {
      ph.textContent =
        selectedPeriod === "SPECIFIC"
          ? "Geçerli bir tarih aralığı seçin veya bu aralıkta yeterli işlem günü yok."
          : "Seçilen dönem için yeterli veri yok.";
      ph.classList.remove("hidden");
    }
    if (retEl) {
      retEl.textContent = "—";
      retEl.classList.remove("positive", "negative");
    }
    setSummaryValue("summaryFundReturn", null);
    setSummaryValue("summaryUsdReturn", null);
    setSummaryValue("summaryBistReturn", null);
    setSummaryValue("summaryTufeReturn", null);
    return;
  }

  const { labels: dl, values: dv } = downsampleSeries(sliced.labels, sliced.values, CHART_MAX_POINTS);
  const sign = sliced.totalReturn >= 0 ? "+" : "";
  if (retEl) {
    retEl.textContent = `${sign}${sliced.totalReturn.toFixed(2)}% (${periodHint}, baz 100)`;
    retEl.classList.remove("positive", "negative");
    retEl.classList.add(sliced.totalReturn >= 0 ? "positive" : "negative");
  }
  setChartArea(true);
  document.getElementById("chartPlaceholder").textContent = "";
  const datasets = [
    {
      label: `Fon — ${periodHint}`,
      data: dv,
      borderColor: "#3ecf8e",
      backgroundColor: "rgba(62, 207, 142, 0.12)",
      borderWidth: 3,
      fill: true,
      tension: 0.22,
      pointRadius: 0,
      pointHoverRadius: 0,
    },
  ];

  if (selectedBenchmark !== "none") {
    const benchmarkValsFull = buildBenchmarkOverlayValues(selectedBenchmark, sliced.t);
    if (benchmarkValsFull) {
      const ds = downsampleSeries(sliced.labels, benchmarkValsFull, CHART_MAX_POINTS);
      const benchmarkStyle = {
        usd: { label: "USD (baz 100)", color: "#fb923c" },
        bist100: { label: "BIST100 (baz 100)", color: "#38bdf8" },
        tufe: { label: "TÜFE (baz 100)", color: "#e879f9" },
      };
      const style = benchmarkStyle[selectedBenchmark];
      if (style) {
        datasets.push({
          label: style.label,
          data: ds.values,
          borderColor: style.color,
          backgroundColor: "transparent",
          borderWidth: 2,
          fill: false,
          tension: 0.12,
          pointRadius: 0,
          pointHoverRadius: 0,
          spanGaps: false,
        });
      }
    }
  }

  renderChart(dl, datasets);

  setSummaryValue("summaryFundReturn", sliced.totalReturn);
  setSummaryValue("summaryUsdReturn", seriesReturnForSelectedPeriodSlice(getBenchmarkSeriesByKey("usd")));
  setSummaryValue("summaryBistReturn", seriesReturnForSelectedPeriodSlice(getBenchmarkSeriesByKey("bist100")));
  setSummaryValue("summaryTufeReturn", seriesReturnForSelectedPeriodSlice(getBenchmarkSeriesByKey("tufe")));
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
      "JSON yüklenemedi. Yerel sunucu kullanın (.venv/Scripts/python -m http.server 8080).";
    document.getElementById("chartPlaceholder").classList.remove("hidden");
    setSummaryValue("summaryFundReturn", null);
    setSummaryValue("summaryUsdReturn", null);
    setSummaryValue("summaryBistReturn", null);
    setSummaryValue("summaryTufeReturn", null);
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
    setSummaryValue("summaryFundReturn", null);
    setSummaryValue("summaryUsdReturn", null);
    setSummaryValue("summaryBistReturn", null);
    setSummaryValue("summaryTufeReturn", null);
    return;
  }

  applyPeriodToChart();
}

function renderFundList() {
  const list = document.getElementById("fundList");
  const countEl = document.getElementById("fundCount");
  if (!list || !manifest) return;
  list.innerHTML = "";
  const allFunds = [...manifest.fonlar].sort((a, b) => String(a.kod).localeCompare(String(b.kod)));
  const q = fundSearchQuery.trim().toUpperCase();
  const fonlar = q
    ? allFunds.filter((f) => String(f.kod || "").toUpperCase().includes(q))
    : allFunds;
  countEl.textContent = `${fonlar.length}/${allFunds.length} fon`;

  if (fonlar.length === 0) {
    list.innerHTML = `<li class="fund-list__error">Aramaya uygun fon bulunamadı.</li>`;
    return;
  }

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

async function getFundSeriesByCode(kod) {
  if (!manifest || !kod) return null;
  if (compareSeriesCache.has(kod)) return compareSeriesCache.get(kod);
  const fundMeta = manifest.fonlar.find((f) => String(f.kod) === String(kod));
  if (!fundMeta) return null;
  const bundle = await loadFundBundle(fundMeta);
  if (!bundle) return null;
  const series = buildFullSeriesFromBundle(bundle);
  if (series) compareSeriesCache.set(kod, series);
  return series;
}

function computePeriodReturnAndVol(series, period) {
  if (!series || !series.t || series.t.length < 2) return { periodReturn: null, volatility: null };
  const prices = [];
  if (period === "SPECIFIC") {
    const r = readGlobalSpecificRangeFromInputs();
    if (!r) return { periodReturn: null, volatility: null };
    for (let i = 0; i < series.t.length; i++) {
      if (series.t[i] >= r.startMs && series.t[i] <= r.endMs) prices.push(series.p[i]);
    }
  } else {
    const last = series.t[series.t.length - 1];
    const cut = periodStartMs(last, period);
    for (let i = 0; i < series.t.length; i++) {
      if (series.t[i] >= cut) prices.push(series.p[i]);
    }
  }
  if (prices.length < 2 || prices[0] <= 0) return { periodReturn: null, volatility: null };

  const periodReturn = prices[prices.length - 1] / prices[0] - 1;
  const rets = [];
  for (let i = 1; i < prices.length; i++) {
    if (prices[i - 1] > 0) rets.push(prices[i] / prices[i - 1] - 1);
  }
  if (rets.length < 2) return { periodReturn, volatility: null };

  const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
  const variance = rets.reduce((a, r) => a + (r - mean) ** 2, 0) / (rets.length - 1);
  const volatility = Math.sqrt(Math.max(variance, 0)) * Math.sqrt(252);
  return { periodReturn, volatility };
}

const PREFERRED_COMPARE_DEFAULTS = ["AAV", "ACC", "IDH", "TCD", "TAU"];

/** Fon karşılaştırma — Fon Rasyoları ile aynı gun_kapsami eşiği (seçilen döneme göre). */
function sortedFundsEligibleForComparison() {
  if (!manifest) return [];
  return [...manifest.fonlar]
    .filter((f) => fundHasEnoughHistoryForRatioPeriod(f, selectedPeriod, manifest))
    .sort((a, b) => String(a.kod).localeCompare(String(b.kod)));
}

function pickCompareDefaultCodes(sortedFunds) {
  const kodSet = new Set(sortedFunds.map((f) => String(f.kod)));
  const out = [];
  for (const k of PREFERRED_COMPARE_DEFAULTS) {
    if (kodSet.has(k)) out.push(k);
  }
  for (const f of sortedFunds) {
    if (out.length >= 5) break;
    const k = String(f.kod);
    if (!out.includes(k)) out.push(k);
  }
  return out.slice(0, 5);
}

function populateCompareSelectors() {
  if (!manifest) return;
  const sorted = sortedFundsEligibleForComparison();
  const selectIds = ["compareFund1", "compareFund2", "compareFund3", "compareFund4", "compareFund5"];
  const kodSetElig = new Set(sorted.map((f) => String(f.kod)));
  const defaults = pickCompareDefaultCodes(sorted);
  const priorSel = selectIds.map((id) => {
    const sel = document.getElementById(id);
    return sel ? String(sel.value || "") : "";
  });

  selectIds.forEach((id, idx) => {
    const sel = document.getElementById(id);
    if (!sel) return;
    sel.innerHTML = "";
    const emptyOpt = document.createElement("option");
    emptyOpt.value = "";
    emptyOpt.textContent = "Fon seç";
    sel.appendChild(emptyOpt);

    sorted.forEach((f) => {
      const opt = document.createElement("option");
      opt.value = f.kod;
      opt.textContent = `${f.kod} - ${f.ad || f.kod}`;
      sel.appendChild(opt);
    });

    let kod = "";
    if (priorSel[idx] && kodSetElig.has(priorSel[idx])) kod = priorSel[idx];
    else if (defaults[idx] && kodSetElig.has(defaults[idx])) kod = defaults[idx];
    sel.value = kod;
  });
}

function getSelectedCompareRows() {
  if (!manifest) return [];
  const byKod = new Map(manifest.fonlar.map((f) => [String(f.kod), f]));
  const selectIds = ["compareFund1", "compareFund2", "compareFund3", "compareFund4", "compareFund5"];
  return selectIds.map((id) => {
    const sel = document.getElementById(id);
    const kod = sel ? String(sel.value || "") : "";
    const f = kod && byKod.has(kod) ? byKod.get(kod) : null;
    if (!f) return null;
    if (!fundHasEnoughHistoryForRatioPeriod(f, selectedPeriod, manifest)) return null;
    return f;
  });
}

function fmtPercent(v) {
  if (v == null || !Number.isFinite(v)) return '<span class="cell-missing">—</span>';
  const sign = v >= 0 ? "+" : "";
  const cls = v >= 0 ? "alpha-pos" : "alpha-neg";
  return `<span class="${cls}">${sign}${(v * 100).toFixed(2)}%</span>`;
}

/** Yilliklandirilmis volatilite (ondalik): dusuk = yesil, yuksek = kirmizi (HSYF icin kabaca esikler). */
function fmtVolatilityRisk(v) {
  if (v == null || !Number.isFinite(v)) return '<span class="cell-missing">—</span>';
  const pct = v * 100;
  const sign = v >= 0 ? "+" : "";
  let risk = "risk-metric--mid";
  if (v <= 0.18) risk = "risk-metric--low";
  else if (v > 0.28) risk = "risk-metric--high";
  return `<span class="risk-metric ${risk}">${sign}${pct.toFixed(2)}%</span>`;
}

/** Max drawdown (ondalik, genelde negatif): 0'a yakin = yesil, cok negatif = kirmizi. */
function fmtMaxDrawdownRisk(v) {
  if (v == null || !Number.isFinite(v)) return '<span class="cell-missing">—</span>';
  const pct = v * 100;
  let risk = "risk-metric--mid";
  if (v >= -0.1) risk = "risk-metric--low";
  else if (v < -0.22) risk = "risk-metric--high";
  return `<span class="risk-metric ${risk}">${pct.toFixed(2)}%</span>`;
}

async function renderMultiCompareTable() {
  const tbody = document.getElementById("compareTableBody");
  if (!tbody || !manifest) return;
  const token = ++compareRenderToken;
  if (selectedPeriod === "SPECIFIC") ensureGlobalSpecificDatesDefault();
  tbody.innerHTML = `<div class="compare-matrix-wrap"><div class="terminal-grid__row terminal-grid__row--loading" role="row"><div class="terminal-grid__cell terminal-grid__cell--span-full terminal-grid__cell--loading" role="status">Yükleniyor...</div></div></div><div class="compare-cards-wrap" role="list"></div>`;
  const selected = getSelectedCompareRows();
  const headIds = ["compareHead1", "compareHead2", "compareHead3", "compareHead4", "compareHead5"];
  selected.forEach((f, i) => {
    const th = document.getElementById(headIds[i]);
    if (th) th.textContent = f ? f.kod : "—";
  });

  const computed = await Promise.all(
    selected.map(async (f) => {
      if (!f) return { periodReturn: null, volatility: null };
      const series = await getFundSeriesByCode(f.kod);
      return computePeriodReturnAndVol(series, selectedPeriod);
    })
  );
  if (token !== compareRenderToken) return;

  let specificStatsList = [];
  if (selectedPeriod === "SPECIFIC" && readGlobalSpecificRangeFromInputs()) {
    const bench = manifest.benchmarks || {};
    specificStatsList = await Promise.all(
      selected.map(async (f) => {
        if (!f) return {};
        const series = await getFundSeriesByCode(f.kod);
        return computeStatsForSpecificWindow(series, bench);
      })
    );
    if (token !== compareRenderToken) return;
  }

  const statsFor = (f, idx) => {
    if (selectedPeriod === "SPECIFIC" && f && specificStatsList[idx]) {
      return specificStatsList[idx];
    }
    return f && f.stats && f.stats[selectedPeriod] ? f.stats[selectedPeriod] : {};
  };
  const rowDefs = [
    {
      label: "Dönem Getirisi",
      render: (st, idx) => fmtPercent(numOrNull(computed[idx].periodReturn)),
    },
    {
      label: "Volatilite",
      render: (st, idx) => fmtVolatilityRisk(numOrNull(computed[idx].volatility)),
    },
    {
      label: "Sharpe",
      render: (st) => formatRatio(numOrNull(st.sharpe)).html,
    },
    {
      label: "Sortino",
      render: (st) => formatRatio(numOrNull(st.sortino)).html,
    },
    {
      label: "Alpha (BIST100)",
      render: (st) => formatAlphaCell(numOrNull(st.alpha)).html,
    },
    {
      label: "Max Drawdown",
      render: (st) => fmtMaxDrawdownRisk(numOrNull(st.max_drawdown)),
    },
  ];

  const matrixHtml = rowDefs
    .map((rowDef) => {
      const cells = selected
        .map((f, idx) => {
          const st = statsFor(f, idx);
          return `<div class="terminal-grid__cell terminal-grid__cell--col-num">${rowDef.render(st, idx)}</div>`;
        })
        .join("");
      return `<div class="terminal-grid__row terminal-grid__row--data" role="row"><div class="terminal-grid__cell terminal-grid__cell--col-first">${escapeHtml(
        rowDef.label
      )}</div>${cells}</div>`;
    })
    .join("");

  const cardsHtml = selected.map((f, idx) => buildCompareFundCard(f, idx, computed, statsFor)).join("");
  tbody.innerHTML = `<div class="compare-matrix-wrap">${matrixHtml}</div><div class="compare-cards-wrap" role="list">${cardsHtml}</div>`;
}

/** Sharpe/Sortino hücre metnini mobil kartta renk sınıfı ile sarar. */
function wrapCompareRatioHtml(html) {
  if (!html || String(html).includes("cell-missing")) return html;
  return `<span class="compare-metric-num">${html}</span>`;
}

/** Mobil: fon karşılaştırma list-kartı (Fon rasyoları ile aynı grid/hiyerarşi). */
function buildCompareFundCard(f, idx, computed, statsFor) {
  if (!f) return "";
  const st = statsFor(f, idx);
  const pr = computed[idx];
  const periodReturnHtml = fmtPercent(numOrNull(pr.periodReturn));
  const volHtml = fmtVolatilityRisk(numOrNull(pr.volatility));
  const sharpeHtml = wrapCompareRatioHtml(formatRatio(numOrNull(st.sharpe)).html);
  const sortHtml = wrapCompareRatioHtml(formatRatio(numOrNull(st.sortino)).html);
  const alphaCell = formatAlphaCell(numOrNull(st.alpha));
  const alphaHtml = alphaCell && typeof alphaCell.html === "string" ? alphaCell.html : '<span class="cell-missing">—</span>';
  const ddHtml = fmtMaxDrawdownRisk(numOrNull(st.max_drawdown));

  return `<article class="compare-card" role="listitem">
    <div class="compare-card__bar">
      <span class="compare-card__code">${escapeHtml(f.kod)}</span>
      <span class="compare-card__badge">${periodReturnHtml}</span>
    </div>
    <div class="compare-card__matrix compare-rasyo-grid">
      <div class="compare-card__slot compare-card__slot--left">
        <span class="compare-card__k">Volatilite</span>
        <div class="compare-card__v">${volHtml}</div>
      </div>
      <div class="compare-card__slot compare-card__slot--right">
        <span class="compare-card__k">Sharpe</span>
        <div class="compare-card__v">${sharpeHtml}</div>
      </div>
      <div class="compare-card__slot compare-card__slot--left">
        <span class="compare-card__k">Sortino</span>
        <div class="compare-card__v">${sortHtml}</div>
      </div>
      <div class="compare-card__slot compare-card__slot--right">
        <span class="compare-card__k">Alpha</span>
        <div class="compare-card__v">${alphaHtml}</div>
      </div>
      <div class="compare-card__slot compare-card__slot--maxdd">
        <span class="compare-card__k">Max DD</span>
        <div class="compare-card__v">${ddHtml}</div>
      </div>
    </div>
  </article>`;
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
    <code>.venv/Scripts/python tefas_scraper.py</code> veya <code>.venv/Scripts/python tefas_scraper.py --manifest-yenile</code><br />
    Sunucu: <code>.venv/Scripts/python -m http.server 8080</code>
  </li>`;
}

function syncNavActive() {
  document.querySelectorAll(".terminal-nav__link").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.route === currentView);
  });
}

function closeMobileNav() {
  const nav = document.querySelector(".terminal-nav");
  const toggle = document.getElementById("navToggle");
  if (nav) nav.classList.remove("is-nav-open");
  if (toggle) toggle.setAttribute("aria-expanded", "false");
  document.body.classList.remove("nav-open");
}

function wireMobileNav() {
  const nav = document.querySelector(".terminal-nav");
  const toggle = document.getElementById("navToggle");
  const backdrop = document.getElementById("navBackdrop");
  if (!nav || !toggle) return;
  toggle.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = !nav.classList.contains("is-nav-open");
    nav.classList.toggle("is-nav-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    document.body.classList.toggle("nav-open", open);
  });
  if (backdrop) {
    backdrop.addEventListener("click", closeMobileNav);
  }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeMobileNav();
  });
  window.addEventListener("resize", () => {
    if (window.innerWidth > 768) closeMobileNav();
    if (chartInstance) chartInstance.resize();
  });
}

function showView(route) {
  closeMobileNav();
  currentView = route;
  syncNavActive();
  document.getElementById("view-dashboard").classList.toggle("hidden", route !== "dashboard");
  document.getElementById("view-analiz").classList.toggle("hidden", route !== "analiz");
  document.getElementById("view-karsilastirma").classList.toggle("hidden", route !== "karsilastirma");
  document.getElementById("view-fon-karsilastirma").classList.toggle("hidden", route !== "fon-karsilastirma");
  const vHisse = document.getElementById("view-fon-hisse-detay");
  if (vHisse) vHisse.classList.toggle("hidden", route !== "fon-hisse-detay");
  const vYildiz = document.getElementById("view-yildiz-fonlar");
  if (vYildiz) vYildiz.classList.toggle("hidden", route !== "yildiz-fonlar");
  if (route === "karsilastirma") {
    renderStatsTable();
  }
  if (route === "fon-karsilastirma") {
    populateCompareSelectors();
    renderMultiCompareTable();
  }
  if (route === "fon-hisse-detay" && typeof window.FonHisseDetay !== "undefined" && window.FonHisseDetay.onRouteEnter) {
    window.FonHisseDetay.onRouteEnter();
  }
  if (route === "yildiz-fonlar") {
    renderYildizFonlar();
  }
  if (route === "analiz" && activeFundMeta && fullSeriesCache) applyPeriodToChart();
}

function updateSpecificPopoversVisibility() {
  document.querySelectorAll(".period-toolbar__specific-popover").forEach((el) => {
    el.hidden = selectedPeriod !== "SPECIFIC";
  });
}

function syncPeriodButtons() {
  document
    .querySelectorAll(
      "#periodToolbarAnaliz .period-btn, #periodToolbarKarsilastirma .period-btn, #periodToolbarFonKarsilastirma .period-btn"
    )
    .forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.period === selectedPeriod);
    });
}

function setPeriod(p) {
  selectedPeriod = String(p || "").trim() || "1Y";
  updateSpecificPopoversVisibility();
  if (selectedPeriod === "SPECIFIC") ensureGlobalSpecificDatesDefault();
  syncPeriodButtons();
  populateCompareSelectors();
  if (currentView === "analiz" && fullSeriesCache) applyPeriodToChart();
  if (currentView === "karsilastirma") {
    renderStatsTable();
  }
  if (currentView === "fon-karsilastirma") {
    renderMultiCompareTable();
  }
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

function pickStarTags(meta, period) {
  const st = (meta.stats && meta.stats[period]) || {};
  const tags = [];
  const alpha = numOrNull(st.alpha);
  const sharpe = numOrNull(st.sharpe);
  const sortino = numOrNull(st.sortino);
  const maxDd = numOrNull(st.max_drawdown);
  if (alpha != null && alpha >= 0.2) tags.push("BIST100'e güçlü alpha");
  else if (alpha != null && alpha > 0) tags.push("BIST100 üstü getiri");
  if (sharpe != null && sharpe >= 0.9) tags.push("Yüksek Sharpe");
  if (sortino != null && sortino >= 1.2) tags.push("Güçlü Sortino");
  if (maxDd != null && maxDd >= -0.2) tags.push("Kontrollü max düşüş");
  if (numOrNull(meta.gun_kapsami) != null && numOrNull(meta.gun_kapsami) >= 1760) tags.push("Uzun track record");
  return tags.slice(0, 3);
}

function scoreStarFund(meta, period) {
  const st = (meta.stats && meta.stats[period]) || {};
  const alpha = numOrNull(st.alpha);
  const sharpe = numOrNull(st.sharpe);
  const sortino = numOrNull(st.sortino);
  const maxDd = numOrNull(st.max_drawdown);
  if (alpha == null || sharpe == null || sortino == null || maxDd == null) return null;
  if (alpha <= 0 || sharpe <= 0) return null;

  const consistencyPeriods = period === "5Y" ? ["1Y", "3Y", "5Y"] : ["1Y", "3Y"];
  let consistency = 0;
  let penalties = 0;
  consistencyPeriods.forEach((p) => {
    const s = (meta.stats && meta.stats[p]) || {};
    const a = numOrNull(s.alpha);
    const sh = numOrNull(s.sharpe);
    if (a != null && a > 0) consistency += 1;
    else penalties += 1;
    if (sh != null && sh > 0) consistency += 0.6;
    else penalties += 0.6;
  });

  const ddPenalty = Math.max(0, Math.abs(maxDd) - 0.2) * 120;
  const score =
    alpha * 230 +
    sharpe * 38 +
    sortino * 22 +
    consistency * 18 -
    penalties * 16 -
    ddPenalty;
  return Number(score.toFixed(2));
}

function buildStarTop(period, topN = 5) {
  if (!manifest || !Array.isArray(manifest.fonlar)) return [];
  const minDays = period === "5Y" ? 1760 : 1095;
  const items = manifest.fonlar
    .filter((f) => {
      const days = numOrNull(f.gun_kapsami);
      const hasStats = Boolean(f.stats && f.stats[period]);
      const isBank = isBankManagedFund(f.ad || "");
      const isIndex = isIndexEquityFund(f.ad || "");
      return hasStats && !isBank && !isIndex && days != null && days >= minDays;
    })
    .map((f) => {
      const score = scoreStarFund(f, period);
      if (score == null) return null;
      return { meta: f, score, tags: pickStarTags(f, period) };
    })
    .filter(Boolean)
    .sort((a, b) => b.score - a.score);
  return items.slice(0, topN);
}

function renderStarList(elId, period) {
  const el = document.getElementById(elId);
  if (!el) return;
  const top = buildStarTop(period, 5);
  if (!top.length) {
    el.innerHTML = '<div class="yildiz-empty">Kriterleri geçen fon bulunamadı. Veri kapsamını kontrol edin.</div>';
    return;
  }
  el.innerHTML = top
    .map((row, idx) => {
      const f = row.meta;
      const title = String(f.ad || f.kod || "");
      const tags = row.tags.length ? row.tags : ["Dönemsel istikrar", "Pozitif alpha"];
      return `<article class="yildiz-item">
        <div class="yildiz-item__head">
          <span class="yildiz-item__kod"><span class="yildiz-item__rank">#${idx + 1}</span> <span class="yildiz-item__code">${escapeHtml(f.kod)}</span></span>
          <span class="yildiz-item__score">Skor: ${row.score.toFixed(1)}</span>
        </div>
        <div class="yildiz-item__ad">${escapeHtml(title)}</div>
        <div class="yildiz-tags">${tags.map((t) => `<span class="yildiz-tag">${escapeHtml(t)}</span>`).join("")}</div>
      </article>`;
    })
    .join("");
}

function renderYildizFonlar() {
  renderStarList("yildiz3yList", "3Y");
  renderStarList("yildiz5yList", "5Y");
}

/** Fon rasyoları tablosu: Sharpe/Sortino — 1.0 üzeri hafif vurgu. */
function formatSharpeSortinoCell(v) {
  if (v == null || !Number.isFinite(v)) return '<span class="cell-missing">—</span>';
  const strong = v >= 1 ? " metric-strong" : "";
  return `<span class="cell-num${strong}">${v.toFixed(3)}</span>`;
}

/** Alpha: pozitif yeşil, negatif kırmızı (BIST100). */
function formatAlphaStatsCell(v) {
  if (v == null || !Number.isFinite(v)) return '<span class="cell-missing">—</span>';
  const pct = (v * 100).toFixed(2);
  const sign = v >= 0 ? "+" : "";
  const cls = v >= 0 ? "metric-alpha-pos" : "metric-alpha-neg";
  return `<span class="${cls}">${sign}${pct}%</span>`;
}

/** Mobil kart rozeti: seçili dönem Alpha (α), kompakt. */
function formatAlphaBadgeHtml(v) {
  if (v == null || !Number.isFinite(v)) {
    return '<span class="ratio-card__pill ratio-card__pill--empty">—</span>';
  }
  const pct = (v * 100).toFixed(1);
  const sign = v >= 0 ? "+" : "";
  const cls = v >= 0 ? "ratio-card__pill--pos" : "ratio-card__pill--neg";
  return `<span class="ratio-card__pill ${cls}">α${sign}${pct}%</span>`;
}

/** Seçilen dönem için anlamlı sıralama: fiyat serisi bu kadar güne kısa olan fonlar tabloda görünmez. */
function minGunKapsamiForRatioPeriod(period, manifestSnapshot) {
  const m = manifestSnapshot || {};
  const hedef5 = numOrNull(m.hedef_gun);
  const min5 = numOrNull(m.beklenen_min_gun);

  if (period === "6M") return 182;
  if (period === "YTD") {
    const refStr = m.guncelleme;
    const ref = refStr ? new Date(refStr) : new Date();
    if (Number.isNaN(ref.getTime())) return 300;
    const start = new Date(ref.getFullYear(), 0, 1);
    const elapsed = Math.floor((ref - start) / 86400000);
    return Math.max(1, elapsed + 1);
  }
  if (period === "1Y") return 350;
  if (period === "3Y") return 365 * 3;
  // Scraped seriler nadiren tam 365*5 güne çıkar (örn. manifest hedef_gun 1825 iken fon max 1823);
  // dahil etmek için manifest'teki beklenen_min_gun kullanılır — hedef idealdir, minimum eşik değildir.
  if (period === "5Y") {
    if (min5 != null && min5 > 0) return Math.round(min5);
    if (hedef5 != null && hedef5 > 0) return Math.round(hedef5);
    return 1760;
  }
  if (period === "SPECIFIC") {
    const r = readGlobalSpecificRangeFromInputs();
    if (!r) return 999999;
    const spanCal = Math.ceil((r.endMs - r.startMs) / 86400000) + 1;
    return Math.max(MIN_OBS_METRICS, Math.min(spanCal * 2, 4000));
  }
  return 0;
}

function fundHasEnoughHistoryForRatioPeriod(f, period, manifestSnapshot) {
  const need = minGunKapsamiForRatioPeriod(period, manifestSnapshot);
  if (need <= 0) return true;
  const days = numOrNull(f.gun_kapsami);
  if (days == null) return false;
  return days >= need;
}

function benchmarkEndIsoYmd(bench, mf) {
  const x = bench?.xu100_tarih;
  if (x && /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(String(x).slice(0, 10))) return String(x).slice(0, 10);
  const g = mf?.guncelleme;
  if (g && String(g).length >= 10) return String(g).slice(0, 10);
  return "";
}

function parseIsoYmdToUtcMs(iso) {
  const parts = String(iso)
    .slice(0, 10)
    .split("-")
    .map((n) => parseInt(n, 10));
  if (parts.length !== 3 || parts.some((p) => Number.isNaN(p))) return NaN;
  return Date.UTC(parts[0], parts[1] - 1, parts[2]);
}

function isoYmdFromUtcMs(ms) {
  const d = new Date(ms);
  return `${String(d.getUTCFullYear()).padStart(4, "0")}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(
    d.getUTCDate(),
  ).padStart(2, "0")}`;
}

/** BIST son tarihine göre tab sekmesi penceresi başı — Python _period_start ile uyumlu. */
function periodStartIsoFromEnd(endIso, period) {
  const ms = parseIsoYmdToUtcMs(endIso);
  if (!Number.isFinite(ms)) return "";
  if (period === "YTD") {
    const d = new Date(ms);
    return `${d.getUTCFullYear()}-01-01`;
  }
  const q = new Date(ms);
  if (period === "6M") q.setUTCMonth(q.getUTCMonth() - 6);
  else if (period === "1Y") q.setUTCFullYear(q.getUTCFullYear() - 1);
  else if (period === "3Y") q.setUTCFullYear(q.getUTCFullYear() - 3);
  else if (period === "5Y") q.setUTCFullYear(q.getUTCFullYear() - 5);
  else q.setUTCFullYear(q.getUTCFullYear() - 5);
  return isoYmdFromUtcMs(q.getTime());
}

/**
 * Tarih, manifest dizisinden onceyse güncel oran yerine ilk bilinen politikayi kullan
 * (5Y penceresi 2021-04 gibi ay_son ilkay 2021-05 ise; yoksa hep %37 yanlis görünür).
 */
function politikOranTcmbBul(changesAsc, ayAylik, isoYmd, yedekPct) {
  let v = policyPctAtOrBeforeAscending(changesAsc, isoYmd);
  if (v == null && Array.isArray(ayAylik) && isoYmd) v = policyPctFromMonthlyAtOrBefore(ayAylik, isoYmd);
  if (v == null && isoYmd) {
    const y = isoYmd.slice(0, 7);
    if (Array.isArray(ayAylik) && ayAylik.length) {
      const firstAy = String(ayAylik[0].ay);
      if (y.length === 7 && y < firstAy) {
        const p0 = Number(ayAylik[0].p);
        if (Number.isFinite(p0)) v = p0;
      }
    }
    if (v == null && changesAsc?.length) {
      const firstT = String(changesAsc[0].t).slice(0, 10);
      if (isoYmd < firstT) {
        const p0 = Number(changesAsc[0].p);
        if (Number.isFinite(p0)) v = p0;
      }
    }
  }
  if (v == null && Number.isFinite(yedekPct)) v = yedekPct;
  return v != null && Number.isFinite(Number(v)) ? Number(v) : null;
}

/** degisim tarihleri artan sirada bekleniyor — son tarih dahil politik oran */
function policyPctAtOrBeforeAscending(changesAsc, isoYmdCut) {
  if (!changesAsc || changesAsc.length === 0 || !isoYmdCut) return null;
  let last = null;
  for (let i = 0; i < changesAsc.length; i += 1) {
    const t = String(changesAsc[i].t).slice(0, 10);
    if (t <= isoYmdCut) last = Number(changesAsc[i].p);
    else break;
  }
  return last != null && Number.isFinite(last) ? last : null;
}

/** politika_faizi_ay_sonu dizisi yyyy-mm ile artan siralı */
function policyPctFromMonthlyAtOrBefore(monthAsc, isoYmd) {
  if (!monthAsc || monthAsc.length === 0 || !isoYmd) return null;
  const cut = isoYmd.slice(0, 7);
  if (cut.length !== 7) return null;
  let best = null;
  for (let i = 0; i < monthAsc.length; i += 1) {
    if (String(monthAsc[i].ay) <= cut) best = Number(monthAsc[i].p);
  }
  return best != null && Number.isFinite(best) ? best : null;
}

function formatRisksizBenchHint(bench, selectedPeriodHint, mf) {
  const periodKey = selectedPeriodHint || "1Y";
  if (!bench || bench.risksiz_faiz_yillik == null) return "";
  const yPct = Number(bench.risksiz_faiz_yillik) * 100;
  const lbl = periodKey === "SPECIFIC" ? getPeriodHintText() : PERIOD_LABELS[periodKey] || periodKey;
  const endIso = benchmarkEndIsoYmd(bench, mf);
  const ch = bench.politika_faizi_degisimleri;
  const ay = bench.politika_faizi_ay_sonu;

  if (bench.risksiz_kaynak === "tcmb_repo_tablosu" || bench.risksiz_kaynak === "tcmb_evds_policy") {
    let basIso = "";
    if (periodKey === "SPECIFIC") {
      const r = readGlobalSpecificRangeFromInputs();
      basIso = r ? r.startIso : "";
    } else {
      basIso = periodStartIsoFromEnd(endIso, periodKey);
    }
    const endForSon =
      periodKey === "SPECIFIC" ? (readGlobalSpecificRangeFromInputs()?.endIso || endIso) : endIso;
    const sonPct = politikOranTcmbBul(ch, ay, endForSon, yPct);
    const basPct = basIso ? politikOranTcmbBul(ch, ay, basIso, yPct) : null;
    if (sonPct == null) return `Risksiz (TCMB, ${lbl}): —`;
    const sonStr = sonPct.toFixed(1);
    if (basPct == null || basIso === "" || Math.abs(basPct - sonPct) < 0.12) {
      return `Risksiz (TCMB, ${lbl}): ~%${sonStr}/yıl`;
    }
    return `Risksiz (TCMB, ${lbl}): baş ~%${basPct.toFixed(1)} · son ~%${sonStr}/yıl`;
  }
  if (!bench.risksiz_kaynak) {
    return `Risksiz: manifest eski — tefas_scraper.py --manifest-yenile`;
  }
  return `Risksiz (sabit): %${yPct.toFixed(0)}/yıl`;
}

function renderStatsTableBodyFromRows(rows) {
  const tbody = document.getElementById("statsTableBody");
  if (!tbody) return;
  tbody.innerHTML = rows
    .map((r) => {
      const sh = formatSharpeSortinoCell(r.sharpe);
      const so = formatSharpeSortinoCell(r.sortino);
      const al = formatAlphaStatsCell(r.alpha);
      const dd = fmtMaxDrawdownRisk(r.max_drawdown);
      const badge = formatAlphaBadgeHtml(r.alpha);
      return `<article class="ratio-card" role="row">
      <div class="ratio-card__bar">
        <span class="ratio-card__code">${escapeHtml(r.kod)}</span>
        <span class="ratio-card__badge">${badge}</span>
      </div>
      <div class="ratio-card__matrix rasyo-grid">
        <div class="ratio-card__slot">
          <span class="ratio-card__k">Sharpe</span>
          <div class="ratio-card__v">${sh}</div>
        </div>
        <div class="ratio-card__slot">
          <span class="ratio-card__k">Sortino</span>
          <div class="ratio-card__v">${so}</div>
        </div>
        <div class="ratio-card__slot">
          <span class="ratio-card__k">Alpha</span>
          <div class="ratio-card__v">${al}</div>
        </div>
        <div class="ratio-card__slot">
          <span class="ratio-card__k">Max DD</span>
          <div class="ratio-card__v">${dd}</div>
        </div>
      </div>
    </article>`;
    })
    .join("");
}

async function renderStatsTable() {
  const tbody = document.getElementById("statsTableBody");
  const hint = document.getElementById("tableBenchmarkHint");
  if (!tbody || !manifest) return;
  const token = ++statsTableRenderToken;

  const b = manifest.benchmarks || {};
  const rf = formatRisksizBenchHint(b, selectedPeriod, manifest);
  const xu = b.xu100_son != null ? ` · ${b.bist100_ticker || "XU100"} son: ${Number(b.xu100_son).toFixed(2)}` : "";
  const us = b.usdtry_son != null ? ` · USD/TRY: ${Number(b.usdtry_son).toFixed(4)}` : "";
  if (hint) {
    hint.textContent = `${rf}${xu}${us}`.trim() || (b.aciklama || "");
  }

  document.querySelectorAll("#statsTableGrid .terminal-grid__cell--sortable").forEach((cell) => {
    cell.classList.toggle("is-sorted", cell.dataset.sort === tableSortKey);
  });

  if (selectedPeriod !== "SPECIFIC") {
    const rows = manifest.fonlar
      .filter((f) => fundHasEnoughHistoryForRatioPeriod(f, selectedPeriod, manifest))
      .map((f) => {
        const st = (f.stats && f.stats[selectedPeriod]) || {};
        return {
          kod: f.kod,
          sharpe: numOrNull(st.sharpe),
          sortino: numOrNull(st.sortino),
          alpha: numOrNull(st.alpha),
          max_drawdown: numOrNull(st.max_drawdown),
        };
      });
    rows.sort(statsTableSortFn);
    if (token !== statsTableRenderToken) return;
    renderStatsTableBodyFromRows(rows);
    return;
  }

  ensureGlobalSpecificDatesDefault();
  const range = readGlobalSpecificRangeFromInputs();
  if (!range) {
    tbody.innerHTML =
      '<div class="ratio-card ratio-card--empty" role="status">Spesifik dönem için başlangıç ve bitiş tarihlerini seçin.</div>';
    return;
  }

  tbody.innerHTML =
    '<div class="ratio-card ratio-card--empty" role="status">Spesifik metrikler hesaplanıyor…</div>';

  const bench = manifest.benchmarks || {};
  const candidates = manifest.fonlar.filter((f) => fundHasEnoughHistoryForRatioPeriod(f, "SPECIFIC", manifest));
  const rows = [];
  for (const f of candidates) {
    if (token !== statsTableRenderToken) return;
    const series = await getFundSeriesByCode(f.kod);
    const st = computeStatsForSpecificWindow(series, bench);
    const hasAny =
      st.sharpe != null || st.sortino != null || st.alpha != null || st.max_drawdown != null;
    if (hasAny) {
      rows.push({
        kod: f.kod,
        sharpe: numOrNull(st.sharpe),
        sortino: numOrNull(st.sortino),
        alpha: numOrNull(st.alpha),
        max_drawdown: numOrNull(st.max_drawdown),
      });
    }
  }
  rows.sort(statsTableSortFn);
  if (token !== statsTableRenderToken) return;
  if (!rows.length) {
    tbody.innerHTML =
      '<div class="ratio-card ratio-card--empty" role="status">Bu aralıkta yeterli gözlem olan fon bulunamadı.</div>';
    return;
  }
  renderStatsTableBodyFromRows(rows);
}

function statsTableSortFn(a, b) {
  if (tableSortKey === "kod") return String(b.kod).localeCompare(String(a.kod));
  const va = a[tableSortKey];
  const vb = b[tableSortKey];
  if (va == null && vb == null) return 0;
  if (va == null) return 1;
  if (vb == null) return -1;
  return vb - va;
}

function wirePeriodToolbars() {
  document
    .querySelectorAll(
      "#periodToolbarAnaliz .period-btn, #periodToolbarKarsilastirma .period-btn, #periodToolbarFonKarsilastirma .period-btn"
    )
    .forEach((btn) => {
      btn.addEventListener("click", () => setPeriod(btn.dataset.period));
    });
}

function wireNav() {
  document.querySelectorAll("[data-route]").forEach((el) => {
    el.addEventListener("click", () => showView(el.dataset.route));
  });
}

function wireTableSort() {
  document.querySelectorAll("#statsTableGrid .terminal-grid__cell--sortable").forEach((cell) => {
    cell.addEventListener("click", () => {
      tableSortKey = cell.dataset.sort || "sharpe";
      renderStatsTable();
    });
  });
}

async function init() {
  manifest = await loadManifest();
  benchmarks = await loadBenchmarks();
  wireMobileNav();
  wireNav();
  wirePeriodToolbars();
  wireTableSort();
  updateSpecificPopoversVisibility();
  syncPeriodButtons();
  showView("dashboard");

  if (!manifest) {
    showManifestError();
    return;
  }
  const fundSearchInput = document.getElementById("fundSearchInput");
  if (fundSearchInput) {
    fundSearchInput.addEventListener("input", (e) => {
      fundSearchQuery = String(e.target.value || "");
      renderFundList();
    });
  }
  const benchmarkSelect = document.getElementById("benchmarkSelect");
  if (benchmarkSelect) {
    benchmarkSelect.addEventListener("change", (e) => {
      selectedBenchmark = String(e.target.value || "none");
      if (currentView === "analiz" && activeFundMeta && fullSeriesCache) applyPeriodToChart();
    });
  }
  document.querySelectorAll(".js-specific-start, .js-specific-end").forEach((el) => {
    el.addEventListener("change", () => {
      const start = document.querySelector(".js-specific-start")?.value || "";
      const end = document.querySelector(".js-specific-end")?.value || "";
      document.querySelectorAll(".js-specific-start").forEach((x) => {
        x.value = start;
      });
      document.querySelectorAll(".js-specific-end").forEach((x) => {
        x.value = end;
      });
      if (selectedPeriod !== "SPECIFIC") return;
      if (currentView === "analiz" && fullSeriesCache) applyPeriodToChart();
      if (currentView === "karsilastirma") renderStatsTable();
      if (currentView === "fon-karsilastirma") renderMultiCompareTable();
    });
  });
  populateCompareSelectors();
  const multiCompareRoot = document.getElementById("multiCompareRoot");
  if (multiCompareRoot) {
    multiCompareRoot.addEventListener("change", (e) => {
      const t = e.target;
      if (t && t.id && String(t.id).startsWith("compareFund")) renderMultiCompareTable();
    });
  }
  renderFundList();
  renderMultiCompareTable();
}

document.addEventListener("DOMContentLoaded", init);
