# README_SIGNALS.md — Signal Engine v2

Tek kaynak: `signal_engine/config/signal_config.yaml`

## Faktörler (0–100, ağırlıklı birleşim)

| Faktör | Ağırlık | Formül özeti |
|--------|---------|--------------|
| **Trend** | 22% | SMA50/200 yapısı, SMA50 eğimi, 12-1 ay momentum |
| **Mean-reversion** | 18% | RSI(14) günlük, Bollinger %B(20,2), 52H drawdown |
| **Volatility** | 18% | 30g/90g yıllık vol, max drawdown, vol spike cezası |
| **Relative strength** | 22% | 3M/6M getiri − benchmark (XU100 / ^GSPC / ^IXIC) |
| **Liquidity** | 20% | Hacim oranı + ETF AUM/TER (`etf_quality.yaml`) |

Eksik faktör → ağırlıklar **yeniden normalize** edilir. UI: `Veri: 8/10`.

## Skor

```
skor = Σ (faktör_i × ağırlık_i) / Σ ağırlık_mevcut
percentile = sınıf içi sıra (etf_broad | etf_other | bist | global_stock)
```

## Rejim

| Rejim | Koşul | Giriş mantığı |
|-------|-------|---------------|
| TRENDING_UP | fiyat > SMA50 > SMA200 | SMA20/50 veya ~%5 sığ geri çekilme |
| TRENDING_DOWN | fiyat < SMA50 < SMA200 | 52H × 0.88 derin değer bandı |
| HIGH_VOL | vol30 yüksek / spike | Contingency seviyeleri |
| RANGE_BOUND | diğer | SMA50 veya −%5 |

**TRENDING_UP + derin −25% hedef birlikte gösterilmez.**

## Karar etiketleri

| Etiket | Skor eşiği | Hysteresis |
|--------|------------|------------|
| GÜÇLÜ AL | ≥ 82 | −3 puan |
| AL | ≥ 72 | −3 |
| İZLE | ≥ 58 | −3 |
| BEKLE | ≥ 45 | — |
| AZALT | < 45 | — |

## Alım seviyesi

- **Yöntem** UI'da `Al` sütununda: örn. `SMA50 pullback`, `%5 geri çekilme`
- **P(doldur,90g)**: son ~5y günlük veride 90 gün içinde hedefe dokunma oranı
- P < 20% → DCA önerisi (beklemek tarihte zayıf)

## Veri

- Canlı tarama: **2y** günlük, `auto_adjust=True` (Yahoo)
- **LSE GBX (pence):** EQQQ.L, EMIM.L vb. → `/100` → GBP; CSPX.L/VUAA.L USD kalır (`listing_currency.yaml`)
- Anormal fiyat (200g medyanın 5× üstü) → **VERİ HATASI**, skor dışı
- Benchmark: config `benchmarks` bölümü
- Feature flag: `USE_SIGNAL_ENGINE_V2=1` veya sidebar

## Backtest

```bash
python3 -m pytest tests/test_signal_engine.py -q
python3 scripts/generate_signal_backtest_report.py
```

Rapor: `signal_engine/reports/signal_backtest_report.json` + `.md`  
CI: config hash değişince raporu yeniden üretin.

Lookahead testi: `assert_no_lookahead()` — gelecek fiyat enjekte edilince skor değişmeli.

## UI

- **90g** sütunu: son ~90 günde haftalık bileşik skor sparkline
- **Neden?** expander: faktör detayları, rejim, giriş, ETF kalite
- **Backtest** sekmesi: 5Y walk-forward özeti

## Uyarı

Bu bir **tarama aracıdır**, yatırım tavsiyesi değildir. Backtest geçmiş performansı garanti etmez.
