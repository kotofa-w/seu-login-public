#!/usr/bin/env python3
"""
SEU campus network auto-login script.

For SEU Dr.COM ePortal authentication system.
Supports ISP selection, silent auto-start, error popup.

Usage:
    python seu_login.py                  # login with config
    python seu_login.py --setup          # interactive setup
    python seu_login.py --isp mobile     # login with China Mobile
    python seu_login.py --logout         # logout
    python seu_login.py --install-start  # install auto-start
    python seu_login.py --remove-start   # remove auto-start
    python seu_login.py --status         # query status
"""

from __future__ import annotations

import argparse
import base64
import configparser
import html
from ipaddress import IPv4Address
import json
from getpass import getpass
import logging
import os
import re
import socket
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import urllib3

try:
    import requests
except ImportError:
    print("[!] Missing dependency: requests")
    print("    Run: pip install requests")
    sys.exit(1)

# Suppress InsecureRequestWarning for self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ── Paths & Constants ─────────────────────────────────────

SCRIPT_DIR: Path = Path(__file__).parent.resolve()
CONFIG_FILE: Path = SCRIPT_DIR / "seu_login.ini"
LOG_FILE: Path = SCRIPT_DIR / "seu_login.log"

# Dr.COM ePortal (SEU packet-capture verified 2026-06-29)
PORTAL_BASE: str = "https://w.seu.edu.cn:801/eportal/"
CAMPUS_PORTAL_BASE: str = "https://w.seu.edu.cn:802/eportal/"
PORTAL_PAGE_URL: str = "https://w.seu.edu.cn/a79.htm"
DEFAULT_AC_IP: str = "10.80.175.4"
# shortcut: WLAN controller verified by the successful capture; update if campus AC changes.
CAMPUS_DEFAULT_AC_IP: str = "10.80.175.1"
CONNECTIVITY_CHECK_URL: str = "http://connect.rom.miui.com/generate_204"
JSONP_CALLBACK: str = "dr1003"
JS_VERSION: str = "3.3.2"
REQ_VERSION: str = "9969"

TASK_NAME: str = "SEU_AutoLogin"

# ISP suffix appended to user_account (from capture)
ISP_SUFFIX: dict[str, str] = {
    "campus": "",  # Unified authentication has no operator suffix.
    "telecom": "@dx",  # China Telecom
    "unicom": "@unicom",  # China Unicom
    "mobile": "@cmcc",  # China Mobile
}

ISP_DISPLAY: dict[str, str] = {
    "campus": "SEU-WLAN (\u6821\u56ed\u7f51)",
    "telecom": "\u4e2d\u56fd\u7535\u4fe1",
    "unicom": "\u4e2d\u56fd\u8054\u901a",
    "mobile": "\u4e2d\u56fd\u79fb\u52a8",
}

# Status codes
OK: int = 0
ERR_NETWORK: int = 1
ERR_AUTH: int = 2
ERR_CONFIG: int = 3
ERR_OTHER: int = 9


# ── Logging ───────────────────────────────────────────────

logger = logging.getLogger("seu_login")


