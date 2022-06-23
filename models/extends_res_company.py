# -*- coding: utf-8 -*-

from openerp import models, fields, api

class ExtendsResCompany(models.Model):
	_name = 'res.company'
	_inherit = 'res.company'

	pagos_360 = fields.Boolean('Pagos360 - Pago voluntario')
	pagos_360_id = fields.Many2one('financiera.pagos.360.cuenta', 'Pagos360 - Cuenta')