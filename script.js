/**
 * Sol menü: data/manifest.json (py tefas_scraper.py üretir).
 * Grafik: her fonun data/<KOD>_tefas.json dosyası (HTTP sunucu gerekir).
 */

const CHART_MAX_POINTS = 240;

const NEDEN_TR = {
  bes_yildan_kisa: "5 yıldan kısa geçmiş",
  cekim_basarisiz: "veri çekilemedi",
};

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

function buildSeriesFromBundle(bundle, fallbackName) {
  const rows = Array.isArray(bundle.veri) ? bundle.veri : [];
  const byDay = new Map();

  for (const row of rows) {
    const dt = parseRowDate(row.TARIH ?? row.tarih ?? row.date);
    const price = parseRowPrice(row);
    if (!dt || price == null) continue;
    const key = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
    byDay.set(key, { dt, price, row });
  }

  const sorted = Array.from(byDay.values()).sort((a, b) => a.dt - b.dt);
  if (sorted.length === 0) {
    return null;
  }

  const base = sorted[0].price;
  const labels = [];
  const values = [];
  for (const { dt, price } of sorted) {
    labels.push(formatLabelTr(dt));
    values.push(Number(((price / base) * 100).toFixed(4)));
  }

  const { labels: dl, values: dv } = downsampleSeries(labels, values, CHART_MAX_POINTS);
  const totalReturn = ((values[values.length - 1] - 100) / 100) * 100;

  const unvan = sorted[sorted.length - 1].row.FONUNVAN || sorted[sorted.length - 1].row.fonunvan;
  const displayName =
    (bundle.fon_unvan && String(bundle.fon_unvan).trim()) ||
    (typeof unvan === "string" && unvan.trim()) ||
    fallbackName;

  const bas = bundle.baslangic || "";
  const bit = bundle.bitis || "";
  const rangeLabel = bas && bit ? `${bas} → ${bit}` : "TEFAS verisi";

  const durum = bundle.durum_panel || "tam";
  const nedenKey = bundle.neden;
  const nedenTr = nedenKey ? NEDEN_TR[nedenKey] || nedenKey : "";

  return {
    labels: dl,
    values: dv,
    totalReturn,
    source: "tefas",
    rangeLabel,
    chartTitle: "Baz 100 — pay fiyatı (TEFAS)",
    datasetLabel: "Baz 100 (ilk gün = 100)",
    footReturnSuffix: durum === "tam" ? "(TEFAS, baz 100)" : `(TEFAS — Veri eksik${nedenTr ? `: ${nedenTr}` : ""})`,
    displayName,
    kaynak: bundle.kaynak || "",
    durumPanel: durum,
    nedenTr,
    hasChart: true,
  };
}

function emptySeries(fundMeta, message) {
  return {
    labels: [],
    values: [],
    totalReturn: 0,
    source: "none",
    rangeLabel: "Veri yok",
    chartTitle: "Grafik yok",
    datasetLabel: "",
    footReturnSuffix: "",
    displayName: fundMeta.ad || fundMeta.kod,
    kaynak: "",
    durumPanel: "veri_eksik",
    nedenTr: "",
    hasChart: false,
    placeholderMessage: message || "Bu fon için grafik oluşturulamadı (dosya yok veya boş veri).",
  };
}

async function loadFundBundle(fundMeta) {
  const path = fundMeta.dosya || `data/${fundMeta.kod}_tefas.json`;
  return await fetchJson(path);
}

let chartInstance = null;

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
  const tick = "#8b9cb3";

  chartInstance = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: datasetLabel || "Seri",
          data: values,
          borderColor: "#5ee9b5",
          backgroundColor: "rgba(94, 233, 181, 0.12)",
          borderWidth: 2,
          fill: true,
          tension: 0.25,
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
          backgroundColor: "#1a222d",
          titleColor: "#e8edf4",
          bodyColor: "#b8f5d9",
          borderColor: "rgba(255,255,255,0.1)",
          borderWidth: 1,
          padding: 10,
        },
      },
      scales: {
        x: {
          grid: { color: grid },
          ticks: {
            color: tick,
            maxRotation: 0,
            autoSkip: true,
            maxTicksLimit: 12,
          },
        },
        y: {
          grid: { color: grid },
          ticks: {
            color: tick,
            callback(v) {
              return v.toFixed(0);
            },
          },
        },
      },
    },
  });
}

