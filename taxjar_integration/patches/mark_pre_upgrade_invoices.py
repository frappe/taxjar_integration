import frappe
from frappe.query_builder.functions import Coalesce
from frappe.utils import today

from taxjar_integration.taxjar_integration.taxjar_integration import EXCLUSION_LEGACY_UNCHECKED

SETTINGS = "TaxJar Settings"

# Fields only version 15 wrote on TaxJar Settings. Removing a field from a
# Single leaves its rows in tabSingles, so any one of them shows that this site
# ran version 15.
_VERSION_15_FIELDS = (
	"api_key",
	"sandbox_api_key",
	"is_sandbox",
	"tax_account_head",
	"taxjar_create_transactions",
)


def execute():
	"""Mark every invoice submitted under version 15 as not yet checked.

	Version 15 sent invoices to TaxJar on submit and recorded nothing on the
	invoice. When this app added taxjar_sync_status, the column default wrote
	Excluded on every existing row, including the rows TaxJar holds. This patch
	gives those rows the reason EXCLUSION_LEGACY_UNCHECKED, and records the
	upgrade date. legacy_check.py then asks TaxJar which of them it holds.

	One UPDATE, for the reason backfill_transaction_nature gives: the fields are
	read-only and derived, and a site can hold a very large number of invoices.
	"""
	if not _ran_version_15():
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


def _ran_version_15():
	singles = frappe.qb.DocType("Singles")
	return bool(
		frappe.qb.from_(singles)
		.select(singles.field)
		.where((singles.doctype == SETTINGS) & singles.field.isin(_VERSION_15_FIELDS))
		.limit(1)
		.run()
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
