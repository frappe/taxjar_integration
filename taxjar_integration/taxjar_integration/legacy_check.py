"""Find out which pre-upgrade invoices TaxJar already holds.

TaxJar version 15 sent an invoice to TaxJar on submit and recorded nothing
about it on the invoice. After the upgrade, every one of those invoices reads
Excluded, including the ones TaxJar holds. The mark_pre_upgrade_invoices patch
gives them the reason EXCLUSION_LEGACY_UNCHECKED, and this module replaces that
reason with the answer TaxJar gives.

The check asks TaxJar for the ids of its orders and refunds, one calendar month
at a time, and matches them to invoice names. Version 15 used the invoice name
as the transaction id. That costs two calls per month of history for each
company, whatever the number of invoices.

The outcome for each invoice:

* submitted, and TaxJar holds it: Synced;
* cancelled, and TaxJar still holds it: Failed, not retryable. Version 15
  deleted the order on cancel, so the delete failed. The Retry button on the
  Transaction Sync page deletes it;
* TaxJar does not hold it: Excluded, with EXCLUSION_LEGACY_NOT_FOUND.

The job state lives on TaxJar Settings: legacy_check_status, the last run time,
and legacy_check_summary, a JSON object with one entry for each company. The
Migration tab renders it.
"""

import hashlib
import json
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.query_builder.functions import Coalesce, Count, Min
from frappe.realtime import get_doctype_room
from frappe.utils import add_months, cint, get_datetime, getdate, now
from frappe.utils.background_jobs import is_job_enqueued

from taxjar_integration.taxjar_integration.access import require_permission
from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
	settings_write_lock,
)
from taxjar_integration.taxjar_integration.taxjar_integration import (
	EXCLUSION_LEGACY_NOT_FOUND,
	EXCLUSION_LEGACY_UNCHECKED,
	LEGACY_PROVIDER,
	_allowed_companies_by_customer,
	_customer_sync_companies,
	_customer_sync_status_fields,
	_enqueue_customer_sync,
	_restrict_companies,
	_sync_status_fields,
	classify_taxjar_error,
	get_client,
	log_taxjar_call,
)

SETTINGS = "TaxJar Settings"
JOB_ID = "taxjar_legacy_check"

# Sent to the open TaxJar Settings form: one event for each month the job
# reads, and one when it ends.
PROGRESS_EVENT = "taxjar_legacy_check_progress"

STATUS_PENDING = "Pending"
STATUS_RUNNING = "Running"
STATUS_DONE = "Done"
STATUS_FAILED = "Failed"

# The result recorded for each company in legacy_check_summary.
RESULT_DONE = "done"
RESULT_FAILED = "failed"
RESULT_NO_CREDENTIAL = "no_credential"

# Rows written in one UPDATE. A name list this long stays far below every
# database's statement limit.
WRITE_BATCH = 500

STALE_CANCEL_ERROR = (
	"Cancelled in ERPNext, but TaxJar still holds this transaction. "
	"Retry to remove it from TaxJar."
)


# ── State the tab reads ───────────────────────────────────────────────────


@frappe.whitelist()
def get_legacy_check_state():
	"""Everything the Migration tab shows."""
	require_permission(SETTINGS, "read")

	values = frappe.db.get_singles_dict(SETTINGS, cast=True)
	status = values.legacy_check_status or STATUS_PENDING
	summary = _load_summary(values.legacy_check_summary)

	# A worker that died mid-run never writes its own end. Without this, the
	# tab would say Running for good and keep the button disabled.
	if status == STATUS_RUNNING and not is_job_enqueued(JOB_ID):
		status = STATUS_FAILED

	pending = {row.company: row for row in _permitted_pending_by_company()}
	companies = []
	for company in sorted(set(pending) | set(summary)):
		row = pending.get(company)
		entry = {
			"company": company,
			"pending": cint(row.invoices) if row else 0,
			"first_month": _month_label(row.first_created) if row else None,
			"has_credential": bool(get_client(company, mode="Live")),
		}
		entry.update(summary.get(company) or {})
		companies.append(entry)

	return {
		"cutoff_date": values.legacy_cutoff_date,
		"cutoff_month": _month_label(values.legacy_cutoff_date),
		"status": status,
		"last_run": values.legacy_check_last_run,
		"api_mode": values.api_mode,
		"companies": companies,
		"pending": sum(entry["pending"] for entry in companies),
	}


