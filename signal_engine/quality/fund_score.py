# -*- coding: utf-8 -*-
"""Bağımsız TEMEL SKOR (0–100) — teknik skor / fund_gate ile karışmaz.

mode=live: Yahoo .info + bilanço
mode=backtest: live-only alanlar dışlanır; yalnızca PIT adayı statement alanları
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Tuple

from signal_engine.quality.fund_score_pit import (
    LIVE_ONLY_FIELDS,
    filter_temel_for_mode,
)
from signal_engine.quality.peer_valuation import MIN_PEERS, _group_key, _is_hisse, _percentile_rank

PILLAR_WEIGHTS = {
    "quality": 0.30,
    "growth": 0.25,
    "valuation": 0.25,
    "health": 0.20,
}

LABEL_BANDS = (
    (80.0, "GÜÇLÜ"),
    (64.0, "SAĞLAM"),
    (52.0, "NÖTR"),
    (42.0, "ZAYIF"),
    (0.0, "RİSKLİ"),
)

# Temel skor için minimum alan — yoksa cache doldur / YETERSİZ
_FUND_CORE_KEYS = (
    "revenue_y",
    "profit_margin_y",
    "profitMargins",
    "trailingPE",
    "forwardPE",
    "returnOnEquity",
    "fcf_y",
    "total_assets_y",
    "net_income_y",
    "operatingMargins",
)


HISSE_TEMEL_SUTUN = "Temel"


def is_etf_or_emtia(h: Any = None, temel: Optional[dict] = None) -> bool:
    if h is not None:
        piyasa = (getattr(h, "piyasa", "") or "").upper()
        tur = (getattr(h, "varlik_turu", "") or "").lower()
        if piyasa in ("ETF", "EMTIA") or tur in ("etf", "emtia"):
            return True
    qt = str((temel or {}).get("quoteType") or "").upper()
    return qt in ("ETF", "MUTUALFUND", "INDEX", "CURRENCY", "FUTURE")


def temel_fund_yeterli(temel: Optional[dict]) -> bool:
    """Skor üretmek için yeterli ham alan var mı? (peer şart değil)."""
    if not temel or temel.get("_bos"):
        return False
    if is_etf_or_emtia(temel=temel):
        return False
    n = sum(1 for k in _FUND_CORE_KEYS if temel.get(k) is not None)
    return n >= 2


def ensure_temel_cache_for_fund_score(
    hisseler: Iterable[Any],
    cache: Optional[Dict[str, dict]] = None,
) -> Dict[str, dict]:
    """Eksik hisse temel cache'ini doldur — yanlış YETERSİZ azaltır."""
    try:
        from temel_veri import yukle_cache, temel_veri_tarama_icin
    except Exception:
        return dict(cache or {})

    out = dict(cache or yukle_cache() or {})
    need: List[str] = []
    for h in hisseler or []:
        if is_etf_or_emtia(h):
            continue
        sym = (getattr(h, "sembol", "") or "").strip().upper()
        if not sym:
            continue
        if not temel_fund_yeterli(out.get(sym)):
            need.append(sym)
    need = list(dict.fromkeys(need))
    if not need:
        return out
    try:
        filled, _stats = temel_veri_tarama_icin(need, force=False)
        out.update(filled or {})
    except Exception:
        # Tek tek dene (en azından UNH tipi büyük hisseler)
        try:
            from temel_veri import get_temel

            for sym in need[:40]:
                try:
                    t = get_temel(sym)
                    if t:
                        out[sym] = t
                except Exception:
                    continue
        except Exception:
            pass
    return out


def _pe_abs_score(pe: Optional[float]) -> Optional[float]:
    """Peer yokken mutlak F/K — düşük daha iyi (aşırı ucuz değer kapanı yok)."""
    if pe is None or pe <= 0:
        return None
    if pe < 12:
        return 72.0
    if pe < 18:
        return 66.0
    if pe < 25:
        return 58.0
    if pe < 35:
        return 48.0
    if pe < 50:
        return 38.0
    return 28.0


@dataclass
class FundScoreResult:
    score: Optional[float]
    label: str
    pillars: Dict[str, Optional[float]] = field(default_factory=dict)
    missing: List[str] = field(default_factory=list)
    partial_pillars: List[str] = field(default_factory=list)
    asof: Optional[str] = None
    reasons: List[str] = field(default_factory=list)
    mode: str = "live"
    used_fields: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "label": self.label,
            "pillars": dict(self.pillars),
            "missing": list(self.missing),
            "partial_pillars": list(self.partial_pillars),
            "asof": self.asof,
            "reasons": list(self.reasons),
            "mode": self.mode,
            "used_fields": list(self.used_fields),
        }


