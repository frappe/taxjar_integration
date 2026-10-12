import frappe

# The tables render at their natural height with no inner scrollbar, so the
# default is a page that stays roughly a screenful.
PAGE_SIZE = 20
PAGE_SIZES = (20, 50, 100)

# The most rows one export may carry. An export is not paginated - that is the
# point of it - so this is what stops a whitelisted endpoint being asked for the
# whole table: every row is read, formatted and written inside one request, and
# a request has to answer. The page envelope below carries the number to the
# client, so the button can say why it is out of reach rather than letting the
# reader press it and meet an error page.
EXPORT_ROW_LIMIT = 10000

# The most documents one bulk action may name. The pages themselves can send no
# more than one page of checked rows, so this is the ceiling for a request that
# did not come from them - every name costs a permission check and a read.
MAX_BULK_DOCUMENTS = 500


def parse_filters(filters):
	"""Normalise the filters argument from a whitelisted page method."""
	return frappe.parse_json(filters) if filters else {}


def parse_document_names(names, label="documents"):
	"""Normalise and type-check the list of document names a bulk endpoint acts on.

	In frappe a dict where a docname is expected is not a type error, it is a
	filter: frappe.get_doc("Customer", {"customer_group": "X"}) looks up the
	first match rather than refusing. The per-document permission loops that
	follow stop that becoming a bypass - has_permission() only wraps str and int
	in a document, so a dict falls through and raises - but it surfaces as an
	unattributable 500 rather than a refusal that says what was wrong.

	A bare string is also rejected rather than iterated: "SINV-001" is a
	sequence, so a caller who forgets the list gets 8 single-character lookups
	and a confusing silence instead of an error.
	"""
	names = frappe.parse_json(names) if isinstance(names, str) else names

	if not isinstance(names, list | tuple):
		frappe.throw(
			frappe._("Expected a list of {0}.").format(label),
			title=frappe._("Invalid Request"),
		)

	if len(names) > MAX_BULK_DOCUMENTS:
		frappe.throw(
			frappe._("A bulk action takes at most {0} {1} at a time. This one named {2}.").format(
				MAX_BULK_DOCUMENTS, label, len(names)
			),
			title=frappe._("Too Many Records"),
		)

	bad = [n for n in names if not isinstance(n, str) or not n.strip()]
	if bad:
		frappe.throw(
			frappe._("Expected {0} to be names. Got {1}.").format(label, frappe.bold(str(bad[0])[:80])),
			title=frappe._("Invalid Request"),
		)

	return list(names)


def parse_page(page):
	"""Clamp a caller-supplied page number to one the table can hold.

	The same treatment parse_page_size() gives its own argument, and for the
	same reason: these are whitelisted endpoints, so the value is
	attacker-controlled. int("abc") raised, and the caller met a 500 with a
	traceback rather than a page of rows.
	"""
	try:
		page = int(page)
	except (TypeError, ValueError):
		return 1

	return max(1, page)


def clamp_page(page, total, page_size):
	"""Turn a page past the end into the last page.

	A bulk action on the last page can move every row on it off the tab, and
	the reload asks for the same page again. That page no longer exists, so the
	table came back empty under "Page 3 of 2". The reply carries the page it
	used, and the paginator renders from the reply.
	"""
	return min(page, max(1, -(-total // page_size)))


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


def permitted_count(doctype, filters, or_filters=None):
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
	rows = frappe.get_list(doctype, filters=filters, or_filters=or_filters, fields=[{"COUNT": "*"}])
	return next(iter(rows[0].values()), 0) if rows else 0


def paginated_response(items_key, items, total, page, page_size=PAGE_SIZE):
	"""Build the standard page envelope shared by the TaxJar list pages."""
	return {
		items_key: items,
		"total": total,
		"page": page,
		"page_size": page_size,
		"total_pages": max(1, -(-total // page_size)),
		"export_limit": EXPORT_ROW_LIMIT,
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
