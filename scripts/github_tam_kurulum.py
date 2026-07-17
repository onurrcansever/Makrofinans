#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Actions tam kurulum — git credential ile:
  1. VARLIKLARIM_JSON (+ cache) secret yükle
  2. docs/ci_workflows → .github/workflows (Contents API)
  3. gunluk-rapor workflow_dispatch tetikle
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.getenv("GITHUB_REPO", "onurrcansever/Makrofinans")
WORKFLOWS_SRC = os.path.join(ROOT, "docs", "ci_workflows")
WORKFLOWS = (
    "gunluk-rapor.yml",
    "sinyal-alarm.yml",
    "signal-engine-ci.yml",
)


def _git_token() -> str:
    for src in (
        os.getenv("GITHUB_TOKEN"),
        os.getenv("GITHUB_PAT"),
    ):
        if src and str(src).strip():
            return str(src).strip()
    proc = subprocess.run(
        ["git", "credential", "fill"],
        input=b"protocol=https\nhost=github.com\n\n",
        capture_output=True,
        cwd=ROOT,
    )
    if proc.returncode != 0:
        raise RuntimeError("git credential bulunamadı")
    for line in proc.stdout.decode().splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise RuntimeError("GitHub token alınamadı")


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _workflow_dosya_yukle(token: str, fname: str) -> bool:
    src = os.path.join(WORKFLOWS_SRC, fname)
    dest = f".github/workflows/{fname}"
    if not os.path.isfile(src):
        print(f"  ⚠ kaynak yok: {src}")
        return False
    with open(src, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode("ascii")
    url = f"https://api.github.com/repos/{REPO}/contents/{dest}"
    r = requests.get(url, headers=_headers(token), timeout=30)
    sha = r.json().get("sha") if r.status_code == 200 else None
    payload = {
        "message": f"ci: {fname} güncelle — portföy restore + pozisyon tablosu",
        "content": content_b64,
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha
    r2 = requests.put(url, headers=_headers(token), json=payload, timeout=30)
    if r2.status_code in (200, 201):
        print(f"  ✓ {dest}")
        return True
    print(f"  ✗ {dest}: {r2.status_code} {r2.text[:200]}")
    return False


def _workflow_tetikle(token: str, workflow_file: str = "gunluk-rapor.yml") -> bool:
    url = f"https://api.github.com/repos/{REPO}/actions/workflows/{workflow_file}/dispatches"
    r = requests.post(
        url,
        headers=_headers(token),
        json={"ref": "main"},
        timeout=30,
    )
    if r.status_code == 204:
        print(f"  ✓ workflow_dispatch → {workflow_file}")
        return True
    print(f"  ✗ dispatch {workflow_file}: {r.status_code} {r.text[:200]}")
    return False


def main() -> int:
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
    except ImportError:
        pass

    print("=== GitHub Actions tam kurulum ===\n")
    try:
        token = _git_token()
    except RuntimeError as exc:
        print(f"[HATA] {exc}")
        return 1

    # 1. Secrets
    print("1) Secret yükleme...")
    os.environ["GITHUB_TOKEN"] = token
    from scripts.portfoy_github_sync import main as sync_main
    old_argv = sys.argv
    sys.argv = ["portfoy_github_sync.py"]
    rc = sync_main()
    sys.argv = old_argv
    if rc != 0:
        print("[HATA] Secret yükleme başarısız")
        return rc

    # 2. Workflows
    print("\n2) Workflow dosyaları...")
    ok = 0
    for wf in WORKFLOWS:
        if _workflow_dosya_yukle(token, wf):
            ok += 1
    if ok == 0:
        print("[UYARI] Workflow API güncellenemedi — PAT workflow scope gerekebilir")
        print("        Yedek: data/ci_* repo sync (portföy checkout ile gelir)")

    # 2b. Repo sync (workflow olmasa da çalışır)
    print("\n2b) Repo portföy sync (data/ci_*)...")
    from scripts.portfoy_github_sync import REPO_SYNC_DOSYALAR, _bul
    from scripts.github_secrets_util import repo_dosya_yukle
    repo_ok = 0
    for fname, repo_path in REPO_SYNC_DOSYALAR:
        path = _bul(fname)
        if not path:
            continue
        try:
            sha = repo_dosya_yukle(
                repo_path,
                path,
                message=f"sync: {repo_path} — CI portföy",
                repo=REPO,
                token=token,
            )
            print(f"  ✓ {repo_path} ({sha[:7] if sha else 'ok'})")
            repo_ok += 1
        except Exception as exc:
            print(f"  ✗ {repo_path}: {exc}")
    if repo_ok == 0:
        print("[HATA] Repo sync başarısız — portföy CI'da boş kalır")
        return 1

    # 3. Trigger test run
    print("\n3) Test workflow tetikleme...")
    time.sleep(2)
    _workflow_tetikle(token)

    print("\n=== Tamamlandı ===")
    print("Actions sekmesinden 'Makrofinans Alarmları' run'ını izleyin (~2-3 dk).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
