import frappe

_FIELDNAME = "taxjar_show_tax_breakdown"


def execute():
	"""Remove "Show Detailed TaxJar Tax Breakdown" from Print Settings.

	The US Sales Tax (Invoice, DN, CN) print format now always prints its
	jurisdiction table when TaxJar charged tax, so nothing reads the field.
	make_custom_fields() no longer creates it, but after_migrate never deletes
	a field it stops listing, so an upgraded site would keep a checkbox that
	does nothing.

	The stored value goes too. Print Settings is a Single, so the value sits in
	the Singles table, where deleting the Custom Field does not reach it.
	"""
	frappe.delete_doc("Custom Field", f"Print Settings-{_FIELDNAME}", ignore_missing=True)
	frappe.db.delete("Singles", {"doctype": "Print Settings", "field": _FIELDNAME})
	frappe.clear_cache(doctype="Print Settings")
