 # -*- coding: utf-8 -*-

from openerp import models, fields, api, _
from datetime import datetime, timedelta
from openerp.exceptions import UserError, ValidationError
import httplib
import json
import logging
import base64
_logger = logging.getLogger(__name__)

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
	expire_create_new = fields.Boolean("Crear nueva Solicitud de Pago al expirar")
	expire_days_payment = fields.Integer("Dias para pagar la nueva Solicitud de Pago", default=1)
	expire_max_count_create = fields.Integer("Numero de renovaciones")
	email_template_id = fields.Many2one('mail.template', 'Plantilla de envio de cuponera por mail')
	report_name = fields.Char('Pdf adjunto en email')

	@api.one
	def actualizar_saldo(self):
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
	pagos_360_solicitud_id = fields.Integer('Pagos360 - ID de la solicitud')
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
		print("chequeamos")
		pagos_360_id = self.company_id.pagos_360_id
		print("self.state: ", self.state)
		if self.state in ('activa', 'judicial', 'incobrable'):
			solicitud_pago = self.pagos_360_obtener_solicitud_pago()
			print("solicitud_pago:: ", solicitud_pago)
			if self.state in ('activa', 'judicial', 'incobrable') and solicitud_pago['state'] == 'paid':
				request_result = solicitud_pago['request_result'][0]
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


class ExtendsFinancieraPrestamo(models.Model):
	_inherit = 'financiera.prestamo' 
	_name = 'financiera.prestamo'

	pagos_360 = fields.Boolean('Pagos360 - Pago voluntario', compute='_compute_pagos_360')
	pagos360_pago_voluntario = fields.Boolean('Pagos360 - Pago Voluntario')
	pagos_360_cupon_sent = fields.Boolean('Pagos360 - Cupon enviado por mail', default=False)
	# pagos_360_cupon_generado_cuotas = fields.Boolean('Pagos360 - Cupon no generado en todas las cuotas', compute='_compute_pagos_360_cupon_cuotas')

	@api.model
	def default_get(self, fields):
		rec = super(ExtendsFinancieraPrestamo, self).default_get(fields)
		if len(self.env.user.company_id.pagos_360_id) > 0:
			rec.update({
				'pagos360_pago_voluntario': self.env.user.company_id.pagos_360_id.set_default_payment,
			})
		return rec

	@api.one
	def crear_solicitudes_pagos_360(self):
		for cuota_id in self.cuota_ids:
			if self.pagos360_pago_voluntario:
				cuota_id.pagos_360_crear_solicitud()

	@api.one
	def enviar_a_acreditacion_pendiente(self):
		super(ExtendsFinancieraPrestamo, self).enviar_a_acreditacion_pendiente()
		self.crear_solicitudes_pagos_360()

	@api.one
	def _compute_pagos_360(self):
		self.pagos_360 = self.company_id.pagos_360

	# @api.one
	# def _compute_pagos_360_cupon_generado_cuotas(self):
	# 	ret = False
	# 	for cuota_id in self.cuota_ids:
	# 		if cuota_id.pagos_360_generar_pago_voluntario:
	# 			ret = True
	# 			break
	# 	self.pagos_360_cupon_generado_cuotas = ret

	@api.multi
	def action_cupon_sent(self):
		""" Open a window to compose an email, with the edi payment template
			message loaded by default
		"""
		self.ensure_one()
		# template = self.env.ref('financiera_pagos_360.email_template_payment', False)
		pagos_360_id = self.company_id.pagos_360_id
		template = pagos_360_id.email_template_id
		compose_form = self.env.ref('mail.email_compose_message_wizard_form', False)
		report_name = pagos_360_id.report_name
		pdf = self.pool['report'].get_pdf(self._cr, self._uid, [self.id], report_name, context=None)
		new_attachment_id = self.env['ir.attachment'].create({
			'name': 'Cuponera ' + self.display_name + '.pdf',
			'datas_fname': 'Cuponera ' + self.display_name + '.pdf',
			'type': 'binary',
			'datas': base64.encodestring(pdf),
			'res_model': 'financiera.prestamo',
			'res_id': self.id,
			'mimetype': 'application/x-pdf',
		})
		ctx = dict(
			default_model='financiera.prestamo',
			default_res_id=self.id,
			default_use_template=bool(template),
			default_template_id=template and template.id or False,
			default_composition_mode='comment',
			default_attachment_ids=[new_attachment_id.id],
			sub_action='cupon_sent',
		)
		return {
			'name': _('Compose Email'),
			'type': 'ir.actions.act_window',
			'view_type': 'form',
			'view_mode': 'form',
			'res_model': 'mail.compose.message',
			'views': [(compose_form.id, 'form')],
			'view_id': compose_form.id,
			'target': 'new',
			'context': ctx,
		}

	@api.one
	def enviar_email_cuponera_prestamo(self):
		if len(self.company_id.pagos_360_id) > 0:
			pagos_360_id = self.company_id.pagos_360_id
			if len(pagos_360_id.email_template_id) > 0:
				template = pagos_360_id.email_template_id
				report_name = pagos_360_id.report_name
				if report_name:
					pdf = self.pool['report'].get_pdf(self._cr, self._uid, [self.id], report_name, context=None)
					new_attachment_id = self.env['ir.attachment'].create({
						'name': 'Cuponera ' + self.display_name+'.pdf',
						'datas_fname': 'Cuponera ' + self.display_name+'.pdf',
						'type': 'binary',
						'datas': base64.encodestring(pdf),
						'res_model': 'financiera.prestamo',
						'res_id': self.id,
						'mimetype': 'application/x-pdf',
					})
					template.attachment_ids = [(6, 0, [new_attachment_id.id])]
				# context = self.env.context.copy()
				template.send_mail(self.id, raise_exception=False, force_send=True)

	@api.multi
	def cuponera_de_pagos_report(self):
		self.ensure_one()
		pagos_360_id = self.company_id.pagos_360_id
		if len(pagos_360_id) > 0 and pagos_360_id.report_name:
			return self.env['report'].get_action(self, pagos_360_id.report_name)
		else:
			raise UserError("Reporte de cuponera no configurado.")

class ExtendsMailMail(models.Model):
	_name = 'mail.mail'
	_inherit = 'mail.mail'

	@api.one
	def send(self, auto_commit=False, raise_exception=False):
		context = dict(self._context or {})
		active_model = context.get('active_model')
		sub_action = context.get('sub_action')
		active_id = context.get('active_id')
		if active_model == 'financiera.prestamo' and sub_action == 'cupon_sent':
			cr = self.env.cr
			uid = self.env.uid
			prestamo_obj = self.pool.get('financiera.prestamo')
			prestamo_id = prestamo_obj.browse(cr, uid, active_id)
			prestamo_id.pagos_360_cupon_sent = True
			self.company_id = prestamo_id.company_id.id
			prestamo_id.email_ids = [self.id]
			self.tipo = 'Pagos360 - Cuponera'
			self.auto_delete = False
		res = super(ExtendsMailMail, self).send(auto_commit=False, raise_exception=False)