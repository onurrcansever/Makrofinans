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
    makro_agirliklar: Optional[dict] = None,
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

    # Uyarı: iki tahsis tablosu neden farklı olabilir?
    if makro_agirliklar and oneri.hedef_tablo:
        # Hedef tablodaki ana kategorileri topla
        hedef_toplamlar: dict = {}
        for h in oneri.hedef_tablo:
            kat = (h.kategori or "").lower()
            hedef_toplamlar[kat] = hedef_toplamlar.get(kat, 0) + h.agirlik_pct
        # Makro tahsisten belirgin fark var mı? (>2pp)
        farklar = []
        KATEGORI_MAP = {"altın": "gold", "tl mevduat": "tl_deposit",
                        "bist / hisse": "bist", "eur nakit": "eur_cash"}
        for kat_ad, mak_key in KATEGORI_MAP.items():
            mak_pct = (makro_agirliklar.get(mak_key, 0) or 0) * 100
            hdf_pct = hedef_toplamlar.get(kat_ad, hedef_toplamlar.get(mak_key, None))
            if hdf_pct is not None and abs(mak_pct - hdf_pct) > 2:
                farklar.append(f"{kat_ad}: Makro %{mak_pct:.0f} — Bu tablo %{hdf_pct:.0f}")
        if farklar:
            doc.kutu(
                "Neden İki Farklı Tahsis Tablosu Var?",
                "Üstteki 'Önerilen Portföy Dağılımı' tablosu saf makro rejim çıktısıdır. "
                "Bu tablo ise BIST/ETF/TEFAS paylarını araçlara dağıtan birleşik model çıktısıdır; "
                "BIST payının hisse/ETF'lere bölünmesi ve araç sınırlamalarından dolayı küçük farklar normaldir. "
                "Farklılıklar: " + " · ".join(farklar),
            )
        else:
            doc.paragraf(
                "Not: Bu tablo BIST/ETF paylarını araçlara bölen birleşik model çıktısıdır; "
                "üstteki makro tahsis tablosundan ±2pp sapma normaldir."
            )

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
                f"%{s.portfoy_pct:.1f}",
                f"%{s.kategori_ici_pct:.1f}",
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
        f"Güncel değer: {toplam:,.0f} {pb}  ·  Maliyet: {maliyet:,.0f} {pb}  ·  "
        f"Kar/Zarar: {kz:+,.0f} ({kz_pct:+.2f}%)  ·  Öneri hedefi: {hedef:,.0f} {pb}",
    )
    if hedef > 0:
        bosluk_pct = abs(toplam - hedef) / hedef * 100
        if bosluk_pct >= 15:
            fark_tutar = abs(toplam - hedef)
            if toplam < hedef:
                secenek_a = (
                    f"(a) ~{fark_tutar:,.0f} {pb} ek sermaye ekleyerek "
                    f"portföyü {hedef:,.0f} {pb} hedef düzeyine çıkarın"
                )
                secenek_b = (
                    f"(b) Rapordaki tüm yüzdeleri mevcut {toplam:,.0f} {pb} "
                    "tutarınıza göre yeniden ölçekleyin — her öneri tutarı "
                    f"otomatik olarak küçülür, dağılım oranları değişmez"
                )
            else:
                secenek_a = (
                    f"(a) ~{fark_tutar:,.0f} {pb} tutarında pozisyon kapatarak "
                    f"portföyü {hedef:,.0f} {pb} hedef düzeyine indirin"
                )
                secenek_b = (
                    f"(b) Öneri tabanını mevcut {toplam:,.0f} {pb} tutarınıza "
                    "göre yeniden ölçekleyin — dağılım oranları değişmez"
                )
            doc.kutu(
                f"Büyük Portföy Boşluğu — %{bosluk_pct:.0f} Fark",
                f"Mevcut portföyünüz ({toplam:,.0f} {pb}) öneri tabanından "
                f"{fark_tutar:,.0f} {pb} (%{bosluk_pct:.0f}) uzakta. "
                "Rapor bu farkı öneriler içinde açıkça ele almıyor. "
                "İki seçenek mevcut: "
                f"{secenek_a}; "
                f"VEYA {secenek_b}. "
                "Pozisyon değişikliğini tek seferde değil kademeli yapmanız "
                "piyasa riskini azaltır.",
            )
        elif bosluk_pct > 5:
            doc.madde(
                _temiz_pdf(
                    f"Portföy ile öneri hedefi arasında %{bosluk_pct:.1f} fark var — "
                    "pozisyonları kontrol edin veya öneriyi yeniden aktarın.",
                    220,
                )
            )
        else:
            doc.madde(f"Portföy, öneri hedefi ile uyumlu (fark: %{bosluk_pct:.1f}).")

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
    makro_agirliklar: Optional[dict] = None,
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

    # Tutarsızlık notu
    tutarsizlik_html = ""
    if makro_agirliklar and oneri.hedef_tablo:
        hedef_toplamlar: dict = {}
        for h in oneri.hedef_tablo:
            kat = (h.kategori or "").lower()
            hedef_toplamlar[kat] = hedef_toplamlar.get(kat, 0) + h.agirlik_pct
        KATEGORI_MAP = {"altın": "gold", "tl mevduat": "tl_deposit",
                        "bist / hisse": "bist", "eur nakit": "eur_cash"}
        farklar = []
        for kat_ad, mak_key in KATEGORI_MAP.items():
            mak_pct = (makro_agirliklar.get(mak_key, 0) or 0) * 100
            hdf_pct = hedef_toplamlar.get(kat_ad, hedef_toplamlar.get(mak_key, None))
            if hdf_pct is not None and abs(mak_pct - hdf_pct) > 2:
                farklar.append(f"<strong>{esc(kat_ad)}</strong>: Makro %{mak_pct:.0f} — Bu tablo %{hdf_pct:.0f}")
        if farklar:
            tutarsizlik_html = (
                '<div class="box"><strong>Neden İki Farklı Tahsis Tablosu Var?</strong>'
                "<p>Üstteki tablo saf makro rejim çıktısı; bu tablo BIST/ETF/TEFAS araçlarına "
                "bölünen birleşik model çıktısıdır. Farklar:<br>"
                + " &nbsp;·&nbsp; ".join(farklar) + "</p></div>"
            )
        else:
            tutarsizlik_html = (
                "<p class='muted'>Bu tablo BIST/ETF paylarını araçlara bölen birleşik model çıktısıdır; "
                "üstteki makro tahsis tablosundan ±2 puan sapma normaldir.</p>"
            )

    arac_rows = ""
    for s in oneri.arac_dagilim:
        arac_rows += (
            f"<tr><td>{esc(s.ust_kategori)}</td><td>{esc(s.arac)}</td>"
            f"<td>{esc((s.aciklama or '')[:55])}</td>"
            f"<td class='num'>%{s.portfoy_pct:.1f}</td>"
            f"<td class='num'>%{s.kategori_ici_pct:.1f}</td>"
            f"<td class='num'>{s.tutar:,.0f} {esc(s.para)}</td>"
            f"<td>{esc(s.etiket)}</td></tr>"
        )
    arac_tablo = ""
    if arac_rows:
        arac_tablo = f"""
<h3>Araç İçi Dağılım (TEFAS / ETF / BIST)</h3>
<p class="muted">TEFAS/ETF tutarları ilgili nakit payının içinden ayrılır; çift sayım yapılmaz.</p>
<table>
<thead><tr>
<th>Kategori</th><th>Kod</th><th>Açıklama</th><th>Portföy %</th><th>İç %</th><th>Tutar</th><th>Etiket</th>
</tr></thead>
<tbody>{arac_rows}</tbody>
</table>"""
    return f"""
<h2>Önerilen Portföy — Detaylı Hedef</h2>
<p>Sidebar toplam: <strong>{pb_toplam:,.0f} {esc(para_birimi)}</strong> &nbsp;·&nbsp; EUR referans: <strong>{toplam_eur:,.0f} EUR</strong></p>
{tutarsizlik_html}
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
    bosluk_html = ""
    if hedef > 0:
        bosluk_pct = abs(toplam - hedef) / hedef * 100
        if bosluk_pct >= 15:
            fark_tutar = abs(toplam - hedef)
            if toplam < hedef:
                sec_a = (
                    f"<strong>(a)</strong> ~{fark_tutar:,.0f} {esc(pb)} ek sermaye ekleyerek "
                    f"portföyü {hedef:,.0f} {esc(pb)} hedef düzeyine çıkarın"
                )
                sec_b = (
                    f"<strong>(b)</strong> Rapordaki tüm yüzdeleri mevcut "
                    f"<strong>{toplam:,.0f} {esc(pb)}</strong> tutarınıza göre yeniden ölçekleyin "
                    "— her öneri tutarı küçülür, dağılım oranları değişmez"
                )
            else:
                sec_a = (
                    f"<strong>(a)</strong> ~{fark_tutar:,.0f} {esc(pb)} tutarında pozisyon "
                    "kapatarak portföyü hedef düzeyine indirin"
                )
                sec_b = (
                    f"<strong>(b)</strong> Öneri tabanını mevcut "
                    f"<strong>{toplam:,.0f} {esc(pb)}</strong> tutarınıza göre "
                    "yeniden ölçekleyin — dağılım oranları değişmez"
                )
            bosluk_html = f"""
