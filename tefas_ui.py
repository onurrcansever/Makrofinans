# -*- coding: utf-8 -*-
"""TEFAS fon karşılaştırma paneli — Yapı Kredi + Kuveyt Türk Portföy."""
from __future__ import annotations

from copy import deepcopy
from typing import List, Optional

import pandas as pd
import streamlit as st

from investor_profile import YatirimProfili
from fiyat_para import (
    fiyat_sutun_adi,
    fx_serileri_al,
    getiri_sutun_adi,
    kur_al,
    session_gosterim_pb,
    tefas_tablo_fiyat,
    tablo_getiri,
    tutar_goster,
)
from tefas_data import TefasTaramaSonuc, secili_fon_serisi, yk_fonlari_performans
from tefas_skor import fonlari_skorla, top_oneri
from tefas_explain import tefas_neden_metni
from tefas_fon_meta import (
    fon_gider_meta_cache_oku,
    fon_gider_meta_cek,
    gider_meta_uygula,
)
from tefas_stopaj import STOPAJ_CAPTION, tefas_stopaj_sinifi
from tefas_universe import (
    KATEGORILER,
    PARA_BIRIMI,
    populer_yk_kodlari,
    portfoy_sirketi,
    tefas_fiyat_kaynak_pb,
)
from favoriler_widgets import favori_row_keys, favori_yildiz_sutunu, render_df_table_favorili
from ui_theme import plotly_base_layout, render_df_table, render_metric_strip

try:
    import plotly.graph_objects as go
except ImportError:
    go = None


_ONERI_ETIKET = {
    "AL": "🟢 AL",
    "IZLE": "🟡 İZLE",
    "BEKLE": "⚪ BEKLE",
    "ZAYIF": "🔴 Zayıf",
}


def _pct(x: Optional[float]) -> str:
    if x is None:
        return "—"
    return f"{x:+.2f}%"


def _fmt_fiyat(x: float) -> str:
    return f"{x:,.4f}" if x < 10 else f"{x:,.2f}"


def _fmt_pct_oran(x: Optional[float]) -> str:
    if x is None:
        return "—"
    return f"{x:.2f}"


_ONERI_KISA = {
    "AL": "AL",
    "IZLE": "İZLE",
    "BEKLE": "BEKLE",
    "ZAYIF": "Zayıf",
}


