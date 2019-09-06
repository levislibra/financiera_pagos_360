# -*- coding: utf-8 -*-
{
    'name': "Financiera Pagos360",

    'summary': """
        Modulo para el cobro de cuotas con distintos medios de pago
        brindados por pagos360.com""",

    'description': """
        Medios de cobro de cuotas.
    """,

    'author': "Levis Libra",
    'website': "https://libra-soft.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/master/openerp/addons/base/module/module_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'financiera_prestamos'],

    # always loaded
    'data': [
        # 'security/ir.model.access.csv',
        'views/views.xml',
        'views/extends_res_company.xml',
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
}