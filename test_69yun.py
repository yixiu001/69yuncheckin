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

    def test_post_does_not_retry_read_timeout(self):
        # POST 读超时：请求可能已到达服务端，重试会重复签到/重复发消息
        session = Mock()
        session.request = Mock(side_effect=requests.ReadTimeout("rt"))
        with patch.object(m.time, 'sleep'):
            with self.assertRaises(requests.ReadTimeout):
                m.request_with_retry(session, 'POST', 'http://x')
        session.request.assert_called_once()

    def test_post_retries_connect_timeout(self):
        # 连接都没建立，请求肯定没发出去，可以安全重试
        session = Mock()
        session.request = Mock(side_effect=[
            requests.ConnectTimeout("ct"),
            FakeResponse(200),
        ])
        with patch.object(m.time, 'sleep'):
            resp = m.request_with_retry(session, 'POST', 'http://x')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(session.request.call_count, 2)

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
    def _run_checkin(self, login_resp, checkin_resp, user_resp=None, send_result=None):
        """驱动一次 checkin，返回 (ok, result, sent_messages, session)。

        send_result 模拟 send_message 的返回值：None 未配置 / True 送达 / False 发送失败。
        """
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
            return send_result

        with patch.object(m, 'make_session', return_value=session), \
             patch.object(m, 'send_message', side_effect=fake_send), \
             patch.object(m.time, 'sleep'):
            ok, result = m.checkin({"user": "u@x.com", "pass": "secret1"}, "https://69yun69.com", "", "")
        return ok, result, sent, session

    def test_success_path(self):
        login = FakeResponse(200, {"ret": 1, "msg": "ok"})
        checkin = FakeResponse(200, {"ret": 1, "msg": "签到成功"})
        user = FakeResponse(200, text="<html></html>")
        ok, result, sent, session = self._run_checkin(login, checkin, user)
        self.assertTrue(ok)
        self.assertIn("签到成功", result)
        self.assertEqual(len(sent), 1)
        self.assertIn("u@x.com", sent[0])
        self.assertNotIn("secret1", sent[0])  # 密码不明文出现
        self.assertNotIn("密码", sent[0])     # 脱敏后的密码也不再出现
        self.assertNotIn("s****1", sent[0])

    def test_already_checked_in_is_not_failure(self):
        # 手动重跑时服务端回「已签到」，不应让 CI 变红
        login = FakeResponse(200, {"ret": 1, "msg": "ok"})
        checkin = FakeResponse(200, {"ret": 0, "msg": "您似乎已经签到过了"})
        user = FakeResponse(200, text="<html></html>")
        ok, result, sent, session = self._run_checkin(login, checkin, user)
        self.assertTrue(ok)
        self.assertIn("已经签到过", result)

    def test_server_reported_failure_marks_failed(self):
        # ret=-1、缺 ret、HTTP 500 带 JSON：都是失败，不能当成功
        cases = [
            FakeResponse(200, {"ret": -1, "msg": "验证码错误"}),
            FakeResponse(200, {"msg": "奇怪的返回"}),
            FakeResponse(500, {"ret": 1, "msg": "服务器错误"}),
        ]
        for checkin in cases:
            with self.subTest(checkin=checkin._json):
                login = FakeResponse(200, {"ret": 1, "msg": "ok"})
                user = FakeResponse(200, text="<html></html>")
                ok, result, sent, session = self._run_checkin(login, checkin, user)
                self.assertFalse(ok)
                self.assertIn("签到失败", result)
                self.assertEqual(len(sent), 1)  # 失败也要通知

    def test_error_result_for_log_has_no_plain_account(self):
        # 返回值会打印到日志，不能带明文账号；Telegram 消息里要带账号方便定位
        login = FakeResponse(200, {"ret": 0, "msg": "密码错误"})
        ok, result, sent, session = self._run_checkin(login, FakeResponse(200, {"ret": 1}))
        self.assertNotIn("u@x.com", result)
        self.assertIn("u@x.com", sent[0])

    def test_error_branch_with_telegram_failure_still_failed(self):
        login = FakeResponse(200, text="<html>维护中</html>")
        ok, result, sent, session = self._run_checkin(login, FakeResponse(200, {"ret": 1}), send_result=False)
        self.assertFalse(ok)

    def test_telegram_send_failure_marks_failed(self):
        # 签到成功但通知没发出去：没人知道结果，要让 CI 变红
        login = FakeResponse(200, {"ret": 1, "msg": "ok"})
        checkin = FakeResponse(200, {"ret": 1, "msg": "签到成功"})
        user = FakeResponse(200, text="<html></html>")
        ok, result, sent, session = self._run_checkin(login, checkin, user, send_result=False)
        self.assertFalse(ok)

    def test_login_bad_json_reports_friendly_error(self):
        login = FakeResponse(200, text="<html>维护中</html>")
        ok, result, sent, session = self._run_checkin(login, FakeResponse(200, {"ret": 1}))
        self.assertFalse(ok)
        self.assertIn("不是 JSON", result)
        self.assertEqual(session.request.call_count, 1)  # 不再继续签到

    def test_login_failure_stops(self):
        login = FakeResponse(200, {"ret": 0, "msg": "密码错误"})
        ok, result, sent, session = self._run_checkin(login, FakeResponse(200, {"ret": 1}))
        self.assertFalse(ok)
        self.assertIn("密码错误", result)
        self.assertEqual(session.request.call_count, 1)

    def test_html_escape_in_message(self):
        # 服务端文案含 < > &，必须转义后再进 HTML 消息
        login = FakeResponse(200, {"ret": 1, "msg": "ok"})
        checkin = FakeResponse(200, {"ret": 1, "msg": "流量 <10GB & 到期"})
        user = FakeResponse(200, text="<html></html>")
        ok, result, sent, session = self._run_checkin(login, checkin, user)
        self.assertIn("&lt;10GB &amp;", sent[0])
        self.assertNotIn("<10GB", sent[0])

    def test_checkin_html_page_reports_login_invalid(self):
        login = FakeResponse(200, {"ret": 1, "msg": "ok"})
        checkin = FakeResponse(200, text="<html>请登录</html>")
        ok, result, sent, session = self._run_checkin(login, checkin)
        self.assertFalse(ok)
        self.assertIn("登录状态无效", result)


