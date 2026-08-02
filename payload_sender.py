import socket
import os

def send_payload(file_path: str, host: str, port: int = 9021, timeout: float = 8.0) -> tuple[bool, str]:
    """
    Envia um arquivo de payload (.elf ou .bin) para o PS5 via Socket TCP.
    Retorna uma tupla (sucesso: bool, mensagem: str).
    """
    if not os.path.exists(file_path):
        return False, f"Arquivo não encontrado: {file_path}"
    
    try:
        file_size = os.path.getsize(file_path)
        with open(file_path, 'rb') as f:
            data = f.read()
            
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, int(port)))
        sock.sendall(data)
        sock.close()
        return True, f"Sucesso! Sent {file_size} bytes -> {host}:{port}"
    except socket.timeout:
        return False, f"Erro de Timeout em {host}:{port}. Verifique o IP do PS5."
    except ConnectionRefusedError:
        return False, f"Conexão recusada em {host}:{port}. Verifique a porta/receiver no PS5."
    except Exception as e:
        return False, f"Erro no envio: {str(e)}"

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        h = sys.argv[1]
        p = int(sys.argv[2]) if len(sys.argv) > 3 else 9090
        f = sys.argv[3] if len(sys.argv) > 3 else sys.argv[2]
        ok, msg = send_payload(f, h, p)
        print(msg)
    else:
        print("Uso: python payload_sender.py <host> [port] <file>")