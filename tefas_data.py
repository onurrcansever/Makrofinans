# -*- coding: utf-8 -*-
"""
TEFAS fon verisi — pytefas ile resmi API, performans metrikleri.
"""
from __future__ import annotations

import threading
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
    skor_ham: float = 0.0
    skor_notu: str = ""
    oneri: str = "BEKLE"
    skor_pb: str = "EUR"
    getiri_gosterim_1a: Optional[float] = None
    getiri_gosterim_3a: Optional[float] = None
    getiri_gosterim_ybb: Optional[float] = None
    skor_faktorler: Dict[str, float] = field(default_factory=dict)
    akran_kucuk: bool = False
    yonetim_ucreti_pct: Optional[float] = None
    tgo_pct: Optional[float] = None
    gider_kaynak: str = ""
    stopaj_etiket: str = ""


@dataclass
class TefasTaramaSonuc:
    fonlar: List[FonPerformans] = field(default_factory=list)
    kaynak: str = "TEFAS (pytefas)"
    guncelleme: str = ""
    gun: int = 0
    hata: str = ""


def _simdi() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _getiri_hesapla(
    sub: pd.DataFrame,
    gun: int,
    *,
    tolerans_gun: int = 5,
) -> Optional[float]:
    """Takvim günü penceresi getirisi. Tarihçe yetersizse None (ilk bara yapıştırma yok)."""
    if sub.empty or len(sub) < 2:
        return None
    sub = sub.sort_values("date_dt")
    son = float(sub.iloc[-1]["price"])
    if son <= 0:
        return None
    hedef = sub.iloc[-1]["date_dt"] - timedelta(days=gun)
    onceki = sub[sub["date_dt"] <= hedef]
    if onceki.empty:
        ilk = sub.iloc[0]["date_dt"]
        # Seri hedefe yetişmiyorsa (ör. 30g veri ile 90g istek) uydurma getiri yok
        if (ilk - hedef).days > tolerans_gun:
            return None
        bas = float(sub.iloc[0]["price"])
    else:
        bas = float(onceki.iloc[-1]["price"])
    if bas <= 0:
        return None
    return (son / bas - 1.0) * 100.0


def _ybb_getiri(sub: pd.DataFrame, *, tolerans_gun: int = 10) -> Optional[float]:
    """Yıl başından bu yana. YTD serisi eksikse None (kısa cache ile 1A'ya eşitleme yok)."""
    if sub.empty or len(sub) < 2:
        return None
    sub = sub.sort_values("date_dt")
    yil_basi = date(sub.iloc[-1]["date_dt"].year, 1, 1)
    ybb = sub[sub["date_dt"] >= pd.Timestamp(yil_basi)]
    if len(ybb) < 2:
        return None
    ilk = ybb.iloc[0]["date_dt"]
    ilk_d = ilk.date() if hasattr(ilk, "date") else pd.Timestamp(ilk).date()
    if (ilk_d - yil_basi).days > tolerans_gun:
        return None
    bas = float(ybb.iloc[0]["price"])
    son = float(ybb.iloc[-1]["price"])
    if bas <= 0:
        return None
    return (son / bas - 1.0) * 100.0


def _hedef_pencere_gun(gun: int) -> int:
    """1A/3A/YBB için yeterli tarihçe — en az istenen gün ve YTD."""
    bugun = date.today()
    ytd = (bugun - date(bugun.year, 1, 1)).days + 1
    return max(int(gun or 90), 90, min(int(ytd), 370))


