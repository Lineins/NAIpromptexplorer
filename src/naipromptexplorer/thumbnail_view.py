from __future__ import annotations

from collections import OrderedDict
from math import ceil
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
        entry: Optional[ImageEntry],
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
        self.current_row: Optional[int] = None
        self.current_entry_index: Optional[int] = None

        self._image_label = ttk.Label(self)
        name = entry.file_name if entry else ""
        self._name_label = ttk.Label(self, text=name, wraplength=size, justify="center")
        self._image_label.pack(expand=True, fill="both")
        self._name_label.pack(fill="x")

        self._bind_clicks()

    def ensure_thumbnail(self) -> None:
        if self._has_thumbnail or not self.entry:
            return
        image = self.cache.get(self.entry.path, self.size)
        self._image_label.configure(image=image)
        self._image_label.image = image
        self._has_thumbnail = True

    def _bind_clicks(self) -> None:
        for widget in (self, self._image_label, self._name_label):
            widget.bind("<Button-1>", self._on_click)

    def _on_click(self, _event: tk.Event) -> None:  # type: ignore[override]
        if self.entry:
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

    def set_entry(self, entry: Optional[ImageEntry]) -> None:
        if entry is self.entry:
            return
        self.entry = entry
        text = entry.file_name if entry else ""
        self._name_label.configure(text=text)
        self.clear_thumbnail()
        if not entry:
            self.set_selected(False)

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
        self._entries: List[ImageEntry] = []
        self._items: List[ThumbnailItem] = []
        self._item_entries: List[Optional[int]] = []
        self._selected_path: Optional[Path] = None
        self._visible_row = 0
        self._row_height = thumbnail_size + 48
        self._buffer_rows = 2
        self._needs_rebind = True
        self._measurement_job: Optional[str] = None
        self._horizontal_padding = 4
        self._vertical_padding = 4

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

    def _on_scrollbar(self, *args: str) -> None:
        self.canvas.yview(*args)
        self._update_visible_items()

    def _on_canvas_scroll(self, *args: str) -> None:
        self.scrollbar.set(*args)
        self._update_visible_items()

    def _on_frame_configure(self, _event: tk.Event) -> None:  # type: ignore[override]
        self._update_scrollregion()

    def _on_canvas_configure(self, event: tk.Event) -> None:  # type: ignore[override]
        self.canvas.itemconfigure(self._window_id, width=event.width)
        self._needs_rebind = True
        self._ensure_pool()
        self._update_scrollregion()
        self._update_visible_items()

    def clear(self) -> None:
        if self._measurement_job is not None:
            self.after_cancel(self._measurement_job)
            self._measurement_job = None

        for item in self._items:
            item.destroy()
        self._items.clear()
        self._item_entries.clear()
        self._entries.clear()
        self._selected_path = None
        self._visible_row = 0
        self._row_height = self.thumbnail_size + 48
        self._needs_rebind = True
        self.canvas.yview_moveto(0)
        self._update_scrollregion()

    def set_entries(self, entries: Iterable[ImageEntry]) -> None:
        if self._measurement_job is not None:
            self.after_cancel(self._measurement_job)
            self._measurement_job = None

        self._entries = list(entries)
        if self._selected_path and not any(entry.path == self._selected_path for entry in self._entries):
            self._selected_path = None
        self.canvas.yview_moveto(0)
        self._visible_row = 0
        self._needs_rebind = True
        self._ensure_pool()
        self._update_scrollregion()
        self._update_visible_items()

    def clear_cache(self) -> None:
        self._cache.clear()

    def _handle_select(self, entry: ImageEntry) -> None:
        self._selected_path = entry.path
        for item in self._items:
            is_selected = item.entry is not None and item.entry.path == entry.path
            item.set_selected(is_selected)
            if is_selected:
                item.ensure_thumbnail()
        self.on_select(entry)

    def set_columns(self, columns: int) -> None:
        columns = max(1, columns)
        if columns == self.columns:
            return
        self.columns = columns
        self._visible_row = 0
        self._needs_rebind = True
        self._ensure_pool()
        self._update_scrollregion()
        self._update_visible_items()

    def set_thumbnail_size(self, size: int) -> None:
        size = max(48, min(size, 512))
        if size == self.thumbnail_size:
            return
        self.thumbnail_size = size
        self._cache.clear()
        for item in self._items:
            item.update_size(size)
        self._row_height = self.thumbnail_size + 48
        self._visible_row = 0
        self._needs_rebind = True
        self._ensure_pool()
        self._update_scrollregion()
        self._update_visible_items()

    def select_first(self) -> None:
        if self._entries:
            self._handle_select(self._entries[0])
        self._update_visible_items()

    def _refresh_visible_items(self) -> None:
        self._needs_rebind = True
        self._ensure_pool()
        self._update_visible_items()

    def _update_visible_items(self) -> None:
        if not self._entries and not self._items:
            return

        self._ensure_pool()

        row_height = max(1, self._row_height)
        try:
            canvas_top = self.canvas.canvasy(0)
            canvas_bottom = canvas_top + self.canvas.winfo_height()
        except tk.TclError:
            return

        new_row = max(0, int(canvas_top // row_height))
        if self._needs_rebind or new_row != self._visible_row:
            self._rebind_visible_items(new_row)
            self._needs_rebind = False

        margin = max(128, self.thumbnail_size)
        visible_top = canvas_top - margin
        visible_bottom = canvas_bottom + margin
        self._update_item_thumbnails(visible_top, visible_bottom)

    def _ensure_pool(self) -> None:
        current = len(self._items)
        if not self._entries:
            required_items = 0
        else:
            try:
                canvas_height = self.canvas.winfo_height()
            except tk.TclError:
                canvas_height = 0
            canvas_height = max(1, canvas_height)
            row_height = max(1, self._row_height)
            visible_rows = max(1, ceil(canvas_height / row_height))
            total_rows = max(1, ceil(len(self._entries) / self.columns))
            required_rows = min(total_rows, visible_rows + self._buffer_rows)
            required_rows = max(1, min(total_rows, required_rows))
            required_items = required_rows * self.columns

        if required_items == current:
            return

        if required_items < current:
            for _ in range(current - required_items):
                item = self._items.pop()
                item.destroy()
                self._item_entries.pop()
        else:
            for _ in range(required_items - current):
                item = ThumbnailItem(
                    self.inner,
                    entry=None,
                    cache=self._cache,
                    size=self.thumbnail_size,
                    on_select=self._handle_select,
                )
                item.place_forget()
                self._items.append(item)
                self._item_entries.append(None)

        self._needs_rebind = True

    def _compute_column_width(self) -> int:
        width = 0
        try:
            width = self.inner.winfo_width()
        except tk.TclError:
            width = 0
        if width <= 1:
            try:
                width = self.canvas.winfo_width()
            except tk.TclError:
                width = 0
        if width <= 1:
            width = self.columns * (self.thumbnail_size + self._horizontal_padding * 2)
        return max(1, width // max(1, self.columns))

    def _rebind_visible_items(self, start_row: int) -> None:
        if not self._items:
            self._visible_row = 0
            return

        total_entries = len(self._entries)
        if total_entries == 0:
            for index, item in enumerate(self._items):
                item.set_entry(None)
                item.place_forget()
                item.current_row = None
                item.current_entry_index = None
                if index < len(self._item_entries):
                    self._item_entries[index] = None
            self._visible_row = 0
            self._update_scrollregion()
            return

        total_rows = max(1, ceil(total_entries / self.columns))
        pool_rows = max(1, len(self._items) // self.columns)
        max_row = max(total_rows - pool_rows, 0)
        start_row = min(max(start_row, 0), max_row)
        self._visible_row = start_row

        column_width = self._compute_column_width()
        start_index = start_row * self.columns

        for slot, item in enumerate(self._items):
            entry_index = start_index + slot
            if entry_index < total_entries:
                entry = self._entries[entry_index]
                item.set_entry(entry)
                item.set_selected(self._selected_path == entry.path)
                row_index = start_row + slot // self.columns
                column_index = slot % self.columns
                x = column_index * column_width + self._horizontal_padding
                y = row_index * self._row_height + self._vertical_padding
                width = column_width - 2 * self._horizontal_padding
                if width <= 0:
                    width = column_width
                item.place(x=x, y=y, width=width)
                item.current_row = row_index
                item.current_entry_index = entry_index
                self._item_entries[slot] = entry_index
            else:
                item.set_entry(None)
                item.place_forget()
                item.current_row = None
                item.current_entry_index = None
                self._item_entries[slot] = None

        self._schedule_measurement()

    def _schedule_measurement(self) -> None:
        if self._measurement_job is not None:
            return
        self._measurement_job = self.after_idle(self._perform_measurement)

    def _perform_measurement(self) -> None:
        self._measurement_job = None
        new_height = self._measure_row_height()
        if new_height != self._row_height:
            self._row_height = new_height
            self._needs_rebind = True
        self._update_scrollregion()
        if self._needs_rebind:
            self.after_idle(self._update_visible_items)

    def _measure_row_height(self) -> int:
        try:
            self.inner.update_idletasks()
        except tk.TclError:
            return max(1, self._row_height)

        height = 0
        for item in self._items:
            if not item.winfo_ismapped():
                continue
            try:
                item_height = item.winfo_height()
            except tk.TclError:
                item_height = 0
            if item_height:
                height = item_height + self._vertical_padding * 2
                break
        if not height:
            for item in self._items:
                try:
                    req_height = item.winfo_reqheight()
                except tk.TclError:
                    continue
                if req_height:
                    height = req_height + self._vertical_padding * 2
                    break

        if not height:
            height = self.thumbnail_size + 48

        return max(1, height)

    def _update_scrollregion(self) -> None:
        total_rows = ceil(len(self._entries) / self.columns) if self._entries else 0
        total_height = total_rows * self._row_height
        try:
            width = self.canvas.winfo_width()
        except tk.TclError:
            width = 0
        if width <= 0:
            width = self.columns * (self.thumbnail_size + self._horizontal_padding * 2)
        self.canvas.configure(scrollregion=(0, 0, width, total_height))
        window_height = max(total_height, self.canvas.winfo_height())
        try:
            self.canvas.itemconfigure(self._window_id, height=window_height)
        except tk.TclError:
            pass

    def _update_item_thumbnails(self, visible_top: float, visible_bottom: float) -> None:
        for item, entry_index in zip(self._items, self._item_entries):
            if entry_index is None:
                item.clear_thumbnail()
                continue
            row_index = entry_index // self.columns
            top = row_index * self._row_height + self._vertical_padding
            bottom = top + max(0, self._row_height - 2 * self._vertical_padding)
            if bottom < visible_top or top > visible_bottom:
                item.clear_thumbnail()
            else:
                item.ensure_thumbnail()

