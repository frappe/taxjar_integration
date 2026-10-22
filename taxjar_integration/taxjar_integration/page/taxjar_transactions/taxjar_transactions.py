import frappe
from frappe import _
from frappe.utils import cint

from taxjar_integration.taxjar_integration.access import require_permission
from taxjar_integration.taxjar_integration.exporting import send_xlsx
from taxjar_integration.taxjar_integration.pagination import (
	PAGE_SIZE,
	clamp_page,
	not_configured_response,
	parse_document_names,
	paginated_response,
	parse_filters,
	parse_page,
	parse_page_size,
	permitted_count,
)
from taxjar_integration.taxjar_integration.taxjar_integration import (
	DOMESTIC_NATURE,
	EXCLUSION_LEGACY_NOT_FOUND,
	EXCLUSION_LEGACY_UNCHECKED,
	EXPORT_NATURE,
	LEGACY_PROVIDER,
	_publish_transaction_update,
	transaction_exclusion_reason,
)
from taxjar_integration.telemetry import capture

# A representative TaxJar custom field; if this column is absent the fields were
# never created, so reads would hit MySQLdb (1054) Unknown column.
_TAXJAR_INVOICE_COLUMN = "taxjar_sync_status"

_DOC_STATUS_LABELS = {0: "Draft", 1: "Submitted", 2: "Cancelled"}

# What the Nature column holds, and the invoice field it is read from. Both
# defined next to the integration's other invoice fields - see
# set_transaction_nature(), which writes this one on every save.
_NATURE_COLUMN = "taxjar_transaction_nature"

# The page's tabs. Five of them are one per state a transaction can be in, and
# between them they partition the table: every invoice in range lands in exactly
# one, so a row can never go missing by being in none of them. The sixth, All,
# is their union - the tab the page opens on - and so filters on nothing but the
# company/date scope every tab shares.
ALL_SCOPE = "all"
FAILED_SCOPE = "failed"
QUEUED_SCOPE = "queued"
NOT_APPLICABLE_SCOPE = "not_applicable"
DRAFT_SCOPE = "draft"
SYNCED_SCOPE = "synced"

# Summary-only: the strip counts the submitted statuses in one grouped query.
SUBMITTED_SCOPE = "submitted"

# The statuses a transaction can only reach by actually being sent.
_SENT_STATUSES = ("Synced", "Queued", "Failed")

# Cancelled sits with Submitted throughout: it was sent to TaxJar, and the
# cancellation is itself something to have been synced.
_SUBMITTED = ("in", (1, 2))

_SCOPE_CONDITIONS = {
	ALL_SCOPE: {},
	FAILED_SCOPE: {"docstatus": _SUBMITTED, "taxjar_sync_status": "Failed"},
	QUEUED_SCOPE: {"docstatus": _SUBMITTED, "taxjar_sync_status": "Queued"},
	# Submitted and deliberately not sent. "not in" rather than "= Excluded" so
	# a row whose status was never written still lands somewhere: frappe wraps a
	# nullable field in IFNULL for this operator (query.py:1971), so a NULL
	# counts as not applicable instead of falling out of every tab.
	NOT_APPLICABLE_SCOPE: {
		"docstatus": _SUBMITTED,
		"taxjar_sync_status": ("not in", _SENT_STATUSES),
	},
	# Nothing syncs before submit (see enqueue_taxjar_sync's on_submit hook),
	# so a draft's sync status says nothing and is not filtered on.
	DRAFT_SCOPE: {"docstatus": 0},
	SYNCED_SCOPE: {"docstatus": _SUBMITTED, "taxjar_sync_status": "Synced"},
	SUBMITTED_SCOPE: {"docstatus": _SUBMITTED},
}

# What each tab is called on screen. Used to name an export after the tab it
# came from, so two files in a downloads folder say which is which. Stored
# untranslated and passed through _() at the point of use: a module-level _()
# resolves once, in whatever language the first request happened to use.
_SCOPE_LABELS = {
	ALL_SCOPE: "All Transactions",
	FAILED_SCOPE: "Failed",
	QUEUED_SCOPE: "Queued",
	NOT_APPLICABLE_SCOPE: "Excluded",
	DRAFT_SCOPE: "Draft",
	SYNCED_SCOPE: "Synced",
}


