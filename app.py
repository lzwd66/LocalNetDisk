# app.py
import os
import random
import math
import io
import zipfile
import tempfile
import shutil
import re
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import Flask, send_from_directory, request, render_template, redirect, abort, after_this_request, send_file

app = Flask(__name__)

# ===== 配置区域 Config Area =====
# 要共享的根目录（绝对路径或相对路径） Direction to share (absolute or relative path)
# 例如 Such as：BASE_DIR = os.path.abspath("./shared_files")
BASE_DIR = os.path.abspath("./shared")   # 默认程序目录下的 shared 文件夹 Default "shared" folder in the program directory
# 若该文件夹不存在，自动创建 If the folder does not exist, it will be created automatically
if not os.path.exists(BASE_DIR):
    os.makedirs(BASE_DIR)
    # 创建示例文件 Create example files
    with open(os.path.join(BASE_DIR, "example.txt"), "w", encoding="utf-8") as f:
        f.write("这是根目录下的示例文件。\nThis is an example file in the root directory.\n您可以创建文件夹和上传文件到此目录。\nYou can create folders and upload files to this directory.")
    with open(os.path.join(BASE_DIR, "欢迎.txt"), "w", encoding="utf-8") as f:
        f.write("局域网文件共享服务已启动。\nLAN File Sharing Service is running.")

# 允许访问的文件扩展名（None 表示无限制）
# Allowed file extensions (None means no restriction)
# 例如设置 For example: {'.txt', '.pdf', '.jpg', '.mp4'}
ALLOWED_EXTENSIONS = None
# ===================

def get_file_size(size_bytes):
    # 将字节转换为人类可读格式
    # Turn bytes into human-readable format
    if size_bytes == 0:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

def safe_join(base, subpath):
    # 安全拼接路径，确保最终路径在 base 内 Safely join paths, ensuring the final path is within base
    # 规范化基础路径和子路径 Normalize base and subpath
    base = os.path.realpath(base)
    # 将子路径中的 / 替换为 os.sep，并去除开头的分隔符 Replace / in subpath with os.sep and remove leading separator
    subpath = subpath.replace('/', os.sep)
    if subpath.startswith(os.sep):
        subpath = subpath[1:]
    target = os.path.realpath(os.path.join(base, subpath))
    if not target.startswith(base):
        return None   # 路径穿越攻击 Path traversal attack
    return target

def get_server_ip():
    # 获取本机局域网IP（简易方法） The most straightforward way to get the local IP address on the LAN
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "无法自动获取 Can not automatically get IP"
    finally:
        s.close()
    return ip

@app.route('/')
@app.route('/browse/')
@app.route('/browse/<path:subpath>')
def browse(subpath=""):
    # 浏览目录，显示文件和文件夹列表 Browse directory, showing files and folders list
    # 安全拼接路径 Safely join paths
    target_path = safe_join(BASE_DIR, subpath)
    if target_path is None or not os.path.exists(target_path):
        abort(404, description="路径不存在或访问被拒绝 Path does not exist or access denied")
    
    # 如果是文件，则直接下载（防止用户手动在URL后添加文件路径导致显示错误）
    # If it's a file, download it directly (prevent users from manually adding file paths in the URL causing display errors)
    if os.path.isfile(target_path):
        return download_file(subpath)
    
    # 是目录，列出内容
    # if it's a directory, list its contents
    items = []
    try:
        entries = os.listdir(target_path)
    except PermissionError:
        abort(403, description="无权限访问该目录")
    
    for entry in sorted(entries):
        full_entry = os.path.join(target_path, entry)
        # 隐藏以点开头的文件（可选）
        # Hide files starting with a dot (optional)
        if entry.startswith('.'):
            continue
        is_dir = os.path.isdir(full_entry)
        # 构建相对路径用于URL
        # Construct relative path for URL
        rel_path = os.path.join(subpath, entry) if subpath else entry
        rel_path = rel_path.replace(os.sep, '/')  # Windows兼容 Windows compatibility
        
        item = {
            'name': entry,
            'url': f"/browse/{rel_path}" if is_dir else f"/download/{rel_path}",
            'download_url': f"/download_folder/{rel_path}" if is_dir else None,
            'is_dir': is_dir,
            'size_human': get_file_size(os.path.getsize(full_entry)) if not is_dir else "",
            'mtime_str': datetime.fromtimestamp(os.path.getmtime(full_entry)).strftime("%Y-%m-%d %H:%M:%S")
        }
        items.append(item)
    
    # 计算上级目录URL Calculate parent directory URL
    parent_dir = None
    if subpath:
        # 去掉最后一级路径 Remove the last level of the path
        parent = os.path.dirname(subpath)
        parent_dir = f"/browse/{parent}" if parent else "/browse/"
    
    # 显示当前路径（美化） Display current path (beautify)
    display_path = subpath if subpath else "/"
    server_ip = get_server_ip()
    port = app.config.get('PORT', 5000)
    
    return render_template(
        'file_t_index.html',
        items=items,
        current_path=subpath,
        display_path=display_path,
        parent_dir=parent_dir,
        server_ip=server_ip,
        port=port
    )

