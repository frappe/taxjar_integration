# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""The check of invoices submitted under TaxJar version 15.

Nothing here calls TaxJar, and the job's database writes are replaced with
recorders. The things worth pinning are the ones that would go wrong quietly:
the months the check asks about, the provider it asks under, which outcome an
invoice gets, and that a failure for one company leaves its invoices alone.
"""

import json
from datetime import date, datetime
from unittest.mock import MagicMock, call, patch

import frappe
from frappe.tests import UnitTestCase

from taxjar_integration.taxjar_integration import legacy_check
from taxjar_integration.taxjar_integration.legacy_check import (
	RESULT_DONE,
	RESULT_FAILED,
	RESULT_NO_CREDENTIAL,
	STATUS_DONE,
	STATUS_FAILED,
	STATUS_RUNNING,
	apply_outcomes,
	month_windows,
)
from taxjar_integration.taxjar_integration.taxjar_integration import (
	EXCLUSION_LEGACY_NOT_FOUND,
	EXCLUSION_LEGACY_UNCHECKED,
	LEGACY_PROVIDER,
	TAXJAR_PROVIDER,
	provider_params,
)

_LC = "taxjar_integration.taxjar_integration.legacy_check"


def _client(api_key="token-a", orders=(), refunds=()):
	"""A client that answers like the SDK: a new TaxJarOrders on every call,
	for refunds too. TaxJarOrders has no len() and reads only once."""
	from taxjar.data.order import TaxJarOrders

	client = MagicMock()
	client.api_key = api_key
	client.list_orders.side_effect = lambda params: TaxJarOrders(list(orders))
	client.list_refunds.side_effect = lambda params: TaxJarOrders(list(refunds))
	return client


def _pending(company, invoices=10, first_created=datetime(2026, 8, 14, 9, 30)):
	return frappe._dict(company=company, invoices=invoices, first_created=first_created)


class TestMonthWindows(UnitTestCase):
	def test_one_window_for_each_calendar_month(self):
		windows = month_windows(date(2026, 7, 20), date(2026, 10, 1))

		self.assertEqual(windows, [
			(date(2026, 7, 1), date(2026, 7, 31)),
			(date(2026, 8, 1), date(2026, 8, 31)),
			(date(2026, 9, 1), date(2026, 9, 30)),
			(date(2026, 10, 1), date(2026, 10, 1)),
		])

	def test_the_first_window_starts_on_the_first_of_the_month(self):
		"""Each window is a whole calendar month, so the months line up for two
		companies that share one TaxJar account and the cache can serve both."""
		self.assertEqual(month_windows(date(2026, 9, 17), date(2026, 9, 30)), [
			(date(2026, 9, 1), date(2026, 9, 30)),
		])

	def test_a_year_boundary(self):
		windows = month_windows(date(2025, 12, 5), date(2026, 1, 9))

		self.assertEqual(windows, [
			(date(2025, 12, 1), date(2025, 12, 31)),
			(date(2026, 1, 1), date(2026, 1, 9)),
		])

	def test_no_window_when_the_range_is_empty(self):
		self.assertEqual(month_windows(date(2026, 10, 2), date(2026, 10, 1)), [])
		self.assertEqual(month_windows(None, date(2026, 10, 1)), [])


class TestReadingTransactionIds(UnitTestCase):
	def _read(self, client, windows, cache=None):
		with patch(f"{_LC}.log_taxjar_call"), patch(f"{_LC}._publish"):
			return legacy_check._read_transaction_ids(client, "ACME", windows, {} if cache is None else cache)

	def test_asks_under_the_provider_version_15_used(self):
		"""Version 15 named no provider, so TaxJar filed its orders under the
		default one. Asked under ours, the list would come back empty and every
		invoice would read "not found"."""
		client = _client()

		self._read(client, [(date(2026, 9, 1), date(2026, 9, 30))])

		params = client.list_orders.call_args.args[0]
		self.assertEqual(params["provider"], LEGACY_PROVIDER)
		self.assertNotEqual(LEGACY_PROVIDER, TAXJAR_PROVIDER)
		self.assertEqual(params["from_transaction_date"], "2026/09/01")
		self.assertEqual(params["to_transaction_date"], "2026/09/30")
		self.assertEqual(client.list_refunds.call_args.args[0], params)

	def test_two_calls_for_each_month(self):
		client = _client(orders=["SINV-1"], refunds=["SINV-RET-1"])
		windows = month_windows(date(2026, 7, 1), date(2026, 9, 30))

		orders, refunds, calls = self._read(client, windows)

		self.assertEqual(calls, 6)
		self.assertEqual(client.list_orders.call_count, 3)
		self.assertEqual(orders, {"SINV-1"})
		self.assertEqual(refunds, {"SINV-RET-1"})

	def test_one_account_is_read_once_for_two_companies(self):
		"""Two companies on one TaxJar token share one set of months."""
		cache = {}
		windows = [(date(2026, 9, 1), date(2026, 9, 30))]
		first = _client(api_key="shared", orders=["SINV-1"])
		second = _client(api_key="shared")

		self._read(first, windows, cache)
		orders, _refunds, calls = self._read(second, windows, cache)

		second.list_orders.assert_not_called()
		self.assertEqual(calls, 0)
		self.assertEqual(orders, {"SINV-1"})

	def test_a_different_token_is_read_again(self):
		cache = {}
		windows = [(date(2026, 9, 1), date(2026, 9, 30))]

		self._read(_client(api_key="a"), windows, cache)
		other = _client(api_key="b")
		self._read(other, windows, cache)

		other.list_orders.assert_called_once()

	def test_a_failed_call_raises(self):
		"""The caller writes nothing for a company whose read failed."""
		client = _client()
		client.list_orders.side_effect = RuntimeError("boom")

		with self.assertRaises(RuntimeError):
			self._read(client, [(date(2026, 9, 1), date(2026, 9, 30))])


class TestTheSdkAnswer(UnitTestCase):
	def test_the_ids_come_from_the_sdk_object(self):
		"""The SDK's TaxJarOrders has no len(). Counting it for the log raised
		TypeError, and the check failed for every company."""
		from taxjar.data.order import TaxJarOrders

		from taxjar_integration.taxjar_integration.legacy_check import _list_ids

		answer = TaxJarOrders(["SINV-1", "SINV-2"])
		with self.assertRaises(TypeError):
			len(answer)

		with patch(f"{_LC}.log_taxjar_call") as log:
			ids = _list_ids(lambda params: answer, "list_orders", {}, "ACME")

		self.assertEqual(ids, {"SINV-1", "SINV-2"})
		self.assertEqual(log.call_args.kwargs["response"], {"count": 2})


class TestOutcomes(UnitTestCase):
	def _apply(self, invoices, orders=(), refunds=()):
		writes = {}

		def record(names, fields):
			for name in names:
				writes[name] = fields

		rows = [frappe._dict(row) for row in invoices]
		real_get_all = frappe.get_all

		def get_all(doctype, *args, **kwargs):
			return rows if doctype == "Sales Invoice" else real_get_all(doctype, *args, **kwargs)

		with patch(f"{_LC}.frappe.get_all", side_effect=get_all), patch(f"{_LC}._write", side_effect=record):
			counts = apply_outcomes("ACME", set(orders), set(refunds))
		return counts, writes

	def test_a_submitted_invoice_that_taxjar_holds_is_synced(self):
		counts, writes = self._apply([{"name": "SINV-1", "docstatus": 1, "is_return": 0}], orders=["SINV-1"])

		fields = writes["SINV-1"]
		self.assertEqual(fields["taxjar_sync_status"], "Synced")
		self.assertEqual(fields["taxjar_exclusion_reason"], "")
		self.assertEqual(fields["taxjar_provider"], LEGACY_PROVIDER)
		self.assertEqual(counts["found"], 1)

	def test_synced_carries_no_last_synced_time(self):
		"""The list says that TaxJar holds the order, not when it arrived."""
		_counts, writes = self._apply([{"name": "SINV-1", "docstatus": 1, "is_return": 0}], orders=["SINV-1"])

		self.assertNotIn("taxjar_last_synced", writes["SINV-1"])

	def test_a_cancelled_invoice_that_taxjar_still_holds_fails(self):
		"""Failed, not retryable: the cron must not delete it on its own, and
		the Retry button deletes it under the provider recorded here."""
		counts, writes = self._apply([{"name": "SINV-2", "docstatus": 2, "is_return": 0}], orders=["SINV-2"])

		fields = writes["SINV-2"]
		self.assertEqual(fields["taxjar_sync_status"], "Failed")
		self.assertEqual(fields["taxjar_sync_retryable"], 0)
		self.assertEqual(fields["taxjar_provider"], LEGACY_PROVIDER)
		self.assertIn("still holds", fields["taxjar_sync_error"])
		self.assertEqual(counts["cancelled_in_taxjar"], 1)

	def test_an_invoice_taxjar_does_not_hold_keeps_excluded(self):
		counts, writes = self._apply([
			{"name": "SINV-3", "docstatus": 1, "is_return": 0},
			{"name": "SINV-4", "docstatus": 2, "is_return": 0},
		])

		self.assertEqual(writes["SINV-3"], {"taxjar_exclusion_reason": EXCLUSION_LEGACY_NOT_FOUND})
		self.assertEqual(writes["SINV-4"], {"taxjar_exclusion_reason": EXCLUSION_LEGACY_NOT_FOUND})
		self.assertEqual(counts["not_found"], 2)

	def test_a_return_is_matched_to_the_refunds(self):
		"""Version 15 sent a return as a refund under the same name. An order
		with that name means something else."""
		_counts, writes = self._apply(
			[
				{"name": "SINV-RET-1", "docstatus": 1, "is_return": 1},
				{"name": "SINV-RET-2", "docstatus": 1, "is_return": 1},
			],
			orders=["SINV-RET-2"],
			refunds=["SINV-RET-1"],
		)

		self.assertEqual(writes["SINV-RET-1"]["taxjar_sync_status"], "Synced")
		self.assertEqual(writes["SINV-RET-2"], {"taxjar_exclusion_reason": EXCLUSION_LEGACY_NOT_FOUND})

	def test_only_unchecked_invoices_are_read(self):
		real_get_all = frappe.get_all

		def fake(doctype, *args, **kwargs):
			return [] if doctype == "Sales Invoice" else real_get_all(doctype, *args, **kwargs)

		with patch(f"{_LC}.frappe.get_all", side_effect=fake) as get_all, patch(f"{_LC}._write"):
			apply_outcomes("ACME", set(), set())

		# Other code reads through frappe.get_all too, System Settings among it.
		invoice_call = next(c for c in get_all.call_args_list if c.args[0] == "Sales Invoice")
		filters = invoice_call.kwargs["filters"]
		self.assertEqual(filters["taxjar_exclusion_reason"], EXCLUSION_LEGACY_UNCHECKED)
		self.assertEqual(filters["company"], "ACME")

	def test_the_write_only_touches_rows_still_waiting(self):
		"""A row someone retried or synced meanwhile keeps that change."""
		invoice = frappe.qb.DocType("Sales Invoice")
		sql = str(frappe.qb.from_(invoice).select("*").where(legacy_check._is_unchecked(invoice)))

		self.assertIn(f"`taxjar_exclusion_reason`='{EXCLUSION_LEGACY_UNCHECKED}'", sql)
		self.assertIn("`docstatus` IN (1,2)", sql)


class TestTheJob(UnitTestCase):
	def _run(self, pending, clients, read=None, summary=None):
		"""Run _check_all_companies with every outside call replaced.

		Returns the state writes, in order."""
		states = []

		def single_value(_doctype, field):
			return {
				"legacy_cutoff_date": "2026-10-01",
				"legacy_check_summary": json.dumps(summary or {}),
			}[field]

		read = read or (lambda client, company, windows, cache: ({"SINV-1"}, set(), 2 * len(windows)))
		with patch(f"{_LC}.pending_by_company", return_value=pending), \
		     patch(f"{_LC}.get_client", side_effect=lambda company: clients.get(company)), \
		     patch(f"{_LC}._read_transaction_ids", side_effect=read), \
		     patch(f"{_LC}.apply_outcomes", return_value={"checked": 10, "found": 9, "not_found": 1, "cancelled_in_taxjar": 0}) as apply, \
		     patch(f"{_LC}._write_state", side_effect=lambda **values: states.append(values)), \
		     patch(f"{_LC}.frappe.db.get_single_value", side_effect=single_value), \
		     patch(f"{_LC}.frappe.db.commit"), \
		     patch(f"{_LC}.frappe.publish_realtime"), \
		     patch(f"{_LC}._publish"):
			legacy_check._check_all_companies()
		return states, apply

	def test_marks_running_then_done(self):
		states, _apply = self._run([_pending("ACME")], {"ACME": _client()})

		self.assertEqual(states[0]["legacy_check_status"], STATUS_RUNNING)
		self.assertEqual(states[-1]["legacy_check_status"], STATUS_DONE)
		summary = json.loads(states[-1]["legacy_check_summary"])
		self.assertEqual(summary["ACME"]["result"], RESULT_DONE)
		self.assertEqual(summary["ACME"]["found"], 9)
		self.assertEqual(summary["ACME"]["first_month"], "2026-08")
		self.assertEqual(summary["ACME"]["calls"], 6)

	def test_a_company_with_no_token_is_skipped(self):
		states, apply = self._run([_pending("ACME", invoices=120)], {})

		summary = json.loads(states[-1]["legacy_check_summary"])
		self.assertEqual(summary["ACME"], {"result": RESULT_NO_CREDENTIAL, "invoices": 120})
		apply.assert_not_called()
		self.assertEqual(states[-1]["legacy_check_status"], STATUS_DONE)

	def test_a_failed_company_changes_no_invoice_and_the_rest_go_on(self):
		def read(client, company, windows, cache):
			if company == "Broken":
				raise RuntimeError("TaxJar said no")
			return {"SINV-1"}, set(), 2

		states, apply = self._run(
			[_pending("Broken"), _pending("ACME")],
			{"Broken": _client("x"), "ACME": _client("y")},
			read=read,
		)

		self.assertEqual(apply.call_args_list, [call("ACME", {"SINV-1"}, set())])
		summary = json.loads(states[-1]["legacy_check_summary"])
		self.assertEqual(summary["Broken"]["result"], RESULT_FAILED)
		self.assertTrue(summary["Broken"]["error"])
		self.assertEqual(states[-1]["legacy_check_status"], STATUS_FAILED)

	def test_a_second_run_keeps_the_first_runs_results(self):
		"""Check Again only reads the companies that still wait. The ones done
		before keep their counts on the tab."""
		earlier = {"Done Co": {"result": RESULT_DONE, "found": 40}}

		states, _apply = self._run([_pending("ACME")], {"ACME": _client()}, summary=earlier)

		summary = json.loads(states[-1]["legacy_check_summary"])
		self.assertEqual(summary["Done Co"], earlier["Done Co"])
		self.assertIn("ACME", summary)


class TestStartingTheJob(UnitTestCase):
	def test_runs_in_live_mode_only(self):
		with patch(f"{_LC}.frappe.has_permission"), \
		     patch(f"{_LC}.frappe.db.get_single_value", return_value="Sandbox"), \
		     patch(f"{_LC}.enqueue_legacy_check") as enqueue:
			self.assertRaises(frappe.ValidationError, legacy_check.run_legacy_check)
		enqueue.assert_not_called()

	def test_needs_write_permission(self):
		with patch(f"{_LC}.frappe.has_permission", side_effect=frappe.PermissionError):
			self.assertRaises(frappe.PermissionError, legacy_check.run_legacy_check)

	def test_refuses_when_nothing_waits(self):
		with patch(f"{_LC}.frappe.has_permission"), \
		     patch(f"{_LC}.frappe.db.get_single_value", return_value="Live"), \
		     patch(f"{_LC}.pending_by_company", return_value=[]), \
		     patch(f"{_LC}.enqueue_legacy_check") as enqueue:
			self.assertRaises(frappe.ValidationError, legacy_check.run_legacy_check)
		enqueue.assert_not_called()

	def test_queues_once(self):
		with patch(f"{_LC}.is_job_enqueued", return_value=True), \
		     patch(f"{_LC}.frappe.enqueue") as enqueue, \
		     patch(f"{_LC}._write_state") as write_state:
			legacy_check.enqueue_legacy_check()
		enqueue.assert_not_called()
		write_state.assert_not_called()

	def test_queues_on_the_long_queue_with_a_fixed_id(self):
		with patch(f"{_LC}.is_job_enqueued", return_value=False), \
		     patch(f"{_LC}.frappe.enqueue") as enqueue, \
		     patch(f"{_LC}._write_state") as write_state:
			legacy_check.enqueue_legacy_check()
		self.assertEqual(enqueue.call_args.kwargs["job_id"], legacy_check.JOB_ID)
		self.assertEqual(enqueue.call_args.kwargs["queue"], "long")
		write_state.assert_called_once_with(legacy_check_status=STATUS_RUNNING)

	def test_the_job_starts_the_check_only_when_it_has_work(self):
		cases = (("Sandbox", [_pending("ACME")], False), ("Live", [], False), ("Live", [_pending("ACME")], True))
		for mode, pending, expected in cases:
			with self.subTest(mode=mode, pending=bool(pending)):
				with patch(f"{_LC}.frappe.db.get_single_value", return_value=mode), \
				     patch(f"{_LC}.pending_by_company", return_value=pending), \
				     patch(f"{_LC}.enqueue_unsent_exempt_customers"), \
				     patch(f"{_LC}.enqueue_legacy_check") as enqueue:
					legacy_check.start_live_work()
				self.assertEqual(enqueue.called, expected)

	def test_live_also_sends_the_unsent_customers(self):
		for mode, expected in (("Sandbox", False), ("Live", True)):
			with self.subTest(mode=mode):
				with patch(f"{_LC}.frappe.db.get_single_value", return_value=mode), \
				     patch(f"{_LC}.pending_by_company", return_value=[]), \
				     patch(f"{_LC}.enqueue_unsent_exempt_customers") as customers, \
				     patch(f"{_LC}.enqueue_legacy_check"):
					legacy_check.start_live_work()
				self.assertEqual(customers.called, expected)

	def test_the_work_runs_in_a_job_after_commit(self):
		"""Never inside the caller's request: it may hold settings_write_lock."""
		with patch(f"{_LC}.frappe.enqueue") as enqueue:
			legacy_check.enqueue_live_work()
		self.assertEqual(enqueue.call_args.args[0], "taxjar_integration.taxjar_integration.legacy_check.start_live_work")
		self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])

	def test_finish_setup_starts_the_check(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup import taxjar_setup

		with patch.object(taxjar_setup.frappe, "has_permission"), \
		     patch.object(taxjar_setup.frappe, "get_single", return_value=MagicMock()), \
		     patch.object(taxjar_setup, "enqueue_live_work") as start:
			taxjar_setup.finish_setup()
		start.assert_called_once_with()


class TestUnsentExemptCustomers(UnitTestCase):
	"""The upgrade copies a customer's exemption with no token on the site, so
	no save hook sent it to TaxJar. Going live sends it."""

	def _run(self, names, companies=("ACME",), allowed=None):
		query = MagicMock()
		query.run.return_value = list(names)
		with patch(f"{_LC}.frappe.db.has_column", return_value=True), \
		     patch(f"{_LC}._customer_sync_companies", return_value=list(companies)), \
		     patch(f"{_LC}._unsent_exempt_customers_query", return_value=query), \
		     patch(f"{_LC}._allowed_companies_by_customer", return_value=allowed or dict.fromkeys(names)), \
		     patch(f"{_LC}.frappe.db.set_value") as set_value, \
		     patch(f"{_LC}._enqueue_customer_sync") as enqueue:
			queued = legacy_check.enqueue_unsent_exempt_customers()
		return queued, set_value, enqueue

	def test_picks_customers_with_an_exemption_never_sent(self):
		sql = " ".join(str(legacy_check._unsent_exempt_customers_query()).split())

		self.assertIn("COALESCE(`taxjar_exemption_type`,'')<>''", sql)
		self.assertIn("COALESCE(`taxjar_customer_id`,'')=''", sql)
		self.assertIn("COALESCE(`taxjar_customer_sync_status`,'')=''", sql)

	def test_queues_one_job_for_each_company_and_marks_queued(self):
		queued, set_value, enqueue = self._run(["C-1", "C-2"], companies=("ACME", "Old Co"))

		self.assertEqual(queued, 2)
		self.assertEqual(
			enqueue.call_args_list,
			[call("C-1", "ACME"), call("C-1", "Old Co"), call("C-2", "ACME"), call("C-2", "Old Co")],
		)
		self.assertEqual(set_value.call_count, 2)
		self.assertEqual(set_value.call_args.args[2]["taxjar_customer_sync_status"], "Queued")

	def test_a_customer_restricted_to_other_companies_is_left_alone(self):
		"""Queued with no job to clear it would sit there for good."""
		queued, set_value, enqueue = self._run(["C-1"], allowed={"C-1": {"Elsewhere"}})

		self.assertEqual(queued, 0)
		set_value.assert_not_called()
		enqueue.assert_not_called()

	def test_nothing_without_a_taxjar_company(self):
		queued, set_value, enqueue = self._run(["C-1"], companies=())

		self.assertEqual(queued, 0)
		enqueue.assert_not_called()


class TestGoingLive(UnitTestCase):
	"""TaxJar Settings queues the start when API Mode changes to Live."""

	def _on_update(self, changed, mode):
		from taxjar_integration.taxjar_integration.doctype.taxjar_settings import taxjar_settings as ts

		doc = MagicMock()
		doc.flags.nexus_sync = False
		doc.api_mode = mode
		doc.has_value_changed.side_effect = lambda field: field == "api_mode" and changed
		doc.table_hvjw = []
		doc.company_config = []
		with patch.object(ts, "clear_company_config_cache"), \
		     patch.object(ts, "_is_taxjar_enabled", return_value=False), \
		     patch.object(ts.frappe, "enqueue"), \
		     patch(f"{_LC}.enqueue_live_work") as start:
			ts.TaxJarSettings.on_update(doc)
		return start.called

	def test_a_change_to_live_queues_the_start(self):
		self.assertTrue(self._on_update(changed=True, mode="Live"))

	def test_other_saves_do_not(self):
		for changed, mode in ((False, "Live"), (True, "Sandbox")):
			with self.subTest(changed=changed, mode=mode):
				self.assertFalse(self._on_update(changed=changed, mode=mode))


class TestTheStateTheTabReads(UnitTestCase):
	def _state(self, status, job_alive):
		values = frappe._dict(
			legacy_cutoff_date="2026-10-01",
			legacy_check_status=status,
			legacy_check_summary=json.dumps({"Old Co": {"result": RESULT_DONE, "found": 3}}),
			api_mode="Live",
		)
		with patch(f"{_LC}.frappe.has_permission"), \
		     patch(f"{_LC}.frappe.db.get_value", return_value=values), \
		     patch(f"{_LC}.is_job_enqueued", return_value=job_alive), \
		     patch(f"{_LC}.pending_by_company", return_value=[_pending("ACME", invoices=7)]), \
		     patch(f"{_LC}.get_client", return_value=_client()):
			return legacy_check.get_legacy_check_state()

	def test_a_run_whose_worker_died_reads_failed(self):
		"""Otherwise the tab says Running for good, with the button disabled."""
		self.assertEqual(self._state(STATUS_RUNNING, job_alive=False)["status"], STATUS_FAILED)
		self.assertEqual(self._state(STATUS_RUNNING, job_alive=True)["status"], STATUS_RUNNING)

	def test_lists_waiting_and_finished_companies(self):
		state = self._state(STATUS_DONE, job_alive=False)

		by_company = {row["company"]: row for row in state["companies"]}
		self.assertEqual(by_company["ACME"]["pending"], 7)
		self.assertEqual(by_company["ACME"]["first_month"], "2026-08")
		self.assertTrue(by_company["ACME"]["has_credential"])
		self.assertEqual(by_company["Old Co"]["pending"], 0)
		self.assertEqual(by_company["Old Co"]["found"], 3)
		self.assertEqual(state["pending"], 7)
		self.assertEqual(state["cutoff_month"], "2026-10")


class TestProvider(UnitTestCase):
	def test_ours_unless_the_invoice_records_another(self):
		self.assertEqual(provider_params(frappe._dict()), {"provider": TAXJAR_PROVIDER})
		self.assertEqual(provider_params(frappe._dict(taxjar_provider="")), {"provider": TAXJAR_PROVIDER})
		self.assertEqual(
			provider_params(frappe._dict(taxjar_provider=LEGACY_PROVIDER)), {"provider": LEGACY_PROVIDER}
		)

	def test_the_delete_path_asks_under_the_recorded_provider(self):
		"""A pre-upgrade order deleted under our provider answers 404, and the
		delete path reads a 404 as "already gone" - while TaxJar keeps it."""
		from taxjar_integration.taxjar_integration import taxjar_integration as tj

		doc = frappe._dict(name="SINV-2", company="ACME", is_return=0, taxjar_provider=LEGACY_PROVIDER)
		client = MagicMock()
		with patch.object(tj.frappe, "get_doc", return_value=doc), \
		     patch.object(tj, "get_client", return_value=client), \
		     patch.object(tj, "log_taxjar_call"), \
		     patch.object(tj, "_set_sync_status"):
			tj.delete_transaction_from_taxjar("SINV-2")

		client.delete_order.assert_called_once_with("SINV-2", params={"provider": LEGACY_PROVIDER})


class TestCancelBeforeTheCheckAnswers(UnitTestCase):
	"""An invoice cancelled before legacy_check.py has answered records no
	provider. Only version 15 can have filed it, under LEGACY_PROVIDER.

	TaxJar's delete answers success under any provider, and removes the order
	only under the one that holds it (verified on the live API, 2026-10-12).
	So the job cannot learn from the answer, and must ask the right provider
	first. The client below answers the way TaxJar does."""

	def _delete(self, doc):
		from taxjar_integration.taxjar_integration import taxjar_integration as tj

		client = MagicMock()
		with patch.object(tj.frappe, "get_doc", return_value=doc), \
		     patch.object(tj, "get_client", return_value=client), \
		     patch.object(tj, "log_taxjar_call"), \
		     patch.object(tj, "_record_sync_failure") as failure, \
		     patch.object(tj, "_set_sync_status") as status:
			tj.delete_transaction_from_taxjar(doc.name)
		return client, status, failure

	def _invoice(self, **values):
		return frappe._dict({"name": "SINV-3", "company": "ACME", "is_return": 0, **values})

	def test_an_unchecked_invoice_is_deleted_under_the_version_15_provider(self):
		client, status, failure = self._delete(self._invoice(taxjar_exclusion_reason=EXCLUSION_LEGACY_UNCHECKED))

		client.delete_order.assert_called_once_with("SINV-3", params={"provider": LEGACY_PROVIDER})
		status.assert_called_once_with("SINV-3", "Synced")
		failure.assert_not_called()

	def test_an_unchecked_return_is_deleted_the_same_way(self):
		client, _status, _failure = self._delete(
			self._invoice(is_return=1, taxjar_exclusion_reason=EXCLUSION_LEGACY_UNCHECKED)
		)

		client.delete_refund.assert_called_once_with("SINV-3", params={"provider": LEGACY_PROVIDER})
		client.delete_order.assert_not_called()

	def test_a_checked_invoice_uses_the_provider_it_records(self):
		client, _status, _failure = self._delete(self._invoice(taxjar_provider=LEGACY_PROVIDER))

		client.delete_order.assert_called_once_with("SINV-3", params={"provider": LEGACY_PROVIDER})

	def test_an_invoice_filed_after_the_upgrade_uses_ours(self):
		"""Asking under the version-15 provider could delete a different order
		that version 15 filed with the same name."""
		client, _status, _failure = self._delete(self._invoice(taxjar_exclusion_reason=""))

		client.delete_order.assert_called_once_with("SINV-3", params={"provider": TAXJAR_PROVIDER})

	def test_a_not_found_invoice_uses_ours(self):
		"""The check found nothing under the version-15 provider. If anyone
		filed it since, this app did, under its own."""
		client, _status, _failure = self._delete(self._invoice(taxjar_exclusion_reason=EXCLUSION_LEGACY_NOT_FOUND))

		client.delete_order.assert_called_once_with("SINV-3", params={"provider": TAXJAR_PROVIDER})

	def test_the_job_asks_once(self):
		"""TaxJar's answer cannot tell a deleted order from one it never held, so
		a second provider would only be a guess."""
		client, _status, _failure = self._delete(self._invoice(taxjar_exclusion_reason=EXCLUSION_LEGACY_UNCHECKED))

		self.assertEqual(client.delete_order.call_count, 1)


class TestThePatch(UnitTestCase):
	def test_does_nothing_unless_this_migrate_upgrades_from_version_15(self):
		"""A site already on version 16 runs this patch once, on the migrate that
		ships it. Its old Excluded rows are not version-15 invoices to check."""
		from taxjar_integration.patches import mark_pre_upgrade_invoices as patch_module

		with patch.object(patch_module, "is_version_15_upgrade", return_value=False), \
		     patch.object(patch_module, "_mark_query") as mark, \
		     patch.object(patch_module.frappe.db, "set_single_value") as set_single:
			patch_module.execute()
		mark.assert_not_called()
		set_single.assert_not_called()

	def test_marks_the_invoices_and_records_the_upgrade_date(self):
		from taxjar_integration.patches import mark_pre_upgrade_invoices as patch_module

		with patch.object(patch_module, "is_version_15_upgrade", return_value=True), \
		     patch.object(patch_module.frappe.db, "has_column", return_value=True), \
		     patch.object(patch_module, "_mark_query") as mark, \
		     patch.object(patch_module.frappe.db, "set_single_value") as set_single, \
		     patch.object(patch_module, "today", return_value="2026-10-01"):
			patch_module.execute()
		mark.return_value.run.assert_called_once_with()
		set_single.assert_called_once_with(
			"TaxJar Settings", {"legacy_cutoff_date": "2026-10-01", "legacy_check_status": "Pending"}
		)

	def test_marks_only_rows_this_app_did_not_write(self):
		"""A row with a reason, or with a status other than Excluded, records
		what this app did. Only the rows the column default wrote are marked."""
		from taxjar_integration.patches import mark_pre_upgrade_invoices as patch_module

		sql = " ".join(str(patch_module._mark_query()).split())

		self.assertIn(f"`taxjar_exclusion_reason`='{EXCLUSION_LEGACY_UNCHECKED}'", sql)
		self.assertIn("`docstatus` IN (1,2)", sql)
		self.assertIn("COALESCE(`taxjar_sync_status`,'') IN ('','Excluded')", sql)
		self.assertIn("COALESCE(`taxjar_exclusion_reason`,'')=''", sql)

	def test_it_runs_while_the_version_15_marker_is_set(self):
		"""clear_version_15_upgrade_marker deletes the marker, so this patch has
		to come before it."""
		import os

		import taxjar_integration

		path = os.path.join(os.path.dirname(taxjar_integration.__file__), "patches.txt")
		with open(path) as handle:
			order = [line.strip() for line in handle if line.strip().startswith("taxjar_integration.")]

		self.assertLess(
			order.index("taxjar_integration.patches.mark_pre_upgrade_invoices"),
			order.index("taxjar_integration.patches.clear_version_15_upgrade_marker"),
		)


class TestTheTab(UnitTestCase):
	"""The Migration tab shows on every site. Only a site upgraded
	from version 15 has invoices in it."""

	def _settings_path(self, name):
		import os

		return os.path.join(
			frappe.get_app_path("taxjar_integration"), "taxjar_integration", "doctype", "taxjar_settings", name
		)

	def test_the_tab_has_no_condition(self):
		with open(self._settings_path("taxjar_settings.json")) as handle:
			fields = {f["fieldname"]: f for f in json.load(handle)["fields"]}

		self.assertEqual(fields["legacy_tab"]["label"], "Migration")
		self.assertFalse(fields["legacy_tab"].get("depends_on"))
		self.assertFalse(fields["legacy_tab"].get("hidden"))

	def test_the_tab_is_drawn_without_an_upgrade_date(self):
		with open(self._settings_path("taxjar_settings.js")) as handle:
			js = handle.read()

		self.assertNotIn("!frm.doc.legacy_cutoff_date", js)
		self.assertIn("if (!state.cutoff_date) {", js)
		self.assertIn("Nothing to check on this site", js)
		self.assertNotIn("__('Not needed')", js)

	def test_the_tab_is_one_full_width_view(self):
		"""The view draws its own header, button and dates. The fields that used
		to hold them are gone, and the two dates sit in the hidden section."""
		with open(self._settings_path("taxjar_settings.json")) as handle:
			doc = json.load(handle)
		fields = {f["fieldname"]: f for f in doc["fields"]}
		order = doc["field_order"]

		for gone in ("legacy_intro_html", "legacy_check_status_html", "run_legacy_check_btn", "section_legacy_check"):
			self.assertNotIn(gone, fields)
		self.assertTrue(fields["section_legacy_raw"].get("hidden"))
		raw = order.index("section_legacy_raw")
		for kept in ("legacy_cutoff_date", "legacy_check_last_run"):
			self.assertGreater(order.index(kept), raw)

	def test_the_status_reads_as_the_design_names_it(self):
		with open(self._settings_path("taxjar_settings.js")) as handle:
			js = handle.read()

		self.assertIn("__('TaxJar Invoice Sync Status')", js)
		for label in ("Checking…", "All found", "Needs review", "Stale in TaxJar"):
			self.assertIn(f"__('{label}')", js)

	def test_the_issues_are_alerts_not_a_summary_line(self):
		"""A company the check flagged gets one alert that names its not-found
		and stale invoices, below the table."""
		with open(self._settings_path("taxjar_settings.js")) as handle:
			js = handle.read()

		self.assertNotIn("_legacy_summary", js)
		self.assertNotIn("cancelled but still in TaxJar'", js)
		self.assertIn("if (!row.pending && (row.not_found || row.cancelled_in_taxjar)) {", js)
		self.assertIn("alerts.push(_legacy_review_alert(state, row));", js)
		self.assertGreater(js.index("const alerts = _legacy_alerts(state);"), js.index("$section.append(_legacy_companies_table(frm, state));"))

	def test_alert_titles_carry_no_count(self):
		"""The title names the issue. The count is in the description."""
		import re

		with open(self._settings_path("taxjar_settings.js")) as handle:
			js = handle.read()

		alerts = js[js.index("function _legacy_alerts"):js.index("function _open_setup_connection")]
		titles = re.findall(r"title(?::|\s*=)\s*__\('([^']*)'", alerts)
		self.assertEqual(len(titles), 6)
		for title in titles:
			# {0} is the company. Any other placeholder or digit is a count.
			self.assertNotRegex(title.replace("{0}", ""), r"\{\d\}|\d", title)

	def test_the_heading_carries_no_status_badge(self):
		"""Each company's result is in the table, so the heading shows none."""
		with open(self._settings_path("taxjar_settings.js")) as handle:
			js = handle.read()

		self.assertNotIn("LEGACY_STATUS", js)
		for label in ("Not run", "Completed"):
			self.assertNotIn(f"__('{label}')", js)

	def test_the_state_of_a_site_that_did_not_upgrade(self):
		with patch(f"{_LC}.require_permission"), \
		     patch(f"{_LC}.frappe.db.get_value", return_value=frappe._dict(api_mode="Live")), \
		     patch(f"{_LC}.pending_by_company", return_value=[]):
			state = legacy_check.get_legacy_check_state()

		self.assertIsNone(state["cutoff_date"])
		self.assertIsNone(state["last_run"])
		self.assertIsNone(state["cutoff_month"])
		self.assertEqual(state["companies"], [])
		self.assertEqual(state["pending"], 0)


class TestTheInvoiceButton(UnitTestCase):
	def test_no_sync_button_before_the_check_answers(self):
		"""Version 15 may have filed the invoice already, under another
		provider. A second send would file it twice."""
		import os

		path = os.path.join(os.path.dirname(__file__), "..", "public", "js", "sales_invoice.js")
		with open(path) as f:
			js = f.read()

		self.assertIn(
			f'if (frm.doc.taxjar_exclusion_reason === "{EXCLUSION_LEGACY_UNCHECKED}") return;', js
		)
