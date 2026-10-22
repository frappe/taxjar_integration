# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""The Excel export the TaxJar list pages share.

Nothing here touches the database. The two things worth pinning are the ones a
reader would only notice in the file itself: that the sheet holds every batch
the filters match rather than the first one, and that a column says the same
word the table above it says.
"""

import frappe
from frappe.tests import UnitTestCase

from taxjar_integration.taxjar_integration.exporting import (
	BATCH_SIZE,
	_cell,
	_sheet_rows,
	check_export_limit,
	send_xlsx,
)
from taxjar_integration.taxjar_integration.pagination import EXPORT_ROW_LIMIT
from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import (
	_region_codes,
)
from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import (
	_sync_status_label as _customer_sync_status_label,
)
from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import (
	_exclusion_reason_label,
)
from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import (
	_sync_status_label as _invoice_sync_status_label,
)

COLUMNS = [
	{"label": "Name", "fieldname": "name"},
	{"label": "Shouted", "value": lambda row: (row.get("name") or "").upper()},
]


def _rows(count, start=0):
	return [{"name": f"row-{index}"} for index in range(start, start + count)]


class TestExportSheet(UnitTestCase):
	def test_header_row_comes_first(self):
		sheet = list(_sheet_rows(COLUMNS, lambda start, size: [], 0))

		self.assertEqual(sheet, [["Name", "Shouted"]])

	def test_every_batch_is_read(self):
		"""The export is the whole table, so it reads past the first batch.

		The bug this guards is the one the page itself has by design - a reader
		who exports 1,200 rows and gets 500 has no way to tell from the file.
		"""
		total = BATCH_SIZE * 2 + 3
		asked = []

		def fetch(start, size):
			asked.append(start)
			return _rows(min(size, total - start), start)

		sheet = list(_sheet_rows(COLUMNS, fetch, total))

		self.assertEqual(asked, [0, BATCH_SIZE, BATCH_SIZE * 2])
		self.assertEqual(len(sheet), total + 1)
		self.assertEqual(sheet[1], ["row-0", "ROW-0"])
		self.assertEqual(sheet[-1], [f"row-{total - 1}", f"ROW-{total - 1}"])

	def test_an_empty_batch_ends_the_sheet(self):
		"""Rows can go between the count and the read. Without this the loop
		would read the same empty window until it reached the counted total."""
		asked = []

		def fetch(start, size):
			asked.append(start)
			return _rows(size, start) if start == 0 else []

		sheet = list(_sheet_rows(COLUMNS, fetch, BATCH_SIZE * 10))

		self.assertEqual(asked, [0, BATCH_SIZE])
		self.assertEqual(len(sheet), BATCH_SIZE + 1)

	def test_a_missing_value_is_an_empty_cell(self):
		self.assertEqual(_cell({"label": "Name", "fieldname": "name"}, {}), "")


class TestExportLimit(UnitTestCase):
	def test_the_limit_itself_is_allowed(self):
		check_export_limit(EXPORT_ROW_LIMIT)

	def test_one_row_over_the_limit_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			check_export_limit(EXPORT_ROW_LIMIT + 1)

	def test_nothing_is_read_when_the_export_is_refused(self):
		"""The refusal comes before the first query, not after the last one."""

		def fetch(start, size):
			self.fail("the export read rows it was never going to send")

		with self.assertRaises(frappe.ValidationError):
			send_xlsx(
				doctype="Sales Invoice",
				filename="TaxJar Transactions",
				columns=COLUMNS,
				fetch_rows=fetch,
				total=EXPORT_ROW_LIMIT + 1,
			)


class TestTransactionColumns(UnitTestCase):
	"""The Sync Status and Exclusion Reason columns say what the page says.

	Their twins are render_sync_status_cell and exclusion_reason_text in the
	page's own scripts. Nothing but these tests holds the two together.
	"""

	def test_a_draft_is_told_to_submit(self):
		label = _invoice_sync_status_label({"docstatus": 0, "taxjar_sync_status": "Excluded"})

		self.assertEqual(label, "Submit to Sync")

	def test_a_failed_cancellation_says_so(self):
		label = _invoice_sync_status_label({"docstatus": 2, "taxjar_sync_status": "Failed"})

		self.assertEqual(label, "Failed to Cancel")

	def test_a_failed_submission_stays_failed(self):
		label = _invoice_sync_status_label({"docstatus": 1, "taxjar_sync_status": "Failed"})

		self.assertEqual(label, "Failed")

	def test_a_reason_read_from_today_is_marked_current(self):
		label = _exclusion_reason_label(
			{"taxjar_exclusion_reason": "TaxJar Disabled", "taxjar_exclusion_reason_is_current": 1}
		)

		self.assertEqual(label, "TaxJar Disabled (current setting)")

	def test_a_reason_the_document_carries_is_not(self):
		label = _exclusion_reason_label({"taxjar_exclusion_reason": "TaxJar Disabled"})

		self.assertEqual(label, "TaxJar Disabled")


class TestCustomerColumns(UnitTestCase):
	def test_regions_become_one_cell_of_codes(self):
		codes = _region_codes(
			{"exempt_regions": [{"country": "US", "state": "CA"}, {"country": "CA", "state": "ON"}]}
		)

		self.assertEqual(codes, "US-CA, CA-ON")

	def test_a_customer_with_no_sync_status_reads_na(self):
		self.assertEqual(_customer_sync_status_label({}), "NA")

	def test_a_synced_customer_reads_synced(self):
		self.assertEqual(
			_customer_sync_status_label({"taxjar_customer_sync_status": "Synced"}), "Synced"
		)
