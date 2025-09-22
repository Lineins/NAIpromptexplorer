from __future__ import annotations

from bisect import bisect_left, bisect_right
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
        self._item_tops: List[int] = []
        self._item_bottoms: List[int] = []

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
        self._visibility_job_id: Optional[str] = None

    def _on_frame_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._schedule_visible_update()

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._window_id, width=event.width)
        self._schedule_visible_update()

    def _on_canvas_scroll(self, first: str, last: str) -> None:
        self.scrollbar.set(first, last)
        self._schedule_visible_update()

    def _on_scrollbar(self, *args: str) -> None:
        self.canvas.yview(*args)
        self._schedule_visible_update()

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
            self._schedule_visible_update()

    def clear(self) -> None:
        if self._batch_job_id is not None:
            self.after_cancel(self._batch_job_id)
            self._batch_job_id = None
        if self._visibility_job_id is not None:
            self.after_cancel(self._visibility_job_id)
            self._visibility_job_id = None
        for item in self._items:
            item.clear_thumbnail()
            item.destroy()
        self._items.clear()
        self._pending.clear()
        self._selected_path = None
        self._item_tops.clear()
        self._item_bottoms.clear()

    def set_entries(self, entries: Iterable[ImageEntry]) -> None:
        self.clear()
        self._pending = list(entries)
        self._build_next_batch()

    def clear_cache(self) -> None:
        self._cache.clear()

    def _build_next_batch(self, batch_size: int = 24) -> None:
        if not self._pending:
            self._batch_job_id = None
            self._schedule_visible_update()
            return
        batch_count = min(batch_size, len(self._pending))
        for _ in range(batch_count):
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
        start_index = max(0, len(self._items) - batch_count)
        self._refresh_item_bounds(start_index=start_index)
        self._schedule_visible_update()
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
        self._schedule_visible_update()

    def set_thumbnail_size(self, size: int) -> None:
        size = max(48, min(size, 512))
        if size == self.thumbnail_size:
            return
        self.thumbnail_size = size
        self._cache.clear()
        for item in self._items:
            item.update_size(size)
        self._relayout_items()
        self._schedule_visible_update()

    def _relayout_items(self) -> None:
        for item in self._items:
            item.grid_forget()
        for index, item in enumerate(self._items):
            row = index // self.columns
            column = index % self.columns
            item.grid(row=row, column=column, padx=4, pady=4, sticky="nsew")
        self._refresh_item_bounds()
        self._schedule_visible_update()

    def select_first(self) -> None:
        if self._items:
            self._handle_select(self._items[0].entry)

    def _refresh_item_bounds(self, start_index: int = 0) -> None:
        if start_index >= len(self._items):
            self._item_tops = self._item_tops[: len(self._items)]
            self._item_bottoms = self._item_bottoms[: len(self._items)]
            return
        try:
            self.inner.update_idletasks()
        except tk.TclError:
            return
        tops = self._item_tops
        bottoms = self._item_bottoms
        for index in range(start_index, len(self._items)):
            item = self._items[index]
            try:
                top = item.winfo_y()
                bottom = top + max(item.winfo_height(), self.thumbnail_size)
            except tk.TclError:
                continue
            if index < len(tops):
                tops[index] = top
                bottoms[index] = bottom
            else:
                tops.append(top)
                bottoms.append(bottom)
        if len(tops) > len(self._items):
            del tops[len(self._items) :]
            del bottoms[len(self._items) :]

    def _schedule_visible_update(self) -> None:
        if self._visibility_job_id is not None:
            return
        self._visibility_job_id = self.after_idle(self._update_visible_thumbnails)

    def _update_visible_thumbnails(self) -> None:
        self._visibility_job_id = None
        if not self._items:
            return
        try:
            canvas_top = self.canvas.canvasy(0)
            canvas_bottom = canvas_top + self.canvas.winfo_height()
        except tk.TclError:
            return
        margin = max(128, self.thumbnail_size)
        tops = self._item_tops
        bottoms = self._item_bottoms
        if len(tops) != len(self._items):
            self._refresh_item_bounds(0)
            tops = self._item_tops
            bottoms = self._item_bottoms
        if not tops or not bottoms:
            return
        lower_bound = canvas_top - margin
        upper_bound = canvas_bottom + margin
        start = bisect_left(bottoms, lower_bound)
        end = bisect_right(tops, upper_bound)
        for index, item in enumerate(self._items):
            if start <= index < end:
                item.ensure_thumbnail()
            else:
                item.clear_thumbnail()

