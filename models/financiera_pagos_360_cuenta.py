# -*- coding: utf-8 -*-

from openerp import models, fields, api, _
from datetime import datetime, timedelta
from openerp.exceptions import UserError, ValidationError
import httplib
import json
import requests

PAGOS360_ENDPOINT = "api.pagos360.com"
ENDPOINT_CONSULTAR_COBROS = "https://api.pagos360.com/report/collection/"
WEBHOOK_DIR = "https://cloudlibrasoft.com/financiera.pagos.360/webhook"

class FinancieraPagos360Cuenta(models.Model):
	_name = 'financiera.pagos.360.cuenta'

	name = fields.Char('Nombre')
	company_id = fields.Many2one('res.company', 'Empresa', default=lambda self: self.env['res.company']._company_default_get('financiera.pagos.360.cuenta'))
	api_key = fields.Text('API Key')
	available_balance = fields.Float("Saldo Disponible")
	unavailable_balance = fields.Float("Saldo Pendiente")

	journal_id = fields.Many2one('account.journal', 'Diario de Cobro', domain="[('type', 'in', ('cash', 'bank'))]")
	factura_electronica = fields.Boolean('Factura electronica')
	set_default_payment = fields.Boolean("Marcar como medio de pago por defecto")
	cobros_days_check = fields.Integer('Dias para chequear cobros', default=7)
	expire_days_payment = fields.Integer("Dias para pagar la nueva Solicitud de Pago", default=1)
	email_template_id = fields.Many2one('mail.template', 'Plantilla de cuponera')
	email_template_renovacion_cuota_id = fields.Many2one('mail.template', 'Plantilla de renovacion cuota')
	report_name = fields.Char('Pdf adjunto en email')

	@api.one
	def actualizar_saldo(self):
		conn = httplib.HTTPSConnection(PAGOS360_ENDPOINT)
		headers = { 'authorization': "Bearer " + self.api_key }
		conn.request("GET", "/account/balances", headers=headers)
		res = conn.getresponse()
		responseObject = json.loads(res.read())
		self.available_balance = responseObject['available_balance']
		self.unavailable_balance = responseObject['unavailable_balance']

	@api.one
	def check_cobros(self):
		headers = {
			'Authorization': "Bearer " + self.api_key,
			'Content-Type': "application/json"
		}
		for day in range(1, self.cobros_days_check):
			date = (datetime.now() - timedelta(hours=(day*24)-3)).date() #-3 porque el servidor esta en EEUU
			date = date.strftime('%d-%m-%Y')
			print("URL: ",  ENDPOINT_CONSULTAR_COBROS + date)
			r = requests.get(ENDPOINT_CONSULTAR_COBROS + date, headers=headers)
			print("r.status_code: ", r.status_code)
			if r.status_code == 200:
				responseObject = r.json()
				print("responseObject: ", responseObject)
				if 'data' in responseObject:
					for cobro in responseObject['data']:
						print("informed_date: " + cobro['informed_date'])
						print("request_id: " + cobro['request_id'])
						print("external_reference: " + cobro['external_reference'])
						print("payer_name: " + cobro['payer_name'])
						print("description: " + cobro['description'])
						print("payment_date: " + cobro['payment_date'])
						print("channel: " + cobro['channel'])
						print("amount_paid: " + str(cobro['amount_paid']))
						print("net_fee: " + str(cobro['net_fee']))
						print("iva_fee: " + str(cobro['iva_fee']))
						print("net_amount: " + str(cobro['net_amount']))
						print("available_at: " + cobro['available_at'])
						print("=====================================")
						solicitud_ids = self.env['financiera.pagos360.solicitud'].search([
							('pagos_360_solicitud_id', '=', cobro['request_id']),
						])
						if not solicitud_ids:
							# creamos la solicitud que deberia haber existido
							print("No existe la solicitud, la creamos")
							id_cuota = False
							if cobro['external_reference']:
								id_cuota = cobro['external_reference']
							solicitud_id = self.env['financiera.pagos360.solicitud'].create({
								'pagos_360_solicitud_id': cobro['request_id'],
								'cuota_id': id_cuota,
								'pagos_360_solicitud_state': 'pending',
								'payer_name': cobro['payer_name'],
								'company_id': self.company_id.id,
							})
							# Si esta asignada a una cuota actualizamos la solicitud
							# sino queda creada para asginarla de forma manual
							if id_cuota:
								solicitud_id.actualizar_solicitud()
						else:
							solicitud_id = solicitud_ids[0]
							if solicitud_id.pagos_360_solicitud_state == 'pending':
								print("La solicitud esta pendiente, actualizamos")
								solicitud_id.actualizar_solicitud()
							elif solicitud_id.pagos_360_solicitud_state == 'paid':
								print("La solicitud ya esta pagada")
