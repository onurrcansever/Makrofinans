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
from investor_profile import YatirimProfili, profil_degerlendirme, profil_mevduat_vadesi, profil_sinirlari, profil_skor_ayari
from macro_data import MacroSnapshot
from regime import RejimSonucu, rejim_tespit
from regime_hysteresis import rejim_tespit_v2
from regime_stability import rejim_kararli_uygula
from regime_uyum import rejim_gosterim_metni, rejim_kapilarla_uyumla
from girdi_dogrulama import snap_rejim_icin
from rates_tr import mevduat_analizi
from tl_decision_explain import explain_tl_decision, explain_to_dict
from tl_engine import TlKararPaketi, tl_karar_hesapla
from news_sentiment_scan import sentiment_tara
from siyasi_etkin import siyasi_sayim_raporla
from ppk_awareness import ppk_teyit_atla

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
    tl_rejim_sinirlandi: bool = False
    tl_risk_sinirlandi: bool = False
    altin_momentum_sinirlandi: bool = False
    tl_explain: List[dict] = field(default_factory=list)
    tl_baglayici_kisit: str = ""
    tl_baglayici_etiket: str = ""
    tl_oneri_cumlesi: str = ""
    tl_kritik_veto: bool = False
    tl_ppk_bekle: bool = False
    tl_ppk_notu: str = ""
    tl_efektif_tavan: float = 0.0
    rebalance_korundu: bool = False
    # Makro tahsis (sinyal ince ayarı öncesi) — tekrar uygulanabilir köprü
    agirliklar_makro: Dict[str, float] = field(default_factory=dict)
    bist_al_sayisi: int = 0
    bist_sinyal_notu: str = ""


def _skor_sinirla(s: float) -> float:
    return max(0.0, min(100.0, s))


def tl_reel_negatif_max_oran(reel_mev: float) -> float:
    """Profil vadesi mevduat reel getirisine göre TL üst sınırı (0–1)."""
    if reel_mev > config.TL_REEL_NEGATIF_ESIK:
        return config.MUTLAK_TAVAN
    if reel_mev <= config.TL_REEL_COK_NEGATIF_ESIK:
        return config.TL_REEL_COK_NEGATIF_MAX_ORAN
    return config.TL_REEL_NEGATIF_MAX_ORAN


def tl_profil_risk_tavan(profil: YatirimProfili, rejim: str) -> float:
    """
    Risk toleransı × rejim — kısa vadeli reel pozitif carry, düşük riskte sınırlı.
    Faiz avantajı risk profilini ezmemeli.
    """
    if rejim in ("KRIZ", "EM_STRES"):
        return 0.0
    if rejim == "TL_FIRSAT":
        return {
            "dusuk": config.TL_DUSUK_RISK_FIRSAT_MAX,
            "orta": config.TL_ORTA_RISK_FIRSAT_MAX,
            "yuksek": config.TL_YUKSEK_RISK_FIRSAT_MAX,
        }.get(profil.risk, config.TL_ORTA_RISK_FIRSAT_MAX)
    return {
        "dusuk": config.TL_DUSUK_RISK_MAX_ORAN,
        "orta": config.TL_REJIM_DISI_MAX_ORAN,
        "yuksek": config.TL_YUKSEK_RISK_DISI_MAX,
    }.get(profil.risk, config.TL_REJIM_DISI_MAX_ORAN)


def _fazlalik_dagit(agirliklar: Dict[str, float], fark: float, dagilim: Tuple[float, float, float]) -> None:
    eur, gold, usd = dagilim
    agirliklar["eur_cash"] += fark * eur
    agirliklar["gold"] += fark * gold
    agirliklar["usd_cash"] += fark * usd


def _tl_fazlalik_dagit(agirliklar: Dict[str, float], fark: float) -> None:
    _fazlalik_dagit(agirliklar, fark, (0.55, 0.30, 0.15))


def _varlik_skorlari(
    snap: MacroSnapshot, rejim: RejimSonucu, profil: Optional[YatirimProfili] = None
) -> Dict[str, float]:
    v = snap.veri
    skor = dict(config.TEMEL_SKORLAR)

    from reel_hesap import reel_getiri
    cds = v.cds_5y_bp or 300
    enflasyon = snap.enflasyon_tr_yillik or 35.0
    tcmb = v.tcmb_politika_faizi or (v.tl_mevduat_brut_faiz or 0.4) * 100
    reel_faiz = reel_getiri(tcmb, enflasyon)
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


