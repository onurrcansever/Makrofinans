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
    st.header("Yatırımcı profiliniz")
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
    st.header("Ayarlar")
    sayfa = st.radio(
        "Bölüm",
        ["Portföy Tahsisi", "Varlıklarım", "AI Danışman", "TL Mevduat Faizleri", "TEFAS Fonları", "Hisse & Endeks Taraması", "Backtest"],
    )
    mod = st.radio("Veri modu", ["Canlı veri", "Demo (senaryo)"], index=0)
    st.session_state.hisse_haber_tara = st.checkbox(
        "Derin haber taraması (~1 dk ek süre)",
        value=st.session_state.get("hisse_haber_tara", False),
        help="Hisse/endeks taramasında Google News katmanı — açılış yüklemesine dahil edilir.",
    )

    if "kullanici_portfoy" not in st.session_state:
        st.session_state.kullanici_portfoy = varsayilan_portfoy()
    kp_sb = st.session_state.kullanici_portfoy
    mev_sb = kp_sb.mevcut_tl_mevduat()

    para_birimi = st.selectbox(
        "Portföy para birimi",
        ["EUR", "TL"],
        index=0 if kp_sb.para_birimi == "EUR" else 1,
    )
    toplam = st.number_input(
        f"Toplam portföy ({para_birimi})",
        value=float(kp_sb.toplam),
        step=1000.0 if para_birimi == "EUR" else 50000.0,
        min_value=0.0,
    )

    with st.expander("Mevcut pozisyonlarım", expanded=False):
        st.caption("Örn. tüm paranız Yapı Kredi 90 gün vadeli hesapta — birleşik öneri buna göre hesaplanır.")
        mevduat_var = st.checkbox(
            "TL vadeli mevduat",
            value=mev_sb is not None,
            key="kp_mevduat_var",
        )
        mev_bank = st.text_input("Banka", value=mev_sb.banka if mev_sb else "Yapı Kredi")
        mev_tutar = st.number_input(
            "Mevduat tutarı (TL)",
            value=float(mev_sb.tutar if mev_sb else (toplam if para_birimi == "TL" else 0)),
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
            "Brüt faiz (% yıllık)",
            value=float(mev_sb.brut_faiz if mev_sb else 42.0),
            min_value=0.0,
            max_value=100.0,
            step=0.5,
        )
        tefas_kod = st.text_input(
            "TEFAS fon kodu (isteğe bağlı)",
            value=next((p.fon_kodu for p in kp_sb.pozisyonlar if p.tur == "tefas"), ""),
            placeholder="YHS",
        ).strip().upper()
        tefas_tutar = st.number_input(
            "TEFAS tutarı (TL, isteğe bağlı)",
            value=float(next((p.tutar for p in kp_sb.pozisyonlar if p.tur == "tefas"), 0.0)),
            min_value=0.0,
            step=10000.0,
        )

    pozisyonlar: list = []
    if mevduat_var and mev_tutar > 0:
        pozisyonlar.append(
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
        pozisyonlar.append(
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
        pozisyonlar=pozisyonlar,
    )

    trans = st.number_input("Tranş sayısı", value=int(config.TRANS_SAYISI), min_value=1)
    bt_ay = st.slider("Backtest ay sayısı", 6, 18, 12)
    st.divider()
    st.subheader("CDS 5Y (otomatik)")
    from cds_bloomberg import bloomberg_terminal_erisimli

    if bloomberg_terminal_erisimli():
        st.caption("Bloomberg Terminal: **bağlı**")
    else:
        st.caption("Bloomberg Terminal: **yok** — Investing otomatik çekiliyor.")
    if st.button("CDS kaynaklarını yenile", use_container_width=True):
        cds_kaynak_ozet.clear()
        st.session_state["cds_son_kaynak"] = cds_kaynak_ozet(st.session_state.son_yenileme_sayaci)
        veri_onbellegi_temizle()
        onbellek_gecersiz_kil()
        st.rerun()
    st.divider()
    otoyenile = st.toggle("Otomatik yenileme", value=False)
    aralik_etiket = st.selectbox(
        "Yenileme aralığı",
        ["1 dakika", "3 dakika", "5 dakika", "10 dakika"],
        index=1,
    )
    aralik_dk = int(aralik_etiket.split()[0])
    yenile = st.button("Şimdi yenile", type="primary", use_container_width=True)

config.TOPLAM_EUR = toplam  # snap sonrası EUR'a çevrilir
config.TRANS_SAYISI = int(trans)
kullanici_portfoy = st.session_state.kullanici_portfoy
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
    veri_onbellegi_temizle,
)
from app_onbellek import onbellek_gecersiz_kil, onbellek_sayfa_hazirla, uygulama_onbellegi_al


