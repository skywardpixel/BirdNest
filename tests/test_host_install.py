import json
import struct
import subprocess
from pathlib import Path

import pytest
from birdnest.host import handle
from birdnest.install import extension_id_from_der

ROOT = Path(__file__).resolve().parents[1]


def test_extension_id_is_a_valid_chrome_id():
    ext_id = extension_id_from_der(b"some der bytes")
    assert len(ext_id) == 32
    assert all("a" <= c <= "p" for c in ext_id)


def test_extension_id_is_deterministic():
    assert extension_id_from_der(b"x") == extension_id_from_der(b"x")
    assert extension_id_from_der(b"x") != extension_id_from_der(b"y")


@pytest.mark.parametrize("payload", [
    {"action": "save"},                      # no id at all
    {"action": "save", "tweet_id": "abc"},   # non-numeric
    {"action": "save", "tweet_id": ""},
])
def test_malformed_ids_are_rejected_before_any_network(payload):
    from birdnest.config import Config
    res = handle(payload, Config())
    assert res["ok"] is False
    assert "tweet_id" in res["error"]


def test_stdio_framing_round_trip():
    """The host must emit a length-prefixed frame and nothing on stderr —
    a stray print would corrupt the native-messaging stream."""
    exe = ROOT / ".venv" / "bin" / "birdnest-host"
    if not exe.exists():
        pytest.skip("run `uv sync` first")
    msg = json.dumps({"action": "save", "tweet_id": "nope"}).encode()
    proc = subprocess.run([str(exe)], input=struct.pack("@I", len(msg)) + msg,
                          capture_output=True, timeout=60)
    (n,) = struct.unpack("@I", proc.stdout[:4])
    reply = json.loads(proc.stdout[4:4 + n])
    assert reply["ok"] is False
    assert proc.stderr.strip() == b""


def test_ffmpeg_found_without_a_useful_path(monkeypatch):
    """Chrome spawns the native host with PATH=/usr/bin:/bin:/usr/sbin:/sbin,
    so shutil.which() misses Homebrew. Regression for the 'ffmpeg is not
    installed' failure seen from the extension while ffmpeg was installed."""
    from birdnest import postprocess

    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    if not any(Path(d, "ffmpeg").exists() for d in postprocess.CANDIDATE_DIRS):
        pytest.skip("no ffmpeg in any candidate directory on this machine")
    assert postprocess.find_ffmpeg() is not None
    assert postprocess.have_ffmpeg()


def test_ensure_on_path_prepends_and_is_idempotent(monkeypatch):
    import os

    from birdnest import postprocess

    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    if postprocess.find_ffmpeg() is None:
        pytest.skip("ffmpeg not available")
    postprocess.ensure_on_path()
    first = os.environ["PATH"]
    postprocess.ensure_on_path()
    assert os.environ["PATH"] == first        # no unbounded growth
    assert "ffmpeg" in str(postprocess.find_ffmpeg())
