# -*- coding: utf-8 -*-
"""
Dinamik Yatırım Danışmanı (kural tabanlı açıklama motoru)
=========================================================
Gerçek LLM değil — mevcut makro/teknik veriden şeffaf, okunabilir gerekçe üretir.
Her öneri: yön oku, güven skoru, neden listesi, dikkat notları.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

import config
from allocation_engine import TahsisSonucu, VARLIKLAR, tl_profil_risk_tavan
from investor_profile import VADE_SECENEKLERI, YatirimProfili, vade_kisa_mi
from macro_data import MacroSnapshot
from market_context import MakroBaglam, makro_baglam_olustur
from stock_scanner import TaramaSonucu

if TYPE_CHECKING:
    from audit_engine import DenetimRaporu


@dataclass
class VarlikTavsiyesi:
    anahtar: str
    ad: str
    agirlik_pct: float
    tutar_eur: float
    skor: float
    sinyal: str          # GUCLU_AL | AL | TUT | AZALT | KACIN
    sinyal_etiket: str
    ok: str              # ↑ ↗ → ↘ ↓
    ok_renk: str         # yesil | sari | kirmizi | gri
    guven: int           # 0-100
    baslik: str
    nedenler: List[str] = field(default_factory=list)
    dikkat: List[str] = field(default_factory=list)
    teknik: Optional[str] = None


@dataclass
class DanismanRaporu:
    genel_ozet: str
    rejim_yorumu: str
    oncelik_sirasi: List[str]
    varliklar: List[VarlikTavsiyesi] = field(default_factory=list)
    kacinilan: List[str] = field(default_factory=list)
    makro_baglam: Optional[MakroBaglam] = None
    denetim: Optional["DenetimRaporu"] = None


def _ok_yon(degisim: Optional[float]) -> tuple:
    if degisim is None:
        return "→", "gri", "Yatay / veri yok"
    if degisim > 8:
        return "↑", "yesil", f"Son 3 ay +{degisim:.1f}%"
    if degisim > 2:
        return "↗", "yesil", f"Son 3 ay +{degisim:.1f}%"
    if degisim < -8:
        return "↓", "kirmizi", f"Son 3 ay {degisim:.1f}%"
    if degisim < -2:
        return "↘", "kirmizi", f"Son 3 ay {degisim:.1f}%"
    return "→", "sari", f"Son 3 ay {degisim:+.1f}%"


def _sinyal(agirlik: float, skor: float, rejim: str, key: str) -> tuple:
    if agirlik < 0.01 or (rejim == "KRIZ" and key in ("bist", "crypto", "tl_deposit", "silver")):
        return "KACIN", "Kaçının", "↓", "kirmizi"
    if agirlik >= 0.18 and skor >= 65:
        return "GUCLU_AL", "Güçlü alım", "↑", "yesil"
    if agirlik >= 0.10 and skor >= 50:
        return "AL", "Alım önerisi", "↗", "yesil"
    if agirlik >= 0.05:
        return "TUT", "Tutun / kademeli", "→", "sari"
    return "AZALT", "Azaltın", "↘", "kirmizi"


def _altin_aciklama(snap, tahsis, profil, baglam: Optional[MakroBaglam]) -> VarlikTavsiyesi:
    w = tahsis.agirliklar.get("gold", 0)
    sk = tahsis.skorlar.get("gold", 0)
    sig, lbl, ok, renk = _sinyal(w, sk, tahsis.rejim.rejim, "gold")
    nedenler, dikkat = [], []

    alt_ctx = next((p for p in (baglam.parcalar if baglam else []) if "Altın" in p.baslik), None)
    if alt_ctx:
        ok = alt_ctx.ok
        # Alanları ayrı tut — konum/trend/beklenti tek stringde birleşmesin (kart sızıntısı)
        nedenler.append(f"**Canlı (altın):** {alt_ctx.canli}")
        if alt_ctx.konum:
            nedenler.append(f"**Konum:** {alt_ctx.konum}")
        if alt_ctx.trend:
            nedenler.append(f"**Trend:** {alt_ctx.trend}")
        if alt_ctx.beklenti and "orta bölge" not in alt_ctx.beklenti:
            nedenler.append(f"**Beklenti:** {alt_ctx.beklenti}")
    elif snap.altin_usd_oz:
        nedenler.append(f"Spot altın ~**${snap.altin_usd_oz:,.0f}/oz** — tahsis önerisi portföyün **%{w*100:.0f}**'i.")

    if tahsis.rejim.rejim in ("ENFLASYON_KORUMA", "KRIZ", "EM_STRES"):
        nedenler.append(f"Makro rejim **{tahsis.rejim.etiket}** — altın tarihsel olarak bu ortamlarda koruma sağlar.")
    if (snap.enflasyon_tr_yillik or 0) > 25:
        nedenler.append(f"Türkiye enflasyonu ~**%{snap.enflasyon_tr_yillik:.0f}** — satın alma gücü koruma ihtiyacı.")

    cds_ctx = next((p for p in (baglam.parcalar if baglam else []) if "CDS" in p.baslik), None)
    if cds_ctx:
        nedenler.append(f"**CDS:** {cds_ctx.canli} — {cds_ctx.konum}")
    elif (snap.veri.cds_5y_bp or 0) > 250:
        nedenler.append(f"CDS **{snap.veri.cds_5y_bp:.0f} bp** — ülke risk primi yükselince altına talep artar.")

    if profil.risk == "dusuk":
        nedenler.append("Düşük risk profilinizle uyumlu: fiziki/hesap altın volatil hisseye göre daha öngörülebilir.")

    altin_3m = snap.altin_3m_degisim
    if altin_3m is not None and altin_3m < config.ALTIN_MOMENTUM_ESIK:
        dikkat.append(
            f"Son 3 ay **{altin_3m:+.1f}%** — momentum zayıf; "
            "tahsis koruma amaçlı, **kademeli alım** uygun."
        )
        if sig == "GUCLU_AL":
            sig, lbl = "AL", "Alım önerisi"
        elif sig == "AL" and w >= 0.15:
            sig, lbl = "TUT", "Tutun / kademeli"
            ok, renk = "→", "sari"

    if w < 0.05:
        dikkat.append("Mevcut makro ve profil kombinasyonunda altın ağırlığı düşük tutuldu.")

    baslik = "Bu aşamada **Altın** öneriyoruz." if sig in ("GUCLU_AL", "AL") else (
        "Altında **bekleyin** veya küçük pozisyon." if sig == "TUT" else "Altın için **acele etmeyin**."
    )
    tek = alt_ctx.trend if alt_ctx else None
    return VarlikTavsiyesi(
        "gold", config.VARLIK_ETIKETLERI["gold"], w * 100, config.TOPLAM_EUR * w, sk,
        sig, lbl, ok, renk, min(95, int(sk + w * 30)), baslik, nedenler, dikkat,
        tek,
    )


def _bist_aciklama(snap, tahsis, profil, tarama: Optional[TaramaSonucu]) -> VarlikTavsiyesi:
    w = tahsis.agirliklar.get("bist", 0)
    sk = tahsis.skorlar.get("bist", 0)
    sig, lbl, ok, renk = _sinyal(w, sk, tahsis.rejim.rejim, "bist")
    ok, renk, tek = _ok_yon(snap.bist100_3m_degisim)
    nedenler, dikkat = [], []

    endeks = next((e for e in (tarama.endeksler if tarama else []) if "BIST" in e.ad), None)
    if endeks and endeks.rsi:
        tek = f"BIST 100 RSI **{endeks.rsi:.0f}** · 1 ay {endeks.degisim_1ay or 0:+.1f}%"
        if endeks.rsi < 42:
            nedenler.append("RSI dip bölgesinde — dönüş teyidi yok; teknik izleme penceresi.")
        elif endeks.rsi > 65:
            dikkat.append("RSI yüksek — kısa vadede kar realizasyonu baskısı olabilir.")

    if tahsis.rejim.rejim == "TL_FIRSAT" and tahsis.tl_tavan_oran >= 0.05:
        nedenler.append("**TL fırsat** rejimi: yerel varlıklar (BIST) makro tabloyla uyumlu.")
    elif tahsis.rejim.rejim in ("KRIZ", "EM_STRES"):
        dikkat.append("Stres rejiminde BIST önerisi bilinçli olarak **kısıtlandı** — kur riski baskın.")
    if snap.bist100:
        nedenler.append(f"BIST 100 seviyesi **{snap.bist100:,.0f}** · 3 aylık trend: {snap.bist100_3m_degisim or 0:+.1f}%.")
    if profil.risk == "dusuk":
        dikkat.append("Düşük risk profili: BIST üst sınırı %5 ile sınırlandı.")
    if vade_kisa_mi(profil.vade):
        dikkat.append("Kısa vade profili: hisse ağırlığı düşük tutulmalı.")

    if sig in ("GUCLU_AL", "AL"):
        baslik = "Bu aşamada **BIST 100** exposure öneriyoruz (kademeli)."
    elif sig == "KACIN":
        baslik = "Şu an **BIST'ten uzak durun** — makro risk öncelikli."
    else:
        baslik = "BIST için **küçük ve kademeli** pozisyon yeterli."

    return VarlikTavsiyesi(
        "bist", config.VARLIK_ETIKETLERI["bist"], w * 100, config.TOPLAM_EUR * w, sk,
        sig, lbl, ok, renk, min(90, int(sk + w * 25)), baslik, nedenler, dikkat, tek,
    )


def _tl_aciklama(
    snap,
    tahsis,
    profil,
    baglam: Optional[MakroBaglam],
    mevduat=None,
) -> VarlikTavsiyesi:
    w = tahsis.agirliklar.get("tl_deposit", 0)
    sk = tahsis.skorlar.get("tl_deposit", 0)
    sig, lbl, ok, renk = _sinyal(w, sk, tahsis.rejim.rejim, "tl_deposit")
    nedenler, dikkat = [], []

    reel_mev = None
    if mevduat and mevduat.profil_vade_reel is not None:
        reel_mev = mevduat.profil_vade_reel
    elif tahsis.tl_mevduat_reel is not None:
        reel_mev = tahsis.tl_mevduat_reel

    tl_ctx = next((p for p in (baglam.parcalar if baglam else []) if "TL mevduat" in p.baslik), None)
    if tl_ctx:
        ok = tl_ctx.ok
        nedenler.append(f"**Canlı:** {tl_ctx.canli}")
        nedenler.append(f"**{tl_ctx.trend}**")
        nedenler.append(f"**Süre / beklenti:** {tl_ctx.beklenti}")
    else:
        tcmb = snap.veri.tcmb_politika_faizi or 37
        enf = snap.enflasyon_tr_yillik or 35
        reel = tcmb - enf
        nedenler.append(f"TCMB ~**%{tcmb:.0f}**, enflasyon ~**%{enf:.0f}** → reel faiz ~**{reel:+.1f} pp**.")
        if tahsis.rejim.rejim == "TL_FIRSAT" and reel > 0 and tahsis.tl_tavan_oran >= 0.05:
            nedenler.append("TL fırsat rejimi + pozitif reel faiz — mevduat cazip.")
        elif "askıda" in tahsis.rejim.etiket:
            nedenler.append(
                f"**{tahsis.rejim.etiket}** — reel faiz lehte olabilir; "
                f"4 kapı tavanı **%{tahsis.tl_tavan_oran*100:.0f}**."
            )

    if reel_mev is not None:
        vade_etik = mevduat.profil_vade if mevduat and mevduat.profil_vade else "profil vadesi"
        nedenler.append(
            f"Banka net reel ({vade_etik}): **{reel_mev:+.1f} pp** — mevduat analizi tablosu."
        )

    nedenler.append(f"4 kapılı algoritma TL tavanını **%{tahsis.tl_tavan_oran*100:.0f}** olarak hesapladı.")
    if tahsis.tl_reel_sinirlandi:
        nedenler.append(
            "Reel getiri negatif — TL payı otomatik sınırlandı; fazla EUR/altın/USD'ye aktarıldı."
        )
    if tahsis.tl_risk_sinirlandi:
        nedenler.append(
            f"**{profil.risk}** risk profili — kısa vadeli reel carry olsa bile "
            f"TL kur riski sınırlı tutuldu (max %{tl_profil_risk_tavan(profil, tahsis.rejim.rejim)*100:.0f})."
        )
    if tahsis.tl_rejim_sinirlandi:
        nedenler.append(
            f"Rejim **{tahsis.rejim.etiket}** — TL_FIRSAT değil; "
            f"TL payı %{config.TL_REJIM_DISI_MAX_ORAN*100:.0f} tavanı ile sınırlandı."
        )
    if (snap.veri.cds_5y_bp or 300) > 300:
        dikkat.append(f"CDS {snap.veri.cds_5y_bp:.0f} bp yüksek — kur riski TL getirisini yiyebilir.")
    if tahsis.rejim.rejim == "KRIZ":
        dikkat.append("Kriz modu: TL pozisyonu **sıfırlandı**.")

    if reel_mev is not None and reel_mev <= config.TL_REEL_NEGATIF_ESIK:
        if sig in ("GUCLU_AL", "AL"):
            sig = "TUT" if w >= 0.05 else "AZALT"
            lbl = "Tutun / kademeli" if sig == "TUT" else "Azaltın"
            ok, renk = ("→", "sari") if sig == "TUT" else ("↘", "kirmizi")
        dikkat.append(
            f"Mevduat reel **{reel_mev:+.1f} pp** — enflasyon altında; güçlü alım uygun değil."
        )

    if tahsis.rejim.rejim != "TL_FIRSAT" and sig in ("GUCLU_AL", "AL"):
        sig = "TUT" if w >= 0.05 else "AZALT"
        lbl = "Tutun / kademeli" if sig == "TUT" else "Azaltın"
        ok, renk = ("→", "sari") if sig == "TUT" else ("↘", "kirmizi")
        dikkat.append(
            f"Rejim **{tahsis.rejim.etiket}** — TL fırsat koşulları sağlanmıyor; "
            "güçlü alım sinyali verilmedi."
        )

    reel_politika = (snap.veri.tcmb_politika_faizi or 37) - (snap.enflasyon_tr_yillik or 35)
    reel_goster = reel_mev if reel_mev is not None else reel_politika
    if sig in ("GUCLU_AL", "AL"):
        baslik = "Bu aşamada **TL mevduat** öneriyoruz."
    elif sig == "TUT":
        baslik = "TL mevduat **sınırlı** tutulmalı."
    else:
        baslik = "TL mevduat **önerilmiyor**."
    return VarlikTavsiyesi(
        "tl_deposit", config.VARLIK_ETIKETLERI["tl_deposit"], w * 100, config.TOPLAM_EUR * w, sk,
        sig, lbl, ok if reel_goster > 0 else "↘", renk if reel_goster > 0 else "kirmizi",
        min(88, int(sk + w * 20)), baslik, nedenler, dikkat,
    )


def _eur_usd_aciklama(key, snap, tahsis, profil, baglam: Optional[MakroBaglam]) -> VarlikTavsiyesi:
    w = tahsis.agirliklar.get(key, 0)
    sk = tahsis.skorlar.get(key, 0)
    ad = config.VARLIK_ETIKETLERI[key]
    sig, lbl, ok, renk = _sinyal(w, sk, tahsis.rejim.rejim, key)
    nedenler, dikkat = [], []

    if key == "eur_cash":
        nedenler.append("Ana para biriminiz EUR — mevduat **taban** pozisyon olarak korunur.")
        if tahsis.rejim.rejim in ("KRIZ", "EM_STRES"):
            nedenler.append("Stres ortamında EUR likidite ve güvenli liman rolü görür.")
    else:
        nedenler.append("ABD doları global rezerv para — jeopolitik stresde talep artabilir.")
        fed_ctx = next((p for p in (baglam.parcalar if baglam else []) if "Fed" in p.baslik), None)
        if fed_ctx:
            ok = fed_ctx.ok
            nedenler.append(f"**Fed (canlı):** {fed_ctx.canli}")
            nedenler.append(f"**Trend:** {fed_ctx.trend}")
            nedenler.append(f"**Beklenti:** {fed_ctx.beklenti}")
        elif (snap.veri.fed_faizi or 0) > 3:
            nedenler.append(f"Fed faizi ~**%{snap.veri.fed_faizi:.1f}** — USD mevduat getirisi destekleyici.")

    if vade_kisa_mi(profil.vade):
        nedenler.append("Kısa vade profiliniz nakit/mevduat ağırlığını destekliyor.")

    baslik = f"Bu aşamada **{ad}** tutmanızı öneriyoruz." if w >= 0.10 else f"**{ad}** minimal düzeyde."
    return VarlikTavsiyesi(
        key, ad, w * 100, config.TOPLAM_EUR * w, sk, sig, lbl, ok, renk,
        min(92, int(sk + w * 15)), baslik, nedenler, dikkat,
    )


def _crypto_aciklama(snap, tahsis, profil) -> VarlikTavsiyesi:
    w = tahsis.agirliklar.get("crypto", 0)
    sk = tahsis.skorlar.get("crypto", 0)
    sig, lbl, ok, renk = _sinyal(w, sk, tahsis.rejim.rejim, "crypto")
    ok, renk, tek = _ok_yon(snap.btc_3m_degisim)
    nedenler, dikkat = [], []

    if snap.btc_usd:
        nedenler.append(f"BTC ~**${snap.btc_usd:,.0f}** · 3 ay {snap.btc_3m_degisim or 0:+.1f}%.")
    if tahsis.rejim.rejim == "RISK_ON":
        nedenler.append("Risk-iştahı rejimi kripto için teorik olarak uygun.")
    else:
        dikkat.append("Mevcut rejim kripto için agresif değil.")
    if profil.risk == "dusuk":
        dikkat.append("Düşük risk profili: kripto **önerilmiyor**.")
    dikkat.append("Kripto yüksek volatilite — portföyün küçük bir dilimi bile risklidir.")

    baslik = "BTC **sınırlı** tahsis." if w > 0.02 else "Kripto **şimdilik yok**."
    return VarlikTavsiyesi(
        "crypto", config.VARLIK_ETIKETLERI["crypto"], w * 100, config.TOPLAM_EUR * w, sk,
        sig, lbl, ok, renk, min(70, int(sk)), baslik, nedenler, dikkat, tek,
    )


def _gumus_aciklama(snap, tahsis, profil) -> VarlikTavsiyesi:
    w = tahsis.agirliklar.get("silver", 0)
    sk = tahsis.skorlar.get("silver", 0)
    sig, lbl, ok, renk = _sinyal(w, sk, tahsis.rejim.rejim, "silver")
    nedenler = ["Altına göre daha volatil — ikincil emtia."]
    if w >= 0.08 and tahsis.rejim.rejim == "RISK_ON":
        nedenler.append("Risk-on rejiminde gümüş beta artabilir — pay sınırlı tutuldu.")
    elif w < 0.05:
        nedenler.append("Mevcut pay minimal; öncelik altın ve nakit tarafında.")
    baslik = "Gümüş **ikincil** emtia — küçük pay." if w < 0.08 else "Gümüş **kademeli** alınabilir."
    return VarlikTavsiyesi(
        "silver", config.VARLIK_ETIKETLERI["silver"], w * 100, config.TOPLAM_EUR * w, sk,
        sig, lbl, ok, renk, int(sk), baslik, nedenler, [],
    )


def danisman_raporu_olustur(
    snap: MacroSnapshot,
    tahsis: TahsisSonucu,
    profil: Optional[YatirimProfili] = None,
    tarama: Optional[TaramaSonucu] = None,
    mevduat: Optional[object] = None,
) -> DanismanRaporu:
    profil = profil or tahsis.profil or YatirimProfili()
    baglam = makro_baglam_olustur(snap, tahsis, profil=profil)

    varliklar = [
        _altin_aciklama(snap, tahsis, profil, baglam),
        _bist_aciklama(snap, tahsis, profil, tarama),
        _tl_aciklama(snap, tahsis, profil, baglam, mevduat=mevduat),
        _eur_usd_aciklama("eur_cash", snap, tahsis, profil, baglam),
        _eur_usd_aciklama("usd_cash", snap, tahsis, profil, baglam),
        _crypto_aciklama(snap, tahsis, profil),
        _gumus_aciklama(snap, tahsis, profil),
    ]
    varliklar.sort(key=lambda x: (-x.agirlik_pct, -x.guven))

    oncelik = [v.ad for v in varliklar if v.sinyal in ("GUCLU_AL", "AL")][:3]
    kacin = [v.ad for v in varliklar if v.sinyal == "KACIN"]

    en_iyi = varliklar[0].ad if varliklar else "—"
    rejim_etiket = tahsis.rejim.etiket
    if tahsis.rejim.rejim == "KRIZ" or tahsis.tl_tavan_oran < 0.01:
        genel = (
            f"**{rejim_etiket}** — TL tahsisi kapalı veya sıfır (Kapı 1 / 4 kapı). "
            f"Profiliniz: *{profil.ozet()}*. "
        )
    elif "askıda" in rejim_etiket:
        genel = (
            f"**{rejim_etiket}** — reel faiz lehte olabilir; makro haber/kapılar TL payını kısıtlıyor. "
            f"Profiliniz: *{profil.ozet()}*. "
        )
    else:
        genel = (
            f"**{rejim_etiket}** rejimindeyiz. Profiliniz: *{profil.ozet()}*. "
            f"Bu tabloda öncelik **{en_iyi}** — portföyün en büyük payı burada. "
        )
    if oncelik:
        genel += f"Güçlü öneriler: **{', '.join(oncelik)}**. "
    if kacin:
        genel += f"Uzak durulması gerekenler: **{', '.join(kacin)}**. "
    genel += "Aşağıdaki kartlarda her varlık için *neden* açıklandı."

    rejim_yorum = (
        f"{tahsis.rejim.aciklama} "
        f"(EUR/TRY {snap.veri.eur_try or '—'}, "
        f"{'kur volatilitesi + ' if vade_kisa_mi(profil.vade) else ''}"
        f"CDS {snap.veri.cds_5y_bp or '—'} bp, VIX {snap.vix or '—'}). "
        f"Profil vadeniz: **{VADE_SECENEKLERI.get(profil.vade, profil.vade)}**. "
        f"Canlı makro değerlendirme aşağıda — **{baglam.guncelleme}** güncellendi."
    )

    from audit_engine import denetim_calistir
    denetim = denetim_calistir(
        snap, tahsis, varliklar, baglam, mevduat=mevduat, oncelik=oncelik,
        tarama=tarama,
    )

    # Denetim bulgularını ilgili kartların dikkat listesine ekle
    for b in denetim.bulgular:
        if b.varlik and b.seviye in ("KRITIK", "UYARI"):
            v = next((x for x in varliklar if x.anahtar == b.varlik), None)
            if v:
                etiket = "⛔" if b.seviye == "KRITIK" else "⚠️"
                v.dikkat.append(
                    f"{etiket} **Denetim:** {b.baslik} — {b.taraf_a} / {b.taraf_b} → {b.oneri}"
                )

    return DanismanRaporu(
        genel_ozet=genel,
        rejim_yorumu=rejim_yorum,
        oncelik_sirasi=oncelik,
        varliklar=varliklar,
        kacinilan=kacin,
        makro_baglam=baglam,
        denetim=denetim,
    )
