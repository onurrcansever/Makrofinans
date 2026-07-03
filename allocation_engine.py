# -*- coding: utf-8 -*-
"""
Çoklu Varlık Tahsis Motoru
===========================
EUR, USD, TL mevduat, altın, gümüş ve rezerv (diğer) için şeffaf,
kural tabanlı ağırlık üretir. Mevcut 4 kapılı TL tavan mantığı korunur.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import config
from decision_engine import karar_ver
from investor_profile import YatirimProfili, profil_degerlendirme, profil_mevduat_vadesi, profil_sinirlari, profil_skor_ayari
from macro_data import MacroSnapshot
from regime import RejimSonucu, rejim_tespit
from regime_stability import rejim_kararli_uygula
from girdi_dogrulama import snap_rejim_icin
from rates_tr import mevduat_analizi

VARLIKLAR = ["eur_cash", "usd_cash", "tl_deposit", "gold", "silver", "bist", "crypto"]


@dataclass
class TahsisSonucu:
    agirliklar: Dict[str, float]
    skorlar: Dict[str, float]
    rejim: RejimSonucu
    tl_karar_adimlari: List[str]
    tl_tavan_oran: float
    adimlar: List[str] = field(default_factory=list)
    uyarilar: List[str] = field(default_factory=list)
    tavsiye_metni: str = ""
    profil: Optional[YatirimProfili] = None
    profil_notlari: List[str] = field(default_factory=list)
    tl_mevduat_reel: Optional[float] = None
    tl_reel_sinirlandi: bool = False


def _skor_sinirla(s: float) -> float:
    return max(0.0, min(100.0, s))


def tl_reel_negatif_max_oran(reel_mev: float) -> float:
    """Profil vadesi mevduat reel getirisine göre TL üst sınırı (0–1)."""
    if reel_mev > config.TL_REEL_NEGATIF_ESIK:
        return config.MUTLAK_TAVAN
    if reel_mev <= config.TL_REEL_COK_NEGATIF_ESIK:
        return config.TL_REEL_COK_NEGATIF_MAX_ORAN
    return config.TL_REEL_NEGATIF_MAX_ORAN


def _tl_fazlalik_dagit(agirliklar: Dict[str, float], fark: float) -> None:
    agirliklar["eur_cash"] += fark * 0.55
    agirliklar["gold"] += fark * 0.30
    agirliklar["usd_cash"] += fark * 0.15


def _varlik_skorlari(
    snap: MacroSnapshot, rejim: RejimSonucu, profil: Optional[YatirimProfili] = None
) -> Dict[str, float]:
    v = snap.veri
    skor = dict(config.TEMEL_SKORLAR)

    cds = v.cds_5y_bp or 300
    enflasyon = snap.enflasyon_tr_yillik or 35.0
    tcmb = v.tcmb_politika_faizi or (v.tl_mevduat_brut_faiz or 0.4) * 100
    reel_faiz = tcmb - enflasyon
    vix = snap.vix or 20.0

    # EUR — güvenli liman, krizde artar
    if rejim.rejim == "KRIZ":
        skor["eur_cash"] += 25
    if rejim.rejim == "EM_STRES":
        skor["eur_cash"] += 15
    if v.rezerv_artiyor is False:
        skor["eur_cash"] += 5

    # USD — Fed faizi ve global güvenli liman
    if (v.fed_faizi or 0) > 3.5:
        skor["usd_cash"] += 10
    if rejim.rejim in ("KRIZ", "EM_STRES"):
        skor["usd_cash"] += 12
    if vix > 22:
        skor["usd_cash"] += 8

    # TL — reel faiz ve 4 kapı tavanı ile sınırlı
    if reel_faiz > 2:
        skor["tl_deposit"] += 15
    elif reel_faiz > 0:
        skor["tl_deposit"] += 8
    else:
        skor["tl_deposit"] -= 15
    if cds < 250:
        skor["tl_deposit"] += 10
    elif cds > 320:
        skor["tl_deposit"] -= 20
    if rejim.rejim == "TL_FIRSAT":
        skor["tl_deposit"] += 20
    if rejim.rejim == "KRIZ":
        skor["tl_deposit"] -= 40

    # Altın — enflasyon ve jeopolitik
    if enflasyon > 25:
        skor["gold"] += min(15, (enflasyon - 25) * 0.5)
    if (v.savas_risk_makale_sayisi or 0) > 10:
        skor["gold"] += 10
    if rejim.rejim in ("KRIZ", "ENFLASYON_KORUMA", "EM_STRES"):
        skor["gold"] += 15
    if cds > 280:
        skor["gold"] += 8

    # Gümüş — risk-on ve altına göre beta
    if rejim.rejim == "RISK_ON":
        skor["silver"] += 15
    if vix < 18:
        skor["silver"] += 8
    if rejim.rejim == "KRIZ":
        skor["silver"] -= 25
    if cds > 300:
        skor["silver"] -= 10

    # BIST — TL fırsatı ve yerel risk iştahı
    if rejim.rejim in ("TL_FIRSAT", "RISK_ON"):
        skor["bist"] += 15
    if reel_faiz > 0 and cds < 280:
        skor["bist"] += 10
    if snap.bist100_3m_degisim is not None:
        if snap.bist100_3m_degisim > 5:
            skor["bist"] += 8
        elif snap.bist100_3m_degisim < -10:
            skor["bist"] -= 12
    if rejim.rejim in ("KRIZ", "EM_STRES"):
        skor["bist"] -= 25
    if cds > 320:
        skor["bist"] -= 15

    # Kripto — yüksek risk, risk-on rejiminde sınırlı tahsis
    if rejim.rejim == "RISK_ON" and vix < 20:
        skor["crypto"] += 20
    if snap.btc_3m_degisim is not None and snap.btc_3m_degisim > 15:
        skor["crypto"] += 8
    if snap.btc_3m_degisim is not None and snap.btc_3m_degisim < -20:
        skor["crypto"] -= 15
    if rejim.rejim in ("KRIZ", "EM_STRES"):
        skor["crypto"] -= 30
    if cds > 300:
        skor["crypto"] -= 10

    if profil:
        for k, d in profil_skor_ayari(profil).items():
            skor[k] += d

    return {k: _skor_sinirla(v) for k, v in skor.items()}


def _skorlari_agirliga_cevir(
    skorlar: Dict[str, float],
    min_agirlik: Optional[Dict[str, float]] = None,
    max_agirlik: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    mn = min_agirlik or config.MIN_AGIRLIK
    mx = max_agirlik or config.MAX_AGIRLIK
    toplam = sum(max(s, 1.0) for s in skorlar.values())
    ham = {k: max(skorlar[k], 1.0) / toplam for k in VARLIKLAR}
    sinirli = {}
    for k in VARLIKLAR:
        sinirli[k] = max(mn[k], min(mx[k], ham[k]))
    t = sum(sinirli.values())
    return {k: sinirli[k] / t for k in VARLIKLAR}


def tahsis_hesapla(snap: MacroSnapshot, profil: Optional[YatirimProfili] = None) -> TahsisSonucu:
    profil = profil or YatirimProfili()
    min_a, max_a, kalan_gun, mutlak_tavan = profil_sinirlari(profil)

    # TL kapı hesabı için vadeye göre kalan gün
    eski_kalan = config.KALAN_GUN
    config.KALAN_GUN = kalan_gun

    rejim = rejim_kararli_uygula(
        snap_rejim_icin(snap),
        getattr(snap, "girdi_dogrulama", None),
    )
    if rejim.degisim_gerekce:
        adimlar_pre = [rejim.degisim_gerekce]
    else:
        adimlar_pre = []

    if rejim.rejim == "BELIRSIZ" and rejim.komşu_rejimler:
        r1, r2 = rejim.komşu_rejimler
        skor1 = _varlik_skorlari(
            snap, RejimSonucu(rejim=r1, etiket=r1, aciklama="", guven=0.5), profil
        )
        skor2 = _varlik_skorlari(
            snap, RejimSonucu(rejim=r2, etiket=r2, aciklama="", guven=0.5), profil
        )
        skorlar = {k: (skor1[k] + skor2[k]) / 2.0 for k in VARLIKLAR}
    else:
        skorlar = _varlik_skorlari(snap, rejim, profil)
    agirliklar = _skorlari_agirliga_cevir(skorlar, min_a, max_a)
    adimlar = adimlar_pre + list(rejim.adimlar)
    if rejim.gecis_notu:
        adimlar.append(f"[Geçiş bölgesi] {rejim.gecis_notu}")
    adimlar.append(f"[Profil] {profil.ozet()} · yatırım ufku {kalan_gun} gün")
    uyarilar = list(snap.cekim_uyarilari)
    profil_notlari = profil_degerlendirme(profil, rejim.rejim)

    mevduat_vade_adi, mevduat_vade_gun = profil_mevduat_vadesi(profil)
    tl_mevduat_reel: Optional[float] = None
    tl_reel_sinirlandi = False

    # Mevcut 4 kapılı TL tavanını uygula (profil mevduat vadesi = Kapı 3 gün sayısı)
    tl_sonuc = karar_ver(snap.veri, vade_gun=mevduat_vade_gun)
    adimlar.extend([f"[TL kapı] {a}" for a in tl_sonuc.adimlar])
    uyarilar.extend(tl_sonuc.uyarilar)

    tl_tavan = tl_sonuc.tavan_oran if tl_sonuc.kapi1_gecti else 0.0
    if agirliklar["tl_deposit"] > tl_tavan:
        fark = agirliklar["tl_deposit"] - tl_tavan
        agirliklar["tl_deposit"] = tl_tavan
        _tl_fazlalik_dagit(agirliklar, fark)
        adimlar.append(
            f"TL ağırlığı 4 kapı tavanına ({tl_tavan*100:.1f}%) indirildi; "
            f"fazla %{fark*100:.1f} EUR/altın/USD'ye aktarıldı."
        )

    try:
        mev = mevduat_analizi(
            enflasyon=snap.enflasyon_tr_yillik,
            profil_vade=mevduat_vade_adi,
            eur_try=snap.veri.eur_try,
            kalan_gun=kalan_gun,
        )
        tl_mevduat_reel = mev.profil_vade_reel
    except Exception:
        mev = None

    if tl_mevduat_reel is not None and tl_mevduat_reel <= config.TL_REEL_NEGATIF_ESIK:
        reel_tavan = min(tl_tavan, tl_reel_negatif_max_oran(tl_mevduat_reel))
        skorlar["tl_deposit"] = min(skorlar["tl_deposit"], config.TL_REEL_SKOR_TAVAN_NEGATIF)
        if agirliklar["tl_deposit"] > reel_tavan:
            fark = agirliklar["tl_deposit"] - reel_tavan
            agirliklar["tl_deposit"] = reel_tavan
            _tl_fazlalik_dagit(agirliklar, fark)
            tl_reel_sinirlandi = True
            adimlar.append(
                f"[Mevduat reel {tl_mevduat_reel:+.1f} pp] TL payı "
                f"%{reel_tavan*100:.0f} ile sınırlandı; fazla %{fark*100:.1f} EUR/altın/USD'ye aktarıldı."
            )
        elif agirliklar["tl_deposit"] > 0:
            adimlar.append(
                f"[Mevduat reel {tl_mevduat_reel:+.1f} pp] TL payı "
                f"%{agirliklar['tl_deposit']*100:.0f} — güçlü alım uygun değil."
            )

    if rejim.rejim == "KRIZ":
        sablon = {
            "dusuk": {"eur_cash": 0.45, "usd_cash": 0.25, "gold": 0.30},
            "orta": {"eur_cash": 0.42, "usd_cash": 0.23, "gold": 0.28},
            "yuksek": {"eur_cash": 0.38, "usd_cash": 0.22, "gold": 0.25, "tl_deposit": 0.05},
        }
        baz = sablon.get(profil.risk, sablon["orta"])
        agirliklar = {k: 0.0 for k in VARLIKLAR}
        for k, v in baz.items():
            agirliklar[k] = v
        agirliklar["silver"] = 0.0
        agirliklar["bist"] = 0.0
        agirliklar["crypto"] = 0.0
        t = sum(agirliklar.values())
        if t < 1.0:
            agirliklar["eur_cash"] += 1.0 - t
        adimlar.append(f"KRİZ rejimi: {profil.risk} risk profiline göre defansif şablon.")

    # Profil mutlak tavan
    toplam_riskli = agirliklar["bist"] + agirliklar["crypto"] + agirliklar["silver"]
    if profil.risk == "dusuk" and toplam_riskli > 0.10:
        kes = toplam_riskli - 0.10
        agirliklar["bist"] = min(agirliklar["bist"], 0.05)
        agirliklar["crypto"] = 0.0
        agirliklar["silver"] = min(agirliklar["silver"], 0.05)
        agirliklar["eur_cash"] += kes * 0.6
        agirliklar["gold"] += kes * 0.4
        adimlar.append("Düşük risk profili: volatil pay %10 ile sınırlandı.")

    # Kripto: yalnızca RISK_ON + skor eşiği; aksi halde 0 (rapor tutarlılığı)
    if agirliklar.get("crypto", 0) > 0:
        max_crypto = max_a.get("crypto", 0)
        izin = (
            max_crypto > 0
            and skorlar.get("crypto", 0) >= config.KRIPTO_MIN_SKOR
            and (rejim.rejim == "RISK_ON" or not config.KRIPTO_SADECE_RISK_ON)
        )
        if not izin:
            fark = agirliklar["crypto"]
            agirliklar["crypto"] = 0.0
            agirliklar["eur_cash"] += fark * 0.55
            agirliklar["usd_cash"] += fark * 0.25
            agirliklar["gold"] += fark * 0.20
            adimlar.append(
                f"Kripto payı sıfırlandı ({fark*100:.1f}%) — "
                f"rejim {rejim.rejim} RISK_ON değil veya skor yetersiz."
            )

    t = sum(agirliklar.values())
    agirliklar = {k: v / t for k, v in agirliklar.items()}
    agirliklar = {k: min(v, mutlak_tavan) if k == "tl_deposit" else v for k, v in agirliklar.items()}
    t = sum(agirliklar.values())
    agirliklar = {k: v / t for k, v in agirliklar.items()}

    config.KALAN_GUN = eski_kalan

    tutarlar = {k: config.TOPLAM_EUR * agirliklar[k] for k in VARLIKLAR}
    en_yuksek = max(agirliklar, key=agirliklar.get)

    etiket = config.VARLIK_ETIKETLERI
    satir = ", ".join(
        f"{etiket[k]} %{agirliklar[k]*100:.0f} ({tutarlar[k]:,.0f} EUR)"
        for k in sorted(agirliklar, key=agirliklar.get, reverse=True)
        if agirliklar[k] >= 0.01
    )

    tavsiye = (
        f"ÖNERİ [{rejim.etiket}] · {profil.ozet()}: "
        f"Toplam {config.TOPLAM_EUR:,.0f} EUR için önerilen dağılım — {satir}. "
        f"Öncelikli varlık: {etiket[en_yuksek]}. "
        f"Tranşlar halinde ({config.TRANS_SAYISI} parça) girin."
    )

    return TahsisSonucu(
        agirliklar=agirliklar,
        skorlar=skorlar,
        rejim=rejim,
        tl_karar_adimlari=tl_sonuc.adimlar,
        tl_tavan_oran=tl_tavan,
        adimlar=adimlar,
        uyarilar=uyarilar,
        tavsiye_metni=tavsiye,
        profil=profil,
        profil_notlari=profil_notlari,
        tl_mevduat_reel=tl_mevduat_reel,
        tl_reel_sinirlandi=tl_reel_sinirlandi,
    )
