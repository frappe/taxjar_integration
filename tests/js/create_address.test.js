// Creating the customer's first address, without leaving the transaction.
//
// The strip on a document with no address offers "Create Address". That used to
// open the Address form: the reader left the document, saved an address, came
// back, and linked it by hand. The address never reached the transaction on its
// own, and neither did the two preferred-address flags, because the quick entry
// frappe builds for an Address leaves both boxes out.
//
// So the three things this file holds: the dialog collects what a sale is
// priced on, the new address lands on the document, and nobody is routed away.

import { beforeEach, describe, expect, it } from "vitest";

import {
	US_CALC,
	answer_xcall,
	flush,
	install_desk,
	load_taxjar_utils,
	make_frm,
	record_dialogs,
} from "./helpers/desk.js";

const MOD = "taxjar_integration.taxjar_integration.taxjar_integration";
const CREATE_METHOD = `${MOD}.create_customer_address`;
const REGION_METHOD = `${MOD}.resolve_region_code`;

let frappe;
let taxjar;

beforeEach(() => {
	frappe = install_desk();
	taxjar = load_taxjar_utils();
});

/** A transaction with no address, and the dialog the strip's link opens on it. */
function open_dialog({ doc = {}, options } = {}) {
	const frm = make_frm({
		doctype: "Sales Invoice",
		company: US_CALC.company,
		doc: { customer: "Acme Inc", ...doc },
	});
	const opened = record_dialogs();
	taxjar._open_new_address(frm, options);
	return { frm, d: opened[0] };
}

/** Fill every box the dialog requires, and press Create. */
function create(d, values = {}) {
	// Country first. The box already holds the United States, but the state
	// box asks the server for a region code on every change, and a United
	// States address needs none. See _refresh_dialog_codes.
	const filled = {
		country: "United States",
		address_line1: "1 Test Road",
		city: "Austin",
		state: "Texas",
		pincode: "73301",
		...values,
	};
	for (const [fieldname, value] of Object.entries(filled)) {
		d.set_value(fieldname, value);
	}
	return d.options.primary_action(d.get_values());
}

/** The fieldnames of the boxes the dialog offers, in order. */
function boxes(d) {
	return d.options.fields
		.filter((field) => field.fieldname && field.fieldname !== "why")
		.map((field) => field.fieldname);
}

describe("the Create Address dialog", () => {
	it("asks for the five fields a sale is priced on", () => {
		const { d } = open_dialog();

		// Three are mandatory on the Address doctype. The other two are what
		// TaxJar refuses a transaction without, and the save-time dialog would
		// ask for them again at the next save.
		const required = d.options.fields
			.filter((field) => field.reqd)
			.map((field) => field.fieldname);

		expect(required).toContain("address_line1");
		expect(required).toContain("city");
		expect(required).toContain("country");
		expect(required).toContain("state");
		expect(required).toContain("pincode");
	});

	it("offers both preferred-address flags", () => {
		// The pair the Address form carries and its quick entry leaves out.
		// This is the customer's first address, so these decide what every
		// later transaction picks up on its own.
		const { d } = open_dialog();

		expect(boxes(d)).toContain("is_primary_address");
		expect(boxes(d)).toContain("is_shipping_address");
	});

	it("names the address after the customer", () => {
		const { d } = open_dialog();

		expect(d.get_value("address_title")).toBe("Acme Inc");
	});

	it("opens no Address form", () => {
		// The page this dialog exists to avoid.
		const { d } = open_dialog();

		expect(d).toBeDefined();
		expect(frappe.new_doc).not.toHaveBeenCalled();
		expect(frappe.set_route).not.toHaveBeenCalled();
	});

	it("does nothing on a document with no customer", () => {
		const frm = make_frm({ doctype: "Sales Invoice", doc: {} });
		const opened = record_dialogs();
		taxjar._open_new_address(frm);

		expect(opened).toHaveLength(0);
	});
});

describe("Create", () => {
	it("sends the boxes to the server under this customer", async () => {
		answer_xcall(frappe, { [CREATE_METHOD]: { name: "Acme Inc-Shipping" } });

		const { d } = open_dialog();
		await create(d, { is_shipping_address: 1 });

		const [method, args] = frappe.xcall.mock.calls[0];
		expect(method).toBe(CREATE_METHOD);
		expect(args.customer).toBe("Acme Inc");
		expect(JSON.parse(args.values)).toMatchObject({
			address_line1: "1 Test Road",
			city: "Austin",
			state: "Texas",
			pincode: "73301",
			country: "United States",
			taxjar_state_code: "TX",
			is_shipping_address: 1,
		});
	});

	it("puts the new address on the transaction", async () => {
		// The whole point. The reader answered one dialog and the document now
		// names the address, with nothing left to link by hand.
		answer_xcall(frappe, { [CREATE_METHOD]: { name: "Acme Inc-Shipping" } });

		const { frm, d } = open_dialog();
		await create(d);

		expect(frm.doc.shipping_address_name).toBe("Acme Inc-Shipping");
		expect(frm.doc.customer_address).toBe("Acme Inc-Shipping");
		expect(d.hide).toHaveBeenCalled();
	});

	it("leaves a billing address the document already names", async () => {
		// This document reached the dialog for a delivery address. Overwriting
		// the billing address would answer a question nobody asked.
		answer_xcall(frappe, { [CREATE_METHOD]: { name: "Acme Inc-Shipping" } });

		const { frm, d } = open_dialog({ doc: { customer_address: "Acme Inc-Billing" } });
		await create(d);

		expect(frm.doc.customer_address).toBe("Acme Inc-Billing");
		expect(frm.doc.shipping_address_name).toBe("Acme Inc-Shipping");
	});

	it("routes nobody away from the transaction", async () => {
		answer_xcall(frappe, { [CREATE_METHOD]: { name: "Acme Inc-Shipping" } });

		const { d } = open_dialog();
		await create(d);

		expect(frappe.set_route).not.toHaveBeenCalled();
	});

	it("makes the save again when a save opened it", async () => {
		// The two save-time prompts pass save_after. The picker beside them
		// ends the same way: fix what blocked the save, then make it again.
		answer_xcall(frappe, { [CREATE_METHOD]: { name: "Acme Inc-Shipping" } });

		const { frm, d } = open_dialog({ options: { save_after: true } });
		await create(d);

		expect(frm.save).toHaveBeenCalled();
	});

	it("saves nothing when the strip's own link opened it", async () => {
		// The strip is a note on an open document, not a blocked save. A save
		// the reader did not ask for would write a draft they were still
		// editing.
		answer_xcall(frappe, { [CREATE_METHOD]: { name: "Acme Inc-Shipping" } });

		const { frm, d } = open_dialog();
		await create(d);

		expect(frm.save).not.toHaveBeenCalled();
	});
});

