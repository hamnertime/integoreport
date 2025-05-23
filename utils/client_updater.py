# integoreport/utils/client_updater.py

import requests
import base64
import json
import os
import sys
import time
import datetime
import argparse

# --- Configuration --- (Keep as is)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FS_TOKEN_FILE = os.path.join(PROJECT_ROOT, "token.txt")
MC_TOKEN_FILE = os.path.join(PROJECT_ROOT, "mail_token.txt")
FRESHSERVICE_DOMAIN = "integotecllc.freshservice.com"
BASE_URL = f"https://{FRESHSERVICE_DOMAIN}"
CLIENT_LIST_OUTPUT_FILE = os.path.join(PROJECT_ROOT, "companies_list.json")
MAILCHIMP_LIST_ID = "fa1002aff6" # User provided

ITEMS_PER_PAGE = 30
MC_MEMBERS_PER_PAGE = 100
MAX_RETRIES = 3
RETRY_DELAY = 5
REQUEST_TIMEOUT = 30

# --- Logging, Token Reading, Mailchimp DC, FS API Request, FS Client Details, Get All FS Clients ---
# (These functions remain the same as the previous correct version)
def log_message(message, is_error=False):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_message = f"[{timestamp}] [client_updater] {message}"
    stream = sys.stderr if is_error else sys.stdout
    print(formatted_message, file=stream)

def read_token(file_path, service_name="API"):
    try:
        abs_file_path = os.path.abspath(file_path)
        if not os.path.exists(abs_file_path):
             log_message(f"Error: {service_name} Token file '{abs_file_path}' not found.", is_error=True); return None
        with open(abs_file_path, 'r') as f: api_key = f.read().strip()
        if not api_key:
            log_message(f"Error: {service_name} Token file '{abs_file_path}' is empty.", is_error=True); return None
        return api_key
    except Exception as e:
        log_message(f"Error reading {service_name} token file '{abs_file_path}': {e}", is_error=True); return None

def get_mailchimp_dc(api_key):
    parts = api_key.split('-')
    if len(parts) == 2: return parts[1]
    else: log_message("Could not determine Mailchimp DC from API key.", is_error=True); return None

def make_fs_api_request(url, headers, params=None, retries=MAX_RETRIES, delay=RETRY_DELAY, allow_404=False):
    current_retry = 0
    while current_retry <= retries:
        try:
            response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
            if response.status_code == 404 and allow_404:
                return {"error": "404", "status_code": 404, "url": url}
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', delay))
                log_message(f"FS Rate limit. Waiting {retry_after}s.", is_error=True)
                time.sleep(retry_after); current_retry += 1; continue
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response is not None and e.response.status_code == 404 and allow_404:
                 return {"error": "404", "status_code": 404, "url": url}
            log_message(f"FS Request Exception: {url}: {e}. Attempt {current_retry + 1}/{retries +1}", is_error=True)
        except json.JSONDecodeError:
            log_message(f"FS JSON decode error: {url}. Response: {response.text[:200]}", is_error=True); return None
        current_retry += 1; time.sleep(delay)
    log_message(f"FS Failed: {url} after {retries +1} attempts.", is_error=True); return None

def get_fs_client_details(base_url, headers, client_id, primary_entity_hint):
    primary_endpoint_path, primary_key, fallback_endpoint_path, fallback_key = "", "", "", ""
    if primary_entity_hint.lower() == "departments":
        primary_endpoint_path = f"departments/{client_id}"; primary_key = "department"
        fallback_endpoint_path = f"companies/{client_id}"; fallback_key = "company"
    else:
        primary_endpoint_path = f"companies/{client_id}"; primary_key = "company"
        fallback_endpoint_path = f"departments/{client_id}"; fallback_key = "department"
    url_primary = f"{base_url}/api/v2/{primary_endpoint_path}"
    data_primary = make_fs_api_request(url_primary, headers, allow_404=True)
    if data_primary and data_primary.get("error") != "404" and primary_key in data_primary:
        return data_primary[primary_key]
    url_fallback = f"{base_url}/api/v2/{fallback_endpoint_path}"
    data_fallback = make_fs_api_request(url_fallback, headers, allow_404=True)
    if data_fallback and data_fallback.get("error") != "404" and fallback_key in data_fallback:
        log_message(f"Fetched ID {client_id} as {fallback_key.capitalize()} (using fallback).")
        return data_fallback[fallback_key]
    return None

