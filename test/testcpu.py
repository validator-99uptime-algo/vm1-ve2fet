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

def enable_all_standby_cpus():
    cpus = get_all_possible_cpus()
    original_states = {}
    for cpu in cpus:
        state = get_cpu_state(cpu)
        original_states[cpu] = state
        if state is False:
            set_cpu_state(cpu, True)
    return original_states

def restore_cpus_to_states(original_states):
    for cpu, was_online in original_states.items():
        current = get_cpu_state(cpu)
        if was_online is False and current is True:
            set_cpu_state(cpu, False)


if __name__ == "__main__":
    print("All possible CPUs on this VM:", get_all_possible_cpus())

    # Print which CPUs are currently online
    online_cpus = [cpu for cpu in get_all_possible_cpus() if get_cpu_state(cpu)]
    print("Currently online CPUs:", online_cpus)

    print("\nEnabling all standby (offline) CPUs...")
    original_states = enable_all_standby_cpus()

    # Print now-online CPUs
    online_cpus = [cpu for cpu in get_all_possible_cpus() if get_cpu_state(cpu)]
    print("CPUs now online:", online_cpus)

    # Simulate workload
    input("\nSimulating heavy work... Press Enter to restore previous CPU states.")

    print("Restoring CPUs to their original states...")
    restore_cpus_to_states(original_states)

    # Print final state
    online_cpus = [cpu for cpu in get_all_possible_cpus() if get_cpu_state(cpu)]
    print("CPUs now online (should match original):", online_cpus)
    print("Done.")