def _tablo_df(sonuc: TefasTaramaSonuc, snap=None) -> pd.DataFrame:
    gpb = session_gosterim_pb()
    eur_try, usd_try = kur_al(snap) if snap is not None else (35.0, 37.8)
    eur_s, usd_s, gbp_s, eurusd_s, chf_s = fx_serileri_al()
    gbp_usd = float(gbp_s.dropna().iloc[-1]) if gbp_s is not None and not gbp_s.empty else None
    eur_usd = float(eurusd_s.dropna().iloc[-1]) if eurusd_s is not None and not eurusd_s.empty else None
    chf_usd = float(chf_s.dropna().iloc[-1]) if chf_s is not None and not chf_s.empty else None
    fiyat_kol = fiyat_sutun_adi(gpb)
    h1 = getiri_sutun_adi("1H", gpb)
    a1 = getiri_sutun_adi("1A", gpb)
    a3 = getiri_sutun_adi("3A", gpb)
    ybb = getiri_sutun_adi("YBB", gpb)
    bd = pd.DatetimeIndex(usd_s.index) if usd_s is not None and not usd_s.dropna().empty else None
    rows = []
    for f in sonuc.fonlar:
        src_pb = tefas_fiyat_kaynak_pb(f.para_birimi)
        # KARISIK / PB belirsiz: TEFAS payı çoğu zaman TL kotasyon
        pb_fiyat = src_pb or "TL"
        try:
            fiyat_g = tefas_tablo_fiyat(
                f.fiyat, gpb, pb_fiyat, eur_try, usd_try,
                gbp_usd=gbp_usd, eur_usd=eur_usd, chf_usd=chf_usd,
            )
        except Exception:
            fiyat_g = None
        if fiyat_g is not None:
            fiyat_disp = _fmt_fiyat(fiyat_g)
            if src_pb is None and gpb != "TL":
                fiyat_disp = f"{fiyat_disp}†"
        elif f.fiyat is not None and float(f.fiyat or 0) > 0 and (src_pb == gpb or src_pb is None or gpb == "TL"):
            # Dönüşüm başarısız / PB belirsiz — ham pay (çoğu TL)
            fiyat_disp = _fmt_fiyat(float(f.fiyat)) + ("†" if src_pb is None or gpb != pb_fiyat else "")
        else:
            fiyat_disp = "—"
        asset_pb = pb_fiyat
        rows.append(
            {
                **favori_yildiz_sutunu("tefas", f.kod),
                "Öneri": (
                    _ONERI_KISA.get(f.oneri, f.oneri)
                    + ("*" if f.akran_kucuk else "")
                ),
                "Kod": f.kod,
                "Portföy": portfoy_sirketi(f.ad),
                "Fon": (f.kisa_ad or "")[:30],
                "Kat.": (f.kategori_etiket or "")[:18],
                "PB": f.para_etiket[:8] if f.para_etiket else "—",
                "Yön.%": _fmt_pct_oran(f.yonetim_ucreti_pct),
                # TGO: dolu oran | yönetim gelmiş ama KAP’ta bildirim yok | henüz çekilmedi
                "TGO%": (
                    _fmt_pct_oran(f.tgo_pct)
                    if f.tgo_pct is not None
                    else (
                        "KAP yok"
                        if f.yonetim_ucreti_pct is not None
                        else "—"
                    )
                ),
                "Stopaj": f.stopaj_etiket or "—",
                "Hisse%": f"{f.hisse_pct:.0f}" if f.hisse_pct is not None else "—",
                "Bono%": f"{f.bono_repo_pct:.0f}" if f.bono_repo_pct is not None else "—",
                fiyat_kol: fiyat_disp,
                h1: _pct(tablo_getiri(f.getiri_1h, gpb, 7, eur_s, usd_s, gbp_seri=gbp_s, asset_pb=asset_pb, bar_dates=bd)),
                a1: _pct(tablo_getiri(f.getiri_1a, gpb, 30, eur_s, usd_s, gbp_seri=gbp_s, asset_pb=asset_pb, bar_dates=bd)),
                a3: _pct(tablo_getiri(f.getiri_3a, gpb, 90, eur_s, usd_s, gbp_seri=gbp_s, asset_pb=asset_pb, bar_dates=bd)),
                ybb: _pct(tablo_getiri(
                    f.getiri_ybb, gpb, 0, eur_s, usd_s, gbp_seri=gbp_s, asset_pb=asset_pb, ybb=True, bar_dates=bd,
                )),
                "Skor": f"{f.skor:.0f}",
            }
        )
    return pd.DataFrame(rows)


