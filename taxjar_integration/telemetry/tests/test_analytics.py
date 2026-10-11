import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from taxjar_integration import telemetry
from taxjar_integration.telemetry import feature_state
from taxjar_integration.telemetry.events import BROWSER_EVENTS, EVENTS

APP = Path(frappe.get_app_path("taxjar_integration"))
TELEMETRY = "taxjar_integration.telemetry"

# capture("x"), capture_once("x") and capture_for_user("x") in Python;
# taxjar_integration.track("x") in JavaScript.
PY_CALL = re.compile(r"\bcapture(?:_once|_for_user)?\(\s*\"(taxjar_[a-z_]+)\"")
JS_CALL = re.compile(r"taxjar_integration\.track\(\s*\"(taxjar_[a-z_]+)\"")


def _sent_events(pattern, suffix):
	"""Event names sent from the app's own code, outside tests and built files."""
	names = set()
	for path in APP.rglob(f"*{suffix}"):
		if path.name.startswith("test_") or "dist" in path.parts or "node_modules" in path.parts:
			continue
		names |= set(pattern.findall(path.read_text()))
	return names


class TestEventWiring(UnitTestCase):
	"""An event name that is not in EVENTS is dropped with only a log line, so a
	typo would lose the event without any visible error. These tests read the code."""

	def test_every_event_that_the_code_sends_is_in_the_list(self):
		sent = _sent_events(PY_CALL, ".py") | _sent_events(JS_CALL, ".js")
		self.assertEqual(sent - set(EVENTS), set())

	def test_every_event_in_the_list_is_sent_somewhere(self):
		sent = _sent_events(PY_CALL, ".py") | _sent_events(JS_CALL, ".js")
		self.assertEqual(set(EVENTS) - sent, set())

	def test_the_browser_sends_only_browser_events(self):
		self.assertEqual(_sent_events(JS_CALL, ".js"), set(BROWSER_EVENTS))

	def test_no_event_carries_a_user_id(self):
		"""All events are site-level. capture_for_user exists, but nothing uses it yet."""
		for path in APP.rglob("*.py"):
			if path == APP / "telemetry" / "__init__.py" or path.name.startswith("test_"):
				continue
			with self.subTest(file=path.name):
				self.assertNotIn("capture_for_user(", path.read_text())


class TestCountProperties(UnitTestCase):
	def test_a_count_must_be_a_whole_number_of_zero_or_more(self):
		allowed = telemetry.allowed_properties
		self.assertEqual(allowed("taxjar_exemption_cleared", {"customers": 0}), {"customers": 0})
		self.assertEqual(allowed("taxjar_exemption_cleared", {"customers": 12}), {"customers": 12})
		for bad in (-1, True, "3", 2.5, None):
			with self.subTest(value=bad):
				self.assertEqual(allowed("taxjar_exemption_cleared", {"customers": bad}), {})


class TestCaptureOnce(IntegrationTestCase):
	"""Telemetry is off in test runs unless a test asks for it (telemetry._active)."""

	EVENT = "taxjar_first_tax_calculated"

	def setUp(self):
		frappe.flags.taxjar_telemetry_in_test = True
		frappe.defaults.clear_default(telemetry.SENT_PREFIX + self.EVENT)

	def tearDown(self):
		frappe.flags.taxjar_telemetry_in_test = False
		frappe.defaults.clear_default(telemetry.SENT_PREFIX + self.EVENT)

	def test_sends_the_first_time_only(self):
		with patch(f"{TELEMETRY}.is_pulse_enabled", return_value=True), patch(f"{TELEMETRY}.capture") as capture:
			telemetry.capture_once(self.EVENT, days_since_setup=3)
			telemetry.capture_once(self.EVENT, days_since_setup=4)

		capture.assert_called_once_with(self.EVENT, days_since_setup=3)

	def test_waits_while_telemetry_is_off(self):
		"""A site that turns telemetry on later still sends its first event."""
		with patch(f"{TELEMETRY}.capture") as capture:
			with patch(f"{TELEMETRY}.is_pulse_enabled", return_value=False):
				telemetry.capture_once(self.EVENT)
			with patch(f"{TELEMETRY}.is_pulse_enabled", return_value=True):
				telemetry.capture_once(self.EVENT)

		capture.assert_called_once_with(self.EVENT)


