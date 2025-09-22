from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Callable, Iterable, List, Optional

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

from .image_index import ImageEntry


class ThumbnailCache:
    def __init__(self, max_items: int = 256) -> None:
        self.max_items = max_items
        self._cache: OrderedDict[tuple[Path, int], ImageTk.PhotoImage] = OrderedDict()

    def get(self, path: Path, size: int) -> ImageTk.PhotoImage:
        key = (path, size)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        image = self._create_thumbnail(path, size)
        self._cache[key] = image
        if len(self._cache) > self.max_items:
            self._cache.popitem(last=False)
        return image

    def clear(self) -> None:
        self._cache.clear()

    def _create_thumbnail(self, path: Path, size: int) -> ImageTk.PhotoImage:
        try:
            with Image.open(path) as img:
                img.thumbnail((size, size), Image.LANCZOS)
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA")
                return ImageTk.PhotoImage(img)
        except Exception:
            placeholder = Image.new("RGBA", (size, size), (60, 60, 60, 255))
            return ImageTk.PhotoImage(placeholder)


class ThumbnailItem(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        entry: ImageEntry,
        cache: ThumbnailCache,
        size: int,
        on_select: Callable[[ImageEntry], None],
    ) -> None:
        super().__init__(parent, relief="flat", borderwidth=2)
        self.entry = entry
        self.cache = cache
        self.size = size
        self.on_select = on_select
        self.selected = False

        self._image_label = ttk.Label(self)
        self._name_label = ttk.Label(self, text=entry.file_name, wraplength=size, justify="center")
        self._image_label.pack(expand=True, fill="both")
        self._name_label.pack(fill="x")

        self._update_thumbnail()
        self._bind_clicks()

    def _update_thumbnail(self) -> None:
        image = self.cache.get(self.entry.path, self.size)
        self._image_label.configure(image=image)
        self._image_label.image = image

    def _bind_clicks(self) -> None:
        for widget in (self, self._image_label, self._name_label):
            widget.bind("<Button-1>", self._on_click)

    def _on_click(self, _event: tk.Event) -> None:  # type: ignore[override]
        self.on_select(self.entry)

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        relief = "solid" if selected else "flat"
        self.configure(relief=relief)

    def update_size(self, size: int) -> None:
        if size != self.size:
            self.size = size
            self._name_label.configure(wraplength=size)
            self._update_thumbnail()


class ThumbnailView(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        on_select: Callable[[ImageEntry], None],
        *,
        columns: int = 5,
        thumbnail_size: int = 160,
    ) -> None:
        super().__init__(parent)
        self.columns = max(1, columns)
        self.thumbnail_size = thumbnail_size
        self.on_select = on_select
        self._cache = ThumbnailCache()
        self._items: List[ThumbnailItem] = []
        self._pending: List[ImageEntry] = []
        self._selected_path: Optional[Path] = None

        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.inner = ttk.Frame(self.canvas)
        self._window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.inner.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _on_frame_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._window_id, width=event.width)

    def clear(self) -> None:
        for item in self._items:
            item.destroy()
        self._items.clear()
        self._pending.clear()
        self._selected_path = None

    def set_entries(self, entries: Iterable[ImageEntry]) -> None:
        self.clear()
        self._pending = list(entries)
        self._build_next_batch()

    def _build_next_batch(self, batch_size: int = 24) -> None:
        if not self._pending:
            return
        for _ in range(min(batch_size, len(self._pending))):
            entry = self._pending.pop(0)
            item = ThumbnailItem(
                self.inner,
                entry=entry,
                cache=self._cache,
                size=self.thumbnail_size,
                on_select=self._handle_select,
            )
            index = len(self._items)
            row = index // self.columns
            column = index % self.columns
            item.grid(row=row, column=column, padx=4, pady=4, sticky="nsew")
            self._items.append(item)
        self.after(10, self._build_next_batch)

    def _handle_select(self, entry: ImageEntry) -> None:
        self._selected_path = entry.path
        for item in self._items:
            item.set_selected(item.entry.path == entry.path)
        self.on_select(entry)

    def set_columns(self, columns: int) -> None:
        columns = max(1, columns)
        if columns == self.columns:
            return
        self.columns = columns
        self._relayout_items()

    def set_thumbnail_size(self, size: int) -> None:
        size = max(48, min(size, 512))
        if size == self.thumbnail_size:
            return
        self.thumbnail_size = size
        self._cache.clear()
        for item in self._items:
            item.update_size(size)
        self._relayout_items()

    def _relayout_items(self) -> None:
        for item in self._items:
            item.grid_forget()
        for index, item in enumerate(self._items):
            row = index // self.columns
            column = index % self.columns
            item.grid(row=row, column=column, padx=4, pady=4, sticky="nsew")

    def select_first(self) -> None:
        if self._items:
            self._handle_select(self._items[0].entry)

