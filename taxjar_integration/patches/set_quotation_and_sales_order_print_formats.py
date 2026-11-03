from taxjar_integration.install import set_default_print_format


def execute():
	"""Make the app's Quotation and Sales Order formats the defaults on an upgraded site.

	Only these two doctypes. The set_default_print_format patch already ran for
	Sales Invoice, and a site that cleared that default keeps it clear.
	"""
	set_default_print_format(("Quotation", "Sales Order"))
