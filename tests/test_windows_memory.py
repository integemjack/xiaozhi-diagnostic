#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Headless test for Windows memory detection.

Exercises the REAL code paths in src/main.py without launching the Tk GUI:
  - DiagnosticApp._get_windows_memory  (the layered fallback method)
  - DiagnosticApp._get_system_memory   (the cross-platform entry point)

It also independently probes each of the three fallback strategies
(GlobalMemoryStatusEx via ctypes, wmic, PowerShell Get-CimInstance) and
reports which ones work on the current runner, so we can see Win10/Win11
coverage in the CI logs.

Exit code 0 = memory was obtained and is sane; non-zero = failure.
"""
import os
import sys
import platform

# Make src/ importable
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "src")
sys.path.insert(0, SRC)

import main  # noqa: E402  (importing main does NOT launch Tk; guarded by __main__)


def gb(n):
    return n / (1024 ** 3)


def probe_individual_methods():
    """Report which low-level strategies work, for visibility in CI logs."""
    print("--- Individual strategy probes ---")

    # 1) ctypes GlobalMemoryStatusEx
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        if ok and stat.ullTotalPhys > 0:
            print(f"  [PASS] GlobalMemoryStatusEx: total={gb(stat.ullTotalPhys):.2f} GB "
                  f"free={gb(stat.ullAvailPhys):.2f} GB load={stat.dwMemoryLoad}%")
        else:
            print("  [WARN] GlobalMemoryStatusEx returned no data")
    except Exception as e:
        print(f"  [WARN] GlobalMemoryStatusEx failed: {e}")

    # 2) wmic
    try:
        rc, out = main.run_cmd(
            "wmic OS get TotalVisibleMemorySize,FreePhysicalMemory /format:list",
            timeout=15)
        has = "TotalVisibleMemorySize=" in out
        print(f"  [{'PASS' if (rc == 0 and has) else 'WARN'}] wmic rc={rc} "
              f"has_data={has}")
    except Exception as e:
        print(f"  [WARN] wmic failed: {e}")

    # 3) PowerShell Get-CimInstance
    try:
        rc, out = main.run_cmd(
            'powershell -NoProfile -NonInteractive -Command '
            '"Get-CimInstance Win32_OperatingSystem | '
            'Select-Object TotalVisibleMemorySize,FreePhysicalMemory | Format-List"',
            timeout=20)
        has = "TotalVisibleMemorySize" in out
        print(f"  [{'PASS' if (rc == 0 and has) else 'WARN'}] PowerShell Get-CimInstance "
              f"rc={rc} has_data={has}")
    except Exception as e:
        print(f"  [WARN] PowerShell Get-CimInstance failed: {e}")


def main_test():
    print(f"OS: {platform.system()} {platform.release()} ({platform.version()})")
    print(f"Python: {sys.version.split()[0]}")
    print(f"IS_WIN={main.IS_WIN}")
    print()

    probe_individual_methods()
    print()

    print("--- Real code path: DiagnosticApp._get_windows_memory ---")
    # Create an instance WITHOUT running __init__ so no Tk window is created,
    # while still getting properly bound methods.
    app = main.DiagnosticApp.__new__(main.DiagnosticApp)
    win_mem = app._get_windows_memory()
    print(f"  result: {win_mem}")

    print("--- Real code path: DiagnosticApp._get_system_memory ---")
    sys_mem = app._get_system_memory()
    print(f"  result: {sys_mem}")
    print()

    # Validate
    errors = []
    if not sys_mem:
        errors.append("_get_system_memory returned None")
    else:
        total = sys_mem.get("total", 0)
        free = sys_mem.get("free", 0)
        used = sys_mem.get("used", 0)
        print(f"  total={gb(total):.2f} GB  used={gb(used):.2f} GB  free={gb(free):.2f} GB")
        if total <= 0:
            errors.append(f"total memory is not positive: {total}")
        if free < 0:
            errors.append(f"free memory is negative: {free}")
        if free > total:
            errors.append(f"free ({free}) > total ({total})")
        # A CI runner should have at least 1 GB total and 4 GB is typical.
        if 0 < total < (1 * 1024 ** 3):
            errors.append(f"total memory implausibly low: {gb(total):.2f} GB")

    if errors:
        print("\nRESULT: FAIL")
        for e in errors:
            print(f"  [FAIL] {e}")
        return 1

    print("\nRESULT: PASS - memory information obtained and sane.")
    return 0


if __name__ == "__main__":
    sys.exit(main_test())
