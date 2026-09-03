frappe.ui.form.on("Sales Invoice", {
	shipping_address_name: function(frm) {
		if (frm.doc.shipping_address_name) {
			frappe.call({
				method: "taxjar_integration.taxjar_integration.taxjar_integration.check_nexus",
				args: {
					shipping_address_name: frm.doc.shipping_address_name
				},
				callback: function(r) {
					if (r.message) {
						let msg = __("The state {0} ({1}) is not in your TaxJar Nexus list.", [r.message.state, r.message.state_code]);
						msg += "<br><br>";
						msg += __("Please add it to your TaxJar account at {0} to enable tax calculation for this state.", [
							'<a href="https://app.taxjar.com/account#states" target="_blank">https://app.taxjar.com/account#states</a>'
						]);
						
						frappe.msgprint({
							title: __("Nexus Missing"),
							message: msg,
							indicator: "orange"
						});
					}
				}
			});
		}
	}
});
