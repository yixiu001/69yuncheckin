import os
import json
import requests
import time
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta

# 配置文件路径
config_file_path = "config.json"
签到结果 = ""

# 获取html中的用户信息
def fetch_and_extract_info(domain,headers):
    url = f"{domain}/user"

    # 发起 GET 请求
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print("用户信息获取失败，页面打开异常.")
        return None

    # 解析网页内容
    soup = BeautifulSoup(response.text, 'html.parser')

    # 找到所有 script 标签
    script_tags = soup.find_all('script')

    # 提取 ChatraIntegration 的 script 内容
    chatra_script = None
    for script in script_tags:
        if 'window.ChatraIntegration' in str(script):
            chatra_script = script.string
            break

    if not chatra_script:
        print("未识别到用户信息")
        return None

    # 使用正则表达式提取需要的信息
    # 提取用户名、邮箱、到期时间和剩余流量
    user_info = {}
    # user_info['用户名'] = re.search(r"name: '(.*?)'", chatra_script).group(1) if re.search(r"name: '(.*?)'", chatra_script) else None
    # user_info['邮箱'] = re.search(r"email: '(.*?)'", chatra_script).group(1) if re.search(r"email: '(.*?)'", chatra_script) else None
    user_info['到期时间'] = re.search(r"'Class_Expire': '(.*?)'", chatra_script).group(1) if re.search(r"'Class_Expire': '(.*?)'", chatra_script) else None
    user_info['剩余流量'] = re.search(r"'Unused_Traffic': '(.*?)'", chatra_script).group(1) if re.search(r"'Unused_Traffic': '(.*?)'", chatra_script) else None

    # 输出用户信息
    用户信息 = f"到期时间: {user_info['到期时间']}\n剩余流量: {user_info['剩余流量']}\n"
    # print(f"到期时间: {user_info['到期时间']}")
    # print(f"剩余流量: {user_info['剩余流量']}")

    # 提取 Clash 订阅链接
    clash_link = None
    for script in script_tags:
        if 'index.oneclickImport' in str(script) and 'clash' in str(script):
            link = re.search(r"'https://checkhere.top/link/(.*?)\?sub=1'", str(script))
            if link:
                用户信息 += f"Clash 订阅链接: https://checkhere.top/link/{link.group(1)}?clash=1\nv2ray 订阅链接: https://checkhere.top/link/{link.group(1)}?sub=3\n\n"
                # print(f"Clash 订阅链接: https://checkhere.top/link/{link.group(1)}?clash=1")
                # print(f"v2ray 订阅链接: https://checkhere.top/link/{link.group(1)}?sub=3")
                break
    return 用户信息
# 读取配置文件
def read_config(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"配置文件 {file_path} 未找到，请检查配置文件是否存在。")
    except json.JSONDecodeError:
        raise ValueError("配置文件格式错误，请检查 config.json 文件是否有效。")

# 发送消息到 钉钉 机器人的函数，支持卡片消息
def send_message(msg="", webhook_url=""):
    # 获取当前 UTC 时间，并转换为北京时间（+8小时）
    now = datetime.utcnow()
    beijing_time = now + timedelta(hours=8)
    formatted_time = beijing_time.strftime("%Y-%m-%d %H:%M:%S")

    # 如果 webhook_url 已配置，则发送消息
    if webhook_url != '':
        # 构建消息内容
        message_text = f"执行时间: {formatted_time}\n{msg}"

        # 构造 payload
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": "签到结果",
                "text": message_text
            }
        }

        try:
            # 发送 POST 请求
            response = requests.post(webhook_url, json=payload)
            response.raise_for_status()  # 如果请求返回错误，将引发异常
            return response
        except Exception as e:
            print(f"发送钉钉消息时发生错误: {str(e)}")
            return None


