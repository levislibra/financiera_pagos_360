 # -*- coding: utf-8 -*-

from openerp import models, fields, api, _
from datetime import datetime, timedelta
from openerp.exceptions import UserError, ValidationError
import httplib
import json
import logging
import base64
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
			('pagos_360_solicitud_state', 'in', ('pending', 'expired')),
		])
		# No se obtienen las pagadas ya que el cobro no puede ser revertido, debido
		# a los medios de pago offline
		_logger.info('Chequear cobro voluntario por medio de pagos360')
		count = 0
		for _id in cuotas_ids:
			pagos_360_id = self.env.user.company_id.pagos_360_id
			cuota_id = cuotas_obj.browse(cr, uid, _id)
			request_result = cuota_id.pagos_360_actualizar_estado()[0]
			pagos_360_solicitud_state = cuota_id.pagos_360_solicitud_state
			if cuota_id.state in ('activa', 'judicial', 'incobrable') and pagos_360_solicitud_state == 'paid':
				journal_id = pagos_360_id.journal_id
				factura_electronica = pagos_360_id.factura_electronica
				payment_date = request_result['paid_at']
				amount = request_result['amount']
				# Si se desea hacer factura electronica esto puede traer problemas
				# dependiendo de la fecha de la utlima factura
				# Posible solucion es usar un punto de venta exclusivo
				invoice_date = request_result['paid_at']
				cuota_id.pagos_360_cobrar_y_facturar(payment_date, journal_id, factura_electronica, amount, invoice_date)
				pagos_360_id.actualizar_saldo()
			elif cuota_id.state in ('activa', 'judicial', 'incobrable') and pagos_360_solicitud_state == 'expired':
				cuota_id.pagos_360_renovar_solicitud()
			elif cuota_id.state == 'cobrada' and pagos_360_solicitud_state == 'reverted':
				# Marcar diario con posibilidad de cancelar pagos => asientos
				# No se puede revertir pagos por medios de cobro off line
				pass
			count += 1
		_logger.info('Finalizo el chequeo: %s cuotas chequeadas', count)

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
		if self.punitorio_a_facturar > 0:
			fpcmf_values = {
				'invoice_type': 'punitorio',
				'company_id': self.company_id.id,
			}
			multi_factura_punitorio_id = self.env['financiera.prestamo.cuota.multi.factura'].create(fpcmf_values)
			self.facturar_punitorio_cuota(invoice_date, factura_electronica, multi_factura_punitorio_id, multi_cobro_id)
		if multi_factura_id.invoice_amount == 0:
			multi_factura_id.unlink()
		if multi_factura_punitorio_id.invoice_amount == 0:
			multi_factura_punitorio_id.unlink()


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
			ret = data['request_result'][0]
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
			}""" % (self.name, self.id, self.partner_id.name, fecha_vencimiento, self.total, segunda_fecha_vencimiento, self.total_segunda_fecha)
		else:
			payload = """{\
				"payment_request":{\
					"description":"%s",\
					"external_reference":"%s",\
					"payer_name":"%s",\
					"first_due_date":"%s",\
					"first_total":%s\
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
		fecha_vencimiento = datetime.strptime(self.fecha_vencimiento, "%Y-%m-%d")
		if self.pagos_360_solicitud_state == 'expired' and fecha_vencimiento < datetime.now():
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
		else:
			raise ValidationError("La cuota aun no esta vencida y no puede ser renovada.")


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

	@api.one
	def _compute_pagos_360(self):
		self.pagos_360 = self.env.user.company_id.pagos_360

	@api.multi
	def action_cupon_sent(self):
		""" Open a window to compose an email, with the edi payment template
			message loaded by default
		"""
		self.ensure_one()
		# template = self.env.ref('financiera_pagos_360.email_template_payment', False)
		pagos_360_id = self.env.user.company_id.pagos_360_id
		template = pagos_360_id.email_template_id
		compose_form = self.env.ref('mail.email_compose_message_wizard_form', False)
		report_name = pagos_360_id.report_name
		pdf = self.pool['report'].get_pdf(self._cr, self._uid, [self.id], report_name, context=None)
		new_attachment_id = self.env['ir.attachment'].create({
			'name': self.display_name+'.pdf',
			'datas_fname': self.display_name+'.pdf',
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
			prestamo_id.email_ids = [self.id]
			self.tipo = 'Pagos360 - Cuponera'
			self.auto_delete = False
		res = super(ExtendsMailMail, self).send(auto_commit=False, raise_exception=False)