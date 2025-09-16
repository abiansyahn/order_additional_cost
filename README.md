# AI Purchase Order Costs Importer

An ERPNext custom app to automate the extraction of additional costs (like transport and customs duties) from PDF invoices using Mistral AI. The app intelligently matches extracted data to system records and streamlines the creation of the corresponding Purchase Invoice.

## Key Features

-   **"Add Custom and Transport Costs" Button:** A simple button on the Purchase Order form to initiate the workflow.
-   **AI-Powered Data Extraction:** Uses Mistral AI's large language models to read a PDF invoice and extract:
    -   The name of the logistics supplier.
    -   A detailed list of all cost items (description, amount, HS code).
-   **Intelligent Database Matching:**
    -   Performs a fuzzy search to match the extracted supplier name to an existing Supplier in your ERPNext system.
    -   Performs a fuzzy search for each cost description to find and assign the most relevant Item code.
-   **User-Friendly Verification:** Displays all extracted and matched data in a clean popup dialog where the user can verify, edit, and confirm the details.
-   **Automated Document Creation:**
    -   Updates the Purchase Order with a child table of the verified additional costs.
    -   Automatically creates a draft Purchase Invoice linked to the logistics supplier with the correct items and amounts.
-   **Highly Configurable:**
    -   An admin settings page allows you to fine-tune the AI's instructions (the system prompt) without changing any code.
    -   An admin can set a default "fallback" Item for costs that cannot be matched.
-   **Robust Pre-flight Checks:** The app checks that all necessary settings are configured before allowing a user to start the process, preventing errors and frustration.

## Prerequisites

-   A working Frappe Bench.
-   An ERPNext site (developed and tested on v15).
-   A valid API Key from [Mistral AI](https://console.mistral.ai/).

## Installation

1.  **Get the App**
    Navigate to your `frappe-bench` directory and run the following command to download the app from its Git repository.
    ```bash
    # Replace the URL with your actual Git repository URL
    bench get-app [https://github.com/your-username/order_additional_cost.git](https://github.com/your-username/order_additional_cost.git)
    ```

2.  **Install the App**
    Install the app on your desired site.
    ```bash
    # Replace 'your-site.name' with your actual site name
    bench --site your-site.name install-app order_additional_cost
    ```

3.  **Run Migrations & Install Dependencies**
    This command will create the new Doctypes and install the required Python packages from `requirements.txt`.
    ```bash
    bench --site your-site.name migrate
    ```

4.  **Restart the Bench**
    To ensure all changes are loaded, restart the bench.
    ```bash
    bench restart
    ```

## Configuration

After installation, you must configure the following settings for the app to function correctly.

#### 1. Set Mistral AI API Key

You must provide your secret API key.

* **For Local/Private Server:** Add the key to your `site_config.json` file.
    ```json
    // file: ~/frappe-bench/sites/your-site.name/site_config.json
    {
        ...
        "mistral_api_key": "YOUR_SECRET_API_KEY_HERE"
    }
    ```
* **For Frappe Cloud:** Add the key via the Frappe Cloud dashboard.
    1.  Go to your Site's page on the dashboard.
    2.  Click on the **"Configuration"** tab.
    3.  Add a new key named `mistral_api_key` and paste your key as the value.
    4.  Click **"Deploy"** to apply the changes.

#### 2. Configure MistralAI Settings in ERPNext

This app includes a settings page for easy configuration. In the Awesome Bar, search for **"MistralAI Settings"**.

1.  **Set the System Prompt:** Copy the entire prompt text below and paste it into the "System Prompt" field. This tells the AI exactly how to extract data and in what format.

    <details>
    <summary>Click to view the recommended System Prompt</summary>

    ```text
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
    ```
    </details>

2.  **Set the Default Fallback Item:** In the "Default Fallback Item" field, click and select an Item from your system. This Item will be used when the AI extracts a cost description that it cannot match to any existing items.
    * **Note:** You must create a generic "Service" item (e.g., "LOGISTICS-OTHER" or "Other Additional Costs") for this purpose beforehand.

3.  **Save** the settings.

#### 3. (Recommended) Configure Supplier Groups

For the supplier filter to work effectively, ensure your logistics providers (e.g., FedEx, DHL) are assigned to the **"Logistics"** Supplier Group in the Supplier master.

## Usage Workflow

1.  Open a **submitted** Purchase Order.
2.  Click the custom button **"Add Customs & Transport Costs"**.
3.  If the system is not configured correctly, an alert will appear. Otherwise, the dialog window will open.
4.  Click "Attach", select the PDF invoice from the logistics provider, and click "Upload".
5.  The system will show a "Processing" indicator while it performs the following tasks:
    -   Makes the uploaded file accessible.
    -   Calls the Mistral AI API to extract the data.
    -   Performs a fuzzy search to match the supplier and item codes from your database.
6.  The dialog will be automatically filled with the extracted and matched data.
7.  The user can now verify the data, make any necessary edits (e.g., change a matched Item), and then click **"Add Costs & Create Invoice"**.
8.  The system will:
    -   Add the costs to the "Additional Shipping Costs" table on the Purchase Order.
    -   Update the "Total Shipping Cost Amount".
    -   Create a new **draft** Purchase Invoice linked to the logistics supplier containing the cost items.
