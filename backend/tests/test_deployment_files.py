"""Checks on the deployment files. Docker itself is not run here; these tests catch the
mistakes that can be caught by reading the files (and they run in CI)."""
import ast
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

from app.config import Settings

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

SECRET_SHAPES = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
SKIP_DIRS = {"node_modules", ".venv", "__pycache__", ".pytest_cache", "dist", ".git", "data"}


def text_files():
    for path in ROOT.rglob("*"):
        if path.is_file() and not (set(path.relative_to(ROOT).parts) & SKIP_DIRS):
            if path.suffix in {".py", ".md", ".yml", ".yaml", ".json", ".ts", ".tsx", ".conf", ".txt", ".example", ".html", ""} \
                    and path.stat().st_size < 600_000 and path.name != "package-lock.json":
                yield path


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_env_example() -> dict[str, str]:
    values = {}
    for line in read(ROOT / ".env.example").splitlines():
        m = re.match(r"^\s*#?\s*(GRAPHGUARD_[A-Z_]+)=(.*)$", line)
        if m:
            values[m.group(1)] = re.split(r"\s+#", m.group(2))[0].strip()
    return values


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(read(ROOT / "docker-compose.yml"))


# ---------- secrets ----------

def test_no_secret_shaped_strings_in_repo():
    hits = []
    for path in text_files():
        if path.name == "test_deployment_files.py":
            continue
        body = read(path) if path.suffix != ".png" else ""
        for pattern in SECRET_SHAPES:
            if pattern.search(body):
                hits.append(f"{path.relative_to(ROOT)} matches {pattern.pattern}")
    assert not hits, hits


def test_env_files_are_git_ignored():
    ignored = read(ROOT / ".gitignore").splitlines()
    for entry in (".env", ".env.local", "data/"):
        assert entry in ignored, f"{entry} must be in .gitignore"


def test_no_real_env_file_committed():
    assert not (ROOT / ".env.example").read_text().count("sk-")


def test_compose_has_no_literal_secrets(compose):
    for name, svc in compose["services"].items():
        for key, value in (svc.get("environment") or {}).items():
            if "KEY" in key or "SECRET" in key or "TOKEN" in key:
                assert str(value).startswith("${"), f"{name}.{key} must come from the environment, not be written here"


# ---------- .env.example matches the real settings ----------

def test_every_example_variable_is_a_real_setting():
    fields = {f.upper() for f in Settings.model_fields}
    for var in parse_env_example():
        assert var.removeprefix("GRAPHGUARD_") in fields, f"{var} is not a setting"


def test_every_setting_is_documented():
    documented = {v.removeprefix("GRAPHGUARD_").lower() for v in parse_env_example()}
    # Fixed metadata, not meant to be configured
    internal = {"app_name", "version"}
    missing = set(Settings.model_fields) - documented - internal
    assert not missing, f"undocumented settings: {sorted(missing)}"


def test_example_file_is_a_valid_config(tmp_path, monkeypatch):
    for key in list(parse_env_example()):
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=ROOT / ".env.example")
    s.validate_for_environment()
    assert s.llm_provider == "none"
    assert s.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]
    assert s.llm_api_key is None


# ---------- compose ----------

def test_compose_ports_are_local_only(compose):
    for name, svc in compose["services"].items():
        for port in svc.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port} to the whole network"


def test_cors_origin_matches_frontend_port(compose):
    be = compose["services"]["backend"]
    fe_port = compose["services"]["frontend"]["ports"][0].split(":")[1]
    assert f"http://localhost:{fe_port}" in json.loads(be["environment"]["GRAPHGUARD_CORS_ORIGINS"])
    assert f"http://localhost:{fe_port}" in json.loads(be["environment"]["GRAPHGUARD_WS_ALLOWED_ORIGINS"])


def test_api_url_is_reachable_from_a_browser(compose):
    url = compose["services"]["frontend"]["build"]["args"]["VITE_API_URL"]
    assert "backend" not in url, "a Compose service name only works inside Docker, not in the browser"
    be_port = compose["services"]["backend"]["ports"][0].split(":")[1]
    assert url == f"http://localhost:{be_port}"


