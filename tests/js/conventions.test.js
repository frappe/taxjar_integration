// The client half of scripts/audit_conventions.py check 1: every name this
// suite stubs out still names something the code defines.
//
// A spy on a renamed function is a spy on a dead property. The real function
// still runs, the assertion still reads the spy, and the test goes on passing
// while controlling nothing. That is the failure mode a large refactor is most
// likely to introduce and least likely to notice, which is why the Python suite
// has the same check.

import { beforeEach, describe, expect, it } from "vitest";

import {
	TRANSACTION_DOCTYPES,
	install_desk,
	load_taxjar_settings_form,
	load_taxjar_utils,
	load_transaction_forms,
} from "./helpers/desk.js";

let taxjar;

beforeEach(() => {
	install_desk();
	taxjar = load_taxjar_utils();
});

// Every public entry point the gate tests drive.
const ENTRY_POINTS = [
	"scope",
	"when_scoped",
	"check_shipping_address",
	"confirm_foreign_tax_rows",
	"apply_region_exemption",
	"show_no_address_tax_message",
	"toggle_taxjar_ui",
	"render_sync_status_sidebar_pill",
	"render_status_cards",
	"render_addresses",
	"render_tax_breakdown",
	"render_shipping_taxability",
];

// Every private body the gate tests replace with a spy, and every private
// renderer they assert on by name.
const PRIVATE_BODIES = [
	"_prompt_for_shipping_address",
	"_confirm_foreign_tax_rows",
	"_apply_region_exemption",
	"_show_tax_message",
	"_render_empty_status",
	"_render_taxjar_sync_status_pill",
	"_render_taxjar_not_enabled_link",
];

describe("the names this suite depends on", () => {
	it.each(ENTRY_POINTS)("taxjar_integration.%s is defined", (name) => {
		expect(typeof taxjar[name], `${name} is not a function on taxjar_integration`).toBe(
			"function"
		);
	});

	it.each(PRIVATE_BODIES)("taxjar_integration.%s is defined", (name) => {
		expect(typeof taxjar[name], `${name} is not a function on taxjar_integration`).toBe(
			"function"
		);
	});
});

describe("the files this suite loads", () => {
	it("finds a form script for each transaction doctype", () => {
		const forms = load_transaction_forms();

		for (const doctype of TRANSACTION_DOCTYPES) {
			expect(forms[doctype], `${doctype} has no handlers`).toBeTruthy();
		}
	});

	it("finds the settings form and its grid handlers", () => {
		const handlers = load_taxjar_settings_form();

		expect(typeof handlers["TaxJar Company Config"]?.company).toBe("function");
		expect(typeof handlers["TaxJar Settings"]?.refresh).toBe("function");
	});
});

// The endpoint name is a string in the client and a function in Python. Nothing
// in either language checks they agree, so the suite pins the string in one
// place and this says which place.
describe("the scope endpoint", () => {
	it("is the path the client actually calls", async () => {
		const { SCOPE_METHOD } = await import("./helpers/desk.js");

		expect(SCOPE_METHOD).toBe(
			"taxjar_integration.taxjar_integration.taxjar_integration.get_company_scope"
		);
	});
});