def _rebalance_deadband(
    yeni: Dict[str, float],
    eski: Optional[Dict[str, float]],
    esik: float,
) -> tuple:
    """Küçük sapmada önceki ağırlığı koru — aşırı işlem / nokta hedef hissi azaltır."""
    if not eski or esik <= 0:
        return yeni, False
    try:
        max_d = max(abs(float(yeni.get(k, 0)) - float(eski.get(k, 0) or 0)) for k in VARLIKLAR)
    except (TypeError, ValueError):
        return yeni, False
    if max_d < esik:
        koru = {k: float(eski.get(k, 0) or 0) for k in VARLIKLAR}
        t = sum(koru.values()) or 1.0
        return {k: koru[k] / t for k in VARLIKLAR}, True
    return yeni, False


def tahsis_hesapla(
    snap: MacroSnapshot,
    profil: Optional[YatirimProfili] = None,
    ham_rejim: bool = False,
    onceki_agirliklar: Optional[Dict[str, float]] = None,
) -> TahsisSonucu:
    profil = profil or YatirimProfili()
    min_a, max_a, kalan_gun, mutlak_tavan = profil_sinirlari(profil)

    # TL kapı hesabı için vadeye göre kalan gün
    eski_kalan = config.KALAN_GUN
    config.KALAN_GUN = kalan_gun

    if ham_rejim:
        rejim = rejim_tespit(snap)
        ham_sonuc = rejim
        adimlar_pre = ["[Backtest] Ham rejim — histerezis/geçiş bölgesi devre dışı"]
        sentiment = sentiment_tara(canli=False)
        siyasi_sayim_raporla(snap, sentiment)
        backtest_mod = True
    else:
        sentiment = sentiment_tara(canli=snap.veri_kaynak == "canli")
        siyasi_sayim_raporla(snap, sentiment)
        girdi = getattr(snap, "girdi_dogrulama", None)
        ham_sonuc = rejim_tespit(snap_rejim_icin(snap))
        if girdi and girdi.rejim_donduruldu:
            rejim = rejim_kararli_uygula(snap_rejim_icin(snap), girdi)
        else:
            rejim = rejim_tespit_v2(
                snap_rejim_icin(snap),
                etkin_siyasi=sentiment.etkin_siyasi,
                ham_siyasi=sentiment.siyasi.haber_sayisi,
                atla_teyit=ppk_teyit_atla(),
            )
        adimlar_pre = [rejim.degisim_gerekce] if rejim.degisim_gerekce else []
        adimlar_pre.extend(
            a for a in ham_sonuc.adimlar if "askıya" in a and a not in adimlar_pre
        )
        backtest_mod = False

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
    tl_rejim_sinirlandi = False
    tl_risk_sinirlandi = False
    altin_momentum_sinirlandi = False

    # Mevcut 4 kapılı TL tavanını uygula (v2: duygu + histerezis + explain)
    onceki_tcmb = (snap.kaynak_haritasi or {}).get("tcmb_faiz_onceki")
    onceki_faiz = float(onceki_tcmb) if onceki_tcmb else None

    tl_paket: TlKararPaketi = tl_karar_hesapla(
        snap.veri,
        vade_gun=mevduat_vade_gun,
        sentiment=sentiment,
        canli_sentiment=False,
        onceki_tcmb_faiz=onceki_faiz,
    )
    tl_sonuc = tl_paket.sonuc
    adimlar.extend([f"[TL kapı] {a}" for a in tl_sonuc.adimlar])
    uyarilar.extend(tl_sonuc.uyarilar)
    if tl_paket.kritik_veto:
        uyarilar.append("[KRİTİK] Olay vetosu aktif")

    if not backtest_mod:
        rejim = rejim_kapilarla_uyumla(rejim, ham_sonuc, snap, tl_paket)

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

    if rejim.rejim != "TL_FIRSAT" and agirliklar["tl_deposit"] > config.TL_REJIM_DISI_MAX_ORAN:
        rejim_tavan = min(tl_tavan, config.TL_REJIM_DISI_MAX_ORAN)
        skorlar["tl_deposit"] = min(skorlar["tl_deposit"], config.TL_REJIM_DISI_SKOR_TAVAN)
        fark = agirliklar["tl_deposit"] - rejim_tavan
        agirliklar["tl_deposit"] = rejim_tavan
        _tl_fazlalik_dagit(agirliklar, fark)
        tl_rejim_sinirlandi = True
        adimlar.append(
            f"[Rejim {rejim.etiket}] TL_FIRSAT değil — TL payı "
            f"%{config.TL_REJIM_DISI_MAX_ORAN*100:.0f} ile sınırlandı; "
            f"fazla %{fark*100:.1f} EUR/altın/USD'ye aktarıldı."
        )

    risk_tavan = tl_profil_risk_tavan(profil, rejim.rejim)
    if agirliklar["tl_deposit"] > risk_tavan:
        fark = agirliklar["tl_deposit"] - risk_tavan
        agirliklar["tl_deposit"] = risk_tavan
        _tl_fazlalik_dagit(agirliklar, fark)
        tl_risk_sinirlandi = True
        adimlar.append(
            f"[Risk {profil.risk}] TL carry sınırı %{risk_tavan*100:.0f} — "
            f"faiz avantajı risk toleransını aşmamalı; fazla %{fark*100:.1f} EUR/altın/USD'ye aktarıldı."
        )

    altin_3m = snap.altin_3m_degisim
    if altin_3m is not None and altin_3m < config.ALTIN_MOMENTUM_ESIK:
        skorlar["gold"] = min(skorlar["gold"], config.ALTIN_MOMENTUM_SKOR_TAVAN)

    if rejim.rejim == "KRIZ":
        # TL tüm profillerde 0 — Kapı 1 / kriz ile tutarlı (yüksek riskte bile %5 TL yok)
        sablon = {
            "dusuk": {"eur_cash": 0.45, "usd_cash": 0.25, "gold": 0.30},
            "orta": {"eur_cash": 0.42, "usd_cash": 0.23, "gold": 0.35},
            "yuksek": {"eur_cash": 0.40, "usd_cash": 0.25, "gold": 0.35},
        }
        baz = sablon.get(profil.risk, sablon["orta"])
        agirliklar = {k: 0.0 for k in VARLIKLAR}
        for k, v in baz.items():
            agirliklar[k] = v
        agirliklar["silver"] = 0.0
        agirliklar["bist"] = 0.0
        agirliklar["crypto"] = 0.0
        agirliklar["tl_deposit"] = 0.0
        t = sum(agirliklar.values())
        if t < 1.0:
            agirliklar["eur_cash"] += 1.0 - t
        adimlar.append(
            f"KRİZ rejimi: {profil.risk} risk — defansif şablon (TL=0, BIST/kripto kapalı)."
        )

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

    tl_efektif_tavan = min(mutlak_tavan, tl_tavan, risk_tavan)
    if rejim.rejim != "TL_FIRSAT":
        tl_efektif_tavan = min(tl_efektif_tavan, config.TL_REJIM_DISI_MAX_ORAN)
        tl_efektif_tavan = min(tl_efektif_tavan, tl_profil_risk_tavan(profil, rejim.rejim))
    if tl_mevduat_reel is not None and tl_mevduat_reel <= config.TL_REEL_NEGATIF_ESIK:
        tl_efektif_tavan = min(tl_efektif_tavan, tl_reel_negatif_max_oran(tl_mevduat_reel))

    if agirliklar["tl_deposit"] > tl_efektif_tavan:
        fark = agirliklar["tl_deposit"] - tl_efektif_tavan
        agirliklar["tl_deposit"] = tl_efektif_tavan
        _tl_fazlalik_dagit(agirliklar, fark)

    altin_3m = snap.altin_3m_degisim
    if altin_3m is not None and altin_3m < config.ALTIN_MOMENTUM_ESIK:
        max_g = config.ALTIN_MOMENTUM_MAX_ORAN
        if agirliklar["gold"] > max_g:
            fark = agirliklar["gold"] - max_g
            agirliklar["gold"] = max_g
            _fazlalik_dagit(agirliklar, fark, (0.50, 0.0, 0.50))
            altin_momentum_sinirlandi = True
            adimlar.append(
                f"[Altın momentum {altin_3m:+.1f}% 3A] Pay "
                f"%{max_g*100:.0f} ile sınırlandı — kademeli alım önerilir."
            )

    t = sum(agirliklar.values())
    agirliklar = {k: v / t for k, v in agirliklar.items()}

    if (
        profil.risk == "yuksek"
        and profil.vade == "kisa"
        and skorlar.get("bist", 0) > skorlar.get("silver", 0) + 8
        and agirliklar["silver"] > agirliklar["bist"] + 0.015
    ):
        hedef_bist = min(max_a.get("bist", 0.12), agirliklar["bist"] + 0.03)
        kay = min(
            agirliklar["silver"] - 0.05,
            hedef_bist - agirliklar["bist"],
        )
        if kay > 0.004:
            agirliklar["silver"] -= kay
            agirliklar["bist"] += kay
            adimlar.append(
                f"[Profil] Yüksek risk + 0–12 ay: gümüşten BIST'e %{kay*100:.1f} kaydırıldı "
                f"(BIST skoru {skorlar['bist']:.0f} > gümüş {skorlar['silver']:.0f})."
            )
            t = sum(agirliklar.values())
            agirliklar = {k: v / t for k, v in agirliklar.items()}

    # Ülke riski bütçesi (düşük risk): TL + BIST birlikte sınırlı
    if profil.risk == "dusuk":
        tr_budce = 0.18
        tr_toplam = agirliklar["tl_deposit"] + agirliklar["bist"]
        if tr_toplam > tr_budce + 1e-6:
            kes = tr_toplam - tr_budce
            # Önce BIST'ten kes
            bist_kes = min(agirliklar["bist"], kes)
            agirliklar["bist"] -= bist_kes
            kalan_kes = kes - bist_kes
            if kalan_kes > 0:
                agirliklar["tl_deposit"] = max(0.0, agirliklar["tl_deposit"] - kalan_kes)
            agirliklar["eur_cash"] += kes * 0.65
            agirliklar["gold"] += kes * 0.35
            adimlar.append(
                f"[Ülke riski] Düşük risk: TL+BIST ≤%{tr_budce*100:.0f} "
                f"(fazla %{kes*100:.1f} EUR/altına)."
            )
            t = sum(agirliklar.values())
            agirliklar = {k: v / t for k, v in agirliklar.items()}

    esik_reb = float(getattr(config, "REBALANCE_MIN_PP", 0.03) or 0.03)
    agirliklar, rebalance_korundu = _rebalance_deadband(
        agirliklar, onceki_agirliklar, esik_reb,
    )
    if rebalance_korundu:
        adimlar.append(
            f"[Rebalance] Değişim <%{esik_reb*100:.0f} pp — önceki dağılım korundu "
            "(aşırı işlem önlemi)."
        )

    config.KALAN_GUN = eski_kalan

    tutarlar = {k: config.TOPLAM_EUR * agirliklar[k] for k in VARLIKLAR}
    en_yuksek = max(agirliklar, key=agirliklar.get)

    etiket = config.VARLIK_ETIKETLERI
    satir = ", ".join(
        f"{etiket[k]} %{agirliklar[k]*100:.0f} ({tutarlar[k]:,.0f} EUR)"
        for k in sorted(agirliklar, key=agirliklar.get, reverse=True)
        if agirliklar[k] >= 0.01
    )

    tl_oneri_pct = agirliklar["tl_deposit"] * 100
    tl_explain = explain_tl_decision(
        snap.veri,
        vade_gun=mevduat_vade_gun,
        sentiment=tl_paket.sentiment,
        reel_pp=tl_mevduat_reel,
        profil_tavan=risk_tavan,
        allocation_pay=agirliklar["tl_deposit"],
    )
    tavsiye = (
        f"ÖNERİ [{rejim.etiket}] · {profil.ozet()}: "
        f"Toplam {config.TOPLAM_EUR:,.0f} EUR için önerilen dağılım — {satir}. "
        f"TL öneri ~%{tl_oneri_pct:.0f} · etkin tavan %{tl_efektif_tavan*100:.0f} "
        f"({tl_explain.baglayici_etiket or tl_explain.baglayici_kisit or '—'}). "
        f"Öncelikli: {etiket[en_yuksek]}. "
        f"Tranş ({config.TRANS_SAYISI} parça); küçük sapmada yeniden dengelemeyin."
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
        tl_rejim_sinirlandi=tl_rejim_sinirlandi,
        tl_risk_sinirlandi=tl_risk_sinirlandi,
        altin_momentum_sinirlandi=altin_momentum_sinirlandi,
        tl_explain=explain_to_dict(tl_explain),
        tl_baglayici_kisit=tl_explain.baglayici_kisit,
        tl_baglayici_etiket=tl_explain.baglayici_etiket,
        tl_oneri_cumlesi=tl_explain.oneri_cumlesi,
        tl_kritik_veto=tl_paket.kritik_veto,
        tl_ppk_bekle=tl_paket.ppk_bekle,
        tl_ppk_notu=tl_paket.ppk_notu,
        tl_efektif_tavan=tl_efektif_tavan,
        rebalance_korundu=rebalance_korundu,
        agirliklar_makro={k: float(v) for k, v in agirliklar.items()},
        bist_al_sayisi=0,
        bist_sinyal_notu="",
    )


