# -*- coding: utf-8 -*-
"""Birleşik aksiyon — teknik + temel skor + pahalı + giriş + Ichimoku.

Blended skor yok. Ham v2 kodu (decide+fund_gate+makro) üzerine yükseltme/düşürme.
AZALT asla AL'ye yükseltilmez.

Önemli: İZLE→AL (küçük) yükseltmesi ÇOK sıkı — aksi halde tablo
«hepsi AL · küçük» olur (spot civarı + SAĞLAM her yerde yaygın).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from signal_engine.decisions.state_machine import LEVEL_CODES, LEVEL_LABELS

_FUND_RANK = {
    "GÜÇLÜ": 4,
    "SAĞLAM": 3,
    "NÖTR": 2,
    "ZAYIF": 1,
    "RİSKLİ": 0,
    "YETERSİZ": -1,
}

ENTRY_FAR_PCT = 12.0
ENTRY_OK_PCT = 5.0
# Teknik skor AL eşiğine çok yakın olmadan İZLE→AL yok (config buy≈68)
NEAR_BUY_SCORE = 60.0
# Küçük-AL için minimum teknik skor (SAĞLAM ile)
LIFT_MIN_SCORE_SAGLAM = 62.0
# GÜÇLÜ temel ile biraz daha düşük bar
LIFT_MIN_SCORE_GUCLU = 58.0


@dataclass
class SynthResult:
    code: str
    label: str
    gates: List[str] = field(default_factory=list)
    small_size: bool = False
    reason: str = ""
    ready_note: bool = False  # İZLE kaldı ama eşiğe yakın bilgilendirme

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "gates": list(self.gates),
            "small_size": self.small_size,
            "reason": self.reason,
            "ready_note": self.ready_note,
        }


def _fund_rank(label: Optional[str]) -> int:
    return _FUND_RANK.get((label or "").upper(), -1)


def _peer_expensive(peer: Optional[dict]) -> bool:
    if not peer:
        return False
    return bool(peer.get("expensive"))


def synthesize_action(
    base_code: str,
    *,
    fund_label: str = "YETERSİZ",
    peer: Optional[dict] = None,
    spot_near: bool = False,
    spot_distance_pct: Optional[float] = None,
    ichimoku_buy_zone: bool = False,
    ichimoku_note: str = "",
    regime: str = "",
    tech_score: Optional[float] = None,
    gates: Optional[List[str]] = None,
) -> SynthResult:
    """
    base_code: fund_gate + makro sonrası kod.
    tech_score: birleşik teknik skor — İZLE→AL için zorunlu yakınlık kontrolü.
    """
    code = base_code if base_code in LEVEL_CODES else "WATCH"
    g = list(gates or [])
    expensive = _peer_expensive(peer)
    fr = _fund_rank(fund_label)
    regime_u = (regime or "").upper()
    dist = float(spot_distance_pct) if spot_distance_pct is not None else None
    entry_ok = spot_near or (dist is not None and dist <= ENTRY_OK_PCT)
    entry_far = dist is not None and dist > ENTRY_FAR_PCT
    score = float(tech_score) if tech_score is not None else None

    small_size = False
    ready_note = False
    reasons: List[str] = []

    # --- 1) AZALT: yükseltme yok ---
    if code == "REDUCE":
        if expensive:
            g.append("Sentez: sektör F/K pahalı (görünür uyarı)")
            reasons.append("pahalı")
        reasons.append("teknik AZALT — yükseltme yok")
        return SynthResult(
            code=code,
            label=LEVEL_LABELS[code],
            gates=g,
            reason=" · ".join(reasons),
        )

    # --- 2) Düşürme ---
    if code in ("BUY", "STRONG_BUY"):
        label_u = (fund_label or "").strip().upper()
        etf_bypass = label_u in ("—", "-", "–")
        # YETERSİZ / ZAYIF / RİSKLİ → AL yok; ETF "—" bypass (bilanço yok)
        if not etf_bypass and fr <= 1:
            g.append(f"Sentez: Temel {fund_label or 'YETERSİZ'} → AL/GÜÇLÜ AL → İZLE")
            code = "WATCH"
            reasons.append(f"temel {fund_label or 'YETERSİZ'}")
        elif expensive and fr <= 2 and not etf_bypass:
            g.append("Sentez: sektör F/K pahalı + temel zayıf/nötr → İZLE")
            code = "WATCH"
            reasons.append("pahalı+temel")
        elif expensive and fr >= 3:
            g.append("Sentez: sektör F/K pahalı (uyarı) — temel sağlam, AL korunur")
            reasons.append("pahalı uyarı")
        elif entry_far:
            # Ichimoku yeşil olsa bile uzak girişte kovalama yok
            g.append(
                f"Sentez: fiyat girişin %{dist:.0f} üstünde → İZLE "
                "(bölge/geri çekilme bekle; Ichimoku kovalama izni vermez)"
            )
            code = "WATCH"
            reasons.append("giriş uzak")

    # --- 3) GÜÇLÜ AL sıkılaştırma ---
    if code == "STRONG_BUY":
        if fr < 3 or expensive or not entry_ok:
            if fr < 3:
                g.append(f"Sentez: Temel {fund_label or 'yetersiz'} → GÜÇLÜ AL → AL")
                reasons.append("temel GÜÇLÜ AL için yetmez")
            elif expensive:
                g.append("Sentez: pahalı → GÜÇLÜ AL → AL")
                reasons.append("pahalı")
            elif not entry_ok:
                g.append("Sentez: giriş uzak → GÜÇLÜ AL → AL")
                reasons.append("giriş")
            code = "BUY"

    # --- 4) İZLE→AL (küçük): sıkı AND koşulları ---
    # Eski gevşek kural (SAĞLAM + spot VEYA ichimoku) tabloyu «AL · küçük» dolduruyordu.
    if code == "WATCH":
        min_score = LIFT_MIN_SCORE_GUCLU if fr >= 4 else LIFT_MIN_SCORE_SAGLAM
        score_ok = score is not None and score >= min_score
        # Hem spot civarı hem Ichimoku bölgesi — tek başına yetmez
        zone_ok = bool(spot_near and ichimoku_buy_zone)
        regime_ok = regime_u == "TRENDING_UP"
        fund_ok = fr >= 3
        can_lift = (
            fund_ok
            and zone_ok
            and score_ok
            and regime_ok
            and not expensive
            and not entry_far
        )
        if can_lift:
            g.append(
                "Sentez: skor eşiğe yakın + Temel sağlam + spot+Ichimoku + Trend↑ "
                "→ AL (küçük pay)"
            )
            if ichimoku_note:
                g.append(ichimoku_note)
            code = "BUY"
            small_size = True
            reasons.append("sıkı bölge teşviki")
        else:
            # Bilgilendirme: AL demeden «hazır» ipucu
            soft_ready = (
                fund_ok
                and (spot_near or ichimoku_buy_zone)
                and not expensive
                and regime_u != "TRENDING_DOWN"
            )
            if soft_ready:
                missing = []
                if not spot_near:
                    missing.append("spot civarı yok")
                if not ichimoku_buy_zone:
                    missing.append("Ichimoku bölgesi yok")
                if not score_ok:
                    missing.append(
                        f"skor<{min_score:.0f}"
                        + (f" (şimdi {score:.0f})" if score is not None else "")
                    )
                if not regime_ok:
                    missing.append(f"rejim≠Trend↑ ({regime_u or '—'})")
                g.append(
                    "Sentez: eşiğe yakın aday (İZLE) — AL değil. Eksik: "
                    + (", ".join(missing) if missing else "koşul tam değil")
                )
                ready_note = True
                reasons.append("hazır notu · İZLE korundu")
            elif expensive:
                g.append("Sentez: sektör F/K pahalı (görünür uyarı)")
                reasons.append("pahalı uyarı")

    # WAIT: asla yükseltme
    if code == "WAIT" and expensive:
        g.append("Sentez: sektör F/K pahalı (görünür uyarı)")
        reasons.append("pahalı uyarı")

    if code == "BUY" and not small_size:
        if fr >= 2 and not expensive:
            reasons.append(f"teknik AL + temel {fund_label or 'NÖTR+'}")
        elif fr >= 3:
            reasons.append(f"teknik AL + temel {fund_label}")

    if ichimoku_buy_zone and code in ("BUY", "STRONG_BUY"):
        if ichimoku_note and ichimoku_note not in g:
            g.append(ichimoku_note)

    label = LEVEL_LABELS.get(code, code)
    reason = " · ".join(reasons) if reasons else f"ham {LEVEL_LABELS.get(base_code, base_code)}"
    return SynthResult(
        code=code,
        label=label,
        gates=g,
        small_size=small_size,
        reason=reason,
        ready_note=ready_note,
    )
