"""Config layers, their merge, schema validation, and data-file lookup."""

import pytest
from arbiter.config import (
    ConfigLoader,
    find_data,
    resolve_instruction,
    resolve_output_style,
    resolve_persona,
)
from arbiter.constants import BUILTIN_DIR, ENGINE_BUDGET
from arbiter.errors import ConfigError

SHELL = '[[task]]\nname = "{name}"\nrunner = "shell"\ncommand = "{command}"\n'


def load(root):
    return ConfigLoader(root).load()


def by_name(config):
    return {t.name: t for t in config.tasks}


def test_no_config_anywhere_is_empty(repo):
    assert ConfigLoader(repo).layer_paths() == []
    config = load(repo)
    assert not config
    assert config.tasks == []


def test_builtin_layer_never_applies_alone(repo):
    assert (BUILTIN_DIR / "defaults.toml").is_file()
    assert not load(repo)


def test_builtin_layer_joins_under_a_project_config(repo, write_config):
    write_config(SHELL.format(name="lint", command="true"))
    paths = ConfigLoader(repo).layer_paths()
    assert paths == [BUILTIN_DIR / "defaults.toml", repo / "arbiter.toml"]
    tasks = by_name(load(repo))
    assert list(tasks) == ["security", "scalability", "lint"]
    assert not tasks["security"].enabled
    assert not tasks["scalability"].enabled


def test_builtin_layer_joins_under_a_user_config(home, repo):
    home.user_defaults(SHELL.format(name="lint", command="true"))
    assert ConfigLoader(repo).layer_paths() == [
        BUILTIN_DIR / "defaults.toml",
        home.config / "defaults.toml",
    ]


def test_layer_order_and_field_level_merge(home, repo, write_config):
    home.user_defaults(
        SHELL.format(name="test", command="user-test") + "timeout = 30\nrequired = false\n"
    )
    write_config(SHELL.format(name="test", command="project-test") + 'paths = ["**/*.py"]\n')
    write_config('[[task]]\nname = "test"\ntimeout = 45\n', "arbiter.local.toml")
    task = by_name(load(repo))["test"]
    assert task.command == "project-test"
    assert task.timeout == 45
    assert task.required is False
    assert task.paths == ["**/*.py"]
    assert task.source == str(repo / "arbiter.local.toml")


def test_a_project_enables_a_builtin_task_by_name(repo, write_config):
    write_config('[[task]]\nname = "security"\nenabled = true\n')
    task = by_name(load(repo))["security"]
    assert task.enabled
    assert (task.runner, task.agent, task.effort) == ("codex", "security-reviewer", "high")


def test_a_later_layer_disables_a_task(home, repo, write_config):
    home.user_defaults(SHELL.format(name="lint", command="true"))
    write_config('[[task]]\nname = "lint"\nenabled = false\n', "arbiter.local.toml")
    assert not by_name(load(repo))["lint"].enabled


def test_budget_defaults_and_is_overridden_by_a_later_layer(home, repo, write_config):
    write_config(SHELL.format(name="lint", command="true"))
    assert load(repo).budget == ENGINE_BUDGET
    home.user_defaults("[arbiter]\nbudget = 300\n")
    assert load(repo).budget == 300
    write_config("[arbiter]\nbudget = 200\n", "arbiter.local.toml")
    assert load(repo).budget == 200


@pytest.mark.parametrize("budget", ["0", "600", "900", '"fast"', "true"])
def test_budget_must_stay_under_the_hook_ceiling(repo, write_config, budget):
    write_config(f"[arbiter]\nbudget = {budget}\n" + SHELL.format(name="lint", command="true"))
    with pytest.raises(ConfigError, match="budget"):
        load(repo)


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ('[[task]]\nrunner = "shell"\ncommand = "true"\n', "missing required field 'name'"),
        ('[[task]]\nname = "x"\nrunner = "bash"\ncommand = "true"\n', "runner must be one of"),
        ('[[task]]\nname = "x"\nrunner = "shell"\n', "requires 'command'"),
        (
            '[[task]]\nname = "x"\nrunner = "shell"\ncommand = "true"\neffort = "high"\n',
            "judge runners only",
        ),
        ('[[task]]\nname = "x"\nrunner = "claude"\n', "require one of"),
        (
            '[[task]]\nname = "x"\nrunner = "claude"\nprompt = "a"\nprompt_file = "b"\n',
            "mutually exclusive",
        ),
        (
            '[[task]]\nname = "x"\nrunner = "claude"\nprompt = "a"\neffort = "minimal"\n',
            "effort must be one of",
        ),
        (
            '[[task]]\nname = "x"\nrunner = "codex"\nprompt = "a"\neffort = "max"\n',
            "effort must be one of",
        ),
        ('[[task]]\nname = "x"\nrunner = "shell"\ncommand = "true"\ntimeout = 0\n', "positive"),
        ("task = 3\n", "array of tables"),
        ("[arbiter\n", "invalid TOML"),
    ],
)
def test_invalid_config_is_a_located_error(repo, write_config, body, error):
    path = write_config(body)
    with pytest.raises(ConfigError, match=error) as caught:
        load(repo)
    assert str(path) in str(caught.value) or "task 'x'" in str(caught.value)


