// Sends the few analytics events that only the browser knows about.
//
// The server accepts only the events in BROWSER_EVENTS
// (taxjar_integration/taxjar_integration/telemetry_events.py), cleans the
// properties, and sends them to Pulse with no user ID. When telemetry is off,
// the server sends nothing.
if (!window.taxjar_integration) {
	window.taxjar_integration = {};
}

taxjar_integration.track = function (event, properties = {}) {
	if (!frappe.boot.enable_telemetry) return;

	frappe
		.xcall("taxjar_integration.taxjar_integration.telemetry.track", {
			event,
			properties,
		})
		// Analytics must never show an error or stop the user's work.
		.catch(() => {});
};
