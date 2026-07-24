#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""+1 ekstra flip dağılımı — base'te yok, siki'de var olan olayları listele."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from signal_engine.backtest.trend_short_mom_backtest import (  # noqa: E402
    DEFAULT_SYMBOLS,
    REPORT_DIR,
    download_closes,
    flip_diff_report,
)


def main() -> int:
    print("Downloading…")
    closes, bench = download_closes(DEFAULT_SYMBOLS, period="5y")
    print(f"symbols={len(closes)}")
    diff = flip_diff_report(closes, bench, arm="siki", step=5)
    out = REPORT_DIR / "trend_short_mom_flip_diff.json"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")

    md = REPORT_DIR / "trend_short_mom_flip_diff.md"
    lines = [
        "# Kısa mom — ekstra flip dağılımı (siki vs base)",
        "",
        f"Ekstra (yalnız siki): **{diff['n_extra']}**",
        f"Paylaşılan: {diff['n_shared']} · yalnız base: {diff['n_base_only']}",
        "",
        "## Ekstra olaylar",
        "",
    ]
    for e in diff["extra_vs_base"]:
        lines.append(
            f"- **{e['symbol']}** `{e['date']}` "
            f"lvl {e['from']}→{e['to']} ({e['direction']}) skor={e['score']}"
        )
    if not diff["extra_vs_base"]:
        lines.append("_Ekstra flip yok._")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(md.read_text(encoding="utf-8"))
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
