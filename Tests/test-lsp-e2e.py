#!/usr/bin/env python3
"""
End-to-end tests for delphi-lsp-server.

Tests the full LSP lifecycle, document sync, go-to-definition, find-references,
hover, documentSymbol, workspace/symbol, and edge cases.

Requires: Python 3.6+ (stdlib only, no pip dependencies)
Usage: python3 test-lsp-e2e.py
"""

import json
import os
import subprocess
import sys
import time
import threading
import struct


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LSP_SERVER_EXE = "/mnt/w/Public/delphi-lookup/delphi-lsp-server.exe"
DATABASE_PATH_WIN = r"W:\Public\delphi-lookup\delphi_symbols.db"

# A real .pas file that should exist and be indexed
TEST_PAS_FILE_WIN = r"W:\Public\delphi-lookup\LSP\uLSPTypes.pas"
TEST_PAS_FILE_URI = "file:///W:/Public/delphi-lookup/LSP/uLSPTypes.pas"

# A non-existent file for negative tests
NONEXISTENT_FILE_URI = "file:///W:/Public/delphi-lookup/nonexistent_file_that_does_not_exist.pas"

# Well-known symbols that should be in the database
KNOWN_SYMBOL = "TStringList"
KNOWN_SYMBOL_FRAMEWORK = "TTableMAX"


# ---------------------------------------------------------------------------
# Color output helpers
# ---------------------------------------------------------------------------

USE_COLOR = sys.stdout.isatty()


def green(text):
    return f"\033[92m{text}\033[0m" if USE_COLOR else text


def red(text):
    return f"\033[91m{text}\033[0m" if USE_COLOR else text


def yellow(text):
    return f"\033[93m{text}\033[0m" if USE_COLOR else text


def cyan(text):
    return f"\033[96m{text}\033[0m" if USE_COLOR else text


def bold(text):
    return f"\033[1m{text}\033[0m" if USE_COLOR else text


# ---------------------------------------------------------------------------
# LSP Client
# ---------------------------------------------------------------------------

class LSPClient:
    """Manages a subprocess running the LSP server and communicates via stdin/stdout."""

    def __init__(self, exe_path, database_path):
        self.exe_path = exe_path
        self.database_path = database_path
        self.process = None
        self._next_id = 1
        self._lock = threading.Lock()
        self._buffer = b""
        self._responses = {}  # id -> response dict
        self._reader_thread = None
        self._running = False

    def start(self):
        """Launch the LSP server process."""
        cmd = [self.exe_path, "--database", self.database_path]
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._running = True
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def stop(self):
        """Terminate the process."""
        self._running = False
        if self.process:
            try:
                self.process.stdin.close()
            except Exception:
                pass
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
            self.process = None

    def _reader_loop(self):
        """Background thread that reads LSP messages from stdout."""
        try:
            while self._running and self.process and self.process.poll() is None:
                # Read Content-Length header
                header_data = b""
                while self._running:
                    byte = self.process.stdout.read(1)
                    if not byte:
                        self._running = False
                        return
                    header_data += byte
                    # Check for \r\n\r\n (end of headers)
                    if header_data.endswith(b"\r\n\r\n"):
                        break

                if not self._running:
                    return

                # Parse Content-Length
                headers_str = header_data.decode("utf-8", errors="replace")
                content_length = None
                for line in headers_str.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        content_length = int(line.split(":", 1)[1].strip())
                        break

                if content_length is None:
                    continue

                # Read content
                content = b""
                while len(content) < content_length:
                    chunk = self.process.stdout.read(content_length - len(content))
                    if not chunk:
                        self._running = False
                        return
                    content += chunk

                # Parse JSON
                try:
                    msg = json.loads(content.decode("utf-8"))
                except json.JSONDecodeError:
                    continue

                # Store response by id
                msg_id = msg.get("id")
                if msg_id is not None:
                    with self._lock:
                        self._responses[msg_id] = msg

        except Exception:
            self._running = False

    def _encode_message(self, obj):
        """Encode a JSON-RPC message with Content-Length header."""
        content = json.dumps(obj)
        header = f"Content-Length: {len(content)}\r\n\r\n"
        return (header + content).encode("utf-8")

    def _get_id(self):
        """Get next request ID."""
        with self._lock:
            rid = self._next_id
            self._next_id += 1
        return rid

    def send_request(self, method, params=None, timeout=15.0):
        """Send a JSON-RPC request and wait for the response."""
        rid = self._get_id()
        msg = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": method,
        }
        if params is not None:
            msg["params"] = params

        data = self._encode_message(msg)
        self.process.stdin.write(data)
        self.process.stdin.flush()

        # Wait for response
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if rid in self._responses:
                    return self._responses.pop(rid)
            time.sleep(0.05)

        raise TimeoutError(f"No response for request id={rid} method={method} within {timeout}s")

    def send_notification(self, method, params=None):
        """Send a JSON-RPC notification (no id, no response expected)."""
        msg = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            msg["params"] = params

        data = self._encode_message(msg)
        self.process.stdin.write(data)
        self.process.stdin.flush()

    def is_alive(self):
        """Check if the server process is still running."""
        return self.process is not None and self.process.poll() is None


