# integoreport/main.py

import json
import os
import subprocess
import sys
from flask import Flask, render_template, redirect, url_for, jsonify, send_file
import logging

# --- Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CLIENT_LIST_FILE = os.path.join(PROJECT_ROOT, "companies_list.json")
CLIENT_UPDATER_SCRIPT = os.path.join(PROJECT_ROOT, "utils", "client_updater.py")
FRESHSERVICE_PULLER_SCRIPT = os.path.join(PROJECT_ROOT, "data_pullers", "freshservice.py")
BUILD_REPORT_SCRIPT = os.path.join(PROJECT_ROOT, "build_report.py")
OUTPUT_REPORT_FILE = os.path.join(PROJECT_ROOT, "output_report.html")
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates") # Explicitly define templates dir
RAW_DATA_DIR = os.path.join(PROJECT_ROOT, "raw_data")
TOKEN_FILE = os.path.join(PROJECT_ROOT, "token.txt")


# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Setup Flask App ---
app = Flask(__name__, template_folder=TEMPLATES_DIR) # Use defined templates_dir

# --- Helper Functions ---
def run_script(script_path, *args):
    """Runs a Python script using subprocess and logs its output."""
    python_executable = sys.executable
    command = [python_executable, script_path] + list(args)
    logging.info(f"Running command: {' '.join(command)}")
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False
        )
        if result.stdout: # Log stdout if it's not empty
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
        # The actual list of clients is under the "clients" key
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
        issues.append(f"<b>CRITICAL:</b> `token.txt` (Freshservice API key) not found in project root ({PROJECT_ROOT}).")
    if not os.path.exists(os.path.join(PROJECT_ROOT, "mail_token.txt")):
        issues.append(f"Warning: `mail_token.txt` (Mailchimp API key) not found. Mailchimp linking will be skipped.")
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
<style>
    body{font-family:sans-serif;margin:20px;background-color:#f4f8fb;}
    h1,h2{color:#333;}
    table{border-collapse:collapse;width:100%;margin-bottom:20px;box-shadow: 0 2px 3px rgba(0,0,0,0.1);}
    th,td{border:1px solid #ddd;padding:10px 12px;text-align:left;}
    th{background-color:#007bff;color:white;font-weight:bold;}
    tr:nth-child(even){background-color:#f9f9f9;}
    tr:hover{background-color:#f1f1f1;}
    a,button{text-decoration:none;padding:8px 12px;border:none;background-color:#007bff;color:white;border-radius:4px;cursor:pointer;margin-right:5px;transition: background-color 0.2s ease;}
    a:hover,button:hover{background-color:#0056b3;}
    .update-btn{background-color:#28a745;}.update-btn:hover{background-color:#218838;}
    .error{color:red;border:1px solid red;padding:10px;margin-bottom:15px;background-color:#ffebee;}
    .warning{color:darkorange;border:1px solid orange;padding:10px;margin-bottom:15px;background-color:#fff3e0;}
    .status-linked{color:green;}
    .status-to-add{color:#ff9800;font-weight:bold;}
    .status-no-contact{color:#757575;font-style:italic;}
    .status-not-found{color:#e53935;}
</style>
</head><body><h1>IntegoReport Dashboard</h1>
{% if issues %}{% for issue in issues %}<p class="{% if 'CRITICAL' in issue %}error{% elif 'Warning' in issue %}warning{% else %}error{% endif %}">{{ issue | safe }}</p>{% endfor %}{% endif %}
<form action="{{ url_for('update_clients') }}" method="post"><button type="submit" class="update-btn">Update Client List (with Mailchimp)</button></form>
<h2>Client Overview</h2>
{% if clients %}<table><thead>
    <tr><th>Client ID</th><th>Client Name</th><th>Mailchimp Link Status</th><th>Action</th></tr>
</thead><tbody>
{% for client in clients %}<tr>
    <td>{{ client.id }}</td>
    <td>{{ client.name }}</td>
    <td>
        {% if client.mc_link_status == "Linked (Prime Name)" or client.mc_link_status == "Linked (Head Name)" or "Linked (Domain" in client.mc_link_status %}
            <span class="status-linked">Linked: {{ client.email }} ({{ client.mc_link_status.replace("Linked (", "").replace(")", "") }})</span>
        {% elif client.mc_link_status == "To Add to Mailchimp" %}
            <span class="status-to-add">To Add: {{ client.fs_contact_to_link if client.fs_contact_to_link else 'Unknown Contact' }}</span>
        {% elif client.mc_link_status == "No FS Contact to Link" %}
            <span class="status-no-contact">No FS Contact to Link</span>
        {% else %}
            <span class="status-not-found">{{ client.mc_link_status if client.mc_link_status else 'N/A' }}</span>
        {% endif %}
    </td>
    <td><a href="{{ url_for('generate_report', client_id=client.id) }}">Generate Report</a></td>
</tr>{% endfor %}
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
            .then(response => { if (!response.ok) { throw new Error(`HTTP error! status: ${response.status}`); } return response.json(); })
            .then(data => {
                if (data.status === 'ok') { statusElement.textContent = 'Report generated! Redirecting...'; window.location.href = data.report_url; }
                else { statusElement.textContent = `Error: ${data.message}`; statusElement.style.color = 'red'; }
            })
            .catch(error => { console.error('Fetch error:', error); statusElement.textContent = `Failed to generate report. Check console/logs. Error: ${error}`; statusElement.style.color = 'red'; });
    }
    window.onload = runScripts;
</script></body></html>
"""

    def write_template_if_needed(path, content):
        write = True
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f_read:
                    if f_read.read() == content: write = False
            except Exception as e: logging.warning(f"Error reading existing template {path}: {e}")
        if write:
            with open(path, 'w', encoding='utf-8') as f: f.write(content)
            logging.info(f"Created/Updated template: {path}")
        else:
            logging.info(f"Template {path} is up-to-date.")

    write_template_if_needed(index_template_path, index_html)
    write_template_if_needed(generating_template_path, generating_html)


# --- Flask Routes ---
@app.route('/')
def index():
    issues = check_setup()
    clients = load_clients() # This now gets the list from data.get("clients", [])
    return render_template('index.html', clients=clients, issues=issues)

@app.route('/update_clients', methods=['POST'])
def update_clients():
    logging.info("Attempting to update client list...")
    success, message = run_script(CLIENT_UPDATER_SCRIPT)
    if not success:
        logging.error(f"Client update script failed: {message}")
        # Add flash message here for user feedback if desired
    return redirect(url_for('index'))

@app.route('/generate/<int:client_id>')
def generate_report(client_id):
    logging.info(f"Showing generation page for client ID: {client_id}")
    return render_template('generating.html', client_id=client_id)

@app.route('/run/<int:client_id>')
def run_generation_scripts(client_id):
    logging.info(f"Starting data pull for client ID: {client_id}...")
    # Determine the entity type from companies_list.json for freshservice.py
    client_list_data = load_clients() # Reload the client list
    entity_type = "department" # Default
    if os.path.exists(CLIENT_LIST_FILE):
        try:
            with open(CLIENT_LIST_FILE, 'r', encoding='utf-8') as f:
                full_data = json.load(f)
            retrieved_as = full_data.get("retrieved_as", "Departments").lower() # Departments or Companies
            if "companies" in retrieved_as:
                entity_type = "company"
        except Exception as e:
            logging.warning(f"Could not read entity type from {CLIENT_LIST_FILE}: {e}")


    script_args = [str(client_id), "--entity_type", entity_type]
    success_pull, msg_pull = run_script(FRESHSERVICE_PULLER_SCRIPT, *script_args)

    if not success_pull:
        logging.error(f"Freshservice pull failed for {client_id}: {msg_pull}")
        return jsonify({"status": "error", "message": f"Data pull failed: {msg_pull}"})

    logging.info(f"Starting report build for client ID: {client_id}...")
    success_build, msg_build = run_script(BUILD_REPORT_SCRIPT)
    if not success_build:
        logging.error(f"Report build failed for {client_id}: {msg_build}")
        return jsonify({"status": "error", "message": f"Report build failed: {msg_build}"})

    logging.info(f"Report generation complete for client ID: {client_id}.")
    return jsonify({"status": "ok", "report_url": url_for('view_report')})

@app.route('/report')
def view_report():
    if not os.path.exists(OUTPUT_REPORT_FILE):
        logging.error("Output report file not found.")
        return "Error: Report file not found. Please try generating it again.", 404
    try:
        return send_file(OUTPUT_REPORT_FILE, mimetype='text/html')
    except Exception as e:
        logging.error(f"Error sending report file: {e}")
        return "Error displaying report.", 500

# --- Main Execution ---
if __name__ == '__main__':
    _ = check_setup()
    ensure_templates()
    logging.info("Starting Flask application...")
    app.run(debug=True, host='0.0.0.0', port=5000)
