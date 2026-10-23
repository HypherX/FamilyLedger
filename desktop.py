"""家庭账本桌面入口：本机服务加一个窗口，和 ArxivReader 的运行方式一致。"""
import json
import multiprocessing as mp
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time


def _backend(pipe, data_dir, ticket, cookie):
    try:
        os.environ["FAMILYLEDGER_DATA"] = data_dir
        from app import desktop_session
        import uvicorn
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        desktop_session.configure(sock.getsockname()[1], ticket, cookie)
        from app.main import app
        server = uvicorn.Server(uvicorn.Config(
            app, log_level="info", access_log=False, timeout_graceful_shutdown=5, loop="asyncio"))

        def control():
            while not server.started:
                if server.should_exit:
                    return
                time.sleep(0.03)
            pipe.send({"ok": True, "port": sock.getsockname()[1]})
            try:
                while pipe.recv() != "stop":
                    pass
            except EOFError:
                pass
            server.should_exit = True

        threading.Thread(target=control, daemon=True).start()
        server.run(sockets=[sock])
    except Exception:
        try:
            pipe.send({"ok": False})
        except (EOFError, OSError):
            pass
    finally:
        pipe.close()


def _root():
    override = os.environ.get("FAMILYLEDGER_HOME")
    if override:
        return Path(override)
    from platformdirs import user_data_dir
    return Path(user_data_dir("FamilyLedger", appauthor=False))


def _notice(message):
    if sys.platform == "darwin":
        from AppKit import NSAlert
        alert = NSAlert.alloc().init()
        alert.setMessageText_("家庭账本")
        alert.setInformativeText_(message)
        alert.addButtonWithTitle_("确定")
        alert.runModal()
    else:
        print(message, file=sys.stderr)


class _Instance:
    def __init__(self, root):
        self.file = open(root / "instance.lock", "a+b")
        try:
            import fcntl
            fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.owned = False
            for _ in range(30):
                try:
                    self.file.seek(0)
                    info = json.loads(self.file.read().decode())
                    with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=1) as client:
                        client.sendall(info["token"].encode())
                    break
                except (OSError, ValueError, KeyError):
                    time.sleep(0.1)
            self.file.close()
            return
        self.owned = True
        self.token = secrets.token_hex(32)
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(2)
        self.file.seek(0)
        self.file.truncate()
        self.file.write(json.dumps({"port": self.listener.getsockname()[1], "token": self.token}).encode())
        self.file.flush()

    def watch(self, callback):
        def wait():
            while self.owned:
                try:
                    client, _ = self.listener.accept()
                    with client:
                        client.settimeout(1)
                        if secrets.compare_digest(client.recv(128).decode(), self.token):
                            callback()
                except (OSError, UnicodeError):
                    pass
        threading.Thread(target=wait, daemon=True).start()

    def close(self):
        if self.owned:
            self.owned = False
            self.listener.close()
            self.file.close()


class _Bridge:
    def __init__(self, data_dir, origin):
        self._data = data_dir
        self._origin = origin
        self._window = None

    def perform(self, action, payload):
        try:
            from desktop_native import allowed
            if not self._window or not allowed(self._window.get_current_url() or "", self._origin):
                raise ValueError("untrusted")
            if action == "open_data":
                subprocess.Popen(["/usr/bin/open", str(self._data)])
            else:
                raise ValueError("unknown")
            return {"ok": True}
        except Exception:
            return {"ok": False}


def main():
    instance = None
    process = None
    parent = None
    try:
        root = _root().resolve()
        root.mkdir(parents=True, exist_ok=True)
        instance = _Instance(root)
        if not instance.owned:
            return
        if getattr(sys, "frozen", False):
            data = root / "data"
        else:
            data = Path(__file__).resolve().parent / "data"
        data.mkdir(parents=True, exist_ok=True)
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        ticket, cookie = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        process = ctx.Process(target=_backend, args=(child, str(data), ticket, cookie))
        process.start()
        child.close()
        if not parent.poll(45):
            raise RuntimeError("startup_timeout")
        ready = parent.recv()
        if not ready.get("ok"):
            raise RuntimeError("startup_failed")
        origin = f"http://127.0.0.1:{ready['port']}"
        import webview
        from desktop_native import install_navigation_guard
        gui = install_navigation_guard(origin)
        bridge = _Bridge(data, origin)
        window = webview.create_window(
            "家庭账本", origin + "/desktop-start?ticket=" + ticket,
            js_api=bridge, width=1280, height=840, min_size=(960, 640))
        bridge._window = window

        def shutdown():
            try:
                parent.send("stop")
            except (EOFError, OSError):
                pass

        window.events.closing += shutdown
        instance.watch(lambda: (window.restore(), window.show()))
        webview.start(gui=gui, debug=False, private_mode=False, storage_path=str(root / "webview"))
    except Exception:
        _notice("家庭账本无法启动。请确认使用 Python 3.12，并已安装依赖。")
    finally:
        if process is not None:
            if parent:
                try:
                    parent.send("stop")
                except (EOFError, OSError):
                    pass
            process.join(8)
            if process.is_alive():
                process.terminate()
                process.join(2)
        if parent:
            parent.close()
        if instance is not None:
            instance.close()


if __name__ == "__main__":
    mp.freeze_support()
    main()
