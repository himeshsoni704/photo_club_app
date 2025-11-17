import sys 
import time
import requests
from datetime import datetime
import os
import psutil

# --- Configuration ---
LOG_INTERVAL_SECONDS = 5  # How often to take a system snapshot
LOG_DURATION_HOURS = 2    # Script will stop after this duration (set high for full battery life test)

# !!! CRITICAL: REPLACE THIS WITH THE IP ADDRESS OF YOUR COLLECTION MACHINE !!!
# Find your collection machine's local IP (e.g., 192.168.1.50)
SERVER_URL = "http://192.168.1.50:5000/collect_data" 
# NOTE: The server.py file must be running on this IP address.

# --- Feature Definitions (Must match the server) ---
FIELDNAMES = [
    'timestamp',
    'user_activity_label',
    'battery_level_percent',
    'cpu_usage_percent',
    'cpu_freq_mhz',
    'memory_usage_percent',
    'disk_read_mbps',
    'disk_write_mbps',
    'net_sent_mbps',
    'net_recv_mbps',
    'wifi_status_proxy',
    'top_process_name',
    'top_process_cpu_percent',
]

# --- Helper Functions ---

def bytes_to_mbps(byte_rate, interval):
    """Converts bytes/interval to MB/s."""
    return round((byte_rate / interval) / (1024 * 1024), 2)

def get_top_process():
    """Finds the process with the highest CPU usage."""
    try:
        processes = []
        # Get all processes with CPU percentage
        for proc in psutil.process_iter(['name', 'cpu_percent']):
            processes.append(proc.info)

        # Sort by CPU percentage (descending)
        processes.sort(key=lambda x: x['cpu_percent'], reverse=True)

        if processes:
            top_proc = processes[0]
            if top_proc['cpu_percent'] > 0:
                return top_proc['name'], round(top_proc['cpu_percent'], 2)

    except Exception:
        return 'N/A', 0.0

    return 'N/A', 0.0

def collect_data(prev_disk_io, prev_net_io, interval, activity_label):
    """Collects a single snapshot of system metrics."""
    try:
        # 1. TIME & BATTERY
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        battery = psutil.sensors_battery()
        batt_level = battery.percent if battery else -1

        # 2. CPU
        # psutil.cpu_percent needs to be called with a very small interval to get a quick reading
        cpu_usage = psutil.cpu_percent(interval=0.1) 
        cpu_freq = psutil.cpu_freq().current / 1000 if psutil.cpu_freq() else 0.0 # KHz to MHz

        # 3. MEMORY
        memory_usage = psutil.virtual_memory().percent

        # 4. DISK I/O (Calculate rate since last log)
        current_disk_io = psutil.disk_io_counters()
        # Ensure we don't calculate rate on the first run (where prev is all zeros)
        if prev_disk_io:
            disk_read_bytes = current_disk_io.read_bytes - prev_disk_io.read_bytes
            disk_write_bytes = current_disk_io.write_bytes - prev_disk_io.write_bytes
        else:
            disk_read_bytes = 0
            disk_write_bytes = 0
            
        disk_read_mbps = bytes_to_mbps(disk_read_bytes, interval)
        disk_write_mbps = bytes_to_mbps(disk_write_bytes, interval)

        # 5. NETWORK I/O (Calculate rate since last log)
        current_net_io = psutil.net_io_counters()
        if prev_net_io:
            net_sent_bytes = current_net_io.bytes_sent - prev_net_io.bytes_sent
            net_recv_bytes = current_net_io.bytes_recv - prev_net_io.bytes_recv
        else:
            net_sent_bytes = 0
            net_recv_bytes = 0
            
        net_sent_mbps = bytes_to_mbps(net_sent_bytes, interval)
        net_recv_mbps = bytes_to_mbps(net_recv_bytes, interval)

        # 6. WIFI/CONNECTIVITY PROXY
        is_wifi_active = 'ON' if net_sent_mbps > 0.01 or net_recv_mbps > 0.01 else 'OFF'

        # 7. WORKFLOW PROXY (Top Process)
        top_proc_name, top_proc_cpu = get_top_process()

        data = {
            'timestamp': current_time,
            'user_activity_label': activity_label,
            'battery_level_percent': batt_level,
            'cpu_usage_percent': cpu_usage,
            'cpu_freq_mhz': round(cpu_freq, 1),
            'memory_usage_percent': memory_usage,
            'disk_read_mbps': disk_read_mbps,
            'disk_write_mbps': disk_write_mbps,
            'net_sent_mbps': net_sent_mbps,
            'net_recv_mbps': net_recv_mbps,
            'wifi_status_proxy': is_wifi_active,
            'top_process_name': top_proc_name,
            'top_process_cpu_percent': top_proc_cpu,
        }

        # Return data and current I/O counters for next interval calculation
        return data, current_disk_io, current_net_io

    except Exception as e:
        print(f"Error collecting data: {e}")
        return None, prev_disk_io, prev_net_io
        
