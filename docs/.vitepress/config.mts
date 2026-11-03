import { defineConfig } from 'vitepress'
import { tabsMarkdownPlugin } from 'vitepress-plugin-tabs'
import { withMermaid } from 'vitepress-plugin-mermaid'
import { base, pageHead, siteUrl, writeDiscoveryFiles } from './seo'

const description = 'US sales tax for ERPNext, calculated by TaxJar and filed with AutoFile.'

// The sidebar follows the reader's journey: start, setting up, sales tax, transaction sync, sales adjustments,
// tax exemptions, tax return filing, troubleshoot. Reference pages come last.
const sidebar = [
	{
		text: 'Getting Started',
		items: [
			{ text: 'Introduction', link: '/getting-started/introduction' },
			{ text: 'Walkthrough', link: '/getting-started/walkthrough' },
			{ text: 'Installation', link: '/getting-started/installation' },
		],
	},
	{
		text: 'Setting Up',
		items: [
			{ text: 'Guided Setup', link: '/setting-up/guided-setup' },
			{ text: 'Roles & Permissions', link: '/setting-up/roles-and-permissions' },
			{ text: 'Updating your nexus', link: '/setting-up/updating-your-nexus' },
			{ text: 'Address Validation', link: '/setting-up/address-validation' },
			{ text: 'Before you go live', link: '/setting-up/before-you-go-live' },
		],
	},
	{
		text: 'Sales Tax',
		items: [
			{ text: 'Tax Computation', link: '/sales-tax/tax-computation' },
			{ text: 'Verify Tax Applicability', link: '/sales-tax/verify-tax-applicability' },
			{ text: 'Additional Charges & Discounts', link: '/sales-tax/additional-charges-and-discounts' },
			{ text: 'Print Format', link: '/sales-tax/print-format' },
		],
	},
	{
		text: 'Transaction Sync',
		items: [
			{ text: 'Syncing to TaxJar', link: '/transaction-sync/syncing-to-taxjar' },
			{ text: 'Resolve Failed Syncs', link: '/transaction-sync/resolve-failed-syncs' },
		],
	},
	{
		text: 'Sales Adjustments',
		items: [
			{ text: 'Credit & Debit Notes', link: '/sales-adjustments/credit-and-debit-notes' },
			{ text: 'Cancellations & Amendments', link: '/sales-adjustments/cancellations-and-amendments' },
		],
	},
	{
		text: 'Tax Exemptions',
		items: [
			{ text: 'Customer Tax Exemption', link: '/tax-exemptions/customer-tax-exemption' },
			{ text: 'Transaction Tax Exemption', link: '/tax-exemptions/transaction-tax-exemption' },
			{ text: 'Item Tax Exemption', link: '/tax-exemptions/item-tax-exemption' },
		],
	},
	{
		text: 'Tax Return Filing',
		items: [
			{ text: 'Period Close & Filing', link: '/tax-return-filing/period-close-and-filing' },
		],
	},
	{
		text: 'Troubleshoot',
		items: [
			{ text: 'Missing Sales Tax', link: '/troubleshoot/missing-sales-tax' },
			{ text: 'Messages & Errors', link: '/troubleshoot/messages-and-errors' },
			{ text: 'API Log', link: '/troubleshoot/api-log' },
		],
	},
	{
		text: 'Reference',
		collapsed: true,
		items: [
			{ text: 'Scheduled Jobs', link: '/reference/scheduled-jobs' },
			{ text: 'TaxJar Pages & Settings', link: '/reference/taxjar-pages-and-settings' },
			{ text: 'Upgrade from Version 15', link: '/reference/upgrade-from-version-15' },
			{ text: 'Usage Data & Feedback', link: '/reference/usage-data-and-feedback' },
			{ text: 'Glossary', link: '/reference/glossary' },
		],
	},
]

// withMermaid draws ```mermaid code blocks as diagrams.
export default withMermaid(defineConfig({
	srcDir: 'src',
	// Parts are included into pages. They are not pages.
	srcExclude: ['parts/**'],
	title: 'TaxJar Integration',
	// Search results show about 60 characters of a title. The suffix holds the two
	// words that people search with. scripts/lint.py reads it to check the length.
	titleTemplate: ':title | TaxJar for ERPNext',
	description,
	lang: 'en-US',
	base,
	cleanUrls: true,
	lastUpdated: false,
	// Search and discovery: see seo.ts. The sitemap needs the public address.
	sitemap: siteUrl ? { hostname: `${siteUrl}/` } : undefined,
	transformHead: ({ pageData }) => pageHead(pageData),
	buildEnd: (siteConfig) => writeDiscoveryFiles(siteConfig, sidebar, description),
	// Content tabs: :::tabs with == Live and == Sandbox.
	markdown: {
		// A ::: tip or ::: info with no title shows an icon in place of the word
		// "TIP" or "INFO". See custom.css.
		container: {
			tipLabel: '<span class="tip-icon" role="img" aria-label="Tip"></span>',
			infoLabel: '<span class="tip-icon info-icon" role="img" aria-label="Info"></span>',
		},
		config(md) {
			md.use(tabsMarkdownPlugin)
		},
	},
	head: [['link', { rel: 'icon', type: 'image/png', href: `${base}logo.png` }]],
	themeConfig: {
		logo: '/logo.png',
		nav: [
			{ text: 'Setting Up', link: '/setting-up/guided-setup' },
			{ text: 'Troubleshoot', link: '/troubleshoot/messages-and-errors' },
		],
		sidebar,
		outline: { level: [2, 3], label: 'On this page' },
		search: { provider: 'local' },
		docFooter: { prev: 'Previous', next: 'Next' },
		footer: {
			message: 'For the TaxJar Integration app for ERPNext version 16.',
		},
	},
	vite: {
		// Mermaid 11 uses fastdom, an old-style module. The Mermaid plugin does not
		// pre-bundle it, so the dev server cannot load it without this line.
		optimizeDeps: { include: ['mermaid > fastdom', 'mermaid > fastdom/extensions/fastdom-promised.js'] },
	},
}))
