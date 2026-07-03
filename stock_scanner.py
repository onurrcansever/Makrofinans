# -*- coding: utf-8 -*-
"""
Hisse & Endeks Tarayıcı
========================
Genişletilmiş evren (BIST ~32, SP500/NASDAQ ~30+, Revolut ETF ~23) · Yahoo Finance · RSI+SMA
+ makro rejim filtresi + Google News haber katmanı.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from hisse_rejim_haber import haber_filtresi_uygula, rejim_hisse_ayarla
from profil_hisse import (
    profil_firsat_esik,
    profil_firsat_sinirla,
    profil_hisse_ayarla,
    profil_tarama_bilgisi,
)
from investor_profile import YatirimProfili
from etf_universe import ETF_ETIKET, REVOLUT_ETFLER, etf_oncelik
from stock_universe import (
    ENDEKSLER,
    SEKTOR_ETIKET,
    BIST_HISSELER,
    NASDAQ_HISSELER,
    SP500_HISSELER,
    tum_evren,
    tum_hisseler,
)

SINYAL_ETIKET = {
    "ALIM_FIRSATI": "Alım fırsatı",
    "TREND_ALIM": "Trend alımı",
    "BEKLE": "Bekle",
    "ASIRI_ALIM": "Aşırı alım",
    "UZAK_DUR": "Uzak dur",
    "VERI_YOK": "Veri yok",
}

# Geriye dönük import uyumluluğu
BIST_HISSELER_LEGACY = [(s, a) for s, a, _ in BIST_HISSELER]
SP500_HISSELER_LEGACY = [(s, a) for s, a, _ in SP500_HISSELER]
NASDAQ_HISSELER_LEGACY = [(s, a) for s, a, _ in NASDAQ_HISSELER]


@dataclass
class EndeksOzet:
    ad: str
    sembol: str
    fiyat: Optional[float]
    degisim_1g: Optional[float]
    degisim_1ay: Optional[float]
    degisim_3ay: Optional[float]
    rsi: Optional[float]
    sinyal: str
    skor: float


@dataclass
class HisseAnaliz:
    sembol: str
    ad: str
    piyasa: str
    fiyat: Optional[float]
    degisim_1g: Optional[float]
    degisim_1ay: Optional[float]
    degisim_3ay: Optional[float]
    rsi: Optional[float]
    sma20: Optional[float]
    sma50: Optional[float]
    sinyal: str
    skor: float
    gerekce: str
    sektor: str = ""
    rejim_notu: str = ""
    profil_notu: str = ""
    haber_notu: str = ""
    haber_sayisi: int = 0
    teknik_skor: float = 0.0
    hikaye: str = ""
    isin: str = ""
    revolut_ticker: str = ""
    varlik_turu: str = "hisse"  # hisse | etf
    peer_yuzdelik: Optional[float] = None
    endeks_gore: Optional[float] = None
    faktor_notu: str = ""
    sma200: Optional[float] = None
    zirve_52h_pct: Optional[float] = None
    trend_notu: str = ""
    alim_uygun: str = "IZLE"
    alim_uygun_etiket: str = "⚪ İzle / bekle"
    alim_uygun_not: str = ""


@dataclass
class TaramaSonucu:
    endeksler: List[EndeksOzet] = field(default_factory=list)
    hisseler: List[HisseAnaliz] = field(default_factory=list)
    alim_firsatlari: List[HisseAnaliz] = field(default_factory=list)
    etf_firsatlari: List[HisseAnaliz] = field(default_factory=list)
    uyarilar: List[str] = field(default_factory=list)
    makro_rejim: str = ""
    tarama_ozet: str = ""
    profil_ozet: str = ""
    profil_notlari: List[str] = field(default_factory=list)


def _rsi(seri: pd.Series, period: int = 14) -> Optional[float]:
    if len(seri) < period + 1:
        return None
    delta = seri.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, 1e-10)
    val = 100 - (100 / (1 + rs))
    v = val.iloc[-1]
    return float(v) if pd.notna(v) else None


def _sma(seri: pd.Series, n: int) -> Optional[float]:
    if len(seri) < n:
        return None
    v = seri.rolling(n).mean().iloc[-1]
    return float(v) if pd.notna(v) else None


def _degisim(seri: pd.Series, gun: int) -> Optional[float]:
    if len(seri) < gun + 1:
        return None
    eski = float(seri.iloc[-gun - 1])
    yeni = float(seri.iloc[-1])
    if eski == 0:
        return None
    return (yeni - eski) / eski * 100


def _close_al(df: pd.DataFrame, sembol: str) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    try:
        if isinstance(df.columns, pd.MultiIndex):
            if sembol in df.columns.get_level_values(0):
                return df[sembol]["Close"].dropna()
        elif len(df.columns) == 1 or "Close" not in df.columns:
            return df.iloc[:, 0].dropna()
        else:
            return df["Close"].dropna()
    except Exception:
        pass
    return pd.Series(dtype=float)


def _sinyal_uret(
    fiyat: float,
    rsi: Optional[float],
    sma20: Optional[float],
    sma50: Optional[float],
) -> Tuple[str, float, str]:
    if rsi is None or sma50 is None:
        return "VERI_YOK", 0.0, "Yetersiz fiyat verisi"

    skor = 50.0
    gerekceler = []

    if 28 <= rsi <= 45:
        skor += 25
        gerekceler.append(f"RSI {rsi:.0f} — dipten dönüş bölgesi")
        sinyal = "ALIM_FIRSATI"
    elif 42 < rsi <= 62 and fiyat > sma50:
        skor += 18
        gerekceler.append(f"RSI {rsi:.0f} + fiyat SMA50 üstünde")
        sinyal = "TREND_ALIM"
    elif (
        40 <= rsi <= 58
        and sma20
        and sma50
        and sma20 > sma50
        and fiyat >= sma50 * 0.96
    ):
        skor += 16
        gerekceler.append(f"RSI {rsi:.0f} — yükselen trendde geri çekilme")
        sinyal = "TREND_ALIM"
    elif rsi > 72:
        skor -= 25
        gerekceler.append(f"RSI {rsi:.0f} — aşırı alım")
        sinyal = "ASIRI_ALIM"
    elif rsi < 25 and fiyat < sma50 * 0.90:
        skor -= 15
        gerekceler.append(f"RSI {rsi:.0f} — düşen bıçak riski")
        sinyal = "UZAK_DUR"
    else:
        sinyal = "BEKLE"
        gerekceler.append(f"RSI {rsi:.0f} — net sinyal yok")

    if sma20 and sma50:
        if sma20 > sma50 and fiyat > sma20:
            skor += 10
            gerekceler.append("Kısa vade trend yukarı")
        elif sma20 < sma50 and fiyat < sma20:
            skor -= 10
            gerekceler.append("Kısa vade trend aşağı")

    return sinyal, max(0, min(100, skor)), "; ".join(gerekceler)


def _indir(semboller: List[str], period: str = "1y") -> pd.DataFrame:
    import yfinance as yf

    if not semboller:
        return pd.DataFrame()
    parcalar = []
    batch = 35
    for i in range(0, len(semboller), batch):
        chunk = semboller[i : i + batch]
        try:
            part = yf.download(
                chunk,
                period=period,
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if not part.empty:
                parcalar.append(part)
        except Exception as e:
            print(f"[UYARI] yfinance batch {i}: {e}")
    if not parcalar:
        return pd.DataFrame()
    if len(parcalar) == 1:
        return parcalar[0]
    return pd.concat(parcalar, axis=1)


def _endeks_analiz(df: pd.DataFrame, ad: str, sym: str, makro_rejim: str, snap) -> EndeksOzet:
    close = _close_al(df, sym)
    if close.empty:
        return EndeksOzet(ad, sym, None, None, None, None, None, "VERI_YOK", 0)

    fiyat = float(close.iloc[-1])
    rsi = _rsi(close)
    sma20, sma50 = _sma(close, 20), _sma(close, 50)
    piyasa = "BIST" if sym.endswith(".IS") else "NASDAQ" if sym in ("^IXIC", "^NDX") else "SP500"
    sinyal, skor, _ = _sinyal_uret(fiyat, rsi, sma20, sma50)
    sektor = "sanayi" if piyasa == "BIST" else "teknoloji"
    rh = rejim_hisse_ayarla(sinyal, skor, "", piyasa, sektor, makro_rejim, snap)
    skor = max(0, min(100, skor + rh.skor_delta))

    return EndeksOzet(
        ad=ad,
        sembol=sym,
        fiyat=fiyat,
        degisim_1g=_degisim(close, 1),
        degisim_1ay=_degisim(close, 21),
        degisim_3ay=_degisim(close, 63),
        rsi=rsi,
        sinyal=rh.sinyal,
        skor=skor,
    )


def _hisse_analiz(
    df: pd.DataFrame,
    sembol: str,
    ad: str,
    piyasa: str,
    sektor: str,
    makro_rejim: str,
    snap,
    isin: str = "",
    revolut_ticker: str = "",
    varlik_turu: str = "hisse",
    profil: Optional[YatirimProfili] = None,
) -> HisseAnaliz:
    close = _close_al(df, sembol)
    if close.empty or len(close) < 30:
        return HisseAnaliz(
            sembol, ad, piyasa, None, None, None, None, None, None, None,
            "VERI_YOK", 0, "Veri yok", sektor=sektor,
            isin=isin, revolut_ticker=revolut_ticker, varlik_turu=varlik_turu,
        )

    fiyat = float(close.iloc[-1])
    rsi = _rsi(close)
    sma20, sma50 = _sma(close, 20), _sma(close, 50)
    sinyal, skor, gerekce = _sinyal_uret(fiyat, rsi, sma20, sma50)
    teknik_skor = skor

    from hisse_trend_filtresi import trend_filtresi_uygula
    _h = HisseAnaliz(
        sembol=sembol, ad=ad, piyasa=piyasa, fiyat=fiyat,
        degisim_1g=_degisim(close, 1), degisim_1ay=_degisim(close, 21),
        degisim_3ay=_degisim(close, 63), rsi=rsi, sma20=sma20, sma50=sma50,
        sinyal=sinyal, skor=skor, gerekce=gerekce, sektor=sektor,
        teknik_skor=teknik_skor, isin=isin, revolut_ticker=revolut_ticker,
        varlik_turu=varlik_turu,
    )
    trend_filtresi_uygula(_h, close)
    sinyal, skor, gerekce = _h.sinyal, _h.skor, _h.gerekce

    rh = rejim_hisse_ayarla(sinyal, skor, gerekce, piyasa, sektor, makro_rejim, snap)
    skor = max(0, min(100, skor + rh.skor_delta))
    sinyal = rh.sinyal
    gerekce_full = gerekce
    if rh.rejim_notu and rh.rejim_notu != "Rejim uyumlu":
        gerekce_full += f"; {rh.rejim_notu}"

    profil_notu = ""
    if profil:
        ph = profil_hisse_ayarla(sinyal, skor, piyasa, sektor, varlik_turu, profil)
        skor = max(0, min(100, skor + ph.skor_delta))
        sinyal = ph.sinyal
        profil_notu = ph.profil_notu
        if ph.profil_notu and ph.profil_notu != "Profil uyumlu":
            gerekce_full += f"; {ph.profil_notu}"

    return HisseAnaliz(
        sembol=sembol,
        ad=ad,
        piyasa=piyasa,
        fiyat=fiyat,
        degisim_1g=_degisim(close, 1),
        degisim_1ay=_degisim(close, 21),
        degisim_3ay=_degisim(close, 63),
        rsi=rsi,
        sma20=sma20,
        sma50=sma50,
        sinyal=sinyal,
        skor=skor,
        gerekce=gerekce_full,
        sektor=sektor,
        rejim_notu=rh.rejim_notu,
        profil_notu=profil_notu,
        teknik_skor=teknik_skor,
        isin=isin,
        revolut_ticker=revolut_ticker,
        varlik_turu=varlik_turu,
        sma200=_h.sma200,
        zirve_52h_pct=_h.zirve_52h_pct,
        trend_notu=_h.trend_notu,
    )


def _hikaye_uret(h: HisseAnaliz) -> str:
    """Büyük şirket / Revolut ETF için kısa yatırım hikayesi."""
    sek = SEKTOR_ETIKET.get(h.sektor, h.sektor)

    if h.varlik_turu == "etf" or h.piyasa == "ETF":
        rt = h.revolut_ticker or h.sembol.split(".")[0]
        if h.sinyal in ("ALIM_FIRSATI", "TREND_ALIM"):
            hik = f"Revolut {rt} · {sek} ETF — kademeli DCA / alım adayı"
        elif h.sinyal in ("ASIRI_ALIM", "UZAK_DUR"):
            hik = f"Revolut {rt} · {sek} ETF — şimdilik bekle, zirveye yakın"
        else:
            hik = f"Revolut {rt} · {sek} ETF — çekirdek portföy, izleme"
        if h.isin:
            hik += f" (ISIN {h.isin})"
    elif h.sinyal == "ALIM_FIRSATI":
        hik = f"Blue-chip {sek} · RSI dipten toparlanma — kademeli alım bölgesi"
    elif h.sinyal == "TREND_ALIM":
        hik = f"Blue-chip {sek} · trend yukarı (SMA50 destek) — momentum alımı"
    elif h.sinyal in ("ASIRI_ALIM", "UZAK_DUR"):
        hik = f"Blue-chip {sek} · riskli bölge — şimdilik uzak dur"
    else:
        hik = f"Blue-chip {sek} · net teknik sinyal yok"

    if h.degisim_1ay is not None and h.degisim_1ay <= -12 and h.rsi and h.rsi < 50:
        hik = f"{sek} · son 1 ay %{abs(h.degisim_1ay):.0f} geri çekilme — indirim bölgesi"
    if h.rejim_notu and h.rejim_notu != "Rejim uyumlu":
        hik += f" · {h.rejim_notu.split(';')[0]}"
    if getattr(h, "profil_notu", "") and h.profil_notu != "Profil uyumlu":
        hik += f" · {h.profil_notu.split(';')[0]}"
    if getattr(h, "faktor_notu", "") and h.faktor_notu not in ("", "Faktör nötr"):
        hik += f" · {h.faktor_notu.split('·')[0].strip()}"
    if getattr(h, "trend_notu", "") and "OK" not in h.trend_notu:
        hik += f" · {h.trend_notu.split('—')[0].strip()}"
    if getattr(h, "alim_uygun_etiket", ""):
        hik += f" · {h.alim_uygun_etiket.replace('🟢 ', '').replace('🟡 ', '').replace('🔴 ', '').replace('⚪ ', '')}"
    return hik


def _firsatlari_sec(hisseler: List[HisseAnaliz], min_skor: float = 55) -> List[HisseAnaliz]:
    return sorted(
        [h for h in hisseler if h.sinyal in ("ALIM_FIRSATI", "TREND_ALIM") and h.skor >= min_skor],
        key=lambda x: -x.skor,
    )


def _etf_sirala(hisseler: List[HisseAnaliz], makro_rejim: str) -> List[HisseAnaliz]:
    return sorted(
        hisseler,
        key=lambda x: (etf_oncelik(x.sektor, makro_rejim), -x.skor),
    )


def tam_tarama(
    makro_rejim: str = "NOTR",
    demo: bool = False,
    snap=None,
    haber_tara: bool = True,
    profil: Optional[YatirimProfili] = None,
) -> TaramaSonucu:
    profil = profil or YatirimProfili()
    if demo:
        return _demo_tarama(makro_rejim, profil=profil)

    evren = tum_evren()
    semboller = list(dict.fromkeys(
        list(ENDEKSLER.values()) + [s for s, _, _, _, _, _ in evren]
    ))
    df = _indir(semboller, period="1y")
    if df.empty:
        return TaramaSonucu(
            uyarilar=["Yahoo Finance verisi alınamadı."],
            makro_rejim=makro_rejim,
        )

    endeksler = [_endeks_analiz(df, ad, sym, makro_rejim, snap) for ad, sym in ENDEKSLER.items()]
    tum: List[HisseAnaliz] = []
    for sembol, ad, piyasa, sektor, isin, revolut_ticker in evren:
        varlik = "etf" if piyasa == "ETF" else "hisse"
        tum.append(_hisse_analiz(
            df, sembol, ad, piyasa, sektor, makro_rejim, snap,
            isin=isin, revolut_ticker=revolut_ticker, varlik_turu=varlik, profil=profil,
        ))

    profil_ozet, profil_notlari = profil_tarama_bilgisi(profil, makro_rejim)
    esik = profil_firsat_esik(profil)

    uyarilar: List[str] = []
    if snap and snap.veri and snap.veri.savas_risk_guvenilir is False:
        uyarilar.append(
            "Jeopolitik haber taraması güvenilir değil — hisse haber skorları eksik kalabilir."
        )

    # Haber katmanı: teknik+rejim geçen adaylar (en fazla 25 Google News sorgusu)
    if haber_tara and not demo:
        adaylar = sorted(tum, key=lambda x: -x.skor)
        haber_filtresi_uygula(adaylar, max_kontrol=25)

    from hisse_faktor import faktor_katmani_uygula
    faktor_katmani_uygula(tum, df)

    firsatlar = profil_firsat_sinirla(_firsatlari_sec(tum, esik)[:20], profil)
    etfler = [h for h in tum if h.piyasa == "ETF"]
    etf_firsat = _etf_sirala(_firsatlari_sec(etfler, esik)[:10], makro_rejim)

    aday_sem = {h.sembol for h in firsatlar} | {h.sembol for h in etf_firsat}
    from alim_uygunluk import alim_uygunluk_uygula
    alim_uygunluk_uygula(tum, aday_sem, esik)

    for h in tum:
        h.hikaye = _hikaye_uret(h)

    ozet = (
        f"{len(evren)} varlık tarandı (BIST {len(BIST_HISSELER)}, "
        f"SP500 {len(SP500_HISSELER)}, NASDAQ {len(NASDAQ_HISSELER)}, "
        f"Revolut ETF {len(REVOLUT_ETFLER)}) · "
        f"Rejim: {makro_rejim} · Profil: {profil_ozet} · "
        f"{len(firsatlar)} alım adayı (eşik ≥{esik:.0f}, {len(etf_firsat)} ETF)"
    )

    return TaramaSonucu(
        endeksler=endeksler,
        hisseler=sorted(tum, key=lambda x: -x.skor),
        alim_firsatlari=firsatlar,
        etf_firsatlari=etf_firsat,
        uyarilar=uyarilar,
        makro_rejim=makro_rejim,
        tarama_ozet=ozet,
        profil_ozet=profil_ozet,
        profil_notlari=profil_notlari,
    )


def _demo_tarama(
    makro_rejim: str = "NOTR",
    profil: Optional[YatirimProfili] = None,
) -> TaramaSonucu:
    profil = profil or YatirimProfili()
    profil_ozet, profil_notlari = profil_tarama_bilgisi(profil, makro_rejim)
    endeksler = [
        EndeksOzet("BIST 100", "XU100.IS", 14286, 0.8, 5.2, 8.5, 48, "BEKLE", 52),
        EndeksOzet("NASDAQ Composite", "^IXIC", 19850, 0.5, 3.1, 12.0, 55, "TREND_ALIM", 68),
        EndeksOzet("NASDAQ 100", "^NDX", 21500, 0.6, 3.5, 13.2, 56, "TREND_ALIM", 70),
        EndeksOzet("S&P 500", "^GSPC", 5450, 0.3, 2.8, 9.5, 52, "BEKLE", 58),
    ]
    hisseler = [
        HisseAnaliz("NVDA", "NVIDIA", "NASDAQ", 135.0, 1.2, 8.5, 15.0, 38, 128, 120, "ALIM_FIRSATI", 78, "RSI 38 — dipten dönüş", "teknoloji", teknik_skor=78),
        HisseAnaliz("ASELS.IS", "Aselsan", "BIST", 185.0, -0.5, 4.2, 6.0, 36, 180, 175, "ALIM_FIRSATI", 72, "RSI 36 — dipten dönüş", "savunma", teknik_skor=72),
        HisseAnaliz("AAPL", "Apple", "NASDAQ", 210.0, 0.4, 2.1, 5.0, 58, 205, 200, "TREND_ALIM", 65, "RSI 58 + SMA50 üstü", "teknoloji", teknik_skor=65),
        HisseAnaliz("GARAN.IS", "Garanti BBVA", "BIST", 142.0, 0.2, 1.5, 2.0, 45, 140, 138, "BEKLE", 55, "Net sinyal yok", "finans", teknik_skor=55),
        HisseAnaliz("TSLA", "Tesla", "NASDAQ", 320.0, -1.5, -5.0, -8.0, 72, 315, 300, "ASIRI_ALIM", 25, "RSI 72 — aşırı alım", "buyume", teknik_skor=25),
        HisseAnaliz("VWCE.DE", "Vanguard All-World", "ETF", 118.5, 0.3, 2.1, 4.0, 44, 116, 114,
                    "ALIM_FIRSATI", 76, "RSI 44 — dipten dönüş", "dunya",
                    isin="IE00BK5BQT80", revolut_ticker="VWCE", varlik_turu="etf", teknik_skor=66),
        HisseAnaliz("CSPX.L", "iShares S&P 500", "ETF", 520.0, 0.2, 1.8, 3.5, 52, 515, 510,
                    "TREND_ALIM", 74, "RSI 52 + SMA50 üstü", "abd",
                    isin="IE00B5BMR087", revolut_ticker="CSPX", varlik_turu="etf", teknik_skor=68),
    ]
    firsatlar = [h for h in hisseler if h.sinyal in ("ALIM_FIRSATI", "TREND_ALIM")]
    etf_f = [h for h in firsatlar if h.piyasa == "ETF"]
    return TaramaSonucu(
        endeksler=endeksler,
        hisseler=hisseler,
        alim_firsatlari=firsatlar,
        etf_firsatlari=etf_f,
        makro_rejim=makro_rejim,
        tarama_ozet=f"Demo tarama · Profil: {profil_ozet}",
        profil_ozet=profil_ozet,
        profil_notlari=profil_notlari,
    )
