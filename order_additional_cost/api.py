import frappe
import json
import os
from mistralai import Mistral, SystemMessage, UserMessage
from thefuzz import process

@frappe.whitelist()
def check_settings():
    """
    Checks if all required settings for the AI feature are configured.
    Returns a list of missing settings.
    """
    missing_settings = []
    
    # Check for the API key in site_config.json
    if not frappe.conf.get("mistral_api_key"):
        missing_settings.append("Mistral API Key has not been set by the administrator.")
        
    # Check for the fallback item in the Settings Doctype
    if not frappe.db.get_single_value("MistralAI Settings", "default_item"):
        missing_settings.append("A 'Default Fallback Item' has not been selected in MistralAI Settings.")
        
    return missing_settings

@frappe.whitelist()
def process_invoice_pdf(file_url):
    """
    Receives a public file URL, sends it directly to Mistral AI
    for internal OCR and structured data extraction, and returns the result.
    """
    try:
        # Get the full, absolute URL of the file
        file_doc = frappe.get_doc("File", {"file_url": file_url})
        if file_doc.is_private:
            private_file_path = file_doc.get_full_path()
            public_folder_path = os.path.join(frappe.get_site_path(), "public", "files")
            new_public_file_path = os.path.join(public_folder_path, file_doc.file_name)

            if os.path.exists(new_public_file_path):
                os.remove(private_file_path)
            else:
                os.makedirs(public_folder_path, exist_ok=True)
                os.rename(private_file_path, new_public_file_path)

            new_public_url = f"/files/{file_doc.file_name}"
            frappe.db.sql("""
                UPDATE `tabFile`
                SET is_private = 0, file_url = %s
                WHERE name = %s
            """, (new_public_url, file_doc.name))
            frappe.db.commit()

            file_doc.file_url = new_public_url

        public_url = frappe.utils.get_url(file_doc.file_url)

        # Call the updated function that uses Mistral's native document processing
        extracted_data = get_raw_text_from_mistral(public_url)

        matched_supplier = find_best_match(extracted_data.get("supplier_name"), "Supplier", "supplier_name")

        cost_with_items = []
        if extracted_data.get("costs"):
            fallback_item = frappe.db.get_single_value("MistralAI Settings", "default_item")
            if not fallback_item:
                frappe.throw("Please set a default item in MistralAI Settings to use when no match is found.")

            item_choices = [d.item_name for d in frappe.get_all("Item", {"disabled": 0, "is_stock_item": 0}, "item_name")]

            for cost in extracted_data["costs"]:
                best_item_match = find_best_match(cost.get("description"), item_choices, use_list=True, score_cutoff=80)

                frappe.logger("api").info(f"Cost description: {cost.get('description')}, Best item match: {best_item_match}")
                new_cost = cost.copy()
                if best_item_match:
                    matched_item_code = frappe.get_value("Item", {"item_name": best_item_match}, "item_code")
                else:
                    matched_item_code = fallback_item
                new_cost["item_code"] = matched_item_code
                cost_with_items.append(new_cost)
        
        return {
            "matched_supplier": matched_supplier,
            "costs": cost_with_items
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Mistral Document Processing Failed")
        frappe.throw(f"An error occurred during PDF processing: {str(e)}")

def find_best_match(query, target_doctype_or_list, target_field=None, use_list=False, score_cutoff=85):
    """
    Finds the best fuzzy match for a query string against a DocType or a list.
    """
    if not query:
        return None
        
    if use_list:
        choices = target_doctype_or_list
    else:
        choices = [d[target_field] for d in frappe.get_all(target_doctype_or_list, fields=[target_field], filters={"disabled": 0})]

    if not choices:
        return None

    best_match = process.extractOne(query, choices, score_cutoff=score_cutoff)
    
    if best_match:
        if not use_list:
            return frappe.db.get_value(target_doctype_or_list, {target_field: best_match[0]}, "name")
        return best_match[0]
    return None

def get_raw_text_from_mistral(document_url):
    """
    Sends a document URL to the Mistral API and asks for structured data extraction.
    asks for the supplier name as a separate field
    The API handles the OCR internally.
    """
    api_key = frappe.conf.get("mistral_api_key")
    if not api_key:
        frappe.throw("Mistral API key is not set in site_config.json")

    model_name = "mistral-large-latest"
    client = Mistral(api_key=api_key)

    default_system_prompt = """
    You are an expert data extraction assistant. You will be given a URL to a document.
    Your task is to read the document and extract the logistics company's name (e.g., FedEx, DHL) and
    all cost-related line items, such as transport fees, customs duties, handling fees, etc.
    Analyze the description of each cost. If it is a government levy, duty, or tax, set the category to 'Tax'. Otherwise, set it to 'Logistics'.
    Provide the output as a single, valid JSON object containing a single key "costs" which is a list of objects.

    Each object in the "costs" list must contain these keys:
    - "description": A string describing the cost (e.g., "Transport", "Customs Duty").
    - "amount": A number representing the cost amount.
    - "hs_code": A string for the HS/Tariff code if available, otherwise an empty string "".
    - "category": A string categorizing the cost ("Tax" or "Logistics").

    Example:
    {
      "supplier_name": "FedEx Express",
      "costs": [
        { "description": "International Priority Freight", "amount": 150.75, "hs_code": "85171200", "category": "Logistics" },
        { "description": "Customs Duty", "amount": 75.00, "hs_code": "87032100", "category": "Tax" },
        { "description": "Customs Handling Fee", "amount": 45.50, "hs_code": "" }
      ]
    }
    """

    custom_prompt = frappe.db.get_single_value("MistralAI Settings", "system_prompt")

    system_prompt = custom_prompt or default_system_prompt
    
    user_prompt_text = "Please extract the supplier name and all cost line items from the provided logistics invoice document."

    try:
        messages = [
            SystemMessage(content=system_prompt),
            UserMessage(content=[
                {"type": "text", "text": user_prompt_text},
                {"type": "document_url", "document_url": document_url}
            ])
        ]

        chat_response = client.chat.complete(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"}
        )
        
        extracted_json_string = chat_response.choices[0].message.content
        return json.loads(extracted_json_string)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f"Mistral API Request Failed: {e}")
        frappe.throw(f"An error occurred while communicating with the Mistral AI service: {e}")


