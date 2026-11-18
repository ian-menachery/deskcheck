"""Load the frozen case set and its split."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES_FILE = ROOT / "cases" / "cases.jsonl"
SPLIT_FILE = ROOT / "cases" / "split.json"


def load_cases() -> list[dict]:
    return [json.loads(line) for line in CASES_FILE.read_text("utf-8").splitlines() if line.strip()]


def load_split() -> dict:
    return json.loads(SPLIT_FILE.read_text("utf-8"))


def select(split: str, ids: list[str] | None = None) -> list[dict]:
    cases = load_cases()
    if ids:
        return [c for c in cases if c["id"] in ids]
    if split == "all":
        return cases
    keep = set(load_split()[split])
    return [c for c in cases if c["id"] in keep]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
