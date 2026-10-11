import frappe
from frappe import _

from taxjar_integration.taxjar_integration.access import require_permission
from taxjar_integration.taxjar_integration.exporting import send_xlsx
from taxjar_integration.taxjar_integration.pagination import (
	PAGE_SIZE,
	clamp_page,
	parse_document_names,
	not_configured_response,
	paginated_response,
	parse_filters,
	parse_page,
	parse_page_size,
	permitted_count,
)
from taxjar_integration.taxjar_integration.taxjar_integration import (
	TAXJAR_QUEUED_STUCK_MINUTES,
	_EXEMPTION_TYPES_REQUIRING_REGIONS,
	_allowed_companies_by_customer,
	_customer_sync_companies,
	_customer_sync_status_fields,
	_enqueue_customer_sync,
	_publish_customer_update,
	_restrict_companies,
)

# A representative TaxJar custom field; if this column is absent the fields were
# never created, so reads would hit MySQLdb (1054) Unknown column.
_TAXJAR_CUSTOMER_COLUMN = "taxjar_exemption_type"

# The page's four tabs. Whether an exemption is configured is the tab's job,
# not a filter - which is why there is no "__not_set" exemption filter value.
ALL_SCOPE = "all"
EXEMPT_SCOPE = "exempt"
NON_EXEMPT_SCOPE = "non_exempt"
NOT_CONFIGURED_SCOPE = "not_configured"

# "Non Exempt" is a configured answer, not an exemption - _customer_master_exemption()
# reads it the same way - so it gets its own tab rather than folding into
# Exempted or Not Configured.
_NON_EXEMPT = "Non Exempt"

# NOT the tempting ("not in", ("", None)) / ("in", ("", None)) pair. SQL
# evaluates `x NOT IN ('', NULL)` to NULL for every row, so the Exempted tab
# matched nothing at all; and `x IN ('', NULL)` never matches a genuinely NULL
# column, so the Not Configured tab silently dropped any customer whose field
# was never written. "is set"/"is not set" compile to an IFNULL comparison, and
# a NOT IN list with no NULL in it excludes NULL rows correctly.
_NOT_SET = ("is", "not set")
_EXEMPT = ("not in", ("", _NON_EXEMPT))

_SCOPE_CONDITIONS = {
	ALL_SCOPE: {},
	EXEMPT_SCOPE: {"taxjar_exemption_type": _EXEMPT},
	NON_EXEMPT_SCOPE: {"taxjar_exemption_type": _NON_EXEMPT},
	NOT_CONFIGURED_SCOPE: {"taxjar_exemption_type": _NOT_SET},
}

# What each tab is called on screen. Used to name an export after the tab it
# came from, so two files in a downloads folder say which is which. Stored
# untranslated and passed through _() at the point of use: a module-level _()
# resolves once, in whatever language the first request happened to use.
_SCOPE_LABELS = {
	ALL_SCOPE: "All",
	EXEMPT_SCOPE: "Exempted",
	NON_EXEMPT_SCOPE: "Non-Exempted",
	NOT_CONFIGURED_SCOPE: "Not Configured",
}


def _taxjar_customer_fields_ready():
	return frappe.db.has_column("Customer", _TAXJAR_CUSTOMER_COLUMN)


def _build_conditions(filters, scope=ALL_SCOPE):
	conditions = dict(_SCOPE_CONDITIONS.get(scope, _SCOPE_CONDITIONS[ALL_SCOPE]))

	if filters.get("sync_status"):
		if filters["sync_status"] == "__not_set":
			conditions["taxjar_customer_sync_status"] = _NOT_SET
		else:
			conditions["taxjar_customer_sync_status"] = filters["sync_status"]

	_add_column_search(conditions, filters)

	return conditions


# Columns the inline filter row is allowed to search on. An allowlist, not
# "whatever the client sent" - these land in a database query, and the caller
# is a whitelisted endpoint.
_SEARCHABLE_COLUMNS = ("customer_name", "customer_group", "taxjar_customer_id")


