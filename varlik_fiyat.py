# -*- coding: utf-8 -*-
"""Varlıklarım — canlı fiyat ve dönem getirileri (miktar × birim fiyat)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

from macro_data import MacroSnapshot
from stock_scanner import _close_al, _indir
from varliklarim import BIRIMLI_TURLER, VarlikPortfoy, VarlikPozisyon

PERIYOTLAR = {
    "1G": 1,
    "1H": 7,
    "1A": 30,
    "3A": 90,
    "6A": 180,
}

YF_SEMBOL = {
    "altin": "GC=F",
    "gumus": "SI=F",
    "kripto": "BTC-USD",
}

ONS_GRAM = 31.1034768

_yf_cache: Dict[str, pd.DataFrame] = {}
_tefas_cache: Dict[str, Dict[str, pd.Series]] = {}


def fiyat_onbellegi_temizle() -> None:
    """Yenile butonunda gün içi Yahoo/TEFAS önbelleğini sıfırla."""
    _yf_cache.clear()
    _tefas_cache.clear()


def _tum_bugun_alim(pozisyonlar: List[VarlikPozisyon], bugun: date) -> bool:
    if not pozisyonlar:
        return True
    return all(_gun_tutma(p.alim_tarihi, bugun) <= 0 for p in pozisyonlar)


def _yf_indir(
    semboller: List[str],
    period: str = "6mo",
    *,
    cache_salt: str = "",
    aninda: bool = False,
) -> pd.DataFrame:
    """Yahoo fiyat serileri — bellek + disk; aninda=True ise ağ beklemez."""
    if not semboller:
        return pd.DataFrame()
    key = f"{date.today().isoformat()}:{cache_salt}:{period}:{','.join(semboller)}"
    if key in _yf_cache:
        return _yf_cache[key]

    from disk_onbellek import TTL, disk_getir_aninda, disk_getir_swr

    def _uret():
        df = _indir(semboller, period=period, timeout=25.0)
        return df if df is not None and not df.empty else None

    disk_key = f"yf:{period}:{','.join(semboller)}"
    if aninda:
        df = disk_getir_aninda(disk_key, TTL["fiyat_seri"], _uret, varsayilan=pd.DataFrame())
    else:
        df = disk_getir_swr(disk_key, TTL["fiyat_seri"], _uret, blokla=True)
    if df is None:
        df = pd.DataFrame()
    _yf_cache[key] = df
    return df


@dataclass
class PozisyonDeger:
    pozisyon: VarlikPozisyon
    guncel_birim: float
    alim_birim: float
    miktar_goster: str
    guncel_deger: float
    maliyet_deger: float
    kar_zarar: float
    kar_zarar_pct: float
    para: str
    getiriler: Dict[str, Optional[float]] = field(default_factory=dict)


@dataclass
class PortfoyDeger:
    pozisyonlar: List[PozisyonDeger]
    toplam: Dict[str, float]
    agirlikli_getiri: Dict[str, Optional[float]]
    maliyet_toplam: Dict[str, float]
    fiyat_bekleniyor: bool = False


def _pb_cevir(tutar: float, kaynak_pb: str, hedef_pb: str, eur_try: float, usd_try: float) -> float:
    if kaynak_pb == hedef_pb:
        return tutar
    if kaynak_pb == "TL":
        tl = tutar
    elif kaynak_pb == "EUR":
        tl = tutar * eur_try
    elif kaynak_pb == "USD":
        tl = tutar * (usd_try or eur_try * 1.08)
    else:
        tl = tutar
    if hedef_pb == "TL":
        return tl
    if hedef_pb == "EUR":
        return tl / eur_try if eur_try > 0 else tutar
    if hedef_pb == "USD":
        kur = usd_try or eur_try * 1.08
        return tl / kur if kur > 0 else tutar
    return tutar


def _gun_tutma(alim_tarihi: str, bugun: date) -> int:
    if not alim_tarihi:
        return 0
    try:
        alim = datetime.fromisoformat(alim_tarihi).date()
    except ValueError:
        return 0
    return max(0, (bugun - alim).days)


def _seri_fiyat(seri: pd.Series, hedef: date) -> Optional[float]:
    if seri.empty:
        return None
    seri = seri.dropna().sort_index()
    idx = pd.to_datetime(seri.index)
    mask = idx.date <= hedef
    if not mask.any():
        return float(seri.iloc[0])
    return float(seri.iloc[mask][-1])


def _getiri_tarih_arasi(seri: pd.Series, bas: date, bit: date) -> Optional[float]:
    if seri.empty or bas > bit:
        return None
    f_bas = _seri_fiyat(seri, bas)
    f_bit = _seri_fiyat(seri, bit)
    if f_bas is None or f_bit is None or f_bas <= 0:
        return None
    return (f_bit / f_bas - 1.0) * 100.0


def _getiri_alimden(seri: pd.Series, alim_tarihi: str, bugun: date) -> Optional[float]:
    gun_t = _gun_tutma(alim_tarihi, bugun)
    if gun_t <= 0 or seri.empty:
        return 0.0 if gun_t <= 0 else None
    try:
        alim = datetime.fromisoformat(alim_tarihi).date()
    except ValueError:
        return None
    return _getiri_tarih_arasi(seri, alim, bugun)


def _getiriler_portfoy(
    seri: pd.Series,
    alim_tarihi: str,
    bugun: date,
) -> Dict[str, Optional[float]]:
    """Dönem getirileri — yalnızca sizin tutma sürenize göre."""
    gun_t = _gun_tutma(alim_tarihi, bugun)
    if gun_t <= 0:
        return {et: 0.0 for et in PERIYOTLAR}
    try:
        alim = datetime.fromisoformat(alim_tarihi).date()
    except ValueError:
        return {et: None for et in PERIYOTLAR}

    out: Dict[str, Optional[float]] = {}
    for et, gun in PERIYOTLAR.items():
        if gun_t < gun:
            out[et] = _getiri_tarih_arasi(seri, alim, bugun)
        else:
            ref = max(alim, bugun - timedelta(days=gun))
            out[et] = _getiri_tarih_arasi(seri, ref, bugun)
    return out


def _deger_tutar_bazli(maliyet: float, getiri_pct: Optional[float]) -> float:
    if getiri_pct is None:
        return maliyet
    return maliyet * (1.0 + getiri_pct / 100.0)


def _tl_gram_altin(snap: MacroSnapshot) -> Optional[float]:
    oz = snap.altin_usd_oz
    usd = snap.veri.usd_try or (snap.veri.eur_try or 35.0) * 1.08
    if oz and usd:
        return oz * usd / ONS_GRAM
    return None


def _tl_gram_gumus(snap: MacroSnapshot) -> Optional[float]:
    oz = snap.gumus_usd_oz
    usd = snap.veri.usd_try or (snap.veri.eur_try or 35.0) * 1.08
    if oz and usd:
        return oz * usd / ONS_GRAM
    return None


def _alim_tarihi_date(alim_tarihi: str) -> Optional[date]:
    if not alim_tarihi:
        return None
    try:
        return datetime.fromisoformat(alim_tarihi).date()
    except ValueError:
        return None


def _fx_period(portfoy: VarlikPortfoy, bugun: date) -> str:
    """Döviz alım tarihine göre Yahoo FX geçmişi süresi."""
    en_eski: Optional[date] = None
    for p in portfoy.pozisyonlar:
        if p.tur not in ("nakit_eur", "nakit_usd", "nakit_ron"):
            continue
        g = _alim_tarihi_date(p.alim_tarihi)
        if g and (en_eski is None or g < en_eski):
            en_eski = g
    if en_eski is None:
        return "6mo"
    gun = (bugun - en_eski).days + 14
    if gun <= 30:
        return "1mo"
    if gun <= 90:
        return "3mo"
    if gun <= 180:
        return "6mo"
    if gun <= 365:
        return "1y"
    return "2y"


def _doviz_alim_kuru(
    p: VarlikPozisyon,
    fx_seri: pd.Series,
    qty: float,
    maliyet_tl: float,
) -> Optional[float]:
    """Alış kuru — güncel kur asla varsayılan alış kuru olmaz."""
    if p.alim_fiyati > 0:
        return p.alim_fiyati
    alim_g = _alim_tarihi_date(p.alim_tarihi)
    if alim_g and not fx_seri.empty:
        kur = _seri_fiyat(fx_seri, alim_g)
        if kur and kur > 0:
            return kur
    if qty > 0 and maliyet_tl > qty * 1.5:
        return maliyet_tl / qty
    return None


def _legacy_tutar_modu(p: VarlikPozisyon) -> bool:
    """Eski kayıt: yalnızca TL tutar girilmiş, birim fiyat yok."""
    if p.tur not in BIRIMLI_TURLER:
        return False
    if p.alim_fiyati > 0 and p.miktar > 0 and abs(p.miktar * p.alim_fiyati - p.maliyet_toplam()) > 1:
        return False
    if p.alim_fiyati > 0:
        return False
    maliyet = p.maliyet_toplam()
    if maliyet <= 0:
        return False
    if p.miktar <= 0:
        return True
    oran = p.miktar / maliyet if maliyet > 0 else 0
    return 0.85 <= oran <= 1.15


def _miktar_maliyet_coz(
    p: VarlikPozisyon,
    birim_alim: Optional[float],
) -> Tuple[float, float, float]:
    """(miktar, maliyet, alim_fiyati) — birimli veya legacy."""
    maliyet = p.maliyet_toplam()
    if p.birimli() and p.alim_fiyati > 0 and p.miktar > 0:
        return p.miktar, maliyet, p.alim_fiyati
    if p.birimli() and birim_alim and birim_alim > 0 and maliyet > 0:
        qty = maliyet / birim_alim
        return qty, maliyet, birim_alim
    return p.miktar, maliyet, p.alim_fiyati or (birim_alim or 0.0)


def _miktar_etiket(p: VarlikPozisyon, qty: float) -> str:
    if qty <= 0:
        return "—"
    if p.tur in ("altin", "gumus"):
        return f"{qty:,.2f} gr"
    if p.tur == "kripto":
        return f"{qty:.6f} BTC"
    if p.tur in ("tefas", "hisse", "etf"):
        return f"{qty:,.2f} adet"
    if p.tur == "nakit_eur":
        return f"{qty:,.2f} EUR"
    if p.tur == "nakit_usd":
        return f"{qty:,.2f} USD"
    if p.tur == "nakit_ron":
        return f"{qty:,.2f} RON"
    return f"{qty:,.0f} {p.para_birimi or 'TL'}"


def pozisyon_legacy_normalize(
    p: VarlikPozisyon,
    *,
    birim_alim: Optional[float],
) -> bool:
    """TL tutar kaydını miktar × birim fiyata çevirir. True = değişti."""
    if not _legacy_tutar_modu(p) or not birim_alim or birim_alim <= 0:
        return False
    maliyet = p.maliyet or p.miktar
    p.miktar = maliyet / birim_alim
    p.alim_fiyati = birim_alim
    p.maliyet = maliyet
    return True


def portfoy_legacy_normalize(
    portfoy: VarlikPortfoy,
    snap: MacroSnapshot,
    *,
    cache_salt: str = "",
) -> bool:
    """İlk açılışta eski TL-tutar pozisyonlarını birimli modele taşır."""
    degisti = False
    deger = portfoy_degerle(portfoy, snap, cache_salt=cache_salt, normalize=False)
    for pd_ in deger.pozisyonlar:
        p = pd_.pozisyon
        if pozisyon_legacy_normalize(p, birim_alim=pd_.alim_birim or None):
            degisti = True
    return degisti


def _mevduat_deger(p: VarlikPozisyon, bugun: date) -> float:
    if p.miktar <= 0:
        return 0.0
    gun = _gun_tutma(p.alim_tarihi, bugun)
    net_oran = (p.brut_faiz / 100.0) * (1 - 0.15) if p.brut_faiz > 1 else p.brut_faiz * 0.85
    return p.miktar * (1 + net_oran * gun / 365.0)


def _mevduat_getiriler(p: VarlikPozisyon, bugun: date) -> Dict[str, Optional[float]]:
    gun_t = _gun_tutma(p.alim_tarihi, bugun)
    if gun_t <= 0:
        return {et: 0.0 for et in PERIYOTLAR}
    gunluk = (p.brut_faiz / 100 * 0.85) / 365 if p.brut_faiz > 1 else 0
    return {
        et: round(gunluk * min(gun, gun_t) * 100, 2) if gunluk else 0.0
        for et, gun in PERIYOTLAR.items()
    }


def _yf_sembolleri(pozisyonlar: List[VarlikPozisyon]) -> List[str]:
    out = set()
    for p in pozisyonlar:
        if p.tur in ("hisse", "etf") and p.sembol:
            out.add(p.sembol)
        elif p.tur in YF_SEMBOL:
            out.add(YF_SEMBOL[p.tur])
        elif p.tur == "nakit_eur":
            out.add("EURTRY=X")
        elif p.tur == "nakit_usd":
            out.add("USDTRY=X")
        elif p.tur == "nakit_ron":
            out.add("EURRON=X")  # RONTRY=X Yahoo'da yok; çapraz kur: ron_try = eur_try / eur_ron
    return sorted(out)


def _tefas_serileri(kodlar: List[str], gun: int = 90, *, aninda: bool = False) -> Dict[str, pd.Series]:
    if not kodlar:
        return {}
    key = f"{date.today().isoformat()}:{gun}:{','.join(sorted(k.upper() for k in kodlar))}"
    if key in _tefas_cache:
        return _tefas_cache[key]

    from disk_onbellek import TTL, disk_getir_aninda, disk_getir_swr

    def _uret():
        try:
            from tefas_data import _ham_veri_cek
            df, _ = _ham_veri_cek(min(gun, 90), timeout=45.0)
            if df is None:
                return None
            seriler = {}
            for kod in kodlar:
                sub = df[df["fund_code"].str.upper() == kod.upper()].sort_values("date_dt")
                if sub.empty:
                    continue
                seriler[kod.upper()] = sub.set_index("date_dt")["price"].astype(float)
            return seriler or None
        except Exception:
            return None

    disk_key = f"tefas_seri:{gun}:{','.join(sorted(k.upper() for k in kodlar))}"
    if aninda:
        out = disk_getir_aninda(disk_key, TTL["tefas"], _uret, varsayilan={}) or {}
    else:
        out = disk_getir_swr(disk_key, TTL["tefas"], _uret, blokla=True) or {}
    _tefas_cache[key] = out
    return out


def _etf_birim_tl(sym: str, fiyat: float, snap: MacroSnapshot) -> float:
    """LSE/USD ETF fiyatını TL'ye çevir (para_birimi TL ise)."""
    if fiyat <= 0:
        return 0.0
    sym_u = sym.upper()
    usd = snap.veri.usd_try or (snap.veri.eur_try or 35.0) * 1.08
    eur = snap.veri.eur_try or 35.0
    if sym_u.endswith(".L") or sym_u.endswith(".LON"):
        return fiyat * usd
    if sym_u.endswith(".DE") or sym_u.endswith(".PA"):
        return fiyat * eur
    return fiyat * usd


