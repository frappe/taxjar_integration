# Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import json
import os
import re
from pathlib import Path

_CODE_RE = re.compile(r"^[A-Z]{2}$")

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.model.document import Document
from frappe.permissions import add_permission, update_permission_property

import taxjar

from taxjar_integration.taxjar_integration.taxjar_integration import (
	SUPPORTED_STATE_CODES,
	_is_taxjar_enabled,
	get_client,
	log_taxjar_call,
	sanitize_error_response,
)


BASE_DIR = Path(__file__).resolve().parent
PRODUCT_TAX_CATEGORY_DATA_FILE = (BASE_DIR / "product_tax_category_data.json").resolve()


class TaxJarSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from taxjar_integration.taxjar_integration.doctype.taxjar_api_credential.taxjar_api_credential import TaxJarAPICredential
		from taxjar_integration.taxjar_integration.doctype.taxjar_company_config.taxjar_company_config import TaxJarCompanyConfig
		from taxjar_integration.taxjar_integration.doctype.taxjar_nexus.taxjar_nexus import TaxJarNexus

		api_mode: DF.Literal["", "Live", "Sandbox"]
		company_config: DF.Table[TaxJarCompanyConfig]
		enable_taxjar_logging: DF.Check
		log_retention_days: DF.Int
		nexus: DF.Table[TaxJarNexus]
		nexus_last_synced: DF.Datetime | None
		setup_complete: DF.Check
		table_hvjw: DF.Table[TaxJarAPICredential]
		taxjar_enabled: DF.Check
	# end: auto-generated types

	def on_update(self):
		features_enabled = _is_taxjar_enabled(self)

		# Custom fields, the Product Tax Category master and permissions are all set up
		# at install / migrate (see install.setup_taxjar). The single slow piece, the
		# live token check, runs in the background so it never blocks the save.
		if features_enabled and self.table_hvjw:
			frappe.enqueue(
				"taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings.validate_taxjar_tokens",
				user=frappe.session.user,
				queue="short",
				enqueue_after_commit=True,
				now=frappe.flags.in_test,
			)

		# Auto-fetch nexus when first configured: features on, company config present, nexus empty.
		if features_enabled and self.company_config and not self.nexus:
			frappe.enqueue(
				"taxjar_integration.taxjar_integration.tasks.sync_nexus_list",
				queue="short",
				enqueue_after_commit=True,
				now=frappe.flags.in_test,
			)

		# Safety net for ledger auto-fill + tax template sync: not gated on
		# features_enabled, since a company's ledgers/template should be ready
		# before the master switch flips on. Re-reads company_config fresh once the
		# job runs rather than passing rows through the queue (child-row objects
		# aren't safe to serialize across the RQ boundary). Idempotent per-row, so
		# repeated saves converge rather than re-doing work.
		if self.company_config:
			frappe.enqueue(
				"taxjar_integration.taxjar_integration.regional.united_states.sync_all_company_tax_templates",
				queue="short",
				enqueue_after_commit=True,
				now=frappe.flags.in_test,
			)

	def validate(self):
		if not _is_taxjar_enabled(self):
			return

		if not self.api_mode:
			frappe.throw(frappe._("Please select an API Mode before enabling features."))

		# Cheap, local credential-presence checks only. The live token check (an API
		# round-trip per credential) runs in the background via validate_taxjar_tokens
		# so it never blocks the save.
		if self.api_mode == "Sandbox":
			if not any(cred.sandbox_token for cred in (self.table_hvjw or [])):
				frappe.throw(frappe._("At least one Sandbox Token is required in API Credentials for Sandbox mode."))
		else:
			if not any(cred.live_token for cred in (self.table_hvjw or [])):
				frappe.throw(frappe._("At least one Live Token is required in API Credentials for Live mode."))

	@frappe.whitelist(methods=["POST"])
	def update_nexus_list(self):
		# run_doc_method only guarantees read on the way in, and this calls
		# TaxJar and then saves.
		self.check_permission("write")

		if not self.company_config:
			frappe.throw(frappe._("Please add at least one Company Configuration before updating Nexus list"))

		self.set("nexus", [])

		# Clears `nexus`; iterates `company_config`. Different tables.
		# nosemgrep: frappe-modifying-child-tables-while-iterating
		for config in self.company_config:
			client = get_client(config.company)
			if not client:
				frappe.msgprint(
					frappe._("Could not connect to TaxJar for company {0}. Skipping.").format(config.company)
				)
				continue

			try:
				log_taxjar_call(action="nexus_regions", status="request", context={"company": config.company})
				nexus = client.nexus_regions()
				log_taxjar_call(action="nexus_regions", status="success", response=nexus, context={"company": config.company})
			except taxjar.exceptions.TaxJarResponseError as e:
				log_taxjar_call(action="nexus_regions", status="error", error=str(e), context={"company": config.company})
				# One bad credential used to crash this loop for every company
				# with a raw 401 traceback (the guided setup's own Connect step
				# now requires every company to test successfully before this
				# step is reachable, but this doctype method is also called
				# directly - e.g. the "Update Nexus List" button on the TaxJar
				# Settings form, or the nightly sync_nexus_list job - so it
				# needs its own clear message rather than relying on that gate).
				full = getattr(e, "full_response", None) or {}
				status = full.get("status_code") if isinstance(full, dict) else None
				if status == 401:
					frappe.throw(
						frappe._(
							"TaxJar rejected the API credential for {0} (401 Unauthorized). "
							"Enter a correct API Token for {0} on the Connect step, or remove {0} "
							"from API Credentials, to continue."
						).format(config.company)
					)
				raise
			except Exception as e:
				log_taxjar_call(action="nexus_regions", status="error", error=str(e), context={"company": config.company})
				raise

			for address in nexus:
				region_code = (address.region_code or "").strip().upper()
				country_code = (address.country_code or "").strip().upper()
				if not _CODE_RE.match(region_code) or not _CODE_RE.match(country_code):
					continue
				self.append("nexus", {
					"company": config.company,
					"region": address.region,
					"region_code": region_code,
					"country": address.country,
					"country_code": country_code,
				})

		self.nexus_last_synced = frappe.utils.now()
		self.save()

	@frappe.whitelist()
	def get_product_tax_category_summary(self):
		"""Live count and most-recent modification time for Product Tax Category rows,
		rendered next to the "Nexus & Product Category" tab. Reads straight off the
		table rather than a separate tracking field, so it's correct whether rows came
		from the install-time seed or the weekly TaxJar sync (tasks.sync_product_tax_categories).
		"""
		return {
			"count": frappe.db.count("Product Tax Category"),
			"last_updated": frappe.db.get_value(
				"Product Tax Category", filters={}, fieldname="modified", order_by="modified desc"
			),
		}

	@frappe.whitelist(methods=["POST"])
	def refresh_product_tax_categories(self):
		"""Manual "Update Product Tax Category List" button: unlike the weekly
		scheduled job (which logs and moves on - see tasks.sync_product_tax_categories),
		this is user-triggered, so any TaxJar error should surface as a clear
		message rather than an unhandled exception. Categories aren't
		company-scoped, so any configured credential is enough - this doesn't gate
		on _is_taxjar_enabled()."""
		# Same reasoning as update_nexus_list: read perm gets you in here, but
		# this calls TaxJar and inserts Product Tax Category rows.
		self.check_permission("write")

		client = get_client()
		if not client:
			frappe.throw(frappe._("Could not connect to TaxJar. Check your API credentials."))

		try:
			fetch_and_insert_categories(client)
		except taxjar.exceptions.TaxJarConnectionError:
			frappe.throw(frappe._("TaxJar API is unreachable. Please try again later."))
		except taxjar.exceptions.TaxJarResponseError as err:
			full = getattr(err, "full_response", None) or {}
			status = full.get("status_code") if isinstance(full, dict) else None
			if status == 401:
				frappe.throw(frappe._("Invalid TaxJar API token. Please check your credentials."))
			frappe.throw(frappe._("Failed to fetch categories from TaxJar: {0}").format(sanitize_error_response(err)))

		return self.get_product_tax_category_summary()


