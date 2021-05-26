# -*- coding: utf-8 -*-
from openerp import http
from openerp.http import request
import logging
import json

_logger = logging.getLogger(__name__)
class FinancieraPagos360WebhookController(http.Controller):

	@http.route("/financiera.pagos.360/webhook", auth="public", csrf=False)
	def webhook_listener(self, **post):
		_logger.info('Pagos360: nuevo webhook.')
		_logger.info('post:: ', post)
		print("print post:: ", post)
		if 'entity_name' in post.keys():
			print("entity_name:: ", post.get('entity_name'))
		if 'type' in post.keys():
			print("type:: ", post.get('type'))
		if 'entity_id' in post.keys():
			print("entity_id:: ", post.get('entity_id'))
		webhook_type = None
		entity_id = None
		if 'entity_name' in post.keys():
			# Obtener type
			webhook_type = post.get('type')
			entity_id = post.get('entity_id')
			_id = request.env['financiera.prestamo.cuota'].sudo().search([('pagos_360_solicitud_id','=', int(entity_id))])
			if _id and len(_id) > 0:
				cuota_id = request.env['financiera.prestamo.cuota'].sudo().browse(int(_id[0]))
				print("CUOTA:: ", cuota_id)
				print("CUOTA.saldo:: ", cuota_id.saldo)
				_logger.info('Pagos360: tipo '+post.get('type'))
				if webhook_type == "paid":
					# Cobrar y facturar
					cuota_id.button_actualizar_estado()
					_logger.info('Pagos360: nuevo pago procesado.')
				elif webhook_type == "expired":
					# Renovar
					cuota_id.cuota_id.pagos_360_renovar_solicitud()
					_logger.info('Pagos360: expiro Cupon de Pago.')
			else:
				_logger.warning('Pagos360: No existe referencia de la cuota.')
		return json.dumps("OK")

