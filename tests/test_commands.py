from lawcorpus.commands import _try_parse_yyyymmdd


def test_try_parse_yyyymmdd_accepts_plain_digits():
    assert _try_parse_yyyymmdd("20201015").isoformat() == "2020-10-15"


def test_try_parse_yyyymmdd_accepts_dotted_format():
    assert _try_parse_yyyymmdd("2020.10.15").isoformat() == "2020-10-15"


def test_try_parse_yyyymmdd_rejects_garbage():
    assert _try_parse_yyyymmdd("") is None
    assert _try_parse_yyyymmdd("미상") is None
