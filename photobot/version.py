"""Deployed-version info.

update.sh writes DATA_DIR/deploy_info (key=value lines: commit, build,
subject, deployed_at) right before restarting the container. `build` is the
commit count on main — an automatic, monotonically increasing number, so every
merged PR bumps it without anyone maintaining a version file. When running
locally the file simply doesn't exist and everything degrades to silence.
"""

from . import config


def read_deploy_info() -> dict[str, str]:
    path = config.DATA_DIR / "deploy_info"
    if not path.exists():
        return {}
    info: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            info[key.strip()] = value.strip()
    return info


def describe(info: dict[str, str]) -> str:
    build = info.get("build", "?")
    commit = info.get("commit", "?")
    subject = info.get("subject", "")
    return f"build {build} ({commit}) — {subject}"