def pending_by_company():
	"""For each company: how many invoices still wait for the check, and when
	the first of them was created."""
	if not frappe.db.has_column("Sales Invoice", "taxjar_exclusion_reason"):
		return []

	invoice = frappe.qb.DocType("Sales Invoice")
	return (
		frappe.qb.from_(invoice)
		.select(
			invoice.company,
			Count("*").as_("invoices"),
			Min(invoice.creation).as_("first_created"),
		)
		.where(_is_unchecked(invoice))
		.groupby(invoice.company)
		.run(as_dict=True)
	)


def _permitted_pending_by_company():
	"""pending_by_company(), for only the invoices the caller may read.

	The tab shows these counts to every Settings reader. The job and the
	buttons that start it use pending_by_company(), which covers every company.
	"""
	if not frappe.db.has_column("Sales Invoice", "taxjar_exclusion_reason"):
		return []

	return frappe.get_list(
		"Sales Invoice",
		filters={"docstatus": ["in", [1, 2]], "taxjar_exclusion_reason": EXCLUSION_LEGACY_UNCHECKED},
		fields=["company", {"COUNT": "*", "as": "invoices"}, {"MIN": "creation", "as": "first_created"}],
		group_by="company",
		limit_page_length=0,
	)


def _is_unchecked(invoice):
	return invoice.docstatus.isin([1, 2]) & (invoice.taxjar_exclusion_reason == EXCLUSION_LEGACY_UNCHECKED)


# ── Starting the job ──────────────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])
def run_legacy_check():
	"""The Run Check button."""
	require_permission(SETTINGS, "write")

	if frappe.db.get_single_value(SETTINGS, "api_mode") != "Live":
		frappe.throw(
			_("The check runs in Live mode only. Change API Mode to Live in TaxJar Setup."),
			title=_("Live Mode Required"),
		)

	if not pending_by_company():
		frappe.throw(_("No invoice from before the upgrade waits for the check."), title=_("Nothing to Check"))

	enqueue_legacy_check()
	return {"status": STATUS_RUNNING}


def enqueue_legacy_check():
	"""Queue the check once. A second call while it runs does nothing."""
	if is_job_enqueued(JOB_ID):
		return

	_write_state(legacy_check_status=STATUS_RUNNING)
	frappe.enqueue(
		"taxjar_integration.taxjar_integration.legacy_check.check_legacy_invoices",
		queue="long",
		job_id=JOB_ID,
		deduplicate=True,
		enqueue_after_commit=True,
	)


def enqueue_live_work():
	"""Queue start_live_work() to run once this request commits.

	Called when the guided setup finishes (finish_setup) and when API Mode
	changes to Live (TaxJar Settings on_update). Both are the moment a site
	upgraded from version 15 first has a live token: the upgrade itself
	copies data while the site has no token at all.

	A job, not a call inside the request: both callers can run under
	settings_write_lock, and enqueue_legacy_check() takes the same lock to
	write its status. The file lock does not re-enter. After commit, so the
	job reads the save that queued it.
	"""
	frappe.enqueue(
		"taxjar_integration.taxjar_integration.legacy_check.start_live_work",
		queue="short",
		enqueue_after_commit=True,
	)


def start_live_work():
	"""Background job: start the work that waits for a live token.

	Two pieces, each a no-op where there is nothing to do:

	- a TaxJar sync for each customer whose exemption was never sent;
	- the invoice check, for invoices submitted before the upgrade.

	Live only. The check proves what the live account holds, and the sandbox
	account is a different account.
	"""
	if frappe.db.get_single_value(SETTINGS, "api_mode") != "Live":
		return
	enqueue_unsent_exempt_customers()
	if pending_by_company():
		enqueue_legacy_check()


def enqueue_unsent_exempt_customers():
	"""Queue a TaxJar sync for each customer that holds an exemption but was
	never sent to TaxJar. Returns how many customers were queued.

	copy_legacy_customer_exemption writes the exemption straight to the
	database, on a migrate that runs before the site has a token, so no save
	hook queued a sync. Tax is right without one: each request sends the
	exemption type from these columns. But TaxJar has no customer record
	until something sends it.

	"Never sent" is no TaxJar customer id and no sync status. A customer with
	a status has a sync in hand, or a Failed one the retry cron and the
	Customers page already handle. Queued is written before the jobs, the
	same way the save hook and the Customers page do it, and only for a
	customer with a company to go to.
	"""
	if not frappe.db.has_column("Customer", "taxjar_exemption_type"):
		return 0

	companies = _customer_sync_companies()
	if not companies:
		return 0

	names = _unsent_exempt_customers_query().run(pluck=True)
	allowed = _allowed_companies_by_customer(names)
	queued = 0
	for name in names:
		targets = _restrict_companies(companies, allowed[name])
		if not targets:
			continue
		frappe.db.set_value("Customer", name, _customer_sync_status_fields("Queued"), update_modified=False)
		for company in targets:
			_enqueue_customer_sync(name, company)
		queued += 1
	return queued


