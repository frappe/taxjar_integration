if (!window.taxjar_integration) {
	window.taxjar_integration = {};
}

// The guided setup page, opened on the card that holds the setting these two
// links exist because of. Both appear only when a company has Calculate Sales
// Tax or File Transactions switched off, and Features is the step that owns
// both flags - so the link says which card to open rather than dropping the
// user on the summary to find it.
//
// The error-message links elsewhere in this file stay unfocused on purpose:
// their cause varies per message, so naming one card would be a guess.
const TAXJAR_SETUP_FEATURES_URL = "/app/taxjar-setup?focus=features";

// ── The roles documentation link ──
// A permission refusal ends with "Read documentation", which links here (see
// ROLES_DOCS_URL in access.py, the same URL). Frappe cleans the HTML of every
// message it shows, and the cleaning keeps href but drops target, so this one
// link is opened in a new tab here. Every other link stays with the desk. The
// handler is named, so loading this file again replaces it rather than adding a
// second one.
taxjar_integration.ROLES_DOCS_URL = "https://docs.example.com/taxjar/roles-and-permissions";

$(document)
	.off("click.taxjar_roles_docs")
	.on("click.taxjar_roles_docs", `a[href^="${taxjar_integration.ROLES_DOCS_URL}"]`, function (event) {
		event.preventDefault();
		window.open(this.href, "_blank", "noopener,noreferrer");
	});

// ── Shared geography constants ──
// Single source of truth for US state + Canadian province codes used across the
// Address and Customer forms and the TaxJar Customers configuration page.
taxjar_integration.US_STATE_NAMES = {
	AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas",
	CA: "California", CO: "Colorado", CT: "Connecticut", DE: "Delaware",
	DC: "District of Columbia", FL: "Florida", GA: "Georgia", HI: "Hawaii",
	ID: "Idaho", IL: "Illinois", IN: "Indiana", IA: "Iowa",
	KS: "Kansas", KY: "Kentucky", LA: "Louisiana", ME: "Maine",
	MD: "Maryland", MA: "Massachusetts", MI: "Michigan", MN: "Minnesota",
	MS: "Mississippi", MO: "Missouri", MT: "Montana", NE: "Nebraska",
	NV: "Nevada", NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico",
	NY: "New York", NC: "North Carolina", ND: "North Dakota", OH: "Ohio",
	OK: "Oklahoma", OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island",
	SC: "South Carolina", SD: "South Dakota", TN: "Tennessee", TX: "Texas",
	UT: "Utah", VT: "Vermont", VA: "Virginia", WA: "Washington",
	WV: "West Virginia", WI: "Wisconsin", WY: "Wyoming",
};
taxjar_integration.US_STATE_CODES = Object.keys(taxjar_integration.US_STATE_NAMES);

// ISO 3166-2:CA - https://en.wikipedia.org/wiki/ISO_3166-2:CA
taxjar_integration.CA_PROVINCE_NAMES = {
	AB: "Alberta", BC: "British Columbia", MB: "Manitoba", NB: "New Brunswick",
	NL: "Newfoundland and Labrador", NS: "Nova Scotia", NT: "Northwest Territories",
	NU: "Nunavut", ON: "Ontario", PE: "Prince Edward Island", QC: "Quebec",
	SK: "Saskatchewan", YT: "Yukon",
};
taxjar_integration.CA_PROVINCE_CODES = Object.keys(taxjar_integration.CA_PROVINCE_NAMES);

taxjar_integration.REGION_NAMES_BY_COUNTRY = {
	US: taxjar_integration.US_STATE_NAMES,
	CA: taxjar_integration.CA_PROVINCE_NAMES,
};

// Where nexus is actually declared - TaxJar's own account settings. Nothing in
// this app can add one, so every "no nexus" message points here.
taxjar_integration.TAXJAR_NEXUS_URL = "https://app.taxjar.com/account#api-access:~:text=Nexus%20Address%20Configuration";

// The app's own mark, the same file hooks.app_logo_url serves to the apps
// screen - one asset, so a re-brand is one file and never leaves a second copy
// of an older mark to be found later.
// test_the_sidebar_logo_is_the_app_logo keeps this path and the hook together.
taxjar_integration.LOGO_URL = "/assets/taxjar_integration/images/taxjar_logo.png";

// Decorative: every caption it sits beside already says "TaxJar", so an alt
// text would only repeat the next word to a screen reader.
taxjar_integration._logo_html = function () {
	return `<img src="${taxjar_integration.LOGO_URL}" alt="" width="20" height="20" style="flex-shrink: 0;">`;
};

taxjar_integration.region_full_name = function (country, code) {
	return (taxjar_integration.REGION_NAMES_BY_COUNTRY[country] || {})[code] || code;
};

// The two flags this app can ever draw - it stores regions for the United
// States and Canada and nowhere else (see REGION_NAMES_BY_COUNTRY above).
// Drawn inline rather than fetched: two shapes at 16px cost less as markup
// than as two more requests, and an <img> that 404s leaves a broken-image box
// where the flag should be.
//
// Both are authored on a 20x15 viewBox and drawn with plain rects and one
// polygon, so they scale to whatever the caller sizes .taxjar-flag at. The
// stars are dots rather than five-pointed stars on purpose: at 16px wide a
// real star is three grey pixels, and a dot grid reads as the canton while a
// smudge does not. No <clipPath> either - an id inside markup that renders
// twice on a page collides with itself, so the rounded corner is CSS on the
// wrapper instead.
const COUNTRY_FLAG_SVG = {
	US: `<svg viewBox="0 0 20 15" xmlns="http://www.w3.org/2000/svg">
		<rect width="20" height="15" fill="#ffffff"/>
		<g fill="#b22234">
			<rect y="0" width="20" height="1.154"/><rect y="2.308" width="20" height="1.154"/>
			<rect y="4.615" width="20" height="1.154"/><rect y="6.923" width="20" height="1.154"/>
			<rect y="9.231" width="20" height="1.154"/><rect y="11.538" width="20" height="1.154"/>
			<rect y="13.846" width="20" height="1.154"/>
		</g>
		<rect width="8" height="8.077" fill="#3c3b6e"/>
		<g fill="#ffffff">
			<circle cx="1.15" cy="1.35" r="0.3"/><circle cx="2.85" cy="1.35" r="0.3"/>
			<circle cx="4.55" cy="1.35" r="0.3"/><circle cx="6.25" cy="1.35" r="0.3"/>
			<circle cx="2" cy="3.15" r="0.3"/><circle cx="3.7" cy="3.15" r="0.3"/>
			<circle cx="5.4" cy="3.15" r="0.3"/>
			<circle cx="1.15" cy="4.95" r="0.3"/><circle cx="2.85" cy="4.95" r="0.3"/>
			<circle cx="4.55" cy="4.95" r="0.3"/><circle cx="6.25" cy="4.95" r="0.3"/>
			<circle cx="2" cy="6.75" r="0.3"/><circle cx="3.7" cy="6.75" r="0.3"/>
			<circle cx="5.4" cy="6.75" r="0.3"/>
		</g>
	</svg>`,
	CA: `<svg viewBox="0 0 20 15" xmlns="http://www.w3.org/2000/svg">
		<rect width="20" height="15" fill="#ffffff"/>
		<rect width="5" height="15" fill="#d52b1e"/>
		<rect x="15" width="5" height="15" fill="#d52b1e"/>
		<polygon fill="#d52b1e" points="10,2.6 11,4.9 12.9,4.5 12.3,6.6 14.5,6.2 13.2,8 14.1,8.7 11.5,9.5 11.8,11.6 10.5,11.2 10.5,12.4 9.5,12.4 9.5,11.2 8.2,11.6 8.5,9.5 5.9,8.7 6.8,8 5.5,6.2 7.7,6.6 7.1,4.5 9,4.9"/>
	</svg>`,
};

// Decorative: the country's own name is always right beside it, so a screen
// reader that announced the flag too would just say the country twice. Empty
// string for a country with no flag on file, so a caller can concatenate it
// without checking first.
taxjar_integration.country_flag_html = function (country) {
	const svg = COUNTRY_FLAG_SVG[country];
	if (!svg) return "";
	return `<span class="taxjar-flag" aria-hidden="true">${svg}</span>`;
};

// Select options for a US state code, as "AK — Alaska" over the stored "AK".
// The value is still the 2-letter code TaxJar asks for, but a list of 51 bare
// codes is read one guess at a time, so the option text carries the name too.
// One builder for every state picker in the app - the Address form and the
// guided setup's address dialog - so both lists read the same.
//
// Sorted by code, because the code is what the reader scans down.
taxjar_integration.us_state_code_options = function () {
	const names = taxjar_integration.US_STATE_NAMES;
	// A leading blank option, so the field can go back to empty. Frappe adds
	// one on its own only when the options are a newline string.
	return [{ label: "", value: "" }].concat(
		Object.keys(names).sort().map((code) => ({ label: `${code} — ${names[code]}`, value: code }))
	);
};

// A US state code from whatever the reader typed into the State box: the code
// itself, or the state's full name. Null where the text names neither.
//
// The map it reads is US_STATE_NAMES above, the one map every state picker in
// this app reads, so the Address form and the transaction's own Create Address
// dialog resolve a name the same way.
const TAXJAR_US_STATE_CODE_BY_NAME = Object.fromEntries(
	Object.entries(taxjar_integration.US_STATE_NAMES).map(([code, name]) => [
		name.toUpperCase(),
		code,
	])
);

taxjar_integration.us_state_code_from_name = function (state) {
	if (!state) return null;
	const upper = String(state).toUpperCase().trim();
	if (taxjar_integration.US_STATE_NAMES[upper]) return upper;
	return TAXJAR_US_STATE_CODE_BY_NAME[upper] || null;
};

// ── Region hover card ──
// The card behind a region count, on the Customer Configuration page and on the
// guided setup's Nexus card. A count says how many, not which; this card names
// them, one section per country.
//
// Past five names the list stops being read and starts being skimmed for its
// length, which the count beside it already gives - so it is capped.
taxjar_integration.REGION_PREVIEW_LIMIT = 5;

// `sections` is [{heading, names, all_label}]. The caller resolves the names,
// because the two pages hold different data: the customer page stores codes for
// two known countries, and nexus arrives from TaxJar with its own country names.
// `all_label` is the one sentence that replaces the names when the country is
// complete, since a 51-name list only reads as "all of them" after a count.
taxjar_integration.region_hover_card = function (sections) {
	const $card = $(`<div class="taxjar-regions-card"></div>`);
	const limit = taxjar_integration.REGION_PREVIEW_LIMIT;

	sections.forEach(({ heading, names, all_label }) => {
		if (!names.length) return;

		const sorted = names.slice().sort();
		let body;
		if (all_label) {
			body = all_label;
		} else if (sorted.length > limit) {
			body = __("{0}, and {1} more.", [sorted.slice(0, limit).join(", "), sorted.length - limit]);
		} else {
			body = sorted.join(", ");
		}

		$card.append(`
			<div class="taxjar-regions-card-heading">${heading}</div>
			<div class="taxjar-regions-card-body">${frappe.utils.escape_html(body)}</div>
		`);
	});

	return $card;
};

// ── Sync failure dialog ──
// Some of taxjar_integration.py's classify_taxjar_error() messages (e.g. an
// invalid API token) point the user at the guided setup wizard by name -
// turn that phrase into an actual link wherever the message reaches an
// interactive dialog. The stored Sync Error field itself stays plain text
// (it's a Small Text field, which renders as text, not HTML) - only this
// dialog rendering gets the link.
// ── Company scope ──
// Every TaxJar feature on a transaction form depends on one question - what may
// TaxJar do for this document's company - and the form used to ask two different
// halves of it, on two endpoints, several times per load, while the features that
// block a save asked nothing at all. That is why a company registered outside the
// United States was told its shipping address was required and that it had no
// nexus in Karnataka.
//
// One promise per company, memoised for the life of the page. Memoised on the
// promise rather than its result so that the several callers that run together on
// a single refresh share one request instead of racing four.
//
// The company is read fresh from the form each time rather than captured: changing
// the company on a draft has to change the answer.
taxjar_integration._scope_cache = {};

taxjar_integration.scope = function (company) {
	if (!company) return Promise.resolve(null);

	if (!taxjar_integration._scope_cache[company]) {
		taxjar_integration._scope_cache[company] = frappe
			.xcall("taxjar_integration.taxjar_integration.taxjar_integration.get_company_scope", {
				company,
			})
			.catch(() => {
				// A failed read must not leave a permanently poisoned entry, and
				// must not leave the form asserting things about a company it
				// could not resolve. Null reads as "out of scope" everywhere.
				delete taxjar_integration._scope_cache[company];
				return null;
			});
	}

	return taxjar_integration._scope_cache[company];
};

// The scope answer is memoised for the life of the page, which is right until
// somebody changes the configuration it describes. Nothing on a transaction form
// can change it. The two screens that can - the TaxJar Settings form and the
// guided setup page - call this when they write, so the next form load asks
// again instead of painting an answer from before the change. Without it the
// sidebar reported the old configuration until a hard refresh.
//
// The export memo goes with it. check_export_destination answers two questions
// in one call, and the second one - files_exports - is read off the same company
// configuration this clears (see the server method). So the two memos hold parts
// of one answer and have to be forgotten together: clearing only the first left
// a draft's pill saying "Submit to Sync" for an export the company had just
// stopped filing, until a hard refresh. One function, because a caller that has
// to remember two cannot be relied on to.
taxjar_integration.clear_scope_cache = function () {
	taxjar_integration._scope_cache = {};
	taxjar_integration._export_cache = {};
};

// Sugar for the common shape: run `fn` only when the company is in TaxJar's
// remit and `predicate` holds for it. Every entry point below goes through this,
// so "does this apply here?" is asked one way in one place.
taxjar_integration.when_scoped = function (frm, predicate, fn) {
	return taxjar_integration.scope(frm.doc.company).then((scope) => {
		if (!scope || !scope.in_scope) return;
		if (predicate && !predicate(scope)) return;
		return fn(scope);
	});
};

// erpnext writes a party's defaults in one go: customer_address,
// shipping_address_name and a dozen other fields, one after another, with
// frm.updating_party_details set for the whole run (party.js).
//
// The fields land one at a time, so anything that reads the destination between
// two of them reads a half-written document - a billing address in one country
// beside a ship-to field that is not set yet. That is how a yellow "no tax on
// an export" strip appeared for a moment on picking a customer, and went again
// as soon as the ship-to field landed.
//
// erpnext's own address helpers refuse to run on this same flag, and party.js
// clears it and calls frm.refresh() once the write is done - which runs every
// gated entry point again, on the settled document. So nothing is skipped, only
// deferred to the one moment the document is whole.
taxjar_integration.party_details_are_updating = function (frm) {
	return !!(frm && frm.updating_party_details);
};

// ── Export destinations ──
// A sale delivered to another country. TaxJar prices United States sales tax,
// so it prices nothing here: no tax is charged, nothing is filed, and the form
// says so instead of reporting a state that does not exist. The server asks the
// same question of the saved document - see is_export_destination() in
// taxjar_integration.py.
//
// Cached per address, the same way scope() is cached per company: three parts
// of the form need this answer on the same form load, and it is one column of
// one Address.
taxjar_integration._export_cache = {};

// The same stand-in the server writes - see UNKNOWN_REGION_CODE in
// taxjar_integration.py. Named here so the dialog's sentence and the stored
// value cannot drift apart.
taxjar_integration.UNKNOWN_REGION_CODE = "XX";

