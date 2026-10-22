// The whole form, not one entry point at a time.
//
// The gates are covered one by one in gates.test.js. What that cannot show is
// the thing the bug report was about: a Quotation, Sales Order or Sales Invoice
// for a company registered outside the United States, opened and saved, with no
// shipping address.
//
// The handlers are read out of quotation.js, sales_order.js and
// sales_invoice.js through the same `frappe.ui.form.on` the desk registers them
// with - never transcribed. A copy would go on passing while the real form grew
// an ungated handler, which is exactly the failure this file exists to catch.

import { beforeEach, describe, expect, it } from "vitest";

import {
	IN_CO,
	IN_FLAGGED,
	SCOPE_METHOD,
	TRANSACTION_DOCTYPES,
	US_CALC,
	US_UNCONFIGURED,
	answer_scope,
	answer_xcall,
	flush,
	install_desk,
	load_taxjar_utils,
	load_transaction_forms,
	make_frm,
	sidebar_section,
} from "./helpers/desk.js";

let frappe;
let taxjar;
let forms;

beforeEach(() => {
	frappe = install_desk();
	taxjar = load_taxjar_utils();
	forms = load_transaction_forms();
});

// Every custom field the app adds to a transaction, so each render helper gets
// past its own `fields_dict` guard and actually runs.
const TRANSACTION_FIELDS = [
	"taxjar_tab",
	"taxjar_exemption_section",
	"taxjar_breakdown_section",
	"taxjar_status_html",
	"taxjar_addresses_html",
	"taxjar_breakdown_html",
	"taxjar_freight_taxable_html",
	"taxjar_sync_status",
	"taxjar_transaction_exempt",
	"taxjar_transaction_exemption_type",
];

function open_form(doctype, profile) {
	return make_frm({
		doctype,
		company: profile.company,
		name: `${doctype.slice(0, 4).toUpperCase()}-0001`,
		fields: TRANSACTION_FIELDS,
		// The reported bug exactly: a customer, and no shipping address.
		doc: { customer: "Acme Corp", party_name: "Acme Corp", quotation_to: "Customer" },
	});
}

/** Run every handler the form script registered, the way the desk would. */
async function run_all_handlers(doctype, frm) {
	const events = forms[doctype];
	for (const name of Object.keys(events)) {
		await events[name](frm);
		await flush();
	}
}

async function load_and_save(doctype, profile) {
	answer_scope(frappe, profile);

	const frm = open_form(doctype, profile);
	await run_all_handlers(doctype, frm);

	return frm;
}

// If a form script starts registering a handler nobody here knows about, that
// is not a failure - run_all_handlers runs it too. This only records what the
// forms carry today, so a new one shows up in a diff rather than silently.
describe("the form scripts themselves", () => {
	it.each(TRANSACTION_DOCTYPES)("%s registers handlers that are all functions", (doctype) => {
		const events = forms[doctype];

		expect(Object.keys(events).length).toBeGreaterThan(0);
		for (const [name, handler] of Object.entries(events)) {
			expect(typeof handler, `${doctype}.${name} is not a function`).toBe("function");
		}
	});

	it("covers all three transaction forms", () => {
		expect(Object.keys(forms)).toEqual(expect.arrayContaining(TRANSACTION_DOCTYPES));
	});
});

describe("a company registered outside the United States", () => {
	// "An India company was asked for a shipping address and told it had no
	// nexus in Karnataka." None of that may happen now - and this runs every
	// handler the form has, so a new one that forgets its gate lands here.
	describe.each(TRANSACTION_DOCTYPES)("%s", (doctype) => {
		it.each([IN_CO, IN_FLAGGED])("shows no TaxJar chrome for $company", async (profile) => {
			const frm = await load_and_save(doctype, profile);

			expect(frm.fields_dict.taxjar_tab.df.hidden).toBe(1);
			expect(frm.fields_dict.taxjar_exemption_section.df.hidden).toBe(1);
			expect(frm.fields_dict.taxjar_breakdown_section.df.hidden).toBe(1);
		});

		it.each([IN_CO, IN_FLAGGED])("shows no message strip for $company", async (profile) => {
			const frm = await load_and_save(doctype, profile);

			expect(frm.layout.message.text().trim()).toBe("");
			expect(frm.layout.message.hasClass("hidden")).toBe(true);
		});

		it.each([IN_CO, IN_FLAGGED])("opens no dialog at all for $company", async (profile) => {
			await load_and_save(doctype, profile);

			expect(frappe.msgprint).not.toHaveBeenCalled();
			expect(frappe.ui.Dialog).not.toHaveBeenCalled();
		});

		it.each([IN_CO, IN_FLAGGED])("adds no button for $company", async (profile) => {
			const frm = await load_and_save(doctype, profile);

			expect(frm.add_custom_button).not.toHaveBeenCalled();
		});

		// frappe.validated is what a client script sets to stop the save. Left
		// alone, the document saves.
		it.each([IN_CO, IN_FLAGGED])("lets the save go through for $company", async (profile) => {
			await load_and_save(doctype, profile);

			expect(frappe.validated).toBe(true);
		});

		// One read for the whole load and save. The form asks four or five
		// times; the memo in scope() turns that into a single request.
		it.each([IN_CO, IN_FLAGGED])(
			"asks the server once, and only about scope, for $company",
			async (profile) => {
				await load_and_save(doctype, profile);

				expect(frappe.xcall).toHaveBeenCalledTimes(1);
				expect(frappe.xcall).toHaveBeenCalledWith(SCOPE_METHOD, { company: profile.company });
			}
		);
	});

	it("puts no pill and no link in the Sales Invoice sidebar", async () => {
		await load_and_save("Sales Invoice", IN_CO);

		expect(sidebar_section().length).toBe(0);
	});
});

