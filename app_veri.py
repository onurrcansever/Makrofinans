# -*- coding: utf-8 -*-
"""
Streamlit cache_data + kalıcı disk önbelleği — ağır veri çekimleri.

Tarama/TEFAS: st.cache_data KULLANILMAZ — boş placeholder 30 dk kilitlenmesin diye.
Her çağrıda disk kontrol edilir; arka plan tamamlanınca bir sonraki okuma veriyi getirir.
"""
from __future__ import annotations

import streamlit as st

from disk_onbellek import TTL, disk_getir, disk_getir_aninda, disk_getir_swr, disk_hepsini_sil
from investor_profile import YatirimProfili, profil_mevduat_vadesi
from macro_data import canli_snapshot, demo_snapshot
from rates_tr import mevduat_analizi
from stock_scanner import tam_tarama
from backtest import backtest_calistir


def tarama_yukleniyor(tarama) -> bool:
    """Boş placeholder mı — arka plan henüz bitmedi mi?"""
    if tarama is None:
        return True
    if getattr(tarama, "hisseler", None) or getattr(tarama, "endeksler", None):
        return False
    return any("arka planda" in (u or "").lower() for u in (getattr(tarama, "uyarilar", None) or []))


def tefas_yukleniyor(sonuc) -> bool:
    if sonuc is None:
        return True
    if getattr(sonuc, "fonlar", None):
        return False
    hata = getattr(sonuc, "hata", "") or ""
    return "arka planda" in hata.lower()


@st.cache_data(ttl=TTL["cds"], show_spinner=False)
def cds_kaynak_ozet(_tick: int = 0):
    from cds_sync import cds_guncelleme_calistir
    return cds_guncelleme_calistir(taze=_tick > 0, tick=_tick)


@st.cache_data(ttl=TTL["makro"], show_spinner=False)
def veri_cek(canli: bool, _tick: int = 0):
    if not canli:
        return demo_snapshot()
    return disk_getir_swr(
        "makro:canli",
        TTL["makro"],
        lambda: canli_snapshot(taze=_tick > 0, _tick=_tick),
    )


def tarama_cek(
    canli: bool,
    rejim: str,
    snap_veri_kaynak: str,
    _tick: int = 0,
    haber_tara: bool = False,
    profil_risk: str = "orta",
    profil_vade: str = "orta",
    *,
    zorla: bool = False,
    use_signal_v2: bool = True,
):
    """Hisse/endeks taraması — disk önbellek; zorla=True senkron çeker (Taramayı yenile)."""
    del snap_veri_kaynak
    from stock_scanner import TaramaSonucu

    anahtar = f"tarama:{canli}:{rejim}:{haber_tara}:{profil_risk}:{profil_vade}:v2={int(use_signal_v2)}:gbx_v3:live_v1"

    def _uret():
        snap = veri_cek(canli, _tick)
        profil = YatirimProfili(risk=profil_risk, vade=profil_vade)
        return tam_tarama(
            makro_rejim=rejim, demo=not canli, snap=snap, haber_tara=haber_tara,
            profil=profil, use_signal_v2=use_signal_v2,
        )

    def _placeholder():
        return TaramaSonucu(
            uyarilar=[
                "Hisse/endeks taraması arka planda yükleniyor — "
                "tablolar 30–90 sn içinde otomatik dolacak."
            ],
            makro_rejim=rejim,
        )

    if zorla:
        sonuc = disk_getir_swr(anahtar, TTL["tarama"], _uret, blokla=True)
        return sonuc if sonuc is not None else _placeholder()

    veri, yas = disk_getir(anahtar, TTL["tarama"], bayat_kabul=True)
    if veri is not None:
        if yas is not None and yas > TTL["tarama"]:
            disk_getir_aninda(anahtar, TTL["tarama"], _uret, varsayilan=veri)
        return veri

    disk_getir_aninda(anahtar, TTL["tarama"], _uret, varsayilan=None)
    return _placeholder()


@st.cache_data(ttl=TTL["mevduat"], show_spinner=False)
def mevduat_cek(enflasyon: float, profil_vade: str, eur_try: float, kalan_gun: int):
    return disk_getir_swr(
        f"mevduat:{round(enflasyon, 1)}:{profil_vade}:{kalan_gun}",
        TTL["mevduat"],
        lambda: mevduat_analizi(
            enflasyon, profil_vade=profil_vade, eur_try=eur_try, kalan_gun=kalan_gun,
        ),
    )


