from solution import merge_intervals


def test_merge_intervals():
    assert merge_intervals([[1, 3], [2, 6], [8, 10]]) == [[1, 6], [8, 10]]
    assert merge_intervals([]) == []
