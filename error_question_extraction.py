import asyncio
import os
import base64
import re
import cv2
import numpy as np
import matplotlib.pyplot as plt

from openai import OpenAI  
from dotenv import load_dotenv
import shutil

load_dotenv()
openai_api_key = os.getenv("DASHSCOPE_API_KEY")  # 读取 OpenAI API Key
print(f"api_key is {openai_api_key}")
base_url = os.getenv("BASE_URL")  # 读取 BASE YRL
model = os.getenv("MODEL")  # 读取 model
print(f"model is {model}")
client = OpenAI(api_key=openai_api_key, base_url=base_url) # 创建OpenAI client
basic_msg =  [
    {"role": "system", "content": """你是错题提取助手"""}
]
def color_to_white(image):
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    
    # 自适应直方图均衡化
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    enhanced = cv2.merge((l, a, b))
    img = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    lower_color = np.array([35, 50, 50])   # H:35~85, S≥50, V≥50
    upper_color = np.array([85, 255, 255])
    mask = cv2.inRange(hsv, lower_color, upper_color)
    kernel = np.ones((3, 3), np.uint8)
    
    # 后处理
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    
    img[mask > 0] = [255, 255, 255]  # BGR白色
    
    return img

def extract_multiple_green_boxes(image_path, output_dir="extracted_images"):
    # 创建输出目录
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # 读取图片
    count = 1
    for p in image_path:
        img = cv2.imread(p)
        if img is None:
            print("无法读取图片，请检查路径")
            return None
        
        # 保存原图副本用于显示
        original_img = img.copy()
        
        # 图像增强
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        enhanced = cv2.merge((l, a, b))
        img = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
        
        # 转换到HSV颜色空间
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        # 定义绿色的HSV范围（可能需要根据具体图片调整）
        lower_green = np.array([30, 40, 40])   # H:30~90, S≥40, V≥40
        upper_green = np.array([90, 255, 255])
        
        # 创建掩码
        green_mask = cv2.inRange(hsv, lower_green, upper_green)
        
        # 应用形态学操作使矩形框更完整
        kernel = np.ones((3, 3), np.uint8)  # 增大内核大小
        green_mask = cv2.morphologyEx(green_mask, cv2.MORPH_CLOSE, kernel, iterations=2)  # 增加迭代次数
        green_mask = cv2.morphologyEx(green_mask, cv2.MORPH_OPEN, kernel, iterations=1)   # 增加迭代次数
        
        # 寻找轮廓
        contours, _ = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            print("未检测到矩形框")
            return 0
        
        # 用于存储结果
        cropped_images = []
        
        # 设置最小轮廓面积阈值，过滤掉噪声
        min_contour_area = 500  # 适当降低阈值
        # 遍历所有找到的轮廓
        for i, contour in enumerate(contours):
            # 过滤小轮廓
            if cv2.contourArea(contour) < min_contour_area:
                continue
            
            # 获取矩形边界
            x, y, w, h = cv2.boundingRect(contour)
            
            # 为了确保我们捕获了框内的内容，可以稍微缩小区域（避免包含红线）
            padding = 0  # 向内缩小的像素数
            x_inner = x + padding
            y_inner = y + padding
            w_inner = w - 2 * padding
            h_inner = h - 2 * padding
            
            # 确保不会超出图像边界
            x_inner = max(0, x_inner)
            y_inner = max(0, y_inner)
            w_inner = min(w_inner, img.shape[1] - x_inner)
            h_inner = min(h_inner, img.shape[0] - y_inner)
            
            # 截取图片
            cropped_img = color_to_white(img[y_inner:y_inner+h_inner, x_inner:x_inner+w_inner])
            
            # 在原图上标记已检测的区域
            cv2.rectangle(original_img, (x, y), (x+w, y+h), (0, 255, 0), 2)
            
            # 保存截取的图片
            output_path = os.path.join(output_dir, f"cropped_{count}.jpg")
            cv2.imwrite(output_path, cropped_img)
            cropped_images.append((cropped_img, output_path))
            print(f"已保存矩形框 {count} 的内容到 {output_path}")
            count += 1
    
    return count-1

