// The gate on every client entry point, against every company profile.
//
// This is the table in §3.4 of the company-scope design, turned into
// assertions. Each entry point takes the gate and hands the work to a private
// body, so the test drives the public name and watches the body: that is the
// arrangement that makes the gate impossible to bypass, and it is what the
// spies below check.

import { beforeEach, describe, expect, it, vi } from "vitest";

import {
	ALL_PROFILES,
	IN_CO,
	IN_FLAGGED,
	US_CALC,
	US_FILE,
	US_OFF,
	US_SITE_OFF,
	US_UNCONFIGURED,
	answer_scope,
	flush,
	install_desk,
	load_taxjar_utils,
	make_frm,
	sidebar_section,
} from "./helpers/desk.js";

let frappe;
let taxjar;

beforeEach(() => {
	frappe = install_desk();
	taxjar = load_taxjar_utils();
});

/** The profiles for which a gate should let the work through. */
const passes = {
	uses_taxjar: [US_CALC, US_FILE],
	calculates: [US_CALC],
	files: [US_FILE],
	in_scope: [US_CALC, US_FILE, US_OFF],
	// The sidebar is the one place that renders for a company out of scope. A
	// site switch that is off, and a company TaxJar could serve that nobody has
	// configured, are both something the reader can go and change - so both get
	// the setup link rather than an empty column. Only a company registered
	// outside the United States gets nothing, because nothing on the setup page
	// can help it.
	has_sidebar: [US_CALC, US_FILE, US_OFF, US_UNCONFIGURED, US_SITE_OFF],
};

function should_pass(gate, profile) {
	return passes[gate].includes(profile);
}

/**
 * Drive one entry point for one company and report whether the body ran.
 *
 * The body is replaced with a spy after the file is loaded, so the real gate
 * runs and only the work behind it is stubbed.
 */
async function run_entry_point({ entry, body, profile, doc = {}, fields }) {
	answer_scope(frappe, profile);

	// The same rule audit_conventions.py applies to the Python suite: a spy has
	// to name something the code still defines. Without this, renaming the body
	// leaves the spy on a dead property, and every out-of-scope case goes on
	// passing while asserting nothing.
	if (typeof taxjar[entry] !== "function") {
		throw new Error(`no such entry point: taxjar_integration.${entry}`);
	}
	if (typeof taxjar[body] !== "function") {
		throw new Error(`no such body: taxjar_integration.${body} - has it been renamed?`);
	}

	taxjar[body] = vi.fn(() => Promise.resolve());

	const frm = make_frm({ company: profile.company, doc, ...(fields ? { fields } : {}) });
	await taxjar[entry](frm);
	await flush();

	return { frm, ran: taxjar[body].mock.calls.length > 0 };
}

describe("check_shipping_address", () => {
	const doc = { customer: "Acme Corp" };

	it.each(ALL_PROFILES)("gates on uses_taxjar for $company", async (profile) => {
		const { ran } = await run_entry_point({
			entry: "check_shipping_address",
			body: "_prompt_for_shipping_address",
			profile,
			doc,
		});

		expect(ran).toBe(should_pass("uses_taxjar", profile));
	});

	it("does not ask about scope at all when the form already has a shipping address", async () => {
		answer_scope(frappe, US_CALC);
		taxjar._prompt_for_shipping_address = vi.fn();

		const frm = make_frm({
			company: US_CALC.company,
			doc: { ...doc, shipping_address_name: "Acme-Shipping" },
		});
		await taxjar.check_shipping_address(frm);
		await flush();

		expect(frappe.xcall).not.toHaveBeenCalled();
		expect(taxjar._prompt_for_shipping_address).not.toHaveBeenCalled();
	});

	it("does not ask about scope for a Quotation to a Lead", async () => {
		answer_scope(frappe, US_CALC);
		taxjar._prompt_for_shipping_address = vi.fn();

		const frm = make_frm({
			doctype: "Quotation",
			company: US_CALC.company,
			doc: { quotation_to: "Lead", party_name: "LEAD-0001" },
		});
		await taxjar.check_shipping_address(frm);
		await flush();

		expect(frappe.xcall).not.toHaveBeenCalled();
		expect(taxjar._prompt_for_shipping_address).not.toHaveBeenCalled();
	});
});

