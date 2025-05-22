# integoreport/build_report.py

import json
import os
import glob
import datetime
from dateutil.parser import isoparse # For parsing ISO 8601 date strings
from jinja2 import Environment, FileSystemLoader

# --- Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
RAW_DATA_DIR = os.path.join(PROJECT_ROOT, "raw_data")
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")
OUTPUT_HTML_FILE = os.path.join(PROJECT_ROOT, "output_report.html")

def log_message(message, level="INFO"):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] [build_report] {message}")

def format_datetime_filter(value, format_string="%b %d, %Y %H:%M"):
    if not value: return "N/A" # Modified to return N/A for None/empty
    try:
        dt_obj = isoparse(str(value))
        return dt_obj.strftime(format_string)
    except (ValueError, TypeError): return str(value)

def format_date_filter(value, format_string="%b %d, %Y"):
    if not value: return "N/A" # Modified to return N/A for None/empty
    try:
        dt_obj = isoparse(str(value))
        return dt_obj.strftime(format_string)
    except (ValueError, TypeError): return str(value)

def find_client_data_file(raw_data_path):
    log_message(f"Searching for client data files in: {raw_data_path}")
    search_pattern = os.path.join(raw_data_path, "freshservice_*.json")
    files = glob.glob(search_pattern)
    if not files:
        log_message("No client data files found.", level="ERROR"); return None
    if len(files) > 1:
        try:
            files.sort(key=os.path.getmtime, reverse=True)
            log_message(f"Multiple files found. Using newest: {files[0]}", level="WARNING")
        except Exception as e:
            log_message(f"Error sorting files ({e}), using first: {files[0]}", level="WARNING")
    log_message(f"Found data file: {files[0]}")
    return files[0]

