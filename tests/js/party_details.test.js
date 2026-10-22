// Picking a customer, while erpnext writes that customer's defaults.
//
// erpnext writes a party's defaults in one go: customer_address,
// shipping_address_name and a dozen other fields, one after another, with
// frm.updating_party_details set for the whole run (party.js). Each field fires
// its own handlers as it lands, so a handler that reads the destination between
// two of them reads a half-written document.
//
// CUST-0003 on the test site shows what that costs. Its default billing address
// is in India and its preferred shipping address is in Arizona, so the moment
// the billing address landed the form said "Sales taxes are not applicable on
// export transactions" - a yellow strip that went again a moment later, when
// the ship-to field landed and the sale turned out to be domestic after all.
//
// So nothing that reads the destination runs during that write. erpnext clears
// the flag and calls frm.refresh() when it is done, which runs all of it again
// on the settled document.

import { beforeEach, describe, expect, it } from "vitest";

import {
	TRANSACTION_DOCTYPES,
	US_CALC,
	answer_xcall,
	flush,
	install_desk,
	load_taxjar_utils,
	load_transaction_forms,
	make_frm,
	message_text,
	sidebar_section,
} from "./helpers/desk.js";

const MOD = "taxjar_integration.taxjar_integration.taxjar_integration";
const SCOPE_METHOD = `${MOD}.get_company_scope`;
const EXPORT_METHOD = `${MOD}.check_export_destination`;
const REGION_METHOD = `${MOD}.get_region_exemption`;
const NEXUS_METHOD = `${MOD}.check_nexus`;

const TRANSACTION_FIELDS = [
	"taxjar_sync_status",
	"taxjar_transaction_exempt",
	"taxjar_transaction_exemption_type",
];

// The two addresses CUST-0003 hands the form, and what each one answers.
const BILLING = "CUST-0003-India";
const SHIPPING = "CUST-0003-Arizona";

let frappe;
let taxjar;
let forms;

beforeEach(() => {
	frappe = install_desk();
	taxjar = load_taxjar_utils();
	forms = load_transaction_forms();
});

/** Every read the form makes: India is an export, Arizona is not. */
function answer_every_read() {
	answer_xcall(frappe, {
		[SCOPE_METHOD]: US_CALC,
		[EXPORT_METHOD]: (args) => (args.address === BILLING ? { country: "India" } : {}),
		[NEXUS_METHOD]: null,
		[REGION_METHOD]: null,
	});
}

/** A draft with a customer on it and no address yet. */
function open_draft(doctype) {
	return make_frm({
		doctype,
		company: US_CALC.company,
		is_new: true,
		fields: TRANSACTION_FIELDS,
		doc: { customer: "CUST-0003", party_name: "CUST-0003" },
	});
}

/**
 * Write the party's defaults the way erpnext writes them.
 *
 * One field at a time, each firing its own handler, with the flag set for the
 * whole run - then the flag cleared and one refresh, which is what party.js
 * does at the end.
 */
async function write_party_details(frm, doctype) {
	frm.updating_party_details = true;

	frm.doc.customer_address = BILLING;
	await forms[doctype].customer_address(frm);
	await flush();

	frm.doc.shipping_address_name = SHIPPING;
	await forms[doctype].shipping_address_name(frm);
	await flush();

	frm.updating_party_details = false;
	await forms[doctype].refresh(frm);
	await flush();
	await flush();
}

describe.each(TRANSACTION_DOCTYPES)("%s", (doctype) => {
	it("shows no strip while the party's defaults are still landing", async () => {
		// The bug, stated as the reader saw it: a yellow strip for a split
		// second on picking a customer.
		answer_every_read();
		const frm = open_draft(doctype);

		frm.updating_party_details = true;
		frm.doc.customer_address = BILLING;
		await forms[doctype].customer_address(frm);
		await flush();
		await flush();

		expect(message_text(frm)).toBe("");
	});

	it("asks nothing while the party's defaults are still landing", async () => {
		answer_every_read();
		const frm = open_draft(doctype);

		frm.updating_party_details = true;
		frm.doc.customer_address = BILLING;
		await forms[doctype].customer_address(frm);
		await flush();

		expect(frappe.xcall).not.toHaveBeenCalled();
	});

	it("says nothing about an export once both addresses have landed", async () => {
		// Arizona decides it, not the billing address that landed first.
		answer_every_read();
		const frm = open_draft(doctype);

		await write_party_details(frm, doctype);

		expect(message_text(frm)).toBe("");
	});

	it("reads the ship-to address, not the one that landed first", async () => {
		answer_every_read();
		const frm = open_draft(doctype);

		await write_party_details(frm, doctype);

		const asked = frappe.xcall.mock.calls
			.filter(([method]) => method === EXPORT_METHOD)
			.map(([, args]) => args.address);
		expect(asked).toContain(SHIPPING);
		expect(asked).not.toContain(BILLING);
	});

	it("still says so when the ship-to address really is an export", async () => {
		// The guard defers the answer; it does not swallow it.
		answer_xcall(frappe, {
			[SCOPE_METHOD]: US_CALC,
			[EXPORT_METHOD]: { country: "India" },
			[NEXUS_METHOD]: null,
			[REGION_METHOD]: null,
		});
		const frm = open_draft(doctype);

		await write_party_details(frm, doctype);

		expect(message_text(frm)).toContain(
			"Sales taxes are not applicable on export transactions."
		);
	});
});

describe("the exemption fields", () => {
	it("are left alone while the party's defaults are still landing", async () => {
		// This one writes to the document as well as reading it, so running it
		// mid-write would put a set_value of its own between erpnext's.
		answer_every_read();
		const frm = open_draft("Sales Invoice");

		frm.updating_party_details = true;
		frm.doc.customer_address = BILLING;
		await forms["Sales Invoice"].customer_address(frm);
		await flush();

		expect(frm.set_value).not.toHaveBeenCalled();
		expect(frm.set_df_property).not.toHaveBeenCalled();
	});
});

describe("the sidebar pill", () => {
	it("is left alone while the party's defaults are still landing", async () => {
		// It reads the destination too, so it would flicker with the strip.
		answer_every_read();
		const frm = open_draft("Sales Invoice");

		frm.updating_party_details = true;
		frm.doc.customer_address = BILLING;
		await forms["Sales Invoice"].customer_address(frm);
		await flush();

		expect(sidebar_section()).toHaveLength(0);
	});
});
