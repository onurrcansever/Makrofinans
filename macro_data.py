# -*- coding: utf-8 -*-
"""
Makro Veri Katmanı
===================
Canlı / gecikmeli piyasa verilerini toplar, birleştirir ve önbelleğe yazar.
Ücretsiz kaynaklar: Frankfurter, FRED, EVDS, GDELT, Yahoo Finance (yfinance).
"""
import json
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import config
import data_sources as ds
from decision_engine import PiyasaVerisi
from free_fallbacks import (
    cds_al,
    enflasyon_al,
    fed_faizi_al,
    rezerv_trend_al,
    savas_risk_al,
    siyasi_risk_al,
    tcmb_faizi_al,
    tl_makro_risk_al,
)
from yapikredi_rates import yapikredi_tl_faizleri
from db_paths import market_cache_db


@dataclass
class MacroSnapshot:
    """Genişletilmiş piyasa görünümü — çoklu varlık tahsisi için."""
    veri: PiyasaVerisi
    altin_usd_oz: Optional[float] = None
    gumus_usd_oz: Optional[float] = None
    altin_eur_oz: Optional[float] = None
    gumus_eur_oz: Optional[float] = None
    vix: Optional[float] = None
    enflasyon_tr_yillik: Optional[float] = None
    eur_usd: Optional[float] = None
    bist100: Optional[float] = None
    bist100_3m_degisim: Optional[float] = None
    bist100_1g_degisim: Optional[float] = None
    btc_usd: Optional[float] = None
    btc_3m_degisim: Optional[float] = None
    btc_1g_degisim: Optional[float] = None
    eur_try_1g_degisim: Optional[float] = None
    vix_1g_degisim: Optional[float] = None
    altin_1g_degisim: Optional[float] = None
    altin_3m_degisim: Optional[float] = None
    bist_vol_30g: Optional[float] = None
    bist_vol_1g_degisim: Optional[float] = None
    veri_kaynak: str = ""
    veri_zamani: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    cekim_uyarilari: List[str] = field(default_factory=list)
    kaynak_haritasi: Dict[str, str] = field(default_factory=dict)
    girdi_dogrulama: Optional[Any] = None
    rejim_donduruldu: bool = False


def _uyari(uyarilar: List[str], mesaj: str) -> None:
    print(f"[UYARI] {mesaj}")
    uyarilar.append(mesaj)


def _fred_son_deger(api_key: str, series_id: str) -> Optional[float]:
    if not api_key:
        return None
    try:
        import requests
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 5,
            },
            timeout=ds.TIMEOUT,
        )
        r.raise_for_status()
        for obs in r.json().get("observations", []):
            if obs.get("value") not in (None, ".", ""):
                return float(obs["value"])
    except Exception as e:
        print(f"[UYARI] FRED {series_id} çekilemedi: {e}")
    return None


