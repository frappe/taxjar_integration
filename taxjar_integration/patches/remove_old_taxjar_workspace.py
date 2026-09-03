import frappe


def execute():
	"""Repoint the TaxJar desk surfaces to the renamed, branded workspace.

	The workspace was renamed to "Taxjar Integration" so the desk sidebar (which
	shows the workspace name, not its title) reads the branded name. The route
	therefore changed from /app/taxjar to /app/taxjar-integration. This patch:

	* drops the stale "TaxJar" workspace record (the renamed one is recreated from
	  the app's workspace fixture during migrate);
	* repoints any Desktop Icon still linking to the old /app/taxjar route. These
	  icons are user-created (standard=0), so they survive an app reinstall and are
	  never regenerated from hooks — they must be fixed explicitly; and
	* drops the auto-generated Workspace Sidebar records for the TaxJar workspaces.
	  In v16 the desk sidebar is "Home + one item per workspace shortcut"; an older
	  version shipped no shortcuts, so the generated sidebar held only "Home" and
	  suppressed the module auto-generation that lists the DocTypes and Pages.
	  Deleting it lets the sidebar repopulate (from the shortcuts now in the
	  workspace, or the module fallback).
	"""
	if frappe.db.exists("Workspace", "TaxJar"):
		frappe.delete_doc("Workspace", "TaxJar", ignore_missing=True, force=True)

	for name in frappe.get_all("Desktop Icon", filters={"link": "/app/taxjar"}, pluck="name"):
		frappe.db.set_value("Desktop Icon", name, "link", "/app/taxjar-integration")

	# Drop the stale auto-generated "TaxJar" sidebar; the branded "Taxjar Integration"
	# sidebar is (re)built to mirror the workspace cards by install.setup_taxjar.
	if frappe.db.exists("DocType", "Workspace Sidebar") and frappe.db.exists("Workspace Sidebar", "TaxJar"):
		frappe.delete_doc("Workspace Sidebar", "TaxJar", ignore_missing=True, force=True)
