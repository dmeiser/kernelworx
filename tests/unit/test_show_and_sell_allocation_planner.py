from src.utils.show_and_sell_allocation_planner import plan_allocation_targets


def test_increase_target():
    actions = plan_allocation_targets({"p1": 2}, {"p1": 5})
    assert len(actions) == 1
    assert actions[0].delta == 3
    assert actions[0].target_qty == 5


def test_decrease_target():
    actions = plan_allocation_targets({"p1": 5}, {"p1": 2}, sold={"p1": 0})
    assert actions[0].delta == -3
    assert actions[0].released_qty == 3


def test_zero_target_releases():
    actions = plan_allocation_targets({"p1": 4}, {"p1": 0})
    assert actions[0].released_qty == 4
    assert actions[0].target_qty == 0


def test_omitted_product_no_action():
    actions = plan_allocation_targets({"p1": 4, "p2": 3}, {"p1": 5})
    assert len(actions) == 1
    assert actions[0].product_id == "p1"


def test_sold_stock_protection():
    actions = plan_allocation_targets({"p1": 5}, {"p1": 1}, sold={"p1": 3})
    assert actions[0].target_qty >= 3
    assert actions[0].protected_sold_qty == 3


def test_16th_product():
    current = {f"p{i}": 1 for i in range(16)}
    targets = {f"p{i}": 2 for i in range(16)}
    actions = plan_allocation_targets(current, targets)
    assert len(actions) == 16
