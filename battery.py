import psutil
import time
import csv
import os
from datetime import datetime

# --- RAW ENERGY IMPORT ---
try:
    import pyRAPL
    pyRAPL.setup(devices=[pyRAPL.Device.PKG, pyRAPL.Device.DRAM])
    RAPL_INITIALIZED = True
except ImportError:
    RAPL_INITIALIZED = False
    print("WARNING: pyRAPL not found. Install with 'pip install pyRAPL'. Cannot collect raw energy data.")
except Exception as e:
    RAPL_INITIALIZED = False
    print(f"WARNING: pyRAPL initialization failed. Likely need admin/MSR access. Error: {e}")

# --- Configuration ---
OUTPUT_FILENAME = "telemetry_data.csv"
COLLECTION_INTERVAL_SECONDS = 3  # seconds

# Global for last RAPL reading
LAST_RAPL_ENERGY = {}

def get_rapl_energy(interval):
    """Return CPU and DRAM energy in Joules (or 0 if unavailable)."""
    global LAST_RAPL_ENERGY
    if not RAPL_INITIALIZED:
        return {'PKG_Energy_Joules': 0.0, 'DRAM_Energy_Joules': 0.0}
    try:
        measurement = pyRAPL.Measurement('snapshot')
        measurement.begin()
        time.sleep(0.001)
        measurement.end()
        pkg_energy = measurement.result.energy['package'][0] if measurement.result.energy.get('package') else 0.0
        dram_energy = measurement.result.energy['dram'][0] if measurement.result.energy.get('dram') else 0.0
        return {'PKG_Energy_Joules': round(pkg_energy, 4), 'DRAM_Energy_Joules': round(dram_energy, 4)}
    except Exception:
        return {'PKG_Energy_Joules': 0.0, 'DRAM_Energy_Joules': 0.0}

def get_telemetry_snapshot():
    """Return a dict of system telemetry data."""
    try:
        rapl_data = get_rapl_energy(COLLECTION_INTERVAL_SECONDS)
        cpu_usage = psutil.cpu_percent(interval=None)
        cpu_freq = psutil.cpu_freq()
        mem = psutil.virtual_memory()
        net_io = psutil.net_io_counters()
        disk_io = psutil.disk_io_counters()

        # Thermal
        try:
            thermal_data = psutil.sensors_temperatures()
            cpu_temp = thermal_data.get('coretemp', [None])[0]
            core_temp_c = cpu_temp.current if cpu_temp else -1
        except AttributeError:
            core_temp_c = -1

        # Battery
        try:
            battery = psutil.sensors_battery()
            power_plugged = battery.power_plugged if battery else False
            battery_pct = battery.percent if battery else -1
        except AttributeError:
            power_plugged = False
            battery_pct = -1

        # Context label placeholder
        activity_label = "PENDING_CONTEXTUAL_LABEL"

        return {
            'Timestamp': datetime.now().isoformat(),
            'Activity_Label': activity_label,
            'CPU_Package_Energy_Joules': rapl_data['PKG_Energy_Joules'],
            'DRAM_Energy_Joules': rapl_data['DRAM_Energy_Joules'],
            'CPU_Usage_Pct': cpu_usage,
            'CPU_Freq_Current_MHz': cpu_freq.current if cpu_freq else -1,
            'CPU_Cores_Active': psutil.cpu_count(logical=False),
            'Mem_Usage_Pct': mem.percent,
            'Mem_Used_GB': round(mem.used / (1024**3), 2),
            'Disk_Read_Bytes_Cumulative': disk_io.read_bytes,
            'Disk_Write_Bytes_Cumulative': disk_io.write_bytes,
            'Net_Sent_Bytes_Cumulative': net_io.bytes_sent,
            'Net_Recv_Bytes_Cumulative': net_io.bytes_recv,
            'Thermal_Temp_C': core_temp_c,
            'Battery_Level_Pct': battery_pct,
            'Power_Plugged': power_plugged
        }

    except Exception as e:
        print(f"Error during telemetry collection: {e}")
        return None

def collect_data(duration_seconds):
    """Collect telemetry data for the given duration and save to CSV."""
    initial_snapshot = get_telemetry_snapshot()
    if not initial_snapshot:
        print("Failed to get initial snapshot. Exiting.")
        return

    fieldnames = list(initial_snapshot.keys())
    write_header = not os.path.exists(OUTPUT_FILENAME) or os.path.getsize(OUTPUT_FILENAME) == 0

    print(f"\n--- Starting Data Collection for {duration_seconds} seconds ---")
    print(f"Data will be saved to: {os.path.abspath(OUTPUT_FILENAME)}")
    print(f"Sampling every {COLLECTION_INTERVAL_SECONDS} seconds.")
    print(f"RAPL Status: {'ACTIVE' if RAPL_INITIALIZED else 'INACTIVE (No raw energy data)'}")

    start_time = time.time()
    with open(OUTPUT_FILENAME, 'a', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
            print("CSV header written.")

        while time.time() - start_time < duration_seconds:
            data_row = get_telemetry_snapshot()
            if data_row:
                writer.writerow(data_row)
                elapsed = int(time.time() - start_time)
                progress_pct = (elapsed / duration_seconds) * 100
                energy_joules = data_row.get('CPU_Package_Energy_Joules', 0.0)
                avg_power = energy_joules / COLLECTION_INTERVAL_SECONDS if energy_joules > 0 else 0
                print(f"[{elapsed:04d}s/{duration_seconds}s | {progress_pct:.1f}%] "
                      f"CPU: {data_row['CPU_Usage_Pct']:.1f}% | Temp: {data_row['Thermal_Temp_C']}°C | "
                      f"Power(W): {avg_power:.2f}", end='\r')

            time.sleep(COLLECTION_INTERVAL_SECONDS)

    print("\n\n--- Collection Complete ---")
    print(f"CSV saved successfully at: {os.path.abspath(OUTPUT_FILENAME)}")
    print("Remember to replace 'PENDING_CONTEXTUAL_LABEL' manually in the CSV.")

if __name__ == "__main__":
    while True:
        try:
            duration = input("Enter collection duration in seconds (e.g., 300 for 5 minutes): ")
            duration_seconds = int(duration)
            if duration_seconds <= 0:
                print("Duration must be positive.")
                continue
            break
        except ValueError:
            print("Invalid input. Enter an integer.")

    collect_data(duration_seconds)
