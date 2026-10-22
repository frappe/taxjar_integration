// _render_empty_status - the one place in the client that reads `reason`
// rather than a boolean. Design doc §3.4.
//
// "Registered elsewhere" and "switched off" are both no, and they are not the
// same no: one names a setting the reader can go and change, the other names
// the company's country, which is not changed in TaxJar at all.

import { beforeEach, describe, expect, it } from "vitest";

import {
	IN_CO,
	IN_FLAGGED,
	US_CALC,
	US_OFF,
	US_UNCONFIGURED,
	answer_scope,
	flush,
	install_desk,
	load_taxjar_utils,
	make_frm,
} from "./helpers/desk.js";

let frappe;
let taxjar;

beforeEach(() => {
	frappe = install_desk();
	taxjar = load_taxjar_utils();
});

const STATUS_FIELDS = ["taxjar_status_html"];

async function render(profile, options = {}) {
	answer_scope(frappe, profile);

	const frm = make_frm({
		company: profile.company,
		fields: STATUS_FIELDS,
		...options,
	});
	taxjar.render_status_cards(frm);
	await flush();

	return frm.fields_dict.taxjar_status_html.$wrapper;
}

describe("a document with nothing evaluated on it", () => {
	it("says the status comes after saving, on a new document", async () => {
		const wrapper = await render(US_CALC, { is_new: true });

		expect(wrapper.text()).toContain("Tax status will be available after saving.");
		expect(frappe.xcall).not.toHaveBeenCalled();
	});

	it("says the status comes after saving, on a saved document that calculates", async () => {
		const wrapper = await render(US_CALC);

		expect(wrapper.text()).toContain("Tax status will be available after saving.");
	});
});

describe("a company registered outside the United States", () => {
	// Said before the calculation switch, because it is the reason that would
	// still hold if the switch were on.
	it.each([IN_CO, IN_FLAGGED])("names the country for $company", async (profile) => {
		const wrapper = await render(profile);

		expect(wrapper.text()).toContain(
			`${profile.company} is based in India, and TaxJar only handles United States sales tax`
		);
	});

	it("falls back to a message with no country when the country is unknown", async () => {
		const wrapper = await render({ ...IN_CO, country: null });

		expect(wrapper.text()).toContain(
			`${IN_CO.company} is not based in the United States, and TaxJar only handles United States sales tax`
		);
	});

	// The setup page holds nothing that can resolve this, and the country is
	// changed on the Company, not in TaxJar.
	it("offers no setup link", async () => {
		const wrapper = await render(IN_CO);

		expect(wrapper.find("a").length).toBe(0);
	});

	it("does not say the calculation switch is off", async () => {
		const wrapper = await render(IN_CO);

		expect(wrapper.text()).not.toContain("turned off");
	});
});

describe("a company in the United States that does not calculate", () => {
	it.each([US_OFF, US_UNCONFIGURED])(
		"says the switch is off, and where to change it, for $company",
		async (profile) => {
			const wrapper = await render(profile);

			expect(wrapper.text()).toContain(
				`Sales tax calculation is turned off for ${profile.company}`
			);
			expect(wrapper.find("a").attr("href")).toBe("/app/taxjar-setup?focus=features");
		}
	);

	// "After saving" sent the reader round a loop that could not end: saving
	// again would change nothing.
	it("does not tell the reader to save again", async () => {
		const wrapper = await render(US_OFF);

		expect(wrapper.text()).not.toContain("after saving");
	});
});

describe("the company name in the message", () => {
	it("is escaped", async () => {
		const wrapper = await render({ ...US_OFF, company: '<script>alert("x")</script>' });

		expect(wrapper.find("script").length).toBe(0);
		expect(wrapper.html()).toContain("&lt;script&gt;");
	});
});

describe("an answer that arrives late", () => {
	// The reader has moved to another document by the time the scope lands.
	// Writing it then would put one document's status on another's form.
	it("is dropped when the form has moved on", async () => {
		let settle;
		frappe.xcall.mockImplementation(
			() => new Promise((resolve) => {
				settle = resolve;
			})
		);

		const frm = make_frm({ company: IN_CO.company, fields: STATUS_FIELDS });
		taxjar.render_status_cards(frm);

		frm.doc.name = "SINV-0002";
		settle(IN_CO);
		await flush();

		expect(frm.fields_dict.taxjar_status_html.$wrapper.text().trim()).toBe("");
	});

	// Emptied rather than filled with a guess: a wrong message that corrects
	// itself a moment later reads worse than a blank that fills in.
	it("leaves the panel blank until it lands, rather than guessing", async () => {
		frappe.xcall.mockImplementation(() => new Promise(() => {}));

		const frm = make_frm({ company: IN_CO.company, fields: STATUS_FIELDS });
		taxjar.render_status_cards(frm);
		await flush();

		expect(frm.fields_dict.taxjar_status_html.$wrapper.text().trim()).toBe("");
	});
});
