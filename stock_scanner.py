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

import config
from hisse_rejim_haber import haber_filtresi_uygula, rejim_hisse_ayarla
from profil_hisse import (
    profil_firsat_esik,
    profil_firsat_sinirla,
    profil_hisse_ayarla,
    profil_tarama_bilgisi,
)
from investor_profile import YatirimProfili
from etf_universe import ETF_ETIKET, REVOLUT_ETFLER, etf_oncelik
from emtia_universe import EMTIA_SEMBOLLER
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
    "ALIM_FIRSATI": "RSI dip bölgesi",
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
    sinyal: str  # legacy uyum — UI aksiyon/kurulum kullanır
    skor: float
    close_bar_dates: Optional[pd.DatetimeIndex] = None
    quote_currency: str = ""
    platform: str = ""
    aksiyon: str = "BEKLE"
    aksiyon_etiket: str = "Bekle"
    kurulum: str = ""
    guven: float = 0.0
    gerekce: str = ""
    sma20: Optional[float] = None
    sma50: Optional[float] = None
    sma200: Optional[float] = None
    teknik_aksiyon: str = "BEKLE"
    teknik_aksiyon_etiket: str = "Bekle"
    makro_chip: str = ""
    makro_not: str = ""


@dataclass
class HisseAnaliz:
    sembol: str
    ad: str
    piyasa: str
    fiyat: Optional[float]
    degisim_1g: Optional[float]
    degisim_1ay: Optional[float]
    degisim_3ay: Optional[float]
    degisim_1y: Optional[float]
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
    temel_skor: float = 0.0
    bilesik_skor: float = 0.0
    vade_uyum_puani: float = 0.0
    vade_uygun: bool = True
    temel_not: str = ""
    vol_30g: Optional[float] = None
    hikaye: str = ""
    isin: str = ""
    revolut_ticker: str = ""
    varlik_turu: str = "hisse"  # hisse | etf | emtia
    peer_yuzdelik: Optional[float] = None
    endeks_gore: Optional[float] = None
    faktor_notu: str = ""
    sma200: Optional[float] = None
    zirve_52h_pct: Optional[float] = None
    zirve_52h_eur_pct: Optional[float] = None
    zirve_52h_eur_etiket: str = ""
    bist_52h_join_gun: Optional[int] = None
    bist_52h_join_uyari: bool = False
    bist_52h_kur_yok: bool = False
    trend_notu: str = ""
    alim_uygun: str = "IZLE"
    alim_uygun_etiket: str = "⚪ İzle / bekle"
    alim_uygun_not: str = ""
    yonetici_aksiyon: str = "BEKLE"
    yonetici_ozet: str = ""
    yonetici_detay: str = ""
    yonetici_destek: Optional[float] = None
    yonetici_alim: Optional[float] = None
    yonetici_iptal: Optional[float] = None
    # Signal Engine v2
    signal_v2_score: Optional[float] = None
    signal_v2_percentile: Optional[float] = None
    signal_v2_regime: str = ""
    signal_v2_regime_detail: str = ""
    signal_v2_decision: str = ""
    signal_v2_code: str = ""
    signal_v2_why: str = ""
    signal_v2_decision_gates: list = field(default_factory=list)
    signal_v2_fund_note: str = ""
    signal_v2_fund_score: Optional[float] = None
    signal_v2_fund_label: str = ""
    signal_v2_fund_pillars: dict = field(default_factory=dict)
    signal_v2_fund_score_detail: Optional[dict] = None
    signal_v2_dual_line: str = ""
    signal_v2_ichimoku: Optional[dict] = None
    signal_v2_synth_reason: str = ""
    signal_v2_small_size: bool = False
    signal_v2_ready_note: bool = False
    signal_v2_al_price: Optional[float] = None
    signal_v2_al_method: str = ""
    signal_v2_al_p_fill: Optional[float] = None
    signal_v2_dca: bool = False
    signal_v2_data: str = ""
    signal_v2_factors: dict = field(default_factory=dict)
    signal_v2_factor_details: dict = field(default_factory=dict)
    signal_v2_sparkline: list = field(default_factory=list)
    signal_v2_etf_quality: str = ""
    signal_v2_al_secondary: Optional[float] = None
    signal_v2_al_secondary_p_fill: Optional[float] = None
    signal_v2_spot_near: bool = False
    signal_v2_spot_distance_pct: Optional[float] = None
    signal_v2_regime_days: int = 0
    close_bar_dates: Optional[pd.DatetimeIndex] = field(default=None, repr=False)
    signal_v2_regime_fresh: bool = False
    quote_currency: str = ""
    quote_timestamp: str = ""
    quote_age_min: Optional[float] = None
    veri_hatasi: str = ""
    veri_quarantine: bool = False


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
    eurtry_seri: Optional[pd.Series] = None
    usdtry_seri: Optional[pd.Series] = None
    gbpusd_seri: Optional[pd.Series] = None
    eurusd_seri: Optional[pd.Series] = None
    chfusd_seri: Optional[pd.Series] = None
    # Veri bütünlüğü — sessiz düşme yok
    veri_ozet_log: str = ""
    veri_ozet_ui: str = ""
    veri_yok_semboller: List[str] = field(default_factory=list)
    karantina_semboller: List[str] = field(default_factory=list)


def _skaler(val) -> Optional[float]:
    """Series/DataFrame/numpy skaler → float."""
    if isinstance(val, pd.DataFrame):
        if val.empty:
            return None
        val = val.iloc[-1, 0]
    elif isinstance(val, pd.Series):
        val = val.iloc[-1] if len(val) else None
    try:
        f = float(val)
        return f if pd.notna(f) else None
    except (TypeError, ValueError):
        return None


