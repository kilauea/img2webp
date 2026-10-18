"""Tests for the web GUI's conversion endpoint logic and HTTP server."""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from img2webp.webgui import Handler, _parse_dim, run_conversion


class TestParseDim:
    @pytest.mark.parametrize("value", [None, "", "0"])
    def test_blank_values_mean_none(self, value):
        assert _parse_dim(value) is None

    def test_positive_int(self):
        assert _parse_dim("1920") == 1920

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            _parse_dim("-5")


class TestRunConversion:
    def test_success(self, sample_tree, tmp_path):
        result = run_conversion(
            {
                "input": str(sample_tree),
                "output": str(tmp_path / "out"),
                "max_width": "1200",
                "lossless": True,
                "overwrite": True,
                "jobs": 2,
            }
        )
        assert result["ok"] is True
        assert result["succeeded"] == 2
        assert result["failed"] == 0

    def test_missing_path_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            run_conversion({"input": str(tmp_path / "nope")})

    def test_no_images_raises(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(ValueError):
            run_conversion({"input": str(empty)})

    def test_invalid_quality_raises(self, sample_tree):
        with pytest.raises(ValueError):
            run_conversion({"input": str(sample_tree), "lossless": False, "quality": 200})


class TestHttpServer:
    """End-to-end test against a real (ephemeral) server instance."""

    @pytest.fixture
    def server(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{srv.server_address[1]}"
        srv.shutdown()
        srv.server_close()

    def test_index_served(self, server):
        with urllib.request.urlopen(
            server + "/"
        ) as resp:  # nosec B310 - test hits a local 127.0.0.1 server
            assert resp.status == 200
            body = resp.read().decode()
        assert 'id="input"' in body
        assert 'id="max_width"' in body
        assert "/convert" in body

    def test_convert_endpoint(self, server, sample_tree, tmp_path):
        payload = json.dumps(
            {
                "input": str(sample_tree),
                "output": str(tmp_path / "out"),
                "lossless": True,
                "overwrite": True,
                "jobs": 2,
            }
        ).encode()
        req = urllib.request.Request(
            server + "/convert",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:  # nosec B310 - test hits a local 127.0.0.1 server
            data = json.loads(resp.read())
        assert data["ok"] is True
        assert data["succeeded"] == 2

    def test_convert_error_returns_json(self, server, tmp_path):
        payload = json.dumps({"input": str(tmp_path / "nope")}).encode()
        req = urllib.request.Request(
            server + "/convert",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:  # nosec B310 - test hits a local 127.0.0.1 server
            data = json.loads(resp.read())
        assert data["ok"] is False
        assert "does not exist" in data["error"]