def _add_column_search(conditions, filters):
	"""Apply the datatable's inline column filters as server-side LIKE terms.

	The filter row narrows the whole result set rather than the loaded page -
	the library's own filtering only ever sees one page of rows, which would
	make a search for someone on page 3 look like they do not exist. This page
	has no header search at all, so this is the only way to find a customer.
	"""
	for fieldname in _SEARCHABLE_COLUMNS:
		value = (filters.get("search") or {}).get(fieldname)
		if value:
			conditions[fieldname] = ("like", f"%{value}%")


def _ensure_taxjar_customer_fields():
	if not _taxjar_customer_fields_ready():
		frappe.throw(
			_("TaxJar is not set up yet. Enable a TaxJar feature in TaxJar Settings first."),
			title=_("TaxJar Not Configured"),
		)


@frappe.whitelist()
def get_customers(
	filters: dict | str | None = None,
	page: int | str = 1,
	scope: str = ALL_SCOPE,
	page_size: int | str = PAGE_SIZE,
):
	require_permission("Customer", "read")
	if not _taxjar_customer_fields_ready():
		return not_configured_response("customers")

	filters = parse_filters(filters)
	page = parse_page(page)
	page_size = parse_page_size(page_size)

	conditions = _build_conditions(filters, scope)

	total = permitted_count("Customer", conditions)
	page = clamp_page(page, total, page_size)
	customers = _fetch_customers(conditions, (page - 1) * page_size, page_size)

	return paginated_response("customers", customers, total, page, page_size)


def _fetch_customers(conditions, start, page_size):
	"""One window of the table, with everything the table adds to a raw row.

	Shared by the paginated read and the export, so the sheet holds the same
	rows, in the same order, saying the same things as the page it came from.
	"""
	# get_list, not get_all - see the note in the Transaction Sync page.
	customers = frappe.get_list(
		"Customer",
		filters=conditions,
		fields=[
			"name", "customer_name", "customer_group",
			"taxjar_exemption_type", "taxjar_customer_id",
			"taxjar_customer_sync_status", "taxjar_customer_sync_error",
			"taxjar_customer_sync_queued_at",
		],
		order_by="customer_name asc",
		start=start,
		limit_page_length=page_size,
	)

	# Every row's regions in one query instead of one per row. The count is
	# derived from them rather than grouped separately, because the Exempted
	# Regions cell also names them on hover - one page of customers holds at
	# most a few hundred codes, so a second round trip per hover would cost
	# more than carrying them here.
	#
	# get_all rather than get_list here on purpose: get_list drops the `parent`
	# column from a child-table select, which is the one field this grouping
	# needs. It stays permission-correct because `names` came out of the
	# permission-aware Customer query above, so nothing outside the caller's
	# visibility can be read.
	names = [c["name"] for c in customers]
	regions_by_customer = {}
	if names:
		for row in frappe.get_all(
			"TaxJar Customer Exempt Region",
			filters={"parenttype": "Customer", "parent": ("in", names)},
			fields=["parent", "country", "state"],
			order_by="state asc",
		):
			regions_by_customer.setdefault(row["parent"], []).append(
				{"country": row["country"], "state": row["state"]}
			)

	stalled_before = frappe.utils.add_to_date(
		frappe.utils.now(), minutes=-TAXJAR_QUEUED_STUCK_MINUTES
	)

	for c in customers:
		regions = regions_by_customer.get(c["name"], [])
		c["exempt_regions"] = regions
		c["exempt_region_count"] = len(regions)
		c["taxjar_sync_stalled"] = _is_sync_stalled(c, stalled_before)

	return customers


def _is_sync_stalled(customer, stalled_before):
	"""Whether this customer has waited far longer than a sync takes.

	"Queued" is a promise that a job is coming, and this page used to keep
	showing it in calm blue long after that stopped being true. A worker that
	cannot start takes every job with it - a half-applied framework update is
	enough, and one on this bench did exactly that - including the job that
	would have recovered this row. The answer on screen stayed "Queued"
	indefinitely, with nothing to act on and nothing saying anything was wrong.

	Worked out on read, by the request the browser makes, rather than stored by
	a job. That is the whole point: it has to stay true when nothing in the
	background is running, which is the one condition it exists to report.

	recover_stuck_customer_syncs() asks the same question against the same
	cutoff and turns the row into a Failed one the retry cron owns. This says
	the same thing on screen straight away, and without a queue.
	"""
	if customer.get("taxjar_customer_sync_status") != "Queued":
		return False

	queued_at = customer.get("taxjar_customer_sync_queued_at")
	# A row queued before that field existed has no timestamp to judge, and has
	# certainly waited longer than the cutoff.
	return not queued_at or str(queued_at) < str(stalled_before)