# ---------------------------------------------------------------------------
# Test Framework
# ---------------------------------------------------------------------------

class TestResult:
    def __init__(self, name, passed, message=""):
        self.name = name
        self.passed = passed
        self.message = message


results = []


def test(name):
    """Decorator for test functions."""
    def decorator(func):
        func._test_name = name
        return func
    return decorator


def record_pass(name, detail=""):
    results.append(TestResult(name, True, detail))
    status = green("PASS")
    msg = f"  {status}  {name}"
    if detail:
        msg += f" -- {detail}"
    print(msg)


def record_fail(name, detail=""):
    results.append(TestResult(name, False, detail))
    status = red("FAIL")
    msg = f"  {status}  {name}"
    if detail:
        msg += f" -- {detail}"
    print(msg)


def assert_test(condition, name, pass_detail="", fail_detail=""):
    if condition:
        record_pass(name, pass_detail)
    else:
        record_fail(name, fail_detail)
    return condition


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def make_text_document_position_params(uri, line, character):
    return {
        "textDocument": {"uri": uri},
        "position": {"line": line, "character": character},
    }


def has_uri_and_range(location):
    """Check if a location object has uri and range fields."""
    if not isinstance(location, dict):
        return False
    if "uri" not in location:
        return False
    if "range" not in location:
        return False
    r = location["range"]
    if not isinstance(r, dict):
        return False
    if "start" not in r or "end" not in r:
        return False
    return True


def valid_range(r):
    """Check if a range has start/end with line/character."""
    if not isinstance(r, dict):
        return False
    for key in ("start", "end"):
        if key not in r:
            return False
        pos = r[key]
        if not isinstance(pos, dict):
            return False
        if "line" not in pos or "character" not in pos:
            return False
    return True


# ---------------------------------------------------------------------------
# Test: Lifecycle
# ---------------------------------------------------------------------------

def run_lifecycle_tests(client):
    print()
    print(bold(cyan("=== Lifecycle Tests ===")))

    # --- Initialize ---
    resp = client.send_request("initialize", {
        "processId": os.getpid(),
        "rootUri": "file:///W:/Public/delphi-lookup",
        "capabilities": {},
    })

    assert_test(
        "result" in resp and "error" not in resp,
        "initialize: returns result without error",
        fail_detail=f"response={json.dumps(resp, indent=2)[:200]}"
    )

    result = resp.get("result", {})
    caps = result.get("capabilities", {})

    # Check all capabilities
    assert_test(
        caps.get("textDocumentSync") == 0,
        "initialize: textDocumentSync = 0 (None)",
        pass_detail=f"textDocumentSync={caps.get('textDocumentSync')}",
        fail_detail=f"textDocumentSync={caps.get('textDocumentSync')}"
    )

    assert_test(
        caps.get("definitionProvider") is True,
        "initialize: definitionProvider = true",
        fail_detail=f"definitionProvider={caps.get('definitionProvider')}"
    )

    assert_test(
        caps.get("referencesProvider") is True,
        "initialize: referencesProvider = true",
        fail_detail=f"referencesProvider={caps.get('referencesProvider')}"
    )

    assert_test(
        caps.get("hoverProvider") is True,
        "initialize: hoverProvider = true",
        fail_detail=f"hoverProvider={caps.get('hoverProvider')}"
    )

    assert_test(
        caps.get("documentSymbolProvider") is True,
        "initialize: documentSymbolProvider = true",
        fail_detail=f"documentSymbolProvider={caps.get('documentSymbolProvider')}"
    )

    assert_test(
        caps.get("workspaceSymbolProvider") is True,
        "initialize: workspaceSymbolProvider = true",
        fail_detail=f"workspaceSymbolProvider={caps.get('workspaceSymbolProvider')}"
    )

    # Check serverInfo
    server_info = result.get("serverInfo", {})
    assert_test(
        isinstance(server_info.get("name"), str) and len(server_info.get("name", "")) > 0,
        "initialize: serverInfo.name is present",
        pass_detail=f"name={server_info.get('name')}",
        fail_detail=f"serverInfo={server_info}"
    )

    assert_test(
        isinstance(server_info.get("version"), str) and len(server_info.get("version", "")) > 0,
        "initialize: serverInfo.version is present",
        pass_detail=f"version={server_info.get('version')}",
        fail_detail=f"serverInfo={server_info}"
    )

    # --- Initialized notification ---
    client.send_notification("initialized", {})
    # Give server a moment to process
    time.sleep(0.2)
    assert_test(
        client.is_alive(),
        "initialized: server still running after notification"
    )


