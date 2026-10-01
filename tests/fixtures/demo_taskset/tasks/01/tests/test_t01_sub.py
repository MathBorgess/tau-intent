from calc.core import add, sub


def test_sub():
    assert sub(5, 3) == 2
    assert sub(0, 4) == -4


def test_add_still_works():
    assert add(1, 1) == 2
