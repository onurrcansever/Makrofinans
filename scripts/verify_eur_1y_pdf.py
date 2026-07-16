#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ürün yolu: EQQQ/AMAT/VEUR EUR 1Y + mini PDF — native≠EUR kanıtı."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fiyat_para import getiri_kur_ayarli, tablo_getiri  # noqa: E402
from report_pdf import hisse_etf_tablo_pdf_olustur  # noqa: E402
from signal_engine.data.bars import BarSeries, pct_change_n, _extract_close  # noqa: E402
from stock_scanner import _indir  # noqa: E402


SYMS = [
    "AMAT", "EQQQ.L", "VEUR.L",
    "EURTRY=X", "USDTRY=X", "GBPUSD=X", "EURUSD=X",
]


def main() -> None:
    # Settlement asof: ABD bench günü (LSE-ahead kes)
    raw = _indir(SYMS + ["^GSPC"], period="2y")
    gspc = _extract_close(raw, "^GSPC")
    asof = gspc.index[-1]
    df = raw.loc[:asof]

    et = _extract_close(df, "EURTRY=X")
    ut = _extract_close(df, "USDTRY=X")
    gbp = _extract_close(df, "GBPUSD=X")

    rows = []
    for sym, pb in [("AMAT", "USD"), ("EQQQ.L", "GBP"), ("VEUR.L", "GBP")]:
        bars = BarSeries.from_df(df, sym)
        d1y = pct_change_n(bars.close, 252)
        eur = getiri_kur_ayarli(
            d1y, pb, "EUR", 252, et, ut, gbp, bar_dates=bars.close.index,
        )
        # Ürün fonksiyonu
        tablo = tablo_getiri(
            d1y, "EUR", 252, et, ut, gbp_seri=gbp,
            asset_pb=pb, bar_dates=bars.close.index,
        )
        assert eur == tablo
        assert abs(eur - d1y) > 0.5, f"{sym}: hâlâ native!"
        rows.append({
            "Karar": "—",
            "Sembol": sym,
            "Hisse/ETF": sym,
            "Fiyat (EUR)": "—",
            "1Y % (EUR)": eur,
            "native %": round(d1y, 2),
            "asset_pb": pb,
            "d1": str(bars.close.index[-1].date()),
            "Al": "—",
            "Rejim": "—",
            "Veri": "5/5 ✓",
            "RSI": None,
            "Skor": "—",
        })
        print(f"{sym}: native={d1y:.2f}  EUR_1Y={eur}  d1={bars.close.index[-1].date()}")

    out = ROOT / "signal_engine/reports/verify_eur_1y.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf = hisse_etf_tablo_pdf_olustur(
        pd.DataFrame(rows),
        gosterim_pb="EUR",
        profil_ozet="doğrulama — settlement asof",
        piyasa_filtre=["NASDAQ", "ETF"],
        sinyal_filtre=["(filtre yok — doğrulama)"],
    )
    out.write_bytes(pdf)
    print(f"Wrote {out} ({len(pdf)} bytes)")
    # Beklenen pin (15 Tem fixture bandı)
    amat = next(r for r in rows if r["Sembol"] == "AMAT")["1Y % (EUR)"]
    eqqq = next(r for r in rows if r["Sembol"] == "EQQQ.L")["1Y % (EUR)"]
    veur = next(r for r in rows if r["Sembol"] == "VEUR.L")["1Y % (EUR)"]
    print(f"ASSERT band: AMAT~202 EQQQ~30 VEUR~20 | got {amat} {eqqq} {veur}")


if __name__ == "__main__":
    main()