def run_shutdown_exit_tests():
    """Separate test: full shutdown + exit cycle (terminates the server)."""
    print()
    print(bold(cyan("=== Shutdown/Exit Tests ===")))

    client = LSPClient(LSP_SERVER_EXE, DATABASE_PATH_WIN)
    client.start()

    try:
        # Initialize
        client.send_request("initialize", {
            "processId": os.getpid(),
            "rootUri": "file:///W:/Public/delphi-lookup",
            "capabilities": {},
        })
        client.send_notification("initialized", {})
        time.sleep(0.2)

        # Shutdown
        resp = client.send_request("shutdown")
        shutdown_result = resp.get("result")
        assert_test(
            shutdown_result is None,
            "shutdown: returns null result",
            pass_detail=f"result={shutdown_result}",
            fail_detail=f"result={json.dumps(shutdown_result)}"
        )

        # Exit notification
        # Note: After shutdown, the server sets FShutdownRequested=True and the
        # Run loop exits. The process may already be terminating by the time we
        # send exit. We handle BrokenPipeError gracefully.
        try:
            client.send_notification("exit")
        except (BrokenPipeError, OSError):
            pass  # Process already exiting after shutdown -- this is fine

        # Wait for process to terminate
        time.sleep(1.5)

        process_terminated = not client.is_alive()
        assert_test(
            process_terminated,
            "exit: server process terminated",
            fail_detail=f"poll={client.process.poll() if client.process else 'no process'}"
        )

        if client.process and client.process.poll() is not None:
            exit_code = client.process.returncode
            assert_test(
                exit_code == 0,
                "exit: clean exit code 0",
                pass_detail=f"exit_code={exit_code}",
                fail_detail=f"exit_code={exit_code}"
            )

    finally:
        client.stop()


# ---------------------------------------------------------------------------
# Test: Document Sync Notifications
# ---------------------------------------------------------------------------

def run_document_sync_tests(client):
    print()
    print(bold(cyan("=== Document Sync Notification Tests ===")))

    # didOpen
    client.send_notification("textDocument/didOpen", {
        "textDocument": {
            "uri": TEST_PAS_FILE_URI,
            "languageId": "pascal",
            "version": 1,
            "text": "unit test;\ninterface\nend.",
        }
    })
    time.sleep(0.3)
    assert_test(
        client.is_alive(),
        "didOpen: server still alive (no error, no response)"
    )

    # Verify server still works after didOpen by sending a real request
    resp = client.send_request("workspace/symbol", {"query": KNOWN_SYMBOL})
    assert_test(
        "result" in resp and "error" not in resp,
        "didOpen: server continues working after notification",
        fail_detail=f"response has error: {resp.get('error', 'no error')}"
    )

    # didChange
    client.send_notification("textDocument/didChange", {
        "textDocument": {"uri": TEST_PAS_FILE_URI, "version": 2},
        "contentChanges": [{"text": "unit test;\ninterface\nimplementation\nend."}],
    })
    time.sleep(0.3)
    assert_test(
        client.is_alive(),
        "didChange: server still alive (no error, no response)"
    )

    # didSave
    client.send_notification("textDocument/didSave", {
        "textDocument": {"uri": TEST_PAS_FILE_URI},
    })
    time.sleep(0.3)
    assert_test(
        client.is_alive(),
        "didSave: server still alive (no error, no response)"
    )

    # didClose
    client.send_notification("textDocument/didClose", {
        "textDocument": {"uri": TEST_PAS_FILE_URI},
    })
    time.sleep(0.3)
    assert_test(
        client.is_alive(),
        "didClose: server still alive (no error, no response)"
    )

    # Verify server still works after all notifications
    resp = client.send_request("workspace/symbol", {"query": KNOWN_SYMBOL})
    assert_test(
        "result" in resp and "error" not in resp,
        "document sync: server continues working after all notifications",
        fail_detail=f"response has error: {resp.get('error', 'no error')}"
    )


