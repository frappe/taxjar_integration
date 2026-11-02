# Style guide for the TaxJar docs, version 2

This file is for the people who write these docs. VitePress does not publish it.

## Readers and version

| Reader | Goal | Prior knowledge |
|---|---|---|
| Implementer or finance lead (TaxJar Manager) | Set up TaxJar once, keep it correct | Knows ERPNext accounts and roles. Does not know TaxJar. |
| Accountant (TaxJar User) | Invoice, fix sync problems, close the period | Knows ERPNext invoices. Knows sales tax a little. |
| Sales user | Make quotations and orders with the correct tax | Knows ERPNext selling. Needs to know nothing about TaxJar. |

Product version: the TaxJar Integration app for ERPNext version 16, commit `521751a` (2026-11-01) on `upstream/develop`. It holds all of `ux-improvements` and `fix-sandbox-address-check`, and `b1ba1a1` from `fix-tax-cache-month`. The source code is the truth for every label, status and message.

## Structure

- Sections follow the journey: Getting Started, Setting Up, Sales Tax, Transaction Sync, Sales Adjustments, Tax Exemptions, Tax Return Filing, Troubleshoot, Reference.
- Each page has one Diátaxis type. The type is in the frontmatter as `type`.
- Each shared fact has one owner page. Other pages link to it.

| Fact | Owner page |
|---|---|
| Every message and error, with its fix | `/help/messages` |
| Sync statuses and exclusion reasons | `/invoice/how-sync-works#sync-statuses` |
| Roles and the rights for each task | `/setup/access` |
| Schedules: nexus update, category update, retries, log cleanup | `/reference/scheduled-jobs` |
| What TaxJar uses to calculate the tax | `/sell/how-tax-is-calculated` |
| Live mode and Sandbox mode | `/setup/go-live` |

## Terms

| Use | Do not use | Meaning |
|---|---|---|
| sales tax | taxes, tax amount (alone) | The US tax on a sale. |
| nexus state | nexus region (except in a UI label) | A state where you must collect sales tax. |
| API token | API key, access token | The token from TaxJar for one company and one mode. |
| Live mode, Sandbox mode | production, test mode | The two API modes. |
| sync, send to TaxJar | push, upload | The app sends a submitted document to TaxJar. |
| TaxJar Setup | wizard, onboarding | The guided setup page. |
| transaction | order (alone) | An invoice, credit note or debit note in TaxJar. |
| exemption | exception | A customer or a sale that pays no sales tax. |
| TaxJar Manager, TaxJar User | admin, operator | The two personas. |

## Editorial patterns

These patterns come from the review of the docs in November 2026. Follow them on every page.

1. **Names:** short nouns in Title Case, with "&" in place of "and". Use the app's own terms, for example "Customer Tax Exemption". No "Step x:" in headings. The page heading is the same as the sidebar name.
2. **Group by feature, not by document type.** Merge pages that cover the same thing. Keep a reference table next to its feature, not in Reference.
3. **Openers:** one plain line about the purpose, with no background. Use "Pre-requisites", not "Before you start".
4. **Visual first:** the screenshot or the video comes before the text. Use real app screenshots, and remove noise from them. A video part for each step has a start time, an end time and a thumbnail.
5. **Tabs and rails:** parallel items go in tabs. Tab names have no numbers and fit on one row; split the tabs into groups when they do not fit. Sequential steps go in a collapsible rail (`<ol class="steps">` with `<details>`). Inside a tab or a rail step, use bold labels, not headings.
6. **Short text:** few numbered steps, at most one note, no repetition. Leave out rare facts.
7. **No endings:** no "Related", "Next steps" or "Change it later" sections. No transcripts, and no labels above videos.
8. **Few tips:** use a tip box only for a fact that prevents a mistake.

## Page rules

- Frontmatter: `title`, `description` (150 to 160 characters), `type`. Quote every value.
- `title` is the page name. Add a search word only when the name alone is not clear, for example "TaxJar API Log". VitePress adds " | TaxJar for ERPNext", and the full title is 60 characters or fewer. The home page has `titleTemplate: false`. The lint checks the length.
- One H1. Then H2, H3, H4 in order.
- A how-to page starts with "Pre-requisites" when the reader needs something first.
- Callouts: `::: tip`, `::: warning`, `::: danger` (for data loss or a filed return only), `::: info`.
- Images: `/images/<name>.webp`, with alt text that says what the image shows.
- Videos: `<YouTubeVideo id="..." title="..." />`, with no transcript. For one part of a video, add `:start="27" :end="53"` (seconds) and `thumbnail="/images/video-....webp"`, a frame from the clean render in `videos/`. The setup video is `2RnyQMNnjME` and the features video is `Y-ppuE5RsLg`, the same IDs as in `taxjar_setup.js`.
- Tabs: `:::tabs`, then one `== Name` line for each tab, then `:::`. When a tab holds a callout, use `::::tabs` and `::::`, so that the callout's `:::` does not close the tabs. For Live and Sandbox tabs, add `key:mode` and put Live first, so that all such tab groups on the site change together.
- Links: descriptive text, site paths without `.md`.
- Field labels as in the UI, in bold. Empty table cells: `-`.
- No `{{ }}` and no bare `<tag>` in text. The only HTML is the collapsible rail: `<ol class="steps">`, each step `<li><details><summary><h3 id="...">Name</h3><span>Description</span></summary>`, the step content in Markdown, then `</details></li>`. The `h3` puts the step in the outline, and its `id` is the link target.

## URL map: old page to new page

| Old page (`docs/content/`) | New page or pages |
|---|---|
| `/` (index) | `/`, `/start/overview` |
| `/before-you-start` | `/setup/guided-setup#pre-requisites`, `/setup/go-live` |
| `/guided-setup` | `/setup/guided-setup` |
| `/nexus-and-product-categories` | `/setup/nexus`, `/setup/product-tax-categories` |
| `/customer-exemptions` | `/sell/exempt-customers` |
| `/sales-tax-on-documents` | `/sell/how-tax-is-calculated`, `/sell/check-the-tax`, `/setup/address-validation`, `/sell/exempt-a-sale`, `/sell/extra-charges`, `/sell/print` |
| `/invoices-and-credit-notes` | `/invoice/how-sync-works`, `/invoice/credit-and-debit-notes`, `/invoice/cancel-or-correct` |
| `/period-close-and-filing` | `/file/close-a-period`, `/file/fix-failed-syncs` |
| `/troubleshooting` | `/help/no-sales-tax`, `/help/messages`, `/help/api-log`, `/reference/screens` |
| `/roles-and-permissions` | `/setup/access` |
| `/upgrade-from-version-15` | `/setup/upgrade-from-v15` |
| `/usage-data-and-feedback` | `/reference/usage-data` |
| (new) | `/reference/scheduled-jobs`, `/reference/glossary` |

## Search and discovery

- `.vitepress/seo.ts` adds the search and AI-agent files. Set `DOCS_URL` to the public address, with its path, when you build the public site: `DOCS_URL=https://<host>/<path> npm run docs:build`.
- A build with `DOCS_URL` has canonical URLs, Open Graph tags, JSON-LD, `sitemap.xml` and a `robots.txt` that allows indexing.
- A build without `DOCS_URL` is a preview. Each page has `noindex`, and `robots.txt` disallows all pages.
- Every build writes `llms.txt`, `llms-full.txt` and a `.md` copy of each sidebar page for AI agents. A page that is not in the sidebar is not in these files.
- Search engines show the `title` and the `description` from the frontmatter. Keep them in the lengths of "Page rules", with the words that a reader types into a search.