def _taxjar_invoice_fields_ready():
	return frappe.db.has_column("Sales Invoice", _TAXJAR_INVOICE_COLUMN)


@frappe.whitelist()
def get_transactions(
	filters: dict | str | None = None,
	page: int | str = 1,
	scope: str = ALL_SCOPE,
	page_size: int | str = PAGE_SIZE,
):
	require_permission("Sales Invoice", "read")
	if not _taxjar_invoice_fields_ready():
		return not_configured_response("invoices")

	filters = parse_filters(filters)
	page = parse_page(page)
	page_size = parse_page_size(page_size)

	conditions = _build_conditions(filters, scope)
	or_filters = _pre_upgrade_filters(filters)

	total = permitted_count("Sales Invoice", conditions, or_filters)
	page = clamp_page(page, total, page_size)
	invoices = _fetch_invoices(conditions, scope, (page - 1) * page_size, page_size, or_filters=or_filters)

	return paginated_response("invoices", invoices, total, page, page_size)


def _fetch_invoices(conditions, scope, start, page_size, truncate_errors=True, or_filters=None):
	"""One window of the table, with everything the table adds to a raw row.

	Shared by the paginated read and the export, so the sheet holds the same
	rows, in the same order, saying the same things as the page it came from.
	"""
	# get_list, not get_all: get_all defaults to ignore_permissions=True, which
	# would show this page every company's invoices regardless of the caller's
	# User Permissions.
	invoices = frappe.get_list(
		"Sales Invoice",
		filters=conditions,
		or_filters=or_filters,
		fields=[
			"name", "posting_date", "customer_name", "grand_total", "docstatus",
			# currency is here for the Grand Total column: it is a Currency
			# field, and without the invoice's own currency beside it the table
			# printed every total with the system default symbol. A foreign
			# invoice then read as the wrong amount of the wrong money.
			"currency",
			"is_return", "is_debit_note", "company",
			# The Nature column, read straight off the invoice. Written on every
			# save by set_transaction_nature() - see its docstring for why this
			# is stored rather than worked out here.
			"taxjar_transaction_nature",
			"taxjar_sync_status", "taxjar_last_synced", "taxjar_sync_error",
			"taxjar_exclusion_reason",
		],
		order_by="posting_date desc, name desc",
		start=start,
		limit_page_length=page_size,
	)

	for row in invoices:
		if row.is_return:
			row["transaction_type"] = "Credit Note"
		elif row.get("is_debit_note"):
			row["transaction_type"] = "Debit Note"
		else:
			row["transaction_type"] = "Sales Invoice"

		row["doc_status"] = _DOC_STATUS_LABELS.get(row.docstatus, "")

		# Shown in full inside a popover, not a table cell, so the cap is only
		# there to keep a runaway message out of the response. 100 used to cut
		# the sentence before the part that says what to do about it. The export
		# carries the whole message: a spreadsheet cell holds it, and there is no
		# popover there to open.
		if truncate_errors and row.taxjar_sync_error and len(row.taxjar_sync_error) > 300:
			row["taxjar_sync_error"] = row.taxjar_sync_error[:300] + "..."

	if scope == NOT_APPLICABLE_SCOPE:
		_explain_exclusions(invoices)
	elif scope == ALL_SCOPE:
		# The All tab holds the excluded rows too, and they are the same rows
		# with the same nothing to say for themselves - so they get the same
		# answer here rather than a bare pill on one tab and an explained one
		# on the other. Only those rows: every other state explains itself.
		_explain_exclusions([row for row in invoices if _is_not_applicable(row)])

	return invoices


def _is_not_applicable(row):
	"""Submitted (or cancelled) and never sent - what the Not Applicable tab holds."""
	return row.docstatus in (1, 2) and row.get("taxjar_sync_status") not in _SENT_STATUSES


