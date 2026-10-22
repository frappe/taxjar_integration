import frappe
from frappe.utils import cint

from taxjar_integration.taxjar_integration.taxjar_integration import (
	TAXJAR_MAX_SYNC_RETRIES,
	_allowed_companies_by_customer,
	_customer_sync_companies,
	_enqueue_customer_removal,
	_is_taxjar_enabled,
	_pending_removals_of,
	_restrict_companies,
	classify_taxjar_error,
	company_scope,
	get_catalogue_client,
	get_client,
	recover_stuck_customer_syncs,
)
from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
	fetch_and_insert_categories,
)


def purge_old_api_logs():
	"""Daily job: drop log rows older than the retention window.

	Zero means keep everything, which the field's own description says. So does
	a negative, which the field refuses (non_negative) but a raw
	db.set_single_value from a console does not: -30 puts the cutoff a month in
	the future and deletes the whole table, this morning's rows included. The
	guard is here as well as on the field because this is the line that deletes.
	"""
	retention_days = cint(frappe.db.get_single_value("TaxJar Settings", "log_retention_days"))
	if retention_days <= 0:
		return
	cutoff = frappe.utils.add_days(frappe.utils.today(), -retention_days)
	frappe.db.delete("TaxJar API Log", {"creation": ("<", cutoff)})


# Where the notification lands: the page that shows the nexus per company and
# the date it last came from TaxJar. Site-relative, because a notification row
# belongs to one site and the host it is read on is not this job's to know.
NEXUS_PAGE_ROUTE = "/desk/taxjar/taxjar-nexus"


def sync_nexus_list():
	"""Daily job: refresh nexus regions from TaxJar for all configured companies."""
	doc = frappe.get_doc("TaxJar Settings", "TaxJar Settings")

	if not _is_taxjar_enabled(doc):
		return
	if not doc.company_config:
		return

	try:
		doc.update_nexus_list()
	except Exception as error:
		frappe.log_error(frappe.get_traceback(), "TaxJar: Nexus sync failed")
		notify_nexus_sync_failure(
			frappe._("TaxJar could not refresh the nexus list: {0}").format(
				classify_taxjar_error(error)["message"]
			)
		)
		return

	skipped = doc.flags.get("nexus_sync_skipped")
	if skipped:
		notify_nexus_sync_failure(
			frappe._("TaxJar refreshed no nexus for {0}. No usable API credential.").format(
				", ".join(sorted(skipped))
			)
		)


def taxjar_user_roles():
	"""Every role with read on TaxJar Settings: the TaxJar User persona, with the
	TaxJar Managers (write) included.

	Who hears about a nexus sync that did not run. Nexus decides whether tax is
	charged at all, so this is an accounting fact before it is an administrative
	one - the accountant is told, not only whoever keeps the site.

	Read from the meta, so the site's own Custom DocPerm rows count. An admin who
	gives a role read on TaxJar Settings makes its holders TaxJar Users, and they
	hear about a failed sync too.
	"""
	return sorted({
		perm.role
		for perm in frappe.get_meta("TaxJar Settings").permissions
		if not perm.permlevel and perm.read
	})


def notify_nexus_sync_failure(message):
	"""Raise a desk notification for every TaxJar User.

	The failure reached the Error Log and nothing else. Nexus decides whether
	tax is charged, so a sync that stops is a sale that stops collecting - and
	the screens that show "Last updated" go on showing an older date with
	nothing saying why.

	Only from the scheduled job. The Update Nexus List button and the guided
	setup both raise their own error to the person who pressed them; notifying
	as well would tell them twice.
	"""
	from frappe.desk.doctype.notification_log.notification_log import (
		enqueue_create_notification,
	)
	from frappe.utils.user import get_users_with_role

	users = sorted({user for role in taxjar_user_roles() for user in get_users_with_role(role)})
	if not users:
		return

	enqueue_create_notification(
		users,
		{
			"type": "Alert",
			# The bell reads `title`; `subject` is what an email carries, for a
			# user who has email notifications on for this type.
			"title": message,
			"subject": message,
			"email_content": frappe._(
				"{0}<br><br>The nexus on file is unchanged, so tax is still "
				"calculated from the regions of the last sync that worked. See "
				'<a href="{1}">Nexus &amp; Product Category</a>.'
			).format(message, NEXUS_PAGE_ROUTE),
			"document_type": "TaxJar Settings",
			"document_name": "TaxJar Settings",
			# Taken before document_type by the desk, so the bell opens the page
			# that shows the nexus rather than the settings form.
			"link": NEXUS_PAGE_ROUTE,
		},
	)


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

	client = get_catalogue_client()
	if not client:
		return

	try:
		fetch_and_insert_categories(client)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "TaxJar: Product tax category sync failed")


