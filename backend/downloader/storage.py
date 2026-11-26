from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from uuid import UUID

ROOT = Path(os.getenv("VTT_DOWNLOAD_DIR", str(Path(__file__).resolve().parents[2] / "downloads"))).resolve()


def safe_media_filename(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]
    suffix = Path(name).suffix.lower()
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", Path(name).stem).strip(" .")[:100]
    if not stem or stem.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(COM|LPT)[1-9]", stem.upper()):
        stem = "video"
    valid_suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ".mp4"
    return f"{stem}{valid_suffix}"


def job_directory(job_id: str) -> Path:
    UUID(job_id)
    for day in ROOT.iterdir() if ROOT.exists() else ():
        resolved_day = day.resolve()
        candidate = (resolved_day / job_id).resolve()
        if resolved_day.parent == ROOT.resolve() and candidate.parent == resolved_day and candidate.is_dir():
            return candidate
    return ROOT / date.today().isoformat() / job_id


def save_manifest(directory: Path, manifest: dict) -> None:
    temp = directory / "manifest.json.tmp"
    final = directory / "manifest.json"
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, final)


def read_manifest(job_id: str) -> dict | None:
    directory = job_directory(job_id)
    path = directory / "manifest.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("job_id") != job_id:
            return None
        value["_directory"] = str(directory)
        return value
    except (OSError, ValueError, TypeError):
        return None


def list_manifests() -> list[dict]:
    records = []
    if not ROOT.exists():
        return records
    resolved_root = ROOT.resolve()
    for day in ROOT.iterdir():
        resolved_day = day.resolve()
        if resolved_day.parent != resolved_root or not resolved_day.is_dir():
            continue
        for directory in resolved_day.iterdir():
            resolved_directory = directory.resolve()
            if resolved_directory.parent != resolved_day or not resolved_directory.is_dir():
                continue
            path = resolved_directory / "manifest.json"
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if item.get("status") == "done":
                    item["_directory"] = str(resolved_directory)
                    records.append(item)
            except (OSError, ValueError, TypeError):
                continue
    return sorted(records, key=lambda item: item.get("completed_at", ""), reverse=True)
