"""OneBot 事件解析与三种连接方式 (本地模拟 NapCat, 不连接任何真实服务)."""
import asyncio, hashlib, hmac, json, socket, threading, time
import pytest
from homeworkbot.parser import parse_event, accept, cq_to_segments, SeenStore, is_teacher
from homeworkbot.config import DEFAULTS
from homeworkbot import onebot

def group_event(text="今日作业：语文抄写第5课", uid=10001, gid=123456, card="王老师", nick="Wang", mid=1, images=()):
    segs = [{"type": "text", "data": {"text": text}}] if text else []
    segs += [{"type": "image", "data": {"file": f"{i}.jpg", "url": u}} for i, u in enumerate(images)]
    return {"post_type": "message", "message_type": "group", "sub_type": "normal", "time": 1760500000,
            "self_id": 99999, "user_id": uid, "group_id": gid, "message_id": mid, "message": segs,
            "raw_message": text, "sender": {"user_id": uid, "nickname": nick, "card": card, "role": "member"}}

CFG = dict(DEFAULTS, qq_group_ids=[123456], teachers=["王老师"])

# ---------- 解析 ----------
def test_parse_array_message():
    m = parse_event(group_event(images=["https://multimedia.nt.qq.com.cn/download?a=1&amp;b=2"]))
    assert m.sender == "王老师" and m.user_id == "10001" and m.group == "123456" and m.message_id == "1"
    assert m.text.startswith("今日作业")
    assert m.attachments[0].url == "https://multimedia.nt.qq.com.cn/download?a=1&b=2"
    assert m.images == ["https://multimedia.nt.qq.com.cn/download?a=1&b=2"]

def test_parse_cq_string():
    ev = group_event(); ev["message"] = "数学作业[CQ:image,file=a.jpg,url=https://x.qq.com/a&#44;b]口算"
    m = parse_event(ev)
    assert "数学作业" in m.text and "口算" in m.text and m.attachments[0].url == "https://x.qq.com/a,b"
    assert cq_to_segments("[CQ:at,qq=1] hi")[0] == {"type": "at", "data": {"qq": "1"}}

def test_non_group_ignored():
    assert parse_event({"post_type": "message", "message_type": "private", "message": "作业"}) is None
    assert parse_event({"post_type": "meta_event", "meta_event_type": "heartbeat"}) is None
    assert not accept(None, CFG)

def test_filter_group_and_teacher():
    assert accept(parse_event(group_event()), CFG)
    assert not accept(parse_event(group_event(gid=999)), CFG)                       # 其他群
    assert not accept(parse_event(group_event(card="小明妈妈", nick="m")), CFG)      # 家长
    assert not accept(parse_event(group_event(text="今晚开家长会")), CFG)             # 无关键词
    assert accept(parse_event(group_event(text="", images=["https://x/1"])), CFG)    # 纯图片
    assert accept(parse_event(group_event(text="今晚开家长会")), dict(CFG, require_keyword=False))

def test_teacher_by_qq_nickname_card():
    m = parse_event(group_event(card="", nick="王老师-语文", uid=555))
    assert m.sender == "王老师-语文"
    assert is_teacher(m, ["王老师"]) and is_teacher(m, ["555"]) and not is_teacher(m, ["556"])
    assert accept(parse_event(group_event()), dict(CFG, qq_group_ids=[]))           # 未设群号 = 所有群

def test_dedup_message_id_and_similar(tmp_path):
    s = SeenStore(str(tmp_path / "s.json"), threshold=0.9)
    a = parse_event(group_event(text="今日作业：1.语文抄写第5课生字两遍 2.数学口算本第12页", mid=1))
    s.add_msg(a)
    assert s.is_dup(parse_event(group_event(text="完全不同的内容但同一个消息", mid=1)))
    assert s.is_dup(parse_event(group_event(text="今日作业:1.语文抄写第5课生字两遍 2.数学口算本第12页!", mid=2)))
    assert not s.is_dup(parse_event(group_event(text="英语：背诵Unit3单词并完成练习册P20", mid=3)))
    assert not s.is_dup(parse_event(group_event(text="", images=["u"], mid=4)))     # 纯图片只按 id

# ---------- 鉴权 ----------
def test_token_and_signature():
    assert onebot.check_token("", {}) and onebot.check_token("t", {"Authorization": "Bearer t"})
    assert onebot.check_token("t", {}, "access_token=t") and not onebot.check_token("t", {"Authorization": "Bearer x"})
    body = b'{"a":1}'
    sig = "sha1=" + hmac.new(b"s", body, hashlib.sha1).hexdigest()
    assert onebot.check_signature("s", body, sig) and not onebot.check_signature("s", body, "sha1=00")

# ---------- 网络: 本地模拟 NapCat ----------
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def wait(cond, t=5):
    end = time.time() + t
    while time.time() < end:
        if cond(): return True
        time.sleep(0.05)
    return False

LOGIN = {"status": "ok", "retcode": 0, "data": {"user_id": 99999, "nickname": "作业小号"}}

