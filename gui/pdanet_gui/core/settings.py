"""Persistent user settings (JSON in the XDG config dir). No secrets are stored."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields

LANGUAGES = ("system", "en", "fa")
THEMES = ("system", "light", "dark")
POLL_CHOICES = (1, 2, 5)


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "pdanet-linux")


@dataclass
class Settings:
    language: str = "system"
    theme: str = "system"
    launch_at_login: bool = False
    start_minimized: bool = False
    auto_connect: bool = False
    auto_restore: bool = False
    lookup_public_ip: bool = True
    poll_seconds: int = 2

    def validate(self) -> "Settings":
        if self.language not in LANGUAGES:
            self.language = "system"
        if self.theme not in THEMES:
            self.theme = "system"
        if self.poll_seconds not in POLL_CHOICES:
            self.poll_seconds = 2
        for name in ("launch_at_login", "start_minimized", "auto_connect",
                     "auto_restore", "lookup_public_ip"):
            if not isinstance(getattr(self, name), bool):
                setattr(self, name, getattr(Settings, name))
        return self


def settings_path() -> str:
    return os.path.join(config_dir(), "settings.json")


def load(path: str | None = None) -> Settings:
    path = path or settings_path()
    defaults = Settings()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return defaults
    if not isinstance(data, dict):
        return defaults
    known = {f.name for f in fields(Settings)}
    for key, value in data.items():
        if key in known:
            setattr(defaults, key, value)
    return defaults.validate()


def save(settings: Settings, path: str | None = None) -> None:
    path = path or settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".settings-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(asdict(settings.validate()), fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
