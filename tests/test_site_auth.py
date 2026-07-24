# -*- coding: utf-8 -*-
"""Site giriş kapısı — env ve şifre doğrulama."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from site_auth import (
    _check_password,
    _expected_password,
    site_password_configured,
)


class SiteAuthTest(unittest.TestCase):
    def test_unset_password_skips_gate(self):
        with patch.dict(os.environ, {}, clear=True):
            for key in ("MAKROFINANS_SITE_PASSWORD", "APP_PASSWORD"):
                os.environ.pop(key, None)
            self.assertFalse(site_password_configured())
            self.assertEqual(_expected_password(), "")

    def test_makrofinans_env_takes_precedence(self):
        with patch.dict(
            os.environ,
            {
                "MAKROFINANS_SITE_PASSWORD": " secret1 ",
                "APP_PASSWORD": "other",
            },
            clear=False,
        ):
            self.assertTrue(site_password_configured())
            self.assertEqual(_expected_password(), "secret1")

    def test_app_password_fallback(self):
        env = os.environ.copy()
        env.pop("MAKROFINANS_SITE_PASSWORD", None)
        env["APP_PASSWORD"] = "fallback"
        with patch.dict(os.environ, env, clear=True):
            self.assertTrue(site_password_configured())
            self.assertEqual(_expected_password(), "fallback")

    def test_check_password_constant_time_match(self):
        with patch.dict(os.environ, {"MAKROFINANS_SITE_PASSWORD": "test123"}, clear=False):
            self.assertTrue(_check_password("test123"))
            self.assertFalse(_check_password("wrong"))
            self.assertFalse(_check_password(""))


if __name__ == "__main__":
    unittest.main()