taxjar_integration.export_destination = function (address, company) {
	if (!address) return Promise.resolve(null);

	// Keyed by both, not by the address alone. Whether an export is filed is a
	// per-company setting, so the same address answers differently for two
	// companies and one cached answer would speak for both.
	const key = `${company || ""}::${address}`;

	if (!taxjar_integration._export_cache[key]) {
		taxjar_integration._export_cache[key] = frappe
			.xcall(
				"taxjar_integration.taxjar_integration.taxjar_integration.check_export_destination",
				{ address, company }
			)
			.then((answer) => (answer && answer.country ? answer : null))
			.catch(() => {
				// Same reason scope() clears its own entry on failure: a failed
				// read must not become a permanent answer.
				delete taxjar_integration._export_cache[key];
				return null;
			});
	}

	return taxjar_integration._export_cache[key];
};

// The reason an export is exempt, as one of the Select's own options. TaxJar
// offers Wholesale, Government and Other, and an export is none of the first
// two - test_export_exemption_type_is_a_valid_option keeps this in step with
// the field.
taxjar_integration.EXPORT_EXEMPTION_TYPE = "Other";

// The TaxJar tab, its exemption section and the breakdown section are created on
// every Quotation, Sales Order and Sales Invoice at install, so a company TaxJar
// does not serve carries a tab full of sections that can never say anything.
// Hidden from the field definition rather than by emptying the HTML inside it:
// a section whose control still exists is re-shown by the next refresh_sections().
taxjar_integration.toggle_taxjar_ui = function (frm) {
	return taxjar_integration.scope(frm.doc.company).then((scope) => {
		const show = Boolean(scope && scope.in_scope);
		["taxjar_tab", "taxjar_exemption_section", "taxjar_breakdown_section"].forEach((f) => {
			if (frm.fields_dict[f]) frm.set_df_property(f, "hidden", show ? 0 : 1);
		});
	});
};

taxjar_integration.show_taxjar_sync_error = function (title, message) {
	const html = frappe.utils
		.escape_html(message)
		.replace(/guided setup/i, `<a href="/app/taxjar-setup">${__("guided setup")}</a>`);
	frappe.msgprint({ title, message: html, indicator: "red" });
};

// One frappe.ui.form MultiCheck field per country (US states, CA provinces),
// each with its own built-in "Select All"/"Unselect All" buttons - real desk
// controls rather than a hand-built checkbox grid. `selected` is a Set of
// "US:TX"-style keys. Returns dialog field defs to splice into a Dialog's
// `fields` array, right after the Exemption Type Select. Shared by the
// Customers page's bulk dialog and the Customer form's per-customer dialog.
taxjar_integration.build_region_multicheck_fields = function (selected) {
	taxjar_integration._inject_multicheck_column_styles();

	const to_options = (codes, country) =>
		codes.map((code) => ({
			label: taxjar_integration.region_full_name(country, code),
			value: `${country}:${code}`,
			checked: selected.has(`${country}:${code}`),
		}));

	return [
		// Named so update_visibility can hide the section itself (not just
		// its individual fields) whenever the grid has nothing to show -
		// otherwise the section's own divider and padding are left behind as
		// bare whitespace with nothing inside it.
		{ fieldtype: "Section Break", fieldname: "taxjar_regions_section" },
		{
			fieldtype: "MultiCheck",
			fieldname: "taxjar_us_states",
			label: __("US States"),
			options: to_options(taxjar_integration.US_STATE_CODES, "US"),
			columns: 3,
			select_all: true,
		},
		{
			fieldtype: "MultiCheck",
			fieldname: "taxjar_ca_provinces",
			label: __("CA Provinces"),
			options: to_options(taxjar_integration.CA_PROVINCE_CODES, "CA"),
			columns: 2,
			select_all: true,
		},
		{
			fieldtype: "HTML",
			fieldname: "taxjar_regions_warning",
			options: `<p class="taxjar-region-requirement-warning text-danger small" style="display:none;">
				${__("Select at least one region for this exemption type.")}
			</p>`,
		},
	];
};

// MultiCheck's own `columns` option relies on this rule (multicheck.js sets
// --checkbox-options-columns inline and expects `.checkbox-options { columns:
// var(...) }` to consume it) - frappe only ships that rule in its website/
// portal stylesheet (templates/styles/standard.css), not the desk bundle, so
// a MultiCheck field inside a desk dialog renders as one long single column
// without it. Injected once.
taxjar_integration._inject_multicheck_column_styles = function () {
	if (document.getElementById("taxjar-multicheck-column-styles")) return;
	const style = document.createElement("style");
	style.id = "taxjar-multicheck-column-styles";
	style.textContent = `
		.checkbox-options {
			columns: var(--checkbox-options-columns);
		}
	`;
	document.head.appendChild(style);
};

// Reads both MultiCheck fields built by build_region_multicheck_fields back
// into {country, state} rows, the shape configure_exemption expects.
taxjar_integration.get_selected_regions = function (dialog) {
	const values = [
		...(dialog.get_value("taxjar_us_states") || []),
		...(dialog.get_value("taxjar_ca_provinces") || []),
	];
	return values.map((value) => {
		const [country, state] = value.split(":");
		return { country, state };
	});
};

// Types that require at least one exempt region on file - kept in lockstep
// with _EXEMPTION_TYPES_REQUIRING_REGIONS in taxjar_integration.py, the real
// enforcement point. This is a live UX layer on top of that server throw,
// not a replacement for it.
const EXEMPTION_TYPES_REQUIRING_REGIONS = new Set(["Wholesale", "Government", "Other"]);

// Wires a dialog built from build_region_multicheck_fields: shows the region
// fields only once a region-scoped type is chosen, and disables the primary
// action with a warning while such a type has no regions checked. Returns an
// `update()` function the caller invokes on exemption_type change and once
// after dialog.show().
taxjar_integration.wire_exemption_dialog = function (dialog) {
	const $warning = dialog.fields_dict.taxjar_regions_warning.$wrapper.find(
		".taxjar-region-requirement-warning"
	);

	// MultiCheck.toggle() forces a full refresh(), which re-derives its
	// checkboxes from the field's original df.options (construction-time
	// `checked` flags) and overwrites selected_options from those - calling
	// it on every checkbox click would silently undo the very click that
	// triggered it. So visibility is only touched here, driven off whether
	// "enabled" actually flipped, never on every requirement check.
	let regions_visible = null;
	const update_visibility = () => {
		const type = dialog.get_value("exemption_type");
		const enabled = EXEMPTION_TYPES_REQUIRING_REGIONS.has(type);

		// The section itself (its divider + padding) must disappear along
		// with its contents for blank or Non Exempt, both of which have
		// nothing to show here - otherwise it's left behind as bare
		// whitespace between Exemption Type and Apply. Section isn't a
		// Control subclass - .show()/.hide() are its own API, not the
		// MultiCheck-specific toggle()-driven refresh() risk below.
		if (enabled) {
			dialog.fields_dict.taxjar_regions_section.show();
		} else {
			dialog.fields_dict.taxjar_regions_section.hide();
		}

		if (enabled === regions_visible) return;
		regions_visible = enabled;

		dialog.fields_dict.taxjar_us_states.toggle(enabled);
		dialog.fields_dict.taxjar_ca_provinces.toggle(enabled);
	};

	const update_requirement = () => {
		const type = dialog.get_value("exemption_type");
		const has_region = taxjar_integration.get_selected_regions(dialog).length > 0;
		const blocked = EXEMPTION_TYPES_REQUIRING_REGIONS.has(type) && !has_region;

		$warning.toggle(blocked);
		if (blocked) {
			dialog.disable_primary_action();
		} else {
			dialog.enable_primary_action();
		}
	};

	// Switching to a type that doesn't take regions (blank, or Non Exempt)
	// must drop whatever was checked for the PREVIOUS type - otherwise
	// regions picked for e.g. Wholesale silently ride along underneath,
	// invisible once update_visibility hides the grid for either of these.
	// select_all(true) is the same call the "Unselect All" button makes - a
	// direct checkbox update, not the destructive toggle()-driven refresh()
	// above.
	const clear_regions_if_not_required = () => {
		if (EXEMPTION_TYPES_REQUIRING_REGIONS.has(dialog.get_value("exemption_type"))) return;
		dialog.fields_dict.taxjar_us_states.select_all(true);
		dialog.fields_dict.taxjar_ca_provinces.select_all(true);
	};

	// MultiCheck's Select All/Unselect All buttons set checkbox.checked
	// directly (not via .prop()), which never dispatches a "change" event -
	// on_change is the control's own hook, fired for both that and a single
	// checkbox click, so it's the only reliable place to catch every case.
	// Only the (non-destructive) requirement check runs from here.
	dialog.fields_dict.taxjar_us_states.df.on_change = update_requirement;
	dialog.fields_dict.taxjar_ca_provinces.df.on_change = update_requirement;

	return () => {
		clear_regions_if_not_required();
		update_visibility();
		update_requirement();
	};
};

taxjar_integration.check_shipping_address = function (frm) {
	if (frm.doc.shipping_address_name) {
		return;
	}

	let party_type = frm.doc.quotation_to || "Customer";
	let party_name = frm.doc.party_name || frm.doc.customer;

	if (!party_name || party_type !== "Customer") {
		return;
	}

	// A ship-to is only required because TaxJar needs a destination to price or
	// to file against. Without either feature there is nothing this address is
	// for, and blocking the save asks the user to satisfy a integration that is
	// not going to look at the answer.
	return taxjar_integration.when_scoped(
		frm,
		(scope) => scope.uses_taxjar,
		() => taxjar_integration._prompt_unless_export(frm, party_name)
	);
};

// An export needs no shipping address of its own. The billing address already
// names another country, TaxJar prices nothing there, and a second address in
// the same country would not change that - so the picker used to block the save
// to collect a destination nothing was ever going to read.
//
// Only asked when the document has a billing address to judge: with neither
// address set there is no country to read, and the picker is exactly what that
// document needs.
taxjar_integration._prompt_unless_export = function (frm, party_name) {
	if (!frm.doc.customer_address) {
		return taxjar_integration._prompt_for_shipping_address(frm, party_name);
	}

	return taxjar_integration.export_destination(frm.doc.customer_address, frm.doc.company).then((export_to) => {
		if (export_to) return;
		return taxjar_integration._prompt_for_shipping_address(frm, party_name);
	});
};

taxjar_integration._prompt_for_shipping_address = function (frm, party_name) {
	return frappe.xcall(
		"taxjar_integration.taxjar_integration.taxjar_integration.get_customer_addresses",
		{ customer: party_name }
	).then(function (addresses) {
		addresses = addresses || [];

		if (addresses.length) {
			frappe.validated = false;
			taxjar_integration.show_address_picker_dialog(frm, addresses);
			return;
		}

		if (frm.doc.doctype === "Quotation") {
			return;
		}

		frappe.validated = false;
		frappe.msgprint({
			title: __("No Addresses Found"),
			message: __("No addresses found for this customer. Please add a shipping address before saving."),
			indicator: "red",
			primary_action: {
				label: __("Add New Address"),
				action() {
					// The save this message blocked is made again once the
					// address is on the document.
					taxjar_integration._open_new_address(frm, { save_after: true });
					frappe.msg_dialog.hide();
				},
			},
		});
	});
};

// TaxJar refuses a transaction with a blank state or a blank postcode. It
// answers "State can't be blank" or "Zipcode can't be blank", the invoice is
// filed nowhere, and nothing says so until after the submit. Both were
// confirmed against the live API.
//
// So the gap is closed at save, while the reader is still on the document,
// rather than reported afterwards from the Transaction Sync page.
taxjar_integration.check_destination_address = function (frm) {
	const address = frm.doc.shipping_address_name || frm.doc.customer_address;
	if (!address) return;

	// Only where TaxJar will read the answer. check_shipping_address gates on
	// the same question, for the same reason.
	return taxjar_integration.when_scoped(
		frm,
		(scope) => scope.uses_taxjar,
		() => taxjar_integration._check_destination_address(frm, address)
	);
};

taxjar_integration._check_destination_address = function (frm, address) {
	return frappe
		.xcall("taxjar_integration.taxjar_integration.taxjar_integration.get_destination_address", {
			address,
		})
		.then((row) => {
			if (!row || !row.name) return;

			const missing = row.missing || [];
			// An unresolved region is asked about once. The dialog writes the
			// answer to the Address, so the next save reads it back and this
			// stops firing - which is what makes a country with no matching
			// region, like Singapore, saveable at all.
			if (!missing.length && row.region_resolved) return;

			frappe.validated = false;
			taxjar_integration._show_destination_address_dialog(frm, row, missing);
		});
};

// The sentence under the Region Code box, on the Address form and in every
// address dialog.
//
// Off the stand-in, not off region_resolved. A stored "XX" resolves - that is
// what stops the dialog reopening - but it was accepted rather than worked out,
// and the box has to say which of the two it holds.
//
// With the State box empty, nothing was looked up yet, so "cannot find" is not
// true. The box then says where its code comes from.
taxjar_integration._region_code_hint = function (is_placeholder, has_state) {
	return has_state && is_placeholder
		? __("Cannot find region code, using fallback code.")
		: __("Auto-filled based on State/Province.");
};

// The sentence under the State Code box. A State that names no United States
// state leaves the box as it was, so the reader picks the code instead.
taxjar_integration._state_code_hint = function (state) {
	const has_state = !!(state || "").trim();
	return has_state && !taxjar_integration.us_state_code_from_name(state)
		? __("Cannot find state code, please select from dropdown.")
		: __("Auto-filled based on State/Province.");
};

// The country box of an address dialog. ERPNext's Customer quick entry names
// it country_address, because "country" is already a field on the Customer.
taxjar_integration._dialog_country = function (d) {
	return d.get_value(d.__taxjar_country_field || "country");
};

// The country decides which code box the reader is filling, so a change to the
// state or to the country settles both: the state code for a United States
// sale, the region code for every other one.
taxjar_integration._refresh_dialog_codes = function (d) {
	if (!d) return;

	if (taxjar_integration._dialog_country(d) === "United States") {
		return taxjar_integration._fill_dialog_state_code(d);
	}

	// A state code left behind by an earlier country names a state this sale is
	// not delivered to, and the box that holds it is hidden now.
	if (d.fields_dict["taxjar_state_code"] && d.get_value("taxjar_state_code")) {
		d.set_value("taxjar_state_code", "");
	}

	return taxjar_integration._refresh_dialog_region(d);
};

// The state code, from whatever the reader typed into the State box. The two
// boxes hold one answer in two forms - "Arizona" and "AZ" - and the Address
// form fills each from the other in exactly this way.
//
// Only on a change, so the write below cannot answer itself: setting the code
// fills the State box, which asks for the code again.
taxjar_integration._fill_dialog_state_code = function (d) {
	if (!d.fields_dict["taxjar_state_code"]) return;

	d.set_df_property(
		"taxjar_state_code",
		"description",
		taxjar_integration._state_code_hint(d.get_value("state"))
	);

	const code = taxjar_integration.us_state_code_from_name(d.get_value("state"));
	if (code && code !== d.get_value("taxjar_state_code")) {
		return d.set_value("taxjar_state_code", code);
	}
};

// The other direction: the reader picks a code, and the State box takes the
// name it stands for. The same guard, for the same reason.
taxjar_integration._fill_dialog_state_from_code = function (d) {
	const code = d.get_value("taxjar_state_code");
	if (!code) return;

	const name = taxjar_integration.US_STATE_NAMES[code];
	if (name && name !== d.get_value("state")) {
		return d.set_value("state", name);
	}
};