def validate_taxjar_tokens(user=None):
	"""Background job: verify each TaxJar credential against a lightweight endpoint.

	Run from TaxJar Settings on_update so the save never waits on a network round
	trip. On an invalid (401) or unreachable credential it pushes a realtime alert
	to the user who saved the settings instead of blocking the save.
	"""
	settings = frappe.get_single("TaxJar Settings")

	for cred in settings.table_hvjw or []:
		company = cred.company
		try:
			client = get_client(company)
			if client:
				client.categories()
		except taxjar.exceptions.TaxJarResponseError as err:
			full = getattr(err, "full_response", None) or {}
			status = full.get("status_code") if isinstance(full, dict) else None
			if status == 401:
				_alert_token_issue(
					user,
					frappe._("Invalid TaxJar API token for company {0}. Please check your credentials.").format(company),
					indicator="red",
				)
		except taxjar.exceptions.TaxJarConnectionError:
			_alert_token_issue(
				user,
				frappe._("Could not reach TaxJar to verify credentials for {0}. Token not validated.").format(company),
				indicator="orange",
			)
		except Exception:
			pass


def _alert_token_issue(user, message, indicator):
	"""Push a desk alert about a credential problem to the saving user."""
	if not user:
		return
	frappe.publish_realtime(
		"msgprint",
		{"message": message, "title": frappe._("TaxJar"), "indicator": indicator, "alert": True},
		user=user,
	)


