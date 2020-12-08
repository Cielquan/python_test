"""Config file for nox."""
import contextlib
import os
import re
import subprocess  # noqa: S404
import sys

from pathlib import Path
from typing import Any, Callable, Dict, Optional

import nox
import tomlkit  # type: ignore[import]

from formelsammlung.venv_utils import (
    get_venv_bin_dir,
    get_venv_path,
    get_venv_site_packages_dir,
    get_venv_tmp_dir,
)
from nox.command import CommandFailed
from nox.logger import logger as nox_logger
from nox.sessions import Session as _Session


#: -- NOX OPTIONS ----------------------------------------------------------------------
nox.options.reuse_existing_virtualenvs = True
nox.options.default_venv_backend = "none"
nox.options.sessions = ["tox_lint", "tox_code", "tox_docs"]


#: -- CONFIG FROM PYPROJECT.TOML -------------------------------------------------------
NOXFILE_DIR = Path(__file__).parent
with open(NOXFILE_DIR / "pyproject.toml") as pyproject_file:
    PYPROJECT = tomlkit.parse(pyproject_file.read())

COV_CACHE_DIR = NOXFILE_DIR / ".coverage_cache"
JUNIT_CACHE_DIR = NOXFILE_DIR / ".junit_cache"
PACKAGE_NAME = PYPROJECT["tool"]["poetry"]["name"]

TOX_SKIP_SDIST = PYPROJECT["tool"]["_testing"]["tox_skip_sdist"]
TOX_PYTHON_VERSIONS = PYPROJECT["tool"]["_testing"]["tox_python_versions"]
TOX_DOCS_BUILDERS = PYPROJECT["tool"]["_testing"]["tox_docs_builders"]
# Currently used
__TOXENV_PYTHON_TEST_VERSIONS = TOX_PYTHON_VERSIONS
__TOXENV_SPHINX_BUILDER = TOX_DOCS_BUILDERS
__SPHINX_BUILDERS = __TOXENV_SPHINX_BUILDER[11:-1].split(",")


#: -- FILE GEN SOURCE ------------------------------------------------------------------
PDBRC_FILE = """# .pdbrc file generated by nox
import IPython
from traitlets.config import get_config

cfg = get_config()
cfg.InteractiveShellEmbed.colors = "Linux"
cfg.InteractiveShellEmbed.confirm_exit = False

# Use IPython for interact
alias interacti IPython.embed(config=cfg)

# Print a dictionary, sorted. %1 is the dict, %2 is the prefix for the names
alias p_ for k in sorted(%1.keys()): print("%s%-15s= %-80.80s" % ("%2",k,repr(%1[k]))

# Print member vars of a thing
alias pi p_ %1.__dict__ %1.

# Print member vars of self
alias ps pi self

# Print locals
alias pl p_ locals() local:

# Next and list
alias nl n;;l

# Step and list
alias sl s;;l
"""

_DEBUG_PY_FILE = """# Import devtools if installed and add to builtins
from importlib.util import find_spec
if find_spec('devtools'):
    import devtools
    __builtins__.update(debug=devtools.debug)
"""


#: -- MONKEYPATCH SESSION --------------------------------------------------------------
class Session(_Session):  # noqa: R0903
    """Subclass of nox's Session class to add `poetry_install` method."""

    def poetry_install(
        self,
        extras: Optional[str] = None,
        no_dev: bool = False,
        no_root: bool = False,
        require_venv: bool = False,
        **kwargs: Any,
    ) -> None:
        """Wrap `poetry install` for nox sessions.

        :param extras: string of space separated extras to install
        :param no_dev: if `--no-dev` should be set; defaults to: True
        :param no_root: if `--no-root` should be set; defaults to: False
        """
        #: Safety hurdle copied from nox.sessions.Session.install()
        if not isinstance(
            self._runner.venv,
            (
                nox.sessions.CondaEnv,
                nox.sessions.VirtualEnv,
                nox.sessions.PassthroughEnv,
            ),
        ):
            raise ValueError(
                "A session without a virtualenv can not install dependencies."
            )

        _env = {"PIP_DISABLE_VERSION_CHECK": "1"}
        _req_venv = {"PIP_REQUIRE_VIRTUALENV": "true"}

        if require_venv or isinstance(self.virtualenv, nox.sessions.PassthroughEnv):
            _env.update(_req_venv)
            if "env" in kwargs:
                kwargs["env"].update(_req_venv)
            else:
                kwargs["env"] = _req_venv

        self.install("poetry>=1", env=_env)

        extra_deps = ["--extras", extras] if extras else []
        no_dev_flag = ["--no-dev"] if no_dev else []
        no_root_flag = ["--no-root"] if no_root else []
        install_args = no_root_flag + no_dev_flag + extra_deps

        poetry_args = ["--ansi"] if os.getenv("_NOX_POETRY_COLOR") == "true" else []

        self._run("poetry", "install", *poetry_args, *install_args, **kwargs)