def _yf_gunluk_degisim(ticker: str) -> Optional[float]:
    """Resmi previousClose varsa onu kullan; yoksa history son iki mum."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        fi = getattr(t, "fast_info", None) or {}
        last = fi.get("lastPrice") or fi.get("regularMarketPrice")
        prev = fi.get("previousClose") or fi.get("regularMarketPreviousClose")
        if last is None or prev is None:
            info = t.info or {}
            last = last or info.get("regularMarketPrice") or info.get("currentPrice")
            prev = prev or info.get("regularMarketPreviousClose") or info.get("previousClose")
        if last is not None and prev is not None and float(prev) > 0:
            return (float(last) - float(prev)) / float(prev) * 100
        hist = t.history(period="5d", auto_adjust=True)
        if hist.empty or len(hist) < 2:
            return None
        close = hist["Close"].dropna()
        if len(close) < 2:
            return None
        onceki, son = float(close.iloc[-2]), float(close.iloc[-1])
        if onceki <= 0:
            return None
        return (son - onceki) / onceki * 100
    except Exception as e:
        print(f"[UYARI] yfinance {ticker} günlük: {e}")
        return None


def _frankfurter_gunluk_degisim(from_ccy: str, to_ccy: str) -> Optional[float]:
    """ECB Frankfurter — son iki işlem günü arası kur değişimi (%)."""
    try:
        import requests
        from datetime import date, timedelta
        bitis = date.today()
        baslangic = bitis - timedelta(days=10)
        r = requests.get(
            f"https://api.frankfurter.app/{baslangic.isoformat()}..{bitis.isoformat()}",
            params={"from": from_ccy, "to": to_ccy},
            timeout=ds.TIMEOUT,
        )
        r.raise_for_status()
        gunluk = r.json().get("rates", {})
        tarihler = sorted(gunluk.keys())
        if len(tarihler) < 2:
            return None
        onceki = float(gunluk[tarihler[-2]][to_ccy])
        son = float(gunluk[tarihler[-1]][to_ccy])
        return (son - onceki) / onceki * 100 if onceki else None
    except Exception as e:
        print(f"[UYARI] Frankfurter günlük {from_ccy}/{to_ccy}: {e}")
        return _yf_gunluk_degisim(f"{from_ccy}{to_ccy}=X")


def _yf_son_fiyat(ticker: str) -> Optional[float]:
    """Yahoo Finance — history fallback (fast_info bazen None/bozuk döner)."""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception as e:
        print(f"[UYARI] yfinance {ticker}: {e}")
        return None


def _yf_analiz(
    ticker: str,
    momentum_gun: int = 63,
    vol_pencere: Optional[int] = None,
    period: str = "6mo",
) -> Dict[str, Optional[float]]:
    """
    Tek indirme ile fiyat + günlük değişim + momentum (+ opsiyonel realize vol).
    Aynı ticker için tekrarlı API çağrılarını önler.
    """
    import math
    sonuc: Dict[str, Optional[float]] = {
        "fiyat": None, "degisim_pct": None, "degisim_1g": None,
        "vol": None, "vol_1g": None,
    }
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period=period, auto_adjust=True)
        if hist.empty or len(hist) < 2:
            return sonuc
        close = hist["Close"].dropna()
        fiyat = float(close.iloc[-1])
        sonuc["fiyat"] = fiyat

        fi = getattr(t, "fast_info", None) or {}
        last = fi.get("lastPrice") or fi.get("regularMarketPrice") or fiyat
        prev = fi.get("previousClose") or fi.get("regularMarketPreviousClose")
        if prev is None:
            try:
                info = t.info or {}
                prev = info.get("regularMarketPreviousClose") or info.get("previousClose")
                last = last or info.get("regularMarketPrice") or info.get("currentPrice") or fiyat
            except Exception:
                pass
        if last is not None and prev is not None and float(prev) > 0:
            sonuc["fiyat"] = float(last)
            sonuc["degisim_1g"] = (float(last) - float(prev)) / float(prev) * 100
        else:
            onceki_gun = float(close.iloc[-2])
            if onceki_gun:
                sonuc["degisim_1g"] = (fiyat - onceki_gun) / onceki_gun * 100

        hedef = max(0, len(close) - momentum_gun)
        baz = float(close.iloc[hedef]) if len(close) > momentum_gun else float(close.iloc[0])
        if baz:
            sonuc["degisim_pct"] = (float(sonuc["fiyat"]) - baz) / baz * 100

        if vol_pencere and len(close) >= vol_pencere + 3:
            ret = close.pct_change().dropna()

            def _yillik_vol(seri) -> Optional[float]:
                if len(seri) < vol_pencere:
                    return None
                penc = seri.iloc[-vol_pencere:]
                if penc.std() < 1e-12:
                    return 0.0
                return float(penc.std() * math.sqrt(252) * 100)

            vol = _yillik_vol(ret)
            vol_onceki = _yillik_vol(ret.iloc[:-1])
            sonuc["vol"] = vol
            if vol is not None and vol_onceki is not None:
                sonuc["vol_1g"] = vol - vol_onceki
        return sonuc
    except Exception as e:
        print(f"[UYARI] yfinance {ticker} çekilemedi: {e}")
        return sonuc


def _eur_usd_spot() -> Optional[float]:
    try:
        import requests
        r = requests.get(
            "https://api.frankfurter.app/latest",
            params={"from": "EUR", "to": "USD"},
            timeout=ds.TIMEOUT,
        )
        r.raise_for_status()
        return float(r.json()["rates"]["USD"])
    except Exception as e:
        print(f"[UYARI] EUR/USD çekilemedi: {e}")
        return None


def _enflasyon_tr(api_key: str) -> Tuple[Optional[float], str]:
    tufe = ds.evds_tufe_yoy(api_key)
    if tufe:
        val, detay = tufe
        return val, f"TCMB EVDS — {detay}"
    return None, "varsayilan"


def _piyasa_fiyatlari() -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Kur, endeks, emtia — paralel Yahoo/Frankfurter çekimi."""
    from concurrent.futures import ThreadPoolExecutor

    kaynak: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        fut_eur = ex.submit(_yf_analiz, "EURTRY=X", period="1mo")
        fut_usd = ex.submit(_yf_analiz, "USDTRY=X", period="1mo")
        fut_altin = ex.submit(_yf_analiz, "GC=F", period="3mo")
        fut_vix = ex.submit(_yf_analiz, "^VIX", period="3mo")
        fut_bist = ex.submit(_yf_analiz, "XU100.IS", vol_pencere=30, period="6mo")
        fut_btc = ex.submit(_yf_analiz, "BTC-USD", period="3mo")
        fut_gumus = ex.submit(_yf_son_fiyat, "SI=F")
        fut_eur_usd = ex.submit(_eur_usd_spot)
        eur_a = fut_eur.result()
        usd_a = fut_usd.result()
        altin_a = fut_altin.result()
        vix_a = fut_vix.result()
        bist = fut_bist.result()
        btc = fut_btc.result()
        gumus = fut_gumus.result()
        eur_usd = fut_eur_usd.result()

    eur_try = eur_a["fiyat"]
    usd_try = usd_a["fiyat"]
    if eur_try:
        kaynak["eur_try"] = "Yahoo Finance (EURTRY=X, spot ~15 dk gecikme)"
    else:
        eur_try = ds.eur_try_spot()
        kaynak["eur_try"] = "Frankfurter (ECB, günlük referans)" if eur_try else "—"
    if usd_try:
        kaynak["usd_try"] = "Yahoo Finance (USDTRY=X, spot ~15 dk gecikme)"
    else:
        usd_try = ds.usd_try_spot()
        kaynak["usd_try"] = "Frankfurter (ECB, günlük referans)" if usd_try else "—"

    if eur_usd is None and eur_try and usd_try and usd_try > 0:
        eur_usd = eur_try / usd_try
        kaynak["eur_usd"] = "Hesaplanan (EUR/TRY ÷ USD/TRY)"
    else:
        kaynak["eur_usd"] = "Frankfurter" if eur_usd else "—"

    altin = altin_a["fiyat"]
    kaynak["altin"] = "Yahoo Finance (GC=F vadeli)" if altin else "—"
    if altin is None:
        altin = _fred_son_deger(config.FRED_API_KEY, "GOLDPMGBD228NLBM")
        kaynak["altin"] = "FRED (Londra altin, gecikmeli)" if altin else "—"

    kaynak["gumus"] = "Yahoo Finance (SI=F vadeli)" if gumus else "—"

    vix = vix_a["fiyat"]
    kaynak["vix"] = "Yahoo Finance (^VIX)" if vix else "—"
    if vix is None:
        vix = _fred_son_deger(config.FRED_API_KEY, "VIXCLS")
        kaynak["vix"] = "FRED (VIXCLS)" if vix else "—"

    kaynak["bist100"] = "Yahoo Finance (XU100.IS)" if bist["fiyat"] else "—"
    kaynak["bist_vol"] = (
        "Yahoo XU100.IS — 30G realize vol (yıllık %, TR proxy)"
        if bist["vol"] is not None else "—"
    )

    kaynak["btc"] = "Yahoo Finance (BTC-USD)" if btc["fiyat"] else "—"

    eur_try_1g = eur_a["degisim_1g"]
    if eur_try_1g is None:
        eur_try_1g = _frankfurter_gunluk_degisim("EUR", "TRY")

    return {
        "eur_try": eur_try,
        "usd_try": usd_try,
        "eur_usd": eur_usd,
        "altin_usd_oz": altin,
        "gumus_usd_oz": gumus,
        "vix": vix,
        "bist100": bist["fiyat"],
        "bist100_3m_degisim": bist["degisim_pct"],
        "bist100_1g_degisim": bist["degisim_1g"],
        "btc_usd": btc["fiyat"],
        "btc_3m_degisim": btc["degisim_pct"],
        "btc_1g_degisim": btc["degisim_1g"],
        "eur_try_1g_degisim": eur_try_1g,
        "vix_1g_degisim": vix_a["degisim_1g"],
        "altin_1g_degisim": altin_a["degisim_1g"],
        "altin_3m_degisim": altin_a["degisim_pct"],
        "bist_vol_30g": bist["vol"],
        "bist_vol_1g_degisim": bist["vol_1g"],
    }, kaynak


