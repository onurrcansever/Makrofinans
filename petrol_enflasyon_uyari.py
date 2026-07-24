# -*- coding: utf-8 -*-
"""
Petrol → Enflasyon Riski — DANIŞMAN UYARISI (advisory-only)
===========================================================
Brent'in son 3 aylık yükselişinden ithal-enflasyon riski notu üretir.

ÖNEMLİ: Bu YALNIZCA bilgi/uyarı katmanıdır — rejim, tahsis, TL tavanı veya reel
getiri hesabını DEĞİŞTİRMEZ. Karar motoruna bağlanmadı çünkü
`macro_anchor_validation` kalibrasyonu (n=21, dezenflasyon dönemi confound,
MoM R²≈0.01) petrol→enflasyon öncü ilişkisinin sayısal kapıya bağlanacak kadar
sağlam OLMADIĞINI gösterdi. Eş-zamanlı ilişki güçlü (YoY R²≈0.62) olduğundan
mentor-tarzı bir "dikkat" notu vermek anlamlı; ama sayısal etkisi yok.

Bantlar (3 aylık Brent %) tanımlayıcı/danışman amaçlıdır, karar eşiği değildir.
"""
from __future__ import annotations

from typing import Optional, Dict

# Danışman bantları — 3 aylık Brent değişimi (%). Karar eşiği DEĞİL.
_IZLE_ESIK = 8.0
_YUKSEK_ESIK = 15.0


def petrol_enflasyon_uyarisi(brent_3a_degisim: Optional[float]) -> Optional[Dict[str, str]]:
    """Brent 3 aylık % değişimden enflasyon-riski danışman notu.

    Dönüş: {'seviye': 'izle'|'yüksek', 'mesaj': ...} veya None (uyarı yok).
    Karar motorunu etkilemez; yalnızca UI/AI bağlamında gösterilir.
    """
    if brent_3a_degisim is None:
        return None
    try:
        d = float(brent_3a_degisim)
    except (TypeError, ValueError):
        return None
    if d >= _YUKSEK_ESIK:
        return {
            "seviye": "yüksek",
            "mesaj": (
                f"Brent son 3 ayda %{d:+.0f} — belirgin yükseliş. İthal enflasyon "
                "baskısı artabilir; TÜİK açıklayana dek reel getiri görünenden düşük "
                "olabilir. (Bilgi amaçlı — karar motoruna dahil değil.)"
            ),
        }
    if d >= _IZLE_ESIK:
        return {
            "seviye": "izle",
            "mesaj": (
                f"Brent son 3 ayda %{d:+.0f} arttı — enflasyon riskini izleyin. "
                "(Bilgi amaçlı — karar motoruna dahil değil.)"
            ),
        }
    return None
