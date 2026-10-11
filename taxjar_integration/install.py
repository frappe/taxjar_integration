import frappe

from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
	add_product_tax_categories,
	hide_legacy_exempt_from_sales_tax,
	make_custom_fields,
	set_taxes_field_description,
)
from taxjar_integration.taxjar_integration.regional.united_states import (
	sync_all_company_tax_templates,
)

WORKSPACE = "TaxJar Integration"

GUIDED_SETUP_ALERT_BLOCK = "TaxJar Guided Setup Alert"

# Blue/subtle styling mirrors the Frappe UI Alert component's look
# (https://ui.frappe.io/docs/components/alert) - that component itself belongs to a
# different (Vue-based) UI stack the classic Desk workspace editor can't embed, so
# this hand-builds the same visual language via a Custom HTML Block instead, which is
# the supported extension point for custom workspace content. "Subtle" = a soft
# tinted fill rather than the "outline" variant's bordered-only look.
#
# The colours are the ones .es-alert itself reads for data-theme="blue" and
# data-theme="green" (frappe/public/css/espresso/components/alert.css):
# --surface-*-2 for the fill, --ink-*-6 for the icon, and --ink-gray-9 /
# --ink-gray-6 for the two lines of text. --ink-*-7 carries the link, which the
# component has no equivalent for - in light mode it is --blue-600 / --green-600,
# the values this banner used to hardcode.
#
# They are theme ROLES, and that is the point of using them: --surface-blue-2 is
# --blue-100 on a light ground and --blue-900 on a dark one. The raw ramp does
# not invert - --blue-50 is #f1f8fe in light and #c9e0f5 in dark, pale in both -
# so a fill taken from there put near-white --ink-gray-9 text on a pale blue
# background for every user on the dark theme.
#
# Custom HTML Block content is rendered inside a Shadow DOM
# (CustomBlockWidget -> frappe.create_shadow_element(), dom.js), which is its own
# tree scope - an <svg><use href="#icon-info"> referencing the global lucide sprite
# in the main document silently resolves to nothing in there, so the icon's path
# data is inlined directly below instead of referenced by id. `width: 100%;
# box-sizing: border-box;` on the outer div is likewise explicit rather than
# assumed, since the shadow host custom element's own default display/sizing
# behavior isn't something this app controls.
# Both states ship in the html and the script below picks one, rather than the
# server rendering whichever state was true at migrate time. A banner baked at
# migrate goes stale the moment somebody finishes the wizard, and nothing runs
# again until the next migrate.
#
# The pending state is the one that renders if the script never runs (an old
# browser, a failed call, a user who cannot read the flag). It links to the
# setup page either way, so the fallback is the safe half.
GUIDED_SETUP_ALERT_HTML = """
<div data-taxjar-state="pending" style="
	display: flex;
	align-items: flex-start;
	gap: 12px;
	width: 100%;
	box-sizing: border-box;
	padding: 14px 16px;
	background: var(--surface-blue-2);
	border-radius: var(--radius-md);
">
	<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--ink-blue-6)"
		stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
		style="flex-shrink: 0; margin-top: 1px;">
		<circle cx="12" cy="12" r="10" />
		<path d="M12 16v-4" />
		<path d="M12 8h.01" />
	</svg>
	<div>
		<div style="font-weight: 600; font-size: 13px; color: var(--ink-gray-9);">
			Configure TaxJar Integration
		</div>
		<div style="font-size: 13px; color: var(--ink-gray-6); margin-top: 2px;">
			<a href="/app/taxjar-setup" style="color: var(--ink-blue-7); font-weight: 500;">
				Go to guided setup experience &rarr;
			</a>
		</div>
	</div>
</div>
<div data-taxjar-state="done" style="
	display: none;
	align-items: flex-start;
	gap: 12px;
	width: 100%;
	box-sizing: border-box;
	padding: 14px 16px;
	background: var(--surface-green-2);
	border-radius: var(--radius-md);
">
	<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--ink-green-6)"
		stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
		style="flex-shrink: 0; margin-top: 1px;">
		<circle cx="12" cy="12" r="10" />
		<path d="m9 12 2 2 4-4" />
	</svg>
	<div>
		<div style="font-weight: 600; font-size: 13px; color: var(--ink-gray-9);">
			TaxJar Integration is successfully configured
		</div>
		<div style="font-size: 13px; color: var(--ink-gray-6); margin-top: 2px;">
			<a href="/app/taxjar-setup" style="color: var(--ink-green-7); font-weight: 500;">
				Review configuration &rarr;
			</a>
		</div>
	</div>
</div>
""".strip()

