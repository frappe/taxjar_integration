import frappe

from taxjar_integration.taxjar_integration.taxjar_integration import (
	TAXJAR_MAX_SYNC_RETRIES,
	_is_taxjar_enabled,
	company_creates_transactions,
	get_client,
)
from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
	fetch_and_insert_categories,
)


def purge_old_api_logs():
	retention_days = frappe.db.get_single_value("TaxJar Settings", "log_retention_days")
	if not retention_days:
		return
	cutoff = frappe.utils.add_days(frappe.utils.today(), -int(retention_days))
	frappe.db.delete("TaxJar API Log", {"creation": ("<", cutoff)})


def sync_nexus_list():
	"""Daily job: refresh nexus regions from TaxJar for all configured companies."""
	doc = frappe.get_doc("TaxJar Settings", "TaxJar Settings")

	if not _is_taxjar_enabled(doc):
		return
	if not doc.company_config:
		return

	try:
		doc.update_nexus_list()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "TaxJar: Nexus sync failed")


def sync_product_tax_categories():
	"""Weekly job: pull TaxJar's current category list and insert any new ones.

	TaxJar doesn't publish a fixed update cadence for categories (added on an ongoing
	basis, not on a schedule), so weekly polling rather than daily. Reuses
	fetch_and_insert_categories() (shared with the manual "Update Product Tax
	Category List" button), which only inserts categories missing by
	product_tax_code - existing rows (and any Item already linked to them) are
	never touched.
	"""
	if not _is_taxjar_enabled():
		return

	client = get_client()
	if not client:
		return

	try:
		fetch_and_insert_categories(client)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "TaxJar: Product tax category sync failed")


def retry_failed_taxjar_syncs():
	"""Every 15 min: re-enqueue Failed Sales Invoices for companies that still have
	transaction filing enabled.

	Only invoices whose last failure was classified retryable - a timeout, a rate
	limit, a TaxJar outage (classify_taxjar_error) - are picked up. A rejection
	the request itself caused, such as a duplicate transaction_id or an exemption
	that contradicts the tax rows, cannot clear on its own; re-sending it every 15
	minutes burns API quota and keeps rewriting Sync Error with whatever TaxJar
	objects to that hour, which reads as an error that "keeps changing". Those wait
	for the Retry button on the Transactions page instead.

	Also capped at TAXJAR_MAX_SYNC_RETRIES consecutive Failed outcomes
	(taxjar_sync_retry_count, bumped by _set_sync_status) - a retryable failure
	that keeps recurring stops being auto-retried too, rather than being
	re-enqueued every 15 minutes forever. The Retry button is unaffected.
	"""
	if not _is_taxjar_enabled():
		return

	failed_invoices = frappe.get_all(
		"Sales Invoice",
		filters={
			"taxjar_sync_status": "Failed",
			"taxjar_sync_retryable": 1,
			"taxjar_sync_retry_count": ("<", TAXJAR_MAX_SYNC_RETRIES),
			"docstatus": ("in", (1, 2)),
		},
		fields=["name", "company"],
		limit=50,
	)

	for invoice in failed_invoices:
		if not company_creates_transactions(invoice.company):
			continue
		frappe.enqueue(
			"taxjar_integration.taxjar_integration.taxjar_integration.sync_transaction_to_taxjar",
			invoice_name=invoice.name,
			queue="short",
			job_id=f"taxjar_retry_{invoice.name}",
			deduplicate=True,
		)


def retry_failed_taxjar_customer_syncs():
	"""Every 15 min: re-enqueue Customers whose last TaxJar sync failed in a way a
	retry could clear - see retry_failed_taxjar_syncs() for why the rest are left
	alone, and for the same TAXJAR_MAX_SYNC_RETRIES cap on consecutive failures."""
	if not _is_taxjar_enabled():
		return

	failed_customers = frappe.get_all(
		"Customer",
		filters={
			"taxjar_customer_sync_status": "Failed",
			"taxjar_customer_sync_retryable": 1,
			"taxjar_customer_sync_retry_count": ("<", TAXJAR_MAX_SYNC_RETRIES),
		},
		pluck="name",
		limit=50,
	)

	taxjar_settings = frappe.get_single("TaxJar Settings")
	for customer_name in failed_customers:
		for config in taxjar_settings.company_config or []:
			if not (config.taxjar_calculate_tax or config.taxjar_create_transactions):
				continue
			frappe.enqueue(
				"taxjar_integration.taxjar_integration.taxjar_integration.sync_customer_to_taxjar",
				customer_name=customer_name,
				company=config.company,
				queue="short",
				job_id=f"taxjar_customer_retry_{customer_name}_{config.company}",
				deduplicate=True,
			)
