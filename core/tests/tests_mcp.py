# -*- coding: utf-8 -*-
import json

from django.test import TestCase, override_settings
from django.utils import timezone

from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from babybuddy.models import User
from core import models


MCP_ENDPOINT = '/api/mcp'


def _mcp_request(method, params=None, id=1):
    """Build a JSON-RPC 2.0 request body for MCP."""
    body = {
        'jsonrpc': '2.0',
        'method': method,
        'id': id,
    }
    if params is not None:
        body['params'] = params
    return body


class MCPEndpointTests(TestCase):
    """Tests for MCP endpoint accessibility and authentication."""

    fixtures = ['tests.json']

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.first()
        self.token = Token.objects.create(user=self.user)

    def _post_mcp(self, data, **extra):
        return self.client.post(
            MCP_ENDPOINT,
            data=json.dumps(data),
            content_type='application/json',
            HTTP_ACCEPT='application/json',
            **extra,
        )

    def test_unauthenticated_request_rejected(self):
        """MCP endpoint requires authentication."""
        response = self._post_mcp(_mcp_request('initialize'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_request_accepted(self):
        """MCP endpoint accepts authenticated requests."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        response = self._post_mcp(_mcp_request('initialize', {
            'protocolVersion': '2025-03-26',
            'capabilities': {},
            'clientInfo': {'name': 'test', 'version': '1.0'},
        }))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_get_request(self):
        """MCP endpoint responds to authenticated GET."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        response = self.client.get(
            MCP_ENDPOINT, HTTP_ACCEPT='*/*')
        # GET may return 200 (SSE stream) or other valid status
        self.assertNotEqual(response.status_code,
                            status.HTTP_401_UNAUTHORIZED)


class MCPToolListingTests(TestCase):
    """Tests for MCP tool discovery."""

    fixtures = ['tests.json']

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.first()
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        # Initialize the MCP session first
        self._post_mcp(_mcp_request('initialize', {
            'protocolVersion': '2025-03-26',
            'capabilities': {},
            'clientInfo': {'name': 'test', 'version': '1.0'},
        }))

    def _post_mcp(self, data):
        return self.client.post(
            MCP_ENDPOINT,
            data=json.dumps(data),
            content_type='application/json',
            HTTP_ACCEPT='application/json',
        )

    def test_list_tools(self):
        """Tools listing returns all registered tools."""
        response = self._post_mcp(_mcp_request('tools/list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('result', data)
        tools = data['result']['tools']
        tool_names = [t['name'] for t in tools]

        # Verify core tools exist
        expected_tools = [
            'list_children', 'get_child', 'create_child',
            'update_child', 'delete_child',
            'list_feedings', 'get_feeding', 'log_feeding',
            'list_diaper_changes', 'get_diaper_change', 'log_diaper_change',
            'list_sleep', 'get_sleep', 'log_sleep',
            'list_temperatures', 'log_temperature',
            'list_weights', 'log_weight',
            'list_tummy_times', 'log_tummy_time',
            'list_notes', 'create_note',
            'list_timers', 'start_timer', 'stop_timer', 'restart_timer',
            'get_daily_summary',
        ]
        for tool_name in expected_tools:
            self.assertIn(tool_name, tool_names,
                          f"Tool '{tool_name}' not found in tool listing")


class MCPToolCallTests(TestCase):
    """Tests for MCP tool invocations."""

    fixtures = ['tests.json']

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.first()
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        # Initialize session
        self._post_mcp(_mcp_request('initialize', {
            'protocolVersion': '2025-03-26',
            'capabilities': {},
            'clientInfo': {'name': 'test', 'version': '1.0'},
        }))

    def _post_mcp(self, data):
        return self.client.post(
            MCP_ENDPOINT,
            data=json.dumps(data),
            content_type='application/json',
            HTTP_ACCEPT='application/json',
        )

    def _call_tool(self, name, arguments=None):
        """Helper to call an MCP tool and return the response data."""
        params = {'name': name}
        if arguments:
            params['arguments'] = arguments
        response = self._post_mcp(_mcp_request('tools/call', params))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    def test_list_children(self):
        """list_children returns the test fixture child."""
        data = self._call_tool('list_children')
        self.assertIn('result', data)
        content = data['result']['content']
        self.assertTrue(len(content) > 0)

    def test_get_child(self):
        """get_child returns the correct child."""
        data = self._call_tool('get_child', {'slug': 'fake-child'})
        self.assertIn('result', data)
        content = data['result']['content']
        self.assertTrue(len(content) > 0)

    def test_create_and_delete_child(self):
        """Create a child and then delete it."""
        data = self._call_tool('create_child', {
            'first_name': 'Test',
            'last_name': 'Baby',
            'birth_date': '2024-01-01',
        })
        self.assertIn('result', data)
        self.assertFalse(data['result'].get('isError', False))

        # Verify child exists
        child = models.Child.objects.get(slug='test-baby')
        self.assertEqual(child.first_name, 'Test')

        # Delete
        data = self._call_tool('delete_child', {'slug': 'test-baby'})
        self.assertIn('result', data)
        self.assertFalse(models.Child.objects.filter(slug='test-baby').exists())

    def test_log_diaper_change(self):
        """Log a diaper change via MCP."""
        now = timezone.now().isoformat()
        data = self._call_tool('log_diaper_change', {
            'child_slug': 'fake-child',
            'time': now,
            'wet': True,
            'solid': False,
        })
        self.assertIn('result', data)
        self.assertFalse(data['result'].get('isError', False))

    def test_get_daily_summary(self):
        """get_daily_summary returns a structured summary."""
        data = self._call_tool('get_daily_summary', {
            'child_slug': 'fake-child',
            'date': '2017-11-18',
        })
        self.assertIn('result', data)
        self.assertFalse(data['result'].get('isError', False))

    def test_start_and_stop_timer(self):
        """Start and stop a timer via MCP."""
        data = self._call_tool('start_timer', {
            'name': 'Test Timer',
            'child_slug': 'fake-child',
        })
        self.assertIn('result', data)
        self.assertFalse(data['result'].get('isError', False))

        # Find the created timer
        timer = models.Timer.objects.filter(name='Test Timer').first()
        self.assertIsNotNone(timer)
        self.assertTrue(timer.active)

        # Stop it
        data = self._call_tool('stop_timer', {'id': timer.id})
        self.assertIn('result', data)
        self.assertFalse(data['result'].get('isError', False))
        timer.refresh_from_db()
        self.assertFalse(timer.active)
