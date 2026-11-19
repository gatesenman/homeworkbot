"""NapCat / OneBot v11 连接: 反向 WS 服务端、正向 WS 客户端、HTTP POST 上报接收. 自动重连.

用法: conn = make_connector(cfg, on_event, on_status, log); conn.start(); conn.call("get_login_info")
on_event(event_dict) 在后台线程中被调用; on_status(state:str, detail:str).
"""
import asyncio, hashlib, hmac, json, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REVERSE_PATH = "/onebot/v11/ws"

class Status:
    STOPPED, WAITING, CONNECTING, CONNECTED, ERROR = "stopped", "waiting", "connecting", "connected", "error"

def check_token(expected, headers, query=""):
    """OneBot 鉴权: Authorization: Bearer <token> 或 ?access_token=<token>."""
    if not expected:
        return True
    auth = headers.get("Authorization") or headers.get("authorization") or ""
    if auth.replace("Bearer", "").replace("Token", "").strip() == expected:
        return True
    from urllib.parse import parse_qs
    return parse_qs(query).get("access_token", [""])[0] == expected

def check_signature(secret, body, header):
    """HTTP 上报签名: X-Signature: sha1=<hmac_sha1(secret, body)>."""
    if not secret:
        return True
    want = "sha1=" + hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
    return hmac.compare_digest(want, header or "")


class _WsBase:
    """WS 两种模式共用: 后台 asyncio 线程, 事件分发, API 调用(echo 匹配)."""
    def __init__(self, cfg, on_event, on_status=None, log=print):
        self.cfg, self.on_event, self.log = cfg, on_event, log
        self.on_status = on_status or (lambda s, d="": None)
        self.state, self.detail, self.self_id = Status.STOPPED, "", ""
        self.loop, self.thread, self.ws = None, None, None
        self._pending, self._stop = {}, None

    def _set(self, state, detail=""):
        self.state, self.detail = state, detail
        try: self.on_status(state, detail)
        except Exception: pass

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        ready = threading.Event()
        def run():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self._stop = asyncio.Event()
            ready.set()
            try:
                self.loop.run_until_complete(self._main())
            except Exception as e:
                self._set(Status.ERROR, str(e)); self.log(f"连接线程异常: {e}")
            finally:
                self.loop.close()
        self.thread = threading.Thread(target=run, daemon=True, name="onebot"); self.thread.start()
        ready.wait(5)

    def stop(self):
        if self.loop and self._stop and not self.loop.is_closed():
            try: self.loop.call_soon_threadsafe(self._stop.set)
            except RuntimeError: pass
        if self.thread: self.thread.join(5)
        self._set(Status.STOPPED, "")

    @property
    def connected(self):
        return self.state == Status.CONNECTED

    async def _handle(self, ws):
        """处理一条已建立的连接, 直到断开."""
        self.ws = ws
        self._set(Status.CONNECTED, "NapCat 已连接")
        try:
            asyncio.ensure_future(self._fetch_login())
            async for raw in ws:
                try:
                    data = json.loads(raw)
                except ValueError:
                    continue
                if "echo" in data and data.get("echo") in self._pending:
                    fut = self._pending.pop(data["echo"])
                    if not fut.done(): fut.set_result(data)
                    continue
                if data.get("post_type") == "meta_event":
                    if data.get("meta_event_type") == "lifecycle" and data.get("self_id"):
                        self.self_id = str(data["self_id"])
                    continue
                if data.get("post_type"):
                    self._dispatch(data)          # on_event 只做入队, 不会阻塞事件循环
        finally:
            if self.ws is ws:
                self.ws = None
            for f in self._pending.values():
                if not f.done(): f.set_exception(ConnectionError("连接已断开"))
            self._pending.clear()

    def _dispatch(self, data):
        try:
            self.on_event(data)
        except Exception as e:
            self.log(f"处理事件出错: {e}")

    async def _fetch_login(self):
        try:
            d = await self._call("get_login_info", {}, 5)
            info = d.get("data") or {}
            self.self_id = str(info.get("user_id") or self.self_id)
            self._set(Status.CONNECTED, f"已连接 QQ {info.get('nickname', '')}({self.self_id})")
        except Exception:
            pass

    async def _call(self, action, params, timeout):
        if not self.ws:
            raise ConnectionError("NapCat 未连接")
        echo = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self._pending[echo] = fut
        await self.ws.send(json.dumps({"action": action, "params": params or {}, "echo": echo}))
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(echo, None)

    def call(self, action, params=None, timeout=8):
        """线程安全的 OneBot API 调用, 返回响应 dict."""
        if not self.loop or not self.connected:
            raise ConnectionError("NapCat 未连接")
        f = asyncio.run_coroutine_threadsafe(self._call(action, params, timeout), self.loop)
        return f.result(timeout + 1)


