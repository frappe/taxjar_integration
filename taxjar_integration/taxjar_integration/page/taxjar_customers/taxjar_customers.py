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
from taxjar_integration.taxjar_integration.taxjar_integration import _publish_customer_update

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
	frappe.has_permission("Customer", "read", throw=True)
	if not _taxjar_customer_fields_ready():
		return not_configured_response("customers")

	filters = parse_filters(filters)
	page = max(1, int(page))
	page_size = parse_page_size(page_size)

	conditions = _build_conditions(filters, scope)

	total = permitted_count("Customer", conditions)

	# get_list, not get_all - see the note in the Transaction Sync page.
	customers = frappe.get_list(
		"Customer",
		filters=conditions,
		fields=[
			"name", "customer_name", "customer_group",
			"taxjar_exemption_type", "taxjar_customer_id",
			"taxjar_customer_sync_status", "taxjar_customer_sync_error",
		],
		order_by="customer_name asc",
		start=(page - 1) * page_size,
		limit_page_length=page_size,
	)

	# Fetch all region counts in one grouped query instead of one count per row.
	# get_all rather than get_list here on purpose: get_list drops the `parent`
	# column from a child-table select, which is the one field this grouping
	# needs. It stays permission-correct because `names` came out of the
	# permission-aware Customer query above, so nothing outside the caller's
	# visibility can be counted.
	names = [c["name"] for c in customers]
	region_counts = {}
	if names:
		for row in frappe.get_all(
			"TaxJar Customer Exempt Region",
			filters={"parenttype": "Customer", "parent": ("in", names)},
			fields=["parent", {"COUNT": "*"}],
			group_by="parent",
		):
			region_counts[row.get("parent")] = next(
				(v for k, v in row.items() if k != "parent"), 0
			)

	for c in customers:
		c["exempt_region_count"] = region_counts.get(c["name"], 0)

	return paginated_response("customers", customers, total, page, page_size)


@frappe.whitelist()
def get_summary(filters: dict | str | None = None):
	"""Counts for the summary strip. Scoped by the same filters as the table so
	the strip always describes what is on screen.
	"""
	frappe.has_permission("Customer", "read", throw=True)
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
	frappe.has_permission("Customer", "read", doc=customer, throw=True)

	# get_all on a child table, gated by the doc-level Customer check above -
	# get_list would need a parent_doctype and still resolve to the same rows.
	regions = frappe.get_all(
		"TaxJar Customer Exempt Region",
		filters={"parent": customer, "parenttype": "Customer"},
		fields=["country", "state"],
	)
	return regions


def _check_each(customers):
	"""Assert write permission on every named customer before touching any.

	The blanket has_permission() at the top of each bulk endpoint only proves
	the caller may write *some* Customer; the names come from the client. This
	checks up front rather than inside the mutation loop so a caller who is
	only allowed half the list gets a clean refusal instead of a half-applied
	bulk edit.
	"""
	for name in customers:
		frappe.has_permission("Customer", "write", doc=name, throw=True)


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
	frappe.has_permission("Customer", "write", throw=True)
	_ensure_taxjar_customer_fields()

	customers = frappe.parse_json(customers) if isinstance(customers, str) else customers
	regions = frappe.parse_json(regions) if isinstance(regions, str) else (regions or [])
	_check_each(customers)

	# No exemption type means no exemption, and an exemption region without one
	# is meaningless - drop them rather than orphan them.
	if not exemption_type:
		regions = []

	for name in customers:
		doc = frappe.get_doc("Customer", name)
		doc.taxjar_exemption_type = exemption_type or ""
		doc.set("taxjar_exempt_regions", [])
		for r in regions:
			doc.append("taxjar_exempt_regions", {"country": r["country"], "state": r["state"]})
		doc.save()

	return {"updated": len(customers)}


@frappe.whitelist(methods=["POST"])
def bulk_clear_exemption(customers: list | str):
	frappe.has_permission("Customer", "write", throw=True)
	_ensure_taxjar_customer_fields()
	customers = frappe.parse_json(customers) if isinstance(customers, str) else customers
	_check_each(customers)

	for name in customers:
		doc = frappe.get_doc("Customer", name)
		doc.taxjar_exemption_type = ""
		doc.set("taxjar_exempt_regions", [])
		doc.save()

	return {"updated": len(customers)}


@frappe.whitelist(methods=["POST"])
def bulk_sync_to_taxjar(customers: list | str):
	"""Re-enqueue a customer sync without changing anything on the customer.

	Reached only by the page's "Retry {n} Failed" action. Ordinary edits do not
	need it - on_customer_update already enqueues a sync whenever a TaxJar
	field changes. It exists because a failure leaves nothing to re-save, and
	the 15-minute retry cron (retry_failed_taxjar_syncs) covers Sales Invoices
	only, never Customers.
	"""
	frappe.has_permission("Customer", "write", throw=True)
	_ensure_taxjar_customer_fields()
	customers = frappe.parse_json(customers) if isinstance(customers, str) else customers
	_check_each(customers)

	queued = 0
	for name in customers:
		customer_id = frappe.db.get_value("Customer", name, "taxjar_customer_id")
		exemption_type = frappe.db.get_value("Customer", name, "taxjar_exemption_type")
		if not customer_id and not exemption_type:
			continue

		frappe.db.set_value("Customer", name, "taxjar_customer_sync_status", "Queued", update_modified=False)
		_publish_customer_update(name, "Queued")
		taxjar_settings = frappe.get_single("TaxJar Settings")
		for config in taxjar_settings.company_config or []:
			frappe.enqueue(
				"taxjar_integration.taxjar_integration.taxjar_integration.sync_customer_to_taxjar",
				customer_name=name,
				company=config.company,
				queue="short",
				deduplicate=True,
				job_id=f"sync_customer_taxjar_{name}_{config.company}",
			)
		queued += 1

	return {"queued": queued}
