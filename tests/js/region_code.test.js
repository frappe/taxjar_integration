// The region code an export is filed under.
//
// It is not typed. It comes from the country and the state, and ISO 3166-2
// lists thousands of regions across 250 countries - so the form asks the server
// for it, on every change to either box, and shows the answer while the reader
// is still on the address.
//
// Two places ask: the Address form, and the save-time dialog on a transaction
// whose delivery address is not complete yet. One rule holds in both. What the
// script wrote, the script replaces. What the reader typed stays.

import { beforeEach, describe, expect, it } from "vitest";

import {
	answer_xcall,
	flush,
	install_desk,
	load_address_form,
	load_taxjar_utils,
	make_frm,
	record_dialogs,
} from "./helpers/desk.js";

const MOD = "taxjar_integration.taxjar_integration.taxjar_integration";
const REGION_METHOD = `${MOD}.resolve_region_code`;

const ADDRESS_FIELDS = ["taxjar_state_code", "taxjar_region_code"];

let frappe;
let taxjar;
let address;

beforeEach(() => {
	frappe = install_desk();
	taxjar = load_taxjar_utils();
	address = load_address_form();
});

/** An Address form, open on the country and state given. */
function open_address(doc = {}) {
	return make_frm({
		doctype: "Address",
		fields: ADDRESS_FIELDS,
		doc: { country: "India", ...doc },
	});
}

/** The sentence the form put under the Region Code box. */
function region_hint(frm) {
	return frm.fields_dict["taxjar_region_code"].df.description || "";
}

describe("the Address form", () => {
	it("works out the code when the state changes", async () => {
		answer_xcall(frappe, { [REGION_METHOD]: { region_code: "GJ" } });

		const frm = open_address({ state: "Gujarat" });
		await address.state(frm);

		expect(frm.doc.taxjar_region_code).toBe("GJ");
		expect(frappe.xcall).toHaveBeenCalledWith(REGION_METHOD, {
			country: "India",
			state: "Gujarat",
		});
	});

	it("works out the code when the country changes", async () => {
		answer_xcall(frappe, { [REGION_METHOD]: { region_code: "BY" } });

		const frm = open_address({ country: "Germany", state: "Bayern" });
		await address.country(frm);

		expect(frm.doc.taxjar_region_code).toBe("BY");
	});

	it("says the code comes from the state when the state produced a code", async () => {
		answer_xcall(frappe, { [REGION_METHOD]: { region_code: "GJ" } });

		const frm = open_address({ state: "Gujarat" });
		await address.state(frm);

		expect(region_hint(frm)).toBe("Auto-filled based on State/Province.");
	});

	it("writes the stand-in and says so when no region matched", async () => {
		// Singapore has no ISO region to match. The reader is told so here
		// rather than by a dialog on the next invoice, and the box holds the
		// stand-in that TaxJar takes.
		answer_xcall(frappe, { [REGION_METHOD]: { region_code: "" } });

		const frm = open_address({ country: "Singapore", state: "Singapore" });
		await address.state(frm);

		expect(frm.doc.taxjar_region_code).toBe("XX");
		expect(region_hint(frm)).toBe("Cannot find region code, using fallback code.");
	});

	it("says the code comes from the state while the state box is empty", async () => {
		const frm = open_address({ country: "Germany", state: "" });
		await address.country(frm);

		expect(region_hint(frm)).toBe("Auto-filled based on State/Province.");
	});

	it("replaces its own answer when the state changes again", async () => {
		answer_xcall(frappe, { [REGION_METHOD]: { region_code: "GJ" } });
		const frm = open_address({ state: "Gujarat" });
		await address.state(frm);

		answer_xcall(frappe, { [REGION_METHOD]: { region_code: "MH" } });
		frm.doc.state = "Maharashtra";
		await address.state(frm);

		expect(frm.doc.taxjar_region_code).toBe("MH");
	});

	it("leaves a code the reader typed alone", async () => {
		answer_xcall(frappe, { [REGION_METHOD]: { region_code: "GJ" } });

		const frm = open_address({ state: "Gujarat", taxjar_region_code: "DL" });
		await address.state(frm);

		expect(frm.doc.taxjar_region_code).toBe("DL");
		expect(frappe.xcall).not.toHaveBeenCalled();
	});

	it("replaces a saved stand-in once the state names a region", async () => {
		// The stand-in is never the reader's answer. A real region beats it,
		// and a state with no match writes the stand-in again.
		answer_xcall(frappe, { [REGION_METHOD]: { region_code: "GJ" } });

		const frm = open_address({ state: "Gujarat", taxjar_region_code: "XX" });
		await address.state(frm);

		expect(frm.doc.taxjar_region_code).toBe("GJ");
	});

	it("asks nothing for a United States address, and clears a code left behind", async () => {
		// taxjar_state_code carries the answer there, and the box is hidden.
		const frm = open_address({
			country: "United States",
			state: "Florida",
			taxjar_region_code: "GJ",
		});
		await address.country(frm);

		expect(frm.doc.taxjar_region_code).toBe("");
		expect(frappe.xcall).not.toHaveBeenCalled();
	});

	it("asks nothing while the state box is empty", async () => {
		// A reader picks the country first and types the state after it. The
		// server answers "" to every one of those picks, so the trip is skipped
		// and the code this script wrote for the country before it goes.
		answer_xcall(frappe, {});

		const frm = open_address({ country: "Germany", state: "" });
		frm.__taxjar_region_code = "GJ";
		frm.doc.taxjar_region_code = "GJ";
		await address.country(frm);

		expect(frm.doc.taxjar_region_code).toBe("");
		expect(frappe.xcall).not.toHaveBeenCalled();
	});

	it("asks nothing on a site where the field was never installed", async () => {
		const frm = make_frm({ doctype: "Address", fields: [], doc: { country: "India" } });
		await address.state(frm);

		expect(frappe.xcall).not.toHaveBeenCalled();
	});
});

