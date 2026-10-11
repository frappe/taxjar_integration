import inspect
from contextlib import ExitStack
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from taxjar_integration.telemetry import csat

USER = "csat-test-user@example.com"
MODULE = "taxjar_integration.telemetry.csat"


class TestCsatSurvey(IntegrationTestCase):
	def setUp(self):
		for key in (csat.ASKED_ON, csat.CLOSED_ON, csat.ANSWERED, csat.OPTED_OUT):
			frappe.defaults.clear_user_default(key, USER)

		self.stack = ExitStack()
		self.pulse = self.patch("is_pulse_enabled", return_value=True)
		self.set_up = self.patch("_taxjar_is_set_up", return_value=True)
		self.used = self.patch("_site_has_used_taxjar", return_value=True)
		self.roles = self.stack.enter_context(patch("frappe.get_roles", return_value=["Accounts User"]))
		self.site_capture = self.patch("capture")
		self.survey = csat.CsatSurvey(USER)

	def tearDown(self):
		self.stack.close()

	def patch(self, name, **kwargs):
		return self.stack.enter_context(patch(f"{MODULE}.{name}", **kwargs))

	def answers(self):
		"""The properties of each taxjar_csat_submitted event sent."""
		return [c.kwargs for c in self.site_capture.call_args_list if c.args == ("taxjar_csat_submitted",)]

	def test_due_when_the_site_used_taxjar_and_the_user_has_a_taxjar_role(self):
		self.assertTrue(self.survey.is_due())

	def test_not_due_when_telemetry_is_off(self):
		self.pulse.return_value = False
		self.assertFalse(self.survey.is_due())

	def test_not_due_before_taxjar_setup_is_finished(self):
		self.set_up.return_value = False
		self.assertFalse(self.survey.is_due())

	def test_not_due_before_the_site_used_taxjar(self):
		self.used.return_value = False
		self.assertFalse(self.survey.is_due())

	def test_due_for_a_system_manager(self):
		self.roles.return_value = ["System Manager"]
		self.assertTrue(self.survey.is_due())

	def test_not_due_for_a_user_without_a_taxjar_role(self):
		self.roles.return_value = ["Sales User"]
		self.assertFalse(self.survey.is_due())

	def test_shown_starts_one_cycle_and_sends_one_site_event(self):
		self.survey.record("shown")
		self.survey.record("shown")

		self.site_capture.assert_called_once_with("taxjar_csat_shown", survey="csat")
		self.assertTrue(self.survey.is_due())

	def test_submitted_sends_the_score_and_closes_the_cycle(self):
		self.survey.record("shown")
		self.survey.record("submitted", "5")

		self.assertEqual(self.answers(), [{"survey": "csat", "score": 5}])
		self.assertFalse(self.survey.is_due())

	def test_a_comment_goes_with_the_answer(self):
		self.survey.record("shown")
		self.survey.record("submitted", 4, "Works well")

		self.assertEqual(self.answers(), [{"survey": "csat", "score": 4, "comment": "Works well"}])

	def test_a_score_outside_one_to_five_is_refused(self):
		self.survey.record("shown")
		with self.assertRaises(frappe.ValidationError):
			self.survey.record("submitted", 7)
		self.assertEqual(self.answers(), [])

	def test_a_submit_without_an_open_cycle_sends_nothing(self):
		self.survey.record("submitted", 4)
		self.assertEqual(self.answers(), [])

	def test_dismissed_is_a_site_event_and_hides_the_card(self):
		self.survey.record("shown")
		self.survey.record("dismissed")

		self.site_capture.assert_called_with("taxjar_csat_dismissed", survey="csat", permanent=False)
		self.assertEqual(self.answers(), [])
		self.assertFalse(self.survey.is_due())

	def test_opted_out_never_asks_again(self):
		self.survey.record("shown")
		self.survey.record("opted_out")

		self.site_capture.assert_called_with("taxjar_csat_dismissed", survey="csat", permanent=True)
		with patch(f"{MODULE}.today", return_value=add_days(today(), 400)):
			self.assertFalse(self.survey.is_due())

	def test_a_sent_score_comes_back_after_the_longer_wait(self):
		self.survey.record("shown")
		self.survey.record("submitted", 4)

		wait = csat.ASK_AFTER_ANSWER_DAYS
		with patch(f"{MODULE}.today", return_value=add_days(today(), wait - 1)):
			self.assertFalse(self.survey.is_due())
		with patch(f"{MODULE}.today", return_value=add_days(today(), wait)):
			self.assertTrue(self.survey.is_due())

	def test_a_new_cycle_forgets_the_last_answer(self):
		"""After an answer, a card that is then closed waits the shorter time."""
		self.survey.record("shown")
		self.survey.record("submitted", 4)

		later = add_days(today(), csat.ASK_AFTER_ANSWER_DAYS)
		with patch(f"{MODULE}.today", return_value=later):
			self.survey.record("shown")
			self.survey.record("dismissed")
		with patch(f"{MODULE}.today", return_value=add_days(later, csat.ASK_AGAIN_AFTER_DAYS)):
			self.assertTrue(self.survey.is_due())

	def test_a_closed_card_comes_back_after_the_wait(self):
		self.survey.record("shown")
		self.survey.record("dismissed")

		wait = csat.ASK_AGAIN_AFTER_DAYS
		with patch(f"{MODULE}.today", return_value=add_days(today(), wait - 1)):
			self.assertFalse(self.survey.is_due())
		with patch(f"{MODULE}.today", return_value=add_days(today(), wait)):
			self.assertTrue(self.survey.is_due())

	def test_an_ignored_card_closes_and_comes_back_after_the_wait(self):
		self.survey.record("shown")

		ended = csat.OPEN_FOR_DAYS
		with patch(f"{MODULE}.today", return_value=add_days(today(), ended)):
			self.assertFalse(self.survey.is_due())
		with patch(f"{MODULE}.today", return_value=add_days(today(), ended + csat.ASK_AGAIN_AFTER_DAYS)):
			self.assertTrue(self.survey.is_due())

	def test_an_unknown_action_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.survey.record("liked")

	def test_the_survey_never_sends_a_user_id(self):
		"""The dialog tells users that their feedback is anonymous."""
		self.assertNotIn("capture_for_user", inspect.getsource(csat))

	def test_record_csat_uses_no_reserved_parameter_name(self):
		"""frappe.call() deletes `flags` and `ignore_permissions` before the method sees them."""
		params = set(inspect.signature(csat.record_csat).parameters)
		self.assertFalse(params & {"flags", "ignore_permissions"})


class TestSiteHasUsedTaxJar(IntegrationTestCase):
	"""What counts as use: a TaxJar tax calculation on any sales document, or a synced invoice."""

	def used_with(self, found):
		def exists(doctype, filters):
			return any(doctype == dt and all(filters.get(k) == v for k, v in f.items()) for dt, f in found)

		with patch(f"{MODULE}.frappe.db.exists", side_effect=exists):
			return csat._site_has_used_taxjar()

	def test_a_calculated_quotation_counts(self):
		self.assertTrue(self.used_with([("Quotation", {"taxjar_has_nexus": 1})]))

	def test_a_synced_invoice_counts(self):
		self.assertTrue(self.used_with([("Sales Invoice", {"taxjar_sync_status": "Synced"})]))

	def test_nothing_calculated_or_synced_does_not_count(self):
		self.assertFalse(self.used_with([]))