# Runs inside the block's Shadow DOM, where frappe.create_shadow_element() hands
# it `root_element` (the shadow root) as its only local. `frappe` itself is a
# window global, so frappe.xcall reaches it from in here.
#
# get_setup_status() is used rather than get_setup_state(): this runs for every
# user who opens the workspace, and get_setup_state() guards on read permission
# for TaxJar Settings, which most of them do not have. A failure leaves the
# pending state showing, which is the state that links somewhere useful anyway.
GUIDED_SETUP_ALERT_SCRIPT = """
frappe
	.xcall("taxjar_integration.taxjar_integration.page.taxjar_setup.taxjar_setup.get_setup_status")
	.then(function (status) {
		if (!status || !status.setup_complete) return;
		var pending = root_element.querySelector('[data-taxjar-state="pending"]');
		var done = root_element.querySelector('[data-taxjar-state="done"]');
		if (!pending || !done) return;
		pending.style.display = "none";
		done.style.display = "flex";
	})
	.catch(function () {});
""".strip()


def after_install():
	setup_taxjar()


def after_migrate():
	setup_taxjar()


def setup_taxjar():
	"""Idempotent TaxJar setup that runs on install and on every migrate.

	All the one-time, heavy work lives here rather than on the first save of TaxJar
	Settings:

	* custom fields (the Customer/Sales Invoice ``taxjar_*`` columns) — created up
	  front so the desk pages never query columns that don't exist (MySQLdb 1054);
	* the Product Tax Category master (~800 rows from the bundled fixture). Who may
	  read or change it is set in its doctype JSON, not here. The fixture is
	  applied on every run, not only on the first one: create_tax_categories()
	  inserts a code the site does not hold and leaves every other row alone, so
	  a site seeded by an older release picks up the codes added since;
	* the guided-setup alert banner at the top of the workspace, and the roles
	  that see the workspace;
	* standard-CoA ledger backfill and TaxJar Sales Tax template sync for every
	  already-configured company (regional/united_states.py) — this is also what
	  reconciles an existing site upgrading into this feature for the first time;
	* hiding ERPNext's own regional "exempt from sales tax" checkbox in favour of
	  TaxJar-native exemption (Customer.taxjar_exemption_type and, per-transaction,
	  taxjar_transaction_exempt);
	* a hint on the native "taxes" table field explaining the $0 placeholder row
	  is populated by TaxJar on save, not on load.
	"""
	make_custom_fields()

	add_product_tax_categories()

	sync_all_company_tax_templates()

	hide_legacy_exempt_from_sales_tax()

	set_taxes_field_description()

	add_guided_setup_alert()

	set_workspace_roles()


# The roles that see the TaxJar workspace: every role the TaxJar pages list,
# which is the TaxJar Manager and TaxJar User personas. The workspace JSON
# carries the same list.
WORKSPACE_ROLES = ("System Manager", "Accounts Manager", "Accounts User")


def set_workspace_roles():
	"""Give the TaxJar workspace its roles, on every install and migrate.

	The workspace JSON carries them, but Frappe imports a workspace file only
	when the file is newer than the site's own copy. This app saves the
	workspace to put back the guided-setup banner, and admins save it to change
	the layout, so on many sites the file is never imported and the workspace
	shows to every desk user.

	Adds a missing role and keeps every role an admin added. A default role an
	admin removed comes back here, the same as the banner does. Saves only when
	a role was added: each save moves the workspace's date forward.
	"""
	if not frappe.db.exists("Workspace", WORKSPACE):
		return

	ws = frappe.get_doc("Workspace", WORKSPACE)
	present = {row.role for row in ws.roles}
	missing = [role for role in WORKSPACE_ROLES if role not in present]
	if not missing:
		return

	for role in missing:
		ws.append("roles", {"role": role})
	ws.save(ignore_permissions=True)


