# -*- coding: utf-8 -*-
"""Günlük teknik özet + giriş/Ichimoku — skor motoruna girmez."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

if TYPE_CHECKING:
    from stock_scanner import HisseAnaliz


@dataclass
class TechSnapshot:
    fiyat: Optional[float] = None
    rsi: Optional[float] = None
    rsi_okuma: str = "veri yok"
    sma20: Optional[float] = None
    sma20_okuma: str = "veri yok"
    sma50: Optional[float] = None
    sma50_okuma: str = "veri yok"
    sma200: Optional[float] = None
    sma200_okuma: str = "veri yok"
    kisa_okuma: str = ""
    uzun_okuma: str = ""
    ozet: str = ""
    rejim: str = ""
    rows: List[Tuple[str, str, str]] = field(default_factory=list)
    # Giriş / Ichimoku (yorumcu sentezi için)
    karar: str = ""
    skor: Optional[float] = None
    al_seviyesi: Optional[float] = None
    al_method: str = ""
    spot_near: bool = False
    ichimoku_buy_zone: Optional[bool] = None
    ichimoku_note: str = ""
    ready_note: bool = False
    small_size: bool = False
    aksiyon_okuma: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["rows"] = [list(r) for r in self.rows]
        return d

    def asistan_odak_dict(self) -> Dict[str, Any]:
        """Asistan odak_sembol için kompakt alanlar."""
        return {
            "rsi": self.rsi,
            "rsi_okuma": self.rsi_okuma,
            "sma20": self.sma20,
            "sma20_okuma": self.sma20_okuma,
            "sma50": self.sma50,
            "sma50_okuma": self.sma50_okuma,
            "sma200": self.sma200,
            "sma200_okuma": self.sma200_okuma,
            "kisa_okuma": self.kisa_okuma,
            "uzun_okuma": self.uzun_okuma,
            "ozet": self.ozet,
            "al_seviyesi": self.al_seviyesi,
            "al_method": self.al_method,
            "spot_near": self.spot_near,
            "ichimoku_buy_zone": self.ichimoku_buy_zone,
            "ichimoku_note": (self.ichimoku_note or "")[:120],
            "ready_note": self.ready_note,
            "aksiyon_okuma": self.aksiyon_okuma,
        }

    def prompt_block(self) -> str:
        lines = ["Teknik özet (günlük — yalnızca verilen göstergeler):"]
        for ad, deger, okuma in self.rows:
            lines.append(f"- {ad}: {deger} — {okuma}")
        if self.kisa_okuma:
            lines.append(f"- Kısa vade: {self.kisa_okuma}")
        if self.uzun_okuma:
            lines.append(f"- Orta/uzun vade: {self.uzun_okuma}")
        if self.ozet:
            lines.append(f"- Özet: {self.ozet}")
        if self.rejim:
            lines.append(f"- Rejim (motor): {self.rejim}")

        lines.append("Giriş / Ichimoku (motor):")
        if self.al_seviyesi is not None:
            near = "spot civarı" if self.spot_near else "mesafe var"
            method = self.al_method or "—"
            lines.append(
                f"- Alım seviyesi (motor): {self.al_seviyesi:.4f} "
                f"({near}; yöntem: {method})"
            )
        else:
            lines.append("- Alım seviyesi (motor): yok")
        if self.ichimoku_buy_zone is None and not self.ichimoku_note:
            lines.append("- Ichimoku: veri yok")
        else:
            bz = (
                "alım bölgesi AÇIK"
                if self.ichimoku_buy_zone
                else "alım bölgesi KAPALI — bekle"
            )
            note = self.ichimoku_note or "—"
            lines.append(f"- Ichimoku: {bz} · not: {note}")
        if self.ready_note:
            lines.append("- Eşiğe yakın not: İZLE kaldı (AL · küçük değil)")
        if self.small_size:
            lines.append("- Küçük pay teşviki (tam boyut AL değil)")
        if self.aksiyon_okuma:
            lines.append(f"- Birleşik aksiyon okuma: {self.aksiyon_okuma}")

        lines.append(
            "- Not: MACD, Stokastik, Williams, haftalık bar yok — uydurma."
        )
        return "\n".join(lines)


def _rsi_okuma(rsi: Optional[float]) -> str:
    if rsi is None:
        return "veri yok"
    if rsi <= 30:
        return "Aşırı satım bölgesi"
    if rsi < 45:
        return "Nötr-alt (hafif baskı)"
    if rsi <= 55:
        return "Nötr orta"
    if rsi < 70:
        return "Nötr-üst (hafif güç)"
    return "Aşırı alım bölgesi"


def _sma_okuma(fiyat: Optional[float], sma: Optional[float]) -> str:
    if fiyat is None or sma is None or sma <= 0:
        return "veri yok"
    if fiyat >= sma:
        return "Destek (Al) — fiyat ortalamanın üstünde"
    return "Baskı (Sat) — fiyat ortalamanın altında"


def _fmt_num(v: Optional[float], *, digits: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:.{digits}f}"


def _build_aksiyon_okuma(
    *,
    karar: str,
    al_seviyesi: Optional[float],
    spot_near: bool,
    ichimoku_buy_zone: Optional[bool],
    ichimoku_note: str,
    ready_note: bool,
    small_size: bool,
    uzun_okuma: str,
    kisa_okuma: str,
) -> str:
    """Kural tabanlı birleşik cümle — AI'ye örnek dil."""
    parts: List[str] = []
    k = (karar or "").upper()
    buyish = "AL" in k and "İZLE" not in k and "IZLE" not in k

    if al_seviyesi is not None:
        if spot_near:
            parts.append(f"Motor alım seviyesi ~{al_seviyesi:.4f} (spot civarı)")
        else:
            parts.append(
                f"Motor alım seviyesi {al_seviyesi:.4f} — fiyata yaklaşınca değerlendir"
            )
    else:
        parts.append("Net motor alım seviyesi yok")

    if ichimoku_buy_zone is True:
        parts.append("Ichimoku alım bölgesi açık")
    elif ichimoku_buy_zone is False:
        note = (ichimoku_note or "").strip()
        if note:
            parts.append(f"Ichimoku bekle diyor ({note})")
        else:
            parts.append("Ichimoku henüz bekle diyor (bölge kapalı)")
    elif ichimoku_note:
        parts.append(f"Ichimoku: {ichimoku_note}")

    if "baskı" in (kisa_okuma or "").lower() and "destek" in (uzun_okuma or "").lower():
        parts.append("kısa baskı / uzun destek çelişkisi var")
    elif "Nötr-yukarı" in (uzun_okuma or ""):
        parts.append("uzun ortalamalar destekleyici")

    if ready_note:
        parts.append("eşiğe yakın ama aksiyon hâlâ İZLE — teyit bekle")
    elif small_size:
        parts.append("yalnızca küçük pay teşviki")
    elif buyish and ichimoku_buy_zone and (spot_near or al_seviyesi is not None):
        parts.append("teknik + Ichimoku hizalıysa seviyeden kademeli düşünülebilir")
    elif buyish and ichimoku_buy_zone is False:
        parts.append("skor AL olsa bile Ichimoku teyidi yok — acele etme")
    elif not buyish:
        parts.append("motor İZLE/BEKLE tarafında — bekle veya izle")

    return ". ".join(parts) + "."


