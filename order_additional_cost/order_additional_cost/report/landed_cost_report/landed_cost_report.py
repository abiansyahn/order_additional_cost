# Copyright (c) 2025, abiansyahn and contributors
# For license information, please see license.txt

import frappe


def execute(filters=None):
	columns = [
		{
			"fieldname": "supplier",
			"label": "Supplier",
			"fieldtype": "Link",
			"options": "Supplier",
		},
		{
			"fieldname": "purchase_order",
			"label": "Purchase Order",
			"fieldtype": "Link",
			"options": "Purchase Order",
		},
		{
			"fieldname": "item_code",
			"label": "Item Code",
			"fieldtype": "Link",
			"options": "Item",
		},
		{
			"fieldname": "item_name",
			"label": "Item Name",
			"fieldtype": "Data",
		},
		{
			"fieldname": "description",
			"label": "Description",
			"fieldtype": "Text",
		},
		{
			"fieldname": "quantity",
			"label": "Quantity",
			"fieldtype": "Float",
		},
		{
			"fieldname": "rate",
			"label": "Rate",
			"fieldtype": "Currency",
		},
		{
			"fieldname": "amount",
			"label": "Amount",
			"fieldtype": "Currency",
		},
		{
			"fieldname": "landed_cost",
			"label": "Landed Cost",
			"fieldtype": "Currency",
		},
		{
			"fieldname": "total_cost",
			"label": "Total Cost",
			"fieldtype": "Currency",
		}
	]

	data = []
	query = """
		SELECT
			po.supplier,
			po.name AS purchase_order,
			poi.item_code,
			poi.item_name,
			poi.description,
			poi.qty AS quantity,
			poi.rate,
			poi.amount,
			po.custom_total_shipping_cost_amount AS landed_cost,
			(poi.amount + po.custom_total_shipping_cost_amount) AS total_cost
		FROM
			`tabPurchase Order` po
		LEFT JOIN
			`tabPurchase Order Item` poi ON po.name = poi.parent
		WHERE
			po.docstatus = 1
			{conditions}
		ORDER BY
			poi.item_code ASC, po.name ASC, po.supplier ASC
		"""
	conditions = []
	if filters:
		if filters.get("from_date"):
			conditions.append("po.transaction_date >= %(from_date)s")
		if filters.get("to_date"):
			conditions.append("po.transaction_date <= %(to_date)s")
		if filters.get("supplier"):
			conditions.append("po.supplier = %(supplier)s")
		if filters.get("item_code"):
			conditions.append("poi.item_code = %(item_code)s")

	if conditions:
		query = query.replace("{conditions}", " AND " + " AND ".join(conditions))
	else:
		query = query.replace("{conditions}", "")

	data = frappe.db.sql(query, filters, as_dict=1)

	return columns, data