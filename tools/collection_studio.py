"""Desktop collection manager for osu!stable and copied osu!lazer Realms."""

import argparse
import queue
import sys
import tempfile
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, font, messagebox, simpledialog, ttk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.collection_application import load_document, save_workspace  # noqa: E402
from tools.collection_backend import Backend  # noqa: E402
from tools.collection_workspace import Workspace  # noqa: E402
from tools.credits import read_documents  # noqa: E402
from tools.stable_collections import (  # noqa: E402
    read_replay_cache,
    read_stable,
    scan_songs,
)

PAGE_SIZE = 500


class CollectionStudio:
    def __init__(self, root, backend=None):
        self.root = root
        self.backend = backend or Backend()
        self.workspace = None
        self.busy = False
        self.events = queue.Queue()
        self.selected = None
        self.map_page = 0
        self.map_pages = 1
        self.download_window = None
        self.download_directory = ""
        self.migration_window = None
        self.last_import_ids = set()
        self.root.title("Collections Studio · osu!")
        width = min(1360, max(1000, self.root.winfo_screenwidth() - 80))
        height = min(900, max(700, self.root.winfo_screenheight() - 80))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(1000, 700)
        self.root.configure(background="#141216")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._style()
        self._build()
        self.root.bind("<Control-z>", lambda _event: self.undo())
        self.root.bind("<Control-s>", lambda _event: self.save())
        self.root.after(100, self._poll)
        self._controls()

    def _style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        self.body_font = font.nametofont("TkDefaultFont").copy()
        self.body_font.configure(size=11)
        self.title_font = self.body_font.copy()
        self.title_font.configure(size=23, weight="bold")
        self.heading_font = self.body_font.copy()
        self.heading_font.configure(size=14, weight="bold")
        style.configure(".", background="#1d1a20", foreground="#f7f0f2", font=self.body_font)
        style.configure("TFrame", background="#141216")
        style.configure("TLabel", background="#141216")
        style.configure("Muted.TLabel", foreground="#b5a9b7")
        style.configure("Title.TLabel", font=self.title_font)
        style.configure("Heading.TLabel", font=self.heading_font)
        style.configure("TButton", padding=(12, 8), background="#302735", bordercolor="#514257")
        style.map("TButton", background=[("active", "#49354f"), ("disabled", "#211e24")])
        style.configure("Accent.TButton", background="#ffa58d", foreground="#2b1610")
        style.map("Accent.TButton", background=[("active", "#ffb9a6"), ("disabled", "#493432")])
        style.configure("TEntry", fieldbackground="#211d25", insertcolor="#f7f0f2", padding=7)
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#211d25")],
            foreground=[("readonly", "#f7f0f2")],
            selectbackground=[("readonly", "#211d25")],
            selectforeground=[("readonly", "#f7f0f2")],
        )
        self.root.option_add("*TCombobox*Listbox.background", "#211d25")
        self.root.option_add("*TCombobox*Listbox.foreground", "#f7f0f2")
        style.configure(
            "Treeview", background="#1d1a20", fieldbackground="#1d1a20", rowheight=33, borderwidth=0
        )
        style.configure("Treeview.Heading", background="#302735", foreground="#f7f0f2", padding=9)
        style.map(
            "Treeview", background=[("selected", "#5c3d51")], foreground=[("selected", "#ffffff")]
        )

    def show_credits(self):
        existing = getattr(self, "credits_window", None)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            return
        try:
            documents = read_documents()
        except RuntimeError as error:
            messagebox.showerror("Credits and licences", str(error), parent=self.root)
            return
        window = tk.Toplevel(self.root)
        self.credits_window = window
        window.title("Credits and licences — Collections Studio")
        window.geometry("840x640")
        window.minsize(540, 380)
        window.configure(background="#1d1a20")
        style = ttk.Style(window)
        style.configure("Credits.TNotebook", background="#1d1a20")
        style.configure(
            "Credits.TNotebook.Tab", background="#302735", foreground="#f7f0f2", padding=(12, 8)
        )
        style.map(
            "Credits.TNotebook.Tab",
            background=[("selected", "#5c3d51"), ("active", "#49354f")],
            foreground=[("selected", "#ffffff"), ("active", "#ffffff")],
        )
        notebook = ttk.Notebook(window, style="Credits.TNotebook")
        notebook.pack(fill="both", expand=True, padx=12, pady=12)
        self.credits_texts = {}
        for title, content in documents:
            frame = ttk.Frame(notebook)
            text = tk.Text(
                frame,
                wrap="word",
                font="TkDefaultFont",
                padx=12,
                pady=12,
                background="#1d1a20",
                foreground="#f7f0f2",
                selectbackground="#5c3d51",
                selectforeground="#ffffff",
            )
            scrollbar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
            text.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side="right", fill="y")
            text.pack(fill="both", expand=True)
            text.insert("1.0", content)
            text.configure(state="disabled")
            self.credits_texts[title] = text
            notebook.add(frame, text=title)
        ttk.Button(window, text="Close", command=window.destroy).pack(pady=(0, 12))
        window.bind("<Escape>", lambda _event: window.destroy())

    def _build(self):
        menu = tk.Menu(self.root)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Credits and licences…", command=self.show_credits)
        menu.add_cascade(label="Help", menu=help_menu)
        self.root.configure(menu=menu)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        header = ttk.Frame(self.root, padding=(24, 20, 24, 10))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Collections Studio", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header, text="Manage osu!stable and osu!lazer collections.", style="Muted.TLabel"
        ).pack(anchor="w", pady=(4, 12))
        bar = ttk.Frame(header)
        bar.pack(fill="x")
        self.open_button = ttk.Button(
            bar, text="Open collections…", width=0, command=self.open_file
        )
        self.open_button.pack(side="left", padx=(0, 8))
        self.new_file_button = ttk.Button(
            bar, text="New collection.db", width=0, command=self.new_file
        )
        self.new_file_button.pack(side="left", padx=(0, 8))
        self.import_button = ttk.Button(bar, text="Import .db…", width=0, command=self.import_file)
        self.import_button.pack(side="left", padx=(0, 8))
        self.collector_button = ttk.Button(
            bar, text="Import link…", width=0, command=self.import_link
        )
        self.collector_button.pack(side="left", padx=(0, 8))
        tools = ttk.Frame(header)
        tools.pack(fill="x", pady=(8, 0))
        self.download_button = ttk.Button(
            tools, text="Get missing maps…", width=0, command=self.download_maps
        )
        self.download_button.pack(side="left", padx=(0, 8))
        self.scan_button = ttk.Button(
            tools, text="Scan Songs folder…", width=0, command=self.scan_folder
        )
        self.database_button = ttk.Button(
            tools, text="Read osu!.db…", width=0, command=self.read_database
        )
        self.database_button.pack(side="left", padx=(0, 8))
        self.scan_button.pack(side="left", padx=(0, 8))
        self.replay_button = ttk.Button(
            tools, text="Replay cache…", width=0, command=self.read_cache
        )
        self.replay_button.pack(side="left", padx=(0, 8))
        self.undo_button = ttk.Button(tools, text="Undo", width=0, command=self.undo)
        self.undo_button.pack(side="left")
        self.migrate_button = ttk.Button(
            tools, text="Migrate…", width=0, command=self.migrate_collections
        )
        self.migrate_button.pack(side="left", padx=(8, 0))
        self.save_button = ttk.Button(
            bar, text="Save new file…", width=0, style="Accent.TButton", command=self.save
        )
        self.save_button.pack(side="right")
        self.source = tk.StringVar(
            value="Open client.realm or collection.db, or start a new collection.db."
        )
        self.source_label = ttk.Label(
            header, textvariable=self.source, style="Muted.TLabel", wraplength=1190
        )
        self.source_label.pack(anchor="w", fill="x", pady=(12, 0))
        header.bind(
            "<Configure>",
            lambda event: self.source_label.configure(wraplength=max(250, event.width - 48)),
        )

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.grid(row=1, column=0, sticky="nsew", padx=24, pady=12)
        left = ttk.Frame(body, padding=(0, 0, 15, 0))
        right = ttk.Frame(body, padding=(15, 0, 0, 0))
        body.add(left, weight=1)
        body.add(right, weight=3)
        for panel in (left, right):
            panel.columnconfigure(0, weight=1)
            panel.rowconfigure(3, weight=1)
        ttk.Label(left, text="COLLECTIONS", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 10)
        )
        ttk.Label(left, text="Search collections", style="Muted.TLabel").grid(
            row=1, column=0, sticky="w"
        )
        self.collection_search = tk.StringVar()
        ttk.Entry(left, textvariable=self.collection_search).grid(
            row=2, column=0, sticky="ew", pady=(0, 10)
        )
        self.collection_search.trace_add("write", lambda *_args: self.refresh_collections())
        collections_frame = ttk.Frame(left)
        collections_frame.grid(row=3, column=0, sticky="nsew")
        self.collections = ttk.Treeview(
            collections_frame, columns=("count",), show="tree headings", selectmode="browse"
        )
        self.collections.heading("#0", text="Collection")
        self.collections.heading("count", text="Maps")
        self.collections.column("#0", width=245, minwidth=150)
        self.collections.column("count", width=60, stretch=False, anchor="e")
        self.collections.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(collections_frame, orient="vertical", command=self.collections.yview)
        scroll.pack(side="right", fill="y")
        self.collections.configure(yscrollcommand=scroll.set)
        self.collections.bind("<<TreeviewSelect>>", self.select_collection)
        actions = ttk.Frame(left)
        actions.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self.new_button = ttk.Button(actions, text="New", width=0, command=self.new_collection)
        self.rename_button = ttk.Button(
            actions, text="Rename", width=0, command=self.rename_collection
        )
        self.delete_button = ttk.Button(
            actions, text="Delete", width=0, command=self.delete_collection
        )
        for button in (self.new_button, self.rename_button, self.delete_button):
            button.pack(side="left", padx=(0, 6))

        self.map_heading = tk.StringVar(value="Choose a collection")
        ttk.Label(
            right, textvariable=self.map_heading, style="Heading.TLabel", wraplength=730
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.map_search = tk.StringVar()
        ttk.Label(right, text="Search maps or MD5", style="Muted.TLabel").grid(
            row=1, column=0, sticky="w"
        )
        ttk.Entry(right, textvariable=self.map_search).grid(
            row=2, column=0, sticky="ew", pady=(0, 10)
        )
        self.map_search.trace_add("write", lambda *_args: self.reset_maps())
        maps_frame = ttk.Frame(right)
        maps_frame.grid(row=3, column=0, sticky="nsew")
        maps_frame.columnconfigure(0, weight=1)
        maps_frame.rowconfigure(0, weight=1)
        self.maps = ttk.Treeview(
            maps_frame,
            columns=("song", "difficulty", "mode", "state", "md5"),
            show="headings",
            displaycolumns=("song", "difficulty", "mode", "state"),
            selectmode="extended",
        )
        for column, label, width in [
            ("song", "Artist / title", 350),
            ("difficulty", "Difficulty", 210),
            ("mode", "Mode", 70),
            ("state", "Map details", 100),
        ]:
            self.maps.heading(column, text=label)
            self.maps.column(column, width=width, minwidth=60)
        self.maps.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(maps_frame, orient="vertical", command=self.maps.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(maps_frame, orient="horizontal", command=self.maps.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.maps.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.maps.bind("<<TreeviewSelect>>", self.select_map)
        self.maps.bind("<Control-a>", self.select_all_maps)
        pager = ttk.Frame(right)
        pager.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.previous_button = ttk.Button(
            pager, text="Previous", command=lambda: self.page_maps(-1)
        )
        self.previous_button.pack(side="left")
        self.next_button = ttk.Button(pager, text="Next", command=lambda: self.page_maps(1))
        self.next_button.pack(side="right")
        self.page_text = tk.StringVar(value="0 maps")
        ttk.Label(pager, textvariable=self.page_text, style="Muted.TLabel").pack(pady=8)
        details = ttk.Frame(right)
        details.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        self.select_all_button = ttk.Button(
            details, text="Select all shown", command=self.select_all_maps
        )
        self.select_all_button.pack(side="left", padx=(0, 8))
        self.remove_button = ttk.Button(
            details, text="Remove selected maps", command=self.remove_maps
        )
        self.remove_button.pack(side="left")
        self.selection = tk.StringVar(value="0 selected")
        ttk.Label(details, textvariable=self.selection, style="Muted.TLabel").pack(
            side="left", padx=12
        )
        self.hash_text = tk.StringVar(value="Select a map to view its MD5.")
        ttk.Label(right, textvariable=self.hash_text, style="Muted.TLabel").grid(
            row=6, column=0, sticky="w", pady=(10, 0)
        )
        ttk.Label(
            right,
            text="Removing maps changes collection membership; beatmap data stays saved.",
            style="Muted.TLabel",
            wraplength=730,
        ).grid(row=7, column=0, sticky="w", pady=(4, 0))

        footer = ttk.Frame(self.root, padding=(24, 0, 24, 18))
        footer.grid(row=2, column=0, sticky="ew")
        self.status = tk.StringVar(
            value="Ready. All edits stay in this window until you save a new copy."
        )
        ttk.Label(footer, textvariable=self.status, style="Muted.TLabel", wraplength=1190).pack(
            side="left"
        )
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=120)

    def _controls(self):
        loaded = self.workspace is not None and not self.busy
        selected = loaded and self.selected is not None
        for button, enabled in [
            (self.open_button, not self.busy),
            (self.new_file_button, not self.busy),
            (self.import_button, loaded),
            (self.collector_button, loaded),
            (self.download_button, loaded),
            (self.migrate_button, loaded and bool(self.workspace.collections)),
            (self.database_button, loaded and self.workspace.format == "stable"),
            (self.scan_button, loaded and self.workspace.format == "stable"),
            (self.replay_button, loaded and self.workspace.format == "stable"),
            (self.new_button, loaded),
            (self.rename_button, selected),
            (self.delete_button, selected),
            (self.select_all_button, selected and bool(self.maps.get_children())),
            (self.previous_button, selected and self.map_page > 0),
            (self.next_button, selected and self.map_page + 1 < self.map_pages),
            (self.undo_button, loaded and self.workspace.can_undo),
            (self.save_button, loaded and (self.workspace.dirty or not self.workspace.source_path)),
            (self.remove_button, selected and bool(self.maps.selection())),
        ]:
            button.configure(state="normal" if enabled else "disabled")
        dirty = self.workspace is not None and self.workspace.dirty
        self.root.title(("● " if dirty else "") + "Collections Studio · osu!")
        if self.workspace:
            self.save_button.configure(
                text="Save new .db…" if self.workspace.format == "stable" else "Save new Realm…"
            )

    def _task(self, label, work, done):
        if self.busy:
            return
        self.busy = True
        self.status.set(label)
        self.progress.pack(side="right")
        self.progress.start(12)
        self._controls()

        def execute():
            try:
                self.events.put((done, work(), None))
            except Exception as error:
                self.events.put((done, None, error))

        threading.Thread(target=execute, daemon=True).start()

    def _poll(self):
        try:
            while True:
                done, result, error = self.events.get_nowait()
                self.busy = False
                self.progress.stop()
                self.progress.pack_forget()
                if error:
                    self.status.set("The operation failed. Your source file is unchanged.")
                    messagebox.showerror("Collections Studio", str(error), parent=self.root)
                else:
                    done(result)
                self._controls()
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _discard_ok(self):
        return (
            not self.workspace
            or not self.workspace.dirty
            or messagebox.askyesno(
                "Discard unsaved changes?", "Discard the changes in this window?", parent=self.root
            )
        )

    def open_file(self):
        if self.busy or not self._discard_ok():
            return
        path = filedialog.askopenfilename(
            title="Open osu!stable collection.db or a copied osu!lazer Realm",
            filetypes=[("Collections", "*.realm *.db"), ("All files", "*")],
            parent=self.root,
        )
        if path:
            self.load(path)

    def load(self, path):
        def read():
            return load_document(path, self.backend)

        def loaded(document):
            self.workspace = Workspace(document, str(Path(path).resolve()))
            self.selected = None
            self.last_import_ids.clear()
            self.source.set(
                self.workspace.format + " · Working from: " + self.workspace.source_path
            )
            self.refresh_collections()
            self.status.set(
                f"Loaded {len(self.workspace.collections)} collections. Source file is unchanged."
                + f" {len(self.workspace.present_hashes):,} library MD5s."
                + (" Library: " + document["LibraryError"] if document.get("LibraryError") else "")
            )

        self._task(
            "Reading collections and map details…",
            read,
            loaded,
        )

    def new_file(self):
        if self.busy or not self._discard_ok():
            return
        self.workspace = Workspace(
            {"Format": "stable", "Version": 20261026, "SourceRealmSha256": "", "Collections": []},
            "",
        )
        self.selected = None
        self.source.set("New osu!stable collection.db · not saved yet")
        self.last_import_ids.clear()
        self.refresh_collections()
        self.status.set("Create a collection or import a .db file or collection link.")

    def scan_folder(self):
        if self.busy or not self.workspace:
            return
        folder = filedialog.askdirectory(
            title="Select your osu!stable Songs folder", parent=self.root
        )
        if not folder:
            return

        def scanned(document):
            self.workspace.beatmaps.update(document["Beatmaps"])
            self.workspace.present_hashes = self.workspace.database_hashes | set(
                document["Beatmaps"]
            )
            self.refresh_maps()
            self.status.set(
                f"Scanned {document['Scanned']:,} .osu files; "
                f"{document['ErrorCount']} unreadable. No Songs files were changed."
            )

        self._task("Scanning .osu files and their MD5s…", lambda: scan_songs(folder), scanned)

    def read_database(self):
        if self.busy or not self.workspace:
            return
        path = filedialog.askopenfilename(
            title="Read osu!stable's osu!.db (read-only)",
            filetypes=[("osu! database", "*.db"), ("All files", "*")],
            parent=self.root,
        )
        if path:
            from tools.osu_database import read_osu_database

            self._task(
                "Reading cached beatmap hashes from osu!.db…",
                lambda: read_osu_database(path),
                self._library_loaded,
            )

    def read_cache(self):
        if self.busy or not self.workspace:
            return
        path = filedialog.askopenfilename(
            title="Read Replay Parser's beatmap-index-cache.json",
            filetypes=[("Replay Parser cache", "*.json"), ("All files", "*")],
            parent=self.root,
        )
        if path:
            self._task(
                "Checking Replay Parser cache file sizes and modification times…",
                lambda: read_replay_cache(path),
                self._library_loaded,
            )

    def _library_loaded(self, document):
        self.workspace.beatmaps.update(document["Beatmaps"])
        self.workspace.present_hashes = self.workspace.database_hashes | set(document["Beatmaps"])
        self.refresh_maps()
        self.status.set(
            f"Loaded {document['Scanned']:,} cached beatmaps; "
            f"{document['ErrorCount']} stale/invalid entries skipped. "
            "No beatmap files were rehashed."
        )

    def refresh_collections(self):
        if not hasattr(self, "collections"):
            return
        for item in self.collections.get_children():
            self.collections.delete(item)
        if self.workspace:
            query = self.collection_search.get().casefold()
            for item in sorted(
                self.workspace.collections, key=lambda item: (item["Name"].casefold(), item["Id"])
            ):
                if query in item["Name"].casefold():
                    self.collections.insert(
                        "", "end", iid=item["Id"], text=item["Name"], values=(len(item["Hashes"]),)
                    )
        children = self.collections.get_children()
        if self.selected not in children:
            self.selected = children[0] if children else None
            self.map_page = 0
        if self.selected:
            self.collections.selection_set(self.selected)
        self.refresh_maps()
        self._controls()

    def select_collection(self, _event=None):
        selected = self.collections.selection()
        collection_id = selected[0] if selected else None
        if collection_id != self.selected:
            self.map_page = 0
        self.selected = collection_id
        self.refresh_maps()
        self._controls()

    def reset_maps(self):
        self.map_page = 0
        self.refresh_maps()

    def page_maps(self, step):
        self.map_page = max(0, min(self.map_pages - 1, self.map_page + step))
        self.refresh_maps()

    def _map_values(self, value):
        meta = self.workspace.beatmaps.get(value.lower(), {})
        title = meta.get("Title") or f"Unknown beatmap · {value[:12]}…"
        artist = meta.get("Artist")
        song = f"{artist} — {title}" if artist else title
        present = value.lower() in self.workspace.present_hashes
        state = (
            ("In Realm" if self.workspace.format == "realm" else "Installed")
            if present
            else "Missing"
        )
        if not present and value.lower() in self.workspace.downloaded:
            state = "Downloaded"
        return (
            song,
            meta.get("Difficulty") or "MD5 only",
            meta.get("Mode") or "—",
            state,
            value,
        )

    def refresh_maps(self):
        if not hasattr(self, "maps"):
            return
        for item in self.maps.get_children():
            self.maps.delete(item)
        self.hash_text.set("Select a map to view its MD5.")
        self.map_pages = 1
        self.page_text.set("0 maps")
        if not self.workspace or not self.selected:
            self.map_heading.set("Choose a collection")
        else:
            group = self.workspace.collection(self.selected)
            self.map_heading.set(f"{group['Name']}  ·  {len(group['Hashes'])} maps")
            query = self.map_search.get().casefold()
            matching = [
                (index, value)
                for index, value in enumerate(group["Hashes"])
                if not query or query in " ".join(self._map_values(value)).casefold()
            ]
            count = len(matching)
            self.map_pages = max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)
            self.map_page = min(self.map_page, self.map_pages - 1)
            start = self.map_page * PAGE_SIZE
            self.page_text.set(
                f"Page {self.map_page + 1} / {self.map_pages} · "
                f"{min(PAGE_SIZE, count - start)} of {count:,} matching maps shown"
            )
            for index, value in matching[start : start + PAGE_SIZE]:
                self.maps.insert(
                    "",
                    "end",
                    iid=f"{index}:{value}",
                    values=self._map_values(value),
                )
        self.select_map()

    def select_map(self, _event=None):
        selected = self.maps.selection()
        self.selection.set(f"{len(selected)} selected")
        self.hash_text.set("Select a map to view its MD5.")
        if len(selected) == 1:
            self.hash_text.set("MD5: " + self.maps.item(selected[0], "values")[-1])
        self._controls()

    def select_all_maps(self, _event=None):
        self.maps.selection_set(self.maps.get_children())
        self.select_map()
        return "break"

    def _edit(self, action):
        if not self.workspace or self.busy:
            return
        try:
            action()
            self.refresh_collections()
            created, edited, deleted = self.workspace.summary()
            self.status.set(
                f"Unsaved changes: {created} new, {edited} edited, {deleted} deleted collections. "
                "Undo is available."
            )
        except ValueError as error:
            messagebox.showerror("Collection edit", str(error), parent=self.root)

    def new_collection(self):
        if not self.workspace or self.busy:
            return
        name = simpledialog.askstring("New collection", "Collection name:", parent=self.root)
        if name is not None:

            def create():
                self.selected = self.workspace.create(name)

            self._edit(create)

    def rename_collection(self):
        if not self.selected or self.busy:
            return
        name = simpledialog.askstring(
            "Rename collection",
            "Collection name:",
            initialvalue=self.workspace.collection(self.selected)["Name"],
            parent=self.root,
        )
        if name is not None:
            self._edit(lambda: self.workspace.rename(self.selected, name))

    def delete_collection(self):
        if not self.selected or self.busy:
            return
        group = self.workspace.collection(self.selected)
        if messagebox.askyesno(
            "Delete collection?",
            f"Delete “{group['Name']}” from this working copy?\n\n"
            "Its beatmap data will stay saved. You can undo this change.",
            parent=self.root,
        ):
            self._edit(lambda: self.workspace.delete(self.selected))

    def remove_maps(self):
        if not self.selected or self.busy:
            return
        hashes = [self.maps.item(item, "values")[-1] for item in self.maps.selection()]
        if hashes:
            self._edit(lambda: self.workspace.remove_maps(self.selected, hashes))

    def undo(self):
        if self.workspace and not self.busy:
            self.workspace.undo()
            self.refresh_collections()
            self.status.set(
                "Last edit undone."
                if self.workspace.dirty
                else "All changes undone. Source file is unchanged."
            )

    def import_file(self):
        if not self.workspace or self.busy:
            return
        path = filedialog.askopenfilename(
            title="Import collection.db",
            filetypes=[("Legacy collection database", "*.db"), ("All files", "*")],
            parent=self.root,
        )
        if path:

            def imported(document):
                try:
                    created, added = self.workspace.merge(document["Collections"])
                    self._import_selection(document["Collections"])
                    self.refresh_collections()
                    self.status.set(
                        f"Imported into the working copy: {created} new collections, "
                        f"{added} added memberships. "
                        f"{len(self.workspace.missing_hashes()):,} missing hashes; "
                        "use Get missing maps."
                    )
                except ValueError as error:
                    messagebox.showerror("Import collections", str(error), parent=self.root)

            self._task(
                "Reading collection.db…",
                lambda: read_stable(path),
                imported,
            )

    def import_link(self):
        if self.busy or not self.workspace:
            return
        value = simpledialog.askstring(
            "Import collection link",
            "Maps import link, osu!collector collection URL, or osu!collector ID:",
            parent=self.root,
        )
        if not value:
            return
        from tools.collection_links import fetch_link

        def imported(document):
            try:
                created, added = self.workspace.merge(document["Collections"])
                self._import_selection(document["Collections"])
                for checksum, details in document["Beatmaps"].items():
                    self.workspace.beatmaps.setdefault(checksum, details)
                self.refresh_collections()
                self.status.set(
                    f"{document['SourceName']}: {created} new collections, "
                    f"{added} added memberships. " + " ".join(document["Warnings"])
                )
            except ValueError as error:
                messagebox.showerror("Import collection link", str(error), parent=self.root)

        self._task(
            "Fetching collection contents…",
            lambda: fetch_link(value),
            imported,
        )

    def _import_selection(self, groups):
        names = {group["Name"] for group in groups}
        self.last_import_ids = {
            group["Id"] for group in self.workspace.collections if group["Name"] in names
        }
        if self.last_import_ids:
            self.selected = next(
                group["Id"]
                for group in self.workspace.collections
                if group["Id"] in self.last_import_ids
            )
            self.collection_search.set("")

    def save(self):
        if (
            not self.workspace
            or (not self.workspace.dirty and self.workspace.source_path)
            or self.busy
        ):
            return
        parent = filedialog.askdirectory(
            title="Choose where to create the exported collections folder",
            initialdir=str(Path(self.workspace.source_path).parent),
            parent=self.root,
        )
        if not parent:
            return
        output = Path(parent) / ("collections-export-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        if output.exists():
            output = Path(tempfile.mkdtemp(prefix="collections-export-", dir=parent))
            output.rmdir()
        created, edited, deleted = self.workspace.summary()
        stable = self.workspace.format == "stable"
        filename = "collection.db" if stable else "client.realm"
        if not messagebox.askyesno(
            "Save new collections copy?",
            f"Create {created}, edit {edited}, and delete {deleted} collections "
            f"in a NEW file?\n\nOutput:\n{output / filename}",
            parent=self.root,
        ):
            return

        def write():
            return save_workspace(self.workspace, output, self.backend)

        def saved(report):
            path = report["OutputFile"] if stable else report["OutputRealm"]
            checksum = report["OutputSha256"] if stable else report["OutputRealmSha256"]
            self.workspace.mark_saved(path, checksum)
            self.source.set("Working from: " + self.workspace.source_path)
            self.status.set(
                "Saved and verified the new collection.db."
                if stable
                else "Saved and verified the new Realm. "
                "Other database tables passed the data audit."
            )
            messagebox.showinfo(
                "Collections copy saved",
                f"Saved:\n{path}\n\n"
                "Changes and verification details are in import-report.json beside it.",
                parent=self.root,
            )

        self._task("Writing and verifying a new collections copy…", write, saved)

    def download_maps(self):
        if not self.workspace or self.busy:
            return
        if self.download_window:
            self.download_window.window.lift()
            return
        from tools.download_window import DownloadWindow

        self.download_window = DownloadWindow(self)

    def migrate_collections(self):
        if not self.workspace or self.busy or not self.workspace.collections:
            return
        if self.migration_window:
            self.migration_window.window.lift()
            return
        from tools.migration_window import MigrationWindow

        self.migration_window = MigrationWindow(self)

    def close(self):
        if self.migration_window:
            self.migration_window.close()
            return
        if self.download_window:
            self.download_window.close()
            return
        if self.busy:
            messagebox.showinfo(
                "Operation in progress",
                "Wait for the current operation to finish before closing.",
                parent=self.root,
            )
        elif self._discard_ok():
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    files = parser.add_mutually_exclusive_group()
    files.add_argument("--realm-copy", help="Open this copied Realm on startup")
    files.add_argument("--file", help="Open collection.db or a copied client.realm on startup")
    args = parser.parse_args()
    root = tk.Tk()
    app = CollectionStudio(root)
    if path := args.realm_copy or args.file:
        root.after(150, lambda: app.load(path))
    root.mainloop()


if __name__ == "__main__":
    main()
