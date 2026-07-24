# -*- coding: utf-8 -*-
"""
Anlık Durum Yatırım Raporu — tüm sistem verilerini tarayan profesyonel çıktı.
Matriks/strateji raporu tarzında antetli HTML + PDF.
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any, List, Optional

import config
from advice_engine import DanismanRaporu
from allocation_engine import TahsisSonucu, VARLIKLAR
from investor_profile import VADE_SECENEKLERI, YatirimProfili
from macro_data import MacroSnapshot
from rates_tr import MevduatKarsilastirma, _eur_bazli_tahmini, tl_vade_sonu_hesapla, tl_vade_sonu_rapor_metni, tmsf_uyari_satirlari
from girdi_dogrulama import girdi_rapor_uyarilari
from report_pdf import _isin_birlestir_gosterim
from stock_scanner import SINYAL_ETIKET, TaramaSonucu
from tl_durum import TlDurumOzeti
from veri_kalitesi import veri_kalite_olustur
from backtest import backtest_calistir, backtest_karsilastirma_uret
from alim_uygunluk import alim_aksiyon_hucre
from bist_52h_eur import format_52h_metin
from report_pdf import rapor_pdf_direkt_olustur


def _esc(text: Any) -> str:
    if text is None:
        return "—"
    return html.escape(str(text))


def _fmt_num(val: Any, nd: int = 2) -> str:
    if val is None:
        return "—"
    try:
        f = float(val)
        if abs(f) >= 1000:
            return f"{f:,.{nd}f}"
        return f"{f:.{nd}f}"
    except (TypeError, ValueError):
        return _esc(val)


def _veri_kaynaklari(snap: MacroSnapshot) -> List[tuple]:
    kh = snap.kaynak_haritasi or {}
    etiketler = [
        ("EUR/TRY", "eur_try"), ("USD/TRY", "usd_try"), ("Altın", "altin"),
        ("BIST 100", "bist100"), ("BTC", "btc"), ("VIX (ABD)", "vix"), ("BIST Vol (TR)", "bist_vol"),
        ("CDS 5Y", "cds"), ("Enflasyon TR", "enflasyon"), ("TL mevduat", "tl_mevduat"),
        ("Fed faizi", "fed_faizi"), ("TCMB faizi", "tcmb_faizi"),
        ("Siyasi risk", "siyasi_risk"), ("Rezerv", "rezerv"),
    ]
    return [(a, kh.get(b, "—")) for a, b in etiketler]


def _md_strip(text: str) -> str:
    return text.replace("**", "").replace("*", "")


_UYGUN_SIRA = {"UYGUN": 0, "SINIRLI": 1, "IZLE": 2, "UYGUN_DEGIL": 3}

_PLAIN_ONERI = {
    "UYGUN": "Şu an alınabilir",
    "SINIRLI": "Sınırlı miktarda değerlendirilebilir",
    "UYGUN_DEGIL": "Şu an uygun değil",
    "IZLE": "İzle, henüz erken",
}

_SINYAL_SADE = {
    "ALIM_FIRSATI": "Teknik alım sinyali veriyor",
    "TREND_ALIM": "Yükseliş trendinde, alım destekli",
    "BEKLE": "Net sinyal yok, beklenebilir",
    "ASIRI_ALIM": "Fiyat yüksek — aşırı alım bölgesinde",
    "UZAK_DUR": "Olumsuz görünüm, kaçınılmalı",
    "VERI_YOK": "Fiyat verisi alınamadı",
}

_ONERI_CSS = {
    "UYGUN": "oneri-al",
    "SINIRLI": "oneri-dikkat",
    "UYGUN_DEGIL": "oneri-alma",
    "IZLE": "oneri-bekle",
}


def _plain_oneri_html(h) -> str:
    return _PLAIN_ONERI.get(getattr(h, "alim_uygun", "IZLE"), "İzle, henüz erken")


def _sinyal_sade_html(sinyal: str) -> str:
    return _SINYAL_SADE.get(sinyal, sinyal)


def _oneri_css(h) -> str:
    return _ONERI_CSS.get(getattr(h, "alim_uygun", "IZLE"), "oneri-bekle")


def _neden_kisa_html(h, max_len: int = 160) -> str:
    not1 = (getattr(h, "alim_uygun_not", "") or "").strip()
    not2 = (getattr(h, "trend_notu", "") or "").strip()
    not3 = (getattr(h, "profil_notu", "") or "").strip()
    not4 = (getattr(h, "temel_not", "") or "").strip()
    sinyal = getattr(h, "sinyal", "")
    uygun = getattr(h, "alim_uygun", "IZLE")
    for n in (not1, not2, not3, not4):
        if n and n not in ("Trend filtresi OK", "Rejim uyumlu", "Faktör nötr", "Profil uyumlu"):
            return n[:max_len - 1] + "…" if len(n) > max_len else n
    if sinyal:
        return _sinyal_sade_html(sinyal)
    return _PLAIN_ONERI.get(uygun, "—")


def _uygun_tablo_hucre(h) -> str:
    return alim_aksiyon_hucre(h)


def _hisse_sirala_html(hisseler: list) -> list:
    return sorted(
        hisseler,
        key=lambda h: (_UYGUN_SIRA.get(getattr(h, "alim_uygun", "IZLE"), 9), -h.skor),
    )


def _skor_sirala_html(hisseler: list) -> list:
    return sorted(
        hisseler,
        key=lambda h: (_UYGUN_SIRA.get(getattr(h, "alim_uygun", "IZLE"), 9), -h.skor),
    )


def _pct_html(val: Optional[float], nd: int = 1) -> str:
    if val is None:
        return "—"
    return f"{val:+.{nd}f}%"


def _uygunluk_ozet_html(tarama: TaramaSonucu) -> str:
    say = {"UYGUN": 0, "SINIRLI": 0, "UYGUN_DEGIL": 0, "IZLE": 0}
    for h in tarama.hisseler or []:
        k = getattr(h, "alim_uygun", "IZLE")
        say[k] = say.get(k, 0) + 1
    return (
        f"Şu an alınabilir: {say['UYGUN']}  ·  Sınırlı/Dikkat: {say['SINIRLI']}  ·  "
        f"Şu an uygun değil: {say['UYGUN_DEGIL']}  ·  İzle/Bekle: {say['IZLE']}"
    )


def _hisse_tablo_html(hisseler: list, *, detayli: bool = False, ilk_sutun: str = "uygunluk") -> str:
    """
    Yatırımcı dostu hisse/ETF tablosu.
    Ana sütunlar: Öneri (renk kodlu) · Varlık Adı · Sembol · Piyasa · Son 1 Ay · Neden?
    Teknik detay (ilk_sutun='sira') modunda sıra numarası + ek kolon gösterilir.
    """
    if not hisseler:
        return ""

    if ilk_sutun == "sira":
        heads = ["Sıra", "Varlık Adı", "Sembol", "Piyasa", "Durum", "Son 1 Ay", "Son 3 Ay"]
    else:
        heads = ["Öneri", "Varlık Adı", "Sembol / Kod", "Piyasa", "Son 1 Ay", "Neden?"]

    thead = "".join(f"<th>{_esc(h)}</th>" for h in heads)
    rows = ""

    for i, h in enumerate(hisseler):
        css = _oneri_css(h)
        rt = getattr(h, "revolut_ticker", "") or h.sembol.split(".")[0]
        sembol_goster = rt if h.piyasa == "ETF" else h.sembol

        if ilk_sutun == "sira":
            cells = [
                f"#{i + 1}",
                _esc(h.ad),
                _esc(h.sembol),
                _esc(h.piyasa),
                _esc(_sinyal_sade_html(h.sinyal)),
                _pct_html(h.degisim_1ay, 0),
                _pct_html(getattr(h, "degisim_3ay", None), 0),
            ]
            num_set = {5, 6}
        else:
            cells = [
                f'<span class="{css}">{_esc(_plain_oneri_html(h))}</span>',
                _esc(h.ad),
                _esc(sembol_goster),
                _esc(h.piyasa),
                _pct_html(h.degisim_1ay, 0),
                _esc(_neden_kisa_html(h)),
            ]
            num_set = {4}

        tds = ""
        for j, c in enumerate(cells):
            cls = ' class="num"' if j in num_set else ""
            tds += f"<td{cls}>{c}</td>"
        rows += f"<tr>{tds}</tr>"

    return f"<table><thead><tr>{thead}</tr></thead><tbody>{rows}</tbody></table>"


def _hisse_detay_li(h) -> str:
    neden = _neden_kisa_html(h, 80)
    css = _oneri_css(h)
    return (
        f'<li><span class="{css}">{_esc(_plain_oneri_html(h))}</span> &nbsp;'
        f'{_esc(h.ad)} ({_esc(h.sembol)}) &nbsp;·&nbsp; '
        f'{_esc(_sinyal_sade_html(h.sinyal))} &nbsp;·&nbsp; '
        f'Son 1 Ay: {_pct_html(h.degisim_1ay)} &nbsp;·&nbsp; '
        f'Son 3 Ay: {_pct_html(getattr(h, "degisim_3ay", None))}'
        + (f' &nbsp;— {_esc(neden)}' if neden else '')
        + '</li>'
    )


def _backtest_html(
    rejim: str,
    profil: YatirimProfili,
    bugun_agirliklar: Optional[dict] = None,
    ay: int = 12,
    onceden_hesaplanan_kars=None,
) -> str:
    """Backtest HTML bloğu. onceden_hesaplanan_kars verilirse yeniden hesaplama yapılmaz."""
    try:
        if onceden_hesaplanan_kars is not None:
            kars = onceden_hesaplanan_kars
            satirlar = kars.satirlar or []
        else:
            satirlar = backtest_calistir(ay, profil=profil)
            kars = backtest_karsilastirma_uret(
                satirlar, rejim, bugun_agirliklar=bugun_agirliklar, profil=profil
            )
    except Exception:
        return ""
    if not kars:
        return ""

    met = kars.dinamik
    ref = kars.referans_statik
    karsi = kars.karsi_olgusal
    rejim = rejim  # local alias for clarity
    rejim_hic_gorulmedi = (
        rejim and met.mevcut_rejim_oran_pct is not None
        and met.mevcut_rejim_oran_pct < 1
    )

    def _sh(m):
        return f"{m.sharpe_yillik:.2f}" if m.sharpe_yillik is not None else "—"

    # Dinamik'i yenen karşılaştırmayı bul (statik mi, bugünkü ağırlıklar mı?)
    _en_iyi = kars.en_iyi_strateji
    _din_sh = met.sharpe_yillik or 0
    if (karsi and karsi.sharpe_yillik is not None
            and karsi.sharpe_yillik - _din_sh >= 0.25):
        _kaz_lbl = "bugünkü ağırlıkları sabit tutmak"
        _kaz_sh = f"{karsi.sharpe_yillik:.2f}"
    else:
        _kaz_lbl = "statik referans portföy"
        _kaz_sh = f"{ref.sharpe_yillik:.2f}" if ref.sharpe_yillik else "—"

    uyari = ""
    if kars.dinamik_dezavantaj and rejim_hic_gorulmedi:
        uyari = f"""<div class="ozet-kutu tl-onerilmiyor">