def _seri_1d(obj) -> pd.Series:
    """Kapanış verisini tek sütunlu Series'e indirger."""
    if isinstance(obj, pd.DataFrame):
        if obj.empty:
            return pd.Series(dtype=float)
        obj = obj.iloc[:, 0]
    if not isinstance(obj, pd.Series):
        return pd.Series(dtype=float)
    return obj.dropna()


def _son_fiyat(seri: pd.Series) -> Optional[float]:
    seri = _seri_1d(seri)
    if seri.empty:
        return None
    return _skaler(seri.iloc[-1])


def _rsi(seri: pd.Series, period: int = 14) -> Optional[float]:
    """Wilder RSI — EWM düzeltmeli (endüstri standardı; rolling-mean'den daha az gürültülü)."""
    seri = _seri_1d(seri)
    if len(seri) < period + 1:
        return None
    delta = seri.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-10)
    val = 100 - (100 / (1 + rs))
    return _skaler(val.iloc[-1])


def _sma(seri: pd.Series, n: int) -> Optional[float]:
    seri = _seri_1d(seri)
    if len(seri) < n:
        return None
    return _skaler(seri.rolling(n).mean().iloc[-1])


def _degisim(seri: pd.Series, gun: int) -> Optional[float]:
    """gun >= 252 → 365 takvim günü (1Y); aksi halde trading-bar ofseti."""
    seri = _seri_1d(seri)
    if gun >= 252:
        from signal_engine.data.bars import pct_change_calendar
        return pct_change_calendar(seri, calendar_days=365)
    if len(seri) < gun + 1:
        return None
    eski = _skaler(seri.iloc[-gun - 1])
    yeni = _skaler(seri.iloc[-1])
    if eski is None or yeni is None or eski == 0:
        return None
    return (yeni - eski) / eski * 100


def _degisim_1g(
    fiyat: Optional[float],
    close: pd.Series,
    previous_close: Optional[float] = None,
    *,
    sembol: str = "",
) -> Optional[float]:
    """1G % — resmi önceki seans kapanışı (Yahoo/Google previousClose).

    History'deki son iki mum, eksik bar / tatil boşluğunda yanlış 'önceki
    kapanış' verebilir (ör. MGROS 608 vs resmi 627). previousClose varsa onu kullan.
    """
    prev = previous_close
    px = fiyat
    if (prev is None or px is None) and sembol:
        try:
            from signal_engine.data.live_quote import get_live_quote

            live = get_live_quote(sembol)
            if live:
                if prev is None and live.previous_close is not None:
                    prev = live.previous_close
                if px is None and live.price is not None:
                    px = live.price
        except Exception:
            pass
    if (
        prev is not None
        and px is not None
        and float(prev) > 0
        and float(px) > 0
    ):
        return (float(px) - float(prev)) / float(prev) * 100.0

    # Bar fallback yalnızca bitişik seanslarda — çok günlük boşlukta yanlış % üretme
    close = _seri_1d(close)
    if len(close) >= 2:
        try:
            d0 = pd.Timestamp(close.index[-2]).tz_localize(None).normalize()
            d1 = pd.Timestamp(close.index[-1]).tz_localize(None).normalize()
            if abs((d1 - d0).days) > 2:
                return None
        except Exception:
            pass
    return _degisim(close, 1)


def _extract_close_raw(df: pd.DataFrame, sembol: str) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    raw = None
    if isinstance(df.columns, pd.MultiIndex):
        lvl0 = df.columns.get_level_values(0)
        if sembol in lvl0:
            raw = df[sembol]["Close"]
        else:
            for t in lvl0.unique():
                if str(t).upper() == str(sembol).upper():
                    raw = df[t]["Close"]
                    break
    elif "Close" in df.columns:
        raw = df["Close"]
        if isinstance(raw, pd.DataFrame) and sembol in raw.columns:
            raw = raw[sembol]
    elif len(df.columns) >= 1:
        raw = df.iloc[:, 0]
    return _seri_1d(raw)


def _close_al_with_meta(df: pd.DataFrame, sembol: str):
    from signal_engine.data.quote_normalize import (
        fetch_source_quote_currency,
        normalize_close_series,
        SeriesQuoteMeta,
    )

    raw = _extract_close_raw(df, sembol)
    if raw.empty:
        return raw, SeriesQuoteMeta(sembol, "", "", quarantine=True, quarantine_reason="boş seri")
    try:
        src_ccy = fetch_source_quote_currency(sembol) or None
        return normalize_close_series(sembol, raw, source_currency=src_ccy)
    except Exception:
        return pd.Series(dtype=float), SeriesQuoteMeta(sembol, "", "", quarantine=True, quarantine_reason="normalizasyon hatası")


def _close_al(df: pd.DataFrame, sembol: str) -> pd.Series:
    close, _ = _close_al_with_meta(df, sembol)
    return close


