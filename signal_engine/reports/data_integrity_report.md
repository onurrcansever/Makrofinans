# Veri bütünlüğü raporu

Üretim: `2026-07-16T15:57:28`

## 1. İndirme / karantina boşlukları

Yok — tüm semboller settlement bar üretti.

## 2. LSE takvim delikleri (aynı borsa ≠ aynı bar seti)

### LSE_USD

| Sembol | Bars | d1 | Union'da eksik |
|--------|------|----|----------------|
| CSPX.L | 505 | 2026-07-16 | 2026-03-06 |
| VUAA.L | 506 | 2026-07-16 | — |

Çift farklar:
- `CSPX.L` vs `VUAA.L`: only_a=— · only_b=['2026-03-06']

### LSE_GBP

| Sembol | Bars | d1 | Union'da eksik |
|--------|------|----|----------------|
| EQQQ.L | 505 | 2026-07-16 | 2026-03-06 |
| VUSA.L | 505 | 2026-07-16 | 2026-03-06 |
| VUKE.L | 506 | 2026-07-16 | — |
| VEUR.L | 505 | 2026-07-16 | 2026-03-06 |
| VWRL.L | 505 | 2026-07-16 | 2026-03-06 |

Çift farklar:
- `EQQQ.L` vs `VUKE.L`: only_a=— · only_b=['2026-03-06']
- `VUSA.L` vs `VUKE.L`: only_a=— · only_b=['2026-03-06']
- `VUKE.L` vs `VEUR.L`: only_a=['2026-03-06'] · only_b=—
- `VUKE.L` vs `VWRL.L`: only_a=['2026-03-06'] · only_b=—

## 3. LSE-ahead (asset d1 > ^GSPC d1)

^GSPC d1: `2026-07-15`
- **EQQQ.L** 2026-07-16 > GSPC 2026-07-15
- **VUSA.L** 2026-07-16 > GSPC 2026-07-15
- **VUKE.L** 2026-07-16 > GSPC 2026-07-15
- **VEUR.L** 2026-07-16 > GSPC 2026-07-15
- **VWRL.L** 2026-07-16 > GSPC 2026-07-15
- **CSPX.L** 2026-07-16 > GSPC 2026-07-15
- **VUAA.L** 2026-07-16 > GSPC 2026-07-15

## Sonuç

- Aynı borsa takvimi varsayımı **veri delikleri yüzünden bozulabilir** (ör. CSPX vs VUAA `2026-03-06`).
- Skor motoru `settlement_asof` ile LSE-ahead'i keser; getiri pencereleri sembolün kendi bar takvimini kullanır → FX katsayısı sembol bazında farklı olabilir.
- FROTO tipi boşluk: ham seri yok → `VERI_YOK` → teknik filtre dışı.