<strong>Önemli Uyarı — Bu Raporun Önerisini Nasıl Okumalısınız</strong>
<p>Backtest iki kritik sorunu aynı anda ortaya koyuyor:</p>
<ol>
<li>Son {ay} ayda <strong>{_kaz_lbl}</strong> dinamik rejim modelinden <strong>daha iyi</strong> performans sergiledi
(Sharpe: Dinamik {_din_sh:.2f} &ndash; {_esc(_en_iyi)}: {_kaz_sh}).</li>
<li>Mevcut rejim (<em>{_esc(rejim.replace("_", " "))}</em>) bu dönemde hiç görülmedi
(%{met.mevcut_rejim_oran_pct:.0f}) — bugünkü öneri seti <strong>test edilmemiş koşullara</strong> dayanıyor.</li>
</ol>
<p><strong>Sonuç:</strong> Rapordaki spesifik yüzdelerden çok <em>çerçeveyi</em> (başabaş kur, TL tavan mantığı,
reel getiri ayrımı) esas alınız. Yaklaşan merkez bankası kararları öncesinde
büyük pozisyon değişikliği yapmamak raporun kendi verileriyle uyumludur.</p>
</div>"""
    elif kars.dinamik_dezavantaj and kars.uyari_mesaji:
        uyari = f"<div class='ozet-kutu tl-sinirli'><strong>Dinamik Katman Uyarısı:</strong> {_esc(kars.uyari_mesaji)}</div>"
    elif rejim_hic_gorulmedi:
        uyari = f"""<div class="ozet-kutu tl-sinirli">
