# -*- coding: utf-8 -*-
"""Site giriş kapısı — tek paylaşımlı şifre (Render env)."""
from __future__ import annotations

import hmac
import os

import streamlit as st

from ui_theme import BORDER, PANEL, TEXT, TEXT_MUTED, _FONT

_SESSION_KEY = "_site_auth_ok"
_ENV_KEYS = ("MAKROFINANS_SITE_PASSWORD", "APP_PASSWORD")


def site_password_configured() -> bool:
    """Env'de şifre tanımlı mı? Boş/unset ise kapı devre dışı."""
    return bool(_expected_password())


def _expected_password() -> str:
    for key in _ENV_KEYS:
        val = (os.getenv(key) or "").strip()
        if val:
            return val
    return ""


def is_authenticated() -> bool:
    if not site_password_configured():
        return True
    return bool(st.session_state.get(_SESSION_KEY))


def _check_password(candidate: str) -> bool:
    expected = _expected_password()
    if not expected:
        return True
    return hmac.compare_digest(candidate, expected)


def logout() -> None:
    st.session_state.pop(_SESSION_KEY, None)


def gate_site_entry() -> bool:
    """Giriş ekranı. True = ana uygulamaya devam; False = st.stop() gerekir."""
    if not site_password_configured():
        return True
    if is_authenticated():
        return True
    _render_login_screen()
    return False


def render_logout_control(*, sidebar: bool = True) -> None:
    """Oturumu kapat — sidebar altında."""
    if not site_password_configured():
        return
    container = st.sidebar if sidebar else st
    with container:
        st.divider()
        if st.button("Çıkış", key="site_auth_logout", use_container_width=True):
            logout()
            st.rerun()


def _render_login_screen() -> None:
    """Tam genişlik giriş — mobilde kart ekranı doldurur."""
    st.markdown(
        """
<style>
[data-testid="stSidebar"] { display: none !important; }
[data-testid="stSidebarCollapsedControl"] { display: none !important; }
.block-container {
  max-width: 100% !important;
  padding-top: max(1rem, env(safe-area-inset-top)) !important;
  padding-left: max(1rem, env(safe-area-inset-left)) !important;
  padding-right: max(1rem, env(safe-area-inset-right)) !important;
}
</style>
""",
        unsafe_allow_html=True,
    )

    st.markdown('<div class="mc-login-shell">', unsafe_allow_html=True)

    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        st.markdown(
            f"""
<div class="mc-login-card">
  <div class="mc-login-eyebrow">Makrofinans</div>
  <div class="mc-login-title">Giriş</div>
  <div class="mc-login-sub">Devam etmek için site şifresini girin.</div>
</div>
""",
            unsafe_allow_html=True,
        )

        with st.form("site_auth_form", clear_on_submit=False):
            pwd = st.text_input("Şifre", type="password", key="site_auth_pwd")
            submitted = st.form_submit_button("Giriş", type="primary", use_container_width=True)

        if submitted:
            if _check_password(pwd or ""):
                st.session_state[_SESSION_KEY] = True
                st.rerun()
            else:
                st.error("Şifre hatalı. Tekrar deneyin.")

    st.markdown("</div>", unsafe_allow_html=True)

    # Kart stili — tema dosyasındaki mobil kurallarla uyumlu
    st.markdown(
        f"""
<style>
.mc-login-card {{
  font-family: {_FONT};
  background: {PANEL};
  border: 1px solid {BORDER};
  border-radius: 16px;
  padding: 24px 24px 8px;
  margin-bottom: 8px;
  box-shadow: 0 12px 40px rgba(0,0,0,0.35);
}}
.mc-login-eyebrow {{
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: {TEXT_MUTED};
  font-weight: 600;
}}
.mc-login-title {{
  font-size: 26px;
  font-weight: 600;
  color: {TEXT};
  margin: 6px 0 4px;
}}
.mc-login-sub {{
  font-size: 14px;
  color: {TEXT_MUTED};
  margin-bottom: 4px;
}}
@media (max-width: 768px) {{
  .mc-login-shell [data-testid="column"]:nth-child(1),
  .mc-login-shell [data-testid="column"]:nth-child(3) {{
    display: none !important;
  }}
  .mc-login-shell [data-testid="column"]:nth-child(2) {{
    flex: 1 1 100% !important;
    width: 100% !important;
    min-width: 0 !important;
  }}
  .mc-login-card {{
    padding: 20px 18px 6px;
    border-radius: 14px;
  }}
  .mc-login-title {{ font-size: 22px; }}
}}
</style>
""",
        unsafe_allow_html=True,
    )
