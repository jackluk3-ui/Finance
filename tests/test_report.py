from pathlib import Path

from manulife_analyzer.reports import build_report


def test_build_weekly_report(loaded_db, sample_settings, tmp_path):
    out_dir = tmp_path / "reports"
    path = build_report(loaded_db, sample_settings, "weekly", out_dir)
    assert Path(path).exists()
    html = path.read_text()
    assert "每週市場觀察報告" in html
    assert "測試美國股票" in html
    assert "免責聲明" in html
    assert "data:image/png;base64," in html
    # 4 個組合都應該出現
    assert "短炒組合" in html
    assert "中長線組合" in html
    assert "長線組合" in html
    # 板塊熱度區塊
    assert "板塊熱度" in html
    # 半導體標籤要出現
    assert "半導體" in html


def test_build_monthly_report(loaded_db, sample_settings, tmp_path):
    path = build_report(loaded_db, sample_settings, "monthly", tmp_path / "reports")
    html = path.read_text()
    assert "每月市場觀察報告" in html
    assert "四個時間框架嘅組合建議" in html
