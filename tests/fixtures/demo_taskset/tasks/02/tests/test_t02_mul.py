from calc.ops import mul


def test_mul():
    assert mul(3, 4) == 12
    assert mul(-2, 5) == -10
