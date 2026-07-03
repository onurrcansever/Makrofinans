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
from rates_tr import MevduatKarsilastirma, _eur_bazli_tahmini
from stock_scanner import SINYAL_ETIKET, TaramaSonucu
from tl_durum import TlDurumOzeti
from veri_kalitesi import veri_kalite_olustur
from backtest import backtest_calistir, backtest_metrikleri
from alim_uygunluk import alim_aksiyon_hucre
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
        ("BIST 100", "bist100"), ("BTC", "btc"), ("VIX", "vix"),
        ("CDS 5Y", "cds"), ("Enflasyon TR", "enflasyon"), ("TL mevduat", "tl_mevduat"),
        ("Fed faizi", "fed_faizi"), ("TCMB faizi", "tcmb_faizi"),
        ("Siyasi risk", "siyasi_risk"), ("Rezerv", "rezerv"),
    ]
    return [(a, kh.get(b, "—")) for a, b in etiketler]


def _md_strip(text: str) -> str:
    return text.replace("**", "").replace("*", "")


_UYGUN_SIRA = {"UYGUN": 0, "SINIRLI": 1, "IZLE": 2, "UYGUN_DEGIL": 3}


def _uygun_tablo_hucre(h) -> str:
    return alim_aksiyon_hucre(h)


def _hisse_sirala_html(hisseler: list) -> list:
    return sorted(
        hisseler,
        key=lambda h: (_UYGUN_SIRA.get(getattr(h, "alim_uygun", "IZLE"), 9), -h.skor),
    )


def _skor_sirala_html(hisseler: list) -> list:
    return sorted(hisseler, key=lambda h: -h.skor)


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
        f"AL: {say['UYGUN']} · DİKKAT: {say['SINIRLI']} · "
        f"ALMA: {say['UYGUN_DEGIL']} · BEKLE: {say['IZLE']}"
    )


def _hisse_tablo_html(hisseler: list, *, detayli: bool = False, ilk_sutun: str = "uygunluk") -> str:
    if not hisseler:
        return ""
    ilk_baslik = "Skor Sırası" if ilk_sutun == "sira" else "Karar"
    heads = [
        ilk_baslik, "Sembol", "Hisse", "Piyasa", "Sinyal", "Skor",
        "1A", "3A", "RSI", "52H", "Peer", "End.", "SMA200",
    ]
    if detayli:
        heads.append("Not")
    num_cols = {5, 6, 7, 8, 9, 10, 11, 12}
    thead = "".join(f"<th>{_esc(h)}</th>" for h in heads)
    rows = ""
    for i, h in enumerate(hisseler):
        peer = getattr(h, "peer_yuzdelik", None)
        endeks = getattr(h, "endeks_gore", None)
        z52 = getattr(h, "zirve_52h_pct", None)
        col0 = f"#{i + 1}" if ilk_sutun == "sira" else _esc(_uygun_tablo_hucre(h))
        cells = [
            col0,
            _esc(h.sembol),
            _esc(h.ad),
            _esc(h.piyasa),
            _esc(SINYAL_ETIKET.get(h.sinyal, h.sinyal)),
            f"{h.skor:.0f}",
            _pct_html(h.degisim_1ay, 0),
            _pct_html(getattr(h, "degisim_3ay", None), 0),
            f"{h.rsi:.0f}" if h.rsi is not None else "—",
            f"{z52:.0f}" if z52 is not None else "—",
            f"{peer:.0f}" if peer is not None else "—",
            f"{endeks:+.0f}" if endeks is not None else "—",
            _fmt_num(getattr(h, "sma200", None), 0) if getattr(h, "sma200", None) else "—",
        ]
        if detayli:
            cells.append(_esc(getattr(h, "alim_uygun_not", "") or getattr(h, "trend_notu", "")))
        tds = ""
        for j, c in enumerate(cells):
            cls = ' class="num"' if j in num_cols else ""
            tds += f"<td{cls}>{c}</td>"
        rows += f"<tr>{tds}</tr>"
    return f"<table><thead><tr>{thead}</tr></thead><tbody>{rows}</tbody></table>"


