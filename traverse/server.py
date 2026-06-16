"""Stdlib HTTP server for the Traverse API."""

from __future__ import annotations

import json
import logging
import mimetypes
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from traverse.cache import SummaryCache
from traverse.config import TraverseConfig, load_config
from traverse.graph_service import GraphService, list_directory
from traverse.llm_factory import create_llm_client, llm_available
from traverse.llm_service import FlowSummaryService
from traverse.serialize import graph_to_response

logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if not FRONTEND_DIST.is_dir() and Path("/app/frontend/dist").is_dir():
    FRONTEND_DIST = Path("/app/frontend/dist")



class TraverseHandler(BaseHTTPRequestHandler):
    config: TraverseConfig
    graph_service: GraphService
    summary_service: FlowSummaryService | None

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        logger.info("%s - %s", self.address_string(), format % args)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json(status, {"error": message})

    def _send_cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/health":
            self._handle_health()
            return
        if path == "/api/files":
            params = parse_qs(parsed.query)
            dir_arg = params.get("dir", [""])[0]
            self._handle_files(dir_arg)
            return
        if path.startswith("/api/"):
            self._send_error_json(HTTPStatus.NOT_FOUND, "not found")
            return
        self._serve_static(path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, json.JSONDecodeError):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid JSON body")
            return

        if path == "/api/graph":
            self._handle_graph(body)
            return
        if path == "/api/flow/summary":
            self._handle_summary(body)
            return
        self._send_error_json(HTTPStatus.NOT_FOUND, "not found")

    def _handle_health(self) -> None:
        self._send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "project_root": str(self.config.project_root),
                "llm": self.config.llm_label if llm_available(self.config) else None,
            },
        )

    def _handle_files(self, relative_dir: str) -> None:
        try:
            payload = list_directory(self.config.project_root, relative_dir)
            self._send_json(HTTPStatus.OK, payload)
        except FileNotFoundError as exc:
            self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

    def _handle_graph(self, body: dict) -> None:
        file_arg = body.get("file")
        if not file_arg or not isinstance(file_arg, str):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "file is required")
            return
        try:
            scoped = self.graph_service.build_for_file(file_arg)
            rel_root = "."
            try:
                rel_root = str(scoped.collection_root.relative_to(self.config.project_root))
            except ValueError:
                rel_root = str(scoped.collection_root)
            payload = graph_to_response(
                scoped.graph,
                scope_file=scoped.scope_file,
                collection_root=rel_root,
            )
            self._send_json(HTTPStatus.OK, payload)
        except FileNotFoundError as exc:
            self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            logger.exception("graph build failed")
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _handle_summary(self, body: dict) -> None:
        scope_file = body.get("scope_file")
        start_node_id = body.get("start_node_id")
        if not scope_file or not start_node_id:
            self._send_error_json(
                HTTPStatus.BAD_REQUEST, "scope_file and start_node_id are required"
            )
            return
        if self.summary_service is None:
            self._send_error_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "LLM not configured. Set LLAMACPP_URL.",
            )
            return
        scoped = self.graph_service.get_cached(scope_file)
        if scoped is None:
            try:
                scoped = self.graph_service.build_for_file(scope_file)
            except Exception as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
        bypass = bool(body.get("regenerate"))
        try:
            result = self.summary_service.summarize(scoped, start_node_id, bypass_cache=bypass)
            self._send_json(HTTPStatus.OK, result)
        except KeyError as exc:
            self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
        except RuntimeError as exc:
            self._send_error_json(HTTPStatus.BAD_GATEWAY, str(exc))
        except Exception as exc:
            logger.exception("summary failed")
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _serve_static(self, path: str) -> None:
        if not FRONTEND_DIST.is_dir():
            self._send_error_json(
                HTTPStatus.NOT_FOUND,
                "frontend not built; run npm run build in frontend/",
            )
            return
        rel = path.lstrip("/") or "index.html"
        file_path = (FRONTEND_DIST / rel).resolve()
        if not str(file_path).startswith(str(FRONTEND_DIST.resolve())):
            self._send_error_json(HTTPStatus.FORBIDDEN, "forbidden")
            return
        if file_path.is_dir():
            file_path = file_path / "index.html"
        if not file_path.exists():
            file_path = FRONTEND_DIST / "index.html"
        mime, _ = mimetypes.guess_type(str(file_path))
        content = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def make_handler_class(
    config: TraverseConfig,
    graph_service: GraphService,
    summary_service: FlowSummaryService | None,
) -> type[TraverseHandler]:
    class Handler(TraverseHandler):
        pass

    Handler.config = config
    Handler.graph_service = graph_service
    Handler.summary_service = summary_service
    return Handler


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = load_config()
    graph_service = GraphService(config.project_root)
    cache = SummaryCache(config.cache_dir)

    llm = None
    summary_service: FlowSummaryService | None = None
    try:
        llm = create_llm_client(config)
        summary_service = FlowSummaryService(config, cache, llm)
        logger.info("LLM configured: %s", config.llm_label)
    except RuntimeError as exc:
        logger.warning("%s — summaries will be unavailable", exc)

    handler = make_handler_class(config, graph_service, summary_service)
    server = ThreadingHTTPServer((config.host, config.port), handler)
    logger.info(
        "Traverse server at http://%s:%s (project: %s)",
        config.host,
        config.port,
        config.project_root,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down")
        server.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    main()
