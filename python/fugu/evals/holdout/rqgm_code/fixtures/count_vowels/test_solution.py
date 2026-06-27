from solution import count_vowels


def test_count_vowels():
    assert count_vowels("hello") == 2
    assert count_vowels("xyz") == 0
