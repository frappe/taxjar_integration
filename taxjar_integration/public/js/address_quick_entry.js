// TaxJar — State Code and Region Code in the address quick entries.
//
// Two dialogs make an Address without the Address form: "New Address" on a
// form's Address & Contact tab (frappe's AddressQuickEntryForm), and the
// address part of the Customer quick entry (ERPNext's CustomerQuickEntryForm).
// A quick entry shows only required fields, so neither showed the two codes,
// and the Address form's script that fills them does not run in a dialog.
//
// The save fills an empty code from the state - see validate_address() and
// set_address_region_code(). These boxes show the reader that answer before
// the save, and let them correct it.

// The two boxes, the same pair under the same rule as the Create Address
// dialog in taxjar_utils.js: the state code for a United States address, the
// region code for every other one.
function code_fields(d, country_field) {
	const is_us = `eval:doc.${country_field} === "United States"`;
	return [
		{
			fieldtype: "Select",
			fieldname: "taxjar_state_code",
			label: __("State Code (US)"),
			options: taxjar_integration.us_state_code_options(),
			depends_on: is_us,
			mandatory_depends_on: is_us,
			onchange: () => taxjar_integration._fill_dialog_state_from_code(d),
		},
		{
			fieldtype: "Data",
			fieldname: "taxjar_region_code",
			label: __("Region Code (ISO 3166-2)"),
			depends_on: `eval:doc.${country_field} && doc.${country_field} !== "United States"`,
		},
	];
}

// The dialog's fields with the two boxes after State, and State and Country
// set to work the codes out again on a change.
//
// Copies, not the fields themselves. A quick entry's fields are the doctype's
// own docfields, and an onchange set on one would reach every later dialog.
function with_code_fields(fields, d, country_field) {
	const out = [];
	const add = (df) => out.push(bind_to_doc(d, df));
	for (const df of fields) {
		// A site that ticked "Allow in Quick Entry" on either box already has
		// it here, without the onchange. The copy below replaces it.
		if (df.fieldname === "taxjar_state_code" || df.fieldname === "taxjar_region_code") continue;

		if (df.fieldname === "state" || df.fieldname === country_field) {
			add({ ...df, onchange: () => taxjar_integration._refresh_dialog_codes(d) });
		} else {
			out.push(df);
		}
		if (df.fieldname === "state") code_fields(d, country_field).forEach(add);
	}
	return out;
}

// The same settings, written onto the document's own copy of the field.
//
// A dialog that holds a document swaps each field for that copy when it draws
// - see refresh_fields() in frappe's form/layout.js - so a setting on the
// dialog's field alone is lost: the State Code showed bare codes and nothing
// filled it. The copy belongs to this one new document, so no other form sees
// the change. The Customer has no field of these names, and there is nothing
// to write.
function bind_to_doc(d, df) {
	const own = d.doc && frappe.meta.get_docfield(d.doc.doctype, df.fieldname, d.doc.name);
	if (own) Object.assign(own, df);
	return df;
}

// What each dialog shares once it is on the screen. The country names the
// box, and an empty region box matches the Address form - see
// _refresh_dialog_region().
function prepare(d, country_field) {
	d.__taxjar_country_field = country_field;
	d.__taxjar_region_fallback = "";
}

function with_address_codes(Base) {
	return class extends Base {
		render_dialog() {
			prepare(this, "country");
			this.docfields = with_code_fields(this.docfields, this, "country");
			super.render_dialog();
			taxjar_integration._refresh_dialog_codes(this);
		}
	};
}

// ERPNext adds the address boxes in get_variant_fields(), inside its own
// render_dialog(), so the two codes go in there. Its country box is
// country_address, because the Customer has a country field of its own.
function with_customer_codes(Base) {
	return class extends Base {
		get_variant_fields() {
			prepare(this, "country_address");
			return with_code_fields(super.get_variant_fields(), this, "country_address");
		}

		render_dialog() {
			super.render_dialog();
			taxjar_integration._refresh_dialog_codes(this);
		}
	};
}

const WRAPPERS = {
	AddressQuickEntryForm: with_address_codes,
	CustomerQuickEntryForm: with_customer_codes,
};

// Each class is wrapped the first time a quick entry opens, not when this
// file loads. This app can load before ERPNext, and CustomerQuickEntryForm does
// not exist until ERPNext's bundle runs.
function wrap_quick_entry_forms() {
	for (const [name, wrap] of Object.entries(WRAPPERS)) {
		const Base = frappe.ui.form[name];
		if (!Base || Base.__taxjar_codes) continue;

		const Wrapped = wrap(Base);
		Wrapped.__taxjar_codes = true;
		frappe.ui.form[name] = Wrapped;
	}
}

const make_quick_entry = frappe.ui.form.make_quick_entry;
frappe.ui.form.make_quick_entry = function (...args) {
	wrap_quick_entry_forms();
	return make_quick_entry.apply(this, args);
};
