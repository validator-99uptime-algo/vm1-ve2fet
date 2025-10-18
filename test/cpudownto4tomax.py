#!/usr/bin/env python3
import os
import subprocess

def get_all_possible_cpus():
    cpu_dir = "/sys/devices/system/cpu/"
    cpus = []
    for entry in os.listdir(cpu_dir):
        if entry.startswith("cpu") and entry[3:].isdigit():
            cpus.append(int(entry[3:]))
    return sorted(cpus)

def get_cpu_state(cpu):
    online_file = f"/sys/devices/system/cpu/cpu{cpu}/online"
    if os.path.exists(online_file):
        with open(online_file, "r") as f:
            return f.read().strip() == "1"
    return None

def set_cpu_state(cpu, online):
    online_file = f"/sys/devices/system/cpu/cpu{cpu}/online"
    if os.path.exists(online_file):
        val = b"1\n" if online else b"0\n"
        subprocess.run(
            ["sudo", "/usr/bin/tee", online_file],
            input=val,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

def limit_online_cpus(max_online=8):
    """Turn off CPUs so that at most `max_online` remain online.
       Returns list of CPUs that were taken offline."""
    cpus = get_all_possible_cpus()
    online = [c for c in cpus if get_cpu_state(c)]
    # If there are more than max_online, turn off highest-numbered first
    to_disable = []
    for cpu in sorted(online, reverse=True):
        if len(online) - len(to_disable) > max_online:
            to_disable.append(cpu)
    for cpu in to_disable:
        set_cpu_state(cpu, False)
    return to_disable

def enable_all_cpus():
    """Bring every possible CPU online."""
    for cpu in get_all_possible_cpus():
        set_cpu_state(cpu, True)

if __name__ == "__main__":
    print("All possible CPUs:", get_all_possible_cpus())
    print("Currently online:", [c for c in get_all_possible_cpus() if get_cpu_state(c)])

    # --- Limit to 4 cores ---
    print("\nLimiting to 8 online CPUs...0-7")
    disabled = limit_online_cpus(7)
    print("CPUs taken offline:", disabled)
    print("Now online:", [c for c in get_all_possible_cpus() if get_cpu_state(c)])

    input("\nPress Enter when you’re done with your 8-core workload...")

    # --- Restore to max ---
    print("\nBringing all CPUs back online...")
    enable_all_cpus()
    print("Now online (should be max):", [c for c in get_all_possible_cpus() if get_cpu_state(c)])
    print("Done.")
