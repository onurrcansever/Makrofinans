# -*- coding: utf-8 -*-
"""
Ana Betik
==========
Kullanım:
    python main.py                      -> canlı veri + çoklu varlık raporu
    python main.py --demo               -> demo verilerle
    python main.py --telegram           -> rapor + rejim değiştiyse alarm
    python main.py --sinyal-alarm       -> AL/SAT değiştiyse Telegram/WhatsApp
    python main.py --sinyal-alarm --notify  -> bildirim kanallarına gönder
    python main.py --ozet-alarm --notify    -> kısa özet (rejim+varlık+AL) tek mesaj
    python main.py --alert-only         -> sadece rejim değiştiyse Telegram
    python main.py --evds-test          -> EVDS API key doğrulama
    python main.py --cds-durum          -> CDS kaynaklarını listele
    python main.py --cds-guncelle       -> Bloomberg + Investing CDS çek
    python backtest.py --months 12      -> geçmiş simülasyon
"""
import argparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import config
import notifier
from alerts import kontrol_ve_bildir
from allocation_engine import tahsis_hesapla
from decision_engine import karar_ver
from investor_profile import YatirimProfili
from macro_data import canli_snapshot, demo_snapshot


def _profil_env() -> YatirimProfili:
    return YatirimProfili(risk=config.INVESTOR_RISK, vade=config.INVESTOR_VADE)


