# -*- coding: utf-8 -*-
"""
Kalıcı disk önbelleği — oturumlar/yeniden başlatmalar arası veri saklama.

Amaç: Bölümler arası geçişte ve uygulama yeniden açıldığında ağır API
çekimlerini (hisse taraması, TEFAS, Yahoo fiyat serileri, mevduat)
tekrarlamamak. Veri TTL süresi içindeyse anında diskten döner.

Kullanım:
    veri, yas = disk_getir("tarama:orta_kisa", ttl_sn=1800)
    if veri is None:
        veri = pahali_hesap()
        disk_yaz("tarama:orta_kisa", veri)
"""
from __future__ import annotations

import hashlib
import os
import pickle
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

ONBELLEK_DIZIN = Path(os.getenv("MAKROFINANS_CACHE_DIR", Path(__file__).resolve().parent / ".onbellek"))

# Veri tipi başına önerilen TTL (saniye) — tek yerden yönetilir.
TTL = {
    "makro": 15 * 60,        # makro snapshot: 15 dk
    "tarama": 15 * 60,       # hisse/ETF taraması: 15 dk
    "tefas": 6 * 3600,       # TEFAS fon verisi: 6 saat (günde ~2 kez yeter)
    "mevduat": 6 * 3600,     # banka faizleri: 6 saat
    "backtest": 24 * 3600,   # geçmiş veri: 24 saat
    "fiyat_seri": 15 * 60,   # Yahoo fiyat serileri: 15 dk
    "cds": 30 * 60,          # CDS kaynakları: 30 dk
}


def _dosya(anahtar: str) -> Path:
    h = hashlib.sha1(anahtar.encode("utf-8")).hexdigest()[:24]
    return ONBELLEK_DIZIN / f"{h}.pkl"


def disk_getir(
    anahtar: str,
    ttl_sn: float,
    *,
    bayat_kabul: bool = False,
) -> Tuple[Optional[Any], Optional[float]]:
    """(veri, yaş_saniye) döner. TTL aşıldıysa (None, None) — bayat_kabul=True ise
    süresi geçmiş veri de döner (arka planda yenileme senaryosu için)."""
    yol = _dosya(anahtar)
    if not yol.exists():
        return None, None
    try:
        yas = time.time() - yol.stat().st_mtime
        if yas > ttl_sn and not bayat_kabul:
            return None, None
        with open(yol, "rb") as f:
            return pickle.load(f), yas
    except Exception:
        try:
            yol.unlink(missing_ok=True)
        except OSError:
            pass
        return None, None


def disk_yaz(anahtar: str, veri: Any) -> None:
    try:
        ONBELLEK_DIZIN.mkdir(parents=True, exist_ok=True)
        tmp = _dosya(anahtar).with_suffix(".tmp")
        with open(tmp, "wb") as f:
            pickle.dump(veri, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(_dosya(anahtar))
    except Exception:
        pass  # disk yazılamazsa sessizce geç — önbellek zorunlu değil


# Arka planda tazeleme — aynı anahtar için tek iş parçacığı
_yenileme_kilidi = threading.Lock()
_yenilenenler: set = set()


def _arka_planda_yenile(anahtar: str, uret_fn: Callable[[], Any]) -> None:
    def _calis():
        try:
            veri = uret_fn()
            if veri is not None:
                disk_yaz(anahtar, veri)
        except Exception:
            pass
        finally:
            with _yenileme_kilidi:
                _yenilenenler.discard(anahtar)

    with _yenileme_kilidi:
        if anahtar in _yenilenenler:
            return
        _yenilenenler.add(anahtar)
    threading.Thread(target=_calis, daemon=True, name=f"onbellek-yenile:{anahtar[:30]}").start()


def disk_getir_aninda(
    anahtar: str,
    ttl_sn: float,
    uret_fn: Callable[[], Any],
    *,
    varsayilan: Any = None,
) -> Any:
    """UI için: asla ağ bekletmez. Önbellek varsa döner, yoksa varsayılan + arka planda tazele."""
    veri, yas = disk_getir(anahtar, ttl_sn, bayat_kabul=True)
    if veri is not None:
        if yas is None or yas > ttl_sn:
            _arka_planda_yenile(anahtar, uret_fn)
        return veri
    _arka_planda_yenile(anahtar, uret_fn)
    return varsayilan


def disk_getir_swr(
    anahtar: str,
    ttl_sn: float,
    uret_fn: Callable[[], Any],
    *,
    max_bayat_sn: float = 48 * 3600,
    blokla: bool = True,
) -> Any:
    """Bayat-göster + arka planda tazele (stale-while-revalidate).

    - Veri taze (yaş ≤ TTL): anında döner.
    - Veri bayat ama max_bayat_sn içinde: ESKİSİ ANINDA döner, arka planda
      taze veri çekilip diske yazılır — kullanıcı asla dakikalarca beklemez.
    - Hiç veri yoksa: blokla=True ise senkron çekilir; blokla=False ise
      varsayılan döner ve arka planda tazelenir (CLI/alarm için blokla=True).
    """
    if not blokla:
        return disk_getir_aninda(anahtar, ttl_sn, uret_fn, varsayilan=None)
    veri, yas = disk_getir(anahtar, ttl_sn, bayat_kabul=True)
    if veri is not None and yas is not None:
        if yas <= ttl_sn:
            return veri
        if yas <= max_bayat_sn:
            _arka_planda_yenile(anahtar, uret_fn)
            return veri
    taze = uret_fn()
    if taze is not None:
        disk_yaz(anahtar, taze)
    return taze


def disk_sil(anahtar: str) -> None:
    try:
        _dosya(anahtar).unlink(missing_ok=True)
    except OSError:
        pass


def disk_temizle(eski_gun: float = 7.0) -> int:
    """7 günden eski önbellek dosyalarını sil; silinen sayısını döner."""
    if not ONBELLEK_DIZIN.exists():
        return 0
    esik = time.time() - eski_gun * 86400
    n = 0
    for p in ONBELLEK_DIZIN.glob("*.pkl"):
        try:
            if p.stat().st_mtime < esik:
                p.unlink()
                n += 1
        except OSError:
            continue
    return n


def disk_hepsini_sil() -> None:
    """Manuel 'Şimdi yenile' — tüm disk önbelleğini boşalt."""
    if not ONBELLEK_DIZIN.exists():
        return
    for p in ONBELLEK_DIZIN.glob("*.pkl"):
        try:
            p.unlink()
        except OSError:
            continue
