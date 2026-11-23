import os
import sys
import json
import time
import re
import html
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone

# 单次请求超时（秒）。不设超时的话，CI 遇到网络卡死会一直挂到 job 上限。
TIMEOUT = 25

# 网络抖动重试：只对连接类异常重试，避免把「登录失败」这种业务错误重复提交。
RETRIES = 2
RETRY_BACKOFF = 1  # 秒，线性退避

# 幂等方法（重复发送无副作用），读超时也可以放心重试
IDEMPOTENT_METHODS = {'GET', 'HEAD', 'OPTIONS'}

# 支持的最大账号数，用于探测 USER1..USERn
MAX_ACCOUNTS = 20

# 订阅站域名：面板页面只暴露 /link/<token>，不暴露完整订阅地址，
# 所以域名只能写一个默认值。站点换订阅域名时，用环境变量 SUB_HOST 覆盖即可，不用改代码。
DEFAULT_SUB_HOST = "https://checkhere.top"


def get_sub_host():
    return (os.getenv('SUB_HOST') or DEFAULT_SUB_HOST).rstrip('/')


USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
)


def make_session():
    """统一使用 Session，自动管理 Cookie 和连接复用。"""
    session = requests.Session()
    session.headers.update({'User-Agent': USER_AGENT})
    return session


def request_with_retry(session, method, url, **kwargs):
    """带有限重试的请求封装。

    只对网络类异常重试，不重试 HTTP 业务错误：
    登录失败、签到失败是服务端明确返回的，重试没有意义还可能触发风控。

    GET 等幂等请求：连接失败、读超时都重试。
    POST 等非幂等请求：只重试 ConnectionError（含 ConnectTimeout，它是 ConnectionError 的子类）。
    读超时（ReadTimeout）说明请求可能已经到达服务端，再发一次会重复签到、
    或让 Telegram 收到两条一样的消息，所以直接抛出不重试。
    残余风险：requests 也会把「请求已发出、服务端中途断开」（RemoteDisconnected）
    归为 ConnectionError，这种情况仍会重试，极少数情况下可能重复提交一次。
    """
    kwargs.setdefault('timeout', TIMEOUT)
    if method.upper() in IDEMPOTENT_METHODS:
        retry_on = (requests.ConnectionError, requests.Timeout)
    else:
        retry_on = (requests.ConnectionError,)

    last_exc = None
    for attempt in range(RETRIES + 1):
        try:
            return session.request(method, url, **kwargs)
        except retry_on as e:
            last_exc = e
            if attempt < RETRIES:
                print(f"  网络异常，{RETRY_BACKOFF}s 后重试（{attempt + 1}/{RETRIES}）: {e}")
                time.sleep(RETRY_BACKOFF)
    raise last_exc


def mask(value, head=1, tail=1):
    """脱敏，只保留首尾少量字符。"""
    if not value:
        return ""
    if len(value) <= head + tail:
        return "*" * len(value)
    return f"{value[:head]}****{value[-tail:]}"


# 获取 html 中的用户信息
def fetch_and_extract_info(session, domain):
    """抓取 /user 页面，解析到期时间、剩余流量与订阅链接。

    失败时返回空字符串而不是 None —— 调用方要做字符串拼接，
    返回 None 会直接 TypeError，把已经成功的签到结果一并丢掉。
    """
    try:
        response = request_with_retry(session, 'GET', f"{domain}/user")
    except requests.RequestException as e:
        print(f"用户信息获取失败（网络异常）: {e}")
        return ""

    if response.status_code != 200:
        print(f"用户信息获取失败，页面打开异常（HTTP {response.status_code}）.")
        return ""

    soup = BeautifulSoup(response.text, 'html.parser')
    script_tags = soup.find_all('script')

    # 提取 ChatraIntegration 的 script 内容
    chatra_script = None
    for script in script_tags:
        # script.string 在有多个子节点时是 None，需要回退到 get_text()
        content = script.string or script.get_text()
        if content and 'window.ChatraIntegration' in content:
            chatra_script = content
            break

    if not chatra_script:
        print("未识别到用户信息")
        return ""

    def pick(pattern):
        found = re.search(pattern, chatra_script)
        return found.group(1) if found else None

    # 提取到期时间和剩余流量
    # 面板改版导致匹配不到时显示「未知」，而不是把 None 原样发出去
    expire = pick(r"'Class_Expire': '(.*?)'") or "未知"
    traffic = pick(r"'Unused_Traffic': '(.*?)'") or "未知"

    用户信息 = f"到期时间: {expire}\n剩余流量: {traffic}\n"

    # 提取 Clash 订阅链接：页面里只取 token，域名用 SUB_HOST（见文件顶部说明）
    token = None
    # 优先在 oneclickImport 那段脚本里找
    for script in script_tags:
        text = str(script)
        if 'oneclickImport' in text:
            found = re.search(r"/link/([A-Za-z0-9_-]+)", text)
            if found:
                token = found.group(1)
                break

    # 兜底：脚本结构变了也能找到（要求带订阅参数，避免误抓其他链接）
    if not token:
        for script in script_tags:
            text = str(script)
            if '?sub=' in text or '?clash=' in text:
                found = re.search(r"/link/([A-Za-z0-9_-]+)", text)
                if found:
                    token = found.group(1)
                    break

    if token:
        sub_host = get_sub_host()
        用户信息 += (
            f"Clash 订阅链接: {sub_host}/link/{token}?clash=1\n"
            f"v2ray 订阅链接: {sub_host}/link/{token}?sub=3\n\n"
        )

    return 用户信息