def add_product_tax_categories():
	if PRODUCT_TAX_CATEGORY_DATA_FILE.parent != BASE_DIR or not PRODUCT_TAX_CATEGORY_DATA_FILE.is_file():
		frappe.throw(frappe._("Product tax category fixture file is missing or invalid"))

	# nosemgrep: frappe-security-file-traversal - fixed local fixture path with validation.
	tax_categories = json.loads(PRODUCT_TAX_CATEGORY_DATA_FILE.read_text(encoding="utf-8"))
	create_tax_categories(tax_categories["categories"])


def create_tax_categories(data):
	for d in data:
		if not frappe.db.exists("Product Tax Category", {"product_tax_code": d.get("product_tax_code")}):
			tax_category = frappe.new_doc("Product Tax Category")
			tax_category.description = d.get("description")
			tax_category.product_tax_code = d.get("product_tax_code")
			tax_category.category_name = d.get("name")
			tax_category.db_insert()


def fetch_and_insert_categories(client):
	"""Pull TaxJar's current category list via the given client and insert any new
	ones. Shared by tasks.sync_product_tax_categories() (the weekly scheduled job)
	and TaxJarSettings.refresh_product_tax_categories() (the manual button) so the
	TaxJarCategory -> dict mapping only lives in one place.

	Logs the call via log_taxjar_call() same as every other TaxJar call site,
	then re-raises on error so each caller keeps its own presentation behaviour
	(the manual button throws a clear message; the scheduled job logs via
	frappe.log_error and moves on)."""
	try:
		log_taxjar_call(action="categories", status="request")
		categories = client.categories()
		log_taxjar_call(action="categories", status="success", response=categories)
	except Exception as err:
		log_taxjar_call(action="categories", status="error", error=str(err))
		raise

	create_tax_categories([
		{
			"product_tax_code": category.product_tax_code,
			"description": category.description,
			"name": category.name,
		}
		for category in categories
	])


# Single source of truth: the leading "" yields a blank first option in the Select.
_US_STATE_CODE_OPTIONS = "\n" + "\n".join(SUPPORTED_STATE_CODES)


def _make_status_fields(insert_after_tab, allow_on_submit=False):
	"""Return chained list of TaxJar status custom field dicts."""
	_fields = [
		("taxjar_has_nexus", "Check", None, "0"),
		("taxjar_nexus_reason", "Small Text", None, None),
		("taxjar_customer_taxable", "Check", None, "0"),
		("taxjar_customer_taxable_reason", "Small Text", None, None),
		("taxjar_product_taxable", "Select", None, None),
		("taxjar_product_taxable_reason", "Small Text", None, None),
		("taxjar_ship_from", "Small Text", None, None),
		("taxjar_ship_to", "Small Text", None, None),
		# TaxJar's own tax_source off the /v2/taxes response: "origin" or
		# "destination", null where there is no nexus to source anything from.
		# Per transaction, not per company - a handful of states are
		# origin-sourced for intrastate sales only, so the same customer can be
		# sourced either way depending on where the goods ship.
		("taxjar_tax_source", "Data", None, None),
		("taxjar_addresses_section", "Section Break", "Addresses", None),
		("taxjar_addresses_html", "HTML", None, None),
		("taxjar_status_section", "Section Break", "Tax Applicability Matrix", None),
		("taxjar_status_html", "HTML", None, None),
	]
	result = []
	prev = insert_after_tab
	for fieldname, fieldtype, label, default in _fields:
		d = dict(fieldname=fieldname, fieldtype=fieldtype, insert_after=prev)
		is_data = fieldtype in ("Check", "Data", "Small Text", "Select")
		if is_data:
			d["hidden"] = 1
			d["read_only"] = 1
		if label:
			d["label"] = label
		if default is not None:
			d["default"] = default
		if fieldtype == "Select" and fieldname == "taxjar_product_taxable":
			d["options"] = "\nYes\nNo\nPartially"
		if allow_on_submit:
			d["allow_on_submit"] = 1
		prev = fieldname
		result.append(d)
	return result


