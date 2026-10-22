// A small stand-in for the parts of the desk that `taxjar_utils.js` touches.
//
// The client gating in the company-scope design (§3.4) had no automated cover:
// this repo had no JavaScript test infrastructure, so a green Python suite said
// nothing about whether the forms behave. The scripts are plain browser scripts
// that hang off a global rather than ES modules, so they are evaluated here
// instead of imported, against the globals the desk gives them.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { vi } from "vitest";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP_ROOT = path.resolve(HERE, "../../..");
const JS_ROOT = path.join(APP_ROOT, "taxjar_integration/public/js");
const TELEMETRY_PATH = path.join(JS_ROOT, "telemetry.js");
const UTILS_PATH = path.join(JS_ROOT, "taxjar_utils.js");
const DESK_SIDEBAR_PATH = path.join(JS_ROOT, "desk_sidebar.js");
const SETTINGS_PATH = path.join(
	APP_ROOT,
	"taxjar_integration/taxjar_integration/doctype/taxjar_settings/taxjar_settings.js"
);
const CUSTOMER_PATH = path.join(JS_ROOT, "customer.js");
const ADDRESS_PATH = path.join(JS_ROOT, "address.js");

// The transaction forms, by the doctype each one registers. Read from disk, not
// transcribed: a test that copies the handlers out of these files cannot notice
// a handler added to them, which is the one thing it most needs to notice.
const FORM_SCRIPTS = {
	Quotation: path.join(JS_ROOT, "quotation.js"),
	"Sales Order": path.join(JS_ROOT, "sales_order.js"),
	"Sales Invoice": path.join(JS_ROOT, "sales_invoice.js"),
};

// Read once. The source never changes inside a run, and each load evaluates it
// again in a fresh function scope.
const TELEMETRY_SOURCE = fs.readFileSync(TELEMETRY_PATH, "utf8");
const UTILS_SOURCE = fs.readFileSync(UTILS_PATH, "utf8");
const DESK_SIDEBAR_SOURCE = fs.readFileSync(DESK_SIDEBAR_PATH, "utf8");
const SETTINGS_SOURCE = fs.readFileSync(SETTINGS_PATH, "utf8");
const CUSTOMER_SOURCE = fs.readFileSync(CUSTOMER_PATH, "utf8");
const ADDRESS_SOURCE = fs.readFileSync(ADDRESS_PATH, "utf8");
const FORM_SOURCES = Object.fromEntries(
	Object.entries(FORM_SCRIPTS).map(([doctype, file]) => [doctype, fs.readFileSync(file, "utf8")])
);

export const TRANSACTION_DOCTYPES = Object.keys(FORM_SCRIPTS);

// ── The company profiles ──
// The first six are the ones the Python fixture uses (TaxJarCompanyProfile in
// test_taxjar_settings.py), written here as the payload get_company_scope
// returns for each. One vocabulary across both suites: a case named US_CALC in
// one file means the same company in the other.
//
// US_SITE_OFF is the seventh, and it is not a seventh company. It is the site
// switch, which company_scope() answers ahead of every company fact - so it
// arrives at the client as one more scope payload, and the client has to handle
// it like one.
function scope_payload(company, { in_scope, calculates, files, reason, country }) {
	return {
		company,
		in_scope,
		calculates,
		files,
		uses_taxjar: calculates || files,
		reason: reason || null,
		country,
	};
}

export const US_CALC = scope_payload("US Calc Co", {
	in_scope: true,
	calculates: true,
	files: false,
	country: "United States",
});

export const US_FILE = scope_payload("US File Co", {
	in_scope: true,
	calculates: false,
	files: true,
	country: "United States",
});

// In scope but every feature off. This is the state most easily confused with
// "not in scope at all", and the two want different messages.
export const US_OFF = scope_payload("US Off Co", {
	in_scope: true,
	calculates: false,
	files: false,
	country: "United States",
});

export const IN_CO = scope_payload("India Co", {
	in_scope: false,
	calculates: false,
	files: false,
	reason: "not_us",
	country: "India",
});

// The dangerous one: an India company somebody switched both features on for.
// The server refuses to act on it, so every field below reads the same as
// IN_CO. It is kept as its own profile because the client must not treat the
// two differently either.
export const IN_FLAGGED = scope_payload("India Flagged Co", {
	in_scope: false,
	calculates: false,
	files: false,
	reason: "not_us",
	country: "India",
});

