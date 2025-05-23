# integoreport/build_report.py

import json
import os
import glob
import datetime
from dateutil.parser import isoparse
from jinja2 import Environment, FileSystemLoader
import math
# Removed: io, base64, matplotlib imports

# --- Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
RAW_DATA_DIR = os.path.join(PROJECT_ROOT, "raw_data")
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")
OUTPUT_HTML_FILE = os.path.join(PROJECT_ROOT, "output_report.html")

SLA_DEFINITIONS = {
    "Urgent": {"reply": 30 * 60, "resolve": 7 * 24 * 60 * 60},
    "High": {"reply": 2 * 60 * 60, "resolve": 14 * 24 * 60 * 60},
    "Medium": {"reply": 3 * 60 * 60, "resolve": 21 * 24 * 60 * 60},
    "Low": {"reply": 4 * 60 * 60, "resolve": 30 * 24 * 60 * 60},
    "Unknown": {"reply": None, "resolve": None},
}
CHART_COLORS = ['#007bff', '#28a745', '#ffc107', '#dc3545', '#6f42c1', '#fd7e14', '#20c997', '#6610f2', '#e83e8c']


def log_message(message, level="INFO"):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] [build_report] {message}")

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

# --- NEW: HTML Bar Chart Generation Functions ---
def generate_html_bar_chart(data_dict, chart_title, bar_height_px=20, max_bar_width_percent=100):
    """Generates an HTML table-based horizontal bar chart string."""
    if not data_dict or sum(data_dict.values()) == 0:
        return f'<p style="font-size:13px; color:#555; text-align:center;">{chart_title}: No data available.</p>'

    html_rows = []
    total_value = sum(data_dict.values())

    # Sort data by value, descending, for better visual
    sorted_data = dict(sorted(data_dict.items(), key=lambda item: item[1], reverse=True))

    for i, (label, value) in enumerate(sorted_data.items()):
        percentage_of_total = (value / total_value * 100) if total_value > 0 else 0
        bar_width_percent = (percentage_of_total / 100) * max_bar_width_percent
        color = CHART_COLORS[i % len(CHART_COLORS)]

        html_rows.append(f"""
        <tr>
            <td style="padding: 4px 8px; font-size: 12px; color: #333; width: 40%; white-space: nowrap; vertical-align: middle;">{label}: {value} ({percentage_of_total:.1f}%)</td>
            <td style="padding: 4px 0; vertical-align: middle; width: 60%;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:none;"><tr>
                    <td width="{bar_width_percent:.2f}%" bgcolor="{color}" style="height:{bar_height_px}px; font-size:1px; line-height:1px; border-radius: 3px;">&nbsp;</td>
                    <td width="{100 - bar_width_percent:.2f}%" style="height:{bar_height_px}px; font-size:1px; line-height:1px;">&nbsp;</td>
                </tr></table>
            </td>
        </tr>
        """)

    return f"""
    <div style="margin-bottom: 25px; padding:10px; border: 1px solid #eee; border-radius: 5px; background-color: #fdfdfd;">
        <h4 style="margin-top:0; margin-bottom: 10px; font-size: 16px; font-weight: 600; color: #444; text-align:center;">{chart_title}</h4>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:none;">
            {''.join(html_rows)}
        </table>
    </div>
    """

