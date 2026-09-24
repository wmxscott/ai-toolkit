"""Runs the commands exactly as SKILL.md gives them, with git config in a scratch repository
and a stub gpg on PATH."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
SKILL = (PLUGIN / "skills" / "security-key-git-signing" / "SKILL.md").read_text()
GIT = shutil.which("git") or "/usr/bin/git"
COMMIT_SIGN, TAG_SIGN, FORMAT, ON_CARD, CARD_PRESENT = re.findall(
    r"^```bash\n(.+?)\n```$", SKILL, re.M | re.S
)

KEY_LISTING = """[keyboxd]
---------
sec{sec}  ed25519 2024-01-01 [SC]
      0123456789ABCDEF0123456789ABCDEF01234567
uid           [ultimate] Test User <test@example.invalid>
ssb{ssb}  cv25519 2024-01-01 [E]

"""

STUB_GPG = """#!/bin/bash
printf '%s\\n' "$*" >> "$GPG_LOG"
case "$1" in
    --list-secret-keys) cat "$GPG_LISTING" ;;
    --card-status) echo "Signature key ....: 0123 4567"; exit "$CARD_STATUS" ;;
esac
"""


def test_frontmatter_names_the_skill():
    frontmatter = re.match(r"---\n(.*?)\n---\n", SKILL, re.S)
    assert frontmatter
    fields = dict(line.split(": ", 1) for line in frontmatter[1].splitlines())
    assert fields.keys() == {"name", "description"}
    assert fields["name"] == "security-key-git-signing"
    assert fields["description"].startswith("Use when")


def test_procedure_commands():
    assert (COMMIT_SIGN, TAG_SIGN, FORMAT, ON_CARD, CARD_PRESENT) == (
        "git config --bool --get commit.gpgsign",
        "git config --bool --get tag.gpgsign",
        "git config --get gpg.format",
        "gpg --list-secret-keys $(git config --get user.signingkey) 2>/dev/null"
        " | grep -qE '^(sec|ssb)>'",
        "gpg --card-status >/dev/null 2>&1",
    )


def test_never_turns_signing_off():
    assert SKILL.count("--no-gpg-sign") == 1
    assert "Never add `--no-gpg-sign`" in SKILL


class Sandbox:
    def __init__(self, root: Path):
        home = root / "home"
        home.mkdir()
        (home / ".gitconfig").touch()
        bin_dir = root / "bin"
        bin_dir.mkdir()
        gpg = bin_dir / "gpg"
        gpg.write_text(STUB_GPG)
        gpg.chmod(0o755)
        self.log = root / "gpg.log"
        self.listing = root / "listing"
        self.repo = root / "repo"
        self.env = {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{Path(GIT).parent}:/usr/bin:/bin",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GPG_LOG": str(self.log),
            "GPG_LISTING": str(self.listing),
            "CARD_STATUS": "0",
        }
        self.cards("", "")
        subprocess.run(["git", "init", "-q", str(self.repo)], env=self.env, check=True)

    def config(self, key: str, value: str) -> None:
        subprocess.run(["git", "config", key, value], cwd=self.repo, env=self.env, check=True)

    def cards(self, sec: str, ssb: str) -> None:
        self.listing.write_text(KEY_LISTING.format(sec=sec.ljust(1), ssb=ssb.ljust(1)))

    def run(self, command: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", "-c", command], cwd=self.repo, env=self.env, capture_output=True, text=True
        )

    def gpg_calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []


@pytest.fixture
def sandbox(tmp_path):
    return Sandbox(tmp_path)


@pytest.mark.parametrize("command", [COMMIT_SIGN, TAG_SIGN])
def test_signing_off_by_default(sandbox, command):
    result = sandbox.run(command)
    assert (result.returncode, result.stdout) == (1, "")


@pytest.mark.parametrize("value", ["true", "yes", "on", "1"])
@pytest.mark.parametrize("key", ["commit.gpgsign", "tag.gpgsign"])
def test_signing_on_prints_true_for_any_spelling(sandbox, key, value):
    sandbox.config(key, value)
    command = COMMIT_SIGN if key == "commit.gpgsign" else TAG_SIGN
    assert sandbox.run(command).stdout == "true\n"


def test_signing_explicitly_off(sandbox):
    sandbox.config("commit.gpgsign", "no")
    assert sandbox.run(COMMIT_SIGN).stdout == "false\n"


@pytest.mark.parametrize("value", [None, "openpgp", "ssh", "x509"])
def test_format(sandbox, value):
    if value:
        sandbox.config("gpg.format", value)
    assert sandbox.run(FORMAT).stdout.strip() == (value or "")


@pytest.mark.parametrize(
    ("sec", "ssb", "on_card"),
    [
        ("", "", False),
        ("#", "", False),
        ("", ">", True),
        (">", "", True),
        (">", ">", True),
    ],
)
def test_card_marker(sandbox, sec, ssb, on_card):
    sandbox.cards(sec, ssb)
    assert (sandbox.run(ON_CARD).returncode == 0) is on_card


def test_listing_is_limited_to_the_signing_key(sandbox):
    sandbox.config("user.signingkey", "test-signing-key")
    sandbox.run(ON_CARD)
    assert sandbox.gpg_calls() == ["--list-secret-keys test-signing-key"]


def test_listing_covers_every_key_without_a_signing_key(sandbox):
    sandbox.run(ON_CARD)
    assert sandbox.gpg_calls() == ["--list-secret-keys"]


@pytest.mark.parametrize(("status", "present"), [("0", True), ("2", False)])
def test_card_present(sandbox, status, present):
    sandbox.env["CARD_STATUS"] = status
    result = sandbox.run(CARD_PRESENT)
    assert (result.returncode == 0) is present
    assert result.stdout == ""


def test_pin_helper_is_optional():
    readme = (PLUGIN / "README.md").read_text()
    assert "[seckey-dialog](https://github.com/wmxscott/seckey-dialog) is another option" in SKILL
    assert "[seckey-dialog](https://github.com/wmxscott/seckey-dialog) is an optional" in readme
