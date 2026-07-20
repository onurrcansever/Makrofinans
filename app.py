# -*- coding: utf-8 -*-
"""
Makro Portföy Dashboard — portföy, mevduat, hisse taraması
Otomatik yenileme: sidebar'dan açılır (varsayılan 3 dk).
"""
import pandas as pd
import streamlit as st
from pathlib import Path
from streamlit_autorefresh import st_autorefresh
from typing import Optional

import config
from investor_profile import (
    AMAC_SECENEKLERI,
    RISK_SECENEKLERI,
    VADE_SECENEKLERI,
    YatirimProfili,
    profil_mevduat_vadesi,
    vade_kisa_mi,
)
from allocation_engine import VARLIKLAR
from regime_uyum import rejim_gosterim_metni
from backtest import backtest_karsilastirma_uret
from veri_kalitesi import veri_kalite_olustur
from macro_data import cache_gecmisi
from notifier import portfoy_raporu_olustur
from stock_scanner import SINYAL_ETIKET, esige_yakin_sec
from stock_universe import SEKTOR_ETIKET
from alim_uygunluk import alim_aksiyon_kisa
from bist_52h_eur import format_52h_metin
from fiyat_para import (
    fiyat_sutun_adi,
    fx_serileri_al,
    getiri_sutun_adi,
    session_gosterim_pb,
    sidebar_gosterim_pb_secici,
    tablo_fiyat,
    tablo_fx_hazirla,
    tablo_getiri,
    spot_fiyat_veya_live,
)
from advisor_ui import danisman_paneli
from tefas_ui import tefas_paneli
from favoriler_widgets import (
    favori_hisse_turu,
    favori_row_keys,
    favori_yildiz_sutunu,
    render_df_table_favorili,
    restore_nav_from_query,
)
from favoriler_ui import favoriler_paneli
from kullanici_portfoy import KullaniciPortfoy, MevcutPozisyon, varsayilan_portfoy
from portfoy_yoneticisi import yonetici_oncelikli, yonetici_tablo_kolonlari, yonetici_pozisyon_kolonlari
from birlesik_oneri_ui import birlesik_oneri_paneli
from varliklarim_ui import varliklarim_paneli, oneri_aktar_butonu
from signal_engine.explain.why import why_markdown
from investment_report import rapor_paketi_olustur
from report_pdf import hisse_etf_tablo_pdf_olustur
from ui_theme import (
    inject_tradingview_theme,
    plotly_area_line,
    plotly_hbar,
    plotly_vbar,
    render_df_table,
    render_live_banner,
    render_metric_strip,
    render_page_header,
)

_UYGUN_SIRA = {"UYGUN": 0, "SINIRLI": 1, "IZLE": 2, "UYGUN_DEGIL": 3}


def _tablo_fiyat_fx(fiyat, gpb, fx, *, sembol="", piyasa="", varlik_turu="", quote_currency="", kaynak_pb=""):
    from fiyat_para_fx import FxUnavailableError

    if fiyat is None:
        return None
    try:
        return tablo_fiyat(
            fiyat, gpb, fx.eur_try, fx.usd_try,
            sembol=sembol, piyasa=piyasa, varlik_turu=varlik_turu,
            quote_currency=quote_currency, kaynak_pb=kaynak_pb,
            gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd,
            chf_usd=getattr(fx, "chf_usd", None),
        )
    except FxUnavailableError:
        return None


def _hisse_spot_fiyat(h, fiyat=None) -> tuple:
    """Tablo/Gram için (fiyat, quote_currency) — önce tarama, yoksa canlı kotasyon."""
    return spot_fiyat_veya_live(
        getattr(h, "sembol", "") or "",
        fiyat if fiyat is not None else getattr(h, "fiyat", None),
        getattr(h, "quote_currency", "") or "",
    )


def _hisse_tablo_fiyat(h, gpb, fx, fiyat=None):
    px, qc = _hisse_spot_fiyat(h, fiyat=fiyat)
    return _tablo_fiyat_fx(
        px, gpb, fx,
        sembol=h.sembol, piyasa=h.piyasa,
        varlik_turu=getattr(h, "varlik_turu", "hisse"),
        quote_currency=qc,
    )


def _endeks_tablo_fiyat(e, gpb, fx, fiyat=None):
    px, qc = spot_fiyat_veya_live(
        getattr(e, "sembol", "") or "",
        fiyat if fiyat is not None else getattr(e, "fiyat", None),
        (getattr(e, "quote_currency", "") or "").strip()
        or ("TRY" if str(getattr(e, "sembol", "")).endswith(".IS") else "USD"),
    )
    return _tablo_fiyat_fx(px, gpb, fx, sembol=e.sembol, quote_currency=qc)


def _endeks_bar_dates(e, usd_s) -> Optional[pd.DatetimeIndex]:
    bd = getattr(e, "close_bar_dates", None)
    if bd is not None and len(bd) > 0:
        return bd
    usd = usd_s.dropna() if usd_s is not None else pd.Series(dtype=float)
    return pd.DatetimeIndex(usd.index) if not usd.empty else None


def _1g_onceki_kapanis(sembol: str, fiyat: Optional[float], r_native: Optional[float]):
    """Tablo 1G — canlı previousClose varsa yeniden hesapla (bayat tarama bar-%'sini ez).

    allow_stale: Şimdi yenile / arka plan son kaydı TTL aşsa da 1G için kullan
    (bölüm dönüşünde bellekteki yanlış bar-% yerine).
    """
    try:
        from signal_engine.data.live_quote import get_live_quote

        live = get_live_quote(sembol, allow_stale=True)
        if live and live.previous_close and float(live.previous_close) > 0:
            px = live.price if live.price and live.price > 0 else fiyat
            if px is not None and float(px) > 0:
                return (float(px) - float(live.previous_close)) / float(live.previous_close) * 100.0
    except Exception:
        pass
    return r_native


def _hisse_tablo_getiri(h, r_native, gpb, gun, eur_s, usd_s, gbp_s):
    """Kur ayarlı getiri — FX yoksa native'e düşmez (None)."""
    from fiyat_para_fx import FxUnavailableError

    if gun == 1:
        r_native = _1g_onceki_kapanis(h.sembol, getattr(h, "fiyat", None), r_native)
    try:
        return tablo_getiri(
            r_native,
            gpb,
            gun,
            eur_s,
            usd_s,
            gbp_seri=gbp_s,
            sembol=h.sembol,
            piyasa=h.piyasa,
            varlik_turu=getattr(h, "varlik_turu", "hisse"),
            quote_currency=getattr(h, "quote_currency", ""),
            bar_dates=getattr(h, "close_bar_dates", None),
        )
    except FxUnavailableError:
        return None


def _teknik_sinyal_etiket(h) -> str:
    """Teknik sinyal — nihai kararla çelişiyorsa bunu etikette belirt."""
    tek = SINYAL_ETIKET.get(h.sinyal, h.sinyal)
    karar = getattr(h, "alim_uygun", "IZLE")
    if h.sinyal in ("ALIM_FIRSATI", "TREND_ALIM") and karar == "UYGUN_DEGIL":
        return f"{tek} → elendi"
    if h.sinyal in ("ALIM_FIRSATI", "TREND_ALIM") and karar == "SINIRLI":
        return f"{tek} → dikkat"
    return tek


def _karar_emoji(h) -> str:
    return {"UYGUN": "🟢", "SINIRLI": "🟡", "UYGUN_DEGIL": "🔴", "IZLE": "⚪"}.get(
        getattr(h, "alim_uygun", "IZLE"), "⚪"
    )


def _gunluk_delta(pct) -> Optional[str]:
    """st.metric delta — günlük % değişim."""
    if pct is None:
        return None
    try:
        return f"{float(pct):+.2f}%"
    except (TypeError, ValueError):
        return None


def _gunluk_delta_pp(pp) -> Optional[str]:
    """Volatilite seviyesi — puan (pp) değişimi."""
    if pp is None:
        return None
    try:
        return f"{float(pp):+.2f} pp"
    except (TypeError, ValueError):
        return None


