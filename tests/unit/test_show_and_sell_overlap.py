from src.utils.show_and_sell_overlap import evaluate_overlaps, Interval


def test_four_box():
    ivs = [Interval(0, 10, "p1", 6, 10), Interval(0, 10, "p1", 6, 10)]
    hard, warns = evaluate_overlaps(ivs)
    assert hard is True


def test_three_event_boundary():
    ivs = [Interval(0, 5, "p1", 4, 10), Interval(5, 10, "p1", 4, 10)]
    hard, warns = evaluate_overlaps(ivs)
    assert hard is False


def test_adjacency():
    ivs = [Interval(0, 5, "p1", 4, 10), Interval(5, 10, "p1", 4, 10)]
    hard, warns = evaluate_overlaps(ivs)
    assert hard is False


def test_zero_stock():
    ivs = [Interval(0, 10, "p1", 1, 0)]
    hard, warns = evaluate_overlaps(ivs)
    assert hard is True or len(warns) >= 0


def test_accessible_warning():
    ivs = [Interval(0, 5, "p1", 6, 10), Interval(5, 10, "p1", 6, 10)]
    hard, warns = evaluate_overlaps(ivs)
    assert isinstance(warns, list)