def tefas_paneli(
    snap,
    profil: YatirimProfili,
    rejim: str,
    mevduat_ozet=None,
    ham_onbellek=None,
) -> None:
    from karar_lejant import tefas_lejant_caption, tefas_lejant_detay
    from ui_theme import render_page_header
    from vergi_notu import vergi_notu_caption, vergi_notu_markdown

    render_page_header(
        "TEFAS Fonları",
        "Yapı Kredi + Kuveyt Türk portföy fonları · resmi TEFAS verisi",
    )
    st.caption(tefas_lejant_caption())
    with st.expander("Sözlük / vergi notu", expanded=False):
        st.caption(tefas_lejant_detay())
        st.caption(vergi_notu_caption("tefas"))
        st.markdown(vergi_notu_markdown(kisa=True))

    ara = st.text_input(
        "Fon ara",
        value="",
        key="tefas_ara",
        placeholder="Kod, fon adı veya portföy (ör. KLU, altın, Kuveyt)…",
        help="Tabloyu kod / ad / portföy şirketine göre anında daraltır.",
    )

    col_a, col_b, col_c, col_d = st.columns([1.1, 1.1, 1.1, 0.9])
    with col_a:
        gun = st.selectbox(
            "Veri penceresi",
            options=[60, 90, 120],
            index=1,
            format_func=lambda g: f"Son {g} gün",
            help="İlk yükleme ~1–2 dk sürebilir; sonraki açılışlar önbellekten gelir.",
        )
    with col_b:
        kat_filtre = st.selectbox(
            "Kategori",
            ["tumu"] + list(KATEGORILER.keys()),
            format_func=lambda k: "Tümü" if k == "tumu" else KATEGORILER[k],
        )
    with col_c:
        siralama = st.selectbox(
            "Sırala",
            ["Skor (profil)", "3 ay getiri", "1 ay getiri", "YBB getiri", "Kod", "Portföy"],
            index=0,
        )
    with col_d:
        yenile = st.button("Yenile", key="tefas_yenile", type="primary", use_container_width=True)
    if yenile:
        from tefas_data import _BD_CACHE, _CACHE, _hedef_pencere_gun
        from app_veri import tefas_ham_cek
        from disk_onbellek import disk_sil

        _CACHE["ts"] = 0.0
        _CACHE["df"] = None
        _CACHE["gun"] = 0
        _BD_CACHE["ts"] = 0.0
        _BD_CACHE["df"] = None
        for g in (60, 90, 120):
            disk_sil(f"tefas:{g}")
            disk_sil(f"tefas:v2:{g}")
        for g in {_hedef_pencere_gun(gun), gun, 120, 90, 60, 30, 14}:
            disk_sil(f"tefas_ham:{int(g)}")
        # Uygulama önbelleğindeki bozuk TEFAS’ı da düşür
        try:
            import streamlit as _st
            ob = _st.session_state.get("app_onbellek")
            if ob is not None:
                ob.tefas_ham = None
                ob.yuklenen_sayfalar -= {"TEFAS Fonları", "Portföy Tahsisi", "Favorilerim", "Asistan"}
        except Exception:
            pass

    from app_veri import (
        _tefas_getiri_bozuk_mu,
        _tefas_pencere_yetersiz_mu,
        tefas_ham_cek,
        tefas_yukleniyor,
    )
    from tefas_progress import progress_durum, render_tefas_progress_strip

    if yenile:
        with st.spinner("TEFAS verisi çekiliyor (90+ gün / YTD — aşamalar üstte)…"):
            ham = tefas_ham_cek(gun, zorla=True)
        st.session_state.tefas_kap_oturum_denenen = set()
        render_tefas_progress_strip()
    elif (
        ham_onbellek is not None
        and not tefas_yukleniyor(ham_onbellek)
        and not _tefas_getiri_bozuk_mu(ham_onbellek)
        and not _tefas_pencere_yetersiz_mu(ham_onbellek)
    ):
        ham = ham_onbellek
        _kap_ok = bool(st.session_state.get("tefas_kap_oturum_tamam")) or bool(
            st.session_state.get("tefas_kap_oturum_denenen")
        )
        st.caption(
            "TEFAS oturum önbelleği · anında"
            + (" · KAP bu oturumda yüklendi" if _kap_ok else "")
            + " · skor yerel (Yenile = yeniden çek)"
        )
    else:
        if ham_onbellek is not None and _tefas_getiri_bozuk_mu(ham_onbellek):
            st.warning(
                "Eski TEFAS önbelleğinde 1A=3A=YBB hatası vardı — doğru tarihçe ile yeniden çekiliyor."
            )
        elif ham_onbellek is not None and _tefas_pencere_yetersiz_mu(ham_onbellek):
            st.info(
                "Yüklü TEFAS tarihçesi kısaydı (3A/YBB boş) — tam pencere (YTD) "
                "arka planda yeniden çekiliyor."
            )
        ham = tefas_ham_cek(gun)
        # Tam pencere geldiyse oturuma yaz — sonraki render'da tekrar düşmesin.
        if (
            ham is not None
            and not tefas_yukleniyor(ham)
            and not _tefas_pencere_yetersiz_mu(ham)
            and ham_onbellek is not None
        ):
            try:
                ob = st.session_state.get("app_onbellek")
                if ob is not None:
                    ob.tefas_ham = ham
            except Exception:
                pass

    # Yüklenirken: aşama şeridi + poll (boş “30–90 sn” mesajı yerine)
    _tefas_bekliyor = tefas_yukleniyor(ham)
    _tefas_bg = bool(progress_durum().get("active"))
    if _tefas_bekliyor or _tefas_bg:
        if _tefas_bg and not _tefas_bekliyor:
            st.session_state["_tefas_bg_strip"] = True

        @st.fragment(run_every=2)
        def _tefas_ilerleme_poll():
            from app_veri import tefas_ham_cek as _cek
            from tefas_progress import progress_durum as _pd, render_tefas_progress_strip as _strip

            _strip()
            stt = _pd()
            if _tefas_bekliyor:
                fresh = _cek(gun)
                if not tefas_yukleniyor(fresh):
                    try:
                        ob = st.session_state.get("app_onbellek")
                        if ob is not None:
                            ob.tefas_ham = fresh
                    except Exception:
                        pass
                    st.rerun()
                elif not stt.get("active") and stt.get("error"):
                    st.caption(f"TEFAS: {stt.get('error')}")
                return
            # Tablo görünürken arka plan tazeleme bitti → bir kez yenile
            if not stt.get("active") and st.session_state.pop("_tefas_bg_strip", None):
                fresh = _cek(gun)
                if not tefas_yukleniyor(fresh):
                    try:
                        ob = st.session_state.get("app_onbellek")
                        if ob is not None:
                            ob.tefas_ham = fresh
                    except Exception:
                        pass
                    st.rerun()

        _tefas_ilerleme_poll()
        if _tefas_bekliyor:
            st.caption(
                "Bellekte tablo yok — üstteki aşamalar canlı ilerliyor. "
                "Disk/önbellek dolunca tablo otomatik açılır."
            )
            return

    if ham.hata and not getattr(ham, "fonlar", None):
        st.error(ham.hata)
        st.info("Kurulum: `pip install pytefas` — TEFAS resmi API kullanılır.")
        return

    mevduat_reel = None
    if mevduat_ozet and getattr(mevduat_ozet, "profil_vade_reel", None) is not None:
        mevduat_reel = mevduat_ozet.profil_vade_reel

    gpb = session_gosterim_pb()
    eur_s, usd_s, gbp_s, _, _chf_s = fx_serileri_al()
    # Önbellek ham listesini filtre bozmasın — arama silinince tam liste geri gelir
    sonuc = fonlari_skorla(
        deepcopy(ham), profil, rejim=rejim, mevduat_reel=mevduat_reel,
        gosterim_pb=gpb, eur_seri=eur_s, usd_seri=usd_s, gbp_seri=gbp_s,
        mevduat_ozet=mevduat_ozet,
    )
    try:
        from tefas_skor import assert_tefas_skor_tutarliligi
        assert_tefas_skor_tutarliligi(sonuc.fonlar)
    except AssertionError:
        pass

    fonlar = list(sonuc.fonlar)
    if kat_filtre != "tumu":
        fonlar = [f for f in fonlar if f.kategori == kat_filtre]

    q = (ara or "").strip().casefold()
    if q:
        def _eslesir(f) -> bool:
            port = portfoy_sirketi(f.ad).casefold()
            hay = " ".join(
                [
                    f.kod or "",
                    f.kisa_ad or "",
                    f.ad or "",
                    f.kategori_etiket or "",
                    port,
                ]
            ).casefold()
            return q in hay

        fonlar = [f for f in fonlar if _eslesir(f)]

    if siralama == "3 ay getiri":
        fonlar.sort(key=lambda f: -(f.getiri_3a or -999))
    elif siralama == "1 ay getiri":
        fonlar.sort(key=lambda f: -(f.getiri_1a or -999))
    elif siralama == "YBB getiri":
        fonlar.sort(key=lambda f: -(f.getiri_ybb or -999))
    elif siralama == "Kod":
        fonlar.sort(key=lambda f: f.kod)
    elif siralama == "Portföy":
        fonlar.sort(key=lambda f: (portfoy_sirketi(f.ad), f.kod))

    for f in fonlar:
        etiket, _oran, _not = tefas_stopaj_sinifi(
            ad=f.ad, kategori=f.kategori, hisse_pct=f.hisse_pct,
        )
        f.stopaj_etiket = etiket

    # Yön.% / TGO: önce disk önbelleği (anında); eksikler KAP’tan (oturumda bir kez)
    kodlar = [f.kod for f in fonlar]
    if fonlar:
        gider_meta_uygula(fonlar, fon_gider_meta_cache_oku(kodlar, limit=len(kodlar)))

    # Eski varsayılan (kapalı) oturum anahtarını bırak — ücretler görünür olsun
    st.session_state.pop("tefas_gider_yukle", None)
    if "tefas_kap_gider" not in st.session_state:
        st.session_state.tefas_kap_gider = True
    if "tefas_kap_oturum_denenen" not in st.session_state:
        st.session_state.tefas_kap_oturum_denenen = set()

    col_kap, col_kap_yenile = st.columns([3.2, 1.0])
    with col_kap:
        gider_yukle = st.checkbox(
            "Yön.% / TGO’yu KAP’tan doldur (resmi; oturumda bir kez, sonra önbellek)",
            key="tefas_kap_gider",
            help="TEFAS profil → KAP fon sayfası + TGO bildirimi. Uydurma oran yok; disk önbelleği ~7 gün. "
            "Aynı Streamlit oturumunda toplu KAP taraması bir kez yapılır; sekme gezinmesinde tekrarlanmaz.",
        )
    with col_kap_yenile:
        kap_zorla = st.button(
            "KAP yenile",
            key="tefas_kap_yenile",
            help="Bu oturumdaki KAP tarama bayrağını sıfırlar ve eksikleri yeniden çeker.",
            use_container_width=True,
        )
    if kap_zorla:
        st.session_state.tefas_kap_oturum_denenen = set()

    if gider_yukle and fonlar:
        # Görünen listedeki eksik Yön.% — oturumda daha önce denenmeyenler
        denenen = st.session_state.tefas_kap_oturum_denenen
        if not isinstance(denenen, set):
            denenen = set(denenen or [])
            st.session_state.tefas_kap_oturum_denenen = denenen
        eksik = [
            f.kod for f in fonlar
            if f.yonetim_ucreti_pct is None and f.kod not in denenen
        ]
        if eksik:
            from tefas_progress import progress_ayarla, progress_bitir

            progress_ayarla(
                "kap",
                f"KAP yönetim ücreti / TGO · {len(eksik)} fon…",
                counter=f"0/{len(eksik)}",
                pct=92.0,
            )
            with st.spinner(
                f"KAP yönetim ücreti / TGO — {len(eksik)} fon "
                f"(~{max(1, int(len(eksik) * 0.4))} sn; oturumda bir kez)…"
            ):
                meta_map = fon_gider_meta_cek(eksik, limit=len(eksik))
            gider_meta_uygula(fonlar, meta_map)
            denenen.update(eksik)
            st.session_state.tefas_kap_oturum_denenen = denenen
            st.session_state["tefas_kap_oturum_tamam"] = True
            progress_bitir(detail=f"KAP tamam · {len(eksik)} fon işlendi")
        elif any(f.yonetim_ucreti_pct is None for f in fonlar):
            st.caption(
                "KAP bu oturumda tarandı · eksik kalanlar için **KAP yenile** "
                "(bildirim yoksa «KAP yok»)."
            )

    gosterim = TefasTaramaSonuc(
        fonlar=fonlar,
        kaynak=sonuc.kaynak,
        guncelleme=sonuc.guncelleme,
        gun=sonuc.gun,
        hata=sonuc.hata,
    )
    oneri_list = top_oneri(gosterim, n=5, kategori=kat_filtre if kat_filtre != "tumu" else None)
    al_aday = sum(1 for f in fonlar if f.oneri == "AL")
    ort_3a = pd.Series([f.getiri_3a for f in fonlar if f.getiri_3a is not None]).median()

    render_metric_strip([
        {"label": "Fon sayısı", "value": str(len(fonlar))},
        {"label": "Uyumluluk adayı", "value": str(al_aday)},
        {"label": "Medyan 3A", "value": _pct(float(ort_3a) if pd.notna(ort_3a) else None)},
        {"label": "Kaynak", "value": ham.guncelleme[:16]},
    ])
    st.caption(
        f"{sonuc.kaynak} · {sonuc.guncelleme} · fiili tarihçe ~**{sonuc.gun}** gün · "
        f"Skor/getiri bazı: **{gpb}** (fon PB → {gpb} kur). "
        f"1A/3A/YBB tarihçe yetersizse — (uydurma eşitleme yok). "
        f"* = küçük kategori (mutlak skor) · † = fiyat PB belirsiz"
    )
    with st.expander("Skor nasıl hesaplanır?", expanded=False):
        st.markdown(
            """
Skor **0–100**; profil risk/vade + makro rejim ile uyuma göre:

1. **Kategori önceliği** — rejime göre (ör. kriz → para piyasası; risk-on → hisse)
2. **Vade uyumu** — kısa vadede hisse/değişken cezası, PP/borçlanma ikramiyesi
3. **Getiri** — gösterim PB’sinde (1A / 3A / YBB; vadene göre hangisi)
4. **Fon büyüklüğü** — büyük fonlara küçük artı
5. **Mevduat eşiği** — PP/borçlanma 1A getirisi mevduatın altındaysa ceza

Öneri eşikleri (signal motoru ile aynı): **AL ≥ 64** (= profil uyumu, emir değil), **İZLE ≥ 52**, **BEKLE ≥ 42**, altı **Zayıf**.
Stopaj ve Yön.%/TGO skora **girmez** (hafif ücret cezası hariç). Makro KRIZ/EM_STRES → risk kategorilerinde AL kapalı.
            """.strip()
        )
    yon_dolu = sum(1 for f in fonlar if f.yonetim_ucreti_pct is not None)
    tgo_dolu = sum(1 for f in fonlar if f.tgo_pct is not None)
    tgo_kap_yok = sum(
        1 for f in fonlar
        if f.yonetim_ucreti_pct is not None and f.tgo_pct is None
    )
    st.caption(
        f"**Yön.%** = uygulanan yıllık yönetim ücreti (KAP) · {yon_dolu}/{len(fonlar)}. "
        f"**TGO%** = KAP TGO bildirimindeki yıllık azami oran · {tgo_dolu}/{len(fonlar)}"
        + (f" · **KAP yok** {tgo_kap_yok} fonda bildirim yayımlanmamış" if tgo_kap_yok else "")
        + ". Oran uydurulmaz — banka/KAP ekranı esas. "
        f"**Stopaj** = iktisap matrisi — {STOPAJ_CAPTION}"
    )

    st.subheader("Fon karşılaştırma")
    if q and not fonlar:
        st.info(f"«{ara}» ile eşleşen fon yok — aramayı veya kategori filtresini gevşetin.")
    tefas_meta = [("tefas", f.kod, f.kisa_ad or f.kod) for f in fonlar]
    render_df_table_favorili(
        _tablo_df(gosterim, snap=snap),
        tefas_meta,
        key_prefix="tefas_tablo",
        max_height=480,
    )
    st.caption("★/☆ satır içi — favori ekle/çıkar (custom component; fragment; tarama yeniden koşmaz)")

    al_fonlar = [f for f in fonlar if f.oneri == "AL"]
    if al_fonlar:
        with st.expander("Neden? — AL önerilerinin gerekçesi", expanded=False):
            for f in al_fonlar:
                st.markdown(tefas_neden_metni(f))
                st.divider()

    st.subheader("Performans grafiği (normalize 100)")
    varsayilan = [f.kod for f in oneri_list[:3]] or populer_yk_kodlari()[:3]
    mevcut_kodlar = {f.kod for f in fonlar}
    varsayilan = [k for k in varsayilan if k in mevcut_kodlar]

    secim = st.multiselect(
        "Grafiğe ekle (en fazla 6)",
        options=sorted(mevcut_kodlar),
        default=varsayilan[:3],
        max_selections=6,
        format_func=lambda k: k,
    )

    if secim:
        seri = secili_fon_serisi(secim, gun=gun)
        if not seri.empty:
            pivot = seri.pivot_table(index="tarih", columns="kod", values="endeks", aggfunc="last")
            if go is not None:
                fig = go.Figure()
                for kod in pivot.columns:
                    fig.add_trace(
                        go.Scatter(
                            x=pivot.index,
                            y=pivot[kod],
                            name=str(kod),
                            mode="lines",
                        )
                    )
                fig.update_layout(
                    **plotly_base_layout(
                        title=f"Normalize performans (başlangıç=100) — son {gun} gün",
                        height=360,
                    )
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.line_chart(pivot)
        else:
            st.warning("Seçili fonlar için seri bulunamadı.")
    else:
        st.info("Grafik için en az bir fon seçin.")

    with st.expander("Kategori rehberi"):
        for kod, etiket in KATEGORILER.items():
            adet = sum(1 for f in fonlar if f.kategori == kod)
            st.write(f"**{etiket}** ({adet} fon) — {PARA_BIRIMI.get('TL', '')}")

    st.caption(
        "Detay ve işlem: [TEFAS](https://www.tefas.gov.tr) · "
        "Yapı Kredi: [yapikredi.com.tr](https://www.yapikredi.com.tr) · "
        "Kuveyt Türk Portföy: [kuveytturkportfoy.com.tr](https://www.kuveytturkportfoy.com.tr)"
    )