class TestBrowserTrack(UnitTestCase):
	def test_sends_a_browser_event_with_its_properties(self):
		with patch(f"{TELEMETRY}.capture") as capture:
			telemetry.track("taxjar_setup_step_viewed", '{"step": "connect"}')

		capture.assert_called_once_with("taxjar_setup_step_viewed", step="connect")

	def test_refuses_an_event_that_only_the_server_may_send(self):
		with patch(f"{TELEMETRY}.capture") as capture:
			telemetry.track("taxjar_setup_finished", {"companies": 1})

		capture.assert_not_called()

	def test_refuses_properties_that_are_not_an_object(self):
		with patch(f"{TELEMETRY}.capture") as capture:
			telemetry.track("taxjar_setup_step_viewed", '["connect"]')

		capture.assert_not_called()


class TestFeatureState(IntegrationTestCase):
	"""The collectors run on this site's real tables."""

	def test_every_collected_property_is_allowed(self):
		for collect in (
			feature_state.settings_state,
			feature_state.document_state,
			feature_state.invoice_state,
			feature_state.customer_state,
			feature_state.sync_error_state,
			feature_state.api_call_state,
		):
			with self.subTest(collector=collect.__name__):
				state = collect()
				self.assertEqual(telemetry.allowed_properties("taxjar_feature_state", state), state)

	def test_one_broken_collector_does_not_stop_the_others(self):
		def document_state():
			raise RuntimeError("boom")

		with (
			patch.object(feature_state, "is_pulse_enabled", return_value=True),
			patch.object(feature_state, "document_state", new=document_state),
			patch.object(feature_state, "capture") as capture,
			patch.object(feature_state.frappe, "log_error"),
		):
			feature_state.capture_feature_state()

		sent = capture.call_args.kwargs
		self.assertIn("companies", sent)
		self.assertNotIn("items_with_tax_category", sent)

	def test_sends_nothing_while_telemetry_is_off(self):
		with (
			patch.object(feature_state, "is_pulse_enabled", return_value=False),
			patch.object(feature_state, "capture") as capture,
		):
			feature_state.capture_feature_state()

		capture.assert_not_called()


class TestFrictionEvents(UnitTestCase):
	MODULE = "taxjar_integration.taxjar_integration.taxjar_integration"

	def test_a_submit_with_no_destination_is_counted(self):
		from taxjar_integration.taxjar_integration.taxjar_integration import validate_taxable_destination

		doc = frappe._dict(company="Test Co", shipping_address_name=None, customer_address=None)
		with (
			patch(f"{self.MODULE}.company_scope", return_value=SimpleNamespace(files=True)),
			patch(f"{self.MODULE}.capture") as capture,
			self.assertRaises(frappe.ValidationError),
		):
			validate_taxable_destination(doc)

		capture.assert_called_once_with("taxjar_document_blocked", reason="destination_required")


class TestVersionProperty(UnitTestCase):
	def test_accepts_version_strings_only(self):
		version = telemetry.Version()
		self.assertEqual(version.clean("16.2.0"), "16.2.0")
		self.assertEqual(version.clean("17.0.0-dev"), "17.0.0-dev")
		for bad in ("<script>", "1.0 beta", "x" * 41, 16, None):
			with self.subTest(value=bad):
				self.assertIsNone(version.clean(bad))


class TestSyncErrorReasons(UnitTestCase):
	def test_a_taxjar_refusal_is_split_by_status(self):
		from taxjar_integration.taxjar_integration.taxjar_integration import _sync_error_reason

		cases = {
			401: "auth",
			403: "auth",
			400: "rejected",
			422: "rejected",
			429: "rate_limited",
			503: "server_error",
			418: "response_other",
		}
		for status, reason in cases.items():
			with self.subTest(status=status):
				self.assertEqual(_sync_error_reason({"kind": "response", "status": status}), reason)

	def test_every_other_kind_is_its_own_reason(self):
		from taxjar_integration.taxjar_integration.taxjar_integration import _sync_error_reason

		for kind in ("connection", "validation", "unreadable", "not_configured", "unknown"):
			with self.subTest(kind=kind):
				self.assertEqual(_sync_error_reason({"kind": kind, "status": None}), kind)


