#!/usr/bin/env python3
"""Market Tracker - desktop app (Tkinter, standard library only).

Run:  python3 market_tracker.py
Data is saved to ~/.market_tracker.json
"""
import json
import os
import shutil
import subprocess
import sys
import time


def ensure_tkinter():
    """If Tkinter is missing, install it automatically, then restart the app."""
    try:
        import tkinter  # noqa: F401
        return
    except ImportError:
        pass
    packages = {"dnf": ["dnf", "install", "-y", "python3-tkinter"],
                "apt": ["apt", "install", "-y", "python3-tk"],
                "pacman": ["pacman", "-S", "--noconfirm", "tk"]}
    manager = next((m for m in packages if shutil.which(m)), None)
    if manager is None:
        sys.exit("Tkinter is missing and no supported package manager was found. Please install it manually.")
    # pkexec shows a graphical password dialog; fall back to sudo if it isn't available
    elevate = ["pkexec"] if shutil.which("pkexec") else ["sudo"]
    if subprocess.call(elevate + packages[manager]) != 0:
        sys.exit("Automatic installation of Tkinter failed.")
    os.execv(sys.executable, [sys.executable] + sys.argv)  # restart so the new module is found


ensure_tkinter()

import tkinter as tk
from tkinter import ttk, font as tkfont

DATA = os.path.join(os.path.expanduser("~"), ".market_tracker.json")
CUR = "₹"
UNITS = ["pcs", "kg", "g", "L", "ml", "dozen", "pack"]
PAPER, BROWN, RED, GREEN = "#efe6d2", "#3a2314", "#a3321f", "#2f5d2a"


