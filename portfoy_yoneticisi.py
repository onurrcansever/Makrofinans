# -*- coding: utf-8 -*-
"""
Portföy yöneticisi planı — rakamlı bant, alım hedefi, iptal seviyesi.
Karar (AL/BEKLE) ile birlikte "ne zaman, hangi fiyatta" rehberi üretir.
"""
from __future__ import annotations

import logging
from typing import List, Optional, TYPE_CHECKING

import config
from fiyat_para import kaynak_para_birimi, tablo_fiyat
from ui_regime_badge import regime_badge_html
from investor_profile import vade_kisa_mi

if TYPE_CHECKING:
    from investor_profile import YatirimProfili
    from stock_scanner import HisseAnaliz

# Varlıklarım tablo sütun adları (tarama Karar/Emir'den ayrı)
POZ_COL_SINYAL = "Alım/Satış Sinyali"
POZ_COL_ONERI = "Pozisyon Önerisi"

_log = logging.getLogger(__name__)

_TL_KUR_RISK_TURLER = ("hisse", "tefas", "tl_mevduat", "nakit_tl")

POZ_ONERI_ETIKET = {
    "Tut": "Elde tut",
    "Bekle": "Pasif bekle",
    "Ekle": "Ekleme düşün",
    "Kâr Al": "Kâr al",
    "Sat": "Çıkış değerlendir",
    "Azalt": "Küçült",
}


def pozisyon_oneri_etiket(hucre) -> str:
    """Tablo hücresinden görünen etiket."""
    if isinstance(hucre, dict):
        return str(hucre.get("label") or "—")
    return str(hucre or "—")


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


def _is_emtia(h: "HisseAnaliz") -> bool:
    return h.piyasa == "EMTIA" or getattr(h, "varlik_turu", "") == "emtia"


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
    """Veri kalitesi + önbellek tazeliği (SLA: ≤15 dk).

    Yaş = bizim live-quote / disk önbelleğinin yaşı — Yahoo last-trade
    timestamp'i değil (BIST açıkken bile last-trade 1 sa eski görünebilir).
    """
    if getattr(h, "veri_quarantine", False):
        return getattr(h, "veri_hatasi", "VERİ HATASI")[:40]
    base = getattr(h, "signal_v2_data", "—")

    age_min: Optional[float] = None
    try:
        import time

        from signal_engine.data.live_quote import DISK_TTL_SEC, get_live_quote

        live = get_live_quote(getattr(h, "sembol", "") or "")
        if live is not None:
            if live.cached_at is not None:
                age_min = max(0.0, (time.time() - float(live.cached_at)) / 60.0)
            elif live.age_min is not None:
                age_min = float(live.age_min)
        if age_min is None:
            age_min = getattr(h, "quote_age_min", None)
        ttl_dk = DISK_TTL_SEC / 60.0
    except Exception:
        age_min = getattr(h, "quote_age_min", None)
        ttl_dk = 15.0

    if age_min is None:
        return base
    if age_min > 24 * 60:
        return f"{base} 🔴 bayat"
    # SLA: 15 dk — aşılınca uyarı (önceden 60 dk eşiği BIST'te yanıltıcıydı)
    if age_min > ttl_dk:
        if age_min >= 60:
            return f"{base} ⚠ {int(age_min // 60)} sa"
        return f"{base} ⚠ {int(age_min)} dk"
    return f"{base} ✓"


