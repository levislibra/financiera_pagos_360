 # -*- coding: utf-8 -*-

from openerp import models, fields, api, _
from datetime import datetime, timedelta
from openerp.exceptions import UserError, ValidationError
import logging
import base64

WEBHOOK_DIR = "https://cloudlibrasoft.com/financiera.pagos.360/webhook"

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
		if self.cuota_ids and self.cuota_ids[0].pagos_360_solicitud_id == 0:
			self.crear_solicitudes_pagos_360()
		else:
			print("Acreditaicon pendiente: cupon ya generado!")

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
