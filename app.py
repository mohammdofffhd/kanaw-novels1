from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os, ssl

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kanaw-novels-2026-secret'

# ==========================================
# إعداد قاعدة البيانات (Neon + pg8000)
# ==========================================
db_url = os.environ.get('DATABASE_URL', 'sqlite:///kanaw.db')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)

if db_url.startswith('postgresql://'):
    db_url = db_url.split('?')[0]
    db_url = db_url.replace('postgresql://', 'postgresql+psycopg2://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'connect_args': {'sslmode': 'require'}
    }
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'يجب تسجيل الدخول أولاً'
login_manager.login_message_category = 'warning'

# ==========================================
# نظام الرتب والمستويات (60 مستوى)
# ==========================================
MAX_LEVEL = 60
XP_PER_CHAPTER = 7

def xp_needed(level):
    return 300 + (level - 1) * 200

LEVEL_THRESHOLDS = [0]
for _i in range(1, MAX_LEVEL + 1):
    LEVEL_THRESHOLDS.append(LEVEL_THRESHOLDS[-1] + xp_needed(_i))

def get_rank(level):
    if level <= 10: return ("مبتدئ", "🌱")
    if level <= 20: return ("عادي", "📗")
    if level <= 30: return ("متمرس", "📘")
    if level <= 40: return ("خبير", "📙")
    if level <= 50: return ("أسطوري", "🔥")
    return ("سلف القراء", "👑")

# ==========================================
# الموديلات
# ==========================================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    xp = db.Column(db.Integer, default=0)
    level = db.Column(db.Integer, default=1)
    last_checkin = db.Column(db.DateTime)
    checkin_streak = db.Column(db.Integer, default=0)
    chapters_read = db.Column(db.Integer, default=0)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def xp_progress(self):
        if self.level >= MAX_LEVEL: return 100
        cur = LEVEL_THRESHOLDS[self.level - 1]
        nxt = LEVEL_THRESHOLDS[self.level]
        span = nxt - cur
        if span <= 0: return 0
        return max(0, min(100, int(((self.xp - cur) / span) * 100)))

    @property
    def xp_remaining(self):
        if self.level >= MAX_LEVEL: return 0
        return max(0, LEVEL_THRESHOLDS[self.level] - self.xp)

    @property
    def rank_name(self): return get_rank(self.level)[0]
    @property
    def rank_icon(self): return get_rank(self.level)[1]

    @property
    def can_checkin(self):
        if not self.last_checkin: return True
        return self.last_checkin.date() < datetime.utcnow().date()

class Novel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    author = db.Column(db.String(200), default='غير معروف')
    description = db.Column(db.Text, default='')
    cover_url = db.Column(db.String(500), default='')
    category = db.Column(db.String(100), default='عام')
    status = db.Column(db.String(50), default='مكتملة')
    source = db.Column(db.String(50), default='manual')
    source_id = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    chapters = db.relationship('Chapter', backref='novel', lazy=True, cascade='all, delete-orphan', order_by='Chapter.number')

