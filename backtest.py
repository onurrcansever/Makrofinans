# -*- coding: utf-8 -*-
"""
Geçmiş Senaryo Backtest
========================
Son N ay için aylık snapshot oluşturup algoritmanın ne önereceğini simüle eder.
CDS/enflasyon geçmişi tam API'den gelmediği için yaklaşık tablo kullanılır —
sonuçlar yön gösterir, kesin getiri iddiası değildir.
"""
import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

import config
from allocation_engine import tahsis_hesapla
from decision_engine import PiyasaVerisi
from macro_data import MacroSnapshot

# Yaklaşık makro tablo (CDS bp, enflasyon %, TCMB %) — literatür / piyasa ortalamaları
MAKRO_TABLO: Dict[str, Dict[str, float]] = {
    "2024-01": {"cds": 340, "enflasyon": 64.9, "tcmb": 42.5},
    "2024-04": {"cds": 310, "enflasyon": 69.8, "tcmb": 50.0},
    "2024-07": {"cds": 280, "enflasyon": 61.8, "tcmb": 50.0},
    "2024-10": {"cds": 270, "enflasyon": 48.6, "tcmb": 50.0},
    "2025-01": {"cds": 265, "enflasyon": 42.1, "tcmb": 47.5},
    "2025-04": {"cds": 260, "enflasyon": 38.0, "tcmb": 46.0},
    "2025-07": {"cds": 255, "enflasyon": 36.0, "tcmb": 43.0},
    "2025-10": {"cds": 262, "enflasyon": 35.0, "tcmb": 40.5},
    "2026-01": {"cds": 268, "enflasyon": 34.5, "tcmb": 38.0},
    "2026-04": {"cds": 265, "enflasyon": 35.0, "tcmb": 37.0},
}


def _makro_aylik(anahtar: str) -> Dict[str, float]:
    if anahtar in MAKRO_TABLO:
        return MAKRO_TABLO[anahtar]
    # En yakın ayı bul
    keys = sorted(MAKRO_TABLO.keys())
    for k in reversed(keys):
        if k <= anahtar:
            return MAKRO_TABLO[k]
    return MAKRO_TABLO[keys[0]]


