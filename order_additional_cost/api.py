import frappe
import json
import os
import requests
from thefuzz import process

@frappe.whitelist()
def check_settings():
    """Checks if all required settings are configured."""
    missing_settings = []
    if not frappe.conf.get("mistral_api_key"):
        missing_settings.append("Mistral API Key has not been set in site_config.json.")
        
    if not frappe.db.get_single_value("MistralAI Settings", "default_item"):
        missing_settings.append("A 'Default Fallback Item' has not been selected in MistralAI Settings.")

    # Check for the VAT template
    if not frappe.db.get_single_value("MistralAI Settings", "standard_service_vat_template"):
        missing_settings.append("A 'Standard Service VAT Template' has not been selected in MistralAI Settings.")

    # Check for account heads
    if not frappe.db.get_single_value("MistralAI Settings", "account_head_for_logistic"):
        missing_settings.append("Account Head for 'Logistics' costs has not been set in MistralAI Settings.")
    if not frappe.db.get_single_value("MistralAI Settings", "account_head_for_tariff"):
        missing_settings.append("Account Head for 'Tariff' costs has not been set in MistralAI Settings.")
    if not frappe.db.get_single_value("MistralAI Settings", "account_head_for_tax"):
        missing_settings.append("Account Head for 'Tax' costs has not been set in MistralAI Settings.")
        
    return missing_settings

@frappe.whitelist()
def process_invoice_pdf(file_url):
    """
    Receives a public file URL, sends it directly to Mistral AI
    for internal OCR and structured data extraction, and returns the result.
    """
    try:
        import base64
        import mimetypes

        # Get the file document directly
        file_doc = frappe.get_doc("File", {"file_url": file_url})
        file_content = file_doc.get_content()
        
        mime_type = mimetypes.guess_type(file_doc.file_name or file_url)[0] or "application/pdf"
        base64_data = base64.b64encode(file_content).decode('utf-8')
        document_to_send = f"data:{mime_type};base64,{base64_data}"

        # Call the updated function that uses Mistral's native document processing
        extracted_data = get_raw_text_from_mistral(document_to_send)

        matched_supplier = find_best_match(extracted_data.get("supplier_name"), "Supplier", "supplier_name")
        invoice_number = extracted_data.get("invoice_number", "")
        invoice_date = extracted_data.get("invoice_date", "")

        cost_with_items = []
        if extracted_data.get("costs"):
            fallback_item = frappe.db.get_single_value("MistralAI Settings", "default_item")
            if not fallback_item:
                frappe.throw("Please set a default item in MistralAI Settings to use when no match is found.")

            keyword_mappings = {d.keyword.lower(): d.item_code for d in frappe.get_all("AI Cost Item Mapping", fields=["keyword", "item_code"])}
            all_items = frappe.get_all("Item", {"disabled": 0, "is_stock_item": 0}, ["name", "item_name", "description"])

            search_choices = {}
            for item in all_items:
                search_texts = item.item_name
                if item.description:
                    search_texts += f" | {item.description}"
                search_choices[search_texts] = item.name
            
            for cost in extracted_data["costs"]:
                new_cost = cost.copy()
                matched_item_code = None
                description = frappe.get_value("Item", fallback_item, "description") or "Other Cost"

                for keyword, item_code in keyword_mappings.items():
                    if keyword in cost.get("description", "").lower():
                        matched_item_code = item_code
                        description = frappe.get_value("Item", item_code, "description") or description
                        break

                if (not matched_item_code or matched_item_code == fallback_item) and search_choices:
                    best_match_tuple = process.extractOne(cost.get("description"), list(search_choices.keys()), score_cutoff=80)
                    if best_match_tuple:
                        matched_search_text = best_match_tuple[0]
                        matched_item_code = search_choices[matched_search_text]
                        description = frappe.get_value("Item", matched_item_code, "description") or description

                new_cost["item_code"] = matched_item_code or fallback_item
                new_cost["item_description"] = description
                cost_with_items.append(new_cost)
        
        return {
            "matched_supplier": matched_supplier,
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
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

    default_system_prompt = """
    You are an expert data extraction assistant. You will be given a URL to a document.
    Your task is to read the document and extract the logistics company's name (e.g., FedEx, DHL) and
    all cost-related line items, such as transport fees, customs duties, handling fees, etc.
    Analyze the description of each cost.
    Important Rules:
    1. Ignore any lines that represent a subtotal or grand total (e.g., 'Gesamtsumme', 'Total', 'Summe'). Only extract individual cost line items.
    2. Ignore any line item that is a standard VAT calculation (Umsatzsteuer/USt.) on another service fee listed in the same invoice. The system will calculate this automatically. Only extract the primary costs themselves.
    3. Extract the Invoice Date in YYYY-MM-DD format.
    
    Use these rules for categorization:
    - 'Tariff': Use for customs duties specifically related to importing goods.
    - 'Tax': Use for other government levies like VAT, GST, or sales tax.
    - 'Logistics': Use for all other costs related to transport, freight, handling, insurance, etc.

    Provide the output as a single, valid JSON object with these keys:
    - "supplier_name": String.
    - "invoice_number": String.
    - "invoice_date": String (Format: YYYY-MM-DD).
    - "costs": List of objects (
        "description": A string describing the cost (e.g., "Transport", "Customs Duty").,
        "amount": A number representing the cost amount.,
        "hs_code": A string for the HS/Tariff code if available, otherwise an empty string "".,
        "category": A string classifying the cost into one of three types: 'Tariff', 'Tax', or 'Logistics'.,
    ).
    
    Example:
    {
        "supplier_name": "FedEx Express",
        "invoice_number": "9988776655",
        "invoice_date": "2025-05-13",
        "costs": [
            { "description": "International Priority Freight", "amount": 150.75, "hs_code": "85171200", "category": "Logistics" },
            { "description": "Customs Duty", "amount": 75.00, "hs_code": "87032100", "category": "Tariff" },
            { "description": "Customs Handling Fee", "amount": 45.50, "hs_code": "" }
        ]
    }
    """

    custom_prompt = frappe.db.get_single_value("MistralAI Settings", "system_prompt")

    system_prompt = custom_prompt or default_system_prompt
    
    user_prompt_text = "Please extract the supplier name and all cost line items from the provided logistics invoice document."

    try:
        url = "https://api.mistral.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        payload = {
            "model": model_name,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt_text},
                        {"type": "document_url", "document_url": document_url}
                    ]
                }
            ]
        }

        response = requests.post(url, headers=headers, json=payload, timeout=90)
        response.raise_for_status()
        
        data = response.json()
        extracted_json_string = data["choices"][0]["message"]["content"]
        return json.loads(extracted_json_string)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f"Mistral API Request Failed: {e}")
        frappe.throw(f"An error occurred while communicating with the Mistral AI service: {e}")


