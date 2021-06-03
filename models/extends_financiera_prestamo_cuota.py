 # -*- coding: utf-8 -*-

from openerp import models, fields, api, _
from datetime import datetime, timedelta, date
from openerp.exceptions import UserError, ValidationError
import httplib
import json
import logging
_logger = logging.getLogger(__name__)

WEBHOOK_DIR = "https://cloudlibrasoft.com/financiera.pagos.360/webhook"

class ExtendsFinancieraPrestamoCuota(models.Model):
	_inherit = 'financiera.prestamo.cuota' 
	_name = 'financiera.prestamo.cuota'

	pagos_360_generar_pago_voluntario = fields.Boolean('Pagos360 - Generar cupon de pago voluntario')
	pagos_360_solicitud_id = fields.Integer('Pagos360 - ID de la solicitud')
	pagos_360_solicitud_previa1_id = fields.Integer('Pagos360 - ID de la solicitud previa 1')
	pagos_360_solicitud_previa1_fecha = fields.Date('Pagos360 - Fecha de la solicitud previa 1')
	pagos_360_solicitud_previa2_id = fields.Integer('Pagos360 - ID de la solicitud previa 2')
	pagos_360_solicitud_previa2_fecha = fields.Date('Pagos360 - Fecha de la solicitud previa 2')
	pagos_360_solicitud_id_origen_pago = fields.Integer('Pagos360 - ID de la solicitud de pago', readonly=1)
	pagos_360_solicitud_state = fields.Selection([
			('pending', 'Pendiente'), ('paid', 'Pagada'),
			('expired', 'Expirada'), ('reverted', 'Revertida')],
			string='Pagos360 - Estado', readonly=True, default='pending')
	pagos_360_first_due_date = fields.Date('Pagos360 - Primer Vencimiento')
	pagos_360_first_total = fields.Float('Pagos360 - Importe', digits=(16,2))
	pagos_360_second_due_date = fields.Date('Pagos360 - Segundo Vencimiento')
	pagos_360_second_total = fields.Float('Pagos360 - Importe', digits=(16,2))
	pagos_360_barcode = fields.Char('Pagos360 - Barcode')
	pagos_360_checkout_url = fields.Char('Pagos360 - Url de pago online')
	pagos_360_barcode_url = fields.Char('Pagos360 - Url imagen del codigo de barras')
	pagos_360_pdf_url = fields.Char('Pagos360 - Url de cupon de pago en pdf')

	@api.one
	def button_actualizar_estado(self):
		print("button_actualizar_estado")
		pagos_360_id = self.company_id.pagos_360_id
		if self.state in ('activa', 'judicial', 'incobrable'):
			solicitud_pago = self.pagos_360_obtener_solicitud_pago()
			print("solicitud_pago:: ", solicitud_pago)
			self.pagos_360_solicitud_state = solicitud_pago['state']
			self.pagos_360_solicitud_id_origen_pago = solicitud_pago['id']
			if self.state in ('activa', 'judicial', 'incobrable') and solicitud_pago['state'] == 'paid':
				request_result = solicitud_pago['request_result'][0]
				superuser_id = self.sudo().pool.get('res.users').browse(self.env.cr, self.env.uid, 1)
				superuser_id.sudo().company_id = self.company_id.id
				journal_id = pagos_360_id.journal_id
				factura_electronica = pagos_360_id.factura_electronica
				payment_date = request_result['paid_at']
				amount = request_result['amount']
				invoice_date = datetime.now()
				self.pagos_360_cobrar_y_facturar(payment_date, journal_id, factura_electronica, amount, invoice_date)
				self.pagos_360_solicitud_state = 'paid'
				pagos_360_id.actualizar_saldo()
		else:
			raise UserError('La cuota debe estar en estado activa, judicial o incobrable.')

	@api.one
	def pagos_360_cobrar_y_facturar(self, payment_date, journal_id, factura_electronica, amount, invoice_date):
		# Cobro cuota
		partner_id = self.partner_id
		fpcmc_values = {
			'partner_id': partner_id.id,
			'company_id': self.company_id.id,
		}
		multi_cobro_id = self.env['financiera.prestamo.cuota.multi.cobro'].create(fpcmc_values)
		partner_id.multi_cobro_ids = [multi_cobro_id.id]
		# Fijar fecha punitorio
		solicitud_id = self.pagos_360_solicitud_id_origen_pago
		if solicitud_id == self.pagos_360_solicitud_id:
			if not self.pagos_360_solicitud_previa1_id:
				self.punitorio_fecha_actual = payment_date
			else:
				self.punitorio_fecha_actual = self.pagos_360_solicitud_previa1_fecha
		if solicitud_id == self.pagos_360_solicitud_previa1_id:
			if not self.pagos_360_solicitud_previa2_id:
				self.punitorio_fecha_actual = payment_date
			else:
				self.punitorio_fecha_actual = self.pagos_360_solicitud_previa2_fecha
		if solicitud_id == self.pagos_360_solicitud_previa2_id:
			self.punitorio_fecha_actual = payment_date
		if self.saldo > 0:
			self.confirmar_cobrar_cuota(payment_date, journal_id, amount, multi_cobro_id)
		# Facturacion cuota
		if not self.facturada:
			fpcmf_values = {
				'invoice_type': 'interes',
				'company_id': self.company_id.id,
			}
			multi_factura_id = self.env['financiera.prestamo.cuota.multi.factura'].create(fpcmf_values)
			self.facturar_cuota(invoice_date, factura_electronica, multi_factura_id, multi_cobro_id)
		multi_factura_punitorio_id = None
		if self.punitorio_a_facturar > 0:
			fpcmf_values = {
				'invoice_type': 'punitorio',
				'company_id': self.company_id.id,
			}
			multi_factura_punitorio_id = self.env['financiera.prestamo.cuota.multi.factura'].create(fpcmf_values)
			self.facturar_punitorio_cuota(invoice_date, factura_electronica, multi_factura_punitorio_id, multi_cobro_id)
		if multi_factura_id.invoice_amount == 0:
			multi_factura_id.unlink()
		if multi_factura_punitorio_id != None and multi_factura_punitorio_id.invoice_amount == 0:
			multi_factura_punitorio_id.unlink()


	def pagos_360_obtener_solicitud_pago(self):
		conn = httplib.HTTPSConnection("api.pagos360.com")
		pagos_360_id = self.company_id.pagos_360_id
		if len(pagos_360_id) > 0 and self.pagos_360_solicitud_id > 0:
			headers = {
				'authorization': "Bearer " + pagos_360_id.api_key,
			}
			conn.request("GET", "/payment-request/%s" % self.pagos_360_solicitud_id, headers=headers)
			res = conn.getresponse()
			data = json.loads(res.read().decode("utf-8"))
		return data

	def normalize(self, s):
		replacements = (
			("á", "a"),
			("é", "e"),
			("í", "i"),
			("ó", "o"),
			("ú", "u"),
			("ñ", "n"),
		)
		for a, b in replacements:
			s = s.replace(a, b).replace(a.upper(), b.upper())
		return s

	@api.one
	def pagos_360_crear_solicitud(self, log_consola=None):
		conn = httplib.HTTPSConnection("api.pagos360.com")
		pagos_360_id = self.company_id.pagos_360_id
		payload = ""
		# primer vencimiento
		fecha_vencimiento = datetime.strptime(self.fecha_vencimiento, "%Y-%m-%d")
		if fecha_vencimiento < datetime.now():
			if pagos_360_id.expire_days_payment <= 0:
				if log_consola == True:
					_logger.error("En configuracion de Pagos360 defina Dias para pagar la nueva Solicitud de Pago mayor que 0.")
				else:
					raise ValidationError("En configuracion de Pagos360 defina Dias para pagar la nueva Solicitud de Pago mayor que 0.")
			else:
				fecha_vencimiento = datetime.now() + timedelta(days=+pagos_360_id.expire_days_payment)
		fecha_vencimiento = str(fecha_vencimiento.day).zfill(2)+"-"+str(fecha_vencimiento.month).zfill(2)+"-"+str(fecha_vencimiento.year)
		# segundo vencimiento
		if self.segunda_fecha_vencimiento != False:
			segunda_fecha_vencimiento = datetime.strptime(self.segunda_fecha_vencimiento, "%Y-%m-%d")
		if  self.segunda_fecha_vencimiento != False and segunda_fecha_vencimiento >= datetime.now() and self.total_segunda_fecha >= self.total:
			segunda_fecha_vencimiento = str(segunda_fecha_vencimiento.day).zfill(2)+"-"+str(segunda_fecha_vencimiento.month).zfill(2)+"-"+str(segunda_fecha_vencimiento.year)
			payload = """{\
				"payment_request":{\
					"description":"%s",\
					"external_reference":"%s",\
					"payer_name":"%s",\
					"first_due_date": "%s",\
					"first_total":%s,\
					"second_due_date":"%s",\
					"second_total":%s\
				}\
			}""" % (self.name, self.id, self.normalize(self.partner_id.name), fecha_vencimiento, self.total, segunda_fecha_vencimiento, self.total_segunda_fecha)
		else:
			payload = """{\
				"payment_request":{\
					"description":"%s",\
					"external_reference":"%s",\
					"payer_name":"%s",\
					"first_due_date":"%s",\
					"first_total":%s\
				}\
			}""" % (self.name, self.id, self.normalize(self.partner_id.name), fecha_vencimiento, self.total)
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
		self.button_actualizar_estado()
		fecha_vencimiento = datetime.strptime(self.fecha_vencimiento, "%Y-%m-%d") or False
		if (self.pagos_360_solicitud_state == 'expired' or self.pagos_360_solicitud_id == 0) and (fecha_vencimiento == False or fecha_vencimiento < datetime.now()):
			conn = httplib.HTTPSConnection("api.pagos360.com")
			pagos_360_id = self.company_id.pagos_360_id
			payload = ""
			if pagos_360_id.expire_days_payment <= 0:
				_logger.error("En configuracion de Pagos360 defina Dias para pagar la nueva Solicitud de Pago mayor que 0.")
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
				}""" % (self.name, self.id, self.normalize(self.partner_id.name), fecha_vencimiento, self.total)
			self.pagos_360_generar_pago_voluntario = True
			headers = {
				'content-type': "application/json",
				'authorization': "Bearer " + pagos_360_id.api_key,
			}
			conn.request("POST", "/payment-request", payload, headers)
			res = conn.getresponse()
			data = json.loads(res.read().decode("utf-8"))
			self.procesar_respuesta(data)
		else:
			_logger.error("La cuota aun no esta vencida y no puede ser renovada.")


	@api.one
	def procesar_respuesta(self, data):
		if 'error' in data.keys():
			_logger.error(data['error']['message'])
		if 'id' in data.keys():
			if self.pagos_360_solicitud_previa1_id > 0:
				self.pagos_360_solicitud_previa2_id = self.pagos_360_solicitud_previa1_id
				self.pagos_360_solicitud_previa2_fecha = self.pagos_360_solicitud_previa1_fecha
			if self.pagos_360_solicitud_id > 0:
				self.pagos_360_solicitud_previa1_id = self.pagos_360_solicitud_id
				self.pagos_360_solicitud_previa1_fecha = date.today()
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

	@api.multi
	def action_cupon_sent(self):
		""" Open a window to compose an email, with the edi cupon template
			message loaded by default
		"""
		self.ensure_one()
		template = self.env.ref('financiera_pagos_360.email_template_edi_cupon', False)
		compose_form = self.env.ref('mail.email_compose_message_wizard_form', False)
		ctx = dict(
			default_model='financiera.prestamo.cuota',
			default_res_id=self.id,
			default_use_template=bool(template),
			default_template_id=template and template.id or False,
			default_composition_mode='comment',
			sub_action='cupon_sent',
			# mark_invoice_as_sent=True,
		)
		return {
			'name': 'Envio cupon de pago',
			'type': 'ir.actions.act_window',
			'view_type': 'form',
			'view_mode': 'form',
			'res_model': 'mail.compose.message',
			'views': [(compose_form.id, 'form')],
			'view_id': compose_form.id,
			'target': 'new',
			'context': ctx,
		}

