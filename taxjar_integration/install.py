import frappe

from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
	add_permissions,
	add_product_tax_categories,
	hide_legacy_exempt_from_sales_tax,
	make_custom_fields,
	set_taxes_field_description,
)
from taxjar_integration.taxjar_integration.regional.united_states import (
	sync_all_company_tax_templates,
)

WORKSPACE = "TaxJar Integration"

# Lucide icon names shown next to each sidebar card group. Cards without an entry
# fall back to no icon.
SIDEBAR_CARD_ICONS = {
	"Setup": "settings",
	"Manage": "layers",
	"Sync": "refresh-cw",
}

GUIDED_SETUP_ALERT_BLOCK = "TaxJar Guided Setup Alert"

# Blue/subtle styling mirrors the Frappe UI Alert component's look
# (https://ui.frappe.io/docs/components/alert) - that component itself belongs to a
# different (Vue-based) UI stack the classic Desk workspace editor can't embed, so
# this hand-builds the same visual language via a Custom HTML Block instead, which is
# the supported extension point for custom workspace content. "Subtle" = a soft
# tinted fill rather than the "outline" variant's bordered-only look.
#
# Custom HTML Block content is rendered inside a Shadow DOM
# (CustomBlockWidget -> frappe.create_shadow_element(), dom.js), which is its own
# tree scope - an <svg><use href="#icon-info"> referencing the global lucide sprite
# in the main document silently resolves to nothing in there, so the icon's path
# data is inlined directly below instead of referenced by id. `width: 100%;
# box-sizing: border-box;` on the outer div is likewise explicit rather than
# assumed, since the shadow host custom element's own default display/sizing
# behavior isn't something this app controls.
GUIDED_SETUP_ALERT_HTML = """
<div style="
	display: flex;
	align-items: flex-start;
	gap: 12px;
	width: 100%;
	box-sizing: border-box;
	padding: 14px 16px;
	background: var(--blue-50);
	border-radius: 8px;
">
	<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--blue-500)"
		stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
		style="flex-shrink: 0; margin-top: 1px;">
		<circle cx="12" cy="12" r="10" />
		<path d="M12 16v-4" />
		<path d="M12 8h.01" />
	</svg>
	<div>
		<div style="font-weight: 600; font-size: 13px; color: var(--heading-color);">
			Configure TaxJar Integration
		</div>
		<div style="font-size: 13px; color: var(--text-muted); margin-top: 2px;">
			<a href="/app/taxjar-setup" style="color: var(--blue-600); font-weight: 500;">
				Try the guided setup experience &rarr;
			</a>
		</div>
	</div>
</div>
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
	* the Product Tax Category master (~800 rows from the bundled fixture) and the
	  permissions that let the accounting/stock roles manage it;
	* the guided-setup alert banner at the top of the workspace;
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

	if not frappe.db.exists("Product Tax Category"):
		add_product_tax_categories()

	add_permissions()

	sync_all_company_tax_templates()

	hide_legacy_exempt_from_sales_tax()

	set_taxes_field_description()

	add_guided_setup_alert()

	sync_taxjar_workspace_sidebar()


def add_guided_setup_alert():
	"""Blue/subtle banner at the top of the workspace nudging first-time users
	toward the guided setup wizard, spanning the full row width (col: 12) above the
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
	html/script back in line with the constants above."""
	if frappe.db.exists("Custom HTML Block", GUIDED_SETUP_ALERT_BLOCK):
		block = frappe.get_doc("Custom HTML Block", GUIDED_SETUP_ALERT_BLOCK)
		if block.html != GUIDED_SETUP_ALERT_HTML or block.script:
			block.html = GUIDED_SETUP_ALERT_HTML
			block.script = ""
			block.save(ignore_permissions=True)
	else:
		frappe.get_doc({
			"doctype": "Custom HTML Block",
			"name": GUIDED_SETUP_ALERT_BLOCK,
			"html": GUIDED_SETUP_ALERT_HTML,
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


def sync_taxjar_workspace_sidebar():
	"""(Re)build the desk left sidebar so it mirrors the workspace's card groups.

	The grouped sidebar lives on ``Workspace.sidebar_items`` (a child table on the
	workspace itself): each card (Card Break) becomes a collapsible Section Break
	and its links become nested child items. This is NOT the standalone
	``Workspace Sidebar`` doctype - that was merged into ``Workspace`` earlier in
	v16 (see ``frappe.patches.v16_0.migrate_workspace_sidebar_to_workspace`` and
	``frappe.boot.get_sidebar_items``, which explicitly says "the legacy Workspace
	Sidebar doctype is no longer read here"). The workspace is the single source
	of truth, so this runs on every install/migrate and stays in lockstep with
	the card layout.
	"""
	if not frappe.db.exists("Workspace", WORKSPACE):
		return

	ws = frappe.get_doc("Workspace", WORKSPACE)

	# Card display order comes from the content blocks; the links table holds the
	# Card Break -> child-link grouping.
	content = frappe.parse_json(ws.content or "[]")
	card_order = [
		block["data"]["card_name"]
		for block in content
		if block.get("type") == "card" and block.get("data", {}).get("card_name")
	]

	grouped = {}
	current = None
	for link in ws.links:
		if link.type == "Card Break":
			current = link.label
			grouped.setdefault(current, [])
		elif link.type == "Link" and current and link.link_to:
			grouped[current].append(link)

	# Honour the visual (content) order, then any card only present in links.
	ordered_cards = card_order + [card for card in grouped if card not in card_order]

	# A Home entry routes back to the workspace itself, mirroring core desk sidebars.
	items = [{
		"type": "Link",
		"label": "Home",
		"link_to": WORKSPACE,
		"link_type": "Workspace",
		"icon": "house",
	}]
	for card in ordered_cards:
		links = grouped.get(card)
		if not links:
			continue
		items.append({
			"type": "Section Break",
			"label": card,
			"icon": SIDEBAR_CARD_ICONS.get(card),
			"collapsible": 1,
			"indent": 1,
		})
		for link in links:
			items.append({
				"type": "Link",
				"label": link.label,
				"link_to": link.link_to,
				"link_type": link.link_type,
				"child": 1,
				"collapsible": 1,
			})

	ws.set("sidebar_items", [])
	for item in items:
		ws.append("sidebar_items", item)
	ws.save(ignore_permissions=True)

	# Drop the pre-merge standalone record left over from older v16 builds; it's
	# no longer read by frappe.boot.get_sidebar_items.
	if frappe.db.exists("DocType", "Workspace Sidebar"):
		frappe.delete_doc("Workspace Sidebar", WORKSPACE, ignore_missing=True, force=True)
