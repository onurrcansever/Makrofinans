# -*- coding: utf-8 -*-
"""
Portföy yöneticisi planı — rakamlı bant, alım hedefi, iptal seviyesi.
Karar (AL/BEKLE) ile birlikte "ne zaman, hangi fiyatta" rehberi üretir.
"""
from __future__ import annotations

from typing import List, Optional, TYPE_CHECKING

import config
from fiyat_para import kaynak_para_birimi, tablo_fiyat
from ui_regime_badge import regime_badge_html
from investor_profile import vade_kisa_mi

if TYPE_CHECKING:
    from investor_profile import YatirimProfili
    from stock_scanner import HisseAnaliz

AKSIYON_ETIKET = {
    "AL": "🟢 AL",
    "KADEMELI": "🟡 Kademeli al",
    "BEKLE": "⚪ Bekle",
    "TUT": "🟢 Tut",
    "SAT": "🟡 Sat",
    "UZAK": "🔴 Uzak",
}


def _is_etf(h: "HisseAnaliz") -> bool:
    return h.piyasa == "ETF" or getattr(h, "varlik_turu", "") == "etf"


def _core_etf(h: "HisseAnaliz") -> bool:
    return _is_etf(h) and h.sektor in ("abd", "hisse_global", "teknoloji", "temettu", "europa")


def _high_52(h: "HisseAnaliz") -> Optional[float]:
    z = getattr(h, "zirve_52h_pct", None)
    if h.fiyat and z and z > 0:
        return float(h.fiyat) / (float(z) / 100.0)
    return None


def _alim_hedef(h: "HisseAnaliz") -> Optional[float]:
    high = _high_52(h)
    hedef = None
    if high:
        hedef = high * (config.AL_TEK_HISSE_ZIRVE_52H_MAX / 100.0)
    elif getattr(h, "sma200", None):
        hedef = float(h.sma200) * 0.97
    return _sane_seviye(h.fiyat, hedef)


def _sane_seviye(fiyat: Optional[float], seviye: Optional[float]) -> Optional[float]:
    if fiyat is None or seviye is None or fiyat <= 0:
        return None
    if seviye > fiyat * 1.05 or seviye < fiyat * 0.2:
        return None
    return seviye


def _destek(h: "HisseAnaliz") -> Optional[float]:
    if not h.fiyat:
        return None
    aday = []
    for attr in ("sma50", "sma20", "sma200"):
        v = getattr(h, attr, None)
        if v and float(v) < float(h.fiyat) * 0.998:
            aday.append(float(v))
    if not aday:
        return None
    return _sane_seviye(h.fiyat, max(aday))


def _iptal(h: "HisseAnaliz") -> Optional[float]:
    if getattr(h, "sma200", None):
        s = _sane_seviye(h.fiyat, float(h.sma200) * 0.98)
        if s:
            return s
    destek = _destek(h)
    if destek:
        return _sane_seviye(h.fiyat, destek * 0.95)
    return None


def _pct_asagi(hedef: Optional[float], fiyat: Optional[float]) -> Optional[float]:
    if hedef is None or fiyat is None or fiyat <= 0 or hedef >= fiyat:
        return None
    return (1.0 - hedef / fiyat) * 100.0


def _veri_hucre(h: "HisseAnaliz") -> str:
    if getattr(h, "veri_quarantine", False):
        return getattr(h, "veri_hatasi", "VERİ HATASI")[:40]
    base = getattr(h, "signal_v2_data", "—")
    age = getattr(h, "quote_age_min", None)
    if age is None:
        return base
    if age > 24 * 60:
        return f"{base} 🔴 bayat"
    if age > 60:
        return f"{base} ⚠ {int(age // 60)} sa"
    if age > 15:
        return f"{base} · {int(age)} dk"
    return f"{base} ✓"