def monkeypatch_session(session_func: Callable) -> Callable:
    """Decorate nox session functions to add `poetry_install` method.

    :param session_func: decorated function with commands for nox session
    """

    def switch_session_class(session: Session, **kwargs: Dict[str, Any]) -> None:
        """Call session function with session object overwritten by custom one.

        :param session: nox session object
        :param kwargs: keyword arguments from e.g. parametrize
        """
        session = Session(session._runner)  # noqa: W0212
        session_func(session=session, **kwargs)

    #: Overwrite name and docstring to imitate decorated function for nox
    switch_session_class.__name__ = session_func.__name__
    switch_session_class.__doc__ = session_func.__doc__
    return switch_session_class


# FIXME: make venv/tox checker a decorator


#: -- UTILS ----------------------------------------------------------------------------
TOX_CALLS = os.getenv("_NOX_TOX_CALLS") == "true"
IN_CI = os.getenv("_NOX_IN_CI") == "true"
IN_VENV = False
with contextlib.suppress(FileNotFoundError):
    IN_VENV = get_venv_path() is not None


def _tox_caller(session: Session, tox_env: str) -> None:
    session.poetry_install("tox", no_root=True, no_dev=IN_CI)
    session.env["_TOX_SKIP_SDIST"] = str(TOX_SKIP_SDIST)
    session.run("tox", "-e", tox_env, *session.posargs)


#: -- TEST SESSIONS --------------------------------------------------------------------
@nox.session
@monkeypatch_session
def package(session: Session) -> None:
    """Check sdist and wheel."""
    if not IN_VENV or "tox" in session.posargs:
        with contextlib.suppress(ValueError):
            session.posargs.remove("tox")
        session.log("Using `tox` as venv backend.")
        _tox_caller(session, "package")
        return

    if "skip_install" not in session.posargs:
        extras = "poetry twine"
        session.poetry_install(extras, no_root=True, no_dev=(TOX_CALLS or IN_CI))
    else:
        session.log("Skipping install step.")

    session.run("poetry", "build", "-vvv")
    session.run("twine", "check", "dist/*")


@nox.session
@monkeypatch_session
def test_code(session: Session) -> None:
    """Run tests with given python version."""
    if not IN_VENV or "tox" in session.posargs:
        session.log("Using `tox` as venv backend.")
        _tox_caller(session, TOX_PYTHON_VERSIONS)
        return

    if "skip_install" not in session.posargs:
        extras = "testing"
        session.poetry_install(extras, no_root=True, no_dev=(TOX_CALLS or IN_CI))
        # TODO: check if coverage path can be changed to make cov work for .venv
        # TODO: and change no_root to dynamic
        if not TOX_CALLS:
            session.install(".")
    else:
        session.log("Skipping install step.")
        #: Remove processed posargs
        with contextlib.suppress(ValueError):
            session.posargs.remove("skip_install")

    interpreter = sys.implementation.__getattribute__("name")
    version = ".".join([str(v) for v in sys.version_info[0:2]])
    name = f"{interpreter}{version}"

    session.env["COVERAGE_FILE"] = str(COV_CACHE_DIR / f".coverage.{name}")

    venv_path = get_venv_path()

    session.run(
        "pytest",
        f"--basetemp={get_venv_tmp_dir(venv_path)}",
        f"--junitxml={JUNIT_CACHE_DIR / f'junit.{session.python}.xml'}",
        f"--cov={get_venv_site_packages_dir(venv_path) / PACKAGE_NAME}",
        f"--cov-fail-under={session.env.get('MIN_COVERAGE') or 100}",
        f"--numprocesses={session.env.get('PYTEST_XDIST_N') or 'auto'}",
        f"{session.posargs or 'tests'}",
    )


