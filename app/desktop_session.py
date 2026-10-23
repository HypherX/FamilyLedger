"""桌面窗口注入的短期会话，避免本机其他网页调用这个接口。"""
import secrets
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

session = None


def configure(port, ticket, cookie):
    global session
    session = {"host": f"127.0.0.1:{port}", "ticket": ticket, "cookie": cookie}


class DesktopSessionMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not session or scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        host = headers.get(b"host", b"").decode("latin1")
        origin = headers.get(b"origin", b"").decode("latin1")
        if host != session["host"] or (origin and origin != "http://" + session["host"]):
            return await self._reject(send, 403)
        if headers.get(b"sec-fetch-site") == b"cross-site":
            return await self._reject(send, 403)
        if scope["path"] == "/desktop-start":
            supplied = parse_qs(scope.get("query_string", b"").decode()).get("ticket", [""])[0]
            ticket = session.get("ticket")
            if scope["method"] != "GET" or not ticket or not secrets.compare_digest(supplied, ticket):
                return await self._reject(send, 401)
            session["ticket"] = None
            await send({"type": "http.response.start", "status": 303, "headers": [
                (b"location", b"/"),
                (b"cache-control", b"no-store"),
                (b"set-cookie", f"ledger_session={session['cookie']}; Path=/; HttpOnly; SameSite=Strict".encode()),
            ]})
            return await send({"type": "http.response.body", "body": b""})
        cookies = SimpleCookie()
        try:
            cookies.load(headers.get(b"cookie", b"").decode("latin1"))
            value = cookies["ledger_session"].value
        except (KeyError, ValueError):
            return await self._reject(send, 401)
        if not secrets.compare_digest(value, session["cookie"]):
            return await self._reject(send, 401)

        async def secure_send(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend([
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"content-security-policy",
                     b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                     b"font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
                     b"form-action 'self'; frame-ancestors 'none'"),
                ])
            await send(message)

        await self.app(scope, receive, secure_send)

    @staticmethod
    async def _reject(send, status):
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", b"application/json"),
        ]})
        await send({"type": "http.response.body", "body": b'{"detail":"forbidden"}'})
