# IntegoReport

**IntegoReport** is a Python-based project designed to pull data from various service APIs (initially Freshservice) to generate insightful reports for demonstrating value to clients. The primary output will be HTML reports, with a longer-term goal of integrating with services like Mailchimp for email delivery.

**Current Status: Early Development**

This project is in the very early stages of development. The immediate focus is on establishing the data pipeline from Freshservice and generating a basic HTML report.

## Project Goal

To create a system that can:
1.  Fetch relevant client service data (e.g., helpdesk tickets, MS365 usage, Sentinel One alerts - future) from multiple APIs.
2.  Process this data to derive key performance indicators and value metrics (e.g., tickets solved, types of issues, resolution times, proactive measures).
3.  Generate comprehensive and easy-to-understand HTML reports for clients.
4.  (Future) Automate the delivery of these reports, potentially via email services like Mailchimp.
5.  Provide a simple Flask-based web interface for internal management, client selection, and report generation.

## Current Features (In Progress)

* **Freshservice Data Puller (`data_pullers/freshservice.py`):**
    * Accepts a client ID (currently a Freshservice Department ID) and an optional entity type hint (`department` or `company`).
    * Automatically determines the date range for the **previous full calendar month**.
    * Fetches client (Department/Company) details from Freshservice, including standard and some custom fields (e.g., Prime User Name, Client Type).
    * Fetches all tickets for the specified client within the calculated date range using the `(department_id:{client_id}) AND (created_at:...)` filter.
    * For each ticket, fetches detailed information including:
        * Standard ticket attributes.
        * Embedded stats, requester, assets, department, requested_for, and tags.
        * All conversations (paginated).
        * All time entries (paginated).
        * Satisfaction ratings (handles 404s gracefully if none exist).
    * Adds textual representations for status (`status_text`) and priority (`priority_text`) to each ticket object.
    * Saves the comprehensive data for the client into a JSON file in the `raw_data/` directory (e.g., `raw_data/freshservice_{CLIENT_ID}.json`).
* **Client List Manager (`utils/client_manager.py`):**
    * Fetches a list of all "clients" from Freshservice.
    * Intelligently tries the `/api/v2/companies` endpoint first, then falls back to `/api/v2/departments` if companies are not found (as is common in some MSP setups).
    * Extracts client ID and Name.
    * Saves this list to `companies_list.json` in the project root.
* **HTML Report Builder (`build_report.py`):**
    * Automatically detects the most recent `freshservice_*.json` file in the `raw_data/` directory.
    * Loads the client and ticket data from this JSON file.
    * Calculates basic summary statistics (total tickets, closed/resolved, open, counts by type and priority, average resolution time).
    * Renders an HTML report using a Jinja2 template (`templates/email_report_template.html`).
    * The default template includes client details, summary stats, and a sample list of recent tickets with formatted dates and durations.
    * Saves the generated report as `output_report.html` in the project root.
* **Templating:** Uses Jinja2 for HTML generation, with custom filters for date and duration formatting.

## Planned Project Structure
integoreport/
├── main.py                     # Flask app (To be developed)
├── pull_info.py                # Orchestrates data pullers (Basic placeholder)
├── build_report.py             # Generates HTML report from raw_data
│
├── data_pullers/
│   └── freshservice.py         # Fetches data for a client from Freshservice
│
├── utils/
│   └── client_manager.py       # Fetches and manages the list of clients
│
├── raw_data/                   # Stores JSON output from data_pullers (e.g., freshservice_CLIENTID.json)
│                               # This folder is intended to be temporary for each report run.
│
├── templates/
│   └── email_report_template.html # Template for the client HTML email
│
├── static/                     # CSS, JS for the Flask app (if needed)
│
├── token.txt                   # Stores Freshservice API key (MUST be in .gitignore)
├── companies_list.json         # Stores the list of clients (ID and Name)
└── README.md                   # This file

## Setup (Current)

1.  **Clone the Repository.**
2.  **Python Environment:**
    * Python 3.x recommended.
    * Use a virtual environment:
        ```bash
        python -m venv venv
        source venv/bin/activate  # On Windows: venv\Scripts\activate
        ```
3.  **Install Dependencies:**
    ```bash
    pip install requests python-dateutil Jinja2
    ```
4.  **Configuration:**
    * Create `token.txt` in the project root (`integoreport/`) and place your Freshservice API key in it (just the key, no other text).
    * Ensure your API key has permissions to:
        * Read Departments (and/or Companies, depending on your setup).
        * Filter and Read Tickets (including details, stats, requester info, assets, conversations, time entries).
        * *(Currently, the script assumes read access to Requesters is NOT available due to prior 403 errors, so it doesn't fetch Prime User emails directly).*

## Running the Components (Current Workflow)

1.  **Update Client List (as needed):**
    ```bash
    python utils/client_manager.py
    ```
    This will generate/update `companies_list.json` in the project root.

2.  **Fetch Data for a Specific Client:**
    * Identify the `CLIENT_ID` from `companies_list.json`.
    * Run the Freshservice data puller:
        ```bash
        python data_pullers/freshservice.py <CLIENT_ID>
        # Example: python data_pullers/freshservice.py 19000077030
        ```
    * This will create a `freshservice_<CLIENT_ID>.json` file in the `raw_data/` directory.

3.  **Generate the HTML Report:**
    ```bash
    python build_report.py
    ```
    * This script will automatically find the latest `freshservice_*.json` file in `raw_data/`.
    * It will generate `output_report.html` in the project root.

## Next Steps & Future Development

* **Refine `build_report.py`:**
    * Calculate more advanced and insightful statistics (e.g., First Contact Resolution, SLA adherence if data is available, trends over time).
    * Improve the HTML template (`templates/email_report_template.html`) for better presentation and client-readiness.
    * Implement CSS inlining for robust email client compatibility (e.g., using the `premailer` library).
* **Develop `pull_info.py`:**
    * Create logic to iterate through a list of clients (from `companies_list.json`) and run the appropriate data pullers for each.
    * Manage the `raw_data/` directory (e.g., clear it before a new batch run or archive old data).
* **Develop `main.py` (Flask Interface):**
    * UI to trigger `client_manager.py`.
    * UI to select a client and date range (or "previous month") to trigger `pull_info.py` and then `build_report.py`.
    * Display generated reports or provide download links.
* **Add More Data Pullers:**
    * Microsoft 365 (e.g., Secure Score, user activity).
    * Sentinel One (e.g., threat summaries).
* **Mailchimp Integration:** Send the generated HTML reports via Mailchimp API.
* **Error Handling & Logging:** Enhance across all scripts.

## License

This project is licensed under the GPLv3 License. See the `LICENSE.md` file for details (you'll need to create this file and add the GPLv3 text to it).

---
Copyright (c) 2025 David Hamner
