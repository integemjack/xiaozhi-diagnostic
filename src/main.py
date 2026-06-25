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
import zipfile

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

XIAOZHI_ZIP_URL = "https://creator.integem.com/wp-content/soft/xiaozhi_v18.zip"
XIAOZHI_ZIP_NAME = "xiaozhi_v18.zip"

IS_MAC = platform.system() == "Darwin"
IS_WIN = platform.system() == "Windows"

msg_queue = queue.Queue()


# ==================== Utility Functions ====================
def run_cmd(cmd, timeout=30):
    """Run a shell command and return (returncode, stdout+stderr combined)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, timeout=timeout,
            encoding="utf-8", errors="replace"
        )
        # Docker logs writes to stderr, so combine both
        output = (r.stdout or "") + (r.stderr or "")
        return r.returncode, output.strip()
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

        self.tab_env = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_env, text="  0. Environment  ")
        self._build_env_tab()

        self.tab_deploy = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_deploy, text="  1. Download & Deploy  ")
        self._build_deploy_tab()

        self.tab_conn = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_conn, text="  2. Connection  ")
        self._build_conn_tab()

        self.tab_chat = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_chat, text="  3. Conversation Health  ")
        self._build_chat_tab()

        self.tab_dev = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_dev, text="  4. Devices  ")
        self._build_dev_tab()

    def _build_env_tab(self):
        """Build the Environment tab with memory usage and process management."""
        bar = ttk.Frame(self.tab_env)
        bar.pack(fill="x", padx=8, pady=6)
        self.btn_env_check = ttk.Button(bar, text="Check Memory",
                                        command=self._start_env_check)
        self.btn_env_check.pack(side="left", padx=4)
        self.btn_kill_proc = ttk.Button(bar, text="Kill Selected Process",
                                        command=self._kill_selected_process)
        self.btn_kill_proc.pack(side="left", padx=4)
        self.btn_env_refresh = ttk.Button(bar, text="Refresh Process List",
                                          command=self._start_env_check)
        self.btn_env_refresh.pack(side="left", padx=4)

        # Search bar
        search_frame = ttk.Frame(self.tab_env)
        search_frame.pack(fill="x", padx=8, pady=2)
        ttk.Label(search_frame, text="Filter:").pack(side="left", padx=4)
        self.env_search_var = tk.StringVar()
        self.env_search_var.trace_add("write", self._filter_process_list)
        self.env_search_entry = ttk.Entry(search_frame, textvariable=self.env_search_var, width=30)
        self.env_search_entry.pack(side="left", padx=4)

        # Memory summary label
        self.env_mem_label = tk.Label(self.tab_env, text="  Click [Check Memory] to view system memory and process info",
                                     bg="#3c424e", fg="white", anchor="w",
                                     font=("Helvetica", 11, "bold"), padx=14, pady=8)
        self.env_mem_label.pack(fill="x", padx=8, pady=4)

        # Process list treeview
        proc_frame = ttk.Frame(self.tab_env)
        proc_frame.pack(fill="both", expand=True, padx=8, pady=4)

        cols = ("PID", "Name", "Memory (MB)", "CPU %", "Status")
        self.proc_tree = ttk.Treeview(proc_frame, columns=cols, show="headings", height=18)
        for c in cols:
            self.proc_tree.heading(c, text=c, command=lambda col=c: self._sort_proc_tree(col))
            self.proc_tree.column(c, width=120)
        self.proc_tree.column("PID", width=70)
        self.proc_tree.column("Name", width=250)
        self.proc_tree.column("Memory (MB)", width=120)
        self.proc_tree.column("CPU %", width=80)
        self.proc_tree.column("Status", width=100)

        # Scrollbar
        proc_scroll = ttk.Scrollbar(proc_frame, orient="vertical", command=self.proc_tree.yview)
        self.proc_tree.configure(yscrollcommand=proc_scroll.set)
        self.proc_tree.pack(side="left", fill="both", expand=True)
        proc_scroll.pack(side="right", fill="y")

        # Store process data for filtering/sorting
        self._proc_data = []
        self._proc_sort_col = "Memory (MB)"
        self._proc_sort_reverse = True

    def _start_env_check(self):
        """Start environment check in a background thread."""
        self._start_worker(self._worker_env)

    def _worker_env(self):
        """Worker thread: collect memory and process information."""
        msg_queue.put(("progress", "indeterminate"))
        self._verdict(self.env_mem_label, "Collecting system information...", "#3c424e")

        # Get system memory info
        mem_info = self._get_system_memory()
        if mem_info:
            total_gb = mem_info["total"] / (1024 ** 3)
            used_gb = mem_info["used"] / (1024 ** 3)
            free_gb = mem_info["free"] / (1024 ** 3)
            pct = (mem_info["used"] / mem_info["total"]) * 100 if mem_info["total"] else 0
            if pct > 90:
                color = "#ce3a3a"
            elif pct > 70:
                color = "#d69e14"
            else:
                color = "#22a056"
            mem_text = (f"Memory: {used_gb:.1f} GB / {total_gb:.1f} GB used ({pct:.0f}%)  |  "
                        f"Free: {free_gb:.1f} GB")
            self._verdict(self.env_mem_label, mem_text, color)
        else:
            self._verdict(self.env_mem_label, "Failed to get memory info", "#ce3a3a")

        # Get process list
        proc_list = self._get_process_list()
        self._proc_data = proc_list

        # Update tree on main thread
        self.root.after(0, self._populate_proc_tree)

        msg_queue.put(("progress", 0))
        msg_queue.put(("done",))

    def _get_system_memory(self):
        """Get system memory usage (cross-platform)."""
        try:
            if IS_WIN:
                rc, out = run_cmd(
                    'powershell -Command "Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize,FreePhysicalMemory | Format-List"',
                    timeout=15
                )
                total = free = 0
                for line in out.split("\n"):
                    line = line.strip()
                    if "TotalVisibleMemorySize" in line and ":" in line:
                        val = line.split(":")[-1].strip()
                        if val.isdigit():
                            total = int(val) * 1024  # KB to bytes
                    elif "FreePhysicalMemory" in line and ":" in line:
                        val = line.split(":")[-1].strip()
                        if val.isdigit():
                            free = int(val) * 1024
                if total:
                    return {"total": total, "used": total - free, "free": free}
            else:
                # macOS / Linux
                if IS_MAC:
                    rc, out = run_cmd("sysctl -n hw.memsize", timeout=5)
                    total = int(out.strip()) if rc == 0 and out.strip() else 0
                    rc2, vm_out = run_cmd("vm_stat", timeout=5)
                    free = 0
                    if rc2 == 0:
                        page_size = 4096
                        for m in re.finditer(r"Pages free:\s+(\d+)", vm_out):
                            free += int(m.group(1)) * page_size
                        for m in re.finditer(r"Pages inactive:\s+(\d+)", vm_out):
                            free += int(m.group(1)) * page_size
                    if total:
                        return {"total": total, "used": total - free, "free": free}
                else:
                    rc, out = run_cmd("cat /proc/meminfo", timeout=5)
                    total = free = available = 0
                    for line in out.split("\n"):
                        if line.startswith("MemTotal:"):
                            total = int(re.search(r"\d+", line).group()) * 1024
                        elif line.startswith("MemAvailable:"):
                            available = int(re.search(r"\d+", line).group()) * 1024
                    if total:
                        return {"total": total, "used": total - available, "free": available}
        except Exception:
            pass
        return None

    def _get_process_list(self):
        """Get list of all processes with memory usage (cross-platform)."""
        processes = []
        try:
            if IS_WIN:
                # Use tasklist for process info
                rc, out = run_cmd(
                    'tasklist /FO CSV /NH',
                    timeout=15
                )
                if rc == 0 and out:
                    for line in out.strip().split("\n"):
                        line = line.strip()
                        if not line:
                            continue
                        # Parse CSV: "name","pid","session","session#","mem"
                        parts = line.split('","')
                        if len(parts) >= 5:
                            name = parts[0].strip('"')
                            try:
                                pid = int(parts[1].strip('"'))
                            except ValueError:
                                continue
                            # Memory is like "12,345 K"
                            mem_str = parts[4].strip('"').replace(",", "").replace(" K", "").replace(" k", "")
                            try:
                                mem_kb = int(mem_str)
                                mem_mb = mem_kb / 1024.0
                            except ValueError:
                                mem_mb = 0.0
                            processes.append({
                                "pid": pid,
                                "name": name,
                                "mem_mb": round(mem_mb, 1),
                                "cpu": "-",
                                "status": "Running"
                            })
            else:
                # macOS / Linux: use ps
                rc, out = run_cmd("ps aux --sort=-%mem", timeout=15)
                if rc != 0:
                    rc, out = run_cmd("ps aux", timeout=15)
                if rc == 0 and out:
                    lines = out.strip().split("\n")
                    for line in lines[1:]:  # Skip header
                        parts = line.split(None, 10)
                        if len(parts) >= 11:
                            try:
                                pid = int(parts[1])
                                cpu = parts[2]
                                mem_pct = parts[3]
                                # VSZ is in KB (column 4)
                                rss_kb = int(parts[5])
                                mem_mb = rss_kb / 1024.0
                                status = parts[7]
                                name = parts[10]
                            except (ValueError, IndexError):
                                continue
                            processes.append({
                                "pid": pid,
                                "name": name[:60],
                                "mem_mb": round(mem_mb, 1),
                                "cpu": cpu,
                                "status": status
                            })
        except Exception:
            pass

        # Sort by memory descending
        processes.sort(key=lambda x: x["mem_mb"], reverse=True)
        return processes

    def _populate_proc_tree(self):
        """Populate the process treeview with current data (applies filter)."""
        for item in self.proc_tree.get_children():
            self.proc_tree.delete(item)

        filter_text = self.env_search_var.get().lower()
        for proc in self._proc_data:
            if filter_text and filter_text not in proc["name"].lower() and filter_text not in str(proc["pid"]):
                continue
            self.proc_tree.insert("", "end", values=(
                proc["pid"],
                proc["name"],
                f"{proc['mem_mb']:.1f}",
                proc["cpu"],
                proc["status"]
            ))

    def _filter_process_list(self, *args):
        """Re-filter process list when search text changes."""
        self._populate_proc_tree()

    def _sort_proc_tree(self, col):
        """Sort the process tree by the clicked column."""
        if self._proc_sort_col == col:
            self._proc_sort_reverse = not self._proc_sort_reverse
        else:
            self._proc_sort_col = col
            self._proc_sort_reverse = True

        key_map = {
            "PID": lambda x: x["pid"],
            "Name": lambda x: x["name"].lower(),
            "Memory (MB)": lambda x: x["mem_mb"],
            "CPU %": lambda x: float(x["cpu"]) if x["cpu"] != "-" else 0,
            "Status": lambda x: x["status"],
        }
        key_fn = key_map.get(col, lambda x: x["name"].lower())
        try:
            self._proc_data.sort(key=key_fn, reverse=self._proc_sort_reverse)
        except (ValueError, TypeError):
            pass
        self._populate_proc_tree()

    def _kill_selected_process(self):
        """Kill the selected process in the process list."""
        selected = self.proc_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select a process to kill.")
            return

        item = self.proc_tree.item(selected[0])
        values = item["values"]
        pid = values[0]
        name = values[1]

        confirm = messagebox.askyesno(
            "Confirm Kill Process",
            f"Are you sure you want to kill the process?\n\n"
            f"PID: {pid}\nName: {name}\n\n"
            f"Warning: Killing system processes may cause instability."
        )
        if not confirm:
            return

        try:
            if IS_WIN:
                rc, out = run_cmd(f"taskkill /PID {pid} /F", timeout=10)
            else:
                rc, out = run_cmd(f"kill -9 {pid}", timeout=10)

            if rc == 0:
                messagebox.showinfo("Success", f"Process {name} (PID: {pid}) has been terminated.")
                # Refresh the list
                self._start_env_check()
            else:
                messagebox.showerror("Failed", f"Failed to kill process {name} (PID: {pid}).\n\n{out}")
        except Exception as e:
            messagebox.showerror("Error", f"Error killing process: {str(e)}")

    def _build_deploy_tab(self):
        """Build the Download & Deploy tab."""
        bar = ttk.Frame(self.tab_deploy)
        bar.pack(fill="x", padx=8, pady=6)
        self.btn_one_click_start = ttk.Button(bar, text="One-Click Start",
                                              command=self._start_one_click)
        self.btn_one_click_start.pack(side="left", padx=4)
        self.btn_change_ip = ttk.Button(bar, text="Change Server IP",
                                        command=self._start_change_ip)
        self.btn_change_ip.pack(side="left", padx=4)
        self.btn_redownload = ttk.Button(bar, text="Re-download",
                                         command=self._start_redownload)
        self.btn_redownload.pack(side="left", padx=4)
        self.btn_stop_containers = ttk.Button(bar, text="Stop Containers",
                                              command=self._start_stop_containers)
        self.btn_stop_containers.pack(side="left", padx=4)
        self.btn_open_admin = ttk.Button(bar, text="Open Admin Panel",
                                         command=self._open_admin_panel)
        self.btn_open_admin.pack(side="left", padx=4)

        pane = ttk.PanedWindow(self.tab_deploy, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8, pady=4)
        self.deploy_list = scrolledtext.ScrolledText(pane, width=48, height=20,
                                                     state="disabled", wrap="word")
        pane.add(self.deploy_list, weight=1)
        self.deploy_log = scrolledtext.ScrolledText(pane, width=48, height=20,
                                                    bg="#1e2230", fg="#dce0e6",
                                                    state="disabled", wrap="word",
                                                    font=("Consolas", 9))
        pane.add(self.deploy_log, weight=1)

        self.deploy_verdict = tk.Label(self.tab_deploy,
                                       text="  Click [One-Click Start] to download, deploy, and configure",
                                       bg="#3c424e", fg="white", anchor="w",
                                       font=("Helvetica", 12, "bold"), padx=14, pady=10)
        self.deploy_verdict.pack(fill="x", side="bottom")

    def _start_stop_containers(self):
        """Stop all Docker containers."""
        self._start_worker(self._worker_stop_containers)

    def _worker_stop_containers(self):
        """Worker thread: stop all xiaozhi Docker containers."""
        L, LOG, V = self.deploy_list, self.deploy_log, self.deploy_verdict
        msg_queue.put(("clear", L)); msg_queue.put(("clear", LOG))
        msg_queue.put(("progress", "indeterminate"))
        self._verdict(V, "Stopping Docker containers...", "#3c424e")
        self._log(LOG, "===== Stopping Containers =====")

        rc, _ = run_cmd("docker info", timeout=10)
        if rc != 0:
            self._item(L, "\u2718", "Docker is not running")
            self._verdict(V, "Docker is not running.", "#d69e14")
            msg_queue.put(("progress", 0))
            msg_queue.put(("done",))
            return

        compose_file = self._find_compose_file()
        if os.path.exists(compose_file):
            rc_test, _ = run_cmd("docker compose version", timeout=10)
            if rc_test == 0:
                down_cmd = f'docker compose -p xiaozhi -f "{compose_file}" down'
            else:
                down_cmd = f'docker-compose -p xiaozhi -f "{compose_file}" down'

            self._item(L, "\u2022", "Running docker compose down...")
            self._log(LOG, f"Running: {down_cmd}")
            rc, out = run_cmd(down_cmd, timeout=60)
            if out:
                for line in out.split("\n")[-10:]:
                    self._log(LOG, line)

            if rc == 0:
                self._item(L, "\u2714", "All containers stopped and removed")
                self._verdict(V, "All containers stopped.", "#22a056")
            else:
                self._item(L, "!", "docker compose down had issues")
                self._log(LOG, f"[WARN] Exit code: {rc}")
                self._verdict(V, "Containers may not have stopped cleanly.", "#d69e14")
        else:
            self._item(L, "\u2718", "No docker-compose file found")
            self._verdict(V, "No compose file found.", "#ce3a3a")

        msg_queue.put(("progress", 0))
        msg_queue.put(("done",))

    def _open_admin_panel(self):
        """Open the admin management panel in browser using the configured server IP."""
        import webbrowser

        # Try to get the current server IP
        server_ip = None

        # First try from .last_ip file
        last_ip_path = os.path.join(SCRIPT_DIR, ".last_ip")
        if os.path.exists(last_ip_path):
            try:
                with open(last_ip_path) as f:
                    ip = f.read().strip()
                if re.match(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", ip):
                    server_ip = ip
            except Exception:
                pass

        # Fallback: try from database
        if not server_ip:
            try:
                server_ip = self._get_current_ip_from_db()
            except Exception:
                pass

        # Fallback: use localhost
        if not server_ip:
            server_ip = "localhost"

        url = f"http://{server_ip}:{WEB_PORT}/#/params-management"
        webbrowser.open(url)

    def _start_one_click(self):
        """One-click: download + docker start + change IP."""
        self._force_redownload = False
        self._start_worker(self._worker_one_click)

    def _start_redownload(self):
        """Force re-download then full start."""
        self._force_redownload = True
        self._start_worker(self._worker_one_click)

    def _worker_one_click(self):
        """One-click worker: download → start Docker → start services → change IP."""
        L, LOG, V = self.deploy_list, self.deploy_log, self.deploy_verdict
        msg_queue.put(("clear", L)); msg_queue.put(("clear", LOG))
        msg_queue.put(("progress", "indeterminate"))
        self._verdict(V, "Starting one-click deployment...", "#3c424e")
        self._log(LOG, "========== One-Click Start ==========")
        self._log(LOG, "")

        target_dir = SCRIPT_DIR
        zip_path = os.path.join(target_dir, XIAOZHI_ZIP_NAME)
        force = getattr(self, '_force_redownload', False)

        # If re-download, stop existing containers first
        if force:
            self._log(LOG, "===== Stopping existing containers =====")
            self._item(L, "\u2022", "Stopping existing Docker containers...")
            self._verdict(V, "Stopping existing containers...", "#3c424e")

            rc, _ = run_cmd("docker info", timeout=10)
            if rc == 0:
                compose_file = self._find_compose_file()
                if os.path.exists(compose_file):
                    # Try docker compose down to stop and remove containers
                    rc_test, _ = run_cmd("docker compose version", timeout=10)
                    if rc_test == 0:
                        down_cmd = f'docker compose -p xiaozhi -f "{compose_file}" down'
                    else:
                        down_cmd = f'docker-compose -p xiaozhi -f "{compose_file}" down'
                    self._log(LOG, f"Running: {down_cmd}")
                    rc, out = run_cmd(down_cmd, timeout=60)
                    if rc == 0:
                        self._item(L, "\u2714", "Containers stopped and removed")
                        self._log(LOG, "[OK] Containers stopped")
                    else:
                        self._log(LOG, f"[WARN] docker compose down: {out[:200]}")
                        self._item(L, "!", "Some containers may still be running")
                else:
                    self._log(LOG, "[INFO] No compose file found, skipping stop")
            else:
                self._log(LOG, "[INFO] Docker not running, nothing to stop")
            self._log(LOG, "")

        # ===== Phase 1: Download & Extract =====
        self._log(LOG, "===== Phase 1: Download & Extract =====")
        self._item(L, "\u2022", "Phase 1: Checking package...")

        if os.path.exists(zip_path) and not force:
            self._item(L, "\u2714", f"{XIAOZHI_ZIP_NAME} exists, skipping download")
            self._log(LOG, f"[INFO] File exists: {zip_path} ({os.path.getsize(zip_path) // (1024*1024)} MB)")
        else:
            if force and os.path.exists(zip_path):
                os.remove(zip_path)
                self._item(L, "\u2022", "Re-downloading...")
            self._verdict(V, "Phase 1: Downloading package...", "#3c424e")
            if not self._do_download(zip_path, L, LOG, V):
                msg_queue.put(("progress", 0))
                msg_queue.put(("done",))
                return

        # Verify and extract
        self._verdict(V, "Phase 1: Extracting...", "#3c424e")
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                bad_file = zf.testzip()
                if bad_file:
                    raise zipfile.BadZipFile(f"Corrupt file: {bad_file}")
                self._safe_extract(zf, target_dir, LOG)
            self._item(L, "\u2714", "Package extracted")
            self._log(LOG, "[OK] Extraction complete")

            if IS_MAC:
                for root_dir, dirs, files in os.walk(target_dir):
                    for fname in files:
                        if fname.endswith(('.sh', '.command', '.py')):
                            try:
                                os.chmod(os.path.join(root_dir, fname), 0o755)
                            except OSError:
                                pass
                self._log(LOG, "[OK] macOS permissions fixed")

        except zipfile.BadZipFile as e:
            self._item(L, "!", f"Zip corrupt, re-downloading...")
            self._log(LOG, f"[WARN] {str(e)}, re-downloading...")
            try:
                os.remove(zip_path)
            except OSError:
                pass
            if not self._do_download(zip_path, L, LOG, V):
                msg_queue.put(("progress", 0))
                msg_queue.put(("done",))
                return
            try:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    self._safe_extract(zf, target_dir, LOG)
                self._item(L, "\u2714", "Re-download and extract OK")
            except Exception as e2:
                self._item(L, "\u2718", f"Extract failed: {str(e2)}")
                self._verdict(V, f"Extract failed: {str(e2)}", "#ce3a3a")
                msg_queue.put(("progress", 0))
                msg_queue.put(("done",))
                return
        except Exception as e:
            self._item(L, "\u2718", f"Extract error: {str(e)}")
            self._verdict(V, f"Extract error: {str(e)}", "#ce3a3a")
            msg_queue.put(("progress", 0))
            msg_queue.put(("done",))
            return

        if self.cancel:
            msg_queue.put(("progress", 0)); msg_queue.put(("done",)); return

        # ===== Phase 2: Docker =====
        self._log(LOG, "")
        self._log(LOG, "===== Phase 2: Docker Engine =====")
        self._item(L, "\u2022", "Phase 2: Checking Docker...")
        self._verdict(V, "Phase 2: Checking Docker...", "#3c424e")

        # Check if Docker is installed
        docker_installed = self._check_docker_installed(L, LOG)
        if not docker_installed:
            self._item(L, "\u2718", "Docker not installed, attempting install...")
            install_ok = self._install_docker(L, LOG, V)
            if not install_ok:
                self._verdict(V, "Docker installation failed.", "#ce3a3a")
                msg_queue.put(("progress", 0))
                msg_queue.put(("done",))
                return

        # Check if Docker is running
        rc, _ = run_cmd("docker info", timeout=15)
        if rc != 0:
            self._item(L, "\u2022", "Starting Docker Desktop...")
            started = self._launch_docker_desktop(L, LOG)
            if started:
                self._verdict(V, "Phase 2: Waiting for Docker to start...", "#3c424e")
                docker_ready = False
                for i in range(60):
                    if self.cancel:
                        msg_queue.put(("progress", 0)); msg_queue.put(("done",)); return
                    time.sleep(2)
                    rc2, _ = run_cmd("docker info", timeout=5)
                    if rc2 == 0:
                        docker_ready = True
                        break
                    self._verdict(V, f"Phase 2: Waiting for Docker... ({(i+1)*2}s)", "#3c424e")
                if not docker_ready:
                    self._item(L, "\u2718", "Docker failed to start")
                    self._verdict(V, "Docker failed to start.", "#ce3a3a")
                    msg_queue.put(("progress", 0))
                    msg_queue.put(("done",))
                    return
            else:
                self._verdict(V, "Could not start Docker.", "#ce3a3a")
                msg_queue.put(("progress", 0))
                msg_queue.put(("done",))
                return

        self._item(L, "\u2714", "Docker is running")
        self._log(LOG, "[OK] Docker engine ready")

        if self.cancel:
            msg_queue.put(("progress", 0)); msg_queue.put(("done",)); return

        # ===== Phase 3: Start Services =====
        self._log(LOG, "")
        self._log(LOG, "===== Phase 3: Start Services =====")
        self._item(L, "\u2022", "Phase 3: Starting services...")
        self._verdict(V, "Phase 3: Starting Docker services...", "#3c424e")

        compose_file = self._find_compose_file()
        if not os.path.exists(compose_file):
            self._item(L, "\u2718", "docker-compose file not found")
            self._verdict(V, "No docker-compose file found.", "#ce3a3a")
            msg_queue.put(("progress", 0))
            msg_queue.put(("done",))
            return

        # Determine compose command
        compose_cmd = None
        rc_test, _ = run_cmd("docker compose version", timeout=10)
        if rc_test == 0:
            compose_cmd = f'docker compose -p xiaozhi -f "{compose_file}" up -d'
        else:
            rc_test2, _ = run_cmd("docker-compose version", timeout=10)
            if rc_test2 == 0:
                compose_cmd = f'docker-compose -p xiaozhi -f "{compose_file}" up -d'

        if not compose_cmd:
            self._item(L, "\u2718", "Docker Compose not found")
            self._verdict(V, "Docker Compose not available.", "#ce3a3a")
            msg_queue.put(("progress", 0))
            msg_queue.put(("done",))
            return

        self._log(LOG, f"Running: {compose_cmd}")
        rc, out = run_cmd(compose_cmd, timeout=1800)
        if out:
            for line in out.split("\n")[-15:]:
                self._log(LOG, line)

        if rc != 0:
            self._item(L, "\u2718", "docker compose up failed")
            self._verdict(V, "Docker compose up failed.", "#ce3a3a")
            msg_queue.put(("progress", 0))
            msg_queue.put(("done",))
            return

        self._item(L, "\u2714", "Docker compose up completed")

        # Wait for containers to be ready
        self._item(L, "\u2022", "Waiting for all services to be ready...")
        self._verdict(V, "Phase 3: Waiting for containers...", "#3c424e")
        max_wait = 300
        check_interval = 5
        elapsed = 0

        while elapsed < max_wait:
            if self.cancel:
                msg_queue.put(("progress", 0)); msg_queue.put(("done",)); return
            time.sleep(check_interval)
            elapsed += check_interval

            fmt = "{{.Names}}|{{.Status}}"
            if IS_WIN:
                rc, ps_out = run_cmd(f'docker ps --format "{fmt}"', timeout=10)
            else:
                rc, ps_out = run_cmd(f"docker ps --format '{fmt}'", timeout=10)

            running_containers = {}
            if ps_out:
                for line in ps_out.strip().split("\n"):
                    line = line.strip().strip("'").strip('"')
                    if "|" in line:
                        name, status = line.split("|", 1)
                        running_containers[name.strip()] = status.strip()

            running_count = sum(1 for c in CONTAINERS if c in running_containers)
            total_count = len(CONTAINERS)

            all_healthy = True
            for c in CONTAINERS:
                if c in running_containers:
                    if "health: starting" in running_containers[c].lower():
                        all_healthy = False
                else:
                    all_healthy = False

            self._verdict(V, f"Phase 3: {running_count}/{total_count} containers ({elapsed}s)", "#3c424e")

            if running_count == total_count and all_healthy:
                break
        else:
            self._log(LOG, f"[WARN] Timeout after {max_wait}s")

        self._item(L, "\u2714", "Services are running")
        self._log(LOG, "[OK] All containers ready")

        if self.cancel:
            msg_queue.put(("progress", 0)); msg_queue.put(("done",)); return

        # ===== Phase 4: Configure Server IP =====
        self._log(LOG, "")
        self._log(LOG, "===== Phase 4: Configure Server IP =====")
        self._item(L, "\u2022", "Phase 4: Configuring server IP...")
        self._verdict(V, "Phase 4: Configuring server IP...", "#3c424e")

        # Get current IP from DB
        current_ip = self._get_current_ip_from_db()
        if current_ip:
            self._log(LOG, f"Current IP in database: {current_ip}")
        else:
            self._log(LOG, "[INFO] No IP found in database (first run)")
            current_ip = ""

        # Detect LAN IPs
        lan_ips = get_lan_ips()
        if not lan_ips:
            self._item(L, "!", "No LAN IP detected, skipping IP config")
            self._log(LOG, "[WARN] No LAN IP, skipping")
        else:
            self._log(LOG, f"Detected LAN IPs: {', '.join(lan_ips)}")

            # Always let user confirm/select IP
            if len(lan_ips) == 1:
                # Only one IP, auto-use it but still inform user
                new_ip = lan_ips[0]
                self._item(L, "\u2714", f"Detected IP: {new_ip}")
                self._log(LOG, f"Only one IP detected, using: {new_ip}")
            else:
                # Multiple IPs, user must select
                self._item(L, "\u2022", "Multiple IPs detected, please select...")
                new_ip = self._ask_user_select_ip(lan_ips, current_ip)
                if not new_ip:
                    # User cancelled, pick first 192.168.x.x or first available
                    new_ip = next((ip for ip in lan_ips if ip.startswith("192.168.")), lan_ips[0])
                    self._log(LOG, f"Auto-selected: {new_ip}")

            # Apply IP change if needed
            if current_ip and current_ip == new_ip:
                self._item(L, "\u2714", f"IP already correct: {new_ip}")
                self._log(LOG, "IP unchanged, refreshing Redis cache...")
                run_cmd("docker exec xiaozhi-esp32-server-redis redis-cli FLUSHALL", timeout=10)
            else:
                self._item(L, "\u2022", f"Setting IP: {current_ip or '(default)'} → {new_ip}")
                old_ip = current_ip if current_ip else "192.168.20.42"
                sql_update = (
                    f"UPDATE sys_params SET param_value = REPLACE(param_value, '{old_ip}', '{new_ip}') "
                    f"WHERE param_value LIKE '%{old_ip}%'; "
                    f"UPDATE ai_model_config SET config_json = REPLACE(config_json, '{old_ip}', '{new_ip}') "
                    f"WHERE config_json LIKE '%{old_ip}%';"
                )
                cmd = f'docker exec {DB_CONTAINER} mysql -u{DB_USER} -p{DB_PASS} {DB_NAME} -e "{sql_update}"'
                rc, out = run_cmd(cmd, timeout=30)
                if rc == 0:
                    self._item(L, "\u2714", f"IP updated to {new_ip}")
                    self._log(LOG, "[OK] Database IP updated")
                else:
                    self._item(L, "\u2718", f"IP update failed: {out[:100]}")
                    self._log(LOG, f"[FAIL] {out}")

                # Flush Redis
                run_cmd("docker exec xiaozhi-esp32-server-redis redis-cli FLUSHALL", timeout=10)
                self._log(LOG, "[OK] Redis cache cleared")

                # Save .last_ip
                try:
                    with open(os.path.join(SCRIPT_DIR, ".last_ip"), "w") as f:
                        f.write(new_ip)
                except Exception:
                    pass

                # Restart services to apply new IP
                self._item(L, "\u2022", "Restarting services to apply IP...")
                self._verdict(V, "Restarting services...", "#3c424e")
                restart_cmd = f'docker compose -p xiaozhi -f "{compose_file}" restart'
                run_cmd(restart_cmd, timeout=120)
                time.sleep(10)
                self._item(L, "\u2714", "Services restarted")

            # Show final OTA address
            ota_addr = f"http://{new_ip}:{WEB_PORT}/xiaozhi/ota/"
            self._item(L, "\u2714", f"Device OTA: {ota_addr}")
            self._log(LOG, "")
            self._log(LOG, f"Device OTA address: {ota_addr}")
            self._log(LOG, "  (trailing slash '/' is REQUIRED)")

        if self.cancel:
            msg_queue.put(("progress", 0)); msg_queue.put(("done",)); return

        # ===== Phase 5: Final Status Check =====
        self._log(LOG, "")
        self._log(LOG, "===== Phase 5: Final Status Check =====")
        self._item(L, "\u2022", "Phase 5: Verifying all services...")
        self._verdict(V, "Phase 5: Final verification...", "#3c424e")

        # Wait a moment for services to stabilize after restart
        time.sleep(5)

        self._verify_docker_services(L, LOG, V)

        # Override verdict with full OTA info if all OK
        fmt = "{{.Names}}"
        if IS_WIN:
            rc, out = run_cmd(f'docker ps --format "{fmt}"', timeout=10)
        else:
            rc, out = run_cmd(f"docker ps --format '{fmt}'", timeout=10)
        running = [x.strip().strip("'").strip('"') for x in (out or "").split("\n") if x.strip()]
        all_running = all(c in running for c in CONTAINERS)

        # ===== Done =====
        self._log(LOG, "")
        self._log(LOG, "========== One-Click Start Complete ==========")
        ota_display = f"http://{new_ip}:{WEB_PORT}/xiaozhi/ota/" if lan_ips else ""
        if all_running:
            self._verdict(V, f"All done! All services running. OTA: {ota_display}", "#22a056")
        else:
            self._verdict(V, f"Done, but some services have issues. OTA: {ota_display}", "#d69e14")

        msg_queue.put(("progress", 0))
        msg_queue.put(("done",))

    def _ask_user_select_ip(self, lan_ips, current_ip):
        """Show dialog for user to select IP. Returns selected IP or None."""
        selected_ip = [None]
        dialog_done = [False]

        def show_dialog():
            dialog = tk.Toplevel(self.root)
            dialog.title("Select Server IP")
            dialog.geometry("400x300")
            dialog.transient(self.root)
            dialog.grab_set()

            tk.Label(dialog, text="Multiple network IPs detected.",
                     font=("Helvetica", 10)).pack(padx=10, pady=(10, 0), anchor="w")
            if current_ip:
                tk.Label(dialog, text=f"Current: {current_ip}",
                         font=("Consolas", 10), fg="#2266aa").pack(padx=10, pady=(0, 5), anchor="w")

            tk.Label(dialog, text="Select the IP for your Xiaozhi server:",
                     font=("Helvetica", 10)).pack(padx=10, pady=(5, 5), anchor="w")

            listbox = tk.Listbox(dialog, font=("Consolas", 12), height=6)
            listbox.pack(fill="both", expand=True, padx=10, pady=5)
            for ip in lan_ips:
                display = f"{ip}  ← current" if ip == current_ip else ip
                listbox.insert("end", display)

            if current_ip in lan_ips:
                listbox.selection_set(lan_ips.index(current_ip))
            else:
                listbox.selection_set(0)

            def on_confirm():
                sel = listbox.curselection()
                if sel:
                    selected_ip[0] = lan_ips[sel[0]]
                dialog.destroy()
                dialog_done[0] = True

            def on_cancel():
                dialog.destroy()
                dialog_done[0] = True

            btn_frame = ttk.Frame(dialog)
            btn_frame.pack(fill="x", padx=10, pady=10)
            ttk.Button(btn_frame, text="Confirm", command=on_confirm).pack(side="left", padx=5)
            ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side="left", padx=5)
            dialog.protocol("WM_DELETE_WINDOW", on_cancel)

        self.root.after(0, show_dialog)
        while not dialog_done[0]:
            if self.cancel:
                return None
            time.sleep(0.1)
        return selected_ip[0]

    def _start_docker_services(self):
        """Start docker services in background thread."""
        self._start_worker(self._worker_docker_start)

    def _start_docker_check(self):
        """Check docker status in background thread."""
        self._start_worker(self._worker_docker_check)

    def _start_change_ip(self):
        """Start the change IP workflow."""
        self._start_worker(self._worker_change_ip)

    def _worker_change_ip(self):
        """Worker thread: detect LAN IPs, let user pick one, update database."""
        L, LOG, V = self.deploy_list, self.deploy_log, self.deploy_verdict
        msg_queue.put(("clear", L)); msg_queue.put(("clear", LOG))
        msg_queue.put(("progress", "indeterminate"))
        self._verdict(V, "Preparing to change server IP...", "#3c424e")
        self._log(LOG, "===== Change Server IP =====")

        # Check Docker is running
        rc, _ = run_cmd("docker info", timeout=10)
        if rc != 0:
            self._item(L, "\u2718", "Docker is not running")
            self._verdict(V, "Docker must be running to change IP.", "#ce3a3a")
            msg_queue.put(("progress", 0))
            msg_queue.put(("done",))
            return

        # Check DB container is running
        fmt = "{{.Names}}"
        if IS_WIN:
            rc, out = run_cmd(f'docker ps --format "{fmt}"', timeout=10)
        else:
            rc, out = run_cmd(f"docker ps --format '{fmt}'", timeout=10)
        running = [x.strip().strip("'").strip('"') for x in (out or "").split("\n") if x.strip()]
        if DB_CONTAINER not in running:
            self._item(L, "\u2718", f"{DB_CONTAINER} is not running")
            self._verdict(V, "Database container must be running to change IP.", "#ce3a3a")
            msg_queue.put(("progress", 0))
            msg_queue.put(("done",))
            return

        # Get current IP from database
        self._item(L, "\u2022", "Reading current IP from database...")
        current_ip = self._get_current_ip_from_db()
        if current_ip:
            self._item(L, "\u2714", f"Current IP in database: {current_ip}")
            self._log(LOG, f"Current IP: {current_ip}")
        else:
            self._item(L, "!", "Could not read current IP from database (may be first run)")
            self._log(LOG, "[INFO] No IP found in database, will set fresh")
            current_ip = ""

        # Detect LAN IPs
        self._item(L, "\u2022", "Detecting LAN IP addresses...")
        lan_ips = get_lan_ips()
        if not lan_ips:
            self._item(L, "\u2718", "No LAN IP detected")
            self._verdict(V, "No LAN IP address found on this machine.", "#ce3a3a")
            msg_queue.put(("progress", 0))
            msg_queue.put(("done",))
            return

        for ip in lan_ips:
            marker = " (current)" if ip == current_ip else ""
            self._item(L, "\u2022", f"  {ip}{marker}")
        self._log(LOG, f"Detected IPs: {', '.join(lan_ips)}")

        # If current IP is already one of the LAN IPs, note that
        if current_ip in lan_ips:
            self._item(L, "\u2714", f"Current IP {current_ip} matches this machine")

        # Ask user to select IP via dialog
        self._verdict(V, "Please select the new server IP...", "#3c424e")
        msg_queue.put(("progress", 0))

        selected_ip = [None]
        dialog_done = [False]

        def show_ip_dialog():
            dialog = tk.Toplevel(self.root)
            dialog.title("Select Server IP")
            dialog.geometry("400x300")
            dialog.transient(self.root)
            dialog.grab_set()

            tk.Label(dialog, text="Current IP in database:",
                     font=("Helvetica", 10)).pack(padx=10, pady=(10, 0), anchor="w")
            tk.Label(dialog, text=f"  {current_ip if current_ip else '(not set)'}",
                     font=("Consolas", 11, "bold"), fg="#2266aa").pack(padx=10, pady=(0, 10), anchor="w")

            tk.Label(dialog, text="Select new server IP:",
                     font=("Helvetica", 10)).pack(padx=10, pady=(5, 5), anchor="w")

            listbox = tk.Listbox(dialog, font=("Consolas", 12), height=6)
            listbox.pack(fill="both", expand=True, padx=10, pady=5)
            for ip in lan_ips:
                display = f"{ip}  ← current" if ip == current_ip else ip
                listbox.insert("end", display)

            # Pre-select the current IP or first one
            if current_ip in lan_ips:
                listbox.selection_set(lan_ips.index(current_ip))
            else:
                listbox.selection_set(0)

            def on_confirm():
                sel = listbox.curselection()
                if sel:
                    selected_ip[0] = lan_ips[sel[0]]
                dialog.destroy()
                dialog_done[0] = True

            def on_cancel():
                dialog.destroy()
                dialog_done[0] = True

            btn_frame = ttk.Frame(dialog)
            btn_frame.pack(fill="x", padx=10, pady=10)
            ttk.Button(btn_frame, text="Confirm", command=on_confirm).pack(side="left", padx=5)
            ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side="left", padx=5)

            dialog.protocol("WM_DELETE_WINDOW", on_cancel)

        self.root.after(0, show_ip_dialog)

        # Wait for dialog
        while not dialog_done[0]:
            if self.cancel:
                msg_queue.put(("done",))
                return
            time.sleep(0.1)

        if not selected_ip[0]:
            self._item(L, "!", "IP change cancelled")
            self._verdict(V, "IP change cancelled by user.", "#3c424e")
            msg_queue.put(("done",))
            return

        new_ip = selected_ip[0]
        self._item(L, "\u2022", f"Selected new IP: {new_ip}")
        self._log(LOG, f"New IP selected: {new_ip}")

        if current_ip and current_ip == new_ip:
            # Same IP, just refresh Redis
            self._item(L, "\u2022", "IP unchanged, refreshing Redis cache...")
            run_cmd("docker exec xiaozhi-esp32-server-redis redis-cli FLUSHALL", timeout=10)
            self._item(L, "\u2714", "Redis cache cleared")
            self._verdict(V, f"IP unchanged ({new_ip}). Redis cache refreshed.", "#22a056")
            msg_queue.put(("done",))
            return

        # Perform IP replacement in database
        msg_queue.put(("progress", "indeterminate"))
        self._verdict(V, f"Replacing IP: {current_ip} → {new_ip} ...", "#3c424e")
        self._log(LOG, f"Replacing {current_ip} -> {new_ip} in database...")

        if current_ip:
            # Replace old IP with new IP
            sql_update = (
                f"UPDATE sys_params SET param_value = REPLACE(param_value, '{current_ip}', '{new_ip}') "
                f"WHERE param_value LIKE '%{current_ip}%'; "
                f"UPDATE ai_model_config SET config_json = REPLACE(config_json, '{current_ip}', '{new_ip}') "
                f"WHERE config_json LIKE '%{current_ip}%';"
            )
        else:
            # No old IP - update websocket and ota URLs with new IP
            sql_update = (
                f"UPDATE sys_params SET param_value = REPLACE(param_value, '192.168.20.42', '{new_ip}') "
                f"WHERE param_value LIKE '%192.168.20.42%'; "
                f"UPDATE ai_model_config SET config_json = REPLACE(config_json, '192.168.20.42', '{new_ip}') "
                f"WHERE config_json LIKE '%192.168.20.42%';"
            )

        cmd = f'docker exec {DB_CONTAINER} mysql -u{DB_USER} -p{DB_PASS} {DB_NAME} -e "{sql_update}"'
        rc, out = run_cmd(cmd, timeout=30)

        if rc == 0:
            self._item(L, "\u2714", "Database updated successfully")
            self._log(LOG, "[OK] Database IP replaced")
        else:
            self._item(L, "\u2718", f"Database update failed: {out}")
            self._log(LOG, f"[FAIL] SQL error: {out}")
            self._verdict(V, "Database update failed. Check logs.", "#ce3a3a")
            msg_queue.put(("progress", 0))
            msg_queue.put(("done",))
            return

        # Flush Redis cache
        self._item(L, "\u2022", "Clearing Redis cache...")
        run_cmd("docker exec xiaozhi-esp32-server-redis redis-cli FLUSHALL", timeout=10)
        self._item(L, "\u2714", "Redis cache cleared")
        self._log(LOG, "[OK] Redis FLUSHALL")

        # Save new IP to .last_ip file
        last_ip_path = os.path.join(SCRIPT_DIR, ".last_ip")
        try:
            with open(last_ip_path, "w") as f:
                f.write(new_ip)
            self._log(LOG, f"Saved new IP to: {last_ip_path}")
        except Exception:
            pass

        # Verify the replacement
        self._item(L, "\u2022", "Verifying...")
        verify_sql = (
            f"SELECT param_code, param_value FROM sys_params "
            f"WHERE param_value LIKE '%{new_ip}%'"
        )
        verify_out = docker_exec_sql(verify_sql)
        if verify_out:
            self._log(LOG, "")
            self._log(LOG, "Verified - configs with new IP:")
            for line in verify_out.strip().split("\n"):
                self._log(LOG, f"  {line}")
            self._item(L, "\u2714", f"IP changed: {current_ip or '(default)'} → {new_ip}")
        else:
            self._log(LOG, "[WARN] Could not verify, but update may have succeeded")

        # Restart services to apply
        self._item(L, "\u2022", "Restarting services to apply new IP...")
        self._verdict(V, "Restarting services...", "#3c424e")

        if IS_WIN:
            rc, out = run_cmd(f'docker compose -p xiaozhi -f "{self._find_compose_file()}" restart', timeout=120)
        else:
            rc, out = run_cmd(f"docker compose -p xiaozhi -f '{self._find_compose_file()}' restart", timeout=120)

        if rc == 0:
            self._item(L, "\u2714", "Services restarted")
            self._log(LOG, "[OK] Services restarted")
        else:
            self._item(L, "!", "Restart may have issues, check Docker status")
            self._log(LOG, f"[WARN] Restart output: {out[:200]}")

        ota_addr = f"http://{new_ip}:{WEB_PORT}/xiaozhi/ota/"
        self._verdict(V, f"Done! Server IP: {new_ip} | Device OTA: {ota_addr}", "#22a056")
        self._log(LOG, "")
        self._log(LOG, f"Device OTA address: {ota_addr}")
        self._log(LOG, "  (trailing slash '/' is REQUIRED)")

        msg_queue.put(("progress", 0))
        msg_queue.put(("done",))

    def _get_current_ip_from_db(self):
        """Read the current server IP from database sys_params."""
        # Try to get from websocket URL or OTA URL in sys_params
        out = docker_exec_sql(
            "SELECT param_value FROM sys_params WHERE param_code IN ('websocket_url','ota_url') LIMIT 1"
        )
        if out:
            # Extract IP from URL like ws://192.168.1.5:8000/xiaozhi/v1/
            m = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", out)
            if m:
                return m.group(1)
        # Fallback: read from .last_ip file
        last_ip_path = os.path.join(SCRIPT_DIR, ".last_ip")
        if os.path.exists(last_ip_path):
            try:
                with open(last_ip_path) as f:
                    ip = f.read().strip()
                if re.match(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", ip):
                    return ip
            except Exception:
                pass
        return None

    def _find_compose_file(self):
        """Find the docker-compose file path."""
        for name in ["docker-compose_all.yml", "docker-compose.yml"]:
            path = os.path.join(SCRIPT_DIR, name)
            if os.path.exists(path):
                return path
        return "docker-compose_all.yml"

    def _safe_extract(self, zf, target_dir, LOG):
        """Extract zip contents safely, skipping files that can't be created on this OS."""
        skipped = []
        # Files to skip: Unix sockets, device files, or names problematic on Windows
        skip_suffixes = ('.sock', '.socket')

        for member in zf.infolist():
            if self.cancel:
                return skipped
            # Skip Unix socket files and other special files
            if any(member.filename.endswith(s) for s in skip_suffixes):
                skipped.append(member.filename)
                continue
            # Skip empty entries with no name
            if not member.filename:
                continue
            try:
                zf.extract(member, target_dir)
            except (OSError, IOError) as e:
                # Skip files that can't be extracted on this platform
                skipped.append(f"{member.filename} ({str(e)})")
                self._log(LOG, f"  [SKIP] {member.filename}: {str(e)}")
            except Exception as e:
                skipped.append(f"{member.filename} ({str(e)})")
                self._log(LOG, f"  [SKIP] {member.filename}: {str(e)}")

        if skipped:
            self._log(LOG, f"  Skipped {len(skipped)} file(s) incompatible with this OS")
        return skipped

    def _do_download(self, zip_path, L, LOG, V):
        """Perform the actual file download. Returns True if successful."""
        import urllib.request

        try:
            self._item(L, "\u2022", f"Downloading from: {XIAOZHI_ZIP_URL}")
            self._log(LOG, f"Downloading {XIAOZHI_ZIP_URL} ...")

            req = urllib.request.Request(XIAOZHI_ZIP_URL)
            req.add_header("User-Agent", "XiaozhiDiagnostic/1.0")
            resp = urllib.request.urlopen(req, timeout=120)

            total_size = resp.headers.get("Content-Length")
            total_size = int(total_size) if total_size else 0
            downloaded = 0
            block_size = 8192

            with open(zip_path, "wb") as f:
                while True:
                    if self.cancel:
                        self._verdict(V, "Download cancelled.", "#d69e14")
                        return False
                    chunk = resp.read(block_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size:
                        pct = int(downloaded / total_size * 100)
                        self._verdict(V,
                                      f"Downloading... {downloaded // (1024*1024)} MB / {total_size // (1024*1024)} MB ({pct}%)",
                                      "#3c424e")

            self._item(L, "\u2714", f"Download complete: {XIAOZHI_ZIP_NAME} ({downloaded // (1024*1024)} MB)")
            self._log(LOG, f"Download complete. Size: {downloaded // (1024*1024)} MB")
            return True

        except Exception as e:
            self._item(L, "\u2718", f"Download failed: {str(e)}")
            self._log(LOG, f"[FAIL] Download error: {str(e)}")
            self._verdict(V, f"Download failed: {str(e)}", "#ce3a3a")
            return False

    def _worker_download(self):
        """Worker thread: download xiaozhi.zip and extract to current directory."""
        L, LOG, V = self.deploy_list, self.deploy_log, self.deploy_verdict
        msg_queue.put(("clear", L)); msg_queue.put(("clear", LOG))
        msg_queue.put(("progress", "indeterminate"))

        target_dir = SCRIPT_DIR
        zip_path = os.path.join(target_dir, XIAOZHI_ZIP_NAME)
        force = getattr(self, '_force_redownload', False)

        self._log(LOG, f"Target directory: {target_dir}")

        # Check if zip already exists
        if os.path.exists(zip_path) and not force:
            self._item(L, "\u2714", f"{XIAOZHI_ZIP_NAME} already exists, skipping download")
            self._log(LOG, f"[INFO] File exists: {zip_path}")
            self._log(LOG, f"  Size: {os.path.getsize(zip_path) // (1024*1024)} MB")
            self._log(LOG, "  Use [Re-download] to force re-download")
            self._verdict(V, "File exists, verifying zip integrity...", "#3c424e")
        else:
            if force:
                self._item(L, "\u2022", "Force re-download requested")
                self._log(LOG, "[INFO] Re-downloading...")
                if os.path.exists(zip_path):
                    os.remove(zip_path)
            self._verdict(V, "Downloading Xiaozhi package...", "#3c424e")
            if not self._do_download(zip_path, L, LOG, V):
                msg_queue.put(("progress", 0))
                msg_queue.put(("done",))
                return

        # Extract - verify zip first
        self._verdict(V, "Verifying and extracting zip file...", "#3c424e")
        self._log(LOG, "Verifying zip integrity...")
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                bad_file = zf.testzip()
                if bad_file:
                    raise zipfile.BadZipFile(f"Corrupt file in archive: {bad_file}")
                self._item(L, "\u2714", "Zip file integrity OK")
                self._log(LOG, "[OK] Zip file is valid")

                # Extract
                self._verdict(V, "Extracting files...", "#3c424e")
                self._log(LOG, "Extracting...")
                self._safe_extract(zf, target_dir, LOG)

            self._item(L, "\u2714", "Extraction complete")
            self._log(LOG, f"Files extracted to: {target_dir}")

            # macOS: fix permissions for shell scripts and executables
            if IS_MAC:
                self._item(L, "\u2022", "Fixing file permissions (macOS)...")
                self._log(LOG, "Setting executable permissions for scripts...")
                for root_dir, dirs, files in os.walk(target_dir):
                    for fname in files:
                        fpath = os.path.join(root_dir, fname)
                        if fname.endswith(('.sh', '.command', '.py')) or not os.path.splitext(fname)[1]:
                            try:
                                with open(fpath, 'rb') as bf:
                                    header = bf.read(4)
                                if header.startswith(b'#!') or fname.endswith(('.sh', '.command')):
                                    os.chmod(fpath, 0o755)
                            except (IOError, OSError):
                                pass
                for pattern in ['*.command', '*.sh']:
                    run_cmd(f'find "{target_dir}" -name "{pattern}" -exec chmod +x {{}} \\;', timeout=10)
                self._item(L, "\u2714", "Permissions fixed")

            self._item(L, "\u2714", "Ready to start Docker services")
            self._verdict(V,
                          "Download & extract complete! Click [Start Docker Services] to deploy.",
                          "#22a056")

            # Enable docker start button, change download button to re-download
            self.root.after(0, lambda: self.btn_docker_start.config(state="normal"))
            self.root.after(0, lambda: self.btn_download.config(text="Re-download", command=self._start_redownload))

        except zipfile.BadZipFile as e:
            self._item(L, "\u2718", f"Zip file is corrupt: {str(e)}")
            self._log(LOG, f"[FAIL] Bad zip file: {str(e)}")
            self._log(LOG, "  Deleting corrupt file and re-downloading...")
            self._verdict(V, "Zip file corrupt, re-downloading...", "#d69e14")

            # Delete bad file and re-download
            try:
                os.remove(zip_path)
            except OSError:
                pass

            if not self._do_download(zip_path, L, LOG, V):
                msg_queue.put(("progress", 0))
                msg_queue.put(("done",))
                return

            # Try extract again
            try:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    self._safe_extract(zf, target_dir, LOG)
                self._item(L, "\u2714", "Re-download and extraction successful")

                if IS_MAC:
                    for root_dir, dirs, files in os.walk(target_dir):
                        for fname in files:
                            fpath = os.path.join(root_dir, fname)
                            if fname.endswith(('.sh', '.command', '.py')):
                                try:
                                    os.chmod(fpath, 0o755)
                                except OSError:
                                    pass
                    for pattern in ['*.command', '*.sh']:
                        run_cmd(f'find "{target_dir}" -name "{pattern}" -exec chmod +x {{}} \\;', timeout=10)

                self._verdict(V, "Re-download & extract complete! Click [Start Docker Services] to deploy.", "#22a056")
                self.root.after(0, lambda: self.btn_docker_start.config(state="normal"))
                self.root.after(0, lambda: self.btn_download.config(text="Re-download", command=self._start_redownload))

            except Exception as e2:
                self._item(L, "\u2718", f"Extract still failed: {str(e2)}")
                self._verdict(V, f"Extract failed after re-download: {str(e2)}", "#ce3a3a")

        except PermissionError as e:
            self._item(L, "\u2718", f"Permission denied: {str(e)}")
            self._verdict(V, "Extract failed: permission denied", "#ce3a3a")
        except Exception as e:
            self._item(L, "\u2718", f"Extract error: {str(e)}")
            self._verdict(V, f"Extract error: {str(e)}", "#ce3a3a")

        msg_queue.put(("progress", 0))
        msg_queue.put(("done",))

    def _worker_docker_start(self):
        """Worker thread: check Docker, start services, verify they are running."""
        L, LOG, V = self.deploy_list, self.deploy_log, self.deploy_verdict
        msg_queue.put(("clear", L)); msg_queue.put(("clear", LOG))
        msg_queue.put(("progress", "indeterminate"))
        self._verdict(V, "Starting Docker services...", "#3c424e")

        # Step 1: Check if Docker is installed
        self._item(L, "\u2022", "Checking Docker installation...")
        self._log(LOG, "===== Docker pre-check =====")

        docker_installed = self._check_docker_installed(L, LOG)
        if not docker_installed:
            self._item(L, "\u2718", "Docker is NOT installed")
            self._log(LOG, "[FAIL] Docker is not installed on this system")
            self._log(LOG, "")
            self._verdict(V, "Docker not installed. Attempting to install...", "#d69e14")

            # Try to install Docker automatically
            install_ok = self._install_docker(L, LOG, V)
            if not install_ok:
                self._verdict(V, "Docker installation failed. Please install Docker manually.", "#ce3a3a")
                msg_queue.put(("progress", 0))
                msg_queue.put(("done",))
                return

        # Step 2: Check if Docker is running
        self._item(L, "\u2022", "Checking if Docker is running...")
        rc, out = run_cmd("docker info", timeout=15)
        if rc != 0:
            self._item(L, "\u2718", "Docker is NOT running, attempting to start...")
            self._log(LOG, "[INFO] Docker not running, trying to start Docker Desktop...")

            # Try to start Docker Desktop automatically
            started = self._launch_docker_desktop(L, LOG)

            if started:
                # Wait for Docker to be ready
                self._item(L, "\u2022", "Waiting for Docker to be ready...")
                self._verdict(V, "Docker Desktop is starting, please wait...", "#3c424e")
                docker_ready = False
                for i in range(60):  # Wait up to 60 seconds
                    if self.cancel:
                        msg_queue.put(("progress", 0))
                        msg_queue.put(("done",))
                        return
                    time.sleep(2)
                    rc2, _ = run_cmd("docker info", timeout=5)
                    if rc2 == 0:
                        docker_ready = True
                        break
                    self._verdict(V, f"Waiting for Docker... ({(i+1)*2}s)", "#3c424e")

                if docker_ready:
                    self._item(L, "\u2714", "Docker Desktop started successfully")
                    self._log(LOG, "[OK] Docker is now running")
                else:
                    self._item(L, "\u2718", "Docker failed to start within 120 seconds")
                    self._log(LOG, "[FAIL] Docker did not become ready in time")
                    self._verdict(V, "Docker failed to start. Please start Docker Desktop manually.", "#ce3a3a")
                    msg_queue.put(("progress", 0))
                    msg_queue.put(("done",))
                    return
            else:
                self._verdict(V, "Could not start Docker. Please start Docker Desktop manually.", "#ce3a3a")
                msg_queue.put(("progress", 0))
                msg_queue.put(("done",))
                return

        self._item(L, "\u2714", "Docker is running")
        self._log(LOG, "[OK] Docker is running")

        # Step 2: Find docker-compose file
        compose_file = None
        for name in ["docker-compose_all.yml", "docker-compose.yml"]:
            path = os.path.join(SCRIPT_DIR, name)
            if os.path.exists(path):
                compose_file = path
                break

        if not compose_file:
            self._item(L, "\u2718", "docker-compose file not found")
            self._log(LOG, "[FAIL] No docker-compose_all.yml or docker-compose.yml found")
            self._verdict(V, "No docker-compose file found in current directory.", "#ce3a3a")
            msg_queue.put(("progress", 0))
            msg_queue.put(("done",))
            return

        self._item(L, "\u2714", f"Found: {os.path.basename(compose_file)}")
        self._log(LOG, f"Using compose file: {compose_file}")

        # Step 3: Start services with docker compose
        self._item(L, "\u2022", "Starting services (this may take a while)...")
        self._log(LOG, "")
        self._log(LOG, "===== Starting docker compose =====")
        self._verdict(V, "Starting containers... (pulling images if needed, please wait)", "#3c424e")

        # Try docker compose (v2) first, then docker-compose (v1)
        compose_cmd = None
        rc_test, _ = run_cmd("docker compose version", timeout=10)
        if rc_test == 0:
            compose_cmd = f'docker compose -p xiaozhi -f "{compose_file}" up -d'
        else:
            rc_test2, _ = run_cmd("docker-compose version", timeout=10)
            if rc_test2 == 0:
                compose_cmd = f'docker-compose -p xiaozhi -f "{compose_file}" up -d'

        if not compose_cmd:
            self._item(L, "\u2718", "docker compose command not found")
            self._log(LOG, "[FAIL] Neither 'docker compose' nor 'docker-compose' is available")
            self._verdict(V, "Docker Compose not found. Install Docker Compose.", "#ce3a3a")
            msg_queue.put(("progress", 0))
            msg_queue.put(("done",))
            return

        self._log(LOG, f"Running: {compose_cmd}")
        rc, out = run_cmd(compose_cmd, timeout=1800)
        if out:
            for line in out.split("\n")[-20:]:
                self._log(LOG, line)

        if rc != 0:
            self._item(L, "\u2718", "docker compose up failed")
            self._log(LOG, f"[FAIL] Exit code: {rc}")
            self._verdict(V, "Docker compose up failed. Check logs for details.", "#ce3a3a")
            msg_queue.put(("progress", 0))
            msg_queue.put(("done",))
            return

        self._item(L, "\u2714", "Docker compose up completed")
        self._log(LOG, "")

        # Step 4: Wait for all containers to be running and healthy
        self._item(L, "\u2022", "Waiting for all services to be ready...")
        self._verdict(V, "Waiting for containers to start...", "#3c424e")
        self._log(LOG, "===== Waiting for services =====")

        max_wait = 300  # Maximum 5 minutes
        check_interval = 5  # Check every 5 seconds
        elapsed = 0

        while elapsed < max_wait:
            if self.cancel:
                self._log(LOG, "Cancelled by user.")
                msg_queue.put(("progress", 0))
                msg_queue.put(("done",))
                return

            time.sleep(check_interval)
            elapsed += check_interval

            # Check how many containers are running
            fmt = "{{.Names}}|{{.Status}}"
            if IS_WIN:
                rc, out = run_cmd(f'docker ps --format "{fmt}"', timeout=10)
            else:
                rc, out = run_cmd(f"docker ps --format '{fmt}'", timeout=10)

            running_containers = {}
            if out:
                for line in out.strip().split("\n"):
                    line = line.strip().strip("'").strip('"')
                    if "|" in line:
                        name, status = line.split("|", 1)
                        running_containers[name.strip()] = status.strip()

            # Count how many of our containers are up
            running_count = sum(1 for c in CONTAINERS if c in running_containers)
            total_count = len(CONTAINERS)

            # Check if containers with healthcheck are healthy
            all_healthy = True
            for c in CONTAINERS:
                if c in running_containers:
                    status = running_containers[c].lower()
                    if "health: starting" in status:
                        all_healthy = False
                else:
                    all_healthy = False

            self._verdict(V,
                          f"Waiting... {running_count}/{total_count} containers running ({elapsed}s elapsed)",
                          "#3c424e")
            self._log(LOG, f"  [{elapsed}s] {running_count}/{total_count} running, healthy={all_healthy}")

            # All containers running and healthy - done!
            if running_count == total_count and all_healthy:
                self._item(L, "\u2714", f"All {total_count} containers are ready ({elapsed}s)")
                self._log(LOG, f"[OK] All containers ready after {elapsed}s")
                break

            # If some containers exited/restarting, show details
            for c in CONTAINERS:
                if c in running_containers:
                    status = running_containers[c]
                    if "restarting" in status.lower():
                        self._log(LOG, f"  [WARN] {c} is restarting: {status}")
        else:
            # Timeout reached
            self._item(L, "!", f"Timeout: not all services ready after {max_wait}s")
            self._log(LOG, f"[WARN] Timeout after {max_wait}s, some services may still be starting")

        # Step 5: Final verification
        self._log(LOG, "")
        self._log(LOG, "===== Post-start verification =====")
        self._verify_docker_services(L, LOG, V)

        # Step 6: Prompt to change IP after successful start
        # Check if all containers are running before offering IP change
        fmt = "{{.Names}}"
        if IS_WIN:
            rc, out = run_cmd(f'docker ps --format "{fmt}"', timeout=10)
        else:
            rc, out = run_cmd(f"docker ps --format '{fmt}'", timeout=10)
        running = [x.strip().strip("'").strip('"') for x in (out or "").split("\n") if x.strip()]
        all_running = all(c in running for c in CONTAINERS)

        if all_running:
            self._item(L, "\u2714", "Services ready! You can now change server IP if needed.")
            self._log(LOG, "")
            self._log(LOG, "[TIP] Click [Change Server IP] to update the server address in database.")

        msg_queue.put(("progress", 0))
        msg_queue.put(("done",))

    def _worker_docker_check(self):
        """Worker thread: check current Docker service status."""
        L, LOG, V = self.deploy_list, self.deploy_log, self.deploy_verdict
        msg_queue.put(("clear", L)); msg_queue.put(("clear", LOG))
        msg_queue.put(("progress", "indeterminate"))
        self._verdict(V, "Checking Docker status...", "#3c424e")
        self._log(LOG, "===== Docker status check =====")

        # Check Docker running
        rc, out = run_cmd("docker info", timeout=15)
        if rc != 0:
            self._item(L, "\u2718", "Docker is NOT running")
            self._log(LOG, "[FAIL] Docker is not running")
            self._verdict(V, "Docker is NOT running. Start Docker Desktop first.", "#ce3a3a")
            msg_queue.put(("progress", 0))
            msg_queue.put(("done",))
            return

        self._item(L, "\u2714", "Docker is running")
        self._log(LOG, "[OK] Docker engine is running")
        self._log(LOG, "")

        # Verify services
        self._verify_docker_services(L, LOG, V)

        msg_queue.put(("progress", 0))
        msg_queue.put(("done",))

    def _check_docker_installed(self, L, LOG):
        """Check if Docker is installed on the system."""
        if IS_WIN:
            # Check if docker.exe exists in PATH or common locations
            rc, out = run_cmd("where docker", timeout=10)
            if rc == 0 and out.strip():
                self._log(LOG, f"  Docker found at: {out.strip().split(chr(10))[0]}")
                return True
            # Check common install paths
            paths = [
                r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
                r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
                os.path.expandvars(r"%ProgramFiles%\Docker\Docker\resources\bin\docker.exe"),
            ]
            for p in paths:
                if os.path.exists(p):
                    self._log(LOG, f"  Docker found at: {p}")
                    return True
            return False
        elif IS_MAC:
            rc, out = run_cmd("which docker", timeout=5)
            if rc == 0 and out.strip():
                self._log(LOG, f"  Docker found at: {out.strip()}")
                return True
            # Check if Docker.app exists
            if os.path.exists("/Applications/Docker.app"):
                self._log(LOG, "  Docker.app found in Applications")
                return True
            return False
        else:
            # Linux
            rc, out = run_cmd("which docker", timeout=5)
            if rc == 0 and out.strip():
                self._log(LOG, f"  Docker found at: {out.strip()}")
                return True
            return False

    def _install_docker(self, L, LOG, V):
        """Attempt to install Docker automatically. Returns True if successful."""
        import urllib.request
        import urllib.error

        if IS_WIN:
            self._item(L, "\u2022", "Downloading Docker Desktop for Windows...")
            self._log(LOG, "Downloading Docker Desktop installer...")
            self._verdict(V, "Downloading Docker Desktop installer...", "#3c424e")

            installer_url = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
            installer_path = os.path.join(SCRIPT_DIR, "DockerDesktopInstaller.exe")

            try:
                req = urllib.request.Request(installer_url)
                req.add_header("User-Agent", "XiaozhiDiagnostic/1.0")
                resp = urllib.request.urlopen(req, timeout=300)

                total_size = resp.headers.get("Content-Length")
                total_size = int(total_size) if total_size else 0
                downloaded = 0
                block_size = 65536

                with open(installer_path, "wb") as f:
                    while True:
                        if self.cancel:
                            return False
                        chunk = resp.read(block_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size:
                            pct = int(downloaded / total_size * 100)
                            self._verdict(V,
                                          f"Downloading Docker... {downloaded // (1024*1024)} MB / {total_size // (1024*1024)} MB ({pct}%)",
                                          "#3c424e")

                self._item(L, "\u2714", "Docker installer downloaded")
                self._log(LOG, f"Installer saved to: {installer_path}")

                # Run installer silently
                self._item(L, "\u2022", "Installing Docker Desktop (this may take a few minutes)...")
                self._verdict(V, "Installing Docker Desktop... please wait", "#3c424e")
                self._log(LOG, "Running installer with install --quiet flag...")
                rc, out = run_cmd(f'"{installer_path}" install --quiet', timeout=600)

                if rc == 0:
                    self._item(L, "\u2714", "Docker Desktop installed successfully")
                    self._log(LOG, "[OK] Docker Desktop installed")
                    # Clean up installer
                    try:
                        os.remove(installer_path)
                    except OSError:
                        pass
                    return True
                else:
                    self._item(L, "\u2718", "Docker installer returned an error")
                    self._log(LOG, f"[WARN] Installer exit code: {rc}")
                    self._log(LOG, f"  Output: {out[:500]}")
                    # It might still have installed, check again
                    rc2, _ = run_cmd("where docker", timeout=10)
                    if rc2 == 0:
                        self._item(L, "\u2714", "Docker appears to be installed despite error")
                        return True
                    return False

            except Exception as e:
                self._item(L, "\u2718", f"Download/install failed: {str(e)}")
                self._log(LOG, f"[FAIL] {str(e)}")
                self._log(LOG, "")
                self._log(LOG, "Please install Docker Desktop manually:")
                self._log(LOG, "  https://www.docker.com/products/docker-desktop/")
                self.root.after(0, lambda: messagebox.showwarning(
                    "Install Docker Manually",
                    "Automatic Docker installation failed.\n\n"
                    "Please download and install Docker Desktop manually:\n"
                    "https://www.docker.com/products/docker-desktop/\n\n"
                    "After installation, click [Start Docker Services] again."
                ))
                return False

        elif IS_MAC:
            self._item(L, "\u2022", "Docker not installed on macOS")
            self._log(LOG, "Attempting to install Docker via Homebrew...")

            # Check if brew is available
            rc, _ = run_cmd("which brew", timeout=5)
            if rc == 0:
                self._item(L, "\u2022", "Installing Docker via Homebrew (may take a while)...")
                self._verdict(V, "Installing Docker via Homebrew...", "#3c424e")
                rc, out = run_cmd("brew install --cask docker", timeout=600)
                if rc == 0:
                    self._item(L, "\u2714", "Docker Desktop installed via Homebrew")
                    self._log(LOG, "[OK] Docker installed via brew")
                    return True
                else:
                    self._log(LOG, f"[FAIL] brew install failed: {out[:300]}")

            # Fallback: prompt user
            self._item(L, "\u2718", "Cannot auto-install Docker on macOS")
            self._log(LOG, "")
            self._log(LOG, "Please install Docker Desktop manually:")
            self._log(LOG, "  https://www.docker.com/products/docker-desktop/")
            self._log(LOG, "  Or: brew install --cask docker")
            self.root.after(0, lambda: messagebox.showwarning(
                "Install Docker Manually",
                "Docker is not installed.\n\n"
                "Please install Docker Desktop for macOS:\n"
                "https://www.docker.com/products/docker-desktop/\n\n"
                "Or run: brew install --cask docker\n\n"
                "After installation, click [Start Docker Services] again."
            ))
            return False

        else:
            # Linux: try to install via package manager
            self._item(L, "\u2022", "Attempting to install Docker on Linux...")
            self._log(LOG, "Trying to install Docker via package manager...")
            self._verdict(V, "Installing Docker...", "#3c424e")

            # Try the official convenience script
            self._log(LOG, "  Trying official install script: get.docker.com")
            rc, out = run_cmd("curl -fsSL https://get.docker.com | sh", timeout=300)
            if rc == 0:
                self._item(L, "\u2714", "Docker installed via get.docker.com")
                self._log(LOG, "[OK] Docker installed")
                # Enable and start docker service
                run_cmd("sudo systemctl enable docker", timeout=10)
                run_cmd("sudo systemctl start docker", timeout=15)
                return True

            # Try apt
            self._log(LOG, "  Trying apt-get install...")
            rc, out = run_cmd("sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin", timeout=300)
            if rc == 0:
                self._item(L, "\u2714", "Docker installed via apt")
                run_cmd("sudo systemctl enable docker", timeout=10)
                run_cmd("sudo systemctl start docker", timeout=15)
                return True

            # Try yum/dnf
            self._log(LOG, "  Trying yum/dnf install...")
            rc, _ = run_cmd("which dnf", timeout=5)
            pkg_cmd = "dnf" if rc == 0 else "yum"
            rc, out = run_cmd(f"sudo {pkg_cmd} install -y docker docker-compose-plugin", timeout=300)
            if rc == 0:
                self._item(L, "\u2714", f"Docker installed via {pkg_cmd}")
                run_cmd("sudo systemctl enable docker", timeout=10)
                run_cmd("sudo systemctl start docker", timeout=15)
                return True

            self._item(L, "\u2718", "Could not auto-install Docker on Linux")
            self._log(LOG, "[FAIL] All installation attempts failed")
            self._log(LOG, "")
            self._log(LOG, "Please install Docker manually:")
            self._log(LOG, "  https://docs.docker.com/engine/install/")
            self.root.after(0, lambda: messagebox.showwarning(
                "Install Docker Manually",
                "Automatic Docker installation failed.\n\n"
                "Please install Docker manually:\n"
                "https://docs.docker.com/engine/install/\n\n"
                "After installation, click [Start Docker Services] again."
            ))
            return False

    def _launch_docker_desktop(self, L, LOG):
        """Try to launch Docker Desktop automatically. Returns True if launch command succeeded."""
        try:
            if IS_WIN:
                # Windows: try common Docker Desktop paths
                docker_paths = [
                    r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
                    r"C:\Program Files (x86)\Docker\Docker\Docker Desktop.exe",
                    os.path.expandvars(r"%ProgramFiles%\Docker\Docker\Docker Desktop.exe"),
                    os.path.expandvars(r"%LocalAppData%\Docker\Docker Desktop.exe"),
                ]
                launched = False
                for docker_path in docker_paths:
                    if os.path.exists(docker_path):
                        self._log(LOG, f"  Launching: {docker_path}")
                        subprocess.Popen(
                            [docker_path],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=0x00000008  # DETACHED_PROCESS
                        )
                        launched = True
                        break

                if not launched:
                    # Try via start command (searches PATH and Start Menu)
                    self._log(LOG, "  Trying: start Docker Desktop via shell...")
                    rc, _ = run_cmd('start "" "Docker Desktop"', timeout=10)
                    if rc != 0:
                        # Try powershell Start-Process
                        rc, _ = run_cmd(
                            'powershell -Command "Start-Process \'Docker Desktop\' -ErrorAction SilentlyContinue"',
                            timeout=10
                        )
                    launched = True  # We attempted, let the wait loop verify

                self._item(L, "\u2022", "Docker Desktop launch command sent (Windows)")
                return launched

            elif IS_MAC:
                # macOS: use open -a Docker
                self._log(LOG, "  Launching: open -a Docker")
                rc, out = run_cmd("open -a Docker", timeout=10)
                if rc == 0:
                    self._item(L, "\u2022", "Docker Desktop launch command sent (macOS)")
                    return True
                else:
                    # Try alternate path
                    rc, _ = run_cmd("open /Applications/Docker.app", timeout=10)
                    if rc == 0:
                        self._item(L, "\u2022", "Docker Desktop launch command sent (macOS)")
                        return True
                    self._item(L, "\u2718", "Failed to launch Docker Desktop on macOS")
                    self._log(LOG, f"  [FAIL] open -a Docker failed: {out}")
                    return False

            else:
                # Linux: try systemctl to start docker daemon
                self._log(LOG, "  Launching: systemctl start docker")
                rc, out = run_cmd("systemctl start docker", timeout=15)
                if rc == 0:
                    self._item(L, "\u2022", "Docker daemon started (Linux systemctl)")
                    return True
                # Try without sudo (in case already has permissions)
                self._log(LOG, f"  systemctl failed (rc={rc}), trying sudo...")
                rc2, out2 = run_cmd("sudo systemctl start docker", timeout=15)
                if rc2 == 0:
                    self._item(L, "\u2022", "Docker daemon started (Linux sudo systemctl)")
                    return True
                # Try service command
                rc3, _ = run_cmd("sudo service docker start", timeout=15)
                if rc3 == 0:
                    self._item(L, "\u2022", "Docker daemon started (Linux service)")
                    return True
                self._item(L, "\u2718", "Failed to start Docker on Linux")
                self._log(LOG, f"  [FAIL] Could not start docker: {out2}")
                return False

        except Exception as e:
            self._log(LOG, f"  [ERROR] Exception launching Docker: {str(e)}")
            self._item(L, "\u2718", f"Error launching Docker: {str(e)}")
            return False

    def _verify_docker_services(self, L, LOG, V):
        """Verify all Docker containers are running and healthy."""
        # Check containers - use double quotes on Windows, single on Unix
        fmt = "{{.Names}}|{{.Status}}"
        if IS_WIN:
            rc, out = run_cmd(f'docker ps --format "{fmt}"', timeout=10)
        else:
            rc, out = run_cmd(f"docker ps --format '{fmt}'", timeout=10)
        running_containers = {}
        if out:
            for line in out.strip().split("\n"):
                line = line.strip().strip("'")
                if "|" in line:
                    name, status = line.split("|", 1)
                    running_containers[name.strip()] = status.strip()

        self._log(LOG, f"Running containers: {len(running_containers)}")
        all_ok = True
        for container in CONTAINERS:
            if self.cancel:
                return
            if container in running_containers:
                status = running_containers[container]
                is_healthy = "healthy" in status.lower() or "up" in status.lower()
                icon = "\u2714" if is_healthy else "!"
                self._item(L, icon, f"{container}: {status}")
                self._log(LOG, f"  [{container}] {status}")
                if not is_healthy:
                    all_ok = False
            else:
                self._item(L, "\u2718", f"{container}: NOT running")
                self._log(LOG, f"  [{container}] NOT FOUND")
                all_ok = False

        # Check ports
        self._log(LOG, "")
        self._log(LOG, "Port check:")
        port_map = {WS_PORT: "WebSocket", WEB_PORT: "Web/OTA", VISION_PORT: "Vision"}
        ports_ok = True
        for p, desc in port_map.items():
            if port_listening(p):
                self._item(L, "\u2714", f"Port {p} ({desc}): listening")
                self._log(LOG, f"  Port {p} ({desc}): OK")
            else:
                self._item(L, "\u2718", f"Port {p} ({desc}): NOT listening")
                self._log(LOG, f"  Port {p} ({desc}): FAILED")
                ports_ok = False

        # Check container logs for errors (last 10 lines of main server)
        self._log(LOG, "")
        rc, logs = run_cmd("docker logs --tail 5 xiaozhi-esp32-server", timeout=10)
        if logs:
            self._log(LOG, "Recent server logs:")
            for line in logs.split("\n")[-5:]:
                self._log(LOG, f"  {line[:150]}")

        # Final verdict
        if all_ok and ports_ok:
            self._verdict(V, "All Docker services are running and healthy!", "#22a056")
            self._item(L, "\u2714", "All services OK")
            # Enable docker start button for restarts
            self.root.after(0, lambda: self.btn_docker_start.config(state="normal"))
        elif all_ok and not ports_ok:
            self._verdict(V, "Containers running but some ports not ready. Services may still be starting...", "#d69e14")
            self.root.after(0, lambda: self.btn_docker_start.config(state="normal"))
        else:
            self._verdict(V, "Some services are not running. Click [Start Docker Services] to start them.", "#ce3a3a")
            self.root.after(0, lambda: self.btn_docker_start.config(state="normal"))

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
        self.btn_one_click_start.config(state=st)
        self.btn_change_ip.config(state=st)
        self.btn_redownload.config(state=st)
        self.btn_stop_containers.config(state=st)
        self.btn_open_admin.config(state=st)
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
            if IS_WIN:
                rc, out = run_cmd('docker ps --format "{{.Names}}"')
            else:
                rc, out = run_cmd("docker ps --format '{{.Names}}'")
            if out:
                running = [x.strip().strip("'").strip('"') for x in out.split("\n") if x.strip()]
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
            rc, sl = run_cmd("docker logs --since 60s xiaozhi-esp32-server", timeout=10)
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
            self._item(L, "\u2714", "Device detected on the network")
            self._log(LOG, "[OK] Device reached the server but full conversation channel not confirmed in logs.")
            self._log(LOG, "     This usually means the connection is working. Try talking to the device.")
            self._verdict(V, "Device detected! Connection appears OK. If device still not responding, check Conversation Health tab.", "#22a056")
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

        rc, log = run_cmd("docker logs --tail 600 xiaozhi-esp32-server", timeout=20)
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