def _sinyal_uret(
    fiyat: float,
    rsi: Optional[float],
    sma20: Optional[float],
    sma50: Optional[float],
    degisim_3ay: Optional[float] = None,
    degisim_1ay: Optional[float] = None,
) -> Tuple[str, float, str]:
    if rsi is None or sma50 is None:
        return "VERI_YOK", 0.0, "Yetersiz fiyat verisi"

    skor = 50.0
    gerekceler = []

    # Düşen bıçak koruması: 3 ayda -%25'ten fazla kayıp varsa dip RSI alım sinyali sayılmaz
    dusen_bicak = degisim_3ay is not None and degisim_3ay < -25

    if 28 <= rsi <= 45 and not dusen_bicak:
        skor += 25
        # Dönüş teyidi (higher low / önceki kapanış üstü) YOK — yalnızca RSI bandı
        gerekceler.append(f"RSI {rsi:.0f} — RSI dip bölgesi")
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
    elif dusen_bicak and rsi <= 45:
        skor -= 10
        gerekceler.append(f"RSI {rsi:.0f} ama 3A {degisim_3ay:+.0f}% — dip henüz doğrulanmadı")
        sinyal = "BEKLE"
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

    # Momentum katmanı (faktör literatürü: 3-12 ay momentum kalıcıdır; aşırıda ters çevirir)
    if degisim_3ay is not None:
        if 5 <= degisim_3ay <= 40:
            skor += 8
            gerekceler.append(f"3A momentum {degisim_3ay:+.0f}%")
        elif degisim_3ay > 60:
            skor -= 5
            gerekceler.append(f"3A {degisim_3ay:+.0f}% — aşırı ısınma riski")
        elif degisim_3ay < -15:
            skor -= 8
            gerekceler.append(f"3A momentum zayıf ({degisim_3ay:+.0f}%)")

    return sinyal, max(0, min(100, skor)), "; ".join(gerekceler)


def _df_index_tz_naive(df: pd.DataFrame) -> pd.DataFrame:
    """yf.download (naive) ile Ticker.history (UTC-aware) concat uyumu."""
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    out = df.copy()
    idx = out.index
    if isinstance(idx, pd.DatetimeIndex) and idx.tz is not None:
        out.index = idx.tz_convert("UTC").tz_localize(None)
    return out


def _indir(semboller: List[str], period: str = "1y", *, timeout: float = 25.0) -> pd.DataFrame:
    import yfinance as yf

    if not semboller:
        return pd.DataFrame()

    def _batch_indir(chunk: List[str], *, threads: bool = True) -> pd.DataFrame:
        part = yf.download(
            chunk,
            period=period,
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=threads,
        )
        if part is None or part.empty:
            return pd.DataFrame()
        return _df_index_tz_naive(part)

    def _tek_ticker(sym: str) -> pd.DataFrame:
        try:
            h = yf.Ticker(sym).history(period=period, auto_adjust=True)
            if h is None or h.empty or "Close" not in h.columns:
                return pd.DataFrame()
            # MultiIndex (ticker, field) — ana df ile uyum
            part = h[["Open", "High", "Low", "Close", "Volume"]].copy()
            part.columns = pd.MultiIndex.from_product([[sym], part.columns])
            return _df_index_tz_naive(part)
        except Exception as e:
            print(f"[UYARI] yfinance tek {sym}: {e}")
            return pd.DataFrame()

    parcalar = []
    batch = 35
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

    basarisiz_chunklar: List[List[str]] = []
    for i in range(0, len(semboller), batch):
        chunk = semboller[i : i + batch]
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_batch_indir, chunk)
                part = fut.result(timeout=timeout) if timeout > 0 else fut.result()
            if not part.empty:
                parcalar.append(part)
            else:
                basarisiz_chunklar.append(chunk)
        except FutTimeout:
            print(f"[UYARI] yfinance batch {i}: zaman aşımı ({timeout}s)")
            basarisiz_chunklar.append(chunk)
        except Exception as e:
            print(f"[UYARI] yfinance batch {i}: {e}")
            basarisiz_chunklar.append(chunk)

    # Başarısız batch: bir kez threads=False + daha uzun timeout
    for chunk in basarisiz_chunklar:
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(lambda c=chunk: _batch_indir(c, threads=False))
                part = fut.result(timeout=max(timeout, 40.0))
            if not part.empty:
                parcalar.append(part)
        except Exception as e:
            print(f"[UYARI] yfinance retry batch: {e}")

    if not parcalar:
        out = pd.DataFrame()
    elif len(parcalar) == 1:
        out = parcalar[0]
    else:
        out = pd.concat([_df_index_tz_naive(p) for p in parcalar], axis=1)
    if not out.empty and isinstance(out.columns, pd.MultiIndex):
        out = out.loc[:, ~out.columns.duplicated(keep="first")]
    out = _df_index_tz_naive(out)

    # Eksik kritik semboller (emtia + FX) — tek ticker doldur
    kritik = [s for s, *_ in EMTIA_SEMBOLLER] + [
        "EURTRY=X", "USDTRY=X", "GBPUSD=X", "EURUSD=X", "CHFUSD=X",
    ]
    eksik = [s for s in kritik if s in semboller and not _df_sembol_var(out, s)]
    # Evren genelinde de boş kalanları (sınırlı) doldur — emtia öncelikli
    diger_eksik = [
        s for s in semboller
        if s not in eksik and not _df_sembol_var(out, s)
    ]
    # Önce kritik, sonra en fazla 15 diğer (timeout patlamasın)
    for sym in eksik + diger_eksik[:15]:
        tek = _tek_ticker(sym)
        if tek.empty:
            continue
        if out.empty:
            out = tek
        else:
            out = pd.concat([_df_index_tz_naive(out), tek], axis=1)
        if isinstance(out.columns, pd.MultiIndex):
            out = out.loc[:, ~out.columns.duplicated(keep="first")]
    return out


def _df_sembol_var(df: pd.DataFrame, sembol: str) -> bool:
    if df is None or df.empty:
        return False
    if isinstance(df.columns, pd.MultiIndex):
        lvl0 = df.columns.get_level_values(0)
        su = str(sembol).upper()
        return any(str(t).upper() == su for t in lvl0.unique())
    return sembol in df.columns or any(
        str(c).upper() == str(sembol).upper() for c in df.columns
    )