// A company TaxJar could serve that nobody configured behaves the same way on
// the form. It differs only in what the status panel says, which
// empty_status.test.js covers.
describe("a company nobody has configured", () => {
	it.each(TRANSACTION_DOCTYPES)("shows no TaxJar chrome on a %s", async (doctype) => {
		const frm = await load_and_save(doctype, US_UNCONFIGURED);

		expect(frm.fields_dict.taxjar_tab.df.hidden).toBe(1);
		expect(frm.layout.message.text().trim()).toBe("");
		expect(frappe.msgprint).not.toHaveBeenCalled();
		expect(frappe.validated).toBe(true);
	});
});

// The other half of the check: with a company TaxJar does serve, the same run
// has to produce the chrome. Without this, every assertion above would also
// pass against a build that had simply stopped working.
describe("a company that TaxJar calculates for", () => {
	function answer_full(profile, { addresses = [] } = {}) {
		answer_xcall(frappe, {
			[SCOPE_METHOD]: profile,
			"taxjar_integration.taxjar_integration.taxjar_integration.get_customer_addresses": addresses,
			"taxjar_integration.taxjar_integration.taxjar_integration.preview_foreign_tax_rows": {
				foreign_rows: [],
			},
			"taxjar_integration.taxjar_integration.taxjar_integration.get_region_exemption": {},
			"taxjar_integration.taxjar_integration.taxjar_integration.check_nexus": { has_nexus: true },
		});
	}

	it.each(TRANSACTION_DOCTYPES)("shows the TaxJar tab on a %s", async (doctype) => {
		answer_full(US_CALC);

		const frm = open_form(doctype, US_CALC);
		await forms[doctype].refresh(frm);
		await flush();

		expect(frm.fields_dict.taxjar_tab.df.hidden).toBe(0);
	});

	it.each(TRANSACTION_DOCTYPES)("asks for an address in the message strip on a %s", async (doctype) => {
		answer_full(US_CALC);

		const frm = open_form(doctype, US_CALC);
		await forms[doctype].refresh(frm);
		await flush();

		expect(frm.layout.message.text()).toContain(
			"Customer address is not set, hence taxes are not calculated"
		);
	});

	// A Sales Invoice with no address and no address on file stops its own save
	// and says so. A Quotation does not: a quotation to a customer with no
	// address yet is unfinished, not wrong.
	it("stops the save on a Sales Invoice with no address on file", async () => {
		answer_full(US_CALC);

		const frm = open_form("Sales Invoice", US_CALC);
		await forms["Sales Invoice"].validate(frm);
		await flush();

		expect(frappe.validated).toBe(false);
		expect(frappe.msgprint).toHaveBeenCalledTimes(1);
		expect(frappe.msgprint.mock.calls[0][0].title).toBe("No Addresses Found");
	});

	it("lets a Quotation save with no address on file", async () => {
		answer_full(US_CALC);

		const frm = open_form("Quotation", US_CALC);
		await forms.Quotation.validate(frm);
		await flush();

		expect(frappe.validated).toBe(true);
		expect(frappe.msgprint).not.toHaveBeenCalled();
	});

	// Where the customer does have addresses, the picker opens instead.
	it("opens the address picker when the customer has addresses", async () => {
		answer_full(US_CALC, {
			addresses: [{ name: "Acme-Miami", city: "Miami", state: "FL", pincode: "33169" }],
		});

		const frm = open_form("Sales Invoice", US_CALC);
		await forms["Sales Invoice"].validate(frm);
		await flush();

		expect(frappe.validated).toBe(false);
		expect(frappe.ui.Dialog).toHaveBeenCalledTimes(1);
		expect(frappe.msgprint).not.toHaveBeenCalled();
	});

	// Every message that stops a save carries its own heading. Without a title
	// frappe renders the generic "Message", which is what the originally
	// reported dialog showed.
	it("gives every blocking message a heading of its own", async () => {
		answer_full(US_CALC);

		const frm = open_form("Sales Invoice", US_CALC);
		await forms["Sales Invoice"].validate(frm);
		await flush();

		for (const [options] of frappe.msgprint.mock.calls) {
			expect(options.title).toBeTruthy();
			expect(options.title).not.toBe("Message");
		}
	});
});
