# Copyright (c) 2026,  Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from unittest.mock import patch

import taxjar
from frappe.model.document import Document
from frappe.tests import IntegrationTestCase
from taxjar.data.tax import TaxJarTax

from taxjar_integration.taxjar_integration.taxjar_integration import (
	_taxjar_response_payload,
	_write_taxjar_ui_log,
)

# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
# The company field links to Company, whose ERPNext test records these tests
# do not need.
IGNORE_TEST_RECORD_DEPENDENCIES = ["Company"]


class IntegrationTestTaxJarAPILog(IntegrationTestCase):
	def test_error_row_defers_its_insert(self):
		"""An error row must outlive the raise that follows it.

		Every caller that logs an error raises straight afterwards, and the
		raise rolls the request back. A plain insert() went back with it, so
		the log kept every row except the ones a reader opens it for.
		"""
		with patch.object(Document, "deferred_insert") as deferred:
			with patch.object(Document, "insert") as insert:
				_write_taxjar_ui_log({"action": "tax_for_order", "status": "error", "error": "boom"})

		deferred.assert_called_once()
		insert.assert_not_called()

	def test_other_rows_insert_in_the_caller_transaction(self):
		"""Only errors defer. A success commits with the document, and appears at once."""
		with patch.object(Document, "deferred_insert") as deferred:
			with patch.object(Document, "insert") as insert:
				_write_taxjar_ui_log({"action": "tax_for_order", "status": "success"})

		insert.assert_called_once()
		deferred.assert_not_called()

	def test_success_response_logs_its_own_fields(self):
		"""to_json(), not __dict__.

		__dict__ is jsonobject's instance dict: it buried the response one
		level down under "_obj" and sat it beside a repr of a private object
		at a memory address.
		"""
		payload = _taxjar_response_payload(TaxJarTax({"amount_to_collect": 7.25, "has_nexus": True}))

		self.assertEqual(payload["amount_to_collect"], 7.25)
		self.assertTrue(payload["has_nexus"])
		self.assertNotIn("_obj", payload)
		self.assertNotIn("_$", payload)

	def test_error_response_keeps_full_response(self):
		"""full_response wins over to_json(), because the client puts the detail there."""
		err = taxjar.exceptions.TaxJarResponseError("400 Bad Request")
		err.full_response = {"status_code": 400, "detail": "no nexus"}

		self.assertEqual(_taxjar_response_payload(err)["status_code"], 400)

	def test_no_response_logs_nothing(self):
		self.assertIsNone(_taxjar_response_payload(None))

	def test_accounts_manager_reads_the_log_but_cannot_change_it(self):
		"""The guided setup and the sync pages are open to Accounts Manager, and
		their errors send the reader to this log. Reading it is enough - the rows
		are a record of what TaxJar said, not something to edit or hand out."""
		import frappe

		perms = [
			p for p in frappe.get_meta("TaxJar API Log").permissions
			if p.role == "Accounts Manager" and p.permlevel == 0
		]
		self.assertEqual(len(perms), 1)
		self.assertTrue(perms[0].read)
		for ptype in ("write", "create", "delete", "export", "share"):
			self.assertFalse(perms[0].get(ptype), ptype)

	def test_a_row_records_the_company_of_its_context(self):
		"""User Permissions on Company filter the log through this field."""
		with patch.object(Document, "insert", autospec=True) as insert:
			_write_taxjar_ui_log(
				{
					"action": "create_order",
					"status": "success",
					"context": {"doctype": "Sales Invoice", "name": "SINV-1", "company": "ACME"},
				}
			)

		self.assertEqual(insert.call_args.args[0].company, "ACME")

	def test_the_company_is_a_link_to_company(self):
		import frappe

		field = frappe.get_meta("TaxJar API Log").get_field("company")
		self.assertEqual((field.fieldtype, field.options), ("Link", "Company"))