def _coverage(session: Session, job: str = "all") -> None:
    if "skip_install" not in session.posargs:
        extras = "coverage"
        if job in ["report", "all"]:
            extras += " diff-cover"
        session.poetry_install(extras, no_root=True, no_dev=(TOX_CALLS or IN_CI))
    else:
        session.log("Skipping install step.")
        #: Remove processed posargs
        with contextlib.suppress(ValueError):
            session.posargs.remove("skip_install")

    session.env["COVERAGE_FILE"] = str(COV_CACHE_DIR / ".coverage")

    if job in ["merge", "all"]:
        session.run("coverage", "combine")

        cov_xml = f"{COV_CACHE_DIR / 'coverage.xml'}"
        session.run("coverage", "xml", "-o", cov_xml)

        cov_html_dir = f"{COV_CACHE_DIR / 'htmlcov'}"
        session.run("coverage", "html", "-d", cov_html_dir)

    if job in ["report", "all"]:
        raise_error = False
        min_cov = session.env.get("MIN_COVERAGE") or 100

        try:
            session.run("coverage", "report", "-m", f"--fail-under={min_cov}")
        except CommandFailed:
            raise_error = True

        cov_xml = f"{COV_CACHE_DIR / 'coverage.xml'}"
        session.run(
            "diff-cover",
            f"--compare-branch={session.env.get('DIFF_AGAINST') or 'origin/master'}",
            "--ignore-staged",
            "--ignore-unstaged",
            f"--fail-under={session.env.get('MIN_DIFF_COVERAGE') or 100}",
            f"--diff-range-notation={session.env.get('DIFF_RANGE_NOTATION') or '..'}",
            cov_xml,
        )

        if raise_error:
            raise CommandFailed


@nox.session
@monkeypatch_session
def coverage_merge(session: Session) -> None:
    """Combine coverage data and create xml/html reports."""
    if not IN_VENV or "tox" in session.posargs:
        with contextlib.suppress(ValueError):
            session.posargs.remove("tox")
        session.log("Using `tox` as venv backend.")
        _tox_caller(session, "coverage_merge")
        return

    _coverage(session, "merge")


@nox.session
@monkeypatch_session
def coverage_report(session: Session) -> None:
    """Report total and diff coverage against origin/master (or DIFF_AGAINST)."""
    if not IN_VENV or "tox" in session.posargs:
        with contextlib.suppress(ValueError):
            session.posargs.remove("tox")
        session.log("Using `tox` as venv backend.")
        _tox_caller(session, "coverage_report")
        return

    _coverage(session, "report")


@nox.session
@monkeypatch_session
def coverage(session: Session) -> None:
    """Run coverage_merge + coverage_report."""
    if not IN_VENV or "tox" in session.posargs:
        with contextlib.suppress(ValueError):
            session.posargs.remove("tox")
        session.log("Using `tox` as venv backend.")
        _tox_caller(session, "coverage")
        return

    _coverage(session, "all")


@nox.session
@monkeypatch_session
def safety(session: Session) -> None:
    """Check all dependencies for known vulnerabilities."""
    if not IN_VENV or "tox" in session.posargs:
        with contextlib.suppress(ValueError):
            session.posargs.remove("tox")
        session.log("Using `tox` as venv backend.")
        _tox_caller(session, "safety")
        return

    if "skip_install" not in session.posargs:
        extras = "poetry safety"
        session.poetry_install(extras, no_root=True, no_dev=(TOX_CALLS or IN_CI))
    else:
        session.log("Skipping install step.")

    venv_path = get_venv_path()
    req_file_path = get_venv_tmp_dir(venv_path) / "requirements.txt"

    #: Use `poetry show` to fill `requirements.txt`
    command = [str(get_venv_bin_dir(venv_path) / "poetry"), "show"]
    # TODO: simplify when py36 is not longer supported.  # noqa: W0511
    if sys.version_info[0:2] > (3, 6):
        cmd = subprocess.run(command, check=True, capture_output=True)  # noqa: S603
    else:
        cmd = subprocess.run(command, check=True, stdout=subprocess.PIPE)  # noqa: S603
    with open(req_file_path, "w") as req_file:
        req_file.write(
            re.sub(r"([\w-]+)[ (!)]+([\d.a-z-]+).*", r"\1==\2", cmd.stdout.decode())
        )

    session.run("safety", "check", "-r", str(req_file_path), "--full-report")