describe("the State Code on the Address form", () => {
	/** The sentence the form put under the State Code box. */
	function state_hint(frm) {
		return frm.fields_dict["taxjar_state_code"].df.description || "";
	}

	it("says the code comes from the state when the state names one", async () => {
		const frm = open_address({ country: "United States", state: "Texas" });
		await address.state(frm);

		expect(frm.doc.taxjar_state_code).toBe("TX");
		expect(state_hint(frm)).toBe("Auto-filled based on State/Province.");
	});

	it("asks for the code from the dropdown when the state names none", async () => {
		const frm = open_address({ country: "United States", state: "Nowhere" });
		await address.state(frm);

		expect(state_hint(frm)).toBe("Cannot find state code, please select from dropdown.");
	});
});

describe("the save-time dialog", () => {
	/** Open the dialog on one address row, and hand back the dialog. */
	function open_dialog(row = {}, missing = []) {
		const opened = record_dialogs();
		taxjar._show_destination_address_dialog(make_frm(), {
			name: "ADDR-IN",
			address_line1: "1 Test Road",
			city: "Surat",
			state: "",
			pincode: "395007",
			country: "India",
			region_code: taxjar.UNKNOWN_REGION_CODE,
			region_placeholder: true,
			...row,
		}, missing);
		return opened[0];
	}

	/** The sentence the dialog put under the Region Code box. */
	function hint(d) {
		return d.fields_dict["taxjar_region_code"].df.description || "";
	}

	it("turns the stand-in into a real code once the state names a region", async () => {
		answer_xcall(frappe, { [REGION_METHOD]: { region_code: "GJ" } });

		const d = open_dialog();
		expect(d.get_value("taxjar_region_code")).toBe(taxjar.UNKNOWN_REGION_CODE);

		await d.set_value("state", "Gujarat");
		await flush();

		expect(d.get_value("taxjar_region_code")).toBe("GJ");
		expect(hint(d)).toBe("Auto-filled based on State/Province.");
	});

	it("keeps the stand-in when the new state names no region", async () => {
		answer_xcall(frappe, { [REGION_METHOD]: { region_code: "" } });

		const d = open_dialog();
		await d.set_value("state", "Nowhere");
		await flush();

		expect(d.get_value("taxjar_region_code")).toBe(taxjar.UNKNOWN_REGION_CODE);
		expect(hint(d)).toBe("Cannot find region code, using fallback code.");
	});

	it("works out the code again when the country changes", async () => {
		answer_xcall(frappe, { [REGION_METHOD]: { region_code: "ON" } });

		const d = open_dialog({ state: "Ontario" });
		await d.set_value("country", "Canada");
		await flush();

		expect(d.get_value("taxjar_region_code")).toBe("ON");
	});

	it("leaves a code the reader typed alone", async () => {
		answer_xcall(frappe, { [REGION_METHOD]: { region_code: "GJ" } });

		const d = open_dialog();
		await d.set_value("taxjar_region_code", "DL");
		await d.set_value("state", "Gujarat");
		await flush();

		expect(d.get_value("taxjar_region_code")).toBe("DL");
		expect(frappe.xcall).not.toHaveBeenCalled();
	});

	it("asks nothing while the state box is empty", async () => {
		// The stand-in is what the server would answer, and the box shows it
		// again rather than the code the country before it produced.
		answer_xcall(frappe, {});

		const d = open_dialog({ state: "" });
		d.set_value("taxjar_region_code", "ON");
		d.__taxjar_region_code = "ON";
		await d.set_value("country", "India");
		await flush();

		expect(d.get_value("taxjar_region_code")).toBe(taxjar.UNKNOWN_REGION_CODE);
		expect(frappe.xcall).not.toHaveBeenCalled();
	});

	it("says where the code comes from when it opens with no state", () => {
		const d = open_dialog({ state: "" });

		expect(hint(d)).toBe("Auto-filled based on State/Province.");
	});

	it("says where the code comes from again when the state is cleared", async () => {
		answer_xcall(frappe, { [REGION_METHOD]: { region_code: "" } });

		const d = open_dialog({ state: "Nowhere" });
		expect(hint(d)).toBe("Cannot find region code, using fallback code.");

		await d.set_value("state", "");
		await flush();

		expect(hint(d)).toBe("Auto-filled based on State/Province.");
	});

	it("asks nothing while the country is the United States", async () => {
		const d = open_dialog({ country: "United States" });
		await d.set_value("state", "Florida");
		await flush();

		expect(frappe.xcall).not.toHaveBeenCalled();
	});

	it("takes the red outline off the box once it holds a real code", async () => {
		answer_xcall(frappe, { [REGION_METHOD]: { region_code: "GJ" } });

		const d = open_dialog();
		const box = d.fields_dict["taxjar_region_code"].$wrapper;
		expect(box.hasClass("has-error")).toBe(true);

		await d.set_value("state", "Gujarat");
		await flush();

		expect(box.hasClass("has-error")).toBe(false);
	});
});
