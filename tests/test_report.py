from pathlib import Path

from manulife_analyzer.reports import build_report


def test_build_weekly_report(loaded_db, sample_settings, tmp_path):
    out_dir = tmp_path / "reports"
    path = build_report(loaded_db, sample_settings, "weekly", out_dir)
    assert Path(path).exists()
    html = path.read_text()
    # smoke checks: report includes title, fund names, disclaimer
    assert "Weekly Market Observation Report" in html
    assert "Test US Equity" in html
    assert "Disclaimer" in html
    assert "data:image/png;base64," in html  # at least one chart embedded


def test_build_monthly_report(loaded_db, sample_settings, tmp_path):
    path = build_report(loaded_db, sample_settings, "monthly", tmp_path / "reports")
    html = path.read_text()
    assert "Monthly Market Observation Report" in html
    assert "Risk-adjusted candidates" in html
