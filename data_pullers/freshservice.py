# integoreport/data_pullers/freshservice.py

import requests
import base64
import json
import os
import sys
import time
import datetime
from dateutil.relativedelta import relativedelta # For easy month calculation
import argparse # For command-line arguments

# --- Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # integoreport/
TOKEN_FILE = os.path.join(PROJECT_ROOT, "token.txt")
FRESHSERVICE_DOMAIN = "integotecllc.freshservice.com"
BASE_URL = f"https://{FRESHSERVICE_DOMAIN}"
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "raw_data")

ITEMS_PER_PAGE = 30
TICKETS_PER_PAGE = 30 # For the initial list call
MAX_RETRIES = 3
RETRY_DELAY = 5
REQUEST_TIMEOUT = 30
DELAY_BETWEEN_TICKET_PROCESSING_CALLS = 0.25 # Small delay between processing each ticket from the list
DELAY_BETWEEN_SUB_RESOURCE_CALLS = 0.1 # Smaller delay for conversations, time entries etc. for a single ticket

def log_message(message, is_error=False):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_message = f"[{timestamp}] [freshservice_explorer] {message}"
    stream = sys.stderr if is_error else sys.stdout
    print(formatted_message, file=stream)

def read_api_key(file_path):
    try:
        abs_file_path = os.path.abspath(file_path)
        log_message(f"Attempting to read token from: {abs_file_path}")
        if not os.path.exists(abs_file_path):
            log_message(f"Error: Token file '{abs_file_path}' not found.", is_error=True)
            sys.exit(1)
        with open(abs_file_path, 'r') as f:
            api_key = f.read().strip()
        if not api_key:
            log_message(f"Error: Token file '{abs_file_path}' is empty.", is_error=True)
            sys.exit(1)
        return api_key
    except Exception as e:
        log_message(f"Error reading token file '{abs_file_path}': {e}", is_error=True)
        sys.exit(1)

def make_api_request(url, headers, params=None, method="GET", retries=MAX_RETRIES, delay=RETRY_DELAY, allow_404=False, allow_403=False):
    current_retry = 0
    while current_retry <= retries:
        try:
            if method == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)

            if response.status_code == 404 and allow_404:
                return {"error": "404", "status_code": 404, "url": url}
            if response.status_code == 403 and allow_403:
                log_message(f"Access Denied (403) for URL: {url}. API key may lack permissions for this specific resource.", is_error=True)
                return {"error": "403", "status_code": 403, "url": url, "body": response.json() if response.content else None}

            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', delay))
                log_message(f"Rate limit. Waiting {retry_after}s. URL: {url}. Attempt {current_retry + 1}/{retries +1}", is_error=True)
                time.sleep(retry_after)
                current_retry += 1
                continue

            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout:
            log_message(f"Timeout: {url}. Attempt {current_retry + 1}/{retries +1}", is_error=True)
        except requests.exceptions.RequestException as e:
            log_message(f"Request Exception: {url}: {e}. Attempt {current_retry + 1}/{retries +1}", is_error=True)
            if hasattr(e, 'response') and e.response is not None:
                if e.response.status_code == 403 and not allow_403:
                     log_message(f"Access Denied (403) for URL: {url}. Halting retries for this call.", is_error=True)
                     log_message(f"Status: 403, Body: {e.response.text[:500]}", is_error=True)
                     return {"error": "403", "status_code": 403, "url": url, "body": e.response.json() if e.response.content else None}
                log_message(f"Status: {e.response.status_code}, Body: {e.response.text[:500]}", is_error=True)
        except json.JSONDecodeError:
            response_text_snippet = response.text[:200] if 'response' in locals() and hasattr(response, 'text') else 'N/A'
            log_message(f"JSON decode error: {url}. Response: {response_text_snippet}", is_error=True)
            return None

        current_retry += 1
        if current_retry <= retries:
            time.sleep(delay)

    log_message(f"Failed: {url} after {retries +1} attempts.", is_error=True)
    return None

def map_status_id_to_text(status_id):
    status_map = {
        2: "Open", 3: "Pending", 4: "Resolved", 5: "Closed",
        8: "Scheduled", 9: "Waiting on Customer", 10: "Waiting on Third Party",
        13: "Under Investigation", 23: "On Hold", 26: "Waiting on Agent"
    }
    return status_map.get(status_id, f"Status ID {status_id}")

