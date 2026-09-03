import frappe

# The Section Break and the HTML field it held. Custom Fields are named
# "{doctype}-{fieldname}".
_FIELDNAMES = ("taxjar_response_section", "taxjar_response_html")


def execute():
	"""Drop the "TaxJar Response" section from the Sales Invoice TaxJar tab.

	The section rendered the last successful TaxJar API Log response as a table.
	Every row in it either duplicated a field already on the form or, in the
	case of "Provider", echoed back a constant this app sends TaxJar on every
	call (TAXJAR_PROVIDER) - so it said nothing about the invoice it sat on.
	Anyone who needs the raw response has the TaxJar API Log, which stores it in
	full.

	Removing the definitions from make_custom_fields() only stops them being
	recreated; after_migrate re-runs that function but never deletes what it no
	longer lists, so already-migrated sites would keep an empty section forever.
	Hence this.
	"""
	for fieldname in _FIELDNAMES:
		name = f"Sales Invoice-{fieldname}"
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, ignore_missing=True)

	frappe.clear_cache(doctype="Sales Invoice")
