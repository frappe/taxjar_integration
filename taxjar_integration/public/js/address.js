// TaxJar — Address form client script
// Auto-syncs taxjar_state_code ↔ state when country is "United States".
// Enforces mandatory fields: state (US/CA), taxjar_state_code (US), pincode (US).

// State code → full name map is defined once in taxjar_utils.js (loaded globally
// via the app bundle) so the Address and Customer forms stay in lockstep.
const TAXJAR_US_STATES = taxjar_integration.US_STATE_NAMES;

// Build reverse map: "CALIFORNIA" → "CA"
const TAXJAR_US_STATE_BY_NAME = Object.fromEntries(
	Object.entries(TAXJAR_US_STATES).map(([code, name]) => [name.toUpperCase(), code])
);

function _resolve_state_code(state_value) {
	if (!state_value) return null;
	const upper = state_value.toUpperCase().trim();
	// Direct 2-letter code match
	if (TAXJAR_US_STATES[upper]) return upper;
	// Full name match
	if (TAXJAR_US_STATE_BY_NAME[upper]) return TAXJAR_US_STATE_BY_NAME[upper];
	return null;
}

function _has_state_code_field(frm) {
	return !!frm.fields_dict["taxjar_state_code"];
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
	refresh(frm) {
		_set_taxjar_mandatory_fields(frm);
	},

	country(frm) {
		_set_taxjar_mandatory_fields(frm);

		if (!_has_state_code_field(frm)) return;
		if (frm.doc.country !== "United States" && frm.doc.taxjar_state_code) {
			frm.set_value("taxjar_state_code", "");
		}
	},

	state(frm) {
		if (!_has_state_code_field(frm)) return;
		if (frm.doc.country !== "United States") return;
		const code = _resolve_state_code(frm.doc.state);
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