def build_tech_snapshot(
    *,
    fiyat: Optional[float] = None,
    rsi: Optional[float] = None,
    sma20: Optional[float] = None,
    sma50: Optional[float] = None,
    sma200: Optional[float] = None,
    rejim: str = "",
    karar: str = "",
    skor: Optional[float] = None,
    al_seviyesi: Optional[float] = None,
    al_method: str = "",
    spot_near: bool = False,
    ichimoku_buy_zone: Optional[bool] = None,
    ichimoku_note: str = "",
    ready_note: bool = False,
    small_size: bool = False,
) -> TechSnapshot:
    rsi_o = _rsi_okuma(rsi)
    s20_o = _sma_okuma(fiyat, sma20)
    s50_o = _sma_okuma(fiyat, sma50)
    s200_o = _sma_okuma(fiyat, sma200)

    kisa_parts: List[str] = []
    if rsi is not None:
        if rsi <= 30:
            kisa_parts.append("RSI aşırı satımda")
        elif rsi >= 70:
            kisa_parts.append("RSI aşırı alımda")
        elif 45 <= rsi <= 55:
            kisa_parts.append("RSI nötr")
        elif rsi < 45:
            kisa_parts.append("RSI hafif baskıda")
        else:
            kisa_parts.append("RSI hafif güçlü")
    if fiyat is not None and sma20 is not None and sma20 > 0:
        if fiyat < sma20:
            kisa_parts.append("kısa ortalama (SMA20) baskısı var")
        else:
            kisa_parts.append("fiyat SMA20 üstünde")
    kisa = "; ".join(kisa_parts) if kisa_parts else "Kısa vade için yeterli gösterge yok"

    ust50 = fiyat is not None and sma50 is not None and sma50 > 0 and fiyat >= sma50
    alt50 = fiyat is not None and sma50 is not None and sma50 > 0 and fiyat < sma50
    ust200 = fiyat is not None and sma200 is not None and sma200 > 0 and fiyat >= sma200
    alt200 = fiyat is not None and sma200 is not None and sma200 > 0 and fiyat < sma200

    if ust50 and ust200:
        uzun = "Nötr-yukarı — fiyat SMA50 ve SMA200 üstünde (uzun destek)"
    elif alt50 and alt200:
        uzun = "Zayıf — fiyat SMA50 ve SMA200 altında"
    elif ust200 and alt50:
        uzun = "Karışık — uzun SMA200 destekli, SMA50 altında kısa baskı"
    elif ust50 and alt200:
        uzun = "Karışık — SMA50 üstü ama SMA200 altında"
    elif ust200:
        uzun = "Uzun SMA200 üstünde destek; SMA50 verisi sınırlı"
    elif alt200:
        uzun = "Uzun SMA200 altında zayıf görünüm"
    else:
        uzun = "Orta/uzun ortalama için yeterli veri yok"

    kisa_baski = (
        (fiyat is not None and sma20 is not None and sma20 > 0 and fiyat < sma20)
        or (rsi is not None and rsi < 45)
    )
    uzun_destek = ust50 and ust200
    if kisa_baski and uzun_destek:
        ozet = (
            "Kısa vadede baskı görünüyor; orta/uzun vadede ortalamalar hâlâ destekleyici."
        )
    elif not kisa_baski and uzun_destek:
        ozet = "Kısa ve uzun vadede görünüm nötr-pozitif tarafta."
    elif kisa_baski and alt50 and alt200:
        ozet = "Kısa ve uzun vadede baskı birleşiyor — temkinli okuma."
    elif uzun_destek:
        ozet = "Uzun ortalamalar destekliyor; kısa vade sinyali sınırlı."
    else:
        ozet = "Göstergeler karışık veya eksik — tek başına karar dayanağı değil."

    rows: List[Tuple[str, str, str]] = [
        ("RSI(14)", _fmt_num(rsi, digits=1), rsi_o),
        ("SMA20", _fmt_num(sma20), s20_o),
        ("SMA50", _fmt_num(sma50), s50_o),
        ("SMA200", _fmt_num(sma200), s200_o),
    ]
    if fiyat is not None:
        rows.insert(0, ("Fiyat", _fmt_num(fiyat), "Spot"))

    aksiyon = _build_aksiyon_okuma(
        karar=karar,
        al_seviyesi=al_seviyesi,
        spot_near=spot_near,
        ichimoku_buy_zone=ichimoku_buy_zone,
        ichimoku_note=ichimoku_note,
        ready_note=ready_note,
        small_size=small_size,
        uzun_okuma=uzun,
        kisa_okuma=kisa,
    )

    return TechSnapshot(
        fiyat=fiyat,
        rsi=rsi,
        rsi_okuma=rsi_o,
        sma20=sma20,
        sma20_okuma=s20_o,
        sma50=sma50,
        sma50_okuma=s50_o,
        sma200=sma200,
        sma200_okuma=s200_o,
        kisa_okuma=kisa,
        uzun_okuma=uzun,
        ozet=ozet,
        rejim=(rejim or "").strip(),
        rows=rows,
        karar=karar or "",
        skor=skor,
        al_seviyesi=al_seviyesi,
        al_method=al_method or "",
        spot_near=bool(spot_near),
        ichimoku_buy_zone=ichimoku_buy_zone,
        ichimoku_note=ichimoku_note or "",
        ready_note=bool(ready_note),
        small_size=bool(small_size),
        aksiyon_okuma=aksiyon,
    )