def _explain_exclusions(invoices):
	"""Give every excluded row something to say about why it was kept out.

	Two different answers, and the difference matters enough to be flagged rather
	than smoothed over. A row written since enqueue_taxjar_sync started recording
	the reason carries the one that was true when it was submitted. A row written
	before that carries nothing, and the reason cannot be recovered - the
	configuration has moved on since, so reading today's settings and reporting
	them as history would state something that was never true. What can honestly
	be said is what the configuration says now, so that is sent, marked current so
	the client words it in the present tense.

	The live answer is asked once per company rather than once per row - a page
	holds at most page_size rows and usually far fewer companies.
	"""
	inferred = {}

	for row in invoices:
		# The scope is "submitted and not sent", which also catches rows written
		# before the sync status field existed. They are excluded in fact, so the
		# column says so rather than leaving a blank where every other row has a
		# pill.
		if not row.get("taxjar_sync_status"):
			row["taxjar_sync_status"] = "Excluded"

		if row.get("taxjar_exclusion_reason"):
			continue

		if row.company not in inferred:
			inferred[row.company] = transaction_exclusion_reason(row.company)

		if inferred[row.company]:
			row["taxjar_exclusion_reason"] = inferred[row.company]
			row["taxjar_exclusion_reason_is_current"] = 1


@frappe.whitelist()
def get_summary(filters: dict | str | None = None):
	"""Counts for the summary strip: the submitted/cancelled statuses plus a
	draft total, both under the same company/date/type filters as the table -
	the strip drills into what is on screen, so it has to be scoped the same.
	"""
	require_permission("Sales Invoice", "read")
	if not _taxjar_invoice_fields_ready():
		return not_configured_response()

	filters = parse_filters(filters)

	# Aggregate counts in SQL instead of pulling every row into Python.
	or_filters = _pre_upgrade_filters(filters)
	rows = frappe.get_list(
		"Sales Invoice",
		filters=_build_conditions(filters, SUBMITTED_SCOPE),
		or_filters=or_filters,
		fields=["taxjar_sync_status", {"COUNT": "*"}],
		group_by="taxjar_sync_status",
	)
	by_status = {}
	for r in rows:
		status = r.get("taxjar_sync_status")
		by_status[status] = next((v for k, v in r.items() if k != "taxjar_sync_status"), 0)

	return {
		"submitted": {
			"total": sum(by_status.values()),
			"synced": by_status.get("Synced", 0),
			"queued": by_status.get("Queued", 0),
			"failed": by_status.get("Failed", 0),
			"excluded": by_status.get("Excluded", 0),
		},
		"draft": {
			"total": permitted_count("Sales Invoice", _build_conditions(filters, DRAFT_SCOPE), or_filters),
		},
	}


def _sync_status_label(row):
	"""What the Sync Status column shows for this row, in words.

	The twin of render_sync_status_cell in taxjar_transactions.js. An export is
	the table the reader is looking at, so a state is not called one thing on
	the page and another in the file.
	"""
	# Nothing syncs before submit, so whatever a draft holds in the field - by
	# its own default, "Excluded" - is not a report about the document.
	if row.get("docstatus") == 0:
		return _("Submit to Sync")

	status = row.get("taxjar_sync_status")
	if not status:
		return ""

	# On a cancelled row, Failed means the cancellation never reached TaxJar -
	# the order is still filed there, which is the opposite of what "Failed"
	# beside a cancelled transaction reads as.
	if row.get("docstatus") == 2 and status == "Failed":
		return _("Failed to Cancel")

	return _(status)


def _exclusion_reason_label(row):
	"""Why this row was kept out of TaxJar, and whether that is history or now.

	_explain_exclusions marks a reason it read from today's configuration rather
	than from the document itself. The page says that difference with a tense;
	a spreadsheet cell has no room for a sentence, so it says it in a suffix.
	"""
	reason = row.get("taxjar_exclusion_reason")
	if not reason:
		return ""

	if row.get("taxjar_exclusion_reason_is_current"):
		return _("{0} (current setting)").format(_(reason))

	return _(reason)


