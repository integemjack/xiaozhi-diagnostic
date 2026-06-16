#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Xiaozhi Diagnostic Center
Cross-platform GUI tool for diagnosing Xiaozhi device connection issues.
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import subprocess
import re
import os
import sys
import queue
import socket
import time
import platform

# ==================== Configuration ====================
def get_script_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(sys.argv[0]))

SCRIPT_DIR = get_script_dir()
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

IS_MAC = platform.system() == "Darwin"
IS_WIN = platform.system() == "Windows"

msg_queue = queue.Queue()


# ==================== Utility Functions ====================
def run_cmd(cmd, timeout=30):
    """Run a shell command and return (returncode, stdout)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout.strip()
    except subprocess.TimeoutExpired:
        return -1, ""
    except Exception as e:
        return -1, str(e)


def get_lan_ips():
    """Get this machine's LAN IPs."""
    ips = []
    try:
        if IS_WIN:
            rc, out = run_cmd("ipconfig")
        else:
            rc, out = run_cmd("ifconfig 2>/dev/null || ip addr 2>/dev/null")
        for m in re.finditer(
            r"(?:IPv4.*?|inet\s+)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", out
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
    """Simple HTTP GET."""
    import urllib.request
    try:
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        code = getattr(e, "code", None)
        return code, str(e)


def docker_exec_sql(sql):
    """Execute SQL in the DB container."""
    cmd = f'docker exec {DB_CONTAINER} mysql -u{DB_USER} -p{DB_PASS} -N -e "{sql}" {DB_NAME}'
    rc, out = run_cmd(cmd)
    return out if out else ""


# ==================== Application ====================
class DiagnosticApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Xiaozhi Diagnostic Center")
        self.root.geometry("1000x700")
        self.root.minsize(860, 620)
        self.running = False
        self.cancel = False
        self.state = {}
        self._build_ui()
        self._poll_queue()

    def _build_ui(self):
        style = ttk.Style()
        style.configure("TNotebook.Tab", padding=[12, 6])

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_conn = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_conn, text="  1. Connection  ")
        self._build_conn_tab()

        self.tab_chat = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_chat, text="  2. Conversation Health  ")
        self._build_chat_tab()

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
        self.progress = ttk.Progressbar(bar, length=220, mode="determinate")
        self.progress.pack(side="left", padx=12)

        pane = ttk.PanedWindow(self.tab_conn, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8, pady=4)
        self.conn_list = scrolledtext.ScrolledText(pane, width=48, height=20,
                                                   state="disabled", wrap="word")
        pane.add(self.conn_list, weight=1)
        self.conn_log = scrolledtext.ScrolledText(pane, width=48, height=20,
                                                  bg="#1e2230", fg="#dce0e6",
                                                  state="disabled", wrap="word",
                                                  font=("Consolas", 9))
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
        self.chat_list = scrolledtext.ScrolledText(pane, width=48, height=20,
                                                   state="disabled", wrap="word")
        pane.add(self.chat_list, weight=1)
        self.chat_log = scrolledtext.ScrolledText(pane, width=48, height=20,
                                                  bg="#1e2230", fg="#dce0e6",
                                                  state="disabled", wrap="word",
                                                  font=("Consolas", 9))
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
        self.dev_tree = ttk.Treeview(self.tab_dev, columns=cols, show="headings", height=16)
        for c in cols:
            self.dev_tree.heading(c, text=c)
            self.dev_tree.column(c, width=130)
        self.dev_tree.column("Type", width=80)
        self.dev_tree.column("Xiaozhi", width=70)
        self.dev_tree.pack(fill="both", expand=True, padx=8, pady=4)

        self.dev_status = tk.Label(self.tab_dev,
                                   text="  Click [Scan LAN Devices] to start",
                                   bg="#3c424e", fg="white", anchor="w",
                                   font=("Helvetica", 11, "bold"), padx=14, pady=8)
        self.dev_status.pack(fill="x", side="bottom")

    # ========== UI Helpers ==========
    def _log(self, widget, text):
        msg_queue.put(("log", widget, text))

    def _item(self, widget, icon, text):
        msg_queue.put(("item", widget, icon, text))

    def _verdict(self, widget, text, color):
        msg_queue.put(("verdict", widget, text, color))

    def _set_buttons(self, enabled):
        st = "normal" if enabled else "disabled"
        self.btn_server.config(state=st)
        self.btn_monitor.config(
            state="normal" if enabled and self.state.get("server_ok") else "disabled"
        )
        self.btn_chat.config(state=st)
        self.btn_dev.config(state=st)
        self.btn_stop.config(state="disabled" if enabled else "normal")

    def _poll_queue(self):
        while not msg_queue.empty():
            try:
                msg = msg_queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    w, text = msg[1], msg[2]
                    w.config(state="normal")
                    w.insert("end", text + "\n")
                    w.see("end")
                    w.config(state="disabled")
                elif kind == "item":
                    w, icon, text = msg[1], msg[2], msg[3]
                    w.config(state="normal")
                    w.insert("end", f" {icon}  {text}\n")
                    w.see("end")
                    w.config(state="disabled")
                elif kind == "verdict":
                    w, text, color = msg[1], msg[2], msg[3]
                    w.config(text=f"  {text}", bg=color)
                elif kind == "clear":
                    w = msg[1]
                    w.config(state="normal")
                    w.delete("1.0", "end")
                    w.config(state="disabled")
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
        threading.Thread(target=target, daemon=True).start()

    def _start_server_check(self):
        self._start_worker(self._worker_server)

    def _start_monitor(self):
        self._start_worker(self._worker_monitor)

    def _start_chat(self):
        self._start_worker(self._worker_chat)

    def _start_devices(self):
        self._start_worker(self._worker_devices)

    # ========== Server Check ==========
    def _worker_server(self):
        L, LOG, V = self.conn_list, self.conn_log, self.conn_verdict
        msg_queue.put(("clear", L)); msg_queue.put(("clear", LOG))
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
            self._log(LOG, "[FAIL] Docker not running. Start Docker first.")
        if self.cancel: msg_queue.put(("done",)); return

        # Containers
        running = []
        if docker_ok:
            rc, out = run_cmd("docker ps --format '{{.Names}}'")
            if out:
                running = [x.strip().strip("'") for x in out.split("\n") if x.strip()]
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
        server_ip = next((ip for ip in lan_ips if ip.startswith("192.168.")), None)
        if not server_ip and lan_ips:
            server_ip = lan_ips[0]
        self.state["ServerIp"] = server_ip
        ota_addr = f"http://{server_ip}:{WEB_PORT}/xiaozhi/ota/" if server_ip else f"http://<server-ip>:{WEB_PORT}/xiaozhi/ota/"
        self.state["OtaAddr"] = ota_addr
        self._log(LOG, f"LAN IP: {', '.join(lan_ips) if lan_ips else 'none'}")
        self._log(LOG, f"Device OTA address: {ota_addr}")
        self._log(LOG, "     (trailing slash '/' is REQUIRED)")

        # OTA self-test
        if self.cancel: msg_queue.put(("done",)); return
        ota_ok = False
        ws_addr = None
        code, body = http_get(f"http://127.0.0.1:{WEB_PORT}/xiaozhi/ota/")
        if code == 200:
            ota_ok = True
            m = re.search(r"ws://[^\s\"']+", body or "")
            if m:
                ws_addr = m.group(0)
                self.state["OtaWsAddr"] = ws_addr
        elif code:
            ota_ok = True
        self.state["OtaOk"] = ota_ok
        if ota_ok:
            self._item(L, "\u2714", "OTA endpoint: alive")
        else:
            self._item(L, "!", "OTA endpoint: not reachable")
            self._log(LOG, "[WARN] OTA endpoint not reachable locally.")

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
            self._item(L, "\u2718", "IP: no LAN IP")
            self.state["IpMatch"] = False
        elif db_ip:
            if db_ip in lan_ips:
                self._item(L, "\u2714", f"IP: DB IP {db_ip} matches")
                self.state["IpMatch"] = True
            else:
                self._item(L, "\u2718", f"IP: DB={db_ip} NOT in local IPs!")
                self._log(LOG, f"[FAIL] DB IP ({db_ip}) != machine IP ({', '.join(lan_ips)})")
                self._log(LOG, "       Run changeIp.bat (Win) or changeIp.command (Mac)")
                self.state["IpMatch"] = False
                self.root.after(0, lambda: messagebox.showwarning(
                    "IP Mismatch",
                    f"Database IP ({db_ip}) does NOT match this machine ({', '.join(lan_ips)}).\n\n"
                    f"Devices will get a wrong address.\n\nRun changeIp to fix it."
                ))
        else:
            self._item(L, "!", "IP: .last_ip not found")
            self.state["IpMatch"] = None

        self._log(LOG, "===== Server check complete =====")

        # Verdict
        if not docker_ok or not all_c or not all_p or not ws_ok:
            self._verdict(V, "Server not ready: service/port problem. Start Docker and services first.", "#ce3a3a")
        elif self.state.get("IpMatch") is False:
            self._verdict(V, "Services OK but DATABASE IP is wrong. Run changeIp to fix.", "#d69e14")
        else:
            self._verdict(V, f"Server OK! Device OTA: {ota_addr} (trailing slash required). Click [Monitor Device].", "#22a056")
            self.state["server_ok"] = True

        msg_queue.put(("progress", 0))
        msg_queue.put(("done",))

    # ========== Monitor ==========
    def _worker_monitor(self):
        L, LOG, V = self.conn_list, self.conn_log, self.conn_verdict

        # Step 1: Turn OFF
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

        self._log(LOG, "\n===== Monitoring (45s) =====")
        self._verdict(V, "Monitoring... now TURN ON the device", "#3c424e")
        msg_queue.put(("progress", "indeterminate"))

        # Step 2: Turn ON
        ok2 = [None]
        def ask_on():
            messagebox.showinfo(
                "Step 2: Turn ON the device",
                "Monitoring has started.\n\nNow TURN ON the Xiaozhi device.\n\n"
                "Click [OK] - monitoring runs for 45 seconds."
            )
            ok2[0] = True
        self.root.after(0, ask_on)
        while ok2[0] is None:
            if self.cancel: msg_queue.put(("done",)); return
            time.sleep(0.15)

        lan_ips = self.state.get("LanIps", [])
        my_ips = set(lan_ips + ["127.0.0.1", "0.0.0.0"])
        saw_in = False
        in_ips = set()
        total = 45

        for elapsed in range(total):
            if self.cancel:
                self._log(LOG, "Monitoring stopped."); msg_queue.put(("done",)); return
            if IS_WIN:
                rc, out = run_cmd("netstat -an", timeout=5)
            else:
                rc, out = run_cmd("netstat -an 2>/dev/null | grep ESTABLISHED", timeout=5)
            if out:
                for line in out.split("\n"):
                    if "ESTABLISHED" not in line:
                        continue
                    # Match IP:port patterns
                    parts = line.split()
                    for part in parts:
                        for p in [WS_PORT, WEB_PORT, VISION_PORT]:
                            # Windows: 192.168.1.5:8000  macOS: 192.168.1.5.8000
                            pat = re.search(r"(\d+\.\d+\.\d+\.\d+)[.:]" + str(p) + r"\b", part)
                            if pat and pat.group(1) in my_ips:
                                # This is local side, find remote
                                for rpart in parts:
                                    rpat = re.search(r"(\d+\.\d+\.\d+\.\d+)[.:]\d+", rpart)
                                    if rpat and rpat.group(1) not in my_ips and rpat.group(1) != "0.0.0.0":
                                        rip = rpat.group(1)
                                        if not saw_in:
                                            self._log(LOG, f"[FOUND] Device: {rip} -> port {p}")
                                        saw_in = True
                                        in_ips.add(rip)
            msg_queue.put(("progress", int((elapsed + 1) / total * 100)))
            time.sleep(1)

        # Check docker logs
        saw_ota = False; saw_ws = False
        if self.state.get("DockerOk"):
            rc, sl = run_cmd("docker logs --since 60s xiaozhi-esp32-server 2>&1", timeout=10)
            if sl:
                if "conn - Headers" in sl:
                    saw_ws = True
                if "OTA" in sl or "ota" in sl:
                    saw_ota = True

        # Verdicts
        ota_addr = self.state.get("OtaAddr", f"http://<server-ip>:{WEB_PORT}/xiaozhi/ota/")

        if saw_ws:
            self._item(L, "\u2714", "Device connected to WebSocket!")
            self._log(LOG, "[OK] Device connected successfully.")
            self._verdict(V, "Device connected! Network and server are fine. If still unusable, check Conversation Health.", "#22a056")
        elif saw_ota or saw_in:
            self._item(L, "!", "Device reached server but no full connection")
            self._log(LOG, f"[WARN] No working connection. OTA address must be: {ota_addr}")
            self._log(LOG, "       Trailing slash '/' at the end is REQUIRED.")
            self._verdict(V, f"No working connection. Check OTA address: {ota_addr} (trailing slash required).", "#d69e14")
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
            self._item(L, "\u2718", "No device connected")
            self._log(LOG, f"[FAIL] No device connected. OTA address must be: {ota_addr}")
            self._log(LOG, "       Trailing slash required. Also check: same WiFi, no AP isolation.")
            self._verdict(V, f"No device connected! Check OTA: {ota_addr} (trailing slash, same WiFi).", "#ce3a3a")
            self.root.after(0, lambda: messagebox.showwarning(
                "Check the Device OTA Address",
                f"No device connected during monitoring.\n\n"
                f"The OTA address on the device must be EXACTLY:\n\n"
                f"{ota_addr}\n\n"
                f"IMPORTANT: trailing slash '/' at the end is REQUIRED.\n"
                f"- Correct : .../xiaozhi/ota/\n"
                f"- Wrong   : .../xiaozhi/ota   (missing slash -> fails)\n\n"
                f"Also confirm device is on the SAME WiFi and no AP isolation."
            ))

        msg_queue.put(("progress", 0))
        msg_queue.put(("done",))

    # ========== Conversation Health ==========
    def _worker_chat(self):
        CL, CLOG, CV = self.chat_list, self.chat_log, self.chat_verdict
        msg_queue.put(("clear", CL)); msg_queue.put(("clear", CLOG))
        msg_queue.put(("progress", "indeterminate"))
        self._verdict(CV, "Analyzing logs...", "#3c424e")

        rc, _ = run_cmd("docker info")
        if rc != 0:
            self._item(CL, "\u2718", "Docker not running")
            self._verdict(CV, "Docker not running.", "#ce3a3a")
            msg_queue.put(("done",)); return

        rc, log = run_cmd("docker logs --tail 600 xiaozhi-esp32-server 2>&1", timeout=20)
        if not log:
            self._verdict(CV, "No logs found.", "#d69e14")
            msg_queue.put(("done",)); return
        lines = log.split("\n")
        self._log(CLOG, f"Read {len(lines)} lines.")

        conn_count = sum(1 for l in lines if "conn - Headers" in l)
        self._item(CL, "\u2714" if conn_count else "!", f"Connections: {conn_count}")

        llm_req = sum(1 for l in lines if "[LLM" in l or "base_url=" in l)
        llm_key = sum(1 for l in lines if "API key is not set" in l)
        llm_run = sum(1 for l in lines if "LLM stream processing error" in l)
        if llm_key:
            self._item(CL, "\u2718", "LLM: api_key NOT configured")
            self._log(CLOG, "[FAIL] An LLM api_key is a placeholder. Set real keys in Web console.")
        elif llm_run:
            self._item(CL, "\u2718", f"LLM: {llm_run} runtime error(s)")
            self._log(CLOG, "[FAIL] LLM call failed (wrong key/quota/network).")
        elif llm_req:
            self._item(CL, "\u2714", f"LLM: {llm_req} call(s), OK")
        else:
            self._item(CL, "!", "LLM: no recent calls")

        tts_ok = sum(1 for l in lines if "providers.tts.base" in l)
        tts_err = sum(1 for l in lines if "tts" in l.lower() and "ERROR" in l)
        if tts_err:
            self._item(CL, "\u2718", f"TTS: {tts_err} error(s)")
            self._log(CLOG, "[FAIL] TTS errors - device has no sound.")
        elif tts_ok:
            self._item(CL, "\u2714", f"TTS: {tts_ok} event(s)")
        else:
            self._item(CL, "!", "TTS: no activity")

        audio = sum(1 for l in lines if "sendAudioHandle" in l or "SentenceType" in l)
        self._item(CL, "\u2714" if audio else "!", f"Audio push: {audio}")

        bye = sum(1 for l in lines if "Time flies" in l or "end this conversation" in l or "reluctant" in l)
        if bye:
            self._item(CL, "!", f"Auto goodbye: triggered ({bye})")
            self._log(CLOG, "[FOUND] Idle auto-goodbye triggered (not a fault, ~120s idle).")
            self._log(CLOG, "  Fix: increase close_connection_no_voice_time or disable end_prompt.")
        else:
            self._item(CL, "\u2714", "Auto goodbye: not triggered")

        w_err = sum(1 for l in lines if "get_weather" in l and ("ERROR" in l or "Authentication failed" in l))
        if w_err:
            self._item(CL, "!", "Weather: auth failed")
            self._log(CLOG, "[WARN] Weather plugin key wrong.")
        else:
            self._item(CL, "\u2714", "Weather: OK")

        err_count = sum(1 for l in lines if "-ERROR-" in l or "Traceback" in l)
        if err_count:
            self._item(CL, "!", f"Other errors: {err_count}")
            for el in [l for l in lines if "-ERROR-" in l][-4:]:
                self._log(CLOG, el[:180])
        else:
            self._item(CL, "\u2714", "No other errors")

        # Verdict
        if bye:
            self._verdict(CV, "Main: 'crying then disconnect' = idle auto-goodbye. Increase timeout or disable.", "#d69e14")
        elif llm_key:
            self._verdict(CV, "LLM api_key not configured. Set real keys in Web console.", "#ce3a3a")
        elif llm_run:
            self._verdict(CV, "LLM runtime errors. Check api_key/quota/network.", "#ce3a3a")
        elif tts_err:
            self._verdict(CV, "TTS errors. Check TTS config.", "#ce3a3a")
        elif conn_count == 0:
            self._verdict(CV, "No recent conversations. Check Connection tab.", "#d69e14")
        else:
            self._verdict(CV, "Conversation pipeline looks healthy.", "#22a056")

        msg_queue.put(("progress", 0))
        msg_queue.put(("done",))

    # ========== Devices ==========
    def _worker_devices(self):
        tree = self.dev_tree
        DS = self.dev_status
        msg_queue.put(("progress", "indeterminate"))
        self._verdict(DS, "Scanning...", "#3c424e")
        self.root.after(0, lambda: [tree.delete(i) for i in tree.get_children()])

        lan_ips = get_lan_ips()
        if not lan_ips:
            self._verdict(DS, "No LAN IP found.", "#ce3a3a")
            msg_queue.put(("done",)); return

        base_ip = next((ip for ip in lan_ips if ip.startswith("192.168.")), lan_ips[0])
        prefix = ".".join(base_ip.split(".")[:3])
        self._verdict(DS, f"Pinging {prefix}.1-254...", "#3c424e")

        # DB query for registered devices
        xz_map = {}
        rc, _ = run_cmd("docker info")
        if rc == 0:
            out = docker_exec_sql(
                "SELECT mac_address,IFNULL(alias,''),IFNULL(last_connected_at,''),IFNULL(board,'') FROM ai_device"
            )
            if out:
                for row in out.strip().split("\n"):
                    cols = row.split("\t")
                    if cols and cols[0]:
                        mac = cols[0].replace("-", ":").lower().strip()
                        xz_map[mac] = {
                            "alias": cols[1] if len(cols) > 1 else "",
                            "last": cols[2] if len(cols) > 2 else "",
                            "board": cols[3] if len(cols) > 3 else "",
                        }

        # Ping sweep
        if IS_WIN:
            # Use parallel ping on Windows
            for i in range(1, 255):
                if self.cancel: break
                subprocess.Popen(
                    f"ping -n 1 -w 300 {prefix}.{i}",
                    shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            time.sleep(3)
        else:
            # macOS/Linux
            run_cmd(f"fping -a -g {prefix}.1 {prefix}.254 -t 300 2>/dev/null", timeout=30)
            if self.cancel: msg_queue.put(("done",)); return
            # Fallback: sequential ping
            for i in range(1, 255, 4):
                if self.cancel: break
                for j in range(4):
                    ip = f"{prefix}.{i+j}"
                    if i + j > 254:
                        break
                    subprocess.Popen(
                        ["ping", "-c", "1", "-W", "1", ip],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                time.sleep(0.3)
            time.sleep(2)

        # Read ARP
        ip_mac = {}
        if IS_WIN:
            rc, arp_out = run_cmd("arp -a")
            if arp_out:
                for m in re.finditer(
                    r"(\d+\.\d+\.\d+\.\d+)\s+([\da-fA-F]{2}-[\da-fA-F]{2}-[\da-fA-F]{2}-[\da-fA-F]{2}-[\da-fA-F]{2}-[\da-fA-F]{2})",
                    arp_out
                ):
                    ip, mac = m.group(1), m.group(2).replace("-", ":").lower()
                    if ip.startswith(prefix + "."):
                        ip_mac[ip] = mac
        else:
            rc, arp_out = run_cmd("arp -a")
            if arp_out:
                for m in re.finditer(r"\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:]+)", arp_out):
                    ip, mac = m.group(1), m.group(2).lower()
                    if ip.startswith(prefix + "."):
                        ip_mac[ip] = mac

        # Build rows
        sorted_ips = sorted(ip_mac.keys(), key=lambda x: int(x.split(".")[-1]))
        xz_found = 0
        for ip in sorted_ips:
            mac = ip_mac[ip]
            is_xz = "Yes" if mac in xz_map else "No"
            alias, last, kind = "", "", "Other"
            if mac in xz_map:
                xz_found += 1
                info = xz_map[mac]
                alias = info["alias"] or info["board"]
                last = info["last"]
                kind = "Xiaozhi"
            if ip == base_ip:
                kind = "This PC"
                if is_xz == "No":
                    alias = "(server)"
            tag = "xz" if is_xz == "Yes" else ""
            self.root.after(0, lambda v=(kind, ip, mac, is_xz, alias, last), tg=tag:
                           tree.insert("", "end", values=v, tags=(tg,)))

        # Offline registered
        for mac, info in xz_map.items():
            if mac not in ip_mac.values():
                alias = info["alias"] or info["board"]
                self.root.after(0, lambda v=("Xiaozhi", "(offline)", mac, "Yes", alias, info["last"]):
                               tree.insert("", "end", values=v, tags=("xz",)))

        self.root.after(0, lambda: tree.tag_configure("xz", background="#e1f5e8"))

        total = len(sorted_ips)
        if xz_map:
            self._verdict(DS, f"Done: {total} device(s), {xz_found} Xiaozhi online / {len(xz_map)} registered.", "#22a056")
        else:
            self._verdict(DS, f"Done: {total} device(s). No Xiaozhi registered in DB.", "#d69e14")

        msg_queue.put(("progress", 0))
        msg_queue.put(("done",))


# ==================== Main ====================
if __name__ == "__main__":
    root = tk.Tk()
    app = DiagnosticApp(root)
    root.mainloop()
