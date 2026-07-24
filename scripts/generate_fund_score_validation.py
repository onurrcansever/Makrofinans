#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FAZ5: fund_score_validation.md + .json üret.

Point-in-time tarihsel Yahoo filing yoksa indicative_only=true → FUND_SCORE_UI kapalı.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from signal_engine.backtest.fund_score_backtest import (  # noqa: E402
    build_validation_payload,
    metric_inventory_table,
)
from signal_engine.quality.fund_score import compute_fund_score  # noqa: E402
from signal_engine.quality.fund_score_pit import LIVE_ONLY_FIELDS  # noqa: E402
from signal_engine.quality.fund_score_ui import fund_score_ui_allowed  # noqa: E402


OUT_JSON = ROOT / "signal_engine" / "reports" / "fund_score_validation.json"
OUT_MD = ROOT / "signal_engine" / "reports" / "fund_score_validation.md"


def _probe_cache() -> tuple:
    """Mevcut temel cache üzerinde live vs backtest alan ayrımı teyidi."""
    n_sym = 0
    n_pit = 0
    n_scored_bt = 0
    live_leak = []
    try:
        from temel_veri import yukle_cache

        cache = yukle_cache() or {}
    except Exception:
        cache = {}

    for sym, t in cache.items():
        if not isinstance(t, dict) or t.get("_bos"):
            continue
        n_sym += 1
        has_stmt = any(
            t.get(k) is not None
            for k in ("revenue_y", "net_income_y", "fcf_y", "total_assets_y")
        )
        if has_stmt and (t.get("period_end_y") or t.get("period_end_q")):
            n_pit += 1
        res = compute_fund_score(t, mode="backtest")
        if res.score is not None:
            n_scored_bt += 1
        # used_fields türetilmiş; ham dict filter kontrolü
        from signal_engine.quality.fund_score_pit import filter_temel_for_mode

        filtered = filter_temel_for_mode(t, "backtest")
        leak = [k for k in filtered if k in LIVE_ONLY_FIELDS]
        if leak:
            live_leak.append({"sym": sym, "fields": leak})

    return n_sym, n_pit, n_scored_bt, live_leak


def main() -> int:
    n_sym, n_pit, n_scored_bt, live_leak = _probe_cache()
    # Kesit: cache peer grupları için kaba proxy
    n_cs = min(n_pit, 8) if n_pit else 0

    # PIT filing arşivi yok → indicative
    indicative = True
    look_ahead_clean = len(live_leak) == 0  # alan ayrımı temiz

    notes = [
        "Tarihsel point-in-time filing arşivi yok; mevcut cache snapshot restatement riski taşır.",
        "Bu nedenle indicative_only=true — FUND_SCORE_UI prod’da açılmaz.",
        f"Backtest modunda skor üretilebilen sembol (snapshot): {n_scored_bt}.",
        "Publish-lag (+45ç / +90y) ve live-only dışlama kodda zorunlu.",
    ]
    if live_leak:
        notes.append(f"UYARI: live-only sızıntı {len(live_leak)} sembol")
        look_ahead_clean = False

    payload = build_validation_payload(
        n_symbols=n_sym,
        n_pit_symbols=n_pit,
        n_cross_section=n_cs,
        bucket_returns={},
        look_ahead_clean=look_ahead_clean,
        indicative_only=indicative,
        notes=notes,
    )
    payload["n_scored_backtest_mode"] = n_scored_bt
    payload["live_leak_count"] = len(live_leak)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    md = _render_md(payload)
    OUT_MD.write_text(md, encoding="utf-8")

    ok, reason = fund_score_ui_allowed(payload)
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(f"FUND_SCORE_UI allowed={ok} ({reason})")
    return 0


def _render_md(p: dict) -> str:
    lines = [
        "# Temel skor validation (FAZ5)",
        "",
        f"- Üretim: `{p.get('generated_at')}`",
        f"- `look_ahead_clean`: **{p.get('look_ahead_clean')}**",
        f"- `indicative_only`: **{p.get('indicative_only')}**",
        f"- `sample_adequate`: **{p.get('sample_adequate')}**",
        f"- Sembol: {p.get('n_symbols')} · PIT adayı: {p.get('n_pit_symbols')} · "
        f"kesit: {p.get('n_cross_section')}",
        f"- Eşik: pit≥{p.get('min_pit_symbols')}, kesit≥{p.get('min_cross_section')}",
        "",
        "## Restatement uyarısı",
        "",
        p.get("restatement_warning") or "",
        "",
        "## Metrik envanteri",
        "",
        "| Metrik | Sınıf |",
        "|--------|-------|",
    ]
    for row in p.get("metric_inventory") or metric_inventory_table():
        lines.append(f"| `{row['metric']}` | `{row['class']}` |")

    lines.extend([
        "",
        "## Look-ahead teyidi",
        "",
        "Backtest skorunda `LIVE_ONLY_FIELDS` (PE, PB, hedef fiyat, analist, "
        "Yahoo .info snapshot marj/ROE/oran) **okunmaz**. "
        f"Live sızıntı sayısı: **{p.get('live_leak_count', 0)}**.",
        "",
        "## Publish-lag",
        "",
        f"- Çeyrek: +{p.get('publish_lag', {}).get('quarter_days', 45)} gün",
        f"- Yıllık: +{p.get('publish_lag', {}).get('annual_days', 90)} gün",
        f"- Örnek available_asof(2024-12-31, annual): "
        f"`{p.get('publish_lag', {}).get('available_asof_example')}`",
        "",
        "## Getiri kovaları",
        "",
        "Tarihsel PIT fiyat hizası bu koşuda boş bırakıldı (indicative). "
        "SAĞLAM/GÜÇLÜ vs RİSKLİ ve AZALT∩SAĞLAM vs AZALT∩RİSKLİ karşılaştırması "
        "PIT arşivi bağlandığında doldurulacak.",
        "",
        f"_{p.get('weights_note')}_",
        "",
        "## Notlar",
        "",
    ])
    for n in p.get("notes") or []:
        lines.append(f"- {n}")

    lines.extend([
        "",
        "## Gate",
        "",
        "`FUND_SCORE_UI` açılmaz çünkü `indicative_only=true` "
        "(ve/veya örneklem / look_ahead). Debug: `FUND_SCORE_UI_FORCE=1`.",
        "",
    ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