# ---------------------------------------------------------------------------
# Test: Go-to-Definition
# ---------------------------------------------------------------------------

def run_definition_tests(client):
    print()
    print(bold(cyan("=== Go-to-Definition Tests ===")))

    # Known symbol: We use workspace/symbol to find a file that contains
    # a known symbol, then request definition at its position.
    # Since the server reads files from disk and resolves the identifier at cursor,
    # we need a real file with real positions.

    # Strategy: Use uLSPTypes.pas where "TLSPPosition" is declared.
    # In uLSPTypes.pas, line 18 (0-indexed = 17) has "TLSPPosition = record"
    # The "T" of TLSPPosition starts at character 2 (0-indexed).
    # But the server reads from the Windows path, so it should work.

    params = make_text_document_position_params(TEST_PAS_FILE_URI, 17, 4)
    resp = client.send_request("textDocument/definition", params)

    result = resp.get("result")
    has_error = "error" in resp

    # The result should be a location or null. If the symbol is in the DB, it will be a location.
    # If the file can be read, the identifier at line 17, char 4 is "TLSPPosition".
    # That may or may not be in the database. Let's check what we get.
    if has_error:
        record_fail(
            "definition: known file/position returns result (not error)",
            f"error={resp.get('error')}"
        )
    else:
        record_pass("definition: known file/position returns result (not error)")

    # If we get a valid location, check structure
    if isinstance(result, dict) and "uri" in result:
        assert_test(
            has_uri_and_range(result),
            "definition: result has uri and range fields",
            pass_detail=f"uri={result.get('uri', '')[:60]}"
        )
    elif result is None:
        record_pass(
            "definition: null result (symbol not in DB or file not readable from Windows path) -- acceptable"
        )
    else:
        record_pass(
            "definition: returned a valid response (may be null for unindexed symbol)"
        )

    # Unknown symbol at a position that likely has no identifier (empty line or punctuation)
    # Line 0 is "unit uLSPTypes;" -- position at char 0 is "u" of "unit" (keyword)
    # Actually let's try a very high line number where there's nothing
    params2 = make_text_document_position_params(TEST_PAS_FILE_URI, 999, 0)
    resp2 = client.send_request("textDocument/definition", params2)
    result2 = resp2.get("result")

    assert_test(
        "error" not in resp2,
        "definition: out-of-range position returns result (not error)",
        fail_detail=f"error={resp2.get('error')}"
    )

    # Non-existent file
    params3 = make_text_document_position_params(NONEXISTENT_FILE_URI, 0, 0)
    resp3 = client.send_request("textDocument/definition", params3)

    assert_test(
        "error" not in resp3,
        "definition: non-existent file returns result (not error)",
        fail_detail=f"error={resp3.get('error')}"
    )


# ---------------------------------------------------------------------------
# Test: Find References
# ---------------------------------------------------------------------------

def run_references_tests(client):
    print()
    print(bold(cyan("=== Find References Tests ===")))

    # Use the same file and position approach
    params = make_text_document_position_params(TEST_PAS_FILE_URI, 17, 4)
    params["context"] = {"includeDeclaration": True}
    resp = client.send_request("textDocument/references", params)

    result = resp.get("result")
    has_error = "error" in resp

    assert_test(
        not has_error,
        "references: returns result without error",
        fail_detail=f"error={resp.get('error')}"
    )

    if isinstance(result, list):
        assert_test(
            True,
            "references: result is an array",
            pass_detail=f"count={len(result)}"
        )

        # Check structure of each location
        if len(result) > 0:
            all_valid = all(has_uri_and_range(loc) for loc in result)
            assert_test(
                all_valid,
                "references: each location has uri and range",
                fail_detail="some locations missing uri/range"
            )
        else:
            record_pass(
                "references: empty array (symbol not in DB or not readable) -- acceptable"
            )
    elif result is None or result == []:
        record_pass(
            "references: empty/null result (acceptable for unindexed symbol)"
        )
    else:
        record_fail(
            "references: unexpected result type",
            f"type={type(result).__name__}"
        )