def _export_columns():
	"""The sheet's columns, in the table's own order.

	Company is here and not in the table: on screen it is a filter above the
	rows, and a file that leaves the site carries no filter row with it. The
	error and the exclusion reason each get a column of their own, because in a
	spreadsheet they are two fields to sort and filter on rather than one
	popover that opens on whichever applies.
	"""
	return [
		{"label": _("Posting Date"), "fieldname": "posting_date"},
		{"label": _("Transaction ID"), "fieldname": "name"},
		{"label": _("Customer"), "fieldname": "customer_name"},
		{"label": _("Type"), "fieldname": "transaction_type"},
		{"label": _("Nature"), "fieldname": _NATURE_COLUMN},
		{"label": _("Company"), "fieldname": "company"},
		{"label": _("Currency"), "fieldname": "currency"},
		{"label": _("Grand Total"), "fieldname": "grand_total"},
		{"label": _("Transaction Status"), "fieldname": "doc_status"},
		{"label": _("Sync Status"), "value": _sync_status_label},
		{"label": _("Last Synced"), "fieldname": "taxjar_last_synced"},
		{"label": _("Sync Error"), "fieldname": "taxjar_sync_error"},
		{"label": _("Exclusion Reason"), "value": _exclusion_reason_label},
	]


@frappe.whitelist(methods=["POST"])
def export_transactions(filters: dict | str | None = None, scope: str = ALL_SCOPE):
	"""Every transaction the open tab holds, under the page's own filters, as one xlsx.

	The same filters and the same scope as get_transactions, with the page
	boundary taken off - so the file is the whole tab rather than the twenty
	rows on screen.

	Answered with a file rather than JSON, so the client reaches it with a form
	POST rather than frappe.xcall.
	"""
	require_permission("Sales Invoice", "read")
	if not _taxjar_invoice_fields_ready():
		frappe.throw(
			_("TaxJar is not set up yet. Enable a TaxJar feature in TaxJar Settings first."),
			title=_("TaxJar Not Configured"),
		)

	filters = parse_filters(filters)
	conditions = _build_conditions(filters, scope)
	or_filters = _pre_upgrade_filters(filters)
	total = permitted_count("Sales Invoice", conditions, or_filters)

	send_xlsx(
		doctype="Sales Invoice",
		filename="{0} - {1}".format(
			_("TaxJar Transactions"), _(_SCOPE_LABELS.get(scope, _SCOPE_LABELS[ALL_SCOPE]))
		),
		columns=_export_columns(),
		# The whole error message, not the 300 characters the popover shows.
		fetch_rows=lambda start, page_size: _fetch_invoices(
			conditions, scope, start, page_size, truncate_errors=False, or_filters=or_filters
		),
		total=total,
		filters=filters,
	)
	capture("taxjar_export_downloaded", page="transactions")


@frappe.whitelist(methods=["POST"])
def bulk_retry(invoices: list | str):
	require_permission("Sales Invoice", "write")
	if not _taxjar_invoice_fields_ready():
		frappe.throw(
			_("TaxJar is not set up yet. Enable a TaxJar feature in TaxJar Settings first."),
			title=_("TaxJar Not Configured"),
		)
	invoices = parse_document_names(invoices, label=frappe._("invoices"))

	# The blanket check above only proves the caller may write *some* Sales
	# Invoice; these names came from the client, and the loop below writes with
	# frappe.db.set_value, which enforces nothing. Checked up front so a partly
	# permitted list is refused rather than half-applied.
	for name in invoices:
		require_permission("Sales Invoice", "write", doc=name)

	queued = 0
	for name in invoices:
		status = frappe.db.get_value("Sales Invoice", name, "taxjar_sync_status")
		if status != "Failed":
			continue

		# Not routed through _set_sync_status: a re-attempt moves the status and
		# nothing else, whereas that would also blank taxjar_sync_error and reset
		# taxjar_sync_retry_count - discarding the count of how many times TaxJar
		# has already rejected this document, which is what caps the cron's
		# automatic retries.
		frappe.db.set_value(
			"Sales Invoice", name, "taxjar_sync_status", "Queued", update_modified=False
		)
		_publish_transaction_update(name, "Queued")
		frappe.enqueue(
			"taxjar_integration.taxjar_integration.taxjar_integration.sync_transaction_to_taxjar",
			invoice_name=name,
			queue="short",
			job_id=f"taxjar_retry_{name}",
			deduplicate=True,
			# The "Queued" status written just above is not committed yet.
			enqueue_after_commit=True,
		)
		queued += 1

	capture("taxjar_transactions_resynced", source="bulk", count=queued)
	return {"queued": queued}


