# Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import json
import os
import re
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

_CODE_RE = re.compile(r"^[A-Z]{2}$")

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.model.document import Document
from frappe.utils.file_lock import LockTimeoutError
from frappe.utils.synchronization import filelock

import taxjar

from taxjar_integration.taxjar_integration.taxjar_integration import (
	SUPPORTED_STATE_CODES,
	TRANSACTION_EXCLUSION_REASONS,
	TRANSACTION_NATURES,
	_is_taxjar_enabled,
	clear_company_config_cache,
	get_catalogue_client,
	get_client,
	log_taxjar_call,
	sanitize_error_response,
)


BASE_DIR = Path(__file__).resolve().parent
PRODUCT_TAX_CATEGORY_DATA_FILE = (BASE_DIR / "product_tax_category_data.json").resolve()

# One writer at a time on the TaxJar Settings Single. A Single is saved as a
# delete of all its rows in `tabSingles` followed by an insert of all of them
# again, so two saves in flight at once deadlock in the database rather than
# queue behind each other - the browser then shows "Deadlock Occurred".
#
# Two groups of callers meet here. The nexus sync rewrites the `nexus` table
# from the nightly sync_nexus_list job, from the auto-fetch enqueued when a
# company is first configured, and from the Fetch button on the guided setup /
# settings form. The guided setup writes the same Single on every step, and its
# Activate button (finish_setup) used to land on top of a running nexus fetch.
#
# Held per site, so a web worker and an RQ worker contend for the same lock.
SETTINGS_WRITE_LOCK = "taxjar_settings_write"


@contextmanager
def settings_write_lock():
	"""Serialise writes to TaxJar Settings. See SETTINGS_WRITE_LOCK.

	Read the document inside this lock, not before it. A writer that reads
	first and waits second saves a copy the winner has already replaced, and
	frappe then refuses that save on the modified timestamp - one error traded
	for another.
	"""
	try:
		with filelock(SETTINGS_WRITE_LOCK, timeout=60):
			yield
	except LockTimeoutError:
		frappe.throw(
			frappe._("Another TaxJar Settings update is already running. Please try again in a moment."),
			title=frappe._("TaxJar Settings Busy"),
		)


