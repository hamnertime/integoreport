# integoreport/utils/client_manager.py

import requests
import base64
import json
import os
import sys
import time
import datetime
import argparse

# --- Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # integoreport/
TOKEN_FILE = os.path.join(PROJECT_ROOT, "token.txt")
FRESHSERVICE_DOMAIN = "integotecllc.freshservice.com"
BASE_URL = f"https://{FRESHSERVICE_DOMAIN}"
CLIENT_LIST_OUTPUT_FILE = os.path.join(PROJECT_ROOT, "companies_list.json")

ITEMS_PER_PAGE = 30
MAX_RETRIES = 3
RETRY_DELAY = 5
REQUEST_TIMEOUT = 30

def log_message(message, is_error=False):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_message = f"[{timestamp}] [client_manager] {message}"
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

def make_api_request(url, headers, params=None, method="GET", retries=MAX_RETRIES, delay=RETRY_DELAY, allow_404=False):
    current_retry = 0
    while current_retry <= retries:
        try:
            log_message(f"Requesting URL: {url} with params: {params}")
            if method == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
            if response.status_code == 404 and allow_404:
                log_message(f"URL not found (404): {url}. This may be handled by fallback logic.", is_error=True)
                return {"error": "404", "status_code": 404, "url": url}
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', delay))
                log_message(f"Rate limit. Waiting {retry_after}s. Attempt {current_retry + 1}/{retries +1}", is_error=True)
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
                log_message(f"Status: {e.response.status_code}, Body: {e.response.text[:200]}", is_error=True)
        except json.JSONDecodeError:
            response_text_snippet = response.text[:200] if 'response' in locals() and hasattr(response, 'text') else 'N/A'
            log_message(f"JSON decode error: {url}. Response: {response_text_snippet}", is_error=True)
            return None
        current_retry += 1
        if current_retry <= retries:
            time.sleep(delay)
    log_message(f"Failed: {url} after {retries +1} attempts.", is_error=True)
    return None

def get_all_clients_data(base_url, headers):
    all_items = []
    page = 1
    endpoint_to_try = "/api/v2/companies"
    json_key = "companies"
    entity_type_name = "Companies"
    log_message(f"Attempting to fetch all {entity_type_name} from: {base_url}{endpoint_to_try}")

    while True:
        params = {'page': page, 'per_page': ITEMS_PER_PAGE}
        response_data = make_api_request(f"{base_url}{endpoint_to_try}", headers, params=params, allow_404=(page==1 and endpoint_to_try=="/api/v2/companies"))
        if response_data and response_data.get("error") == "404" and page == 1 and endpoint_to_try == "/api/v2/companies":
            log_message(f"{base_url}{endpoint_to_try} 404. Trying /api/v2/departments.")
            endpoint_to_try = "/api/v2/departments"
            json_key = "departments"
            entity_type_name = "Departments"
            page = 1
            all_items = []
            log_message(f"Attempting to fetch all {entity_type_name} from: {base_url}{endpoint_to_try}")
            continue
        if not response_data or json_key not in response_data:
            log_message(f"No more {entity_type_name} or error fetching page {page}.", is_error=not response_data)
            break
        current_page_items = response_data[json_key]
        log_message(f"Fetched {len(current_page_items)} {entity_type_name} on page {page}.")
        all_items.extend(current_page_items)
        if len(current_page_items) < ITEMS_PER_PAGE:
            log_message(f"Last page of {entity_type_name} reached.")
            break
        page += 1
        if page > 200:
            log_message(f"Max page limit (200) for {entity_type_name}. Stopping.", is_error=True)
            break
    log_message(f"Total {entity_type_name} (as clients) fetched: {len(all_items)}")
    return all_items, entity_type_name

def update_client_list(output_to_file=True):
    log_message("Starting client list update.")
    api_key = read_api_key(TOKEN_FILE)
    auth_str = f"{api_key}:X"
    encoded_auth = base64.b64encode(auth_str.encode()).decode()
    headers = {"Content-Type": "application/json", "Authorization": f"Basic {encoded_auth}"}

    client_data, actual_entity_type = get_all_clients_data(BASE_URL, headers)
    if client_data is None:
        log_message("Failed to fetch client data.", is_error=True)
        return None
    if not isinstance(client_data, list):
        log_message(f"Fetched data not a list: {client_data}", is_error=True)
        return None

    client_list_for_ui = []
    for item in client_data:
        item_id = item.get("id")
        item_name = item.get("name")
        if item_id and item_name:
            client_list_for_ui.append({"id": item_id, "name": item_name}) # Removed primary_contact_id
        else:
            log_message(f"Skipping item (missing ID/Name): {item}", is_error=True)

    if output_to_file:
        output_dir = os.path.dirname(CLIENT_LIST_OUTPUT_FILE)
        if not os.path.exists(output_dir) and output_dir: # Ensure output_dir is not empty
            try:
                os.makedirs(output_dir)
                log_message(f"Created directory: {output_dir}")
            except OSError as e:
                log_message(f"Error creating directory {output_dir}: {e}", is_error=True)
                return None
        try:
            with open(CLIENT_LIST_OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump({
                    "retrieval_date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "retrieved_as": actual_entity_type,
                    "clients": client_list_for_ui
                }, f, indent=4)
            log_message(f"Wrote client list ({actual_entity_type}) to {CLIENT_LIST_OUTPUT_FILE}")
        except IOError as e:
            log_message(f"Error writing to {CLIENT_LIST_OUTPUT_FILE}: {e}", is_error=True)
            return None

    log_message(f"Client list update finished. Found {len(client_list_for_ui)} clients ({actual_entity_type}).")
    return client_list_for_ui

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch client list (Companies/Departments) from Freshservice.")
    parser.add_argument("--no-file", action="store_true", help="Print summary, do not write to file.")
    args = parser.parse_args()
    clients = update_client_list(output_to_file=not args.no_file)
    if clients and args.no_file:
        log_message("Client list (not saved):")
        for client in clients:
            print(f"  ID: {client['id']}, Name: {client['name']}")
    elif not clients:
         log_message("Client list update failed.", is_error=True)
