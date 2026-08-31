"""
Loads all runtime configuration for the simplefix-based FIX session from
environment variables (via .env). No credentials, hosts, or ports should
ever be hardcoded elsewhere in the codebase - everything comes through this
module so the same code runs unchanged against TT UAT (or, eventually and
carefully, production) just by swapping .env values.

Note: the FIX credential env vars are named TT_USERNAME / TT_PASSWORD
rather than USERNAME / PASSWORD - Windows sets an OS-level USERNAME env var
to the logged-in user by default, which would silently shadow a FIX
username if we reused that name.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    sender_comp_id: str
    target_comp_id: str
    tt_username: str
    tt_password: str
    host: str
    port: int
    fix_version: str
    heartbeat_interval: int
    default_symbol: str


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy config.example.env to .env and fill it in."
        )
    return value


def load_settings() -> Settings:
    return Settings(
        sender_comp_id=_require("SENDER_COMP_ID"),
        target_comp_id=_require("TARGET_COMP_ID"),
        tt_username=os.getenv("TT_USERNAME", ""),
        tt_password=os.getenv("TT_PASSWORD", ""),
        host=_require("HOST"),
        port=int(_require("PORT")),
        fix_version=os.getenv("FIX_VERSION", "FIX.4.4"),
        heartbeat_interval=int(os.getenv("HEARTBEAT_INTERVAL", "30")),
        default_symbol=os.getenv("DEFAULT_SYMBOL", "ES"),
    )
