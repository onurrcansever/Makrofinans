# -*- coding: utf-8 -*-
"""Point-in-time / publish-lag — fund_score backtest look-ahead koruması."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional, Set, Union

QUARTER_PUBLISH_LAG_DAYS = 45
ANNUAL_PUBLISH_LAG_DAYS = 90

# Yahoo .info anlık — backtest'te YASAK
LIVE_ONLY_FIELDS: Set[str] = {
    "trailingPE",
    "forwardPE",
    "pegRatio",
    "priceToBook",
    "priceToSalesTrailing12Months",
    "enterpriseToEbitda",
    "enterpriseValue",
    "marketCap",
    "currentPrice",
    "regularMarketPrice",
    "targetMeanPrice",
    "recommendationKey",
    "numberOfAnalystOpinions",
    "strongBuy",
    "buy",
    "hold",
    "sell",
    "strongSell",
    "al_sayi",
    "earningsGrowth",
    "revenueGrowth",
    # .info snapshot (restatement / anlık)
    "returnOnEquity",
    "returnOnAssets",
    "grossMargins",
    "operatingMargins",
    "profitMargins",
    "currentRatio",
    "quickRatio",
    "debtToEquity",
    "interestCoverage",
    "totalDebt",
    "totalCash",
    "ebitda",
}

# Bilanço/gelir kalemleri — publish-lag ile PIT adayı
PIT_STATEMENT_FIELDS: Set[str] = {
    "revenue_y",
    "revenue_y_prev",
    "revenue_q",
    "net_income_y",
    "net_income_q",
    "fcf_y",
    "fcf_q",
    "profit_margin_y",
    "total_assets_y",
    "total_liab_y",
    "total_assets_q",
    "total_liab_q",
    "investing_y",
    "financing_y",
}

METRIC_CLASS = {
    **{k: "excluded_live_only" for k in LIVE_ONLY_FIELDS},
    **{k: "publish_lag" for k in PIT_STATEMENT_FIELDS},
}


def _as_date(d: Union[date, datetime, str]) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()


def available_asof(
    period_end: Union[date, datetime, str],
    *,
    annual: bool = False,
    lag_days: Optional[int] = None,
) -> date:
    pe = _as_date(period_end)
    lag = lag_days
    if lag is None:
        lag = ANNUAL_PUBLISH_LAG_DAYS if annual else QUARTER_PUBLISH_LAG_DAYS
    return pe + timedelta(days=int(lag))


def period_visible_at(
    asof: Union[date, datetime, str],
    period_end: Union[date, datetime, str],
    *,
    annual: bool = False,
) -> bool:
    return available_asof(period_end, annual=annual) <= _as_date(asof)


def filter_temel_for_mode(temel: Optional[dict], mode: str) -> dict:
    if not temel:
        return {}
    if mode != "backtest":
        return dict(temel)
    return {k: v for k, v in temel.items() if k not in LIVE_ONLY_FIELDS}


def assert_no_live_only(keys: Iterable[str]) -> List[str]:
    return sorted({k for k in keys if k in LIVE_ONLY_FIELDS})