def _fmt_seviye(
    fiyat: Optional[float],
    h: "HisseAnaliz",
    gosterim_pb: str,
    fx,
) -> str:
    if fiyat is None:
        return "—"
    kaynak = kaynak_para_birimi(
        h.sembol, piyasa=h.piyasa, varlik_turu=getattr(h, "varlik_turu", "hisse"),
        quote_currency=getattr(h, "quote_currency", ""),
    )
    v = tablo_fiyat(
        fiyat, gosterim_pb, fx.eur_try, fx.usd_try,
        sembol=h.sembol, piyasa=h.piyasa, varlik_turu=getattr(h, "varlik_turu", "hisse"),
        kaynak_pb=kaynak, quote_currency=getattr(h, "quote_currency", ""),
        gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd,
    )
    if v is None:
        return "—"
    if gosterim_pb == "TL":
        return f"{v:,.0f} {gosterim_pb}"
    if gosterim_pb == "EUR":
        return f"{v:,.2f} {gosterim_pb}"
    return f"{v:,.2f} {gosterim_pb}"


def yonetici_plani_olustur(
    h: "HisseAnaliz",
    profil: Optional["YatirimProfili"] = None,
) -> None:
    """HisseAnaliz üzerine yonetici_* alanlarını yazar."""
    from investor_profile import YatirimProfili

    if getattr(h, "signal_v2_regime", ""):
        _yonetici_v2_uygula(h)
        return

    profil = profil or YatirimProfili()
    uygun = getattr(h, "alim_uygun", "IZLE")
    zirve = getattr(h, "zirve_52h_pct", None)
    destek = _destek(h)
    alim = _alim_hedef(h)
    iptal = _iptal(h)
    uzun = profil.vade in ("uzun", "orta") and not vade_kisa_mi(profil.vade)

    if h.fiyat is None:
        h.yonetici_aksiyon = "BEKLE"
        h.yonetici_ozet = "Veri yok"
        h.yonetici_detay = ""
        return

    if uygun == "UYGUN":
        h.yonetici_aksiyon = "AL"
        h.yonetici_ozet = "Alım bölgesi"
    elif uygun == "UYGUN_DEGIL" or h.sinyal in ("UZAK_DUR", "ASIRI_ALIM"):
        h.yonetici_aksiyon = "UZAK"
        h.yonetici_ozet = "Alma"
    elif _is_etf(h) and not getattr(h, "vade_uygun", True):
        h.yonetici_aksiyon = "BEKLE"
        h.yonetici_ozet = "Vade kısa — bekle"
    elif _is_etf(h) and _core_etf(h) and zirve is not None and zirve >= 80 and uzun:
        h.yonetici_aksiyon = "KADEMELI"
        h.yonetici_ozet = "Parça parça al"
    elif zirve is not None and zirve >= config.AL_TEK_HISSE_ZIRVE_52H_MAX:
        h.yonetici_aksiyon = "BEKLE"
        h.yonetici_ozet = "Pahalı — bekle"
    elif uygun == "SINIRLI":
        h.yonetici_aksiyon = "KADEMELI" if _is_etf(h) else "BEKLE"
        h.yonetici_ozet = "Kademeli al" if _is_etf(h) else "Teyit bekle"
    else:
        h.yonetici_aksiyon = "BEKLE"
        h.yonetici_ozet = "İzle"

    h.yonetici_destek = destek
    h.yonetici_alim = alim
    h.yonetici_iptal = iptal
    h.yonetici_detay = ""


def _yonetici_v2_uygula(h: "HisseAnaliz") -> None:
    code = getattr(h, "signal_v2_code", "WAIT")
    h.yonetici_aksiyon = {
        "STRONG_BUY": "AL",
        "BUY": "AL",
        "WATCH": "KADEMELI",
        "WAIT": "BEKLE",
        "REDUCE": "UZAK",
    }.get(code, "BEKLE")
    h.yonetici_alim = getattr(h, "signal_v2_al_price", None)
    h.yonetici_destek = _destek(h)
    h.yonetici_iptal = _iptal(h)
    h.yonetici_ozet = f"{getattr(h, 'signal_v2_decision', '')} · {getattr(h, 'signal_v2_regime', '')}"
    h.yonetici_detay = getattr(h, "signal_v2_why", "")