<div class="ozet-kutu tl-onerilmiyor">
<strong>Büyük Portföy Boşluğu — %{bosluk_pct:.0f} Fark</strong>
<p>Mevcut portföyünüz (<strong>{toplam:,.0f} {esc(pb)}</strong>) öneri tabanından
<strong>{fark_tutar:,.0f} {esc(pb)}</strong> (%{bosluk_pct:.0f}) uzakta.
Rapor bu farkı öneriler içinde açıkça ele almıyor.</p>
<p>İki seçenek mevcut:</p>
<ol>
<li>{sec_a}.</li>
<li>{sec_b}.</li>
</ol>
<p class="muted">Pozisyon değişikliğini tek seferde değil kademeli yapmanız piyasa riskini azaltır.</p>
</div>"""
        elif bosluk_pct > 5:
            bosluk_html = f"<p class='muted'>Portföy ile öneri hedefi arasında %{bosluk_pct:.1f} fark — kontrol edin.</p>"

    return f"""
<h2>Varlıklarım — {esc(aktif.ad)}</h2>
<p>Güncel değer: <strong>{toplam:,.0f} {esc(pb)}</strong> &nbsp;·&nbsp; Maliyet: {maliyet:,.0f} &nbsp;·&nbsp; K/Z: {kz:+,.0f} ({kz_pct:+.2f}%) &nbsp;·&nbsp; Öneri hedefi: {hedef:,.0f} {esc(pb)}</p>
{bosluk_html}
<table>
<thead><tr><th>Tür</th><th>Araç</th><th>Sembol</th><th>Maliyet</th><th>Güncel</th><th>K/Z</th><th>1G</th><th>1A</th></tr></thead>
<tbody>{poz_rows}</tbody>
</table>"""


_TEFAS_ONERI_SIRASI = {
    "GÜÇLÜ AL": 0,
    "AL": 1,
    "IZLE": 2,
    "İZLE": 2,
    "BEKLE": 3,
    "AZALT": 4,
}


def _tefas_fon_listesi(
    tefas_ham,
    *,
    limit: int = 20,
    profil=None,
    rejim: str = "NOTR",
    mevduat_reel=None,
    gosterim_pb: str = "EUR",
):
    """Skorlu üst fonlar; KAP disk cache ile Yön/TGO (ağ yok). Ham cache mutate edilmez."""
    if tefas_ham is None or not getattr(tefas_ham, "fonlar", None):
        return []

    from copy import deepcopy

    kaynak = None
    if profil is not None:
        try:
            from tefas_skor import tefas_skorlu_kopya

            kaynak = tefas_skorlu_kopya(
                tefas_ham,
                profil,
                rejim=rejim or "NOTR",
                mevduat_reel=mevduat_reel,
                gosterim_pb=gosterim_pb or "EUR",
            )
        except Exception:
            kaynak = None
    if kaynak is None:
        kaynak = deepcopy(tefas_ham)

    fonlar = list(getattr(kaynak, "fonlar", None) or [])
    if not fonlar:
        return []
    try:
        from tefas_fon_meta import fon_gider_meta_cache_oku, gider_meta_uygula

        kodlar = [f.kod for f in fonlar if getattr(f, "kod", None)]
        if kodlar:
            gider_meta_uygula(fonlar, fon_gider_meta_cache_oku(kodlar, limit=len(kodlar)))
    except Exception:
        pass
    try:
        from tefas_stopaj import tefas_stopaj_sinifi

        for f in fonlar:
            if getattr(f, "stopaj_etiket", None):
                continue
            etiket, _o, _n = tefas_stopaj_sinifi(
                ad=getattr(f, "ad", "") or "",
                kategori=getattr(f, "kategori", "") or "",
                hisse_pct=getattr(f, "hisse_pct", None),
            )
            f.stopaj_etiket = etiket
    except Exception:
        pass
    fonlar = sorted(
        fonlar,
        key=lambda f: (
            _TEFAS_ONERI_SIRASI.get(getattr(f, "oneri", "") or "", 5),
            -(getattr(f, "skor", 0) or 0),
            -(getattr(f, "getiri_3a", None) or -999),
        ),
    )
    return fonlar[: max(1, limit)]


def _pct_cell(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):+.2f}%"
    except (TypeError, ValueError):
        return "—"


def _fee_cell(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return "—"


def tefas_fonlari_pdf_bolumu(
    doc: "RaporPDF",
    tefas_ham,
    *,
    limit: int = 18,
    profil=None,
    rejim: str = "NOTR",
    mevduat_reel=None,
    gosterim_pb: str = "EUR",
) -> None:
    """TEFAS üst fonlar — profil skorlu Öneri/Skor, Yön%/TGO, stopaj, 1A/3A/YBB."""
    fonlar = _tefas_fon_listesi(
        tefas_ham,
        limit=limit,
        profil=profil,
        rejim=rejim,
        mevduat_reel=mevduat_reel,
        gosterim_pb=gosterim_pb,
    )
    if not fonlar:
        doc.bolum("TEFAS Fon Özeti (Yön / TGO / Getiri)")
        doc.paragraf(
            "TEFAS verisi bu raporda yok (henüz yüklenmedi veya hata). "
            "TEFAS sayfasını açıp Yenile sonrası raporu yeniden oluşturun."
        )
        return

    n_al = sum(1 for f in fonlar if (getattr(f, "oneri", "") or "") == "AL")
    doc.bolum("TEFAS Fon Özeti (Yön / TGO / Getiri)")
    doc.paragraf(
        f"Kaynak: {_temiz_pdf(getattr(tefas_ham, 'kaynak', '') or 'TEFAS', 40)} · "
        f"fiili tarihçe ~{getattr(tefas_ham, 'gun', '—')} gün · "
        f"üst {len(fonlar)} fon (profil skor) · AL: {n_al}. "
        "Yön.%/TGO disk KAP önbelleğinden; ağ yok. "
        "Getiriler fon PB native; 3A/YBB tarihçe yoksa —."
    )
    w = doc._w()
    rows = []
    for f in fonlar:
        g1 = getattr(f, "getiri_gosterim_1a", None)
        if g1 is None:
            g1 = getattr(f, "getiri_1a", None)
        g3 = getattr(f, "getiri_gosterim_3a", None)
        if g3 is None:
            g3 = getattr(f, "getiri_3a", None)
        gy = getattr(f, "getiri_gosterim_ybb", None)
        if gy is None:
            gy = getattr(f, "getiri_ybb", None)
        rows.append([
            _temiz_pdf(getattr(f, "oneri", "") or "—", 8),
            _temiz_pdf(f.kod, 6),
            _temiz_pdf(getattr(f, "kisa_ad", None) or f.ad, 22),
            _fee_cell(getattr(f, "yonetim_ucreti_pct", None)),
            _fee_cell(getattr(f, "tgo_pct", None)) if getattr(f, "tgo_pct", None) is not None else "KAP yok",
            _temiz_pdf(getattr(f, "stopaj_etiket", "") or "—", 8),
            _pct_cell(g1),
            _pct_cell(g3),
            _pct_cell(gy),
            f"{getattr(f, 'skor', 0) or 0:.0f}",
        ])
    doc.tablo(
        ["Öneri", "Kod", "Fon", "Yön.%", "TGO%", "Stopaj", "1A", "3A", "YBB", "Skor"],
        rows,
        col_w=[w * x for x in (0.07, 0.06, 0.18, 0.07, 0.08, 0.08, 0.09, 0.09, 0.09, 0.07)],
        font_boyut=6.5,
        satir_yuk=3.5,
    )


def tefas_fonlari_html_blok(
    tefas_ham,
    *,
    esc,
    limit: int = 18,
    profil=None,
    rejim: str = "NOTR",
    mevduat_reel=None,
    gosterim_pb: str = "EUR",
) -> str:
    fonlar = _tefas_fon_listesi(
        tefas_ham,
        limit=limit,
        profil=profil,
        rejim=rejim,
        mevduat_reel=mevduat_reel,
        gosterim_pb=gosterim_pb,
    )
    if not fonlar:
        return """