def _endeks_analiz(
    df: pd.DataFrame,
    ad: str,
    sym: str,
    makro_rejim: str,
    snap,
    *,
    fx_ok: bool = True,
) -> EndeksOzet:
    """Endeks özeti — hisse `_sinyal_uret` yolundan bağımsız platform yönlendirme."""
    from endeks_yonlendirme import karar as endeks_karar

    close = _close_al(df, sym)
    if close.empty:
        return EndeksOzet(
            ad, sym, None, None, None, None, None, "VERI_YOK", 0,
            platform="TR" if sym.endswith(".IS") else "ABD",
            kurulum="Veri zayıf", guven=0.0, gerekce="Fiyat serisi yok",
        )

    fiyat = _son_fiyat(close)
    prev_close = None
    try:
        from signal_engine.data.live_quote import get_live_quote

        live = get_live_quote(sym)
        if live and live.price > 0:
            fiyat = live.price
            prev_close = live.previous_close
    except Exception:
        pass
    if fiyat is None:
        return EndeksOzet(
            ad, sym, None, None, None, None, None, "VERI_YOK", 0,
            platform="TR" if sym.endswith(".IS") else "ABD",
            kurulum="Veri zayıf", guven=0.0, gerekce="Fiyat yok",
        )
    rsi = _rsi(close)
    sma20, sma50, sma200 = _sma(close, 20), _sma(close, 50), _sma(close, 200)
    d1ay, d3ay = _degisim(close, 21), _degisim(close, 63)
    k = endeks_karar(
        sembol=sym,
        fiyat=float(fiyat),
        rsi=rsi,
        sma20=sma20,
        sma50=sma50,
        sma200=sma200,
        degisim_1ay=d1ay,
        degisim_3ay=d3ay,
        fx_ok=fx_ok,
        makro_rejim=makro_rejim or "NOTR",
        snap=snap,
    )

    return EndeksOzet(
        ad=ad,
        sembol=sym,
        fiyat=fiyat,
        degisim_1g=_degisim_1g(fiyat, close, prev_close, sembol=sym),
        degisim_1ay=d1ay,
        degisim_3ay=d3ay,
        rsi=rsi,
        sinyal=k.sinyal,
        skor=k.skor,
        close_bar_dates=close.index,
        quote_currency="TRY" if sym.endswith(".IS") else "USD",
        platform=k.platform,
        aksiyon=k.aksiyon,
        aksiyon_etiket=k.aksiyon_etiket,
        kurulum=k.kurulum,
        guven=k.guven,
        gerekce=k.gerekce,
        sma20=sma20,
        sma50=sma50,
        sma200=sma200,
        teknik_aksiyon=k.teknik_aksiyon,
        teknik_aksiyon_etiket=k.teknik_aksiyon_etiket,
        makro_chip=k.makro_chip,
        makro_not=k.makro_not,
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
    eurtry_close: Optional[pd.Series] = None,
) -> HisseAnaliz:
    close, quote_meta = _close_al_with_meta(df, sembol)
    if close.empty or len(close) < 30:
        return HisseAnaliz(
            sembol, ad, piyasa, None, None, None, None, None, None, None, None,
            "VERI_YOK", 0, "Veri yok", sektor=sektor,
            isin=isin, revolut_ticker=revolut_ticker, varlik_turu=varlik_turu,
            quote_currency=getattr(quote_meta, "settlement_currency", ""),
            veri_hatasi=getattr(quote_meta, "quarantine_reason", "") or "Veri yok",
            veri_quarantine=True,
        )

    if quote_meta.quarantine:
        return HisseAnaliz(
            sembol, ad, piyasa, None, None, None, None, None, None, None, None,
            "VERI_YOK", 0, quote_meta.quarantine_reason, sektor=sektor,
            isin=isin, revolut_ticker=revolut_ticker, varlik_turu=varlik_turu,
            quote_currency=quote_meta.settlement_currency,
            veri_hatasi=quote_meta.quarantine_reason,
            veri_quarantine=True,
        )

    fiyat = _son_fiyat(close)
    quote_ts = ""
    quote_age: Optional[float] = None
    prev_close: Optional[float] = None
    try:
        from datetime import timezone

        from signal_engine.data.live_quote import get_live_quote, quote_age_from_bar

        live = get_live_quote(sembol)
        if live and live.price > 0:
            prev_close = live.previous_close
            target = quote_meta.settlement_currency
            if live.settlement == target:
                fiyat = live.price
            else:
                from signal_engine.data.bars import _extract_close
                from signal_engine.data.quote_normalize import convert_settlement
                from fiyat_para_fx import FxUnavailableError, kur_tablo_spot

                when = close.index.max()
                ut = _extract_close(df, "USDTRY=X")
                et = _extract_close(df, "EURTRY=X")
                gbp_s = _extract_close(df, "GBPUSD=X")
                eurusd_s = _extract_close(df, "EURUSD=X")
                chf_s = _extract_close(df, "CHFUSD=X")
                try:
                    fx = kur_tablo_spot(
                        snap, et, ut, gbp_s, eurusd_s, asof=when,
                        chf_s=chf_s, check_plausibility=False,
                    )
                    fiyat = convert_settlement(
                        live.price, live.settlement, target,
                        eur_try=fx.eur_try, usd_try=fx.usd_try,
                        gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd, chf_usd=fx.chf_usd,
                    )
                    if live.previous_close is not None:
                        try:
                            prev_close = convert_settlement(
                                live.previous_close, live.settlement, target,
                                eur_try=fx.eur_try, usd_try=fx.usd_try,
                                gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd, chf_usd=fx.chf_usd,
                            )
                        except FxUnavailableError:
                            prev_close = live.previous_close
                except FxUnavailableError:
                    # Canlı kotasyon PB'si farklı ve FX yok — bar settlement fiyatında kal
                    # (yanlış PB ile live fiyat YAZMA)
                    pass
            quote_ts = live.timestamp.isoformat()
            quote_age = live.age_min
        elif hasattr(close.index, "max"):
            ts = close.index.max()
            if hasattr(ts, "to_pydatetime"):
                dt = ts.to_pydatetime()
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                quote_ts = dt.isoformat()
                quote_age = quote_age_from_bar(ts, piyasa)
    except Exception:
        # Live katmanı tamamen başarısız — settlement bar fiyatı korunur
        pass

    if fiyat is None:
        return HisseAnaliz(
            sembol, ad, piyasa, None, None, None, None, None, None, None, None,
            "VERI_YOK", 0, "Veri yok", sektor=sektor,
            isin=isin, revolut_ticker=revolut_ticker, varlik_turu=varlik_turu,
            quote_currency=quote_meta.settlement_currency,
        )
    rsi = _rsi(close)
    sma20, sma50 = _sma(close, 20), _sma(close, 50)
    d1ay, d3ay = _degisim(close, 21), _degisim(close, 63)
    d1y = _degisim(close, 252)
    sinyal, skor, gerekce = _sinyal_uret(
        fiyat, rsi, sma20, sma50, degisim_3ay=d3ay, degisim_1ay=d1ay,
    )
    teknik_skor = skor

    from hisse_trend_filtresi import trend_filtresi_uygula
    d1g = _degisim_1g(fiyat, close, prev_close, sembol=sembol)
    _h = HisseAnaliz(
        sembol=sembol, ad=ad, piyasa=piyasa, fiyat=fiyat,
        degisim_1g=d1g, degisim_1ay=d1ay,
        degisim_3ay=d3ay, degisim_1y=d1y, rsi=rsi, sma20=sma20, sma50=sma50,
        sinyal=sinyal, skor=skor, gerekce=gerekce, sektor=sektor,
        teknik_skor=teknik_skor, isin=isin, revolut_ticker=revolut_ticker,
        varlik_turu=varlik_turu,
        quote_currency=quote_meta.settlement_currency,
    )
    trend_filtresi_uygula(_h, close, profil=profil)
    from bist_52h_eur import bist_52h_eur_uygula
    bist_52h_eur_uygula(_h, close, eurtry_close)
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
        degisim_1g=d1g,
        degisim_1ay=d1ay,
        degisim_3ay=d3ay,
        degisim_1y=d1y,
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
        zirve_52h_eur_pct=_h.zirve_52h_eur_pct,
        zirve_52h_eur_etiket=_h.zirve_52h_eur_etiket,
        bist_52h_join_gun=_h.bist_52h_join_gun,
        bist_52h_join_uyari=_h.bist_52h_join_uyari,
        bist_52h_kur_yok=_h.bist_52h_kur_yok,
        trend_notu=_h.trend_notu,
        quote_currency=quote_meta.settlement_currency,
        quote_timestamp=quote_ts,
        quote_age_min=quote_age,
        close_bar_dates=close.index,
    )


