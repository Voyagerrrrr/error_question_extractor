import os
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from config import Config
from fpdf import FPDF
from datetime import datetime
from PIL import Image
import error_question_extraction
from openai import OpenAI  
from dotenv import load_dotenv
import shutil

app = Flask(__name__)
app.config.from_object(Config)
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

def create_pdf_from_images(image_paths, output_path, pdf_name,pdf_path):
    load_dotenv()
    openai_api_key = os.getenv("DASHSCOPE_API_KEY")  # 读取 OpenAI API Key
    #print(f"api_key is {openai_api_key}")
    base_url = os.getenv("BASE_URL")  # 读取 BASE YRL
    model = os.getenv("MODEL")  # 读取 model
    #print(f"model is {model}")
    client = OpenAI(api_key=openai_api_key, base_url=base_url) # 创建OpenAI client
    basic_msg =  [
        {"role": "system", "content": """你是初中生错题提取助手"""}
    ]
    pictures=[]
    for image_path in image_paths:
        pictures.append(image_path)
    # 创建临时目录
    temp_dir = os.path.join(app.config['TEMP_FOLDER'], f"{datetime.now().strftime('%Y%m%d%H%M%S')}")
    os.makedirs(temp_dir, exist_ok=True)
    image_num = error_question_extraction.extract_multiple_green_boxes(pictures, temp_dir)
    latex_content = error_question_extraction.extact_error_question_of_latex_format(pictures,image_num)  # 发送用户输入到 OpenAI API
    #print(f"\n🤖 OpenAI: {latex_content}")
    #将response写到result.tex文件中
    error_question_extraction.write_to_latex_file(latex_content,temp_dir,pdf_name,pdf_path)
    pictures=[]
    try:
        shutil.rmtree(temp_dir)
    except Exception as e:
        print(f"Error cleaning temp directory {temp_dir}: {e}")


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

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash('登录成功!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('用户名或密码错误', 'danger')
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

@app.route('/create_pdf', methods=['POST'])
def create_pdf():
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
            print('已选择'+image_id)
    
    if not image_paths:
        flash('文件异常！', 'danger')
        return redirect(url_for('gallery'))
    
    # 创建PDF
    pdf_filename = f"pdf_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    pdf_path = os.path.join(app.config['PDF_UPLOADS'], pdf_filename)
    
    create_pdf_from_images(image_paths, app.config['PDF_UPLOADS'],f"pdf_{datetime.now().strftime('%Y%m%d%H%M%S')}",pdf_path)
    
    # 保存PDF记录到数据库
    user_pdf = UserPDF(filename=pdf_filename, user_id=user.id)
    db.session.add(user_pdf)
    db.session.commit()
    
    flash('成功创建错题集！', 'success')
    return redirect(url_for('gallery'))

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
    app.run(debug=True)