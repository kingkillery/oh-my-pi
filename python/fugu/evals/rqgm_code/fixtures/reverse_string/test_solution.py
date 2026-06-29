from solution import reverse


def test_reverse():
    assert reverse("abc") == "cba"
    assert reverse("") == ""