def test_containers_drop_privileges(compose):
    for name, svc in compose["services"].items():
        assert "no-new-privileges:true" in svc.get("security_opt", []), name
        assert "ALL" in svc.get("cap_drop", []), name


def test_frontend_waits_for_healthy_backend(compose):
    assert compose["services"]["frontend"]["depends_on"]["backend"]["condition"] == "service_healthy"
    assert "healthcheck" in compose["services"]["backend"]


def test_database_is_on_a_volume(compose):
    assert any(v.endswith(":/data") for v in compose["services"]["backend"]["volumes"])
    assert "graphguard-data" in compose["volumes"]


# ---------- Dockerfiles ----------

def test_backend_dockerfile_basics():
    d = read(BACKEND / "Dockerfile")
    assert re.search(r"^USER\s+app", d, re.M), "must not run as root"
    assert "--workers\", \"1\"" in d, "state is in memory: exactly one worker"
    assert "HEALTHCHECK" in d and "/api/ready" in d
    assert d.index("COPY requirements.txt") < d.index("COPY app"), "install dependencies before copying code (layer cache)"
    assert "GRAPHGUARD_ENVIRONMENT=production" in d
    assert not re.search(r"^(ENV|ARG)\s+\S*(KEY|SECRET|TOKEN)", d, re.M | re.I)


def test_frontend_dockerfile_basics():
    d = read(FRONTEND / "Dockerfile")
    assert d.count("FROM ") == 2, "multi-stage: build tools must not ship in the final image"
    assert "nginx-unprivileged" in d
    assert d.index("COPY package.json") < d.index("COPY . ."), "install packages before copying source"


def test_dockerignore_keeps_junk_and_secrets_out():
    for d, must in ((BACKEND, {".venv", ".env"}), (FRONTEND, {"node_modules", ".env"})):
        lines = set(read(d / ".dockerignore").split())
        assert must <= lines, (d.name, must - lines)


# ---------- nginx ----------

def test_nginx_csp_allows_exactly_the_api(compose):
    conf = read(FRONTEND / "nginx.conf")
    api = compose["services"]["frontend"]["build"]["args"]["VITE_API_URL"]
    ws = api.replace("http://", "ws://")
    csp = re.search(r'Content-Security-Policy "([^"]+)"', conf).group(1)
    assert f"connect-src 'self' {api} {ws}" in csp
    assert "unsafe-eval" not in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp


def test_nginx_locations_do_not_reset_headers():
    """In nginx, an add_header inside a location silently removes all the server-level ones."""
    conf = read(FRONTEND / "nginx.conf")
    for block in re.findall(r"location[^{]*\{([^}]*)\}", conf):
        assert "add_header" not in block


def test_nginx_has_spa_fallback():
    assert "try_files $uri /index.html" in read(FRONTEND / "nginx.conf")


# ---------- dependencies ----------

def test_every_third_party_import_is_declared():
    declared = {re.split(r"[<>=\[ ]", l)[0].lower().replace("-", "_") for l in read(BACKEND / "requirements.txt").splitlines() if l.strip()}
    stdlib = set(sys.stdlib_module_names)
    local = {"app", "tests"}
    imported = set()
    for path in (BACKEND / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(read(path))):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
    third_party = imported - stdlib - local
    # starlette and pydantic come with fastapi; uvicorn is the server
    provided = {"starlette": "fastapi", "pydantic": "fastapi", "pydantic_settings": "pydantic_settings"}
    for mod in third_party:
        assert mod.lower() in declared or provided.get(mod) in declared, f"{mod} is imported but not in requirements.txt"


def test_ci_runs_both_suites():
    path = ROOT / ".github" / "workflows" / "ci.yml"
    if not path.exists():
        pytest.skip("ci.yml not created yet (optional until the repo is on GitHub)")
    ci = yaml.safe_load(read(path))
    steps = json.dumps(ci)
    for needle in ("pytest", "npm run lint", "vitest", "npm run build"):
        assert needle in steps
