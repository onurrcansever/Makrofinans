# -*- coding: utf-8 -*-
"""
2026 menkul kıymet vergi notu — bilgi katmanı (hesap motoru değil).

Tam mükellef gerçek kişi özeti. Hisse/ETF/TEFAS tutarlarına stopaj uygulanmaz;
mevduat net % zaten rates_tr / yapikredi_rates ile hesaplanır.
"""
from __future__ import annotations

from typing import Dict, List, Optional

# Sabit sözleşme metinleri — tests/test_vergi_notu.py bunlara bağlanır
BIST_OZET = (
    "BIST’te işlem gören hisse alım-satımında stopaj çoğu senaryoda %0 "
    "(Geç. 67; özet — istisna/süre için kaynak tablo)."
)
TEFAS_OZET = (
    "TEFAS / yatırım fonu stopajı iktisap tarihine ve fon türüne bağlı "
    "(%0 / %7,5 / %10 / %15…); hisse yoğun fonlarda sıklıkla %0. "
    "Banka/TEFAS ekranını esas alın — yazılım net fon getirisi hesaplamaz."
)
MEVDUAT_OZET = (
    "TL/döviz mevduatta yazılım net % gösterir (stopaj düşülmüş; "
    "TL varsayılan ~%15, döviz ~%25 — bankadan teyit edin)."
)
YABANCI_OZET = (
    "Yabancı hisse / yurt dışı ETF için TR stopaj matrisi hesaplanmaz; "
    "BIST Geç. 67 ile aynı değildir — aracı kurum ve beyan ayrı."
)
TEMETTU_OZET = (
    "Kar payında tipik stopaj + yarısı istisna; eşik aşımında beyan olabilir "
    "(tarama skoruna karışmaz)."
)
BRUT_UYARI = (
    "Hisse / ETF / TEFAS / emtia K/Z ve getiriler brüttür; vergi düşülmez. "
    "Yalnızca mevduat satırlarında net (stopaj sonrası) kullanılır."
)
UYARI_UST = (
    "Yasal tavsiye değildir. Oranlar değişebilir — GİB / mali müşavir / banka teyidi şart. "
    "Özet: Tam mükellef gerçek kişi."
)

VERGI_OZET_SATIRLARI: List[str] = [
    BIST_OZET,
    TEFAS_OZET,
    MEVDUAT_OZET,
    YABANCI_OZET,
    TEMETTU_OZET,
]

_CAPTION: Dict[str, str] = {
    "bist": BIST_OZET,
    "tefas": TEFAS_OZET,
    "mevduat": MEVDUAT_OZET,
    "yabanci": YABANCI_OZET,
    "etf": YABANCI_OZET,
    "temettu": TEMETTU_OZET,
    "genel": BRUT_UYARI,
}


def vergi_notu_markdown(*, kisa: bool = False) -> str:
    """Streamlit expander / HTML için markdown özet."""
    satirlar = VERGI_OZET_SATIRLARI[:3] if kisa else VERGI_OZET_SATIRLARI
    maddeler = "\n".join(f"- {s}" for s in satirlar)
    ekstra = "" if kisa else f"\n\n*{BRUT_UYARI}*"
    return f"**{UYARI_UST}**\n\n{maddeler}{ekstra}"


def vergi_notu_caption(varlik_sinifi: Optional[str] = None) -> str:
    """Tek satır caption — sınıf anahtarı: bist, tefas, mevduat, yabanci, etf, genel.

    UI’da genelde yalnızca bu satır + kapalı expander kullanılır.
    """
    key = (varlik_sinifi or "genel").strip().lower()
    # Kısa UI satırı; testler anahtar kelimeleri doğrular
    kisa_ui = {
        "bist": "BIST hisse alım-satımında stopaj çoğu senaryoda %0 (özet).",
        "tefas": "TEFAS stopajı iktisap tarihine/fon türüne bağlı; getiriler brüttür.",
        "mevduat": "Mevduatta net % gösterilir (stopaj düşülmüş).",
        "yabanci": "Yabancı hisse/ETF için TR stopaj matrisi hesaplanmaz.",
        "etf": "Yabancı hisse/ETF için TR stopaj matrisi hesaplanmaz.",
        "temettu": "Kar payında tipik stopaj + istisna; beyan eşiği olabilir.",
        "genel": "Hisse/ETF/TEFAS getiriler brüttür; vergi düşülmez.",
    }
    govde = kisa_ui.get(key, _CAPTION.get(key, BRUT_UYARI))
    return f"Vergi notu: {govde}"


def vergi_notu_rapor_satirlari(*, max_satir: int = 5) -> List[str]:
    """PDF/HTML dipnot — düz metin satırları."""
    out = [UYARI_UST] + VERGI_OZET_SATIRLARI[: max(1, max_satir - 1)]
    if max_satir >= 6:
        out.append(BRUT_UYARI)
    return out[:max_satir]


def vergi_notu_html_blok(*, esc=None) -> str:
    """investment_report için küçük HTML kutusu."""
    if esc is None:
        esc = lambda x: (
            str(x)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
    li = "".join(f"<li>{esc(s)}</li>" for s in VERGI_OZET_SATIRLARI)
    return (
        "<div class='box'>"
        f"<strong>2026 menkul kıymet vergi notu (özet)</strong>"
        f"<p class='muted'>{esc(UYARI_UST)}</p>"
        f"<ul>{li}</ul>"
        f"<p class='muted'>{esc(BRUT_UYARI)}</p>"
        "</div>"
    )