def _hisse_detay_li(h) -> str:
    rsi = f"{h.rsi:.0f}" if h.rsi is not None else "—"
    z52 = getattr(h, "zirve_52h_pct", None)
    z52_txt = f"{z52:.0f}" if z52 is not None else "—"
    ek = ""
    if getattr(h, "alim_uygun_not", ""):
        ek += f" [{_esc(h.alim_uygun_not)}]"
    if getattr(h, "trend_notu", "") and h.trend_notu not in ("", "Trend filtresi OK"):
        ek += f" Trend: {_esc(h.trend_notu)}."
    if getattr(h, "faktor_notu", "") and h.faktor_notu not in ("", "Faktör nötr"):
        ek += f" Faktör: {_esc(h.faktor_notu)}."
    if getattr(h, "profil_notu", "") and h.profil_notu != "Profil uyumlu":
        ek += f" Profil: {_esc(h.profil_notu)}."
    peer = getattr(h, "peer_yuzdelik", None)
    endeks = getattr(h, "endeks_gore", None)
    if peer is not None:
        ek += f" Peer %{peer:.0f}"
    if endeks is not None:
        ek += f" · Endeks {endeks:+.0f}pp 3A"
    sma = _fmt_num(getattr(h, "sma200", None), 0) if getattr(h, "sma200", None) else "—"
    return (
        f"<li>{_esc(_uygun_tablo_hucre(h))} · {_esc(h.ad)} ({_esc(h.sembol)}) · "
        f"{_esc(SINYAL_ETIKET.get(h.sinyal, h.sinyal))} · RSI {rsi} · skor {h.skor:.0f} · "
        f"1A {_pct_html(h.degisim_1ay)} · 3A {_pct_html(getattr(h, 'degisim_3ay', None))} · "
        f"52H %{z52_txt} · SMA200 {sma}{ek}</li>"
    )