@frappe.whitelist()
def save_costs_and_create_pi(po_name, costs_data, logistic_supplier):
    """
    Saves the verified costs to the Purchase Order's child table and
    creates a draft Purchase Invoice.
    """
    try:
        if isinstance(costs_data, str):
            costs_data = json.loads(costs_data)
            
        po_doc = frappe.get_doc("Purchase Order", po_name)
        po_doc.set("custom_additional_shipping_cost", [])
        total_shipping_cost = 0

        for cost_item in costs_data:
            cost_item = frappe._dict(cost_item)
            if cost_item.amount and float(cost_item.amount) > 0:
                frappe.logger("api").info(f"Adding cost item: {cost_item}")
                po_doc.append("custom_additional_shipping_cost", {
                    "item_code": cost_item.get("item_code"),
                    "description": cost_item.description[:140],
                    "amount": cost_item.amount,
                    "hs_code_tariff_number": cost_item.hs_code,
                    "category": cost_item.category
                })
                total_shipping_cost += float(cost_item.amount)

        po_doc.custom_total_shipping_cost_amount = total_shipping_cost
        po_doc.save(ignore_permissions=True)
        frappe.db.commit()

        pi_name = create_logistics_purchase_invoice(po_doc, total_shipping_cost, logistic_supplier, costs_data)
        return { "status": "success", "pi_name": pi_name }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Save Costs and Create PI Failed")
        frappe.throw(str(e))

def create_logistics_purchase_invoice(source_po, total_amount, logistic_supplier, costs_data):
    if total_amount <= 0:
        return None
    
    invoice_items = []
    for cost in costs_data:
        invoice_items.append({
            "item_code": cost.get("item_code") or "Other Cost",
            "qty": 1,
            "rate": cost.amount,
            "description": cost.description[:140],
        })

    pi = frappe.get_doc({
        "doctype": "Purchase Invoice",
        "supplier": logistic_supplier,
        "posting_date": frappe.utils.today(),
        "due_date": frappe.utils.add_days(frappe.utils.today(), 30),
        "custom_source_purchase_order": source_po.name,
        "items": invoice_items,
    })
    pi.insert(ignore_permissions=True)
    frappe.db.commit()
    return pi.name