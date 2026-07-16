# -*- coding: utf-8 -*-
"""
Karar sözlükleri — v1 / v2 / TEFAS ayrımı korunur (zorla birleştirilmez).

v2 (Signal Engine): GÜÇLÜ AL / AL / İZLE / BEKLE / AZALT
v1 (eski bileşik): AL / DİKKAT / BEKLE / ALMA
TEFAS: AL / İZLE / BEKLE / Zayıf; AL* = küçük akran grubu işareti
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable, List

# Signal Engine v2 — tek kaynak (tablo Karar + lejant)
V2_KARAR_SIRASI = ("GÜÇLÜ AL", "AL", "İZLE", "BEKLE", "AZALT")

V2_KARAR_ACIKLAMA = {
    "GÜÇLÜ AL": "Tüm faktörler pozitif, güçlü giriş sinyali",
    "AL": "Momentum ve trend uyumlu, giriş değerlendirilebilir",
    "İZLE": "Nötr bölge, net sinyal yok",
    "BEKLE": "Zayıflama sinyali, pozisyon azaltılabilir",
    "AZALT": "Trend ve momentum olumsuz, çıkış değerlendirilebilir",
}

# Eski motor (v2 kapalıyken)
V1_KARAR_ACIKLAMA = {
    "AL": "Teknik + hikâye uygun — alım değerlendirilebilir",
    "DİKKAT": "Bazı uyarılar var — sınırlı pay",
    "BEKLE": "Net alım uygunluğu yok — bekle",
    "ALMA": "Koşullar olumsuz — alım önerilmez",
}

# TEFAS * işareti (Öneri sütunu) — tüm öneri kodları için aynı anlam
TEFAS_YILDIZ_ACIKLAMA = (
    "* = küçük akran grubu (aynı kategoride 8’den az fon) — göreli skor zayıf güvenilir. "
    "AL* = AL önerisi; akran grubu küçük. "
    "BEKLE* = BEKLE önerisi var ama akran grubu küçük. "
    "İZLE*/Zayıf* aynı kural."
)


def v2_lejant_satirlari() -> List[str]:
    return [f"**{k}** = {v}" for k, v in V2_KARAR_ACIKLAMA.items()]


def v2_lejant_markdown() -> str:
    lines = ["**Signal Engine v2 — Karar sözlüğü**", ""]
    lines.extend(f"- {s}" for s in v2_lejant_satirlari())
    lines.append("")
    lines.append(
        "Not: **BEKLE** ≠ İZLE. İZLE nötr izleme; BEKLE zayıflama "
        "(AZALT’ın bir üstü)."
    )
    return "\n".join(lines)


def v1_lejant_markdown() -> str:
    lines = ["**Eski bileşik skor — Karar sözlüğü**", ""]
    for k, v in V1_KARAR_ACIKLAMA.items():
        lines.append(f"- **{k}** = {v}")
    return "\n".join(lines)


def tefas_lejant_caption() -> str:
    return (
        "Öneri: AL / İZLE / BEKLE / Zayıf · "
        + TEFAS_YILDIZ_ACIKLAMA
    )


def _normalize_karar(k: str) -> str:
    s = (k or "").strip()
    if not s or s == "—":
        return ""
    # GÜÇLÜ AL tam eşleşme
    u = s.upper().replace("I", "İ") if "GÜÇLÜ" in s.upper() or "GUCLU" in s.upper() else s
    for label in V2_KARAR_SIRASI:
        if s == label or s.upper() == label.upper():
            return label
    # ASCII fallbacks
    m = {
        "GUCLU AL": "GÜÇLÜ AL",
        "GÜCLÜ AL": "GÜÇLÜ AL",
        "IZLE": "İZLE",
        "STRONG_BUY": "GÜÇLÜ AL",
        "BUY": "AL",
        "WATCH": "İZLE",
        "WAIT": "BEKLE",
        "REDUCE": "AZALT",
    }
    return m.get(s.upper(), s)


def karar_dagilim_say(kararlar: Iterable[str]) -> dict:
    c: Counter = Counter()
    for k in kararlar:
        n = _normalize_karar(str(k))
        if n in V2_KARAR_SIRASI:
            c[n] += 1
    return {lab: int(c.get(lab, 0)) for lab in V2_KARAR_SIRASI}


def karar_dagilim_ozeti(
    kararlar: Iterable[str],
    *,
    sadece_pozitif: bool = True,
) -> str:
    """Örn: 'AL: 1 · İZLE: 83 · BEKLE: 11 · AZALT: 9' (sıfırlar gizlenir)."""
    counts = karar_dagilim_say(kararlar)
    parts = []
    for lab in V2_KARAR_SIRASI:
        n = counts[lab]
        if sadece_pozitif and n <= 0:
            continue
        parts.append(f"{lab}: {n}")
    return " · ".join(parts) if parts else "Karar dağılımı yok"


def kararlar_from_df_column(series) -> List[str]:
    try:
        return [str(x) for x in series.tolist()]
    except Exception:
        return list(series or [])
