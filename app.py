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
from allocation_engine import tahsis_hesapla, VARLIKLAR
from backtest import backtest_calistir, backtest_karsilastirma_uret
from veri_kalitesi import veri_kalite_olustur
from macro_data import cache_gecmisi, canli_snapshot, demo_snapshot
from notifier import portfoy_raporu_olustur
from rates_tr import mevduat_analizi
from stock_scanner import SINYAL_ETIKET, tam_tarama
from stock_universe import SEKTOR_ETIKET
from advice_engine import danisman_raporu_olustur
from alim_uygunluk import alim_aksiyon_kisa
from advisor_ui import danisman_paneli
from tl_durum import tl_durum_olustur
from investment_report import rapor_paketi_olustur

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
        index=2,
        format_func=lambda k: VADE_SECENEKLERI[k],
    )
    profil = YatirimProfili(risk=risk_etiket, vade=vade_etiket)
    st.caption(profil.ozet())
    st.divider()
    st.header("Ayarlar")
    sayfa = st.radio(
        "Bölüm",
        ["Portföy Tahsisi", "AI Danışman", "TL Mevduat Faizleri", "Hisse & Endeks Taraması", "Backtest"],
    )
    mod = st.radio("Veri modu", ["Canlı veri", "Demo (senaryo)"], index=0)
    toplam = st.number_input("Toplam portföy (EUR)", value=float(config.TOPLAM_EUR), step=1000.0)
    tl_mevduat_tutar = st.number_input(
        "TL mevduat tutarı (TL, isteğe bağlı)",
        value=float(config.TL_MEVDUAT_TUTAR_TL or 0),
        min_value=0.0,
        step=50000.0,
        help="0 bırakırsanız vade sonu simülasyonu önerilen portföy TL dilimini kullanır.",
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
        st.cache_data.clear()
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

config.TOPLAM_EUR = toplam
config.TRANS_SAYISI = int(trans)
tl_mevduat_arg = float(tl_mevduat_tutar) if tl_mevduat_tutar > 0 else None
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


@st.cache_data(ttl=300, show_spinner=False)
def cds_kaynak_ozet(_tick: int = 0):
    from cds_sync import cds_guncelleme_calistir
    return cds_guncelleme_calistir()


@st.cache_data(ttl=180, show_spinner=False)
def veri_cek(canli: bool, _tick: int = 0):
    return canli_snapshot(taze=True) if canli else demo_snapshot()


@st.cache_data(ttl=120, show_spinner=False)
def tarama_cek(
    canli: bool,
    rejim: str,
    snap_veri_kaynak: str,
    _tick: int = 0,
    haber_tara: bool = False,
    profil_risk: str = "orta",
    profil_vade: str = "orta",
):
    del snap_veri_kaynak
    snap = veri_cek(canli, _tick)
    profil = YatirimProfili(risk=profil_risk, vade=profil_vade)
    return tam_tarama(
        makro_rejim=rejim, demo=not canli, snap=snap, haber_tara=haber_tara, profil=profil,
    )


@st.cache_data(ttl=600, show_spinner=False)
def mevduat_cek(enflasyon: float, profil_vade: str, eur_try: float, kalan_gun: int):
    return mevduat_analizi(
        enflasyon, profil_vade=profil_vade, eur_try=eur_try, kalan_gun=kalan_gun,
    )


@st.cache_data(ttl=3600, show_spinner="Backtest hesaplanıyor…")
def backtest_veri(ay: int, vade: str, risk: str):
    from investor_profile import YatirimProfili
    return backtest_calistir(ay, profil=YatirimProfili(risk=risk, vade=vade))


def _tarama_param(profil: YatirimProfili) -> dict:
    return {
        "profil_risk": profil.risk,
        "profil_vade": profil.vade,
    }


def _hisse_tarama_icerik(tarama, snap, tahsis, *, guncelleniyor: bool = False) -> None:
    """Hisse & ETF tarama sayfası gövdesi — spinner yerine satır içi durum."""
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
    st.dataframe(endeks_df, use_container_width=True, hide_index=True)

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
        "52H %": round(h.zirve_52h_pct, 1) if getattr(h, "zirve_52h_pct", None) is not None else None,
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

    st.dataframe(hisse_df, use_container_width=True, hide_index=True)

    st.caption(
        "Evren: BIST/SP500/NASDAQ blue-chip + Revolut UCITS ETF (~23 fon). "
        "Alım fırsatı: RSI 28–45 dipten dönüş veya SMA50 üstü trend (skor ≥55). "
        "Faktör: sektör içi momentum + endeks karşılaştırması (3 ay). "
        "ETF: VWCE (küresel), CSPX/VUAA (S&P500), SGLD (altın), VAGP (tahvil). "
        "Rejim: TL fırsat→küresel ETF + · ENFLASYON→altın/tahvil ETF +."
    )


def _onbellek_temizle():
    veri_cek.clear()
    mevduat_cek.clear()
    # Hisse taraması önbelleği korunur — yalnızca Hisse sayfasında yenilenir


if otoyenile:
    tick = st_autorefresh(interval=aralik_dk * 60 * 1000, key="piyasa_autorefresh")
    if tick > st.session_state.son_yenileme_sayaci:
        st.session_state.son_yenileme_sayaci = tick
        _onbellek_temizle()

if yenile:
    st.session_state.son_yenileme_sayaci += 1
    st.session_state.tarama_son = None
    tarama_cek.clear()
    _onbellek_temizle()
    backtest_veri.clear()


_tick = st.session_state.son_yenileme_sayaci
_profil_anahtar = f"{profil.risk}_{profil.vade}"
if st.session_state.get("tarama_profil_key") != _profil_anahtar:
    st.session_state.tarama_profil_key = _profil_anahtar
    st.session_state.tarama_son = None
    tarama_cek.clear()

st.title("Makro Portföy Asistanı")
st.caption("Karar-destek aracı — otomatik işlem yapmaz, finansal tavsiye değildir.")

with st.status("Canlı veriler çekiliyor… (~5 sn)", expanded=True) as _yukleme:
    snap = veri_cek(canli_mod, _tick)
    _yukleme.update(label=f"Veri hazır — {snap.veri_zamani}", state="complete")

tahsis = tahsis_hesapla(snap, profil)
# Hisse taraması yalnızca Hisse sayfasında çalışır (diğer sekmeler anında açılır)
tarama_ozet = st.session_state.tarama_son
profil_mevduat_etiket, profil_mevduat_gun = profil_mevduat_vadesi(profil)
mevduat_ozet = mevduat_cek(
    snap.enflasyon_tr_yillik or 35.0,
    profil_mevduat_etiket,
    snap.veri.eur_try or 35.0,
    profil_mevduat_gun,
)
danisman = danisman_raporu_olustur(snap, tahsis, profil, tarama_ozet, mevduat=mevduat_ozet)
tl_durum = tl_durum_olustur(snap, tahsis, mevduat_ozet)

with st.sidebar:
    st.divider()
    st.subheader("Anlık yatırım raporu")
    st.caption("Canlı veriler → antetli PDF rapor (makro + hisse/endeks taraması)")

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
                st.session_state.son_rapor = rapor_paketi_olustur(
                    snap, tahsis, profil, danisman, mevduat_ozet, tl_durum, toplam, tarama_rapor,
                    tl_mevduat_tutar_tl=tl_mevduat_arg,
                )
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
                st.session_state.son_rapor = rapor_paketi_olustur(
                    snap, tahsis, profil, danisman, mevduat_ozet, tl_durum, toplam, tarama_rapor,
                    tl_mevduat_tutar_tl=tl_mevduat_arg,
                )
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

durum_renk = "info" if snap.veri_kaynak == "demo" else "success"
durum_metin = (
    "**Demo modu** — makro senaryo sabit, piyasa fiyatları canlı."
    if snap.veri_kaynak == "demo"
    else "**Canlı veri aktif** — her yenilemede API'den taze çekilir (Yahoo, EVDS, TCMB.gov, Yapı Kredi)."
)
getattr(st, durum_renk)(durum_metin)

with st.expander("Veri kalitesi & kaynak şeffaflığı"):
    vk = veri_kalite_olustur(snap)
    k1, k2, k3 = st.columns(3)
    k1.metric("Kalite skoru", f"{vk.genel_skor:.0f}/100")
    k2.metric("Düzey", vk.genel_duzey)
    k3.metric("Mod", vk.mod.upper())
    st.caption(vk.ozet)
    for u in vk.uyarilar:
        st.warning(u)
    st.dataframe(pd.DataFrame([{
        "Gösterge": g.etiket,
        "Değer": g.deger_gosterim,
        "Kalite": g.kalite_etiket,
        "Kaynak": g.kaynak,
        "Tazelik": f"{g.tazelik_saat:.0f} saat" if g.tazelik_saat is not None else "—",
        "Durum": g.tazelik_durum,
        "Eksikte": g.eksik_politikasi[:80],
    } for g in vk.gostergeler]), use_container_width=True, hide_index=True)
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
    st.dataframe(
        pd.DataFrame([
            {
                "Kaynak": k.ad,
                "Değer (bp)": f"{k.deger:.2f}" if k.deger is not None else "—",
                "Gecikme": f"+{k.gecikme_gun}g" if k.gecikmeli else "—",
                "Detay": k.kaynak or k.hata,
            }
            for k in _s.kaynaklar
        ]),
        use_container_width=True,
        hide_index=True,
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
    c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
    c1.metric("Makro rejim", tahsis.rejim.rejim.replace("_", " "))
    c2.metric(
        "EUR/TRY",
        f"{snap.veri.eur_try:.2f}" if snap.veri.eur_try else "—",
        _gunluk_delta(snap.eur_try_1g_degisim),
    )
    if vade_kisa_mi(profil.vade):
        c3.metric(
            f"TL faiz ({profil_mevduat_etiket})",
            f"%{mevduat_ozet.profil_vade_net:.1f} net" if mevduat_ozet.profil_vade_net else "—",
            f"reel {mevduat_ozet.profil_vade_reel:+.1f}%",
        )
        c4.metric("CDS 5Y (ref.)", f"{snap.veri.cds_5y_bp:.0f} bp" if snap.veri.cds_5y_bp else "—")
    else:
        c3.metric("CDS 5Y", f"{snap.veri.cds_5y_bp:.0f} bp" if snap.veri.cds_5y_bp else "—")
        c4.metric(
            f"TL faiz ({profil_mevduat_etiket})",
            f"%{mevduat_ozet.profil_vade_net:.1f} net" if mevduat_ozet.profil_vade_net else "—",
        )
    c5.metric(
        "VIX (ABD)",
        f"{snap.vix:.1f}" if snap.vix else "—",
        _gunluk_delta(snap.vix_1g_degisim),
        delta_color="inverse",
        help="ABD S&P 500 opsiyonlarından — küresel korku endeksi.",
    )
    c6.metric(
        "Altın",
        f"${snap.altin_usd_oz:,.0f}" if snap.altin_usd_oz else "—",
        _gunluk_delta(snap.altin_1g_degisim),
    )
    c7.metric(
        "BIST",
        f"{snap.bist100:,.0f}" if snap.bist100 else "—",
        _gunluk_delta(snap.bist100_1g_degisim),
    )
    c8.metric(
        "BIST Vol (TR)",
        f"{snap.bist_vol_30g:.1f}" if snap.bist_vol_30g is not None else "—",
        _gunluk_delta_pp(snap.bist_vol_1g_degisim),
        delta_color="inverse",
        help="BIST 100 son 30 gün realize volatilite (yıllık %). Resmi TR VIX değil — yerel stres proxy.",
    )
    if not vade_kisa_mi(profil.vade):
        btc_delta = _gunluk_delta(snap.btc_1g_degisim)
        btc_line = f"BTC: ${snap.btc_usd:,.0f}" if snap.btc_usd else "BTC: —"
        if btc_delta:
            btc_line += f" ({btc_delta} 1G)"
        st.caption(btc_line)

    st.info(f"**Makro rejim:** {tahsis.rejim.etiket} — {tahsis.rejim.aciklama}")
    if tahsis.rejim.rejim == "TL_FIRSAT":
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
        for n in tl_durum.nedenler:
            st.markdown(f"- {n}")
        st.caption(f"Alternatif: {tl_durum.alternatif}")
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

    col_sol, col_sag = st.columns([1.2, 1])
    with col_sol:
        st.subheader("Önerilen portföy dağılımı")
        df = pd.DataFrame({
            "Varlık": [config.VARLIK_ETIKETLERI[k] for k in VARLIKLAR],
            "Ağırlık %": [tahsis.agirliklar[k] * 100 for k in VARLIKLAR],
            "Tutar EUR": [toplam * tahsis.agirliklar[k] for k in VARLIKLAR],
            "Skor": [tahsis.skorlar[k] for k in VARLIKLAR],
        })
        df_goster = df[df["Ağırlık %"] >= 0.5].sort_values("Ağırlık %", ascending=False)
        st.bar_chart(df_goster.set_index("Varlık")["Ağırlık %"], horizontal=True)
        for _, row in df_goster.iterrows():
            st.progress(
                min(row["Ağırlık %"] / 100, 1.0),
                text=f"{row['Varlık']}: %{row['Ağırlık %']:.1f} ({row['Tutar EUR']:,.0f} EUR)",
            )

    with col_sag:
        st.subheader("Makro göstergeler")
        g1, g2 = st.columns(2)
        g1.metric("USD/TRY", snap.veri.usd_try or "—")
        g1.metric("Fed faizi", f"{snap.veri.fed_faizi}%" if snap.veri.fed_faizi else "—")
        g1.metric("Enflasyon TR", f"{snap.enflasyon_tr_yillik}%" if snap.enflasyon_tr_yillik else "—")
        g2.metric("TL tavan", f"%{tahsis.tl_tavan_oran*100:.1f}")
        g2.metric("Siyasi risk", snap.veri.siyasi_risk_makale_sayisi or "—")
        g2.metric("TCMB rezerv", "↑" if snap.veri.rezerv_artiyor else "↓" if snap.veri.rezerv_artiyor is False else "?")

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
            st.dataframe(pd.DataFrame([
                {"Zaman": g["ts"], "EUR/TRY": g["payload"].get("veri", {}).get("eur_try"),
                 "CDS": g["payload"].get("veri", {}).get("cds_5y_bp")}
                for g in gecmis
            ]), use_container_width=True)
        else:
            st.caption("Canlı modda otomatik kaydedilir.")

# ══════════════════════════════════════════════════════════════
elif sayfa == "AI Danışman":
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
    st.dataframe(df_m, use_container_width=True, hide_index=True)

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
elif sayfa == "Hisse & Endeks Taraması":
    st.header("Canlı Hisse & Endeks Analizi")
    st.caption(
        "Genişletilmiş evren · Hisse + Revolut UCITS ETF · RSI+SMA · Makro rejim + haber filtresi"
    )

    st.session_state.hisse_haber_tara = st.checkbox(
        "Derin haber taraması (Google News, ~1 dk ek süre)",
        value=st.session_state.hisse_haber_tara,
        key="hisse_haber_chk",
    )
    tara_yenile = st.button("Taramayı yenile", key="hisse_tara_yenile")

    onceki = st.session_state.tarama_son
    if onceki is not None and not tara_yenile:
        _hisse_tarama_icerik(onceki, snap, tahsis)
        st.caption("Son tarama yüklü · güncellemek için **Taramayı yenile**.")
    else:
        if onceki is None:
            st.caption("⏳ İlk tarama ~10–70 sn sürebilir (haber kapalıyken ~10 sn).")
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
            durum.update(label="Tarama tamamlandı", state="complete")
        _hisse_tarama_icerik(tarama, snap, tahsis)

# ══════════════════════════════════════════════════════════════
elif sayfa == "Backtest":
    st.header("Backtest — Dinamik vs Statik")
    st.caption(
        "CDS/enflasyon yaklaşık tablodan — kesin getiri iddiası değil. "
        "Dinamik rejim katmanının statik referansa karşı performansını test eder."
    )
    bt = backtest_veri(bt_ay, profil.vade, profil.risk)
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
            st.dataframe(pd.DataFrame(cmp_rows), use_container_width=True, hide_index=True)

            if kars.rejim_dagilimi:
                st.subheader("Rejim dağılımı")
                rej_df = pd.DataFrame([
                    {"Rejim": r.replace("_", " "), "Süre %": p}
                    for r, p in kars.rejim_dagilimi.items()
                ])
                st.bar_chart(rej_df.set_index("Rejim"))
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
        st.dataframe(bt_df, use_container_width=True, hide_index=True)
        st.line_chart(bt_df.set_index("Ay")[["Altın %", "TL %", "BIST %"]])
    else:
        st.warning("Backtest verisi alınamadı.")
