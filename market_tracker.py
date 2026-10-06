#!/usr/bin/env python3
"""Market Tracker - desktop app (Tkinter + Supabase, standard library only).

Run:  python3 market_tracker.py
Log in with the same account as the web app and your list is shared.
"""
import datetime
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

SB_URL = "https://qyytskjlycyfymsjogqc.supabase.co"
SB_KEY = "sb_publishable_Rx_X89TBIXA7ep6Kv97UQQ_Z59eKfdQ"


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
    elevate = ["pkexec"] if shutil.which("pkexec") else ["sudo"]
    if subprocess.call(elevate + packages[manager]) != 0:
        sys.exit("Automatic installation of Tkinter failed.")
    os.execv(sys.executable, [sys.executable] + sys.argv)


ensure_tkinter()

import tkinter as tk
from tkinter import ttk, font as tkfont, messagebox

HOME = os.path.expanduser("~")
SESSION_FILE = os.path.join(HOME, ".market_tracker_session.json")
OLD_DATA = os.path.join(HOME, ".market_tracker.json")            # list saved by the older local-only version
IMPORTED_FILE = os.path.join(HOME, ".market_tracker_imported.json")
CUR = "₹"
UNITS = ["pcs", "kg", "g", "L", "ml", "dozen", "pack"]
PAPER, BROWN, RED, GREEN = "#efe6d2", "#3a2314", "#a3321f", "#2f5d2a"


# ---------------------------------------------------------------- helpers
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


def now_iso(offset_ms=0):
    t = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(milliseconds=offset_ms)
    return t.isoformat()


def from_row(r):
    return {"id": r["id"], "name": r["name"], "details": r.get("details") or "", "qty": float(r["qty"]),
            "unit": r["unit"], "price": float(r["price"]), "dt": r["discount_type"],
            "dv": float(r["discount_value"]), "bought": bool(r["bought"]), "at": r["created_at"]}


def to_row(i, full=False):
    r = {"name": i["name"], "details": i["details"], "qty": i["qty"], "unit": i["unit"], "price": i["price"],
         "discount_type": i["dt"], "discount_value": i["dv"], "bought": bool(i.get("bought"))}
    if full:
        r["id"], r["created_at"] = i["id"], i["at"]
    return r


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------- Supabase client (REST over HTTPS)
class ApiError(Exception):
    status = 0


