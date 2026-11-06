#!/usr/bin/env python3
"""Run the annotation page and decode frames from a user-selected local video."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import selectors
import shutil
import subprocess
import tempfile
import threading
import time
import webbrowser
from collections import OrderedDict
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
FRAME_LOOKBACK = 4
FRAME_REWIND_LOOKBACK = 24
FRAME_CONTINUE_LIMIT = 24
FRAME_CACHE_COUNT = 48
FRAME_CACHE_BYTES = 64 * 1024**2
MAX_PNG_BYTES = MAX_PIXELS * 9
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


class FrameDecoder:
    """Read a continuous stream of PNG frames in source presentation order."""

    def __init__(self, command: list[str], video: BinaryIO, start: int):
        video.seek(0)
        self.readers = selectors.DefaultSelector()
        try:
            self.process = subprocess.Popen(
                command,
                pass_fds=(video.fileno(),),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception:
            self.readers.close()
            raise
        self.stdout = self.process.stdout
        self.stderr = self.process.stderr
        try:
            self.readers.register(self.stdout, selectors.EVENT_READ)
            self.readers.register(self.stderr, selectors.EVENT_READ)
        except Exception:
            self.close()
            raise
        self.buffer = bytearray()
        self.next_index = start

    @staticmethod
    def remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ReviewError(HTTPStatus.GATEWAY_TIMEOUT, "逐帧解码超时，请尝试较短的视频。")
        return remaining

    def receive(self, deadline: float) -> None:
        readable = {key.fileobj for key, _ in self.readers.select(self.remaining(deadline))}
        for stream in (self.stderr, self.stdout):
            if stream not in readable:
                continue
            chunk = os.read(stream.fileno(), 64 * 1024)
            if not chunk:
                self.readers.unregister(stream)
            elif stream is self.stderr:
                raise ReviewError(HTTPStatus.UNPROCESSABLE_ENTITY, "无法可靠解码该视频，请检查视频格式或文件是否损坏。")
            else:
                self.buffer.extend(chunk)

    def read(self, size: int, deadline: float) -> bytes:
        while len(self.buffer) < size and self.stdout in self.readers.get_map():
            self.receive(deadline)
        if len(self.buffer) < size:
            raise ReviewError(HTTPStatus.UNPROCESSABLE_ENTITY, "解码输出不完整，无法确认帧号。")
        result = bytes(self.buffer[:size])
        del self.buffer[:size]
        return result

    def frame(self, deadline: float) -> bytes:
        image = bytearray(self.read(len(PNG_SIGNATURE), deadline))
        if image != PNG_SIGNATURE:
            raise ReviewError(HTTPStatus.UNPROCESSABLE_ENTITY, "解码输出不完整，无法确认帧号。")
        while True:
            header = self.read(8, deadline)
            length = int.from_bytes(header[:4], "big")
            if len(image) + length + 12 > MAX_PNG_BYTES:
                raise ReviewError(HTTPStatus.UNPROCESSABLE_ENTITY, "解码画面超出大小限制，无法确认帧号。")
            image.extend(header)
            image.extend(self.read(length + 4, deadline))
            if header[4:] == b"IEND" and length == 0:
                self.next_index += 1
                return bytes(image)

    def finish(self, deadline: float) -> None:
        while self.readers.get_map() and not self.buffer:
            self.receive(deadline)
        if self.buffer:
            raise ReviewError(HTTPStatus.UNPROCESSABLE_ENTITY, "实际解码帧数不匹配，无法确认帧号。")
        try:
            returncode = self.process.wait(timeout=self.remaining(deadline))
        except subprocess.TimeoutExpired as error:
            raise ReviewError(HTTPStatus.GATEWAY_TIMEOUT, "逐帧解码超时，请尝试较短的视频。") from error
        if returncode:
            raise ReviewError(HTTPStatus.UNPROCESSABLE_ENTITY, "无法可靠解码该视频，请检查视频格式或文件是否损坏。")

    def close(self) -> None:
        # A blocked pipe writer must be released before waiting for the process.
        self.readers.close()
        self.stdout.close()
        self.stderr.close()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


class Video:
    def __init__(self, video_id: str, file: BinaryIO):
        self.video_id = video_id
        self.file = file
        self.cache: OrderedDict[int, bytes] = OrderedDict()
        self.cache_bytes = 0
        self.decoder: FrameDecoder | None = None
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

    def stop_decoder(self) -> None:
        if self.decoder:
            self.decoder.close()
            self.decoder = None

    def close(self) -> None:
        try:
            self.stop_decoder()
        finally:
            self.file.close()

    def frame(self, index: int) -> bytes:
        if not 0 <= index < self.frame_count:
            raise ReviewError(HTTPStatus.BAD_REQUEST, "该索引超出视频范围。")
        if index in self.cache:
            return self.cache[index]
        deadline = time.monotonic() + DECODE_TIMEOUT
        try:
            if not self.decoder or not 0 <= index - self.decoder.next_index <= FRAME_CONTINUE_LIMIT:
                lookback = FRAME_LOOKBACK
                if self.cache and index < next(iter(self.cache)):
                    average_bytes = self.cache_bytes // len(self.cache)
                    lookback = min(FRAME_REWIND_LOOKBACK, FRAME_CACHE_BYTES // average_bytes - 1)
                self.stop_decoder()
                self.cache.clear()
                self.cache_bytes = 0
                # A fresh decode still starts at frame zero, so n has no timestamp dependence.
                start = max(0, index - max(0, lookback))
                self.decoder = FrameDecoder([
                    "ffmpeg", "-v", "error", "-nostdin", "-xerror", *self.input_options,
                    "-reinit_filter", "0", "-i", "fd:", "-map", "0:V:0",
                    "-vf", f"select=gte(n\\,{start})", "-fps_mode", "passthrough",
                    "-threads", "2", "-c:v", "png",
                    "-compression_level", "1", "-f", "image2pipe", "pipe:1",
                ], self.file, start)
            while self.decoder.next_index <= index:
                frame_index = self.decoder.next_index
                frame = self.decoder.frame(deadline)
                self.cache[frame_index] = frame
                self.cache_bytes += len(frame)
                while len(self.cache) > FRAME_CACHE_COUNT or (len(self.cache) > 1 and self.cache_bytes > FRAME_CACHE_BYTES):
                    _, evicted = self.cache.popitem(last=False)
                    self.cache_bytes -= len(evicted)
            if index == self.frame_count - 1:
                self.decoder.finish(deadline)
                self.stop_decoder()
        except Exception:
            self.stop_decoder()
            self.cache.clear()
            self.cache_bytes = 0
            raise
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
            self.video.close()
            self.video = None

    def server_close(self) -> None:
        super().server_close()
        with self.lock:
            self.clear_video()

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
