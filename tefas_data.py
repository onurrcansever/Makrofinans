# -*- coding: utf-8 -*-
"""
TEFAS fon verisi — pytefas ile resmi API, performans metrikleri.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

from tefas_universe import (
    KATEGORILER,
    PARA_BIRIMI,
    fon_kategorisi,
    fon_para_birimi,
    kisa_fon_adi,
    yk_fon_mu,
)

_CACHE_TTL = 3600
_CACHE: Dict[str, object] = {"ts": 0.0, "df": None, "gun": 0}
_BD_CACHE: Dict[str, object] = {"ts": 0.0, "df": None}


@dataclass
class FonPerformans:
    kod: str
    ad: str
    kisa_ad: str
    kategori: str
    kategori_etiket: str
    para_birimi: str
    para_etiket: str
    fiyat: float
    getiri_1h: Optional[float] = None
    getiri_1a: Optional[float] = None
    getiri_3a: Optional[float] = None
    getiri_6a: Optional[float] = None
    getiri_ybb: Optional[float] = None
    yatirimci_sayisi: Optional[int] = None
    fon_buyuklugu: Optional[float] = None
    hisse_pct: Optional[float] = None
    bono_repo_pct: Optional[float] = None
    doviz_pct: Optional[float] = None
    altin_pct: Optional[float] = None
    dagilim_ozet: str = ""
    etkin_kategori: str = ""
    skor: float = 0.0
    skor_notu: str = ""
    oneri: str = "IZLE"


@dataclass
class TefasTaramaSonuc:
    fonlar: List[FonPerformans] = field(default_factory=list)
    kaynak: str = "TEFAS (pytefas)"
    guncelleme: str = ""
    gun: int = 0
    hata: str = ""


def _simdi() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _getiri_hesapla(sub: pd.DataFrame, gun: int) -> Optional[float]:
    if sub.empty or len(sub) < 2:
        return None
    sub = sub.sort_values("date_dt")
    son = float(sub.iloc[-1]["price"])
    if son <= 0:
        return None
    hedef = sub.iloc[-1]["date_dt"] - timedelta(days=gun)
    onceki = sub[sub["date_dt"] <= hedef]
    if onceki.empty:
        bas = float(sub.iloc[0]["price"])
    else:
        bas = float(onceki.iloc[-1]["price"])
    if bas <= 0:
        return None
    return (son / bas - 1.0) * 100.0


def _ybb_getiri(sub: pd.DataFrame) -> Optional[float]:
    if sub.empty:
        return None
    sub = sub.sort_values("date_dt")
    yil_basi = date(sub.iloc[-1]["date_dt"].year, 1, 1)
    ybb = sub[sub["date_dt"] >= pd.Timestamp(yil_basi)]
    if len(ybb) < 2:
        return _getiri_hesapla(sub, 180)
    bas = float(ybb.iloc[0]["price"])
    son = float(ybb.iloc[-1]["price"])
    if bas <= 0:
        return None
    return (son / bas - 1.0) * 100.0


def _ham_veri_cek(gun: int = 90, *, timeout: float = 45.0) -> Tuple[Optional[pd.DataFrame], str]:
    """TEFAS YAT fonları — son N gün (bellek + disk önbellek, zaman aşımı korumalı)."""
    global _CACHE
    now = time.time()
    if (
        _CACHE.get("df") is not None
        and now - float(_CACHE.get("ts", 0)) < _CACHE_TTL
        and int(_CACHE.get("gun", 0)) >= gun
    ):
        return _CACHE["df"], f"TEFAS önbellek ({int(_CACHE['gun'])} gün)"

    from disk_onbellek import TTL, disk_getir, disk_yaz

    def _disk_key(g: int) -> str:
        return f"tefas_ham:{g}"

    def _bellege_yaz(df: pd.DataFrame, g: int) -> pd.DataFrame:
        _CACHE["ts"] = time.time()
        _CACHE["df"] = df
        _CACHE["gun"] = g
        return df

    def _indir(g: int) -> Tuple[Optional[pd.DataFrame], str]:
        try:
            from pytefas import Crawler
        except ImportError:
            return None, "pytefas kurulu değil — pip install pytefas"

        end = date.today()
        start = end - timedelta(days=g)
        try:
            df = Crawler().fetch(start, end, kind="YAT", columns="info")
        except Exception as e:
            return None, f"TEFAS hatası: {e}"

        if df is None or df.empty:
            return None, "TEFAS verisi boş"

        df = df.copy()
        df["date_dt"] = pd.to_datetime(df["date"])
        disk_yaz(_disk_key(g), df)
        _bellege_yaz(df, g)
        return df, f"TEFAS canlı ({g} gün, {len(df):,} satır)"

    def _diskten(g: int, *, bayat: bool) -> Tuple[Optional[pd.DataFrame], Optional[float]]:
        return disk_getir(_disk_key(g), TTL["tefas"], bayat_kabul=bayat)

    # Hızlı pencere: 90 gün ~70 sn sürebilir; portföy için 30/14 gün yeterli (~8 sn)
    pencereler = []
    for g in (min(gun, 30), 14):
        if g not in pencereler:
            pencereler.append(g)

    # Taze disk
    for g in pencereler:
        veri, yas = _diskten(g, bayat=False)
        if veri is not None:
            _bellege_yaz(veri, g)
            return veri, f"TEFAS disk ({g} gün)"

    def _zaman_asimli(g: int) -> Tuple[Optional[pd.DataFrame], str]:
        if timeout and timeout > 0:
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_indir, g)
                try:
                    return fut.result(timeout=timeout)
                except FutTimeout:
                    return None, f"TEFAS zaman aşımı ({int(timeout)} sn, {g} gün)"
        return _indir(g)

    # Canlı çekim — kısa pencereden başla
    for g in pencereler:
        df, mesaj = _zaman_asimli(g)
        if df is not None:
            return df, mesaj

    # Zaman aşımı: bayat disk (en az bir fiyat serisi olsun)
    for g in pencereler:
        veri, yas = _diskten(g, bayat=True)
        if veri is not None:
            _bellege_yaz(veri, g)
            yas_sn = int(yas or 0)
            return veri, f"TEFAS disk bayat ({g} gün, {yas_sn // 3600} sa önce)"

    return None, "TEFAS verisi alınamadı — internet bağlantısını kontrol edin"


def _breakdown_ham_cek(gun: int = 14):
    """Portföy dağılımı — tek önbellek (yk_fonlari ile aynı oturumda paylaşılır)."""
    global _BD_CACHE
    now = time.time()
    if (
        _BD_CACHE.get("df") is not None
        and now - float(_BD_CACHE.get("ts", 0)) < _CACHE_TTL
    ):
        return _BD_CACHE["df"]

    try:
        from pytefas import Crawler
    except ImportError:
        return None

    end = date.today()
    start = end - timedelta(days=max(3, min(gun, 14)))
    try:
        df = Crawler().fetch(start, end, kind="YAT", columns="breakdown")
    except Exception:
        return None
    if df is None or df.empty:
        return None
    df = df.copy()
    df["date_dt"] = pd.to_datetime(df["date"])
    _BD_CACHE = {"ts": now, "df": df}
    return df


def yk_dagilim_haritasi(gun: int = 7) -> Dict:
    """Yapı Kredi fonları — son dağılım (tefas_data önbelleği)."""
    from tefas_dagilim import FonDagilim, satirdan_dagilim

    df = _breakdown_ham_cek(gun)
    if df is None:
        return {}
    yk = df[df["fund_name"].str.contains("YAPI KRED", case=False, na=False)]
    if yk.empty:
        return {}
    son = yk.sort_values("date_dt").groupby("fund_code").tail(1)
    return {str(r["fund_code"]): satirdan_dagilim(r) for _, r in son.iterrows()}


def yk_fonlari_performans(
    gun: int = 90,
    sadece_yk: bool = True,
    *,
    onceden: Optional[TefasTaramaSonuc] = None,
) -> TefasTaramaSonuc:
    if onceden is not None and not onceden.hata and onceden.gun >= gun:
        return onceden

    df, kaynak = _ham_veri_cek(gun)
    if df is None:
        return TefasTaramaSonuc(hata=kaynak, guncelleme=_simdi())

    if sadece_yk:
        df = df[df["fund_name"].apply(yk_fon_mu)]

    dagilim_map = {}
    try:
        dagilim_map = yk_dagilim_haritasi(gun=min(14, gun))
    except Exception:
        pass

    fonlar: List[FonPerformans] = []
    for kod, grp in df.groupby("fund_code"):
        grp = grp.dropna(subset=["price"])
        if grp.empty:
            continue
        son = grp.sort_values("date_dt").iloc[-1]
        ad = str(son.get("fund_name") or kod)
        kat = fon_kategorisi(ad)
        d = dagilim_map.get(str(kod))
        if d:
            kat = d.etkin_kategori
        pb = fon_para_birimi(ad)
        yat = son.get("investor_count")
        buy = son.get("portfolio_size")
        fonlar.append(
            FonPerformans(
                kod=str(kod),
                ad=ad,
                kisa_ad=kisa_fon_adi(ad),
                kategori=kat,
                kategori_etiket=KATEGORILER.get(kat, kat),
                para_birimi=pb,
                para_etiket=PARA_BIRIMI.get(pb, pb),
                fiyat=float(son["price"]),
                getiri_1h=_getiri_hesapla(grp, 7),
                getiri_1a=_getiri_hesapla(grp, 30),
                getiri_3a=_getiri_hesapla(grp, 90),
                getiri_6a=_getiri_hesapla(grp, min(180, gun)),
                getiri_ybb=_ybb_getiri(grp),
                yatirimci_sayisi=int(yat) if pd.notna(yat) else None,
                fon_buyuklugu=float(buy) if pd.notna(buy) else None,
                hisse_pct=d.hisse_pct if d else None,
                bono_repo_pct=d.bono_repo_pct if d else None,
                doviz_pct=d.doviz_borc_pct if d else None,
                altin_pct=d.altin_pct if d else None,
                dagilim_ozet=d.ozet if d else "",
                etkin_kategori=kat,
            )
        )

    return TefasTaramaSonuc(
        fonlar=sorted(fonlar, key=lambda f: f.kod),
        kaynak=kaynak,
        guncelleme=_simdi(),
        gun=gun,
    )


def secili_fon_serisi(
    kodlar: List[str],
    gun: int = 90,
) -> pd.DataFrame:
    """Karşılaştırma grafiği — normalize fiyat serisi."""
    df, _ = _ham_veri_cek(gun)
    if df is None or not kodlar:
        return pd.DataFrame()

    kodlar_u = [k.upper() for k in kodlar]
    sub = df[df["fund_code"].str.upper().isin(kodlar_u)].copy()
    if sub.empty:
        return pd.DataFrame()

    out_rows = []
    for kod, grp in sub.groupby("fund_code"):
        grp = grp.sort_values("date_dt")
        bas = float(grp.iloc[0]["price"])
        if bas <= 0:
            continue
        for _, row in grp.iterrows():
            out_rows.append(
                {
                    "tarih": row["date_dt"],
                    "kod": kod,
                    "ad": kisa_fon_adi(str(row["fund_name"])),
                    "endeks": float(row["price"]) / bas * 100.0,
                }
            )
    return pd.DataFrame(out_rows)


def fon_detay(kod: str, gun: int = 90) -> Optional[FonPerformans]:
    sonuc = yk_fonlari_performans(gun=gun)
    for f in sonuc.fonlar:
        if f.kod.upper() == kod.upper():
            return f
    return None
