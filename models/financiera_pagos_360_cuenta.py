 # -*- coding: utf-8 -*-

from openerp import models, fields, api, _
from datetime import datetime, timedelta
from openerp.exceptions import UserError, ValidationError
import httplib
import json
import logging
import base64
import xlrd
import tempfile
import binascii
import StringIO
_logger = logging.getLogger(__name__)

WEBHOOK_DIR = "https://cloudlibrasoft.com/financiera.pagos.360/webhook"
COLUMNA_ID_SOLICITUD = "ID Solicitud"

class FinancieraPagos360Cuenta(models.Model):
	_name = 'financiera.pagos.360.cuenta'

	name = fields.Char('Nombre')
	company_id = fields.Many2one('res.company', 'Empresa', default=lambda self: self.env['res.company']._company_default_get('financiera.pagos.360.cuenta'))
	api_key = fields.Text('API Key')
	available_balance = fields.Float("Saldo Disponible")
	unavailable_balance = fields.Float("Saldo Pendiente")

	journal_id = fields.Many2one('account.journal', 'Diario de Cobro', domain="[('type', 'in', ('cash', 'bank'))]")
	factura_electronica = fields.Boolean('Factura electronica')
	cobros_archivo = fields.Binary('Archivo de cobros')
	cobros_contabilizados = fields.Integer('Cobros contabilizados')
	cobros_no_encontrados = fields.Text('Cobros no encontrados')
	set_default_payment = fields.Boolean("Marcar como medio de pago por defecto")
	expire_create_new = fields.Boolean("Crear nueva Solicitud de Pago al expirar")
	expire_days_payment = fields.Integer("Dias para pagar la nueva Solicitud de Pago", default=1)
	expire_max_count_create = fields.Integer("Numero de renovaciones")
	email_template_id = fields.Many2one('mail.template', 'Plantilla de cuponera')
	email_template_renovacion_cuota_id = fields.Many2one('mail.template', 'Plantilla de renovacion cuota')
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

	@api.one
	def actualizar_cobros(self):
		self.cobros_contabilizados = 0
		self.cobros_no_encontrados = ""
		cobros_no_encontrados = ""
		if self.cobros_archivo == None:
			raise ValidationError('El archivo resultado no fue cargado')
		# open file cobros_archivos whit xlrd
		f = StringIO.StringIO(base64.b64decode(self.cobros_archivo))
		book = xlrd.open_workbook(file_contents=f.getvalue(), ignore_workbook_corruption=True)
		sheet = book.sheet_by_index(0)
		col_id_solicitud = -1
		j = 0
		while j < sheet.ncols:
			if sheet.cell(0, j).value == COLUMNA_ID_SOLICITUD:
				col_id_solicitud = j
				break
			j += 1
		if col_id_solicitud == -1:
			raise ValidationError('No se encontro la columna: ' + COLUMNA_ID_SOLICITUD)
		i = 1
		for row in range(1, sheet.nrows):
			id_solicitud = str(sheet.cell(row, col_id_solicitud).value).split(".")[0]
			_id = self.env['financiera.pagos360.solicitud'].search([('pagos_360_solicitud_id', '=', id_solicitud)])
			if _id:
				solicitud_id = self.env['financiera.pagos360.solicitud'].browse(_id.id)
				solicitud_id.actualizar_solicitud()
				self.cobros_contabilizados += 1
			else:
				# hacer i modulo 6 para que se vea bonito en el html
				if i % 6 == 0:
					cobros_no_encontrados += str(id_solicitud) + ", <br>"
				else:
					cobros_no_encontrados += str(id_solicitud) + ", "
			i += 1
		self.cobros_no_encontrados = cobros_no_encontrados
