"""69yun.py 关键路径单元测试。

不依赖真实网络：所有请求用 unittest.mock 模拟。
运行： python -m unittest -v test_69yun
"""
import os
import sys
import time
import unittest
from unittest.mock import Mock, patch

import requests

import importlib.util

# 避免脚本名带数字导致 import 问题，用 importlib 按路径加载
_HERE = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location("checkin_module", os.path.join(_HERE, "69yun.py"))
m = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(m)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class TestMask(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(m.mask("abcdefgh", 1, 1), "a****h")

    def test_short(self):
        self.assertEqual(m.mask("ab", 1, 1), "**")

    def test_empty(self):
        self.assertEqual(m.mask(""), "")


class TestRetry(unittest.TestCase):
    def test_returns_first_success(self):
        session = Mock()
        session.request = Mock(return_value=FakeResponse(200))
        resp = m.request_with_retry(session, 'GET', 'http://x')
        self.assertEqual(resp.status_code, 200)
        session.request.assert_called_once()

    def test_retries_on_connection_error_then_success(self):
        session = Mock()
        session.request = Mock(side_effect=[
            requests.ConnectionError("boom"),
            FakeResponse(200),
        ])
        with patch.object(m.time, 'sleep'):  # 不等真正的退避
            resp = m.request_with_retry(session, 'GET', 'http://x')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(session.request.call_count, 2)

    def test_raises_after_all_retries(self):
        session = Mock()
        session.request = Mock(side_effect=requests.Timeout("t"))
        with patch.object(m.time, 'sleep'):
            with self.assertRaises(requests.Timeout):
                m.request_with_retry(session, 'GET', 'http://x')
        self.assertEqual(session.request.call_count, m.RETRIES + 1)

    def test_does_not_retry_http_error(self):
        # HTTP 4xx/5xx 是正常返回的 Response，不应触发重试
        session = Mock()
        session.request = Mock(return_value=FakeResponse(500, text="err"))
        resp = m.request_with_retry(session, 'GET', 'http://x')
        self.assertEqual(resp.status_code, 500)
        session.request.assert_called_once()


class TestGenerateConfig(unittest.TestCase):
    def test_empty_accounts_returns_empty_list(self):
        env = {"DOMAIN": "https://69yun69.com", "BOT_TOKEN": "", "CHAT_ID": ""}
        with patch.dict(os.environ, env, clear=True):
            cfg = m.generate_config()
        self.assertEqual(cfg["accounts"], [])
        self.assertEqual(cfg["domain"], "https://69yun69.com")

    def test_reads_accounts_and_skips_gaps(self):
        env = {
            "DOMAIN": "https://x/",
            "USER1": "u1@x.com", "PASS1": "p1",
            # USER2 缺失，USER3 应仍被读取
            "USER3": "u3@x.com", "PASS3": "p3",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = m.generate_config()
        self.assertEqual(cfg["domain"], "https://x")  # rstrip('/')
        self.assertEqual([a["user"] for a in cfg["accounts"]], ["u1@x.com", "u3@x.com"])


class TestCheckinPaths(unittest.TestCase):
    def _run_checkin(self, login_resp, checkin_resp, user_resp=None):
        """驱动一次 checkin，返回 (result, sent_messages)。"""
        sent = []
        session = Mock()
        session.cookies = {"session": "abc"}
        # 按调用顺序：登录 POST -> 签到 POST -> /user GET
        responses = [login_resp, checkin_resp]
        if user_resp is not None:
            responses.append(user_resp)
        session.request = Mock(side_effect=responses)

        def fake_send(msg, token="", chat=""):
            sent.append(msg)

        with patch.object(m, 'make_session', return_value=session), \
             patch.object(m, 'send_message', side_effect=fake_send), \
             patch.object(m.time, 'sleep'):
            result = m.checkin({"user": "u@x.com", "pass": "secret1"}, "https://69yun69.com", "", "")
        return result, sent, session

    def test_success_path(self):
        login = FakeResponse(200, {"ret": 1, "msg": "ok"})
        checkin = FakeResponse(200, {"ret": 1, "msg": "签到成功"})
        user = FakeResponse(200, text="<html></html>")
        result, sent, session = self._run_checkin(login, checkin, user)
        self.assertIn("签到成功", result)
        self.assertEqual(len(sent), 1)
        self.assertIn("u@x.com", sent[0])
        self.assertNotIn("secret1", sent[0])  # 密码不明文出现

    def test_login_bad_json_reports_friendly_error(self):
        login = FakeResponse(200, text="<html>维护中</html>")
        result, sent, session = self._run_checkin(login, FakeResponse(200, {"ret": 1}))
        self.assertIn("不是 JSON", result)
        self.assertEqual(session.request.call_count, 1)  # 不再继续签到

    def test_login_failure_stops(self):
        login = FakeResponse(200, {"ret": 0, "msg": "密码错误"})
        result, sent, session = self._run_checkin(login, FakeResponse(200, {"ret": 1}))
        self.assertIn("密码错误", result)
        self.assertEqual(session.request.call_count, 1)

    def test_html_escape_in_message(self):
        # 服务端文案含 < > &，必须转义后再进 HTML 消息
        login = FakeResponse(200, {"ret": 1, "msg": "ok"})
        checkin = FakeResponse(200, {"ret": 1, "msg": "流量 <10GB & 到期"})
        user = FakeResponse(200, text="<html></html>")
        result, sent, session = self._run_checkin(login, checkin, user)
        self.assertIn("&lt;10GB &amp;", sent[0])
        self.assertNotIn("<10GB", sent[0])

    def test_checkin_html_page_reports_login_invalid(self):
        login = FakeResponse(200, {"ret": 1, "msg": "ok"})
        checkin = FakeResponse(200, text="<html>请登录</html>")
        result, sent, session = self._run_checkin(login, checkin)
        self.assertIn("登录状态无效", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