def main():
    parser = argparse.ArgumentParser(description="Makro Portföy Asistanı")
    parser.add_argument("--demo", action="store_true", help="Örnek verilerle çalıştır")
    parser.add_argument("--legacy", action="store_true", help="Eski TL/EUR 4 kapılı rapor")
    parser.add_argument("--telegram", action="store_true", help="Telegram'a gönder")
    parser.add_argument(
        "--alert-only",
        action="store_true",
        help="Rejim değiştiyse Telegram alarmı; değişmediyse sessiz kal",
    )
    parser.add_argument(
        "--sinyal-alarm",
        action="store_true",
        help="Hisse AL/SAT sinyalleri değiştiyse bildir (Telegram/WhatsApp)",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Bildirim gönder (.env BILDIRIM_KANALI: telegram/whatsapp/both)",
    )
    parser.add_argument(
        "--ozet-alarm",
        action="store_true",
        help="Kısa WhatsApp özeti (varlık+AL hisse/ETF); OZET_ALARM_HER_ZAMAN=1 ile günde 4 kez",
    )
    parser.add_argument(
        "--her-zaman",
        action="store_true",
        help="Özet alarm: değişiklik olmasa da gönder",
    )
    parser.add_argument(
        "--sadece-degisim",
        action="store_true",
        help="Özet alarm: yalnızca rejim/sinyal/vade değişince gönder",
    )
    parser.add_argument(
        "--evds-test",
        action="store_true",
        help="EVDS API key doğrulama (enflasyon, TCMB, CDS, rezerv)",
    )
    parser.add_argument(
        "--cds-durum",
        action="store_true",
        help="CDS kaynaklarını listele (Investing, WGB, manual)",
    )
    parser.add_argument(
        "--cds-guncelle",
        action="store_true",
        help="CDS kaynaklarını çek (Bloomberg Terminal + Investing.com)",
    )
    parser.add_argument(
        "--cds-guncelle-bildir",
        action="store_true",
        help="--cds-guncelle ile birlikte: çelişki/sıçrama varsa Telegram/WhatsApp bildir",
    )
    args = parser.parse_args()

    if args.cds_durum:
        from cds_sync import cds_durum_metni
        notifier.konsola_yazdir(cds_durum_metni())
        raise SystemExit(0)

    if args.cds_guncelle:
        from cds_sync import cds_guncelleme_calistir
        sonuc = cds_guncelleme_calistir(
            bildir=args.cds_guncelle_bildir or args.telegram or args.notify,
        )
        for k in sonuc.kaynaklar:
            if k.deger is not None:
                notifier.konsola_yazdir(f"  {k.ad}: {k.deger:.2f} bp — {k.kaynak}")
            else:
                notifier.konsola_yazdir(f"  {k.ad}: — ({k.hata or 'yok'})")
        if sonuc.efektif is not None:
            notifier.konsola_yazdir(f"\n→ Rejim CDS: {sonuc.efektif:.0f} bp ({sonuc.efektif_kaynak[:70]})")
        for u in sonuc.uyarilar:
            notifier.konsola_yazdir(f"  ⚠ {u}")
        raise SystemExit(0)

    if args.evds_test:
        from data_sources import evds_dogrula
        sonuc = evds_dogrula(config.EVDS_API_KEY)
        for m in sonuc["mesajlar"]:
            notifier.konsola_yazdir(m)
        if sonuc["ok"]:
            notifier.konsola_yazdir(
                "\nÖnbelleği temizleyip canlı veri çekmek için uygulamayı yeniden başlatın "
                "(market_cache.db eski proxy veriyi tutabilir)."
            )
        raise SystemExit(0 if sonuc["ok"] else 1)

    snap = demo_snapshot() if args.demo else canli_snapshot()

    if args.ozet_alarm:
        from ozet_bildirim import kontrol_ozet_ve_bildir

        her_zaman = config.OZET_ALARM_HER_ZAMAN
        if args.her_zaman:
            her_zaman = True
        if args.sadece_degisim:
            her_zaman = False

        ok, olaylar, rejim_degisti = kontrol_ozet_ve_bildir(
            snap, bildir=args.notify or args.telegram, her_zaman=her_zaman
        )
        if rejim_degisti:
            notifier.konsola_yazdir("Rejim değişti.")
        else:
            notifier.konsola_yazdir("Rejim aynı.")
        for tip, sym, h in olaylar:
            notifier.konsola_yazdir(f"  {tip}: {sym} ({h.ad}) skor={h.skor:.0f}")
        if ok:
            notifier.konsola_yazdir(
                "Günlük özet bildirimi gönderildi." if her_zaman and not olaylar and not rejim_degisti
                else "Özet bildirim gönderildi."
            )
        elif olaylar or rejim_degisti or her_zaman:
            if args.notify or args.telegram:
                notifier.konsola_yazdir("Bildirim gönderilemedi — .env ayarlarını kontrol edin.")
        else:
            notifier.konsola_yazdir("Değişiklik yok — bildirim gönderilmedi.")
        return

    if args.sinyal_alarm:
        from signal_alerts import kontrol_sinyal_ve_bildir
        ok, olaylar = kontrol_sinyal_ve_bildir(snap, bildir=args.notify or args.telegram)
        if olaylar:
            for tip, sym, h in olaylar:
                notifier.konsola_yazdir(f"  {tip}: {sym} ({h.ad}) skor={h.skor:.0f}")
            if ok:
                notifier.konsola_yazdir(f"Bildirim gönderildi ({len(olaylar)} olay).")
            elif args.notify or args.telegram:
                notifier.konsola_yazdir("Bildirim gönderilemedi — .env ayarlarını kontrol edin.")
            else:
                notifier.konsola_yazdir(
                    f"{len(olaylar)} olay bulundu — göndermek için --notify ekleyin."
                )
        else:
            notifier.konsola_yazdir("Yeni AL/SAT sinyali yok.")
        return

    if args.legacy:
        sonuc = karar_ver(snap.veri)
        rapor = notifier.rapor_metni_olustur(snap.veri, sonuc)
        notifier.konsola_yazdir(rapor)
        if args.telegram:
            notifier.telegrama_gonder(rapor, config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)
        return

    tahsis = tahsis_hesapla(snap, _profil_env())
    rapor = notifier.portfoy_raporu_olustur(snap, tahsis)

    if args.alert_only:
        from alerts import rejim_degisti_mi
        if rejim_degisti_mi(tahsis):
            kontrol_ve_bildir(tahsis, tam_rapor=rapor, bildir=True)
            notifier.konsola_yazdir("Rejim değişti — bildirim gönderildi.")
        else:
            kontrol_ve_bildir(tahsis, bildir=False)
            notifier.konsola_yazdir("Rejim değişmedi — bildirim gönderilmedi.")
    else:
        notifier.konsola_yazdir(rapor)
        if args.telegram:
            kontrol_ve_bildir(tahsis, tam_rapor=rapor, telegram=True)
        else:
            kontrol_ve_bildir(tahsis, telegram=False)


if __name__ == "__main__":
    main()