// The region code, worked out again from the two boxes it comes from. A dialog
// that opened because no region could be worked out answers itself as the
// reader fills in the state, rather than sending the stand-in for a state that
// now names a region TaxJar can file.
taxjar_integration._refresh_dialog_region = function (d) {
	if (!d) return;
	const field = d.fields_dict["taxjar_region_code"];
	if (!field) return;

	// Only the latest lookup may write the box - see _refresh_region_code in
	// address.js. The server can answer overlapping lookups in any order.
	const lookup = (d.__taxjar_region_lookup = (d.__taxjar_region_lookup || 0) + 1);

	// The United States answer is taxjar_state_code on the Address, and the box
	// is hidden here.
	if (taxjar_integration._dialog_country(d) === "United States") return;

	// Only what this dialog wrote is replaced. A code the reader typed is their
	// answer, and an edit to the state does not make it ours to overwrite. The
	// stand-in is never the reader's answer, and a real region beats it.
	const unknown = taxjar_integration.UNKNOWN_REGION_CODE;
	const current = (d.get_value("taxjar_region_code") || "").trim();
	if (current !== (d.__taxjar_region_code || "") && current !== unknown) return;

	const has_state = !!(d.get_value("state") || "").trim();

	// What the box holds before a State is typed. A quick entry sets "", as the
	// Address form does, and the save works out the code from the State. A
	// State with no matching region always gets the stand-in.
	const no_state_code = d.__taxjar_no_state_code ?? unknown;

	const apply = (code) => {
		const is_placeholder = code === unknown;

		d.__taxjar_region_code = code;
		d.set_value("taxjar_region_code", code);
		d.set_df_property(
			"taxjar_region_code",
			"description",
			taxjar_integration._region_code_hint(is_placeholder, has_state)
		);
		// The red outline asks for an answer. This is one, so it goes -
		// _mark_missing_fields clears it on a keystroke for the same reason,
		// and the stand-in is not an answer.
		if (!is_placeholder && field.$wrapper) field.$wrapper.removeClass("has-error");
	};

	// Nothing to work out without a region name. The stand-in is what the
	// server would answer, so the trip is skipped rather than made.
	if (!has_state) {
		return apply(no_state_code);
	}

	return frappe
		.xcall("taxjar_integration.taxjar_integration.taxjar_integration.resolve_region_code", {
			country: taxjar_integration._dialog_country(d),
			state: d.get_value("state"),
		})
		.then((answer) => {
			if (lookup !== d.__taxjar_region_lookup) return;
			// A code the reader typed while the lookup ran is their answer.
			if ((d.get_value("taxjar_region_code") || "").trim() !== current) return;
			apply((answer && answer.region_code) || unknown);
		});
};

// The fields of an address dialog: one banner, then each group of boxes in a
// section of its own.
//
// No Column Break. A Column Break draws a fixed grid, and a box the country
// hides leaves its cell empty - the boxes after it stay where they are, so a
// hole opens where the hidden box was. Every box in a group goes into one
// column instead, and _inject_destination_address_styles lays that column out
// as a two-column grid. A grid packs only the boxes that are shown, so the next
// box moves up into the space a hidden one leaves.
//
// A group is a run of boxes that belongs together. The last group starts a new
// row whatever the group above it ended on, which is how the two
// preferred-address checkboxes stay side by side under the address itself.
//
// Two dialogs build their boxes this way: the one that completes an address the
// document already names, and the one that creates the customer's first.
taxjar_integration._address_dialog_fields = function (banner, groups) {
	const fields = [
		{
			fieldtype: "HTML",
			fieldname: "why",
			options: taxjar_integration.requirements_banner(banner),
		},
	];

	groups.forEach((boxes) => {
		if (!boxes.length) return;
		// hide_border keeps the groups apart without drawing a line between
		// them.
		fields.push({
			fieldtype: "Section Break",
			hide_border: 1,
			css_class: TAXJAR_ADDRESS_GRID_CLASS,
		});
		fields.push(...boxes);
	});

	return fields;
};

taxjar_integration._show_destination_address_dialog = function (frm, row, missing) {
	taxjar_integration._inject_requirements_banner_styles();
	taxjar_integration._inject_destination_address_styles();

	// Every one of the five carries the star, whether it is filled or not,
	// because every one of them is genuinely required. Three are mandatory on
	// the Address doctype and Continue saves the Address; the other two are
	// what TaxJar refuses a transaction without. A star only on the empty ones
	// would say the filled ones are optional, and clearing one would then be a
	// save the dialog appeared to allow.
	//
	// ``missing`` still says which are empty right now. That drives the red
	// outline and the focus - see _mark_missing_fields.
	// Declared ahead of the boxes, because two of them hand it to the region
	// recompute. A `const` on the line where the dialog is built is not readable
	// from anything that runs before that line.
	let d;

	const boxes = [
		{ fieldtype: "Data", fieldname: "address_line1", label: __("Address Line 1"), reqd: 1, default: row.address_line1 || "" },
		// An empty second line is one more box to read past in a dialog that
		// asks for what is missing. It is shown only where the Address already
		// carries one, so the reader can correct it.
		...(row.address_line2
			? [{ fieldtype: "Data", fieldname: "address_line2", label: __("Address Line 2"), default: row.address_line2 }]
			: []),
		{ fieldtype: "Data", fieldname: "city", label: __("City"), reqd: 1, default: row.city || "" },
		{ fieldtype: "Data", fieldname: "state", label: __("State / Province"), reqd: 1, default: row.state || "",
			onchange: () => taxjar_integration._refresh_dialog_region(d) },
		{ fieldtype: "Data", fieldname: "pincode", label: __("Postal Code"), reqd: 1, default: row.pincode || "" },
		// Not starred. It always carries a value, the stand-in included, so
		// there is nothing for a star to ask for - but the reader can still
		// correct it here.
		{
			fieldtype: "Data",
			fieldname: "taxjar_region_code",
			label: __("Region Code (ISO 3166-2)"),
			default: row.region_code || "",
			// A United States sale is filed under taxjar_state_code on the
			// Address, which this dialog does not collect. Asking for a region
			// code there offers a box nothing reads.
			depends_on: 'eval:doc.country !== "United States"',
			description: taxjar_integration._region_code_hint(
				row.region_placeholder,
				!!(row.state || "").trim()
			),
		},
		{ fieldtype: "Link", fieldname: "country", label: __("Country"), options: "Country", reqd: 1, default: row.country || "",
			onchange: () => taxjar_integration._refresh_dialog_region(d) },
	];

	const fields = taxjar_integration._address_dialog_fields(
		__("Please fill the missing address details."),
		[boxes]
	);

	d = new frappe.ui.Dialog({
		title: __("Complete the Shipping Address"),
		fields,
		primary_action_label: __("Continue"),
		primary_action(values) {
			return frappe
				.xcall(
					"taxjar_integration.taxjar_integration.taxjar_integration.update_destination_address",
					{ address: row.name, values: JSON.stringify(values) }
				)
				.then(() => {
					d.hide();
					// The picker dialog ends the same way: fix the thing that
					// blocked the save, then make the save again.
					frm.save();
				});
		},
	});

	// What this dialog put in the region box. _refresh_dialog_region replaces
	// its own answer and leaves the reader's alone, and this is the first one.
	d.__taxjar_region_code = row.region_code || "";

	d.$wrapper.addClass(TAXJAR_ADDRESS_DIALOG_CLASS);
	d.show();
	taxjar_integration._mark_missing_fields(d, missing, row);
};

const TAXJAR_ADDRESS_DIALOG_CLASS = "taxjar-address-dialog";
const TAXJAR_ADDRESS_GRID_CLASS = "taxjar-address-grid";

// The two-column layout of an address dialog, drawn as a CSS grid rather than
// with Column Breaks - see _address_dialog_fields for why.
//
// A section break also carries its own spacing: --padding-sm above and below
// the section, and a 1rem top margin on a section body that starts the section
// (form.scss). Between the banner and the boxes that reads as a gap about twice
// the standard one, so it is zeroed here and each control's own bottom margin
// spaces the rows, the way it does for two boxes in one column.
taxjar_integration._inject_destination_address_styles = function () {
	if (document.getElementById("taxjar-address-dialog-styles")) return;
	const style = document.createElement("style");
	style.id = "taxjar-address-dialog-styles";
	style.textContent = `
		/* frappe gives the column the full width, and the boxes inside it are
		   laid out two to a row here. A box the country hides is display:none,
		   so it takes no cell and the next box moves up into its place. */
		.${TAXJAR_ADDRESS_GRID_CLASS} .form-column > form {
			display: grid;
			grid-template-columns: repeat(2, minmax(0, 1fr));
			/* Two col-sm-6 columns carry 15px of padding each, so 30px is the
			   gap the reader sees between two boxes on a standard form. */
			column-gap: 30px;
			/* A box with a sentence under it is taller than the box beside it.
			   Top alignment keeps the pair on one line rather than centring the
			   shorter one against the taller. */
			align-items: start;
		}
		.${TAXJAR_ADDRESS_DIALOG_CLASS} .form-section {
			padding-top: 0;
			padding-bottom: 0;
		}
		.${TAXJAR_ADDRESS_DIALOG_CLASS} .form-section > .section-body {
			margin-top: 0;
			padding-top: 0;
		}
		/* frappe gives the last box in a column 0.5rem where every box above it
		   gets 1rem. The last box of a group is not the last box of the dialog,
		   so it keeps the standard gap. */
		.${TAXJAR_ADDRESS_DIALOG_CLASS} .form-section .frappe-control:last-child {
			margin-bottom: 1rem;
		}
		.${TAXJAR_ADDRESS_DIALOG_CLASS} .form-section:last-child .frappe-control:last-child {
			margin-bottom: 0.5rem;
		}
		/* The banner sits in a section of its own, so that same 1rem is the gap
		   below it. Its own margin would add to it. */
		.${TAXJAR_ADDRESS_DIALOG_CLASS} .taxjar-requirements-banner {
			margin-bottom: 0;
		}
	`;
	document.head.appendChild(style);
};

// Red on the boxes that are empty, so the eye lands on them rather than reading
// six filled fields to find the two that are not. frappe paints .has-error on a
// mandatory field only once a save has been refused, which has not happened to
// this dialog yet.
taxjar_integration._mark_missing_fields = function (d, missing, row) {
	const wanted = missing.slice();
	if (row.region_placeholder) wanted.push("taxjar_region_code");

	wanted.forEach((fieldname) => {
		const field = d.fields_dict[fieldname];
		if (!field || !field.$wrapper) return;
		field.$wrapper.addClass("has-error");
		field.$input && field.$input.one("input", () => field.$wrapper.removeClass("has-error"));
	});

	const first = d.fields_dict[wanted[0]];
	first && first.$input && first.$input.focus();
};

// A foreign Sales Taxes and Charges row (a handling fee, a manual
// "Loyalty Discount" row, etc - anything that isn't our own tax row or the
// configured shipping row) is otherwise invisible to TaxJar. This gates
// save with a dialog showing exactly how each one will be treated, built
// from the same classifier get_tax_data() itself uses server-side (design
// doc §5) - what the dialog shows is guaranteed to match what gets sent.
taxjar_integration.confirm_foreign_tax_rows = function (frm) {
	// The server answers empty for a company out of scope, so this used to be a
	// round trip on every save of every transaction on the site to be told there
	// was nothing to say.
	return taxjar_integration.when_scoped(
		frm,
		(scope) => scope.uses_taxjar,
		() => taxjar_integration._confirm_foreign_tax_rows(frm)
	);
};

taxjar_integration._confirm_foreign_tax_rows = function (frm) {
	return frappe
		.xcall("taxjar_integration.taxjar_integration.taxjar_integration.preview_foreign_tax_rows", {
			doc_json: JSON.stringify(frm.doc),
		})
		.then(function (result) {
			let rows = (result && result.foreign_rows) || [];
			if (!rows.length) {
				return;
			}

			// Only re-prompt when the foreign-row set has actually changed
			// since the last "Proceed" - otherwise every unrelated resave of
			// a draft carrying a foreign row would re-block on this dialog.
			let ack_hash = taxjar_integration._hash_foreign_rows(rows);
			if (frm._taxjar_foreign_rows_ack === ack_hash) {
				return;
			}

			return new Promise(function (resolve) {
				taxjar_integration._show_foreign_tax_rows_dialog(frm, rows, ack_hash, resolve);
			});
		});
};

taxjar_integration._hash_foreign_rows = function (rows) {
	// affected_item_count is part of the fingerprint too - a negative row is
	// spread across the items, so a changed item set changes what it does,
	// even if the row's own account_head/amount/treatment stay the same.
	return JSON.stringify(
		rows.map((row) => [row.account_head, row.amount, row.treatment, row.affected_item_count])
	);
};

taxjar_integration._show_foreign_tax_rows_dialog = function (frm, rows, ack_hash, resolve) {
	let resolved = false;
	let settle = function (proceed) {
		if (resolved) return;
		resolved = true;
		taxjar_integration.track("taxjar_extra_charges_answered", {
			choice: proceed ? "proceed" : "cancel",
		});
		if (!proceed) frappe.validated = false;
		resolve();
	};

	// The Type column says which way the row moves the taxable value, with an
	// arrow and a color, and the Impact column says how TaxJar is sent it. The
	// row's own description is on the Sales Taxes and Charges row already.
	let taxable = (row) => row.treatment === "taxable_line_item";

	let type_badge = (row) =>
		taxable(row)
			? frappe.ui.badge.html({
					label: __("Increases Taxable Value"),
					icon: "arrow-up",
					theme: "blue",
					size: "sm",
			  })
			: frappe.ui.badge.html({
					label: __("Decreases Taxable Value"),
					icon: "arrow-down",
					theme: "amber",
					size: "sm",
			  });

	let impact = (row) =>
		taxable(row)
			? __("Additional line item is added & taxed.")
			: __("Discount is applied to each line item proportionally.");

	let table_rows = rows
		.map(
			(row) => `<tr>
				<td>${frappe.utils.escape_html(row.account_head)}</td>
				<td class="text-right text-nowrap">${format_currency(row.amount, frm.doc.currency)}</td>
				<td class="text-nowrap">${type_badge(row)}</td>
				<td class="text-muted">${impact(row)}</td>
			</tr>`
		)
		.join("");

	let html = `
		<p class="text-muted">${__("Additional rows have been added to Sales Taxes & Charges, please review.")}</p>
		<div style="max-height:300px;overflow-y:auto;margin-top:10px">
			<table class="table">
				<thead>
					<tr>
						<th>${__("Ledger")}</th>
						<th class="text-right">${__("Amount")}</th>
						<th>${__("Type")}</th>
						<th>${__("Impact")}</th>
					</tr>
				</thead>
				<tbody>${table_rows}</tbody>
			</table>
		</div>
	`;

	let d = new frappe.ui.Dialog({
		title: __("Confirm Tax Treatment for Extra Charges"),
		// Wide enough that the Type badge stays on one line beside the ledger.
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "foreign_rows_table", options: html }],
		primary_action_label: __("Proceed"),
		primary_action() {
			frm._taxjar_foreign_rows_ack = ack_hash;
			// Settle before hide: hide() runs on_hide, which settles as Cancel
			// and so stops the save that Proceed must let through.
			settle(true);
			d.hide();
		},
		secondary_action_label: __("Cancel"),
		secondary_action() {
			d.hide();
			settle(false);
		},
		on_hide() {
			// Dismissed via Escape/backdrop click, not a button - treat like
			// Cancel rather than silently letting the save through.
			settle(false);
		},
	});
	d.show();
};

