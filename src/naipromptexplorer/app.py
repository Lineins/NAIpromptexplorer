from __future__ import annotations

import threading
from pathlib import Path
from typing import List, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .image_index import ImageEntry, ImageIndexer
from .settings import SettingsManager
from .thumbnail_view import ThumbnailView


class PromptExplorerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("NAI Prompt Explorer")
        self.root.geometry("1200x720")

        self.settings = SettingsManager(self._settings_path())
        self.indexer = ImageIndexer()

        self.current_folder = Path(self.settings.default_folder)
        self.entries: List[ImageEntry] = []
        self.filtered_entries: List[ImageEntry] = []
        self.selected_entry: Optional[ImageEntry] = None

        self._scan_request_id = 0
        self._scan_thread: Optional[threading.Thread] = None

        self.folder_var = tk.StringVar(value=str(self.current_folder))
        self.search_var = tk.StringVar()
        self.search_mode_var = tk.StringVar(value="exact")
        self.hit_count_var = tk.StringVar(value="ヒット数: 0")
        self.status_var = tk.StringVar(value="準備完了")
        self.columns_var = tk.IntVar(value=5)
        self.size_var = tk.IntVar(value=160)

        self._build_ui()
        self.root.after(100, lambda: self.load_folder(self.current_folder))

    @staticmethod
    def _settings_path() -> Path:
        home = Path.home()
        config_dir = home / ".naipromptexplorer"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "settings.json"

    def _build_ui(self) -> None:
        self._build_top_controls()
        self._build_main_area()
        self._build_status_bar()
        self.root.bind("<Control-MouseWheel>", self._on_ctrl_mousewheel)
        self.root.bind("<Control-Button-4>", lambda e: self._adjust_thumbnail_size(16))
        self.root.bind("<Control-Button-5>", lambda e: self._adjust_thumbnail_size(-16))

    def _build_top_controls(self) -> None:
        container = ttk.Frame(self.root)
        container.pack(fill="x", padx=8, pady=4)

        # Search controls
        search_frame = ttk.Frame(container)
        search_frame.pack(fill="x", pady=(0, 6))

        ttk.Label(search_frame, text="検索:").pack(side="left")
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=50)
        search_entry.pack(side="left", padx=(4, 4))
        search_entry.bind("<Return>", lambda _event: self.apply_filter())

        ttk.Button(search_frame, text="検索", command=self.apply_filter).pack(side="left", padx=2)
        ttk.Button(search_frame, text="リセット", command=self.reset_search).pack(side="left", padx=2)

        mode_frame = ttk.Frame(search_frame)
        mode_frame.pack(side="left", padx=12)
        ttk.Label(mode_frame, text="検索モード:").pack(side="left")
        ttk.Radiobutton(mode_frame, text="完全一致", variable=self.search_mode_var, value="exact", command=self.apply_filter).pack(side="left", padx=2)
        ttk.Radiobutton(mode_frame, text="タグAND", variable=self.search_mode_var, value="and", command=self.apply_filter).pack(side="left", padx=2)

        ttk.Label(search_frame, textvariable=self.hit_count_var).pack(side="right")

        # Folder controls
        folder_frame = ttk.LabelFrame(container, text="対象フォルダ")
        folder_frame.pack(fill="x")

        folder_entry = ttk.Entry(folder_frame, textvariable=self.folder_var)
        folder_entry.pack(side="left", fill="x", expand=True, padx=4, pady=4)

        ttk.Button(folder_frame, text="参照", command=self.browse_folder).pack(side="left", padx=2, pady=4)
        ttk.Button(folder_frame, text="再読み込み", command=lambda: self.load_folder(Path(self.folder_var.get()))).pack(side="left", padx=2, pady=4)
        ttk.Button(folder_frame, text="既定に設定", command=self._set_default_folder).pack(side="left", padx=2, pady=4)
        ttk.Button(folder_frame, text="プリセット追加", command=self._add_preset).pack(side="left", padx=2, pady=4)
        ttk.Button(folder_frame, text="プリセット削除", command=self._remove_preset).pack(side="left", padx=2, pady=4)

        presets_frame = ttk.Frame(container)
        presets_frame.pack(fill="x", pady=(6, 0))
        ttk.Label(presets_frame, text="プリセット:").pack(side="left")
        self.presets_var = tk.StringVar()
        self.presets_combobox = ttk.Combobox(presets_frame, textvariable=self.presets_var, state="readonly")
        self.presets_combobox.pack(side="left", padx=4)
        self.presets_combobox.bind("<<ComboboxSelected>>", self._on_select_preset)
        self._refresh_presets()

        # Display options
        display_frame = ttk.Frame(container)
        display_frame.pack(fill="x", pady=(6, 0))

        ttk.Label(display_frame, text="1列あたり").pack(side="left")
        self.columns_value_label = ttk.Label(display_frame, text=str(self.columns_var.get()))
        columns_scale = ttk.Scale(display_frame, from_=1, to=10, orient="horizontal")
        columns_scale.set(self.columns_var.get())
        columns_scale.pack(side="left", padx=4)
        self.columns_value_label.pack(side="left")
        columns_scale.configure(command=self._on_columns_scale)

        ttk.Label(display_frame, text="サムネイルサイズ").pack(side="left", padx=(12, 0))
        self.size_value_label = ttk.Label(display_frame, text=f"{self.size_var.get()}px")
        size_scale = ttk.Scale(display_frame, from_=64, to=320, orient="horizontal")
        size_scale.set(self.size_var.get())
        size_scale.pack(side="left", padx=4)
        self.size_value_label.pack(side="left")
        size_scale.configure(command=self._on_size_scale)

    def _build_main_area(self) -> None:
        paned = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill="both", expand=True, padx=8, pady=4)

        thumbnails_container = ttk.Frame(paned)
        self.thumbnail_view = ThumbnailView(
            thumbnails_container,
            on_select=self._on_select_entry,
            columns=self.columns_var.get(),
            thumbnail_size=self.size_var.get(),
        )
        self.thumbnail_view.pack(fill="both", expand=True)
        paned.add(thumbnails_container, weight=3)

        prompt_container = ttk.Frame(paned)
        prompt_header = ttk.Frame(prompt_container)
        prompt_header.pack(fill="x")
        self.prompt_title_var = tk.StringVar(value="プロンプト未選択")
        ttk.Label(prompt_header, textvariable=self.prompt_title_var).pack(side="left", padx=4, pady=4)
        ttk.Button(prompt_header, text="txt保存", command=self._export_prompt).pack(side="right", padx=4, pady=4)

        text_frame = ttk.Frame(prompt_container)
        text_frame.pack(fill="both", expand=True)
        self.prompt_text = tk.Text(text_frame, wrap="word")
        prompt_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.prompt_text.yview)
        self.prompt_text.configure(yscrollcommand=prompt_scroll.set)
        self.prompt_text.pack(side="left", fill="both", expand=True)
        prompt_scroll.pack(side="right", fill="y")
        paned.add(prompt_container, weight=2)

    def _build_status_bar(self) -> None:
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill="x", padx=8, pady=4)
        ttk.Label(status_frame, textvariable=self.status_var).pack(side="left")

    def browse_folder(self) -> None:
        initial_dir = self.folder_var.get() or str(Path.home())
        selected = filedialog.askdirectory(initialdir=initial_dir)
        if selected:
            self.load_folder(Path(selected))

    def load_folder(self, folder: Path) -> None:
        folder = folder.expanduser()
        if not folder.exists() or not folder.is_dir():
            messagebox.showerror("エラー", f"フォルダが見つかりません: {folder}")
            return
        self.current_folder = folder
        self.folder_var.set(str(folder))
        self.status_var.set("インデックスを作成しています...")
        self.thumbnail_view.clear_cache()
        self.thumbnail_view.clear()
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_title_var.set("プロンプト未選択")
        self.hit_count_var.set("ヒット数: 0")

        self._scan_request_id += 1
        request_id = self._scan_request_id

        def progress(done: int, total: int) -> None:
            if self._scan_request_id != request_id:
                return
            self.root.after(0, lambda: self.status_var.set(f"インデックス作成中... {done}/{total}"))

        def worker() -> None:
            entries = self.indexer.scan_folder(folder, progress)
            if self._scan_request_id != request_id:
                return
            self.root.after(0, lambda: self._on_scan_complete(entries))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        self._scan_thread = thread

    def _on_scan_complete(self, entries: List[ImageEntry]) -> None:
        self.entries = entries
        self.status_var.set(f"読み込み完了 ({len(entries)} ファイル)")
        self.apply_filter()

    def apply_filter(self) -> None:
        mode = self.search_mode_var.get()
        search_text = self.search_var.get()
        entries = self.indexer.search(search_text, mode, self.entries)
        self.filtered_entries = entries
        self.hit_count_var.set(f"ヒット数: {len(entries)}")
        self.thumbnail_view.set_columns(self.columns_var.get())
        self.thumbnail_view.set_thumbnail_size(self.size_var.get())
        self.thumbnail_view.set_entries(entries)
        if entries:
            self.thumbnail_view.select_first()
        else:
            self.prompt_text.delete("1.0", tk.END)
            self.prompt_title_var.set("プロンプト未選択")

    def reset_search(self) -> None:
        self.search_var.set("")
        self.search_mode_var.set("exact")
        self.apply_filter()

    def _on_select_entry(self, entry: ImageEntry) -> None:
        self.selected_entry = entry
        self.prompt_title_var.set(entry.file_name)
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", entry.prompt or "(プロンプトなし)")
        self.prompt_text.see("1.0")

    def _export_prompt(self) -> None:
        if not self.selected_entry:
            messagebox.showinfo("情報", "プロンプトが選択されていません。")
            return
        output_path = self.selected_entry.path.with_suffix(".txt")
        try:
            output_path.write_text(self.selected_entry.prompt, encoding="utf-8")
        except Exception as error:
            messagebox.showerror("エラー", f"書き込みに失敗しました: {error}")
            return
        messagebox.showinfo("完了", f"保存しました: {output_path.name}")

    def _set_default_folder(self) -> None:
        folder = self.folder_var.get()
        if folder:
            self.settings.set_default_folder(folder)
            messagebox.showinfo("情報", "デフォルトフォルダを更新しました。")
            self._refresh_presets()

    def _add_preset(self) -> None:
        folder = self.folder_var.get()
        if folder:
            self.settings.add_preset(folder)
            self._refresh_presets()

    def _remove_preset(self) -> None:
        selection = self.presets_var.get()
        if selection:
            self.settings.remove_preset(selection)
            self._refresh_presets()

    def _refresh_presets(self) -> None:
        presets = self.settings.presets
        self.presets_combobox["values"] = presets
        if presets:
            self.presets_combobox.configure(state="readonly")
        else:
            self.presets_combobox.configure(state="disabled")

    def _on_select_preset(self, _event: tk.Event) -> None:
        selected = self.presets_var.get()
        if selected:
            self.load_folder(Path(selected))

    def _on_columns_scale(self, value: str) -> None:
        if not hasattr(self, "columns_value_label") or not hasattr(self, "thumbnail_view"):
            return
        columns = max(1, int(float(value)))
        if columns != self.columns_var.get():
            self.columns_var.set(columns)
        self.columns_value_label.configure(text=str(columns))
        self.thumbnail_view.set_columns(columns)

    def _on_size_scale(self, value: str) -> None:
        if not hasattr(self, "size_value_label") or not hasattr(self, "thumbnail_view"):
            return
        size = max(64, min(320, int(float(value))))
        if size != self.size_var.get():
            self.size_var.set(size)
        self.size_value_label.configure(text=f"{size}px")
        self.thumbnail_view.set_thumbnail_size(size)

    def _on_ctrl_mousewheel(self, event: tk.Event) -> None:  # type: ignore[override]
        delta = 1 if event.delta > 0 else -1
        self._adjust_thumbnail_size(delta * 16)

    def _adjust_thumbnail_size(self, amount: int) -> None:
        size = self.size_var.get() + amount
        size = max(64, min(320, size))
        self.size_var.set(size)
        self.size_value_label.configure(text=f"{size}px")
        self.thumbnail_view.set_thumbnail_size(size)


def run() -> None:
    root = tk.Tk()
    app = PromptExplorerApp(root)
    root.mainloop()


if __name__ == "__main__":
    run()
