#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5Y signal backtest raporu üretir (JSON + MD)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from signal_engine.backtest.full_report import ci_check, generate_report, write_report


def main() -> int:
    report = generate_report()
    path = write_report(report)
    print(f"Wrote {path}")
    md = path.with_suffix(".md")
    if md.name.endswith(".json.md"):
        md = path.parent / "signal_backtest_report.md"
    print(f"Wrote {md}")
    if not ci_check():
        print("CI check failed: config hash mismatch or lookahead_ok=false", file=sys.stderr)
        return 1
    print("CI check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
