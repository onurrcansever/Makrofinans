# -*- coding: utf-8 -*-
"""
Endeks platform yönlendirme — hisse/ETF sinyal motorundan bağımsız.

Çıktı: aksiyon (Artır/Koru/Azalt/Bekle) + kurulum + güven.
Eski `sinyal` alanı yalnızca geriye uyum için map edilir; UI yeni kolonları kullanır.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence


AKSIYON_ETIKET = {
    "ARTIR": "Artır",
    "KORU": "Koru",
    "AZALT": "Azalt",
    "BEKLE": "Bekle",
}

# Kurulum etiketleri (alım pazarlaması yok)
KURULUM_ASIRI = "Aşırı ısınma"
KURULUM_TREND_CEKILME = "Trend içi geri çekilme"
KURULUM_TREND = "Trend devam"
KURULUM_ZAYIF = "Zayıf momentum"
KURULUM_NOTR = "Nötr"
KURULUM_VERI = "Veri zayıf"

TR_SEMBOLLER = frozenset({"XU100.IS"})
ABD_SEMBOLLER = frozenset({"^GSPC", "^IXIC", "^NDX"})

_AKSIYON_RANK = {"ARTIR": 4, "KORU": 3, "BEKLE": 2, "AZALT": 1}


@dataclass(frozen=True)
class EndeksKarar:
    platform: str
    aksiyon: str
    aksiyon_etiket: str
    kurulum: str
    guven: float
    gerekce: str
    skor: float
    sinyal: str  # legacy SINYAL_ETIKET anahtarı
    teknik_aksiyon: str = "BEKLE"
    teknik_aksiyon_etiket: str = "Bekle"
    makro_chip: str = "Makro: nötr"
    makro_not: str = ""


_AKSIYON_SIRA = ("AZALT", "BEKLE", "KORU", "ARTIR")


def _aksiyon_tavan(aksiyon: str, tavan: str) -> str:
    """Aksiyonu tavanın üstüne çıkarma (ARTIR → KORU gibi)."""
    try:
        i = _AKSIYON_SIRA.index(aksiyon)
        j = _AKSIYON_SIRA.index(tavan)
    except ValueError:
        return aksiyon
    return _AKSIYON_SIRA[min(i, j)]


def makro_kapisi(
    teknik_aksiyon: str,
    platform: str,
    *,
    makro_rejim: str = "NOTR",
    snap=None,
    ppk_gun: Optional[int] = None,
    fomc_gun: Optional[int] = None,
) -> tuple:
    """
    Teknik adayı makro ile tavanla.
    Dönüş: (aksiyon, guven_delta, makro_chip, makro_not)
    """
    aksiyon = teknik_aksiyon
    delta = 0.0
    notlar: List[str] = []
    rejim = (makro_rejim or "NOTR").upper()

    if rejim in ("KRIZ", "EM_STRES"):
        once = aksiyon
        aksiyon = _aksiyon_tavan(aksiyon, "BEKLE")
        delta -= 18
        if once != aksiyon:
            notlar.append(f"{rejim}: Artır yasak → {AKSIYON_ETIKET.get(aksiyon, aksiyon)}")
        else:
            notlar.append(f"{rejim}: risk tavanı")
    elif rejim == "TL_FIRSAT":
        if platform == "ABD" and aksiyon == "ARTIR":
            aksiyon = "KORU"
            delta -= 5
            notlar.append("TL_FIRSAT: ABD Artır → Koru")
        elif platform == "TR":
            delta += 4
            notlar.append("TL_FIRSAT: BIST destek")
    elif rejim == "RISK_ON":
        if platform == "ABD":
            delta += 6
            notlar.append("RISK_ON: ABD destek")
        else:
            delta += 2
            notlar.append("RISK_ON: BIST sınırlı destek")
    elif rejim == "ENFLASYON_KORUMA":
        if aksiyon == "ARTIR":
            aksiyon = "KORU"
            delta -= 6
            notlar.append("ENFLASYON: hisse endeksi Artır → Koru")
        else:
            notlar.append("ENFLASYON_KORUMA")

    v = getattr(snap, "veri", snap) if snap is not None else None
    cds = getattr(v, "cds_5y_bp", None) if v is not None else None
    try:
        cds_f = float(cds) if cds is not None else None
    except (TypeError, ValueError):
        cds_f = None
    if cds_f is not None and cds_f >= 350:
        once = aksiyon
        aksiyon = _aksiyon_tavan(aksiyon, "KORU" if cds_f < 450 else "BEKLE")
        delta -= 12 if cds_f < 450 else 18
        if once != aksiyon:
            notlar.append(f"CDS {cds_f:.0f}bp: tavan {AKSIYON_ETIKET.get(aksiyon, aksiyon)}")
        else:
            notlar.append(f"CDS {cds_f:.0f}bp yüksek")

    vix = getattr(snap, "vix", None) if snap is not None else None
    if vix is None and v is not None:
        vix = getattr(v, "vix", None)
    try:
        vix_f = float(vix) if vix is not None else None
    except (TypeError, ValueError):
        vix_f = None
    if platform == "ABD" and vix_f is not None and vix_f >= 28:
        once = aksiyon
        aksiyon = _aksiyon_tavan(aksiyon, "KORU")
        delta -= 10
        if once != aksiyon:
            notlar.append(f"VIX {vix_f:.0f}: ABD Artır → Koru")
        else:
            notlar.append(f"VIX {vix_f:.0f} yüksek")

    if platform == "TR" and ppk_gun is not None and 0 <= ppk_gun <= 5 and aksiyon == "ARTIR":
        aksiyon = "KORU"
        delta -= 8
        notlar.append(f"PPK {ppk_gun}g: Artır → Koru")
    if platform == "ABD" and fomc_gun is not None and 0 <= fomc_gun <= 5 and aksiyon == "ARTIR":
        aksiyon = "KORU"
        delta -= 8
        notlar.append(f"FOMC {fomc_gun}g: Artır → Koru")

    if not notlar:
        chip = "Makro: nötr"
        notu = ""
    elif aksiyon != teknik_aksiyon:
        chip = f"Makro: {AKSIYON_ETIKET.get(aksiyon, aksiyon)} tavan"
        notu = "; ".join(notlar)
    else:
        chip = f"Makro: {notlar[0].split(':')[0]}"
        notu = "; ".join(notlar)

    return aksiyon, delta, chip, notu


def platform_for(sembol: str) -> str:
    s = (sembol or "").upper()
    if s in TR_SEMBOLLER or s.endswith(".IS"):
        return "TR"
    if s in ABD_SEMBOLLER:
        return "ABD"
    return "DIGER"


def _kurulum(
    fiyat: float,
    rsi: Optional[float],
    sma20: Optional[float],
    sma50: Optional[float],
    sma200: Optional[float],
) -> str:
    if rsi is None or sma50 is None or fiyat <= 0:
        return KURULUM_VERI
    if rsi > 72:
        return KURULUM_ASIRI
    dusen = sma20 is not None and sma20 < sma50 and fiyat < sma50
    if rsi < 28 and (fiyat < sma50 * 0.92 or dusen):
        return KURULUM_ZAYIF
    trend_yukari = (
        (sma20 is not None and sma20 > sma50)
        or (sma200 is not None and fiyat > sma200 and fiyat > sma50)
    )
    if 28 <= rsi <= 48 and trend_yukari and fiyat >= sma50 * 0.94:
        return KURULUM_TREND_CEKILME
    if 28 <= rsi <= 48 and (fiyat < sma50 or dusen):
        return KURULUM_ZAYIF
    if 42 < rsi <= 62 and fiyat > sma50:
        if sma20 is not None and sma20 > sma50:
            return KURULUM_TREND
        return KURULUM_TREND_CEKILME if fiyat < sma50 * 1.02 else KURULUM_TREND
    if (
        40 <= rsi <= 58
        and sma20 is not None
        and sma50 is not None
        and sma20 > sma50
        and fiyat >= sma50 * 0.96
    ):
        return KURULUM_TREND_CEKILME
    return KURULUM_NOTR


def _dusen_trend(
    fiyat: float,
    sma20: Optional[float],
    sma50: Optional[float],
    sma200: Optional[float],
) -> bool:
    if sma50 is None or fiyat <= 0:
        return False
    if fiyat < sma50 and sma20 is not None and sma20 < sma50:
        return True
    if sma200 is not None and fiyat < sma50 < sma200:
        return True
    return False


def _aksiyon(
    kurulum: str,
    *,
    fiyat: float,
    sma50: Optional[float],
    sma20: Optional[float],
    sma200: Optional[float],
    degisim_1ay: Optional[float],
    degisim_3ay: Optional[float],
) -> str:
    if kurulum == KURULUM_VERI:
        return "BEKLE"
    if kurulum == KURULUM_ASIRI:
        return "AZALT"

    dusen = _dusen_trend(fiyat, sma20, sma50, sma200)
    d1 = degisim_1ay if degisim_1ay is not None else 0.0
    d3 = degisim_3ay if degisim_3ay is not None else 0.0

    if dusen:
        if d3 <= -8 or d1 <= -5:
            return "AZALT"
        return "BEKLE"

    if kurulum == KURULUM_ZAYIF:
        if d3 <= -5 or d1 <= -4:
            return "AZALT" if d3 <= -10 else "BEKLE"
        return "BEKLE"

    if kurulum == KURULUM_TREND_CEKILME:
        if d3 >= 3 and d1 > -6:
            return "ARTIR"
        if d3 >= 0 or (sma50 is not None and fiyat >= sma50 * 0.98):
            return "KORU"
        return "BEKLE"

    if kurulum == KURULUM_TREND:
        if d3 >= 5 and d1 > -4:
            return "ARTIR"
        if d3 >= 0:
            return "KORU"
        return "BEKLE"

    # Nötr
    if sma50 is not None and fiyat > sma50 and d3 >= 2:
        return "KORU"
    if d3 <= -8:
        return "AZALT"
    return "BEKLE"


def _guven(
    *,
    kurulum: str,
    rsi: Optional[float],
    sma50: Optional[float],
    fx_ok: bool,
    degisim_3ay: Optional[float],
) -> float:
    g = 72.0
    if kurulum == KURULUM_VERI or rsi is None or sma50 is None:
        g = 25.0
    elif kurulum == KURULUM_NOTR:
        g -= 8
    elif kurulum in (KURULUM_TREND, KURULUM_TREND_CEKILME):
        g += 8
    elif kurulum == KURULUM_ZAYIF:
        g -= 5
    if degisim_3ay is None:
        g -= 10
    if not fx_ok:
        g = min(g, 40.0)
    return max(0.0, min(100.0, g))


def _legacy_sinyal(aksiyon: str, kurulum: str) -> str:
    if kurulum == KURULUM_VERI:
        return "VERI_YOK"
    if aksiyon == "AZALT" and kurulum == KURULUM_ASIRI:
        return "ASIRI_ALIM"
    if aksiyon == "AZALT":
        return "BEKLE"
    if aksiyon == "ARTIR":
        return "TREND_ALIM"
    if aksiyon == "KORU" and kurulum in (KURULUM_TREND, KURULUM_TREND_CEKILME):
        return "TREND_ALIM"
    return "BEKLE"


def _skor(aksiyon: str, guven: float, degisim_3ay: Optional[float]) -> float:
    base = {"ARTIR": 72.0, "KORU": 58.0, "BEKLE": 48.0, "AZALT": 35.0}.get(aksiyon, 50.0)
    if degisim_3ay is not None:
        if 5 <= degisim_3ay <= 40:
            base += 6
        elif degisim_3ay < -10:
            base -= 8
    # Güven ile hafif hizala (hisse skorundan bağımsız ölçek)
    return max(0.0, min(100.0, 0.65 * base + 0.35 * guven))


def karar(
    *,
    sembol: str,
    fiyat: float,
    rsi: Optional[float],
    sma20: Optional[float],
    sma50: Optional[float],
    sma200: Optional[float] = None,
    degisim_1ay: Optional[float] = None,
    degisim_3ay: Optional[float] = None,
    fx_ok: bool = True,
    makro_rejim: str = "NOTR",
    snap=None,
    ppk_gun: Optional[int] = None,
    fomc_gun: Optional[int] = None,
) -> EndeksKarar:
    """Teknik fırsat → makro kapı/tavan → güven."""
    platform = platform_for(sembol)
    kurulum = _kurulum(fiyat, rsi, sma20, sma50, sma200)
    teknik = _aksiyon(
        kurulum,
        fiyat=fiyat,
        sma50=sma50,
        sma20=sma20,
        sma200=sma200,
        degisim_1ay=degisim_1ay,
        degisim_3ay=degisim_3ay,
    )
    guven = _guven(
        kurulum=kurulum, rsi=rsi, sma50=sma50, fx_ok=fx_ok, degisim_3ay=degisim_3ay,
    )
    if not fx_ok and teknik == "ARTIR":
        teknik = "KORU" if kurulum in (KURULUM_TREND, KURULUM_TREND_CEKILME) else "BEKLE"
        guven = min(guven, 40.0)

    if ppk_gun is None or fomc_gun is None:
        try:
            from ppk_awareness import ppk_fomc_durumu
            d = ppk_fomc_durumu()
            if ppk_gun is None:
                ppk_gun = d.ppk_gun
            if fomc_gun is None:
                fomc_gun = d.fomc_gun
        except Exception:
            pass

    aksiyon, g_delta, makro_chip, makro_not = makro_kapisi(
        teknik,
        platform,
        makro_rejim=makro_rejim,
        snap=snap,
        ppk_gun=ppk_gun,
        fomc_gun=fomc_gun,
    )
    guven = max(0.0, min(100.0, guven + g_delta))

    parts = [kurulum]
    if rsi is not None:
        parts.append(f"RSI {rsi:.0f}")
    if degisim_3ay is not None:
        parts.append(f"3A {degisim_3ay:+.1f}%")
    if not fx_ok:
        parts.append("kur verisi zayıf")
    if makro_not:
        parts.append(makro_not)
    gerekce = " · ".join(parts)

    return EndeksKarar(
        platform=platform,
        aksiyon=aksiyon,
        aksiyon_etiket=AKSIYON_ETIKET.get(aksiyon, aksiyon),
        kurulum=kurulum,
        guven=round(guven, 0),
        gerekce=gerekce,
        skor=round(_skor(aksiyon, guven, degisim_3ay), 0),
        sinyal=_legacy_sinyal(aksiyon, kurulum),
        teknik_aksiyon=teknik,
        teknik_aksiyon_etiket=AKSIYON_ETIKET.get(teknik, teknik),
        makro_chip=makro_chip,
        makro_not=makro_not,
    )


def _grup_skoru(items: Sequence) -> Optional[float]:
    """EndeksOzet veya benzeri: 3A ortanca + aksiyon rank."""
    if not items:
        return None
    d3s = [float(x.degisim_3ay) for x in items if getattr(x, "degisim_3ay", None) is not None]
    ranks = [_AKSIYON_RANK.get(getattr(x, "aksiyon", "BEKLE"), 2) for x in items]
    med_d3 = sorted(d3s)[len(d3s) // 2] if d3s else 0.0
    med_rank = sorted(ranks)[len(ranks) // 2] if ranks else 2
    return med_d3 + med_rank * 2.0


def oncelik_ozeti(endeksler: Sequence) -> str:
    """
    TR vs ABD grup skoruna göre tek satır özet.
    `endeksler`: aksiyon + degisim_3ay + platform (+ sembol/ad) alanlı nesneler.
    """
    if not endeksler:
        return ""
    tr = [e for e in endeksler if getattr(e, "platform", "") == "TR"]
    abd = [e for e in endeksler if getattr(e, "platform", "") == "ABD"]
    if not tr and not abd:
        return ""

    s_tr = _grup_skoru(tr)
    s_abd = _grup_skoru(abd)
    if s_tr is None and s_abd is None:
        return ""
    if s_abd is None:
        return "Bugün öncelik: TR (BIST) — ABD verisi yok"
    if s_tr is None:
        return "Bugün öncelik: ABD — TR verisi yok"

    # En iyi ABD satırı etiketi
    abd_sorted = sorted(
        abd,
        key=lambda e: (
            _AKSIYON_RANK.get(getattr(e, "aksiyon", "BEKLE"), 0),
            float(getattr(e, "degisim_3ay") or -999),
        ),
        reverse=True,
    )
    top = abd_sorted[0] if abd_sorted else None
    abd_label = "ABD"
    if top is not None:
        ad = (getattr(top, "ad", "") or getattr(top, "sembol", "") or "").strip()
        if "NASDAQ 100" in ad or getattr(top, "sembol", "") == "^NDX":
            abd_label = "ABD (NDX)"
        elif "S&P" in ad or getattr(top, "sembol", "") == "^GSPC":
            abd_label = "ABD (SPX)"
        elif "NASDAQ" in ad:
            abd_label = "ABD (IXIC)"

    # Gerekçe ipucu
    if s_abd > s_tr + 1.5:
        tip = "3A göreli güç + kurulum"
        return f"Bugün öncelik: {abd_label} > BIST — gerekçe: {tip}"
    if s_tr > s_abd + 1.5:
        tip = "3A göreli güç + kurulum"
        return f"Bugün öncelik: BIST > ABD — gerekçe: {tip}"
    return "Bugün öncelik: dengeli (TR ≈ ABD) — gerekçe: göreli güç yakın"


def ozet_neden(
    e,
    *,
    gosterim_1ay: Optional[float] = None,
    gosterim_3ay: Optional[float] = None,
    gosterim_pb: str = "",
) -> str:
    """
    Tek satır insan dili.
    Gösterim getirileri (EUR/TL tablo) verilirse Neden onlarla yazılır —
    native bar % ile tablo sütunu çelişmesin.
    """
    teknik = (getattr(e, "teknik_aksiyon", None) or getattr(e, "aksiyon", "") or "BEKLE").upper()
    aksiyon = (getattr(e, "aksiyon", None) or "BEKLE").upper()
    kurulum = (getattr(e, "kurulum", None) or "").strip()
    makro_not = (getattr(e, "makro_not", None) or "").strip()
    chip = (getattr(e, "makro_chip", None) or "").strip()
    platform = (getattr(e, "platform", None) or platform_for(getattr(e, "sembol", "") or "")).upper()

    # Tablo ile aynı sayılar öncelikli
    d1_src = gosterim_1ay if gosterim_1ay is not None else getattr(e, "degisim_1ay", None)
    d3_src = gosterim_3ay if gosterim_3ay is not None else getattr(e, "degisim_3ay", None)
    try:
        d1f = float(d1_src) if d1_src is not None else None
    except (TypeError, ValueError):
        d1f = None
    try:
        d3f = float(d3_src) if d3_src is not None else None
    except (TypeError, ValueError):
        d3f = None

    pb_etiket = f" {gosterim_pb}" if gosterim_pb else ""

    if kurulum == "Trend içi geri çekilme":
        if d1f is not None and d1f >= 0:
            kur_kisa = "trend devam, 1A pozitif"
        elif d1f is not None and d1f > -3:
            kur_kisa = "sığ geri çekilme"
        else:
            kur_kisa = "trend içi geri çekilme"
    elif kurulum == "Trend devam":
        kur_kisa = "trend devam"
    elif kurulum == "Zayıf momentum":
        # Gösterimde 3A güçlüyse "zayıf" yanıltıcı — yumuşat
        if d3f is not None and d3f >= 5:
            kur_kisa = "kısa vade zayıf, orta vade güçlü"
        else:
            kur_kisa = "zayıf momentum"
    elif kurulum == "Nötr":
        kur_kisa = "nötr kurulum"
    elif kurulum == "Aşırı ısınma":
        kur_kisa = "aşırı ısınma"
    elif kurulum == "Veri zayıf":
        kur_kisa = "veri zayıf"
    else:
        kur_kisa = kurulum.lower() if kurulum else "nötr"

    mom = ""
    if d3f is not None:
        mom = f"3A{pb_etiket} {d3f:+.1f}%"
        if d1f is not None:
            mom += f", 1A{pb_etiket} {d1f:+.1f}%"

    if teknik != aksiyon and teknik == "ARTIR" and aksiyon == "KORU":
        neden_makro = "makro tavan (yeni alım yok)"
        if "TL_FIRSAT" in makro_not or "TL_FIRSAT" in chip:
            if platform == "ABD":
                neden_makro = "TL fırsat rejimi — ABD'de agresif ekleme yok"
            else:
                neden_makro = "TL fırsat rejimi — temkinli tut"
        elif "FOMC" in makro_not:
            neden_makro = "FOMC yakındır"
        elif "VIX" in makro_not:
            neden_makro = "VIX yüksek"
        elif "CDS" in makro_not:
            neden_makro = "CDS yüksek"
        elif "KRIZ" in makro_not or "EM_STRES" in makro_not:
            neden_makro = "stres rejimi"
        base = f"Grafik uygun ({kur_kisa}"
        if mom:
            base += f"; {mom}"
        return f"{base}); {neden_makro} → tut."

    if teknik != aksiyon and aksiyon == "BEKLE":
        return f"Grafik {AKSIYON_ETIKET.get(teknik, teknik).lower()} derdi; makro beklemeyi istedi."

    if aksiyon == "ARTIR":
        ekstra = f" — {mom}" if mom else ""
        return f"Grafik + makro uyumlu — kademeli artır ({kur_kisa}{ekstra})."
    if aksiyon == "KORU":
        ekstra = f"; {mom}" if mom else ""
        return f"Mevcut ağırlığı koru ({kur_kisa}{ekstra})."
    if aksiyon == "AZALT":
        return f"Ağırlığı azalt ({kur_kisa or 'risk'})."
    ekstra = f"; {mom}" if mom else ""
    return f"Bekle — net fırsat yok ({kur_kisa}{ekstra})."

def oncelik_ozeti_sade(endeksler: Sequence) -> str:
    """Üst bant — daha sade dil."""
    ham = oncelik_ozeti(endeksler)
    if not ham:
        return ""
    if "ABD" in ham and "BIST" in ham and ">" in ham and ham.index("ABD") < ham.index("BIST"):
        return "Bugün bakılacak yer: **ABD** (BIST’ten göreli daha güçlü). Yine de makro tavan varsa sadece tut."
    if "BIST" in ham and "ABD" in ham and ham.index("BIST") < ham.index("ABD"):
        return "Bugün bakılacak yer: **BIST** (ABD’den göreli daha güçlü)."
    if "dengeli" in ham:
        return "Bugün TR ve ABD birbirine yakın — tek yöne agresif kayma yok."
    return ham


def endeks_eksik_mi(e) -> bool:
    """Eski önbellek: kurulum/güven/platform doldurulmamış."""
    if not (getattr(e, "kurulum", None) or "").strip():
        return True
    if float(getattr(e, "guven", 0) or 0) <= 0:
        return True
    if not (getattr(e, "platform", None) or "").strip():
        return True
    return False


def _sma_proxy(
    fiyat: float,
    rsi: Optional[float],
    degisim_1ay: Optional[float],
    degisim_3ay: Optional[float],
) -> tuple:
    """SMA yoksa (eski cache) 3A/RSI ile kabaca yapı — yalnızca doldurma için."""
    d3 = degisim_3ay if degisim_3ay is not None else 0.0
    if d3 > 2:
        # Yükselen trendde geri çekilme ihtimali
        sma50 = fiyat * 0.985
        sma20 = fiyat * (1.002 if rsi is not None and rsi < 50 else 1.01)
        sma200 = fiyat * 0.90
    elif d3 < -2:
        sma50 = fiyat * 1.025
        sma20 = fiyat * 1.01
        sma200 = fiyat * 1.06
    else:
        sma50 = fiyat * 1.0
        sma20 = fiyat * 0.998
        sma200 = fiyat * 0.95
    return sma20, sma50, sma200


def endeks_alanlarini_doldur(
    endeksler: Sequence,
    *,
    fx_ok: bool = True,
    makro_rejim: str = "NOTR",
    snap=None,
) -> None:
    """
    Eski session/disk tarama nesnelerinde aksiyon/kurulum/güven boşsa yerinde doldur.
    Hisse listesine dokunmaz; yalnızca endeks satırları.
    """
    for e in endeksler:
        # Makro chip yoksa da yeniden hesapla (eski cache)
        makro_eksik = not (getattr(e, "makro_chip", None) or "").strip()
        if not endeks_eksik_mi(e) and not makro_eksik:
            continue
        fiyat = getattr(e, "fiyat", None)
        if fiyat is None or float(fiyat) <= 0:
            e.platform = platform_for(getattr(e, "sembol", "") or "")
            e.aksiyon = "BEKLE"
            e.aksiyon_etiket = AKSIYON_ETIKET["BEKLE"]
            e.kurulum = KURULUM_VERI
            e.guven = 0.0
            e.gerekce = "Fiyat yok"
            e.sinyal = "VERI_YOK"
            e.teknik_aksiyon = "BEKLE"
            e.teknik_aksiyon_etiket = "Bekle"
            e.makro_chip = "Makro: nötr"
            e.makro_not = ""
            continue

        sma20 = getattr(e, "sma20", None)
        sma50 = getattr(e, "sma50", None)
        sma200 = getattr(e, "sma200", None)
        if sma50 is None:
            sma20, sma50, sma200 = _sma_proxy(
                float(fiyat),
                getattr(e, "rsi", None),
                getattr(e, "degisim_1ay", None),
                getattr(e, "degisim_3ay", None),
            )

        k = karar(
            sembol=getattr(e, "sembol", "") or "",
            fiyat=float(fiyat),
            rsi=getattr(e, "rsi", None),
            sma20=sma20,
            sma50=sma50,
            sma200=sma200,
            degisim_1ay=getattr(e, "degisim_1ay", None),
            degisim_3ay=getattr(e, "degisim_3ay", None),
            fx_ok=fx_ok,
            makro_rejim=makro_rejim or getattr(e, "makro_rejim", None) or "NOTR",
            snap=snap,
        )
        e.platform = k.platform
        e.aksiyon = k.aksiyon
        e.aksiyon_etiket = k.aksiyon_etiket
        e.kurulum = k.kurulum
        e.guven = k.guven
        e.gerekce = k.gerekce
        e.skor = k.skor
        e.sinyal = k.sinyal
        e.teknik_aksiyon = k.teknik_aksiyon
        e.teknik_aksiyon_etiket = k.teknik_aksiyon_etiket
        e.makro_chip = k.makro_chip
        e.makro_not = k.makro_not
        if getattr(e, "sma50", None) is None:
            e.sma20 = sma20
            e.sma50 = sma50
            e.sma200 = sma200