<strong>Dikkat — Test Edilmemiş Rejim:</strong>
Mevcut rejim ({_esc(rejim.replace("_", " "))}) geçmiş {ay} aylık simülasyonda
%{met.mevcut_rejim_oran_pct:.0f} ile temsil edildi — tarihsel referans çok sınırlı.
</div>"""

    karsi_hdr = "<th>Bugünkü ağırlıklar</th>" if karsi else ""
    karsi_cells = ""
    if karsi:
        karsi_cells = (
            f"<td class='num'>{karsi.toplam_getiri_pct:+.1f}%</td>"
            f"<td class='num'>{_sh(karsi)}</td>"
            f"<td class='num'>{karsi.max_drawdown_pct:.1f}%</td>"
            f"<td class='num'>{karsi.volatilite_yillik_pct:.1f}%</td>"
        )

    rej_tab = ""
    if kars.rejim_dagilimi:
        rej_tr = "".join(
            f"<tr><td>{_esc(r.replace('_', ' '))}</td><td class='num'>%{p:.0f}</td></tr>"
            for r, p in kars.rejim_dagilimi.items()
        )
        rej_tab = f"""
        <h3>Rejim dağılımı</h3>
        <table><thead><tr><th>Rejim</th><th>Süre</th></tr></thead><tbody>{rej_tr}</tbody></table>"""

    tablo = ""
    if satirlar:
        tr = ""
        for s in satirlar[-6:]:
            tr += (
                f"<tr><td>{_esc(s.tarih)}</td><td>{_esc(s.rejim_etiket)}</td>"
                f"<td class='num'>{_fmt_num(s.eur_try, 1)}</td>"
                f"<td class='num'>%{s.agirliklar.get('gold', 0) * 100:.0f}</td>"
                f"<td class='num'>%{s.agirliklar.get('tl_deposit', 0) * 100:.0f}</td>"
                f"<td class='num'>%{s.agirliklar.get('bist', 0) * 100:.0f}</td></tr>"
            )
        tablo = f"""
        <table>
            <thead><tr><th>Ay</th><th>Rejim</th><th>EUR/TRY</th><th>Altın</th><th>TL</th><th>BIST</th></tr></thead>
            <tbody>{tr}</tbody>
        </table>"""

    return f"""
    <h2>Backtest — Dinamik vs Statik Karşılaştırma</h2>
    {uyari}
    <p>{_esc(kars.ozet.replace('**', ''))}</p>
    <p class='muted'>Üç yollu simülasyon: aylık dinamik rejim · profil referansı ({_esc(profil.risk)} risk) · bugünkü ağırlıklar sabit.</p>
    <table>
        <thead><tr>
            <th>Metrik</th><th>Dinamik rejim</th><th>Referans statik</th>{karsi_hdr}
        </tr></thead>
        <tbody>
            <tr><td>Toplam getiri</td>
                <td class='num'>{met.toplam_getiri_pct:+.1f}%</td>
                <td class='num'>{ref.toplam_getiri_pct:+.1f}%</td>
                {f"<td class='num'>{karsi.toplam_getiri_pct:+.1f}%</td>" if karsi else ""}</tr>
            <tr><td>Sharpe (yıllık)</td>
                <td class='num'>{_sh(met)}</td><td class='num'>{_sh(ref)}</td>
                {f"<td class='num'>{_sh(karsi)}</td>" if karsi else ""}</tr>
            <tr><td>Max drawdown</td>
                <td class='num'>{met.max_drawdown_pct:.1f}%</td><td class='num'>{ref.max_drawdown_pct:.1f}%</td>
                {f"<td class='num'>{karsi.max_drawdown_pct:.1f}%</td>" if karsi else ""}</tr>
            <tr><td>Volatilite</td>
                <td class='num'>{met.volatilite_yillik_pct:.1f}%</td><td class='num'>{ref.volatilite_yillik_pct:.1f}%</td>
                {f"<td class='num'>{karsi.volatilite_yillik_pct:.1f}%</td>" if karsi else ""}</tr>
        </tbody>
    </table>
    {rej_tab}
    <ul>{"".join(f"<li>{_esc(n)}</li>" for n in met.notlar[:2])}
        <li>{_esc(ref.notlar[0])}</li></ul>
    {tablo}"""


def rapor_html_olustur(
    snap: MacroSnapshot,
    tahsis: TahsisSonucu,
    profil: YatirimProfili,
    danisman: DanismanRaporu,
    mevduat: Optional[MevduatKarsilastirma] = None,
    tl_durum: Optional[TlDurumOzeti] = None,
    toplam_eur: float = None,
    tarama: Optional[TaramaSonucu] = None,
    tl_mevduat_tutar_tl: Optional[float] = None,
    birlesik_oneri=None,
    varlik_store=None,
    kullanici_portfoy=None,
    para_birimi: str = "EUR",
    tefas_ham=None,
) -> str:
    toplam_eur = toplam_eur or config.TOPLAM_EUR
    v = snap.veri
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    rapor_uretim_zamani = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    try:
        import subprocess
        _git_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=__file__[:__file__.rfind("/")],
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode().strip()
    except Exception:
        _git_hash = "—"
    vade_metin = VADE_SECENEKLERI.get(profil.vade, profil.vade)

    makro_satirlar = ""
    if danisman.makro_baglam:
        for p in danisman.makro_baglam.parcalar:
            makro_satirlar += f"""
            <div class="makro-kart">
                <h4>{_esc(p.baslik)}</h4>
                <p><strong>Canlı:</strong> {_esc(_md_strip(p.canli))}</p>
                <p>{_esc(_md_strip(p.konum))}</p>
                <p class="muted"><em>Beklenti:</em> {_esc(_md_strip(p.beklenti)[:500])}</p>
            </div>"""

    tahsis_rows = ""
    for k in sorted(VARLIKLAR, key=lambda x: -tahsis.agirliklar.get(x, 0)):
        w = tahsis.agirliklar.get(k, 0)
        if w < 0.005:
            continue
        tahsis_rows += f"""
        <tr>
            <td>{_esc(config.VARLIK_ETIKETLERI[k])}</td>
            <td class="num">%{w * 100:.1f}</td>
            <td class="num">{toplam_eur * w:,.0f} EUR</td>
        </tr>"""

    varlik_kartlari = ""
    for var in danisman.varliklar:
        nedenler = "".join(f"<li>{_esc(_md_strip(n))}</li>" for n in var.nedenler[:5])
        dikkat = "".join(f"<li>{_esc(_md_strip(d))}</li>" for d in var.dikkat[:3])
        teknik_html = (
            f"<p class='muted'><strong>Teknik ({_esc(var.ad)}):</strong> "
            f"{_esc(_md_strip(var.teknik))}</p>"
            if getattr(var, "teknik", None) else ""
        )
        varlik_kartlari += f"""
        <div class="varlik-kart">
            <h4>{_esc(var.ad)} — {_esc(var.sinyal_etiket)} ({_esc(var.ok)})</h4>
            <p><strong>Ağırlık:</strong> %{var.agirlik_pct:.1f} · <strong>Güven:</strong> {var.guven}/100</p>
            <p>{_esc(_md_strip(var.baslik))}</p>
            <ul>{nedenler}</ul>
            {teknik_html}
            {"<p><strong>Dikkat:</strong></p><ul>" + dikkat + "</ul>" if dikkat else ""}
        </div>"""

    mevduat_html = ""
    if mevduat:
        profil_reel = getattr(mevduat, "profil_vade_reel", None)
        profil_eur_tah = getattr(mevduat, "profil_vade_eur_tahmini", None)
        reel_cok_dusuk = profil_reel is not None and profil_reel < 0.5

        mev_rows = ""
        for o in mevduat.oranlar:
            isaret = " ✓" if o.vade == mevduat.profil_vade else ""
            net_pct = o.net_yillik * 100
            eur_tah = (
                f"{_eur_bazli_tahmini(net_pct, mevduat.enflasyon):+.1f}*"
                if o.vade.startswith("TL") else "—"
            )
            reel_val = o.reel_yillik or 0
            reel_str = f"{reel_val:+.1f}"
            if reel_val < 0.5 and o.vade.startswith("TL"):
                reel_str = f'<span style="color:#c0392b;font-weight:600">{reel_val:+.1f} (!)</span>'
            mev_rows += f"""
            <tr>
                <td>{_esc(o.vade)}{isaret}</td>
                <td class="num">%{o.brut_yillik * 100:.2f}</td>
                <td class="num">%{net_pct:.2f}</td>
                <td class="num">{reel_str}</td>
                <td class="num">{eur_tah}</td>
            </tr>"""

        getiri_kutu = ""
        if mevduat.getiri_notu:
            uyari_sinif = "ozet-kutu tl-sinirli" if reel_cok_dusuk else "ozet-kutu"
            uyari_ek = ""
            if reel_cok_dusuk:
                uyari_ek = (
                    f" <strong>Uyarı:</strong> Profilinizin vadesi için yerel reel getiri "
                    f"yalnızca {profil_reel:+.1f} puan — pratikte enflasyona karşı sıfır koruma."
                )
            eur_caveat = ""
            if profil_eur_tah is not None and profil_eur_tah > 0:
                eur_caveat = (
                    f" EUR bazlı tahmin (<strong>{profil_eur_tah:+.1f} puan</strong>) "
                    "EUR/TRY kurunun vade boyunca <em>değişmeyeceği</em> varsayımına dayanır. "
                    "Kur şok senaryosunda bu getiri negatife dönebilir. "
                    'Tablodaki "*" işaretli değerler bu varsayımı içerir.'
                )
            getiri_kutu = (
                f'<div class="{uyari_sinif}">'
                f"<strong>Getiri Tanımı — Önemli:</strong> {_esc(mevduat.getiri_notu)}"
                f"{uyari_ek}{eur_caveat}</div>"
            )

        vade_sonu_html = ""
        profil_o = next((o for o in mevduat.oranlar if o.vade == mevduat.profil_vade), None)
        if profil_o and v.eur_try:
            tl_tutar = tl_mevduat_tutar_tl or config.TL_MEVDUAT_TUTAR_TL
            ozet = tl_vade_sonu_hesapla(
                toplam_eur=toplam_eur,
                tl_agirlik=tahsis.agirliklar.get("tl_deposit", 0),
                eur_try=v.eur_try,
                brut_yillik=profil_o.brut_yillik,
                gun=profil_o.vade_gun or 365,
                manuel_anapara_tl=tl_tutar,
            )
            if ozet:
                tmsf_html = "".join(
                    f"<li>{_esc(_md_strip(t))}</li>" for t in tmsf_uyari_satirlari(ozet.anapara_tl)
                )
                vade_sonu_html = (
                    f'<p><strong>{_esc(_md_strip(tl_vade_sonu_rapor_metni(ozet)))}</strong></p>'
                    f"<ul>{tmsf_html}</ul>"
                )
        mevduat_html = f"""
        <h2>TL Mevduat &amp; Faiz Karşılaştırması</h2>
        <p>{_esc(mevduat.ozet)}</p>
        <p class="muted">Enflasyon girdisi: {_esc((snap.kaynak_haritasi or {}).get("enflasyon", "—"))}</p>
        {getiri_kutu}
        {vade_sonu_html}
        <p class="muted">Veri: {_esc(mevduat.veri_kaynagi)} &nbsp;·&nbsp; Profil vadesi: {_esc(mevduat.profil_vade)}</p>
        <table>
            <thead><tr><th>Vade</th><th>Brüt %</th><th>Net %</th><th>Yerel Reel (enf. üstü)</th><th>EUR Karş. (tahmini*)</th></tr></thead>
            <tbody>{mev_rows}</tbody>
        </table>"""

    tl_html = ""
    if tl_durum:
        tl_neden = "".join(f"<li>{_esc(_md_strip(n))}</li>" for n in tl_durum.nedenler)
        tl_html = f"""
        <h2>TL Mevduat Kararı (Dinamik)</h2>
        <div class="ozet-kutu tl-{tl_durum.durum.lower()}">
            <strong>{_esc(tl_durum.baslik)}</strong><br>
            Portföy payı: %{tl_durum.agirlik_pct:.1f} · 4 kapı tavanı: %{tl_durum.tavan_pct:.0f}
        </div>
        <ul>{tl_neden}</ul>
        <p><em>Alternatif:</em> {_esc(tl_durum.alternatif)}</p>"""

    denetim_html = ""
    if danisman.denetim and danisman.denetim.bulgular:
        bulgular = ""
        for b in danisman.denetim.bulgular[:8]:
            bulgular += f"<li><strong>[{b.seviye}]</strong> {_esc(b.baslik)} — {_esc(b.oneri)}</li>"
        denetim_html = f"""
        <h2>Denetim & Tutarlılık</h2>
        <p>{_esc(danisman.denetim.ozet)}</p>
        <ul>{bulgular}</ul>"""

    tarama_html = ""
    if tarama and (tarama.endeksler or tarama.hisseler):
        from endeks_yonlendirme import (
            endeks_alanlarini_doldur,
            oncelik_ozeti_sade,
            ozet_neden,
        )
        from karar_lejant import endeks_lejant_caption

        makro = (
            getattr(tarama, "makro_rejim", None)
            or getattr(getattr(tahsis, "rejim", None), "rejim", None)
            or "NOTR"
        )
        endeks_alanlarini_doldur(
            tarama.endeksler,
            fx_ok=True,
            makro_rejim=makro,
            snap=snap,
        )
        oncelik = oncelik_ozeti_sade(tarama.endeksler)
        oncelik_html = (
            f'<p><strong>{_esc(_md_strip(oncelik))}</strong></p>' if oncelik else ""
        )
        endeks_rows = ""
        for e in tarama.endeksler:
            d1 = f"{e.degisim_1g:+.1f}%" if e.degisim_1g is not None else "—"
            d1a = f"{e.degisim_1ay:+.1f}%" if e.degisim_1ay is not None else "—"
            d3a = f"{e.degisim_3ay:+.1f}%" if e.degisim_3ay is not None else "—"
            oneri = _esc(getattr(e, "aksiyon_etiket", None) or "Bekle")
            neden = _esc(ozet_neden(e))
            endeks_rows += f"""
            <tr>
                <td>{_esc(e.ad)}</td>
                <td class="num">{_fmt_num(e.fiyat, 0 if (e.fiyat or 0) >= 100 else 2)}</td>
                <td class="num">{d1}</td>
                <td class="num">{d1a}</td>
                <td class="num">{d3a}</td>
                <td><strong>{oneri}</strong></td>
                <td>{neden}</td>
            </tr>"""

        uygun_list = _hisse_sirala_html([
            h for h in (tarama.hisseler or []) if getattr(h, "alim_uygun", "") == "UYGUN"
        ])
        sinirli_list = _hisse_sirala_html([
            h for h in (tarama.hisseler or []) if getattr(h, "alim_uygun", "") == "SINIRLI"
        ])
        etf_firsat = getattr(tarama, "etf_firsatlari", None) or []
        kanonik = _isin_birlestir_gosterim(
            _hisse_sirala_html(uygun_list + sinirli_list + list(etf_firsat))
        )
        kanonik.sort(
            key=lambda h: (_UYGUN_SIRA.get(getattr(h, "alim_uygun", "IZLE"), 9), -h.skor)
        )
        if kanonik:
            al_n = len(uygun_list)
            max_satir = config.TARAMA_KANONIK_MAX_SATIR if al_n == 0 else 35
            trunc_not = ""
            evren_n = len(tarama.hisseler or [])
            if al_n == 0 and len(kanonik) > max_satir:
                trunc_not = (
                    f" <span class='muted'>UYGUN yok — özet tablo {max_satir} satır "
                    f"(listede {len(kanonik)} sınırlı/ETF; taranan evren {evren_n} sembol).</span>"
                )
            kanonik_blok = f"""
            <h3>Yatırım Önerileri — {al_n} Alınabilir (UYGUN) · {len(sinirli_list)} Dikkat · {len(etf_firsat)} ETF{trunc_not}</h3>
            <p class="muted">Her satırda "Öneri" sütunu o varlığı şu an almanızın uygun olup olmadığını,
            "Neden?" sütunu ise gerekçeyi sade dilde açıklar.</p>
            {_hisse_tablo_html(kanonik[:max_satir])}"""
        else:
            kanonik_blok = (
                "<p class='muted'>Şu an profil ve piyasa koşullarınıza uygun alım adayı bulunmuyor. "
                "Makro tahsis (mevduat / altın / EUR) öncelikli dönem.</p>"
            )

        onemli = _hisse_sirala_html([
            h for h in (tarama.hisseler or [])
            if getattr(h, "alim_uygun", "") in ("UYGUN", "SINIRLI")
            or h.sinyal in ("ALIM_FIRSATI", "TREND_ALIM")
        ])[:35]
        teknik_blok = ""
        if onemli:
            teknik_blok = f"""
            <h3>Teknik Görünüm — Öne Çıkan {len(onemli)} Varlık</h3>
            <p class="muted">Aşağıdaki tablo teknik durum bilgisi içindir. Alım kararı için yukarıdaki
            "Yatırım Önerileri" tablosunu esas alınız.</p>
            {_hisse_tablo_html(onemli, ilk_sutun="sira")}"""

        piyasa_html = ""
        piyasa_html += (
            "<p class='muted'>Her piyasadan en yüksek puan alan 6 varlık. "
            "Alım kararı için yalnızca &ldquo;Yatırım Önerileri&rdquo; tablosunu esas alınız.</p>"
        )
        piyasa_etiket = {
            "BIST": "Borsa İstanbul (BIST)",
            "SP500": "ABD S&P 500",
            "NASDAQ": "ABD NASDAQ",
            "AVRUPA": "Avrupa hisseleri",
            "ETF": "ETF (Borsa Yatırım Fonu)",
        }
        for piyasa in ("BIST", "SP500", "NASDAQ", "AVRUPA", "ETF"):
            grup = _skor_sirala_html([
                h for h in (tarama.hisseler or [])
                if h.piyasa == piyasa and h.sinyal not in ("ASIRI_ALIM", "UZAK_DUR", "VERI_YOK")
            ])[:6]
            if not grup:
                continue
            piyasa_html += f"""
            <h4>{piyasa_etiket.get(piyasa, piyasa)}</h4>
            {_hisse_tablo_html(grup, ilk_sutun="sira")}"""

        uyarilar = "".join(f"<li>{_esc(u)}</li>" for u in (tarama.uyarilar or [])[:3])
        profil_blok = ""
        if getattr(tarama, "profil_ozet", ""):
            profil_not = "".join(
                f"<li>{_esc(n)}</li>" for n in (getattr(tarama, "profil_notlari", None) or [])[:5]
            )
            profil_blok = f"""
        <div class="box"><strong>Tarama profili:</strong> {_esc(tarama.profil_ozet)}
        <ul>{profil_not}</ul></div>"""
        ozet = getattr(tarama, "tarama_ozet", "") or ""
        tarama_html = f"""
        <h2>Hisse &amp; ETF Yatırım Önerileri</h2>
        <p class="muted"><strong>Öneri açıklaması:</strong>
        "Şu an alınabilir" = teknik ve makro koşullar uygun, alım değerlendirilebilir ·
        "Sınırlı" = bazı uyarılar var, küçük pay ile değerlendirilebilir ·
        "Şu an uygun değil" = koşullar olumsuz, beklenmeli ·
        "İzle" = net bir sinyal yok, fiyat takibi önerilir.
        Tüm veriler Yahoo Finance (gecikmeli). Mevcut rejim: {_esc(tahsis.rejim.etiket)}.</p>
        {profil_blok}
        <div class="box">
            <strong>Özet:</strong> {_esc(_uygunluk_ozet_html(tarama))}
            {"<p class='muted'>" + _esc(ozet) + "</p>" if ozet else ""}
        </div>
        {"<ul class='muted'>" + uyarilar + "</ul>" if uyarilar else ""}
        <h3>Ana Endeksler — BIST 100 · NASDAQ · S&amp;P 500</h3>
        {oncelik_html}
        <p class="muted">Öneri = pozisyon ağırlığı (Artır / Koru / Bekle / Azalt).
        Getiriler yerel para biriminde. {_esc(_md_strip(endeks_lejant_caption()))}</p>
        <table>
            <thead><tr><th>Endeks</th><th>Fiyat</th><th>1 Gün</th><th>1 Ay</th><th>3 Ay</th><th>Öneri</th><th>Neden</th></tr></thead>
            <tbody>{endeks_rows}</tbody>
        </table>
        {kanonik_blok}
        {teknik_blok}
        <h3>Piyasaya Göre Öne Çıkanlar</h3>
        {piyasa_html}"""

    # Backtest tek seferinde çalıştır — hem özet hem de teknik ek aynı sonucu kullanır
    _backtest_ozet_uyari = ""
    _bt_kars_onceden = None
    try:
        _bt_satirlar = backtest_calistir(12, profil=profil)
        _bt_kars_onceden = backtest_karsilastirma_uret(
            _bt_satirlar, tahsis.rejim.rejim,
            bugun_agirliklar=tahsis.agirliklar, profil=profil
        )
    except Exception:
        _bt_kars_onceden = None

    backtest_html = _backtest_html(
        tahsis.rejim.rejim, profil,
        bugun_agirliklar=tahsis.agirliklar,
        onceden_hesaplanan_kars=_bt_kars_onceden,
    )

    _bt_kars = _bt_kars_onceden
    if _bt_kars:
            _bt_met = _bt_kars.dinamik
            _bt_ref = _bt_kars.referans_statik
            _bt_karsi = _bt_kars.karsi_olgusal
            _bt_rejim_hic = (
                tahsis.rejim.rejim
                and _bt_met.mevcut_rejim_oran_pct is not None
                and _bt_met.mevcut_rejim_oran_pct < 1
            )
            # Dinamik'i yenen karşılaştırmayı bul (statik mi, bugünkü ağırlıklar mı?)
            _bt_en_iyi = _bt_kars.en_iyi_strateji
            if _bt_karsi and _bt_karsi.sharpe_yillik is not None and _bt_met.sharpe_yillik is not None:
                _kar_sh = _bt_karsi.sharpe_yillik
                _din_sh = _bt_met.sharpe_yillik
                if _kar_sh - _din_sh >= 0.25:
                    _bt_kazanan_etiket = "bugünkü ağırlıkları sabit tutmak"
                    _bt_kazanan_sh = f"{_kar_sh:.2f}"
                    _bt_din_sh_str = f"{_din_sh:.2f}"
                else:
                    _bt_kazanan_etiket = "statik referans portföy"
                    _bt_kazanan_sh = f"{_bt_ref.sharpe_yillik:.2f}" if _bt_ref.sharpe_yillik else "—"
                    _bt_din_sh_str = f"{_din_sh:.2f}"
            else:
                _bt_kazanan_etiket = _bt_en_iyi.lower()
                _bt_kazanan_sh = (
                    f"{_bt_ref.sharpe_yillik:.2f}" if _bt_ref.sharpe_yillik else "—"
                )
                _bt_din_sh_str = f"{_bt_met.sharpe_yillik:.2f}" if _bt_met.sharpe_yillik else "—"

            if _bt_kars.dinamik_dezavantaj and _bt_rejim_hic:
                _backtest_ozet_uyari = (
                    f'<div class="ozet-kutu tl-onerilmiyor" style="margin-top:14px">'
                    f"<strong>Model Sınırı — Önemli:</strong> "
                    f"Son 12 ayda <strong>{_bt_kazanan_etiket}</strong> dinamik rejim modelinden "
                    f"<strong>daha iyi</strong> performans sergiledi "
                    f"(Sharpe: Dinamik {_bt_din_sh_str} — {_bt_en_iyi}: {_bt_kazanan_sh}). "
                    f"Üstelik mevcut rejim ({_esc(tahsis.rejim.rejim.replace('_', ' '))}) "
                    "simülasyon döneminde hiç görülmedi — öneri seti test edilmemiş koşullara dayanıyor. "
                    "Spesifik yüzdelerden çok çerçeveyi (başabaş kur, TL tavan, reel getiri) esas alınız. "
                    "Teknik Ekler &gt; Backtest bölümünde tam analiz mevcuttur.</div>"
                )
            elif _bt_kars.dinamik_dezavantaj:
                _backtest_ozet_uyari = (
                    f'<div class="ozet-kutu tl-sinirli" style="margin-top:14px">'
                    f"<strong>Model Uyarısı:</strong> Son 12 ayda <strong>{_bt_kazanan_etiket}</strong> "
                    f"dinamik rejim modelinden daha iyi performans sergiledi "
                    f"(Sharpe: Dinamik {_bt_din_sh_str} — {_bt_en_iyi}: {_bt_kazanan_sh}). "
                    "Önerileri rehber olarak kullanın, kesin emir olarak değil.</div>"
                )

    from kullanici_portfoy import varsayilan_portfoy
    from rapor_ek_bolumler import (
        birlesik_oneri_html_blok,
        tefas_fonlari_html_blok,
        varliklarim_html_blok,
    )

    kp = kullanici_portfoy or varsayilan_portfoy()
    birlesik_html = birlesik_oneri_html_blok(
        birlesik_oneri,
        para_birimi=para_birimi,
        toplam_eur=toplam_eur,
        eur_try=v.eur_try or 35.0,
        esc=_esc,
        makro_agirliklar=tahsis.agirliklar,
    )
    _mev_reel_html = None
    if mevduat is not None:
        _mev_reel_html = getattr(mevduat, "profil_vade_reel", None)
        if _mev_reel_html is None:
            _mev_reel_html = getattr(mevduat, "reel_getiri_pp", None)
    tefas_html = tefas_fonlari_html_blok(
        tefas_ham,
        esc=_esc,
        profil=profil,
        rejim=getattr(getattr(tahsis, "rejim", None), "rejim", None) or "NOTR",
        mevduat_reel=_mev_reel_html,
        gosterim_pb=para_birimi or "EUR",
    )
    varlik_html = varliklarim_html_blok(varlik_store, snap, kp, esc=_esc)

    kaynak_rows = ""
    vk = veri_kalite_olustur(snap)
    for g in vk.gostergeler:
        tz = f"{g.tazelik_saat:.0f}s" if g.tazelik_saat is not None else "—"
        kaynak_rows += (
            f"<tr><td>{_esc(g.etiket)}</td><td class='num'>{_esc(g.deger_gosterim)}</td>"
            f"<td>{_esc(g.kalite_etiket)}</td><td>{_esc(g.kaynak)}</td><td>{tz}</td></tr>"
        )
    kalite_uyarilar = "".join(f"<li>{_esc(u)}</li>" for u in vk.uyarilar[:4])
    kalite_blok = f"""
    <div class="ozet-kutu"><strong>Veri kalitesi: {vk.genel_skor:.0f}/100 ({vk.genel_duzey})</strong>
    <p>{_esc(vk.ozet)}</p>
    {"<ul>" + kalite_uyarilar + "</ul>" if kalite_uyarilar else ""}
    </div>"""

    profil_notlari = ""
    if tahsis.profil_notlari:
        profil_notlari = "<ul>" + "".join(
            f"<li>{_esc(n)}</li>" for n in tahsis.profil_notlari
        ) + "</ul>"

    girdi_html = ""
    girdi_uyar = girdi_rapor_uyarilari(snap)
    if girdi_uyar or getattr(snap, "rejim_donduruldu", False):
        gd = getattr(snap, "girdi_dogrulama", None)
        bekleyen = ", ".join(gd.onay_bekleyen) if gd else "—"
        kutu = ""
        if getattr(snap, "rejim_donduruldu", False):
            kutu = (
                f'<div class="ozet-kutu tl-onerilmiyor"><strong>Girdi sıçraması — rejim donduruldu</strong>'
                f"<p>Onay bekleyen: {_esc(bekleyen)}. Rejim hesabında önceki değer kullanılıyor.</p></div>"
            )
        liste = "".join(f"<li>{_esc(_md_strip(u))}</li>" for u in girdi_uyar)
        girdi_html = f"""
        <h2>Girdi Doğrulama (Faz 1)</h2>
        {kutu}
        <ul>{liste}</ul>"""

    from vergi_notu import vergi_notu_html_blok
    vergi_html = (
        "<h2>2026 Menkul Kıymet Vergi Notu</h2>"
        + vergi_notu_html_blok(esc=_esc)
    )

    rezerv = (
        "Artıyor" if v.rezerv_artiyor
        else "Azalıyor" if v.rezerv_artiyor is False
        else "Bilinmiyor"
    )
    siyasi_pencere = getattr(config, "SIYASI_RISK_TARAMA_SAAT", 24)
    kapi_html = ""
    if tahsis.tl_karar_adimlari:
        kapi_html = (
            "<details><summary><strong>TL Karar Adımları — tüm indirim basamakları (teknik detay)</strong></summary>"
            "<p class='muted'>Her satır bir indirim basamağını gösterir. 'Kapı' basamakları karar motorunun çıktısı; "
            "sonraki satırlar reel getiri ve rejim kısıtlamalarını uygular. "
            "Son satır nihai portföy payını gösterir.</p><ul>"
            + "".join(f"<li>{_esc(a)}</li>" for a in tahsis.tl_karar_adimlari)
            + "</ul></details>"
        )

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8"/>
<title>Yatırım Raporu — {now}</title>
<style>
@page {{ margin: 18mm 15mm; }}
body {{ font-family: Georgia, 'Times New Roman', serif; color: #1a1a1a; line-height: 1.6; font-size: 11pt; max-width: 210mm; margin: 0 auto; padding: 12px; }}
.antet {{ background: linear-gradient(135deg, #003366 0%, #004080 100%); color: #fff; padding: 28px 32px; margin: -12px -12px 28px -12px; }}
.antet h1 {{ margin: 0 0 6px 0; font-size: 22pt; font-weight: 700; letter-spacing: -0.3px; }}
.antet .alt {{ font-size: 12pt; opacity: 0.90; margin: 0 0 4px 0; }}
.antet .meta {{ margin-top: 12px; font-size: 9.5pt; opacity: 0.82; }}
h2 {{ color: #003366; border-bottom: 2px solid #003366; padding-bottom: 5px; margin-top: 30px; font-size: 13.5pt; }}
h3 {{ color: #003366; border-bottom: 1px solid #a0b4cc; padding-bottom: 4px; margin-top: 22px; font-size: 11.5pt; }}
h4 {{ color: #004080; margin: 14px 0 6px 0; font-size: 10.5pt; }}
.ozet-kutu {{ background: #f0f4f8; border-left: 4px solid #003366; padding: 14px 18px; margin: 16px 0; border-radius: 2px; }}
.tl-onerilmiyor {{ border-left-color: #c0392b; background: #fdf2f2; }}
.tl-sinirli {{ border-left-color: #d68910; background: #fef9e7; }}
.tl-cazip, .tl-guclu {{ border-left-color: #1e8449; background: #eafaf1; }}
table {{ width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 10pt; }}
th {{ background: #003366; color: #fff; padding: 10px 12px; text-align: left; font-size: 10pt; font-weight: 600; }}
td {{ border-bottom: 1px solid #dde; padding: 8px 12px; vertical-align: top; }}
tr:nth-child(even) td {{ background: #f8f9fb; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.oneri-al {{ background: #d4edda; color: #155724; padding: 2px 7px; border-radius: 3px; font-weight: 600; font-size: 9.5pt; white-space: nowrap; }}
.oneri-dikkat {{ background: #fff3cd; color: #856404; padding: 2px 7px; border-radius: 3px; font-weight: 600; font-size: 9.5pt; white-space: nowrap; }}
.oneri-alma {{ background: #f8d7da; color: #721c24; padding: 2px 7px; border-radius: 3px; font-weight: 600; font-size: 9.5pt; white-space: nowrap; }}
.oneri-bekle {{ background: #e2e3e5; color: #383d41; padding: 2px 7px; border-radius: 3px; font-weight: 600; font-size: 9.5pt; white-space: nowrap; }}
.box {{ background: #f0f4f8; border: 1px solid #c8d8e8; border-radius: 4px; padding: 12px 16px; margin: 12px 0; }}
.makro-kart, .varlik-kart {{ border: 1px solid #dde; border-radius: 5px; padding: 14px 18px; margin: 10px 0; background: #fafbfc; }}
.muted {{ color: #556; font-size: 9.5pt; }}
details summary {{ cursor: pointer; color: #003366; font-weight: 600; padding: 6px 0; }}
.disclaimer {{ margin-top: 36px; padding-top: 16px; border-top: 1px solid #ccc; font-size: 9pt; color: #666; line-height: 1.5; }}
@media print {{
  body {{ padding: 0; }}
  .antet {{ margin: 0 0 22px 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  details {{ display: block; }}
  details summary {{ display: none; }}
}}
</style>
</head>
<body>
<div class="antet">
    <h1>Yatırım Raporu</h1>
    <p class="alt">Kişisel Portföy Asistanı — Makro Analiz &amp; Hisse Taraması</p>
    <p class="meta">Rapor üretildi: {rapor_uretim_zamani} &nbsp;·&nbsp; Veri güncellemesi: {_esc(snap.veri_zamani)} &nbsp;·&nbsp; Mod: {_esc(snap.veri_kaynak.upper())} &nbsp;·&nbsp; Sürüm: <code style="font-size:0.85em;color:#555">{_git_hash}</code></p>
    <p class="meta">Yatırımcı profili: {_esc(profil.ozet())}</p>
</div>

<!-- 1. BUGÜNKÜ DURUM VE AKSİYONLAR -->
<h2>Bugünkü Durum ve Önerilen Aksiyonlar</h2>
<div class="ozet-kutu">
    <p><strong>Piyasa rejimi:</strong> {_esc(tahsis.rejim.etiket)} — {_esc(tahsis.rejim.aciklama)}</p>
    <p>{_esc(_md_strip(danisman.genel_ozet))}</p>
    {"<p>" + _esc(_md_strip(danisman.rejim_yorumu)[:600]) + "</p>" if getattr(danisman, "rejim_yorumu", "") else ""}
</div>
{_backtest_ozet_uyari}
{profil_notlari}
{girdi_html}

<!-- 2. ÖNERİLEN PORTFÖY DAĞILIMI -->
<h2>Önerilen Portföy Dağılımı</h2>
<p>Toplam portföy: <strong>{toplam_eur:,.0f} EUR</strong> &nbsp;·&nbsp; Yatırım vadesi: <strong>{_esc(vade_metin)}</strong> &nbsp;·&nbsp; TL maksimum pay: <strong>%{tahsis.tl_tavan_oran * 100:.1f}</strong></p>
<table>
    <thead><tr><th>Varlık Sınıfı</th><th>Portföyden Pay</th><th>Tutar (EUR)</th></tr></thead>
    <tbody>{tahsis_rows}</tbody>
</table>
<p class="muted">{_esc(tahsis.tavsiye_metni)}</p>

{birlesik_html}

{tefas_html}

<!-- 3. HİSSE & ETF YATIRIM ÖNERİLERİ -->
{tarama_html}

<!-- 4. VARLIKLARIM POZİSYONLARI -->
{varlik_html}

<!-- 5. TL MEVDUAT DEĞERLENDİRMESİ -->
{tl_html}

{mevduat_html}

<!-- 5b. VERGİ NOTU -->
{vergi_html}

<!-- 6. MAKRO VERİLER -->
<h2>Makro Göstergeler</h2>
<table>
    <tr><td>EUR/TRY</td><td class="num">{_fmt_num(v.eur_try)}</td>
        <td>USD/TRY</td><td class="num">{_fmt_num(v.usd_try)}</td></tr>
    <tr><td>TCMB Faizi</td><td class="num">%{_fmt_num(v.tcmb_politika_faizi, 1)}</td>
        <td>Fed Faizi (ABD)</td><td class="num">%{_fmt_num(v.fed_faizi, 2)}</td></tr>
    <tr><td>Enflasyon (TR)</td><td class="num">%{_fmt_num(snap.enflasyon_tr_yillik, 1)}</td>
        <td>BIST 100</td><td class="num">{_fmt_num(snap.bist100, 0)}</td></tr>
    <tr><td>Altın (USD/oz)</td><td class="num">${_fmt_num(snap.altin_usd_oz, 0)}</td>
        <td>BTC (USD)</td><td class="num">${_fmt_num(snap.btc_usd, 0)}</td></tr>
    <tr><td>Ülke riski (CDS 5Y)</td><td class="num">{_fmt_num(v.cds_5y_bp, 0)} bp</td>
        <td>ABD Korku Endeksi (VIX)</td><td class="num">{_fmt_num(snap.vix, 1)}</td></tr>
    <tr>
        <td>Siyasi risk haberleri <span class="muted">(son {siyasi_pencere}s)</span></td>
        <td class="num">{_esc(v.siyasi_risk_makale_sayisi) if v.siyasi_risk_makale_sayisi is not None else "—"} haber</td>
        <td>Jeopolitik risk haberleri <span class="muted">(son 48s)</span></td>
        <td class="num">{(_esc(v.savas_risk_makale_sayisi) if v.savas_risk_guvenilir is not False else "Güvenilmez") if v.savas_risk_makale_sayisi is not None else "—"} haber</td>
    </tr>
    <tr><td>Döviz rezervleri</td><td class="num">{rezerv}</td>
        <td>TL maksimum pay</td><td class="num">%{_fmt_num(tahsis.tl_tavan_oran * 100, 0)}</td></tr>
</table>
<p class="muted">Siyasi ve jeopolitik haber sayıları farklı anahtar kelime setleriyle farklı kaynaklardan taranır.
Her iki sayı da aynı {siyasi_pencere} saatlik pencerededir; aralarındaki fark zaman değil,
duygu analizi ağırlıklandırmasından (negatif duygu sayıyı artırır) ve farklı sorgu konularından kaynaklanır.</p>

<!-- 7. MAKRO DEĞERLENDİRME -->
<h2>Makro Piyasa Değerlendirmesi</h2>
{makro_satirlar or '<p class="muted">Makro bağlam verisi yok.</p>'}

<!-- 8. VARLIK STRATEJİ NOTLARI -->
<h2>Varlık Bazlı Strateji Notları</h2>
{varlik_kartlari}

<!-- 9. TEKNİK EKLER -->
{denetim_html}

{backtest_html}

{kapi_html}

<details>
<summary><strong>Algoritma Adımları (teknik detay)</strong></summary>
<ul>{"".join(f"<li>{_esc(a)}</li>" for a in tahsis.adimlar[:20])}</ul>
</details>

<details>
<summary><strong>Veri Kalitesi &amp; Kaynak Şeffaflığı</strong></summary>
{kalite_blok}
<table>
    <thead><tr><th>Gösterge</th><th>Değer</th><th>Kalite</th><th>Kaynak</th><th>Yaş</th></tr></thead>
    <tbody>{kaynak_rows}</tbody>
</table>
</details>

<div class="disclaimer">
    <p><strong>Yasal uyarı:</strong> Bu rapor otomatik üretilmiş bir karar-destek belgesidir.
    Yatırım tavsiyesi niteliği taşımaz. Nihai yatırım kararı yatırımcıya aittir.
    Geçmiş performans gelecek getirileri garanti etmez.
    Menkul kıymet vergi özeti bilgi amaçlıdır; hisse/ETF/TEFAS getirileri brüt gösterilir,
    yalnızca mevduat satırlarında stopaj düşülmüş net % kullanılır.</p>
    <p>© {datetime.now().year} Kişisel Portföy Asistanı</p>
</div>
</body>
</html>"""


