// The credit note has to name the invoice it reverses.
//
// validate_return_against refuses to save a filing company's credit note
// without `return_against`, and it refuses at `validate`, not at submit - so a
// draft in that state cannot be written at all. The message names the route
// that gets it right (Sales Invoice → Create → Return / Credit Note) and leaves
// the user to walk it.
//
// The picker asks at the moment the user ticks Is Return, and then takes that
// route for them. The handler is read out of sales_invoice.js through the same
// `frappe.ui.form.on` the desk registers it with, never transcribed: a
// transcribed copy would go on passing while the real form changed.

import { beforeEach, describe, expect, it, vi } from "vitest";

import {
	IN_CO,
	IN_FLAGGED,
	US_CALC,
	US_FILE,
	US_OFF,
	US_UNCONFIGURED,
	answer_scope,
	dialog_html,
	flush,
	install_desk,
	load_taxjar_utils,
	load_transaction_forms,
	make_frm,
	record_dialogs,
} from "./helpers/desk.js";

const RETURN_MAPPER = "erpnext.accounts.doctype.sales_invoice.mapper.make_sales_return";

let frappe;
let forms;
let dialogs;

beforeEach(() => {
	frappe = install_desk();
	load_taxjar_utils();
	forms = load_transaction_forms();
	dialogs = record_dialogs();
});

/** A draft credit note the user has just ticked Is Return on. */
function open_credit_note(profile, doc = {}) {
	return make_frm({
		doctype: "Sales Invoice",
		company: profile.company,
		fields: ["taxjar_sync_status"],
		doc: {
			is_return: 1,
			customer: "CUST-0003",
			customer_name: "Northwind Traders",
			items: [],
			...doc,
		},
	});
}

/** Tick the box and let every read the handler starts settle. */
async function tick_is_return(frm) {
	await forms["Sales Invoice"].is_return(frm);
	await flush();
	await flush();
}

/** One submitted invoice to reverse, and what the preview reads off it. */
function answer_invoice_reads(count = 1, values = {}) {
	frappe.db.count.mockResolvedValue(count);
	frappe.db.get_value.mockResolvedValue({
		message: {
			posting_date: "2026-08-14",
			currency: "USD",
			grand_total: 4820,
			total_taxes_and_charges: 312.3,
			taxjar_sync_status: "Synced",
			...values,
		},
	});
}

describe("the handler the form registers", () => {
	// The picker is reachable only through this. A rename here is a feature
	// that silently stops existing, which no other test in this file would see.
	it("is on the Sales Invoice form", () => {
		expect(typeof forms["Sales Invoice"].is_return).toBe("function");
	});
});

describe("which companies are asked", () => {
	// A dialog focuses its first input as it opens, and a focused Link control
	// drops its list open with it - so the picker arrived under a list of every
	// customer, covering its own title.
	it("opens without a list over it", async () => {
		answer_scope(frappe, US_FILE);
		answer_invoice_reads();

		await tick_is_return(open_credit_note(US_FILE));

		expect(dialogs[0].options.no_focus).toBe(true);
	});

	it("asks a company that files its transactions", async () => {
		answer_scope(frappe, US_FILE);
		answer_invoice_reads();

		await tick_is_return(open_credit_note(US_FILE));

		expect(dialogs).toHaveLength(1);
		expect(dialogs[0].options.title).toBe("Credit Note Against Invoice");
	});

	// The rule validate_return_against itself applies. A company that only
	// prices tax never needs the reference, so the dialog would be collecting
	// an answer that nothing goes on to read.
	it("does not ask a company that only calculates tax", async () => {
		answer_scope(frappe, US_CALC);
		answer_invoice_reads();

		await tick_is_return(open_credit_note(US_CALC));

		expect(dialogs).toHaveLength(0);
	});

	it.each([US_OFF, IN_CO, IN_FLAGGED, US_UNCONFIGURED])(
		"does not ask $company",
		async (profile) => {
			answer_scope(frappe, profile);
			answer_invoice_reads();

			await tick_is_return(open_credit_note(profile));

			expect(dialogs).toHaveLength(0);
		}
	);
});

