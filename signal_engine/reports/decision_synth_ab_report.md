# Decision Synth A/B — özet

Generated: `2026-07-21T11:35:02.239160+00:00`
Lookahead OK: **True** · step=5

İki senaryo: sabit `fund_label` (temel skor PIT yok — hassasiyet analizi).

## Senaryo fund_label=NÖTR

Örneklem: base_AL=91, synth_AL=91, upgrade=0, downgrade=0. Synth 1M ort (0.5%) base'e yakın/üstün (0.5%) — sentez 'felaket değil' kapısından geçti (fiyat-only).

- base_AL=91 · synth_AL=91 · upgrade=0 · downgrade=0

| Kol | n | 1M | 3M | Hit1M |
|-----|---|----|----|-------|
| base | 91 | 0.5% | 2.3% | 23% |
| synth | 91 | 0.5% | 2.3% | 23% |
| both_buy | 91 | 0.5% | 2.3% | 23% |
| synth_upgrade | 0 | — | — | — |
| synth_downgrade | 0 | — | — | — |

## Senaryo fund_label=SAĞLAM

Örneklem: base_AL=91, synth_AL=429, upgrade=338, downgrade=0. Synth 1M ort (1.0%) base'e yakın/üstün (0.5%) — sentez 'felaket değil' kapısından geçti (fiyat-only). Upgrade kolları 1M pozitif (1.1%, n=338) — bölge teşviki en azından yıkıcı görünmüyor.

- base_AL=91 · synth_AL=429 · upgrade=338 · downgrade=0

| Kol | n | 1M | 3M | Hit1M |
|-----|---|----|----|-------|
| base | 91 | 0.5% | 2.3% | 23% |
| synth | 429 | 1.0% | 3.4% | 84% |
| both_buy | 91 | 0.5% | 2.3% | 23% |
| synth_upgrade | 338 | 1.1% | 3.7% | 100% |
| synth_downgrade | 0 | — | — | — |

## Yorum

- **NÖTR**: upgrade≈0 beklenir (sentez yükseltmesi SAĞLAM+ ister).
- **SAĞLAM**: bölge teşviki (upgrade) ve uzak-giriş kesimi (downgrade) burada görünür.
- Bu price-only; gerçek temel skor zamanla değişir → güven hâlâ orta.
