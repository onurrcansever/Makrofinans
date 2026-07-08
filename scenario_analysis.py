# -*- coding: utf-8 -*-
"""
Senaryo analizi — kur şoku, CDS stresi, TCMB faiz kararı.
Mevcut breakeven / reel getiri / 4 kapı fonksiyonlarını yeniden kullanır.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import List, Optional

import config
from allocation_engine import TahsisSonucu
from breakeven import breakeven_eur_try, profil_mevduat_parametreleri
from decision_engine import karar_ver
from macro_data import MacroSnapshot
from rates_tr import _oran_hesapla
from yapikredi_rates import yapikredi_tl_faizleri


@dataclass
class SenaryoSatir:
    ad: str
    ozet: str
    tablo_baslik: List[str]
    tablo_satirlar: List[List[str]] = field(default_factory=list)


def _portfoy_eur_etkisi(tahsis: TahsisSonucu, tl_eur_etki_pct: float) -> float:
    w = tahsis.agirliklar.get("tl_deposit", 0)
    return w * tl_eur_etki_pct


def _usd_bazli_etf_listesi(tarama=None, birlesik_oneri=None) -> List[str]:
    """Kur şoku notu — sepetteki / tipik USD bazlı ETF'ler."""
    tickers: List[str] = []
    if birlesik_oneri:
        for s in getattr(birlesik_oneri, "arac_dagilim", []) or []:
            if "ETF" not in (getattr(s, "ust_kategori", "") or ""):
                continue
            arac = (getattr(s, "arac", "") or "").strip()
            if arac:
                tickers.append(arac.split()[0].upper().replace(".L", ""))
    if not tickers and tarama and getattr(tarama, "etf_firsatlari", None):
        tickers = [
            (h.revolut_ticker or h.sembol.split(".")[0]).upper().replace(".L", "")
            for h in tarama.etf_firsatlari
            if h.sektor in config.USD_BAZLI_ETF_SEKTORLER
        ]
    if not tickers:
        from etf_universe import REVOLUT_ETFLER
        tickers = [
            e[0].upper().replace(".L", "")
            for e in REVOLUT_ETFLER
            if e[2] in config.USD_BAZLI_ETF_SEKTORLER
        ][:3]
    seen = set()
    out: List[str] = []
    for t in tickers:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _kur_soku(
    snap: MacroSnapshot,
    tahsis: TahsisSonucu,
    vade_gun: int,
    tarama=None,
    birlesik_oneri=None,
) -> SenaryoSatir:
    eur = snap.veri.eur_try or 35.0
    net_tl, gun, kaynak = profil_mevduat_parametreleri(vade_gun, snap.veri.tl_mevduat_brut_faiz)
    be = breakeven_eur_try(eur, net_tl, gun)
    carpan = float(getattr(config, "SENARYO_KUR_SOKU_CARPANI", 1.05))
    sok_kur = be * carpan
    tl_eur_zarar = -((sok_kur / be) - 1.0) * 100
    port_etki = _portfoy_eur_etkisi(tahsis, tl_eur_zarar)
    ozet = (
        f"Profil vadesi ({gun} gün, {kaynak}) başabaş {be:.2f} TRY/EUR — "
        f"vade sonunda kur %{(carpan-1)*100:.0f} üzerine ({sok_kur:.2f}) çıkarsa: "
        f"TL mevduat EUR bazlı ~%{tl_eur_zarar:.1f}, portföy toplam ~%{port_etki:.1f}."
    )
    etf_not = ""
    usd_etfs = _usd_bazli_etf_listesi(tarama=tarama, birlesik_oneri=birlesik_oneri)
    if usd_etfs:
        eur_usd = snap.eur_usd or 1.08
        etf_not = (
            f" USD bazlı ETF ({', '.join(usd_etfs[:4])}): EUR/USD paritesi "
            f"({eur_usd:.2f}) TL kur şokundan bağımsız ek kur riski taşır."
        )
        ozet += etf_not
    return SenaryoSatir(
        ad="Kur şoku",
        ozet=ozet,
        tablo_baslik=["Gösterge", "Mevcut", "Senaryo"],
        tablo_satirlar=[
            ["Profil vadesi (gün)", f"{gun}", f"{gun}"],
            ["EUR/TRY spot", f"{eur:.2f}", f"{eur:.2f}"],
            ["Başa baş kur", f"{be:.2f}", f"{be:.2f}"],
            ["Vade sonu kur", "—", f"{sok_kur:.2f}"],
            ["TL EUR etkisi", "—", f"{tl_eur_zarar:+.1f}%"],
            ["Portföy EUR etkisi", "—", f"{port_etki:+.1f}%"],
        ],
    )


