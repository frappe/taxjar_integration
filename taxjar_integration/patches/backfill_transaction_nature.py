import frappe
from frappe.query_builder.functions import Coalesce, NullIf

from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
	make_custom_fields,
)

# The one country the app treats as home. An address that names no country is
# domestic here, as it is in the hook.
_HOME_COUNTRY = "United States"


def execute():
	"""Fill taxjar_transaction_nature on every Sales Invoice that predates it.

	set_transaction_nature() writes the field on save, so only invoices written
	before this release hold a blank. Those are never saved again, and a blank
	keeps them out of the Transaction Sync page's Export filter for good.

	The work itself lives in backfill_if_needed(), which install.setup_taxjar()
	calls as well. A patch alone does not reach every site that needs it - see
	that function.
	"""
	# The field is created by make_custom_fields(), which this app runs from its
	# after_migrate hook - and after_migrate runs after patches. So on the
	# migrate that first ships this field the column does not exist yet, and a
	# patch that only checked for it would skip every row and still be recorded
	# as done, leaving the backfill to never happen at all.
	#
	# make_custom_fields() is idempotent and re-runs on every migrate anyway, so
	# asking for it early costs one extra pass and settles the order.
	if not frappe.db.has_column("Sales Invoice", "taxjar_transaction_nature"):
		make_custom_fields()

	backfill_if_needed()


def backfill_if_needed():
	"""Give every blank nature an answer. Safe to call as often as a caller likes.

	Called from the patch above, and from install.setup_taxjar(). Both are needed.
	Installing an app records every patch in patches.txt as done without running
	one (frappe/installer.py:380, set_all_patches_as_completed), so a site that
	already holds Sales Invoices when this app is installed never gets the patch.
	Its invoices are submitted and never saved again, so the validate hook never
	reaches them either, and their nature stays blank for good.

	Two statements rather than a loop over documents. The field is read-only and
	derived, nothing hooks its change, and a site can hold a very large number of
	invoices - loading each one to set one column would be a long migrate for no
	added correctness.
	"""
	# setup_taxjar() calls this on every migrate, and it runs before
	# make_custom_fields() has reached a site whose column is still missing.
	# Nothing to fill there, and the patch creates the column itself.
	if not frappe.db.has_column("Sales Invoice", "taxjar_transaction_nature"):
		return

	# The two statements below scan the table, so they run only when there is a
	# row to write. Every other migrate pays one indexed read instead.
	if not _has_blank_row():
		return

	# Order matters. The first statement claims the export rows, and the second
	# gives every row that is still blank the domestic answer.
	_export_query().run()
	_domestic_query().run()


def _has_blank_row():
	"""Whether any Sales Invoice still holds no nature.

	The column is tested directly, as IS NULL or the empty string, rather than
	through COALESCE. A function wrapped around a column cannot use that column's
	index, and this one is indexed - which is also why the two UPDATE statements
	below scan rather than seek, and why this read stands in front of them.

	A blank is stored as the empty string on every site I can read, and the
	column allows NULL, so both are asked for.
	"""
	sales_invoice = frappe.qb.DocType("Sales Invoice")

	return bool(
		frappe.qb.from_(sales_invoice)
		.select(sales_invoice.name)
		.where(
			sales_invoice.taxjar_transaction_nature.isnull()
			| (sales_invoice.taxjar_transaction_nature == "")
		)
		.limit(1)
		.run()
	)


def _destination_address(sales_invoice):
	"""Build the address term the whole app reads a sale's destination from.

	The destination is the shipping address where there is one and the billing
	address where there is not - see _destination_address() in
	taxjar_integration.py. Python falls back with ``or``, which treats an empty
	string as nothing, while COALESCE falls back only on NULL. An unset Link is
	stored as an empty string as often as it is stored as NULL, so NULLIF turns
	the empty string back into the NULL that COALESCE skips. Without it an
	invoice with an empty shipping address and a foreign billing address would
	be written Domestic here and read Export everywhere else.
	"""
	return Coalesce(
		NullIf(sales_invoice.shipping_address_name, ""),
		NullIf(sales_invoice.customer_address, ""),
	)


def _export_query():
	"""Build the UPDATE that writes Export on every invoice sent abroad.

	The query builder writes the statement, and this module assembles no SQL as
	a string. An UPDATE that joins a second table is written one way on MariaDB
	and another way on Postgres, so the Address rows are read with a subquery
	instead. A subquery is the same SQL on both.

	Returned rather than run, so a test can read the statement the patch would
	send without a database behind it.
	"""
	sales_invoice = frappe.qb.DocType("Sales Invoice")
	address = frappe.qb.DocType("Address")

	abroad = (
		frappe.qb.from_(address)
		.select(address.name)
		.where(Coalesce(address.country, "").notin(["", _HOME_COUNTRY]))
	)

	return (
		frappe.qb.update(sales_invoice)
		.set(sales_invoice.taxjar_transaction_nature, "Export")
		.where(_is_blank(sales_invoice) & _destination_address(sales_invoice).isin(abroad))
	)


def _domestic_query():
	"""Build the UPDATE that writes Domestic on every invoice left blank.

	It runs after the export statement, so the rows it still finds are the rows
	that are not exports. An invoice whose destination address is missing, empty
	or deleted lands here, which is the answer the hook gives it too.

	Returned rather than run, for the reason _export_query() gives.
	"""
	sales_invoice = frappe.qb.DocType("Sales Invoice")

	return (
		frappe.qb.update(sales_invoice)
		.set(sales_invoice.taxjar_transaction_nature, "Domestic")
		.where(_is_blank(sales_invoice))
	)


def _is_blank(sales_invoice):
	"""Test the rows the patch is allowed to write.

	Only rows that hold nothing yet. A submitted invoice keeps the nature it was
	sold under, even if the Address is corrected later.
	"""
	return Coalesce(sales_invoice.taxjar_transaction_nature, "") == ""
