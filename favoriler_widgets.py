# -*- coding: utf-8
"""Favori widget'ları — hafif import (döngüsel import önleme)."""
from __future__ import annotations

from typing import Any, Callable, List, Optional, Sequence, Set, Tuple
from urllib.parse import unquote

import pandas as pd
import streamlit as st

from favoriler import (
    FavoriStore,
    data_column_lock,
    favori_toggle,
    favori_var,
    normalize_sembol,
    yukle_store as yukle_favori_store,
)
from ui_theme import (
    _is_pct_col,
    build_df_table_html,
    render_df_table,
)

_FAV_ACTION_KEY = "fav_action_item_id"
_NAV_PAGES = frozenset({
    "Portföy Tahsisi",
    "Karar Asistanı",
    "Asistan",
    "Varlıklarım",
    "Favorilerim",
    "AI Danışman",
    "TL Mevduat Faizleri",
    "TEFAS Fonları",
    "Hisse & Endeks Taraması",
    "Backtest",
})


def restore_nav_from_query() -> None:
    """Yıldız tıklaması sonrası sidebar bölümünü koru."""
    raw = st.query_params.get("mc_nav")
    if not raw:
        return
    nav = unquote(str(raw))
    if nav in _NAV_PAGES:
        st.session_state["nav_sayfa"] = nav
    if "mc_nav" in st.query_params:
        del st.query_params["mc_nav"]


def _store(*, reload_disk: bool = False) -> FavoriStore:
    if reload_disk or "favori_store" not in st.session_state:
        st.session_state.favori_store = yukle_favori_store()
        return st.session_state.favori_store
    raw = st.session_state.favori_store
    if not isinstance(raw, FavoriStore):
        st.session_state.favori_store = yukle_favori_store()
    return st.session_state.favori_store


def favori_store_yenile() -> FavoriStore:
    """Diskten taze yükle — başka sayfadan eklenen yıldızlar için."""
    st.session_state.favori_store = yukle_favori_store()
    return st.session_state.favori_store


def favori_yildiz_metni(tur: str, sembol: str) -> str:
    return "★" if favori_var(_store(), tur, sembol) else "☆"


def favori_yildiz_sutunu(tur: str, sembol: str) -> dict:
    return {"⭐": favori_yildiz_metni(tur, sembol)}


def favori_hisse_turu(h) -> str:
    if getattr(h, "piyasa", "") == "EMTIA" or getattr(h, "varlik_turu", "") == "emtia":
        return "emtia"
    if getattr(h, "piyasa", "") == "ETF" or getattr(h, "varlik_turu", "") == "etf":
        return "etf"
    return "hisse"


def favori_row_keys(meta: Sequence[Tuple[str, str, str]]) -> List[str]:
    return [f"{t}:{normalize_sembol(t, s)}" for t, s, _ in meta]


def queue_favori_action(item_id: str) -> None:
    st.session_state[_FAV_ACTION_KEY] = item_id


def pop_pending_favori_action() -> Optional[str]:
    return st.session_state.pop(_FAV_ACTION_KEY, None)


def _toggle_favori(tur: str, sym: str, ad: str) -> None:
    """Diskten oku → toggle → atomik kaydet. on_click içinde st.rerun() YOK."""
    store = yukle_favori_store()
    eklendi = favori_toggle(store, tur, sym, ad=ad or sym)
    st.session_state.favori_store = store
    etiket = (sym or "").split(".")[0]
    st.toast(f"{etiket} favorilere eklendi" if eklendi else f"{etiket} favorilerden çıkarıldı")


def _default_badge_col(df: pd.DataFrame) -> str:
    for c in ("Şimdi ne yap?", "Karar", "Öneri", "Emir", "Sinyal / Öneri"):
        if c in df.columns:
            return c
    return "Şimdi ne yap?"