@app.route('/download/<path:filepath>')
def download_file(filepath):
    # 下载文件（安全发送） Download file (safely send)
    # 安全拼接路径 Safely join paths
    target_path = safe_join(BASE_DIR, filepath)
    if target_path is None:
        abort(404)
    if not os.path.isfile(target_path):
        abort(404, description="文件不存在 File does not exist")
    
    # 可选：检查扩展名限制
    # Optional: Check extension restrictions
    if ALLOWED_EXTENSIONS is not None:
        ext = os.path.splitext(target_path)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            abort(403, description="不允许下载此类型文件 Downloading this type of file is not allowed")
    
    # 使用 send_from_directory 安全发送（需要目录和文件名分开）
    # Use send_from_directory to safely send (requires directory and filename separately)
    directory = os.path.dirname(target_path)
    filename = os.path.basename(target_path)
    return send_from_directory(directory, filename, as_attachment=True)

@app.route('/download_folder/<path:folderpath>')
def download_folder(folderpath):
    # 将文件夹打包为临时 ZIP 文件并下载，请求结束后删除临时文件
    # Package the folder into a temporary ZIP file and download it, then delete the temporary file after the request is finished
    target_path = safe_join(BASE_DIR, folderpath)
    if target_path is None or not os.path.isdir(target_path):
        abort(404, description="文件夹不存在或访问被拒绝 Folder does not exist or access denied")
    
    # 创建临时 ZIP 文件（使用 tempfile，自动保证唯一且不冲突）
    # Create a temporary ZIP file (using tempfile, automatically ensures uniqueness and no conflicts)
    temp_fd, temp_zip_path = tempfile.mkstemp(suffix='.zip', prefix='folder_')
    os.close(temp_fd)  # 关闭文件描述符，让 zipfile 打开 Close the file descriptor so that zipfile can open it
    
    try:
        # 将文件夹内容压缩到临时 ZIP 文件
        # Compress the folder contents into the temporary ZIP file
        with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(target_path):
                for file in files:
                    full_path = os.path.join(root, file)
                    # 计算在 ZIP 中的相对路径（保持文件夹结构）
                    # Calculate the relative path in the ZIP (keep folder structure)
                    arcname = os.path.relpath(full_path, start=os.path.dirname(target_path))
                    zf.write(full_path, arcname=arcname)
        
        # 发送文件，并在请求结束后删除临时文件
        # Send the file and delete the temporary file after the request is finished
        @after_this_request
        def cleanup(response):
            try:
                os.remove(temp_zip_path)
            except Exception as e:
                app.logger.warning(f"删除临时 ZIP 文件失败: {e}")
            return response
        
        # 确定下载文件名（文件夹名.zip）
        # Determine the download filename (foldername.zip)
        folder_name = os.path.basename(target_path)
        download_name = f"{folder_name}.zip"
        
        return send_file(
            temp_zip_path,
            as_attachment=True,
            download_name=download_name,
            mimetype='application/zip'
        )
    except Exception as e:
        # 如果出错，清理临时文件 If an error occurs, clean up the temporary file
        if os.path.exists(temp_zip_path):
            os.remove(temp_zip_path)
        abort(500, description=f"打包失败: {str(e)}")