def _hikaye_uret(h: HisseAnaliz) -> str:
    """Büyük şirket / Revolut ETF / spot emtia için kısa yatırım hikayesi."""
    sek = SEKTOR_ETIKET.get(h.sektor, h.sektor)
    v2_code = (getattr(h, "signal_v2_code", None) or "").upper()
    # v2 nihai karar alım değilse — eski v1 “kademeli alım” dilini sustur
    v2_alim_yok = v2_code in ("WATCH", "WAIT", "REDUCE")

    if h.varlik_turu == "emtia" or h.piyasa == "EMTIA":
        if v2_alim_yok:
            hik = f"Spot {sek} (ons) — {getattr(h, 'signal_v2_decision', None) or 'izle'}"
        elif h.sinyal in ("ALIM_FIRSATI", "TREND_ALIM"):
            hik = f"Spot {sek} (ons) — teknik alım bölgesi"
        elif h.sinyal in ("ASIRI_ALIM", "UZAK_DUR"):
            hik = f"Spot {sek} (ons) — zirveye yakın, temkin"
        else:
            hik = f"Spot {sek} (ons) — fiziksel alım/satım izleme"
    elif h.varlik_turu == "etf" or h.piyasa == "ETF":
        rt = h.revolut_ticker or h.sembol.split(".")[0]
        if v2_alim_yok:
            hik = f"Revolut {rt} · {sek} ETF — {getattr(h, 'signal_v2_decision', None) or 'izle'}"
        elif h.sinyal in ("ALIM_FIRSATI", "TREND_ALIM"):
            hik = f"Revolut {rt} · {sek} ETF — kademeli DCA / alım adayı"
        elif h.sinyal in ("ASIRI_ALIM", "UZAK_DUR"):
            hik = f"Revolut {rt} · {sek} ETF — şimdilik bekle, zirveye yakın"
        else:
            hik = f"Revolut {rt} · {sek} ETF — çekirdek portföy, izleme"
        if h.isin:
            hik += f" (ISIN {h.isin})"
    elif v2_alim_yok:
        hik = (
            f"Blue-chip {sek} · karar {getattr(h, 'signal_v2_decision', None) or 'İZLE'} "
            "— alım hikayesi yok"
        )
    elif h.sinyal == "ALIM_FIRSATI":
        hik = f"Blue-chip {sek} · RSI dip bölgesi — teyit sonrası değerlendir"
    elif h.sinyal == "TREND_ALIM":
        hik = f"Blue-chip {sek} · trend yukarı (SMA50 destek) — momentum"
    elif h.sinyal in ("ASIRI_ALIM", "UZAK_DUR"):
        hik = f"Blue-chip {sek} · riskli bölge — şimdilik uzak dur"
    else:
        hik = f"Blue-chip {sek} · net teknik sinyal yok"

    if (
        not v2_alim_yok
        and h.degisim_1ay is not None
        and h.degisim_1ay <= -12
        and h.rsi
        and h.rsi < 50
    ):
        hik = f"{sek} · son 1 ay %{abs(h.degisim_1ay):.0f} geri çekilme — izleme"
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