# 登录并签到的主要函数
def checkin(account, domain, webhook_url):
    user = account['user']
    pass_ = account['pass']

    签到结果 = f"地址: {domain[:9]}****{domain[-5:]}\n账号: {user[:1]}****{user[-5:]}\n密码: {pass_[:1]}****{pass_[-1]}\n\n"

    try:
        # 检查必要的配置参数是否存在
        if not domain or not user or not pass_:
            raise ValueError('必需的配置参数缺失')

        # 登录请求的 URL
        login_url = f"{domain}/auth/login"

        # 登录请求的 Payload（请求体）
        login_data = {
            'email': user,
            'passwd': pass_,
            'remember_me': 'on',
            'code': "",
        }

        # 设置请求头
        login_headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Origin': domain,
            'Referer': f"{domain}/auth/login",
        }

        # 发送登录请求
        login_response = requests.post(login_url, json=login_data, headers=login_headers)

        print(f'{user}账号登录状态:', login_response.status_code)

        # 如果响应状态不是200，表示登录失败
        if login_response.status_code != 200:
            raise ValueError(f"登录请求失败: {login_response.text}")

        # 解析登录响应的 JSON 数据
        login_json = login_response.json()

        # 检查登录是否成功
        if login_json.get("ret") != 1:
            raise ValueError(f"登录失败: {login_json.get('msg', '未知错误')}")

        # 获取登录成功后的 Cookie
        cookies = login_response.cookies
        if not cookies:
            raise ValueError('登录成功但未收到Cookie')

        # 等待确保登录状态生效
        time.sleep(1)

        # 签到请求的 URL
        checkin_url = f"{domain}/user/checkin"

        # 签到请求的 Headers
        checkin_headers = {
            'Cookie': '; '.join([f"{key}={value}" for key, value in cookies.items()]),
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'Origin': domain,
            'Referer': f"{domain}/user/panel",
            'X-Requested-With': 'XMLHttpRequest'
        }

        # 发送签到请求
        checkin_response = requests.post(checkin_url, headers=checkin_headers)

        print(f'{user}账号签到状态:', checkin_response.status_code)

        # 获取签到请求的响应内容
        response_text = checkin_response.text

        try:
            # 尝试解析签到的 JSON 响应
            checkin_result = checkin_response.json()
            账号信息 = f"地址: {domain}\n账号: {user}\n密码: <tg-spoiler>{pass_}</tg-spoiler>\n"

            用户信息 = fetch_and_extract_info(domain, checkin_headers)

            # 根据返回的结果更新签到信息
            if checkin_result.get('ret') == 1 or checkin_result.get('ret') == 0:
                签到结果 = f"🎉 签到结果 🎉\n {checkin_result.get('msg', '签到成功' if checkin_result['ret'] == 1 else '签到失败')}"
            else:
                签到结果 = f"🎉 签到结果 🎉\n {checkin_result.get('msg', '签到结果未知')}"
        except Exception as e:
            # 如果出现解析错误，检查是否由于登录失效
            if "登录" in response_text:
                raise ValueError('登录状态无效，请检查Cookie处理')
            raise ValueError(f"解析签到响应失败: {str(e)}\n\n原始响应: {response_text}")

        # 发送签到结果到 钉钉
        send_message(账号信息 + 用户信息 + 签到结果, webhook_url)
        return 签到结果

    except Exception as error:
        # 捕获异常，打印错误并发送错误信息到 钉钉
        print(f'{user}账号签到异常:', error)
        签到结果 = f"签到过程发生错误: {error}"
        send_message(签到结果, webhook_url)
        return 签到结果

# 主程序执行逻辑
if __name__ == "__main__":
    # 读取配置
    config = read_config(config_file_path)

    # 读取全局配置
    domain = config['domain']
    webhook_url = config['DingTalkWebhook']  # 假设您在 config.json 中有这个字段

    # 循环执行每个账号的签到任务
    for account in config.get("accounts", []):
        print("----------------------------------签到信息----------------------------------")
        print(checkin(account, domain, webhook_url))
        print("---------------------------------------------------------------------------")
