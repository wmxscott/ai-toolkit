"""Drives scripts/gh-app-identity.sh and the `git app` alias it adds in scratch repositories,
with a stub gh on PATH and a git config built from scratch, so no real extension, keyring or
$HOME is ever reached."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent / "skills" / "gh-app-auth"
SKILL = (SKILL_DIR / "SKILL.md").read_text()
SCRIPT = SKILL_DIR / "scripts" / "gh-app-identity.sh"
GIT = shutil.which("git") or "/usr/bin/git"
JQ = shutil.which("jq")
TARGET = "github.com/acme/widget"
BOT = "acme-agent[bot]"
BOT_EMAIL = f"4242+{BOT}@users.noreply.github.com"
COAUTHOR = "Co-authored-by: Ada Lovelace <ada@example.com>"

STUB = r"""#!/bin/bash
printf '%s\n' "$*" >> "$STUB_DIR/calls"
case "$1 $2" in
"app-auth --help") ;;
"app-auth exec")
	[[ -z $STUB_EXEC_ERROR ]] || { printf '%s\n' "$STUB_EXEC_ERROR" >&2; exit 1; }
	printf '%s\n' "$STUB_IDENTITY" ;;
"app-auth list") printf '%s\n' "$STUB_LIST" ;;
"app-auth setup")
	printf '%s' "$GH_APP_PRIVATE_KEY" > "$STUB_DIR/key"
	printf '%s\n' "${@:3}" > "$STUB_DIR/setup" ;;
"app-auth test") printf 'All tests passed\n' ;;
"app-auth git-credential")
	cat > /dev/null
	[[ $3 != get ]] || printf 'username=x-access-token\npassword=app-token\n' ;;
