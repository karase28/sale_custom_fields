from odoo import models, fields

class SaleOrder(models.Model):
    _inherit = "sale.order"

    client_order_ref = fields.Char(string="Nr obcy zamówienia")
    client_project_number = fields.Char(string="Nr projektu klienta")
    client_requested_date = fields.Date(string="Data życzona klienta")