def _tarama_param(profil: YatirimProfili) -> dict:
    return {
        "profil_risk": profil.risk,
        "profil_vade": profil.vade,
    }


def _hisse_tarama_icerik(tarama, snap, tahsis, *, guncelleniyor: bool = False) -> None:
    """Hisse & ETF tarama sayfası gövdesi — spinner yerine satır içi durum."""
    if tarama is None:
        st.info("Tarama henüz yüklenmedi — birkaç saniye içinde liste görünecek.")
        return
    if guncelleniyor:
        st.caption("🔄 Tarama arka planda güncelleniyor — liste bir önceki sonucu gösteriyor.")

    if getattr(tarama, "profil_ozet", ""):
        st.info(f"**Yatırımcı profili:** {tarama.profil_ozet}")
    for n in (getattr(tarama, "profil_notlari", None) or [])[:4]:
        st.caption(f"📋 {n}")

    st.info(
        f"**Makro rejim (profilden bağımsız):** {tahsis.rejim.etiket} — reel faiz, CDS, VIX ile belirlenir. "
        f"Hisse filtreleri profilinize göre ayrıca uygulanır."
    )
    if profil.risk == "yuksek" and profil.vade == "uzun":
        st.caption(
            "Uzun vade + yüksek risk: trend filtresi gevşetildi; BEKLE artık ALMA değil — "
            "net sinyal yoksa BEKLE (izle) gösterilir."
        )
    if tarama.tarama_ozet:
        st.caption(tarama.tarama_ozet)

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
    st.caption(
        "UCITS ETF'ler Revolut Invest'te ISIN veya ticker ile aranır (VWCE, CSPX, IWDA vb.). "
        "Liste EEA platformu odaklıdır; ülkenize göre değişebilir."
    )
    etf_firsat = getattr(tarama, "etf_firsatlari", None) or []
    if etf_firsat:
        for h in etf_firsat:
            badge = getattr(h, "alim_uygun_etiket", "⚪ İzle / bekle")
            emoji = _karar_emoji(h)
            rt = h.revolut_ticker or h.sembol.split(".")[0]
            st.markdown(
                f"**{badge}** · {emoji} **{rt}** — {h.ad} · "
                f"Fiyat: {h.fiyat:,.2f} · RSI: {h.rsi:.0f} · Skor: {h.skor:.0f} · "
                f"**{_teknik_sinyal_etiket(h)}**"
            )
            if getattr(h, "alim_uygun_not", ""):
                st.caption(f"↳ {h.alim_uygun_not}")
            st.caption(h.hikaye or h.gerekce)
            if h.isin:
                st.caption(f"📋 ISIN: `{h.isin}` · Yahoo: `{h.sembol}`")
    else:
        st.info("ETF'lerde güçlü alım sinyali yok — VWCE/CSPX gibi çekirdek fonları izleme modunda tutun.")

    st.subheader("Alım fırsatları — öne çıkan hisseler")
    hisse_firsat = [h for h in (tarama.alim_firsatlari or []) if h.piyasa != "ETF"]
    if hisse_firsat:
        for h in hisse_firsat:
            badge = getattr(h, "alim_uygun_etiket", "⚪ İzle / bekle")
            emoji = _karar_emoji(h)
            st.markdown(
                f"**{badge}** · {emoji} **{h.ad}** (`{h.sembol}`) · {h.piyasa} · "
                f"Fiyat: {h.fiyat:,.2f} · RSI: {h.rsi:.0f} · Skor: {h.skor:.0f} · "
                f"**{_teknik_sinyal_etiket(h)}**"
            )
            if getattr(h, "alim_uygun_not", ""):
                st.caption(f"↳ {h.alim_uygun_not}")
            st.caption(h.hikaye or h.gerekce)
            if h.rejim_notu and h.rejim_notu != "Rejim uyumlu":
                st.caption(f"📊 Rejim: {h.rejim_notu}")
            if h.haber_notu:
                st.caption(f"📰 Haber: {h.haber_notu}")
            if h.profil_notu and h.profil_notu != "Profil uyumlu":
                st.caption(f"👤 Profil: {h.profil_notu}")
            if getattr(h, "faktor_notu", "") and h.faktor_notu not in ("", "Faktör nötr"):
                st.caption(f"📈 Faktör: {h.faktor_notu}")
    else:
        st.info("Şu an güçlü alım sinyali yok — BEKLE veya mevduat/altın ağırlıklı makro tahsise bakın.")

    st.subheader("Tüm varlıklar (hisse + ETF)")
    st.caption(
        "**Karar kodları:** AL = aday · DİKKAT = uyarılı aday · BEKLE = izle · ALMA = elendi. "
        "**Teknik sinyal** yalnızca RSI/trend katmanıdır; **Alım uygunluğu** profil, aday listesi, "
        "haber ve makro filtrelerinden sonra nihai karardır. İkisi çelişirse alım uygunluğuna güvenin."
    )
    piyasa_filtre = st.multiselect(
        "Piyasa filtresi",
        ["BIST", "SP500", "NASDAQ", "ETF"],
        default=["BIST", "SP500", "NASDAQ", "ETF"],
        key="hisse_piyasa_filtre",
    )
    sinyal_filtre = st.multiselect(
        "Sinyal filtresi",
        list(SINYAL_ETIKET.keys()),
        default=["ALIM_FIRSATI", "TREND_ALIM", "BEKLE"],
        format_func=lambda x: SINYAL_ETIKET.get(x, x),
        key="hisse_sinyal_filtre",
    )

    filtrelenmis = [
        h for h in tarama.hisseler
        if h.piyasa in piyasa_filtre and h.sinyal in sinyal_filtre
    ]
    filtrelenmis.sort(key=lambda h: (_UYGUN_SIRA.get(getattr(h, "alim_uygun", "IZLE"), 9), -h.skor))

    hisse_df = pd.DataFrame([{
        "Karar": alim_aksiyon_kisa(getattr(h, "alim_uygun", "IZLE")),
        "Alım uygunluğu": getattr(h, "alim_uygun_etiket", "⚪ İzle / bekle"),
        "Uygunluk notu": (getattr(h, "alim_uygun_not", "") or "")[:55],
        "Sembol": h.sembol,
        "Hisse/ETF": h.ad,
        "Revolut": h.revolut_ticker if h.revolut_ticker else "",
        "Piyasa": h.piyasa,
        "Sektör": SEKTOR_ETIKET.get(h.sektor, h.sektor),
        "Fiyat": h.fiyat,
        "1 Gün %": round(h.degisim_1g, 2) if h.degisim_1g is not None else None,
        "1 Ay %": round(h.degisim_1ay, 2) if h.degisim_1ay is not None else None,
        "3 Ay %": round(h.degisim_3ay, 2) if getattr(h, "degisim_3ay", None) is not None else None,
        "SMA200": round(h.sma200, 2) if getattr(h, "sma200", None) else None,
        "52H": format_52h_metin(h),
        "Peer %": round(h.peer_yuzdelik, 0) if getattr(h, "peer_yuzdelik", None) is not None else None,
        "Endeks farkı": round(h.endeks_gore, 1) if getattr(h, "endeks_gore", None) is not None else None,
        "RSI": round(h.rsi, 1) if h.rsi else None,
        "Teknik skor": round(h.teknik_skor, 0) if h.teknik_skor else round(h.skor, 0),
        "Nihai skor": round(h.skor, 0),
        "Teknik sinyal": _teknik_sinyal_etiket(h),
        "ISIN": h.isin if h.isin else "",
        "Rejim etkisi": h.rejim_notu[:60] if h.rejim_notu else "",
        "Profil etkisi": h.profil_notu[:60] if getattr(h, "profil_notu", "") else "",
        "Faktör": (h.faktor_notu or "")[:60] if getattr(h, "faktor_notu", "") else "",
        "Trend filtresi": (h.trend_notu or "")[:60] if getattr(h, "trend_notu", "") else "",
        "Haber": h.haber_notu[:50] if h.haber_notu else "",
        "Hikaye": (h.hikaye or "")[:70],
        "Gerekçe": h.gerekce,
    } for h in filtrelenmis])

    render_df_table(hisse_df, max_height=560)

    st.caption(
        "Evren: BIST/SP500/NASDAQ blue-chip + Revolut UCITS ETF (~23 fon). "
        "Alım fırsatı: RSI 28–45 dipten dönüş veya SMA50 üstü trend (skor ≥55). "
        "Faktör: sektör içi momentum + endeks karşılaştırması (3 ay). "
        "ETF: VWCE (küresel), CSPX/VUAA (S&P500), SGLD (altın), VAGP (tahvil). "
        "Rejim: TL fırsat→küresel ETF + · ENFLASYON→altın/tahvil ETF +."
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

st.title("Makro Portföy Asistanı")
st.caption("Karar-destek aracı — otomatik işlem yapmaz, finansal tavsiye değildir.")

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

hdr_sol, hdr_sag = st.columns([3, 1])
with hdr_sag:
    if st.button("📄 Yatırım raporu oluştur", type="primary", use_container_width=True, key="rapor_main"):
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
            st.toast("PDF rapor hazır", icon="✅")
        except Exception as exc:
            st.session_state.son_rapor = None
            st.session_state.rapor_hata = str(exc)
    if st.session_state.rapor_hata:
        st.error(f"Rapor oluşturulamadı: {st.session_state.rapor_hata}")
    if st.session_state.son_rapor:
        rp = st.session_state.son_rapor
        st.download_button(
            "⬇ PDF indir",
            data=rp["pdf"],
            file_name=rp["pdf_dosya"],
            mime="application/pdf",
            use_container_width=True,
            key="dl_rapor_hdr",
        )

if st.session_state.son_rapor:
    with st.expander("Son yatırım raporu — önizleme", expanded=False):
        rp = st.session_state.son_rapor
        st.download_button(
            "PDF raporu indir",
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
    from cds_sync import cds_guncelleme_calistir

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
    st.caption(
        "CDS manuel girilmez. **Investing.com** her yenilemede otomatik çekilir. "
        "**Bloomberg** için Terminal açık olmalı ve `pip install blpapi` kurulu olmalı "
        "(BLOOMBERG_CDS_TICKER .env). Terminal yoksa yalnızca Investing kullanılır."
    )

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
    if not _ob.birlesik_tam:
        with st.spinner("TEFAS fonları ve BIST önerileri yükleniyor (~30–90 sn)…"):
            _ob = _sayfa_onbellegi_hazirla(_ob)
            birlesik = _ob.birlesik
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

# ══════════════════════════════════════════════════════════════
elif sayfa == "Varlıklarım":
    aktif_vp = _ob.varlik_store.aktif()
    if aktif_vp and aktif_vp.pozisyonlar and _ob.varlik_deger is None:
        with st.spinner("Portföy fiyatları yükleniyor…"):
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
        with st.spinner("Hisse taraması ve danışman analizi yükleniyor…"):
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
        "(100.000 TL referans, vadeye göre stopaj). EUR/USD için piyasa ortalaması kullanılır."
    )

# ══════════════════════════════════════════════════════════════
elif sayfa == "TEFAS Fonları":
    if _ob.tefas_ham is None or getattr(_ob.tefas_ham, "hata", ""):
        with st.spinner("TEFAS verisi yükleniyor (~1–2 dk)…"):
            _ob = _sayfa_onbellegi_hazirla(_ob)
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

    tara_yenile = st.button("Taramayı yenile", key="hisse_tara_yenile")

    if _ob.tarama is None and not tara_yenile:
        with st.spinner("Hisse ve endeks taraması yükleniyor (~1–2 dk)…"):
            _ob = _sayfa_onbellegi_hazirla(_ob)
            tarama_ozet = _ob.tarama

    tarama = tarama_ozet
    if tara_yenile:
        with st.status("Hisse taraması güncelleniyor…", expanded=True) as durum:
            tarama = tarama_cek(
                canli_mod,
                tahsis.rejim.rejim,
                snap.veri_kaynak,
                _tick,
                haber_tara=st.session_state.hisse_haber_tara,
                **_tarama_param(profil),
            )
            st.session_state.tarama_son = tarama
            st.session_state.app_onbellek.tarama = tarama
            durum.update(label="Tarama tamamlandı", state="complete")
        _hisse_tarama_icerik(tarama, snap, tahsis)
    else:
        _hisse_tarama_icerik(tarama, snap, tahsis)
        st.caption("Güncellemek için **Taramayı yenile** · veri kaynak etiketleri tabloda.")

# ══════════════════════════════════════════════════════════════
elif sayfa == "Backtest":
    if _ob.backtest is None:
        with st.spinner("Backtest geçmiş verisi yükleniyor…"):
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