describe("the country box", () => {
	it("holds the United States before the reader types anything", () => {
		// Every company this app serves is registered there, so a reader
		// delivering at home changes no box at all.
		const { d } = open_dialog();

		expect(d.get_value("country")).toBe("United States");
	});
});

describe("the layout", () => {
	/** The groups of boxes, in order, as the dialog was built with them. */
	function groups(d) {
		const grouped = [[]];

		for (const field of d.options.fields) {
			if (field.fieldtype === "Section Break") grouped.push([]);
			if (field.fieldtype === "Section Break") continue;
			grouped[grouped.length - 1].push(field);
		}

		return grouped.filter((group) => group.length);
	}

	it("pins no box to a cell of its own", () => {
		// A Column Break draws a fixed grid: a box the country hides leaves its
		// cell empty, and the boxes after it stay where they are - which is the
		// hole that opened above Country. The boxes are laid out as a CSS grid
		// instead, and a hidden box takes no cell at all.
		const { d } = open_dialog();

		expect(d.options.fields.map((field) => field.fieldtype)).not.toContain("Column Break");
	});

	it("lays every group out as a grid", () => {
		const { d } = open_dialog();
		const breaks = d.options.fields.filter((field) => field.fieldtype === "Section Break");

		expect(breaks.length).toBeGreaterThan(0);
		for (const field of breaks) {
			expect(field.css_class).toBe("taxjar-address-grid");
		}
	});

	it("keeps the two flags in a group of their own", () => {
		// So they sit side by side under the address, whatever the row above
		// them ended on.
		const { d } = open_dialog();
		const last = groups(d)[groups(d).length - 1];

		expect(last.map((field) => field.fieldname)).toEqual([
			"is_primary_address",
			"is_shipping_address",
		]);
	});

	it("writes the country once the dialog is on the screen", () => {
		// A default alone is judged before it reaches the box, so the two code
		// boxes would both start hidden. A write settles them.
		const { d } = open_dialog();

		expect(d.set_value).toHaveBeenCalledWith("country", "United States");
	});
});

describe("the State Code box", () => {
	/** The box definition, as the dialog was built with it. */
	function state_code_box(d) {
		return d.options.fields.find((field) => field.fieldname === "taxjar_state_code");
	}

	it("shows only for a United States address", () => {
		// A United States sale is filed under the state code. Everywhere else
		// it is filed under the ISO 3166-2 region code, and the box beside this
		// one holds that.
		const { d } = open_dialog();

		expect(state_code_box(d).depends_on).toBe('eval:doc.country === "United States"');
		expect(state_code_box(d).mandatory_depends_on).toBe(
			'eval:doc.country === "United States"'
		);
	});

	it("offers the fifty codes under their state names", () => {
		const { d } = open_dialog();
		const options = state_code_box(d).options;

		expect(options).toContainEqual({ label: "AZ — Arizona", value: "AZ" });
	});

	it("fills itself from the state the reader typed", async () => {
		const { d } = open_dialog();
		await d.set_value("state", "Arizona");

		expect(d.get_value("taxjar_state_code")).toBe("AZ");
	});

	it("reads a code typed into the State box as that code", async () => {
		const { d } = open_dialog();
		await d.set_value("state", "az");

		expect(d.get_value("taxjar_state_code")).toBe("AZ");
	});

	it("fills the State box when the reader picks a code", async () => {
		const { d } = open_dialog();
		await d.set_value("taxjar_state_code", "AZ");

		expect(d.get_value("state")).toBe("Arizona");
	});

	it("clears itself once the address leaves the United States", async () => {
		// The box is hidden now, and the state it names is not where this sale
		// is delivered.
		answer_xcall(frappe, { [REGION_METHOD]: { region_code: "GJ" } });

		const { d } = open_dialog();
		await d.set_value("state", "Arizona");
		expect(d.get_value("taxjar_state_code")).toBe("AZ");

		await d.set_value("country", "India");
		await flush();

		expect(d.get_value("taxjar_state_code")).toBe("");
	});
});

describe("the region code box", () => {
	it("works the code out from the state, as the save-time dialog does", async () => {
		answer_xcall(frappe, { [REGION_METHOD]: { region_code: "GJ" } });

		const { d } = open_dialog();
		await d.set_value("country", "India");
		await d.set_value("state", "Gujarat");
		await flush();

		expect(d.get_value("taxjar_region_code")).toBe("GJ");
	});

	it("stays hidden for a United States address", () => {
		// The state code box beside it holds that answer.
		const { d } = open_dialog();
		const box = d.options.fields.find((field) => field.fieldname === "taxjar_region_code");

		expect(box.depends_on).toBe('eval:doc.country && doc.country !== "United States"');
	});
});
