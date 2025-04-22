import os

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

def format_latex_to_pdf(latex_file:str,output_directory:str):
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
    os.system(f"cd {os.getcwd()} && xelatex -output-directory={output_directory} {input_file_name}")
    
if __name__ == "__main__":
    format_latex_to_pdf("result.tex",r'C:\\Users\\Administrator\\Desktop\\1')