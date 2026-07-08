# -*- coding: utf-8 -*-
"""
Denetim / Tutarlılık Motoru
===========================
Farklı modüllerden gelen verileri çapraz kontrol eder; çelişki ve güncellik
uyarıları üretir. AI Danışman raporuna eklenir — kullanıcıyı yanıltıcı
önerilerden korur.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from allocation_engine import TahsisSonucu
from investor_profile import vade_kisa_mi
from macro_data import MacroSnapshot
from market_context import MakroBaglam
from rates_tr import MevduatKarsilastirma
from veri_kalitesi import veri_kalite_olustur


@dataclass
class DenetimBulgusu:
    seviye: str          # KRITIK | UYARI | BILGI
    kategori: str        # veri | mantik | sinyal | rejim
    baslik: str
    taraf_a: str         # "Sistem X diyor"
    taraf_b: str         # "Oysa Y diyor"
    oneri: str
    varlik: Optional[str] = None


@dataclass
class DenetimRaporu:
    bulgular: List[DenetimBulgusu] = field(default_factory=list)
    temiz: bool = True
    kritik_sayisi: int = 0
    uyari_sayisi: int = 0
    ozet: str = ""


def _ekle(bulgular: List[DenetimBulgusu], b: DenetimBulgusu) -> None:
    bulgular.append(b)


def _varlik_bul(varliklar: List[Any], anahtar: str) -> Optional[Any]:
    return next((v for v in varliklar if v.anahtar == anahtar), None)


def _enflasyon_resmi_kaynak(kaynak: str) -> bool:
    k = (kaynak or "").lower()
    return any(x in k for x in ("tüik", "resmi", "enflasyon_resmi", "tcmb evds"))


def denetim_calistir(
    snap: MacroSnapshot,
    tahsis: TahsisSonucu,
    varliklar: List[Any],
    baglam: Optional[MakroBaglam] = None,
    mevduat: Optional[MevduatKarsilastirma] = None,
    oncelik: Optional[List[str]] = None,
    tarama=None,
) -> DenetimRaporu:
    bulgular: List[DenetimBulgusu] = []
    kh = snap.kaynak_haritasi or {}
    rejim = tahsis.rejim.rejim
    enf = snap.enflasyon_tr_yillik or 35.0
    tcmb = snap.veri.tcmb_politika_faizi or 37.0
    tcmb_reel = tcmb - enf
    cds = snap.veri.cds_5y_bp

    vk = veri_kalite_olustur(snap)
    if vk.genel_duzey == "DUSUK":
        _ekle(bulgular, DenetimBulgusu(
            "UYARI", "veri",
            f"Veri kalitesi düşük ({vk.genel_skor:.0f}/100)",
            f"Rapor {len(vk.gostergeler)} göstergeden üretildi.",
            vk.ozet,
            "Proxy/yedek kaynakları manuel teyit edin; EVDS/FRED key ekleyin.",
        ))
    elif vk.genel_skor < 65:
        _ekle(bulgular, DenetimBulgusu(
            "BILGI", "veri",
            f"Veri kalitesi orta ({vk.genel_skor:.0f}/100)",
            "Bazı göstergeler model veya gecikmeli kaynaklı.",
            vk.ozet,
            "CDS ve enflasyon için resmi kaynak teyidi önerilir.",
        ))

    if tarama:
        tarama_uyarilar = getattr(tarama, "uyarilar", None) or []
        kur_yok = any(
            "EUR bazlı 52H hesaplanamadı" in u for u in tarama_uyarilar
        ) or any(
            getattr(h, "bist_52h_kur_yok", False)
            for h in getattr(tarama, "hisseler", []) or []
            if str(getattr(h, "sembol", "")).endswith(".IS")
        )
        if kur_yok:
            _ekle(bulgular, DenetimBulgusu(
                "UYARI", "veri",
                "EUR bazlı 52H hesaplanamadı",
                "BIST değerleme riski için EUR bandı kullanılamıyor.",
                "Kur (EURTRY=X) verisi çekilemedi — tabloda TL bandı gösteriliyor.",
                "Yahoo Finance erişimini kontrol edin; DİKKAT kararı EUR olmadan verilmez.",
                "bist",
            ))

    # ── 1) Veri güncelliği ──────────────────────────────────────
    cds_kaynak = kh.get("cds", "")
    cds_lower = cds_kaynak.lower()
    if "investing" in cds_lower and any(x in cds_lower for x in ("çelişki", "çapraz", "tercih")):
        _ekle(bulgular, DenetimBulgusu(
            "UYARI", "veri",
            "CDS Bloomberg ile Investing çelişiyor",
            f"Rejim motoru CDS **{cds or '?'} bp** ile çalışıyor.",
            f"Kaynak: **{cds_kaynak}**.",
            "Bloomberg Terminal bağlantısını kontrol edin.",
        ))
    elif any(x in " ".join(getattr(snap, "cekim_uyarilari", []) or []).lower() for x in ("geciken veri", "bloomberg terminal erişilemedi")):
        _ekle(bulgular, DenetimBulgusu(
            "UYARI", "veri",
            "CDS yalnızca Investing (gecikmeli) veya tek kaynak",
            f"Rejim motoru CDS **{cds or '?'} bp** ile çalışıyor.",
            f"Kaynak: **{cds_kaynak}**.",
            "Bloomberg Terminal (BLPAPI) bağlantısı kurulursa çapraz doğrulama aktif olur.",
        ))
    elif any(x in cds_lower for x in ("piyasa modeli", "proxy", "türetilmiş")):
        _ekle(bulgular, DenetimBulgusu(
            "BILGI", "veri",
            "CDS piyasa modeli ile tahmin ediliyor",
            f"Rejim motoru CDS **{cds or '?'} bp** ile çalışıyor.",
            f"Kaynak: **{cds_kaynak}** — doğrudan CDS kotasyonu değil, makro proxy.",
            "Bloomberg Terminal veya Investing erişimini kontrol edin.",
        ))
    elif any(x in cds_lower for x in ("acil yedek", "ulaşılamadı")):
        _ekle(bulgular, DenetimBulgusu(
            "UYARI", "veri",
            "CDS kaynağına ulaşılamadı",
            f"Rejim motoru CDS **{cds or '?'} bp** ile çalışıyor.",
            f"Kaynak: **{cds_kaynak}**.",
            "Ağ bağlantısını kontrol edin; sistem bir sonraki yenilemede tekrar dener.",
        ))

    enf_kaynak = kh.get("enflasyon", "")
    if any(x in enf_kaynak.lower() for x in ("varsayılan", "acil yedek", "ulaşılamadı")):
        _ekle(bulgular, DenetimBulgusu(
            "UYARI", "veri",
            "Enflasyon varsayılan",
            f"Reel faiz hesabı **%{enf:.0f}** enflasyon varsayımına dayanıyor.",
            "TÜİK/EVDS canlı verisi yok.",
            "Reel getiri yorumları gerçek enflasyondan sapabilir — EVDS key opsiyonel.",
        ))
    elif any(x in enf_kaynak.lower() for x in ("gecikmeli", "⚠")) and "evds" in enf_kaynak.lower():
        _ekle(bulgular, DenetimBulgusu(
            "UYARI", "veri",
            "Enflasyon verisi güncel ay değil",
            f"Reel faiz **%{enf:.1f}** ile hesaplanıyor.",
            f"Kaynak: **{enf_kaynak}**.",
            "TÜİK aylık bülten sonrası manual_inputs.json → "
            "`enflasyon_tr_yillik` + `enflasyon_ay` (ör. 2026-6) güncelleyin.",
        ))
    elif (
        not _enflasyon_resmi_kaynak(enf_kaynak)
        and any(x in enf_kaynak.lower() for x in ("world bank", "fred"))
        and "evds" not in enf_kaynak.lower()
    ):
        _ekle(bulgular, DenetimBulgusu(
            "UYARI", "veri",
            "Enflasyon yıllık/gecikmeli kaynaktan (TÜİK değil)",
            f"Reel faiz **%{enf:.0f}** enflasyon ile hesaplanıyor.",
            f"Kaynak: **{enf_kaynak}**.",
            "Aylık resmi TÜFE için EVDS TP.FG.J0 veya TÜİK bülteni kullanın.",
        ))

    fed_kaynak = kh.get("fed_faizi", "")
    if "irx" in fed_kaynak.lower():
        _ekle(bulgular, DenetimBulgusu(
            "BILGI", "veri",
            "Fed faizi ^IRX proxy ile",
            f"Gösterilen değer: **%{snap.veri.fed_faizi or '?'}**.",
            f"Kaynak: **{fed_kaynak}** — 13W Hazine bonosu, Fed DFF değil.",
            "FRED_API_KEY ile DFF serisi kullanılabilir.",
        ))

    if snap.veri_kaynak == "demo":
        _ekle(bulgular, DenetimBulgusu(
            "BILGI", "veri",
            "Demo modu aktif",
            "Bazı makro parametreler (CDS, enflasyon senaryosu) **sabit senaryo**.",
            "Piyasa fiyatları (altın, BIST, kur) **canlı** çekiliyor.",
            "Tam güven için sidebar'dan **Canlı veri** moduna geçin.",
        ))

    # ── 2) Reel faiz: yerel vs EUR bazlı ─────────────────────────
    if mevduat and mevduat.profil_vade_reel > 0 and mevduat.profil_vade_eur_tahmini <= 0:
        _ekle(bulgular, DenetimBulgusu(
            "UYARI", "mantik",
            "Yerel reel pozitif ama EUR bazlı tahmini negatif/sınırda",
            f"Yerel reel (TL enflasyonu): **{mevduat.profil_vade_reel:+.1f} pp**.",
            f"EUR bazlı tahmini: **{mevduat.profil_vade_eur_tahmini:+.1f} pp** (reel kur sabit varsayımı).",
            "«Reel +%2» ifadesini EUR garantisi sanmayın — kur hızlanırsa EUR bazında zarar mümkün.",
            "tl_deposit",
        ))
    elif mevduat and mevduat.profil_vade_reel > 1 and mevduat.profil_vade_eur_tahmini < mevduat.profil_vade_reel - 3:
        _ekle(bulgular, DenetimBulgusu(
            "BILGI", "mantik",
            "Yerel reel ile EUR bazlı tahmini farklı",
            f"Yerel reel: **{mevduat.profil_vade_reel:+.1f} pp** (net − TL enflasyonu).",
            f"EUR bazlı tahmini: **{mevduat.profil_vade_eur_tahmini:+.1f} pp**.",
            "EUR yatırımcısı için asıl soru kur hareketidir; mevduat tablosundaki «getiri notu»nu okuyun.",
            "tl_deposit",
        ))

    if mevduat and mevduat.profil_vade_reel is not None and abs(tcmb_reel - mevduat.profil_vade_reel) >= 1.5:
        _ekle(bulgular, DenetimBulgusu(
            "BILGI", "mantik",
            "Politika reel ile mevduat reel farklı — ikisi de doğru, tanım farklı",
            f"Politika reel (TCMB − enflasyon): **{tcmb_reel:+.1f} pp** — rejim/strateji notlarında.",
            f"Mevduat reel (banka net − enflasyon): **{mevduat.profil_vade_reel:+.1f} pp** — mevduat tablosunda.",
            "TL kararı için **mevduat reel** esas alın; politika reel makro bağlam içindir.",
            "tl_deposit",
        ))

    if snap.veri.savas_risk_guvenilir is False:
        _ekle(bulgular, DenetimBulgusu(
            "UYARI", "veri",
            "Jeopolitik tarama güvenilir değil",
            f"Rapor jeopolitik sayısı: **{snap.veri.savas_risk_makale_sayisi or 0}**.",
            "Google News/GDELT boş veya erişilemedi — aktif savaş haberleri kaçırılmış olabilir.",
            "Hürmüz/İran gündemini manuel kontrol edin; jeopolitik kapıya güvenmeyin.",
        ))

    if snap.veri.rezerv_artiyor is None:
        _ekle(bulgular, DenetimBulgusu(
            "UYARI", "veri",
            "Rezerv trendi bilinmiyor — Kapı 4 temkin uygulandı",
            "TL tavanı rezerv verisi olmadan **×0,85** temkin çarpanı ile hesaplandı.",
            "EVDS key yoksa gerçek rezerv trendi uygulanamaz.",
            "TL payı olasılıkla tavanın altında kalmalı; EVDS ile teyit edin.",
            "tl_deposit",
        ))

    # ── 3) Reel faiz: TCMB vs banka faizi ───────────────────────
    ykb = None
    try:
        from yapikredi_rates import net_brut_oran, yapikredi_tl_faizleri
        ykb = yapikredi_tl_faizleri()
        if ykb:
            reel_3ay = net_brut_oran(ykb.tl_3ay_brut, 92) * 100 - enf
            reel_1y = net_brut_oran(ykb.tl_1y_brut, 365) * 100 - enf
            if tcmb_reel > 0 and reel_1y < 0:
                _ekle(bulgular, DenetimBulgusu(
                    "UYARI", "mantik",
                    "Reel faiz vadeye göre değişiyor",
                    f"TCMB − enflasyon = **{tcmb_reel:+.1f} pp** (politika faizi bazlı).",
                    f"Yapı Kredi 1 yıl mevduat reel = **{reel_1y:+.1f}%**; 3 ay reel = **{reel_3ay:+.1f}%**.",
                    "TL mevduat yorumu **vadeye bağlı**: kısa vade cazip, 1 yıl enflasyon altında kalabilir.",
                    "tl_deposit",
                ))
            if tcmb_reel <= 0 and reel_3ay > 0:
                _ekle(bulgular, DenetimBulgusu(
                    "UYARI", "mantik",
                    "TCMB reel negatif, banka faizi pozitif",
                    f"Politika faizi reel **{tcmb_reel:+.1f} pp**.",
                    f"Banka 3 ay brüt **%{ykb.tl_3ay_brut:.1f}** → reel **{reel_3ay:+.1f}%**.",
                    "Karar **banka teklif vadesine** göre verilmeli; tek reel faiz rakamına güvenmeyin.",
                    "tl_deposit",
                ))
    except Exception:
        pass

    # ── 4) Mevduat modülü vs danışman ───────────────────────────
    if mevduat:
        tl_v = _varlik_bul(varliklar, "tl_deposit")
        if (
            tl_v
            and tl_v.sinyal in ("GUCLU_AL", "AL")
            and not mevduat.tl_mevduat_kazanir
        ):
            _ekle(bulgular, DenetimBulgusu(
                "KRITIK", "sinyal",
                "TL önerisi vs mevduat analizi çelişiyor",
                f"AI Danışman TL için **{tl_v.sinyal_etiket}** diyor.",
                f"Mevduat modülü: en iyi TL reel **{mevduat.en_iyi_reel:+.1f}%** — EUR'ya göre cazip değil.",
                "TL tahsisini **kısa vade** ve kur riski ile sınırlayın; mevduat tablosunu kontrol edin.",
                "tl_deposit",
            ))
        elif (
            tahsis.tl_reel_sinirlandi
            and mevduat.profil_vade_reel is not None
            and mevduat.profil_vade_reel <= 0
        ):
            _ekle(bulgular, DenetimBulgusu(
                "BILGI", "sinyal",
                "TL reel negatif — tahsis otomatik sınırlandı",
                f"Profil vadesi reel **{mevduat.profil_vade_reel:+.1f} pp**.",
                f"TL payı **%{tahsis.agirliklar.get('tl_deposit', 0)*100:.0f}** — güçlü alım sinyali verilmedi.",
                "Mevduat tablosu ile danışman önerisi uyumlu.",
                "tl_deposit",
            ))
        elif tl_v and tl_v.sinyal in ("GUCLU_AL", "AL") and mevduat.en_iyi_reel < 0:
            best = next((o for o in mevduat.oranlar if o.vade.startswith("TL")), None)
            if best and best.reel_yillik and best.reel_yillik < 0:
                _ekle(bulgular, DenetimBulgusu(
                    "UYARI", "sinyal",
                    "TL alım sinyali ama reel getiri negatif",
                    f"Danışman: **{tl_v.sinyal_etiket}** (%{tl_v.agirlik_pct:.0f}).",
                    f"{best.vade} reel getiri **{best.reel_yillik:+.1f}%** (enflasyon altında).",
                    "Uzun vadeli TL yerine **3–6 ay** kademeli mevduat düşünün.",
                    "tl_deposit",
                ))

    # ── 4) Rejim vs sinyal çelişkileri ─────────────────────────
    tl_v = _varlik_bul(varliklar, "tl_deposit")
    if rejim == "TL_FIRSAT" and tl_v and tl_v.agirlik_pct < 8:
        profil = tahsis.profil
        vade_kisa = profil and vade_kisa_mi(profil.vade)
        tl_tavan_pct = (tahsis.tl_tavan_oran or 0) * 100
        sinirli = (
            tahsis.tl_reel_sinirlandi
            or tahsis.tl_rejim_sinirlandi
            or tahsis.tl_risk_sinirlandi
            or (tl_tavan_pct > 0 and tl_v.agirlik_pct >= tl_tavan_pct - 1.5)
        )
        if vade_kisa or sinirli:
            _ekle(bulgular, DenetimBulgusu(
                "BILGI", "rejim",
                "TL fırsat rejimi — kısa vade / tavan TL payını sınırlıyor",
                f"Rejim: **{tahsis.rejim.etiket}** (TL cazip olabilir).",
                f"TL tahsis **%{tl_v.agirlik_pct:.0f}** — "
                f"{'vade tabanı ve EUR likidite öncelikli' if vade_kisa else '4 kapı / risk / reel tavanı bağlayıcı'}.",
                "Rejim etiketi makro koşulu yansıtır; tahsis **vade + kapı** önceliklidir.",
                "tl_deposit",
            ))
        else:
            _ekle(bulgular, DenetimBulgusu(
                "UYARI", "rejim",
                "TL fırsat rejimi ama düşük tahsis",
                f"Rejim: **{tahsis.rejim.etiket}** (TL cazip olmalı).",
                f"TL tahsis yalnızca **%{tl_v.agirlik_pct:.0f}** — profil veya 4 kapı sınırlıyor.",
                "Bu tutarlı olabilir; 4 kapı kuralları bilinçli sınırlama yapıyor.",
                "tl_deposit",
            ))

    if rejim != "TL_FIRSAT" and tl_v and tl_v.sinyal == "GUCLU_AL":
        if tahsis.tl_rejim_sinirlandi or tahsis.tl_risk_sinirlandi:
            _ekle(bulgular, DenetimBulgusu(
                "BILGI", "rejim",
                "TL otomatik sınırlandı (rejim/risk)",
                f"Rejim: **{tahsis.rejim.etiket}**.",
                f"TL payı **%{tl_v.agirlik_pct:.0f}** — rejim veya risk tavanı uygulandı.",
                "Carry trade faiz avantajı risk toleransının üstüne çıkmadı.",
                "tl_deposit",
            ))
        else:
            _ekle(bulgular, DenetimBulgusu(
                "UYARI", "rejim",
                "Güçlü TL sinyali ama rejim TL fırsat değil",
                f"Rejim: **{tahsis.rejim.etiket}**.",
                f"TL kartı: **Güçlü alım** (%{tl_v.agirlik_pct:.0f}).",
                "TL ağırlığı makro skordan geliyor; rejim etiketi ile çelişiyor gibi görünebilir — dikkatli olun.",
                "tl_deposit",
            ))

    bist_v = _varlik_bul(varliklar, "bist")
    if rejim in ("KRIZ", "EM_STRES") and bist_v and bist_v.sinyal in ("GUCLU_AL", "AL"):
        _ekle(bulgular, DenetimBulgusu(
            "KRITIK", "rejim",
            "Stres rejiminde BIST alım sinyali",
            f"Rejim: **{tahsis.rejim.etiket}** — hisse riski yüksek.",
            f"BIST kartı: **{bist_v.sinyal_etiket}**.",
            "Stres ortamında BIST pozisyonu **küçük tutun** veya bekleyin; sinyal skorla çelişiyor.",
            "bist",
        ))

    if rejim == "KRIZ":
        for key in ("tl_deposit", "bist", "crypto", "silver"):
            v = _varlik_bul(varliklar, key)
            if v and v.agirlik_pct > 1 and v.sinyal != "KACIN":
                _ekle(bulgular, DenetimBulgusu(
                    "KRITIK", "rejim",
                    f"Kriz rejiminde {v.ad} hâlâ aktif",
                    "Kriz modu: riskli varlıklar **sıfırlanmalı**.",
                    f"{v.ad}: **%{v.agirlik_pct:.0f}** — {v.sinyal_etiket}.",
                    "Kriz rejiminde likit EUR/altın ağırlığını tercih edin.",
                    key,
                ))

    # ── 5) Kart başlığı vs sinyal ───────────────────────────────
    for v in varliklar:
        olumlu = any(w in v.baslik.lower() for w in ("öneriyoruz", "alınabilir", "exposure"))
        olumsuz = v.sinyal in ("KACIN", "AZALT")
        if olumlu and olumsuz:
            _ekle(bulgular, DenetimBulgusu(
                "KRITIK", "sinyal",
                f"{v.ad}: metin ile sinyal çelişiyor",
                f"Başlık: *{v.baslik}*",
                f"Sinyal rozeti: **{v.sinyal_etiket}**.",
                "Bu karttaki metne değil **sinyal rozetine** güvenin.",
                v.anahtar,
            ))

    # ── 6) Öncelik listesi tutarlılığı ──────────────────────────
    if oncelik:
        for ad in oncelik:
            v = next((x for x in varliklar if x.ad == ad), None)
            if v and v.sinyal in ("KACIN", "AZALT"):
                _ekle(bulgular, DenetimBulgusu(
                    "KRITIK", "sinyal",
                    "Öncelik listesinde çelişkili varlık",
                    f"Üst özet **{ad}** güçlü öneri diyor.",
                    f"Kart sinyali: **{v.sinyal_etiket}**.",
                    "Öncelik listesini yok sayın; ilgili kartın sinyaline bakın.",
                    v.anahtar,
                ))

    # ── 7) Makro bağlam vs rejim ────────────────────────────────
    if baglam:
        tl_ctx = next((p for p in baglam.parcalar if "TL mevduat" in p.baslik), None)
        if tl_ctx and rejim == "TL_FIRSAT" and "sağlanmıyor" in tl_ctx.beklenti:
            _ekle(bulgular, DenetimBulgusu(
                "UYARI", "mantik",
                "TL rejim etiketi vs bağlam metni",
                f"Rejim motoru: **{tahsis.rejim.etiket}**.",
                "Makro bağlam: TL fırsat koşulları **tam sağlanmıyor** diyor.",
                "Rejim etiketi ile bağlam farklı kriter kullanıyor — **her ikisini de okuyun**.",
            ))

        fed_ctx = next((p for p in baglam.parcalar if "Fed" in p.baslik), None)
        fed_snap = snap.veri.fed_faizi
        if fed_ctx and fed_snap:
            import re
            m = re.search(r"%([\d.]+)", fed_ctx.canli)
            if m:
                fed_canli = float(m.group(1))
                if abs(fed_canli - fed_snap) > 0.8:
                    _ekle(bulgular, DenetimBulgusu(
                        "UYARI", "veri",
                        "Fed faizi kaynakları arasında fark",
                        f"Portföy motoru Fed: **%{fed_snap:.2f}**.",
                        f"Makro bağlam (tahvil proxy): **%{fed_canli:.2f}**.",
                        "Demo modda Fed sabit kalabilir; **Canlı veri** modunda tekrar kontrol edin.",
                        "usd_cash",
                    ))

    # ── 8) Portföy toplamı ───────────────────────────────────────
    toplam = sum(tahsis.agirliklar.values())
    if abs(toplam - 1.0) > 0.02:
        _ekle(bulgular, DenetimBulgusu(
            "UYARI", "mantik",
            "Portföy ağırlıkları toplamı sapma",
            f"Ağırlıklar toplamı **%{toplam*100:.1f}** (beklenen %100).",
            "Normalizasyon veya yuvarlama hatası olabilir.",
            "Tahsis tablosunu yenileyin; sapma devam ederse bildirin.",
        ))

    # ── 9) CDS eşik vs rejim ────────────────────────────────────
    if cds is not None:
        if cds > 280 and rejim not in ("EM_STRES", "KRIZ", "ENFLASYON_KORUMA"):
            _ekle(bulgular, DenetimBulgusu(
                "UYARI", "rejim",
                "CDS yüksek ama rejim sakin görünüyor",
                f"CDS **{cds:.0f} bp** (>280 stres eşiği).",
                f"Rejim: **{tahsis.rejim.etiket}**.",
                "Diğer göstergeler (VIX, rezerv) stresi dengelemiş olabilir — yine de temkinli olun.",
            ))
        if cds < 250 and rejim == "EM_STRES":
            _ekle(bulgular, DenetimBulgusu(
                "UYARI", "rejim",
                "EM stres rejimi düşük CDS ile",
                f"CDS **{cds:.0f} bp** — normal bandında.",
                f"Rejim: **{tahsis.rejim.etiket}** (VIX/rezerv tetiklemiş olabilir).",
                "Stres rejimi CDS dışı faktörlerden geliyor; kartları birlikte okuyun.",
            ))

    # ── 10) Altın: düşüş trendi vs güçlü alım ───────────────────
    gold_v = _varlik_bul(varliklar, "gold")
    if gold_v and gold_v.sinyal in ("GUCLU_AL", "AL") and baglam:
        alt_ctx = next((p for p in baglam.parcalar if "Altın" in p.baslik), None)
        if alt_ctx and "düşüş" in alt_ctx.beklenti.lower() and alt_ctx.ok in ("↘", "↓"):
            _ekle(bulgular, DenetimBulgusu(
                "BILGI", "sinyal",
                "Altın alım önerisi ama kısa vade düşüşte",
                f"Danışman: **{gold_v.sinyal_etiket}** (makro koruma).",
                f"Teknik: {alt_ctx.trend} — momentum zayıf.",
                "Makro koruma için alım mantıklı; **kademeli** girin, tek seferde almayın.",
                "gold",
            ))

    # ── Özet ────────────────────────────────────────────────────
    kritik = sum(1 for b in bulgular if b.seviye == "KRITIK")
    uyari = sum(1 for b in bulgular if b.seviye == "UYARI")
    if kritik:
        ozet = (
            f"**{kritik} kritik** ve **{uyari} uyarı** bulundu. "
            "Aşağıdaki çelişkileri okumadan işlem yapmayın."
        )
    elif uyari:
        ozet = f"**{uyari} uyarı** — veri güncelliği veya vade farkları var; dikkatli olun."
    else:
        ozet = "Kritik çelişki tespit edilmedi. Yine de yatırım tavsiyesi değildir."

    return DenetimRaporu(
        bulgular=bulgular,
        temiz=kritik == 0,
        kritik_sayisi=kritik,
        uyari_sayisi=uyari,
        ozet=ozet,
    )