def setup_logging(verbose: bool = False) -> None:
    """Configure file + optional console logging.

    Clears any existing handlers before setup to prevent
    duplicate log entries when called multiple times.

    Args:
        verbose: If True, also log to stdout at INFO level.
    """
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = RotatingFileHandler(
        LOG_FILE,
        maxBytes=512 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    if verbose:
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        logger.addHandler(ch)


# ── Config ────────────────────────────────────────────────

_Config = dict[str, str | int | bool]


def load_config(config_path: Path = CONFIG_FILE) -> _Config:
    """Read config from ini file.

    Args:
        config_path: Path to the .ini file.

    Returns:
        Dict with config values, or empty dict if file missing.
    """
    if not config_path.exists():
        return {}

    cfg = configparser.ConfigParser()
    cfg.read(str(config_path), encoding="utf-8")

    return {
        "username": cfg.get("auth", "username", fallback=""),
        "password": cfg.get("auth", "password", fallback=""),
        "isp": cfg.get("auth", "isp", fallback="campus"),
        "retry_count": cfg.getint(
            "settings",
            "retry_count",
            fallback=3,
        ),
        "retry_delay": cfg.getint(
            "settings",
            "retry_delay",
            fallback=5,
        ),
        "timeout": cfg.getint(
            "settings",
            "timeout",
            fallback=10,
        ),
        "silent": cfg.getboolean(
            "settings",
            "silent",
            fallback=True,
        ),
        "auto_network": cfg.getboolean(
            "settings", "auto_network", fallback=True,
        ),
        "auto_login": cfg.getboolean("settings", "auto_login", fallback=True),
        "event_trigger": cfg.getboolean("settings", "event_trigger", fallback=False),
        "check_interval": cfg.getint(
            "settings",
            "check_interval",
            fallback=30,
        ),
    }


def save_config(
    config: _Config,
    config_path: Path = CONFIG_FILE,
) -> None:
    """Write config to ini file.

    Args:
        config: Dict with config values.
        config_path: Destination path.
    """
    cfg = configparser.ConfigParser()

    cfg["auth"] = {
        "username": str(config.get("username", "")),
        "password": str(config.get("password", "")),
        "isp": str(config.get("isp", "campus")),
    }
    cfg["settings"] = {
        "retry_count": str(config.get("retry_count", 3)),
        "retry_delay": str(config.get("retry_delay", 5)),
        "timeout": str(config.get("timeout", 10)),
        "silent": str(config.get("silent", True)),
        "auto_network": str(config.get("auto_network", True)),
        "auto_login": str(config.get("auto_login", True)),
        "event_trigger": str(config.get("event_trigger", False)),
        "check_interval": str(
            config.get("check_interval", 30),
        ),
    }

    with open(config_path, "w", encoding="utf-8") as f:
        cfg.write(f)

    logger.info("Config saved")


def interactive_setup(
    config_path: Path = CONFIG_FILE,
) -> _Config | None:
    """Run interactive first-time setup wizard.

    Args:
        config_path: Where to save the config.

    Returns:
        The saved config dict, or None on failure.
    """
    print()
    print("=" * 46)
    print("  SEU Auto-Login - Setup Wizard")
    print("=" * 46)
    print()

    old = load_config(config_path)

    username = input(
        f"  Username [{old.get('username', '')}]: ",
    ).strip()
    if not username:
        username = old.get("username", "")
    if not username:
        print("  [!] Username required")
        return None

    password = getpass("  Password: ").strip()
    if not password:
        password = old.get("password", "")

    print()
    print("  ISP options:")
    for key, name in ISP_DISPLAY.items():
        suffix = ISP_SUFFIX[key]
        s_disp = f" (suffix {suffix})" if suffix else " (no suffix)"
        marker = " <--" if old.get("isp") == key else ""
        print(f"    [{key:>8}]  {name}{s_disp}{marker}")
    print()

    isp = (
        input(
            f"  ISP [{old.get('isp', 'campus')}]: ",
        )
        .strip()
        .lower()
    )
    if not isp:
        isp = old.get("isp", "campus")
    if isp not in ISP_SUFFIX:
        print(f"  [!] Unknown ISP '{isp}', using campus")
        isp = "campus"

    print()
    rc = input(
        f"  Retry count [{old.get('retry_count', 3)}]: ",
    ).strip()
    retry_count = int(rc) if rc else old.get("retry_count", 3)

    rd = input(
        f"  Retry delay(s) [{old.get('retry_delay', 5)}]: ",
    ).strip()
    retry_delay = int(rd) if rd else old.get("retry_delay", 5)

    config: _Config = {
        "username": username,
        "password": password,
        "isp": isp,
        "retry_count": retry_count,
        "retry_delay": retry_delay,
        "timeout": old.get("timeout", 10),
        "silent": old.get("silent", True),
        "auto_network": old.get("auto_network", True),
        "auto_login": old.get("auto_login", True),
        "event_trigger": old.get("event_trigger", False),
        "check_interval": old.get("check_interval", 30),
    }
    save_config(config, config_path)

    print()
    print(f"  Config saved: {config_path}")
    print(f"  Username: {username}")
    print(f"  ISP: {ISP_DISPLAY.get(isp, isp)}")
    print()

    test = input("  Test login now? [Y/n]: ").strip().lower()
    if test != "n":
        run_login(config, verbose=True)

    return config


# ── Core Login Client ─────────────────────────────────────


def _parse_jsonp(text: str) -> dict:
    """Extract JSON from a JSONP response like dr1003({...}).

    Args:
        text: Raw response body.

    Returns:
        Parsed dict, or empty dict on failure.
    """
    m = re.search(r"[^(]*\((\{.*\})\)", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            logger.debug("JSONP JSON decode failed")
    return {}


def _extract_fail_detail(data: dict) -> str | None:
    """Extract human-readable error from parsed response.

    The ePortal may return ``msg`` as plain text or
    base64-encoded UTF-8.  Try decoding base64 first; fall
    back to raw string.

    Args:
        data: Parsed JSONP response dict.

    Returns:
        Error message string or None.
    """
    msg = data.get("msg") or data.get("msga")
    if not msg or not isinstance(msg, str):
        return None
    if "\u6210\u529f" in msg:
        return None

    # Try base64 decode (ePortal often encodes msgs)
    try:
        decoded = base64.b64decode(msg).decode("utf-8")
        if decoded and "\u6210\u529f" not in decoded:
            if decoded.isprintable() or any(
                "\u4e00" <= c <= "\u9fff" for c in decoded
            ):
                return decoded
    except Exception:
        pass  # not base64, use raw

    return msg


def _verify_connectivity(
    session: requests.Session,
) -> bool:
    """Quick connectivity check via 204 endpoint.

    Args:
        session: Active requests session.

    Returns:
        True if network is reachable.
    """
    try:
        r = session.get(CONNECTIVITY_CHECK_URL, timeout=5)
        return r.status_code == 204
    except Exception:
        return False


def _get_local_ip() -> str:
    """Detect local IP via UDP socket trick.

    Opens a UDP socket to 8.8.8.8:80 and reads the local
    address. Returns an empty string if detection fails.

    Returns:
        Local IP address string.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return ""
    finally:
        sock.close()


class SEULogin:
    """SEU Dr.COM ePortal login client."""

    def __init__(
        self,
        username: str,
        password: str,
        isp: str = "campus",
        timeout: int = 10,
    ) -> None:
        self.username = username
        self.password = password
        self.isp = isp
        self.timeout = timeout

        self.session = requests.Session()
        self.session.trust_env = False  # Both authentication modes use the local portal.
        self.session.verify = False  # self-signed cert on :801
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 10; Pixel 10) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/155.0.0.0 Mobile Safari/537.36"
                ) if isp == "campus" else (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Origin": "https://w.seu.edu.cn",
                "Referer": "https://w.seu.edu.cn/",
            }
        )

        self.wlan_user_ip: str = ""
        self.wlan_ac_ip: str = ""
        self.wlan_ac_name: str = ""
        self.already_online = False

    def _get_campus_portal_params(self) -> bool:
        """Discover this connection's AC parameters, without ISP fallbacks."""
        self.already_online = False
        self.wlan_user_ip = self.wlan_ac_ip = self.wlan_ac_name = ""
        for probe_url in (CONNECTIVITY_CHECK_URL, "http://w.seu.edu.cn/"):
            try:
                resp = self.session.get(probe_url, timeout=self.timeout)
                logger.debug(
                    "Campus discovery: probe=%s HTTP=%d official_host=%s redirects=%d",
                    "connectivity" if probe_url == CONNECTIVITY_CHECK_URL else "portal",
                    resp.status_code,
                    urlparse(resp.url).hostname == "w.seu.edu.cn",
                    len(getattr(resp, "history", [])),
                )
                if resp.status_code == 204 and urlparse(resp.url).hostname == urlparse(CONNECTIVITY_CHECK_URL).hostname:
                    self.already_online = True
                    return True
                urls = [resp.url] + [item.url for item in getattr(resp, "history", [])]
                urls += re.findall(
                    r'https?://w\.seu\.edu\.cn/[^\s\'"<>]+',
                    html.unescape(resp.text),
                )
                urls.sort(key=lambda url: not (
                    urlparse(url).hostname == "w.seu.edu.cn"
                    and parse_qs(urlparse(url).query).get("wlanacip")
                ))
                for portal_url in urls:
                    parsed = urlparse(portal_url)
                    if parsed.hostname != "w.seu.edu.cn" or parsed.scheme not in ("http", "https"):
                        continue
                    params = parse_qs(parsed.query)
                    ac_ip = params.get("wlanacip", [""])[0]
                    logger.debug(
                        "Campus candidate: query_user_ip=%s query_ac_ip=%s query_ac_name=%s",
                        bool(params.get("wlanuserip")),
                        bool(ac_ip),
                        bool(params.get("wlanacname")),
                    )
                    user_ip = params.get("wlanuserip", [""])[0]
                    if not user_ip or not ac_ip:
                        page = resp if portal_url == resp.url else self.session.get(portal_url, timeout=self.timeout)
                        match = re.search(r'(?:wlanuserip|v46ip|ss5|v4ip)["\s:=]+["\']?([\d.]+)', page.text)
                        user_ip = user_ip or (match.group(1) if match else "")
                        if not ac_ip and page.status_code == 200 and "Dr.COMWebLoginID_0.htm" in page.text:
                            ac_ip = CAMPUS_DEFAULT_AC_IP
                            logger.debug("Campus controller: using capture-verified WLAN default")
                    try:
                        if IPv4Address(user_ip).is_unspecified or IPv4Address(ac_ip).is_unspecified:
                            continue
                    except ValueError:
                        logger.debug("Campus candidate rejected: invalid or missing IPv4 parameter")
                        continue
                    self.wlan_user_ip = user_ip
                    self.wlan_ac_ip = ac_ip
                    self.wlan_ac_name = params.get("wlanacname", [""])[0]
                    logger.debug("Campus portal parameters obtained")
                    return True
            except requests.exceptions.RequestException as exc:
                logger.debug(
                    "Campus discovery: probe=%s exception=%s",
                    "connectivity" if probe_url == CONNECTIVITY_CHECK_URL else "portal",
                    type(exc).__name__,
                )
                continue
        logger.warning("Campus portal parameters unavailable; authentication stopped")
        return False

    def _get_portal_params(self) -> bool:
        """Fetch dynamic params from the portal page.

        Falls back to socket-based local IP detection when
        the portal page is unreachable or doesn't provide
        ``wlanuserip``.

        Returns:
            True if params obtained (or fallback used).
        """
        if self.isp == "campus":
            return self._get_campus_portal_params()
        try:
            resp = self.session.get(
                PORTAL_PAGE_URL,
                allow_redirects=True,
                timeout=self.timeout,
            )
            params = parse_qs(
                urlparse(resp.url).query,
            )

            self.wlan_user_ip = params.get(
                "wlanuserip",
                [""],
            )[0]
            self.wlan_ac_ip = params.get(
                "wlanacip",
                [""],
            )[0]
            self.wlan_ac_name = params.get(
                "wlanacname",
                [""],
            )[0]

            # Fallback: extract from page JS
            if not self.wlan_user_ip:
                m = re.search(
                    r'(?:wlanuserip|v46ip|ss5|v4ip)["\s:=]+["\']?([\d.]+)',
                    resp.text,
                )
                if m:
                    self.wlan_user_ip = m.group(1)

            if not self.wlan_ac_ip:
                m = re.search(
                    r'wlanacip["\s:=]+["\']?([\d.]+)',
                    resp.text,
                )
                self.wlan_ac_ip = m.group(1) if m else DEFAULT_AC_IP

            logger.debug("Portal parameters obtained")
            return True

        except requests.exceptions.Timeout:
            logger.warning(
                "Portal params timeout, using fallback",
            )
            self.wlan_ac_ip = DEFAULT_AC_IP
            return True

        except requests.exceptions.ConnectionError:
            logger.warning(
                "Cannot reach portal, using fallback",
            )
            self.wlan_ac_ip = DEFAULT_AC_IP
            return True

        finally:
            # Socket IP fallback if portal didn't give us one
            if not self.wlan_user_ip:
                self.wlan_user_ip = _get_local_ip()
                logger.debug("Local IP detection attempted")

    def _build_login_params(self) -> dict[str, str]:
        """Build GET query parameters for login.

        Format verified from browser DevTools capture:
        user_account = ,0,username@isp_suffix

        Returns:
            Dict of query string parameters.
        """
        suffix = ISP_SUFFIX.get(self.isp, "")
        user_account = f",1,{self.username}" if self.isp == "campus" else f",0,{self.username}{suffix}"

        params: dict[str, str] = {
            "c": "Portal",
            "a": "login",
            "callback": JSONP_CALLBACK,
            "login_method": "1",
            "user_account": user_account,
            "user_password": self.password,
            "wlan_user_ip": self.wlan_user_ip or "",
            "wlan_user_ipv6": "",
            "wlan_user_mac": "000000000000",
            "wlan_ac_ip": self.wlan_ac_ip or DEFAULT_AC_IP,
            "wlan_ac_name": self.wlan_ac_name or "",
            "jsVersion": "3.3.3" if self.isp == "campus" else JS_VERSION,
            "v": REQ_VERSION,
        }

        logger.debug("Login parameters prepared")
        return params

    def login(self) -> tuple[int, str]:
        """Execute login attempt.

        Returns:
            Tuple of (status_code, message).
        """
        if not self._get_portal_params():
            return ERR_NETWORK, "Cannot get portal params"
        if self.already_online:
            return OK, "Already online (network verified)"
        if not self.wlan_user_ip:
            return ERR_NETWORK, "Cannot get portal user IP"

        params = self._build_login_params()
        suffix = ISP_SUFFIX.get(self.isp, "")
        isp_name = ISP_DISPLAY.get(self.isp, self.isp)

        try:
            resp = self.session.get(
                CAMPUS_PORTAL_BASE if self.isp == "campus" else PORTAL_BASE,
                params=params,
                timeout=self.timeout,
            )
            resp_text = resp.text.strip()
            logger.debug("Login response HTTP %d", resp.status_code)
        except requests.exceptions.Timeout:
            return ERR_OTHER, "Login request timeout"
        except requests.exceptions.ConnectionError as exc:
            return ERR_NETWORK, f"Connection failed: {type(exc).__name__}"
        except Exception as exc:
            return ERR_OTHER, f"Request error: {type(exc).__name__}"

        # Parse JSONP: dr1003({"result":1,"msg":"..."})
        data = _parse_jsonp(resp_text)
        result = data.get("result")
        logger.debug("Authentication result: %s", result if result in (0, "0", 1, "1", 2, "2") else "unknown")

        if result in (1, "1", 2, "2"):
            # 1 = auth success, 2 = already online
            s_disp = f"({suffix})" if suffix else ""
            # Decode server message for logging
            raw_msg = data.get("msg", "")
            srv_msg = ""
            if raw_msg and isinstance(raw_msg, str):
                try:
                    srv_msg = base64.b64decode(
                        raw_msg,
                    ).decode("utf-8")
                except Exception:
                    srv_msg = raw_msg
            msg = f"Login OK | {isp_name}{s_disp}"
            if srv_msg:
                logger.info("Server confirmed authentication")
            return OK, msg

        # Auth failed - extract error detail
        detail = _extract_fail_detail(data)
        if detail:
            return ERR_AUTH, "Auth failed: server rejected credentials"

        # Fallback: verify connectivity
        if resp.status_code == 200 and resp_text:
            if _verify_connectivity(self.session):
                msg = f"Login OK (net verified) | {isp_name}"
                return OK, msg

        return ERR_AUTH, (
            f"Login failed, result={result}, HTTP {resp.status_code}"
        )

    def logout(self) -> tuple[int, str]:
        """Logout current session.

        Returns:
            Tuple of (status_code, message).
        """
        try:
            resp = self.session.get(
                PORTAL_BASE,
                params={
                    "c": "Portal",
                    "a": "logout",
                    "callback": JSONP_CALLBACK,
                },
                timeout=self.timeout,
            )
            data = _parse_jsonp(resp.text.strip())
            result = data.get("result")
            if result in (1, "1") or resp.status_code == 200:
                return OK, "Logout OK"
            return ERR_OTHER, "Logout unexpected: server rejected request"
        except Exception as exc:
            return ERR_OTHER, f"Logout failed: {type(exc).__name__}"

    def query_status(self) -> tuple[int, str]:
        """Query online status.

        Returns:
            Tuple of (status_code, message).
        """
        try:
            resp = self.session.get(
                "https://w.seu.edu.cn/drcom/chkstatus",
                params={
                    "callback": JSONP_CALLBACK,
                },
                timeout=self.timeout,
            )
            data = _parse_jsonp(resp.text.strip())
            if data.get("result") in (1, "1"):
                return OK, "Online"
            if data.get("result") in (0, "0"):
                return ERR_NETWORK, "Offline"
            return ERR_OTHER, "Status response unavailable"
        except Exception as exc:
            return ERR_OTHER, f"Query failed: {type(exc).__name__}"


# ── Login Flow ────────────────────────────────────────────


class NetworkDetectionError(RuntimeError):
    """Safe network-selection error, containing no credentials."""


def detect_network_isp(isp: str) -> str:
    """Select authentication from the currently connected Windows SSID."""
    if os.name != "nt":
        raise NetworkDetectionError("Auto detection requires Windows; use manual mode")
    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise NetworkDetectionError("Wi-Fi detection failed; use manual mode") from None
    if result.returncode != 0:
        raise NetworkDetectionError(
            "Cannot read Wi-Fi; check Windows location permission or use manual mode"
        )
    # Parse only SSID, never BSSID or localized status text.
    ssids = set(re.findall(rb"^\s*SSID\s*:\s*([^\r\n]+)", result.stdout, re.MULTILINE))
    ssids = {ssid.strip() for ssid in ssids}
    if ssids == {b"SEU-WLAN"}:
        return "campus"
    if ssids == {b"SEU-ISP"}:
        if isp not in ("telecom", "unicom", "mobile"):
            raise NetworkDetectionError("SEU-ISP requires a configured operator")
        return isp
    raise NetworkDetectionError(
        "Connect only SEU-WLAN or SEU-ISP before login, or use manual mode"
    )


def create_client(config: _Config) -> SEULogin:
    """Build SEULogin from config dict.

    Args:
        config: Config dict.

    Returns:
        SEULogin instance.
    """
    isp = str(config.get("isp", "campus"))
    if config.get("auto_network", True):
        isp = detect_network_isp(isp)
    logger.debug("Authentication mode selected: %s", isp if isp in ISP_SUFFIX else "unknown")
    return SEULogin(
        username=str(config.get("username", "")),
        password=str(config.get("password", "")),
        isp=isp,
        timeout=int(config.get("timeout", 10)),
    )


def run_login(
    config: _Config,
    verbose: bool = False,
) -> int:
    """Full login flow with retry.

    Args:
        config: Config dict.
        verbose: Print progress to stdout.

    Returns:
        Exit status code.
    """
    username = str(config.get("username", ""))
    password = str(config.get("password", ""))
    retry_count = int(config.get("retry_count", 3))
    retry_delay = int(config.get("retry_delay", 5))

    if not username or not password:
        msg = "Username/password not configured"
        logger.error(msg)
        if not config.get("silent"):
            show_error(msg)
        return ERR_CONFIG

    code, msg = ERR_OTHER, ""

    for attempt in range(1, retry_count + 1):
        try:
            client = create_client(config)
        except NetworkDetectionError as exc:
            logger.error("%s", exc)
            print(f"[ERR] {exc}")
            return ERR_NETWORK
        logger.info(
            "Login mode: %s | attempt=%d/%d",
            ISP_DISPLAY.get(client.isp, client.isp),
            attempt,
            retry_count,
        )
        code, msg = client.login()

        if code == OK:
            logger.info("[Attempt %d] %s", attempt, msg)
            print(f"[OK] {msg}")
            return OK

        logger.warning("[Attempt %d] %s", attempt, msg)

        if attempt < retry_count:
            delay = retry_delay * attempt
            logger.info("Retry in %ds...", delay)
            time.sleep(delay)

    final_msg = f"Login failed after {retry_count} tries"
    logger.error("%s: %s", final_msg, msg)

    if not config.get("silent"):
        show_error(final_msg)
    elif verbose:
        print(f"[ERR] {final_msg}")

    return code


def run_logout(config: _Config) -> int:
    """Logout using config credentials.

    Args:
        config: Config dict.

    Returns:
        Exit status code.
    """
    client = create_client({**config, "auto_network": False})
    code, msg = client.logout()
    logger.info(msg)
    tag = "OK" if code == OK else "ERR"
    print(f"[{tag}] {msg}")
    return code


def run_status(config: _Config) -> int:
    """Query status using config credentials.

    Args:
        config: Config dict.

    Returns:
        Exit status code.
    """
    client = create_client({**config, "auto_network": False})
    code, msg = client.query_status()
    tag = "ONLINE" if code == OK else "OFFLINE"
    print(f"[{tag}] {msg}")
    return code


# ── Auto-Start (Windows Task Scheduler) ──────────────────


def install_auto_start() -> int:
    """Install auto-start via Windows Task Scheduler.

    Uses pythonw.exe for windowless execution with a
    30-second post-login delay.

    Returns:
        Exit status code.
    """
    pythonw = sys.executable.replace(
        "python.exe",
        "pythonw.exe",
    )
    if not os.path.exists(pythonw):
        pythonw = sys.executable
        logger.warning("pythonw.exe not found, fallback")

    script_path = str(SCRIPT_DIR / "seu_login.py")

    cmd = (
        f"schtasks /Create "
        f'/TN "{TASK_NAME}" '
        f'/TR "\\"{pythonw}\\" \\"{script_path}\\"" '
        f"/SC ONLOGON "
        f"/DELAY 0000:30 "
        f"/RL HIGHEST "
        f"/F"
    )

    logger.info("Installing auto-start")

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            print(f"[OK] Auto-start installed ({TASK_NAME})")
            print(f"     Executable: {pythonw}")
            print(f"     Script: {script_path}")
            print("     Trigger: ONLOGON + 30s delay")
            logger.info("Auto-start installed")
            return OK

        err = result.stderr.strip() or result.stdout.strip()
        denied = "\u62d2\u7edd" in err or "denied" in err.lower()
        if denied:
            print("[!] Permission denied. Run as admin:")
            print(f'    python "{script_path}" --install-start')
            return ERR_OTHER

        print(f"[ERR] Install failed: {err}")
        logger.error("Install failed: %s", err)
        return ERR_OTHER

    except Exception as exc:
        print(f"[ERR] Install error: {exc}")
        logger.error("Install error: %s", exc)
        return ERR_OTHER


def remove_auto_start() -> int:
    """Remove auto-start task.

    Returns:
        Exit status code.
    """
    cmd = f'schtasks /Delete /TN "{TASK_NAME}" /F'

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            print(f"[OK] Auto-start removed ({TASK_NAME})")
            logger.info("Auto-start removed")
            return OK

        err = result.stderr.strip() or result.stdout.strip()
        not_found = "\u627e\u4e0d\u5230" in err or "cannot find" in err.lower()
        if not_found:
            print(f"[INFO] Task {TASK_NAME} not found")
            return OK

        print(f"[ERR] Remove failed: {err}")
        return ERR_OTHER

    except Exception as exc:
        print(f"[ERR] Remove error: {exc}")
        return ERR_OTHER


# ── Error Popup ───────────────────────────────────────────


def show_error(
    message: str,
    title: str = "SEU Login Failed",
) -> None:
    """Show Windows MessageBox error.

    Args:
        message: Error text.
        title: Dialog title.
    """
    try:
        import ctypes

        mb_ok = 0x00000000
        mb_iconerror = 0x00000010
        ctypes.windll.user32.MessageBoxW(
            0,
            str(message),
            str(title),
            mb_ok | mb_iconerror,
        )
    except Exception:
        print(f"[ERROR] {message}", file=sys.stderr)


# ── Daemon Mode ──────────────────────────────────────────


def automatic_login_check(config: _Config) -> int:
    """Authenticate only after the portal explicitly reports offline."""
    if not config.get("auto_login", True):
        return OK
    if not config.get("username") or not config.get("password"):
        return ERR_CONFIG
    try:
        client = create_client(config)
        code, _ = client.query_status()
    except NetworkDetectionError:
        return ERR_NETWORK
    if code == OK:
        logger.debug("Auto check: already authenticated; login skipped")
        return OK
    if code != ERR_NETWORK:
        logger.debug("Auto check: portal status unavailable; waiting")
        return code
    logger.info("Auto check: portal reports offline; authenticating")
    return run_login({**config, "silent": True})


def daemon_mode(config: _Config) -> None:
    """Periodic reconnect daemon.

    Args:
        config: Config dict.
    """
    interval = max(5, int(config.get("check_interval", 30)))
    logger.info("Daemon start, interval=%ds", interval)
    print("[DAEMON] Running (Ctrl+C to stop)")

    while True:
        try:
            code = automatic_login_check(config)
            if code == OK:
                logger.info("Daemon: network OK")
            else:
                logger.warning("Daemon: code=%d", code)
        except KeyboardInterrupt:
            print("\n[DAEMON] Stopped")
            break
        except Exception as exc:
            logger.error("Daemon error: %s", type(exc).__name__)

        time.sleep(interval)


def network_connect_login(config: _Config) -> int:
    """Run a bounded check after a Windows Wi-Fi connection event."""
    event_config = {**config, "auto_login": True, "auto_network": True, "retry_count": 1}
    for attempt in range(3):
        code = automatic_login_check(event_config)
        if code in (OK, ERR_AUTH, ERR_CONFIG):
            return code
        if attempt < 2:
            time.sleep(5)
    return code


# ── CLI Entry Point ──────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    """Build argument parser.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        description="SEU campus network auto-login",
        formatter_class=(argparse.RawDescriptionHelpFormatter),
        epilog=(
            "Examples:\n"
            "  seu_login.py --setup\n"
            "  seu_login.py --isp mobile\n"
            "  seu_login.py --logout\n"
            "  seu_login.py --install-start\n"
            "  seu_login.py --daemon\n"
        ),
    )

    parser.add_argument(
        "--setup",
        action="store_true",
        help="Interactive setup wizard",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        default=True,
        help="Login (default action)",
    )
    parser.add_argument(
        "--logout",
        action="store_true",
        help="Logout current session",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Query online status",
    )
    parser.add_argument(
        "--install-start",
        action="store_true",
        help="Install Windows auto-start task",
    )
    parser.add_argument(
        "--remove-start",
        action="store_true",
        help="Remove auto-start task",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Daemon mode: periodic reconnect",
    )
    parser.add_argument(
        "--username",
        "-u",
        type=str,
        help="Override username (not saved)",
    )
    parser.add_argument(
        "--password",
        "-p",
        type=str,
        help="Override password (not saved)",
    )
    parser.add_argument(
        "--isp",
        type=str,
        choices=list(ISP_SUFFIX.keys()),
        help="ISP: campus/telecom/unicom/mobile",
    )
    parser.add_argument(
        "--manual-network",
        action="store_true",
        help="Use configured ISP without Windows SSID detection",
    )
    parser.add_argument(
        "--on-network-connect",
        action="store_true",
        help="Bounded automatic authentication for a Windows Wi-Fi connection event",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=str(CONFIG_FILE),
        help=f"Config path (default: {CONFIG_FILE})",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--silent",
        action="store_true",
        help="Silent mode (popup on error only)",
    )

    return parser


def main() -> int:
    """CLI entry point.

    Returns:
        Exit status code.
    """
    parser = _build_parser()
    args = parser.parse_args()
    config_path = Path(args.config)

    setup_logging(verbose=args.verbose)
    logger.debug("Started")

    # ── Immediate commands ──
    if args.setup:
        interactive_setup(config_path)
        return OK

    if args.install_start:
        return install_auto_start()

    if args.remove_start:
        return remove_auto_start()

    # ── Load config ──
    config = load_config(config_path)
    if not config:
        print("[!] No config. Run --setup first.")
        print(f"    Path: {config_path}")
        return ERR_CONFIG

    # CLI overrides
    if args.username:
        config["username"] = args.username
    if args.password:
        config["password"] = args.password
    if args.isp:
        config["isp"] = args.isp
    if args.manual_network:
        config["auto_network"] = False
    if args.silent:
        config["silent"] = True

    # ── Dispatch ──
    if args.logout:
        return run_logout(config)

    if args.status:
        return run_status(config)

    if args.on_network_connect:
        if args.daemon:
            print("[ERR] Choose event-triggered mode or daemon mode")
            return ERR_CONFIG
        return network_connect_login(config)

    if args.daemon:
        daemon_mode(config)
        return OK

    return run_login(config, verbose=args.verbose)


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        print("\n[Interrupted]")
        code = 0
    except NetworkDetectionError as exc:
        logger.error("%s", exc)
        print(f"[ERR] {exc}")
        code = ERR_NETWORK
    except Exception as exc:
        logger.error("Uncaught: %s", type(exc).__name__)
        code = ERR_OTHER
        try:
            show_error(f"Script error: {type(exc).__name__}")
        except Exception:
            logger.debug("show_error also failed")

    sys.exit(code)
