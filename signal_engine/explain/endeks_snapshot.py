# -*- coding: utf-8 -*-
"""Endeks tablosu özeti — EndeksAI prompt (skora girmez)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence


LEJANT = (
    "Endeks Öneri (Artır/Koru/Bekle/Azalt) = platform pozisyon ağırlığıdır; "
    "hisse «Şimdi ne yap?» (AL/İZLE) aksiyonundan ayrıdır. "
    "Koru ≈ İZLE değildir. Endeks Azalt/Bekle, o pazardaki hisse AL’yi otomatik iptal etmez — "
    "seçici/küçük pay ve platform temkini anlamına gelir."
)

OKUMA_SIRASI = (
    "Okuma sırası: (1) makro/rejim → (2) Endeks Öneri + Bugün bakılacak yer → "
    "(3) Hisse/ETF «Şimdi ne yap?» → (4) Neden?/seviye."
)


@dataclass
class EndeksSatirSnap:
    ad: str = ""
    sembol: str = ""
    oneri: str = ""
    guven: int = 0
    kurulum: str = ""
    neden: str = ""
    platform: str = ""
    yerel_1a: Optional[float] = None
    yerel_3a: Optional[float] = None
    gosterim_1a: Optional[float] = None
    gosterim_3a: Optional[float] = None
    teknik: str = ""
    makro: str = ""


@dataclass
class EndeksSnapshot:
    oncelik: str = ""
    gosterim_pb: str = "EUR"
    satirlar: List[EndeksSatirSnap] = field(default_factory=list)
    lejant: str = LEJANT
    okuma_sirasi: str = OKUMA_SIRASI
    makro_rejim: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "oncelik": self.oncelik,
            "gosterim_pb": self.gosterim_pb,
            "lejant": self.lejant,
            "okuma_sirasi": self.okuma_sirasi,
            "makro_rejim": self.makro_rejim,
            "satirlar": [asdict(s) for s in self.satirlar],
        }

    def cache_fingerprint(self) -> str:
        raw = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def prompt_block(self) -> str:
        lines = [
            "ENDEKS TABLOSU (yazılım motoru — uydurma yok):",
            f"- Gösterim PB (tablo %): {self.gosterim_pb}",
            f"- Makro rejim: {self.makro_rejim or '—'}",
            f"- Öncelik bandı: {self.oncelik or '—'}",
            f"- Lejant: {self.lejant}",
            f"- {self.okuma_sirasi}",
            "",
            "Satırlar:",
        ]
        for s in self.satirlar:
            y1 = f"{s.yerel_1a:+.1f}%" if s.yerel_1a is not None else "—"
            y3 = f"{s.yerel_3a:+.1f}%" if s.yerel_3a is not None else "—"
            g1 = f"{s.gosterim_1a:+.1f}%" if s.gosterim_1a is not None else "—"
            g3 = f"{s.gosterim_3a:+.1f}%" if s.gosterim_3a is not None else "—"
            lines.append(
                f"- {s.ad} ({s.sembol}) · platform={s.platform or '—'} · "
                f"Öneri={s.oneri or '—'} · Güven={s.guven} · Kurulum={s.kurulum or '—'} · "
                f"yerel 1A/3A={y1}/{y3} · {self.gosterim_pb} 1A/3A={g1}/{g3} · "
                f"Teknik={s.teknik or '—'} · Makro={s.makro or '—'} · "
                f"Neden={s.neden or '—'}"
            )
        lines.append(
            "\nNot: Öneri yerel para momentum + RSI/SMA + makro kapısından gelir; "
            f"tablodaki %{self.gosterim_pb} sütunları gösterimdir — karar ile birebir aynı dil olmayabilir."
        )
        return "\n".join(lines)


def _fmt_opt(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def build_endeks_snapshot(
    endeksler: Sequence[Any],
    *,
    oncelik: str = "",
    gosterim_pb: str = "EUR",
    makro_rejim: str = "",
    gosterim_getiriler: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
    nedenler: Optional[Dict[str, str]] = None,
) -> EndeksSnapshot:
    """
    gosterim_getiriler: sembol -> {"1a": float|None, "3a": float|None}
    nedenler: sembol -> neden metni
    """
    gmap = gosterim_getiriler or {}
    nmap = nedenler or {}
    satirlar: List[EndeksSatirSnap] = []
    for e in endeksler or []:
        sym = str(getattr(e, "sembol", "") or "")
        g = gmap.get(sym) or {}
        neden = nmap.get(sym)
        if not neden:
            neden = str(getattr(e, "gerekce", "") or getattr(e, "aksiyon_neden", "") or "")
        satirlar.append(
            EndeksSatirSnap(
                ad=str(getattr(e, "ad", "") or sym),
                sembol=sym,
                oneri=str(getattr(e, "aksiyon_etiket", None) or "Bekle"),
                guven=int(getattr(e, "guven", 0) or 0),
                kurulum=str(getattr(e, "kurulum", "") or ""),
                neden=neden[:220],
                platform=str(getattr(e, "platform", "") or ""),
                yerel_1a=_fmt_opt(getattr(e, "degisim_1ay", None)),
                yerel_3a=_fmt_opt(getattr(e, "degisim_3ay", None)),
                gosterim_1a=_fmt_opt(g.get("1a")),
                gosterim_3a=_fmt_opt(g.get("3a")),
                teknik=str(getattr(e, "teknik_aksiyon_etiket", "") or ""),
                makro=str(getattr(e, "makro_chip", "") or ""),
            )
        )
    return EndeksSnapshot(
        oncelik=(oncelik or "").strip(),
        gosterim_pb=(gosterim_pb or "EUR").strip().upper(),
        satirlar=satirlar,
        makro_rejim=(makro_rejim or "").strip(),
    )
