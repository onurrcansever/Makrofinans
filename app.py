# -*- coding: utf-8 -*-
"""
Makro Portföy Dashboard — portföy, mevduat, hisse taraması
Otomatik yenileme: sidebar'dan açılır (varsayılan 3 dk).
"""
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from typing import Optional

import config
from investor_profile import RISK_SECENEKLERI, VADE_SECENEKLERI, YatirimProfili, profil_mevduat_vadesi, vade_kisa_mi
from allocation_engine import VARLIKLAR
from backtest import backtest_karsilastirma_uret
from veri_kalitesi import veri_kalite_olustur
from macro_data import cache_gecmisi
from notifier import portfoy_raporu_olustur
from stock_scanner import SINYAL_ETIKET
from stock_universe import SEKTOR_ETIKET
from alim_uygunluk import alim_aksiyon_kisa
from bist_52h_eur import format_52h_metin
from advisor_ui import danisman_paneli
from tefas_ui import tefas_paneli
from kullanici_portfoy import KullaniciPortfoy, MevcutPozisyon, varsayilan_portfoy
from birlesik_oneri_ui import birlesik_oneri_paneli
from varliklarim_ui import varliklarim_paneli, oneri_aktar_butonu
from regime_uyum import rejim_gosterim_metni
from investment_report import rapor_paketi_olustur
from ui_theme import (
    inject_tradingview_theme,
    plotly_area_line,
    plotly_hbar,
    plotly_vbar,
    render_df_table,
    render_live_banner,
    render_metric_strip,
)

_UYGUN_SIRA = {"UYGUN": 0, "SINIRLI": 1, "IZLE": 2, "UYGUN_DEGIL": 3}


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