def rapor_paketi_olustur(
    snap: MacroSnapshot,
    tahsis: TahsisSonucu,
    profil: YatirimProfili,
    danisman: DanismanRaporu,
    mevduat: Optional[MevduatKarsilastirma] = None,
    tl_durum: Optional[TlDurumOzeti] = None,
    toplam_eur: float = None,
    tarama: Optional[TaramaSonucu] = None,
    tl_mevduat_tutar_tl: Optional[float] = None,
    birlesik_oneri=None,
    varlik_store=None,
    kullanici_portfoy=None,
    para_birimi: str = "EUR",
    tefas_ham=None,
) -> dict:
    html_out = rapor_html_olustur(
        snap, tahsis, profil, danisman, mevduat, tl_durum, toplam_eur, tarama,
        tl_mevduat_tutar_tl=tl_mevduat_tutar_tl,
        birlesik_oneri=birlesik_oneri,
        varlik_store=varlik_store,
        kullanici_portfoy=kullanici_portfoy,
        para_birimi=para_birimi,
        tefas_ham=tefas_ham,
    )
    pdf_out = rapor_pdf_direkt_olustur(
        snap, tahsis, profil, danisman, mevduat, tl_durum, toplam_eur, tarama,
        tl_mevduat_tutar_tl=tl_mevduat_tutar_tl,
        birlesik_oneri=birlesik_oneri,
        varlik_store=varlik_store,
        kullanici_portfoy=kullanici_portfoy,
        para_birimi=para_birimi,
        tefas_ham=tefas_ham,
    )
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    return {
        "html": html_out,
        "pdf": pdf_out,
        "html_dosya": f"anlik_yatirim_raporu_{ts}.html",
        "pdf_dosya": f"anlik_yatirim_raporu_{ts}.pdf",
    }