def _build_conditions(filters, scope=ALL_SCOPE):
	conditions = dict(_SCOPE_CONDITIONS.get(scope, _SCOPE_CONDITIONS[ALL_SCOPE]))

	if filters.get("company"):
		conditions["company"] = filters["company"]

	from_date = filters.get("from_date")
	to_date = filters.get("to_date")

	if from_date and to_date:
		conditions["posting_date"] = ("between", (from_date, to_date))
	elif from_date:
		conditions["posting_date"] = (">=", from_date)
	elif to_date:
		conditions["posting_date"] = ("<=", to_date)

	transaction_type = filters.get("transaction_type")
	if transaction_type:
		if transaction_type == "Credit Note":
			conditions["is_return"] = 1
		elif transaction_type == "Debit Note":
			conditions["is_debit_note"] = 1
		else:
			conditions["is_return"] = 0
			conditions["is_debit_note"] = 0

	_add_column_search(conditions, filters)

	return _add_nature_filter(conditions, filters)


def _pre_upgrade_filters(filters):
	"""The OR filters for the pre_upgrade filter, or None when it is off.

	The Migration tab on TaxJar Settings opens this page with pre_upgrade set,
	to show the invoices that legacy_check.py answered or has still to answer.
	The page shows no control for it: it holds the flag only until the user
	leaves the page.

	The check writes LEGACY_PROVIDER on each invoice TaxJar holds, and
	EXCLUSION_LEGACY_NOT_FOUND on each one TaxJar does not hold. A date filter
	cannot select them: the check groups invoices by creation month, and this
	page filters on posting date.
	"""
	if not cint(filters.get("pre_upgrade")):
		return None
	return [
		["taxjar_provider", "=", LEGACY_PROVIDER],
		["taxjar_exclusion_reason", "in", [EXCLUSION_LEGACY_NOT_FOUND, EXCLUSION_LEGACY_UNCHECKED]],
	]


def _add_nature_filter(conditions, filters):
	"""Narrow the result set to exports or to domestic sales, when asked.

	One indexed test on the invoice's own column, which is why
	set_transaction_nature() stores the answer instead of the page working it
	out - see that function for what the stored field replaced.

	Export is the positive test and domestic is everything else, rather than two
	equality tests. A row written before the field existed holds a blank until
	the backfill patch runs, and a blank says nothing about the sale leaving the
	United States. That is the same reading the column always had.
	"""
	nature = filters.get("transaction_nature")
	if nature not in (EXPORT_NATURE, DOMESTIC_NATURE):
		return conditions

	conditions[_NATURE_COLUMN] = (
		("=", EXPORT_NATURE) if nature == EXPORT_NATURE else ("!=", EXPORT_NATURE)
	)
	return conditions


# Columns the inline filter row is allowed to search on. An allowlist, not
# "whatever the client sent" - these land in a database query, and the caller
# is a whitelisted endpoint.
_SEARCHABLE_COLUMNS = ("name", "customer_name")


def _add_column_search(conditions, filters):
	"""Apply the datatable's inline column filters as server-side LIKE terms.

	The filter row narrows the whole result set rather than the loaded page -
	the library's own filtering only ever sees one page of rows, which would
	make a search for something on page 3 look like it does not exist.
	"""
	for fieldname in _SEARCHABLE_COLUMNS:
		value = (filters.get("search") or {}).get(fieldname)
		if value:
			conditions[fieldname] = ("like", f"%{value}%")
