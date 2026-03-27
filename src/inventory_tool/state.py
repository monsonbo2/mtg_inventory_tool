from __future__ import annotations

import json
from pathlib import Path


STATE_PATH = Path(".inventory_tool_state.json")


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def get_active_inventory() -> str | None:
    return load_state().get("active_inventory")


def set_active_inventory(inventory_name: str) -> None:
    state = load_state()
    state["active_inventory"] = inventory_name
    save_state(state)


def clear_active_inventory() -> None:
    state = load_state()
    state.pop("active_inventory", None)
    save_state(state)