# Statuses that mean "this credential will not work", as opposed to a request
# TaxJar disliked. Both send the reader to the same place: the Connect step.
_CREDENTIAL_REJECTED_STATUSES = frozenset({401, 403})


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
		# This save is what changes the answer, so nothing later in the request
		# should still be reading the memo from before it.
		clear_company_config_cache()

		# A nexus refresh replaces the `nexus` table and stamps nexus_last_synced.
		# It changes no credential and no company config, so none of the three
		# jobs below have anything to react to - and enqueuing them would send
		# more writers at this same Single and its child tables while the
		# refresh's own transaction is still open. That is what surfaced in the
		# browser as "Deadlock Occurred" when a manual Fetch landed on top of
		# the background sync.
		if self.flags.nexus_sync:
			return

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

		# Auto-fetch nexus when first configured: features on, company config
		# present, and nexus never synced. Gated on the timestamp, not on an
		# empty `nexus` table: a TaxJar account with no nexus registered
		# legitimately syncs to zero rows, and "empty" would then re-enqueue the
		# job on the very save the job itself makes - a sync that never stops,
		# hammering TaxJar and rewriting this Single until someone notices.
		if features_enabled and self.company_config and not self.nexus_last_synced:
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

	def _validate_company_configuration(self):
		"""Every configured company must be one TaxJar can serve, with ledgers
		that are its own.

		Both halves were previously guarded only by a client-side link filter on
		the account fields, evaluated when the account is picked and never again.
		Change the company on a row afterwards and the previous company's ledgers
		stay behind - and _upsert_tax_template() then writes them into a Sales
		Taxes and Charges Template it marks default for the new company, so the
		mismatch surfaces later as ERPNext rejecting an unrelated invoice with a
		message that mentions neither TaxJar nor this row.

		Existence is deliberately not checked here: a Link pointing at nothing is
		frappe's own link validation to report, and duplicating it would only
		change which message the user sees. This checks the one thing frappe
		cannot know - that these two records belong together.
		"""
		for row in (self.company_config or []):
			self._validate_company_is_servable(row)
			for fieldname, label in (
				("tax_account_head", frappe._("Sales Tax Ledger Account")),
				("shipping_account_head", frappe._("Shipping Ledger Account")),
			):
				self._validate_account_belongs_to_company(row, fieldname, label)

		for row in (self.table_hvjw or []):
			self._validate_company_is_servable(row)

	def _validate_company_is_servable(self, row):
		"""TaxJar computes United States sales tax. A company registered anywhere
		else is not a company with the feature switched off, it is one the feature
		cannot serve - so it does not belong in this configuration at all."""
		if not row.company:
			return

		country = frappe.db.get_value("Company", row.company, "country")
		if not country or country == "United States":
			return

		frappe.throw(
			frappe._(
				"Row {0}: {1} is registered in {2}. TaxJar calculates United States "
				"sales tax only, so it cannot be configured for this company."
			).format(row.idx, frappe.bold(row.company), frappe.bold(country)),
			title=frappe._("Company Outside TaxJar's Remit"),
		)

	def _validate_account_belongs_to_company(self, row, fieldname, label):
		account = row.get(fieldname)
		if not account or not row.company:
			return

		details = frappe.db.get_value("Account", account, ["company", "is_group"], as_dict=True)
		if not details:
			return

		if details.company != row.company:
			frappe.throw(
				frappe._(
					"Row {0}: {1} {2} belongs to {3}, not to {4}. Pick a ledger from "
					"{4}'s own chart of accounts."
				).format(
					row.idx,
					label,
					frappe.bold(account),
					frappe.bold(details.company),
					frappe.bold(row.company),
				),
				title=frappe._("Ledger Belongs to Another Company"),
			)

		if details.is_group:
			frappe.throw(
				frappe._(
					"Row {0}: {1} {2} is a group account. Pick a single ledger to post to."
				).format(row.idx, label, frappe.bold(account)),
				title=frappe._("Group Account Selected"),
			)

	def validate(self):
		# Ahead of the feature gate on purpose. on_update syncs this company's tax
		# template whether or not any feature is on, so a broken row saved with
		# everything switched off still reaches _upsert_tax_template - and, from
		# after_migrate, still aborts a migrate.
		self._validate_company_configuration()

		if not _is_taxjar_enabled(self):
			return

		if not self.api_mode:
			frappe.throw(
				frappe._("Please select an API Mode before enabling features."),
				title=frappe._("API Mode Required"),
			)

		# Cheap, local credential-presence checks only. The live token check (an API
		# round-trip per credential) runs in the background via validate_taxjar_tokens
		# so it never blocks the save.
		if self.api_mode == "Sandbox":
			if not any(cred.sandbox_token for cred in (self.table_hvjw or [])):
				frappe.throw(
					frappe._("At least one Sandbox Token is required in API Credentials for Sandbox mode."),
					title=frappe._("Sandbox Token Required"),
				)
		else:
			if not any(cred.live_token for cred in (self.table_hvjw or [])):
				frappe.throw(
					frappe._("At least one Live Token is required in API Credentials for Live mode."),
					title=frappe._("Live Token Required"),
				)

	@frappe.whitelist(methods=["POST"])
	def update_nexus_list(self):
		# run_doc_method only guarantees read on the way in, and this calls
		# TaxJar and then saves.
		self.check_permission("write")

		if not self.company_config:
			frappe.throw(
				frappe._("Please add at least one Company Configuration before updating Nexus list"),
				title=frappe._("Company Configuration Required"),
			)

		# One writer at a time. Two syncs clear and re-insert the same child rows
		# under the same parent, in whatever order each transaction happens to
		# reach them, which is a deadlock waiting for the timing to line up - and
		# it did, for anyone who pressed Fetch while the background sync was
		# still running. This sync is the slow writer the guided setup's own
		# saves queue behind, so the lock is the doctype's, not this table's.
		with settings_write_lock():
			self._sync_nexus_from_taxjar()

	def _sync_nexus_from_taxjar(self):
		"""Replace `nexus` with what TaxJar reports for every configured company.

		Call only while holding NEXUS_SYNC_LOCK - update_nexus_list() is the
		entry point that takes it.
		"""
		# Whoever held the lock before this one may have saved while this one
		# waited for it, leaving this copy behind the database - save() would
		# then fail on the modified timestamp rather than on anything the user
		# did. Only reload when that actually happened: callers hand this method
		# a settings doc they may have changed in memory, and an unconditional
		# reload would throw those changes away.
		db_modified = frappe.db.get_single_value(self.doctype, "modified", cache=False)
		if db_modified != (frappe.utils.get_datetime(self.modified) if self.modified else None):
			self.reload()

		# Read before anything is cleared. A company this run cannot reach keeps
		# the rows it already had.
		#
		# The table used to be emptied here, up front. A company with no usable
		# credential - no row in API Credentials, or no token for the API mode
		# the site is in - then hit the `continue` below and was never written
		# back, so its nexus was deleted outright. check_for_nexus() reads this
		# table on every save, so every sale into a state that company is
		# registered in stopped collecting tax. The run went on to stamp
		# nexus_last_synced, and three screens reported a refresh that had not
		# happened for it. Switching the site between Live and Sandbox with a
		# token on file for only some companies is enough to cause it.
		#
		# The 401/403 and the re-raise paths below never reached the save at
		# all, so they lost nothing. This one did.
		existing_by_company = {}
		for row in (self.nexus or []):
			existing_by_company.setdefault(row.company, []).append({
				"company": row.company,
				"region": row.region,
				"region_code": row.region_code,
				"country": row.country,
				"country_code": row.country_code,
			})

		refreshed = {}
		skipped = []

		for config in self.company_config:
			client = get_client(config.company)
			if not client:
				skipped.append(config.company)
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
				# 401 and 403 are one problem to the person reading this: the
				# credential on file does not work. TaxJar sends 403 ("Not
				# authorized for resource") for a token its account will not
				# serve, and used to reach here as a ValueError rather than as
				# this error at all - see _taxjar_responder().
				if status in _CREDENTIAL_REJECTED_STATUSES:
					frappe.throw(
						frappe._(
							"TaxJar rejected the API credential for {0} (HTTP {1}). "
							"Enter a correct API Token for {0} on the Connect step, or remove {0} "
							"from API Credentials, to continue."
						).format(config.company, status),
						title=frappe._("TaxJar Rejected the API Token"),
					)
				raise
			except Exception as e:
				log_taxjar_call(action="nexus_regions", status="error", error=str(e), context={"company": config.company})
				raise

			rows = []
			for address in nexus:
				region_code = (address.region_code or "").strip().upper()
				country_code = (address.country_code or "").strip().upper()
				if not _CODE_RE.match(region_code) or not _CODE_RE.match(country_code):
					continue
				rows.append({
					"company": config.company,
					"region": address.region,
					"region_code": region_code,
					"country": address.country,
					"country_code": country_code,
				})

			# An account registered nowhere answers with no regions, and that is
			# a real answer. It replaces what was there.
			refreshed[config.company] = rows

		# Rebuilt in company_config order, so the grouping the screens render
		# reads the same as before. A company no longer configured is in neither
		# map, so its rows drop, exactly as the old clear-everything did.
		self.set("nexus", [
			row
			for config in self.company_config
			for row in refreshed.get(config.company, existing_by_company.get(config.company, []))
		])

		# Only when every configured company answered. A partial run leaves the
		# previous timestamp, which is still true of every row now in the table -
		# rather than claiming a refresh for a company that never got one.
		# Read by sync_nexus_list, which tells the people who can fix it. A skip
		# is silent otherwise: the msgprint below reaches nobody in a scheduled
		# job, and the timestamp deliberately does not move, so the three
		# screens that show it just go on showing an older date.
		self.flags.nexus_sync_skipped = skipped

		if not skipped:
			self.nexus_last_synced = frappe.utils.now()
		# Read by on_update: this save carries nexus, and nothing the credential
		# check or the tax template sync would need to run again for.
		self.flags.nexus_sync = True
		self.save()

	@frappe.whitelist()
	def get_product_tax_category_summary(self):
		"""Live count and last-fetched time for Product Tax Category rows, rendered
		on the "Nexus & Product Category" tab and the page of the same name.

		`last_updated` is when the list last came from TaxJar (stamped by
		fetch_and_insert_categories), falling back to the most recently modified
		row for a site whose categories predate that stamp - the install-time
		seed, or any sync before this field existed. Read from the database, not
		off `self`, so a summary returned right after a fetch reflects it.
		"""
		last_synced = frappe.db.get_single_value(
			"TaxJar Settings", "product_tax_categories_last_synced"
		)
		# An unwritten Datetime single comes back as datetime.min, not None -
		# get_single_value() casts through get_datetime(None) (database.py) - so
		# a plain truthiness check would never reach the fallback.
		if last_synced == datetime.min:
			last_synced = None

		return {
			"count": frappe.db.count("Product Tax Category"),
			"last_updated": last_synced or frappe.db.get_value(
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

		client = get_catalogue_client()
		if not client:
			frappe.throw(
				frappe._("Could not connect to TaxJar. Check your API credentials."),
				title=frappe._("TaxJar Connection Failed"),
			)

		try:
			fetch_and_insert_categories(client)
		except taxjar.exceptions.TaxJarConnectionError:
			frappe.throw(
				frappe._("TaxJar API is unreachable. Please try again later."),
				title=frappe._("TaxJar Unreachable"),
			)
		except taxjar.exceptions.TaxJarResponseError as err:
			full = getattr(err, "full_response", None) or {}
			status = full.get("status_code") if isinstance(full, dict) else None
			if status == 401:
				frappe.throw(
					frappe._("Invalid TaxJar API token. Please check your credentials."),
					title=frappe._("Invalid TaxJar API Token"),
				)
			frappe.throw(
				frappe._("Failed to fetch categories from TaxJar: {0}").format(sanitize_error_response(err)),
				title=frappe._("Product Tax Category Refresh Failed"),
			)

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
		frappe.throw(
			frappe._("Product tax category fixture file is missing or invalid"),
			title=frappe._("Product Tax Category Data Missing"),
		)

	# nosemgrep: frappe-security-file-traversal - fixed local fixture path with validation.
	tax_categories = json.loads(PRODUCT_TAX_CATEGORY_DATA_FILE.read_text(encoding="utf-8"))
	create_tax_categories(tax_categories["categories"])


def create_tax_categories(data):
	"""Insert each category whose product_tax_code is not here yet.

	The existing codes are read once, not once per row. The list is about 800
	rows, and it runs at install, on the manual button and every week, so a
	query per row was about 800 round trips even when nothing was new. The set
	also takes each code this loop inserts, so a code listed twice goes in once.

	db_insert(), not insert(): insert() validates every row, so one fixture row
	longer than its field would fail an install or migrate that passes today.
	"""
	existing = set(frappe.get_all("Product Tax Category", pluck="product_tax_code"))
	for d in data:
		code = d.get("product_tax_code")
		if code in existing:
			continue
		tax_category = frappe.new_doc("Product Tax Category")
		tax_category.description = d.get("description")
		tax_category.product_tax_code = code
		tax_category.category_name = d.get("name")
		tax_category.db_insert()
		existing.add(code)


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

	# create_tax_categories() only inserts codes that are missing, so a fetch
	# that finds nothing new leaves every row's `modified` untouched - which is
	# why "when did this list last come from TaxJar" needs recording separately
	# rather than being read back off the rows. Stamped here rather than in
	# either caller so the weekly job and the manual button can't disagree.
	frappe.db.set_single_value(
		"TaxJar Settings", "product_tax_categories_last_synced", frappe.utils.now()
	)


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
		if fieldname == "taxjar_addresses_section":
			# Neither address is stored until set_sales_tax has run, and it never
			# does for a company outside the United States or one with sales tax
			# calculation switched off. An "Addresses" heading announcing nothing
			# is worse than no section at all.
			#
			# Declared here rather than hidden from render_addresses: a section
			# hidden by hand is re-shown by the next Section.refresh(), which
			# recomputes visibility from df.hidden and hidden_due_to_dependency
			# alone and knows nothing of a hide() called in between - and
			# refresh_sections() then marks the section visible because the HTML
			# control inside it is still there, merely emptied. Expressed as a
			# dependency, frappe owns the answer and keeps it across every refresh.
			#
			# Deliberately not the treatment the Tax Applicability Matrix gets: that
			# one stays and says why it is empty (see _render_empty_status), because
			# it has an answer worth reading. An absent address pair does not.
			d["depends_on"] = "eval: doc.taxjar_ship_from || doc.taxjar_ship_to"
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

	- taxjar_product_tax_category feeds product_tax_code on every tax_for_order
	  and create_order call. It is read_only and fetched from the Item master:
	  the stored copy is what makes a retried sync (retry_failed_taxjar_syncs,
	  days after submit) send the category the tax was actually calculated with,
	  rather than whatever the Item says by then.
	- taxjar_tax_collectable is read back as the per-line sales_tax on
	  create_order once the invoice is submitted (get_line_item_dict).

	Both carry the taxjar_ prefix every other field this app owns carries. They
	sit on child tables this app does not own, so an unprefixed name is a name
	a second tax app can claim for a different meaning. The prefix also tells
	the two apart from the TaxJar SDK's own tax_collectable response attribute,
	which set_sales_tax reads two lines away from where it writes ours.

	Both are print_hide: a child field without it becomes a column in the item
	table of every printed document, which is how core ERPNext treats its own
	net_amount and item_tax_template. taxjar_tax_collectable is also no_copy so
	a quotation's tax cannot ride into a sales order, invoice, or credit note as
	a stale figure the user cannot edit.
	"""
	return [
		dict(
			fieldname="taxjar_product_tax_category",
			fieldtype="Link",
			insert_after="description",
			options="Product Tax Category",
			label="Product Tax Category",
			fetch_from="item_code.taxjar_product_tax_category",
			read_only=1,
			print_hide=1,
		),
		dict(
			fieldname="taxjar_tax_collectable",
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

	This replaces ERPNext's own regional exempt_from_sales_tax checkbox (see
	hide_legacy_exempt_from_sales_tax()). Ticking it does not skip the TaxJar
	API call - exemption_type is sent in the tax_for_order/create_order payload
	so TaxJar computes and records the exemption itself (see
	_get_effective_exemption() in taxjar_integration.py).
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
				fieldname="taxjar_product_tax_category",
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
			),
			dict(
				# The same answer for everywhere else, and a separate field
				# because the one above is a Select of the fifty states - it can
				# hold nothing else, which is right for a domestic sale and
				# leaves an export with nowhere to put its region.
				#
				# Data, not Select: ISO 3166-2 lists thousands of regions across
				# 250 countries, and the code is usually worked out from the
				# state name rather than picked. This is where the answer goes
				# when it cannot be - see UNKNOWN_REGION_CODE.
				fieldname="taxjar_region_code",
				fieldtype="Data",
				insert_after="taxjar_state_code",
				label="Region Code (ISO 3166-2)",
				description=(
					"Region code sent to TaxJar for a sale delivered outside the "
					"United States. Worked out from State where it can be."
				),
				depends_on='eval: doc.country && doc.country !== "United States"',
				length=10,
			),
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
			dict(
				# Draft docs never reach set_sales_tax's sync path (see
				# enqueue_taxjar_sync's on_submit hook), so there is no sync
				# state to report yet and every field in here is hidden - the
				# section itself goes with them rather than standing empty
				# above a "submit to sync" placeholder. The sidebar pill still
				# says so for a draft.
				fieldname="taxjar_sync_section",
				fieldtype="Section Break",
				insert_after="taxjar_status_html",
				label="Transaction Sync",
				allow_on_submit=1,
				depends_on="eval: doc.docstatus !== 0",
			),
			dict(
				# Indexed, along with taxjar_sync_retryable and
				# taxjar_sync_retry_count below: retry_failed_taxjar_syncs runs
				# every 15 minutes and filters Sales Invoice on all three, and the
				# Transaction Sync page filters and COUNTs on this one for every
				# tab and every summary refresh. Unindexed those are repeated full
				# scans of the largest table on the site. Declared here rather than
				# added by hand because make_custom_fields() re-runs on every
				# migrate - an index applied ad-hoc is an index that disappears.
				fieldname="taxjar_sync_status",
				fieldtype="Select",
				insert_after="taxjar_sync_section",
				label="Sync Status",
				options="Excluded\nQueued\nSynced\nFailed",
				default="Excluded",
				search_index=1,
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
				# Why a submitted document was kept out of TaxJar. Only ever set
				# alongside the Excluded status, and cleared by every other status
				# (see _sync_status_fields), so it cannot outlive the state it
				# explains. The leading "" yields a blank first option, which is what
				# a row written before the reason was recorded holds.
				fieldname="taxjar_exclusion_reason",
				fieldtype="Select",
				insert_after="taxjar_sync_error",
				label="Exclusion Reason",
				options="\n" + "\n".join(TRANSACTION_EXCLUSION_REASONS),
				read_only=1,
				allow_on_submit=1,
				depends_on="eval: doc.docstatus === 1 && doc.taxjar_sync_status == 'Excluded'",
			),
			dict(
				# Export or Domestic, written on every save by
				# set_transaction_nature(). Indexed because the Transaction Sync
				# page filters and COUNTs on it for every tab, the same reason
				# taxjar_sync_status above is indexed.
				#
				# Hidden: the form already says an export is an export, in the
				# tax message strip and in the sidebar pill, and both say it
				# before the first save. This field exists so the Transaction
				# Sync page can filter on one indexed column instead of asking
				# the database for every invoice with a foreign destination.
				#
				# The leading "" yields a blank first option, which is what a row
				# written before this field existed holds until the backfill
				# patch runs.
				fieldname="taxjar_transaction_nature",
				fieldtype="Select",
				insert_after="taxjar_exclusion_reason",
				label="Transaction Nature",
				options="\n" + "\n".join(TRANSACTION_NATURES),
				search_index=1,
				read_only=1,
				hidden=1,
				allow_on_submit=1,
			),
			dict(
				fieldname="taxjar_last_synced",
				fieldtype="Datetime",
				insert_after="taxjar_transaction_nature",
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
				search_index=1,
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
				search_index=1,
				read_only=1,
				hidden=1,
				no_copy=1,
				allow_on_submit=1,
			),
		],
		"Customer": [
			# ── TaxJar Tax Exemption ──
			# One field, the whole width of the section. The summary card that
			# renders into it is a card: it draws its own bordered box when an
			# exemption exists, and frappe's empty state - icon, sentence, two
			# actions - when none does. Both want the full column. Sharing the
			# section with the sync fields squeezed the card into half of it and
			# left the empty state's centred actions crowded against the edge.
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
			# ── TaxJar Sync Details (collapsed by default) ───────────────
			# Everything about the last sync, in one place: what it did, what
			# went wrong, which record it wrote, and when. Sync Status used to
			# sit beside the card in the section above, which put the reading
			# ("Queued") next to the exemption rather than next to the rest of
			# the sync it belongs to.
			dict(
				fieldname="taxjar_sync_details_section",
				fieldtype="Section Break",
				insert_after="taxjar_exemption_summary_html",
				label="TaxJar Sync Details",
				collapsible=1,
			),
			dict(
				fieldname="taxjar_customer_sync_status",
				fieldtype="Select",
				insert_after="taxjar_sync_details_section",
				label="TaxJar Sync Status",
				options="\nQueued\nSynced\nFailed",
				search_index=1,
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
			dict(
				# When this customer entered the sync queue, set by
				# _customer_sync_status_fields() and cleared on any other
				# status. recover_stuck_customer_syncs() reads it to tell a
				# sync that is in flight apart from one whose job never ran -
				# taxjar_customer_sync_status says "Queued" for both, and
				# before this field existed, the second kind sat there for
				# good. Hidden for the same reason as the retry fields on
				# Sales Invoice: it is machinery, not an answer.
				fieldname="taxjar_customer_sync_queued_at",
				fieldtype="Datetime",
				insert_after="taxjar_customer_sync_error",
				label="TaxJar Queued At",
				search_index=1,
				read_only=1,
				hidden=1,
				no_copy=1,
			),
			dict(
				# The companies whose TaxJar account must still lose this
				# customer, one per line. A save that takes a company off the
				# allowed list adds it, and the removal job takes it out when
				# the DELETE is done. retry_pending_customer_removals() queues
				# again whatever is left. Hidden: it is machinery.
				fieldname="taxjar_customer_pending_removals",
				fieldtype="Small Text",
				insert_after="taxjar_customer_sync_queued_at",
				label="TaxJar Pending Removals",
				read_only=1,
				hidden=1,
				no_copy=1,
			),
			dict(
				fieldname="taxjar_sync_details_cb",
				fieldtype="Column Break",
				insert_after="taxjar_customer_pending_removals",
			),
			dict(
				fieldname="taxjar_customer_id",
				fieldtype="Data",
				insert_after="taxjar_sync_details_cb",
				label="TaxJar Customer ID",
				read_only=1,
				description="",
			),
			dict(
				fieldname="taxjar_last_synced",
				fieldtype="Datetime",
				insert_after="taxjar_customer_id",
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
	}


def make_custom_fields(update=True):
	create_custom_fields(get_custom_fields(), update=update)

	make_property_setter(
		"Sales Invoice", "return_against", "no_copy", "0", "Check",
		for_doctype=False,
	)


_EXEMPT_FROM_SALES_TAX_DOCTYPES = ("Quotation", "Sales Order", "Sales Invoice", "Customer")


def hide_legacy_exempt_from_sales_tax():
	"""Hide ERPNext's own regional "exempt_from_sales_tax" checkbox (created by
	erpnext/regional/united_states/setup.py, not this app - it fires whenever a
	Company's country is United States, independent of TaxJar being installed).

	Customer exemption is now managed at the Customer master level
	(taxjar_exemption_type) and, per-transaction, via taxjar_transaction_exempt
	- both of which actually reach TaxJar's API, unlike this blunt local-only
	checkbox. Nothing in this app reads it. It is hidden so nobody ticks a box
	that no longer does anything.

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
