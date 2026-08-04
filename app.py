# -*- coding: utf-8 -*-
"""موقع جمعية المجد الشبابية — الخادم الرئيسي
الصفحة الرئيسية + مركز وثائق الحوكمة والشفافية + لوحة تحكم لرفع الملفات
"""
import os
import uuid
from datetime import datetime
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   session, send_from_directory, abort, flash)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'almajd-dev-secret-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE, 'instance', 'almajd.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(BASE, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 30 * 1024 * 1024  # 30MB حد أقصى للملف

# كلمة مرور لوحة التحكم — غيّرها عبر متغير البيئة ADMIN_PASSWORD
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'almajd2026')

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'png', 'jpg', 'jpeg'}

db = SQLAlchemy(app)


# ═══════════════ النماذج ═══════════════

class Section(db.Model):
    """تصنيف وثائق (مثال: محاضر الاجتماعات، اللوائح والسياسات...)"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(300), default='')
    icon = db.Column(db.String(30), default='doc')
    position = db.Column(db.Integer, default=0)
    documents = db.relationship('Document', backref='section',
                                cascade='all, delete-orphan',
                                order_by='Document.created_at.desc()')


class Document(db.Model):
    """ملف مرفوع تحت تصنيف"""
    id = db.Column(db.Integer, primary_key=True)
    section_id = db.Column(db.Integer, db.ForeignKey('section.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(300), nullable=False)   # الاسم المخزن على القرص
    orig_name = db.Column(db.String(300), default='')
    size = db.Column(db.Integer, default=0)                # بالبايت
    date_label = db.Column(db.String(60), default='')      # تاريخ النشر المعروض (هجري/ميلادي حر)
    downloads = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def ext(self):
        return (self.filename.rsplit('.', 1)[-1] if '.' in self.filename else 'ملف').upper()

    @property
    def size_label(self):
        s = self.size or 0
        if s >= 1024 * 1024:
            return f'{s / (1024*1024):.1f} MB'
        return f'{max(s // 1024, 1)} KB'


# أيقونات التصنيفات (SVG مضمّن)
SECTION_ICONS = {
    'scale': '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 3v18M3 7l3-4 3 4M3 7a3 3 0 1 0 6 0M15 7l3-4 3 4M15 7a3 3 0 1 0 6 0M8 21h8"/></svg>',
    'doc': '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/></svg>',
    'people': '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/></svg>',
    'chart': '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>',
    'money': '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>',
}

DEFAULT_SECTIONS = [
    ('أدلة الحوكمة', 'الأدلة التنظيمية المعتمدة من مجلس الإدارة والجمعية العمومية', 'scale'),
    ('اللوائح والسياسات', 'السياسات المنظّمة لعمل الجمعية وعلاقاتها مع أصحاب المصلحة', 'doc'),
    ('محاضر الاجتماعات', 'محاضر اجتماعات مجلس الإدارة والجمعية العمومية المعتمدة', 'people'),
    ('التقارير السنوية', 'التقارير الإدارية والتشغيلية عن أعمال الجمعية', 'chart'),
    ('الشفافية المالية', 'القوائم المالية المدققة وتقارير المراجع الخارجي', 'money'),
]


def init_db():
    os.makedirs(os.path.join(BASE, 'instance'), exist_ok=True)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    db.create_all()
    if Section.query.count() == 0:
        for i, (name, desc, icon) in enumerate(DEFAULT_SECTIONS):
            db.session.add(Section(name=name, description=desc, icon=icon, position=i))
        db.session.commit()


with app.app_context():
    init_db()


# ═══════════════ الصفحات العامة ═══════════════

@app.route('/')
def index():
    sections = Section.query.order_by(Section.position, Section.id).all()
    return render_template('index.html', sections=sections, icons=SECTION_ICONS)


@app.route('/files/<int:doc_id>/download')
def download_file(doc_id):
    doc = db.session.get(Document, doc_id) or abort(404)
    doc.downloads += 1
    db.session.commit()
    return send_from_directory(app.config['UPLOAD_FOLDER'], doc.filename,
                               as_attachment=True,
                               download_name=doc.orig_name or doc.filename)


@app.route('/files/<int:doc_id>/view')
def view_file(doc_id):
    doc = db.session.get(Document, doc_id) or abort(404)
    return send_from_directory(app.config['UPLOAD_FOLDER'], doc.filename)


# ═══════════════ لوحة التحكم ═══════════════

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return wrapper


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
        flash('كلمة المرور غير صحيحة', 'error')
    return render_template('admin/login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('index'))


@app.route('/admin/')
@admin_required
def admin_dashboard():
    sections = Section.query.order_by(Section.position, Section.id).all()
    return render_template('admin/dashboard.html', sections=sections, icons=SECTION_ICONS)


@app.route('/admin/sections', methods=['POST'])
@admin_required
def add_section():
    name = (request.form.get('name') or '').strip()
    if not name:
        flash('اكتب اسم التصنيف', 'error')
        return redirect(url_for('admin_dashboard'))
    max_pos = db.session.query(db.func.max(Section.position)).scalar() or 0
    db.session.add(Section(name=name,
                           description=(request.form.get('description') or '').strip(),
                           icon=request.form.get('icon') or 'doc',
                           position=max_pos + 1))
    db.session.commit()
    flash('تمت إضافة التصنيف بنجاح', 'ok')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/sections/<int:sec_id>/update', methods=['POST'])
@admin_required
def update_section(sec_id):
    sec = db.session.get(Section, sec_id) or abort(404)
    sec.name = (request.form.get('name') or sec.name).strip()
    sec.description = (request.form.get('description') or '').strip()
    db.session.commit()
    flash('تم تحديث التصنيف', 'ok')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/sections/<int:sec_id>/delete', methods=['POST'])
@admin_required
def delete_section(sec_id):
    sec = db.session.get(Section, sec_id) or abort(404)
    for doc in sec.documents:
        _remove_file(doc.filename)
    db.session.delete(sec)
    db.session.commit()
    flash('تم حذف التصنيف وجميع ملفاته', 'ok')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/documents', methods=['POST'])
@admin_required
def upload_document():
    sec = db.session.get(Section, request.form.get('section_id', type=int)) or abort(404)
    title = (request.form.get('title') or '').strip()
    file = request.files.get('file')
    if not title or not file or not file.filename:
        flash('اكتب عنوان الملف واختر الملف', 'error')
        return redirect(url_for('admin_dashboard'))
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        flash('نوع الملف غير مسموح (المسموح: PDF, Word, Excel, صور)', 'error')
        return redirect(url_for('admin_dashboard'))
    stored = f'{uuid.uuid4().hex}.{ext}'
    path = os.path.join(app.config['UPLOAD_FOLDER'], stored)
    file.save(path)
    date_label = (request.form.get('date_label') or '').strip() \
        or datetime.now().strftime('%Y/%m/%d') + 'م'
    db.session.add(Document(section_id=sec.id, title=title, filename=stored,
                            orig_name=secure_filename(file.filename) or stored,
                            size=os.path.getsize(path), date_label=date_label))
    db.session.commit()
    flash(f'تم رفع «{title}» تحت تصنيف «{sec.name}»', 'ok')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/documents/<int:doc_id>/delete', methods=['POST'])
@admin_required
def delete_document(doc_id):
    doc = db.session.get(Document, doc_id) or abort(404)
    _remove_file(doc.filename)
    db.session.delete(doc)
    db.session.commit()
    flash('تم حذف الملف', 'ok')
    return redirect(url_for('admin_dashboard'))


def _remove_file(filename):
    try:
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    except OSError:
        pass


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
