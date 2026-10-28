"""Tk download queue; worker threads never access widgets or Realm files."""

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from tools.beatmap_downloads import (
    MIRRORS,
    Downloader,
    DownloadError,
    download_counts,
    load_download_progress,
)

SAVED_SCOPE = "Saved download queue"


class DownloadWindow:
    def __init__(self, app, downloader=None):
        self.app = app
        self.workspace = app.workspace
        self.window = tk.Toplevel(app.root)
        self.window.title("Missing beatmaps · Collections Studio")
        width = min(1100, max(900, self.window.winfo_screenwidth() - 80))
        height = min(760, max(700, self.window.winfo_screenheight() - 80))
        self.window.geometry(f"{width}x{height}")
        self.window.minsize(900, 700)
        self.window.configure(background="#141216")
        self.window.transient(app.root)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.running = False
        self.close_requested = False
        self.downloader = downloader or Downloader()
        self.hashes = []
        self.saved_hashes = []
        self.resume_mode = False
        self.states = {}
        self.report_path = None
        self.page = 0
        self._build()
        self.scan()
        self.window.bind("<Map>", self._grab_when_visible, add="+")
        self.window.update_idletasks()
        if self.window.winfo_viewable():
            self.window.grab_set()
        self.window.after(75, self.poll)

    def _grab_when_visible(self, event):
        if event.widget is self.window and self.window.winfo_viewable():
            self.window.grab_set()

    def _build(self):
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(2, weight=1)
        header = ttk.Frame(self.window, padding=20)
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Get missing beatmaps", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Download verified .osz archives, then import them into your osu! client.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 10))
        row = ttk.Frame(header)
        row.pack(fill="x")
        ttk.Label(row, text="Check:").pack(side="left", padx=(0, 8))
        choices = (["Last import"] if self.app.last_import_ids else []) + [
            "Selected collection",
            "All collections",
        ]
        self.scope = tk.StringVar(value=choices[0] if self.app.selected else "All collections")
        self.scope_box = ttk.Combobox(
            row,
            textvariable=self.scope,
            values=choices,
            state="readonly",
            width=24,
        )
        self.scope_box.pack(side="left")
        self.scope_box.bind("<<ComboboxSelected>>", lambda _event: self.scan())
        self.count = tk.StringVar()
        ttk.Label(row, textvariable=self.count, style="Muted.TLabel").pack(side="left", padx=12)
        ttk.Label(
            header,
            text="Mirrors tried in this order (left to right, top to bottom):",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(12, 4))
        mirrors = ttk.Frame(header)
        mirrors.pack(fill="x")
        self.mirror_flags = {}
        self.mirror_controls = []
        for index, mirror in enumerate(MIRRORS):
            flag = tk.BooleanVar(value=True)
            self.mirror_flags[mirror.name] = flag
            box = ttk.Checkbutton(mirrors, text=mirror.name, variable=flag)
            box.grid(row=index // 4, column=index % 4, sticky="w", padx=(0, 20), pady=2)
            self.mirror_controls.append(box)
        ttk.Label(
            header,
            text="MD5 lookup: " + ", ".join(m.name for m in MIRRORS if m.lookup) + ".",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(6, 0))

        destination = ttk.Frame(self.window, padding=(20, 0, 20, 12))
        destination.grid(row=1, column=0, sticky="ew")
        destination.columnconfigure(1, weight=1)
        ttk.Label(destination, text="Save folder:").grid(row=0, column=0, padx=(0, 8))
        self.directory = tk.StringVar(value=self.app.download_directory)
        self.directory_entry = ttk.Entry(destination, textvariable=self.directory)
        self.directory_entry.grid(row=0, column=1, sticky="ew")
        self.browse = ttk.Button(destination, text="Browse…", width=0, command=self.choose_folder)
        self.browse.grid(row=0, column=2, padx=(8, 0))
        self.resume_button = ttk.Button(
            destination, text="Resume queue…", width=0, command=self.resume_queue
        )
        self.resume_button.grid(row=0, column=3, padx=(8, 0))

        frame = ttk.Frame(self.window, padding=(20, 0))
        frame.grid(row=2, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.rows = ttk.Treeview(
            frame, columns=("map", "state", "mirror", "md5"), show="headings", selectmode="extended"
        )
        for key, title, width in [
            ("map", "Artist / title · difficulty", 430),
            ("state", "Status", 175),
            ("mirror", "Mirror", 100),
            ("md5", "MD5", 275),
        ]:
            self.rows.heading(key, text=title)
            self.rows.column(key, width=width, minwidth=65)
        self.rows.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.rows.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=self.rows.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.rows.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.rows.bind("<<TreeviewSelect>>", self.details)

        bottom = ttk.Frame(self.window, padding=20)
        bottom.grid(row=3, column=0, sticky="ew")
        pager = ttk.Frame(bottom)
        pager.pack(fill="x")
        ttk.Button(pager, text="Previous", width=0, command=lambda: self.change_page(-1)).pack(
            side="left"
        )
        self.page_text = tk.StringVar()
        ttk.Label(pager, textvariable=self.page_text, style="Muted.TLabel").pack(
            side="left", padx=12
        )
        ttk.Button(pager, text="Next", width=0, command=lambda: self.change_page(1)).pack(
            side="left"
        )
        controls = ttk.Frame(bottom)
        controls.pack(fill="x", pady=(8, 0))
        self.start_button = ttk.Button(controls, text="Download missing", command=self.start)
        self.start_button.pack(side="left", padx=(0, 8))
        self.selected_button = ttk.Button(
            controls, text="Download selected", command=lambda: self.start(selected=True)
        )
        self.selected_button.pack(side="left", padx=(0, 8))
        self.retry_button = ttk.Button(
            controls, text="Retry failed", command=lambda: self.start(retry=True)
        )
        self.retry_button.pack(side="left", padx=(0, 8))
        self.cancel_button = ttk.Button(
            controls, text="Cancel", command=self.cancel, state="disabled"
        )
        self.cancel_button.pack(side="right")
        self.progress = ttk.Progressbar(bottom, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(12, 8))
        self.status = tk.StringVar(
            value="Choose a download folder, or Resume queue… to continue a saved queue."
        )
        self.status_label = ttk.Label(
            bottom, textvariable=self.status, style="Muted.TLabel", wraplength=1020
        )
        self.status_label.pack(anchor="w", fill="x")
        self.detail = tk.StringVar(value="Select a row for its MD5 and result details.")
        self.detail_label = ttk.Label(
            bottom, textvariable=self.detail, style="Muted.TLabel", wraplength=1020
        )
        self.detail_label.pack(anchor="w", fill="x", pady=(6, 0))

        def wrap(event):
            for label in (self.status_label, self.detail_label):
                label.configure(wraplength=max(250, event.width - 40))

        bottom.bind("<Configure>", wrap)

    def scan(self):
        if self.running:
            return
        ids = (
            self.app.last_import_ids
            if self.scope.get() == "Last import"
            else {self.app.selected}
            if self.scope.get() == "Selected collection"
            else None
        )
        if self.scope.get() == SAVED_SCOPE:
            self.hashes = [
                checksum
                for checksum in self.saved_hashes
                if checksum not in self.workspace.present_hashes
            ]
        else:
            self.hashes = self.workspace.missing_hashes(ids)
            self.resume_mode = False
        self.page = 0
        self.count.set(f"{len(self.hashes):,} unique hashes missing from this library")
        self.refresh()

    def change_page(self, delta):
        self.page = max(0, min(max(0, (len(self.hashes) - 1) // 200), self.page + delta))
        self.refresh()

    def _values(self, checksum):
        details = self.workspace.beatmaps.get(checksum, {})
        label = " — ".join(str(details.get(key) or "") for key in ("Artist", "Title")).strip(" —")
        if details.get("Difficulty"):
            label += " [" + details["Difficulty"] + "]"
        state = self.states.get(checksum, {})
        return (
            label or "Waiting for MD5 lookup",
            state.get("state", "Queued"),
            state.get("mirror", ""),
            checksum,
        )

    def refresh(self):
        for row in self.rows.get_children():
            self.rows.delete(row)
        for checksum in self.hashes[self.page * 200 : (self.page + 1) * 200]:
            self.rows.insert("", "end", iid=checksum, values=self._values(checksum))
        self.page_text.set(f"Page {self.page + 1} / {max(1, (len(self.hashes) + 199) // 200)}")
        self.controls()

    def controls(self):
        ready, pending, failed, installed = download_counts(self.hashes, self.states)
        self.count.set(
            f"{ready - installed:,} downloaded · {installed:,} installed · "
            f"{pending:,} remaining · {failed:,} failed"
        )
        self.start_button.configure(
            text="Resume remaining" if self.resume_mode else "Download missing"
        )
        for button in (
            self.start_button,
            self.selected_button,
            self.retry_button,
            self.browse,
            self.resume_button,
        ):
            button.configure(state="disabled" if self.running else "normal")
        self.directory_entry.configure(state="disabled" if self.running else "normal")
        self.scope_box.configure(state="disabled" if self.running else "readonly")
        for control in self.mirror_controls:
            control.configure(state="disabled" if self.running else "normal")
        self.cancel_button.configure(state="normal" if self.running else "disabled")

    def choose_folder(self):
        directory = filedialog.askdirectory(
            parent=self.window, title="Save downloaded .osz archives"
        )
        if directory:
            self.directory.set(directory)
            self.app.download_directory = directory
            self.status.set(f"Ready to download {len(self.hashes):,} missing hashes.")

    def resume_queue(self):
        if self.running:
            return
        directory = filedialog.askdirectory(
            parent=self.window,
            title="Choose the download folder containing your saved queue",
            initialdir=self.directory.get() or None,
        )
        if not directory:
            return
        try:
            saved = load_download_progress(directory)
            if saved is None:
                raise DownloadError(
                    "This folder has no saved download queue. Choose its original folder."
                )
        except DownloadError as error:
            self.status.set(str(error))
            return
        self.directory.set(directory)
        self.app.download_directory = directory
        self.saved_hashes = saved["hashes"]
        self.states.clear()
        self.report_path = None
        self.progress.configure(value=0)
        choices = list(self.scope_box["values"])
        if SAVED_SCOPE not in choices:
            self.scope_box.configure(values=choices + [SAVED_SCOPE])
        self.scope.set(SAVED_SCOPE)
        if any(mirror.lookup and mirror.name in saved["mirrors"] for mirror in MIRRORS):
            for name, flag in self.mirror_flags.items():
                flag.set(name in saved["mirrors"])
        self.resume_mode = True
        self.scan()
        self.states.update(saved["failed"])
        self.states.update(saved["completed"])
        self.refresh()
        self.status.set(
            "Saved queue loaded. Resume remaining checks completed archives and downloads the rest."
        )
        self.detail.set("Keep this folder’s archives and download records together.")

    def details(self, _event=None):
        rows = self.rows.selection()
        if len(rows) == 1:
            result = self.states.get(rows[0], {})
            self.detail.set(
                rows[0]
                + " · "
                + result.get("message", result.get("file", result.get("state", "Queued")))
            )

    def start(self, selected=False, retry=False):
        if self.running:
            return
        hashes = list(self.rows.selection()) if selected else list(self.hashes)
        if retry:
            hashes = [
                checksum
                for checksum in hashes
                if self.states.get(checksum, {}).get("state") == "Failed"
            ]
        if not hashes:
            self.status.set("No missing maps in this selection.")
            return
        directory = Path(self.directory.get()).expanduser()
        if not self.directory.get() or not directory.is_dir():
            self.status.set("Choose an existing download folder first.")
            return
        mirrors = tuple(m for m in MIRRORS if self.mirror_flags[m.name].get())
        if not any(m.lookup for m in mirrors):
            self.status.set(
                "Enable an MD5 lookup mirror: " + ", ".join(m.name for m in MIRRORS if m.lookup)
            )
            return
        self.downloader.mirrors = mirrors
        self.app.download_directory = str(directory)
        self.stop.clear()
        self.running = True
        self.completed = 0
        self.total = len(hashes)
        self.progress.configure(value=0)
        self.controls()

        def work():
            try:
                result = self.downloader.run(
                    hashes,
                    directory,
                    self.events.put,
                    self.stop,
                    **({"retry_failed": True} if retry or selected else {}),
                )
                self.events.put({"kind": "done", "report": result})
            except Exception as error:
                self.events.put({"kind": "error", "message": str(error)})

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind, checksum = event["kind"], event.get("hash")
                if kind == "snapshot":
                    for h in event["hashes"]:
                        self.states.pop(h, None)
                    self.states.update(event["states"])
                    self.total = event["remaining"]
                    for h, state in event["states"].items():
                        if state["state"] == "Ready" and state.get("installed"):
                            self.workspace.present_hashes.add(h)
                            self.workspace.beatmaps[h] = {**state["details"], "Available": True}
                    self.refresh()
                elif kind in ("item", "result"):
                    self.states.setdefault(checksum, {}).update(event)
                    if kind == "result":
                        self.completed += 1
                        self.progress.configure(value=100 * self.completed / max(1, self.total))
                        if event["state"] == "Ready":
                            self.workspace.downloaded[checksum] = event["file"]
                            self.workspace.beatmaps[checksum] = event["details"]
                    self.status.set(
                        f"{self.completed}/{self.total} checked · " + event.get("state", "")
                    )
                elif kind == "metadata":
                    self.workspace.beatmaps[checksum] = event["details"]
                elif kind == "bytes":
                    mb = event["received"] / 1024 / 1024
                    self.status.set(
                        f"{event['mirror']} · {mb:.1f} MiB received · "
                        f"{self.completed}/{self.total} checked"
                    )
                elif kind == "log":
                    self.status.set(event["message"])
                elif kind in ("done", "error"):
                    self.running = False
                    if kind == "done":
                        report = event["report"]
                        self.report_path = report["report_path"]
                        ready, pending, failed, installed = download_counts(
                            self.hashes, self.states
                        )
                        self.resume_mode = True
                        self.status.set(
                            ("Paused. " if report.get("cancelled") else "")
                            + f"{ready - installed:,} downloaded; {installed:,} installed; "
                            + f"{pending:,} remaining; {failed:,} failed (Retry failed only). "
                            "Queue saved."
                        )
                        self.detail.set("Report: " + self.report_path)
                    else:
                        self.status.set(event["message"])
                        messagebox.showerror(
                            "Download failed", event["message"], parent=self.window
                        )
                    self.controls()
                    self.app.refresh_maps()
                    if self.close_requested:
                        self.close()
                        return
                if checksum and self.rows.exists(checksum):
                    self.rows.item(checksum, values=self._values(checksum))
        except queue.Empty:
            pass
        self.window.after(75, self.poll)

    def cancel(self):
        self.stop.set()
        self.status.set(
            "Stopping; completed archives and the queue stay saved. "
            "The current network read may take up to 15 seconds."
        )

    def close(self):
        if self.running:
            self.close_requested = True
            self.cancel()
        else:
            self.window.grab_release()
            self.window.destroy()
            self.app.download_window = None
