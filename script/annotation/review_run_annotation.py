#!/usr/bin/env python3
"""Run the annotation page with local annotation files and frame decoding."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import secrets
import selectors
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import webbrowser
from collections import OrderedDict
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import BinaryIO


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
DEFAULT_CSV = "data/annotation-table-full.csv"
DEFAULT_VIDEOS = "data/videos"
ASSETS = {
    "/": (HERE / "review_annotation.html", "text/html; charset=utf-8"),
    "/review_annotation.js": (HERE / "review_annotation.js", "text/javascript; charset=utf-8"),
}
VIDEO_ROUTE = re.compile(r"/api/video/([a-f0-9]{32})(?:/frame/([0-9]{1,9}))?")
VIDEO_FILE_ROUTE = re.compile(r"/api/video/file/([a-f0-9]{32})")
VIDEO_PREVIEW_ROUTE = re.compile(r"/api/video/preview/([a-f0-9]{32})")
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv", ".ogv", ".mpeg",
                    ".mpg", ".mts", ".m2ts", ".wmv", ".3gp", ".flv"}
FORMAT_WHITELIST = "mov,matroska,webm,avi,ogg,mpeg,mpegvideo,mpegts,asf,flv"
MAX_VIDEO_BYTES = 2 * 1024**3
MAX_CSV_BYTES = 32 * 1024**2
MAX_VIDEO_ENTRIES = 10000
MAX_PIXELS = 16 * 1024**2
DECODE_TIMEOUT = 90
PREVIEW_TIMEOUT = 180
MAX_PREVIEW_BYTES = 512 * 1024**2
FRAME_LOOKBACK = 4
FRAME_REWIND_LOOKBACK = 24
FRAME_CONTINUE_LIMIT = 24
FRAME_CACHE_COUNT = 48
FRAME_CACHE_BYTES = 64 * 1024**2
MAX_PNG_BYTES = MAX_PIXELS * 9
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def default_source_warnings(project_root: Path) -> list[str]:
    warnings = []
    if not (project_root / DEFAULT_CSV).is_file():
        warnings.append(f"默认标注表 {DEFAULT_CSV} 在项目根目录 {project_root} 不存在；请在页面的 CSV 路径填写实际标注表路径。")
    if not (project_root / DEFAULT_VIDEOS).is_dir():
        warnings.append(f"默认视频目录 {DEFAULT_VIDEOS} 在项目根目录 {project_root} 不存在；请在页面填写实际视频目录路径。")
    return warnings


class ReviewError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status


@contextmanager
def open_directory(path: Path):
    """Open an already resolved directory without following replaced symlinks."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def open_regular(directory: int, name: str) -> BinaryIO:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("not a regular file")
        return os.fdopen(fd, "rb")
    except Exception:
        os.close(fd)
        raise