def backtest_veri(ay: int, vade: str, risk: str, *, zorla: bool = False):
    anahtar = f"backtest:{ay}:{vade}:{risk}"

    def _uret():
        return backtest_calistir(ay, profil=YatirimProfili(risk=risk, vade=vade))

    if zorla:
        return disk_getir_swr(anahtar, TTL["backtest"], _uret, blokla=True)

    veri, yas = disk_getir(anahtar, TTL["backtest"], bayat_kabul=True)
    if isinstance(veri, list) and veri:
        if yas is not None and yas > TTL["backtest"]:
            disk_getir_aninda(anahtar, TTL["backtest"], _uret, varsayilan=veri)
        return veri

    disk_getir_aninda(anahtar, TTL["backtest"], _uret, varsayilan=None)
    return {"hata": "Backtest arka planda yükleniyor — bir dakika sonra yenileyin."}


def backtest_hazir_mi(bt) -> bool:
    """Liste[BacktestSatir] mi — yükleme/hata dict'i False."""
    return (
        isinstance(bt, list)
        and bool(bt)
        and hasattr(bt[0], "tarih")
        and hasattr(bt[0], "agirliklar")
    )


def backtest_yukleniyor_mu(bt) -> bool:
    return isinstance(bt, dict) and bool(bt.get("hata"))



def _tefas_getiri_bozuk_mu(sonuc) -> bool:
    """Eski kısa-pencere bug'ı: çoğu fonda 1A==3A==YBB (uydurma eşitleme)."""
    fonlar = [
        f for f in (getattr(sonuc, "fonlar", None) or [])
        if getattr(f, "getiri_1a", None) is not None
        and getattr(f, "getiri_3a", None) is not None
        and getattr(f, "getiri_ybb", None) is not None
    ]
    if len(fonlar) < 8:
        return False
    ayni = sum(
        1 for f in fonlar
        if f.getiri_1a == f.getiri_3a == f.getiri_ybb
    )
    return (ayni / len(fonlar)) >= 0.80


def _tefas_pencere_yetersiz_mu(sonuc, *, esik: float = 0.8) -> bool:
    """Kesik pencere: 1A var ama YBB (ve çoğu 3A) hesaplanamıyorsa tarihçe kısa.

    90 günlük pencere YBB'yi (yılbaşından bu yana) doldurmaz → tüm fonlarda "—".
    Daha kısa (≤60g) pencerede 3A da boşalır. Bu durumda diskte daha uzun ham veri
    varsa tekrar çekmek/yükseltmek gerekir (aksi halde tablo kalıcı "—" kalır)."""
    fonlar = [
        f for f in (getattr(sonuc, "fonlar", None) or [])
        if getattr(f, "getiri_1a", None) is not None
    ]
    if len(fonlar) < 8:
        return False
    ybb_bos = sum(1 for f in fonlar if getattr(f, "getiri_ybb", None) is None)
    return (ybb_bos / len(fonlar)) >= esik