@frappe.whitelist()
def get_summary(filters: dict | str | None = None):
	"""Counts for the summary strip. Scoped by the same filters as the table so
	the strip always describes what is on screen.
	"""
	require_permission("Customer", "read")
	if not _taxjar_customer_fields_ready():
		return not_configured_response()

	filters = parse_filters(filters)
	# The strip is what you drill *from* - see the note in the Transaction Sync
	# get_summary. A status drill-down must not narrow the counts it came from.
	filters.pop("sync_status", None)

	exempt_conditions = _build_conditions(filters, EXEMPT_SCOPE)
	rows = frappe.get_list(
		"Customer",
		filters=exempt_conditions,
		fields=["taxjar_customer_sync_status", {"COUNT": "*"}],
		group_by="taxjar_customer_sync_status",
	)
	by_status = {}
	for r in rows:
		status = r.get("taxjar_customer_sync_status")
		by_status[status] = next(
			(v for k, v in r.items() if k != "taxjar_customer_sync_status"), 0
		)

	return {
		"total": permitted_count("Customer", _build_conditions(filters, ALL_SCOPE)),
		"exempt": {
			"total": sum(by_status.values()),
			"synced": by_status.get("Synced", 0),
			"queued": by_status.get("Queued", 0),
			"failed": by_status.get("Failed", 0),
		},
		"non_exempt": permitted_count("Customer", _build_conditions(filters, NON_EXEMPT_SCOPE)),
		"not_configured": permitted_count(
			"Customer", _build_conditions(filters, NOT_CONFIGURED_SCOPE)
		),
	}


@frappe.whitelist()
def get_exempt_regions(customer: str):
	require_permission("Customer", "read", doc=customer)

	# get_all on a child table, gated by the doc-level Customer check above -
	# get_list would need a parent_doctype and still resolve to the same rows.
	regions = frappe.get_all(
		"TaxJar Customer Exempt Region",
		filters={"parent": customer, "parenttype": "Customer"},
		fields=["country", "state"],
	)
	return regions


# The statuses the page draws a coloured pill for. Anything else means no
# TaxJar customer was ever created to sync, which the table names rather than
# leaving blank - see render_sync_status_cell in taxjar_customers.js.
_PILL_STATUSES = ("Synced", "Queued", "Failed")


def _sync_status_label(row):
	"""What the Sync Status column shows for this row, in words.

	The twin of render_sync_status_cell in taxjar_customers.js. An export is the
	table the reader is looking at, so a state is not called one thing on the
	page and another in the file.
	"""
	status = row.get("taxjar_customer_sync_status")
	return _(status) if status in _PILL_STATUSES else _("NA")


def _region_codes(row):
	"""The exempt regions as codes, one cell: "US-CA, US-NY, CA-ON".

	The table names them in full inside a hover card. A cell has no hover, and a
	list of fifty full names would not be read in one either, so the file carries
	the codes - short enough to sit in a column and exact enough to look up.
	"""
	return ", ".join(
		"{0}-{1}".format(region["country"], region["state"])
		for region in (row.get("exempt_regions") or [])
	)


def _export_columns():
	"""The sheet's columns, in the table's own order.

	The Customer ID is here and not in the table: on screen the customer name
	links to the document, and a file carries no link. The region codes sit
	beside their count for the same reason - the count is a hover trigger on the
	page, and a cell cannot be hovered.
	"""
	return [
		{"label": _("Customer ID"), "fieldname": "name"},
		{"label": _("Customer Name"), "fieldname": "customer_name"},
		{"label": _("Customer Group"), "fieldname": "customer_group"},
		{"label": _("TaxJar Customer ID"), "fieldname": "taxjar_customer_id"},
		{"label": _("Exemption Type"), "fieldname": "taxjar_exemption_type"},
		{"label": _("Exempted Regions"), "fieldname": "exempt_region_count"},
		{"label": _("Exempted Region Codes"), "value": _region_codes},
		{"label": _("Sync Status"), "value": _sync_status_label},
		{"label": _("Sync Error"), "fieldname": "taxjar_customer_sync_error"},
	]