def generate_config():
    # 获取环境变量
    domain = (os.getenv('DOMAIN') or 'https://69yun69.com').rstrip('/')
    bot_token = os.getenv('BOT_TOKEN') or ''
    chat_id = os.getenv('CHAT_ID') or ''

    # 获取用户和密码的环境变量
    accounts = []
    for index in range(1, MAX_ACCOUNTS + 1):
        user = os.getenv(f'USER{index}')
        password = os.getenv(f'PASS{index}')
        # 编号中间断一个不影响后续账号（原实现遇到空就 break，USER1 缺失会全跳过）
        if not user or not password:
            continue
        accounts.append({'user': user, 'pass': password})

    config = {
        'domain': domain,
        'BotToken': bot_token,
        'ChatID': chat_id,
        'accounts': accounts
    }

    # 不要直接 print(config)：那会把密码打进 Actions 日志
    print(
        f"配置加载: domain={domain}, 账号数={len(accounts)}, "
        f"Telegram={'已配置' if bot_token and chat_id else '未配置'}"
    )
    for i, account in enumerate(accounts, 1):
        print(f"  账号{i}: {mask(account['user'], 2, 4)}")

    return config


def truncate_html(text, limit):
    """截断到 limit 字符，并去掉末尾被切断的 HTML 转义（如 `&am`），否则 Telegram 会回 400。"""
    if len(text) <= limit:
        return text
    return re.sub(r"&[#A-Za-z0-9]*$", "", text[:limit])


# 发送消息到 Telegram Bot，支持按钮
def send_message(msg="", BotToken="", ChatID=""):
    """返回值：True 已送达；False 配置了 Telegram 但发送失败；None 未配置 Telegram。

    调用方据此判断「失败有没有人知道」：发送失败时要让 CI 变红，否则静默丢消息。
    """
    # 获取当前 UTC 时间，并转换为北京时间（+8 小时）
    beijing_time = datetime.now(timezone.utc) + timedelta(hours=8)
    formatted_time = beijing_time.strftime("%Y-%m-%d %H:%M:%S")

    # 如果 Telegram Bot Token 和 Chat ID 都配置了，则发送消息
    if not BotToken or not ChatID:
        return None

    message_text = f"执行时间: {formatted_time}\n{msg}"

    # 构造按钮的键盘布局
    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "一休交流群",
                    "url": "https://t.me/yxjsjl"
                }
            ]
        ]
    }

    url = f"https://api.telegram.org/bot{BotToken}/sendMessage"
    payload = {
        "chat_id": ChatID,
        # Telegram 单条上限 4096 字符，兜底截断防止 400
        "text": truncate_html(message_text, 4096),
        "parse_mode": "HTML",
        "reply_markup": json.dumps(keyboard)
    }

    try:
        session = make_session()
        response = request_with_retry(session, 'POST', url, data=payload)
        # 原来不检查返回值，token 失效或 HTML 解析失败时会静默丢消息
        if response.status_code != 200:
            print(f"Telegram 发送失败 HTTP {response.status_code}: {response.text[:200]}")
            return False
        return True
    except requests.RequestException as e:
        print(f"发送电报消息时发生错误: {e}")
        return False