def _firsatlari_sec(
    hisseler: List[HisseAnaliz],
    min_skor: float = 55,
    *,
    v2: bool = False,
) -> List[HisseAnaliz]:
    """v2 açıksa yalnızca BUY/STRONG_BUY; kapalıysa eski v1 sinyal filtresi."""
    esik = max(min_skor, config.BILESKE_BEKLE_ESIK)
    if v2:
        adaylar = [
            h
            for h in hisseler
            if (getattr(h, "signal_v2_code", None) or "") in ("STRONG_BUY", "BUY")
            and _bilesik(h) >= esik
            and not getattr(h, "veri_quarantine", False)
        ]
    else:
        adaylar = [
            h
            for h in hisseler
            if h.sinyal in ("ALIM_FIRSATI", "TREND_ALIM")
            and _bilesik(h) >= esik
        ]
    return sorted(adaylar, key=lambda x: -_bilesik(x))


# AL eşiği 68; histerezis 3 → 65 = eşiğe yakın (AL değil)
ESIGE_YAKIN_SKOR = 65.0


def esige_yakin_sec(
    hisseler: List[HisseAnaliz],
    makro_rejim: str = "",
    *,
    min_skor: float = ESIGE_YAKIN_SKOR,
    n: int = 12,
) -> List[HisseAnaliz]:
    """İZLE + skoru AL’ye yakın — takip listesi; asla AL adayı sayılmaz.

    Koşulların hepsi zorunlu: WATCH, skor≥min_skor, TRENDING_DOWN değil,
    makro KRIZ/EM_STRES değil, karantina yok. ETF’ler önce.
    """
    rejim = (makro_rejim or "").strip().upper()
    if rejim in ("KRIZ", "EM_STRES"):
        return []
    adaylar: List[HisseAnaliz] = []
    for h in hisseler:
        if getattr(h, "veri_quarantine", False):
            continue
        code = (getattr(h, "signal_v2_code", None) or "").upper()
        if code != "WATCH":
            continue
        if (getattr(h, "signal_v2_regime", None) or "") == "TRENDING_DOWN":
            continue
        skor = getattr(h, "signal_v2_score", None)
        if skor is None:
            skor = getattr(h, "skor", None)
        try:
            if float(skor or 0) < float(min_skor):
                continue
        except (TypeError, ValueError):
            continue
        adaylar.append(h)

    def _key(h: HisseAnaliz):
        etf = 0 if getattr(h, "piyasa", "") == "ETF" else 1
        s = getattr(h, "signal_v2_score", None)
        if s is None:
            s = getattr(h, "skor", 0) or 0
        return (etf, -float(s))

    return sorted(adaylar, key=_key)[:n]


def _bilesik(h: HisseAnaliz) -> float:
    return float(getattr(h, "bilesik_skor", None) or h.skor or 0)


def _etf_sirala(hisseler: List[HisseAnaliz], makro_rejim: str) -> List[HisseAnaliz]:
    return sorted(
        hisseler,
        key=lambda x: (etf_oncelik(x.sektor, makro_rejim), -_bilesik(x)),
    )


def _isin_dedup(hisseler: List["HisseAnaliz"]) -> List["HisseAnaliz"]:
    """Aynı ISIN — farklı borsa kotasyonlarını tek fon olarak say."""
    goren: dict = {}
    cikis: List["HisseAnaliz"] = []
    for h in sorted(hisseler, key=lambda x: -_bilesik(x)):
        if h.isin:
            if h.isin in goren:
                continue
            goren[h.isin] = h.sembol
        cikis.append(h)
    return cikis


