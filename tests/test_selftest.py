from __future__ import annotations

from autobom.cli import main
from autobom.core.selftest import run_selftest
from autobom.version import run_number


class TestRunSelftest:
    def test_passes_on_a_healthy_build(self):
        ok, report = run_selftest()
        assert ok is True, "\n".join(report)

    def test_report_covers_every_sheet(self):
        _, report = run_selftest()
        text = "\n".join(report)
        for name in ("1-8", "3-16", "F Parts", "Other", "All"):
            assert name in text

    def test_needs_no_customer_files(self, tmp_path, monkeypatch):
        # The synthetic job is built in a temp dir, so the self-test works on a
        # machine that has never seen a real BOM.
        monkeypatch.chdir(tmp_path)
        ok, _ = run_selftest()
        assert ok is True

    def test_detects_a_broken_classifier(self, monkeypatch):
        """A build whose rules regressed must fail, not report success."""
        import autobom.core.selftest as module

        monkeypatch.setattr(
            module, "classify_thickness", lambda value: "OTHER", raising=False
        )
        monkeypatch.setattr(
            "autobom.core.pipeline.classify_thickness", lambda value: "OTHER"
        )
        ok, report = run_selftest()
        assert ok is False
        assert any("expected" in line for line in report)


class TestCliSelftest:
    def test_exit_code_zero(self, capsys):
        assert main(["--selftest"]) == 0
        assert "SELF-TEST PASSED" in capsys.readouterr().out

    def test_needs_no_other_arguments(self, capsys):
        # CI runs the bare flag; inputs and -o must not be required.
        assert main(["--selftest"]) == 0

    def test_inputs_without_output_is_an_error(self, tmp_path):
        with __import__("pytest").raises(SystemExit):
            main([str(tmp_path)])


class TestRunNumber:
    def test_extracts_the_ci_run(self):
        assert run_number("42.a1b2c3d") == 42

    def test_dev_build_is_zero(self):
        assert run_number("0.dev") == 0

    def test_garbage_is_zero(self):
        assert run_number("nonsense") == 0