def _settlement_fiyat(h: "HisseAnaliz") -> Optional[float]:
    return float(h.fiyat) if h.fiyat is not None else None


def _al_seviye_metni(
    h: "HisseAnaliz",
    gosterim_pb: str,
    fx,
) -> str:
    """Al sütunu — seviye ve spot aynı gösterim para biriminde."""
    spot = _settlement_fiyat(h)
    price = getattr(h, "signal_v2_al_price", None)
    if spot is None or spot <= 0:
        return "—"
    dist = getattr(h, "signal_v2_spot_distance_pct", None)
    if price is None or price <= 0:
        return "—"
    if dist is None:
        dist = abs(price / spot - 1.0) * 100.0
    spot_txt = _fmt_seviye(spot, h, gosterim_pb, fx)
    if dist <= 2.0 or getattr(h, "signal_v2_spot_near", False):
        out = f"spot civarı ({spot_txt})"
    elif price < spot * 0.995:
        out = _fmt_seviye(price, h, gosterim_pb, fx)
    else:
        out = _fmt_seviye(price, h, gosterim_pb, fx)
    # P(doldur) UI'da yok — tarihsel min≤hedef oranı limit doldurma olasılığı değil.
    sec = getattr(h, "signal_v2_al_secondary", None)
    if sec and (dist <= 2.0 or getattr(h, "signal_v2_spot_near", False)):
        out += f" / 2: {_fmt_seviye(sec, h, gosterim_pb, fx)}"
    return out


def yonetici_tablo_kolonlari(
    h: "HisseAnaliz",
    gosterim_pb: str,
    fx,
) -> dict:
    """Tablo sütunları — v2: Al/Rejim/Veri (Emir yok; Karar ayrı sütun)."""
    v2 = (
        getattr(h, "signal_v2_decision", "")
        or getattr(h, "signal_v2_regime", "")
        or getattr(h, "signal_v2_score", None) is not None
    )
    if v2:
        al = "—"
        if getattr(h, "signal_v2_code", "") in ("STRONG_BUY", "BUY"):
            al = _al_seviye_metni(h, gosterim_pb, fx)
        elif getattr(h, "signal_v2_al_price", None):
            al = _al_seviye_metni(h, gosterim_pb, fx)
        return {
            "Al": al,
            "Rejim": regime_badge_html(
                getattr(h, "signal_v2_regime", ""),
                getattr(h, "signal_v2_regime_detail", ""),
                duration_days=getattr(h, "signal_v2_regime_days", 0) or None,
                fresh_change=getattr(h, "signal_v2_regime_fresh", False),
            ),
            "Veri": _veri_hucre(h),
        }

    aks = getattr(h, "yonetici_aksiyon", "BEKLE")
    alim = getattr(h, "yonetici_alim", None)
    al = "—"
    if aks == "AL":
        al = "Şimdi"
    elif aks == "KADEMELI" and not (alim and h.fiyat and alim < h.fiyat * 0.995):
        al = "Parça"
    elif alim and h.fiyat and alim < h.fiyat * 0.995:
        al = _fmt_seviye(alim, h, gosterim_pb, fx)
    # v1: Emir kaldırıldı — Karar sütunu yeterli (çift gösterim yok)
    return {
        "Al": al,
        "Rejim": "—",
        "Veri": _veri_hucre(h),
    }