_TRANSACTION_BREAKDOWN_FIELDS = [
	dict(
		fieldname="taxjar_breakdown_section",
		fieldtype="Section Break",
		insert_after="other_charges_calculation",
		label="TaxJar Tax Breakdown",
		collapsible=1,
	),
	dict(
		fieldname="taxjar_breakdown_json",
		fieldtype="Long Text",
		insert_after="taxjar_breakdown_section",
		hidden=1,
		read_only=1,
	),
	dict(
		fieldname="taxjar_freight_taxable",
		fieldtype="Check",
		insert_after="taxjar_breakdown_json",
		label="Shipping Taxable (TaxJar)",
		hidden=1,
		read_only=1,
	),
	dict(
		# Plain HTML (not part of taxjar_breakdown_html) so it isn't wrapped in
		# the boxed "like-disabled-input" background a read-only Text Editor
		# field gets - that box is meant for the table, not this pill.
		fieldname="taxjar_freight_taxable_html",
		fieldtype="HTML",
		insert_after="taxjar_freight_taxable",
	),
	dict(
		fieldname="taxjar_breakdown_html",
		fieldtype="Text Editor",
		insert_after="taxjar_freight_taxable_html",
		is_virtual=1,
		read_only=1,
		allow_on_submit=1,
	),
]

def _item_tax_fields():
	"""Custom fields shared by the Sales Invoice / Quotation / Sales Order Item tables.

	Only fields the tax engine actually reads live here. Both are inputs to the
	TaxJar payload, not decoration:

	- product_tax_category feeds product_tax_code on every tax_for_order and
	  create_order call. It is read_only and fetched from the Item master: the
	  stored copy is what makes a retried sync (retry_failed_taxjar_syncs, days
	  after submit) send the category the tax was actually calculated with,
	  rather than whatever the Item says by then.
	- tax_collectable is read back as the per-line sales_tax on create_order
	  once the invoice is submitted (get_line_item_dict).

	Both are print_hide: a child field without it becomes a column in the item
	table of every printed document, which is how core ERPNext treats its own
	net_amount and item_tax_template. tax_collectable is also no_copy so a
	quotation's tax cannot ride into a sales order, invoice, or credit note as
	a stale figure the user cannot edit.
	"""
	return [
		dict(
			fieldname="product_tax_category",
			fieldtype="Link",
			insert_after="description",
			options="Product Tax Category",
			label="Product Tax Category",
			fetch_from="item_code.product_tax_category",
			read_only=1,
			print_hide=1,
		),
		dict(
			fieldname="tax_collectable",
			fieldtype="Currency",
			insert_after="net_amount",
			label="Tax Collectable",
			read_only=1,
			no_copy=1,
			print_hide=1,
			options="currency",
		),
	]


