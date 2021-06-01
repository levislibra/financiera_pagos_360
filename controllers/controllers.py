# -*- coding: utf-8 -*-
from openerp import http
from openerp.http import request
import logging
import json

_logger = logging.getLogger(__name__)
class FinancieraPagos360WebhookController(http.Controller):

	@http.route("/financiera.pagos.360/test", type='json', auth='public', methods=['POST'], csrf=False)
	def webhook_listener(self):
		_logger.info('Pagos360: nuevo webhook test.')
		data = json.loads(request.httprequest.data)
		args = json.loads(request.httprequest.args)
		print("print data:: ", data)
		print("print args:: ", args)

	@http.route("/financiera.pagos.360/webhook", type='json', auth='none', cors='*', csrf=False)
	def webhook_listener(self):
		_logger.info('Pagos360: nuevo webhook.')
		data = json.loads(request.httprequest.data)
		args = json.loads(request.httprequest.args)
		print("print data:: ", data)
		print("print args:: ", args)
		if 'entity_name' in data.keys():
			print("entity_name:: ", data.get('entity_name'))
		if 'type' in data.keys():
			print("type:: ", data.get('type'))
		if 'entity_id' in data.keys():
			print("entity_id:: ", data.get('entity_id'))
		webhook_type = None
		entity_id = None
		if 'entity_name' in data.keys():
			# Obtener type
			webhook_type = data.get('type')
			entity_id = data.get('entity_id')
			_id = request.env['financiera.prestamo.cuota'].sudo().search([('pagos_360_solicitud_id','=', int(entity_id))])
			if _id and len(_id) > 0:
				cuota_id = request.env['financiera.prestamo.cuota'].sudo().browse(int(_id[0]))
				print("CUOTA:: ", cuota_id)
				print("CUOTA.saldo:: ", cuota_id.saldo)
				_logger.info('Pagos360: tipo '+data.get('type'))
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

