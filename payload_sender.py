import os
import socket


def send_payload(
    file_path: str,
    host: str,
    port: int = 9021,
    timeout: float = 8.0,
    chunk_size: int = 1024 * 1024,
) -> tuple[bool, str]:
    """Envia o arquivo como fluxo TCP bruto para o receptor de payload do PS5.

    Não adiciona cabeçalho nem prefixo: o formato continua compatível com
    ELF loaders que esperam receber os bytes originais diretamente no socket.
    """
    if chunk_size <= 0:
        return False, "Tamanho de bloco deve ser maior que zero."
    if not os.path.isfile(file_path):
        return False, f"Arquivo não encontrado: {file_path}"

    try:
        file_size = os.path.getsize(file_path)
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            with open(file_path, "rb") as source:
                while True:
                    chunk = source.read(chunk_size)
                    if not chunk:
                        break
                    sock.sendall(chunk)
        return True, f"Sucesso! {file_size} bytes enviados para {host}:{port}"
    except socket.timeout:
        return False, f"Timeout em {host}:{port}. Verifique o IP e o receiver no PS5."
    except ConnectionRefusedError:
        return False, f"Conexão recusada em {host}:{port}. Verifique a porta/receiver no PS5."
    except OSError as exc:
        return False, f"Erro de rede/arquivo: {exc}"
    except Exception as exc:
        return False, f"Erro no envio: {exc}"


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3:
        host_arg = sys.argv[1]
        if len(sys.argv) == 3:
            port_arg = 9021
            file_arg = sys.argv[2]
        else:
            port_arg = int(sys.argv[2])
            file_arg = sys.argv[3]
        success, message = send_payload(file_arg, host_arg, port_arg)
        print(message)
        raise SystemExit(0 if success else 1)
    print("Uso: python payload_sender.py <host> [port] <file>")