def tam_tarama(
    makro_rejim: str = "NOTR",
    demo: bool = False,
    snap=None,
    haber_tara: bool = True,
    profil: Optional[YatirimProfili] = None,
    use_signal_v2: Optional[bool] = None,
) -> TaramaSonucu:
    profil = profil or YatirimProfili()
    v2 = config.USE_SIGNAL_ENGINE_V2 if use_signal_v2 is None else use_signal_v2
    if demo:
        return _demo_tarama(makro_rejim, profil=profil)

    evren = tum_evren()
    semboller = list(dict.fromkeys(
        list(ENDEKSLER.values()) + [s for s, _, _, _, _, _ in evren]
        + ["EURTRY=X", "USDTRY=X", "GBPUSD=X", "EURUSD=X", "CHFUSD=X"]
    ))
    period = "2y" if v2 else "1y"
    df = _indir(semboller, period=period)
    if df.empty:
        return TaramaSonucu(
            uyarilar=["Yahoo Finance verisi alınamadı."],
            makro_rejim=makro_rejim,
        )

    try:
        from signal_engine.data.live_quote import refresh_live_quotes

        refresh_live_quotes(semboller, force=True, min_refresh_sec=0)
    except Exception:
        pass

    eurtry_close = _close_al(df, "EURTRY=X")
    usdtry_close = _close_al(df, "USDTRY=X")
    gbpusd_close = _close_al(df, "GBPUSD=X")
    eurusd_close = _close_al(df, "EURUSD=X")
    chfusd_close = _close_al(df, "CHFUSD=X")

    fx_ok = not eurtry_close.empty
    endeksler = [
        _endeks_analiz(df, ad, sym, makro_rejim, snap, fx_ok=fx_ok)
        for ad, sym in ENDEKSLER.items()
    ]
    tum: List[HisseAnaliz] = []
    for sembol, ad, piyasa, sektor, isin, revolut_ticker in evren:
        if piyasa == "ETF":
            varlik = "etf"
        elif piyasa == "EMTIA":
            varlik = "emtia"
        else:
            varlik = "hisse"
        tum.append(_hisse_analiz(
            df, sembol, ad, piyasa, sektor, makro_rejim, snap,
            isin=isin, revolut_ticker=revolut_ticker, varlik_turu=varlik, profil=profil,
            eurtry_close=eurtry_close,
        ))

    profil_ozet, profil_notlari = profil_tarama_bilgisi(profil, makro_rejim)
    esik = profil_firsat_esik(profil)

    uyarilar: List[str] = []
    # Başarısız / eksik emtia uyarısı
    emtia_bos = [
        h.sembol for h in tum
        if (h.piyasa == "EMTIA" or getattr(h, "varlik_turu", "") == "emtia")
        and (getattr(h, "veri_hatasi", "") or "").startswith("boş")
    ]
    if emtia_bos:
        uyarilar.append(
            f"[UYARI] Emtia tarihsel seri eksik ({', '.join(emtia_bos)}) — "
            "canlı fiyat görünür ama RSI/karar güvenilir değil; taramayı yenileyin."
        )
    if eurtry_close.empty:
        uyarilar.append("[UYARI] EUR bazlı 52H hesaplanamadı — kur verisi çekilemedi")
    elif usdtry_close.empty:
        uyarilar.append("[UYARI] USD/TRY serisi çekilemedi — kur ayarlı getiriler eksik kalabilir")
    elif any(getattr(h, "bist_52h_join_uyari", False) for h in tum if h.sembol.endswith(".IS")):
        dusuk = min(
            (getattr(h, "bist_52h_join_gun", 0) or 0 for h in tum if h.sembol.endswith(".IS")),
            default=0,
        )
        if dusuk and dusuk < 200:
            uyarilar.append(
                f"[BILGI] BIST 52H EUR hizalama: bazı sembollerde join sonrası "
                f"≤{dusuk} gün (eşik 200) — kur/hisse takvim uyumsuzluğu olabilir."
            )
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

    from temel_skor import temel_skor_katmani_uygula
    temel_skor_katmani_uygula(tum, df, makro_rejim, profil)

    if v2:
        from signal_engine.pipeline import signal_engine_v2_uygula
        signal_engine_v2_uygula(
            tum,
            df,
            profil_risk=profil.risk,
            persist_decision_history=True,
            makro_rejim=makro_rejim,
        )

    firsatlar = profil_firsat_sinirla(
        _isin_dedup(_firsatlari_sec(tum, esik, v2=v2)[:20]), profil
    )
    etfler = [h for h in tum if h.piyasa == "ETF"]
    etf_firsat = _isin_dedup(
        _etf_sirala(_firsatlari_sec(etfler, esik, v2=v2)[:10], makro_rejim)
    )

    aday_sem = {h.sembol for h in firsatlar} | {h.sembol for h in etf_firsat}
    from alim_uygunluk import alim_uygunluk_uygula
    if not v2:
        alim_uygunluk_uygula(tum, aday_sem, esik, profil=profil)
    else:
        for h in tum:
            h.alim_uygun_etiket = getattr(h, "signal_v2_decision", "BEKLE")

    from portfoy_yoneticisi import yonetici_notu_uygula
    yonetici_notu_uygula(tum, profil=profil)

    for h in tum:
        h.hikaye = _hikaye_uret(h)

    uygun_n = sum(1 for h in tum if getattr(h, "alim_uygun", "") == "UYGUN")
    if v2:
        ozet = (
            f"Evren: {len(evren)} sembol tarandı (BIST {len(BIST_HISSELER)}, "
            f"SP500 {len(SP500_HISSELER)}, NASDAQ {len(NASDAQ_HISSELER)}, "
            f"Revolut ETF {len(REVOLUT_ETFLER)}, Emtia {len(EMTIA_SEMBOLLER)}) · "
            f"Rejim: {makro_rejim} · Profil: {profil_ozet} · "
            f"Karar AL/GÜÇLÜ AL (UYGUN): {uygun_n} · "
            f"Öne çıkan liste: {len(firsatlar)} "
            f"(yalnızca v2 AL/GÜÇLÜ AL, eşik ≥{esik:.0f}, {len(etf_firsat)} ETF)"
        )
    else:
        ozet = (
            f"Evren: {len(evren)} sembol tarandı (BIST {len(BIST_HISSELER)}, "
            f"SP500 {len(SP500_HISSELER)}, NASDAQ {len(NASDAQ_HISSELER)}, "
            f"Revolut ETF {len(REVOLUT_ETFLER)}, Emtia {len(EMTIA_SEMBOLLER)}) · "
            f"Rejim: {makro_rejim} · Profil: {profil_ozet} · "
            f"Şu an alınabilir (UYGUN): {uygun_n} · "
            f"Teknik skor listesi: {len(firsatlar)} (eşik ≥{esik:.0f}, "
            f"içinde {len(etf_firsat)} ETF — UYGUN ile aynı şey değildir)"
        )

    from veri_butunlugu import tarama_butunluk_ozeti
    vo = tarama_butunluk_ozeti(tum)
    for bu in vo.bar_uyarilari:
        uyarilar.append(f"[WARN] {bu}")

    return TaramaSonucu(
        endeksler=endeksler,
        hisseler=sorted(tum, key=lambda x: -_bilesik(x)),
        alim_firsatlari=firsatlar,
        etf_firsatlari=etf_firsat,
        uyarilar=uyarilar,
        makro_rejim=makro_rejim,
        tarama_ozet=ozet,
        profil_ozet=profil_ozet,
        profil_notlari=profil_notlari,
        eurtry_seri=eurtry_close,
        usdtry_seri=usdtry_close,
        gbpusd_seri=gbpusd_close,
        eurusd_seri=eurusd_close,
        chfusd_seri=chfusd_close,
        veri_ozet_log=vo.log_satiri,
        veri_ozet_ui=vo.ui_satiri or "",
        veri_yok_semboller=list(vo.veri_yok),
        karantina_semboller=list(vo.karantina),
    )