// The `input[type="radio"]` element already gets frappe's own filled-circle
// treatment (frappe/public/scss/element/radio.scss) - no need to re-skin it.
// What the plain <table> didn't have was any row-level affordance, so the
// dot was the only thing on the row that looked clickable even though the
// whole `<tr>` already carries the click handler below. Reusing the
// --bg-blue "lit" treatment from .taxjar-address-lit (render_addresses,
// above) instead of inventing a new selected-state color.
taxjar_integration._inject_address_picker_styles = function () {
	if (document.getElementById("taxjar-address-picker-styles")) return;
	const style = document.createElement("style");
	style.id = "taxjar-address-picker-styles";
	style.textContent = `
		.taxjar-address-table thead th {
			background-color: var(--subtle-fg);
		}
		.taxjar-address-table .taxjar-address-row:hover {
			background-color: var(--subtle-fg);
		}
		.taxjar-address-table .taxjar-address-row-selected,
		.taxjar-address-table .taxjar-address-row-selected:hover {
			background-color: var(--bg-blue);
		}
		.taxjar-address-table .taxjar-address-radio-cell {
			width: 36px;
			text-align: center;
			vertical-align: middle;
		}
		.taxjar-address-table .taxjar-address-radio-cell input[type="radio"] {
			margin: 0 !important;
		}
	`;
	document.head.appendChild(style);
};

taxjar_integration.show_address_picker_dialog = function (frm, addresses) {
	let selected = null;
	// Nothing to compare against with one address, and an all-blank column
	// is just noise - only show it once it's actually telling the user
	// something (at least one Yes to weigh against the others).
	let show_preferred_col = addresses.length > 1 && addresses.some((addr) => addr.is_shipping_address);

	let table_rows = addresses
		.map((addr, idx) => {
			let addr_parts = [addr.address_line1, addr.city, addr.state, addr.pincode]
				.filter(Boolean)
				.join(", ");
			let checked = idx === 0 ? "checked" : "";
			if (idx === 0) selected = addr.name;

			return `<tr data-address="${frappe.utils.escape_html(addr.name)}"
					class="taxjar-address-row ${idx === 0 ? "taxjar-address-row-selected" : ""}">
				<td class="taxjar-address-radio-cell">
					<input type="radio" name="taxjar_addr" value="${frappe.utils.escape_html(addr.name)}" ${checked}>
				</td>
				<td>${frappe.utils.escape_html(addr.address_title || addr.name)}</td>
				<td>${frappe.utils.escape_html(addr_parts)}</td>
				<td>${frappe.utils.escape_html(addr.address_type || "")}</td>
				${
					show_preferred_col
						? `<td style="text-align:center">
					${addr.is_shipping_address ? frappe.ui.badge.html({ label: "Yes", theme: "green", size: "sm" }) : ""}
				</td>`
						: ""
				}
			</tr>`;
		})
		.join("");

	let html = `
		<p class="text-muted">${__("A shipping address is required for sales tax calculation. Select an existing address or add a new one.")}</p>
		<div style="max-height:300px;overflow-y:auto;margin-top:10px">
			<table class="table table-hover taxjar-address-table">
				<thead>
					<tr>
						<th style="width:36px"></th>
						<th>${__("Title")}</th>
						<th>${__("Address")}</th>
						<th>${__("Type")}</th>
						${show_preferred_col ? `<th style="text-align:center">${__("Preferred Shipping")}</th>` : ""}
					</tr>
				</thead>
				<tbody>${table_rows}</tbody>
			</table>
		</div>
	`;

	taxjar_integration._inject_address_picker_styles();

	let d = new frappe.ui.Dialog({
		title: __("Select Shipping Address"),
		fields: [
			{ fieldtype: "HTML", fieldname: "address_table", options: html },
			{
				fieldtype: "Check",
				fieldname: "mark_as_shipping",
				label: __("Use this address as shipping address for future transactions"),
				default: 0,
			},
		],
		primary_action_label: __("Use Selected"),
		primary_action() {
			if (!selected) {
				frappe.show_alert({ message: __("Please select an address"), indicator: "orange" });
				return;
			}

			// Returning the promise lets the dialog disable/spin its button
			// while set_value's own triggers run.
			return frm.set_value("shipping_address_name", selected).then(function () {
				if (d.get_value("mark_as_shipping")) {
					frappe.xcall(
						"taxjar_integration.taxjar_integration.taxjar_integration.mark_address_as_shipping",
						{ address_name: selected }
					);
				}

				d.hide();
				frm.save();
			});
		},
		secondary_action_label: __("Add New Address"),
		secondary_action() {
			d.hide();
			// Same ending as Use Selected above: the new address goes on the
			// document, and the save the picker blocked is made again.
			taxjar_integration._open_new_address(frm, { save_after: true });
		},
	});

	d.$wrapper.on("click", "tr[data-address]", function () {
		let addr_name = $(this).data("address");
		d.$wrapper
			.find('input[name="taxjar_addr"][value="' + addr_name + '"]')
			.prop("checked", true)
			.trigger("change");
	});

	d.$wrapper.on("change", 'input[name="taxjar_addr"]', function () {
		selected = $(this).val();
		d.$wrapper.find("tr[data-address]").removeClass("taxjar-address-row-selected");
		$(this).closest("tr").addClass("taxjar-address-row-selected");
	});

	d.show();
};

// ── Credit note reference ──
//
// A credit note a filing company raises has to name the invoice it reverses.
// validate_return_against refuses the save without it, because TaxJar files the
// refund against that invoice's transaction id.
//
// That refusal arrives after the user has filled the form in, and tells them to
// start again from Sales Invoice → Create → Return / Credit Note. This asks for
// the reference the moment the user says the document is a return, and then
// takes that same route for them.

taxjar_integration.prompt_for_return_reference = function (frm) {
	if (!frm.doc.is_return) return;
	if (frm.doc.docstatus !== 0) return;

	// A document the Return / Credit Note mapper built arrives with both fields
	// already set, so there is nothing left to ask it.
	if (frm.doc.return_against) return;

	// One dialog at a time. Ticking the box twice in quick succession would
	// otherwise stack two, and the second one's cancel would undo the first
	// one's choice.
	if (frm._taxjar_return_prompt_open) return;

	// Claimed here, before the scope lookup, rather than where the dialog is
	// built. The lookup is asynchronous - the first tick on a form waits for
	// get_company_scope to answer - so a claim made after it leaves the guard
	// above reading false for every tick that arrives while it runs, and two
	// dialogs open after all.
	frm._taxjar_return_prompt_open = true;

	// `files`, not `uses_taxjar`: this is the rule validate_return_against
	// itself applies. A company that only calculates tax never needs the
	// reference, so asking for it would collect an answer nothing reads.
	return taxjar_integration
		.when_scoped(
			frm,
			(scope) => scope.files,
			() => taxjar_integration._prompt_for_return_reference(frm)
		)
		.then(
			(dialog) => {
				// No dialog opened, so no on_hide will ever release the claim.
				// A claim left standing would refuse every later tick for the
				// life of the form - including the ticks on a company the user
				// then changes to one TaxJar files for.
				if (!dialog) taxjar_integration.release_return_prompt(frm);
				return dialog;
			},
			(error) => {
				taxjar_integration.release_return_prompt(frm);
				throw error;
			}
		);
};

// One name for "this form is no longer asking", so the dialogs and the paths
// that open none release the claim the same way.
taxjar_integration.release_return_prompt = function (frm) {
	frm._taxjar_return_prompt_open = false;
};

// Returns the dialog it opened. prompt_for_return_reference reads that to tell
// an open dialog from a path that opened none.
taxjar_integration._prompt_for_return_reference = function (frm) {
	// With no customer on the form the list covers the whole company, which is
	// worth opening the picker for. With one, an empty list is a dead end the
	// picker cannot show a way out of, so it is asked about first.
	if (!frm.doc.customer) {
		return taxjar_integration.show_return_reference_dialog(frm);
	}

	return frappe.db
		.count("Sales Invoice", {
			filters: taxjar_integration.return_reference_filters(frm, frm.doc.customer),
			limit: 1,
		})
		.then((count) => {
			if (count) {
				return taxjar_integration.show_return_reference_dialog(frm);
			}
			return taxjar_integration.show_no_returnable_invoice_dialog(frm);
		})
		// The count decides which dialog to open, not whether to open one. A
		// failed read opens the picker, where the link field asks the server
		// the same question again.
		.catch(() => taxjar_integration.show_return_reference_dialog(frm));
};

// Submitted, and not itself a return: TaxJar files the refund against an order
// it already holds, and a draft was never sent to it. The company keeps one
// company's invoices out of another company's credit note.
taxjar_integration.return_reference_filters = function (frm, customer) {
	const filters = { docstatus: 1, is_return: 0, company: frm.doc.company };
	if (customer) filters.customer = customer;
	return filters;
};

// Most sites name a Customer by series, so a link field shows CUST-0003 where
// the reader expects a name. The name is already on the transaction, so the
// dialog says both and the reader never has to recognise an id.
taxjar_integration.customer_label = function (frm) {
	const customer = frm.doc.customer;
	if (!customer) return "";

	const customer_name = frm.doc.customer_name;
	if (!customer_name || customer_name === customer) return customer;

	return `${customer_name} (${customer})`;
};

// The form's own customer whenever it has one: the dialog shows that as a label
// there, not as a value a field can be read for. Only where the form names
// nobody does the dialog's own link field hold the answer.
taxjar_integration.return_reference_customer = function (frm, d) {
	if (frm.doc.customer) return frm.doc.customer;
	return d ? d.get_value("customer") : "";
};

taxjar_integration.show_return_reference_dialog = function (frm) {
	taxjar_integration._inject_requirements_banner_styles();
	taxjar_integration._inject_return_reference_styles();

	const customer_on_form = Boolean(frm.doc.customer);
	let chosen = false;

	// Declared before the field definitions below, which close over it. A
	// control can fire its own onchange while the Dialog constructor is still
	// running, which is before the constructor has returned anything to assign.
	let d = null;

	// First, because it is the reason the dialog opened at all. The two fields
	// below are what the reader does about it.
	const fields = [
		{
			fieldtype: "HTML",
			fieldname: "taxjar_return_requirements",
			options: taxjar_integration.requirements_banner(
				__("Original sales invoice must be referenced for credit note.")
			),
		},
	];

	// A label, not a link, where the form has already decided the customer:
	// changing it here would pick an invoice for a customer the credit note is
	// not for, and a link field would show the id where a name reads better.
	fields.push(
		customer_on_form
			? {
					fieldtype: "Data",
					fieldname: "customer_display",
					label: __("Customer"),
					default: taxjar_integration.customer_label(frm),
					read_only: 1,
			  }
			: {
					fieldtype: "Link",
					fieldname: "customer",
					label: __("Customer"),
					options: "Customer",
					onchange() {
						if (!d) return;
						// The invoice belonged to the previous customer, so it
						// cannot stand once that changes.
						d.set_value("return_against", "");
					},
			  },
		{
			fieldtype: "Link",
			fieldname: "return_against",
			label: __("Sales Invoice"),
			options: "Sales Invoice",
			reqd: 1,
			get_query: () => ({
				filters: taxjar_integration.return_reference_filters(
					frm,
					taxjar_integration.return_reference_customer(frm, d)
				),
			}),
			onchange() {
				if (!d) return;
				taxjar_integration.render_return_invoice_preview(d);
			},
		},
		{ fieldtype: "HTML", fieldname: "taxjar_return_preview" }
	);

	d = new frappe.ui.Dialog({
		title: __("Credit Note Against Invoice"),
		fields,
		// A dialog focuses its first input as it opens (FieldGroup's
		// focus_on_first_input), and a focused Link control drops its whole
		// list open. The dialog then arrived with a list of every customer
		// over it, hiding its own title. frappe's assign-to dialog turns the
		// focus off the same way, for the same reason.
		no_focus: true,
		primary_action_label: __("Continue"),
		primary_action() {
			const invoice_name = d.get_value("return_against");
			if (!invoice_name) {
				frappe.show_alert({
					message: __("Please select a Sales Invoice"),
					indicator: "orange",
				});
				return;
			}

			// Read live rather than off the preview above. The preview's own
			// read can still be in flight when this is clicked, and its answer
			// is a moment old either way - the sync runs in a background job,
			// so a Queued invoice can become Synced while the dialog is open.
			//
			// Returning the promise lets the dialog disable its button while
			// the read runs, the same way the address picker does.
			return taxjar_integration.invoice_is_synced(invoice_name).then((synced) => {
				if (!synced) {
					taxjar_integration.show_invoice_not_synced_message();
					return;
				}

				chosen = true;
				d.hide();
				return taxjar_integration.open_return_credit_note(frm, invoice_name);
			});
		},
		secondary_action_label: __("Cancel"),
		secondary_action() {
			d.hide();
		},
		on_hide() {
			// Escape and the backdrop reach here too, and they mean the same
			// thing the Cancel button means.
			if (!chosen) taxjar_integration.cancel_return_reference(frm);
			taxjar_integration.release_return_prompt(frm);
		},
	});

	d.show();
	return d;
};

// The customer has nothing this credit note can reverse, so the dialog offers
// the one move that is left. A picker here would open on an empty list and say
// nothing about why. The same banner as the picker states the rule, and the
// line under it links the customer, where the reader goes to find the invoice.
taxjar_integration.show_no_returnable_invoice_dialog = function (frm) {
	taxjar_integration._inject_requirements_banner_styles();

	const customer_link = frappe.utils.get_form_link(
		"Customer",
		frm.doc.customer,
		true,
		frappe.utils.escape_html(taxjar_integration.customer_label(frm))
	);

	const d = new frappe.ui.Dialog({
		title: __("Credit Note Against Invoice"),
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "taxjar_return_requirements",
				options: taxjar_integration.requirements_banner(
					__("Original sales invoice must be referenced for credit note.")
				),
			},
			{
				fieldtype: "HTML",
				fieldname: "taxjar_no_invoice",
				// Space above sets the text apart from the banner. The bold line
				// says what is wrong, and the line under it says what to do.
				options: `<p class="mt-3 font-weight-bold">${__("{0} has no submitted invoice.", [
					customer_link,
				])}</p>
				<p>${__(
					"Please submit a sales invoice against the customer to generate a credit note."
				)}</p>`,
			},
		],
		primary_action_label: __("Cancel"),
		primary_action() {
			d.hide();
		},
		on_hide() {
			taxjar_integration.cancel_return_reference(frm);
			taxjar_integration.release_return_prompt(frm);
		},
	});

	d.show();
	return d;
};

// What the user is about to reverse, read from the invoice itself rather than
// guessed from its name. The sync status is here because a credit note against
// an invoice TaxJar never received has nothing to file against.
// The same pill the invoice's own sidebar shows, off the same colour map, so a
// status does not read green in one place and grey in another.
//
// Only the submitted states: the picker offers submitted invoices and nothing
// else, so the sidebar's draft and cancelled wording has nothing to describe
// here. An invoice with no status at all was submitted before this app watched
// it - "Excluded" would claim a decision nobody made, so it says what is true.
taxjar_integration.sync_status_badge_html = function (status) {
	if (!status) {
		return frappe.ui.badge.html({ label: __("Not synced"), theme: "gray", size: "sm" });
	}

	return frappe.ui.badge.html({
		label: __(status),
		theme: taxjar_integration.SYNC_STATUS_COLORS[status] || "gray",
		size: "sm",
	});
};

taxjar_integration.render_return_invoice_preview = function (d) {
	const invoice_name = d.get_value("return_against");
	const $wrapper = d.fields_dict.taxjar_return_preview.$wrapper;

	if (!invoice_name) {
		$wrapper.empty();
		return;
	}

	return frappe.db
		.get_value("Sales Invoice", invoice_name, [
			"posting_date",
			"currency",
			"grand_total",
			"total_taxes_and_charges",
			"taxjar_sync_status",
		])
		.then((result) => {
			// A second pick can land while this read is in flight. The field is
			// the record of what the user chose last, so it decides.
			if (d.get_value("return_against") !== invoice_name) return;

			const row = (result && result.message) || {};

			// Every value but the last is text this escapes; the status is a
			// pill, which is markup this builds itself. Escaping that would
			// print the tags, so the value carries its own HTML and the plain
			// ones are escaped as they are put in.
			const text = (value) =>
				frappe.utils.escape_html(value === undefined || value === null ? "" : value);

			const rows = [
				[__("Posting Date"), text(frappe.datetime.str_to_user(row.posting_date))],
				[__("Grand Total"), text(format_currency(row.grand_total, row.currency))],
				[__("Sales Tax"), text(format_currency(row.total_taxes_and_charges, row.currency))],
				[__("Sync Status"), taxjar_integration.sync_status_badge_html(row.taxjar_sync_status)],
			];

			$wrapper.html(`<div class="taxjar-return-preview">
				${rows
					.map(
						([label, value]) => `<div class="taxjar-return-preview-row">
							<span class="text-muted">${label}</span>
							<span>${value}</span>
						</div>`
					)
					.join("")}
			</div>`);
		});
};