with st.sidebar:
    st.markdown("## 📊 Makrofinans")
    st.caption("Profesyonel portföy karar destek sistemi")
    st.divider()
    st.subheader("Yatırımcı Profili")
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
    profil = YatirimProfili(risk=risk_etiket, vade=vade_etiket)
    st.caption(profil.ozet())
    st.divider()
    st.subheader("Bölüm Seçimi")
    sayfa = st.radio(
        "Bölüm",
        ["Portföy Tahsisi", "Karar Asistanı", "Varlıklarım", "AI Danışman", "TL Mevduat Faizleri", "TEFAS Fonları", "Hisse & Endeks Taraması", "Backtest"],
        format_func=lambda s: {
            "Portföy Tahsisi": "📊 Portföy Tahsisi",
            "Karar Asistanı": "💡 Karar Asistanı",
            "Varlıklarım": "💼 Varlıklarım",
            "AI Danışman": "🤖 AI Danışman",
            "TL Mevduat Faizleri": "🏦 TL Mevduat",
            "TEFAS Fonları": "📈 TEFAS Fonları",
            "Hisse & Endeks Taraması": "📉 Hisse & ETF",
            "Backtest": "⏱ Backtest",
        }.get(s, s),
    )
    mod = st.radio("Veri modu", ["Canlı veri", "Demo (senaryo)"], index=0)
    st.session_state.hisse_haber_tara = st.checkbox(
        "Derin haber taraması (~1 dk ek süre)",
        value=st.session_state.get("hisse_haber_tara", False),
        help="Hisse/endeks taramasında Google News katmanı — açılış yüklemesine dahil edilir.",
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
    st.caption(
        "Veriler otomatik tazelenir: fiyatlar 15 dk · tarama 30 dk · "
        "TEFAS/faiz 6 sa. Bölüm geçişleri önbellekten anında açılır; "
        "anlık taze veri için **Şimdi yenile**."
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
    }


def _hisse_tarama_icerik(tarama, snap, tahsis, profil=None, *, guncelleniyor: bool = False) -> None:
    """Hisse & ETF tarama sayfası gövdesi."""
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

    profil_ozet = getattr(tarama, "profil_ozet", "")
    st.info(
        f"**Profil:** {profil_ozet or '—'} · **Makro rejim:** {tahsis.rejim.etiket}"
    )
    with st.expander("Profil notları ve tarama detayı", expanded=False):
        for n in (getattr(tarama, "profil_notlari", None) or [])[:4]:
            st.caption(f"📋 {n}")
        if profil and profil.risk == "yuksek" and profil.vade == "uzun":
            st.caption(
                "Uzun vade + yüksek risk: trend filtresi gevşetildi; net sinyal yoksa BEKLE (izle) gösterilir."
            )
        if tarama.tarama_ozet:
            st.caption(tarama.tarama_ozet)
        st.caption(
            "Makro rejim reel faiz, CDS ve VIX ile belirlenir — profilden bağımsızdır. "
            "Hisse filtreleri profilinize göre ayrıca uygulanır."
        )

    if tarama.uyarilar:
        st.warning("\n".join(tarama.uyarilar))

    st.subheader("Endeksler — NASDAQ · S&P 500 · BIST 100")
    endeks_df = pd.DataFrame([{
        "Endeks": e.ad,
        "Fiyat": e.fiyat,
        "1 Gün %": round(e.degisim_1g, 2) if e.degisim_1g is not None else None,
        "1 Ay %": round(e.degisim_1ay, 2) if e.degisim_1ay is not None else None,
        "3 Ay %": round(e.degisim_3ay, 2) if e.degisim_3ay is not None else None,
        "RSI": round(e.rsi, 1) if e.rsi else None,
        "Sinyal": SINYAL_ETIKET.get(e.sinyal, e.sinyal),
        "Skor": round(e.skor, 0),
    } for e in tarama.endeksler])
    render_df_table(endeks_df)

    st.subheader("Revolut ETF — alım adayları")
    etf_firsat = getattr(tarama, "etf_firsatlari", None) or []
    if etf_firsat:
        etf_df = pd.DataFrame([{
            "Karar": f"{_karar_emoji(h)} {alim_aksiyon_kisa(getattr(h, 'alim_uygun', 'IZLE'))}",
            "Ticker": h.revolut_ticker or h.sembol.split(".")[0],
            "ETF": h.ad,
            "Fiyat": round(h.fiyat, 2) if h.fiyat else None,
            "RSI": round(h.rsi, 0) if h.rsi else None,
            "Skor": round(h.skor, 0),
            "Teknik sinyal": _teknik_sinyal_etiket(h),
            "Not": (getattr(h, "alim_uygun_not", "") or h.hikaye or h.gerekce or "")[:70],
            "ISIN": h.isin or "",
        } for h in etf_firsat])
        render_df_table(etf_df)
        st.caption("Revolut Invest'te ISIN veya ticker ile aranır · EEA odaklı liste, ülkeye göre değişebilir.")
    else:
        st.info("ETF'lerde güçlü alım sinyali yok — VWCE/CSPX gibi çekirdek fonları izleme modunda tutun.")

    st.subheader("Alım fırsatları — öne çıkan hisseler")
    st.caption(
        "**Karar = AL** → profil + makro + teknik uyumlu adaylar; aynı gün Portföy Tahsisi'ne girer. "
        "**DİKKAT** → fırsat var ama uyarı (ör. 52H zirveye yakın)."
    )
    hisse_firsat = [h for h in (tarama.alim_firsatlari or []) if h.piyasa != "ETF"]
    if hisse_firsat:
        firsat_df = pd.DataFrame([{
            "Karar": f"{_karar_emoji(h)} {alim_aksiyon_kisa(getattr(h, 'alim_uygun', 'IZLE'))}",
            "Sembol": h.sembol,
            "Hisse": h.ad,
            "Piyasa": h.piyasa,
            "Fiyat": round(h.fiyat, 2) if h.fiyat else None,
            "RSI": round(h.rsi, 0) if h.rsi else None,
            "Skor": round(h.skor, 0),
            "Teknik sinyal": _teknik_sinyal_etiket(h),
            "Not": (getattr(h, "alim_uygun_not", "") or h.hikaye or h.gerekce or "")[:70],
            "Haber": (h.haber_notu or "")[:50],
        } for h in hisse_firsat])
        render_df_table(firsat_df)
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
        st.info("Şu an güçlü alım sinyali yok — BEKLE veya mevduat/altın ağırlıklı makro tahsise bakın.")

    st.subheader("Tüm varlıklar (hisse + ETF)")
    f1, f2, f3 = st.columns([2, 2, 1])
    piyasa_filtre = f1.multiselect(
        "Piyasa",
        ["BIST", "SP500", "NASDAQ", "ETF"],
        default=["BIST", "SP500", "NASDAQ", "ETF"],
        key="hisse_piyasa_filtre",
    )
    sinyal_filtre = f2.multiselect(
        "Sinyal",
        list(SINYAL_ETIKET.keys()),
        default=["ALIM_FIRSATI", "TREND_ALIM", "BEKLE"],
        format_func=lambda x: SINYAL_ETIKET.get(x, x),
        key="hisse_sinyal_filtre",
    )
    detay_sutun = f3.toggle("Detay sütunları", value=False, key="hisse_detay_sutun")

    filtrelenmis = [
        h for h in tarama.hisseler
        if h.piyasa in piyasa_filtre and h.sinyal in sinyal_filtre
    ]
    filtrelenmis.sort(key=lambda h: (_UYGUN_SIRA.get(getattr(h, "alim_uygun", "IZLE"), 9), -h.skor))

    def _satir(h, detay: bool) -> dict:
        temel = {
            "Karar": alim_aksiyon_kisa(getattr(h, "alim_uygun", "IZLE")),
            "Sembol": h.sembol,
            "Hisse/ETF": h.ad,
            "Piyasa": h.piyasa,
            "Fiyat": h.fiyat,
            "1G %": round(h.degisim_1g, 2) if h.degisim_1g is not None else None,
            "1A %": round(h.degisim_1ay, 2) if h.degisim_1ay is not None else None,
            "3A %": round(h.degisim_3ay, 2) if getattr(h, "degisim_3ay", None) is not None else None,
            "1Y %": round(h.degisim_1y, 2) if getattr(h, "degisim_1y", None) is not None else None,
            "RSI": round(h.rsi, 1) if h.rsi else None,
            "Skor": round(h.skor, 0),
            "Teknik sinyal": _teknik_sinyal_etiket(h),
            "Not": (getattr(h, "alim_uygun_not", "") or "")[:55],
        }
        if not detay:
            return temel
        temel.update({
            "Sektör": SEKTOR_ETIKET.get(h.sektor, h.sektor),
            "Revolut": h.revolut_ticker or "",
            "SMA200": round(h.sma200, 2) if getattr(h, "sma200", None) else None,
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
    render_df_table(hisse_df, max_height=560)

    with st.expander("Karar kodları ve metodoloji", expanded=False):
        st.markdown(
            "- **AL** = aday · **DİKKAT** = uyarılı aday · **BEKLE** = izle · **ALMA** = elendi\n"
            "- **Teknik sinyal** yalnızca RSI/trend katmanıdır; **Karar** profil, haber ve makro "
            "filtrelerinden sonra nihai sonuçtur — çelişirse Karar'a güvenin.\n"
            "- **Karar = AL** (tek hisse): bileşik skor + **teknik teyit** (AL/TREND sinyali), "
            "SMA200 üstü, 52H zirveye yakın değil, 1–3 ay momentum uygun.\n"
            "- **Portföy Tahsisi** BIST: yalnızca **AL** adaylarından skor sırası "
            "(kısa vadede en fazla 1 hisse). Varlıklarım'dan bağımsızdır.\n"
            "- Evren: BIST/SP500/NASDAQ blue-chip + Revolut UCITS ETF (~23 fon)\n"
            "- Alım fırsatı: RSI 28–45 dipten dönüş veya SMA50 üstü trend (skor ≥55)\n"
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
    _onbellek_temizle()
    st.session_state["_son_yenileme_toast"] = True


_tick = st.session_state.son_yenileme_sayaci
_profil_anahtar = f"{profil.risk}_{profil.vade}"
if st.session_state.get("tarama_profil_key") != _profil_anahtar:
    st.session_state.tarama_profil_key = _profil_anahtar
    onbellek_gecersiz_kil()

_baslik_sol, _baslik_sag = st.columns([4, 1])
with _baslik_sol:
    st.title("📊 Makrofinans")
    st.caption("Karar-destek sistemi — otomatik işlem yapmaz, yatırım tavsiyesi değildir.")
with _baslik_sag:
    st.caption(f"**Mod:** {'🟢 Canlı' if canli_mod else '🟡 Demo'}")
    st.caption(f"**Profil:** {profil.ozet()}")

_ob = uygulama_onbellegi_al(
    canli_mod=canli_mod,
    tick=_tick,
    profil=profil,
    profil_anahtar=_profil_anahtar,
    kp=kullanici_portfoy,
    haber_tara=st.session_state.hisse_haber_tara,
    bt_ay=bt_ay,
)
if st.session_state.get("app_onbellek_key"):
    _durum = "temel veriler hazır"
    if _ob.birlesik_tam:
        _durum = "tüm bölümler hazır"
    st.caption(
        f"✓ {_durum.capitalize()} ({_ob.yukleme_zamani}) — "
        "makro/TL kararı anında · TEFAS/BIST detayı aşağıda yüklenir"
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
    mod_etiket = "CANLI" if canli_mod else "DEMO"
    st.caption(
        f"Gösterge modu: {mod_etiket} · Profil: **{VADE_SECENEKLERI.get(profil.vade, profil.vade)}**"
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
            "value": f"{snap.vix:.1f}" if snap.vix else "—",
            "delta": snap.vix_1g_degisim,
            "delta_inverse": True,
        },
        {
            "label": "Altın",
            "value": f"${snap.altin_usd_oz:,.0f}" if snap.altin_usd_oz else "—",
            "delta": snap.altin_1g_degisim,
        },
        {
            "label": "BIST",
            "value": f"{snap.bist100:,.0f}" if snap.bist100 else "—",
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
        btc_line = f"BTC: ${snap.btc_usd:,.0f}" if snap.btc_usd else "BTC: —"
        if btc_delta:
            btc_line += f" ({btc_delta} 1G)"
        st.caption(btc_line)

    st.info(rejim_gosterim_metni(tahsis.rejim, tahsis.tl_tavan_oran))
    if (
        tahsis.rejim.rejim == "TL_FIRSAT"
        and tahsis.tl_tavan_oran >= 0.05
        and "askıda" not in tahsis.rejim.etiket
    ):
        tl_p = tahsis.agirliklar.get("tl_deposit", 0) * 100
        bist_p = tahsis.agirliklar.get("bist", 0) * 100
        kripto_p = tahsis.agirliklar.get("crypto", 0) * 100
        if profil.risk == "yuksek" and profil.vade == "uzun":
            st.success(
                f"**Profilinizle birlikte okuyun:** Makro tablo TL mevduatı cazip gösteriyor (reel faiz pozitif) — "
                f"rejim adı bunu yansıtır. Uzun vade + yüksek risk profilinize göre portföy yine "
                f"**BIST %{bist_p:.0f}** ve **kripto %{kripto_p:.0f}** içeriyor; TL payı **%{tl_p:.0f}**. "
                f"Çelişki değil: makro taban + büyüme payı."
            )
        elif vade_kisa_mi(profil.vade):
            st.caption(
                "Kısa vade profilde TL/EUR öncelikli; hisse taraması bilgi amaçlı ve sıkı filtrelenir."
            )

    _tl_renk = {
        "GUCLU": "success",
        "CAZIP": "success",
        "SINIRLI": "warning",
        "ONERILMIYOR": "error",
    }
    _tl_kutu = getattr(st, _tl_renk.get(tl_durum.durum, "info"))
    with _tl_kutu(
        f"**TL kararı (canlı):** {tl_durum.baslik} · "
        f"Portföy payı **%{tl_durum.agirlik_pct:.1f}** · "
        f"4 kapı tavanı **%{tl_durum.tavan_pct:.0f}**"
    ):
        if tl_durum.baglayici_etiket:
            st.markdown(
                f"**Bağlayıcı kısıt:** {tl_durum.baglayici_etiket} "
                f"({tl_durum.baglayici_kisit})"
            )
        for n in tl_durum.nedenler:
            st.markdown(f"- {n}")
        st.caption(f"Alternatif: {tl_durum.alternatif}")
        if tl_durum.explain:
            with st.expander("TL kararı nasıl oluştu?", expanded=False):
                import pandas as pd
                df = pd.DataFrame(tl_durum.explain)
                st.dataframe(df, use_container_width=True, hide_index=True)
        if tahsis.tl_ppk_notu:
            st.info(tahsis.tl_ppk_notu)
        st.caption(
            "Veriler her yenilemede güncellenir — rejim, CDS, reel faiz veya siyasi risk "
            "değişince TL önerisi otomatik artar veya sıfırlanır."
        )

    if tahsis.profil_notlari:
        with st.expander("Profilinize göre değerlendirme", expanded=False):
            for n in tahsis.profil_notlari:
                st.write(f"• {n}")

    with st.expander("Hızlı danışman özeti — tıklayın", expanded=True):
        st.markdown(danisman.genel_ozet)
        o1, o2, o3 = st.columns(3)
        for col, v in zip([o1, o2, o3], danisman.varliklar[:3]):
            with col:
                st.metric(f"{v.ok} {v.ad.split()[0]}", f"%{v.agirlik_pct:.0f}", v.sinyal_etiket)
        st.caption("Detaylı gerekçeler için sol menüden **AI Danışman** bölümüne gidin.")

    st.divider()
    _ob = _sayfa_onbellegi_hazirla(_ob)
    birlesik = _ob.birlesik

    @st.fragment(run_every=15)
    def _portfoy_bist_otoyenile():
        ob = st.session_state.get("app_onbellek")
        if ob is None:
            return
        tarama_hazir = ob.tarama is not None and not tarama_yukleniyor(ob.tarama)
        if not tarama_hazir or ob.birlesik_tarama_hazir:
            return
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
    )
    oneri_aktar_butonu(
        _ob.varlik_store,
        birlesik,
        kullanici_portfoy.para_birimi,
        mevcut_mevduat=kullanici_portfoy.mevcut_tl_mevduat(),
    )

    st.subheader("Makro göstergeler")
    g1, g2, g3, g4, g5, g6 = st.columns(6)
    g1.metric("USD/TRY", f"{snap.veri.usd_try:.2f}" if snap.veri.usd_try else "—")
    g2.metric("Fed faizi", f"{snap.veri.fed_faizi:.2f}%" if snap.veri.fed_faizi is not None else "—")
    g3.metric("Enflasyon TR", f"{snap.enflasyon_tr_yillik:.2f}%" if snap.enflasyon_tr_yillik is not None else "—")
    g4.metric("TL tavan", f"%{tahsis.tl_tavan_oran*100:.1f}")
    g5.metric("Siyasi risk", snap.veri.siyasi_risk_makale_sayisi or "—")
    g6.metric(
        "TCMB rezerv",
        "↑" if snap.veri.rezerv_artiyor else "↓" if snap.veri.rezerv_artiyor is False else "?",
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

    st.header("💡 Karar Asistanı")
    st.caption(
        "Elinize geçen yeni parayı veya vadesi dolan mevduatı, güncel rejim ve "
        "portföyünüzdeki açıklara göre **rakamsal plana** çevirir. Yatırım tavsiyesi değildir."
    )

    def _plan_goster(plan) -> None:
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
            st.caption(f"ℹ️ {n}")

    tab_yeni, tab_vade = st.tabs(["💰 Yeni param var", "⏳ Vadesi yaklaşanlar"])

    with tab_yeni:
        st.markdown("**Elinize yeni para geçti — neye ne kadar ekleyeceğinizi hesaplayın.**")
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
        if st.session_state.get("ka_son_plan"):
            _plan_goster(st.session_state.ka_son_plan)
            if _ob.tarama is None:
                st.caption(
                    "💬 Somut hisse/ETF isimleri için önce **Hisse & ETF** sayfasını bir kez açın — "
                    "AL sinyalleri plana otomatik eklenir."
                )

    with tab_vade:
        st.markdown("**Vadeli mevduatlarınız ve vade sonu yönlendirme planı.**")
        vadeliler = vadeli_mevduatlar(_ob.varlik_store)
        if not vadeliler:
            st.info(
                "Vade takibi için **Varlıklarım** bölümünde TL mevduat pozisyonuna "
                "**vade (gün)** bilgisi girin — örn. 3 Temmuz'da yatırılan 94 gün vadeli "
                "mevduat 5 Ekim'de izlenir, WhatsApp uyarısı da otomatik devreye girer."
            )
        for vb in vadeliler:
            banka = vb.pozisyon.banka.strip() or "Banka"
            kalan_metin = (
                f"⚠️ **vade doldu** ({vb.vade_tarihi.strftime('%d.%m.%Y')})"
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
                    _plan_goster(vplan)
                else:
                    st.warning("Plan oluşturulamadı.")
            st.divider()

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
    )

# ══════════════════════════════════════════════════════════════
elif sayfa == "AI Danışman":
    if not _ob.danisman_tam:
        _ob = _sayfa_onbellegi_hazirla(_ob)
        danisman = _ob.danisman
    danisman_paneli(danisman)

# ══════════════════════════════════════════════════════════════
elif sayfa == "TL Mevduat Faizleri":
    st.header("Türkiye Mevduat Faiz Karşılaştırması")
    st.caption(f"Profil vadeniz: **{VADE_SECENEKLERI.get(profil.vade, profil.vade)}** → **{profil_mevduat_etiket}** öne çıkarıldı")
    enf = snap.enflasyon_tr_yillik or 35.0
    mev = mevduat_ozet

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Enflasyon (TR)", f"%{mev.enflasyon:.1f}")
    m2.metric(
        f"Profil vadeniz ({mev.profil_vade or profil_mevduat_etiket}) net",
        f"%{mev.profil_vade_net:.1f}",
    )
    m3.metric("Yerel reel (TL enfl.)", f"{mev.profil_vade_reel:+.1f} pp")
    m4.metric("EUR bazlı tahmini", f"{mev.profil_vade_eur_tahmini:+.1f} pp")

    st.info(mev.ozet)

    if mev.veri_kaynagi:
        st.success(f"Veri kaynağı: **{mev.veri_kaynagi}** — otomatik güncellenir, key gerekmez.")

    if mev.getiri_notu:
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

    st.subheader("Mevduat vs Hisse — ne zaman hangisi?")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("""
        **TL mevduat tercih edilir:**
        - Reel faiz pozitif (net > enflasyon)
        - CDS düşük, siyasi risk sakin
        - Makro rejim: TL FIRSAT
        """)
    with col_b:
        st.markdown("""
        **Hisse (BIST/NASDAQ) tercih edilir:**
        - Reel mevduat getirisi negatif
        - Risk-on rejimi + teknik alım sinyali
        - Uzun vade büyüme beklentisi
        """)
    if mev.uyarilar:
        st.warning("\n".join(mev.uyarilar))
    st.caption(
        "TL faizleri **Yapı Kredi** resmi hesaplama aracından otomatik çekilir "
        "(100.000 TL referans, vadeye göre stopaj). **EUR/USD** oranları da aynı "
        "Yapı Kredi hesaplama aracından canlı çekilir."
    )

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
    st.header("Canlı Hisse & Endeks Analizi")
    st.caption(
        "Genişletilmiş evren · Hisse + Revolut UCITS ETF · RSI+SMA · Makro rejim + haber filtresi"
    )
    if st.session_state.hisse_haber_tara:
        st.caption("Derin haber taraması **açık** (sidebar).")

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

    if _ob.tarama is None or tarama_yukleniyor(_ob.tarama):
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
    st.header("Backtest — Dinamik vs Statik")
    st.caption(
        "CDS/enflasyon yaklaşık tablodan — kesin getiri iddiası değil. "
        "Dinamik rejim katmanının statik referansa karşı performansını test eder."
    )
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
