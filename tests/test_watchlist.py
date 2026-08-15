from xtrading.screener.watchlist import load_watchlist


def test_load_watchlist_strips_comments_blanks_dupes_and_case(tmp_path):
    p = tmp_path / "w.txt"
    p.write_text(" spy \n# comment\nSNPS\n\nGOOG  # trailing\nspy\niren\n")
    assert load_watchlist(p) == ["SPY", "SNPS", "GOOG", "IREN"]


def test_load_watchlist_empty_file(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("# only a comment\n\n")
    assert load_watchlist(p) == []