class Cloud:
    def __init__(self):
        self.s = read_json(SESSION_FILE, None)  # {access_token, refresh_token, expires_at, user_id, email}
        self.lock = threading.Lock()

    def _req(self, method, path, body=None, token=None, headers=None):
        h = {"apikey": SB_KEY, "Content-Type": "application/json"}
        if token:
            h["Authorization"] = "Bearer " + token
        if headers:
            h.update(headers)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(SB_URL + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                d = json.loads(raw)
                msg = d.get("msg") or d.get("message") or d.get("error_description") or d.get("error") or raw
            except ValueError:
                msg = raw
            err = ApiError(msg)
            err.status = e.code
            raise err
        except (urllib.error.URLError, OSError):
            raise ApiError("Can't reach the server. Check your internet connection.")

    def _set(self, d):
        self.s = {"access_token": d["access_token"], "refresh_token": d["refresh_token"],
                  "expires_at": time.time() + d.get("expires_in", 3600) - 30,
                  "user_id": d["user"]["id"], "email": d["user"].get("email", "")}
        fd = os.open(SESSION_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.s, fh)

    def sign_in(self, email, password):
        self._set(self._req("POST", "/auth/v1/token?grant_type=password", {"email": email, "password": password}))

    def sign_up(self, email, password):
        d = self._req("POST", "/auth/v1/signup", {"email": email, "password": password})
        if d and d.get("access_token"):
            self._set(d)
            return True
        return False  # email confirmation is required first

    def refresh(self):
        with self.lock:
            if not self.s:
                raise ApiError("Not logged in.")
            self._set(self._req("POST", "/auth/v1/token?grant_type=refresh_token",
                                {"refresh_token": self.s["refresh_token"]}))

    def sign_out(self):
        try:
            if self.s:  # scope=local: only this device is logged out, not your phone
                self._req("POST", "/auth/v1/logout?scope=local", token=self.s["access_token"])
        except ApiError:
            pass
        self.s = None
        try:
            os.remove(SESSION_FILE)
        except OSError:
            pass

    def rest(self, method, path, body=None, prefer=None):
        if not self.s:
            raise ApiError("Not logged in.")
        if time.time() > self.s["expires_at"]:
            self.refresh()
        h = {"Prefer": prefer} if prefer else None
        try:
            return self._req(method, "/rest/v1/" + path, body, self.s["access_token"], h)
        except ApiError as e:
            if e.status != 401:
                raise
            self.refresh()
            return self._req(method, "/rest/v1/" + path, body, self.s["access_token"], h)


class Worker:
    """Runs network jobs one at a time in the background so the window never freezes."""

    def __init__(self):
        self.jobs, self.done = queue.Queue(), queue.Queue()
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            fn, ok, bad = self.jobs.get()
            try:
                self.done.put((ok, fn(), None))
            except ApiError as e:
                self.done.put((bad, None, e))
            except Exception as e:  # noqa: BLE001
                self.done.put((bad, None, ApiError(str(e))))


# ---------------------------------------------------------------- dialogs
class LoginDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Market Tracker - Log in")
        self.resizable(False, False)
        self.email, self.pw = tk.StringVar(), tk.StringVar()
        f = ttk.Frame(self, padding=24)
        f.pack()
        ttk.Label(f, text="Market Tracker", font=(app.fam, 20, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text="Log in to keep your list in the cloud.").grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 14))
        ttk.Label(f, text="Email").grid(row=2, column=0, sticky="w", pady=4, padx=(0, 14))
        first = ttk.Entry(f, textvariable=self.email, width=32)
        first.grid(row=2, column=1, pady=4)
        ttk.Label(f, text="Password").grid(row=3, column=0, sticky="w", pady=4, padx=(0, 14))
        ttk.Entry(f, textvariable=self.pw, show="•", width=32).grid(row=3, column=1, pady=4)
        self.m = tk.Label(f, text="", fg=RED, wraplength=320, justify="left", anchor="w")
        self.m.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        btns = ttk.Frame(f)
        btns.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Create account", command=self.signup).pack(side="left", padx=6)
        ttk.Button(btns, text="Log in", command=self.login).pack(side="left")
        self.bind("<Return>", lambda e: self.login())
        self.update_idletasks()
        x = (self.winfo_screenwidth() - self.winfo_width()) // 2
        y = (self.winfo_screenheight() - self.winfo_height()) // 3
        self.geometry(f"+{x}+{y}")
        self.wait_visibility()
        self.grab_set()
        first.focus_set()

    def msg(self, text, bad=True):
        self.m.config(text=text, fg=RED if bad else BROWN)
        self.update_idletasks()

    def creds(self):
        email, pw = self.email.get().strip(), self.pw.get()
        if not email or len(pw) < 6:
            self.msg("Enter your email and a password of at least 6 characters.")
            return None
        return email, pw

    def login(self):
        c = self.creds()
        if not c:
            return
        self.msg("Logging in…", bad=False)
        try:
            self.app.cloud.sign_in(*c)
            self.destroy()
        except ApiError as e:
            self.msg(str(e))

    def signup(self):
        c = self.creds()
        if not c:
            return
        self.msg("Creating account…", bad=False)
        try:
            if self.app.cloud.sign_up(*c):
                self.destroy()
            else:
                self.msg("Account created. Check your email to confirm it, then log in.", bad=False)
        except ApiError as e:
            self.msg(str(e))


class ItemDialog(tk.Toplevel):
    """Popup used for both adding and editing an item."""

    def __init__(self, app, item=None):
        super().__init__(app)
        self.result = None
        self.title("Edit item" if item else "Add item")
        self.transient(app)
        self.resizable(False, False)
        p = item or {"name": "", "details": "", "qty": 1, "unit": "pcs", "price": "", "dt": "pct", "dv": ""}
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


