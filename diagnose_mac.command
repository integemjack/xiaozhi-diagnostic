#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Xiaozhi Diagnostic Center - macOS Version
Double-click this .command file in Finder to run.
Requires: Python 3 (pre-installed on macOS), Docker.
Uses Tkinter for GUI (included with macOS Python).
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import subprocess
import re
import os
import queue
import socket
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LAST_IP_FILE = os.path.join(SCRIPT_DIR, ".last_ip")
WS_PORT = 8000
WEB_PORT = 8002
VISION_PORT = 8003
DB_CONTAINER = "xiaozhi-esp32-server-db"
DB_USER = "root"
DB_PASS = "123456"
DB_NAME = "xiaozhi_esp32_server"
CONTAINERS = [
    "xiaozhi-esp32-server",
    "xiaozhi-esp32-server-web",
    "xiaozhi-esp32-server-db",
    "xiaozhi-esp32-server-redis",
]

# Message queue for thread-safe UI updates
msg_queue = queue.Queue()

# ===================== Utility functions =====================

def run_cmd(cmd, timeout=30):
    """Run a shell command and return (returncode, stdout)."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except subprocess.TimeoutExpired:
        return -1, ""
    except Exception as e:
        return -1, str(e)


def get_lan_ips():
    """Get this machine's LAN IPs."""
    ips = []
    try:
        out = subprocess.check_output(
            "ifconfig 2>/dev/null || ip addr 2>/dev/null",
            shell=True, text=True
        )
        for m in re.finditer(
            r"inet\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", out
        ):
            ip = m.group(1)
            if ip.startswith("127."):
                continue
            if (ip.startswith("192.168.") or ip.startswith("10.") or
                re.match(r"^172\.(1[6-9]|2\d|3[0-1])\.", ip)):
                ips.append(ip)
    except Exception:
        pass
    return list(set(ips))


