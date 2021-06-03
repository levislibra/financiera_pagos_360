 # -*- coding: utf-8 -*-

from openerp import models, fields, api, _
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