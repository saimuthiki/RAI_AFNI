import argparse
import socket
import pytest
from unittest.mock import patch, MagicMock
from fuzzyai.cli import find_available_port, run_webui

def test_find_available_port_success():
    """Test finding an available port when the start port is free."""
    with patch('socket.socket') as mock_socket:
        mock_socket.return_value.__enter__.return_value.connect_ex.return_value = 1  # Port not in use
        port = find_available_port(8080)
        assert port == 8080

def test_find_available_port_conflict():
    """Test finding an available port when the start port is taken."""
    with patch('socket.socket') as mock_socket:
        # First call returns 0 (in use), second returns 1 (free)
        mock_socket.return_value.__enter__.return_value.connect_ex.side_effect = [0, 1]
        port = find_available_port(8080)
        assert port == 8081

def test_find_available_port_exhausted():
    """Test raising RuntimeError when no ports are available."""
    with patch('socket.socket') as mock_socket:
        mock_socket.return_value.__enter__.return_value.connect_ex.return_value = 0  # All in use
        with pytest.raises(RuntimeError):
            find_available_port(8080, max_attempts=5)

@pytest.mark.asyncio
async def test_run_webui_default_port():
    """Test run_webui with default port selection."""
    args = argparse.Namespace(port=None)
    with patch('fuzzyai.cli.find_available_port', return_value=8080) as mock_find_port, \
         patch('subprocess.Popen') as mock_popen, \
         patch('asyncio.sleep'), \
         patch('builtins.print'):
        
        await run_webui(args)
        
        mock_find_port.assert_called_once_with(8080)
        mock_popen.assert_called_once()
        assert mock_popen.call_args[0][0][-1] == '8080'

@pytest.mark.asyncio
async def test_run_webui_custom_port():
    """Test run_webui with custom port."""
    args = argparse.Namespace(port=9000)
    with patch('fuzzyai.cli.find_available_port') as mock_find_port, \
         patch('subprocess.Popen') as mock_popen, \
         patch('asyncio.sleep'), \
         patch('builtins.print'):
        
        await run_webui(args)
        
        mock_find_port.assert_not_called()
        mock_popen.assert_called_once()
        assert mock_popen.call_args[0][0][-1] == '9000'
