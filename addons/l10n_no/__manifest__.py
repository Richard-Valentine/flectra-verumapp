# -*- coding: utf-8 -*-
# Part of Odoo, Flectra. See LICENSE file for full copyright and licensing details.

{
    "name" : "Norway - Accounting",
    "version" : "2.0",
    "author" : "Rolv Råen",
    'category': 'Accounting/Localizations/Account Charts',
    "description": """This is the module to manage the accounting chart for Norway in Odoo, Flectra.

Updated for Odoo 9 by Bringsvor Consulting AS <www.bringsvor.com>
""",
    "depends" : [
        "account",
        "base_iban",
        "base_vat",
    ],
    "data": ['data/l10n_no_chart_data.xml',
             'data/account_data.xml',
             'data/account_tax_report_data.xml',
             'data/account.account.template.csv',
             'data/account_tax_data.xml',
             'data/account_chart_template_data.xml',
             ],
     'demo': [
         'demo/demo_company.xml',
     ],
    "active": False,
    'post_init_hook': '_preserve_tag_on_taxes',
    'license': 'LGPL-3',
}
