// The TaxJar exemption card on the Customer form, rendered rather than read.
//
// The Python suite greps customer.js for the classes and component calls it
// should contain. That catches a name that was never written; it cannot catch
// markup that is written and still comes out wrong - a country band that
// renders for a country with nothing selected, a chip cap that hides the
// control meant to reveal the rest, an action whose click never reaches the
// dialog. So this renders both states and reads the result back out of the DOM.
//
// The espresso components are stubbed rather than imported: they are ES modules
// inside frappe, and what matters here is the options this card hands them and
// where their output ends up, not how frappe draws a badge.

import { beforeEach, describe, expect, it, vi } from "vitest";

import { install_desk, load_customer_form, load_taxjar_utils } from "./helpers/desk.js";

// Mirrors REGIONS_SHOWN in customer.js. Stated here rather than imported: the
// file is a browser script, and a test that reads the cap from the code it is
// testing cannot notice the cap changing.
const REGIONS_SHOWN = 8;

let frappe;
let empty_state_opts;
let button_opts;
let badge_opts;

/** Stand-ins that record what the card asked for, and return real elements so
 *  the result can be read back out of the DOM. */
function install_espresso_components() {
	empty_state_opts = null;
	button_opts = [];
	badge_opts = [];

	frappe.ui.empty_state = Object.assign(vi.fn(), {
		html: vi.fn((opts) => {
			empty_state_opts = opts;
			const actions = (opts.actions || [])
				.map((a) =>
					a.href
						? `<a class="es-button ${a.css_class || ""}" href="${a.href}">${a.label}</a>`
						: `<button type="button" class="es-button ${a.css_class || ""}">${a.label}</button>`
				)
				.join("");
			return `<div class="es-empty-state"><div class="es-title">${opts.title}</div>${actions}</div>`;
		}),
	});

	frappe.ui.button = Object.assign(
		vi.fn((opts) => {
			button_opts.push(opts);
			const $b = $('<button type="button" class="es-button"></button>')
				.addClass(opts.css_class || "")
				.text(opts.label || "");
			if (opts.tooltip) $b.attr("aria-label", opts.tooltip);
			if (opts.onclick) $b.on("click", opts.onclick);
			return $b;
		}),
		{
			html: vi.fn((opts) => {
				button_opts.push(opts);
				return `<button type="button" class="es-button ${opts.css_class || ""}">${
					opts.label || ""
				}</button>`;
			}),
		}
	);

	frappe.ui.badge = Object.assign(
		vi.fn((opts) => {
			badge_opts.push(opts);
			return $('<span class="es-badge"></span>')
				.addClass(opts.css_class || "")
				.text(opts.label);
		}),
		{ html: vi.fn((opts) => `<span class="es-badge">${opts.label}</span>`) }
	);

	frappe.ui.tooltip = vi.fn();
	frappe.defaults = { get_user_default: vi.fn(() => "Test Co") };

	// The card's job ends at opening the dialog; what the dialog then wires up
	// has its own tests. Any field the wiring reaches for answers with the same
	// inert stub, so a field added there cannot fail a test about the card.
	frappe.ui.Dialog = vi.fn(function Dialog(options) {
		this.options = options;
		this.$wrapper = $("<div class='modal'></div>");
		this.show = vi.fn();
		this.hide = vi.fn();
		this.set_value = vi.fn();
		this.get_value = vi.fn(() => "");
		const field_stub = () =>
			new Proxy(
				{
					df: {},
					$wrapper: $("<div><div class='taxjar-region-requirement-warning'></div></div>"),
					get_checked_options: () => [],
				},
				{ get: (target, prop) => (prop in target ? target[prop] : vi.fn()) }
			);
		this.fields_dict = new Proxy({}, { get: field_stub });
		return new Proxy(this, {
			get: (target, prop) => (prop in target ? target[prop] : vi.fn()),
		});
	});
}

function us_states(n) {
	return window.taxjar_integration.US_STATE_CODES.slice(0, n).map((state) => ({
		country: "US",
		state,
	}));
}

function make_customer_frm({ exemption_type = "", exempt_regions = [] } = {}) {
	const $wrapper = $("<div></div>").appendTo(document.body);
	return {
		doc: {
			doctype: "Customer",
			name: "CUST-0001",
			taxjar_exemption_type: exemption_type,
			taxjar_exempt_regions: exempt_regions,
		},
		is_new: () => false,
		add_custom_button: vi.fn(),
		fields_dict: { taxjar_exemption_summary_html: { $wrapper } },
		reload_doc: vi.fn(),
	};
}

function render(options) {
	const frm = make_customer_frm(options);
	load_customer_form().refresh(frm);
	return frm.fields_dict.taxjar_exemption_summary_html.$wrapper;
}

/** The chip labels on screen, minus the control that opens the rest. */
function chip_labels($wrapper) {
	return $wrapper
		.find(".taxjar-region-chip")
		.map((_, el) => $(el).text())
		.get();
}

