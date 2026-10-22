import frappe

# Every (doctype, old fieldname, new fieldname) this patch moves. These are the
# only two unprefixed fields any released version of this app ever created, and
# it created them on these two doctypes alone. Sales Invoice Item carries both;
# the Item master carries only the category the child rows fetch from.
_RENAMES = (
	("Sales Invoice Item", "product_tax_category", "taxjar_product_tax_category"),
	("Sales Invoice Item", "tax_collectable", "taxjar_tax_collectable"),
	("Item", "product_tax_category", "taxjar_product_tax_category"),
)

# The tables the copy writes to, in the order _RENAMES names them. Read off
# _RENAMES rather than written out a second time, so a rename added above
# cannot name a table the copy then skips.
_COPY_DOCTYPES = tuple(dict.fromkeys(doctype for doctype, _old, _new in _RENAMES))


def execute():
	"""Move the app's two unprefixed item fields into the taxjar_ namespace.

	product_tax_category and tax_collectable were the only custom fields this
	app created without its own prefix, and tax_collectable sits on a child
	table the app does not own. An unprefixed name on a shared table is a name
	a second tax app can claim for a different meaning, and nothing warns either
	app. The prefix also tells our field apart from the SDK's own tax_collectable
	response attribute, which set_sales_tax reads two lines from where it
	writes ours.

	The steps, in order:

	1. Create the new fields. make_custom_fields() is idempotent and creates
	   each column as a side effect of inserting its Custom Field. It cannot be
	   left to after_migrate: that hook runs after every patch, and the copy
	   below needs the new columns to already exist.
	2. Copy each old column into its new one, one UPDATE per table.
	3. Delete the old Custom Field records.

	Copied with the query builder, not with the document API: tax_collectable
	lives on submitted Sales Invoice Items, so a doc.save() migration fights
	docstatus validation for a read-only value no user typed and no user can
	edit. The copy moves that value unchanged, so there is nothing for the
	Sales Invoice controller to revalidate.

	The old columns stay. Deleting a Custom Field does not drop its column, and
	an unused column is cheaper to keep than a one-way DDL is to get wrong.
	Keeping them also makes the copy re-runnable.

	Each table is guarded on its columns. A site that installed the app but
	never enabled a TaxJar feature has no such columns at all, and reading one
	would raise MySQLdb (1054) Unknown column.
	"""
	from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
		make_custom_fields,
	)

	make_custom_fields()

	for doctype in _COPY_DOCTYPES:
		if _columns_ready(doctype):
			_copy_query(doctype).run()

	_drop_old_fields()


def _copy_query(doctype):
	"""Build the one UPDATE that copies a table's old columns into its new ones.

	frappe.qb, not frappe.db.sql: the builder writes the same statement, quotes
	each name for the database in use, and leaves nothing for this module to
	assemble as a string. It also stays below the document API, which is what
	execute() needs - see its docstring for why a doc.save() cannot do this.

	Returned rather than run, so a test can read the statement the patch would
	send without a database behind it.
	"""
	table = frappe.qb.DocType(doctype)
	query = frappe.qb.update(table)
	rows_to_copy = None

	for dt, old, new in _RENAMES:
		if dt != doctype:
			continue
		query = query.set(table[new], table[old])
		# One row is worth copying if any old column on it holds a value.
		carries_a_value = table[old].isnotnull()
		rows_to_copy = carries_a_value if rows_to_copy is None else rows_to_copy | carries_a_value

	return query.where(rows_to_copy)


def _columns_ready(doctype):
	"""Report whether every column one table's UPDATE names already exists.

	Both the old and the new column are checked. The old one can be absent on a
	site that never enabled a TaxJar feature. The new one can be absent if
	make_custom_fields() skipped the doctype, which happens when the doctype
	itself is not installed.
	"""
	for dt, old, new in _RENAMES:
		if dt != doctype:
			continue
		if not frappe.db.has_column(dt, old) or not frappe.db.has_column(dt, new):
			return False
	return True


def _drop_old_fields():
	"""Delete the old Custom Field records and clear each doctype's cache.

	Removing them from make_custom_fields() only stops them being recreated.
	after_migrate re-runs that function but never deletes what it no longer
	lists, so a migrated site would show the old field beside the new one on
	every item row.
	"""
	for doctype, old, _new in _RENAMES:
		name = f"{doctype}-{old}"
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, ignore_missing=True)

	for doctype in _COPY_DOCTYPES:
		frappe.clear_cache(doctype=doctype)
