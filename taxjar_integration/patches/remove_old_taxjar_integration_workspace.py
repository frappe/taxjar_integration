import frappe


def execute():
	"""Fix the casing of the "TaxJar Integration" Workspace / Workspace Sidebar in place.

	MySQL's default collation is case-insensitive, so "Taxjar Integration" and
	"TaxJar Integration" resolve to the exact same row for frappe.db.exists()/
	get_value() lookups - there is only ever one Workspace (and one Workspace
	Sidebar) row, whatever casing it was created with. Blindly deleting by the
	old-cased name (as an earlier version of this patch did) would therefore risk
	deleting the correct, already-fixed row on any site where sync_all() only
	ever created it once. Renaming in place is safe here (unlike Module Def,
	Workspace/Workspace Sidebar have no "custom only" before_rename guard).

	The route slug is unaffected (both names lowercase to the same
	`/app/taxjar-integration`), so no Desktop Icon repointing is needed here,
	unlike remove_old_taxjar_workspace.py.
	"""
	current = frappe.db.get_value("Workspace", "TaxJar Integration", "name")
	if current and current != "TaxJar Integration":
		frappe.rename_doc("Workspace", current, "TaxJar Integration", force=True)

	if frappe.db.exists("DocType", "Workspace Sidebar"):
		current_sidebar = frappe.db.get_value("Workspace Sidebar", "TaxJar Integration", "name")
		if current_sidebar and current_sidebar != "TaxJar Integration":
			frappe.rename_doc("Workspace Sidebar", current_sidebar, "TaxJar Integration", force=True)
