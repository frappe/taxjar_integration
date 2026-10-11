import frappe
from frappe import _

# PLACEHOLDER: replace with the published address of the TaxJar "Roles and
# permissions" page (docs/taxjar/09-roles-and-permissions.md) before release.
# Every permission refusal in the app links here. Change it here and in
# taxjar_integration.ROLES_DOCS_URL in public/js/taxjar_utils.js, which opens
# the link in a new tab. A test fails while the two differ. Tracked in
# docs/taxjar/FINAL-RELEASE-PLAN.md.
ROLES_DOCS_URL = "https://docs.example.com/taxjar/roles-and-permissions"

# The heading of the table that lists the rights for each TaxJar task, as the
# slug a Markdown renderer gives it.
TASK_TABLE_ANCHOR = "taxjar-tasks-and-the-rights-they-need"


def require_permission(doctype, ptype="read", doc=None):
	"""Refuse, with a link to the roles documentation, unless the user has the right.

	The same check as Frappe's has_permission with throw on. That call raises
	with Frappe's own text, which names the record but not what to do about it.
	This one names the right that is missing, tells the user to ask their
	administrator, and links to the table that lists the rights for each TaxJar
	task, so the administrator gives the right one.
	"""
	if frappe.has_permission(doctype, ptype, doc=doc):
		return

	frappe.throw(
		_("You do not have {0} access to {1}, ask your administrator to update permissions for your user.").format(
			frappe.bold(_(ptype)),
			frappe.bold(_(doctype)),
		)
		# A blank line, then the link. The whole line is the link, the arrow included.
		+ f'<br><br><a href="{ROLES_DOCS_URL}#{TASK_TABLE_ANCHOR}" rel="noopener noreferrer">'
		f'{_("Read documentation")} &rarr;</a>',
		exc=frappe.PermissionError,
		title=_("Not Permitted"),
	)