def _transaction_exemption_fields():
	"""Per-transaction TaxJar exemption override, in its own Details-tab section
	below Net Total. Previously the two fields were scattered - the checkbox
	after Shipping Rule, the reason Select after Incoterm - which put a question
	and its answer in different columns of an unrelated section.

	Unlike ERPNext's own regional exempt_from_sales_tax checkbox this replaces
	(see hide_legacy_exempt_from_sales_tax()), ticking this one does NOT skip
	the TaxJar API call - exemption_type is sent in the tax_for_order/
	create_order payload so TaxJar computes and records the exemption itself
	(see _get_effective_exemption() in taxjar_integration.py).
	"""
	return [
		dict(
			fieldname="taxjar_exemption_section",
			fieldtype="Section Break",
			insert_after="net_total",
			label="TaxJar Exemptions",
		),
		dict(
			fieldname="taxjar_transaction_exempt",
			fieldtype="Check",
			insert_after="taxjar_exemption_section",
			label="Is transaction exempt from sales tax?",
		),
		dict(
			fieldname="taxjar_transaction_exemption_type",
			fieldtype="Select",
			insert_after="taxjar_transaction_exempt",
			label="Reason for exemption?",
			options="\nWholesale\nGovernment\nOther",
			# Explicit == 1 rather than a bare truthiness check: an unset Check
			# reads back as undefined on a new doc, and "== 1" is unambiguous
			# about which value shows the field and makes it mandatory.
			depends_on="eval: doc.taxjar_transaction_exempt == 1",
			mandatory_depends_on="eval: doc.taxjar_transaction_exempt == 1",
		),
	]


def _marketplace_fields():
	"""Sales Invoice only: an invoice a marketplace already raised and priced,
	sent to ERPNext purely for the books.

	The two skip flags exist because such an invoice must not be re-priced or
	re-filed - the marketplace is the seller of record and has already collected
	and remitted the tax. Both are gated on the marketplace checkbox rather than
	standing alone, so they cannot be set on an ordinary invoice.

	Fields only, no behaviour: nothing reads these yet.
	"""
	is_marketplace = "eval: doc.taxjar_is_marketplace_invoice == 1"

	return [
		dict(
			fieldname="taxjar_marketplace_section",
			fieldtype="Section Break",
			insert_after="taxjar_status_html",
			label="Marketplace",
			description=(
				"Invoices which are already generated on marketplace & are sent "
				"to ERPNext for accounting"
			),
		),
		dict(
			fieldname="taxjar_is_marketplace_invoice",
			fieldtype="Check",
			insert_after="taxjar_marketplace_section",
			label="Is marketplace generated invoice?",
		),
		dict(
			fieldname="taxjar_marketplace_platform",
			fieldtype="Data",
			insert_after="taxjar_is_marketplace_invoice",
			label="Marketplace Platform Name",
			depends_on=is_marketplace,
			mandatory_depends_on=is_marketplace,
		),
		dict(
			fieldname="taxjar_marketplace_cb",
			fieldtype="Column Break",
			insert_after="taxjar_marketplace_platform",
		),
		dict(
			fieldname="taxjar_skip_tax_calculation",
			fieldtype="Check",
			insert_after="taxjar_marketplace_cb",
			label="Skip sales tax calculation?",
			depends_on=is_marketplace,
		),
		dict(
			fieldname="taxjar_skip_transaction_sync",
			fieldtype="Check",
			insert_after="taxjar_skip_tax_calculation",
			label="Skip sending transaction to TaxJar?",
			depends_on=is_marketplace,
		),
	]