beforeEach(() => {
	frappe = install_desk();
	install_espresso_components();
	load_taxjar_utils();
});

describe("no exemption configured yet", () => {
	it("renders frappe's empty state, not a card", () => {
		const $wrapper = render();
		expect($wrapper.find(".es-empty-state").length).toBe(1);
		expect($wrapper.find(".taxjar-exemption-card").length).toBe(0);
	});

	it("names the state and says what configuring one would do", () => {
		render();
		expect(empty_state_opts.title).toBe("No exemption configured");
		expect(empty_state_opts.description).toBe("Set exemption to stop collecting sales tax");
		expect(empty_state_opts.icon).toBeTruthy();
	});

	it("offers only Manage Exemption", () => {
		render();
		expect(empty_state_opts.actions.map((a) => a.label)).toEqual(["Manage Exemption"]);
	});

	it("keeps Manage Exemption a subtle button", () => {
		render();
		const [manage] = empty_state_opts.actions;
		expect(manage.variant).toBe("subtle");
		// No href: it opens the dialog rather than navigating anywhere.
		expect(manage.href).toBeUndefined();
	});

	it("opens the dialog from the empty state's own button", () => {
		const $wrapper = render();
		$wrapper.find(".taxjar-manage-exemption-btn").trigger("click");
		expect(frappe.ui.Dialog).toHaveBeenCalledTimes(1);
	});
});

describe("the card's header", () => {
	it("says the state and the type on one line", () => {
		// Asserted part by part: the header is a flex row, so the space either
		// side of the separator is the row's gap rather than a text node.
		const $wrapper = render({ exemption_type: "Wholesale", exempt_regions: us_states(2) });
		const parts = $wrapper
			.find(".taxjar-exemption-header > span")
			.map((_, el) => $(el).text())
			.get();
		expect(parts).toEqual(["Exempted", "·", "Wholesale"]);
	});

	it("is the first band in the card", () => {
		// The rules between bands are drawn by `> * + *`, so a header that is
		// not first would carry a rule above it.
		const $wrapper = render({ exemption_type: "Wholesale", exempt_regions: us_states(2) });
		expect($wrapper.find(".taxjar-exemption-card > :first-child").hasClass("taxjar-exemption-header")).toBe(
			true
		);
	});

	it("holds the control, rather than pinning it to the card's corner", () => {
		const $wrapper = render({ exemption_type: "Wholesale", exempt_regions: us_states(2) });
		expect($wrapper.find(".taxjar-exemption-header > .taxjar-exemption-edit").length).toBe(1);
		// frappe's corner rule would put it half a band away from its own line.
		expect($wrapper.find(".card-menu-btn").length).toBe(0);
	});

	it("names the control for a reader who cannot see it", () => {
		const $wrapper = render({ exemption_type: "Wholesale", exempt_regions: us_states(2) });
		const manage = button_opts.find((o) => o.icon === "pencil");
		expect(manage.tooltip).toBe("Manage Exemption");
		expect($wrapper.find(".taxjar-exemption-edit").attr("aria-label")).toBe("Manage Exemption");
	});

	it("opens the dialog from the header control", () => {
		const $wrapper = render({ exemption_type: "Wholesale", exempt_regions: us_states(2) });
		$wrapper.find(".taxjar-manage-exemption-btn").trigger("click");
		expect(frappe.ui.Dialog).toHaveBeenCalledTimes(1);
	});

	it("opens one dialog, not two, on a card drawn after the empty state", () => {
		// The empty state delegates its click from the wrapper, and the header
		// control carries the same class. Every customer who gets an exemption goes
		// through both states in one form, so the card used to answer a single
		// click twice and stack two dialogs.
		const form = load_customer_form();
		const frm = make_customer_frm();
		form.refresh(frm);

		frm.doc.taxjar_exemption_type = "Wholesale";
		frm.doc.taxjar_exempt_regions = us_states(2);
		form.refresh(frm);

		frm.fields_dict.taxjar_exemption_summary_html.$wrapper
			.find(".taxjar-manage-exemption-btn")
			.trigger("click");
		expect(frappe.ui.Dialog).toHaveBeenCalledTimes(1);
	});

	it("says plainly when the customer is taxable everywhere", () => {
		const $wrapper = render({ exemption_type: "Non Exempt" });
		expect($wrapper.find(".taxjar-exemption-header").text()).toContain("Non-Exempted");
		expect($wrapper.text()).toContain("Sales tax is applicable.");
	});

	it("lists no region under Non Exempt, even when rows survived an earlier type", () => {
		// Non Exempt is a global answer and the server never reads the table
		// under it. A listed region would read as a place the customer is
		// exempt in, one band above the line that says tax applies.
		const $wrapper = render({ exemption_type: "Non Exempt", exempt_regions: us_states(3) });
		expect($wrapper.find(".taxjar-region-chip").length).toBe(0);
		expect($wrapper.find(".taxjar-exemption-country").length).toBe(0);
		expect($wrapper.text()).not.toContain("No regions selected");
		expect($wrapper.text()).toContain("Sales tax is applicable.");
	});
});

