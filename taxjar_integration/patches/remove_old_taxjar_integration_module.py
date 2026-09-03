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
	"""
	current_name = frappe.db.get_value("Module Def", "TaxJar Integration", "name")
	if current_name and current_name != "TaxJar Integration":
		frappe.db.sql(
			"update `tabModule Def` set name=%s, module_name=%s where name=%s",
			("TaxJar Integration", "TaxJar Integration", current_name),
		)