# 登录并签到的主要函数
def checkin(account, domain, BotToken, ChatID):
    """返回 (ok, 结果文本)。

    ok=False 的情况：登录/签到过程抛错，或 Telegram 已配置但消息没发出去。
    服务端回「今天已签到过」属于正常结果，不算失败（手动重跑时不会误报）。
    """
    user = account['user']
    pass_ = account['pass']

    try:
        # 检查必要的配置参数是否存在
        if not domain or not user or not pass_:
            raise ValueError('必需的配置参数缺失')

        session = make_session()

        # 登录请求
        login_url = f"{domain}/auth/login"
        login_data = {
            'email': user,
            'passwd': pass_,
            'remember_me': 'on',
            'code': "",
        }
        login_headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/plain, */*',
            'Origin': domain,
            'Referer': f"{domain}/auth/login",
        }

        login_response = request_with_retry(
            session, 'POST', login_url, json=login_data, headers=login_headers
        )
        print(f'{mask(user, 2, 4)}账号登录状态:', login_response.status_code)

        if login_response.status_code != 200:
            raise ValueError(f"登录请求失败: {login_response.text[:200]}")

        try:
            login_json = login_response.json()
        except ValueError:
            # 站点维护或被风控时可能返回登录页 HTML，直接 json() 会抛出难懂的异常
            raise ValueError(f"登录响应不是 JSON（可能被风控/站点维护）: {login_response.text[:200]}")
        if login_json.get("ret") != 1:
            raise ValueError(f"登录失败: {login_json.get('msg', '未知错误')}")

        # Cookie 由 Session 自动管理，不再手动拼接 Cookie header
        if not session.cookies:
            raise ValueError('登录成功但未收到Cookie')

        # 等待确保登录状态生效
        time.sleep(1)

        # 签到请求
        checkin_url = f"{domain}/user/checkin"
        checkin_headers = {
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'Origin': domain,
            'Referer': f"{domain}/user/panel",
            'X-Requested-With': 'XMLHttpRequest'
        }

        checkin_response = request_with_retry(
            session, 'POST', checkin_url, headers=checkin_headers
        )
        print(f'{mask(user, 2, 4)}账号签到状态:', checkin_response.status_code)

        response_text = checkin_response.text

        # 解析签到的 JSON 响应
        try:
            checkin_result = checkin_response.json()
        except ValueError:
            # 登录失效时服务端通常返回登录页 HTML
            if "登录" in response_text:
                raise ValueError('登录状态无效，请检查Cookie处理')
            raise ValueError(f"解析签到响应失败\n\n原始响应: {response_text[:300]}")

        # 先把 ret 取出来：dict.get 的默认参数是立即求值的，
        # 原来写成 get('msg', ... if checkin_result['ret'] ...) 在缺 ret 键时会 KeyError
        ret = checkin_result.get('ret')
        msg = checkin_result.get('msg') or ('签到成功' if str(ret) == '1' else '签到结果未知')

        # 只有 HTTP 200 且 ret 为 1（成功）或 0（今天已签到）才算正常；
        # ret=-1、缺 ret、HTTP 500 带 JSON 正文这些都是失败，要让 CI 变红。
        # 注意：部分面板的 ret=0 也可能表示其他失败，这里无法区分，按「已签到」处理。
        签到正常 = checkin_response.status_code == 200 and str(ret) in ('0', '1')

        # parse_mode=HTML 下，所有进入消息的动态内容都必须转义：
        # 服务端文案、账号、域名、订阅信息里的 < > & 都会让 Telegram 报 400。
        # 消息里不放密码：哪怕脱敏也会泄露首尾字符，而定位账号有邮箱就够了
        账号信息 = (
            f"地址: {html.escape(str(domain))}\n"
            f"账号: {html.escape(str(user))}\n"
        )

        # 用户信息抓取失败时返回空串，不影响签到结果回传
        用户信息 = fetch_and_extract_info(session, domain)
        用户信息 = html.escape(用户信息)

        if 签到正常:
            签到结果 = f"🎉 签到结果 🎉\n {html.escape(str(msg))}"
        else:
            签到结果 = (
                f"⚠️ 签到失败 ⚠️\n HTTP {checkin_response.status_code}，"
                f"ret={html.escape(str(ret))}：{html.escape(str(msg))}"
            )

        sent = send_message(账号信息 + 用户信息 + 签到结果, BotToken, ChatID)
        return 签到正常 and sent is not False, 签到结果

    except Exception as error:
        # 捕获异常，打印错误并发送错误信息到 Telegram
        # 日志侧账号脱敏；Telegram 侧带上完整账号地址，方便多账号时定位
        print(f'{mask(user, 2, 4)}账号签到异常:', error)
        签到结果 = f"签到过程发生错误: {html.escape(str(error))}"
        send_message(
            f"地址: {html.escape(str(domain))}\n"
            f"账号: {html.escape(str(user))}\n" + 签到结果,
            BotToken, ChatID,
        )
        # 返回值会被 main 打印到日志，所以这里不带账号
        return False, 签到结果


# 主程序执行逻辑，返回进程退出码（0 全部成功，1 有失败）
def main():
    config = generate_config()

    domain = config['domain']
    BotToken = config['BotToken']
    ChatID = config['ChatID']
    accounts = config.get("accounts", [])

    # 原来这里账号为空时会直接走完 for 循环、exit 0，
    # CI 显示绿色成功，实际一个账号都没签到。
    if not accounts:
        print("错误: 未读取到任何账号，请检查 USER1 / PASS1 等 Secrets 配置")
        send_message("签到未执行：未配置任何账号（USER1 / PASS1）", BotToken, ChatID)
        return 1

    # 原来单个账号签到失败、Telegram 又没发出去时，CI 仍显示绿色，等于没人知道。
    # 现在有任何账号失败就以非 0 退出码结束，GitHub 会发失败邮件提醒。
    failed = []
    for account in accounts:
        print("----------------------------------签到信息----------------------------------")
        ok, result = checkin(account, domain, BotToken, ChatID)
        print(result)
        if not ok:
            failed.append(account['user'])
        print("---------------------------------------------------------------------------")

    if failed:
        print(f"错误: {len(failed)}/{len(accounts)} 个账号失败: "
              + ", ".join(mask(u, 2, 4) for u in failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
