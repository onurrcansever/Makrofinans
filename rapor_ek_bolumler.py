# -*- coding: utf-8 -*-
"""PDF/HTML rapor — birleşik öneri ve Varlıklarım bölümleri."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from birlesik_oneri import BirlesikOneri
from kullanici_portfoy import KullaniciPortfoy
from macro_data import MacroSnapshot
from varlik_fiyat import portfoy_degerle
from varliklarim import TUR_SECENEKLERI, VarlikStore

if TYPE_CHECKING:
    from report_pdf import RaporPDF


def _temiz_pdf(text, max_len=0):
    from report_pdf import _temiz
    return _temiz(text, max_len)


def _fmt_getiri(v) -> str:
    if v is None:
        return "—"
    return f"{v:+.2f}%"


def _sidebar_hedef(kp: KullaniciPortfoy, pb: str, snap: MacroSnapshot) -> float:
    eur_try = snap.veri.eur_try or 35.0
    usd_try = snap.veri.usd_try or eur_try * 1.08
    hedef_tl = kp.toplam_tl(eur_try)
    if pb == "TL":
        return hedef_tl
    if pb == "EUR":
        return hedef_tl / eur_try if eur_try > 0 else kp.toplam
    return hedef_tl / usd_try if usd_try > 0 else hedef_tl


def birlesik_oneri_pdf_bolumu(
    doc: "RaporPDF",
    oneri: Optional[BirlesikOneri],
    *,
    para_birimi: str,
    toplam_eur: float,
    eur_try: float,
) -> None:
    if not oneri:
        return

    pb_toplam = toplam_eur * eur_try if para_birimi == "TL" else toplam_eur
    doc.bolum("Önerilen Portföy — Detaylı Hedef")
    doc.paragraf(
        f"Sidebar toplam: {_temiz_pdf(f'{pb_toplam:,.0f} {para_birimi}')} · "
        f"EUR referans: {_temiz_pdf(f'{toplam_eur:,.0f} EUR')} · "
        f"{_temiz_pdf(oneri.ozet, 120)}"
    )
    for n in oneri.mevcut_notlar[:4]:
        doc.madde(_temiz_pdf(n, 200))

    if oneri.hedef_tablo:
        w = doc._w()
        rows = [
            [
                _temiz_pdf(h.kategori, 22),
                _temiz_pdf(h.arac, 48),
                f"%{h.agirlik_pct:.1f}",
                f"{h.tutar:,.0f} {h.para}",
            ]
            for h in oneri.hedef_tablo
        ]
        doc.tablo(
            ["Varlık sınıfı", "Özet", "Portföy %", "Tutar"],
            rows,
            col_w=[w * 0.26, w * 0.40, w * 0.12, w * 0.22],
            font_boyut=7.5,
        )

    if oneri.arac_dagilim:
        doc.bolum("Araç İçi Dağılım (TEFAS / ETF / BIST)")
        doc.paragraf(
            "TEFAS ve ETF tutarları ilgili TL/EUR nakit payının içinden ayrılır; "
            "Varlıklarım'a aktarımda çift sayım yapılmaz."
        )
        w = doc._w()
        rows = [
            [
                _temiz_pdf(s.ust_kategori, 16),
                _temiz_pdf(s.arac, 10),
                _temiz_pdf(s.aciklama, 28),
                f"{s.portfoy_pct:.2f}%",
                f"{s.kategori_ici_pct:.1f}%",
                f"{s.tutar:,.0f} {s.para}",
                _temiz_pdf(s.etiket, 8),
            ]
            for s in oneri.arac_dagilim
        ]
        doc.tablo(
            ["Kategori", "Kod", "Açıklama", "Portföy %", "İç %", "Tutar", "Etiket"],
            rows,
            col_w=[w * 0.14, w * 0.07, w * 0.24, w * 0.10, w * 0.08, w * 0.22, w * 0.08],
            font_boyut=7,
            satir_yuk=3.8,
        )


def varliklarim_pdf_bolumu(
    doc: "RaporPDF",
    store: Optional[VarlikStore],
    snap: MacroSnapshot,
    kp: KullaniciPortfoy,
) -> None:
    doc.bolum("Varlıklarım — Portföy Takibi")
    if not store:
        doc.paragraf("Varlıklarım kaydı bulunamadı.")
        return

    aktif = store.aktif()
    if not aktif:
        doc.paragraf("Aktif portföy seçilmemiş.")
        return

    pb = store.goruntuleme_pb or kp.para_birimi
    if not aktif.pozisyonlar:
        doc.paragraf(
            f"{aktif.ad} portföyünde pozisyon yok. "
            "Portföy Tahsisi'nden öneriyi aktararak takibe başlayabilirsiniz."
        )
        return

    deger = portfoy_degerle(aktif, snap)
    toplam = deger.toplam.get(pb, 0)
    maliyet = deger.maliyet_toplam.get(pb, 0)
    kz = toplam - maliyet
    kz_pct = (kz / maliyet * 100) if maliyet > 0 else 0.0
    hedef = _sidebar_hedef(kp, pb, snap)

    doc.kutu(
        f"{aktif.ad} · {pb} görünüm",
        f"Toplam: {toplam:,.0f} {pb} · Maliyet: {maliyet:,.0f} {pb} · "
        f"K/Z: {kz:+,.0f} ({kz_pct:+.2f}%) · "
        f"Sidebar hedef: {hedef:,.0f} {pb}",
    )
    if hedef > 0 and abs(toplam - hedef) / hedef > 0.02:
        doc.madde(
            _temiz_pdf(
                f"Toplam ile sidebar hedefi arasında %{abs(toplam - hedef) / hedef * 100:.1f} fark var — "
                "öneriyi yeniden aktarmayı veya pozisyonları kontrol etmeyi düşünün.",
                220,
            )
        )
    else:
        doc.madde("Toplam, sidebar portföy tutarı ile uyumlu (±%2).")

    doc.paragraf(
        "Dönem getirileri (1G/1H/1A/3A/6A) alım tarihinizden itibarendir; bugün eklenen pozisyonlarda 0,00%."
    )

    w = doc._w()
    ozet_row = [
        [
            "Portföy",
            f"{toplam:,.0f} {pb}",
            f"{maliyet:,.0f} {pb}",
            f"{kz:+,.0f} ({kz_pct:+.1f}%)",
            _fmt_getiri(deger.agirlikli_getiri.get("1G")),
            _fmt_getiri(deger.agirlikli_getiri.get("1H")),
            _fmt_getiri(deger.agirlikli_getiri.get("1A")),
        ]
    ]
    doc.tablo(
        ["", "Güncel", "Maliyet", "K/Z", "1G", "1H", "1A"],
        ozet_row,
        col_w=[w * 0.14, w * 0.18, w * 0.18, w * 0.18, w * 0.10, w * 0.10, w * 0.10],
        font_boyut=7.5,
    )

    poz_rows = []
    for pd_ in deger.pozisyonlar:
        p = pd_.pozisyon
        poz_rows.append([
            _temiz_pdf(TUR_SECENEKLERI.get(p.tur, p.tur), 14),
            _temiz_pdf(p.etiket(), 18),
            _temiz_pdf(p.sembol or "—", 10),
            f"{pd_.maliyet_deger:,.0f} {pd_.para}",
            f"{pd_.guncel_deger:,.0f} {pd_.para}",
            f"{pd_.kar_zarar:+,.0f}",
            _fmt_getiri(pd_.getiriler.get("1G")),
            _fmt_getiri(pd_.getiriler.get("1A")),
        ])
    doc.tablo(
        ["Tür", "Araç", "Sembol", "Maliyet", "Güncel", "K/Z", "1G", "1A"],
        poz_rows,
        col_w=[w * 0.12, w * 0.18, w * 0.08, w * 0.14, w * 0.14, w * 0.10, w * 0.07, w * 0.07],
        font_boyut=6.8,
        satir_yuk=3.6,
    )

    diger = [x for x in ("TL", "EUR", "USD") if x != pb]
    if diger:
        diger_metin = " · ".join(
            f"{x}: {deger.toplam.get(x, 0):,.0f}" for x in diger
        )
        doc.paragraf(f"Aynı portföy — diğer kur görünümü: {diger_metin}")


def birlesik_oneri_html_blok(
    oneri: Optional[BirlesikOneri],
    *,
    para_birimi: str,
    toplam_eur: float,
    eur_try: float,
    esc,
) -> str:
    if not oneri:
        return ""
    pb_toplam = toplam_eur * eur_try if para_birimi == "TL" else toplam_eur
    notlar = "".join(f"<li>{esc(n)}</li>" for n in oneri.mevcut_notlar[:4])
    hedef_rows = ""
    for h in oneri.hedef_tablo:
        hedef_rows += (
            f"<tr><td>{esc(h.kategori)}</td><td>{esc(h.arac)}</td>"
            f"<td class='num'>%{h.agirlik_pct:.1f}</td>"
            f"<td class='num'>{h.tutar:,.0f} {esc(h.para)}</td></tr>"
        )
    arac_rows = ""
    for s in oneri.arac_dagilim:
        arac_rows += (
            f"<tr><td>{esc(s.ust_kategori)}</td><td>{esc(s.arac)}</td>"
            f"<td>{esc((s.aciklama or '')[:55])}</td>"
            f"<td class='num'>{s.portfoy_pct:.2f}%</td>"
            f"<td class='num'>{s.kategori_ici_pct:.1f}%</td>"
            f"<td class='num'>{s.tutar:,.0f} {esc(s.para)}</td>"
            f"<td>{esc(s.etiket)}</td></tr>"
        )
    arac_tablo = ""
    if arac_rows:
        arac_tablo = f"""