def _yf_aylik(ticker: str, aylar: int) -> pd.Series:
    import yfinance as yf
    end = datetime.now()
    start = end - timedelta(days=30 * aylar + 45)
    df = yf.download(ticker, start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"), progress=False)
    if df.empty:
        return pd.Series(dtype=float)
    col = "Close" if "Close" in df.columns else df.columns[0]
    s = df[col].dropna()
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return s.resample("ME").last().dropna()


def _frankfurter_eurtry(bas: str, bit: str) -> Dict[str, float]:
    import requests
    try:
        r = requests.get(
            f"https://api.frankfurter.app/{bas}..{bit}",
            params={"from": "EUR", "to": "TRY"},
            timeout=15,
        )
        r.raise_for_status()
        rates = r.json().get("rates", {})
        return {t: float(v["TRY"]) for t, v in rates.items()}
    except Exception as e:
        print(f"[UYARI] Frankfurter geçmiş kur alınamadı: {e}")
        return {}


@dataclass
class BacktestSatir:
    tarih: str
    rejim: str
    rejim_etiket: str
    eur_try: float
    bist100: Optional[float]
    btc_usd: Optional[float]
    altin_usd: Optional[float]
    vix: Optional[float]
    cds: float
    enflasyon: float
    tcmb: float
    oncelikli_varlik: str
    agirliklar: Dict[str, float]


@dataclass
class BacktestMetrik:
    toplam_getiri_pct: float
    max_drawdown_pct: float
    sharpe_yillik: Optional[float]
    volatilite_yillik_pct: float
    rejim_degisim_sayisi: int
    en_sik_rejim: str
    mevcut_rejim_oran_pct: float
    model_drift: bool
    drift_mesaji: str
    aylik_getiriler: List[float]
    notlar: List[str]


def backtest_calistir(ay_sayisi: int = 12) -> List[BacktestSatir]:
    eurtry = _yf_aylik("EURTRY=X", ay_sayisi)
    bist = _yf_aylik("XU100.IS", ay_sayisi)
    btc = _yf_aylik("BTC-USD", ay_sayisi)
    altin = _yf_aylik("GC=F", ay_sayisi)
    vix = _yf_aylik("^VIX", ay_sayisi)

    # Frankfurter yedek
    if eurtry.empty:
        bit = datetime.now().strftime("%Y-%m-%d")
        bas = (datetime.now() - timedelta(days=30 * ay_sayisi)).strftime("%Y-%m-%d")
        ff = _frankfurter_eurtry(bas, bit)
        if ff:
            eurtry = pd.Series(ff)
            eurtry.index = pd.to_datetime(eurtry.index)

    if eurtry.empty:
        print("[HATA] EUR/TRY geçmiş verisi alınamadı.")
        return []

    sonuclar: List[BacktestSatir] = []
    for ts, kur in eurtry.tail(ay_sayisi).items():
        anahtar = ts.strftime("%Y-%m")
        makro = _makro_aylik(anahtar)

        def _deger(seri: pd.Series) -> Optional[float]:
            if seri.empty:
                return None
            try:
                idx = seri.index.asof(ts)
                v = seri.loc[idx]
                return float(v.iloc[0]) if hasattr(v, "iloc") and not isinstance(v, (int, float)) else float(v)
            except Exception:
                return None

        bist_v = _deger(bist)
        btc_v = _deger(btc)
        altin_v = _deger(altin)
        vix_v = _deger(vix)

        bist_mom = None
        if not bist.empty and len(bist) >= 2:
            try:
                onceki_idx = bist.index.asof(ts - pd.DateOffset(months=3))
                if onceki_idx in bist.index or True:
                    b0 = float(bist.asof(ts - pd.DateOffset(months=3)))
                    b1 = float(bist.asof(ts))
                    if b0 > 0:
                        bist_mom = (b1 - b0) / b0 * 100
            except Exception:
                pass

        btc_mom = None
        if not btc.empty:
            try:
                b0 = float(btc.asof(ts - pd.DateOffset(months=3)))
                b1 = float(btc.asof(ts))
                if b0 > 0:
                    btc_mom = (b1 - b0) / b0 * 100
            except Exception:
                pass

        veri = PiyasaVerisi(
            eur_try=float(kur),
            usd_try=float(kur) / 1.08,
            fed_faizi=4.5,
            tcmb_politika_faizi=makro["tcmb"],
            tl_mevduat_brut_faiz=makro["tcmb"] / 100 * 0.95,
            cds_5y_bp=makro["cds"],
            rezerv_artiyor=False,
            siyasi_risk_makale_sayisi=3,
            savas_risk_makale_sayisi=8,
        )
        snap = MacroSnapshot(
            veri=veri,
            altin_usd_oz=altin_v,
            gumus_usd_oz=altin_v / 80 if altin_v else None,
            vix=vix_v,
            enflasyon_tr_yillik=makro["enflasyon"],
            eur_usd=1.08,
            bist100=bist_v,
            bist100_3m_degisim=bist_mom,
            btc_usd=btc_v,
            btc_3m_degisim=btc_mom,
            veri_kaynak="backtest",
            veri_zamani=ts.strftime("%Y-%m-%d"),
        )
        tahsis = tahsis_hesapla(snap)
        oncelik = max(tahsis.agirliklar, key=tahsis.agirliklar.get)
        sonuclar.append(
            BacktestSatir(
                tarih=ts.strftime("%Y-%m"),
                rejim=tahsis.rejim.rejim,
                rejim_etiket=tahsis.rejim.etiket,
                eur_try=float(kur),
                bist100=bist_v,
                btc_usd=btc_v,
                altin_usd=altin_v,
                vix=vix_v,
                cds=makro["cds"],
                enflasyon=makro["enflasyon"],
                tcmb=makro["tcmb"],
                oncelikli_varlik=config.VARLIK_ETIKETLERI[oncelik],
                agirliklar=dict(tahsis.agirliklar),
            )
        )
    return sonuclar


def _pct(a: Optional[float], b: Optional[float]) -> float:
    if a is None or b is None or a <= 0:
        return 0.0
    return (b - a) / a


def backtest_metrikleri(
    satirlar: List[BacktestSatir],
    mevcut_rejim: str = "",
) -> Optional[BacktestMetrik]:
    """Portföy simülasyonu + rejim istikrarı + model drift uyarısı."""
    if len(satirlar) < 3:
        return None

    aylik: List[float] = []
    for i in range(1, len(satirlar)):
        prev, cur = satirlar[i - 1], satirlar[i]
        w = prev.agirliklar
        tl_faiz_ay = (prev.tcmb / 100) / 12
        kur_degisim = _pct(prev.eur_try, cur.eur_try)
        r_varlik = {
            "eur_cash": 0.0,
            "usd_cash": 0.0,
            "tl_deposit": tl_faiz_ay - kur_degisim,
            "gold": _pct(prev.altin_usd, cur.altin_usd),
            "silver": _pct(prev.altin_usd, cur.altin_usd) * 0.85,
            "bist": _pct(prev.bist100, cur.bist100),
            "crypto": _pct(prev.btc_usd, cur.btc_usd),
        }
        port = sum(w.get(k, 0) * r_varlik.get(k, 0) for k in w)
        aylik.append(port)

    if not aylik:
        return None

    import statistics

    kum = 1.0
    zirve = 1.0
    max_dd = 0.0
    for r in aylik:
        kum *= 1 + r
        zirve = max(zirve, kum)
        dd = (kum - zirve) / zirve if zirve > 0 else 0
        max_dd = min(max_dd, dd)

    toplam_getiri = (kum - 1) * 100
    ort = statistics.mean(aylik)
    std = statistics.stdev(aylik) if len(aylik) > 1 else 0.0
    vol_yillik = std * (12 ** 0.5) * 100
    sharpe = (ort / std * (12 ** 0.5)) if std > 1e-9 else None

    rejimler = [s.rejim for s in satirlar]
    rejim_degisim = sum(1 for i in range(1, len(rejimler)) if rejimler[i] != rejimler[i - 1])
    frek = {}
    for r in rejimler:
        frek[r] = frek.get(r, 0) + 1
    en_sik = max(frek, key=frek.get)
    mevcut_oran = 0.0
    drift = False
    drift_msg = ""
    if mevcut_rejim:
        mevcut_oran = frek.get(mevcut_rejim, 0) / len(rejimler) * 100
        if mevcut_oran < 20:
            drift = True
            drift_msg = (
                f"Mevcut rejim ({mevcut_rejim}) backtest döneminde yalnızca "
                f"%{mevcut_oran:.0f} süre görüldü — model drift uyarısı."
            )

    notlar = [
        "Portföy simülasyonu: aylık yeniden dengeleme, TL getirisi EUR bazında (faiz − kur).",
        "CDS/enflasyon yaklaşık tablodan — kesin performans iddiası değildir.",
    ]
    if sharpe is not None and sharpe < 0:
        notlar.append("Negatif Sharpe — rejim kuralları bu dönemde EUR nakitte kalmaktan zayıf kalmış olabilir.")

    return BacktestMetrik(
        toplam_getiri_pct=toplam_getiri,
        max_drawdown_pct=max_dd * 100,
        sharpe_yillik=sharpe,
        volatilite_yillik_pct=vol_yillik,
        rejim_degisim_sayisi=rejim_degisim,
        en_sik_rejim=en_sik,
        mevcut_rejim_oran_pct=mevcut_oran,
        model_drift=drift,
        drift_mesaji=drift_msg,
        aylik_getiriler=aylik,
        notlar=notlar,
    )


def rapor_yaz(satirlar: List[BacktestSatir]) -> str:
    if not satirlar:
        return "Backtest verisi yok."
    lines = [
        "BACKTEST RAPORU — aylık rejim ve tahsis simülasyonu",
        "=" * 55,
        "NOT: CDS/enflasyon yaklaşık tablodan; yön analizi içindir.",
        "",
        f"{'Ay':<8} {'Rejim':<18} {'EUR/TRY':>8} {'CDS':>5} {'Öncelik':<18} {'Altın%':>6} {'TL%':>5}",
        "-" * 55,
    ]
    for s in satirlar:
        lines.append(
            f"{s.tarih:<8} {s.rejim:<18} {s.eur_try:>8.1f} {s.cds:>5.0f} "
            f"{s.oncelikli_varlik:<18} {s.agirliklar.get('gold',0)*100:>5.0f} "
            f"{s.agirliklar.get('tl_deposit',0)*100:>5.0f}"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Makro portföy backtest")
    parser.add_argument("--months", type=int, default=12, help="Kaç ay geriye")
    args = parser.parse_args()
    satirlar = backtest_calistir(args.months)
    print(rapor_yaz(satirlar))


if __name__ == "__main__":
    main()