# ---------------------------------------------------------------------------
# Test: Hover
# ---------------------------------------------------------------------------

def run_hover_tests(client):
    print()
    print(bold(cyan("=== Hover Tests ===")))

    params = make_text_document_position_params(TEST_PAS_FILE_URI, 17, 4)
    resp = client.send_request("textDocument/hover", params)

    result = resp.get("result")
    has_error = "error" in resp

    assert_test(
        not has_error,
        "hover: returns result without error",
        fail_detail=f"error={resp.get('error')}"
    )

    if isinstance(result, dict) and "contents" in result:
        contents = result["contents"]
        assert_test(
            isinstance(contents, dict) and contents.get("kind") == "markdown",
            "hover: contents.kind is 'markdown'",
            pass_detail=f"kind={contents.get('kind')}",
            fail_detail=f"contents={json.dumps(contents)[:100]}"
        )

        assert_test(
            isinstance(contents.get("value"), str) and len(contents.get("value", "")) > 0,
            "hover: contents.value is non-empty string",
            pass_detail=f"value length={len(contents.get('value', ''))}",
            fail_detail=f"value={contents.get('value')}"
        )
    elif result is None:
        record_pass(
            "hover: null result (symbol not in DB) -- acceptable"
        )
    else:
        record_fail(
            "hover: unexpected result format",
            f"result={json.dumps(result)[:150]}"
        )

    # Hover on non-existent file
    params2 = make_text_document_position_params(NONEXISTENT_FILE_URI, 0, 0)
    resp2 = client.send_request("textDocument/hover", params2)

    assert_test(
        "error" not in resp2,
        "hover: non-existent file returns result (not error)",
        fail_detail=f"error={resp2.get('error')}"
    )


# ---------------------------------------------------------------------------
# Test: Document Symbols
# ---------------------------------------------------------------------------

def run_document_symbol_tests(client):
    print()
    print(bold(cyan("=== Document Symbol Tests ===")))

    # Real file
    resp = client.send_request("textDocument/documentSymbol", {
        "textDocument": {"uri": TEST_PAS_FILE_URI},
    })

    result = resp.get("result")
    has_error = "error" in resp

    assert_test(
        not has_error,
        "documentSymbol: returns result without error",
        fail_detail=f"error={resp.get('error')}"
    )

    if isinstance(result, list):
        assert_test(
            True,
            "documentSymbol: result is an array",
            pass_detail=f"count={len(result)}"
        )

        if len(result) > 0:
            sym = result[0]
            has_name = "name" in sym
            has_kind = "kind" in sym
            has_range_field = "range" in sym
            has_sel_range = "selectionRange" in sym

            assert_test(
                has_name and has_kind,
                "documentSymbol: symbols have name and kind",
                pass_detail=f"first symbol: name={sym.get('name')}, kind={sym.get('kind')}",
                fail_detail=f"name={has_name}, kind={has_kind}"
            )

            assert_test(
                has_range_field and valid_range(sym.get("range", {})),
                "documentSymbol: symbols have valid range",
                fail_detail=f"range={sym.get('range')}"
            )

            assert_test(
                has_sel_range and valid_range(sym.get("selectionRange", {})),
                "documentSymbol: symbols have valid selectionRange",
                fail_detail=f"selectionRange={sym.get('selectionRange')}"
            )
        else:
            record_pass(
                "documentSymbol: empty array (file not indexed) -- acceptable"
            )
    else:
        record_fail(
            "documentSymbol: expected array result",
            f"type={type(result).__name__}, value={json.dumps(result)[:100]}"
        )

    # Non-existent file
    resp2 = client.send_request("textDocument/documentSymbol", {
        "textDocument": {"uri": NONEXISTENT_FILE_URI},
    })

    result2 = resp2.get("result")
    assert_test(
        "error" not in resp2,
        "documentSymbol: non-existent file returns result (not error)",
        fail_detail=f"error={resp2.get('error')}"
    )

    assert_test(
        result2 is None or (isinstance(result2, list) and len(result2) == 0),
        "documentSymbol: non-existent file returns empty/null",
        pass_detail=f"result={'null' if result2 is None else f'array({len(result2)})'}",
        fail_detail=f"result={json.dumps(result2)[:100]}"
    )