def get_custom_fields():
	"""The app's custom fields, keyed by doctype.

	Split out from make_custom_fields() so uninstall.py can delete exactly
	what install created without keeping a second, drifting copy of the list.
	"""
	return {
		"Sales Invoice Item": _item_tax_fields(),
		"Quotation Item": _item_tax_fields(),
		"Sales Order Item": _item_tax_fields(),
		"Item": [
			dict(
				fieldname="product_tax_category",
				fieldtype="Link",
				insert_after="item_group",
				options="Product Tax Category",
				label="Product Tax Category",
				allow_in_quick_entry=1,
			)
		],
		"Quotation": [
			*_TRANSACTION_BREAKDOWN_FIELDS,
			*_transaction_exemption_fields(),
			dict(fieldname="taxjar_tab", fieldtype="Tab Break",
				insert_after="company_contact_person", label="TaxJar"),
			*_make_status_fields("taxjar_tab"),
		],
		"Sales Order": [
			*_TRANSACTION_BREAKDOWN_FIELDS,
			*_transaction_exemption_fields(),
			dict(fieldname="taxjar_tab", fieldtype="Tab Break",
				insert_after="company_contact_person", label="TaxJar"),
			*_make_status_fields("taxjar_tab"),
		],
		"Address": [
			dict(
				fieldname="taxjar_state_code",
				fieldtype="Select",
				insert_after="state",
				label="State Code (US)",
				description="2-letter US state code for TaxJar. Auto-populated when State is entered.",
				depends_on='eval: doc.country === "United States"',
				options=_US_STATE_CODE_OPTIONS,
			)
		],
		"Sales Invoice": [
			*[{**f, "allow_on_submit": 1} if f["fieldname"] in ("taxjar_breakdown_json", "taxjar_freight_taxable") else f
			  for f in _TRANSACTION_BREAKDOWN_FIELDS],
			*_transaction_exemption_fields(),
			dict(
				fieldname="taxjar_tab",
				fieldtype="Tab Break",
				insert_after="loyalty_amount",
				label="TaxJar",
			),
			*_make_status_fields("taxjar_tab", allow_on_submit=True),
			*_marketplace_fields(),
			dict(
				fieldname="taxjar_sync_section",
				fieldtype="Section Break",
				# Chained behind the marketplace section, which claims
				# taxjar_status_html - two fields cannot share one insert_after.
				insert_after="taxjar_skip_transaction_sync",
				label="Transaction Sync",
				allow_on_submit=1,
			),
			dict(
				# Draft docs never reach set_sales_tax's sync path (see
				# enqueue_taxjar_sync's on_submit hook) - showing the Sync Status
				# Select at its "Excluded" default there reads as "TaxJar
				# doesn't apply to this invoice" rather than "not submitted yet",
				# so this replaces the Select/Last Synced fields entirely while
				# a draft, same message the sidebar pill shows for consistency.
				fieldname="taxjar_sync_draft_message_html",
				fieldtype="HTML",
				insert_after="taxjar_sync_section",
				options='<p class="text-muted">TaxJar: Submit to sync</p>',
				depends_on="eval: doc.docstatus === 0",
			),
			dict(
				fieldname="taxjar_sync_status",
				fieldtype="Select",
				insert_after="taxjar_sync_draft_message_html",
				label="Sync Status",
				options="Excluded\nQueued\nSynced\nFailed",
				default="Excluded",
				allow_on_submit=1,
				in_list_view=1,
				read_only=1,
				depends_on="eval: doc.docstatus === 1",
			),
			dict(
				fieldname="taxjar_sync_error",
				fieldtype="Small Text",
				insert_after="taxjar_sync_status",
				label="Sync Error",
				read_only=1,
				allow_on_submit=1,
				depends_on="eval: doc.docstatus === 1 && doc.taxjar_sync_status == 'Failed'",
			),
			dict(
				fieldname="taxjar_last_synced",
				fieldtype="Datetime",
				insert_after="taxjar_sync_error",
				label="Last Synced",
				read_only=1,
				allow_on_submit=1,
				depends_on="eval: doc.docstatus === 1",
			),
			dict(
				# Set from classify_taxjar_error() when a sync fails, and read
				# only by retry_failed_taxjar_syncs() to decide what the 15-min
				# cron may re-send. Hidden: "we will try again" is already said
				# in Sync Error, in words, and a second half-explained checkbox
				# on the form would only invite people to tick it.
				fieldname="taxjar_sync_retryable",
				fieldtype="Check",
				insert_after="taxjar_last_synced",
				label="TaxJar Retry Pending",
				read_only=1,
				hidden=1,
				no_copy=1,
				allow_on_submit=1,
			),
			dict(
				# Consecutive Failed count, bumped by _set_sync_status() and reset
				# on any other status. retry_failed_taxjar_syncs() stops
				# re-enqueueing once this reaches TAXJAR_MAX_SYNC_RETRIES - the
				# Retry button on the Transactions page is unaffected. Hidden for
				# the same reason as taxjar_sync_retryable above.
				fieldname="taxjar_sync_retry_count",
				fieldtype="Int",
				insert_after="taxjar_sync_retryable",
				label="TaxJar Retry Count",
				default="0",
				read_only=1,
				hidden=1,
				no_copy=1,
				allow_on_submit=1,
			),
		],
		"Customer": [
			# ── TaxJar Tax Exemption (summary card + sync status) ──
			dict(
				fieldname="taxjar_section_break",
				fieldtype="Section Break",
				insert_after="tax_tab",
				label="TaxJar Tax Exemption",
				collapsible=0,
			),
			dict(
				fieldname="taxjar_exemption_summary_html",
				fieldtype="HTML",
				insert_after="taxjar_section_break",
			),
			dict(
				fieldname="taxjar_column_break",
				fieldtype="Column Break",
				insert_after="taxjar_exemption_summary_html",
			),
			dict(
				fieldname="taxjar_customer_sync_status",
				fieldtype="Select",
				insert_after="taxjar_column_break",
				label="TaxJar Sync Status",
				options="\nQueued\nSynced\nFailed",
				read_only=1,
			),
			dict(
				fieldname="taxjar_customer_sync_error",
				fieldtype="Small Text",
				insert_after="taxjar_customer_sync_status",
				label="TaxJar Sync Error",
				read_only=1,
				depends_on="eval: doc.taxjar_customer_sync_status == 'Failed'",
			),
			# ── TaxJar Tax Exemption Sync Details (collapsed by default) ───
			dict(
				fieldname="taxjar_sync_details_section",
				fieldtype="Section Break",
				insert_after="taxjar_customer_sync_error",
				label="TaxJar Sync Details",
				collapsible=1,
			),
			dict(
				fieldname="taxjar_customer_id",
				fieldtype="Data",
				insert_after="taxjar_sync_details_section",
				label="TaxJar Customer ID",
				read_only=1,
				description="",
			),
			dict(
				fieldname="taxjar_sync_details_cb",
				fieldtype="Column Break",
				insert_after="taxjar_customer_id",
			),
			dict(
				fieldname="taxjar_last_synced",
				fieldtype="Datetime",
				insert_after="taxjar_sync_details_cb",
				label="Last Synced to TaxJar",
				read_only=1,
			),
			# ── TaxJar Exemption Raw Data (hidden - backing fields for the
			# summary card + dialog above; configure_exemption is their only
			# write path) ───────────────────────────────────────────
			dict(
				fieldname="taxjar_raw_section",
				fieldtype="Section Break",
				insert_after="taxjar_last_synced",
				label="TaxJar Exemption Raw Data",
				collapsible=0,
			),
			dict(
				fieldname="taxjar_exemption_type",
				fieldtype="Select",
				insert_after="taxjar_raw_section",
				label="TaxJar Exemption Type",
				options="\nWholesale\nGovernment\nNon Exempt\nOther",
				hidden=1,
				description="",
			),
			dict(
				fieldname="taxjar_raw_column_break",
				fieldtype="Column Break",
				insert_after="taxjar_exemption_type",
			),
			dict(
				# Customer-side twin of taxjar_sync_retryable - see its comment.
				fieldname="taxjar_customer_sync_retryable",
				fieldtype="Check",
				insert_after="taxjar_raw_column_break",
				label="TaxJar Retry Pending",
				read_only=1,
				hidden=1,
				no_copy=1,
			),
			dict(
				fieldname="taxjar_exempt_regions",
				fieldtype="Table",
				insert_after="taxjar_customer_sync_retryable",
				label="Tax Exempt Regions",
				options="TaxJar Customer Exempt Region",
				depends_on="eval: doc.taxjar_exemption_type && doc.taxjar_exemption_type !== 'Non Exempt'",
				hidden=1,
				description="",
			),
			dict(
				# Customer-side twin of taxjar_sync_retry_count - see its comment.
				fieldname="taxjar_customer_sync_retry_count",
				fieldtype="Int",
				insert_after="taxjar_exempt_regions",
				label="TaxJar Retry Count",
				default="0",
				read_only=1,
				hidden=1,
				no_copy=1,
			),
		],
		# Print-time toggle for the "US Sales Tax Invoice" print format's
		# jurisdiction-by-jurisdiction breakdown table. Lives on Print Settings
		# rather than as a field on Sales Invoice itself, same convention
		# erpnext's own compact_item_print/print_taxes_with_zero_amount use
		# (erpnext.setup.install.create_print_setting_custom_fields) - it is a
		# print-run preference, not document data, and this way it shows up in
		# the print preview's Settings sidebar for free, with no client script.
		"Print Settings": [
			dict(
				fieldname="taxjar_show_tax_breakdown",
				fieldtype="Check",
				insert_after="print_taxes_with_zero_amount",
				label="Show Detailed TaxJar Tax Breakdown",
				default="1",
				description=(
					"Applies to print formats built for TaxJar, such as the US "
					"Sales Tax Invoice - includes the jurisdiction-by-jurisdiction "
					"tax breakdown table."
				),
			),
		],
	}


