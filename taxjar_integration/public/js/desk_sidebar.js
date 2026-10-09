// Keeps a collapsed sidebar group collapsed once you leave its pages.
//
// The "Other" group is authored closed: install.py marks it `keep_closed`, and
// frappe.ui.sidebar_item closes it on every render. The desk then opens the
// group that holds the page you are on
// (frappe.ui.Sidebar.expand_parent_section), which is right while you are in
// it - but nothing closes the group again when you navigate out. So one visit
// to TaxJar API Logs leaves the group open for the rest of the browser tab,
// over every other page, until a full reload. That reads as "the group does not
// stay closed", because from the workspace page it looks exactly like an open
// group with nothing selected.
//
// This closes such a group again as soon as the route leaves it. A group the
// user opened by a click is left alone: the desk writes that click to
// localStorage under `section-breaks-state`, so an entry there means the user
// asked for this group's state and the app does not overrule it.
if (!window.taxjar_integration) {
	window.taxjar_integration = {};
}

// Only this app's own sidebar. Other apps author their own closed groups (the
// ERPNext "Taxes" workspace has two), and their behaviour is not ours to change.
// The desk names a sidebar by its Workspace Sidebar record, in exact case
// (sidebar.current_module). This app ships that record as "TaxJar".
const TAXJAR_SIDEBAR = "TaxJar";

/** Is this the sidebar of the TaxJar app? */
taxjar_integration.is_taxjar_sidebar = function (sidebar) {
	return Boolean(sidebar) && sidebar.current_module === TAXJAR_SIDEBAR;
};

// The desk's own store for "the user clicked this group open or closed".
// Written by frappe.ui.sidebar_item.TypeSectionBreak.save_section_break_state.
const SECTION_CLICK_STATE_KEY = "section-breaks-state";

/** The group labels the user has clicked in this workspace, as a plain object. */
function clicked_groups(sidebar_name) {
	try {
		const raw = localStorage.getItem(SECTION_CLICK_STATE_KEY);
		return (raw ? JSON.parse(raw) : {})[sidebar_name] || {};
	} catch (error) {
		// A blocked or corrupt localStorage means no click is on record, which
		// is the safe reading: the authored default then applies.
		return {};
	}
}

/** Drop a trailing slash, so "/app/x/" and "/app/x" compare equal. */
function clean_path(path) {
	return decodeURIComponent(String(path || "").split("?")[0].split("#")[0]).replace(/\/$/, "");
}

/**
 * Is the current page one of this group's links?
 *
 * Matched the way the desk matches its own active item (is_route_in_sidebar):
 * the path equals a link's path, or sits under it - so the API Log list and any
 * one API Log both count as inside the group that links the list.
 */
function holds_current_page(section) {
	const path = clean_path(window.location.pathname);
	const anchors = section.wrapper.find(".nested-container a.item-anchor");

	return Array.from(anchors).some((anchor) => {
		const href = clean_path(anchor.getAttribute("href"));
		return href && (path === href || path.startsWith(href + "/"));
	});
}

/**
 * Close every authored-closed group of this sidebar that the current page is
 * not in, unless the user clicked that group themselves.
 */
taxjar_integration.collapse_unvisited_sidebar_groups = function (sidebar) {
	if (!taxjar_integration.is_taxjar_sidebar(sidebar)) return;

	const clicked = clicked_groups(sidebar.current_module);

	(sidebar.items || []).forEach((section) => {
		// A group with no links never renders a header to collapse, so it has
		// no `close` and nothing to do.
		if (!section || !section.item || section.item.type !== "Section Break") return;
		if (!section.item.keep_closed || !section.$drop_icon) return;
		if (section.collapsed) return;
		if (Object.prototype.hasOwnProperty.call(clicked, section.item.label)) return;
		if (holds_current_page(section)) return;

		section.close();
	});
};

/**
 * Run the collapse after every one of the desk's own active-item passes.
 *
 * set_active_workspace_item is the desk's route hook for the sidebar: it runs
 * on each route change, on each sidebar render, and when the sidebar is
 * expanded - the same three moments a group can end up open on a page that is
 * not in it. Wrapping it once on the prototype covers them all, and covers a
 * sidebar built before this file loaded.
 */
function patch_sidebar_class() {
	const sidebar_class = window.frappe && frappe.ui && frappe.ui.Sidebar;
	if (!sidebar_class || sidebar_class.prototype.taxjar_collapse_patched) return;

	const set_active_workspace_item = sidebar_class.prototype.set_active_workspace_item;

	sidebar_class.prototype.set_active_workspace_item = function () {
		set_active_workspace_item.apply(this, arguments);
		try {
			taxjar_integration.collapse_unvisited_sidebar_groups(this);
		} catch (error) {
			// The sidebar is navigation, not the page: a failure here must not
			// take the desk down with it.
			console.error(error);
		}
	};

	sidebar_class.prototype.taxjar_collapse_patched = true;
}

patch_sidebar_class();

// The desk fires this at the top of every Sidebar.setup(), so the class exists
// by then even if this file was evaluated before the desk built one.
$(document).on("sidebar_setup", patch_sidebar_class);
