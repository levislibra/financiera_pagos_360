 # -*- coding: utf-8 -*-

from openerp import models, fields, api
from datetime import datetime, timedelta
from openerp.exceptions import UserError, ValidationError
# import http.client

class FinancieraPagos360Cuenta(models.Model):
	_name = 'financiera.pagos.360.cuenta'

	name = fields.Char('Nombre')
	company_id = fields.Many2one('res.company', 'Empresa', required=False, default=lambda self: self.env['res.company']._company_default_get('financiera.pagos.360.cuenta'))
	api_key = fields.Text('API Key')
	available_balance = fields.Float("Saldo Disponible")
	unavailable_balance = fields.Float("Saldo Pendiente")

	expire_create_new = fields.Boolean("Crear nueva Solicitud de Pago al expirar")
	expire_days_payment = fields.Integer("Dias para pagar la nueva Solicitud de Pago")

	def button_test(self):
		conn = http.client.HTTPSConnection("api.pagos360.com")
		headers = { 'authorization': "Bearer <API Key>" }
		conn.request("GET", "/account/balances", headers=headers)
		res = conn.getresponse()
		data = res.read()
		print(data.decode("utf-8"))