@nox.session
@monkeypatch_session
def pre_commit(session: Session) -> None:  # noqa: R0912
    """Format and check the code."""
    if not IN_VENV or "tox" in session.posargs:
        with contextlib.suppress(ValueError):
            session.posargs.remove("tox")
        session.log("Using `tox` as venv backend.")
        _tox_caller(session, "pre_commit")
        return

    if "skip_install" not in session.posargs:
        extras = "pre-commit testing docs poetry nox"
        session.poetry_install(extras, no_root=TOX_CALLS, no_dev=(TOX_CALLS or IN_CI))
    else:
        session.log("Skipping install step.")

    #: Set 'show-diff' and 'skip identity hook'
    show_diff = []
    env = {"SKIP": "identity"}
    if (session.interactive and "diff" in session.posargs) or (
        not session.interactive and "nodiff" not in session.posargs
    ):
        show_diff = ["--show-diff-on-failure"]
        env = {}

    #: Add SKIP from posargs to env
    skip = ""
    for arg in session.posargs:
        if arg.startswith("SKIP="):
            skip = arg
            break

    if skip:
        env = {"SKIP": f"{skip[5:]},{env.get('SKIP', '')}"}

    #: Get hooks from posargs
    hooks_arg = ""
    for arg in session.posargs:
        if arg.startswith("HOOKS="):
            hooks_arg = arg
            break

    #: Remove processed posargs
    for arg in ("skip_install", "diff", "nodiff", skip, hooks_arg):
        with contextlib.suppress(ValueError):
            session.posargs.remove(arg)

    hooks = hooks_arg[6:].split(",") if hooks_arg else [""]

    error_hooks = []
    for hook in hooks:
        add_args = show_diff + session.posargs + [hook]
        try:
            session.run("pre-commit", "run", "--all-files", *add_args, env=env)
        except CommandFailed:
            error_hooks.append(hook)

    print(
        "HINT: to add checks as pre-commit hook run: ",
        f'"{get_venv_bin_dir(get_venv_path()) / "pre-commit"} '
        "install -t pre-commit -t commit-msg.",
    )

    if error_hooks:
        if hooks != [""]:
            nox_logger.error(f"The following pre-commit hooks failed: {error_hooks}.")
        raise CommandFailed


@nox.session
@monkeypatch_session
def docs(session: Session) -> None:
    """Build docs with sphinx."""
    if not IN_VENV or "tox" in session.posargs:
        with contextlib.suppress(ValueError):
            session.posargs.remove("tox")
        session.log("Using `tox` as venv backend.")
        _tox_caller(session, "docs")
        return

    extras = "docs"
    cmd = "sphinx-build"
    args = ["-b", "html", "-aE", "docs/source", "docs/build/html"]

    if "autobuild" in session.posargs or "ab" in session.posargs:
        extras += " sphinx-autobuild"
        cmd = "sphinx-autobuild"
        args += ["--open-browser"]

    #: Remove processed posargs
    for arg in ("skip_install", "autobuild", "ab"):
        with contextlib.suppress(ValueError):
            session.posargs.remove(arg)

    if "skip_install" not in session.posargs:
        session.poetry_install(extras, no_root=TOX_CALLS, no_dev=(TOX_CALLS or IN_CI))
    else:
        session.log("Skipping install step.")

    session.run(cmd, *args, *session.posargs)

    index_file = NOXFILE_DIR / "docs/build/html/index.html"
    print(f"DOCUMENTATION AVAILABLE UNDER: {index_file.as_uri()}")


