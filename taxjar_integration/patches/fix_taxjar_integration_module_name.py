import frappe


def execute():
	"""Fix the casing of the "TaxJar Integration" Module Def in place.

	MySQL's default collation is case-insensitive, so "Taxjar Integration" and
	"TaxJar Integration" resolve to the exact same row for every
	frappe.db.exists()/get_value() lookup - there has only ever been one Module
	Def row, whatever casing it happened to be created with. ModuleDef.before_rename
	also blocks renaming any non-custom module, so this corrects the stored name
	in place with a direct UPDATE rather than attempting a delete-and-recreate
	(which, under that same collation, would delete the only copy outright).

	The UPDATE comes from frappe.qb rather than from frappe.db.sql. The builder
	writes the same statement and quotes each name for the database in use.
	frappe.db.set_value() cannot stand in for it: the primary key is one of the
	two columns this corrects, and set_value() would also stamp the row as
	modified for a change no user made.
	"""
	current_name = frappe.db.get_value("Module Def", "TaxJar Integration", "name")
	if not current_name or current_name == "TaxJar Integration":
		return

	module_def = frappe.qb.DocType("Module Def")
	(
		frappe.qb.update(module_def)
		.set(module_def.name, "TaxJar Integration")
		.set(module_def.module_name, "TaxJar Integration")
		.where(module_def.name == current_name)
	).run()