@frappe.whitelist(methods=["POST"])
def export_customers(filters: dict | str | None = None, scope: str = ALL_SCOPE):
	"""Every customer the open tab holds, under the page's own filters, as one xlsx.

	The same filters and the same scope as get_customers, with the page boundary
	taken off - so the file is the whole tab rather than the twenty rows on
	screen. The sync status drill-down is part of those filters, because the
	table honours it too.

	Answered with a file rather than JSON, so the client reaches it with a form
	POST rather than frappe.xcall.
	"""
	require_permission("Customer", "read")
	_ensure_taxjar_customer_fields()

	filters = parse_filters(filters)
	conditions = _build_conditions(filters, scope)
	total = permitted_count("Customer", conditions)

	send_xlsx(
		doctype="Customer",
		filename="{0} - {1}".format(
			_("TaxJar Customers"), _(_SCOPE_LABELS.get(scope, _SCOPE_LABELS[ALL_SCOPE]))
		),
		columns=_export_columns(),
		fetch_rows=lambda start, page_size: _fetch_customers(conditions, start, page_size),
		total=total,
		filters=filters,
	)


def _check_each(customers):
	"""Assert write permission on every named customer before touching any.

	The blanket has_permission() at the top of each bulk endpoint only proves
	the caller may write *some* Customer; the names come from the client. This
	checks up front rather than inside the mutation loop so a caller who is
	only allowed half the list gets a clean refusal instead of a half-applied
	bulk edit.
	"""
	for name in customers:
		require_permission("Customer", "write", doc=name)


@frappe.whitelist(methods=["POST"])
def configure_exemption(
	customers: list | str,
	exemption_type: str,
	regions: list | str | None = None,
):
	"""Write the exemption type and its exempt regions together, for one or
	many customers.

	Deliberately one endpoint rather than the previous separate
	save_exemption_type / save_exempt_regions / bulk_set_exemption_type: those
	could disagree. Clearing the type through save_exemption_type left the
	child region rows behind, so a customer could hold exempt regions that
	nothing in the UI would ever show again. Type and regions are one decision,
	so they are one write.

	Saving is what triggers the sync - on_customer_update enqueues it when a
	TaxJar field actually changed - so there is no separate "send to TaxJar"
	step for the caller to remember.
	"""
	require_permission("Customer", "write")
	_ensure_taxjar_customer_fields()

	customers = parse_document_names(customers, label=frappe._("customers"))
	regions = frappe.parse_json(regions) if isinstance(regions, str) else (regions or [])
	_check_each(customers)

	# Only three types are scoped to regions. A blank type is no exemption at
	# all, and "Non Exempt" is one global answer: the customer pays sales tax
	# everywhere. A region under either is meaningless, so it is dropped rather
	# than orphaned.
	#
	# Dropped here, not only in the dialog that usually sends this: the payload
	# sync_customer_to_taxjar builds reads the region table whatever the type
	# says, so a row left behind here travels to TaxJar and sits there under a
	# non_exempt customer.
	if exemption_type not in _EXEMPTION_TYPES_REQUIRING_REGIONS:
		regions = []

	return _apply_exemption(customers, exemption_type or "", regions)


@frappe.whitelist(methods=["POST"])
def bulk_clear_exemption(customers: list | str):
	require_permission("Customer", "write")
	_ensure_taxjar_customer_fields()
	customers = parse_document_names(customers, label=frappe._("customers"))
	_check_each(customers)

	return _apply_exemption(customers, "", [])


# Above this many customers the edit goes to a background job. Each one is a full
# document save, and every save fires on_customer_update, which enqueues a TaxJar
# sync per configured company - so a hundred selected customers is a hundred saves
# and a couple of hundred enqueues. Inline, that runs past the point where a
# request should have answered; the page has a realtime channel already and can
# report progress on it.
_INLINE_EXEMPTION_LIMIT = 10


