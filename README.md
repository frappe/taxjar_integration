# TaxJar Integration

TaxJar Integration for ERPNext (Frappe/ERPNext v16).

This app calculates US sales tax using TaxJar, writes tax values back to ERPNext documents, and can create TaxJar order/refund transactions on submission/cancellation.

## Features

- Tax calculation hook on Quotation, Sales Order, and Sales Invoice validation.
- Optional TaxJar transaction creation on Sales Invoice submit.
- Optional TaxJar transaction deletion on Sales Invoice cancel.
- Product Tax Category support for item-level TaxJar product tax codes.
- Sandbox mode support.
- UI-visible API diagnostics via TaxJar API Log DocType.

## Version Compatibility

- Tested for Frappe/ERPNext v16.

## Installation

From your bench folder:

```bash
bench get-app taxjar_integration
bench --site <site-name> install-app taxjar_integration
bench --site <site-name> migrate
```

## Dependency Management

- Runtime dependencies are defined in [project.dependencies] in pyproject.toml.
- pyproject.toml is the only build definition; there is no setup.py.
- requirements.txt is a compatibility stub and not the source of truth.

## Basic Configuration

Open TaxJar Settings and configure:

- Enable Tax Calculation
- Sandbox Mode (optional, for testing)
- Live API Key or Sandbox API Key
- Company
- Tax Account Head
- Shipping Account Head
- Create TaxJar Transaction (optional)
- Enable TaxJar Logging (optional, enabled by default)

Notes:

- Tax Account Head should match the account where TaxJar tax is expected on invoices.
- If a static Sales Taxes and Charges template is auto-applied, it can override expected TaxJar behavior.

## How Tax Is Applied

- Hook entrypoint: validate event for Quotation, Sales Order, Sales Invoice.
- TaxJar payload uses company and customer shipping addresses plus item product tax codes.
- Returned tax is added/updated as an Actual tax row using Tax Account Head.
- Item fields tax_collectable and taxable_amount are populated from TaxJar breakdown where applicable.

## TaxJar API Log (UI)

Use TaxJar API Log in Desk to inspect calls and outcomes.

Logging behavior:

- When Enable TaxJar Logging is checked, TaxJar requests/responses/skips/errors are written to TaxJar API Log and file logs.
- When Enable TaxJar Logging is unchecked, tax logic still runs, but no new TaxJar log entries are written.

Each row captures:

- action: tax_for_order, create_order, create_refund, delete_order, etc.
- status: request, success, error, skipped
- reference_doctype/reference_name (when available)
- payload
- response
- error or skipped reason

Typical skipped reasons include:

- taxjar_calculate_tax is disabled
- company is not in a supported context for the request
- no nexus match for destination
- TaxJar client credentials not configured
- no matching sales tax amount for transaction creation

## Troubleshooting

If tax looks template-driven instead of TaxJar-driven:

1. Remove/default-disable static Sales Taxes and Charges template for the test case.
2. Ensure TaxJar Settings tax_account_head aligns with invoice tax account behavior.
3. Confirm destination address and nexus setup.
4. Confirm product tax category is present on item.
5. Check TaxJar API Log for request/response and skipped/error reason.

If code changes are not reflected:

```bash
bench --site <site-name> migrate
bench restart
```

## Contributing

Contributions are welcome.

Recommended workflow:

1. Fork the repository.
2. Create a feature branch.
3. Add or update tests where possible.
4. Run bench migrate and validate on a v16 site.
5. Open a pull request with clear reproduction steps and expected behavior.

## License

MIT