<h2>TEFAS Fon Özeti (Yön / TGO / Getiri)</h2>
<p class="muted">TEFAS verisi bu raporda yok (henüz yüklenmedi veya hata).
TEFAS sayfasını açıp Yenile sonrası raporu yeniden oluşturun.</p>"""
    rows = ""
    for f in fonlar:
        g1 = getattr(f, "getiri_gosterim_1a", None)
        if g1 is None:
            g1 = getattr(f, "getiri_1a", None)
        g3 = getattr(f, "getiri_gosterim_3a", None)
        if g3 is None:
            g3 = getattr(f, "getiri_3a", None)
        gy = getattr(f, "getiri_gosterim_ybb", None)
        if gy is None:
            gy = getattr(f, "getiri_ybb", None)
        tgo = getattr(f, "tgo_pct", None)
        tgo_s = _fee_cell(tgo) if tgo is not None else "KAP yok"
        rows += (
            f"<tr><td>{esc(getattr(f, 'oneri', '') or '—')}</td>"
            f"<td>{esc(f.kod)}</td>"
            f"<td>{esc(getattr(f, 'kisa_ad', None) or f.ad)}</td>"
            f"<td class='num'>{esc(_fee_cell(getattr(f, 'yonetim_ucreti_pct', None)))}</td>"
            f"<td class='num'>{esc(tgo_s)}</td>"
            f"<td>{esc(getattr(f, 'stopaj_etiket', '') or '—')}</td>"
            f"<td class='num'>{esc(_pct_cell(g1))}</td>"
            f"<td class='num'>{esc(_pct_cell(g3))}</td>"
            f"<td class='num'>{esc(_pct_cell(gy))}</td>"
            f"<td class='num'>{getattr(f, 'skor', 0) or 0:.0f}</td></tr>"
        )
    n_al = sum(1 for f in fonlar if (getattr(f, "oneri", "") or "") == "AL")
    return f"""
<h2>TEFAS Fon Özeti (Yön / TGO / Getiri)</h2>
<p class="muted">Kaynak: {esc(getattr(tefas_ham, 'kaynak', '') or 'TEFAS')} ·
fiili ~{esc(getattr(tefas_ham, 'gun', '—'))} gün · üst {len(fonlar)} fon (profil skor) · AL: {n_al}.
Yön.%/TGO disk KAP önbelleğinden (ağ yok).</p>
<table>
<thead><tr>
<th>Öneri</th><th>Kod</th><th>Fon</th><th>Yön.%</th><th>TGO%</th>
<th>Stopaj</th><th>1A</th><th>3A</th><th>YBB</th><th>Skor</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>"""

