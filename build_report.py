# integoreport/build_report.py

import json
import os
import glob
import datetime
from dateutil.parser import isoparse
from jinja2 import Environment, FileSystemLoader
import math

# --- Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
RAW_DATA_DIR = os.path.join(PROJECT_ROOT, "raw_data")
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")
OUTPUT_HTML_FILE = os.path.join(PROJECT_ROOT, "output_report.html")

# --- SLA Definitions (in seconds) ---
SLA_DEFINITIONS = {
    "Urgent": {"reply": 30 * 60, "resolve": 7 * 24 * 60 * 60},
    "High": {"reply": 2 * 60 * 60, "resolve": 14 * 24 * 60 * 60},
    "Medium": {"reply": 3 * 60 * 60, "resolve": 21 * 24 * 60 * 60},
    "Low": {"reply": 4 * 60 * 60, "resolve": 30 * 24 * 60 * 60},
    "Unknown": {"reply": None, "resolve": None},
}
# Pie Chart Colors
PIE_COLORS = ["#007bff", "#28a745", "#ffc107", "#dc3545", "#6c757d", "#17a2b8", "#343a40", "#fd7e14", "#6610f2"]


def log_message(message, level="INFO"):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] [build_report] {message}")

# --- Jinja2 Filters & Helpers ---
def format_datetime_filter(value, format_string="%b %d, %Y %H:%M"):
    if not value: return "N/A"
    try: return isoparse(str(value)).strftime(format_string)
    except (ValueError, TypeError): return str(value)

def format_date_filter(value, format_string="%b %d, %Y"):
    if not value: return "N/A"
    try: return isoparse(str(value)).strftime(format_string)
    except (ValueError, TypeError): return str(value)

def format_duration(seconds):
    if seconds is None or not isinstance(seconds, (int, float)) or seconds < 0: return "N/A"
    seconds = int(seconds)
    if seconds == 0: return "0m"
    days, r = divmod(seconds, 86400); hours, r = divmod(r, 3600); minutes, _ = divmod(r, 60)
    parts = [f"{d}d" for d in [days] if d > 0] + [f"{h}h" for h in [hours] if h > 0] + [f"{m}m" for m in [minutes] if m > 0]
    return " ".join(parts) if parts else "< 1m"

def get_satisfaction_text(rating):
    return {5: "😊", 4: "🙂", 3: "😐", 2: "🙁", 1: "😠"}.get(rating, "")

def make_aware(dt, default_tz=datetime.timezone.utc):
    if dt is None: return None
    return dt.replace(tzinfo=dt.tzinfo or default_tz)

def get_svg_pie_chart(data, size=120, title="Chart"):
    if not data: return f"<p>{title}: No data.</p>"
    chart_data = {k: v for k, v in data.items() if v > 0}
    if not chart_data: return f"<p>{title}: No data.</p>"
    total = sum(chart_data.values())
    radius = size / 2; cx, cy = radius, radius; current_angle = -90
    paths = []; legend = []
    start_x = cx + radius * math.cos(math.radians(current_angle))
    start_y = cy + radius * math.sin(math.radians(current_angle))
    for i, (label, value) in enumerate(chart_data.items()):
        percentage = value / total; angle = percentage * 360
        color = PIE_COLORS[i % len(PIE_COLORS)]
        end_angle = current_angle + angle
        end_x = cx + radius * math.cos(math.radians(end_angle))
        end_y = cy + radius * math.sin(math.radians(end_angle))
        large_arc_flag = 1 if angle >= 180 else 0
        d = f"M {cx} {cy - radius} A {radius} {radius} 0 1 1 {cx - 0.01} {cy - radius} Z" if abs(angle - 360) < 0.01 else f"M {cx},{cy} L {start_x},{start_y} A {radius},{radius} 0 {large_arc_flag},1 {end_x},{end_y} Z"
        paths.append(f'<path d="{d}" fill="{color}"><title>{label}: {value} ({percentage:.1%})</title></path>')
        legend.append(f'<li style="margin-bottom: 5px;"><span style="display:inline-block;width:12px;height:12px;border-radius:3px;background-color:{color};margin-right:8px;vertical-align:middle;"></span>{label}: {value} ({percentage:.1%})</li>')
        current_angle = end_angle; start_x, start_y = end_x, end_y
    svg_code = f"""<div style="text-align: center; margin-bottom: 25px;"><h4 style="margin-bottom: 15px; font-size: 16px; font-weight: 600; color: #444;">{title}</h4><table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%"><tr><td style="width: {size}px; vertical-align: middle;"><svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">{''.join(paths)}</svg></td><td style="vertical-align: middle; padding-left: 20px;"><ul style="list-style: none; padding: 0; margin: 0; text-align: left; font-size: 13px; line-height: 1.6;">{''.join(legend)}</ul></td></tr></table></div>"""
    return svg_code

