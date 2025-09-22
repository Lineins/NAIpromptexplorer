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
        self._has_thumbnail = False

        self._image_label = ttk.Label(self)
        self._name_label = ttk.Label(self, text=entry.file_name, wraplength=size, justify="center")
        self._image_label.pack(expand=True, fill="both")
        self._name_label.pack(fill="x")

        self._bind_clicks()

    def ensure_thumbnail(self) -> None:
        if self._has_thumbnail:
            return
        image = self.cache.get(self.entry.path, self.size)
        self._image_label.configure(image=image)
        self._image_label.image = image
        self._has_thumbnail = True

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
            self.clear_thumbnail()

    def clear_thumbnail(self) -> None:
        if not self._has_thumbnail:
            return
        self._image_label.configure(image="")
        self._image_label.image = None
        self._has_thumbnail = False


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
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._on_scrollbar)
        self.canvas.configure(yscrollcommand=self._on_canvas_scroll)

        self.inner = ttk.Frame(self.canvas)
        self._window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.inner.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind(sequence, self._on_mousewheel)
            self.inner.bind(sequence, self._on_mousewheel)
        self._batch_job_id: Optional[str] = None

    def _on_frame_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._update_visible_thumbnails()

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._window_id, width=event.width)
        self._update_visible_thumbnails()

    def _on_canvas_scroll(self, first: str, last: str) -> None:
        self.scrollbar.set(first, last)
        self._update_visible_thumbnails()

    def _on_scrollbar(self, *args: str) -> None:
        self.canvas.yview(*args)
        self._update_visible_thumbnails()

    def _on_mousewheel(self, event: tk.Event) -> None:  # type: ignore[override]
        delta = 0
        if hasattr(event, "delta") and event.delta:
            delta = -1 if event.delta > 0 else 1
        elif event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        if delta:
            self.canvas.yview_scroll(delta, "units")
            self._update_visible_thumbnails()

    def clear(self) -> None:
        if self._batch_job_id is not None:
            self.after_cancel(self._batch_job_id)
            self._batch_job_id = None
        for item in self._items:
            item.clear_thumbnail()
            item.destroy()
        self._items.clear()
        self._pending.clear()
        self._selected_path = None

    def set_entries(self, entries: Iterable[ImageEntry]) -> None:
        self.clear()
        self._pending = list(entries)
        self._build_next_batch()

    def clear_cache(self) -> None:
        self._cache.clear()

    def _build_next_batch(self, batch_size: int = 24) -> None:
        if not self._pending:
            self._batch_job_id = None
            self._update_visible_thumbnails()
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
        self._update_visible_thumbnails()
        self._batch_job_id = self.after(30, self._build_next_batch)

    def _handle_select(self, entry: ImageEntry) -> None:
        self._selected_path = entry.path
        for item in self._items:
            is_selected = item.entry.path == entry.path
            item.set_selected(is_selected)
            if is_selected:
                item.ensure_thumbnail()
        self.on_select(entry)

    def set_columns(self, columns: int) -> None:
        columns = max(1, columns)
        if columns == self.columns:
            return
        self.columns = columns
        self._relayout_items()
        self._update_visible_thumbnails()

    def set_thumbnail_size(self, size: int) -> None:
        size = max(48, min(size, 512))
        if size == self.thumbnail_size:
            return
        self.thumbnail_size = size
        self._cache.clear()
        for item in self._items:
            item.update_size(size)
        self._relayout_items()
        self._update_visible_thumbnails()

    def _relayout_items(self) -> None:
        for item in self._items:
            item.grid_forget()
        for index, item in enumerate(self._items):
            row = index // self.columns
            column = index % self.columns
            item.grid(row=row, column=column, padx=4, pady=4, sticky="nsew")
        self._update_visible_thumbnails()

    def select_first(self) -> None:
        if self._items:
            self._handle_select(self._items[0].entry)

    def _update_visible_thumbnails(self) -> None:
        if not self._items:
            return
        try:
            canvas_top = self.canvas.canvasy(0)
            canvas_bottom = canvas_top + self.canvas.winfo_height()
        except tk.TclError:
            return
        margin = max(128, self.thumbnail_size)
        for item in self._items:
            try:
                item_top = item.winfo_y()
                item_bottom = item_top + max(item.winfo_height(), self.thumbnail_size)
            except tk.TclError:
                continue
            if item_bottom >= canvas_top - margin and item_top <= canvas_bottom + margin:
                item.ensure_thumbnail()
            else:
                item.clear_thumbnail()