class TestFetchUserInfo(unittest.TestCase):
    PAGE = (
        "<html><script>window.ChatraIntegration = {%s};</script>"
        "<script>function oneclickImport(){ var u = '/link/AbC_12-x?clash=1'; }</script></html>"
    )

    def _fetch(self, page, env=None):
        session = Mock()
        session.request = Mock(return_value=FakeResponse(200, text=page))
        with patch.dict(os.environ, env or {}, clear=True):
            return m.fetch_and_extract_info(session, "https://69yun69.com")

    def test_parses_fields_and_default_sub_host(self):
        info = self._fetch(self.PAGE % "'Class_Expire': '2027-01-01', 'Unused_Traffic': '50GB'")
        self.assertIn("到期时间: 2027-01-01", info)
        self.assertIn("剩余流量: 50GB", info)
        self.assertIn("https://checkhere.top/link/AbC_12-x?clash=1", info)

    def test_missing_fields_show_unknown_not_none(self):
        info = self._fetch(self.PAGE % "")
        self.assertIn("到期时间: 未知", info)
        self.assertIn("剩余流量: 未知", info)
        self.assertNotIn("None", info)

    def test_sub_host_env_override(self):
        info = self._fetch(self.PAGE % "", env={"SUB_HOST": "https://new.example/"})
        self.assertIn("https://new.example/link/AbC_12-x?sub=3", info)
        self.assertNotIn("checkhere.top", info)


class TestTruncateHtml(unittest.TestCase):
    def test_short_text_unchanged(self):
        self.assertEqual(m.truncate_html("a &amp; b", 100), "a &amp; b")

    def test_cut_entity_removed(self):
        # 截在 &amp; 中间，残缺的 &am 要去掉
        self.assertEqual(m.truncate_html("abc&amp;def", 6), "abc")

    def test_complete_entity_kept(self):
        self.assertEqual(m.truncate_html("abc&amp;def", 8), "abc&amp;")


class TestSendMessage(unittest.TestCase):
    def _send(self, resp=None, exc=None):
        session = Mock()
        session.request = Mock(return_value=resp, side_effect=exc)
        with patch.object(m, 'make_session', return_value=session), \
             patch.object(m.time, 'sleep'):
            return m.send_message("hi", "token", "chat")

    def test_not_configured_returns_none(self):
        self.assertIsNone(m.send_message("hi", "", ""))

    def test_ok_returns_true(self):
        self.assertIs(self._send(FakeResponse(200)), True)

    def test_http_error_returns_false(self):
        self.assertIs(self._send(FakeResponse(400, text="bad")), False)

    def test_network_error_returns_false(self):
        self.assertIs(self._send(exc=requests.ConnectionError("x")), False)


class TestMainExitCode(unittest.TestCase):
    def _main(self, results, env=None):
        env = env if env is not None else {"USER1": "a@x.com", "PASS1": "p", "USER2": "b@x.com", "PASS2": "q"}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(m, 'checkin', side_effect=results) as fake_checkin, \
             patch.object(m, 'send_message', return_value=None):
            code = m.main()
        return code, fake_checkin

    def test_all_ok_exit_0(self):
        code, _ = self._main([(True, "ok"), (True, "ok")])
        self.assertEqual(code, 0)

    def test_one_failure_exit_1_but_others_still_run(self):
        code, fake_checkin = self._main([(False, "err"), (True, "ok")])
        self.assertEqual(code, 1)
        self.assertEqual(fake_checkin.call_count, 2)  # 第一个失败不影响第二个签到

    def test_no_accounts_exit_1(self):
        code, fake_checkin = self._main([], env={})
        self.assertEqual(code, 1)
        fake_checkin.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