describe("confirm_foreign_tax_rows", () => {
	it.each(ALL_PROFILES)("gates on uses_taxjar for $company", async (profile) => {
		const { ran } = await run_entry_point({
			entry: "confirm_foreign_tax_rows",
			body: "_confirm_foreign_tax_rows",
			profile,
		});

		expect(ran).toBe(should_pass("uses_taxjar", profile));
	});
});

describe("apply_region_exemption", () => {
	it.each(ALL_PROFILES)("gates on uses_taxjar for $company", async (profile) => {
		const { ran } = await run_entry_point({
			entry: "apply_region_exemption",
			body: "_apply_region_exemption",
			profile,
			doc: { customer: "Acme Corp", shipping_address_name: "Acme-Shipping" },
		});

		expect(ran).toBe(should_pass("uses_taxjar", profile));
	});

	// Locking the exemption fields is a statement that TaxJar has decided the
	// matter. For a company it does not serve it has decided nothing.
	it("leaves the exemption fields writable for a company out of scope", async () => {
		answer_scope(frappe, IN_CO);

		const frm = make_frm({
			company: IN_CO.company,
			fields: ["taxjar_transaction_exempt", "taxjar_transaction_exemption_type"],
			doc: { customer: "Acme Corp", shipping_address_name: "Acme-Shipping" },
		});
		await taxjar.apply_region_exemption(frm);
		await flush();

		expect(frm.fields_dict.taxjar_transaction_exempt.df.read_only).toBe(0);
		expect(frm.fields_dict.taxjar_transaction_exemption_type.df.read_only).toBe(0);
	});
});

describe("show_no_address_tax_message", () => {
	it.each(ALL_PROFILES)("gates on calculates for $company", async (profile) => {
		const { ran } = await run_entry_point({
			entry: "show_no_address_tax_message",
			body: "_show_tax_message",
			profile,
			doc: { customer: "Acme Corp" },
		});

		expect(ran).toBe(should_pass("calculates", profile));
	});

	// A company that only files gets no tax figure, so "hence taxes are not
	// calculated" would be a statement about a feature it does not have.
	it("stays silent for a company that only files", async () => {
		answer_scope(frappe, US_FILE);

		const frm = make_frm({ company: US_FILE.company, doc: { customer: "Acme Corp" } });
		await taxjar.show_no_address_tax_message(frm);
		await flush();

		expect(frm.layout.message.text()).toBe("");
	});
});

describe("toggle_taxjar_ui", () => {
	const TABS = ["taxjar_tab", "taxjar_exemption_section", "taxjar_breakdown_section"];

	it.each(ALL_PROFILES)("gates on in_scope for $company", async (profile) => {
		answer_scope(frappe, profile);

		const frm = make_frm({ company: profile.company });
		await taxjar.toggle_taxjar_ui(frm);

		const expected_hidden = should_pass("in_scope", profile) ? 0 : 1;
		for (const fieldname of TABS) {
			expect(frm.fields_dict[fieldname].df.hidden).toBe(expected_hidden);
		}
	});

	// A tab kept for a company TaxJar cannot serve is a tab full of sections
	// that can never say anything.
	it("hides the tab when the scope could not be read", async () => {
		frappe.xcall.mockRejectedValue(new Error("network"));

		const frm = make_frm({ company: US_CALC.company });
		await taxjar.toggle_taxjar_ui(frm);

		for (const fieldname of TABS) {
			expect(frm.fields_dict[fieldname].df.hidden).toBe(1);
		}
	});
});