# ---------------------------------------------------------------- main window
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title("Market Tracker")
        self.geometry("780x860")
        self.minsize(560, 520)
        self.configure(bg=PAPER)
        fams = set(tkfont.families(self))
        # Uses Doto if you have it installed, otherwise a monospace fallback.
        self.fam = next((f for f in ("Doto", "DejaVu Sans Mono", "Courier New") if f in fams), "Courier")
        self.cloud, self.worker = Cloud(), Worker()
        self.items, self.bill_type = [], "pct"
        self.bill_val = tk.StringVar()
        self.loading_bill, self.bill_job, self.last_sync = False, None, 0.0
        self.undo_data, self.undo_job = None, None
        self.build()
        self.bind("<FocusIn>", self.on_focus)
        self.poll()
        self.after(50, self.start)

    # ---------- background jobs ----------
    def bg(self, fn, ok=None, bad=None):
        self.worker.jobs.put((fn, ok, bad or self.on_fail))

    def poll(self):
        try:
            while True:
                cb, res, err = self.worker.done.get_nowait()
                if err is not None:
                    cb(err)
                elif cb:
                    cb(res)
        except queue.Empty:
            pass
        self.after(80, self.poll)

    def on_fail(self, err):
        self.notice(f"Could not save: {err}")
        if self.cloud.s:
            self.sync()  # put the list back in line with the cloud

    # ---------- login / sync ----------
    def start(self):
        if self.cloud.s:
            try:
                self.cloud.refresh()
            except ApiError:
                self.cloud.s = None
        if not self.cloud.s:
            dlg = LoginDialog(self)
            self.wait_window(dlg)
            if not self.cloud.s:
                self.destroy()
                return
        self.who.config(text=self.cloud.s["email"])
        self.deiconify()
        self.sync(first=True)

    def logout(self):
        self.cloud.sign_out()
        self.items = []
        self.refresh()
        self.withdraw()
        self.start()

    def on_focus(self, e):
        if e.widget is self and self.cloud.s and time.time() - self.last_sync > 30:
            self.sync()

    def sync(self, first=False):
        if not self.cloud.s:
            return
        self.last_sync = time.time()

        def job():
            rows = self.cloud.rest("GET", "items?select=*&order=created_at.asc")
            b = self.cloud.rest("GET", "bill_settings?select=*")
            return [from_row(r) for r in rows], (b[0] if b else None)

        self.bg(job, lambda res: self.apply_sync(res, first), lambda e: self.notice(f"Could not load: {e}"))

    def apply_sync(self, res, first):
        self.items, b = res
        self.loading_bill = True
        self.bill_type = b["discount_type"] if b else "pct"
        self.bill_cb.set("%" if self.bill_type == "pct" else CUR)
        self.bill_val.set(f"{b['discount_value']:g}" if b and float(b["discount_value"]) else "")
        self.loading_bill = False
        self.refresh()
        if first:
            self.offer_import()

    def offer_import(self):
        """One-time import of the list saved by the older local-only version."""
        uid = self.cloud.s["user_id"]
        done = read_json(IMPORTED_FILE, [])
        old = read_json(OLD_DATA, {}).get("items", [])
        if uid in done or self.items or not old:
            return
        if messagebox.askyesno("Import", f"Import the {len(old)} item(s) saved on this computer into your account?"):
            for i, o in enumerate(old):
                self.items.append({"id": str(uuid.uuid4()), "at": now_iso(i), "bought": bool(o.get("bought")),
                                   "name": o["name"], "details": o.get("details", ""), "qty": o["qty"],
                                   "unit": o.get("unit", "pcs"), "price": o["price"],
                                   "dt": o.get("dt", "pct"), "dv": o.get("dv", 0)})
            rows = [to_row(i, True) for i in self.items]
            self.bg(lambda: self.cloud.rest("POST", "items", rows, prefer="return=minimal"))
            self.refresh()
        try:
            with open(IMPORTED_FILE, "w", encoding="utf-8") as fh:
                json.dump(done + [uid], fh)
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
        right = tk.Frame(head, bg=PAPER)
        right.pack(side="right")
        self.who = tk.Label(right, text="", font=self.f(10), bg=PAPER, fg=BROWN)
        self.who.pack(side="left", padx=(0, 14))
        for text, cmd in (("Sync", self.sync), ("Log out", self.logout), ("Clear all", self.clear_all)):
            lbl = tk.Label(right, text=text, font=self.f(12, underline=True), bg=PAPER, fg=BROWN, cursor="hand2")
            lbl.bind("<Button-1>", lambda e, c=cmd: c())
            lbl.pack(side="left", padx=(0, 12))

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
        self.bill_cb = ttk.Combobox(ctl, values=["%", CUR], width=3, state="readonly")
        self.bill_cb.set("%")
        self.bill_cb.bind("<<ComboboxSelected>>", lambda e: self.on_bill_type(self.bill_cb.get()))
        self.bill_cb.pack(side="left", padx=6)
        self.billamt = tk.Label(s, text="", font=self.f(13), bg=PAPER, fg=BROWN)
        self.billamt.grid(row=2, column=2, sticky="e")
        self.bill_val.trace_add("write", lambda *a: self.on_bill_edit())
        tk.Label(s, text="Total", font=self.f(20), bg=PAPER, fg=BROWN).grid(row=3, column=0, sticky="w", pady=(14, 0))
        self.total = tk.Label(s, text="", font=self.f(38), bg=PAPER, fg=BROWN)
        self.total.grid(row=3, column=1, columnspan=2, sticky="e", pady=(14, 0))
        self.saved = tk.Label(s, text="", font=self.f(13), bg=PAPER, fg=GREEN)
        self.saved.grid(row=4, column=0, columnspan=3, sticky="e")

        self.bar = tk.Frame(self, bg=BROWN)
        self.bar_msg = tk.Label(self.bar, bg=BROWN, fg=PAPER, font=self.f(12))
        self.bar_msg.pack(side="left", padx=(14, 10), pady=8)
        self.undo_lbl = tk.Label(self.bar, text="Undo", bg=BROWN, fg=PAPER, font=self.f(12, underline=True), cursor="hand2")
        self.undo_lbl.bind("<Button-1>", lambda e: self.undo())

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
            tk.Label(info, text=it["details"], font=self.f(11), bg=PAPER, fg=BROWN).pack(anchor="w")
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

    # ---------- actions (the screen updates first, the cloud follows) ----------
    def on_bill_type(self, value):
        self.bill_type = "pct" if value == "%" else "fix"
        self.update_summary()
        self.schedule_bill_save()

    def on_bill_edit(self):
        self.update_summary()
        if not self.loading_bill:
            self.schedule_bill_save()

    def schedule_bill_save(self):
        if self.bill_job:
            self.after_cancel(self.bill_job)
        self.bill_job = self.after(600, self.save_bill)

    def save_bill(self):
        if not self.cloud.s:
            return
        row = {"user_id": self.cloud.s["user_id"], "discount_type": self.bill_type,
               "discount_value": max(num(self.bill_val.get()) or 0.0, 0.0)}
        self.bg(lambda: self.cloud.rest("POST", "bill_settings?on_conflict=user_id", row,
                                        prefer="resolution=merge-duplicates,return=minimal"))

    def toggle(self, it, var):
        it["bought"], iid, val = var.get(), it["id"], var.get()
        self.refresh()
        self.bg(lambda: self.cloud.rest("PATCH", f"items?id=eq.{iid}", {"bought": val}, prefer="return=minimal"))

    def open_dialog(self, item=None):
        dlg = ItemDialog(self, item)
        self.wait_window(dlg)
        if not dlg.result:
            return
        if item:
            item.update(dlg.result)
            iid, row = item["id"], to_row(item)
            self.bg(lambda: self.cloud.rest("PATCH", f"items?id=eq.{iid}", row, prefer="return=minimal"))
        else:
            new = {"id": str(uuid.uuid4()), "at": now_iso(), "bought": False, **dlg.result}
            self.items.append(new)
            row = to_row(new, True)
            self.bg(lambda: self.cloud.rest("POST", "items", row, prefer="return=minimal"))
            self.after(60, lambda: self.canvas.yview_moveto(1))
        self.refresh()

    def delete(self, it):
        iid = it["id"]
        self.show_undo(f"Deleted {it['name']}")
        self.items = [i for i in self.items if i["id"] != iid]
        self.refresh()
        self.bg(lambda: self.cloud.rest("DELETE", f"items?id=eq.{iid}", prefer="return=minimal"))

    def clear_all(self):
        if not self.items or not self.cloud.s:
            return
        uid = self.cloud.s["user_id"]
        self.show_undo("Cleared all items")
        self.items = []
        self.refresh()
        self.bg(lambda: self.cloud.rest("DELETE", f"items?user_id=eq.{uid}", prefer="return=minimal"))

    def show_bar(self, msg, with_undo):
        self.bar_msg.config(text=msg)
        if with_undo:
            self.undo_lbl.pack(side="left", padx=(0, 14))
        else:
            self.undo_lbl.pack_forget()
        self.bar.place(relx=0.5, rely=1.0, y=-20, anchor="s")
        if self.undo_job:
            self.after_cancel(self.undo_job)
        self.undo_job = self.after(6000, self.bar.place_forget)

    def show_undo(self, msg):
        self.undo_data = json.dumps(self.items)
        self.show_bar(msg, True)

    def notice(self, msg):
        self.show_bar(msg, False)

    def undo(self):
        self.bar.place_forget()
        if not self.undo_data:
            return
        self.items = json.loads(self.undo_data)
        self.undo_data = None
        self.refresh()
        rows = [to_row(i, True) for i in self.items]
        if rows:
            self.bg(lambda: self.cloud.rest("POST", "items?on_conflict=id", rows,
                                            prefer="resolution=merge-duplicates,return=minimal"))


if __name__ == "__main__":
    App().mainloop()