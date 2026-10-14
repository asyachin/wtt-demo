from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_no_env_symlink():
    path = ROOT / "app/.env"
    assert not path.exists()
    assert not path.is_symlink()


def test_gitignore_blocks_env_files():
    assert git("check-ignore", "-q", "app/.env.dev").returncode == 0
    assert git("check-ignore", "-q", "app/.env.template").returncode == 1


def test_gitignore_blocks_build_output():
    assert git(
        "check-ignore", "-q", "app/worker/obj/project.assets.json"
    ).returncode == 0


def test_no_build_output_tracked():
    result = git("ls-files")
    assert result.returncode == 0
    for path in result.stdout.splitlines():
        parts = Path(path).parts
        assert not any(
            item in parts for item in ("obj", "bin", "node_modules")
        ), path


def test_infrastructure_code_is_not_ignored():
    paths = [
        "infra/terraform/env/platform/main.tf",
        "infra/terraform/env/platform/terraform.tfvars",
        "infra/terraform/env/platform/.terraform.lock.hcl",
        "deploy/helm/wtt-vote/values-prod.yaml",
    ]
    for path in paths:
        assert git("check-ignore", "-q", path).returncode == 1, path


def test_dockerignore_exists_per_build_context():
    paths = [
        "app/vote/.dockerignore",
        "app/result/.dockerignore",
        "app/worker/.dockerignore",
    ]
    for path in paths:
        assert (ROOT / path).is_file(), path


def test_service_dockerignores_are_allow_lists():
    for service in ("vote", "result", "worker"):
        path = ROOT / "app" / service / ".dockerignore"
        rules = [
            line.strip()
            for line in path.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        assert rules[0] == "*", path


def test_no_previous_project_references():
    result = git(
        "grep",
        "-inE",
        "ironhack|lilywalch|diogobarros|v2-lwinux|wtt-campusone[.]click",
        "--",
        ".",
    )
    assert result.returncode == 1, result.stdout


def test_env_template_is_parseable():
    path = ROOT / "app/.env.template"
    pattern = re.compile(r"^[A-Z][A-Z0-9_]*=.*$")
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        assert pattern.fullmatch(line), line.partition("=")[0]
        assert " #" not in line


def test_env_template_has_no_credentials():
    path = ROOT / "app/.env.template"
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key.endswith(("PASSWORD", "TOKEN")):
            assert not value, key