def _ham_veri_cek(
    gun: int = 90,
    *,
    timeout: float = 45.0,
    progress_cb=None,
) -> Tuple[Optional[pd.DataFrame], str]:
    """TEFAS YAT fonları — son N gün (bellek + disk önbellek, zaman aşımı korumalı)."""
    global _CACHE

    def _p(phase: str, detail: str = "", **kw) -> None:
        if progress_cb:
            try:
                progress_cb(phase, detail, **kw)
            except Exception:
                pass

    now = time.time()
    if (
        _CACHE.get("df") is not None
        and now - float(_CACHE.get("ts", 0)) < _CACHE_TTL
        and int(_CACHE.get("gun", 0)) >= gun
    ):
        _p("disk", f"Bellek önbelleği · {int(_CACHE['gun'])} gün")
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
        _p(
            "fetch",
            f"TEFAS API · {g} gün tarihçe ({start.isoformat()} → {end.isoformat()})…",
            counter=f"{g}g",
        )
        try:
            from tefas_progress import progress_heartbeat

            # Uzun fetch sırasında UI’nin donmuş görünmemesi
            stop = threading.Event()

            def _beat():
                while not stop.wait(2.0):
                    progress_heartbeat(
                        detail=(
                            f"TEFAS API bekleniyor · {g} gün "
                            f"({start.isoformat()} → {end.isoformat()}) — "
                            "bu adım 1–2 dk sürebilir"
                        ),
                        pct_cap=48.0,
                    )

            thr = threading.Thread(target=_beat, daemon=True, name="tefas-fetch-beat")
            thr.start()
            try:
                df = Crawler().fetch(start, end, kind="YAT", columns="info")
            finally:
                stop.set()
        except Exception as e:
            return None, f"TEFAS hatası: {e}"

        if df is None or df.empty:
            return None, "TEFAS verisi boş"

        df = df.copy()
        df["date_dt"] = pd.to_datetime(df["date"])
        _p("yaz", f"Disk’e yazılıyor · {len(df):,} satır · {g} gün")
        disk_yaz(_disk_key(g), df)
        _bellege_yaz(df, g)
        return df, f"TEFAS canlı ({g} gün, {len(df):,} satır)"

    def _diskten(g: int, *, bayat: bool) -> Tuple[Optional[pd.DataFrame], Optional[float]]:
        return disk_getir(_disk_key(g), TTL["tefas"], bayat_kabul=bayat)

    # 1A/3A/YBB için yeterli pencere (eski min(gun,30) 3A=YBB hatasına yol açıyordu)
    hedef = _hedef_pencere_gun(gun)
    min_tam = max(int(gun or 90), 90)
    pencereler_tam: List[int] = []
    for g in (hedef, max(int(gun), 90), 120, 90):
        g = int(g)
        if g >= min_tam and g not in pencereler_tam:
            pencereler_tam.append(g)
    pencereler_kisa = [g for g in (60, 30, 14) if g not in pencereler_tam]

    def _zaman_asimli(g: int, to: float) -> Tuple[Optional[pd.DataFrame], str]:
        if to and to > 0:
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_indir, g)
                try:
                    return fut.result(timeout=to)
                except FutTimeout:
                    return None, f"TEFAS zaman aşımı ({int(to)} sn, {g} gün)"
        return _indir(g)

    _p("disk", "Disk önbelleği taranıyor…")
    # 1) Taze disk — yalnızca yeterli pencere (kısa 30g cache 3A'yı kilitlemesin)
    for g in pencereler_tam:
        veri, yas = _diskten(g, bayat=False)
        if veri is not None:
            _bellege_yaz(veri, g)
            _p("disk", f"Disk hit · {g} gün" + (f" · yaş {yas:.0f}s" if yas else ""))
            return veri, f"TEFAS disk ({g} gün)"

    # 2) Canlı tam pencere (YTD / 90+)
    for g in pencereler_tam:
        to = max(float(timeout or 45), 120.0 if g >= 180 else 90.0)
        _p("fetch", f"Canlı çekim · {g} gün (zaman aşımı {int(to)}s)…", counter=f"{g}g")
        df, mesaj = _zaman_asimli(g, to)
        if df is not None:
            return df, mesaj

    # 3) Kısa yedek (1H/1A dolu; 3A/YBB hesapta None kalır)
    for g in pencereler_kisa:
        veri, yas = _diskten(g, bayat=False)
        if veri is not None:
            _bellege_yaz(veri, g)
            _p("disk", f"Kısa disk · {g} gün — 3A/YBB eksik olabilir")
            return veri, f"TEFAS disk ({g} gün) · kısa pencere: 3A/YBB eksik olabilir"
    for g in pencereler_kisa:
        _p("fetch", f"Kısa yedek çekim · {g} gün…", counter=f"{g}g")
        df, mesaj = _zaman_asimli(g, max(float(timeout or 45), 45.0))
        if df is not None:
            return df, mesaj + " · kısa pencere: 3A/YBB eksik olabilir"

    # 4) Bayat disk
    for g in pencereler_tam + pencereler_kisa:
        veri, yas = _diskten(g, bayat=True)
        if veri is not None:
            _bellege_yaz(veri, g)
            yas_sn = int(yas or 0)
            not_ = "" if g >= min_tam else " · kısa pencere"
            _p("disk", f"Bayat disk · {g} gün{not_}")
            return (
                veri,
                f"TEFAS disk bayat ({g} gün, {yas_sn // 3600} sa önce){not_}",
            )

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
    """YK + Kuveyt Türk fonları — son dağılım (tefas_data önbelleği)."""
    from tefas_dagilim import FonDagilim, satirdan_dagilim
    from tefas_universe import evren_fon_mu

    df = _breakdown_ham_cek(gun)
    if df is None:
        return {}
    yk = df[df["fund_name"].apply(evren_fon_mu)]
    if yk.empty:
        return {}
    son = yk.sort_values("date_dt").groupby("fund_code").tail(1)
    return {str(r["fund_code"]): satirdan_dagilim(r) for _, r in son.iterrows()}


