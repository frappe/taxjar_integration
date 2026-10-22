import frappe

_DOCTYPE = "Product Tax Category"

# The rows add_permissions() wrote on every install and migrate. It called
# frappe.permissions.add_permission, which first copies the doctype's JSON rights into
# Custom DocPerm - so the System Manager row is that copy - and then added one
# row per role with read, write and create.
_SYSTEM_MANAGER_RIGHTS = {"read", "write", "create", "delete", "report", "export", "print", "email", "share"}
_ADDED_ROLES = ("Accounts Manager", "Accounts User", "Item Manager", "Stock Manager")
_ADDED_RIGHTS = {"read", "write", "create"}

# Every right a Custom DocPerm row can hold, so an extra right an admin ticked
# shows up as a difference. export is left out: its default for a new Custom
# DocPerm row has not been the same in every Frappe version, so add_permission
# left it on some sites and off on others.
_COMPARED = (
	"read", "write", "create", "delete", "submit", "cancel", "amend", "report",
	"import", "print", "email", "share", "if_owner",
)


def execute():
	"""Hand Product Tax Category back to the rights in its doctype JSON.

	A site that holds any Custom DocPerm row for a doctype uses those rows only,
	and ignores the doctype's JSON rights. add_permissions() wrote such rows, so
	the rights the app now ships for this doctype would never reach a site that
	ran it.

	The rows are removed only when they are exactly what add_permissions() left.
	Rows an admin changed in Role Permission Manager are the admin's decision and
	stay as they are; the migrate output says so.
	"""
	rows = frappe.get_all(
		"Custom DocPerm",
		filters={"parent": _DOCTYPE},
		fields=["role", "permlevel", "export", *_COMPARED],
	)
	if not rows:
		return

	if not is_app_created(rows):
		print(
			f"TaxJar: kept the Custom DocPerm rows on {_DOCTYPE}, because they differ from "
			"what this app wrote. Remove them in Role Permission Manager to use the app's own rights."
		)
		return

	frappe.db.delete("Custom DocPerm", {"parent": _DOCTYPE})
	frappe.clear_cache(doctype=_DOCTYPE)


def is_app_created(rows):
	"""Whether these Custom DocPerm rows are exactly the ones add_permissions() wrote."""
	expected = {"System Manager": _SYSTEM_MANAGER_RIGHTS} | dict.fromkeys(_ADDED_ROLES, _ADDED_RIGHTS)
	if sorted(row.role for row in rows) != sorted(expected):
		return False

	for row in rows:
		if row.permlevel:
			return False
		held = {right for right in _COMPARED if row.get(right)}
		if held != expected[row.role] - {"export"}:
			return False
	return True