def label_from_score(score: Optional[float]) -> str:
    if score is None:
        return "YETERSİZ"
    for thr, lab in LABEL_BANDS:
        if score >= thr:
            return lab
    return "RİSKLİ"


def _f(temel: dict, *keys: str) -> Optional[float]:
    for k in keys:
        v = temel.get(k)
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if x == x:
            return x
    return None


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _avg(vals: List[Optional[float]]) -> Optional[float]:
    xs = [v for v in vals if v is not None]
    if not xs:
        return None
    return float(mean(xs))


def _pct_to_score(pct: Optional[float], *, higher_better: bool = True) -> Optional[float]:
    """Peer percentile → 0–100. higher_better=False → pahalı/kötü yüksek %ile."""
    if pct is None:
        return None
    return _clip(pct if higher_better else (100.0 - pct))


def _margin_abs_score(m: Optional[float]) -> Optional[float]:
    """Kâr marjı mutlak: negatif düşük, %20+ yüksek."""
    if m is None:
        return None
    # m oran (0.15 = %15) veya zaten yüzde olabilir
    x = m * 100.0 if abs(m) <= 1.5 else m
    return _clip(50.0 + x * 2.5)


def _roe_score(roe: Optional[float]) -> Optional[float]:
    if roe is None:
        return None
    x = roe * 100.0 if abs(roe) <= 2.0 else roe
    return _clip(40.0 + x * 2.0)


def _growth_score(g: Optional[float]) -> Optional[float]:
    if g is None:
        return None
    x = g * 100.0 if abs(g) <= 2.0 else g
    return _clip(50.0 + x * 1.5)


def _fcf_margin_score(fcf: Optional[float], rev: Optional[float]) -> Optional[float]:
    if fcf is None or rev is None or rev == 0:
        return None
    m = fcf / rev
    x = m * 100.0
    return _clip(50.0 + x * 2.0)


def _leverage_score(assets: Optional[float], liab: Optional[float]) -> Optional[float]:
    if assets is None or liab is None or assets <= 0:
        return None
    ratio = liab / assets
    # 0.3 → iyi (~80), 0.7 → zayıf (~40), 1.0+ → riskli
    return _clip(100.0 - ratio * 80.0)


def _debt_equity_score(de: Optional[float]) -> Optional[float]:
    if de is None:
        return None
    # Yahoo debtToEquity çoğu zaman yüzde (80 = 0.8)
    x = de / 100.0 if de > 5 else de
    return _clip(100.0 - x * 40.0)


def _liquidity_score(cr: Optional[float]) -> Optional[float]:
    if cr is None:
        return None
    # current ratio 1.5–2.5 ideal
    if cr < 0.8:
        return 25.0
    if cr < 1.0:
        return 40.0
    if cr <= 2.5:
        return _clip(50.0 + (cr - 1.0) * 25.0)
    return _clip(85.0 - (cr - 2.5) * 10.0)


def _peg_score(peg: Optional[float]) -> Optional[float]:
    if peg is None or peg <= 0:
        return None
    # PEG < 1 iyi
    return _clip(100.0 - peg * 35.0)


def _fcf_yield_score(fcf: Optional[float], mcap: Optional[float]) -> Optional[float]:
    if fcf is None or mcap is None or mcap <= 0:
        return None
    y = fcf / mcap
    return _clip(50.0 + y * 400.0)


def _analyst_tilt_score(temel: dict) -> Optional[float]:
    al = _f(temel, "al_sayi")
    sell = (_f(temel, "sell") or 0) + (_f(temel, "strongSell") or 0)
    hold = _f(temel, "hold") or 0
    total = (al or 0) + sell + hold
    if total <= 0 and al is None:
        return None
    if total <= 0:
        return None
    buy_ratio = (al or 0) / total
    return _clip(buy_ratio * 100.0)