def tefas_ham_cek(gun: int = 120, _tick: int = 0, *, zorla: bool = False):
    from tefas_data import TefasTaramaSonuc, yk_fonlari_performans
    from tefas_progress import (
        progress_aktif_mi,
        progress_baslat,
        progress_bitir,
        progress_cb,
        progress_heartbeat,
    )

    # v2: kısa ham + uydurma 3A/YBB önbelleklerini devre dışı bırak
    anahtar = f"tefas:v2:{gun}"

    def _uret():
        progress_baslat(detail=f"TEFAS yükleniyor · hedef {gun} gün…", zorla=True)
        try:
            sonuc = yk_fonlari_performans(
                gun=gun, sadece_yk=True, progress_cb=progress_cb,
            )
            if getattr(sonuc, "hata", ""):
                progress_bitir(hata=str(sonuc.hata))
                return None
            n = len(getattr(sonuc, "fonlar", None) or [])
            progress_bitir(detail=f"Tablo hazır · {n} fon · {getattr(sonuc, 'gun', gun)} gün")
            return sonuc
        except Exception as e:
            progress_bitir(hata=str(e))
            raise

    def _placeholder():
        return TefasTaramaSonuc(
            hata="TEFAS arka planda yükleniyor — tablolar 30–90 sn içinde otomatik dolacak.",
            guncelleme="",
        )

    def _kardes_disk():
        """İstenen pencerede yoksa kardeş gün anahtarlarından anında göster."""
        for g in (gun, 120, 90, 60, 30):
            veri, yas = disk_getir(f"tefas:v2:{int(g)}", TTL["tefas"], bayat_kabul=True)
            if veri is None or _tefas_getiri_bozuk_mu(veri):
                continue
            if not getattr(veri, "fonlar", None):
                continue
            return veri, yas, int(g)
        return None, None, None

    if zorla:
        progress_baslat(detail="TEFAS Yenile — tam çekim…", zorla=True)
        try:
            sonuc = disk_getir_swr(anahtar, TTL["tefas"], _uret, blokla=True)
            if sonuc is not None:
                return sonuc
            progress_bitir(hata="TEFAS Yenile başarısız")
            return _placeholder()
        except Exception as e:
            progress_bitir(hata=str(e))
            return _placeholder()

    veri, yas = disk_getir(anahtar, TTL["tefas"], bayat_kabul=True)
    if veri is not None and _tefas_getiri_bozuk_mu(veri):
        from disk_onbellek import disk_sil
        disk_sil(anahtar)
        veri = None
    # Kesik pencere (3A/YBB toplu boş): diskte daha uzun ham veri olabilir — tam
    # pencereyle yeniden hesaplamayı ARKA PLANDA tetikle, eldeki kısa tabloyu ANINDA
    # göster (bloklama yok). Bir sonraki rerun'da tam veri gelir. Oturumda bir kez;
    # sonuç yine kısaysa (TEFAS gerçekten kısa tarihçe döndürdü) tekrar denemez → döngü yok.
    if veri is not None and _tefas_pencere_yetersiz_mu(veri):
        _yenile_bayrak = f"_tefas_pencere_yenile_{gun}"
        if not st.session_state.get(_yenile_bayrak):
            st.session_state[_yenile_bayrak] = True
            from disk_onbellek import disk_sil
            disk_sil(anahtar)
            return disk_getir_aninda(anahtar, TTL["tefas"], _uret, varsayilan=veri)
    if veri is not None:
        if yas is not None and yas > TTL["tefas"]:
            disk_getir_aninda(anahtar, TTL["tefas"], _uret, varsayilan=veri)
        return veri

    # Kardeş önbellek: tabloyu hemen göster, istenen pencereyi arka planda tazele
    kardes, _ky, kg = _kardes_disk()
    if kardes is not None:
        disk_getir_aninda(anahtar, TTL["tefas"], _uret, varsayilan=None)
        return kardes

    # Poll her 2 sn buraya düşer — aktif yüklemeyi sıfırlama
    if progress_aktif_mi():
        progress_heartbeat()
        return _placeholder()

    progress_baslat(detail="Disk boş — TEFAS canlı çekim başlıyor…")
    disk_getir_aninda(anahtar, TTL["tefas"], _uret, varsayilan=None)
    return _placeholder()


def veri_onbellegi_temizle() -> None:
    from cds_guven import cds_tick_onbellegi_temizle
    from macro_auto import enflasyon_cache_temizle
    from varlik_fiyat import fiyat_onbellegi_temizle
    from signal_engine.data.live_quote import clear_live_quote_cache
    from signal_engine.data.quote_normalize import fetch_source_quote_currency

    fetch_source_quote_currency.cache_clear()
    # Son kotasyonlar diskte kalsın — yenile bitene / yeni yazılana kadar 1G SWR
    clear_live_quote_cache(keep_disk=True)
    cds_tick_onbellegi_temizle()
    enflasyon_cache_temizle()
    fiyat_onbellegi_temizle()
    veri_cek.clear()
    mevduat_cek.clear()
    cds_kaynak_ozet.clear()
    disk_hepsini_sil()
    try:
        from tefas_data import _BD_CACHE as tefas_bd_cache, _CACHE as tefas_py_cache
        tefas_py_cache["ts"] = 0.0
        tefas_bd_cache["ts"] = 0.0
        tefas_bd_cache["df"] = None
    except Exception:
        pass