class TestSyncErrorCounts(IntegrationTestCase):
	"""Real Redis: the counters live in the site cache, under a site-prefixed key."""

	def setUp(self):
		frappe.flags.taxjar_telemetry_in_test = True
		telemetry.take_sync_error_counts("invoice")

	def tearDown(self):
		telemetry.take_sync_error_counts("invoice")
		frappe.flags.taxjar_telemetry_in_test = False

	def test_counts_by_reason_and_resets_on_read(self):
		with patch(f"{TELEMETRY}.is_pulse_enabled", return_value=True):
			telemetry.count_sync_error("invoice", "connection")
			telemetry.count_sync_error("invoice", "connection")
			telemetry.count_sync_error("invoice", "auth")
			telemetry.count_sync_error("invoice", "made_up")

		self.assertEqual(telemetry.take_sync_error_counts("invoice"), {"connection": 2, "auth": 1})
		self.assertEqual(telemetry.take_sync_error_counts("invoice"), {})

	def test_counts_survive_a_cache_clear(self):
		"""frappe.clear_cache() runs on many ordinary actions, for example a saved setting."""
		with patch(f"{TELEMETRY}.is_pulse_enabled", return_value=True):
			telemetry.count_sync_error("invoice", "connection")
			frappe.clear_cache()

		self.assertEqual(telemetry.take_sync_error_counts("invoice"), {"connection": 1})

	def test_counts_nothing_while_telemetry_is_off(self):
		with patch(f"{TELEMETRY}.is_pulse_enabled", return_value=False):
			telemetry.count_sync_error("invoice", "connection")

		self.assertEqual(telemetry.take_sync_error_counts("invoice"), {})


class TestApiCallTypes(UnitTestCase):
	MODULE = "taxjar_integration.taxjar_integration.taxjar_integration"
	LIVE = "https://api.taxjar.com/v2/"

	def test_every_endpoint_that_the_app_calls_has_a_type(self):
		from taxjar_integration.taxjar_integration.taxjar_integration import _api_call_type

		cases = {
			("POST", "taxes"): "tax_calculation",
			("POST", "transactions/orders"): "order_create",
			("PUT", "transactions/orders/ACC-SINV-2026-00001"): "order_update",
			("DELETE", "transactions/orders/ACC-SINV-2026-00001"): "order_delete",
			("GET", "transactions/orders/ACC-SINV-2026-00001"): "order_read",
			("POST", "transactions/refunds"): "refund_create",
			("PUT", "transactions/refunds/ACC-SINV-RET-1"): "refund_update",
			("DELETE", "transactions/refunds/ACC-SINV-RET-1"): "refund_delete",
			("POST", "customers"): "customer_create",
			("PUT", "customers/Acme%20Corp"): "customer_update",
			("DELETE", "customers/Acme%20Corp"): "customer_delete",
			("GET", "customers/Acme%20Corp"): "customer_read",
			("POST", "addresses/validate"): "address_validation",
			("GET", "nexus/regions"): "nexus_regions",
			("GET", "categories"): "categories",
			("GET", "rates/10001"): "other",
			("PATCH", "transactions/orders/X"): "other",
		}
		for (method, path), call_type in cases.items():
			with self.subTest(method=method, path=path):
				self.assertEqual(_api_call_type(method, self.LIVE + path), call_type)

	def test_only_live_calls_are_counted(self):
		from taxjar_integration.taxjar_integration.taxjar_integration import _count_api_call

		def response(url):
			return SimpleNamespace(request=SimpleNamespace(method="POST", url=url))

		with patch(f"{self.MODULE}.count_api_call") as count:
			_count_api_call(response("https://api.taxjar.com/v2/taxes"))
			_count_api_call(response("https://api.sandbox.taxjar.com/v2/taxes"))

		count.assert_called_once_with("tax_calculation")

	def test_a_strange_response_does_not_raise(self):
		from taxjar_integration.taxjar_integration.taxjar_integration import _count_api_call

		with patch(f"{self.MODULE}.count_api_call") as count:
			_count_api_call(object())

		count.assert_not_called()


class TestApiCallCounts(IntegrationTestCase):
	def setUp(self):
		frappe.flags.taxjar_telemetry_in_test = True
		telemetry.take_api_call_counts()

	def tearDown(self):
		telemetry.take_api_call_counts()
		frappe.flags.taxjar_telemetry_in_test = False

	def test_the_snapshot_sends_the_calls_by_type_and_resets_them(self):
		with patch(f"{TELEMETRY}.is_pulse_enabled", return_value=True):
			telemetry.count_api_call("tax_calculation")
			telemetry.count_api_call("tax_calculation")
			telemetry.count_api_call("order_create")
			telemetry.count_api_call("made_up")

		self.assertEqual(
			feature_state.api_call_state(), {"api_calls_tax_calculation": 2, "api_calls_order_create": 1}
		)
		self.assertEqual(feature_state.api_call_state(), {})
