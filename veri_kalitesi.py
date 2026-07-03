# -*- coding: utf-8 -*-
"""
Veri Kalitesi Katmanı
======================
Her gösterge için kaynak, tazelik, kalite sınıfı ve eksik veri politikası.
Kurumsal veri şeffaflığı — ham istatistik sağlayıcı değil, meta veri disiplini.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from macro_data import MacroSnapshot

KALITE_ETIKET = {
    "CANLI": "Canlı API",
    "GECIKMELI": "Gecikmeli",
    "PROXY": "Model / proxy",
    "MANUEL": "Manuel giriş",
    "YEDEK": "Yedek / güvensiz",
    "EKSIK": "Eksik",
}

KALITE_AGIRLIK = {
    "CANLI": 1.0,
    "GECIKMELI": 0.75,
    "PROXY": 0.45,
    "MANUEL": 0.55,
    "YEDEK": 0.25,
    "EKSIK": 0.0,
}

# (anahtar, etiket, deger_fn, max_tazelik_saat, eksik_politikasi)
_GOSTERGE_TANIM: List[Tuple[str, str, Callable, int, str]] = []


def _tanimla(
    anahtar: str,
    etiket: str,
    deger_fn: Callable[[MacroSnapshot], Any],
    max_saat: int,
    politika: str,
) -> None:
    _GOSTERGE_TANIM.append((anahtar, etiket, deger_fn, max_saat, politika))


_tanimla("eur_try", "EUR/TRY", lambda s: s.veri.eur_try, 24, "Frankfurter yedek; kur yoksa 4 kapı hesaplanamaz.")
_tanimla("usd_try", "USD/TRY", lambda s: s.veri.usd_try, 24, "EUR/TRY ile türetilebilir.")
_tanimla("altin", "Altın (USD/oz)", lambda s: s.altin_usd_oz, 48, "FRED/yfinance yedek; altın tahsisi etkilenir.")
_tanimla("gumus", "Gümüş (USD/oz)", lambda s: s.gumus_usd_oz, 48, "Altın oranından türetilebilir.")
_tanimla("vix", "VIX", lambda s: s.vix, 48, "Rejim ve CDS proxy için kullanılır.")
_tanimla("bist100", "BIST 100", lambda s: s.bist100, 48, "Yahoo gecikmeli; BIST tahsisi etkilenir.")
_tanimla("btc", "Bitcoin", lambda s: s.btc_usd, 48, "Kripto tahsisi etkilenir.")
_tanimla("cds", "CDS 5Y (bp)", lambda s: s.veri.cds_5y_bp, 24, "Proxy/model — EVDS veya manuel teyit önerilir.")
_tanimla("enflasyon", "Enflasyon TR (%)", lambda s: s.enflasyon_tr_yillik, 720, "EVDS/TÜİK aylık; yoksa son bilinen.")
_tanimla("tl_mevduat", "TL mevduat (brüt)", lambda s: s.veri.tl_mevduat_brut_faiz, 168, "Yapı Kredi yoksa TCMB türetilmiş.")
_tanimla("fed_faizi", "Fed fon faizi", lambda s: s.veri.fed_faizi, 168, "FRED yoksa ^IRX veya sabit yedek.")
_tanimla("tcmb_faizi", "TCMB politika faizi", lambda s: s.veri.tcmb_politika_faizi, 168, "EVDS yoksa son bilinen.")
_tanimla("siyasi_risk", "Siyasi risk (haber)", lambda s: s.veri.siyasi_risk_makale_sayisi, 6, "GDELT 6 saat önbellek.")
_tanimla("rezerv", "Rezerv trend", lambda s: s.veri.rezerv_artiyor, 720, "EVDS; bilinmiyorsa Kapı 4 ×0,85.")


def _siniflandir(kaynak: str, deger: Any, anahtar: str = "") -> str:
    if deger is None or kaynak in ("—", "?", "", None):
        return "EKSIK"
    k = (kaynak or "").lower()

    # Göstergeye özel — kaynak metninden bağımsız doğru sınıf
    if anahtar == "enflasyon":
        if "evds" in k or "tüik" in k:
            return "GECIKMELI" if "önbellek" in k else "CANLI"
        if any(x in k for x in ("world bank", "fred", "yıllık")):
            return "GECIKMELI"
    if anahtar == "fed_faizi":
        if "dff" in k and "irx" not in k:
            return "GECIKMELI" if "önbellek" in k else "CANLI"
        if "irx" in k or "proxy" in k or "hazine" in k:
            return "PROXY"
    if anahtar == "tcmb_faizi":
        if "evds" in k:
            return "GECIKMELI" if "önbellek" in k else "CANLI"
        if any(x in k for x in ("ykb", "türetilmiş", "tahmin", "proxy", "banka proxy")):
            return "PROXY"
        if "manual" in k or "manuel" in k:
            return "MANUEL"

    if any(x in k for x in ("manuel", "manual", "manual_inputs")):
        return "MANUEL"
    if any(x in k for x in (
        "piyasa modeli", "proxy", "türetilmiş", "türetilm", "hesaplanan", "irx",
    )):
        return "PROXY"
    if any(x in k for x in ("world bank", "fred", "yıllık")):
        return "GECIKMELI"
    if any(x in k for x in ("acil yedek", "ulaşılamadı", "güvensiz", "guvensiz")):
        return "YEDEK"
    if any(x in k for x in ("yahoo", "gecikme", "gecikmeli")):
        return "GECIKMELI"
    if "demo" in k:
        return "PROXY"
    if "önbellek" in k:
        return "GECIKMELI"
    return "CANLI"


def _tazelik_saat(veri_zamani: str) -> Optional[float]:
    try:
        dt = datetime.fromisoformat(veri_zamani.replace("Z", "+00:00"))
        return max(0.0, (datetime.now() - dt.replace(tzinfo=None)).total_seconds() / 3600)
    except (ValueError, TypeError):
        return None


@dataclass
class VeriGostergeMeta:
    anahtar: str
    etiket: str
    deger: Any
    deger_gosterim: str
    kaynak: str
    kalite: str
    kalite_etiket: str
    tazelik_saat: Optional[float]
    tazelik_durum: str  # TAZE | ESKI | BILINMIYOR
    eksik_politikasi: str
    uyari: str = ""


@dataclass
class VeriKaliteRaporu:
    gostergeler: List[VeriGostergeMeta] = field(default_factory=list)
    genel_skor: float = 0.0  # 0-100
    genel_duzey: str = "ORTA"  # YUKSEK | ORTA | DUSUK
    ozet: str = ""
    uyarilar: List[str] = field(default_factory=list)
    veri_zamani: str = ""
    mod: str = ""


def _deger_str(deger: Any, anahtar: str) -> str:
    if deger is None:
        return "—"
    if anahtar == "rezerv":
        if deger is True:
            return "Artıyor"
        if deger is False:
            return "Azalıyor"
        return "Bilinmiyor"
    if anahtar == "tl_mevduat" and isinstance(deger, (int, float)):
        pct = deger * 100 if deger <= 1 else deger
        return f"%{pct:.1f}"
    if isinstance(deger, bool):
        return "Evet" if deger else "Hayır"
    if isinstance(deger, float):
        if anahtar in ("eur_try", "usd_try", "bist100", "btc", "altin", "gumus", "vix"):
            return f"{deger:,.2f}" if deger < 10000 else f"{deger:,.0f}"
        return f"{deger:.1f}"
    return str(deger)


def veri_kalite_olustur(snap: MacroSnapshot) -> VeriKaliteRaporu:
    kh = snap.kaynak_haritasi or {}
    tazelik = _tazelik_saat(snap.veri_zamani)
    gostergeler: List[VeriGostergeMeta] = []
    uyarilar: List[str] = []

    if snap.veri_kaynak == "demo":
        uyarilar.append("Demo modu — makro senaryo sabit; kalite skoru düşük sayılır.")

    agirlik_toplam = 0.0
    agirlik_say = 0

    for anahtar, etiket, deger_fn, max_saat, politika in _GOSTERGE_TANIM:
        deger = deger_fn(snap)
        kaynak = kh.get(anahtar, "—")
        kalite = _siniflandir(kaynak, deger, anahtar)
        if snap.veri_kaynak == "demo" and kalite == "CANLI" and anahtar in (
            "cds", "enflasyon", "tcmb_faizi", "tl_mevduat", "fed_faizi",
        ):
            kalite = "PROXY"

        tz_durum = "BILINMIYOR"
        uyari = ""
        if tazelik is not None:
            if tazelik <= max_saat:
                tz_durum = "TAZE"
            else:
                tz_durum = "ESKI"
                uyari = f"Veri {tazelik:.0f} saat önce — eşik {max_saat} saat"
        if kalite in ("PROXY", "YEDEK", "EKSIK"):
            uyari = uyari or f"{KALITE_ETIKET[kalite]} — {politika}"

        gostergeler.append(
            VeriGostergeMeta(
                anahtar=anahtar,
                etiket=etiket,
                deger=deger,
                deger_gosterim=_deger_str(deger, anahtar),
                kaynak=kaynak or "—",
                kalite=kalite,
                kalite_etiket=KALITE_ETIKET[kalite],
                tazelik_saat=tazelik,
                tazelik_durum=tz_durum,
                eksik_politikasi=politika,
                uyari=uyari,
            )
        )
        if deger is not None:
            agirlik_toplam += KALITE_AGIRLIK[kalite]
            agirlik_say += 1

    genel_skor = (agirlik_toplam / agirlik_say * 100) if agirlik_say else 0.0
    if genel_skor >= 75:
        duzey = "YUKSEK"
    elif genel_skor >= 50:
        duzey = "ORTA"
    else:
        duzey = "DUSUK"

    eksik = sum(1 for g in gostergeler if g.kalite == "EKSIK")
    proxy = sum(1 for g in gostergeler if g.kalite in ("PROXY", "YEDEK"))
    if eksik:
        uyarilar.append(f"{eksik} gösterge eksik — kararlar kısmi veriyle üretiliyor.")
    if proxy >= 3:
        uyarilar.append(f"{proxy} gösterge model/yedek kaynaklı — manuel teyit önerilir.")

    ozet = (
        f"Veri kalitesi: {genel_skor:.0f}/100 ({duzey}) · "
        f"{sum(1 for g in gostergeler if g.kalite == 'CANLI')} canlı, "
        f"{proxy} proxy/yedek, {eksik} eksik"
    )

    return VeriKaliteRaporu(
        gostergeler=gostergeler,
        genel_skor=genel_skor,
        genel_duzey=duzey,
        ozet=ozet,
        uyarilar=uyarilar,
        veri_zamani=snap.veri_zamani,
        mod=snap.veri_kaynak,
    )
