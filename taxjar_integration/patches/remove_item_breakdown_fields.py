import frappe

_DOCTYPES = ("Sales Invoice Item", "Quotation Item", "Sales Order Item")

# The per-line "TaxJar Tax Detail" section, the JSON behind it, the HTML field
# that rendered it, and the Taxable Amount column beside it.
_FIELDNAMES = (
	"taxjar_item_tax_section",
	"taxjar_item_breakdown_json",
	"taxjar_item_breakdown_html",
	"taxable_amount",
)


def execute():
	"""Drop the view-only TaxJar fields from the sales item child tables.

	What is left behind - product_tax_category and tax_collectable - is what the
	tax engine reads: the first feeds product_tax_code on every TaxJar call, the
	second is read back as the per-line sales_tax on create_order. The four
	removed here were written and never read by any server code:

	- taxable_amount was stored on every line and consumed by nothing at all.
	- taxjar_item_breakdown_json duplicated, per line, a slice of the breakdown
	  already stored whole on the parent's taxjar_breakdown_json.
	- the HTML field and its Section Break existed only to draw that duplicate.

	Removing them from make_custom_fields() only stops them being recreated;
	after_migrate re-runs that function but never deletes what it no longer
	lists, so migrated sites would keep the section forever. Hence this.

	The underlying columns are intentionally left in place - deleting a Custom
	Field does not drop its column, and an unused column is cheaper to keep than
	a one-way DDL is to get wrong.
	"""
	for doctype in _DOCTYPES:
		for fieldname in _FIELDNAMES:
			name = f"{doctype}-{fieldname}"
			if frappe.db.exists("Custom Field", name):
				frappe.delete_doc("Custom Field", name, ignore_missing=True)

		frappe.clear_cache(doctype=doctype)
