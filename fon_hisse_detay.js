/**
 * Fon Hisse Detay — izole modül (fhd- namespace).
 * Veri: data/fon_hisse_birlesik.json (tercih) veya data/fon_hisse_portfoy.json
 */
(function () {
  const TOP_N = 10;
  const CHART_MAX_SLICES = 10;

  const DONUT_COLORS = [
    "rgba(99, 179, 142, 0.88)",
    "rgba(86, 156, 214, 0.88)",
    "rgba(206, 145, 120, 0.88)",
    "rgba(180, 140, 220, 0.88)",
    "rgba(120, 190, 200, 0.88)",
    "rgba(220, 180, 90, 0.88)",
    "rgba(240, 120, 140, 0.75)",
    "rgba(140, 200, 160, 0.85)",
    "rgba(160, 160, 220, 0.8)",
    "rgba(200, 200, 120, 0.8)",
    "rgba(120, 120, 140, 0.65)",
  ];

  let fhdChart = null;
  let fhdData = null;
  let fhdManifestFunds = [];
  let fhdLoaded = false;

  async function fhdFetchJson(url) {
    try {
      const r = await fetch(url, { cache: "no-store" });
      if (!r.ok) return null;
      return await r.json();
    } catch {
      return null;
    }
  }

  async function fhdLoadManifestFunds() {
    const m = await fhdFetchJson("data/manifest.json");
    if (!m || !Array.isArray(m.fonlar)) return [];
    return [...m.fonlar].sort((a, b) => String(a.kod).localeCompare(String(b.kod)));
  }

  async function fhdLoadPortfolioBundle() {
    let b = await fhdFetchJson("data/fon_hisse_birlesik.json");
    if (!b || typeof b.fonlar !== "object") {
      b = await fhdFetchJson("data/fon_hisse_portfoy.json");
    }
    return b && typeof b.fonlar === "object" ? b : null;
  }

  function fhdDestroyChart() {
    if (fhdChart) {
      fhdChart.destroy();
      fhdChart = null;
    }
  }

  function fhdNormalizeRows(fonBlock) {
    const hisseler = Array.isArray(fonBlock.hisseler) ? fonBlock.hisseler : [];
    if (hisseler.length > 0) {
      return hisseler
        .map((h) => ({
          key: String(h.ticker || h.kod || "").trim().toUpperCase(),
          label: String(h.ticker || h.kod || "—").trim().toUpperCase(),
          sub: (h.ad || "").trim(),
          pct: Number(h.agirlik),
          isHisse: true,
        }))
        .filter((r) => r.key && Number.isFinite(r.pct) && r.pct > 0)
        .sort((a, b) => b.pct - a.pct);
    }
    const vd = Array.isArray(fonBlock.varlik_dagilimi) ? fonBlock.varlik_dagilimi : [];
    return vd
      .map((v) => ({
        key: String(v.tip || "").trim(),
        label: String(v.tip || "—").trim(),
        sub: "Varlık sınıfı (TEFAS)",
        pct: Number(v.oran),
        isHisse: false,
      }))
      .filter((r) => r.key && Number.isFinite(r.pct) && r.pct > 0)
      .sort((a, b) => b.pct - a.pct);
  }

  function fhdBuildChartSlices(rows) {
    if (!rows.length) return { labels: [], data: [], colors: [] };
    const top = rows.slice(0, CHART_MAX_SLICES - 1);
    const rest = rows.slice(CHART_MAX_SLICES - 1);
    const restSum = rest.reduce((s, r) => s + r.pct, 0);
    const labels = top.map((r) => r.label);
    const data = top.map((r) => r.pct);
    const colors = top.map((_, i) => DONUT_COLORS[i % DONUT_COLORS.length]);
    if (restSum > 0.01) {
      labels.push("Diğer");
      data.push(Number(restSum.toFixed(2)));
      colors.push(DONUT_COLORS[DONUT_COLORS.length - 1]);
    }
    return { labels, data, colors };
  }

  function fhdRenderChart(canvas, rows) {
    fhdDestroyChart();
    if (!canvas || typeof Chart === "undefined") return;
    const { labels, data, colors } = fhdBuildChartSlices(rows);
    if (!data.length) return;

    fhdChart = new Chart(canvas, {
      type: "doughnut",
      data: {
        labels,
        datasets: [
          {
            data,
            backgroundColor: colors,
            borderColor: "rgba(10, 14, 20, 0.95)",
            borderWidth: 2,
            hoverOffset: 6,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        cutout: "58%",
        plugins: {
          legend: {
            display: false,
          },
          tooltip: {
            callbacks: {
              label(ctx) {
                const v = ctx.raw;
                return ` ${ctx.label}: %${Number(v).toFixed(2)}`;
              },
            },
          },
        },
      },
    });
  }

  function fhdRenderBars(container, rows) {
    if (!container) return;
    if (!rows.length) {
      container.innerHTML = '<div class="fhd-empty">Gösterilecek dağılım yok.</div>';
      return;
    }
    const maxPct = rows[0] ? rows[0].pct : 1;
    container.innerHTML = rows
      .map((r, idx) => {
        const top = idx < TOP_N;
        const w = maxPct > 0 ? Math.min(100, (r.pct / maxPct) * 100) : 0;
        const pctStr = `%${r.pct.toFixed(1)}`;
        const cls = top ? "fhd-bar-row fhd-bar-row--top" : "fhd-bar-row";
        const badge = top ? '<span class="fhd-badge">Top</span>' : "";
        return `<div class="${cls}" data-fhd-rank="${idx + 1}">
          <div class="fhd-bar-row__label">
            <span class="fhd-bar-row__ticker">${escapeHtml(r.label)} <span class="fhd-pct">${escapeHtml(
          pctStr
        )}</span>${badge}</span>
            <span class="fhd-bar-row__sub">${escapeHtml(r.sub || "")}</span>
          </div>
          <div class="fhd-bar-track"><div class="fhd-bar-fill" style="width:${w}%"></div></div>
        </div>`;
      })
      .join("");
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fhdFillSelect(selectEl) {
    if (!selectEl) return;
    const opts = ['<option value="">Fon seçin…</option>'];
    for (const f of fhdManifestFunds) {
      const kod = String(f.kod || "").trim();
      if (!kod) continue;
      const ad = (f.ad || "").trim();
      opts.push(`<option value="${escapeHtml(kod)}">${escapeHtml(kod)}${ad ? " — " + escapeHtml(ad.slice(0, 52)) : ""}</option>`);
    }
    selectEl.innerHTML = opts.join("");
  }

  function fhdRenderForKod(kod) {
    const canvas = document.getElementById("fhdDonutCanvas");
    const bars = document.getElementById("fhdBars");
    const caption = document.getElementById("fhdChartCaption");
    const note = document.getElementById("fhdVarlikNote");
    const metaEl = document.getElementById("fhdFundMeta");
    const ocrBanner = document.getElementById("fhdOcrBanner");

    if (!fhdData || !fhdData.fonlar) {
      if (bars) bars.innerHTML = '<div class="fhd-empty">Veri yüklenemedi.</div>';
      if (ocrBanner) {
        ocrBanner.hidden = true;
        ocrBanner.textContent = "";
      }
      return;
    }

    const block = fhdData.fonlar[kod];
    if (!block) {
      if (bars) {
        bars.innerHTML =
          '<div class="fhd-empty">Bu fon için kayıt yok. <code>fon_hisse_portfoy.json</code> veya <code>.venv/Scripts/python fon_hisse_scraper.py ' +
          escapeHtml(kod) +
          "</code> ile ekleyin.</div>";
      }
      fhdDestroyChart();
      if (caption) caption.textContent = "";
      if (note) note.textContent = "";
      if (metaEl) metaEl.textContent = "";
      if (ocrBanner) {
        ocrBanner.hidden = true;
        ocrBanner.textContent = "";
      }
      return;
    }

    if (ocrBanner) {
      if (block.kaynak_pdr_ocr === true) {
        ocrBanner.hidden = false;
        ocrBanner.innerHTML =
          "<strong>OCR ile okunan PDR.</strong> Bu fonun KAP portföy dağılım raporu PDF’i taramalı (görüntü) olduğu için hisse ağırlıkları optik karakter tanıma ile çıkarıldı. Okuma hataları veya eksik satırlar olabilir; oranlar yaklaşıktır.";
      } else {
        ocrBanner.hidden = true;
        ocrBanner.textContent = "";
      }
    }

    const rows = fhdNormalizeRows(block);
    const hisseli = rows.length > 0 && rows[0].isHisse;

    if (metaEl) {
      const parts = [];
      if (block.unvan) parts.push(block.unvan);
      if (block.guncelleme) parts.push(`Güncelleme: ${block.guncelleme}`);
      if (block.kaynak_tefas === false) parts.push("TEFAS canlı çekim başarısız (önbellek / manuel).");
      metaEl.textContent = parts.join(" · ");
    }

    if (note) {
      note.textContent = hisseli
        ? `En yüksek ağırlıklı ilk ${TOP_N} kısım vurgulandı.`
        : "TEFAS’ta bu fon için pay bazlı liste yok; grafik varlık sınıfı dağılımını gösterir. Hisse detayı için manuel JSON kullanın.";
    }

    if (caption) {
      caption.textContent = hisseli ? "Hisse dağılımı (manuel / birleşik)" : "Varlık sınıfı (TEFAS)";
    }

    fhdRenderChart(canvas, rows);
    fhdRenderBars(bars, rows);
  }

  async function fhdEnsureLoaded() {
    if (fhdLoaded) return;
    const selectEl = document.getElementById("fhdFundSelect");
    const btn = document.getElementById("fhdRefreshBtn");

    fhdManifestFunds = await fhdLoadManifestFunds();
    fhdFillSelect(selectEl);

    if (btn) btn.disabled = true;
    fhdData = await fhdLoadPortfolioBundle();
    if (btn) btn.disabled = false;
    fhdLoaded = true;

    if (!fhdData) {
      const bars = document.getElementById("fhdBars");
      if (bars) {
        bars.innerHTML =
          '<div class="fhd-empty">Henüz veri yok. Örnek: <code>.venv/Scripts/python fon_hisse_scraper.py IDH AAV</code></div>';
      }
      return;
    }

    const params = new URLSearchParams(window.location.search);
    let initial = (params.get("fhd") || "").trim().toUpperCase();
    if (initial && fhdData.fonlar && !fhdData.fonlar[initial]) initial = "";
    if (!initial && fhdData.fonlar) {
      const keys = new Set(Object.keys(fhdData.fonlar));
      const hit = fhdManifestFunds.map((f) => String(f.kod || "").trim().toUpperCase()).find((k) => k && keys.has(k));
      initial = hit || [...keys].sort()[0] || "";
    }
    if (selectEl) selectEl.value = initial || "";

    if (initial) fhdRenderForKod(initial);
  }

  function fhdOnRouteEnter() {
    fhdEnsureLoaded().then(() => {
      if (fhdChart) fhdChart.resize();
    });
  }

  function fhdWire() {
    const selectEl = document.getElementById("fhdFundSelect");
    const btn = document.getElementById("fhdRefreshBtn");

    if (selectEl) {
      selectEl.addEventListener("change", () => {
        const v = String(selectEl.value || "").trim().toUpperCase();
        if (v) fhdRenderForKod(v);
      });
    }

    if (btn) {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        fhdLoaded = false;
        fhdData = null;
        await fhdEnsureLoaded();
        const v = String(selectEl?.value || "").trim().toUpperCase();
        if (v) fhdRenderForKod(v);
        btn.disabled = false;
      });
    }

    window.addEventListener("resize", () => {
      if (fhdChart) fhdChart.resize();
    });
  }

  window.FonHisseDetay = {
    onRouteEnter: fhdOnRouteEnter,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", fhdWire);
  } else {
    fhdWire();
  }
})();
