import frappe

# The tables render at their natural height with no inner scrollbar, so the
# default is a page that stays roughly a screenful.
PAGE_SIZE = 20
PAGE_SIZES = (20, 50, 100)


def parse_filters(filters):
	"""Normalise the filters argument from a whitelisted page method."""
	return frappe.parse_json(filters) if filters else {}


def parse_page_size(page_size):
	"""Clamp a caller-supplied page size to the sizes the UI offers.

	These are whitelisted endpoints, so the value is attacker-controlled -
	without the clamp a crafted request could ask for every row in the table.
	"""
	try:
		page_size = int(page_size)
	except (TypeError, ValueError):
		return PAGE_SIZE

	return page_size if page_size in PAGE_SIZES else PAGE_SIZE


def permitted_count(doctype, filters):
	"""Row count for ``filters`` that respects the caller's permissions.

	frappe.db.count goes straight to the database: it applies no permission
	query conditions and no User Permissions, so a user restricted to one
	company would get a total covering every company - a number the table
	beneath it can never match. get_list runs the same aggregate through the
	permission-aware query builder.

	The dict form is required: this frappe rejects SQL function strings in
	SELECT ("count(name) as total") and asks for {"COUNT": "*"} instead, which
	comes back keyed "COUNT(*)".
	"""
	rows = frappe.get_list(doctype, filters=filters, fields=[{"COUNT": "*"}])
	return next(iter(rows[0].values()), 0) if rows else 0


def paginated_response(items_key, items, total, page, page_size=PAGE_SIZE):
	"""Build the standard page envelope shared by the TaxJar list pages."""
	return {
		items_key: items,
		"total": total,
		"page": page,
		"page_size": page_size,
		"total_pages": max(1, -(-total // page_size)),
	}


def not_configured_response(items_key=None):
	"""Envelope returned by page read methods when the TaxJar custom fields do not
	exist yet (features were never enabled and the columns were never created).

	Querying those columns would raise MySQLdb (1054) Unknown column, so the page
	methods detect the missing schema up front and return this instead. The page JS
	renders a "TaxJar not set up" panel when it sees ``not_configured``.
	"""
	response = {"not_configured": True}
	if items_key:
		response.update(paginated_response(items_key, [], 0, 1))
	return response
