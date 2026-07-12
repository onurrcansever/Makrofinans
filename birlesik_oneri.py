# -*- coding: utf-8 -*-
"""
Birleşik portföy önerisi — makro tahsis + TEFAS + ETF + BIST + kıymetli maden.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import config
from allocation_engine import TahsisSonucu, VARLIKLAR
from bist_sepet import bist_sepet_sec
from etf_universe import ETF_ETIKET, REVOLUT_ETFLER, etf_oncelik
from investor_profile import VADE_GUN, YatirimProfili, profil_mevduat_vadesi, vade_cok_kisa_mi, vade_kisa_mi
from kullanici_portfoy import KullaniciPortfoy, MevcutPozisyon
from macro_data import MacroSnapshot
from tefas_data import TefasTaramaSonuc, yk_fonlari_performans
from tefas_skor import fonlari_skorla, top_oneri


@dataclass
class OneriSatir:
    sinif: str
    baslik: str
    detay: str
    tutar: float
    para: str
    donem: str  # BUGUN | VADE
    oncelik: int  # 1 yüksek
    etiket: str


@dataclass
class HedefSatir:
    kategori: str
    arac: str
    agirlik_pct: float
    tutar: float
    para: str


@dataclass
class AracDagilimSatir:
    ust_kategori: str
    arac: str
    aciklama: str
    portfoy_pct: float
    kategori_ici_pct: float
    tutar: float
    para: str
    etiket: str = ""


@dataclass
class BirlesikOneri:
    bugun: List[OneriSatir] = field(default_factory=list)
    vade: List[OneriSatir] = field(default_factory=list)
    hedef_tablo: List[HedefSatir] = field(default_factory=list)
    arac_dagilim: List[AracDagilimSatir] = field(default_factory=list)
    mevcut_notlar: List[str] = field(default_factory=list)
    grafik_mevcut: Dict[str, float] = field(default_factory=dict)
    grafik_hedef: Dict[str, float] = field(default_factory=dict)
    ozet: str = ""


def _tutar_pb(tutar_eur: float, pb: str, eur_try: float) -> tuple:
    if pb == "TL" and eur_try > 0:
        return tutar_eur * eur_try, "TL"
    return tutar_eur, "EUR"


def _etf_oneri(rejim: str, n: int = 2) -> List[tuple]:
    sira = sorted(REVOLUT_ETFLER, key=lambda e: etf_oncelik(e[2], rejim))
    return [(e[4], e[1], e[2]) for e in sira[:n]]


def _skorla_bol(
    adaylar: List[tuple],
    kategori_tutar_eur: float,
    kategori_portfoy_pct: float,
    pb: str,
    eur_try: float,
    ust_kategori: str,
) -> List[AracDagilimSatir]:
    """Aday listesi: (arac, aciklama, skor, etiket) — skor ağırlıklı kategori içi dağılım."""
    if not adaylar or kategori_tutar_eur <= 0:
        return []
    skorlar = [max(float(s[2]), 1.0) for s in adaylar]
    top_skor = sum(skorlar)
    rows: List[AracDagilimSatir] = []
    for (arac, aciklama, skor, etiket), agirlik in zip(adaylar, skorlar):
        pay = agirlik / top_skor
        tut_eur = kategori_tutar_eur * pay
        tut, p = _tutar_pb(tut_eur, pb, eur_try)
        rows.append(
            AracDagilimSatir(
                ust_kategori=ust_kategori,
                arac=arac,
                aciklama=aciklama,
                portfoy_pct=round(kategori_portfoy_pct * pay, 2),
                kategori_ici_pct=round(pay * 100, 1),
                tutar=tut,
                para=p,
                etiket=etiket,
            )
        )
    return rows


def _sira_bol(
    adaylar: List[tuple],
    kategori_tutar_eur: float,
    kategori_portfoy_pct: float,
    pb: str,
    eur_try: float,
    ust_kategori: str,
    agirliklar: Optional[List[float]] = None,
) -> List[AracDagilimSatir]:
    """Sabit oranlı kategori içi dağılım (ETF öncelik sırası vb.)."""
    if not adaylar or kategori_tutar_eur <= 0:
        return []
    if agirliklar is None:
        n = len(adaylar)
        agirliklar = [1.0 / n] * n
    top = sum(agirliklar) or 1.0
    rows: List[AracDagilimSatir] = []
    for (arac, aciklama, _skor, etiket), w in zip(adaylar, agirliklar):
        pay = w / top
        tut_eur = kategori_tutar_eur * pay
        tut, p = _tutar_pb(tut_eur, pb, eur_try)
        rows.append(
            AracDagilimSatir(
                ust_kategori=ust_kategori,
                arac=arac,
                aciklama=aciklama,
                portfoy_pct=round(kategori_portfoy_pct * pay, 2),
                kategori_ici_pct=round(pay * 100, 1),
                tutar=tut,
                para=p,
                etiket=etiket,
            )
        )
    return rows


def _ozet_arac_metni(satirlar: List[AracDagilimSatir]) -> str:
    if not satirlar:
        return "—"
    return " · ".join(
        f"{s.arac} %{s.kategori_ici_pct:.0f}" for s in satirlar[:4]
    )


def _dagilim_toplam(satirlar: List[AracDagilimSatir], pb: str, eur_try: float) -> tuple:
    if not satirlar:
        return 0.0, pb, 0.0
    toplam_eur = 0.0
    for s in satirlar:
        if s.para == "TL" and eur_try > 0:
            toplam_eur += s.tutar / eur_try
        else:
            toplam_eur += s.tutar
    pct = round(sum(s.portfoy_pct for s in satirlar), 1)
    tut, p = _tutar_pb(toplam_eur, pb, eur_try)
    return tut, p, pct


def _bist_sepet_aday(tarama, profil: YatirimProfili, bist_w: float, varlik_store=None):
    """Geriye dönük uyumluluk — bist_sepet.bist_sepet_sec sarmalayıcı."""
    adaylar, _ = bist_sepet_sec(tarama, profil, bist_w, varlik_store)
    return adaylar


def _bist_hedef_arac_metni(
    bist_d: List[AracDagilimSatir],
    *,
    tarama_yapildi: bool,
) -> str:
    if bist_d:
        isimler = ", ".join(s.arac.replace(".IS", "") for s in bist_d)
        return f"{isimler} — AL (teyit edildi)"
    if not tarama_yapildi:
        return "Tarama bekleniyor…"
    return "Bugün AL (UYGUN) BIST adayı yok"


def _bist_payini_dagit(agirliklar: Dict[str, float]) -> Dict[str, float]:
    """AL BIST adayı yoksa bist payını diğer sınıflara orantılı dağıt."""
    out = dict(agirliklar)
    freed = out.get("bist", 0.0)
    if freed < 0.005:
        out["bist"] = 0.0
        return out
    out["bist"] = 0.0
    keys = [k for k in VARLIKLAR if k != "bist" and out.get(k, 0) >= 0.005]
    total = sum(out.get(k, 0) for k in keys)
    if total <= 0:
        return out
    for k in keys:
        out[k] = out.get(k, 0) + freed * (out.get(k, 0) / total)
    return out


def _hedef_tablo_olustur(
    tahsis: TahsisSonucu,
    profil: YatirimProfili,
    toplam_eur: float,
    pb: str,
    eur_try: float,
    arac_dagilim: List[AracDagilimSatir],
    tarama_yapildi: bool = False,
    agirliklar: Optional[Dict[str, float]] = None,
) -> List[HedefSatir]:
    by_kat: Dict[str, List[AracDagilimSatir]] = {}
    for s in arac_dagilim:
        by_kat.setdefault(s.ust_kategori, []).append(s)

    _, vade_gun = profil_mevduat_vadesi(profil)

    w_map = agirliklar if agirliklar is not None else tahsis.agirliklar

    rows: List[HedefSatir] = []
    for key in VARLIKLAR:
        w = w_map.get(key, 0)
        if w < 0.005:
            continue
        kat = config.VARLIK_ETIKETLERI.get(key, key)
        if key == "eur_cash":
            kat = "EUR nakit / mevduat"
        elif key == "usd_cash":
            kat = "USD nakit / mevduat"
        elif key == "tl_deposit":
            kat = "TL vadeli mevduat"
        elif key == "bist":
            kat = "BIST 100 (hisse)"
        tut, p = _tutar_pb(toplam_eur * w, pb, eur_try)

        if key == "tl_deposit":
            arac = f"Banka vadeli hesap (~{vade_gun} gün)"
        elif key == "eur_cash":
            arac = "EUR vadeli mevduat veya nakit (banka)"
        elif key == "usd_cash":
            arac = "USD vadeli mevduat veya nakit (banka)"
        elif key == "bist":
            bist_d = by_kat.get("BIST 100 (hisse)", [])
            arac = _bist_hedef_arac_metni(bist_d, tarama_yapildi=tarama_yapildi)
        elif key == "gold":
            arac = "Altın (ons / gram)"
        elif key == "silver":
            arac = "Gümüş"
        elif key == "crypto":
            arac = "Bitcoin (BTC)"
        else:
            arac = "—"

        rows.append(
            HedefSatir(
                kategori=kat,
                arac=arac,
                agirlik_pct=round(w * 100, 1),
                tutar=tut,
                para=p,
            )
        )

    for kat_adi in ("TEFAS fon", "ETF (hisse senedi)"):
        grp = by_kat.get(kat_adi, [])
        if not grp:
            continue
        tut, p, pct = _dagilim_toplam(grp, pb, eur_try)
        rows.append(
            HedefSatir(
                kategori=kat_adi,
                arac=_ozet_arac_metni(grp) + " — detay tablosu",
                agirlik_pct=pct,
                tutar=tut,
                para=p,
            )
        )

    rows.sort(key=lambda r: -r.agirlik_pct)
    return rows


def _mevcut_grafik(kp: KullaniciPortfoy, eur_try: float) -> Dict[str, float]:
    if not kp.pozisyonlar:
        return {}
    toplam_tl = kp.toplam_tl(eur_try)
    if toplam_tl <= 0:
        return {}
    out: Dict[str, float] = {}
    for p in kp.pozisyonlar:
        tl = p.tutar if p.para_birimi == "TL" else p.tutar * eur_try
        anahtar = {
            "tl_mevduat": config.VARLIK_ETIKETLERI.get("tl_deposit", "TL mevduat (TR)"),
            "tefas": "TEFAS fon",
            "nakit_eur": config.VARLIK_ETIKETLERI.get("eur_cash", "EUR mevduat"),
            "nakit_usd": config.VARLIK_ETIKETLERI.get("usd_cash", "USD mevduat"),
            "nakit_tl": config.VARLIK_ETIKETLERI.get("tl_deposit", "TL mevduat (TR)"),
        }.get(p.tur, p.tur)
        out[anahtar] = out.get(anahtar, 0.0) + tl / toplam_tl * 100.0
    return out


def birlesik_oneri_olustur(
    snap: MacroSnapshot,
    tahsis: TahsisSonucu,
    profil: YatirimProfili,
    kp: KullaniciPortfoy,
    mevduat_reel: Optional[float] = None,
    tarama=None,
    tefas_ham: Optional[TefasTaramaSonuc] = None,
    *,
    tefas_istek: bool = True,
    varlik_store=None,
) -> BirlesikOneri:
    eur_try = snap.veri.eur_try or 35.0
    toplam_eur = kp.toplam_eur(eur_try)
    rejim = tahsis.rejim.rejim
    vade_gun = VADE_GUN.get(profil.vade, 365)
    pb = kp.para_birimi

    sonuc = BirlesikOneri()
    sonuc.grafik_mevcut = _mevcut_grafik(kp, eur_try)
    arac_dagilim: List[AracDagilimSatir] = []
    agirlik_efektif = dict(tahsis.agirliklar)

    tl_w = tahsis.agirliklar.get("tl_deposit", 0)
    bist_w = tahsis.agirliklar.get("bist", 0)
    eur_w = tahsis.agirliklar.get("eur_cash", 0)
    usd_w = tahsis.agirliklar.get("usd_cash", 0)

    # Mevcut pozisyon değerlendirme
    mev = kp.mevcut_tl_mevduat()
    if mev:
        net = mev.brut_faiz * (1 - 0.15) if mev.brut_faiz > 1 else mev.brut_faiz * 0.85
        sonuc.mevcut_notlar.append(
            f"Mevcut: **{mev.banka or 'Banka'}** {mev.tutar:,.0f} TL · "
            f"{mev.vade_gun} gün %{mev.brut_faiz:.1f} brüt mevduat"
        )
        if mevduat_reel is not None and net > mevduat_reel + 1:
            sonuc.mevcut_notlar.append(
                f"Mevduatınız (net ~%{net:.1f}) reel getiri açısından **güçlü** — "
                f"vade bitene kadar tutmak mantıklı olabilir."
            )
            sonuc.bugun.append(
                OneriSatir(
                    sinif="tl_mevduat",
                    baslik="Mevcut vadeli hesap",
                    detay=f"{mev.banka} {mev.vade_gun}g %{mev.brut_faiz:.0f} brüt — vade dolana kadar",
                    tutar=mev.tutar,
                    para="TL",
                    donem="BUGUN",
                    oncelik=1,
                    etiket="TUT",
                )
            )
        elif vade_kisa_mi(profil.vade):
            sonuc.mevcut_notlar.append(
                "Vade bitince aşağıdaki **hedef dağılıma** göre yeniden değerlendirme yapılabilir."
            )

    # TEFAS — skor ağırlıklı kategori içi dağılım (ağır; yalnızca tefas_istek=True)
    if tefas_istek:
        try:
            ham = tefas_ham if tefas_ham is not None else yk_fonlari_performans(gun=90, sadece_yk=True)
            if not ham.hata:
                scored = fonlari_skorla(ham, profil, rejim=rejim, mevduat_reel=mevduat_reel)
                if vade_cok_kisa_mi(profil.vade):
                    fon_aday = top_oneri(
                        scored,
                        n=3,
                        kategoriler=("para_piyasasi", "borclanma", "katilim"),
                        kisa_vade=True,
                    )
                    if fon_aday:
                        sonuc.mevcut_notlar.append(
                            "TEFAS (0–6 ay): **para piyasası / borçlanma** — "
                            "hisse yoğun, değişken ve karma fonlar (YAK vb.) hariç."
                        )
                else:
                    fon_aday = top_oneri(scored, n=3)
                if fon_aday:
                    tefas_pay = max(tl_w, 0.05) * 0.35
                    tefas_tutar_eur = toplam_eur * tefas_pay
                    tefas_pct = tefas_pay * 100
                    adaylar = []
                    for f in fon_aday:
                        det = f.kisa_ad
                        if f.dagilim_ozet:
                            det += f" · {f.dagilim_ozet}"
                        adaylar.append((f.kod, det, f.skor or 10.0, f.oneri))
                    tefas_satirlar = _skorla_bol(
                        adaylar, tefas_tutar_eur, tefas_pct, pb, eur_try, "TEFAS fon",
                    )
                    arac_dagilim.extend(tefas_satirlar)
                    for s in tefas_satirlar:
                        sonuc.vade.append(
                            OneriSatir(
                                sinif="tefas",
                                baslik=s.arac,
                                detay=s.aciklama,
                                tutar=s.tutar,
                                para=s.para,
                                donem="VADE",
                                oncelik=1 if s.etiket == "GUCLU" else 2,
                                etiket=s.etiket,
                            )
                        )
        except Exception:
            pass

    # ETF — öncelik sırasına göre 55/45 (çok kısa vadede hisse ETF kapalı)
    if eur_w + usd_w >= 0.08 and not vade_cok_kisa_mi(profil.vade):
        etf_list = _etf_oneri(rejim, n=2)
        if etf_list:
            etf_pay = max(eur_w, usd_w) * 0.45
            etf_tutar_eur = toplam_eur * etf_pay
            etf_pct = etf_pay * 100
            adaylar = [
                (ticker, f"{ad} ({ETF_ETIKET.get(sektor, sektor)})", 10 - i, "ETF")
                for i, (ticker, ad, sektor) in enumerate(etf_list)
            ]
            agirliklar = [0.55, 0.45][: len(adaylar)]
            etf_satirlar = _sira_bol(
                adaylar, etf_tutar_eur, etf_pct, pb, eur_try,
                "ETF (hisse senedi)", agirliklar=agirliklar,
            )
            arac_dagilim.extend(etf_satirlar)
            for s in etf_satirlar:
                sonuc.vade.append(
                    OneriSatir(
                        sinif="etf",
                        baslik=f"ETF {s.arac}",
                        detay=s.aciklama,
                        tutar=s.tutar,
                        para=s.para,
                        donem="VADE",
                        oncelik=2,
                        etiket="ETF",
                    )
                )
    elif vade_cok_kisa_mi(profil.vade) and (eur_w + usd_w) >= 0.08:
        sonuc.mevcut_notlar.append(
            "Profil vadesi **0–6 ay**: hisse ETF (CSPX/VUAA vb.) önerilmez — "
            "EUR/USD payı **nakit veya kısa vadeli mevduat** olarak tutulmalı; "
            "BIST/kripto ile aynı vade mantığı."
        )

    # BIST — Karar=AL (UYGUN) hisseler, skor sırası (Varlıklarım'dan bağımsız)
    bist_aday_var = False
    tarama_hazir = bool(tarama and getattr(tarama, "hisseler", None))
    if tarama and bist_w >= 0.03:
        adaylar_h, bist_notlar = bist_sepet_sec(tarama, profil, bist_w, varlik_store)
        for n in bist_notlar:
            sonuc.mevcut_notlar.append(n)
        if adaylar_h:
            bist_aday_var = True
            bist_tutar_eur = toplam_eur * bist_w
            bist_pct = bist_w * 100
            skor_aday = [
                (h.sembol, (h.ad or "")[:50], float(h.skor or 50), getattr(h, "alim_uygun", "IZLE"))
                for h in adaylar_h
            ]
            bist_satirlar = _skorla_bol(
                skor_aday, bist_tutar_eur, bist_pct, pb, eur_try, "BIST 100 (hisse)",
            )
            arac_dagilim.extend(bist_satirlar)
            for s in bist_satirlar:
                sonuc.vade.append(
                    OneriSatir(
                        sinif="bist",
                        baslik=s.arac,
                        detay=s.aciklama,
                        tutar=s.tutar,
                        para=s.para,
                        donem="VADE",
                        oncelik=3,
                        etiket=s.etiket,
                    )
                )

    if tarama_hazir and bist_w >= 0.005 and not bist_aday_var:
        agirlik_efektif = _bist_payini_dagit(agirlik_efektif)
        sonuc.mevcut_notlar.append(
            f"Uygun BIST hissesi olmadığı için makro BIST payı (**%{bist_w * 100:.1f}**) "
            "mevduat, altın ve dövize yeniden dağıtıldı."
        )

    sonuc.grafik_hedef = {
        config.VARLIK_ETIKETLERI.get(k, k): agirlik_efektif.get(k, 0) * 100
        for k in VARLIKLAR
        if agirlik_efektif.get(k, 0) >= 0.005
    }

    # TL mevduat hedef (4 kapı) — makro satır, araç dağılımı yok
    if tl_w >= 0.05 and tahsis.tl_tavan_oran > 0.01:
        tut_eur = toplam_eur * min(tl_w, tahsis.tl_tavan_oran)
        tut, p = _tutar_pb(tut_eur, pb, eur_try)
        _, vade_g = profil_mevduat_vadesi(profil)
        sonuc.vade.append(
            OneriSatir(
                sinif="tl_deposit",
                baslik="TL mevduat (hedef)",
                detay=f"4 kapı tavan %{tahsis.tl_tavan_oran*100:.0f} · ~{vade_g} gün vade",
                tutar=tut,
                para=p if p == "TL" else "TL" if pb == "TL" else p,
                donem="VADE",
                oncelik=1,
                etiket="TL",
            )
        )

    sonuc.arac_dagilim = arac_dagilim
    sonuc.hedef_tablo = _hedef_tablo_olustur(
        tahsis, profil, toplam_eur, pb, eur_try, arac_dagilim,
        tarama_yapildi=tarama_hazir,
        agirliklar=agirlik_efektif,
    )
    sonuc.bugun.sort(key=lambda x: x.oncelik)
    sonuc.vade.sort(key=lambda x: x.oncelik)
    sonuc.ozet = (
        f"{VADE_GUN.get(profil.vade, 365)} gün vade · {rejim} · "
        f"toplam {kp.ozet()}"
    )
    return sonuc
