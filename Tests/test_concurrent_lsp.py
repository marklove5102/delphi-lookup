#!/usr/bin/env python3
"""
Test: Two concurrent LSP server instances without "database is locked" errors.

Launches TWO delphi-lsp-server.exe instances simultaneously, sends LSP
initialize + initialized + workspace/symbol requests to BOTH, and verifies
both return results without database locking errors.
"""

import subprocess
import json
import sys
import time
import threading
import os

LSP_SERVER = "/mnt/w/Public/delphi-lookup/delphi-lsp-server.exe"
LSP_ARGS = ["--database", "W:\\Public\\delphi-lookup\\delphi_symbols.db"]
TIMEOUT = 30  # seconds per operation


def make_lsp_message(obj: dict) -> bytes:
    """Encode a JSON-RPC object as an LSP message with Content-Length header."""
    body = json.dumps(obj).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def read_lsp_response(proc, label: str, timeout: float = TIMEOUT) -> dict:
    """Read one LSP response from the process stdout."""
    import select

    # Read Content-Length header
    header_data = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        byte = proc.stdout.read(1)
        if byte == b"":
            raise RuntimeError(f"[{label}] EOF while reading header")
        header_data += byte
        if header_data.endswith(b"\r\n\r\n"):
            break
    else:
        raise RuntimeError(
            f"[{label}] Timeout reading header. Got so far: {header_data!r}"
        )

    # Parse Content-Length
    header_str = header_data.decode("ascii", errors="replace")
    content_length = None
    for line in header_str.split("\r\n"):
        if line.lower().startswith("content-length:"):
            content_length = int(line.split(":", 1)[1].strip())
            break

    if content_length is None:
        raise RuntimeError(
            f"[{label}] No Content-Length in header: {header_str!r}"
        )

    # Read body
    body = b""
    while len(body) < content_length:
        remaining = content_length - len(body)
        chunk = proc.stdout.read(remaining)
        if chunk == b"":
            raise RuntimeError(
                f"[{label}] EOF while reading body ({len(body)}/{content_length})"
            )
        body += chunk

    return json.loads(body.decode("utf-8"))


