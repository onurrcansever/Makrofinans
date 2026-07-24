# Trend kısa-momentum A/B

Üretilme: `2026-07-24T11:28:12.732623+00:00`
Sembol: **30** · step=5

## Verdict: **bağla** · preset=`siki`

- --- aday=siki ---
- whipsaw_flips base=5 siki=6 extra=1 (DUR için extra>=3 VE pct>15.0)
- whipsaw_increase_pct=20.0
- NOT: göreli %20 yüksek ama extra=1 < 3 — küçük örneklem gürültüsü; whipsaw DUR tetiklemedi
- hit_1m_pp=+0.00 (min 0.0)
- upgrade_n=165 upgrade_avg_1m=1.3711560410308397 (min 0.0)
- OK: siki whipsaw çift-eşik geçti ve hit/upgrade kabul

## Kollar

| Arm | n | hit_1m | avg_1m | avg_3m | flips | whipsaw_rate | upgrades | up_avg_1m |
|-----|---|--------|--------|--------|-------|--------------|----------|-----------|
| base | 5640 | 0.5650709219858157 | 1.9239923282862712 | 6.402910747377765 | 5 | 0.0008866820358219542 | 0 | None |
| small | 5640 | 0.5650709219858157 | 1.9239923282862712 | 6.402910747377765 | 8 | 0.0014186912573151268 | 258 | 1.5586961935605508 |
| temkinli | 5640 | 0.5650709219858157 | 1.9239923282862712 | 6.402910747377765 | 6 | 0.001064018442986345 | 200 | 1.4481535358793667 |
| siki | 5640 | 0.5650709219858157 | 1.9239923282862712 | 6.402910747377765 | 6 | 0.001064018442986345 | 165 | 1.3711560410308397 |

> `hit_1m` / `avg_*` tüm kollarda aynıdır: her adımda aynı ileri fiyat yolu ölçülür; 
> kol farkı `upgrades` / `up_avg_1m` (base'e göre seviye yükselten örnekler) sütunlarındadır.

## Notlar

- Composite: trend kolu A/B; MR/vol/RS aynı; liq skip
- Whipsaw proxy: REDUCE↔WATCH+ flip (cold-start levels)
- Whipsaw DUR = göreli% VE mutlak ek flip (küçük base gürültüsü için)
- hit/avg_* tüm adımlarda aynıdır: ileri getiri fiyat yolu; kol farkı upgrades'te
- Aday sırası: siki(+4) → temkinli(+6) → small
- Panel/UX değişikliği yok
