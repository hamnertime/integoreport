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
