# -*- coding: utf-8 -*-
from openerp import http
from openerp.http import request
import logging
import json

_logger = logging.getLogger(__name__)
class FinancieraPagos360WebhookController(http.Controller):

	@http.route("/financiera.pagos.360/webhook", type='json', auth='none', cors='*', csrf=False)
	def webhook_listener(self, **post):
		_logger.info('Pagos360: nuevo webhook.')
		_logger.info(request.jsonrequest)
		data = request.jsonrequest
		webhook_type = None
		entity_id = None
		if 'entity_name' in data.keys():
			# Obtener type
			webhook_type = data.get('type')
			entity_id = data.get('entity_id')
			_id = request.env['financiera.prestamo.cuota'].sudo().search([
				'|', ('pagos_360_solicitud_id','=', int(entity_id)),
				'|', ('pagos_360_solicitud_previa1_id','=', int(entity_id)),
				('pagos_360_solicitud_previa2_id','=', int(entity_id)),
			])
			if _id and len(_id) > 0:
				cuota_id = request.env['financiera.prestamo.cuota'].sudo().browse(int(_id[0]))
				_logger.info("CUOTA:: ", cuota_id)
				_logger.info("CUOTA.saldo:: ", cuota_id.saldo)
				_logger.info('Pagos360: tipo '+data.get('type'))
				if webhook_type == "paid":
					# Cobrar y facturar
					cuota_id.button_actualizar_estado()
					_logger.info('Pagos360: nuevo pago procesado.')
				# elif webhook_type == "expired":
				# 	# Renovar
				# 	cuota_id.cuota_id.pagos_360_renovar_solicitud()
				# 	_logger.info('Pagos360: expiro Cupon de Pago.')
			else:
				_logger.warning('Pagos360: No existe referencia de la cuota.')
		return json.dumps("OK")
