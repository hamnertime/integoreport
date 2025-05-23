# integoreport/main.py

import json
import os
import subprocess
import sys
from flask import Flask, render_template, redirect, url_for, jsonify, send_file, flash
import logging
import time
import requests
import datetime

# --- Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CLIENT_LIST_FILE = os.path.join(PROJECT_ROOT, "companies_list.json")
CLIENT_UPDATER_SCRIPT = os.path.join(PROJECT_ROOT, "utils", "client_updater.py")
FRESHSERVICE_PULLER_SCRIPT = os.path.join(PROJECT_ROOT, "data_pullers", "freshservice.py")
BUILD_REPORT_SCRIPT = os.path.join(PROJECT_ROOT, "build_report.py")
OUTPUT_REPORT_FILE = os.path.join(PROJECT_ROOT, "output_report.html")
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")
RAW_DATA_DIR = os.path.join(PROJECT_ROOT, "raw_data")
FS_TOKEN_FILE = os.path.join(PROJECT_ROOT, "token.txt")
MC_TOKEN_FILE = os.path.join(PROJECT_ROOT, "mail_token.txt")
MAILCHIMP_LIST_ID = "fa1002aff6"

COPY_REPORT_TO_EMAIL = "david@integotec.com"

SECRET_KEY = os.urandom(24)
REQUEST_TIMEOUT = 30

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [flask_app] - %(message)s')
app = Flask(__name__, template_folder=TEMPLATES_DIR)
app.secret_key = SECRET_KEY

def log_message_flask(message, is_error=False):
    if is_error: logging.error(message)
    else: logging.info(message)

def read_token(file_path, service_name="API"):
    try:
        abs_file_path = os.path.abspath(file_path)
        if not os.path.exists(abs_file_path):
             log_message_flask(f"Error: {service_name} Token file '{abs_file_path}' not found.", is_error=True); return None
        with open(abs_file_path, 'r') as f: api_key = f.read().strip()
        if not api_key:
            log_message_flask(f"Error: {service_name} Token file '{abs_file_path}' is empty.", is_error=True); return None
        return api_key
    except Exception as e:
        log_message_flask(f"Error reading {service_name} token file '{abs_file_path}': {e}", is_error=True); return None

def get_mailchimp_dc(api_key):
    parts = api_key.split('-')
    if len(parts) == 2: return parts[1]
    else: log_message_flask("Could not determine Mailchimp DC from API key.", is_error=True); return None

