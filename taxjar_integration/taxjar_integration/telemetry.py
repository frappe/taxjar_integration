"""Product analytics for the TaxJar app. Frappe telemetry sends the events to Pulse.

Frappe sends an event only when the site allows telemetry, so the System
Settings opt-out applies here with no extra code.

`capture` sends a site-level event as Administrator, a standard user that
Frappe does not hash into an ID. `capture_for_user` sends the pseudonymous ID of
the session user. The CSAT survey must use `capture` only, because it tells
users that their feedback is anonymous.

Each property must be in EVENTS with an allowed value or type. The capture drops
all other properties, so names and amounts cannot reach Pulse. Text that a user
typed is allowed only where EVENTS says FreeText, and the gate cleans it first.
"""

import unicodedata

import frappe
from frappe.utils import strip_html
from frappe.utils.telemetry import capture as frappe_capture

APP = "taxjar_integration"

# A standard user. Frappe sends it as is, so the event has no user ID.
SITE_USER = "Administrator"

SURVEYS = ("csat",)
SCORES = (1, 2, 3, 4, 5)


class FreeText:
	"""A property that holds text that a user typed and chose to send.

	Pulse and Insights can show the text, so the gate removes HTML and control
	characters before it leaves the site. Control characters include zero-width
	and text-direction characters, which can hide or reorder what a reader sees.
	"""

	def __init__(self, max_length: int):
		self.max_length = max_length

	def clean(self, value) -> str | None:
		if not isinstance(value, str):
			return None
		text = "".join(
			char for char in strip_html(value) if char in "\n\t" or unicodedata.category(char)[0] != "C"
		)
		return text.strip()[: self.max_length].strip() or None


# Each event, its properties, and the allowed values (a tuple), type or FreeText.
EVENTS = {
	"taxjar_csat_shown": {"survey": SURVEYS},
	"taxjar_csat_submitted": {
		"survey": SURVEYS,
		"score": SCORES,
		"comment": FreeText(max_length=1000),
	},
	"taxjar_csat_dismissed": {"survey": SURVEYS, "permanent": bool},
}


def capture(event: str, **properties):
	"""Send a site-level event, with no user ID."""
	_send(event, properties, user=SITE_USER)


def capture_for_user(event: str, **properties):
	"""Send an event with the pseudonymous ID of the session user.

	Never use it for the CSAT survey: the survey says that feedback is anonymous.
	"""
	_send(event, properties, user=frappe.session.user)


def _send(event, properties, user):
	if event not in EVENTS:
		# A code error, not a user error: log it and never break the user's action.
		frappe.logger("taxjar_telemetry").warning(f"Unknown telemetry event: {event}")
		return

	try:
		frappe_capture(event, APP, user=user, properties=allowed_properties(event, properties))
	except Exception:
		frappe.logger("taxjar_telemetry").exception(f"Telemetry capture failed: {event}")


def allowed_properties(event: str, properties: dict) -> dict:
	"""Keep only the properties that EVENTS allows for the event, with text cleaned."""
	schema = EVENTS[event]
	allowed = {}
	for key, value in properties.items():
		if key in schema:
			value = _allowed_value(value, schema[key])
			if value is not None:
				allowed[key] = value
	return allowed


def _allowed_value(value, allowed):
	"""The value to send, or None to drop it."""
	if isinstance(allowed, FreeText):
		return allowed.clean(value)
	if allowed is bool:
		return value if isinstance(value, bool) else None
	# bool is a subclass of int, so True must not pass as the score 1.
	return value if not isinstance(value, bool) and value in allowed else None