def yonetici_tablo_metni(
    h: "HisseAnaliz",
    gosterim_pb: str,
    fx,
) -> str:
    """Tarama tablosu — sadece alım kararı (henüz pozisyon yok, Sat yok)."""
    aks = getattr(h, "yonetici_aksiyon", "BEKLE")
    etiket = AKSIYON_ETIKET.get(aks, "⚪ Bekle")
    alim = getattr(h, "yonetici_alim", None)
    parcalar = [etiket]

    if aks == "AL":
        parcalar.append("Al: şimdi")
    elif aks == "KADEMELI":
        parcalar.append("Al: parça parça")
        if alim and h.fiyat and alim < h.fiyat * 0.995:
            parcalar.append(f"tam al {_fmt_seviye(alim, h, gosterim_pb, fx)}")
    elif aks != "UZAK" and alim and h.fiyat and alim < h.fiyat * 0.995:
        parcalar.append(f"Al: {_fmt_seviye(alim, h, gosterim_pb, fx)}")

    return " · ".join(parcalar)[:90]


def yonetici_notu_uygula(
    hisseler: List["HisseAnaliz"],
    profil: Optional["YatirimProfili"] = None,
) -> None:
    for h in hisseler:
        yonetici_plani_olustur(h, profil=profil)


def yonetici_oncelikli(
    hisseler: List["HisseAnaliz"],
    n: int = 5,
) -> List["HisseAnaliz"]:
    """Özet panel — çekirdek ETF + en iyi adaylar."""
    sira = {"AL": 0, "KADEMELI": 1, "BEKLE": 2, "UZAK": 3}

    def key(h):
        return (
            sira.get(getattr(h, "yonetici_aksiyon", "BEKLE"), 9),
            0 if _core_etf(h) else 1,
            -float(getattr(h, "bilesik_skor", 0) or h.skor or 0),
        )

    aday = [h for h in hisseler if h.fiyat is not None and getattr(h, "yonetici_aksiyon", "") != "UZAK"]
    aday.sort(key=key)
    return aday[:n]


def tarama_hisse_bul(tarama, sembol: str):
    if not tarama or not sembol:
        return None
    sym = sembol.upper()
    for h in getattr(tarama, "hisseler", None) or []:
        if (h.sembol or "").upper() == sym:
            return h
    return None


def _fmt_poz_birim(
    fiyat: float,
    tur: str,
    sembol: str,
    gosterim_pb: str,
    fx,
    quote_currency: str = "",
    kaynak_pb: str = "",
) -> str:
    if fiyat <= 0:
        return "—"
    if tur == "tefas":
        from fiyat_para import tefas_tablo_fiyat

        src = kaynak_pb or "TL"
        v = tefas_tablo_fiyat(
            fiyat, gosterim_pb, src, fx.eur_try, fx.usd_try,
            gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd,
        )
        if v is None:
            return "—"
        if gosterim_pb == "TL":
            return f"{v:,.0f} {gosterim_pb}"
        return f"{v:,.2f} {gosterim_pb}"
    kaynak = kaynak_pb or kaynak_para_birimi(
        sembol or "", pozisyon_turu=tur, varlik_turu=tur,
        quote_currency=quote_currency,
    )
    use_sym = sembol if tur in ("hisse", "etf") else ""
    v = tablo_fiyat(
        fiyat, gosterim_pb, fx.eur_try, fx.usd_try,
        sembol=use_sym, varlik_turu=tur,
        kaynak_pb=kaynak, quote_currency=quote_currency if use_sym else "",
        gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd,
    )
    if v is None:
        return "—"
    if gosterim_pb == "TL":
        return f"{v:,.0f} {gosterim_pb}"
    return f"{v:,.2f} {gosterim_pb}"


def _pozisyon_stop(alis: float, guncel: float) -> float:
    """Zarar kes — maliyetin ~%12 altı; güncel fiyattan yüksek olamaz."""
    stop = alis * 0.88
    if guncel > 0:
        stop = min(stop, guncel * 0.92)
    return stop