@pytest.mark.parametrize(
    ("runner", "effort"),
    [("claude", "max"), ("claude", "xhigh"), ("codex", "minimal"), ("codex", "xhigh")],
)
def test_effort_is_validated_per_runner(repo, write_config, runner, effort):
    write_config(f'[[task]]\nname = "j"\nrunner = "{runner}"\nprompt = "p"\neffort = "{effort}"\n')
    assert by_name(load(repo))["j"].effort == effort


def test_persona_resolution_order(home, repo):
    builtin = BUILTIN_DIR / "judges" / "security-reviewer.md"
    assert resolve_persona("security-reviewer", repo) == builtin

    user = home.config / "judges" / "security-reviewer.md"
    user.parent.mkdir(parents=True)
    user.write_text("user")
    assert resolve_persona("security-reviewer", repo) == user

    shared = repo / "judges" / "security-reviewer.md"
    shared.parent.mkdir()
    shared.write_text("repo")
    assert resolve_persona("security-reviewer", repo) == shared

    private = repo / ".arbiter" / "judges" / "security-reviewer.md"
    private.parent.mkdir(parents=True)
    private.write_text("private")
    assert resolve_persona("security-reviewer", repo) == private


def test_unknown_persona_lists_where_it_looked(home, repo):
    with pytest.raises(ConfigError) as caught:
        resolve_persona("nobody", repo)
    message = str(caught.value)
    for place in (repo / ".arbiter" / "judges", home.config / "judges", BUILTIN_DIR / "judges"):
        assert str(place / "nobody.md") in message


def test_output_style_is_the_body_without_frontmatter(home, repo):
    style = resolve_output_style("verdict", repo)
    assert style.startswith("You are rendering a verdict")
    assert "---" not in style.splitlines()[0]
    assert "name: verdict" not in style

    user = home.config / "output-styles" / "verdict.md"
    user.parent.mkdir(parents=True)
    user.write_text("---\nname: verdict\n---\nuser style\n")
    assert resolve_output_style("verdict", repo) == "user style"

    project = repo / ".arbiter" / "output-styles" / "verdict.md"
    project.parent.mkdir(parents=True)
    project.write_text("project style")
    assert resolve_output_style("verdict", repo) == "project style"


def test_output_style_empty_means_none_and_unknown_is_an_error(repo):
    assert resolve_output_style("", repo) == ""
    with pytest.raises(ConfigError, match="output style 'nope' not found"):
        resolve_output_style("nope", repo)


def test_find_data_prefers_the_user_copy(home):
    builtin = find_data("schema", "verdict.schema.json")
    assert builtin == BUILTIN_DIR / "schema" / "verdict.schema.json"
    user = home.config / "schema" / "verdict.schema.json"
    user.parent.mkdir(parents=True)
    user.write_text("{}")
    assert find_data("schema", "verdict.schema.json") == user
    assert find_data("schema", "missing.json") is None


def test_instruction_joins_persona_and_prompt(repo, write_config):
    (repo / "review.md").write_text("from a file")
    write_config(
        '[[task]]\nname = "a"\nrunner = "claude"\nagent = "security-reviewer"\nprompt = "extra"\n'
        '[[task]]\nname = "b"\nrunner = "codex"\nprompt_file = "review.md"\n'
        '[[task]]\nname = "c"\nrunner = "codex"\nprompt_file = "missing.md"\n'
    )
    tasks = by_name(load(repo))
    text = resolve_instruction(tasks["a"], repo)
    assert text.startswith("# Security reviewer")
    assert text.endswith("extra")
    assert resolve_instruction(tasks["b"], repo) == "from a file"
    with pytest.raises(ConfigError, match="prompt_file not found"):
        resolve_instruction(tasks["c"], repo)