<h3>Araç İçi Dağılım (TEFAS / ETF / BIST)</h3>
<p class="muted">TEFAS/ETF tutarları ilgili nakit payının içinden ayrılır.</p>
<table>
<thead><tr>
<th>Kategori</th><th>Kod</th><th>Açıklama</th><th>Portföy %</th><th>İç %</th><th>Tutar</th><th>Etiket</th>
</tr></thead>
<tbody>{arac_rows}</tbody>
</table>"""
    return f"""
<h2>Önerilen Portföy — Detaylı Hedef</h2>
<p>Sidebar toplam: <strong>{pb_toplam:,.0f} {esc(para_birimi)}</strong> · EUR referans: <strong>{toplam_eur:,.0f} EUR</strong></p>
<p class="muted">{esc(oneri.ozet)}</p>
{"<ul>" + notlar + "</ul>" if notlar else ""}
<table>
<thead><tr><th>Varlık sınıfı</th><th>Özet</th><th>Portföy %</th><th>Tutar</th></tr></thead>
<tbody>{hedef_rows}</tbody>
</table>
{arac_tablo}"""


def varliklarim_html_blok(
    store: Optional[VarlikStore],
    snap: MacroSnapshot,
    kp: KullaniciPortfoy,
    esc,
) -> str:
    if not store:
        return ""
    aktif = store.aktif()
    if not aktif or not aktif.pozisyonlar:
        return f"<h2>Varlıklarım</h2><p class='muted'>{esc(aktif.ad if aktif else 'Portföy')} — pozisyon yok.</p>"

    pb = store.goruntuleme_pb or kp.para_birimi
    deger = portfoy_degerle(aktif, snap)
    toplam = deger.toplam.get(pb, 0)
    maliyet = deger.maliyet_toplam.get(pb, 0)
    kz = toplam - maliyet
    kz_pct = (kz / maliyet * 100) if maliyet > 0 else 0.0
    hedef = _sidebar_hedef(kp, pb, snap)

    poz_rows = ""
    for pd_ in deger.pozisyonlar:
        p = pd_.pozisyon
        poz_rows += (
            f"<tr><td>{esc(TUR_SECENEKLERI.get(p.tur, p.tur))}</td>"
            f"<td>{esc(p.etiket())}</td><td>{esc(p.sembol or '—')}</td>"
            f"<td class='num'>{pd_.maliyet_deger:,.0f} {esc(pd_.para)}</td>"
            f"<td class='num'>{pd_.guncel_deger:,.0f} {esc(pd_.para)}</td>"
            f"<td class='num'>{pd_.kar_zarar:+,.0f}</td>"
            f"<td class='num'>{esc(_fmt_getiri(pd_.getiriler.get('1G')))}</td>"
            f"<td class='num'>{esc(_fmt_getiri(pd_.getiriler.get('1A')))}</td></tr>"
        )
    return f"""
<h2>Varlıklarım — {esc(aktif.ad)}</h2>
<p>Toplam: <strong>{toplam:,.0f} {esc(pb)}</strong> · Maliyet: {maliyet:,.0f} · K/Z: {kz:+,.0f} ({kz_pct:+.2f}%) · Sidebar hedef: {hedef:,.0f} {esc(pb)}</p>
<table>
<thead><tr><th>Tür</th><th>Araç</th><th>Sembol</th><th>Maliyet</th><th>Güncel</th><th>K/Z</th><th>1G</th><th>1A</th></tr></thead>
<tbody>{poz_rows}</tbody>
</table>"""
