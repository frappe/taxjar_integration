import frappe


def execute():
	"""Rename the "Not Applicable" TaxJar sync status to "Excluded".

	"Not Applicable" read as though TaxJar had no opinion about the invoice,
	when it actually means the opposite: TaxJar was asked and the transaction
	was deliberately kept out of it (no nexus, exempt customer, a submitted doc
	whose sync path was never reached). "Excluded" says that.

	The Select's own options are updated from the field definition in
	taxjar_settings.make_custom_fields, which after_migrate re-runs on every
	migrate. Only the already-written row values need fixing here, and a raw
	UPDATE is right for that - this is a pure relabel, so there is nothing for
	the Sales Invoice controller to revalidate, and the table can hold a lot of
	rows.

	Guarded on the column: a site that installed the app but never enabled a
	TaxJar feature has no taxjar_* columns at all, and reading one would raise
	MySQLdb (1054) Unknown column.
	"""
	if not frappe.db.has_column("Sales Invoice", "taxjar_sync_status"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabSales Invoice`
		SET taxjar_sync_status = 'Excluded'
		WHERE taxjar_sync_status = 'Not Applicable'
		"""
	)