def read_csv_bytes(file: BinaryIO) -> bytes:
    raw = file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise ReviewError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "CSV 超出大小限制。")
    return raw


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


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
        # A seekable file descriptor keeps ffmpeg from resolving any paths from the browser.
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
    def __init__(self, project_root: Path = PROJECT_ROOT):
        super().__init__(("127.0.0.1", 0), Handler)
        self.host = f"127.0.0.1:{self.server_port}"
        self.origin = f"http://{self.host}"
        self.token = secrets.token_hex(32)
        self.video: Video | None = None
        self.lock = threading.Lock()
        self.source_lock = threading.Lock()
        self.preview_lock = threading.Lock()
        self.preview_stop = threading.Event()
        self.project_root = project_root.resolve()
        self.csv_paths: set[Path] = set()
        self.video_paths: dict[str, tuple[Path, tuple[int, int, int, int, int]]] = {}

    def source_path(self, value: object) -> Path:
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise ReviewError(HTTPStatus.BAD_REQUEST, "请填写有效的本机路径。")
        try:
            path = Path(value).expanduser()
            return (self.project_root / path).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as error:
            raise ReviewError(HTTPStatus.NOT_FOUND, "找不到此路径，或本机没有访问权限。") from error

    def read_csv(self, value: object) -> dict:
        try:
            path = self.source_path(value)
        except ReviewError as error:
            if value == DEFAULT_CSV and error.status == HTTPStatus.NOT_FOUND:
                raise ReviewError(HTTPStatus.NOT_FOUND, f"默认标注表 {DEFAULT_CSV} 不存在；请在页面的 CSV 路径填写实际标注表路径。") from error
            raise
        if path.suffix.lower() != ".csv":
            raise ReviewError(HTTPStatus.BAD_REQUEST, "请选择 CSV 文件。")
        try:
            with open_directory(path.parent) as directory, open_regular(directory, path.name) as file:
                raw = read_csv_bytes(file)
            csv = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ReviewError(HTTPStatus.UNPROCESSABLE_ENTITY, "无法读取此 CSV，请检查文件和 UTF-8 编码。") from error
        with self.source_lock:
            self.csv_paths.add(path)
        return {"path": str(path), "name": path.name, "csv": csv, "sha256": sha256(raw)}

    def write_csv(self, value: object, expected: object, csv: object) -> dict:
        if not isinstance(value, str) or not isinstance(expected, str) or not isinstance(csv, str):
            raise ReviewError(HTTPStatus.BAD_REQUEST, "CSV 写回请求格式无效。")
        if not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise ReviewError(HTTPStatus.BAD_REQUEST, "CSV 原内容校验值无效。")
        try:
            raw = csv.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ReviewError(HTTPStatus.BAD_REQUEST, "CSV 必须使用有效的 UTF-8 编码。") from error
        if not raw or len(raw) > MAX_CSV_BYTES:
            raise ReviewError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "CSV 为空或超出大小限制。")
        path = Path(value)
        with self.source_lock:
            if path not in self.csv_paths:
                raise ReviewError(HTTPStatus.FORBIDDEN, "请先从当前页面打开要写回的 CSV。")
            try:
                with open_directory(path.parent) as directory:
                    self.replace_csv(directory, path.name, expected, raw)
            except OSError as error:
                raise ReviewError(HTTPStatus.CONFLICT, "原 CSV 无法写回，请核对文件是否被移动或已变成只读。") from error
        return {"sha256": sha256(raw)}

    @staticmethod
    def replace_csv(directory: int, name: str, expected: str, raw: bytes) -> None:
        def conflict():
            return ReviewError(HTTPStatus.CONFLICT, "原 CSV 已被其他程序修改，已暂停写回。可导出当前标注另存。")

        with open_regular(directory, name) as original:
            before = os.fstat(original.fileno())
            if sha256(read_csv_bytes(original)) != expected:
                raise conflict()
            if not os.access(name, os.W_OK, dir_fd=directory, follow_symlinks=False):
                raise OSError("not writable")
        temporary = ".annotation-" + secrets.token_hex(16) + ".tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, "wb") as staged:
                staged.write(raw)
                os.fchmod(staged.fileno(), stat.S_IMODE(before.st_mode) & 0o777)
                staged.flush()
                os.fsync(staged.fileno())
            with open_regular(directory, name) as original:
                latest = os.fstat(original.fileno())
                if (latest.st_dev, latest.st_ino) != (before.st_dev, before.st_ino):
                    raise conflict()
                if sha256(read_csv_bytes(original)) != expected:
                    raise conflict()
                current = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if file_identity(current) != file_identity(latest):
                    raise conflict()
            os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass

    def video_library(self, value: object) -> dict:
        try:
            root = self.source_path(value)
        except ReviewError as error:
            if value == DEFAULT_VIDEOS and error.status == HTTPStatus.NOT_FOUND:
                raise ReviewError(HTTPStatus.NOT_FOUND, f"默认视频目录 {DEFAULT_VIDEOS} 不存在；请在页面填写实际视频目录路径。") from error
            raise
        if not root.is_dir():
            raise ReviewError(HTTPStatus.BAD_REQUEST, "请选择视频目录。")
        paths = {}
        files = []
        with open_directory(root) as root_fd:
            for directory, subdirectories, names, fd in os.fwalk(".", dir_fd=root_fd, follow_symlinks=False):
                subdirectories.sort()
                for name in sorted(names):
                    path = root / directory / name
                    if path.suffix.lower() not in VIDEO_EXTENSIONS:
                        continue
                    try:
                        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    if not stat.S_ISREG(info.st_mode):
                        continue
                    if len(paths) >= MAX_VIDEO_ENTRIES:
                        raise ReviewError(HTTPStatus.BAD_REQUEST, "目录中的视频太多，请缩小视频目录范围。")
                    file_id = secrets.token_hex(16)
                    paths[file_id] = path, file_identity(info)
                    files.append({"id": file_id, "name": name, "relative_path": path.relative_to(root).as_posix()})
        with self.source_lock:
            self.video_paths = paths
        return {"path": str(root), "files": files}

    def open_video(self, file_id: object) -> tuple[Path, BinaryIO]:
        with self.source_lock:
            entry = self.video_paths.get(file_id) if isinstance(file_id, str) else None
        if entry is None:
            raise ReviewError(HTTPStatus.NOT_FOUND, "视频已不在当前目录列表中，请重新读取视频目录。")
        path, identity = entry
        try:
            with open_directory(path.parent) as directory:
                file = open_regular(directory, path.name)
        except OSError as error:
            raise ReviewError(HTTPStatus.NOT_FOUND, "视频已移动或无法读取，请重新读取视频目录。") from error
        info = os.fstat(file.fileno())
        if file_identity(info) != identity:
            file.close()
            raise ReviewError(HTTPStatus.CONFLICT, "视频文件在读取目录后发生变化，请重新打开视频目录。")
        if not 0 < info.st_size <= MAX_VIDEO_BYTES:
            file.close()
            raise ReviewError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "仅支持不超过 2 GiB 的非空视频。")
        return path, file

    def select_video(self, video_id: str, file_id: object) -> int:
        _, file = self.open_video(file_id)
        with self.lock:
            self.clear_video()
            try:
                self.video = Video(video_id, file)
            except Exception:
                file.close()
                raise
            return self.video.frame_count

    def clear_video(self) -> None:
        if self.video:
            self.video.close()
            self.video = None

    def server_close(self) -> None:
        self.preview_stop.set()
        super().server_close()
        with self.preview_lock:
            pass
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

    def respond_headers(self, status: HTTPStatus, length: int, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
            "connect-src 'self'; img-src blob:; media-src blob:; frame-ancestors 'none'; base-uri 'none'",
        )
        self.end_headers()

    def respond(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.respond_headers(status, len(body), content_type)
        if body:
            self.wfile.write(body)

    def respond_json(self, status: HTTPStatus, content: dict) -> None:
        self.respond(status, json.dumps(content, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def read_json(self, max_size: int = 16384) -> dict:
        lengths = self.headers.get_all("Content-Length") or []
        if (
            self.headers.get_content_type() != "application/json"
            or self.headers.get("Transfer-Encoding")
            or len(lengths) != 1
            or not re.fullmatch(r"[0-9]{1,10}", lengths[0])
        ):
            raise ReviewError(HTTPStatus.BAD_REQUEST, "请求格式无效。")
        size = int(lengths[0])
        if size > max_size:
            raise ReviewError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "请求内容超出大小限制。")
        try:
            data = json.loads(self.rfile.read(size).decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError) as error:
            raise ReviewError(HTTPStatus.BAD_REQUEST, "请求不是有效的 JSON。") from error
        if not isinstance(data, dict):
            raise ReviewError(HTTPStatus.BAD_REQUEST, "请求格式无效。")
        return data

    def send_video(self, file: BinaryIO, content_type: str) -> None:
        length = os.fstat(file.fileno()).st_size
        self.respond_headers(HTTPStatus.OK, length, content_type)
        while chunk := file.read(min(length, 1024**2)):
            self.wfile.write(chunk)
            length -= len(chunk)

    def build_preview(self, source: BinaryIO, output: Path) -> None:
        fd = source.fileno()
        before = file_identity(os.fstat(fd))
        command = [
            "ffmpeg", "-v", "error", "-nostdin", "-xerror", "-filter_threads", "1",
            "-protocol_whitelist", "fd", "-format_whitelist", FORMAT_WHITELIST,
            "-max_pixels", str(MAX_PIXELS), "-err_detect", "explode", "-threads", "2",
            "-fd", str(fd), "-i", "fd:", "-map", "0:V:0", "-map", "0:a:0?",
            "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-pix_fmt", "yuv420p",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-threads:v", "2",
            "-fps_mode", "passthrough", "-enc_time_base:v", "demux",
            "-c:a", "aac", "-fs", str(MAX_PREVIEW_BYTES),
            "-movflags", "+faststart", str(output),
        ]
        deadline = time.monotonic() + PREVIEW_TIMEOUT
        with selectors.DefaultSelector() as selector, subprocess.Popen(
            command, pass_fds=(fd,), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ) as process:
            try:
                selector.register(self.connection, selectors.EVENT_READ)
                while process.poll() is None:
                    if self.server.preview_stop.is_set() or selector.select(timeout=0.2):
                        # A GET has no request body. Socket readability here means the browser
                        # disconnected or sent unexpected bytes before receiving a response.
                        raise ConnectionResetError
                    if time.monotonic() >= deadline:
                        raise ReviewError(HTTPStatus.GATEWAY_TIMEOUT, "兼容视频准备超时，可继续使用原视频逐帧查看。")
            finally:
                if process.poll() is None:
                    process.kill()
            if process.returncode or not output.is_file() or output.stat().st_size == 0:
                raise ReviewError(HTTPStatus.UNPROCESSABLE_ENTITY, "无法生成兼容视频，请检查本机 FFmpeg 的 libx264 支持或视频文件。")
        if output.stat().st_size >= MAX_PREVIEW_BYTES:
            raise ReviewError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "兼容视频超出预览大小限制，可继续使用原视频逐帧查看。")
        if file_identity(os.fstat(fd)) != before:
            raise ReviewError(HTTPStatus.CONFLICT, "视频文件在生成预览时发生变化，请重新打开视频目录。")

    def serve_preview(self, file_id: str) -> None:
        if not self.server.preview_lock.acquire(timeout=1):
            raise ReviewError(HTTPStatus.SERVICE_UNAVAILABLE, "另一个视频正在准备兼容播放，请稍候重试。")
        try:
            if self.server.preview_stop.is_set():
                raise ConnectionResetError
            _, source = self.server.open_video(file_id)
            with source, tempfile.TemporaryDirectory(prefix="annotation-preview-") as directory:
                output = Path(directory) / "preview.mp4"
                self.build_preview(source, output)
                with output.open("rb") as preview:
                    self.send_video(preview, "video/mp4")
        finally:
            self.server.preview_lock.release()

    def serve_source(self) -> bool:
        if self.command == "GET" and self.path == "/api/default-sources":
            self.respond_json(HTTPStatus.OK, {"csv_path": DEFAULT_CSV, "video_directory": DEFAULT_VIDEOS})
            return True
        if self.command == "POST" and self.path in {"/api/csv/read", "/api/csv/write", "/api/video/library"}:
            data = self.read_json(6 * MAX_CSV_BYTES + 16384) if self.path == "/api/csv/write" else self.read_json()
            path = data.get("path")
            if self.path == "/api/csv/read":
                result = self.server.read_csv(path)
            elif self.path == "/api/csv/write":
                result = self.server.write_csv(path, data.get("expected_sha256"), data.get("csv"))
            else:
                result = self.server.video_library(path)
            self.respond_json(HTTPStatus.OK, result)
            return True
        match = VIDEO_FILE_ROUTE.fullmatch(self.path)
        if self.command == "GET" and match:
            path, file = self.server.open_video(match[1])
            with file:
                self.send_video(file, mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            return True
        match = VIDEO_PREVIEW_ROUTE.fullmatch(self.path)
        if self.command == "GET" and match:
            self.serve_preview(match[1])
            return True
        return False

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
                raise ReviewError(HTTPStatus.FORBIDDEN, "本机服务只接受当前标注页面的请求。")
            if self.serve_source():
                return
            match = VIDEO_ROUTE.fullmatch(self.path)
            if not match:
                raise ReviewError(HTTPStatus.NOT_FOUND, "请求路径无效。")
            video_id, index = match.groups()
            if self.command == "POST" and index is None:
                if self.headers.get_content_type() == "application/json":
                    count = self.server.select_video(video_id, self.read_json().get("file_id"))
                    self.respond_json(HTTPStatus.OK, {"frame_count": count})
                else:
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
            self.respond_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "本机服务读写失败，请检查路径、权限或可用空间。"})

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
    for warning in default_source_warnings(PROJECT_ROOT):
        print(warning, flush=True)
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