def peer_metric_percentile(
    peer_ctx: Optional[Dict[str, Any]],
    metric: str,
) -> Optional[float]:
    """peer_ctx: {metric: pct, f'{metric}_n': n, ...} — n<MIN_PEERS → None."""
    if not peer_ctx:
        return None
    n = peer_ctx.get(f"{metric}_n")
    pct = peer_ctx.get(metric)
    if pct is None:
        return None
    try:
        if n is not None and int(n) < MIN_PEERS:
            return None
        return float(pct)
    except (TypeError, ValueError):
        return None


def build_peer_metric_map(
    hisseler: Iterable[Any],
    cache: Dict[str, dict],
    metric_fn,
    *,
    metric_key: str,
    min_peers: int = MIN_PEERS,
) -> Dict[str, Dict[str, Any]]:
    """(piyasa, sektör) gruplarında metrik percentile map."""
    members: Dict[Tuple[str, str], List[Tuple[str, float]]] = {}
    for h in hisseler or []:
        if not _is_hisse(h):
            continue
        sym = (getattr(h, "sembol", "") or "").strip().upper()
        if not sym:
            continue
        temel = cache.get(sym) or {}
        val = metric_fn(temel)
        if val is None:
            continue
        members.setdefault(_group_key(h), []).append((sym, float(val)))

    out: Dict[str, Dict[str, Any]] = {}
    for _key, pairs in members.items():
        if len(pairs) < min_peers:
            continue
        vals = [v for _, v in pairs]
        for sym, val in pairs:
            pct = _percentile_rank(vals, val)
            out.setdefault(sym, {})[metric_key] = pct
            out[sym][f"{metric_key}_n"] = len(pairs)
    return out


def _yoy_growth(cur: Optional[float], prev: Optional[float]) -> Optional[float]:
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / abs(prev)