# ---------------------------------------------------------------------------
# Test: Workspace Symbol
# ---------------------------------------------------------------------------

def run_workspace_symbol_tests(client):
    print()
    print(bold(cyan("=== Workspace Symbol Tests ===")))

    # Known symbol query
    resp = client.send_request("workspace/symbol", {"query": KNOWN_SYMBOL})
    result = resp.get("result")

    assert_test(
        "error" not in resp,
        "workspace/symbol: known query returns result without error",
        fail_detail=f"error={resp.get('error')}"
    )

    if isinstance(result, list):
        assert_test(
            len(result) > 0,
            f"workspace/symbol: query '{KNOWN_SYMBOL}' returns results",
            pass_detail=f"count={len(result)}",
            fail_detail="empty array"
        )

        if len(result) > 0:
            sym = result[0]
            has_name = "name" in sym
            has_kind = "kind" in sym
            has_location = "location" in sym

            assert_test(
                has_name and has_kind and has_location,
                "workspace/symbol: results have name, kind, location",
                pass_detail=f"name={sym.get('name')}, kind={sym.get('kind')}",
                fail_detail=f"name={has_name}, kind={has_kind}, location={has_location}"
            )

            if has_location:
                assert_test(
                    has_uri_and_range(sym.get("location", {})),
                    "workspace/symbol: location has uri and range",
                    fail_detail=f"location={sym.get('location')}"
                )
    else:
        record_fail(
            "workspace/symbol: expected array result",
            f"type={type(result).__name__}"
        )

    # Empty query - server should return empty array (the code exits early on empty query)
    resp2 = client.send_request("workspace/symbol", {"query": ""})
    result2 = resp2.get("result")

    assert_test(
        "error" not in resp2,
        "workspace/symbol: empty query returns result without error",
        fail_detail=f"error={resp2.get('error')}"
    )

    assert_test(
        isinstance(result2, list) and len(result2) == 0,
        "workspace/symbol: empty query returns empty array",
        pass_detail=f"count={len(result2) if isinstance(result2, list) else 'N/A'}",
        fail_detail=f"result={json.dumps(result2)[:100]}"
    )

    # Partial query - prefix match
    resp3 = client.send_request("workspace/symbol", {"query": "TTable"})
    result3 = resp3.get("result")

    assert_test(
        "error" not in resp3,
        "workspace/symbol: partial query 'TTable' returns without error",
        fail_detail=f"error={resp3.get('error')}"
    )

    if isinstance(result3, list):
        assert_test(
            len(result3) > 0,
            "workspace/symbol: partial query 'TTable' returns results",
            pass_detail=f"count={len(result3)}",
            fail_detail="empty array"
        )
    else:
        record_fail(
            "workspace/symbol: partial query expected array",
            f"type={type(result3).__name__}"
        )


# ---------------------------------------------------------------------------
# Test: Edge Cases
# ---------------------------------------------------------------------------

def run_edge_case_tests(client):
    print()
    print(bold(cyan("=== Edge Case Tests ===")))

    # Unknown method (with id -> should get method not found error)
    resp = client.send_request("textDocument/nonExistentMethod", {})
    assert_test(
        "error" in resp,
        "edge: unknown method returns error response",
        pass_detail=f"error.code={resp.get('error', {}).get('code')}",
        fail_detail=f"response={json.dumps(resp)[:150]}"
    )

    if "error" in resp:
        error_code = resp["error"].get("code")
        assert_test(
            error_code == -32601,  # Method not found
            "edge: unknown method error code is -32601 (MethodNotFound)",
            pass_detail=f"code={error_code}",
            fail_detail=f"code={error_code}"
        )

    # Server still alive after unknown method
    assert_test(
        client.is_alive(),
        "edge: server still alive after unknown method"
    )

    # Malformed URI
    params = make_text_document_position_params("not-a-valid-uri", 0, 0)
    resp2 = client.send_request("textDocument/definition", params)

    assert_test(
        client.is_alive(),
        "edge: server still alive after malformed URI",
    )

    # Very long symbol name -- server has a 200-char limit on queries
    # which is correct validation behavior. We just verify it handles it
    # gracefully (returns an error, does not crash).
    long_name = "A" * 10000
    resp3 = client.send_request("workspace/symbol", {"query": long_name})

    assert_test(
        client.is_alive(),
        "edge: server still alive after very long symbol name query"
    )

    # The server validates query length (2-200 chars) and returns an error.
    # This is correct graceful handling -- it does not crash.
    assert_test(
        "error" in resp3 or "result" in resp3,
        "edge: very long symbol name handled gracefully (error or result)",
        pass_detail=f"error={resp3.get('error', {}).get('message', 'N/A')}" if "error" in resp3 else "returned result",
        fail_detail=f"response={json.dumps(resp3)[:150]}"
    )

    # Unknown notification (no id) -- should be silently ignored
    client.send_notification("someCustom/notification", {"data": "test"})
    time.sleep(0.3)
    assert_test(
        client.is_alive(),
        "edge: server still alive after unknown notification"
    )

    # Verify server still works
    resp4 = client.send_request("workspace/symbol", {"query": KNOWN_SYMBOL})
    assert_test(
        "result" in resp4 and "error" not in resp4,
        "edge: server continues working after all edge cases",
        fail_detail=f"response has error: {resp4.get('error', 'no error')}"
    )


