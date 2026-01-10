from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import List

from app.core.models import Profile


class ProfileStore:
    def __init__(self, base_dir: Path) -> None:
        self._path = base_dir / "data" / "profiles.json"

    def load(self) -> List[Profile]:
        if not self._path.exists():
            return [Profile(name="Default", max_concurrent=2)]
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return [Profile(name="Default", max_concurrent=2)]
        profiles = []
        for item in data.get("profiles", []):
            profiles.append(
                Profile(
                    name=item.get("name", "Default"),
                    output_dir=item.get("output_dir"),
                    cookies_path=item.get("cookies_path"),
                    cookies_browser=item.get("cookies_browser"),
                    max_concurrent=int(item.get("max_concurrent", 2)),
                )
            )
        return profiles or [Profile(name="Default", max_concurrent=2)]

    def save(self, profiles: List[Profile]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"profiles": [asdict(profile) for profile in profiles]}
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
