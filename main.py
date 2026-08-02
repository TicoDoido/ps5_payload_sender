import os
import urllib.parse
import flet as ft
from flet_permission_handler import PermissionHandler, PermissionType
from payload_sender import send_payload

def resolve_android_path(raw_path: str) -> str:
    """ Resolve URIs do Android SAF (Storage Access Framework) para caminhos POSIX reais """
    if not raw_path:
        return ""
    
    decoded = urllib.parse.unquote(raw_path)
    
    if os.path.exists(decoded):
        return decoded
        
    # Formato SAF do Android: tree/primary:Download/Subfolder
    if "primary:" in decoded:
        rel_path = decoded.split("primary:")[-1].lstrip("/")
        candidate = os.path.join("/storage/emulated/0", rel_path)
        return candidate

    if "primary" in decoded and ":" in decoded:
        rel_path = decoded.split(":")[-1].lstrip("/")
        candidate = os.path.join("/storage/emulated/0", rel_path)
        return candidate

    if "/storage/emulated/0/" in decoded:
        idx = decoded.find("/storage/emulated/0/")
        return decoded[idx:]

    return decoded

def main(page: ft.Page):
    page.title = "PS5 Payload Sender"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 16
    page.spacing = 12
    page.scroll = ft.ScrollMode.AUTO

    # Handler de Permissões Android
    permission_handler = PermissionHandler()
    page.overlay.append(permission_handler)

    # Armazenamento dos Payloads carregados: list of dict {'name': str, 'path': str, 'size': int}
    payload_files = []

    # Header / AppBar
    page.appbar = ft.AppBar(
        leading=ft.Icon(ft.Icons.SPORTS_ESPORTS, color=ft.Colors.BLUE_400),
        leading_width=40,
        title=ft.Text("PS5 Payload Sender", weight=ft.FontWeight.BOLD),
        center_title=False,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
    )

    # Configuração PS5 IP e Porta
    saved_ip = page.client_storage.get("ps5_ip") or "192.168.1.100"
    saved_port = page.client_storage.get("ps5_port") or "9021"
    saved_folder = page.client_storage.get("payload_folder") or "/storage/emulated/0/Download"

    ip_input = ft.TextField(
        label="IP do PS5",
        value=saved_ip,
        hint_text="Ex: 192.168.1.15",
        prefix_icon=ft.Icons.WIFI,
        expand=True,
        on_change=lambda e: page.client_storage.set("ps5_ip", e.control.value)
    )

    port_input = ft.TextField(
        label="Porta",
        value=saved_port,
        hint_text="Ex: 9021",
        prefix_icon=ft.Icons.NUMBERS,
        width=120,
        on_change=lambda e: page.client_storage.set("ps5_port", e.control.value)
    )

    folder_input = ft.TextField(
        label="Caminho da Pasta de Payloads",
        value=saved_folder,
        hint_text="Ex: /storage/emulated/0/Download",
        prefix_icon=ft.Icons.FOLDER,
        expand=True,
        on_change=lambda e: page.client_storage.set("payload_folder", e.control.value)
    )

    # Status / Informação do envio
    status_text = ft.Text("Selecione a pasta ou arquivos para iniciar", color=ft.Colors.GREY_400, size=13)
    progress_ring = ft.ProgressRing(visible=False, width=20, height=20, stroke_width=2)

    # Lista contêiner de Payloads
    payloads_list = ft.ListView(
        expand=False,
        spacing=8,
        divider_thickness=1,
    )

    # Contador e Filtro
    count_text = ft.Text("Nenhum payload encontrado", size=13, weight=ft.FontWeight.W_500)
    search_input = ft.TextField(
        hint_text="Filtrar por nome...",
        prefix_icon=ft.Icons.SEARCH,
        dense=True,
        visible=False,
        on_change=lambda e: filter_and_render_list(e.control.value)
    )

    folder_path_text = ft.Text("Nenhuma pasta varrida", color=ft.Colors.GREY_400, size=12, italic=True)

    def show_snack(msg: str, is_error: bool = False):
        page.open(
            ft.SnackBar(
                content=ft.Text(msg, color=ft.Colors.WHITE),
                bgcolor=ft.Colors.RED_700 if is_error else ft.Colors.GREEN_700,
                duration=4000
            )
        )

    def request_android_permissions():
        """ Solicita permissões de armazenamento (STORAGE e MANAGE_EXTERNAL_STORAGE) """
        try:
            permission_handler.request_permission(PermissionType.MANAGE_EXTERNAL_STORAGE)
            permission_handler.request_permission(PermissionType.STORAGE)
        except Exception as ex:
            print(f"Solicitação de permissão: {ex}")

    def format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f} MB"

    def scan_directory(dir_path: str):
        """Varre a pasta e suas subpastas em busca de arquivos .elf, .bin e .js."""
        nonlocal payload_files
        payload_files = []

        resolved = resolve_android_path(dir_path)
        target = resolved if os.path.exists(resolved) else dir_path

        if not target or not os.path.exists(target):
            show_snack(f"Pasta não encontrada: {target}", is_error=True)
            folder_path_text.value = f"Não encontrada: {target}"
            render_list()
            return

        try:
            valid_exts = (".elf", ".bin", ".js")
            for current_dir, _, file_names in os.walk(target):
                for file_name in file_names:
                    if not file_name.lower().endswith(valid_exts):
                        continue

                    full_path = os.path.join(current_dir, file_name)
                    relative_path = os.path.relpath(full_path, target)
                    try:
                        size = os.path.getsize(full_path)
                    except OSError:
                        size = 0

                    payload_files.append({
                        "name": relative_path,
                        "path": full_path,
                        "size": size,
                    })

            payload_files.sort(key=lambda item: item["name"].lower())

            folder_input.value = target
            page.client_storage.set("payload_folder", target)
            folder_path_text.value = f"Pasta ativa: {target}"
            search_input.visible = len(payload_files) > 5
            render_list()
            show_snack(f"Encontrados {len(payload_files)} payloads!")
        except Exception as err:
            show_snack(f"Erro ao ler pasta ({target}): {str(err)}", is_error=True)

    def render_list(filtered_items=None):
        payloads_list.controls.clear()
        items = filtered_items if filtered_items is not None else payload_files

        if not items:
            count_text.value = "Nenhum payload (.elf / .bin / .js) encontrado."
            payloads_list.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.FOLDER_OFF_OUTLINED, size=48, color=ft.Colors.GREY_600),
                        ft.Text("Nenhum arquivo .elf, .bin ou .js encontrado.", color=ft.Colors.GREY_500, text_align=ft.TextAlign.CENTER)
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=20
                )
            )
        else:
            count_text.value = f"Total: {len(items)} payload(s)"
            for item in items:
                ext = os.path.splitext(item["name"])[1].lower()
                if ext == ".elf":
                    icon = ft.Icons.TERMINAL
                    icon_color = ft.Colors.AMBER_400
                elif ext == ".js":
                    icon = ft.Icons.DESCRIPTION
                    icon_color = ft.Colors.GREEN_400
                else:
                    icon = ft.Icons.MEMORY
                    icon_color = ft.Colors.CYAN_400

                payloads_list.controls.append(
                    ft.Card(
                        content=ft.ListTile(
                            leading=ft.Icon(icon, color=icon_color, size=30),
                            title=ft.Text(item["name"], weight=ft.FontWeight.W_600, selectable=True),
                            subtitle=ft.Text(f"{ext.upper()} • {format_size(item['size'])}", size=12, color=ft.Colors.GREY_400),
                            trailing=ft.ElevatedButton(
                                "Enviar",
                                icon=ft.Icons.SEND,
                                style=ft.ButtonStyle(color=ft.Colors.BLUE_200, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST),
                                on_click=lambda _, file_item=item: send_payload_to_ps5(file_item)
                            )
                        )
                    )
                )

        page.update()

    def filter_and_render_list(query: str):
        if not query.strip():
            render_list()
        else:
            q = query.lower().strip()
            filtered = [item for item in payload_files if q in item["name"].lower()]
            render_list(filtered)

    def send_payload_to_ps5(item: dict):
        ip = ip_input.value.strip()
        port_str = port_input.value.strip()

        if not ip:
            show_snack("Informe o IP do PS5!", is_error=True)
            return

        if not port_str.isdigit():
            show_snack("Informe uma porta válida!", is_error=True)
            return

        port = int(port_str)
        status_text.value = f"Enviando {item['name']} para {ip}:{port}..."
        status_text.color = ft.Colors.BLUE_300
        progress_ring.visible = True
        page.update()

        # Envio Socket
        success, message = send_payload(item["path"], ip, port)

        progress_ring.visible = False
        if success:
            status_text.value = f"✅ Enviado: {item['name']}"
            status_text.color = ft.Colors.GREEN_400
            show_snack(message, is_error=False)
        else:
            status_text.value = f"❌ Erro ao enviar {item['name']}"
            status_text.color = ft.Colors.RED_400
            show_snack(message, is_error=True)

        page.update()

    # Callback do FilePicker para Seleção de Diretório ou Arquivos
    def on_file_picker_result(e: ft.FilePickerResultEvent):
        if e.path:
            # Resolve o URI SAF retornado pelo Android
            resolved = resolve_android_path(e.path)
            scan_directory(resolved)
        elif e.files:
            # Arquivos Selecionados Diretamente
            nonlocal payload_files
            payload_files = []
            valid_exts = (".elf", ".bin", ".js")
            for f in e.files:
                if f.name.lower().endswith(valid_exts):
                    payload_files.append({
                        "name": f.name,
                        "path": f.path,
                        "size": f.size or 0
                    })
            folder_path_text.value = f"Arquivos selecionados ({len(payload_files)})"
            render_list()
            show_snack(f"{len(payload_files)} payload(s) carregado(s)!")

    file_picker = ft.FilePicker(on_result=on_file_picker_result)
    page.overlay.append(file_picker)

    def pick_folder_click(_):
        request_android_permissions()
        file_picker.get_directory_path(dialog_title="Selecione a pasta com os Payloads (.elf / .bin / .js)")

    def pick_files_click(_):
        request_android_permissions()
        file_picker.pick_files(
            allow_multiple=True,
            allowed_extensions=["elf", "bin", "js"],
            dialog_title="Selecione os Payloads (.elf, .bin ou .js)"
        )

    def preset_click(path: str):
        folder_input.value = path
        scan_directory(path)

    # UI LAYOUT

    # Card Conexão PS5
    connection_card = ft.Card(
        content=ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.ROUTER, color=ft.Colors.BLUE_400),
                    ft.Text("Conexão PS5", size=16, weight=ft.FontWeight.BOLD),
                ]),
                ft.Row([
                    ip_input,
                    port_input,
                ]),
            ]),
            padding=14
        )
    )

    # Card Seleção da Pasta / Payloads
    folder_card = ft.Card(
        content=ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.FOLDER_SPECIAL, color=ft.Colors.AMBER_400),
                    ft.Text("Payloads (.elf / .bin / .js)", size=16, weight=ft.FontWeight.BOLD),
                ]),
                folder_path_text,
                ft.Row([
                    folder_input,
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        tooltip="Varrer Pasta",
                        on_click=lambda _: scan_directory(folder_input.value)
                    )
                ]),
                # Atalhos rápidos de pastas no Android
                ft.Row([
                    ft.Text("Atalhos:", size=12, color=ft.Colors.GREY_400),
                    ft.TextButton("Download", on_click=lambda _: preset_click("/storage/emulated/0/Download")),
                    ft.TextButton("Documents", on_click=lambda _: preset_click("/storage/emulated/0/Documents")),
                ]),
                ft.Row([
                    ft.ElevatedButton(
                        "Abrir Seletor de Pasta",
                        icon=ft.Icons.FOLDER_OPEN,
                        style=ft.ButtonStyle(color=ft.Colors.AMBER_200),
                        on_click=pick_folder_click,
                        expand=True
                    ),
                    ft.ElevatedButton(
                        "Escolher Arquivos",
                        icon=ft.Icons.FILE_UPLOAD,
                        style=ft.ButtonStyle(color=ft.Colors.CYAN_200),
                        on_click=pick_files_click,
                        expand=True
                    )
                ]),
            ]),
            padding=14
        )
    )

    # Status Bar Row
    status_row = ft.Container(
        content=ft.Row([
            progress_ring,
            status_text,
        ], alignment=ft.MainAxisAlignment.CENTER),
        padding=6
    )

    # Adicionar componentes à página
    page.add(
        connection_card,
        folder_card,
        status_row,
        ft.Row([count_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        search_input,
        payloads_list
    )

    # Se a pasta salva existir ao iniciar, carrega automaticamente
    if os.path.exists(saved_folder):
        scan_directory(saved_folder)

if __name__ == "__main__":
    ft.app(target=main)
