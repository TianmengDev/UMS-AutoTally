import subprocess
import time
import os
import hmac
import hashlib
import base64
import urllib.parse
from PIL import Image, ImageEnhance
import requests
from datetime import datetime
import shutil
import re
import easyocr  # 替换 pytesseract

# 配置
ADB_PATH = "adb"  # ADB 命令路径，如果未添加到环境变量，改为完整路径
DEVICE_ID = ""  # 模拟器设备ID，通过 adb devices 获取
APP_PACKAGE = "com.chinaums.onlineservice"  # 银联商务包名
APP_ACTIVITY = "com.chinaums.onlineservice.ui.index.SplashActivity"  # 主活动名，需通过 adb logcat 确认
DINGTALK_WEBHOOK = ""  # 钉钉Webhook地址
DINGTALK_SECRET = ""  # 钉钉机器人密钥，用于签名认证
SCREENSHOT_PATH = "temp_screenshot.png"
CROPPED_PATH = "temp_cropped.png"
SCREENSHOT_DIR = "screenshots"
PHONE_SCREENSHOT_DIR = "/storage/emulated/0/ums/screenshot"  # 手机上截图保存路径

# 初始化 EasyOCR 阅读器 
reader = None
def get_ocr_reader():
    global reader
    if reader is None:
        print("初始化 EasyOCR 引擎...")
        # 只使用英文模型以加快识别速度，因为我们只需要识别数字
        reader = easyocr.Reader(['en'], gpu=False)
    return reader

# 二维码名称与相册坐标映射
QR_CODES = [
    {"name": "索桥拍照", "coord": (179, 871)},
    {"name": "木偶戏", "coord": (533, 871)},
    {"name": "索道拍照", "coord": (916, 871)},
    {"name": "漂流拍照", "coord": (1243, 871)},
    {"name": "索桥鞋套", "coord": (179, 1233)}
]