// A company TaxJar could serve that nobody has configured. A different answer
// from "registered outside the United States", and it sends the reader
// somewhere different.
export const US_UNCONFIGURED = scope_payload("US Unconfigured Co", {
	in_scope: false,
	calculates: false,
	files: false,
	reason: "not_configured",
	country: "United States",
});

// TaxJar is switched off for the whole site. Every company reads this way while
// the switch is off, whatever its own country or configuration says.
export const US_SITE_OFF = scope_payload("US Site Off Co", {
	in_scope: false,
	calculates: false,
	files: false,
	reason: "site_off",
	country: "United States",
});

export const ALL_PROFILES = [
	US_CALC, US_FILE, US_OFF, IN_CO, IN_FLAGGED, US_UNCONFIGURED, US_SITE_OFF,
];
export const OUT_OF_SCOPE_PROFILES = [IN_CO, IN_FLAGGED, US_UNCONFIGURED, US_SITE_OFF];

export const SCOPE_METHOD = "taxjar_integration.taxjar_integration.taxjar_integration.get_company_scope";

// ── Globals ──

// frappe's own `__`, reduced to what the strings under test use: positional
// {0}, {1} substitution and nothing else. No translation is loaded in a test,
// so the source string comes back, which is what the assertions read.
function translate(text, args) {
	let out = String(text);
	if (Array.isArray(args)) {
		args.forEach((value, index) => {
			out = out.split(`{${index}}`).join(String(value));
		});
	}
	return out;
}

function cint(value) {
	const number = parseInt(value, 10);
	return Number.isNaN(number) ? 0 : number;
}

// frappe's own global, reduced to what the strings under test read back: a
// currency code and a number, in that order. No number format is loaded in a
// test, so the assertions match on this shape rather than a locale's.
function format_currency(value, currency) {
	const amount = Number(value || 0).toFixed(2);
	return currency ? `${currency} ${amount}` : amount;
}