def get_all_clients_data(base_url, headers):
    all_items_detailed = []
    page = 1
    current_listing_entity_type = "Companies"; endpoint_to_try = "/api/v2/companies"; json_key = "companies"
    params_list = {'page': page, 'per_page': ITEMS_PER_PAGE}
    list_response_data = make_fs_api_request(f"{base_url}{endpoint_to_try}", headers, params=params_list, allow_404=True)
    if list_response_data and list_response_data.get("error") == "404" and page == 1:
        log_message(f"FS Companies list 404. Switching to /api/v2/departments.")
        current_listing_entity_type = "Departments"; endpoint_to_try = "/api/v2/departments"; json_key = "departments"
        list_response_data = make_fs_api_request(f"{base_url}{endpoint_to_try}", headers, params=params_list, allow_404=False)
    processed_stubs_count = 0
    while True:
        if not list_response_data or json_key not in list_response_data: break
        current_page_items = list_response_data[json_key]
        processed_stubs_count += len(current_page_items)
        for item_stub in current_page_items:
            item_id = item_stub.get("id")
            if not item_id: continue
            detailed_item = get_fs_client_details(base_url, headers, item_id, current_listing_entity_type)
            if detailed_item:
                if 'name' not in detailed_item and 'name' in item_stub: detailed_item['name'] = item_stub['name']
                all_items_detailed.append(detailed_item)
            else: all_items_detailed.append({"id": item_id, "name": item_stub.get("name", f"Unknown ID {item_id}"), "error": "Details fetch failed"})
            time.sleep(0.05)
        if len(current_page_items) < ITEMS_PER_PAGE: log_message(f"Last page of {current_listing_entity_type} reached."); break
        page += 1
        if page > 200: log_message(f"Max page limit reached.", is_error=True); break
        params_list = {'page': page, 'per_page': ITEMS_PER_PAGE}
        list_response_data = make_fs_api_request(f"{base_url}{endpoint_to_try}", headers, params=params_list, allow_404=False)
    log_message(f"Processed {processed_stubs_count} FS stubs. Total FS clients with details: {len(all_items_detailed)}")
    return all_items_detailed, current_listing_entity_type

def get_all_mailchimp_contacts_rest(api_key, dc, list_id):
    if not all([api_key, dc, list_id]):
        log_message("MC API key, DC, or List ID missing.", is_error=True); return []
    all_members = []; offset = 0; total_items = -1
    fields_to_retrieve = "members.email_address,members.merge_fields.FNAME,members.merge_fields.LNAME,total_items"
    log_message(f"Starting to fetch all MC contacts from list ID: {list_id}")
    while True:
        url = f"https://{dc}.api.mailchimp.com/3.0/lists/{list_id}/members"
        params = {"count": MC_MEMBERS_PER_PAGE, "offset": offset, "fields": fields_to_retrieve}
        auth = ('anystring', api_key)
        try:
            response = requests.get(url, params=params, auth=auth, timeout=REQUEST_TIMEOUT)
            response.raise_for_status(); data = response.json()
            if total_items == -1:
                total_items = data.get('total_items', 0)
                log_message(f"Mailchimp list '{list_id}' has {total_items} total members.")
            members_on_page = data.get('members', [])
            if not members_on_page: break
            for member in members_on_page:
                all_members.append({
                    "email": member.get("email_address","").lower(),
                    "fname": member.get("merge_fields", {}).get("FNAME", ""),
                    "lname": member.get("merge_fields", {}).get("LNAME", "")
                })
            offset += len(members_on_page)
            if offset >= total_items: break
            time.sleep(0.05)
        except requests.exceptions.RequestException as e:
            log_message(f"MC REST error fetching members: {e}", is_error=True)
            if hasattr(e, 'response') and e.response is not None: log_message(f"MC Response: {e.response.text[:200]}", is_error=True)
            return all_members
        except json.JSONDecodeError:
            log_message(f"MC REST JSON decode error.", is_error=True); return all_members
    log_message(f"Fetched {len(all_members)} Mailchimp contacts.")
    return all_members