describe("when the dialog stays shut", () => {
	beforeEach(() => {
		answer_scope(frappe, US_FILE);
		answer_invoice_reads();
	});

	// The handler fires on every write to the field, the app's own included.
	// Unticking must not re-open what unticking just closed.
	it("says nothing when the box is unticked", async () => {
		await tick_is_return(open_credit_note(US_FILE, { is_return: 0 }));

		expect(dialogs).toHaveLength(0);
		expect(frappe.xcall).not.toHaveBeenCalled();
	});

	// A document the Return / Credit Note mapper built arrives with both
	// fields set. Asking it for a reference it already carries would loop the
	// user straight back out of the document they were just sent to.
	it("says nothing when the reference is already there", async () => {
		await tick_is_return(open_credit_note(US_FILE, { return_against: "ACC-SINV-2026-00318" }));

		expect(dialogs).toHaveLength(0);
	});

	it("says nothing on a submitted document", async () => {
		await tick_is_return(open_credit_note(US_FILE, { docstatus: 1 }));

		expect(dialogs).toHaveLength(0);
	});

	// Two ticks in quick succession. A second dialog would sit over the first,
	// and cancelling it would untick the box the first one is still waiting on.
	it("opens one dialog, not two", async () => {
		const frm = open_credit_note(US_FILE);

		await tick_is_return(frm);
		await tick_is_return(frm);

		expect(dialogs).toHaveLength(1);
	});

	// The same two ticks, with the second one arriving before the first has
	// finished. The scope lookup between the guard and the dialog is a real
	// wait - the first tick on a form waits for get_company_scope - so the
	// second tick used to read the guard before the first had set it.
	it("opens one dialog when the second tick arrives during the scope lookup", async () => {
		answer_scope(frappe, US_FILE);
		answer_invoice_reads();
		const frm = open_credit_note(US_FILE);

		const first = forms["Sales Invoice"].is_return(frm);
		const second = forms["Sales Invoice"].is_return(frm);
		await Promise.all([first, second]);
		await flush();
		await flush();

		expect(dialogs).toHaveLength(1);
	});

	// A tick that opens no dialog must leave nothing behind. The guard is taken
	// before the company is known, so a company TaxJar does not file for has to
	// give it back - otherwise this form never asks again.
	it("asks again after a tick on a company it does not file for", async () => {
		answer_scope(frappe, (args) => (args.company === US_FILE.company ? US_FILE : US_CALC));
		answer_invoice_reads();

		const frm = open_credit_note(US_CALC);
		await tick_is_return(frm);
		expect(dialogs).toHaveLength(0);

		frm.doc.company = US_FILE.company;
		await tick_is_return(frm);

		expect(dialogs).toHaveLength(1);
	});
});

