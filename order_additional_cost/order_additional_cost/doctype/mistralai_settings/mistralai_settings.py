# Copyright (c) 2025, abiansyahn and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

frappe.utils.logger.set_log_level("DEBUG")
class MistralAISettings(Document):
	def onload(self):
		if frappe.conf.get("mistral_api_key"):
			self.api_key_status = "Configured and Active ✅"
		else:
			self.api_key_status = "Not Configured ❌"
