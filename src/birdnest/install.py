"""One-shot setup of the Chrome native-messaging host (DESIGN.md 5.3)."""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HOST_NAME = "com.birdnest.host"
MANIFEST_TEMPLATE = "manifest.template.json"

# Chromium-family browsers that read the same manifest format.
BROWSER_DIRS = {
    "chrome": "Google/Chrome",
    "chrome-beta": "Google/Chrome Beta",
    "chrome-canary": "Google/Chrome Canary",
    "chromium": "Chromium",
    "brave": "BraveSoftware/Brave-Browser",
    "edge": "Microsoft Edge",
}


def host_manifest_dir(browser: str = "chrome") -> Path:
    try:
        leaf = BROWSER_DIRS[browser]
    except KeyError:
        raise ValueError(f"unknown browser {browser!r}; "
                         f"choose from {', '.join(sorted(BROWSER_DIRS))}")
    return (Path.home() / "Library" / "Application Support" / leaf
            / "NativeMessagingHosts")


def extension_id_from_der(der: bytes) -> str:
    """Chrome derives the ID from the public key: first 128 bits of its
    SHA-256, hex, with 0-f remapped onto a-p."""
    digest = hashlib.sha256(der).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def ensure_keypair(ext_dir: Path) -> tuple[str, str]:
    """Return (base64 public key for manifest, derived extension ID).

    Pinning `key` in the extension manifest keeps the ID stable. Without it an
    unpacked extension's ID follows its directory path, and the host manifest's
    allowed_origins silently stops matching after a move (DESIGN.md 5.3).
    """
    key_pem = ext_dir / "key.pem"
    if not key_pem.exists():
        subprocess.run(["openssl", "genrsa", "-out", str(key_pem), "2048"],
                       check=True, capture_output=True)
        key_pem.chmod(0o600)
    der = subprocess.run(
        ["openssl", "rsa", "-in", str(key_pem), "-pubout", "-outform", "DER"],
        check=True, capture_output=True).stdout
    return base64.b64encode(der).decode(), extension_id_from_der(der)


def render_manifest(ext_dir: Path, pubkey_b64: str) -> Path:
    """Render `manifest.json` from the tracked template plus this machine's key.

    The rendered file is gitignored and the template carries no `key`: a shared
    one would hand every clone an identity that is not its own, and it is the
    reason this is generated rather than edited in place.
    """
    manifest = json.loads((ext_dir / MANIFEST_TEMPLATE).read_text())
    manifest["key"] = pubkey_b64
    out = ext_dir / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n")
    return out


def install(ext_dir: Path, browser: str = "chrome") -> dict:
    if sys.platform != "darwin":
        raise RuntimeError("install-host currently supports macOS only")

    # Before ensure_keypair, so a wrong --extension-dir does not get a key.pem.
    template = ext_dir / MANIFEST_TEMPLATE
    if not template.exists():
        raise FileNotFoundError(f"no extension manifest template at {template}")

    pubkey_b64, ext_id = ensure_keypair(ext_dir)
    manifest_path = render_manifest(ext_dir, pubkey_b64)

    exe = Path(sys.executable).parent / "birdnest-host"
    if not exe.exists():
        raise FileNotFoundError(
            f"birdnest-host not found at {exe}; run `uv sync` first")

    target_dir = host_manifest_dir(browser)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{HOST_NAME}.json"
    target.write_text(json.dumps({
        "name": HOST_NAME,
        "description": "BirdNest native helper",
        "path": str(exe),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{ext_id}/"],
    }, indent=2) + "\n")

    return {"extension_id": ext_id, "host_manifest": str(target),
            "extension_manifest": str(manifest_path),
            "executable": str(exe), "extension_dir": str(ext_dir)}