def generate_sla_bar_chart_html(met_count, applicable_count, chart_title, met_color="#28a745", missed_color="#dc3545"):
    if applicable_count == 0:
        return f'<p style="font-size:13px; color:#555; text-align:center;">{chart_title}: Not applicable (0 tickets).</p>'

    missed_count = applicable_count - met_count
    met_percent = (met_count / applicable_count * 100) if applicable_count > 0 else 0
    missed_percent = (missed_count / applicable_count * 100) if applicable_count > 0 else 0

    # Ensure at least a tiny bar is visible for non-zero values for better email client rendering
    min_visible_width = 1 # 1% minimum width if value > 0
    met_bar_width = max(min_visible_width, met_percent) if met_count > 0 else 0
    missed_bar_width = max(min_visible_width, missed_percent) if missed_count > 0 else 0

    # Adjust if sum > 100 due to min_visible_width
    if met_bar_width + missed_bar_width > 100:
        if met_bar_width > missed_bar_width:
            met_bar_width = 100 - missed_bar_width
        else:
            missed_bar_width = 100 - met_bar_width


    html = f"""
    <div style="margin-bottom: 25px; padding:10px; border: 1px solid #eee; border-radius: 5px; background-color: #fdfdfd;">
        <h4 style="margin-top:0; margin-bottom: 10px; font-size: 16px; font-weight: 600; color: #444; text-align:center;">{chart_title}</h4>
        <p style="font-size:12px; text-align:center; margin-top:0; margin-bottom:8px;">
            Met: {met_count} ({met_percent:.1f}%) | Missed: {missed_count} ({missed_percent:.1f}%)
        </p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:none; height: 25px; border-radius: 4px; overflow: hidden;">
            <tr>
    """
    if met_count > 0:
        html += f'<td width="{met_bar_width:.2f}%" bgcolor="{met_color}" style="font-size:1px; line-height:1px;">&nbsp;</td>'
    if missed_count > 0:
        html += f'<td width="{missed_bar_width:.2f}%" bgcolor="{missed_color}" style="font-size:1px; line-height:1px;">&nbsp;</td>'
    if met_count == 0 and missed_count == 0 and applicable_count > 0 : # All were N/A but some were applicable
        html += f'<td width="100%" bgcolor="#e0e0e0" style="font-size:1px; line-height:1px; text-align:center; color:#555; font-size:10px; vertical-align:middle;">(Data Unavailable)</td>'

    html += """
            </tr>
        </table>
    </div>
    """
    return html

# --- Data Loading Functions (find_client_data_file, load_client_data) --- Keep as is
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

