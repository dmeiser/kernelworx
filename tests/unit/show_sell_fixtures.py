"""Show & Sell Stage 1 fixture module: five personas.

Personas: Blake (removed admin), Taylor (non-owner with WRITE),
Riley (READ-only share on Avery), Avery (multi-unit), Devon (campaign joiner),
Emery (independent).
"""

from typing import Any, Dict


def persona_blake() -> Dict[str, Any]:
    return {"name": "Blake", "role": "removed_admin"}


def persona_taylor() -> Dict[str, Any]:
    return {"name": "Taylor", "role": "non_owner_write"}


def persona_riley() -> Dict[str, Any]:
    return {"name": "Riley", "role": "read_only_share_on_avery"}


def persona_avery() -> Dict[str, Any]:
    return {"name": "Avery", "role": "multi_unit"}


def persona_devon() -> Dict[str, Any]:
    return {"name": "Devon", "role": "campaign_joiner"}


def persona_emery() -> Dict[str, Any]:
    return {"name": "Emery", "role": "independent"}


PERSONAS = {
    "Blake": persona_blake(),
    "Taylor": persona_taylor(),
    "Riley": persona_riley(),
    "Avery": persona_avery(),
    "Devon": persona_devon(),
    "Emery": persona_emery(),
}


def all_personas() -> Dict[str, Dict[str, Any]]:
    return dict(PERSONAS)