# --- Data Loading ---
def find_client_data_file(raw_data_path):
    log_message(f"Searching for client data files in: {raw_data_path}")
    search_pattern = os.path.join(raw_data_path, "freshservice_*.json")
    files = glob.glob(search_pattern)
    if not files: log_message("No client data files found.", "ERROR"); return None
    files.sort(key=os.path.getmtime, reverse=True)
    log_message(f"Using newest file: {files[0]}")
    return files[0]

def load_client_data(file_path):
    log_message(f"Loading client data from: {file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
        log_message("Client data loaded successfully.")
        return data
    except Exception as e: log_message(f"Error loading {file_path}: {e}", "ERROR"); return None

# --- Stats Calculation ---
def calculate_ticket_stats(tickets_data):
    log_message(f"Calculating stats for {len(tickets_data)} tickets.")
    if not tickets_data: return {}

    stats = {
        "total_tickets": len(tickets_data), "closed_tickets": 0, "open_tickets": 0,
        "tickets_by_type": {}, "tickets_by_priority": {}, "tickets_by_category": {},
        "total_resolution_seconds": 0, "resolved_ticket_count": 0, "proactive_tickets": 0,
        "total_first_response_seconds": 0, "first_response_count": 0,
        "first_reply_sla_met": 0, "first_reply_sla_applicable": 0,
        "resolution_sla_met": 0, "resolution_sla_applicable": 0,
        "satisfaction_ratings": [],
    }

    for ticket in tickets_data:
        p_text = ticket.get('priority_text', "Unknown")
        sla = SLA_DEFINITIONS.get(p_text, SLA_DEFINITIONS["Unknown"])
        t_stats = ticket.get('stats', {})
        created_dt = make_aware(isoparse(ticket['created_at'])) if ticket.get('created_at') else None

        stats["tickets_by_type"][ticket.get('type', 'N/A')] = stats["tickets_by_type"].get(ticket.get('type', 'N/A'), 0) + 1
        stats["tickets_by_priority"][p_text] = stats["tickets_by_priority"].get(p_text, 0) + 1
        stats["tickets_by_category"][ticket.get('category', 'N/A')] = stats["tickets_by_category"].get(ticket.get('category', 'N/A'), 0) + 1
        if ticket.get('custom_fields', {}).get('proactive_case', False): stats["proactive_tickets"] += 1

        is_closed = "closed" in ticket.get('status_text', "").lower() or "resolved" in ticket.get('status_text', "").lower()
        resolved_dt_str = ticket.get('resolved_at') or t_stats.get('resolved_at') or ticket.get('closed_at') or t_stats.get('closed_at')
        resolved_dt = make_aware(isoparse(resolved_dt_str)) if resolved_dt_str else None
        ticket['calendar_resolution_time_str'] = "N/A"
        ticket['resolved_at_str'] = format_datetime_filter(resolved_dt_str)
        ticket['first_reply_sla_status'] = "N/A" # *** ADDED: Initialize per-ticket SLA status ***

        if is_closed and created_dt and resolved_dt and resolved_dt >= created_dt:
            stats["closed_tickets"] += 1
            cal_secs = (resolved_dt - created_dt).total_seconds()
            ticket['calendar_resolution_time_str'] = format_duration(cal_secs)
            stats["total_resolution_seconds"] += cal_secs
            stats["resolved_ticket_count"] += 1
            if sla["resolve"] is not None:
                stats["resolution_sla_applicable"] += 1
                if cal_secs <= sla["resolve"]: stats["resolution_sla_met"] += 1

        fr_str = t_stats.get('first_responded_at')
        fr_dt = make_aware(isoparse(fr_str)) if fr_str else None
        if fr_dt and created_dt and fr_dt >= created_dt:
            fr_secs = (fr_dt - created_dt).total_seconds()
            stats["total_first_response_seconds"] += fr_secs
            stats["first_response_count"] += 1
            if sla["reply"] is not None:
                stats["first_reply_sla_applicable"] += 1
                if fr_secs <= sla["reply"]:
                    stats["first_reply_sla_met"] += 1
                    ticket['first_reply_sla_status'] = "Met" # *** ADDED: Set status ***
                else:
                    ticket['first_reply_sla_status'] = "Missed" # *** ADDED: Set status ***
            else:
                 ticket['first_reply_sla_status'] = "N/A"
        elif fr_str is None and sla["reply"] is not None:
            # If there's an SLA but no response yet (or ever), it's either N/A (if open) or potentially Missed (if closed without response)
            # For simplicity, we'll keep it N/A unless explicitly asked otherwise.
             ticket['first_reply_sla_status'] = "No Reply"

        for r in ticket.get('all_satisfaction_ratings', []):
            if r and r.get('ratings') is not None: stats["satisfaction_ratings"].append(r['ratings'])

    stats["open_tickets"] = stats["total_tickets"] - stats["closed_tickets"]
    stats["average_resolution_time_str"] = format_duration(stats["total_resolution_seconds"] / stats["resolved_ticket_count"]) if stats["resolved_ticket_count"] > 0 else "N/A"
    stats["average_first_response_time_str"] = format_duration(stats["total_first_response_seconds"] / stats["first_response_count"]) if stats["first_response_count"] > 0 else "N/A"
    stats["resolution_sla_percent"] = f'{(stats["resolution_sla_met"] / stats["resolution_sla_applicable"] * 100):.1f}%' if stats["resolution_sla_applicable"] > 0 else "N/A"
    stats["first_reply_sla_percent"] = f'{(stats["first_reply_sla_met"] / stats["first_reply_sla_applicable"] * 100):.1f}%' if stats["first_reply_sla_applicable"] > 0 else "N/A"
    stats["resolution_sla_data"] = {"Met": stats["resolution_sla_met"], "Missed": stats["resolution_sla_applicable"] - stats["resolution_sla_met"]}
    stats["first_reply_sla_data"] = {"Met": stats["first_reply_sla_met"], "Missed": stats["first_reply_sla_applicable"] - stats["first_reply_sla_met"]}
    stats["satisfaction_summary"] = f'{(sum(1 for r in stats["satisfaction_ratings"] if r >= 4) / len(stats["satisfaction_ratings"]) * 100):.1f}% Positive' if stats["satisfaction_ratings"] else "N/A"

    log_message(f"Final Calculated stats: {json.dumps(stats, indent=2, default=str)}")
    return stats

# --- HTML Rendering ---
def render_html_report(client_info, tickets_data, calculated_stats):
    log_message("Rendering HTML report...")
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    env.filters['format_duration'] = format_duration
    env.filters['format_datetime'] = format_datetime_filter
    env.filters['format_date'] = format_date_filter
    env.filters['get_satisfaction_text'] = get_satisfaction_text
    env.globals['get_svg_pie_chart'] = get_svg_pie_chart

    template_name = 'email_report_template.html'
    try: template = env.get_template(template_name)
    except Exception as e: log_message(f"Error loading template: {e}", "ERROR"); return "Error loading template."

    html_output = template.render({
        "client_info": client_info, "tickets": tickets_data,
        "stats": calculated_stats, "generation_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    log_message("HTML report rendered successfully.")
    return html_output

# --- Main Logic ---
def main():
    log_message("Starting report generation process...")
    client_data_file = find_client_data_file(RAW_DATA_DIR)
    if not client_data_file: return
    data = load_client_data(client_data_file)
    if not data: return

    client_info = data.get('client_info', {})
    tickets_data = data.get('tickets', [])
    log_message(f"Processing report for: {client_info.get('name')} (ID: {client_info.get('id')})")

    calculated_stats = calculate_ticket_stats(tickets_data)
    html_content = render_html_report(client_info, tickets_data, calculated_stats)

    if html_content:
        try:
            with open(OUTPUT_HTML_FILE, 'w', encoding='utf-8') as f: f.write(html_content)
            log_message(f"HTML report saved to: {OUTPUT_HTML_FILE}")
        except Exception as e: log_message(f"Error saving HTML: {e}", "ERROR")
    log_message("Report generation process finished.")


if __name__ == "__main__":
    if not os.path.exists(TEMPLATES_DIR):
        os.makedirs(TEMPLATES_DIR); log_message(f"Created: {TEMPLATES_DIR}")

    default_template_path = os.path.join(TEMPLATES_DIR, "email_report_template.html")
    log_message(f"Ensuring default template at '{default_template_path}'.")

    # --- TEMPLATE V5 (with Reply SLA Column) ---
    basic_template_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Service Report for {{ client_info.name }}</title>
    <style>
        body { margin: 0; padding: 0; background-color: #f4f7f6; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #333; line-height: 1.6; }
        table { border-collapse: collapse; width: 100%; mso-table-lspace:0pt; mso-table-rspace:0pt;}
        img { border: 0; height: auto; line-height: 100%; outline: none; text-decoration: none; -ms-interpolation-mode: bicubic;}
        a { color: #007bff; text-decoration: none; }
        .container { background-color: #ffffff; width: 100%; max-width: 800px; margin: 20px auto; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); overflow: hidden; border: 1px solid #e0e0e0; }
        .header { background-color: #004a99; color: #ffffff; padding: 30px 40px; text-align: left; }
        .header h1 { margin: 0 0 5px 0; font-size: 28px; font-weight: 300; color: #ffffff;}
        .header p { margin: 0; font-size: 16px; font-weight: 300; color: #ffffff;}
        .section { padding: 30px 40px; border-bottom: 1px solid #e0e0e0; }
        .section:last-of-type { border-bottom: none; }
        .section h2 { font-size: 22px; color: #004a99; margin-top: 0; margin-bottom: 25px; font-weight: 600; border-bottom: 2px solid #e0e0e0; padding-bottom: 8px; }
        .kpi-table td { width: 50%; padding: 5px 15px 5px 0; vertical-align: top; }
        .kpi-card { background-color: #f9f9f9; padding: 20px; border-radius: 6px; border: 1px solid #eee; text-align: center; height: 100%; box-sizing: border-box;}
        .kpi-value { font-size: 32px; font-weight: 700; color: #007bff; margin-bottom: 5px; }
        .kpi-label { font-size: 14px; color: #555; }
        .chart-table td { width: 50%; padding: 10px; vertical-align: top; text-align: center; }
        .ticket-table { width: 100%; margin-top: 20px; border: 1px solid #ddd; font-size: 12px; } /* Slightly smaller font */
        .ticket-table th, .ticket-table td { border: 1px solid #ddd; padding: 8px; text-align: left; } /* Reduced padding */
        .ticket-table th { background-color: #f2f2f2; color: #333; font-weight: 600; }
        .ticket-table tr:nth-child(even) { background-color: #f9f9f9; }
        .sla-met { color: #28a745; font-weight: bold; }
        .sla-missed { color: #dc3545; font-weight: bold; }
        .client-details ul { list-style: none; padding: 0; } .client-details li { margin-bottom: 8px; font-size: 14px; }
        .client-details li strong { color: #333; min-width: 150px; display: inline-block; }
        .footer { padding: 30px; text-align: center; font-size: 12px; color: #888; background-color: #f4f7f6; }
    </style>
</head>
<body>
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%"><tr><td style="background-color: #f4f7f6;">
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="800" class="container" align="center">
    <tr><td class="header">
        <h1>Monthly Service Report</h1>
        <p>For: <strong>{{ client_info.name }}</strong></p>
        <p>Period: {{ client_info.report_period_start }} - {{ client_info.report_period_end }}</p>
    </td></tr>
    <tr><td class="section">
        <h2>Key Performance Indicators</h2>
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" class="kpi-table">
            <tr>
                <td><div class="kpi-card"><div class="kpi-value">{{ stats.total_tickets }}</div><div class="kpi-label">Total Tickets</div></div></td>
                <td><div class="kpi-card"><div class="kpi-value">{{ stats.closed_tickets }}</div><div class="kpi-label">Tickets Resolved</div></div></td>
            </tr><tr>
                <td><div class="kpi-card"><div class="kpi-value">{{ stats.average_resolution_time_str }}</div><div class="kpi-label">Avg. Resolution Time</div></div></td>
                <td><div class="kpi-card"><div class="kpi-value">{{ stats.average_first_response_time_str }}</div><div class="kpi-label">Avg. First Response</div></div></td>
            </tr>
        </table>
    </td></tr>
    <tr><td class="section">
        <h2>SLA Performance <span style="font-size: 12px; color: #777;">(Calendar Time)</span></h2>
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" class="chart-table">
            <tr>
                <td>{{ get_svg_pie_chart(stats.first_reply_sla_data, title='First Reply SLA') | safe }}</td>
                <td>{{ get_svg_pie_chart(stats.resolution_sla_data, title='Resolution SLA') | safe }}</td>
            </tr>
        </table>
    </td></tr>
    <tr><td class="section">
        <h2>Ticket Breakdown</h2>
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" class="chart-table">
            <tr>
                <td>{{ get_svg_pie_chart(stats.tickets_by_type, title='By Type') | safe }}</td>
                <td>{{ get_svg_pie_chart(stats.tickets_by_priority, title='By Priority') | safe }}</td>
            </tr>
            <tr>
                <td colspan="2">{{ get_svg_pie_chart(stats.tickets_by_category, size=150, title='By Category') | safe }}</td>
            </tr>
        </table>
    </td></tr>
    <tr><td class="section">
        <h2>Ticket Details</h2>
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" class="ticket-table">
            <thead><tr>
                <th>ID</th><th>Subject</th><th>Status</th><th>Priority</th>
                <th>Created</th><th>Resolved</th><th>Duration</th><th>Reply SLA</th>
            </tr></thead>
            <tbody>
                {% for ticket in tickets | sort(attribute='id', reverse=True) %}
                <tr>
                    <td>#{{ ticket.id }}</td>
                    <td>{{ ticket.subject | truncate(40) }}</td> {# Further truncated for space #}
                    <td>{{ ticket.status_text }}</td>
                    <td>{{ ticket.priority_text }}</td>
                    <td>{{ ticket.created_at | format_datetime }}</td>
                    <td>{{ ticket.resolved_at_str }}</td>
                    <td>{{ ticket.calendar_resolution_time_str }}</td>
                    <td> {# *** ADDED: New Column Data *** #}
                        {% if ticket.first_reply_sla_status == 'Met' %}
                            <span class="sla-met">Met</span>
                        {% elif ticket.first_reply_sla_status == 'Missed' %}
                            <span class="sla-missed">Missed</span>
                        {% else %}
                            {{ ticket.first_reply_sla_status }}
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </td></tr>
    <tr><td class="footer">Report generated by IntegoReport on {{ generation_date }}.</td></tr>
</table>
</td></tr></table>
</body></html>
"""
    # --- END TEMPLATE V5 ---

    # Only write if it doesn't exist or content differs
    write_template = True
    if os.path.exists(default_template_path):
        try:
            with open(default_template_path, 'r', encoding='utf-8') as f_read:
                if f_read.read() == basic_template_content: write_template = False
        except Exception as e: log_message(f"Error reading template: {e}", "WARNING")

    if write_template:
        with open(default_template_path, 'w', encoding='utf-8') as f_template:
            f_template.write(basic_template_content)
        log_message(f"Created/Updated default template at '{default_template_path}'")
    else: log_message(f"Default template '{default_template_path}' is up-to-date.")

    main()
