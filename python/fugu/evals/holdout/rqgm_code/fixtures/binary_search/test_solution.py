from solution import binary_search


def test_binary_search():
    assert binary_search([1, 3, 5, 7], 5) == 2
    assert binary_search([1, 3, 5, 7], 4) == -1
