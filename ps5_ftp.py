from __future__ import annotations

import ftplib
import os
import posixpath
import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class FTPEntry:
    name: str
    path: str
    is_dir: bool
    size: int = 0
    modified: str = ""


class PS5FTPClient:
    """Small FTP client for the PS5 etaHEN FTP service (plain FTP on the LAN)."""

    def __init__(
        self,
        host: str,
        port: int = 2121,
        username: str = "anonymous",
        password: str = "anonymous",
        timeout: float = 12.0,
    ) -> None:
        self.host = host.strip()
        self.port = int(port)
        self.username = username or "anonymous"
        self.password = password or "anonymous"
        self.timeout = float(timeout)
        self.ftp: ftplib.FTP | None = None

    def connect(self) -> "PS5FTPClient":
        if not self.host:
            raise ValueError("Informe o IP do PS5.")
        if not 1 <= self.port <= 65535:
            raise ValueError("Porta FTP inválida.")

        client = ftplib.FTP()
        try:
            client.connect(self.host, self.port, timeout=self.timeout)
            client.login(self.username, self.password)
            client.set_pasv(True)
            self.ftp = client
            return self
        except Exception:
            try:
                client.close()
            except Exception:
                pass
            raise

    def close(self) -> None:
        client, self.ftp = self.ftp, None
        if client is not None:
            try:
                client.quit()
            except Exception:
                try:
                    client.close()
                except Exception:
                    pass

    def __enter__(self) -> "PS5FTPClient":
        return self.connect()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _client(self) -> ftplib.FTP:
        if self.ftp is None:
            raise RuntimeError("Conecte ao FTP antes de usar esta operação.")
        return self.ftp

    @staticmethod
    def _entry_from_list_line(line: str, current_dir: str) -> FTPEntry | None:
        line = line.rstrip("\r\n")
        if not line or line.lower().startswith("total "):
            return None

        # Unix-style LIST: permissions links owner group size month day time name
        parts = line.split(maxsplit=8)
        if len(parts) >= 9 and re.match(r"^[bcdlps-]", parts[0]):
            name = parts[8]
            if name in (".", ".."):
                return None
            try:
                size = int(parts[4])
            except ValueError:
                size = 0
            return FTPEntry(
                name=name,
                path=posixpath.join(current_dir, name),
                is_dir=parts[0].startswith("d"),
                size=size,
                modified=" ".join(parts[5:8]),
            )

        # Windows-style LIST: MM-DD-YY HH:MMPM <DIR>|size name
        match = re.match(
            r"^\s*(\d{2}-\d{2}-\d{2,4})\s+(\d{1,2}:\d{2}\s*[AP]M)\s+(<DIR>|\d+)\s+(.+)$",
            line,
            re.IGNORECASE,
        )
        if match:
            date, clock, size_or_dir, name = match.groups()
            if name in (".", ".."):
                return None
            is_dir = size_or_dir.upper() == "<DIR>"
            return FTPEntry(
                name=name,
                path=posixpath.join(current_dir, name),
                is_dir=is_dir,
                size=0 if is_dir else int(size_or_dir),
                modified=f"{date} {clock}",
            )

        return None

    def list_dir(self, remote_path: str = "/") -> list[FTPEntry]:
        client = self._client()
        previous = client.pwd()
        try:
            client.cwd(remote_path or "/")
            current = client.pwd()
            entries: list[FTPEntry] = []

            # MLSD gives reliable file types/sizes where the FTP daemon supports it.
            try:
                for name, facts in client.mlsd():
                    if name in (".", ".."):
                        continue
                    kind = facts.get("type", "").lower()
                    if kind in ("cdir", "pdir"):
                        continue
                    entries.append(
                        FTPEntry(
                            name=name,
                            path=posixpath.join(current, name),
                            is_dir=kind == "dir",
                            size=int(facts.get("size", "0") or 0),
                            modified=facts.get("modify", ""),
                        )
                    )
            except ftplib.all_errors:
                entries.clear()
                lines: list[str] = []
                try:
                    client.retrlines("LIST", lines.append)
                except ftplib.all_errors:
                    # Last fallback: NLST can still be useful on minimal FTP daemons.
                    for raw_name in client.nlst():
                        name = posixpath.basename(raw_name.rstrip("/"))
                        if name in ("", ".", ".."):
                            continue
                        is_dir = False
                        size = 0
                        try:
                            client.cwd(raw_name)
                            is_dir = True
                            client.cwd(current)
                        except ftplib.all_errors:
                            try:
                                size = int(client.size(raw_name) or 0)
                            except ftplib.all_errors:
                                pass
                        entries.append(
                            FTPEntry(name, posixpath.join(current, name), is_dir, size)
                        )
                else:
                    for line in lines:
                        entry = self._entry_from_list_line(line, current)
                        if entry:
                            entries.append(entry)

            # Avoid duplicates from servers that return both "." and aliases.
            unique: dict[str, FTPEntry] = {}
            for entry in entries:
                unique[entry.name] = entry
            return sorted(unique.values(), key=lambda item: (not item.is_dir, item.name.casefold()))
        finally:
            try:
                client.cwd(previous)
            except ftplib.all_errors:
                pass

    def download_file(self, remote_path: str, local_path: str) -> str:
        client = self._client()
        if "\r" in remote_path or "\n" in remote_path:
            raise ValueError("Caminho remoto inválido.")
        os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
        partial_path = local_path + ".part"
        try:
            with open(partial_path, "wb") as output:
                client.retrbinary(f"RETR {remote_path}", output.write, blocksize=256 * 1024)
            os.replace(partial_path, local_path)
            return local_path
        except Exception:
            try:
                os.remove(partial_path)
            except OSError:
                pass
            raise

    def read_bytes(self, remote_path: str, max_bytes: int | None = None) -> bytes:
        """Read a small FTP sidecar such as a PS5 .dat or .meta file."""
        if "\r" in remote_path or "\n" in remote_path:
            raise ValueError("Caminho remoto inválido.")
        chunks: list[bytes] = []
        total = 0

        def collect(chunk: bytes) -> None:
            nonlocal total
            if max_bytes is None:
                chunks.append(chunk)
                return
            remaining = max_bytes - total
            if remaining > 0:
                piece = chunk[:remaining]
                chunks.append(piece)
                total += len(piece)

        self._client().retrbinary(f"RETR {remote_path}", collect, blocksize=4096)
        return b"".join(chunks)
    def upload_file(self, local_path: str, remote_path: str) -> None:
        client = self._client()
        if not os.path.isfile(local_path):
            raise FileNotFoundError(local_path)
        if "\r" in remote_path or "\n" in remote_path:
            raise ValueError("Caminho remoto inválido.")
        with open(local_path, "rb") as source:
            client.storbinary(f"STOR {remote_path}", source, blocksize=256 * 1024)

    def delete_file(self, remote_path: str) -> None:
        self._client().delete(remote_path)

    def rename(self, old_path: str, new_path: str) -> None:
        self._client().rename(old_path, new_path)

    def walk_media(
        self,
        remote_root: str,
        extensions: Iterable[str],
        max_depth: int = 3,
        max_items: int = 1500,
    ) -> list[FTPEntry]:
        allowed = {ext.lower() if ext.startswith(".") else "." + ext.lower() for ext in extensions}
        stack: list[tuple[str, int]] = [(remote_root, 0)]
        visited: set[str] = set()
        found: list[FTPEntry] = []

        while stack and len(found) < max_items:
            directory, depth = stack.pop()
            normalized = posixpath.normpath(directory)
            if normalized in visited:
                continue
            visited.add(normalized)

            for entry in self.list_dir(directory):
                if entry.is_dir:
                    if depth < max_depth and entry.name not in (".", ".."):
                        stack.append((entry.path, depth + 1))
                elif posixpath.splitext(entry.name)[1].lower() in allowed:
                    found.append(entry)
                    if len(found) >= max_items:
                        break

        return sorted(found, key=lambda item: (item.modified, item.name.casefold()), reverse=True)