def map_priority_id_to_text(priority_id):
    priority_map = {1: "Low", 2: "Medium", 3: "High", 4: "Urgent"}
    return priority_map.get(priority_id, f"Priority ID {priority_id}")

def get_paginated_data(url, headers, key_name):
    all_items = []
    page = 1
    while True:
        params = {'page': page, 'per_page': ITEMS_PER_PAGE}
        time.sleep(DELAY_BETWEEN_SUB_RESOURCE_CALLS)
        response_data = make_api_request(url, headers, params=params)
        if not response_data or key_name not in response_data:
            break
        current_page_items = response_data[key_name]
        if not current_page_items:
            break
        all_items.extend(current_page_items)
        if len(current_page_items) < ITEMS_PER_PAGE:
            break
        page += 1
        if page > 100:
            log_message(f"Reached page limit (100) for {key_name} at {url}.", is_error=True)
            break
    return all_items

def get_ticket_details_with_includes(base_url, headers, ticket_id):
    url = f"{base_url}/api/v2/tickets/{ticket_id}"
    valid_includes = "stats,requester,assets,department,requested_for,tags,problem,impacted_services,related_tickets"
    params = {'include': valid_includes}
    # log_message(f"Fetching details for ticket ID: {ticket_id} with includes: {params['include']}") # Verbose
    response_data = make_api_request(url, headers, params=params)
    if response_data and "ticket" in response_data:
        ticket_data = response_data["ticket"]

        raw_status = ticket_data.get('status')
        raw_priority = ticket_data.get('priority')

        if raw_status is not None:
            ticket_data['status_text'] = map_status_id_to_text(raw_status)
        else:
            ticket_data['status_text'] = "Unknown (No Status ID)"
            log_message(f"Ticket {ticket_id} missing 'status' field for text mapping.", level="WARNING")

        if raw_priority is not None:
            ticket_data['priority_text'] = map_priority_id_to_text(raw_priority)
        else:
            ticket_data['priority_text'] = "Unknown (No Priority ID)"
            log_message(f"Ticket {ticket_id} missing 'priority' field for text mapping.", level="WARNING")
        return ticket_data
    log_message(f"Could not fetch details for ticket ID: {ticket_id} with includes. Response: {response_data}", is_error=True)
    return None

def get_ticket_conversations(base_url, headers, ticket_id):
    url = f"{base_url}/api/v2/tickets/{ticket_id}/conversations"
    return get_paginated_data(url, headers, "conversations")

def get_ticket_time_entries(base_url, headers, ticket_id):
    url = f"{base_url}/api/v2/tickets/{ticket_id}/time_entries"
    return get_paginated_data(url, headers, "time_entries")

def get_ticket_satisfaction_ratings(base_url, headers, ticket_id):
    url = f"{base_url}/api/v2/tickets/{ticket_id}/satisfaction_ratings"
    time.sleep(DELAY_BETWEEN_SUB_RESOURCE_CALLS)
    response_data = make_api_request(url, headers, allow_404=True)
    if response_data:
        if response_data.get("error") == "404" and response_data.get("status_code") == 404:
            # log_message(f"No satisfaction ratings found (404) for ticket ID: {ticket_id}.") # Can be verbose
            return []
        if "satisfaction_ratings" in response_data:
            return response_data["satisfaction_ratings"]
        else:
            log_message(f"Unexpected response structure for satisfaction ratings (ticket {ticket_id}), not a 404: {response_data}", is_error=True)
            return []
    log_message(f"Failed to fetch satisfaction ratings for ticket ID: {ticket_id} (all retries exhausted or critical error).", is_error=True)
    return []

