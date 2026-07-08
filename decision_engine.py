# -*- coding: utf-8 -*-
"""
Karar Motoru
=============
Sohbette tasarlanan 4 kapılı algoritmanın saf Python uygulaması.
Her fonksiyon şeffaftır: girdi + eşik + çıktı + gerekçe metni döner.
Böylece rapor, "neden bu öneri çıktı" sorusunu her zaman cevaplayabilir.
"""
from dataclasses import dataclass, field
from typing import List, Optional

import config
from breakeven import breakeven_eur_try, profil_mevduat_parametreleri
from siyasi_esik import esikler


@dataclass
class PiyasaVerisi:
    eur_try: Optional[float] = None
    usd_try: Optional[float] = None
    fed_faizi: Optional[float] = None
    tcmb_politika_faizi: Optional[float] = None
    tl_mevduat_brut_faiz: Optional[float] = None
    cds_5y_bp: Optional[float] = None
    rezerv_artiyor: Optional[bool] = None
    siyasi_risk_makale_sayisi: Optional[int] = None
    savas_risk_makale_sayisi: Optional[int] = None
    savas_risk_guvenilir: Optional[bool] = None
    tl_makro_risk_aktif: Optional[bool] = None
    tl_faiz_indirim_haber: Optional[int] = None
    tl_erken_secim_haber: Optional[int] = None
    tl_erken_secim_anormal: Optional[bool] = None


@dataclass
class KararSonucu:
    kapi1_gecti: bool
    kapi1_gerekce: str
    tavan_oran: float
    adimlar: List[str] = field(default_factory=list)
    tahsis_eur: float = 0.0
    tavsiye_metni: str = ""
    uyarilar: List[str] = field(default_factory=list)


def _breakeven_kur(eur_try: float) -> float:
    """Geriye dönük uyumluluk — profil_mevduat_parametreleri kullanın."""
    net_tl, gun, _ = profil_mevduat_parametreleri(config.KALAN_GUN)
    return breakeven_eur_try(eur_try, net_tl, gun)


def _cds_tavani(cds_bp: float) -> float:
    """Kapı 2: CDS eşiğine göre maksimum TL tahsis oranı."""
    for esik, oran in config.CDS_ESIK_TABLOSU:
        if cds_bp > esik:
            return oran
    return config.CDS_ESIK_TABLOSU[-1][1]


