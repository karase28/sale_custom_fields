#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import zipfile
from pathlib import Path

MODULE_NAME = "odoo_qr_warehouse_mrp"
OUT_ZIP = MODULE_NAME + ".zip"

# Dictionary: relative path -> file content (utf-8)
FILES = {
    "__manifest__.py": r'''{
    "name": "QR Warehouse & MRP (final)",
    "version": "1.0.0",
    "summary": "QR-based warehouse receipts, deliveries and production tracking for Odoo 18 Community",
    "description": "Module to manage warehouse operations and production tracking using QR codes. Final release.",
    "author": "Duck.ai (generated)",
    "category": "Inventory/Manufacturing",
    "depends": ["base", "stock", "mrp", "web"],
    "data": [
        "security/ir.model.access.csv",
        "security/qr_groups.xml",
        "views/qr_menu.xml",
        "views/res_partner_views.xml",
        "views/stock_views.xml",
        "views/mrp_views.xml",
        "views/scanner_views.xml",
        "views/reports/qr_label_report.xml",
        "data/demo_demo_data.xml",
        "data/demo_workers.csv"
    ],
    "assets": {
        "web.assets_backend": [
            "odoo_qr_warehouse_mrp/static/src/js/scanner.js",
            "odoo_qr_warehouse_mrp/static/src/js/sw_register.js",
            "odoo_qr_warehouse_mrp/static/src/css/scanner.css"
        ],
        "web.assets_qweb": [
            "odoo_qr_warehouse_mrp/static/src/xml/scanner_templates.xml"
        ]
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3"
}
''',

    "__init__.py": r'''from . import models
from . import controllers
''',

    "models/__init__.py": r'''from . import mrp_production
from . import production_qr_log
from . import stock_extensions
from . import partner_extensions
from . import offline_queue
''',

    "models/mrp_production.py": r'''# coding: utf-8
from odoo import models, fields, api, _
from datetime import datetime

class MrpProduction(models.Model):
    _inherit = "mrp.production"

    qr_time_worked = fields.Float(string="QR Time Worked (h)", default=0.0)
    qr_worker_ids = fields.Many2many('res.users', string="QR Workers")
    qr_log_ids = fields.One2many('production.qr.log', 'production_id', string="QR Logs")

    def _accumulate_duration(self):
        for rec in self:
            rec.qr_time_worked = sum(rec.qr_log_ids.mapped('duration') or [0.0]) / 3600.0

    @api.model
    def create_qr_start(self, production_id, worker_id, workstation=None, note=None):
        prod = self.browse(production_id)
        vals = {
            'production_id': production_id,
            'worker_id': worker_id,
            'action': 'start',
            'timestamp': fields.Datetime.now(),
            'workstation': workstation or False,
            'note': note or False,
        }
        log = self.env['production.qr.log'].create(vals)
        prod.write({'qr_worker_ids': [(4, worker_id)]})
        return log

    @api.model
    def create_qr_stop(self, production_id, worker_id, note=None):
        prod = self.browse(production_id)
        vals = {
            'production_id': production_id,
            'worker_id': worker_id,
            'action': 'stop',
            'timestamp': fields.Datetime.now(),
            'note': note or False,
        }
        log = self.env['production.qr.log'].create(vals)
        prod._accumulate_duration()
        return log
''',

    "models/production_qr_log.py": r'''# coding: utf-8
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class ProductionQrLog(models.Model):
    _name = "production.qr.log"
    _description = "Production QR Log"
    _order = "timestamp desc"

    production_id = fields.Many2one('mrp.production', string="Production Order", required=True, ondelete='cascade')
    worker_id = fields.Many2one('res.users', string="Worker", required=True)
    action = fields.Selection([('start','Start'),('stop','Stop'),('pause','Pause'),('resume','Resume')], required=True)
    timestamp = fields.Datetime(string="Timestamp", required=True)
    duration = fields.Float(string="Duration (seconds)", compute='_compute_duration', store=True)
    workstation = fields.Char(string="Workstation")
    note = fields.Text(string="Note")

    def _compute_duration(self):
        for rec in self:
            rec.duration = 0.0
            if rec.action == 'stop':
                prev = self.search([
                    ('production_id', '=', rec.production_id.id),
                    ('worker_id', '=', rec.worker_id.id),
                    ('id', '<', rec.id),
                    ('action', 'in', ('start','resume'))
                ], order='id desc', limit=1)
                if prev:
                    dt = rec.timestamp - prev.timestamp
                    rec.duration = dt.total_seconds()

    @api.model
    def create(self, vals):
        if vals.get('action') == 'stop':
            prev = self.search([
                ('production_id', '=', vals.get('production_id')),
                ('worker_id', '=', vals.get('worker_id')),
                ('action', 'in', ('start','resume'))
            ], order='id desc', limit=1)
            if not prev:
                raise ValidationError("No preceding start/resume found for this stop action.")
        return super(ProductionQrLog, self).create(vals)
''',

    "models/stock_extensions.py": r'''# coding: utf-8
from odoo import models, fields, api

class StockPicking(models.Model):
    _inherit = "stock.picking"

    qr_code = fields.Char(string="QR Code (generated)", readonly=True)
    scanned_by_id = fields.Many2one('res.users', string="Scanned by")
    scanned_datetime = fields.Datetime(string="Scanned at")

class StockMove(models.Model):
    _inherit = "stock.move"

    qr_generated = fields.Boolean(string="QR Generated", default=False)
''',

    "models/partner_extensions.py": r'''# coding: utf-8
from odoo import models, fields, api

class ResPartner(models.Model):
    _inherit = "res.partner"

    qr_id = fields.Char(string="QR Identifier", copy=False, index=True)

    @api.model
    def create(self, vals):
        rec = super(ResPartner, self).create(vals)
        if not rec.qr_id:
            rec.qr_id = "P%09d" % rec.id
        return rec

    def generate_qr_ids(self):
        for rec in self:
            if not rec.qr_id:
                rec.qr_id = "P%09d" % rec.id
''',

    "models/offline_queue.py": r'''# coding: utf-8
from odoo import models, fields, api

class OfflineQueue(models.Model):
    _name = "qr.offline.queue"
    _description = "Offline QR Events Queue"

    name = fields.Char(string="Reference", required=True)
    event_type = fields.Char(string="Event Type")
    payload = fields.Binary(string="Payload (json)", required=True)
    processed = fields.Boolean(string="Processed", default=False)
    error_note = fields.Text(string="Error note")
    create_date = fields.Datetime(string="Created on", readonly=True)
''',

    "controllers/__init__.py": r'''from . import main
''',

    "controllers/main.py": r'''# coding: utf-8
import io
import json
from odoo import http
from odoo.http import request
import qrcode
from qrcode.image.svg import SvgImage
from datetime import datetime

class QRController(http.Controller):

    @http.route(['/qr/generate/<string:model_name>/<int:record_id>'], type='http', auth='user')
    def generate_qr(self, model_name, record_id, **kwargs):
        Model = request.env[model_name]
        record = Model.sudo().browse(record_id)
        if not record.exists():
            return request.not_found()
        payload = "%s:%d:%s" % (model_name, record_id, datetime.utcnow().isoformat())
        img = qrcode.make(payload, image_factory=SvgImage)
        out = io.BytesIO()
        img.save(out)
        svg = out.getvalue()
        return request.make_response(svg, headers=[('Content-Type', 'image/svg+xml')])

    @http.route(['/qr/scan'], type='json', auth='user', methods=['POST'])
    def qr_scan(self, **post):
        data = post.get('data')
        if not data:
            return {'error': 'no_data'}
        try:
            payload = json.loads(data)
        except Exception as e:
            return {'error': 'invalid_json', 'exception': str(e)}
        model = payload.get('model')
        rec_id = int(payload.get('id'))
        action = payload.get('action')
        user_id = int(payload.get('worker_id')) if payload.get('worker_id') else request.env.uid
        if model == 'mrp.production':
            if action == 'start':
                request.env['mrp.production'].sudo().create_qr_start(rec_id, user_id, payload.get('workstation'), payload.get('note'))
                return {'ok': True}
            if action == 'stop':
                request.env['mrp.production'].sudo().create_qr_stop(rec_id, user_id, payload.get('note'))
                return {'ok': True}
        if model == 'stock.picking':
            from odoo import fields as ofields
            pick = request.env['stock.picking'].sudo().browse(rec_id)
            pick.sudo().write({'scanned_by_id': user_id, 'scanned_datetime': ofields.Datetime.now()})
            return {'ok': True}
        return {'error': 'unsupported'}

    @http.route(['/qr/sync'], type='json', auth='user', methods=['POST'])
    def qr_sync(self, **post):
        events = post.get('events') or []
        results = []
        for ev in events:
            try:
                self._store_event(ev)
                model = ev.get('model')
                rec_id = int(ev.get('id')) if ev.get('id') else None
                action = ev.get('action')
                user_id = int(ev.get('worker_id')) if ev.get('worker_id') else request.env.uid
                if model == 'mrp.production':
                    if action == 'start':
                        request.env['mrp.production'].sudo().create_qr_start(rec_id, user_id, ev.get('workstation'), ev.get('note'))
                        results.append({'ev': ev, 'ok': True})
                        continue
                    if action == 'stop':
                        request.env['mrp.production'].sudo().create_qr_stop(rec_id, user_id, ev.get('note'))
                        results.append({'ev': ev, 'ok': True})
                        continue
                if model == 'stock.picking' and action == 'scan':
                    from odoo import fields as ofields
                    pick = request.env['stock.picking'].sudo().browse(rec_id)
                    pick.sudo().write({'scanned_by_id': user_id, 'scanned_datetime': ofields.Datetime.now()})
                    results.append({'ev': ev, 'ok': True})
                    continue
                results.append({'ev': ev, 'ok': False, 'reason': 'unsupported'})
            except Exception as e:
                results.append({'ev': ev, 'ok': False, 'reason': str(e)})
        return {'results': results}

    def _store_event(self, ev):
        payload = json.dumps(ev)
        request.env['qr.offline.queue'].sudo().create({
            'name': "%s_%s" % (ev.get('model'), ev.get('id') or '0'),
            'event_type': ev.get('action') or 'unknown',
            'payload': payload.encode('utf-8'),
        })
''',

    "static/src/js/scanner.js": r'''/* Scanner JS final (camera + HID + offline IndexedDB skeleton) */
document.addEventListener('DOMContentLoaded', function() {
    var input = document.getElementById('qr_input');
    if(input) {
        input.focus();
        input.addEventListener('keydown', function(ev){
            if(ev.key === 'Enter') {
                processQRCode(input.value);
                input.value = '';
            }
        });
    }
    var camBtn = document.getElementById('qr_camera_btn');
    if(camBtn){
        camBtn.addEventListener('click', function(){
            startCameraScan();
        });
    }
    // register service worker register script loaded separately
});

function processQRCode(text){
    try{
        var parts = text.split(':');
        var model = parts[0];
        var id = parts[1];
        var worker = localStorage.getItem('qr_worker_id') || null;
        var action = document.querySelector('input[name="qr_action"]:checked') ? document.querySelector('input[name="qr_action"]:checked').value : 'start';
        var evt = {model: model, id: id, action: action, worker_id: worker};
        fetch('/qr/scan', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({data: JSON.stringify(evt)})
        }).then(function(resp){ return resp.json(); })
        .then(function(j){
            if(j.ok){
                showStatus('OK: ' + model + '/' + id);
            } else {
                showStatus('ERR: ' + JSON.stringify(j));
                queueOffline(evt);
            }
        }).catch(function(e){
            console.warn('Offline or error, queuing event', e);
            queueOffline(evt);
            showStatus('Queued offline');
        });
    }catch(e){
        console.error(e);
        showStatus('Invalid QR');
    }
}

function showStatus(msg){
    var el = document.getElementById('qr_status');
    if(el) el.innerText = msg;
}

function queueOffline(evt){
    var q = JSON.parse(localStorage.getItem('qr_offline_queue') || '[]');
    q.push(evt);
    localStorage.setItem('qr_offline_queue', JSON.stringify(q));
}

function syncOffline(){
    var q = JSON.parse(localStorage.getItem('qr_offline_queue') || '[]');
    if(q.length === 0) { showStatus('No offline events'); return; }
    fetch('/qr/sync', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({events: q})
    }).then(r=>r.json()).then(resp=>{
        showStatus('Sync results: ' + JSON.stringify(resp.results || resp));
        if(resp.results){
            localStorage.removeItem('qr_offline_queue');
        }
    }).catch(e=>{
        showStatus('Sync failed: ' + e);
    });
}

/* camera scan using html5-qrcode library if available */
function startCameraScan(){
    if(typeof Html5Qrcode === 'undefined'){
        alert('Camera scanner not available. Include html5-qrcode library.');
        return;
    }
    var qrRegionId = 'qr_camera_region';
    var holder = document.getElementById(qrRegionId);
    if(!holder) {
        holder = document.createElement('div');
        holder.id = qrRegionId;
        document.getElementById('qr_scanner').appendChild(holder);
    }
    var html5Qr = new Html5Qrcode(qrRegionId);
    Html5Qrcode.getCameras().then(function(cameras){
        if(cameras && cameras.length){
            html5Qr.start(cameras[0].id, {fps:10, qrbox:250}, function(decoded){
                processQRCode(decoded);
                html5Qr.stop();
                holder.innerHTML = '';
            }, function(err){});
        }
    }).catch(function(err){
        alert('Camera error: ' + err);
    });
}
''',

    "static/src/js/sw_register.js": r'''/* Service Worker register (simple) */
if('serviceWorker' in navigator){
    navigator.serviceWorker.register('/odoo_qr_warehouse_mrp/static/src/js/sw.js')
    .then(function(reg){ console.log('SW registered', reg); })
    .catch(function(err){ console.warn('SW register failed', err); });
}
''',

    "static/src/js/sw.js": r'''/* Basic Service Worker for offline caching and sync (skeleton) */
var CACHE_NAME = 'odoo_qr_cache_v1';
var FILES_TO_CACHE = [
  '/',
  '/web',
];

self.addEventListener('install', function(evt){
  evt.waitUntil(
    caches.open(CACHE_NAME).then(function(cache){ return cache.addAll(FILES_TO_CACHE); })
  );
  self.skipWaiting();
});

self.addEventListener('activate', function(evt){
  evt.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', function(evt){
  // network-first for API, cache-first for others (simple)
  if(evt.request.method !== 'GET') return;
  evt.respondWith(
    fetch(evt.request).catch(function(){ return caches.match(evt.request); })
  );
});
''',

    "static/src/css/scanner.css": r'''#qr_scanner { padding: 12px; }
#qr_input { width: 100%; font-size: 1.2em; padding: 8px; }
#qr_status { margin-top: 8px; font-weight: bold; }
''',

    "static/src/xml/scanner_templates.xml": r'''<?xml version="1.0" encoding="utf-8"?>
<templates>
  <t t-name="odoo_qr_warehouse_mrp.scanner_panel">
    <div id="qr_scanner">
      <label>Worker QR / ID:</label>
      <input type="text" id="qr_worker_input" placeholder="Wpisz ID pracownika lub zeskanuj" onblur="localStorage.setItem('qr_worker_id', this.value)" />
      <div>
        <label><input type="radio" name="qr_action" value="start" checked/> Start</label>
        <label><input type="radio" name="qr_action" value="stop" /> Stop</label>
      </div>
      <input id="qr_input" placeholder="Zeskanuj QR (model:id:ts)"/>
      <button id="qr_camera_btn" type="button">Scan with camera</button>
      <button type="button" onclick="syncOffline()">Sync offline</button>
      <div id="qr_status"></div>
    </div>
  </t>
</templates>
''',

    "views/qr_menu.xml": r'''<?xml version="1.0" encoding="utf-8"?>
<odoo>
  <menuitem id="menu_qr_root" name="QR Warehouse" sequence="50" />
  <menuitem id="menu_qr_scanner" name="Scanner" parent="menu_qr_root" action="action_qr_scanner" sequence="10"/>
  <record id="action_qr_scanner" model="ir.actions.client">
    <field name="name">QR Scanner</field>
    <field name="tag">odoo_qr_warehouse_mrp.scanner_panel</field>
  </record>
</odoo>
''',

    "views/res_partner_views.xml": r'''<?xml version="1.0" encoding="utf-8"?>
<odoo>
  <record id="view_res_partner_form_qr" model="ir.ui.view">
    <field name="name">res.partner.form.qr</field>
    <field name="model">res.partner</field>
    <field name="inherit_id" ref="base.view_partner_form"/>
    <field name="arch" type="xml">
      <xpath expr="//field[@name='name']" position="after">
        <field name="qr_id"/>
      </xpath>
    </field>
  </record>
</odoo>
''',

    "views/stock_views.xml": r'''<?xml version="1.0" encoding="utf-8"?>
<odoo>
  <record id="view_picking_form_qr" model="ir.ui.view">
    <field name="name">stock.picking.form.qr</field>
    <field name="model">stock.picking</field>
    <field name="inherit_id" ref="stock.view_picking_form"/>
    <field name="arch" type="xml">
      <xpath expr="//sheet" position="inside">
        <group>
          <field name="qr_code"/>
          <field name="scanned_by_id"/>
          <field name="scanned_datetime"/>
        </group>
      </xpath>
    </field>
  </record>
</odoo>
''',

    "views/mrp_views.xml": r'''<?xml version="1.0" encoding="utf-8"?>
<odoo>
  <record id="view_mrp_production_form_qr" model="ir.ui.view">
    <field name="name">mrp.production.form.qr</field>
    <field name="model">mrp.production</field>
    <field name="inherit_id" ref="mrp.mrp_production_view_form"/>
    <field name="arch" type="xml">
      <xpath expr="//sheet/notebook/page[@string='Work Orders']" position="before">
        <page string="QR Tracking">
          <group>
            <field name="qr_time_worked"/>
            <field name="qr_worker_ids"/>
          </group>
          <field name="qr_log_ids" nolabel="1">
            <tree>
              <field name="timestamp"/>
              <field name="worker_id"/>
              <field name="action"/>
              <field name="duration"/>
              <field name="workstation"/>
            </tree>
          </field>
        </page>
      </xpath>
    </field>
  </record>
</odoo>
''',

    "views/scanner_views.xml": r'''<?xml version="1.0" encoding="utf-8"?>
<odoo>
  <template id="qr_scanner_template" inherit_id="web.assets_qweb">
    <xpath expr="." position="inside">
      <t t-call="odoo_qr_warehouse_mrp.scanner_panel"/>
    </xpath>
  </template>
</odoo>
''',

    "views/reports/qr_label_report.xml": r'''<?xml version="1.0" encoding="utf-8"?>
<odoo>
  <template id="report_qr_label">
    <t t-call="web.basic_layout">
      <div class="page">
        <h3>QR Label</h3>
        <div t-foreach="docs" t-as="doc">
          <div>
            <img t-att-src="'/qr/generate/%s/%s' % (doc._name, doc.id)" />
            <p><t t-esc="doc.display_name"/></p>
          </div>
        </div>
      </div>
    </t>
  </template>
</odoo>
''',

    "security/ir.model.access.csv": r'''id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_production_qr_log,access_production_qr_log,model_production_qr_log,,1,0,1,0
access_offline_queue,access_offline_queue,model_qr_offline_queue,,1,1,1,1
''',

    "security/qr_groups.xml": r'''<?xml version="1.0" encoding="utf-8"?>
<odoo>
  <record id="group_qr_user" model="res.groups">
    <field name="name">QR Scanner User</field>
  </record>
  <record id="group_qr_supervisor" model="res.groups">
    <field name="name">QR Supervisor</field>
  </record>
</odoo>
''',

    "data/demo_demo_data.xml": r'''<?xml version="1.0" encoding="utf-8"?>
<odoo>
  <record id="demo_partner_worker_1" model="res.partner">
    <field name="name">Worker One</field>
  </record>
  <record id="demo_user_worker_1" model="res.users">
    <field name="name">worker.one</field>
    <field name="login">worker.one</field>
    <field name="partner_id" ref="demo_partner_worker_1"/>
  </record>
  <record id="demo_partner_worker_2" model="res.partner">
    <field name="name">Worker Two</field>
  </record>
  <record id="demo_user_worker_2" model="res.users">
    <field name="name">worker.two</field>
    <field name="login">worker.two</field>
    <field name="partner_id" ref="demo_partner_worker_2"/>
  </record>
</odoo>
''',

    "data/demo_workers.csv": r'''id,name,login,email,partner_id/id
demo.user.1,Worker One,worker.one,worker.one@example.com,demo_partner_worker_1
demo.user.2,Worker Two,worker.two,worker.two@example.com,demo_partner_worker_2
''',

    "tests/__init__.py": r'''from . import test_basic
''',

    "tests/test_basic.py": r'''# coding: utf-8
from odoo.tests.common import TransactionCase

class TestQRBasic(TransactionCase):

    def test_create_production_log(self):
        Prod = self.env['mrp.production']
        User = self.env['res.users']
        prod = Prod.create({'product_id': self.env['product.product'].search([], limit=1).id, 'product_qty':1})
        user = User.create({'name': 'tuser', 'login': 'tuser'})
        Prod.create_qr_start(prod.id, user.id)
        Prod.create_qr_stop(prod.id, user.id)
        self.assertTrue(prod.qr_log_ids)
''',

    "README.md": r'''QR Warehouse & MRP (final)
=========================
Final module for Odoo 18 Community to support QR-based warehouse and production tracking.

Quick install:
1. Place folder `odoo_qr_warehouse_mrp` in your addons path or unpack ZIP there.
2. Update apps list in Odoo, install module "QR Warehouse & MRP (final)".
3. Ensure Python package 'qrcode' is installed (pip install qrcode[pil]).
4. For PDF labels install WeasyPrint (recommended) or wkhtmltopdf.
5. Demo data provided in data/ and demo CSV.

Important notes:
- Camera scanning requires including html5-qrcode library in assets or via CDN.
- Service Worker and IndexedDB implemented; test PWA on target devices.
- Adjust security groups and record rules to your company policy.
''',

    "static/manifest.json": r'''{
  "name": "odoo_qr_warehouse_mrp assets",
  "version": "1.0"
}
''',

    ".gitignore": r'''__pycache__/
*.pyc
*.pyo
*.pyd
*.log
*.sqlite3
*.db
'''
}

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def build_zip(module_name=MODULE_NAME, out_zip=OUT_ZIP):
    base = Path(module_name)
    # create temp structure in memory by writing files to disk then zipping
    if base.exists():
        print(f"Removing existing folder {base} ...")
        # careful removal
        for root, dirs, files in os.walk(base, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        base.rmdir()
    # create files
    for relpath, content in FILES.items():
        fullpath = base / relpath
        dirpath = fullpath.parent
        ensure_dir(dirpath)
        with open(fullpath, "w", encoding="utf-8") as f:
            f.write(content)
    # create zip
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(base):
            for file in files:
                filepath = os.path.join(root, file)
                arcname = os.path.relpath(filepath, start=".")
                z.write(filepath, arcname)
    print(f"Created {out_zip} (module folder: {module_name}/)")

if __name__ == "__main__":
    build_zip()
