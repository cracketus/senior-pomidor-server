import nox

PACKAGE = ".[dev]"

nox.options.default_venv_backend = "venv"


def install_project(session: nox.Session) -> None:
    session.install("-e", PACKAGE)


@nox.session
def tests(session: nox.Session) -> None:
    install_project(session)
    session.run("python", "-m", "pytest", "-q")


@nox.session
def coverage(session: nox.Session) -> None:
    install_project(session)
    session.run("coverage", "run", "-m", "pytest", "-q")
    session.run("coverage", "report")


@nox.session
def lint(session: nox.Session) -> None:
    install_project(session)
    session.run("ruff", "check", ".")


@nox.session
def format_check(session: nox.Session) -> None:
    install_project(session)
    session.run("ruff", "format", "--check", ".")


@nox.session
def types(session: nox.Session) -> None:
    install_project(session)
    session.run("mypy", "app", "tools", "tests")


@nox.session
def security(session: nox.Session) -> None:
    install_project(session)
    session.run("bandit", "-c", "pyproject.toml", "-r", "app", "tools")


@nox.session
def deps_audit(session: nox.Session) -> None:
    session.install("--upgrade", "pip")
    install_project(session)
    session.run("pip-audit", "--skip-editable", "--cache-dir", session.create_tmp())
