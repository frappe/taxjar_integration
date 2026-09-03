from setuptools import setup, find_packages

# get version from __version__ variable in taxjar_integration/__init__.py
from taxjar_integration import __version__ as version

setup(
	name="taxjar_integration",
	version=version,
	description="Taxjar Integration with ERPNext",
	author=" Frappe Technologies Pvt. Ltd.",
	author_email="hello@frappe.io",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=["taxjar~=1.9.2"],
	python_requires=">=3.10"
)