def _cds_stresi(snap: MacroSnapshot, tahsis: TahsisSonucu, vade_gun: int) -> SenaryoSatir:
    from allocation_engine import tahsis_hesapla

    cds_stres = float(getattr(config, "SENARYO_CDS_STRES_BP", 280))
    mevcut_cds = snap.veri.cds_5y_bp or 250
    mevcut_tavan = tahsis.tl_tavan_oran
    mevcut_tl = tahsis.agirliklar.get("tl_deposit", 0)
    veri_stres = deepcopy(snap.veri)
    veri_stres.cds_5y_bp = cds_stres
    stres_karar = karar_ver(veri_stres, vade_gun=vade_gun)
    yeni_tavan = stres_karar.tavan_oran if stres_karar.kapi1_gecti else 0.0

    snap_stres = deepcopy(snap)
    snap_stres.veri = veri_stres
    profil = tahsis.profil
    tahsis_stres = tahsis_hesapla(snap_stres, profil)
    hedef_tl = tahsis_stres.agirliklar.get("tl_deposit", 0)
    mevcut_eur = tahsis.agirliklar.get("eur_cash", 0)
    stres_eur = tahsis_stres.agirliklar.get("eur_cash", 0)
    eur_kayma = (stres_eur - mevcut_eur) * 100
    tavan_baglayici = mevcut_tl >= mevcut_tavan - 0.008

    if abs(hedef_tl - mevcut_tl) < 0.005:
        ozet = (
            f"CDS {cds_stres:.0f} bp stresinde tavan %{mevcut_tavan*100:.0f}→%{yeni_tavan*100:.0f}; "
            f"TL payı %{mevcut_tl*100:.0f}→%{hedef_tl*100:.0f} — "
            f"{'tavan zaten bağlayıcı değil' if not tavan_baglayici else 'skor etkisi sınırlı'}; "
            f"EUR payı {eur_kayma:+.1f} pp kaydı (tam tahsis yeniden hesaplandı)."
        )
    else:
        ozet = (
            f"CDS {cds_stres:.0f} bp stresinde Kapı 2 tavanı %{mevcut_tavan*100:.0f}→"
            f"%{yeni_tavan*100:.0f}; tam tahsis yeniden hesaplandı — "
            f"TL payı ~%{mevcut_tl*100:.0f}→~%{hedef_tl*100:.0f}."
        )
    return SenaryoSatir(
        ad="CDS stresi",
        ozet=ozet,
        tablo_baslik=["", "Mevcut", f"CDS {cds_stres:.0f} bp"],
        tablo_satirlar=[
            ["CDS (bp)", f"{mevcut_cds:.0f}", f"{cds_stres:.0f}"],
            ["TL tavan (4 kapı)", f"%{mevcut_tavan*100:.0f}", f"%{yeni_tavan*100:.0f}"],
            ["Tavan bağlayıcı mı?", "Evet" if tavan_baglayici else "Hayır", "—"],
            ["Önerilen TL payı", f"%{mevcut_tl*100:.0f}", f"%{hedef_tl*100:.0f}"],
            ["EUR payı", f"%{mevcut_eur*100:.0f}", f"%{stres_eur*100:.0f}"],
        ],
    )


def _tcmb_faiz(snap: MacroSnapshot, vade_gun: int) -> SenaryoSatir:
    delta = float(getattr(config, "SENARYO_TCMB_DEGISIM_BP", 300)) / 100.0
    tcmb = snap.veri.tcmb_politika_faizi or 37.0
    enflasyon = snap.enflasyon_tr_yillik or 35.0
    ykb = yapikredi_tl_faizleri()
    satirlar: List[List[str]] = []
    if ykb:
        for etiket, brut, gun in (
            ("TL 3 ay", ykb.tl_3ay_brut, 92),
            ("TL 6 ay", ykb.tl_6ay_brut, 181),
        ):
            baz = _oran_hesapla(etiket, brut, enflasyon, "baz", gun)
            arti = _oran_hesapla(etiket, brut + delta, enflasyon, "+Δ", gun)
            eksi = _oran_hesapla(etiket, max(brut - delta, 0.05), enflasyon, "-Δ", gun)
            satirlar.append([
                etiket,
                f"{baz.reel_yillik:+.1f}",
                f"{arti.reel_yillik:+.1f}",
                f"{eksi.reel_yillik:+.1f}",
            ])
    ozet = (
        f"PPK ±{delta*100:.0f} bp senaryosunda 3/6 ay yerel reel getiri tablosu güncellenir "
        f"(baz TCMB %{tcmb:.1f})."
    )
    return SenaryoSatir(
        ad="TCMB faiz kararı",
        ozet=ozet,
        tablo_baslik=["Vade", "Baz reel", f"+{delta*100:.0f}bp", f"-{delta*100:.0f}bp"],
        tablo_satirlar=satirlar or [["—", "—", "—", "—"]],
    )


def senaryo_analizi_uret(
    snap: MacroSnapshot,
    tahsis: TahsisSonucu,
    vade_gun: Optional[int] = None,
    tarama=None,
    birlesik_oneri=None,
) -> List[SenaryoSatir]:
    from investor_profile import profil_mevduat_vadesi

    if vade_gun is None and tahsis.profil:
        _, vade_gun = profil_mevduat_vadesi(tahsis.profil)
    gun = vade_gun or config.KALAN_GUN
    return [
        _kur_soku(snap, tahsis, gun, tarama=tarama, birlesik_oneri=birlesik_oneri),
        _cds_stresi(snap, tahsis, gun),
        _tcmb_faiz(snap, gun),
    ]