# ADB 命令执行封装
def run_adb_command(command):
    full_command = f"{ADB_PATH} -s {DEVICE_ID} {command}"
    result = subprocess.run(full_command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ADB 命令执行失败: {command}\n错误: {result.stderr}")
        return False
    return result.stdout

# 模拟点击（根据屏幕坐标）
def tap_screen(x, y):
    print(f"点击屏幕位置: ({x}, {y})")
    run_adb_command(f"shell input tap {x} {y}")
    time.sleep(1.5)  # 适当延长等待时间，确保界面响应

# 模拟按下返回键
def press_back():
    print("模拟按下返回键")
    run_adb_command("shell input keyevent 4")
    time.sleep(1.5)  # 等待界面响应

# 创建手机上的目标文件夹并添加 .nomedia 文件
def setup_phone_screenshot_dir():
    print(f"创建手机截图文件夹: {PHONE_SCREENSHOT_DIR}")
    run_adb_command(f"shell mkdir -p {PHONE_SCREENSHOT_DIR}")
    print("添加 .nomedia 文件以隐藏相册显示")
    run_adb_command(f"shell touch {PHONE_SCREENSHOT_DIR}/.nomedia")

# 截图并保存到手机指定路径和本地，添加文件验证和重试机制
def take_screenshot(save_path=None, name=None):
    print("截图中...")
    current_date = datetime.now().strftime('%Y-%m-%d')
    current_time = datetime.now().strftime('%H-%M-%S')
    # 使用时间戳避免文件名冲突
    screenshot_filename = f"{name}_{current_date}_{current_time}.png" if name else f"screenshot_{current_date}_{current_time}.png"
    phone_screenshot_path = f"{PHONE_SCREENSHOT_DIR}/{screenshot_filename}"
    
    # 尝试保存截图到手机
    for attempt in range(3):  # 最多重试3次
        print(f"尝试保存截图到手机 (第 {attempt+1} 次): {phone_screenshot_path}")
        result = run_adb_command(f"shell screencap {phone_screenshot_path}")
        if result is not False:
            # 验证文件是否存在
            check_result = run_adb_command(f"shell ls {phone_screenshot_path}")
            if check_result and phone_screenshot_path in check_result:
                print(f"截图已成功保存到手机: {phone_screenshot_path}")
                break
        else:
            print(f"截图保存失败，重试中...")
            time.sleep(2)
    else:
        print(f"多次尝试后截图保存失败: {phone_screenshot_path}")
        return False
    
    # 拉取到本地临时文件用于 OCR 识别
    for attempt in range(3):  # 最多重试3次
        print(f"尝试拉取截图到本地 (第 {attempt+1} 次): {SCREENSHOT_PATH}")
        result = run_adb_command(f"pull {phone_screenshot_path} {SCREENSHOT_PATH}")
        if result is not False and os.path.exists(SCREENSHOT_PATH):
            try:
                # 验证本地文件是否可打开
                Image.open(SCREENSHOT_PATH).verify()
                print(f"截图已成功拉取到本地: {SCREENSHOT_PATH}")
                break
            except Exception as e:
                print(f"本地截图文件损坏，无法打开: {str(e)}，重试中...")
                time.sleep(2)
        else:
            print(f"拉取截图失败，重试中...")
            time.sleep(2)
    else:
        print(f"多次尝试后截图拉取失败或文件损坏: {SCREENSHOT_PATH}")
        return False
    
    # 如果需要本地保存副本
    if save_path:
        try:
            shutil.copy(SCREENSHOT_PATH, save_path)
            print(f"截图已保存到本地副本: {save_path}")
        except Exception as e:
            print(f"保存本地副本失败: {str(e)}")
    
    return True

# 使用 EasyOCR 识别金额
def recognize_amount():
    print("识别金额中...")
    try:
        img = Image.open(SCREENSHOT_PATH)
        # 裁剪区域为 (512, 1058, 921, 1165)
        cropped = img.crop((512, 1058, 921, 1165))
        
        # 增强对比度
        enhancer = ImageEnhance.Contrast(cropped)
        cropped = enhancer.enhance(2.0)
        
        # 保存裁剪后的图像以便调试
        cropped.save(CROPPED_PATH)
        
        # 使用 EasyOCR 识别文本
        reader = get_ocr_reader()
        results = reader.readtext(CROPPED_PATH)
        print(f"EasyOCR 结果: {results}")
        
        # 提取识别结果
        if results:
            # EasyOCR 返回格式是：[(bbox, text, probability), ...]
            all_text = ' '.join([result[1] for result in results])
            print(f"合并文本: {all_text}")
            
            # 清理文本，只保留数字和点
            cleaned_text = ''.join([c for c in all_text if c.isdigit() or c == '.'])
            print(f"清理后文本: {cleaned_text}")
            
            # 使用正则表达式提取数字
            match = re.search(r'(\d+\.?\d*)', cleaned_text)
            if match:
                amount_str = match.group(1)
                # 处理提取到的文本
                if amount_str and amount_str != '.':
                    try:
                        return float(amount_str)
                    except ValueError:
                        print(f"转换为浮点数失败: {amount_str}")
            else:
                print(f"未从清理后文本中提取到数字: {cleaned_text}")
        else:
            print("EasyOCR 未识别到任何文本")
    except Exception as e:
        print(f"金额识别过程中发生错误: {str(e)}")
    return 0.0

# 发送钉钉通知，增加密钥认证
def send_dingtalk_message(message):
    print("发送钉钉通知...")
    try:
        # 获取当前时间戳（毫秒）
        timestamp = str(round(time.time() * 1000))
        # 计算签名
        sign_string = timestamp + "\n" + DINGTALK_SECRET
        sign = hmac.new(DINGTALK_SECRET.encode('utf-8'), sign_string.encode('utf-8'), digestmod=hashlib.sha256).digest()
        sign = base64.b64encode(sign).decode('utf-8')
        sign = urllib.parse.quote_plus(sign)
        
        # 构建带签名的 webhook URL
        webhook_url = f"{DINGTALK_WEBHOOK}&timestamp={timestamp}&sign={sign}"
        
        # 消息内容
        payload = {
            "msgtype": "text",
            "text": {"content": message}
        }
        
        # 发送请求
        response = requests.post(webhook_url, json=payload, timeout=10)
        result = response.json()
        if result.get("errcode") == 0:
            print("钉钉通知发送成功")
        else:
            print(f"钉钉通知发送失败: {result}")
    except Exception as e:
        print(f"钉钉通知发送过程中发生错误: {str(e)}")
        # 即使发送失败，也不会抛出异常影响主流程

# 获取今日日期命名的文件夹
def get_today_folder():
    today = datetime.now().strftime("%Y-%m-%d")
    folder = os.path.join(SCREENSHOT_DIR, today)
    if not os.path.exists(folder):
        os.makedirs(folder)
    return folder

# 执行扫码流程
def perform_scan(qr_info, index, is_first=False):
    print(f"处理第 {index} 个二维码: {qr_info['name']}")
    today_folder = get_today_folder()
    screenshot_name = f"scan_{index}_{qr_info['name']}_{datetime.now().strftime('%H-%M-%S')}.png"
    local_screenshot_path = os.path.join(today_folder, screenshot_name)
    
    if is_first:
        # 首次扫描流程
        tap_screen(190, 2908)  # 点击"对账"按钮（底部菜单栏）
        time.sleep(2)
        tap_screen(571, 1500)  # 点击"对账范围"
        time.sleep(2)
        tap_screen(1100, 396)  # 点击"收款码"
        time.sleep(2)
    else:
        # 后续扫描流程
        tap_screen(571, 1500)  # 点击"对账范围"
        time.sleep(2)
        tap_screen(1100, 396)  # 点击"收款码"
        time.sleep(2)
        tap_screen(1329, 885)  # 点击"移除"
        time.sleep(2)
    
    # 扫码流程
    tap_screen(716, 599)  # 点击"扫描收款码"
    time.sleep(2)
    tap_screen(1320, 244)  # 点击"相册"
    time.sleep(2)
    tap_screen(qr_info['coord'][0], qr_info['coord'][1])  # 选择对应二维码图片
    time.sleep(3)  # 等待扫码结果
    press_back()  # 使用原生返回键返回到上一级界面
    time.sleep(3)
    
    # 截图并识别金额
    success = take_screenshot(save_path=local_screenshot_path, name=qr_info['name'])
    if success:
        amount = recognize_amount()
    else:
        print(f"截图失败，无法识别金额: {qr_info['name']}")
        amount = 0.0
    print(f"第 {index} 个二维码金额: {amount}")
    return amount

# 启动APP
def start_app():
    print("启动银联商务APP...")
    result = run_adb_command(f"shell am start -n {APP_PACKAGE}/{APP_ACTIVITY}")
    print(f"启动结果: {result}")
    time.sleep(5)  # 等待APP启动

# 主流程
def main():
    # 初始化手机截图文件夹并隐藏相册显示
    setup_phone_screenshot_dir()
    
    amounts = []
    start_app()
    
    # 完成所有二维码的扫描和金额识别
    for i, qr_info in enumerate(QR_CODES, 1):
        is_first = (i == 1)
        try:
            amount = perform_scan(qr_info, i, is_first)
            amounts.append((qr_info['name'], amount))
        except Exception as e:
            print(f"处理二维码 {qr_info['name']} 时发生错误: {str(e)}")
            amounts.append((qr_info['name'], 0.0))  # 如果出错，金额记为 0，继续处理其他二维码
    
    # 最后一个二维码处理完成后，执行一次收款码移除操作
    print("所有二维码处理完成，执行最后的收款码移除操作...")
    tap_screen(571, 1500)  # 点击"对账范围"
    time.sleep(2)
    tap_screen(1100, 396)  # 点击"收款码"
    time.sleep(2)
    tap_screen(1329, 885)  # 点击"移除"
    time.sleep(2)
    print("收款码移除操作完成")

    # 在移除收款码后，执行一次返回操作，确保回到主页面
    press_back()  
    
    # 所有识别完成后，汇总结果并发送钉钉通知
    total = sum(amount for _, amount in amounts)
    result_message = f"扫码结果 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}):\n"
    for name, amt in amounts:
        result_message += f"{name}: {amt} 元\n"
    result_message += f"总计: {total} 元"
    print(result_message)
    
    # 统一发送钉钉通知，即使失败也不会影响流程
    send_dingtalk_message(result_message)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        error_msg = f"自动化脚本失败: {str(e)}"
        print(error_msg)
        # 即使主流程出错，也尝试发送错误通知，但不影响程序退出
        send_dingtalk_message(error_msg) 