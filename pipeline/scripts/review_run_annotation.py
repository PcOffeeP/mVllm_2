#!/usr/bin/env python3
"""Run the annotation page and decode frames from a user-selected local video."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import BinaryIO


HERE = Path(__file__).resolve().parent
ASSETS = {
    "/": (HERE / "review_annotation.html", "text/html; charset=utf-8"),
    "/review_annotation.js": (HERE / "review_annotation.js", "text/javascript; charset=utf-8"),
}
VIDEO_ROUTE = re.compile(r"/api/video/([a-f0-9]{32})(?:/frame/([0-9]{1,9}))?")
FORMAT_WHITELIST = "mov,matroska,webm,avi,ogg,mpeg,mpegvideo,mpegts,asf,flv"
MAX_VIDEO_BYTES = 2 * 1024**3
MAX_PIXELS = 16 * 1024**2
DECODE_TIMEOUT = 90
FRAME_BATCH = 4
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ReviewError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status


def decode(command: list[str], video: BinaryIO) -> bytes:
    video.seek(0)
    try:
        result = subprocess.run(
            command,
            pass_fds=(video.fileno(),),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=DECODE_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ReviewError(HTTPStatus.GATEWAY_TIMEOUT, "逐帧解码超时，请尝试较短的视频。") from error
    if result.returncode or result.stderr:
        raise ReviewError(HTTPStatus.UNPROCESSABLE_ENTITY, "无法可靠解码该视频，请检查视频格式或文件是否损坏。")
    return result.stdout


def split_pngs(data: bytes) -> list[bytes]:
    frames = []
    offset = 0
    while offset < len(data):
        start = offset
        if data[offset:offset + 8] != PNG_SIGNATURE:
            raise ReviewError(HTTPStatus.UNPROCESSABLE_ENTITY, "解码输出不完整，无法确认帧号。")
        offset += 8
        while offset + 12 <= len(data):
            length = int.from_bytes(data[offset:offset + 4], "big")
            kind = data[offset + 4:offset + 8]
            offset += length + 12
            if offset > len(data):
                raise ReviewError(HTTPStatus.UNPROCESSABLE_ENTITY, "解码输出不完整，无法确认帧号。")
            if kind == b"IEND" and length == 0:
                frames.append(data[start:offset])
                break
        else:
            raise ReviewError(HTTPStatus.UNPROCESSABLE_ENTITY, "解码输出不完整，无法确认帧号。")
    return frames


class Video:
    def __init__(self, video_id: str, file: BinaryIO):
        self.video_id = video_id
        self.file = file
        self.cache: dict[int, bytes] = {}
        # An anonymous temporary file remains seekable and needs no pathname from the browser.
        self.input_options = [
            "-protocol_whitelist", "fd", "-format_whitelist", FORMAT_WHITELIST,
            "-max_pixels", str(MAX_PIXELS), "-err_detect", "explode", "-threads", "2",
            "-fd", str(file.fileno()),
        ]
        output = decode([
            "ffprobe", "-v", "error", *self.input_options,
            "-select_streams", "V:0", "-show_frames",
            "-show_entries", "frame=width,height,pix_fmt,sample_aspect_ratio",
            "-of", "json", "fd:",
        ], self.file)
        try:
            frames = json.loads(output)["frames"]
            layouts = {
                (frame["width"], frame["height"], frame["pix_fmt"], frame.get("sample_aspect_ratio"))
                for frame in frames
            }
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise ReviewError(HTTPStatus.UNPROCESSABLE_ENTITY, "无法确认视频的解码帧数。") from error
        if not frames:
            raise ReviewError(HTTPStatus.UNPROCESSABLE_ENTITY, "视频没有可用的画面。")
        if len(layouts) != 1:
            raise ReviewError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "视频中途改变分辨率、像素格式或画面比例，无法可靠标注帧索引。",
            )
        self.frame_count = len(frames)

    def frame(self, index: int) -> bytes:
        if index >= self.frame_count:
            raise ReviewError(HTTPStatus.BAD_REQUEST, "该索引超出视频范围。")
        if index not in self.cache:
            # Decode from the beginning to keep n tied to frame order even with variable timestamps.
            start = index - index % FRAME_BATCH
            end = min(start + FRAME_BATCH, self.frame_count) - 1
            output = decode([
                "ffmpeg", "-v", "error", "-nostdin", "-xerror", *self.input_options,
                "-reinit_filter", "0", "-i", "fd:", "-map", "0:V:0",
                "-vf", f"select=between(n\\,{start}\\,{end})", "-fps_mode", "passthrough",
                "-frames:v", str(end - start + 1), "-threads", "2", "-c:v", "png",
                "-compression_level", "1", "-f", "image2pipe", "pipe:1",
            ], self.file)
            frames = split_pngs(output)
            if len(frames) != end - start + 1:
                raise ReviewError(HTTPStatus.UNPROCESSABLE_ENTITY, "实际解码帧数不匹配，无法确认帧号。")
            self.cache = dict(enumerate(frames, start))
        return self.cache[index]


class LocalServer(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.host = f"127.0.0.1:{self.server_port}"
        self.origin = f"http://{self.host}"
        self.token = secrets.token_hex(32)
        self.video: Video | None = None
        self.lock = threading.Lock()

    def clear_video(self) -> None:
        if self.video:
            self.video.file.close()
            self.video = None

    def upload(self, video_id: str, body: BinaryIO, size: int) -> int:
        self.clear_video()
        file = tempfile.TemporaryFile()
        try:
            if shutil.disk_usage(tempfile.gettempdir()).free < size:
                raise ReviewError(HTTPStatus.INSUFFICIENT_STORAGE, "本机临时空间不足，无法打开逐帧查看。")
            while size:
                chunk = body.read(min(size, 1024**2))
                if not chunk:
                    raise ReviewError(HTTPStatus.BAD_REQUEST, "视频读取中断，请重新打开逐帧查看。")
                file.write(chunk)
                size -= len(chunk)
            file.flush()
            self.video = Video(video_id, file)
        except Exception:
            file.close()
            raise
        return self.video.frame_count


class Handler(BaseHTTPRequestHandler):
    server: LocalServer

    def setup(self) -> None:
        self.request.settimeout(20)
        super().setup()

    def log_message(self, format: str, *args) -> None:
        # Do not log URLs or user-controlled request text.
        pass

    def respond(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
            "connect-src 'self'; img-src blob:; media-src blob:; frame-ancestors 'none'; base-uri 'none'",
        )
        self.end_headers()
        if body:
            self.wfile.write(body)

    def respond_json(self, status: HTTPStatus, content: dict) -> None:
        self.respond(status, json.dumps(content, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def run_request(self) -> None:
        try:
            if self.headers.get_all("Host") != [self.server.host]:
                raise ReviewError(HTTPStatus.FORBIDDEN, "请使用本机工具打开的地址。")
            if self.command == "GET" and self.path in ASSETS:
                path, content_type = ASSETS[self.path]
                self.respond(HTTPStatus.OK, path.read_bytes(), content_type)
                return
            if (
                self.headers.get("Origin", self.server.origin) != self.server.origin
                or self.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin"
                or not secrets.compare_digest(
                    self.headers.get("X-Annotation-Session", "").encode(), self.server.token.encode()
                )
            ):
                raise ReviewError(HTTPStatus.FORBIDDEN, "逐帧服务只接受当前本机标注页面的请求。")
            match = VIDEO_ROUTE.fullmatch(self.path)
            if not match:
                raise ReviewError(HTTPStatus.NOT_FOUND, "请求路径无效。")
            video_id, index = match.groups()
            if self.command == "POST" and index is None:
                self.handle_upload(video_id)
                return
            with self.server.lock:
                video = self.server.video
                if self.command == "DELETE" and index is None:
                    if video and video.video_id == video_id:
                        self.server.clear_video()
                elif self.command == "GET" and index is not None:
                    if not video or video.video_id != video_id:
                        raise ReviewError(HTTPStatus.CONFLICT, "逐帧会话已切换，请重新打开当前视频。")
                    frame = video.frame(int(index))
                else:
                    raise ReviewError(HTTPStatus.METHOD_NOT_ALLOWED, "操作无效。")
            if self.command == "GET":
                self.respond(HTTPStatus.OK, frame, "image/png")
            else:
                self.respond(HTTPStatus.NO_CONTENT, b"", "text/plain")
        except ReviewError as error:
            self.respond_json(error.status, {"error": str(error)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            # The browser can cancel an upload or navigation while changing rows.
            pass
        except OSError:
            self.respond_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "本机服务读写失败，请检查临时空间后重试。"})

    def handle_upload(self, video_id: str) -> None:
        lengths = self.headers.get_all("Content-Length") or []
        if (
            self.headers.get_content_type() != "application/octet-stream"
            or self.headers.get("Transfer-Encoding")
            or len(lengths) != 1
            or not re.fullmatch(r"[0-9]{1,12}", lengths[0])
        ):
            raise ReviewError(HTTPStatus.BAD_REQUEST, "视频请求格式无效。")
        size = int(lengths[0])
        if not 0 < size <= MAX_VIDEO_BYTES:
            raise ReviewError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "逐帧查看仅接受不超过 2 GiB 的非空视频。")
        with self.server.lock:
            frame_count = self.server.upload(video_id, self.rfile, size)
        self.respond_json(HTTPStatus.OK, {"frame_count": frame_count})

    do_GET = do_POST = do_DELETE = run_request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-browser", action="store_true", help="只打印地址，不自动打开浏览器。")
    args = parser.parse_args()
    if not all(shutil.which(name) for name in ("ffmpeg", "ffprobe")):
        parser.error("需要本机 PATH 中有 ffmpeg 和 ffprobe。")
    if os.name != "posix":
        parser.error("本机逐帧服务需要 macOS 或 Linux。")
    for name in ("ffmpeg", "ffprobe"):
        try:
            protocols = subprocess.check_output([name, "-hide_banner", "-protocols"], timeout=5).split()
        except (OSError, subprocess.SubprocessError):
            parser.error(f"无法查询 {name} 的输入协议。")
        if b"fd" not in protocols:
            parser.error(f"需要支持 fd 输入协议的 {name}。")
    with LocalServer() as server:
        url = f"{server.origin}/#{server.token}"
        print(f"本机标注地址：{url}\n标注结束后可按 Ctrl+C 关闭服务。", flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