def port_listening(port):
    """Check if a port is listening locally."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        result = s.connect_ex(("127.0.0.1", port))
        s.close()
        return result == 0
    except Exception:
        return False

def http_get(url, timeout=5):
    """Simple HTTP GET using urllib."""
    import urllib.request
    try:
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        code = None
        if hasattr(e, "code"):
            code = e.code
        return code, str(e)


def docker_exec_sql(sql):
    """Execute SQL in the DB container and return output."""
    cmd = f'docker exec {DB_CONTAINER} mysql -u{DB_USER} -p{DB_PASS} -N -e "{sql}" {DB_NAME}'
    rc, out = run_cmd(cmd)
    return out if rc == 0 or out else ""


# ===================== Worker functions =====================

class DiagnosticApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Xiaozhi Diagnostic Center")
        self.root.geometry("960x680")
        self.root.minsize(820, 600)

        self.running = False
        self.cancel = False
        self.state = {}

        self._build_ui()
        self._poll_queue()

    def _build_ui(self):
        # Tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=6)

        # Tab 1: Connection
        self.tab_conn = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_conn, text="  1. Connection  ")
        self._build_conn_tab()

        # Tab 2: Conversation Health
        self.tab_chat = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_chat, text="  2. Conversation Health  ")
        self._build_chat_tab()

        # Tab 3: Devices
        self.tab_dev = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_dev, text="  3. Devices  ")
        self._build_dev_tab()

    def _build_conn_tab(self):
        bar = ttk.Frame(self.tab_conn)
        bar.pack(fill="x", padx=8, pady=6)
        self.btn_server = ttk.Button(bar, text="Check Server",
                                     command=self._start_server_check)
        self.btn_server.pack(side="left", padx=4)
        self.btn_monitor = ttk.Button(bar, text="Monitor Device (45s)",
                                      command=self._start_monitor, state="disabled")
        self.btn_monitor.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(bar, text="Stop", command=self._stop,
                                   state="disabled")
        self.btn_stop.pack(side="left", padx=4)
        self.progress = ttk.Progressbar(bar, length=200, mode="determinate")
        self.progress.pack(side="left", padx=12)

        pane = ttk.PanedWindow(self.tab_conn, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8, pady=4)

        self.conn_list = scrolledtext.ScrolledText(pane, width=50, height=20,
                                                   state="disabled", wrap="word")
        pane.add(self.conn_list, weight=1)

        self.conn_log = scrolledtext.ScrolledText(pane, width=50, height=20,
                                                  bg="#1e2230", fg="#dce0e6",
                                                  state="disabled", wrap="word")
        pane.add(self.conn_log, weight=1)

        self.conn_verdict = tk.Label(self.tab_conn, text="  Click [Check Server] to start",
                                     bg="#3c424e", fg="white", anchor="w",
                                     font=("Helvetica", 12, "bold"), padx=14, pady=10)
        self.conn_verdict.pack(fill="x", side="bottom")

    def _build_chat_tab(self):
        bar = ttk.Frame(self.tab_chat)
        bar.pack(fill="x", padx=8, pady=6)
        self.btn_chat = ttk.Button(bar, text="Analyze Conversation Logs",
                                   command=self._start_chat)
        self.btn_chat.pack(side="left", padx=4)

        pane = ttk.PanedWindow(self.tab_chat, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8, pady=4)

        self.chat_list = scrolledtext.ScrolledText(pane, width=50, height=20,
                                                   state="disabled", wrap="word")
        pane.add(self.chat_list, weight=1)

        self.chat_log = scrolledtext.ScrolledText(pane, width=50, height=20,
                                                  bg="#1e2230", fg="#dce0e6",
                                                  state="disabled", wrap="word")
        pane.add(self.chat_log, weight=1)

        self.chat_verdict = tk.Label(self.tab_chat,
                                     text="  Click [Analyze Conversation Logs] to start",
                                     bg="#3c424e", fg="white", anchor="w",
                                     font=("Helvetica", 12, "bold"), padx=14, pady=10)
        self.chat_verdict.pack(fill="x", side="bottom")

    def _build_dev_tab(self):
        bar = ttk.Frame(self.tab_dev)
        bar.pack(fill="x", padx=8, pady=6)
        self.btn_dev = ttk.Button(bar, text="Scan LAN Devices",
                                  command=self._start_devices)
        self.btn_dev.pack(side="left", padx=4)

        cols = ("Type", "IP", "MAC", "Xiaozhi", "Alias/Board", "Last Connected")
        self.dev_tree = ttk.Treeview(self.tab_dev, columns=cols, show="headings",
                                     height=18)
        for c in cols:
            self.dev_tree.heading(c, text=c)
            self.dev_tree.column(c, width=130)
        self.dev_tree.column("Type", width=70)
        self.dev_tree.column("Xiaozhi", width=70)
        self.dev_tree.pack(fill="both", expand=True, padx=8, pady=4)

        self.dev_status = tk.Label(self.tab_dev,
                                   text="  Click [Scan LAN Devices] to start",
                                   bg="#3c424e", fg="white", anchor="w",
                                   font=("Helvetica", 12, "bold"), padx=14, pady=8)
        self.dev_status.pack(fill="x", side="bottom")

    # ========== UI helpers ==========

    def _log(self, widget, text, tag=None):
        msg_queue.put(("log", widget, text, tag))

    def _item(self, widget, icon, text):
        msg_queue.put(("item", widget, icon, text))

    def _verdict(self, widget, text, color):
        msg_queue.put(("verdict", widget, text, color))

    def _set_buttons(self, enabled):
        state = "normal" if enabled else "disabled"
        self.btn_server.config(state=state)
        self.btn_monitor.config(state=state if enabled and self.state.get("server_ok") else "disabled")
        self.btn_chat.config(state=state)
        self.btn_dev.config(state=state)
        self.btn_stop.config(state="disabled" if enabled else "normal")

    def _poll_queue(self):
        """Process UI update messages from worker threads."""
        while not msg_queue.empty():
            try:
                msg = msg_queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    widget, text, tag = msg[1], msg[2], msg[3]
                    widget.config(state="normal")
                    widget.insert("end", text + "\n", tag)
                    widget.see("end")
                    widget.config(state="disabled")
                elif kind == "item":
                    widget, icon, text = msg[1], msg[2], msg[3]
                    widget.config(state="normal")
                    widget.insert("end", f" {icon}  {text}\n")
                    widget.see("end")
                    widget.config(state="disabled")
                elif kind == "verdict":
                    widget, text, color = msg[1], msg[2], msg[3]
                    widget.config(text=f"  {text}", bg=color)
                elif kind == "clear":
                    widget = msg[1]
                    widget.config(state="normal")
                    widget.delete("1.0", "end")
                    widget.config(state="disabled")
                elif kind == "done":
                    self.running = False
                    self._set_buttons(True)
                    self.progress.config(mode="determinate", value=0)
                elif kind == "progress":
                    val = msg[1]
                    if val == "indeterminate":
                        self.progress.config(mode="indeterminate")
                        self.progress.start(20)
                    else:
                        self.progress.stop()
                        self.progress.config(mode="determinate", value=val)
            except queue.Empty:
                break
        self.root.after(80, self._poll_queue)

    def _stop(self):
        self.cancel = True

    def _start_worker(self, target):
        if self.running:
            return
        self.running = True
        self.cancel = False
        self._set_buttons(False)
        t = threading.Thread(target=target, daemon=True)
        t.start()

    def _start_server_check(self):
        self._start_worker(self._worker_server)

    def _start_monitor(self):
        self._start_worker(self._worker_monitor)

    def _start_chat(self):
        self._start_worker(self._worker_chat)

    def _start_devices(self):
        self._start_worker(self._worker_devices)

    # ========== Server Check Worker ==========
    def _worker_server(self):
        L = self.conn_list
        LOG = self.conn_log
        V = self.conn_verdict
        msg_queue.put(("clear", L))
        msg_queue.put(("clear", LOG))
        msg_queue.put(("progress", "indeterminate"))
        self._verdict(V, "Checking server...", "#3c424e")
        self._log(LOG, "===== Server check started =====")

        # Docker
        rc, _ = run_cmd("docker info")
        docker_ok = (rc == 0)
        self.state["DockerOk"] = docker_ok
        if docker_ok:
            self._item(L, "\u2714", "Docker: running")
            self._log(LOG, "[OK] Docker is running")
        else:
            self._item(L, "\u2718", "Docker: NOT running")
            self._log(LOG, "[FAIL] Docker is not running. Start Docker first.")
        if self.cancel: msg_queue.put(("done",)); return

        # Containers
        running = []
        if docker_ok:
            rc, out = run_cmd("docker ps --format '{{.Names}}'")
            if out:
                running = [x.strip() for x in out.split("\n") if x.strip()]
        all_c = True
        for c in CONTAINERS:
            if self.cancel: msg_queue.put(("done",)); return
            if c in running:
                self._item(L, "\u2714", f"Container: {c}")
            else:
                self._item(L, "\u2718", f"Container: {c} NOT running")
                self._log(LOG, f"[FAIL] Container not running: {c}")
                all_c = False
        self.state["ContainersOk"] = all_c

        # Ports
        all_p = True
        port_map = {WS_PORT: "WebSocket", WEB_PORT: "Web/OTA", VISION_PORT: "Vision"}
        for p, desc in port_map.items():
            if self.cancel: msg_queue.put(("done",)); return
            if port_listening(p):
                self._item(L, "\u2714", f"Port {p} ({desc}): listening")
            else:
                self._item(L, "\u2718", f"Port {p} ({desc}): NOT listening")
                self._log(LOG, f"[FAIL] Port {p} not listening")
                all_p = False
        self.state["PortsOk"] = all_p

        # LAN IP
        lan_ips = get_lan_ips()
        self.state["LanIps"] = lan_ips
        server_ip = None
        for ip in lan_ips:
            if ip.startswith("192.168."):
                server_ip = ip; break
        if not server_ip and lan_ips:
            server_ip = lan_ips[0]
        self.state["ServerIp"] = server_ip
        ota_addr = f"http://{server_ip}:{WEB_PORT}/xiaozhi/ota/" if server_ip else f"http://<server-ip>:{WEB_PORT}/xiaozhi/ota/"
        self.state["OtaAddr"] = ota_addr
        self._log(LOG, f"Local LAN IP: {', '.join(lan_ips) if lan_ips else 'none'}")

        # OTA self-test
        if self.cancel: msg_queue.put(("done",)); return
        ota_ok = False
        ws_addr = None
        code, body = http_get(f"http://127.0.0.1:{WEB_PORT}/xiaozhi/ota/")
        if code and code == 200:
            ota_ok = True
            m = re.search(r"ws://[^\s\"']+", body)
            if m:
                ws_addr = m.group(0)
                self.state["OtaWsAddr"] = ws_addr
        elif code:
            ota_ok = True  # got a response, endpoint is alive
        self.state["OtaOk"] = ota_ok

        if ota_ok:
            self._item(L, "\u2714", f"OTA endpoint: alive")
            self._log(LOG, f"[OK] OTA endpoint alive. Device OTA address: {ota_addr}")
            self._log(LOG, f"     Note: trailing slash '/' at the end is REQUIRED.")
            if ws_addr:
                self._log(LOG, f"     (OTA hands devices WS: {ws_addr})")
        else:
            self._item(L, "!", f"OTA endpoint: not reachable locally")
            self._log(LOG, f"[WARN] OTA endpoint not reachable. Expected: {ota_addr}")
        self._log(LOG, f"     >>> Device OTA address MUST be exactly: {ota_addr}")

        # WebSocket port
        if self.cancel: msg_queue.put(("done",)); return
        ws_ok = port_listening(WS_PORT)
        self.state["WsReachable"] = ws_ok
        if ws_ok:
            self._item(L, "\u2714", "WebSocket port: reachable")
        else:
            self._item(L, "\u2718", "WebSocket port: NOT reachable")
            self._log(LOG, "[FAIL] WebSocket port not reachable")

        # IP consistency
        if self.cancel: msg_queue.put(("done",)); return
        db_ip = None
        if os.path.exists(LAST_IP_FILE):
            with open(LAST_IP_FILE) as f:
                db_ip = f.read().strip()
        self.state["DbIp"] = db_ip

        if not lan_ips:
            self._item(L, "\u2718", "IP: no LAN IP found")
            self._log(LOG, "[FAIL] This machine has no LAN IP.")
            self.state["IpMatch"] = False
        elif db_ip:
            if db_ip in lan_ips:
                self._item(L, "\u2714", f"IP: DB IP {db_ip} matches")
                self.state["IpMatch"] = True
            else:
                self._item(L, "\u2718", f"IP: DB={db_ip} NOT in {lan_ips}")
                self._log(LOG, f"[FAIL] DB IP ({db_ip}) != this machine ({', '.join(lan_ips)})")
                self._log(LOG, "       Fix: run changeIp.bat / changeIp.command")
                self.state["IpMatch"] = False
                # Alert to offer fix
                self.root.after(0, lambda: messagebox.showwarning(
                    "IP Mismatch",
                    f"Database IP ({db_ip}) does NOT match this machine ({', '.join(lan_ips)}).\n\n"
                    f"Devices will get a wrong address.\n\nRun changeIp.command to fix it."
                ))
        else:
            self._item(L, "!", "IP: .last_ip not found, skipped")
            self.state["IpMatch"] = None

        # Firewall (macOS: check if pf is enabled)
        if self.cancel: msg_queue.put(("done",)); return
        rc, out = run_cmd("sudo -n pfctl -s info 2>/dev/null | head -3")
        fw_on = "enabled" in out.lower() if out else False
        if fw_on:
            self._item(L, "!", "Firewall: PF is enabled")
            self._log(LOG, "[WARN] macOS PF firewall is enabled, may block devices.")
        else:
            self._item(L, "\u2714", "Firewall: OK")

        self._log(LOG, "===== Server check complete =====")

        # Verdict
        if not docker_ok or not all_c or not all_p or not ws_ok:
            self._verdict(V, "Server not ready: service/port problem. Start Docker and containers first.", "#ce3a3a")
        elif self.state.get("IpMatch") is False:
            self._verdict(V, "Services OK but DATABASE IP is wrong. Run changeIp.command.", "#d69e14")
        else:
            self._verdict(V, f"Server OK! Device OTA: {ota_addr} (keep trailing slash). Click [Monitor Device].", "#22a056")
            self.state["server_ok"] = True

        msg_queue.put(("progress", 0))
        msg_queue.put(("done",))

    # ========== Monitor Worker ==========
    def _worker_monitor(self):
        L = self.conn_list
        LOG = self.conn_log
        V = self.conn_verdict

        # Step 1: ask user to turn OFF
        ok = [None]
        def ask_off():
            ok[0] = messagebox.askokcancel(
                "Step 1: Turn OFF the device",
                "Please TURN OFF (power off) the Xiaozhi device now.\n\n"
                "When it is fully off, click [OK] to start monitoring."
            )
        self.root.after(0, ask_off)
        while ok[0] is None:
            if self.cancel: msg_queue.put(("done",)); return
            time.sleep(0.15)
        if not ok[0]:
            msg_queue.put(("done",)); return

        self._log(LOG, "\n===== Monitoring (45s) - now turn ON the device =====")
        self._verdict(V, "Monitoring... now TURN ON the device", "#3c424e")

        # Step 2: ask user to turn ON
        ok2 = [None]
        def ask_on():
            ok2[0] = messagebox.showinfo(
                "Step 2: Turn ON the device",
                "Monitoring has started.\n\nNow TURN ON the Xiaozhi device.\n\n"
                "Click [OK] - monitoring runs for 45 seconds."
            )
            ok2[0] = True
        self.root.after(0, ask_on)
        while ok2[0] is None:
            if self.cancel: msg_queue.put(("done",)); return
            time.sleep(0.15)

        # Monitor for connections
        lan_ips = self.state.get("LanIps", [])
        my_ips = set(lan_ips + ["127.0.0.1", "0.0.0.0"])
        saw_in = False
        in_ips = set()
        total = 45

        for elapsed in range(total):
            if self.cancel:
                self._log(LOG, "Monitoring stopped.")
                msg_queue.put(("done",)); return
            rc, out = run_cmd("netstat -an 2>/dev/null | grep ESTABLISHED")
            if out:
                for line in out.split("\n"):
                    for p in [WS_PORT, WEB_PORT, VISION_PORT]:
                        pat = re.search(
                            r"(\d+\.\d+\.\d+\.\d+)\.(\d+)\s+(\d+\.\d+\.\d+\.\d+)\.(\d+)",
                            line
                        )
                        if pat:
                            lip, lport = pat.group(1), pat.group(2)
                            rip, rport = pat.group(3), pat.group(4)
                            if lport == str(p) and rip not in my_ips:
                                if not saw_in:
                                    self._log(LOG, f"[FOUND] Device: {rip} -> local:{p}")
                                saw_in = True
                                in_ips.add(rip)
            msg_queue.put(("progress", int((elapsed+1)/total*100)))
            time.sleep(1)

        # Check docker logs
        saw_ota = False; saw_ws = False
        if self.state.get("DockerOk"):
            rc, sl = run_cmd("docker logs --since 60s xiaozhi-esp32-server 2>&1")
            if "conn - Headers" in sl:
                saw_ws = True
            if "OTA" in sl or "ota" in sl.lower():
                saw_ota = True

        # Verdicts
        ota_addr = self.state.get("OtaAddr", f"http://<server-ip>:{WEB_PORT}/xiaozhi/ota/")
        if saw_ws:
            self._item(L, "\u2714", "Device established WebSocket - connected!")
            self._log(LOG, "[OK] Device connected successfully.")
            self._verdict(V, "Device connected! Server and network are fine. If still unusable, check Conversation Health tab.", "#22a056")
        elif saw_ota or saw_in:
            self._item(L, "!", "Device reached server but no full connection")
            self._log(LOG, "[WARN] Device may have reached OTA but did not fully connect.")
            self._log(LOG, f"     The OTA address on the device may be wrong. Must be exactly:")
            self._log(LOG, f"         {ota_addr}")
            self._log(LOG, f"     IMPORTANT: trailing slash '/' at the end is REQUIRED.")
            self._verdict(V, f"No working connection. Check device OTA address: {ota_addr} (trailing slash required).", "#d69e14")
            # Alert
            self.root.after(0, lambda: messagebox.showwarning(
                "Check the Device OTA Address",
                f"The Xiaozhi device did not connect properly.\n\n"
                f"The OTA address on the device may be WRONG. It must be EXACTLY:\n\n"
                f"{ota_addr}\n\n"
                f"IMPORTANT: there MUST be a trailing slash '/' at the end.\n"
                f"- Correct : .../xiaozhi/ota/\n"
                f"- Wrong   : .../xiaozhi/ota   (missing slash -> fails)"
            ))
        else:
            self._item(L, "\u2718", "No device connected at all")
            self._log(LOG, "[RESULT] No device reached the server.")
            self._log(LOG, f"     Device OTA address must be exactly: {ota_addr}")
            self._log(LOG, f"     Trailing slash '/' is REQUIRED. Also check: same WiFi, no AP isolation.")
            self._verdict(V, f"No device connected! Check OTA address: {ota_addr} (trailing slash, same WiFi, no AP isolation).", "#ce3a3a")
            self.root.after(0, lambda: messagebox.showwarning(
                "Check the Device OTA Address",
                f"No device connected during monitoring.\n\n"
                f"The #1 cause is a wrong OTA address. It must be EXACTLY:\n\n"
                f"{ota_addr}\n\n"
                f"IMPORTANT: trailing slash '/' at the end is REQUIRED.\n"
                f"- Correct : .../xiaozhi/ota/\n"
                f"- Wrong   : .../xiaozhi/ota   (missing slash -> fails)\n\n"
                f"Also confirm device is on the SAME WiFi and router has no AP isolation."
            ))

        msg_queue.put(("progress", 0))
        msg_queue.put(("done",))

    # ========== Chat Health Worker ==========
    def _worker_chat(self):
        CL = self.chat_list
        CLOG = self.chat_log
        CV = self.chat_verdict
        msg_queue.put(("clear", CL))
        msg_queue.put(("clear", CLOG))
        msg_queue.put(("progress", "indeterminate"))
        self._verdict(CV, "Analyzing conversation logs...", "#3c424e")

        rc, _ = run_cmd("docker info")
        if rc != 0:
            self._item(CL, "\u2718", "Docker not running")
            self._verdict(CV, "Docker not running, cannot read logs.", "#ce3a3a")
            msg_queue.put(("done",)); return

        rc, log = run_cmd("docker logs --tail 600 xiaozhi-esp32-server 2>&1", timeout=20)
        if not log:
            self._item(CL, "\u2718", "Log is empty")
            self._verdict(CV, "No logs found.", "#d69e14")
            msg_queue.put(("done",)); return

        lines = log.split("\n")
        self._log(CLOG, f"Read {len(lines)} log lines.")

        # Checks
        conn_count = sum(1 for l in lines if "conn - Headers" in l)
        if conn_count > 0:
            self._item(CL, "\u2714", f"Device connection: {conn_count} recent")
        else:
            self._item(CL, "!", "Device connection: none in recent logs")

        llm_req = sum(1 for l in lines if "[LLM" in l or "base_url=" in l)
        llm_key_err = sum(1 for l in lines if "API key is not set" in l or "check_model_key" in l)
        llm_run_err = sum(1 for l in lines if "LLM stream processing error" in l or "Error in response generation" in l)

        if llm_key_err > 0:
            self._item(CL, "\u2718", "LLM: api_key NOT configured")
            self._log(CLOG, "[FAIL] An LLM api_key still has a placeholder (contains 'your...').")
            self._log(CLOG, "       A secondary model's key may be missing. Set real keys in Web console -> Model Config.")
        elif llm_run_err > 0:
            self._item(CL, "\u2718", f"LLM: {llm_run_err} runtime error(s)")
            self._log(CLOG, "[FAIL] LLM call failed (wrong key, no quota, or network).")
        elif llm_req > 0:
            self._item(CL, "\u2714", f"LLM: {llm_req} call(s), no errors")
        else:
            self._item(CL, "!", "LLM: no recent calls")

        tts_ok = sum(1 for l in lines if "providers.tts.base" in l)
        tts_err = sum(1 for l in lines if "tts" in l.lower() and "ERROR" in l)
        if tts_err > 0:
            self._item(CL, "\u2718", f"TTS: {tts_err} error(s)")
            self._log(CLOG, "[FAIL] TTS errors - device will have no sound.")
        elif tts_ok > 0:
            self._item(CL, "\u2714", f"TTS: {tts_ok} synthesis event(s)")
        else:
            self._item(CL, "!", "TTS: no recent activity")

        audio = sum(1 for l in lines if "sendAudioHandle" in l or "SentenceType" in l)
        if audio > 0:
            self._item(CL, "\u2714", f"Audio sent: {audio} push(es)")
        else:
            self._item(CL, "!", "Audio: no recent push")

        bye_hit = sum(1 for l in lines if "Time flies" in l or "end this conversation" in l or "reluctant" in l)
        if bye_hit > 0:
            self._item(CL, "!", f"Auto goodbye: triggered ({bye_hit})")
            self._log(CLOG, "[FOUND] Idle auto-goodbye was triggered.")
            self._log(CLOG, "        Symptom: device says sad farewell (crying face) then disconnects.")
            self._log(CLOG, "        This is NOT a fault - normal after ~120s idle.")
            self._log(CLOG, "        Fix: Web console -> Parameters -> increase close_connection_no_voice_time")
            self._log(CLOG, "             or set end_prompt.enable = false, then restart server container.")
        else:
            self._item(CL, "\u2714", "Auto goodbye: not triggered")

        w_err = sum(1 for l in lines if "get_weather" in l and ("ERROR" in l or "Authentication failed" in l))
        if w_err > 0:
            self._item(CL, "!", "Weather plugin: auth failed")
            self._log(CLOG, "[WARN] Weather plugin key/host wrong. Fix in Web console -> Plugins.")
        else:
            self._item(CL, "\u2714", "Weather plugin: OK")

        err_count = sum(1 for l in lines if "-ERROR-" in l or "Traceback" in l or "Exception" in l)
        if err_count > 0:
            self._item(CL, "!", f"Other errors: {err_count} in logs")
            err_lines = [l for l in lines if "-ERROR-" in l or "Traceback" in l][-5:]
            self._log(CLOG, "--- Recent error lines ---")
            for el in err_lines:
                self._log(CLOG, el[:180])
        else:
            self._item(CL, "\u2714", "No other errors")

        # Final verdict
        if bye_hit > 0:
            self._verdict(CV, "Main finding: 'crying then no response' = idle auto-goodbye, not a fault. Increase timeout or disable goodbye.", "#d69e14")
        elif llm_key_err > 0:
            self._verdict(CV, "LLM api_key not configured (placeholder). Set real keys in Web console.", "#ce3a3a")
        elif llm_run_err > 0:
            self._verdict(CV, "LLM calls failed at runtime. Check api_key / quota / network.", "#ce3a3a")
        elif tts_err > 0:
            self._verdict(CV, "TTS errors - device has no sound. Check TTS config.", "#ce3a3a")
        elif conn_count == 0:
            self._verdict(CV, "No recent device conversation. Check Connection tab first.", "#d69e14")
        else:
            self._verdict(CV, "Conversation pipeline looks healthy.", "#22a056")

        msg_queue.put(("progress", 0))
        msg_queue.put(("done",))

    # ========== Devices Worker ==========
    def _worker_devices(self):
        tree = self.dev_tree
        DS = self.dev_status
        msg_queue.put(("progress", "indeterminate"))
        self._verdict(DS, "Scanning LAN devices...", "#3c424e")
        # Clear tree
        self.root.after(0, lambda: [tree.delete(i) for i in tree.get_children()])

        lan_ips = get_lan_ips()
        if not lan_ips:
            self._verdict(DS, "No LAN IP found, cannot scan.", "#ce3a3a")
            msg_queue.put(("done",)); return

        base_ip = None
        for ip in lan_ips:
            if ip.startswith("192.168."):
                base_ip = ip; break
        if not base_ip:
            base_ip = lan_ips[0]
        prefix = ".".join(base_ip.split(".")[:3])

        # Query registered Xiaozhi devices from DB
        xz_map = {}
        rc, _ = run_cmd("docker info")
        if rc == 0:
            sql = f"SELECT mac_address,IFNULL(alias,''),IFNULL(last_connected_at,''),IFNULL(board,'') FROM ai_device"
            out = docker_exec_sql(sql)
            if out:
                for row in out.strip().split("\n"):
                    cols = row.split("\t")
                    if len(cols) >= 1 and cols[0]:
                        mac = cols[0].replace("-", ":").lower().strip()
                        xz_map[mac] = {
                            "alias": cols[1] if len(cols) > 1 else "",
                            "last": cols[2] if len(cols) > 2 else "",
                            "board": cols[3] if len(cols) > 3 else "",
                        }

        # Ping sweep
        self._verdict(DS, f"Pinging {prefix}.1-254...", "#3c424e")
        # Use fping if available, otherwise sequential ping
        run_cmd(f"fping -a -g {prefix}.1 {prefix}.254 -t 300 2>/dev/null", timeout=40)

        # Read ARP
        ip_mac = {}
        rc, arp_out = run_cmd("arp -a")
        if arp_out:
            for line in arp_out.split("\n"):
                m = re.search(
                    r"\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:]+)",
                    line
                )
                if m:
                    ip = m.group(1)
                    mac = m.group(2).lower()
                    if ip.startswith(prefix + "."):
                        ip_mac[ip] = mac

        # Add self
        try:
            import netifaces
            for iface in netifaces.interfaces():
                addrs = netifaces.ifaddresses(iface)
                if netifaces.AF_INET in addrs and netifaces.AF_LINK in addrs:
                    for a in addrs[netifaces.AF_INET]:
                        if a.get("addr") == base_ip:
                            mac = addrs[netifaces.AF_LINK][0].get("addr", "")
                            if mac:
                                ip_mac[base_ip] = mac.lower()
        except ImportError:
            pass

        # Build rows
        sorted_ips = sorted(ip_mac.keys(), key=lambda x: int(x.split(".")[-1]))
        xz_found = 0
        for ip in sorted_ips:
            if self.cancel: break
            mac = ip_mac[ip]
            is_xz = "No"
            alias = ""
            last = ""
            kind = "Other"
            if mac in xz_map:
                is_xz = "Yes"
                xz_found += 1
                info = xz_map[mac]
                alias = info["alias"] or info["board"]
                last = info["last"]
                kind = "Xiaozhi"
            if ip == base_ip:
                kind = "This Mac"
                if is_xz == "No":
                    alias = "(server)"
            tag = "xz" if is_xz == "Yes" else ""
            self.root.after(0, lambda i=ip, m=mac, x=is_xz, a=alias, l=last, k=kind, tg=tag:
                           tree.insert("", "end", values=(k, i, m, x, a, l), tags=(tg,)))

        # Offline registered devices
        for mac, info in xz_map.items():
            online = mac in ip_mac.values()
            if not online:
                alias = info["alias"] or info["board"]
                self.root.after(0, lambda m=mac, a=alias, l=info["last"]:
                               tree.insert("", "end", values=("Xiaozhi", "(offline)", m, "Yes", a, l), tags=("xz",)))

        # Style
        self.root.after(0, lambda: tree.tag_configure("xz", background="#e1f5e8"))

        total = len(sorted_ips)
        if xz_map:
            self._verdict(DS, f"Done: {total} LAN device(s), {xz_found} Xiaozhi online / {len(xz_map)} registered. Green = Xiaozhi.", "#22a056")
        else:
            self._verdict(DS, f"Done: {total} LAN device(s). No registered Xiaozhi in DB (or Docker not running).", "#d69e14")

        msg_queue.put(("progress", 0))
        msg_queue.put(("done",))


# ===================== Main =====================
if __name__ == "__main__":
    root = tk.Tk()
    app = DiagnosticApp(root)
    root.mainloop()
