# Gizli kapı envanteri — FX / getiri / skor sessiz fallback
# Üretim: 2026-07-16 · filtre iddiası için kapanış listesi maddesi 1

Severity: CRITICAL = yanlış karar/gösterim sessiz | WARN = None/boş | OK = raise veya bilinçli

## A. Kapatılan kapılar (bu tur)

| Kapı | Önce | Sonra |
|------|------|-------|
| `getiri_kur_ayarli` FX uçları yok | native | `FxUnavailableError` |
| `getiri_kur_ayarli` gun≤0 cross | native | `FxUnavailableError` |
| `getiri_kur_ayarli_ybb` empty EUR cross | native | raise |
| `benchmark_close_in_settlement` FX yok | unconverted bench (yanlış α) | raise → RS `available=False` |
| `historical_p_fill` → DCA/karar | AL→İZLE kapısı | koparıldı |
| Live quote FX fail (`stock_scanner`) | pass | bar settlement fiyatı korunur (yanlış PB live yazılmaz) |

Testler: `tests/test_getiri_no_native_fallback.py`, `tests/test_score_determinism.py`, `tests/test_degeneracy.py`

## B. Bilinçli OK dallar

| Yer | Davranış |
|-----|----------|
| `getiri_kur_ayarli` asset==display | native — doğru |
| `app._hisse_tablo_getiri` FxUnavailable | `None` (hücre boş; native değil) |
| `favoriler._guvenli_tablo_getiri` | `None` — native değil ama hatayı gizler (**WARN**) |

## C. Açık CRITICAL (filtre dışı / portföy — sonraki tur)

| # | Yer | Sorun |
|---|-----|-------|
| 1 | `fiyat_para.kur_al` / `varlik_fiyat` / `birlesik_oneri` | `eur_try or 35.0`, `*1.08` uydurma kur |
| 2 | `fiyat_para._fx_endpoints` legacy (bar_dates=None yolu) | `usd = eur*1.08` — getiri artık bar_dates zorunlu; ölü yol |
| 3 | `fiyat_para.pb_cevir` / `_pb_tl_katsayi` unknown pb | identity / 1.0 |
| 4 | `varlik_fiyat` LSE×USDTRY (GBP→USD karışımı) | portföy değerleme |
| 5 | `tefas_skor` `g1 or f.getiri_1a` | FX yoksa native skora |
| 6 | `tefas_skor` tüm fonlar `asset_pb=TL` | USD/EUR fon yanlış FX |
| 7 | `quote_normalize` unknown CCY bridge | amount unchanged |
| 8 | `favoriler` endeks `_yf_getiri` | native %, FX yok |

## D. WARN (bilinçli degrade)

| Yer | Davranış |
|-----|----------|
| `favoriler_ui` except Exception → None | boş hücre |
| `fx_serileri_yukle` except → empty | downstream raise |
| `bars._extract_close` except → empty | VERI_YOK |

## E. Kural

Yeni cross-currency native `return round(float(r_native…))` eklemek yasak.
`tests/test_getiri_no_native_fallback.py::test_branches_inventory_documented` dal sayısını sabitler.