describe("render_sync_status_sidebar_pill", () => {
	const fields = ["taxjar_sync_status"];

	async function render(profile, doc = {}) {
		answer_scope(frappe, profile);
		taxjar._render_taxjar_sync_status_pill = vi.fn();

		const frm = make_frm({ company: profile.company, fields, doc });
		taxjar.render_sync_status_sidebar_pill(frm);
		await flush();

		return frm;
	}

	it.each(ALL_PROFILES)("renders for $company only when TaxJar can help it", async (profile) => {
		await render(profile, { taxjar_sync_status: "Queued" });

		const rendered = taxjar._render_taxjar_sync_status_pill.mock.calls.length > 0;
		const linked = sidebar_section().length > 0;

		expect(rendered || linked).toBe(should_pass("has_sidebar", profile));
	});

	it("shows the sync pill for a company that files", async () => {
		await render(US_FILE, { taxjar_sync_status: "Queued" });

		expect(taxjar._render_taxjar_sync_status_pill).toHaveBeenCalledTimes(1);
		expect(sidebar_section().length).toBe(0);
	});

	// In scope but not filing: there is no sync state to report, so no label and
	// no pill - only a link to the setting that would create one.
	it("shows a setup link instead for a company in scope that does not file", async () => {
		await render(US_CALC, { taxjar_sync_status: "Queued" });

		expect(taxjar._render_taxjar_sync_status_pill).not.toHaveBeenCalled();

		const section = sidebar_section();
		expect(section.length).toBe(1);
		expect(section.find("a.taxjar-not-enabled-link").attr("href")).toBe(
			"/app/taxjar-setup?focus=features"
		);
	});

	// No link for a company registered outside the United States: the setup page
	// has nothing to offer a company TaxJar cannot serve, so the link would be a
	// dead end.
	it.each([IN_CO, IN_FLAGGED])("offers no setup link for $company", async (profile) => {
		await render(profile, { taxjar_sync_status: "Queued" });

		expect(sidebar_section().length).toBe(0);
	});

	// Both of these used to render nothing at all, which left a reader who had
	// switched TaxJar off site-wide with no cue that this was why.
	it.each([US_SITE_OFF, US_UNCONFIGURED])(
		"offers the setup link for $company",
		async (profile) => {
			await render(profile, { taxjar_sync_status: "Queued" });

			expect(taxjar._render_taxjar_sync_status_pill).not.toHaveBeenCalled();

			const section = sidebar_section();
			expect(section.length).toBe(1);
			expect(section.find("a.taxjar-not-enabled-link").attr("href")).toBe(
				"/app/taxjar-setup?focus=features"
			);
		}
	);

	// Nothing is known, so nothing is claimed - not even the link.
	it("renders nothing when the scope could not be read", async () => {
		frappe.xcall.mockRejectedValue(new Error("network"));
		taxjar._render_taxjar_sync_status_pill = vi.fn();

		const frm = make_frm({
			company: US_FILE.company,
			fields,
			doc: { taxjar_sync_status: "Queued" },
		});
		taxjar.render_sync_status_sidebar_pill(frm);
		await flush();

		expect(taxjar._render_taxjar_sync_status_pill).not.toHaveBeenCalled();
		expect(sidebar_section().length).toBe(0);
	});

	it("leaves no stale row behind on a document with no sync field", async () => {
		await render(US_CALC, { taxjar_sync_status: "Queued" });
		expect(sidebar_section().length).toBe(1);

		const plain = make_frm({ company: US_CALC.company, fields: [] });
		taxjar.render_sync_status_sidebar_pill(plain);
		await flush();

		expect(sidebar_section().length).toBe(0);
	});

	// The answer lands after the user has moved on. Writing it then would put
	// one document's status on another's form.
	it("drops an answer that arrives after the form moved to another document", async () => {
		let settle;
		frappe.xcall.mockImplementation(
			() => new Promise((resolve) => {
				settle = resolve;
			})
		);

		const frm = make_frm({
			company: US_CALC.company,
			fields,
			doc: { taxjar_sync_status: "Queued" },
		});
		taxjar.render_sync_status_sidebar_pill(frm);

		frm.doc.name = "SINV-0002";
		settle(US_CALC);
		await flush();

		expect(sidebar_section().length).toBe(0);
	});
});
