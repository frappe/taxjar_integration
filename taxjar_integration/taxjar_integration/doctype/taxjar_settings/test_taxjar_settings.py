# Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import json

from unittest.mock import DEFAULT, MagicMock, patch

import frappe
from frappe.tests import UnitTestCase

from taxjar_integration.taxjar_integration.taxjar_integration import (
	SUPPORTED_STATE_CODES,
	TAXJAR_ROW_DESCRIPTION,
	_apply_item_discounts,
	_build_synthetic_line_item,
	_classify_foreign_tax_rows,
	_clear_breakdown_data,
	_distribute_negative_total,
	_compute_product_taxable,
	_convert_breakdown_amounts,
	_extract_breakdown_data,
	_extract_breakdown_from_obj,
	_format_address_short,
	_get_customer_exemption_type,
	_get_customer_name,
	_get_effective_exemption,
	_get_transaction_date,
	_get_usd_exchange_rate,
	_has_taxjar_fields_changed,
	_is_taxjar_enabled,
	_linkify_guided_setup,
	_make_safe_customer_id,
	_remove_taxjar_rows,
	_set_customer_sync_status,
	_set_sync_status,
	_set_tax_status_fields,
	_store_breakdown_data,
	_validate_address_with_taxjar,
	check_for_nexus,
	classify_taxjar_error,
	check_sales_tax_exemption,
	delete_customer_from_taxjar,
	delete_transaction_from_taxjar,
	delete_transaction_manual,
	enqueue_taxjar_delete,
	enqueue_taxjar_sync,
	fetch_transaction_from_taxjar,
	get_company_config,
	get_line_item_dict,
	get_taxjar_breakdown_html,
	is_taxjar_enabled_for_company,
	on_customer_delete,
	on_customer_update,
	on_customer_validate,
	preview_foreign_tax_rows,
	_validate_exempt_regions,
	_EXEMPTION_TYPES_REQUIRING_REGIONS,
	sanitize_error_response,
	set_sales_tax,
	set_taxjar_breakdown_html,
	sync_customer_to_taxjar,
	sync_transaction_to_taxjar,
	validate_return_against,
	validate_tax_request,
)
from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
	TaxJarSettings,
	_TRANSACTION_BREAKDOWN_FIELDS,
	_item_tax_fields,
	_US_STATE_CODE_OPTIONS,
	make_custom_fields,
	validate_taxjar_tokens,
)
from taxjar_integration.taxjar_integration.regional.united_states import (
	TAXJAR_TEMPLATE_TITLE,
	_disable_default_us_templates,
	_upsert_tax_template,
	ensure_company_ledgers_and_template,
	resolve_default_ledgers,
	sync_all_company_tax_templates,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_settings(company="Test Co", tax_head="Sales Tax - TC", shipping_head="Freight - TC", api_mode="Sandbox", sandbox_key="sk_test"):
	config_row = MagicMock()
	config_row.company = company
	config_row.tax_account_head = tax_head
	config_row.shipping_account_head = shipping_head

	settings = MagicMock()
	settings.api_mode = api_mode
	settings.sandbox_key = sandbox_key
	settings.company_config = [config_row]
	settings.table_hvjw = []
	return settings


class _TaxRow:
	"""Minimal stand-in for a Sales Taxes and Charges row."""
	def __init__(self, account_head, description="", tax_amount=100.0, idx=1):
		self.account_head = account_head
		self.description = description
		self.tax_amount = tax_amount
		self.idx = idx


def _make_tax_row(account_head, description="", tax_amount=100.0, idx=1):
	return _TaxRow(account_head, description, tax_amount, idx)


class _FakeItem:
	def __init__(self, idx=1, qty=1, rate=100.0, net_amount=None):
		self.idx = idx
		self.qty = qty
		self.rate = rate
		self.product_tax_category = None
		self.tax_collectable = 0.0
		self.price_list_rate = None
		self.rate_with_margin = None
		# no discount happened by default - matches _make_item()'s baseline.
		self.net_amount = rate * qty if net_amount is None else net_amount

	def get(self, field):
		return getattr(self, field, None)


class _FakeMeta:
	"""Stand-in for doc.meta - real doctype metadata, not instance state.

	Deliberately NOT driven off which attributes _FakeDoc happens to have set:
	a virtual field (is_virtual=1, no backing @property) is never set as a
	plain instance attribute on a real Document until something explicitly
	assigns it - hasattr(doc, fieldname) is unreliable for exactly the fields
	set_taxjar_breakdown_html needs to check for. This bit taxjar_breakdown_html
	in production: a hasattr guard silently no-opped for every real document.
	"""
	def __init__(self, fields=("taxjar_breakdown_html", "taxjar_breakdown_json", "taxjar_freight_taxable")):
		self._fields = set(fields)

	def has_field(self, fieldname):
		return fieldname in self._fields


class _FakeDoc:
	"""Minimal stand-in for a Frappe document that supports append() on taxes."""
	def __init__(self, company="Test Co", taxes=None, currency="USD", items=None):
		self.company = company
		self.doctype = "Sales Invoice"
		self.name = "SINV-TEST-001"
		self.docstatus = 0
		self.is_return = False
		self.return_against = None
		self.posting_date = "2025-06-01"
		self.transaction_date = "2025-06-01"
		self.net_total = 1000.0
		self.total = 1000.0
		self.exempt_from_sales_tax = 0
		self.customer = "_Test Customer"
		self.shipping_address_name = "Test Address"
		self.customer_address = None
		self.currency = currency
		self.items = items if items is not None else [_FakeItem()]   # must be non-empty to pass the early-return guard
		self.taxes = list(taxes) if taxes else []
		self.taxjar_breakdown_json = None
		self.taxjar_has_nexus = 0
		self.taxjar_nexus_reason = None
		self.taxjar_customer_taxable = 0
		self.taxjar_customer_taxable_reason = None
		self.taxjar_product_taxable = None
		self.taxjar_product_taxable_reason = None
		self.taxjar_ship_from = None
		self.taxjar_ship_to = None
		self.taxjar_tax_source = None
		self.taxjar_freight_taxable = 0
		self.taxjar_breakdown_html = None
		self._onload = {}
		self.meta = _FakeMeta()

	def append(self, field, data):
		if field == "taxes":
			row = _TaxRow(
				account_head=data.get("account_head", ""),
				description=data.get("description", ""),
				tax_amount=data.get("tax_amount", 0.0),
			)
			self.taxes.append(row)

	def run_method(self, method):
		pass

	def get(self, field):
		return getattr(self, field, [])

	def set_onload(self, key, value):
		self._onload[key] = value

	def get_onload(self, key=None):
		return self._onload[key] if key else self._onload


# Doctypes the framework itself reads through frappe.db.get_value while doing
# unrelated work - loading a Meta, resolving a custom field. A test stubbing
# get_value must let these through.
_FRAMEWORK_DOCTYPES = frozenset({"DocType", "DocField", "Custom Field", "Property Setter", "DocPerm"})


def _scalar_get_value(value):
	"""frappe.db.get_value stub answering the app's own lookups with `value`
	while letting the framework's internal ones reach the real implementation.

	frappe.get_meta() loads a DocType through frappe.db.get_value, so a blanket
	`return_value=` hands the meta loader a scalar and it dies with "'str'
	object has no attribute 'get'". It only bites when that meta is not already
	cached, which depends on which tests ran first - so the blanket form fails
	by test order rather than never.
	"""
	real = frappe.db.get_value

	def side_effect(doctype, *args, **kwargs):
		if doctype in _FRAMEWORK_DOCTYPES:
			return real(doctype, *args, **kwargs)
		return value

	return side_effect


def _make_doc(company="Test Co", taxes=None, currency="USD", items=None):
	return _FakeDoc(company=company, taxes=taxes, currency=currency, items=items)


# ── Phase 1: Schema & Validation ──────────────────────────────────────────────

class TestTaxJarSettings(UnitTestCase):

	def setUp(self):
		self.settings = frappe.get_single("TaxJar Settings")
		self.settings.taxjar_enabled = 0
		self.settings.api_mode = "Live"
		self.settings.set("table_hvjw", [])
		self.settings.set("company_config", [])
		self.settings.set("nexus", [])

	def _add_sandbox_credential(self):
		self.settings.append("table_hvjw", {
			"company": "_Test Company",
			"sandbox_token": "test-sandbox-token",
		})

	def _enable_feature(self, calculate=0, create=0, company="_Test Company"):
		"""Turn on the master switch and add a company config row carrying the
		per-company feature flags."""
		self.settings.taxjar_enabled = 1
		self.settings.set("company_config", [{
			"company": company,
			"tax_account_head": "Sales Tax - _TC",
			"shipping_account_head": "Freight - _TC",
			"taxjar_calculate_tax": calculate,
			"taxjar_create_transactions": create,
		}])

	# validate() — no features enabled: always passes regardless of api_mode or credentials

	def test_validate_no_features_blank_mode_passes(self):
		"""Fresh install state: blank mode, no credentials, no features — must save cleanly."""
		self.settings.api_mode = ""
		self.settings.set("table_hvjw", [])
		self.settings.validate()  # must not raise

	def test_validate_no_features_live_mode_no_creds_passes(self):
		"""Credentials are not required when no features are enabled."""
		self.settings.api_mode = "Live"
		self.settings.set("table_hvjw", [])
		self.settings.validate()  # must not raise

	def test_validate_no_features_sandbox_mode_no_creds_passes(self):
		self.settings.api_mode = "Sandbox"
		self.settings.set("table_hvjw", [])
		self.settings.validate()  # must not raise

	# validate() — features enabled, blank mode

	def test_validate_blank_mode_with_calculate_tax_throws(self):
		"""Enabling a feature without selecting an API Mode must throw."""
		self.settings.api_mode = ""
		self._enable_feature(calculate=1)
		with self.assertRaises(frappe.exceptions.ValidationError):
			self.settings.validate()

	def test_validate_blank_mode_with_create_transactions_throws(self):
		self.settings.api_mode = ""
		self._enable_feature(create=1)
		with self.assertRaises(frappe.exceptions.ValidationError):
			self.settings.validate()

	# validate() — features enabled, sandbox mode

	def test_validate_sandbox_requires_sandbox_token_when_features_enabled(self):
		self.settings.api_mode = "Sandbox"
		self._enable_feature(calculate=1)
		self.settings.set("table_hvjw", [])
		with self.assertRaises(frappe.exceptions.ValidationError):
			self.settings.validate()

	def test_validate_sandbox_passes_with_sandbox_token_and_features_enabled(self):
		self.settings.api_mode = "Sandbox"
		self._enable_feature(calculate=1)
		self._add_sandbox_credential()
		self.settings.validate()  # must not raise

	def test_validate_sandbox_fails_when_only_live_token_present_and_features_enabled(self):
		"""A row with only live_token is not enough for Sandbox mode."""
		self.settings.api_mode = "Sandbox"
		self._enable_feature(calculate=1)
		self.settings.append("table_hvjw", {
			"company": "_Test Company",
			"live_token": "test-live-token",
		})
		with self.assertRaises(frappe.exceptions.ValidationError):
			self.settings.validate()

	# validate() — features enabled, live mode

	def test_validate_live_requires_credential_when_features_enabled(self):
		self.settings.api_mode = "Live"
		self._enable_feature(calculate=1)
		self.settings.set("table_hvjw", [])
		with self.assertRaises(frappe.exceptions.ValidationError):
			self.settings.validate()

	def test_validate_live_passes_with_credential_and_features_enabled(self):
		self.settings.api_mode = "Live"
		self._enable_feature(calculate=1)
		self.settings.append("table_hvjw", {
			"company": "_Test Company",
			"live_token": "test-live-token",
		})
		self.settings.validate()  # must not raise

	def test_validate_both_features_enabled_passes(self):
		self.settings.api_mode = "Sandbox"
		self._add_sandbox_credential()
		self._enable_feature(calculate=1, create=1)
		self.settings.validate()  # must not raise

	# validate() — feature independence

	def test_create_transactions_alone_enforces_credentials(self):
		"""create_transactions alone (without calculate_tax) must still enforce credentials."""
		self.settings.api_mode = "Live"
		self._enable_feature(create=1)
		self.settings.set("table_hvjw", [])
		with self.assertRaises(frappe.exceptions.ValidationError):
			self.settings.validate()

	def test_calculate_tax_alone_enforces_credentials(self):
		self.settings.api_mode = "Sandbox"
		self._enable_feature(calculate=1)
		self.settings.set("table_hvjw", [])
		with self.assertRaises(frappe.exceptions.ValidationError):
			self.settings.validate()

	# DocType schema

	def test_company_config_has_correct_fields(self):
		doc = frappe.get_meta("TaxJar Company Config")
		fieldnames = [f.fieldname for f in doc.fields]
		self.assertIn("company", fieldnames)
		self.assertIn("tax_account_head", fieldnames)
		self.assertIn("shipping_account_head", fieldnames)
		# Feature flags are per-company (moved off the TaxJar Settings single).
		self.assertIn("taxjar_calculate_tax", fieldnames)
		self.assertIn("taxjar_create_transactions", fieldnames)

	def test_taxjar_settings_has_master_switch_not_per_feature_flags(self):
		meta = frappe.get_meta("TaxJar Settings")
		self.assertIsNotNone(meta.get_field("taxjar_enabled"))
		self.assertIsNone(meta.get_field("taxjar_calculate_tax"))
		self.assertIsNone(meta.get_field("taxjar_create_transactions"))

	def test_taxjar_settings_has_company_config_table(self):
		meta = frappe.get_meta("TaxJar Settings")
		field = meta.get_field("company_config")
		self.assertIsNotNone(field)
		self.assertEqual(field.options, "TaxJar Company Config")

	def test_taxjar_nexus_has_company_field(self):
		meta = frappe.get_meta("TaxJar Nexus")
		field = meta.get_field("company")
		self.assertIsNotNone(field)
		self.assertEqual(field.options, "Company")

	def test_taxjar_settings_no_single_tax_account_head(self):
		meta = frappe.get_meta("TaxJar Settings")
		self.assertIsNone(meta.get_field("tax_account_head"))

	def test_taxjar_settings_no_single_shipping_account_head(self):
		meta = frappe.get_meta("TaxJar Settings")
		self.assertIsNone(meta.get_field("shipping_account_head"))

	def test_taxjar_settings_no_single_company_field(self):
		meta = frappe.get_meta("TaxJar Settings")
		company_link_fields = [
			f for f in meta.fields if f.fieldname == "company" and f.fieldtype == "Link"
		]
		self.assertEqual(len(company_link_fields), 0)

	def test_taxjar_settings_no_sandbox_key_field(self):
		"""Global sandbox_key field must be gone — sandbox token lives in the credential row."""
		meta = frappe.get_meta("TaxJar Settings")
		self.assertIsNone(meta.get_field("sandbox_key"))

	def test_taxjar_api_credential_has_sandbox_token(self):
		meta = frappe.get_meta("TaxJar API Credential")
		field = meta.get_field("sandbox_token")
		self.assertIsNotNone(field)
		self.assertEqual(field.fieldtype, "Password")


# ── get_client() — per-company, per-mode token routing ───────────────────────

class TestGetClient(UnitTestCase):

	def _make_cred(self, company, live_token=None, sandbox_token=None):
		cred = MagicMock()
		cred.company = company
		cred.live_token = live_token
		cred.sandbox_token = sandbox_token
		# mimic getattr behaviour for token fields
		cred.configure_mock(**{"live_token": live_token, "sandbox_token": sandbox_token})
		return cred

	def _make_settings(self, api_mode, creds):
		settings = MagicMock()
		settings.api_mode = api_mode
		settings.table_hvjw = creds
		return settings

	def _call_get_client(self, settings, company=None, decrypted="test-key"):
		from taxjar_integration.taxjar_integration.taxjar_integration import get_client
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_single", return_value=settings), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_decrypted_password", return_value=decrypted), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.taxjar.Client") as mock_client:
			mock_instance = MagicMock()
			mock_client.return_value = mock_instance
			result = get_client(company)
			return mock_client, result

	def test_live_mode_uses_live_token(self):
		cred = self._make_cred("Acme Inc", live_token="live_abc")
		settings = self._make_settings("Live", [cred])
		mock_client, _ = self._call_get_client(settings, company="Acme Inc")
		import taxjar as tj
		mock_client.assert_called_once()
		self.assertEqual(mock_client.call_args[1]["api_url"], tj.DEFAULT_API_URL)

	def test_sandbox_mode_uses_sandbox_token(self):
		cred = self._make_cred("Acme Inc", sandbox_token="sandbox_xyz")
		settings = self._make_settings("Sandbox", [cred])
		mock_client, _ = self._call_get_client(settings, company="Acme Inc")
		import taxjar as tj
		mock_client.assert_called_once()
		self.assertEqual(mock_client.call_args[1]["api_url"], tj.SANDBOX_API_URL)

	def test_sandbox_mode_returns_none_when_no_sandbox_token(self):
		"""Credential row with only live_token must yield no client in Sandbox mode."""
		cred = self._make_cred("Acme Inc", live_token="live_abc", sandbox_token=None)
		settings = self._make_settings("Sandbox", [cred])
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_single", return_value=settings), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_decrypted_password", return_value=None):
			from taxjar_integration.taxjar_integration.taxjar_integration import get_client
			result = get_client("Acme Inc")
		self.assertIsNone(result)

	def test_company_filters_correct_credential_row(self):
		"""Only the row matching doc.company should be used."""
		cred_a = self._make_cred("Acme Inc", live_token="live_acme")
		cred_b = self._make_cred("Other Co", live_token="live_other")
		settings = self._make_settings("Live", [cred_a, cred_b])

		calls = []
		def _capture_decrypt(doctype, name, fieldname):
			calls.append((name, fieldname))
			return "live_acme"

		from taxjar_integration.taxjar_integration.taxjar_integration import get_client
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_single", return_value=settings), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_decrypted_password", side_effect=_capture_decrypt), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.taxjar.Client"):
			get_client("Acme Inc")

		# Only one decrypt call, and it must be for live_token (not sandbox_token)
		self.assertEqual(len(calls), 1)
		self.assertEqual(calls[0][1], "live_token")


# ── Phase 2: get_company_config ───────────────────────────────────────────────

class TestGetCompanyConfig(UnitTestCase):

	def test_returns_config_for_matching_company(self):
		settings = _make_settings(company="Acme Inc")
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_single", return_value=settings):
			result = get_company_config("Acme Inc")
		self.assertIsNotNone(result)
		self.assertEqual(result.company, "Acme Inc")

	def test_returns_none_for_unknown_company(self):
		settings = _make_settings(company="Acme Inc")
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_single", return_value=settings):
			result = get_company_config("Other Co")
		self.assertIsNone(result)

	def test_returns_none_when_config_is_empty(self):
		settings = _make_settings()
		settings.company_config = []
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_single", return_value=settings):
			result = get_company_config("Any Co")
		self.assertIsNone(result)


# ── Phase 2: _remove_taxjar_rows ──────────────────────────────────────────────

class TestRemoveTaxjarRows(UnitTestCase):

	def test_removes_rows_matching_tax_account_head(self):
		config = MagicMock()
		config.tax_account_head = "Sales Tax - TC"
		doc = _make_doc(taxes=[
			_make_tax_row("Sales Tax - TC", TAXJAR_ROW_DESCRIPTION),
			_make_tax_row("Freight - TC"),
			_make_tax_row("Sales Tax - TC", "Template Tax"),  # template row, same account
		])
		_remove_taxjar_rows(doc, config)
		self.assertEqual(len(doc.taxes), 1)
		self.assertEqual(doc.taxes[0].account_head, "Freight - TC")

	def test_leaves_rows_with_different_accounts_untouched(self):
		config = MagicMock()
		config.tax_account_head = "Sales Tax - TC"
		doc = _make_doc(taxes=[
			_make_tax_row("VAT - TC"),
			_make_tax_row("Freight - TC"),
		])
		_remove_taxjar_rows(doc, config)
		self.assertEqual(len(doc.taxes), 2)

	def test_handles_empty_taxes_table(self):
		config = MagicMock()
		config.tax_account_head = "Sales Tax - TC"
		doc = _make_doc(taxes=[])
		_remove_taxjar_rows(doc, config)
		self.assertEqual(len(doc.taxes), 0)


# ── Part B: _classify_foreign_tax_rows (design doc §4) ────────────────────────

class TestClassifyForeignTaxRows(UnitTestCase):

	def _config(self, tax_head="Sales Tax - TC", shipping_head="Freight - TC"):
		return MagicMock(tax_account_head=tax_head, shipping_account_head=shipping_head)

	def test_no_foreign_rows_baseline_unchanged(self):
		doc = _make_doc(taxes=[
			_make_tax_row("Sales Tax - TC", TAXJAR_ROW_DESCRIPTION, 80.0),
			_make_tax_row("Freight - TC", "Shipping", 20.0),
		])
		result = _classify_foreign_tax_rows(doc, self._config())
		self.assertEqual(result["foreign_rows"], [])
		self.assertEqual(result["synthetic_items"], [])
		self.assertEqual(result["item_discounts"], {})

	def test_zero_amount_row_excluded(self):
		doc = _make_doc(taxes=[_make_tax_row("Handling - TC", "Handling Fee", 0.0)])
		result = _classify_foreign_tax_rows(doc, self._config())
		self.assertEqual(result["foreign_rows"], [])

	def test_row_matching_tax_account_excluded(self):
		"""This is our own inserted row - never foreign, by construction."""
		doc = _make_doc(taxes=[_make_tax_row("Sales Tax - TC", "Our own row", 80.0)])
		result = _classify_foreign_tax_rows(doc, self._config())
		self.assertEqual(result["foreign_rows"], [])

	def test_row_matching_shipping_account_excluded(self):
		doc = _make_doc(taxes=[_make_tax_row("Freight - TC", "Shipping", 20.0)])
		result = _classify_foreign_tax_rows(doc, self._config())
		self.assertEqual(result["foreign_rows"], [])

	def test_positive_row_becomes_synthetic_line_item(self):
		doc = _make_doc(taxes=[_make_tax_row("5210 - Handling - TC", "Handling Fee", 20.0, idx=2)])
		with patch(
			"taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value",
			side_effect=_scalar_get_value("Handling Charges"),
		):
			result = _classify_foreign_tax_rows(doc, self._config())
		self.assertEqual(len(result["synthetic_items"]), 1)
		synthetic = result["synthetic_items"][0]
		self.assertEqual(synthetic["id"], 1002)  # 1000 + idx(2)
		self.assertEqual(synthetic["quantity"], 1)
		self.assertIsNone(synthetic["product_tax_code"])
		self.assertEqual(synthetic["product_identifier"], "5210 - Handling - TC")
		self.assertEqual(synthetic["description"], "Handling Charges - Handling Fee")
		self.assertEqual(synthetic["unit_price"], 20.0)
		self.assertEqual(result["item_discounts"], {})

	def test_synthetic_description_falls_back_to_account_head_when_no_account_name(self):
		doc = _make_doc(taxes=[_make_tax_row("5210 - Handling - TC", "Handling Fee", 20.0, idx=1)])
		with patch(
			"taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value",
			side_effect=_scalar_get_value(None),
		):
			result = _classify_foreign_tax_rows(doc, self._config())
		self.assertEqual(result["synthetic_items"][0]["description"], "5210 - Handling - TC - Handling Fee")

	def test_synthetic_description_omits_dangling_separator_when_row_description_blank(self):
		doc = _make_doc(taxes=[_make_tax_row("5210 - Handling - TC", "", 20.0, idx=1)])
		with patch(
			"taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value",
			side_effect=_scalar_get_value("Handling Charges"),
		):
			result = _classify_foreign_tax_rows(doc, self._config())
		self.assertEqual(result["synthetic_items"][0]["description"], "Handling Charges")

	def test_negative_row_distributes_proportionally_by_net_amount(self):
		"""Mirrors apply_discount_amount()'s own distributed_amount math
		(design doc §3.1/§4.3) - a 3:1 net_amount split gets a 3:1 discount
		split."""
		items = [
			_FakeItem(idx=1, qty=1, rate=100.0, net_amount=750.0),
			_FakeItem(idx=2, qty=1, rate=100.0, net_amount=250.0),
		]
		doc = _make_doc(items=items, taxes=[_make_tax_row("Loyalty Discount - TC", "Loyalty", -100.0, idx=3)])
		result = _classify_foreign_tax_rows(doc, self._config())
		self.assertEqual(result["synthetic_items"], [])
		self.assertAlmostEqual(result["item_discounts"][1], 75.0)
		self.assertAlmostEqual(result["item_discounts"][2], 25.0)

	def test_mixed_positive_and_negative_rows(self):
		items = [_FakeItem(idx=1, qty=1, rate=100.0, net_amount=100.0)]
		doc = _make_doc(items=items, taxes=[
			_make_tax_row("Handling - TC", "Handling Fee", 20.0, idx=1),
			_make_tax_row("Loyalty Discount - TC", "Loyalty", -30.0, idx=2),
		])
		with patch(
			"taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value",
			side_effect=_scalar_get_value("Handling"),
		):
			result = _classify_foreign_tax_rows(doc, self._config())
		self.assertEqual(len(result["synthetic_items"]), 1)
		self.assertEqual(result["item_discounts"][1], 30.0)

	def test_no_negative_total_yields_empty_discount_map_even_with_zero_net_amount_items(self):
		"""Guard against a divide-by-zero when every item has net_amount == 0."""
		items = [_FakeItem(idx=1, qty=1, rate=0.0, net_amount=0.0)]
		doc = _make_doc(items=items, taxes=[_make_tax_row("Loyalty Discount - TC", "Loyalty", -30.0, idx=1)])
		result = _classify_foreign_tax_rows(doc, self._config())
		self.assertEqual(result["item_discounts"], {})

	def test_synthetic_id_never_collides_with_a_real_item_idx(self):
		doc = _make_doc(taxes=[_make_tax_row("Handling - TC", "Fee", 5.0, idx=5)])
		with patch(
			"taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value",
			side_effect=_scalar_get_value("Handling"),
		):
			result = _classify_foreign_tax_rows(doc, self._config())
		self.assertEqual(result["synthetic_items"][0]["id"], 1005)

	def test_unconfigured_shipping_account_treats_freight_row_as_foreign(self):
		"""Design doc §4.6: with no shipping_account_head configured, a real
		Freight row is intentionally classified as foreign, not silently
		dropped - TaxJar has no way to know it was shipping."""
		doc = _make_doc(taxes=[_make_tax_row("Freight - TC", "Freight", 15.0, idx=1)])
		config = self._config(shipping_head=None)
		with patch(
			"taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value",
			side_effect=_scalar_get_value("Freight"),
		):
			result = _classify_foreign_tax_rows(doc, config)
		self.assertEqual(len(result["synthetic_items"]), 1)


class TestApplyItemDiscounts(UnitTestCase):

	def test_adds_discount_key_when_absent(self):
		line_items = [{"id": 1, "unit_price": 100.0, "quantity": 1}]
		_apply_item_discounts(line_items, {1: 25.0})
		self.assertEqual(line_items[0]["discount"], 25.0)

	def test_adds_on_top_of_existing_discount(self):
		line_items = [{"id": 1, "unit_price": 100.0, "quantity": 1, "discount": 10.0}]
		_apply_item_discounts(line_items, {1: 25.0})
		self.assertEqual(line_items[0]["discount"], 35.0)

	def test_zero_extra_discount_leaves_line_item_untouched(self):
		line_items = [{"id": 1, "unit_price": 100.0, "quantity": 1}]
		_apply_item_discounts(line_items, {1: 0.0})
		self.assertNotIn("discount", line_items[0])

	def test_ignores_ids_with_no_matching_line_item(self):
		"""An item removed after distribution was computed must not raise."""
		line_items = [{"id": 1, "unit_price": 100.0, "quantity": 1}]
		_apply_item_discounts(line_items, {99: 25.0})
		self.assertNotIn("discount", line_items[0])

	def test_clamps_combined_discount_to_the_lines_own_price(self):
		"""A large foreign discount row distributed onto a line that already
		carries a big item-level discount must not push the combined
		discount above unit_price × quantity - that would be a negative
		effective taxable amount for the line."""
		line_items = [{"id": 1, "unit_price": 100.0, "quantity": 2, "discount": 150.0}]
		_apply_item_discounts(line_items, {1: 100.0})
		self.assertEqual(line_items[0]["discount"], 200.0)  # 100 * 2, not 250

	def test_clamp_uses_quantity_scaled_price_not_just_unit_price(self):
		line_items = [{"id": 1, "unit_price": 50.0, "quantity": 3}]
		_apply_item_discounts(line_items, {1: 1000.0})
		self.assertEqual(line_items[0]["discount"], 150.0)  # 50 * 3, not 1000


class TestGetTaxDataForeignRows(UnitTestCase):
	"""Integration-level: foreign rows wired into get_tax_data()'s actual
	line_items list, including the multi-currency conversion loop."""

	def _call(self, doc, usd_rate=None):
		from taxjar_integration.taxjar_integration.taxjar_integration import get_tax_data

		mock_company_config = MagicMock(tax_account_head="Sales Tax - TC", shipping_account_head="Freight - TC")
		mock_address = MagicMock(pincode="78701", city="Austin", address_line1="123 Main St",
			country="United States", state="TX")
		mock_address.get.return_value = "TX"

		# frappe.db.get_value is the same shared object regardless of which
		# module's reference reaches it, so patching it here also intercepts
		# Frappe's own internal lookups made during this call - notably
		# flt()'s rounding-method resolution via frappe.get_system_settings(),
		# which silently returns 0 for every value once its own DB call is
		# redirected into a stub with no matching case. wraps= + returning
		# DEFAULT is the supported way to override just one case and let a
		# Mock fall through to the real callable - with the real call's own
		# original args - for everything else, rather than hand-rolling a
		# delegating wrapper that risks getting some other caller's argument
		# shape wrong.
		def fake_get_value(doctype, *args, **kwargs):
			if doctype == "Account":
				return "Handling Charges"
			return DEFAULT

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=mock_company_config), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_address_details", return_value=mock_address), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_shipping_address_details", return_value=mock_address), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value",
		           wraps=frappe.db.get_value, side_effect=fake_get_value), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._get_usd_exchange_rate", return_value=usd_rate), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._get_taxjar_customer_id", return_value=None):
			return get_tax_data(doc)

	def test_synthetic_line_item_appended_after_real_items(self):
		items = [_FakeItem(idx=1, qty=1, rate=100.0, net_amount=100.0)]
		doc = _make_doc(items=items, taxes=[_make_tax_row("Handling - TC", "Handling Fee", 20.0, idx=2)])
		result = self._call(doc)
		self.assertEqual(len(result["line_items"]), 2)
		self.assertEqual(result["line_items"][0]["id"], 1)
		self.assertEqual(result["line_items"][1]["id"], 1002)
		self.assertEqual(result["line_items"][1]["unit_price"], 20.0)

	def test_positive_foreign_row_amount_added_to_top_level_amount(self):
		"""TaxJar's live validation rejects a request where "amount" doesn't
		equal the sum of line items plus shipping - a synthetic line item's
		contribution must be reflected in "amount" too."""
		items = [_FakeItem(idx=1, qty=1, rate=100.0, net_amount=100.0)]
		doc = _make_doc(items=items, taxes=[_make_tax_row("Handling - TC", "Handling Fee", 20.0, idx=2)])
		result = self._call(doc)
		self.assertEqual(result["amount"], 120.0)  # 100 (item) + 20 (synthetic charge)

	def test_negative_row_discount_merged_into_real_item(self):
		items = [_FakeItem(idx=1, qty=1, rate=100.0, net_amount=100.0)]
		doc = _make_doc(items=items, taxes=[_make_tax_row("Loyalty Discount - TC", "Loyalty", -10.0, idx=2)])
		result = self._call(doc)
		self.assertEqual(len(result["line_items"]), 1)
		self.assertEqual(result["line_items"][0]["discount"], 10.0)

	def test_negative_foreign_row_amount_subtracted_from_top_level_amount(self):
		items = [_FakeItem(idx=1, qty=1, rate=100.0, net_amount=100.0)]
		doc = _make_doc(items=items, taxes=[_make_tax_row("Loyalty Discount - TC", "Loyalty", -10.0, idx=2)])
		result = self._call(doc)
		self.assertEqual(result["amount"], 90.0)  # 100 (item) - 10 (distributed discount)

	def test_amount_equals_line_items_plus_shipping_with_no_foreign_rows(self):
		items = [_FakeItem(idx=1, qty=1, rate=100.0, net_amount=100.0)]
		doc = _make_doc(items=items, taxes=[_make_tax_row("Freight - TC", "Shipping", 15.0, idx=1)])
		result = self._call(doc)
		self.assertEqual(result["amount"], 115.0)  # 100 (item) + 15 (shipping)

	def test_multi_currency_conversion_applies_to_synthetic_line_identically(self):
		items = [_FakeItem(idx=1, qty=1, rate=100.0, net_amount=100.0)]
		doc = _make_doc(items=items, currency="EUR", taxes=[_make_tax_row("Handling - TC", "Handling Fee", 20.0, idx=2)])
		result = self._call(doc, usd_rate=1.1)
		synthetic = result["line_items"][1]
		self.assertAlmostEqual(synthetic["unit_price"], 22.0)


# ── Part C: preview_foreign_tax_rows (design doc §5) ──────────────────────────

class TestPreviewForeignTaxRows(UnitTestCase):

	MOD = "taxjar_integration.taxjar_integration.taxjar_integration"

	def _doc_data(self, taxes=None, items=None, company="Test Co", currency="USD"):
		return {
			"doctype": "Sales Invoice",
			"company": company,
			"currency": currency,
			"taxes": taxes or [],
			"items": items or [{"idx": 1, "qty": 1, "rate": 100.0, "net_amount": 100.0}],
		}

	def _call(self, doc_data, calculates_tax=True, region="United States"):
		mock_config = MagicMock(tax_account_head="Sales Tax - TC", shipping_account_head="Freight - TC")
		with patch(f"{self.MOD}.frappe.has_permission"), \
		     patch(f"{self.MOD}.company_calculates_tax", return_value=calculates_tax), \
		     patch(f"{self.MOD}.get_region", return_value=region), \
		     patch(f"{self.MOD}.get_company_config", return_value=mock_config), \
		     patch(f"{self.MOD}.frappe.db.get_value", side_effect=_scalar_get_value("Handling Charges")):
			return preview_foreign_tax_rows(doc_data)

	def test_returns_empty_for_no_foreign_rows(self):
		doc_data = self._doc_data(taxes=[
			{"account_head": "Sales Tax - TC", "description": "Sales Tax", "tax_amount": 80.0, "idx": 1},
			{"account_head": "Freight - TC", "description": "Shipping", "tax_amount": 20.0, "idx": 2},
		])
		self.assertEqual(self._call(doc_data), {"foreign_rows": []})

	def test_returns_empty_when_feature_disabled(self):
		doc_data = self._doc_data(taxes=[
			{"account_head": "Handling - TC", "description": "Fee", "tax_amount": 20.0, "idx": 1},
		])
		self.assertEqual(self._call(doc_data, calculates_tax=False), {"foreign_rows": []})

	def test_returns_empty_for_non_us_region(self):
		doc_data = self._doc_data(taxes=[
			{"account_head": "Handling - TC", "description": "Fee", "tax_amount": 20.0, "idx": 1},
		])
		self.assertEqual(self._call(doc_data, region="Canada"), {"foreign_rows": []})

	def test_positive_row_returns_taxable_line_item_treatment(self):
		doc_data = self._doc_data(taxes=[
			{"account_head": "Handling - TC", "description": "Handling Fee", "tax_amount": 20.0, "idx": 1},
		])
		result = self._call(doc_data)
		self.assertEqual(len(result["foreign_rows"]), 1)
		row = result["foreign_rows"][0]
		self.assertEqual(row["treatment"], "taxable_line_item")
		self.assertEqual(row["amount"], 20.0)
		self.assertEqual(row["description"], "Handling Charges - Handling Fee")

	def test_negative_row_returns_discount_treatment_with_affected_item_count(self):
		doc_data = self._doc_data(
			items=[
				{"idx": 1, "qty": 1, "rate": 100.0, "net_amount": 75.0},
				{"idx": 2, "qty": 1, "rate": 100.0, "net_amount": 25.0},
			],
			taxes=[{"account_head": "Loyalty Discount - TC", "description": "Loyalty", "tax_amount": -10.0, "idx": 1}],
		)
		result = self._call(doc_data)
		self.assertEqual(len(result["foreign_rows"]), 1)
		row = result["foreign_rows"][0]
		self.assertEqual(row["treatment"], "discount")
		self.assertEqual(row["amount"], -10.0)
		self.assertEqual(row["affected_item_count"], 2)

	def test_mixed_rows_returns_both_treatments(self):
		doc_data = self._doc_data(taxes=[
			{"account_head": "Handling - TC", "description": "Fee", "tax_amount": 20.0, "idx": 1},
			{"account_head": "Loyalty Discount - TC", "description": "Loyalty", "tax_amount": -10.0, "idx": 2},
		])
		result = self._call(doc_data)
		treatments = {row["treatment"] for row in result["foreign_rows"]}
		self.assertEqual(treatments, {"taxable_line_item", "discount"})

	def test_no_company_config_returns_empty(self):
		doc_data = self._doc_data(taxes=[
			{"account_head": "Handling - TC", "description": "Fee", "tax_amount": 20.0, "idx": 1},
		])
		with patch(f"{self.MOD}.frappe.has_permission"), \
		     patch(f"{self.MOD}.company_calculates_tax", return_value=True), \
		     patch(f"{self.MOD}.get_region", return_value="United States"), \
		     patch(f"{self.MOD}.get_company_config", return_value=None):
			result = preview_foreign_tax_rows(doc_data)
		self.assertEqual(result, {"foreign_rows": []})

	def test_checks_read_permission_on_the_document_doctype(self):
		doc_data = self._doc_data()
		with patch(f"{self.MOD}.frappe.has_permission") as mock_perm, \
		     patch(f"{self.MOD}.company_calculates_tax", return_value=True), \
		     patch(f"{self.MOD}.get_region", return_value="United States"), \
		     patch(f"{self.MOD}.get_company_config", return_value=MagicMock()):
			preview_foreign_tax_rows(doc_data)
		mock_perm.assert_called_once_with("Sales Invoice", "read", throw=True)

	def test_accepts_a_json_string_as_well_as_a_dict(self):
		"""frappe.xcall may deliver the form field as a raw JSON string rather
		than an already-parsed dict, depending on request encoding."""
		doc_data = self._doc_data(taxes=[
			{"account_head": "Handling - TC", "description": "Fee", "tax_amount": 20.0, "idx": 1},
		])
		result = self._call(json.dumps(doc_data))
		self.assertEqual(len(result["foreign_rows"]), 1)


class TestConfirmForeignTaxRowsJS(UnitTestCase):

	def _js_dir(self):
		import os
		return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "public", "js"))

	def _read_js(self, filename):
		import os
		with open(os.path.join(self._js_dir(), filename)) as f:
			return f.read()

	def _validate_fn(self, filename):
		js = self._read_js(filename)
		return js.split("validate(frm) {")[1].split("\n\t},")[0]

	def _confirm_fn_section(self):
		"""The confirm_foreign_tax_rows()/_show_foreign_tax_rows_dialog() block
		in taxjar_utils.js, up to the next top-level function definition."""
		js = self._read_js("taxjar_utils.js")
		return js.split("taxjar_integration.confirm_foreign_tax_rows = function")[1].split(
			"taxjar_integration.show_address_picker_dialog"
		)[0]

	def test_confirm_foreign_tax_rows_runs_before_check_shipping_address(self):
		"""Design doc §5.3/§6: the foreign-row dialog must resolve before the
		existing shipping-address check runs."""
		for filename in ("quotation.js", "sales_order.js", "sales_invoice.js"):
			validate_fn = self._validate_fn(filename)
			self.assertLess(
				validate_fn.index("confirm_foreign_tax_rows"),
				validate_fn.index("check_shipping_address"),
				f"{filename}: confirm_foreign_tax_rows must run before check_shipping_address",
			)

	def test_all_three_doctypes_wire_up_the_new_check(self):
		for filename in ("quotation.js", "sales_order.js", "sales_invoice.js"):
			self.assertIn(".confirm_foreign_tax_rows(frm)", self._validate_fn(filename))

	def test_calls_preview_endpoint(self):
		js = self._read_js("taxjar_utils.js")
		self.assertIn(
			'"taxjar_integration.taxjar_integration.taxjar_integration.preview_foreign_tax_rows"',
			js,
		)

	def test_cancel_sets_frappe_validated_false(self):
		"""Aborting the dialog must gate save the same way check_shipping_address's
		own abort path does."""
		self.assertIn("frappe.validated = false", self._confirm_fn_section())

	def test_reprompt_is_skipped_when_the_foreign_row_set_is_unchanged(self):
		"""§5.4: caching an acknowledgment hash avoids re-blocking save on
		every unrelated resave of a draft that already carries the same
		foreign rows."""
		self.assertIn("_taxjar_foreign_rows_ack", self._confirm_fn_section())

	def test_dialog_handles_dismiss_without_a_button_as_cancel(self):
		"""Escape/backdrop dismiss must not silently let the save through."""
		self.assertIn("on_hide()", self._confirm_fn_section())


# ── Phase 2: check_for_nexus ─────────────────────────────────────────────────

class TestCheckForNexus(UnitTestCase):

	def test_returns_true_when_in_nexus(self):
		doc = _make_doc(company="Acme Inc")
		tax_dict = {"to_state": "CA"}
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value("NX-1")), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=MagicMock()):
			self.assertTrue(check_for_nexus(doc, tax_dict))

	def test_returns_false_and_clears_rows_when_not_in_nexus(self):
		config = MagicMock()
		config.tax_account_head = "Sales Tax - TC"
		doc = _make_doc(taxes=[_make_tax_row("Sales Tax - TC", TAXJAR_ROW_DESCRIPTION, 50.0)])

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value(None)), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=config):
			result = check_for_nexus(doc, {"to_state": "TX"})

		self.assertFalse(result)
		self.assertEqual(len([t for t in doc.taxes if t.account_head == "Sales Tax - TC"]), 0)


# ── Phase 2: set_sales_tax — double-tax fix ───────────────────────────────────

def _no_cache():
	"""Return a mock frappe.cache() that always misses."""
	mock_cache = MagicMock()
	mock_cache.get_value.return_value = None
	return mock_cache


def _fake_cache():
	"""Return a mock frappe.cache() backed by a plain dict, so a value set by
	one set_sales_tax() call is actually seen by the next one - unlike
	_no_cache(), which always misses and so can't exercise a real hit."""
	store = {}
	mock_cache = MagicMock()
	mock_cache.get_value.side_effect = store.get
	mock_cache.set_value.side_effect = lambda key, value, expires_in_sec=None: store.__setitem__(key, value)
	return mock_cache


class TestSetSalesTax(UnitTestCase):

	def test_replaces_template_row_not_duplicates(self):
		"""Template row for the tax account is removed and replaced by one TaxJar row."""
		doc = _make_doc(taxes=[_make_tax_row("Sales Tax - TC", "Sales Tax 8%", 80.0)])

		tax_data = MagicMock()
		tax_data.amount_to_collect = 85.0
		tax_data.breakdown.line_items = []
		tax_data.jurisdictions = MagicMock(state="CA", county="", city="")

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_region", return_value="United States"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=MagicMock(tax_account_head="Sales Tax - TC", shipping_account_head="Freight - TC")), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_sales_tax_exemption", return_value=(False, None)), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"dummy": True}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_for_nexus", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.validate_tax_request", return_value=tax_data), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value("2026-01-01 00:00:00")), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.cache", return_value=_no_cache()):
			set_sales_tax(doc, None)

		tax_rows = [t for t in doc.taxes if t.account_head == "Sales Tax - TC"]
		self.assertEqual(len(tax_rows), 1)
		self.assertEqual(tax_rows[0].description, TAXJAR_ROW_DESCRIPTION)
		self.assertEqual(tax_rows[0].tax_amount, 85.0)

	def test_recalculation_replaces_not_duplicates_taxjar_row(self):
		"""On a second save, the existing TaxJar row is replaced, not added to."""
		doc = _make_doc(taxes=[_make_tax_row("Sales Tax - TC", TAXJAR_ROW_DESCRIPTION, 82.0)])

		tax_data = MagicMock()
		tax_data.amount_to_collect = 90.0
		tax_data.breakdown.line_items = []
		tax_data.jurisdictions = MagicMock(state="CA", county="", city="")

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_region", return_value="United States"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=MagicMock(tax_account_head="Sales Tax - TC", shipping_account_head="Freight - TC")), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_sales_tax_exemption", return_value=(False, None)), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"dummy": True}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_for_nexus", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.validate_tax_request", return_value=tax_data), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value("2026-01-01 00:00:00")), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.cache", return_value=_no_cache()):
			set_sales_tax(doc, None)

		tax_rows = [t for t in doc.taxes if t.account_head == "Sales Tax - TC"]
		self.assertEqual(len(tax_rows), 1)
		self.assertEqual(tax_rows[0].tax_amount, 90.0)

	def test_customer_taxable_status_true_when_not_exempt(self):
		"""No taxjar_exemption_type set on the customer - status stays "Taxable",
		matching the pre-existing default behaviour."""
		doc = _make_doc(taxes=[])

		tax_data = MagicMock()
		tax_data.amount_to_collect = 85.0
		tax_data.breakdown.line_items = []
		tax_data.jurisdictions = MagicMock(state="CA", county="", city="")

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_region", return_value="United States"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=MagicMock(tax_account_head="Sales Tax - TC", shipping_account_head="Freight - TC")), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_sales_tax_exemption", return_value=(False, None)), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"dummy": True}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_for_nexus", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.validate_tax_request", return_value=tax_data), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._get_customer_exemption_type", return_value=None), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value("2026-01-01 00:00:00")), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.cache", return_value=_no_cache()):
			set_sales_tax(doc, None)

		self.assertEqual(doc.taxjar_customer_taxable, 1)
		self.assertEqual(doc.taxjar_customer_taxable_reason, "Taxable")

	def test_customer_taxable_status_reflects_exemption_type_even_when_tax_is_computed(self):
		"""Regression guard: a customer with a TaxJar exemption_type set
		(Wholesale/Government/Other) but without the blunt exempt_from_sales_tax
		checkbox still reaches the TaxJar API call - region-scoped exemption is
		TaxJar's own job via customer_id, not replicated here. Previously the
		status matrix hardcoded "Is the customer taxable? Yes" regardless of
		this, even when the customer's own master data said otherwise. The tax
		amount itself is untouched (still whatever TaxJar computed) - only the
		status label is corrected."""
		doc = _make_doc(taxes=[])

		tax_data = MagicMock()
		tax_data.amount_to_collect = 0.0
		tax_data.breakdown.line_items = []
		tax_data.jurisdictions = MagicMock(state="CA", county="", city="")

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_region", return_value="United States"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=MagicMock(tax_account_head="Sales Tax - TC", shipping_account_head="Freight - TC")), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_sales_tax_exemption", return_value=(False, None)), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"dummy": True}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_for_nexus", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.validate_tax_request", return_value=tax_data), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._get_customer_exemption_type", return_value="Wholesale"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value("2026-01-01 00:00:00")), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.cache", return_value=_no_cache()):
			set_sales_tax(doc, None)

		self.assertEqual(doc.taxjar_customer_taxable, 0)
		self.assertIn("Wholesale", doc.taxjar_customer_taxable_reason)
		tax_rows = [t for t in doc.taxes if t.account_head == "Sales Tax - TC"]
		self.assertEqual(tax_rows[0].tax_amount, 0.0)

	def test_customer_taxable_status_shows_transaction_override_distinctly(self):
		"""A transaction-level override must not read as the customer being
		exempt: the card reports the master's own answer ("Taxable") and says
		the override applies on top, rather than flipping to "No" and hiding
		the customer's standing status."""
		doc = _make_doc(taxes=[])
		doc.taxjar_transaction_exempt = 1
		doc.taxjar_transaction_exemption_type = "Government"

		tax_data = MagicMock()
		tax_data.amount_to_collect = 0.0
		tax_data.breakdown.line_items = []
		tax_data.jurisdictions = MagicMock(state="CA", county="", city="")

		captured = {}

		def capture(doc, **kwargs):
			captured.update(kwargs)

		mod = "taxjar_integration.taxjar_integration.taxjar_integration"
		with patch(f"{mod}.frappe.db.get_single_value", return_value=1), \
		     patch(f"{mod}.get_region", return_value="United States"), \
		     patch(f"{mod}.get_company_config", return_value=MagicMock(tax_account_head="Sales Tax - TC", shipping_account_head="Freight - TC")), \
		     patch(f"{mod}.check_sales_tax_exemption", return_value=(False, None)), \
		     patch(f"{mod}.get_tax_data", return_value={"dummy": True}), \
		     patch(f"{mod}.check_for_nexus", return_value=True), \
		     patch(f"{mod}.validate_tax_request", return_value=tax_data), \
		     patch(f"{mod}._get_customer_exemption_type", return_value=None), \
		     patch(f"{mod}._set_tax_status_fields", side_effect=capture), \
		     patch(f"{mod}.frappe.db.get_value", side_effect=_scalar_get_value("2026-01-01 00:00:00")), \
		     patch(f"{mod}.frappe.cache", return_value=_no_cache()):
			set_sales_tax(doc, None)

		# The master says taxable, and stays saying so.
		self.assertTrue(captured["customer_taxable"])
		self.assertEqual(captured["customer_reason"], "Taxable, but transaction is marked as exempt")

	def test_clears_tax_rows_when_outside_nexus(self):
		"""When the delivery state is not in nexus, sales tax rows must be removed."""
		doc = _make_doc(taxes=[_make_tax_row("Sales Tax - TC", "Sales Tax 8%", 80.0)])
		company_config = MagicMock(tax_account_head="Sales Tax - TC", shipping_account_head="Freight - TC")

		# Don't mock check_for_nexus itself — let it run so it calls _remove_taxjar_rows.
		# Mock the DB lookup inside check_for_nexus to return None (outside nexus).
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_region", return_value="United States"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=company_config), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_sales_tax_exemption", return_value=(False, None)), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"to_state": "TX", "dummy": True}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value(None)):
			set_sales_tax(doc, None)

		self.assertEqual(len([t for t in doc.taxes if t.account_head == "Sales Tax - TC"]), 0)

	def test_skips_when_calculate_tax_disabled(self):
		doc = _make_doc(taxes=[_make_tax_row("Sales Tax - TC", "Some Tax", 80.0)])
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=0):
			set_sales_tax(doc, None)
		self.assertEqual(len(doc.taxes), 1)  # unchanged

	def test_skips_when_no_company_config(self):
		doc = _make_doc()
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_region", return_value="United States"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=None):
			set_sales_tax(doc, None)
		self.assertEqual(len(doc.taxes), 0)


class TestSetSalesTaxCache(UnitTestCase):
	"""set_sales_tax caches a successful TaxJar response for 5 minutes, keyed on
	the request payload plus TaxJar Settings' own `modified` timestamp.

	Regression coverage for a real incident: the key used to be derived from
	the payload alone, so rotating the API token in TaxJar Settings (or
	toggling Sandbox/Live, or editing the company config) did not bust the
	cache. An identical cart/address kept silently replaying the pre-change
	success for up to five minutes, with no call to TaxJar and no failure
	surfaced anywhere - the token could be outright invalid and nothing would
	show it.
	"""

	def _run(self, cache, settings_modified, company="Test Co"):
		doc = _make_doc(taxes=[], company=company)
		tax_data = MagicMock(amount_to_collect=85.0)
		tax_data.breakdown.line_items = []
		tax_data.jurisdictions = MagicMock(state="CA", county="", city="")

		# The cache key reads TaxJar Settings.modified through get_single_value,
		# the same call the enabled flag uses - so the stub answers per field
		# rather than returning one constant, or the key stops varying and the
		# cache-busting this class exists to prove would look broken.
		def _single_value(doctype, fieldname, *args, **kwargs):
			return settings_modified if fieldname == "modified" else 1

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", side_effect=_single_value), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_region", return_value="United States"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=MagicMock(tax_account_head="Sales Tax - TC", shipping_account_head="Freight - TC")), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_sales_tax_exemption", return_value=(False, None)), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"dummy": True}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_for_nexus", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.validate_tax_request", return_value=tax_data) as mock_validate, \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value(settings_modified)), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.cache", return_value=cache):
			set_sales_tax(doc, None)

		return mock_validate

	def test_identical_payload_and_unchanged_settings_hits_the_cache(self):
		cache = _fake_cache()

		self._run(cache, "2026-08-25 10:00:00")
		second_call = self._run(cache, "2026-08-25 10:00:00")

		second_call.assert_not_called()

	def test_saving_taxjar_settings_busts_the_cache_even_with_an_identical_cart(self):
		"""The reported bug's exact scenario: the cart/address is unchanged
		(same hash), but Settings was saved in between - the second call must
		reach TaxJar again rather than replay the earlier success."""
		cache = _fake_cache()

		self._run(cache, "2026-08-25 10:00:00")
		second_call = self._run(cache, "2026-08-25 10:00:05")

		second_call.assert_called_once()

	def test_different_companies_do_not_share_the_cache(self):
		"""Two companies can hold different TaxJar credentials (see
		get_company_config). An identical cart/address for both must not let
		the second company's document reuse the first company's cached
		result - that would compute its tax through the wrong TaxJar account."""
		cache = _fake_cache()

		self._run(cache, "2026-08-25 10:00:00", company="Company A")
		second_call = self._run(cache, "2026-08-25 10:00:00", company="Company B")

		second_call.assert_called_once()


# ── Phase 2: get_line_item_dict — product_tax_code resolution ────────────────

class TestGetLineItemDict(UnitTestCase):

	def _make_item(self, item_code=None, product_tax_category=None, item_name=None, description=None,
			qty=2, rate=100.0, price_list_rate=None, rate_with_margin=None, net_amount=None):
		# net_amount defaults to rate * qty (i.e. "no discount happened") so
		# every test not focused on the discount formula gets a neutral
		# baseline rather than an implicit 100%-off line.
		if net_amount is None:
			net_amount = rate * qty
		item = MagicMock()
		item.get = lambda key, default=None: {
			"idx": 1,
			"qty": qty,
			"rate": rate,
			"item_code": item_code,
			"product_tax_category": product_tax_category,
			"item_name": item_name,
			"description": description,
			"price_list_rate": price_list_rate,
			"rate_with_margin": rate_with_margin,
			"net_amount": net_amount,
		}.get(key, default)
		return item

	def _call(self, item, item_master_category=None):
		from taxjar_integration.taxjar_integration.taxjar_integration import get_line_item_dict
		with patch(
			"taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value",
			side_effect=_scalar_get_value(item_master_category),
		):
			return get_line_item_dict(item, docstatus=0)

	# Happy path: field is populated on the line item (Sales Invoice Item via fetch_from)

	def test_uses_line_item_product_tax_category_when_set(self):
		item = self._make_item(item_code="ITEM-001", product_tax_category="20010")
		result = self._call(item)
		self.assertEqual(result["product_tax_code"], "20010")

	# Fallback: field is empty on line item (Quotation/SO Item, or fetch_from never fired)

	def test_falls_back_to_item_master_when_line_item_field_empty(self):
		item = self._make_item(item_code="ITEM-001", product_tax_category=None)
		result = self._call(item, item_master_category="31000")
		self.assertEqual(result["product_tax_code"], "31000")

	def test_falls_back_to_item_master_when_line_item_field_blank_string(self):
		item = self._make_item(item_code="ITEM-001", product_tax_category="")
		result = self._call(item, item_master_category="20010")
		self.assertEqual(result["product_tax_code"], "20010")

	def test_line_item_field_takes_priority_over_item_master(self):
		"""If line item already has the category, the Item master must not be queried."""
		item = self._make_item(item_code="ITEM-001", product_tax_category="20010")
		with patch(
			"taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value",
		) as mock_db:
			from taxjar_integration.taxjar_integration.taxjar_integration import get_line_item_dict
			get_line_item_dict(item, docstatus=0)
		mock_db.assert_not_called()

	def test_returns_none_when_no_item_code_and_no_line_item_field(self):
		"""No item_code means no fallback lookup — product_tax_code should be None."""
		item = self._make_item(item_code=None, product_tax_category=None)
		result = self._call(item)
		self.assertIsNone(result["product_tax_code"])

	def test_returns_none_when_item_master_has_no_category(self):
		item = self._make_item(item_code="ITEM-001", product_tax_category=None)
		result = self._call(item, item_master_category=None)
		self.assertIsNone(result["product_tax_code"])

	# product_identifier / description — TaxJar's create-order line_items shape
	# (https://developers.taxjar.com/api/reference/#post-create-an-order-transaction)

	def test_product_identifier_is_the_item_code(self):
		"""item_code is the row's reference to the Item master, and by this
		app's autoname convention (field:item_code) already equals that Item
		doc's own name - no separate lookup needed to satisfy "the name of
		the Item"."""
		item = self._make_item(item_code="ITEM-001")
		result = self._call(item)
		self.assertEqual(result["product_identifier"], "ITEM-001")

	def test_description_is_bracketed_code_plus_name_plus_row_description(self):
		item = self._make_item(item_code="ITEM-001", item_name="Fuzzy Widget", description="Extra soft edition")
		result = self._call(item)
		self.assertEqual(result["description"], "[ITEM-001] Fuzzy Widget - Extra soft edition")

	def test_description_falls_back_to_bracketed_code_and_name_alone(self):
		"""Quotation/Sales Order rows commonly carry item_name with no free-text
		description filled in - the combined description must not end up with
		a dangling separator in that case."""
		item = self._make_item(item_code="ITEM-001", item_name="Fuzzy Widget", description=None)
		result = self._call(item)
		self.assertEqual(result["description"], "[ITEM-001] Fuzzy Widget")

	def test_description_omits_brackets_when_no_item_code(self):
		"""A row with no item_code (a free-text/service line) has nothing to
		bracket - the format falls back to plain item_name, not "[] name"."""
		item = self._make_item(item_code=None, item_name="Fuzzy Widget", description="Extra soft edition")
		result = self._call(item)
		self.assertEqual(result["description"], "Fuzzy Widget - Extra soft edition")

	def test_description_falls_back_to_row_description_alone(self):
		item = self._make_item(item_code=None, item_name=None, description="Extra soft edition")
		result = self._call(item)
		self.assertEqual(result["description"], "Extra soft edition")

	def test_description_is_blank_when_nothing_is_set(self):
		item = self._make_item(item_code=None, item_name=None, description=None)
		result = self._call(item)
		self.assertEqual(result["description"], "")

	# discount formula (design doc §3.2) — sourced from net_amount, not
	# price_list_rate vs rate, so it survives Margin and picks up both
	# item-level and document-level Additional Discount for free.

	def test_item_level_discount_only(self):
		"""No document-level discount: net_amount is just this line's own
		post-item-discount amount (rate * qty, no distribution applied)."""
		item = self._make_item(qty=1, rate=800.0, price_list_rate=1000.0, net_amount=800.0)
		result = self._call(item)
		self.assertEqual(result["unit_price"], 1000.0)
		self.assertEqual(result["discount"], 200.0)

	def test_document_level_discount_only_net_total_mode(self):
		"""No item-level discount (price_list_rate == rate); net_amount is
		reduced only by this line's share of Additional Discount, as
		apply_discount_amount() computes in "Net Total" mode."""
		item = self._make_item(qty=2, rate=500.0, price_list_rate=500.0, net_amount=900.0)
		result = self._call(item)
		self.assertEqual(result["unit_price"], 500.0)
		self.assertEqual(result["discount"], 100.0)

	def test_document_level_discount_only_grand_total_mode(self):
		"""Same shape as Net Total mode from get_line_item_dict's point of
		view - apply_discount_amount() distributes into net_amount
		identically in both non-cash modes."""
		item = self._make_item(qty=1, rate=300.0, price_list_rate=300.0, net_amount=270.0)
		result = self._call(item)
		self.assertEqual(result["unit_price"], 300.0)
		self.assertEqual(result["discount"], 30.0)

	def test_item_and_document_level_discount_combined(self):
		"""Live-verified against ACC-SINV-2026-00069 (design doc §3.2.1):
		Margin pushes list_rate to rate_with_margin (price_list_rate alone
		would understate it), an item-level discount and a distributed
		Additional Discount are both already folded into net_amount."""
		shoes = self._make_item(qty=1, rate=1800.0, price_list_rate=1000.0,
			rate_with_margin=2000.0, net_amount=1523.08)
		result = self._call(shoes)
		self.assertEqual(result["unit_price"], 2000.0)
		self.assertAlmostEqual(result["discount"], 476.92)

		sandwich = self._make_item(qty=1, rate=150.0, price_list_rate=120.0,
			rate_with_margin=200.0, net_amount=126.92)
		result = self._call(sandwich)
		self.assertEqual(result["unit_price"], 200.0)
		self.assertAlmostEqual(result["discount"], 73.08)

	def test_grand_total_cash_or_non_trade_discount_yields_zero_discount(self):
		"""ERPNext leaves net_amount untouched for this one mode (the
		discount is subtracted from grand_total after tax, not before) -
		so the formula must compute zero discount by construction, with
		no special-casing of the mode itself."""
		item = self._make_item(qty=2, rate=500.0, price_list_rate=500.0, net_amount=1000.0)
		result = self._call(item)
		self.assertEqual(result["unit_price"], 500.0)
		self.assertNotIn("discount", result)

	def test_no_price_list_configured_falls_back_to_rate(self):
		"""A row with rate typed directly and no Price List still picks up
		a document-level discount via net_amount, using rate as the base."""
		item = self._make_item(qty=1, rate=300.0, price_list_rate=None, net_amount=250.0)
		result = self._call(item)
		self.assertEqual(result["unit_price"], 300.0)
		self.assertEqual(result["discount"], 50.0)

	def test_rate_above_stale_price_list_rate_with_no_margin_uses_the_higher_rate(self):
		"""A line whose rate is typed above price_list_rate with no margin
		fields populated (e.g. a stale/lower Price List, or a document
		created via API that bypassed ERPNext's client-side margin auto-set)
		must still send the actual higher amount charged, not silently
		understate it by falling back to the lower list price."""
		item = self._make_item(qty=1, rate=150.0, price_list_rate=100.0, net_amount=150.0)
		result = self._call(item)
		self.assertEqual(result["unit_price"], 150.0)
		self.assertNotIn("discount", result)

	def test_discount_never_goes_negative_on_rounding_noise(self):
		"""net_amount fractionally exceeding list_amount (rounding noise
		from ERPNext's own distributed_discount_amount math) must clamp to
		zero, not surface a negative discount."""
		item = self._make_item(qty=1, rate=100.0, price_list_rate=100.0, net_amount=100.005)
		result = self._call(item)
		self.assertEqual(result["unit_price"], 100.0)
		self.assertNotIn("discount", result)


# ── Phase 2: sync_transaction_to_taxjar row detection ────────────────────────

class TestSyncTransactionRowDetection(UnitTestCase):

	def test_taxjar_row_description_constant_value(self):
		self.assertEqual(TAXJAR_ROW_DESCRIPTION, "Sales Tax")

	def test_sets_failed_when_no_tax_data(self):
		"""When get_tax_data returns None, sync should mark as Failed."""
		doc = _make_doc(taxes=[_make_tax_row("Sales Tax - TC", "Template Tax", 80.0)])
		doc.docstatus = 1
		mock_client = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value=None), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_sync_status") as mock_status, \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			sync_transaction_to_taxjar("SINV-TEST-001")

		args, kwargs = mock_status.call_args
		self.assertEqual(args, ("SINV-TEST-001", "Failed"))
		self.assertIn("No TaxJar payload", kwargs["error"])
		self.assertTrue(kwargs["retryable"], "resolves itself once the company is configured")
		mock_client.create_order.assert_not_called()

	def test_uses_taxjar_row_amount_for_transaction(self):
		"""Sales tax amount is taken from the row matching company_config.tax_account_head -
		not by matching the row's (user-editable) description text."""
		doc = _make_doc(taxes=[_make_tax_row("Sales Tax - TC", TAXJAR_ROW_DESCRIPTION, 95.0)])
		doc.docstatus = 1
		mock_client = MagicMock()
		mock_client.create_order.return_value = MagicMock()
		mock_config = MagicMock(tax_account_head="Sales Tax - TC")

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=mock_config), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"shipping": 10.0}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_sync_status"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			sync_transaction_to_taxjar("SINV-TEST-001")

		mock_client.create_order.assert_called_once()
		self.assertEqual(mock_client.create_order.call_args[0][0]["sales_tax"], 95.0)

	def test_does_not_override_get_tax_datas_amount_with_doc_total(self):
		"""Regression guard: get_tax_data() already derives "amount" correctly
		from the actual line_items + shipping being sent. This function used
		to clobber it with doc.total + shipping, which excludes any
		document-level Additional Discount and double-counts shipping - a
		real, live-verified TaxJar "amount must be equal to the sum of line
		items and shipping" rejection, not a hypothetical."""
		doc = _make_doc(taxes=[_make_tax_row("Sales Tax - TC", TAXJAR_ROW_DESCRIPTION, 95.0)])
		doc.docstatus = 1
		doc.total = 1950.0  # pre-Additional-Discount total - must NOT end up in the payload
		mock_client = MagicMock()
		mock_client.create_order.return_value = MagicMock()
		mock_config = MagicMock(tax_account_head="Sales Tax - TC")

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=mock_config), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"shipping": 10.0, "amount": 1650.0}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_sync_status"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			sync_transaction_to_taxjar("SINV-TEST-001")

		self.assertEqual(mock_client.create_order.call_args[0][0]["amount"], 1650.0)

	def test_row_description_does_not_affect_sales_tax_match(self):
		"""A user retitling the row's description before submit must not
		change what gets reported to TaxJar - only account_head matters."""
		doc = _make_doc(taxes=[_make_tax_row("Sales Tax - TC", "Whatever the user renamed it to", 95.0)])
		doc.docstatus = 1
		mock_client = MagicMock()
		mock_client.create_order.return_value = MagicMock()
		mock_config = MagicMock(tax_account_head="Sales Tax - TC")

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=mock_config), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"shipping": 10.0}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_sync_status"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			sync_transaction_to_taxjar("SINV-TEST-001")

		self.assertEqual(mock_client.create_order.call_args[0][0]["sales_tax"], 95.0)

	def test_other_account_rows_excluded_even_with_matching_description(self):
		"""A non-TaxJar row that happens to share the description text must
		not be counted - account_head is the only thing that matters."""
		doc = _make_doc(taxes=[
			_make_tax_row("Sales Tax - TC", TAXJAR_ROW_DESCRIPTION, 95.0),
			_make_tax_row("Other Account - TC", TAXJAR_ROW_DESCRIPTION, 1000.0),
		])
		doc.docstatus = 1
		mock_client = MagicMock()
		mock_client.create_order.return_value = MagicMock()
		mock_config = MagicMock(tax_account_head="Sales Tax - TC")

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=mock_config), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"shipping": 10.0}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_sync_status"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			sync_transaction_to_taxjar("SINV-TEST-001")

		self.assertEqual(mock_client.create_order.call_args[0][0]["sales_tax"], 95.0)

	def test_no_company_config_yields_zero_sales_tax_not_a_crash(self):
		doc = _make_doc(taxes=[_make_tax_row("Sales Tax - TC", TAXJAR_ROW_DESCRIPTION, 95.0)])
		doc.docstatus = 1
		mock_client = MagicMock()
		mock_client.create_order.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=None), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"shipping": 10.0}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_sync_status"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			sync_transaction_to_taxjar("SINV-TEST-001")

		self.assertEqual(mock_client.create_order.call_args[0][0]["sales_tax"], 0)


# ── Phase 1: taxjar_state_code custom field on Address ───────────────────────

class TestItemProductTaxCategoryQuickEntry(UnitTestCase):
	"""product_tax_category should be pickable from Item's Quick Entry dialog
	without being made globally mandatory - Frappe's quick_entry.js includes a
	field when reqd OR allow_in_quick_entry is set (never both needed)."""

	def _get_item_field(self):
		captured = {}

		def _capture(custom_fields, update=True):
			captured.update(custom_fields)

		with patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.create_custom_fields",
			side_effect=_capture,
		):
			make_custom_fields()

		return next(f for f in captured["Item"] if f["fieldname"] == "product_tax_category")

	def test_allowed_in_quick_entry(self):
		field = self._get_item_field()
		self.assertEqual(field.get("allow_in_quick_entry"), 1)

	def test_not_made_globally_mandatory(self):
		"""allow_in_quick_entry, not reqd - ticking this shouldn't block saving
		an Item from the full form when left blank."""
		field = self._get_item_field()
		self.assertFalse(field.get("reqd"))


class TestAddressCustomField(UnitTestCase):

	def _get_address_field_def(self):
		"""Return the Address field definition dict from make_custom_fields()."""
		# Intercept create_custom_fields to capture the dict without hitting the DB
		captured = {}

		def _capture(custom_fields, update=True):
			captured.update(custom_fields)

		with patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.create_custom_fields",
			side_effect=_capture,
		):
			make_custom_fields()

		return captured.get("Address", [])

	def test_make_custom_fields_includes_address(self):
		fields = self._get_address_field_def()
		self.assertTrue(len(fields) > 0, "Expected at least one Address custom field")

	def test_address_custom_field_fieldname(self):
		fields = self._get_address_field_def()
		fieldnames = [f["fieldname"] for f in fields]
		self.assertIn("taxjar_state_code", fieldnames)

	def test_address_custom_field_type_is_select(self):
		fields = self._get_address_field_def()
		field = next(f for f in fields if f["fieldname"] == "taxjar_state_code")
		self.assertEqual(field["fieldtype"], "Select")

	def test_address_custom_field_inserted_after_state(self):
		fields = self._get_address_field_def()
		field = next(f for f in fields if f["fieldname"] == "taxjar_state_code")
		self.assertEqual(field["insert_after"], "state")

	def test_address_custom_field_depends_on_united_states(self):
		fields = self._get_address_field_def()
		field = next(f for f in fields if f["fieldname"] == "taxjar_state_code")
		self.assertIn("United States", field["depends_on"])

	def test_address_custom_field_options_cover_all_supported_codes(self):
		"""Every code in SUPPORTED_STATE_CODES must appear in the Select options."""
		options = set(_US_STATE_CODE_OPTIONS.split("\n"))
		for code in SUPPORTED_STATE_CODES:
			self.assertIn(code, options, f"State code {code!r} missing from taxjar_state_code options")


# ── Transaction-level exemption override (taxjar_transaction_exempt) ────────


class TestTransactionExemptionCustomFields(UnitTestCase):
	"""JSON-shape assertions on the taxjar_transaction_exempt/exemption_type
	custom fields - same intercept-create_custom_fields pattern as
	TestAddressCustomField, no DB writes."""

	def _get_custom_fields(self):
		captured = {}

		def _capture(custom_fields, update=True):
			captured.update(custom_fields)

		with patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.create_custom_fields",
			side_effect=_capture,
		):
			make_custom_fields()

		return captured

	def _field(self, fields, fieldname):
		return next(f for f in fields if f["fieldname"] == fieldname)

	def test_present_on_all_three_transaction_doctypes(self):
		captured = self._get_custom_fields()
		for doctype in ("Quotation", "Sales Order", "Sales Invoice"):
			fieldnames = [f["fieldname"] for f in captured[doctype]]
			self.assertIn("taxjar_transaction_exempt", fieldnames, doctype)
			self.assertIn("taxjar_transaction_exemption_type", fieldnames, doctype)

	def test_not_present_on_customer(self):
		"""Transaction-level override is per-document, not per-customer-master —
		Customer exemption stays on taxjar_exemption_type."""
		captured = self._get_custom_fields()
		fieldnames = [f["fieldname"] for f in captured["Customer"]]
		self.assertNotIn("taxjar_transaction_exempt", fieldnames)

	def test_fields_sit_under_their_own_section(self):
		"""Previously the checkbox went after Shipping Rule and its reason after
		Incoterm, which split a question from its answer across two columns of an
		unrelated section."""
		captured = self._get_custom_fields()
		for doctype in ("Quotation", "Sales Order", "Sales Invoice"):
			with self.subTest(doctype=doctype):
				section = self._field(captured[doctype], "taxjar_exemption_section")
				self.assertEqual(section["fieldtype"], "Section Break")
				self.assertEqual(section["label"], "TaxJar Exemptions")
				self.assertEqual(section["insert_after"], "net_total")

				checkbox = self._field(captured[doctype], "taxjar_transaction_exempt")
				self.assertEqual(checkbox["insert_after"], "taxjar_exemption_section")

				reason = self._field(captured[doctype], "taxjar_transaction_exemption_type")
				self.assertEqual(reason["insert_after"], "taxjar_transaction_exempt")

	def test_checkbox_is_a_check_field(self):
		captured = self._get_custom_fields()
		field = self._field(captured["Sales Invoice"], "taxjar_transaction_exempt")
		self.assertEqual(field["fieldtype"], "Check")
		self.assertEqual(field["label"], "Is transaction exempt from sales tax?")

	def test_exemption_type_select_options_and_visibility(self):
		captured = self._get_custom_fields()
		field = self._field(captured["Sales Invoice"], "taxjar_transaction_exemption_type")
		self.assertEqual(field["fieldtype"], "Select")
		self.assertEqual(field["label"], "Reason for exemption?")
		self.assertEqual(field["options"], "\nWholesale\nGovernment\nOther")
		self.assertNotIn("Non Exempt", field["options"])
		# Explicit == 1: an unset Check reads back as undefined on a new doc.
		condition = "eval: doc.taxjar_transaction_exempt == 1"
		self.assertEqual(field["depends_on"], condition)
		self.assertEqual(field["mandatory_depends_on"], condition)


class TestHideLegacyExemptFromSalesTax(UnitTestCase):

	def test_hides_on_all_four_doctypes_when_column_exists(self):
		from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
			hide_legacy_exempt_from_sales_tax,
		)
		with patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.frappe.db.has_column", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.make_property_setter") as mock_setter:
			hide_legacy_exempt_from_sales_tax()

		self.assertEqual(mock_setter.call_count, 4)
		doctypes = {c.args[0] for c in mock_setter.call_args_list}
		self.assertEqual(doctypes, {"Quotation", "Sales Order", "Sales Invoice", "Customer"})
		for call in mock_setter.call_args_list:
			self.assertEqual(call.args[1], "exempt_from_sales_tax")
			self.assertEqual(call.args[2], "hidden")
			self.assertEqual(call.args[3], "1")

	def test_hides_even_before_erpnext_creates_the_field(self):
		"""ERPNext only adds the checkbox once a Company is United States. If
		TaxJar is installed first there is nothing to hide yet, and skipping
		meant the field turned up unhidden the moment a US company was created.
		A Property Setter for a field that does not exist is inert until it
		does (frappe/model/meta.py:441-445), so it is written up front."""
		from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
			hide_legacy_exempt_from_sales_tax,
		)
		with patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.frappe.db.has_column", return_value=False), \
		     patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.make_property_setter") as mock_setter:
			hide_legacy_exempt_from_sales_tax()

		self.assertEqual(mock_setter.call_count, 4)
		self.assertIn("Sales Invoice", {c.args[0] for c in mock_setter.call_args_list})


class TestSetTaxesFieldDescription(UnitTestCase):

	def test_sets_description_on_all_three_transaction_doctypes(self):
		from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
			set_taxes_field_description,
			_TAXES_FIELD_DESCRIPTION,
		)
		with patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.make_property_setter") as mock_setter:
			set_taxes_field_description()

		self.assertEqual(mock_setter.call_count, 3)
		doctypes = {c.args[0] for c in mock_setter.call_args_list}
		self.assertEqual(doctypes, {"Quotation", "Sales Order", "Sales Invoice"})
		for call in mock_setter.call_args_list:
			self.assertEqual(call.args[1], "taxes")
			self.assertEqual(call.args[2], "description")
			self.assertEqual(call.args[3], _TAXES_FIELD_DESCRIPTION)
			self.assertEqual(call.args[4], "Table")

	def test_does_not_touch_customer(self):
		"""The "taxes" field lives on transaction doctypes only - Customer has
		no such field, so it must never be targeted here."""
		from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
			set_taxes_field_description,
		)
		with patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.make_property_setter") as mock_setter:
			set_taxes_field_description()

		doctypes = {c.args[0] for c in mock_setter.call_args_list}
		self.assertNotIn("Customer", doctypes)


# ── Phase 2: get_iso_3166_2_state_code ───────────────────────────────────────

class TestGetIso3166StateCode(UnitTestCase):
	"""Tests for get_iso_3166_2_state_code() — pycountry is exercised for fallback
	paths; the DB call for country_code is mocked to "US"."""

	def _call(self, state=None, taxjar_state_code=None, country="United States"):
		from taxjar_integration.taxjar_integration.taxjar_integration import get_iso_3166_2_state_code

		address = MagicMock()
		address.get = lambda key, default=None: {
			"state": state,
			"taxjar_state_code": taxjar_state_code,
			"country": country,
		}.get(key, default)

		with patch(
			"taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value",
			side_effect=_scalar_get_value("US"),
		):
			return get_iso_3166_2_state_code(address)

	# Fast path — taxjar_state_code is set

	def test_prefers_taxjar_state_code_when_set(self):
		"""When taxjar_state_code is a valid code, return it without pycountry."""
		result = self._call(taxjar_state_code="FL", state="Anything")
		self.assertEqual(result, "FL")

	def test_prefers_taxjar_state_code_over_state_field(self):
		"""taxjar_state_code wins even when state would also parse correctly."""
		result = self._call(taxjar_state_code="CA", state="Florida")
		self.assertEqual(result, "CA")

	def test_ignores_taxjar_state_code_if_not_in_supported_list(self):
		"""An unrecognised taxjar_state_code falls through to pycountry lookup."""
		result = self._call(taxjar_state_code="XX", state="California")
		self.assertEqual(result, "CA")

	def test_ignores_blank_taxjar_state_code(self):
		"""Empty string in taxjar_state_code falls through to pycountry."""
		result = self._call(taxjar_state_code="", state="New York")
		self.assertEqual(result, "NY")

	# Fallback — pycountry via state field

	def test_falls_back_to_state_short_code(self):
		"""state='CA' (≤3 chars, valid code) → 'CA'."""
		result = self._call(state="CA")
		self.assertEqual(result, "CA")

	def test_falls_back_to_state_full_name(self):
		"""state='New York' → 'NY' via pycountry name lookup."""
		result = self._call(state="New York")
		self.assertEqual(result, "NY")

	def test_falls_back_to_state_full_name_case_insensitive(self):
		"""state='florida' (lowercase) → 'FL'."""
		result = self._call(state="florida")
		self.assertEqual(result, "FL")

	# Error handling

	def test_none_state_throws_validation_error(self):
		"""state=None with no taxjar_state_code must throw ValidationError, not AttributeError."""
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._call(state=None, taxjar_state_code=None)

	def test_empty_state_throws_validation_error(self):
		"""state='' with no taxjar_state_code must throw ValidationError."""
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._call(state="", taxjar_state_code=None)

	def test_invalid_state_name_throws_validation_error(self):
		"""An unrecognisable state like 'Fla.' must throw ValidationError."""
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._call(state="Fla.", taxjar_state_code=None)

	def test_invalid_short_code_throws_validation_error(self):
		"""A 2-letter code that isn't a real state must throw ValidationError."""
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._call(state="ZZ", taxjar_state_code=None)


# ── Phase 3: validate_address — server-side hook ─────────────────────────────

class _MockAddress:
	"""Minimal stand-in for a Frappe Address document."""
	def __init__(self, country=None, state=None, taxjar_state_code=None, pincode=None):
		self.country = country
		self.state = state
		self.pincode = pincode
		self._taxjar_state_code = taxjar_state_code

	def get(self, key, default=None):
		if key == "taxjar_state_code":
			return self._taxjar_state_code
		return getattr(self, key, default)


class TestValidateAddress(UnitTestCase):

	def _call(self, doc, country_code):
		from taxjar_integration.taxjar_integration.taxjar_integration import validate_address
		with patch(
			"taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value",
			side_effect=_scalar_get_value(country_code),
		), patch(
			"taxjar_integration.taxjar_integration.taxjar_integration._is_taxjar_enabled",
			return_value=False,
		):
			validate_address(doc, None)

	# No country — early return, nothing should raise

	def test_no_country_skips_validation(self):
		from taxjar_integration.taxjar_integration.taxjar_integration import validate_address
		doc = _MockAddress(country=None)
		validate_address(doc, None)  # no mock needed — returns before DB call

	def test_empty_country_skips_validation(self):
		from taxjar_integration.taxjar_integration.taxjar_integration import validate_address
		doc = _MockAddress(country="")
		validate_address(doc, None)

	# United States — all three fields mandatory

	def test_us_missing_state_throws(self):
		doc = _MockAddress(country="United States", state=None, taxjar_state_code="CA", pincode="90210")
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._call(doc, "US")

	def test_us_empty_state_throws(self):
		doc = _MockAddress(country="United States", state="", taxjar_state_code="CA", pincode="90210")
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._call(doc, "US")

	def test_us_missing_taxjar_state_code_throws(self):
		doc = _MockAddress(country="United States", state="California", taxjar_state_code=None, pincode="90210")
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._call(doc, "US")

	def test_us_empty_taxjar_state_code_throws(self):
		doc = _MockAddress(country="United States", state="California", taxjar_state_code="", pincode="90210")
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._call(doc, "US")

	def test_us_missing_pincode_throws(self):
		doc = _MockAddress(country="United States", state="California", taxjar_state_code="CA", pincode=None)
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._call(doc, "US")

	def test_us_empty_pincode_throws(self):
		doc = _MockAddress(country="United States", state="California", taxjar_state_code="CA", pincode="")
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._call(doc, "US")

	def test_us_all_fields_present_passes(self):
		doc = _MockAddress(country="United States", state="California", taxjar_state_code="CA", pincode="90210")
		self._call(doc, "US")  # must not raise

	def test_us_country_code_case_insensitive(self):
		"""DB may return lowercase 'us' — must still apply validation."""
		doc = _MockAddress(country="United States", state=None, taxjar_state_code="CA", pincode="90210")
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._call(doc, "us")

	# Canada — only state is mandatory; taxjar_state_code and pincode are not

	def test_canada_missing_state_throws(self):
		doc = _MockAddress(country="Canada", state=None, taxjar_state_code=None, pincode="M5H 2N2")
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._call(doc, "CA")

	def test_canada_state_present_passes(self):
		doc = _MockAddress(country="Canada", state="Ontario", taxjar_state_code=None, pincode=None)
		self._call(doc, "CA")  # must not raise

	def test_canada_missing_taxjar_state_code_does_not_throw(self):
		"""taxjar_state_code is US-only — missing value is fine for Canada."""
		doc = _MockAddress(country="Canada", state="Ontario", taxjar_state_code=None, pincode="M5H 2N2")
		self._call(doc, "CA")  # must not raise

	def test_canada_missing_pincode_does_not_throw(self):
		"""Pincode is mandatory for US only."""
		doc = _MockAddress(country="Canada", state="Ontario", taxjar_state_code=None, pincode=None)
		self._call(doc, "CA")  # must not raise

	def test_canada_country_code_case_insensitive(self):
		"""DB may return lowercase 'ca' — must still enforce state."""
		doc = _MockAddress(country="Canada", state=None)
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._call(doc, "ca")

	# Other countries — no mandatory rules apply

	def test_other_country_no_fields_required(self):
		doc = _MockAddress(country="Germany", state=None, taxjar_state_code=None, pincode=None)
		self._call(doc, "DE")  # must not raise

	def test_uk_no_fields_required(self):
		doc = _MockAddress(country="United Kingdom", state=None, taxjar_state_code=None, pincode=None)
		self._call(doc, "GB")  # must not raise


# ── Phase 3: Address desk client script ──────────────────────────────────────

class TestAddressClientScript(UnitTestCase):
	"""Structural tests: hooks registration and JS file content."""

	def _app_root(self):
		import os
		return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

	def _read_js(self):
		import os
		path = os.path.join(self._app_root(), "public", "js", "address.js")
		with open(path) as f:
			return f.read()

	def test_hooks_registers_address_js(self):
		"""hooks.py must declare Address in doctype_js."""
		from taxjar_integration import hooks
		self.assertIn("Address", hooks.doctype_js)
		self.assertEqual(hooks.doctype_js["Address"], "public/js/address.js")

	def test_address_js_file_exists(self):
		import os
		path = os.path.join(self._app_root(), "public", "js", "address.js")
		self.assertTrue(os.path.isfile(path), "public/js/address.js does not exist")

	def test_address_js_has_state_handler(self):
		js = self._read_js()
		self.assertIn("state(frm)", js, "Missing 'state' event handler in address.js")

	def test_address_js_has_taxjar_state_code_handler(self):
		js = self._read_js()
		self.assertIn("taxjar_state_code(frm)", js, "Missing 'taxjar_state_code' event handler")

	def test_address_js_has_country_handler(self):
		js = self._read_js()
		self.assertIn("country(frm)", js, "Missing 'country' event handler in address.js")

	def test_address_js_guards_against_missing_field(self):
		"""All handlers must check _has_state_code_field before calling frm.set_value."""
		js = self._read_js()
		self.assertIn("_has_state_code_field", js, "Missing field-existence guard in address.js")

	def test_address_js_has_all_supported_state_codes(self):
		"""Every code in SUPPORTED_STATE_CODES must appear in the shared state map.

		The map lives in taxjar_utils.js (loaded globally via the app bundle) and is
		referenced by address.js as taxjar_integration.US_STATE_NAMES.
		"""
		import os
		path = os.path.join(self._app_root(), "public", "js", "taxjar_utils.js")
		with open(path) as f:
			js = f.read()
		# address.js must reference the shared map rather than hardcode its own copy.
		self.assertIn("taxjar_integration.US_STATE_NAMES", self._read_js())
		for code in SUPPORTED_STATE_CODES:
			self.assertIn(code, js, f"State code {code!r} missing from taxjar_utils.js")

	def test_address_js_makes_pincode_mandatory_for_us(self):
		"""pincode must be set as required when country is United States."""
		js = self._read_js()
		self.assertIn("_set_taxjar_mandatory_fields", js)
		self.assertIn('"pincode"', js)
		self.assertIn("reqd", js)

	def test_address_js_mandatory_applied_on_refresh_and_country_change(self):
		"""_set_taxjar_mandatory_fields must be called from both refresh and country handlers."""
		js = self._read_js()
		refresh_idx = js.index("refresh(frm)")
		country_idx = js.index("country(frm)")
		self.assertGreater(js.index("_set_taxjar_mandatory_fields", refresh_idx), refresh_idx)
		self.assertGreater(js.index("_set_taxjar_mandatory_fields", country_idx), country_idx)

	def test_address_js_makes_state_mandatory_for_us_and_ca(self):
		"""state must become required for both United States and Canada."""
		js = self._read_js()
		self.assertIn('"state"', js)
		self.assertIn("Canada", js)

	def test_address_js_makes_taxjar_state_code_mandatory_for_us(self):
		"""taxjar_state_code reqd must be toggled (US only, field is hidden for CA)."""
		js = self._read_js()
		self.assertIn('"taxjar_state_code"', js)
		# reqd is toggled based on is_us, not needs_state
		self.assertIn("is_us", js)

	def test_hooks_registers_address_validate(self):
		"""hooks.py must declare an Address validate doc event."""
		from taxjar_integration import hooks
		self.assertIn("Address", hooks.doc_events)
		self.assertIn("validate", hooks.doc_events["Address"])


# ── Nexus HTML renderer — JS content ─────────────────────────────────────────

class TestNexusHtmlRenderer(UnitTestCase):
	"""Structural tests for the nexus grouped-HTML renderer in taxjar_settings.js."""

	def _read_js(self):
		import os
		path = os.path.join(os.path.dirname(__file__), "taxjar_settings.js")
		with open(path) as f:
			return f.read()

	def test_settings_js_has_render_nexus_html_function(self):
		js = self._read_js()
		self.assertIn("_render_nexus_html", js)

	def test_settings_js_render_called_on_refresh(self):
		js = self._read_js()
		refresh_idx = js.index("refresh(frm)")
		self.assertGreater(js.index("_render_nexus_html", refresh_idx), refresh_idx)

	def test_settings_js_render_called_after_update_nexus(self):
		js = self._read_js()
		btn_idx = js.index("update_nexus_list_btn")
		self.assertGreater(js.index("_render_nexus_html", btn_idx), btn_idx)

	def test_last_synced_renders_beside_the_button_not_the_hidden_field(self):
		"""nexus_last_synced is hidden (see TestTaxJarSettingsJsonNexusTab) - the
		date has to come from somewhere still visible, so it is appended next to
		Update Nexus List itself rather than left to the field's own display.
		"""
		js = self._read_js()
		self.assertIn("function _render_nexus_last_synced(frm) {", js)
		fn = js.split("function _render_nexus_last_synced(frm) {")[1].split("\n}\n")[0]
		self.assertIn("frm.fields_dict.update_nexus_list_btn", fn)
		self.assertIn("_format_last_synced(frm.doc.nexus_last_synced)", fn)
		# Re-rendered, not appended blind - a second click must replace the
		# text rather than stack a duplicate span next to the first.
		self.assertIn("find('.taxjar-nexus-last-synced').remove();", fn)

	def test_last_synced_is_pushed_to_the_far_right(self):
		"""A lone full-width field gets frappe's own .input-max-width
		(desk/form.scss), capping the row at 50% of the section - fine for a
		button alone, but it left "Last updated" sitting right after the
		button instead of at the row's far edge, reported as "not extreme
		right". Two things had to change together: the cap removed so the row
		can use the full section width, and justify-content: space-between so
		the caption actually travels to that freed-up edge - either alone
		still leaves it sitting next to the button.
		"""
		js = self._read_js()
		fn = js.split("function _render_nexus_last_synced(frm) {")[1].split("\n}\n")[0]
		self.assertIn("field.$wrapper.removeClass('input-max-width');", fn)
		self.assertIn("'justify-content': 'space-between',", fn)

	def test_last_synced_wired_into_refresh_and_the_update_button(self):
		js = self._read_js()
		refresh_idx = js.index("refresh(frm)")
		self.assertGreater(js.index("_render_nexus_last_synced(frm)", refresh_idx), refresh_idx)
		btn_idx = js.index("update_nexus_list_btn(frm)")
		self.assertGreater(js.index("_render_nexus_last_synced(frm)", btn_idx), btn_idx)

	def test_last_synced_reuses_the_product_tax_category_formatter(self):
		"""Both Nexus and Product Tax Category answer "when did this list last
		come from TaxJar" - one shared helper rather than two copies of the
		str_to_user/Never fallback, which is what this used to be.
		"""
		js = self._read_js()
		self.assertEqual(js.count("function _format_last_synced(value) {"), 1)
		self.assertIn("const last_updated = _format_last_synced(summary.last_updated);", js)
		self.assertIn("_format_last_synced(frm.doc.nexus_last_synced)", js)

	def test_settings_js_groups_by_company(self):
		"""Renderer must group nexus rows by company."""
		js = self._read_js()
		self.assertIn("by_company", js)

	def test_settings_js_renders_region_and_code_columns(self):
		js = self._read_js()
		self.assertIn("region_code", js)
		self.assertIn("country_code", js)

	def test_settings_js_has_empty_state_message(self):
		"""When nexus is empty, a helpful message must be shown."""
		js = self._read_js()
		self.assertIn("No nexus regions loaded", js)

	def test_settings_js_overflow_x_auto_for_responsiveness(self):
		"""Table wrapper must use overflow-x: auto for narrow-screen support."""
		js = self._read_js()
		self.assertIn("overflow-x: auto", js)


# ── Phase 1: sync_nexus_list scheduled task ──────────────────────────────────

class TestSyncNexusList(UnitTestCase):
	"""Tests for the daily scheduled task that refreshes nexus from TaxJar."""

	def _make_settings_doc(self, calculate_tax=1, create_transactions=0, has_company_config=True):
		doc = MagicMock()
		doc.taxjar_enabled = 1
		if has_company_config:
			row = MagicMock()
			row.taxjar_calculate_tax = calculate_tax
			row.taxjar_create_transactions = create_transactions
			doc.company_config = [row]
		else:
			doc.company_config = []
		return doc

	def _call(self, doc):
		from taxjar_integration.taxjar_integration.tasks import sync_nexus_list
		with patch("taxjar_integration.taxjar_integration.tasks.frappe.get_doc", return_value=doc):
			sync_nexus_list()

	# Guard: features disabled

	def test_skips_when_both_features_disabled(self):
		"""No API call when neither calculate_tax nor create_transactions is on."""
		doc = self._make_settings_doc(calculate_tax=0, create_transactions=0)
		self._call(doc)
		doc.update_nexus_list.assert_not_called()

	def test_runs_when_only_calculate_tax_enabled(self):
		doc = self._make_settings_doc(calculate_tax=1, create_transactions=0)
		self._call(doc)
		doc.update_nexus_list.assert_called_once()

	def test_runs_when_only_create_transactions_enabled(self):
		doc = self._make_settings_doc(calculate_tax=0, create_transactions=1)
		self._call(doc)
		doc.update_nexus_list.assert_called_once()

	def test_runs_when_both_features_enabled(self):
		doc = self._make_settings_doc(calculate_tax=1, create_transactions=1)
		self._call(doc)
		doc.update_nexus_list.assert_called_once()

	# Guard: no company config

	def test_skips_when_no_company_config(self):
		"""No API call when company_config table is empty."""
		doc = self._make_settings_doc(calculate_tax=1, has_company_config=False)
		self._call(doc)
		doc.update_nexus_list.assert_not_called()

	# Error handling

	def test_catches_exception_and_logs_error(self):
		"""Exceptions from update_nexus_list must be caught and logged, not re-raised."""
		doc = self._make_settings_doc(calculate_tax=1)
		doc.update_nexus_list.side_effect = Exception("TaxJar API timeout")

		from taxjar_integration.taxjar_integration.tasks import sync_nexus_list
		with patch("taxjar_integration.taxjar_integration.tasks.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.get_traceback", return_value="traceback"), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.log_error") as mock_log:
			sync_nexus_list()  # must not raise

		mock_log.assert_called_once_with("traceback", "TaxJar: Nexus sync failed")

	def test_does_not_reraise_exception(self):
		"""Scheduler must not crash if TaxJar is unreachable."""
		doc = self._make_settings_doc(calculate_tax=1)
		doc.update_nexus_list.side_effect = Exception("Network error")

		from taxjar_integration.taxjar_integration.tasks import sync_nexus_list
		with patch("taxjar_integration.taxjar_integration.tasks.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.get_traceback", return_value="tb"), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.log_error"):
			try:
				sync_nexus_list()
			except Exception:
				self.fail("sync_nexus_list() raised an exception — scheduler would crash")

	# Hooks registration

	def test_hooks_registers_sync_nexus_list_as_daily_job(self):
		"""hooks.py must declare sync_nexus_list in scheduler_events['daily']."""
		from taxjar_integration import hooks
		self.assertIn(
			"taxjar_integration.taxjar_integration.tasks.sync_nexus_list",
			hooks.scheduler_events.get("daily", []),
		)


# ── Weekly Product Tax Category sync task ────────────────────────────────────

class TestSyncProductTaxCategories(UnitTestCase):
	"""Tests for the weekly scheduled task that refreshes Product Tax Category from
	TaxJar. Mirrors sync_nexus_list's guard/error-handling pattern; reuses the
	shared fetch_and_insert_categories() helper (also used by the manual "Update
	Product Tax Category List" button) rather than new insert logic."""

	def _category(self, product_tax_code, description, name):
		category = MagicMock()
		category.product_tax_code = product_tax_code
		category.description = description
		category.name = name
		return category

	def test_skips_when_taxjar_disabled(self):
		"""No client is even requested when the master switch/company gate is off."""
		from taxjar_integration.taxjar_integration.tasks import sync_product_tax_categories
		with patch("taxjar_integration.taxjar_integration.tasks._is_taxjar_enabled", return_value=False), \
		     patch("taxjar_integration.taxjar_integration.tasks.get_client") as mock_get_client:
			sync_product_tax_categories()
		mock_get_client.assert_not_called()

	def test_skips_when_no_client(self):
		"""No usable credential (get_client returns None) -> no TaxJar call, no insert attempt."""
		from taxjar_integration.taxjar_integration.tasks import sync_product_tax_categories
		with patch("taxjar_integration.taxjar_integration.tasks._is_taxjar_enabled", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.tasks.get_client", return_value=None), \
		     patch("taxjar_integration.taxjar_integration.tasks.fetch_and_insert_categories") as mock_fetch:
			sync_product_tax_categories()
		mock_fetch.assert_not_called()

	def test_maps_taxjar_categories_and_inserts_new_ones(self):
		"""New categories from the API get inserted; the TaxJarCategory attribute shape
		(.product_tax_code/.description/.name) is mapped to the dict shape
		create_tax_categories() expects (product_tax_code/description/name)."""
		frappe.db.delete("Product Tax Category", {"product_tax_code": "TEST_SYNC_NEW"})
		self.addCleanup(frappe.db.delete, "Product Tax Category", {"product_tax_code": "TEST_SYNC_NEW"})

		mock_client = MagicMock()
		mock_client.categories.return_value = [
			self._category("TEST_SYNC_NEW", "A brand new test category", "New Test Category"),
		]
		from taxjar_integration.taxjar_integration.tasks import sync_product_tax_categories
		with patch("taxjar_integration.taxjar_integration.tasks._is_taxjar_enabled", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.tasks.get_client", return_value=mock_client):
			sync_product_tax_categories()

		inserted = frappe.get_doc("Product Tax Category", "TEST_SYNC_NEW")
		self.assertEqual(inserted.description, "A brand new test category")
		self.assertEqual(inserted.category_name, "New Test Category")

	def test_existing_category_is_left_untouched(self):
		"""A category TaxJar still reports that already exists locally must not be
		updated or duplicated - Items are already Linked to it by product_tax_code."""
		existing = frappe.get_doc({
			"doctype": "Product Tax Category",
			"product_tax_code": "TEST_SYNC_EXISTING",
			"category_name": "Original Name",
			"description": "Original description",
		}).insert(ignore_permissions=True)
		self.addCleanup(frappe.db.delete, "Product Tax Category", {"product_tax_code": "TEST_SYNC_EXISTING"})

		mock_client = MagicMock()
		mock_client.categories.return_value = [
			self._category("TEST_SYNC_EXISTING", "A changed description", "Changed Name"),
		]
		from taxjar_integration.taxjar_integration.tasks import sync_product_tax_categories
		with patch("taxjar_integration.taxjar_integration.tasks._is_taxjar_enabled", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.tasks.get_client", return_value=mock_client):
			sync_product_tax_categories()

		unchanged = frappe.get_doc("Product Tax Category", existing.name)
		self.assertEqual(unchanged.category_name, "Original Name")
		self.assertEqual(unchanged.description, "Original description")

	def test_catches_exception_and_logs_error(self):
		"""Exceptions from the TaxJar call must be caught and logged, not re-raised -
		matching sync_nexus_list's error handling exactly."""
		mock_client = MagicMock()
		mock_client.categories.side_effect = Exception("TaxJar API timeout")

		from taxjar_integration.taxjar_integration.tasks import sync_product_tax_categories
		with patch("taxjar_integration.taxjar_integration.tasks._is_taxjar_enabled", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.tasks.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.get_traceback", return_value="traceback"), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.log_error") as mock_log:
			sync_product_tax_categories()  # must not raise

		mock_log.assert_called_once_with("traceback", "TaxJar: Product tax category sync failed")

	def test_hooks_registers_sync_product_tax_categories_as_weekly_job(self):
		"""hooks.py must declare sync_product_tax_categories in scheduler_events['weekly']."""
		from taxjar_integration import hooks
		self.assertIn(
			"taxjar_integration.taxjar_integration.tasks.sync_product_tax_categories",
			hooks.scheduler_events.get("weekly", []),
		)


# ── update_nexus_list(): a 401 from any one company must not crash the whole
# fetch with a raw traceback (bug report: this is exactly what happened when
# an untested/bad-token company reached the Nexus step) ─────────────────────

class TestUpdateNexusListAuthError(UnitTestCase):
	def setUp(self):
		self.settings = frappe.get_single("TaxJar Settings")
		self.settings.set("company_config", [{
			"company": "_Test Company",
			"tax_account_head": "Sales Tax - _TC",
			"shipping_account_head": "Freight - _TC",
		}])

	def _taxjar_error(self, status_code, message="error"):
		import taxjar.exceptions
		error = taxjar.exceptions.TaxJarResponseError(message)
		error.full_response = {"status_code": status_code}
		return error

	def test_401_throws_clear_message_naming_the_company(self):
		"""Previously re-raised as a bare TaxJarResponseError - a 500 to the
		browser with a raw traceback, for every company in the request, the
		moment any one of them had a bad token."""
		mock_client = MagicMock()
		mock_client.nexus_regions.side_effect = self._taxjar_error(401, "401 Unauthorized")
		with patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.get_client",
			return_value=mock_client,
		), patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.log_taxjar_call"
		):
			with self.assertRaises(frappe.exceptions.ValidationError) as cm:
				self.settings.update_nexus_list()

		message = str(cm.exception)
		self.assertIn("_Test Company", message)
		self.assertIn("401", message)
		# Both remedies the user actually has, named explicitly - matching
		# the bug report's own wording ("put correct API Token or remove the
		# company").
		self.assertIn("API Token", message)
		self.assertIn("remove", message)

	def test_non_auth_taxjar_error_still_propagates_unchanged(self):
		"""Only a 401 gets the special message - any other TaxJar error (500,
		rate limit, ...) is not silently swallowed or reworded."""
		import taxjar.exceptions
		mock_client = MagicMock()
		mock_client.nexus_regions.side_effect = self._taxjar_error(500, "500 Internal Server Error")
		with patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.get_client",
			return_value=mock_client,
		), patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.log_taxjar_call"
		):
			with self.assertRaises(taxjar.exceptions.TaxJarResponseError):
				self.settings.update_nexus_list()

	def test_successful_fetch_is_unaffected(self):
		"""The happy path (no error at all) must still work exactly as before.
		self.save() is stubbed out - _Test Company/its accounts aren't real
		records in this site, and this test isn't about link validation."""
		mock_client = MagicMock()
		mock_client.nexus_regions.return_value = []
		with patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.get_client",
			return_value=mock_client,
		), patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.log_taxjar_call"
		), patch.object(self.settings, "save"):
			self.settings.update_nexus_list()  # must not raise
		mock_client.nexus_regions.assert_called_once()


# ── Phase 2: auto-enqueue nexus sync on first configuration ──────────────────

class TestAutoNexusEnqueue(UnitTestCase):
	"""
	Tests for the on_update auto-enqueue: nexus is fetched in the background
	the first time settings are saved with features + company config + empty nexus.
	"""

	def _settings(self, calculate_tax=1, create_transactions=0, has_company_config=True, has_nexus=False):
		"""Return a live TaxJar Settings single doc wired up for the test scenario."""
		doc = frappe.get_single("TaxJar Settings")
		doc.taxjar_enabled = 1 if (calculate_tax or create_transactions) else 0
		if has_company_config:
			doc.set("company_config", [{
				"company": "_Test Company",
				"tax_account_head": "Tax - TC",
				"shipping_account_head": "Freight - TC",
				"taxjar_calculate_tax": calculate_tax,
				"taxjar_create_transactions": create_transactions,
			}])
		else:
			doc.set("company_config", [])
		if has_nexus:
			doc.set("nexus", [{"company": "_Test Company", "region": "California", "region_code": "CA", "country": "United States", "country_code": "US"}])
		else:
			doc.set("nexus", [])
		# No credentials → the background token check is not enqueued, so the only
		# enqueue under test is the nexus fetch.
		doc.set("table_hvjw", [])
		return doc

	def _call_on_update(self, doc):
		"""Call on_update with frappe.flags.in_test=True and enqueue mocked."""
		with patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.frappe.enqueue") as mock_enqueue, \
		     patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.frappe.db.exists", return_value=True):
			doc.on_update()
		return mock_enqueue

	# Trigger conditions

	def test_enqueues_when_features_enabled_config_present_nexus_empty(self):
		"""The happy path: first save after setup should trigger a background nexus fetch.

		Also enqueues the (separate, always-on-with-company_config) ledger/template
		sync job — see TestLedgerTemplateSyncEnqueue — so this asserts on the
		nexus-specific call rather than call count.
		"""
		doc = self._settings(calculate_tax=1, has_company_config=True, has_nexus=False)
		mock_enqueue = self._call_on_update(doc)
		nexus_calls = [c for c in mock_enqueue.call_args_list if "sync_nexus_list" in str(c)]
		self.assertEqual(len(nexus_calls), 1)

	def test_enqueues_when_only_create_transactions_enabled(self):
		"""create_transactions alone (without calculate_tax) should also trigger auto-fetch."""
		doc = self._settings(calculate_tax=0, create_transactions=1, has_company_config=True, has_nexus=False)
		mock_enqueue = self._call_on_update(doc)
		nexus_calls = [c for c in mock_enqueue.call_args_list if "sync_nexus_list" in str(c)]
		self.assertEqual(len(nexus_calls), 1)

	# Guard: nexus already populated

	def test_does_not_enqueue_when_nexus_already_populated(self):
		"""If nexus rows exist the fetch must not fire — avoids redundant API call on every save."""
		doc = self._settings(calculate_tax=1, has_company_config=True, has_nexus=True)
		mock_enqueue = self._call_on_update(doc)
		# enqueue may be called for the product_tax_categories background job — filter to nexus call only
		nexus_calls = [c for c in mock_enqueue.call_args_list if "sync_nexus_list" in str(c)]
		self.assertEqual(len(nexus_calls), 0)

	# Guard: features disabled

	def test_does_not_enqueue_when_features_disabled(self):
		"""No enqueue when both checkboxes are off."""
		doc = self._settings(calculate_tax=0, create_transactions=0, has_company_config=True, has_nexus=False)
		mock_enqueue = self._call_on_update(doc)
		nexus_calls = [c for c in mock_enqueue.call_args_list if "sync_nexus_list" in str(c)]
		self.assertEqual(len(nexus_calls), 0)

	# Guard: no company config

	def test_does_not_enqueue_when_company_config_empty(self):
		"""No company config means update_nexus_list would fail — skip the enqueue."""
		doc = self._settings(calculate_tax=1, has_company_config=False, has_nexus=False)
		mock_enqueue = self._call_on_update(doc)
		nexus_calls = [c for c in mock_enqueue.call_args_list if "sync_nexus_list" in str(c)]
		self.assertEqual(len(nexus_calls), 0)

	# Queue selection

	def test_enqueue_uses_short_queue(self):
		"""Nexus fetch should go to the short queue — it completes in seconds."""
		doc = self._settings(calculate_tax=1, has_company_config=True, has_nexus=False)
		mock_enqueue = self._call_on_update(doc)
		nexus_calls = [c for c in mock_enqueue.call_args_list if "sync_nexus_list" in str(c)]
		self.assertEqual(nexus_calls[0][1]["queue"], "short")


class TestLedgerTemplateSyncEnqueue(UnitTestCase):
	"""Tests for the on_update safety-net enqueue: ledger auto-fill + tax template
	sync should run whenever company_config is non-empty, regardless of whether
	the taxjar_enabled master switch or the per-company feature flags are on -
	ledgers/template should be ready before those are ever flipped on."""

	def _settings(self, has_company_config=True, taxjar_enabled=0):
		doc = frappe.get_single("TaxJar Settings")
		doc.taxjar_enabled = taxjar_enabled
		if has_company_config:
			doc.set("company_config", [{
				"company": "_Test Company",
				"tax_account_head": "Tax - TC",
				"shipping_account_head": "Freight - TC",
				"taxjar_calculate_tax": 0,
				"taxjar_create_transactions": 0,
			}])
		else:
			doc.set("company_config", [])
		doc.set("nexus", [{"company": "_Test Company", "region": "California", "region_code": "CA",
			"country": "United States", "country_code": "US"}])
		doc.set("table_hvjw", [])
		return doc

	def _call_on_update(self, doc):
		with patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.frappe.enqueue") as mock_enqueue, \
		     patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.frappe.db.exists", return_value=True):
			doc.on_update()
		return mock_enqueue

	def _sync_calls(self, mock_enqueue):
		return [c for c in mock_enqueue.call_args_list if "sync_all_company_tax_templates" in str(c)]

	def test_enqueues_when_company_config_present(self):
		doc = self._settings(has_company_config=True, taxjar_enabled=1)
		sync_calls = self._sync_calls(self._call_on_update(doc))
		self.assertEqual(len(sync_calls), 1)
		self.assertIn("regional.united_states.sync_all_company_tax_templates", sync_calls[0][0][0])

	def test_enqueues_even_when_master_switch_is_off(self):
		"""Unlike the nexus fetch, this is not gated on features_enabled — ledgers
		and the template should be ready before the switch is ever flipped on."""
		doc = self._settings(has_company_config=True, taxjar_enabled=0)
		sync_calls = self._sync_calls(self._call_on_update(doc))
		self.assertEqual(len(sync_calls), 1)

	def test_does_not_enqueue_when_company_config_empty(self):
		doc = self._settings(has_company_config=False, taxjar_enabled=1)
		sync_calls = self._sync_calls(self._call_on_update(doc))
		self.assertEqual(len(sync_calls), 0)

	def test_enqueue_uses_short_queue(self):
		doc = self._settings(has_company_config=True, taxjar_enabled=1)
		sync_calls = self._sync_calls(self._call_on_update(doc))
		self.assertEqual(sync_calls[0][1]["queue"], "short")


# ── TaxJar Customer API — _get_customer_name helper ─────────────────────────


class TestGetCustomerName(UnitTestCase):

	def test_sales_invoice(self):
		doc = MagicMock(doctype="Sales Invoice", customer="CUST-001")
		self.assertEqual(_get_customer_name(doc), "CUST-001")

	def test_sales_order(self):
		doc = MagicMock(doctype="Sales Order", customer="CUST-002")
		self.assertEqual(_get_customer_name(doc), "CUST-002")

	def test_quotation_for_customer(self):
		doc = MagicMock(doctype="Quotation", quotation_to="Customer", party_name="CUST-003")
		self.assertEqual(_get_customer_name(doc), "CUST-003")

	def test_quotation_for_lead(self):
		doc = MagicMock(doctype="Quotation", quotation_to="Lead", party_name="LEAD-001")
		self.assertIsNone(_get_customer_name(doc))

	def test_missing_customer_attr(self):
		doc = MagicMock(spec=[], doctype="Sales Invoice")
		self.assertIsNone(_get_customer_name(doc))


# ── TaxJar Customer API — customer_id in get_tax_data ────────────────────────


class TestGetTaxDataCustomerId(UnitTestCase):

	def _call_get_tax_data(self, doc, taxjar_customer_id=None, customer_exemption_type=None):
		from taxjar_integration.taxjar_integration.taxjar_integration import get_tax_data

		mock_company_config = MagicMock(
			tax_account_head="Sales Tax - TC",
			shipping_account_head="Freight - TC",
		)
		mock_address = MagicMock(
			pincode="78701",
			city="Austin",
			address_line1="123 Main St",
			country="United States",
			state="TX",
		)
		mock_address.get.return_value = "TX"

		# frappe.db.get_value is called for Country -> code lookups, Customer ->
		# taxjar_customer_id, and Customer -> taxjar_exemption_type - a blanket
		# return_value would answer all three identically and mask the bugs
		# this class guards against, so each is faked by fieldname.
		def fake_get_value(doctype, name=None, fieldname=None, **kwargs):
			if doctype == "Customer":
				if fieldname == "taxjar_customer_id":
					return taxjar_customer_id
				if fieldname == "taxjar_exemption_type":
					return customer_exemption_type
				return None
			return "us"

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=mock_company_config), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_address_details", return_value=mock_address), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_shipping_address_details", return_value=mock_address), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=fake_get_value), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.has_column", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_all", return_value=[]), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_line_item_dict", return_value={}):
			return get_tax_data(doc)

	def test_customer_id_uses_synced_taxjar_customer_id_not_raw_name(self):
		"""Regression guard: TaxJar stores/matches a customer's exemption record
		under the normalized id sync_customer_to_taxjar() actually assigned (e.g.
		"Alan-Houk"), not the raw ERPNext customer name ("Alan Houk") - sending
		the raw name here silently misses the match and the customer's
		exemption never applies, so tax gets calculated as if they had none."""
		doc = _make_doc()
		doc.customer = "Alan Houk"
		result = self._call_get_tax_data(doc, taxjar_customer_id="Alan-Houk")
		self.assertEqual(result["customer_id"], "Alan-Houk")

	def test_customer_id_falls_back_to_safe_id_when_never_synced(self):
		"""Customer hasn't been synced to TaxJar yet (taxjar_customer_id blank) -
		falls back to the same normalization sync_customer_to_taxjar() would use,
		so the id stays consistent whenever it does eventually sync."""
		doc = _make_doc()
		doc.customer = "Alan Houk"
		result = self._call_get_tax_data(doc, taxjar_customer_id=None)
		self.assertEqual(result["customer_id"], "Alan-Houk")

	def test_customer_id_absent_for_lead_quotation(self):
		doc = _make_doc()
		doc.doctype = "Quotation"
		doc.quotation_to = "Lead"
		doc.party_name = "LEAD-001"
		del doc.customer
		result = self._call_get_tax_data(doc)
		self.assertNotIn("customer_id", result)

	def test_exemption_type_absent_when_no_exemption_applies(self):
		doc = _make_doc()
		doc.customer = "Alan Houk"
		result = self._call_get_tax_data(doc)
		self.assertNotIn("exemption_type", result)

	def test_exemption_type_from_transaction_override(self):
		"""taxjar_transaction_exempt with no customer-level exemption on file -
		the payload carries the mapped (lowercase) exemption_type so TaxJar can
		zero the tax without needing a synced Customer record."""
		doc = _make_doc()
		doc.customer = "Alan Houk"
		doc.taxjar_transaction_exempt = 1
		doc.taxjar_transaction_exemption_type = "Wholesale"
		result = self._call_get_tax_data(doc)
		self.assertEqual(result["exemption_type"], "wholesale")

	def test_customer_exemption_type_takes_precedence_over_transaction_override(self):
		"""Matches TaxJar's own documented precedence: a matched customer's
		exemption_type wins over whatever order-level exemption_type is sent."""
		doc = _make_doc()
		doc.customer = "Alan Houk"
		doc.taxjar_transaction_exempt = 1
		doc.taxjar_transaction_exemption_type = "Wholesale"
		result = self._call_get_tax_data(doc, customer_exemption_type="Government")
		self.assertEqual(result["exemption_type"], "government")


# ── TaxJar Customer API — check_sales_tax_exemption ─────────────────────────


class TestCheckSalesTaxExemptionUpdated(UnitTestCase):

	def test_blanket_exempt_via_doc_flag(self):
		"""Document-level exempt_from_sales_tax should return (True, reason) and zero tax."""
		doc = _make_doc(taxes=[_make_tax_row("Sales Tax - TC", "Tax", 80.0)])
		doc.exempt_from_sales_tax = 1
		config = MagicMock(tax_account_head="Sales Tax - TC")
		is_exempt, reason = check_sales_tax_exemption(doc, config)
		self.assertTrue(is_exempt)
		self.assertIn("exempt", reason.lower())
		self.assertEqual(len([t for t in doc.taxes if t.account_head == "Sales Tax - TC"]), 0)

	def test_blanket_exempt_via_customer(self):
		"""Customer-level exempt_from_sales_tax should return (True, reason) and zero tax."""
		doc = _make_doc(taxes=[_make_tax_row("Sales Tax - TC", "Tax", 80.0)])
		doc.exempt_from_sales_tax = 0
		config = MagicMock(tax_account_head="Sales Tax - TC")

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.has_column", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value",
		           side_effect=_scalar_get_value({"exempt_from_sales_tax": 1, "taxjar_exemption_type": "Wholesale"})):
			is_exempt, reason = check_sales_tax_exemption(doc, config)

		self.assertTrue(is_exempt)
		self.assertIn("exempt", reason.lower())
		self.assertEqual(len([t for t in doc.taxes if t.account_head == "Sales Tax - TC"]), 0)

	def test_state_specific_exempt_returns_false(self):
		"""Customer with exempt_regions but exempt_from_sales_tax=0 should NOT short-circuit."""
		doc = _make_doc(taxes=[_make_tax_row("Sales Tax - TC", "Tax", 80.0)])
		doc.exempt_from_sales_tax = 0
		config = MagicMock(tax_account_head="Sales Tax - TC")

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.has_column", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value",
		           side_effect=_scalar_get_value({"exempt_from_sales_tax": 0, "taxjar_exemption_type": None})):
			is_exempt, reason = check_sales_tax_exemption(doc, config)

		self.assertFalse(is_exempt)
		self.assertIsNone(reason)
		self.assertEqual(len(doc.taxes), 1)

	def test_quotation_for_lead_does_not_crash(self):
		"""Quotation for Lead has no customer — exemption check should return (False, None) safely."""
		doc = _make_doc()
		doc.doctype = "Quotation"
		doc.quotation_to = "Lead"
		doc.party_name = "LEAD-001"
		del doc.customer
		doc.exempt_from_sales_tax = 0
		config = MagicMock(tax_account_head="Sales Tax - TC")

		is_exempt, reason = check_sales_tax_exemption(doc, config)
		self.assertFalse(is_exempt)


# ── TaxJar Customer API — _get_customer_exemption_type ──────────────────────


class _patch_all:
	"""Combine several patches into one context manager."""

	def __init__(self, *patchers):
		self.patchers = patchers

	def __enter__(self):
		return [p.__enter__() for p in self.patchers]

	def __exit__(self, *exc):
		for p in reversed(self.patchers):
			p.__exit__(*exc)
		return False


class TestGetCustomerExemptionType(UnitTestCase):
	"""_get_customer_exemption_type() feeds the "Is the customer taxable?" status
	shown on the transaction (see set_sales_tax) - distinct from
	check_sales_tax_exemption()'s hard-stop exempt_from_sales_tax check, this
	fires for customers who only have taxjar_exemption_type set (the TaxJar-
	native path). Region scoping lives in _customer_master_exemption(); these
	cases list no exempt regions, which means exempt everywhere - see
	test_customer_exemption_is_region_scoped for the scoped cases."""

	def _patch(self, exemption_type):
		mod = "taxjar_integration.taxjar_integration.taxjar_integration"
		return _patch_all(
			patch(f"{mod}.frappe.db.get_value", side_effect=_scalar_get_value(exemption_type)),
			# No exempt regions listed: exempt wherever the sale ships.
			patch(f"{mod}.frappe.get_all", return_value=[]),
		)

	def test_returns_none_when_blank(self):
		doc = _make_doc()
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.has_column", return_value=True), \
		     self._patch(None):
			self.assertIsNone(_get_customer_exemption_type(doc))

	def test_returns_none_when_non_exempt(self):
		""""Non Exempt" is an explicit selectable option meaning "normal taxable
		customer" - not a truthy exemption."""
		doc = _make_doc()
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.has_column", return_value=True), \
		     self._patch("Non Exempt"):
			self.assertIsNone(_get_customer_exemption_type(doc))

	def test_returns_exemption_type_when_set(self):
		doc = _make_doc()
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.has_column", return_value=True), \
		     self._patch("Wholesale"):
			self.assertEqual(_get_customer_exemption_type(doc), "Wholesale")

	def test_returns_none_without_a_customer(self):
		doc = _make_doc()
		doc.doctype = "Quotation"
		doc.quotation_to = "Lead"
		doc.party_name = "LEAD-001"
		del doc.customer
		self.assertIsNone(_get_customer_exemption_type(doc))

	def test_returns_none_when_column_missing(self):
		"""Non-US company/region where the field was never installed."""
		doc = _make_doc()
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.has_column", return_value=False):
			self.assertIsNone(_get_customer_exemption_type(doc))


class TestGetEffectiveExemption(UnitTestCase):
	"""_get_effective_exemption() combines the customer master's exemption_type
	with the transaction-level override, customer taking precedence - matches
	TaxJar's own documented precedence rule for a matched customer_id."""

	def _doc_with_transaction_override(self, exemption_type="Wholesale"):
		doc = _make_doc()
		doc.taxjar_transaction_exempt = 1
		doc.taxjar_transaction_exemption_type = exemption_type
		return doc

	def test_customer_exemption_wins_when_both_set(self):
		doc = self._doc_with_transaction_override("Wholesale")
		with patch("taxjar_integration.taxjar_integration.taxjar_integration._get_customer_exemption_type", return_value="Government"):
			result = _get_effective_exemption(doc)
		self.assertEqual(result, ("Government", "customer"))

	def test_transaction_override_used_when_customer_not_exempt(self):
		doc = self._doc_with_transaction_override("Wholesale")
		with patch("taxjar_integration.taxjar_integration.taxjar_integration._get_customer_exemption_type", return_value=None):
			result = _get_effective_exemption(doc)
		self.assertEqual(result, ("Wholesale", "transaction"))

	def test_neither_set_returns_none_none(self):
		doc = _make_doc()
		with patch("taxjar_integration.taxjar_integration.taxjar_integration._get_customer_exemption_type", return_value=None):
			result = _get_effective_exemption(doc)
		self.assertEqual(result, (None, None))

	def test_checkbox_ticked_without_a_reason_selected_is_a_noop(self):
		"""Reason is mandatory_depends_on the checkbox on the form, but a
		document saved via API could still have the box ticked with no reason -
		don't treat that as an exemption with no explanation."""
		doc = _make_doc()
		doc.taxjar_transaction_exempt = 1
		doc.taxjar_transaction_exemption_type = None
		with patch("taxjar_integration.taxjar_integration.taxjar_integration._get_customer_exemption_type", return_value=None):
			result = _get_effective_exemption(doc)
		self.assertEqual(result, (None, None))

	def test_reason_set_without_checkbox_ticked_is_ignored(self):
		"""Stale/leftover exemption_type value with the checkbox off must not
		be treated as an active override."""
		doc = _make_doc()
		doc.taxjar_transaction_exempt = 0
		doc.taxjar_transaction_exemption_type = "Wholesale"
		with patch("taxjar_integration.taxjar_integration.taxjar_integration._get_customer_exemption_type", return_value=None):
			result = _get_effective_exemption(doc)
		self.assertEqual(result, (None, None))


# ── TaxJar Customer API — sync_customer_to_taxjar ───────────────────────────


class TestSyncCustomerToTaxJar(UnitTestCase):

	def _make_customer_doc(self, exemption_type="Wholesale", exempt_regions=None, customer_id=""):
		doc = MagicMock()
		doc.customer_name = "Acme Corp"
		doc.get.side_effect = lambda field, default=None: {
			"taxjar_exemption_type": exemption_type,
			"taxjar_exempt_regions": exempt_regions or [],
			"taxjar_customer_id": customer_id,
		}.get(field, default)
		return doc

	def _make_exempt_region(self, country="US", state="TX"):
		region = MagicMock()
		region.country = country
		region.state = state
		return region

	def test_new_customer_uses_create(self):
		"""When taxjar_customer_id is empty, should call create_customer directly."""
		customer_doc = self._make_customer_doc(customer_id="")
		mock_client = MagicMock()
		mock_client.create_customer.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=customer_doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call") as mock_log, \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.set_value") as mock_set:
			sync_customer_to_taxjar("CUST-001", company="Test Co")

		mock_client.create_customer.assert_called_once()
		mock_client.update_customer.assert_not_called()
		payload = mock_client.create_customer.call_args[0][0]
		self.assertEqual(payload["customer_id"], "CUST-001")  # already URL-safe
		self.assertEqual(payload["exemption_type"], "wholesale")
		self.assertEqual(payload["name"], "Acme Corp")

		success_calls = [c for c in mock_log.call_args_list if c[1].get("status") == "success"]
		self.assertTrue(len(success_calls) > 0)
		self.assertTrue(mock_set.called)

	def test_new_customer_with_spaces_uses_safe_id(self):
		"""Customer names with spaces should get a URL-safe customer_id."""
		customer_doc = self._make_customer_doc(customer_id="")
		customer_doc.customer_name = "Denna Jaina"
		mock_client = MagicMock()
		mock_client.create_customer.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=customer_doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.set_value") as mock_set:
			sync_customer_to_taxjar("Denna Jaina", company="Test Co")

		payload = mock_client.create_customer.call_args[0][0]
		self.assertEqual(payload["customer_id"], "Denna-Jaina")
		self.assertEqual(payload["name"], "Denna Jaina")
		# taxjar_customer_id stored as the safe ID
		id_set_calls = [c for c in mock_set.call_args_list if len(c[0]) >= 4 and c[0][2] == "taxjar_customer_id"]
		self.assertEqual(id_set_calls[0][0][3], "Denna-Jaina")

	def test_existing_customer_uses_update(self):
		"""When taxjar_customer_id is set, should call update_customer with the stored safe ID."""
		customer_doc = self._make_customer_doc(customer_id="Denna-Jaina")
		mock_client = MagicMock()
		mock_client.update_customer.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=customer_doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.set_value"):
			sync_customer_to_taxjar("Denna Jaina", company="Test Co")

		mock_client.update_customer.assert_called_once()
		# The safe ID (from taxjar_customer_id) should be used, not the raw name
		self.assertEqual(mock_client.update_customer.call_args[0][0], "Denna-Jaina")
		mock_client.create_customer.assert_not_called()

	def test_update_fallback_to_create_on_404(self):
		"""When update_customer returns 404, should fall back to create without clearing taxjar_customer_id."""
		import taxjar.exceptions

		customer_doc = self._make_customer_doc(customer_id="CUST-001")
		mock_client = MagicMock()

		err = taxjar.exceptions.TaxJarResponseError(MagicMock())
		err.full_response = {"status_code": 404}
		mock_client.update_customer.side_effect = err
		mock_client.create_customer.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=customer_doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.set_value") as mock_set:
			sync_customer_to_taxjar("CUST-001")

		mock_client.create_customer.assert_called_once()
		# taxjar_customer_id must NOT be cleared — prevents permanent broken state if create also fails
		clear_calls = [c for c in mock_set.call_args_list if len(c[0]) >= 4 and c[0][2] == "taxjar_customer_id" and c[0][3] == ""]
		self.assertEqual(len(clear_calls), 0)

	def test_skips_when_no_client(self):
		"""Should log skip AND flip the customer to Failed - a customer queued
		by bulk_sync_to_taxjar (or on_customer_update) must not be left stuck
		at "Queued" forever just because no client could be resolved, the same
		way sync_transaction_to_taxjar's own client-missing branch already
		behaves for Sales Invoices."""
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=None), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call") as mock_log, \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_customer_sync_status") as mock_status:
			sync_customer_to_taxjar("CUST-001")

		skip_calls = [c for c in mock_log.call_args_list if c[1].get("status") == "skipped"]
		self.assertEqual(len(skip_calls), 1)
		args, kwargs = mock_status.call_args
		self.assertEqual(args, ("CUST-001", "Failed"))

	def test_no_client_is_not_retryable(self):
		"""A missing/misconfigured credential for this company is a config
		problem, not a transient one - retrying every 15 minutes forever
		achieves nothing until a human fixes it (contrast with a real
		TaxJarConnectionError or 5xx, which stays retryable via
		classify_taxjar_error()). retryable defaults to False, so this must
		not be passed as True."""
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=None), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_customer_sync_status") as mock_status:
			sync_customer_to_taxjar("CUST-001")

		args, kwargs = mock_status.call_args
		self.assertEqual(args, ("CUST-001", "Failed"))
		self.assertIn("not configured", kwargs["error"])
		self.assertNotIn("retryable", kwargs)

	def test_exempt_regions_serialized(self):
		"""Exempt regions from child table should appear as dicts in the payload."""
		regions = [self._make_exempt_region("US", "TX"), self._make_exempt_region("US", "CA")]
		customer_doc = self._make_customer_doc(exempt_regions=regions, customer_id="")
		mock_client = MagicMock()
		mock_client.create_customer.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=customer_doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.set_value"):
			sync_customer_to_taxjar("CUST-001")

		payload = mock_client.create_customer.call_args[0][0]
		self.assertEqual(payload["exempt_regions"], [{"country": "US", "state": "TX"}, {"country": "US", "state": "CA"}])

	def test_defaults_to_non_exempt(self):
		"""When exemption_type is blank, payload should send 'non_exempt'."""
		customer_doc = self._make_customer_doc(exemption_type="", customer_id="")
		mock_client = MagicMock()
		mock_client.create_customer.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=customer_doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.set_value"):
			sync_customer_to_taxjar("CUST-001")

		payload = mock_client.create_customer.call_args[0][0]
		self.assertEqual(payload["exemption_type"], "non_exempt")

	def test_connection_error_sets_failed(self):
		"""TaxJarConnectionError should set Failed status."""
		import taxjar.exceptions

		customer_doc = self._make_customer_doc(customer_id="")
		mock_client = MagicMock()
		mock_client.create_customer.side_effect = taxjar.exceptions.TaxJarConnectionError("timeout")

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=customer_doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_customer_sync_status") as mock_status:
			sync_customer_to_taxjar("CUST-001")

		args, kwargs = mock_status.call_args
		self.assertEqual(args, ("CUST-001", "Failed"))
		self.assertIn("unreachable", kwargs["error"])
		self.assertTrue(kwargs["retryable"], "a connection failure has to stay on the retry cron")


# ── TaxJar Customer API — on_customer_update hook ───────────────────────────


class TestOnCustomerUpdate(UnitTestCase):

	def _make_customer_doc(self, exemption_type="Wholesale", customer_id="", exempt_regions=None,
	                       has_value_changed=True, previous_regions=None, sync_status=""):
		"""Build a mock Customer doc with TaxJar fields and change-detection support."""
		doc = MagicMock()
		doc.name = "CUST-001"
		doc.db_set = MagicMock()

		regions = exempt_regions or []
		doc.get.side_effect = lambda field, default=None: {
			"taxjar_exemption_type": exemption_type,
			"taxjar_customer_id": customer_id,
			"taxjar_exempt_regions": regions,
			"taxjar_customer_sync_status": sync_status,
		}.get(field, default)

		doc.has_value_changed.return_value = has_value_changed

		if previous_regions is not None:
			previous = MagicMock()
			previous.get.return_value = previous_regions
			doc.get_doc_before_save.return_value = previous
		else:
			doc.get_doc_before_save.return_value = None

		return doc

	def test_skips_when_features_disabled(self):
		doc = self._make_customer_doc()
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=0), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.enqueue") as mock_enqueue:
			on_customer_update(doc, None)
		mock_enqueue.assert_not_called()

	def test_skips_when_no_exemption_and_never_synced(self):
		"""Clearing exemption on a never-synced customer should not sync."""
		doc = self._make_customer_doc(exemption_type="", customer_id="")
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.enqueue") as mock_enqueue:
			on_customer_update(doc, None)
		mock_enqueue.assert_not_called()

	def test_clears_stale_status_when_exemption_cleared_and_never_synced(self):
		"""Nothing to push to TaxJar (no exemption, no existing customer id) must
		not leave a Failed/Queued status from an earlier attempt sitting there
		with no explanation - it should reset to blank, same as a real sync
		attempt would leave the field once it's no longer relevant."""
		doc = self._make_customer_doc(exemption_type="", customer_id="", sync_status="Failed")
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.enqueue") as mock_enqueue, \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_customer_sync_status") as mock_status:
			on_customer_update(doc, None)
		mock_enqueue.assert_not_called()
		mock_status.assert_called_once_with("CUST-001", "")

	def test_disabled_clears_stale_status_and_notifies_user(self):
		"""TaxJar off must not silently swallow the edit - any stale status is
		reset, and the user is told why nothing was sent, instead of a Customer
		save that visibly did nothing."""
		doc = self._make_customer_doc(exemption_type="Wholesale", sync_status="Failed")
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=0), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.enqueue") as mock_enqueue, \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_customer_sync_status") as mock_status, \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.msgprint") as mock_msgprint:
			on_customer_update(doc, None)
		mock_enqueue.assert_not_called()
		mock_status.assert_called_once_with("CUST-001", "")
		mock_msgprint.assert_called_once()

	def test_disabled_with_no_stale_status_still_notifies_but_does_not_reset(self):
		"""A customer that was never synced has nothing to reset - only the
		notification is needed, not a pointless status write."""
		doc = self._make_customer_doc(exemption_type="Wholesale", sync_status="")
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=0), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_customer_sync_status") as mock_status, \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.msgprint") as mock_msgprint:
			on_customer_update(doc, None)
		mock_status.assert_not_called()
		mock_msgprint.assert_called_once()

	def test_disabled_when_no_company_actually_has_a_feature_enabled(self):
		"""Master switch on, but every company config row has both feature
		flags off - _is_taxjar_enabled() treats that the same as the master
		switch being off (its own "at least one company enabled" check), so
		this reaches the disabled branch (msgprint, no enqueue), not the
		per-company loop. get_single_value only fast-paths the pure
		master-switch-off case, so this also needs the full settings doc
		mocked via get_single for _is_taxjar_enabled()'s own "any company
		enabled" check to see the all-off config."""
		doc = self._make_customer_doc(exemption_type="Wholesale", sync_status="Failed")
		config = MagicMock(company="Test Co", taxjar_calculate_tax=0, taxjar_create_transactions=0)
		settings = MagicMock(taxjar_enabled=1, company_config=[config])

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_single", return_value=settings), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.enqueue") as mock_enqueue, \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_customer_sync_status") as mock_status, \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.msgprint") as mock_msgprint:
			on_customer_update(doc, None)
		mock_enqueue.assert_not_called()
		mock_status.assert_called_once_with("CUST-001", "")
		mock_msgprint.assert_called_once()

	def test_skips_when_no_taxjar_fields_changed(self):
		"""Saving a customer without changing TaxJar fields should not sync."""
		old_region = MagicMock(country="US", state="TX")
		new_region = MagicMock(country="US", state="TX")
		doc = self._make_customer_doc(
			exemption_type="Wholesale", customer_id="CUST-001",
			has_value_changed=False,
			exempt_regions=[new_region], previous_regions=[old_region],
		)
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.enqueue") as mock_enqueue:
			on_customer_update(doc, None)
		mock_enqueue.assert_not_called()

	def test_syncs_when_exemption_type_set(self):
		"""Setting exemption type should trigger sync."""
		doc = self._make_customer_doc(exemption_type="Government", customer_id="")
		config = MagicMock(company="Test Co")
		settings = MagicMock()
		settings.company_config = [config]

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_single", return_value=settings), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.enqueue") as mock_enqueue:
			on_customer_update(doc, None)
		mock_enqueue.assert_called_once()

	def test_syncs_when_exemption_cleared_on_synced_customer(self):
		"""Clearing exemption on a previously-synced customer should sync as non_exempt."""
		doc = self._make_customer_doc(exemption_type="", customer_id="CUST-001")
		config = MagicMock(company="Test Co")
		settings = MagicMock()
		settings.company_config = [config]

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_single", return_value=settings), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.enqueue") as mock_enqueue:
			on_customer_update(doc, None)
		mock_enqueue.assert_called_once()
		doc.db_set.assert_called_once_with("taxjar_customer_sync_status", "Queued", update_modified=False)

	def test_syncs_when_exempt_regions_changed(self):
		"""Adding exempt regions should trigger sync even if exemption_type didn't change."""
		old_region = MagicMock(country="US", state="TX")
		new_region_1 = MagicMock(country="US", state="TX")
		new_region_2 = MagicMock(country="US", state="CA")
		doc = self._make_customer_doc(
			exemption_type="Wholesale", customer_id="CUST-001",
			has_value_changed=False,
			exempt_regions=[new_region_1, new_region_2], previous_regions=[old_region],
		)
		config = MagicMock(company="Test Co")
		settings = MagicMock()
		settings.company_config = [config]

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_single", return_value=settings), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.enqueue") as mock_enqueue:
			on_customer_update(doc, None)
		mock_enqueue.assert_called_once()

	def test_enqueues_per_company(self):
		doc = self._make_customer_doc(exemption_type="Wholesale")
		config_a = MagicMock(company="Company A")
		config_b = MagicMock(company="Company B")
		settings = MagicMock()
		settings.company_config = [config_a, config_b]

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_single", return_value=settings), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.enqueue") as mock_enqueue:
			on_customer_update(doc, None)

		self.assertEqual(mock_enqueue.call_count, 2)
		companies_synced = [c[1]["company"] for c in mock_enqueue.call_args_list]
		self.assertIn("Company A", companies_synced)
		self.assertIn("Company B", companies_synced)

	def test_enqueue_uses_short_queue_and_deduplicate(self):
		doc = self._make_customer_doc(exemption_type="Government")
		config = MagicMock(company="Test Co")
		settings = MagicMock()
		settings.company_config = [config]

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_single", return_value=settings), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.enqueue") as mock_enqueue:
			on_customer_update(doc, None)

		call_kwargs = mock_enqueue.call_args[1]
		self.assertEqual(call_kwargs["queue"], "short")
		self.assertTrue(call_kwargs["deduplicate"])
		self.assertIn("job_id", call_kwargs)
		self.assertIn("CUST-001", call_kwargs["job_id"])


# ── TaxJar Customer API — Custom Field definitions ──────────────────────────


class TestCustomerCustomFields(UnitTestCase):

	def _get_customer_field_defs(self):
		"""Intercept create_custom_fields and return the Customer field list."""
		captured = {}
		def fake_create(fields, update=True):
			captured.update(fields)
		with patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.create_custom_fields", side_effect=fake_create):
			make_custom_fields(update=True)
		return {f["fieldname"]: f for f in captured.get("Customer", [])}

	def test_exemption_type_is_select(self):
		fields = self._get_customer_field_defs()
		f = fields["taxjar_exemption_type"]
		self.assertEqual(f["fieldtype"], "Select")
		for opt in ("Wholesale", "Government", "Other", "Non Exempt"):
			self.assertIn(opt, f["options"])

	def test_exempt_regions_is_table(self):
		fields = self._get_customer_field_defs()
		f = fields["taxjar_exempt_regions"]
		self.assertEqual(f["fieldtype"], "Table")
		self.assertEqual(f["options"], "TaxJar Customer Exempt Region")

	def test_customer_id_is_readonly(self):
		fields = self._get_customer_field_defs()
		f = fields["taxjar_customer_id"]
		self.assertEqual(f["fieldtype"], "Data")
		self.assertTrue(f.get("read_only"))

	def test_last_synced_is_readonly_datetime(self):
		fields = self._get_customer_field_defs()
		f = fields["taxjar_last_synced"]
		self.assertEqual(f["fieldtype"], "Datetime")
		self.assertTrue(f.get("read_only"))

	def test_exempt_regions_depends_on_exemption_type(self):
		fields = self._get_customer_field_defs()
		f = fields["taxjar_exempt_regions"]
		self.assertIn("taxjar_exemption_type", f.get("depends_on", ""))

	def test_exemption_type_and_regions_are_hidden(self):
		"""The Manage Exemption dialog + summary card are now the only UI for
		these - the raw fields stay writable (configure_exemption still uses
		them) but are hidden, not deleted."""
		fields = self._get_customer_field_defs()
		self.assertTrue(fields["taxjar_exemption_type"].get("hidden"))
		self.assertTrue(fields["taxjar_exempt_regions"].get("hidden"))

	def test_exemption_summary_html_field_exists(self):
		fields = self._get_customer_field_defs()
		f = fields["taxjar_exemption_summary_html"]
		self.assertEqual(f["fieldtype"], "HTML")
		self.assertEqual(f["insert_after"], "taxjar_section_break")

	def test_main_section_layout(self):
		"""One section ("TaxJar Tax Exemption"): just the summary card in
		column 1, Sync Status/Sync Error in column 2 - the at-a-glance state.
		Customer ID and Last Synced are bookkeeping detail, not glance-state,
		so they live in their own collapsed section instead."""
		fields = self._get_customer_field_defs()
		self.assertEqual(fields["taxjar_column_break"]["insert_after"], "taxjar_exemption_summary_html")
		self.assertEqual(fields["taxjar_customer_sync_status"]["insert_after"], "taxjar_column_break")
		self.assertEqual(fields["taxjar_customer_sync_error"]["insert_after"], "taxjar_customer_sync_status")

	def test_sync_details_section_is_collapsed_by_default(self):
		"""collapsible=1 with no collapsible_depends_on collapses by default
		(frappe/form/layout.js refresh_section_collapse: `let collapse =
		true` unless collapsible_depends_on says otherwise) - exactly what
		"collapsed" means here, not conditionally hidden like the old
		depends_on-gated section this replaced."""
		fields = self._get_customer_field_defs()
		section = fields["taxjar_sync_details_section"]
		self.assertEqual(section["fieldtype"], "Section Break")
		self.assertEqual(section["label"], "TaxJar Sync Details")
		self.assertEqual(section["insert_after"], "taxjar_customer_sync_error")
		self.assertTrue(section.get("collapsible"))
		self.assertFalse(section.get("collapsible_depends_on"))
		self.assertFalse(section.get("depends_on"))

	def test_sync_details_section_layout(self):
		fields = self._get_customer_field_defs()
		self.assertEqual(fields["taxjar_customer_id"]["insert_after"], "taxjar_sync_details_section")
		self.assertEqual(fields["taxjar_sync_details_cb"]["insert_after"], "taxjar_customer_id")
		self.assertEqual(fields["taxjar_last_synced"]["insert_after"], "taxjar_sync_details_cb")

	def test_raw_data_section_layout(self):
		"""A third, separate section groups the hidden backing fields
		(Exemption Type in column 1, Retry Pending + Tax Exempt Regions in
		column 2) - configure_exemption's write path, not a UI a normal user
		reaches (both fields stay hidden=1)."""
		fields = self._get_customer_field_defs()
		section = fields["taxjar_raw_section"]
		self.assertEqual(section["fieldtype"], "Section Break")
		self.assertEqual(section["label"], "TaxJar Exemption Raw Data")
		self.assertEqual(section["insert_after"], "taxjar_last_synced")
		self.assertEqual(fields["taxjar_exemption_type"]["insert_after"], "taxjar_raw_section")
		self.assertEqual(fields["taxjar_raw_column_break"]["insert_after"], "taxjar_exemption_type")
		self.assertEqual(
			fields["taxjar_customer_sync_retryable"]["insert_after"], "taxjar_raw_column_break"
		)
		self.assertEqual(
			fields["taxjar_exempt_regions"]["insert_after"], "taxjar_customer_sync_retryable"
		)

	def test_no_field_carries_a_description(self):
		fields = self._get_customer_field_defs()
		for fieldname, f in fields.items():
			self.assertFalse(f.get("description"), f"{fieldname} still has a description")

	def test_no_two_fields_share_an_insert_after_anchor(self):
		"""Two fields both claiming insert_after=X collide onto the same idx
		at creation time (Custom Field.validate: self.idx =
		fieldnames.index(insert_after) + 1, computed once, with nothing to
		break the tie) - exactly what silently pushed
		taxjar_exemption_summary_html to the very end of the Customer field
		list, inside a conditionally-hidden section, when it first shipped."""
		fields = self._get_customer_field_defs()
		anchors = [f["insert_after"] for f in fields.values() if f.get("insert_after")]
		seen = set()
		for anchor in anchors:
			self.assertNotIn(anchor, seen, f"Two fields both insert_after={anchor}")
			seen.add(anchor)

	def test_section_inserted_in_tax_tab(self):
		"""TaxJar section must be inside the Tax tab."""
		fields = self._get_customer_field_defs()
		f = fields["taxjar_section_break"]
		self.assertEqual(f["insert_after"], "tax_tab")


# ── TaxJar Customer API — DocType schema ─────────────────────────────────────


class TestTaxJarCustomerExemptRegion(UnitTestCase):

	def test_doctype_exists(self):
		self.assertTrue(frappe.db.exists("DocType", "TaxJar Customer Exempt Region"))

	def test_is_child_table(self):
		meta = frappe.get_meta("TaxJar Customer Exempt Region")
		self.assertTrue(meta.istable)

	def test_has_country_field(self):
		meta = frappe.get_meta("TaxJar Customer Exempt Region")
		field = meta.get_field("country")
		self.assertIsNotNone(field)
		self.assertEqual(field.fieldtype, "Select")

	def test_has_state_field(self):
		meta = frappe.get_meta("TaxJar Customer Exempt Region")
		field = meta.get_field("state")
		self.assertIsNotNone(field)
		self.assertEqual(field.fieldtype, "Select")


# ── Realtime notification: _set_sync_status / _set_customer_sync_status ────
# Fixes stale sync status on an open form: the async paths (on_submit/
# on_cancel hooks, the 15-min cron retry, bulk retry from the Transactions/
# Customers pages) update the DB via a bare frappe.db.set_value with no
# notification, so an already-open form kept showing "Queued" until manually
# reloaded. Same fix india_compliance already uses elsewhere in this bench
# (GSTR-3B report generation, e-Waybill PDF generation): publish_realtime
# scoped to the document's own room via doctype/docname, after_commit=True
# so the event can't race ahead of the write becoming visible.

class TestSetSyncStatusRealtime(UnitTestCase):

	def test_publishes_realtime_event_scoped_to_document(self):
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.publish_realtime") as mock_publish:
			_set_sync_status("SINV-TEST-001", "Synced")

		mock_publish.assert_any_call(
			"taxjar_invoice_sync_update",
			{"taxjar_sync_status": "Synced"},
			doctype="Sales Invoice",
			docname="SINV-TEST-001",
			after_commit=True,
		)
		# Exactly two: the doc-room event above for the open form, and the
		# doctype-room event below for the Transaction Sync page.
		self.assertEqual(mock_publish.call_count, 2)

	def test_publishes_after_the_db_write(self):
		"""Must not race ahead of the db.set_value it's meant to notify
		about - a client that reload_doc()s in response to the event needs
		the write to have actually happened first."""
		calls = []
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", return_value=0), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.set_value",
		           side_effect=lambda *a, **k: calls.append("db_write")), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.publish_realtime",
		           side_effect=lambda *a, **k: calls.append("publish")):
			_set_sync_status("SINV-TEST-001", "Failed", error="timeout")

		self.assertEqual(calls, ["db_write", "publish", "publish"])

	def test_message_reflects_status_for_each_state(self):
		for status in ("Synced", "Failed", "Queued", "Excluded"):
			with self.subTest(status=status):
				with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.publish_realtime") as mock_publish:
					_set_sync_status("SINV-TEST-001", status)
				# call_args_list[0] is the doc-room event; [1] is the page's.
				self.assertEqual(mock_publish.call_args_list[0][0][1], {"taxjar_sync_status": status})
				self.assertEqual(
					mock_publish.call_args_list[1][0][1],
					{"name": "SINV-TEST-001", "taxjar_sync_status": status},
				)


class TestSetCustomerSyncStatusRealtime(UnitTestCase):

	def test_publishes_realtime_event_scoped_to_document(self):
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.publish_realtime") as mock_publish:
			_set_customer_sync_status("CUST-TEST-001", "Synced")

		mock_publish.assert_any_call(
			"taxjar_customer_sync_update",
			{"taxjar_customer_sync_status": "Synced"},
			doctype="Customer",
			docname="CUST-TEST-001",
			after_commit=True,
		)
		self.assertEqual(mock_publish.call_count, 2)

	def test_publishes_after_the_db_write(self):
		calls = []
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", return_value=0), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.set_value",
		           side_effect=lambda *a, **k: calls.append("db_write")), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.publish_realtime",
		           side_effect=lambda *a, **k: calls.append("publish")):
			_set_customer_sync_status("CUST-TEST-001", "Failed", error="timeout")

		self.assertEqual(calls, ["db_write", "publish", "publish"])


class TestSetSyncStatusRetryCount(UnitTestCase):

	MOD = "taxjar_integration.taxjar_integration.taxjar_integration"

	def test_failed_increments_retry_count(self):
		with patch(f"{self.MOD}.frappe.db.get_value", return_value=2), \
		     patch(f"{self.MOD}.frappe.db.set_value") as mock_set, \
		     patch(f"{self.MOD}.frappe.publish_realtime"):
			_set_sync_status("SINV-TEST-001", "Failed", error="timeout", retryable=True)

		fields = mock_set.call_args[0][2]
		self.assertEqual(fields["taxjar_sync_retry_count"], 3)

	def test_first_failure_starts_at_one(self):
		"""No prior stored count (a new invoice's first-ever failure) reads back
		as None from the db - must not crash trying to add 1 to it."""
		with patch(f"{self.MOD}.frappe.db.get_value", return_value=None), \
		     patch(f"{self.MOD}.frappe.db.set_value") as mock_set, \
		     patch(f"{self.MOD}.frappe.publish_realtime"):
			_set_sync_status("SINV-TEST-001", "Failed", error="boom", retryable=True)

		fields = mock_set.call_args[0][2]
		self.assertEqual(fields["taxjar_sync_retry_count"], 1)

	def test_synced_resets_retry_count(self):
		with patch(f"{self.MOD}.frappe.db.get_value", return_value=4), \
		     patch(f"{self.MOD}.frappe.db.set_value") as mock_set, \
		     patch(f"{self.MOD}.frappe.publish_realtime"):
			_set_sync_status("SINV-TEST-001", "Synced")

		fields = mock_set.call_args[0][2]
		self.assertEqual(fields["taxjar_sync_retry_count"], 0)

	def test_excluded_resets_retry_count(self):
		with patch(f"{self.MOD}.frappe.db.get_value", return_value=4), \
		     patch(f"{self.MOD}.frappe.db.set_value") as mock_set, \
		     patch(f"{self.MOD}.frappe.publish_realtime"):
			_set_sync_status("SINV-TEST-001", "Excluded")

		fields = mock_set.call_args[0][2]
		self.assertEqual(fields["taxjar_sync_retry_count"], 0)


class TestSetCustomerSyncStatusRetryCount(UnitTestCase):

	MOD = "taxjar_integration.taxjar_integration.taxjar_integration"

	def test_failed_increments_retry_count(self):
		with patch(f"{self.MOD}.frappe.db.get_value", return_value=1), \
		     patch(f"{self.MOD}.frappe.db.set_value") as mock_set, \
		     patch(f"{self.MOD}.frappe.publish_realtime"):
			_set_customer_sync_status("CUST-TEST-001", "Failed", error="timeout", retryable=True)

		fields = mock_set.call_args[0][2]
		self.assertEqual(fields["taxjar_customer_sync_retry_count"], 2)

	def test_synced_resets_retry_count(self):
		with patch(f"{self.MOD}.frappe.db.get_value", return_value=3), \
		     patch(f"{self.MOD}.frappe.db.set_value") as mock_set, \
		     patch(f"{self.MOD}.frappe.publish_realtime"):
			_set_customer_sync_status("CUST-TEST-001", "Synced")

		fields = mock_set.call_args[0][2]
		self.assertEqual(fields["taxjar_customer_sync_retry_count"], 0)


# ── Realtime notification: the Transactions / Customers desk pages ─────────
# A desk Page never joins a doc room (only a form does, via doc_subscribe on
# form-load), so the doc-scoped events above are unreachable from the pages and
# their status pills sat stale until a browser reload. These publish to the
# doctype room instead - narrow enough that only sockets which opted in receive
# it, and permission-checked server-side at join time, unlike the site room
# every System User is auto-joined to.

class TestTransactionsPageRealtime(UnitTestCase):

	MOD = "taxjar_integration.taxjar_integration.taxjar_integration"

	def test_publishes_doctype_room_event_with_name_and_status(self):
		with patch(f"{self.MOD}.frappe.db.get_value", return_value=0), \
		     patch(f"{self.MOD}.frappe.db.set_value"), \
		     patch(f"{self.MOD}.frappe.publish_realtime") as mock_publish:
			_set_sync_status("SINV-TEST-001", "Failed", error="boom")

		mock_publish.assert_any_call(
			"taxjar_transactions_update",
			{"name": "SINV-TEST-001", "taxjar_sync_status": "Failed"},
			room="doctype:Sales Invoice",
			after_commit=True,
		)

	def test_uses_doctype_room_not_site_room(self):
		"""The site room would wake every logged-in desk user - every System
		User is auto-joined to it on connect."""
		with patch(f"{self.MOD}.frappe.db.set_value"), \
		     patch(f"{self.MOD}.frappe.publish_realtime") as mock_publish:
			_set_sync_status("SINV-TEST-001", "Synced")

		room = mock_publish.call_args_list[1][1]["room"]
		self.assertEqual(room, "doctype:Sales Invoice")
		self.assertNotEqual(room, "all")

	def test_queued_on_submit_is_published(self):
		"""Without this the pill can't show Queued - enqueue_taxjar_sync writes
		it directly, bypassing _set_sync_status."""
		doc = _make_doc()
		doc.db_set = MagicMock()

		with patch(f"{self.MOD}.company_creates_transactions", return_value=True), \
		     patch(f"{self.MOD}.get_client", return_value=MagicMock()), \
		     patch(f"{self.MOD}.frappe.enqueue"), \
		     patch(f"{self.MOD}.frappe.publish_realtime") as mock_publish:
			enqueue_taxjar_sync(doc, None)

		mock_publish.assert_called_once_with(
			"taxjar_transactions_update",
			{"name": doc.name, "taxjar_sync_status": "Queued"},
			room="doctype:Sales Invoice",
			after_commit=True,
		)

	def test_queued_on_cancel_is_published(self):
		doc = _make_doc()
		doc.db_set = MagicMock()

		with patch(f"{self.MOD}.company_creates_transactions", return_value=True), \
		     patch(f"{self.MOD}.get_client", return_value=MagicMock()), \
		     patch(f"{self.MOD}.frappe.enqueue"), \
		     patch(f"{self.MOD}.frappe.publish_realtime") as mock_publish:
			enqueue_taxjar_delete(doc, None)

		mock_publish.assert_called_once_with(
			"taxjar_transactions_update",
			{"name": doc.name, "taxjar_sync_status": "Queued"},
			room="doctype:Sales Invoice",
			after_commit=True,
		)

	def test_nothing_published_when_sync_is_skipped(self):
		doc = _make_doc()
		with patch(f"{self.MOD}.company_creates_transactions", return_value=False), \
		     patch(f"{self.MOD}.frappe.publish_realtime") as mock_publish:
			enqueue_taxjar_sync(doc, None)
		mock_publish.assert_not_called()

	def test_bulk_retry_publishes_queued(self):
		"""bulk_retry writes Queued with a targeted set_value rather than
		_set_sync_status (which would null taxjar_last_synced), so it needs its
		own publish."""
		page_mod = "taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions"
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import (
			bulk_retry,
		)

		with patch(f"{page_mod}.frappe.has_permission"), \
		     patch(f"{page_mod}.frappe.db.has_column", return_value=True), \
		     patch(f"{page_mod}.frappe.db.get_value", side_effect=_scalar_get_value("Failed")), \
		     patch(f"{page_mod}.frappe.db.set_value"), \
		     patch(f"{page_mod}.frappe.enqueue"), \
		     patch(f"{self.MOD}.frappe.publish_realtime") as mock_publish:
			result = bulk_retry(["SINV-0001"])

		self.assertEqual(result, {"queued": 1})
		mock_publish.assert_called_once_with(
			"taxjar_transactions_update",
			{"name": "SINV-0001", "taxjar_sync_status": "Queued"},
			room="doctype:Sales Invoice",
			after_commit=True,
		)

	def test_bulk_retry_skips_rows_that_are_not_failed(self):
		page_mod = "taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions"
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import (
			bulk_retry,
		)

		with patch(f"{page_mod}.frappe.has_permission"), \
		     patch(f"{page_mod}.frappe.db.has_column", return_value=True), \
		     patch(f"{page_mod}.frappe.db.get_value", side_effect=_scalar_get_value("Synced")), \
		     patch(f"{page_mod}.frappe.enqueue"), \
		     patch(f"{self.MOD}.frappe.publish_realtime") as mock_publish:
			bulk_retry(["SINV-0001"])

		mock_publish.assert_not_called()


class TestCustomersPageRealtime(UnitTestCase):

	MOD = "taxjar_integration.taxjar_integration.taxjar_integration"

	def test_publishes_doctype_room_event_with_name_and_status(self):
		with patch(f"{self.MOD}.frappe.db.set_value"), \
		     patch(f"{self.MOD}.frappe.publish_realtime") as mock_publish:
			_set_customer_sync_status("CUST-TEST-001", "Synced")

		mock_publish.assert_any_call(
			"taxjar_customers_update",
			{"name": "CUST-TEST-001", "taxjar_customer_sync_status": "Synced"},
			room="doctype:Customer",
			after_commit=True,
		)

	def test_get_summary_groups_and_respects_filters(self):
		"""Four groups - total, the exemption sync statuses, how many are
		explicitly non-exempt, and how many are still unconfigured - all scoped
		by the filters the table uses."""
		page_mod = "taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers"
		from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import get_summary

		rows = [
			frappe._dict(taxjar_customer_sync_status="Synced", cnt=12),
			frappe._dict(taxjar_customer_sync_status="Queued", cnt=1),
			frappe._dict(taxjar_customer_sync_status="Failed", cnt=1),
		]
		with patch(f"{page_mod}.frappe.has_permission"), patch(
			f"{page_mod}.frappe.db.has_column", return_value=True
		), patch(f"{page_mod}.frappe.get_list", return_value=rows) as mock_get_all, patch(
			f"{page_mod}.permitted_count", side_effect=[52, 6, 38]
		) as mock_count:
			result = get_summary(filters={"search": {"customer_group": "Commercial"}})

		self.assertEqual(result["total"], 52)
		self.assertEqual(result["exempt"], {"total": 14, "synced": 12, "queued": 1, "failed": 1})
		self.assertEqual(result["non_exempt"], 6)
		self.assertEqual(result["not_configured"], 38)

		# Every group carries the caller's filter, or the strip would describe
		# a different population than the table below it.
		self.assertEqual(mock_get_all.call_args[1]["filters"]["customer_group"], ("like", "%Commercial%"))
		for call in mock_count.call_args_list:
			self.assertEqual(call[0][1]["customer_group"], ("like", "%Commercial%"))

	def test_column_search_is_allowlisted_and_page_size_clamped(self):
		"""Both land in a database query from a whitelisted endpoint, so
		neither takes the client's word for it."""
		from taxjar_integration.taxjar_integration.pagination import PAGE_SIZE, parse_page_size
		from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import (
			_build_conditions,
		)

		self.assertEqual(parse_page_size(50), 50)
		self.assertEqual(parse_page_size(100000), PAGE_SIZE)
		self.assertEqual(parse_page_size("nonsense"), PAGE_SIZE)
		self.assertEqual(parse_page_size(None), PAGE_SIZE)

		conditions = _build_conditions(
			{"search": {"customer_name": "Acme", "taxjar_customer_sync_status": "x", "name": "y"}}
		)
		self.assertEqual(conditions["customer_name"], ("like", "%Acme%"))
		# Not on the allowlist - ignored rather than passed through to the query.
		self.assertNotIn("taxjar_customer_sync_status", conditions)
		self.assertNotIn("name", conditions)

	def test_tab_scopes_survive_a_null_column(self):
		"""The obvious spelling is a silent no-op. `x NOT IN ('', NULL)` is NULL
		for every row, so the Exempted tab matched nothing at all; `x IN ('',
		NULL)` never matches a real NULL, so Not Configured dropped any customer
		whose field was never written."""
		from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import (
			ALL_SCOPE,
			EXEMPT_SCOPE,
			NOT_CONFIGURED_SCOPE,
			_build_conditions,
		)

		exempt = _build_conditions({}, EXEMPT_SCOPE)["taxjar_exemption_type"]
		not_configured = _build_conditions({}, NOT_CONFIGURED_SCOPE)["taxjar_exemption_type"]

		self.assertNotIn(None, exempt[1])
		self.assertEqual(not_configured, ("is", "not set"))
		self.assertEqual(_build_conditions({}, ALL_SCOPE), {})

	def test_non_exempt_is_not_an_exemption(self):
		""""Non Exempt" is a configured answer, not an exemption -
		_customer_master_exemption() reads it the same way."""
		from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import (
			EXEMPT_SCOPE,
			_build_conditions,
		)

		self.assertIn("Non Exempt", _build_conditions({}, EXEMPT_SCOPE)["taxjar_exemption_type"][1])

	def test_non_exempt_scope_matches_only_non_exempt(self):
		"""Its own tab, scoped to exactly the value Exempted excludes."""
		from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import (
			NON_EXEMPT_SCOPE,
			_build_conditions,
		)

		self.assertEqual(_build_conditions({}, NON_EXEMPT_SCOPE)["taxjar_exemption_type"], "Non Exempt")

	def test_never_synced_filter_also_survives_a_null_column(self):
		"""Same trap, same fix - the sync status column is NULL until the first
		sync writes to it."""
		from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import (
			_build_conditions,
		)

		conditions = _build_conditions({"sync_status": "__not_set"})
		self.assertEqual(conditions["taxjar_customer_sync_status"], ("is", "not set"))

	def test_configure_exemption_drops_regions_when_type_is_cleared(self):
		"""An exempt region without a type is meaningless - keeping it would
		leave rows no screen could ever show again."""
		page_mod = "taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers"
		from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import (
			configure_exemption,
		)
		doc = MagicMock()

		with patch(f"{page_mod}.frappe.has_permission"), patch(
			f"{page_mod}._ensure_taxjar_customer_fields"
		), patch(f"{page_mod}.frappe.get_doc", return_value=doc):
			configure_exemption(["CUST-0001"], "", [{"country": "US", "state": "TX"}])

		doc.set.assert_called_once_with("taxjar_exempt_regions", [])
		doc.append.assert_not_called()
		self.assertEqual(doc.taxjar_exemption_type, "")

	def test_bulk_sync_publishes_queued(self):
		page_mod = "taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers"
		from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import (
			bulk_sync_to_taxjar,
		)
		settings = MagicMock()
		settings.company_config = []

		with patch(f"{page_mod}.frappe.has_permission"), \
		     patch(f"{page_mod}._ensure_taxjar_customer_fields"), \
		     patch(f"{page_mod}.frappe.db.get_value", side_effect=_scalar_get_value("cust_1")), \
		     patch(f"{page_mod}.frappe.db.set_value"), \
		     patch(f"{page_mod}.frappe.get_single", return_value=settings), \
		     patch(f"{self.MOD}.frappe.publish_realtime") as mock_publish:
			bulk_sync_to_taxjar(["CUST-0001"])

		mock_publish.assert_called_once_with(
			"taxjar_customers_update",
			{"name": "CUST-0001", "taxjar_customer_sync_status": "Queued"},
			room="doctype:Customer",
			after_commit=True,
		)


class TestSyncStatusRealtimeJS(UnitTestCase):

	def _js_dir(self):
		import os
		return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "public", "js"))

	def _read_js(self, filename):
		import os
		with open(os.path.join(self._js_dir(), filename)) as f:
			return f.read()

	def test_sales_invoice_registers_listener_in_setup_not_refresh(self):
		"""setup(frm) runs once per form load; refresh(frm) reruns
		repeatedly (every save, tab switch back) and would stack duplicate
		frappe.realtime.on() listeners if used instead."""
		js = self._read_js("sales_invoice.js")
		setup_fn = js.split("setup(frm) {")[1].split("\n\t},")[0]
		self.assertIn('frappe.realtime.on("taxjar_invoice_sync_update"', setup_fn)
		self.assertIn("frm.reload_doc()", setup_fn)

	def test_customer_registers_listener_in_setup_not_refresh(self):
		js = self._read_js("customer.js")
		setup_fn = js.split("setup(frm) {")[1].split("\n\t},")[0]
		self.assertIn('frappe.realtime.on("taxjar_customer_sync_update"', setup_fn)
		self.assertIn("frm.reload_doc()", setup_fn)

	def test_setup_appears_before_refresh_in_sales_invoice(self):
		js = self._read_js("sales_invoice.js")
		self.assertLess(js.index("setup(frm) {"), js.index("refresh(frm) {"))

	def test_customer_card_reports_the_master_not_the_override(self):
		"""A transaction override used to flip this to "No", hiding that the
		customer themselves is taxable and only this one sale is not."""
		import inspect
		from taxjar_integration.taxjar_integration.taxjar_integration import set_sales_tax

		source = inspect.getsource(set_sales_tax)
		self.assertIn("customer_exemption_type = _get_customer_exemption_type(doc)", source)
		self.assertIn("customer_taxable = not customer_exemption_type", source)
		self.assertIn('"Taxable, but transaction is marked as exempt"', source)
		# The old override wording is what the card now appends instead.
		self.assertNotIn('f"Overridden ({exemption_type})"', source)

	def test_effective_exemption_precedence_is_unchanged(self):
		"""The card is display only - what actually reaches TaxJar still puts
		the customer master ahead of the per-transaction override."""
		import inspect
		from taxjar_integration.taxjar_integration.taxjar_integration import _get_effective_exemption

		source = inspect.getsource(_get_effective_exemption)
		self.assertIn('return customer_exemption_type, "customer"', source)
		self.assertIn('return transaction_exemption_type, "transaction"', source)

	def test_region_exemption_matches_on_destination_state(self):
		mod = "taxjar_integration.taxjar_integration.taxjar_integration"
		from taxjar_integration.taxjar_integration.taxjar_integration import get_region_exemption

		def lookup(regions, dest_state, exemption_type="Wholesale"):
			def get_value(doctype, name, fieldname=None, **kwargs):
				if doctype == "Customer":
					return exemption_type
				return frappe._dict(taxjar_state_code=dest_state, state=dest_state)

			with patch(f"{mod}.frappe.has_permission"), \
			     patch(f"{mod}.frappe.db.has_column", return_value=True), \
			     patch(f"{mod}.frappe.db.get_value", side_effect=get_value), \
			     patch(f"{mod}.frappe.db.exists", return_value=True), \
			     patch(f"{mod}.frappe.get_all", return_value=[frappe._dict(state=r) for r in regions]):
				return get_region_exemption("CUST-0001", "ADDR-0001")

		self.assertEqual(lookup(["FL"], "FL")["exemption_type"], "Wholesale")
		# Exempt in Florida says nothing about a sale shipped to New Jersey.
		self.assertEqual(lookup(["FL"], "NJ"), {})
		# Case and padding come from free-text address fields.
		self.assertEqual(lookup([" fl "], "FL")["exemption_type"], "Wholesale")
		# No regions listed at all is how TaxJar reads "exempt everywhere".
		self.assertEqual(lookup([], "NJ"), {"exemption_type": "Wholesale", "state": None})
		# "Non Exempt" is a real master value meaning not exempt.
		self.assertEqual(lookup(["FL"], "FL", exemption_type="Non Exempt"), {})

	def test_permission_check_is_scoped_to_the_requested_customer(self):
		"""A doctype-level "can read Customer" check is not enough here: a user
		with general Customer read access but no user-permission grant for this
		specific record must not learn its exemption_type/regions through this
		endpoint. has_permission must be record-scoped (doc=customer), not just
		checked against the Customer doctype in the abstract."""
		mod = "taxjar_integration.taxjar_integration.taxjar_integration"
		from taxjar_integration.taxjar_integration.taxjar_integration import get_region_exemption

		with patch(f"{mod}.frappe.has_permission") as mock_has_permission, \
		     patch(f"{mod}._customer_master_exemption", return_value=(None, None)):
			get_region_exemption("CUST-0001", "ADDR-0001")

		mock_has_permission.assert_called_once_with("Customer", "read", doc="CUST-0001", throw=True)

	def test_customer_exemption_is_region_scoped(self):
		"""A customer exempt only in Florida is not exempt on a New Jersey
		sale. This feeds both the status card and, through
		_get_effective_exemption, the exemption_type sent to TaxJar."""
		mod = "taxjar_integration.taxjar_integration.taxjar_integration"
		from taxjar_integration.taxjar_integration.taxjar_integration import (
			_get_customer_exemption_type,
		)

		def master_for(dest_state, regions=("FL",)):
			def get_value(doctype, name, fieldname=None, **kwargs):
				if doctype == "Customer":
					return "Wholesale"
				return frappe._dict(taxjar_state_code=dest_state, state=dest_state)

			doc = frappe._dict(
				doctype="Sales Invoice", customer="CUST-0001",
				shipping_address_name="ADDR-0001", customer_address=None,
			)
			with patch(f"{mod}.frappe.db.has_column", return_value=True), \
			     patch(f"{mod}.frappe.db.get_value", side_effect=get_value), \
			     patch(f"{mod}.frappe.db.exists", return_value=True), \
			     patch(f"{mod}.frappe.get_all", return_value=[frappe._dict(state=r) for r in regions]):
				return _get_customer_exemption_type(doc)

		self.assertEqual(master_for("FL"), "Wholesale")
		self.assertIsNone(master_for("NJ"))
		# No regions listed is exempt everywhere, matching TaxJar.
		self.assertEqual(master_for("NJ", regions=()), "Wholesale")

	def test_out_of_region_lets_the_transaction_override_apply(self):
		"""The bug this closes: an FL-only customer exemption used to win
		precedence on a NJ sale, so a user ticking the per-transaction override
		there had it silently ignored and never sent to TaxJar."""
		mod = "taxjar_integration.taxjar_integration.taxjar_integration"
		from taxjar_integration.taxjar_integration.taxjar_integration import _get_effective_exemption

		doc = frappe._dict(
			taxjar_transaction_exempt=1, taxjar_transaction_exemption_type="Government",
		)
		with patch(f"{mod}._get_customer_exemption_type", return_value=None):
			self.assertEqual(_get_effective_exemption(doc), ("Government", "transaction"))

		# In a covered region the master still wins, as TaxJar documents.
		with patch(f"{mod}._get_customer_exemption_type", return_value="Wholesale"):
			self.assertEqual(_get_effective_exemption(doc), ("Wholesale", "customer"))

	def test_unreadable_destination_keeps_the_standing_exemption(self):
		"""Better to keep honouring a customer's exemption than to start taxing
		them because an address is missing a state."""
		mod = "taxjar_integration.taxjar_integration.taxjar_integration"
		from taxjar_integration.taxjar_integration.taxjar_integration import (
			_customer_master_exemption,
		)
		with patch(f"{mod}.frappe.db.has_column", return_value=True), \
		     patch(f"{mod}.frappe.db.get_value", side_effect=_scalar_get_value("Wholesale")), \
		     patch(f"{mod}.frappe.db.exists", return_value=False), \
		     patch(f"{mod}.frappe.get_all", return_value=[frappe._dict(state="FL")]):
			self.assertEqual(_customer_master_exemption("CUST-0001", None), ("Wholesale", None))

	def test_sourcing_cue_reaches_all_three_transaction_doctypes(self):
		"""The cue is one shared implementation, not three: render_addresses
		lives in taxjar_utils.js and every form script calls it, the field comes
		from _make_status_fields which all three doctypes spread in, and
		set_sales_tax is registered for all three in doc_events.

		Guarded because the natural way to "add it to Quotation and Sales Order"
		is to copy the render into each form script, and then the next change to
		the cue only lands on whichever copy the author remembered.
		"""
		import inspect

		from taxjar_integration import hooks
		from taxjar_integration.taxjar_integration.doctype.taxjar_settings import taxjar_settings
		from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
			_make_status_fields,
		)

		# One definition of the field...
		self.assertIn(
			"taxjar_tax_source",
			[f["fieldname"] for f in _make_status_fields("taxjar_tab")],
		)
		# ...spread into each doctype's list. get_custom_fields() is pure - it
		# builds the dict without writing anything - so this can assert against
		# the real field lists rather than the source text.
		status_fieldnames = {f["fieldname"] for f in _make_status_fields("taxjar_tab")}
		custom_fields = taxjar_settings.get_custom_fields()
		for doctype in ("Quotation", "Sales Order", "Sales Invoice"):
			with self.subTest(doctype=doctype):
				present = {f["fieldname"] for f in custom_fields[doctype]}
				self.assertTrue(status_fieldnames <= present)

		# One validate hook writing it, covering all three.
		validate_targets = [
			key for key, events in hooks.doc_events.items()
			if any(
				"set_sales_tax" in handler
				for handler in (
					events.get("validate", [])
					if isinstance(events.get("validate"), list)
					else [events.get("validate") or ""]
				)
			)
		]
		self.assertEqual(len(validate_targets), 1, "set_sales_tax must be registered once")
		for doctype in ("Quotation", "Sales Order", "Sales Invoice"):
			self.assertIn(doctype, validate_targets[0])

		# One renderer, called by each form script rather than reimplemented.
		utils = self._read_js("taxjar_utils.js")
		self.assertIn("taxjar_integration.render_addresses = function (frm) {", utils)
		for filename in ("quotation.js", "sales_order.js", "sales_invoice.js"):
			with self.subTest(filename=filename):
				form_js = self._read_js(filename)
				self.assertIn("taxjar_integration.render_addresses(frm);", form_js)
				self.assertNotIn("taxjar-address", form_js)
				self.assertNotIn("taxjar_tax_source", form_js)

	def test_addresses_row_captions_the_end_that_sourced_the_rate(self):
		"""Origin marks Ship From, destination marks Ship To - not the reverse.

		The tint alone says "this one" without saying why, so the rule is named
		inside the box it applies to: one thing to read, and nothing at all on
		the side that didn't source the rate.
		"""
		js = self._read_js("taxjar_utils.js")
		fn = js.split("taxjar_integration.render_addresses = function (frm) {")[1].split("\n};")[0]

		self.assertIn('cell(__("Ship From"), from_text, origin ? __("Origin based tax") : "")', fn)
		self.assertIn('cell(__("Ship To"), to_text, destination ? __("Destination based tax") : "")', fn)
		# One argument drives both the tint and the caption - they cannot
		# disagree, and there is no side with a caption but no box.
		self.assertIn('<div class="taxjar-address${note ? " taxjar-address-lit" : ""}">', fn)
		# Brackets in the markup, not inside __() - the translator gets the
		# phrase, not punctuation to reproduce.
		self.assertIn('${note ? `<div class="taxjar-address-note">(${note})</div>` : ""}', fn)
		self.assertNotIn('__("(', fn)
		# No separate legend to read across to.
		self.assertNotIn("taxjar-address-swatch", js)
		self.assertNotIn("taxjar-address-legend", js)

	def test_addresses_row_is_a_flat_flex_row(self):
		"""Three children, in order, no wrappers - so nothing has to be placed
		by hand. The grid this briefly used needed every child to name its own
		row AND column: auto-placement runs items locked to a row before
		auto-flowed ones, so an arrow at "grid-row: 1" with no column took
		column 1 and shunted both addresses one column right. With the caption
		back inside its box there is no second row to line up against, so the
		grid bought nothing and cost that.
		"""
		js = self._read_js("taxjar_utils.js")
		styles = js.split("taxjar_integration._inject_status_card_styles = function () {")[1].split("\n};")[0]
		block = styles.split(".taxjar-addresses {")[1]

		self.assertIn(".taxjar-addresses { display: flex;", styles)
		self.assertNotIn("grid", block)
		self.assertIn("flex: 1;", styles.split(".taxjar-address {")[1].split("}")[0])

	def test_address_caption_is_muted_and_the_box_carries_the_colour(self):
		"""The tinted box is the signal; the caption inside it is its label.
		Colouring the caption too would read as a second signal rather than as
		the words for the one already there.

		Both cells carry a transparent border of the same width, so tinting one
		shifts nothing. --bg-blue / --text-on-blue are frappe's own
		indicator-pill tokens (indicator.scss), redefined per theme - no hex of
		ours, and clear of the green/orange/grey verdict pills on the cards
		above.
		"""
		js = self._read_js("taxjar_utils.js")
		styles = js.split("taxjar_integration._inject_status_card_styles = function () {")[1].split("\n};")[0]

		lit = styles.split(".taxjar-address-lit {")[1].split("}")[0]
		self.assertIn("background: var(--bg-blue);", lit)
		self.assertIn("border-color: var(--text-on-blue);", lit)

		# --text-light (ink-gray-5) is a step lighter than the --text-muted
		# (ink-gray-6) used by the "Ship To" label above it, so the caption
		# reads as subordinate to the label rather than competing with it.
		note = styles.split(".taxjar-address-note {")[1].split("}")[0]
		self.assertIn("color: var(--text-light);", note)
		self.assertNotIn("blue", note)

		cell = styles.split(".taxjar-address {")[1].split("}")[0]
		self.assertIn("border: 1px dashed transparent;", cell)
		# --radius-md, not --border-radius-md: this frappe ships the Espresso
		# --radius-* scale and never defines the old aliases, so the deprecated
		# name resolves to nothing and the corners render square.
		self.assertIn("border-radius: var(--radius-md);", cell)
		# var( so the rule's own explanatory comment doesn't trip this.
		self.assertNotIn("var(--border-radius-", styles.split(".taxjar-addresses {")[1])

		# No fixed colours anywhere in this block - it has to follow the theme.
		self.assertNotIn("#", styles.split(".taxjar-addresses {")[1])

	def test_addresses_row_ignores_a_stale_tax_source_without_nexus(self):
		"""set_sales_tax has early returns that stop before calculating (no
		nexus, exempt, no payload) and none of them clear the stored fields, so
		a document that was taxed once would otherwise keep showing a pill for a
		rule that no longer applies. Gating on nexus also means a null
		tax_source needs no "unknown" state - neither side is tinted or
		captioned, and the row reads exactly as it did before this existed.
		"""
		js = self._read_js("taxjar_utils.js")
		fn = js.split("taxjar_integration.render_addresses = function (frm) {")[1].split("\n};")[0]
		self.assertIn(
			'const source = frm.doc.taxjar_has_nexus ? (frm.doc.taxjar_tax_source || "") : "";', fn
		)

	def test_region_exemption_locks_and_fills_the_override(self):
		js = self._read_js("taxjar_utils.js")
		fn = js.split("taxjar_integration.apply_region_exemption = function (frm) {")[1].split("\n};")[0]

		# Ship-to first, bill-to as fallback - the same order the server uses.
		self.assertIn("frm.doc.shipping_address_name || frm.doc.customer_address", fn)
		self.assertIn('frm.set_df_property(f, "read_only", 1)', fn)
		self.assertIn('frm.set_value("taxjar_transaction_exempt", 1)', fn)
		# Only on a draft, and only when it would actually change something:
		# set_value on an unchanged field still dirties the form.
		self.assertIn("if (frm.doc.docstatus !== 0) return;", fn)
		self.assertIn("if (!cint(frm.doc.taxjar_transaction_exempt))", fn)

		for name in ("sales_invoice.js", "sales_order.js", "quotation.js"):
			with self.subTest(js=name):
				form_js = self._read_js(name)
				# Re-evaluated when either address changes, not only on load.
				self.assertIn("shipping_address_name(frm) {", form_js)
				self.assertIn("customer_address(frm) {", form_js)
				self.assertGreaterEqual(form_js.count("apply_region_exemption(frm)"), 3)

	def test_overridden_pill_is_gone(self):
		"""Its job moved into the card 2 answer itself."""
		js = self._read_js("taxjar_utils.js")
		self.assertNotIn("Overridden", js)
		self.assertNotIn("taxjar-status-card-override", js)
		fn = js.split("taxjar_integration.render_status_cards = function (frm) {")[1].split("\n};")[0]
		self.assertIn('__("Yes, but transaction is marked as exempt")', fn)

	def test_only_the_sentence_answer_opts_into_wrapping(self):
		"""frappe.ui.badge (es-badge) defaults to nowrap/fit-content with a
		fixed one-line height, overflow: clip, a stadium border-radius and
		line-height: 1, all tuned for one line of text - fine for single
		words, but "Yes, but transaction is marked as exempt" needs to wrap
		inside the card instead of overflowing it. White-space alone lets the
		text wrap onto a second line while the rest of the base rule still
		fights it: fixed height + clip crop the second line outside the
		pill's own background, the stadium corners (meant for a short single
		line) curve in close enough to crowd wrapped text against them, and
		line-height: 1 leaves the two lines touching. min-height (not height)
		keeps single-line badges the same size they always were - the corner
		and line-height relaxations are applied unconditionally too since
		they look identical on a single-line badge either way. Scoped to
		badges inside the status cards generally (every card answer goes
		through the same frappe.ui.badge.html() call, so there's no separate
		"wrap" flag to set per card any more)."""
		js = self._read_js("taxjar_utils.js")
		styles = js.split("_inject_status_card_styles = function () {")[1].split("\n};")[0]

		self.assertIn(".taxjar-status-card-a .es-badge {", styles)
		rule = styles.split(".taxjar-status-card-a .es-badge {")[1].split("}")[0]
		self.assertIn("white-space: normal;", rule)
		self.assertIn("height: auto;", rule)
		self.assertIn("overflow: visible;", rule)
		self.assertIn("min-height:", rule)
		self.assertIn("border-radius: var(--radius-lg);", rule)
		self.assertIn("line-height: 1.4;", rule)

		# The old opt-in wrap class and its indicator-pill-specific fixes are
		# gone entirely, not just renamed.
		self.assertNotIn("taxjar-pill-wrap", js)
		# No more .indicator-pill selector - a nearby comment about the
		# address cells' own --bg-blue/--text-on-blue tokens still legitimately
		# mentions "indicator-pill" in prose, so check for the CSS selector
		# itself, not the bare word.
		self.assertNotIn(".indicator-pill", styles)

		# Every card answer renders through the same badge call, sentence or not.
		render_fn = js.split("taxjar_integration.render_status_cards = function (frm) {")[1].split("\n};")[0]
		self.assertIn(
			"frappe.ui.badge.html({ label: card.answer, theme: card.color })", render_fn
		)

	def test_breakdown_field_label_block_is_collapsed(self):
		"""The field has no label - the section heading names it - but frappe
		renders the label block anyway and only hides it on request
		(base_input.js:22-25), leaving an empty row of whitespace above the
		table."""
		js = self._read_js("taxjar_utils.js")
		fn = js.split("taxjar_integration.render_tax_breakdown = function (frm) {")[1].split("\n};")[0]
		self.assertIn("toggle_label?.(false)", fn)
		# After refresh_field, which re-renders the value beneath it.
		self.assertLess(fn.index("refresh_field"), fn.index("toggle_label"))

	def test_no_nexus_empty_state_explains_itself(self):
		"""With no nexus there is no breakdown and never will be, so the empty
		state says why instead of reporting an absence the user cannot act on.

		Asserts the wiring rather than rendering: get_template() needs the app
		installed on the site under test, which is what the environmental
		errors in this module are about.
		"""
		from taxjar_integration.taxjar_integration.taxjar_integration import (
			get_taxjar_breakdown_html,
		)
		mod = "taxjar_integration.taxjar_integration.taxjar_integration"

		def context_for(**extra):
			doc = frappe._dict(taxjar_breakdown_json=None, currency="USD", **extra)
			with patch(f"{mod}.frappe.render_template", return_value="") as mock_render:
				get_taxjar_breakdown_html(doc)
			return mock_render.call_args[0][1]

		self.assertEqual(
			context_for(taxjar_has_nexus=0, taxjar_nexus_reason="No nexus in NJ")["no_nexus_reason"],
			"No nexus in NJ",
		)
		# has_nexus is 0 both for "no nexus" and "never assessed", so the reason
		# is what tells them apart - neither of these should claim no nexus.
		self.assertIsNone(
			context_for(taxjar_has_nexus=1, taxjar_nexus_reason="Nexus in CA")["no_nexus_reason"]
		)
		self.assertIsNone(context_for()["no_nexus_reason"])

	def test_breakup_template_has_the_no_nexus_branch(self):
		import os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "..",
			"templates", "includes", "taxjar_breakup.html",
		))
		with open(path) as f:
			template = f.read()
		self.assertIn("{% if no_nexus_reason %}", template)
		self.assertIn('_("{0}, hence no taxes are charged.").format(no_nexus_reason)', template)
		# The generic message survives for the has-nexus-but-no-data case.
		self.assertIn("No TaxJar tax breakdown available for this transaction.", template)

	def test_shipping_taxability_pill_hidden_without_nexus(self):
		"""Nothing is taxed without a nexus, so the pill would answer a question
		that does not arise."""
		js = self._read_js("taxjar_utils.js")

		guard = js.split("taxjar_integration._has_no_nexus = function (frm) {")[1].split("\n};")[0]
		# has_nexus alone is 0 both for "no nexus" and "not evaluated yet".
		self.assertIn("Boolean(frm.doc.taxjar_nexus_reason) && !frm.doc.taxjar_has_nexus", guard)

		fn = js.split("taxjar_integration.render_shipping_taxability = function (frm) {")[1].split("\n};")[0]
		self.assertIn("taxjar_integration._has_no_nexus(frm)", fn)
		# The wrapper is hidden, not just emptied: an empty field still holds
		# its own margins and leaves a blank band above the breakdown.
		self.assertIn("wrapper.empty().hide()", fn)
		self.assertIn("wrapper.show().html(", fn)

		# The client fallback empty state matches what the server template renders.
		msg_fn = js.split("taxjar_integration._no_breakdown_msg = function (is_new, frm) {")[1].split("\n};")[0]
		self.assertIn('__("{0}, hence no taxes are charged."', msg_fn)

	def test_only_one_copy_of_the_tax_message_is_shown(self):
		"""Layout.show_message() appends and only clears when passed nothing
		(layout.js:132-164), while refresh() runs more than once per form load -
		so calling it directly stacked a duplicate strip each pass. Only our own
		block is replaced: emptying the container would take frappe's own
		messages ("Submit this document to confirm") with it."""
		js = self._read_js("taxjar_utils.js")
		setter = js.split("taxjar_integration._set_tax_message = function (frm, text, color) {")[1].split("\n};")[0]
		self.assertIn("$container.find(`.${TAXJAR_MESSAGE_CLASS}`).remove()", setter)
		self.assertIn("$container.children().last().addClass(TAXJAR_MESSAGE_CLASS)", setter)
		# Hidden only once nothing at all is left in there.
		self.assertIn('if (!$container.children().length) $container.addClass("hidden")', setter)

		# Every branch goes through the setter, or one of them stacks again.
		fn = js.split("taxjar_integration.show_no_address_tax_message = function (frm) {")[1].split("\n};")[0]
		self.assertNotIn("frm.layout.show_message(", fn)

	def test_no_address_message_has_a_create_address_link(self):
		"""The "no address" warning must give the user a way out, not just
		state the problem - a hyperlink straight into a prefilled Address
		form, linked to this customer via the same helper the shipping-
		address picker's own "Add New Address" action already uses."""
		js = self._read_js("taxjar_utils.js")
		fn = js.split("taxjar_integration.show_no_address_tax_message = function (frm) {")[1].split("\n};")[0]
		self.assertIn("Customer Address is not set, hence taxes are not calculated.", fn)
		self.assertIn('class="taxjar-create-address-link"', fn)
		self.assertIn("taxjar_integration._open_new_address(frm)", fn)

	def test_setup_appears_before_refresh_in_customer(self):
		js = self._read_js("customer.js")
		self.assertLess(js.index("setup(frm) {"), js.index("refresh(frm) {"))


# ── Desk page lifecycle: on_page_show + realtime binding ───────────────────
# Desk pages are constructed once and cached in frappe.pages[name]; revisiting
# the route only un-hides the existing DOM and fires on_page_show, so a page
# that fetches solely in on_page_load shows stale data until a browser reload.
# The constructor must NOT fetch: the "show" handler is bound before
# container.change_to() runs, so on_page_show already fires immediately after
# on_page_load and doing both would double-fetch on every load.

class TestDeskPageLifecycleJS(UnitTestCase):

	PAGES = ("taxjar_transactions", "taxjar_customers", "taxjar_setup")
	# The two data pages that also carry a realtime subscription.
	REALTIME_PAGES = {
		"taxjar_transactions": ("Sales Invoice", "taxjar_transactions_update"),
		"taxjar_customers": ("Customer", "taxjar_customers_update"),
	}

	def _read_page_js(self, page):
		import os
		path = os.path.join(
			os.path.dirname(__file__), "..", "..", "page", page, f"{page}.js"
		)
		with open(os.path.normpath(path)) as f:
			return f.read()

	def test_every_page_defines_on_page_show(self):
		for page in self.PAGES:
			with self.subTest(page=page):
				js = self._read_page_js(page)
				self.assertIn(f'frappe.pages["{page.replace("_", "-")}"].on_page_show', js)

	def test_constructor_does_not_fetch(self):
		"""Would double-fetch on first load, since on_page_show fires right
		after on_page_load."""
		for page, fetch_call in (
			("taxjar_transactions", "this.refresh();"),
			("taxjar_customers", "this.refresh();"),
			("taxjar_setup", "this._load_state();"),
		):
			with self.subTest(page=page):
				js = self._read_page_js(page)
				constructor = js.split("\tconstructor(page) {")[1].split("\n\t}")[0]
				self.assertNotIn(fetch_call, constructor)

	def test_realtime_pages_subscribe_and_refresh_on_show(self):
		for page, (doctype, event) in self.REALTIME_PAGES.items():
			with self.subTest(page=page):
				js = self._read_page_js(page)
				on_show = js.split("\ton_show() {")[1].split("\n\t}")[0]
				self.assertIn(f'frappe.realtime.doctype_subscribe("{doctype}")', on_show)
				self.assertIn("frappe.realtime.on(SYNC_UPDATE_EVENT", on_show)
				self.assertIn("this.refresh();", on_show)
				self.assertIn(f'SYNC_UPDATE_EVENT = "{event}"', js)

	def test_realtime_pages_detach_handler_on_hide(self):
		"""Same handler reference passed to on() and off(), or the listener
		stays live and keeps refreshing a page the user has navigated away
		from. Deliberately no doctype_unsubscribe - the Sales Invoice list
		view shares the room and only sets itself up once."""
		for page in self.REALTIME_PAGES:
			with self.subTest(page=page):
				js = self._read_page_js(page)
				on_hide = js.split("\ton_hide() {")[1].split("\n\t}")[0]
				self.assertIn("frappe.realtime.off(SYNC_UPDATE_EVENT, this._on_sync_update)", on_hide)
				self.assertIn("this._on_sync_update.cancel()", on_hide)
				self.assertNotIn("doctype_unsubscribe", on_hide)

	def test_realtime_handler_is_debounced_and_stored_once(self):
		"""A bulk retry publishes one event per row; without a debounce each
		would cost a full two-call refresh."""
		for page in self.REALTIME_PAGES:
			with self.subTest(page=page):
				js = self._read_page_js(page)
				self.assertIn(
					"this._on_sync_update = frappe.utils.debounce(() => this.refresh(), 500);", js
				)

	def test_pages_bind_hide_to_release_the_listener(self):
		for page in self.REALTIME_PAGES:
			with self.subTest(page=page):
				js = self._read_page_js(page)
				self.assertIn('$(wrapper).on("hide"', js)


# ── "Not Applicable" → "Excluded" ──────────────────────────────────────────
# "Not Applicable" read as though TaxJar had no opinion about the invoice, when
# it means the opposite: TaxJar was asked and the transaction was deliberately
# kept out of it.

class TestExcludedRename(UnitTestCase):

	PATCH = "taxjar_integration.patches.rename_not_applicable_sync_status"

	def test_patch_rewrites_the_stored_values(self):
		from taxjar_integration.patches.rename_not_applicable_sync_status import execute

		with patch(f"{self.PATCH}.frappe.db.has_column", return_value=True), patch(
			f"{self.PATCH}.frappe.db.sql"
		) as mock_sql:
			execute()

		sql = mock_sql.call_args[0][0]
		self.assertIn("`tabSales Invoice`", sql)
		self.assertIn("taxjar_sync_status = 'Excluded'", sql)
		self.assertIn("WHERE taxjar_sync_status = 'Not Applicable'", sql)

	def test_patch_is_a_no_op_without_the_column(self):
		"""A site that installed the app but never enabled a TaxJar feature has
		no taxjar_* columns; reading one raises MySQLdb (1054)."""
		from taxjar_integration.patches.rename_not_applicable_sync_status import execute

		with patch(f"{self.PATCH}.frappe.db.has_column", return_value=False), patch(
			f"{self.PATCH}.frappe.db.sql"
		) as mock_sql:
			execute()

		mock_sql.assert_not_called()

	def test_patch_is_registered(self):
		import os
		path = os.path.normpath(
			os.path.join(os.path.dirname(__file__), "..", "..", "..", "patches.txt")
		)
		with open(path) as f:
			self.assertIn("taxjar_integration.patches.rename_not_applicable_sync_status", f.read())

	def test_delete_marks_the_invoice_excluded(self):
		"""Removing a transaction from TaxJar is exactly the excluded state."""
		import inspect

		from taxjar_integration.taxjar_integration.taxjar_integration import delete_transaction_manual

		self.assertIn('_set_sync_status(invoice_name, "Excluded")', inspect.getsource(delete_transaction_manual))

	def test_no_stale_not_applicable_status_value_in_source(self):
		"""Guards the stored status, not the words.

		"Not Applicable" is still live vocabulary on the page - the summary card
		under the Excluded heading, and the drill-down that picks that half of
		the Excluded tab - so a plain string search reports those as leftovers.
		What must never come back is the old *status value*, so the rule is that
		no line may mention both the string and taxjar_sync_status: that catches
		an assignment, a comparison, or a _set_sync_status() call, and leaves the
		labels alone.
		"""
		import os
		root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
		for sub, exts in (("public/js", (".js",)), ("taxjar_integration", (".py", ".js"))):
			for dirpath, _dirs, files in os.walk(os.path.join(root, sub)):
				if "dist" in dirpath or "__pycache__" in dirpath:
					continue
				for name in files:
					if not name.endswith(exts) or name.startswith("test_"):
						continue
					# The patch is the one place that must still name the old value.
					if name == "rename_not_applicable_sync_status.py":
						continue
					path = os.path.join(dirpath, name)
					with open(path) as f:
						lines = f.read().splitlines()
					for number, line in enumerate(lines, 1):
						if "Not Applicable" not in line:
							continue
						with self.subTest(path=path, line=number):
							self.assertNotIn("sync_status", line)


# ── Desk page chrome: tabs, bulk action, summary strip ─────────────────────
# Both pages are built on frappe's own primitives (frappe.DataTable,
# frappe.ui.FieldGroup tabs, frappe.utils.build_summary_item) via thin wrappers
# in public/js/components. Nothing is imported from india_compliance: it lives
# in this bench but is installed on no site, so a reference to it would be
# undefined at runtime.

class TestDeskPageChromeJS(UnitTestCase):

	TABBED_PAGES = ("taxjar_transactions", "taxjar_customers")

	def _read_page_js(self, page):
		import os
		path = os.path.join(os.path.dirname(__file__), "..", "..", "page", page, f"{page}.js")
		with open(os.path.normpath(path)) as f:
			return f.read()

	def _read_component(self, name):
		import os
		path = os.path.join(
			os.path.dirname(__file__), "..", "..", "..", "public", "js", "components", f"{name}.js"
		)
		with open(os.path.normpath(path)) as f:
			return f.read()

	def test_no_dependency_on_india_compliance(self):
		"""india_compliance is in this bench but installed on no site, so any
		reference to its namespace would be undefined at runtime."""
		import os
		js_dir = os.path.normpath(
			os.path.join(os.path.dirname(__file__), "..", "..", "..", "public", "js")
		)
		sources = [self._read_page_js(p) for p in ("taxjar_transactions", "taxjar_customers")]
		for root, _dirs, files in os.walk(js_dir):
			if "dist" in root:
				continue
			sources += [open(os.path.join(root, f)).read() for f in files if f.endswith(".js")]

		for source in sources:
			self.assertNotIn("india_compliance.", source)

	def test_pages_use_the_shared_components(self):
		for page in self.TABBED_PAGES:
			with self.subTest(page=page):
				js = self._read_page_js(page)
				self.assertIn("taxjar_integration.SummaryStrip", js)
				self.assertIn("taxjar_integration.BulkActionButton", js)

	def test_transactions_uses_the_data_table(self):
		"""Only Transaction Sync. The Customer page renders a plain bordered
		table - see TestCustomerConfigPageJS."""
		self.assertIn("taxjar_integration.DataTableManager", self._read_page_js("taxjar_transactions"))

	def test_select_all_is_the_datatable_header_checkbox(self):
		"""checkboxColumn puts a select-all in the header, which is where the
		Transaction Sync page's own "Select All" button went."""
		data_table = self._read_component("data_table_manager")
		self.assertIn("checkboxColumn: true", data_table)
		js = self._read_page_js("taxjar_transactions")
		self.assertNotIn("taxjar-select-all", js)
		self.assertNotIn('__("Select All")', js)

	def test_tabs_use_the_espresso_component_not_a_form_fieldgroup(self):
		"""Both pages used to draw their tabs via a frappe.ui.FieldGroup of
		Tab Break fields - a form-layout mechanism that needed `parent:` and
		`hidden: false` workarounds just to avoid frappe splicing in its own
		"Details" tab and crashing on an undefined frm.doctype. frappe.ui.Tabs
		needs none of that: no FieldGroup, no Tab Break fields, no Section
		Break-triggered "first visible field" footgun."""
		for page in self.TABBED_PAGES:
			with self.subTest(page=page):
				js = self._read_page_js(page)
				# The construction itself is gone; the class name may still
				# appear in a comment explaining what replaced it.
				self.assertNotIn("new frappe.ui.FieldGroup(", js)
				self.assertNotIn('fieldtype: "Tab Break"', js)
				self.assertIn("new frappe.ui.Tabs({", js)
				tabs_block = js.split("new frappe.ui.Tabs({")[1].split("});")[0]
				self.assertIn("tabs: TABS.map((tab) => ({", tabs_block)

	def test_each_tab_lazily_builds_and_caches_its_own_content_wrapper(self):
		"""content is a function so each tab's table wrapper is only ever
		built once, the first time that tab is activated - mirroring the
		lazy build-once-per-tab pattern this page already used before the
		FieldGroup hack was removed."""
		for page in self.TABBED_PAGES:
			with self.subTest(page=page):
				js = self._read_page_js(page)
				tabs_block = js.split("new frappe.ui.Tabs({")[1].split("});")[0]
				self.assertIn("this.tab_content_wrappers[tab.name] = $wrapper", tabs_block)

	def test_bulk_action_is_disabled_not_hidden(self):
		"""A control that disappears teaches nothing. Disabled it explains
		itself - and via data-disabled + title rather than pointer-events,
		which would suppress the very tooltip doing the explaining. Underneath,
		this is now frappe.ui.dropdown (the Espresso replacement for bootstrap's
		data-toggle="dropdown") rather than a hand-rolled .btn-group, so the
		disabled look targets the button's own es-button class, not a
		Bootstrap .dropdown-toggle that no longer exists."""
		button = self._read_component("bulk_action_button")
		self.assertIn('"data-disabled"', button)
		self.assertIn("title: this.disabled_title", button)
		self.assertIn("Select one or more records to run an action", button)
		self.assertIn("new frappe.ui.Dropdown({", button)
		self.assertNotIn("dropdown-toggle", button)
		self.assertNotIn("btn-group", button)

		import os
		scss_path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "..",
			"public", "scss", "taxjar_integration.bundle.scss",
		))
		with open(scss_path) as f:
			disabled_rule = f.read().split(".es-button.taxjar-bulk-action[data-disabled] {")[1].split("}")[0]
		self.assertNotIn("pointer-events", disabled_rule)

	def test_bulk_action_labelled_consistently(self):
		for page in self.TABBED_PAGES:
			with self.subTest(page=page):
				self.assertIn('label: __("Bulk Action")', self._read_page_js(page))

	def test_tab_click_reload_is_wired_via_on_change(self):
		"""frappe.ui.Tabs fires its own on_change on every real tab switch - no
		more setup_tab_change() binding directly on each tab's nav-link to
		dodge Layout.setup_events()'s delegated, stopImmediatePropagation()-ing
		handler on .form-tabs, since that handler (and the <ul> it was bound
		to) no longer exists in this page at all."""
		for page in self.TABBED_PAGES:
			with self.subTest(page=page):
				js = self._read_page_js(page)
				self.assertNotIn("setup_tab_change", js)
				self.assertNotIn("nav-link", js)
				tabs_block = js.split("new frappe.ui.Tabs({")[1].split("});")[0]
				on_change_fn = tabs_block.split("on_change: (index) => {")[1].split("},")[0]
				self.assertIn("this.enter_tab(TABS[index].name);", on_change_fn)
				self.assertIn("this.refresh();", on_change_fn)

	def test_table_fills_width_without_a_serial_gutter(self):
		data_table = self._read_component("data_table_manager")
		self.assertIn('layout: "fluid"', data_table)
		self.assertIn("serialNoColumn: false", data_table)

	def test_table_does_not_scroll_inside_itself(self):
		"""The page paginates instead, so the scroll container is sized to the
		rows it holds. Its height must NOT be dropped to auto: rows are drawn by
		HyperList, which takes the container's computed height as its viewport
		(body-renderer.js:35-40), so auto computes to 0px and the table renders
		empty. fit_height() gives it an exact pixel height instead."""
		data_table = self._read_component("data_table_manager")
		fit_fn = data_table.split("fit_height() {")[1].split("\n\t}\n")[0]
		self.assertIn("rows * cell_height", fit_fn)
		self.assertIn("this.datatable.bodyRenderer.render()", fit_fn)
		# Called on first render and after every data change.
		self.assertIn("this.fit_height();", data_table.split("make() {")[1].split("\n\t}")[0])
		self.assertIn("this.fit_height();", data_table.split("refresh(data, columns) {")[1].split("\n\t}")[0])

		import os
		scss_path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "..",
			"public", "scss", "taxjar_integration.bundle.scss",
		))
		with open(scss_path) as f:
			rule = f.read().split(".dt-scrollable {")[1].split("}")[0]
		self.assertNotIn("height: auto", rule)

	def test_column_filters_are_resolved_server_side(self):
		"""The library filters the rows it holds, which is one page - a search
		for a record on page 3 would report nothing found. The override hands
		every row back and the values go to the server instead."""
		data_table = self._read_component("data_table_manager")
		self.assertIn("filterRows: (rows) => rows.map((row) => row.meta.rowIndex)", data_table)
		self.assertIn("frappe.utils.debounce", data_table)
		self.assertIn("this.on_filter_change(filters)", data_table)

		js = self._read_page_js("taxjar_transactions")
		self.assertIn("on_filter_change: (search) => {", js)
		self.assertIn("filters.search = this.column_search", js)

	def test_customer_page_search_is_also_resolved_server_side(self):
		"""Different control, same rule: the Customer page has no inline filter
		row, so its header fields carry the search instead."""
		js = self._read_page_js("taxjar_customers")
		scope_fn = js.split("get_scope_filters() {")[1].split("\n\t}\n")[0]
		self.assertIn("filters.search = search", scope_fn)
		self.assertIn("control.get_value()", scope_fn)

	def test_pages_use_the_shared_paginator(self):
		for page in self.TABBED_PAGES:
			with self.subTest(page=page):
				js = self._read_page_js(page)
				self.assertIn("taxjar_integration.Paginator", js)
				self.assertIn("page_size: this.page_size", js)
				# Page numbers move when the size changes, so the old one is void.
				size_fn = js.split("on_page_size: (size) => {")[1].split("},")[0]
				self.assertIn("this.current_page = 1;", size_fn)
				self.assertNotIn('__("Showing {0} - {1} of {2}"', js)

	def test_the_card_is_the_click_target_and_says_so(self):
		"""The pointer cursor is the only affordance now that the underline is
		gone, so the whole card has to be clickable - a pointer over dead space
		would be advertising something that is not there."""
		strip = self._read_component("summary_strip")
		self.assertIn('$card\n\t\t\t\t\t.addClass("taxjar-summary-clickable")', strip)
		self.assertIn('$card.on("click", activate)', strip)
		# No native tooltip: it fired on hover across a whole row of cards to
		# repeat what the cursor and the active underline already convey.
		self.assertNotIn('.attr("title"', strip)
		self.assertNotIn("Show only these", strip)

		import os
		scss_path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "..",
			"public", "scss", "taxjar_integration.bundle.scss",
		))
		with open(scss_path) as f:
			rule = f.read().split(".taxjar-summary-clickable {")[1].split("\n}")[0]
		self.assertIn("cursor: pointer", rule)
		# No underline and no background block - both were tried and dropped.
		self.assertNotIn("border-bottom", rule)
		self.assertNotIn("background-color", rule)
		# The active drill-down still has to be visible.
		self.assertIn('&[aria-pressed="true"] .summary-value', rule)

	def test_a_total_card_is_clickable(self):
		"""A Total's key is the empty string - "no filter, show all of it". A
		truthiness check would treat that as "not clickable" and silently drop
		the handler, which is exactly what it did."""
		strip = self._read_component("summary_strip")
		self.assertIn("if (card.value_key == null) return;", strip)
		# Same trap in select(): testing the key would report a Total click as a
		# clear and hand the caller null for a card that was really selected.
		select_fn = strip.split("select(card) {")[1].split("\n\t}\n")[0]
		self.assertIn("const cleared = this.active_key === card.value_key;", select_fn)
		self.assertIn("this.on_select(cleared ? null : card)", select_fn)

	def test_summary_ignores_the_status_drill_down(self):
		"""The strip is what you drill *from*. If clicking Failed also narrowed
		the counts, every other number would collapse to zero and there would be
		nothing left to drill from."""
		for page in self.TABBED_PAGES:
			with self.subTest(page=page):
				js = self._read_page_js(page)
				scope_fn = js.split("get_scope_filters() {")[1].split("\n\t}\n")[0]
				self.assertNotIn("sync_status", scope_fn)
				# The table gets the drill-down; the summary gets the scope only.
				filters_fn = js.split("\tget_filters() {")[1].split("\n\t}\n")[0]
				self.assertIn("sync_status", filters_fn)
				self.assertIn("get_summary", js.split("{ filters: this.get_scope_filters() }")[0])

	def test_summary_endpoints_drop_the_status_filter(self):
		"""Enforced at the endpoint, not just by what the page happens to send."""
		for module in (
			"taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions",
			"taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers",
		):
			with self.subTest(module=module):
				import importlib
				import inspect
				source = inspect.getsource(importlib.import_module(module).get_summary)
				self.assertIn('filters.pop("sync_status", None)', source)

	def test_summary_cards_filter_and_toggle(self):
		"""Clicking a number drills into it; clicking it again clears, so a
		card is a toggle rather than a one-way trip."""
		strip = self._read_component("summary_strip")
		self.assertIn("taxjar-summary-clickable", strip)
		self.assertIn("this.set_active(cleared ? null : card.value_key)", strip)
		# Keyboard reachable, not mouse-only.
		self.assertIn('$card.on("keydown"', strip)
		self.assertIn('attr("tabindex", 0)', strip)


class TestCustomerConfigPageJS(UnitTestCase):

	def _js(self):
		import os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "page", "taxjar_customers", "taxjar_customers.js"
		))
		with open(path) as f:
			return f.read()

	def test_customer_id_column_present(self):
		"""taxjar_customer_id was already fetched by get_customers and simply
		never rendered."""
		js = self._js()
		self.assertIn('__("TaxJar Customer ID")', js)
		self.assertIn('fieldname: "taxjar_customer_id"', js)
		# Empty means no successful create in TaxJar yet - a dash, same as
		# every other empty cell in this table. Scoped to get_columns(), not
		# the whole file - SEARCH_FIELDS has its own, unrelated "TaxJar
		# Customer ID" label for the header search field.
		columns_fn = js.split("\tget_columns() {")[1].split("\n\t}\n")[0]
		id_fn = columns_fn.split('fieldname: "taxjar_customer_id"')[1].split("},")[0]
		self.assertIn('<span class="text-muted">-</span>', id_fn)

	def test_regions_pencil_shows_on_every_row(self):
		"""An affordance that disappears reads as "nothing to do here", when the
		truth is "not yet". Rows with no exemption type keep the pencil - it is
		the only way to set one, so it is never blocked or greyed out."""
		js = self._js()
		regions_fn = js.split("render_regions_cell(row) {")[1].split("\n\t}\n")[0]
		# One unconditional return - no early exit that drops the control.
		self.assertEqual(regions_fn.count("return"), 1)
		self.assertIn("taxjar-configure-link", regions_fn)
		self.assertNotIn("taxjar-configure-link--blocked", regions_fn)

	def test_regions_click_always_opens_the_dialog(self):
		"""The pencil is the only way to set an exemption type now, so a row
		with no type yet must still open the dialog rather than being gated."""
		js = self._js()
		handler = js.split('".taxjar-configure-link", (e) => {')[1].split("\n\t\t});")[0]
		self.assertNotIn("taxjar_exemption_type", handler)
		self.assertIn("open_configure_dialog", handler)

	def test_exemption_columns_show_on_every_tab_including_not_configured(self):
		"""The Configure cell is the only way to set an exemption, so hiding it
		on the Not Configured tab would make exactly the customers that need one
		the only ones you could not give one to. Exemption Type stays too, and
		renders blank as a dash rather than being dropped."""
		js = self._js()
		columns_fn = js.split("\tget_columns() {")[1].split("\n\t}\n")[0]
		self.assertNotIn("if (this.active_tab !== NOT_CONFIGURED_TAB) {", columns_fn)
		self.assertIn('__("Exemption Type")', columns_fn)
		self.assertIn('__("Configure")', columns_fn)
		cell_fn = js.split("render_exemption_type_cell(value) {")[1].split("\n\t}\n")[0]
		self.assertIn('<span class="text-muted">-</span>', cell_fn)
		# Clearing, unlike configuring, IS meaningless there - that guard lives
		# on the bulk actions and must stay.
		bulk_fn = js.split("\tupdate_bulk_state() {")[1].split("\n\t}\n")[0]
		self.assertIn("if (this.active_tab !== NOT_CONFIGURED_TAB) {", bulk_fn)
		# Sync Status sits between the two guarded blocks, and belongs to
		# neither - it shows on every tab, including this one.
		exemption_idx = columns_fn.index('__("Exemption Type")')
		sync_idx = columns_fn.index('__("Sync Status")')
		configure_idx = columns_fn.index('__("Configure")')
		self.assertLess(exemption_idx, sync_idx)
		self.assertLess(sync_idx, configure_idx)

	def test_four_tabs(self):
		js = self._js()
		for label in ("All", "Exempted", "Non-Exempted", "Not Configured"):
			self.assertIn(f'__("{label}")', js)

	def test_no_sync_to_taxjar_bulk_action(self):
		"""Every exemption change saves the Customer, and on_customer_update
		enqueues the sync - a manual "send it" button would be redundant. Retry
		survives only because a failure leaves nothing to re-save."""
		js = self._js()
		bulk_fn = js.split("update_bulk_state() {")[1].split("\n\t}\n")[0]
		self.assertIn('__("Configure Exemption…")', bulk_fn)
		self.assertIn('__("Clear Exemption")', bulk_fn)
		self.assertIn('__("Resync with TaxJar")', bulk_fn)
		# Distinct from a blanket "sync everything" action: this one is offered
		# only when the selection contains Failed rows.
		self.assertIn('failed.length', bulk_fn)

	def test_clear_exemption_hidden_on_the_not_configured_tab(self):
		"""It would be a no-op on every row there."""
		js = self._js()
		bulk_fn = js.split("update_bulk_state() {")[1].split("\n\t}\n")[0]
		self.assertIn("if (this.active_tab !== NOT_CONFIGURED_TAB) {", bulk_fn)

	def test_exemption_type_is_read_only(self):
		"""A region-scoped exemption type needs at least one region to be a
		valid save, so it can no longer be set from an inline cell on its own -
		the pencil is the only way in, and it carries both fields together."""
		js = self._js()
		cell_fn = js.split("render_exemption_type_cell(value) {")[1].split("\n\t}\n")[0]
		self.assertNotIn("<select", cell_fn)
		self.assertNotIn("taxjar-exemption-select", js)
		self.assertNotIn("set_exemption_type", js)

	def test_exemption_type_renders_as_plain_text(self):
		"""Not a badge/pill - blank is common enough (it's the whole Not
		Configured tab) that a colored status pill on every row would read
		as noisier signalling than this column actually carries. Blank
		renders as a muted dash, same as every other empty cell in this
		table, rather than repeating the word the tab itself already says."""
		js = self._js()
		cell_fn = js.split("render_exemption_type_cell(value) {")[1].split("\n\t}\n")[0]
		self.assertNotIn("frappe.ui.badge", cell_fn)
		self.assertNotIn("indicator-pill", cell_fn)
		self.assertNotIn("EXEMPTION_TYPE_COLORS", js)
		self.assertIn("frappe.utils.escape_html(value)", cell_fn)
		self.assertIn('<span class="text-muted">-</span>', cell_fn)

	def test_regions_uses_the_desk_pencil_icon(self):
		"""A text glyph's size and baseline shift from platform to platform.

		The name must be one frappe's sprite actually defines: icon() builds a
		<use href="#icon-{name}">, and an unknown name renders nothing at all
		rather than failing loudly. "edit" is not in the sprite; "square-pen" is.
		"""
		js = self._js()
		regions_fn = js.split("render_regions_cell(row) {")[1].split("\n\t}\n")[0]
		self.assertIn('frappe.utils.icon("square-pen", "sm")', regions_fn)
		self.assertNotIn("\u270e", regions_fn)

	def test_failed_sync_status_pairs_the_pill_with_an_info_icon(self):
		"""The pill text alone doesn't carry the error - Failed gets a
		separate info-icon trigger for a hover/click popover, same split as
		the Transaction Sync page's Sync Status column."""
		js = self._js()
		cell_fn = js.split("render_sync_status_cell(row) {")[1].split("\n\t}\n")[0]
		self.assertIn('status !== "Failed"', cell_fn)
		self.assertIn("taxjar-sync-icon", cell_fn)
		self.assertIn("taxjar-sync-trigger", cell_fn)
		self.assertIn('frappe.utils.icon("info", "sm")', cell_fn)
		self.assertIn("row.taxjar_customer_sync_error", cell_fn)

	def test_sync_popover_bound_and_torn_down(self):
		js = self._js()
		self.assertIn("this.bind_sync_popover($table_wrapper)", js)
		hide_hook = js.split("on_hide() {")[1].split("\n\t}\n")[0]
		self.assertIn("this._hide_sync_popover()", hide_hook)

	def test_header_search_fields(self):
		"""Search lives in the desk's own header filter row. Each field is a
		LIKE term the server resolves against _SEARCHABLE_COLUMNS, so the
		fieldnames must be exactly those columns."""
		js = self._js()
		self.assertIn("make_filters()", js)
		fields_block = js.split("const SEARCH_FIELDS = [")[1].split("];")[0]
		for fieldname in ("customer_name", "customer_group", "taxjar_customer_id"):
			self.assertIn(f'fieldname: "{fieldname}"', fields_block)
		self.assertIn("this.page.add_field(", js)

	def test_search_fields_match_the_server_allowlist(self):
		from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import (
			_SEARCHABLE_COLUMNS,
		)
		fields_block = self._js().split("const SEARCH_FIELDS = [")[1].split("];")[0]
		for fieldname in _SEARCHABLE_COLUMNS:
			self.assertIn(f'fieldname: "{fieldname}"', fields_block)

	def test_selection_is_scoped_to_the_rows_on_screen(self):
		"""A selection that outlived its page would leave the count claiming
		rows nobody can see, and the bulk actions acting on them. Reads
		straight off the DataTableManager instance now (this page's table is
		frappe.DataTable, same as the Transaction Sync page's), not a
		hand-tracked Set of selected names."""
		js = self._js()
		checked_fn = js.split("get_checked() {")[1].split("\n\t}\n")[0]
		self.assertIn("this.datatable?.get_checked_items()", checked_fn)
		self.assertNotIn("this.selected", js)
		# Every navigation clears it.
		self.assertIn("reset_selection()", js.split("enter_tab(name) {")[1].split("\n\t}\n")[0])
		self.assertIn("reset_selection()", js.split("on_page: (page) => {")[1].split("},")[0])
		reset_fn = js.split("reset_selection() {")[1].split("\n\t}\n")[0]
		self.assertIn("this.datatable?.clear_checked_items()", reset_fn)

	def test_configure_dialog_uses_the_shared_multicheck_region_fields(self):
		"""The region pickers are frappe.ui.form MultiCheck fields built and
		wired by the shared taxjar_utils.js helpers, not a hand-built grid
		re-implemented on this page."""
		js = self._js()
		dialog_fn = js.split("show_configure_dialog(rows, exemption_type, existing_regions) {")[1].split(
			"\n\tsave_exemption(rows, exemption_type, regions) {"
		)[0]
		self.assertIn("taxjar_integration.build_region_multicheck_fields(selected)", dialog_fn)
		self.assertIn("taxjar_integration.get_selected_regions(dialog)", dialog_fn)
		self.assertIn("taxjar_integration.wire_exemption_dialog(dialog)", dialog_fn)


# ── Transaction Compliance — async sync_transaction_to_taxjar ─────────────────


class TestSyncTransactionCompliance(UnitTestCase):

	def _make_submit_doc(self, is_return=False, return_against=None, sales_tax=85.0):
		doc = _make_doc(
			taxes=[_make_tax_row("Sales Tax - TC", TAXJAR_ROW_DESCRIPTION, sales_tax)] if sales_tax else [],
		)
		doc.docstatus = 1
		doc.posting_date = "2025-05-31"
		doc.is_return = is_return
		doc.return_against = return_against
		return doc

	def test_transaction_date_uses_posting_date(self):
		"""transaction_date should be doc.posting_date, not today()."""
		doc = self._make_submit_doc()
		mock_client = MagicMock()
		mock_client.create_order.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"shipping": 10, "dummy": True}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_sync_status"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			sync_transaction_to_taxjar("SINV-TEST-001")

		payload = mock_client.create_order.call_args[0][0]
		self.assertEqual(payload["transaction_date"], "2025-05-31")

	def test_refund_includes_transaction_reference_id(self):
		"""Refunds must include transaction_reference_id linking to the original order."""
		doc = self._make_submit_doc(is_return=True, return_against="SINV-ORIG-001")
		mock_client = MagicMock()
		mock_client.create_refund.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"shipping": 0, "dummy": True}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_sync_status"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			sync_transaction_to_taxjar("SINV-TEST-001")

		payload = mock_client.create_refund.call_args[0][0]
		self.assertEqual(payload["transaction_reference_id"], "SINV-ORIG-001")

	def test_zero_tax_order_still_pushed(self):
		"""$0-tax orders must still be pushed to TaxJar for nexus tracking."""
		doc = self._make_submit_doc(sales_tax=0)
		doc.posting_date = "2025-06-01"
		mock_client = MagicMock()
		mock_client.create_order.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"shipping": 0, "dummy": True}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_sync_status"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			sync_transaction_to_taxjar("SINV-TEST-001")

		mock_client.create_order.assert_called_once()
		payload = mock_client.create_order.call_args[0][0]
		self.assertEqual(payload["sales_tax"], 0)

	def test_provider_field_in_payload(self):
		"""Provider should be 'ERPNext' in all transaction payloads."""
		doc = self._make_submit_doc()
		mock_client = MagicMock()
		mock_client.create_order.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"shipping": 10, "dummy": True}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_sync_status"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			sync_transaction_to_taxjar("SINV-TEST-001")

		payload = mock_client.create_order.call_args[0][0]
		self.assertEqual(payload["provider"], "ERPNext")

	def test_sets_synced_on_success(self):
		"""On successful API call, status should be set to Synced."""
		doc = self._make_submit_doc()
		mock_client = MagicMock()
		mock_client.create_order.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"shipping": 10}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_sync_status") as mock_status, \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			sync_transaction_to_taxjar("SINV-TEST-001")

		mock_status.assert_called_with("SINV-TEST-001", "Synced")

	def _fresh_docstatus_stub(self, invoice_name, docstatus):
		"""frappe.db.get_value has plenty of other callers within a single
		sync_transaction_to_taxjar() run (frappe's own doctype-controller
		lookups included) - only the exact re-check this fix added should be
		stubbed, everything else must reach the real implementation."""
		real_get_value = frappe.db.get_value

		def fake_get_value(*args, **kwargs):
			doctype = kwargs.get("doctype", args[0] if len(args) > 0 else None)
			name = kwargs.get("name", args[1] if len(args) > 1 else None)
			fieldname = kwargs.get("fieldname", args[2] if len(args) > 2 else None)
			if doctype == "Sales Invoice" and name == invoice_name and fieldname == "docstatus":
				return docstatus
			return real_get_value(*args, **kwargs)

		return fake_get_value

	def test_deletes_if_cancelled_while_create_was_in_flight(self):
		"""doc is read once at the top of the function - if the invoice gets
		cancelled while create_order() is still running, that stale doc can't
		reflect it. A concurrent delete job may have already 404'd against an
		order that didn't exist yet and treated that as done, so this worker
		must notice the cancellation itself and clean up what it just created."""
		doc = self._make_submit_doc()
		mock_client = MagicMock()
		mock_client.create_order.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"shipping": 10}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value",
		           side_effect=self._fresh_docstatus_stub("SINV-TEST-001", 2)), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.delete_transaction_from_taxjar") as mock_delete, \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_sync_status"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			sync_transaction_to_taxjar("SINV-TEST-001")

		mock_delete.assert_called_once_with("SINV-TEST-001")

	def test_no_cleanup_delete_when_still_submitted(self):
		"""The common case - no cancellation raced the create - must not trigger
		the extra delete call."""
		doc = self._make_submit_doc()
		mock_client = MagicMock()
		mock_client.create_order.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"shipping": 10}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value",
		           side_effect=self._fresh_docstatus_stub("SINV-TEST-001", 1)), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.delete_transaction_from_taxjar") as mock_delete, \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_sync_status"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			sync_transaction_to_taxjar("SINV-TEST-001")

		mock_delete.assert_not_called()


class TestDeleteTransactionCompliance(UnitTestCase):

	def test_order_calls_delete_order(self):
		doc = _make_doc()
		doc.is_return = False
		mock_client = MagicMock()
		mock_client.delete_order.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_sync_status"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			delete_transaction_from_taxjar(doc.name)

		mock_client.delete_order.assert_called_once_with(doc.name, params={"provider": "ERPNext"})
		mock_client.delete_refund.assert_not_called()

	def test_return_calls_delete_refund(self):
		doc = _make_doc()
		doc.is_return = True
		mock_client = MagicMock()
		mock_client.delete_refund.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_sync_status"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			delete_transaction_from_taxjar(doc.name)

		mock_client.delete_refund.assert_called_once_with(doc.name, params={"provider": "ERPNext"})
		mock_client.delete_order.assert_not_called()


# ── Phase 2: Payload Enrichment (Items 7, 8) ────────────────────────────────


# NOTE: the price_list_rate-vs-rate discount formula this class used to cover
# (TestGetLineItemDiscount) was replaced by the net_amount-sourced formula in
# TestGetLineItemDict above (design doc §3.2) - that comparison didn't scale
# with quantity and went blind the moment Margin was in play. See
# docs/discount-and-non-tax-rows-design.md §3.2.1 for the live-verified bug
# this fix addresses.


# ── Phase 3: Token Validation (Item 5) ──────────────────────────────────────


class TestTokenValidation(UnitTestCase):
	"""Token validation runs in the background (validate_taxjar_tokens) and reports
	problems via a realtime alert to the saving user instead of blocking the save."""

	MOD = "taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings"

	def _settings_with_cred(self, **cred):
		settings = MagicMock()
		settings.table_hvjw = [MagicMock(company="Test Co", **cred)]
		return settings

	def test_valid_token_no_alert(self):
		"""categories() succeeds → no alert published."""
		mock_client = MagicMock()
		mock_client.categories.return_value = []
		settings = self._settings_with_cred(sandbox_token="sk_test")

		with patch(f"{self.MOD}.get_client", return_value=mock_client), \
		     patch(f"{self.MOD}.frappe.get_single", return_value=settings), \
		     patch(f"{self.MOD}.frappe.publish_realtime") as mock_pub:
			validate_taxjar_tokens(user="admin@example.com")

		mock_client.categories.assert_called_once()
		mock_pub.assert_not_called()

	def test_invalid_token_alerts_red(self):
		"""401 response → red realtime alert to the saving user, no exception."""
		import taxjar.exceptions
		err = taxjar.exceptions.TaxJarResponseError(MagicMock())
		err.full_response = {"status_code": 401}

		mock_client = MagicMock()
		mock_client.categories.side_effect = err
		settings = self._settings_with_cred()

		with patch(f"{self.MOD}.get_client", return_value=mock_client), \
		     patch(f"{self.MOD}.frappe.get_single", return_value=settings), \
		     patch(f"{self.MOD}.frappe.publish_realtime") as mock_pub:
			validate_taxjar_tokens(user="admin@example.com")

		mock_pub.assert_called_once()
		payload = mock_pub.call_args[0][1]
		self.assertEqual(payload["indicator"], "red")
		self.assertEqual(mock_pub.call_args[1]["user"], "admin@example.com")

	def test_connection_error_alerts_orange(self):
		"""Connection error → orange alert, not an exception."""
		import taxjar.exceptions
		mock_client = MagicMock()
		mock_client.categories.side_effect = taxjar.exceptions.TaxJarConnectionError("timeout")
		settings = self._settings_with_cred()

		with patch(f"{self.MOD}.get_client", return_value=mock_client), \
		     patch(f"{self.MOD}.frappe.get_single", return_value=settings), \
		     patch(f"{self.MOD}.frappe.publish_realtime") as mock_pub:
			validate_taxjar_tokens(user="admin@example.com")

		mock_pub.assert_called_once()
		self.assertEqual(mock_pub.call_args[0][1]["indicator"], "orange")

	def test_no_alert_when_user_missing(self):
		"""Without a user to notify (e.g. a system-triggered save) nothing is published."""
		import taxjar.exceptions
		err = taxjar.exceptions.TaxJarResponseError(MagicMock())
		err.full_response = {"status_code": 401}
		mock_client = MagicMock()
		mock_client.categories.side_effect = err
		settings = self._settings_with_cred()

		with patch(f"{self.MOD}.get_client", return_value=mock_client), \
		     patch(f"{self.MOD}.frappe.get_single", return_value=settings), \
		     patch(f"{self.MOD}.frappe.publish_realtime") as mock_pub:
			validate_taxjar_tokens(user=None)

		mock_pub.assert_not_called()


# ── Phase 4: API Resilience (Items 6, 11) ────────────────────────────────────


class TestValidateTaxRequestOutage(UnitTestCase):

	def test_connection_error_returns_none_with_warning(self):
		"""TaxJarConnectionError should return None and show msgprint, not throw."""
		import taxjar.exceptions

		mock_client = MagicMock()
		mock_client.tax_for_order.side_effect = taxjar.exceptions.TaxJarConnectionError("timeout")

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.msgprint") as mock_msg:
			result = validate_tax_request({"dummy": True})

		self.assertIsNone(result)
		mock_msg.assert_called_once()
		self.assertIn("unreachable", mock_msg.call_args[0][0].lower())


class TestSyncTransactionOutage(UnitTestCase):

	def test_connection_error_sets_failed_status(self):
		"""TaxJarConnectionError in background should set status to Failed, not throw."""
		import taxjar.exceptions

		doc = _make_doc(taxes=[_make_tax_row("Sales Tax - TC", TAXJAR_ROW_DESCRIPTION, 85.0)])
		doc.docstatus = 1
		doc.posting_date = "2025-06-01"

		mock_client = MagicMock()
		mock_client.create_order.side_effect = taxjar.exceptions.TaxJarConnectionError("timeout")

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"shipping": 10, "dummy": True}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_sync_status") as mock_status, \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			sync_transaction_to_taxjar("SINV-TEST-001")

		args, kwargs = mock_status.call_args
		self.assertEqual(args, ("SINV-TEST-001", "Failed"))
		self.assertIn("unreachable", kwargs["error"])
		self.assertTrue(kwargs["retryable"], "a connection failure has to stay on the retry cron")


class TestDeleteTransactionOutage(UnitTestCase):

	def test_connection_error_sets_failed_status(self):
		"""TaxJarConnectionError on delete should set status to Failed, not throw."""
		import taxjar.exceptions

		doc = _make_doc()
		doc.is_return = False

		mock_client = MagicMock()
		mock_client.delete_order.side_effect = taxjar.exceptions.TaxJarConnectionError("timeout")

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_sync_status") as mock_status, \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			delete_transaction_from_taxjar(doc.name)

		args, kwargs = mock_status.call_args
		self.assertEqual(args, ("SINV-TEST-001", "Failed"))
		self.assertIn("unreachable", kwargs["error"])
		self.assertTrue(kwargs["retryable"], "a connection failure has to stay on the retry cron")


# ── Phase 5: Address Validation (Item 14) ────────────────────────────────────


class TestAddressValidationWithTaxJar(UnitTestCase):

	def _make_address_doc(self, country_code="US"):
		doc = MagicMock()
		doc.name = "ADDR-001"
		doc.country = "United States" if country_code == "US" else "Germany"
		doc.state = "Texas"
		doc.taxjar_state_code = "TX"
		doc.city = "Austin"
		doc.pincode = "78701"
		doc.address_line1 = "123 Main St"
		doc.get.side_effect = lambda f, d=None: getattr(doc, f, d)
		return doc

	def test_us_address_calls_validation_api(self):
		"""A match found means TaxJar resolved the address - silent pass, no
		exception, no dialog."""
		mock_client = MagicMock()
		mock_client.validate_address.return_value = [
			MagicMock(street="123 Main St", city="Austin", state="TX", zip="78701", country="US")
		]
		doc = self._make_address_doc()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._is_taxjar_enabled", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			_validate_address_with_taxjar(doc)  # should not raise

		mock_client.validate_address.assert_called_once()

	def test_address_not_found_blocks_save(self):
		"""An empty "addresses" result is how TaxJar reports no match (confirmed
		against the taxjar package and taxjar-ruby's own SDK fixtures) - block
		the save rather than silently letting an unresolvable address through."""
		mock_client = MagicMock()
		mock_client.validate_address.return_value = []
		doc = self._make_address_doc()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			with self.assertRaises(frappe.exceptions.ValidationError):
				_validate_address_with_taxjar(doc)

	def test_address_not_found_error_message(self):
		mock_client = MagicMock()
		mock_client.validate_address.return_value = []
		doc = self._make_address_doc()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			with self.assertRaises(frappe.exceptions.ValidationError) as ctx:
				_validate_address_with_taxjar(doc)

		self.assertEqual(
			str(ctx.exception),
			"The given address is not valid, please reverify the street, city, state, or postal code.",
		)

	def test_connection_error_does_not_block_save(self):
		import taxjar.exceptions

		mock_client = MagicMock()
		mock_client.validate_address.side_effect = taxjar.exceptions.TaxJarConnectionError("timeout")
		doc = self._make_address_doc()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			_validate_address_with_taxjar(doc)  # should not raise

	def test_response_error_404_blocks_save(self):
		"""In case the live API does surface a literal 404 for "not found"
		(undocumented either way), it's handled the same as an empty result."""
		import taxjar.exceptions

		err = taxjar.exceptions.TaxJarResponseError(MagicMock())
		err.full_response = {"status_code": 404, "detail": "Address not found"}

		mock_client = MagicMock()
		mock_client.validate_address.side_effect = err
		doc = self._make_address_doc()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			with self.assertRaises(frappe.exceptions.ValidationError):
				_validate_address_with_taxjar(doc)

	def test_response_error_non_404_does_not_block(self):
		"""A non-404 API error (auth, rate limit, server error) isn't a
		statement about whether the address is valid - don't block the save
		or show a dialog for it."""
		import taxjar.exceptions

		err = taxjar.exceptions.TaxJarResponseError(MagicMock())
		err.full_response = {"status_code": 401, "detail": "Unauthorized"}

		mock_client = MagicMock()
		mock_client.validate_address.side_effect = err
		doc = self._make_address_doc()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.msgprint") as mock_msg, \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.throw") as mock_throw:
			_validate_address_with_taxjar(doc)  # should not raise

		mock_msg.assert_not_called()
		mock_throw.assert_not_called()


# ── Phase 1: Sales Invoice Custom Fields ─────────────────────────────────────


class TestSalesInvoiceCustomFields(UnitTestCase):

	def _get_si_field_defs(self):
		captured = {}
		def fake_create(fields, update=True):
			captured.update(fields)
		with patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.create_custom_fields", side_effect=fake_create), \
		     patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.make_property_setter"):
			make_custom_fields(update=True)
		return {f["fieldname"]: f for f in captured.get("Sales Invoice", [])}

	def test_taxjar_tab_exists(self):
		fields = self._get_si_field_defs()
		self.assertIn("taxjar_tab", fields)
		self.assertEqual(fields["taxjar_tab"]["fieldtype"], "Tab Break")

	def test_exemption_fields_share_one_section(self):
		"""The checkbox used to sit after Shipping Rule and its reason after
		Incoterm - a question and its answer in different columns of an
		unrelated section."""
		fields = self._get_si_field_defs()

		section = fields["taxjar_exemption_section"]
		self.assertEqual(section["fieldtype"], "Section Break")
		self.assertEqual(section["label"], "TaxJar Exemptions")
		self.assertEqual(fields["taxjar_transaction_exempt"]["insert_after"], "taxjar_exemption_section")
		self.assertEqual(
			fields["taxjar_transaction_exemption_type"]["insert_after"], "taxjar_transaction_exempt"
		)

	def test_exemption_reason_shown_and_required_with_the_checkbox(self):
		fields = self._get_si_field_defs()
		reason = fields["taxjar_transaction_exemption_type"]
		condition = "eval: doc.taxjar_transaction_exempt == 1"
		self.assertEqual(reason["depends_on"], condition)
		self.assertEqual(reason["mandatory_depends_on"], condition)

	def test_marketplace_fields_gated_on_the_marketplace_checkbox(self):
		"""None of the three mean anything on an ordinary invoice, so none of
		them can be set without the checkbox first."""
		fields = self._get_si_field_defs()
		condition = "eval: doc.taxjar_is_marketplace_invoice == 1"

		self.assertEqual(fields["taxjar_marketplace_section"]["fieldtype"], "Section Break")
		self.assertEqual(fields["taxjar_is_marketplace_invoice"]["fieldtype"], "Check")

		platform = fields["taxjar_marketplace_platform"]
		self.assertEqual(platform["fieldtype"], "Data")
		self.assertEqual(platform["depends_on"], condition)
		# The one that is also required once the invoice is a marketplace one.
		self.assertEqual(platform["mandatory_depends_on"], condition)

		for fieldname in ("taxjar_skip_tax_calculation", "taxjar_skip_transaction_sync"):
			with self.subTest(fieldname=fieldname):
				field = fields[fieldname]
				self.assertEqual(field["fieldtype"], "Check")
				self.assertEqual(field["depends_on"], condition)
				# A checkbox is never "required" - only shown or not.
				self.assertIsNone(field.get("mandatory_depends_on"))

	def test_marketplace_section_precedes_transaction_sync(self):
		"""Two fields cannot share one insert_after, so Transaction Sync is
		chained behind the marketplace block rather than left on
		taxjar_status_html."""
		fields = self._get_si_field_defs()
		self.assertEqual(fields["taxjar_marketplace_section"]["insert_after"], "taxjar_status_html")
		self.assertEqual(fields["taxjar_sync_section"]["insert_after"], "taxjar_skip_transaction_sync")

	def test_marketplace_fields_are_sales_invoice_only(self):
		"""A marketplace has already raised the invoice - there is no quotation
		or order stage for one."""
		from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
			get_custom_fields,
		)
		import inspect

		source = inspect.getsource(get_custom_fields)
		self.assertEqual(source.count("_marketplace_fields()"), 1)
		sales_invoice_block = source.split('"Sales Invoice": [')[1]
		self.assertIn("_marketplace_fields()", sales_invoice_block)

	def test_sync_status_field(self):
		fields = self._get_si_field_defs()
		f = fields["taxjar_sync_status"]
		self.assertEqual(f["fieldtype"], "Select")
		for opt in ("Excluded", "Queued", "Synced", "Failed"):
			self.assertIn(opt, f["options"])
		self.assertTrue(f.get("allow_on_submit"))
		self.assertTrue(f.get("read_only"))

	def test_sync_status_hidden_while_draft(self):
		"""Replaced by taxjar_sync_draft_message_html while a draft - showing
		the "Excluded" default there read as "TaxJar doesn't apply"
		rather than "not submitted yet"."""
		fields = self._get_si_field_defs()
		self.assertEqual(fields["taxjar_sync_status"]["depends_on"], "eval: doc.docstatus === 1")
		self.assertEqual(fields["taxjar_last_synced"]["depends_on"], "eval: doc.docstatus === 1")

	def test_sync_draft_message_field(self):
		fields = self._get_si_field_defs()
		f = fields["taxjar_sync_draft_message_html"]
		self.assertEqual(f["fieldtype"], "HTML")
		self.assertEqual(f["depends_on"], "eval: doc.docstatus === 0")
		self.assertIn("TaxJar: Submit to sync", f["options"])
		self.assertEqual(f["insert_after"], "taxjar_sync_section")
		self.assertEqual(fields["taxjar_sync_status"]["insert_after"], "taxjar_sync_draft_message_html")

	def test_sync_error_field(self):
		fields = self._get_si_field_defs()
		f = fields["taxjar_sync_error"]
		self.assertEqual(f["fieldtype"], "Small Text")
		self.assertTrue(f.get("read_only"))
		self.assertTrue(f.get("allow_on_submit"))

	def test_sync_error_depends_on_submitted_and_failed(self):
		fields = self._get_si_field_defs()
		depends_on = fields["taxjar_sync_error"]["depends_on"]
		self.assertIn("doc.docstatus === 1", depends_on)
		self.assertIn("doc.taxjar_sync_status == 'Failed'", depends_on)

	def test_last_synced_field(self):
		fields = self._get_si_field_defs()
		f = fields["taxjar_last_synced"]
		self.assertEqual(f["fieldtype"], "Datetime")
		self.assertTrue(f.get("read_only"))


# ── Phase 1: Property Setter for return_against ──────────────────────────────


class TestReturnAgainstPropertySetter(UnitTestCase):

	def test_make_custom_fields_calls_property_setter(self):
		with patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.create_custom_fields"), \
		     patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.make_property_setter") as mock_ps:
			make_custom_fields(update=True)

		mock_ps.assert_called_once_with(
			"Sales Invoice", "return_against", "no_copy", "0", "Check",
			for_doctype=False,
		)


# ── Phase 2: validate_return_against ─────────────────────────────────────────


class TestValidateReturnAgainst(UnitTestCase):

	def test_skips_non_return(self):
		doc = _make_doc()
		doc.is_return = False
		validate_return_against(doc, None)

	def test_skips_when_create_transactions_disabled(self):
		doc = _make_doc()
		doc.is_return = True
		doc.return_against = None
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.company_creates_transactions", return_value=False):
			validate_return_against(doc, None)

	def test_throws_when_return_without_return_against(self):
		doc = _make_doc()
		doc.is_return = True
		doc.return_against = None
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.company_creates_transactions", return_value=True):
			self.assertRaises(frappe.ValidationError, validate_return_against, doc, None)

	def test_passes_when_return_with_return_against(self):
		doc = _make_doc()
		doc.is_return = True
		doc.return_against = "SINV-ORIG-001"
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.company_creates_transactions", return_value=True):
			validate_return_against(doc, None)


# ── Phase 3: enqueue_taxjar_sync / enqueue_taxjar_delete ─────────────────────


class TestEnqueueTaxjarSync(UnitTestCase):

	def test_skips_when_create_transactions_disabled(self):
		doc = _make_doc()
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.company_creates_transactions", return_value=False), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.enqueue") as mock_enqueue:
			enqueue_taxjar_sync(doc, None)
		mock_enqueue.assert_not_called()

	def test_skips_when_no_client(self):
		doc = _make_doc()
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.company_creates_transactions", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=None), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.enqueue") as mock_enqueue:
			enqueue_taxjar_sync(doc, None)
		mock_enqueue.assert_not_called()

	def test_sets_queued_and_enqueues(self):
		doc = _make_doc()
		doc.db_set = MagicMock()
		mock_client = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.company_creates_transactions", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.enqueue") as mock_enqueue:
			enqueue_taxjar_sync(doc, None)

		doc.db_set.assert_called_once_with("taxjar_sync_status", "Queued", update_modified=False)
		mock_enqueue.assert_called_once()
		call_kwargs = mock_enqueue.call_args[1]
		self.assertTrue(call_kwargs["deduplicate"])
		self.assertEqual(call_kwargs["job_id"], f"taxjar_transaction_create_{doc.name}")

	def test_does_not_share_job_id_with_enqueue_taxjar_delete(self):
		"""A shared job_id let deduplicate=True silently drop a cancel's delete
		enqueue whenever the create job was still STARTED - including in the gap
		after the create worker's last docstatus check but before it exits, which
		left the invoice's transaction stranded in TaxJar with no Failed status
		for the retry cron to catch. Each operation must get its own job_id so a
		delete is never dropped, only ever run redundantly alongside a create."""
		doc = _make_doc()
		doc.db_set = MagicMock()
		mock_client = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.company_creates_transactions", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.enqueue") as mock_enqueue:
			enqueue_taxjar_sync(doc, None)
			sync_job_id = mock_enqueue.call_args[1]["job_id"]
			enqueue_taxjar_delete(doc, None)
			delete_job_id = mock_enqueue.call_args[1]["job_id"]

		self.assertNotEqual(sync_job_id, delete_job_id)


class TestEnqueueTaxjarDelete(UnitTestCase):

	def test_skips_when_create_transactions_disabled(self):
		doc = _make_doc()
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.company_creates_transactions", return_value=False), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.enqueue") as mock_enqueue:
			enqueue_taxjar_delete(doc, None)
		mock_enqueue.assert_not_called()

	def test_sets_queued_and_enqueues(self):
		doc = _make_doc()
		doc.db_set = MagicMock()
		mock_client = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.company_creates_transactions", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.enqueue") as mock_enqueue:
			enqueue_taxjar_delete(doc, None)

		doc.db_set.assert_called_once_with("taxjar_sync_status", "Queued", update_modified=False)
		mock_enqueue.assert_called_once()
		# Its own job_id, not shared with enqueue_taxjar_sync() - see the comment
		# there on why a cancel's delete must never dedupe against a create job.
		self.assertEqual(mock_enqueue.call_args[1]["job_id"], f"taxjar_transaction_delete_{doc.name}")


class TestIsTaxjarEnabledForCompany(UnitTestCase):
	"""Live read backing the sidebar's not-enabled link (see
	render_sync_status_sidebar_pill in taxjar_utils.js) - mirrors
	enqueue_taxjar_sync/enqueue_taxjar_delete's own company_creates_transactions
	check so the sidebar never disagrees with what submit/cancel actually do."""

	def test_requires_sales_invoice_read_permission(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				is_taxjar_enabled_for_company("_Test Company")
		finally:
			frappe.set_user("Administrator")

	def test_delegates_to_company_creates_transactions(self):
		with patch(
			"taxjar_integration.taxjar_integration.taxjar_integration.company_creates_transactions",
			return_value=True,
		) as mock_check:
			self.assertTrue(is_taxjar_enabled_for_company("_Test Company"))
		mock_check.assert_called_once_with("_Test Company")

	def test_false_when_company_creates_transactions_is_false(self):
		with patch(
			"taxjar_integration.taxjar_integration.taxjar_integration.company_creates_transactions",
			return_value=False,
		):
			self.assertFalse(is_taxjar_enabled_for_company("_Test Company"))


# ── Phase 3: sync_transaction_to_taxjar — cancelled invoice routing ──────────


class TestSyncCancelledInvoice(UnitTestCase):

	def test_cancelled_invoice_routes_to_delete(self):
		"""sync_transaction_to_taxjar on a cancelled doc should call delete_transaction_from_taxjar."""
		doc = _make_doc()
		doc.docstatus = 2
		doc.is_return = False
		mock_client = MagicMock()
		mock_client.delete_order.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_sync_status"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			sync_transaction_to_taxjar("SINV-TEST-001")

		mock_client.delete_order.assert_called_once()
		mock_client.create_order.assert_not_called()


# ── Phase 5: Sales Invoice JS — structural tests ────────────────────────────


class TestSalesInvoiceClientScript(UnitTestCase):

	def _app_root(self):
		import os
		return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

	def _read_js(self):
		import os
		path = os.path.join(self._app_root(), "public", "js", "sales_invoice.js")
		with open(path) as f:
			return f.read()

	def test_js_has_refresh_handler(self):
		js = self._read_js()
		self.assertIn("refresh(frm)", js)

	def test_js_has_sync_button(self):
		js = self._read_js()
		self.assertIn("Sync to TaxJar", js)
		self.assertIn("resync_transaction", js)

	def test_js_buttons_grouped_under_taxjar(self):
		js = self._read_js()
		self.assertIn('__("TaxJar")', js)

	def test_manual_sync_shows_a_dialog_on_failure(self):
		"""A failed manual sync used to leave the user with only the success
		alert wording and a Sync Status field to notice on their own - the
		callback now checks the freshly-reloaded status and surfaces the
		actual error via a dialog instead of claiming success either way."""
		js = self._read_js()
		callback_fn = js.split("callback() {")[1].split("\n\t\t\t}\n")[0]
		self.assertIn('frm.doc.taxjar_sync_status === "Failed"', callback_fn)
		self.assertIn("taxjar_integration.show_taxjar_sync_error(", callback_fn)
		self.assertIn("frm.doc.taxjar_sync_error", callback_fn)


# ── Phase 6: retry_failed_taxjar_syncs ───────────────────────────────────────


class TestRetryFailedTaxjarSyncs(UnitTestCase):

	def test_skips_when_taxjar_disabled(self):
		from taxjar_integration.taxjar_integration.tasks import retry_failed_taxjar_syncs
		with patch("taxjar_integration.taxjar_integration.tasks._is_taxjar_enabled", return_value=False), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.enqueue") as mock_enqueue:
			retry_failed_taxjar_syncs()
		mock_enqueue.assert_not_called()

	def test_enqueues_only_failed_invoices_for_filing_companies(self):
		from taxjar_integration.taxjar_integration.tasks import retry_failed_taxjar_syncs
		invoices = [
			frappe._dict(name="SINV-001", company="Co A"),
			frappe._dict(name="SINV-002", company="Co B"),
		]
		with patch("taxjar_integration.taxjar_integration.tasks._is_taxjar_enabled", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.tasks.company_creates_transactions", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.get_all", return_value=invoices), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.enqueue") as mock_enqueue:
			retry_failed_taxjar_syncs()
		self.assertEqual(mock_enqueue.call_count, 2)

	def test_skips_invoices_for_companies_with_filing_off(self):
		from taxjar_integration.taxjar_integration.tasks import retry_failed_taxjar_syncs
		invoices = [
			frappe._dict(name="SINV-001", company="Co A"),
			frappe._dict(name="SINV-002", company="Co B"),
		]
		# Only "Co A" still has transaction filing enabled.
		with patch("taxjar_integration.taxjar_integration.tasks._is_taxjar_enabled", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.tasks.company_creates_transactions",
		           side_effect=lambda company: company == "Co A"), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.get_all", return_value=invoices), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.enqueue") as mock_enqueue:
			retry_failed_taxjar_syncs()
		self.assertEqual(mock_enqueue.call_count, 1)
		self.assertEqual(mock_enqueue.call_args[1]["invoice_name"], "SINV-001")

	def test_hooks_registers_cron(self):
		from taxjar_integration import hooks
		self.assertIn("cron", hooks.scheduler_events)
		cron_tasks = hooks.scheduler_events["cron"].get("*/15 * * * *", [])
		self.assertIn("taxjar_integration.taxjar_integration.tasks.retry_failed_taxjar_syncs", cron_tasks)


# ── Phase 7: Transaction Sync page ───────────────────────────────────────────


class TestTaxJarTransactionSyncPage(UnitTestCase):

	MOD = "taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions"

	def test_read_methods_require_permission(self):
		"""get_transactions / get_summary must reject users without Sales Invoice read."""
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import (
			get_transactions,
			get_summary,
		)
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				get_transactions()
			with self.assertRaises(frappe.PermissionError):
				get_summary()
		finally:
			frappe.set_user("Administrator")

	def test_page_files_exist(self):
		import os
		page_dir = os.path.join(
			os.path.dirname(__file__),
			"..", "..", "page", "taxjar_transactions",
		)
		page_dir = os.path.normpath(page_dir)
		self.assertTrue(os.path.isfile(os.path.join(page_dir, "taxjar_transactions.py")))
		self.assertTrue(os.path.isfile(os.path.join(page_dir, "taxjar_transactions.js")))
		self.assertTrue(os.path.isfile(os.path.join(page_dir, "taxjar_transactions.json")))

	def test_get_transactions_returns_paginated_response(self):
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import get_transactions
		mock_rows = [
			frappe._dict(
				name=f"SINV-{i}", posting_date="2026-06-01", customer_name="Test",
				grand_total=100, is_return=False, is_debit_note=False,
				taxjar_sync_status="Synced", taxjar_last_synced=None, taxjar_sync_error="",
			)
			for i in range(3)
		]
		with patch(
			"taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions.frappe.get_list",
			return_value=mock_rows,
		), patch(
			"taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions.permitted_count",
			return_value=3,
		):
			result = get_transactions(filters={}, page=1)

		self.assertEqual(result["total"], 3)
		self.assertEqual(result["page"], 1)
		self.assertEqual(len(result["invoices"]), 3)
		self.assertIn("total_pages", result)
		self.assertIn("page_size", result)

	def test_get_transactions_derives_transaction_type(self):
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import get_transactions
		mock_rows = [
			frappe._dict(
				name="SINV-001", posting_date="2026-06-01", customer_name="A",
				grand_total=100, is_return=False, is_debit_note=False,
				taxjar_sync_status="Synced", taxjar_last_synced=None, taxjar_sync_error="",
			),
			frappe._dict(
				name="SINV-002", posting_date="2026-06-01", customer_name="B",
				grand_total=50, is_return=True, is_debit_note=False,
				taxjar_sync_status="Synced", taxjar_last_synced=None, taxjar_sync_error="",
			),
			frappe._dict(
				name="SINV-003", posting_date="2026-06-01", customer_name="C",
				grand_total=75, is_return=False, is_debit_note=True,
				taxjar_sync_status="Synced", taxjar_last_synced=None, taxjar_sync_error="",
			),
		]
		with patch(
			"taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions.frappe.get_list",
			return_value=mock_rows,
		), patch(
			"taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions.permitted_count",
			return_value=3,
		):
			result = get_transactions(filters={}, page=1)

		types = [r["transaction_type"] for r in result["invoices"]]
		self.assertEqual(types, ["Sales Invoice", "Credit Note", "Debit Note"])

	def test_get_transactions_derives_doc_status_label(self):
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import get_transactions
		mock_rows = [
			frappe._dict(
				name="SINV-001", posting_date="2026-06-01", customer_name="A",
				grand_total=100, is_return=False, is_debit_note=False, docstatus=0,
				taxjar_sync_status="Excluded", taxjar_last_synced=None, taxjar_sync_error="",
			),
			frappe._dict(
				name="SINV-002", posting_date="2026-06-01", customer_name="B",
				grand_total=50, is_return=False, is_debit_note=False, docstatus=1,
				taxjar_sync_status="Synced", taxjar_last_synced=None, taxjar_sync_error="",
			),
			frappe._dict(
				name="SINV-003", posting_date="2026-06-01", customer_name="C",
				grand_total=75, is_return=False, is_debit_note=False, docstatus=2,
				taxjar_sync_status="Excluded", taxjar_last_synced=None, taxjar_sync_error="",
			),
		]
		with patch(
			"taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions.frappe.get_list",
			return_value=mock_rows,
		), patch(
			"taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions.permitted_count",
			return_value=3,
		):
			result = get_transactions(filters={}, page=1)

		labels = [r["doc_status"] for r in result["invoices"]]
		self.assertEqual(labels, ["Draft", "Submitted", "Cancelled"])

	def test_get_transactions_truncates_long_error(self):
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import get_transactions
		long_error = "x" * 400
		mock_rows = [
			frappe._dict(
				name="SINV-001", posting_date="2026-06-01", customer_name="A",
				grand_total=100, is_return=False, is_debit_note=False,
				taxjar_sync_status="Failed", taxjar_last_synced=None,
				taxjar_sync_error=long_error,
			),
		]
		with patch(
			"taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions.frappe.get_list",
			return_value=mock_rows,
		), patch(
			"taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions.permitted_count",
			return_value=1,
		):
			result = get_transactions(filters={}, page=1)

		self.assertTrue(result["invoices"][0]["taxjar_sync_error"].endswith("..."))
		self.assertEqual(len(result["invoices"][0]["taxjar_sync_error"]), 303)

	def test_get_summary_counts(self):
		"""One call feeds both halves of the summary strip: the submitted /
		cancelled statuses, and a draft total counted separately."""
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import get_summary
		# get_summary aggregates in SQL (group_by status), so the mock returns
		# one row per status with a count.
		mock_rows = [
			frappe._dict(taxjar_sync_status="Synced", cnt=2),
			frappe._dict(taxjar_sync_status="Failed", cnt=1),
			frappe._dict(taxjar_sync_status="Queued", cnt=1),
			frappe._dict(taxjar_sync_status="Excluded", cnt=1),
		]
		with patch(f"{self.MOD}.frappe.db.has_column", return_value=True), patch(
			f"{self.MOD}.frappe.get_list", return_value=mock_rows
		), patch(f"{self.MOD}.permitted_count", return_value=4) as mock_count:
			result = get_summary(filters={})

		self.assertEqual(
			result["submitted"],
			{"total": 5, "synced": 2, "queued": 1, "failed": 1, "excluded": 1},
		)
		self.assertEqual(result["draft"], {"total": 4})
		# The draft total is its own docstatus 0 query, not a slice of the rows.
		self.assertEqual(mock_count.call_args[0][1]["docstatus"], 0)

	def test_summary_respects_the_table_filters(self):
		"""The strip drills into what is on screen, so both halves have to be
		scoped by the same company/date filters the table uses."""
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import get_summary

		with patch(f"{self.MOD}.frappe.db.has_column", return_value=True), patch(
			f"{self.MOD}.frappe.get_list", return_value=[]
		) as mock_get_all, patch(f"{self.MOD}.permitted_count", return_value=0) as mock_count:
			get_summary(filters={"company": "Test Co", "from_date": "2026-01-01"})

		for conditions in (mock_get_all.call_args[1]["filters"], mock_count.call_args[0][1]):
			self.assertEqual(conditions["company"], "Test Co")
			self.assertEqual(conditions["posting_date"], (">=", "2026-01-01"))

	def test_build_conditions_scopes_by_tab(self):
		"""The tabs partition the table: Included is what TaxJar actually
		received, Excluded is everything else - drafts and submitted rows left
		out alike, which is why it carries no docstatus of its own."""
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import (
			DRAFT_SCOPE,
			EXCLUDED_SCOPE,
			INCLUDED_SCOPE,
			SUBMITTED_SCOPE,
			_build_conditions,
		)

		included = _build_conditions({}, INCLUDED_SCOPE)
		self.assertEqual(included["docstatus"], ("in", (1, 2)))
		self.assertEqual(included["taxjar_sync_status"], ("in", ("Synced", "Queued", "Failed")))

		excluded = _build_conditions({}, EXCLUDED_SCOPE)
		self.assertEqual(excluded["taxjar_sync_status"], ("not in", ("Synced", "Queued", "Failed")))
		# No docstatus: drafts and submitted-but-excluded rows live together.
		self.assertNotIn("docstatus", excluded)

		# Summary-only scopes, which still count the two separately.
		self.assertEqual(_build_conditions({}, SUBMITTED_SCOPE)["docstatus"], ("in", (1, 2)))
		self.assertEqual(_build_conditions({}, DRAFT_SCOPE)["docstatus"], 0)
		# Callers that omit the scope get the Included tab.
		self.assertEqual(_build_conditions({})["docstatus"], ("in", (1, 2)))

	def test_excluded_kind_splits_the_excluded_tab(self):
		"""Drilling in from the Draft or Not Applicable card narrows the tab to
		that half."""
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import (
			EXCLUDED_SCOPE,
			_build_conditions,
		)

		draft = _build_conditions({"excluded_kind": "Draft"}, EXCLUDED_SCOPE)
		self.assertEqual(draft["docstatus"], 0)

		na = _build_conditions({"excluded_kind": "Not Applicable"}, EXCLUDED_SCOPE)
		self.assertEqual(na["docstatus"], ("in", (1, 2)))

	def test_get_transactions_passes_the_scope_through(self):
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import (
			EXCLUDED_SCOPE,
			get_transactions,
		)

		with patch(f"{self.MOD}.frappe.db.has_column", return_value=True), patch(
			f"{self.MOD}.frappe.get_list", return_value=[]
		), patch(f"{self.MOD}.permitted_count", return_value=0) as mock_count:
			get_transactions(filters={}, page=1, scope=EXCLUDED_SCOPE)

		self.assertEqual(
			mock_count.call_args[0][1]["taxjar_sync_status"],
			("not in", ("Synced", "Queued", "Failed")),
		)

	def test_build_conditions_date_range(self):
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import _build_conditions

		conditions = _build_conditions({"from_date": "2026-01-01", "to_date": "2026-06-30"})
		self.assertEqual(conditions["posting_date"], ("between", ("2026-01-01", "2026-06-30")))

		conditions = _build_conditions({"from_date": "2026-01-01"})
		self.assertEqual(conditions["posting_date"], (">=", "2026-01-01"))

		conditions = _build_conditions({"to_date": "2026-06-30"})
		self.assertEqual(conditions["posting_date"], ("<=", "2026-06-30"))

		conditions = _build_conditions({})
		self.assertNotIn("posting_date", conditions)

	def test_build_conditions_always_includes_docstatus(self):
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import _build_conditions
		conditions = _build_conditions({})
		self.assertEqual(conditions["docstatus"], ("in", (1, 2)))

	def test_build_conditions_with_company_and_sync_status(self):
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import _build_conditions
		conditions = _build_conditions({"company": "Test Co", "sync_status": "Failed"})
		self.assertEqual(conditions["company"], "Test Co")
		self.assertEqual(conditions["taxjar_sync_status"], "Failed")

	def test_get_transactions_page_clamped_to_min_1(self):
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import get_transactions
		with patch(
			"taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions.frappe.get_list",
			return_value=[],
		), patch(
			"taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions.permitted_count",
			return_value=0,
		):
			result = get_transactions(filters={}, page=-5)
		self.assertEqual(result["page"], 1)

	def test_retry_action_offered_only_for_failed_rows(self):
		"""The action itself is scoped to the Failed rows in the selection, and
		the "{n} retryable" counter beside it spells out how many of the
		selected rows that actually is."""
		js = self._transactions_js()
		bulk_fn = js.split("update_bulk_state() {")[1].split("\n\t}\n")[0]
		self.assertIn('__("Resync with TaxJar")', bulk_fn)
		self.assertIn('__("{0} selected · {1} retryable"', bulk_fn)
		self.assertIn('row.taxjar_sync_status === "Failed"', bulk_fn)
		self.assertIn("bulk_retry", js)

	def _transactions_js(self):
		import os
		js_path = os.path.join(
			os.path.dirname(__file__),
			"..", "..", "page", "taxjar_transactions", "taxjar_transactions.js",
		)
		with open(os.path.normpath(js_path)) as f:
			return f.read()

	def _columns_fn(self):
		js = self._transactions_js()
		return js.split("\tget_columns() {")[1].split("\n\t}\n")[0]

	def test_column_order_and_no_last_synced_or_error_columns(self):
		"""Posting Date, Transaction ID, Customer, Type, Grand Total,
		Transaction Status, Sync Status - in that order. Last Synced and Error
		are not columns of their own; that information surfaces through the
		Sync Status cell instead."""
		columns_fn = self._columns_fn()
		order = [
			"Posting Date", "Transaction ID", "Customer", "Type", "Grand Total",
			"Transaction Status", "Sync Status",
		]
		indexes = [columns_fn.index('__("%s")' % col) for col in order]
		self.assertEqual(indexes, sorted(indexes))
		self.assertNotIn('__("Last Synced")', columns_fn)
		self.assertNotIn('__("Error")', columns_fn)

	def test_sync_status_column_only_on_the_included_tab(self):
		"""Excluded is defined as the rows that never got a sync status, so the
		column would read empty on every one of them."""
		columns_fn = self._columns_fn()
		self.assertIn("if (this.active_tab === INCLUDED_TAB) {", columns_fn)
		sync_block = columns_fn.split("if (this.active_tab === INCLUDED_TAB) {")[1]
		self.assertIn('__("Sync Status")', sync_block)
		# Transaction Status is gated the same way: on the Draft tab every row
		# would read "Draft".
		self.assertIn('__("Transaction Status")', sync_block)

	def test_excluded_tab_has_no_checkbox_column(self):
		"""Nothing there has been sent, so there is no bulk action to run on it
		and offering selection would lead nowhere."""
		js = self._transactions_js()
		self.assertIn("checkboxColumn: key === INCLUDED_TAB", js)

	def _sync_status_cell_fn(self):
		js = self._transactions_js()
		return js.split("render_sync_status_cell(row) {")[1].split("\n\t}\n")[0]

	def test_sync_status_cell_uses_one_shape_for_every_status(self):
		"""Failed reads the same as every other status - a pill plus (when
		there is something to say) a separate info icon, never a special-cased
		warning icon + Retry button. Retrying goes through the checkbox and the
		Bulk Action menu instead."""
		cell_fn = self._sync_status_cell_fn()
		self.assertNotIn("triangle-alert", cell_fn)
		self.assertNotIn("taxjar-retry-chip", cell_fn)
		self.assertNotIn("taxjar-retry-one", cell_fn)
		self.assertIn("row.taxjar_sync_error", cell_fn)

	def test_info_icon_only_for_failed(self):
		"""Synced makes the pill itself the trigger for its last-synced time.
		Failed needs the separate icon, since the pill text cannot carry an
		error. Queued and Excluded say all they have to say in the pill, so an
		icon there would promise a detail that does not exist."""
		cell_fn = self._sync_status_cell_fn()
		self.assertIn('frappe.utils.icon("info", "sm")', cell_fn)
		self.assertIn('__("Last synced: {0}"', cell_fn)
		self.assertNotIn('__("Queued for sync")', cell_fn)
		self.assertIn('if (status !== "Failed") return pill;', cell_fn)
		# Info icon must be a separate element, not nested inside the badge.
		self.assertIn("const pill = frappe.ui.badge.html({ label, theme: color });", cell_fn)
		self.assertNotIn("indicator-pill", cell_fn)
		self.assertIn("return `${pill}${icon}`;", cell_fn)

	def test_no_native_title_tooltip_on_sync_icon(self):
		"""A native title attribute has a browser-enforced show delay and never
		responds to a click - the popover is hand-rolled instead (see
		_show_sync_popover), same reasoning as the guided setup's own
		.ts-info-btn/.ts-info-pop pattern."""
		cell_fn = self._sync_status_cell_fn()
		self.assertNotIn("title=", cell_fn)

	def test_sync_popover_shown_on_both_hover_and_click(self):
		"""Hover never fires on a touch device, so click has to work too."""
		js = self._transactions_js()
		bind_fn = js.split("bind_sync_popover($wrapper) {")[1].split("\n\t}\n")[0]
		for event in ("mouseenter", "mouseleave", "click"):
			self.assertIn('$wrapper.on("%s", ".taxjar-sync-trigger"' % event, bind_fn)
		self.assertIn("_show_sync_popover", bind_fn)

	def test_sync_popover_shows_and_hides_without_delay(self):
		js = self._transactions_js()
		show_fn = js.split("_show_sync_popover($trigger) {")[1].split("\n\t}\n")[0]
		self.assertIn("taxjar-sync-pop", show_fn)
		self.assertNotIn("setTimeout", show_fn)
		hide_fn = js.split("_hide_sync_popover() {")[1].split("\n\t}\n")[0]
		self.assertNotIn("setTimeout", hide_fn)

	def test_sync_icon_css_uses_pointer_cursor_not_help(self):
		"""cursor: help renders the browser's own question-mark cursor glyph
		next to the pointer - easy to mistake for a stray "?" over the icon."""
		import os
		css_path = os.path.normpath(os.path.join(
			os.path.dirname(__file__),
			"..", "..", "page", "taxjar_transactions", "taxjar_transactions.css",
		))
		with open(css_path) as f:
			css = f.read()
		self.assertIn("cursor: pointer;", css)
		self.assertNotIn("cursor: help;", css)


# ── Hooks registration — updated hooks ───────────────────────────────────────


class TestHooksUpdated(UnitTestCase):

	def test_sales_invoice_on_submit_is_enqueue(self):
		from taxjar_integration import hooks
		si_events = hooks.doc_events.get("Sales Invoice", {})
		self.assertIn("enqueue_taxjar_sync", si_events.get("on_submit", ""))

	def test_sales_invoice_on_cancel_is_enqueue(self):
		from taxjar_integration import hooks
		si_events = hooks.doc_events.get("Sales Invoice", {})
		self.assertIn("enqueue_taxjar_delete", si_events.get("on_cancel", ""))

	def test_sales_invoice_validate_has_return_against(self):
		from taxjar_integration import hooks
		si_events = hooks.doc_events.get("Sales Invoice", {})
		self.assertIn("validate_return_against", si_events.get("validate", ""))

	def test_customer_retry_cron_registered(self):
		from taxjar_integration import hooks
		cron_tasks = hooks.scheduler_events.get("cron", {}).get("*/15 * * * *", [])
		self.assertIn("taxjar_integration.taxjar_integration.tasks.retry_failed_taxjar_customer_syncs", cron_tasks)


# ── Customer sync status tracking ────────────────────────────────────────────


class TestCustomerSyncStatusTracking(UnitTestCase):

	def _make_customer_doc(self, exemption_type="Wholesale", exempt_regions=None, customer_id=""):
		doc = MagicMock()
		doc.customer_name = "Acme Corp"
		doc.get.side_effect = lambda field, default=None: {
			"taxjar_exemption_type": exemption_type,
			"taxjar_exempt_regions": exempt_regions or [],
			"taxjar_customer_id": customer_id,
		}.get(field, default)
		return doc

	def test_sync_sets_synced_status_on_success(self):
		customer_doc = self._make_customer_doc(customer_id="CUST-001")
		mock_client = MagicMock()
		mock_client.update_customer.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=customer_doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.set_value") as mock_set, \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_customer_sync_status") as mock_status:
			sync_customer_to_taxjar("CUST-001", company="Test Co")

		mock_status.assert_called_once_with("CUST-001", "Synced")

	def test_sync_sets_failed_status_on_api_error(self):
		import taxjar.exceptions

		customer_doc = self._make_customer_doc(customer_id="")
		mock_client = MagicMock()
		err = taxjar.exceptions.TaxJarResponseError(MagicMock())
		err.full_response = {"status_code": 500, "detail": "Server error"}
		mock_client.create_customer.side_effect = err

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=customer_doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_customer_sync_status") as mock_status:
			sync_customer_to_taxjar("CUST-001", company="Test Co")

		mock_status.assert_called_once()
		self.assertEqual(mock_status.call_args[0][1], "Failed")

	def test_sync_sets_failed_on_create_fallback_error(self):
		"""Update returns 404 → create also fails → status should be Failed."""
		import taxjar.exceptions

		customer_doc = self._make_customer_doc(customer_id="CUST-001")
		mock_client = MagicMock()

		update_err = taxjar.exceptions.TaxJarResponseError(MagicMock())
		update_err.full_response = {"status_code": 404}
		mock_client.update_customer.side_effect = update_err

		create_err = taxjar.exceptions.TaxJarResponseError(MagicMock())
		create_err.full_response = {"status_code": 500, "detail": "Create failed"}
		mock_client.create_customer.side_effect = create_err

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_doc", return_value=customer_doc), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._set_customer_sync_status") as mock_status:
			sync_customer_to_taxjar("CUST-001", company="Test Co")

		failed_calls = [c for c in mock_status.call_args_list if c[0][1] == "Failed"]
		self.assertTrue(len(failed_calls) > 0)


# ── Customer sync custom fields ──────────────────────────────────────────────


class TestCustomerSyncStatusFields(UnitTestCase):

	def _get_customer_field_defs(self):
		captured = {}
		def fake_create(fields, update=True):
			captured.update(fields)
		with patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.create_custom_fields", side_effect=fake_create), \
		     patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.make_property_setter"):
			make_custom_fields(update=True)
		return {f["fieldname"]: f for f in captured.get("Customer", [])}

	def test_sync_status_field_exists(self):
		fields = self._get_customer_field_defs()
		f = fields["taxjar_customer_sync_status"]
		self.assertEqual(f["fieldtype"], "Select")
		for opt in ("Queued", "Synced", "Failed"):
			self.assertIn(opt, f["options"])
		self.assertTrue(f.get("read_only"))

	def test_sync_error_field_exists(self):
		fields = self._get_customer_field_defs()
		f = fields["taxjar_customer_sync_error"]
		self.assertEqual(f["fieldtype"], "Small Text")
		self.assertTrue(f.get("read_only"))
		self.assertIn("Failed", f.get("depends_on", ""))


# ── Customer retry scheduled task ────────────────────────────────────────────


class TestRetryFailedCustomerSyncs(UnitTestCase):

	def test_skips_when_features_disabled(self):
		from taxjar_integration.taxjar_integration.tasks import retry_failed_taxjar_customer_syncs
		with patch("taxjar_integration.taxjar_integration.tasks._is_taxjar_enabled", return_value=False), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.enqueue") as mock_enqueue:
			retry_failed_taxjar_customer_syncs()
		mock_enqueue.assert_not_called()

	def test_enqueues_failed_customers(self):
		from taxjar_integration.taxjar_integration.tasks import retry_failed_taxjar_customer_syncs

		config = MagicMock(company="Test Co")
		settings = MagicMock()
		settings.company_config = [config]

		with patch("taxjar_integration.taxjar_integration.tasks._is_taxjar_enabled", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.get_all", return_value=["CUST-001", "CUST-002"]), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.get_single", return_value=settings), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.enqueue") as mock_enqueue:
			retry_failed_taxjar_customer_syncs()

		self.assertEqual(mock_enqueue.call_count, 2)


# ── Customer JS — button removed ─────────────────────────────────────────────


class TestCustomerClientScriptUpdated(UnitTestCase):

	def _app_root(self):
		import os
		return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

	def _read_js(self):
		import os
		path = os.path.join(self._app_root(), "public", "js", "customer.js")
		with open(path) as f:
			return f.read()

	def test_has_sync_button(self):
		"""Manual Sync to TaxJar button should exist for force-syncing."""
		js = self._read_js()
		self.assertIn("Sync to TaxJar", js)

	def test_no_auto_fill_customer_id(self):
		"""taxjar_customer_id should NOT be auto-filled in JS — only set server-side on sync."""
		js = self._read_js()
		self.assertNotIn("frm.set_value(\"taxjar_customer_id\"", js)
		self.assertNotIn("frm.set_value('taxjar_customer_id'", js)

	def test_sync_button_grouped_under_taxjar(self):
		js = self._read_js()
		self.assertIn('__("TaxJar")', js)

	def test_manual_sync_shows_a_dialog_on_failure(self):
		"""A failed manual sync used to leave the user with only the "queued"
		alert and a Sync Status field to notice on their own - the .then()
		chain now checks the freshly-reloaded status and surfaces the actual
		error via a dialog instead of claiming success either way."""
		js = self._read_js()
		sync_click = js.split('"taxjar_integration.taxjar_integration.taxjar_integration.resync_customer",')[1].split(
			"\n\t\t\t\t},\n"
		)[0]
		self.assertIn('frm.doc.taxjar_customer_sync_status === "Failed"', sync_click)
		self.assertIn("taxjar_integration.show_taxjar_sync_error(", sync_click)
		self.assertIn("frm.doc.taxjar_customer_sync_error", sync_click)

	def test_dead_state_filter_code_removed(self):
		"""The raw taxjar_exempt_regions grid is hidden and configure_exemption
		is the only write path now - the per-row state-filter code that kept
		that grid usable has nothing left to run for."""
		js = self._read_js()
		self.assertNotIn("_apply_state_filter", js)
		self.assertNotIn("_get_state_options", js)
		self.assertNotIn('frappe.ui.form.on("TaxJar Customer Exempt Region"', js)

	def test_manage_exemption_dialog_present(self):
		js = self._read_js()
		self.assertIn("function open_manage_exemption_dialog(frm)", js)
		self.assertIn("__(\"Apply\")", js)
		dialog_fn = js.split("function open_manage_exemption_dialog(frm) {")[1].split("\nfunction ")[0]
		self.assertIn("configure_exemption", dialog_fn)
		# Single-customer write, not the list page's bulk rows.map(...) shape.
		self.assertIn("customers: [frm.doc.name]", dialog_fn)

	def test_manage_exemption_dialog_uses_shared_region_helpers(self):
		js = self._read_js()
		dialog_fn = js.split("function open_manage_exemption_dialog(frm) {")[1].split("\nfunction ")[0]
		self.assertIn("taxjar_integration.build_region_multicheck_fields", dialog_fn)
		self.assertIn("taxjar_integration.get_selected_regions", dialog_fn)
		self.assertIn("taxjar_integration.wire_exemption_dialog", dialog_fn)

	def test_exemption_summary_present(self):
		js = self._read_js()
		self.assertIn("function render_exemption_summary(frm)", js)
		summary_fn = js.split("function render_exemption_summary(frm) {")[1].split("\nfunction ")[0]
		self.assertIn("No exemption configured.", summary_fn)
		self.assertIn("taxjar-manage-exemption-btn", summary_fn)
		self.assertIn("_exemption_card_body(frm)", summary_fn)

	def test_exemption_summary_reuses_the_address_card_styling(self):
		"""Reusing frappe's own .address-box/.edit-btn classes and pencil icon
		(rather than inventing parallel CSS or a different icon) is what makes
		this look identical to the Address card for free - .edit-btn's
		absolute top-right positioning is a CSS rule scoped to being inside
		.address-box."""
		js = self._read_js()
		summary_fn = js.split("function render_exemption_summary(frm) {")[1].split("\nfunction ")[0]
		self.assertIn('class="address-box"', summary_fn)
		self.assertIn("edit-btn", summary_fn)
		self.assertIn('frappe.utils.icon("pencil", "xs")', summary_fn)

	def test_exemption_card_body_non_exempt(self):
		js = self._read_js()
		fn = js.split("function _exemption_card_body(frm) {")[1].split("\nfunction ")[0]
		self.assertIn('type === "Non Exempt"', fn)
		self.assertIn("Non-Exempted", fn)
		self.assertIn("Sales tax is applicable.", fn)

	def test_exemption_card_body_splits_regions_by_country(self):
		"""Two separate blocks (US States / CA Provinces), not one
		comma-joined line across both countries - each is built by the same
		shared helper so a full country collapses to just its name."""
		js = self._read_js()
		fn = js.split("function _exemption_card_body(frm) {")[1].split("\nfunction ")[0]
		self.assertIn(
			'_exemption_region_block("US", us_codes, taxjar_integration.US_STATE_CODES, __("United States"), __("US States"), __("All states exempted"))',
			fn,
		)
		self.assertIn(
			'_exemption_region_block("CA", ca_codes, taxjar_integration.CA_PROVINCE_CODES, __("Canada"), __("CA Provinces"), __("All provinces exempted"))',
			fn,
		)
		self.assertIn("No regions selected", fn)
		self.assertIn('<span>${__("Exempted")}</span>', fn)

	def test_exemption_region_block_collapses_a_full_country_to_its_name(self):
		"""A fully-selected country still shows its name (unchanged from
		before), plus a small caption confirming every state/province is
		checked - otherwise "United States" alone reads the same whether one
		state or all fifty are selected."""
		js = self._read_js()
		fn = js.split(
			"function _exemption_region_block(country, codes, all_codes, country_name, label, all_selected_text) {"
		)[1].split("\nfunction ")[0]
		self.assertIn("if (codes.length === all_codes.length) {", fn)
		self.assertIn("frappe.utils.escape_html(country_name)", fn)
		self.assertIn("${all_selected_text}", fn)
		# The country name's own <p> must carry the tight margin, not the
		# caption's - the caption is the pair's LAST line, so it's the one
		# that needs the default bottom margin to separate this block from
		# the next country's, same shape the un-collapsed branch already
		# gets right below (label tight, value carries the gap). Bold and
		# regular size (not text-muted or `small`), so it reads as a heading
		# one step down from the type header, with the muted `small` caption
		# below it one step down again - a three-tier size/weight hierarchy,
		# not just a color difference.
		collapsed_branch = fn.split("if (codes.length === all_codes.length) {")[1].split("\n\t}")[0]
		self.assertIn('<p style="margin-bottom: 0;"><strong>${frappe.utils.escape_html(country_name)}</strong></p>', collapsed_branch)
		self.assertIn('<p class="text-muted small">${all_selected_text}</p>', collapsed_branch)
		# The un-collapsed branch still shows the "US States"/"CA Provinces"
		# label above the comma-joined, sorted full-name list - also bold and
		# regular-size, same reasoning as the collapsed branch above.
		self.assertIn('<p style="margin-bottom: 0;"><strong>${label}</strong></p>', fn)
		self.assertIn(
			'.map((code) => taxjar_integration.region_full_name(country, code))\n\t\t.sort()\n\t\t.join(", ");',
			fn,
		)

	def test_refresh_renders_exemption_summary(self):
		js = self._read_js()
		refresh_fn = js.split("refresh(frm) {")[1].split("\n\t},")[0]
		self.assertIn("render_exemption_summary(frm)", refresh_fn)


# ── Shared region-grid + mandatory-region helpers — taxjar_utils.js ────────


class TestSharedRegionHelpersJS(UnitTestCase):

	def _js_dir(self):
		import os
		return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "public", "js"))

	def _read_js(self, filename):
		import os
		with open(os.path.join(self._js_dir(), filename)) as f:
			return f.read()

	def test_show_taxjar_sync_error_links_guided_setup(self):
		"""The stored Sync Error field is a Small Text field (plain text, not
		HTML) - only this dialog's own rendering turns the phrase "guided
		setup" (from classify_taxjar_error's 401 message) into an actual
		link, without touching what gets saved to that field."""
		js = self._read_js("taxjar_utils.js")
		fn = js.split("taxjar_integration.show_taxjar_sync_error = function (title, message) {")[1].split(
			"\n};"
		)[0]
		self.assertIn("frappe.utils", fn)
		self.assertIn(".escape_html(message)", fn)
		self.assertIn('<a href="/app/taxjar-setup">', fn)
		self.assertIn('frappe.msgprint({ title, message: html, indicator: "red" });', fn)

	def test_build_region_multicheck_fields_present(self):
		js = self._read_js("taxjar_utils.js")
		self.assertIn("taxjar_integration.build_region_multicheck_fields = function (selected)", js)
		self.assertIn("taxjar_integration.REGION_NAMES_BY_COUNTRY", js)

	def test_region_fields_are_multicheck_not_a_hand_built_grid(self):
		"""Real desk MultiCheck fields (with their own built-in Select All /
		Unselect All buttons), not a checkbox grid or table re-implemented
		here - one per country, driven by full names via region_full_name."""
		js = self._read_js("taxjar_utils.js")
		fn = js.split("taxjar_integration.build_region_multicheck_fields = function (selected) {")[1].split(
			"\n};"
		)[0]
		self.assertIn('fieldtype: "MultiCheck"', fn)
		self.assertIn("select_all: true", fn)
		self.assertIn("taxjar_integration.region_full_name(country, code)", fn)
		self.assertIn("taxjar_us_states", fn)
		self.assertIn("taxjar_ca_provinces", fn)

	def test_region_section_is_named_for_later_show_hide(self):
		"""Named (rather than left to Layout's auto __section_N fieldname) so
		wire_exemption_dialog can address it directly - otherwise there is
		no stable handle to hide the section itself, only its individual
		fields, once none of them have anything to show."""
		js = self._read_js("taxjar_utils.js")
		fn = js.split("taxjar_integration.build_region_multicheck_fields = function (selected) {")[1].split(
			"\n};"
		)[0]
		self.assertIn('{ fieldtype: "Section Break", fieldname: "taxjar_regions_section" }', fn)

	def test_multicheck_columns_css_is_injected(self):
		"""MultiCheck's own `columns` option needs `.checkbox-options {
		columns: var(--checkbox-options-columns) }`, which frappe ships only
		in its website stylesheet - absent from the desk bundle - so without
		this the region lists would render as one long single column."""
		js = self._read_js("taxjar_utils.js")
		self.assertIn("taxjar_integration._inject_multicheck_column_styles = function ()", js)
		fn = js.split("taxjar_integration._inject_multicheck_column_styles = function () {")[1].split(
			"\n};"
		)[0]
		self.assertIn("checkbox-options-columns", fn)

	def test_get_selected_regions_reads_both_multicheck_fields(self):
		js = self._read_js("taxjar_utils.js")
		fn = js.split("taxjar_integration.get_selected_regions = function (dialog) {")[1].split("\n};")[0]
		self.assertIn('dialog.get_value("taxjar_us_states")', fn)
		self.assertIn('dialog.get_value("taxjar_ca_provinces")', fn)

	def test_wire_exemption_dialog_present(self):
		js = self._read_js("taxjar_utils.js")
		self.assertIn("taxjar_integration.wire_exemption_dialog = function (dialog)", js)
		fn = js.split("taxjar_integration.wire_exemption_dialog = function (dialog) {")[1].split("\n};")[0]
		self.assertIn("disable_primary_action", fn)
		self.assertIn("enable_primary_action", fn)
		# Select All/Unselect All set checkbox.checked directly, which never
		# fires a DOM "change" event - on_change is the control's own hook,
		# the only reliable place this catches both that and single clicks.
		self.assertIn("taxjar_us_states.df.on_change", fn)
		self.assertIn("taxjar_ca_provinces.df.on_change", fn)

	def test_wire_exemption_dialog_clears_regions_for_a_non_requiring_type(self):
		"""Switching to a type that doesn't take regions (blank, or Non
		Exempt) must drop whatever was checked for the previous type -
		otherwise regions picked for e.g. Wholesale silently ride along
		under Non Exempt with no visible sign they were ever selected for a
		different reason. select_all(true) is the same call the "Unselect
		All" button makes - not the destructive toggle()-driven refresh()
		update_visibility uses."""
		js = self._read_js("taxjar_utils.js")
		fn = js.split("taxjar_integration.wire_exemption_dialog = function (dialog) {")[1].split("\n};")[0]
		clear_fn = fn.split("const clear_regions_if_not_required = () => {")[1].split("\n\t};")[0]
		self.assertIn("if (EXEMPTION_TYPES_REQUIRING_REGIONS.has(dialog.get_value(\"exemption_type\"))) return;", clear_fn)
		self.assertIn("taxjar_us_states.select_all(true)", clear_fn)
		self.assertIn("taxjar_ca_provinces.select_all(true)", clear_fn)
		# Wired into the returned update() the caller invokes on every
		# exemption_type change, not just once at dialog construction.
		returned = fn.split("return () => {")[1].split("\n\t};")[0]
		self.assertIn("clear_regions_if_not_required();", returned)

	def test_wire_exemption_dialog_hides_regions_for_non_exempt_too(self):
		"""Non Exempt takes no regions, same as no type chosen - the grid
		(and Select All controls) must hide for both, not just blank.
		Gating on EXEMPTION_TYPES_REQUIRING_REGIONS rather than "any type
		chosen" is what makes Non Exempt behave like blank here."""
		js = self._read_js("taxjar_utils.js")
		fn = js.split("taxjar_integration.wire_exemption_dialog = function (dialog) {")[1].split("\n};")[0]
		visibility_fn = fn.split("const update_visibility = () => {")[1].split("\n\t};")[0]
		self.assertIn("EXEMPTION_TYPES_REQUIRING_REGIONS.has(type)", visibility_fn)
		self.assertNotIn("!!dialog.get_value", visibility_fn)
		self.assertIn("taxjar_us_states.toggle(enabled)", visibility_fn)
		self.assertIn("taxjar_ca_provinces.toggle(enabled)", visibility_fn)

	def test_wire_exemption_dialog_hides_the_whole_section_for_non_exempt(self):
		"""Hiding the grid alone still leaves the Section Break's own divider
		and padding behind as bare whitespace for a type with nothing to
		show (blank, or Non Exempt) - the section itself must hide too, via
		its own show()/hide() (not a Control, so no .toggle())."""
		js = self._read_js("taxjar_utils.js")
		fn = js.split("taxjar_integration.wire_exemption_dialog = function (dialog) {")[1].split("\n};")[0]
		visibility_fn = fn.split("const update_visibility = () => {")[1].split("\n\t};")[0]
		self.assertIn("if (enabled) {", visibility_fn)
		self.assertIn("taxjar_regions_section.show();", visibility_fn)
		self.assertIn("taxjar_regions_section.hide();", visibility_fn)

	def test_wire_exemption_dialog_has_no_leftover_hint_field(self):
		"""The "choose a type" hint used to leave the section visible - and
		the whitespace it occupied - for blank and Non Exempt alike. Removed
		outright rather than toggled: the section itself already hides for
		both, so there was nothing left for the hint to usefully say."""
		js = self._read_js("taxjar_utils.js")
		self.assertNotIn("taxjar_regions_hint", js)
		self.assertNotIn("Choose an exemption type to select exempt regions", js)


# ── TaxJar Customer API — delete_customer_from_taxjar ─────────────────────


class TestDeleteCustomerFromTaxJar(UnitTestCase):

	def test_happy_path_delete(self):
		"""Successful delete should log success."""
		mock_client = MagicMock()
		mock_client.delete_customer.return_value = MagicMock()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call") as mock_log:
			delete_customer_from_taxjar("CUST-001", company="Test Co")

		mock_client.delete_customer.assert_called_once_with("CUST-001")
		success_calls = [c for c in mock_log.call_args_list if c[1].get("status") == "success"]
		self.assertTrue(len(success_calls) > 0)

	def test_404_treated_as_success(self):
		"""Deleting a customer that doesn't exist in TaxJar should not raise."""
		import taxjar.exceptions

		mock_client = MagicMock()
		err = taxjar.exceptions.TaxJarResponseError(MagicMock())
		err.full_response = {"status_code": 404}
		mock_client.delete_customer.side_effect = err

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			delete_customer_from_taxjar("CUST-001")  # should not raise

	def test_500_error_raises(self):
		"""Non-404 API errors should be re-raised."""
		import taxjar.exceptions

		mock_client = MagicMock()
		err = taxjar.exceptions.TaxJarResponseError(MagicMock())
		err.full_response = {"status_code": 500}
		mock_client.delete_customer.side_effect = err

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			with self.assertRaises(taxjar.exceptions.TaxJarResponseError):
				delete_customer_from_taxjar("CUST-001")

	def test_skips_when_no_client(self):
		"""Should return early when client is None."""
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=None):
			delete_customer_from_taxjar("CUST-001")  # should not raise

	def test_connection_error_raises(self):
		"""TaxJarConnectionError should be re-raised."""
		import taxjar.exceptions

		mock_client = MagicMock()
		mock_client.delete_customer.side_effect = taxjar.exceptions.TaxJarConnectionError("timeout")

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_client", return_value=mock_client), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"):
			with self.assertRaises(taxjar.exceptions.TaxJarConnectionError):
				delete_customer_from_taxjar("CUST-001")


# ── TaxJar Customer API — on_customer_delete hook ──────────────────────────


class TestOnCustomerDelete(UnitTestCase):

	def _make_customer_doc(self, customer_id="CUST-001"):
		doc = MagicMock()
		doc.name = "CUST-001"
		doc.get.side_effect = lambda field, default=None: {
			"taxjar_customer_id": customer_id,
		}.get(field, default)
		return doc

	def test_calls_delete_when_customer_id_set(self):
		doc = self._make_customer_doc(customer_id="CUST-001")
		config = MagicMock(company="Test Co")
		settings = MagicMock()
		settings.company_config = [config]

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_single", return_value=settings), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.delete_customer_from_taxjar") as mock_delete:
			on_customer_delete(doc, None)

		mock_delete.assert_called_once_with("CUST-001", "Test Co")

	def test_skips_when_no_customer_id(self):
		doc = self._make_customer_doc(customer_id="")

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.delete_customer_from_taxjar") as mock_delete:
			on_customer_delete(doc, None)

		mock_delete.assert_not_called()

	def test_skips_when_features_disabled(self):
		doc = self._make_customer_doc(customer_id="CUST-001")

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=0), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.delete_customer_from_taxjar") as mock_delete:
			on_customer_delete(doc, None)

		mock_delete.assert_not_called()

	def test_does_not_block_delete_on_api_error(self):
		"""API errors during delete should be caught, not prevent Customer deletion."""
		doc = self._make_customer_doc(customer_id="CUST-001")
		config = MagicMock(company="Test Co")
		settings = MagicMock()
		settings.company_config = [config]

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.get_single", return_value=settings), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.delete_customer_from_taxjar", side_effect=Exception("API down")), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.log_taxjar_call"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration._get_taxjar_logger"):
			on_customer_delete(doc, None)  # should not raise

	def test_hooks_registers_on_trash(self):
		from taxjar_integration import hooks
		customer_events = hooks.doc_events.get("Customer", {})
		self.assertIn("on_trash", customer_events)
		self.assertIn("on_customer_delete", customer_events["on_trash"])


# ── TaxJar Customer API — _make_safe_customer_id ──────────────────────────


class TestMakeSafeCustomerId(UnitTestCase):

	def test_simple_name_unchanged(self):
		self.assertEqual(_make_safe_customer_id("Acme"), "Acme")

	def test_alphanumeric_with_digits(self):
		self.assertEqual(_make_safe_customer_id("Customer123"), "Customer123")

	def test_spaces_replaced_with_hyphens(self):
		self.assertEqual(_make_safe_customer_id("Denna Jaina"), "Denna-Jaina")

	def test_multiple_spaces_collapsed(self):
		self.assertEqual(_make_safe_customer_id("Don  Bosco"), "Don-Bosco")

	def test_apostrophe_replaced(self):
		self.assertEqual(_make_safe_customer_id("O'Brien"), "O-Brien")

	def test_ampersand_replaced(self):
		self.assertEqual(_make_safe_customer_id("AT&T Corp"), "AT-T-Corp")

	def test_mixed_special_chars(self):
		self.assertEqual(_make_safe_customer_id("Smith & O'Neal (LLC)"), "Smith-O-Neal-LLC")

	def test_leading_trailing_specials_stripped(self):
		self.assertEqual(_make_safe_customer_id(" -Test- "), "Test")

	def test_already_safe_id_unchanged(self):
		self.assertEqual(_make_safe_customer_id("CUST-001"), "CUST-001")

	def test_hyphens_preserved(self):
		self.assertEqual(_make_safe_customer_id("some-id"), "some-id")

	def test_unicode_replaced(self):
		result = _make_safe_customer_id("Müller GmbH")
		self.assertNotIn("ü", result)
		self.assertIn("ller", result)


# ── TaxJar Customer API — _has_taxjar_fields_changed with customer_name ────


class TestHasTaxjarFieldsChangedCustomerName(UnitTestCase):

	def test_customer_name_change_triggers_sync(self):
		"""Changing customer_name should trigger sync even if exemption fields unchanged."""
		doc = MagicMock()
		doc.has_value_changed.side_effect = lambda f: f == "customer_name"
		doc.get.return_value = []
		self.assertTrue(_has_taxjar_fields_changed(doc))

	def test_no_change_returns_false(self):
		"""No changes to any tracked field should return False."""
		doc = MagicMock()
		doc.has_value_changed.return_value = False
		old_region = MagicMock(country="US", state="TX")
		previous = MagicMock()
		previous.get.return_value = [old_region]
		doc.get_doc_before_save.return_value = previous
		new_region = MagicMock(country="US", state="TX")
		doc.get.return_value = [new_region]
		self.assertFalse(_has_taxjar_fields_changed(doc))


# ── on_customer_validate — preserve read-only TaxJar fields ───────────────


class TestOnCustomerValidate(UnitTestCase):

	def _make_doc(self, customer_id="", sync_status="", sync_error="", last_synced=""):
		doc = MagicMock()
		doc.name = "CUST-001"
		doc.is_new.return_value = False
		_values = {
			"taxjar_customer_id": customer_id,
			"taxjar_customer_sync_status": sync_status,
			"taxjar_customer_sync_error": sync_error,
			"taxjar_last_synced": last_synced,
		}
		doc.get.side_effect = lambda f, d=None: _values.get(f, d)
		return doc

	def test_preserves_customer_id_from_stale_overwrite(self):
		"""Form save with stale empty taxjar_customer_id must restore the DB value."""
		doc = self._make_doc(customer_id="")
		db_values = frappe._dict(
			taxjar_customer_id="CUST-001", taxjar_customer_sync_status="Synced",
			taxjar_customer_sync_error="", taxjar_last_synced="2026-06-20 10:00:00",
		)

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value(db_values)):
			on_customer_validate(doc, None)

		doc.set.assert_any_call("taxjar_customer_id", "CUST-001")

	def test_preserves_sync_status_from_stale_blank(self):
		"""Sync status should also be preserved from stale form data."""
		doc = self._make_doc(sync_status="")
		db_values = frappe._dict(
			taxjar_customer_id="CUST-001", taxjar_customer_sync_status="Synced",
			taxjar_customer_sync_error="", taxjar_last_synced="",
		)

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value(db_values)):
			on_customer_validate(doc, None)

		doc.set.assert_any_call("taxjar_customer_sync_status", "Synced")

	def test_restores_sync_status_from_a_stale_non_blank_value(self):
		"""The actual reported bug: a background sync flips the DB to Synced
		while an open form still holds "Queued" from before the job ran (the
		form never reloaded). The old guard only restored a *blank* stale
		value, so a stale-but-non-blank "Queued" sailed through unguarded and
		overwrote "Synced" back to "Queued" on the form's next save."""
		doc = self._make_doc(sync_status="Queued")
		db_values = frappe._dict(
			taxjar_customer_id="CUST-001", taxjar_customer_sync_status="Synced",
			taxjar_customer_sync_error="", taxjar_last_synced="2026-06-20 10:00:00",
		)

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value(db_values)):
			on_customer_validate(doc, None)

		doc.set.assert_any_call("taxjar_customer_sync_status", "Synced")

	def test_restores_sync_error_from_a_stale_value(self):
		"""Same bug, the sibling field: a cleared/updated Sync Error must not
		be resurrected by a form that still holds the old message."""
		doc = self._make_doc(sync_error="Old connection timeout")
		db_values = frappe._dict(
			taxjar_customer_id="CUST-001", taxjar_customer_sync_status="Synced",
			taxjar_customer_sync_error="", taxjar_last_synced="2026-06-20 10:00:00",
		)

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value(db_values)):
			on_customer_validate(doc, None)

		doc.set.assert_any_call("taxjar_customer_sync_error", "")

	def test_does_not_overwrite_when_form_already_matches_db(self):
		"""Nothing to restore when the form's copy already agrees with the DB."""
		doc = self._make_doc(customer_id="CUST-001", sync_status="Synced")
		db_values = frappe._dict(
			taxjar_customer_id="CUST-001", taxjar_customer_sync_status="Synced",
			taxjar_customer_sync_error="", taxjar_last_synced="",
		)

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value(db_values)):
			on_customer_validate(doc, None)

		doc.set.assert_not_called()

	def test_skips_for_new_customer(self):
		"""New customers have no DB values to preserve."""
		doc = MagicMock()
		doc.is_new.return_value = True

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value") as mock_db:
			on_customer_validate(doc, None)

		mock_db.assert_not_called()

	def test_skips_when_db_has_no_values(self):
		"""If DB fields are also empty, nothing to restore."""
		doc = self._make_doc(customer_id="")
		db_values = frappe._dict(
			taxjar_customer_id="", taxjar_customer_sync_status="",
			taxjar_customer_sync_error="", taxjar_last_synced="",
		)

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value(db_values)):
			on_customer_validate(doc, None)

		doc.set.assert_not_called()

	def test_hooks_registers_validate(self):
		from taxjar_integration import hooks
		customer_events = hooks.doc_events.get("Customer", {})
		self.assertIn("validate", customer_events)
		self.assertIn("on_customer_validate", customer_events["validate"])


# ── _validate_exempt_regions — exemption is explicit, regions are mandatory ─


class TestValidateExemptRegions(UnitTestCase):

	def _make_doc(self, exemption_type, regions=None):
		doc = MagicMock()
		rows = [MagicMock(country=r["country"], state=r["state"], idx=i + 1)
		        for i, r in enumerate(regions or [])]
		doc.get.side_effect = lambda f, d=None: {
			"taxjar_exemption_type": exemption_type,
			"taxjar_exempt_regions": rows,
		}.get(f, d)
		return doc

	def test_throws_when_region_scoped_type_has_no_regions(self):
		for exemption_type in ("Wholesale", "Government", "Other"):
			doc = self._make_doc(exemption_type, regions=[])
			with self.assertRaises(frappe.ValidationError, msg=exemption_type):
				_validate_exempt_regions(doc)

	def test_passes_when_region_scoped_type_has_at_least_one_region(self):
		doc = self._make_doc("Wholesale", regions=[{"country": "US", "state": "TX"}])
		_validate_exempt_regions(doc)  # must not raise

	def test_blank_type_does_not_require_regions(self):
		doc = self._make_doc("", regions=[])
		_validate_exempt_regions(doc)  # must not raise

	def test_non_exempt_does_not_require_regions(self):
		"""Non Exempt means explicitly taxable everywhere - it is not a
		region-scoped exemption, so it carries no region requirement."""
		doc = self._make_doc("Non Exempt", regions=[])
		_validate_exempt_regions(doc)  # must not raise

	def test_still_validates_region_state_pairs_when_present(self):
		"""The mandatory-region rule is additive - the pre-existing per-row
		country/state check still runs regardless of it."""
		doc = self._make_doc("Wholesale", regions=[{"country": "US", "state": "ON"}])
		with self.assertRaises(frappe.ValidationError):
			_validate_exempt_regions(doc)


# ── TaxJar Customer Config Page — Python API ──────────────────────────────


from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import (
	get_customers,
	get_exempt_regions,
	configure_exemption,
	bulk_clear_exemption,
	bulk_sync_to_taxjar,
)


class TestCustomerConfigPageAPI(UnitTestCase):

	def test_get_customers_requires_read_permission(self):
		"""An unprivileged user must not be able to read customer data."""
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				get_customers()
		finally:
			frappe.set_user("Administrator")

	def test_get_customers_returns_structure(self):
		result = get_customers()
		self.assertIn("customers", result)
		self.assertIn("total", result)
		self.assertIn("page", result)
		self.assertIn("page_size", result)
		self.assertIn("total_pages", result)
		self.assertEqual(result["page"], 1)
		self.assertEqual(result["page_size"], 20)

	def test_get_customers_returns_expected_fields(self):
		result = get_customers()
		if result["customers"]:
			c = result["customers"][0]
			for key in ("name", "customer_name", "customer_group", "taxjar_exemption_type",
			            "taxjar_customer_id", "taxjar_customer_sync_status",
			            "taxjar_customer_sync_error", "exempt_region_count"):
				self.assertIn(key, c)

	def test_get_customers_filter_by_name(self):
		"""Column search terms are nested under "search" (see _add_column_search) -
		the same shape get_scope_filters() sends from the real client. A flat
		{"customer_name": ...} is not a supported filter and must not silently
		match everything."""
		result = get_customers(filters='{"search": {"customer_name": "NONEXISTENT_XYZ"}}')
		self.assertEqual(result["total"], 0)
		self.assertEqual(len(result["customers"]), 0)

	def test_get_customers_scope_not_configured(self):
		"""Whether an exemption is set is the tab, not a filter - there is only
		one way to express it."""
		from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import (
			NOT_CONFIGURED_SCOPE,
		)
		result = get_customers(scope=NOT_CONFIGURED_SCOPE)
		for c in result["customers"]:
			self.assertIn(c["taxjar_exemption_type"], ("", None))

	def test_get_customers_scope_exempt(self):
		from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import (
			EXEMPT_SCOPE,
		)
		result = get_customers(scope=EXEMPT_SCOPE)
		for c in result["customers"]:
			self.assertTrue(c["taxjar_exemption_type"])

	def test_get_customers_scope_all_is_the_default(self):
		from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import (
			ALL_SCOPE,
			_build_conditions,
		)
		self.assertNotIn("taxjar_exemption_type", _build_conditions({}, ALL_SCOPE))
		self.assertNotIn("taxjar_exemption_type", _build_conditions({}))

	def test_get_customers_filter_by_sync_not_set(self):
		result = get_customers(filters='{"sync_status": "__not_set"}')
		for c in result["customers"]:
			self.assertIn(c["taxjar_customer_sync_status"], ("", None))

	def test_get_customers_pagination(self):
		result = get_customers(page=1)
		self.assertEqual(result["page"], 1)
		self.assertGreaterEqual(result["total_pages"], 1)

	def test_get_customers_page_out_of_range(self):
		result = get_customers(page=9999)
		self.assertEqual(len(result["customers"]), 0)

	def test_configure_exemption_writes_type_and_regions_together(self):
		"""Type and regions are one decision, so they are one write. Splitting
		them is what previously let a customer keep exempt regions after its
		exemption type was cleared."""
		customers = get_customers()["customers"]
		if not customers:
			return

		name = customers[0]["name"]
		original = customers[0]["taxjar_exemption_type"]
		# Captured, not just the type: restoring a region-scoped type without
		# its regions is not a saveable state, so a run where the customer's
		# real original type requires regions would fail here rather than
		# leaving it stuck on this test's own "Government"/TX,ON. Same
		# capture-and-guard as test_clearing_the_type_clears_its_regions.
		original_regions = get_exempt_regions(name)
		mod = "taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers"

		with patch(f"{mod}.frappe.enqueue"):
			configure_exemption(
				[name], "Government", [{"country": "US", "state": "TX"}, {"country": "CA", "state": "ON"}]
			)

		self.assertEqual(frappe.db.get_value("Customer", name, "taxjar_exemption_type"), "Government")
		self.assertEqual({r["state"] for r in get_exempt_regions(name)}, {"TX", "ON"})

		with patch(f"{mod}.frappe.enqueue"):
			regions = [{"country": r["country"], "state": r["state"]} for r in original_regions]
			if original not in _EXEMPTION_TYPES_REQUIRING_REGIONS or regions:
				configure_exemption([name], original or "", regions)

	def test_clearing_the_type_clears_its_regions(self):
		"""An exempt region without an exemption type means nothing, so it is
		dropped rather than orphaned where no screen would ever show it."""
		customers = get_customers()["customers"]
		if not customers:
			return

		name = customers[0]["name"]
		original = customers[0]["taxjar_exemption_type"]
		# Captured, not just the type: restoring a region-scoped type without
		# its regions is not a saveable state, so a run where an earlier test
		# left this customer region-scoped would fail here rather than in
		# whatever actually broke. Same capture-and-guard as
		# test_bulk_clear_exemption and test_configure_exemption_applies_to_many.
		original_regions = get_exempt_regions(name)
		mod = "taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers"

		with patch(f"{mod}.frappe.enqueue"):
			configure_exemption([name], "Wholesale", [{"country": "US", "state": "TX"}])
			self.assertEqual(len(get_exempt_regions(name)), 1)
			# Regions passed alongside an empty type are discarded, not stored.
			configure_exemption([name], "", [{"country": "US", "state": "CA"}])

		self.assertEqual(frappe.db.get_value("Customer", name, "taxjar_exemption_type"), "")
		self.assertEqual(get_exempt_regions(name), [])

		with patch(f"{mod}.frappe.enqueue"):
			regions = [{"country": r["country"], "state": r["state"]} for r in original_regions]
			if original not in _EXEMPTION_TYPES_REQUIRING_REGIONS or regions:
				configure_exemption([name], original or "", regions)

	def test_configure_exemption_applies_to_many(self):
		"""Other is a region-scoped type - at least one region is now mandatory
		to save it (see _validate_exempt_regions)."""
		customers = get_customers()["customers"]
		if len(customers) < 1:
			return

		names = [c["name"] for c in customers[:2]]
		originals = {c["name"]: c["taxjar_exemption_type"] for c in customers[:2]}
		original_regions = {name: get_exempt_regions(name) for name in names}
		mod = "taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers"

		with patch(f"{mod}.frappe.enqueue"):
			result = configure_exemption(names, "Other", [{"country": "US", "state": "TX"}])

		self.assertEqual(result["updated"], len(names))
		for name in names:
			self.assertEqual(frappe.db.get_value("Customer", name, "taxjar_exemption_type"), "Other")

		with patch(f"{mod}.frappe.enqueue"):
			for name, orig in originals.items():
				regions = [{"country": r["country"], "state": r["state"]} for r in original_regions[name]]
				# A pre-existing customer already sitting in a state the new
				# mandatory-region rule forbids (a region-scoped type with no
				# regions on file) cannot be restored to that exact state -
				# leaving it cleared is the closest still-valid outcome.
				if orig in _EXEMPTION_TYPES_REQUIRING_REGIONS and not regions:
					continue
				configure_exemption([name], orig or "", regions)

	def test_bulk_clear_exemption(self):
		"""Wholesale is region-scoped - at least one region is now mandatory to
		save it (see _validate_exempt_regions)."""
		customers = get_customers()["customers"]
		if len(customers) < 1:
			return

		name = customers[0]["name"]
		original = frappe.db.get_value("Customer", name, "taxjar_exemption_type")
		original_regions = get_exempt_regions(name)

		with patch("taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers.frappe.enqueue"):
			configure_exemption([name], "Wholesale", [{"country": "US", "state": "TX"}])
			result = bulk_clear_exemption([name])

		self.assertEqual(result["updated"], 1)
		val = frappe.db.get_value("Customer", name, "taxjar_exemption_type")
		self.assertIn(val, ("", None))

		with patch("taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers.frappe.enqueue"):
			regions = [{"country": r["country"], "state": r["state"]} for r in original_regions]
			# See test_configure_exemption_applies_to_many's identical guard.
			if original not in _EXEMPTION_TYPES_REQUIRING_REGIONS or regions:
				configure_exemption([name], original or "", regions)

	def test_bulk_sync_to_taxjar(self):
		customers = get_customers()["customers"]
		if not customers:
			return

		with patch("taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers.frappe.enqueue") as mock_enqueue:
			result = bulk_sync_to_taxjar([c["name"] for c in customers])

		self.assertIn("queued", result)

	def test_page_json_exists(self):
		import os
		page_json = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..",
			"page", "taxjar_customers", "taxjar_customers.json",
		))
		self.assertTrue(os.path.isfile(page_json))

	def test_page_js_exists(self):
		import os
		page_js = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..",
			"page", "taxjar_customers", "taxjar_customers.js",
		))
		self.assertTrue(os.path.isfile(page_js))

	def test_page_js_has_regions_dialog(self):
		import os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..",
			"page", "taxjar_customers", "taxjar_customers.js",
		))
		with open(path) as f:
			js = f.read()
		self.assertIn("show_configure_dialog", js)
		self.assertIn("build_region_multicheck_fields", js)
		# One dialog covers both halves of the decision.
		self.assertIn("exemption_type", js)
		self.assertIn("configure_exemption", js)

	def test_workspace_has_page_link(self):
		import json, os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..",
			"workspace", "taxjar_integration", "taxjar_integration.json",
		))
		with open(path) as f:
			ws = json.load(f)
		page_links = [l for l in ws["links"] if l.get("link_to") == "taxjar-customers"]
		self.assertTrue(len(page_links) > 0)


# ── Problem 1: pages tolerate missing TaxJar custom fields ───────────────────


class TestNotConfiguredGuards(UnitTestCase):
	"""When the TaxJar custom fields were never created, the desk pages must return
	a not_configured envelope instead of querying non-existent columns (1054)."""

	CUSTOMERS = "taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers"
	TRANSACTIONS = "taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions"

	def test_not_configured_response_shape(self):
		from taxjar_integration.taxjar_integration.pagination import not_configured_response

		bare = not_configured_response()
		self.assertEqual(bare, {"not_configured": True})

		paged = not_configured_response("customers")
		self.assertTrue(paged["not_configured"])
		self.assertEqual(paged["customers"], [])
		self.assertEqual(paged["total"], 0)
		self.assertEqual(paged["page"], 1)
		self.assertIn("total_pages", paged)

	def test_get_customers_not_configured(self):
		from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import (
			get_customers,
		)
		with patch(f"{self.CUSTOMERS}.frappe.db.has_column", return_value=False):
			result = get_customers()
		self.assertTrue(result["not_configured"])
		self.assertEqual(result["customers"], [])

	def test_get_transactions_not_configured(self):
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import (
			get_transactions,
		)
		with patch(f"{self.TRANSACTIONS}.frappe.db.has_column", return_value=False):
			result = get_transactions()
		self.assertTrue(result["not_configured"])
		self.assertEqual(result["invoices"], [])

	def test_get_summary_not_configured(self):
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import (
			get_summary,
		)
		with patch(f"{self.TRANSACTIONS}.frappe.db.has_column", return_value=False):
			result = get_summary()
		self.assertEqual(result, {"not_configured": True})

	def test_customer_mutator_throws_when_not_configured(self):
		from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import (
			configure_exemption,
		)
		with patch(f"{self.CUSTOMERS}.frappe.db.has_column", return_value=False):
			with self.assertRaises(frappe.ValidationError):
				configure_exemption(["Any Customer"], "Government")

	def test_transaction_mutator_throws_when_not_configured(self):
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import (
			bulk_retry,
		)
		with patch(f"{self.TRANSACTIONS}.frappe.db.has_column", return_value=False):
			with self.assertRaises(frappe.ValidationError):
				bulk_retry(["SINV-0001"])

	def test_page_js_handles_not_configured(self):
		import os
		base = os.path.join(
			os.path.dirname(__file__), "..", "..", "page",
		)
		for page in ("taxjar_customers", "taxjar_transactions"):
			path = os.path.normpath(os.path.join(base, page, f"{page}.js"))
			with open(path) as f:
				js = f.read()
			self.assertIn("not_configured", js)
			self.assertIn("show_not_configured", js)

	def test_taxjar_utils_has_not_configured_panel(self):
		import os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "..", "public", "js", "taxjar_utils.js",
		))
		with open(path) as f:
			js = f.read()
		self.assertIn("render_not_configured_panel", js)


# ── Problem 1 / 2: install-time setup ────────────────────────────────────────


class TestInstallSetup(UnitTestCase):

	def test_after_install_hook_registered(self):
		from taxjar_integration import hooks
		self.assertEqual(hooks.after_install, "taxjar_integration.install.after_install")

	def test_after_migrate_hook_registered(self):
		from taxjar_integration import hooks
		self.assertIn("taxjar_integration.install.after_migrate", hooks.after_migrate)

	def _run_setup(self, *, categories_exist):
		from taxjar_integration import install

		# frappe.db.exists is patched on the real frappe.db object (not a local
		# copy), so a blanket return_value would also answer every other
		# frappe.db.exists() call sync_taxjar_workspace_sidebar() makes further
		# down setup_taxjar() (e.g. checking the Workspace Sidebar leftover) -
		# defeating delete_doc's ignore_missing safety net with a lie and turning
		# it into a real DoesNotExistError. Only fake the one check this is
		# actually testing; let everything else hit the real frappe.db.exists.
		real_exists = frappe.db.exists

		def fake_exists(dt, *args, **kwargs):
			if dt == "Product Tax Category" and not args and not kwargs:
				return categories_exist
			return real_exists(dt, *args, **kwargs)

		with patch("taxjar_integration.install.make_custom_fields") as mock_make, \
		     patch("taxjar_integration.install.add_product_tax_categories") as mock_cats, \
		     patch("taxjar_integration.install.add_permissions") as mock_perms, \
		     patch("taxjar_integration.install.sync_all_company_tax_templates") as mock_sync, \
		     patch("taxjar_integration.install.hide_legacy_exempt_from_sales_tax") as mock_hide, \
		     patch("taxjar_integration.install.set_taxes_field_description") as mock_desc, \
		     patch("taxjar_integration.install.add_guided_setup_alert") as mock_alert, \
		     patch("taxjar_integration.install.frappe.db.exists", side_effect=fake_exists):
			install.setup_taxjar()
		return mock_make, mock_cats, mock_perms, mock_sync, mock_hide, mock_desc, mock_alert

	def test_after_install_runs_full_setup(self):
		from taxjar_integration import install
		with patch("taxjar_integration.install.setup_taxjar") as mock_setup:
			install.after_install()
		mock_setup.assert_called_once()

		mock_make, mock_cats, mock_perms, mock_sync, mock_hide, mock_desc, mock_alert = self._run_setup(categories_exist=False)
		mock_make.assert_called_once()
		mock_cats.assert_called_once()
		mock_perms.assert_called_once()
		mock_sync.assert_called_once()
		mock_hide.assert_called_once()
		mock_desc.assert_called_once()
		mock_alert.assert_called_once()

	def test_setup_skips_category_seed_when_already_present(self):
		mock_make, mock_cats, mock_perms, mock_sync, mock_hide, mock_desc, mock_alert = self._run_setup(categories_exist=True)
		mock_cats.assert_not_called()
		mock_make.assert_called_once()
		mock_perms.assert_called_once()
		mock_sync.assert_called_once()
		mock_hide.assert_called_once()
		mock_desc.assert_called_once()
		mock_alert.assert_called_once()


# ── Workspace guided-setup alert banner ───────────────────────────────────────


class TestGuidedSetupAlert(UnitTestCase):
	"""Tests for install.add_guided_setup_alert(): the blue/outline banner at the
	top of the workspace nudging first-time users toward the guided setup wizard."""

	def setUp(self):
		from taxjar_integration.install import GUIDED_SETUP_ALERT_BLOCK, add_guided_setup_alert
		self.block_name = GUIDED_SETUP_ALERT_BLOCK
		frappe.db.delete("Custom HTML Block", {"name": self.block_name})
		self._reset_workspace_content()
		# This runs against the real site DB, not a rolled-back sandbox - a
		# cleanup that only deletes (as this used to) leaves a live site's
		# desk workspace permanently missing its guided-setup banner block
		# (a real incident: the workspace page rendered "undefined" where
		# the banner should have been, and every other test that calls the
		# real sync_taxjar_workspace_sidebar()/setup_taxjar() afterward
		# failed with a LinkValidationError against the now-missing block).
		# add_guided_setup_alert() is idempotent (see
		# test_idempotent_on_repeated_calls below), so calling it once more
		# here unconditionally restores the same valid state a real
		# `bench migrate` would leave, regardless of what an individual
		# test method did to it.
		self.addCleanup(add_guided_setup_alert)

	def _reset_workspace_content(self):
		"""Strip any guided-setup-alert content block and custom_blocks child row
		this test added, leaving the rest of the workspace (Setup/Manage/Sync cards)
		exactly as it was."""
		if not frappe.db.exists("Workspace", "TaxJar Integration"):
			return
		ws = frappe.get_doc("Workspace", "TaxJar Integration")
		content = frappe.parse_json(ws.content or "[]")
		filtered_content = [
			block for block in content
			if block.get("id") not in ("taxjar_guided_setup_alert", "taxjar_guided_setup_alert_spacer")
		]
		filtered_rows = [
			row for row in (ws.custom_blocks or []) if row.custom_block_name != self.block_name
		]
		if filtered_content != content or len(filtered_rows) != len(ws.custom_blocks or []):
			ws.content = frappe.as_json(filtered_content)
			ws.set("custom_blocks", filtered_rows)
			ws.save(ignore_permissions=True)

	def test_creates_custom_html_block_with_expected_content(self):
		from taxjar_integration.install import add_guided_setup_alert
		add_guided_setup_alert()

		block = frappe.get_doc("Custom HTML Block", self.block_name)
		self.assertIn("taxjar-setup", block.html)
		self.assertIn("blue", block.html)
		# Always shown - no setup_complete gate to hide it once the wizard is
		# run, unlike the Settings form's own intro.
		self.assertFalse(block.script)

	def test_registers_custom_blocks_child_row(self):
		"""The `custom_blocks` child table on Workspace is what the block editor
		actually looks up (by label) to resolve a "custom_block" content entry into
		a live widget - without a matching row here the content block has nothing
		to render, regardless of it being present in `content`."""
		from taxjar_integration.install import add_guided_setup_alert
		add_guided_setup_alert()

		ws = frappe.get_doc("Workspace", "TaxJar Integration")
		matches = [row for row in ws.custom_blocks if row.custom_block_name == self.block_name]
		self.assertEqual(len(matches), 1)
		self.assertEqual(matches[0].label, self.block_name)

	def test_inserts_content_block_at_full_width(self):
		"""Setup/Manage/Sync now sit in one row (4 + 4 + 4), so the banner spans
		the full row width above them rather than being paired with a spacer."""
		from taxjar_integration.install import add_guided_setup_alert
		add_guided_setup_alert()

		ws = frappe.get_doc("Workspace", "TaxJar Integration")
		content = frappe.parse_json(ws.content or "[]")
		alert_blocks = [b for b in content if b.get("data", {}).get("custom_block_name") == self.block_name]

		self.assertEqual(len(alert_blocks), 1)
		self.assertEqual(alert_blocks[0]["data"]["col"], 12)
		self.assertNotIn(
			"taxjar_guided_setup_alert_spacer", [b.get("id") for b in content]
		)

	def test_heals_stale_width_and_spacer_from_a_previous_version(self):
		"""A layout change here (col: 4 + spacer -> col: 12) must also reach sites
		that already ran an earlier version of this function, not just fresh
		installs - same self-healing principle as the html/script sync above."""
		from taxjar_integration.install import add_guided_setup_alert

		ws = frappe.get_doc("Workspace", "TaxJar Integration")
		content = frappe.parse_json(ws.content or "[]")
		stale_content = [
			{
				"id": "taxjar_guided_setup_alert",
				"type": "custom_block",
				"data": {"custom_block_name": self.block_name, "col": 4},
			},
			{"id": "taxjar_guided_setup_alert_spacer", "type": "spacer", "data": {"col": 8}},
			*content,
		]
		ws.content = frappe.as_json(stale_content)
		ws.save(ignore_permissions=True)

		add_guided_setup_alert()

		ws = frappe.get_doc("Workspace", "TaxJar Integration")
		content = frappe.parse_json(ws.content or "[]")
		alert_blocks = [b for b in content if b.get("data", {}).get("custom_block_name") == self.block_name]

		self.assertEqual(len(alert_blocks), 1)
		self.assertEqual(alert_blocks[0]["data"]["col"], 12)
		self.assertNotIn(
			"taxjar_guided_setup_alert_spacer", [b.get("id") for b in content]
		)

	def test_idempotent_on_repeated_calls(self):
		"""Running setup/migrate repeatedly must not duplicate the block, the
		custom_blocks child row, or the Custom HTML Block record."""
		from taxjar_integration.install import add_guided_setup_alert
		add_guided_setup_alert()
		add_guided_setup_alert()
		add_guided_setup_alert()

		self.assertEqual(frappe.db.count("Custom HTML Block", {"name": self.block_name}), 1)

		ws = frappe.get_doc("Workspace", "TaxJar Integration")
		content = frappe.parse_json(ws.content or "[]")
		alert_blocks = [b for b in content if b.get("data", {}).get("custom_block_name") == self.block_name]
		self.assertEqual(len(alert_blocks), 1)

		matches = [row for row in ws.custom_blocks if row.custom_block_name == self.block_name]
		self.assertEqual(len(matches), 1)

	def test_syncs_html_on_already_migrated_sites(self):
		"""A style/copy edit to the constants in install.py must reach sites that
		already ran setup once before, not just fresh installs - the app is the
		source of truth, same convention as create_custom_fields(update=True).
		Also covers a site left over from before the hide-on-setup_complete
		script was removed: its stale script must be cleared, not merely left
		alone because the html already matches."""
		from taxjar_integration import install

		install.add_guided_setup_alert()
		stale = frappe.get_doc("Custom HTML Block", self.block_name)
		stale.html = "<div>stale content from a previous version</div>"
		stale.script = "root_element.style.display = \"none\";"
		stale.save(ignore_permissions=True)

		install.add_guided_setup_alert()

		refreshed = frappe.get_doc("Custom HTML Block", self.block_name)
		self.assertEqual(refreshed.html, install.GUIDED_SETUP_ALERT_HTML)
		self.assertFalse(refreshed.script)


# ── Nexus & Product Category tab: count/last-updated summary ─────────────────


class TestProductTaxCategorySummary(UnitTestCase):
	"""Tests for TaxJarSettings.get_product_tax_category_summary(), rendered on the
	renamed 'Nexus & Product Category' tab."""

	def setUp(self):
		self.settings = frappe.get_single("TaxJar Settings")

	def test_count_matches_table_and_last_updated_matches_max_modified(self):
		row = frappe.get_doc({
			"doctype": "Product Tax Category",
			"product_tax_code": "TEST_SUMMARY_ROW",
			"category_name": "Summary Test Category",
			"description": "For summary test",
		}).insert(ignore_permissions=True)
		self.addCleanup(frappe.db.delete, "Product Tax Category", {"product_tax_code": "TEST_SUMMARY_ROW"})

		summary = self.settings.get_product_tax_category_summary()

		self.assertEqual(summary["count"], frappe.db.count("Product Tax Category"))
		self.assertEqual(
			summary["last_updated"],
			frappe.db.get_value(
				"Product Tax Category", filters={}, fieldname="modified", order_by="modified desc"
			),
		)

	def test_zero_rows_returns_none_last_updated_without_raising(self):
		real_count = frappe.db.count
		real_get_value = frappe.db.get_value

		def fake_count(doctype, *args, **kwargs):
			if doctype == "Product Tax Category":
				return 0
			return real_count(doctype, *args, **kwargs)

		def fake_get_value(doctype, *args, **kwargs):
			if doctype == "Product Tax Category":
				return None
			return real_get_value(doctype, *args, **kwargs)

		with patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.frappe.db.count", side_effect=fake_count), \
		     patch("taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.frappe.db.get_value", side_effect=fake_get_value):
			summary = self.settings.get_product_tax_category_summary()  # must not raise

		self.assertEqual(summary["count"], 0)
		self.assertIsNone(summary["last_updated"])

	def test_js_formats_last_updated_via_user_timezone_not_comment_when(self):
		"""comment_when()/prettyDate() blanks the display whenever it computes a
		negative day-diff (pretty_date.js: `if (day_diff < 0) return ""`) - which
		happens for any real timestamp once System Settings' timezone drifts far
		enough from the browser's own. str_to_user() converts system tz -> user tz
		via moment-timezone and just formats it, with no comparison against the
		browser's local clock at all, so it can't hit that guard."""
		import os
		path = os.path.join(os.path.dirname(__file__), "taxjar_settings.js")
		with open(path) as f:
			js = f.read()

		# The call now lives in the shared _format_last_synced() helper (Nexus
		# and Product Tax Category ask the same question), so assert the route
		# rather than one inlined call site.
		formatter = js.split("function _format_last_synced(value) {")[1].split("}")[0]
		self.assertIn("frappe.datetime.str_to_user(value)", formatter)
		self.assertIn("_format_last_synced(summary.last_updated)", js)
		# Only as the comment explaining why it is not used - never as a call.
		self.assertNotIn("frappe.datetime.comment_when(", js)


class TestRefreshProductTaxCategories(UnitTestCase):
	"""Tests for TaxJarSettings.refresh_product_tax_categories(), the manual
	"Update Product Tax Category List" button - unlike the weekly scheduled job this
	is user-triggered, so a missing credential must raise, not silently no-op."""

	def setUp(self):
		self.settings = frappe.get_single("TaxJar Settings")

	def _category(self, product_tax_code, description, name):
		category = MagicMock()
		category.product_tax_code = product_tax_code
		category.description = description
		category.name = name
		return category

	def test_throws_clear_error_when_no_client(self):
		with patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.get_client",
			return_value=None,
		):
			with self.assertRaises(frappe.exceptions.ValidationError) as cm:
				self.settings.refresh_product_tax_categories()
		self.assertIn("API credentials", str(cm.exception))

	def test_inserts_new_categories_and_returns_summary(self):
		frappe.db.delete("Product Tax Category", {"product_tax_code": "TEST_REFRESH_NEW"})
		self.addCleanup(frappe.db.delete, "Product Tax Category", {"product_tax_code": "TEST_REFRESH_NEW"})

		mock_client = MagicMock()
		mock_client.categories.return_value = [
			self._category("TEST_REFRESH_NEW", "A refresh-button test category", "Refresh Test Category"),
		]
		with patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.get_client",
			return_value=mock_client,
		):
			summary = self.settings.refresh_product_tax_categories()

		inserted = frappe.get_doc("Product Tax Category", "TEST_REFRESH_NEW")
		self.assertEqual(inserted.category_name, "Refresh Test Category")
		self.assertEqual(summary["count"], frappe.db.count("Product Tax Category"))

	def test_does_not_depend_on_taxjar_enabled(self):
		"""Categories aren't company-scoped, so a valid client is enough - this must
		not gate on _is_taxjar_enabled() the way the weekly scheduled job does."""
		mock_client = MagicMock()
		mock_client.categories.return_value = []
		with patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.get_client",
			return_value=mock_client,
		), patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings._is_taxjar_enabled",
			return_value=False,
		):
			self.settings.refresh_product_tax_categories()  # must not raise or no-op
		mock_client.categories.assert_called_once()

	def test_connection_error_raises_clear_message(self):
		"""Regression guard: this call used to have no try/except at all, so a
		connection blip surfaced as an unhandled exception instead of a clean
		message like every other TaxJar call site in this app."""
		import taxjar.exceptions
		mock_client = MagicMock()
		mock_client.categories.side_effect = taxjar.exceptions.TaxJarConnectionError("timeout")
		with patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.get_client",
			return_value=mock_client,
		):
			with self.assertRaises(frappe.exceptions.ValidationError) as cm:
				self.settings.refresh_product_tax_categories()
		self.assertIn("unreachable", str(cm.exception))

	def test_401_response_error_raises_invalid_token_message(self):
		import taxjar.exceptions
		err = taxjar.exceptions.TaxJarResponseError(MagicMock())
		err.full_response = {"status_code": 401}
		mock_client = MagicMock()
		mock_client.categories.side_effect = err
		with patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.get_client",
			return_value=mock_client,
		):
			with self.assertRaises(frappe.exceptions.ValidationError) as cm:
				self.settings.refresh_product_tax_categories()
		self.assertIn("Invalid TaxJar API token", str(cm.exception))

	def test_other_response_error_raises_sanitized_message(self):
		import taxjar.exceptions
		err = taxjar.exceptions.TaxJarResponseError(MagicMock())
		err.full_response = {"status_code": 400, "detail": "to_state is invalid"}
		mock_client = MagicMock()
		mock_client.categories.side_effect = err
		with patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.get_client",
			return_value=mock_client,
		):
			with self.assertRaises(frappe.exceptions.ValidationError) as cm:
				self.settings.refresh_product_tax_categories()
		self.assertIn("State", str(cm.exception))  # sanitize_error_response renames "to state" -> "State"


class TestFetchAndInsertCategoriesLogging(UnitTestCase):
	"""fetch_and_insert_categories() is shared by the manual button and the
	weekly cron - it logs via log_taxjar_call() same as every other TaxJar call
	site, then re-raises so each caller keeps its own presentation behaviour."""

	MOD = "taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings"

	def test_logs_request_and_success(self):
		from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
			fetch_and_insert_categories,
		)
		mock_client = MagicMock()
		mock_client.categories.return_value = []
		with patch(f"{self.MOD}.log_taxjar_call") as mock_log:
			fetch_and_insert_categories(mock_client)

		actions = [c.kwargs.get("action") or c.args[0] for c in mock_log.call_args_list]
		statuses = [c.kwargs.get("status") for c in mock_log.call_args_list]
		self.assertIn("categories", actions)
		self.assertIn("request", statuses)
		self.assertIn("success", statuses)

	def test_logs_error_and_reraises(self):
		import taxjar.exceptions
		from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
			fetch_and_insert_categories,
		)
		mock_client = MagicMock()
		mock_client.categories.side_effect = taxjar.exceptions.TaxJarConnectionError("timeout")

		with patch(f"{self.MOD}.log_taxjar_call") as mock_log:
			with self.assertRaises(taxjar.exceptions.TaxJarConnectionError):
				fetch_and_insert_categories(mock_client)

		error_calls = [c for c in mock_log.call_args_list if c.kwargs.get("status") == "error"]
		self.assertEqual(len(error_calls), 1)


class TestTaxJarSettingsJsonNexusTab(UnitTestCase):
	"""JSON-level assertions on the doctype fixture itself - matches the pattern used
	by TestWorkspaceBranding below for the workspace fixture."""

	def _doctype_json(self):
		import json, os
		path = os.path.join(os.path.dirname(__file__), "taxjar_settings.json")
		with open(path) as f:
			return json.load(f)

	def _field(self, doctype_json, fieldname):
		for field in doctype_json["fields"]:
			if field["fieldname"] == fieldname:
				return field
		self.fail(f"Field {fieldname!r} not found in TaxJar Settings JSON")

	def test_nexus_tab_renamed(self):
		doctype_json = self._doctype_json()
		tab = self._field(doctype_json, "nexus_tab")
		self.assertEqual(tab["label"], "Nexus & Product Category")

	def test_state_nexus_section_labelled(self):
		"""The Update Nexus List button + table previously sat directly under
		the Nexus & Product Category tab with no section heading of their
		own - unlike the Product Tax Category block right below it, which
		does have one. section_state_nexus gives this block the same
		treatment."""
		doctype_json = self._doctype_json()
		section = self._field(doctype_json, "section_state_nexus")
		self.assertEqual(section["fieldtype"], "Section Break")
		self.assertEqual(section["label"], "State Nexus")

		order = doctype_json["field_order"]
		self.assertLess(order.index("nexus_tab"), order.index("section_state_nexus"))
		self.assertLess(order.index("section_state_nexus"), order.index("update_nexus_list_btn"))

	def test_nexus_last_synced_is_hidden(self):
		"""The date is still shown - see
		test_last_synced_renders_beside_the_button_not_the_hidden_field - just
		not via this field's own row. read_only stays set: update_nexus_list
		still writes it, it is just no longer this field's job to display it.
		"""
		doctype_json = self._doctype_json()
		field = self._field(doctype_json, "nexus_last_synced")
		self.assertEqual(field.get("hidden"), 1)
		self.assertEqual(field.get("read_only"), 1)

	def test_product_tax_category_summary_fields_present(self):
		doctype_json = self._doctype_json()
		section = self._field(doctype_json, "product_tax_category_section")
		self.assertEqual(section["fieldtype"], "Section Break")

		html_field = self._field(doctype_json, "product_tax_category_html")
		self.assertEqual(html_field["fieldtype"], "HTML")

		self.assertIn("product_tax_category_section", doctype_json["field_order"])
		self.assertIn("product_tax_category_html", doctype_json["field_order"])

	def test_update_product_tax_category_button_present(self):
		doctype_json = self._doctype_json()
		btn = self._field(doctype_json, "update_product_tax_category_btn")
		self.assertEqual(btn["fieldtype"], "Button")
		self.assertEqual(btn["label"], "Update Product Tax Category List")
		self.assertIn("update_product_tax_category_btn", doctype_json["field_order"])

	def test_fresh_install_defaults(self):
		"""A never-configured TaxJar Settings singleton (fresh install, before the
		guided setup wizard has saved anything) should present Live / logging on /
		15-day retention - not the previous Sandbox / logging off / 5-day
		combination."""
		doctype_json = self._doctype_json()
		self.assertEqual(self._field(doctype_json, "api_mode")["default"], "Live")
		self.assertEqual(self._field(doctype_json, "enable_taxjar_logging")["default"], "1")
		self.assertEqual(self._field(doctype_json, "log_retention_days")["default"], "15")


# ── Problem 3: single branded workspace ──────────────────────────────────────


class TestWorkspaceBranding(UnitTestCase):

	def _workspace(self):
		import json, os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "workspace",
			"taxjar_integration", "taxjar_integration.json",
		))
		with open(path) as f:
			return json.load(f)

	def test_branded_title_and_label(self):
		ws = self._workspace()
		self.assertEqual(ws["title"], "TaxJar Integration")
		self.assertEqual(ws["label"], "TaxJar Integration")

	def test_name_drives_branded_route(self):
		"""The desk sidebar shows the workspace name and the route is its slug, so the
		name is branded and app_home points at the matching /app/taxjar-integration."""
		ws = self._workspace()
		self.assertEqual(ws["name"], "TaxJar Integration")
		self.assertEqual(frappe.get_hooks("app_home", app_name="taxjar_integration"), ["/app/taxjar-integration"])

	def test_old_workspace_removed_by_patch(self):
		import os
		patches = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "..", "patches.txt",
		))
		with open(patches) as f:
			self.assertIn("remove_old_taxjar_workspace", f.read())

	def test_taxjar_integration_casing_fix_patches_registered(self):
		"""The "Taxjar Integration" -> "TaxJar Integration" casing fix needs
		post_model_sync cleanup of the old-named Workspace/Workspace Sidebar/Module
		Def left behind once sync_all() creates the new-named records (Module Def
		can't be renamed in place - ModuleDef.before_rename blocks non-custom
		modules)."""
		import os
		patches = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "..", "patches.txt",
		))
		with open(patches) as f:
			content = f.read()
		self.assertIn("remove_old_taxjar_integration_workspace", content)
		self.assertIn("remove_old_taxjar_integration_module", content)

	def test_icon_is_valid_not_dollar_sign(self):
		ws = self._workspace()
		self.assertEqual(ws["icon"], "coins")

	def test_sidebar_mirrors_card_groups(self):
		"""The generated sidebar mirrors the workspace card groups: each card
		becomes a Section Break with its links as nested children, in the card
		display (content) order.

		The sidebar lives on ``Workspace.sidebar_items`` - a child table on the
		workspace itself - not the standalone ``Workspace Sidebar`` doctype, which
		was merged into ``Workspace`` earlier in v16 and is no longer read by
		frappe.boot.get_sidebar_items."""
		from taxjar_integration.install import sync_taxjar_workspace_sidebar

		sync_taxjar_workspace_sidebar()
		doc = frappe.get_doc("Workspace", "TaxJar Integration")

		structure = []
		current = None
		for item in doc.sidebar_items:
			if item.type == "Section Break":
				current = {"group": item.label, "children": []}
				structure.append(current)
			elif item.type == "Link" and current is not None:
				self.assertTrue(item.child)
				current["children"].append(item.link_to)

		self.assertEqual([g["group"] for g in structure], ["Setup", "Manage", "Sync"])
		groups = {g["group"]: g["children"] for g in structure}
		self.assertEqual(groups["Setup"], ["taxjar-setup", "TaxJar Settings", "TaxJar API Log"])
		self.assertEqual(groups["Manage"], ["taxjar-customers", "Product Tax Category"])
		self.assertEqual(groups["Sync"], ["taxjar-transactions"])

	def test_home_entry_uses_an_icon_that_exists_in_the_bundled_lucide_sprite(self):
		"""Regression guard: the desk sidebar resolves an icon name straight to
		#icon-<name> in frappe's bundled lucide sprite (frappe/public/icons/lucide/
		icons.svg) with no fallback - "home" was never in that sprite (only
		"house" is), so the Home entry silently rendered no icon at all."""
		from taxjar_integration.install import sync_taxjar_workspace_sidebar

		sync_taxjar_workspace_sidebar()
		doc = frappe.get_doc("Workspace", "TaxJar Integration")

		home_items = [item for item in doc.sidebar_items if item.label == "Home"]
		self.assertEqual(len(home_items), 1)
		self.assertEqual(home_items[0].icon, "house")

	def test_link_cards(self):
		ws = self._workspace()
		cards = {l["label"] for l in ws["links"] if l["type"] == "Card Break"}
		self.assertEqual(cards, {"Setup", "Manage", "Sync"})

	def test_link_targets(self):
		ws = self._workspace()
		targets = {l["link_to"] for l in ws["links"] if l["type"] == "Link"}
		self.assertEqual(
			targets,
			{"TaxJar Settings", "Product Tax Category", "taxjar-customers",
			 "taxjar-transactions", "TaxJar API Log", "taxjar-setup"},
		)

	def test_apps_screen_title_branded(self):
		from taxjar_integration import hooks
		self.assertEqual(hooks.add_to_apps_screen[0]["title"], "TaxJar Integration")


# ── Tax Breakdown: helpers ──────────────────────────────────────────────────

def _make_us_breakdown():
	"""Return a MagicMock mimicking TaxJar's US tax_for_order breakdown."""
	breakdown = MagicMock()
	breakdown.state_taxable_amount = 100.0
	breakdown.state_tax_rate = 0.0625
	breakdown.state_tax_collectable = 6.25
	breakdown.county_taxable_amount = 100.0
	breakdown.county_tax_rate = 0.01
	breakdown.county_tax_collectable = 1.0
	breakdown.city_taxable_amount = 100.0
	breakdown.city_tax_rate = 0.0
	breakdown.city_tax_collectable = 0.0
	breakdown.special_district_taxable_amount = 100.0
	breakdown.special_tax_rate = 0.025
	breakdown.special_district_tax_collectable = 2.5

	breakdown.country_taxable_amount = 0
	breakdown.country_tax_rate = 0
	breakdown.country_tax_collectable = 0
	breakdown.gst_taxable_amount = 0
	breakdown.gst_tax_rate = 0
	breakdown.gst = 0
	breakdown.pst_taxable_amount = 0
	breakdown.pst_tax_rate = 0
	breakdown.pst = 0
	breakdown.qst_taxable_amount = 0
	breakdown.qst_tax_rate = 0
	breakdown.qst = 0

	li = MagicMock()
	li.id = 1
	li.tax_collectable = 9.75
	li.taxable_amount = 100.0
	li.combined_tax_rate = 0.0975
	li.state_taxable_amount = 100.0
	li.state_sales_tax_rate = 0.0625
	li.state_amount = 6.25
	li.county_taxable_amount = 100.0
	li.county_tax_rate = 0.01
	li.county_amount = 1.0
	li.city_taxable_amount = 100.0
	li.city_tax_rate = 0.0
	li.city_amount = 0.0
	li.special_district_taxable_amount = 100.0
	li.special_tax_rate = 0.025
	li.special_district_amount = 2.5
	li.country_taxable_amount = 0
	li.country_tax_rate = 0
	li.country_tax_collectable = 0
	li.gst_taxable_amount = 0
	li.gst_tax_rate = 0
	li.gst = 0
	li.pst_taxable_amount = 0
	li.pst_tax_rate = 0
	li.pst = 0
	li.qst_taxable_amount = 0
	li.qst_tax_rate = 0
	li.qst = 0
	breakdown.line_items = [li]

	tax_data = MagicMock()
	tax_data.amount_to_collect = 9.75
	tax_data.rate = 0.0975
	tax_data.taxable_amount = 100.0
	tax_data.tax_source = "destination"
	tax_data.breakdown = breakdown

	jurisdictions = MagicMock()
	jurisdictions.state = "CA"
	jurisdictions.county = "LOS ANGELES"
	jurisdictions.city = "LOS ANGELES"
	tax_data.jurisdictions = jurisdictions

	return tax_data


def _make_ca_breakdown():
	"""Return a MagicMock mimicking TaxJar's Canadian GST/PST breakdown."""
	breakdown = MagicMock()
	breakdown.state_taxable_amount = 0
	breakdown.state_tax_rate = 0
	breakdown.state_tax_collectable = 0
	breakdown.county_taxable_amount = 0
	breakdown.county_tax_rate = 0
	breakdown.county_tax_collectable = 0
	breakdown.city_taxable_amount = 0
	breakdown.city_tax_rate = 0
	breakdown.city_tax_collectable = 0
	breakdown.special_district_taxable_amount = 0
	breakdown.special_tax_rate = 0
	breakdown.special_district_tax_collectable = 0
	breakdown.country_taxable_amount = 0
	breakdown.country_tax_rate = 0
	breakdown.country_tax_collectable = 0

	breakdown.gst_taxable_amount = 200.0
	breakdown.gst_tax_rate = 0.05
	breakdown.gst = 10.0
	breakdown.pst_taxable_amount = 200.0
	breakdown.pst_tax_rate = 0.07
	breakdown.pst = 14.0
	breakdown.qst_taxable_amount = 0
	breakdown.qst_tax_rate = 0
	breakdown.qst = 0

	li = MagicMock()
	li.id = 1
	li.tax_collectable = 24.0
	li.taxable_amount = 200.0
	li.combined_tax_rate = 0.12
	li.state_taxable_amount = 0
	li.state_sales_tax_rate = 0
	li.state_amount = 0
	li.county_taxable_amount = 0
	li.county_tax_rate = 0
	li.county_amount = 0
	li.city_taxable_amount = 0
	li.city_tax_rate = 0
	li.city_amount = 0
	li.special_district_taxable_amount = 0
	li.special_tax_rate = 0
	li.special_district_amount = 0
	li.country_taxable_amount = 0
	li.country_tax_rate = 0
	li.country_tax_collectable = 0
	li.gst_taxable_amount = 200.0
	li.gst_tax_rate = 0.05
	li.gst = 10.0
	li.pst_taxable_amount = 200.0
	li.pst_tax_rate = 0.07
	li.pst = 14.0
	li.qst_taxable_amount = 0
	li.qst_tax_rate = 0
	li.qst = 0
	breakdown.line_items = [li]

	tax_data = MagicMock()
	tax_data.amount_to_collect = 24.0
	tax_data.rate = 0.12
	tax_data.taxable_amount = 200.0
	tax_data.breakdown = breakdown
	tax_data.jurisdictions = MagicMock(state="", county="", city="")

	return tax_data


# ── Tax Breakdown: _extract_breakdown_data tests ────────────────────────────

class TestExtractBreakdownData(UnitTestCase):

	def test_us_breakdown_transaction_rows(self):
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		result = _extract_breakdown_data(tax_data, doc)

		self.assertIsNotNone(result)
		self.assertEqual(len(result["transaction"]), 4)
		jurisdictions = [r["jurisdiction"] for r in result["transaction"]]
		self.assertEqual(jurisdictions, ["State", "County", "City", "Special"])

	def test_us_breakdown_transaction_values(self):
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		result = _extract_breakdown_data(tax_data, doc)

		state_row = result["transaction"][0]
		self.assertEqual(state_row["jurisdiction"], "State")
		self.assertEqual(state_row["name"], "CA")
		self.assertAlmostEqual(state_row["rate"], 0.0625)
		self.assertAlmostEqual(state_row["tax_amount"], 6.25)

	def test_special_district_row_gets_a_static_label_not_a_blank_name(self):
		"""TaxJar's jurisdictions object has no per-special-district name (unlike
		state/county/city) - a blank cell there reads like missing data, so this
		row gets a static descriptive label instead."""
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		result = _extract_breakdown_data(tax_data, doc)

		special_row = next(r for r in result["transaction"] if r["jurisdiction"] == "Special")
		self.assertEqual(special_row["name"], "SPECIAL DISTRICT")

	def test_us_breakdown_totals(self):
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		result = _extract_breakdown_data(tax_data, doc)

		self.assertAlmostEqual(result["totals"]["rate"], 0.0975)
		self.assertAlmostEqual(result["totals"]["amount_to_collect"], 9.75)
		self.assertAlmostEqual(result["totals"]["taxable_amount"], 100.0)

	def test_us_breakdown_line_items(self):
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		result = _extract_breakdown_data(tax_data, doc)

		self.assertEqual(len(result["line_items"]), 1)
		li = result["line_items"][0]
		self.assertEqual(li["id"], 1)
		self.assertAlmostEqual(li["tax_collectable"], 9.75)
		self.assertAlmostEqual(li["taxable_amount"], 100.0)
		self.assertEqual(len(li["breakdown"]), 4)

	def test_us_item_exempt_or_non_taxable(self):
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		result = _extract_breakdown_data(tax_data, doc)

		li = result["line_items"][0]
		for row in li["breakdown"]:
			self.assertAlmostEqual(row["exempt_or_non_taxable"], 0.0)
			self.assertAlmostEqual(row["taxable_amount"], 100.0)

	def test_us_item_partial_exemption(self):
		"""When item_amount > taxable_amount, exempt_or_non_taxable should be the difference."""
		tax_data = _make_us_breakdown()
		tax_data.breakdown.line_items[0].state_taxable_amount = 60.0
		tax_data.breakdown.line_items[0].county_taxable_amount = 60.0
		tax_data.breakdown.line_items[0].city_taxable_amount = 60.0
		tax_data.breakdown.line_items[0].special_district_taxable_amount = 60.0
		doc = _make_doc()
		result = _extract_breakdown_data(tax_data, doc)

		li = result["line_items"][0]
		for row in li["breakdown"]:
			self.assertAlmostEqual(row["taxable_amount"], 60.0)
			self.assertAlmostEqual(row["exempt_or_non_taxable"], 40.0)

	def test_canadian_gst_pst_breakdown(self):
		tax_data = _make_ca_breakdown()
		doc = _make_doc()
		doc.items[0].qty = 2
		doc.items[0].rate = 100.0
		result = _extract_breakdown_data(tax_data, doc)

		self.assertIsNotNone(result)
		jurisdictions = [r["jurisdiction"] for r in result["transaction"]]
		self.assertIn("GST", jurisdictions)
		self.assertIn("PST", jurisdictions)
		self.assertNotIn("State", jurisdictions)

	def test_canadian_breakdown_values(self):
		tax_data = _make_ca_breakdown()
		doc = _make_doc()
		doc.items[0].qty = 2
		doc.items[0].rate = 100.0
		result = _extract_breakdown_data(tax_data, doc)

		gst = next(r for r in result["transaction"] if r["jurisdiction"] == "GST")
		self.assertAlmostEqual(gst["rate"], 0.05)
		self.assertAlmostEqual(gst["tax_amount"], 10.0)

		pst = next(r for r in result["transaction"] if r["jurisdiction"] == "PST")
		self.assertAlmostEqual(pst["rate"], 0.07)
		self.assertAlmostEqual(pst["tax_amount"], 14.0)

	def test_no_breakdown_returns_none(self):
		tax_data = MagicMock()
		tax_data.breakdown = None
		doc = _make_doc()
		result = _extract_breakdown_data(tax_data, doc)
		self.assertIsNone(result)

	def test_jurisdiction_names_from_tax_data(self):
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		result = _extract_breakdown_data(tax_data, doc)

		state_row = next(r for r in result["transaction"] if r["jurisdiction"] == "State")
		self.assertEqual(state_row["name"], "CA")
		county_row = next(r for r in result["transaction"] if r["jurisdiction"] == "County")
		self.assertEqual(county_row["name"], "LOS ANGELES")


# ── Tax Breakdown: _clear_breakdown_data tests ──────────────────────────────

class TestClearBreakdownData(UnitTestCase):

	def test_clears_doc_breakdown_json(self):
		doc = _make_doc()
		doc.taxjar_breakdown_json = '{"transaction": []}'
		_clear_breakdown_data(doc)
		self.assertIsNone(doc.taxjar_breakdown_json)

	def test_clears_item_tax_collectable(self):
		"""tax_collectable is read_only - stale per-line tax on a document that
		now carries none is not something the user can correct by hand."""
		doc = _make_doc()
		doc.items[0].tax_collectable = 91.0
		_clear_breakdown_data(doc)
		self.assertEqual(doc.items[0].tax_collectable, 0)

	def test_clears_freight_taxable(self):
		"""A stale "Shipping Taxability: Yes" pill must not survive past the
		point where the tax rows themselves get removed (exempt/no nexus)."""
		doc = _make_doc()
		doc.taxjar_freight_taxable = 1
		_clear_breakdown_data(doc)
		self.assertEqual(doc.taxjar_freight_taxable, 0)

	def test_handles_doc_without_breakdown_field(self):
		doc = MagicMock()
		doc.get.return_value = []
		del doc.taxjar_breakdown_json
		_clear_breakdown_data(doc)


# ── Tax Breakdown: _store_breakdown_data tests ──────────────────────────────

class TestStoreBreakdownData(UnitTestCase):

	def test_stores_json_on_doc(self):
		import json
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		_store_breakdown_data(tax_data, doc)

		self.assertIsNotNone(doc.taxjar_breakdown_json)
		data = json.loads(doc.taxjar_breakdown_json)
		self.assertIn("transaction", data)
		self.assertIn("totals", data)
		self.assertIn("line_items", data)

	def test_no_breakdown_leaves_none(self):
		tax_data = MagicMock()
		tax_data.breakdown = None
		doc = _make_doc()
		_store_breakdown_data(tax_data, doc)
		self.assertIsNone(doc.taxjar_breakdown_json)


# ── Tax Breakdown: set_sales_tax integration ────────────────────────────────

class TestSetSalesTaxBreakdown(UnitTestCase):

	def test_breakdown_json_populated_on_tax_calc(self):
		"""set_sales_tax should populate taxjar_breakdown_json when tax is calculated."""
		import json
		tax_data = _make_us_breakdown()
		doc = _make_doc()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_region", return_value="United States"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=MagicMock(tax_account_head="Sales Tax - TC", shipping_account_head="Freight - TC")), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_sales_tax_exemption", return_value=(False, None)), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"dummy": True}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_for_nexus", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.validate_tax_request", return_value=tax_data), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value("2026-01-01 00:00:00")), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.cache", return_value=_no_cache()):
			set_sales_tax(doc, None)

		self.assertIsNotNone(doc.taxjar_breakdown_json)
		data = json.loads(doc.taxjar_breakdown_json)
		self.assertEqual(len(data["transaction"]), 4)
		self.assertAlmostEqual(data["totals"]["amount_to_collect"], 9.75)

	def test_freight_taxable_set_from_tax_data(self):
		"""doc.taxjar_freight_taxable mirrors TaxJar's own freight_taxable flag on
		the tax_for_order response, both ways (True and False are both real,
		meaningful values - not "unset")."""
		for freight_taxable, expected in ((True, 1), (False, 0)):
			with self.subTest(freight_taxable=freight_taxable):
				tax_data = _make_us_breakdown()
				tax_data.freight_taxable = freight_taxable
				doc = _make_doc()

				with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
				     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_region", return_value="United States"), \
				     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=MagicMock(tax_account_head="Sales Tax - TC", shipping_account_head="Freight - TC")), \
				     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_sales_tax_exemption", return_value=(False, None)), \
				     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"dummy": True}), \
				     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_for_nexus", return_value=True), \
				     patch("taxjar_integration.taxjar_integration.taxjar_integration.validate_tax_request", return_value=tax_data), \
				     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value("2026-01-01 00:00:00")), \
				     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.cache", return_value=_no_cache()):
					set_sales_tax(doc, None)

				self.assertEqual(doc.taxjar_freight_taxable, expected)

	def test_tax_source_set_from_tax_data(self):
		"""taxjar_tax_source mirrors TaxJar's tax_source off the tax_for_order
		response - which end of the shipment set the rate.

		A missing tax_source writes "" rather than being skipped: passing None
		would leave a previously stored value in place and the form would keep
		showing a pill for a rule that no longer applies.
		"""
		for returned, expected in (("origin", "origin"), ("destination", "destination"), (None, "")):
			with self.subTest(tax_source=returned):
				tax_data = _make_us_breakdown()
				tax_data.tax_source = returned
				doc = _make_doc()
				doc.taxjar_tax_source = "destination"

				with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
				     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_region", return_value="United States"), \
				     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=MagicMock(tax_account_head="Sales Tax - TC", shipping_account_head="Freight - TC")), \
				     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_sales_tax_exemption", return_value=(False, None)), \
				     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"dummy": True}), \
				     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_for_nexus", return_value=True), \
				     patch("taxjar_integration.taxjar_integration.taxjar_integration.validate_tax_request", return_value=tax_data), \
				     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value("2026-01-01 00:00:00")), \
				     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.cache", return_value=_no_cache()):
					set_sales_tax(doc, None)

				self.assertEqual(doc.taxjar_tax_source, expected)

	def test_zero_tax_keeps_row_and_stores_breakdown(self):
		"""When TaxJar returns zero tax, a $0 row should be added and breakdown stored."""
		import json
		tax_data = _make_us_breakdown()
		tax_data.amount_to_collect = 0.0
		tax_data.rate = 0.0
		doc = _make_doc()

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_region", return_value="United States"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=MagicMock(tax_account_head="Sales Tax - TC", shipping_account_head="Freight - TC")), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_sales_tax_exemption", return_value=(False, None)), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"dummy": True}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_for_nexus", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.validate_tax_request", return_value=tax_data), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value("2026-01-01 00:00:00")), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.cache", return_value=_no_cache()):
			set_sales_tax(doc, None)

		tax_rows = [t for t in doc.taxes if t.account_head == "Sales Tax - TC"]
		self.assertEqual(len(tax_rows), 1)
		self.assertEqual(tax_rows[0].tax_amount, 0.0)
		self.assertIsNotNone(doc.taxjar_breakdown_json)
		data = json.loads(doc.taxjar_breakdown_json)
		self.assertIn("transaction", data)

	def test_breakdown_cleared_when_outside_nexus(self):
		"""When delivery is outside nexus, breakdown should be cleared."""
		doc = _make_doc(taxes=[_make_tax_row("Sales Tax - TC", "Tax", 80.0)])
		doc.taxjar_breakdown_json = '{"old": "data"}'
		doc.items[0].tax_collectable = 80.0
		company_config = MagicMock(tax_account_head="Sales Tax - TC", shipping_account_head="Freight - TC")

		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_single_value", return_value=1), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_region", return_value="United States"), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=company_config), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.check_sales_tax_exemption", return_value=(False, None)), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_tax_data", return_value={"to_state": "TX", "dummy": True}), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value(None)):
			set_sales_tax(doc, None)

		self.assertIsNone(doc.taxjar_breakdown_json)
		self.assertEqual(doc.items[0].tax_collectable, 0)


# ── Tax Breakdown: Custom field schema tests ────────────────────────────────

class TestTaxBreakdownCustomFields(UnitTestCase):

	def _captured_custom_fields(self):
		"""Return make_custom_fields()' dict without letting it touch the DB."""
		from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
			make_custom_fields,
		)

		captured = {}

		def _capture(custom_fields, update=True):
			captured.update(custom_fields)

		with patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.create_custom_fields",
			side_effect=_capture,
		), patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.make_property_setter"
		):
			make_custom_fields()

		return captured

	def test_transaction_breakdown_fields_defined(self):
		self.assertEqual(len(_TRANSACTION_BREAKDOWN_FIELDS), 5)
		fieldnames = [f["fieldname"] for f in _TRANSACTION_BREAKDOWN_FIELDS]
		self.assertIn("taxjar_breakdown_section", fieldnames)
		self.assertIn("taxjar_breakdown_json", fieldnames)
		self.assertIn("taxjar_freight_taxable", fieldnames)
		self.assertIn("taxjar_freight_taxable_html", fieldnames)
		self.assertIn("taxjar_breakdown_html", fieldnames)

	def test_freight_taxable_field_is_hidden_read_only_check(self):
		field = next(f for f in _TRANSACTION_BREAKDOWN_FIELDS if f["fieldname"] == "taxjar_freight_taxable")
		self.assertEqual(field["fieldtype"], "Check")
		self.assertEqual(field["hidden"], 1)
		self.assertEqual(field["read_only"], 1)
		self.assertEqual(field["insert_after"], "taxjar_breakdown_json")

	def test_freight_taxable_html_is_plain_html_not_boxed(self):
		"""Deliberately plain HTML, not Text Editor - a read-only Text Editor
		field wraps its content in a boxed "like-disabled-input" background,
		which is right for the table but wrong for a standalone pill."""
		field = next(f for f in _TRANSACTION_BREAKDOWN_FIELDS if f["fieldname"] == "taxjar_freight_taxable_html")
		self.assertEqual(field["fieldtype"], "HTML")
		self.assertEqual(field["insert_after"], "taxjar_freight_taxable")

	def test_breakdown_html_is_virtual_text_editor(self):
		"""Server-rendered virtual field (set by onload/before_print via
		set_taxjar_breakdown_html), same shape as india_compliance's
		gst_breakup_table - not a plain HTML display field anymore, so it
		actually shows up in Print/PDF, not just the desk form."""
		field = next(f for f in _TRANSACTION_BREAKDOWN_FIELDS if f["fieldname"] == "taxjar_breakdown_html")
		self.assertEqual(field["fieldtype"], "Text Editor")
		self.assertEqual(field["is_virtual"], 1)
		self.assertEqual(field["read_only"], 1)
		self.assertEqual(field["allow_on_submit"], 1)
		self.assertEqual(field["insert_after"], "taxjar_freight_taxable_html")

	def test_sales_invoice_freight_taxable_allows_on_submit(self):
		"""Written alongside taxjar_breakdown_json on the post-submission
		recalculation path - needs the same allow_on_submit exemption."""
		from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import make_custom_fields

		captured = {}

		def _capture(custom_fields, update=True):
			captured.update(custom_fields)

		with patch(
			"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.create_custom_fields",
			side_effect=_capture,
		):
			make_custom_fields()

		field = next(f for f in captured["Sales Invoice"] if f["fieldname"] == "taxjar_freight_taxable")
		self.assertEqual(field.get("allow_on_submit"), 1)

	def test_item_tables_carry_only_tax_engine_fields(self):
		"""The item tables keep only what TaxJar actually reads back: the
		category that feeds product_tax_code, and the per-line tax that becomes
		sales_tax on create_order. Everything else was display."""
		fields = _item_tax_fields()
		self.assertEqual(
			[f["fieldname"] for f in fields],
			["product_tax_category", "tax_collectable"],
		)

	def test_removed_display_fields_are_not_recreated(self):
		"""The patch deletes these; make_custom_fields must not put them back."""
		captured = self._captured_custom_fields()
		for dt in ("Quotation Item", "Sales Order Item", "Sales Invoice Item"):
			fieldnames = [f["fieldname"] for f in captured[dt]]
			for gone in ("taxable_amount", "taxjar_item_tax_section",
			             "taxjar_item_breakdown_json", "taxjar_item_breakdown_html"):
				self.assertNotIn(gone, fieldnames, f"{gone} still defined on {dt}")

	def test_product_tax_category_is_read_only(self):
		"""Fetched from the Item master and frozen: the stored copy is what a
		retried sync sends days after submit, so it must not drift."""
		field = next(f for f in _item_tax_fields() if f["fieldname"] == "product_tax_category")
		self.assertEqual(field["read_only"], 1)
		self.assertEqual(field["fetch_from"], "item_code.product_tax_category")

	def test_item_fields_are_print_hidden(self):
		"""Without print_hide a child field becomes a column in the item table
		of every printed document - same reason core sets it on net_amount."""
		for field in _item_tax_fields():
			self.assertEqual(field["print_hide"], 1, field["fieldname"])

	def test_tax_collectable_is_no_copy(self):
		"""Stops a quotation's per-line tax riding into a sales order, invoice,
		or credit note as a stale read-only figure."""
		field = next(f for f in _item_tax_fields() if f["fieldname"] == "tax_collectable")
		self.assertEqual(field["no_copy"], 1)

	def test_breakdown_fields_on_all_transaction_doctypes(self):
		from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import get_custom_fields
		import inspect
		source = inspect.getsource(get_custom_fields)
		for dt in ("Quotation", "Sales Order", "Sales Invoice"):
			self.assertIn(dt, source, f"make_custom_fields should reference {dt}")

	def test_item_breakdown_fields_on_all_item_tables(self):
		from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import get_custom_fields
		import inspect
		source = inspect.getsource(get_custom_fields)
		for dt in ("Quotation Item", "Sales Order Item", "Sales Invoice Item"):
			self.assertIn(dt, source, f"make_custom_fields should reference {dt}")

	def test_sales_invoice_breakdown_json_allows_on_submit(self):
		from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import get_custom_fields
		import inspect
		source = inspect.getsource(get_custom_fields)
		self.assertIn("allow_on_submit", source)

	def test_transaction_fields_insert_after_other_charges(self):
		for f in _TRANSACTION_BREAKDOWN_FIELDS:
			if f["fieldname"] == "taxjar_breakdown_section":
				self.assertEqual(f["insert_after"], "other_charges_calculation")

	def test_item_fields_insert_after_core_columns(self):
		expected = {"product_tax_category": "description", "tax_collectable": "net_amount"}
		for f in _item_tax_fields():
			self.assertEqual(f["insert_after"], expected[f["fieldname"]])


# ── Tax Breakdown: server-side HTML rendering (get_taxjar_breakdown_html) ──
# Same tax-break-up/table-bordered/table-hover markup as core ERPNext's Tax
# Breakup table and india_compliance's GST Breakup Table, rendered server-side
# via Jinja (templates/includes/taxjar_breakup.html) instead of built in JS.

class TestGetTaxjarBreakdownHtml(UnitTestCase):

	def test_no_json_shows_no_breakdown_message(self):
		doc = _make_doc()
		html = get_taxjar_breakdown_html(doc)
		self.assertIn("No TaxJar tax breakdown available", html)

	def test_invalid_json_falls_back_to_no_breakdown_message(self):
		doc = _make_doc()
		doc.taxjar_breakdown_json = "not json"
		html = get_taxjar_breakdown_html(doc)
		self.assertIn("No TaxJar tax breakdown available", html)

	def test_renders_table_with_core_erpnext_markup(self):
		"""Same skeleton as erpnext's itemised_tax_breakup.html /
		india_compliance's gst_breakup.html - and, unlike the old JS builder,
		no inline thead background overriding the default desk table theme."""
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		_store_breakdown_data(tax_data, doc)
		html = get_taxjar_breakdown_html(doc)
		self.assertIn('class="tax-break-up"', html)
		self.assertIn("table-bordered", html)
		self.assertIn("table-hover", html)
		self.assertIn("Jurisdiction", html)
		self.assertNotIn("background-color", html)

	def test_output_has_no_newlines_or_tabs(self):
		"""Jinja's {% if/for %} control tags leave their surrounding blank
		lines/indentation in the rendered output; a Text Editor field renders
		that whitespace as real vertical gaps in the desk form (a large empty
		block above the table). Same fix india_compliance applies to its own
		gst_breakup_table render."""
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		_store_breakdown_data(tax_data, doc)
		doc.taxjar_freight_taxable = 1
		html = get_taxjar_breakdown_html(doc)
		self.assertNotIn("\n", html)
		self.assertNotIn("\t", html)

	def test_jurisdiction_rendered_bold(self):
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		_store_breakdown_data(tax_data, doc)
		html = get_taxjar_breakdown_html(doc)
		self.assertIn("<strong>State</strong>", html)
		self.assertIn("<strong>County</strong>", html)
		self.assertIn("<strong>Special</strong>", html)

	def test_no_usd_block_for_single_currency_doc(self):
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		_store_breakdown_data(tax_data, doc)
		html = get_taxjar_breakdown_html(doc)
		self.assertNotIn("Tax Calculation (USD)", html)

	def test_usd_block_rendered_for_multi_currency_doc(self):
		tax_data = _make_us_breakdown()
		doc = _make_doc(currency="EUR")
		_store_breakdown_data(tax_data, doc, usd_rate=1.1)
		html = get_taxjar_breakdown_html(doc)
		self.assertIn("Tax Calculation (USD)", html)
		self.assertIn("Equivalent in Transaction Currency (EUR)", html)
		self.assertIn("multi-currency transaction", html)

	def test_pill_not_part_of_server_rendered_html(self):
		"""The shipping-taxability pill moved to its own plain-HTML field
		(taxjar_freight_taxable_html, rendered client-side by
		render_shipping_taxability in taxjar_utils.js) - a read-only Text
		Editor field boxes its whole content in a "like-disabled-input"
		background, which reads fine around the table but wrong around a
		standalone indicator pill sitting inside it."""
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		_store_breakdown_data(tax_data, doc)
		doc.taxjar_freight_taxable = 1
		html = get_taxjar_breakdown_html(doc)
		self.assertNotIn("Is shipping charges taxable?", html)
		self.assertNotIn("indicator-pill", html)

	def test_jurisdiction_and_name_are_html_escaped(self):
		"""Defensive escaping of TaxJar-sourced jurisdiction/name text, same
		posture as the old JS's frappe.utils.escape_html() calls."""
		import json as _json
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		_store_breakdown_data(tax_data, doc)
		data = _json.loads(doc.taxjar_breakdown_json)
		data["transaction"][0]["name"] = "<script>alert(1)</script>"
		doc.taxjar_breakdown_json = _json.dumps(data)
		html = get_taxjar_breakdown_html(doc)
		self.assertNotIn("<script>alert(1)</script>", html)
		self.assertIn("&lt;script&gt;", html)


# ── Tax Breakdown: onload/before_print wiring (set_taxjar_breakdown_html) ──

class TestSetTaxjarBreakdownHtml(UnitTestCase):

	def test_onload_sets_onload_key_not_field(self):
		"""Desk form: pushed via set_onload for the client shim to copy onto
		the field, since the browser already holds its own copy of the doc."""
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		_store_breakdown_data(tax_data, doc)
		set_taxjar_breakdown_html(doc, "onload")
		self.assertIsNone(doc.taxjar_breakdown_html)
		self.assertIn("Jurisdiction", doc.get_onload("_taxjar_breakdown_html"))

	def test_before_print_sets_field_directly(self):
		"""Print/PDF: assigned directly, since print rendering reads this same
		in-memory doc in the same request - no client round trip involved.
		Called as doc.run_method("before_print", print_settings) by
		frappe.www.printview - the print_settings positional arg must not
		raise a TypeError."""
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		_store_breakdown_data(tax_data, doc)
		set_taxjar_breakdown_html(doc, "before_print", {"some": "print_settings"})
		self.assertIsNotNone(doc.taxjar_breakdown_html)
		self.assertIn("Jurisdiction", doc.taxjar_breakdown_html)
		self.assertEqual(doc.get_onload(), {})

	def test_noop_when_doc_has_no_breakdown_html_field(self):
		doc = _make_doc()
		doc.meta = _FakeMeta(fields=())
		set_taxjar_breakdown_html(doc, "onload")
		self.assertEqual(doc.get_onload(), {})

	def test_real_document_virtual_field_has_no_instance_attribute_when_loaded_from_db(self):
		"""Regression guard for the exact bug this class exists to prevent:
		hasattr(doc, "taxjar_breakdown_html") is False on a document loaded via
		Document.load_from_db(), because is_virtual fields with no backing
		@property are never set as instance attributes there - load_from_db
		populates BaseDocument.__init__ from a raw "SELECT *" row dict, which
		only has real DB columns, and (unlike frappe.new_doc(), which does call
		init_valid_columns() and so does NOT reproduce this) never backfills
		virtual fields to None. A guard using hasattr() instead of
		doc.meta.has_field() silently no-opped set_taxjar_breakdown_html for
		every already-saved document - exactly what onload/before_print always
		deal with.

		Reproduces that exact construction path (BaseDocument.__init__ from a
		bare dict, the same call load_from_db makes) without needing a
		persisted record, since frappe.new_doc()/frappe.get_doc({...}) both
		route through init_valid_columns() and would not reproduce the bug."""
		from frappe.model.base_document import BaseDocument
		from frappe.model.document import get_controller

		controller = get_controller("Quotation")
		doc = controller.__new__(controller)
		doc.flags = frappe._dict()
		BaseDocument.__init__(doc, {"doctype": "Quotation", "name": "QTN-TEST-0001", "company": "_Test Company"})

		self.assertTrue(doc.meta.has_field("taxjar_breakdown_html"))
		self.assertFalse(hasattr(doc, "taxjar_breakdown_html"))

	def test_onload_populates_real_document_loaded_from_db(self):
		"""End-to-end against the real onload dispatch path AND the
		load_from_db-shaped construction from the test above - together these
		cover the exact scenario that broke in production: a doc.meta.has_field()
		guard (fixed) vs. the hasattr() guard (buggy) it replaced, wired through
		the real set_onload()/__onload round trip."""
		from frappe.desk.form.load import run_onload
		from frappe.model.base_document import BaseDocument
		from frappe.model.document import get_controller

		controller = get_controller("Quotation")
		doc = controller.__new__(controller)
		doc.flags = frappe._dict()
		BaseDocument.__init__(doc, {"doctype": "Quotation", "name": "QTN-TEST-0001", "company": "_Test Company"})
		doc.items = []
		doc.append("items", {"item_code": "_Test Item", "qty": 1, "rate": 100})
		doc.taxjar_breakdown_json = frappe.as_json(_extract_breakdown_data(_make_us_breakdown(), doc))

		run_onload(doc)

		html = doc.get_onload("_taxjar_breakdown_html")
		self.assertIsNotNone(html)
		self.assertIn("Jurisdiction", html)


class TestTaxjarBreakdownHtmlHooksRegistered(UnitTestCase):
	"""onload/before_print never fire for a hook registered on the wrong key
	(e.g. a child doctype - see the child-table field investigation for why
	that matters) - so this pins the exact transaction-doctype grouping the
	hook must be registered under."""

	def _transaction_doc_events(self):
		from taxjar_integration import hooks
		for doctypes, events in hooks.doc_events.items():
			key = doctypes if isinstance(doctypes, tuple) else (doctypes,)
			if set(("Quotation", "Sales Order", "Sales Invoice")) <= set(key):
				return events
		return {}

	def test_onload_registered_on_transaction_doctypes(self):
		events = self._transaction_doc_events()
		self.assertIn("set_taxjar_breakdown_html", events.get("onload", ""))

	def test_before_print_registered_on_transaction_doctypes(self):
		events = self._transaction_doc_events()
		self.assertIn("set_taxjar_breakdown_html", events.get("before_print", ""))


# ── Tax Breakdown: JS structure tests ───────────────────────────────────────

class TestTaxBreakdownJS(UnitTestCase):

	def _js_dir(self):
		import os
		return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "public", "js"))

	def _read_js(self, filename):
		import os
		with open(os.path.join(self._js_dir(), filename)) as f:
			return f.read()

	def _read_breakup_template(self):
		import os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "..", "templates", "includes", "taxjar_breakup.html",
		))
		with open(path) as f:
			return f.read()

	def test_shared_utils_defines_render_functions(self):
		# Breakdown rendering is shared in the globally-bundled taxjar_utils.js;
		# the per-doctype scripts call the namespaced helpers (see tests below).
		js = self._read_js("taxjar_utils.js")
		self.assertIn("taxjar_integration.render_tax_breakdown", js)
		self.assertIn("taxjar_breakdown_json", js)

	def test_quotation_js_exists(self):
		import os
		path = os.path.join(self._js_dir(), "quotation.js")
		self.assertTrue(os.path.isfile(path))

	def test_sales_order_js_exists(self):
		import os
		path = os.path.join(self._js_dir(), "sales_order.js")
		self.assertTrue(os.path.isfile(path))

	def test_quotation_js_has_render_functions(self):
		js = self._read_js("quotation.js")
		self.assertIn("taxjar_integration.render_tax_breakdown", js)

	def test_sales_order_js_has_render_functions(self):
		js = self._read_js("sales_order.js")
		self.assertIn("taxjar_integration.render_tax_breakdown", js)

	def test_sales_invoice_js_has_render_functions(self):
		js = self._read_js("sales_invoice.js")
		self.assertIn("taxjar_integration.render_tax_breakdown", js)

	def test_hooks_register_quotation_js(self):
		from taxjar_integration.hooks import doctype_js
		self.assertIn("Quotation", doctype_js)
		self.assertIn("quotation.js", doctype_js["Quotation"])

	def test_hooks_register_sales_order_js(self):
		from taxjar_integration.hooks import doctype_js
		self.assertIn("Sales Order", doctype_js)
		self.assertIn("sales_order.js", doctype_js["Sales Order"])

	def test_status_cards_never_render_reason_text(self):
		"""No reason text anywhere in the matrix - only the answer pill (and,
		for a transaction-level override, the extra "Overridden" pill)."""
		js = self._read_js("taxjar_utils.js")
		render_fn = js.split("render_status_cards = function (frm) {")[1].split("\n};")[0]
		self.assertNotIn("card.reason", render_fn)
		self.assertNotIn("taxjar-status-card-reason", render_fn)
		self.assertNotIn("taxjar_product_taxable_reason", render_fn)

	def test_transaction_override_is_appended_to_the_answer(self):
		"""It used to be a second "Overridden" pill keyed off a reason-string
		prefix. Now the answer itself says so, read straight off the checkbox
		rather than by parsing prose."""
		js = self._read_js("taxjar_utils.js")
		render_fn = js.split("render_status_cards = function (frm) {")[1].split("\n};")[0]
		self.assertIn('__("Yes, but transaction is marked as exempt")', render_fn)
		self.assertIn("taxjar_integration._has_transaction_exemption(frm)", render_fn)
		self.assertNotIn(".startsWith(", render_fn)

	def test_product_card_skipped_when_the_sale_is_exempt_either_way(self):
		"""Product taxability is moot once the sale is exempt - whether that
		came from the customer master or the transaction override."""
		js = self._read_js("taxjar_utils.js")
		render_fn = js.split("render_status_cards = function (frm) {")[1].split("\n};")[0]
		self.assertIn("if (!customer_taxable || transaction_exempt) {", render_fn)

	def test_status_cards_use_skipped_instead_of_na(self):
		js = self._read_js("taxjar_utils.js")
		render_fn = js.split("render_status_cards = function (frm) {")[1].split("\n};")[0]
		self.assertNotIn('__("N/A")', render_fn)
		self.assertIn('__("Skipped")', render_fn)

	def test_status_card_override_css_removed_with_the_pill(self):
		"""Nothing renders that class any more."""
		js = self._read_js("taxjar_utils.js")
		self.assertNotIn("taxjar-status-card-override", js)

	def test_js_has_no_breakdown_message(self):
		js = self._read_js("taxjar_utils.js")
		self.assertIn("No TaxJar tax breakdown available", js, "taxjar_utils.js should have no-breakdown message")

	def test_no_breakdown_msg_distinguishes_unsaved_doc(self):
		js = self._read_js("taxjar_utils.js")
		fn = js.split("_no_breakdown_msg = function (is_new, frm) {")[1].split("\n};")[0]
		self.assertIn("Save transaction to fetch sales tax & view breakup.", fn)
		# Still keyed on is_new; a ternary became an if/else when the no-nexus
		# case was added as a third branch.
		self.assertIn("if (is_new) {", fn)

	def test_render_tax_breakdown_copies_from_onload(self):
		"""The table itself is rendered server-side (see the
		get_taxjar_breakdown_html tests) - this just copies the result from
		frm.doc.__onload onto the virtual field, with a client-side fallback
		message for a truly new/unsaved doc (which never goes through the
		server onload) and for the unexpected case of a saved doc missing
		__onload entirely."""
		js = self._read_js("taxjar_utils.js")
		fn = js.split("render_tax_breakdown = function (frm) {")[1].split("\n};")[0]
		self.assertIn("_no_breakdown_msg(true)", fn)
		self.assertIn("_no_breakdown_msg(false, frm)", fn)
		self.assertIn("frm.doc.__onload?._taxjar_breakdown_html", fn)
		self.assertIn('frm.refresh_field("taxjar_breakdown_html")', fn)

	def test_shipping_taxability_pill_defined_in_js(self):
		"""Plain-HTML field (taxjar_freight_taxable_html), rendered
		client-side straight off the already-loaded taxjar_freight_taxable
		field - no server round trip needed, and deliberately not part of
		templates/includes/taxjar_breakup.html since a read-only Text Editor
		field would box it together with the table."""
		js = self._read_js("taxjar_utils.js")
		fn = js.split("render_shipping_taxability = function (frm) {")[1].split("\n};")[0]
		self.assertIn("taxjar_freight_taxable", fn)
		self.assertIn("Is shipping charges taxable?", fn)
		self.assertIn("frappe.ui.badge.html(", fn)
		self.assertNotIn("indicator-pill", fn)
		self.assertIn('__("Yes")', fn)
		self.assertIn('__("No")', fn)

	def test_shipping_taxability_pill_uses_bigger_font(self):
		js = self._read_js("taxjar_utils.js")
		fn = js.split("render_shipping_taxability = function (frm) {")[1].split("\n};")[0]
		self.assertIn("var(--text-md)", fn)
		self.assertNotIn("var(--text-sm)", fn)

	def test_shipping_taxability_pill_wired_into_refresh(self):
		for filename in ("sales_invoice.js", "sales_order.js", "quotation.js"):
			js = self._read_js(filename)
			self.assertIn(
				"taxjar_integration.render_shipping_taxability(frm)", js,
				f"{filename} should call render_shipping_taxability on refresh",
			)

	def test_breakup_template_has_multi_currency_support(self):
		template = self._read_breakup_template()
		self.assertIn("data.usd", template, "taxjar_breakup.html should check for USD breakdown data")
		self.assertIn("Tax Calculation (USD)", template, "taxjar_breakup.html should have USD table heading")
		self.assertIn("Equivalent in Transaction Currency", template, "taxjar_breakup.html should have converted table heading")

	def test_breakup_template_uses_erpnext_table_styling(self):
		"""Same tax-break-up/table-bordered/table-hover markup as core
		ERPNext's own Tax Breakup table and india_compliance's GST Breakup
		Table - and, unlike the old JS builder, no inline thead background
		overriding the default desk table theme."""
		template = self._read_breakup_template()
		self.assertIn("table-hover", template)
		self.assertIn('class="tax-break-up"', template)
		self.assertIn("overflow-x: auto", template)
		self.assertNotIn("table-sm", template)
		self.assertNotIn("background-color", template)


# ── TaxJar Sync Status: sidebar pill ────────────────────────────────────────

class TestSyncStatusSidebarPill(UnitTestCase):

	def _js_dir(self):
		import os
		return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "public", "js"))

	def _read_js(self, filename):
		import os
		with open(os.path.join(self._js_dir(), filename)) as f:
			return f.read()

	def _dispatcher_fn(self):
		"""render_sync_status_sidebar_pill: the entry point wired into
		refresh(). Decides live, via is_taxjar_enabled_for_company, whether
		to render the pill or the not-enabled link."""
		js = self._read_js("taxjar_utils.js")
		return js.split("render_sync_status_sidebar_pill = function (frm) {")[1].split("\n};")[0]

	def _not_enabled_fn(self):
		js = self._read_js("taxjar_utils.js")
		return js.split("_render_taxjar_not_enabled_link = function (frm) {")[1].split("\n};")[0]

	def _render_fn(self):
		"""_render_taxjar_sync_status_pill: only reached once
		is_taxjar_enabled_for_company has confirmed TaxJar applies to this
		company, so it no longer needs its own "not enabled" branch."""
		js = self._read_js("taxjar_utils.js")
		return js.split("_render_taxjar_sync_status_pill = function (frm) {")[1].split("\n};")[0]

	def test_status_colors_match_transactions_page(self):
		"""Same mapping as STATUS_COLORS in taxjar_transactions.js, kept as
		its own copy since that page's version is bound to its own class."""
		js = self._read_js("taxjar_utils.js")
		colors = js.split("SYNC_STATUS_COLORS = {")[1].split("};")[0]
		self.assertIn('Synced: "green"', colors)
		self.assertIn('Failed: "red"', colors)
		self.assertIn('Queued: "blue"', colors)
		self.assertIn('Excluded: "gray"', colors)

	def test_dispatcher_checks_live_not_cached(self):
		"""Company enable/create-transactions state is read fresh on every
		refresh via a whitelisted call, not cached on the transaction doc -
		a stored flag would go stale for an unsaved Draft, or worse for a
		Cancelled doc, which is never saved again."""
		fn = self._dispatcher_fn()
		self.assertIn(
			'method: "taxjar_integration.taxjar_integration.taxjar_integration.is_taxjar_enabled_for_company"',
			fn,
		)
		self.assertIn("args: { company: frm.doc.company }", fn)

	def test_dispatcher_requires_company(self):
		fn = self._dispatcher_fn()
		self.assertIn("!frm.doc.company", fn)

	def test_dispatcher_dispatches_on_response(self):
		fn = self._dispatcher_fn()
		self.assertIn("_render_taxjar_not_enabled_link(frm)", fn)
		self.assertIn("_render_taxjar_sync_status_pill(frm)", fn)

	def test_not_enabled_link_has_no_status_label(self):
		"""No bold "TaxJar Status" heading and no indicator-pill background -
		just a plain link, since there's no sync state to report when TaxJar
		isn't configured for the company at all."""
		fn = self._not_enabled_fn()
		self.assertNotIn("TaxJar Status", fn)
		self.assertNotIn("indicator-pill", fn)

	def test_not_enabled_link_text_and_href(self):
		fn = self._not_enabled_fn()
		self.assertIn("Configure TaxJar", fn)
		self.assertIn('href="/app/taxjar-setup"', fn)

	def test_not_enabled_link_has_dotted_underline_and_icon(self):
		fn = self._not_enabled_fn()
		self.assertIn("underline dotted", fn)
		self.assertIn('frappe.utils.icon("external-link"', fn)

	def test_not_enabled_link_icon_is_inside_the_anchor(self):
		"""Text and icon both sit inside the single <a> so the whole thing -
		icon included - is one clickable target, not just the text."""
		fn = self._not_enabled_fn()
		anchor = fn.split("<a")[1].split("</a>")[0]
		self.assertIn("Configure TaxJar", anchor)
		self.assertIn("icon", anchor)

	def test_not_enabled_link_only_renders_for_a_united_states_company(self):
		"""TaxJar is a US sales-tax service - the guided setup wizard this link
		points at has nothing to offer a company whose country isn't United
		States, so the link must check the company's country before rendering
		rather than assuming every company it's asked about is a candidate."""
		fn = self._not_enabled_fn()
		self.assertIn('frappe.db.get_value("Company", frm.doc.company, "country")', fn)
		self.assertIn('!== "United States"', fn)

		# The guard must sit before the section is built/inserted, not after -
		# otherwise the section briefly exists for a non-US company.
		guard_pos = fn.index('!== "United States"')
		section_pos = fn.index("taxjar-sync-sidebar-pill-section")
		self.assertLess(guard_pos, section_pos)

	def test_draft_shows_submit_to_sync_label(self):
		fn = self._render_fn()
		self.assertIn("docstatus === 0", fn)
		self.assertIn('__("Submit to Sync")', fn)
		self.assertIn('color = "amber"', fn)

	def test_synced_info_text_shows_last_synced(self):
		fn = self._render_fn()
		synced_branch = fn.split('status === "Synced"')[1].split('} else if (status === "Failed")')[0]
		self.assertIn("Last synced:", synced_branch)
		self.assertIn("taxjar_last_synced", synced_branch)

	def test_synced_label_depends_on_cancelled(self):
		fn = self._render_fn()
		synced_branch = fn.split('status === "Synced"')[1].split('} else if (status === "Failed")')[0]
		self.assertIn('cancelled ? __("Cancelled") : __("Synced")', synced_branch)

	def test_cancelled_pill_is_grey_not_green(self):
		"""Cancelled reuses the "Synced" status value (see _set_sync_status's
		shared write for both the on_submit and on_cancel paths), but should
		read as a neutral gray badge, not the green used for an active sync."""
		fn = self._render_fn()
		synced_branch = fn.split('status === "Synced"')[1].split('} else if (status === "Failed")')[0]
		self.assertIn('cancelled ? "gray" : taxjar_integration.SYNC_STATUS_COLORS[status]', synced_branch)

	def test_queued_info_text(self):
		fn = self._render_fn()
		self.assertIn("Queued for sync", fn)

	def test_failed_info_text_uses_sync_error(self):
		fn = self._render_fn()
		failed_branch = fn.split('status === "Failed"')[1]
		self.assertIn("taxjar_sync_error", failed_branch)

	def test_failed_label_depends_on_cancelled(self):
		fn = self._render_fn()
		failed_branch = fn.split('status === "Failed"')[1]
		self.assertIn('cancelled ? __("Failed to Cancel") : __("Failed")', failed_branch)

	def test_inserted_below_doc_id_above_assign(self):
		"""Sits below the doc id (after .sidebar-meta-details, the
		title/doc-id block) and above Assign/Attachments/Tags/Share, with its
		own border-bottom separating it from Assign below - matching
		.sidebar-meta-details' own border-bottom above it."""
		fn = self._render_fn()
		self.assertIn(".after($pill)", fn)
		self.assertIn("border-bottom", fn)
		not_enabled_fn = self._not_enabled_fn()
		self.assertIn('.find(".form-sidebar .sidebar-meta-details")', not_enabled_fn)
		self.assertIn("border-bottom", not_enabled_fn)

	def test_removes_stale_pill_before_rendering(self):
		"""Idempotent re-render, same pattern as india_compliance's own
		.remove()-then-readd, so repeated refresh() calls on the same
		document don't stack duplicate pills. Lives in the dispatcher, since
		either render path below it needs the slate wiped first."""
		fn = self._dispatcher_fn()
		self.assertIn('.taxjar-sync-sidebar-pill-section").remove()', fn)

	def test_no_field_no_pill(self):
		"""Guards doctypes without the sync fields (Quotation, Sales Order) -
		the pill is Sales Invoice only."""
		fn = self._dispatcher_fn()
		self.assertIn("!frm.fields_dict.taxjar_sync_status", fn)

	def test_bold_status_label_shown(self):
		"""Only shown once TaxJar is confirmed enabled for the company - the
		not-enabled link (above) deliberately has no such label."""
		fn = self._render_fn()
		self.assertIn("TaxJar Status", fn)
		self.assertIn("font-weight: 600", fn)

	def test_uses_indicator_pill_no_dot_class(self):
		"""frappe.ui.badge, not the old india_compliance-style indicator-pill
		no-indicator-dot pill - badges never draw the leading dot in the
		first place, so there's no dot class to suppress."""
		fn = self._render_fn()
		self.assertIn("frappe.ui.badge({ label, theme: color });", fn)
		self.assertNotIn("indicator-pill", fn)

	def test_hover_and_click_wired_not_native_title(self):
		"""frappe.ui.popover, not a hand-rolled hover/click popover and not
		the native title attribute (which enforces its own delay and never
		responds to a click). Popover is click-toggle only - trading the old
		hover preview for the same native component the Customers/
		Transactions pages' own Sync Status columns already use."""
		fn = self._render_fn()
		self.assertIn('frappe.ui.popover({ trigger: $badge, content: () => info_text, side: "bottom" });', fn)
		self.assertNotIn('.on("mouseenter"', fn)
		self.assertNotIn("title=", fn)

	def test_wired_into_sales_invoice_refresh(self):
		js = self._read_js("sales_invoice.js")
		self.assertIn("taxjar_integration.render_sync_status_sidebar_pill(frm)", js)


# ── Tax Breakdown: Multi-currency tests ─────────────────────────────────────

class TestGetTransactionDate(UnitTestCase):

	def test_uses_posting_date_for_sales_invoice(self):
		doc = _make_doc()
		doc.posting_date = "2026-01-15"
		doc.transaction_date = "2026-01-10"
		self.assertEqual(_get_transaction_date(doc), "2026-01-15")

	def test_falls_back_to_transaction_date(self):
		doc = _make_doc()
		doc.posting_date = None
		doc.transaction_date = "2026-01-10"
		self.assertEqual(_get_transaction_date(doc), "2026-01-10")


class TestGetUsdExchangeRate(UnitTestCase):

	def test_returns_none_for_usd(self):
		doc = _make_doc(currency="USD")
		self.assertIsNone(_get_usd_exchange_rate(doc))

	def test_returns_rate_for_non_usd(self):
		doc = _make_doc(currency="EUR")
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_exchange_rate", return_value=1.0856):
			rate = _get_usd_exchange_rate(doc)
		self.assertAlmostEqual(rate, 1.0856)

	def test_throws_when_rate_not_found(self):
		doc = _make_doc(currency="EUR")
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.get_exchange_rate", return_value=0), \
		     self.assertRaises(Exception):
			_get_usd_exchange_rate(doc)


class TestConvertBreakdownAmounts(UnitTestCase):

	def test_converts_transaction_rows(self):
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		usd_data = _extract_breakdown_data(tax_data, doc)
		converted = _convert_breakdown_amounts(usd_data, 1.1)

		state = converted["transaction"][0]
		self.assertAlmostEqual(state["tax_amount"], 6.25 / 1.1, places=2)

	def test_converts_totals(self):
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		usd_data = _extract_breakdown_data(tax_data, doc)
		converted = _convert_breakdown_amounts(usd_data, 1.1)

		self.assertAlmostEqual(converted["totals"]["amount_to_collect"], 9.75 / 1.1, places=2)
		self.assertEqual(converted["totals"]["rate"], usd_data["totals"]["rate"])

	def test_converts_line_item_amounts(self):
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		usd_data = _extract_breakdown_data(tax_data, doc)
		converted = _convert_breakdown_amounts(usd_data, 1.1)

		li = converted["line_items"][0]
		self.assertAlmostEqual(li["tax_collectable"], 9.75 / 1.1, places=2)
		self.assertAlmostEqual(li["item_amount"], 100.0 / 1.1, places=2)

	def test_converts_item_breakdown_rows(self):
		tax_data = _make_us_breakdown()
		doc = _make_doc()
		usd_data = _extract_breakdown_data(tax_data, doc)
		converted = _convert_breakdown_amounts(usd_data, 2.0)

		li_row = converted["line_items"][0]["breakdown"][0]
		self.assertAlmostEqual(li_row["taxable_amount"], 50.0)
		self.assertAlmostEqual(li_row["exempt_or_non_taxable"], 0.0)


class TestStoreBreakdownMultiCurrency(UnitTestCase):

	def test_usd_doc_stores_currency_field(self):
		import json
		tax_data = _make_us_breakdown()
		doc = _make_doc(currency="USD")
		_store_breakdown_data(tax_data, doc)

		data = json.loads(doc.taxjar_breakdown_json)
		self.assertEqual(data["currency"], "USD")
		self.assertNotIn("usd", data)

	def test_non_usd_doc_stores_both(self):
		import json
		tax_data = _make_us_breakdown()
		doc = _make_doc(currency="EUR")
		_store_breakdown_data(tax_data, doc, usd_rate=1.1)

		data = json.loads(doc.taxjar_breakdown_json)
		self.assertEqual(data["currency"], "EUR")
		self.assertEqual(data["base_currency"], "USD")
		self.assertAlmostEqual(data["exchange_rate"], 1.1)
		self.assertIn("usd", data)
		self.assertIn("transaction", data["usd"])
		self.assertIn("totals", data["usd"])

	def test_non_usd_doc_converted_amounts_differ(self):
		import json
		tax_data = _make_us_breakdown()
		doc = _make_doc(currency="EUR")
		_store_breakdown_data(tax_data, doc, usd_rate=1.1)

		data = json.loads(doc.taxjar_breakdown_json)
		usd_total = data["usd"]["totals"]["amount_to_collect"]
		converted_total = data["totals"]["amount_to_collect"]
		self.assertAlmostEqual(usd_total, 9.75)
		self.assertAlmostEqual(converted_total, 9.75 / 1.1, places=2)

	def test_non_usd_stores_exchange_date(self):
		import json
		tax_data = _make_us_breakdown()
		doc = _make_doc(currency="EUR")
		_store_breakdown_data(tax_data, doc, usd_rate=1.1)

		data = json.loads(doc.taxjar_breakdown_json)
		self.assertEqual(data["exchange_date"], "2025-06-01")


# ── TaxJar Transparency Tab — New helpers ──────────────────────────────────


class TestSetTaxStatusFields(UnitTestCase):

	def test_sets_nexus_fields(self):
		doc = _make_doc()
		_set_tax_status_fields(doc, has_nexus=True, nexus_reason="Nexus in CA")
		self.assertEqual(doc.taxjar_has_nexus, 1)
		self.assertEqual(doc.taxjar_nexus_reason, "Nexus in CA")

	def test_sets_customer_fields(self):
		doc = _make_doc()
		_set_tax_status_fields(doc, customer_taxable=False, customer_reason="Customer is exempt (Wholesale)")
		self.assertEqual(doc.taxjar_customer_taxable, 0)
		self.assertEqual(doc.taxjar_customer_taxable_reason, "Customer is exempt (Wholesale)")

	def test_sets_product_fields(self):
		doc = _make_doc()
		_set_tax_status_fields(doc, product_taxable="Partially", product_reason="2 of 3 items taxable")
		self.assertEqual(doc.taxjar_product_taxable, "Partially")
		self.assertEqual(doc.taxjar_product_taxable_reason, "2 of 3 items taxable")

	def test_sets_address_fields(self):
		doc = _make_doc()
		_set_tax_status_fields(doc, ship_from="Austin, TX 78701", ship_to="New York, NY 10001")
		self.assertEqual(doc.taxjar_ship_from, "Austin, TX 78701")
		self.assertEqual(doc.taxjar_ship_to, "New York, NY 10001")

	def test_sets_tax_source(self):
		doc = _make_doc()
		_set_tax_status_fields(doc, tax_source="origin")
		self.assertEqual(doc.taxjar_tax_source, "origin")

	def test_sets_freight_taxable_true(self):
		doc = _make_doc()
		_set_tax_status_fields(doc, freight_taxable=True)
		self.assertEqual(doc.taxjar_freight_taxable, 1)

	def test_sets_freight_taxable_false_not_skipped(self):
		"""False is a real, meaningful value here (not "unset") - it must still
		be written, not treated the same as omitting the argument."""
		doc = _make_doc()
		doc.taxjar_freight_taxable = 1
		_set_tax_status_fields(doc, freight_taxable=False)
		self.assertEqual(doc.taxjar_freight_taxable, 0)

	def test_skips_none_values(self):
		doc = _make_doc()
		doc.taxjar_nexus_reason = "Old reason"
		_set_tax_status_fields(doc, has_nexus=True)
		self.assertEqual(doc.taxjar_nexus_reason, "Old reason")

	def test_skips_missing_fields(self):
		doc = MagicMock(spec=[])
		_set_tax_status_fields(doc, has_nexus=True, nexus_reason="test")


class TestFormatAddressShort(UnitTestCase):

	def test_full_address(self):
		tax_dict = {"from_city": "Austin", "from_state": "TX", "from_zip": "78701"}
		self.assertEqual(_format_address_short(tax_dict, "from"), "Austin, TX 78701")

	def test_missing_zip(self):
		tax_dict = {"to_city": "Austin", "to_state": "TX", "to_zip": ""}
		self.assertEqual(_format_address_short(tax_dict, "to"), "Austin, TX")

	def test_missing_city(self):
		tax_dict = {"from_city": "", "from_state": "CA", "from_zip": "94105"}
		self.assertEqual(_format_address_short(tax_dict, "from"), "CA 94105")

	def test_empty_dict(self):
		self.assertEqual(_format_address_short({}, "from"), "")


class TestComputeProductTaxable(UnitTestCase):

	def _make_tax_data(self, line_items):
		"""line_items: list of (id, taxable_amount)."""
		tax_data = MagicMock()
		tax_data.breakdown.line_items = [
			MagicMock(id=line_id, taxable_amount=taxable_amount)
			for line_id, taxable_amount in line_items
		]
		return tax_data

	def test_all_taxable(self):
		doc = _make_doc()
		doc.items = [_FakeItem(idx=1, net_amount=100.0), _FakeItem(idx=2, net_amount=50.0)]
		tax_data = self._make_tax_data([(1, 100.0), (2, 50.0)])
		status, reason = _compute_product_taxable(doc, tax_data)
		self.assertEqual(status, "Yes")
		self.assertIn("2 of 2", reason)

	def test_all_exempt(self):
		"""A line TaxJar returned taxable_amount 0 for - the item is genuinely
		exempt (e.g. a product tax code TaxJar zero-rates), not merely taxed at
		a 0% local rate - is reported "No", not "Yes"."""
		doc = _make_doc()
		doc.items = [_FakeItem(idx=1, net_amount=100.0), _FakeItem(idx=2, net_amount=50.0)]
		tax_data = self._make_tax_data([(1, 0.0), (2, 0.0)])
		status, reason = _compute_product_taxable(doc, tax_data)
		self.assertEqual(status, "No")
		self.assertIn("0 of 2", reason)

	def test_partially_taxable(self):
		doc = _make_doc()
		doc.items = [_FakeItem(idx=1, net_amount=100.0), _FakeItem(idx=2, net_amount=50.0)]
		tax_data = self._make_tax_data([(1, 100.0), (2, 0.0)])
		status, reason = _compute_product_taxable(doc, tax_data)
		self.assertEqual(status, "Partially")
		self.assertIn("1 of 2", reason)

	def test_no_items(self):
		doc = _make_doc()
		doc.items = []
		tax_data = self._make_tax_data([])
		status, reason = _compute_product_taxable(doc, tax_data)
		self.assertEqual(status, "")

	def test_missing_breakdown_line_counts_as_taxable(self):
		"""No matching breakdown line for an item (e.g. tax_data is None,
		as on the exempt-customer/no-nexus path) falls back to the item's
		own net_amount, i.e. fully taxable - preserving the old default."""
		doc = _make_doc()
		doc.items = [_FakeItem(idx=1, net_amount=0.0)]
		status, reason = _compute_product_taxable(doc, None)
		self.assertEqual(status, "Yes")

	def test_no_usd_rate_uses_taxable_amount_directly(self):
		doc = _make_doc()
		doc.items = [_FakeItem(idx=1, net_amount=100.0)]
		tax_data = self._make_tax_data([(1, 100.0)])
		status, reason = _compute_product_taxable(doc, tax_data, usd_rate=None)
		self.assertEqual(status, "Yes")

	def test_usd_rate_converts_taxable_amount_back_to_doc_currency(self):
		"""taxable_amount comes back from TaxJar in USD; dividing by usd_rate
		mirrors how tax_collectable is converted back to doc currency."""
		doc = _make_doc()
		doc.items = [_FakeItem(idx=1, net_amount=100.0)]
		tax_data = self._make_tax_data([(1, 200.0)])
		status, reason = _compute_product_taxable(doc, tax_data, usd_rate=2.0)
		self.assertEqual(status, "Yes")


class TestCheckForNexusStatusFields(UnitTestCase):

	def test_no_nexus_sets_status_fields(self):
		config = MagicMock(tax_account_head="Sales Tax - TC")
		doc = _make_doc()
		tax_dict = {"to_state": "DC", "from_city": "Austin", "from_state": "TX", "from_zip": "78701",
		            "to_city": "Washington", "to_zip": "20001"}
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value(None)), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=config):
			result = check_for_nexus(doc, tax_dict)
		self.assertFalse(result)
		self.assertEqual(doc.taxjar_has_nexus, 0)
		self.assertIn("DC", doc.taxjar_nexus_reason)
		self.assertEqual(doc.taxjar_ship_from, "Austin, TX 78701")
		self.assertIn("Washington", doc.taxjar_ship_to)

	def test_no_nexus_does_not_write_breakdown_json(self):
		config = MagicMock(tax_account_head="Sales Tax - TC")
		doc = _make_doc()
		tax_dict = {"to_state": "DC"}
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value(None)), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=config):
			check_for_nexus(doc, tax_dict)
		self.assertIsNone(doc.taxjar_breakdown_json)

	def test_in_nexus_returns_true(self):
		doc = _make_doc()
		tax_dict = {"to_state": "CA"}
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value", side_effect=_scalar_get_value("NX-1")), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.get_company_config", return_value=MagicMock()):
			self.assertTrue(check_for_nexus(doc, tax_dict))


class TestExemptionReasonInTuple(UnitTestCase):

	def test_customer_exempt_with_type(self):
		doc = _make_doc()
		doc.exempt_from_sales_tax = 0
		config = MagicMock(tax_account_head="Sales Tax - TC")
		with patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.has_column", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.taxjar_integration.frappe.db.get_value",
		           side_effect=_scalar_get_value({"exempt_from_sales_tax": 1, "taxjar_exemption_type": "Wholesale"})):
			is_exempt, reason = check_sales_tax_exemption(doc, config)
		self.assertTrue(is_exempt)
		self.assertIn("Wholesale", reason)

	def test_doc_exempt_reason(self):
		doc = _make_doc()
		doc.exempt_from_sales_tax = 1
		config = MagicMock(tax_account_head="Sales Tax - TC")
		is_exempt, reason = check_sales_tax_exemption(doc, config)
		self.assertTrue(is_exempt)
		self.assertIn("Document", reason)


# ── Phase 1: Guided Setup page (get_setup_state / finish_setup) ───────────────

_SETUP_MODULE = "taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup"


class TestGuidedSetupState(UnitTestCase):
	def _settings(self):
		s = MagicMock()
		s.api_mode = "Sandbox"
		s.enable_taxjar_logging = 0
		s.log_retention_days = 90
		s.setup_complete = 0
		s.company_config = [frappe._dict(
			company="Frappe Tech", tax_account_head="Sales Tax - FT",
			shipping_account_head="Freight - FT",
			taxjar_calculate_tax=1, taxjar_create_transactions=0,
		)]
		s.table_hvjw = [frappe._dict(
			company="Frappe Tech", name="cred-1", sandbox_token="enc", live_token="",
		)]
		s.nexus = [frappe._dict(
			company="Frappe Tech", region="California", region_code="CA",
			country="United States", country_code="US",
		)]
		return s

	def test_state_shape_and_token_masking(self):
		"""companies (company_config) carries accounts + flags; credentials
		(table_hvjw) carries the masked token — two separate lists, since only
		the latter can exist before a company's accounts are known."""
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import get_setup_state
		s = self._settings()
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s), \
		     patch(_SETUP_MODULE + ".get_decrypted_password", return_value="tok-abcd1234"):
			state = get_setup_state()

		self.assertEqual(state["api_mode"], "Sandbox")
		self.assertNotIn("taxjar_enabled", state)  # managed on the doctype, not by this wizard
		self.assertFalse(state["setup_complete"])

		co = state["companies"][0]
		self.assertEqual(co["company"], "Frappe Tech")
		self.assertTrue(co["calculate"])
		self.assertFalse(co["file"])
		self.assertNotIn("token_last4", co)

		cred = state["credentials"][0]
		self.assertEqual(cred["company"], "Frappe Tech")
		# Only the last 4 chars are ever exposed — never the full token.
		self.assertEqual(cred["token_last4"], "1234")
		self.assertEqual(len(state["nexus_by_company"]["Frappe Tech"]), 1)

	def test_reads_sandbox_token_in_sandbox_mode(self):
		"""In Live mode the live_token is read; sandbox mode reads sandbox_token."""
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import get_setup_state
		s = self._settings()
		s.api_mode = "Live"
		s.table_hvjw = [frappe._dict(company="Frappe Tech", name="cred-1",
			sandbox_token="", live_token="enc")]
		captured = {}
		def fake_decrypt(dt, name, field, raise_exception=False):
			captured["field"] = field
			return "live-wxyz5678"
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s), \
		     patch(_SETUP_MODULE + ".get_decrypted_password", side_effect=fake_decrypt):
			state = get_setup_state()
		self.assertEqual(captured["field"], "live_token")
		self.assertEqual(state["credentials"][0]["token_last4"], "5678")

	def test_token_last4_none_when_no_token(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import get_setup_state
		s = self._settings()
		s.table_hvjw = [frappe._dict(company="Frappe Tech", name="cred-1", sandbox_token="", live_token="")]
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s):
			state = get_setup_state()
		self.assertIsNone(state["credentials"][0]["token_last4"])

	def test_credentials_list_independent_of_company_config(self):
		"""A company can appear in credentials before it has a company_config row."""
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import get_setup_state
		s = self._settings()
		s.company_config = []
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s), \
		     patch(_SETUP_MODULE + ".get_decrypted_password", return_value="tok-abcd1234"):
			state = get_setup_state()
		self.assertEqual(state["companies"], [])
		self.assertEqual(state["credentials"][0]["company"], "Frappe Tech")

	def test_requires_read_permission(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import get_setup_state
		with patch(_SETUP_MODULE + ".frappe.has_permission", side_effect=frappe.PermissionError):
			self.assertRaises(frappe.PermissionError, get_setup_state)

	def test_blank_api_mode_falls_back_to_live_not_sandbox(self):
		"""Matches the doctype's own new default (see TestTaxJarSettingsJsonNexusTab.
		test_fresh_install_defaults) - this fallback only bites if api_mode is ever
		explicitly blank rather than genuinely unset."""
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import get_setup_state
		s = self._settings()
		s.api_mode = ""
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s):
			state = get_setup_state()
		self.assertEqual(state["api_mode"], "Live")

	def test_unconfigured_shows_fresh_defaults_over_stale_saved_values(self):
		"""Regression guard: a DocType JSON "default" only ever applies the
		very first time a Single doctype field is ever saved - it does NOT
		retroactively re-apply once a value has been stored, even an old
		default from before this one changed (e.g. log_retention_days=5,
		leftover from before the default became 15). No credentials and no
		company config is this wizard's own signal to show the current
		recommended defaults regardless of what stale value is stored."""
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import get_setup_state
		s = self._settings()
		s.api_mode = "Sandbox"
		s.enable_taxjar_logging = 0
		s.log_retention_days = 5
		s.table_hvjw = []
		s.company_config = []
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s):
			state = get_setup_state()
		self.assertEqual(state["api_mode"], "Live")
		self.assertTrue(state["enable_taxjar_logging"])
		self.assertEqual(state["log_retention_days"], 15)

	def test_configured_site_keeps_its_stored_values(self):
		"""Once either credentials or company config exist, stored values -
		even ones that differ from the recommended defaults - are respected,
		not silently overridden."""
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import get_setup_state
		s = self._settings()
		s.api_mode = "Sandbox"
		s.enable_taxjar_logging = 0
		s.log_retention_days = 5
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s):
			state = get_setup_state()
		self.assertEqual(state["api_mode"], "Sandbox")
		self.assertFalse(state["enable_taxjar_logging"])
		self.assertEqual(state["log_retention_days"], 5)


# ── Phase 2: test_connection ───────────────────────────────────────────────


class TestGuidedSetupTestConnection(UnitTestCase):
	def _settings(self, mode="Sandbox", creds=None):
		s = MagicMock()
		s.api_mode = mode
		s.table_hvjw = creds or []
		return s

	def test_ok_with_explicit_token_does_not_persist(self):
		"""An explicit token is validated live, transiently — never written to
		table_hvjw or saved, so a bad token typed while testing never lands in
		the database."""
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import test_connection
		s = self._settings()
		mock_client = MagicMock()
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s), \
		     patch(_SETUP_MODULE + ".taxjar.Client", return_value=mock_client):
			res = test_connection(company="Frappe Tech", token="tok-123", mode="Sandbox")

		self.assertTrue(res["ok"])
		mock_client.categories.assert_called_once()
		s.save.assert_not_called()
		self.assertEqual(len(s.table_hvjw), 0)

	def test_falls_back_to_saved_token_when_none_given(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import test_connection
		cred = frappe._dict(company="Frappe Tech", name="cred-1", sandbox_token="enc", live_token="")
		s = self._settings(creds=[cred])
		mock_client = MagicMock()
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s), \
		     patch(_SETUP_MODULE + ".get_decrypted_password", return_value="saved-token"), \
		     patch(_SETUP_MODULE + ".taxjar.Client", return_value=mock_client):
			res = test_connection(company="Frappe Tech")

		self.assertTrue(res["ok"])

	def test_no_token_available_returns_not_ok_without_calling_taxjar(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import test_connection
		s = self._settings()
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s), \
		     patch(_SETUP_MODULE + ".taxjar.Client") as mock_client_cls:
			res = test_connection(company="Frappe Tech")

		self.assertFalse(res["ok"])
		mock_client_cls.assert_not_called()

	def test_blank_mode_and_blank_settings_falls_back_to_live_token_field(self):
		"""No explicit mode param, no saved api_mode - defaults to Live, so a
		saved live_token (not sandbox_token) is what gets read."""
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import test_connection
		cred = frappe._dict(company="Frappe Tech", name="cred-1", sandbox_token="", live_token="enc")
		s = self._settings(mode="", creds=[cred])
		mock_client = MagicMock()
		captured = {}

		def fake_decrypt(dt, name, field, raise_exception=False):
			captured["field"] = field
			return "live-token-value"

		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s), \
		     patch(_SETUP_MODULE + ".get_decrypted_password", side_effect=fake_decrypt), \
		     patch(_SETUP_MODULE + ".taxjar.Client", return_value=mock_client):
			res = test_connection(company="Frappe Tech")

		self.assertTrue(res["ok"])
		self.assertEqual(res["mode"], "Live")
		self.assertEqual(captured["field"], "live_token")

	def test_401_returns_invalid_token_message(self):
		import taxjar.exceptions
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import test_connection
		s = self._settings()
		mock_client = MagicMock()
		err = taxjar.exceptions.TaxJarResponseError(MagicMock())
		err.full_response = {"status_code": 401}
		mock_client.categories.side_effect = err
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s), \
		     patch(_SETUP_MODULE + ".taxjar.Client", return_value=mock_client):
			res = test_connection(company="Frappe Tech", token="bad-token")

		self.assertFalse(res["ok"])
		self.assertIn("Invalid token", res["message"])

	def test_connection_error_returns_not_ok(self):
		import taxjar.exceptions
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import test_connection
		s = self._settings()
		mock_client = MagicMock()
		mock_client.categories.side_effect = taxjar.exceptions.TaxJarConnectionError("timeout")
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s), \
		     patch(_SETUP_MODULE + ".taxjar.Client", return_value=mock_client):
			res = test_connection(company="Frappe Tech", token="tok-123")

		self.assertFalse(res["ok"])

	def test_requires_write_permission(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import test_connection
		with patch(_SETUP_MODULE + ".frappe.has_permission", side_effect=frappe.PermissionError):
			self.assertRaises(frappe.PermissionError, test_connection, company="Frappe Tech", token="x")


# ── Phase 2: save_connection ────────────────────────────────────────────────


class TestGuidedSetupSaveConnection(UnitTestCase):
	def test_sets_mode_and_creates_new_credential(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import save_connection
		s = MagicMock()
		s.table_hvjw = []
		appended = MagicMock(company=None)
		s.append.return_value = appended
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s):
			res = save_connection(mode="Sandbox", credentials=[{"company": "Frappe Tech", "token": "tok-1"}])

		self.assertTrue(res["ok"])
		self.assertEqual(s.api_mode, "Sandbox")
		s.append.assert_called_once_with("table_hvjw", {"company": "Frappe Tech"})
		appended.set.assert_called_once_with("sandbox_token", "tok-1")
		s.save.assert_called_once()

	def test_updates_existing_credential_without_duplicating_row(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import save_connection
		cred = MagicMock(company="Frappe Tech")
		s = MagicMock()
		s.table_hvjw = [cred]
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s):
			save_connection(mode="Live", credentials=[{"company": "Frappe Tech", "token": "new-tok"}])

		s.append.assert_not_called()
		cred.set.assert_called_once_with("live_token", "new-tok")

	def test_blank_token_keeps_existing_not_cleared(self):
		"""A blank token in the payload means the masked field wasn't retyped —
		it must not overwrite the stored token."""
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import save_connection
		cred = MagicMock(company="Frappe Tech")
		s = MagicMock()
		s.table_hvjw = [cred]
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s):
			save_connection(mode="Sandbox", credentials=[{"company": "Frappe Tech", "token": ""}])

		cred.set.assert_not_called()

	def test_requires_write_permission(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import save_connection
		with patch(_SETUP_MODULE + ".frappe.has_permission", side_effect=frappe.PermissionError):
			self.assertRaises(frappe.PermissionError, save_connection, mode="Sandbox", credentials=[])


# ── Phase 2: save_company_accounts ──────────────────────────────────────────


class TestGuidedSetupSaveCompanyAccounts(UnitTestCase):
	def test_creates_new_company_config_row(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import save_company_accounts
		s = MagicMock()
		s.company_config = []
		appended = frappe._dict(company=None, tax_account_head=None, shipping_account_head=None)
		s.append.return_value = appended
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s):
			res = save_company_accounts(rows=[{
				"company": "Frappe Tech",
				"tax_account_head": "Sales Tax - FT",
				"shipping_account_head": "Freight - FT",
			}])

		self.assertTrue(res["ok"])
		s.append.assert_called_once_with("company_config", {"company": "Frappe Tech"})
		self.assertEqual(appended.tax_account_head, "Sales Tax - FT")
		self.assertEqual(appended.shipping_account_head, "Freight - FT")
		s.save.assert_called_once()

	def test_updates_existing_row_without_duplicating(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import save_company_accounts
		cfg = frappe._dict(company="Frappe Tech", tax_account_head="Old", shipping_account_head="Old")
		s = MagicMock()
		s.company_config = [cfg]
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s):
			save_company_accounts(rows=[{
				"company": "Frappe Tech",
				"tax_account_head": "New Tax",
				"shipping_account_head": "New Freight",
			}])

		s.append.assert_not_called()
		self.assertEqual(cfg.tax_account_head, "New Tax")
		self.assertEqual(cfg.shipping_account_head, "New Freight")

	def test_requires_write_permission(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import save_company_accounts
		with patch(_SETUP_MODULE + ".frappe.has_permission", side_effect=frappe.PermissionError):
			self.assertRaises(frappe.PermissionError, save_company_accounts, rows=[])


# ── Phase 2: save_features ──────────────────────────────────────────────────


class TestGuidedSetupSaveFeatures(UnitTestCase):
	def test_parameter_is_not_named_flags_or_ignore_permissions(self):
		"""Regression guard: frappe.call() - used by every real /api/method/...
		request, unlike bench execute or calling the function directly in
		Python - unconditionally strips any kwarg literally named "flags" or
		"ignore_permissions" via frappe.get_newargs() before dispatch, as a
		security measure, regardless of whether the target function declares
		that parameter. A whitelisted method using either name as its own
		parameter silently receives None over real HTTP/JS calls while
		appearing to work when tested via bench execute or direct calls in a
		unit test - exactly the trap this function fell into."""
		import inspect
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import save_features
		params = set(inspect.signature(save_features).parameters)
		self.assertNotIn("flags", params)
		self.assertNotIn("ignore_permissions", params)

	def test_sets_per_company_flags(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import save_features
		cfg = frappe._dict(company="Frappe Tech", taxjar_calculate_tax=0, taxjar_create_transactions=0)
		s = MagicMock()
		s.company_config = [cfg]
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s):
			res = save_features(company_flags=[{"company": "Frappe Tech", "calculate": 1, "file": 0}])

		self.assertTrue(res["ok"])
		self.assertEqual(cfg.taxjar_calculate_tax, 1)
		self.assertEqual(cfg.taxjar_create_transactions, 0)
		s.save.assert_called_once()

	def test_enabling_calculate_auto_enables_master_switch(self):
		"""Per-company flags do nothing while taxjar_enabled is off (see
		_is_taxjar_enabled), which reads as "the toggle didn't save" even though the
		child row was written correctly — flip the master switch the moment any
		company ends up with a feature on."""
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import save_features
		cfg = frappe._dict(company="Frappe Tech", taxjar_calculate_tax=0, taxjar_create_transactions=0)
		s = MagicMock()
		s.company_config = [cfg]
		s.taxjar_enabled = 0
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s):
			save_features(company_flags=[{"company": "Frappe Tech", "calculate": 1, "file": 0}])

		self.assertEqual(s.taxjar_enabled, 1)

	def test_enabling_file_alone_also_auto_enables_master_switch(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import save_features
		cfg = frappe._dict(company="Frappe Tech", taxjar_calculate_tax=0, taxjar_create_transactions=0)
		s = MagicMock()
		s.company_config = [cfg]
		s.taxjar_enabled = 0
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s):
			save_features(company_flags=[{"company": "Frappe Tech", "calculate": 0, "file": 1}])

		self.assertEqual(s.taxjar_enabled, 1)

	def test_disabling_all_flags_does_not_disable_master_switch(self):
		"""Turning individual company flags off does not imply the user wants
		TaxJar off everywhere - that stays a deliberate action on the form."""
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import save_features
		cfg = frappe._dict(company="Frappe Tech", taxjar_calculate_tax=1, taxjar_create_transactions=1)
		s = MagicMock()
		s.company_config = [cfg]
		s.taxjar_enabled = 1
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s):
			save_features(company_flags=[{"company": "Frappe Tech", "calculate": 0, "file": 0}])

		self.assertEqual(s.taxjar_enabled, 1)

	def test_skips_flags_for_company_without_existing_config_row(self):
		"""A company with credentials but no accounts yet (Accounts step not run)
		has no company_config row to flip flags on — must not throw or fabricate one."""
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import save_features
		s = MagicMock()
		s.company_config = []
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s):
			save_features(company_flags=[{"company": "No Config Co", "calculate": 1, "file": 0}])

		s.append.assert_not_called()

	def test_requires_write_permission(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import save_features
		with patch(_SETUP_MODULE + ".frappe.has_permission", side_effect=frappe.PermissionError):
			self.assertRaises(frappe.PermissionError, save_features, company_flags=[])


# ── Phase 2: remove_company ─────────────────────────────────────────────────


class TestGuidedSetupRemoveCompany(UnitTestCase):
	def test_removes_credential_and_company_config_row(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import remove_company
		s = MagicMock()
		s.table_hvjw = [frappe._dict(company="Frappe Tech"), frappe._dict(company="Other Co")]
		s.company_config = [frappe._dict(company="Frappe Tech"), frappe._dict(company="Other Co")]
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s):
			res = remove_company(company="Frappe Tech")

		self.assertTrue(res["ok"])
		set_calls = {c.args[0]: c.args[1] for c in s.set.call_args_list}
		self.assertEqual([r.company for r in set_calls["table_hvjw"]], ["Other Co"])
		self.assertEqual([r.company for r in set_calls["company_config"]], ["Other Co"])
		s.save.assert_called_once()

	def test_leaves_other_companies_untouched_when_no_match(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import remove_company
		s = MagicMock()
		s.table_hvjw = [frappe._dict(company="Other Co")]
		s.company_config = []
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s):
			remove_company(company="Frappe Tech")

		set_calls = {c.args[0]: c.args[1] for c in s.set.call_args_list}
		self.assertEqual([r.company for r in set_calls["table_hvjw"]], ["Other Co"])

	def test_requires_write_permission(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import remove_company
		with patch(_SETUP_MODULE + ".frappe.has_permission", side_effect=frappe.PermissionError):
			self.assertRaises(frappe.PermissionError, remove_company, company="Frappe Tech")


# ── Phase 2: fetch_nexus ─────────────────────────────────────────────────────


class TestGuidedSetupFetchNexus(UnitTestCase):
	def test_calls_update_nexus_list_and_returns_grouped_nexus(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import fetch_nexus
		s = MagicMock()
		s.company_config = [frappe._dict(company="Frappe Tech")]
		s.nexus = [frappe._dict(company="Frappe Tech", region="California", region_code="CA",
			country="United States", country_code="US")]
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s):
			res = fetch_nexus()

		self.assertTrue(res["ok"])
		s.update_nexus_list.assert_called_once()
		self.assertEqual(len(res["nexus_by_company"]["Frappe Tech"]), 1)

	def test_throws_when_no_company_config(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import fetch_nexus
		s = MagicMock()
		s.company_config = []
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=s):
			self.assertRaises(frappe.ValidationError, fetch_nexus)
		s.update_nexus_list.assert_not_called()

	def test_requires_write_permission(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import fetch_nexus
		with patch(_SETUP_MODULE + ".frappe.has_permission", side_effect=frappe.PermissionError):
			self.assertRaises(frappe.PermissionError, fetch_nexus)


class TestGuidedSetupFinish(UnitTestCase):
	def test_finish_sets_complete_and_saves(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import finish_setup
		doc = MagicMock()
		with patch(_SETUP_MODULE + ".frappe.has_permission"), \
		     patch(_SETUP_MODULE + ".frappe.get_single", return_value=doc):
			res = finish_setup()
		self.assertEqual(doc.setup_complete, 1)
		doc.save.assert_called_once()
		self.assertTrue(res["ok"])

	def test_finish_requires_write_permission(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import finish_setup
		with patch(_SETUP_MODULE + ".frappe.has_permission", side_effect=frappe.PermissionError):
			self.assertRaises(frappe.PermissionError, finish_setup)


class TestGuidedSetupSchemaAndEntry(UnitTestCase):
	def test_setup_complete_field_exists(self):
		field = frappe.get_meta("TaxJar Settings").get_field("setup_complete")
		self.assertIsNotNone(field)
		self.assertEqual(field.fieldtype, "Check")

	def test_page_json_declares_roles(self):
		import json, os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "page", "taxjar_setup", "taxjar_setup.json"))
		data = json.load(open(path))
		self.assertEqual(data.get("standard"), "Yes")
		roles = {r["role"] for r in data.get("roles", [])}
		self.assertIn("System Manager", roles)
		self.assertIn("Accounts Manager", roles)

	def test_settings_js_has_setup_intro(self):
		import os
		js = open(os.path.join(os.path.dirname(__file__), "taxjar_settings.js")).read()
		self.assertIn("set_intro", js)
		self.assertIn("/app/taxjar-setup", js)

	def test_setup_page_js_wires_steps_and_apis(self):
		import os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "page", "taxjar_setup", "taxjar_setup.js"))
		js = open(path).read()
		self.assertIn("get_setup_state", js)
		self.assertIn("finish_setup", js)
		for key in ("welcome", "connect", "accounts", "features", "nexus", "review"):
			self.assertIn(key, js)


# ── Phase 2: guided setup JS — native controls per step ─────────────────────


class TestGuidedSetupPhase2JS(UnitTestCase):
	"""String/structure assertions on the page JS — the same pattern used for
	other pages in this app, since there's no JS runtime in the Python test
	suite. Confirms the documented native-control plan (docs/guided-setup-
	plan.md §3/§7) is actually wired, not just described."""

	def _js(self):
		import os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "page", "taxjar_setup", "taxjar_setup.js"))
		return open(path).read()

	def _setup_css(self):
		import os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "page", "taxjar_setup", "taxjar_setup.css"))
		return open(path).read()

	def test_calls_all_five_phase2_apis(self):
		js = self._js()
		for method in ("test_connection", "save_connection", "save_company_accounts",
		               "save_features", "fetch_nexus"):
			self.assertIn(method, js)

	def test_save_features_payload_key_is_not_flags(self):
		"""Regression guard for the save_features(flags=...) trap (see
		test_parameter_is_not_named_flags_or_ignore_permissions): the payload
		key sent to the server must match the server's actual parameter name,
		company_flags - "flags" is silently stripped by frappe.call() on every
		real request, so this has to stay in lockstep on both ends."""
		js = self._js()
		save_features_call = js.split('_save_features()')[1].split("\n\t}")[0]
		self.assertIn("company_flags", save_features_call)
		self.assertIn('this._call("save_features", { company_flags })', save_features_call)

	def test_connect_step_uses_native_link_password_controls(self):
		"""API Mode moved off a native Select onto a hand-built segmented
		toggle (see test_connect_mode_is_a_segmented_toggle) - Company/token
		stay real frappe controls."""
		js = self._js()
		self.assertIn('fieldtype: "Link", fieldname: "company"', js)
		self.assertIn('fieldtype: "Password", fieldname: "token"', js)
		# Continue is gated on at least one successful test, not just field presence.
		self.assertIn("_sync_connect_gate", js)
		self.assertIn("tested", js)

	def test_connect_step_has_api_log_toggle_and_retention(self):
		"""The Connect step previously had no way to enable/disable API Logs,
		even though save_connection/get_setup_state already supported
		enable_taxjar_logging and log_retention_days end to end. "Switch" (a
		real pill toggle shipped in frappe core, controls/switch.js), not
		"Check" - a hand-rolled CSS checkbox-as-switch rendered as a broken
		grey ring in practice."""
		js = self._js()
		self.assertIn('fieldtype: "Switch", fieldname: "enable_taxjar_logging"', js)
		self.assertIn('fieldtype: "Int", fieldname: "log_retention_days"', js)
		# Retention only means anything once logging is on.
		self.assertIn("syncRetentionVisibility", js)

	def test_retention_field_visible_on_initial_load_when_logging_already_on(self):
		"""enableLogging.set_value() resolves asynchronously (frappe.run_serially),
		so calling syncRetentionVisibility() (which reads get_value()) right after
		it could still see the pre-set value - the retention field only ever
		appeared on a real toggle (a genuine click, synchronous), never on initial
		load with logging already enabled from a previous session. The initial
		visibility must be driven by the already-known state value instead."""
		js = self._js()
		render_connect = js.split("_render_connect() {")[1].split("\n\t_add_credential_card")[0]
		self.assertIn("$retentionField.toggle(!!s.enable_taxjar_logging);", render_connect)
		# The initial toggle must not be the same call used for later, real
		# toggle events - that call is fine to read get_value() from since it's
		# driven by a synchronous DOM change event.
		self.assertNotIn("syncRetentionVisibility();\n", render_connect)

	def test_save_connect_sends_logging_fields(self):
		js = self._js()
		save_connect = js.split("_save_connect() {")[1].split("\n\t}")[0]
		self.assertIn("enable_taxjar_logging", save_connect)
		self.assertIn("log_retention_days", save_connect)

	def test_review_shows_api_log_status(self):
		"""The Review step reports whether logging is on and for how long, and
		the retention figure pluralises - "1 days retention" is the bug this
		guards."""
		js = self._js()
		review = js.split("_render_review() {")[1].split("\n\t}\n")[0]
		self.assertIn('__("API Logs")', review)
		self.assertIn(
			'__("Enabled · {0} {1} retention", [retentionDays, retentionDays === 1 ? __("day") : __("days")])',
			review,
		)

	def test_gated_continue_stays_clickable_and_explains_itself(self):
		"""A native `disabled` button eats clicks silently — Connect's gate must
		use a CSS-only look-disabled state so a click can still explain what's
		missing, instead of appearing to do nothing."""
		js = self._js()
		self.assertIn("_set_next_gated", js)
		self.assertIn("this._nextGated", js)
		self.assertIn(
			'__("Test the connection for {0} (or remove it) before continuing.", [untested.company])', js
		)
		# _on_next() must check the gate before anything else, so a click while
		# gated always shows the message rather than silently trying to save.
		on_next = js.split("_on_next() {")[1].split("\n\t}\n")[0]
		self.assertIn("this._nextGated", on_next)
		self.assertIn("frappe.show_alert", on_next)

	def test_connect_gate_requires_every_company_tested_not_just_one(self):
		"""Regression guard for the actual bug report: gating on "at least one
		company tested" let an untested or failed credential ride along past
		Connect - invisible until the Nexus step later fetched nexus for every
		company in one request and hard-crashed with a raw 401 traceback the
		moment any one of them turned out to have a bad token. Every company
		with a name must test successfully now, and the gate message names the
		specific offending company with both ways out: fix its token and
		re-test, or remove it."""
		js = self._js()
		gate = js.split("_sync_connect_gate() {")[1].split("\n\t}\n")[0]
		self.assertIn("const withCompany = this._connectCards.filter((c) => c.company);", gate)
		self.assertIn("const untested = withCompany.find((c) => !c.tested);", gate)
		self.assertNotIn("c.controls.company.get_value()", gate)

	def test_connect_gate_reads_tracked_company_not_control_mid_flight(self):
		"""Regression guard: _sync_connect_gate() runs synchronously right after
		every card is added, including a restored card's companyControl.set_value()
		- which, like the mode label and retention-visibility bugs, resolves
		asynchronously. Reading company.get_value() (a read-only control at that
		point) right here could still see the pre-set value and wrongly gate
		Continue on an already-saved, already-tested credential. c.company (kept
		in sync directly on the entry, not re-derived from the control) must be
		used instead."""
		js = self._js()
		gate = js.split("_sync_connect_gate() {")[1].split("\n\t}\n")[0]
		self.assertIn("c.company", gate)
		self.assertNotIn("c.controls.company.get_value()", gate)

	def test_connect_button_is_not_a_plain_default(self):
		"""It is the action that actually matters before Continue unlocks, so
		it carries a variant of its own rather than falling back to the
		framework's default button styling."""
		js = self._js()
		fn = js.split("_render_cred_action(entry) {")[1].split("\n\t}\n")[0]
		idle = fn.rsplit("} else {", 1)[1]
		self.assertIn('label: __("Connect")', idle)
		self.assertIn('variant: "outline"', idle)

	def test_only_the_page_cta_is_a_solid_button(self):
		"""The filled treatment is reserved for "Continue". Connect and the
		Sandbox/Live segment used to wear ink too, which read as "this is the
		way forward" rather than "this is selected"; both are outline now, so
		exactly one control on the page is solid."""
		js = self._js()
		self.assertEqual(js.count('variant: "solid"'), 1)
		cta = js.split('.find(".ts-next-mount").append(')[1].split("}));")[0]
		self.assertIn('label: __("Continue")', cta)
		self.assertIn('variant: "solid"', cta)
		# and the two that used to compete with it are not.
		action = js.split("_render_cred_action(entry) {")[1].split("\n\t}\n")[0]
		self.assertNotIn('variant: "solid"', action)
		toggle = js.split("_render_mode_toggle($parent, initial) {")[1].split("\n\t}\n")[0]
		self.assertNotIn('variant: "solid"', toggle)

	def test_connect_excludes_already_added_companies_via_get_query(self):
		js = self._js()
		self.assertIn("otherCompanies", js)
		self.assertIn("not in", js)

	# ── Connect step redesign v4: API Mode alone, Enable API logs moved below
	# API Credentials as a toggle-switch row, credential rows top-aligned
	# (per latest user feedback, superseding v3's shared top-row/divider) ──

	def test_connect_mode_is_a_segmented_toggle_not_a_dropdown(self):
		"""Sandbox/Live is a binary choice, shown as a segmented toggle rather
		than hiding one option behind a closed <select>. Built on frappe's own
		tab_buttons component; _render_mode_toggle still wraps it in the
		get_value/set_value pair the rest of the file calls on
		this.controls.mode."""
		js = self._js()
		self.assertNotIn('fieldtype: "Select", fieldname: "api_mode"', js)
		toggle_fn = js.split("_render_mode_toggle($parent, initial) {")[1].split("\n\t}\n")[0]
		self.assertIn("frappe.ui.tab_buttons({", toggle_fn)
		self.assertIn('{ label: __("Sandbox"), value: "Sandbox" }', toggle_fn)
		self.assertIn('{ label: __("Live"), value: "Live" }', toggle_fn)
		self.assertIn("get_value: () => tabButtons.get_value()", toggle_fn)
		self.assertIn("set_value: (v) => tabButtons.set_value(v, { silent: true })", toggle_fn)
		# Changing the segment drives _on_mode_change() directly.
		self.assertIn("on_change: () => this._on_mode_change()", toggle_fn)
		# The note that used to sit under the label is gone, and so is the
		# info-icon tooltip that briefly replaced it.
		self.assertNotIn("Live requests affect real filings", js)
		self.assertNotIn("info-trigger", js)

	def test_connect_logs_card_sits_below_api_credentials(self):
		"""Enable API logs' position has moved a few times across rounds
		(shared row with API Mode -> below Credentials -> above Credentials)
		- settled below/after API Credentials, each card getting the same
		20px top margin for consistent spacing between all three cards."""
		js = self._js()
		render_connect = js.split("_render_connect() {")[1].split("\n\t\tthis.controls.mode")[0]
		self.assertLess(
			render_connect.index('class="ts-card-h ts-cred-heading"'),
			render_connect.index('class="ts-card ts-logtoggle"'),
		)
		self.assertIn('<div class="ts-card ts-logtoggle" style="margin-top:20px">', render_connect)

	def test_connect_logs_card_has_toggle_row_then_retention_row(self):
		"""One card, two rows divided by a border: the Switch control (its own
		native label+description, .ts-field-logging is its only content) on
		top, Retention (a plain label+description on the left, the day-count
		input on the right - the same label-left/control-right shape as
		.ts-mode-row) below it."""
		js = self._js()
		render_connect = js.split("_render_connect() {")[1].split("\n\t\tthis.controls.mode")[0]
		logtoggle = render_connect.split('<div class="ts-card ts-logtoggle"')[1].split("`);")[0]

		retention_row = logtoggle.split('<div class="ts-card-b ts-retention-row">')[1]
		self.assertIn('<label class="control-label">${__("Retention")}</label>', retention_row)
		# Rendered by syncRetentionCopy, not the template - it has no correct
		# static form (see the singular/plural test below).
		self.assertIn('<p class="ts-fieldnote ts-retention-note"></p>', retention_row)
		self.assertIn('class="ts-retention-wrap"', retention_row)

		self.assertLess(
			logtoggle.index('class="ts-field-logging"'),
			logtoggle.index('class="ts-card-b ts-retention-row"'),
		)

		logging_control = js.split("this.controls.enableLogging = frappe.ui.form.make_control({")[1].split("});")[0]
		self.assertIn('fieldtype: "Switch", fieldname: "enable_taxjar_logging"', logging_control)
		self.assertIn('label: __("Enable API Logs")', logging_control)
		# Names no doctype: the wizard is the only place this switch appears and
		# a reader here has no TaxJar API Log list to go and look at yet.
		self.assertIn(
			'description: __("Records API requests, responses, and errors.")', logging_control
		)

	def test_only_the_switch_track_is_clickable_not_the_whole_row(self):
		"""ControlSwitch puts label, description, checkbox and track inside one
		<label> "so clicking the text toggles the switch" (switch.js). Stretched
		across a full-width card row that hands most of the card - including the
		2rem gap of dead space in the middle - to a setting that writes on
		click. Pointer events off on the label, back on for the track alone.
		"""
		css = self._setup_css()
		label_rule = css.split(".taxjar-setup .ts-field-logging label.switch-control {")[1].split("}")[0]
		self.assertIn("pointer-events: none;", label_rule)
		track_rule = css.split(".taxjar-setup .ts-field-logging .switch-visual {")[1].split("}")[0]
		self.assertIn("pointer-events: auto;", track_rule)
		self.assertIn("cursor: pointer;", track_rule)
		# .input-area is sr-only clipped by frappe, so re-enabling pointer
		# events on it would hand back a 1px target, not a useful one.
		self.assertNotIn(".ts-field-logging .input-area {", css)

	def test_retention_label_and_note_share_one_rule_with_the_switch_control(self):
		"""Enable API logs is the only one of these settings that is a real
		control, so frappe sizes and colours its label/description
		(.switch-control's .label-area / .help-box). Retention is hand-authored
		and was rendering a step smaller and greyer directly beneath it.

		Guarded as a SHARED selector rather than as matching values on the
		hand-authored side: two independent declarations are what let them
		drift apart in the first place.
		"""
		css = self._setup_css()

		# Everything between the preceding comment and the switch's own
		# selector: the other selectors sharing this rule.
		label_selectors = css.split(".taxjar-setup .ts-field-logging .label-area {")[0].rsplit("*/", 1)[-1]
		self.assertIn(".taxjar-setup .ts-retention-row > div > label.control-label,", label_selectors)
		label_rule = css.split(".taxjar-setup .ts-field-logging .label-area {")[1].split("}")[0]
		self.assertIn("font-size: var(--text-base);", label_rule)
		self.assertIn("color: var(--ink-gray-7);", label_rule)

		note_selectors = css.split(".taxjar-setup .ts-field-logging .help-box {")[0].rsplit("}", 1)[-1]
		self.assertIn(".taxjar-setup .ts-retention-row .ts-fieldnote,", note_selectors)
		note_rule = css.split(".taxjar-setup .ts-field-logging .help-box {")[1].split("}")[0]
		self.assertIn("font-size: var(--text-sm);", note_rule)
		self.assertIn("color: var(--ink-gray-5);", note_rule)
		# Scoped to the retention row - .ts-fieldnote is also the standalone
		# note on the Accounts step, which is not paired with anything.
		self.assertNotIn(".taxjar-setup .ts-fieldnote,", note_rule)

	def test_rail_sits_above_the_divider_and_the_step_heading_below_it(self):
		"""The rail is page-level chrome (where am I in the wizard); the heading
		and description are the step's own content. Ordering them rail ->
		divider -> heading is what makes .ts-head's border read as the line
		between the two. The heading used to sit inside .ts-head above the rail,
		which put one step's title above a rail describing all six.

		.ts-title has to be a SIBLING of .ts-body, not its first child: every
		_render_*() replaces .ts-body's contents wholesale and would wipe it.
		"""
		js = self._js()
		shell = js.split("_build_shell() {")[1].split("`).appendTo(this.page.main);")[0]

		head = shell.split('<header class="ts-head">')[1].split("</header>")[0]
		self.assertIn("ts-rail", head)
		self.assertNotIn("ts-title", head)

		self.assertLess(shell.index("</header>"), shell.index('<h2 class="ts-title">'))
		self.assertLess(shell.index('<h2 class="ts-title">'), shell.index('<div class="ts-body">'))

	def test_descriptions_are_not_capped_below_the_panel_width(self):
		"""A 60ch measure on .ts-fieldnote broke every step's description onto a
		second line at roughly half the panel's width while the fields beneath
		it ran the full width - it read as a layout bug, not as a reading
		measure. .taxjar-setup's own 880px cap is the only thing setting line
		length now, so this has to stay off every text block on the page.
		"""
		css = self._setup_css()
		for selector in (
			".taxjar-setup .ts-fieldnote {",
			".taxjar-setup .ts-retention-row .ts-fieldnote,",
		):
			rule = css.split(selector)[1].split("}")[0]
			self.assertNotIn("max-width", rule, selector)

	def test_retention_unit_and_description_pluralise_from_one_function(self):
		"""Both the unit beside the input and the description under the label
		swing on the same singular/plural test. Written by one function so they
		cannot disagree - two listeners on the same input is exactly how a "1
		days" / "...older than specified day" mismatch appears.

		Each form is its own complete __() string rather than one sentence with
		the word interpolated: not every language frappe ships translations for
		pluralises by swapping a single word, and a translator handed
		"day"/"days" alone has no sentence to agree it with.
		"""
		js = self._js()
		fn = js.split("const syncRetentionCopy = (days) => {")[1].split("\n\t\t};")[0]
		self.assertIn("const one = cint(days) === 1;", fn)
		self.assertIn('$retentionUnit.text(one ? __("day") : __("days"));', fn)
		self.assertIn('__("Logs older than specified day are auto-purged.")', fn)
		self.assertIn('__("Logs older than specified days are auto-purged.")', fn)
		# No half-sentence strings that a translator can't agree a verb with.
		self.assertNotIn('__("Logs older than specified ")', js)

		# Seeded from the known state, not a synchronous get_value() - set_value
		# resolves through frappe.run_serially, so the first read would still
		# see the pre-set value (same class of bug as _modeIsLive).
		self.assertIn(
			"syncRetentionCopy(s.log_retention_days != null ? s.log_retention_days : 15);", js
		)
		# One listener feeding one function, not one per piece of copy.
		self.assertIn(
			"this.controls.logRetention.$input.on(\"input\", () => {\n"
			"\t\t\tsyncRetentionCopy(this.controls.logRetention.get_value());\n"
			"\t\t});",
			js,
		)
		self.assertNotIn("syncRetentionUnit", js)

	def test_connect_logs_toggle_uses_frappe_core_switch_control(self):
		"""fieldtype "Switch" (frappe.ui.form.ControlSwitch, controls/switch.js)
		is a real pill toggle already shipped and styled in frappe core
		(common/controls.scss's .switch-control/.switch-visual/.switch-thumb,
		already part of the desk CSS bundle - no extra CSS/import needed
		here) - not a hand-rolled CSS checkbox, which rendered as a broken
		grey ring in practice, and not frappe-ui's Vue Switch component
		either (confirmed not feasible from this plain, unbundled page
		script - frappe-ui isn't even installed in this bench, and Vue isn't
		exposed as a global here)."""
		js = self._js()
		self.assertNotIn('input[type="checkbox"]', js)
		self.assertNotIn("appearance: none", js)

		import os
		switch_path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "..", "..", "..", "frappe", "frappe",
			"public", "js", "frappe", "form", "controls", "switch.js"))
		self.assertTrue(os.path.isfile(switch_path), "frappe core's Switch control must exist for fieldtype: \"Switch\" to work")

		css = open(os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "page", "taxjar_setup", "taxjar_setup.css"))).read()
		self.assertNotIn('input[type="checkbox"]', css)

	def test_connect_retention_row_has_border_divider_and_hides_as_one_unit(self):
		""".ts-retention-row gets a border-top (the divider between the two
		rows), and syncRetentionVisibility toggles the whole row - hiding it
		wholesale rather than leaving "Retention / Older logs are deleted
		automatically" visible with no functioning input when logging is off."""
		import os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "page", "taxjar_setup", "taxjar_setup.css"))
		css = open(path).read()
		retention_row_rule = css.split(".taxjar-setup .ts-retention-row {")[1].split("}")[0]
		self.assertIn("border-top: 1px solid var(--border-color)", retention_row_rule)

		js = self._js()
		self.assertIn('const $retentionField = this.$body.find(".ts-retention-row");', js)

	def test_no_hover_only_affordances_remain(self):
		"""Whatever explains a failure has to work on touch as well as desktop.
		The click-driven info popover this used to guard is gone - the reason
		now lives on the token field itself - so what is left to assert is that
		nothing reintroduced a hover-only replacement."""
		css = self._setup_css()
		self.assertNotIn(":hover .ts-info-pop", css)
		self.assertNotIn(".ts-info-pop:hover", css)
		self.assertNotIn(".ts-info-btn", css)

	

	def test_connect_retention_default_is_fifteen_and_shows_pluralised_unit(self):
		"""Default is 15 days, and the "day"/"days" unit word is a separate
		visible element next to the input (not baked into the input itself),
		pluralised off the live value - just the bare unit word, not "day/days
		retention", since the row now has its own "Retention" label doing that
		job (saying it twice on one row read redundant)."""
		js = self._js()
		self.assertIn(
			"this.controls.logRetention.set_value(s.log_retention_days != null ? s.log_retention_days : 15);", js
		)
		self.assertIn("ts-retention-unit", js)
		# Pluralised inside syncRetentionCopy, which writes the description on
		# the same test - see
		# test_retention_unit_and_description_pluralise_from_one_function.
		self.assertIn('$retentionUnit.text(one ? __("day") : __("days"));', js)

		import os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "doctype", "taxjar_settings", "taxjar_settings.json"))
		import json
		with open(path) as f:
			meta = json.load(f)
		field = next(f for f in meta["fields"] if f["fieldname"] == "log_retention_days")
		self.assertEqual(field["default"], "15")

	def test_connect_credentials_section_is_one_collapsible_heading(self):
		"""Replaces the old per-company collapsible header with a single,
		generic "API Credentials" heading for the whole section - clicking it
		toggles every row at once, not one company at a time."""
		js = self._js()
		render_connect = js.split("_render_connect() {")[1].split("\n\t\tthis.controls.mode")[0]
		self.assertIn('class="ts-card-h ts-cred-heading"', render_connect)
		self.assertIn('__("API Credentials")', render_connect)
		self.assertIn("_set_creds_expanded", js)
		self.assertIn(
			'this.$body.find(".ts-cred-heading").on("click", () => this._set_creds_expanded(!this._credsExpanded));',
			js,
		)

	def test_connect_add_company_button_lives_below_the_rows(self):
		"""'Add another company' mounts into its own .ts-cred-add-row below the
		credential rows, not inside the clickable .ts-cred-heading - so it is
		only ever reachable while the section is already expanded, and its
		click needs no stopPropagation to avoid also toggling the collapse."""
		js = self._js()
		render_connect = js.split("_render_connect() {")[1].split("\n\t\tthis.controls.mode")[0]
		heading = render_connect.split('<div class="ts-card-h ts-cred-heading">')[1].split("</div>")[0]
		self.assertNotIn("ts-cred-add-row", heading)
		# Rows first, then the add row - both siblings inside the card.
		self.assertLess(
			render_connect.index("ts-cred-rows"), render_connect.index("ts-cred-add-row")
		)
		add_mount = js.split('.find(".ts-cred-add-row")')[1].split(";")[0]
		self.assertIn("frappe.ui.button", add_mount)
		self.assertNotIn("stopPropagation", add_mount)
		self.assertIn("this._add_credential_card({ company: null, token_last4: null })", js)

	def test_connect_credentials_section_starts_expanded(self):
		"""Required step - starting collapsed would just cost an extra click
		on every single visit."""
		js = self._js()
		self.assertIn("this._credsExpanded = true;", js)

	def test_connect_credential_rows_are_flat_with_dividers_not_accordion_cards(self):
		"""Each company is one plain .ts-cred-row (Company / Live token /
		action slot / remove), always fully visible once the section is
		expanded - not its own collapsible card."""
		js = self._js()
		add_card = js.split("_add_credential_card(cred) {")[1].split("\n\t_render_cred_action")[0]
		self.assertIn('<div class="ts-cred-row">', add_card)
		self.assertNotIn("ts-acc-row", add_card)
		self.assertNotIn("ts-acc-head", add_card)

		import os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "page", "taxjar_setup", "taxjar_setup.css"))
		css = open(path).read()
		row_rule = css.split(".taxjar-setup .ts-cred-row {")[1].split("}")[0]
		self.assertIn("align-items: flex-start", row_rule)
		self.assertIn(".ts-cred-row + .ts-cred-row { padding-top: 12px; border-top:", css)

	def test_connect_credential_row_labels_top_align_regardless_of_field_height(self):
		"""Regression guard: bottom-aligning the row (the previous approach)
		visibly staggered the Company/Live token labels whenever one field
		grew taller than the other (e.g. a per-field description) - reported
		as "alignment breaks after save". Top-aligning is what stays correct
		regardless of which field ends up taller. The tail (action slot +
		remove button) opts out via align-self: flex-end so it lines up with
		the bottom of the input boxes themselves (Company and Live token are
		now equal height) rather than align-self: center, which centered
		against the full label+input span and floated up near the label line -
		reported as the pill/remove not lining up with the inputs."""
		css = self._setup_css()
		tail = css.split(".taxjar-setup .ts-cred-row .ts-cred-tail {")[1].split("}")[0]
		self.assertIn("align-self: flex-end;", tail)

	def test_remove_button_centres_against_the_action_slot_not_its_bottom_edge(self):
		"""Regression guard: the x sat visibly below the Success pill.

		Both used to carry their own align-self: flex-end, which lines up their
		bottom EDGES - and they are different heights (a 22px circle against a
		~28px pill), so their centres landed a few px apart. One bottom-aligned
		wrapper with align-items: center fixes it without pinning either height,
		which matters because the slot's content changes per state (Connect
		button / Connecting... / Success pill / icon + Retry).
		"""
		js = self._js()
		add_card = js.split("_add_credential_card(cred) {")[1].split("\n\t_render_cred_action")[0]
		# To the end of the template literal, not the first </div> - that one
		# closes the action slot, which is the tail's own first child.
		tail = add_card.split('<div class="ts-cred-tail">')[1].split("`)")[0]
		self.assertIn('<div class="ts-cred-action">', tail)
		self.assertIn("ts-card-remove", tail)

		css = self._setup_css()
		tail_rule = css.split(".taxjar-setup .ts-cred-row .ts-cred-tail {")[1].split("}")[0]
		self.assertIn("align-items: center;", tail_rule)
		# The wrapper is the only bottom anchor now - leaving either child with
		# its own flex-end would reinstate the edge-alignment this fixes.
		action_rule = css.split(".taxjar-setup .ts-cred-row .ts-cred-action {")[1].split("}")[0]
		self.assertNotIn("align-self", action_rule)
		self.assertNotIn(".ts-cred-row .ts-card-remove { align-self", css)
		# No hardcoded nudge: a margin tuned to the pill would be wrong for
		# every other state the slot can hold.
		self.assertNotIn("margin-bottom", css.split(".ts-card-remove {")[1].split("}")[0])

	def test_connect_token_field_has_no_per_field_description(self):
		""""Leave blank to keep the saved token." was the extra description
		line that made an already-saved credential's Live token field taller
		than Company - removed rather than compensated for, since the
		placeholder ("••••••••••••2429") already conveys there's a stored
		token."""
		js = self._js()
		add_card = js.split("_add_credential_card(cred) {")[1].split("\n\t_render_cred_action")[0]
		token_control = add_card.split("const tokenControl = frappe.ui.form.make_control({")[1].split("});")[0]
		self.assertNotIn("description", token_control)
		self.assertNotIn("Leave blank to keep the saved token.", js)
		on_mode_change = js.split("_on_mode_change() {")[1].split("\n\t}\n")[0]
		self.assertNotIn("tokenCtrl.df.description", on_mode_change)

	def test_connect_result_replaces_the_button_rather_than_joining_it(self):
		"""The action slot cycles through one control at a time - an idle
		"Connect" button, a green verified badge, a red retry button - by
		emptying the slot and appending a single replacement, never stacking
		two controls side by side."""
		js = self._js()
		fn = js.split("_render_cred_action(entry) {")[1].split("\n\t}\n")[0]
		self.assertIn('.find(".ts-cred-action").empty()', fn)
		self.assertEqual(fn.count("$action.append("), 3)
		self.assertIn('theme: "green"', fn)
		self.assertIn('label: __("Connect")', fn)
		self.assertIn('tooltip: __("Retry")', fn)

	def test_connect_failure_reason_surfaces_on_the_token_field(self):
		"""A failed connection has to say why. It no longer does that through a
		bespoke info popover beside the action slot - the reason is set on the
		token field itself (df.invalid + set_description, frappe's native
		invalid-field primitive), so the message sits next to the input the user
		has to correct rather than behind a second click."""
		js = self._js()
		fn = js.split("_render_cred_action(entry) {")[1].split("\n\t}\n")[0]
		# Every render pushes the current error (or clears it) onto the field.
		self.assertIn("this._set_token_error(entry, entry.lastError);", fn)
		setter = js.split("_set_token_error(entry, message) {")[1].split("\n\t}\n")[0]
		self.assertIn("df.invalid", setter)
		self.assertIn("set_description", setter)
		# The old popover machinery is gone, not merely unused.
		self.assertNotIn("_info_btn_html", js)
		self.assertNotIn("_toggle_info_popover", js)

	def test_retry_state_is_visually_distinct_from_the_neutral_states(self):
		"""The failed state needed to read as failed, not as another neutral
		"in progress" chip. It carries its own theme and its own icon, and is
		the only state in the slot that does."""
		js = self._js()
		fn = js.split("_render_cred_action(entry) {")[1].split("\n\t}\n")[0]
		failed = fn.split("} else if (entry.lastError) {")[1].split("} else {")[0]
		self.assertIn('theme: "red"', failed)
		self.assertIn('icon: "refresh-cw"', failed)
		# Verified is the other themed state, and it is a different colour.
		verified = fn.split("if (entry.tested) {")[1].split("} else if")[0]
		self.assertIn('theme: "green"', verified)
		self.assertNotIn('theme: "red"', verified)

	def test_connect_button_renamed_to_connect(self):
		"""The idle action-slot button reads "Connect", not "Test connection"."""
		js = self._js()
		fn = js.split("_render_cred_action(entry) {")[1].split("\n\t}\n")[0]
		self.assertIn('label: __("Connect")', fn)
		self.assertNotIn("Test connection", fn)

	def test_connect_action_slot_retests_in_every_state(self):
		"""Verified and failed both stay clickable - the same _test_connection
		handler as the idle button, so a stale Success or a failure can always
		be re-checked without reloading the wizard."""
		js = self._js()
		fn = js.split("_render_cred_action(entry) {")[1].split("\n\t}\n")[0]
		for branch in ("if (entry.tested) {", "} else if (entry.lastError) {", "} else {"):
			self.assertIn(branch, fn)
		# Failed and idle wire the handler inline; the verified badge is
		# non-interactive markup on its own, so _build_status_badge does the
		# click/keyboard wiring for that one.
		self.assertEqual(fn.count("onclick: () => this._test_connection(entry)"), 2)
		badge = js.split("_build_status_badge(entry, {")[1].split("\n\t}\n")[0]
		self.assertIn("this._test_connection(entry)", badge)

	def test_connect_edits_fall_back_through_reset_cred_status_to_idle_button(self):
		"""Editing company or token after a test must clear lastError too, not
		just tested - otherwise _render_cred_action would still show the old
		Failed pill instead of falling back to the idle button."""
		js = self._js()
		fn = js.split("_reset_cred_status(entry) {")[1].split("\n\t}\n")[0]
		self.assertIn("entry.lastError = null;", fn)
		self.assertIn("this._render_cred_action(entry);", fn)

	def test_connect_css_supports_credentials_section_and_rows(self):
		"""The credentials heading is the collapse target and its chevron turns
		when open. The pill's own cursor rule is gone with the pill - the action
		slot now holds frappe.ui.button/badge, which carry their own affordance."""
		css = self._setup_css()
		self.assertIn(".taxjar-setup .ts-cred-heading { cursor: pointer; justify-content: flex-start; }", css)
		self.assertIn(".taxjar-setup .ts-acc-chevron-open { transform: rotate(90deg); }", css)
		self.assertNotIn(".ts-cred-pill", css)

	def test_accounts_step_uses_company_scoped_account_links(self):
		js = self._js()
		self.assertIn('fieldtype: "Link", fieldname: "tax_account_head", options: "Account"', js)
		self.assertIn('fieldtype: "Link", fieldname: "shipping_account_head", options: "Account"', js)
		self.assertIn("company: cred.company", js)

	def test_features_step_has_no_master_switch(self):
		"""taxjar_enabled is a TaxJar Settings form field, deliberately left alone
		by this wizard — no control for it, no lock/grey behaviour tied to it."""
		js = self._js()
		self.assertNotIn('fieldname: "taxjar_enabled"', js)
		self.assertNotIn("_sync_master_lock", js)
		self.assertIn('fieldtype: "Check", fieldname: "calculate"', js)
		self.assertIn('fieldtype: "Check", fieldname: "file"', js)

	def test_nexus_step_has_fetch_action_and_grouped_render(self):
		js = self._js()
		self.assertIn("_fetch_nexus", js)
		self.assertIn("_render_nexus_groups", js)

	def test_nexus_note_uses_the_framework_alert_not_a_bespoke_banner(self):
		"""A locally-invented .ts-banner box (hand-picked border/background)
		replaced by frappe's own alert component - themed and light/dark aware
		without this page picking any colours itself."""
		js = self._js()
		self.assertIn('<div class="ts-nexusnote-mount"></div>', js)
		mount = js.split('.find(".ts-nexusnote-mount").append(')[1].split("}));")[0]
		self.assertIn("frappe.ui.alert({", mount)
		self.assertIn('theme: "blue"', mount)
		self.assertNotIn("ts-banner", js)

	def test_token_label_reads_tracked_mode_not_control_mid_flight(self):
		"""_modeIsLive is a plain instance flag set directly from state, read
		by the token label instead of this.controls.mode.get_value() - a
		holdover from when mode was a real frappe control whose set_value()
		resolved asynchronously (frappe.run_serially), so a synchronous read
		right after could still see the pre-set value. The segmented toggle
		that replaced it has no such async step, but _modeIsLive is still
		needed for a different reason: it must exist before any credential
		card is built (see _add_credential_card), not just after a real
		change event."""
		js = self._js()
		self.assertIn("this._modeIsLive = (s.api_mode || \"Live\") === \"Live\";", js)
		self.assertIn('label: this._modeIsLive ? __("Live token") : __("Sandbox token")', js)
		self.assertNotIn('label: this.controls.mode.get_value() === "Live"', js)
		# _on_mode_change is a real change event, so it's safe to read the control
		# there - but it must also keep _modeIsLive in sync for any card added later.
		on_mode_change = js.split("_on_mode_change() {")[1].split("\n\t}\n")[0]
		self.assertIn("this._modeIsLive = live;", on_mode_change)

	def test_credential_card_starts_saved_triggers_a_fresh_test(self):
		"""A company with a stored token must not show a stale verified state
		just because a token exists - it could have been edited on the TaxJar
		Settings form since this wizard last ran. Every card starts untested
		and, if a token was already saved, immediately re-verifies it through
		the same _test_connection path a manual click uses."""
		js = self._js()
		add_card = js.split("_add_credential_card(cred) {")[1].split("\n\t}\n")[0]
		self.assertIn("const alreadySaved = !!cred.token_last4;", add_card)
		self.assertIn(
			"const entry = { company: cred.company, tested: false, lastError: null, $card, controls: {} };",
			add_card,
		)
		self.assertIn("if (alreadySaved) {", add_card)
		self.assertIn("this._test_connection(entry);", add_card)
		# ...and only a real result paints the verified badge.
		fn = js.split("_render_cred_action(entry) {")[1].split("\n\t}\n")[0]
		verified = fn.split("if (entry.tested) {")[1].split("} else if")[0]
		self.assertIn("_build_status_badge", verified)
		self.assertIn('theme: "green"', verified)

	def test_test_connection_reads_entry_company_not_the_control(self):
		"""The auto re-test above fires synchronously right after
		companyControl.set_value(cred.company), whose model update resolves
		asynchronously - reading the control's own get_value() here would
		still see the pre-set blank value in that case. entry.company is
		kept in sync directly (same fix _sync_connect_gate already needed)."""
		js = self._js()
		fn = js.split("_test_connection(entry) {")[1].split("\n\t}\n")[0]
		self.assertIn("const company = entry.company;", fn)
		self.assertNotIn("entry.controls.company.get_value()", fn)

	def test_restoring_existing_company_does_not_fire_onchange_reset(self):
		"""Regression guard: frappe's set_value() invokes df.onchange itself as
		part of setting the value, not only on real user input. Populating an
		already-saved card's Company field with its existing value (so the
		field isn't blank) therefore fired the "company changed" reset and
		immediately wiped the "Success" pill _add_credential_card had just set,
		straight back to the idle button - the exact bug reported. A guard must
		skip that reset exactly once, for the initial programmatic restore."""
		js = self._js()
		add_card = js.split("_add_credential_card(cred) {")[1].split("\n\t_render_cred_action")[0]
		self.assertIn("let restoringInitialCompany = !!cred.company;", add_card)
		onchange = add_card.split("companyControl.df.onchange = () => {")[1].split("};")[0]
		self.assertIn("if (restoringInitialCompany)", onchange)
		self.assertIn("restoringInitialCompany = false;", onchange)
		self.assertIn("return;", onchange)

	def test_editing_token_forces_a_fresh_test(self):
		"""The converse of the above: once the user actually types into the token
		field, the previously-saved-and-trusted state no longer applies."""
		js = self._js()
		self.assertIn('tokenControl.$input.on("input"', js)
		on_input = js.split('tokenControl.$input.on("input", () => {')[1].split("});")[0]
		self.assertIn("entry.tested = false;", on_input)
		self.assertIn("this._reset_cred_status(entry);", on_input)
		self.assertIn("this._sync_connect_gate();", on_input)

	def test_save_methods_reload_state_before_advancing(self):
		"""Every save-then-advance step re-fetches state so the wizard stays
		resumable/consistent instead of trusting a locally-guessed delta — once
		on initial load, once each from the three save steps, and once after
		removing an already-saved company."""
		js = self._js()
		self.assertIn("_save_connect", js)
		self.assertIn("_save_accounts", js)
		self.assertIn("_save_features", js)
		self.assertEqual(js.count("this._reload_state()"), 5)

	def test_review_summarises_connection_accounts_features_nexus(self):
		js = self._js()
		self.assertIn("_render_review", js)
		for label in ('__("Connection")', '__("Accounts")', '__("Features")', '__("Nexus")'):
			self.assertIn(label, js)

	def test_connect_card_has_remove_action_wired_to_server_api(self):
		js = self._js()
		self.assertIn("_remove_credential_card", js)
		self.assertIn("remove_company", js)
		self.assertIn("frappe.confirm", js)

	def test_token_control_disables_password_strength_meter(self):
		"""A TaxJar token isn't a password being created — the strength-meter
		request it fires per keystroke doesn't apply and errored in practice."""
		js = self._js()
		self.assertIn("disable_password_checks", js)

	def test_token_control_shows_masked_placeholder_when_stored(self):
		js = self._js()
		self.assertIn("placeholder: cred.token_last4", js)

	def test_nexus_step_auto_fetches_on_open(self):
		"""Opening the Nexus step pulls fresh data immediately — no need to
		remember to click Fetch just to see current nexus."""
		js = self._js()
		render_nexus = js.split("_render_nexus(")[1].split("\n\t_render_nexus_groups(")[0]
		self.assertIn("this._fetch_nexus()", render_nexus)

	def test_nexus_counts_pluralise_company(self):
		"""1 company must not read "1 companies". The fetch step no longer
		prints a count of its own - the region pills themselves are the result,
		and the badge beside them carries the state - so the count that remains
		is the Review step's, and it is the one that has to agree with itself."""
		js = self._js()
		review = js.split("_render_review() {")[1].split("\n\t}\n")[0]
		self.assertIn(
			'__("{0} across {1} {2}", [totalNexus, nexusCompaniesN, nexusCompaniesN === 1 ? __("company") : __("companies")])',
			review,
		)

	def test_review_nexus_row_pluralises_company(self):
		js = self._js()
		self.assertIn(
			'__("{0} across {1} {2}", [totalNexus, nexusCompaniesN, nexusCompaniesN === 1 ? __("company") : __("companies")])',
			js,
		)

	def test_review_has_no_taxjar_enabled_row_and_uses_green_badges(self):
		"""The master switch isn't managed by this wizard, so Review must not
		claim to report its state; Live mode and the nightly refresh cadence
		get Frappe's native green indicator-pill instead of plain text."""
		js = self._js()
		self.assertNotIn('__("TaxJar")', js)
		self.assertIn("indicator-pill green", js)
		self.assertIn('__("Auto-Refresh")', js)
		self.assertIn('__("Daily at midnight")', js)

	def test_review_values_share_one_weight(self):
		"""Regression guard: "Daily at midnight" was the one Review value placed
		as a direct child of .ts-kv, so it alone picked up that row's bold
		override and rendered heavier than every value beside it. Every value
		now goes through .ts-kv-plain, which is what keeps them consistent."""
		js = self._js()
		review = js.split("_render_review() {")[1].split("\n\t}\n")[0]
		self.assertIn(
			'<span>${__("Auto-Refresh")}</span><span class="ts-kv-plain">${__("Daily at midnight")}</span>',
			review,
		)
		# Nothing in the Review card sets a value span without that class.
		self.assertNotIn('<span>${__("Auto-Refresh")}</span><span>', review)

	def test_review_accounts_stack_company_and_detail_on_separate_lines(self):
		js = self._js()
		self.assertIn("ts-acc-company", js)
		self.assertIn("ts-acc-detail", js)

	def test_review_accounts_label_tax_and_shipping_ledgers_on_separate_lines(self):
		"""Two bare account names side by side ("X · Y") gave no indication of
		which was the tax ledger and which was the shipping ledger; each now
		gets its own labelled line rather than sharing one."""
		js = self._js()
		account_rows = js.split("const accountRows = companies.map((c) => `")[1].split("`).join")[0]
		self.assertEqual(account_rows.count('<div class="ts-acc-detail">'), 2)
		self.assertIn('__("Tax Ledger")}: ${frappe.utils.escape_html(c.tax_account_head', account_rows)
		self.assertIn('__("Shipping Ledger")}: ${frappe.utils.escape_html(c.shipping_account_head', account_rows)

	def test_welcome_step_button_says_continue_not_save(self):
		"""Nothing is saved on the Welcome step (no form fields) — its button
		must not claim to "Save"."""
		js = self._js()
		welcome_step = js.split('key: "welcome"')[1].split("},")[0]
		self.assertIn('nextLabel: __("Continue")', welcome_step)

	def test_check_sub_items_are_not_card_scoped_to_top_level_li(self):
		"""Regression guard: .ts-check li (no `>`) is a descendant selector, so
		it would also match .ts-check-sub's own <li>s two levels down and wrongly
		card-ify "Sales Tax Payable" / "Shipping and Freight Income" as bordered boxes instead of
		plain indented bullets."""
		import os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "page", "taxjar_setup", "taxjar_setup.css"))
		css = open(path).read()
		self.assertIn(".ts-check > li {", css)
		self.assertNotIn(".ts-check li {", css)

	def test_kv_bold_rule_is_child_scoped_not_descendant(self):
		"""Same class of bug as .ts-check li above: .ts-kv span:last-child (no
		`>`) is a descendant selector, so for a row whose value holds two
		stacked indicator-pills (API Logs: "Enabled" + "N days retention") it
		would also match the second pill (itself a last-child of its own
		wrapper) and bold only that one, inconsistent with the first."""
		import os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "page", "taxjar_setup", "taxjar_setup.css"))
		css = open(path).read()
		self.assertIn(".ts-kv > span:first-child {", css)
		self.assertIn(".ts-kv > span:last-child {", css)
		self.assertNotIn(".ts-kv span:first-child {", css)
		self.assertNotIn(".ts-kv span:last-child {", css)

	def test_card_body_zeroes_form_group_margin_to_avoid_double_gap(self):
		"""Bootstrap's default .form-group margin-bottom (15px) stacks on top of
		.ts-card-b's own flex gap (12px), doubling the visual gap between
		stacked fields (e.g. Company -> Live token) to ~27px for no reason."""
		import os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "page", "taxjar_setup", "taxjar_setup.css"))
		css = open(path).read()
		self.assertIn(".ts-card-b .form-group { margin-bottom: 0; }", css)

	def test_css_does_not_clip_link_dropdowns_and_caps_card_width(self):
		import os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "page", "taxjar_setup", "taxjar_setup.css"))
		css = open(path).read()
		# .ts-card holds Link controls (Company/Account) whose search dropdown can
		# extend past the card's own box — it must not clip them. (.ts-check li,
		# which has no dropdown content, is free to clip its own hover background.)
		card_rule = css.split(".taxjar-setup .ts-card {")[1].split("}")[0]
		self.assertNotIn("overflow: hidden", card_rule)
		self.assertIn("minmax(280px, 420px)", css)


# ── Regional: United States — ledger auto-select & tax template sync ────────


class _FakeTemplateRow:
	def __init__(self, **kwargs):
		self.__dict__.update(kwargs)

	def get(self, field):
		return getattr(self, field, None)

	def set(self, field, value):
		setattr(self, field, value)


class _FakeTemplateDoc:
	"""Minimal stand-in for a Sales Taxes and Charges Template doc."""
	def __init__(self, name, taxes=None, is_default=0):
		self.name = name
		self.taxes = taxes or []
		self.is_default = is_default
		self.saved = False

	def append(self, field, data):
		if field == "taxes":
			self.taxes.append(_FakeTemplateRow(**data))

	def save(self, ignore_permissions=False):
		self.saved = True

	def insert(self, ignore_permissions=False):
		self.saved = True


def _fake_company_lookup(abbr="TC", cost_center="Main - TC"):
	"""Side_effect for frappe.db.get_value("Company", company, field)."""
	def _get(doctype, company, field):
		return {"abbr": abbr, "cost_center": cost_center}.get(field)
	return _get


REGIONAL = "taxjar_integration.taxjar_integration.regional.united_states"


class TestResolveDefaultLedgers(UnitTestCase):

	def test_matches_by_account_number_first(self):
		def fake_get_value(doctype, filters):
			if filters.get("account_number") == "21400":
				return "Sales Tax Payable - TC"
			if filters.get("account_number") == "41200":
				return "Shipping and Freight Income - TC"
			return None

		with patch(f"{REGIONAL}.frappe.db.get_value", side_effect=fake_get_value):
			result = resolve_default_ledgers("Test Co")

		self.assertEqual(result["tax_account_head"], "Sales Tax Payable - TC")
		self.assertEqual(result["shipping_account_head"], "Shipping and Freight Income - TC")

	def test_falls_back_to_account_name_when_number_not_found(self):
		def fake_get_value(doctype, filters):
			if "account_number" in filters:
				return None
			if filters.get("account_name") == "Sales Tax Payable":
				return "Custom Sales Tax - TC"
			if filters.get("account_name") == "Shipping and Freight Income":
				return "Custom Freight - TC"
			return None

		with patch(f"{REGIONAL}.frappe.db.get_value", side_effect=fake_get_value):
			result = resolve_default_ledgers("Test Co")

		self.assertEqual(result["tax_account_head"], "Custom Sales Tax - TC")
		self.assertEqual(result["shipping_account_head"], "Custom Freight - TC")

	def test_returns_none_when_neither_found(self):
		"""Non-standard chart of accounts: no account, no exception."""
		with patch(f"{REGIONAL}.frappe.db.get_value", side_effect=_scalar_get_value(None)):
			result = resolve_default_ledgers("Test Co")

		self.assertIsNone(result["tax_account_head"])
		self.assertIsNone(result["shipping_account_head"])

	def test_lookup_is_company_scoped(self):
		def fake_get_value(doctype, filters):
			if filters.get("company") == "Test Co" and filters.get("account_number") == "21400":
				return "Sales Tax Payable - TC"
			return None

		with patch(f"{REGIONAL}.frappe.db.get_value", side_effect=fake_get_value):
			result = resolve_default_ledgers("Other Co")

		self.assertIsNone(result["tax_account_head"])


class TestEnsureCompanyLedgersAndTemplate(UnitTestCase):

	def _row(self, company="Test Co", tax_account_head=None, shipping_account_head=None, calculate_tax=0):
		row = MagicMock()
		row.name = "row-1"
		row.company = company
		row.tax_account_head = tax_account_head
		row.shipping_account_head = shipping_account_head
		row.taxjar_calculate_tax = calculate_tax
		return row

	def test_backfills_both_blank_fields(self):
		row = self._row()
		resolved = {"tax_account_head": "Sales Tax Payable - TC", "shipping_account_head": "Shipping and Freight Income - TC"}

		with patch(f"{REGIONAL}.resolve_default_ledgers", return_value=resolved), \
		     patch(f"{REGIONAL}.frappe.db.set_value") as mock_set, \
		     patch(f"{REGIONAL}._upsert_tax_template") as mock_upsert, \
		     patch(f"{REGIONAL}._disable_default_us_templates") as mock_disable:
			ensure_company_ledgers_and_template(row)

		mock_set.assert_called_once_with("TaxJar Company Config", "row-1", resolved)
		self.assertEqual(row.tax_account_head, resolved["tax_account_head"])
		self.assertEqual(row.shipping_account_head, resolved["shipping_account_head"])
		mock_upsert.assert_called_once_with(
			"Test Co",
			resolved["tax_account_head"],
			shipping_account_head=resolved["shipping_account_head"],
			is_default=False,
		)
		mock_disable.assert_not_called()

	def test_does_not_overwrite_existing_ledger_value(self):
		"""An admin's own choice is never overwritten, even if it differs from what
		the standard-CoA lookup would resolve."""
		row = self._row(tax_account_head="Manual Tax - TC", shipping_account_head="Manual Freight - TC")
		resolved = {"tax_account_head": "Sales Tax Payable - TC", "shipping_account_head": "Shipping and Freight Income - TC"}

		with patch(f"{REGIONAL}.resolve_default_ledgers", return_value=resolved), \
		     patch(f"{REGIONAL}.frappe.db.set_value") as mock_set, \
		     patch(f"{REGIONAL}._upsert_tax_template") as mock_upsert:
			ensure_company_ledgers_and_template(row)

		mock_set.assert_not_called()
		mock_upsert.assert_called_once_with(
			"Test Co", "Manual Tax - TC", shipping_account_head="Manual Freight - TC", is_default=False
		)

	def test_backfills_only_the_blank_field(self):
		row = self._row(tax_account_head="Manual Tax - TC", shipping_account_head=None)
		resolved = {"tax_account_head": "Sales Tax Payable - TC", "shipping_account_head": "Shipping and Freight Income - TC"}

		with patch(f"{REGIONAL}.resolve_default_ledgers", return_value=resolved), \
		     patch(f"{REGIONAL}.frappe.db.set_value") as mock_set, \
		     patch(f"{REGIONAL}._upsert_tax_template"):
			ensure_company_ledgers_and_template(row)

		mock_set.assert_called_once_with(
			"TaxJar Company Config", "row-1", {"shipping_account_head": resolved["shipping_account_head"]}
		)
		self.assertEqual(row.tax_account_head, "Manual Tax - TC")
		self.assertEqual(row.shipping_account_head, resolved["shipping_account_head"])

	def test_leaves_blank_and_skips_template_when_neither_resolves(self):
		row = self._row()
		resolved = {"tax_account_head": None, "shipping_account_head": None}

		with patch(f"{REGIONAL}.resolve_default_ledgers", return_value=resolved), \
		     patch(f"{REGIONAL}.frappe.db.set_value") as mock_set, \
		     patch(f"{REGIONAL}._upsert_tax_template") as mock_upsert, \
		     patch(f"{REGIONAL}._disable_default_us_templates") as mock_disable:
			ensure_company_ledgers_and_template(row)

		mock_set.assert_not_called()
		mock_upsert.assert_not_called()
		mock_disable.assert_not_called()

	def test_gates_is_default_on_taxjar_calculate_tax(self):
		row = self._row(tax_account_head="Tax - TC", calculate_tax=1)
		resolved = {"tax_account_head": None, "shipping_account_head": None}

		with patch(f"{REGIONAL}.resolve_default_ledgers", return_value=resolved), \
		     patch(f"{REGIONAL}._upsert_tax_template") as mock_upsert, \
		     patch(f"{REGIONAL}._disable_default_us_templates") as mock_disable:
			ensure_company_ledgers_and_template(row)

		mock_upsert.assert_called_once_with(
			"Test Co", "Tax - TC", shipping_account_head=None, is_default=True
		)
		mock_disable.assert_called_once_with("Test Co")

	def test_does_not_disable_defaults_when_calculate_tax_off(self):
		"""Ledgers/template stay in sync even with tax calc off, but ERPNext's own
		defaults are only ever disabled once TaxJar's template is actually active."""
		row = self._row(tax_account_head="Tax - TC", calculate_tax=0)
		resolved = {"tax_account_head": None, "shipping_account_head": None}

		with patch(f"{REGIONAL}.resolve_default_ledgers", return_value=resolved), \
		     patch(f"{REGIONAL}._upsert_tax_template") as mock_upsert, \
		     patch(f"{REGIONAL}._disable_default_us_templates") as mock_disable:
			ensure_company_ledgers_and_template(row)

		mock_upsert.assert_called_once_with(
			"Test Co", "Tax - TC", shipping_account_head=None, is_default=False
		)
		mock_disable.assert_not_called()


class TestUpsertTaxTemplate(UnitTestCase):

	def _patch_company_lookups(self, abbr="TC", cost_center="Main - TC"):
		return patch(f"{REGIONAL}.frappe.db.get_value", side_effect=_fake_company_lookup(abbr, cost_center))

	def test_creates_new_template_with_single_actual_row(self):
		created = {}

		def fake_get_doc(arg):
			created["dict"] = arg
			doc = _FakeTemplateDoc(name=f"{arg['title']} - TC", taxes=list(arg["taxes"]), is_default=arg["is_default"])
			created["doc"] = doc
			return doc

		with self._patch_company_lookups(), \
		     patch(f"{REGIONAL}.frappe.db.exists", return_value=False), \
		     patch(f"{REGIONAL}.frappe.get_doc", side_effect=fake_get_doc):
			name = _upsert_tax_template("Test Co", "Sales Tax Payable - TC", is_default=True)

		self.assertEqual(created["dict"]["doctype"], "Sales Taxes and Charges Template")
		self.assertEqual(created["dict"]["title"], TAXJAR_TEMPLATE_TITLE)
		self.assertEqual(created["dict"]["is_default"], 1)
		self.assertEqual(len(created["dict"]["taxes"]), 1)

		row = created["dict"]["taxes"][0]
		self.assertEqual(row["charge_type"], "Actual")
		self.assertEqual(row["account_head"], "Sales Tax Payable - TC")
		self.assertEqual(row["description"], TAXJAR_ROW_DESCRIPTION)
		self.assertEqual(row["cost_center"], "Main - TC")
		self.assertEqual(name, created["doc"].name)

	def test_adds_a_shipping_row_from_the_configured_ledger(self):
		"""A placeholder for the user to type a delivery charge into. TaxJar
		never writes an amount here - get_tax_data() reads shipping back out of
		whatever the user entered, matched on this same ledger."""
		from taxjar_integration.taxjar_integration.regional.united_states import (
			TAXJAR_SHIPPING_ROW_DESCRIPTION,
		)
		created = {}

		def fake_get_doc(arg):
			created["dict"] = arg
			return _FakeTemplateDoc(name="x", taxes=list(arg["taxes"]), is_default=arg["is_default"])

		with self._patch_company_lookups(), \
		     patch(f"{REGIONAL}.frappe.db.exists", return_value=False), \
		     patch(f"{REGIONAL}.frappe.get_doc", side_effect=fake_get_doc):
			_upsert_tax_template(
				"Test Co",
				"Sales Tax Payable - TC",
				shipping_account_head="Shipping and Freight Income - TC",
				is_default=True,
			)

		rows = created["dict"]["taxes"]
		self.assertEqual(len(rows), 2)
		# Shipping leads - sales tax is calculated on a total that includes it.
		self.assertEqual(rows[0]["charge_type"], "Actual")
		self.assertEqual(rows[0]["account_head"], "Shipping and Freight Income - TC")
		self.assertEqual(rows[0]["description"], TAXJAR_SHIPPING_ROW_DESCRIPTION)
		self.assertEqual(rows[0]["cost_center"], "Main - TC")
		self.assertEqual(rows[1]["description"], TAXJAR_ROW_DESCRIPTION)

	def test_no_shipping_row_without_a_shipping_ledger(self):
		created = {}

		def fake_get_doc(arg):
			created["dict"] = arg
			return _FakeTemplateDoc(name="x", taxes=list(arg["taxes"]), is_default=arg["is_default"])

		with self._patch_company_lookups(), \
		     patch(f"{REGIONAL}.frappe.db.exists", return_value=False), \
		     patch(f"{REGIONAL}.frappe.get_doc", side_effect=fake_get_doc):
			_upsert_tax_template("Test Co", "Sales Tax Payable - TC", is_default=True)

		self.assertEqual(len(created["dict"]["taxes"]), 1)

	def test_no_shipping_row_when_it_would_reuse_the_tax_ledger(self):
		"""One ledger for both would make get_tax_data() read the sales tax back
		as a shipping charge, and _remove_taxjar_rows() strip the user's
		shipping amount along with the tax row."""
		created = {}

		def fake_get_doc(arg):
			created["dict"] = arg
			return _FakeTemplateDoc(name="x", taxes=list(arg["taxes"]), is_default=arg["is_default"])

		with self._patch_company_lookups(), \
		     patch(f"{REGIONAL}.frappe.db.exists", return_value=False), \
		     patch(f"{REGIONAL}.frappe.get_doc", side_effect=fake_get_doc):
			_upsert_tax_template(
				"Test Co", "Tax - TC", shipping_account_head="Tax - TC", is_default=True
			)

		self.assertEqual(len(created["dict"]["taxes"]), 1)

	def test_shipping_row_appended_to_an_existing_template(self):
		"""Existing installs gain the row on the next sync, without disturbing
		the tax row already there."""
		from taxjar_integration.taxjar_integration.regional.united_states import (
			TAXJAR_SHIPPING_ROW_DESCRIPTION,
		)
		existing_row = _FakeTemplateRow(charge_type="Actual", account_head="Tax - TC",
			description=TAXJAR_ROW_DESCRIPTION, cost_center="Main - TC")
		doc = _FakeTemplateDoc(name="TaxJar Sales Tax - TC", taxes=[existing_row], is_default=1)

		with self._patch_company_lookups(), \
		     patch(f"{REGIONAL}.frappe.db.exists", return_value=True), \
		     patch(f"{REGIONAL}.frappe.get_doc", return_value=doc):
			_upsert_tax_template(
				"Test Co", "Tax - TC", shipping_account_head="Freight - TC", is_default=True
			)

		# Appended, then reordered ahead of the tax row that was already there -
		# an existing install needs the order corrected, not just the row added.
		self.assertEqual(len(doc.taxes), 2)
		self.assertEqual(doc.taxes[0].description, TAXJAR_SHIPPING_ROW_DESCRIPTION)
		self.assertEqual(doc.taxes[0].account_head, "Freight - TC")
		self.assertEqual(doc.taxes[1].description, TAXJAR_ROW_DESCRIPTION)
		# The child table renders by idx, so the list order alone is not enough.
		self.assertEqual([row.idx for row in doc.taxes], [1, 2])
		self.assertTrue(doc.saved)

	def test_rows_matched_on_description_not_position(self):
		"""An admin's own row must survive a sync, and ours must be found even
		when it is not first."""
		other = _FakeTemplateRow(charge_type="Actual", account_head="Rounding - TC",
			description="Rounding Adjustment", cost_center="Main - TC")
		ours = _FakeTemplateRow(charge_type="Actual", account_head="Old Tax - TC",
			description=TAXJAR_ROW_DESCRIPTION, cost_center="Main - TC")
		doc = _FakeTemplateDoc(name="TaxJar Sales Tax - TC", taxes=[other, ours], is_default=1)

		with self._patch_company_lookups(), \
		     patch(f"{REGIONAL}.frappe.db.exists", return_value=True), \
		     patch(f"{REGIONAL}.frappe.get_doc", return_value=doc):
			_upsert_tax_template("Test Co", "New Tax - TC", is_default=True)

		self.assertEqual(ours.account_head, "New Tax - TC")
		self.assertEqual(other.account_head, "Rounding - TC")
		# Ours leads; the admin's own row keeps its place behind it.
		self.assertEqual(doc.taxes[0].description, TAXJAR_ROW_DESCRIPTION)
		self.assertEqual(doc.taxes[1].description, "Rounding Adjustment")

	def test_updates_existing_template_account_head_when_changed(self):
		existing_row = _FakeTemplateRow(charge_type="Actual", account_head="Old Tax - TC",
			description=TAXJAR_ROW_DESCRIPTION, cost_center="Main - TC")
		doc = _FakeTemplateDoc(name="TaxJar Sales Tax - TC", taxes=[existing_row], is_default=1)

		with self._patch_company_lookups(), \
		     patch(f"{REGIONAL}.frappe.db.exists", return_value=True), \
		     patch(f"{REGIONAL}.frappe.get_doc", return_value=doc):
			_upsert_tax_template("Test Co", "New Tax - TC", is_default=True)

		self.assertEqual(doc.taxes[0].account_head, "New Tax - TC")
		self.assertTrue(doc.saved)

	def test_no_save_when_already_in_sync(self):
		"""Idempotency: a second sync with identical inputs makes zero writes."""
		existing_row = _FakeTemplateRow(charge_type="Actual", account_head="Tax - TC",
			description=TAXJAR_ROW_DESCRIPTION, cost_center="Main - TC")
		doc = _FakeTemplateDoc(name="TaxJar Sales Tax - TC", taxes=[existing_row], is_default=1)

		with self._patch_company_lookups(), \
		     patch(f"{REGIONAL}.frappe.db.exists", return_value=True), \
		     patch(f"{REGIONAL}.frappe.get_doc", return_value=doc):
			_upsert_tax_template("Test Co", "Tax - TC", is_default=True)

		self.assertFalse(doc.saved)

	def test_is_default_flip_triggers_save(self):
		existing_row = _FakeTemplateRow(charge_type="Actual", account_head="Tax - TC",
			description=TAXJAR_ROW_DESCRIPTION, cost_center="Main - TC")
		doc = _FakeTemplateDoc(name="TaxJar Sales Tax - TC", taxes=[existing_row], is_default=1)

		with self._patch_company_lookups(), \
		     patch(f"{REGIONAL}.frappe.db.exists", return_value=True), \
		     patch(f"{REGIONAL}.frappe.get_doc", return_value=doc):
			_upsert_tax_template("Test Co", "Tax - TC", is_default=False)

		self.assertEqual(doc.is_default, 0)
		self.assertTrue(doc.saved)


class TestDisableDefaultUsTemplates(UnitTestCase):

	def test_disables_matching_titles_only(self):
		existing = {"US ST 6%": "US ST 6% - TC", "US ST 4%": "US ST 4% - TC"}

		def fake_get_value(doctype, filters):
			return existing.get(filters.get("title"))

		with patch(f"{REGIONAL}.frappe.db.get_value", side_effect=fake_get_value), \
		     patch(f"{REGIONAL}.frappe.db.set_value") as mock_set:
			_disable_default_us_templates("Test Co")

		self.assertEqual(mock_set.call_count, 2)
		disabled_names = {c.args[1] for c in mock_set.call_args_list}
		self.assertEqual(disabled_names, {"US ST 6% - TC", "US ST 4% - TC"})
		for call in mock_set.call_args_list:
			self.assertEqual(call.args[2], {"is_default": 0, "disabled": 1})

	def test_noop_when_none_present(self):
		with patch(f"{REGIONAL}.frappe.db.get_value", side_effect=_scalar_get_value(None)), \
		     patch(f"{REGIONAL}.frappe.db.set_value") as mock_set:
			_disable_default_us_templates("Test Co")

		mock_set.assert_not_called()

	def test_does_not_touch_similarly_named_custom_template(self):
		"""Only the three exact literal titles are ever matched - a user's own
		template named e.g. "US ST 6% (custom)" is untouched."""
		with patch(f"{REGIONAL}.frappe.db.get_value", side_effect=_scalar_get_value(None)) as mock_get:
			_disable_default_us_templates("Test Co")

		queried_titles = {c.args[1]["title"] for c in mock_get.call_args_list}
		self.assertEqual(queried_titles, {"US ST 6%", "US ST 4%", "US ST 6.25%"})


class TestSyncAllCompanyTaxTemplates(UnitTestCase):

	def test_iterates_explicit_rows_without_touching_settings_singleton(self):
		rows = [MagicMock(), MagicMock()]

		with patch(f"{REGIONAL}.ensure_company_ledgers_and_template") as mock_ensure, \
		     patch(f"{REGIONAL}.frappe.get_single") as mock_get_single:
			sync_all_company_tax_templates(rows)

		mock_get_single.assert_not_called()
		self.assertEqual(mock_ensure.call_count, 2)

	def test_reads_from_settings_singleton_when_rows_omitted(self):
		settings = MagicMock()
		row = MagicMock()
		settings.company_config = [row]

		with patch(f"{REGIONAL}.ensure_company_ledgers_and_template") as mock_ensure, \
		     patch(f"{REGIONAL}.frappe.get_single", return_value=settings):
			sync_all_company_tax_templates()

		mock_ensure.assert_called_once_with(row)

	def test_true_noop_on_empty_company_config(self):
		"""Fresh install: nothing configured yet, nothing to reconcile."""
		settings = MagicMock()
		settings.company_config = []

		with patch(f"{REGIONAL}.ensure_company_ledgers_and_template") as mock_ensure, \
		     patch(f"{REGIONAL}.frappe.get_single", return_value=settings):
			sync_all_company_tax_templates()

		mock_ensure.assert_not_called()


class TestGetDefaultLedgersAPI(UnitTestCase):
	"""Whitelisted wrapper in taxjar_setup.py - the guided setup JS's _call()
	helper hardcodes that module path, so the real lookup in regional/united_states.py
	needs a thin pass-through here to be reachable from the client."""

	def test_delegates_to_resolve_default_ledgers_with_read_permission_check(self):
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import get_default_ledgers

		resolved = {"tax_account_head": "Tax - TC", "shipping_account_head": "Freight - TC"}
		with patch("taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup.frappe.has_permission") as mock_perm, \
		     patch(f"{REGIONAL}.resolve_default_ledgers", return_value=resolved) as mock_resolve:
			result = get_default_ledgers("Test Co")

		mock_perm.assert_called_once_with("TaxJar Settings", "read", throw=True)
		mock_resolve.assert_called_once_with("Test Co")
		self.assertEqual(result, resolved)


class TestAccountsStepLedgerAutoFill(UnitTestCase):
	"""String/structure assertions on _render_accounts() - same pattern as
	TestGuidedSetupPhase2JS since there's no JS runtime in this test suite."""

	def _js(self):
		import os
		path = os.path.normpath(os.path.join(
			os.path.dirname(__file__), "..", "..", "page", "taxjar_setup", "taxjar_setup.js"))
		return open(path).read()

	def _render_accounts_body(self):
		js = self._js()
		return js.split("_render_accounts()")[1].split("\n\t_save_accounts()")[0]

	def test_render_accounts_calls_get_default_ledgers(self):
		self.assertIn('this._call("get_default_ledgers"', self._render_accounts_body())

	def test_autofill_is_guarded_on_blank_fields(self):
		"""Must not fire for a company whose ledgers are already fully configured -
		otherwise revisiting the wizard makes a wasted round trip on every load."""
		body = self._render_accounts_body()
		call_site = body.split('this._call("get_default_ledgers"')[0]
		self.assertIn("if (!cfg.tax_account_head || !cfg.shipping_account_head)", call_site[-400:])

	def test_autofill_never_overwrites_an_already_set_field(self):
		body = self._render_accounts_body()
		autofill_block = body.split('this._call("get_default_ledgers"')[1]
		self.assertIn("if (!cfg.tax_account_head && defaults.tax_account_head)", autofill_block)
		self.assertIn("if (!cfg.shipping_account_head && defaults.shipping_account_head)", autofill_block)


# ── TaxJar error classification ──────────────────────────────────────────────


def _response_error(status, detail=None):
	import taxjar.exceptions

	err = taxjar.exceptions.TaxJarResponseError(f"{status} Error")
	err.full_response = {"status_code": status, "detail": detail}
	return err


class TestClassifyTaxJarError(UnitTestCase):
	"""python-taxjar raises four exception classes and carries no status taxonomy,
	so the split between "retry this" and "a human has to fix this" is entirely
	ours - and getting it wrong is what had a permanently-rejected invoice
	re-sent every 15 minutes for three days."""

	def test_connection_error_is_retryable(self):
		import taxjar.exceptions

		info = classify_taxjar_error(taxjar.exceptions.TaxJarConnectionError("timed out"))
		self.assertTrue(info["retryable"])
		self.assertIsNone(info["status"])
		self.assertIn("unreachable", info["message"])

	def test_transient_status_codes_are_retryable(self):
		for status in (408, 429, 500, 502, 503, 504):
			with self.subTest(status=status):
				self.assertTrue(classify_taxjar_error(_response_error(status))["retryable"])

	def test_request_level_rejections_are_not_retryable(self):
		"""Each of these describes a request that will be rejected identically for
		as long as nothing about it changes."""
		for status in (400, 401, 403, 404, 405, 406, 410, 422):
			with self.subTest(status=status):
				self.assertFalse(classify_taxjar_error(_response_error(status))["retryable"])

	def test_status_carries_a_readable_headline(self):
		info = classify_taxjar_error(_response_error(401, "Not authorized for route"))
		self.assertEqual(info["message"], "TaxJar API Token is invalid, go to guided setup to configure.")
		self.assertNotIn("route", info["message"], "TaxJar's own 401 detail says nothing actionable")

	def test_missing_resource_says_what_to_do(self):
		info = classify_taxjar_error(_response_error(404, "Resource can not be found"))
		self.assertFalse(info["retryable"])
		self.assertEqual(
			info["message"], "Transaction not found in TaxJar, can't update the latest changes."
		)

	def test_linkify_guided_setup_turns_the_phrase_into_a_link(self):
		"""The 401 message points the user at "guided setup" by name - a message
		about to reach frappe.throw() (rendered as HTML, unlike the plain-text
		Sync Error field) should turn that into a real link."""
		message = classify_taxjar_error(_response_error(401))["message"]
		linked = _linkify_guided_setup(message)
		self.assertIn('<a href="/app/taxjar-setup">guided setup</a>', linked)
		self.assertNotIn("<a", message, "the stored/classified message itself must stay plain text")

	def test_linkify_guided_setup_is_case_insensitive_and_leaves_other_text_alone(self):
		linked = _linkify_guided_setup("Go to Guided Setup now.")
		self.assertEqual(linked, 'Go to <a href="/app/taxjar-setup">guided setup</a> now.')

	def test_linkify_guided_setup_is_a_no_op_without_the_phrase(self):
		message = "Something else went wrong."
		self.assertEqual(_linkify_guided_setup(message), message)

	def test_duplicate_transaction_says_what_to_do(self):
		info = classify_taxjar_error(
			_response_error(422, "Provider tranx already imported for your user account")
		)
		self.assertFalse(info["retryable"])
		self.assertIn("Transaction ID already exists in TaxJar", info["message"])
		self.assertNotIn("tranx", info["message"])

	def test_exemption_conflict_says_what_to_do(self):
		info = classify_taxjar_error(_response_error(
			400,
			"exemption_type must be 'non_exempt' or 'marketplace' if any present "
			"sales_tax parameter values are non-zero",
		))
		self.assertFalse(info["retryable"])
		self.assertIn("Exempt transactions cannot have sales tax", info["message"])
		self.assertNotIn("non_exempt", info["message"])

	def test_field_names_are_relabelled_without_mangling_values(self):
		"""The old blanket underscore strip rewrote TaxJar's own quoted values as
		prose ("non_exempt" -> "non exempt"); only keys should be relabelled."""
		message = classify_taxjar_error(_response_error(400, "to_state is invalid"))["message"]
		self.assertIn("State is invalid", message)

	def test_unreadable_body_is_retryable(self):
		"""TaxJarResponse.data_from_request() calls request.json() before it looks
		at the status code, so a gateway HTML error page never becomes a
		TaxJarResponseError - it arrives as a JSON decode failure."""
		info = classify_taxjar_error(json.JSONDecodeError("Expecting value", "<html>502</html>", 0))
		self.assertTrue(info["retryable"])
		self.assertIn("temporary", info["message"])

	def test_unknown_exception_is_not_retryable_and_hides_the_traceback(self):
		try:
			raise RuntimeError("boom")
		except RuntimeError as err:
			info = classify_taxjar_error(err)
		self.assertFalse(info["retryable"])
		self.assertIn("RuntimeError: boom", info["message"])
		self.assertNotIn("Traceback", info["message"])
		self.assertIn("Traceback", info["log_detail"])

	def test_validation_errors_keep_their_own_wording(self):
		info = classify_taxjar_error(
			frappe.exceptions.ValidationError("Please enter a valid State in the Shipping Address")
		)
		self.assertFalse(info["retryable"])
		self.assertIn("valid State", info["message"])

	def test_sanitize_error_response_still_returns_just_the_sentence(self):
		self.assertEqual(
			sanitize_error_response(_response_error(500)),
			classify_taxjar_error(_response_error(500))["message"],
		)


class TestRetryCronOnlyPicksUpRetryableFailures(UnitTestCase):

	def test_invoice_query_filters_on_the_retryable_flag(self):
		from taxjar_integration.taxjar_integration.tasks import retry_failed_taxjar_syncs

		with patch("taxjar_integration.taxjar_integration.tasks._is_taxjar_enabled", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.get_all", return_value=[]) as mock_get_all:
			retry_failed_taxjar_syncs()

		self.assertEqual(mock_get_all.call_args.kwargs["filters"]["taxjar_sync_retryable"], 1)

	def test_customer_query_filters_on_the_retryable_flag(self):
		from taxjar_integration.taxjar_integration.tasks import retry_failed_taxjar_customer_syncs

		with patch("taxjar_integration.taxjar_integration.tasks._is_taxjar_enabled", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.get_all", return_value=[]) as mock_get_all, \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.get_single", return_value=MagicMock(company_config=[])):
			retry_failed_taxjar_customer_syncs()

		self.assertEqual(
			mock_get_all.call_args.kwargs["filters"]["taxjar_customer_sync_retryable"], 1
		)

	def test_invoice_query_filters_on_the_retry_count_cap(self):
		from taxjar_integration.taxjar_integration.tasks import retry_failed_taxjar_syncs
		from taxjar_integration.taxjar_integration.taxjar_integration import TAXJAR_MAX_SYNC_RETRIES

		with patch("taxjar_integration.taxjar_integration.tasks._is_taxjar_enabled", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.get_all", return_value=[]) as mock_get_all:
			retry_failed_taxjar_syncs()

		self.assertEqual(
			mock_get_all.call_args.kwargs["filters"]["taxjar_sync_retry_count"],
			("<", TAXJAR_MAX_SYNC_RETRIES),
		)

	def test_customer_query_filters_on_the_retry_count_cap(self):
		from taxjar_integration.taxjar_integration.tasks import retry_failed_taxjar_customer_syncs
		from taxjar_integration.taxjar_integration.taxjar_integration import TAXJAR_MAX_SYNC_RETRIES

		with patch("taxjar_integration.taxjar_integration.tasks._is_taxjar_enabled", return_value=True), \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.get_all", return_value=[]) as mock_get_all, \
		     patch("taxjar_integration.taxjar_integration.tasks.frappe.get_single", return_value=MagicMock(company_config=[])):
			retry_failed_taxjar_customer_syncs()

		self.assertEqual(
			mock_get_all.call_args.kwargs["filters"]["taxjar_customer_sync_retry_count"],
			("<", TAXJAR_MAX_SYNC_RETRIES),
		)


# ── Whitelisted endpoint contract ────────────────────────────────────────────


class TestWhitelistedEndpointContract(UnitTestCase):
	"""Every HTTP-reachable method checks permission and, if it writes, is
	POST-only.

	The registry assertions matter as much as the behavioural ones: a new
	endpoint added without a guard is the failure mode these are here to catch,
	and it is invisible to a test that only exercises the endpoints that exist
	today.
	"""

	TX_PAGE = "taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions"
	CUST_PAGE = "taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers"

	@staticmethod
	def _methods_for(fn):
		return frappe.allowed_http_methods_for_whitelisted_func.get(fn)

	def test_sync_workers_are_not_reachable_over_http(self):
		"""The workers run under frappe.enqueue, which resolves a dotted path
		without whitelisting. Their permission-checked entry points are the
		only way in from a browser."""
		from taxjar_integration.taxjar_integration.taxjar_integration import (
			delete_transaction_from_taxjar,
			sync_customer_to_taxjar,
			sync_transaction_to_taxjar,
		)

		for worker in (sync_transaction_to_taxjar, sync_customer_to_taxjar, delete_transaction_from_taxjar):
			self.assertNotIn(worker, frappe.whitelisted, f"{worker.__name__} should not be whitelisted")

	def test_sync_entry_points_are_post_only(self):
		from taxjar_integration.taxjar_integration.taxjar_integration import (
			resync_customer,
			resync_transaction,
		)

		for fn in (resync_transaction, resync_customer):
			self.assertIn(fn, frappe.whitelisted)
			self.assertEqual(self._methods_for(fn), ("POST",), f"{fn.__name__} must be POST-only")

	def test_state_changing_endpoints_are_post_only(self):
		"""Frappe only validates the CSRF token for unsafe HTTP methods, so a
		writer left on GET is reachable without one."""
		from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import (
			bulk_clear_exemption,
			bulk_sync_to_taxjar,
			configure_exemption,
		)
		from taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup import (
			fetch_nexus,
			finish_setup,
			remove_company,
			save_company_accounts,
			save_connection,
			save_features,
			test_connection,
		)
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import (
			bulk_retry,
		)
		from taxjar_integration.taxjar_integration.taxjar_integration import (
			delete_transaction_manual,
			mark_address_as_shipping,
		)

		writers = (
			test_connection, save_connection, save_company_accounts, save_features,
			remove_company, fetch_nexus, finish_setup,
			configure_exemption, bulk_clear_exemption, bulk_sync_to_taxjar,
			bulk_retry, delete_transaction_manual, mark_address_as_shipping,
		)
		for fn in writers:
			self.assertEqual(self._methods_for(fn), ("POST",), f"{fn.__name__} must be POST-only")

	def test_every_whitelisted_endpoint_in_this_app_has_type_hints(self):
		import ast
		import pathlib

		offenders = []
		root = pathlib.Path(__file__).resolve().parents[3]
		for path in sorted(root.rglob("*.py")):
			if path.name.startswith("test_") or "__pycache__" in str(path):
				continue
			tree = ast.parse(path.read_text())
			for node in ast.walk(tree):
				if not isinstance(node, ast.FunctionDef):
					continue
				if not any("whitelist" in ast.unparse(d) for d in node.decorator_list):
					continue
				for arg in node.args.args + node.args.kwonlyargs:
					if arg.arg != "self" and arg.annotation is None:
						offenders.append(f"{path.name}:{node.lineno} {node.name}({arg.arg})")

		self.assertEqual(offenders, [], f"whitelisted args without type hints: {offenders}")

	def test_read_endpoints_reject_a_user_without_the_doctype(self):
		from taxjar_integration.taxjar_integration.page.taxjar_customers.taxjar_customers import (
			get_customers,
		)
		from taxjar_integration.taxjar_integration.page.taxjar_transactions.taxjar_transactions import (
			get_transactions,
		)

		frappe.set_user("Guest")
		try:
			for fn in (get_transactions, get_customers):
				with self.assertRaises(frappe.PermissionError):
					fn()
		finally:
			frappe.set_user("Administrator")

	def test_transaction_endpoints_check_the_invoice_before_acting(self):
		"""Each of these reaches TaxJar for a specific Sales Invoice, so the
		check has to name that document - a doctype-level check would let a
		user act on an invoice their User Permissions exclude."""
		from taxjar_integration.taxjar_integration import taxjar_integration as mod

		cases = (
			(mod.resync_transaction, "write"),
			(mod.fetch_transaction_from_taxjar, "read"),
			(mod.delete_transaction_manual, "write"),
		)
		for fn, ptype in cases:
			with patch.object(mod.frappe, "has_permission", side_effect=frappe.PermissionError) as guard:
				with self.assertRaises(frappe.PermissionError):
					fn("SINV-PERM-001")
			self.assertEqual(
				guard.call_args[0][:2], ("Sales Invoice", ptype), f"{fn.__name__} checked the wrong permission"
			)
			self.assertEqual(guard.call_args[1]["doc"], "SINV-PERM-001")

	def test_customer_resync_checks_the_customer_before_acting(self):
		from taxjar_integration.taxjar_integration import taxjar_integration as mod

		with patch.object(mod.frappe, "has_permission", side_effect=frappe.PermissionError) as guard:
			with self.assertRaises(frappe.PermissionError):
				mod.resync_customer("CUST-PERM-001")
		self.assertEqual(guard.call_args[0][:2], ("Customer", "write"))
		self.assertEqual(guard.call_args[1]["doc"], "CUST-PERM-001")

	def test_bulk_actions_check_every_name_before_writing_any(self):
		"""A caller permitted on only part of the list gets a clean refusal
		rather than a half-applied bulk edit."""
		from taxjar_integration.taxjar_integration.page.taxjar_transactions import (
			taxjar_transactions as tx,
		)

		with patch.object(tx.frappe, "has_permission") as guard, patch.object(
			tx, "_taxjar_invoice_fields_ready", return_value=True
		), patch.object(tx.frappe.db, "set_value") as write:
			guard.side_effect = [None, frappe.PermissionError]
			with self.assertRaises(frappe.PermissionError):
				tx.bulk_retry(["SINV-A", "SINV-B"])

		write.assert_not_called()

	def test_settings_actions_that_call_taxjar_require_write(self):
		"""run_doc_method loads the doc with a read check; both of these then
		call TaxJar and save."""
		settings = frappe.get_doc("TaxJar Settings")
		for method in ("update_nexus_list", "refresh_product_tax_categories"):
			with patch.object(type(settings), "check_permission", side_effect=frappe.PermissionError) as guard:
				with self.assertRaises(frappe.PermissionError):
					getattr(settings, method)()
			self.assertEqual(guard.call_args[0][0], "write")


# ── Uninstall ────────────────────────────────────────────────────────────────


class TestUninstall(UnitTestCase):
	"""Removing the app has to hand the site back the way it was found.

	The tax templates are the part that actually hurts if this regresses: the
	site keeps defaulting sales transactions to a TaxJar template nothing
	populates, with ERPNext's own US templates disabled.
	"""

	MOD = "taxjar_integration.uninstall"

	def test_hooks_are_wired(self):
		from taxjar_integration import hooks

		self.assertEqual(hooks.before_uninstall, "taxjar_integration.uninstall.before_uninstall")
		self.assertEqual(hooks.after_uninstall, "taxjar_integration.uninstall.after_uninstall")

	def test_custom_field_removal_reads_the_same_list_install_writes(self):
		"""One source of truth - a field added to get_custom_fields() later is
		removed on uninstall without a second edit."""
		from taxjar_integration import uninstall
		from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
			get_custom_fields,
		)

		with patch(f"{self.MOD}.get_custom_fields", return_value={"Item": [{"fieldname": "x"}]}), patch(
			"frappe.custom.doctype.custom_field.custom_field.delete_custom_fields"
		) as deleter:
			uninstall.remove_custom_fields()

		deleter.assert_called_once_with({"Item": [{"fieldname": "x"}]})
		# and the real list is non-trivial, so the wiring above is worth having
		self.assertGreater(sum(len(v) for v in get_custom_fields().values()), 50)

	def test_property_setter_list_matches_what_install_creates(self):
		"""Scans the install source rather than restating the list, so a new
		make_property_setter() call cannot be added without this failing."""
		import ast
		import pathlib

		from taxjar_integration.uninstall import _PROPERTY_SETTERS

		src_path = (
			pathlib.Path(__file__).resolve().parent / "taxjar_settings.py"
		)
		tree = ast.parse(src_path.read_text())

		call_count = sum(
			1
			for node in ast.walk(tree)
			if isinstance(node, ast.Call)
			and getattr(node.func, "id", None) == "make_property_setter"
		)
		# Three call sites: one literal, two inside per-doctype loops.
		self.assertEqual(call_count, 3)
		# Which expand to eight setters across five doctypes.
		self.assertEqual(len(_PROPERTY_SETTERS), 8)
		self.assertEqual(len({dt for dt, _, _ in _PROPERTY_SETTERS}), 4)
		self.assertIn(("Sales Invoice", "return_against", "no_copy"), _PROPERTY_SETTERS)

	def test_property_setters_are_deleted_and_caches_cleared(self):
		from taxjar_integration import uninstall

		with patch(f"{self.MOD}.frappe.db.delete") as deleter, patch(
			f"{self.MOD}.frappe.clear_cache"
		) as clear:
			uninstall.remove_property_setters()

		self.assertEqual(deleter.call_count, len(uninstall._PROPERTY_SETTERS))
		self.assertEqual(
			deleter.call_args_list[0][0][1],
			{"doc_type": "Sales Invoice", "field_name": "return_against", "property": "no_copy"},
		)
		# Deleting the setter is enough - core's own no_copy=1 comes back from
		# the DocType JSON, so nothing should be writing a value back.
		self.assertEqual(clear.call_count, 4)

	def test_tax_templates_are_handed_back_to_erpnext(self):
		from taxjar_integration import uninstall

		with patch(f"{self.MOD}.frappe.db.exists", return_value=True), patch(
			f"{self.MOD}.frappe.get_all", return_value=["Test Co"]
		), patch(f"{self.MOD}.frappe.db.get_value") as getter, patch(
			f"{self.MOD}.frappe.db.set_value"
		) as setter:
			getter.side_effect = ["TC", "US-ST-6", "US-ST-4", "US-ST-625"]
			uninstall.restore_default_tax_templates()

		writes = [(c[0][1], c[0][2], c[0][3]) for c in setter.call_args_list]
		# Ours stops being the default...
		self.assertIn(("TaxJar Sales Tax - TC", "is_default", 0), writes)
		# ...and ERPNext's three come back off the disabled list.
		for name in ("US-ST-6", "US-ST-4", "US-ST-625"):
			self.assertIn((name, "disabled", 0), writes)

	def test_tax_template_restore_is_a_noop_without_the_config_doctype(self):
		"""after_uninstall ordering safety: if this ever ran once the app's own
		doctypes were gone, it must not explode."""
		from taxjar_integration import uninstall

		with patch(f"{self.MOD}.frappe.db.exists", return_value=False), patch(
			f"{self.MOD}.frappe.db.set_value"
		) as setter:
			uninstall.restore_default_tax_templates()

		setter.assert_not_called()

	def test_workspace_banner_is_removed(self):
		from taxjar_integration import uninstall
		from taxjar_integration.install import GUIDED_SETUP_ALERT_BLOCK

		with patch(f"{self.MOD}.frappe.db.exists", return_value=True), patch(
			f"{self.MOD}.frappe.delete_doc"
		) as deleter:
			uninstall.remove_guided_setup_alert()

		self.assertEqual(deleter.call_args[0][:2], ("Custom HTML Block", GUIDED_SETUP_ALERT_BLOCK))


# ── Company deletion ─────────────────────────────────────────────────────────


class TestCompanyDeletionHooks(UnitTestCase):

	def test_taxjar_config_survives_delete_company_transactions(self):
		"""Transaction Deletion Record collects every doctype with a Company
		link and deletes its rows. Its collector applies no istable filter, so
		the TaxJar Settings child tables are in scope - and deleting them would
		take the company's stored API credential with it. They are
		configuration, not transactions.
		"""
		from erpnext.setup.doctype.transaction_deletion_record.transaction_deletion_record import (
			get_doctypes_to_be_ignored,
		)

		ignored = get_doctypes_to_be_ignored()
		for doctype in ("TaxJar API Credential", "TaxJar Company Config", "TaxJar Nexus"):
			self.assertIn(doctype, ignored, f"{doctype} would be wiped by a company transaction delete")

	def test_company_delete_is_still_blocked_while_taxjar_is_configured(self):
		"""The opposite call: these rows are a deliberate configuration choice,
		so a Company delete should stop and name TaxJar Settings rather than
		silently orphan an encrypted credential. Asserted as the absence of an
		ignore_links_on_delete entry, since that is what would change it."""
		from taxjar_integration import hooks

		self.assertNotIn(
			"TaxJar Settings", getattr(hooks, "ignore_links_on_delete", [])
		)