def generate_message_content_of_pictures(pictures:list)->object:
    msg_content = []
    for p in pictures:
       #把p所指向的文件base64成image_data
       image_data = base64.b64encode(open(p, 'rb').read()).decode("utf-8")
       msg_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}) 
    return msg_content

def extact_error_question_of_latex_format(pictures:list[str], pictures_num:int)->str:
    message = make_user_message(pictures,pictures_num)
    #把message追加到basic_msg
    basic_msg.append(message)
    #print(f"msg is {basic_msg}")
    answer_content=""
    #reasoning_content=""
    #is_answering = False
    completion = client.chat.completions.create(model=model,messages=basic_msg,stream=True,temperature=0)
    latex_content=""
    for chunk in completion:
        if chunk.choices and hasattr(chunk.choices[0].delta, 'content'):
            content = chunk.choices[0].delta.content
            if content:
                print(content, end='', flush=True)
                answer_content += content

    #print("\n" + "=" * 20 + "回复结束" + "=" * 20)
    latex_content = answer_content.strip()
    #把latex_content中的image.png，替换成logo.png
    latex_content=latex_content.replace("image.png", "logo.png")
    
    pattern = r"(\\documentclass.*?\\end{document})"
    match = re.search(pattern, latex_content, flags=re.DOTALL)
    if match:
        latex_content = match.group(1)  # 提取匹配的部分
        print("%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%")
    else:
        latex_content = latex_content  # 如果没有匹配，返回原内容（可选）
        print("%%%%%7&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&%%%%%%%%%%%%%%") 
    #print(f"latex_content is {latex_content}")              
    return latex_content

def make_user_message(pictures, pictures_num):
    msg_content = [{"type": "text", "text": f"""
                    从试卷的图片中,提取出题目序号有红色圆圈的题干，只需要按顺序输出题目不需要划分题目类别，不要识别解题过程，不要给出答案
                    请生成严格的 LaTeX 代码,documentclass 设置为 [12pt]{{ctexart}},添加包{{amsmath, amssymb,enumitem,xcolor,grapgicx,multicol,float}},并根据latex内容添加必要的包，注意在需要打下划线'\_'时替换为括号，如果试卷中有绿色框选中的图片，则在排版时将这些图片统一添加引用至该试卷底部(如果图片属于选择题，则只需要将图片显示在选项位置，不需要展示在底部)，图片引用使用figure环境，加入关键字[H]进行固定，缩小摆放，三个一行。不同试卷需要另起一页。图片地址为当前目录，图片名为“cropped_1.jpg"，如果需要引用不止一张图，则按照"cropped_2.jpg","cropped_3.jpg"自动延续，本次一共只能引用{pictures_num}张图，不要超出
                    """}]
    #把一个list中的每个元素，都追加到msg_content中
    msg_content.extend(generate_message_content_of_pictures(pictures))
    message = {"role": "user",    "content": msg_content}
    return message

    
def write_to_latex_file(latex_content:str,output_directory:str,pdf_name,pdf_path):
    #把目录和文件名连在一起
    output_file_name = os.path.join(output_directory,"result.tex")
    with open(output_file_name, 'w', encoding='utf-8') as f:
        f.write(latex_content)

    print(output_directory," ", output_file_name, " ",pdf_path)
    #先编译到temp 目录，再移动到pdf目录
    os.system(f"cd {output_directory} && xelatex -jobname={pdf_name} {output_file_name}")
    shutil.move(os.path.join(output_directory,pdf_name+'.pdf'), pdf_path)
    print("\n📝 生成的 LaTeX 文件已转换为pdf文件")
    
    
                              
if __name__ == "__main__":
    import sys
   
    #asyncio.run(chat_loop(os.path.dirname(os.path.abspath(__file__))))