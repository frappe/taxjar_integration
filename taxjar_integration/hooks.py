from . import __version__ as app_version

app_name = "taxjar_integration"
app_title = "TaxJar Integration"
app_icon = "octicon octicon-globe"
app_color = "#0b6e99"
app_publisher = " Frappe Technologies Pvt. Ltd."
app_description = "TaxJar Integration with ERPNext"
app_email = "hello@frappe.io"
app_license = "MIT"
app_logo_url = "/assets/taxjar_integration/images/taxjar-integration.svg"
app_home = "/app/taxjar-integration"

add_to_apps_screen = [
	{
		"name": app_name,
		"logo": app_logo_url,
		"title": "TaxJar Integration",
		"route": app_home,
	}
]

# Required Apps
required_apps = ["erpnext"]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
app_include_css = "taxjar_integration.bundle.css"
app_include_js = "taxjar_integration.bundle.js"

# include js, css files in header of web template
# web_include_css = "/assets/taxjar_integration/css/taxjar_integration.css"
# web_include_js = "/assets/taxjar_integration/js/taxjar_integration.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "taxjar_integration/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
	"Sales Invoice": "public/js/sales_invoice.js",
	"Quotation": "public/js/quotation.js",
	"Sales Order": "public/js/sales_order.js",
	"Address": "public/js/address.js",
	"Customer": "public/js/customer.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
#
# get_company_config: exposed so the "US Sales Tax Invoice" print format can
# identify which Sales Taxes and Charges row is the TaxJar sales-tax row and
# which is the shipping row (company_config.tax_account_head /
# shipping_account_head) without re-deriving that lookup in the template.
jinja = {
	"methods": [
		"taxjar_integration.taxjar_integration.taxjar_integration.get_company_config",
	],
}

# Installation
# ------------

# before_install = "taxjar_integration.install.before_install"
after_install = "taxjar_integration.install.after_install"
after_migrate = ["taxjar_integration.install.after_migrate"]

# Uninstallation
# ------------

# Split deliberately: before_uninstall still has this app's doctypes to read
# (TaxJar Settings says which companies to hand the tax templates back to);
# after_uninstall only touches core records. See uninstall.py.
before_uninstall = "taxjar_integration.uninstall.before_uninstall"
after_uninstall = "taxjar_integration.uninstall.after_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "taxjar_integration.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
#	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
#	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
#	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Sales Invoice": {
		"validate": "taxjar_integration.taxjar_integration.taxjar_integration.validate_return_against",
		"on_submit": "taxjar_integration.taxjar_integration.taxjar_integration.enqueue_taxjar_sync",
		"on_cancel": "taxjar_integration.taxjar_integration.taxjar_integration.enqueue_taxjar_delete",
	},
	("Quotation", "Sales Order", "Sales Invoice"): {
		"validate": ["taxjar_integration.taxjar_integration.taxjar_integration.set_sales_tax"],
		"onload": "taxjar_integration.taxjar_integration.taxjar_integration.set_taxjar_breakdown_html",
		"before_print": "taxjar_integration.taxjar_integration.taxjar_integration.set_taxjar_breakdown_html",
	},
	"Address": {
		"validate": "taxjar_integration.taxjar_integration.taxjar_integration.validate_address"
	},
	"Customer": {
		"validate": "taxjar_integration.taxjar_integration.taxjar_integration.on_customer_validate",
		"on_update": "taxjar_integration.taxjar_integration.taxjar_integration.on_customer_update",
		"on_trash": "taxjar_integration.taxjar_integration.taxjar_integration.on_customer_delete",
	},
	"Workspace": {
		"validate": "taxjar_integration.install.keep_guided_setup_alert",
	},
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"daily": [
		"taxjar_integration.taxjar_integration.tasks.purge_old_api_logs",
		"taxjar_integration.taxjar_integration.tasks.sync_nexus_list",
	],
	"weekly": [
		"taxjar_integration.taxjar_integration.tasks.sync_product_tax_categories",
	],
	"cron": {
		"*/15 * * * *": [
			"taxjar_integration.taxjar_integration.tasks.retry_failed_taxjar_syncs",
			"taxjar_integration.taxjar_integration.tasks.retry_failed_taxjar_customer_syncs",
		],
	},
}

# Testing
# -------

# before_tests = "taxjar_integration.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
#	"frappe.desk.doctype.event.event.get_events": "taxjar_integration.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
#	"Task": "taxjar_integration.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]


# Company deletion
# ----------------
#
# "Delete Company Transactions" (Transaction Deletion Record) collects every
# doctype with a Link to Company and deletes its rows for that company. Its
# collector applies no istable filter, so without this it reaches into the
# TaxJar Settings child tables and silently deletes the company's TaxJar
# configuration - credentials included - as though it were transaction data.
# It is configuration, and it outlives the transactions, so it is ignored here
# alongside ERPNext's own Mode of Payment Account / Item Default / Party
# Account entries.
company_data_to_be_ignored = [
	"TaxJar API Credential",
	"TaxJar Company Config",
	"TaxJar Nexus",
]

# Deliberately NOT declaring ignore_links_on_delete for "TaxJar Settings".
#
# Deleting a Company that is still configured for TaxJar is blocked, and the
# error names TaxJar Settings, which is the behaviour we want: these rows are a
# deliberate configuration choice, not an incidental log. frappe and erpnext
# reserve ignore_links_on_delete for records like Communication, Version and
# Tax Withholding Entry. Ignoring the link here would instead leave orphaned
# rows - including an encrypted API credential - pointing at a company that no
# longer exists.


# User Data Protection
# --------------------

user_data_fields = [
	{
		"doctype": "TaxJar API Log",
		"filter_by": "reference_name",
		"redact_fields": ["payload", "response"],
		"partial": 1,
	},
]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
#	"taxjar_integration.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
export_python_type_annotations = True