describe("the invoices the picker offers", () => {
	beforeEach(() => {
		answer_scope(frappe, US_FILE);
		answer_invoice_reads();
	});

	function invoice_filters(dialog) {
		return dialog.fields_dict.return_against.df.get_query().filters;
	}

	// Submitted, because TaxJar files the refund against an order it already
	// holds. Not itself a return, because a credit note cannot reverse a credit
	// note. One company, because another company's invoice is not this
	// company's to reverse.
	it("offers only submitted invoices of this company that are not returns", async () => {
		await tick_is_return(open_credit_note(US_FILE));

		expect(invoice_filters(dialogs[0])).toMatchObject({
			docstatus: 1,
			is_return: 0,
			company: US_FILE.company,
		});
	});

	it("narrows the list to the customer the form names", async () => {
		await tick_is_return(open_credit_note(US_FILE));

		expect(invoice_filters(dialogs[0]).customer).toBe("CUST-0003");
	});

	// A label, not a link: the credit note is for the customer the form names,
	// and a second customer picked here would fetch the wrong invoice.
	it("holds that customer read-only", async () => {
		await tick_is_return(open_credit_note(US_FILE));

		expect(dialogs[0].fields_dict.customer).toBeUndefined();
		expect(dialogs[0].fields_dict.customer_display.df.read_only).toBe(1);
	});

	// Most sites name a Customer by series, so the link field's own value is
	// CUST-0003. Nobody recognises a customer by that.
	it("names the customer, and keeps the id beside it", async () => {
		await tick_is_return(open_credit_note(US_FILE));

		expect(dialogs[0].get_value("customer_display")).toBe("Northwind Traders (CUST-0003)");
	});

	// A site that names its customers by name has the id and the name the same
	// string, and printing it twice reads as a mistake.
	it("says the name once when the id is the name", async () => {
		await tick_is_return(
			open_credit_note(US_FILE, { customer: "Northwind Traders", customer_name: "Northwind Traders" })
		);

		expect(dialogs[0].get_value("customer_display")).toBe("Northwind Traders");
	});

	it("falls back to the id when the form carries no name", async () => {
		await tick_is_return(open_credit_note(US_FILE, { customer_name: "" }));

		expect(dialogs[0].get_value("customer_display")).toBe("CUST-0003");
	});

	// The form is allowed to name nobody yet. The user picks the customer in
	// the dialog instead, and the list is the whole company's until they do.
	it("lets the user choose a customer when the form names none", async () => {
		await tick_is_return(open_credit_note(US_FILE, { customer: "" }));

		expect(dialogs[0].fields_dict.customer_display).toBeUndefined();
		expect(dialogs[0].fields_dict.customer.df.fieldtype).toBe("Link");
		expect(dialogs[0].fields_dict.customer.df.read_only).toBeFalsy();
		expect(invoice_filters(dialogs[0]).customer).toBeUndefined();
	});

	it("narrows the list as soon as a customer is chosen there", async () => {
		await tick_is_return(open_credit_note(US_FILE, { customer: "" }));

		dialogs[0].set_value("customer", "Cascade Outfitters");

		expect(invoice_filters(dialogs[0]).customer).toBe("Cascade Outfitters");
	});

	// The invoice belonged to the customer that was there a moment ago, so it
	// cannot stand once that changes.
	it("drops the chosen invoice when the customer changes", async () => {
		await tick_is_return(open_credit_note(US_FILE, { customer: "" }));

		dialogs[0].set_value("return_against", "ACC-SINV-2026-00318");
		dialogs[0].set_value("customer", "Cascade Outfitters");

		expect(dialogs[0].get_value("return_against")).toBe("");
	});
});

describe("the customer with nothing to reverse", () => {
	beforeEach(() => {
		answer_scope(frappe, US_FILE);
	});

	// A picker here would open on an empty list and say nothing about why it
	// was empty. The count is asked first so the dialog can.
	it("says so instead of opening an empty picker", async () => {
		answer_invoice_reads(0);

		await tick_is_return(open_credit_note(US_FILE));

		expect(dialogs).toHaveLength(1);
		expect(dialogs[0].fields_dict.return_against).toBeUndefined();
		const html = dialog_html(dialogs[0], "taxjar_no_invoice");
		expect(html).toContain(
			'<a href="/desk/customer/CUST-0003">Northwind Traders (CUST-0003)</a> has no submitted invoice.'
		);
		expect(html).toContain(
			"Please submit a sales invoice against the customer to generate a credit note."
		);
	});

	// The same rule the picker states, in the same yellow block, above the
	// line that says why this customer cannot meet it yet.
	it("leads with the requirements banner", async () => {
		answer_invoice_reads(0);

		await tick_is_return(open_credit_note(US_FILE));

		expect(dialogs[0].options.fields[0].fieldname).toBe("taxjar_return_requirements");
		expect(dialog_html(dialogs[0], "taxjar_return_requirements")).toContain(
			"Original sales invoice must be referenced for credit note."
		);
	});

	it("offers cancel and nothing else", async () => {
		answer_invoice_reads(0);

		await tick_is_return(open_credit_note(US_FILE));

		expect(dialogs[0].options.primary_action_label).toBe("Cancel");
		expect(dialogs[0].options.secondary_action_label).toBeUndefined();
	});

	it("unticks the box when that dialog closes", async () => {
		answer_invoice_reads(0);
		const frm = open_credit_note(US_FILE);

		await tick_is_return(frm);
		dialogs[0].options.primary_action();

		expect(frm.doc.is_return).toBe(0);
	});

	// The count decides which dialog to open, not whether to open one. A failed
	// read must not leave the user with a ticked box and no dialog at all.
	it("still opens the picker when the count cannot be read", async () => {
		frappe.db.count.mockRejectedValue(new Error("offline"));

		await tick_is_return(open_credit_note(US_FILE));

		expect(dialogs).toHaveLength(1);
		expect(dialogs[0].fields_dict.return_against).toBeDefined();
	});
});

