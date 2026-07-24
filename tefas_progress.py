# -*- coding: utf-8 -*-
"""TEFAS yükleme ilerlemesi — arka plan thread + UI şeridi."""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

# (id, başlık, alt açıklama)
TEFAS_STAGES: List[Tuple[str, str, str]] = [
    ("disk", "Disk önbelleği", "Son kayıtlı fon tablosu aranıyor"),
    ("fetch", "TEFAS fiyat tarihçesi", "Resmi API · uzun pencere (90+ gün / YTD)"),
    ("returns", "Getiri hesaplama", "1H · 1A · 3A · YBB — uydurma yok"),
    ("dagilim", "Portföy dağılımı", "Hisse / döviz / altın kırılımı"),
    ("yaz", "Önbelleğe yazma", "Sonraki açılış anında gelsin"),
    ("ready", "Tablo hazır", "Skor ve KAP ayrı adım"),
]

_lock = threading.Lock()
_state: Dict[str, Any] = {
    "active": False,
    "phase": "idle",
    "done_ids": [],
    "detail": "",
    "pct": 0.0,
    "counter": "",
    "t0": 0.0,
    "error": "",
}


def _phase_pct(phase: str) -> float:
    base = {
        "idle": 0,
        "disk": 8,
        "fetch": 22,
        "returns": 55,
        "dagilim": 72,
        "yaz": 88,
        "ready": 100,
        "kap": 92,
    }
    return float(base.get(phase, 10))


def progress_baslat(*, detail: str = "TEFAS yüklemesi başlıyor…", zorla: bool = False) -> bool:
    """Yüklemeyi başlat. Zaten aktifse (zorla değilse) dokunma — poll sıfırlamasın."""
    with _lock:
        if _state.get("active") and not zorla:
            return False
        _state.update(
            {
                "active": True,
                "phase": "disk",
                "done_ids": [],
                "detail": detail,
                "pct": _phase_pct("disk"),
                "counter": "",
                "t0": time.time(),
                "error": "",
            }
        )
        return True


def progress_aktif_mi() -> bool:
    with _lock:
        return bool(_state.get("active"))


def progress_heartbeat(*, detail: str = "", pct_cap: float = 50.0) -> None:
    """Uzun API sırasında yüzde yavaş artsın (fetch’te donmuş gibi görünmesin)."""
    with _lock:
        if not _state.get("active"):
            return
        if _state.get("phase") not in ("fetch", "disk"):
            return
        t0 = float(_state.get("t0") or time.time())
        elapsed = max(0.0, time.time() - t0)
        # ~90 sn’de %22 → %50 civarı
        bump = min(pct_cap, 22.0 + elapsed * 0.35)
        cur = float(_state.get("pct") or 0)
        _state["pct"] = max(cur, bump)
        if detail:
            _state["detail"] = detail
        if _state.get("phase") == "disk" and elapsed > 1.5:
            _state["phase"] = "fetch"
            _state["done_ids"] = ["disk"]
            if not detail:
                _state["detail"] = (
                    f"TEFAS API çekiliyor · {elapsed:.0f}s "
                    "(uzun pencere 1–2 dk sürebilir)"
                )


def progress_ayarla(
    phase: str,
    detail: str = "",
    *,
    counter: str = "",
    done_ids: Optional[Sequence[str]] = None,
    pct: Optional[float] = None,
) -> None:
    with _lock:
        if not _state.get("active") and phase != "ready":
            _state["active"] = True
            if not _state.get("t0"):
                _state["t0"] = time.time()
        _state["phase"] = phase
        if detail:
            _state["detail"] = detail
        if counter:
            _state["counter"] = counter
        if done_ids is not None:
            _state["done_ids"] = list(done_ids)
        else:
            # Otomatik: phase öncesi aşamalar tamam
            ids = [s[0] for s in TEFAS_STAGES]
            if phase in ids:
                _state["done_ids"] = ids[: ids.index(phase)]
            elif phase == "ready":
                _state["done_ids"] = [s[0] for s in TEFAS_STAGES]
        _state["pct"] = float(pct) if pct is not None else _phase_pct(phase)