def load_client_data(file_path):
    log_message(f"Loading client data from: {file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
        log_message("Client data loaded successfully.")
        # if data and 'tickets' in data and data['tickets']: # Keep for first run if needed
        #     log_message(f"Sample of first ticket: {json.dumps(data['tickets'][0], indent=2, default=str)}")
        return data
    except Exception as e:
        log_message(f"Error loading/parsing {file_path}: {e}", level="ERROR")
    return None

def format_duration(seconds):
    if seconds is None or not isinstance(seconds, (int, float)) or seconds < 0:
        return "N/A"
    days, remainder = divmod(int(seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts = []
    if days > 0: parts.append(f"{days}d")
    if hours > 0: parts.append(f"{hours}h")
    # Show minutes if it's the only unit, or if there are other units, or if it's exactly 0s show 0m
    if minutes > 0 or (days == 0 and hours == 0): parts.append(f"{minutes}m")
    return " ".join(parts) if parts else ("0m" if seconds == 0 else "N/A")


def calculate_ticket_stats(tickets_data):
    log_message(f"Calculating stats for {len(tickets_data)} tickets.")
    if not tickets_data:
        return {"total_tickets": 0, "closed_tickets": 0, "open_tickets": 0,
                "tickets_by_type": {}, "tickets_by_priority": {},
                "total_resolution_seconds_for_avg": 0, "resolved_ticket_count_for_avg": 0,
                "average_resolution_time_str": "N/A"}

    total_tickets = len(tickets_data)
    closed_or_resolved_tickets_count = 0
    tickets_by_type = {}
    tickets_by_priority = {}
    total_resolution_seconds = 0
    resolved_ticket_count_for_avg = 0

    for i, ticket in enumerate(tickets_data):
        status_text = ticket.get('status_text', "Unknown").lower()
        priority_text = ticket.get('priority_text', "Unknown")
        ticket_type = ticket.get('type', 'Unknown')

        if i < 1:
             log_message(f"Detailed ticket for stats calc (ID {ticket.get('id')}): {json.dumps(ticket, indent=2, default=str)}")

        tickets_by_type[ticket_type] = tickets_by_type.get(ticket_type, 0) + 1
        tickets_by_priority[priority_text] = tickets_by_priority.get(priority_text, 0) + 1
        is_resolved_or_closed = "closed" in status_text or "resolved" in status_text

        if is_resolved_or_closed:
            closed_or_resolved_tickets_count += 1
            res_time_secs = None
            ticket_stats_obj = ticket.get('stats', {}) # Ensure stats object exists

            if ticket_stats_obj.get('resolution_time_in_secs') is not None:
                res_time_secs = ticket_stats_obj['resolution_time_in_secs']
                # log_message(f"Ticket {ticket.get('id')}: Using stats.resolution_time_in_secs: {res_time_secs}s ({format_duration(res_time_secs)})")
            else:
                # Fallback to manual calculation using resolved_at and created_at
                # Prioritize main ticket.resolved_at, then stats.resolved_at, then main ticket.closed_at, then stats.closed_at
                resolved_date_str = ticket.get('resolved_at') or \
                                    ticket_stats_obj.get('resolved_at') or \
                                    ticket.get('closed_at') or \
                                    ticket_stats_obj.get('closed_at')
                created_date_str = ticket.get('created_at')

                if resolved_date_str and created_date_str:
                    try:
                        resolved_at_dt = isoparse(resolved_date_str)
                        created_at_dt = isoparse(created_date_str)
                        if (resolved_at_dt.tzinfo is None and created_at_dt.tzinfo is not None) or \
                           (resolved_at_dt.tzinfo is not None and created_at_dt.tzinfo is None):
                            if resolved_at_dt.tzinfo is None: resolved_at_dt = resolved_at_dt.replace(tzinfo=datetime.timezone.utc)
                            if created_at_dt.tzinfo is None: created_at_dt = created_at_dt.replace(tzinfo=datetime.timezone.utc)
                            log_message(f"Ticket {ticket.get('id')}: Mixed naive/aware datetimes for resolution. Standardized to UTC for calc.", level="WARNING")

                        if resolved_at_dt >= created_at_dt: # Ensure resolved is not before created
                            duration_delta = resolved_at_dt - created_at_dt
                            res_time_secs = duration_delta.total_seconds()
                            # log_message(f"Ticket {ticket.get('id')}: Calc duration from '{resolved_date_str}' & '{created_date_str}': {res_time_secs}s ({format_duration(res_time_secs)})")
                        else:
                            log_message(f"Ticket {ticket.get('id')}: resolved_at ('{resolved_date_str}') is before created_at ('{created_date_str}'). Skipping duration calc.", level="WARNING")
                    except Exception as e:
                        log_message(f"Ticket {ticket.get('id')}: Error parsing dates '{resolved_date_str}', '{created_date_str}' for resolution: {e}", level="WARNING")
                else:
                    log_message(f"Ticket {ticket.get('id')} is {status_text} but missing created_at or any resolved/closed_at date for calc.", level="WARNING")

            if res_time_secs is not None and res_time_secs >= 0:
                total_resolution_seconds += res_time_secs
                resolved_ticket_count_for_avg += 1
            elif is_resolved_or_closed:
                 log_message(f"Ticket {ticket.get('id')} is {status_text} but resolution time could not be determined (res_time_secs: {res_time_secs}).", level="WARNING")

    average_resolution_time_str = "N/A"
    if resolved_ticket_count_for_avg > 0:
        avg_seconds = total_resolution_seconds / resolved_ticket_count_for_avg
        average_resolution_time_str = format_duration(avg_seconds)
        log_message(f"Average resolution time: {avg_seconds:.0f}s = {average_resolution_time_str} over {resolved_ticket_count_for_avg} tickets.")
    else:
        log_message("No tickets with valid resolution time found for average.")

    stats = {
        "total_tickets": total_tickets, "closed_tickets": closed_or_resolved_tickets_count,
        "open_tickets": total_tickets - closed_or_resolved_tickets_count,
        "tickets_by_type": tickets_by_type, "tickets_by_priority": tickets_by_priority,
        "total_resolution_seconds_for_avg": total_resolution_seconds,
        "resolved_ticket_count_for_avg": resolved_ticket_count_for_avg,
        "average_resolution_time_str": average_resolution_time_str
    }
    log_message(f"Final Calculated stats: {json.dumps(stats, indent=2)}")
    return stats

def render_html_report(client_info, tickets_data, calculated_stats):
    log_message("Rendering HTML report...")
    if not os.path.exists(TEMPLATES_DIR):
        log_message(f"Templates directory '{TEMPLATES_DIR}' missing!", level="ERROR")
        return f"<html><body><h1>Error: Template directory missing.</h1></body></html>"
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    env.filters['format_duration'] = format_duration
    env.filters['format_datetime'] = format_datetime_filter
    env.filters['format_date'] = format_date_filter
    template_name = 'email_report_template.html'
    try:
        template = env.get_template(template_name)
    except Exception as e:
        log_message(f"Error loading template '{template_name}': {e}", level="ERROR")
        return f"<html><body><h1>Error: Template '{template_name}' missing.</h1></body></html>"
    report_data = {
        "client_info": client_info, "tickets": tickets_data if tickets_data else [],
        "stats": calculated_stats, "generation_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    html_output = template.render(report_data)
    log_message("HTML report rendered successfully.")
    return html_output

def main():
    log_message("Starting report generation process...")
    client_data_file = find_client_data_file(RAW_DATA_DIR)
    if not client_data_file: log_message("Exiting: No data file.", level="CRITICAL"); return
    data = load_client_data(client_data_file)
    if not data: log_message("Exiting: Failed to load data.", level="CRITICAL"); return
    client_info = data.get('client_info', {})
    tickets_data = data.get('tickets', [])
    if not client_info.get('id'):
        try:
            filename_base = os.path.basename(client_data_file)
            parts = filename_base.replace('freshservice_', '').split('.')
            inferred_id_str = parts[0]
            if inferred_id_str.isdigit(): client_info['id'] = int(inferred_id_str)
            else: client_info['id'] = inferred_id_str
            log_message(f"Inferred client ID: {client_info['id']}", level="WARNING")
        except Exception as e:
            log_message(f"Error inferring client ID: {e}", level="ERROR")
    if not client_info.get('name') and client_info.get('id'): client_info['name'] = f"Client ID {client_info['id']}"
    elif not client_info.get('name'): client_info['name'] = "Unknown"; client_info['id'] = "Unknown"
    log_message(f"Processing report for: {client_info.get('name')} (ID: {client_info.get('id')})")
    calculated_stats = calculate_ticket_stats(tickets_data)
    html_content = render_html_report(client_info, tickets_data, calculated_stats)
    if html_content:
        try:
            with open(OUTPUT_HTML_FILE, 'w', encoding='utf-8') as f: f.write(html_content)
            log_message(f"HTML report saved to: {OUTPUT_HTML_FILE}")
        except Exception as e:
            log_message(f"Error saving HTML: {e}", level="ERROR")
    log_message("Report generation process finished.")

if __name__ == "__main__":
    if not os.path.exists(TEMPLATES_DIR):
        os.makedirs(TEMPLATES_DIR); log_message(f"Created: {TEMPLATES_DIR}")
    default_template_path = os.path.join(TEMPLATES_DIR, "email_report_template.html")
    log_message(f"Ensuring default template at '{default_template_path}'.")
    # --- UPDATED TEMPLATE LOGIC ---
    basic_template_content = """
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Service Report for {{ client_info.name }}</title>
<style>body{font-family:sans-serif;margin:20px}h1,h2,h3{color:#333}table{border-collapse:collapse;width:100%;margin-bottom:20px}th,td{border:1px solid #ddd;padding:8px;text-align:left}th{background-color:#f0f0f0}.container{max-width:800px;margin:auto}.footer{font-size:.8em;color:#777;margin-top:30px;text-align:center}</style>
</head><body><div class="container"><h1>Service Report</h1><h2>Client: {{ client_info.name }} (ID: {{ client_info.id }})</h2>
<p><strong>Report Period:</strong> {{ client_info.report_period_start }} - {{ client_info.report_period_end }}</p>
<p><strong>Report Generated:</strong> {{ generation_date }}</p><h3>Client Details:</h3><ul>
<li><strong>Client Type:</strong> {{ client_info.client_type | default('N/A') }}</li>
<li><strong>Main Number:</strong> {{ client_info.company_main_number | default('N/A') }}</li>
<li><strong>Domains:</strong> {{ client_info.domains | join(', ') if client_info.domains else 'N/A' }}</li>
<li><strong>Company Head:</strong> {{ client_info.company_head_name | default('N/A') }}</li>
<li><strong>Prime User:</strong> {{ client_info.prime_user_name | default('N/A') }}</li>
<li><strong>Company Start Date:</strong> {{ client_info.company_start_date | format_date if client_info.company_start_date else 'N/A' }}</li></ul>
<h2>Ticket Summary Statistics</h2><table>
<tr><td>Total Tickets in Period:</td><td>{{ stats.total_tickets }}</td></tr>
<tr><td>Tickets Closed/Resolved:</td><td>{{ stats.closed_tickets }}</td></tr>
<tr><td>Tickets Still Open (from period):</td><td>{{ stats.open_tickets }}</td></tr>
<tr><td>Average Resolution Time (for {{stats.resolved_ticket_count_for_avg}} resolved/closed tickets):</td><td>{{ stats.average_resolution_time_str }}</td></tr>
</table>
<h3>Tickets by Type:</h3>{% if stats.tickets_by_type %}<ul>{% for type, count in stats.tickets_by_type.items() %}<li>{{ type }}: {{ count }}</li>{% endfor %}</ul>{% else %}<p>No type data.</p>{% endif %}
<h3>Tickets by Priority:</h3>{% if stats.tickets_by_priority %}<ul>{% for priority, count in stats.tickets_by_priority.items() %}<li>{{ priority }}: {{ count }}</li>{% endfor %}</ul>{% else %}<p>No priority data.</p>{% endif %}
<h2>Ticket Details (Sample - Top 10 Newest by ID)</h2>{% if tickets %}<table><thead><tr><th>ID</th><th>Subject</th><th>Status</th><th>Type</th><th>Priority</th><th>Created At</th><th>Resolved At</th><th>Resolution Time</th></tr></thead><tbody>
{% for ticket in (tickets | sort(attribute='id', reverse=True) | list)[:10] %}<tr><td>{{ ticket.id }}</td><td>{{ ticket.subject | truncate(60) }}</td>
<td>{{ ticket.status_text | default(ticket.status) }}</td><td>{{ ticket.type | default('N/A') }}</td><td>{{ ticket.priority_text | default(ticket.priority) }}</td>
<td>{{ ticket.created_at | format_datetime }}</td>
{# Updated "Resolved At" logic #}
<td>
    {% set display_resolved_at = ticket.resolved_at %}
    {% if not display_resolved_at and (ticket.status_text | string | lower == 'resolved' or ticket.status_text | string | lower == 'closed') %}
        {% if ticket.stats and ticket.stats.resolved_at %}
            {% set display_resolved_at = ticket.stats.resolved_at %}
        {% elif ticket.stats and ticket.stats.closed_at %}
            {% set display_resolved_at = ticket.stats.closed_at %}
        {% elif ticket.closed_at %} {# Check top-level closed_at as well #}
            {% set display_resolved_at = ticket.closed_at %}
        {% endif %}
    {% endif %}
    {{ display_resolved_at | format_datetime }}
</td>
{# Updated "Resolution Time" logic #}
<td>
    {% if ticket.status_text | string | lower == 'resolved' or ticket.status_text | string | lower == 'closed' %}
        {% if ticket.stats and ticket.stats.resolution_time_in_secs is not none %}
            {{ ticket.stats.resolution_time_in_secs | format_duration }}
        {% else %}
            {# Fallback for template if stats.resolution_time_in_secs is null for a closed ticket #}
            {# This part is harder to do robustly directly in template without pre-calculation #}
            N/A (Stats missing)
        {% endif %}
    {% else %}
        N/A
    {% endif %}
</td>
</tr>{% endfor %}</tbody></table>
{% else %}<p>No tickets to display.</p>{% endif %}<div class="footer"><p>Report generated by IntegoReport.</p></div></div></body></html>
"""
    # --- END MODIFIED TEMPLATE ---
    with open(default_template_path, 'w', encoding='utf-8') as f_template:
        f_template.write(basic_template_content)
    log_message(f"Created/Updated default template at '{default_template_path}'")
    main()
