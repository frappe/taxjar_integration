// The dialog that gates save on Sales Taxes and Charges rows TaxJar does not
// know as tax or shipping. The form's validate handler waits on it, so what the
// dialog leaves in frappe.validated decides whether the save goes on.

import { beforeEach, describe, expect, it } from "vitest";

import {
	dialog_html,
	install_desk,
	load_taxjar_utils,
	make_frm,
	record_dialogs,
} from "./helpers/desk.js";

let frappe;
let taxjar;
let dialogs;

beforeEach(() => {
	frappe = install_desk();
	taxjar = load_taxjar_utils();
	dialogs = record_dialogs();
	frappe.validated = true;
});

const ROWS = [
	{ account_head: "71000 - Interest Income - FI", amount: 20, treatment: "taxable_line_item" },
	{ account_head: "41900 - Sales Discounts - FI", amount: -10, treatment: "discount", affected_item_count: 2 },
];

/** Open the dialog and return the promise validate waits on. */
function open_dialog(frm) {
	return new Promise((resolve) => {
		taxjar._show_foreign_tax_rows_dialog(frm, ROWS, "ack", resolve);
	});
}

describe("the foreign tax rows dialog", () => {
	// hide() runs on_hide, the path Escape takes. Proceed hides the dialog
	// too, and the save must still go on.
	it("lets the save go on when the user clicks Proceed", async () => {
		const frm = make_frm();
		const settled = open_dialog(frm);

		dialogs[0].options.primary_action();
		await settled;

		expect(frappe.validated).toBe(true);
		expect(frm._taxjar_foreign_rows_ack).toBe("ack");
	});

	it("stops the save when the user clicks Cancel", async () => {
		const settled = open_dialog(make_frm());

		dialogs[0].options.secondary_action();
		await settled;

		expect(frappe.validated).toBe(false);
	});

	it("stops the save when the user closes the dialog", async () => {
		const settled = open_dialog(make_frm());

		dialogs[0].hide();
		await settled;

		expect(frappe.validated).toBe(false);
	});
});

describe("what the dialog shows for each row", () => {
	/** The markup of one table row, by its ledger. */
	function row_html(account_head) {
		open_dialog(make_frm());
		const table = $(dialog_html(dialogs[0], "foreign_rows_table"));
		return table.find("tbody tr").filter((_, tr) => $(tr).text().includes(account_head)).html();
	}

	it("shows a charge as an up arrow that increases the taxable value", () => {
		const html = row_html("71000 - Interest Income - FI");

		expect(html).toContain(
			'<span class="es-badge" data-theme="blue"><svg class="icon icon-arrow-up"></svg>Increases Taxable Value</span>'
		);
		expect(html).toContain("Additional line item is added &amp; taxed.");
	});

	it("shows a discount as a down arrow that decreases the taxable value", () => {
		const html = row_html("41900 - Sales Discounts - FI");

		expect(html).toContain(
			'<span class="es-badge" data-theme="amber"><svg class="icon icon-arrow-down"></svg>Decreases Taxable Value</span>'
		);
		expect(html).toContain("Discount is applied to each line item proportionally.");
	});

	it("names the columns Ledger, Amount, Type and Impact", () => {
		open_dialog(make_frm());
		const headers = $(dialog_html(dialogs[0], "foreign_rows_table"))
			.find("th")
			.map((_, th) => $(th).text())
			.get();

		expect(headers).toEqual(["Ledger", "Amount", "Type", "Impact"]);
	});
});
