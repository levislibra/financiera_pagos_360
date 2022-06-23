# -*- coding: utf-8 -*-

from openerp import models, fields, api, _
from datetime import datetime, timedelta, date

PAGOS360_MONTO_MINIMO = 10
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
	# Nueva integracion
	solicitud_ids = fields.One2many('financiera.pagos360.solicitud', 'cuota_id', 'Solicitudes de Pago')

	@api.one
	def pagos_360_crear_solicitud(self):
		if self.state in ('activa', 'judicial', 'incobrable') and self.saldo >= PAGOS360_MONTO_MINIMO:
			solicitud_id = self.env['financiera.pagos360.solicitud'].crear_solicitud(self)
			solicitud_id.generar_solicitud()

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
			if multi_factura_id.invoice_amount == 0:
				multi_factura_id.unlink()
		multi_factura_punitorio_id = None
		if self.punitorio_a_facturar > 0:
			fpcmf_values = {
				'invoice_type': 'punitorio',
				'company_id': self.company_id.id,
			}
			multi_factura_punitorio_id = self.env['financiera.prestamo.cuota.multi.factura'].create(fpcmf_values)
			self.facturar_punitorio_cuota(invoice_date, factura_electronica, multi_factura_punitorio_id, multi_cobro_id)
			if multi_factura_punitorio_id != None and multi_factura_punitorio_id.invoice_amount == 0:
				multi_factura_punitorio_id.unlink()