async function resolveSeries(fundMeta) {
  const bundle = await loadFundBundle(fundMeta);
  if (!bundle) {
    return emptySeries(fundMeta, "JSON dosyası yüklenemedi. Yerel sunucu kullanıyor musunuz? (py -m http.server 8080)");
  }
  const s = buildSeriesFromBundle(bundle, fundMeta.ad || fundMeta.kod);
  if (s) return s;
  return emptySeries(
    fundMeta,
    "Kayıtlarda geçerli fiyat/tarih yok (çekim başarısız veya bozuk dosya)."
  );
}

async function selectFund(fundMeta) {
  document.getElementById("emptyState").classList.add("hidden");
  document.getElementById("panelContent").classList.remove("hidden");

  document.getElementById("fundCodeBadge").textContent = fundMeta.kod;

  const series = await resolveSeries(fundMeta);
  document.getElementById("fundName").textContent = series.displayName;

  let tag = series.rangeLabel;
  if (fundMeta.durum === "veri_eksik") {
    tag = `Veri eksik${series.nedenTr ? ` · ${series.nedenTr}` : ""}`;
  }
  document.getElementById("dataSourceTag").textContent = tag;

  const retEl = document.getElementById("mockReturn");
  if (series.hasChart) {
    const sign = series.totalReturn >= 0 ? "+" : "";
    retEl.textContent = `${sign}${series.totalReturn.toFixed(2)}% ${series.footReturnSuffix}`;
    retEl.classList.remove("positive", "negative");
    retEl.classList.add(series.totalReturn >= 0 ? "positive" : "negative");
  } else {
    retEl.textContent = "—";
    retEl.classList.remove("positive", "negative");
  }

  document.getElementById("chartCardTitle").textContent = series.chartTitle;

  const foot = document.getElementById("panelFootnote");
  if (series.hasChart) {
    const src = series.kaynak ? ` Kaynak: ${series.kaynak}.` : "";
    foot.innerHTML = `Baz 100 serisi, fonun pay birim fiyatının ilk işlem gününe göre endekslenmesidir.${src} Tam liste ve güncelleme: <code>py tefas_scraper.py</code>.`;
  } else {
    foot.innerHTML = `${series.placeholderMessage} <code>data/${fundMeta.kod}_tefas.json</code> dosyasını kontrol edin.`;
  }

  if (series.hasChart && series.labels.length > 0) {
    setChartArea(true);
    document.getElementById("chartPlaceholder").textContent = "";
    renderChart(series.labels, series.values, series.datasetLabel);
  } else {
    if (chartInstance) {
      chartInstance.destroy();
      chartInstance = null;
    }
    setChartArea(false);
    document.getElementById("chartPlaceholder").textContent = series.placeholderMessage;
  }
}

function renderFundList(manifest) {
  const list = document.getElementById("fundList");
  const countEl = document.getElementById("fundCount");
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
        ? `<span class="fund-item__badge" title="${f.neden || ""}">Veri eksik</span>`
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
  const t = String(s ?? "");
  return t
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showManifestError() {
  const list = document.getElementById("fundList");
  const countEl = document.getElementById("fundCount");
  countEl.textContent = "0 fon";
  list.innerHTML = `<li class="fund-list__error">
    <strong>manifest bulunamadı.</strong><br />
    Önce veriyi üretin: <code>py tefas_scraper.py</code><br />
    Paneli tarayıcıda açmak için proje klasöründe: <code>py -m http.server 8080</code> ardından
    <code>http://localhost:8080</code> — <code>file://</code> ile <code>data/manifest.json</code> yüklenemez.
  </li>`;
}

async function init() {
  const manifest = await loadManifest();
  if (!manifest) {
    showManifestError();
    return;
  }
  renderFundList(manifest);
}

document.addEventListener("DOMContentLoaded", init);
