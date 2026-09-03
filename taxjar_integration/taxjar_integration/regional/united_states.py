"""TaxJar-owned ledger auto-selection and Sales Taxes and Charges Template provisioning
for United States companies.

Reuses the standard US chart of accounts' own ``Sales Tax Payable`` (account_number
21400) and ``Shipping and Freight Income`` (41200) ledgers - never creates a new
Account. A company on a non-standard chart of accounts that lacks these lines simply
resolves to nothing here; the admin still picks a ledger by hand, same as before this
module existed.
"""

import frappe

from taxjar_integration.taxjar_integration.taxjar_integration import TAXJAR_ROW_DESCRIPTION

TAXJAR_TEMPLATE_TITLE = "TaxJar Sales Tax"
TAXJAR_SHIPPING_ROW_DESCRIPTION = "Shipping & Forwarding Charges"

# Exact literal titles ERPNext's own setup wizard seeds for US companies
# (erpnext/setup/setup_wizard/data/country_wise_tax.json). Only these are ever
# disabled - matched by title AND company, so a user's own custom templates
# (even if similarly named) are never touched.
_US_DEFAULT_TEMPLATE_TITLES = ("US ST 6%", "US ST 4%", "US ST 6.25%")

_STANDARD_LEDGERS = {
	"tax_account_head": ("21400", "Sales Tax Payable"),
	"shipping_account_head": ("41200", "Shipping and Freight Income"),
}


def resolve_default_ledgers(company):
	"""Look up the standard US CoA's Sales Tax Payable / Shipping and Freight Income
	ledgers for a company. Lookup by account_number first (survives renames), exact
	account_name second. Never creates an account; returns None for whatever isn't
	found on this company's chart of accounts."""
	resolved = {}
	for fieldname, (account_number, account_name) in _STANDARD_LEDGERS.items():
		resolved[fieldname] = (
			frappe.db.get_value("Account", {"company": company, "account_number": account_number})
			or frappe.db.get_value("Account", {"company": company, "account_name": account_name})
		)
	return resolved


def _taxjar_template_rows(tax_account_head, shipping_account_head, cost_center):
	"""The rows this template owns, in order.

	Both are "Actual" placeholders the user or TaxJar fills in later - the tax
	row is written by set_sales_tax() on save, and the shipping row is left for
	the user to type a delivery charge into. Templating shipping does not change
	how it is read: get_tax_data() still picks it up by matching account_head
	against the company's shipping ledger, whether the row came from here or the
	user added it by hand. It just saves adding that row on every transaction.
	"""
	rows = []

	# Shipping leads: it is the one the user types into, and sales tax is
	# calculated on the total that includes it, so the table reads in the order
	# the amounts actually happen.
	#
	# One ledger for both would make get_tax_data() read the sales tax back as a
	# shipping charge, and _remove_taxjar_rows() strip the user's shipping
	# amount along with the tax row. Better no row than a wrong one.
	if shipping_account_head and shipping_account_head != tax_account_head:
		rows.append(
			{
				"charge_type": "Actual",
				"account_head": shipping_account_head,
				"description": TAXJAR_SHIPPING_ROW_DESCRIPTION,
				"cost_center": cost_center,
			}
		)

	rows.append(
		{
			"charge_type": "Actual",
			"account_head": tax_account_head,
			"description": TAXJAR_ROW_DESCRIPTION,
			"cost_center": cost_center,
		}
	)

	return rows


def _order_template_rows(doc, rows):
	"""Put this template's own rows at the front, in the order given.

	Reconciling matches on description and updates in place, so a template that
	already had the tax row would otherwise keep it first for ever - existing
	installs need the order corrected, not just the new row appended. Rows the
	admin added themselves keep their relative order behind ours.
	"""
	ours = []
	for row_defaults in rows:
		match = next(
			(row for row in doc.taxes if row.get("description") == row_defaults["description"]),
			None,
		)
		if match is not None:
			ours.append(match)

	ours_ids = {id(row) for row in ours}
	ordered = ours + [row for row in doc.taxes if id(row) not in ours_ids]

	if [id(row) for row in ordered] == [id(row) for row in doc.taxes]:
		return False

	doc.taxes = ordered
	# The child table renders by idx, so the list order alone is not enough.
	for index, row in enumerate(ordered, start=1):
		row.set("idx", index)

	return True


