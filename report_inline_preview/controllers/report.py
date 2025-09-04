from odoo.addons.web.controllers.report import ReportController
from odoo.http import request, route, content_disposition

class ReportControllerInline(ReportController):

    @route(['/report/inline/<string:reportname>/<string:docids>'], type='http', auth='user')
    def report_inline(self, reportname, docids=None, **data):
        """Renderuje PDF i pokazuje go w przeglądarce (inline)"""
        report = request.env["ir.actions.report"]._get_report_from_name(reportname)
        pdf_content, _ = report._render_qweb_pdf([int(x) for x in docids.split(",")])

        return request.make_response(
            pdf_content,
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Length", len(pdf_content)),
                ("Content-Disposition", "inline; filename=%s.pdf" % reportname),
            ],
        )

    @route(['/report/download/<string:reportname>/<string:docids>'], type='http', auth='user')
    def report_download_force(self, reportname, docids=None, **data):
        """Klasyczne pobieranie raportu"""
        report = request.env["ir.actions.report"]._get_report_from_name(reportname)
        pdf_content, _ = report._render_qweb_pdf([int(x) for x in docids.split(",")])

        return request.make_response(
            pdf_content,
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Length", len(pdf_content)),
                ("Content-Disposition", content_disposition("%s.pdf" % reportname)),
            ],
        )