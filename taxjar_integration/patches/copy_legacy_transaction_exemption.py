import frappe
from frappe.query_builder.functions import Coalesce

from taxjar_integration.patches.mark_version_15_upgrade import is_version_15_upgrade
from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
	make_custom_fields,
)

# ERPNext's own checkbox sits on these three transaction doctypes, and on
# Customer. A transaction already carries the answer someone gave for that one
# sale, and this app reads its own field instead. The Customer checkbox needs
# regions as well as a type, so copy_legacy_customer_exemption copies it.
_DOCTYPES = ("Quotation", "Sales Order", "Sales Invoice")

# ERPNext's checkbox carries no reason, and this app's field asks for one. The
# honest answer is the one that says no reason was ever recorded.
_EXEMPTION_TYPE = "Other"


def execute():
	"""Copy ERPNext's exempt_from_sales_tax onto this app's own fields.

	ERPNext creates that checkbox for any company registered in the United
	States, whether or not this app is installed, and version 15 of this app
	read it. Version 16 reads taxjar_transaction_exempt instead, and nothing
	reads the old checkbox. So a transaction that someone marked exempt before
	the upgrade would quietly go back to being taxed.

	Every row that already carries this app's own answer is left alone. Only a
	row with the old checkbox ticked and this app's checkbox clear is copied.

	One UPDATE per doctype, for the reason backfill_transaction_nature gives:
	the rows are submitted, a doc.save() migration fights the submitted-document
	rules, and a site can hold a very large number of invoices.

	It runs only on the migrate that upgrades a site from version 15. A site
	already on version 16 also runs this patch once, on the migrate that ships
	it. By then the old checkbox is hidden and nothing reads it, so a tick on it
	is old data.
	"""
	if not is_version_15_upgrade():
		return

	_copy()


def _copy():
	# The columns come from make_custom_fields(), which after_migrate runs after
	# every patch. See backfill_transaction_nature for the same step.
	if not frappe.db.has_column("Sales Invoice", "taxjar_transaction_exempt"):
		make_custom_fields()

	for doctype in _DOCTYPES:
		# ERPNext adds its checkbox only once a company's country is the United
		# States. A site with no US company has no column to read.
		if not frappe.db.has_column(doctype, "exempt_from_sales_tax"):
			continue

		_copy_query(doctype).run()


def _copy_query(doctype):
	"""Build the UPDATE for one doctype. Returned rather than run, so a test can
	read the statement."""
	doc = frappe.qb.DocType(doctype)
	return (
		frappe.qb.update(doc)
		.set(doc.taxjar_transaction_exempt, 1)
		.set(doc.taxjar_transaction_exemption_type, _EXEMPTION_TYPE)
		.where(
			(Coalesce(doc.exempt_from_sales_tax, 0) == 1)
			& (Coalesce(doc.taxjar_transaction_exempt, 0) == 0)
		)
	)
