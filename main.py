# integoreport/main.py

import json
import os
import subprocess
import sys
from flask import Flask, render_template, redirect, url_for, jsonify, send_file, render_template_string
import logging

# --- Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CLIENT_LIST_FILE = os.path.join(PROJECT_ROOT, "companies_list.json")
CLIENT_UPDATER_SCRIPT = os.path.join(PROJECT_ROOT, "utils", "client_updater.py")
FRESHSERVICE_PULLER_SCRIPT = os.path.join(PROJECT_ROOT, "data_pullers", "freshservice.py")
BUILD_REPORT_SCRIPT = os.path.join(PROJECT_ROOT, "build_report.py")
OUTPUT_REPORT_FILE = os.path.join(PROJECT_ROOT, "output_report.html")
RAW_DATA_DIR = os.path.join(PROJECT_ROOT, "raw_data")
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")
TOKEN_FILE = os.path.join(PROJECT_ROOT, "token.txt") # Check for token

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Setup Flask App ---
app = Flask(__name__, template_folder=TEMPLATES_DIR)

# --- Helper Functions ---

def run_script(script_path, *args):
    """Runs a Python script using subprocess and logs its output."""
    python_executable = sys.executable # Use the same python interpreter
    command = [python_executable, script_path] + list(args)
    logging.info(f"Running command: {' '.join(command)}")
    try:
        # Use Popen for better control/logging if needed, but run is simpler for now
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False # Set to False to handle errors manually
        )
        logging.info(f"Script {os.path.basename(script_path)} STDOUT:\n{result.stdout}")
        if result.returncode != 0:
            logging.error(f"Script {os.path.basename(script_path)} STDERR:\n{result.stderr}")
            return False, f"Error running {os.path.basename(script_path)}: {result.stderr[:500]}..."
        return True, "Script executed successfully."

    except FileNotFoundError:
        logging.error(f"Error: Script not found at {script_path}")
        return False, f"Error: Script not found at {script_path}"
    except Exception as e:
        logging.error(f"An unexpected error occurred while running {script_path}: {e}")
        return False, f"An unexpected error occurred: {e}"