def add_guided_setup_alert():
	"""Subtle banner at the top of the workspace, blue while the guided setup has
	not been finished and green once it has, spanning the full row width (col: 12) above the
	Setup/Manage/Sync cards below it. Idempotent and self-healing: creates the
	Custom HTML Block if missing, otherwise keeps its html/script in sync with the
	constants above, and re-normalizes its position/width in the workspace content
	on every call (the app is the source of truth here, same convention as
	create_custom_fields(update=True) - a copy/style/layout edit in this file
	should reach already-migrated sites, not just fresh installs).

	This only runs on install/migrate. `keep_guided_setup_alert` below re-applies
	the same self-heal on every save of the workspace itself, so an in-desk layout
	edit (reordering cards, etc.) can't silently drop the block until the next
	migrate happens to run.
	"""
	_ensure_guided_setup_alert_block()

	if not frappe.db.exists("Workspace", WORKSPACE):
		return

	ws = frappe.get_doc("Workspace", WORKSPACE)
	if _splice_guided_setup_alert_into_content(ws):
		ws.save(ignore_permissions=True)


def _ensure_guided_setup_alert_block():
	"""Create the guided-setup alert's Custom HTML Block if missing, or bring its
	html and script back in line with the constants above."""
	if frappe.db.exists("Custom HTML Block", GUIDED_SETUP_ALERT_BLOCK):
		block = frappe.get_doc("Custom HTML Block", GUIDED_SETUP_ALERT_BLOCK)
		if block.html != GUIDED_SETUP_ALERT_HTML or block.script != GUIDED_SETUP_ALERT_SCRIPT:
			block.html = GUIDED_SETUP_ALERT_HTML
			block.script = GUIDED_SETUP_ALERT_SCRIPT
			block.save(ignore_permissions=True)
	else:
		frappe.get_doc({
			"doctype": "Custom HTML Block",
			"name": GUIDED_SETUP_ALERT_BLOCK,
			"html": GUIDED_SETUP_ALERT_HTML,
			"script": GUIDED_SETUP_ALERT_SCRIPT,
			"private": 0,
		}).insert(ignore_permissions=True)


def _splice_guided_setup_alert_into_content(ws):
	"""Ensure `ws` (a Workspace doc, mutated in place) has the guided-setup alert
	wired into both `custom_blocks` and `content`. Returns True if it changed
	anything, so callers know whether a save is needed."""
	dirty = False

	# The `custom_blocks` child table is what the block editor actually looks up by
	# label to resolve a "custom_block" content entry into a live widget
	# (Block.make() in block.js -> page_data.custom_blocks.items, matched by label).
	# The content block below only controls position/width - without a matching row
	# here, the editor has nothing to render and the block just doesn't show up.
	has_custom_block_row = any(
		row.custom_block_name == GUIDED_SETUP_ALERT_BLOCK for row in ws.custom_blocks or []
	)
	if not has_custom_block_row:
		ws.append("custom_blocks", {
			"custom_block_name": GUIDED_SETUP_ALERT_BLOCK,
			"label": GUIDED_SETUP_ALERT_BLOCK,
		})
		dirty = True

	# Full width (col: 12) - the Setup/Manage/Sync cards below now sit in one row
	# (4 + 4 + 4) rather than one-per-row, so the banner spans the same row width
	# rather than being paired with a spacer. Strip any previous version of this
	# block (and the spacer it used to be paired with) before re-inserting fresh,
	# so a layout change here also self-heals already-migrated sites, not just
	# fresh installs.
	original_content = frappe.parse_json(ws.content or "[]")
	content = [
		b for b in original_content
		if b.get("id") != "taxjar_guided_setup_alert_spacer"
		and not (
			b.get("type") == "custom_block"
			and b.get("data", {}).get("custom_block_name") == GUIDED_SETUP_ALERT_BLOCK
		)
	]
	content = [
		{
			"id": "taxjar_guided_setup_alert",
			"type": "custom_block",
			"data": {"custom_block_name": GUIDED_SETUP_ALERT_BLOCK, "col": 12},
		},
		*content,
	]
	if content != original_content:
		ws.content = frappe.as_json(content)
		dirty = True

	return dirty


def keep_guided_setup_alert(doc, method):
	"""Workspace `validate` hook, scoped to the TaxJar Integration workspace: re-splice
	the guided-setup alert into `doc` before every save of it, not just install/migrate.

	Without this, saving the workspace from the desk block editor - reordering cards,
	adding a link, anything - re-serializes `content`/`custom_blocks` from whatever the
	editor currently has rendered. If the block failed to render in that session (it
	lives in a Shadow DOM - see docs/config-banners-and-dialogs-audit.md Finding #3) or
	was otherwise not present, the save silently drops the banner, and nothing put it
	back until the next `bench migrate`.
	"""
	if doc.name != WORKSPACE:
		return
	_ensure_guided_setup_alert_block()
	_splice_guided_setup_alert_into_content(doc)
