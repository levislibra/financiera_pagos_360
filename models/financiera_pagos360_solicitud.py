# -*- coding: utf-8 -*-

from openerp import models, fields, api, _
from datetime import datetime, timedelta, date
from openerp.exceptions import UserError, ValidationError
import httplib
import json
import logging
_logger = logging.getLogger(__name__)

PAGOS360_ENDPOINT = "api.pagos360.com"
PAGOS360_MONTO_MINIMO = 10
WEBHOOK_DIR = "https://cloudlibrasoft.com/financiera.pagos.360/webhook"

class FinancieraPagos360Solicitud(models.Model):
	_name = 'financiera.pagos360.solicitud'

	_order = 'id desc'
	name = fields.Char('Nombre')
	cuota_id = fields.Many2one('financiera.prestamo.cuota', 'Cuota')
	partner_id = fields.Many2one('res.partner', 'Cliente')
	prestamo_id = fields.Many2one('financiera.prestamo', 'Prestamo')
	pagos_360_solicitud_id = fields.Integer('ID de la solicitud')
	pagos_360_solicitud_state = fields.Selection([
			('draft', 'Borrador'), ('pending', 'Pendiente'), ('paid', 'Pagada'),
			('expired', 'Expirada'), ('reverted', 'Revertida')],
			string='Estado', readonly=True, default='draft')
	pagos_360_first_due_date = fields.Date('Primer Vencimiento')
	pagos_360_first_total = fields.Float('Importe', digits=(16,2))
	pagos_360_second_due_date = fields.Date('Segundo Vencimiento')
	pagos_360_second_total = fields.Float('Importe', digits=(16,2))
	pagos_360_barcode = fields.Char('Barcode')
	pagos_360_checkout_url = fields.Char('Url de pago online')
	pagos_360_barcode_url = fields.Char('Url imagen del codigo de barras')
	pagos_360_pdf_url = fields.Char('Url de cupon de pago en pdf')
	pagos_360_cobro_duplicado = fields.Boolean('Posible cobro duplicado', default=False)
	company_id = fields.Many2one('res.company', 'Empresa')

	@api.model
	def create(self, values):
		rec = super(FinancieraPagos360Solicitud, self).create(values)
		rec.update({
			'name': 'SOLICITUD/',
		})
		return rec

	@api.model
	def crear_solicitud(self, cuota_id):
		values = {
			'cuota_id': cuota_id.id,
			'partner_id': cuota_id.partner_id.id,
			'prestamo_id': cuota_id.prestamo_id.id,
			'company_id': cuota_id.company_id.id,
		}
		rec = super(FinancieraPagos360Solicitud, self).create(values)
		return rec
	
	@api.model
	def _cron_generar_solicitudes(self):
		print("comenzamos _cron_generar_solicitudes")
		cr = self.env.cr
		uid = self.env.uid
		company_obj = self.pool.get('res.company')
		company_ids = company_obj.search(cr, uid, [])
		for companyid in company_ids:
			company_id = company_obj.browse(cr, uid, companyid)
			print("Company: ", company_id.name)
			cuota_obj = self.pool.get('financiera.prestamo.cuota')
			cuota_ids = cuota_obj.search(cr, uid, [
				('pagos_360_solicitud_id', '>', 0),
				('pagos_360_solicitud_state', '=', 'pending'),
				('company_id', '=', companyid),
			])
			print('  Cuotas para generar solicitud: ', len(cuota_ids))
			for cuotaid in cuota_ids:
				cuota_id = cuota_obj.browse(cr, uid, cuotaid)
				solicitud_obj = self.pool.get('financiera.pagos360.solicitud')
				solicitud_ids = solicitud_obj.search(cr, uid, [
					('pagos_360_solicitud_id', '=', cuota_id.pagos_360_solicitud_id),
					('company_id', '=', companyid),
				])
				if len(solicitud_ids) == 0:
					values = {
						'pagos_360_solicitud_id': cuota_id.pagos_360_solicitud_id,
						'name': 'SOLICITUD/' + str(cuota_id.pagos_360_solicitud_id),
						'pagos_360_solicitud_state': cuota_id.pagos_360_solicitud_state,
						'pagos_360_first_due_date': cuota_id.pagos_360_first_due_date,
						'pagos_360_first_total': cuota_id.pagos_360_first_total,
						'pagos_360_second_due_date': cuota_id.pagos_360_second_due_date,
						'pagos_360_second_total': cuota_id.pagos_360_second_total,
						'pagos_360_barcode': cuota_id.pagos_360_barcode,
						'pagos_360_checkout_url': cuota_id.pagos_360_checkout_url,
						'pagos_360_barcode_url': cuota_id.pagos_360_barcode_url,
						'pagos_360_pdf_url': cuota_id.pagos_360_pdf_url,
					}
					nueva_solicitud_id = self.env['financiera.pagos360.solicitud'].crear_solicitud(cuota_id)
					nueva_solicitud_id.update(values)
					print("    Generamos nueva solicitud de pago: ", nueva_solicitud_id.name)
				else:
					print('    La solicitud de pago ya existe')
			print("Finalizamos con la compania!!---------------")

	@api.one
	def generar_solicitud(self):
		if not self.cuota_id:
			raise ValidationError('Cuota no asignada.')
		basic_values = {
			'partner_id': self.cuota_id.partner_id.id,
			'prestamo_id': self.cuota_id.prestamo_id.id,
			'company_id': self.cuota_id.company_id.id,
		}
		self.update(basic_values)
		if self.cuota_id.saldo <= PAGOS360_MONTO_MINIMO:
			raise ValidationError('El monto no puede ser menor a ' + str(PAGOS360_MONTO_MINIMO))
		conn = httplib.HTTPSConnection(PAGOS360_ENDPOINT)
		pagos_360_id = self.cuota_id.company_id.pagos_360_id
		# primer vencimiento
		fecha_vencimiento = datetime.strptime(self.cuota_id.fecha_vencimiento, "%Y-%m-%d")
		if fecha_vencimiento < datetime.now():
			if pagos_360_id.expire_days_payment <= 0:
				raise ValidationError("En configuracion de Pagos360 defina Dias para pagar la nueva Solicitud de Pago mayor que 0.")
			else:
				fecha_vencimiento = datetime.now() + timedelta(days=+pagos_360_id.expire_days_payment)
		fecha_vencimiento = str(fecha_vencimiento.day).zfill(2)+"-"+str(fecha_vencimiento.month).zfill(2)+"-"+str(fecha_vencimiento.year)
		payload = {
			'payment_request': {
				'description': self.cuota_id.name,
				'external_reference': str(self.cuota_id.id),
				'payer_name': self._normalize(self.cuota_id.partner_id.name),
				'first_due_date': fecha_vencimiento,
				'first_total': self.cuota_id.saldo,
			}
		}
		# segundo vencimiento
		if self.cuota_id.segunda_fecha_vencimiento:
			segunda_fecha_vencimiento = datetime.strptime(self.cuota_id.segunda_fecha_vencimiento, "%Y-%m-%d")
			if segunda_fecha_vencimiento >= datetime.now() and self.cuota_id.total_segunda_fecha >= self.cuota_id.saldo:
				segunda_fecha_vencimiento = str(segunda_fecha_vencimiento.day).zfill(2)+"-"+str(segunda_fecha_vencimiento.month).zfill(2)+"-"+str(segunda_fecha_vencimiento.year)
				payload['payment_request']['second_due_date'] = segunda_fecha_vencimiento
				payload['payment_request']['second_total'] = self.cuota_id.total_segunda_fecha
		self.cuota_id.pagos_360_generar_pago_voluntario = True
		headers = {
			'content-type': "application/json",
			'authorization': "Bearer " + pagos_360_id.api_key,
		}
		conn.request("POST", "/payment-request", json.dumps(payload), headers)
		res = conn.getresponse()
		data = json.loads(res.read().decode("utf-8"))
		values = self._procesar_respuesta(data)
		self.update(values)

	def _normalize(self, s):
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
	
	def obtener_solicitud(self):
		data = None
		pagos_360_id = self.company_id.pagos_360_id
		if len(pagos_360_id) > 0 and self.pagos_360_solicitud_id > 0:
			headers = {
				'authorization': "Bearer " + pagos_360_id.api_key,
			}
			conn = httplib.HTTPSConnection(PAGOS360_ENDPOINT)
			conn.request("GET", "/payment-request/%s" % self.pagos_360_solicitud_id, headers=headers)
			res = conn.getresponse()
			data = json.loads(res.read().decode("utf-8"))
		return data
	
	@api.one
	def actualizar_solicitud(self):
		pagos_360_id = self.cuota_id.company_id.pagos_360_id
		if len(pagos_360_id) > 0 and self.pagos_360_solicitud_id > 0:
			solicitud_pago = self.obtener_solicitud()
			# Chequeamos si la solicitud esta en 'pending' y en el servidor esta en 'paid' hacemos el cobro y facturacion
			if solicitud_pago and self.pagos_360_solicitud_state == 'pending' and solicitud_pago['state'] == 'paid':
				if self.cuota_id.state in ('cobrada', 'precancelada', 'cobrada_con_reintegro'):
					self.pagos_360_cobro_duplicado = True
				request_result = solicitud_pago['request_result'][0]
				# superuser_id = self.sudo().pool.get('res.users').browse(self.env.cr, self.env.uid, 1)
				# superuser_id.sudo().company_id = self.company_id.id
				journal_id = pagos_360_id.journal_id
				factura_electronica = pagos_360_id.factura_electronica
				amount = request_result['amount']
				payment_date = request_result['paid_at']
				punitorio_stop_date = datetime.strptime(payment_date[0:10], '%Y-%m-%d')
				pagos_360_first_due_date = datetime.strptime(self.pagos_360_first_due_date, "%Y-%m-%d")
				pagos_360_second_due_date = False
				if self.pagos_360_second_due_date:
					pagos_360_second_due_date = datetime.strptime(self.pagos_360_second_due_date, "%Y-%m-%d")
				if punitorio_stop_date <= pagos_360_first_due_date:
					_logger.info("entramos")
					punitorio_stop_date = str(self.create_date)[0:10]
					_logger.info("punitorio_stop_date: %s" % punitorio_stop_date)
				elif pagos_360_second_due_date and punitorio_stop_date <= pagos_360_second_due_date:
					_logger.info("entramos ------------")
					_logger.info("entramos ************")
					_logger.info("entramos ////////////")
					punitorio_stop_date = str(self.pagos_360_second_due_date)
					_logger.info("punitorio_stop_date: %s" % punitorio_stop_date)
					if amount == self.cuota_id.total_segunda_fecha:
						self.cuota_id.punitorio_fijar = True
						punitorio_manual = self.cuota_id.total_segunda_fecha - self.cuota_id.total_primera_fecha
						if self.cuota_id.punitorio_computar and self.cuota_id.punitorio_calcular_iva and self.cuota_id.punitorio_vat_tax_id:
							punitorio_manual = punitorio_manual / (1 + self.cuota_id.punitorio_vat_tax_id.amount)
						self.cuota_id.punitorio_manual = punitorio_manual
				
				# amount = self.cuota_id.saldo
				invoice_date = datetime.now()
				self.cuota_id.pagos_360_cobrar_y_facturar(payment_date, journal_id, factura_electronica, amount, invoice_date, punitorio_stop_date)
				pagos_360_id.actualizar_saldo()
			self.pagos_360_solicitud_state = solicitud_pago['state']


	def _procesar_respuesta(self, data):
		if 'error' in data.keys():
			raise ValidationError(data['error']['message'])
		values = {}
		if 'id' in data.keys():
			values['pagos_360_solicitud_id'] = data['id']
			values['name'] = 'SOLICITUD/' + str(data['id'])
		if 'state' in data.keys():
			values['pagos_360_solicitud_state'] = data['state']
		if 'first_due_date' in data.keys():
			values['pagos_360_first_due_date'] = data['first_due_date']
		if 'first_total' in data.keys():
			values['pagos_360_first_total'] = data['first_total']
		if 'second_due_date' in data.keys():
			values['pagos_360_second_due_date'] = data['second_due_date']
		if 'second_total' in data.keys():
			values['pagos_360_second_total'] = data['second_total']
		if 'barcode' in data.keys():
			values['pagos_360_barcode'] = data['barcode']
		if 'checkout_url' in data.keys():
			values['pagos_360_checkout_url'] = data['checkout_url']
		if 'barcode_url' in data.keys():
			values['pagos_360_barcode_url'] = data['barcode_url']
		if 'pdf_url' in data.keys():
			values['pagos_360_pdf_url'] = data['pdf_url']
		return values
	
	@api.multi
	def action_cupon_sent(self):
		""" Open a window to compose an email, with the edi cupon template
			message loaded by default
		"""
		self.ensure_one()
		template = self.company_id.pagos_360_id.email_template_renovacion_cuota_id
		compose_form = self.env.ref('mail.email_compose_message_wizard_form', False)
		ctx = dict(
			default_model='financiera.pagos360.solicitud',
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