async def fake_napcat_client(url, events, token=""):
    """模拟 NapCat 的“WebSocket 客户端”(反向 WS): 连接本程序, 回应 API, 推送事件."""
    from websockets.asyncio.client import connect
    hdr = {"X-Self-ID": "99999", "X-Client-Role": "Universal"}
    if token: hdr["Authorization"] = f"Bearer {token}"
    async with connect(url, additional_headers=hdr) as ws:
        await ws.send(json.dumps({"post_type": "meta_event", "meta_event_type": "lifecycle", "sub_type": "connect", "self_id": 99999}))
        async def responder():
            async for raw in ws:
                d = json.loads(raw)
                if d.get("action") == "get_login_info":
                    await ws.send(json.dumps(dict(LOGIN, echo=d["echo"])))
        t = asyncio.ensure_future(responder())
        for e in events:
            await ws.send(json.dumps(e))
        await asyncio.sleep(1.5)
        t.cancel()

def test_reverse_ws_end_to_end():
    port, got, states = free_port(), [], []
    cfg = dict(CFG, reverse_ws_port=port, access_token="tk")
    conn = onebot.ReverseWsServer(cfg, got.append, lambda s, d="": states.append(s), log=lambda s: None)
    conn.start()
    assert wait(lambda: conn.state == "waiting")
    url = f"ws://127.0.0.1:{port}/onebot/v11/ws"
    th = threading.Thread(target=lambda: asyncio.run(fake_napcat_client(url, [group_event()], "tk")))
    th.start()
    assert wait(lambda: got and conn.connected)
    ok, info = onebot.test_connection(conn)
    assert ok and "99999" in info and conn.self_id == "99999"
    th.join()
    assert wait(lambda: conn.state == "waiting")          # NapCat 断开 -> 回到等待
    conn.stop()
    assert parse_event(got[0]).sender == "王老师" and "connected" in states

def test_reverse_ws_rejects_bad_token():
    port, got = free_port(), []
    conn = onebot.ReverseWsServer(dict(CFG, reverse_ws_port=port, access_token="right"), got.append, log=lambda s: None)
    conn.start(); assert wait(lambda: conn.state == "waiting")
    url = f"ws://127.0.0.1:{port}/onebot/v11/ws"
    try:
        asyncio.run(fake_napcat_client(url, [group_event()], "wrong"))
    except Exception:
        pass
    time.sleep(0.3); conn.stop()
    assert got == []

def test_forward_ws_reconnect():
    """模拟 NapCat “WebSocket 服务端”, 中途重启, 客户端应自动重连并继续收消息."""
    from websockets.asyncio.server import serve
    port, got = free_port(), []
    stop_flags = []
    def run_server(event_mid):
        async def main():
            async def handler(ws):
                assert ws.request.headers.get("Authorization") == "Bearer tk"
                await ws.send(json.dumps(group_event(mid=event_mid)))
                async for raw in ws:
                    d = json.loads(raw)
                    if d.get("action") == "get_login_info":
                        await ws.send(json.dumps(dict(LOGIN, echo=d["echo"])))
            async with serve(handler, "127.0.0.1", port):
                while not stop_flags: await asyncio.sleep(0.05)
        asyncio.run(main())
    t1 = threading.Thread(target=run_server, args=(1,)); t1.start()
    conn = onebot.ForwardWsClient(dict(CFG, forward_ws_url=f"ws://127.0.0.1:{port}", access_token="tk"),
                                  got.append, log=lambda s: None)
    conn.start()
    assert wait(lambda: len(got) == 1 and conn.connected)
    assert onebot.test_connection(conn)[0]
    stop_flags.append(1); t1.join()                        # NapCat 关闭
    assert wait(lambda: not conn.connected)
    stop_flags.clear()
    t2 = threading.Thread(target=run_server, args=(2,)); t2.start()   # NapCat 重新启动
    assert wait(lambda: len(got) == 2 and conn.connected, 10)
    conn.stop(); stop_flags.append(1); t2.join()
    assert got[1]["message_id"] == 2

def test_forward_ws_unreachable():
    conn = onebot.ForwardWsClient(dict(CFG, forward_ws_url=f"ws://127.0.0.1:{free_port()}"), lambda e: None, log=lambda s: None)
    conn.start(); assert wait(lambda: conn.state == "error")
    ok, info = onebot.test_connection(conn)
    conn.stop()
    assert not ok and "WebSocket 服务端" in info

def test_http_post_receiver_with_signature():
    import requests
    port, got = free_port(), []
    conn = onebot.HttpPostServer(dict(CFG, http_post_port=port, http_secret="sec"), got.append, log=lambda s: None)
    conn.start()
    body = json.dumps(group_event()).encode()
    sig = "sha1=" + hmac.new(b"sec", body, hashlib.sha1).hexdigest()
    url = f"http://127.0.0.1:{port}/"
    assert requests.post(url, data=body, headers={"X-Signature": "sha1=bad", "Content-Type": "application/json"}).status_code == 403
    assert requests.post(url, data=body, headers={"X-Signature": sig, "Content-Type": "application/json"}).status_code == 204
    assert wait(lambda: got) and conn.connected
    conn.stop()

def test_http_post_test_connection_via_api():
    class S:
        def post(self, url, **kw):
            self.url = url
            class R:
                def raise_for_status(self): pass
                def json(self): return LOGIN
            return R()
    s = S()
    conn = onebot.HttpPostServer(dict(CFG, napcat_http_api="http://127.0.0.1:3000/"), lambda e: None, log=lambda x: None, session=s)
    ok, info = onebot.test_connection(conn)
    assert ok and s.url == "http://127.0.0.1:3000/get_login_info" and conn.connected