function escape_html(value) {
	const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
	return String(value === undefined || value === null ? "" : value).replace(
		/[&<>"']/g,
		(character) => map[character]
	);
}

/**
 * Install the desk globals and return the frappe stub so a test can drive it.
 *
 * `xcall` resolves null by default. A test that cares what an endpoint answers
 * sets it with `answer_xcall` below, which keeps the method name in the test
 * rather than in a shared default nobody reads.
 */
function badge_html(opts = {}) {
	const theme = opts.theme === "orange" ? "amber" : opts.theme;
	const attr = theme && theme !== "gray" ? ` data-theme="${theme}"` : "";
	// frappe draws the icon before the label, from its own sprite.
	const icon = opts.icon ? `<svg class="icon icon-${opts.icon}"></svg>` : "";
	return `<span class="es-badge"${attr}>${icon}${escape_html(opts.label || "")}</span>`;
}

export function install_desk() {
	const frappe = {
		xcall: vi.fn(() => Promise.resolve(null)),
		// Telemetry off, so taxjar_integration.track sends nothing.
		boot: { enable_telemetry: false },
		msgprint: vi.fn(),
		msg_dialog: { hide: vi.fn() },
		new_doc: vi.fn(),
		show_alert: vi.fn(),
		set_route: vi.fn(),
		validated: true,
		call: vi.fn(() => Promise.resolve({ message: null })),
		realtime: { on: vi.fn(), off: vi.fn() },
		// Grid rows are reached through `locals`, not through the parent form,
		// so a write has to land in both for the test to read it back.
		model: {
			set_value: vi.fn((doctype, name, fieldname, value) => {
				const row = (globalThis.locals[doctype] || {})[name];
				if (row) row[fieldname] = value;
				return Promise.resolve();
			}),
			open_mapped_doc: vi.fn(),
		},
		// The two reads the credit-note picker makes. Both answer empty by
		// default, for the same reason xcall does: a test that cares what
		// comes back says so itself, next to the assertion that reads it.
		db: {
			count: vi.fn(() => Promise.resolve(0)),
			get_value: vi.fn(() => Promise.resolve({ message: {} })),
		},
		datetime: {
			str_to_user: (value) => value,
			prettyDate: (value) => value,
		},
		utils: {
			escape_html,
			// frappe's own markup: the display text arrives escaped, the name
			// rides in the route encoded.
			get_form_link: (doctype, name, html = false, display_text = null) => {
				const route = `/desk/${doctype.toLowerCase().replace(/ /g, "-")}/${encodeURIComponent(name)}`;
				return html ? `<a href="${route}">${display_text || escape_html(name)}</a>` : route;
			},
			icon: (name) => `<svg class="icon icon-${name}"></svg>`,
			// frappe's own test: does the string contain a tag.
			is_html: (text) => /<[a-z][\s\S]*>/i.test(String(text)),
		},
		ui: {
			// Both forms badge.js offers, from one piece of markup so they cannot
			// drift apart. The label is escaped, and a theme rides as
			// `data-theme` unless it is the default gray, which is exactly what
			// the assertions read. `frappe.ui.badge` itself returns an element -
			// the sidebar pill hangs a style and a hover card off the one it
			// gets back - while `frappe.ui.badge.html` returns the markup a
			// badge built inside a template literal needs.
			badge: Object.assign(
				vi.fn((opts = {}) => $(badge_html(opts))),
				{ html: badge_html }
			),
			hover_card: vi.fn(),
			empty_state: vi.fn(() => "<div class='empty-state'></div>"),
			Dialog: vi.fn(function Dialog(options) {
				this.options = options;
				this.$wrapper = $("<div class='modal'></div>");
				this.fields_dict = {};
				this.show = vi.fn();
				this.hide = vi.fn();
				this.set_value = vi.fn();
				this.get_value = vi.fn();
			}),
			form: { on: vi.fn() },
		},
	};

	globalThis.frappe = frappe;
	globalThis.__ = translate;
	globalThis.cint = cint;
	globalThis.format_currency = format_currency;
	globalThis.locals = {};
	window.frappe = frappe;
	window.__ = translate;
	window.cint = cint;
	window.format_currency = format_currency;
	window.locals = globalThis.locals;

	// Every test starts from an empty page. The sidebar helpers insert into
	// `.form-sidebar`, so the shape they look for has to be there.
	document.body.innerHTML = `
		<div class="form-sidebar">
			<div class="sidebar-meta-details"></div>
		</div>
	`;

	return frappe;
}

/**
 * Evaluate taxjar_utils.js fresh.
 *
 * `new Function` rather than `import`: the file is a browser script that
 * assigns to `window.taxjar_integration` and declares file-level `const`s. Run
 * through a function body those `const`s are scoped to the call, so the file
 * can be loaded again for the next test without redeclaration, and every free
 * identifier in it - frappe, __, cint, $ - resolves to the global at call time,
 * which is how the desk resolves them too.
 */
export function load_taxjar_utils() {
	delete window.taxjar_integration;
	delete globalThis.taxjar_integration;
	// The bundle loads telemetry.js first, and taxjar_utils.js calls its track.
	// eslint-disable-next-line no-new-func
	new Function(TELEMETRY_SOURCE)();
	// eslint-disable-next-line no-new-func
	new Function(UTILS_SOURCE)();
	return window.taxjar_integration;
}

/**
 * Evaluate desk_sidebar.js fresh, and return the app namespace it adds to.
 *
 * Loaded the same way as taxjar_utils.js, and for the same reason: it is a
 * browser script, and its file-level `const`s are scoped to the call, so each
 * test gets a fresh evaluation against the globals of that test.
 */
export function load_desk_sidebar() {
	// eslint-disable-next-line no-new-func
	new Function(DESK_SIDEBAR_SOURCE)();
	return window.taxjar_integration;
}

/**
 * Evaluate the three transaction form scripts, and return their handlers.
 *
 * The handlers come out of the files themselves, through the same
 * `frappe.ui.form.on` the desk registers them with. So a handler added to one
 * of those files is picked up here without anyone editing a test, which is the
 * point: a transcribed copy of these handlers would go on passing while the
 * real form grew an ungated one.
 *
 * taxjar_utils.js has to be loaded first; the form scripts call into it.
 */
export function load_transaction_forms() {
	for (const source of Object.values(FORM_SOURCES)) {
		// eslint-disable-next-line no-new-func
		new Function(source)();
	}

	const handlers = {};
	for (const [doctype, events] of frappe.ui.form.on.mock.calls) {
		handlers[doctype] = { ...(handlers[doctype] || {}), ...events };
	}

	for (const doctype of TRANSACTION_DOCTYPES) {
		if (!handlers[doctype]) {
			throw new Error(`${doctype} registered no handlers - has its form script moved?`);
		}
	}
	return handlers;
}

/**
 * Evaluate the TaxJar Settings form script, and return its handlers by doctype.
 *
 * The file's only effect on load is to register handlers through
 * `frappe.ui.form.on`, which the stub records. taxjar_utils.js has to be loaded
 * first: the settings script calls into it.
 */
export function load_taxjar_settings_form() {
	// eslint-disable-next-line no-new-func
	new Function(SETTINGS_SOURCE)();

	const handlers = {};
	for (const [doctype, events] of frappe.ui.form.on.mock.calls) {
		handlers[doctype] = { ...(handlers[doctype] || {}), ...events };
	}
	return handlers;
}

/**
 * Put one grid row in `locals` and hand back what a grid event is called with.
 */
/**
 * Evaluate customer.js, and return its handlers by doctype.
 *
 * Loaded the same way as the form scripts above, for the same reason: it is a
 * browser script whose only effect on load is to register handlers through
 * `frappe.ui.form.on`. taxjar_utils.js has to be loaded first - the exemption
 * card resolves region codes to full names through it.
 */
export function load_customer_form() {
	// eslint-disable-next-line no-new-func
	new Function(CUSTOMER_SOURCE)();

	const handlers = {};
	for (const [doctype, events] of frappe.ui.form.on.mock.calls) {
		handlers[doctype] = { ...(handlers[doctype] || {}), ...events };
	}
	if (!handlers.Customer) {
		throw new Error("Customer registered no handlers - has its form script moved?");
	}
	return handlers.Customer;
}

/**
 * Evaluate address.js, and return its handlers.
 *
 * Loaded the same way as the form scripts above, and for the same reason: it is
 * a browser script whose only effect on load is to register handlers through
 * `frappe.ui.form.on`. taxjar_utils.js has to be loaded first - the state code
 * map and the stand-in both live there.
 */
export function load_address_form() {
	// eslint-disable-next-line no-new-func
	new Function(ADDRESS_SOURCE)();

	const handlers = {};
	for (const [doctype, events] of frappe.ui.form.on.mock.calls) {
		handlers[doctype] = { ...(handlers[doctype] || {}), ...events };
	}
	if (!handlers.Address) {
		throw new Error("Address registered no handlers - has its form script moved?");
	}
	return handlers.Address;
}

/**
 * Replace `frappe.ui.Dialog` with one that keeps a value per field.
 *
 * The inert stub in `install_desk` answers every read the same way, so a dialog
 * that reads its own fields back cannot be driven through it: the credit-note
 * picker's Continue button would never see a choice, and the test would be
 * asserting on a button that can only fail.
 *
 * This keeps one value per field, seeded from that field's `default`, and fires
 * the field's own `onchange` on a write, which is what a desk control does. A
 * `hide()` runs `on_hide`, which is the path Escape and the backdrop take.
 *
 * Returns the array the dialogs land in, oldest first.
 */
export function record_dialogs() {
	const opened = [];

	frappe.ui.Dialog = vi.fn(function Dialog(options) {
		const values = {};
		const fields_dict = {};

		for (const field of options.fields || []) {
			if (!field.fieldname) continue;
			values[field.fieldname] = field.default === undefined ? "" : field.default;
			fields_dict[field.fieldname] = {
				df: field,
				$wrapper: $(`<div class='control-${field.fieldname}'></div>`),
			};
		}

		this.options = options;
		this.fields_dict = fields_dict;
		this.$wrapper = $("<div class='modal'></div>");
		this.get_value = (fieldname) => values[fieldname];
		// frappe hands the primary action whatever get_values() returns, and
		// leaves out a box that is empty - so a test that drives the action
		// reads the same shape the server is sent.
		this.get_values = () =>
			Object.fromEntries(
				Object.entries(values).filter(([, value]) => value !== "" && value != null)
			);
		this.set_value = vi.fn((fieldname, value) => {
			values[fieldname] = value;
			const field = fields_dict[fieldname];
			if (field && field.df.onchange) field.df.onchange();
			return Promise.resolve();
		});
		this.set_df_property = vi.fn((fieldname, property, value) => {
			const field = fields_dict[fieldname];
			if (field) field.df[property] = value;
		});
		this.show = vi.fn();
		this.hide = vi.fn(() => {
			if (options.on_hide) options.on_hide();
		});

		opened.push(this);
	});

	return opened;
}

/** The HTML a dialog's HTML field was built with. */
export function dialog_html(dialog, fieldname) {
	const field = dialog.fields_dict[fieldname];
	return field ? field.df.options || "" : "";
}

export function add_grid_row(doctype, name, values) {
	globalThis.locals[doctype] = globalThis.locals[doctype] || {};
	globalThis.locals[doctype][name] = { doctype, name, ...values };
	return { cdt: doctype, cdn: name, row: globalThis.locals[doctype][name] };
}

/**
 * Point `frappe.xcall` at a table of answers, keyed on the method name.
 *
 * A method with no entry rejects rather than resolving empty. A gate that is
 * working does not reach its endpoint at all, so an unexpected call should
 * fail the test loudly instead of passing through as "nothing came back".
 */
export function answer_xcall(frappe, answers) {
	frappe.xcall.mockImplementation((method, args) => {
		if (Object.prototype.hasOwnProperty.call(answers, method)) {
			const answer = answers[method];
			return Promise.resolve(typeof answer === "function" ? answer(args) : answer);
		}
		return Promise.reject(new Error(`unexpected xcall: ${method}`));
	});
}

/** Shorthand for the common case: one company, one scope answer. */
export function answer_scope(frappe, profile, extra = {}) {
	answer_xcall(frappe, { [SCOPE_METHOD]: profile, ...extra });
}

// ── The form ──

// frappe.ui.form.Layout.show_message, reproduced from layout.js so the message
// strip behaves as it does on a real form. _set_tax_message depends on the
// detail: show_message appends, and only clears when called with nothing.
function make_layout() {
	const message = $("<div class='form-message-container hidden'></div>");
	document.body.appendChild(message[0]);

	return {
		message,
		show_message(html, color, permanent = false) {
			if (!html) {
				message.empty().addClass("hidden");
				return;
			}
			const block = frappe.utils.is_html(html)
				? $("<div class='form-message border-bottom'>").html(html)
				: $("<div class='form-message border-bottom'></div>").text(html);
			if (!permanent) {
				$(`<div class="close-message"></div>`).appendTo(block);
			}
			const known = ["yellow", "blue", "red", "green", "orange", "white"];
			block.addClass(known.includes(color) ? color : "blue");
			block.appendTo(message);
			message.removeClass("hidden");
		},
	};
}

/**
 * A fake form good enough for the gates.
 *
 * `fields` names the fields the form has. Every one gets a `$wrapper` and a
 * `df`, so `set_df_property` writes somewhere a test can read. A field the
 * caller does not name is absent, which is itself a case under test: the
 * sidebar pill returns early on a document with no taxjar_sync_status field.
 */
export function make_frm({
	doctype = "Sales Invoice",
	company = US_CALC.company,
	name = "SINV-0001",
	is_new = false,
	fields = ["taxjar_tab", "taxjar_exemption_section", "taxjar_breakdown_section"],
	doc = {},
} = {}) {
	const fields_dict = {};
	for (const fieldname of fields) {
		fields_dict[fieldname] = {
			df: { fieldname, hidden: 0, read_only: 0 },
			$wrapper: $(`<div class='field-${fieldname}'></div>`),
		};
	}

	const frm = {
		doctype,
		doc: { doctype, company, name, docstatus: 0, ...doc },
		fields_dict,
		layout: make_layout(),
		is_new: () => is_new,
		set_df_property: vi.fn((fieldname, property, value) => {
			if (fields_dict[fieldname]) fields_dict[fieldname].df[property] = value;
		}),
		set_value: vi.fn((fieldname, value) => {
			frm.doc[fieldname] = value;
			return Promise.resolve();
		}),
		save: vi.fn(),
		refresh_field: vi.fn(),
		reload_doc: vi.fn(() => Promise.resolve()),
		add_custom_button: vi.fn(),
		get_field: (fieldname) => fields_dict[fieldname],
	};

	return frm;
}

/** Read the text of whatever is currently in the form message strip. */
export function message_text(frm) {
	return frm.layout.message.text().trim();
}

/** Read the HTML of whatever is currently in the form message strip. */
export function message_html(frm) {
	return frm.layout.message.html();
}

/** Read the sidebar section the pill renderer mounts, if it mounted one. */
export function sidebar_section() {
	return $(document).find(".form-sidebar .taxjar-sync-sidebar-pill-section");
}

/**
 * Let every pending promise settle.
 *
 * Some entry points start the scope read and return nothing, because the form
 * has nothing to wait for. A test still has to wait, or it reads the page
 * before the answer lands.
 */
export function flush() {
	return new Promise((resolve) => setTimeout(resolve, 0));
}