st.set_page_config(
    page_title="Makro Portföy Asistanı",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_tradingview_theme()
restore_nav_from_query()

with st.sidebar:
    st.markdown("## Makrofinans")
    st.caption("Portföy karar destek")
    st.divider()
    st.subheader("Profil")
    risk_etiket = st.selectbox(
        "Risk toleransı",
        list(RISK_SECENEKLERI.keys()),
        index=1,
        format_func=lambda k: RISK_SECENEKLERI[k],
    )
    vade_etiket = st.selectbox(
        "Yatırım vadesi",
        list(VADE_SECENEKLERI.keys()),
        index=1,
        format_func=lambda k: VADE_SECENEKLERI[k],
    )
    amac_etiket = st.selectbox(
        "Yatırım amacı",
        list(AMAC_SECENEKLERI.keys()),
        index=1,
        format_func=lambda k: AMAC_SECENEKLERI[k],
        help="Tahsis tavanlarını ve skor ağırlıklarını etkiler (ölü kontrol değil).",
    )
    profil = YatirimProfili(risk=risk_etiket, vade=vade_etiket, amac=amac_etiket)
    st.caption(profil.ozet())
    st.divider()
    st.subheader("Bölümler")
    sayfa = st.radio(
        "Bölüm",
        ["Portföy Tahsisi", "Karar Asistanı", "Asistan", "Varlıklarım", "Favorilerim", "AI Danışman", "TL Mevduat Faizleri", "TEFAS Fonları", "Hisse & Endeks Taraması", "Backtest"],
        key="nav_sayfa",
        format_func=lambda s: {
            "Portföy Tahsisi": "Portföy Tahsisi",
            "Karar Asistanı": "Karar Asistanı",
            "Asistan": "Asistan",
            "Varlıklarım": "Varlıklarım",
            "Favorilerim": "Favorilerim",
            "AI Danışman": "AI Danışman",
            "TL Mevduat Faizleri": "TL Mevduat",
            "TEFAS Fonları": "TEFAS Fonları",
            "Hisse & Endeks Taraması": "Hisse & ETF",
            "Backtest": "Backtest",
        }.get(s, s),
        label_visibility="collapsed",
    )
    mod = st.radio("Veri modu", ["Canlı veri", "Demo (senaryo)"], index=0)
    sidebar_gosterim_pb_secici()
    st.session_state.hisse_haber_tara = st.checkbox(
        "Derin haber taraması (~1 dk ek süre)",
        value=st.session_state.get("hisse_haber_tara", False),
        help="Hisse/endeks taramasında Google News katmanı — açılış yüklemesine dahil edilir.",
    )
    import config as _cfg
    st.session_state.use_signal_v2 = st.checkbox(
        "Signal Engine v2 (çok faktörlü)",
        value=st.session_state.get("use_signal_v2", _cfg.USE_SIGNAL_ENGINE_V2),
        help="Rejim-duyarlı skor, percentile, P(doldur) — eski motor yerine.",
    )

    st.divider()
    st.subheader("Portföy Parametreleri")
    if "kullanici_portfoy" not in st.session_state:
        st.session_state.kullanici_portfoy = varsayilan_portfoy()
    kp_sb = st.session_state.kullanici_portfoy
    mev_sb = kp_sb.mevcut_tl_mevduat()

    st.caption("Değişiklikleri uygulamak için **Güncelle**'ye basın.")
    with st.form("portfoy_form", border=False):
        para_birimi = st.selectbox(
            "Para birimi",
            ["EUR", "TL"],
            index=0 if kp_sb.para_birimi == "EUR" else 1,
        )
        toplam = st.number_input(
            f"Toplam portföy ({kp_sb.para_birimi})",
            value=float(kp_sb.toplam),
            step=1000.0 if kp_sb.para_birimi == "EUR" else 50000.0,
            min_value=0.0,
        )
        with st.expander("Mevcut mevduat / fon", expanded=mev_sb is not None):
            st.caption("Birleşik öneri mevcut pozisyonunuza göre hesaplanır.")
            mevduat_var = st.checkbox(
                "TL vadeli mevduat",
                value=mev_sb is not None,
            )
            mev_bank = st.text_input("Banka", value=mev_sb.banka if mev_sb else "Yapı Kredi")
            mev_tutar = st.number_input(
                "Mevduat (TL)",
                value=float(mev_sb.tutar if mev_sb else (kp_sb.toplam if kp_sb.para_birimi == "TL" else 0)),
                min_value=0.0,
                step=10000.0,
            )
            mev_vade = st.number_input(
                "Vade (gün)",
                value=int(mev_sb.vade_gun if mev_sb else 90),
                min_value=1,
                max_value=730,
                step=1,
            )
            mev_faiz = st.number_input(
                "Faiz % (brüt yıllık)",
                value=float(mev_sb.brut_faiz if mev_sb else 42.0),
                min_value=0.0,
                max_value=100.0,
                step=0.5,
            )
            tefas_kod = st.text_input(
                "TEFAS kodu (isteğe bağlı)",
                value=next((p.fon_kodu for p in kp_sb.pozisyonlar if p.tur == "tefas"), ""),
                placeholder="YHS",
            ).strip().upper()
            tefas_tutar = st.number_input(
                "TEFAS tutarı (TL, isteğe bağlı)",
                value=float(next((p.tutar for p in kp_sb.pozisyonlar if p.tur == "tefas"), 0.0)),
                min_value=0.0,
                step=10000.0,
            )
        if st.form_submit_button("✓ Portföyü güncelle", type="primary", use_container_width=True):
            _pozisyonlar: list = []
            if mevduat_var and mev_tutar > 0:
                _pozisyonlar.append(
                    MevcutPozisyon(
                        tur="tl_mevduat",
                        tutar=float(mev_tutar),
                        para_birimi="TL",
                        banka=mev_bank.strip() or "Banka",
                        vade_gun=int(mev_vade),
                        brut_faiz=float(mev_faiz),
                    )
                )
            if tefas_kod and tefas_tutar > 0:
                _pozisyonlar.append(
                    MevcutPozisyon(
                        tur="tefas",
                        tutar=float(tefas_tutar),
                        para_birimi="TL",
                        fon_kodu=tefas_kod,
                    )
                )
            st.session_state.kullanici_portfoy = KullaniciPortfoy(
                para_birimi=para_birimi,
                toplam=float(toplam),
                pozisyonlar=_pozisyonlar,
            )
            from app_veri import veri_onbellegi_temizle as _veri_temizle
            from app_onbellek import onbellek_gecersiz_kil as _ob_temizle
            _veri_temizle()
            _ob_temizle()
            st.rerun()

    trans = st.number_input("Tranş sayısı", value=int(config.TRANS_SAYISI), min_value=1)
    bt_ay = st.slider("Backtest ay sayısı", 6, 18, 12)
    st.divider()
    otoyenile = st.toggle("Otomatik yenileme", value=False)
    aralik_etiket = st.selectbox(
        "Yenileme aralığı",
        ["1 dakika", "3 dakika", "5 dakika", "10 dakika"],
        index=1,
    )
    aralik_dk = int(aralik_etiket.split()[0])
    yenile = st.button("Şimdi yenile", type="primary", use_container_width=True)
    boot_zorla = st.button(
        "Açılış ekranını yeniden çalıştır",
        use_container_width=True,
        key="boot_zorla",
        help="Kur → canlı fiyat → tarama → analist aşamalarını zorla yeniler.",
    )
    st.caption(
        "Açılışta aşama ekranı verileri doğrular. Sonra: fiyatlar 15 dk · tarama 15 dk · "
        "TEFAS/faiz 6 sa. Anlık taze için **Şimdi yenile** (açılış + zorla tarama)."
    )

kullanici_portfoy = st.session_state.kullanici_portfoy
config.TOPLAM_EUR = kullanici_portfoy.toplam  # form submit sonrası session'dan okunur
config.TRANS_SAYISI = int(trans)
canli_mod = mod == "Canlı veri"

if "son_yenileme_sayaci" not in st.session_state:
    st.session_state.son_yenileme_sayaci = 0
if "onceki_rejim" not in st.session_state:
    st.session_state.onceki_rejim = None
if "son_rapor" not in st.session_state:
    st.session_state.son_rapor = None
if "rapor_hata" not in st.session_state:
    st.session_state.rapor_hata = None
if "tarama_son" not in st.session_state:
    st.session_state.tarama_son = None
if "hisse_haber_tara" not in st.session_state:
    st.session_state.hisse_haber_tara = False


from app_veri import (
    backtest_veri,
    cds_kaynak_ozet,
    mevduat_cek,
    tarama_cek,
    tarama_yukleniyor,
    tefas_yukleniyor,
    veri_onbellegi_temizle,
)
from app_onbellek import onbellek_gecersiz_kil, onbellek_sayfa_hazirla, uygulama_onbellegi_al


def _tarama_param(profil: YatirimProfili) -> dict:
    return {
        "profil_risk": profil.risk,
        "profil_vade": profil.vade,
        "use_signal_v2": st.session_state.get("use_signal_v2", True),
    }


def _karar_etiket(h) -> str:
    if getattr(h, "signal_v2_decision", ""):
        return h.signal_v2_decision
    return alim_aksiyon_kisa(getattr(h, "alim_uygun", "IZLE"))


def _hisse_satir_oncelik(
    h,
    gpb,
    fx,
    *,
    sembol_key: str,
    sembol_val: str,
    ad_key: str,
    ad_val: str,
    fiyat_kol: str,
    fiyat_val,
) -> dict:
    """Sol sıra: aksiyon · momentum · özet · rejim · sembol · ad · fiyat · alım."""
    from hisse_ozet_chip import ozet_chip_html
    from karar_lejant import (
        HISSE_AKSIYON_SUTUN,
        HISSE_ALIM_SEVIYE_SUTUN,
        HISSE_MOMENTUM_SUTUN,
    )

    yon = yonetici_tablo_kolonlari(h, gpb, fx)
    return {
        HISSE_AKSIYON_SUTUN: _karar_etiket(h),
        HISSE_MOMENTUM_SUTUN: _sinyal_etiket(h, fx=fx),
        "Özet": ozet_chip_html(h),
        "Rejim": yon.get("Rejim", "—"),
        sembol_key: sembol_val,
        ad_key: ad_val,
        fiyat_kol: fiyat_val,
        HISSE_ALIM_SEVIYE_SUTUN: yon.get(HISSE_ALIM_SEVIYE_SUTUN, yon.get("Al", "—")),
    }


def _hisse_veri_kolonu(h, gpb, fx) -> str:
    return yonetici_tablo_kolonlari(h, gpb, fx).get("Veri", "—")


def _skor_etiket(h, *, fx=None):
    """Skor hücresi: '65 (99%) 💚14/14 +37%' — temel cache + analist sayısı."""
    from temel_veri import skor_etiket_hisse

    return skor_etiket_hisse(h, fx=fx)


def _sinyal_etiket(h, *, fx=None) -> str:
    """İlk sütun: 🔼 / ⏸ / 🔽 (skor+analist+hedef)."""
    from temel_veri import sinyal_isaret_hisse

    return sinyal_isaret_hisse(h, fx=fx)


def _v2_aktif() -> bool:
    return bool(st.session_state.get("use_signal_v2", config.USE_SIGNAL_ENGINE_V2))


def _v2_tablo_ekstra(h) -> dict:
    if not _v2_aktif():
        return {}
    spark = getattr(h, "signal_v2_sparkline", None) or []
    if spark:
        return {"90g": spark}
    return {}


def _temel_cache_tarama_doldur(
    hisseler,
    *,
    force: bool = False,
    semboller=None,
) -> None:
    """
    Hisse sembolleri için temel_veri cache (analist / hedef).
    ETF atlanır. TTL hit ise hızlı; eksiklerde progress bar + anlık sembol.
    force=True: _bos / bayat dahil yeniden çek (yalnızca manuel buton).
    semboller: verilirse yalnızca bu liste çekilir (tam evren yerine).
    """
    from temel_veri import (
        _cache_taze,
        _rec_counts_eksik,
        temel_veri_tarama_icin,
        yukle_cache,
    )

    if semboller is not None:
        syms = sorted({
            str(s or "").strip().upper()
            for s in semboller
            if str(s or "").strip()
        })
    else:
        syms = sorted({
            (getattr(h, "sembol", "") or "").strip().upper()
            for h in (hisseler or [])
            if getattr(h, "piyasa", "") not in ("ETF", "EMTIA")
            and getattr(h, "varlik_turu", "") not in ("etf", "emtia")
            and (getattr(h, "sembol", "") or "").strip()
        })
    if not syms:
        return

    cache = yukle_cache()
    need_info = [
        s for s in syms
        if force
        or not cache.get(s)
        or not _cache_taze(cache[s])
        or cache[s].get("_bos")
    ]
    need_rec = [s for s in syms if _rec_counts_eksik(cache.get(s))]
    if not need_info and not need_rec:
        n_ok = sum(
            1 for s in syms
            if (cache.get(s) or {}).get("recommendationKey")
            and not (cache.get(s) or {}).get("_bos")
        )
        st.caption(f"Analist cache: **{n_ok}/{len(syms)}** hisse hazır (TTL).")
        return

    n_job = len(set(need_info) | set(need_rec)) if not force else len(syms)
    st.markdown(
        f"**Analist / hedef cache** (tarama değil) — "
        f"Yahoo’dan {n_job} sembol · tabloda {len(syms)} hisse + ETF’ler ayrı"
    )
    bar = st.progress(0)
    status = st.empty()
    son_liste = st.empty()
    son_5: list = []

    def _on_progress(done: int, total: int, mesaj: str) -> None:
        tot = max(1, int(total) or n_job)
        d = min(int(done), tot)
        bar.progress(min(1.0, d / tot))
        pct = 100.0 * d / tot
        status.markdown(
            f"**{d}/{tot}** (%{pct:.0f}) — `{mesaj}`"
        )
        # Son tamamlanan sembolü kaydet (mesajda ticker var)
        parca = mesaj.split(":")[-1].strip() if ":" in mesaj else mesaj
        ticker = parca.split()[0] if parca else ""
        if ticker and ticker not in ("Başlıyor…", "Tamamlandı") and ticker != "?":
            if not son_5 or son_5[-1] != ticker:
                son_5.append(ticker)
                if len(son_5) > 6:
                    del son_5[:-6]
            son_liste.caption("Son: " + " · ".join(son_5))

    _cache, stats = temel_veri_tarama_icin(
        syms, force=force, progress_cb=_on_progress,
    )
    bar.progress(1.0)
    status.markdown(
        f"**Bitti** — analistli **{stats.get('analistli', 0)}/{stats.get('istenen', len(syms))}** · "
        f"yeni çekim {stats.get('fetched', 0)} · {stats.get('elapsed_sec', 0):.0f}s"
    )
    st.caption(
        f"Analist cache hazır · {stats.get('elapsed_sec', 0):.0f}s"
    )


def _hisse_tarama_icerik(tarama, snap, tahsis, profil=None, *, guncelleniyor: bool = False) -> None:
    """Hisse & ETF tarama sayfası gövdesi."""
    # Analist sembolleri — senkron doldurma bitmeden fragment/rerun YASAK
    # (eski 8 sn fragment, uzun Yahoo çekimini yarıda kesiyordu)
    _analist_syms: list = []
    try:
        from background_cache import (
            analist_hisse_sembolleri,
            status_caption_parts,
            universe_analist_symbols,
        )
        from signal_engine.data.live_quote import load_live_quotes_disk

        load_live_quotes_disk(hydrate_memory=True)
        if tarama is not None and not tarama_yukleniyor(tarama):
            _analist_syms = analist_hisse_sembolleri(getattr(tarama, "hisseler", None) or [])
        if not _analist_syms:
            _analist_syms = universe_analist_symbols()
        st.caption(status_caption_parts(_analist_syms))
    except Exception:
        pass

    if tarama is None or tarama_yukleniyor(tarama):
        st.info(
            "Hisse/endeks taraması arka planda yükleniyor — "
            "**30–90 sn** içinde tablolar otomatik dolacak."
        )
        st.caption(
            "Beklemek istemezseniz **Taramayı yenile** ile hemen senkron çekim yapılır."
        )
        return
    if guncelleniyor:
        st.caption("🔄 Tarama arka planda güncelleniyor — liste bir önceki sonucu gösteriyor.")

    # Analist / hedef — yalnızca açılışta kaçan etiketler (tam 102 yeniden değil)
    try:
        from background_cache import analist_hisse_sembolleri
        from boot_sequence import _boot_analist_need

        _auto_syms = analist_hisse_sembolleri(getattr(tarama, "hisseler", None) or [])
        if not _auto_syms:
            _auto_syms = list(_analist_syms)
        # Boot zaten recommendationKey doldurduysa burada tekrar çekme.
        # "kalan 4" (al_sayi) arka plan daemon'a bırakılır.
        _auto_eksik = _boot_analist_need(_auto_syms) if _auto_syms else []
        _rounds = int(st.session_state.get("_analist_autofill_rounds", 0))
        if _auto_eksik and _rounds < 2:
            st.session_state["_analist_sync_fill"] = True
            st.session_state["_analist_autofill_rounds"] = _rounds + 1
            _before = len(_auto_eksik)
            st.info(
                f"Analist / hedef — açılışta kalan **{_before}** sembol "
                f"tamamlanıyor (tam evren yeniden çekilmez)."
            )
            try:
                _temel_cache_tarama_doldur(
                    getattr(tarama, "hisseler", None) or [],
                    force=False,
                    semboller=_auto_eksik,
                )
            finally:
                st.session_state["_analist_sync_fill"] = False
            _after = len(_boot_analist_need(_auto_syms))
            if _after == 0:
                st.session_state["_analist_autofill_rounds"] = 99
            st.rerun()
    except Exception as _af_exc:
        st.session_state["_analist_sync_fill"] = False
        st.caption(f"Analist otomatik doldurma atlandı: {_af_exc}")

    # Senkron doldurma bittikten sonra sessiz arka plan (TTL sonrası)
    if _analist_syms and not st.session_state.get("_analist_sync_fill"):
        try:
            from background_cache import ensure_silent_refresh_daemon

            ensure_silent_refresh_daemon(
                quotes=True,
                analist=True,
                tarama=False,
                analist_symbols=_analist_syms,
                analist_first=True,
            )
        except Exception:
            pass

        @st.fragment(run_every=12)
        def _analist_otomatik_yenile():
            if st.session_state.get("_analist_sync_fill"):
                return
            try:
                from background_cache import (
                    analist_eksik_semboller,
                    analist_hazir_say,
                    ensure_analist_batch_daemon,
                    ensure_quotes_daemon,
                )

                ensure_analist_batch_daemon(_analist_syms)
                ensure_quotes_daemon()
                ok, tot = analist_hazir_say(_analist_syms)
                prev = int(st.session_state.get("_analist_ok_count", -1))
                eksik_n = len(analist_eksik_semboller(_analist_syms))
                st.session_state["_analist_ok_count"] = ok
                if eksik_n:
                    st.caption(
                        f"Analist arka planda… **{ok}/{tot}** (kalan {eksik_n})"
                    )
                    if prev >= 0 and ok >= prev + 8:
                        st.rerun()
                elif prev >= 0 and ok > prev:
                    st.rerun()
                elif tot and ok >= tot:
                    st.caption(f"Analist hazır · **{ok}/{tot}**")
            except Exception:
                pass

        _analist_otomatik_yenile()

    profil_ozet = getattr(tarama, "profil_ozet", "")
    st.caption(f"{profil_ozet or '—'} · {tahsis.rejim.etiket}")
    with st.expander("Profil ve tarama notları", expanded=False):
        for n in (getattr(tarama, "profil_notlari", None) or [])[:4]:
            st.caption(n)
        if profil and profil.risk == "yuksek" and profil.vade == "uzun":
            st.caption("Uzun vade + yüksek risk: trend filtresi gevşetildi.")
        if tarama.tarama_ozet:
            st.caption(tarama.tarama_ozet)
        _vo_ui = getattr(tarama, "veri_ozet_ui", "") or ""
        if _vo_ui:
            st.caption(_vo_ui)

    if tarama.uyarilar:
        with st.expander(f"Uyarılar ({len(tarama.uyarilar)})", expanded=False):
            st.warning("\n".join(tarama.uyarilar))

    gpb = session_gosterim_pb()
    from fiyat_para_fx import FxUnavailableError

    # FX önce — Yahoo serisi yoksa SNAP fallback (sayfa çökmesin)
    try:
        fx, eur_s, usd_s, gbp_s, _eurusd_s = tablo_fx_hazirla(
            snap, tarama, allow_snap_fallback=True,
        )
    except FxUnavailableError as e:
        st.error(f"Kur verisi alınamadı: {e}")
        return
    if "SNAP fallback" in (getattr(fx, "source", "") or ""):
        st.warning(
            "Yahoo USDTRY serisi geçici olarak yok — fiyat/getiri **SNAP kurları** ile "
            "gösteriliyor (bilgiler bayat / yaklaşık olabilir). Sayfayı biraz sonra yenileyin."
        )
    eur_try, usd_try = fx.eur_try, fx.usd_try

    # Analist cache sayfayı BLOKLAMAZ — tablolar önce; doldurma aşağıda opsiyonel
    fiyat_kol = fiyat_sutun_adi(gpb)
    g1 = getiri_sutun_adi("1G %", gpb)
    g1a = getiri_sutun_adi("1A %", gpb)
    g3a = getiri_sutun_adi("3A %", gpb)
    g1y = getiri_sutun_adi("1Y %", gpb)
    e1g = getiri_sutun_adi("1 Gün %", gpb)
    e1a = getiri_sutun_adi("1 Ay %", gpb)
    e3a = getiri_sutun_adi("3 Ay %", gpb)

    st.subheader("Endeksler")
    from endeks_yonlendirme import (
        endeks_alanlarini_doldur,
        oncelik_ozeti_sade,
        ozet_neden,
    )

    # Eski disk/session tarama: kurulum/güven/makro boş kalmasın
    fx_ok_ui = True
    try:
        fx_ok_ui = eur_s is not None and not getattr(eur_s, "empty", True)
    except Exception:
        fx_ok_ui = True
    endeks_alanlarini_doldur(
        tarama.endeksler,
        fx_ok=fx_ok_ui,
        makro_rejim=getattr(tarama, "makro_rejim", None)
        or getattr(getattr(tahsis, "rejim", None), "rejim", None)
        or "NOTR",
        snap=snap,
    )

    oncelik = oncelik_ozeti_sade(tarama.endeksler)
    if oncelik:
        st.caption(oncelik)

    def _endeks_satir(e):
        qc = getattr(e, "quote_currency", "") or ("TRY" if e.sembol.endswith(".IS") else "USD")
        bd = _endeks_bar_dates(e, usd_s)
        g1a_v = tablo_getiri(
            e.degisim_1ay, gpb, 21, eur_s, usd_s, gbp_seri=gbp_s, sembol=e.sembol,
            quote_currency=qc, bar_dates=bd,
        )
        g3a_v = tablo_getiri(
            e.degisim_3ay, gpb, 63, eur_s, usd_s, gbp_seri=gbp_s, sembol=e.sembol,
            quote_currency=qc, bar_dates=bd,
        )
        return {
            **favori_yildiz_sutunu("endeks", e.sembol),
            "Endeks": e.ad,
            fiyat_kol: _endeks_tablo_fiyat(e, gpb, fx),
            e1g: tablo_getiri(
                _1g_onceki_kapanis(e.sembol, getattr(e, "fiyat", None), e.degisim_1g),
                gpb, 1, eur_s, usd_s, gbp_seri=gbp_s, sembol=e.sembol,
                quote_currency=qc, bar_dates=bd,
            ),
            e1a: g1a_v,
            e3a: g3a_v,
            "Öneri": getattr(e, "aksiyon_etiket", None) or "Bekle",
            "Neden": ozet_neden(
                e,
                gosterim_1ay=g1a_v if isinstance(g1a_v, (int, float)) else None,
                gosterim_3ay=g3a_v if isinstance(g3a_v, (int, float)) else None,
                gosterim_pb=gpb,
            ),
            "Güven": int(getattr(e, "guven", 0) or 0),
        }

    endeks_df = pd.DataFrame([_endeks_satir(e) for e in tarama.endeksler])
    endeks_meta = [("endeks", e.sembol, e.ad) for e in tarama.endeksler]
    render_df_table_favorili(endeks_df, endeks_meta, key_prefix="endeks")
    from karar_lejant import (
        endeks_lejant_caption,
        endeks_lejant_detay,
        hisse_lejant_caption,
        hisse_sozluk_expander_markdown,
    )
    st.caption(endeks_lejant_caption())
    with st.expander("Endeks detay", expanded=False):
        st.caption(endeks_lejant_detay())
        detay_df = pd.DataFrame([{
            "Endeks": e.ad,
            "Teknik": getattr(e, "teknik_aksiyon_etiket", None) or "—",
            "Kurulum": getattr(e, "kurulum", None) or "—",
            "Makro": getattr(e, "makro_chip", None) or "—",
            "Nihai": getattr(e, "aksiyon_etiket", None) or "—",
        } for e in tarama.endeksler])
        render_df_table(detay_df, max_height=220)

    on_plani = yonetici_oncelikli(tarama.hisseler, n=5)
    if on_plani:
        st.subheader("Öncelikli plan")
        render_df_table(pd.DataFrame([
            {
                **favori_yildiz_sutunu(favori_hisse_turu(h), h.sembol),
                **_hisse_satir_oncelik(
                    h, gpb, fx,
                    sembol_key="Ticker",
                    sembol_val=h.sembol.split(".")[0],
                    ad_key="Ad",
                    ad_val=(h.ad or "")[:36],
                    fiyat_kol=fiyat_kol,
                    fiyat_val=_hisse_tablo_fiyat(h, gpb, fx),
                ),
                "Veri": _hisse_veri_kolonu(h, gpb, fx),
            }
            for h in on_plani
        ]), max_height=220)
        st.divider()

    _v2_ui = _v2_aktif()
    st.caption(hisse_lejant_caption())
    with st.expander("Sözlük / nasıl okunur?", expanded=False):
        st.markdown(hisse_sozluk_expander_markdown())

    st.subheader(
        "ETF — AL adayları" if _v2_ui else "ETF — alım adayları"
    )
    etf_firsat = getattr(tarama, "etf_firsatlari", None) or []
    if etf_firsat:
        etf_df = pd.DataFrame([{
            **favori_yildiz_sutunu(favori_hisse_turu(h), h.sembol),
            **_hisse_satir_oncelik(
                h, gpb, fx,
                sembol_key="Ticker",
                sembol_val=h.revolut_ticker or h.sembol.split(".")[0],
                ad_key="ETF",
                ad_val=(h.ad or "")[:32],
                fiyat_kol=fiyat_kol,
                fiyat_val=_hisse_tablo_fiyat(h, gpb, fx),
            ),
            "Skor": _skor_etiket(h, fx=fx),
            g1a: _hisse_tablo_getiri(h, h.degisim_1ay, gpb, 21, eur_s, usd_s, gbp_s),
            "RSI": round(h.rsi, 0) if h.rsi else None,
            "Veri": _hisse_veri_kolonu(h, gpb, fx),
        } for h in etf_firsat])
        etf_meta = [(favori_hisse_turu(h), h.sembol, h.ad or h.sembol) for h in etf_firsat]
        render_df_table_favorili(etf_df, etf_meta, key_prefix="hisse_etf", max_height=400)
    else:
        st.info("ETF'lerde AL / GÜÇLÜ AL yok — VWCE/CSPX gibi çekirdek fonları izleme modunda tutun.")

    st.subheader(
        "AL / GÜÇLÜ AL adayları — öne çıkan hisseler"
        if _v2_ui
        else "Alım fırsatları — öne çıkan hisseler"
    )
    if _v2_ui:
        st.caption(
            "Liste yalnızca **Şimdi ne yap? = AL / GÜÇLÜ AL** satırlarından oluşur. "
            "Yalnızca buna göre almayı düşünün."
        )
    hisse_firsat = [h for h in (tarama.alim_firsatlari or []) if h.piyasa != "ETF"]
    if hisse_firsat:
        firsat_df = pd.DataFrame([{
            **favori_yildiz_sutunu("hisse", h.sembol),
            **_hisse_satir_oncelik(
                h, gpb, fx,
                sembol_key="Sembol",
                sembol_val=h.sembol,
                ad_key="Hisse",
                ad_val=(h.ad or "")[:28],
                fiyat_kol=fiyat_kol,
                fiyat_val=_hisse_tablo_fiyat(h, gpb, fx),
            ),
            "Skor": _skor_etiket(h, fx=fx),
            g1a: _hisse_tablo_getiri(h, h.degisim_1ay, gpb, 21, eur_s, usd_s, gbp_s),
            g3a: _hisse_tablo_getiri(h, h.degisim_3ay, gpb, 63, eur_s, usd_s, gbp_s),
            "RSI": round(h.rsi, 0) if h.rsi else None,
            "Veri": _hisse_veri_kolonu(h, gpb, fx),
            **_v2_tablo_ekstra(h),
        } for h in hisse_firsat])
        firsat_meta = [("hisse", h.sembol, h.ad or h.sembol) for h in hisse_firsat]
        render_df_table_favorili(firsat_df, firsat_meta, key_prefix="hisse_firsat", max_height=360)
        with st.expander("Fırsat gerekçeleri — detaylı oku", expanded=False):
            for h in hisse_firsat:
                satirlar = [h.hikaye or h.gerekce or ""]
                if h.rejim_notu and h.rejim_notu != "Rejim uyumlu":
                    satirlar.append(f"Rejim: {h.rejim_notu}")
                if h.profil_notu and h.profil_notu != "Profil uyumlu":
                    satirlar.append(f"Profil: {h.profil_notu}")
                if getattr(h, "faktor_notu", "") and h.faktor_notu not in ("", "Faktör nötr"):
                    satirlar.append(f"Faktör: {h.faktor_notu}")
                st.markdown(f"**{h.sembol}** — " + " · ".join(s for s in satirlar if s))
    else:
        st.info("Şu an AL / GÜÇLÜ AL yok — İZLE veya mevduat/altın ağırlıklı makro tahsise bakın.")

    if _v2_ui:
        _makro_kod = getattr(getattr(tahsis, "rejim", None), "rejim", "") or ""
        yakin = esige_yakin_sec(tarama.hisseler or [], _makro_kod)
        st.subheader("Eşiğe yakın — takip (şimdi alma)")
        st.caption(
            "Skor AL’ye yakın (≈62+) ve **Şimdi ne yap? = İZLE**. "
            "Hazırlan / favoriye ekle — **AL gelmeden alma.** "
            "KRIZ/EM_STRES veya düşen trendde liste boş kalır."
        )
        if yakin:
            yakin_df = pd.DataFrame([{
                **favori_yildiz_sutunu(favori_hisse_turu(h), h.sembol),
                **_hisse_satir_oncelik(
                    h, gpb, fx,
                    sembol_key="Sembol",
                    sembol_val=h.sembol,
                    ad_key="Ad",
                    ad_val=(h.ad or "")[:28],
                    fiyat_kol=fiyat_kol,
                    fiyat_val=_hisse_tablo_fiyat(h, gpb, fx),
                ),
                "Skor": _skor_etiket(h, fx=fx),
                "Veri": _hisse_veri_kolonu(h, gpb, fx),
            } for h in yakin])
            yakin_meta = [
                (favori_hisse_turu(h), h.sembol, h.ad or h.sembol) for h in yakin
            ]
            render_df_table_favorili(
                yakin_df, yakin_meta, key_prefix="hisse_yakin", max_height=280,
            )
        else:
            st.caption("Şu an eşiğe yakın aday yok (veya makro/rejim kapısı kapalı).")

    st.subheader("Tüm varlıklar (hisse + ETF)")
    st.caption("Tablodaki **★/☆** yıldıza tıklayın — favori ekle/çıkar (aynı bölümde kalır).")
    st.caption(hisse_lejant_caption())
    _tum_n = len(tarama.hisseler or [])
    _ozet = getattr(tarama, "tarama_ozet", "") or ""
    if _ozet:
        st.caption(f"Tarama: {_ozet}")
    else:
        st.caption(f"Tarama sonucu: **{_tum_n}** varlık (filtre öncesi).")

    f1, f2, f3 = st.columns([2, 2, 1])
    _sinyal_hepsi = list(SINYAL_ETIKET.keys())
    # Eski oturumda dar default kaldıysa genişlet (kullanıcı bilinçli daralttıysa dokunma)
    _prev = st.session_state.get("hisse_sinyal_filtre")
    if _prev is not None and set(_prev) == {"ALIM_FIRSATI", "TREND_ALIM", "BEKLE"}:
        st.session_state["hisse_sinyal_filtre"] = _sinyal_hepsi
    piyasa_filtre = f1.multiselect(
        "Piyasa",
        ["BIST", "SP500", "NASDAQ", "AVRUPA", "ETF", "EMTIA"],
        default=["BIST", "SP500", "NASDAQ", "AVRUPA", "ETF", "EMTIA"],
        key="hisse_piyasa_filtre",
    )
    sinyal_filtre = f2.multiselect(
        "Teknik sinyal (v1)",
        _sinyal_hepsi,
        default=_sinyal_hepsi,
        format_func=lambda x: SINYAL_ETIKET.get(x, x),
        key="hisse_sinyal_filtre",
        help="RSI/SMA teknik etiket. Varsayılan: tümü. Daraltırsanız Aşırı alım / Veri yok "
        "satırları gizlenir — tarama yine tam evrende yapılır.",
    )
    detay_sutun = f3.toggle("Detay sütunları", value=False, key="hisse_detay_sutun")
    if detay_sutun:
        st.caption(
            "**Peer %** (detay) = sektör içi **momentum** sırası — değerleme değildir. "
            "Sektör F/K peer → **Neden?** paneli / temel kapı soft bayrağı."
        )

    ara = st.text_input(
        "Ara (sembol veya ad)",
        value="",
        placeholder="Örn. MGR · Migros · NV · NVIDIA",
        key="hisse_tum_ara",
        help="En az 2 karakter: sembol veya hisse adında eşleşen satırlar.",
    )

    filtrelenmis = [
        h for h in tarama.hisseler
        if h.piyasa in piyasa_filtre and h.sinyal in sinyal_filtre
    ]
    _q = (ara or "").strip().casefold()
    if len(_q) >= 2:
        def _eslesir(h) -> bool:
            parcalar = (
                h.sembol or "",
                (h.sembol or "").split(".")[0],
                h.ad or "",
                getattr(h, "revolut_ticker", None) or "",
            )
            return any(_q in (p or "").casefold() for p in parcalar)

        filtrelenmis = [h for h in filtrelenmis if _eslesir(h)]
    filtrelenmis.sort(key=lambda h: (_UYGUN_SIRA.get(getattr(h, "alim_uygun", "IZLE"), 9), -h.skor))
    _gizli = _tum_n - len(filtrelenmis)
    if _q and len(_q) >= 2:
        if filtrelenmis:
            st.caption(
                f"Arama **«{ara.strip()}»** → **{len(filtrelenmis)}** satır "
                f"(piyasa/sinyal filtresi sonrası)."
            )
        else:
            st.info(f"«{ara.strip()}» ile eşleşen satır yok — aramayı kısaltın veya filtreleri genişletin.")
    elif _gizli > 0:
        st.info(
            f"Tabloda **{len(filtrelenmis)}** / taranan **{_tum_n}** satır · "
            f"**{_gizli}** satır filtreyle gizli (Piyasa / Teknik sinyal)."
        )
    else:
        st.caption(f"Tabloda **{len(filtrelenmis)}** / taranan **{_tum_n}** satır (filtre gizli yok).")

    def _satir(h, detay: bool) -> dict:
        tur = favori_hisse_turu(h)
        emtia = getattr(h, "piyasa", "") == "EMTIA" or getattr(h, "varlik_turu", "") == "emtia"
        gram = "—"
        spot_px, _spot_qc = _hisse_spot_fiyat(h)
        if emtia and spot_px and fx.usd_try:
            from emtia_universe import gram_tl_metin
            gram = gram_tl_metin(float(spot_px), float(fx.usd_try))
        temel = {
            **favori_yildiz_sutunu(tur, h.sembol),
            **_hisse_satir_oncelik(
                h, gpb, fx,
                sembol_key="Sembol",
                sembol_val=h.sembol,
                ad_key="Hisse/ETF",
                ad_val=(h.ad or "")[:28],
                fiyat_kol=fiyat_kol,
                fiyat_val=_hisse_tablo_fiyat(h, gpb, fx),
            ),
            "Skor": _skor_etiket(h, fx=fx),
            g1: _hisse_tablo_getiri(h, h.degisim_1g, gpb, 1, eur_s, usd_s, gbp_s),
            g1a: _hisse_tablo_getiri(h, h.degisim_1ay, gpb, 21, eur_s, usd_s, gbp_s),
            g3a: _hisse_tablo_getiri(h, h.degisim_3ay, gpb, 63, eur_s, usd_s, gbp_s),
            g1y: _hisse_tablo_getiri(h, h.degisim_1y, gpb, 252, eur_s, usd_s, gbp_s),
            "RSI": round(h.rsi, 1) if h.rsi else None,
            "Veri": _hisse_veri_kolonu(h, gpb, fx),
            "Gram TL": gram if emtia else "",
            **_v2_tablo_ekstra(h),
        }
        if not detay:
            return temel
        temel.update({
            "Sektör": SEKTOR_ETIKET.get(h.sektor, h.sektor),
            "Revolut": h.revolut_ticker or "",
            "SMA200": _hisse_tablo_fiyat(
                h, gpb, fx, fiyat=getattr(h, "sma200", None),
            ),
            "52H": format_52h_metin(h),
            "Peer %": round(h.peer_yuzdelik, 0) if getattr(h, "peer_yuzdelik", None) is not None else None,
            "Endeks farkı": round(h.endeks_gore, 1) if getattr(h, "endeks_gore", None) is not None else None,
            "Teknik skor": round(h.teknik_skor, 0) if h.teknik_skor else round(h.skor, 0),
            "ISIN": h.isin or "",
            "Rejim etkisi": (h.rejim_notu or "")[:60],
            "Profil etkisi": (getattr(h, "profil_notu", "") or "")[:60],
            "Faktör": (getattr(h, "faktor_notu", "") or "")[:60],
            "Trend filtresi": (getattr(h, "trend_notu", "") or "")[:60],
            "Haber": (h.haber_notu or "")[:50],
            "Hikaye": (h.hikaye or "")[:70],
            "Gerekçe": h.gerekce,
        })
        return temel

    hisse_df = pd.DataFrame([_satir(h, detay_sutun) for h in filtrelenmis])
    if "Emir" in hisse_df.columns:
        hisse_df = hisse_df.drop(columns=["Emir"])
    # Gram TL yalnızca emtia satırı varken göster
    if "Gram TL" in hisse_df.columns and not hisse_df["Gram TL"].astype(str).str.startswith("Gram").any():
        hisse_df = hisse_df.drop(columns=["Gram TL"])
    tum_meta = [(favori_hisse_turu(h), h.sembol, h.ad or h.sembol) for h in filtrelenmis]
    from karar_lejant import HISSE_AKSIYON_SUTUN, karar_dagilim_ozeti
    _karar_ozet = karar_dagilim_ozeti(
        [_karar_etiket(h) for h in filtrelenmis]
    ) if filtrelenmis else ""
    if _karar_ozet:
        st.caption(f"**{HISSE_AKSIYON_SUTUN} dağılımı (tabloda):** {_karar_ozet}")

    # Tablo ÖNCE — PDF her rerun'da üretilmesin (boş ekran sebebi)
    render_df_table_favorili(hisse_df, tum_meta, key_prefix="hisse_tum", max_height=560)

    _pdf_sol, _pdf_sag = st.columns([1.35, 5])
    with _pdf_sol:
        if st.button(
            "PDF hazırla",
            key="hisse_tum_pdf_hazirla",
            disabled=hisse_df.empty,
            help="Filtrelenmiş tabloyu PDF üretir — sonra indir.",
        ):
            with st.spinner("PDF hazırlanıyor…"):
                st.session_state["hisse_tum_pdf_bytes"] = hisse_etf_tablo_pdf_olustur(
                    hisse_df,
                    gosterim_pb=gpb,
                    profil_ozet=profil_ozet,
                    piyasa_filtre=piyasa_filtre,
                    sinyal_filtre=[SINYAL_ETIKET.get(s, s) for s in sinyal_filtre],
                    detay_sutun=detay_sutun,
                    veri_ozet=getattr(tarama, "veri_ozet_log", "") or "",
                )
                st.session_state["hisse_tum_pdf_name"] = (
                    f"tum_varliklar_hisse_etf_{pd.Timestamp.now():%Y-%m-%d}.pdf"
                )
        _pdf_bytes = st.session_state.get("hisse_tum_pdf_bytes")
        if _pdf_bytes:
            st.download_button(
                "PDF indir",
                data=_pdf_bytes,
                file_name=st.session_state.get(
                    "hisse_tum_pdf_name", "tum_varliklar_hisse_etf.pdf"
                ),
                mime="application/pdf",
                key="hisse_tum_pdf_indir",
            )

    # Önbellek — otomatik dolar; buton yalnızca acil zorla
    with st.expander("Önbellek durumu", expanded=False):
        try:
            from background_cache import status_caption_parts

            st.caption(status_caption_parts(_analist_syms or None))
        except Exception:
            pass
        st.caption(
            "Liste açılınca eksik analist verisi **otomatik senkron** doldurulur "
            "(progress bar görünür). Buton yalnızca yarıda kalan / TTL sonrası acil tazeleme içindir."
        )
        if st.button("Analist cache zorla doldur", key="hisse_temel_cache_doldur"):
            try:
                st.session_state["_analist_autofill_rounds"] = 0
                st.session_state.pop("_analist_autofill_key", None)
                _temel_cache_tarama_doldur(
                    getattr(tarama, "hisseler", None) or [], force=True,
                )
                st.rerun()
            except Exception as e:
                st.caption(f"Analist cache atlandı: {e}")

    if _v2_aktif():
        with st.expander("Neden? — Signal Engine v2 açıklaması", expanded=False):
            v2_list = [h for h in filtrelenmis if getattr(h, "signal_v2_score", None) is not None]
            if v2_list:
                sembol = st.selectbox(
                    "Varlık",
                    [h.sembol for h in v2_list],
                    format_func=lambda s: s.split(".")[0],
                    key="signal_v2_neden_sembol",
                )
                secili = next(h for h in v2_list if h.sembol == sembol)
                st.markdown(why_markdown(secili))
                # Aşama 2A — değerleme notu (skora girmez)
                try:
                    from temel_veri import (
                        format_degerleme_markdown,
                        get_temel,
                        temel_veri_notu,
                    )
                    tur = (
                        "etf"
                        if getattr(secili, "piyasa", "") == "ETF"
                        or getattr(secili, "varlik_turu", "") == "etf"
                        else "hisse"
                    )
                    fiyat_eur = tablo_fiyat(
                        secili.fiyat, "EUR", fx.eur_try, fx.usd_try,
                        sembol=secili.sembol,
                        piyasa=getattr(secili, "piyasa", ""),
                        varlik_turu=getattr(secili, "varlik_turu", ""),
                        quote_currency=getattr(secili, "quote_currency", "") or "",
                        gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd,
                        chf_usd=getattr(fx, "chf_usd", None),
                    )
                    temel = get_temel(secili.sembol)
                    notu = temel_veri_notu(
                        secili.sembol, temel, fiyat_eur,
                        tur=tur,
                        eur_try=fx.eur_try, usd_try=fx.usd_try,
                        gbp_usd=fx.gbp_usd, eur_usd=fx.eur_usd,
                        chf_usd=getattr(fx, "chf_usd", None),
                    )
                    st.markdown(format_degerleme_markdown(notu))
                    if tur == "hisse":
                        from signal_engine.quality.fund_gate import (
                            evaluate_fund_gate,
                            format_sirket_ozeti_markdown,
                        )
                        peer_val = getattr(secili, "signal_v2_peer_val", None)
                        gate = evaluate_fund_gate(temel, secili, peer=peer_val)
                        st.markdown(
                            format_sirket_ozeti_markdown(
                                temel, gate=gate, peer=peer_val,
                            )
                        )
                        fund_note = getattr(secili, "signal_v2_fund_note", "") or ""
                        if fund_note:
                            st.warning(fund_note)
                        st.caption(
                            "Temel kapı AL/GÜÇLÜ AL’yi İZLE’ye çekebilir "
                            "(negatif FCF+zarar, aşırı kaldıraç, analist sat, "
                            "sektör F/K pahalı soft, ≥2 soft bayrak). "
                            "Eksik Yahoo / küçük akran grubunda peer kapısı uygulanmaz."
                        )
                    # Aşama 2B — AI açıklama (yalnızca tıklanınca; skora girmez)
                    if st.button(
                        "✨ AI Analiz",
                        key=f"ai_analiz_{secili.sembol}",
                        help="Claude ile 2–3 cümlelik not (cache 24 saat)",
                    ):
                        from llm_aciklama import format_ai_markdown, hisse_aciklamasi

                        faktorler = getattr(secili, "signal_v2_factors", None) or {}
                        karar = getattr(secili, "signal_v2_decision", "") or _karar_etiket(secili)
                        skor = int(round(getattr(secili, "signal_v2_score", None) or secili.skor or 0))
                        g1y = getattr(secili, "degisim_1y", None)
                        if g1y is None:
                            g1y = getattr(secili, "getiri_1y", None) or 0.0
                        rejim = getattr(secili, "signal_v2_regime", "") or getattr(
                            tahsis, "rejim", None
                        )
                        rejim_s = getattr(rejim, "rejim", None) or str(rejim or "—")
                        with st.spinner("AI analiz üretiliyor…"):
                            metin, meta = hisse_aciklamasi(
                                secili.sembol,
                                karar,
                                skor,
                                faktorler,
                                notu,
                                float(fiyat_eur or 0),
                                float(g1y or 0),
                                rejim_s,
                            )
                        st.markdown(format_ai_markdown(metin, meta))
                        if meta.get("cache_hit"):
                            st.caption("cache hit")
                        st.caption(
                            "Yasal uyarı: Bu metin otomatik üretilmiştir; yatırım tavsiyesi değildir."
                        )
                except Exception as exc:
                    st.caption(f"Değerleme notu alınamadı: {exc}")
                from signal_engine.quality.degeneracy import debug_threshold_report
                with st.expander("Eşik mesafeleri (debug)", expanded=False):
                    st.markdown(debug_threshold_report(secili))
            else:
                st.caption("V2 skor verisi yok — taramayı yenileyin.")

    with st.expander("Şimdi ne yap? kodları ve metodoloji", expanded=False):
        if _v2_aktif():
            from karar_lejant import v2_lejant_markdown
            st.markdown(v2_lejant_markdown())
            st.markdown(
                "- Skor eşikleri (yaklaşık): **GÜÇLÜ AL** ≥76 · **AL** ≥64 · **İZLE** ≥52 · "
                "**BEKLE** ≥42 · **AZALT** <42\n"
                "- Skor = 5 faktör ağırlıklı bileşik; sınıf içi % = aynı varlık sınıfında sıra\n"
                "- **Şimdi ne yap?** = skor eşiği + **histerezis (H=2)** + fiyat rejimi kapıları "
                "(TRENDING_DOWN → İZLE) + **makro KRIZ/EM_STRES → AL yasak** + "
                "**temel finans kapısı** (FCF/zarar/kaldıraç/analist/sektör F/K peer soft → AL kesilebilir)\n"
                "- Öne çıkan liste = yalnızca **AL / GÜÇLÜ AL**; eşiğe yakın = takip, alma\n"
                "- **Momentum** ≠ aksiyon — ▲ tek başına alım gerekçesi değildir\n"
                "- **Özet (T/A/H)** gösterimdir — AL kararını değiştirmez\n"
                "- İZLE (WATCH) yönetici aksiyonu **BEKLE** — kademeli alım yok\n"
                "- Tek hisse SMA200/52H kapıları **v2 kapalıyken** geçerli; ETF'lere uygulanmaz\n"
            )
        else:
            from karar_lejant import v1_lejant_markdown
            st.markdown(v1_lejant_markdown())
            st.markdown(
                "- **Şimdi ne yap? = AL** (tek hisse): AL/TREND sinyali, SMA200 üstü, 52H zirveye yakın değil, "
                "1–3 ay momentum uygun — **ETF/hisse ayrımı:** yalnız tek hisse\n"
            )
        st.markdown(
            "- **Portföy Tahsisi / makro rejim:** TL fırsat, ENFLASYON, CDS, TL makro haber riski "
            "(faiz indirimi beklentisi, erken seçim) — tahsis ağırlıkları ve `Rejim` sütunu\n"
            "- **Portföy Tahsisi** BIST: yalnızca **AL** adaylarından skor sırası "
            "(kısa vadede en fazla 1 hisse). Varlıklarım'dan bağımsızdır.\n"
            "- Evren: BIST/SP500/NASDAQ blue-chip + Revolut UCITS ETF (~23) + spot emtia (GC=F/SI=F)\n"
            "- RSI dip bölgesi (teknik v1): RSI 28–45 bandı — dönüş teyidi (higher low) yok; "
            "veya SMA50 üstü trend (skor ≥55)\n"
            "- Rejim: TL fırsat → küresel ETF + · ENFLASYON → altın/tahvil ETF +"
        )


def _onbellek_temizle():
    veri_onbellegi_temizle()
    onbellek_gecersiz_kil()


if otoyenile:
    tick = st_autorefresh(interval=aralik_dk * 60 * 1000, key="piyasa_autorefresh")
    if tick > st.session_state.son_yenileme_sayaci:
        st.session_state.son_yenileme_sayaci = tick
        _onbellek_temizle()

if yenile:
    st.session_state.son_yenileme_sayaci += 1
    st.session_state["_tarama_zorla"] = True
    st.session_state["_sistem_boot_ok"] = False
    st.session_state["_boot_force"] = True
    st.session_state.pop("_boot_ctx", None)
    st.session_state["_analist_autofill_rounds"] = 0
    _onbellek_temizle()
    st.session_state["_son_yenileme_toast"] = True

if boot_zorla:
    st.session_state["_sistem_boot_ok"] = False
    st.session_state["_boot_force"] = True
    st.session_state.pop("_boot_ctx", None)
    st.session_state["_analist_autofill_rounds"] = 0
    _onbellek_temizle()
    st.rerun()


_tick = st.session_state.son_yenileme_sayaci
_profil_anahtar = f"{profil.risk}_{profil.vade}_{profil.amac}"
if st.session_state.get("tarama_profil_key") != _profil_anahtar:
    st.session_state.tarama_profil_key = _profil_anahtar
    onbellek_gecersiz_kil()

# ── Film tarzı açılış: her dilimde UI yenilenir (analist sabit kalmaz) ──
if not st.session_state.get("_sistem_boot_ok"):
    from boot_sequence import _new_ctx, advance_boot, boot_ui_state
    from boot_ui import boot_placeholders, update_boot

    if "_boot_ctx" not in st.session_state:
        st.session_state["_boot_ctx"] = _new_ctx(
            canli=canli_mod,
            force=bool(st.session_state.pop("_boot_force", False)),
            profil_risk=profil.risk,
            profil_vade=profil.vade,
            use_signal_v2=bool(st.session_state.get("use_signal_v2", True)),
        )

    _boot_ctx = st.session_state["_boot_ctx"]
    _boot_frame = boot_placeholders()
    def _paint(ui: dict) -> None:
        update_boot(
            _boot_frame,
            active_id=ui["active_id"],
            done_ids=ui["done_ids"],
            detail=ui["detail"],
            pct=ui["pct"],
            counter=ui.get("counter") or "",
            counter_label=ui.get("counter_label") or "",
        )

    _paint(boot_ui_state(_boot_ctx))
    _boot_ctx = advance_boot(_boot_ctx)
    st.session_state["_boot_ctx"] = _boot_ctx
    _paint(boot_ui_state(_boot_ctx))

    if _boot_ctx.get("complete"):
        st.session_state["_sistem_boot_ok"] = True
        st.session_state["_boot_summary"] = _boot_ctx.get("summary") or {}
        st.session_state.pop("_boot_ctx", None)
        st.rerun()
    else:
        # Sonraki dilim — yüzde / sembol satırı hareket eder
        st.rerun()

_bs = st.session_state.get("_boot_summary") or {}
_mod_lbl = "Canlı" if canli_mod else "Demo"
_status_bits = [f"**{_mod_lbl}**", profil.ozet()]
if _bs.get("elapsed_sec") is not None:
    _status_bits.append(f"açılış {_bs['elapsed_sec']:.0f}s")
st.caption(" · ".join(_status_bits))

_ob = uygulama_onbellegi_al(
    canli_mod=canli_mod,
    tick=_tick,
    profil=profil,
    profil_anahtar=_profil_anahtar,
    kp=kullanici_portfoy,
    haber_tara=st.session_state.hisse_haber_tara,
    bt_ay=bt_ay,
)
if st.session_state.pop("_son_yenileme_toast", False):
    st.toast(f"Veriler güncellendi · {_ob.yukleme_zamani}", icon="🔄")

snap = _ob.snap
tahsis = _ob.tahsis
tarama_ozet = _ob.tarama
mevduat_ozet = _ob.mevduat_ozet
danisman = _ob.danisman
tl_durum = _ob.tl_durum
profil_mevduat_etiket = _ob.profil_mevduat_etiket
profil_mevduat_gun = _ob.profil_mevduat_gun
birlesik = _ob.birlesik


def _sayfa_onbellegi_hazirla(ob):
    """Aktif sekme için ağır veriyi yükle."""
    return onbellek_sayfa_hazirla(
        ob,
        sayfa,
        canli_mod=canli_mod,
        tick=_tick,
        profil=profil,
        kp=kullanici_portfoy,
        haber_tara=st.session_state.hisse_haber_tara,
        bt_ay=bt_ay,
    )


_eur_try = snap.veri.eur_try or 35.0
config.TOPLAM_EUR = kullanici_portfoy.toplam_eur(_eur_try)
toplam_eur = config.TOPLAM_EUR
_mev_poz = kullanici_portfoy.mevcut_tl_mevduat()
tl_mevduat_arg = float(_mev_poz.tutar) if _mev_poz else None


def _tutar_pb(eur_tutar: float) -> tuple:
    if kullanici_portfoy.para_birimi == "TL":
        return eur_tutar * _eur_try, "TL"
    return eur_tutar, "EUR"

def _rapor_paketi_hazirla(tarama_rapor):
    return rapor_paketi_olustur(
        snap,
        tahsis,
        profil,
        danisman,
        mevduat_ozet,
        tl_durum,
        toplam_eur,
        tarama_rapor,
        tl_mevduat_tutar_tl=tl_mevduat_arg,
        birlesik_oneri=birlesik,
        varlik_store=_ob.varlik_store,
        kullanici_portfoy=kullanici_portfoy,
        para_birimi=kullanici_portfoy.para_birimi,
    )

with st.sidebar:
    st.divider()
    st.subheader("Anlık yatırım raporu")
    st.caption("Makro + tarama + öneri detayı + Varlıklarım pozisyonları")

    if st.button(
        "Yatırım raporu oluştur",
        type="primary",
        use_container_width=True,
        key="rapor_olustur",
    ):
        try:
            with st.spinner("Rapor hazırlanıyor…"):
                tarama_rapor = st.session_state.tarama_son
                if tarama_rapor is None:
                    tarama_rapor = tarama_cek(
                        canli_mod, tahsis.rejim.rejim, snap.veri_kaynak, _tick,
                        haber_tara=st.session_state.hisse_haber_tara,
                        **_tarama_param(profil),
                    )
                    st.session_state.tarama_son = tarama_rapor
                st.session_state.son_rapor = _rapor_paketi_hazirla(tarama_rapor)
            st.session_state.rapor_hata = None
            st.toast("PDF rapor hazır — indirin", icon="✅")
        except Exception as exc:
            st.session_state.son_rapor = None
            st.session_state.rapor_hata = str(exc)

    if st.session_state.rapor_hata:
        st.error(f"Rapor oluşturulamadı: {st.session_state.rapor_hata}")

    if st.session_state.son_rapor:
        rp = st.session_state.son_rapor
        st.success("PDF rapor hazır")
        st.download_button(
            "⬇ PDF raporu indir",
            data=rp["pdf"],
            file_name=rp["pdf_dosya"],
            mime="application/pdf",
            use_container_width=True,
            key="dl_rapor_pdf",
        )

# Rejim değişince bildir
if st.session_state.onceki_rejim and st.session_state.onceki_rejim != tahsis.rejim.rejim:
    st.toast(f"Rejim değişti → {tahsis.rejim.etiket}", icon="⚠️")
st.session_state.onceki_rejim = tahsis.rejim.rejim

if st.session_state.son_rapor:
    with st.expander("Son yatırım raporu — önizleme", expanded=False):
        rp = st.session_state.son_rapor
        st.download_button(
            "⬇ PDF indir",
            data=rp["pdf"],
            file_name=rp["pdf_dosya"],
            mime="application/pdf",
            key="dl_rapor_main",
        )
        st.components.v1.html(rp["html"], height=520, scrolling=True)

if otoyenile:
    st.caption(f"🔄 Otomatik yenileme: **{aralik_dk} dk** · Son çekim: **{snap.veri_zamani}**")
else:
    st.caption(f"Son çekim: **{snap.veri_zamani}** · Otomatik yenileme kapalı")

durum_metin = (
    "Demo modu — makro senaryo sabit, piyasa fiyatları canlı."
    if snap.veri_kaynak == "demo"
    else "Canlı veri aktif — her yenilemede API'den taze çekilir (Yahoo, EVDS, TCMB.gov, Yapı Kredi)."
)
if snap.veri_kaynak == "demo":
    st.info(f"**{durum_metin}**")
else:
    render_live_banner(durum_metin, live=True)

# ══════════════════════════════════════════════════════════════
if sayfa == "Portföy Tahsisi":
    render_page_header(
        "Portföy Tahsisi",
        f"{'Canlı' if canli_mod else 'Demo'} · {VADE_SECENEKLERI.get(profil.vade, profil.vade)}",
    )
    render_metric_strip([
        {"label": "Makro rejim", "value": tahsis.rejim.etiket.replace("_", " ")},
        {
            "label": "EUR/TRY",
            "value": f"{snap.veri.eur_try:.2f}" if snap.veri.eur_try else "—",
            "delta": snap.eur_try_1g_degisim,
        },
        *(
            [
                {
                    "label": f"TL faiz ({profil_mevduat_etiket})",
                    "value": f"%{mevduat_ozet.profil_vade_net:.1f} net" if mevduat_ozet.profil_vade_net else "—",
                    "delta": f"reel {mevduat_ozet.profil_vade_reel:+.1f}%",
                },
                {
                    "label": "CDS 5Y (ref.)",
                    "value": f"{snap.veri.cds_5y_bp:.0f} bp" if snap.veri.cds_5y_bp else "—",
                },
            ]
            if vade_kisa_mi(profil.vade)
            else [
                {
                    "label": "CDS 5Y",
                    "value": f"{snap.veri.cds_5y_bp:.0f} bp" if snap.veri.cds_5y_bp else "—",
                },
                {
                    "label": f"TL faiz ({profil_mevduat_etiket})",
                    "value": f"%{mevduat_ozet.profil_vade_net:.1f} net" if mevduat_ozet.profil_vade_net else "—",
                },
            ]
        ),
        {
            "label": "VIX (ABD)",
            "value": f"{snap.vix:.1f}" if snap.vix is not None else "—",
            "delta": snap.vix_1g_degisim,
            "delta_inverse": True,
        },
        {
            "label": "Altın",
            "value": f"${snap.altin_usd_oz:,.0f}" if snap.altin_usd_oz is not None else "—",
            "delta": snap.altin_1g_degisim,
        },
        {
            "label": "BIST",
            "value": f"{snap.bist100:,.0f}" if snap.bist100 is not None else "—",
            "delta": snap.bist100_1g_degisim,
        },
        {
            "label": "BIST Vol (TR)",
            "value": f"{snap.bist_vol_30g:.1f}" if snap.bist_vol_30g is not None else "—",
            "delta": snap.bist_vol_1g_degisim,
            "delta_fmt": "pp",
            "delta_inverse": True,
        },
    ])
    if not vade_kisa_mi(profil.vade):
        btc_delta = _gunluk_delta(snap.btc_1g_degisim)
        btc_line = f"BTC: ${snap.btc_usd:,.0f}" if snap.btc_usd is not None else "BTC: —"
        if btc_delta:
            btc_line += f" ({btc_delta} 1G)"
        st.caption(btc_line)

    st.caption(rejim_gosterim_metni(tahsis.rejim, tahsis.tl_tavan_oran))
    if (
        tahsis.rejim.rejim == "TL_FIRSAT"
        and tahsis.tl_tavan_oran >= 0.05
        and "askıda" not in tahsis.rejim.etiket
    ):
        tl_p = tahsis.agirliklar.get("tl_deposit", 0) * 100
        bist_p = tahsis.agirliklar.get("bist", 0) * 100
        kripto_p = tahsis.agirliklar.get("crypto", 0) * 100
        if profil.risk == "yuksek" and profil.vade == "uzun":
            st.caption(
                f"TL cazip (makro) · portföy BIST %{bist_p:.0f} · kripto %{kripto_p:.0f} · TL %{tl_p:.0f}"
            )
        elif vade_kisa_mi(profil.vade):
            st.caption("Kısa vade: TL/EUR öncelikli.")

    st.caption(
        f"TL: {tl_durum.baslik} · pay %{tl_durum.agirlik_pct:.1f} · tavan %{tl_durum.tavan_pct:.0f}"
    )
    with st.expander("TL kararı detayı", expanded=False):
        if tl_durum.baglayici_etiket:
            st.caption(
                f"Bağlayıcı: {tl_durum.baglayici_etiket} ({tl_durum.baglayici_kisit})"
            )
        for n in tl_durum.nedenler:
            st.markdown(f"- {n}")
        if tl_durum.alternatif:
            st.caption(f"Alternatif: {tl_durum.alternatif}")
        if tl_durum.explain:
            import pandas as pd
            st.dataframe(
                pd.DataFrame(tl_durum.explain),
                use_container_width=True,
                hide_index=True,
            )
        if tahsis.tl_ppk_notu:
            st.caption(tahsis.tl_ppk_notu)

    if tahsis.profil_notlari:
        with st.expander("Profilinize göre değerlendirme", expanded=False):
            for n in tahsis.profil_notlari:
                st.write(f"• {n}")

    _ozet_kisa = (danisman.genel_ozet or "").strip()
    if _ozet_kisa:
        _cumleler = [c.strip() for c in _ozet_kisa.replace("\n", " ").split(".") if c.strip()]
        st.caption(". ".join(_cumleler[:2]) + ("." if _cumleler[:2] else ""))
    with st.expander("Danışman özeti", expanded=False):
        st.markdown(danisman.genel_ozet)
        o1, o2, o3 = st.columns(3)
        for col, v in zip([o1, o2, o3], danisman.varliklar[:3]):
            with col:
                st.metric(f"{v.ok} {v.ad.split()[0]}", f"%{v.agirlik_pct:.0f}", v.sinyal_etiket)
        st.caption("Detay: **AI Danışman**")

    st.divider()
    _ob = _sayfa_onbellegi_hazirla(_ob)
    birlesik = _ob.birlesik

    @st.fragment(run_every=8)
    def _portfoy_bist_otoyenile():
        ob = st.session_state.get("app_onbellek")
        if ob is None:
            return
        # Zaten tamam → dur
        if ob.birlesik_tarama_hazir:
            return
        # Tarama hiç başlamadıysa → bekle
        if ob.tarama is None:
            return
        # Tarama yükleniyor (placeholder) VEYA tarama bitti ama birleşik güncellenmedi
        # → disk önbelleğini kontrol et; arka plan tamamlandıysa veriyi al
        from app_onbellek import onbellek_sayfa_hazirla as _osh
        _osh(
            ob,
            "Portföy Tahsisi",
            canli_mod=canli_mod,
            tick=_tick,
            profil=profil,
            kp=kullanici_portfoy,
            haber_tara=st.session_state.hisse_haber_tara,
            bt_ay=bt_ay,
        )
        st.session_state.birlesik_oneri = ob.birlesik
        if ob.birlesik_tarama_hazir:
            st.rerun()

    if not _ob.birlesik_tam or (not _ob.birlesik_tarama_hazir and not tarama_yukleniyor(_ob.tarama)):
        with st.spinner("TEFAS ve BIST önerileri hazırlanıyor (ilk seferde ~1 dk, sonrası anında)…"):
            _ob = _sayfa_onbellegi_hazirla(_ob)
            birlesik = _ob.birlesik
    _portfoy_bist_otoyenile()
    birlesik_oneri_paneli(
        birlesik,
        para_birimi=kullanici_portfoy.para_birimi,
        vade_etiket=VADE_SECENEKLERI.get(profil.vade, profil.vade),
        snap=snap,
        tarama=_ob.tarama,
    )
    oneri_aktar_butonu(
        _ob.varlik_store,
        birlesik,
        kullanici_portfoy.para_birimi,
        mevcut_mevduat=kullanici_portfoy.mevcut_tl_mevduat(),
    )

    tl_oneri = tahsis.agirliklar.get("tl_deposit", 0) * 100
    tl_ef = getattr(tahsis, "tl_efektif_tavan", None)
    tl_ef_pct = (tl_ef * 100) if tl_ef is not None else tahsis.tl_tavan_oran * 100
    with st.expander("Makro göstergeler", expanded=False):
        render_metric_strip([
            {
                "label": "USD/TRY",
                "value": f"{snap.veri.usd_try:.2f}" if snap.veri.usd_try else "—",
            },
            {
                "label": "Fed",
                "value": f"{snap.veri.fed_faizi:.2f}%" if snap.veri.fed_faizi is not None else "—",
            },
            {
                "label": "Enflasyon TR",
                "value": f"{snap.enflasyon_tr_yillik:.2f}%" if snap.enflasyon_tr_yillik is not None else "—",
            },
            {
                "label": "TL öneri / tavan",
                "value": f"%{tl_oneri:.0f} / %{tl_ef_pct:.0f}",
            },
            {
                "label": "Siyasi risk",
                "value": str(snap.veri.siyasi_risk_makale_sayisi or "—"),
            },
            {
                "label": "TCMB rezerv",
                "value": (
                    "↑" if snap.veri.rezerv_artiyor
                    else "↓" if snap.veri.rezerv_artiyor is False
                    else "?"
                ),
            },
        ])
        _bist_not = getattr(tahsis, "bist_sinyal_notu", "") or ""
        if _bist_not:
            st.caption(_bist_not)
        st.caption(
            f"TL bağlayıcı: {getattr(tahsis, 'tl_baglayici_etiket', None) or '—'} · "
            f"tavan %{tahsis.tl_tavan_oran*100:.0f} · etkin %{tl_ef_pct:.0f}"
        )

    t1, t2, t3 = st.tabs(["Algoritma", "Tam rapor", "Geçmiş kayıtlar"])
    with t1:
        for adim in tahsis.adimlar:
            st.write(f"• {adim}")
        if tahsis.uyarilar:
            st.warning("\n".join(tahsis.uyarilar))
    with t2:
        st.success(tahsis.tavsiye_metni)
        st.code(portfoy_raporu_olustur(snap, tahsis), language=None)
    with t3:
        gecmis = cache_gecmisi(20)
        if gecmis:
            render_df_table(pd.DataFrame([
                {"Zaman": g["ts"], "EUR/TRY": g["payload"].get("veri", {}).get("eur_try"),
                 "CDS": g["payload"].get("veri", {}).get("cds_5y_bp")}
                for g in gecmis
            ]))
        else:
            st.caption("Canlı modda otomatik kaydedilir.")

    st.divider()
    with st.expander("Veri kalitesi & kaynak şeffaflığı"):
        vk = veri_kalite_olustur(snap)
        k1, k2, k3 = st.columns(3)
        k1.metric("Kalite skoru", f"{vk.genel_skor:.0f}/100")
        k2.metric("Düzey", vk.genel_duzey)
        k3.metric("Mod", vk.mod.upper())
        st.caption(vk.ozet)
        for u in vk.uyarilar:
            st.warning(u)
        render_df_table(pd.DataFrame([{
            "Gösterge": g.etiket,
            "Değer": g.deger_gosterim,
            "Kalite": g.kalite_etiket,
            "Kaynak": g.kaynak,
            "Tazelik": f"{g.tazelik_saat:.0f} saat" if g.tazelik_saat is not None else "—",
            "Durum": g.tazelik_durum,
            "Eksikte": g.eksik_politikasi[:80],
        } for g in vk.gostergeler]), max_height=400)
        st.caption(f"Son güncelleme: {snap.veri_zamani}")

    with st.expander("CDS 5Y — Bloomberg + Investing (otomatik)"):
        from cds_bloomberg import bloomberg_terminal_erisimli

        kh = snap.kaynak_haritasi or {}
        _r1, _r2, _r3 = st.columns(3)
        _r1.metric("Rejimde kullanılan", f"{snap.veri.cds_5y_bp:.0f} bp" if snap.veri.cds_5y_bp else "—")
        _r2.metric("Bloomberg", "Bağlı" if bloomberg_terminal_erisimli() else "Yok")
        _r3.metric("Investing ham", kh.get("cds_ham", "—")[:20])
        st.caption(f"Kaynak: {kh.get('cds', '—')}")
        for u in [x for x in (snap.cekim_uyarilari or []) if "CDS" in x or "Bloomberg" in x or "Investing" in x]:
            st.warning(u)
        _s = st.session_state.get("cds_son_kaynak") or cds_kaynak_ozet(_tick)
        render_df_table(
            pd.DataFrame([
                {
                    "Kaynak": k.ad,
                    "Değer (bp)": f"{k.deger:.2f}" if k.deger is not None else "—",
                    "Gecikme": f"+{k.gecikme_gun}g" if k.gecikmeli else "—",
                    "Detay": k.kaynak or k.hata,
                }
                for k in _s.kaynaklar
            ]),
        )
        for u in _s.uyarilar:
            st.warning(u)
        cds_sol, cds_sag = st.columns(2)
        with cds_sol:
            st.caption(
                "CDS manuel girilmez. **Investing.com** her yenilemede otomatik çekilir. "
                "**Bloomberg** için Terminal açık olmalı (`pip install blpapi`)."
            )
        with cds_sag:
            if st.button("CDS kaynaklarını yenile", use_container_width=True):
                cds_kaynak_ozet.clear()
                st.session_state["cds_son_kaynak"] = cds_kaynak_ozet(_tick)
                veri_onbellegi_temizle()
                onbellek_gecersiz_kil()
                st.rerun()

# ══════════════════════════════════════════════════════════════
elif sayfa == "Karar Asistanı":
    from nakit_danisman import vade_sonu_plani, vadeli_mevduatlar, yeni_para_plani
    from karar_yorum import (
        format_karar_yorum_markdown,
        karar_ai_yorum,
        karar_baglam_ozeti,
    )
    from llm_client import provider_hint, provider_ready

    _ob = _sayfa_onbellegi_hazirla(_ob)

    render_page_header(
        "Karar Asistanı",
        "Dağılım planı + makro / endeks / AL adaylarıyla yönlendirme",
    )

    def _plan_ai_yorum(plan, *, key_suffix: str = "yeni") -> None:
        """Plan tablosu sonrası ücretsiz AI yorum (rakam değiştirmez)."""
        st.caption(
            "AI: makro + endeks + AL adayları + plan · rakamlar motordan · tavsiye değildir"
        )
        if not provider_ready():
            st.caption(provider_hint())
        else:
            from llm_client import provider_kota_caption
            st.caption(provider_kota_caption())
        if st.button("AI yorum al", key=f"ka_ai_{key_suffix}"):
            baglam = karar_baglam_ozeti(
                plan,
                snap=snap,
                tahsis=tahsis,
                mevduat_ozet=mevduat_ozet,
                tl_durum=tl_durum,
                tarama=_ob.tarama,
                danisman=danisman,
                varlik_store=_ob.varlik_store,
            )
            with st.spinner("AI yorum üretiliyor…"):
                metin, meta = karar_ai_yorum(baglam)
            st.session_state[f"ka_ai_metin_{key_suffix}"] = metin
            st.session_state[f"ka_ai_meta_{key_suffix}"] = meta
        metin = st.session_state.get(f"ka_ai_metin_{key_suffix}")
        meta = st.session_state.get(f"ka_ai_meta_{key_suffix}") or {}
        if metin:
            st.markdown(format_karar_yorum_markdown(metin, meta))

    def _plan_goster(plan, *, ai_key: str = "yeni") -> None:
        render_metric_strip([
            {"label": "Dağıtılacak", "value": f"{plan.tutar_tl:,.0f} TL"},
            {"label": "Mevcut portföy", "value": f"{plan.mevcut_toplam_tl:,.0f} TL"},
            {"label": "Yeni toplam", "value": f"{plan.yeni_toplam_tl:,.0f} TL"},
            {"label": "Rejim", "value": plan.rejim_etiket},
        ])
        render_df_table(pd.DataFrame([{
            "Tutar (TL)": f"{s.tutar_tl:,.0f}",
            "Pay": f"%{s.oran_pct:.0f}",
            "Varlık": s.etiket,
            "Mevcut → Hedef": f"%{s.mevcut_pct:.0f} → %{s.hedef_pct:.0f}",
            "Somut araç": s.arac,
            "Gerekçe": s.gerekce,
        } for s in plan.satirlar]))
        for n in plan.notlar:
            st.caption(n)
        _plan_ai_yorum(plan, key_suffix=ai_key)

    tab_yeni, tab_vade = st.tabs(["Yeni para", "Vadesi yaklaşanlar"])

    with tab_yeni:
        with st.form("yeni_para_form", border=False):
            c1, c2, c3 = st.columns([2, 1, 1])
            yp_tutar = c1.number_input(
                "Tutar",
                min_value=0.0,
                step=10_000.0,
                value=float(st.session_state.get("ka_son_tutar", 200_000.0)),
            )
            yp_pb = c2.selectbox("Para birimi", ["TL", "EUR", "USD"], index=0)
            c3.markdown("<br>", unsafe_allow_html=True)
            yp_hesapla = c3.form_submit_button("Plan oluştur", type="primary", use_container_width=True)

        if yp_hesapla and yp_tutar > 0:
            st.session_state.ka_son_tutar = float(yp_tutar)
            with st.spinner("Portföy dağılımı hesaplanıyor…"):
                plan = yeni_para_plani(
                    yp_tutar,
                    yp_pb,
                    snap,
                    tahsis,
                    varlik_store=_ob.varlik_store,
                    tarama=_ob.tarama,
                    mevduat_ozet=mevduat_ozet,
                )
            if plan is None or not plan.satirlar:
                st.warning("Plan oluşturulamadı — tutarı ve verileri kontrol edin.")
            else:
                st.session_state.ka_son_plan = plan
                st.session_state.pop("ka_ai_metin_yeni", None)
        if st.session_state.get("ka_son_plan"):
            _plan_goster(st.session_state.ka_son_plan, ai_key="yeni")

    with tab_vade:
        vadeliler = vadeli_mevduatlar(_ob.varlik_store)
        if not vadeliler:
            st.info(
                "Vade takibi için **Varlıklarım**’da TL mevduata **vade (gün)** girin."
            )
        for i, vb in enumerate(vadeliler):
            banka = vb.pozisyon.banka.strip() or "Banka"
            kalan_metin = (
                f"**vade doldu** ({vb.vade_tarihi.strftime('%d.%m.%Y')})"
                if vb.kalan_gun < 0
                else f"**{vb.kalan_gun} gün** kaldı ({vb.vade_tarihi.strftime('%d.%m.%Y')})"
            )
            st.markdown(
                f"#### {banka} — {vb.anapara_tl:,.0f} TL · %{vb.pozisyon.brut_faiz:.0f} brüt"
            )
            m1, m2, m3 = st.columns(3)
            m1.metric("Vadeye kalan", "Doldu" if vb.kalan_gun < 0 else f"{vb.kalan_gun} gün",
                      vb.vade_tarihi.strftime("%d.%m.%Y"), delta_color="off")
            m2.metric("Vade sonu net", f"{vb.net_tl:,.0f} TL",
                      f"+{vb.brut_faiz_tl - vb.stopaj_tl:,.0f} TL net faiz")
            m3.metric("Stopaj", f"−{vb.stopaj_tl:,.0f} TL")

            with st.expander(f"Bu para için yönlendirme planı — {kalan_metin}", expanded=vb.kalan_gun <= 7):
                with st.spinner("Plan hesaplanıyor…"):
                    vplan = vade_sonu_plani(
                        vb, snap, tahsis,
                        varlik_store=_ob.varlik_store,
                        tarama=_ob.tarama,
                        mevduat_ozet=mevduat_ozet,
                    )
                if vplan and vplan.satirlar:
                    _plan_goster(vplan, ai_key=f"vade{i}")
                else:
                    st.warning("Plan oluşturulamadı.")
            st.divider()

# ══════════════════════════════════════════════════════════════
elif sayfa == "Asistan":
    from asistan_chat import (
        HAZIR_SORULAR,
        PLAN_SORUSU,
        asistan_yanit,
        sistem_baglam_ozeti,
    )
    from llm_client import provider_hint, provider_kota_caption, provider_ready

    _ob = _sayfa_onbellegi_hazirla(_ob)
    danisman = _ob.danisman

    render_page_header(
        "Asistan",
        "Makro, tahsis, AL listesi, portföy ve plan hakkında soru-cevap",
    )

    head_l, head_r = st.columns([4, 1])
    with head_l:
        st.caption(
            "Yazılımın güncel verisiyle sohbet · rakamlar motordan · tavsiye değildir"
        )
        if provider_ready():
            st.caption(provider_kota_caption())
        else:
            st.caption(provider_hint())
    with head_r:
        if st.button("Sohbeti temizle", key="asistan_clear", use_container_width=True):
            st.session_state.asistan_messages = []
            st.session_state.pop("asistan_pending", None)
            st.rerun()

    # Tarama henüz yoksa net uyarı
    _tarama = _ob.tarama
    _tarama_bos = (
        _tarama is None
        or not list(getattr(_tarama, "hisseler", None) or [])
    )
    if _tarama_bos:
        st.info(
            "Tarama henüz yüklenmedi veya boş — AL/endeks sorularına sınırlı yanıt verilir. "
            "Hisse & ETF sayfasını bir kez açıp bekleyin, sonra buraya dönün."
        )

    if "asistan_messages" not in st.session_state:
        st.session_state.asistan_messages = []

    def _asistan_gonder(soru: str) -> None:
        soru = (soru or "").strip()
        if not soru:
            return
        st.session_state.asistan_messages.append({"role": "user", "content": soru})
        baglam = sistem_baglam_ozeti(
            snap=snap,
            tahsis=tahsis,
            mevduat_ozet=mevduat_ozet,
            tl_durum=tl_durum,
            tarama=_ob.tarama,
            danisman=danisman,
            varlik_store=_ob.varlik_store,
            varlik_deger=_ob.varlik_deger,
            tefas_ham=_ob.tefas_ham,
            plan=st.session_state.get("ka_son_plan"),
            user_msg=soru,
        )
        with st.spinner("Asistan yanıtlıyor…"):
            metin, meta = asistan_yanit(
                baglam,
                st.session_state.asistan_messages[:-1],
                soru,
            )
        st.session_state.asistan_messages.append({
            "role": "assistant",
            "content": metin,
            "meta": meta,
        })

    # Hazır soru / formdan gelen bekleyen mesaj
    pending = st.session_state.pop("asistan_pending", None)
    if pending:
        _asistan_gonder(str(pending))

    msgs = st.session_state.asistan_messages
    if not msgs:
        st.markdown(
            '<div class="mc-asistan-empty">'
            "<p>Merhaba — makro, tahsis, AL listesi ve portföyünüz hakkında sorun.</p>"
            "</div>",
            unsafe_allow_html=True,
        )
        chips = list(HAZIR_SORULAR)
        if st.session_state.get("ka_son_plan"):
            chips = chips + [PLAN_SORUSU]
        cols = st.columns(min(4, len(chips)))
        for i, q in enumerate(chips):
            with cols[i % len(cols)]:
                if st.button(q, key=f"asistan_chip_{i}", use_container_width=True):
                    st.session_state.asistan_pending = q
                    st.rerun()
    else:
        for msg in msgs:
            role = msg.get("role") or "assistant"
            with st.chat_message(role):
                st.markdown(msg.get("content") or "")
                meta = msg.get("meta") or {}
                if role == "assistant" and meta.get("hint"):
                    st.caption(f"{meta.get('hint')} · yatırım tavsiyesi değildir")

    st.markdown('<div class="mc-asistan-composer">', unsafe_allow_html=True)
    with st.form("asistan_form", clear_on_submit=True, border=False):
        c1, c2 = st.columns([5, 1])
        with c1:
            soru_in = st.text_input(
                "Mesajınız",
                placeholder="Örn: Bugün hangi hisseler önde? THYAO neden AL?",
                label_visibility="collapsed",
                key="asistan_input",
            )
        with c2:
            gonder = st.form_submit_button("Gönder", type="primary", use_container_width=True)
        if gonder and (soru_in or "").strip():
            st.session_state.asistan_pending = soru_in.strip()
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
elif sayfa == "Favorilerim":
    _ob = _sayfa_onbellegi_hazirla(_ob)
    favoriler_paneli(
        snap,
        tarama=_ob.tarama,
        tefas_ham=_ob.tefas_ham,
        profil=profil,
        rejim=tahsis.rejim.rejim,
    )

# ══════════════════════════════════════════════════════════════
elif sayfa == "Varlıklarım":
    aktif_vp = _ob.varlik_store.aktif()
    if aktif_vp and aktif_vp.pozisyonlar and _ob.varlik_deger is None:
        _ob = _sayfa_onbellegi_hazirla(_ob)
    varliklarim_paneli(
        snap,
        deger_onbellek=_ob.varlik_deger,
        onbellek_portfoy_id=_ob.varlik_deger_portfoy_id,
        veri_tick=_tick,
        yukleme_zamani=_ob.yukleme_zamani,
        tarama=_ob.tarama,
        tefas_ham=_ob.tefas_ham,
        profil=profil,
        rejim=tahsis.rejim.rejim,
        mevduat_ozet=mevduat_ozet,
    )

# ══════════════════════════════════════════════════════════════
elif sayfa == "AI Danışman":
    if not _ob.danisman_tam:
        _ob = _sayfa_onbellegi_hazirla(_ob)
        danisman = _ob.danisman
    danisman_paneli(danisman)

# ══════════════════════════════════════════════════════════════
elif sayfa == "TL Mevduat Faizleri":
    render_page_header(
        "TL Mevduat",
        f"Profil vade: {VADE_SECENEKLERI.get(profil.vade, profil.vade)} · {profil_mevduat_etiket}",
    )
    enf = snap.enflasyon_tr_yillik or 35.0
    mev = mevduat_ozet

    render_metric_strip([
        {"label": "Enflasyon (TR)", "value": f"%{mev.enflasyon:.1f}"},
        {
            "label": f"Net ({mev.profil_vade or profil_mevduat_etiket})",
            "value": f"%{mev.profil_vade_net:.1f}" if mev.profil_vade_net is not None else "—",
        },
        {
            "label": "Yerel reel",
            "value": f"{mev.profil_vade_reel:+.1f} pp" if mev.profil_vade_reel is not None else "—",
        },
        {
            "label": "EUR bazlı",
            "value": f"{mev.profil_vade_eur_tahmini:+.1f} pp" if mev.profil_vade_eur_tahmini is not None else "—",
        },
    ])
    if mev.ozet:
        st.caption(mev.ozet)
    if mev.veri_kaynagi:
        st.caption(f"Kaynak: {mev.veri_kaynagi}")
    if mev.getiri_notu:
        with st.expander("Getiri notu", expanded=False):
            st.warning(mev.getiri_notu)

    from rates_tr import _eur_bazli_tahmini
    df_m = pd.DataFrame([{
        "Vade / Tür": o.vade,
        "Brüt %": round(o.brut_yillik * 100, 2),
        "Net % (stopaj sonrası)": round(o.net_yillik * 100, 2),
        "Yerel reel (TL enfl.)": round(o.reel_yillik or 0, 2),
        "EUR bazlı tahmini": round(
            _eur_bazli_tahmini(o.net_yillik * 100, mev.enflasyon), 2
        ) if o.vade.startswith("TL") else None,
        "Profil vadeniz": "✓" if o.vade == (mev.profil_vade or profil_mevduat_etiket) else "",
        "Kaynak": o.kaynak,
    } for o in mev.oranlar])
    render_df_table(df_m)

    with st.expander("Mevduat vs hisse — kısa rehber", expanded=False):
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(
                "**Mevduat:** reel faiz pozitif · CDS düşük · rejim TL FIRSAT"
            )
        with col_b:
            st.markdown(
                "**Hisse:** reel mevduat negatif · risk-on + AL sinyali · uzun vade"
            )
    if mev.uyarilar:
        with st.expander(f"Uyarılar ({len(mev.uyarilar)})", expanded=False):
            st.warning("\n".join(mev.uyarilar))
    from vergi_notu import vergi_notu_caption, vergi_notu_markdown
    st.caption(vergi_notu_caption("mevduat"))
    with st.expander("Vergi notu", expanded=False):
        st.markdown(vergi_notu_markdown())

# ══════════════════════════════════════════════════════════════
elif sayfa == "TEFAS Fonları":
    @st.fragment(run_every=15)
    def _tefas_otoyenile():
        ob = st.session_state.get("app_onbellek")
        if ob is None or not tefas_yukleniyor(ob.tefas_ham):
            return
        from app_veri import tefas_ham_cek
        fresh = tefas_ham_cek(120, _tick)
        if not tefas_yukleniyor(fresh):
            ob.tefas_ham = fresh
            st.rerun()

    if _ob.tefas_ham is None or tefas_yukleniyor(_ob.tefas_ham):
        _ob = _sayfa_onbellegi_hazirla(_ob)
    _tefas_otoyenile()
    tefas_paneli(
        snap, profil, tahsis.rejim.rejim,
        mevduat_ozet=mevduat_ozet,
        ham_onbellek=_ob.tefas_ham,
    )

# ══════════════════════════════════════════════════════════════
elif sayfa == "Hisse & Endeks Taraması":
    render_page_header(
        "Hisse & ETF",
        "Endeks · hisse · ETF taraması",
    )
    from vergi_notu import vergi_notu_caption, vergi_notu_markdown
    st.caption(vergi_notu_caption("bist"))
    with st.expander("Vergi notu", expanded=False):
        st.caption(vergi_notu_caption("yabanci"))
        st.markdown(vergi_notu_markdown())
    if st.session_state.hisse_haber_tara:
        st.caption("Derin haber taraması açık.")

    @st.fragment(run_every=15)
    def _tarama_otoyenile():
        ob = st.session_state.get("app_onbellek")
        if ob is None or not tarama_yukleniyor(ob.tarama):
            return
        fresh = tarama_cek(
            canli_mod,
            tahsis.rejim.rejim,
            snap.veri_kaynak,
            _tick,
            haber_tara=st.session_state.hisse_haber_tara,
            **_tarama_param(profil),
        )
        if not tarama_yukleniyor(fresh):
            ob.tarama = fresh
            st.session_state.tarama_son = fresh
            st.rerun()

    tara_yenile = st.button("Taramayı yenile", key="hisse_tara_yenile", type="primary")

    # Her girişte soft-sync (başka bölümden dönüş + disk son kayıt)
    _ob = _sayfa_onbellegi_hazirla(_ob)
    tarama_ozet = _ob.tarama

    _tarama_otoyenile()

    tarama = tarama_ozet
    if tara_yenile:
        with st.status("Hisse taraması güncelleniyor (~1–2 dk)…", expanded=True) as durum:
            tarama = tarama_cek(
                canli_mod,
                tahsis.rejim.rejim,
                snap.veri_kaynak,
                _tick,
                haber_tara=st.session_state.hisse_haber_tara,
                zorla=True,
                **_tarama_param(profil),
            )
            st.session_state.tarama_son = tarama
            st.session_state.app_onbellek.tarama = tarama
            from disk_onbellek import disk_mtime as _dm
            from app_onbellek import _tarama_anahtar as _ta

            st.session_state.app_onbellek.tarama_disk_mtime = _dm(
                _ta(
                    canli_mod=canli_mod,
                    rejim=tahsis.rejim.rejim,
                    haber_tara=st.session_state.hisse_haber_tara,
                    profil_risk=profil.risk,
                    profil_vade=profil.vade,
                )
            )
            durum.update(label="Tarama tamamlandı", state="complete")
        _hisse_tarama_icerik(tarama, snap, tahsis, profil)
    else:
        _hisse_tarama_icerik(tarama, snap, tahsis, profil)
        if not tarama_yukleniyor(tarama):
            st.caption("Güncellemek için **Taramayı yenile** · veri kaynak etiketleri tabloda.")

# ══════════════════════════════════════════════════════════════
elif sayfa == "Backtest":
    if _ob.backtest is None:
        _ob = _sayfa_onbellegi_hazirla(_ob)
    render_page_header(
        "Backtest",
        "Dinamik rejim vs statik referans — kesin getiri iddiası değil",
    )

    _sig_rep = Path(__file__).resolve().parent / "signal_engine" / "reports" / "signal_backtest_report.json"
    if _sig_rep.exists():
        import json as _json
        with st.expander("Signal Engine v2 — 5Y walk-forward özeti", expanded=False):
            rep = _json.loads(_sig_rep.read_text(encoding="utf-8"))
            st.caption(
                f"Üretim: {rep.get('generated_at', '—')[:10]} · "
                f"config `{rep.get('config_hash', '—')}` · "
                f"lookahead OK: {rep.get('lookahead_ok')}"
            )
            st.markdown((rep.get("notes") or ""))
            sym_rows = rep.get("symbols") or []
            if sym_rows:
                render_df_table(pd.DataFrame([{
                    "Sembol": s.get("sembol"),
                    "Sinyal": s.get("signal_count"),
                    "1M %": s.get("avg_ret_1m"),
                    "3M %": s.get("avg_ret_3m"),
                    "Hit 1M": round(s["hit_rate_1m"] * 100, 1) if s.get("hit_rate_1m") is not None else None,
                    "B&H 1Y %": s.get("buy_hold_1y"),
                    "Sharpe": s.get("sharpe_signal"),
                } for s in sym_rows]))
            st.caption("Tam rapor: `signal_engine/reports/signal_backtest_report.md`")

    bt = _ob.backtest
    if bt:
        kars = backtest_karsilastirma_uret(
            bt, tahsis.rejim.rejim, bugun_agirliklar=tahsis.agirliklar, profil=profil
        )
        if kars:
            if kars.dinamik_dezavantaj:
                st.error(kars.uyari_mesaji)
            st.info(kars.ozet.replace("**", ""))

            met = kars.dinamik
            ref = kars.referans_statik
            karsi = kars.karsi_olgusal

            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric(
                    "Dinamik Sharpe",
                    f"{met.sharpe_yillik:.2f}" if met.sharpe_yillik is not None else "—",
                    f"getiri {met.toplam_getiri_pct:+.1f}%",
                )
            with c2:
                st.metric(
                    "Referans statik Sharpe",
                    f"{ref.sharpe_yillik:.2f}" if ref.sharpe_yillik is not None else "—",
                    f"getiri {ref.toplam_getiri_pct:+.1f}%",
                    delta_color="normal" if kars.en_iyi_strateji == "Referans statik" else "off",
                )
            with c3:
                if karsi:
                    st.metric(
                        "Bugünkü ağırlıklar (sabit)",
                        f"{karsi.sharpe_yillik:.2f}" if karsi.sharpe_yillik is not None else "—",
                        f"getiri {karsi.toplam_getiri_pct:+.1f}%",
                    )
                else:
                    st.metric("En iyi strateji", kars.en_iyi_strateji)

            cmp_rows = [
                {
                    "Metrik": "Sharpe",
                    "Dinamik": met.sharpe_yillik,
                    "Referans statik": ref.sharpe_yillik,
                    "Bugünkü sabit": karsi.sharpe_yillik if karsi else None,
                },
                {
                    "Metrik": "Getiri %",
                    "Dinamik": met.toplam_getiri_pct,
                    "Referans statik": ref.toplam_getiri_pct,
                    "Bugünkü sabit": karsi.toplam_getiri_pct if karsi else None,
                },
                {
                    "Metrik": "Max DD %",
                    "Dinamik": met.max_drawdown_pct,
                    "Referans statik": ref.max_drawdown_pct,
                    "Bugünkü sabit": karsi.max_drawdown_pct if karsi else None,
                },
            ]
            render_df_table(pd.DataFrame(cmp_rows))

            if kars.rejim_dagilimi:
                st.subheader("Rejim dağılımı")
                rej_df = pd.DataFrame([
                    {"Rejim": r.replace("_", " "), "Süre %": p}
                    for r, p in kars.rejim_dagilimi.items()
                ])
                plotly_vbar(rej_df["Rejim"].tolist(), rej_df["Süre %"].tolist(), title="Rejim dağılımı (%)")
                if kars.belirsiz_oran_pct >= 30:
                    st.warning(
                        f"BELIRSIZ oranı %{kars.belirsiz_oran_pct:.0f} — "
                        "dinamik katman ayırt edici değil."
                    )

            if met.model_drift:
                st.warning(met.drift_mesaji)

            for n in met.notlar + ref.notlar[:1]:
                st.caption(f"ℹ️ {n}")

        bt_df = pd.DataFrame([{
            "Ay": s.tarih, "Rejim": s.rejim_etiket, "EUR/TRY": s.eur_try,
            "CDS": s.cds, "Öncelik": s.oncelikli_varlik,
            "Altın %": round(s.agirliklar.get("gold", 0) * 100, 1),
            "TL %": round(s.agirliklar.get("tl_deposit", 0) * 100, 1),
            "BIST %": round(s.agirliklar.get("bist", 0) * 100, 1),
        } for s in bt])
        st.subheader("Aylık tahsis geçmişi")
        render_df_table(bt_df, max_height=400)
        plotly_area_line(bt_df, "Ay", ["Altın %", "TL %", "BIST %"], title="Aylık tahsis geçmişi", height=340)
    else:
        st.warning("Backtest verisi alınamadı.")
