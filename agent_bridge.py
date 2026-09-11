#!/usr/bin/env python3
import argparse
import json
import os
import socket
import subprocess
from pathlib import Path

DEFAULT_SOCKET = "/run/agent-bridge/agent.sock"
DEFAULT_WORKSPACE = "/workspace"
MAX_REQUEST = 1024 * 1024
MAX_OUTPUT = 4 * 1024 * 1024


def send(sock_path: str, request: dict) -> dict:
    data = (json.dumps(request) + "\n").encode()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(sock_path)
        sock.sendall(data)
        chunks = []
        size = 0
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_OUTPUT * 2:
                raise RuntimeError("response too large")
    return json.loads(b"".join(chunks))


def safe_cwd(workspace: Path, cwd: str | None) -> Path:
    target = workspace if cwd is None else workspace / cwd
    target = target.resolve()
    try:
        target.relative_to(workspace)
    except ValueError as exc:
        raise ValueError("cwd must stay inside workspace") from exc
    if not target.is_dir():
        raise ValueError("cwd does not exist or is not a directory")
    return target


def handle(request: dict, workspace: Path, max_timeout: float) -> dict:
    op = request.get("op")
    if op == "health":
        return {"ok": True, "workspace": str(workspace)}
    if op != "exec":
        return {"ok": False, "error": "unsupported operation"}

    argv = request.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
        return {"ok": False, "error": "argv must be a non-empty string array"}

    try:
        cwd = safe_cwd(workspace, request.get("cwd"))
        timeout = min(float(request.get("timeout", max_timeout)), max_timeout)
        proc = subprocess.run(
            argv,
            cwd=cwd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
        )
        return {
            "ok": True,
            "returncode": proc.returncode,
            "stdout": proc.stdout[:MAX_OUTPUT],
            "stderr": proc.stderr[:MAX_OUTPUT],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "error": "timeout",
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


def serve(sock_path: str, workspace: str, max_timeout: float) -> None:
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise SystemExit(f"workspace does not exist: {root}")

    path = Path(sock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_socket():
        path.unlink()

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(sock_path)
        os.chmod(sock_path, 0o600)
        server.listen(16)
        try:
            while True:
                conn, _ = server.accept()
                with conn:
                    raw = b""
                    while b"\n" not in raw and len(raw) <= MAX_REQUEST:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        raw += chunk
                    try:
                        if len(raw) > MAX_REQUEST:
                            raise ValueError("request too large")
                        request = json.loads(raw.split(b"\n", 1)[0])
                        response = handle(request, root, max_timeout)
                    except (ValueError, json.JSONDecodeError) as exc:
                        response = {"ok": False, "error": str(exc)}
                    conn.sendall(json.dumps(response).encode())
        finally:
            path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-bridge")
    parser.add_argument("--socket", default=DEFAULT_SOCKET)
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    p_serve.add_argument("--max-timeout", type=float, default=60.0)

    sub.add_parser("health")

    p_exec = sub.add_parser("exec")
    p_exec.add_argument("--cwd")
    p_exec.add_argument("--timeout", type=float, default=60.0)
    p_exec.add_argument("argv", nargs=argparse.REMAINDER)

    args = parser.parse_args()
    if args.command == "serve":
        serve(args.socket, args.workspace, args.max_timeout)
        return

    request = {"op": args.command}
    if args.command == "exec":
        argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
        if not argv:
            parser.error("exec requires a command")
        request.update(argv=argv, cwd=args.cwd, timeout=args.timeout)

    response = send(args.socket, request)
    if args.command == "health":
        print(json.dumps(response, indent=2))
        raise SystemExit(0 if response.get("ok") else 1)

    if response.get("stdout"):
        print(response["stdout"], end="")
    if response.get("stderr"):
        print(response["stderr"], end="", file=__import__("sys").stderr)
    if not response.get("ok"):
        print(response.get("error", "bridge error"), file=__import__("sys").stderr)
        raise SystemExit(125)
    raise SystemExit(response.get("returncode", 0))


if __name__ == "__main__":
    main()
