"""The CSAT survey: when to ask a user, and what to send to Pulse.

The survey state of each user is kept in user defaults on the server, not in
the browser. A survey "cycle" starts when the card first shows. The cycle ends
when the user sends a score or closes the card, or after OPEN_FOR_DAYS.

All survey events are site-level and have no user ID, because the survey
tells users that their feedback is anonymous. The user state above stays on
the site and never goes to Pulse.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, today
from frappe.utils.telemetry import is_pulse_enabled

from taxjar_integration.taxjar_integration.taxjar_integration import _is_taxjar_enabled
from taxjar_integration.taxjar_integration.telemetry import SCORES, capture

SURVEY = "csat"

# The TaxJar Manager and TaxJar User personas (docs/taxjar/09-roles-and-permissions.md).
ASK_ROLES = {"Accounts User", "Accounts Manager"}

MIN_SYNCED_INVOICES = 20
MIN_DAYS_OF_USE = 30
ASK_EVERY_DAYS = 90
OPEN_FOR_DAYS = 14

ASKED_ON = "taxjar_csat_asked_on"
CLOSED_ON = "taxjar_csat_closed_on"
OPTED_OUT = "taxjar_csat_opted_out"


@frappe.whitelist()
def get_csat_prompt() -> dict:
	"""Tell the sidebar if it must show the survey card to the current user."""
	if not CsatSurvey(frappe.session.user).is_due():
		return {"show": False}

	return {"show": True}


@frappe.whitelist(methods=["POST"])
def record_csat(action: str, score: int | None = None, comment: str | None = None):
	"""Record what the user did with the survey: shown, submitted, dismissed or opted_out."""
	CsatSurvey(frappe.session.user).record(action, score, comment)


class CsatSurvey:
	def __init__(self, user: str):
		self.user = user

	def is_due(self) -> bool:
		if not self._can_ask():
			return False
		if self._is_open():
			return True
		return self._next_cycle_reached() and _site_has_used_taxjar()

	def record(self, action: str, score=None, comment=None):
		handlers = {
			"shown": self._shown,
			"submitted": lambda: self._submitted(score, comment),
			"dismissed": self._dismissed,
			"opted_out": self._opted_out,
		}
		if action not in handlers:
			frappe.throw(_("Unknown survey action: {0}").format(action), title=_("Survey Not Recorded"))
		handlers[action]()

	def _shown(self):
		# Count a cycle once, however many pages the card shows on.
		if self._is_open() or not self.is_due():
			return
		self._set(ASKED_ON, today())
		frappe.defaults.clear_user_default(CLOSED_ON, self.user)
		capture("taxjar_csat_shown", survey=SURVEY)

	def _submitted(self, score, comment):
		score = cint(score)
		if score not in SCORES:
			frappe.throw(_("Choose a score from 1 to 5."), title=_("Survey Not Recorded"))
		if not self._is_open():
			return

		answer = {"survey": SURVEY, "score": score}
		if comment:
			# The telemetry gate cleans the text (FreeText) before it leaves the site.
			answer["comment"] = comment

		self._close()
		capture("taxjar_csat_submitted", **answer)

	def _dismissed(self):
		if not self._is_open():
			return
		self._close()
		capture("taxjar_csat_dismissed", survey=SURVEY, permanent=False)

	def _opted_out(self):
		self._set(OPTED_OUT, 1)
		if self._is_open():
			self._close()
		capture("taxjar_csat_dismissed", survey=SURVEY, permanent=True)

	def _can_ask(self) -> bool:
		# With telemetry off, an answer cannot go anywhere, so do not ask.
		return (
			is_pulse_enabled()
			and not cint(self._get(OPTED_OUT))
			and bool(ASK_ROLES & set(frappe.get_roles(self.user)))
			and _is_taxjar_enabled()
		)

	def _is_open(self) -> bool:
		asked_on = self._get(ASKED_ON)
		if not asked_on or self._get(CLOSED_ON):
			return False
		return getdate(today()) < getdate(add_days(asked_on, OPEN_FOR_DAYS))

	def _next_cycle_reached(self) -> bool:
		asked_on = self._get(ASKED_ON)
		return not asked_on or getdate(today()) >= getdate(add_days(asked_on, ASK_EVERY_DAYS))

	def _close(self):
		self._set(CLOSED_ON, today())

	def _get(self, key):
		return frappe.defaults.get_user_default(key, self.user)

	def _set(self, key, value):
		frappe.defaults.set_user_default(key, value, self.user)


def _site_has_used_taxjar() -> bool:
	"""The site sent enough invoices to TaxJar, over enough days, to judge the app."""
	synced = {"taxjar_sync_status": "Synced", "docstatus": 1}
	if frappe.db.count("Sales Invoice", synced) < MIN_SYNCED_INVOICES:
		return False

	first = frappe.db.get_value("Sales Invoice", synced, "creation", order_by="creation asc")
	return bool(first) and getdate(first) <= getdate(add_days(today(), -MIN_DAYS_OF_USE))
