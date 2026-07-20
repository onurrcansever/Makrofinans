# 2026 Menkul Kıymet Vergi Notu (özet)

**Kapsam:** Tam mükellef gerçek kişi (bireysel yatırımcı).  
**Amaç:** Karar destek hatırlatması — yasal tavsiye veya beyanname hesabı değildir.

Oranlar değişebilir. Nihai teyit: GİB, banka/aracı kurum, yeminli mali müşavir.  
Kaynak özet: Türkiye menkul kıymet vergileme matrisi (2026 dönemi özeti; kullanıcı PDF referansı).

---

## Bu yazılımda ne hesaplanır?

| Varlık | Yazılımda | Vergi notu |
|--------|-----------|------------|
| TL / döviz mevduat | **Net %** (stopaj düşülmüş) | Zaten modele dahil |
| BIST hisse, yabancı hisse/ETF, TEFAS | **Brüt** piyasa getirisi / K/Z | Stopaj/beyan **düşülmez** |

---

## Kısa kurallar (Tam mükellef gerçek kişi)

1. **BIST’te işlem gören hisse alım-satım** — Geçici 67: stopaj çoğu senaryoda **%0**; stopaj nihai / beyan genelde yok (özet; süre ve istisna koşulları için kaynak tabloya bakın).
2. **TEFAS / yatırım fonu** — Stopaj oranı **iktisap (alış) tarihine ve fon türüne** bağlı (%0 / %7,5 / %10 / %15…). Hisse senedi yoğun fonlarda sıklıkla %0. Unvanında “döviz”, yabancı, eurobond vb. geçenler istisna dışı kalabilir. Banka/TEFAS ekranındaki stopajı esas alın.
3. **TL vadeli mevduat** — Uygulama varsayılanı yaklaşık **%15** stopaj (net % tabloda). Dönemsel vade dilimleri değişebilir → bankadan teyit.
4. **Döviz mevduat (EUR/USD)** — Uygulama varsayılanı yaklaşık **%25** stopaj; yine banka teyidi.
5. **Yabancı hisse / yurt dışı ETF (ör. Revolut NASDAQ)** — BIST Geç. 67 ile **aynı değildir**. TR stopaj matrisi otomatik uygulanmaz; aracı kurum + olası beyan ayrı konu.
6. **Kar payı (temettü)** — Tipik stopaj + yarısı istisna; diğer gelirlerle birlikte eşik aşımında beyan gündeme gelebilir. Tarama skoruna karışmaz.

---

## Kullanım sırası

1. Önce tahsis ve **mevduat net %** (yazılımın güçlü yanı).
2. BIST payı: brüt teknik getiri, stopaj genelde %0 varsayımıyla net’e daha yakın (komisyon ayrı).
3. TEFAS: alış tarihi + fon tipi → banka stopajı; yazılım “net fon getirisi” iddia etmez.
4. Yabancı ETF/hisse: vergiyi yazılımdan beklemeyin.
