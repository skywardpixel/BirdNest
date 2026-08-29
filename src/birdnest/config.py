"""Defaults and ~/.config/birdnest/config.toml (DESIGN.md 4)."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_data_dir

APP = "BirdNest"


def config_path() -> Path:
    return Path(user_config_dir("birdnest")) / "config.toml"


@dataclass
class Config:
    out_dir: Path = field(default_factory=lambda: Path.home() / "Downloads" / APP)
    # Clipboard copies must outlive the process: a paste minutes later
    # re-resolves the path, so these never go in a temp dir (DESIGN.md 5.5).
    cache_dir: Path = field(default_factory=lambda: Path(user_cache_dir(APP)))
    data_dir: Path = field(default_factory=lambda: Path(user_data_dir("birdnest")))
    quality: str = "best"
    template: str = "{author}_{id}"
    cookies_from_browser: str | None = None
    gif_fps: int = 15
    gif_width: int = 480

    @property
    def db_path(self) -> Path:
        return self.data_dir / "manifest.db"

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        p = config_path()
        if not p.exists():
            return cfg
        data = tomllib.loads(p.read_text())
        for key, value in data.items():
            if not hasattr(cfg, key):
                continue
            setattr(cfg, key, Path(value).expanduser()
                    if key.endswith("_dir") else value)
        return cfg
