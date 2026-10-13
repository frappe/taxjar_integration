import frappe

_OLD = "US Sales Tax Invoice"
_NEW = "US Sales Tax (Invoice, DN, CN)"


def execute():
	"""Rename the app's print format to "US Sales Tax (Invoice, DN, CN)".

	The format prints an invoice, a debit note and a credit note, and the new
	name says so.

	Before the model sync. The sync then finds the renamed record and updates
	it from the new JSON. After the sync, the new JSON would make a second
	record, and the old one would stay with no files.

	The rename also changes a Sales Invoice default print format that names the
	old format - see after_rename() in frappe's print_format.py.
	"""
	if not frappe.db.exists("Print Format", _OLD):
		return

	if frappe.db.exists("Print Format", _NEW):
		frappe.delete_doc("Print Format", _OLD, ignore_missing=True, force=True)
		return

	frappe.rename_doc("Print Format", _OLD, _NEW, force=True)