@frappe.whitelist()
def save_costs_and_create_pi(po_name, costs_data, logistic_supplier, bill_no=None, bill_date=None):
    """
    Saves the verified costs to the Purchase Order's child table and
    creates a draft Purchase Invoice.
    """
    try:
        if isinstance(costs_data, str):
            costs_data = json.loads(costs_data)
            
        po_doc = frappe.get_doc("Purchase Order", po_name)
        total_shipping_cost = float(po_doc.custom_total_shipping_cost_amount or 0.0)

        for cost_item in costs_data:
            cost_item = frappe._dict(cost_item)
            if cost_item.amount and float(cost_item.amount) > 0:
                frappe.logger("api").info(f"Adding cost item: {cost_item}")
                po_doc.append("custom_additional_shipping_cost", {
                    "item_code": cost_item.item_code,
                    "description": cost_item.description[:140],
                    "amount": cost_item.amount,
                    "hs_code_tariff_number": cost_item.hs_code,
                    "category": cost_item.category,
                    "invoice_no": bill_no
                })
                total_shipping_cost += float(cost_item.amount)

        po_doc.custom_total_shipping_cost_amount = total_shipping_cost
        po_doc.save(ignore_permissions=True)

        try:
            fallback_item = frappe.db.get_single_value("MistralAI Settings", "default_item")
            
            for item in costs_data:
                item = frappe._dict(item)
                
                if item.description and item.item_code and item.item_code != fallback_item:
                    keyword = item.description.split(" ")[0].lower()

                    exists = frappe.db.exists("AI Cost Item Mapping", {"keyword": keyword})
                    
                    if not exists:
                        new_mapping = frappe.get_doc({
                            "doctype": "AI Cost Item Mapping",
                            "keyword": keyword,
                            "item_code": item.item_code
                        })
                        new_mapping.insert(ignore_permissions=True)
                        frappe.db.commit()
        except Exception as e:
            frappe.logger("api").error(f"Failed to create keyword mapping: {e}")
        frappe.db.commit()

        frappe.logger("api").info(f"Creating Purchase Invoice for PO {po_name} with total shipping cost {total_shipping_cost} from supplier {logistic_supplier}")
        pi_name = create_logistics_purchase_invoice(po_doc, total_shipping_cost, logistic_supplier, costs_data, bill_no, bill_date)
        return { "status": "success", "pi_name": pi_name }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Save Costs and Create PI Failed")
        frappe.throw(str(e))