def make_custom_fields(update=True):
	create_custom_fields(get_custom_fields(), update=update)

	make_property_setter(
		"Sales Invoice", "return_against", "no_copy", "0", "Check",
		for_doctype=False,
	)

	_backfill_print_settings_defaults()


def _backfill_print_settings_defaults():
	"""A Check custom field's `default` only applies to a document created
	fresh via .new_doc() - Print Settings is a Single that already exists on
	every site (frappe creates it at site creation, long before this app is
	installed), so create_custom_fields() alone leaves
	taxjar_show_tax_breakdown reading back as unchecked forever, silently
	contradicting its declared default="1".

	Checked via a raw query against the Singles table, not get_single_value()/
	db.exists() - for a Check field, cast_fieldtype() maps a missing row to 0
	the same as an explicit 0, so get_single_value() can never tell "never
	set" apart from "someone unchecked it", and using it here would
	re-assert 1 over that choice on every migrate. db.exists() is no better:
	confirmed directly against this site that both it and db.get_value()
	raise/no-op on "Singles", since the QB builder's default order-by-creation
	assumes a real doctype table, and Singles has no such column. Only a plain
	SELECT against the row itself tells "never set" apart from "set to 0",
	so this backfills the very first time only and leaves any later value
	alone.
	"""
	row_exists = frappe.db.sql(
		"select 1 from `tabSingles` where doctype=%s and field=%s limit 1",
		("Print Settings", "taxjar_show_tax_breakdown"),
	)
	if not row_exists:
		frappe.db.set_single_value("Print Settings", "taxjar_show_tax_breakdown", 1)


