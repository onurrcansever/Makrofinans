# Decision Synth A/B Report

Generated: `2026-07-21T11:34:56.157262+00:00`
Lookahead OK: **True**
Fund mode: `price_only_NÖTR` · step=5

## Güven notu

Örneklem: base_AL=91, synth_AL=91, upgrade=0, downgrade=0. Synth 1M ort (0.5%) base'e yakın/üstün (0.5%) — sentez 'felaket değil' kapısından geçti (fiyat-only).

## Notlar

- Price-only A/B: fund_label=NÖTR sabit; peer/fund_gate yok.
- Base = decide() (cold start, percentile=50). Synth = synthesize_action(+Ichimoku+spot).
- Örneklem adımı: her 5 işlem günü.
- Sentez upgrade: base İZLE/BEKLE iken synth AL (bölge+temel≥SAĞLAM gerekir).
- Sentez downgrade: base AL iken synth İZLE (uzak giriş vb.).
- fund_label=NÖTR iken upgrade beklenmez; SAĞLAM ile bölge teşviki test edilir.

## Aggregate

| Kol | n | 1M ort | 3M ort | 6M ort | Hit 1M |
|-----|---|--------|--------|--------|--------|
| base | 91 | 0.5% | 2.3% | 12.6% | 23.1% |
| synth | 91 | 0.5% | 2.3% | 12.6% | 23.1% |
| both_buy | 91 | 0.5% | 2.3% | 12.6% | 23.1% |
| synth_upgrade | 0 | — | — | — | — |
| synth_downgrade | 0 | — | — | — | — |

## Sembol

| Sembol | base_AL | synth_AL | upgrade | downgrade | base 1M | synth 1M |
|--------|---------|----------|---------|-----------|---------|----------|
| AAPL | 15 | 15 | 0 | 0 | -3.8% | -3.8% |
| MSFT | 17 | 17 | 0 | 0 | -0.0% | -0.0% |
| CSCO | 17 | 17 | 0 | 0 | -0.6% | -0.6% |
| AMAT | 21 | 21 | 0 | 0 | 6.9% | 6.9% |
| KO | 21 | 21 | 0 | 0 | -1.7% | -1.7% |

## Nasıl okunur

- **base**: eski `decide()` AL/GÜÇLÜ AL sonrası getiri
- **synth**: birleşik `synthesize_action` AL sonrası getiri
- **upgrade**: sentezin yeni açtığı AL’ler (geç kalmama teşviki)
- **downgrade**: sentezin kestiği AL’ler (uzak giriş vb.)

Bu rapor temel skoru dahil etmez (price-only). Güven 9/10 için PIT temel + daha büyük örneklem gerekir.