class Chapter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    novel_id = db.Column(db.Integer, db.ForeignKey('novel.id'), nullable=False)
    number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(300))
    content = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Favorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    novel_id = db.Column(db.Integer, db.ForeignKey('novel.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    novel = db.relationship('Novel', backref='favorited_by')
    __table_args__ = (db.UniqueConstraint('user_id', 'novel_id', name='unique_fav'),)

class ReadingHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'), nullable=False)
    novel_id = db.Column(db.Integer, db.ForeignKey('novel.id'), nullable=False)
    read_at = db.Column(db.DateTime, default=datetime.utcnow)
    chapter = db.relationship('Chapter')
    novel = db.relationship('Novel')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def add_xp(user, amount):
    user.xp = (user.xp or 0) + amount
    new_level = 1
    for i, threshold in enumerate(LEVEL_THRESHOLDS):
        if user.xp >= threshold: new_level = i + 1
        else: break
    user.level = min(new_level, MAX_LEVEL)
    db.session.add(user)

@app.context_processor
def inject_globals():
    return {'now': datetime.utcnow(), 'max_level': MAX_LEVEL}

# ==========================================
# المسارات (Routes)
# ==========================================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if len(username) < 4:
            flash('اسم المستخدم يجب أن يكون 4 أحرف على الأقل', 'danger')
        elif len(password) < 9:
            flash('كلمة المرور يجب أن تكون 9 أحرف على الأقل', 'danger')
        elif User.query.filter_by(username=username).first():
            flash('اسم المستخدم محجوز', 'danger')
        else:
            user = User(username=username)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash(f'مرحباً {username}! ابدأ رحلتك كمبتدئ 🌱', 'success')
            return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username', '').strip()).first()
        if user and user.check_password(request.form.get('password', '')):
            login_user(user)
            flash(f'مرحباً بعودتك {user.username}!', 'success')
            return redirect(request.args.get('next') or url_for('index'))
        flash('اسم المستخدم أو كلمة المرور خاطئة', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/api/checkin', methods=['POST'])
@login_required
def api_checkin():
    if not current_user.can_checkin:
        return jsonify({'success': False, 'message': 'سجلت حضورك اليوم بالفعل'})
    if current_user.last_checkin and current_user.last_checkin.date() == (datetime.utcnow().date() - timedelta(days=1)):
        current_user.checkin_streak += 1
    else:
        current_user.checkin_streak = 1
    xp_reward = 15 + (current_user.checkin_streak - 1) * 5
    current_user.last_checkin = datetime.utcnow()
    add_xp(current_user, xp_reward)
    db.session.commit()
    return jsonify({'success': True, 'xp': xp_reward, 'streak': current_user.checkin_streak, 'message': f'حصلت على {xp_reward} XP!'})

@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    q = request.args.get('q', '').strip()
    cat = request.args.get('cat', '').strip()
    query = Novel.query
    if q: query = query.filter(Novel.title.contains(q) | Novel.author.contains(q))
    if cat: query = query.filter(Novel.category == cat)
    novels = query.order_by(Novel.created_at.desc()).paginate(page=page, per_page=24, error_out=False)
    categories = [c[0] for c in db.session.query(Novel.category).distinct().all() if c[0]]
    return render_template('index.html', novels=novels, q=q, current_cat=cat, categories=categories)

@app.route('/novel/<int:novel_id>')
def novel_page(novel_id):
    novel = Novel.query.get_or_404(novel_id)
    is_fav = False
    if current_user.is_authenticated:
        is_fav = bool(Favorite.query.filter_by(user_id=current_user.id, novel_id=novel_id).first())
    return render_template('novel.html', novel=novel, is_favorite=is_fav)

@app.route('/read/<int:chapter_id>')
def read_chapter(chapter_id):
    ch = Chapter.query.get_or_404(chapter_id)
    if current_user.is_authenticated:
        existing = ReadingHistory.query.filter_by(user_id=current_user.id, chapter_id=ch.id).first()
        if existing:
            existing.read_at = datetime.utcnow()
        else:
            db.session.add(ReadingHistory(user_id=current_user.id, chapter_id=ch.id, novel_id=ch.novel_id))
            add_xp(current_user, XP_PER_CHAPTER)
            current_user.chapters_read = (current_user.chapters_read or 0) + 1
        db.session.commit()
    all_chapters = ch.novel.chapters
    idx = next((i for i, c in enumerate(all_chapters) if c.id == ch.id), -1)
    prev_ch = all_chapters[idx - 1] if idx > 0 else None
    next_ch = all_chapters[idx + 1] if idx < len(all_chapters) - 1 else None
    return render_template('chapter.html', chapter=ch, novel=ch.novel, prev_ch=prev_ch, next_ch=next_ch, all_chapters=all_chapters)

@app.route('/api/favorite/<int:novel_id>', methods=['POST'])
@login_required
def toggle_favorite(novel_id):
    Novel.query.get_or_404(novel_id)
    fav = Favorite.query.filter_by(user_id=current_user.id, novel_id=novel_id).first()
    if fav:
        db.session.delete(fav)
        db.session.commit()
        return jsonify({'success': True, 'favorited': False})
    db.session.add(Favorite(user_id=current_user.id, novel_id=novel_id))
    db.session.commit()
    return jsonify({'success': True, 'favorited': True})

@app.route('/favorites')
@login_required
def favorites():
    favs = Favorite.query.filter_by(user_id=current_user.id).order_by(Favorite.created_at.desc()).all()
    return render_template('favorites.html', favorites=favs)

@app.route('/history')
@login_required
def history():
    items = ReadingHistory.query.filter_by(user_id=current_user.id).order_by(ReadingHistory.read_at.desc()).limit(100).all()
    return render_template('history.html', history=items)

@app.route('/profile')
@login_required
def profile():
    favs = Favorite.query.filter_by(user_id=current_user.id).order_by(Favorite.created_at.desc()).all()
    history = ReadingHistory.query.filter_by(user_id=current_user.id).order_by(ReadingHistory.read_at.desc()).limit(30).all()
    return render_template('profile.html', favorites=favs, history=history)

# ==========================================
# لوحة التحكم
# ==========================================
@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin: return redirect(url_for('index'))
    return render_template('admin.html', novels=Novel.query.order_by(Novel.created_at.desc()).all())

@app.route('/admin/novel/new', methods=['POST'])
@login_required
def admin_new_novel():
    if not current_user.is_admin: return redirect(url_for('index'))
    title = request.form.get('title', '').strip()
    if title:
        novel = Novel(title=title, author=request.form.get('author', '').strip() or 'غير معروف', description=request.form.get('description', '').strip(), cover_url=request.form.get('cover_url', '').strip(), category=request.form.get('category', 'عام').strip() or 'عام', status=request.form.get('status', 'مكتملة'))
        db.session.add(novel)
        db.session.commit()
    return redirect('/admin')

@app.route('/admin/novel/<int:novel_id>')
@login_required
def admin_edit_novel(novel_id):
    if not current_user.is_admin: return redirect(url_for('index'))
    novel = Novel.query.get_or_404(novel_id)
    return render_template('admin.html', novels=Novel.query.order_by(Novel.created_at.desc()).all(), edit_novel=novel)

@app.route('/admin/novel/<int:novel_id>/chapter/new', methods=['POST'])
@login_required
def admin_new_chapter(novel_id):
    if not current_user.is_admin: return redirect(url_for('index'))
    novel = Novel.query.get_or_404(novel_id)
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    if title and content:
        num = (db.session.query(db.func.max(Chapter.number)).filter_by(novel_id=novel.id).scalar() or 0) + 1
        db.session.add(Chapter(novel_id=novel.id, number=num, title=title, content=content))
        db.session.commit()
    return redirect(f'/admin/novel/{novel.id}')

@app.route('/admin/novel/<int:novel_id>/delete', methods=['POST'])
@login_required
def admin_delete_novel(novel_id):
    if not current_user.is_admin: return redirect(url_for('index'))
    novel = Novel.query.get_or_404(novel_id)
    db.session.delete(novel)
    db.session.commit()
    return redirect('/admin')

@app.route('/admin/chapter/<int:chapter_id>/delete', methods=['POST'])
@login_required
def admin_delete_chapter(chapter_id):
    if not current_user.is_admin: return redirect(url_for('index'))
    ch = Chapter.query.get_or_404(chapter_id)
    novel_id = ch.novel_id
    db.session.delete(ch)
    db.session.commit()
    return redirect(f'/admin/novel/{novel_id}')

# ==========================================
# إنشاء الجداول والأدمن الافتراضي
# ==========================================
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='kanaw').first():
        admin = User(username='kanaw', is_admin=True)
        admin.set_password('0594683283')
        db.session.add(admin)
        db.session.commit()
        print('✅ تم إنشاء حساب المشرف: kanaw')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)