def _unsent_exempt_customers_query():
	"""Build the SELECT for enqueue_unsent_exempt_customers(). Returned rather
	than run, so a test can read the statement."""
	customer = frappe.qb.DocType("Customer")
	return (
		frappe.qb.from_(customer)
		.select(customer.name)
		.where(
			(Coalesce(customer.taxjar_exemption_type, "") != "")
			& (Coalesce(customer.taxjar_customer_id, "") == "")
			& (Coalesce(customer.taxjar_customer_sync_status, "") == "")
		)
	)


# ── The job ───────────────────────────────────────────────────────────────


def check_legacy_invoices():
	"""Background job. Check every company that has unchecked invoices."""
	try:
		_check_all_companies()
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title="TaxJar pre-upgrade invoice check failed")
		_write_state(legacy_check_status=STATUS_FAILED, legacy_check_last_run=now())
		# The job runner rolls back after the raise below. Keep the Failed state.
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		_publish({"done": True})
		raise


def _check_all_companies():
	cutoff = getdate(frappe.db.get_single_value(SETTINGS, "legacy_cutoff_date"))
	summary = _load_summary(frappe.db.get_single_value(SETTINGS, "legacy_check_summary"))
	_write_state(legacy_check_status=STATUS_RUNNING, legacy_check_last_run=now())

	# Ids already read, by token and month. Two companies that share one
	# TaxJar account read each month of it once.
	cache = {}
	failed = False

	for row in pending_by_company():
		company = row.company
		# Live, whatever API Mode says now. A switch to Sandbox while the job
		# waits must not record what the sandbox account holds.
		client = get_client(company, mode="Live")
		if not client:
			summary[company] = {"result": RESULT_NO_CREDENTIAL, "invoices": cint(row.invoices)}
			continue

		windows = month_windows(getdate(row.first_created), cutoff)
		try:
			orders, refunds, calls = _read_transaction_ids(client, company, windows, cache)
		except Exception as err:
			info = classify_taxjar_error(err)
			summary[company] = {"result": RESULT_FAILED, "error": info["message"], "invoices": cint(row.invoices)}
			failed = True
			continue

		counts = apply_outcomes(company, orders, refunds)
		summary[company] = {
			"result": RESULT_DONE,
			"first_month": windows[0][0].strftime("%Y-%m") if windows else None,
			"calls": calls,
			**counts,
		}
		_write_state(legacy_check_summary=json.dumps(summary, sort_keys=True))
		# This company's invoices and its counts commit together. A later
		# company that stops the worker cannot leave them with no counts.
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	_write_state(
		legacy_check_status=STATUS_FAILED if failed else STATUS_DONE,
		legacy_check_last_run=now(),
		legacy_check_summary=json.dumps(summary, sort_keys=True),
	)
	# Commit before the realtime events below make the open form read this state.
	frappe.db.commit()  # nosemgrep: frappe-manual-commit

	# One refresh for the Transaction Sync page, not one for each invoice.
	frappe.publish_realtime("taxjar_transactions_update", {}, room=get_doctype_room("Sales Invoice"))
	_publish({"done": True})


def month_windows(start, end):
	"""Calendar months from the month of ``start`` to the month of ``end``,
	as (first day, last day) pairs. The last pair stops at ``end``."""
	if not start or not end or start > end:
		return []

	windows = []
	first = date(start.year, start.month, 1)
	while first <= end:
		last = getdate(add_months(first, 1)) - timedelta(days=1)
		windows.append((first, min(last, end)))
		first = last + timedelta(days=1)
	return windows


