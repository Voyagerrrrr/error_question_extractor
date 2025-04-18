import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads')
    IMAGE_UPLOADS = os.path.join(UPLOAD_FOLDER, 'images')
    PDF_UPLOADS = os.path.join(UPLOAD_FOLDER, 'pdfs')
    ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 尺寸限制
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    TEMP_FOLDER = os.path.join(UPLOAD_FOLDER, 'temp')  # 添加临时文件夹
    @staticmethod
    def init_app(app):
        # 确保上传目录存在
        os.makedirs(app.config['IMAGE_UPLOADS'], exist_ok=True)
        os.makedirs(app.config['PDF_UPLOADS'], exist_ok=True)
        os.makedirs(app.config['TEMP_FOLDER'], exist_ok=True)  # 添加临时文件夹创建