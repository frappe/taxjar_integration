import frappe
from frappe.query_builder.functions import Coalesce
from frappe.utils import now_datetime

from taxjar_integration.patches.mark_version_15_upgrade import is_version_15_upgrade
from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
	make_custom_fields,
)
from taxjar_integration.taxjar_integration.taxjar_integration import (
	CA_PROVINCE_NAMES,
	US_STATE_NAMES,
)

# ERPNext's checkbox carries no reason, and this app's field asks for one. The
# honest answer is the one that says no reason was ever recorded.
_EXEMPTION_TYPE = "Other"

# ERPNext's checkbox carries no region either. Version 15 exempted the customer
# everywhere, so the copy names every region the exemption dialog offers. This
# is the list "Select all" in that dialog writes.
_REGIONS = tuple(("US", code) for code in US_STATE_NAMES) + tuple(
	("CA", code) for code in CA_PROVINCE_NAMES
)

_REGION_DOCTYPE = "TaxJar Customer Exempt Region"
_REGION_FIELD = "taxjar_exempt_regions"


def execute():
	"""Copy ERPNext's exempt_from_sales_tax on Customer onto this app's fields.

	Version 15 of this app read that checkbox and charged no tax to the
	customer. Version 16 reads taxjar_exemption_type and taxjar_exempt_regions
	instead, and nothing reads the old checkbox. So a customer someone marked
	exempt before the upgrade would quietly go back to being taxed.

	Each customer with the old checkbox ticked and no exemption type of its own
	gets the type Other and every US state and Canadian province. A customer
	that already carries this app's own answer is left alone.

	Direct writes rather than a document save, for the reason the transaction patch
	gives. A save also runs on_customer_update, which enqueues a TaxJar sync per
	customer per company. The tax hook reads the exemption from these columns,
	so tax is right without the sync. The admin pushes the customers to TaxJar
	from the TaxJar Customers page.

	It runs only on the migrate that upgrades a site from version 15. A site
	already on version 16 also runs this patch once, on the migrate that ships
	it. By then the old checkbox is hidden and nothing reads it, so a tick on it
	is old data, and an admin may have set this customer's exemption since.
	"""
	if not is_version_15_upgrade():
		return

	_copy()


def _copy():
	# The columns come from make_custom_fields(), which after_migrate runs after
	# every patch. See backfill_transaction_nature for the same step.
	if not frappe.db.has_column("Customer", "taxjar_exemption_type"):
		make_custom_fields()

	# ERPNext adds its checkbox only once a company's country is the United
	# States. A site with no US company has no column to read.
	if not frappe.db.has_column("Customer", "exempt_from_sales_tax"):
		return

	customers = _customers_query().run(pluck=True)
	if not customers:
		return

	# A customer with no exemption type should hold no regions. Any row left
	# behind would sit next to the full list as a duplicate, so it goes first.
	_delete_regions_query(customers).run()
	frappe.db.bulk_insert(_REGION_DOCTYPE, _REGION_COLUMNS, _region_rows(customers))
	_set_type_query(customers).run()


def _customers_query():
	"""Build the SELECT for the customers to copy. Returned rather than run, so
	a test can read the statement."""
	customer = frappe.qb.DocType("Customer")
	return (
		frappe.qb.from_(customer)
		.select(customer.name)
		.where(
			(Coalesce(customer.exempt_from_sales_tax, 0) == 1)
			& (Coalesce(customer.taxjar_exemption_type, "") == "")
		)
	)


def _delete_regions_query(customers):
	region = frappe.qb.DocType(_REGION_DOCTYPE)
	return (
		frappe.qb.from_(region)
		.delete()
		.where(
			(region.parenttype == "Customer")
			& (region.parentfield == _REGION_FIELD)
			& region.parent.isin(customers)
		)
	)


def _set_type_query(customers):
	customer = frappe.qb.DocType("Customer")
	return (
		frappe.qb.update(customer)
		.set(customer.taxjar_exemption_type, _EXEMPTION_TYPE)
		.where(customer.name.isin(customers))
	)


_REGION_COLUMNS = (
	"name",
	"creation",
	"modified",
	"owner",
	"modified_by",
	"docstatus",
	"parent",
	"parenttype",
	"parentfield",
	"idx",
	"country",
	"state",
)


def _region_rows(customers):
	"""Yield one row for each customer and region, in the order of _REGION_COLUMNS."""
	now = now_datetime()
	for customer in customers:
		for idx, (country, state) in enumerate(_REGIONS, start=1):
			yield (
				frappe.generate_hash(length=10),
				now,
				now,
				"Administrator",
				"Administrator",
				0,
				customer,
				"Customer",
				_REGION_FIELD,
				idx,
				country,
				state,
			)
