# -*- coding: utf-8 -*-
"""Neden? paneli — okunaklı tablolar (inline stil, koyu tema)."""
from __future__ import annotations

import html
from typing import TYPE_CHECKING, List, Optional, Sequence

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

# ui_theme ile aynı palet — CSS ezilse bile okunur
_BG = "#1E2329"
_BG_H = "#2B3139"
_BG_ALT = "#22272e"
_TXT = "#EAECEF"
_MUTED = "#848E9C"
_BD = "#3a4149"


def _esc(s: object) -> str:
    return html.escape("" if s is None else str(s))


def _html_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    ths = "".join(
        f'<th style="background:{_BG_H};color:{_TXT};border:1px solid {_BD};'
        f'padding:8px 10px;text-align:left;font-weight:600;">{_esc(h)}</th>'
        for h in headers
    )
    body = []
    for i, row in enumerate(rows):
        bg = _BG_ALT if i % 2 else _BG
        tds = "".join(
            f'<td style="background:{bg};color:{_TXT};border:1px solid {_BD};'
            f'padding:8px 10px;">{_esc(c)}</td>'
            for c in row
        )
        body.append(f"<tr>{tds}</tr>")
    return (
        f'<table style="width:100%;border-collapse:collapse;background:{_BG};'
        f'color:{_TXT};margin:10px 0 12px;font-size:13px;line-height:1.35;">'
        f"<thead><tr>{ths}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def _factor_plain(score: Optional[float]) -> str:
    if score is None:
        return "eksik"
    if score >= 70:
        return "güçlü"
    if score >= 52:
        return "orta"
    if score >= 40:
        return "zayıf"
    return "çok zayıf"


def why_markdown(h: "HisseAnaliz") -> str:
    if not getattr(h, "signal_v2_score", None):
        return "Signal Engine v2 kapalı veya veri yok."

    cfg = load_signal_config()
    code = getattr(h, "signal_v2_code", "") or ""
    prev = getattr(h, "signal_v2_prev_code", "") or ""
    decision = getattr(h, "signal_v2_decision", "—")
    lines: List[str] = [
        f"### {_esc(h.sembol)} — {_esc(decision)}",
        "",
        _html_table(
            ["Alan", "Değer"],
            [
                ["Teknik skor", f"{h.signal_v2_score:.0f}"],
                [
                    "Sınıf içi sıra",
                    f"%{getattr(h, 'signal_v2_percentile', 0):.0f} "
                    "(güven değil — akran sırası)",
                ],
                ["Veri", getattr(h, "signal_v2_data", "—")],
                [
                    "Rejim",
                    f"{getattr(h, 'signal_v2_regime', '—')} — "
                    f"{getattr(h, 'signal_v2_regime_detail', '')}",
                ],
                ["Giriş yöntemi", getattr(h, "signal_v2_al_method", "—")],
            ],
        ),
        "",
        format_score_vs_threshold_line(
            float(h.signal_v2_score),
            code,
            prev,
            cfg,
        ),
    ]

    # Teknik özet — mevcut RSI/SMA (skora girmez)
    try:
        from signal_engine.explain.tech_snapshot import (
            table_rows_from_snapshot,
            tech_snapshot_from_hisse,
        )

        snap = tech_snapshot_from_hisse(h)
        lines.extend([
            "",
            "**Teknik özet (günlük — mevcut göstergeler)**",
            "",
            _html_table(
                ["Gösterge", "Değer", "Okuma"],
                table_rows_from_snapshot(snap),
            ),
        ])
        if snap.kisa_okuma or snap.uzun_okuma:
            lines.append(
                f'<p style="color:{_TXT};font-size:13px;margin:4px 0 2px;">'
                f"<b>Kısa vade:</b> {_esc(snap.kisa_okuma)}<br/>"
                f"<b>Orta/uzun:</b> {_esc(snap.uzun_okuma)}</p>"
            )
        if snap.ozet:
            lines.append(
                f'<p style="color:{_TXT};font-size:13px;margin:2px 0 4px;">'
                f"{_esc(snap.ozet)}</p>"
            )
        if snap.aksiyon_okuma:
            lines.append(
                f'<p style="color:{_TXT};font-size:13px;margin:2px 0 4px;">'
                f"<b>Birleşik aksiyon:</b> {_esc(snap.aksiyon_okuma)}</p>"
            )
        lines.append(
            f'<p style="color:{_MUTED};font-size:12px;margin:0 0 12px;">'
            "Destek/Baskı = fiyatın ortalamanın üstünde/altında olması "
            "(kesin al/sat emri değil). MACD/haftalık yok; "
            "skor motoru bu tablodan bağımsız.</p>"
        )
    except Exception:
        pass

    if prev and prev != code:
        lines.append(
            f"**Önceki karar:** `{LEVEL_LABELS.get(prev, prev)}` → histerezis"
        )
    hyst_note = getattr(h, "signal_v2_hysteresis_note", "") or ""
    if hyst_note:
        lines.extend(["", f"**Karar gerekçesi:** {_esc(hyst_note)}"])
    elif getattr(h, "signal_v2_cold_start", False):
        cold_reason = getattr(h, "signal_v2_cold_reason", "") or ""
        if cold_reason:
            lines.extend(["", f"**Karar gerekçesi:** {_esc(cold_reason)}"])

    al = getattr(h, "signal_v2_al_price", None)
    if al:
        spot_near = getattr(h, "signal_v2_spot_near", False)
        method = getattr(h, "signal_v2_al_method", "") or ""
        if spot_near or "spot civarı" in method:
            lines.append(f"**Al seviyesi:** {al:.4f} (spot civarı)")
        else:
            lines.append(f"**Al seviyesi:** {al:.4f}")

    # Teknik faktörler
    lines.extend(["", "**Teknik faktörler**", ""])
    scores = getattr(h, "signal_v2_factors", {}) or {}
    details = getattr(h, "signal_v2_factor_details", {}) or {}
    frows = []
    for key, w in cfg.weights.items():
        sc = scores.get(key)
        det = details.get(key, "—")
        label = _FACTOR_LABEL.get(key, key)
        vs = f"{sc:.0f}" if sc is not None else "—"
        frows.append([label, f"%{w*100:.0f}", vs, _factor_plain(sc), det])
    lines.append(_html_table(["Faktör", "Ağırlık", "Skor", "Okuma", "Detay"], frows))
    lines.append(
        f'<p style="color:{_MUTED};font-size:12px;margin:0 0 12px;">'
        "Faktör tablosu: teknik motorun parçaları. "
        "Düşük skor = o faktör zayıf; tek başına AL/İZLE demez.</p>"
    )

    eq = getattr(h, "signal_v2_etf_quality", "")
    if eq:
        lines.extend(["", f"**ETF kalite:** {_esc(eq)}"])

    gates = getattr(h, "signal_v2_decision_gates", None) or []
    if gates:
        lines.extend(["", "**Karar katmanları**", ""])
        lines.append(
            _html_table(
                ["#", "Not"],
                [[str(i), g] for i, g in enumerate(gates, 1)],
            )
        )

    lines.extend(["", "**Karar eşikleri (etkin)**", ""])
    for ln in format_effective_threshold_lines(code, cfg):
        lines.append(ln)

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
    lines.extend(["", f"_{_esc(why_live)}_"])

    try:
        synth_r = getattr(h, "signal_v2_synth_reason", "") or ""
        if synth_r:
            lines.extend(["", f"**Birleşik karar:** {_esc(synth_r)}"])
        if getattr(h, "signal_v2_small_size", False):
            lines.append("_Küçük pay — sıkı bölge teşviki (tam boyut değil)._")
        if getattr(h, "signal_v2_ready_note", False):
            lines.append("_Eşiğe yakın aday — aksiyon hâlâ İZLE (AL · küçük değil)._")
        ichi = getattr(h, "signal_v2_ichimoku", None) or {}
        if ichi:
            note = ichi.get("note") or "—"
            bz = "evet" if ichi.get("buy_zone") else "hayır"
            lines.extend([
                "",
                "**Ichimoku (timing)**",
                "",
                _html_table(
                    ["Alan", "Değer"],
                    [["Alım bölgesi", bz], ["Not", note]],
                ),
                f'<p style="color:{_MUTED};font-size:12px;">'
                "Ichimoku kesin dönüş vaat etmez; kural tabanlı bölge.</p>",
            ])
    except Exception:
        pass

    try:
        from signal_engine.quality.fund_score import (
            FundScoreResult,
            format_fund_score_table_html,
            format_fund_score_table_markdown,
        )
        from signal_engine.quality.fund_score_ui import (
            fund_score_banner_text,
            fund_score_ui_enabled,
        )

        detail = getattr(h, "signal_v2_fund_score_detail", None)
        if fund_score_ui_enabled() and detail:
            fund = FundScoreResult(
                score=detail.get("score"),
                label=detail.get("label") or "YETERSİZ",
                pillars=detail.get("pillars") or {},
                missing=detail.get("missing") or [],
                partial_pillars=detail.get("partial_pillars") or [],
                asof=detail.get("asof"),
                reasons=detail.get("reasons") or [],
                mode=detail.get("mode") or "live",
                used_fields=detail.get("used_fields") or [],
            )
            banner = fund_score_banner_text()
            if banner:
                lines.extend(["", f"> _{_esc(banner)}_"])
            # HTML tablo (kontrast garantili)
            if hasattr(format_fund_score_table_html, "__call__"):
                lines.extend(["", format_fund_score_table_html(fund)])
            else:
                lines.extend(["", format_fund_score_table_markdown(fund)])
            dual = getattr(h, "signal_v2_dual_line", "") or ""
            if dual:
                lines.extend(["", f"**İki eksen:** {_esc(dual)}"])
    except Exception:
        pass

    return "\n".join(lines)
