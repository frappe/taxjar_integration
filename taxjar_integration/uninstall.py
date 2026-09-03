"""Undo everything setup_taxjar() did to doctypes this app does not own.

Split across both hooks, and the order is load-bearing:

* ``before_uninstall`` runs while this app's doctypes still exist, so anything
  that has to *read* TaxJar Settings to know what to undo belongs here. The tax
  template reversal is the whole reason this module exists - see
  restore_default_tax_templates().
* ``after_uninstall`` runs once they are gone, and only touches core/ERPNext
  records: the custom fields, the property setters, and the workspace banner.

Deleting the app without this leaves a site whose sales transactions still
default to a TaxJar tax template that nothing populates any more, with
ERPNext's own US templates disabled and no code left to turn them back on.
"""

import frappe

from taxjar_integration.install import GUIDED_SETUP_ALERT_BLOCK
from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
	_EXEMPT_FROM_SALES_TAX_DOCTYPES,
	_TAXES_FIELD_DOCTYPES,
	get_custom_fields,
)
from taxjar_integration.taxjar_integration.regional.united_states import (
	_US_DEFAULT_TEMPLATE_TITLES,
	TAXJAR_TEMPLATE_TITLE,
)

# Every Property Setter make_custom_fields() and its two helpers create, as
# (doctype, fieldname, property). Deleting a Property Setter reverts the field
# to whatever the DocType JSON says, so nothing here needs to restore a value -
# core's own no_copy=1 on Sales Invoice.return_against comes back on its own.
_PROPERTY_SETTERS = [
	("Sales Invoice", "return_against", "no_copy"),
	*[(dt, "exempt_from_sales_tax", "hidden") for dt in _EXEMPT_FROM_SALES_TAX_DOCTYPES],
	*[(dt, "taxes", "description") for dt in _TAXES_FIELD_DOCTYPES],
]


def before_uninstall():
	restore_default_tax_templates()


def after_uninstall():
	remove_custom_fields()
	remove_property_setters()
	remove_guided_setup_alert()


def restore_default_tax_templates():
	"""Hand the Sales Taxes and Charges defaults back to ERPNext.

	_upsert_tax_template() made "TaxJar Sales Tax - {abbr}" the company default
	and _disable_default_us_templates() disabled ERPNext's own US ST 6% / 4% /
	6.25% for that company. Both have to be undone here, while TaxJar Settings
	still exists to say which companies were configured.

	The TaxJar templates themselves are left in place, only un-defaulted: they
	are ordinary ERPNext documents that may be referenced by historical
	transactions, and deleting them is not this app's call to make.

	Which of the US ST templates was default before TaxJar took over was never
	recorded, so they are re-enabled but not re-defaulted - the admin picks.
	"""
	if not frappe.db.exists("DocType", "TaxJar Company Config"):
		return

	companies = frappe.get_all("TaxJar Company Config", pluck="company", distinct=True)

	for company in companies:
		if not company:
			continue

		abbr = frappe.db.get_value("Company", company, "abbr")
		taxjar_template = f"{TAXJAR_TEMPLATE_TITLE} - {abbr}"
		if frappe.db.exists("Sales Taxes and Charges Template", taxjar_template):
			frappe.db.set_value(
				"Sales Taxes and Charges Template", taxjar_template, "is_default", 0
			)

		for title in _US_DEFAULT_TEMPLATE_TITLES:
			name = frappe.db.get_value(
				"Sales Taxes and Charges Template", {"title": title, "company": company}
			)
			if name:
				frappe.db.set_value("Sales Taxes and Charges Template", name, "disabled", 0)


def remove_custom_fields():
	"""Drop the taxjar_* fields from Sales Invoice, Quotation, Sales Order,
	their item tables, Customer, Item and Address.

	Reads the same dict install writes from, so a field added to
	get_custom_fields() later is removed here without a second edit. The
	underlying columns are left alone, matching the reasoning in
	patches/remove_item_breakdown_fields.py: deleting a Custom Field does not
	drop its column, and an unused column is cheaper to keep than a one-way DDL
	is to get wrong.
	"""
	from frappe.custom.doctype.custom_field.custom_field import delete_custom_fields

	delete_custom_fields(get_custom_fields())


def remove_property_setters():
	"""Un-hide ERPNext's own exempt_from_sales_tax checkbox, drop the hint on
	the taxes table, and restore no_copy on Sales Invoice.return_against."""
	for doctype, fieldname, prop in _PROPERTY_SETTERS:
		frappe.db.delete(
			"Property Setter",
			{"doc_type": doctype, "field_name": fieldname, "property": prop},
		)

	for doctype in {dt for dt, _, _ in _PROPERTY_SETTERS}:
		frappe.clear_cache(doctype=doctype)


def remove_guided_setup_alert():
	"""The workspace banner is a Custom HTML Block - a frappe doctype, so it
	outlives this app's own records and has to be deleted by name."""
	if frappe.db.exists("Custom HTML Block", GUIDED_SETUP_ALERT_BLOCK):
		frappe.delete_doc(
			"Custom HTML Block", GUIDED_SETUP_ALERT_BLOCK, ignore_missing=True, force=True
		)
