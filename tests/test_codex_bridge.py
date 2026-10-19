"""Exercise the real stdio bridge with a deterministic app-server peer, no model usage."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from codex_bridge import ChatBridge, CodexError, RpcClient, instructions, validate_images


FAKE_SERVER = r'''
import json, sys, threading, os
from pathlib import Path
assert "OPENAI_API_KEY" not in os.environ
assert "CODEX_ACCESS_TOKEN" not in os.environ
settings = dict(value.split("=", 1) for value in sys.argv[1:] if "=" in value)
assert settings['forced_login_method'] == '"chatgpt"'
assert settings['features.memories'] == 'false'
assert settings['features.shell_tool'] == 'false'
assert settings['default_permissions'] == '"cad-chat"'
assert settings['permissions.cad-chat.network.enabled'] == 'false'
lock = threading.Lock()
threads, active = {}, {}
def emit(value):
    with lock:
        print(json.dumps(value), flush=True)
def notice(method, params):
    emit({"method": method, "params": params})
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m or "method" not in m: continue
    method, p = m["method"], m.get("params", {})
    result = {}
    if method == "account/read":
        result = {"account": {"type": "chatgpt"}}
    elif method == "account/login/start":
        notice("account/updated", {"authMode": "chatgpt"})
        result = {"authUrl": "https://auth.openai.com/oauth/authorize", "loginId": "login"}
    elif method == "thread/start":
        assert p["ephemeral"] and "sandbox" not in p
        assert p["approvalPolicy"] == "never"
        tid = "thread-" + str(len(threads))
        threads[tid] = 0
        result = {"thread": {"id": tid}}
    elif method == "turn/start":
        tid = p["threadId"]
        threads[tid] += 1
        turn = tid + "-turn-" + str(threads[tid])
        active[tid] = turn
        payload = json.loads(p["input"][0]["text"])
        assert p["outputSchema"]["required"] == ["message", "source"]
        assert "sandboxPolicy" not in p and "permissionProfile" not in p
        result = {"turn": {"id": turn}}
        emit({"id": m["id"], "result": result})
        if payload["message"] == "wait": continue
        notice("item/agentMessage/delta", {"threadId": tid, "turnId": turn, "delta": "..."})
        output = {"message": tid + ":" + str(threads[tid]),
                  "source": None if payload["message"] == "question" else payload["source"] + "\n# edited"}
        if payload["message"] == "restored": output["message"] = payload["restoredHistory"][0]["text"]
        if payload["message"] == "images":
            paths=[item['path'] for item in p['input'] if item['type']=='localImage']
            assert all(Path(path).read_bytes().startswith(b'\x89PNG\r\n\x1a\n') for path in paths)
            assert 'data:image' not in p['input'][0]['text']
            output['message']='images:'+str(len(paths))
        text = "not JSON" if payload["message"] == "malformed" else json.dumps(output)
        notice("item/completed", {"threadId": tid, "turnId": turn,
              "item": {"type": "agentMessage", "phase": "final_answer", "text": text}})
        status = "failed" if payload["message"] == "fail" else "completed"
        notice("turn/completed", {"threadId": tid, "turn": {"id": turn, "status": status,
               "error": {"message": "usage limit"} if status == "failed" else None}})
        continue
    elif method == "turn/interrupt":
        notice("turn/completed", {"threadId": p["threadId"], "turn": {"id": p["turnId"], "status": "interrupted"}})
    elif method == "test/no-reply": continue
    elif method == "test/server-request":
        emit({"id": "tool-request", "method": "item/commandExecution/requestApproval", "params": {}})
    elif method == "test/error":
        emit({"id": m["id"], "error": {"message": "deliberate failure"}})
        continue
    emit({"id": m["id"], "result": result})
'''


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        executable = Path(self.directory.name) / "codex"
        import sys
        executable.write_text(f"#!{sys.executable}\n" + FAKE_SERVER)
        executable.chmod(0o700)
        self.env = patch.dict(os.environ, {"CAD_CODEX_BIN": str(executable), "CAD_CODEX_HOME": str(Path(self.directory.name) / "home")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.bridge = ChatBridge()
        self.addCleanup(self.bridge.close)

    def send(self, message="edit", source="box body 0 0 0 1 1 1", session=None):
        return self.bridge.send({"message": message, "mode": "text", "source": source, "sessionId": session})["sessionId"]

    def finish(self, session):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = self.bridge.poll(session)
            if state["state"] != "running":
                return state
            time.sleep(0.01)
        self.fail("bridge did not finish")

    def test_edit_question_and_current_source_in_one_conversation(self):
        session = self.send()
        result = self.finish(session)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["result"]["source"], "box body 0 0 0 1 1 1\n# edited")
        self.send(source="manually edited source", session=session)
        result = self.finish(session)["result"]
        self.assertEqual(result["source"], "manually edited source\n# edited")
        self.assertEqual(result["message"], "thread-0:2")
        self.send(message="question", session=session)
        self.assertIsNone(self.finish(session)["result"]["source"])

    def test_browser_conversations_are_separate(self):
        first, second = self.send(), self.send()
        a, b = self.finish(first), self.finish(second)
        self.assertNotEqual(a["result"]["message"], b["result"]["message"])

    def test_cancel_in_flight_and_reuse_thread(self):
        session = self.send(message="wait")
        deadline = time.monotonic() + 3
        while not self.bridge.sessions[session]["turn"] and time.monotonic() < deadline:
            time.sleep(0.01)
        with self.assertRaises(CodexError):
            self.send(session=session)
        with self.assertRaises(CodexError):
            self.bridge.reset(session)
        self.bridge.cancel(session)
        self.assertEqual(self.finish(session)["state"], "cancelled")
        self.send(session=session)
        self.assertEqual(self.finish(session)["state"], "completed")
        self.bridge.reset(session)
        with self.assertRaises(ValueError):
            self.bridge.poll(session)

    def test_failed_and_malformed_results_leave_no_edit(self):
        for message in ("fail", "malformed"):
            result = self.finish(self.send(message=message))
            self.assertEqual(result["state"], "failed")
            self.assertIsNone(result["result"])
            if message == "fail": self.assertEqual(result["error"], "usage limit")

    def test_login_notification_does_not_block_rpc_reader(self):
        self.assertTrue(self.bridge.status()["ready"])
        self.assertIn("url", self.bridge.login_start())

    def test_bad_requests_and_unknown_sessions(self):
        for request in ({}, {"source": "x", "mode": "python", "message": ""},
                        {"source": "x", "mode": "other", "message": "x"},
                        {"source": "x", "mode": "text", "message": "x", "sessionId": []}):
            with self.assertRaises(ValueError): self.bridge.send(request)
        with self.assertRaises(CodexError): self.send(session="unknown")

    def test_restore_transcript_on_first_turn(self):
        request = {'message':'restored','mode':'text','source':'box body 0 0 0 2 1 1',
                   'restoredHistory':[{'role':'user','text':'幅を2にして'},{'role':'assistant','text':'変更しました'}]}
        session = self.bridge.send(request)['sessionId']
        result = self.finish(session)
        self.assertEqual(result['state'],'completed')
        self.assertEqual(result['result']['message'],'幅を2にして')
        with self.assertRaises(ValueError): self.bridge.send({**request,'sessionId':session})
        for history in ({},[{'role':'developer','text':'x'}],[{'role':'user','text':'x'*200001}]):
            with self.assertRaises(ValueError): self.bridge.send({**request,'restoredHistory':history})

    def test_current_and_restored_images_use_temporary_local_inputs(self):
        image={'name':'reference.png','dataUrl':'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aDm8AAAAASUVORK5CYII='}
        request={'message':'images','mode':'text','source':'box body 0 0 0 1 1 1','images':[image],
                 'restoredHistory':[{'role':'user','text':'前の画像','images':[image]}]}
        session=self.bridge.send(request)['sessionId']
        result=self.finish(session)
        self.assertEqual(result['state'],'completed')
        self.assertEqual(result['result']['message'],'images:2')
        deadline=time.monotonic()+1
        workspace=Path(self.bridge.client.workspace.name)
        while list(workspace.glob('images-*')) and time.monotonic()<deadline: time.sleep(.01)
        self.assertFalse(list(workspace.glob('images-*')))
        for images in ([{**image,'dataUrl':'https://example.com/private.png'}], [image]*4,
                       [{**image,'dataUrl':'data:image/png;base64,SGVsbG8='}],
                       [{**image,'dataUrl':'data:image/png;base64,%%%%'}]):
            with self.assertRaises(ValueError): validate_images(images)

    def test_expired_idle_sessions_are_removed(self):
        session = self.send()
        self.finish(session)
        self.bridge.sessions[session]["touched"] = time.monotonic() - 3700
        fresh = self.send()
        self.assertEqual(self.finish(fresh)["state"], "completed")
        self.assertNotIn(session, self.bridge.sessions)

    def test_disconnect_reports_failure_and_allows_new_connection(self):
        session = self.send(message="wait")
        deadline = time.monotonic() + 3
        while not self.bridge.sessions[session]["turn"] and time.monotonic() < deadline:
            time.sleep(0.01)
        self.bridge.client.close()
        self.assertEqual(self.finish(session)["state"], "failed")
        self.assertTrue(self.bridge.status()["ready"])
        fresh = self.send()
        self.assertEqual(self.finish(fresh)["state"], "completed")

    def test_api_key_only_account_is_not_accepted(self):
        self.bridge.connect()
        with patch.object(self.bridge.client, "call", return_value={"account": {"type": "apiKey"}}):
            self.assertFalse(self.bridge.status()["ready"])
            with self.assertRaises(CodexError): self.send()

    def test_rpc_timeout_error_and_server_tool_request(self):
        client = self.bridge.connect()
        with self.assertRaisesRegex(CodexError, "時間内"):
            client.call("test/no-reply", timeout=0.02)
        with self.assertRaisesRegex(CodexError, "deliberate failure"):
            client.call("test/error")
        self.assertEqual(client.call("test/server-request"), {})
        self.assertEqual(client.call("account/read")["account"]["type"], "chatgpt")

    def test_instructions_include_both_languages(self):
        text = instructions()
        self.assertIn("create_box", text)
        self.assertIn("group", text)
        self.assertIn("source is null", text)


if __name__ == "__main__":
    unittest.main()