# --- Stats Calculation (Modified to store HTML chart strings) ---
def calculate_ticket_stats(tickets_data):
    log_message(f"Calculating stats for {len(tickets_data)} tickets.")
    if not tickets_data: return {}
    stats = { # (Initialize stats dict as before)
        "total_tickets": len(tickets_data), "closed_tickets": 0, "open_tickets": 0,
        "tickets_by_type": {}, "tickets_by_priority": {}, "tickets_by_category": {},
        "total_resolution_seconds": 0, "resolved_ticket_count": 0, "proactive_tickets": 0,
        "total_first_response_seconds": 0, "first_response_count": 0,
        "first_reply_sla_met": 0, "first_reply_sla_applicable": 0,
        "resolution_sla_met": 0, "resolution_sla_applicable": 0,
        "satisfaction_ratings": [],
    }
    for ticket in tickets_data: # (Process tickets as before to populate counts)
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
        ticket['calendar_resolution_time_str'] = "N/A"; ticket['resolved_at_str'] = format_datetime_filter(resolved_dt_str); ticket['first_reply_sla_status'] = "N/A"
        if is_closed and created_dt and resolved_dt and resolved_dt >= created_dt:
            stats["closed_tickets"] += 1; cal_secs = (resolved_dt - created_dt).total_seconds()
            ticket['calendar_resolution_time_str'] = format_duration(cal_secs); stats["total_resolution_seconds"] += cal_secs; stats["resolved_ticket_count"] += 1
            if sla["resolve"] is not None:
                stats["resolution_sla_applicable"] += 1
                if cal_secs <= sla["resolve"]: stats["resolution_sla_met"] += 1
        fr_str = t_stats.get('first_responded_at'); fr_dt = make_aware(isoparse(fr_str)) if fr_str else None
        if fr_dt and created_dt and fr_dt >= created_dt:
            fr_secs = (fr_dt - created_dt).total_seconds(); stats["total_first_response_seconds"] += fr_secs; stats["first_response_count"] += 1
            if sla["reply"] is not None:
                stats["first_reply_sla_applicable"] += 1
                if fr_secs <= sla["reply"]: ticket['first_reply_sla_status'] = "Met"; stats["first_reply_sla_met"] += 1
                else: ticket['first_reply_sla_status'] = "Missed"
            else: ticket['first_reply_sla_status'] = "N/A"
        elif fr_str is None and sla["reply"] is not None: ticket['first_reply_sla_status'] = "No Reply"
        for r in ticket.get('all_satisfaction_ratings', []):
            if r and r.get('ratings') is not None: stats["satisfaction_ratings"].append(r['ratings'])
    stats["open_tickets"] = stats["total_tickets"] - stats["closed_tickets"]
    stats["average_resolution_time_str"] = format_duration(stats["total_resolution_seconds"] / stats["resolved_ticket_count"]) if stats["resolved_ticket_count"] > 0 else "N/A"
    stats["average_first_response_time_str"] = format_duration(stats["total_first_response_seconds"] / stats["first_response_count"]) if stats["first_response_count"] > 0 else "N/A"
    stats["resolution_sla_percent_str"] = f'{(stats["resolution_sla_met"] / stats["resolution_sla_applicable"] * 100):.1f}% Met' if stats["resolution_sla_applicable"] > 0 else "N/A"
    stats["first_reply_sla_percent_str"] = f'{(stats["first_reply_sla_met"] / stats["first_reply_sla_applicable"] * 100):.1f}% Met' if stats["first_reply_sla_applicable"] > 0 else "N/A"
    stats["satisfaction_summary"] = f'{(sum(1 for r in stats["satisfaction_ratings"] if r >= 4) / len(stats["satisfaction_ratings"]) * 100):.1f}% Positive' if stats["satisfaction_ratings"] else "N/A"

    # Generate HTML for charts
    stats['type_chart_html'] = generate_html_bar_chart(stats['tickets_by_type'], 'Tickets by Type')
    stats['priority_chart_html'] = generate_html_bar_chart(stats['tickets_by_priority'], 'Tickets by Priority')
    stats['category_chart_html'] = generate_html_bar_chart(stats['tickets_by_category'], 'Tickets by Category')
    stats['fr_sla_chart_html'] = generate_sla_bar_chart_html(stats['first_reply_sla_met'], stats['first_reply_sla_applicable'], 'First Reply SLA')
    stats['res_sla_chart_html'] = generate_sla_bar_chart_html(stats['resolution_sla_met'], stats['resolution_sla_applicable'], 'Resolution SLA')

    log_message(f"Stats calculated and HTML charts generated.")
    return stats

