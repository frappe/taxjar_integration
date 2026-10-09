from unittest.mock import patch

from frappe.tests import IntegrationTestCase

from taxjar_integration.taxjar_integration import telemetry

FRAPPE_CAPTURE = "taxjar_integration.taxjar_integration.telemetry.frappe_capture"


class TestTelemetry(IntegrationTestCase):
	def test_drops_properties_that_are_not_in_the_event_schema(self):
		properties = telemetry.allowed_properties(
			"taxjar_csat_submitted", {"survey": "csat", "score": 4, "customer": "Acme Corp"}
		)
		self.assertEqual(properties, {"survey": "csat", "score": 4})

	def test_drops_values_that_the_schema_does_not_allow(self):
		properties = telemetry.allowed_properties(
			"taxjar_csat_submitted", {"survey": "pricing", "score": 9}
		)
		self.assertEqual(properties, {})

	def test_true_does_not_pass_as_the_score_one(self):
		properties = telemetry.allowed_properties("taxjar_csat_submitted", {"score": True})
		self.assertEqual(properties, {})

	def test_only_the_survey_comment_accepts_typed_text(self):
		"""Every other property is a fixed list of values or a boolean."""
		free_text = {
			(event, key)
			for event, schema in telemetry.EVENTS.items()
			for key, allowed in schema.items()
			if not (allowed is bool or isinstance(allowed, tuple))
		}
		self.assertEqual(free_text, {("taxjar_csat_submitted", "comment")})
		self.assertIsInstance(telemetry.EVENTS["taxjar_csat_submitted"]["comment"], telemetry.FreeText)

	def test_free_text_loses_its_html(self):
		comment = self.comment('<img src=x onerror="alert(1)"><b>Sync</b> is slow<script>x()</script>')
		self.assertNotIn("<", comment)
		self.assertNotIn("onerror", comment)
		self.assertIn("Sync is slow", comment)

	def test_free_text_loses_control_and_invisible_characters(self):
		# NUL, a zero-width space, and a right-to-left override, which can reorder what a reader sees.
		comment = self.comment("Good\x00 app\u200b\u202eevil\nSecond line")
		self.assertEqual(comment, "Good appevil\nSecond line")

	def test_free_text_is_cut_to_its_limit(self):
		self.assertEqual(len(self.comment("a" * 5000)), 1000)

	def test_free_text_that_is_empty_after_cleaning_is_dropped(self):
		properties = telemetry.allowed_properties("taxjar_csat_submitted", {"comment": "  <p></p> \u200b "})
		self.assertEqual(properties, {})

	def test_free_text_must_be_a_string(self):
		properties = telemetry.allowed_properties("taxjar_csat_submitted", {"comment": {"a": 1}})
		self.assertEqual(properties, {})

	def comment(self, text):
		return telemetry.allowed_properties("taxjar_csat_submitted", {"comment": text})["comment"]

	def test_site_events_have_no_person_id(self):
		with patch(FRAPPE_CAPTURE) as frappe_capture:
			telemetry.capture("taxjar_csat_shown", survey="csat")

		frappe_capture.assert_called_once_with(
			"taxjar_csat_shown", "taxjar_integration", user="Administrator", properties={"survey": "csat"}
		)

	def test_user_events_carry_the_session_user(self):
		with patch(FRAPPE_CAPTURE) as frappe_capture:
			telemetry.capture_for_user("taxjar_csat_shown", survey="csat")

		self.assertEqual(frappe_capture.call_args.kwargs["user"], "Administrator")
		self.assertEqual(frappe_capture.call_args.kwargs["properties"], {"survey": "csat"})

	def test_an_unknown_event_is_not_sent(self):
		with patch(FRAPPE_CAPTURE) as frappe_capture:
			telemetry.capture("taxjar_made_up_event")

		frappe_capture.assert_not_called()

	def test_a_capture_error_does_not_reach_the_caller(self):
		with patch(FRAPPE_CAPTURE, side_effect=RuntimeError("queue down")):
			telemetry.capture("taxjar_csat_shown", survey="csat")
