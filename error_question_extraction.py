import asyncio
import os
import base64
import re
import cv2
import numpy as np
from typing import List 

from openai import OpenAI  
from dotenv import load_dotenv
import shutil

load_dotenv()
openai_api_key = os.getenv("DASHSCOPE_API_KEY")  # 读取 OpenAI API Key
print(f"api_key is {openai_api_key}")
base_url = os.getenv("BASE_URL")  # 读取 BASE URL
model = os.getenv("MODEL")  # 读取 model
print(f"model is {model}")
client = OpenAI(api_key=openai_api_key, base_url=base_url) # 创建OpenAI client
basic_msg =  [
    {"role": "system", "content": """你是错题提取助手，能从图片中提取出错题，不要尝试理解题目，仅仅提取文字"""}
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


def extract_multiple_green_boxes_from_single_picture(picture:str):
    img = cv2.imread(picture)
    if img is None:
        print("无法读取图片，请检查路径")
        return []
    # 转换到HSV颜色空间
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    # 定义绿色的HSV范围（可能需要根据具体图片调整）
    lower_green = np.array([35, 50, 50])   # H:35~85, S≥50, V≥50
    upper_green = np.array([85, 255, 255])
    
    # 创建掩码
    green_mask = cv2.inRange(hsv, lower_green, upper_green)
    
    # 应用形态学操作使矩形框更完整
    kernel = np.ones((3, 3), np.uint8)
    green_mask = cv2.morphologyEx(green_mask, cv2.MORPH_CLOSE, kernel)
    green_mask = cv2.morphologyEx(green_mask, cv2.MORPH_OPEN, kernel)
    
    # 寻找轮廓
    contours, _ = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        print("未检测到红色矩形框")
        return []
    result = [] 
    # 设置最小轮廓面积阈值，过滤掉噪声
    min_contour_area = 100  # 可以根据需要调整
    # 遍历所有找到的轮廓
    for i,contour in enumerate(contours):
        # 过滤小轮廓
        if cv2.contourArea(contour) < min_contour_area:
            continue
        
        # 获取矩形边界
        x, y, w, h = cv2.boundingRect(contour)
        
        # 为了确保我们捕获了框内的内容，可以稍微缩小区域（避免包含红线）
        padding = 2  # 向内缩小的像素数
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
        result.append(cropped_img)
    return result
        
        
def extract_multiple_green_boxes_from_pictures(pictues:List[str], output_dir="extracted_images"):
    # 创建输出目录
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    cropped_images = []
    cropped_image_names = []
    # 读取图片
    count = 0  
    for p in pictues:
        cropped_images.extend(extract_multiple_green_boxes_from_single_picture(p))
    for img in cropped_images:
        picture_name = f"cropped_{count}.jpg"
        cropped_image_names.append(picture_name)
        output_path = os.path.join(output_dir, picture_name)
        cv2.imwrite(output_path, img)
        print(f"已保存矩形框 {count+1} 的内容到 {output_path}")       
        count += 1
    return cropped_image_names

def generate_message_content_of_pictures(pictures:list)->object:
    msg_content = []
    for p in pictures:
       #把p所指向的文件base64成image_data
       image_data = base64.b64encode(open(p, 'rb').read()).decode("utf-8")
       msg_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}) 
    return msg_content
def clear_context():
    message = {"role": "user",    "content": "现在不考虑之前的图片了，请重新开始。"}
    completion = client.chat.completions.create(model=model,messages=[message],stream=True,temperature=0)

def extact_error_question_of_latex_format(pictures:List[str])->str:
    print(f"提交的图的数量为{len(pictures)}")
    message = make_user_message(pictures)
    #把message追加到basic_msg，不要改变basic_msg
    commit_message = basic_msg+[message]    
    
    completion = client.chat.completions.create(model=model,messages=commit_message,stream=True,temperature=0)
    return get_latex_str_from_model_completion(completion)

def get_latex_str_from_model_completion(completion):
    answer_content=""
    reasoning_content=""
    is_answering = False
    latex_content=""
    for chunk in completion:
    # 如果chunk.choices为空，则打印usage
        if not chunk.choices:
            print("\nUsage:")
            print(chunk.usage)
        else:
            delta = chunk.choices[0].delta
            # 打印思考过程
            if hasattr(delta, 'reasoning_content') and delta.reasoning_content != None:
                print(delta.reasoning_content, end='', flush=True)
                reasoning_content += delta.reasoning_content
            else:
                # 开始回复
                if delta.content != "" and is_answering is False:
                    print("\n" + "=" * 20 + "完整回复" + "=" * 20 + "\n")
                    is_answering = True
                # 打印回复过程
                print(delta.content, end='', flush=True)
                if delta.content is not None:
                    answer_content += delta.content
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
    return latex_content

