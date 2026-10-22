"""The Excel export the TaxJar list pages share.

Each page holds a filtered, tabbed, paginated table, and the reader who wants
that table in a spreadsheet wants all of it - not the twenty rows on screen. So
an export answers the same question the table answers, under the same filters
and the same tab, with the page boundary taken off.

The response is a file, not JSON: build_xlsx_response fills frappe.response with
the workbook bytes, so the client submits a form to the endpoint rather than
calling it through frappe.xcall.
"""

import json

import frappe
from frappe import _
from frappe.core.doctype.access_log.access_log import make_access_log
from frappe.utils.xlsxutils import build_xlsx_response

from taxjar_integration.taxjar_integration.pagination import EXPORT_ROW_LIMIT

# Rows per read. The reader gets one unbroken sheet, but the server still reads
# it a batch at a time: one get_list for ten thousand invoices holds every row
# in memory at once, and the writer below only ever needs the next row.
BATCH_SIZE = 500


def check_export_limit(total):
	"""Refuse an export that is larger than one request can carry.

	The client knows this limit too - it reads EXPORT_ROW_LIMIT out of the page
	envelope and disables the button above it - so a reader meets this message
	only through a crafted request.
	"""
	if total > EXPORT_ROW_LIMIT:
		frappe.throw(
			_("This export holds {0} records. Narrow the filters to {1} records or fewer.").format(
				total, EXPORT_ROW_LIMIT
			),
			title=_("Export Too Large"),
		)


def send_xlsx(doctype, filename, columns, fetch_rows, total, filters=None):
	"""Answer the current request with an xlsx of every matching row.

	``columns`` is the sheet's shape: one dict per column, each with a ``label``
	and either a ``fieldname`` to read or a ``value`` function to compute.
	``fetch_rows(start, page_size)`` returns one batch of rows, already carrying
	whatever the page's own table adds to them.
	"""
	check_export_limit(total)

	# The same record frappe writes for a list view or a report export. A data
	# export is a copy of the table leaving the site, so who exported what, under
	# which filters, is worth the one row it costs.
	make_access_log(
		doctype=doctype,
		file_type="XLSX",
		page=filename,
		filters=filters,
		columns=json.dumps([column["label"] for column in columns]),
	)

	build_xlsx_response(_sheet_rows(columns, fetch_rows, total), filename)


def _sheet_rows(columns, fetch_rows, total):
	"""The header row, then every matching row, one batch at a time.

	A generator, because make_xlsx writes the workbook in row order and holds
	only the row it is writing - so the sheet is built without the whole result
	set ever being in memory.
	"""
	yield [column["label"] for column in columns]

	start = 0
	while start < total:
		rows = fetch_rows(start, BATCH_SIZE)
		# The table can change between the count and the read. An empty batch
		# means there is nothing left, and looping to the counted total anyway
		# would read the same empty window until it reached it.
		if not rows:
			return

		for row in rows:
			yield [_cell(column, row) for column in columns]

		start += BATCH_SIZE


def _cell(column, row):
	"""One cell: a column either names a field or works out its own value.

	None becomes an empty string. xlsxwriter would write a blank cell for it
	either way, and an explicit empty string keeps every cell in the sheet one
	of the types the writer formats.
	"""
	value = column["value"](row) if column.get("value") else row.get(column["fieldname"])
	return "" if value is None else value