def tech_snapshot_from_hisse(h: "HisseAnaliz") -> TechSnapshot:
    rejim = getattr(h, "signal_v2_regime", "") or ""
    detail = getattr(h, "signal_v2_regime_detail", "") or ""
    if detail:
        rejim = f"{rejim} — {detail}".strip(" —")

    ichi = getattr(h, "signal_v2_ichimoku", None) or {}
    if not isinstance(ichi, dict):
        ichi = {}
    buy_zone = ichi.get("buy_zone")
    if buy_zone is not None:
        buy_zone = bool(buy_zone)
    ichi_note = str(ichi.get("note") or "")

    skor = getattr(h, "signal_v2_score", None)
    if skor is None:
        skor = getattr(h, "skor", None)

    return build_tech_snapshot(
        fiyat=getattr(h, "fiyat", None),
        rsi=getattr(h, "rsi", None),
        sma20=getattr(h, "sma20", None),
        sma50=getattr(h, "sma50", None),
        sma200=getattr(h, "sma200", None),
        rejim=rejim,
        karar=str(getattr(h, "signal_v2_decision", "") or ""),
        skor=float(skor) if skor is not None else None,
        al_seviyesi=getattr(h, "signal_v2_al_price", None),
        al_method=str(getattr(h, "signal_v2_al_method", "") or ""),
        spot_near=bool(getattr(h, "signal_v2_spot_near", False)),
        ichimoku_buy_zone=buy_zone,
        ichimoku_note=ichi_note,
        ready_note=bool(getattr(h, "signal_v2_ready_note", False)),
        small_size=bool(getattr(h, "signal_v2_small_size", False)),
    )


def format_tech_snapshot_prompt(snap: Optional[TechSnapshot]) -> str:
    if snap is None:
        return ""
    return snap.prompt_block()


def table_rows_from_snapshot(snap: TechSnapshot) -> Sequence[Sequence[str]]:
    rows = [[a, b, c] for a, b, c in snap.rows]
    if snap.al_seviyesi is not None:
        near = "spot civarı" if snap.spot_near else "mesafe var"
        rows.append([
            "Alım seviyesi",
            f"{snap.al_seviyesi:.4f}",
            f"{near} · {snap.al_method or '—'}",
        ])
    if snap.ichimoku_buy_zone is not None or snap.ichimoku_note:
        bz = "Açık" if snap.ichimoku_buy_zone else "Kapalı (bekle)"
        if snap.ichimoku_buy_zone is None:
            bz = "—"
        rows.append(["Ichimoku", bz, snap.ichimoku_note or "—"])
    return rows