class ReverseWsServer(_WsBase):
    """本程序作为 WS 服务端, NapCat 主动连过来(推荐: NapCat 重启后会自动重连)."""
    mode = "reverse_ws"

    @property
    def address(self):
        return f"ws://{self.cfg['reverse_ws_host']}:{self.cfg['reverse_ws_port']}{REVERSE_PATH}"

    async def _main(self):
        from websockets.asyncio.server import serve
        token = self.cfg.get("access_token", "")
        async def handler(ws):
            req = ws.request
            path, _, query = req.path.partition("?")
            if not check_token(token, req.headers, query):
                self.log("拒绝连接: access_token 不匹配"); await ws.close(1008, "token"); return
            if self.ws is not None:
                self.log("已有 NapCat 连接, 新连接将替换旧连接")
            role = req.headers.get("X-Client-Role", "Universal")
            sid = req.headers.get("X-Self-ID", "")
            if sid: self.self_id = sid
            self.log(f"NapCat 已连接 (role={role}, QQ={sid or '?'}, path={path})")
            await self._handle(ws)
            if self.ws is None:
                self._set(Status.WAITING, f"NapCat 已断开, 等待重连 {self.address}")
                self.log("NapCat 连接断开, 等待重连")
        try:
            async with serve(handler, self.cfg["reverse_ws_host"], int(self.cfg["reverse_ws_port"]),
                             max_size=32 * 1024 * 1024, ping_interval=30):
                self._set(Status.WAITING, f"等待 NapCat 连接 {self.address}")
                self.log(f"反向 WS 服务已启动: {self.address}")
                await self._stop.wait()
        except OSError as e:
            self._set(Status.ERROR, f"端口 {self.cfg['reverse_ws_port']} 无法监听: {e}")
            self.log(f"反向 WS 服务启动失败: {e}")


class ForwardWsClient(_WsBase):
    """本程序作为 WS 客户端, 连接 NapCat 的 WS 服务端; 断线指数退避重连."""
    mode = "forward_ws"

    async def _main(self):
        from websockets.asyncio.client import connect
        url, token, delay = self.cfg["forward_ws_url"], self.cfg.get("access_token", ""), 1
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        while not self._stop.is_set():
            self._set(Status.CONNECTING, f"正在连接 {url}")
            try:
                async with connect(url, additional_headers=headers, max_size=32 * 1024 * 1024,
                                   open_timeout=8, ping_interval=30) as ws:
                    delay = 1
                    self.log(f"已连接 NapCat: {url}")
                    task = asyncio.ensure_future(self._handle(ws))
                    stop = asyncio.ensure_future(self._stop.wait())
                    await asyncio.wait([task, stop], return_when=asyncio.FIRST_COMPLETED)
                    if stop.done():
                        task.cancel(); await ws.close(); break
                    stop.cancel()
                    self.log("与 NapCat 的连接断开")
            except Exception as e:
                self._set(Status.ERROR, f"连接失败: {e}; {delay}s 后重试")
                self.log(f"连接 NapCat 失败: {e}; {delay}s 后重试")
            try:
                await asyncio.wait_for(self._stop.wait(), delay)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, 60)