# *** MODIFIED update_client_list ***
def update_client_list(output_to_file=True):
    log_message("Starting client list update (Fetch all MC, then FS).")
    mc_api_key = read_token(MC_TOKEN_FILE, "Mailchimp")
    mc_dc = get_mailchimp_dc(mc_api_key) if mc_api_key else None
    all_mc_contacts_list = [] # List of MC contact dicts
    mc_contacts_lookup = {}   # For faster name/email lookups: key -> email_string

    if mc_api_key and mc_dc:
        if MAILCHIMP_LIST_ID == "YOUR_MAILCHIMP_LIST_ID_HERE":
            log_message("Mailchimp List ID not set. Skipping Mailchimp contact fetch.", is_error=True)
        else:
            all_mc_contacts_list = get_all_mailchimp_contacts_rest(mc_api_key, mc_dc, MAILCHIMP_LIST_ID)
            for contact in all_mc_contacts_list:
                email_lower = contact.get('email',"").lower()
                if email_lower:
                    mc_contacts_lookup[email_lower] = contact['email'] # Original case email
                full_name = f"{contact.get('fname','')} {contact.get('lname','')} ".lower().strip() # Extra space for single names
                if full_name and full_name not in mc_contacts_lookup :
                    mc_contacts_lookup[full_name] = contact['email']
    else:
        log_message("Mailchimp API key or DC missing. Skipping MC fetch.")

    fs_api_key = read_token(FS_TOKEN_FILE, "Freshservice")
    if not fs_api_key: log_message("FS key missing.", is_error=True); return None
    auth_str = f"{fs_api_key}:X"; encoded_auth = base64.b64encode(auth_str.encode()).decode()
    headers = {"Content-Type": "application/json", "Authorization": f"Basic {encoded_auth}"}

    client_data, actual_entity_type_name = get_all_clients_data(BASE_URL, headers)
    if not client_data: log_message("FS data fetch failed.", is_error=True); return None

    client_list_for_ui = []
    fs_contacts_to_add_to_mc_log = [] # For console logging only
    linked_count = 0

    for item in client_data:
        item_id = item.get("id"); fs_client_name = item.get("name")
        found_mc_email = None
        link_status = "Not Found in MC" # Default status
        fs_contact_to_link = None # Name of FS contact we tried to link

        if not (item_id and fs_client_name):
            log_message(f"Skipping FS client due to missing ID or Name: {item.get('id', 'N/A')}", is_error=True); continue

        fs_prime_name = item.get('prime_user_name')
        fs_head_name = item.get('head_name')

        # Determine the primary FS contact name to search for
        if fs_prime_name and fs_prime_name.strip():
            fs_contact_to_link = fs_prime_name.strip()
            found_mc_email = mc_contacts_lookup.get(fs_contact_to_link.lower())
            if found_mc_email: link_status = "Linked (Prime Name)"

        if not found_mc_email and fs_head_name and fs_head_name.strip():
            fs_contact_to_link = fs_head_name.strip() # This might overwrite fs_contact_to_link if prime was also set
            if not fs_prime_name or not fs_prime_name.strip(): # If prime_name was empty, head_name is primary target
                 fs_contact_to_link = fs_head_name.strip()

            found_mc_email = mc_contacts_lookup.get(fs_head_name.lower().strip())
            if found_mc_email: link_status = "Linked (Head Name)"

        if not fs_contact_to_link and (fs_prime_name or fs_head_name): # Handle cases where one might be just spaces
            fs_contact_to_link = (fs_prime_name if fs_prime_name and fs_prime_name.strip() else fs_head_name).strip()


        # Fallback to domain matching if no name match
        if not found_mc_email:
            fs_domains = item.get('domains', [])
            if fs_domains:
                normalized_fs_domains = [d.lower().strip() for d in fs_domains if d]
                for mc_contact in all_mc_contacts_list: # Iterate the original list for domain check
                    mc_email_val = mc_contact.get('email')
                    if mc_email_val:
                        try:
                            mc_domain = mc_email_val.split('@')[1].lower().strip()
                            if mc_domain in normalized_fs_domains:
                                found_mc_email = mc_email_val
                                link_status = f"Linked (Domain: {mc_domain})"
                                mc_name_for_log = f"{mc_contact.get('fname','')} {mc_contact.get('lname','')} ".strip()
                                log_message(f"Linked {fs_client_name} to MC email {found_mc_email} via domain. (MC Contact: {mc_name_for_log or 'N/A'})")
                                break
                        except IndexError: continue

        if found_mc_email:
            linked_count += 1
        elif fs_contact_to_link: # A specific FS person was identified but not found
            link_status = "To Add to Mailchimp"
            fs_contacts_to_add_to_mc_log.append({ # For console log
                "fs_contact_name": fs_contact_to_link,
                "fs_company_name": fs_client_name,
                "fs_company_id": item_id })
        elif item.get("error") != "Details fetch failed": # No specific FS contact person listed
            link_status = "No FS Contact to Link"
            fs_contact_to_link = None # Ensure it's None if no specific person

        client_list_for_ui.append({
            "id": item_id,
            "name": fs_client_name,
            "email": found_mc_email, # This is the actual linked email
            "mc_link_status": link_status,
            "fs_contact_to_link": fs_contact_to_link if link_status == "To Add to Mailchimp" else None
        })

    if output_to_file:
        try:
            with open(CLIENT_LIST_OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump({"retrieval_date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                           "retrieved_as": actual_entity_type_name, "clients": client_list_for_ui}, f, indent=4)
            log_message(f"Wrote client list to {CLIENT_LIST_OUTPUT_FILE}")
        except IOError as e: log_message(f"Error writing file: {e}", is_error=True); return None

    log_message(f"Update finished. {len(client_list_for_ui)} clients processed. {linked_count} linked to Mailchimp.")
    if fs_contacts_to_add_to_mc_log:
        log_message("\n--- Freshservice Contacts Not Found in Mailchimp (Consider Adding): ---")
        for contact_info in fs_contacts_to_add_to_mc_log:
            log_message(f"  Contact Name: {contact_info['fs_contact_name']}, Company: {contact_info['fs_company_name']} (ID: {contact_info['fs_company_id']})")
    else:
        log_message("All relevant Freshservice contacts (with prime/head names) were found in Mailchimp or had no name to search for.")

    return client_list_for_ui

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch FS clients & link via MC REST API.")
    parser.add_argument("--no-file", action="store_true", help="Print only.")
    args = parser.parse_args()
    clients = update_client_list(output_to_file=not args.no_file)
    # Console output for "to add" is handled within update_client_list now.
    # If --no-file, we might want to print the full list if not too long.
    if clients and args.no_file:
        log_message("\n--- Client List Summary (Not Saved to File) ---")
        for c in clients:
            email_info = c.get('email') if c.get('email') else c.get('mc_link_status', 'N/A')
            if c.get('mc_link_status') == "To Add to Mailchimp" and c.get('fs_contact_to_link'):
                email_info = f"To Add: {c['fs_contact_to_link']}"
            print(f"  ID: {c['id']}, Name: {c['name']}, Link Status/Email: {email_info}")

    elif not clients and args.no_file:
         log_message("Client list update failed.", is_error=True)