// Synced, and nothing else. TaxJar files the refund against a transaction it
// already holds, so it has nothing to file against an invoice it never
// received - Queued, Failed and Excluded all leave it with nothing.
taxjar_integration.invoice_is_synced = function (invoice_name) {
	return frappe.db
		.get_value("Sales Invoice", invoice_name, "taxjar_sync_status")
		.then((result) => {
			const row = (result && result.message) || {};
			return row.taxjar_sync_status === "Synced";
		});
};

// The picker stays open behind this, so the reader picks another invoice
// rather than starting the credit note again. Is Return stays ticked for the
// same reason: nothing has been decided yet.
taxjar_integration.show_invoice_not_synced_message = function () {
	frappe.msgprint({
		title: __("Original Invoice Not Synced"),
		message: __(
			"Original sales invoice isn't synced to TaxJar, so credit note can't be created against it."
		),
		indicator: "red",
	});
};

// The box is what opened the dialog, so dismissing the dialog puts it back.
// Leaving it ticked would leave a draft that validate_return_against refuses to
// save, with no way to reach this dialog again.
taxjar_integration.cancel_return_reference = function (frm) {
	return frm.set_value("is_return", 0);
};

taxjar_integration.open_return_credit_note = function (frm, invoice_name) {
	// This draft is left behind, so it must not be left in the state that
	// cannot be saved. Untick first, then route: the mapper builds its own
	// document and this one is never written.
	return Promise.resolve(frm.set_value("is_return", 0)).then(() =>
		frappe.model.open_mapped_doc({
			method: "erpnext.accounts.doctype.sales_invoice.mapper.make_sales_return",
			source_name: invoice_name,
		})
	);
};

// Two dialogs open because TaxJar wants something the document does not carry
// yet. Both say so the same way, in the same yellow block, so the reader learns
// the shape once.
taxjar_integration.requirements_banner = function (message) {
	return `<div class="taxjar-requirements-banner">
		<div class="taxjar-requirements-banner-title">${__("TaxJar Requirements")}</div>
		<div>${message}</div>
	</div>`;
};

taxjar_integration._inject_requirements_banner_styles = function () {
	if (document.getElementById("taxjar-requirements-banner-styles")) return;
	const style = document.createElement("style");
	style.id = "taxjar-requirements-banner-styles";
	style.textContent = `
		/* What TaxJar requires, above the fields that satisfy it. */
		.taxjar-requirements-banner {
			background-color: var(--bg-yellow);
			border-radius: var(--radius);
			padding: 12px 14px;
			margin-bottom: 10px;
			font-size: var(--text-md);
		}
		.taxjar-requirements-banner-title {
			font-weight: 600;
			margin-bottom: 2px;
		}
	`;
	document.head.appendChild(style);
};

// Injected on first use, the same way the address picker's styles are: a block
// that exists only inside this dialog does not earn a place in the bundle every
// desk page loads.
taxjar_integration._inject_return_reference_styles = function () {
	if (document.getElementById("taxjar-return-reference-styles")) return;
	const style = document.createElement("style");
	style.id = "taxjar-return-reference-styles";
	style.textContent = `
		/* The card the rest of this app already draws (.taxjar-exemption-card in
		   the bundle's scss): the page's own card fill, one hairline, and the
		   8px corner --radius carries. --subtle-fg was the same grey the gray
		   status pill is filled with, so Excluded read as plain text on it. */
		.taxjar-return-preview {
			background-color: var(--card-bg);
			border: 1px solid var(--border-color);
			border-radius: var(--radius);
			padding: 12px 14px;
			font-size: var(--text-md);
		}
		.taxjar-return-preview-row {
			display: flex;
			align-items: center;
			justify-content: space-between;
			gap: 12px;
		}
		.taxjar-return-preview-row + .taxjar-return-preview-row {
			margin-top: 6px;
		}
	`;
	document.head.appendChild(style);
};


const TAXJAR_MESSAGE_CLASS = "taxjar-form-message";

// Layout.show_message() *appends*; it only clears the container when called
// with nothing at all (layout.js:132-164). refresh() runs more than once per
// form load, so routing every call straight through it stacked a fresh copy of
// the same strip each time.
//
// Clearing the container instead would take frappe's own messages with it -
// "Submit this document to confirm" lives there too - so only our own block is
// replaced: tagged on the way in, removed by that tag on the way out.
taxjar_integration._set_tax_message = function (frm, text, color) {
	const $container = frm.layout.message;
	$container.find(`.${TAXJAR_MESSAGE_CLASS}`).remove();

	if (!text) {
		// Someone else's message may still be in there; only hide the container
		// once it is genuinely empty.
		if (!$container.children().length) $container.addClass("hidden");
		return;
	}

	frm.layout.show_message(text, color);
	$container.children().last().addClass(TAXJAR_MESSAGE_CLASS);
};

taxjar_integration.show_no_address_tax_message = function (frm) {
	// Not on a half-written document - see party_details_are_updating.
	if (taxjar_integration.party_details_are_updating(frm)) return;

	// Nothing here is true of a document TaxJar will not price: no address is
	// missing "hence taxes are not calculated", and no destination lacks nexus.
	return taxjar_integration.when_scoped(
		frm,
		(scope) => scope.calculates,
		() => taxjar_integration._show_tax_message(frm)
	);
};

taxjar_integration._show_tax_message = function (frm) {
	if (!(frm.doc.shipping_address_name || frm.doc.customer_address)) {
		let party_name = frm.doc.party_name || frm.doc.customer;
		if (party_name) {
			taxjar_integration._set_tax_message(
				frm,
				__('Customer address is not set, hence taxes are not calculated. <a href="#" class="taxjar-create-address-link">{0} \u2192</a>', [
					__("Create Address"),
				]),
				"orange"
			);
			// The link's target (a prefilled, linked-to-this-customer Address
			// form) only exists as a client-side frappe.new_doc() call, not a
			// real URL - reuse the exact same helper the shipping-address
			// picker's own "Add New Address" action already calls, so both
			// entry points prefill identically.
			frm.layout.message.find(".taxjar-create-address-link").on("click", function (e) {
				e.preventDefault();
				taxjar_integration._open_new_address(frm);
			});
			return;
		}
	}

	// An export is answered first and on its own. The saved reason names the
	// country correctly, but the strip it is painted into ends in "Manage Nexus
	// in TaxJar", and nexus is a registration with a United States state - no
	// amount of it makes a sale to Mumbai taxable, so the link would send the
	// reader somewhere that cannot change the outcome.
	const address = frm.doc.shipping_address_name || frm.doc.customer_address;

	return taxjar_integration.export_destination(address, frm.doc.company).then((export_to) => {
		// The pick can change while this is in flight, and a stale answer names
		// the wrong country - the same guard the nexus check below applies.
		if ((frm.doc.shipping_address_name || frm.doc.customer_address) !== address) return;

		if (export_to) {
			taxjar_integration._show_outside_coverage_message(frm);
			return;
		}

		// Paint what the document itself says first...
		if (frm.doc.taxjar_nexus_reason && !frm.doc.taxjar_has_nexus) {
			taxjar_integration._show_no_nexus_message(frm, frm.doc.taxjar_nexus_reason);
		} else {
			taxjar_integration._set_tax_message(frm, "");
		}

		// ...then correct it from the address actually on the form, which on an
		// edited document is not the one the saved answer was about. A no-op
		// unless there is unsaved input.
		taxjar_integration._check_nexus_for_selected_address(frm);
	});
};

// Same strip, same colour, one sentence and no link: the reader is not missing
// a registration, the sale is simply outside what TaxJar prices. The country is
// escaped because it is rendered as HTML.
taxjar_integration._show_outside_coverage_message = function (frm) {
	// One sentence for both, and no country in it. Whether the export is filed
	// changes nothing about the tax: a sale delivered outside the United States
	// carries none either way, and naming the country only repeated what the
	// address above already says. The same words the server stores on the
	// document - see EXPORT_NO_TAX_REASON in taxjar_integration.py.
	taxjar_integration._set_tax_message(
		frm,
		__("Sales taxes are not applicable on export transactions."),
		"yellow"
	);
};

// Yellow, not blue: no tax on a sale is a caveat about the outcome, not a note
// about how the form works, and the blue read as the latter - the same shade
// frappe's own "Submit this document to confirm" hint uses, directly above it.
//
// Nexus is registered with the tax authority and declared in TaxJar, never
// here, so the strip ends in the one link that can actually resolve it rather
// than leaving the reader to work out where to go.
taxjar_integration._show_no_nexus_message = function (frm, reason) {
	taxjar_integration._set_tax_message(
		frm,
		__("{0}, hence no taxes are charged.", [reason]) +
			` <a href="${taxjar_integration.TAXJAR_NEXUS_URL}" target="_blank" rel="noopener noreferrer">` +
			`${__("Manage Nexus in TaxJar")} \u2192</a>`,
		"yellow"
	);
};

// The nexus gap used to surface as a modal on picking an address, which
// interrupts to report something that changes nothing about what the user can
// do next - and only after a save had already been attempted. It is the same
// fact the saved document states in its own strip, so it says it the same way,
// before the first save.
//
// Only while the form holds unsaved input: once saved, taxjar_nexus_reason is
// the server's own answer for this exact document and is handled above, so
// re-asking on every refresh would be a round trip per form load to be told
// what the document already says.
taxjar_integration._check_nexus_for_selected_address = function (frm) {
	if (!frm.is_new() && !frm.is_dirty()) return;

	// Ship-to decides nexus; the billing address is what a sale with no
	// separate shipping address is taxed against, so it stands in.
	const address = frm.doc.shipping_address_name || frm.doc.customer_address;
	if (!address) return;

	// Nexus is registered per company, so it has to be asked per company - the
	// server scopes the lookup the same way, and used to be handed a question
	// that could only be answered site-wide.
	frappe
		.xcall("taxjar_integration.taxjar_integration.taxjar_integration.check_nexus", {
			shipping_address_name: address,
			company: frm.doc.company,
		})
		.then((missing) => {
			// The pick can change (or the form can be swapped out) while this
			// is in flight, and a stale answer names the wrong state.
			const current = frm.doc.shipping_address_name || frm.doc.customer_address;
			if (current !== address) return;

			if (missing && missing.outside_coverage) {
				// The endpoint answers the export case itself, so a caller that
				// reaches it without asking about the country first still gets
				// the export sentence rather than "Nexus not configured for
				// null".
				taxjar_integration._show_outside_coverage_message(frm);
			} else if (missing) {
				// The full state name, same as the reason the server stores
				// once the document is saved - a two-letter code has to be
				// decoded before the sentence means anything.
				taxjar_integration._show_no_nexus_message(
					frm,
					__("Nexus not configured for {0}", [
						taxjar_integration.region_full_name(
							missing.country_code,
							missing.state_code
						) || missing.state,
					])
				);
			} else {
				// There is nexus here, so whatever the last save concluded
				// about a different address no longer describes this one.
				taxjar_integration._set_tax_message(frm, "");
			}
		});
};

// The customer has no address, and the reader has to make one.
//
// This used to open the Address form, which is a page away from the
// transaction: the reader left the document, saved an address, came back, and
// linked it by hand - three steps to answer a strip that asked for one.
//
// A dialog on the document instead. It asks for what a sale is priced on: the
// three fields the Address doctype makes mandatory, the two more TaxJar refuses
// a transaction without, and the two flags that decide which address later
// transactions pick up on their own. The new address lands on the document
// itself, so the reader never leaves it.
//
// ``options.save_after`` re-makes a save this blocked. Two of the three callers
// are save-time prompts, and the picker beside them ends the same way.
taxjar_integration._open_new_address = function (frm, options) {
	const save_after = !!(options && options.save_after);
	const customer = frm.doc.party_name || frm.doc.customer;
	if (!customer) return;

	taxjar_integration._inject_requirements_banner_styles();
	taxjar_integration._inject_destination_address_styles();

	// Declared ahead of the boxes, because two of them hand it to the region
	// recompute. A `const` on the line where the dialog is built is not
	// readable from anything that runs before that line.
	let d;

	// Seven boxes carry the star, and a United States address carries an
	// eighth. Five are what the Address itself will not save without - the
	// title it is named after, the type, the street, the city and the country.
	// Two more are the state and the postcode, which TaxJar refuses a
	// transaction without: left blank here, _show_destination_address_dialog
	// asks for them again at the next save. The eighth is the state code, which
	// is what a United States sale is actually filed under.
	const boxes = [
		{
			fieldtype: "Data",
			fieldname: "address_title",
			label: __("Address Title"),
			reqd: 1,
			default: customer,
		},
		// Billing and Shipping, and no more. The Address doctype offers twelve
		// types, but a sales transaction reads these two, and the pair below
		// says which one later transactions pick up. A reader who wants one of
		// the other ten has the Address form.
		{
			fieldtype: "Select",
			fieldname: "address_type",
			label: __("Address Type"),
			reqd: 1,
			options: ["Billing", "Shipping"].join("\n"),
			default: "Shipping",
		},
		{ fieldtype: "Data", fieldname: "address_line1", label: __("Address Line 1"), reqd: 1 },
		{ fieldtype: "Data", fieldname: "address_line2", label: __("Address Line 2") },
		{ fieldtype: "Data", fieldname: "city", label: __("City"), reqd: 1 },
		{ fieldtype: "Data", fieldname: "state", label: __("State / Province"), reqd: 1,
			onchange: () => taxjar_integration._refresh_dialog_codes(d) },
		// One of the next two holds the region this sale is filed under, and
		// the country says which. A United States sale is filed under the state
		// code, and everywhere else under the ISO 3166-2 region code, so each
		// box shows only where it is read - the same pair, under the same rule,
		// as the Address form itself. Exactly one of them is on the screen at a
		// time, and the boxes below it move up to meet it.
		{
			fieldtype: "Select",
			fieldname: "taxjar_state_code",
			label: __("State Code (US)"),
			options: taxjar_integration.us_state_code_options(),
			depends_on: 'eval:doc.country === "United States"',
			mandatory_depends_on: 'eval:doc.country === "United States"',
			onchange: () => taxjar_integration._fill_dialog_state_from_code(d),
		},
		// Not starred, and worked out rather than typed - the same box
		// _show_destination_address_dialog offers, filled by the same helper as
		// the state and the country change.
		{
			fieldtype: "Data",
			fieldname: "taxjar_region_code",
			label: __("Region Code (ISO 3166-2)"),
			depends_on: 'eval:doc.country && doc.country !== "United States"',
		},
		{ fieldtype: "Data", fieldname: "pincode", label: __("Postal Code"), reqd: 1 },
		// The United States, because this app prices a United States sale -
		// every company it serves is registered there. A reader delivering
		// somewhere else changes one box; a reader delivering at home changes
		// none.
		{ fieldtype: "Link", fieldname: "country", label: __("Country"), options: "Country", reqd: 1,
			default: "United States",
			onchange: () => taxjar_integration._refresh_dialog_codes(d) },
	];

	// The two flags the Address form carries and its quick entry leaves out.
	// They decide which address a later transaction picks up on its own, and
	// the only other place to say so is the page this dialog exists to avoid.
	//
	// Their own group, so they sit side by side under the address whatever the
	// row above them ended on.
	//
	// Both start clear. This dialog is also reached from the picker, where the
	// customer already has addresses, and a ticked box there would demote one
	// of them without the reader deciding - the picker's own "use this for
	// future transactions" box starts clear for the same reason.
	const flags = [
		{
			fieldtype: "Check",
			fieldname: "is_primary_address",
			label: __("Preferred Billing Address"),
		},
		{
			fieldtype: "Check",
			fieldname: "is_shipping_address",
			label: __("Preferred Shipping Address"),
		},
	];

	d = new frappe.ui.Dialog({
		title: __("Create Address"),
		fields: taxjar_integration._address_dialog_fields(
			__("Please fill the address details as required for sales tax computation."),
			[boxes, flags]
		),
		primary_action_label: __("Create"),
		primary_action(values) {
			return frappe
				.xcall(
					"taxjar_integration.taxjar_integration.taxjar_integration.create_customer_address",
					{ customer, values: JSON.stringify(values) }
				)
				.then((answer) => {
					const address_name = answer && answer.name;
					if (!address_name) return;

					d.hide();
					return taxjar_integration._use_new_address(frm, address_name, save_after);
				});
		},
	});

	d.$wrapper.addClass(TAXJAR_ADDRESS_DIALOG_CLASS);
	d.show();

	// The country again, as a write this time. frappe judges every depends_on
	// while it builds the dialog, which is before a default reaches the box it
	// depends on - so the two code boxes above are judged against an empty
	// country and both start hidden. A write settles them, because set_value
	// judges them again once the value is in.
	d.set_value("country", "United States");
};