describe("the requirements banner", () => {
	beforeEach(() => {
		answer_scope(frappe, US_FILE);
		answer_invoice_reads();
	});

	// The reason the dialog opened, so it opens the dialog. The two fields
	// under it are what the reader does about it.
	it("leads the dialog", async () => {
		await tick_is_return(open_credit_note(US_FILE));

		expect(dialogs[0].options.fields[0].fieldname).toBe("taxjar_return_requirements");
	});

	it("names TaxJar as what requires the reference", async () => {
		await tick_is_return(open_credit_note(US_FILE));

		const html = dialog_html(dialogs[0], "taxjar_return_requirements");
		expect(html).toContain("TaxJar Requirements");
		expect(html).toContain("Original sales invoice must be referenced for credit note.");
	});

	// It states a rule, not a state of this document, so every credit note gets
	// it - an empty draft and a filled one alike.
	it("shows whatever the draft holds", async () => {
		await tick_is_return(open_credit_note(US_FILE, { items: [{ item_code: "WIDGET-1" }] }));

		expect(dialogs[0].fields_dict.taxjar_return_requirements).toBeDefined();
	});
});

describe("the two buttons", () => {
	beforeEach(() => {
		answer_scope(frappe, US_FILE);
		answer_invoice_reads();
	});

	// The same pair whatever the draft holds. They used to rename themselves
	// over a warning that is gone, and a renamed button with nothing above it
	// to explain the rename reads as a different action.
	it.each([
		["an empty draft", []],
		["a draft holding rows", [{ item_code: "WIDGET-1" }, { item_code: "WIDGET-2" }]],
	])("read Continue and Cancel on %s", async (_case, items) => {
		await tick_is_return(open_credit_note(US_FILE, { items }));

		expect(dialogs[0].options.primary_action_label).toBe("Continue");
		expect(dialogs[0].options.secondary_action_label).toBe("Cancel");
	});
});

