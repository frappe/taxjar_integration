"""Product analytics for the TaxJar app. Frappe telemetry sends the events to Pulse.

Frappe sends an event only when the site allows telemetry, so the System
Settings opt-out applies here with no extra code.

`capture` sends a site-level event as Administrator, a standard user that
Frappe does not hash into an ID. `capture_for_user` sends the pseudonymous ID of
the session user. The CSAT survey must use `capture` only, because it tells
users that their feedback is anonymous.

Each property must be in EVENTS (telemetry_events.py) with an allowed value or
type. The capture drops all other properties, so names and amounts cannot
reach Pulse. Telemetry never raises: a failure here must not stop a user's work.
"""

import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils import date_diff, get_app_version, getdate, today
from frappe.utils.telemetry import capture as frappe_capture
from frappe.utils.telemetry import is_pulse_enabled

from taxjar_integration.taxjar_integration.telemetry_events import (
	API_CALL_TYPES,
	BROWSER_EVENTS,
	COMMON,
	EVENTS,
	SCORES,
	SYNC_ERROR_REASONS,
	FreeText,
	Version,
)

__all__ = ["EVENTS", "SCORES", "FreeText", "capture", "capture_for_user", "capture_once", "track"]

APP = "taxjar_integration"

# A standard user. Frappe sends it as is, so the event has no user ID.
SITE_USER = "Administrator"

# Site defaults. The first records when TaxJar Setup was first finished; the
# second marks a once-per-site event as sent.
SETUP_FINISHED_ON = "taxjar_setup_finished_on"
SENT_PREFIX = "taxjar_telemetry_sent:"

# Redis hashes of counts, read and emptied by the daily snapshot: failed sync
# attempts by reason, and live API calls by type. In the cache and not on the
# documents: a count is all the snapshot needs, and a restart loses at most one
# day of counts.
COUNTERS_KEY = "taxjar_telemetry_counts:"


def capture(event: str, **properties):
	"""Send a site-level event, with no user ID."""
	_send(event, properties, user=SITE_USER)


def capture_for_user(event: str, **properties):
	"""Send an event with the pseudonymous ID of the session user.

	Never use it for the CSAT survey: the survey says that feedback is anonymous.
	"""
	_send(event, properties, user=frappe.session.user)


def capture_once(event: str, **properties):
	"""Send a site-level event the first time only, for example the first tax calculation.

	The event counts as sent only when telemetry is on, so a site that turns
	telemetry on later still sends its first events.
	"""
	if not _active():
		return
	try:
		key = SENT_PREFIX + event
		if frappe.db.get_default(key) or not is_pulse_enabled():
			return
		frappe.db.set_default(key, today())
	except Exception:
		frappe.logger("taxjar_telemetry").exception(f"Telemetry capture failed: {event}")
		return
	capture(event, **properties)


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=60, seconds=60)
def track(event: str, properties: dict | str | None = None):
	"""Send one of the few events that only the browser knows about (BROWSER_EVENTS)."""
	if event not in BROWSER_EVENTS:
		return
	properties = frappe.parse_json(properties) if isinstance(properties, str) else (properties or {})
	if isinstance(properties, dict):
		capture(event, **properties)


def count_sync_error(scope: str, reason: str):
	"""Count one failed sync attempt. scope is "invoice" or "customer"."""
	if reason in SYNC_ERROR_REASONS:
		_increment(f"{scope}_sync_errors", reason)


def take_sync_error_counts(scope: str) -> dict:
	"""The counts since the last call, by reason. Reading them sets them back to zero."""
	return _take(f"{scope}_sync_errors")


def count_api_call(call_type: str):
	"""Count one call to the live TaxJar API (API_CALL_TYPES)."""
	if call_type in API_CALL_TYPES:
		_increment("api_calls", call_type)


def take_api_call_counts() -> dict:
	"""The calls since the last call, by type. Reading them sets them back to zero."""
	return _take("api_calls")


def _increment(counter, field):
	if not _active():
		return
	try:
		if is_pulse_enabled():
			frappe.cache.pipeline().hincrby(_counter_key(counter), field, 1).execute()
	except Exception:
		frappe.logger("taxjar_telemetry").exception(f"Telemetry count failed: {counter}")


def _take(counter) -> dict:
	key = _counter_key(counter)
	counts, _deleted = frappe.cache.pipeline(transaction=True).hgetall(key).delete(key).execute()
	return {
		field.decode() if isinstance(field, bytes) else field: int(count) for field, count in counts.items()
	}


def _counter_key(counter):
	return frappe.cache.make_key(COUNTERS_KEY + counter)


def record_setup_finished():
	"""Keep the date of the first finished TaxJar Setup, for days_since_setup."""
	if _active() and not frappe.db.get_default(SETUP_FINISHED_ON):
		frappe.db.set_default(SETUP_FINISHED_ON, today())


def days_since_setup() -> int | None:
	finished_on = frappe.db.get_default(SETUP_FINISHED_ON)
	return date_diff(today(), getdate(finished_on)) if finished_on else None


def _active() -> bool:
	"""False during a test run, unless the test asks for telemetry.

	Test runs call the instrumented code thousands of times. Their events must
	not reach Pulse, and their once-per-site marks must not stay on the site.
	"""
	return not frappe.flags.in_test or bool(frappe.flags.taxjar_telemetry_in_test)


def _send(event, properties, user):
	if not _active():
		return
	if event not in EVENTS:
		# A code error, not a user error: log it and never break the user's action.
		frappe.logger("taxjar_telemetry").warning(f"Unknown telemetry event: {event}")
		return

	try:
		properties = {**_versions(), **properties}
		frappe_capture(event, APP, user=user, properties=allowed_properties(event, properties))
	except Exception:
		frappe.logger("taxjar_telemetry").exception(f"Telemetry capture failed: {event}")


def _versions() -> dict:
	return {"app_version": get_app_version(APP), "frappe_version": frappe.__version__}


def allowed_properties(event: str, properties: dict) -> dict:
	"""Keep only the properties that EVENTS (and COMMON) allow for the event, with text cleaned."""
	schema = {**COMMON, **EVENTS[event]}
	allowed = {}
	for key, value in properties.items():
		if key in schema:
			value = _allowed_value(value, schema[key])
			if value is not None:
				allowed[key] = value
	return allowed


def _allowed_value(value, allowed):
	"""The value to send, or None to drop it."""
	if isinstance(allowed, (FreeText, Version)):
		return allowed.clean(value)
	if allowed is bool:
		return value if isinstance(value, bool) else None
	# bool is a subclass of int, so True must not pass as the count 1 or the score 1.
	if isinstance(value, bool):
		return None
	if allowed is int:
		return value if isinstance(value, int) and value >= 0 else None
	return value if value in allowed else None