// The address the reader just built is the one this sale is delivered to, so
// the ship-to field takes it.
//
// The bill-to field takes it only while it is empty. A document that already
// names a billing address reached this dialog for a delivery address, and
// overwriting the billing address would answer a question nobody asked.
//
// One write at a time. Both fields run their own handlers - the exemption, the
// nexus strip and the sync pill all re-read the destination - and the ship-to
// write goes last so the last handler to run reads the field TaxJar prices on.
taxjar_integration._use_new_address = function (frm, address_name, save_after) {
	let chain = Promise.resolve();

	if (!frm.doc.customer_address) {
		chain = chain.then(() => frm.set_value("customer_address", address_name));
	}

	return chain
		.then(() => frm.set_value("shipping_address_name", address_name))
		.then(() => {
			frappe.show_alert(
				{ message: __("Address {0} created", [address_name]), indicator: "green" },
				5
			);

			// The picker ends the same way: fix what blocked the save, then
			// make the save again.
			if (save_after) frm.save();
		});
};

// ── TaxJar Tab: Status Cards & Addresses ──

// ── Region-scoped customer exemption ──
// A customer can be exempt in some states and not others. Where the master's
// exemption covers this sale's destination, the transaction override is set
// from the master and locked: it is not the user's call, and leaving it blank
// would suggest the sale is taxable when it is not.
//
// Destination follows the same ship-to-then-bill-to fallback the server uses,
// so this re-runs whenever either address changes.
taxjar_integration.apply_region_exemption = function (frm) {
	// Not on a half-written document - see party_details_are_updating. This one
	// writes to the document as well as reading it, so running it mid-write
	// would put a set_value of its own between erpnext's.
	if (taxjar_integration.party_details_are_updating(frm)) return;

	// Locking a transaction's exemption fields is a statement that TaxJar has
	// decided the matter. For a company it does not serve it has decided nothing,
	// and the fields should stay the user's own.
	return taxjar_integration.when_scoped(
		frm,
		(scope) => scope.uses_taxjar,
		() => taxjar_integration._apply_region_exemption(frm)
	);
};

taxjar_integration._apply_region_exemption = function (frm) {
	const fields = ["taxjar_transaction_exempt", "taxjar_transaction_exemption_type"];
	const customer = frm.doc.party_name || frm.doc.customer;
	const address = frm.doc.shipping_address_name || frm.doc.customer_address;

	const unlock = () => fields.forEach((f) => frm.set_df_property(f, "read_only", 0));

	if (!customer || !address) {
		unlock();
		return;
	}

	// Set and locked, whichever of the two reasons applies - the fields say the
	// same thing either way, and only one owner may write them.
	const apply = (exemption_type) => {
		fields.forEach((f) => frm.set_df_property(f, "read_only", 1));

		// Only written on a draft, and only when it would actually change
		// something - set_value on an unchanged field still marks the form
		// dirty, which would make merely opening a saved invoice look edited.
		if (frm.doc.docstatus !== 0) return;

		if (!cint(frm.doc.taxjar_transaction_exempt)) {
			frm.set_value("taxjar_transaction_exempt", 1);
		}
		if (frm.doc.taxjar_transaction_exemption_type !== exemption_type) {
			frm.set_value("taxjar_transaction_exemption_type", exemption_type);
		}
	};

	return frappe
		.xcall("taxjar_integration.taxjar_integration.taxjar_integration.get_region_exemption", {
			customer,
			address,
		})
		.then((exemption) => {
			if (exemption && exemption.exemption_type) {
				apply(exemption.exemption_type);
				return;
			}

			// No standing exemption on the customer. An export is exempt all
			// the same, and for a reason that belongs to the sale rather than
			// to the customer: TaxJar prices United States sales tax, and this
			// sale is delivered elsewhere. "Other" because TaxJar's own list
			// offers Wholesale, Government and Other, and an export is neither
			// of the first two.
			//
			// The customer's own exemption is asked first because TaxJar
			// applies that one itself, off the matched customer - see
			// _get_effective_exemption() in taxjar_integration.py.
			return taxjar_integration.export_destination(address, frm.doc.company).then((export_to) => {
				if (!export_to) {
					unlock();
					return;
				}
				apply(taxjar_integration.EXPORT_EXEMPTION_TYPE);
			});
		});
};

// True when the per-transaction override is both ticked and given a reason -
// the same test the server applies before it counts as real.
taxjar_integration._has_transaction_exemption = function (frm) {
	return Boolean(cint(frm.doc.taxjar_transaction_exempt) && frm.doc.taxjar_transaction_exemption_type);
};

// Nothing has been evaluated for this document, and why decides what to say. A
// new document simply has not been saved yet; a saved one with nothing on it
// means set_sales_tax never ran, and the commonest reason is that tax
// calculation is off for the company - where "after saving" sent the reader
// round a loop that could not end, since saving again would change nothing.
taxjar_integration._render_empty_status = function (frm, wrapper) {
	const after_saving = `<p class="text-muted">${__("Tax status will be available after saving.")}</p>`;

	if (frm.is_new() || !frm.doc.company) {
		wrapper.html(after_saving);
		return;
	}

	// Emptied rather than filled with a guess: the answer is one round trip
	// away, and a wrong message that corrects itself a moment later reads worse
	// than a blank that fills in.
	const docname = frm.doc.name;
	wrapper.empty();

	taxjar_integration
		.scope(frm.doc.company)
		.then((status) => {
			if (frm.doc.name !== docname || !status) return;

			const company = frappe.utils.escape_html(frm.doc.company);

			// TaxJar computes US sales tax, so a company registered anywhere
			// else has no tax status here and never will - said before the
			// calculation switch, which is the reason that would still be true
			// if the switch were on. No "Configure TaxJar" link either: the
			// setup page holds nothing that can resolve this, and the country
			// is changed on the Company, not in TaxJar.
			if (status.reason === "not_us") {
				const country = status.country && frappe.utils.escape_html(status.country);
				wrapper.html(`
					<p class="text-muted">
						${
							country
								? __(
										"{0} is based in {1}, and TaxJar only handles United States sales tax, so no TaxJar features apply to this document.",
										[company, country]
								  )
								: __(
										"{0} is not based in the United States, and TaxJar only handles United States sales tax, so no TaxJar features apply to this document.",
										[company]
								  )
						}
					</p>
				`);
				return;
			}

			if (!status.calculates) {
				wrapper.html(`
					<p class="text-muted">
						${__("Sales tax calculation is turned off for {0}, so there is no tax status to show.", [
							company,
						])}
						<a href="${TAXJAR_SETUP_FEATURES_URL}">${__("Configure TaxJar")} \u2192</a>
					</p>
				`);
				return;
			}

			wrapper.html(after_saving);
		});
};

taxjar_integration.render_status_cards = function (frm) {
	if (!frm.fields_dict.taxjar_status_html) return;
	const wrapper = frm.fields_dict.taxjar_status_html.$wrapper;

	if (!frm.doc.taxjar_nexus_reason && !frm.doc.taxjar_customer_taxable_reason) {
		taxjar_integration._render_empty_status(frm, wrapper);
		return;
	}

	const has_nexus = frm.doc.taxjar_has_nexus;
	// The customer master's own answer. A transaction override no longer flips
	// this to "No" - that would hide the fact that the customer is taxable and
	// only this one sale is not. The override is appended to the answer instead.
	const customer_taxable = frm.doc.taxjar_customer_taxable;
	const transaction_exempt = taxjar_integration._has_transaction_exemption(frm);

	const card1 = {
		question: __("Do you have a nexus here?"),
		answer: has_nexus ? __("Yes") : __("No"),
		color: has_nexus ? "green" : "red",
	};

	let card2, card3;

	const skipped = { answer: __("Skipped"), color: "gray" };

	if (!has_nexus && frm.doc.taxjar_nexus_reason) {
		// Nothing downstream is evaluated once there is no nexus.
		card2 = { question: __("Is the customer taxable?"), ...skipped };
		card3 = { question: __("Is the product taxable?"), ...skipped };
	} else {
		let answer = __("Yes");
		let color = "green";

		if (!customer_taxable) {
			answer = __("No");
			color = "red";
		} else if (transaction_exempt) {
			answer = __("Yes, but transaction is marked as exempt");
			color = "amber";
		}

		card2 = { question: __("Is the customer taxable?"), answer, color };

		// Product taxability is moot once the sale is exempt either way.
		if (!customer_taxable || transaction_exempt) {
			card3 = { question: __("Is the product taxable?"), ...skipped };
		} else {
			const prod = frm.doc.taxjar_product_taxable;
			let prod_color = "gray";
			let prod_answer = __("Skipped");
			if (prod === "Yes") { prod_color = "green"; prod_answer = __("Yes"); }
			else if (prod === "No") { prod_color = "red"; prod_answer = __("No"); }
			else if (prod === "Partially") { prod_color = "blue"; prod_answer = __("Partially"); }

			card3 = {
				question: __("Is the product taxable?"),
				answer: prod_answer,
				color: prod_color,
			};
		}
	}

	taxjar_integration._inject_status_card_styles();

	const cards = [card1, card2, card3];
	let html = '<div class="taxjar-status-cards">';
	cards.forEach((card, i) => {
		// frappe.ui.badge isn't built around a fixed height for one short
		// word the way indicator-pill is, so "Yes, but transaction is marked
		// as exempt" just wraps inside the card - no separate wrap-mode CSS
		// needed the way indicator-pill required.
		html += `
			<div class="taxjar-status-card">
				<div class="text-muted taxjar-status-card-q">${card.question}</div>
				<div class="taxjar-status-card-a">
					${frappe.ui.badge.html({ label: card.answer, theme: card.color })}
				</div>
			</div>
			${i < 2 ? '<div class="taxjar-status-arrow">→</div>' : ""}`;
	});
	html += "</div>";
	wrapper.html(html);
};

// Responsive layout for the status cards. On wide screens the three cards sit
// side by side with → connectors; on narrow screens they stack and the arrows
// rotate to point downward. Injected once.
taxjar_integration._inject_status_card_styles = function () {
	if (document.getElementById("taxjar-status-card-styles")) return;
	const style = document.createElement("style");
	style.id = "taxjar-status-card-styles";
	style.textContent = `
		.taxjar-status-cards {
			display: flex;
			gap: 12px;
			flex-wrap: wrap;
			align-items: stretch;
			margin-bottom: 16px;
		}
		.taxjar-status-card {
			flex: 1 1 200px;
			border: 1px solid var(--border-color);
			border-radius: var(--radius-lg);
			padding: 16px;
			background: var(--fg-color);
		}
		.taxjar-status-card-q {
			font-size: var(--text-sm);
			margin-bottom: 8px;
		}
		.taxjar-status-card-a {
			font-size: var(--text-lg);
			font-weight: 600;
		}
		/* es-badge defaults to white-space: nowrap with a fit-content width -
		   fine for "Yes"/"Skipped", but "Yes, but transaction is marked as
		   exempt" needs to wrap inside the card instead of overflowing it.
		   Its base rule also fixes height to one line and clips anything past
		   it, so height/overflow need overriding too, not just white-space -
		   otherwise a wrapped second line renders outside the pill's own
		   background instead of growing it. min-height (not height) keeps
		   single-line badges the same size they always were.
		   border-radius: full and line-height: 1 both come from the base rule
		   tuned for one line - carried into a two-line box, the stadium-shaped
		   corners curve in close enough to crowd the text against them, and the
		   tight line-height leaves the two lines touching. Both are toned down
		   here rather than only in the wrapped case, since a single-line badge
		   looks identical either way. */
		.taxjar-status-card-a .es-badge {
			white-space: normal;
			text-align: left;
			height: auto;
			min-height: calc(var(--spacing) * 5);
			overflow: visible;
			padding-block: calc(var(--spacing) * 0.75);
			padding-inline: calc(var(--spacing) * 2);
			border-radius: var(--radius-lg);
			line-height: 1.4;
		}
		.taxjar-status-arrow {
			display: flex;
			align-items: center;
			font-size: 20px;
			color: var(--text-muted);
		}
		@media (max-width: 991px) {
			.taxjar-status-cards { flex-direction: column; }
			.taxjar-status-card { flex-basis: auto; }
			.taxjar-status-arrow { justify-content: center; transform: rotate(90deg); }
		}

		.taxjar-addresses { display: flex; align-items: center; gap: 16px; padding: 8px 0; }
		/* Both cells carry the padding and a transparent border of the same
		   width, so lighting one up tints it in place instead of nudging the
		   other one sideways. */
		/* --radius-md, not --border-radius-md: this frappe ships the Espresso
		   --radius-* scale (css/espresso/radius.css) and never defines the old
		   --border-radius-* aliases, so that name resolves to nothing and the
		   corners come out square. Dashed rather than dotted for a longer
		   segment - dotted renders as round dots at 1px. */
		.taxjar-address {
			flex: 1;
			text-align: center;
			padding: 10px 12px;
			border: 1px dashed transparent;
			border-radius: var(--radius-md);
		}
		.taxjar-address-label { font-size: var(--text-sm); color: var(--text-muted); }
		.taxjar-address-value { font-weight: 600; margin-top: 4px; }
		.taxjar-address-arrow { font-size: 20px; color: var(--text-muted); }
		/* --bg-blue / --text-on-blue are frappe's own indicator-pill tokens
		   (indicator.scss), redefined per theme - so this tracks light/dark
		   without a hex of ours, and stays clear of the green/orange/grey
		   verdict pills on the status cards above. */
		.taxjar-address-lit { background: var(--bg-blue); border-color: var(--text-on-blue); }
		/* Not blue: the box carries the colour, and colouring its caption too
		   would read as a second signal rather than as the words for the one
		   already there. --text-light (ink-gray-5) rather than --text-muted
		   (ink-gray-6), a step lighter again, so it also sits below the
		   "Ship To" label it shares the box with rather than competing with
		   it. Both track the theme. */
		.taxjar-address-note {
			margin-top: 4px;
			font-size: var(--text-sm);
			color: var(--text-light);
		}
	`;
	document.head.appendChild(style);
};

