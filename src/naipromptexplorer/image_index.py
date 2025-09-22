from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from PIL import Image


@dataclass
class ImageEntry:
    path: Path
    prompt: str

    @property
    def file_name(self) -> str:
        return self.path.name

    @property
    def prompt_lower(self) -> str:
        return self.prompt.lower()


def extract_prompt_text(image_path: Path) -> str:
    """Extract prompt metadata from a PNG file."""

    texts: List[str] = []
    try:
        with Image.open(image_path) as img:
            info = {}
            info.update(getattr(img, "info", {}))
            text_items = getattr(img, "text", {})
            if isinstance(text_items, dict):
                info.update(text_items)

            prioritized_keys = [
                "prompt",
                "parameters",
                "description",
                "comment",
            ]
            remaining: List[str] = []
            seen: set[str] = set()

            def append_value(value: object, dest: List[str]) -> None:
                if isinstance(value, bytes):
                    try:
                        text_value = value.decode("utf-8")
                    except Exception:
                        text_value = value.decode("latin-1", errors="ignore")
                else:
                    text_value = str(value)
                text_value = text_value.strip()
                if text_value and text_value not in seen:
                    seen.add(text_value)
                    dest.append(text_value)

            for key in prioritized_keys:
                if key in info:
                    append_value(info[key], texts)

            for key, value in info.items():
                if key in prioritized_keys:
                    continue
                append_value(value, remaining)

            texts.extend(remaining)
    except Exception:
        return ""

    return "\n\n".join(texts)


ProgressCallback = Callable[[int, int], None]


class ImageIndexer:
    """Load image metadata for a folder in the background."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: List[ImageEntry] = []

    @property
    def entries(self) -> List[ImageEntry]:
        with self._lock:
            return list(self._entries)

    def scan_folder(
        self, folder: Path, progress_callback: Optional[ProgressCallback] = None
    ) -> List[ImageEntry]:
        png_files = sorted(folder.glob("*.png"))
        entries: List[ImageEntry] = []
        total = len(png_files)
        for index, image_path in enumerate(png_files, start=1):
            prompt = extract_prompt_text(image_path)
            entries.append(ImageEntry(path=image_path, prompt=prompt))
            if progress_callback and index % 25 == 0:
                progress_callback(index, total)
        if progress_callback:
            progress_callback(total, total)
        with self._lock:
            self._entries = entries
        return entries

    def search(
        self,
        search_text: str,
        mode: str,
        source_entries: Optional[Iterable[ImageEntry]] = None,
    ) -> List[ImageEntry]:
        if source_entries is None:
            source_entries = self.entries

        search_text = search_text.strip()
        if not search_text:
            return list(source_entries)

        lowered_entries = list(source_entries)
        if mode == "exact":
            needle = search_text.lower()
            return [entry for entry in lowered_entries if needle in entry.prompt_lower]

        # Default to AND mode.
        tokens = [token.strip().lower() for token in search_text.split(",") if token.strip()]
        if not tokens:
            return list(lowered_entries)

        def matches(entry: ImageEntry) -> bool:
            prompt = entry.prompt_lower
            return all(token in prompt for token in tokens)

        return [entry for entry in lowered_entries if matches(entry)]