def portfoy_degerle(
    portfoy: VarlikPortfoy,
    snap: MacroSnapshot,
    tefas_seriler: Optional[Dict[str, pd.Series]] = None,
    *,
    cache_salt: str = "",
    normalize: bool = True,
    aninda: bool = False,
) -> PortfoyDeger:
    fiyat_bekleniyor = False
    piyasa_turleri = {"tefas", "hisse", "etf", "altin", "gumus", "kripto", "nakit_eur"}
    eur_try = snap.veri.eur_try or 35.0
    usd_try = snap.veri.usd_try or eur_try * 1.08
    bugun = date.today()
    bugun_alim = _tum_bugun_alim(portfoy.pozisyonlar, bugun)

    tefas_kodlar = [p.sembol.upper() for p in portfoy.pozisyonlar if p.tur == "tefas" and p.sembol]
    if tefas_seriler is None:
        tefas_seriler = _tefas_serileri(tefas_kodlar, aninda=aninda)

    semboller = _yf_sembolleri(portfoy.pozisyonlar)
    fx_period = _fx_period(portfoy, bugun)
    df = _yf_indir(semboller, period=fx_period, cache_salt=cache_salt, aninda=aninda) if semboller else pd.DataFrame()
    fx_eur = _close_al(df, "EURTRY=X") if not df.empty else pd.Series(dtype=float)
    fx_usd = _close_al(df, "USDTRY=X") if not df.empty else pd.Series(dtype=float)

    poz_degerler: List[PozisyonDeger] = []
    for p in portfoy.pozisyonlar:
        getiriler: Dict[str, Optional[float]] = {}
        birim_guncel = 0.0
        birim_alim = p.alim_fiyati
        maliyet_d = p.maliyet_toplam()
        deger = maliyet_d
        seri = pd.Series(dtype=float)
        # nakit_eur/usd/ron için deger TL cinsinden hesaplanır; para="TL" olarak sakla
        poz_para_override: Optional[str] = None

        if p.tur == "nakit_tl":
            birim_guncel = 1.0
            deger = p.miktar
            maliyet_d = p.maliyet or p.miktar
            p_miktar = p.miktar
            getiriler = {et: 0.0 for et in PERIYOTLAR}
        elif p.tur == "nakit_eur":
            # deger/maliyet_d TL cinsinden → para="TL" kullan (çift dönüşümü önle)
            poz_para_override = "TL"
            birim_guncel = eur_try
            if p.para_birimi == "EUR" and p.miktar > 0:
                # Normal: miktar EUR cinsinden girilmiş
                qty = p.miktar
            elif p.alim_fiyati > 0 and p.miktar > 0 and p.maliyet > p.miktar * 1.5:
                # Form bug düzeltmesi: para_birimi="TL" kaydedilmiş ama miktar EUR,
                # maliyet=miktar×alim_fiyati (TL). miktar'ı EUR olarak kullan.
                qty = p.miktar
            elif p.maliyet > 0 and eur_try > 0:
                # Legacy mod: miktar TL tutar olarak girilmiş
                qty = p.maliyet / eur_try
            else:
                qty = p.miktar if p.miktar > 0 else 0.0
            maliyet_kayit = p.maliyet if p.maliyet > 0 else 0.0
            alim_kur = _doviz_alim_kuru(p, fx_eur, qty, maliyet_kayit)
            birim_alim = alim_kur or 0.0
            if alim_kur and qty > 0:
                maliyet_d = qty * alim_kur
            elif maliyet_kayit > 0:
                maliyet_d = maliyet_kayit
            else:
                maliyet_d = qty * eur_try if qty > 0 else 0.0
            deger = qty * eur_try if qty > 0 else maliyet_d
            p_miktar = qty
            getiriler = _getiriler_portfoy(fx_eur, p.alim_tarihi, bugun) if not fx_eur.empty else {et: 0.0 for et in PERIYOTLAR}
        elif p.tur == "nakit_usd":
            # deger/maliyet_d TL cinsinden → para="TL" kullan
            poz_para_override = "TL"
            birim_guncel = usd_try
            if p.para_birimi == "USD" and p.miktar > 0:
                qty = p.miktar
            elif p.alim_fiyati > 0 and p.miktar > 0 and p.maliyet > p.miktar * 1.5:
                # Form bug düzeltmesi: para_birimi="TL" ama miktar USD
                qty = p.miktar
            elif p.maliyet > 0 and usd_try > 0:
                qty = p.maliyet / usd_try
            else:
                qty = p.miktar if p.miktar > 0 else 0.0
            maliyet_kayit = p.maliyet if p.maliyet > 0 else 0.0
            alim_kur = _doviz_alim_kuru(p, fx_usd, qty, maliyet_kayit)
            birim_alim = alim_kur or 0.0
            if alim_kur and qty > 0:
                maliyet_d = qty * alim_kur
            elif maliyet_kayit > 0:
                maliyet_d = maliyet_kayit
            else:
                maliyet_d = qty * usd_try if qty > 0 else 0.0
            deger = qty * usd_try if qty > 0 else maliyet_d
            p_miktar = qty
            getiriler = _getiriler_portfoy(fx_usd, p.alim_tarihi, bugun) if not fx_usd.empty else {et: 0.0 for et in PERIYOTLAR}
        elif p.tur == "nakit_ron":
            # RON/TRY çapraz kur: EURRON=X → ron_try = eur_try / eur_ron
            # (RONTRY=X Yahoo'da 404 döndürüyor)
            poz_para_override = "TL"
            fx_eur_ron = _close_al(df, "EURRON=X") if not df.empty else pd.Series(dtype=float)
            if not fx_eur_ron.empty:
                eur_ron_rate = float(fx_eur_ron.iloc[-1])
                ron_try = eur_try / eur_ron_rate if eur_ron_rate > 0 else 0.0
                # RON/TL geçmiş serisi: EURRON ile EUR/TL çaprazından türet
                fx_ron = (fx_eur_ron.apply(lambda x: eur_try / x if x > 0 else 0.0)
                          if not fx_eur_ron.empty else pd.Series(dtype=float))
            else:
                ron_try = 0.0
                fx_ron = pd.Series(dtype=float)
            if ron_try <= 0:
                ron_try = eur_try / 5.2  # son çare — yaklaşık EUR/RON sabit
            birim_guncel = ron_try
            qty = p.miktar if p.miktar > 0 else 0.0
            maliyet_kayit = p.maliyet if p.maliyet > 0 else 0.0
            alim_kur = _doviz_alim_kuru(p, fx_ron, qty, maliyet_kayit)
            birim_alim = alim_kur or 0.0
            if alim_kur and qty > 0:
                maliyet_d = qty * alim_kur
            elif maliyet_kayit > 0:
                maliyet_d = maliyet_kayit
            else:
                maliyet_d = qty * ron_try if qty > 0 else 0.0
            deger = qty * ron_try if qty > 0 else maliyet_d
            p_miktar = qty
            getiriler = (_getiriler_portfoy(fx_ron, p.alim_tarihi, bugun)
                         if not fx_ron.empty else {et: 0.0 for et in PERIYOTLAR})
        elif p.tur == "tl_mevduat":
            deger = _mevduat_deger(p, bugun)
            birim_guncel = deger / p.miktar if p.miktar > 0 else 1.0
            maliyet_d = p.maliyet or p.miktar
            getiriler = _mevduat_getiriler(p, bugun)
            p_miktar = p.miktar
        elif p.tur == "tefas":
            seri = tefas_seriler.get(p.sembol.upper(), pd.Series(dtype=float)) if p.sembol else pd.Series(dtype=float)
            if not seri.empty:
                birim_guncel = float(seri.iloc[-1])
                alim_g = _alim_tarihi_date(p.alim_tarihi)
                if birim_alim <= 0 and alim_g:
                    birim_alim = _seri_fiyat(seri, alim_g) or birim_guncel
            elif aninda and p.alim_fiyati > 0:
                birim_guncel = p.alim_fiyati
                birim_alim = p.alim_fiyati
                fiyat_bekleniyor = True
            p_miktar, maliyet_d, birim_alim = _miktar_maliyet_coz(p, birim_alim)
            if p_miktar > 0 and birim_guncel > 0:
                deger = p_miktar * birim_guncel
            else:
                ret = _getiri_alimden(seri, p.alim_tarihi, bugun)
                deger = _deger_tutar_bazli(maliyet_d, ret)
            getiriler = _getiriler_portfoy(seri, p.alim_tarihi, bugun) if not seri.empty else {et: 0.0 for et in PERIYOTLAR}
        elif p.tur == "altin":
            birim_guncel = _tl_gram_altin(snap) or 0.0
            sym = YF_SEMBOL["altin"]
            seri_usd = _close_al(df, sym) if sym else pd.Series(dtype=float)
            if not seri_usd.empty and usd_try > 0:
                seri = seri_usd * usd_try / ONS_GRAM
            else:
                seri = pd.Series(dtype=float)
            alim_g = _alim_tarihi_date(p.alim_tarihi)
            if birim_alim <= 0 and alim_g and not seri.empty:
                birim_alim = _seri_fiyat(seri, alim_g) or birim_guncel
            elif birim_alim <= 0:
                birim_alim = birim_guncel
            if aninda and birim_guncel <= 0 and p.alim_fiyati > 0:
                birim_guncel = p.alim_fiyati
                birim_alim = p.alim_fiyati
                fiyat_bekleniyor = True
            p_miktar, maliyet_d, birim_alim = _miktar_maliyet_coz(p, birim_alim)
            if p_miktar > 0 and birim_guncel > 0:
                deger = p_miktar * birim_guncel
            else:
                ret = _getiri_alimden(seri, p.alim_tarihi, bugun) if not seri.empty else None
                deger = _deger_tutar_bazli(maliyet_d, ret)
            getiriler = _getiriler_portfoy(seri, p.alim_tarihi, bugun) if not seri.empty else {et: 0.0 for et in PERIYOTLAR}
        elif p.tur == "gumus":
            birim_guncel = _tl_gram_gumus(snap) or 0.0
            sym = YF_SEMBOL["gumus"]
            seri_usd = _close_al(df, sym) if sym else pd.Series(dtype=float)
            if not seri_usd.empty and usd_try > 0:
                seri = seri_usd * usd_try / ONS_GRAM
            else:
                seri = pd.Series(dtype=float)
            alim_g = _alim_tarihi_date(p.alim_tarihi)
            if birim_alim <= 0 and alim_g and not seri.empty:
                birim_alim = _seri_fiyat(seri, alim_g) or birim_guncel
            elif birim_alim <= 0:
                birim_alim = birim_guncel
            if aninda and birim_guncel <= 0 and p.alim_fiyati > 0:
                birim_guncel = p.alim_fiyati
                birim_alim = p.alim_fiyati
                fiyat_bekleniyor = True
            p_miktar, maliyet_d, birim_alim = _miktar_maliyet_coz(p, birim_alim)
            if p_miktar > 0 and birim_guncel > 0:
                deger = p_miktar * birim_guncel
            else:
                ret = _getiri_alimden(seri, p.alim_tarihi, bugun) if not seri.empty else None
                deger = _deger_tutar_bazli(maliyet_d, ret)
            getiriler = _getiriler_portfoy(seri, p.alim_tarihi, bugun) if not seri.empty else {et: 0.0 for et in PERIYOTLAR}
        elif p.tur in ("hisse", "etf", "kripto"):
            sym = p.sembol or YF_SEMBOL.get(p.tur, "")
            seri_raw = _close_al(df, sym) if sym else pd.Series(dtype=float)
            if p.tur == "hisse":
                seri = seri_raw
                birim_guncel = float(seri.iloc[-1]) if not seri.empty else 0.0
            elif p.tur == "etf" and p.para_birimi == "TL" and not seri_raw.empty:
                sym_u = sym.upper()
                kur = eur_try if sym_u.endswith((".DE", ".PA")) else usd_try
                seri = seri_raw * kur
                birim_guncel = float(seri.iloc[-1])
            elif p.tur == "kripto" and p.para_birimi == "TL" and not seri_raw.empty:
                seri = seri_raw * usd_try
                birim_guncel = float(seri.iloc[-1])
            else:
                seri = seri_raw
                birim_guncel = float(seri.iloc[-1]) if not seri.empty else 0.0
            alim_g = _alim_tarihi_date(p.alim_tarihi)
            if birim_alim <= 0 and alim_g and not seri.empty:
                birim_alim = _seri_fiyat(seri, alim_g) or birim_guncel
            elif birim_alim <= 0:
                birim_alim = birim_guncel
            if aninda and birim_guncel <= 0 and p.alim_fiyati > 0:
                birim_guncel = p.alim_fiyati
                birim_alim = p.alim_fiyati
                fiyat_bekleniyor = True
            elif aninda and birim_guncel <= 0 and p.alim_fiyati <= 0 and p.tur in piyasa_turleri:
                fiyat_bekleniyor = True
            p_miktar, maliyet_d, birim_alim = _miktar_maliyet_coz(p, birim_alim)
            if p_miktar > 0 and birim_guncel > 0:
                deger = p_miktar * birim_guncel
            else:
                ret = _getiri_alimden(seri, p.alim_tarihi, bugun)
                deger = _deger_tutar_bazli(maliyet_d, ret)
            getiriler = (
                {et: 0.0 for et in PERIYOTLAR}
                if bugun_alim and _gun_tutma(p.alim_tarihi, bugun) <= 0 and p_miktar <= 0
                else _getiriler_portfoy(seri, p.alim_tarihi, bugun) if not seri.empty else {et: 0.0 for et in PERIYOTLAR}
            )
        else:
            p_miktar = p.miktar
            deger = maliyet_d
            getiriler = {et: 0.0 for et in PERIYOTLAR}

        if normalize and p.birimli() and _legacy_tutar_modu(p) and birim_alim > 0:
            pozisyon_legacy_normalize(p, birim_alim=birim_alim)

        kz = deger - maliyet_d
        kz_pct = (kz / maliyet_d * 100) if maliyet_d > 0 else 0.0
        # poz_para_override: döviz pozisyonlarında deger TL'de; çift dönüşümü önle
        _para = poz_para_override if poz_para_override else (p.para_birimi or "TL")
        poz_degerler.append(
            PozisyonDeger(
                pozisyon=p,
                guncel_birim=birim_guncel,
                alim_birim=birim_alim,
                miktar_goster=_miktar_etiket(p, p_miktar if p.tur != "nakit_tl" else p.miktar),
                guncel_deger=deger,
                maliyet_deger=maliyet_d,
                kar_zarar=kz,
                kar_zarar_pct=kz_pct,
                para=_para,
                getiriler=getiriler,
            )
        )
        poz_para_override = None  # sıfırla

    toplam = {"TL": 0.0, "EUR": 0.0, "USD": 0.0}
    maliyet_toplam = {"TL": 0.0, "EUR": 0.0, "USD": 0.0}
    for pd_ in poz_degerler:
        # pd_.para döviz pozisyonlarında "TL"'ye override edilmiş olabilir;
        # pd_.pozisyon.para_birimi DEĞİL pd_.para kullan — çift dönüşümü önle.
        pb = pd_.para
        toplam["TL"] += _pb_cevir(pd_.guncel_deger, pb, "TL", eur_try, usd_try)
        toplam["EUR"] += _pb_cevir(pd_.guncel_deger, pb, "EUR", eur_try, usd_try)
        toplam["USD"] += _pb_cevir(pd_.guncel_deger, pb, "USD", eur_try, usd_try)
        maliyet_toplam["TL"] += _pb_cevir(pd_.maliyet_deger, pb, "TL", eur_try, usd_try)
        maliyet_toplam["EUR"] += _pb_cevir(pd_.maliyet_deger, pb, "EUR", eur_try, usd_try)
        maliyet_toplam["USD"] += _pb_cevir(pd_.maliyet_deger, pb, "USD", eur_try, usd_try)

    agirlikli: Dict[str, Optional[float]] = {}
    for et in PERIYOTLAR:
        num = 0.0
        den = 0.0
        for pd_ in poz_degerler:
            g = pd_.getiriler.get(et)
            if g is None:
                continue
            w = pd_.maliyet_deger
            if w <= 0:
                continue
            num += w * g
            den += w
        agirlikli[et] = round(num / den, 2) if den > 0 else 0.0

    return PortfoyDeger(
        pozisyonlar=poz_degerler,
        toplam=toplam,
        maliyet_toplam=maliyet_toplam,
        agirlikli_getiri=agirlikli,
        fiyat_bekleniyor=fiyat_bekleniyor,
    )


def tefas_fiyat_haritasi(kodlar: List[str]) -> Dict[str, float]:
    seriler = _tefas_serileri(kodlar, gun=30)
    return {k: float(v.iloc[-1]) for k, v in seriler.items() if not v.empty}
