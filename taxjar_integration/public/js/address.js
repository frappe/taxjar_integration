// TaxJar — Address form client script
// Auto-syncs taxjar_state_code ↔ state when country is "United States".
// Works out taxjar_region_code from the state everywhere else.
// Enforces mandatory fields: state (US/CA), taxjar_state_code (US), pincode (US).
// Labels the State Code options with the state name.

// State code → full name map is defined once in taxjar_utils.js (loaded globally
// via the app bundle) so the Address and Customer forms stay in lockstep. The
// reverse lookup lives there too: the transaction's own Create Address dialog
// reads the State box the same way, and two copies would drift apart.
const TAXJAR_US_STATES = taxjar_integration.US_STATE_NAMES;

function _has_state_code_field(frm) {
	return !!frm.fields_dict["taxjar_state_code"];
}

function _has_region_code_field(frm) {
	return !!frm.fields_dict["taxjar_region_code"];
}

// The sentences under the two code boxes, the same ones the address dialogs
// show - see _region_code_hint() and _state_code_hint() in taxjar_utils.js.
function _describe_region_code(frm) {
	if (!_has_region_code_field(frm)) return;
	frm.set_df_property(
		"taxjar_region_code",
		"description",
		taxjar_integration._region_code_hint(
			(frm.doc.taxjar_region_code || "").trim() === taxjar_integration.UNKNOWN_REGION_CODE,
			!!(frm.doc.state || "").trim()
		)
	);
}

function _describe_state_code(frm) {
	if (!_has_state_code_field(frm)) return;
	frm.set_df_property(
		"taxjar_state_code",
		"description",
		taxjar_integration._state_code_hint(frm.doc.state)
	);
}

// The region code a sale outside the United States is filed under. It comes
// from the country and the state, so the form works it out again whenever
// either one changes - the same answer set_address_region_code() writes at
// save, on the screen before the save rather than after it.
//
// The server is asked rather than a map in this file: ISO 3166-2 lists
// thousands of regions across 250 countries, and pycountry already holds them.
function _refresh_region_code(frm) {
	if (!_has_region_code_field(frm)) return;

	// Each call starts a new lookup and makes the older ones stale. Quick edits
	// to the country or the state start lookups that overlap, and the server
	// can answer them in any order. Only the latest may write the box.
	const lookup = (frm.__taxjar_region_lookup = (frm.__taxjar_region_lookup || 0) + 1);

	// taxjar_state_code carries the United States answer, and the box is hidden
	// there. A code from the country before it is read by nothing.
	if (frm.doc.country === "United States") {
		if (frm.doc.taxjar_region_code) frm.set_value("taxjar_region_code", "");
		return;
	}

	// Only what this script wrote is replaced. A code already in the box is the
	// reader's own answer, and an edit to the state does not make it ours to
	// overwrite. The "XX" stand-in is never an answer, and a real region beats
	// it.
	const unknown = taxjar_integration.UNKNOWN_REGION_CODE;
	const stored = (frm.doc.taxjar_region_code || "").trim();
	if (stored && stored !== frm.__taxjar_region_code && stored !== unknown) return;

	// Nothing to work out without a region name, and nothing to say about it
	// either. A reader picks the country first and types the state after it,
	// and the server would answer "" to every one of those picks.
	if (!(frm.doc.state || "").trim()) {
		if (stored) frm.set_value("taxjar_region_code", "");
		frm.__taxjar_region_code = "";
		return _describe_region_code(frm);
	}

	return frappe
		.xcall("taxjar_integration.taxjar_integration.taxjar_integration.resolve_region_code", {
			country: frm.doc.country,
			state: frm.doc.state,
		})
		.then((answer) => {
			if (lookup !== frm.__taxjar_region_lookup) return;
			// A code the reader typed while the lookup ran is their answer.
			if ((frm.doc.taxjar_region_code || "").trim() !== stored) return;

			// A State with no matching region gets the stand-in, as in the
			// save-time dialog. TaxJar refuses a blank region and takes "XX".
			const code = (answer && answer.region_code) || unknown;
			frm.__taxjar_region_code = code;
			const write = code !== stored ? frm.set_value("taxjar_region_code", code) : null;
			return Promise.resolve(write).then(() => _describe_region_code(frm));
		});
}

// The field stores a 2-letter code, and the custom field's own options are
// those codes alone - the server validates against them. The form relabels each
// option to "AK — Alaska" so the reader does not have to decode it. The value
// under every option stays the code, so nothing about what is saved changes.
// The labels come from the same builder the guided setup address dialog uses.
function _label_state_code_options(frm) {
	if (!_has_state_code_field(frm)) return;
	frm.set_df_property("taxjar_state_code", "options", taxjar_integration.us_state_code_options());
}

function _set_taxjar_mandatory_fields(frm) {
	const country = frm.doc.country;
	// Use country names — standard Frappe Country DocType values, not subject to change.
	const needs_state = country === "United States" || country === "Canada";
	const is_us = country === "United States";

	frm.set_df_property("state", "reqd", needs_state ? 1 : 0);
	frm.set_df_property("pincode", "reqd", is_us ? 1 : 0);

	// taxjar_state_code only renders for US (has depends_on in field def), so only toggle reqd for US.
	if (_has_state_code_field(frm)) {
		frm.set_df_property("taxjar_state_code", "reqd", is_us ? 1 : 0);
	}
}

frappe.ui.form.on("Address", {
	onload(frm) {
		// Once per form: the options never change after this.
		_label_state_code_options(frm);
	},

	refresh(frm) {
		_set_taxjar_mandatory_fields(frm);
		_describe_state_code(frm);
		_describe_region_code(frm);
	},

	country(frm) {
		_set_taxjar_mandatory_fields(frm);

		if (_has_state_code_field(frm)) {
			if (frm.doc.country !== "United States" && frm.doc.taxjar_state_code) {
				frm.set_value("taxjar_state_code", "");
			}
		}

		// The country decides which of the two boxes holds the answer, so both
		// are settled on a change - the state code above, the region code here.
		return _refresh_region_code(frm);
	},

	state(frm) {
		if (frm.doc.country !== "United States") return _refresh_region_code(frm);
		if (!_has_state_code_field(frm)) return;
		_describe_state_code(frm);
		const code = taxjar_integration.us_state_code_from_name(frm.doc.state);
		if (code && code !== frm.doc.taxjar_state_code) {
			frm.set_value("taxjar_state_code", code);
		}
	},

	taxjar_state_code(frm) {
		if (!_has_state_code_field(frm)) return;
		if (!frm.doc.taxjar_state_code) return;
		const full_name = TAXJAR_US_STATES[frm.doc.taxjar_state_code];
		if (full_name && frm.doc.state !== full_name) {
			frm.set_value("state", full_name);
		}
	},
});