def _demo_tarama(
    makro_rejim: str = "NOTR",
    profil: Optional[YatirimProfili] = None,
) -> TaramaSonucu:
    profil = profil or YatirimProfili()
    profil_ozet, profil_notlari = profil_tarama_bilgisi(profil, makro_rejim)
    from endeks_yonlendirme import karar as endeks_karar

    def _demo_endeks(ad, sym, fiyat, d1g, d1a, d3a, rsi, *, fx_ok=True):
        # Demo SMA: fiyat civarı — trend/çekilme senaryosu için
        sma50 = fiyat * (0.98 if d3a and d3a > 0 else 1.04)
        sma20 = fiyat * (0.99 if d3a and d3a > 0 else 1.02)
        sma200 = fiyat * 0.92
        k = endeks_karar(
            sembol=sym, fiyat=float(fiyat), rsi=rsi,
            sma20=sma20, sma50=sma50, sma200=sma200,
            degisim_1ay=d1a, degisim_3ay=d3a, fx_ok=fx_ok,
            makro_rejim=makro_rejim,
        )
        return EndeksOzet(
            ad, sym, fiyat, d1g, d1a, d3a, rsi, k.sinyal, k.skor,
            platform=k.platform, aksiyon=k.aksiyon, aksiyon_etiket=k.aksiyon_etiket,
            kurulum=k.kurulum, guven=k.guven, gerekce=k.gerekce,
            quote_currency="TRY" if sym.endswith(".IS") else "USD",
            teknik_aksiyon=k.teknik_aksiyon, teknik_aksiyon_etiket=k.teknik_aksiyon_etiket,
            makro_chip=k.makro_chip, makro_not=k.makro_not,
        )

    endeksler = [
        _demo_endeks("BIST 100", "XU100.IS", 14286, 0.8, 5.2, 8.5, 48),
        _demo_endeks("NASDAQ Composite", "^IXIC", 19850, 0.5, 3.1, 12.0, 55),
        _demo_endeks("NASDAQ 100", "^NDX", 21500, 0.6, 3.5, 13.2, 56),
        _demo_endeks("S&P 500", "^GSPC", 5450, 0.3, 2.8, 9.5, 52),
    ]
    hisseler = [
        HisseAnaliz("NVDA", "NVIDIA", "NASDAQ", 135.0, 1.2, 8.5, 15.0, 20.0, 38, 128, 120, "ALIM_FIRSATI", 78, "RSI 38 — RSI dip bölgesi", "teknoloji", teknik_skor=78),
        HisseAnaliz("ASELS.IS", "Aselsan", "BIST", 185.0, -0.5, 4.2, 6.0, 18.0, 36, 180, 175, "ALIM_FIRSATI", 72, "RSI 36 — RSI dip bölgesi", "savunma", teknik_skor=72),
        HisseAnaliz("AAPL", "Apple", "NASDAQ", 210.0, 0.4, 2.1, 5.0, 12.0, 58, 205, 200, "TREND_ALIM", 65, "RSI 58 + SMA50 üstü", "teknoloji", teknik_skor=65),
        HisseAnaliz("GARAN.IS", "Garanti BBVA", "BIST", 142.0, 0.2, 1.5, 2.0, 8.0, 45, 140, 138, "BEKLE", 55, "Net sinyal yok", "finans", teknik_skor=55),
        HisseAnaliz("TSLA", "Tesla", "NASDAQ", 320.0, -1.5, -5.0, -8.0, -15.0, 72, 315, 300, "ASIRI_ALIM", 25, "RSI 72 — aşırı alım", "buyume", teknik_skor=25),
        HisseAnaliz("VWCE.DE", "Vanguard All-World", "ETF", 118.5, 0.3, 2.1, 4.0, 10.0, 44, 116, 114,
                    "ALIM_FIRSATI", 76, "RSI 44 — RSI dip bölgesi", "dunya",
                    isin="IE00BK5BQT80", revolut_ticker="VWCE", varlik_turu="etf", teknik_skor=66),
        HisseAnaliz("CSPX.L", "iShares S&P 500", "ETF", 520.0, 0.2, 1.8, 3.5, 9.0, 52, 515, 510,
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
