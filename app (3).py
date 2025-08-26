from flask import Flask, render_template, request, jsonify, session, Response
from flask_cors import CORS
import serial
import serial.tools.list_ports
import threading
import time
import json
import random
import logging
from datetime import datetime
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'beta_one_secret_key_2023'
app.config['SESSION_TYPE'] = 'filesystem'
CORS(app)

# Mock user database (in production, use a real database with hashed passwords)
users = {
    "beta": "beta1"
}

# Global state
serial_connection = None
serial_thread = None
stop_thread = False
connected_mics = set()

# Mic to lung region mapping
mic_to_region = {
    "Mic 1": "Left Upper Lobe (Anterior)",
    "Mic 2": "Right Upper Lobe (Anterior)",
    "Mic 3": "Left Upper Lobe (Posterior)",
    "Mic 4": "Right Upper Lobe (Posterior)",
    "Mic 5": "Left Lower Lobe (Anterior)",
    "Mic 6": "Right Middle Lobe",
    "Mic 7": "Left Lower Lobe (Posterior)",
    "Mic 8": "Right Lower Lobe (Posterior)"
}

# Simulated data generation
def generate_waveform_data():
    """Generate simulated waveform data"""
    base = time.time()
    return [random.uniform(-1, 1) for _ in range(50)]

def generate_fft_data():
    """Generate simulated FFT data"""
    return [random.expovariate(1.5) * (1 - i/50) for i in range(50)]

def generate_heatmap_data():
    """Generate simulated heatmap data"""
    return {f"Mic {i+1}": random.randint(0, 100) for i in range(8)}

def generate_analysis_data():
    """Generate simulated analysis data"""
    patterns = ["Normal", "Shallow", "Deep", "Irregular"]
    return {
        "breath_pattern": random.choice(patterns),
        "respiratory_rate": random.randint(12, 20),
        "dominant_frequency": random.randint(200, 280),
        "lung_capacity": random.randint(80, 95)
    }

# Serial communication functions
def get_available_ports():
    """Get list of available serial ports"""
    ports = serial.tools.list_ports.comports()
    return [port.device for port in ports]

def read_serial_data():
    """Thread function to read data from serial port"""
    global stop_thread, serial_connection, connected_mics
    
    while not stop_thread and serial_connection and serial_connection.is_open:
        try:
            # Simulate reading data from serial port
            # In a real implementation, this would read actual data
            time.sleep(0.1)
            
            # Randomly update mic connectivity
            if random.random() < 0.05:  # 5% chance to change connectivity
                mic_id = f"Mic {random.randint(1, 8)}"
                if mic_id in connected_mics:
                    connected_mics.remove(mic_id)
                    logger.info(f"{mic_id} disconnected")
                else:
                    connected_mics.add(mic_id)
                    logger.info(f"{mic_id} connected")
                    
        except Exception as e:
            logger.error(f"Error reading serial data: {e}")
            time.sleep(1)

def connect_serial(port):
    """Connect to serial port"""
    global serial_connection, serial_thread, stop_thread
    
    try:
        # In a real implementation, you would actually connect to the port
        # serial_connection = serial.Serial(port, baudrate=115200, timeout=1)
        
        # For simulation, we'll just set a flag
        serial_connection = type('MockSerial', (), {'is_open': True})()
        
        # Start thread to read serial data
        stop_thread = False
        serial_thread = threading.Thread(target=read_serial_data)
        serial_thread.daemon = True
        serial_thread.start()
        
        # Initialize with some connected mics
        global connected_mics
        connected_mics = {f"Mic {i+1}" for i in range(4)}  # First 4 mics connected
        
        return True, "Connection successful"
    except Exception as e:
        return False, f"Connection failed: {str(e)}"

def disconnect_serial():
    """Disconnect from serial port"""
    global serial_connection, stop_thread
    
    if serial_connection:
        stop_thread = True
        # In a real implementation: serial_connection.close()
        serial_connection = None
        return True, "Disconnected successfully"
    return False, "Not connected"

# API Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if username in users and users[username] == password:
        session['logged_in'] = True
        session['username'] = username
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Invalid credentials'})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    return jsonify({'success': True})

@app.route('/api/check_session')
def check_session():
    if session.get('logged_in'):
        return jsonify({'logged_in': True, 'username': session.get('username')})
    return jsonify({'logged_in': False})

@app.route('/api/ports')
def get_ports():
    ports = get_available_ports()
    return jsonify(ports)

@app.route('/api/connect', methods=['POST'])
def connect():
    data = request.get_json()
    port = data.get('port')
    
    if not port:
        return jsonify({'success': False, 'error': 'No port specified'})
    
    success, message = connect_serial(port)
    return jsonify({'success': success, 'message': message})

@app.route('/api/disconnect', methods=['POST'])
def disconnect():
    success, message = disconnect_serial()
    return jsonify({'success': success, 'message': message})

@app.route('/api/connection_status')
def connection_status():
    global serial_connection
    connected = serial_connection is not None and serial_connection.is_open
    return jsonify({'connected': connected})

@app.route('/api/mic_status')
def mic_status():
    global connected_mics
    status = {mic: mic in connected_mics for mic in [f"Mic {i+1}" for i in range(8)]}
    return jsonify(status)

@app.route('/api/start_recording', methods=['POST'])
def start_recording():
    # In a real implementation, this would start recording from the device
    return jsonify({'success': True, 'message': 'Recording started'})

@app.route('/api/stop_recording', methods=['POST'])
def stop_recording():
    # In a real implementation, this would stop recording
    return jsonify({'success': True, 'message': 'Recording stopped'})

@app.route('/api/stream/waveform')
def stream_waveform():
    def generate():
        while True:
            data = generate_waveform_data()
            yield f"data: {json.dumps({'waveform': data})}\n\n"
            time.sleep(0.1)
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/stream/fft')
def stream_fft():
    def generate():
        while True:
            data = generate_fft_data()
            yield f"data: {json.dumps({'fft': data})}\n\n"
            time.sleep(0.1)
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/stream/heatmap')
def stream_heatmap():
    def generate():
        while True:
            data = generate_heatmap_data()
            yield f"data: {json.dumps({'heatmap': data})}\n\n"
            time.sleep(1)
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/stream/analysis')
def stream_analysis():
    def generate():
        while True:
            data = generate_analysis_data()
            yield f"data: {json.dumps({'analysis': data})}\n\n"
            time.sleep(2)
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/stream/console')
def stream_console():
    def generate():
        messages = [
            "System initialized",
            "Diagnostic modules loaded",
            "Waiting for hardware connection...",
            "Hardware connected",
            "Calibrating sensors...",
            "Sensors calibrated successfully",
            "Monitoring lung sounds..."
        ]
        
        for message in messages:
            yield f"data: {json.dumps({'message': message})}\n\n"
            time.sleep(1)
        
        while True:
            # Simulate occasional status messages
            if random.random() < 0.1:
                status_msg = f"Status update: {datetime.now().strftime('%H:%M:%S')}"
                yield f"data: {json.dumps({'message': status_msg})}\n\n"
            time.sleep(5)
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/lung_regions')
def get_lung_regions():
    return jsonify(mic_to_region)

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    
    # Save the HTML file to templates
    with open('templates/index.html', 'w') as f:
        # Write your HTML content here
        f.write('''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BETA ONE - Advanced Lung Diagnostic System</title>
    <!-- Your HTML content here -->
</head>
<body>
    <!-- Your HTML content here -->
</body>
</html>''')
    
    app.run(debug=True, port=5000, threaded=True)
