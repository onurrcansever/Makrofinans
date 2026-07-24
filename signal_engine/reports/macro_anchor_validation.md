# Makro Çıpa Doğrulaması

- Üretim: 2026-07-24T08:53:02+00:00
- Pencere: 2021-07-31 → 2026-07-31 (61 ay)
- CPI kaynağı: TÜİK/EVDS (TP.FG.J01, doğrudan çekim)

## Karar / Kanıt Özeti
- A: İlişki zayıf (ρ=-0.038) — tek başına çıpa stresi güçlü öngörücü değil.
- A: Stres → 3a USD/TL ρ=0.247 (TL değer kaybını öngörüyor).
- A: Düşük-stres aylar ort. BIST(USD) 3a %+3.8 vs yüksek-stres %+5.0 — fark kovadan görülür.
- B: Reel getiri BASİT formülle Fisher-tam'dan ort. 3.04 pp iyimser okunuyor — yüksek enflasyonda `(1+i)/(1+π)−1` kullanılmalı (kalibrasyon gerekçesi).
- B: Petrol→TÜFE gecikme korelasyonu {'lag_0a': 0.555, 'lag_3a': 0.648, 'lag_6a': 0.532} — artan lag'de yükseliyorsa petrol öncü göstergedir.
- C: Fisher geçişi rejim reel kovasını 1/10 ayda değiştiriyor; TL_FIRSAT (reel>0) kapısı 0 ayda flip eder (işaret-değişmez → beklenen 0). Etki büyüklük eşiklerinde, sınırlı ve öngörülebilir.

## A) Öngörücü Değer — Çıpa Stresi → İleri Getiri
| İlişki | Spearman ρ |
|---|---|
| stres_vs_bist_usd_ileri_1a | 0.107 |
| stres_vs_bist_usd_ileri_3a | -0.038 |
| stres_vs_usdtry_ileri_3a | 0.247 |

| Kova | n | BIST(USD) ileri 3a ort % | USD/TL ileri 3a ort % |
|---|---|---|---|
| düşük stres | 19 | +3.77 | +9.38 |
| orta stres | 19 | +7.02 | +4.98 |
| yüksek stres | 20 | +5.05 | +9.95 |

Veri-güdümlü stres kesimleri: q33=-0.29, q66=0.235

## B) Reel Getiri Okuması
- Motor reel=tcmb−enflasyon (basit). Yüksek enflasyonda Fisher-tam üstünde kalır.
- Ort. mutlak sapma: **3.04 pp**, max: 8.82 pp

| Ay | TCMB | Enflasyon | Basit reel pp | Fisher-tam pp | Sapma pp |
|---|---|---|---|---|---|
| 2024-01 | 42.5 | 64.9 | -22.40 | -13.58 | -8.82 |
| 2024-04 | 50.0 | 69.8 | -19.80 | -11.66 | -8.14 |
| 2024-07 | 50.0 | 61.8 | -11.80 | -7.29 | -4.51 |
| 2024-10 | 50.0 | 48.6 | +1.40 | +0.94 | +0.46 |
| 2025-01 | 47.5 | 42.1 | +5.40 | +3.80 | +1.60 |
| 2025-04 | 46.0 | 38.0 | +8.00 | +5.80 | +2.20 |
| 2025-07 | 43.0 | 36.0 | +7.00 | +5.15 | +1.85 |
| 2025-10 | 40.5 | 35.0 | +5.50 | +4.07 | +1.43 |
| 2026-01 | 38.0 | 34.5 | +3.50 | +2.60 | +0.90 |
| 2026-04 | 37.0 | 35.0 | +2.00 | +1.48 | +0.52 |

- Petrol→TÜFE gecikme (Spearman): {'lag_0a': 0.555, 'lag_3a': 0.648, 'lag_6a': 0.532}

## C) Fisher Geçişinin Rejim Kararlarına Etkisi
- Rejim skoru reel kova katkısı: basit vs Fisher (regime_hysteresis kuralı).
- Reel kova değişen ay: **1/10**; TL_FIRSAT (reel>0) kapısı flip: **0** (işaret-değişmez → 0 beklenir)

| Ay | Basit reel pp | Fisher reel pp | Basit kova | Fisher kova | Skor Δ |
|---|---|---|---|---|---|
| 2024-01 | -22.40 | -13.58 | -20 | -20 | +0 |
| 2024-04 | -19.80 | -11.66 | -20 | -20 | +0 |
| 2024-07 | -11.80 | -7.29 | -20 | -20 | +0 |
| 2024-10 | +1.40 | +0.94 | +12 | +12 | +0 |
| 2025-01 | +5.40 | +3.80 | +25 | +25 | +0 |
| 2025-04 | +8.00 | +5.80 | +25 | +25 | +0 |
| 2025-07 | +7.00 | +5.15 | +25 | +25 | +0 |
| 2025-10 | +5.50 | +4.07 | +25 | +25 | +0 |
| 2026-01 | +3.50 | +2.60 | +25 | +12 | -13 |
| 2026-04 | +2.00 | +1.48 | +12 | +12 | +0 |

## Notlar
- Eşikler veri kantillerinden (33/66) türetildi — elle/sezgiyle konmadı.
- Lookahead yok: t'deki çıpa → t+1/t+3 getiri.
- CDS/enflasyon yaklaşık; kesin performans değil, yön/kalibrasyon kanıtı.
