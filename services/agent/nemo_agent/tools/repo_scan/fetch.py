import asyncio
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path


class FetchError(Exception):
    pass


@asynccontextmanager
async def resolve(source: str):
    """Yield a local directory for `source`: a local path, or a shallow clone of an
    https git URL that is deleted afterwards. Nothing in the repo is ever executed."""
    if source.startswith(("http://", "https://")):
        if not source.startswith("https://"):
            raise FetchError("only https:// repository URLs are supported")
        tmp = Path(tempfile.mkdtemp(prefix="nemo-scan-"))
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", "--depth", "1", "--no-tags", "--single-branch",
                "--no-recurse-submodules",
                "-c", "core.hooksPath=NUL", "-c", "protocol.file.allow=never",
                "--", source, str(tmp / "repo"),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, err = await asyncio.wait_for(proc.communicate(), timeout=180)
            except asyncio.TimeoutError:
                proc.kill()
                raise FetchError("clone timed out after 180s")
            if proc.returncode != 0:
                raise FetchError(f"git clone failed: {err.decode(errors='ignore')[:200]}")
            yield tmp / "repo"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return

    path = Path(source).expanduser()
    if not path.is_dir():
        raise FetchError(f"not a directory: {source}")
    yield path