def compute_fund_score(
    temel: Optional[dict],
    peer_ctx: Optional[Dict[str, Any]] = None,
    *,
    mode: str = "live",
) -> FundScoreResult:
    """
    Temel skor. Eksik alt-metrik → None (sessiz 50 yok).
    Sütun = mevcut alt-metrik ortalaması; tüm sütun boş → skor None.
    """
    mode = "backtest" if mode == "backtest" else "live"
    raw = filter_temel_for_mode(temel, mode)
    missing: List[str] = []
    used: List[str] = []
    reasons: List[str] = []
    peer_ctx = peer_ctx or {}

    asof = None
    for k in ("finans_guncelleme", "guncelleme", "period_end_q", "period_end_y"):
        if raw.get(k):
            asof = str(raw[k])
            break

    # --- Quality 30% ---
    q_parts: List[Optional[float]] = []
    pm = _f(raw, "profit_margin_y", "profitMargins", "operatingMargins")
    if pm is not None:
        used.append("profit_margin")
        q_parts.append(_margin_abs_score(pm))
    else:
        missing.append("profit_margin")
    pm_pct = peer_metric_percentile(peer_ctx, "margin_pct")
    if pm_pct is not None:
        used.append("margin_peer_pct")
        q_parts.append(_pct_to_score(pm_pct, higher_better=True))
    else:
        missing.append("margin_peer_pct")

    roe = _f(raw, "returnOnEquity")
    if roe is not None:
        used.append("returnOnEquity")
        q_parts.append(_roe_score(roe))
    else:
        missing.append("returnOnEquity")

    fcf_m = _fcf_margin_score(_f(raw, "fcf_y"), _f(raw, "revenue_y"))
    if fcf_m is not None:
        used.append("fcf_margin")
        q_parts.append(fcf_m)
    else:
        missing.append("fcf_margin")

    quality = _avg(q_parts)

    # --- Growth 25% ---
    g_parts: List[Optional[float]] = []
    yoy = _yoy_growth(_f(raw, "revenue_y"), _f(raw, "revenue_y_prev"))
    if yoy is not None:
        used.append("revenue_yoy")
        g_parts.append(_growth_score(yoy))
    else:
        missing.append("revenue_yoy")

    eg = _f(raw, "earningsGrowth")
    if eg is not None:
        used.append("earningsGrowth")
        g_parts.append(_growth_score(eg))
    else:
        missing.append("earningsGrowth")

    rg = _f(raw, "revenueGrowth")
    if rg is not None:
        used.append("revenueGrowth")
        g_parts.append(_growth_score(rg))
    else:
        missing.append("revenueGrowth")

    growth = _avg(g_parts)

    # --- Valuation 25% ---
    v_parts: List[Optional[float]] = []
    if mode == "live":
        pe_pct = peer_metric_percentile(peer_ctx, "pe_pct")
        if pe_pct is not None:
            used.append("pe_peer_pct")
            v_parts.append(_pct_to_score(pe_pct, higher_better=False))
        else:
            missing.append("pe_peer_pct")
            # Peer yokken mutlak F/K — sessizce valuation'ı boş bırakma
            pe_abs = _f(raw, "trailingPE", "forwardPE")
            pe_s = _pe_abs_score(pe_abs)
            if pe_s is not None:
                used.append("pe_abs")
                v_parts.append(pe_s)
            else:
                missing.append("pe_abs")

        peg = _f(raw, "pegRatio")
        if peg is not None:
            used.append("pegRatio")
            v_parts.append(_peg_score(peg))
        else:
            missing.append("pegRatio")

        ev_pct = peer_metric_percentile(peer_ctx, "ev_ebitda_pct")
        if ev_pct is not None:
            used.append("ev_ebitda_peer_pct")
            v_parts.append(_pct_to_score(ev_pct, higher_better=False))
        else:
            missing.append("ev_ebitda_peer_pct")

        fy = _fcf_yield_score(_f(raw, "fcf_y"), _f(raw, "marketCap", "enterpriseValue"))
        if fy is not None:
            used.append("fcf_yield")
            v_parts.append(fy)
        else:
            missing.append("fcf_yield")
    else:
        # Backtest: piyasa çarpanı / FCF yield (mcap) yok
        missing.extend(
            ["pe_peer_pct", "pegRatio", "ev_ebitda_peer_pct", "fcf_yield"]
        )

    valuation = _avg(v_parts)

    # --- Health 20% ---
    h_parts: List[Optional[float]] = []
    lev = _leverage_score(
        _f(raw, "total_assets_y", "total_assets_q"),
        _f(raw, "total_liab_y", "total_liab_q"),
    )
    if lev is not None:
        used.append("leverage_la")
        h_parts.append(lev)
    else:
        missing.append("leverage_la")

    de = _f(raw, "debtToEquity")
    if de is not None:
        used.append("debtToEquity")
        h_parts.append(_debt_equity_score(de))
    else:
        missing.append("debtToEquity")

    cr = _f(raw, "currentRatio", "quickRatio")
    if cr is not None:
        used.append("currentRatio")
        h_parts.append(_liquidity_score(cr))
    else:
        missing.append("currentRatio")

    # Analist — düşük pay (yalnızca live)
    an = _analyst_tilt_score(raw)
    if an is not None:
        used.append("analyst_tilt")
        # düşük ağırlık: health içinde 0.25 pay gibi davran — ortalamaya 1/4 etki için iki kez nötr eklemez;
        # tek alt-metrik olarak ekle ama reasons'ta düşük pay notu
        h_parts.append(an)
        reasons.append("Analist görüşü düşük pay (health alt-metriği)")
    else:
        missing.append("analyst_tilt")

    health = _avg(h_parts)

    pillars = {
        "quality": quality,
        "growth": growth,
        "valuation": valuation,
        "health": health,
    }
    partial_pillars: List[str] = []
    pillar_miss_map = {
        "quality": ("profit_margin", "margin_peer_pct", "returnOnEquity", "fcf_margin"),
        "growth": ("revenue_yoy", "earningsGrowth", "revenueGrowth"),
        "valuation": ("pe_peer_pct", "pe_abs", "pegRatio", "ev_ebitda_peer_pct", "fcf_yield"),
        "health": ("leverage_la", "debtToEquity", "currentRatio", "analyst_tilt"),
    }
    for pk, keys in pillar_miss_map.items():
        if pillars[pk] is None:
            continue
        if any(k in missing for k in keys):
            partial_pillars.append(pk)

    present = [(k, pillars[k]) for k in PILLAR_WEIGHTS if pillars[k] is not None]
    if not present:
        return FundScoreResult(
            score=None,
            label="YETERSİZ",
            pillars=pillars,
            missing=missing,
            partial_pillars=partial_pillars,
            asof=asof,
            reasons=["Yeterli temel veri yok"],
            mode=mode,
            used_fields=used,
        )

    w_sum = sum(PILLAR_WEIGHTS[k] for k, _ in present)
    score = sum(PILLAR_WEIGHTS[k] * v for k, v in present) / w_sum
    score = round(_clip(score), 1)
    lab = label_from_score(score)
    if mode == "backtest":
        reasons.append("Backtest: live-only alanlar dışlandı")
    if partial_pillars:
        reasons.append(f"Kısmi sütunlar: {', '.join(partial_pillars)}")

    # Look-ahead teyidi: used içinde live-only olmamalı (backtest)
    if mode == "backtest":
        bad = [f for f in used if f in LIVE_ONLY_FIELDS]
        # used alan adları türetilmiş olabilir; ham key kontrolü filter'da yapıldı
        if bad:
            reasons.append(f"UYARI live-only sızdı: {bad}")

    return FundScoreResult(
        score=score,
        label=lab,
        pillars=pillars,
        missing=missing,
        partial_pillars=partial_pillars,
        asof=asof,
        reasons=reasons,
        mode=mode,
        used_fields=sorted(set(used)),
    )