def yonetici_pozisyon_kolonlari(
    pozisyon,
    pd_,
    *,
    tarama=None,
    gosterim_pb: str = "EUR",
    fx=None,
) -> dict:
    """Varlıklarım tablo sütunları — Emir, Ekle, Stop."""
    p = pozisyon
    tur = p.tur
    sym = p.sembol or ""
    bos = {"Emir": "—", "Ekle": "—", "Stop": "—"}

    if tur in ("nakit_tl", "nakit_eur", "nakit_usd", "nakit_ron", "tl_mevduat"):
        return {"Emir": "Tut", "Ekle": "—", "Stop": "—"}
    if pd_.guncel_birim <= 0 or pd_.alim_birim <= 0:
        return {"Emir": "Bekle", "Ekle": "—", "Stop": "—"}

    kz = pd_.kar_zarar_pct
    alis = pd_.alim_birim
    guncel = pd_.guncel_birim
    stop = _pozisyon_stop(alis, guncel)
    ekle = alis * 0.95

    h = tarama_hisse_bul(tarama, sym)
    alim = getattr(h, "yonetici_alim", None) if h else None
    if alim and alim < guncel * 0.995:
        ekle = alim

    qc = getattr(h, "quote_currency", "") if h else ""
    src_pb = (pd_.para or p.para_birimi or "TL") if tur == "tefas" else ""

    def _f(x):
        return _fmt_poz_birim(
            x, tur, sym, gosterim_pb, fx, quote_currency=qc, kaynak_pb=src_pb,
        )

    ekle_s = _f(ekle) if ekle < guncel * 0.995 else "—"
    stop_s = _f(stop)

    if kz >= 25:
        return {"Emir": "Sat", "Ekle": "—", "Stop": stop_s}
    if kz <= -12:
        return {"Emir": "Bekle", "Ekle": ekle_s, "Stop": stop_s}
    if kz <= -8 and tur == "tefas":
        return {"Emir": "Ekle", "Ekle": ekle_s, "Stop": stop_s}
    return {"Emir": "Tut", "Ekle": ekle_s, "Stop": stop_s}


def yonetici_pozisyon_plani(
    pozisyon,
    pd_,
    *,
    tarama=None,
    gosterim_pb: str = "EUR",
    fx=None,
) -> str:
    """Varlıklarım — elindeki pozisyon: Tut / ekle / stop."""
    p = pozisyon
    tur = p.tur
    sym = p.sembol or ""

    if tur in ("nakit_tl", "nakit_eur", "nakit_usd", "nakit_ron", "tl_mevduat"):
        return "🟢 Tut"

    if pd_.guncel_birim <= 0 or pd_.alim_birim <= 0:
        return "⚪ Bekle"

    kz = pd_.kar_zarar_pct
    alis = pd_.alim_birim
    guncel = pd_.guncel_birim
    stop = _pozisyon_stop(alis, guncel)

    h = tarama_hisse_bul(tarama, sym)
    alim = getattr(h, "yonetici_alim", None) if h else None
    ekle = alim if (alim and alim < guncel * 0.995) else alis * 0.95

    qc = getattr(h, "quote_currency", "") if h else ""
    src_pb = (pd_.para or p.para_birimi or "TL") if tur == "tefas" else ""

    def _f(x):
        return _fmt_poz_birim(
            x, tur, sym, gosterim_pb, fx, quote_currency=qc, kaynak_pb=src_pb,
        )

    if kz >= 25:
        return f"🟢 Tut · Kârda · Stop: {_f(stop)} altı"
    if kz >= 15 and tur == "tefas":
        return f"🟢 Tut · Stop: {_f(stop)} altı"
    if kz <= -12:
        return f"⚪ Bekle · Ekle: {_f(ekle)} · Stop: {_f(stop)} altı"
    if kz <= -8 and tur == "tefas":
        return f"🟡 Ekle · {_f(ekle)} · Stop: {_f(stop)} altı"

    parcalar = ["🟢 Tut", f"Stop: {_f(stop)} altı"]
    if ekle < guncel * 0.995:
        parcalar.insert(1, f"Ekle: {_f(ekle)}")
    return " · ".join(parcalar)