def get_client_details(base_url, headers, client_id, entity_type_guess="department"):
    endpoint_segment = "departments" if entity_type_guess.lower() == "department" else "companies"
    url = f"{base_url}/api/v2/{endpoint_segment}/{client_id}"
    log_message(f"Fetching client ('{entity_type_guess}') details for ID: {client_id} from {url}")
    data = make_api_request(url, headers)
    key_to_check = entity_type_guess.lower()
    if data and key_to_check in data:
        return data[key_to_check], entity_type_guess
    if entity_type_guess.lower() == "department" and (not data or key_to_check not in data):
        log_message(f"Could not fetch as '{entity_type_guess}', trying as 'company'.")
        endpoint_segment = "companies"
        url = f"{base_url}/api/v2/{endpoint_segment}/{client_id}"
        data = make_api_request(url, headers)
        key_to_check = "company"
        if data and key_to_check in data:
            log_message("Successfully fetched as 'company'.")
            return data[key_to_check], "company"
    log_message(f"Could not fetch client details for ID: {client_id} as '{entity_type_guess}' or 'company'. Response: {data}", is_error=True)
    return None, None

# Removed get_requester_email function as it's not used due to permissions

def get_tickets_for_client_in_range(base_url, headers, client_id, start_date_str, end_date_str):
    all_tickets_enriched = []
    page = 1
    start_dt_iso = start_date_str + "T00:00:00Z"
    end_dt_iso = end_date_str + "T23:59:59Z"
    query = f"(department_id:{client_id}) AND (created_at:>'{start_dt_iso}' AND created_at:<'{end_dt_iso}')"
    filter_url = f"{base_url}/api/v2/tickets/filter"
    log_message(f"Attempting ticket list with query: {query}")

    while True:
        params = {'query': f'"{query}"', 'page': page, 'per_page': TICKETS_PER_PAGE}
        # No 'include' here; details are fetched per ticket later
        response_data = make_api_request(filter_url, headers, params=params)
        if not response_data or 'tickets' not in response_data:
            log_message(f"No more ticket IDs or error fetching page {page} of ID list. Query was: {query}", is_error=not response_data)
            if page == 1 and (not response_data or 'tickets' not in response_data):
                 log_message(f"Initial query with 'department_id:{client_id}' failed. Check filter criteria.", is_error=True)
            break
        current_page_ticket_stubs = response_data['tickets']
        log_message(f"Fetched {len(current_page_ticket_stubs)} ticket stubs on page {page} using query: {query}.")
        for i, ticket_stub in enumerate(current_page_ticket_stubs):
            ticket_id = ticket_stub.get("id")
            if not ticket_id:
                log_message("Skipping ticket stub with no ID.", is_error=True)
                continue

            log_message(f"Processing ticket ID: {ticket_id} ({i+1}/{len(current_page_ticket_stubs)} on this page)")
            detailed_ticket = get_ticket_details_with_includes(base_url, headers, ticket_id)
            if not detailed_ticket:
                log_message(f"Skipping ticket ID {ticket_id} due to error fetching its details.", is_error=True)
                continue

            detailed_ticket['all_conversations'] = get_ticket_conversations(base_url, headers, ticket_id)
            detailed_ticket['all_time_entries'] = get_ticket_time_entries(base_url, headers, ticket_id)
            detailed_ticket['all_satisfaction_ratings'] = get_ticket_satisfaction_ratings(base_url, headers, ticket_id)
            all_tickets_enriched.append(detailed_ticket)
            time.sleep(DELAY_BETWEEN_TICKET_PROCESSING_CALLS)

        if len(current_page_ticket_stubs) < TICKETS_PER_PAGE:
            log_message("Last page of initial ticket ID list reached.")
            break
        page += 1
        if page > 100:
            log_message("Reached page limit (100) for initial ticket ID list.", is_error=True)
            break

    log_message(f"Total tickets fully processed for client {client_id} in period: {len(all_tickets_enriched)}")
    return all_tickets_enriched # Now returns only one value (list of tickets)


