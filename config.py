"""Persistent JSON config stored next to the script."""
import json
import os

_PATH = os.path.join(os.path.dirname(__file__), "config.json")

_DEFAULTS: dict = {
    "gateway_url": "",
    "gateway_enabled": False,
}


def load() -> dict:
    try:
        with open(_PATH, encoding="utf-8") as f:
            return {**_DEFAULTS, **json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_DEFAULTS)


def save(data: dict) -> None:
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get(key: str):
    return load().get(key, _DEFAULTS.get(key))


def set(key: str, value) -> None:  # noqa: A001
    data = load()
    data[key] = value
    save(data)