def _upsert_tax_template(company, tax_account_head, shipping_account_head=None, is_default=False):
	"""Create or update the single TaxJar-owned Sales Taxes and Charges Template
	for this company: the tax/liability row, plus a shipping row when the
	company has a shipping ledger configured.

	is_default tracks the company's own "Calculate Sales Tax" flag rather than just
	ledger resolution succeeding - otherwise a company with tax calc off but ledgers
	resolved would have this template auto-copied onto every new transaction by
	ERPNext's own template machinery, with no code path to strip the resulting
	zero-amount placeholder row.
	"""
	abbr = frappe.db.get_value("Company", company, "abbr")
	name = f"{TAXJAR_TEMPLATE_TITLE} - {abbr}"
	cost_center = frappe.db.get_value("Company", company, "cost_center")

	rows = _taxjar_template_rows(tax_account_head, shipping_account_head, cost_center)

	if frappe.db.exists("Sales Taxes and Charges Template", name):
		doc = frappe.get_doc("Sales Taxes and Charges Template", name)
		dirty = False

		for row_defaults in rows:
			# Matched on description rather than position: the ledger on our own
			# row can change underneath us, rows are added over time as a company
			# gains a shipping ledger, and an admin may have added rows of their
			# own that must be left alone.
			existing = next(
				(row for row in doc.taxes if row.get("description") == row_defaults["description"]),
				None,
			)

			if existing is None:
				doc.append("taxes", row_defaults)
				dirty = True
				continue

			for field, value in row_defaults.items():
				if existing.get(field) != value:
					existing.set(field, value)
					dirty = True

		if _order_template_rows(doc, rows):
			dirty = True

		if bool(doc.is_default) != bool(is_default):
			doc.is_default = 1 if is_default else 0
			dirty = True

		if dirty:
			doc.save(ignore_permissions=True)
		return doc.name

	doc = frappe.get_doc(
		{
			"doctype": "Sales Taxes and Charges Template",
			"title": TAXJAR_TEMPLATE_TITLE,
			"company": company,
			"is_default": 1 if is_default else 0,
			"taxes": rows,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _disable_default_us_templates(company):
	"""Disable (never delete) ERPNext's own US ST 6%/4%/6.25% templates for this
	company, once TaxJar's own template has taken over as the active default.

	Uses a raw db.set_value rather than doc.save() - ERPNext's own
	validate_disabled() throws if is_default and disabled are both true on the
	same save, which a doc-level write could race depending on call order.
	"""
	for title in _US_DEFAULT_TEMPLATE_TITLES:
		existing = frappe.db.get_value(
			"Sales Taxes and Charges Template", {"title": title, "company": company}
		)
		if existing:
			frappe.db.set_value(
				"Sales Taxes and Charges Template", existing, {"is_default": 0, "disabled": 1}
			)


def ensure_company_ledgers_and_template(config_row):
	"""Backfill blank ledger fields on a TaxJar Company Config row from the standard
	CoA, then keep this company's TaxJar tax template in sync with the result.

	Never overwrites a ledger field that's already set - this is a lookup/reconcile
	step, not a provisioning step. Writes via frappe.db.set_value rather than
	settings.save(): both ledger fields are mandatory on the child doctype, so a
	doc-level save would trigger mandatory-field validation across every row in
	company_config, not just the one being backfilled.
	"""
	resolved = resolve_default_ledgers(config_row.company)

	updates = {
		field: resolved[field]
		for field in _STANDARD_LEDGERS
		if not getattr(config_row, field, None) and resolved.get(field)
	}
	if updates:
		frappe.db.set_value("TaxJar Company Config", config_row.name, updates)
		for field, value in updates.items():
			setattr(config_row, field, value)

	tax_account_head = config_row.tax_account_head
	if not tax_account_head:
		return

	is_default = bool(config_row.taxjar_calculate_tax)
	_upsert_tax_template(
		config_row.company,
		tax_account_head,
		shipping_account_head=config_row.shipping_account_head,
		is_default=is_default,
	)
	if is_default:
		_disable_default_us_templates(config_row.company)


def sync_all_company_tax_templates(rows=None):
	"""Reconcile every TaxJar Company Config row's ledgers and tax template.

	Shared entrypoint for both triggers: install.py's setup_taxjar() (bulk, on
	install/migrate) and TaxJarSettings.on_update()'s background safety net (a
	fresh read of the just-saved settings doc). Iterating zero rows (fresh
	install, nothing configured yet) is a true no-op.
	"""
	if rows is None:
		rows = frappe.get_single("TaxJar Settings").company_config or []

	for row in rows:
		ensure_company_ledgers_and_template(row)
