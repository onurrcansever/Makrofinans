# -*- coding: utf-8 -*-
"""TEFAS öneri açıklaması — Neden? paneli (öğretmen dili)."""
from __future__ import annotations

from tefas_data import FonPerformans
from tefas_universe import KATEGORILER


def tefas_neden_metni(f: FonPerformans) -> str:
    pb = f.skor_pb or "EUR"
    kat = KATEGORILER.get(f.kategori, f.kategori) or "—"
    lines = [
        f"**{f.kod}** — öneri **{f.oneri}** · uyum skoru **{f.skor:.0f}** "
        f"(ham {f.skor_ham:.0f}).",
        "Bu skor **profil + rejim uyumu**dur (brüt getiri). "
        "Hisse «Şimdi ne yap? = AL» ile aynı şey değildir; emir değildir.",
        f"Kategori: **{kat}**. Skor/getiri sütunları **{pb}** bazında "
        f"(fon para birimi → {pb}).",
    ]

    # Hangi vade getirisi skoru sürdü
    fac = f.skor_faktorler or {}
    getiri_keys = [k for k in fac if str(k).startswith("getiri_")]
    if getiri_keys:
        gk = getiri_keys[0]
        lines.append(
            f"**Getiri katkısı:** `{gk}` = {fac[gk]:+.0f} "
            "(vade profiline göre 1A / 3A / YBB karışımı)."
        )
    elif fac:
        parca = ", ".join(f"{k}={v:+.0f}" for k, v in fac.items())
        lines.append(f"**Faktör özeti:** {parca}")

    g1 = f.getiri_gosterim_1a
    g3 = f.getiri_gosterim_3a
    gy = f.getiri_gosterim_ybb
    if any(x is not None for x in (g1, g3, gy)):
        def _fmt(x):
            return f"{x:+.2f}%" if x is not None else "—"
        lines.append(
            f"**Görünen getiri ({pb}):** "
            f"1A={_fmt(g1)} · 3A={_fmt(g3)} · YBB={_fmt(gy)}"
        )

    # YBB guard
    note = (f.skor_notu or "").lower()
    if "felaket" in note:
        lines.append(
            "**YBB guard:** yıllık getiri felaket eşiğinde — AL/İZLE kapalı "
            "(kısa vade 1A pozitif olsa bile)."
        )
    elif "ybb" in note and "zayıf" in note:
        lines.append("**YBB:** zayıf aralıkta skor cezası uygulanmış.")

    lines.append(
        "**Stopaj / ücret:** skora **girmez** (yalnızca tabloda bilgi). "
        "Net getiri için Stopaj ve Yön.%/TGO sütunlarına bak."
    )

    if f.akran_kucuk:
        lines.append(
            f"⚠ **Küçük kategori** (n<8) — skor **mutlak**; göreli yüzdelik sıralama yok. "
            f"Güven zayıf. Kategori: {kat}."
        )

    if f.skor_notu:
        lines.append(f"**Motor notu:** {f.skor_notu}")

    lines.append(
        "**Nasıl oku:** uyum skoru yüksek = «profiline/rejime daha uygun aday»; "
        "hemen al demek değil. Makro KRIZ/EM_STRES’te risk kategorilerinde AL kapalıdır."
    )
    return "\n\n".join(lines)
