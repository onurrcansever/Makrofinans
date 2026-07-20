#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Veri bütünlüğü — takvim delikleri, eksik bar, indirme boşlukları."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from signal_engine.data.bars import BarSeries, _extract_close  # noqa: E402
from stock_scanner import _indir  # noqa: E402

# Aynı borsa — takvimleri birebir olmalı
LSE_USD = ["CSPX.L", "VUAA.L"]
LSE_GBP = ["EQQQ.L", "VUSA.L", "VUKE.L", "VEUR.L", "VWRL.L"]
US = ["AMAT", "MSFT", "CSCO"]
BIST = ["FROTO.IS", "EREGL.IS", "THYAO.IS"]
FX = ["EURTRY=X", "USDTRY=X", "GBPUSD=X", "EURUSD=X", "CHFUSD=X", "^GSPC"]


def _dates(df, sym) -> pd.DatetimeIndex:
    bars = BarSeries.from_df(df, sym)
    return bars.close.index


def calendar_holes(df, group: list, label: str) -> dict:
    """Grup içi simetrik fark — kimde hangi gün var/yok."""
    date_sets = {}
    for s in group:
        idx = _dates(df, s)
        date_sets[s] = set(pd.Timestamp(d).normalize() for d in idx) if len(idx) else set()
    union = set()
    for ds in date_sets.values():
        union |= ds
    report = {"group": label, "symbols": {}, "pairwise_extra": []}
    for s, ds in date_sets.items():
        missing = sorted(union - ds)
        report["symbols"][s] = {
            "bars": len(ds),
            "d1": str(max(ds).date()) if ds else None,
            "missing_vs_union": [str(d.date()) for d in missing[-20:]],
            "n_missing_vs_union": len(missing),
        }
    # pairwise
    syms = list(date_sets)
    for i, a in enumerate(syms):
        for b in syms[i + 1:]:
            only_a = sorted(date_sets[a] - date_sets[b])
            only_b = sorted(date_sets[b] - date_sets[a])
            if only_a or only_b:
                report["pairwise_extra"].append({
                    "a": a, "b": b,
                    "only_a": [str(d.date()) for d in only_a],
                    "only_b": [str(d.date()) for d in only_b],
                })
    return report


def download_gaps(df, syms: list) -> list:
    out = []
    for s in syms:
        raw = _extract_close(df, s)
        bars = BarSeries.from_df(df, s)
        if raw.empty or bars.bars == 0:
            out.append({
                "symbol": s,
                "status": "EMPTY",
                "raw_bars": len(raw),
                "settlement_bars": bars.bars,
                "quarantine": bars.quarantine,
                "reason": bars.quarantine_reason or "no bars",
            })
        elif bars.quarantine:
            out.append({
                "symbol": s,
                "status": "QUARANTINE",
                "raw_bars": len(raw),
                "settlement_bars": bars.bars,
                "quarantine": True,
                "reason": bars.quarantine_reason,
            })
    return out


def asof_alignment(df) -> dict:
    gspc = _extract_close(df, "^GSPC")
    out = {"gspc_d1": str(gspc.index[-1].date()) if len(gspc) else None, "ahead": []}
    for s in LSE_GBP + LSE_USD:
        idx = _dates(df, s)
        if len(idx) and len(gspc) and idx[-1].normalize() > gspc.index[-1].normalize():
            out["ahead"].append({
                "symbol": s,
                "asset_d1": str(idx[-1].date()),
                "gspc_d1": str(gspc.index[-1].date()),
            })
    return out


def main() -> None:
    syms = list(dict.fromkeys(LSE_USD + LSE_GBP + US + BIST + FX))
    print(f"Downloading {len(syms)} symbols…")
    df = _indir(syms, period="2y")
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "n_symbols": len(syms),
        "download_gaps": download_gaps(df, syms),
        "lse_usd_calendar": calendar_holes(df, LSE_USD, "LSE_USD"),
        "lse_gbp_calendar": calendar_holes(df, LSE_GBP, "LSE_GBP"),
        "asof_alignment": asof_alignment(df),
    }

    out_json = ROOT / "signal_engine/reports/data_integrity_report.json"
    out_md = ROOT / "signal_engine/reports/data_integrity_report.md"
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Veri bütünlüğü raporu",
        "",
        f"Üretim: `{payload['generated_at']}`",
        "",
        "## 1. İndirme / karantina boşlukları",
        "",
    ]
    gaps = payload["download_gaps"]
    if not gaps:
        lines.append("Yok — tüm semboller settlement bar üretti.")
    else:
        lines.append("| Sembol | Durum | Ham | Settlement | Neden |")
        lines.append("|--------|-------|-----|------------|-------|")
        for g in gaps:
            lines.append(
                f"| {g['symbol']} | {g['status']} | {g['raw_bars']} | "
                f"{g['settlement_bars']} | {g['reason'][:60]} |"
            )
    lines.extend(["", "## 2. LSE takvim delikleri (aynı borsa ≠ aynı bar seti)", ""])
    for block in (payload["lse_usd_calendar"], payload["lse_gbp_calendar"]):
        lines.append(f"### {block['group']}")
        lines.append("")
        lines.append("| Sembol | Bars | d1 | Union'da eksik |")
        lines.append("|--------|------|----|----------------|")
        for s, info in block["symbols"].items():
            miss = ", ".join(info["missing_vs_union"][:5]) or "—"
            if info["n_missing_vs_union"] > 5:
                miss += f" (+{info['n_missing_vs_union']-5})"
            lines.append(f"| {s} | {info['bars']} | {info['d1']} | {miss} |")
        lines.append("")
        if block["pairwise_extra"]:
            lines.append("Çift farklar:")
            for p in block["pairwise_extra"]:
                lines.append(
                    f"- `{p['a']}` vs `{p['b']}`: "
                    f"only_a={p['only_a'] or '—'} · only_b={p['only_b'] or '—'}"
                )
            lines.append("")

    lines.extend(["## 3. LSE-ahead (asset d1 > ^GSPC d1)", ""])
    aa = payload["asof_alignment"]
    lines.append(f"^GSPC d1: `{aa['gspc_d1']}`")
    if not aa["ahead"]:
        lines.append("LSE-ahead yok (veya ABD seansı açık).")
    else:
        for a in aa["ahead"]:
            lines.append(f"- **{a['symbol']}** {a['asset_d1']} > GSPC {a['gspc_d1']}")
    lines.extend([
        "",
        "## Sonuç",
        "",
        "- Aynı borsa takvimi varsayımı **veri delikleri yüzünden bozulabilir** "
        "(ör. CSPX vs VUAA `2026-03-06`).",
        "- Skor motoru `settlement_asof` ile LSE-ahead'i keser; getiri pencereleri "
        "sembolün kendi bar takvimini kullanır → FX katsayısı sembol bazında farklı olabilir.",
        "- FROTO tipi boşluk: ham seri yok → `VERI_YOK` → teknik filtre dışı.",
        "",
    ])
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_json}")
    print(f"Wrote {out_md}")
    print(f"download_gaps={len(gaps)} lse_ahead={len(aa['ahead'])}")


if __name__ == "__main__":
    main()
