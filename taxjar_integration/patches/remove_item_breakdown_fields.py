import frappe

_DOCTYPES = ("Sales Invoice Item",)

# The Taxable Amount column. This is the one field a released version of the
# app created on this table, so it is the one a migrated site still carries.
_FIELDNAMES = ("taxable_amount",)


def execute():
	"""Drop the view-only Taxable Amount field from Sales Invoice Item.

	The field was stored on every line and read by no server code at all. What
	is left behind - product_tax_category and tax_collectable - is what the tax
	engine reads: the first feeds product_tax_code on every TaxJar call, the
	second is read back as the per-line sales_tax on create_order. Both are
	moved into the app's own namespace afterwards, as taxjar_product_tax_category
	and taxjar_tax_collectable, by namespace_item_tax_fields.

	Removing the field from make_custom_fields() only stops it being recreated;
	after_migrate re-runs that function but never deletes what it no longer
	lists, so migrated sites would keep the column on the form forever.

	The underlying column is intentionally left in place - deleting a Custom
	Field does not drop its column, and an unused column is cheaper to keep than
	a one-way DDL is to get wrong.
	"""
	for doctype in _DOCTYPES:
		for fieldname in _FIELDNAMES:
			name = f"{doctype}-{fieldname}"
			if frappe.db.exists("Custom Field", name):
				frappe.delete_doc("Custom Field", name, ignore_missing=True)

		frappe.clear_cache(doctype=doctype)