def load_clients():
    """Loads the client list from the JSON file."""
    if not os.path.exists(CLIENT_LIST_FILE):
        return []
    try:
        with open(CLIENT_LIST_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("clients", [])
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from {CLIENT_LIST_FILE}")
        return []
    except Exception as e:
        logging.error(f"Error loading {CLIENT_LIST_FILE}: {e}")
        return []

def check_setup():
    """Checks if essential files and directories exist."""
    issues = []
    if not os.path.exists(TOKEN_FILE):
        issues.append(f"<b>CRITICAL:</b> `token.txt` not found. Please create it in the project root ({PROJECT_ROOT}) with your Freshservice API key.")
    if not os.path.exists(CLIENT_UPDATER_SCRIPT):
        issues.append(f"Warning: `utils/client_updater.py` not found.")
    if not os.path.exists(FRESHSERVICE_PULLER_SCRIPT):
        issues.append(f"Warning: `data_pullers/freshservice.py` not found.")
    if not os.path.exists(BUILD_REPORT_SCRIPT):
        issues.append(f"Warning: `build_report.py` not found.")
    if not os.path.exists(TEMPLATES_DIR):
         issues.append(f"Info: `templates` directory not found. Creating it.")
         os.makedirs(TEMPLATES_DIR)
    if not os.path.exists(RAW_DATA_DIR):
         issues.append(f"Info: `raw_data` directory not found. Creating it.")
         os.makedirs(RAW_DATA_DIR)
    return issues


def ensure_templates():
    """Ensures basic templates exist."""
    index_template_path = os.path.join(TEMPLATES_DIR, "index.html")
    generating_template_path = os.path.join(TEMPLATES_DIR, "generating.html")

    index_html = """
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>IntegoReport Dashboard</title>
<style>body{font-family:sans-serif;margin:20px}h1,h2{color:#333}table{border-collapse:collapse;width:100%;margin-bottom:20px}th,td{border:1px solid #ddd;padding:8px;text-align:left}th{background-color:#f0f0f0}a,button{text-decoration:none;padding:8px 12px;border:none;background-color:#007bff;color:white;border-radius:4px;cursor:pointer;margin-right:5px;}a:hover,button:hover{background-color:#0056b3}.update-btn{background-color:#28a745}.update-btn:hover{background-color:#218838}.error{color:red;border:1px solid red;padding:10px;margin-bottom:15px;}.warning{color:orange;border:1px solid orange;padding:10px;margin-bottom:15px;}</style>
</head><body><h1>IntegoReport Dashboard</h1>
{% if issues %}<h2>Setup Issues:</h2>{% for issue in issues %}<p class="{% if 'CRITICAL' in issue %}error{% else %}warning{% endif %}">{{ issue | safe }}</p>{% endfor %}{% endif %}
<form action="{{ url_for('update_clients') }}" method="post"><button type="submit" class="update-btn">Update Client List</button></form>
<h2>Select Client to Generate Report</h2>
{% if clients %}<table><thead><tr><th>Client ID</th><th>Client Name</th><th>Action</th></tr></thead><tbody>
{% for client in clients %}<tr><td>{{ client.id }}</td><td>{{ client.name }}</td>
<td><a href="{{ url_for('generate_report', client_id=client.id) }}">Generate Report</a></td></tr>{% endfor %}
</tbody></table>{% else %}<p>No clients found. Try updating the client list.</p>{% endif %}</body></html>
"""

    generating_html = """
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Generating Report...</title>
<style>body{font-family:sans-serif;margin:20px;text-align:center}h1{color:#333}.spinner{border:8px solid #f3f3f3;border-top:8px solid #3498db;border-radius:50%;width:60px;height:60px;animation:spin 2s linear infinite;margin:20px auto}#status{margin-top:20px;font-weight:bold;color:#555}@keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}</style>
</head><body><h1>Generating Report for Client ID {{ client_id }}</h1><div class="spinner"></div><p id="status">Starting data pull... Please wait.</p>
<script>
    const statusElement = document.getElementById('status');
    const clientId = {{ client_id }};

    function runScripts() {
        fetch(`/run/${clientId}`)
            .then(response => {
                if (!response.ok) { throw new Error(`HTTP error! status: ${response.status}`); }
                return response.json();
            })
            .then(data => {
                if (data.status === 'ok') {
                    statusElement.textContent = 'Report generated! Redirecting...';
                    window.location.href = data.report_url;
                } else {
                    statusElement.textContent = `Error: ${data.message}`;
                    statusElement.style.color = 'red';
                }
            })
            .catch(error => {
                console.error('Fetch error:', error);
                statusElement.textContent = `Failed to generate report. Check console/logs. Error: ${error}`;
                statusElement.style.color = 'red';
            });
    }
    // Start the process immediately on page load
    window.onload = runScripts;
</script></body></html>
"""
    if not os.path.exists(index_template_path):
        with open(index_template_path, 'w', encoding='utf-8') as f: f.write(index_html)
        logging.info(f"Created {index_template_path}")
    if not os.path.exists(generating_template_path):
        with open(generating_template_path, 'w', encoding='utf-8') as f: f.write(generating_html)
        logging.info(f"Created {generating_template_path}")


# --- Flask Routes ---

@app.route('/')
def index():
    """Displays the main page with client list and update button."""
    issues = check_setup()
    clients = load_clients()
    return render_template('index.html', clients=clients, issues=issues)

@app.route('/update_clients', methods=['POST'])
def update_clients():
    """Runs the client updater script."""
    logging.info("Attempting to update client list...")
    success, message = run_script(CLIENT_UPDATER_SCRIPT)
    if not success:
        logging.error(f"Client update failed: {message}")
        # Optionally: Add flash messaging to show errors on the index page
    return redirect(url_for('index'))

@app.route('/generate/<int:client_id>')
def generate_report(client_id):
    """Shows the 'Generating...' page, which triggers the actual script run."""
    logging.info(f"Showing generation page for client ID: {client_id}")
    return render_template('generating.html', client_id=client_id)

@app.route('/run/<int:client_id>')
def run_generation_scripts(client_id):
    """Runs the data puller and report builder scripts."""
    logging.info(f"Starting data pull for client ID: {client_id}...")
    success, message = run_script(FRESHSERVICE_PULLER_SCRIPT, str(client_id))
    if not success:
        logging.error(f"Freshservice pull failed for {client_id}: {message}")
        return jsonify({"status": "error", "message": f"Data pull failed: {message}"})

    logging.info(f"Starting report build for client ID: {client_id}...")
    success, message = run_script(BUILD_REPORT_SCRIPT)
    if not success:
        logging.error(f"Report build failed for {client_id}: {message}")
        return jsonify({"status": "error", "message": f"Report build failed: {message}"})

    logging.info(f"Report generation complete for client ID: {client_id}.")
    return jsonify({"status": "ok", "report_url": url_for('view_report')})

@app.route('/report')
def view_report():
    """Displays the generated HTML report."""
    if not os.path.exists(OUTPUT_REPORT_FILE):
        logging.error("Output report file not found.")
        return "Error: Report file not found. Please try generating it again.", 404
    try:
        # Use send_file to ensure correct content type and handling
        return send_file(OUTPUT_REPORT_FILE, mimetype='text/html')
    except Exception as e:
        logging.error(f"Error sending report file: {e}")
        return "Error displaying report.", 500

# --- Main Execution ---
if __name__ == '__main__':
    _ = check_setup() # Run check on startup
    ensure_templates() # Ensure templates exist
    logging.info("Starting Flask application...")
    # Note: For production, use a WSGI server like Gunicorn or uWSGI
    app.run(debug=True, host='0.0.0.0', port=5000)
