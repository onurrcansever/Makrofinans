# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict, List, TYPE_CHECKING

import logging

import pandas as pd

from signal_engine.config.loader import SignalConfig, load_signal_config
from signal_engine.data.bars import (
    BarSeries,
    asset_class_for,
    benchmark_symbol,
    settlement_asof,
    truncate_bars_to_asof,
)
from signal_engine.decisions.history import get_prev_decision, update_decision_history
from signal_engine.decisions.state_machine import LEVEL_LABELS, decide, hysteresis_panel_note
from signal_engine.entry.levels import compute_entry
from signal_engine.factors.compute import (
    liquidity_factor,
    mean_reversion_factor,
    relative_strength_factor,
    trend_factor,
    volatility_factor,
)
from signal_engine.regime.classifier import classify_regime
from signal_engine.regime.history import update_regime_history
from signal_engine.scoring.composite import CompositeResult, composite_score, rank_composites
from signal_engine.scoring.sparkline import compute_score_sparkline
from signal_engine.data.etf_quality import etf_meta

if TYPE_CHECKING:
    from stock_scanner import HisseAnaliz

_log = logging.getLogger(__name__)


def _close_al(df: pd.DataFrame, sembol: str) -> pd.Series:
    return BarSeries.from_df(df, sembol).close


def decision_persist_eligible(h: "HisseAnaliz", bars: BarSeries) -> bool:
    """Karantina / yetersiz veri — karar geçmişine YAZILMAZ."""
    return not (
        getattr(h, "veri_quarantine", False)
        or bars.bars < 30
        or bars.quarantine
    )


def _makro_karar_tavan(
    code: str,
    makro_rejim: str,
    gates: list,
) -> str:
    """
    Portföy makro rejimi — KRIZ/EM_STRES'te yeni AL yasak (endeks/TEFAS ile uyum).
    Skor motoruna dokunmaz; yalnızca nihai karar kodunu tavanlar.
    """
    rejim = (makro_rejim or "").upper()
    if rejim not in ("KRIZ", "EM_STRES"):
        return code
    if code in ("STRONG_BUY", "BUY"):
        gates.append(f"Makro {rejim}: AL/GÜÇLÜ AL → İZLE (yeni risk yok)")
        return "WATCH"
    return code