def al_aday_sayisi(hisseler) -> int:
    """Signal Engine v2 BUY/STRONG_BUY adet (karantina hariç)."""
    n = 0
    for h in hisseler or []:
        if getattr(h, "veri_quarantine", False):
            continue
        if (getattr(h, "signal_v2_code", None) or "") in ("BUY", "STRONG_BUY"):
            n += 1
    return n


def tahsis_bist_sinyal_ayarla(sonuc: TahsisSonucu, al_sayisi: int) -> bool:
    """Tarama AL sayısına göre BIST dilimini ince ayarlar (makro iskelet korunur).

    - KRIZ / EM_STRES: dokunulmaz
    - AL ≥ 1: makro BIST payı korunur (artırılmaz)
    - AL = 0: BIST ← min(makro×0.5, BIST_SINYAL_YOK_MAX); fazla → EUR/altın

    Returns True if weights or note changed.
    """
    al_n = max(0, int(al_sayisi or 0))
    rejim = getattr(getattr(sonuc, "rejim", None), "rejim", "") or ""
    base = dict(sonuc.agirliklar_makro) if sonuc.agirliklar_makro else dict(sonuc.agirliklar)
    if not sonuc.agirliklar_makro:
        sonuc.agirliklar_makro = {k: float(v) for k, v in base.items()}

    onceki_bist = float(sonuc.agirliklar.get("bist", 0) or 0)
    onceki_not = sonuc.bist_sinyal_notu or ""
    onceki_n = int(getattr(sonuc, "bist_al_sayisi", 0) or 0)

    a = {k: float(base.get(k, 0.0)) for k in VARLIKLAR}
    notu = ""
    adim = None

    if rejim in ("KRIZ", "EM_STRES"):
        notu = (
            f"BIST sinyal ayarı yok — rejim {rejim} (defansif şablon)."
        )
    elif al_n >= 1:
        notu = (
            f"Tarama: {al_n} AL/GÜÇLÜ AL — BIST dilimi makro öneride korundu "
            f"(%{a.get('bist', 0)*100:.0f})."
        )
    else:
        carpan = float(getattr(config, "BIST_SINYAL_YOK_CARPAN", 0.50) or 0.50)
        tavan = float(getattr(config, "BIST_SINYAL_YOK_MAX", 0.04) or 0.04)
        eski = float(a.get("bist", 0.0) or 0.0)
        hedef = min(eski * carpan, tavan)
        if eski > hedef + 1e-9:
            fark = eski - hedef
            a["bist"] = hedef
            a["eur_cash"] = a.get("eur_cash", 0.0) + fark * 0.60
            a["gold"] = a.get("gold", 0.0) + fark * 0.40
            notu = (
                f"Tarama: AL yok — BIST %{eski*100:.0f} → %{hedef*100:.0f} "
                f"(fazla EUR/altına; hisse onayına kadar temkin)."
            )
            adim = f"[Sinyal köprüsü] {notu}"
        else:
            notu = (
                f"Tarama: AL yok — BIST zaten düşük (%{eski*100:.0f}); ek kesinti yok."
            )

    t = sum(a.values()) or 1.0
    a = {k: v / t for k, v in a.items()}
    sonuc.agirliklar = a
    sonuc.bist_al_sayisi = al_n
    sonuc.bist_sinyal_notu = notu

    # Adım listesinde tek sinyal satırı tut
    adimlar = list(sonuc.adimlar or [])
    adimlar = [x for x in adimlar if not str(x).startswith("[Sinyal köprüsü]")]
    if adim:
        adimlar.append(adim)
    sonuc.adimlar = adimlar

    degisti = (
        abs(float(a.get("bist", 0)) - onceki_bist) > 1e-9
        or notu != onceki_not
        or al_n != onceki_n
    )
    return degisti
