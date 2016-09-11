"""
test_api.py
author: @mbiokyle29
"""
from click import BadParameter
from functools import partial
import pytest


from onecodex.utils import (
    check_for_allowed_file,
    valid_api_key
)


def test_check_allowed_file():
    # bad ones
    with pytest.raises(SystemExit):
        check_for_allowed_file("file.bam")
        check_for_allowed_file("file")

    # good ones
    check_for_allowed_file("file.fastq")
    check_for_allowed_file("file.fastq.gz")


def test_is_valid_api_key():
    empty_key = ""
    short_key = "123"
    long_key = "123abc123abc123abc123abc123abc123abc123abc123abc123abc"
    good_key = "123abc123abc123abc123abc123abc32"

    # its a click callback so it expects some other params
    valid_api_key_partial = partial(valid_api_key, None, None)

    for key in [empty_key, short_key, long_key]:
        with pytest.raises(BadParameter):
            valid_api_key_partial(key)

    assert good_key == valid_api_key_partial(good_key)