def demo_snapshot() -> MacroSnapshot:
    """Senaryo simülasyonu — piyasa fiyatları canlı, makro parametreler sabit."""
    piyasa, kaynak = _piyasa_fiyatlari()
    kaynak["cds"] = "Demo senaryo (265 bp)"
    kaynak["siyasi_risk"] = "Demo senaryo (5 haber)"
    kaynak["fed_faizi"] = "Demo senaryo"
    kaynak["enflasyon"] = "Demo senaryo (%35)"
    kaynak["tcmb_faizi"] = "Demo senaryo (%37)"
    kaynak["rezerv"] = "Demo senaryo (azalıyor)"
    ykb = yapikredi_tl_faizleri()
    if ykb:
        tl_mevduat = ykb.tl_1y_brut / 100
        kaynak["tl_mevduat"] = ykb.kaynak
    else:
        tl_mevduat = 0.40
        kaynak["tl_mevduat"] = "Demo varsayılan (%40)"

    veri = PiyasaVerisi(
        eur_try=piyasa["eur_try"] or 53.2,
        usd_try=piyasa["usd_try"] or 46.7,
        fed_faizi=4.33,
        tcmb_politika_faizi=37.0,
        tl_mevduat_brut_faiz=tl_mevduat,
        cds_5y_bp=265,
        rezerv_artiyor=False,
        siyasi_risk_makale_sayisi=5,
        savas_risk_makale_sayisi=12,
        savas_risk_guvenilir=True,
    )
    eur_usd = piyasa["eur_usd"] or 1.08
    altin = piyasa["altin_usd_oz"]
    gumus = piyasa["gumus_usd_oz"]

    snap = MacroSnapshot(
        veri=veri,
        altin_usd_oz=altin,
        gumus_usd_oz=gumus,
        altin_eur_oz=altin / eur_usd if altin and eur_usd else None,
        gumus_eur_oz=gumus / eur_usd if gumus and eur_usd else None,
        vix=piyasa["vix"],
        enflasyon_tr_yillik=35.0,
        eur_usd=eur_usd,
        bist100=piyasa["bist100"],
        bist100_3m_degisim=piyasa["bist100_3m_degisim"],
        bist100_1g_degisim=piyasa.get("bist100_1g_degisim"),
        btc_usd=piyasa["btc_usd"],
        btc_3m_degisim=piyasa["btc_3m_degisim"],
        btc_1g_degisim=piyasa.get("btc_1g_degisim"),
        eur_try_1g_degisim=piyasa.get("eur_try_1g_degisim"),
        vix_1g_degisim=piyasa.get("vix_1g_degisim"),
        altin_1g_degisim=piyasa.get("altin_1g_degisim"),
        altin_3m_degisim=piyasa.get("altin_3m_degisim"),
        bist_vol_30g=piyasa.get("bist_vol_30g"),
        bist_vol_1g_degisim=piyasa.get("bist_vol_1g_degisim"),
        veri_kaynak="demo",
        cekim_uyarilari=[],
        kaynak_haritasi=kaynak,
    )

    from girdi_dogrulama import girdi_dogrulama_uygula

    gd = girdi_dogrulama_uygula(
        {
            "cds": veri.cds_5y_bp,
            "enflasyon": snap.enflasyon_tr_yillik,
            "tcmb_faizi": veri.tcmb_politika_faizi,
            "eur_try": veri.eur_try,
            "altin_usd": altin,
        }
    )
    snap.girdi_dogrulama = gd
    snap.rejim_donduruldu = gd.rejim_donduruldu
    if gd.uyarilar:
        snap.cekim_uyarilari = list(gd.uyarilar)
    for anahtar, gs in gd.gostergeler.items():
        if gs.durum == "ONAY_BEKLIYOR":
            kaynak[anahtar] = (kaynak.get(anahtar, "") + " [onay bekliyor]").strip()
        elif gs.durum == "SUPHELI":
            kaynak[anahtar] = (kaynak.get(anahtar, "") + " [SUPHELI]").strip()
    snap.kaynak_haritasi = kaynak
    return snap


