
import pytest
import json
from unittest.mock import patch, MagicMock
from monitor.lib import db_storage

@patch('monitor.lib.db_storage.subprocess.run')
def test_execute_duckdb_success(mock_run):
    mock_process = MagicMock()
    mock_process.stdout = 'result row'
    mock_process.stderr = ''
    mock_process.returncode = 0
    mock_run.return_value = mock_process
    result = db_storage.execute_duckdb('SELECT 1;')
    data = result if isinstance(result, dict) else json.loads(result)
    assert data['stdout'] == 'result row'
    assert data['stderr'] == ''
    assert data['returncode'] == 0
    mock_run.assert_called_once_with(['duckdb', 'my_duckdb.db', '-c', 'SELECT 1;'], capture_output=True, text=True)

@patch('monitor.lib.db_storage.subprocess.run', side_effect=FileNotFoundError)
def test_execute_duckdb_missing_binary(mock_run):
    result = db_storage.execute_duckdb('SELECT 1;')
    data = result if isinstance(result, dict) else json.loads(result)
    assert 'duckdb executable not found' in data['error']

@patch('monitor.lib.db_storage.subprocess.run')
def test_execute_psql_success(mock_run):
    mock_process = MagicMock()
    mock_process.stdout = 'id\n1'
    mock_process.stderr = ''
    mock_process.returncode = 0
    mock_run.return_value = mock_process
    result = db_storage.execute_psql('SELECT 1;')
    data = result if isinstance(result, dict) else json.loads(result)
    assert 'id' in data['stdout']
    assert data['returncode'] == 0
    mock_run.assert_called_once_with(['psql', '-c', 'SELECT 1;'], capture_output=True, text=True)

@patch('monitor.lib.db_storage.subprocess.run', side_effect=FileNotFoundError)
def test_execute_psql_missing_binary(mock_run):
    result = db_storage.execute_psql('SELECT 1;')
    data = result if isinstance(result, dict) else json.loads(result)
    assert 'psql executable not found' in data['error']

@patch('monitor.lib.db_storage.subprocess.run')
def test_execute_mc_success(mock_run):
    mock_process = MagicMock()
    mock_process.stdout = 'success!'
    mock_process.stderr = ''
    mock_process.returncode = 0
    mock_run.return_value = mock_process
    result = db_storage.execute_mc('ls mybucket')
    data = result if isinstance(result, dict) else json.loads(result)
    assert data['stdout'] == 'success!'
    assert data['returncode'] == 0
    mock_run.assert_called_once_with(['mc', 'ls', 'mybucket'], capture_output=True, text=True)

@patch('monitor.lib.db_storage.subprocess.run', side_effect=FileNotFoundError)
def test_execute_mc_missing_binary(mock_run):
    result = db_storage.execute_mc('ls mybucket')
    data = result if isinstance(result, dict) else json.loads(result)
    assert 'mc executable not found' in data['error']

def test_execute_duckdb_missing_command():
    result = db_storage.execute_duckdb('')
    data = result if isinstance(result, dict) else json.loads(result)
    assert 'Missing required parameter' in data['error']

def test_execute_psql_missing_command():
    result = db_storage.execute_psql('')
    data = result if isinstance(result, dict) else json.loads(result)
    assert 'Missing required parameter' in data['error']

def test_execute_mc_missing_command():
    result = db_storage.execute_mc('')
    data = result if isinstance(result, dict) else json.loads(result)
    assert 'Missing required parameter' in data['error']


