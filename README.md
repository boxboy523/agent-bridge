# agent-bridge

Minimal Unix-socket bridge for sending commands into a sandbox without giving the controller direct Docker or host-shell access.

The first version intentionally has only two operations:

- `health`
- `exec` with an argv array (`shell=False`)

The server restricts `cwd` to its configured workspace and caps command runtime/output.

## Development environment

This repository uses Nix for the developer toolchain and uv for Python project state.

```sh
nix develop
uv sync --locked
uv run python -m unittest -v
```

`nix develop` creates `flake.lock` on first use if it is not present yet.

## Local smoke test

Terminal 1:

```sh
nix develop
uv run python agent_bridge.py \
  --socket /tmp/agent-bridge.sock \
  serve --workspace "$PWD"
```

Terminal 2:

```sh
nix develop
uv run python agent_bridge.py --socket /tmp/agent-bridge.sock health
uv run python agent_bridge.py --socket /tmp/agent-bridge.sock exec -- pwd
uv run python agent_bridge.py --socket /tmp/agent-bridge.sock exec -- python3 -c 'print("hello")'
```

## flake-docker smoke test

Create a host directory for the shared Unix socket:

```sh
mkdir -p "$XDG_RUNTIME_DIR/agent-bridge"
```

Assuming this repository is the current directory and `flake-docker` is already built:

```sh
export NIX_DIR=$(dirname "$(readlink -f "$(which nix)")")

docker run --rm -it \
  -v /nix:/nix:ro \
  -v agent-env:/env \
  -v agent-workspace:/workspace \
  -v "$PWD:/opt/agent-bridge:ro" \
  -v "$XDG_RUNTIME_DIR/agent-bridge:/run/agent-bridge" \
  -e NIX_DIR="$NIX_DIR" \
  flake-docker \
  python /opt/agent-bridge/agent_bridge.py serve
```

Then from the host:

```sh
uv run python agent_bridge.py \
  --socket "$XDG_RUNTIME_DIR/agent-bridge/agent.sock" \
  health

uv run python agent_bridge.py \
  --socket "$XDG_RUNTIME_DIR/agent-bridge/agent.sock" \
  exec -- pwd
```

The command is executed inside the container, with `/workspace` as the default working directory.

## Security model

`agent-bridge` is not the sandbox. The container remains the security boundary.

The host-side controller only gets access to the bridge socket. It should not receive the Docker socket, Docker group membership, or an unrestricted host shell.

The bridge server itself:

- accepts only Unix-domain socket connections
- creates the socket with mode `0600`
- executes argv directly with `shell=False`
- restricts requested working directories to the configured workspace
- limits request size, captured output, and command timeout

For a dedicated low-privilege host controller account, socket ownership/group policy can be added later without changing the protocol.