def canli_snapshot(taze: bool = True, _tick: int = 0) -> MacroSnapshot:
    """Tam otomatik — tüm makro veriler canlı kaynaklardan (taze=True: önbellek atlanır)."""
    from concurrent.futures import ThreadPoolExecutor
    from cds_guven import cds_guvenli_al, cds_sonuc_al, cds_sonuc_kaydet

    kaynak: Dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=8) as ex:
        fut_piyasa = ex.submit(_piyasa_fiyatlari)
        fut_enf = ex.submit(enflasyon_al, config.EVDS_API_KEY, taze)
        fut_fed = ex.submit(fed_faizi_al, config.FRED_API_KEY)
        fut_siy = ex.submit(siyasi_risk_al, config.SIYASI_RISK_ANAHTAR_KELIMELER, taze)
        fut_tcmb = ex.submit(tcmb_faizi_al, taze)
        fut_ykb = ex.submit(yapikredi_tl_faizleri, cache_kullan=not taze)
        fut_rez = ex.submit(rezerv_trend_al, config.EVDS_API_KEY)
        fut_sav = ex.submit(savas_risk_al, taze=taze)
        fut_tl_makro = ex.submit(tl_makro_risk_al, taze)

        piyasa, kaynak_p = fut_piyasa.result()
        enflasyon, kaynak["enflasyon"] = fut_enf.result()
        fed, kaynak["fed_faizi"] = fut_fed.result()
        siyasi, kaynak["siyasi_risk"] = fut_siy.result()
        tcmb, kaynak["tcmb_faizi"] = fut_tcmb.result()
        ykb = fut_ykb.result()
        rezerv_artiyor, kaynak["rezerv"] = fut_rez.result()
        savas, kaynak["savas_risk"], savas_guven = fut_sav.result()
        tl_makro, kaynak["tl_makro_risk"] = fut_tl_makro.result()

    kaynak.update(kaynak_p)
    uyarilar: List[str] = []
    onceden = cds_sonuc_al(_tick)
    if onceden is not None:
        cds_sonuc = onceden
    else:
        cds_sonuc = cds_guvenli_al(
            vix=piyasa.get("vix"),
            siyasi=siyasi,
            savas=savas or 0,
            taze=taze,
        )
        cds_sonuc_kaydet(cds_sonuc, _tick)
    cds = cds_sonuc.deger
    kaynak["cds"] = cds_sonuc.kaynak
    if cds_sonuc.uyari:
        uyarilar.extend(cds_sonuc.uyari)
    if cds_sonuc.ham is not None and abs(cds_sonuc.ham - cds) > 1:
        kaynak["cds_ham"] = f"{cds_sonuc.ham:.0f} bp (Investing ham)"
    if ykb:
        tl_mevduat = ykb.tl_1y_brut / 100
        kaynak["tl_mevduat"] = ykb.kaynak
    else:
        tl_mevduat = (tcmb or 37.0) / 100 * 0.95
        kaynak["tl_mevduat"] = "TCMB türetilmiş yedek"

    veri = PiyasaVerisi(
        eur_try=piyasa["eur_try"],
        usd_try=piyasa["usd_try"],
        fed_faizi=fed,
        tcmb_politika_faizi=tcmb,
        tl_mevduat_brut_faiz=tl_mevduat,
        cds_5y_bp=cds,
        rezerv_artiyor=rezerv_artiyor,
        siyasi_risk_makale_sayisi=siyasi,
        savas_risk_makale_sayisi=savas,
        savas_risk_guvenilir=savas_guven,
        tl_makro_risk_aktif=tl_makro.get("tl_makro_risk_aktif"),
        tl_faiz_indirim_haber=tl_makro.get("tl_faiz_indirim_haber"),
        tl_erken_secim_haber=tl_makro.get("tl_erken_secim_haber"),
        tl_erken_secim_anormal=tl_makro.get("tl_erken_secim_anormal"),
    )

    eur_usd = piyasa["eur_usd"]
    altin = piyasa["altin_usd_oz"]
    gumus = piyasa["gumus_usd_oz"]

    snap = MacroSnapshot(
        veri=veri,
        altin_usd_oz=altin,
        gumus_usd_oz=gumus,
        altin_eur_oz=altin / eur_usd if altin and eur_usd else None,
        gumus_eur_oz=gumus / eur_usd if gumus and eur_usd else None,
        vix=piyasa["vix"],
        enflasyon_tr_yillik=enflasyon,
        eur_usd=eur_usd,
        bist100=piyasa["bist100"],
        bist100_3m_degisim=piyasa["bist100_3m_degisim"],
        bist100_1g_degisim=piyasa.get("bist100_1g_degisim"),
        btc_usd=piyasa["btc_usd"],
        btc_3m_degisim=piyasa["btc_3m_degisim"],
        btc_1g_degisim=piyasa.get("btc_1g_degisim"),
        eur_try_1g_degisim=piyasa.get("eur_try_1g_degisim"),
        vix_1g_degisim=piyasa.get("vix_1g_degisim"),
        altin_1g_degisim=piyasa.get("altin_1g_degisim"),
        altin_3m_degisim=piyasa.get("altin_3m_degisim"),
        bist_vol_30g=piyasa.get("bist_vol_30g"),
        bist_vol_1g_degisim=piyasa.get("bist_vol_1g_degisim"),
        veri_kaynak="canli",
        cekim_uyarilari=uyarilar,
        kaynak_haritasi=kaynak,
    )

    from girdi_dogrulama import girdi_dogrulama_uygula
    from data_sources import tcmb_politika_faizi_dogrula

    tcmb_uyar = tcmb_politika_faizi_dogrula(tcmb, kaynak.get("tcmb_faizi", ""))
    uyarilar.extend(tcmb_uyar)

    gd = girdi_dogrulama_uygula(
        {
            "cds": cds,
            "enflasyon": enflasyon,
            "tcmb_faizi": tcmb,
            "eur_try": piyasa.get("eur_try"),
            "altin_usd": altin,
        }
    )
    snap.girdi_dogrulama = gd
    snap.rejim_donduruldu = gd.rejim_donduruldu
    uyarilar.extend(gd.uyarilar)
    for anahtar, gs in gd.gostergeler.items():
        if gs.durum == "SUPHELI":
            kaynak[anahtar] = (kaynak.get(anahtar, "") + " [SUPHELI]").strip()
        elif gs.durum == "ONAY_BEKLIYOR":
            kaynak[anahtar] = (kaynak.get(anahtar, "") + " [onay bekliyor]").strip()
    snap.cekim_uyarilari = uyarilar
    snap.kaynak_haritasi = kaynak

    cache_kaydet(snap)
    return snap


