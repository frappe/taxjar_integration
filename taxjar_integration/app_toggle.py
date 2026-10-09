"""Take this app off the site's forms and books while the site disables it, and put it
back when the site enables it again.

A disabled app keeps its schema and its data. The site only stops the app from taking
effect. Frappe drops the app from ``get_active_apps()``, so the workspace, the sidebar,
the scheduled jobs and the ``doc_events`` go quiet on their own.

Two things do not, and this module handles both.

**The customizations.** setup_taxjar() writes Custom Fields and Property Setters onto
doctypes this app does not own - Sales Invoice, Quotation, Sales Order, their item
tables, Customer, Item and Address. Those rows belong to the core doctypes, so nothing
removes them when the app goes quiet. A site that disables the app would keep the
``taxjar_*`` fields on every sales form. It would also keep ERPNext's own
``exempt_from_sales_tax`` checkbox hidden, behind a Property Setter this app wrote.

``frappe.custom.hide_customizations()`` sets ``is_app_disabled`` on those rows. The rows
and their data stay in the database. ``unhide_customizations()`` clears the flag again.
Both throw if the site has no ``is_app_disabled`` column yet, which means the site needs
``bench migrate`` first.

**The tax templates.** _upsert_tax_template() makes "TaxJar Sales Tax - {abbr}" the
company default, and _disable_default_us_templates() disables ERPNext's own US ST 6% /
4% / 6.25% for that company. The template's tax row is an "Actual" placeholder that
set_sales_tax() fills in on save. That hook stops running when the app goes quiet, and
nothing else fills the row. So a disabled site would submit invoices carrying a $0 sales
tax line, with ERPNext's own templates disabled behind it, and throw nothing at all. A
silent failure is harder to find than an error, which is why this module undoes it.

The hand-back is uninstall.py's restore_default_tax_templates(), reused whole. The
return is regional/united_states.py's sync_all_company_tax_templates(), the same
function setup_taxjar() calls. Neither is written for this module, so neither can drift
from the install and uninstall paths.

One consequence to know about. The hand-back re-enables ERPNext's three US templates but
makes none of them default, because nothing recorded which one was default before TaxJar
took over. So a disabled site has no default sales tax template until an admin picks
one. An empty taxes table reads as unfinished, which a $0 row does not.

Frappe defines four hooks around the switch: ``before_disable``, ``after_disable``,
``before_enable`` and ``after_enable``. This app declares two of them, the pair frappe's
own hooks.md names for this job:

* ``before_disable`` runs while the app is still active, so it can still read TaxJar
  Company Config to learn which companies to hand back.
* ``after_enable`` runs once the app is active again, so company_scope() reads the live
  "Calculate Sales Tax" answer rather than the one a disabled app gives.

The other two have no work here, so this app leaves them undeclared.

``bench migrate`` runs ``before_disable`` again for every disabled app. It has to:
migrate calls ``after_migrate`` for every *installed* app, disabled ones included, so
setup_taxjar() runs, ``make_property_setter()`` writes a fresh row with the flag clear,
and sync_all_company_tax_templates() re-defaults the TaxJar template.
frappe.installer.reapply_disabled_app_state() then runs this module again, at the end of
post_schema_updates, and undoes both. A migrate on a disabled site churns, and it ends
correct. So ``before_disable`` must give the same result on every run. It does: both
halves only write values that are already true on a second pass.
"""

from frappe.custom import hide_customizations, unhide_customizations

from taxjar_integration.taxjar_integration.doctype.taxjar_settings.taxjar_settings import (
	get_custom_fields,
)
from taxjar_integration.taxjar_integration.regional.united_states import (
	sync_all_company_tax_templates,
)

# The same list uninstall.py deletes, and the same hand-back it runs. One copy of each,
# so a Property Setter added to install later cannot reach one of the paths that undo it
# and miss the other.
from taxjar_integration.uninstall import _PROPERTY_SETTERS, restore_default_tax_templates


def before_disable():
	# The templates first, the same order uninstall.py splits its two hooks in: the
	# hand-back is the half that reads this app's own doctypes.
	restore_default_tax_templates()
	hide_customizations(get_customizations())


def after_enable():
	unhide_customizations(get_customizations())
	# Per company, and per its own "Calculate Sales Tax" flag, so a company that had the
	# flag off while the app was disabled does not gain a default template here. Each row
	# is isolated: one company that cannot resolve its ledgers logs an error rather than
	# failing the enable for the whole site.
	sync_all_company_tax_templates()


def get_customizations():
	"""Return every customization this app writes onto a doctype it does not own.

	The shape is the one frappe.custom expects: each customization doctype maps to a
	list of row filters. Every filter names one doctype, because frappe rejects a
	filter without one - it would reach another app's rows on the same table.

	Each filter also names the field. A filter of ``{"dt": "Sales Invoice"}`` alone
	would hide every Custom Field on Sales Invoice, including fields other apps and the
	site's own users wrote.

	Custom DocPerm rows are not here. The app writes none: the rights on its own
	doctypes live in their JSON, and Frappe conceals a disabled app's own doctypes
	whole.
	"""
	return {
		"Custom Field": [
			{"dt": doctype, "fieldname": field["fieldname"]}
			for doctype, fields in get_custom_fields().items()
			for field in fields
		],
		"Property Setter": [
			{"doc_type": doctype, "field_name": fieldname, "property": prop}
			for doctype, fieldname, prop in _PROPERTY_SETTERS
		],
	}
