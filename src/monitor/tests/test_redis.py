import pytest
from unittest.mock import patch, MagicMock
from monitor.lib import redis_utils as redis_module

@patch('lib.redis_utils.get_redis_client')
def test_update_memory_and_read_from_memory(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    # Prepare the pipeline for set/expire
    mock_pipe = MagicMock()
    mock_client.pipeline.return_value.__enter__.return_value = mock_pipe
    mock_pipe.set.return_value = None
    mock_pipe.expire.return_value = None
    mock_pipe.execute.return_value = None

    # verify_ttl needs to return (True, 1000)
    with patch('lib.redis_utils.verify_ttl', return_value=(True, 1000)):
        result = redis_module.update_memory('my input', 'my resp', key='abc', ttl=1000)
        assert 'Successfully saved' in result

    # Simulate reading value
    key = 'abc'
    # Return a fake value for .get
    value_dict = {
        'user_input': 'my input',
        'response': 'my resp',
        'timestamp': 12345,
        'ttl': 1000
    }
    mock_client.get.return_value = __import__('json').dumps(value_dict)
    with patch('lib.redis_utils.verify_ttl', return_value=(True, 900)):
        msg = redis_module.read_from_memory(key)
        assert 'Successfully retrieved' in msg

@patch('lib.redis_utils.get_redis_client')
def test_read_from_memory_key_not_found(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.get.return_value = None
    with patch('lib.redis_utils.verify_ttl', return_value=(False, -2)):
        result = redis_module.read_from_memory('notfound')
        assert result is None

@patch('lib.redis_utils.get_redis_client')
def test_delete_from_memory_success(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.delete.return_value = 1
    assert redis_module.delete_from_memory('deadbeef') is True
    mock_client.delete.return_value = 0
    assert redis_module.delete_from_memory('deadbeef') is False

@patch('lib.redis_utils.get_redis_client')
def test_fetch_memory_keys_as_json_success(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    # Patch fetch_memory_for_context to return two keys
    with patch('lib.redis_utils.fetch_memory_for_context', return_value=['c:1','c:2']):
        res = redis_module.fetch_memory_keys_as_json()
        import json
        keys = json.loads(res)
        assert 'c:1' in keys and 'c:2' in keys

@patch('lib.redis_utils.get_redis_client')
def test_update_memory_handles_json_serialization_error(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    # Patch json.dumps to fail
    with patch('lib.redis_utils.json.dumps', side_effect=TypeError('fail')):
        msg = redis_module.update_memory('bad', 'bad', key='b', ttl=10)
        assert 'Could not serialize data to JSON' in msg
