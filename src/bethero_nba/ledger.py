"""SHA-256 hash-chained JSONL ledger (RULES R-14.1).

Ported from Codex-NPB `src/codex_npb/ledger.py` (GizzyJeans/Codex-NPB@d85a216). Each record carries its
sequence number, the previous record's hash and its own hash over a canonical
JSON form, so any edit, deletion or reordering of an earlier row breaks
`verify`. Git history then guards against replacing the whole file.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ZERO_HASH = "0" * 64
RESERVED = ("sequence", "previous_hash", "record_hash")


class LedgerError(ValueError):
    pass


def canonical_json(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def record_hash(record: dict) -> str:
    payload = {k: v for k, v in record.items() if k != "record_hash"}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def verify(path: Path | str) -> list[dict]:
    path = Path(path)
    previous, records = ZERO_HASH, []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as fh:
        for number, raw in enumerate(fh, start=1):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise LedgerError(f"{path}:{number}: invalid JSON") from exc
            if record.get("sequence") != len(records) + 1:
                raise LedgerError(f"{path}:{number}: broken sequence")
            if record.get("previous_hash") != previous:
                raise LedgerError(f"{path}:{number}: broken previous hash")
            if record.get("record_hash") != record_hash(record):
                raise LedgerError(f"{path}:{number}: hash mismatch")
            records.append(record)
            previous = record["record_hash"]
    return records


def append(path: Path | str, payloads: list[dict]) -> list[dict]:
    """Append records after verifying the existing chain; returns what was written."""
    path = Path(path)
    for payload in payloads:
        clash = set(RESERVED) & set(payload)
        if clash:
            raise LedgerError(f"payload uses reserved keys: {sorted(clash)}")
    existing = verify(path)
    previous = existing[-1]["record_hash"] if existing else ZERO_HASH
    written = []
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        for offset, payload in enumerate(payloads, start=1):
            record = {"sequence": len(existing) + offset, **payload, "previous_hash": previous}
            record["record_hash"] = record_hash(record)
            fh.write(canonical_json(record) + "\n")
            previous = record["record_hash"]
            written.append(record)
        fh.flush()
        os.fsync(fh.fileno())
    return written