# Applied to the jobs a run sends, not to the rows it reads. A row skipped for a
# missing credential must not take one of the places, or 50 such rows would keep
# every other row out of the cron for good.
_RETRIES_PER_TICK = 50


def _companies_with_credential():
	"""A check for "this company has a credential", asked once per company per run.

	The retry crons skip a company with no credential. The job would only fail
	again and add one to the retry count, so after TAXJAR_MAX_SYNC_RETRIES runs
	the record would drop out of the cron. Skipped, it stays in, and the first
	run after an admin adds the credential sends it.
	"""
	cache = {}

	def has_credential(company):
		if company not in cache:
			cache[company] = bool(get_client(company))
		return cache[company]

	return has_credential


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
		limit_page_length=0,
	)

	has_credential = _companies_with_credential()
	sent = 0
	for invoice in failed_invoices:
		if sent >= _RETRIES_PER_TICK:
			break
		if not company_scope(invoice.company).files or not has_credential(invoice.company):
			continue
		sent += 1
		frappe.enqueue(
			"taxjar_integration.taxjar_integration.taxjar_integration.sync_transaction_to_taxjar",
			invoice_name=invoice.name,
			queue="short",
			job_id=f"taxjar_retry_{invoice.name}",
			deduplicate=True,
			enqueue_after_commit=True,
		)


def retry_failed_taxjar_customer_syncs():
	"""Every 15 min: re-enqueue Customers whose last TaxJar sync failed in a way a
	retry could clear - see retry_failed_taxjar_syncs() for why the rest are left
	alone, and for the same TAXJAR_MAX_SYNC_RETRIES cap on consecutive failures.

	Customers stranded at "Queued" are swept into that same set first, before
	the query below reads it, so a row recovered on this tick is also retried
	on this tick rather than waiting another fifteen minutes.
	"""
	if not _is_taxjar_enabled():
		return

	recover_stuck_customer_syncs()

	failed_customers = frappe.get_all(
		"Customer",
		filters={
			"taxjar_customer_sync_status": "Failed",
			"taxjar_customer_sync_retryable": 1,
			"taxjar_customer_sync_retry_count": ("<", TAXJAR_MAX_SYNC_RETRIES),
		},
		pluck="name",
		limit_page_length=0,
	)

	# One shared definition of "a company a customer sync goes to". This loop
	# used to read the two feature flags directly, which skips the
	# United-States test company_scope() applies - so the cron could re-send a
	# customer for a company the save hook itself would never have queued.
	companies = _customer_sync_companies()
	allowed = _allowed_companies_by_customer(failed_customers)

	has_credential = _companies_with_credential()
	sent = 0
	for customer_name in failed_customers:
		if sent >= _RETRIES_PER_TICK:
			break
		ready = [c for c in _restrict_companies(companies, allowed[customer_name]) if has_credential(c)]
		if ready:
			sent += 1
		for company in ready:
			frappe.enqueue(
				"taxjar_integration.taxjar_integration.taxjar_integration.sync_customer_to_taxjar",
				customer_name=customer_name,
				company=company,
				queue="short",
				# deduplicate is safe here, unlike on the save path: this cron
				# re-reads the Failed rows every fifteen minutes, so an enqueue
				# dropped now is simply made again on the next tick. The status
				# it would leave behind is Failed, which is a state something
				# still looks at.
				job_id=f"taxjar_customer_retry_{customer_name}_{company}",
				deduplicate=True,
				enqueue_after_commit=True,
			)


_REMOVALS_PER_TICK = 50
_REMOVAL_CURSOR_KEY = "taxjar_customer_removal_cursor"


def retry_pending_customer_removals():
	"""Every 15 min: queue again each removal that a Customer still holds in
	taxjar_customer_pending_removals - see _remove_from_dropped_companies().

	A removal has no retry count, so a failed one stays pending. Each tick
	starts after the last Customer of the tick before, in name order, and
	starts again from the first when it reaches the end. Without that, 50
	Customers that always fail took every tick, and the rest never had a try.
	"""
	if not _is_taxjar_enabled():
		return

	after = frappe.cache.get_value(_REMOVAL_CURSOR_KEY) or ""
	customers = frappe.get_all(
		"Customer",
		filters=[
			["taxjar_customer_pending_removals", "is", "set"],
			["name", ">", after],
		],
		fields=["name", "taxjar_customer_pending_removals"],
		order_by="name asc",
		limit=_REMOVALS_PER_TICK,
	)
	last = customers[-1].name if len(customers) == _REMOVALS_PER_TICK else ""
	frappe.cache.set_value(_REMOVAL_CURSOR_KEY, last)

	for customer in customers:
		for company in sorted(_pending_removals_of(customer.taxjar_customer_pending_removals)):
			_enqueue_customer_removal(customer.name, company, retry=True)
