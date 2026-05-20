import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "web" / "server.py"


def load_server_module():
    spec = importlib.util.spec_from_file_location("workbench_server", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_parse_json_from_cli_rejects_none_with_clear_error():
    server = load_server_module()
    try:
        server.parse_json_from_cli(None)
    except RuntimeError as exc:
        assert "没有返回 JSON" in str(exc)
    else:
        raise AssertionError("parse_json_from_cli(None) should raise RuntimeError")


def test_parse_json_from_cli_accepts_prefixed_json():
    server = load_server_module()
    assert server.parse_json_from_cli("notice\n{\"ok\": true}") == {"ok": True}
