# -*- coding: utf-8 -*-
"""Neden? paneli — faktör değerleri ve eşikler."""
from __future__ import annotations

from typing import TYPE_CHECKING

from signal_engine.config.loader import load_signal_config
from signal_engine.decisions.state_machine import (
    format_decision_why,
    format_effective_threshold_lines,
    format_score_vs_threshold_line,
    LEVEL_LABELS,
)

if TYPE_CHECKING:
    from stock_scanner import HisseAnaliz

_FACTOR_LABEL = {
    "trend": "Trend",
    "mean_reversion": "Mean-rev",
    "volatility": "Volatilite",
    "relative_strength": "Rel. güç",
    "liquidity": "Likidite/kalite",
}


def why_markdown(h: "HisseAnaliz") -> str:
    if not getattr(h, "signal_v2_score", None):
        return "Signal Engine v2 kapalı veya veri yok."

    cfg = load_signal_config()
    code = getattr(h, "signal_v2_code", "") or ""
    prev = getattr(h, "signal_v2_prev_code", "") or ""
    lines = [
        f"### {h.sembol} — {getattr(h, 'signal_v2_decision', '—')}",
        "",
        f"**Skor:** {h.signal_v2_score:.0f} · **Sınıf içi:** %{getattr(h, 'signal_v2_percentile', 0):.0f} · "
        f"**Veri:** {getattr(h, 'signal_v2_data', '—')}",
        "",
        format_score_vs_threshold_line(
            float(h.signal_v2_score),
            code,
            prev,
            cfg,
        ),
        "",
        f"**Rejim:** `{getattr(h, 'signal_v2_regime', '—')}` — {getattr(h, 'signal_v2_regime_detail', '')}",
        "",
        f"**Giriş:** {getattr(h, 'signal_v2_al_method', '—')}",
    ]
    if prev and prev != code:
        lines.append(f"**Önceki karar:** `{LEVEL_LABELS.get(prev, prev)}` → histerezis uygulandı")
    hyst_note = getattr(h, "signal_v2_hysteresis_note", "") or ""
    if hyst_note:
        lines.extend(["", f"**Karar gerekçesi:** {hyst_note}"])
    elif getattr(h, "signal_v2_cold_start", False):
        cold_reason = getattr(h, "signal_v2_cold_reason", "") or ""
        if cold_reason:
            lines.extend(["", f"**Karar gerekçesi:** {cold_reason}"])
    al = getattr(h, "signal_v2_al_price", None)
    if al:
        spot_near = getattr(h, "signal_v2_spot_near", False)
        method = getattr(h, "signal_v2_al_method", "") or ""
        if spot_near or "spot civarı" in method:
            lines.append(f"**Al seviyesi:** {al:.4f} (spot civarı)")
        else:
            lines.append(f"**Al seviyesi:** {al:.4f}")
    lines.extend(["", "**Faktörler**", ""])
    scores = getattr(h, "signal_v2_factors", {}) or {}
    details = getattr(h, "signal_v2_factor_details", {}) or {}
    weights = cfg.weights
    for key, w in weights.items():
        sc = scores.get(key)
        det = details.get(key, "—")
        label = _FACTOR_LABEL.get(key, key)
        if sc is not None:
            lines.append(f"- **{label}** ({w*100:.0f}%): skor **{sc:.0f}** — {det}")
        else:
            lines.append(f"- **{label}** ({w*100:.0f}%): — (eksik)")

    eq = getattr(h, "signal_v2_etf_quality", "")
    if eq:
        lines.extend(["", f"**ETF kalite:** {eq}"])

    gates = getattr(h, "signal_v2_decision_gates", None) or []
    if gates:
        lines.extend(["", "**Karar katmanları (signal v2)**"])
        for g in gates:
            lines.append(f"- {g}")

    lines.extend(["", "**Karar eşikleri (etkin)**", ""])
    lines.extend(format_effective_threshold_lines(code, cfg))
    # İtalik özet: canlı percentile (pipeline why'sinde eski %50 kalmasın)
    pct = float(getattr(h, "signal_v2_percentile", None) or 0)
    why_live = format_decision_why(
        float(h.signal_v2_score),
        pct,
        getattr(h, "signal_v2_regime", "") or "—",
        entry_method=getattr(h, "signal_v2_al_method", "") or "",
        prev_code=prev,
        code=code,
        gates=list(gates or []),
    )
    lines.extend(["", f"_{why_live}_"])
    return "\n".join(lines)