class HttpPostServer:
    """NapCat 的 HTTP 客户端把事件 POST 到本程序; API 调用走 NapCat HTTP 服务端(napcat_http_api)."""
    mode = "http_post"

    def __init__(self, cfg, on_event, on_status=None, log=print, session=None):
        self.cfg, self.on_event, self.log = cfg, on_event, log
        self.on_status = on_status or (lambda s, d="": None)
        self.state, self.detail, self.self_id = Status.STOPPED, "", ""
        self.httpd, self.thread, self.session, self.last_event = None, None, session, 0

    @property
    def address(self):
        return f"http://{self.cfg['http_post_host']}:{self.cfg['http_post_port']}/"

    @property
    def connected(self):
        return self.state == Status.CONNECTED

    def _set(self, state, detail=""):
        self.state, self.detail = state, detail
        try: self.on_status(state, detail)
        except Exception: pass

    def start(self):
        outer = self
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                path, _, query = self.path.partition("?")
                if not check_token(outer.cfg.get("access_token", ""), self.headers, query) and \
                        not outer.cfg.get("http_secret"):
                    self.send_response(401); self.end_headers(); return
                if not check_signature(outer.cfg.get("http_secret", ""), body, self.headers.get("X-Signature")):
                    self.send_response(403); self.end_headers(); outer.log("拒绝上报: 签名不匹配"); return
                self.send_response(204); self.end_headers()
                try:
                    data = json.loads(body.decode("utf-8"))
                except ValueError:
                    return
                outer.last_event = time.time()
                if data.get("self_id"): outer.self_id = str(data["self_id"])
                if outer.state != Status.CONNECTED:
                    outer._set(Status.CONNECTED, f"正在接收 NapCat 上报 (QQ {outer.self_id})")
                if data.get("post_type") and data.get("post_type") != "meta_event":
                    try: outer.on_event(data)
                    except Exception as e: outer.log(f"处理事件出错: {e}")
            do_PUT = do_POST
        try:
            self.httpd = ThreadingHTTPServer((self.cfg["http_post_host"], int(self.cfg["http_post_port"])), H)
        except OSError as e:
            self._set(Status.ERROR, f"端口 {self.cfg['http_post_port']} 无法监听: {e}")
            self.log(f"HTTP 上报服务启动失败: {e}"); return
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="onebot-http")
        self.thread.start()
        self._set(Status.WAITING, f"等待 NapCat 上报到 {self.address}")
        self.log(f"HTTP 上报接收已启动: {self.address}")

    def stop(self):
        if self.httpd:
            self.httpd.shutdown(); self.httpd.server_close(); self.httpd = None
        self._set(Status.STOPPED, "")

    def call(self, action, params=None, timeout=8):
        session = self.session
        if session is None:
            import requests as session
        token = self.cfg.get("access_token", "")
        r = session.post(self.cfg["napcat_http_api"].rstrip("/") + "/" + action, json=params or {}, timeout=timeout,
                         headers={"Authorization": f"Bearer {token}"} if token else {})
        r.raise_for_status()
        d = r.json()
        if d.get("status") == "ok" and action == "get_login_info":
            self.self_id = str((d.get("data") or {}).get("user_id") or self.self_id)
            if self.state != Status.CONNECTED:
                self._set(Status.CONNECTED, f"NapCat HTTP 接口可用 (QQ {self.self_id})")
        return d


def make_connector(cfg, on_event, on_status=None, log=print):
    mode = cfg.get("onebot_mode", "reverse_ws")
    cls = {"reverse_ws": ReverseWsServer, "forward_ws": ForwardWsClient, "http_post": HttpPostServer}.get(mode)
    if not cls:
        raise ValueError(f"未知连接方式: {mode}")
    return cls(cfg, on_event, on_status, log)

def test_connection(conn, timeout=6):
    """返回 (ok, 说明). 调用 get_login_info 确认 NapCat 在线及登录的 QQ."""
    try:
        d = conn.call("get_login_info", {}, timeout)
    except Exception as e:
        hint = {"reverse_ws": "请确认 NapCat 已登录, 且网络配置中添加了 WebSocket 客户端指向 " + getattr(conn, "address", ""),
                "forward_ws": "请确认 NapCat 已登录, 且开启了 WebSocket 服务端, 地址/端口/token 一致",
                "http_post": "请确认 NapCat 开启了 HTTP 服务端, 且“NapCat HTTP 接口”地址/token 正确"}.get(conn.mode, "")
        return False, f"连接失败: {e}。{hint}"
    if d.get("status") != "ok" and d.get("retcode", 0) != 0:
        return False, f"NapCat 返回错误: {d.get('message') or d.get('wording') or d}"
    info = d.get("data") or {}
    return True, f"连接正常, 当前登录 QQ: {info.get('nickname', '')} ({info.get('user_id', '')})"