def dual_axis_comment(tech_label: str, fund_label: str) -> str:
    """Teknik + temel → kısa kural tabanlı yorum (blended skor yok)."""
    t = (tech_label or "").upper()
    f = (fund_label or "").upper()
    if f in ("YETERSİZ", "", "—"):
        return "temel veri yetersiz"
    if "AZALT" in t and f in ("SAĞLAM", "GÜÇLÜ"):
        return "kısa vade zayıf, temel sağlam"
    if "AZALT" in t and f in ("ZAYIF", "RİSKLİ"):
        return "momentum ve temel zayıf"
    if ("AL" in t or "GÜÇLÜ" in t) and f in ("ZAYIF", "RİSKLİ"):
        return "momentum güçlü, temel zayıf — dikkat"
    if ("AL" in t or "GÜÇLÜ" in t) and f in ("SAĞLAM", "GÜÇLÜ"):
        return "momentum ve temel uyumlu"
    if "İZLE" in t and f in ("SAĞLAM", "GÜÇLÜ"):
        return "izle; temel sağlam — teknik fren/kapı olabilir"
    return "iki eksen ayrı okunmalı"


def pillar_plain_caption(pillar: str, score: Optional[float]) -> str:
    """Kullanıcı dilinde kısa okuma — tek sütun ne diyor?"""
    if score is None:
        return "veri yok / hesaplanamadı"
    p = (pillar or "").lower()
    if p == "quality":
        if score >= 70:
            return "kârlılık/kalite iyi görünüyor"
        if score >= 52:
            return "kalite orta"
        return "kârlılık/kalite zayıf"
    if p == "growth":
        if score >= 70:
            return "büyüme güçlü"
        if score >= 52:
            return "büyüme ılımlı"
        return "büyüme zayıf veya durgun"
    if p == "valuation":
        if score >= 70:
            return "değerleme cazip (ucuz/makul taraf)"
        if score >= 52:
            return "değerleme nötr"
        if score >= 35:
            return "değerleme pahalı tarafta"
        return "bu hisse şu an pahalı görünüyor"
    if p == "health":
        if score >= 70:
            return "bilanço/borç tarafı sağlam"
        if score >= 52:
            return "finansal sağlık orta"
        return "bilanço/borç tarafı zayıf — dikkat"
    return "—"