describe("a country band", () => {
	const two_countries = () => ({
		exemption_type: "Wholesale",
		exempt_regions: [...us_states(2), { country: "CA", state: "ON" }],
	});

	it("draws one band per country actually listed", () => {
		const $wrapper = render(two_countries());
		expect($wrapper.find(".taxjar-exemption-country").length).toBe(2);
	});

	it("drops a country with nothing selected rather than leaving an empty band", () => {
		const $wrapper = render({ exemption_type: "Wholesale", exempt_regions: us_states(2) });
		expect($wrapper.find(".taxjar-exemption-country").length).toBe(1);
		expect($wrapper.text()).not.toContain("Canada");
	});

	it("heads the band with the country, not the kind of region in it", () => {
		const $wrapper = render(two_countries());
		expect($wrapper.text()).toContain("United States");
		expect($wrapper.text()).toContain("Canada");
		expect($wrapper.text()).not.toContain("US States");
		expect($wrapper.text()).not.toContain("CA Provinces");
	});

	it("draws that country's flag before its name", () => {
		const $wrapper = render({ exemption_type: "Wholesale", exempt_regions: us_states(2) });
		const $flag = $wrapper.find(".taxjar-flag");
		expect($flag.length).toBe(1);
		expect($flag.find("svg").length).toBe(1);
		expect($flag.next("span").text()).toBe("United States");
	});

	it("keeps the flag out of a screen reader's way", () => {
		const $wrapper = render({ exemption_type: "Wholesale", exempt_regions: us_states(2) });
		expect($wrapper.find(".taxjar-flag").attr("aria-hidden")).toBe("true");
	});

	it("counts what is selected, in that country's own words", () => {
		const $wrapper = render(two_countries());
		const counts = $wrapper
			.find(".taxjar-exemption-count")
			.map((_, el) => $(el).text())
			.get();
		expect(counts).toEqual(["2 states", "1 province"]);
	});

	it("lists the regions as chips, by full name, sorted", () => {
		const $wrapper = render({
			exemption_type: "Wholesale",
			exempt_regions: [
				{ country: "US", state: "OK" },
				{ country: "US", state: "AL" },
			],
		});
		expect(chip_labels($wrapper)).toEqual(["Alabama", "Oklahoma"]);
	});
});

describe("a fully covered country", () => {
	const every_state = () =>
		window.taxjar_integration.US_STATE_CODES.map((state) => ({ country: "US", state }));

	it("says so instead of listing every region", () => {
		const $wrapper = render({ exemption_type: "Wholesale", exempt_regions: every_state() });
		expect($wrapper.text()).toContain("All states exempted");
		expect(chip_labels($wrapper)).toEqual([]);
	});

	it("shows no count beside it", () => {
		// "All states exempted" and "51 states" say the same thing twice.
		const $wrapper = render({ exemption_type: "Wholesale", exempt_regions: every_state() });
		expect($wrapper.find(".taxjar-exemption-count").length).toBe(0);
	});
});

describe("more regions than fit", () => {
	const many = () => ({
		exemption_type: "Wholesale",
		exempt_regions: us_states(REGIONS_SHOWN + 5),
	});

	it("caps the chips and offers the rest behind one control", () => {
		const $wrapper = render(many());
		expect(chip_labels($wrapper).length).toBe(REGIONS_SHOWN);
		expect($wrapper.find(".taxjar-region-chips .es-button").text()).toBe("+5 more");
	});

	it("shows every chip once that control is pressed", () => {
		const $wrapper = render(many());
		$wrapper.find(".taxjar-region-chips .es-button").trigger("click");
		expect(chip_labels($wrapper).length).toBe(REGIONS_SHOWN + 5);
		expect($wrapper.find(".taxjar-region-chips .es-button").text()).toBe("Show fewer");
	});

	it("closes again", () => {
		const $wrapper = render(many());
		$wrapper.find(".taxjar-region-chips .es-button").trigger("click");
		$wrapper.find(".taxjar-region-chips .es-button").trigger("click");
		expect(chip_labels($wrapper).length).toBe(REGIONS_SHOWN);
	});

	it("draws no control at all when everything already fits", () => {
		const $wrapper = render({ exemption_type: "Wholesale", exempt_regions: us_states(REGIONS_SHOWN) });
		expect(chip_labels($wrapper).length).toBe(REGIONS_SHOWN);
		expect($wrapper.find(".taxjar-region-chips .es-button").length).toBe(0);
	});

	it("caps each country on its own", () => {
		// Opening one country must not open the other.
		const $wrapper = render({
			exemption_type: "Wholesale",
			exempt_regions: [...us_states(REGIONS_SHOWN + 5), { country: "CA", state: "ON" }],
		});
		expect($wrapper.find(".taxjar-region-chips").length).toBe(2);
		expect($wrapper.find(".taxjar-region-chips .es-button").length).toBe(1);
	});
});