_EXEMPT_FROM_SALES_TAX_DOCTYPES = ("Quotation", "Sales Order", "Sales Invoice", "Customer")


def hide_legacy_exempt_from_sales_tax():
	"""Hide ERPNext's own regional "exempt_from_sales_tax" checkbox (created by
	erpnext/regional/united_states/setup.py, not this app - it fires whenever a
	Company's country is United States, independent of TaxJar being installed).

	Customer exemption is now managed at the Customer master level
	(taxjar_exemption_type) and, per-transaction, via taxjar_transaction_exempt
	- both of which actually reach TaxJar's API, unlike this blunt local-only
	checkbox. The field itself is still read by check_sales_tax_exemption() as
	a safety net for any already-set old records; only hidden here so nobody
	sets it fresh once TaxJar is installed.

	Written unconditionally, without first checking that the column exists.
	ERPNext only adds the field once a Company's country is United States, so on
	a site where TaxJar is installed first there is nothing to hide yet - and
	skipping meant the checkbox turned up unhidden the moment a US company was
	created, and stayed that way until the next migrate. A Property Setter that
	names a field which does not exist is inert: apply_property_setters() matches
	on fieldname and skips whatever it cannot find (frappe/model/meta.py:441-445),
	so writing it up front simply takes effect once ERPNext creates the field.
	"""
	for doctype in _EXEMPT_FROM_SALES_TAX_DOCTYPES:
		make_property_setter(doctype, "exempt_from_sales_tax", "hidden", "1", "Check")


_TAXES_FIELD_DOCTYPES = ("Quotation", "Sales Order", "Sales Invoice")
_TAXES_FIELD_DESCRIPTION = "Please save to fetch sales tax from TaxJar."


def set_taxes_field_description():
	"""Hint on the native "taxes" (Sales Taxes and Charges) table field, so a
	freshly-defaulted TaxJar template row showing a $0 Actual amount doesn't
	read as broken - it's populated by set_sales_tax() on save, not on load."""
	for doctype in _TAXES_FIELD_DOCTYPES:
		make_property_setter(doctype, "taxes", "description", _TAXES_FIELD_DESCRIPTION, "Table")


def add_permissions():
	doctype = "Product Tax Category"
	for role in (
		"Accounts Manager",
		"Accounts User",
		"System Manager",
		"Item Manager",
		"Stock Manager",
	):
		if not frappe.db.exists("DocPerm", {"parent": doctype, "role": role, "permlevel": 0}):
			add_permission(doctype, role, 0)
		update_permission_property(doctype, role, 0, "write", 1)
		update_permission_property(doctype, role, 0, "create", 1)