def _read_transaction_ids(client, company, windows, cache):
	"""All order ids and refund ids TaxJar holds for these months.

	Version 15 sent the submit date as transaction_date, not the posting date,
	so the windows run on submit dates. The caller starts them at the first
	invoice's creation date, because no invoice is submitted before it exists.
	"""
	token = hashlib.sha256(client.api_key.encode()).hexdigest()
	orders, refunds = set(), set()
	calls = 0

	for index, (first, last) in enumerate(windows, start=1):
		key = (token, first)
		if key not in cache:
			params = {
				"from_transaction_date": first.strftime("%Y/%m/%d"),
				"to_transaction_date": last.strftime("%Y/%m/%d"),
				# Named, not left out. TaxJar's default happens to be the
				# provider version 15 used, and that is the one asked about.
				"provider": LEGACY_PROVIDER,
			}
			cache[key] = (
				_list_ids(client.list_orders, "list_orders", params, company),
				_list_ids(client.list_refunds, "list_refunds", params, company),
			)
			calls += 2

		month_orders, month_refunds = cache[key]
		orders |= month_orders
		refunds |= month_refunds
		_publish({"company": company, "month": index, "months": len(windows)})

	return orders, refunds, calls


def _list_ids(method, action, params, company):
	ctx = {"doctype": "Company", "name": company, "company": company, "check": "pre-upgrade invoices"}
	log_taxjar_call(action=action, status="request", payload=params, context=ctx)
	try:
		# The SDK answers with a TaxJarOrders object, for refunds too. It has no
		# len(), and it is an iterator that a second pass finds empty. One list
		# is read here and counted and used from then on.
		ids = list(method(params) or [])
	except Exception as err:
		log_taxjar_call(action=action, status="error", payload=params, error=classify_taxjar_error(err)["log_detail"], context=ctx)
		raise
	log_taxjar_call(action=action, status="success", payload=params, response={"count": len(ids)}, context=ctx)
	return {str(transaction_id) for transaction_id in ids}


# ── Writing the outcome ───────────────────────────────────────────────────


def apply_outcomes(company, orders, refunds):
	"""Write the outcome on every unchecked invoice of this company.

	A return is matched to the refund ids, and every other invoice to the order
	ids. Returns the count of each outcome.
	"""
	invoices = frappe.get_all(
		"Sales Invoice",
		filters={
			"company": company,
			"docstatus": ("in", (1, 2)),
			"taxjar_exclusion_reason": EXCLUSION_LEGACY_UNCHECKED,
		},
		fields=["name", "docstatus", "is_return"],
	)

	synced, stale, not_found = [], [], []
	for invoice in invoices:
		held = invoice.name in (refunds if invoice.is_return else orders)
		if not held:
			not_found.append(invoice.name)
		elif invoice.docstatus == 2:
			stale.append(invoice.name)
		else:
			synced.append(invoice.name)

	# No last-synced time: the list says that TaxJar holds the transaction, not
	# when it arrived.
	synced_fields = _sync_status_fields("Synced")
	synced_fields.pop("taxjar_last_synced", None)
	_write(synced, {**synced_fields, "taxjar_provider": LEGACY_PROVIDER})

	_write(stale, {
		**_sync_status_fields("Failed", error=STALE_CANCEL_ERROR, retryable=False),
		"taxjar_provider": LEGACY_PROVIDER,
	})

	_write(not_found, {"taxjar_exclusion_reason": EXCLUSION_LEGACY_NOT_FOUND})

	return {
		"checked": len(invoices),
		"found": len(synced),
		"not_found": len(not_found),
		"cancelled_in_taxjar": len(stale),
	}


def _write(names, fields):
	"""Set ``fields`` on these invoices. Only rows that still wait for the
	check are written, so a row someone changed meanwhile keeps its change."""
	invoice = frappe.qb.DocType("Sales Invoice")
	for start in range(0, len(names), WRITE_BATCH):
		batch = names[start : start + WRITE_BATCH]
		query = frappe.qb.update(invoice)
		for fieldname, value in fields.items():
			query = query.set(invoice[fieldname], value)
		query.where(invoice.name.isin(batch) & _is_unchecked(invoice)).run()


# ── Helpers ───────────────────────────────────────────────────────────────


def _write_state(**values):
	# Under the settings lock: a Single is saved as a delete and an insert of
	# all its rows, and a concurrent save would otherwise deadlock with this.
	with settings_write_lock():
		frappe.db.set_single_value(SETTINGS, values)


def _publish(message):
	frappe.publish_realtime(PROGRESS_EVENT, message, doctype=SETTINGS, docname=SETTINGS)


def _load_summary(raw):
	try:
		summary = json.loads(raw or "{}")
	except ValueError:
		return {}
	return summary if isinstance(summary, dict) else {}


def _month_label(value):
	return get_datetime(value).strftime("%Y-%m") if value else None