def main(client_id_to_fetch, client_entity_type_guess="department"):
    today = datetime.date.today()
    first_day_current_month = today.replace(day=1)
    last_day_previous_month = first_day_current_month - datetime.timedelta(days=1)
    first_day_previous_month = last_day_previous_month.replace(day=1)
    start_date_str = first_day_previous_month.strftime("%Y-%m-%d")
    end_date_str = last_day_previous_month.strftime("%Y-%m-%d")

    log_message(f"Starting exploratory data pull for Client ID: {client_id_to_fetch}")
    log_message(f"Calculated Date Range: {start_date_str} to {end_date_str}")

    if not os.path.exists(OUTPUT_DIR):
        try:
            os.makedirs(OUTPUT_DIR)
            log_message(f"Created output directory: {OUTPUT_DIR}")
        except OSError as e:
            log_message(f"Error creating output dir {OUTPUT_DIR}: {e}", is_error=True)
            return

    api_key = read_api_key(TOKEN_FILE)
    auth_str = f"{api_key}:X"
    encoded_auth = base64.b64encode(auth_str.encode()).decode()
    headers = {"Content-Type": "application/json", "Authorization": f"Basic {encoded_auth}"}

    client_details_obj, client_type_found = get_client_details(BASE_URL, headers, client_id_to_fetch, entity_type_guess=client_entity_type_guess)
    client_name = f"Client_{client_id_to_fetch}"
    actual_client_entity_type = client_entity_type_guess

    client_info_output = {
        "id": client_id_to_fetch, "name": client_name,
        "fetched_as_type": actual_client_entity_type,
        "report_period_start": start_date_str, "report_period_end": end_date_str,
        "retrieval_date": datetime.datetime.now(datetime.timezone.utc).isoformat()
        # Removed contact_email field
    }

    if client_details_obj:
        log_message(f"Successfully fetched client_details for ID {client_id_to_fetch}. Extracting specific fields.")
        client_name = client_details_obj.get('name', client_name)
        actual_client_entity_type = client_type_found
        client_info_output["name"] = client_name
        client_info_output["fetched_as_type"] = actual_client_entity_type

        custom_fields = client_details_obj.get('custom_fields', {})
        client_info_output['client_type'] = custom_fields.get('type_of_client')
        client_info_output['company_main_number'] = custom_fields.get('company_main_number')
        client_info_output['company_start_date'] = custom_fields.get('company_start_date')
        client_info_output['domains'] = client_details_obj.get('domains', [])
        client_info_output['company_head_name'] = client_details_obj.get('head_name')
        client_info_output['prime_user_name'] = client_details_obj.get('prime_user_name')
        # Prime_user_id and head_user_id are still in client_details_obj if needed for other purposes later
        log_message(f"Extracted client info. Prime User Name: {client_info_output.get('prime_user_name')}, Head Name: {client_info_output.get('company_head_name')}.")
    else:
        log_message(f"Could not retrieve client details for ID {client_id_to_fetch}. Client info in output will be minimal.", is_error=True)

    tickets_data = get_tickets_for_client_in_range(BASE_URL, headers, client_id_to_fetch, start_date_str, end_date_str)

    if tickets_data is None:
        log_message(f"Ticket fetching process failed critically for client ID {client_id_to_fetch}.", is_error=True)
        error_data = { "client_info": client_info_output, "error": "Ticket fetching failed", "tickets": []}
        output_filename = f"freshservice_{client_id_to_fetch}_ERROR.json"
        output_filepath = os.path.join(OUTPUT_DIR, output_filename)
        try:
            with open(output_filepath, 'w') as f_err: json.dump(error_data, f_err, indent=4)
        except Exception as e_json:
            log_message(f"Could not write error JSON: {e_json}", is_error=True)
        return

    log_message(f"Note: Email fetching for Prime User/Company Head has been removed due to API permission issues.")

    output_data = {
        "client_info": client_info_output,
        "tickets": tickets_data,
        "summary_stats": {"total_tickets_processed_in_period": len(tickets_data) if tickets_data is not None else 0}
    }
    output_filename = f"freshservice_{client_id_to_fetch}.json"
    output_filepath = os.path.join(OUTPUT_DIR, output_filename)
    try:
        with open(output_filepath, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=4)
        log_message(f"Successfully wrote detailed data to {output_filepath}")
    except IOError as e:
        log_message(f"Error writing data to {output_filepath}: {e}", is_error=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch detailed Freshservice ticket data for a specific client for the previous full month.")
    parser.add_argument("client_id", type=int, help="The Freshservice Client ID (Company or Department ID).")
    parser.add_argument("--entity_type", type=str, default="department", choices=["department", "company"],
                        help="The entity type Freshservice likely treats this client ID as (default: department).")
    args = parser.parse_args()
    main(args.client_id, args.entity_type)
    log_message(f"Exploratory data pull for client {args.client_id} finished.")