def cache_kaydet(snap: MacroSnapshot) -> None:
    try:
        conn = sqlite3.connect(market_cache_db())
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                kaynak TEXT,
                payload TEXT NOT NULL
            )
            """
        )
        payload = {
            "veri": asdict(snap.veri),
            "altin_usd_oz": snap.altin_usd_oz,
            "gumus_usd_oz": snap.gumus_usd_oz,
            "vix": snap.vix,
            "enflasyon_tr_yillik": snap.enflasyon_tr_yillik,
            "eur_usd": snap.eur_usd,
            "bist100": snap.bist100,
            "btc_usd": snap.btc_usd,
            "veri_kaynak": snap.veri_kaynak,
        }
        conn.execute(
            "INSERT INTO snapshots (ts, kaynak, payload) VALUES (?, ?, ?)",
            (snap.veri_zamani, snap.veri_kaynak, json.dumps(payload)),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[UYARI] Önbellek yazılamadı: {e}")


def cache_gecmisi(limit: int = 30) -> List[Dict[str, Any]]:
    db = market_cache_db()
    if not os.path.exists(db):
        return []
    try:
        conn = sqlite3.connect(db)
        rows = conn.execute(
            "SELECT ts, kaynak, payload FROM snapshots ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [{"ts": r[0], "kaynak": r[1], "payload": json.loads(r[2])} for r in rows]
    except Exception:
        return []
