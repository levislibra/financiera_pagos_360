 # -*- coding: utf-8 -*-

from openerp import models, fields, api
from datetime import datetime, timedelta
from openerp.exceptions import UserError, ValidationError
import httplib
import json

class FinancieraPagos360Cuenta(models.Model):
	_name = 'financiera.pagos.360.cuenta'

	name = fields.Char('Nombre')
	company_id = fields.Many2one('res.company', 'Empresa', default=lambda self: self.env['res.company']._company_default_get('financiera.pagos.360.cuenta'))
	api_key = fields.Text('API Key')
	available_balance = fields.Float("Saldo Disponible")
	unavailable_balance = fields.Float("Saldo Pendiente")

	expire_create_new = fields.Boolean("Crear nueva Solicitud de Pago al expirar")
	expire_days_payment = fields.Integer("Dias para pagar la nueva Solicitud de Pago", default=1)
	expire_max_count_create = fields.Integer("Numero de renovaciones")

	@api.one
	def button_test(self):
		conn = httplib.HTTPSConnection("api.pagos360.com")
		headers = { 'authorization': "Bearer " + self.api_key }
		conn.request("GET", "/account/balances", headers=headers)
		res = conn.getresponse()
		responseObject = json.loads(res.read())
		self.available_balance = responseObject['available_balance']
		self.unavailable_balance = responseObject['unavailable_balance']

class ExtendsFinancieraPrestamoCuota(models.Model):
	_inherit = 'financiera.prestamo.cuota' 
	_name = 'financiera.prestamo.cuota'

	pagos_360_generar_pago_voluntario = fields.Boolean('Pagos360 - Generar cupon de pago voluntario')
	pagos_360_solicitud_id = fields.Integer("ID de la solicitud")
	pagos_360_solicitud_state = fields.Selection([
			('pending', 'Pendiente'), ('paid', 'Pagada'),
			('expired', 'Expirada'), ('reverted', 'Revertida')],
			string='Estado', readonly=True, default='pending')

	@api.one
	def pagos_360_crear_solicitud(self):
		conn = httplib.HTTPSConnection("api.pagos360.com")
		pagos_360_id = self.env.user.company_id.pagos_360_id
		fecha_vencimiento = datetime.strptime(self.fecha_vencimiento, "%Y-%m-%d")
		if fecha_vencimiento < datetime.now():
			if pagos_360_id.expire_days_payment <= 0:
				raise ValidationError("En configuracion de Pagos360 defina Dias para pagar la nueva Solicitud de Pago mayor que 0.")
			else:
				fecha_vencimiento = datetime.now() + timedelta(days=+pagos_360_id.expire_days_payment)
		print("Fecha fecha_vencimiento:: "+str(fecha_vencimiento))
		fecha_vencimiento = str(fecha_vencimiento.day).zfill(2)+"-"+str(fecha_vencimiento.month).zfill(2)+"-"+str(fecha_vencimiento.year)
		payload = """{\
			"payment_request":{\
				"description":"%s",\
				"payer_name": "%s",\
				"first_due_date": "%s",\
				"first_total": %s\
			}\
		}""" % (self.name, self.partner_id.name, fecha_vencimiento, self.total)
		# "second_due_date": "%s",\
		# "second_total": %s\
		# , self.segunda_fecha_vencimiento, self.total_segunda_fecha

		print("********************************")
		print(payload)
		print("-----------------------------")
		headers = {
			'content-type': "application/json",
			'authorization': "Bearer " + pagos_360_id.api_key,
		}
		conn.request("POST", "/payment-request", payload, headers)
		res = conn.getresponse()
		data = json.loads(res.read().decode("utf-8"))
		print(data)
		print(data['id'])
		self.pagos_360_solicitud_id = data['id']
		self.pagos_360_solicitud_state = data['state']

	@api.one
	def pagos_360_renovar_solicitud(self):
		rec = super(FinancieraPagos360Solicitud, self).create(values)
		conn = httplib.HTTPSConnection("api.pagos360.com")
		pagos_360_id = self.env.user.company_id.pagos_360_id
		# payload = "{\"payment_request\":{\"description\":\"concepto_del_pago\",\"first_due_date\":\"25-01-2020\",\"first_total\":200.99,\"payer_name\":\"nombre_pagador\"}}"
		fecha_vencimiento = datetime.now() + pagos_360_id.expire_days_payment
		fecha_vencimiento = fecha_vencimiento.replace(hour=23,minute=59,second=59,microsecond=0)
		payload = {
			'payment_request': {
				'description': 'Pago de cuota',
				'payer_name': self.cuota_id.partner_id.name,
				'first_due_date': fecha_vencimiento,
				'first_total': self.cuota_id.saldo,
				# 'second_due_date': self.cuota_id.segunda_fecha_vencimiento,
				# 'second_total': self.cuota_id.total_segunda_fecha,
			}
		}
		headers = {
			'content-type': "application/json",
			'authorization': "<API Key>"
		}
		conn.request("POST", "/payment-request", payload, headers)
		res = conn.getresponse()
		data = res.read()
		print(data.decode("utf-8"))


class ExtendsFinancieraPrestamo(models.Model):
	_inherit = 'financiera.prestamo' 
	_name = 'financiera.prestamo'

	pagos_360 = fields.Boolean('Pagos360 - Pago voluntario', compute='_compute_pagos_360')
	pagos360_pago_voluntario = fields.Boolean('Pagos360 - Pago Voluntario')

	@api.one
	def _compute_pagos_360(self):
		self.pagos_360 = self.env.user.company_id.pagos_360

	# @api.one
	# def enviar_a_acreditacion_pendiente(self):
	# 	rec = super(ExtendsFinancieraPrestamo, self).enviar_a_acreditacion_pendiente()

	# 	for cuota_id in self.cuota_ids:
	# 		cuota_id.pagos_360_crear_solicitud()
