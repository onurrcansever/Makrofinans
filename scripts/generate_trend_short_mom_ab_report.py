#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trend kısa-momentum A/B — çalıştır, verdict yaz, isteğe bağlı flag aç."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from signal_engine.backtest.trend_short_mom_backtest import (  # noqa: E402
    DEFAULT_SYMBOLS,
    download_closes,
    generate_short_mom_ab_report,
    write_report,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Trend short-mom A/B backtest")
    p.add_argument("--symbols", nargs="*", default=None)
    p.add_argument("--period", default="5y")
    p.add_argument("--step", type=int, default=5)
    p.add_argument(
        "--apply-if-ok",
        action="store_true",
        help="Verdict bağla ise signal_config.yaml short_momentum.enabled=true yap",
    )
    args = p.parse_args()

    symbols = args.symbols or DEFAULT_SYMBOLS
    print(f"Downloading {len(symbols)} symbols ({args.period})…")
    closes, bench = download_closes(symbols, period=args.period)
    print(f"OK bars≥300: {len(closes)}")
    if len(closes) < 10:
        print("Yetersiz sembol", file=sys.stderr)
        return 1

    print("Walking A/B…")
    report = generate_short_mom_ab_report(closes, bench, step=args.step)
    path = write_report(report)
    print(f"Report: {path}")
    print(f"Verdict: {report.verdict}"
          + (f" (preset={report.chosen_preset})" if report.chosen_preset else ""))
    for r in report.reasons:
        print(f"  · {r}")

    if args.apply_if_ok and report.verdict == "bağla" and report.chosen_preset:
        cfg_path = ROOT / "signal_engine" / "config" / "signal_config.yaml"
        text = cfg_path.read_text(encoding="utf-8")
        text2 = text
        if "enabled: false" in text2:
            text2 = text2.replace(
                "short_momentum:\n  enabled: false",
                "short_momentum:\n  enabled: true",
                1,
            )
        # preset satırını seçilene çek
        import re
        text2 = re.sub(
            r"(short_momentum:\n  enabled: true\n  preset: )\w+",
            rf"\1{report.chosen_preset}",
            text2,
            count=1,
        )
        if text2 != text:
            cfg_path.write_text(text2, encoding="utf-8")
            print(f"→ short_momentum.enabled=true preset={report.chosen_preset}")
        else:
            print("→ yaml güncellenemedi")
    elif args.apply_if_ok:
        print("→ Flag açılmadı (verdict bağlama)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
