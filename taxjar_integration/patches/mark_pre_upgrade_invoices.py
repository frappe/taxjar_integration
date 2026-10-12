import frappe
from frappe.query_builder.functions import Coalesce
from frappe.utils import today

from taxjar_integration.patches.mark_version_15_upgrade import is_version_15_upgrade
from taxjar_integration.taxjar_integration.taxjar_integration import EXCLUSION_LEGACY_UNCHECKED

SETTINGS = "TaxJar Settings"


def execute():
	"""Mark every invoice submitted under version 15 as not yet checked.

	Version 15 sent invoices to TaxJar on submit and recorded nothing on the
	invoice. When this app added taxjar_sync_status, the column default wrote
	Excluded on every existing row, including the rows TaxJar holds. This patch
	gives those rows the reason EXCLUSION_LEGACY_UNCHECKED, and records the
	upgrade date. legacy_check.py then asks TaxJar which of them it holds.

	One UPDATE, for the reason backfill_transaction_nature gives: the fields are
	read-only and derived, and a site can hold a very large number of invoices.

	It runs only on the migrate that upgrades a site from version 15. A site
	already on version 16 also runs this patch once, on the migrate that ships
	it. Its invoices from before that upgrade can also carry Excluded with no
	reason, and this app has written to them since, so they are left alone.
	"""
	if not is_version_15_upgrade():
		return

	# The columns come from make_custom_fields(), which after_migrate runs after
	# every patch. See backfill_transaction_nature for the same step.
	if not frappe.db.has_column("Sales Invoice", "taxjar_exclusion_reason"):
		from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
			make_custom_fields,
		)

		make_custom_fields()

	_mark_query().run()

	frappe.db.set_single_value(
		SETTINGS,
		{"legacy_cutoff_date": today(), "legacy_check_status": "Pending"},
	)


def _mark_query():
	"""Build the UPDATE that marks the pre-upgrade invoices.

	Only submitted and cancelled rows with no status other than Excluded and no
	reason. A row that holds anything else was written by this app, which
	records what it did.

	Returned rather than run, so a test can read the statement.
	"""
	invoice = frappe.qb.DocType("Sales Invoice")
	return (
		frappe.qb.update(invoice)
		.set(invoice.taxjar_sync_status, "Excluded")
		.set(invoice.taxjar_exclusion_reason, EXCLUSION_LEGACY_UNCHECKED)
		.where(
			invoice.docstatus.isin([1, 2])
			& Coalesce(invoice.taxjar_sync_status, "").isin(["", "Excluded"])
			& (Coalesce(invoice.taxjar_exclusion_reason, "") == "")
		)
	)