def run_lsp_session(instance_id: int, results: dict):
    """Run a complete LSP session: initialize, initialized, workspace/symbol query."""
    label = f"Instance-{instance_id}"
    proc = None
    try:
        # Launch the LSP server
        proc = subprocess.Popen(
            [LSP_SERVER] + LSP_ARGS,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        print(f"[{label}] Started PID={proc.pid}")

        # 1) Send initialize request
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "processId": os.getpid(),
                "capabilities": {},
                "rootUri": None,
                "clientInfo": {"name": f"test-client-{instance_id}", "version": "1.0"},
            },
        }
        proc.stdin.write(make_lsp_message(init_request))
        proc.stdin.flush()
        print(f"[{label}] Sent initialize request")

        # Read initialize response
        init_response = read_lsp_response(proc, label)
        print(f"[{label}] Got initialize response: id={init_response.get('id')}")

        if "error" in init_response:
            error_msg = json.dumps(init_response["error"])
            results[instance_id] = {
                "status": "FAIL",
                "error": f"Initialize error: {error_msg}",
            }
            return

        # 2) Send initialized notification
        initialized_notif = {
            "jsonrpc": "2.0",
            "method": "initialized",
            "params": {},
        }
        proc.stdin.write(make_lsp_message(initialized_notif))
        proc.stdin.flush()
        print(f"[{label}] Sent initialized notification")

        # Small delay to let server process the notification
        time.sleep(0.2)

        # 3) Send workspace/symbol query
        symbol_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "workspace/symbol",
            "params": {"query": "TStringList"},
        }
        proc.stdin.write(make_lsp_message(symbol_request))
        proc.stdin.flush()
        print(f"[{label}] Sent workspace/symbol query for 'TStringList'")

        # Read symbol response
        symbol_response = read_lsp_response(proc, label)
        print(
            f"[{label}] Got workspace/symbol response: id={symbol_response.get('id')}"
        )

        if "error" in symbol_response:
            error_msg = json.dumps(symbol_response["error"])
            # Check specifically for database locked
            if "locked" in error_msg.lower() or "database is locked" in error_msg.lower():
                results[instance_id] = {
                    "status": "FAIL",
                    "error": f"DATABASE LOCKED: {error_msg}",
                }
            else:
                results[instance_id] = {
                    "status": "FAIL",
                    "error": f"Symbol query error: {error_msg}",
                }
            return

        # Check results
        result_data = symbol_response.get("result", [])
        if result_data is None:
            result_data = []

        num_results = len(result_data) if isinstance(result_data, list) else 0
        print(f"[{label}] Got {num_results} symbol results")

        if num_results > 0:
            results[instance_id] = {
                "status": "PASS",
                "num_results": num_results,
            }
        else:
            results[instance_id] = {
                "status": "WARN",
                "error": "No results returned (but no error either)",
                "num_results": 0,
            }

        # 4) Send shutdown
        shutdown_request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "shutdown",
            "params": None,
        }
        proc.stdin.write(make_lsp_message(shutdown_request))
        proc.stdin.flush()

        try:
            shutdown_response = read_lsp_response(proc, label, timeout=5)
            print(f"[{label}] Shutdown response received")
        except Exception:
            print(f"[{label}] Shutdown response timeout (acceptable)")

        # Send exit notification
        exit_notif = {
            "jsonrpc": "2.0",
            "method": "exit",
            "params": None,
        }
        proc.stdin.write(make_lsp_message(exit_notif))
        proc.stdin.flush()

    except Exception as e:
        error_str = str(e)
        if "locked" in error_str.lower():
            results[instance_id] = {
                "status": "FAIL",
                "error": f"DATABASE LOCKED: {error_str}",
            }
        else:
            results[instance_id] = {
                "status": "FAIL",
                "error": error_str,
            }
    finally:
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
                proc.wait(timeout=5)
        # Read stderr for diagnostics
        if proc:
            try:
                stderr_output = proc.stderr.read().decode("utf-8", errors="replace")
                if stderr_output.strip():
                    print(f"[{label}] stderr: {stderr_output[:500]}")
                    # Check stderr for database locked too
                    if "locked" in stderr_output.lower() and instance_id in results:
                        if results[instance_id]["status"] == "PASS":
                            results[instance_id] = {
                                "status": "FAIL",
                                "error": f"DATABASE LOCKED in stderr: {stderr_output[:200]}",
                            }
            except Exception:
                pass


def main():
    print("=" * 60)
    print("Concurrent LSP Server Test")
    print("=" * 60)
    print(f"Server: {LSP_SERVER}")
    print(f"Args: {LSP_ARGS}")
    print()

    results = {}

    # Launch both sessions simultaneously
    t1 = threading.Thread(target=run_lsp_session, args=(1, results))
    t2 = threading.Thread(target=run_lsp_session, args=(2, results))

    print("Starting both LSP instances simultaneously...")
    t1.start()
    t2.start()

    # Wait for both to complete
    t1.join(timeout=60)
    t2.join(timeout=60)

    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)

    all_pass = True
    for inst_id in sorted(results.keys()):
        r = results[inst_id]
        status = r["status"]
        if status == "PASS":
            print(f"  Instance {inst_id}: PASS ({r['num_results']} results)")
        elif status == "WARN":
            print(f"  Instance {inst_id}: WARN - {r.get('error', 'unknown')}")
            # WARN is acceptable (no error, just no results)
        else:
            print(f"  Instance {inst_id}: FAIL - {r.get('error', 'unknown')}")
            all_pass = False

    if len(results) < 2:
        print("  ERROR: Not all instances reported results!")
        all_pass = False

    print()
    if all_pass:
        print("OVERALL: PASS - Both instances worked concurrently without errors")
    else:
        print("OVERALL: FAIL - Concurrency issues detected")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