// Show or hide a whole Section Break by fieldname, heading included. Emptying
// an HTML field inside a section leaves its heading behind, which announces a
// section that then says nothing - the state a non-US company's TaxJar tab was
// permanently in. Sections live in layout.sections_dict, not in fields_dict
// alongside the controls, and carry their own show/hide.
taxjar_integration.render_addresses = function (frm) {
	if (!frm.fields_dict.taxjar_addresses_html) return;
	const wrapper = frm.fields_dict.taxjar_addresses_html.$wrapper;

	// Nothing to show: neither address is stored until set_sales_tax has run,
	// and it never does for a company outside the United States or one with
	// calculation switched off. Only the content is cleared here - the heading
	// goes with it via the section's own depends_on (see _make_status_fields),
	// because a section hidden from here is re-shown by the next
	// Section.refresh(), which recomputes visibility from the field definition
	// and knows nothing of a hide() called in between.
	if (!frm.doc.taxjar_ship_from && !frm.doc.taxjar_ship_to) {
		wrapper.html("");
		return;
	}

	taxjar_integration._inject_status_card_styles();

	const from_text = frm.doc.taxjar_ship_from || __("Not set");
	const to_text = frm.doc.taxjar_ship_to || __("Not set");

	// Which end of the shipment set the rate, off TaxJar's own tax_source.
	// Only trusted while the document actually has nexus: the early returns in
	// set_sales_tax that stop before calculating (no nexus, exempt, no payload)
	// leave the stored value untouched, so a document that was taxed once would
	// otherwise keep advertising a rule that no longer applies to it. Same
	// guard shape as _has_no_nexus. With no source, neither side is tinted or
	// captioned - the row reads exactly as it did before.
	const source = frm.doc.taxjar_has_nexus ? (frm.doc.taxjar_tax_source || "") : "";
	const origin = source === "origin";
	const destination = source === "destination";

	// The tint alone says "this one" without saying why, so the rule is named
	// inside the box it applies to - no separate legend to read across to, and
	// nothing rendered at all on the side that didn't source the rate. One
	// argument drives both the tint and the caption, so they cannot disagree.
	// Brackets live in the markup, not in the translatable - a translator gets
	// the phrase to translate, not punctuation to reproduce.
	const cell = (label, text, note) => `
		<div class="taxjar-address${note ? " taxjar-address-lit" : ""}">
			<div class="taxjar-address-label">${label}</div>
			<div class="taxjar-address-value">${frappe.utils.escape_html(text)}</div>
			${note ? `<div class="taxjar-address-note">(${note})</div>` : ""}
		</div>`;

	wrapper.html(`
		<div class="taxjar-addresses">
			${cell(__("Ship From"), from_text, origin ? __("Origin based tax") : "")}
			<div class="taxjar-address-arrow">→</div>
			${cell(__("Ship To"), to_text, destination ? __("Destination based tax") : "")}
		</div>
	`);
};

// ── TaxJar Tax Breakdown Rendering ──
// Shared by the Sales Invoice / Sales Order / Quotation forms. Renders the
// jurisdiction-level tax breakdown stored on taxjar_breakdown_json.

taxjar_integration._no_breakdown_msg = function (is_new, frm) {
	let text;
	if (is_new) {
		text = __("Save transaction to fetch sales tax & view breakup.");
	} else if (frm && taxjar_integration._has_no_nexus(frm)) {
		// There is no breakdown and there never will be - say why, rather than
		// reporting an absence the user cannot act on.
		text = __("{0}, hence no taxes are charged.", [frm.doc.taxjar_nexus_reason]);
	} else {
		text = __("No TaxJar tax breakdown available for this transaction.");
	}
	return `<p class="text-muted">${text}</p>`;
};

// Nexus was actually assessed and came back negative. taxjar_has_nexus alone
// is 0 both for "no nexus" and "not evaluated yet", so the reason has to be
// present too.
taxjar_integration._has_no_nexus = function (frm) {
	return Boolean(frm.doc.taxjar_nexus_reason) && !frm.doc.taxjar_has_nexus;
};

// Plain HTML field, rendered client-side straight off the already-loaded
// taxjar_freight_taxable Check field - no server round trip needed. Kept out
// of taxjar_breakdown_html on purpose: a read-only Text Editor field wraps
// its whole content in a boxed "like-disabled-input" background, which looks
// right around the table but wrong around a standalone indicator pill.
taxjar_integration.render_shipping_taxability = function (frm) {
	if (!frm.fields_dict.taxjar_freight_taxable_html) return;
	const wrapper = frm.fields_dict.taxjar_freight_taxable_html.$wrapper;

	// Nothing is taxed without a nexus, so shipping taxability is moot - the
	// pill would answer a question that does not arise.
	//
	// hide() rather than just emptying: the field's own wrapper keeps its
	// margins when it holds no content, leaving a blank band above the
	// breakdown on an unsaved doc.
	if (
		frm.doc.taxjar_freight_taxable === undefined ||
		frm.doc.taxjar_freight_taxable === null ||
		taxjar_integration._has_no_nexus(frm)
	) {
		wrapper.empty().hide();
		return;
	}

	const taxable = cint(frm.doc.taxjar_freight_taxable);
	const label = taxable ? __("Yes") : __("No");
	const badge = frappe.ui.badge.html({ label, theme: taxable ? "green" : "gray" });
	wrapper.show().html(`
		<div style="margin-bottom: 10px; font-size: var(--text-md); display: flex; align-items: center; gap: 8px;">
			<span class="text-muted">${__("Are shipping charges taxable?")}</span>
			${badge}
		</div>
	`);
};

// The table itself (plus, for multi-currency docs, the USD sub-table above
// it) is rendered server-side - see get_taxjar_breakdown_html() in
// taxjar_integration.py and templates/includes/taxjar_breakup.html - same
// tax-break-up/table-bordered/table-hover markup core ERPNext and
// india_compliance use for their own Tax Breakup / GST Breakup tables, which
// is also what makes it show up in Print/PDF. onload pushes the rendered
// HTML onto frm.doc.__onload (the browser already holds its own copy of the
// doc by the time onload runs, so it can't be written directly onto the
// field) - this just copies it across.
taxjar_integration.render_tax_breakdown = function (frm) {
	if (!frm.fields_dict.taxjar_breakdown_html) return;

	if (frm.is_new()) {
		frm.doc.taxjar_breakdown_html = taxjar_integration._no_breakdown_msg(true);
	} else {
		frm.doc.taxjar_breakdown_html =
			frm.doc.__onload?._taxjar_breakdown_html || taxjar_integration._no_breakdown_msg(false, frm);
	}
	frm.refresh_field("taxjar_breakdown_html");

	// The field carries no label - the section heading above already names it -
	// but frappe renders the label block regardless and only hides it on
	// request (base_input.js:22-25, toggle_label). Left alone it is an empty
	// row of whitespace between the heading and the table. After
	// refresh_field(), which re-renders the value beneath it.
	frm.fields_dict.taxjar_breakdown_html.toggle_label?.(false);
};

// ── TaxJar Sync Status: sidebar pill (Sales Invoice) ──
// Inserted right after .sidebar-meta-details (the title/doc-id block), so it
// sits below the doc id and above the Assign/Attachments/Tags/Share list -
// its own border-bottom draws the line separating it from Assign below,
// same as .sidebar-meta-details already does above it.
// Same color mapping as the Sync Status column on the TaxJar Transaction
// Sync page (taxjar_transactions.js) - its detail now goes through
// frappe.ui.hover_card, a native component, rather than a fourth
// hand-rolled copy of the same fixed-position popover.

taxjar_integration.SYNC_STATUS_COLORS = {
	Synced: "green",
	Failed: "red",
	Queued: "blue",
	Excluded: "gray",
};

// Inserting is a separate step because clearing has to happen here, at the
// insert, not only in the dispatcher below: refresh() runs more than once per
// form load, and both renders are asynchronous (a whitelisted call, and for the
// not-enabled link a country lookup after it). A second pass therefore clears
// the sidebar while the first is still in flight, and both then insert - which
// is how two "Configure TaxJar" rows appeared. Clearing immediately before the
// insert makes the last render win instead of stacking.
taxjar_integration._mount_sidebar_section = function ($section) {
	$(document).find(".form-sidebar .taxjar-sync-sidebar-pill-section").remove();
	$(document).find(".form-sidebar .sidebar-meta-details").after($section);
};

taxjar_integration.render_sync_status_sidebar_pill = function (frm) {
	// Not on a half-written document - see party_details_are_updating. The pill
	// reads the destination too, so it would flicker with the strip.
	if (taxjar_integration.party_details_are_updating(frm)) return;

	// Still cleared up front, so a doc that renders nothing at all (no sync
	// field, no company, or TaxJar disabled for it) leaves no stale row behind.
	$(document).find(".form-sidebar .taxjar-sync-sidebar-pill-section").remove();

	if (!frm.fields_dict.taxjar_sync_status || !frm.doc.company) return;

	const docname = frm.doc.name;

	// Checked live on every refresh rather than cached on the transaction doc -
	// a stored flag would go stale for a Draft left unsaved, or worse for a
	// Cancelled doc (which is never saved again), once the company's TaxJar
	// config changes after the doc was last written.
	taxjar_integration.scope(frm.doc.company).then((scope) => {
		if (frm.doc.name !== docname) return;
		// The scope could not be read at all. Nothing is known, so nothing is
		// claimed.
		if (!scope) return;

		// TaxJar prices United States sales tax. A company registered elsewhere
		// is not one with a switch off, it is one the feature cannot serve, so
		// the setup page has nothing to offer it and the row stays empty.
		//
		// Every other no is something the reader can go and change: the site
		// switch, a company with no TaxJar row, or the two feature switches. All
		// three used to render nothing at all, which left a reader who had
		// switched TaxJar off site-wide with no cue that this was why. They now
		// get the same link, because they are all fixed on the same page.
		if (scope.reason === "not_us") return;

		if (!scope.files) {
			taxjar_integration._render_taxjar_not_enabled_link(frm);
			return;
		}

		// Every state but one is read off the document itself. An export is the
		// exception: the destination country decides it, the document carries a
		// destination from its first draft, and the answer is one column of one
		// Address rather than anything the sync path writes. So a draft asks,
		// and the pill is told.
		//
		// Nothing else asks. A submitted document has its status recorded, and
		// its detail line says the same thing for an export as for a domestic
		// sale - so the lookup would buy nothing and cost a round trip on every
		// submitted invoice anyone opens.
		if (frm.doc.docstatus !== 0) {
			taxjar_integration._render_taxjar_sync_status_pill(frm);
			return;
		}

		// Ship-to decides the destination. The billing address stands in for a
		// sale with no separate shipping address, the same way it does for nexus.
		const address = frm.doc.shipping_address_name || frm.doc.customer_address;
		return taxjar_integration.export_destination(address, frm.doc.company).then((export_to) => {
			// The form can move to another document while this is in flight, and
			// a stale answer describes another sale.
			if (frm.doc.name !== docname) return;
			// It can move to another address on the same document too, and that
			// answer is just as stale. Both address fields repaint this pill, so
			// two picks in quick succession leave two lookups running, and the
			// one asked first can be the one to answer last - which would leave
			// the pill describing a destination the document no longer has. Same
			// guard _show_no_address_tax_message and the nexus check above
			// already apply to the same lookup.
			if ((frm.doc.shipping_address_name || frm.doc.customer_address) !== address) return;
			// The whole answer, not a boolean: the pill needs the country to know
			// this is an export, and files_exports to know what the submit will
			// do about it.
			taxjar_integration._render_taxjar_sync_status_pill(frm, export_to);
		});
	});
};

// TaxJar isn't configured for this company at all - there's no sync state to
// report, so no "TaxJar Status" label and no pill, just a plain link to go
// fix it. Distinct from the "Excluded" pill (below), which covers a
// company that IS enabled but hasn't reached _set_sync_status yet.
//
// Only rendered for a United States company - TaxJar is a US sales-tax
// service and the guided setup wizard it links to has nothing to offer a
// non-US company, so the link would just be a dead end for one.
taxjar_integration._render_taxjar_not_enabled_link = function (frm) {
	// Reached only for a company the dispatcher has already cleared as one the
	// setup page can help, so the country round trip this used to make has
	// nothing left to decide.
	{
		const icon = frappe.utils.icon("external-link", "xs", "", "", "", true);
		// The logo sits beside the link rather than inside it, so it is not
		// dragged into the link's own colour or hover treatment.
		//
		// The words carry the same class and weight as the status label this
		// row stands in for (see _render_taxjar_sync_status_pill), so the two
		// states of the same sidebar row read as one thing rather than as a
		// caption and a link that happen to share a slot. The external-link
		// icon is the affordance that says it goes somewhere.
		const $section = $(`
			<div class="sidebar-section taxjar-sync-sidebar-pill-section border-bottom">
				<div style="display: flex; align-items: center; gap: 4px;">
					${taxjar_integration._logo_html()}
					<a
						href="${TAXJAR_SETUP_FEATURES_URL}"
						class="taxjar-not-enabled-link text-muted"
						style="display: inline-flex; align-items: center; gap: 4px; font-weight: 600; color: inherit;"
					>${__("Configure TaxJar")}${icon}</a>
				</div>
			</div>
		`);
		taxjar_integration._mount_sidebar_section($section);
	}
};

// Why a submitted document was kept out of TaxJar, as the sentence it deserves.
// Shared by the invoice form's sidebar pill and the Transaction Sync page's info
// icon, so one state is not explained two ways on two screens.
//
// Every configuration reason has two readings, and which one is being given is
// not a detail to gloss over: `is_current` says this was read off the settings
// as they stand now, because the row predates the reason being recorded and its
// real reason is not recoverable - the configuration has moved on since. Saying
// that in the past tense would claim to know something that was never written
// down. "Removed from TaxJar" is only ever a recorded fact; nothing in the
// current configuration can infer it.
taxjar_integration.exclusion_reason_text = function (reason, is_current) {
	if (reason === "TaxJar Disabled") {
		return is_current
			? __("TaxJar is switched off for this site.")
			: __("TaxJar was switched off for this site when this document was submitted.");
	}

	if (reason === "Transaction Sync not enabled for company") {
		// Same words as the stored value the reader can see on the invoice's own
		// Exclusion Reason field, expanded into a sentence rather than restated in
		// a second vocabulary.
		return is_current
			? __("Transaction sync is not enabled for this company.")
			: __("Transaction sync was not enabled for this company when this document was submitted.");
	}

	if (reason === "Removed from TaxJar") {
		return __("This transaction was removed from TaxJar.");
	}

	if (reason === "Export Transaction") {
		// Present tense, and it names the setting rather than the country: an
		// export is kept out by a choice someone made and can unmake, not by
		// where the sale went. See Include Export Transactions on TaxJar
		// Company Config. The link that unmakes it is exclusion_reason_action,
		// kept out of the sentence for the reason given there.
		return __("Export transactions sync is disabled.");
	}

	// Both written by the pre-upgrade invoice check (legacy_check.py), on
	// invoices that TaxJar version 15 may have sent without a record.
	if (reason === "Submitted before upgrade, not yet checked") {
		return __("This invoice was submitted before the upgrade from TaxJar version 15. The check of whether TaxJar holds it has not run yet.");
	}

	if (reason === "Not found in TaxJar, submitted before upgrade") {
		return __("This invoice was submitted before the upgrade from TaxJar version 15. TaxJar does not hold it.");
	}

	return "";
};

