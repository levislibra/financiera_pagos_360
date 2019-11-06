 # -*- coding: utf-8 -*-

from openerp import models, fields, api
from datetime import datetime, timedelta
from openerp.exceptions import UserError, ValidationError
import httplib
import json
import logging
_logger = logging.getLogger(__name__)

class FinancieraPagos360Cuenta(models.Model):
	_name = 'financiera.pagos.360.cuenta'

	name = fields.Char('Nombre')
	company_id = fields.Many2one('res.company', 'Empresa', default=lambda self: self.env['res.company']._company_default_get('financiera.pagos.360.cuenta'))
	api_key = fields.Text('API Key')
	available_balance = fields.Float("Saldo Disponible")
	unavailable_balance = fields.Float("Saldo Pendiente")

	journal_id = fields.Many2one('account.journal', 'Diario de Cobro', domain="[('type', 'in', ('cash', 'bank'))]")
	factura_electronica = fields.Boolean('Factura electronica')

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
	pagos_360_solicitud_id = fields.Integer('ID de la solicitud')
	pagos_360_solicitud_state = fields.Selection([
			('pending', 'Pendiente'), ('paid', 'Pagada'),
			('expired', 'Expirada'), ('reverted', 'Revertida')],
			string='Estado', readonly=True, default='pending')
	pagos_360_first_due_date = fields.Date('Primer Vencimiento')
	pagos_360_first_total = fields.Float('Importe', digits=(16,2))
	pagos_360_second_due_date = fields.Date('Segundo Vencimiento')
	pagos_360_second_total = fields.Float('Importe', digits=(16,2))
	pagos_360_barcode = fields.Char('Barcode')
	pagos_360_checkout_url = fields.Char('Url de pago online')
	pagos_360_barcode_url = fields.Char('Url imagen del codigo de barras')
	pagos_360_pdf_url = fields.Char('Url de cupon de pago en pdf')

	@api.model
	def compute_cuota(self):
		super(ExtendsFinancieraPrestamoCuota, self).compute_cuota()
		if self.prestamo_id.pagos360_pago_voluntario:
			self.pagos_360_crear_solicitud()

	@api.model
	def _actualizar_cobros_360(self):
		cr = self.env.cr
		uid = self.env.uid
		cuotas_obj = self.pool.get('financiera.prestamo.cuota')
		cuotas_ids = cuotas_obj.search(cr, uid, [
			('pagos_360_generar_pago_voluntario', '=', True),
			('state', 'in', ('activa', 'judicial', 'incobrable')),
			('pagos_360_solicitud_state', 'in', ('pending', 'paid')),
		])
		_logger.info('Chequear cobro voluntario por medio de pagos360')
		count = 0
		for _id in cuotas_ids:
			pagos_360_id = self.env.user.company_id.pagos_360_id
			cuota_id = cuotas_obj.browse(cr, uid, _id)
			old_state = cuota_id.pagos_360_solicitud_state
			request_result = cuota_id.pagos_360_actualizar_estado()[0]
			print("request_result :: ")
			print(request_result)
			new_state = cuota_id.pagos_360_solicitud_state
			print("ESTADO ACTUALIZADO A:: "+str(new_state))
			print("FUE ACTUALIZADO? "+str(old_state != new_state))
			if old_state != new_state:
				if new_state == 'paid':
					payment_date = None
					journal_id = self.company_id.pagos_360_id.journal_id
					factura_electronica = self.company_id.pagos_360_id.factura_electronica
					amount = 0
					invoice_date = None
					if request_result:
						payment_date = request_result['paid_at']
						amount = request_result['amount']
						# Si se desea hacer factura electronica esto puede traer problemas
						# dependiendo de la fecha de la utlima factura
						# Posible solucion es usar un punto de venta exclusivo
						invoice_date = request_result['paid_at']

					partner_id = cuota_id.partner_id
					fpcmc_values = {
						'partner_id': partner_id.id,
						'company_id': self.company_id.id,
					}
					multi_cobro_id = self.env['financiera.prestamo.cuota.multi.cobro'].create(fpcmc_values)
					partner_id.multi_cobro_ids = [multi_cobro_id.id]
					cuota_id.confirmar_cobrar_cuota(payment_date, journal_id, amount, multi_cobro_id)
					# Facturacion cuota
					if not cuota_id.facturada:
						fpcmf_values = {
							'invoice_type': 'interes',
							'company_id': self.company_id.id,
						}
						multi_factura_id = self.env['financiera.prestamo.cuota.multi.factura'].create(fpcmf_values)
						cuota_id.facturar_cuota(invoice_date, factura_electronica, multi_factura_id, multi_cobro_id)
					if cuota_id.punitorio_a_facturar > 0:
						fpcmf_values = {
							'invoice_type': 'punitorio',
							'company_id': self.company_id.id,
						}
						multi_factura_punitorio_id = self.env['financiera.prestamo.cuota.multi.factura'].create(fpcmf_values)
						cuota_id.facturar_punitorio_cuota(punitorio_invoice_date, punitorio_factura_electronica, multi_factura_punitorio_id, multi_cobro_id)
					if multi_factura_id.invoice_amount == 0:
						multi_factura_id.unlink()
					if multi_factura_punitorio_id.invoice_amount == 0:
						multi_factura_punitorio_id.unlink()
				elif new_state == 'expire':
					self.pagos_360_renovar_solicitud()
				elif new_state == 'reverted':
					# Marcar diario con posibilidad de cancelar pagos => asientos
					# No se puede revertir pagos por medios de cobro off line
					pass
			count += 1
		_logger.info('Finalizo el chequeo: %s cuotas chequeadas', count)

	@api.one
	def pagos_360_actualizar_estado(self):
		conn = httplib.HTTPSConnection("api.pagos360.com")
		pagos_360_id = self.env.user.company_id.pagos_360_id
		headers = {
			'authorization': "Bearer " + pagos_360_id.api_key,
		}
		conn.request("GET", "/payment-request/%s" % self.pagos_360_solicitud_id, headers=headers)
		res = conn.getresponse()
		data = json.loads(res.read().decode("utf-8"))
		if 'error' in data.keys():
			raise ValidationError(data['error']['message'])
		if 'state' in data.keys():
			self.pagos_360_solicitud_state = data['state']
		ret = False
		if 'request_result' in data.keys():
			print(data['request_result'])
			print(data['request_result']['amount'])
			ret = data['request_result']
		return ret

	@api.one
	def pagos_360_crear_solicitud(self):
		conn = httplib.HTTPSConnection("api.pagos360.com")
		pagos_360_id = self.env.user.company_id.pagos_360_id
		payload = ""
		# primer vencimiento
		fecha_vencimiento = datetime.strptime(self.fecha_vencimiento, "%Y-%m-%d")
		if fecha_vencimiento < datetime.now():
			if pagos_360_id.expire_days_payment <= 0:
				raise ValidationError("En configuracion de Pagos360 defina Dias para pagar la nueva Solicitud de Pago mayor que 0.")
			else:
				fecha_vencimiento = datetime.now() + timedelta(days=+pagos_360_id.expire_days_payment)
		fecha_vencimiento = str(fecha_vencimiento.day).zfill(2)+"-"+str(fecha_vencimiento.month).zfill(2)+"-"+str(fecha_vencimiento.year)
		# segundo vencimiento
		if self.segunda_fecha_vencimiento != False:
			segunda_fecha_vencimiento = datetime.strptime(self.segunda_fecha_vencimiento, "%Y-%m-%d")
		if  self.segunda_fecha_vencimiento != False and segunda_fecha_vencimiento >= datetime.now() and self.total_segunda_fecha > self.total:
			segunda_fecha_vencimiento = str(segunda_fecha_vencimiento.day).zfill(2)+"-"+str(segunda_fecha_vencimiento.month).zfill(2)+"-"+str(segunda_fecha_vencimiento.year)
			payload = """{\
				"payment_request":{\
					"description":"%s",\
					"external_reference":"%s",\
					"payer_name": "%s",\
					"first_due_date": "%s",\
					"first_total": %s,\
					"second_due_date": "%s",\
					"second_total": %s\
				}\
			}""" % (self.name, self.id, self.partner_id.name, fecha_vencimiento, self.total, segunda_fecha_vencimiento, self.total_segunda_fecha)
		else:
			payload = """{\
				"payment_request":{\
					"description":"%s",\
					"external_reference":"%s",\
					"payer_name": "%s",\
					"first_due_date": "%s",\
					"first_total": %s\
				}\
			}""" % (self.name, self.id, self.partner_id.name, fecha_vencimiento, self.total)
		self.pagos_360_generar_pago_voluntario = True
		headers = {
			'content-type': "application/json",
			'authorization': "Bearer " + pagos_360_id.api_key,
		}
		conn.request("POST", "/payment-request", payload, headers)
		res = conn.getresponse()
		data = json.loads(res.read().decode("utf-8"))
		self.procesar_respuesta(data)


	@api.one
	def pagos_360_renovar_solicitud(self):
		conn = httplib.HTTPSConnection("api.pagos360.com")
		pagos_360_id = self.env.user.company_id.pagos_360_id
		payload = ""
		if pagos_360_id.expire_days_payment <= 0:
			raise ValidationError("En configuracion de Pagos360 defina Dias para pagar la nueva Solicitud de Pago mayor que 0.")
		else:
			fecha_vencimiento = datetime.now() + timedelta(days=+pagos_360_id.expire_days_payment)
			fecha_vencimiento = str(fecha_vencimiento.day).zfill(2)+"-"+str(fecha_vencimiento.month).zfill(2)+"-"+str(fecha_vencimiento.year)
			payload = """{\
				"payment_request":{\
					"description":"%s",\
					"external_reference":"%s",\
					"payer_name": "%s",\
					"first_due_date": "%s",\
					"first_total": %s\
				}\
			}""" % (self.name, self.id, self.partner_id.name, fecha_vencimiento, self.total)
		self.pagos_360_generar_pago_voluntario = True
		headers = {
			'content-type': "application/json",
			'authorization': "Bearer " + pagos_360_id.api_key,
		}
		conn.request("POST", "/payment-request", payload, headers)
		res = conn.getresponse()
		data = json.loads(res.read().decode("utf-8"))
		self.procesar_respuesta(data)


	@api.one
	def procesar_respuesta(self, data):
		if 'error' in data.keys():
			raise ValidationError(data['error']['message'])
		if 'id' in data.keys():
			self.pagos_360_solicitud_id = data['id']
		if 'state' in data.keys():
			self.pagos_360_solicitud_state = data['state']
		if 'first_due_date' in data.keys():
			self.pagos_360_first_due_date = data['first_due_date']
		if 'first_total' in data.keys():
			self.pagos_360_first_total = data['first_total']
		if 'second_due_date' in data.keys():
			self.pagos_360_second_due_date = data['second_due_date']
		if 'second_total' in data.keys():
			self.pagos_360_second_total = data['second_total']
		if 'barcode' in data.keys():
			self.pagos_360_barcode = data['barcode']
		if 'checkout_url' in data.keys():
			self.pagos_360_checkout_url = data['checkout_url']
		if 'barcode_url' in data.keys():
			self.pagos_360_barcode_url = data['barcode_url']
		if 'pdf_url' in data.keys():
			self.pagos_360_pdf_url = data['pdf_url']


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