def yk_fonlari_performans(
    gun: int = 90,
    sadece_yk: bool = True,
    *,
    onceden: Optional[TefasTaramaSonuc] = None,
    progress_cb=None,
) -> TefasTaramaSonuc:
    def _p(phase: str, detail: str = "", **kw) -> None:
        if progress_cb:
            try:
                progress_cb(phase, detail, **kw)
            except Exception:
                pass

    if onceden is not None and not onceden.hata and onceden.gun >= gun:
        return onceden

    df, kaynak = _ham_veri_cek(gun, progress_cb=progress_cb)
    if df is None:
        return TefasTaramaSonuc(hata=kaynak, guncelleme=_simdi())

    if sadece_yk:
        df = df[df["fund_name"].apply(yk_fon_mu)]

    _p("dagilim", "Portföy dağılımı (hisse/döviz/altın)…")
    dagilim_map = {}
    try:
        dagilim_map = yk_dagilim_haritasi(gun=min(14, gun))
    except Exception:
        pass

    _p("returns", "Getiri hesaplanıyor · 1H / 1A / 3A / YBB…")
    fonlar: List[FonPerformans] = []
    gruplar = list(df.groupby("fund_code"))
    n_grp = len(gruplar)
    for i, (kod, grp) in enumerate(gruplar):
        if n_grp and i > 0 and i % max(1, n_grp // 8) == 0:
            _p(
                "returns",
                f"Getiri · {i}/{n_grp} fon",
                counter=f"{i}/{n_grp}",
                pct=55.0 + 15.0 * (i / n_grp),
            )
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

    # İstenen gün ≠ gerçek span; UI/caption için fiili tarihçe
    span_gun = gun
    try:
        if df is not None and not df.empty and "date_dt" in df.columns:
            span_gun = int((df["date_dt"].max() - df["date_dt"].min()).days)
    except Exception:
        span_gun = gun

    return TefasTaramaSonuc(
        fonlar=sorted(fonlar, key=lambda f: f.kod),
        kaynak=kaynak,
        guncelleme=_simdi(),
        gun=span_gun,
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
