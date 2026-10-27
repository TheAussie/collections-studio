"""Choose and copy collections to the other osu! collection format."""

import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from uuid import uuid4

from tools.collection_migration import capture_source, migrate


class MigrationWindow:
    def __init__(self, app):
        self.app = app
        self.workspace = app.workspace
        self.to_stable = self.workspace.format == "realm"
        self.running = False
        self.events = queue.Queue()
        self.result = None
        self.window = tk.Toplevel(app.root)
        self.window.title("Migrate collections · Collections Studio")
        width = min(1000, max(900, self.window.winfo_screenwidth() - 80))
        height = min(800, max(700, self.window.winfo_screenheight() - 80))
        self.window.geometry(f"{width}x{height}")
        self.window.minsize(900, 700)
        self.window.configure(background="#141216")
        self.window.transient(app.root)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.grab_set()
        self._build()
        self.select_all()
        self.poll_id = self.window.after(100, self.poll)

    def _build(self):
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)
        header = ttk.Frame(self.window, padding=(20, 20, 20, 10))
        header.grid(row=0, column=0, sticky="ew")
        direction = "lazer → stable" if self.to_stable else "stable → lazer"
        ttk.Label(header, text="Migrate collections: " + direction, style="Heading.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            header,
            text="Copy all or selected collections into a verified new file.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(6, 0))
        if self.workspace.dirty:
            ttk.Label(
                header, text="Includes your unsaved collection edits.", style="Muted.TLabel"
            ).pack(anchor="w", pady=(4, 0))
        selection = ttk.Frame(header)
        selection.pack(fill="x", pady=(12, 0))
        self.all_button = ttk.Button(selection, text="Select all", width=0, command=self.select_all)
        self.all_button.pack(side="left", padx=(0, 8))
        self.none_button = ttk.Button(
            selection,
            text="Clear selection",
            width=0,
            command=lambda: self.groups.selection_remove(self.groups.selection()),
        )
        self.none_button.pack(side="left", padx=(0, 8))
        self.current_button = ttk.Button(
            selection, text="Current collection", width=0, command=self.select_current
        )
        self.current_button.pack(side="left")
        self.selection_text = tk.StringVar()
        ttk.Label(selection, textvariable=self.selection_text, style="Muted.TLabel").pack(
            side="right"
        )

        frame = ttk.Frame(self.window, padding=(20, 0))
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.groups = ttk.Treeview(
            frame, columns=("maps",), show="tree headings", selectmode="extended", height=6
        )
        self.groups.heading("#0", text="Collections to copy · Ctrl/Shift to select")
        self.groups.heading("maps", text="Maps")
        self.groups.column("#0", width=600, minwidth=300)
        self.groups.column("maps", width=100, minwidth=80, stretch=False, anchor="e")
        self.groups.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.groups.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.groups.configure(yscrollcommand=scroll.set)
        for group in self.workspace.collections:
            self.groups.insert(
                "", "end", iid=group["Id"], text=group["Name"], values=(len(group["Hashes"]),)
            )
        self.groups.bind("<<TreeviewSelect>>", lambda _event: self.selected())
        self.groups.bind("<Control-a>", lambda _event: self.select_all())

        destination = ttk.Frame(self.window, padding=(20, 12, 20, 0))
        destination.grid(row=2, column=0, sticky="ew")
        destination.columnconfigure(0, weight=1)
        self.merge_existing = tk.BooleanVar(value=not self.to_stable)
        if self.to_stable:
            self.merge_check = ttk.Checkbutton(
                destination,
                text="Merge with an existing collection.db (optional)",
                variable=self.merge_existing,
                command=self.target_controls,
            )
            self.merge_check.grid(row=0, column=0, sticky="w", pady=(0, 6))
        else:
            ttk.Label(destination, text="Destination: choose an existing copied client.realm").grid(
                row=0, column=0, sticky="w", pady=(0, 6)
            )
            self.merge_check = None
        self.target = tk.StringVar()
        self.target_entry = ttk.Entry(destination, textvariable=self.target)
        self.target_entry.grid(row=1, column=0, sticky="ew")
        self.target_button = ttk.Button(
            destination, text="Browse…", width=0, command=self.choose_target
        )
        self.target_button.grid(row=1, column=1, padx=(8, 0))
        ttk.Label(
            destination,
            text="Matching names merge by MD5. Other destination collections are retained.",
            style="Muted.TLabel",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        output = ttk.Frame(self.window, padding=(20, 12, 20, 0))
        output.grid(row=3, column=0, sticky="ew")
        output.columnconfigure(0, weight=1)
        self.output_parent = tk.StringVar(
            value=str(Path(self.workspace.source_path).parent.resolve())
        )
        self.output_name = (
            "collections-migration-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:6]
        )
        ttk.Label(output, text="Create the result in this folder:").grid(
            row=0, column=0, sticky="w"
        )
        self.parent_entry = ttk.Entry(output, textvariable=self.output_parent)
        self.parent_entry.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.parent_button = ttk.Button(output, text="Browse…", width=0, command=self.choose_parent)
        self.parent_button.grid(row=1, column=1, padx=(8, 0), pady=(6, 0))
        self.output_text = tk.StringVar()
        self.output_label = ttk.Label(
            output, textvariable=self.output_text, style="Muted.TLabel", wraplength=940
        )
        self.output_label.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.output_parent.trace_add("write", lambda *_args: self.update_output())
        self.update_output()
        output.bind(
            "<Configure>",
            lambda event: self.output_label.configure(wraplength=max(250, event.width - 40)),
        )

        footer = ttk.Frame(self.window, padding=20)
        footer.grid(row=4, column=0, sticky="ew")
        self.progress = ttk.Progressbar(footer, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 10))
        row = ttk.Frame(footer)
        row.pack(fill="x")
        self.start_button = ttk.Button(
            row,
            text="Migrate to " + ("collection.db" if self.to_stable else "client.realm"),
            style="Accent.TButton",
            width=0,
            command=self.start,
        )
        self.start_button.pack(side="left")
        self.close_button = ttk.Button(row, text="Close", width=0, command=self.close)
        self.close_button.pack(side="right")
        self.status = tk.StringVar(value="Source and destination inputs stay unchanged.")
        self.status_label = ttk.Label(
            footer, textvariable=self.status, style="Muted.TLabel", wraplength=940
        )
        self.status_label.pack(anchor="w", fill="x", pady=(10, 0))
        footer.bind(
            "<Configure>",
            lambda event: self.status_label.configure(wraplength=max(250, event.width - 40)),
        )
        self.target_controls()

    def selected(self):
        selected = set(self.groups.selection())
        count = sum(
            len(group["Hashes"]) for group in self.workspace.collections if group["Id"] in selected
        )
        self.selection_text.set(f"{len(selected)} selected · {count:,} memberships")
        self.start_button.configure(state="normal" if selected and not self.running else "disabled")

    def select_all(self):
        self.groups.selection_set(self.groups.get_children())
        self.selected()
        return "break"

    def select_current(self):
        self.groups.selection_set((self.app.selected,) if self.app.selected else ())
        self.selected()

    def target_controls(self):
        enabled = self.merge_existing.get() and not self.running
        self.target_entry.configure(state="normal" if enabled else "disabled")
        self.target_button.configure(state="normal" if enabled else "disabled")

    def choose_target(self):
        target = filedialog.askopenfilename(
            parent=self.window,
            title="Select destination collection.db"
            if self.to_stable
            else "Select a destination Realm copy",
            filetypes=[
                ("Collection database", "*.db" if self.to_stable else "*.realm"),
                ("All files", "*"),
            ],
        )
        if target:
            self.target.set(target)

    def choose_parent(self):
        path = filedialog.askdirectory(parent=self.window, title="Create migrated collections here")
        if path:
            self.output_parent.set(path)

    def update_output(self):
        filename = "collection.db" if self.to_stable else "client.realm"
        self.output_text.set(
            "New file: " + str(Path(self.output_parent.get()) / self.output_name / filename)
        )

    def controls(self):
        for button in (
            self.all_button,
            self.none_button,
            self.current_button,
            self.parent_button,
            self.parent_entry,
        ):
            button.configure(state="disabled" if self.running else "normal")
        if self.merge_check:
            self.merge_check.configure(state="disabled" if self.running else "normal")
        self.target_controls()
        self.selected()

    def start(self):
        if self.running:
            return
        try:
            source = capture_source(self.workspace, self.groups.selection())
            target = self.target.get().strip() if self.merge_existing.get() else ""
            if self.merge_existing.get() and (not target or not Path(target).is_file()):
                raise ValueError("Choose the destination database file first.")
            if not self.output_parent.get() or not Path(self.output_parent.get()).is_dir():
                raise ValueError("Choose an existing output parent folder.")
        except ValueError as error:
            self.status.set(str(error))
            return
        output = Path(self.output_parent.get()) / self.output_name
        self.running = True
        self.controls()
        self.progress.start(12)
        self.status.set("Copying and verifying collections. A large Realm can take a moment…")

        def work():
            try:
                self.events.put(
                    (migrate(source, output, backend=self.app.backend, target_path=target), None)
                )
            except Exception as error:
                self.events.put((None, error))

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            result, error = self.events.get_nowait()
        except queue.Empty:
            self.poll_id = self.window.after(100, self.poll)
            return
        self.running = False
        self.progress.stop()
        self.controls()
        if error:
            self.status.set("Migration failed. No output was published.")
            messagebox.showerror("Migration failed", str(error), parent=self.window)
        else:
            self.result = result
            self.status.set(
                f"Verified: {result['Created']} new collections, {result['Updated']} merged. "
                f"Saved: {result['OutputFile']}"
            )
            self.output_name = (
                "collections-migration-"
                + datetime.now().strftime("%Y%m%d-%H%M%S-")
                + uuid4().hex[:6]
            )
            self.update_output()
            messagebox.showinfo(
                "Migration complete",
                f"Saved and verified:\n{result['OutputFile']}\n\n"
                f"Report:\n{result['ReportPath']}\n\n"
                "Your input files and editing session are unchanged.",
                parent=self.window,
            )
        self.poll_id = self.window.after(100, self.poll)

    def close(self):
        if self.running:
            self.status.set("Wait for copying and verification to finish before closing.")
            return
        self.window.grab_release()
        self.window.after_cancel(self.poll_id)
        self.window.destroy()
        self.app.migration_window = None