// The link a reason leaves the reader wanting. Held apart from the sentence
// because both screens that show the sentence render it as text on purpose -
// taxjar_sync_error is whatever TaxJar's API said, and must not be able to put
// markup on a form - so the link is built as an element instead.
//
// Only a reason someone can act on gets one. "Removed from TaxJar" is a record
// of what happened and has nothing to open.
taxjar_integration.exclusion_reason_action = function (reason) {
	if (reason === "Export Transaction") {
		// Features is the step that owns Include Export Transactions, the same
		// card the other remedial links open.
		return { label: __("Configure"), href: TAXJAR_SETUP_FEATURES_URL };
	}

	if (reason === "Submitted before upgrade, not yet checked") {
		return { label: __("Run the check"), href: "/app/taxjar-settings#legacy_tab" };
	}

	return null;
};

// The body of a hover card or a popover: the sentence, then the link that acts
// on it. An element, and the sentence goes in through .text(), so no part of it
// is ever read as markup.
//
// Underlined, and with an arrow after the words. The link follows a sentence of
// the same size, weight and color, and a card of this size carries nothing else
// for the eye to tell it apart from - so the underline says it can be pressed
// and the arrow says where pressing it goes.
//
// The rule runs under the word and stops there. An arrow is a shape, and a line
// under it reads as part of the shape rather than as the same line the word
// carries - so the word owns the underline and the anchor draws none of its
// own. nowrap keeps the two on one line. The style is inline because the two
// screens that show this body keep their own stylesheets, and the link would
// otherwise be written twice.
taxjar_integration.sync_info_body = function (text, action) {
	const $body = $("<div>").text(text);
	if (action) {
		$body.append(
			" ",
			$("<a>")
				.attr("href", action.href)
				.css({ color: "inherit", "text-decoration": "none", "white-space": "nowrap" })
				.append(
					$("<span>").text(action.label).css("text-decoration", "underline"),
					" \u2192"
				)
		);
	}

	return $body;
};

taxjar_integration._render_taxjar_sync_status_pill = function (frm, export_to) {
	// "Synced"/"Failed" are written by both the on_submit sync path and the
	// on_cancel delete path (see _set_sync_status), so docstatus === 2 is
	// what turns those two into the cancel-flow wording below.
	const cancelled = frm.doc.docstatus === 2;
	const status = frm.doc.taxjar_sync_status || "Excluded";
	// An export this company does not file. The country alone does not decide
	// it: the same sale is filed for one company and kept out for the next.
	// Only a draft is given one - see render_sync_status_sidebar_pill.
	const export_excluded = Boolean(export_to) && !export_to.files_exports;
	let label, color, info_text;
	// Only an exclusion reason carries an action. Every other detail below is a
	// report on what happened, not a setting the reader can go and change.
	let info_action = null;

	if (frm.doc.docstatus === 0 && export_excluded) {
		// A draft is told what to do rather than given a status, because nothing
		// syncs before submit. An export the company keeps out is the one draft
		// whose answer is already settled, so the submit will exclude it and
		// "Submit to Sync" would promise a sync that cannot happen. An export
		// the company does file falls through to that promise like any other
		// draft, because for it the promise is true.
		label = __("Excluded");
		color = taxjar_integration.SYNC_STATUS_COLORS.Excluded;
		info_text = taxjar_integration.exclusion_reason_text("Export Transaction");
		info_action = taxjar_integration.exclusion_reason_action("Export Transaction");
	} else if (frm.doc.docstatus === 0) {
		label = __("Submit to Sync");
		color = "amber";
		// The one state whose detail is an instruction rather than a report:
		// nothing has gone wrong, there is simply nothing to sync until the
		// document is submitted.
		info_text = __("Submit this document to sync it with TaxJar.");
	} else if (status === "Queued") {
		label = __("Queued");
		color = taxjar_integration.SYNC_STATUS_COLORS[status];
		info_text = __("Queued for sync");
	} else if (status === "Synced") {
		label = cancelled ? __("Cancelled") : __("Synced");
		color = cancelled ? "gray" : taxjar_integration.SYNC_STATUS_COLORS[status];
		// Cancelled is this same "Synced" status value written by the
		// on_cancel delete path (see _set_sync_status), so both read the same
		// way: when TaxJar last heard about this document.
		info_text = frm.doc.taxjar_last_synced
			? taxjar_integration._synced_ago_text(frm.doc.taxjar_last_synced)
			: __("Synced with TaxJar");
	} else if (status === "Failed") {
		label = cancelled ? __("Failed to Cancel") : __("Failed");
		color = taxjar_integration.SYNC_STATUS_COLORS[status];
		info_text = frm.doc.taxjar_sync_error || __("Unknown error");
	} else {
		// Excluded: submitted, and deliberately not sent. The pill used to stop
		// at the word and leave the reader to go and compare the settings
		// themselves; enqueue_taxjar_sync now records which switch was off, and
		// this says it. A document excluded before that was recorded has nothing
		// stored and gets no hover card - the page can fall back on the current
		// configuration because it says so in the present tense, whereas a bare
		// sentence on the form could not carry that distinction.
		label = __(status);
		color = taxjar_integration.SYNC_STATUS_COLORS[status];
		info_text = taxjar_integration.exclusion_reason_text(frm.doc.taxjar_exclusion_reason);
		info_action = taxjar_integration.exclusion_reason_action(frm.doc.taxjar_exclusion_reason);
	}

	const $badge = frappe.ui.badge({ label, theme: color });
	if (info_text) $badge.css("cursor", "pointer");

	// Label and pill on one row, pill to the right - stacked, three words and
	// a badge took two lines of a narrow column, and the label sat far enough
	// from the badge to read as a heading over the rest of the sidebar rather
	// than as this pill's own caption. The row class is an append target, not
	// a styling hook; the layout is two properties and stays inline, same as
	// the label's own weight.
	const $pill = $(`
		<div class="sidebar-section taxjar-sync-sidebar-pill-section border-bottom">
			<div class="taxjar-sync-sidebar-pill-row"
				style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
				<div style="display: flex; align-items: center; gap: 4px;">
					${taxjar_integration._logo_html()}
					<div class="text-muted" style="font-weight: 600;">${__("TaxJar Status")}</div>
				</div>
			</div>
		</div>
	`);
	$pill.find(".taxjar-sync-sidebar-pill-row").append($badge);

	taxjar_integration._mount_sidebar_section($pill);

	// frappe.ui.hover_card, not popover: every state now carries a detail
	// worth glancing at - why it failed, how long ago it synced, what to do
	// about a Draft - and a preview that answers a passing glance shouldn't
	// ask to be clicked open and clicked shut again. Delays are the component
	// explorer's "quick preview" pair; the 700ms default is tuned to keep
	// cards from popping as the pointer skims a list of links, and there is
	// exactly one trigger in this sidebar. Aligned to the badge's own right
	// edge, which is the edge it sits against in the column.
	//
	// A string content wherever the detail is a report, so the card renders it
	// as text - taxjar_sync_error is whatever TaxJar's API said, and must not be
	// able to smuggle markup into the sidebar. A reason with an action gets an
	// element instead, built by sync_info_body out of words this app wrote. The
	// card keeps itself open while the pointer is on it, so the link is
	// reachable.
	if (info_text) {
		frappe.ui.hover_card($badge, {
			content: () =>
				info_action ? taxjar_integration.sync_info_body(info_text, info_action) : info_text,
			side: "bottom",
			align: "end",
			open_delay: 200,
			close_delay: 150,
		});
	}
};

// "Synced 5 minutes ago" - the question a status pill raises is how fresh
// this is, not what the clock read. prettyDate blanks out for a timestamp it
// reads as being in the future (pretty_date.js's `day_diff < 0` guard), which
// a site whose System Settings timezone runs ahead of the browser's own
// produces for a sync that has only just happened, so fall back to the
// absolute user-tz time rather than to a bare "Synced".
taxjar_integration._synced_ago_text = function (timestamp) {
	const ago = frappe.datetime.prettyDate(timestamp);
	return ago ? __("Synced {0}", [ago]) : __("Synced on {0}", [frappe.datetime.str_to_user(timestamp)]);
};

// ── "TaxJar not set up" panel ──
// Rendered by the Customers / Transactions pages when their read methods report
// not_configured (the TaxJar custom fields do not exist yet). Replaces the table
// area with a friendly call to action instead of an empty grid or a server error.
taxjar_integration.render_not_configured_panel = function ($container) {
	$container.empty().append(frappe.ui.empty_state({
		icon: "settings",
		title: __("TaxJar is not set up yet"),
		description: __("Enable a TaxJar feature in TaxJar Settings to start configuring customers and syncing transactions."),
		// onclick + set_route, not href - href actions open in a new tab
		// (empty_state.js's own behavior for external links); this is desk
		// navigation to another doctype, which should stay in the same tab
		// the way the plain <a> it replaces did.
		actions: [{
			label: __("Open TaxJar Settings"), variant: "solid",
			onclick: () => frappe.set_route("Form", "TaxJar Settings"),
		}],
		css_class: "min-h-64",
	}));
};

// ── Nexus & Product Tax Category summary ──
// The tables the TaxJar Settings form's "Nexus & Product Category" tab draws.
// They live here rather than in the form because the form only hands them a
// wrapper and its data, so they never have to know about a form at all.
//
// The standalone page of the same name (/app/taxjar-nexus) drew these too,
// until it took on a card layout of its own. Every card there carries its own
// title, subtitle, "Synced ..." caption and refresh control, all four of which
// the form already supplies from its section headers and labelled buttons - so
// one renderer can no longer serve both. format_last_synced() below is still
// shared, because both places show the same caption.

// str_to_user() converts system tz -> user tz via moment-timezone and just
// formats it - no comparison against the browser's local clock, so it can't
// hit comment_when()/prettyDate()'s "future date" guard (pretty_date.js:21,
// `if (day_diff < 0) return ""`), which blanked this out whenever the site's
// System Settings timezone drifted far enough from the browser's own.
// Shared by Nexus and Product Tax Category - both are "when did this list
// last come from TaxJar" and were duplicating the same three lines.
taxjar_integration.format_last_synced = function (value) {
	return value ? frappe.datetime.str_to_user(value) : __("Never");
};

// comment_when() puts the absolute date in a native title on its span. This
// moves it into the desk's own bubble, so the date on hover matches every
// other tooltip in the app. refresh_when() rewrites only the span's text each
// minute, so the title does not come back.
taxjar_integration.timestamp_tooltips = function ($el) {
	$el.find(".frappe-timestamp[title]").each((_, span) => {
		const text = span.getAttribute("title");
		span.removeAttribute("title");
		if (frappe.ui.tooltip) frappe.ui.tooltip(span, { text });
	});
};

// Espresso's own component CSS (.es-badge, and the shared radius/spacing
// tokens the classes below key off) is already loaded on every desk page -
// only the card/table layout specific to this grouped-by-company list needs
// injecting, same pattern as _inject_status_card_styles() above.
taxjar_integration._inject_nexus_table_styles = function () {
	if (document.getElementById("taxjar-nexus-table-styles")) return;
	const style = document.createElement("style");
	style.id = "taxjar-nexus-table-styles";
	style.textContent = `
		.taxjar-nexus-card {
			border: 1px solid var(--border-color);
			border-radius: var(--radius-md);
			margin-bottom: 16px;
			overflow: hidden;
		}
		.taxjar-nexus-card-h {
			display: flex; align-items: center; gap: 8px;
			background: var(--subtle-fg);
			padding: 10px 16px;
			font-weight: 600;
			font-size: 13px;
			color: var(--heading-color);
			border-bottom: 1px solid var(--border-color);
		}
		.taxjar-nexus-table-wrap { overflow-x: auto; }
		.taxjar-nexus-table { width: 100%; border-collapse: collapse; font-size: 12px; }
		.taxjar-nexus-table th {
			text-align: left; padding: 8px 16px; color: var(--text-muted);
			font-weight: 500; border-bottom: 1px solid var(--border-color); white-space: nowrap;
		}
		.taxjar-nexus-table td { padding: 8px 16px; white-space: nowrap; }
		.taxjar-nexus-table tr:not(:last-child) td { border-bottom: 1px solid var(--border-color); }
		/* The desk's default <code> color is a fixed purple that is too dark to
		   read on the dark theme. The ink token follows the theme. */
		.taxjar-nexus-table code { color: var(--ink-gray-6); background: none; }
	`;
	document.head.appendChild(style);
};

// One bordered card per company, each holding that company's nexus regions.
// `rows` is the TaxJar Settings `nexus` child table (or the same shape read
// back from the page's own API).
taxjar_integration.render_nexus_cards = function ($wrapper, rows) {
	rows = rows || [];

	if (!rows.length) {
		$wrapper.empty().append(frappe.ui.empty_state({
			icon: "map-pin",
			title: __("No nexus regions loaded"),
			description: __("Fetch them from TaxJar using the button above."),
			css_class: "my-2",
		}));
		return;
	}

	taxjar_integration._inject_nexus_table_styles();

	// Group rows by company
	const by_company = {};
	for (const row of rows) {
		const key = row.company || "(No Company)";
		if (!by_company[key]) by_company[key] = [];
		by_company[key].push(row);
	}

	$wrapper.empty();
	for (const [company, company_rows] of Object.entries(by_company)) {
		const rows_html = company_rows.map((r) => `
			<tr>
				<td>${frappe.utils.escape_html(r.region || "—")}</td>
				<td><code>${frappe.utils.escape_html(r.region_code || "—")}</code></td>
				<td>${frappe.utils.escape_html(r.country || "—")}</td>
				<td><code>${frappe.utils.escape_html(r.country_code || "—")}</code></td>
			</tr>`).join("");

		const $card = $(`
			<div class="taxjar-nexus-card">
				<div class="taxjar-nexus-card-h">${frappe.utils.escape_html(company)}</div>
				<div class="taxjar-nexus-table-wrap">
					<table class="taxjar-nexus-table">
						<thead>
							<tr>
								<th>${__("Region")}</th>
								<th>${__("Code")}</th>
								<th>${__("Country")}</th>
								<th>${__("Country Code")}</th>
							</tr>
						</thead>
						<tbody>${rows_html}</tbody>
					</table>
				</div>
			</div>
		`).appendTo($wrapper);

		$card.find(".taxjar-nexus-card-h").append(
			frappe.ui.badge({ label: String(company_rows.length), theme: "blue", size: "sm" })
		);
	}
};

// `summary` is get_product_tax_category_summary()'s {count, last_updated} -
// the categories are not company-scoped, so there is nothing to group and the
// count itself is the whole summary. `show_last_updated` stays an option for a
// caller whose own section header already carries that caption; on the settings
// form, the only caller left, the box is the only place it can go.
taxjar_integration.render_product_tax_category_summary = function ($wrapper, summary, options) {
	const count = (summary || {}).count || 0;
	const show_last_updated = (options || {}).show_last_updated !== false;

	if (!count) {
		$wrapper.empty().append(frappe.ui.empty_state({
			icon: "tag",
			title: __("No product tax categories loaded"),
			description: __("Fetch them from TaxJar using the button above."),
			css_class: "my-2",
		}));
		return;
	}

	const last_updated = show_last_updated
		? `<div style="color: var(--text-muted); font-size: var(--text-sm); margin-top: 4px;">
				${__("Last updated")}: ${taxjar_integration.format_last_synced(summary.last_updated)}
			</div>`
		: "";

	$wrapper.html(`
		<div style="
			border: 1px solid var(--border-color);
			border-radius: var(--radius-md);
			padding: 16px;
			text-align: center;
			/* Last thing in the section - without this the box's border
			   sits flush against the next section's divider. Matches the
			   empty-state box below so the gap doesn't change when the
			   list is loaded. */
			margin-bottom: 16px;
		">
			<div style="font-size: var(--text-lg);">
				<a href="/app/product-tax-category">${count} ${__("Product Tax Categories")}</a>
				${__("are configured.")}
			</div>
			<div style="color: var(--text-muted); font-size: var(--text-sm); margin-top: 4px;">
				${__("(Updates are automatically fetched every week)")}
			</div>
			${last_updated}
		</div>
	`);
};
