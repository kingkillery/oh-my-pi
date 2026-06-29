from solution import running_max


def test_running_max():
    assert running_max([1, 3, 2]) == [1, 3, 3]
    assert running_max([]) == []