def signal_engine_v2_uygula(
    hisseler: List["HisseAnaliz"],
    df: pd.DataFrame,
    *,
    cfg: SignalConfig | None = None,
    profil_risk: str = "orta",
    persist_decision_history: bool = False,
    makro_rejim: str = "",
) -> None:
    """V2 sinyal motoru — HisseAnaliz üzerine signal_v2_* yazar.

    persist_decision_history: yalnızca ana tarama True — favoriler/testler False (sadece okur).
    makro_rejim: tahsis rejimi (KRIZ/EM_STRES → AL tavanı).
    """
    cfg = cfg or load_signal_config()
    risk_limit = {"dusuk": 22.0, "orta": 32.0, "yuksek": 45.0}.get(profil_risk, 32.0)

    bench_cache: Dict[str, BarSeries] = {}
    prepared: List[tuple] = []

    for h in hisseler:
        bars_raw = BarSeries.from_df(df, h.sembol)
        h._signal_asset_class = asset_class_for(h, cfg)
        bm_sym = benchmark_symbol(h, cfg)
        if bm_sym:
            if bm_sym not in bench_cache:
                bench_cache[bm_sym] = BarSeries.from_df(df, bm_sym)
            bench = bench_cache[bm_sym]
            asof = settlement_asof(bars_raw, bench, df)
            bars = truncate_bars_to_asof(bars_raw, asof) if asof is not None else bars_raw
            if asof is not None:
                bench = truncate_bars_to_asof(bench, asof)
        else:
            # Emtia: benchmark yok — asof yalnızca varlık barı
            bench = bars_raw
            bars = bars_raw

        meta = etf_meta(getattr(h, "isin", "") or "")
        if getattr(h, "_signal_asset_class", "") == "emtia" or not bm_sym:
            from signal_engine.factors.compute import FactorResult
            rel = FactorResult(50.0, True, "emtia: rel nötr (benchmark yok)")
        else:
            rel = relative_strength_factor(
                bars, bench, df=df, bench_symbol=bm_sym,
            )
        factors = {
            "trend": trend_factor(bars),
            "mean_reversion": mean_reversion_factor(bars),
            "volatility": volatility_factor(bars, risk_limit=risk_limit),
            "relative_strength": rel,
            "liquidity": liquidity_factor(bars, isin=getattr(h, "isin", "") or "", etf_meta=meta),
        }
        score, used, total = composite_score(factors, cfg)
        comp = CompositeResult(
            score=round(score, 1),
            percentile=50.0,
            factors_used=used,
            factors_total=total,
            factor_scores={k: round(v.score, 1) for k, v in factors.items()},
            factor_details={k: v.detail for k, v in factors.items()},
        )
        regime = classify_regime(bars, cfg)
        try:
            entry = compute_entry(bars, regime.regime, cfg)
        except Exception as exc:
            from signal_engine.entry.levels import EntryLevel, EntrySanityError
            if isinstance(exc, EntrySanityError):
                h.veri_quarantine = True
                h.veri_hatasi = str(exc)[:120]
                entry = EntryLevel(None, "—", None, False, str(exc)[:120])
            else:
                raise
        if (
            not h.veri_quarantine
            and h.fiyat
            and entry.price
            and h.quote_currency
            and entry.settlement_currency
        ):
            if h.quote_currency != entry.settlement_currency:
                h.veri_quarantine = True
                h.veri_hatasi = (
                    f"Para birimi uyumsuz: spot {h.quote_currency} vs seviye {entry.settlement_currency}"
                )
            else:
                dist_live = abs(entry.price / float(h.fiyat) - 1.0)
                if dist_live > 0.15:
                    h.veri_quarantine = True
                    h.veri_hatasi = (
                        f"Al/spot sapması %{dist_live * 100:.1f} — settlement tutarsızlığı"
                    )
        bar_date = ""
        if not bars.close.empty:
            bar_date = str(bars.close.index[-1].date())
        prev, cold, cold_reason = get_prev_decision(h.sembol, asof=bar_date)
        if cold and cold_reason and "önceki karar yok" not in cold_reason:
            _log.info("%s histerezis %s", h.sembol, cold_reason)
        prepared.append((
            h, comp, regime, entry, bars, bench, meta,
            prev, cold, cold_reason, bar_date,
        ))

    rank_composites([(h, c) for h, c, *_ in prepared])

    # Sektör F/K peer — tek geçiş (gate soft bayrağı)
    from signal_engine.quality.peer_valuation import PeerValuation, build_peer_valuation_map

    peer_map: Dict[str, PeerValuation] = {}
    temel_cache: Dict = {}
    try:
        from temel_veri import yukle_cache

        temel_cache = yukle_cache()
        peer_map = build_peer_valuation_map(hisseler, temel_cache)
    except Exception:
        peer_map = {}
        temel_cache = {}

    for h, comp, regime, entry, bars, bench, meta, prev, cold, cold_reason, bar_date in prepared:
        decision = decide(comp.score, comp.percentile, regime, entry, cfg, prev_code=prev)
        gates = list(decision.gates or [])
        code = _makro_karar_tavan(decision.code, makro_rejim, gates)
        sym_u = (h.sembol or "").strip().upper()
        peer = peer_map.get(sym_u)
        if peer is not None:
            h.signal_v2_peer_val = peer.as_dict() if hasattr(peer, "as_dict") else peer
            h.signal_v2_peer_note = getattr(peer, "note", "") or ""
        else:
            h.signal_v2_peer_val = None
            h.signal_v2_peer_note = ""
        # Temel finans kapısı — cache hit; yoksa no-op (yanlış İZLE yok)
        try:
            from signal_engine.quality.fund_gate import apply_fund_gate_to_code

            temel = temel_cache.get(sym_u, {}) if temel_cache else {}
            if not temel:
                from temel_veri import yukle_cache

                temel = yukle_cache().get(sym_u, {})
            code = apply_fund_gate_to_code(code, temel, h, gates, peer=peer)
        except Exception:
            pass
        label = LEVEL_LABELS.get(code, decision.label)
        why = decision.why
        if code != decision.code:
            why = f"{why} · nihai {decision.code}→{code}"

        h.signal_v2_score = comp.score
        h.signal_v2_percentile = comp.percentile
        h.signal_v2_regime = regime.regime
        h.signal_v2_regime_detail = regime.detail
        h.signal_v2_decision = label
        h.signal_v2_code = code
        h.signal_v2_why = why
        h.signal_v2_decision_gates = gates
        h.signal_v2_fund_note = next(
            (g for g in gates if str(g).startswith("Temel kapı")),
            "",
        )
        h.signal_v2_prev_code = prev
        h.signal_v2_cold_start = cold
        h.signal_v2_cold_reason = cold_reason
        h.signal_v2_hysteresis_note = hysteresis_panel_note(
            comp.score, code, prev,
            cold_start=cold, cold_reason=cold_reason, cfg=cfg,
        )
        h.signal_v2_al_price = entry.price
        h.signal_v2_al_method = entry.method
        h.signal_v2_al_p_fill = entry.p_fill_90d
        h.signal_v2_dca = entry.dca_preferred
        h.signal_v2_data = f"{comp.factors_used}/{comp.factors_total}"
        h.signal_v2_factors = comp.factor_scores
        h.signal_v2_factor_details = comp.factor_details
        h.signal_v2_sparkline = compute_score_sparkline(bars, bench, cfg, risk_limit=risk_limit)
        if meta:
            h.signal_v2_etf_quality = (
                f"AUM ~{meta.get('aum_bn_eur')}bn EUR · TER {meta.get('ter_pct')}%"
            )

        days, fresh = update_regime_history(h.sembol, regime.regime)
        h.signal_v2_regime_days = days
        h.signal_v2_regime_fresh = fresh
        h.signal_v2_al_secondary = entry.secondary_price
        h.signal_v2_al_secondary_p_fill = entry.secondary_p_fill
        h.signal_v2_spot_near = entry.spot_near
        h.signal_v2_spot_distance_pct = entry.spot_distance_pct

        if not decision_persist_eligible(h, bars):
            continue
        h.skor = comp.score
        h.bilesik_skor = comp.score
        h.alim_uygun = _map_alim_uygun(code)
        h.alim_uygun_not = why[:120]

        if entry.price:
            h.yonetici_alim = entry.price
        h.yonetici_ozet = f"{label} · {regime.regime}"

        if persist_decision_history and bar_date:
            update_decision_history(
                h.sembol, code, comp.score,
                asof=bar_date,
            )


def _map_alim_uygun(code: str) -> str:
    # WATCH = İZLE (SINIRLI/Dikkat değil — yumuşak alım çağrışımı yok)
    return {
        "STRONG_BUY": "UYGUN",
        "BUY": "UYGUN",
        "WATCH": "IZLE",
        "WAIT": "IZLE",
        "REDUCE": "UYGUN_DEGIL",
    }.get(code, "IZLE")