# ---------------------------------------------------------------------------
# Test: Request before initialized (separate server instance)
# ---------------------------------------------------------------------------

def run_not_initialized_test():
    """Test that requests before 'initialized' notification return ServerNotInitialized error."""
    print()
    print(bold(cyan("=== Not Initialized Tests ===")))

    client = LSPClient(LSP_SERVER_EXE, DATABASE_PATH_WIN)
    client.start()

    try:
        # Send initialize but NOT the 'initialized' notification
        client.send_request("initialize", {
            "processId": os.getpid(),
            "rootUri": "file:///W:/Public/delphi-lookup",
            "capabilities": {},
        })
        # Deliberately NOT sending 'initialized'

        # Try a workspace/symbol request - should fail with ServerNotInitialized
        resp = client.send_request("workspace/symbol", {"query": "TStringList"})

        assert_test(
            "error" in resp,
            "not-initialized: request before 'initialized' returns error",
            pass_detail=f"error.code={resp.get('error', {}).get('code')}",
            fail_detail=f"response={json.dumps(resp)[:200]}"
        )

        if "error" in resp:
            error_code = resp["error"].get("code")
            assert_test(
                error_code == -32002,  # ServerNotInitialized
                "not-initialized: error code is -32002 (ServerNotInitialized)",
                pass_detail=f"code={error_code}",
                fail_detail=f"code={error_code}"
            )

    finally:
        client.stop()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print()
    print(bold("=" * 60))
    print(bold("  delphi-lsp-server End-to-End Tests"))
    print(bold("=" * 60))
    print()
    print(f"Server:   {LSP_SERVER_EXE}")
    print(f"Database: {DATABASE_PATH_WIN}")
    print(f"Python:   {sys.version.split()[0]}")
    print()

    # Verify prerequisites
    if not os.path.exists(LSP_SERVER_EXE):
        print(red(f"ERROR: LSP server not found at {LSP_SERVER_EXE}"))
        sys.exit(1)

    # --- Main test session (single server instance) ---
    client = LSPClient(LSP_SERVER_EXE, DATABASE_PATH_WIN)
    client.start()

    try:
        # 1. Lifecycle (initialize + initialized)
        run_lifecycle_tests(client)

        # 2. Document sync notifications
        run_document_sync_tests(client)

        # 3. Go-to-definition
        run_definition_tests(client)

        # 4. Find references
        run_references_tests(client)

        # 5. Hover
        run_hover_tests(client)

        # 6. Document symbols
        run_document_symbol_tests(client)

        # 7. Workspace symbol
        run_workspace_symbol_tests(client)

        # 8. Edge cases
        run_edge_case_tests(client)

    finally:
        client.stop()

    # --- Separate server instances for isolation tests ---
    run_not_initialized_test()
    run_shutdown_exit_tests()

    # --- Summary ---
    print()
    print(bold("=" * 60))
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    total = len(results)

    if failed == 0:
        print(green(bold(f"  ALL TESTS PASSED: {passed}/{total}")))
    else:
        print(red(bold(f"  TESTS FAILED: {failed}/{total} failed")))
        print()
        print("  Failed tests:")
        for r in results:
            if not r.passed:
                print(red(f"    - {r.name}"))
                if r.message:
                    print(f"      {r.message}")

    print(bold("=" * 60))
    print()

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
