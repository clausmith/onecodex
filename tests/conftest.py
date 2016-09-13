from contextlib import contextmanager
import json
import os
from pkg_resources import resource_string
import pytest
import re
import requests
import responses

from onecodex import Api


def intercept(func, log=False, dump=None):
    """
    Used to copy API requests to make sure test data doesn't depend upon a connection to the One
    Codex server (basically like `betamax`, but for our requests/responses setup).

    For example, to dump out a log of everything that the function `test_function` requests, do the
    following:

    >>>mock_responses = {}
    >>>intercept(test_function, dump=mock_responses)
    >>>mock_json = json.dumps(mock_responses, separators=(',', ':'))

    Then you can test the function in the future by copying the output of mock_json into
    a string literal and doing:

    >>>mock_request(test_function, mock_json)
    """
    def handle_request(request):
        if log:
            print('->', request.method, request.url)

        # patch the request through (and disable mocking for this chunk)
        responses.mock.stop()
        resp = requests.get(request.url, headers=request.headers)
        text = resp.text
        headers = resp.headers
        # for some reason, responses pitches a fit about this being in the cookie
        headers['Set-Cookie'] = headers.get('Set-Cookie', '').replace(' HttpOnly;', '')
        responses.mock.start()
        data = json.dumps(json.loads(text), separators=(',', ':'))
        if log:
            print('<-', resp.status_code, data)
        if dump is not None:
            dump[request.method + ':' + request.url.split('/', 3)[-1]] = data
        return (200, headers, text)

    regex = re.compile('.*')
    with responses.mock as rsps:
        rsps.add_callback(responses.GET, regex, callback=handle_request)
        func()


# TODO: Fix a bug wherein this will return all the items to potion
#       but potion will still try to request subsequent pages... (it's stubborn!)
#       CRITICALLY THIS MEANS THAT TEST CASES SHOULD ONLY USE THE FIRST 20 ITEMS
@contextmanager
def mock_requests(mock_json):
    with responses.mock as rsps:
        for mock_url, mock_data in mock_json.items():
            method, content_type, url = mock_url.split(':', 2)
            if not content_type:
                content_type = 'application/json'
            if callable(mock_data):
                rsps.add_callback(method, re.compile('http://[^/]+/' + url + '(\?.*)?$'),
                                  callback=mock_data,
                                  content_type=content_type)
            else:
                rsps.add(method, re.compile('http://[^/]+/' + url + '(\?.*)?$'),
                         body=json.dumps(mock_data),
                         content_type=content_type)
        yield


# TODO: Consider deleting in favor of context manager as above
def mock_requests_decorator(mock_json):
    def decorator(func):
        def wrapper(*args, **kwargs):
            with responses.mock as rsps:
                for mock_url, mock_data in mock_json.items():
                    method, content_type, url = mock_url.split(':', 2)
                    if not content_type:
                        content_type = 'application/json'
                    if callable(mock_data):
                        rsps.add_callback(method, re.compile('http://[^/]+/' + url + '(\?.*)?$'),
                                          callback=mock_data,
                                          content_type=content_type)
                    else:
                        rsps.add(method, re.compile('http://[^/]+/' + url + '(\?.*)?$'),
                                 body=mock_data,
                                 content_type=content_type)
                func(*args, **kwargs)
                assert len(responses.calls) > 0
        return wrapper
    return decorator


def rs(path):
    return resource_string(__name__, path).decode('utf-8')


def json_resource(path):
    return json.loads(rs(path))


# All of the API data
# Scheme is
# METHOD:CONTENT_TYPE:URL  (content-type is optional)
# and then data is JSON or a callable
API_DATA = {
    # These are overrides for non-GET calls, which we don't auto-mock
    "DELETE::api/v1/samples/761bc54b97f64980": {},
    "GET::api/v1/classifications/f9e4a5506b154953/table": {
        "table": [{
            "name": "Salmonella enterica subsp. enterica",
            "rank": "subspecies",
            "readcount": 4642,
            "readcount_w_children": 4960,
            "species_abundance": None,
            "tax_id": 59201
        }]
    },
}

for filename in os.listdir('tests/api_data'):
    if not filename.endswith('.json'):
        continue

    resource = json.load(open(os.path.join('tests/api_data', filename)))
    if filename.startswith('schema'):
        continue  # Parse separately below

    resource_name = filename.replace('.json', '')
    resource_uri = "GET::api/v1/{}".format(resource_name)
    API_DATA[resource_uri] = resource

    # Then iterate through all instances
    if isinstance(resource, list):
        for instance in resource:
            instance_uri = "GET::{}".format(instance['$uri'].lstrip('/'))
            API_DATA[instance_uri] = instance


SCHEMA_ROUTES = {}

for filename in os.listdir('tests/api_data'):
    if not filename.startswith('schema'):
        continue

    resource = json.load(open(os.path.join('tests/api_data', filename)))
    if filename == 'schema.json':
        resource_uri = 'GET::api/v1/schema'
    else:
        resource_name = filename.replace('.json', '').split('_')[1]
        resource_uri = 'GET::api/v1/{}/schema'.format(resource_name)

    SCHEMA_ROUTES[resource_uri] = resource


API_DATA.update(SCHEMA_ROUTES)


@pytest.fixture(scope='function')
def api_data():
    with mock_requests(API_DATA):
        yield


@pytest.fixture(scope='function')
def upload_mocks():
    def upload_callback(request):
        return (201, {'location': 'on-aws'}, {})

    json_data = {
        'GET::api/v1/samples/presign_upload': {
            'callback_url': '/api/confirm_upload',
            'signing_url': '/s3_sign',
            'url': 'http://localhost:3000/fake_aws_callback'
        },
        'POST::api/confirm_upload': '',
        'POST::s3_sign': {
            'AWSAccessKeyId': 'AKIAI36HUSHZTL3A7ORQ',
            'success_action_status': 201,
            'acl': 'private',
            'key': 'asd/file_ab6276c673814123/myfile.fastq',
            'signature': 'asdjsa',
            'policy': '123123123',
            'x-amz-server-side-encryption': 'AES256'
        },
        'POST:multipart/form-data:fake_aws_callback': upload_callback,
        'GET::api/v1/samples/init_multipart_upload': {
            'callback_url': '/api/import_file_from_s3',
            'file_id': 'abcdef0987654321',
            's3_bucket': 'onecodex-multipart-uploads-encrypted',
            'upload_aws_access_key_id': 'aws_key',
            'upload_aws_secret_access_key': 'aws_secret_key'
        },
        'POST::api/import_file_from_s3': '',
    }
    json_data.update(SCHEMA_ROUTES)
    with mock_requests(json_data):
        yield


# API FIXTURES
@pytest.fixture(scope='session')
def ocx():
    """Instantiated API client
    """
    with mock_requests(SCHEMA_ROUTES):
        ocx = Api(api_key='1eab4217d30d42849dbde0cd1bb94e39',
                  base_url='http://localhost:3000', cache_schema=False)
        return ocx


# CLI / FILE SYSTEM FIXTURE
@pytest.fixture(scope='function')
def mocked_creds_file(monkeypatch, tmpdir):
    # TODO: tmpdir is actually a LocalPath object
    # from py.path, and we coerce it into a string
    # for compatibility with the existing library code
    # *but* we should perhaps *not* do that for
    # better cross-platform compatibility. Investigate
    # and update as needed.
    def mockreturn(path):
        return os.path.join(str(tmpdir), '.onecodex')
    monkeypatch.setattr(os.path, 'expanduser', mockreturn)