# *** MODIFIED send_report_via_mailchimp for single campaign ***
def send_report_via_mailchimp(mc_api_key, mc_dc, list_id, client_email, client_name, report_html_content, copy_to_email_address=None):
    if not all([mc_api_key, mc_dc, list_id, client_email]):
        log_message_flask("Mailchimp API key, DC, List ID, or client email missing.", is_error=True)
        return False, "Missing Mailchimp configuration or client email."

    base_mc_url = f"https://{mc_dc}.api.mailchimp.com/3.0"
    auth = ('anystring', mc_api_key)
    headers = {'Content-Type': 'application/json'}

    safe_client_name = "".join(c if c.isalnum() or c.isspace() else "_" for c in client_name)
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")

    campaign_title = f"Monthly Report for {safe_client_name} - {timestamp_str}"

    # Build segment conditions
    segment_conditions = [
        {"condition_type": "EmailAddress", "field": "EMAIL", "op": "is", "value": client_email}
    ]
    if copy_to_email_address and copy_to_email_address != client_email: # Add copy email if different
        segment_conditions.append(
            {"condition_type": "EmailAddress", "field": "EMAIL", "op": "is", "value": copy_to_email_address}
        )

    recipients_payload = {
        "list_id": list_id,
        "segment_opts": {
            "match": "any", # Use 'any' (OR logic) if including a copy address
            "conditions": segment_conditions
        }
    }
    if not copy_to_email_address or copy_to_email_address == client_email:
        recipients_payload["segment_opts"]["match"] = "all" # revert to 'all' if only one recipient

    campaign_payload = {
        "type": "regular",
        "recipients": recipients_payload,
        "settings": {
            "subject_line": f"Your Monthly Service Report: {client_name}",
            "title": campaign_title,
            "from_name": "IntegoReport (Integotec)",
            "reply_to": "support@integotec.com"
        }
    }
    campaign_id = None

    def get_error_response_text(e):
        if hasattr(e, 'response') and e.response is not None:
            try: return e.response.json()
            except json.JSONDecodeError: return e.response.text
        return "No response attribute or response is None."

    target_emails_log = f"{client_email}"
    if copy_to_email_address and copy_to_email_address != client_email:
        target_emails_log += f" and {copy_to_email_address}"

    try:
        log_message_flask(f"Creating Mailchimp campaign: {campaign_title} for {target_emails_log}")
        response = requests.post(f"{base_mc_url}/campaigns", auth=auth, headers=headers, json=campaign_payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        campaign_id = response.json().get("id")
        log_message_flask(f"Mailchimp campaign created with ID: {campaign_id} for {target_emails_log}")
    except requests.exceptions.RequestException as e:
        err_msg = f"MC campaign creation error ({target_emails_log}): {e}. Response: {get_error_response_text(e)}"
        log_message_flask(err_msg, is_error=True)
        return False, "Failed to create Mailchimp campaign."
    except Exception as e:
        log_message_flask(f"Unexpected error creating MC campaign ({target_emails_log}): {e}", is_error=True)
        return False, "Unexpected error creating Mailchimp campaign."

    if not campaign_id: return False, "Failed to get campaign ID."

    content_payload = {"html": report_html_content}
    try:
        log_message_flask(f"Setting content for MC campaign ID: {campaign_id}")
        response = requests.put(f"{base_mc_url}/campaigns/{campaign_id}/content", auth=auth, headers=headers, json=content_payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except Exception as e:
        err_msg = f"MC set content error ({campaign_id}): {e}. Response: {get_error_response_text(e) if isinstance(e, requests.exceptions.RequestException) else 'N/A'}"
        log_message_flask(err_msg, is_error=True)
        if campaign_id: requests.delete(f"{base_mc_url}/campaigns/{campaign_id}", auth=auth, timeout=REQUEST_TIMEOUT)
        return False, "Failed to set Mailchimp campaign content."

    try:
        log_message_flask(f"Sending MC campaign ID: {campaign_id} to {target_emails_log}")
        response = requests.post(f"{base_mc_url}/campaigns/{campaign_id}/actions/send", auth=auth, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        log_message_flask(f"Mailchimp campaign sent successfully to {target_emails_log}.")
    except Exception as e:
        err_msg = f"MC send campaign error ({campaign_id}): {e}. Response: {get_error_response_text(e) if isinstance(e, requests.exceptions.RequestException) else 'N/A'}"
        log_message_flask(err_msg, is_error=True)
        return False, f"Failed to send Mailchimp campaign to {target_emails_log}. Detail: {err_msg}"

    sleep_duration_before_delete = 15
    log_message_flask(f"Waiting {sleep_duration_before_delete}s before attempting to delete campaign {campaign_id}...")
    time.sleep(sleep_duration_before_delete)

    try:
        log_message_flask(f"Deleting MC campaign ID: {campaign_id}")
        requests.delete(f"{base_mc_url}/campaigns/{campaign_id}", auth=auth, timeout=REQUEST_TIMEOUT).raise_for_status()
        log_message_flask(f"Mailchimp campaign {campaign_id} deleted successfully.")
    except Exception as e:
        log_message_flask(f"MC delete campaign error ({campaign_id}): {e}. Response: {get_error_response_text(e) if isinstance(e, requests.exceptions.RequestException) else 'N/A'}", is_error=True)

    return True, f"Report sent via Mailchimp to {target_emails_log}."


# --- Helper Functions ---
def run_script(script_path, *args):
    python_executable = sys.executable; command = [python_executable, script_path] + list(args)
    log_message_flask(f"Running command: {' '.join(command)}")
    try:
        result = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
        if result.stdout: log_message_flask(f"Script {os.path.basename(script_path)} STDOUT:\n{result.stdout}")
        if result.returncode != 0:
            log_message_flask(f"Script {os.path.basename(script_path)} STDERR:\n{result.stderr}",is_error=True)
            return False, f"Error in {os.path.basename(script_path)}: {result.stderr[:500]}..."
        return True, "Script executed successfully."
    except Exception as e:
        log_message_flask(f"Unexpected error running {script_path}: {e}", is_error=True)
        return False, f"Unexpected error: {e}"

def load_client_data_from_json(client_id_to_find=None):
    if not os.path.exists(CLIENT_LIST_FILE):
        return None if client_id_to_find else {"clients": [], "retrieved_as": "Unknown"}
    try:
        with open(CLIENT_LIST_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
        if client_id_to_find:
            for client in data.get("clients", []):
                if str(client.get("id")) == str(client_id_to_find): return client
            return None
        return data
    except Exception as e:
        log_message_flask(f"Error loading {CLIENT_LIST_FILE}: {e}", is_error=True)
        return None if client_id_to_find else {"clients": [], "retrieved_as": "Unknown"}

def check_setup():
    issues = []
    if not os.path.exists(FS_TOKEN_FILE): issues.append(f"<b>CRITICAL:</b> `token.txt` (FS key) not found.")
    if not os.path.exists(MC_TOKEN_FILE): issues.append(f"Warning: `mail_token.txt` (MC key) not found. Mailchimp functions will fail.")
    for d in [TEMPLATES_DIR, RAW_DATA_DIR]:
        if not os.path.exists(d): os.makedirs(d); issues.append(f"Info: Created `{os.path.basename(d)}` directory.")
    return issues

def ensure_templates():
    index_template_path = os.path.join(TEMPLATES_DIR, "index.html")
    generating_template_path = os.path.join(TEMPLATES_DIR, "generating.html")
    dispatch_template_path = os.path.join(TEMPLATES_DIR, "dispatch_report.html")
    index_html = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>IntegoReport Dashboard</title><style>body{font-family:sans-serif;margin:20px;background-color:#f4f8fb;}h1,h2{color:#333;} table{border-collapse:collapse;width:100%;margin-bottom:20px;box-shadow: 0 2px 3px rgba(0,0,0,0.1);}th,td{border:1px solid #ddd;padding:10px 12px;text-align:left;} th{background-color:#007bff;color:white;font-weight:bold;}tr:nth-child(even){background-color:#f9f9f9;} tr:hover{background-color:#f1f1f1;}a,button{text-decoration:none;padding:8px 12px;border:none;background-color:#007bff;color:white;border-radius:4px;cursor:pointer;margin-right:5px;transition: background-color 0.2s ease;}a:hover,button:hover{background-color:#0056b3;} .update-btn{background-color:#28a745;}.update-btn:hover{background-color:#218838;}.btn-disabled{background-color:#secondary;color:#6c757d;cursor:not-allowed;opacity:0.65;}.error, .flash.error{color:red;border:1px solid red;padding:10px;margin-bottom:15px;background-color:#ffebee;}.warning{color:darkorange;border:1px solid orange;padding:10px;margin-bottom:15px;background-color:#fff3e0;}.flash.success{color:green;border:1px solid green;padding:10px;margin-bottom:15px;background-color:#e8f5e9;}.status-linked{color:green;} .status-to-add{color:#ff9800;font-weight:bold;}.status-no-contact, .status-not-found{color:#757575;font-style:italic;}</style></head><body><h1>IntegoReport Dashboard</h1>{% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category, message in messages %}<div class="flash {{ category }}">{{ message }}</div>{% endfor %}{% endif %}{% endwith %}{% if issues %}{% for issue in issues %}<p class="{% if 'CRITICAL' in issue %}error{% elif 'Warning' in issue %}warning{% else %}error{% endif %}">{{ issue | safe }}</p>{% endfor %}{% endif %}<form action="{{ url_for('update_clients') }}" method="post"><button type="submit" class="update-btn">Update Client List</button></form><h2>Client Overview</h2>{% if clients %}<table><thead><tr><th>Client ID</th><th>Client Name</th><th>Mailchimp Link Status</th><th>Action</th></tr></thead><tbody>{% for client in clients %}<tr><td>{{ client.id }}</td><td>{{ client.name }}</td><td>{% set is_linked = client.email and ("Linked" in client.mc_link_status) %}{% if is_linked %}<span class="status-linked">Linked: {{ client.email }} ({{ client.mc_link_status.replace("Linked (", "").replace(")", "") }})</span>{% elif client.mc_link_status == "To Add to Mailchimp" %}<span class="status-to-add">To Add: {{ client.fs_contact_to_link if client.fs_contact_to_link else 'Unknown' }}</span>{% elif client.mc_link_status == "No FS Contact to Link" %}<span class="status-no-contact">No FS Contact to Link</span>{% else %}<span class="status-not-found">{{ client.mc_link_status if client.mc_link_status else 'N/A' }}</span>{% endif %}</td><td>{% if is_linked %}<a href="{{ url_for('generate_report_for_dispatch', client_id=client.id) }}">Generate Report</a>{% else %}<button class="btn-disabled" disabled title="Link to Mailchimp email first">Generate Report</button>{% endif %}</td></tr>{% endfor %}</tbody></table>{% else %}<p>No clients found. Try updating list.</p>{% endif %}</body></html>"""
    generating_html = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Generating Report...</title><style>body{font-family:sans-serif;margin:20px;text-align:center}h1{color:#333}.spinner{border:8px solid #f3f3f3;border-top:8px solid #3498db;border-radius:50%;width:60px;height:60px;animation:spin 2s linear infinite;margin:20px auto}#status{margin-top:20px;font-weight:bold;color:#555}@keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}</style></head><body><h1>Generating Report for Client ID {{ client_id }}</h1><div class="spinner"></div><p id="status">Starting data pull... Please wait.</p><script>const statusElement = document.getElementById('status'); const clientId = {{ client_id }};window.onload = function() {statusElement.textContent = 'Fetching Freshservice data...';fetch(`/execute_report_generation/${clientId}`).then(response => { if (!response.ok) { throw new Error(`HTTP error! status: ${response.status}`); } return response.json(); }).then(data => {if (data.status === 'ok') { statusElement.textContent = 'Report generated! Preparing dispatch...'; window.location.href = data.dispatch_url; } else { statusElement.textContent = `Error: ${data.message}`; statusElement.style.color = 'red'; }}).catch(error => { console.error('Fetch error:', error); statusElement.textContent = `Failed: ${error}`; statusElement.style.color = 'red'; });};</script></body></html>"""
    dispatch_report_html = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Dispatch Report for {{ client.name if client else 'N/A' }}</title><style>body{font-family:sans-serif;margin:20px;background-color:#f4f8fb;display:flex;flex-direction:column;align-items:center;padding-top:40px;}.card{background-color:white;padding:30px 40px;border-radius:8px;box-shadow:0 4px 15px rgba(0,0,0,0.1);text-align:center;width:100%;max-width:500px;}h1{color:#004a99;margin-bottom:15px;} p{color:#333;margin-bottom:25px;font-size:1.1em;}.actions a, .actions button {display:inline-block;background-color:#007bff;color:white;padding:12px 20px;text-decoration:none;border-radius:5px;margin:10px;font-size:1em;border:none;cursor:pointer;transition:background-color 0.2s ease;}.actions a:hover, .actions button:hover {background-color:#0056b3;}.actions .view-btn{background-color:#6c757d;}.actions .view-btn:hover{background-color:#5a6268;}.back-link{margin-top:30px;color:#007bff;text-decoration:none;font-size:0.9em;}.flash.success{color:green;border:1px solid green;padding:10px;margin-bottom:15px;background-color:#e8f5e9;border-radius:4px;}.flash.error{color:red;border:1px solid red;padding:10px;margin-bottom:15px;background-color:#ffebee;border-radius:4px;}</style></head><body><div class="card">{% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}{% for category, message in messages %}<div class="flash {{ category }}">{{ message }}</div>{% endfor %}{% endif %}{% endwith %}{% if client %}<h1>Report Generated for {{ client.name }}</h1><p>Linked Email: <strong>{{ client.email if client.email else 'N/A (Cannot send email)' }}</strong></p><div class="actions"><form action="{{ url_for('send_report_email', client_id=client.id) }}" method="post" style="display:inline;"><button type="submit" {% if not client.email %}disabled title="No email linked for this client"{% endif %}>Send via Mailchimp</button></form><a href="{{ url_for('view_report_page') }}" target="_blank" class="view-btn">View in Browser</a></div>{% else %}<h1>Error</h1><p>Client details not found.</p>{% endif %}<a href="{{ url_for('index') }}" class="back-link">Back to Client List</a></div></body></html>"""
    def write_template_if_needed(path, content):
        write = True;
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f_read:
                    if f_read.read() == content: write = False
            except Exception as e: logging.warning(f"Error reading template {path}: {e}")
        if write:
            with open(path, 'w', encoding='utf-8') as f: f.write(content)
            log_message_flask(f"Created/Updated template: {path}")
    write_template_if_needed(index_template_path, index_html)
    write_template_if_needed(generating_template_path, generating_html)
    write_template_if_needed(dispatch_template_path, dispatch_report_html)

# --- Flask Routes ---
@app.route('/')
def index():
    issues = check_setup()
    full_data = load_client_data_from_json()
    clients = full_data.get("clients", []) if full_data else []
    return render_template('index.html', clients=clients, issues=issues)

@app.route('/update_clients', methods=['POST'])
def update_clients():
    log_message_flask("Attempting to update client list...")
    success, message = run_script(CLIENT_UPDATER_SCRIPT)
    if success: flash("Client list updated successfully!", "success")
    else: flash(f"Client list update failed: {message}", "error")
    return redirect(url_for('index'))

@app.route('/generate_report_for_dispatch/<client_id>')
def generate_report_for_dispatch(client_id):
    log_message_flask(f"Showing generation page for client ID: {client_id}")
    return render_template('generating.html', client_id=client_id)

@app.route('/execute_report_generation/<client_id>')
def execute_report_generation(client_id):
    log_message_flask(f"Executing report generation for client ID: {client_id}...")
    full_client_data_json = load_client_data_from_json()
    entity_type = "department"
    if full_client_data_json and full_client_data_json.get("retrieved_as"):
        retrieved_as = full_client_data_json.get("retrieved_as", "Departments").lower()
        if "companies" in retrieved_as: entity_type = "company"

    script_args = [str(client_id), "--entity_type", entity_type]
    success_pull, msg_pull = run_script(FRESHSERVICE_PULLER_SCRIPT, *script_args)
    if not success_pull:
        return jsonify({"status": "error", "message": f"Data pull failed: {msg_pull}"})

    success_build, msg_build = run_script(BUILD_REPORT_SCRIPT)
    if not success_build:
        return jsonify({"status": "error", "message": f"Report build failed: {msg_build}"})

    return jsonify({"status": "ok", "dispatch_url": url_for('dispatch_report', client_id=client_id)})

@app.route('/dispatch_report/<client_id>')
def dispatch_report(client_id):
    client = load_client_data_from_json(client_id_to_find=client_id)
    if not client:
        flash(f"Could not find client details for ID {client_id}.", "error")
        return redirect(url_for('index'))
    return render_template('dispatch_report.html', client=client)

# *** MODIFIED /send_report_email ROUTE for single campaign send ***
@app.route('/send_report_email/<client_id>', methods=['POST'])
def send_report_email(client_id):
    client = load_client_data_from_json(client_id_to_find=client_id)
    if not client or not client.get('email'):
        flash(f"Cannot send email: No email address linked for client ID {client_id}.", "error")
        return redirect(url_for('dispatch_report', client_id=client_id))

    if not os.path.exists(OUTPUT_REPORT_FILE):
        flash("Error: Report file not found. Please regenerate.", "error")
        return redirect(url_for('dispatch_report', client_id=client_id))

    mc_api_key = read_token(MC_TOKEN_FILE, "Mailchimp")
    mc_dc = get_mailchimp_dc(mc_api_key) if mc_api_key else None

    if not mc_api_key or not mc_dc:
        flash("Mailchimp API key or datacenter not configured. Cannot send email.", "error")
        return redirect(url_for('dispatch_report', client_id=client_id))

    try:
        with open(OUTPUT_REPORT_FILE, 'r', encoding='utf-8') as f:
            html_content = f.read()

        # Determine if a copy needs to be sent and to whom
        copy_email_address = COPY_REPORT_TO_EMAIL if COPY_REPORT_TO_EMAIL and COPY_REPORT_TO_EMAIL != client.get('email') else None

        success, message = send_report_via_mailchimp(
            mc_api_key, mc_dc, MAILCHIMP_LIST_ID,
            client.get('email'), client.get('name'), html_content,
            copy_to_email_address=copy_email_address # Pass the copy address
        )

        if success:
            flash(message, "success") # Message from send_report_via_mailchimp already includes target(s)
        else:
            flash(f"Failed to send report via Mailchimp: {message}", "error")

    except Exception as e:
        log_message_flask(f"Error preparing to send email via Mailchimp: {e}", is_error=True)
        flash(f"An unexpected error occurred: {e}", "error")

    return redirect(url_for('dispatch_report', client_id=client_id))

@app.route('/report')
def view_report_page():
    if not os.path.exists(OUTPUT_REPORT_FILE):
        flash("Report file not found. Please generate it first.", "error")
        return redirect(url_for('index'))
    return send_file(OUTPUT_REPORT_FILE, mimetype='text/html')

# --- Main Execution ---
if __name__ == '__main__':
    _ = check_setup()
    ensure_templates()
    log_message_flask("Starting Flask application...")
    app.run(debug=True, host='0.0.0.0', port=5000)