def _sync_star_column(
    df: pd.DataFrame,
    meta: Sequence[Tuple[str, str, str]],
) -> pd.DataFrame:
    show = df.copy()
    if "⭐" not in show.columns:
        return show
    for ri, (tur, sym, _ad) in enumerate(meta):
        if ri >= len(show):
            break
        show.iloc[ri, show.columns.get_loc("⭐")] = favori_yildiz_metni(tur, sym)
    return show


def _consume_click_query(
    key_prefix: str,
    *,
    favori_meta: Optional[Sequence[Tuple[str, str, str]]],
    on_action: Optional[Callable[[str], None]],
) -> bool:
    """URL tıklamasını işle. True dönerse rerun gerekir."""
    changed = False
    fav_k = f"fav_{key_prefix}"
    if fav_k in st.query_params and favori_meta is not None:
        try:
            ri = int(st.query_params[fav_k])
            if 0 <= ri < len(favori_meta):
                tur, sym, ad = favori_meta[ri]
                _toggle_favori(tur, sym, ad)
                changed = True
        except (ValueError, TypeError):
            pass
        del st.query_params[fav_k]

    act_k = f"act_{key_prefix}"
    if act_k in st.query_params and on_action is not None:
        on_action(unquote(str(st.query_params[act_k])))
        del st.query_params[act_k]
        changed = True

    return changed


def render_df_table_interactive(
    df: pd.DataFrame,
    *,
    key_prefix: str = "favtbl",
    max_height: Optional[int] = 480,
    favori_meta: Optional[Sequence[Tuple[str, str, str]]] = None,
    row_ids: Optional[Sequence[str]] = None,
    action_col: bool = False,
    on_action: Optional[Callable[[str], None]] = None,
    pct_cols: Optional[Set[str]] = None,
    badge_col: str = "Karar",
    truncate_cols: Optional[Set[str]] = None,
) -> None:
    """HTML tablo — tıklanabilir yıldız ve işlem sütunu."""
    if df.empty:
        st.caption("Tablo boş.")
        return

    if _consume_click_query(key_prefix, favori_meta=favori_meta, on_action=on_action):
        st.rerun()

    pct_cols = pct_cols or {c for c in df.columns if _is_pct_col(c)}
    body_h = max_height or 480
    has_star = favori_meta is not None and "⭐" in df.columns
    has_action = bool(
        action_col and row_ids is not None and len(row_ids) == len(df) and on_action is not None
    )

    if has_star and favori_meta is not None and len(favori_meta) != len(df):
        render_df_table(df, max_height=body_h, pct_cols=pct_cols, badge_col=badge_col)
        st.caption("Favori eşleşmesi hatası — tablo salt okunur.")
        return

    if not has_star and not has_action:
        render_df_table(
            df,
            max_height=body_h,
            pct_cols=pct_cols,
            badge_col=badge_col,
            truncate_cols=truncate_cols,
        )
        return

    show = _sync_star_column(df, favori_meta) if has_star and favori_meta else df.copy()
    nav_page = str(st.session_state.get("nav_sayfa", "") or "")
    table_html = build_df_table_html(
        show,
        pct_cols=pct_cols,
        badge_col=badge_col,
        max_height=body_h,
        truncate_cols=truncate_cols,
        click_table_id=key_prefix,
        action_row_ids=list(row_ids) if has_action and row_ids is not None else None,
        nav_page=nav_page or None,
    )
    st.markdown(table_html, unsafe_allow_html=True)


def render_df_table_favorili(
    df: pd.DataFrame,
    meta: Sequence[Tuple[str, str, str]],
    *,
    key_prefix: str = "favtbl",
    **table_kwargs: Any,
) -> None:
    """TEFAS — fragment sarmalı yıldızlı tablo."""
    render_df_table_favorili_fragment(df, meta, key_prefix=key_prefix, **table_kwargs)