def make_user_message(pictures):    
    msg_content = [{"type": "text", "text": """ 仅从图片中提取红圈标注的题号对应的题干及选项，
- 尽可能还原原来的题目，不要扩展和续写
- 不要提取题目引用的图片
- 对于 **填空题**，**保留下划线占位**，不要在下划线里填写任何答案；
- 不把题目中的省略号按照规律展开，例如 1 2 3 ...,不展开成1 2 3 4 5 6 ...；
- 不提取解题过程，也不提取任何手写答案或括号内的解答；
生成完整的 LaTeX 文档，documentclass[12pt]{ctexart}，导言区加载 `amsmath,amssymb,enumitem,xcolor,graphicx,float`。
"""}]
    #把一个list中的每个元素，都追加到msg_content中
    msg_content.extend(generate_message_content_of_pictures(pictures))
    message = {"role": "user",    "content": msg_content}
    return message

    
def write_to_latex_file(latex_content:str,latex_file_name:str,output_directory:str):
    """
    把latex字符串写入指定目录的指定文件中
    参数:
    -latex_content:latex字符串
    -latex_file_name:要写入的文件名
    -output_directory:要写入的目录
    返回:
    -
    """
    #把目录和文件名连在一起
    output_file_name = os.path.join(output_directory,latex_file_name)
    with open(output_file_name, 'w', encoding='utf-8') as f:
         f.write(latex_content)
         print("\n📝 生成的 LaTeX 文件已保存到latex文件中")
def merge_graphics_to_latex(src_latex:str,graphic_pathes:List[str])->str:
    """
    把多附图让大模型插入到既有的latex中
    返回:插入附图之后的latex
    """
    pictures_msg = generate_message_content_of_pictures(graphic_pathes)
    #根据图片的路径获取图片的文件名到列表中
    picture_names = [os.path.basename(picture) for picture in graphic_pathes]
    msg_content = [{"type": "text", "text": f""" 请把附图插入到{src_latex}合理的位置，生成新的latex文件,附图的文件名使用{picture_names} """}]
    msg_content.extend(pictures_msg)
    message = {"role": "user",    "content": msg_content}
    completion = client.chat.completions.create(model=model,messages=[message],stream=True,temperature=0)
    return get_latex_str_from_model_completion(completion=completion)
    
def add_latex_figures_with_images(src, image_names):
    """
    在完整的 LaTeX 文档的 `\end{document}` 之前，添加指定名称的图片作为占位符。

    参数:
        src (str): 完整可编译的 LaTeX 文档字符串。
        image_names (list of str): 图片名称数组，每个名称对应一个图片文件。

    返回:
        str: 修改后的完整 LaTeX 文档字符串。
    """
    # 定义 figure 环境模板，动态插入图片名称
    figure_template = r"""
\begin{figure}[h!]
    \centering
    \includegraphics[width=0.9\linewidth]{%s}
\end{figure}
"""

    # 构建所有 figure 环境
    figures = ""
    for image_name in image_names:
        figures += figure_template % (image_name)

    # 在 \end{document} 之前插入 figure 环境
    if r"\end{document}" in src:
        src = src.replace(r"\end{document}", figures + "\n\\end{document}")
    else:
        raise ValueError("The provided LaTeX source does not contain \\end{document}.")

    return src

def format_latex_to_pdf(latex_file:str,output_directory:str,pdf_name,pdf_path):
    """
    把latex文件编译成pdf文件
    参数:
    -latex_file:latex文件名
    -output_directory:要写入pdf文件的目录
    返回:
    -
    """
    #执行命令行 xelatex a.tex
    input_file_name = os.path.join(output_directory,latex_file)
    os.system(f"cd {output_directory} && xelatex -jobname={pdf_name} {input_file_name}")
    shutil.move(os.path.join(output_directory,pdf_name+'.pdf'), pdf_path)
    print("\n📝 生成的 LaTeX 文件已转换为pdf文件")
                 
if __name__ == "__main__":
    import sys
                              
    