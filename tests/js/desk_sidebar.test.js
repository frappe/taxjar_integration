// desk_sidebar.js - the "Other" sidebar group, and when it closes again.
//
// The group is authored closed (install.py marks it `keep_closed`). The desk
// opens the group that holds the page you are on and never closes it again, so
// one visit to TaxJar API Logs left it open over every later page in that
// browser tab. These cases fix the three answers apart: open while you are in
// the group, closed once you leave it, and open for as long as the user asked
// for it by a click.

import { beforeEach, describe, expect, it, vi } from "vitest";

import { install_desk, load_desk_sidebar } from "./helpers/desk.js";

// The desk names a sidebar by its Workspace Sidebar record, in exact case
// (sidebar.current_module). desk_sidebar.js reads the same name.
const SIDEBAR_NAME = "TaxJar";
const CLICK_STATE_KEY = "section-breaks-state";

let frappe;
let taxjar;

beforeEach(() => {
	frappe = install_desk();
	localStorage.clear();
	go_to("/app/taxjar-integration");
	taxjar = load_desk_sidebar();
});

function go_to(path) {
	window.history.pushState({}, "", path);
}

/**
 * One rendered sidebar group, reduced to what the collapse reads: the links it
 * holds, whether it is open, and a `close` the test can see being called.
 */
function make_group(label, { keep_closed = 1, collapsed = false, links = [] } = {}) {
	const wrapper = $(
		`<div class="sidebar-item-container section-item" title="${label}">
			<div class="nested-container"></div>
		</div>`
	);
	links.forEach((href) => {
		wrapper.find(".nested-container").append(`<a class="item-anchor" href="${href}"></a>`);
	});

	const group = {
		item: { type: "Section Break", label, keep_closed },
		wrapper,
		// The desk builds this button only for a collapsible group. Its absence
		// means the group never rendered a header, so it cannot be closed.
		$drop_icon: $("<button class='drop-icon'></button>"),
		collapsed,
		close: vi.fn(() => {
			group.collapsed = true;
		}),
	};
	return group;
}

function make_sidebar(groups, { current_module = SIDEBAR_NAME } = {}) {
	return { current_module, items: groups };
}

/** The group as it ships: closed by default, holding the two reference pages. */
function other_group(options = {}) {
	return make_group("Other", {
		links: ["/app/taxjar-api-log", "/app/taxjar-settings"],
		...options,
	});
}

/** Record a user click on a group, the way the desk records one. */
function remember_click(label, collapsed, sidebar_name = SIDEBAR_NAME) {
	localStorage.setItem(
		CLICK_STATE_KEY,
		JSON.stringify({ [sidebar_name]: { [label]: collapsed } })
	);
}

describe("collapse_unvisited_sidebar_groups", () => {
	it("closes an open group when the page is not one of its links", () => {
		const group = other_group({ collapsed: false });
		go_to("/app/taxjar-setup");

		taxjar.collapse_unvisited_sidebar_groups(make_sidebar([group]));

		expect(group.close).toHaveBeenCalled();
		expect(group.collapsed).toBe(true);
	});

	it("leaves the group open on one of its own pages", () => {
		const group = other_group({ collapsed: false });
		go_to("/app/taxjar-api-log");

		taxjar.collapse_unvisited_sidebar_groups(make_sidebar([group]));

		expect(group.close).not.toHaveBeenCalled();
	});

	it("leaves the group open on a document of one of its own pages", () => {
		const group = other_group({ collapsed: false });
		go_to("/app/taxjar-api-log/ur9hp8l18u");

		taxjar.collapse_unvisited_sidebar_groups(make_sidebar([group]));

		expect(group.close).not.toHaveBeenCalled();
	});

	it("leaves a group the user clicked open alone", () => {
		const group = other_group({ collapsed: false });
		remember_click("Other", false);
		go_to("/app/taxjar-setup");

		taxjar.collapse_unvisited_sidebar_groups(make_sidebar([group]));

		expect(group.close).not.toHaveBeenCalled();
	});

	it("reads the click record of this workspace only", () => {
		const group = other_group({ collapsed: false });
		remember_click("Other", false, "Taxes");
		go_to("/app/taxjar-setup");

		taxjar.collapse_unvisited_sidebar_groups(make_sidebar([group]));

		expect(group.close).toHaveBeenCalled();
	});

	it("survives a localStorage that cannot be read", () => {
		const group = other_group({ collapsed: false });
		localStorage.setItem(CLICK_STATE_KEY, "{not json");
		go_to("/app/taxjar-setup");

		taxjar.collapse_unvisited_sidebar_groups(make_sidebar([group]));

		expect(group.close).toHaveBeenCalled();
	});

	it("leaves a group that is authored open alone", () => {
		const group = make_group("Setup", {
			keep_closed: 0,
			links: ["/app/taxjar-setup"],
		});
		go_to("/app/taxjar-api-log");

		taxjar.collapse_unvisited_sidebar_groups(make_sidebar([group]));

		expect(group.close).not.toHaveBeenCalled();
	});

	it("leaves another app's sidebar alone", () => {
		const group = other_group({ collapsed: false });
		go_to("/app/taxjar-setup");

		taxjar.collapse_unvisited_sidebar_groups(make_sidebar([group], { current_module: "Taxes" }));

		expect(group.close).not.toHaveBeenCalled();
	});

	it("closes an already closed group no further", () => {
		const group = other_group({ collapsed: true });
		go_to("/app/taxjar-setup");

		taxjar.collapse_unvisited_sidebar_groups(make_sidebar([group]));

		expect(group.close).not.toHaveBeenCalled();
	});
});

describe("the desk's own route pass", () => {
	// The desk calls set_active_workspace_item on every route change, on every
	// sidebar render and when the sidebar is expanded. Those are the three
	// moments a group can be left open on a page that is not in it, so the
	// collapse rides on that one method rather than on a route event of its own.
	function install_sidebar_class() {
		const calls = [];
		frappe.ui.Sidebar = class Sidebar {
			constructor(groups) {
				this.current_module = SIDEBAR_NAME;
				this.items = groups;
			}
			set_active_workspace_item() {
				calls.push("desk");
			}
		};
		return calls;
	}

	it("closes the group after the desk's own pass, not instead of it", () => {
		const calls = install_sidebar_class();
		load_desk_sidebar();

		const group = other_group({ collapsed: false });
		go_to("/app/taxjar-setup");
		new frappe.ui.Sidebar([group]).set_active_workspace_item();

		expect(calls).toEqual(["desk"]);
		expect(group.close).toHaveBeenCalled();
	});

	it("wraps the desk's method once, however often the file is loaded", () => {
		install_sidebar_class();
		load_desk_sidebar();
		const wrapped = frappe.ui.Sidebar.prototype.set_active_workspace_item;
		load_desk_sidebar();

		expect(frappe.ui.Sidebar.prototype.set_active_workspace_item).toBe(wrapped);
	});

	it("keeps the desk on its feet when a group cannot be closed", () => {
		const calls = install_sidebar_class();
		load_desk_sidebar();
		vi.spyOn(console, "error").mockImplementation(() => {});

		const group = other_group({ collapsed: false });
		group.close = () => {
			throw new Error("no such group");
		};
		go_to("/app/taxjar-setup");

		expect(() => new frappe.ui.Sidebar([group]).set_active_workspace_item()).not.toThrow();
		expect(calls).toEqual(["desk"]);
	});
});
