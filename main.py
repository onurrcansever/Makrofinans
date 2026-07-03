# -*- coding: utf-8 -*-
"""
Ana Betik
==========
Kullanım:
    python main.py                      -> canlı veri + çoklu varlık raporu
    python main.py --demo               -> demo verilerle
    python main.py --telegram           -> rapor + rejim değiştiyse alarm
    python main.py --alert-only         -> sadece rejim değiştiyse Telegram
    python main.py --legacy             -> eski TL/EUR 4 kapılı rapor
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
from macro_data import canli_snapshot, demo_snapshot


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
    args = parser.parse_args()

    snap = demo_snapshot() if args.demo else canli_snapshot()

    if args.legacy:
        sonuc = karar_ver(snap.veri)
        rapor = notifier.rapor_metni_olustur(snap.veri, sonuc)
        notifier.konsola_yazdir(rapor)
        if args.telegram:
            notifier.telegrama_gonder(rapor, config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)
        return

    tahsis = tahsis_hesapla(snap)
    rapor = notifier.portfoy_raporu_olustur(snap, tahsis)

    if args.alert_only:
        from alerts import rejim_degisti_mi
        if rejim_degisti_mi(tahsis):
            kontrol_ve_bildir(tahsis, tam_rapor=rapor, telegram=True)
            notifier.konsola_yazdir("Rejim değişti — Telegram alarmı gönderildi.")
        else:
            kontrol_ve_bildir(tahsis, telegram=False)
            notifier.konsola_yazdir("Rejim değişmedi — bildirim gönderilmedi.")
    else:
        notifier.konsola_yazdir(rapor)
        if args.telegram:
            kontrol_ve_bildir(tahsis, tam_rapor=rapor, telegram=True)
        else:
            kontrol_ve_bildir(tahsis, telegram=False)


if __name__ == "__main__":
    main()