def format_fund_score_table_markdown(fund: FundScoreResult) -> str:
    """Neden? paneli — markdown tablo (test / düz metin)."""
    lines = [
        "**Temel skor (4 sütun)**",
        "",
        "| Sütun | Ağırlık | Skor | Kısa okuma |",
        "|-------|---------|------|------------|",
    ]
    names = {
        "quality": "Quality (kalite)",
        "growth": "Growth (büyüme)",
        "valuation": "Valuation (değerleme)",
        "health": "Health (bilanço)",
    }
    for k in ("quality", "growth", "valuation", "health"):
        v = fund.pillars.get(k)
        w = int(PILLAR_WEIGHTS[k] * 100)
        vs = f"{v:.0f}" if v is not None else "—"
        if k in fund.partial_pillars and v is not None:
            vs += "*"
        cap = pillar_plain_caption(k, v)
        lines.append(f"| {names[k]} | %{w} | {vs} | {cap} |")

    lines.append("")
    if fund.score is None:
        lines.append(f"**Özet etiket:** {fund.label} — yeterli veri yok.")
    else:
        lines.append(f"**Özet etiket:** **{fund.label}** ({fund.score:.0f}/100)")

    scored = [(k, fund.pillars[k]) for k in names if fund.pillars.get(k) is not None]
    if scored:
        weakest = min(scored, key=lambda x: x[1])
        strongest = max(scored, key=lambda x: x[1])
        lines.append("")
        lines.append(
            f"- En güçlü: **{names[strongest[0]]}** ({strongest[1]:.0f}) — "
            f"{pillar_plain_caption(strongest[0], strongest[1])}"
        )
        lines.append(
            f"- En zayıf: **{names[weakest[0]]}** ({weakest[1]:.0f}) — "
            f"{pillar_plain_caption(weakest[0], weakest[1])}"
        )
        if weakest[0] == "valuation" and weakest[1] < 45 and strongest[1] >= 60:
            lines.append(
                "- _Okuma: şirket kalitesi/büyüme iyi olabilir ama **fiyat pahalı** "
                "tarafında — «kötü şirket» değil, «şu an pahalı»._"
            )
        if weakest[0] == "health" and weakest[1] < 45:
            lines.append(
                "- _Okuma: **bilanço/borç** tarafı zayıf — kaldıraç veya likiditeye bak._"
            )

    if fund.partial_pillars:
        lines.append("")
        lines.append(
            f"_\\* kısmi sütun (bazı alt-metrikler eksik): "
            f"{', '.join(fund.partial_pillars)}_"
        )
    if fund.asof:
        lines.append(f"- As-of: `{fund.asof}`")
    return "\n".join(lines)


def format_fund_score_table_html(fund: FundScoreResult) -> str:
    """Koyu tema için inline stilli HTML tablo (Streamlit CSS ezmez)."""
    import html as _html

    bg, bg_h, bg_alt = "#1E2329", "#2B3139", "#22272e"
    txt, muted, bd = "#EAECEF", "#848E9C", "#3a4149"
    names = {
        "quality": "Quality (kalite)",
        "growth": "Growth (büyüme)",
        "valuation": "Valuation (değerleme)",
        "health": "Health (bilanço)",
    }

    def esc(x: object) -> str:
        return _html.escape("" if x is None else str(x))

    rows_html = []
    for i, k in enumerate(("quality", "growth", "valuation", "health")):
        v = fund.pillars.get(k)
        w = int(PILLAR_WEIGHTS[k] * 100)
        vs = f"{v:.0f}" if v is not None else "—"
        if k in fund.partial_pillars and v is not None:
            vs += "*"
        cap = pillar_plain_caption(k, v)
        row_bg = bg_alt if i % 2 else bg
        rows_html.append(
            "<tr>"
            f'<td style="background:{row_bg};color:{txt};border:1px solid {bd};padding:8px 10px;">{esc(names[k])}</td>'
            f'<td style="background:{row_bg};color:{txt};border:1px solid {bd};padding:8px 10px;">%{w}</td>'
            f'<td style="background:{row_bg};color:{txt};border:1px solid {bd};padding:8px 10px;">{esc(vs)}</td>'
            f'<td style="background:{row_bg};color:{txt};border:1px solid {bd};padding:8px 10px;">{esc(cap)}</td>'
            "</tr>"
        )

    parts = [
        f'<p style="color:{txt};font-weight:600;margin:12px 0 6px;">Temel skor (4 sütun)</p>',
        f'<table style="width:100%;border-collapse:collapse;background:{bg};color:{txt};'
        f'font-size:13px;margin:0 0 10px;">',
        "<thead><tr>"
        f'<th style="background:{bg_h};color:{txt};border:1px solid {bd};padding:8px 10px;text-align:left;">Sütun</th>'
        f'<th style="background:{bg_h};color:{txt};border:1px solid {bd};padding:8px 10px;text-align:left;">Ağırlık</th>'
        f'<th style="background:{bg_h};color:{txt};border:1px solid {bd};padding:8px 10px;text-align:left;">Skor</th>'
        f'<th style="background:{bg_h};color:{txt};border:1px solid {bd};padding:8px 10px;text-align:left;">Kısa okuma</th>'
        "</tr></thead>",
        f"<tbody>{''.join(rows_html)}</tbody></table>",
    ]
    if fund.score is None:
        parts.append(
            f'<p style="color:{txt};"><b>Özet etiket:</b> {esc(fund.label)} — yeterli veri yok.</p>'
        )
    else:
        parts.append(
            f'<p style="color:{txt};"><b>Özet etiket:</b> <b>{esc(fund.label)}</b> '
            f"({fund.score:.0f}/100)</p>"
        )

    scored = [(k, fund.pillars[k]) for k in names if fund.pillars.get(k) is not None]
    if scored:
        weakest = min(scored, key=lambda x: x[1])
        strongest = max(scored, key=lambda x: x[1])
        parts.append(
            f'<ul style="color:{txt};font-size:13px;margin:6px 0 10px;padding-left:18px;">'
            f"<li>En güçlü: <b>{esc(names[strongest[0]])}</b> ({strongest[1]:.0f}) — "
            f"{esc(pillar_plain_caption(strongest[0], strongest[1]))}</li>"
            f"<li>En zayıf: <b>{esc(names[weakest[0]])}</b> ({weakest[1]:.0f}) — "
            f"{esc(pillar_plain_caption(weakest[0], weakest[1]))}</li>"
        )
        if weakest[0] == "valuation" and weakest[1] < 45 and strongest[1] >= 60:
            parts.append(
                "<li><i>Okuma: kalite/büyüme iyi olabilir ama <b>fiyat pahalı</b> "
                "tarafında — kötü şirket değil, şu an pahalı.</i></li>"
            )
        if weakest[0] == "health" and weakest[1] < 45:
            parts.append(
                "<li><i>Okuma: <b>bilanço/borç</b> tarafı zayıf — kaldıraç/likiditeye bak.</i></li>"
            )
        parts.append("</ul>")
    if fund.partial_pillars:
        parts.append(
            f'<p style="color:{muted};font-size:12px;">* kısmi sütun: '
            f"{esc(', '.join(fund.partial_pillars))}</p>"
        )
    if fund.asof:
        parts.append(f'<p style="color:{muted};font-size:12px;">As-of: {esc(fund.asof)}</p>')
    return "\n".join(parts)


