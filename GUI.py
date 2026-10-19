"""Tkinter GUI front end for Main.py (the PowerFlex 525 CLI).

Every action here builds the same argv the command line accepts and runs it
through ``Main.build_parser()`` / ``Main.main()``, so the GUI can never drift
from the CLI's behaviour - including its default-to-dry-run safety and its
``ConfirmationRequired`` checks. Network calls run on a background thread;
stdout/stderr/logging are redirected into a queue the GUI polls, so the
window never blocks or gets touched from another thread.

    python GUI.py
"""
from __future__ import annotations

import contextlib
import ipaddress
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import Main

DEFAULT_DUMP_NAME = "Drive Parameter Dump"


class QueueWriter:
    """File-like object that pushes writes into a queue instead of a stream."""

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, text: str) -> None:
        if text:
            self.q.put(text)

    def flush(self) -> None:
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PowerFlex 525 Tools")
        self.geometry("980x700")
        self.minsize(760, 560)

        self.drives: list[str] = []
        self.out_queue: queue.Queue[str] = queue.Queue()
        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._run_buttons: list[tk.Widget] = []
        self._busy = False

        self._build_drive_panel()
        self._build_options_panel()
        self._build_notebook()
        self._build_output_panel()
        self._build_status_bar()

        self.after(100, self._poll_queues)

    # -------------------------------------------------------------- drive list
    def _build_drive_panel(self) -> None:
        frame = ttk.LabelFrame(self, text="Drives")
        frame.pack(fill="x", padx=8, pady=(8, 4))

        list_frame = ttk.Frame(frame)
        list_frame.pack(side="left", fill="y", padx=(6, 10), pady=6)
        self.drive_list = tk.Listbox(list_frame, height=5, width=22, selectmode="extended",
                                     exportselection=False)
        self.drive_list.pack(side="left", fill="y")
        scrollbar = ttk.Scrollbar(list_frame, command=self.drive_list.yview)
        scrollbar.pack(side="left", fill="y")
        self.drive_list.config(yscrollcommand=scrollbar.set)

        controls = ttk.Frame(frame)
        controls.pack(side="left", fill="both", expand=True, pady=6)

        row1 = ttk.Frame(controls)
        row1.pack(fill="x")
        ttk.Label(row1, text="IP:").pack(side="left")
        self.ip_entry = ttk.Entry(row1, width=18)
        self.ip_entry.pack(side="left", padx=4)
        self.ip_entry.bind("<Return>", lambda _e: self._add_ip())
        ttk.Button(row1, text="Add", command=self._add_ip).pack(side="left", padx=2)
        ttk.Button(row1, text="Remove selected", command=self._remove_selected_ips).pack(side="left", padx=2)
        ttk.Button(row1, text="Clear", command=self._clear_ips).pack(side="left", padx=2)
        ttk.Button(row1, text="Load from file...", command=self._load_ip_file).pack(side="left", padx=2)

        row2 = ttk.Frame(controls)
        row2.pack(fill="x", pady=(8, 0))
        ttk.Label(row2, text="Discover for (s):").pack(side="left")
        self.discover_seconds = tk.StringVar(value="10")
        ttk.Entry(row2, width=6, textvariable=self.discover_seconds).pack(side="left", padx=4)
        self.discover_button = ttk.Button(row2, text="Discover now (adds to list)",
                                          command=self._discover_now)
        self.discover_button.pack(side="left", padx=4)
        self._run_buttons.append(self.discover_button)
        ttk.Label(row2, text="(leave the field set to also include fresh discoveries"
                             " in any run below)").pack(side="left", padx=6)

    def _add_ip(self) -> None:
        text = self.ip_entry.get().strip()
        if not text:
            return
        try:
            ip = str(ipaddress.ip_address(text))
        except ValueError:
            messagebox.showerror("Add drive", f"{text!r} is not a valid IP address")
            return
        if ip not in self.drives:
            self.drives.append(ip)
            self.drive_list.insert("end", ip)
        self.ip_entry.delete(0, "end")

    def _remove_selected_ips(self) -> None:
        for index in reversed(self.drive_list.curselection()):
            del self.drives[index]
            self.drive_list.delete(index)

    def _clear_ips(self) -> None:
        self.drives.clear()
        self.drive_list.delete(0, "end")

    def _load_ip_file(self) -> None:
        path = filedialog.askopenfilename(title="Drive list file",
                                          filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            ips = Main.read_ip_file(path)
        except OSError as exc:
            messagebox.showerror("Load from file", str(exc))
            return
        for ip in ips:
            try:
                ip = str(ipaddress.ip_address(ip))
            except ValueError:
                messagebox.showwarning("Load from file", f"Skipping invalid IP {ip!r}")
                continue
            if ip not in self.drives:
                self.drives.append(ip)
                self.drive_list.insert("end", ip)

    def _discover_now(self) -> None:
        seconds_text = self.discover_seconds.get().strip() or "10"
        try:
            seconds = float(seconds_text)
        except ValueError:
            messagebox.showerror("Discover", "Seconds must be a number")
            return
        if self._busy:
            return
        self._set_busy(True, "discovering")
        self._append(f"Discovering PowerFlex 525 drives for {seconds:g}s ...\n")
        threading.Thread(target=self._discover_worker, args=(seconds,), daemon=True).start()

    def _discover_worker(self, seconds: float) -> None:
        from pf525 import Network
        try:
            found = Network().discover(seconds)
        except Exception as exc:  # network errors here are non-fatal to the GUI
            self.out_queue.put(f"Discover failed: {exc}\n")
            found = []
        for ip in found:
            self.out_queue.put(f"  found {ip}\n")
        if not found:
            self.out_queue.put("  no new drives found\n")
        self.ui_queue.put(("discovered", found))
        self.ui_queue.put(("done", 0))

    # ----------------------------------------------------------------- options
    def _build_options_panel(self) -> None:
        frame = ttk.LabelFrame(self, text="Options (apply to every run below)")
        frame.pack(fill="x", padx=8, pady=4)

        ttk.Label(frame, text="Workers:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.workers = tk.StringVar(value="16")
        ttk.Spinbox(frame, from_=1, to=64, width=4, textvariable=self.workers).grid(
            row=0, column=1, sticky="w", pady=4)

        self.no_backup = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="No backup", variable=self.no_backup,
                        command=self._toggle_backup_dir).grid(row=0, column=2, sticky="w", padx=12)

        ttk.Label(frame, text="Backup dir:").grid(row=0, column=3, sticky="w", padx=(12, 0))
        self.backup_dir = tk.StringVar(value="pf525_backups")
        self.backup_dir_entry = ttk.Entry(frame, textvariable=self.backup_dir, width=22)
        self.backup_dir_entry.grid(row=0, column=4, sticky="w", padx=4)
        ttk.Button(frame, text="Browse...", command=self._browse_backup_dir).grid(
            row=0, column=5, sticky="w")

        ttk.Label(frame, text="Verbosity:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.verbosity = tk.StringVar(value="Normal")
        ttk.Combobox(frame, textvariable=self.verbosity, state="readonly", width=8,
                    values=["Normal", "-v", "-vv"]).grid(row=1, column=1, sticky="w")

        ttk.Label(frame, text="Log file:").grid(row=1, column=2, sticky="w", padx=12)
        self.log_file = tk.StringVar(value="")
        ttk.Entry(frame, textvariable=self.log_file, width=22).grid(row=1, column=3, sticky="w", padx=4)
        ttk.Button(frame, text="Browse...", command=self._browse_log_file).grid(
            row=1, column=4, sticky="w")

    def _toggle_backup_dir(self) -> None:
        self.backup_dir_entry.config(state="disabled" if self.no_backup.get() else "normal")

    def _browse_backup_dir(self) -> None:
        path = filedialog.askdirectory(title="Backup directory")
        if path:
            self.backup_dir.set(path)

    def _browse_log_file(self) -> None:
        path = filedialog.asksaveasfilename(title="Log file", defaultextension=".log")
        if path:
            self.log_file.set(path)

    def _common_argv(self) -> list[str]:
        argv: list[str] = []
        for ip in self.drives:
            argv += ["--ip", ip]
        if self.discover_seconds.get().strip():
            argv += ["--discover", self.discover_seconds.get().strip()]
        argv += ["--workers", self.workers.get() or "16"]
        if self.no_backup.get():
            argv += ["--no-backup"]
        else:
            argv += ["--backup-dir", self.backup_dir.get() or "pf525_backups"]
        verbosity = self.verbosity.get()
        if verbosity == "-v":
            argv.append("-v")
        elif verbosity == "-vv":
            argv.append("-vv")
        if self.log_file.get().strip():
            argv += ["--log-file", self.log_file.get().strip()]
        return argv

    # --------------------------------------------------------------- notebook
    def _build_notebook(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="x", padx=8, pady=4)
        self._build_read_tab()
        self._build_write_tab()
        self._build_search_tab()
        self._build_dump_tab()
        self._build_load_tab()
        self._build_health_tab()
        self._build_autotune_tab()
        self._build_restore_tab()

    def _tab(self, title: str) -> ttk.Frame:
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text=title)
        return frame

    def _run_button(self, parent: ttk.Frame, row: int, command) -> ttk.Button:
        button = ttk.Button(parent, text="Run", command=command)
        button.grid(row=row, column=0, sticky="w", pady=(10, 0))
        self._run_buttons.append(button)
        return button

    def _int_field(self, parent: ttk.Frame, row: int, label: str) -> tk.StringVar:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
        var = tk.StringVar()
        ttk.Entry(parent, textvariable=var, width=12).grid(row=row, column=1, sticky="w", padx=6)
        return var

    @staticmethod
    def _parse_int(var: tk.StringVar, what: str) -> int | None:
        text = var.get().strip()
        try:
            return int(text)
        except ValueError:
            messagebox.showerror("Invalid input", f"{what} must be a whole number, got {text!r}")
            return None

    def _build_read_tab(self) -> None:
        frame = self._tab("Read")
        param = self._int_field(frame, 0, "Parameter number:")

        def run():
            p = self._parse_int(param, "Parameter number")
            if p is None:
                return
            self._run(["read", str(p)])

        self._run_button(frame, 1, run)

    def _build_write_tab(self) -> None:
        frame = self._tab("Write")
        param = self._int_field(frame, 0, "Parameter number:")
        value = self._int_field(frame, 1, "New value:")
        apply_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Apply (actually write; otherwise dry run)",
                        variable=apply_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)

        def run():
            p, v = self._parse_int(param, "Parameter number"), self._parse_int(value, "Value")
            if p is None or v is None:
                return
            argv = ["write", str(p), str(v)] + (["--apply"] if apply_var.get() else [])
            confirm = (f"Write P{p} = {v} on {len(self.drives)} drive(s)?"
                      if apply_var.get() else None)
            self._run(argv, confirm)

        self._run_button(frame, 3, run)

    def _build_search_tab(self) -> None:
        frame = self._tab("Search")
        param = self._int_field(frame, 0, "Parameter number:")
        value = self._int_field(frame, 1, "Value:")
        matching_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="List drives that match instead of differ",
                        variable=matching_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)

        def run():
            p, v = self._parse_int(param, "Parameter number"), self._parse_int(value, "Value")
            if p is None or v is None:
                return
            argv = ["search", str(p), str(v)] + (["--matching"] if matching_var.get() else [])
            self._run(argv)

        self._run_button(frame, 3, run)

    def _build_dump_tab(self) -> None:
        frame = self._tab("Dump")
        ttk.Label(frame, text="Output file (.xlsx):").grid(row=0, column=0, sticky="w")
        output = tk.StringVar(value=DEFAULT_DUMP_NAME)
        ttk.Entry(frame, textvariable=output, width=40).grid(row=0, column=1, sticky="w", padx=6)

        def browse():
            path = filedialog.asksaveasfilename(title="Save dump as", defaultextension=".xlsx",
                                                initialfile=output.get())
            if path:
                output.set(path)

        ttk.Button(frame, text="Browse...", command=browse).grid(row=0, column=2)

        def run():
            if not output.get().strip():
                messagebox.showerror("Dump", "Enter an output file name")
                return
            self._run(["dump", "-o", output.get().strip()])

        self._run_button(frame, 1, run)

    def _build_load_tab(self) -> None:
        frame = self._tab("Load")
        ttk.Label(frame, text="Spreadsheet (.xlsx):").grid(row=0, column=0, sticky="w")
        file_var = tk.StringVar()
        ttk.Entry(frame, textvariable=file_var, width=40).grid(row=0, column=1, sticky="w", padx=6)

        def browse():
            path = filedialog.askopenfilename(title="Parameter spreadsheet",
                                              filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")])
            if path:
                file_var.set(path)

        ttk.Button(frame, text="Browse...", command=browse).grid(row=0, column=2)

        apply_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Apply (actually write; otherwise dry run)",
                        variable=apply_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=4)
        add_drives_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Also write drives named in the sheet but not in the list above",
                        variable=add_drives_var).grid(row=2, column=0, columnspan=3, sticky="w")

        def run():
            if not file_var.get().strip():
                messagebox.showerror("Load", "Choose a spreadsheet file")
                return
            argv = ["load", file_var.get().strip()]
            if apply_var.get():
                argv.append("--apply")
            if add_drives_var.get():
                argv.append("--add-sheet-drives")
            confirm = f"Write the values in {file_var.get()!r} to the drives?" if apply_var.get() else None
            self._run(argv, confirm)

        self._run_button(frame, 3, run)

    def _build_health_tab(self) -> None:
        frame = self._tab("Health")
        ttk.Label(frame, text="Config file (.toml/.json, optional):").grid(row=0, column=0, sticky="w")
        config_var = tk.StringVar()
        ttk.Entry(frame, textvariable=config_var, width=40).grid(row=0, column=1, sticky="w", padx=6)

        def browse_config():
            path = filedialog.askopenfilename(
                title="Health config",
                filetypes=[("TOML/JSON", "*.toml *.json"), ("All files", "*.*")])
            if path:
                config_var.set(path)

        ttk.Button(frame, text="Browse...", command=browse_config).grid(row=0, column=2)

        fix_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Fix (write the proposed fixes)",
                        variable=fix_var).grid(row=1, column=0, columnspan=2, sticky="w", pady=4)
        dry_run_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Dry run the fixes (show writes without making them)",
                        variable=dry_run_var).grid(row=2, column=0, columnspan=2, sticky="w")

        ttk.Label(frame, text="Also save findings as CSV (optional):").grid(
            row=3, column=0, sticky="w", pady=(8, 0))
        csv_var = tk.StringVar()
        ttk.Entry(frame, textvariable=csv_var, width=40).grid(row=3, column=1, sticky="w", padx=6)

        def browse_csv():
            path = filedialog.asksaveasfilename(title="Save findings as", defaultextension=".csv")
            if path:
                csv_var.set(path)

        ttk.Button(frame, text="Browse...", command=browse_csv).grid(row=3, column=2)

        def run():
            argv = ["health"]
            if config_var.get().strip():
                argv += ["--config", config_var.get().strip()]
            if fix_var.get():
                argv.append("--fix")
            if dry_run_var.get():
                argv.append("--dry-run")
            if csv_var.get().strip():
                argv += ["--csv", csv_var.get().strip()]
            confirm = ("Write the proposed fixes to every scanned drive?"
                      if fix_var.get() and not dry_run_var.get() else None)
            self._run(argv, confirm)

        self._run_button(frame, 4, run)

    def _build_autotune_tab(self) -> None:
        frame = self._tab("Autotune")
        ttk.Label(frame, text="STARTS THE MOTOR on every targeted drive.", foreground="red").grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, text="Network filter (CIDR, optional):").grid(row=1, column=0, sticky="w", pady=(8, 0))
        network_var = tk.StringVar()
        ttk.Entry(frame, textvariable=network_var, width=20).grid(row=1, column=1, sticky="w", padx=6)
        yes_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="The machinery is clear and safe to run",
                        variable=yes_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)

        def run():
            if not yes_var.get():
                messagebox.showerror("Autotune", "Confirm the machinery is clear first")
                return
            argv = ["autotune", "--yes"]
            if network_var.get().strip():
                argv += ["--network", network_var.get().strip()]
            self._run(argv, "This starts the motor on every targeted drive. Proceed?")

        self._run_button(frame, 3, run)

    def _build_restore_tab(self) -> None:
        frame = self._tab("Restore")
        ttk.Label(frame, text="Needs exactly one drive in the list above.").grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, text="Backup file (.json):").grid(row=1, column=0, sticky="w", pady=(8, 0))
        file_var = tk.StringVar()
        ttk.Entry(frame, textvariable=file_var, width=40).grid(row=1, column=1, sticky="w", padx=6)

        def browse():
            path = filedialog.askopenfilename(title="Backup file", initialdir="pf525_backups",
                                              filetypes=[("JSON", "*.json"), ("All files", "*.*")])
            if path:
                file_var.set(path)

        ttk.Button(frame, text="Browse...", command=browse).grid(row=1, column=2)
        apply_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Apply (actually write; otherwise dry run)",
                        variable=apply_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)

        def run():
            if len(self.drives) != 1:
                messagebox.showerror("Restore", "Restore needs exactly one drive in the list above")
                return
            if not file_var.get().strip():
                messagebox.showerror("Restore", "Choose a backup file")
                return
            argv = ["restore", file_var.get().strip()]
            if apply_var.get():
                argv.append("--apply")
            confirm = f"Write {file_var.get()!r} back to {self.drives[0]}?" if apply_var.get() else None
            self._run(argv, confirm)

        self._run_button(frame, 3, run)

    # ----------------------------------------------------------------- output
    def _build_output_panel(self) -> None:
        frame = ttk.LabelFrame(self, text="Output")
        frame.pack(fill="both", expand=True, padx=8, pady=4)
        self.output = ScrolledText(frame, height=16, state="disabled", wrap="word")
        self.output.pack(fill="both", expand=True, padx=4, pady=4)
        ttk.Button(frame, text="Clear output", command=self._clear_output).pack(anchor="e", padx=4, pady=(0, 4))

    def _clear_output(self) -> None:
        self.output.config(state="normal")
        self.output.delete("1.0", "end")
        self.output.config(state="disabled")

    def _append(self, text: str) -> None:
        self.output.config(state="normal")
        self.output.insert("end", text)
        self.output.see("end")
        self.output.config(state="disabled")

    def _build_status_bar(self) -> None:
        self.status = tk.StringVar(value="Idle")
        ttk.Label(self, textvariable=self.status, anchor="w", relief="sunken").pack(
            fill="x", side="bottom")

    # -------------------------------------------------------------- execution
    def _run(self, subcommand_args: list[str], confirm_message: str | None = None) -> None:
        if self._busy:
            return
        if not self.drives and not self.discover_seconds.get().strip() and subcommand_args[0] != "load":
            messagebox.showerror("No drives", "Add at least one drive, or set a discover time, first")
            return
        if confirm_message and not messagebox.askyesno("Confirm", confirm_message, icon="warning"):
            return
        argv = self._common_argv() + subcommand_args
        self._set_busy(True, subcommand_args[0])
        self._append(f"\n$ Main.py {' '.join(argv)}\n")
        threading.Thread(target=self._worker, args=(argv,), daemon=True).start()

    def _worker(self, argv: list[str]) -> None:
        writer = QueueWriter(self.out_queue)
        code = 2
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                code = Main.main(argv)
        except SystemExit as exc:          # argparse errors on bad input
            code = exc.code if isinstance(exc.code, int) else 2
        except Exception as exc:           # keep the GUI alive no matter what
            self.out_queue.put(f"Unexpected error: {exc!r}\n")
        self.out_queue.put(f"[exit code {code}]\n")
        self.ui_queue.put(("done", code))

    def _set_busy(self, busy: bool, what: str = "") -> None:
        self._busy = busy
        for button in self._run_buttons:
            button.config(state="disabled" if busy else "normal")
        self.status.set(f"Running: {what} ..." if busy else "Idle")

    def _poll_queues(self) -> None:
        try:
            while True:
                self._append(self.out_queue.get_nowait())
        except queue.Empty:
            pass
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "done":
                    self._set_busy(False)
                elif kind == "discovered":
                    for ip in payload:
                        if ip not in self.drives:
                            self.drives.append(ip)
                            self.drive_list.insert("end", ip)
        except queue.Empty:
            pass
        self.after(100, self._poll_queues)


if __name__ == "__main__":
    App().mainloop()
