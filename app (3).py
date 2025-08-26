import serial
import serial.tools.list_ports
from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
import time
import collections
import numpy as np
from scipy.fft import fft

app = Flask(__name__)
CORS(app) # Enable CORS for all routes

# --- Configuration (matches your plotting script) ---
BAUD_RATE = 115200
SAMPLE_RATE = 1000 # Must match Arduino
N_FFT = 256        # Number of FFT points

# Calculate frequencies once
FREQS = np.fft.fftfreq(N_FFT, 1 / SAMPLE_RATE)[:N_FFT // 2].tolist() # Convert to list for JSON

# --- Global State for Serial Communication ---
ser = None  # Global serial port object
serial_reader_thread = None
is_reading_serial = False

# Store latest N_FFT samples for each of the 8 microphones
# Each mic_id (0-7) will have its own deque
latest_mic_buffers = {str(i): collections.deque(maxlen=N_FFT) for i in range(8)}
latest_mic_heatmap_values = {str(i): 0 for i in range(8)} # For heatmap values

console_logs = collections.deque(maxlen=50) # Stores up to 50 console messages
connected_mics_set = set() # To keep track of which mics are actively sending data (0-7)
lock = threading.Lock() # To protect shared resources from race conditions

# --- Serial Reading Thread Function ---
def read_from_serial():
    global is_reading_serial
    global connected_mics_set
    global latest_mic_heatmap_values

    # Clear previous data when starting
    for mic_id in latest_mic_buffers:
        latest_mic_buffers[mic_id].clear()
    latest_mic_heatmap_values = {str(i): 0 for i in range(8)}
    connected_mics_set.clear()
    console_logs.clear()
    
    with lock: # Acquire lock before appending to console_logs
        console_logs.append(f"Serial reader thread started for {ser.port}...")
        console_logs.append("Waiting for Arduino 'READY' signal...")

    try:
        # Wait for Arduino's "READY" signal
        ready_received = False
        while is_reading_serial and not ready_received:
            if ser and ser.is_open:
                line = ser.readline().decode('utf-8').strip()
                if line == "READY":
                    with lock:
                        console_logs.append("Arduino is READY!")
                    ready_received = True
                elif line: # Still log other messages while waiting for READY
                    with lock:
                        console_logs.append(f"[PRE-READY] {line}")
            time.sleep(0.01) # Small delay

        if not ready_received:
            with lock:
                console_logs.append("Arduino READY signal not received, stopping thread.")
            is_reading_serial = False
            return # Exit thread if not ready

        # Start reading actual data
        while is_reading_serial:
            if ser and ser.is_open:
                try:
                    line = ser.readline().decode('utf-8').strip()
                    if line:
                        with lock:
                            console_logs.append(f"[RAW] {line}")
                        
                        # --- Parsing Logic (from your code) ---
                        values = list(map(int, line.split('\t')))

                        if len(values) == 8:
                            with lock: # Protect shared buffers
                                temp_connected_mics = set()
                                for i in range(8):
                                    mic_id_str = str(i)
                                    latest_mic_buffers[mic_id_str].append(values[i])
                                    latest_mic_heatmap_values[mic_id_str] = values[i] # Update heatmap value
                                    temp_connected_mics.add(mic_id_str)
                                
                                connected_mics_set.update(temp_connected_mics) # Update only with currently reporting mics

                        else:
                            with lock:
                                console_logs.append(f"[WARN] Expected 8 values, got {len(values)}: {line}")
                except ValueError as ve:
                    with lock:
                        console_logs.append(f"[ERROR] Data format error: {ve} in line '{line}'")
                except Exception as e:
                    with lock:
                        console_logs.append(f"[ERROR] Error reading/parsing line: {e}")
            else:
                with lock:
                    console_logs.append("Serial port not open, stopping reader thread.")
                is_reading_serial = False
                break
            time.sleep(0.001) # Even smaller delay for faster data processing, adjust if needed
    except serial.SerialException as e:
        with lock:
            console_logs.append(f"[CRITICAL ERROR] Serial communication failed: {e}")
        is_reading_serial = False
    except Exception as e:
        with lock:
            console_logs.append(f"[FATAL ERROR] An unexpected error occurred in serial reader: {e}")
        is_reading_serial = False
    finally:
        if ser and ser.is_open:
            ser.close()
        with lock:
            console_logs.append("Serial reader thread stopped.")
        # Clear connected mics and data on disconnect
        connected_mics_set.clear()
        for mic_id in latest_mic_buffers:
            latest_mic_buffers[mic_id].clear()
        latest_mic_heatmap_values = {str(i): 0 for i in range(8)}


# --- API Endpoints ---

@app.route('/api/get-ports', methods=['GET'])
def get_ports():
    ports = [port.device for port in serial.tools.list_ports.comports()]
    return jsonify(ports=ports)

@app.route('/api/start-connection', methods=['POST'])
def start_connection():
    global ser, serial_reader_thread, is_reading_serial
    port = request.json.get('port')

    if ser and ser.is_open:
        return jsonify(is_connected=True, message=f"Already connected to {ser.port}")

    if not port:
        return jsonify(is_connected=False, message="No port selected"), 400

    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=1) # timeout=1 for readline()
        is_reading_serial = True
        # Start the serial reading in a separate thread
        serial_reader_thread = threading.Thread(target=read_from_serial)
        serial_reader_thread.daemon = True # Allow main program to exit even if thread is running
        serial_reader_thread.start()
        
        with lock:
            console_logs.append(f"Attempting to connect to {port}...")
        return jsonify(is_connected=True, message=f"Initiated connection to {port}")
    except serial.SerialException as e:
        with lock:
            console_logs.append(f"Failed to connect to {port}: {e}")
        return jsonify(is_connected=False, message=str(e)), 500
    except Exception as e:
        with lock:
            console_logs.append(f"An unexpected error occurred: {e}")
        return jsonify(is_connected=False, message=f"An unexpected error occurred: {e}"), 500

