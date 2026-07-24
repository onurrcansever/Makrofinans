# Kısa momentum (siki) — canlı ops / rollback

## Bağlama özeti

- Preset: `siki` (3A +4)
- Backtest: 30 sembol × 5y; upgrade n=165, ort. +%1.37 1A
- Whipsaw: base 5 / siki 6 flip (±1) — göreli % yüksek, mutlak ek &lt; 3 → gürültü

## Rollback kriteri (yazılı)

`signal_config.yaml` → `short_momentum.monitor`:

1. **Whipsaw:** canlı izleme `whipsaw_rate` &gt; `backtest_ref_whipsaw_rate × rollback_whipsaw_mult` (varsayılan **2×**)
2. Pencere: özellikle **ilk 30 gün** (`rollback_window_days`) — aşılırsa hemen geri al
3. Aksiyon: `short_momentum.enabled: false` (tek satır) + uygulamayı yenile

Haftalık komut:

```bash
python3 scripts/monitor_short_mom_live.py
```

Çıkış kodu 2 → rollback önerisi.

### Otomasyon (kaçırma riskini azaltır)

| Yer | Ne |
|-----|-----|
| **GitHub Actions** | [`.github/workflows/short-mom-monitor.yml`](../../.github/workflows/short-mom-monitor.yml) — her Pazartesi 07:00 UTC; eşiği aşarsa job fail |
| **macOS LaunchAgent** | `bash macos/short_mom_monitor_kurulum.sh` — her Pazartesi 10:00 (Mac açıkken) + bildirim |

İlk 30 günde en az bir kanalın aktif olması yeterli; ikisi birlikte en güvenlisi.

## Flip dağılımı

```bash
python3 scripts/inspect_short_mom_flips.py
```

Çıktı: `trend_short_mom_flip_diff.md` — ekstra (yalnız siki) olayların sembol + tarihi.

## Not

`hit_1m` / `avg_*` kollarda aynı görünmesi bug değil: ileri getiri fiyat yolu ortaktır; fark `upgrades` sütunundadır.