def _backtest_html(rejim: str, ay: int = 12) -> str:
    try:
        satirlar = backtest_calistir(ay)
        met = backtest_metrikleri(satirlar, rejim)
    except Exception:
        return ""
    if not met:
        return ""
    sharpe = f"{met.sharpe_yillik:.2f}" if met.sharpe_yillik is not None else "—"
    drift = f"<p class='warn'>{_esc(met.drift_mesaji)}</p>" if met.model_drift else (
        f"<p class='muted'>Mevcut rejim ({_esc(rejim)}) backtest döneminde "
        f"%{met.mevcut_rejim_oran_pct:.0f} süre görüldü — drift yok.</p>"
    )
    notlar = "".join(f"<li>{_esc(n)}</li>" for n in met.notlar[:3])
    tablo = ""
    if satirlar:
        tr = ""
        for s in satirlar[-6:]:
            tr += (
                f"<tr><td>{_esc(s.tarih)}</td><td>{_esc(s.rejim_etiket)}</td>"
                f"<td class='num'>{_fmt_num(s.eur_try, 1)}</td>"
                f"<td class='num'>{s.agirliklar.get('gold', 0) * 100:.0f}%</td>"
                f"<td class='num'>{s.agirliklar.get('tl_deposit', 0) * 100:.0f}%</td>"
                f"<td class='num'>{s.agirliklar.get('bist', 0) * 100:.0f}%</td></tr>"
            )
        tablo = f"""
        <table>
            <thead><tr><th>Ay</th><th>Rejim</th><th>EUR/TRY</th><th>Altın</th><th>TL</th><th>BIST</th></tr></thead>
            <tbody>{tr}</tbody>
        </table>"""
    return f"""
    <h2>Backtest & Model İstikrarı</h2>
    <div class="box"><strong>Son {ay} ay simülasyon · Sharpe {sharpe}</strong>
    <p>Toplam getiri {met.toplam_getiri_pct:+.1f}% · Max drawdown {met.max_drawdown_pct:.1f}% ·
    Volatilite (yıllık) {met.volatilite_yillik_pct:.1f}% · Rejim değişimi {met.rejim_degisim_sayisi} ·
    En sık rejim: {_esc(met.en_sik_rejim.replace('_', ' '))}</p></div>
    {drift}
    <ul>{notlar}</ul>
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
) -> str:
    toplam_eur = toplam_eur or config.TOPLAM_EUR
    v = snap.veri
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
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
            <td class="num">{tahsis.skorlar.get(k, 0):.0f}</td>
        </tr>"""

    varlik_kartlari = ""
    for var in danisman.varliklar:
        nedenler = "".join(f"<li>{_esc(_md_strip(n))}</li>" for n in var.nedenler[:5])
        dikkat = "".join(f"<li>{_esc(_md_strip(d))}</li>" for d in var.dikkat[:3])
        varlik_kartlari += f"""
        <div class="varlik-kart">
            <h4>{_esc(var.ad)} — {_esc(var.sinyal_etiket)} ({_esc(var.ok)})</h4>
            <p><strong>Ağırlık:</strong> %{var.agirlik_pct:.1f} · <strong>Güven:</strong> {var.guven}/100</p>
            <p>{_esc(_md_strip(var.baslik))}</p>
            <ul>{nedenler}</ul>
            {"<p><strong>Dikkat:</strong></p><ul>" + dikkat + "</ul>" if dikkat else ""}
        </div>"""

    mevduat_html = ""
    if mevduat:
        mev_rows = ""
        for o in mevduat.oranlar:
            isaret = " ✓" if o.vade == mevduat.profil_vade else ""
            net_pct = o.net_yillik * 100
            eur_tah = (
                f"{_eur_bazli_tahmini(net_pct, mevduat.enflasyon):+.1f}"
                if o.vade.startswith("TL") else "—"
            )
            mev_rows += f"""
            <tr>
                <td>{_esc(o.vade)}{isaret}</td>
                <td class="num">%{o.brut_yillik * 100:.2f}</td>
                <td class="num">%{net_pct:.2f}</td>
                <td class="num">{o.reel_yillik or 0:+.1f}</td>
                <td class="num">{eur_tah}</td>
            </tr>"""
        getiri_kutu = ""
        if mevduat.getiri_notu:
            getiri_kutu = f'<div class="ozet-kutu"><strong>Getiri tanımı:</strong> {_esc(mevduat.getiri_notu)}</div>'
        mevduat_html = f"""
        <h2>TL Mevduat & Faiz Karşılaştırması</h2>
        <p>{_esc(mevduat.ozet)}</p>
        {getiri_kutu}
        <p class="muted">Veri: {_esc(mevduat.veri_kaynagi)} · Profil vadesi: {_esc(mevduat.profil_vade)}</p>
        <table>
            <thead><tr><th>Vade</th><th>Brüt %</th><th>Net %</th><th>Yerel reel</th><th>EUR tah.</th></tr></thead>
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
        endeks_rows = ""
        for e in tarama.endeksler:
            d1 = f"{e.degisim_1g:+.1f}%" if e.degisim_1g is not None else "—"
            d1a = f"{e.degisim_1ay:+.1f}%" if e.degisim_1ay is not None else "—"
            d3a = f"{e.degisim_3ay:+.1f}%" if e.degisim_3ay is not None else "—"
            rsi = f"{e.rsi:.0f}" if e.rsi is not None else "—"
            endeks_rows += f"""
            <tr>
                <td>{_esc(e.ad)}</td>
                <td class="num">{_fmt_num(e.fiyat, 0 if (e.fiyat or 0) >= 100 else 2)}</td>
                <td class="num">{d1}</td>
                <td class="num">{d1a}</td>
                <td class="num">{d3a}</td>
                <td class="num">{rsi}</td>
                <td>{_esc(SINYAL_ETIKET.get(e.sinyal, e.sinyal))}</td>
                <td class="num">{e.skor:.0f}</td>
            </tr>"""

        uygun_list = _hisse_sirala_html([
            h for h in (tarama.hisseler or []) if getattr(h, "alim_uygun", "") == "UYGUN"
        ])
        uygun_blok = ""
        if uygun_list:
            detay = "".join(_hisse_detay_li(h) for h in uygun_list[:8])
            uygun_blok = f"""
            <h3>AL — {len(uygun_list)} varlık</h3>
            {_hisse_tablo_html(uygun_list, detayli=True)}
            <ul>{detay}</ul>"""

        sinirli_list = _hisse_sirala_html([
            h for h in (tarama.hisseler or []) if getattr(h, "alim_uygun", "") == "SINIRLI"
        ])
        sinirli_blok = ""
        if sinirli_list:
            detay = "".join(_hisse_detay_li(h) for h in sinirli_list[:6])
            sinirli_blok = f"""
            <h3>DİKKAT — sınırlı uygun — {len(sinirli_list)} varlık</h3>
            {_hisse_tablo_html(sinirli_list[:15], detayli=True)}
            <ul>{detay}</ul>"""

        if tarama.alim_firsatlari:
            firsat_html = f"""
            <h3>Alım adayları (profil filtreli) — {len(tarama.alim_firsatlari)} varlık</h3>
            {_hisse_tablo_html(_hisse_sirala_html(tarama.alim_firsatlari[:20]), detayli=True)}
            <ul>{"".join(_hisse_detay_li(h) for h in tarama.alim_firsatlari[:8])}</ul>"""
        else:
            firsat_html = (
                "<p class='muted'>Profil filtreli alım adayı yok — BEKLE veya makro tahsis öncelikli.</p>"
            )

        etf_firsat = getattr(tarama, "etf_firsatlari", None) or []
        etf_blok = ""
        if etf_firsat:
            etf_rows = ""
            for h in _hisse_sirala_html(etf_firsat[:12]):
                rt = getattr(h, "revolut_ticker", "") or h.sembol.split(".")[0]
                z52 = getattr(h, "zirve_52h_pct", None)
                etf_rows += f"""
                <tr>
                    <td>{_esc(_uygun_tablo_hucre(h))}</td>
                    <td>{_esc(rt)}</td>
                    <td>{_esc(h.ad)}</td>
                    <td>{_esc(SINYAL_ETIKET.get(h.sinyal, h.sinyal))}</td>
                    <td class="num">{h.skor:.0f}</td>
                    <td class="num">{_pct_html(h.degisim_1ay, 0)}</td>
                    <td class="num">{f"{h.rsi:.0f}" if h.rsi is not None else "—"}</td>
                    <td class="num">{f"{z52:.0f}" if z52 is not None else "—"}</td>
                    <td>{_esc(getattr(h, 'isin', '') or '—')}</td>
                    <td>{_esc(getattr(h, 'alim_uygun_not', ''))}</td>
                </tr>"""
            etf_blok = f"""
            <h3>Revolut ETF adayları — {len(etf_firsat)} fon</h3>
            <table>
                <thead><tr><th>Karar</th><th>Revolut</th><th>ETF</th><th>Sinyal</th><th>Skor</th>
                <th>1A</th><th>RSI</th><th>52H</th><th>ISIN</th><th>Not</th></tr></thead>
                <tbody>{etf_rows}</tbody>
            </table>
            <ul>{"".join(_hisse_detay_li(h) for h in etf_firsat[:6])}</ul>"""

        onemli = _hisse_sirala_html([
            h for h in (tarama.hisseler or [])
            if getattr(h, "alim_uygun", "") in ("UYGUN", "SINIRLI")
            or h.sinyal in ("ALIM_FIRSATI", "TREND_ALIM")
        ])[:35]
        teknik_blok = ""
        if onemli:
            teknik_blok = f"""
            <h3>Teknik özet — öncelikli {len(onemli)} varlık (skor sıralı, bilgi amaçlı)</h3>
            {_hisse_tablo_html(onemli, detayli=False, ilk_sutun="sira")}"""

        piyasa_html = ""
        piyasa_html += (
            "<p class='muted'>Bilgi amaçlı en yüksek skorlu 6 varlık — "
            "alım kararı için yalnızca üstteki Alım uygunluk bölümüne bakın.</p>"
        )
        for piyasa in ("BIST", "SP500", "NASDAQ", "ETF"):
            grup = _skor_sirala_html([
                h for h in (tarama.hisseler or [])
                if h.piyasa == piyasa and h.sinyal not in ("ASIRI_ALIM", "UZAK_DUR", "VERI_YOK")
            ])[:6]
            if not grup:
                continue
            piyasa_html += f"""
            <h4>{piyasa} — top 6 (skor sıralı)</h4>
            {_hisse_tablo_html(grup, detayli=True, ilk_sutun="sira")}"""

        uyarilar = "".join(f"<li>{_esc(u)}</li>" for u in (tarama.uyarilar or [])[:3])
        profil_blok = ""
        if getattr(tarama, "profil_ozet", ""):
            profil_not = "".join(
                f"<li>{_esc(n)}</li>" for n in (getattr(tarama, "profil_notlari", None) or [])[:5]
            )
            profil_blok = f"""
        <div class="box"><strong>Yatırımcı profili (tarama filtresi):</strong> {_esc(tarama.profil_ozet)}
        <ul>{profil_not}</ul></div>"""
        ozet = getattr(tarama, "tarama_ozet", "") or ""
        tarama_html = f"""
        <h2>Hisse & Endeks Taraması</h2>
        <p class="muted">Karar: AL = al · DİKKAT = küçük pay/uyarı · ALMA = alma · BEKLE = izle.
        Yahoo (gecikmeli) · RSI + SMA20/50/200 · Rejim: {_esc(tahsis.rejim.etiket)}.
        Katmanlar: teknik → trend → rejim → profil → faktör/peer → haber.</p>
        {profil_blok}
        <div class="box"><strong>Alım uygunluk özeti:</strong> {_esc(_uygunluk_ozet_html(tarama))}</div>
        <p class="muted">{_esc(ozet)}</p>
        {"<ul>" + uyarilar + "</ul>" if uyarilar else ""}
        <h3>Endeksler — BIST 100 · NASDAQ · S&P 500</h3>
        <table>
            <thead><tr><th>Endeks</th><th>Fiyat</th><th>1 Gün</th><th>1 Ay</th><th>3 Ay</th><th>RSI</th><th>Sinyal</th><th>Skor</th></tr></thead>
            <tbody>{endeks_rows}</tbody>
        </table>
        {uygun_blok}
        {sinirli_blok}
        {firsat_html}
        {etf_blok}
        {teknik_blok}
        <h3>Piyasa bazında öne çıkanlar</h3>
        {piyasa_html}"""

    backtest_html = _backtest_html(tahsis.rejim.rejim)

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

    rezerv = (
        "Artıyor" if v.rezerv_artiyor
        else "Azalıyor" if v.rezerv_artiyor is False
        else "Bilinmiyor (Kapı 4 ×0,85)"
    )
    kapi_html = ""
    if tahsis.tl_karar_adimlari:
        kapi_html = "<h2>4 Kapı Özeti (TL tavan)</h2><ul>" + "".join(
            f"<li>{_esc(a)}</li>" for a in tahsis.tl_karar_adimlari[:6]
        ) + "</ul>"

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8"/>
<title>Anlık Durum Yatırım Raporu — {now}</title>
<style>
@page {{ margin: 18mm 15mm; }}
body {{ font-family: Georgia, 'Times New Roman', serif; color: #1a1a1a; line-height: 1.55; font-size: 11pt; max-width: 210mm; margin: 0 auto; padding: 12px; }}
.antet {{ background: linear-gradient(135deg, #003366 0%, #004080 100%); color: #fff; padding: 28px 32px; margin: -12px -12px 24px -12px; }}
.antet h1 {{ margin: 0 0 6px 0; font-size: 22pt; font-weight: 700; }}
.antet .alt {{ font-size: 13pt; opacity: 0.92; margin: 0; }}
.antet .meta {{ margin-top: 14px; font-size: 10pt; opacity: 0.85; }}
h2 {{ color: #003366; border-bottom: 2px solid #003366; padding-bottom: 6px; margin-top: 28px; font-size: 14pt; }}
h4 {{ color: #004080; margin: 12px 0 6px 0; font-size: 11pt; }}
.ozet-kutu {{ background: #f0f4f8; border-left: 4px solid #003366; padding: 14px 18px; margin: 16px 0; }}
.tl-onerilmiyor {{ border-left-color: #c0392b; background: #fdf2f2; }}
.tl-sinirli {{ border-left-color: #d68910; background: #fef9e7; }}
.tl-cazip, .tl-guclu {{ border-left-color: #1e8449; background: #eafaf1; }}
table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 10pt; }}
th {{ background: #003366; color: #fff; padding: 8px 10px; text-align: left; }}
td {{ border-bottom: 1px solid #ddd; padding: 7px 10px; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.makro-kart, .varlik-kart {{ border: 1px solid #dde; border-radius: 6px; padding: 12px 16px; margin: 10px 0; background: #fafbfc; }}
.muted {{ color: #555; font-size: 9.5pt; }}
.disclaimer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid #ccc; font-size: 9pt; color: #666; }}
@media print {{ body {{ padding: 0; }} .antet {{ margin: 0 0 20px 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }} }}
</style>
</head>
<body>
<div class="antet">
    <h1>Anlık Durum Yatırım Raporu</h1>
    <p class="alt">Makro Portföy Asistanı · Haber Araştırma & Strateji Özeti</p>
    <p class="meta">Rapor tarihi: {now} · Veri çekimi: {_esc(snap.veri_zamani)} · Mod: {_esc(snap.veri_kaynak.upper())}</p>
    <p class="meta">Yatırımcı profili: {_esc(profil.ozet())}</p>
</div>

<h2>Yönetici Özeti</h2>
<div class="ozet-kutu">
    <p><strong>Makro rejim:</strong> {_esc(tahsis.rejim.etiket)} — {_esc(tahsis.rejim.aciklama)}</p>
    <p>{_esc(_md_strip(danisman.genel_ozet))}</p>
    <p>{_esc(_md_strip(danisman.rejim_yorumu)[:600])}</p>
</div>
{profil_notlari}

<h2>Piyasa Verileri (Canlı)</h2>
<table>
    <tr><td>EUR/TRY</td><td class="num">{_fmt_num(v.eur_try)}</td>
        <td>USD/TRY</td><td class="num">{_fmt_num(v.usd_try)}</td></tr>
    <tr><td>CDS 5Y</td><td class="num">{_fmt_num(v.cds_5y_bp, 0)} bp</td>
        <td>VIX</td><td class="num">{_fmt_num(snap.vix, 1)}</td></tr>
    <tr><td>TCMB faizi</td><td class="num">%{_fmt_num(v.tcmb_politika_faizi, 1)}</td>
        <td>Enflasyon TR</td><td class="num">%{_fmt_num(snap.enflasyon_tr_yillik, 1)}</td></tr>
    <tr><td>Fed faizi</td><td class="num">%{_fmt_num(v.fed_faizi, 2)}</td>
        <td>Altın USD/oz</td><td class="num">${_fmt_num(snap.altin_usd_oz, 0)}</td></tr>
    <tr><td>BIST 100</td><td class="num">{_fmt_num(snap.bist100, 0)}</td>
        <td>BTC USD</td><td class="num">${_fmt_num(snap.btc_usd, 0)}</td></tr>
    <tr><td>Siyasi risk (48s)</td><td class="num">{_esc(v.siyasi_risk_makale_sayisi)} haber (ağırlıksız)</td>
        <td>Jeopolitik (48s)</td><td class="num">{_esc(v.savas_risk_makale_sayisi)} haber</td></tr>
    <tr><td>Rezerv (Kapı 4)</td><td class="num">{rezerv}</td>
        <td>TL tavan</td><td class="num">%{_fmt_num(tahsis.tl_tavan_oran * 100, 0)}</td></tr>
</table>

{kapi_html}

{tl_html}

<h2>Önerilen Portföy Dağılımı</h2>
<p>Toplam portföy: <strong>{toplam_eur:,.0f} EUR</strong> · Yatırım vadesi: <strong>{_esc(vade_metin)}</strong> · TL tavan: <strong>%{tahsis.tl_tavan_oran * 100:.1f}</strong></p>
<table>
    <thead><tr><th>Varlık</th><th>Ağırlık</th><th>Tutar</th><th>Skor</th></tr></thead>
    <tbody>{tahsis_rows}</tbody>
</table>
<p class="muted">{_esc(tahsis.tavsiye_metni)}</p>

<h2>Canlı Makro Değerlendirme</h2>
{makro_satirlar or '<p class="muted">Makro bağlam verisi yok.</p>'}

{mevduat_html}

{tarama_html}

{backtest_html}

<h2>Varlık Bazlı Strateji Notları</h2>
{varlik_kartlari}

{denetim_html}

<h2>Algoritma Adımları</h2>
<ul>{"".join(f"<li>{_esc(a)}</li>" for a in tahsis.adimlar[:20])}</ul>

<h2>Veri Kalitesi & Kaynak Şeffaflığı</h2>
{kalite_blok}
<table>
    <thead><tr><th>Gösterge</th><th>Değer</th><th>Kalite</th><th>Kaynak</th><th>Yaş</th></tr></thead>
    <tbody>{kaynak_rows}</tbody>
</table>

<div class="disclaimer">
    <p><strong>Yasal uyarı:</strong> Bu rapor Makro Portföy Asistanı tarafından otomatik üretilmiş
    kural tabanlı bir karar-destek belgesidir. Yatırım tavsiyesi niteliği taşımaz.
    Nihai yatırım kararı yatırımcıya aittir.</p>
    <p>© {datetime.now().year} Makro Portföy Asistanı</p>
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
) -> dict:
    html_out = rapor_html_olustur(
        snap, tahsis, profil, danisman, mevduat, tl_durum, toplam_eur, tarama,
    )
    pdf_out = rapor_pdf_direkt_olustur(
        snap, tahsis, profil, danisman, mevduat, tl_durum, toplam_eur, tarama,
    )
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    return {
        "html": html_out,
        "pdf": pdf_out,
        "html_dosya": f"anlik_yatirim_raporu_{ts}.html",
        "pdf_dosya": f"anlik_yatirim_raporu_{ts}.pdf",
    }