describe("what the preview reads off the invoice", () => {
	beforeEach(() => {
		answer_scope(frappe, US_FILE);
		answer_invoice_reads();
	});

	it("shows nothing until an invoice is chosen", async () => {
		await tick_is_return(open_credit_note(US_FILE));

		expect(frappe.db.get_value).not.toHaveBeenCalled();
	});

	it("shows the amount, the tax and the sync status of the chosen invoice", async () => {
		await tick_is_return(open_credit_note(US_FILE));

		dialogs[0].set_value("return_against", "ACC-SINV-2026-00318");
		await flush();

		const text = dialogs[0].fields_dict.taxjar_return_preview.$wrapper.text();
		expect(text).toContain("2026-08-14");
		expect(text).toContain("USD 4820.00");
		expect(text).toContain("USD 312.30");
		expect(text).toContain("Sync Status");
		expect(text).toContain("Synced");
	});

	// The invoice's own sidebar shows this status as a pill. Two readings of
	// one status, in two colours, would have the reader wondering which is
	// right - so both read off SYNC_STATUS_COLORS.
	it("draws the status as the pill the sidebar draws, in the sidebar's colour", async () => {
		await tick_is_return(open_credit_note(US_FILE));

		dialogs[0].set_value("return_against", "ACC-SINV-2026-00318");
		await flush();

		const $pill = dialogs[0].fields_dict.taxjar_return_preview.$wrapper.find(".es-badge");
		expect($pill).toHaveLength(1);
		expect($pill.text()).toBe("Synced");
		expect($pill.attr("data-theme")).toBe(window.taxjar_integration.SYNC_STATUS_COLORS.Synced);
	});

	it.each([
		["Failed", "red"],
		["Queued", "blue"],
	])("draws %s in the sidebar's own colour", async (status, theme) => {
		answer_invoice_reads(1, { taxjar_sync_status: status });

		await tick_is_return(open_credit_note(US_FILE));
		dialogs[0].set_value("return_against", "ACC-SINV-2026-00318");
		await flush();

		const $pill = dialogs[0].fields_dict.taxjar_return_preview.$wrapper.find(".es-badge");
		expect($pill.text()).toBe(status);
		expect($pill.attr("data-theme")).toBe(theme);
		expect(window.taxjar_integration.SYNC_STATUS_COLORS[status]).toBe(theme);
	});

	// Gray is the badge's own default, so frappe leaves the attribute off.
	it("draws Excluded with no colour of its own", async () => {
		answer_invoice_reads(1, { taxjar_sync_status: "Excluded" });

		await tick_is_return(open_credit_note(US_FILE));
		dialogs[0].set_value("return_against", "ACC-SINV-2026-00318");
		await flush();

		const $pill = dialogs[0].fields_dict.taxjar_return_preview.$wrapper.find(".es-badge");
		expect($pill.text()).toBe("Excluded");
		expect($pill.attr("data-theme")).toBeUndefined();
	});

	// An invoice TaxJar never received has nothing for a credit note to file
	// against, and the reader should see that before they commit to it.
	it("says so when the invoice never reached TaxJar", async () => {
		answer_invoice_reads(1, { taxjar_sync_status: "" });

		await tick_is_return(open_credit_note(US_FILE));
		dialogs[0].set_value("return_against", "ACC-SINV-2026-00318");
		await flush();

		const $pill = dialogs[0].fields_dict.taxjar_return_preview.$wrapper.find(".es-badge");
		expect($pill.text()).toBe("Not synced");
		expect($pill.attr("data-theme")).toBeUndefined();
	});

	// A second pick can land while the first read is still in flight. The field
	// is the record of what the user chose last, so it decides.
	it("ignores a read that a later choice has overtaken", async () => {
		await tick_is_return(open_credit_note(US_FILE));

		let settle_first;
		frappe.db.get_value.mockReturnValueOnce(
			new Promise((resolve) => {
				settle_first = resolve;
			})
		);

		dialogs[0].set_value("return_against", "ACC-SINV-2026-00001");
		dialogs[0].set_value("return_against", "ACC-SINV-2026-00318");
		await flush();

		settle_first({ message: { grand_total: 11, currency: "USD" } });
		await flush();

		expect(dialogs[0].fields_dict.taxjar_return_preview.$wrapper.text()).not.toContain(
			"USD 11.00"
		);
		expect(dialogs[0].fields_dict.taxjar_return_preview.$wrapper.text()).toContain(
			"USD 4820.00"
		);
	});
});

describe("continuing", () => {
	beforeEach(() => {
		answer_scope(frappe, US_FILE);
		answer_invoice_reads();
	});

	it("opens the Return / Credit Note mapper on the chosen invoice", async () => {
		await tick_is_return(open_credit_note(US_FILE));

		dialogs[0].set_value("return_against", "ACC-SINV-2026-00318");
		await dialogs[0].options.primary_action();

		expect(frappe.model.open_mapped_doc).toHaveBeenCalledWith({
			method: RETURN_MAPPER,
			source_name: "ACC-SINV-2026-00318",
		});
	});

	// The mapper builds its own document, so this draft is left behind. Left
	// ticked it could never be saved again, because validate_return_against
	// refuses a return with no reference - and the dialog that collects one
	// only opens on the tick that has already happened.
	it("unticks the box on the draft it leaves behind", async () => {
		const frm = open_credit_note(US_FILE);
		await tick_is_return(frm);

		dialogs[0].set_value("return_against", "ACC-SINV-2026-00318");
		await dialogs[0].options.primary_action();

		expect(frm.doc.is_return).toBe(0);
	});

	it("goes nowhere while no invoice is chosen", async () => {
		await tick_is_return(open_credit_note(US_FILE));

		await dialogs[0].options.primary_action();

		expect(frappe.model.open_mapped_doc).not.toHaveBeenCalled();
		expect(frappe.show_alert).toHaveBeenCalled();
	});
});

