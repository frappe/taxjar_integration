from taxjar_integration.install import set_default_print_format


def execute():
	"""Make the app's print format the Sales Invoice default on an upgraded site.

	A new site gets it from after_install(). Installing an app records every
	patch as done without running it, so this patch reaches only a site that
	had the app before.
	"""
	set_default_print_format()
