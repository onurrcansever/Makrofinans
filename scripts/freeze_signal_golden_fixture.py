#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2026-07-15 kapanışına göre Signal Engine golden fixture üretir."""
from __future__ import annotations

import json
import pickle
import sys
import unittest.mock
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from decision_engine import PiyasaVerisi  # noqa: E402
from etf_universe import REVOLUT_ETFLER  # noqa: E402
from macro_data import MacroSnapshot  # noqa: E402
from signal_engine.data.bars import _extract_volume, momentum_12_1, BarSeries  # noqa: E402
from signal_engine.pipeline import signal_engine_v2_uygula  # noqa: E402
from signal_engine.decisions.history import clear_decision_history  # noqa: E402
from stock_scanner import _extract_close_raw, _hisse_analiz, _indir  # noqa: E402

ASOF = pd.Timestamp("2026-07-15")
SYMS = [
    "AMAT", "CSCO", "MSFT", "EQQQ.L", "CSPX.L", "IS3N.DE", "VEUR.L", "VWRL.L",
    "VUAA.L", "VUSA.L", "VUKE.L",
    "^GSPC", "^IXIC",
    "GBPUSD=X", "EURUSD=X", "USDTRY=X", "EURTRY=X",
]
OUT_PKL = ROOT / "tests/fixtures/signal_golden_20260715.pkl"
OUT_JSON = ROOT / "tests/fixtures/signal_golden_20260715.json"


def _pin_snap(df: pd.DataFrame, end: pd.Timestamp) -> dict:
    from signal_engine.data.bars import _extract_close

    ut = _extract_close(df, "USDTRY=X").loc[:end]
    et = _extract_close(df, "EURTRY=X").loc[:end]
    gbp = _extract_close(df, "GBPUSD=X").loc[:end]
    return {
        "eur_try": round(float(et.iloc[-1]), 4),
        "usd_try": round(float(ut.iloc[-1]), 4),
        "gbp_usd": round(float(gbp.iloc[-1]), 4),
        "fx_asof": str(end.date()),
        "fx_source": "Yahoo EURTRY=X / USDTRY=X / GBPUSD=X (fixture close)",
    }


def _truncate_df(df: pd.DataFrame, end: pd.Timestamp) -> pd.DataFrame:
    frames = {}
    for sym in SYMS:
        raw = _extract_close_raw(df, sym)
        if raw.empty:
            continue
        s = raw.loc[raw.index <= end].astype(float)
        frames[(sym, "Close")] = s
        vol = _extract_volume(df, sym)
        if vol is not None and not vol.empty:
            vol = vol.loc[vol.index <= end].reindex(s.index).fillna(0.0)
        else:
            vol = pd.Series(0.0, index=s.index)
        frames[(sym, "Volume")] = vol.astype(float)
    return pd.DataFrame(frames)


def main() -> None:
    raw = _indir(SYMS, period="2y")
    df = _truncate_df(raw, ASOF)
    snap_vals = _pin_snap(df, ASOF)
    snap = MacroSnapshot(veri=PiyasaVerisi(
        eur_try=snap_vals["eur_try"],
        usd_try=snap_vals["usd_try"],
    ))
    etf = {x[0]: x for x in REVOLUT_ETFLER}
    golden = {}
    clear_decision_history()

    for sym in ["AMAT", "CSCO", "MSFT", "EQQQ.L", "IS3N.DE", "VEUR.L"]:
        if sym in etf:
            t = etf[sym]
            h = _hisse_analiz(
                df, t[0], t[1], "ETF", t[2], "NOTR", snap,
                isin=t[3], revolut_ticker=t[4], varlik_turu="etf",
            )
        else:
            h = _hisse_analiz(df, sym, sym, "NASDAQ", "teknoloji", "NOTR", snap)
        with unittest.mock.patch("signal_engine.data.live_quote.get_live_quote", return_value=None):
            signal_engine_v2_uygula([h], df, profil_risk="orta")
        row = {
            "score": round(h.signal_v2_score),
            "decision": h.signal_v2_decision,
            "code": h.signal_v2_code,
            "factors": {k: round(v, 1) for k, v in h.signal_v2_factors.items()},
            "quote_currency": h.quote_currency,
        }
        if sym == "EQQQ.L":
            bars = BarSeries.from_df(df, sym)
            mom = momentum_12_1(bars.close)
            from fiyat_para import tablo_getiri, tablo_fiyat, try_per_gbp
            from signal_engine.data.bars import _extract_close, pct_change_n

            ut = _extract_close(df, "USDTRY=X")
            gbp_fx = _extract_close(df, "GBPUSD=X")
            et = _extract_close(df, "EURTRY=X")
            d1y = pct_change_n(bars.close, 252)
            d1a = pct_change_n(bars.close, 21)
            tl_1y = tablo_getiri(
                d1y, "TL", 252, et, ut, gbp_seri=gbp_fx, asset_pb="GBP",
                bar_dates=bars.close.index,
            )
            tl_1a = tablo_getiri(
                d1a, "TL", 21, et, ut, gbp_seri=gbp_fx, asset_pb="GBP",
                bar_dates=bars.close.index,
            )
            tl_12_1 = ((1 + tl_1y / 100) / (1 + tl_1a / 100) - 1) * 100 if tl_1y and tl_1a else None
            gbp_px = float(bars.close.iloc[-1])
            tl_px = tablo_fiyat(
                gbp_px, "TL", float(et.iloc[-1]), float(ut.iloc[-1]),
                sembol=sym, quote_currency="GBP",
                gbp_usd=float(gbp_fx.iloc[-1]),
            )
            usd_1y = tablo_getiri(
                d1y, "USD", 252, et, ut, gbp_seri=gbp_fx, asset_pb="GBP",
                bar_dates=bars.close.index,
            )
            row.update({
                "al_price_settlement": h.signal_v2_al_price,
                "spot_settlement": h.fiyat,
                "spot_near": h.signal_v2_spot_near,
                "momentum_12_1_gbp_pct": round(mom, 4) if mom is not None else None,
                "momentum_12_1_tl_pct": round(tl_12_1, 2) if tl_12_1 is not None else None,
                "getiri_1y_tl_pct": tl_1y,
                "getiri_1y_usd_pct": usd_1y,
                "try_per_gbp": round(try_per_gbp(float(ut.iloc[-1]), float(gbp_fx.iloc[-1])), 2),
            })
        golden[sym] = row

    OUT_PKL.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PKL.open("wb") as f:
        pickle.dump({"asof": str(ASOF.date()), "df": df, "snap": snap_vals, "golden": golden}, f)
    with OUT_JSON.open("w", encoding="utf-8") as f:
        payload = {
            "asof": str(ASOF.date()),
            "snap": snap_vals,
            "golden": golden,
            "hysteresis": {
                "EQQQ.L": [
                    {"score": 68, "code": "BUY", "decision": "AL"},
                    {"score": 64, "prev": "BUY", "code": "BUY", "decision": "AL"},
                ],
            },
        }
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"Wrote {OUT_PKL} and {OUT_JSON}")


if __name__ == "__main__":
    main()
