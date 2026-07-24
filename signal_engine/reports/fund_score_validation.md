# Temel skor validation (FAZ5)

- Üretim: `2026-07-21T10:56:11Z`
- `look_ahead_clean`: **True**
- `indicative_only`: **True**
- `sample_adequate`: **False**
- Sembol: 21 · PIT adayı: 0 · kesit: 0
- Eşik: pit≥30, kesit≥4

## Restatement uyarısı

Restatement riski: Finansal kalemler bugünkü Yahoo/finansal tablo snapshot’ından; o dönemde yayınlanan ilk rakam olmayabilir.

## Metrik envanteri

| Metrik | Sınıf |
|--------|-------|
| `al_sayi` | `excluded_live_only` |
| `buy` | `excluded_live_only` |
| `currentPrice` | `excluded_live_only` |
| `currentRatio` | `excluded_live_only` |
| `debtToEquity` | `excluded_live_only` |
| `earningsGrowth` | `excluded_live_only` |
| `ebitda` | `excluded_live_only` |
| `enterpriseToEbitda` | `excluded_live_only` |
| `enterpriseValue` | `excluded_live_only` |
| `fcf_q` | `publish_lag` |
| `fcf_y` | `publish_lag` |
| `financing_y` | `publish_lag` |
| `forwardPE` | `excluded_live_only` |
| `grossMargins` | `excluded_live_only` |
| `hold` | `excluded_live_only` |
| `interestCoverage` | `excluded_live_only` |
| `investing_y` | `publish_lag` |
| `marketCap` | `excluded_live_only` |
| `net_income_q` | `publish_lag` |
| `net_income_y` | `publish_lag` |
| `numberOfAnalystOpinions` | `excluded_live_only` |
| `operatingMargins` | `excluded_live_only` |
| `pegRatio` | `excluded_live_only` |
| `priceToBook` | `excluded_live_only` |
| `priceToSalesTrailing12Months` | `excluded_live_only` |
| `profitMargins` | `excluded_live_only` |
| `profit_margin_y` | `publish_lag` |
| `quickRatio` | `excluded_live_only` |
| `recommendationKey` | `excluded_live_only` |
| `regularMarketPrice` | `excluded_live_only` |
| `returnOnAssets` | `excluded_live_only` |
| `returnOnEquity` | `excluded_live_only` |
| `revenueGrowth` | `excluded_live_only` |
| `revenue_q` | `publish_lag` |
| `revenue_y` | `publish_lag` |
| `revenue_y_prev` | `publish_lag` |
| `sell` | `excluded_live_only` |
| `strongBuy` | `excluded_live_only` |
| `strongSell` | `excluded_live_only` |
| `targetMeanPrice` | `excluded_live_only` |
| `totalCash` | `excluded_live_only` |
| `totalDebt` | `excluded_live_only` |
| `total_assets_q` | `publish_lag` |
| `total_assets_y` | `publish_lag` |
| `total_liab_q` | `publish_lag` |
| `total_liab_y` | `publish_lag` |
| `trailingPE` | `excluded_live_only` |

## Look-ahead teyidi

Backtest skorunda `LIVE_ONLY_FIELDS` (PE, PB, hedef fiyat, analist, Yahoo .info snapshot marj/ROE/oran) **okunmaz**. Live sızıntı sayısı: **0**.

## Publish-lag

- Çeyrek: +45 gün
- Yıllık: +90 gün
- Örnek available_asof(2024-12-31, annual): `2025-03-31`

## Getiri kovaları

Tarihsel PIT fiyat hizası bu koşuda boş bırakıldı (indicative). SAĞLAM/GÜÇLÜ vs RİSKLİ ve AZALT∩SAĞLAM vs AZALT∩RİSKLİ karşılaştırması PIT arşivi bağlandığında doldurulacak.

_Ağırlıklar %30/25/25/20 geçmesi optimal değil; yalnızca 'felaket değil' kapısı._

## Notlar

- Tarihsel point-in-time filing arşivi yok; mevcut cache snapshot restatement riski taşır.
- Bu nedenle indicative_only=true — FUND_SCORE_UI prod’da açılmaz.
- Backtest modunda skor üretilebilen sembol (snapshot): 11.
- Publish-lag (+45ç / +90y) ve live-only dışlama kodda zorunlu.

## Gate

`FUND_SCORE_UI` açılmaz çünkü `indicative_only=true` (ve/veya örneklem / look_ahead). Debug: `FUND_SCORE_UI_FORCE=1`.

