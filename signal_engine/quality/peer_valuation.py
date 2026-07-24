# -*- coding: utf-8 -*-
"""Sektör içi değerleme peer — F/K medyan ve yüzdelik.

Momentum peer_yuzdelik ile karıştırılmaz. Eksik/negatif F/K veya küçük grup → atlanır.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple


MIN_PEERS = 4
EXPENSIVE_PCT = 85.0
EXPENSIVE_MULT = 1.6
# Akran grubu inceyken mutlak F/K soft tavan (chase pahalı mega-cap)
ABS_PE_EXPENSIVE = 45.0


@dataclass(frozen=True)
class PeerValuation:
    pe: float
    pe_median: float
    pe_pct: float
    peer_n: int
    expensive: bool
    note: str
    pe_vs_median: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "pe": self.pe,
            "pe_median": self.pe_median,
            "pe_pct": self.pe_pct,
            "peer_n": self.peer_n,
            "expensive": self.expensive,
            "note": self.note,
            "pe_vs_median": self.pe_vs_median,
        }


def pe_from_temel(temel: Optional[dict]) -> Optional[float]:
    """Önce trailingPE, yoksa forwardPE; yalnızca >0."""
    if not temel or temel.get("_bos"):
        return None
    for key in ("trailingPE", "forwardPE"):
        v = temel.get(key)
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if x == x and x > 0:
            return x
    return None


def _is_hisse(h) -> bool:
    piyasa = (getattr(h, "piyasa", "") or "").upper()
    tur = (getattr(h, "varlik_turu", "") or "").lower()
    return piyasa not in ("ETF", "EMTIA") and tur not in ("etf", "emtia")


def _group_key(h) -> Tuple[str, str]:
    piyasa = (getattr(h, "piyasa", "") or "").upper() or "GENEL"
    sektor = (getattr(h, "sektor", "") or "").strip().lower() or "genel"
    return piyasa, sektor


def _percentile_rank(values: List[float], value: float) -> float:
    """Artan sırada yüzdelik (0–100). n=1 → 50."""
    n = len(values)
    if n <= 1:
        return 50.0
    ordered = sorted(values)
    # Bağlarda ortalama sıra
    idxs = [i for i, v in enumerate(ordered) if abs(v - value) < 1e-12]
    if not idxs:
        # en yakın alt indeks
        below = sum(1 for v in ordered if v < value)
        return 100.0 * below / (n - 1)
    avg_i = sum(idxs) / len(idxs)
    return 100.0 * avg_i / (n - 1)


def build_peer_valuation_map(
    hisseler: Iterable[Any],
    cache: Dict[str, dict],
    *,
    min_peers: int = MIN_PEERS,
    expensive_pct: float = EXPENSIVE_PCT,
    expensive_mult: float = EXPENSIVE_MULT,
    abs_pe_expensive: float = ABS_PE_EXPENSIVE,
) -> Dict[str, PeerValuation]:
    """Tek geçiş: (piyasa, sektör) → gerekirse sektör-global → mutlak F/K soft."""
    members: Dict[Tuple[str, str], List[Tuple[str, float]]] = {}
    by_sector: Dict[str, List[Tuple[str, float]]] = {}
    all_pe: List[Tuple[str, float]] = []
    for h in hisseler or []:
        if not _is_hisse(h):
            continue
        sym = (getattr(h, "sembol", "") or "").strip().upper()
        if not sym:
            continue
        pe = pe_from_temel(cache.get(sym) or {})
        if pe is None:
            continue
        pk, sk = _group_key(h)
        members.setdefault((pk, sk), []).append((sym, pe))
        by_sector.setdefault(sk, []).append((sym, pe))
        all_pe.append((sym, pe))

    out: Dict[str, PeerValuation] = {}

    def _fill(pairs: List[Tuple[str, float]], *, note_prefix: str) -> None:
        if len(pairs) < min_peers:
            return
        pes = [p for _, p in pairs]
        med = float(median(pes))
        if med <= 0:
            return
        for sym, pe in pairs:
            if sym in out:
                continue
            pct = _percentile_rank(pes, pe)
            ratio = pe / med
            expensive = pct >= expensive_pct or ratio >= expensive_mult
            note = (
                f"{note_prefix} pahalı (P{pct:.0f}, {ratio:.1f}× medyan, n={len(pairs)})"
                if expensive
                else f"{note_prefix} P{pct:.0f} ({ratio:.1f}× medyan, n={len(pairs)})"
            )
            out[sym] = PeerValuation(
                pe=pe,
                pe_median=med,
                pe_pct=pct,
                peer_n=len(pairs),
                expensive=expensive,
                note=note,
                pe_vs_median=ratio,
            )

    # 1) (piyasa, sektör)
    for _key, pairs in members.items():
        _fill(pairs, note_prefix="Sektör F/K")

    # 2) İnce grup → sektör (tüm piyasalar)
    for sk, pairs in by_sector.items():
        _fill(pairs, note_prefix=f"Sektör-global ({sk}) F/K")

    # 3) Hâlâ yoksa mutlak F/K soft
    for sym, pe in all_pe:
        if sym in out:
            continue
        if pe >= abs_pe_expensive:
            out[sym] = PeerValuation(
                pe=pe,
                pe_median=pe,
                pe_pct=100.0,
                peer_n=1,
                expensive=True,
                note=f"Mutlak F/K pahalı ({pe:.0f} ≥ {abs_pe_expensive:.0f}; akran yetersiz)",
                pe_vs_median=1.0,
            )
    return out
