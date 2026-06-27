from solution import is_palindrome


def test_is_palindrome():
    assert is_palindrome("racecar") is True
    assert is_palindrome("ab") is False