def safe_filename(filename):
    """
    安全处理文件名：保留扩展名，只对基本名进行安全过滤
    Safely handle filenames: keep the extension, only apply secure filtering to the base name
    例如 For example "a.zip" -> "a.zip"；"a b.zip" -> "a_b.zip"
    """
    # 分离基本名和扩展名（最后一个点号）
    # Split the base name and extension (last dot)
    base, ext = os.path.splitext(filename)
    # 对基本名进行安全过滤（替换危险字符，保留字母数字、点号、下划线）
    # Securely filter the base name (replace dangerous characters, keep alphanumeric, dots, underscores)
    safe_base = secure_filename(base)
    # 如果过滤后基本名为空（例如文件名是 ".gitignore"），则使用下划线
    # If the safe base is empty after filtering (e.g., filename is ".gitignore"), use an underscore
    if not safe_base:
        safe_base = "_"
    return safe_base + ext

def get_unique_filename(directory, filename):
    """
    如果文件名已存在，自动添加序号，如 file.txt -> file(1).txt
    If the filename already exists, automatically add a number, such as file.txt -> file(1).txt
    """
    safe_name = safe_filename(filename)
    name, ext = os.path.splitext(safe_name)
    counter = 1
    new_filename = safe_name
    while os.path.exists(os.path.join(directory, new_filename)):
        new_filename = f"{name}({counter}){ext}"
        counter += 1
    return new_filename

@app.route('/upload', methods=['POST'])
def upload_file():
    # 处理文件上传，保存到当前浏览的目录 Handle file upload, save to the currently browsed directory
    # 获取目标目录（从表单字段 current_path 获取） Get the target directory (from the form field current_path)
    current_path = request.form.get('current_path', '')
    # 安全拼接目标目录 Safely join the target directory
    target_dir = safe_join(BASE_DIR, current_path)
    if target_dir is None or not os.path.isdir(target_dir):
        abort(400, description="无效的目录路径 Invalid directory path")

    # 检查是否有文件被上传 Check if a file was uploaded
    if 'file' not in request.files:
        abort(400, description="没有选择文件 No file selected")
    
    file = request.files['file']
    if file.filename == '':
        abort(400, description="文件名为空 File name is empty")
    
    # 安全处理文件名（移除危险字符） Safely handle the filename (remove dangerous characters)
    unique_filename = get_unique_filename(target_dir, file.filename)
    if not unique_filename:
        abort(400, description="无效的文件名 Invalid filename")
    
    # Save file
    save_path = os.path.join(target_dir, unique_filename)
    file.save(save_path)
    
    # 上传成功后重定向回原来的目录 Redirect back to the original directory after successful upload
    return redirect(f"/browse/{current_path}" if current_path else "/")
    
#Test which university is suit for you
@app.route('/test_university', methods=['GET', 'POST'])
def test_university():
    if request.method == 'POST':
        university = request.form.get('university', '').strip()
        # Generate random int to create a sence of variaton
        match_percent = random.randint(80, 100)
        match_percent = 10002221
        return render_template('result.html', university=university, match_percent=match_percent)
    return render_template('test_university.html')

if __name__ == '__main__':
    port = 5000
    app.config['PORT'] = port
    print(f"共享根目录: {BASE_DIR}")
    print(f"服务器启动: http://127.0.0.1:{port}")
    print(f"局域网访问: http://{get_server_ip()}:{port}")
    # debug=False, To ensure security and enhance efficiency
    app.run(host='0.0.0.0', port=port, debug=False)