describe("an invoice TaxJar never received", () => {
	beforeEach(() => {
		answer_scope(frappe, US_FILE);
	});

	async function continue_on(status) {
		answer_invoice_reads(1, { taxjar_sync_status: status });

		const frm = open_credit_note(US_FILE);
		await tick_is_return(frm);
		dialogs[0].set_value("return_against", "ACC-SINV-2026-00318");
		await dialogs[0].options.primary_action();

		return frm;
	}

	// TaxJar files the refund against a transaction it already holds. Queued
	// and Failed leave it with nothing to file against, and so does Excluded,
	// which was a decision never to send the invoice at all.
	it.each(["Queued", "Failed", "Excluded", ""])(
		"refuses to continue on a %s invoice",
		async (status) => {
			await continue_on(status);

			expect(frappe.model.open_mapped_doc).not.toHaveBeenCalled();
		}
	);

	it("says why, with a heading of its own", async () => {
		await continue_on("Failed");

		expect(frappe.msgprint).toHaveBeenCalledTimes(1);
		const [options] = frappe.msgprint.mock.calls[0];
		expect(options.title).toBe("Original Invoice Not Synced");
		expect(options.message).toBe(
			"Original sales invoice isn't synced to TaxJar, so credit note can't be created against it."
		);
	});

	// The picker stays open behind the message, so the reader picks another
	// invoice rather than starting the credit note again.
	it("leaves the picker open", async () => {
		await continue_on("Failed");

		expect(dialogs[0].hide).not.toHaveBeenCalled();
	});

	// Nothing has been decided, so the box that opened the dialog stays as it
	// is. Unticking it here would close the one route back.
	it("leaves Is Return ticked", async () => {
		const frm = await continue_on("Failed");

		expect(frm.doc.is_return).toBe(1);
	});

	// The preview's own read can still be in flight, and the background sync
	// job can move a status while the dialog sits open, so the check is made
	// against the server at the moment of the click.
	it("reads the status again on the click", async () => {
		await continue_on("Synced");

		const reads = frappe.db.get_value.mock.calls.filter(
			(call) => Array.isArray(call[2]) && call[2].includes("taxjar_exclusion_reason")
		);
		expect(reads).toHaveLength(1);
		expect(frappe.model.open_mapped_doc).toHaveBeenCalledTimes(1);
	});
});

describe("an export the company keeps out of TaxJar", () => {
	async function continue_on(values, profile = US_FILE) {
		answer_scope(frappe, profile);
		answer_invoice_reads(1, values);

		const frm = open_credit_note(profile);
		await tick_is_return(frm);
		dialogs[0].set_value("return_against", "ACC-SINV-2026-00318");
		await dialogs[0].options.primary_action();

		return frm;
	}

	const EXCLUDED_EXPORT = {
		taxjar_sync_status: "Excluded",
		taxjar_exclusion_reason: "Export Transaction",
	};

	// The credit note is an export too, so it is excluded and never sent.
	// Refusing it would leave no way to refund an export sale.
	it("opens the credit note", async () => {
		await continue_on(EXCLUDED_EXPORT);

		expect(frappe.msgprint).not.toHaveBeenCalled();
		expect(frappe.model.open_mapped_doc).toHaveBeenCalledTimes(1);
	});

	// Exports are filed now, so the credit note would go to TaxJar against an
	// invoice TaxJar never received.
	it("refuses once the company files its exports", async () => {
		await continue_on(EXCLUDED_EXPORT, { ...US_FILE, files_exports: true });

		expect(frappe.model.open_mapped_doc).not.toHaveBeenCalled();
		expect(frappe.msgprint.mock.calls[0][0].title).toBe("Original Invoice Not Synced");
	});

	it("refuses an invoice excluded for any other reason", async () => {
		await continue_on({
			taxjar_sync_status: "Excluded",
			taxjar_exclusion_reason: "Transaction Sync not enabled for company",
		});

		expect(frappe.model.open_mapped_doc).not.toHaveBeenCalled();
	});
});