def _write_exemption(name, exemption_type, regions):
	doc = frappe.get_doc("Customer", name)
	doc.taxjar_exemption_type = exemption_type
	doc.set("taxjar_exempt_regions", [])
	for region in regions:
		doc.append("taxjar_exempt_regions", {"country": region["country"], "state": region["state"]})
	doc.save()


def apply_exemption_in_background(customers, exemption_type, regions):
	"""Background worker for a bulk exemption edit. Not whitelisted: the endpoint
	above has already checked write permission on every name."""
	for name in customers:
		try:
			_write_exemption(name, exemption_type, regions)
		except Exception:
			# One customer's failure is not the batch's. Logged per row so the
			# admin can see which, rather than losing the rest to a dead job.
			frappe.log_error(
				title=f"TaxJar: could not set exemption on {name}",
				message=frappe.get_traceback(with_context=True),
			)
	frappe.publish_realtime(
		"taxjar_customer_sync_update", {"bulk_exemption_done": len(customers)}, user=frappe.session.user
	)


def _apply_exemption(customers, exemption_type, regions):
	if len(customers) <= _INLINE_EXEMPTION_LIMIT:
		for name in customers:
			_write_exemption(name, exemption_type, regions)
		return {"updated": len(customers), "queued": False}

	frappe.enqueue(
		"taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers.apply_exemption_in_background",
		customers=customers,
		exemption_type=exemption_type,
		regions=regions,
		queue="long",
		enqueue_after_commit=True,
		now=frappe.flags.in_test,
	)
	return {"updated": len(customers), "queued": True}


@frappe.whitelist(methods=["POST"])
def bulk_sync_to_taxjar(customers: list | str):
	"""Re-enqueue a customer sync without changing anything on the customer.

	Reached only by the page's "Retry {n} Failed" action. Ordinary edits do not
	need it - on_customer_update already enqueues a sync whenever a TaxJar
	field changes. It exists because a failure leaves nothing to re-save, and
	the 15-minute retry cron (retry_failed_taxjar_syncs) covers Sales Invoices
	only, never Customers.
	"""
	require_permission("Customer", "write")
	_ensure_taxjar_customer_fields()
	customers = parse_document_names(customers, label=frappe._("customers"))
	_check_each(customers)

	# Read once. frappe.get_single() rebuilds the settings document and its child
	# tables on every call, and this used to sit inside the loop - a hundred
	# selected customers meant a hundred rebuilds of a list that cannot change
	# during the request.
	companies = _customer_sync_companies()
	if not companies:
		# Nothing to queue for, so nothing may be marked Queued. Writing the
		# status anyway left every selected customer waiting on a job that was
		# never created, and still reported them as queued to the caller.
		frappe.throw(
			_("No company on this site is set up for TaxJar, so there is nothing to sync to."),
			title=_("TaxJar Not Configured"),
		)

	allowed = _allowed_companies_by_customer(customers)

	queued = 0
	for name in customers:
		# One row, one read: two get_value calls for two columns of the same row
		# is two round trips where one will do.
		fields = frappe.db.get_value(
			"Customer", name, ["taxjar_customer_id", "taxjar_exemption_type"], as_dict=True
		) or {}
		if not fields.get("taxjar_customer_id") and not fields.get("taxjar_exemption_type"):
			continue

		# A customer restricted to companies without TaxJar has nowhere to go,
		# so it must not be marked Queued either.
		customer_companies = _restrict_companies(companies, allowed[name])
		if not customer_companies:
			continue

		frappe.db.set_value(
			"Customer", name, _customer_sync_status_fields("Queued"), update_modified=False
		)
		_publish_customer_update(name, "Queued")
		for company in customer_companies:
			# No deduplicate here, for the reason spelled out in
			# _enqueue_customer_sync(): a dropped enqueue leaves the "Queued"
			# written just above with no job to clear it, and this button is
			# the very thing a stuck customer is supposed to be rescued by.
			_enqueue_customer_sync(name, company)
		queued += 1

	return {"queued": queued}
