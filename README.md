# TEFAS Terminal

Hisse senedi yoğun fonlar için yerel bir “terminal” arayüzü: getiri eğrileri, risk metrikleri, karşılaştırma ve KAP’tan okunan **gerçek hisse ağırlıkları**. Veriler `data/` altındaki JSON dosyalarından beslenir.

## Son durum (özet)

- **Arayüz:** `index.html` + `script.js` + `style.css`; fon bazlı hisse dağılımı `fon_hisse_detay.js`.
- **TEFAS getiri / istatistik:** `tefas_scraper.py` → `data/<KOD>_tefas.json`, `data/manifest.json`, `data/benchmarks.json` (Playwright + stealth; TEFAS Next.js API). **Sharpe/Sortino risksiz bacak (`--risk-free-model otomatik`, varsayılan):** Anahtarsız **`tcmb.gov.tr` kamuya açık 1 haftalık repo HTML tablosu**; okunamazsa `--risksiz-faiz` sabiti (varsayılan 0.45). Arayüz yalnızca son `manifest.json`’u okur — `Ctrl+F5` scrape tetiklemez.
- **KAP portföy dağılımı (PDR):** `fon_hisse_scraper.py` → `data/fon_hisse_birlesik.json` ve `data/<KOD>_hisse_pdr.json`. Metin içermeyen (taranmış) PDF’lerde **OCR** kullanılır; bu fonlar birleşik veride `kaynak_pdr_ocr: true` ile işaretlenir, **Fon Hisse Detay** sayfasında uyarı gösterilir.
- **Otomasyon:** GitHub Actions **hafta içi** (Pzt–Cu) **TR saati ~12:00**’de tam tarama yapar (`data/` commit). Hafta sonu job yok — borsa kapalı olduğundan günlük NAV genelde güncellenmez. İsteğe bağlı **`workflow_dispatch`** ile `manifest-only` çalıştırılabilir (mevcut JSON + politik/benchmark ile manifest/rasyolar, TEFAS taraması yok). Ayrıntı: `.github/workflows/tefas-daily-scrape.yml`.

## Kurulum (yerel)

```text
cd TEFAS
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m playwright install chromium
```

Tarayıcıdan açmak için proje kökünde statik sunucu:

```text
.\.venv\Scripts\python -m http.server 8080
```

Adres: `http://127.0.0.1:8080/`

## Sık kullanılan komutlar

| Ne | Komut |
|----|--------|
| Tüm HSYF getiri + manifest | `.\.venv\Scripts\python tefas_scraper.py` |
| Tek fon (örnek) | `.\.venv\Scripts\python tefas_scraper.py MAC --gun 365` |
| KAP hisse çekimi (örnek) | `.\.venv\Scripts\python fon_hisse_scraper.py AAV` |
| Tüm manifest fonları (KAP) | `.\.venv\Scripts\python fon_hisse_scraper.py --tum-manifest` |

## Senden beklenen (varsa)

| Durum | Ne yapmalısın |
|--------|----------------|
| Güncel veri | Genelde **hiçbir şey**; GitHub günlük job’u `data/`’ı günceller. Yerelde çalışıyorsan `git pull` yeterli. |
| Risksiz oran kaynağı (CI/yerel) | Varsayılan `otomatik` = **tcmb.gov.tr repo tablosu**; bazen **`--risk-free-model sabit`** veya **`tcmb-policy`** (tablo şart). |
| Sharpe / manifest yenileme (yerel) | Örnek: `python tefas_scraper.py --manifest-yenile` veya tam tarama `python tefas_scraper.py`. |
| Hemen tazele | Depoda **Actions → TEFAS günlük veri → Run workflow** veya yerelde `tefas_scraper.py` çalıştır. |
| Hisse listesini yenile | `fon_hisse_scraper.py` (KAP rate limit nedeniyle fonlar arasında bekleme önerilir; `--delay 2`). |
| Actions çalışmıyor | Repo **Settings → Actions** açık mı, `main` koruması bot push’u engelliyor mu kontrol et. |

## Dosya ipuçları

- `data/manifest.json` — fon listesi ve özet istatistikler (dashboard tabloları).
- `data/fon_hisse_birlesik.json` — birleşik hisse ağırlıkları (KAP PDR).
- `data/_known_tickers.txt` — OCR/yardımcı doğrulama için bilinen kod listesi (geliştirici).