describe("cancelling", () => {
	beforeEach(() => {
		answer_scope(frappe, US_FILE);
		answer_invoice_reads();
	});

	it("unticks the box", async () => {
		const frm = open_credit_note(US_FILE);
		await tick_is_return(frm);

		dialogs[0].options.secondary_action();

		expect(frm.doc.is_return).toBe(0);
	});

	// Escape and a click on the backdrop take this path. They mean what the
	// Cancel button means, and used to leave the box ticked.
	it("unticks the box when the dialog is dismissed", async () => {
		const frm = open_credit_note(US_FILE);
		await tick_is_return(frm);

		dialogs[0].options.on_hide();

		expect(frm.doc.is_return).toBe(0);
	});

	it("goes nowhere", async () => {
		const frm = open_credit_note(US_FILE);
		await tick_is_return(frm);

		dialogs[0].options.secondary_action();

		expect(frappe.model.open_mapped_doc).not.toHaveBeenCalled();
	});

	// Continue hides the dialog too, and on_hide runs either way. It must not
	// undo the choice the user just made on the way out.
	it("does not untick the box behind a choice that was made", async () => {
		const frm = open_credit_note(US_FILE);
		await tick_is_return(frm);

		dialogs[0].set_value("return_against", "ACC-SINV-2026-00318");
		await dialogs[0].options.primary_action();
		frm.set_value.mockClear();

		expect(frappe.model.open_mapped_doc).toHaveBeenCalledTimes(1);
		expect(frm.set_value).not.toHaveBeenCalled();
	});

	// The dialog is reopenable after a cancel. The guard that stops a second
	// dialog has to come off when the first one goes.
	it("lets the user tick the box again afterwards", async () => {
		const frm = open_credit_note(US_FILE);
		await tick_is_return(frm);
		dialogs[0].options.secondary_action();

		frm.doc.is_return = 1;
		await tick_is_return(frm);

		expect(dialogs).toHaveLength(2);
	});
});

describe("every string the dialogs show", () => {
	// A dialog with no heading renders frappe's generic "Message", which says
	// nothing about what is being asked or why.
	it("carries a heading of its own", async () => {
		answer_scope(frappe, US_FILE);

		answer_invoice_reads(1);
		await tick_is_return(open_credit_note(US_FILE));

		answer_invoice_reads(0);
		await tick_is_return(open_credit_note(US_FILE));

		expect(dialogs).toHaveLength(2);
		for (const dialog of dialogs) {
			expect(dialog.options.title).toBe("Credit Note Against Invoice");
		}
	});

	// A customer name goes into the dialog's HTML as markup. frappe does not
	// escape an HTML field's options for us.
	it("escapes a customer name before writing it into the markup", async () => {
		answer_scope(frappe, US_FILE);
		answer_invoice_reads(0);

		await tick_is_return(
			open_credit_note(US_FILE, { customer: "CUST-0003", customer_name: "<script>x</script> Co" })
		);

		const html = dialog_html(dialogs[0], "taxjar_no_invoice");
		expect(html).not.toContain("<script>");
		expect(html).toContain("&lt;script&gt;");
	});
});

describe("the mapper this calls", () => {
	// The path is a string here and a function in erpnext. Nothing checks that
	// they agree, so the suite pins the string in one place and this says
	// which place.
	it("is the one erpnext's own Return / Credit Note button calls", () => {
		expect(RETURN_MAPPER).toBe("erpnext.accounts.doctype.sales_invoice.mapper.make_sales_return");
	});
});

describe("the reads the picker makes", () => {
	// The count is a "does any exist" question, not a tally. Asking for the
	// whole count of a large customer's invoices to decide which dialog to
	// open would read a number nobody displays.
	it("asks only whether one invoice exists", async () => {
		answer_scope(frappe, US_FILE);
		answer_invoice_reads();

		await tick_is_return(open_credit_note(US_FILE));

		expect(frappe.db.count).toHaveBeenCalledWith(
			"Sales Invoice",
			expect.objectContaining({ limit: 1 })
		);
	});

	// With no customer the list is the whole company's, which is worth opening
	// the picker for without asking anything first.
	it("asks nothing first when the form names no customer", async () => {
		answer_scope(frappe, US_FILE);
		answer_invoice_reads();

		await tick_is_return(open_credit_note(US_FILE, { customer: "" }));

		expect(frappe.db.count).not.toHaveBeenCalled();
		expect(dialogs).toHaveLength(1);
	});
});

describe("the dialog stub this file drives", () => {
	// A stub that answered every read the same way would let the picker's
	// Continue button pass a test it cannot pass on a desk.
	it("keeps a value per field", async () => {
		answer_scope(frappe, US_FILE);
		answer_invoice_reads();

		await tick_is_return(open_credit_note(US_FILE));

		expect(dialogs[0].get_value("customer_display")).toBe("Northwind Traders (CUST-0003)");
		expect(dialogs[0].get_value("return_against")).toBe("");
		expect(vi.isMockFunction(dialogs[0].show)).toBe(true);
	});
});
