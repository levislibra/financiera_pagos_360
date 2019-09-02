# -*- coding: utf-8 -*-
from openerp import http

# class FinancieraPagos360(http.Controller):
#     @http.route('/financiera_pagos_360/financiera_pagos_360/', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/financiera_pagos_360/financiera_pagos_360/objects/', auth='public')
#     def list(self, **kw):
#         return http.request.render('financiera_pagos_360.listing', {
#             'root': '/financiera_pagos_360/financiera_pagos_360',
#             'objects': http.request.env['financiera_pagos_360.financiera_pagos_360'].search([]),
#         })

#     @http.route('/financiera_pagos_360/financiera_pagos_360/objects/<model("financiera_pagos_360.financiera_pagos_360"):obj>/', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('financiera_pagos_360.object', {
#             'object': obj
#         })