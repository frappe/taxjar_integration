---
title: "Installation"
description: "Install the TaxJar Integration app on Frappe Cloud, with Docker or with bench, and see what the app adds to your ERPNext site when you install it."
type: "how-to"
---

# Installation

Install the app from the branch that matches your Frappe and ERPNext branch. Use **Version 16** for a live site.

| Branch | Frappe Framework | ERPNext | Python |
| --- | --- | --- | --- |
| **Version 16** | 16.50.0 or later | 16.52.0 or later | 3.14 or later |
| **Develop** | `develop` | `develop` | 3.14 or later |

## Frappe Cloud

If you do not have a Frappe site yet, Frappe Cloud is the quickest way to start. The app is not in the Frappe Cloud marketplace, so you add it from GitHub.

:::tabs key:branch
== Version 16
1. Sign up on [Frappe Cloud](https://cloud.frappe.io/dashboard/signup) and create a bench group with the version **Version 16**.
2. Add ERPNext to the bench group.
3. Add the TaxJar Integration app from GitHub: `https://github.com/frappe/taxjar_integration`, branch `version-16`.
4. Deploy the bench group, then create a site on it with ERPNext and TaxJar Integration.
== Develop
1. Sign up on [Frappe Cloud](https://cloud.frappe.io/dashboard/signup) and create a bench group with the version **Nightly**. Nightly is the `develop` branch.
2. Add ERPNext to the bench group.
3. Add the TaxJar Integration app from GitHub: `https://github.com/frappe/taxjar_integration`, branch `develop`.
4. Deploy the bench group, then create a site on it with ERPNext and TaxJar Integration.
:::

## Docker

To run the app with Docker, build a custom image. In the [frappe_docker](https://github.com/frappe/frappe_docker) folder, create an `apps.json` file, then build the image.

:::tabs key:branch
== Version 16
```json
[
  {
    "url": "https://github.com/frappe/erpnext",
    "branch": "version-16"
  },
  {
    "url": "https://github.com/frappe/taxjar_integration",
    "branch": "version-16"
  }
]
```

```bash
docker build \
 --no-cache \
 --build-arg=FRAPPE_PATH=https://github.com/frappe/frappe \
 --build-arg=FRAPPE_BRANCH=version-16 \
 --secret=id=apps_json,src=apps.json \
 --tag=custom:taxjar \
 --file=images/layered/Containerfile .
```
== Develop
```json
[
  {
    "url": "https://github.com/frappe/erpnext",
    "branch": "develop"
  },
  {
    "url": "https://github.com/frappe/taxjar_integration",
    "branch": "develop"
  }
]
```

```bash
docker build \
 --no-cache \
 --build-arg=FRAPPE_PATH=https://github.com/frappe/frappe \
 --build-arg=FRAPPE_BRANCH=develop \
 --secret=id=apps_json,src=apps.json \
 --tag=custom:taxjar \
 --file=images/layered/Containerfile .
```
:::

For the other options, refer to the [Frappe Docker build guide](https://github.com/frappe/frappe_docker/blob/main/docs/02-setup/02-build-setup.md).

## Manual

If you run your own bench, follow the [Frappe installation guide](https://docs.frappe.io/framework/user/en/installation) first. Then make a bench with Frappe and ERPNext, and get the app:

:::tabs key:branch
== Version 16
```bash
bench init --frappe-branch version-16 frappe-bench
cd frappe-bench
bench get-app --branch version-16 erpnext
bench get-app --branch version-16 https://github.com/frappe/taxjar_integration
```
== Develop
```bash
bench init --frappe-branch develop frappe-bench
cd frappe-bench
bench get-app --branch develop erpnext
bench get-app --branch develop https://github.com/frappe/taxjar_integration
```
:::

Install the app on your site, and migrate:

```bash
bench --site [site name] install-app taxjar_integration
bench --site [site name] migrate
```

## What the app adds to your site

When you install the app, it adds these items:

- The **TaxJar** app on the ERPNext apps screen, with a banner that opens TaxJar Setup.
- TaxJar fields on items, addresses, quotations, sales orders and sales invoices.
- The product tax categories from TaxJar, about 800 codes.
- The print format **US Sales Tax (Invoice, DN, CN)**. Refer to [Print Format](/sales-tax/print-format).

The app does not calculate tax until you connect a company in TaxJar Setup.

::: tip Need help?
If the installation fails, [open an issue on GitHub](https://github.com/frappe/taxjar_integration/issues/new). If the site has TaxJar version 15, refer to [Upgrade from Version 15](/reference/upgrade-from-version-15).
:::
