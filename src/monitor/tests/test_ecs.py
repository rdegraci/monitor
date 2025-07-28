import pytest
from unittest.mock import patch, mock_open, MagicMock
import os
from monitor.lib import ecs

# Test index_directory for normal and recursive cases
@patch('lib.ecs.open', new_callable=mock_open, read_data='# some code')
@patch('lib.ecs.os.walk')
def test_index_directory_recursive(mock_walk, mock_file_open):
    mock_walk.return_value = [
        ('/my/dir', [], ['a.py', 'b.txt', 'c.swift']),
        ('/my/dir/nested', [], ['d.py'])
    ]
    files = list(ecs.index_directory('/my/dir', recursive=True))
    file_paths = [f[0] for f in files]
    assert '/my/dir/a.py' in file_paths
    assert '/my/dir/c.swift' in file_paths
    assert '/my/dir/nested/d.py' in file_paths
    # .txt should not be in results
    assert all(f[0].endswith(('.py', '.swift')) for f in files)

@patch('lib.ecs.open', new_callable=mock_open, read_data='print("hi")')
@patch('lib.ecs.os.listdir', return_value=['x.py', 'y.m', 'z.txt'])
@patch('lib.ecs.os.path.isfile', side_effect=lambda path: not path.endswith('dir'))
def test_index_directory_non_recursive(mock_isfile, mock_listdir, mock_file_open):
    files = list(ecs.index_directory('/dir', recursive=False))
    file_paths = [f[0] for f in files]
    assert '/dir/x.py' in file_paths
    assert '/dir/y.m' in file_paths
    assert '/dir/z.txt' not in file_paths

@patch('lib.ecs.requests.post')
@patch('lib.ecs.config')
def test_send_to_embedding_service_success(mock_config, mock_post):
    mock_config.ECS_HOST = 'localhost'
    mock_config.ECS_PORT = '1234'
    mock_config.ECS_TIMEOUT = 5
    # Simulate accepted
    mock_post.return_value.status_code = 202
    file_path = '/src/a.py'
    source = 'print(1)'
    ecs.send_to_embedding_service(file_path, source)
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert mock_config.ECS_HOST in args[0]
    assert kwargs['json']['file_name'] == file_path
    assert kwargs['json']['source_code'] == source

@patch('lib.ecs.send_to_embedding_service')
def test_embed_directory_orchestration(mock_send):
    # Patch index_directory to yield two files
    with patch('lib.ecs.index_directory', return_value=[('/f1.py','a'),('/f2.swift','b')]):
        ecs.embed_directory('/my/dir')
        mock_send.assert_any_call('/f1.py','a')
        mock_send.assert_any_call('/f2.swift','b')
        assert mock_send.call_count == 2
