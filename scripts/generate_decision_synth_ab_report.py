#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sentez A/B backtest — base decide vs synthesize_action (NÖTR + SAĞLAM senaryoları)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from signal_engine.backtest.decision_synth_backtest import (  # noqa: E402
    DEFAULT_SYMBOLS,
    REPORT_DIR,
    download_closes,
    generate_synth_ab_report,
    write_synth_ab_report,
)
from signal_engine.backtest.signal_backtest import assert_no_lookahead  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Decision synth A/B backtest")
    p.add_argument("--symbols", nargs="*", default=None)
    p.add_argument("--period", default="5y")
    p.add_argument("--step", type=int, default=5)
    args = p.parse_args()

    symbols = args.symbols or DEFAULT_SYMBOLS
    print(f"Downloading {symbols} ({args.period})…")
    closes, bench = download_closes(symbols, period=args.period)
    if not closes:
        print("No symbols with enough bars", file=sys.stderr)
        return 1

    la_ok = True
    for c in closes.values():
        la_ok = la_ok and assert_no_lookahead(c)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    combined = {
        "generated_at": None,
        "lookahead_ok": la_ok,
        "step": args.step,
        "scenarios": {},
    }

    for label in ("NÖTR", "SAĞLAM"):
        print(f"Walking fund_label={label}…")
        report = generate_synth_ab_report(
            closes, bench, step=args.step, fund_label=label, lookahead_ok=la_ok,
        )
        out = REPORT_DIR / f"decision_synth_ab_{'notr' if label == 'NÖTR' else 'saglam'}.json"
        write_synth_ab_report(report, path=out)
        print(f"  → {out.name}: {report.confidence_note}")
        combined["generated_at"] = report.generated_at
        combined["scenarios"][label] = {
            "confidence_note": report.confidence_note,
            "fund_mode": report.fund_mode,
            "aggregate": {
                k: {
                    "n": v.n,
                    "avg_ret_1m": v.avg_ret_1m,
                    "avg_ret_3m": v.avg_ret_3m,
                    "avg_ret_6m": v.avg_ret_6m,
                    "hit_rate_1m": v.hit_rate_1m,
                }
                for k, v in report.aggregate.items()
            },
            "totals": {
                "n_base_buy": sum(s.n_base_buy for s in report.symbols),
                "n_synth_buy": sum(s.n_synth_buy for s in report.symbols),
                "n_upgrade": sum(s.n_upgrade for s in report.symbols),
                "n_downgrade": sum(s.n_downgrade for s in report.symbols),
            },
        }

    # Ana özet (SAĞLAM senaryosu birincil — kullanıcıda temel skor açık)
    primary = generate_synth_ab_report(
        closes, bench, step=args.step, fund_label="SAĞLAM", lookahead_ok=la_ok,
    )
    main_path = write_synth_ab_report(
        primary, path=REPORT_DIR / "decision_synth_ab_report.json",
    )

    summary_path = REPORT_DIR / "decision_synth_ab_summary.json"
    summary_path.write_text(
        json.dumps(combined, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )

    # Birleşik MD özeti
    md_lines = [
        "# Decision Synth A/B — özet",
        "",
        f"Generated: `{combined['generated_at']}`",
        f"Lookahead OK: **{la_ok}** · step={args.step}",
        "",
        "İki senaryo: sabit `fund_label` (temel skor PIT yok — hassasiyet analizi).",
        "",
    ]
    for label, sc in combined["scenarios"].items():
        t = sc["totals"]
        md_lines.extend([
            f"## Senaryo fund_label={label}",
            "",
            sc["confidence_note"],
            "",
            f"- base_AL={t['n_base_buy']} · synth_AL={t['n_synth_buy']} · "
            f"upgrade={t['n_upgrade']} · downgrade={t['n_downgrade']}",
            "",
        ])
        agg = sc["aggregate"]
        md_lines.extend([
            "| Kol | n | 1M | 3M | Hit1M |",
            "|-----|---|----|----|-------|",
        ])
        for name, arm in agg.items():
            hit = arm["hit_rate_1m"]
            hit_s = f"{hit*100:.0f}%" if hit is not None else "—"
            a1 = f"{arm['avg_ret_1m']:.1f}%" if arm["avg_ret_1m"] is not None else "—"
            a3 = f"{arm['avg_ret_3m']:.1f}%" if arm["avg_ret_3m"] is not None else "—"
            md_lines.append(f"| {name} | {arm['n']} | {a1} | {a3} | {hit_s} |")
        md_lines.append("")

    md_lines.extend([
        "## Yorum",
        "",
        "- **NÖTR**: upgrade≈0 beklenir (sentez yükseltmesi SAĞLAM+ ister).",
        "- **SAĞLAM**: bölge teşviki (upgrade) ve uzak-giriş kesimi (downgrade) burada görünür.",
        "- Bu price-only; gerçek temel skor zamanla değişir → güven hâlâ orta.",
        "",
    ])
    (REPORT_DIR / "decision_synth_ab_report.md").write_text(
        "\n".join(md_lines), encoding="utf-8",
    )

    print(f"Wrote {main_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {REPORT_DIR / 'decision_synth_ab_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
