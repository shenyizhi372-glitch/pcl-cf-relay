#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PCL 自定义镜像代理（纯标准库，无第三方依赖）

用途：替代 mod.mcimirror.top，让 PCL 的 CurseForge / Modrinth 下载继续可用。
把本文件放到你的服务器上，用 python3 proxy.py 启动，前面套一层 Caddy/Nginx 做 HTTPS，
再用 apply-custom-mirror.ps1 把 PCL 的镜像域名改成你的域名。

路由：
  /curseforge/*  -> CF_API_KEY 存在时优先官方 api.curseforge.com，失败再试 CF_UPSTREAMS 里的其他上游
  /modrinth/*    -> api.modrinth.com
  /files/*       -> edge.forgecdn.net（CurseForge 文件）
  /data/*        -> cdn.modrinth.com（Modrinth 文件）
  /__health      -> 健康检查

环境变量（都可用默认值）：
  BIND=127.0.0.1
  PORT=8088
  CF_API_KEY=""                         # 有官方 key 就填，没有留空
  CF_UPSTREAMS="https://api.curseforge.com|https://mod.mcimirror.top/curseforge"
  MR_UPSTREAMS="https://api.modrinth.com"
  FILE_UPSTREAMS="https://edge.forgecdn.net"
  CDN_UPSTREAMS="https://cdn.modrinth.com"
  UPSTREAM_TIMEOUT=25

安全：默认只监听 127.0.0.1，由 Caddy 反代；不要直接暴露到公网裸端口，
      也不要泄露 CF_API_KEY。PCL 无法携带自定义鉴权头，所以本代理不适合加简单鉴权，
      建议用「不公开的域名 + 限制 UA」来降低滥用。
"""
import os
import sys
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BIND = os.environ.get("BIND", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8088"))
CF_KEY = os.environ.get("CF_API_KEY", "").strip()
TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "25"))


def _list(name, default):
    raw = os.environ.get(name, default)
    return [x.strip() for x in raw.split("|") if x.strip()]


CF_UPSTREAMS = _list("CF_UPSTREAMS", "https://api.curseforge.com|https://mod.mcimirror.top/curseforge")
MR_UPSTREAMS = _list("MR_UPSTREAMS", "https://api.modrinth.com")
FILE_UPSTREAMS = _list("FILE_UPSTREAMS", "https://edge.forgecdn.net")
CDN_UPSTREAMS = _list("CDN_UPSTREAMS", "https://cdn.modrinth.com")

RETRY_STATUS = {403, 404, 429, 500, 502, 503, 504}


def route(path):
    if path.startswith("/curseforge/"):
        return CF_UPSTREAMS, path[len("/curseforge"):], True
    if path.startswith("/modrinth/"):
        return MR_UPSTREAMS, path[len("/modrinth"):], False
    if path.startswith("/files/"):
        return FILE_UPSTREAMS, path, True
    if path.startswith("/data/"):
        return CDN_UPSTREAMS, path, False
    return None, None, False


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def _handle(self):
        if self.path == "/__health":
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length > 0 else None

        upstreams, rest, with_key = route(self.path)
        if upstreams is None:
            self.send_error(404, "unknown path")
            return

        headers = {}
        for k, v in self.headers.items():
            if k.lower() in ("host", "connection", "content-length", "accept-encoding"):
                continue
            headers[k] = v
        headers["Accept-Encoding"] = "identity"  # 避免 gzip 透传问题

        last = None
        for base in upstreams:
            url = base.rstrip("/") + rest
            h = dict(headers)
            if with_key and CF_KEY:
                h["x-api-key"] = CF_KEY
            req = urllib.request.Request(url, data=body, headers=h, method=self.command)
            try:
                resp = urllib.request.urlopen(req, timeout=TIMEOUT)
            except urllib.error.HTTPError as e:
                last = e
                sys.stderr.write("upstream %s -> HTTP %s\n" % (url, e.code))
                if e.code in RETRY_STATUS:
                    continue
                self._relay(e)
                return
            except Exception as e:
                last = e
                sys.stderr.write("upstream %s -> %s\n" % (url, e))
                continue
            self._relay(resp)
            return

        code = getattr(last, "code", 502) or 502
        if code == 403:
            code = 502
        msg = ("all upstreams failed: %s" % (last,)).encode("utf-8", "replace")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(msg)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(msg)

    def _relay(self, resp):
        status = getattr(resp, "status", None) or getattr(resp, "code", 502)
        self.send_response(status)
        clen = resp.headers.get("Content-Length")
        for k, v in resp.headers.items():
            if k.lower() in ("transfer-encoding", "connection", "content-length", "content-encoding"):
                continue
            self.send_header(k, v)
        if clen is not None:
            self.send_header("Content-Length", clen)
        else:
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command == "HEAD":
            return
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            self.wfile.write(chunk)

    do_GET = _handle
    do_HEAD = _handle
    do_POST = _handle


if __name__ == "__main__":
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    print("PCL mirror proxy listening on http://%s:%d" % (BIND, PORT))
    print("curseforge upstreams:", CF_UPSTREAMS, "key:", "YES" if CF_KEY else "NO")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