def karar_ver(veri: PiyasaVerisi, vade_gun: Optional[int] = None) -> KararSonucu:
    adimlar = []
    uyarilar = []

    # --- Kapı 1: Siyasi/jeopolitik risk ------------------------------
    kriz_var = False
    es = esikler()
    if veri.siyasi_risk_makale_sayisi is not None:
        kriz_var = veri.siyasi_risk_makale_sayisi >= es["kriz"]
        adimlar.append(
            f"Kapı 1 (siyasi risk): son {config.SIYASI_RISK_TARAMA_SAAT}s "
            f"{veri.siyasi_risk_makale_sayisi} haber "
            f"(kriz eşiği: {es['kriz']}, taban: {es['taban']}) -> "
            f"{'KRİZ MODU' if kriz_var else 'sakin'}"
        )
    else:
        uyarilar.append("Siyasi risk verisi çekilemedi — GDELT yedek değeri kullanılıyor.")

    if kriz_var:
        return KararSonucu(
            kapi1_gecti=False,
            kapi1_gerekce="Son 48 saatte siyasi risk eşiği aşıldı.",
            tavan_oran=0.0,
            adimlar=adimlar,
            tahsis_eur=0.0,
            tavsiye_metni=(
                "ÖNERİ: Pozisyon açma. Tüm varlığı EUR'da tutmaya devam edin. "
                "2 hafta sonra tekrar çalıştırın."
            ),
            uyarilar=uyarilar,
        )

    # --- Kapı 2: CDS eşiği --------------------------------------------
    if veri.cds_5y_bp is None:
        uyarilar.append("CDS verisi alınamadı — güvenlik gereği tavan %0 kabul edildi.")
        tavan = 0.0
        adimlar.append("Kapı 2 (CDS): veri yok, güvenlik gereği tavan %0 kabul edildi.")
    else:
        tavan = _cds_tavani(veri.cds_5y_bp)
        adimlar.append(f"Kapı 2 (CDS={veri.cds_5y_bp:.0f}bp): tavan -> %{tavan*100:.0f}")

    # --- Kapı 3: Kur / başabaş oranı (Yapı Kredi net faiz + profil vade günü) ---
    if veri.eur_try is not None:
        profil_gun = vade_gun or config.KALAN_GUN
        net_tl, gun_used, faiz_kaynak = profil_mevduat_parametreleri(
            profil_gun, veri.tl_mevduat_brut_faiz,
        )
        breakeven = breakeven_eur_try(veri.eur_try, net_tl, gun_used)
        oran = veri.eur_try / breakeven
        adimlar.append(
            f"Kapı 3 (kur/başabaş): spot={veri.eur_try:.2f}, "
            f"başabaş≈{breakeven:.2f}, oran={oran:.2f} "
            f"(net TL %{net_tl*100:.1f}, {gun_used} gün, {faiz_kaynak})"
        )
        if oran >= 1.0:
            tavan = tavan / 2
            adimlar.append("  -> oran >= 1, tavan yarıya indirildi.")
    else:
        uyarilar.append("EUR/TRY kuru çekilemedi.")

    # --- Kapı 4: Rezerv trendi ------------------------------------------
    if veri.rezerv_artiyor is False:
        tavan = tavan * config.REZERV_DUSUS_CARPANI
        adimlar.append(
            f"Kapı 4 (rezerv): son 4 haftada rezerv azalıyor -> "
            f"tavan ×{config.REZERV_DUSUS_CARPANI} = %{tavan*100:.1f}"
        )
    elif veri.rezerv_artiyor is True:
        adimlar.append("Kapı 4 (rezerv): son 4 haftada rezerv artıyor -> değişiklik yok.")
    else:
        onceki = tavan
        tavan = tavan * config.REZERV_BILINMIYOR_CARPANI
        adimlar.append(
            f"Kapı 4 (rezerv): veri yok -> temkin ×{config.REZERV_BILINMIYOR_CARPANI} "
            f"(%{onceki*100:.0f} -> %{tavan*100:.1f})"
        )
        uyarilar.append(
            "Rezerv trendi bilinmiyor — Kapı 4 temkinli çarpan uygulandı (EVDS key ile gerçek veri)."
        )

    # --- Kapı 1b: Jeopolitik / savaş riski -----------------------------
    if veri.savas_risk_makale_sayisi is not None:
        guven = veri.savas_risk_guvenilir if veri.savas_risk_guvenilir is not None else True
        if not guven:
            onceki = tavan
            tavan = tavan * 0.85
            adimlar.append(
                f"Kapı 1b (jeopolitik): tarama güvenilir değil -> tavan ×0.85 "
                f"(%{onceki*100:.0f} -> %{tavan*100:.1f})"
            )
            uyarilar.append(
                "Jeopolitik haber taraması boş veya erişilemedi — 'düşük risk' varsaymayın; "
                "Hürmüz/İran gündemini manuel kontrol edin."
            )
        elif veri.savas_risk_makale_sayisi >= config.SAVAS_RISK_YUKSEK_ESIGI:
            onceki = tavan
            tavan = tavan * config.SAVAS_TAVAN_CARPANI
            adimlar.append(
                f"Kapı 1b (jeopolitik): {veri.savas_risk_makale_sayisi} haber (yüksek) -> "
                f"tavan ×{config.SAVAS_TAVAN_CARPANI} (%{onceki*100:.0f} -> %{tavan*100:.1f})"
            )
        elif veri.savas_risk_makale_sayisi >= config.SAVAS_RISK_ESIGI:
            adimlar.append(
                f"Kapı 1b (jeopolitik): {veri.savas_risk_makale_sayisi} haber — "
                f"Orta Doğu/Hürmüz gündemde; temkinli pozisyon."
            )
        else:
            adimlar.append(
                f"Kapı 1b (jeopolitik): {veri.savas_risk_makale_sayisi} haber — düşük sayılıyor."
            )

    # --- Kapı 1d: TL makro haber (faiz indirimi beklentisi / erken seçim sıçraması) ---
    if veri.tl_makro_risk_aktif:
        onceki = tavan
        tavan = tavan * config.TL_MAKRO_TAVAN_CARPANI
        parcalar = []
        if veri.tl_faiz_indirim_haber is not None and (
            veri.tl_faiz_indirim_haber >= config.TL_MAKRO_FAIZ_ESIGI
        ):
            parcalar.append(f"faiz indirimi beklentisi {veri.tl_faiz_indirim_haber} haber")
        if veri.tl_erken_secim_anormal:
            parcalar.append(
                f"erken seçim anormal sıklık ({veri.tl_erken_secim_haber or 0} haber)"
            )
        neden = "; ".join(parcalar) if parcalar else "TL makro haber riski"
        adimlar.append(
            f"Kapı 1d (TL makro): {neden} -> tavan ×{config.TL_MAKRO_TAVAN_CARPANI} "
            f"(%{onceki*100:.0f} -> %{tavan*100:.1f})"
        )
    elif veri.tl_faiz_indirim_haber is not None or veri.tl_erken_secim_haber is not None:
        adimlar.append(
            f"Kapı 1d (TL makro): faiz beklentisi {veri.tl_faiz_indirim_haber or 0}, "
            f"erken seçim {veri.tl_erken_secim_haber or 0} — normal aralık."
        )

    # --- Mutlak tavan ------------------------------------------------
    tavan = min(tavan, config.MUTLAK_TAVAN)

    tahsis_eur = config.TOPLAM_EUR * tavan
    trans_tutar = tahsis_eur / config.TRANS_SAYISI if config.TRANS_SAYISI else tahsis_eur

    tavsiye = (
        f"ÖNERİ: Toplam {config.TOPLAM_EUR:,.0f} EUR üzerinden maksimum "
        f"{tahsis_eur:,.0f} EUR (%{tavan*100:.1f}) TL varlıklara ayrılabilir. "
        f"Bunu {config.TRANS_SAYISI} eşit tranşa bölün "
        f"(~{trans_tutar:,.0f} EUR/tranş), her tranş öncesi bu raporu "
        f"tekrar çalıştırıp koşulları yeniden test edin. "
        f"Kalan {config.TOPLAM_EUR - tahsis_eur:,.0f} EUR Euro mevduatında kalsın."
    )

    return KararSonucu(
        kapi1_gecti=True,
        kapi1_gerekce="Siyasi risk eşiği altında.",
        tavan_oran=tavan,
        adimlar=adimlar,
        tahsis_eur=tahsis_eur,
        tavsiye_metni=tavsiye,
        uyarilar=uyarilar,
    )
