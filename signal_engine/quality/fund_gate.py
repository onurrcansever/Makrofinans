# -*- coding: utf-8 -*-
"""Temel finans kalite kapısı — AL/GÜÇLÜ AL → İZLE (ağır / çoklu bayrak).

Teknik skora dokunmaz. Eksik kritik veri → ilgili kural atlanır (yanlış İZLE yok).
ETF / emtia: bypass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from signal_engine.quality.peer_valuation import PeerValuation


def _peer_as_dict(peer: Optional[Union[PeerValuation, dict]]) -> Optional[dict]:
    if peer is None:
        return None
    if isinstance(peer, PeerValuation):
        return peer.as_dict()
    return peer if isinstance(peer, dict) else None


@dataclass
class FundGateResult:
    block: bool = False
    reasons: List[str] = field(default_factory=list)
    soft_flags: List[str] = field(default_factory=list)
    hard_flags: List[str] = field(default_factory=list)
    applied: bool = False  # hisse + değerlendirildi


def _f(temel: dict, *keys: str) -> Optional[float]:
    for k in keys:
        v = (temel or {}).get(k)
        if v is None:
            continue
        try:
            x = float(v)
            if x == x:  # not NaN
                return x
        except (TypeError, ValueError):
            continue
    return None


def _is_hisse(h, temel: Optional[dict] = None) -> bool:
    piyasa = (getattr(h, "piyasa", "") or "").upper()
    tur = (getattr(h, "varlik_turu", "") or "").lower()
    if piyasa in ("ETF", "EMTIA") or tur in ("etf", "emtia"):
        return False
    qt = str((temel or {}).get("quoteType") or "").upper()
    if qt == "ETF":
        return False
    return True


def evaluate_fund_gate(
    temel: Optional[dict],
    h=None,
    *,
    peer: Optional[Union[PeerValuation, dict]] = None,
) -> FundGateResult:
    """Temel dict + opsiyonel HisseAnaliz → kapı sonucu."""
    out = FundGateResult()
    if h is not None and not _is_hisse(h, temel):
        return out
    if h is None and temel and str(temel.get("quoteType") or "").upper() == "ETF":
        return out

    t = temel or {}
    if not t or t.get("_bos"):
        return out

    out.applied = True
    hard: List[str] = []
    soft: List[str] = []

    # --- Analist hard ---
    key = str(t.get("recommendationKey") or "").lower().replace(" ", "_")
    sb = int(t.get("strongBuy") or 0)
    b = int(t.get("buy") or 0)
    sell = int(t.get("sell") or 0)
    ss = int(t.get("strongSell") or 0)
    hold = int(t.get("hold") or 0)
    toplam = sb + b + sell + ss + hold
    al_taraf = sb + b
    sat_taraf = sell + ss
    if key == "strong_sell":
        hard.append("Analist konsensüsü: güçlü sat")
    elif toplam >= 5 and sat_taraf >= al_taraf and sat_taraf > 0:
        hard.append(
            f"Analist sat ≥ al ({sat_taraf}/{al_taraf}, n={toplam})"
        )

    fcf = _f(t, "fcf_y")
    ni = _f(t, "net_income_y")
    if fcf is not None and ni is not None and fcf < 0 and ni < 0:
        hard.append("Yıllık FCF ve net gelir negatif")

    assets = _f(t, "total_assets_y")
    liab = _f(t, "total_liab_y")
    if assets and assets > 0 and liab is not None:
        lev = liab / assets
        if lev >= 0.85 and fcf is not None and fcf < 0:
            hard.append(f"Yüksek kaldıraç (L/A={lev:.0%}) + negatif FCF")

    # --- Soft ---
    pm = _f(t, "profit_margin_y", "profitMargins")
    # profitMargins Yahoo'da oran (0.12); profit_margin_y aynı
    if pm is not None and pm < 0:
        soft.append(f"Kâr marjı negatif ({pm:.1%})" if abs(pm) <= 2 else f"Kâr marjı negatif ({pm:.1f})")

    rev = _f(t, "revenue_y")
    rev_prev = _f(t, "revenue_y_prev")
    if rev is not None and rev_prev is not None and rev_prev > 0:
        chg = (rev / rev_prev) - 1.0
        if chg < -0.15:
            soft.append(f"Yıllık ciro %{chg*100:.0f}")

    ni_q = _f(t, "net_income_q")
    if ni is not None and ni_q is not None and ni < 0 and ni_q < 0:
        soft.append("Yıllık ve çeyrek net gelir negatif")

    fiyat = _f(t, "currentPrice", "regularMarketPrice")
    hedef = _f(t, "targetMeanPrice")
    if fiyat and fiyat > 0 and hedef is not None:
        upside = hedef / fiyat - 1.0
        if upside < -0.10:
            soft.append(f"Analist hedefi %{upside*100:.0f} (implied)")

    # Sektör F/K peer (soft) — tek başına AL kesmez
    peer_d = _peer_as_dict(peer)
    if peer_d is None and h is not None:
        peer_d = _peer_as_dict(getattr(h, "signal_v2_peer_val", None))
    if peer_d and peer_d.get("expensive"):
        pct = peer_d.get("pe_pct")
        ratio = peer_d.get("pe_vs_median")
        n = peer_d.get("peer_n")
        try:
            soft.append(
                f"Sektör F/K pahalı (P{float(pct):.0f}, {float(ratio):.1f}× medyan, n={int(n)})"
            )
        except (TypeError, ValueError):
            soft.append("Sektör F/K pahalı")

    out.hard_flags = hard
    out.soft_flags = soft
    if hard:
        out.block = True
        out.reasons = list(hard)
    elif len(soft) >= 2:
        out.block = True
        out.reasons = list(soft)
    else:
        out.block = False
        out.reasons = []
    return out


def apply_fund_gate_to_code(
    code: str,
    temel: Optional[dict],
    h,
    gates: List[str],
    *,
    peer: Optional[Union[PeerValuation, dict]] = None,
) -> str:
    """BUY/STRONG_BUY ise kapıyı uygula; gates listesine yazar."""
    if code not in ("BUY", "STRONG_BUY"):
        return code
    res = evaluate_fund_gate(temel, h, peer=peer)
    if not res.applied or not res.block:
        return code
    neden = "; ".join(res.reasons[:3])
    gates.append(f"Temel kapı: AL → İZLE ({neden})")
    return "WATCH"


def format_sirket_ozeti_markdown(
    temel: Optional[dict],
    *,
    gate: Optional[FundGateResult] = None,
    peer: Optional[Union[PeerValuation, dict]] = None,
) -> str:
    """Neden? paneli için şirket özeti."""
    t = temel or {}
    if not t or t.get("_bos"):
        return "_Temel finans verisi yok (cache boş veya çekilemedi)._"

    def _fmt_money(v) -> str:
        if v is None:
            return "—"
        try:
            x = float(v)
        except (TypeError, ValueError):
            return "—"
        ax = abs(x)
        if ax >= 1e12:
            return f"{x/1e12:.2f}T"
        if ax >= 1e9:
            return f"{x/1e9:.2f}B"
        if ax >= 1e6:
            return f"{x/1e6:.1f}M"
        return f"{x:,.0f}"

    def _fmt_pct(v) -> str:
        if v is None:
            return "—"
        try:
            x = float(v)
        except (TypeError, ValueError):
            return "—"
        if abs(x) <= 2:  # oran
            return f"{x*100:.1f}%"
        return f"{x:.1f}%"

    lines = [
        "**Şirket özeti (Yahoo — yıllık / çeyrek)**",
        "",
        "| Metrik | Yıllık | Çeyrek |",
        "|--------|--------|--------|",
        f"| Ciro | {_fmt_money(t.get('revenue_y'))} | {_fmt_money(t.get('revenue_q'))} |",
        f"| Net gelir | {_fmt_money(t.get('net_income_y'))} | {_fmt_money(t.get('net_income_q'))} |",
        f"| Kâr marjı | {_fmt_pct(t.get('profit_margin_y') or t.get('profitMargins'))} | — |",
        f"| FCF | {_fmt_money(t.get('fcf_y'))} | {_fmt_money(t.get('fcf_q'))} |",
        f"| Investing CF | {_fmt_money(t.get('investing_y'))} | {_fmt_money(t.get('investing_q'))} |",
        f"| Financing CF | {_fmt_money(t.get('financing_y'))} | {_fmt_money(t.get('financing_q'))} |",
        f"| Toplam varlık | {_fmt_money(t.get('total_assets_y'))} | {_fmt_money(t.get('total_assets_q'))} |",
        f"| Toplam yükümlülük | {_fmt_money(t.get('total_liab_y'))} | {_fmt_money(t.get('total_liab_q'))} |",
        "",
    ]
    fiyat = _f(t, "currentPrice", "regularMarketPrice")
    hedef = _f(t, "targetMeanPrice")
    if fiyat and hedef:
        lines.append(f"- Analist implied upside: **{(hedef/fiyat - 1)*100:+.1f}%**")
    rec = t.get("recommendationKey")
    if rec:
        lines.append(f"- Analist: `{rec}` · n={t.get('numberOfAnalystOpinions') or '—'}")

    pe_t = _f(t, "trailingPE")
    pe_f = _f(t, "forwardPE")
    if pe_t is not None or pe_f is not None:
        pe_txt = f"trailing {pe_t:.1f}" if pe_t is not None else "—"
        if pe_f is not None:
            pe_txt += f" · forward {pe_f:.1f}"
        lines.append(f"- F/K: **{pe_txt}**")

    peer_d = _peer_as_dict(peer)
    if peer_d:
        lines.append(
            f"- Sektör peer F/K: **{peer_d.get('pe', 0):.1f}** · "
            f"medyan **{peer_d.get('pe_median', 0):.1f}** · "
            f"P**{peer_d.get('pe_pct', 0):.0f}** · "
            f"n={peer_d.get('peer_n', 0)} · "
            f"{peer_d.get('pe_vs_median', 0):.1f}× medyan"
            + (" · **pahalı**" if peer_d.get("expensive") else "")
        )
    else:
        lines.append(
            "- Sektör peer F/K: — (küçük akran / F/K yok; değerleme peer uygulanmadı)"
        )

    g = gate or evaluate_fund_gate(t, peer=peer)
    if g.block:
        lines.append("")
        lines.append(
            "**Karara etki:** Temel kapı **AL → İZLE** — "
            + "; ".join(g.reasons)
        )
    elif g.soft_flags:
        lines.append("")
        lines.append(
            "**Karara etki:** Soft bayrak (tek başına AL kesmez): "
            + "; ".join(g.soft_flags)
        )
    elif g.applied:
        lines.append("")
        lines.append("**Karara etki:** Temel kapı geçti (AL engeli yok).")
    return "\n".join(lines)
