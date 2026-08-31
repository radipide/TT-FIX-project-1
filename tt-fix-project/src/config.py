"""
Loads all runtime configuration for the simplefix-based FIX session from
environment variables (via .env). No credentials, hosts, or ports should
ever be hardcoded elsewhere in the codebase - everything comes through this
module so the same code runs unchanged against TT UAT (or, eventually and
carefully, production) just by swapping .env values.

Note on ACCOUNT vs TT_USERNAME: verified against
docs/tt-fix-reference/schemas/TT-FIX42_legacy.xml, TT's Logon (A) message
has NO Username field at all (that's a standard FIX tag TT doesn't
support), so there is nothing to log in with beyond SenderCompID/Password.
Account (tag 1), however, IS a required field on NewOrderSingle - orders
sent without it will likely be rejected. ACCOUNT replaces the old
TT_USERNAME field for that reason.
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
    account: str
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
        account=_require("ACCOUNT"),
        tt_password=os.getenv("TT_PASSWORD", ""),
        host=_require("HOST"),
        port=int(_require("PORT")),
        fix_version=os.getenv("FIX_VERSION", "FIX.4.4"),
        heartbeat_interval=int(os.getenv("HEARTBEAT_INTERVAL", "30")),
        default_symbol=os.getenv("DEFAULT_SYMBOL", "ES"),
    )