def create_logistics_purchase_invoice(source_po, total_amount, logistic_supplier, costs_data, bill_no=None, bill_date=None):
    if total_amount <= 0:
        return None
    
    invoice_items = []
    invoice_taxes = []

    cost_center = source_po.cost_center
    service_vat_template =  frappe.db.get_single_value("MistralAI Settings", "standard_service_vat_template")
    
    for cost in costs_data:
        cost = frappe._dict(cost)
        category = cost.get("category")

        if category in ["Tariff", "Logistics"]:
            item_dict = {
                "item_code": cost.get("item_code"),
                "description": cost.get("description"),
                "qty": 1,
                "rate": cost.get("amount"),
                "cost_center": cost_center,
            }
            account = None
            if category == "Tariff":
                account = frappe.db.get_single_value("MistralAI Settings", "account_head_for_tariff")
                item_dict["expense_account"] = account
            elif category == "Logistics":
                account = frappe.db.get_single_value("MistralAI Settings", "account_head_for_logistic")
                item_dict["expense_account"] = account
                if service_vat_template:
                    item_dict["items_tax_template"] = service_vat_template
            invoice_items.append(item_dict)
        elif category == "Tax":
            tax_account = None
            tax_account = frappe.db.get_single_value("MistralAI Settings", "account_head_for_tax")
            invoice_taxes.append({
                "charge_type": "Actual",
                "account_head": tax_account,
                "tax_amount": cost.get("amount"),
                "description": cost.get("description"),
                "cost_center": cost_center
            })

    if not invoice_items:
        frappe.throw("Cannot create Purchase Invoice: No valid items found for logistics or tariff categories.")

    pi = frappe.get_doc({
        "doctype": "Purchase Invoice",
        "supplier": logistic_supplier,
        "posting_date": frappe.utils.today(),
        "due_date": frappe.utils.add_days(frappe.utils.today(), 30),
        "custom_source_purchase_order": source_po.name,
        "custom_po_no": source_po.name,
        "bill_no": bill_no,
        "bill_date": bill_date,
        "custom_transport_invoice": 1,
        "items": invoice_items,
        "taxes": invoice_taxes,
    })
    pi.insert(ignore_permissions=True)
    frappe.db.commit()
    return pi.name

@frappe.whitelist()
def learn_from_corrections(corrections):
    """
    Receives user corrections and creates new, high-quality keyword mappings.
    A correction is a dict with {'description': ai_text, 'item_code': user_selected_item}
    """
    if not corrections:
        return

    try:
        for correction in corrections:
            correction = frappe._dict(correction)

            if not (correction.description and correction.item_code):
                continue
            
            item_doc = frappe.get_doc("Item", correction.item_code)
            
            item_text = (item_doc.name + " " + (item_doc.description or "")).lower()
            item_words = set(item_text.split())
            
            ai_words = set(correction.description.lower().split())
            
            common_words = item_words.intersection(ai_words)
            
            for keyword in common_words:
                if len(keyword) <= 2:
                    continue

                exists = frappe.db.exists("AI Cost Item Mapping", {"keyword": keyword, "item_code": correction.item_code})
                
                if not exists:
                    new_mapping = frappe.get_doc({
                        "doctype": "AI Cost Item Mapping",
                        "keyword": keyword,
                        "item_code": correction.item_code
                    })
                    new_mapping.insert(ignore_permissions=True)
        
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"Failed to create self-learning item mapping: {e}", "AI Self-Learning Error")