def money(n):
    """Format with Indian digit grouping, e.g. ₹1,00,000.00"""
    whole, frac = f"{round(n, 2):.2f}".split(".")
    if len(whole) > 3:
        head, tail, parts = whole[:-3], whole[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return f"{CUR}{whole}.{frac}"


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def calc(it):
    line = it["qty"] * it["price"]
    d = line * it["dv"] / 100 if it["dt"] == "pct" else it["dv"]
    d = min(max(d, 0), line)
    return line, d, line - d


class ItemDialog(tk.Toplevel):
    """Popup used for both adding and editing an item."""

    def __init__(self, app, item=None):
        super().__init__(app)
        self.result = None
        self.title("Edit item" if item else "Add item")
        self.transient(app)
        self.resizable(False, False)
        p = item or {"name": "", "details": "", "qty": 1, "unit": "pcs",
                     "price": "", "dt": "pct", "dv": ""}
        g = lambda x: f"{x:g}" if isinstance(x, (int, float)) else x
        self.v = {k: tk.StringVar(value=g(p[k])) for k in ("name", "details", "qty", "price", "dv")}
        self.unit = tk.StringVar(value=p["unit"])
        self.dt = tk.StringVar(value="%" if p["dt"] == "pct" else CUR)

        f = ttk.Frame(self, padding=20)
        f.pack()
        ttk.Label(f, text=self.title(), font=(app.fam, 18, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        disc = ttk.Frame(f)
        ttk.Entry(disc, textvariable=self.v["dv"], width=10).pack(side="left")
        ttk.Combobox(disc, textvariable=self.dt, values=["%", CUR], width=3, state="readonly").pack(side="left", padx=6)
        rows = [("Name", ttk.Entry(f, textvariable=self.v["name"], width=34)),
                ("Details", ttk.Entry(f, textvariable=self.v["details"], width=34)),
                ("Quantity", ttk.Entry(f, textvariable=self.v["qty"], width=10)),
                ("Unit", ttk.Combobox(f, textvariable=self.unit, values=UNITS, width=8, state="readonly")),
                (f"Unit price ({CUR})", ttk.Entry(f, textvariable=self.v["price"], width=10)),
                ("Discount", disc)]
        for i, (label, widget) in enumerate(rows, start=1):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", pady=4, padx=(0, 14))
            widget.grid(row=i, column=1, sticky="w", pady=4)
            if i == 1:
                widget.focus_set()
        self.hint = tk.Label(f, text="", fg=RED, anchor="w")
        self.hint.grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))
        btns = ttk.Frame(f)
        btns.grid(row=8, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=6)
        ttk.Button(btns, text="Save changes" if item else "Add item", command=self.submit).pack(side="left")
        self.bind("<Return>", self.submit)
        self.bind("<Escape>", lambda e: self.destroy())

        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_width()) // 2
        y = app.winfo_rooty() + (app.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.wait_visibility()
        self.grab_set()

    def submit(self, _=None):
        name = self.v["name"].get().strip()
        qty, price = num(self.v["qty"].get()), num(self.v["price"].get())
        dv_text = self.v["dv"].get().strip()
        dv = num(dv_text) if dv_text else 0.0
        dt = "pct" if self.dt.get() == "%" else "fix"
        err = ""
        if not name:
            err = "Enter an item name."
        elif qty is None or qty <= 0:
            err = "Quantity must be more than 0."
        elif price is None or price < 0:
            err = "Enter a price of 0 or more."
        elif dv is None or dv < 0:
            err = "Enter a valid discount (0 or more)."
        elif dt == "pct" and dv > 100:
            err = "A percentage discount can't exceed 100."
        elif dt == "fix" and dv > qty * price:
            err = "Discount is larger than the item total."
        if err:
            self.hint.config(text=err)
            return
        self.result = {"name": name, "details": self.v["details"].get().strip(), "qty": qty,
                       "unit": self.unit.get(), "price": price, "dt": dt, "dv": dv}
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Market Tracker")
        self.geometry("780x860")
        self.minsize(560, 520)
        self.configure(bg=PAPER)
        fams = set(tkfont.families(self))
        # Uses Doto if you have it installed, otherwise a monospace fallback.
        self.fam = next((f for f in ("Doto", "DejaVu Sans Mono", "Courier New") if f in fams), "Courier")
        self.items, self.bill_type, bill_val = self.load()
        self.bill_val = tk.StringVar(value=bill_val)
        self.undo_data, self.undo_job = None, None
        self.build()
        self.refresh()

    # ---------- storage ----------
    def load(self):
        try:
            with open(DATA, encoding="utf-8") as fh:
                d = json.load(fh)
            return d.get("items", []), d.get("bill", {}).get("t", "pct"), d.get("bill", {}).get("v", "")
        except (OSError, ValueError):
            return [], "pct", ""

    def save(self):
        try:
            with open(DATA, "w", encoding="utf-8") as fh:
                json.dump({"items": self.items, "bill": {"t": self.bill_type, "v": self.bill_val.get()}}, fh)
        except OSError:
            pass

    # ---------- layout ----------
    def f(self, size, strike=False, underline=False):
        style = ("bold",) + (("overstrike",) if strike else ()) + (("underline",) if underline else ())
        return (self.fam, size) + style

    def build(self):
        head = tk.Frame(self, bg=PAPER)
        head.pack(fill="x", padx=28, pady=(24, 8))
        tk.Label(head, text="Market Tracker", font=self.f(30), bg=PAPER, fg=BROWN).pack(side="left")
        clear = tk.Label(head, text="Clear all", font=self.f(12, underline=True), bg=PAPER, fg=BROWN, cursor="hand2")
        clear.pack(side="right")
        clear.bind("<Button-1>", lambda e: self.clear_all())

        wrap = tk.Frame(self, bg=PAPER)
        wrap.pack(fill="both", expand=True, padx=(28, 0))
        self.canvas = tk.Canvas(wrap, bg=PAPER, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=PAPER)
        win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width - 28))
        self.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

        self.list_frame = tk.Frame(self.body, bg=PAPER)
        self.list_frame.pack(fill="x")

        add_row = tk.Frame(self.body, bg=PAPER)
        add_row.pack(fill="x", pady=(10, 0))
        plus = tk.Canvas(add_row, width=54, height=54, bg=PAPER, highlightthickness=0, cursor="hand2")
        plus.create_oval(2, 2, 52, 52, fill=BROWN, outline=BROWN)
        plus.create_line(27, 16, 27, 38, fill=PAPER, width=4, capstyle="round")
        plus.create_line(16, 27, 38, 27, fill=PAPER, width=4, capstyle="round")
        plus.bind("<Button-1>", lambda e: self.open_dialog())
        plus.pack(side="right")

        rule = tk.Canvas(self.body, height=4, bg=PAPER, highlightthickness=0)
        rule.pack(fill="x", pady=(18, 12))
        rule.create_line(0, 2, 4000, 2, fill=BROWN, width=2, dash=(8, 5))

        s = tk.Frame(self.body, bg=PAPER)
        s.pack(fill="x", pady=(0, 70))
        s.columnconfigure(1, weight=1)
        self.sub = self.summary_row(s, 0, "Subtotal")
        self.itemd = self.summary_row(s, 1, "Item discounts")
        tk.Label(s, text="Bill discount", font=self.f(13), bg=PAPER, fg=BROWN).grid(row=2, column=0, sticky="w", pady=4)
        ctl = tk.Frame(s, bg=PAPER)
        ctl.grid(row=2, column=1, sticky="e", padx=12)
        tk.Entry(ctl, textvariable=self.bill_val, width=8, font=self.f(12), bg="#f8f2e4", fg=BROWN,
                 relief="solid", bd=2, highlightthickness=0).pack(side="left")
        cb = ttk.Combobox(ctl, values=["%", CUR], width=3, state="readonly")
        cb.set("%" if self.bill_type == "pct" else CUR)
        cb.bind("<<ComboboxSelected>>", lambda e: self.on_bill_type(cb.get()))
        cb.pack(side="left", padx=6)
        self.billamt = tk.Label(s, text="", font=self.f(13), bg=PAPER, fg=BROWN)
        self.billamt.grid(row=2, column=2, sticky="e")
        self.bill_val.trace_add("write", lambda *a: (self.update_summary(), self.save()))
        tk.Label(s, text="Total", font=self.f(20), bg=PAPER, fg=BROWN).grid(row=3, column=0, sticky="w", pady=(14, 0))
        self.total = tk.Label(s, text="", font=self.f(38), bg=PAPER, fg=BROWN)
        self.total.grid(row=3, column=1, columnspan=2, sticky="e", pady=(14, 0))
        self.saved = tk.Label(s, text="", font=self.f(13), bg=PAPER, fg=GREEN)
        self.saved.grid(row=4, column=0, columnspan=3, sticky="e")

        self.bar = tk.Frame(self, bg=BROWN)
        self.bar_msg = tk.Label(self.bar, bg=BROWN, fg=PAPER, font=self.f(12))
        self.bar_msg.pack(side="left", padx=(14, 10), pady=8)
        undo = tk.Label(self.bar, text="Undo", bg=BROWN, fg=PAPER, font=self.f(12, underline=True), cursor="hand2")
        undo.bind("<Button-1>", lambda e: self.undo())
        undo.pack(side="left", padx=(0, 14))

    def summary_row(self, parent, r, text):
        tk.Label(parent, text=text, font=self.f(13), bg=PAPER, fg=BROWN).grid(row=r, column=0, sticky="w", pady=4)
        val = tk.Label(parent, text="", font=self.f(13), bg=PAPER, fg=BROWN)
        val.grid(row=r, column=2, sticky="e")
        return val

    def icon(self, parent, kind, cmd):
        c = tk.Canvas(parent, width=24, height=24, bg=PAPER, highlightthickness=0, cursor="hand2")

        def draw(col):
            c.delete("all")
            if kind == "edit":  # tilted pencil
                c.create_polygon(16, 3, 21, 8, 9, 20, 3, 21, 4, 15, outline=col, fill="", width=2, joinstyle="round")
                c.create_line(13, 6, 18, 11, fill=col, width=2)
            else:  # dustbin
                c.create_line(4, 7, 20, 7, fill=col, width=2, capstyle="round")
                c.create_line(9, 7, 9, 4, 15, 4, 15, 7, fill=col, width=2)
                c.create_polygon(6, 7, 7, 21, 17, 21, 18, 7, outline=col, fill="", width=2, joinstyle="round")
                c.create_line(10, 11, 10, 17, fill=col, width=2)
                c.create_line(14, 11, 14, 17, fill=col, width=2)

        hover = RED if kind == "del" else "#8a5a2b"
        draw(BROWN)
        c.bind("<Enter>", lambda e: draw(hover))
        c.bind("<Leave>", lambda e: draw(BROWN))
        c.bind("<Button-1>", lambda e: cmd())
        return c

    # ---------- rendering ----------
    def refresh(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        if not self.items:
            tk.Label(self.list_frame, text="Nothing here yet. Press + to add your first item.",
                     font=self.f(13), bg=PAPER, fg=BROWN).pack(anchor="w", pady=24)
        for i, it in enumerate(self.items):
            self.make_row(it, first=(i == 0))
        self.update_summary()

    def make_row(self, it, first):
        line, d, net = calc(it)
        if not first:
            sep = tk.Canvas(self.list_frame, height=3, bg=PAPER, highlightthickness=0)
            sep.pack(fill="x")
            sep.create_line(0, 1, 4000, 1, fill=BROWN, dash=(1, 4))
        row = tk.Frame(self.list_frame, bg=PAPER)
        row.pack(fill="x")
        row.columnconfigure(1, weight=1)
        var = tk.BooleanVar(value=it["bought"])
        tk.Checkbutton(row, variable=var, bg=PAPER, activebackground=PAPER, selectcolor="white", bd=0,
                       highlightthickness=0, command=lambda: self.toggle(it, var)).grid(row=0, column=0, padx=(0, 10), pady=12, sticky="n")
        info = tk.Frame(row, bg=PAPER)
        info.grid(row=0, column=1, sticky="w", pady=12)
        top = tk.Frame(info, bg=PAPER)
        top.pack(anchor="w")
        tk.Label(top, text=it["name"], font=self.f(15, strike=it["bought"]), bg=PAPER, fg=BROWN).pack(side="left")
        if d > 0:
            tk.Label(top, text=f"-{money(d)}", font=self.f(10), bg=PAPER, fg=GREEN).pack(side="left", padx=8)
        self.icon(top, "edit", lambda: self.open_dialog(it)).pack(side="left", padx=(8, 0))
        self.icon(top, "del", lambda: self.delete(it)).pack(side="left", padx=(4, 0))
        if it["details"]:
            tk.Label(info, text=it["details"], font=self.f(11, strike=False), bg=PAPER, fg=BROWN).pack(anchor="w")
        tk.Label(info, text=f'{it["qty"]:g} {it["unit"]} × {money(it["price"])}', font=self.f(11), bg=PAPER, fg=BROWN).pack(anchor="w")
        right = tk.Frame(row, bg=PAPER)
        right.grid(row=0, column=2, sticky="ne", pady=12, padx=(10, 0))
        if d > 0:
            tk.Label(right, text=money(line), font=self.f(10, strike=True), bg=PAPER, fg=BROWN).pack(anchor="e")
        tk.Label(right, text=money(net), font=self.f(15, strike=it["bought"]), bg=PAPER, fg=BROWN).pack(anchor="e")

    def update_summary(self):
        sub = disc = 0.0
        for it in self.items:
            _, d, net = calc(it)
            sub += net
            disc += d
        bv = num(self.bill_val.get()) or 0.0
        bd = sub * bv / 100 if self.bill_type == "pct" else bv
        bd = min(max(bd, 0), sub)
        self.sub.config(text=money(sub + disc))
        self.itemd.config(text=("-" + money(disc)) if disc > 0 else money(0))
        self.billamt.config(text=("-" + money(bd)) if bd > 0 else money(0))
        self.total.config(text=money(sub - bd))
        self.saved.config(text=f"You saved {money(disc + bd)}" if disc + bd > 0 else "")

    # ---------- actions ----------
    def on_bill_type(self, value):
        self.bill_type = "pct" if value == "%" else "fix"
        self.update_summary()
        self.save()

    def toggle(self, it, var):
        it["bought"] = var.get()
        self.save()
        self.refresh()

    def open_dialog(self, item=None):
        dlg = ItemDialog(self, item)
        self.wait_window(dlg)
        if not dlg.result:
            return
        if item:
            item.update(dlg.result)
        else:
            self.items.append({"id": time.time(), "bought": False, **dlg.result})
            self.after(60, lambda: self.canvas.yview_moveto(1))
        self.save()
        self.refresh()

    def delete(self, it):
        self.show_undo(f"Deleted {it['name']}")
        self.items = [i for i in self.items if i is not it]
        self.save()
        self.refresh()

    def clear_all(self):
        if not self.items:
            return
        self.show_undo("Cleared all items")
        self.items = []
        self.save()
        self.refresh()

    def show_undo(self, msg):
        self.undo_data = json.dumps(self.items)
        self.bar_msg.config(text=msg)
        self.bar.place(relx=0.5, rely=1.0, y=-20, anchor="s")
        if self.undo_job:
            self.after_cancel(self.undo_job)
        self.undo_job = self.after(6000, self.bar.place_forget)

    def undo(self):
        if self.undo_data:
            self.items = json.loads(self.undo_data)
            self.undo_data = None
            self.save()
            self.refresh()
        self.bar.place_forget()


if __name__ == "__main__":
    App().mainloop()