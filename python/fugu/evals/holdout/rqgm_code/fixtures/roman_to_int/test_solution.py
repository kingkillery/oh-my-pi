from solution import roman_to_int


def test_roman_to_int():
    assert roman_to_int("III") == 3
    assert roman_to_int("IX") == 9
    assert roman_to_int("LVIII") == 58