# --- HTML Rendering ---
def render_html_report(client_info, tickets_data, calculated_stats):
    log_message("Rendering HTML report with HTML charts...")
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    env.filters['format_duration'] = format_duration
    env.filters['format_datetime'] = format_datetime_filter
    env.filters['format_date'] = format_date_filter
    env.filters['get_satisfaction_text'] = get_satisfaction_text
    template_name = 'email_report_template.html'
    try: template = env.get_template(template_name)
    except Exception as e: log_message(f"Error loading template: {e}", "ERROR"); return "Error loading template."
    report_data = {"client_info": client_info, "tickets": tickets_data, "stats": calculated_stats,
                   "generation_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    html_output = template.render(report_data)
    log_message("HTML report rendered successfully.")
    return html_output

# --- Main Logic --- (Keep as is)
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

    # --- TEMPLATE V7 (with HTML bar charts) ---
    basic_template_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Service Report for {{ client_info.name }}</title>
    <style>
        body { margin: 0; padding: 0; background-color: #f4f7f6; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #333; line-height: 1.6; }
        table { border-collapse: collapse; width: 100%; mso-table-lspace:0pt; mso-table-rspace:0pt;}
        img { border: 0; height: auto; line-height: 100%; outline: none; text-decoration: none; -ms-interpolation-mode: bicubic; max-width: 100%;}
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
        .chart-table td { width: 50%; padding: 10px; vertical-align: top; } /* Removed text-align: center for charts */
        .ticket-table { width: 100%; margin-top: 20px; border: 1px solid #ddd; font-size: 12px; }
        .ticket-table th, .ticket-table td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        .ticket-table th { background-color: #f2f2f2; color: #333; font-weight: 600; }
        .ticket-table tr:nth-child(even) { background-color: #f9f9f9; }
        .sla-met { color: #28a745; font-weight: bold; } .sla-missed { color: #dc3545; font-weight: bold; }
        .client-details ul { list-style: none; padding: 0; } .client-details li { margin-bottom: 8px; font-size: 14px; }
        .client-details li strong { color: #333; min-width: 150px; display: inline-block; }
        .footer { padding: 30px; text-align: center; font-size: 12px; color: #888; background-color: #f4f7f6; }
    </style>
</head>
<body>
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%"><tr><td style="background-color: #f4f7f6;">
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="800" class="container" align="center">
    <tr><td class="header"> <h1>Monthly Service Report</h1>
        <p>For: <strong>{{ client_info.name }}</strong></p>
        <p>Period: {{ client_info.report_period_start }} - {{ client_info.report_period_end }}</p>
    </td></tr>
    <tr><td class="section"> <h2>Key Performance Indicators</h2>
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
    <tr><td class="section"> <h2>SLA Performance <span style="font-size: 12px; color: #777;">(Calendar Time)</span></h2>
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" class="chart-table">
            <tr>
                <td>{{ stats.fr_sla_chart_html | safe }}</td>
                <td>{{ stats.res_sla_chart_html | safe }}</td>
            </tr>
        </table>
         <p style="font-size:12px; color: #777; text-align:center; margin-top:15px;">First Reply SLA: {{ stats.first_reply_sla_percent_str }}. Resolution SLA: {{ stats.resolution_sla_percent_str }}.</p>
    </td></tr>
    <tr><td class="section"> <h2>Ticket Breakdown</h2>
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" class="chart-table">
            <tr>
                <td>{{ stats.type_chart_html | safe }}</td>
                <td>{{ stats.priority_chart_html | safe }}</td>
            </tr>
            <tr>
                <td colspan="2" style="padding-top:20px;">{{ stats.category_chart_html | safe }}</td>
            </tr>
        </table>
    </td></tr>
    <tr><td class="section"> <h2>Ticket Details</h2>
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" class="ticket-table">
            <thead><tr><th>ID</th><th>Subject</th><th>Status</th><th>Priority</th><th>Created</th><th>Resolved</th><th>Duration</th><th>Reply SLA</th></tr></thead>
            <tbody>
                {% for ticket in tickets | sort(attribute='id', reverse=True) %}
                <tr><td>#{{ ticket.id }}</td><td>{{ ticket.subject | truncate(40) }}</td><td>{{ ticket.status_text }}</td><td>{{ ticket.priority_text }}</td><td>{{ ticket.created_at | format_datetime }}</td><td>{{ ticket.resolved_at_str }}</td><td>{{ ticket.calendar_resolution_time_str }}</td>
                <td>{% if ticket.first_reply_sla_status == 'Met' %}<span class="sla-met">Met</span>{% elif ticket.first_reply_sla_status == 'Missed' %}<span class="sla-missed">Missed</span>{% else %}{{ ticket.first_reply_sla_status }}{% endif %}</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </td></tr>
    <tr><td class="footer">Report generated by IntegoReport on {{ generation_date }}.</td></tr>
</table>
</td></tr></table>
</body></html>
"""
    # --- END TEMPLATE V7 ---

    write_template = True
    if os.path.exists(default_template_path):
        try:
            with open(default_template_path, 'r', encoding='utf-8') as f_read:
                if f_read.read() == basic_template_content: write_template = False
        except Exception as e: log_message(f"Error reading template: {e}", "WARNING")
    if write_template:
        with open(default_template_path, 'w', encoding='utf-8') as f_template: f_template.write(basic_template_content)
        log_message(f"Created/Updated default template at '{default_template_path}'")
    else: log_message(f"Default template '{default_template_path}' is up-to-date.")

    main()
