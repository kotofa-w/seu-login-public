#!/usr/bin/env python3
"""SEU campus network auto-login GUI.

Based on tkinter, no extra dependencies.

Usage:
    python seu_login_gui.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

# Ensure local seu_login module is importable
_SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_SCRIPT_DIR))

import seu_login  # noqa: E402

# ── Constants ─────────────────────────────────────────────

APP_TITLE: str = "SEU \u6821\u56ed\u7f51\u81ea\u52a8\u767b\u5f55"
WIN_SIZE: str = "480x620"

ISP_OPTIONS: dict[str, str] = {
    "campus": "校园网（SEU-WLAN）",
    "telecom": "中国电信",
    "unicom": "中国联通",
    "mobile": "中国移动",
}

# Reverse: display text -> key
_ISP_DISPLAY_TO_KEY: dict[str, str] = {v: k for k, v in ISP_OPTIONS.items()}

# Status colours
CLR_OK: str = "#27ae60"
CLR_ERR: str = "#c0392b"
CLR_WARN: str = "#e67e22"
CLR_GRAY: str = "#999999"


# ── Main Window ──────────────────────────────────────────


class SEULoginApp:
    """SEU campus network login GUI application."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry(WIN_SIZE)
        self.root.resizable(False, False)

        # Windows DPI awareness
        try:
            from ctypes import windll

            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass  # non-Windows or unavailable

        self._logging_in: bool = False
        self._closing = False
        self._auto_login_timer = None
        self._auto_start_on: bool = False
        self.config: dict = seu_login.load_config()

        self._build_ui()
        self._apply_config()

        self.root.after(500, self._check_auto_start_async)
        self._auto_login_timer = self.root.after(1000, self._auto_login_tick)
        if not self.var_auto_login.get():
            self.root.after(1000, self._check_online_async)

    # ── UI construction ──────────────────────────────────

    def _build_ui(self) -> None:
        """Build the full UI layout."""
        style = ttk.Style()
        for theme in ("vista", "clam", "default"):
            try:
                style.theme_use(theme)
                break
            except Exception:
                continue

        style.configure("TNotebook.Tab", padding=[14, 4])
        style.configure(
            "Status.TLabel",
            font=("Microsoft YaHei UI", 10),
        )
        style.configure(
            "StatusDetail.TLabel",
            font=("Microsoft YaHei UI", 9),
        )
        style.configure(
            "Section.TLabelframe.Label",
            font=("Microsoft YaHei UI", 9, "bold"),
        )

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(
            fill=tk.BOTH,
            expand=True,
            padx=10,
            pady=6,
        )

        self.tab_login = ttk.Frame(self.notebook, padding=12)
        self.tab_settings = ttk.Frame(
            self.notebook,
            padding=12,
        )
        self.tab_log = ttk.Frame(self.notebook, padding=12)

        self.notebook.add(self.tab_login, text="  登录  ")
        self.notebook.add(
            self.tab_settings,
            text="  设置  ",
        )
        self.notebook.add(self.tab_log, text="  日志  ")

        self._build_login_tab()
        self._build_settings_tab()
        self._build_log_tab()

        # Bottom status bar
        self.status_var = tk.StringVar(value="就绪")
        bar = ttk.Label(
            self.root,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(6, 2),
        )
        bar.pack(side=tk.BOTTOM, fill=tk.X)

    def _build_login_tab(self) -> None:
        """Build the login tab widgets."""
        tab = self.tab_login

        # -- Credentials --
        cred = ttk.LabelFrame(
            tab,
            text=" 账号信息 ",
            style="Section.TLabelframe",
        )
        cred.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(cred, text="学号:").grid(
            row=0,
            column=0,
            sticky=tk.W,
            padx=8,
            pady=6,
        )
        self.var_username = tk.StringVar()
        ttk.Entry(
            cred,
            textvariable=self.var_username,
            width=32,
        ).grid(row=0, column=1, padx=8, pady=6, sticky=tk.EW)

        ttk.Label(cred, text="密码:").grid(
            row=1,
            column=0,
            sticky=tk.W,
            padx=8,
            pady=6,
        )
        pwd_frame = ttk.Frame(cred)
        pwd_frame.grid(
            row=1,
            column=1,
            padx=8,
            pady=6,
            sticky=tk.EW,
        )

        self.var_password = tk.StringVar()
        self.ent_pwd = ttk.Entry(
            pwd_frame,
            textvariable=self.var_password,
            show="\u2022",
            width=27,
        )
        self.ent_pwd.pack(
            side=tk.LEFT,
            fill=tk.X,
            expand=True,
        )

        self._pwd_visible: bool = False
        ttk.Button(
            pwd_frame,
            text="\u25c9",
            width=3,
            command=self._toggle_pwd,
        ).pack(side=tk.RIGHT, padx=(4, 0))

        ttk.Label(cred, text="校园网 / 运营商:").grid(
            row=2,
            column=0,
            sticky=tk.W,
            padx=8,
            pady=6,
        )
        self.var_isp = tk.StringVar(
            value=ISP_OPTIONS.get("campus", ""),
        )
        cb_isp = ttk.Combobox(
            cred,
            textvariable=self.var_isp,
            values=list(ISP_OPTIONS.values()),
            state="readonly",
            width=29,
        )
        cb_isp.grid(
            row=2,
            column=1,
            padx=8,
            pady=6,
            sticky=tk.EW,
        )
        cb_isp.bind(
            "<<ComboboxSelected>>",
            self._on_isp_change,
        )

        self.var_auto_network = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            cred,
            text="自动识别 SEU-WLAN / SEU-ISP（共用账号密码）",
            variable=self.var_auto_network,
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=8, pady=6)
        self.var_auto_login = tk.BooleanVar(value=True)

        cred.columnconfigure(1, weight=1)

        # -- Action buttons --
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, pady=8)

        self.btn_login = ttk.Button(
            btn_frame,
            text="\u25b6  登录",
            command=self._do_login,
        )
        self.btn_login.pack(
            side=tk.LEFT,
            expand=True,
            fill=tk.X,
            padx=(0, 5),
        )

        self.btn_logout = ttk.Button(
            btn_frame,
            text="\u25a0  注销",
            command=self._do_logout,
            state=tk.DISABLED,
        )
        self.btn_logout.pack(
            side=tk.RIGHT,
            expand=True,
            fill=tk.X,
            padx=(5, 0),
        )

        # -- Connection status --
        status_frame = ttk.LabelFrame(
            tab,
            text=" 连接状态 ",
            style="Section.TLabelframe",
        )
        status_frame.pack(
            fill=tk.BOTH,
            expand=True,
            pady=(8, 0),
        )

        self.status_icon = tk.Label(
            status_frame,
            text="\u25cf",
            fg=CLR_GRAY,
            font=("Consolas", 28),
        )
        self.status_icon.pack(pady=(12, 0))

        self.status_text = tk.StringVar(value="未连接")
        ttk.Label(
            status_frame,
            textvariable=self.status_text,
            style="Status.TLabel",
        ).pack(pady=(2, 0))

        self.status_detail = tk.StringVar(value="")
        ttk.Label(
            status_frame,
            textvariable=self.status_detail,
            style="StatusDetail.TLabel",
            foreground=CLR_GRAY,
        ).pack(pady=(2, 12))

        self.root.bind("<Return>", lambda e: self._do_login())

    def _build_settings_tab(self) -> None:
        """Build the settings tab widgets."""
        tab = self.tab_settings

        # -- Auto-start --
        as_frame = ttk.LabelFrame(
            tab,
            text=" 开机自启动 ",
            style="Section.TLabelframe",
        )
        as_frame.pack(fill=tk.X, pady=(0, 10))

        row1 = ttk.Frame(as_frame)
        row1.pack(fill=tk.X, padx=10, pady=8)

        self.var_auto_start = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            row1,
            text="开机自动登录（任务计划程序）",
            variable=self.var_auto_start,
        ).pack(side=tk.LEFT)

        self.auto_start_label = ttk.Label(
            row1,
            text="检测中...",
            foreground=CLR_GRAY,
        )
        self.auto_start_label.pack(side=tk.RIGHT)

        row2 = ttk.Frame(as_frame)
        row2.pack(fill=tk.X, padx=10, pady=(0, 8))

        ttk.Button(
            row2,
            text="应用",
            command=self._apply_auto_start,
        ).pack(side=tk.LEFT)

        ttk.Button(
            row2,
            text="打开任务计划程序",
            command=self._open_taskschd,
        ).pack(side=tk.RIGHT)

        # -- Retry settings --
        retry_frame = ttk.LabelFrame(
            tab,
            text=" 重试设置 ",
            style="Section.TLabelframe",
        )
        retry_frame.pack(fill=tk.X, pady=(0, 10))

        r1 = ttk.Frame(retry_frame)
        r1.pack(fill=tk.X, padx=10, pady=6)

        ttk.Label(r1, text="重试次数:").pack(side=tk.LEFT)
        self.var_retry = tk.IntVar(value=3)
        ttk.Spinbox(
            r1,
            from_=1,
            to=10,
            textvariable=self.var_retry,
            width=5,
        ).pack(side=tk.LEFT, padx=8)

        ttk.Label(r1, text="重试间隔(秒):").pack(
            side=tk.LEFT,
            padx=(16, 0),
        )
        self.var_delay = tk.IntVar(value=5)
        ttk.Spinbox(
            r1,
            from_=1,
            to=60,
            textvariable=self.var_delay,
            width=5,
        ).pack(side=tk.LEFT, padx=8)

        # -- Other --
        other = ttk.LabelFrame(
            tab,
            text=" 其他设置 ",
            style="Section.TLabelframe",
        )
        other.pack(fill=tk.X, pady=(0, 10))

        self.var_silent = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            other,
            text="静默模式（登录成功不弹提示，登录失败提醒）",
            variable=self.var_silent,
        ).pack(anchor=tk.W, padx=10, pady=6)

        ttk.Label(
            other,
            text="连接监测维护模式",
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(anchor=tk.W, padx=10, pady=(8, 2))

        self.var_daemon = self.var_auto_login
        ttk.Checkbutton(
            other,
            text="守护模式（每30秒检查连接，未登录就自动登录）",
            variable=self.var_daemon,
            command=self._select_guardian_mode,
        ).pack(anchor=tk.W, padx=10, pady=6)
        self.var_event_trigger = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            other,
            text="连接触发模式（监测到连接行为时检查连接）",
            variable=self.var_event_trigger,
            command=self._select_event_mode,
        ).pack(anchor=tk.W, padx=10, pady=6)
        ttk.Label(
            other,
            text="设置好后，请点击下方“保存所有设置”。",
        ).pack(anchor=tk.W, padx=10, pady=(2, 8))

        # -- Save --
        ttk.Button(
            tab,
            text="\u2714  保存所有设置",
            command=self._save_settings,
        ).pack(fill=tk.X, pady=(6, 0))

    def _build_log_tab(self) -> None:
        """Build the log viewer tab."""
        tab = self.tab_log

        top = ttk.Frame(tab)
        top.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(
            top,
            text="刷新",
            command=self._refresh_log,
        ).pack(side=tk.LEFT)
        ttk.Button(
            top,
            text="清空显示",
            command=self._clear_log,
        ).pack(side=tk.LEFT, padx=8)
        ttk.Button(
            top,
            text="打开日志文件",
            command=self._open_log_file,
        ).pack(side=tk.RIGHT)

        self.log_text = tk.Text(
            tab,
            wrap=tk.WORD,
            font=("Consolas", 9),
            state=tk.DISABLED,
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#ffffff",
            selectbackground="#264f78",
        )
        scrollbar = ttk.Scrollbar(
            tab,
            orient=tk.VERTICAL,
            command=self.log_text.yview,
        )
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(
            side=tk.LEFT,
            fill=tk.BOTH,
            expand=True,
        )
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.log_text.tag_configure("ok", foreground=CLR_OK)
        self.log_text.tag_configure(
            "err",
            foreground=CLR_ERR,
        )
        self.log_text.tag_configure(
            "warn",
            foreground=CLR_WARN,
        )
        self.log_text.tag_configure(
            "info",
            foreground="#d4d4d4",
        )

        self.notebook.bind(
            "<<NotebookTabChanged>>",
            self._on_tab_change,
        )

    # ── Config load / save ───────────────────────────────

    def _apply_config(self) -> None:
        """Populate widgets from loaded config."""
        c = self.config
        if not c:
            return
        self.var_username.set(c.get("username", ""))
        self.var_password.set(c.get("password", ""))
        isp_key = str(c.get("isp", "campus"))
        self.var_isp.set(ISP_OPTIONS.get(isp_key, ""))
        self.var_retry.set(c.get("retry_count", 3))
        self.var_delay.set(c.get("retry_delay", 5))
        self.var_silent.set(c.get("silent", True))
        self.var_auto_network.set(c.get("auto_network", True))
        self.var_auto_login.set(c.get("auto_login", True))
        self.var_event_trigger.set(c.get("event_trigger", False))
        if self.var_event_trigger.get():
            self.var_auto_login.set(False)

    def _collect_settings(self) -> dict:
        """Build config dict from current widget values.

        Returns:
            Config dict ready to pass to save_config.
        """
        return {
            "username": self.var_username.get().strip(),
            "password": self.var_password.get(),
            "isp": self._get_isp_key(),
            "retry_count": self.var_retry.get(),
            "retry_delay": self.var_delay.get(),
            "timeout": self.config.get("timeout", 10),
            "silent": self.var_silent.get(),
            "auto_network": self.var_auto_network.get(),
            "auto_login": self.var_auto_login.get(),
            "event_trigger": self.var_event_trigger.get(),
            "check_interval": self.config.get(
                "check_interval",
                30,
            ),
        }

    def _save_settings(self) -> None:
        """Save current settings to config file."""
        previous_event = self.config.get("event_trigger", False)
        previous_guardian = self.config.get("auto_login", True)
        self.config.update(self._collect_settings())
        seu_login.save_config(self.config)
        try:
            self._sync_event_trigger(self.var_event_trigger.get())
        except (OSError, subprocess.SubprocessError, RuntimeError):
            self.config.update(event_trigger=previous_event, auto_login=previous_guardian)
            self.var_event_trigger.set(previous_event)
            self.var_auto_login.set(previous_guardian)
            seu_login.save_config(self.config)
            self._set_status("触发任务设置未确认")
            messagebox.showerror(
                "触发任务设置失败",
                "请检查管理员权限、WLAN 事件日志及同名任务。未确认任务已应用；请检查任务计划程序。",
            )
            return
        self._set_status("设置已保存")
        messagebox.showinfo(
            "保存成功",
            "配置已写入 seu_login.ini",
        )

    def _save_settings_quiet(self) -> None:
        """Silently save settings (on window close)."""
        settings = self._collect_settings()
        settings["event_trigger"] = self.config.get("event_trigger", False)
        if settings["event_trigger"]:
            settings["auto_login"] = False
        self.config.update(settings)
        try:
            seu_login.save_config(self.config)
        except Exception:
            pass  # best-effort on exit

    def _select_event_mode(self) -> None:
        if self.var_event_trigger.get():
            self.var_auto_login.set(False)

    def _select_guardian_mode(self) -> None:
        if self.var_auto_login.get():
            self.var_event_trigger.set(False)

    def _sync_event_trigger(self, enabled: bool) -> None:
        command = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(_SCRIPT_DIR / "install-network-trigger.ps1"),
            "-ConfigPath", str(seu_login.CONFIG_FILE),
        ]
        if not enabled:
            command.append("-Remove")
        result = subprocess.run(
            command, capture_output=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            raise RuntimeError("Event-trigger task not confirmed")

    # ── Login / Logout ───────────────────────────────────

    def _auto_login_tick(self) -> None:
        if self._closing:
            return
        interval = max(5, int(self.config.get("check_interval", 30)))
        self._auto_login_timer = self.root.after(interval * 1000, self._auto_login_tick)
        if self._logging_in or not self.var_auto_login.get() or self.config.get("event_trigger", False):
            return
        config = self._collect_settings()
        if not config.get("username") or not config.get("password"):
            return
        self._logging_in = True
        self.btn_login.configure(state=tk.DISABLED)
        threading.Thread(target=self._auto_login_thread, args=(config,), daemon=True).start()

    def _auto_login_thread(self, config: dict) -> None:
        try:
            code = seu_login.automatic_login_check(config)
        except Exception as exc:
            seu_login.logger.error("Automatic check failed: %s", type(exc).__name__)
            code = seu_login.ERR_OTHER
        if not self._closing:
            self.root.after(0, self._on_auto_login_done, code)

    def _on_auto_login_done(self, code: int) -> None:
        self._logging_in = False
        self.btn_login.configure(state=tk.NORMAL)
        if code == seu_login.OK:
            self._set_conn_status("ok", "已认证")
            self.btn_logout.configure(state=tk.NORMAL)
            self._set_status("自动检查完成：已认证")
        else:
            self._set_conn_status("pending", "等待自动认证")
            self._set_status("自动检查暂未完成，稍后重试")

    def _do_login(self) -> None:
        """Handle login button click."""
        if self._logging_in:
            return

        username = self.var_username.get().strip()
        password = self.var_password.get()

        if not username or not password:
            messagebox.showwarning(
                "提示",
                "请先填写学号和密码",
            )
            return

        self._logging_in = True
        self.btn_login.configure(
            state=tk.DISABLED,
            text="登录中...",
        )
        self._set_status("正在登录...")
        self._set_conn_status(
            "pending",
            "正在连接认证服务器...",
        )

        threading.Thread(
            target=self._login_thread,
            daemon=True,
        ).start()

    def _login_thread(self) -> None:
        """Background login worker."""
        try:
            retries = self.var_retry.get()
            delay = self.var_delay.get()
            code, msg = seu_login.ERR_OTHER, ""

            for attempt in range(1, retries + 1):
                client = seu_login.create_client(self._collect_settings())
                self.root.after(
                    0,
                    lambda a=attempt, n=retries: self._set_conn_status(
                        "pending",
                        f"第 {a}/{n} 次尝试...",
                    ),
                )
                code, msg = client.login()
                if code == seu_login.OK:
                    break
                if attempt < retries:
                    wait = delay * attempt
                    self.root.after(
                        0,
                        lambda w=wait: self._set_conn_status(
                            "pending",
                            f"等待 {w} 秒后重试...",
                        ),
                    )
                    time.sleep(wait)

            self.root.after(
                0,
                self._on_login_done,
                code,
                msg,
            )

        except Exception as exc:
            self.root.after(
                0,
                self._on_login_done,
                seu_login.ERR_OTHER,
                str(exc) if isinstance(exc, seu_login.NetworkDetectionError) else type(exc).__name__,
            )

    def _on_login_done(self, code: int, msg: str) -> None:
        """Login completion callback (main thread)."""
        self._logging_in = False
        self.btn_login.configure(
            state=tk.NORMAL,
            text="\u25b6  登录",
        )

        if code == seu_login.OK:
            self._set_conn_status("ok", "已连接")
            self.btn_logout.configure(state=tk.NORMAL)
            self._set_status(msg)
            if "|" in msg:
                parts = msg.split("|")
                detail = parts[-1].strip() if len(parts) > 1 else ""
                self.status_detail.configure(text=detail)
            if not self.var_silent.get():
                messagebox.showinfo("登录成功", msg)
        else:
            self._set_conn_status("err", "登录失败")
            self.btn_logout.configure(state=tk.DISABLED)
            self._set_status(f"登录失败: {msg}")
            messagebox.showerror("登录失败", msg)

    def _do_logout(self) -> None:
        """Handle logout button click."""
        if self._logging_in:
            return
        if not messagebox.askyesno(
            "确认",
            "确定要注销当前网络连接吗？",
        ):
            return
        self._logging_in = True
        self.btn_login.configure(state=tk.DISABLED)
        self.btn_logout.configure(state=tk.DISABLED)
        self._set_status("正在注销...")
        threading.Thread(
            target=self._logout_thread,
            daemon=True,
        ).start()

    def _logout_thread(self) -> None:
        """Background logout worker."""
        try:
            client = seu_login.create_client({**self._collect_settings(), "auto_network": False})
            code, msg = client.logout()
            self.root.after(
                0,
                self._on_logout_done,
                code,
                msg,
            )
        except Exception as exc:
            self.root.after(
                0,
                self._on_logout_done,
                seu_login.ERR_OTHER,
                str(exc) if isinstance(exc, seu_login.NetworkDetectionError) else type(exc).__name__,
            )

    def _on_logout_done(
        self,
        code: int,
        msg: str,
    ) -> None:
        """Logout completion callback."""
        self._logging_in = False
        self.btn_login.configure(state=tk.NORMAL)
        if code == seu_login.OK:
            self._set_conn_status("offline", "已注销")
            self.btn_logout.configure(state=tk.DISABLED)
            self._set_status("已注销")
        else:
            self._set_conn_status("err", "注销失败")
            self.btn_logout.configure(state=tk.NORMAL)
            self._set_status(f"注销失败: {msg}")

    # ── Online status check ──────────────────────────────

    def _check_online_async(self) -> None:
        """Start async online status check."""
        if not self.config.get("username"):
            return
        threading.Thread(
            target=self._query_online_thread,
            daemon=True,
        ).start()

    def _query_online_thread(self) -> None:
        """Background status query worker."""
        try:
            client = seu_login.create_client({**self.config, "timeout": 5, "auto_network": False})
            code, msg = client.query_status()
            self.root.after(
                0,
                self._on_query_done,
                code,
                msg,
            )
        except Exception:
            pass  # status check is best-effort

    def _on_query_done(
        self,
        code: int,
        msg: str,
    ) -> None:
        """Status query callback."""
        if code == seu_login.OK:
            self._set_conn_status("ok", "已连接")
            self.btn_logout.configure(state=tk.NORMAL)
        else:
            self._set_conn_status("offline", "未连接")

    # ── Auto-start management ────────────────────────────

    def _check_auto_start_async(self) -> None:
        """Check if auto-start task exists."""
        threading.Thread(
            target=self._check_auto_start_thread,
            daemon=True,
        ).start()

    def _check_auto_start_thread(self) -> None:
        """Background task to query Task Scheduler."""
        try:
            result = subprocess.run(
                f'schtasks /Query /TN "{seu_login.TASK_NAME}" /FO CSV /NH',
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            exists = (
                result.returncode == 0 and seu_login.TASK_NAME in result.stdout
            )
            self.root.after(
                0,
                self._on_auto_start_checked,
                exists,
            )
        except Exception:
            self.root.after(
                0,
                self._on_auto_start_checked,
                False,
            )

    def _on_auto_start_checked(
        self,
        exists: bool,
    ) -> None:
        """Auto-start check callback."""
        self._auto_start_on = exists
        self.var_auto_start.set(exists)
        if exists:
            self.auto_start_label.configure(
                text="已启用",
                foreground=CLR_OK,
            )
        else:
            self.auto_start_label.configure(
                text="未启用",
                foreground=CLR_GRAY,
            )

    def _apply_auto_start(self) -> None:
        """Apply or remove auto-start task."""
        want = self.var_auto_start.get()

        if want and not self._auto_start_on:
            code = seu_login.install_auto_start()
            if code == seu_login.OK:
                self._auto_start_on = True
                self.auto_start_label.configure(
                    text="已启用",
                    foreground=CLR_OK,
                )
                self._set_status("开机自启动已安装")
            else:
                self.var_auto_start.set(False)
                messagebox.showerror(
                    "安装失败",
                    "安装自启动失败。\n请以管理员身份运行此程序后重试。",
                )
        elif not want and self._auto_start_on:
            code = seu_login.remove_auto_start()
            if code == seu_login.OK:
                self._auto_start_on = False
                self.auto_start_label.configure(
                    text="未启用",
                    foreground=CLR_GRAY,
                )
                self._set_status("开机自启动已卸载")

    def _open_taskschd(self) -> None:
        """Open Windows Task Scheduler."""
        subprocess.Popen(
            ["taskschd.msc"],
            shell=True,
        )

    # ── Log viewer ───────────────────────────────────────

    def _on_tab_change(self, event: object = None) -> None:
        """Handle tab switch event."""
        try:
            idx = self.notebook.index(self.notebook.select())
            if idx == 2:
                self._refresh_log()
        except Exception:
            pass  # ignore tab errors

    def _refresh_log(self) -> None:
        """Load and display last 200 log lines."""
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)

        log_path = seu_login.LOG_FILE
        if not log_path.exists():
            self.log_text.insert(
                tk.END,
                "暂无日志记录",
            )
            self.log_text.configure(state=tk.DISABLED)
            return

        try:
            with open(
                log_path,
                encoding="utf-8",
            ) as f:
                lines = f.readlines()

            for line in lines[-200:]:
                tag = _classify_log_line(line)
                self.log_text.insert(tk.END, line, tag)

            self.log_text.see(tk.END)
        except Exception as exc:
            self.log_text.insert(
                tk.END,
                f"读取日志失败: {exc}",
            )

        self.log_text.configure(state=tk.DISABLED)

    def _clear_log(self) -> None:
        """Clear log display (file untouched)."""
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _open_log_file(self) -> None:
        """Open log file in system default editor."""
        log_path = seu_login.LOG_FILE
        if log_path.exists():
            os.startfile(str(log_path))
        else:
            messagebox.showinfo(
                "提示",
                "日志文件尚未生成",
            )

    # ── Helpers ──────────────────────────────────────────

    def _toggle_pwd(self) -> None:
        """Toggle password field visibility."""
        self._pwd_visible = not self._pwd_visible
        self.ent_pwd.configure(
            show="" if self._pwd_visible else "\u2022",
        )

    def _on_isp_change(self, event: object = None) -> None:
        """Handle ISP combobox selection change."""
        pass  # display text is already shown in combobox

    def _get_isp_key(self) -> str:
        """Convert current ISP display text to internal key.

        Returns:
            ISP key string (e.g. 'campus', 'telecom').
        """
        display = self.var_isp.get()
        return _ISP_DISPLAY_TO_KEY.get(display, "campus")

    def _set_status(self, text: str) -> None:
        """Update bottom status bar."""
        self.status_var.set(text)

    def _set_conn_status(
        self,
        state: str,
        text: str,
    ) -> None:
        """Update connection status indicator."""
        colors = {
            "ok": CLR_OK,
            "err": CLR_ERR,
            "pending": CLR_WARN,
            "offline": CLR_GRAY,
        }
        self.status_icon.configure(
            fg=colors.get(state, CLR_GRAY),
        )
        self.status_text.set(text)

    def _close_window(self) -> None:
        """Handle window close."""
        self._closing = True
        if self._auto_login_timer is not None:
            self.root.after_cancel(self._auto_login_timer)
        self._save_settings_quiet()
        self.root.destroy()


# ── Helpers ───────────────────────────────────────────────


def _classify_log_line(line: str) -> str:
    """Determine colour tag for a log line.

    Args:
        line: Raw log line text.

    Returns:
        Tag name: 'ok', 'err', 'warn', or 'info'.
    """
    if "[ERROR]" in line:
        return "err"
    if "[WARNING]" in line:
        return "warn"
    if "OK" in line or "\u6210\u529f" in line:
        return "ok"
    return "info"


# ── Entry Point ──────────────────────────────────────────


def main() -> None:
    """Launch the GUI application."""
    seu_login.setup_logging()

    root = tk.Tk()

    try:
        root.iconbitmap(default="")
    except Exception:
        pass  # icon is optional

    app = SEULoginApp(root)
    root.protocol(
        "WM_DELETE_WINDOW",
        app._close_window,
    )

    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        messagebox.showerror(
            "启动失败",
            f"程序异常: {type(exc).__name__}",
        )
        sys.exit(1)
