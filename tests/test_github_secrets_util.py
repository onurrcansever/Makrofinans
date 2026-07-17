# -*- coding: utf-8 -*-
"""GitHub secrets util — encrypt smoke test."""
from __future__ import annotations

import base64
import unittest

from scripts.github_secrets_util import _encrypt_secret


class GithubSecretsUtilTest(unittest.TestCase):
    def test_encrypt_roundtrip_format(self):
        # GitHub test key (libsodium docs example — sadece format testi)
        from nacl.public import PrivateKey, PublicKey
        from nacl import encoding

        sk = PrivateKey.generate()
        pk_b64 = sk.public_key.encode(encoder=encoding.Base64Encoder).decode()
        enc = _encrypt_secret(pk_b64, "hello")
        self.assertTrue(len(base64.b64decode(enc)) > 0)


if __name__ == "__main__":
    unittest.main()
