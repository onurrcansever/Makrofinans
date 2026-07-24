# -*- coding: utf-8 -*-
"""
Karar sözlükleri — v1 / v2 / TEFAS ayrımı korunur (zorla birleştirilmez).

v2 (Signal Engine): GÜÇLÜ AL / AL / İZLE / BEKLE / AZALT
v1 (eski bileşik): AL / DİKKAT / BEKLE / ALMA
TEFAS: AL / İZLE / BEKLE / Zayıf; AL* = küçük akran grubu işareti

UI birincil sütun adı: «Şimdi ne yap?» (değerler aynı sözlük).
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable, List

# Signal Engine v2 — tek kaynak (tablo aksiyon + lejant)
V2_KARAR_SIRASI = ("GÜÇLÜ AL", "AL", "İZLE", "BEKLE", "AZALT")

# UI birincil aksiyon sütunu (eski ad: Karar)
HISSE_AKSIYON_SUTUN = "Şimdi ne yap?"
HISSE_MOMENTUM_SUTUN = "Momentum"
HISSE_ALIM_SEVIYE_SUTUN = "Alım seviyesi"
HISSE_TEMEL_SUTUN = "Temel"

# Temel skor etiketleri (teknik aksiyondan bağımsız)
FUND_LABEL_ACIKLAMA = {
    "GÜÇLÜ": "Temel kalite yüksek (80–100)",
    "SAĞLAM": "Temel kalite iyi (64–79)",
    "NÖTR": "Temel nötr (52–63)",
    "ZAYIF": "Temel zayıf (42–51)",
    "RİSKLİ": "Temel riskli (0–41)",
    "YETERSİZ": "Temel skor için veri yetersiz",
}

V2_KARAR_ACIKLAMA = {
    "GÜÇLÜ AL": "Yeni alım öncelikli değerlendirilebilir — Alım seviyesi’ne bak",
    "AL": "Yeni alım değerlendirilebilir — Alım seviyesi’ne bak",
    "İZLE": "Yeni alım yok; izle / tut (Momentum ▲ olsa bile)",
    "BEKLE": "Ekleme yok; zayıflama — pozisyonu gözden geçir",
    "AZALT": "Ekleme yok; çıkış / azaltma değerlendir",
}

# Eski motor (v2 kapalıyken)
V1_KARAR_ACIKLAMA = {
    "AL": "Teknik + hikâye uygun — alım değerlendirilebilir",
    "DİKKAT": "Bazı uyarılar var — sınırlı pay",
    "BEKLE": "Net alım uygunluğu yok — bekle",
    "ALMA": "Koşullar olumsuz — alım önerilmez",
}

# TEFAS * işareti (Öneri sütunu) — mutlak skor; göreli yüzdelik yok
TEFAS_YILDIZ_ACIKLAMA = (
    "* (öneri yanında) = küçük kategori (n<8) — skor mutlak; göreli sıralama yok, güven zayıf. "
    "AL* = profil uyumu eşiği (≥64) geçildi ama akran az. "
    "İZLE*/BEKLE*/Zayıf* aynı kural. "
    "Fiyat sütunundaki † = gösterim PB belirsiz (ayrı işaret)."
)

TEFAS_STRES_CAPTION = (
    "Makro **KRIZ / EM_STRES** → yeni risk AL yok "
    "(hisse/değişken/fon sepeti; para piyasası/borçlanma istisna). "
    "Hisse + endeks Artır + TEFAS aynı stres kuralı."
)


def v2_lejant_satirlari() -> List[str]:
    return [f"**{k}** = {v}" for k, v in V2_KARAR_ACIKLAMA.items()]


def v2_lejant_markdown() -> str:
    lines = [
        f"**Signal Engine v2 — {HISSE_AKSIYON_SUTUN} sözlüğü**",
        "",
    ]
    lines.extend(f"- {s}" for s in v2_lejant_satirlari())
    lines.append("")
    lines.append(
        "Not: **BEKLE** ≠ İZLE. İZLE nötr izleme; BEKLE zayıflama "
        "(AZALT’ın bir üstü)."
    )
    lines.append(
        f"**{HISSE_MOMENTUM_SUTUN}** (▲/—/▼) skor/analist rozetidir — "
        f"**{HISSE_AKSIYON_SUTUN} değildir.**"
    )
    lines.append(
        "**Temel kapı:** negatif FCF+zarar, aşırı kaldıraç, analist sat, "
        "sektör F/K pahalı (soft) veya ≥2 soft bayrak → AL/GÜÇLÜ AL **İZLE**’ye çekilir."
    )
    lines.append(
        f"**{HISSE_TEMEL_SUTUN} skor** (ikinci eksen): GÜÇLÜ/SAĞLAM/NÖTR/ZAYIF/RİSKLİ — "
        "teknik skordan bağımsız. **AZALT ≠ temel satım.**"
    )
    lines.append(
        f"**{HISSE_AKSIYON_SUTUN} (birleşik):** teknik + temel + pahalı + giriş + Ichimoku. "
        "**AL · küçük** nadirdir (skor≈AL + spot **ve** Ichimoku + Trend↑ + temel sağlam). "
        "Sadece SAĞLAM + spot → **İZLE** kalır (eşiğe yakın notu). Yatırım tavsiyesi değildir."
    )
    lines.append(TEFAS_STRES_CAPTION)
    return "\n".join(lines)


def v1_lejant_markdown() -> str:
    lines = [f"**Eski bileşik skor — {HISSE_AKSIYON_SUTUN} sözlüğü**", ""]
    for k, v in V1_KARAR_ACIKLAMA.items():
        lines.append(f"- **{k}** = {v}")
    return "\n".join(lines)


def tefas_lejant_kisa() -> str:
    return (
        "TEFAS öneri = **profil uyumu** (brüt getiri; stopaj/ücret skora girmez; emir değil) · "
        "AL ≥68 / İZLE ≥52 · * = küçük kategori · hisse AL ile aynı şey değil"
    )


def tefas_lejant_caption() -> str:
    return tefas_lejant_kisa()


def tefas_lejant_detay() -> str:
    return (
        "TEFAS **AL** = profil + rejim uyum skoru (≥64), brüt getiri; "
        "stopaj ve yönetim ücreti skora **girmez** — emir / hisse «Şimdi ne yap?» değildir. "
        + TEFAS_YILDIZ_ACIKLAMA
        + " "
        + TEFAS_STRES_CAPTION
    )


def endeks_lejant_kisa() -> str:
    return (
        "Endeks **Artır/Koru/Bekle/Azalt** = pozisyon ağırlığı · "
        "Koru ≈ İZLE değildir · hisse «Şimdi ne yap?»tan ayrı"
    )


def endeks_lejant_caption() -> str:
    return endeks_lejant_kisa()


def endeks_lejant_detay() -> str:
    return (
        "Endeks önerisi (**Artır / Koru / Bekle / Azalt**) pozisyon ağırlığıdır; "
        f"hisse **{HISSE_AKSIYON_SUTUN}** (AL / İZLE / BEKLE / AZALT) motor aksiyonudur — "
        "**Koru ≈ İZLE değildir.**"
    )


def hisse_lejant_caption() -> str:
    """Tablo üstü — tek kısa satır (detay expander’da)."""
    base = (
        f"**Okuma:** makro → endeks → **{HISSE_AKSIYON_SUTUN}** → Alım seviyesi · "
        f"**{HISSE_AKSIYON_SUTUN}** = al/ekle · "
        f"**{HISSE_MOMENTUM_SUTUN}** = skor rozeti "
        f"(aksiyon değildir) · KRIZ/EM_STRES → yeni risk AL yok"
    )
    try:
        from signal_engine.quality.fund_score_ui import fund_score_ui_enabled

        if fund_score_ui_enabled():
            base += f" · **{HISSE_TEMEL_SUTUN}** = bağımsız temel skor (deneysel)"
    except Exception:
        pass
    return base


def hisse_playbook_caption() -> str:
    """Kısa kullanım: ne zaman alırım."""
    return (
        "**Okuma sırası:** makro → endeks ağırlık → «Şimdi ne yap?» → Alım seviyesi/Ichimoku. "
        "**AL / GÜÇLÜ AL** → Alım seviyesi yakın + Ichimoku açıkken kademeli değerlendir "
        "(tek rozet = emir değil). "
        "**İZLE** → yeni alım yok. **BEKLE / AZALT** → ekleme yok. "
        "Evren likit/Revolut odaklı kişisel liste — piyasa-geniş tarama değil. "
        "KRIZ/EM_STRES → yeni risk AL yok."
    )


def hisse_al_bildirim_caption() -> str:
    return "AL / GÜÇLÜ AL listesine bakın; eşiğe yakın = takip, şimdi alma."


def hisse_sozluk_expander_markdown() -> str:
    """Kapalı expander — tam sözlük + playbook."""
    return "\n\n".join([
        (
            f"**{HISSE_AKSIYON_SUTUN}** = motor aksiyonu (yalnızca buna göre al/ekle) · "
            f"**{HISSE_ALIM_SEVIYE_SUTUN}** = emir fiyat bandı · "
            f"**{HISSE_MOMENTUM_SUTUN}** = skor/analist rozeti "
            f"(**{HISSE_AKSIYON_SUTUN} değildir**) · "
            "**Özet** = T teknik / A analist / H haber (AL kararını değiştirmez)."
        ),
        (
            "**AL / GÜÇLÜ AL** → Alım seviyesi’ne bak (yoksa spot civarı, küçük dilim). "
            "**İZLE** → yeni alım yok. **BEKLE / AZALT** → ekleme yok. "
            "Makro KRIZ/EM_STRES → AL listede görünmez. "
            "Eşiğe yakın = takip; şimdi alma."
        ),
        v2_lejant_markdown(),
    ])


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
    return " · ".join(parts) if parts else "Aksiyon dağılımı yok"


def kararlar_from_df_column(series) -> List[str]:
    try:
        return [str(x) for x in series.tolist()]
    except Exception:
        return list(series or [])