*) exit 64 ;;
esac
"""


class Sandbox:
    def __init__(self, root: Path, remote: str = f"https://{TARGET}.git"):
        self.root = root
        self.home = root / "home"
        self.bin = root / "bin"
        self.repo = root / "repo"
        for directory in (self.home, self.bin, self.repo):
            directory.mkdir()
        (self.bin / "gh").write_text(STUB)
        (self.bin / "gh").chmod(0o755)
        tools = [str(self.bin), str(Path(GIT).parent)]
        if JQ:
            tools.append(str(Path(JQ).parent))
        self.env = {
            "HOME": str(self.home),
            "PATH": ":".join([*tools, "/usr/bin", "/bin"]),
            "GIT_CONFIG_GLOBAL": str(self.home / ".gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "STUB_DIR": str(root),
            "STUB_IDENTITY": f"{BOT} 4242",
            "STUB_EXEC_ERROR": "",
            "STUB_LIST": "[]",
        }
        for key, value in {
            "user.name": "Ada Lovelace",
            "user.email": "ada@example.com",
            "commit.gpgsign": "true",
            "gpg.program": "false",
            "credential.helper": "store",
            "init.defaultBranch": "main",
        }.items():
            self.git("config", "--global", key, value)
        (self.home / ".git-credentials").write_text(f"https://ada:personal-token@{TARGET}.git\n")
        self.git("init", "-q")
        self.git("remote", "add", "origin", remote)

    def git(self, *args: str, check: bool = True) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.repo, env=self.env, capture_output=True, text=True, check=check
        ).stdout.strip()

    def config(self, key: str) -> str:
        return self.git("config", "--get", key, check=False)

    def run(self, *args: str, cwd: Path | None = None, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo,
            env={**self.env, "GIT_TERMINAL_PROMPT": "0"},
            capture_output=True,
            text=True,
            **kwargs,
        )

    def script(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["/bin/bash", str(SCRIPT), *args],
            cwd=self.repo,
            env={**self.env, **env},
            capture_output=True,
            text=True,
        )

    def calls(self) -> list[str]:
        calls = self.root / "calls"
        return calls.read_text().splitlines() if calls.exists() else []

    def password(self, *git: str) -> str:
        filled = self.run(*git, "credential", "fill", input=f"url=https://{TARGET}.git\n\n")
        assert filled.returncode == 0, filled.stderr
        return re.search(r"^password=(.*)$", filled.stdout, re.M)[1]

    def local_keys(self) -> set[str]:
        listed = self.git("config", "--local", "--name-only", "--list").splitlines()
        return {key for key in listed if not key.startswith(("core.", "remote."))}


@pytest.fixture
def box(tmp_path):
    return Sandbox(tmp_path)


def set_up(box: Sandbox, *args: str) -> subprocess.CompletedProcess:
    result = box.script("setup", *args)
    assert result.returncode == 0, result.stderr
    return result


def test_frontmatter_is_portable():
    frontmatter = re.match(r"---\n(.*?)\n---\n", SKILL, re.S)
    assert frontmatter
    fields = dict(line.split(": ", 1) for line in frontmatter[1].splitlines())
    assert fields.keys() == {"name", "description"}
    assert fields["name"] == SKILL_DIR.name
    assert fields["description"].startswith("Use ")
    assert len(fields["description"]) <= 1024
    assert ": " not in fields["description"]


def test_skill_runs_only_subcommands_the_script_has():
    used = set(re.findall(r"<scripts>/gh-app-identity\.sh (\w+)", SKILL))
    assert used == {"setup", "off", "status", "rekey"}


@pytest.mark.parametrize(
    "remote",
    [
        f"https://{TARGET}.git",
        f"https://someone@{TARGET}",
        "git@github.com:acme/widget.git",
        "ssh://git@github.com:22/acme/widget.git",
    ],
)
def test_setup_reads_the_repository_from_any_remote_form(tmp_path, remote):
    box = Sandbox(tmp_path, remote)
    set_up(box)
    assert f"app-auth exec --repo {TARGET} -- gh api graphql" in "\n".join(box.calls())
    assert box.config("gh-app-auth.repo") == TARGET


def test_setup_adds_only_the_alias_and_the_identity(box):
    set_up(box)
    assert box.local_keys() == {
        "alias.app",
        "gh-app-auth.login",
        "gh-app-auth.userid",
        "gh-app-auth.coauthor",
        "gh-app-auth.repo",
    }
    assert box.config("gh-app-auth.login") == BOT
    assert box.config("gh-app-auth.userid") == "4242"
    assert box.config("gh-app-auth.coauthor") == "Ada Lovelace <ada@example.com>"


def test_setup_leaves_global_config_alone(box):
    before = (box.home / ".gitconfig").read_text()
    set_up(box)
    assert (box.home / ".gitconfig").read_text() == before


def test_plain_git_is_still_the_user(box):
    set_up(box)
    assert box.git("var", "GIT_AUTHOR_IDENT").startswith("Ada Lovelace <ada@example.com>")
    assert box.password() == "personal-token"
    (box.repo / "notes.txt").write_text("mine\n")
    box.git("add", "notes.txt")
    signed = box.run("commit", "-m", "Mine")
    assert signed.returncode != 0
    assert "gpg" in signed.stderr


def test_git_app_logs_in_with_gh_app_auth_only(box):
    set_up(box)
    assert box.password("app") == "app-token"


def test_git_app_commits_as_the_bot_from_a_subdirectory(box):
    set_up(box)
    sub = box.repo / "src"
    sub.mkdir()
    (sub / "login.txt").write_text("fixed\n")
    for args in (["add", "login.txt"], ["commit", "-m", "Fix login bug"]):
        result = box.run("app", *args, cwd=sub)
        assert result.returncode == 0, result.stderr
    assert box.git("log", "-1", "--format=%an <%ae>|%cn|%G?") == f"{BOT} <{BOT_EMAIL}>|{BOT}|N"
    assert box.git("log", "-1", "--format=%B") == f"Fix login bug\n\n{COAUTHOR}"


def test_git_app_credits_the_coauthor_once(box):
    set_up(box)
    (box.repo / "a.txt").write_text("a\n")
    box.git("add", "a.txt")
    message = f"Add a\n\n{COAUTHOR}"
    for args in (["commit", "-m", message], ["commit", "--amend", "--no-edit"]):
        result = box.run("app", *args)
        assert result.returncode == 0, result.stderr
    assert box.git("log", "-1", "--format=%B") == message


@pytest.mark.parametrize(
    ("url", "pushurl"),
    [
        ("git@github.com:acme/widget.git", None),
        (f"https://{TARGET}.git", "git@github.com:acme/widget.git"),
        (f"https://{TARGET}.git", "ssh://git@github.com/acme/widget.git"),
    ],
)
def test_git_app_pushes_over_https(tmp_path, url, pushurl):
    box = Sandbox(tmp_path, url)
    if pushurl:
        box.git("remote", "set-url", "--push", "origin", pushurl)
    set_up(box)
    pushed = box.run("app", "remote", "get-url", "--push", "origin")
    assert pushed.stdout.strip() == f"https://{TARGET}.git"
    assert box.git("remote", "get-url", "--push", "origin") == (pushurl or url)


def test_git_app_refuses_without_the_identity(box):
    set_up(box)
    box.git("config", "--local", "--remove-section", "gh-app-auth")
    result = box.run("app", "commit", "--allow-empty", "-m", "x")
    assert result.returncode != 0
    assert "not set up" in result.stderr
    assert box.git("rev-list", "--all") == ""


def test_setup_takes_an_explicit_coauthor(box):
    set_up(box, "--coauthor", "Grace Hopper <grace@example.com>")
    assert box.config("gh-app-auth.coauthor") == "Grace Hopper <grace@example.com>"


def test_rerunning_setup_keeps_the_coauthor(box):
    set_up(box, "--coauthor", "Grace Hopper <grace@example.com>")
    set_up(box)
    assert box.config("gh-app-auth.coauthor") == "Grace Hopper <grace@example.com>"
    assert len(box.git("config", "--local", "--get-all", "alias.app").splitlines()) == 1


def test_setup_rejects_a_malformed_coauthor(box):
    result = box.script("setup", "--coauthor", "ada@example.com")
    assert result.returncode == 1
    assert "Name <email>" in result.stderr
    assert box.local_keys() == set()


def test_setup_refuses_a_credential_that_is_not_an_app(box):
    result = box.script("setup", STUB_IDENTITY="ada 1")
    assert result.returncode == 1
    assert "not as a GitHub App" in result.stderr
    assert box.local_keys() == set()


def test_setup_points_at_the_extension_when_no_app_works(box):
    result = box.script("setup", STUB_EXEC_ERROR="no GitHub App configured")
    assert result.returncode == 1
    assert f"gh app-auth test --repo {TARGET}" in result.stderr


def test_status_without_setup(box):
    result = box.script("status")
    assert result.returncode == 2
    assert "Not set up" in result.stdout


def test_status_mints_a_token_and_passes(box):
    set_up(box)
    result = box.script("status")
    assert result.returncode == 0, result.stdout
    assert f"OK: {BOT}" in result.stdout
    assert box.calls()[-1].startswith(f"app-auth exec --repo {TARGET} --")


@pytest.mark.parametrize(
    ("change", "env", "problem"),
    [
        (("alias.app", "!git"), {}, "alias is missing or changed"),
        (("gh-app-auth.repo", "github.com/acme/other"), {}, "gh-app-auth.repo is not"),
        (None, {"GIT_AUTHOR_NAME": "Ada"}, "GIT_AUTHOR_NAME is set"),
        (None, {"STUB_EXEC_ERROR": "failed to generate JWT"}, "failed to generate JWT"),
        (None, {"STUB_IDENTITY": "other[bot] 7"}, "acts as 'other[bot]'"),
    ],
)
def test_status_reports_problems(box, change, env, problem):
    set_up(box)
    if change:
        box.git("config", "--local", *change)
    result = box.script("status", **env)
    assert result.returncode == 1
    assert problem in result.stdout


def test_status_warns_about_an_exported_token(box):
    set_up(box)
    result = box.script("status", GH_TOKEN="ghs_old")
    assert result.returncode == 0
    assert "GH_TOKEN is exported" in result.stdout


APPS = [
    {"name": "Everything", "app_id": 1, "patterns": ["github.com/*"], "priority": 1},
    {"name": "Acme", "client_id": "Iv1.acme", "patterns": ["github.com/acme/*"], "priority": 5},
    {"name": "Other", "app_id": 3, "patterns": ["github.com/other/*"], "priority": 9},
]


@pytest.mark.skipif(not JQ, reason="rekey needs jq")
@pytest.mark.parametrize("listing", [[APPS, None], {"github_apps": APPS, "pats": []}])
def test_rekey_stores_the_key_for_the_app_that_serves_the_repository(box, listing):
    pem = box.root / "new.pem"
    pem.write_text("-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----\n")
    result = box.script("rekey", str(pem), STUB_LIST=json.dumps(listing))
    assert result.returncode == 0, result.stderr
    assert (box.root / "setup").read_text().split("\n")[:-1] == [
        "--client-id",
        "Iv1.acme",
        "--patterns",
        "github.com/acme/*",
        "--name",
        "Acme",
        "--priority",
        "5",
    ]
    assert (box.root / "key").read_text() == pem.read_text().rstrip("\n")
    assert box.calls()[-1] == f"app-auth test --repo {TARGET}"


@pytest.mark.skipif(not JQ, reason="rekey needs jq")
def test_rekey_refuses_a_file_that_is_not_a_key(box):
    note = box.root / "note.txt"
    note.write_text("hello\n")
    result = box.script("rekey", str(note), STUB_LIST=json.dumps([APPS, None]))
    assert result.returncode == 1
    assert not (box.root / "setup").exists()


def test_off_removes_the_alias_and_the_identity(box):
    set_up(box)
    result = box.script("off")
    assert result.returncode == 0, result.stderr
    assert box.local_keys() == set()
    assert box.run("app", "status").returncode != 0
