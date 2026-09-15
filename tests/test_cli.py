from typer.testing import CliRunner

from texlate.cli import app


def test_version() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert "texlate" in result.output