def progress_bitir(*, hata: str = "", detail: str = "") -> None:
    with _lock:
        elapsed = time.time() - float(_state.get("t0") or time.time())
        _state["active"] = False
        _state["phase"] = "ready" if not hata else _state.get("phase") or "ready"
        _state["done_ids"] = [s[0] for s in TEFAS_STAGES]
        _state["pct"] = 100.0 if not hata else float(_state.get("pct") or 0)
        _state["error"] = hata or ""
        if detail:
            _state["detail"] = detail
        elif hata:
            _state["detail"] = hata
        else:
            _state["detail"] = f"Tablo hazır · {elapsed:.0f}s"
        _state["counter"] = ""


def progress_durum() -> Dict[str, Any]:
    with _lock:
        return dict(_state)


def progress_cb(phase: str, detail: str = "", **kwargs: Any) -> None:
    """tefas_data / app_veri için tek satır callback."""
    progress_ayarla(phase, detail, **kwargs)


def render_tefas_progress_strip() -> None:
    """Streamlit — TEFAS aşama şeridi (boot strip tarzı)."""
    import html as _html

    import streamlit as st

    from ui_theme import ACCENT, BORDER, PANEL, PANEL_HOVER, TEXT, TEXT_MUTED, UP, _FONT

    stt = progress_durum()
    phase = stt.get("phase") or "disk"
    done = set(stt.get("done_ids") or [])
    pct = max(0.0, min(100.0, float(stt.get("pct") or 0)))
    detail = stt.get("detail") or "Yükleniyor…"
    counter = stt.get("counter") or ""
    err = stt.get("error") or ""
    active = bool(stt.get("active"))

    def _esc(s: object) -> str:
        return _html.escape(str(s or ""))

    chips = []
    for sid, title, _sub in TEFAS_STAGES:
        if sid == "ready" and phase != "ready" and "ready" not in done:
            continue
        if sid in done or phase == "ready":
            chips.append(
                f'<span style="color:{UP};font-weight:600;font-size:12px;'
                f'font-family:{_FONT};">✓ {_esc(title)}</span>'
            )
        elif sid == phase:
            chips.append(
                f'<span style="color:{ACCENT};font-weight:600;font-size:12px;'
                f'font-family:{_FONT};">▸ {_esc(title)}</span>'
            )
        else:
            chips.append(
                f'<span style="color:{TEXT_MUTED};font-size:12px;font-family:{_FONT};'
                f'opacity:0.55;">○ {_esc(title)}</span>'
            )
    bar_w = f"{pct:.1f}%"
    counter_html = (
        f'<span style="font-variant-numeric:tabular-nums;color:{ACCENT};'
        f'font-weight:600;margin-left:8px;">{_esc(counter)}</span>'
        if counter
        else ""
    )
    baslik = (
        "TEFAS yükleniyor · aşamaları izleyin"
        if active
        else ("TEFAS tamamlandı" if not err else "TEFAS uyarı")
    )
    st.html(
        f"""
<div style="margin:0 0 12px;padding:12px 16px;background:{PANEL};
  border:1px solid {BORDER};border-radius:12px;font-family:{_FONT};">
  <div style="display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;
    justify-content:space-between;">
    <div style="font-size:11px;letter-spacing:0.06em;text-transform:uppercase;
      color:{TEXT_MUTED};font-weight:600;">{_esc(baslik)}</div>
    <div style="font-size:12px;color:{TEXT_MUTED};">{pct:.0f}%{counter_html}</div>
  </div>
  <div style="display:flex;flex-wrap:wrap;gap:10px 16px;margin-top:8px;">
    {"".join(chips)}
  </div>
  <div style="margin-top:10px;height:4px;background:{PANEL_HOVER};border-radius:99px;overflow:hidden;">
    <div style="height:100%;width:{bar_w};background:{ACCENT};border-radius:99px;"></div>
  </div>
  <div style="margin-top:8px;font-size:12px;color:{TEXT if not err else '#F6465D'};">
    {_esc(err or detail)}
  </div>
</div>
"""
    )
