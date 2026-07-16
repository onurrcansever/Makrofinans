# -*- coding: utf-8 -*-
"""TEFAS öneri açıklaması — Neden? paneli."""
from __future__ import annotations

from tefas_data import FonPerformans
from tefas_universe import KATEGORILER


def tefas_neden_metni(f: FonPerformans) -> str:
    pb = f.skor_pb or "EUR"
    lines = [
        f"**{f.kod}** — {f.oneri} · skor **{f.skor:.0f}** (ham {f.skor_ham:.0f})",
        f"Skor ve getiri sütunları **{pb}** bazında "
        f"(fon para birimi → {pb} kur ayarı; hisse/ETF ile aynı desen).",
    ]
    if f.akran_kucuk:
        kat = KATEGORILER.get(f.kategori, f.kategori)
        lines.append(
            f"⚠ **Küçük akran grubu** — kategoride yeterli fon yok; "
            f"mutlak skor kullanıldı (yüzdelik sıralama yok). Kategori: {kat}."
        )
    fac = f.skor_faktorler or {}
    if fac:
        parca = ", ".join(f"{k}={v:+.0f}" for k, v in fac.items())
        lines.append(f"**Faktörler:** {parca}")
    g1 = f.getiri_gosterim_1a
    g3 = f.getiri_gosterim_3a
    gy = f.getiri_gosterim_ybb
    if any(x is not None for x in (g1, g3, gy)):
        lines.append(
            f"**Görünen getiri ({pb}):** "
            f"1A={g1:+.2f}% · 3A={g3:+.2f}% · YBB={gy:+.2f}%"
            if g1 is not None and g3 is not None and gy is not None
            else f"**Görünen getiri ({pb}):** 1A={g1} · 3A={g3} · YBB={gy}"
        )
    if f.skor_notu:
        lines.append(f"**Not:** {f.skor_notu}")
    return "\n\n".join(lines)