def render_df_table_with_star_buttons(
    df: pd.DataFrame,
    meta: Sequence[Tuple[str, str, str]],
    *,
    key_prefix: str = "favtbl",
    max_height: Optional[int] = 480,
    row_ids: Optional[Sequence[str]] = None,
    action_col: bool = False,
    on_action: Optional[Callable[[str], None]] = None,
    pct_cols: Optional[Set[str]] = None,
    badge_col: str = "Karar",
    truncate_cols: Optional[Set[str]] = None,
) -> None:
    """
    Seçenek C — yıldız HTML tablo satırına gömülü (custom component).
    JS: Streamlit.setComponentValue → Python: _toggle_favori (rerun yok on_click'te).
    Fragment sarmalı çağrı korunur (TEFAS / Favoriler).
    """
    if df.empty:
        st.caption("Tablo boş.")
        return

    lock_before = data_column_lock(df)
    data_df = df.drop(columns=["⭐"], errors="ignore").copy()
    lock_after = data_column_lock(data_df)
    if lock_before != lock_after:
        st.error("Değer kilidi bozuldu — yıldız sütunu veri değiştirdi.")
        render_df_table(df, max_height=max_height or 480, pct_cols=pct_cols, badge_col=badge_col)
        return

    if meta is not None and len(meta) != len(data_df):
        render_df_table(data_df, max_height=max_height or 480, pct_cols=pct_cols, badge_col=badge_col)
        st.caption("Favori eşleşmesi hatası — tablo salt okunur.")
        return

    store = favori_store_yenile()
    pct_cols = pct_cols or {c for c in data_df.columns if _is_pct_col(c)}
    body_h = max_height or 480
    has_action = bool(
        action_col and row_ids is not None and len(row_ids) == len(data_df) and on_action is not None
    )

    from star_table_component import build_star_rows_from_df, star_favori_table

    cols, rows = build_star_rows_from_df(
        df,
        meta,
        store=store,
        favori_var_fn=favori_var,
        pct_cols=pct_cols,
        badge_col=badge_col,
        row_ids=list(row_ids) if has_action and row_ids is not None else None,
    )

    # Tıklama jetonu — aynı değerle tekrar toggle olmasın. Sabit component key:
    # önceden her toggle'da anahtar (_n) artırılıp iframe remount ediliyordu →
    # tabloda yanıp sönme. Token (result["t"]) dedup için yeterli.
    tok_key = f"_star_comp_tok_{key_prefix}"
    result = star_favori_table(
        columns=cols,
        rows=rows,
        max_height=body_h,
        has_action=has_action,
        key=f"{key_prefix}_starcomp",
        default=None,
    )
    if isinstance(result, dict) and result.get("t") != st.session_state.get(tok_key):
        st.session_state[tok_key] = result.get("t")
        kind = result.get("kind")
        if kind == "star":
            try:
                ri = int(result.get("i", -1))
            except (TypeError, ValueError):
                ri = -1
            if 0 <= ri < len(meta):
                tur, sym, ad = meta[ri]
                _toggle_favori(tur, sym, ad)
        elif kind == "action" and on_action is not None and result.get("id"):
            on_action(str(result["id"]))


@st.fragment
def render_df_table_favorili_fragment(
    df: pd.DataFrame,
    meta: Sequence[Tuple[str, str, str]],
    *,
    key_prefix: str = "favtbl",
    **table_kwargs: Any,
) -> None:
    """TEFAS karşılaştırma — fragment; yıldız tıklaması tarama yeniden koşturmaz."""
    if "badge_col" not in table_kwargs:
        table_kwargs = {**table_kwargs, "badge_col": _default_badge_col(df)}
    render_df_table_with_star_buttons(df, meta, key_prefix=key_prefix, **table_kwargs)


# Geriye uyum — eski prototip çağrıları no-op fragment
@st.fragment
def render_star_alignment_prototype(*, key_prefix: str = "star_proto") -> None:
    st.caption("Yıldız prototipi üretim tablolarına taşındı (TEFAS + Favorilerim).")
