# -*- coding: utf-8 -*-
"""
Bloomberg CDS — Bloomberg Terminal (BLPAPI) üzerinden otomatik çekim.
Ücretsiz web/API yok; Terminal açık ve blpapi kurulu olmalı.
"""
from __future__ import annotations

import os
from typing import List, Optional, Tuple

DEFAULT_TICKERS = (
    "TRGV5YUSAC Corp",
    "TURKEY CDS USD SR 5Y D14 Corp",
    "TURKEY CDS USD SR 5Y Corp",
)


def _blp_px_last(ticker: str) -> Optional[float]:
    try:
        import blpapi
    except ImportError:
        return None

    host = os.getenv("BLOOMBERG_HOST", "localhost")
    port = int(os.getenv("BLOOMBERG_PORT", "8194"))

    opts = blpapi.SessionOptions()
    opts.setServerHost(host)
    opts.setServerPort(port)

    session = blpapi.Session(opts)
    try:
        if not session.start():
            return None
        if not session.openService("//blp/refdata"):
            return None
        service = session.getService("//blp/refdata")
        req = service.createRequest("ReferenceDataRequest")
        req.append("securities", ticker)
        req.append("fields", "PX_LAST")
        req.append("fields", "LAST_UPDATE_DT")
        session.sendRequest(req)

        while True:
            event = session.nextEvent(5000)
            for msg in event:
                if msg.messageType() in (
                    blpapi.Names.REFERENCE_DATA_RESPONSE,
                    "ReferenceDataResponse",
                ):
                    sec_data = msg.getElement("securityData")
                    for i in range(sec_data.numValues()):
                        sd = sec_data.getValueAsElement(i)
                        if sd.hasElement("fieldData"):
                            fd = sd.getElement("fieldData")
                            if fd.hasElement("PX_LAST"):
                                return float(fd.getElement("PX_LAST").getValue())
            if event.eventType() == blpapi.Event.RESPONSE:
                break
    except Exception as e:
        print(f"[UYARI] Bloomberg BLPAPI ({ticker}): {e}")
    finally:
        try:
            session.stop()
        except Exception:
            pass
    return None


def turkiye_cds_5y_bloomberg_blp() -> Optional[Tuple[float, str]]:
    """
    Bloomberg Terminal — PX_LAST (bp).
    BLOOMBERG_CDS_TICKER ile özelleştirilebilir.
    """
    if os.getenv("BLOOMBERG_CDS_KAPALI", "0").strip() in ("1", "true", "yes"):
        return None

    tickers: List[str] = []
    env_t = os.getenv("BLOOMBERG_CDS_TICKER", "").strip()
    if env_t:
        tickers.append(env_t)
    for t in DEFAULT_TICKERS:
        if t not in tickers:
            tickers.append(t)

    for ticker in tickers:
        val = _blp_px_last(ticker)
        if val is not None and 50.0 < val < 2000.0:
            return val, f"Bloomberg Terminal BLPAPI ({ticker})"
    return None


def bloomberg_terminal_erisimli() -> bool:
    """Terminal/BLPAPI erişimi var mı (hızlı kontrol)."""
    try:
        import blpapi
    except ImportError:
        return False
    host = os.getenv("BLOOMBERG_HOST", "localhost")
    port = int(os.getenv("BLOOMBERG_PORT", "8194"))
    opts = blpapi.SessionOptions()
    opts.setServerHost(host)
    opts.setServerPort(port)
    session = blpapi.Session(opts)
    try:
        return session.start()
    except Exception:
        return False
    finally:
        try:
            session.stop()
        except Exception:
            pass
