# -*- coding: utf-8 -*-
"""GitHub Actions repository secrets — yükleme (PyNaCl sealed box)."""
from __future__ import annotations

import base64
import os
from typing import Optional

import requests

try:
    from nacl import encoding, public
except ImportError as exc:
    raise ImportError("pynacl gerekli: pip install pynacl") from exc


def _repo_slug(explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit.strip().strip("/")
    env = os.getenv("GITHUB_REPOSITORY", "").strip()
    if env and "/" in env:
        return env
    remote = os.getenv("GITHUB_REPO", "onurrcansever/Makrofinans")
    return remote


def _token(token: Optional[str] = None) -> str:
    tok = (token or os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PAT") or "").strip()
    if not tok:
        raise ValueError(
            "GITHUB_TOKEN veya GITHUB_PAT gerekli (.env). "
            "İzinler: repo, admin:repo_hook (secret yazma)."
        )
    return tok


def _encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    pk = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
    sealed = public.SealedBox(pk).encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(sealed).decode("ascii")


def secret_yukle(
    name: str,
    value: str,
    *,
    repo: Optional[str] = None,
    token: Optional[str] = None,
) -> None:
    """Repository secret oluştur/güncelle."""
    slug = _repo_slug(repo)
    tok = _token(token)
    headers = {
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    pk_url = f"https://api.github.com/repos/{slug}/actions/secrets/public-key"
    r = requests.get(pk_url, headers=headers, timeout=30)
    r.raise_for_status()
    key_id = r.json()["key_id"]
    key_b64 = r.json()["key"]

    payload = {
        "encrypted_value": _encrypt_secret(key_b64, value),
        "key_id": key_id,
    }
    put_url = f"https://api.github.com/repos/{slug}/actions/secrets/{name}"
    r2 = requests.put(put_url, headers=headers, json=payload, timeout=30)
    r2.raise_for_status()


def dosya_base64_yukle(
    secret_name: str,
    path: str,
    *,
    repo: Optional[str] = None,
    token: Optional[str] = None,
) -> int:
    """Dosyayı base64 encode edip secret olarak yükle. Dönüş: ham byte boyutu."""
    with open(path, "rb") as f:
        raw = f.read()
    if not raw.strip():
        raise ValueError(f"Boş dosya: {path}")
    b64 = base64.b64encode(raw).decode("ascii")
    secret_yukle(secret_name, b64, repo=repo, token=token)
    return len(raw)