@nox.parametrize("builder", __SPHINX_BUILDERS)
@nox.session
@monkeypatch_session
def test_docs(session: Session, builder: str) -> None:
    """Build and check docs with (see env name) sphinx builder."""
    if not IN_VENV or "tox" in session.posargs:
        with contextlib.suppress(ValueError):
            session.posargs.remove("tox")
        session.log("Using `tox` as venv backend.")
        _tox_caller(session, TOX_DOCS_BUILDERS)
        return

    if "skip_install" not in session.posargs:
        extras = "docs"
        session.poetry_install(extras, no_root=TOX_CALLS, no_dev=(TOX_CALLS or IN_CI))
    else:
        session.log("Skipping install step.")
        #: Remove processed posargs
        with contextlib.suppress(ValueError):
            session.posargs.remove("skip_install")

    source_dir = "docs/source"
    target_dir = f"docs/build/test/{builder}"
    default_args = ["-aE", "-v", "-nW", "--keep-going", source_dir, target_dir]
    add_args = ["-t", "builder_confluence"] if builder == "confluence" else []

    session.run(
        "sphinx-build", "-b", builder, *default_args, *add_args, *session.posargs
    )


#: -- DEV NOX SESSIONS -----------------------------------------------------------------
# FIXME: update the tox wrapper (for more than 1 env)
@nox.session
@monkeypatch_session
def install_extras(session: Session) -> None:
    """Set up dev environment in current venv."""
    extras = PYPROJECT["tool"]["poetry"].get("extras")

    if not extras:
        session.skip("No extras found to be installed.")

    extras_to_install = ""
    for extra in extras:
        if not extras_to_install:
            extras_to_install = extra
        else:
            extras_to_install += f" {extra}"

    session.poetry_install(extras_to_install, no_dev=False)

    session.run("python", "-m", "pip", "list", "--format=columns")
    print(f"PYTHON INTERPRETER LOCATION: {sys.executable}")


@nox.session
def setup_pre_commit(session: Session) -> None:
    """Set up pre-commit.

    ReCreate pre-commit tox env, install pre-commit hook, run tox env.
    """
    session.run("tox", "-re", "pre_commit", "--notest")
    session.run("pre-commit", "install", "-t", "pre-commit", "-t", "commit-msg")
    session.run("tox", "-e", "pre_commit")


@nox.session
def debug_import(session: Session) -> None:  # noqa: W0613
    """Hack for global import of `devtools.debug` in venv."""
    file_path = get_venv_site_packages_dir(get_venv_path())
    filename = "__devtools_debug_import_hack"

    with open(f"{file_path / f'{filename}.pth'}", "w") as pth_file:
        pth_file.write(f"import {filename}\n")

    with open(f"{file_path / f'{filename}.py'}", "w") as py_file:
        py_file.writelines(_DEBUG_PY_FILE)


@nox.session
def pdbrc(session: Session) -> None:  # noqa: W0613
    """Create .pdbrc file.

    Does not overwrite existing file.
    """
    pdbrc_file_path = NOXFILE_DIR / ".pdbrc"
    if not pdbrc_file_path.is_file():
        with open(pdbrc_file_path, "w") as pdbrc_file:
            pdbrc_file.writelines(PDBRC_FILE)


@nox.session
@monkeypatch_session
def tox_test_docs(session: Session) -> None:
    """Call tox to run `test_docs` envs."""
    _tox_caller(session, TOX_DOCS_BUILDERS)


#: -- TOX MULTI WRAPPER SESSIONS -------------------------------------------------------
# FIXME: update the tox wrapper (for more than 1 env)
@nox.session
@monkeypatch_session
def tox_lint(session: Session) -> None:
    """Call tox to run all lint tests."""
    _tox_caller(session, "safety,pre_commit")


@nox.session
@monkeypatch_session
def tox_code(session: Session) -> None:
    """Call tox to run all code tests incl. package and coverage."""
    toxenv = ""
    if "nopkg" not in session.posargs:
        toxenv += "package"

    if "notest" not in session.posargs:
        if not __TOXENV_PYTHON_TEST_VERSIONS:
            session.error(
                "Could not find 'python_test_version' in "
                "'[tox]' section in 'tox.ini' file"
            )
        toxenv += "," if toxenv else ""
        toxenv += __TOXENV_PYTHON_TEST_VERSIONS

    if "nocov" not in session.posargs:
        toxenv += "," if toxenv else ""
        toxenv += "coverage-all"

    if not toxenv:
        session.skip("No toxenv left to run")

    _tox_caller(session, toxenv)


@nox.session
@monkeypatch_session
def tox_docs_test(session: Session) -> None:
    """Call tox to run all docs tests."""
    _tox_caller(session, __TOXENV_SPHINX_BUILDER)
