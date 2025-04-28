import os
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session, jsonify, abort
from flask_wtf.csrf import CSRFProtect
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_moment import Moment
import traceback
import redis
import base64
from datetime import timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from config import Config
from datetime import datetime
import error_question_extraction 
import shutil

app = Flask(__name__)
app.config['SECRET_KEY'] = '000000'  # 必须设置密钥
app.config.from_object(Config)
moment = Moment(app)
csrf = CSRFProtect(app)
limiter = Limiter(app)
Config.init_app(app)
db = SQLAlchemy(app)

# 数据库模型
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    images = db.relationship('UserImage', backref='user', lazy=True)
    pdfs = db.relationship('UserPDF', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class UserImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    upload_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class UserPDF(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    creation_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# 辅助函数
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_IMAGE_EXTENSIONS']
def extract_error_questions(image_paths):
    """提取错题图片和文本信息"""
    # 创建临时目录
    temp_dir = os.path.join(app.config['TEMP_FOLDER'], f"{datetime.now().strftime('%Y%m%d%H%M%S')}")
    os.makedirs(temp_dir, exist_ok=True)
    
    # 截取错题图片
    cropped_image_names = error_question_extraction.extract_multiple_green_boxes_from_pictures(image_paths, temp_dir)
    cropped_image_pathes = [os.path.join(temp_dir, name) for name in cropped_image_names]
    
    # 提取文本信息
    latex_content = error_question_extraction.extact_error_question_of_latex_format(image_paths)
    
    return {
        'temp_dir': temp_dir,
        'cropped_images': cropped_image_pathes,
        'latex_content': latex_content
    }

def generate_pdf_from_selection(temp_dir, latex_content, selected_images, pdf_path):
    """根据用户选择生成PDF"""
    try:
        # 组合文本和图片
        if selected_images and len(selected_images) > 0:
            latex_content = error_question_extraction.merge_graphics_to_latex(latex_content, selected_images)
        
        # 写出到.tex文件
        latex_file_path = 'result.tex'
        error_question_extraction.write_to_latex_file(latex_content, latex_file_path, temp_dir)
        
        # 编译为pdf
        pdf_name = f"pdf_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        exit_code = error_question_extraction.format_latex_to_pdf(latex_file_path, temp_dir, pdf_name, pdf_path)
        
    finally:
        # 清理临时文件
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            print(f"Error cleaning temp directory {temp_dir}: {e}")
    return exit_code

@app.context_processor
def inject_datetime():
    from datetime import datetime, timedelta
    return dict(datetime=datetime, timedelta=timedelta)

@app.route('/preview_errors', methods=['POST'])
def preview_errors():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    selected_images = request.form.getlist('selected_images')
    
    if not selected_images:
        flash('请选择至少一张试卷！', 'danger')
        return redirect(url_for('gallery'))
    
    # 获取完整的图片路径
    image_paths = []
    for image_id in selected_images:
        image = UserImage.query.filter_by(id=image_id, user_id=user.id).first()
        if image:
            image_paths.append(os.path.join(app.config['IMAGE_UPLOADS'], image.filename))
    
    if not image_paths:
        flash('文件异常！', 'danger')
        return redirect(url_for('gallery'))
    
    # 提取错题
    extraction_result = extract_error_questions(image_paths)
    
    # 将临时目录存入session以便后续使用
    session['temp_error_dir'] = extraction_result['temp_dir']
    session['latex_content'] = extraction_result['latex_content']
    
    # 准备预览数据
    preview_images = []
    for idx, img_path in enumerate(extraction_result['cropped_images']):
        # 将图片转为base64用于预览
        with open(img_path, "rb") as img_file:
            img_base64 = base64.b64encode(img_file.read()).decode('utf-8')
        preview_images.append({
            'id': idx,
            'data': f"data:image/png;base64,{img_base64}",
            'path': img_path
        })
    
    return render_template('preview_errors.html', preview_images=preview_images)

@app.route('/create_pdf_final', methods=['POST'])
def create_pdf_final():
    if 'user_id' not in session or 'temp_error_dir' not in session:
        return redirect(url_for('login'))
    
    # 获取用户选择的图片
    selected_preview_images = request.form.getlist('selected_errors')
    latex_content = session.get('latex_content')
    temp_dir = session['temp_error_dir']
    
    # 生成PDF
    pdf_filename = f"pdf_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    pdf_path = os.path.join(app.config['PDF_UPLOADS'], pdf_filename)
    
    exit_code = generate_pdf_from_selection(temp_dir, latex_content, selected_preview_images, pdf_path)
    if exit_code:
        # 保存PDF记录到数据库
        user = User.query.get(session['user_id'])
        user_pdf = UserPDF(filename=pdf_filename, user_id=user.id)
        db.session.add(user_pdf)
        db.session.commit()
        
        # 清理session
        session.pop('temp_error_dir', None)
        session.pop('latex_content', None)
        
        flash('成功创建错题集！', 'success')
        return redirect(url_for('gallery'))
    else:
        flash('创建异常', 'danger')
        return redirect(url_for('gallery'))

# 路由
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if password != confirm_password:
            flash('两次密码不一致！', 'danger')
            return redirect(url_for('register'))
        
        if User.query.filter_by(username=username).first():
            flash('用户名已被占用！', 'danger')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('该邮箱已经注册！', 'danger')
            return redirect(url_for('register'))
        
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('注册成功，请登录', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

r = redis.Redis(host="localhost", port=6379, db=0)
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")  # 每分钟最多 5 次
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if r.get(f"lock:{username}"):
            flash(f'账户已锁定，请 15 分钟后重试', 'danger')
            return redirect(url_for('login'))
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            r.delete(f"failed:{username}")  # 登录成功，清除失败计数
            flash('登录成功!', 'success')
            return redirect(url_for('dashboard'))
        else:
            failed_count = r.incr(f"failed:{username}")
            if failed_count >= 5:  # 输错 5 次锁定
                r.setex(f"lock:{username}", timedelta(minutes=15), "locked")
                flash(f'错误次数过多，账户已锁定', 'danger')
                return redirect(url_for('login'))

            flash(f'用户名或密码错误（剩余尝试次数：{5 - failed_count}）', 'danger')
            return redirect(url_for('login'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    flash('注销成功', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    recent_images = UserImage.query.filter_by(user_id=user.id).order_by(UserImage.upload_date.desc()).limit(5).all()
    recent_pdfs = UserPDF.query.filter_by(user_id=user.id).order_by(UserPDF.creation_date.desc()).limit(5).all()
    
    return render_template('dashboard.html', 
                         username=user.username, 
                         recent_images=recent_images, 
                         recent_pdfs=recent_pdfs)

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        if 'files' not in request.files:
            flash('选择一张试卷', 'danger')
            return redirect(request.url)
        
        files = request.files.getlist('files')
        user = User.query.get(session['user_id'])
        uploaded_files = []
        
        for file in files:
            if file.filename == '':
                continue
            
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                save_path = os.path.join(app.config['IMAGE_UPLOADS'], unique_filename)
                file.save(save_path)
                
                # 保存到数据库
                user_image = UserImage(filename=unique_filename, user_id=user.id)
                db.session.add(user_image)
                uploaded_files.append(unique_filename)
            else:
                flash(f'试卷{file.filename} 内容异常', 'warning')
        
        if uploaded_files:
            db.session.commit()
            flash(f'成功上传了 {len(uploaded_files)} 张试卷', 'success')
        
        return redirect(url_for('upload'))
    
    return render_template('upload.html')

@app.route('/gallery')
def gallery():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    images = UserImage.query.filter_by(user_id=user.id).order_by(UserImage.upload_date.desc()).all()
    pdfs = UserPDF.query.filter_by(user_id=user.id).order_by(UserPDF.creation_date.desc()).all()
    
    return render_template('gallery.html', images=images, pdfs=pdfs)

@app.route('/download/image/<int:image_id>')
def download_image(image_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    image = UserImage.query.filter_by(id=image_id, user_id=session['user_id']).first_or_404()
    return send_from_directory(app.config['IMAGE_UPLOADS'], image.filename, as_attachment=True)

@app.route('/download/pdf/<int:pdf_id>')
def download_pdf(pdf_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    pdf = UserPDF.query.filter_by(id=pdf_id, user_id=session['user_id']).first_or_404()
    return send_from_directory(app.config['PDF_UPLOADS'], pdf.filename, as_attachment=True)

@app.route('/delete/image/<int:image_id>', methods=['POST'])
def delete_image(image_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    image = UserImage.query.filter_by(id=image_id, user_id=session['user_id']).first_or_404()
    
    # 删除文件
    try:
        os.remove(os.path.join(app.config['IMAGE_UPLOADS'], image.filename))
    except OSError:
        pass
    
    # 删除数据库记录
    db.session.delete(image)
    db.session.commit()
    
    flash('成功删除试卷！', 'success')
    return redirect(url_for('gallery'))

@app.route('/delete/pdf/<int:pdf_id>', methods=['POST'])
def delete_pdf(pdf_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    pdf = UserPDF.query.filter_by(id=pdf_id, user_id=session['user_id']).first_or_404()
    
    # 删除文件
    try:
        os.remove(os.path.join(app.config['PDF_UPLOADS'], pdf.filename))
    except OSError:
        pass
    
    # 删除数据库记录
    db.session.delete(pdf)
    db.session.commit()
    
    flash('成功删除错题集！', 'success')
    return redirect(url_for('gallery'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0',port=5000,debug=True)
