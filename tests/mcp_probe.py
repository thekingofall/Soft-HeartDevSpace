"""Local OAuth and read-only MCP probe for the disposable integration instance."""
import base64
import hashlib
import http.client
import json
import secrets
from urllib.parse import urlencode, urlsplit, parse_qs


class Probe:
    def __init__(self, manager):
        self.manager = manager
        self.token = ""
        self.session = ""
        self.number = 0

    def request(self, path, body, form=False):
        connection = http.client.HTTPConnection("127.0.0.1", self.manager.settings["port"], timeout=30)
        headers = {"Content-Type": "application/x-www-form-urlencoded" if form else "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if self.session:
            headers["Mcp-Session-Id"] = self.session
            headers["MCP-Protocol-Version"] = "2025-03-26"
        connection.request("POST", path, urlencode(body) if form else json.dumps(body), headers)
        response = connection.getresponse()
        status, response_headers, content = response.status, dict(response.getheaders()), response.read().decode()
        connection.close()
        if status >= 400:
            raise AssertionError(f"Local probe failed at {path}: HTTP {status}")
        return response_headers, content

    def authorize(self):
        redirect = "http://127.0.0.1:18080/callback"
        _, body = self.request("/register", {"client_name": "Soft-HeartDevSpace integration test",
                "redirect_uris": [redirect], "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]})
        client = json.loads(body)["client_id"]
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        resource = "https://" + self.manager.settings["domain"] + "/mcp"
        headers, _ = self.request("/authorize", {"client_id": client, "redirect_uri": redirect,
            "response_type": "code", "code_challenge": challenge, "code_challenge_method": "S256",
            "scope": "devspace", "resource": resource, "owner_token": self.manager.owner_password()}, True)
        location = next(value for key, value in headers.items() if key.lower() == "location")
        code = parse_qs(urlsplit(location).query)["code"][0]
        _, body = self.request("/token", {"client_id": client, "grant_type": "authorization_code",
            "redirect_uri": redirect, "code": code, "code_verifier": verifier, "resource": resource}, True)
        self.token = json.loads(body)["access_token"]

    def rpc(self, method, params):
        self.number += 1
        headers, body = self.request("/mcp", {"jsonrpc": "2.0", "id": self.number, "method": method, "params": params})
        for key, value in headers.items():
            if key.lower() == "mcp-session-id":
                self.session = value
        if body.startswith("event:") or body.startswith("data:"):
            messages = [json.loads(line[5:].strip()) for line in body.splitlines() if line.startswith("data:")]
            result = next(message for message in messages if message.get("id") == self.number)
        else:
            result = json.loads(body)
        assert "error" not in result and not result.get("result", {}).get("isError"), method
        return result["result"]

    def read_fixture(self, project):
        self.session = ""
        self.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                    "clientInfo": {"name": "integration-probe", "version": "1"}})
        self.request("/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = self.rpc("tools/list", {})["tools"]
        read_name = next(tool["name"] for tool in tools if tool.get("title") == "Read file" or tool["name"] in ("read", "read_file"))
        opened = self.rpc("tools/call", {"name": "open_workspace", "arguments": {"path": str(project)}})
        workspace = opened["structuredContent"]["workspaceId"]
        result = self.rpc("tools/call", {"name": read_name, "arguments": {"workspaceId": workspace, "path": "hello.txt"}})
        assert "heartbeat integration fixture" in json.dumps(result)