def format_fund_score_markdown(fund: FundScoreResult) -> str:
    """Geriye uyum — tablo formatı."""
    return format_fund_score_table_markdown(fund)


def format_dual_line(
    tech_aksiyon: str,
    tech_skor: Optional[float],
    fund: FundScoreResult,
) -> str:
    ts = f"{tech_skor:.0f}" if tech_skor is not None else "—"
    if fund.score is None:
        return f"Teknik: {tech_aksiyon} ({ts}) | Temel: YETERSİZ"
    yorum = dual_axis_comment(tech_aksiyon, fund.label)
    return (
        f"Teknik: {tech_aksiyon} ({ts}) | "
        f"Temel: {fund.label} ({fund.score:.0f}) → {yorum}"
    )


def build_peer_ctx_for_symbol(
    sym: str,
    h: Any,
    cache: Dict[str, dict],
    hisseler: Iterable[Any],
    *,
    mode: str = "live",
) -> Dict[str, Any]:
    """Peer percentile bağlamı — mode=backtest'te PE/EV peer yok."""
    ctx: Dict[str, Any] = {}
    filtered_cache = {
        k: filter_temel_for_mode(v, mode) for k, v in (cache or {}).items()
    }

    def _margin(t: dict) -> Optional[float]:
        return _f(t, "profit_margin_y", "profitMargins", "operatingMargins")

    def _lev(t: dict) -> Optional[float]:
        a = _f(t, "total_assets_y", "total_assets_q")
        l = _f(t, "total_liab_y", "total_liab_q")
        if a is None or l is None or a <= 0:
            return None
        return l / a

    maps = [
        build_peer_metric_map(hisseler, filtered_cache, _margin, metric_key="margin_pct"),
        build_peer_metric_map(hisseler, filtered_cache, _lev, metric_key="leverage_pct"),
    ]
    if mode != "backtest":
        def _pe(t: dict) -> Optional[float]:
            for k in ("trailingPE", "forwardPE"):
                v = _f(t, k)
                if v is not None and v > 0:
                    return v
            return None

        def _ev(t: dict) -> Optional[float]:
            v = _f(t, "enterpriseToEbitda")
            return v if v is not None and v > 0 else None

        maps.append(
            build_peer_metric_map(hisseler, filtered_cache, _pe, metric_key="pe_pct")
        )
        maps.append(
            build_peer_metric_map(hisseler, filtered_cache, _ev, metric_key="ev_ebitda_pct")
        )

    sym_u = (sym or "").strip().upper()
    for m in maps:
        if sym_u in m:
            ctx.update(m[sym_u])
    return ctx