@app.route('/api/stop-connection', methods=['POST'])
def stop_connection():
    global ser, serial_reader_thread, is_reading_serial

    if ser and ser.is_open:
        is_reading_serial = False # Signal the thread to stop
        if serial_reader_thread and serial_reader_thread.is_alive():
            serial_reader_thread.join(timeout=3) # Wait for thread to finish (max 3 seconds)
        if ser.is_open: # Check again after join, as the thread might have closed it
            ser.close()
        ser = None
        with lock:
            console_logs.append("Connection closed.")
        # Clear all data buffers and connected mics on disconnect
        connected_mics_set.clear()
        for mic_id in latest_mic_buffers:
            latest_mic_buffers[mic_id].clear()
        global latest_mic_heatmap_values
        latest_mic_heatmap_values = {str(i): 0 for i in range(8)}
        return jsonify(status="success", message="Disconnected")
    else:
        return jsonify(status="error", message="Not connected"), 400

@app.route('/api/live-data/<string:mic_id>', methods=['GET'])
def get_live_data(mic_id):
    if not is_reading_serial:
        return jsonify(status="error", message="Not connected to hardware"), 400
    
    # mic_id will be 1-based from frontend, convert to 0-based for backend buffers
    try:
        mic_idx = int(mic_id) - 1
        if not (0 <= mic_idx <= 7):
            return jsonify(status="error", message="Invalid Mic ID"), 400
    except ValueError:
        return jsonify(status="error", message="Invalid Mic ID format"), 400

    time_series_data = []
    with lock: # Ensure consistent read from buffer
        time_series_data = list(latest_mic_buffers[str(mic_idx)]) # Get a copy
    # If no data for specific mic yet, fill with zeros to keep chart stable
    if not time_series_data:
        time_series_data = [0] * N_FFT
    elif len(time_series_data) < N_FFT:
        # Pad with zeros if not enough data yet
        time_series_data = [0] * (N_FFT - len(time_series_data)) + time_series_data
    
    # Compute FFT on the time series data
    fft_raw = np.abs(fft(time_series_data)[:N_FFT // 2]).tolist() # Convert to list
    
    return jsonify(status="success", 
                   time_series=time_series_data, 
                   fft_data=fft_raw,
                   freqs=FREQS,
                   mic_heatmap_values=latest_mic_heatmap_values
                   )

@app.route('/api/analysis/<string:mic_id>', methods=['GET'])
def get_analysis(mic_id):
    if not is_reading_serial:
        return jsonify(status="error", message="Not connected to hardware"), 400

    # mic_id will be 1-based from frontend, convert to 0-based for backend buffers
    try:
        mic_idx = int(mic_id) - 1
        if not (0 <= mic_idx <= 7):
            return jsonify(status="error", message="Invalid Mic ID"), 400
    except ValueError:
        return jsonify(status="error", message="Invalid Mic ID format"), 400

    time_series_data = []
    with lock:
        time_series_data = list(latest_mic_buffers[str(mic_idx)])
    
    if not time_series_data:
        return jsonify(status="success", analysis={
            "breath_pattern": "No data yet",
            "abnormalities": "N/A",
            "resp_rate": "N/A"
        })

    # --- More sophisticated analysis logic would go here ---
    # For demonstration, a very basic "analysis" based on FFT
    fft_vals = np.abs(fft(time_series_data)[:N_FFT // 2])
    
    # Find dominant frequency (excluding DC component and very high freqs)
    # Adjust frequency range based on what's expected for breath sounds (e.g., 5-50 Hz)
    dominant_freq = "N/A"
    if len(fft_vals) > 1 and FREQS:
        # Find index of max amplitude in a relevant frequency range (e.g., 5-500 Hz for breath sounds)
        min_freq_idx = np.searchsorted(FREQS, 5)
        max_freq_idx = np.searchsorted(FREQS, 500)
        
        relevant_fft_vals = fft_vals[min_freq_idx:max_freq_idx]
        relevant_freqs = FREQS[min_freq_idx:max_freq_idx]

        if len(relevant_fft_vals) > 0:
            peak_idx = np.argmax(relevant_fft_vals)
            dominant_freq = f"{relevant_freqs[peak_idx]:.2f} Hz"

    # Simple checks for abnormalities and breath pattern
    max_amplitude = np.max(np.abs(time_series_data))
    
    breath_pattern = "Normal"
    abnormalities = "None detected"
    resp_rate = f"{np.random.randint(12, 20)} breaths/min" # Placeholder

    if max_amplitude > 10000: # Arbitrary high threshold
        breath_pattern = "Loud / Strong"
    elif max_amplitude < 1000: # Arbitrary low threshold
        breath_pattern = "Shallow / Weak"

    if "Hz" in dominant_freq:
        freq_val = float(dominant_freq.split(' ')[0])
        if freq_val > 100: # Example: higher frequencies might indicate abnormal sounds
            abnormalities = "Possible adventitious sounds (e.g., wheezes, crackles)"
        elif freq_val < 20 and max_amplitude > 5000: # Example: very low frequency, high amplitude
             abnormalities = "Deep, slow breathing or potential obstruction"

    analysis_results = {
        "breath_pattern": breath_pattern,
        "abnormalities": abnormalities,
        "resp_rate": resp_rate,
        "dominant_frequency": dominant_freq,
        "max_amplitude": f"{max_amplitude:.2f}"
    }
    return jsonify(status="success", analysis=analysis_results)

@app.route('/api/console-data', methods=['GET'])
def get_console_data():
    with lock: # Read from console_logs with lock
        return jsonify(status="success", console=list(console_logs))

@app.route('/api/connected-mics', methods=['GET'])
def get_connected_mics():
    with lock: # Read from connected_mics_set with lock
        return jsonify(status="success", connected_mics=list(connected_mics_set))

@app.route('/api/heatmap-data', methods=['GET'])
def get_heatmap_data():
    if not is_reading_serial:
        return jsonify(status="error", message="Not connected to hardware"), 400
    
    with lock:
        # Convert dictionary to a 2x4 list structure as expected by your heatmap frontend
        # values[0:4] for row 0, values[4:8] for row 1
        heatmap_matrix = [
            [latest_mic_heatmap_values[str(i)] for i in range(4)],
            [latest_mic_heatmap_values[str(i)] for i in range(4, 8)]
        ]
    return jsonify(status="success", heatmap_data=heatmap_matrix)


# --- Serve the Frontend (Optional) ---
@app.route('/')
def index():
    return app.send_static_file('index.html')

if __name__ == '__main__':
    # Ensure a 'static' folder exists in the same directory as this script,
    # and your index.html is inside it for the @app.route('/') to work.
    app.run(debug=True, host='0.0.0.0', port=5000)