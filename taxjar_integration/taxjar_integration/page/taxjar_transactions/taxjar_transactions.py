import frappe
from frappe import _

from taxjar_integration.taxjar_integration.pagination import (
	PAGE_SIZE,
	not_configured_response,
	paginated_response,
	parse_filters,
	parse_page_size,
	permitted_count,
)
from taxjar_integration.taxjar_integration.taxjar_integration import _publish_transaction_update

# A representative TaxJar custom field; if this column is absent the fields were
# never created, so reads would hit MySQLdb (1054) Unknown column.
_TAXJAR_INVOICE_COLUMN = "taxjar_sync_status"

_DOC_STATUS_LABELS = {0: "Draft", 1: "Submitted", 2: "Cancelled"}

# The page's two tabs: what TaxJar has, and what it does not.
INCLUDED_SCOPE = "included"
EXCLUDED_SCOPE = "excluded"

# Summary-only scopes. The strip counts drafts and submitted docs separately
# even though the Excluded tab lists them together.
SUBMITTED_SCOPE = "submitted"
DRAFT_SCOPE = "draft"

# The statuses a transaction can only reach by actually being sent.
_INCLUDED_STATUSES = ("Synced", "Queued", "Failed")

_SCOPE_CONDITIONS = {
	INCLUDED_SCOPE: {
		"docstatus": ("in", (1, 2)),
		"taxjar_sync_status": ("in", _INCLUDED_STATUSES),
	},
	# Everything TaxJar never received: drafts (nothing syncs before submit,
	# see enqueue_taxjar_sync's on_submit hook) and submitted docs deliberately
	# left out. Deliberately not filtered on docstatus - the two live together
	# here, told apart by the tab's Status column.
	#
	# "not in" rather than "= Excluded" so a row whose status was never written
	# still lands somewhere: frappe wraps a nullable field in IFNULL for this
	# operator (query.py:1971), so a NULL counts as excluded instead of falling
	# out of both tabs.
	EXCLUDED_SCOPE: {"taxjar_sync_status": ("not in", _INCLUDED_STATUSES)},
	SUBMITTED_SCOPE: {"docstatus": ("in", (1, 2))},
	DRAFT_SCOPE: {"docstatus": 0},
}


def _taxjar_invoice_fields_ready():
	return frappe.db.has_column("Sales Invoice", _TAXJAR_INVOICE_COLUMN)


@frappe.whitelist()
def get_transactions(
	filters: dict | str | None = None,
	page: int | str = 1,
	scope: str = INCLUDED_SCOPE,
	page_size: int | str = PAGE_SIZE,
):
	frappe.has_permission("Sales Invoice", "read", throw=True)
	if not _taxjar_invoice_fields_ready():
		return not_configured_response("invoices")

	filters = parse_filters(filters)
	page = max(1, int(page))
	page_size = parse_page_size(page_size)

	conditions = _build_conditions(filters, scope)

	total = permitted_count("Sales Invoice", conditions)

	# get_list, not get_all: get_all defaults to ignore_permissions=True, which
	# would show this page every company's invoices regardless of the caller's
	# User Permissions.
	invoices = frappe.get_list(
		"Sales Invoice",
		filters=conditions,
		fields=[
			"name", "posting_date", "customer_name", "grand_total", "docstatus",
			"is_return", "is_debit_note",
			"taxjar_sync_status", "taxjar_last_synced", "taxjar_sync_error",
		],
		order_by="posting_date desc, name desc",
		start=(page - 1) * page_size,
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
		# the sentence before the part that says what to do about it.
		if row.taxjar_sync_error and len(row.taxjar_sync_error) > 300:
			row["taxjar_sync_error"] = row.taxjar_sync_error[:300] + "..."

	return paginated_response("invoices", invoices, total, page, page_size)


@frappe.whitelist()
def get_summary(filters: dict | str | None = None):
	"""Counts for the summary strip: the submitted/cancelled statuses plus a
	draft total, both under the same company/date/type filters as the table -
	the strip drills into what is on screen, so it has to be scoped the same.
	"""
	frappe.has_permission("Sales Invoice", "read", throw=True)
	if not _taxjar_invoice_fields_ready():
		return not_configured_response()

	filters = parse_filters(filters)
	# The strip is what you drill *from*, so a status drill-down must not feed
	# back into it - honouring it here would collapse every other number to zero
	# the moment one was clicked. Enforced at the endpoint, not just by what the
	# page happens to send.
	filters.pop("sync_status", None)
	filters.pop("excluded_kind", None)

	# Aggregate counts in SQL instead of pulling every row into Python.
	rows = frappe.get_list(
		"Sales Invoice",
		filters=_build_conditions(filters, SUBMITTED_SCOPE),
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
			"total": permitted_count("Sales Invoice", _build_conditions(filters, DRAFT_SCOPE)),
		},
	}


@frappe.whitelist(methods=["POST"])
def bulk_retry(invoices: list | str):
	frappe.has_permission("Sales Invoice", "write", throw=True)
	if not _taxjar_invoice_fields_ready():
		frappe.throw(
			_("TaxJar is not set up yet. Enable a TaxJar feature in TaxJar Settings first."),
			title=_("TaxJar Not Configured"),
		)
	invoices = frappe.parse_json(invoices) if isinstance(invoices, str) else invoices

	# The blanket check above only proves the caller may write *some* Sales
	# Invoice; these names came from the client, and the loop below writes with
	# frappe.db.set_value, which enforces nothing. Checked up front so a partly
	# permitted list is refused rather than half-applied.
	for name in invoices:
		frappe.has_permission("Sales Invoice", "write", doc=name, throw=True)

	queued = 0
	for name in invoices:
		status = frappe.db.get_value("Sales Invoice", name, "taxjar_sync_status")
		if status != "Failed":
			continue

		# Not routed through _set_sync_status: that also nulls
		# taxjar_last_synced, which would discard the real last-sync time on a
		# doc that synced fine and only later failed its cancel-delete.
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
		)
		queued += 1

	return {"queued": queued}


def _build_conditions(filters, scope=INCLUDED_SCOPE):
	conditions = dict(_SCOPE_CONDITIONS.get(scope, _SCOPE_CONDITIONS[INCLUDED_SCOPE]))

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

	if filters.get("sync_status"):
		conditions["taxjar_sync_status"] = filters["sync_status"]

	# Drilled in from the Excluded group of the summary strip: which half of
	# that tab to show.
	excluded_kind = filters.get("excluded_kind")
	if excluded_kind == "Draft":
		conditions["docstatus"] = 0
	elif excluded_kind == "Not Applicable":
		conditions["docstatus"] = ("in", (1, 2))

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
