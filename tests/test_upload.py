from io import BytesIO

from mock import patch
import pytest

from onecodex.lib.inline_validator import FASTXNuclIterator, FASTXTranslator
from onecodex.lib.upload import upload, upload_file, upload_large_file


def test_nucl_iterator():
    fakefile = BytesIO(b'>test\nACGT\n')
    iterator = iter(FASTXNuclIterator(fakefile))
    val = next(iterator)
    assert val == b'>test\nACGT\n'
    with pytest.raises(StopIteration):
        next(iterator)


def test_paired_validator():
    # test a single file
    fakefile = BytesIO(b'>test\nACGT\n')
    outfile = FASTXTranslator(fakefile, recompress=False)
    assert outfile.read() == b'>test\nACGT\n'

    # test a single file without an ending newline
    fakefile = BytesIO(b'>test\nACGT')
    outfile = FASTXTranslator(fakefile, recompress=False)
    assert outfile.read() == b'>test\nACGT\n'

    # test paired files
    fakefile = BytesIO(b'>test\nACGT\n')
    fakefile2 = BytesIO(b'>test2\nTGCA\n')
    outfile = FASTXTranslator(fakefile, pair=fakefile2, recompress=False)
    assert outfile.read() == b'>test\nACGT\n>test2\nTGCA\n'

    # test compression works
    fakefile = BytesIO(b'>test\nACGT\n')
    outfile = FASTXTranslator(fakefile)
    outdata = outfile.read()

    # there's a 4-byte timestamp in the middle of the gziped data so we check the start and end
    assert outdata.startswith(b'\x1f\x8b\x08\x00')
    assert outdata.endswith(b'\x02\xff\xb3+I-.\xe1rtv\x0f\xe1\x02\x00\xf3\x1dK\xc4\x0b\x00\x00\x00')


@pytest.mark.parametrize('n_newlines', [0, 1, 2, 3])
def test_validator_newlines(runner, n_newlines):
    # Test that we properly parse files with 0, 1, or more than 1 newline at the end
    # including our n bytes remaining calculations
    # (Use runner for isolated filesystem only here)
    content = (b'>test\nACGTACGTAGCTGACACGTACGTAGCTGACACGTACGTAGCTGACACGTACGTAGCTGAC' +
               'ACGTACGTAGCTGACACGTACGTAGCTGACACGTACGTAGCTGACACGTACGTAGCTGAC' +
               '\n' * n_newlines)
    fakefile = BytesIO(content)
    outfile = FASTXTranslator(fakefile, recompress=False)
    if n_newlines == 0:
        assert content[-1] == 'C'
    else:
        assert content[(-1 * n_newlines):] == '\n' * n_newlines
    assert outfile.read().rstrip('\n') == content.rstrip('\n')
    assert outfile.reads.bytes_left == 0

    with runner.isolated_filesystem():
        with open('myfasta.fa', mode='w') as f:
            f.write(content)
        outfile2 = FASTXTranslator(open('myfasta.fa'), recompress=False)
        assert outfile2.read().rstrip('\n') == content.rstrip('\n')
        assert outfile2.reads.bytes_left == 0


@pytest.mark.parametrize('file_list,n_small,n_big', [
    (['file.1000.fa', 'file.5e10.fa'], 1, 1),
    ([('file.3e10.R1.fa', 'file.3e10.R2.fa')], 0, 1),
    ([('file.3e5.R1.fa', 'file.3e5.R2.fa'), 'file.1e5.fa'], 2, 0),
])
def test_upload_lots_of_files(file_list, n_small, n_big):
    session, samples_resource, server_url = None, None, None

    fake_size = lambda filename: int(float(filename.split('.')[1]))  # noqa

    uf = 'onecodex.lib.upload.upload_file'
    ulf = 'onecodex.lib.upload.upload_large_file'
    opg = 'onecodex.lib.upload.os.path.getsize'
    wf = 'onecodex.lib.upload._wrap_files'
    with patch(uf) as sm_upload, patch(ulf) as lg_upload, patch(wf) as p:
        with patch(opg, side_effect=fake_size) as p2:
            upload(file_list, session, samples_resource, server_url)
            assert sm_upload.call_count == n_small
            assert lg_upload.call_count == n_big
            assert p.call_count == len(file_list)
            assert p2.call_count == sum(2 if isinstance(f, tuple) else 1 for f in file_list)


class FakeSamplesResource():
    def init_upload(self, obj):
        assert 'filename' in obj
        assert 'size' in obj
        assert 'upload_type' in obj
        return {
            'upload_url': '',
            'sample_id': '',
            'additional_fields': {},
        }

    def read_init_multipart_upload(self):
        return {
            'callback_url': '',
            's3_bucket': '',
            'file_id': '',
            'upload_aws_access_key_id': '',
            'upload_aws_secret_access_key': '',
        }

    def confirm_upload(self, obj):
        assert 'sample_id' in obj
        assert 'upload_type' in obj


class FakeSession():
    def post(self, url, **kwargs):
        resp = lambda: None  # noqa
        resp.status_code = 201 if 'auth' in kwargs else 200
        return resp


def test_upload_big_file():
    file_obj = BytesIO(b'>test\nACGT\n')
    session = FakeSession()
    samples_resource = FakeSamplesResource()
    server_url = ''

    with patch('boto3.client') as p:
        upload_large_file(file_obj, 'test.fa', session, samples_resource, server_url)
        assert p.call_count == 1

    file_obj.close()


def test_upload_small_file():
    file_obj = BytesIO(b'>test\nACGT\n')
    session = FakeSession()
    samples_resource = FakeSamplesResource()

    upload_file(file_obj, 'test.fa', session, samples_resource)
    file_obj.close()


def test_wrapper_speed():
    # to check serialization speed run just this test with:
    # %timeit !py.test tests/test_upload.py::test_wrapper_speed

    # most of the current bottleneck appears to be in the gzip.write step
    long_seq = b'ACGT' * 20
    record = b'>header_%s\n' + long_seq + '\n'
    data = b'\n'.join(record % i for i in range(200))
    wrapper = FASTXTranslator(BytesIO(data))
    assert len(wrapper.read()) < len(data)