def send_data(data):
    """Sends the collected data snapshot to the central server."""
    try:
        response = requests.post(SERVER_URL, json=data, timeout=5)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        return True
    except requests.exceptions.RequestException as e:
        # Check if running as a bundled executable
        if getattr(sys, 'frozen', False):
            # If frozen, we don't want the console window to disappear immediately on error,
            # but we also need to avoid hanging the script. We just log the error.
            pass 
        else:
            print(f"CLIENT ERROR: Failed to send data to server: {e}")
        return False

def main():
    """Main logging and sending loop."""
    
    # --- GET USER ACTIVITY LABEL FROM COMMAND LINE OR SET DEFAULT ---
    # The label must now be passed as the first argument when running the script.
    if len(sys.argv) > 1:
        user_activity_label = sys.argv[1].strip()
        if not user_activity_label:
            user_activity_label = "Unlabeled Workload"
    else:
        user_activity_label = "Unlabeled Workload"

    print("--- System Telemetry Sender Initializing ---")
    print("\n--- WORKLOAD CONTEXT ---")
    
    # If the label is default, print a warning to the console
    if user_activity_label == "Unlabeled Workload":
        print("WARNING: Activity label not provided as a command-line argument.")

    print(f"Activity Label set to: '{user_activity_label}'")
    print(f"Log Interval: {LOG_INTERVAL_SECONDS} seconds")
    print(f"Target Server URL: {SERVER_URL}")
    print(f"Maximum Duration: {LOG_DURATION_HOURS} hours")


    # --- Initial Setup ---
    # Need to call cpu_percent to prime the I/O counters
    psutil.cpu_percent(interval=0.1) 
    
    # Get initial I/O counters to calculate deltas
    prev_disk_io = psutil.disk_io_counters()
    prev_net_io = psutil.net_io_counters()
    start_time = time.time()
    
    # Convert max duration to seconds
    max_duration_seconds = LOG_DURATION_HOURS * 3600

    try:
        # --- Main Logging and Sending Loop ---
        while (time.time() - start_time) < max_duration_seconds:
            
            # Collect data - PASS THE LABEL
            data_snapshot, prev_disk_io, prev_net_io = collect_data(
                prev_disk_io, prev_net_io, LOG_INTERVAL_SECONDS, user_activity_label
            )
            
            if data_snapshot:
                # Attempt to send the data
                send_success = send_data(data_snapshot)
                
                # Console progress update
                status = "SENT" if send_success else "FAILED"
                print(f"[{data_snapshot['timestamp']}] Batt: {data_snapshot['battery_level_percent']}% | CPU: {data_snapshot['cpu_usage_percent']}% | Label: {user_activity_label} ({status})")
            
            # Wait for the next interval
            time.sleep(LOG_INTERVAL_SECONDS)
            
            # Check for battery drain to 0% (or very low) to stop gracefully
            battery_info = psutil.sensors_battery()
            if battery_info and battery_info.percent <= 5 and not battery_info.power_plugged:
                print("\n--- Battery level critically low (<=5%). Stopping log. ---")
                break


    except KeyboardInterrupt:
        print("\n--- Logging stopped manually by user (Ctrl+C). ---")
    except Exception as e:
        print(f"\n--- Critical error during operation: {e} ---")
    finally:
        print("Data collection finished.")
        # Pause the console for a moment if running as an executable
        if getattr(sys, 'frozen', False):
            input("Press Enter to close the window...")


if __name__ == "__main__":
    main()