def _fmt_seviye(
    fiyat: Optional[float],
    h: "HisseAnaliz",
    gosterim_pb: str,
    fx,
) -> str:
    if fiyat is None:
        return "—"
    from fiyat_para_fx import FxUnavailableError

    kaynak = kaynak_para_birimi(
        h.sembol, piyasa=h.piyasa, varlik_turu=getattr(h, "varlik_turu", "hisse"),
        quote_currency=getattr(h, "quote_currency", ""),
    )
    try:
        v = tablo_fiyat(
            fiyat, gosterim_pb, fx.eur_try, fx.usd_try,
            sembol=h.sembol, piyasa=h.piyasa, varlik_turu=getattr(h, "varlik_turu", "hisse"),
            kaynak_pb=kaynak, quote_currency=getattr(h, "quote_currency", ""),
            gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd,
            chf_usd=getattr(fx, "chf_usd", None),
        )
    except FxUnavailableError:
        return "—"
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
    gates = getattr(h, "signal_v2_decision_gates", None) or []
    gate_txt = " ".join(str(g) for g in gates)
    # İZLE (WATCH): kademeli alım yok — özellikle TRENDING_DOWN / makro tavan sonrası
    if code == "WATCH":
        aksiyon = "BEKLE"
        ozet_ek = "İzle — kademeli alım yok"
        if "TRENDING_DOWN" in gate_txt or "Makro" in gate_txt:
            ozet_ek = "Kapı: alım askıda"
    else:
        aksiyon = {
            "STRONG_BUY": "AL",
            "BUY": "AL",
            "WAIT": "BEKLE",
            "REDUCE": "UZAK",
        }.get(code, "BEKLE")
        ozet_ek = ""
    h.yonetici_aksiyon = aksiyon
    h.yonetici_alim = getattr(h, "signal_v2_al_price", None)
    h.yonetici_destek = _destek(h)
    h.yonetici_iptal = _iptal(h)
    base = f"{getattr(h, 'signal_v2_decision', '')} · {getattr(h, 'signal_v2_regime', '')}"
    h.yonetici_ozet = f"{base} · {ozet_ek}" if ozet_ek else base
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
    """Tablo sütunları — v2: Alım seviyesi/Rejim/Veri (Emir yok; aksiyon ayrı sütun)."""
    from karar_lejant import HISSE_ALIM_SEVIYE_SUTUN

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
            HISSE_ALIM_SEVIYE_SUTUN: al,
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
    # v1: Emir kaldırıldı — aksiyon sütunu yeterli (çift gösterim yok)
    return {
        HISSE_ALIM_SEVIYE_SUTUN: al,
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
    """Özet panel — v2 açıksa önce AL; KADEMELİ yumuşak alım önceliği verilmez."""
    sira = {"AL": 0, "KADEMELI": 1, "BEKLE": 2, "UZAK": 3}
    v2_any = any(getattr(h, "signal_v2_code", None) for h in hisseler)

    def key(h):
        return (
            sira.get(getattr(h, "yonetici_aksiyon", "BEKLE"), 9),
            0 if _core_etf(h) else 1,
            -float(getattr(h, "bilesik_skor", 0) or h.skor or 0),
        )

    aday = [
        h for h in hisseler
        if h.fiyat is not None and getattr(h, "yonetici_aksiyon", "") != "UZAK"
    ]
    if v2_any:
        # Öncelik: gerçek AL; yoksa boş/az satır — yanlış KADEMELİ fırsat şişirmesin
        sadece_al = [h for h in aday if getattr(h, "yonetici_aksiyon", "") == "AL"]
        if sadece_al:
            aday = sadece_al
    aday.sort(key=key)
    return aday[:n]


def tarama_hisse_bul(tarama, sembol: str):
    """Tarama evreninde sembol eşleşmesi (.IS / kok uyumlu)."""
    if not tarama or not sembol:
        return None
    from portfoy_yorum import sembol_kok

    sym_u = sembol.upper()
    kok = sembol_kok(sym_u)
    for h in getattr(tarama, "hisseler", None) or []:
        hs = (h.sembol or "").upper()
        if hs == sym_u or sembol_kok(hs) == kok:
            return h
    return None


_EMTIA_TARAMA = {"altin": "GC=F", "gumus": "SI=F"}
_KZ_SAT = 25.0
_KZ_KAR_AL = 15.0
_KZ_ZARAR_BEKLE = -12.0
_KZ_EKLE = -8.0
_TEFAS_ONERI_KARAR = {
    "AL": "AL",
    "IZLE": "İZLE",
    "BEKLE": "BEKLE",
    "ZAYIF": "AZALT",
}


def tefas_pozisyon_bul(tefas_kaynak, kod: str):
    if not tefas_kaynak or not kod:
        return None
    hedef = kod.upper()
    for f in getattr(tefas_kaynak, "fonlar", None) or []:
        if (getattr(f, "kod", "") or "").upper() == hedef:
            return f
    return None


def pozisyon_sinyal_bilgisi(
    tur: str,
    sembol: str,
    *,
    tarama=None,
    tefas_ham=None,
    tefas_skorlu=None,
) -> dict:
    """
    Signal Engine v2 (hisse/ETF/emtia) veya TEFAS skor → karar + skor.
    Dönüş: {karar, skor, kaynak, sinyal_obj}
    """
    tur_l = (tur or "").lower()
    bos = {"karar": "—", "skor": None, "kaynak": "", "sinyal_obj": None}

    if tur_l in ("nakit_tl", "nakit_eur", "nakit_usd", "nakit_ron", "tl_mevduat"):
        return {**bos, "karar": "—", "kaynak": "nakit"}

    if tur_l == "tefas":
        tefas_k = tefas_skorlu or tefas_ham
        f = tefas_pozisyon_bul(tefas_k, sembol)
        if not f:
            return bos
        oneri = (getattr(f, "oneri", "") or "").upper()
        return {
            "karar": _TEFAS_ONERI_KARAR.get(oneri, "—"),
            "skor": getattr(f, "skor", None),
            "kaynak": "tefas",
            "sinyal_obj": f,
        }

    if tur_l in ("hisse", "hisse_us", "etf", "altin", "gumus", "kripto"):
        lookup = _EMTIA_TARAMA.get(tur_l) or sembol
        h = tarama_hisse_bul(tarama, lookup)
        if not h:
            return bos
        karar = (
            getattr(h, "signal_v2_decision", None)
            or getattr(h, "karar", None)
            or "—"
        )
        skor = getattr(h, "signal_v2_score", None) or getattr(h, "skor", None)
        return {
            "karar": str(karar).strip() or "—",
            "skor": skor,
            "kaynak": "signal_v2",
            "sinyal_obj": h,
        }

    return bos


def _pozisyon_karar_normalize(karar: str) -> str:
    from portfoy_yorum import _karar_normalize
    return _karar_normalize(karar)


def pozisyon_emir_hesapla(kz: float, karar: str, *, tur: str = "") -> str:
    """
    Eldeki pozisyon için Emir — Signal v2 kararı + K/Z bantları.
    Kâr realizasyonu: AZALT / zayıf sinyal + kârda → Kâr Al.
    """
    k = _pozisyon_karar_normalize(karar)
    if k == "—" or not k:
        # Sinyal yok — eski K/Z kuralları
        if kz >= _KZ_SAT:
            return "Sat"
        if kz <= _KZ_ZARAR_BEKLE:
            return "Bekle"
        if kz <= _KZ_EKLE and (tur or "").lower() == "tefas":
            return "Ekle"
        return "Tut"

    if kz >= _KZ_SAT:
        return "Sat"

    if k == "AZALT":
        if kz >= _KZ_KAR_AL:
            return "Kâr Al"
        if kz > 0:
            return "Azalt"
        return "Sat" if kz <= _KZ_ZARAR_BEKLE else "Azalt"

    if kz >= _KZ_KAR_AL and k in ("BEKLE", "İZLE"):
        return "Kâr Al"

    if k == "BEKLE":
        if kz <= _KZ_ZARAR_BEKLE:
            return "Bekle"
        if kz > 0 and kz >= _KZ_KAR_AL:
            return "Kâr Al"
        return "Bekle"

    if k in ("AL",):
        if kz <= _KZ_EKLE:
            return "Ekle"
        return "Tut"

    if k == "İZLE":
        if kz <= _KZ_ZARAR_BEKLE:
            return "Bekle"
        return "Tut"

    return "Tut"


def _kur_risk_notu(tur: str, gosterim_pb: str) -> str:
    if gosterim_pb == "EUR" and tur in _TL_KUR_RISK_TURLER:
        return " TL/EUR kuru getiriyi etkiler."
    return ""


def pozisyon_oneri_hucre(
    emir: str,
    karar: str,
    kz: float,
    *,
    tur: str = "",
    gosterim_pb: str = "",
) -> dict:
    """Pozisyon önerisi — görünen etiket + hover açıklaması."""
    kod = emir or "—"
    label = POZ_ONERI_ETIKET.get(kod, kod)
    k = _pozisyon_karar_normalize(karar) if karar and karar != "—" else "—"
    kz_s = f"{kz:+.1f}%"
    sinyal_p = f" Motor sinyali: {karar}." if karar and karar != "—" else ""
    kur_n = _kur_risk_notu(tur, gosterim_pb)

    if kod == "Tut":
        if tur in ("nakit_tl", "nakit_eur", "nakit_usd", "nakit_ron", "tl_mevduat"):
            tip = "Nakit veya mevduat — pozisyonu koruyun, ek işlem gerekmez."
        elif k in ("AL", "İZLE"):
            tip = (
                f"Elde tutun — motor hâlâ olumlu ({karar}). K/Z {kz_s}. "
                "Yeni ekleme zorunlu değil; Stop sütununu izleyin."
            )
        else:
            tip = (
                f"Elde tutun — K/Z {kz_s}, acil çıkış veya ekleme sinyali yok.{sinyal_p} "
                "Rutin takip yeterli."
            )
    elif kod == "Bekle":
        if k == "BEKLE":
            tip = (
                f"Pasif bekleyin — motor zayıf ({karar}). K/Z {kz_s}. "
                "Pozisyonu tutabilirsiniz ama yeni para eklemeyin; sinyal güçlenene kadar bekleyin."
            )
        elif kz <= _KZ_ZARAR_BEKLE:
            tip = (
                f"Pasif bekleyin — K/Z {kz_s} (derin zarar bandı).{sinyal_p} "
                "Panik satış yerine toparlanma veya net sinyal bekleyin; Ekle sütununa bakın."
            )
        else:
            tip = (
                f"Pasif bekleyin — K/Z {kz_s}.{sinyal_p} "
                "Ekleme yapmayın; motor veya fiyat netleşene kadar bekleyin."
            )
    elif kod == "Ekle":
        tip = (
            f"Ekleme düşünün — motor {karar} diyor, K/Z {kz_s}. "
            "Ekle sütunundaki fiyattan kademeli ortalama düşürme değerlendirilebilir."
        )
    elif kod == "Kâr Al":
        tip = (
            f"Kâr almayı düşünün — K/Z {kz_s}, motor {karar}.{sinyal_p} "
            "Kademeli satış ile kâr kilitlemeyi değerlendirin. "
            "Kademeli realizasyon — tam kapatma zorunlu değil."
        )
    elif kod == "Sat":
        tip = (
            f"Çıkış değerlendirin — K/Z {kz_s} (güçlü kâr veya ciddi zarar).{sinyal_p} "
            "Tam veya kısmi satış düşünülebilir. "
            "Kademeli realizasyon — tam kapatma zorunlu değil."
        )
    elif kod == "Azalt":
        tip = (
            f"Pozisyonu küçültün — motor AZALT, K/Z {kz_s}. "
            "Tam çıkış yerine kademeli azaltma da mümkün."
        )
    else:
        tip = "Pozisyon önerisi — yatırım tavsiyesi değildir."

    return {"code": kod, "label": label, "tip": tip + kur_n}


def pozisyon_kar_uyarisi(
    etiket: str,
    emir: str,
    karar: str,
    kz: float,
) -> Optional[str]:
    """Kâr realizasyonu / çıkış uyarı metni (None = uyarı yok)."""
    if emir == "Kâr Al":
        return (
            f"**{etiket}** — K/Z **{kz:+.1f}%** · motor **{karar}** → "
            "kâr realizasyonu düşünün (kademeli satış)."
        )
    if emir == "Sat":
        return (
            f"**{etiket}** — K/Z **{kz:+.1f}%** · "
            + (f"motor **{karar}** → " if karar and karar != "—" else "")
            + "tam/parsiyel çıkış değerlendirin."
        )
    if emir == "Azalt":
        return (
            f"**{etiket}** — motor **AZALT** · K/Z **{kz:+.1f}%** → "
            "pozisyon küçültmeyi değerlendirin."
        )
    return None


def _pozisyon_ekle_karantina(
    ekle: float,
    guncel: float,
    *,
    tur: str = "",
    sembol: str = "",
) -> bool:
    """|ekle/güncel − 1| > ENTRY_SANITY_PCT ise Ekle gösterme (tarama guard ile aynı)."""
    from signal_engine.entry.levels import ENTRY_SANITY_PCT

    if guncel <= 0 or ekle <= 0:
        return False
    sapma = abs(ekle / guncel - 1.0)
    if sapma > ENTRY_SANITY_PCT:
        _log.warning(
            "pozisyon_ekle_karantina tur=%s sembol=%s ekle=%.4f guncel=%.4f sapma=%.1f%%",
            tur, sembol, ekle, guncel, sapma * 100,
        )
        return True
    return False


def _pozisyon_ekle_fiyat(
    tur: str,
    sym: str,
    alis: float,
    guncel: float,
    tarama,
    sinyal_obj,
    *,
    usd_try: float = 0.0,
) -> Optional[float]:
    ekle = alis * 0.95
    h = sinyal_obj if getattr(sinyal_obj, "sembol", None) else None
    if not h and tur in ("hisse", "hisse_us", "etf", "altin", "gumus"):
        h = tarama_hisse_bul(tarama, _EMTIA_TARAMA.get(tur, sym) or sym)
    alim = getattr(h, "signal_v2_al_price", None) if h else None
    if alim is None and h:
        alim = getattr(h, "yonetici_alim", None)
    if alim and alim < guncel * 0.995:
        alim_f = float(alim)
        if tur in ("altin", "gumus") and usd_try > 0:
            from emtia_universe import gram_tl_from_oz
            alim_f = gram_tl_from_oz(alim_f, usd_try)
        ekle = alim_f
    if _pozisyon_ekle_karantina(ekle, guncel, tur=tur, sembol=sym):
        return None
    return ekle


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
            chf_usd=getattr(fx, "chf_usd", None),
        )
        if v is None:
            return "—"
        return f"{v:,.4f} {gosterim_pb}"
    kaynak = kaynak_pb or kaynak_para_birimi(
        sembol or "", pozisyon_turu=tur, varlik_turu=tur,
        quote_currency=quote_currency,
    )
    use_sym = sembol if tur in ("hisse", "hisse_us", "etf", "kripto") else ""
    # BIST / TL — fiyat zaten yerel para; Yahoo settlement dönüşümü gereksiz
    if kaynak in ("TL", "TRY"):
        use_sym = ""
    qc_use = quote_currency if use_sym else ""
    v = tablo_fiyat(
        fiyat, gosterim_pb, fx.eur_try, fx.usd_try,
        sembol=use_sym, varlik_turu=tur,
        kaynak_pb=kaynak, quote_currency=qc_use,
        gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd,
        chf_usd=getattr(fx, "chf_usd", None),
        allow_currency_guess=False,
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


def _manuel_hedef_hucre(
    hedef_fiyat: float,
    tur: str,
    sym: str,
    guncel_birim: float,
    gosterim_pb: str,
    fx,
    *,
    quote_currency: str = "",
    kaynak_pb: str = "",
) -> dict:
    """Kullanıcının kendi girdiği hedef fiyat — her araç türü için (fon dahil)."""
    if not hedef_fiyat or hedef_fiyat <= 0 or fx is None:
        return {"label": "—", "tip": "Hedef fiyat girilmedi."}
    label = _fmt_poz_birim(
        hedef_fiyat, tur, sym, gosterim_pb, fx,
        quote_currency=quote_currency, kaynak_pb=kaynak_pb,
    )
    if label == "—":
        return {"label": "—", "tip": "Hedef fiyat gösterilemedi."}
    tip = "Senin hedefin · bilgi; otomatik satış / Kâr al sinyali değil."
    if guncel_birim and guncel_birim > 0:
        upside = (float(hedef_fiyat) / float(guncel_birim) - 1.0) * 100.0
        tip = f"Senin hedefin · spot’a göre ~{upside:+.0f}% · bilgi; otomatik satış değil."
    return {"label": label, "tip": tip}


def _yahoo_hedef_hucre(
    tur: str,
    sym: str,
    guncel_birim: float,
    gosterim_pb: str,
    fx,
    *,
    quote_currency: str = "",
    kaynak_pb: str = "",
) -> dict:
    """Yahoo targetMeanPrice — bilgi amaçlı; emir motoruna bağlanmaz."""
    bos = {"label": "—", "tip": "Yahoo hedef yok (cache boş, ETF/TEFAS veya veri yok)."}
    if tur not in ("hisse", "hisse_us") or not (sym or "").strip():
        return bos
    if fx is None:
        return bos
    try:
        from temel_veri import get_temel

        temel = get_temel(sym) or {}
    except Exception:
        return bos
    if not temel or temel.get("_bos"):
        return bos
    try:
        hedef = float(temel.get("targetMeanPrice"))
    except (TypeError, ValueError):
        return bos
    if hedef <= 0:
        return bos
    cur = str(temel.get("currency") or quote_currency or "").upper()
    if cur == "TRY":
        cur = "TL"
    qc = quote_currency or cur
    src_pb = kaynak_pb or cur or ("USD" if tur == "hisse_us" else "")
    label = _fmt_poz_birim(
        hedef, tur, sym, gosterim_pb, fx,
        quote_currency=qc, kaynak_pb=src_pb,
    )
    if label == "—":
        return bos
    tip = (
        "Yahoo konsensüs hedef (ortalama) · bilgi; otomatik satış / Kâr al sinyali değil."
    )
    if guncel_birim and guncel_birim > 0:
        # Spot ile aynı birimde kıyas (quote); FX sapması küçük kalır
        upside = (hedef / float(guncel_birim) - 1.0) * 100.0
        tip = (
            f"Yahoo konsensüs hedef · spot’a göre ~{upside:+.0f}% · "
            "bilgi; otomatik satış değil."
        )
    return {"label": label, "tip": tip}


def yonetici_pozisyon_kolonlari(
    pozisyon,
    pd_,
    *,
    tarama=None,
    tefas_ham=None,
    tefas_skorlu=None,
    gosterim_pb: str = "EUR",
    fx=None,
) -> dict:
    """Varlıklarım tablo sütunları — sinyal (v2/TEFAS), pozisyon önerisi, Ekle, Stop, Hedef."""
    p = pozisyon
    tur = p.tur
    sym = p.sembol or ""
    hedef_manuel = float(getattr(p, "hedef_fiyat", 0.0) or 0.0)
    _src_pb0 = pd_.para or p.para_birimi or ("TL" if tur == "tefas" else "")
    bos = {
        POZ_COL_SINYAL: "—", POZ_COL_ONERI: "—",
        "Ekle": "—", "Stop": "—", "Hedef": "—",
    }

    if tur in ("nakit_tl", "nakit_eur", "nakit_usd", "nakit_ron", "tl_mevduat"):
        return {
            POZ_COL_SINYAL: "—",
            POZ_COL_ONERI: pozisyon_oneri_hucre("Tut", "—", 0, tur=tur, gosterim_pb=gosterim_pb),
            "Ekle": "—", "Stop": "—", "Hedef": "—",
        }
    if pd_.guncel_birim <= 0 or pd_.alim_birim <= 0:
        return {
            POZ_COL_SINYAL: "—",
            POZ_COL_ONERI: pozisyon_oneri_hucre(
                "Bekle", "—", pd_.kar_zarar_pct, tur=tur, gosterim_pb=gosterim_pb,
            ),
            "Ekle": "—", "Stop": "—",
            "Hedef": (
                _manuel_hedef_hucre(
                    hedef_manuel, tur, sym, pd_.guncel_birim, gosterim_pb, fx,
                    kaynak_pb=_src_pb0,
                )
                if hedef_manuel > 0 else "—"
            ),
        }

    kz = pd_.kar_zarar_pct
    alis = pd_.alim_birim
    guncel = pd_.guncel_birim
    stop = _pozisyon_stop(alis, guncel)

    sinyal = pozisyon_sinyal_bilgisi(
        tur, sym, tarama=tarama, tefas_ham=tefas_ham, tefas_skorlu=tefas_skorlu,
    )
    karar = sinyal["karar"]
    emir = pozisyon_emir_hesapla(kz, karar, tur=tur)
    s_obj = sinyal.get("sinyal_obj")
    usd_try = float(getattr(fx, "usd_try", 0) or 0) if fx else 0.0
    ekle = _pozisyon_ekle_fiyat(
        tur, sym, alis, guncel, tarama, s_obj, usd_try=usd_try,
    )

    h = s_obj if getattr(s_obj, "sembol", None) else tarama_hisse_bul(
        tarama, _EMTIA_TARAMA.get(tur, sym) or sym,
    )
    qc = getattr(h, "quote_currency", "") if h else ""
    src_pb = pd_.para or p.para_birimi or ""
    if tur == "tefas" and not src_pb:
        src_pb = "TL"

    def _f(x):
        return _fmt_poz_birim(
            x, tur, sym, gosterim_pb, fx, quote_currency=qc, kaynak_pb=src_pb,
        )

    ekle_s = (
        _f(ekle)
        if ekle is not None and ekle < guncel * 0.995
        and emir in ("Ekle", "Bekle", "Tut", "Azalt")
        else "—"
    )
    stop_s = _f(stop)
    if hedef_manuel > 0:
        hedef_h = _manuel_hedef_hucre(
            hedef_manuel, tur, sym, guncel, gosterim_pb, fx,
            quote_currency=qc, kaynak_pb=src_pb,
        )
    else:
        hedef_h = _yahoo_hedef_hucre(
            tur, sym, guncel, gosterim_pb, fx,
            quote_currency=qc, kaynak_pb=src_pb,
        )

    return {
        POZ_COL_SINYAL: karar,
        POZ_COL_ONERI: pozisyon_oneri_hucre(
            emir, karar, kz, tur=tur, gosterim_pb=gosterim_pb,
        ),
        "Ekle": ekle_s,
        "Stop": stop_s,
        "Hedef": hedef_h,
    }


def yonetici_pozisyon_plani(
    pozisyon,
    pd_,
    *,
    tarama=None,
    tefas_ham=None,
    tefas_skorlu=None,
    gosterim_pb: str = "EUR",
    fx=None,
) -> str:
    """Varlıklarım — elindeki pozisyon: sinyal v2 + K/Z rehberi."""
    p = pozisyon
    tur = p.tur
    sym = p.sembol or ""

    if tur in ("nakit_tl", "nakit_eur", "nakit_usd", "nakit_ron", "tl_mevduat"):
        return f"🟢 {POZ_ONERI_ETIKET['Tut']}"

    if pd_.guncel_birim <= 0 or pd_.alim_birim <= 0:
        return f"⚪ {POZ_ONERI_ETIKET['Bekle']}"

    kz = pd_.kar_zarar_pct
    alis = pd_.alim_birim
    guncel = pd_.guncel_birim
    stop = _pozisyon_stop(alis, guncel)

    sinyal = pozisyon_sinyal_bilgisi(
        tur, sym, tarama=tarama, tefas_ham=tefas_ham, tefas_skorlu=tefas_skorlu,
    )
    karar = sinyal["karar"]
    emir = pozisyon_emir_hesapla(kz, karar, tur=tur)
    s_obj = sinyal.get("sinyal_obj")
    usd_try = float(getattr(fx, "usd_try", 0) or 0) if fx else 0.0
    ekle = _pozisyon_ekle_fiyat(
        tur, sym, alis, guncel, tarama, s_obj, usd_try=usd_try,
    )

    h = s_obj if getattr(s_obj, "sembol", None) else tarama_hisse_bul(
        tarama, _EMTIA_TARAMA.get(tur, sym) or sym,
    )
    qc = getattr(h, "quote_currency", "") if h else ""
    src_pb = pd_.para or p.para_birimi or ""
    if tur == "tefas" and not src_pb:
        src_pb = "TL"

    def _f(x):
        return _fmt_poz_birim(
            x, tur, sym, gosterim_pb, fx, quote_currency=qc, kaynak_pb=src_pb,
        )

    skor = sinyal.get("skor")
    skor_p = f" · Skor {int(round(float(skor)))}" if skor is not None else ""
    karar_p = f" · {karar}" if karar and karar != "—" else ""

    emir_l = POZ_ONERI_ETIKET.get(emir, emir)

    if emir == "Kâr Al":
        return (
            f"🟡 {emir_l}{karar_p}{skor_p} · K/Z {kz:+.1f}% · "
            f"kademeli realizasyon · Stop: {_f(stop)} altı"
        )
    if emir == "Sat":
        return (
            f"🟡 {emir_l}{karar_p}{skor_p} · K/Z {kz:+.1f}% · "
            f"Stop: {_f(stop)} altı"
        )
    if emir == "Azalt":
        return (
            f"🟡 {emir_l}{karar_p}{skor_p} · K/Z {kz:+.1f}% · "
            f"pozisyon küçült · Stop: {_f(stop)} altı"
        )
    if emir == "Ekle":
        ekle_p = _f(ekle) if ekle is not None else "—"
        return f"🟡 {emir_l}{karar_p}{skor_p} · {ekle_p} · Stop: {_f(stop)} altı"
    if emir == "Bekle":
        parca = f"⚪ {emir_l}{karar_p}{skor_p}"
        if ekle is not None and ekle < guncel * 0.995:
            parca += f" · dip Ekle: {_f(ekle)}"
        parca += f" · Stop: {_f(stop)} altı"
        return parca

    parcalar = [f"🟢 {emir_l}{karar_p}{skor_p}", f"Stop: {_f(stop)} altı"]
    if ekle is not None and ekle < guncel * 0.995:
        parcalar.insert(1, f"Ekle: {_f(ekle)}")
    return " · ".join(parcalar)
