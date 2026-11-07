import hashlib
import os
import posixpath
import tempfile
import urllib.parse

import flet as ft
import flet_video as ftv
from flet_permission_handler import PermissionHandler, PermissionType

from payload_sender import send_payload
from ps5_ftp import FTPEntry, PS5FTPClient
from ps5_media import build_capture_details
from jxr_preview import (build_jxr_viewer_html, decode_jpeg_preview_base64, decode_png_preview_base64)
from jxr_thumbnails import build_jxr_thumbnails_html

try:
    from flet_webview import WebView as FletWebView
except ImportError:
    FletWebView = None


def build_video_player_control(local_path: str, on_error=None):
    """Create the registered flet-video player for a cached local capture."""
    return ftv.Video(
        playlist=[ftv.VideoMedia(resource=local_path)],
        width=340,
        height=240,
        fit=ft.ImageFit.CONTAIN,
        autoplay=False,
        show_controls=True,
        on_error=on_error,
    )


def resolve_android_path(raw_path: str) -> str:
    """Resolve URIs do Android SAF para caminhos POSIX acessíveis ao app."""
    if not raw_path:
        return ""
    decoded = urllib.parse.unquote(raw_path)
    if os.path.exists(decoded):
        return decoded
    if "primary:" in decoded:
        rel_path = decoded.split("primary:")[-1].lstrip("/")
        return os.path.join("/storage/emulated/0", rel_path)
    if "primary" in decoded and ":" in decoded:
        rel_path = decoded.split(":")[-1].lstrip("/")
        return os.path.join("/storage/emulated/0", rel_path)
    if "/storage/emulated/0/" in decoded:
        return decoded[decoded.find("/storage/emulated/0/"):]
    return decoded


def main(page: ft.Page):
    page.title = "PS5 Payload Sender"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 12
    page.spacing = 0
    # Tabs/expanded content need a bounded viewport. Scrolling the Page itself
    # wraps its children in an unbounded scroll view and can collapse the tab
    # body to zero height on Android. Each tab owns its own scroll container.
    page.scroll = None

    permission_handler = PermissionHandler()
    page.overlay.append(permission_handler)

    payload_files: list[dict] = []
    gallery_entries: list[FTPEntry] = []
    gallery_details: dict[str, dict] = {}
    gallery_thumbnail_paths: dict[str, str] = {}
    gallery_thumb_lookup: dict[str, str] = {}
    gallery_thumb_expected: set[str] = set()
    gallery_thumb_completed: set[str] = set()
    gallery_thumb_root = ""
    gallery_thumb_webview = None
    gallery_preview_pending: dict[str, dict] = {}

    page.appbar = ft.AppBar(
        leading=ft.Icon(ft.Icons.SPORTS_ESPORTS, color=ft.Colors.BLUE_400),
        leading_width=40,
        title=ft.Text("PS5 Payload Sender", weight=ft.FontWeight.BOLD),
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
    )

    # ELF loader e FTP são serviços independentes e usam portas diferentes.
    saved_ip = page.client_storage.get("ps5_ip")
    if not saved_ip or saved_ip == "192.168.1.100":
        saved_ip = "192.168.15.4"
    saved_port = page.client_storage.get("ps5_port") or "9021"
    saved_folder = page.client_storage.get("payload_folder") or "/storage/emulated/0/Download"
    saved_ftp_ip = page.client_storage.get("ps5_ftp_ip") or "192.168.15.4"
    saved_ftp_port = page.client_storage.get("ps5_ftp_port")
    if not saved_ftp_port or saved_ftp_port == "1337":
        saved_ftp_port = "2121"
    saved_ftp_user = page.client_storage.get("ps5_ftp_user") or "anonymous"

    ip_input = ft.TextField(
        label="IP do PS5", value=saved_ip, hint_text="Ex.: 192.168.1.15",
        prefix_icon=ft.Icons.WIFI, expand=True,
        on_change=lambda e: page.client_storage.set("ps5_ip", e.control.value),
    )
    port_input = ft.TextField(
        label="Porta do payload", value=saved_port, expand=True,
        prefix_icon=ft.Icons.NUMBERS,
        on_change=lambda e: page.client_storage.set("ps5_port", e.control.value),
    )
    folder_input = ft.TextField(
        label="Pasta de payloads", value=saved_folder, prefix_icon=ft.Icons.FOLDER,
        expand=True,
        on_change=lambda e: page.client_storage.set("payload_folder", e.control.value),
    )

    status_text = ft.Text("Selecione a pasta ou os arquivos para iniciar.", color=ft.Colors.GREY_400, size=13)
    progress_ring = ft.ProgressRing(visible=False, width=20, height=20, stroke_width=2)
    payloads_list = ft.ListView(spacing=8, divider_thickness=1, height=320)
    count_text = ft.Text("Nenhum payload encontrado", size=13, weight=ft.FontWeight.W_500)
    folder_path_text = ft.Text("Nenhuma pasta varrida", color=ft.Colors.GREY_400, size=12, italic=True)
    search_input = ft.TextField(hint_text="Filtrar por nome...", prefix_icon=ft.Icons.SEARCH, dense=True, visible=False)

    def show_snack(message: str, is_error: bool = False):
        page.open(ft.SnackBar(
            content=ft.Text(message, color=ft.Colors.WHITE),
            bgcolor=ft.Colors.RED_700 if is_error else ft.Colors.GREEN_700,
            duration=4500,
        ))

    def request_android_permissions():
        try:
            permission_handler.request_permission(PermissionType.MANAGE_EXTERNAL_STORAGE)
            permission_handler.request_permission(PermissionType.STORAGE)
        except Exception as ex:
            print(f"Solicitação de permissão: {ex}")

    def format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        if size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.2f} MB"
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    # ------------------------------ Payloads ------------------------------
    def render_payload_list(filtered_items=None):
        payloads_list.controls.clear()
        items = filtered_items if filtered_items is not None else payload_files
        if not items:
            count_text.value = "Nenhum payload (.elf / .bin / .js) encontrado."
            payloads_list.controls.append(ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.FOLDER_OFF_OUTLINED, size=48, color=ft.Colors.GREY_600),
                    ft.Text("Nenhum arquivo .elf, .bin ou .js encontrado.", color=ft.Colors.GREY_500),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=20,
            ))
        else:
            count_text.value = f"Total: {len(items)} payload(s)"
            for item in items:
                ext = os.path.splitext(item["name"])[1].lower()
                if ext == ".elf":
                    icon, icon_color = ft.Icons.TERMINAL, ft.Colors.AMBER_400
                elif ext == ".js":
                    icon, icon_color = ft.Icons.DESCRIPTION, ft.Colors.GREEN_400
                else:
                    icon, icon_color = ft.Icons.MEMORY, ft.Colors.CYAN_400
                payloads_list.controls.append(ft.Card(content=ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(icon, color=icon_color, size=28),
                            ft.Column([
                                ft.Text(item["name"], weight=ft.FontWeight.W_600,
                                        selectable=True, max_lines=3,
                                        overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text(f"{ext.upper()} • {format_size(item['size'])}",
                                        size=12, color=ft.Colors.GREY_400),
                            ], expand=True, spacing=2),
                        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Row([ft.ElevatedButton(
                            "Enviar payload", icon=ft.Icons.SEND, expand=True,
                            on_click=lambda _, file_item=item: send_payload_to_ps5(file_item),
                        )], spacing=0),
                    ], spacing=8),
                    padding=12,
                )))
        page.update()

    def filter_payloads(_):
        query = search_input.value.lower().strip()
        render_payload_list(
            [item for item in payload_files if query in item["name"].lower()]
            if query else None
        )

    search_input.on_change = filter_payloads

    def scan_directory(dir_path: str):
        nonlocal payload_files
        payload_files = []
        resolved = resolve_android_path(dir_path)
        target = resolved if os.path.exists(resolved) else dir_path
        if not target or not os.path.exists(target):
            show_snack(f"Pasta não encontrada: {target}", is_error=True)
            folder_path_text.value = f"Não encontrada: {target}"
            render_payload_list()
            return
        try:
            for current_dir, _, file_names in os.walk(target):
                for file_name in file_names:
                    if not file_name.lower().endswith((".elf", ".bin", ".js")):
                        continue
                    full_path = os.path.join(current_dir, file_name)
                    try:
                        size = os.path.getsize(full_path)
                    except OSError:
                        size = 0
                    payload_files.append({
                        "name": os.path.relpath(full_path, target),
                        "path": full_path,
                        "size": size,
                    })
            payload_files.sort(key=lambda item: item["name"].lower())
            folder_input.value = target
            page.client_storage.set("payload_folder", target)
            folder_path_text.value = f"Pasta ativa: {target}"
            search_input.visible = len(payload_files) > 5
            render_payload_list()
            show_snack(f"Encontrados {len(payload_files)} payloads.")
        except Exception as err:
            show_snack(f"Erro ao ler a pasta: {err}", is_error=True)

    def send_payload_to_ps5(item: dict):
        ip, port_text = ip_input.value.strip(), port_input.value.strip()
        if not ip:
            show_snack("Informe o IP do PS5.", is_error=True)
            return
        if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
            show_snack("Informe uma porta TCP válida.", is_error=True)
            return
        status_text.value = f"Enviando {item['name']} para {ip}:{port_text}..."
        status_text.color = ft.Colors.BLUE_300
        progress_ring.visible = True
        page.update()
        success, message = send_payload(item["path"], ip, int(port_text))
        progress_ring.visible = False
        status_text.value = ("Enviado: " if success else "Falha ao enviar ") + item["name"]
        status_text.color = ft.Colors.GREEN_400 if success else ft.Colors.RED_400
        show_snack(message, is_error=not success)
        page.update()

    def on_payload_picker_result(e: ft.FilePickerResultEvent):
        nonlocal payload_files
        if e.path:
            scan_directory(resolve_android_path(e.path))
        elif e.files:
            payload_files = []
            for file in e.files:
                if file.name.lower().endswith((".elf", ".bin", ".js")) and file.path:
                    payload_files.append({"name": file.name, "path": file.path, "size": file.size or 0})
            folder_path_text.value = f"Arquivos selecionados ({len(payload_files)})"
            render_payload_list()
            show_snack(f"{len(payload_files)} payload(s) carregado(s).")

    payload_picker = ft.FilePicker(on_result=on_payload_picker_result)
    page.overlay.append(payload_picker)

    def pick_payload_folder(_):
        request_android_permissions()
        payload_picker.get_directory_path(dialog_title="Selecione a pasta de payloads")

    def pick_payload_files(_):
        request_android_permissions()
        payload_picker.pick_files(allow_multiple=True, allowed_extensions=["elf", "bin", "js"])

    payload_panel = ft.Column([
        ft.Card(content=ft.Container(content=ft.Column([
            ft.Row([ft.Icon(ft.Icons.ROUTER, color=ft.Colors.BLUE_400), ft.Text("Conexão do payload", size=16, weight=ft.FontWeight.BOLD)]),
            ft.Column([
                ft.Row([ip_input], spacing=0),
                ft.Row([port_input], spacing=0),
            ], spacing=8),
            ft.Text("Porta comum do ELF loader: 9021. O receptor precisa estar ativo no PS5.", size=11, color=ft.Colors.GREY_400),
        ], spacing=10), padding=14)),
        ft.Card(content=ft.Container(content=ft.Column([
            ft.Row([ft.Icon(ft.Icons.FOLDER_SPECIAL, color=ft.Colors.AMBER_400), ft.Text("Payloads (.elf / .bin / .js)", size=16, weight=ft.FontWeight.BOLD)]),
            folder_path_text,
            ft.Row([folder_input, ft.IconButton(icon=ft.Icons.REFRESH, tooltip="Varrer pasta", on_click=lambda _: scan_directory(folder_input.value))]),
            ft.Row([
                ft.Text("Atalhos:", size=12, color=ft.Colors.GREY_400),
                ft.TextButton("Download", on_click=lambda _: scan_directory("/storage/emulated/0/Download")),
                ft.TextButton("Documents", on_click=lambda _: scan_directory("/storage/emulated/0/Documents")),
            ], wrap=True),
            ft.Column([
                ft.Row([ft.ElevatedButton("Abrir seletor de pasta", icon=ft.Icons.FOLDER_OPEN,
                                          on_click=pick_payload_folder, expand=True)], spacing=0),
                ft.Row([ft.ElevatedButton("Escolher arquivos", icon=ft.Icons.FILE_UPLOAD,
                                          on_click=pick_payload_files, expand=True)], spacing=0),
            ], spacing=8),
        ], spacing=10), padding=14)),
        ft.Container(content=ft.Row([progress_ring, status_text], alignment=ft.MainAxisAlignment.CENTER), padding=6),
        count_text, search_input, payloads_list,
    ], spacing=10, scroll=ft.ScrollMode.AUTO)

    # -------------------------------- FTP --------------------------------
    ftp_ip_input = ft.TextField(
        label="IP do FTP", value=saved_ftp_ip, expand=True,
        prefix_icon=ft.Icons.WIFI,
        on_change=lambda e: page.client_storage.set("ps5_ftp_ip", e.control.value),
    )
    ftp_port_input = ft.TextField(
        label="Porta FTP", value=saved_ftp_port, expand=True,
        keyboard_type=ft.KeyboardType.NUMBER,
        on_change=lambda e: page.client_storage.set("ps5_ftp_port", e.control.value),
    )
    ftp_user_input = ft.TextField(
        label="Usuário", value=saved_ftp_user, expand=True,
        on_change=lambda e: page.client_storage.set("ps5_ftp_user", e.control.value),
    )
    ftp_password_input = ft.TextField(label="Senha", password=True, can_reveal_password=True, expand=True)
    ftp_path_input = ft.TextField(label="Pasta remota", value="/", expand=True)
    ftp_status = ft.Text(
        f"FTP desconectado. Destino: {saved_ftp_ip}:{saved_ftp_port}.",
        size=12, color=ft.Colors.GREY_400,
    )
    ftp_list = ft.ListView(spacing=8, height=520, divider_thickness=1)

    def create_ftp_client() -> PS5FTPClient:
        host, port_text = ftp_ip_input.value.strip(), ftp_port_input.value.strip()
        if not host:
            raise ValueError("Informe o IP do servidor FTP.")
        if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
            raise ValueError("Informe uma porta FTP válida.")
        return PS5FTPClient(
            host, int(port_text),
            ftp_user_input.value.strip() or "anonymous",
            ftp_password_input.value or "anonymous",
        )

    def current_ftp_path() -> str:
        return ftp_path_input.value.strip() or "/"

    def download_directory() -> str:
        candidates = [
            "/storage/emulated/0/Download/PS5 Captures",
            os.path.join(os.path.expanduser("~"), "Downloads", "PS5 Captures"),
            os.path.join(tempfile.gettempdir(), "PS5 Captures"),
        ]
        for candidate in candidates:
            try:
                os.makedirs(candidate, exist_ok=True)
                probe = os.path.join(candidate, ".write_test")
                with open(probe, "wb") as test_file:
                    test_file.write(b"ok")
                os.remove(probe)
                return candidate
            except OSError:
                continue
        raise OSError("Não foi possível gravar no armazenamento do celular.")

    def unique_download_path(file_name: str) -> str:
        safe_name = os.path.basename(file_name).replace("/", "_").replace("\\", "_")
        directory = download_directory()
        target = os.path.join(directory, safe_name)
        if not os.path.exists(target):
            return target
        stem, extension = os.path.splitext(safe_name)
        index = 2
        while os.path.exists(os.path.join(directory, f"{stem} ({index}){extension}")):
            index += 1
        return os.path.join(directory, f"{stem} ({index}){extension}")

    def download_remote_file(remote_path: str, file_name: str) -> str:
        local_path = unique_download_path(file_name)
        with create_ftp_client() as client:
            client.download_file(remote_path, local_path)
        return local_path

    def download_ftp_entry(entry: FTPEntry):
        try:
            show_snack(f"Baixado para: {download_remote_file(entry.path, entry.name)}")
        except Exception as ex:
            show_snack(f"Falha no download: {ex}", is_error=True)

    def open_ftp_directory(remote_path: str):
        ftp_path_input.value = remote_path
        load_ftp_directory()

    def go_to_parent_ftp(_):
        path = current_ftp_path().rstrip("/")
        open_ftp_directory(posixpath.dirname(path) or "/")

    def load_ftp_directory(_=None):
        remote_path = current_ftp_path()
        ftp_host = ftp_ip_input.value.strip()
        ftp_port = ftp_port_input.value.strip()
        ftp_status.value = f"Conectando ao FTP em {ftp_host}:{ftp_port}..."
        ftp_status.color = ft.Colors.BLUE_300
        ftp_list.controls.clear()
        page.update()
        try:
            with create_ftp_client() as client:
                entries = client.list_dir(remote_path)
            ftp_status.value = f"{len(entries)} item(ns) em {remote_path}"
            ftp_status.color = ft.Colors.GREEN_400
            ftp_list.controls.clear()
            if not entries:
                ftp_list.controls.append(ft.Container(content=ft.Text("Esta pasta está vazia."), padding=16))
            for entry in entries:
                if entry.is_dir:
                    leading = ft.Icon(ft.Icons.FOLDER, color=ft.Colors.AMBER_300)
                    trailing = ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, tooltip="Abrir pasta", on_click=lambda _, p=entry.path: open_ftp_directory(p))
                    subtitle = "Pasta"
                    action = lambda _, p=entry.path: open_ftp_directory(p)
                else:
                    leading = ft.Icon(ft.Icons.INSERT_DRIVE_FILE, color=ft.Colors.CYAN_300)
                    trailing = ft.IconButton(icon=ft.Icons.DOWNLOAD, tooltip="Baixar para o celular", on_click=lambda _, item=entry: download_ftp_entry(item))
                    subtitle = format_size(entry.size)
                    action = lambda _, item=entry: download_ftp_entry(item)
                ftp_list.controls.append(ft.Card(content=ft.Container(
                    content=ft.Column([
                        ft.Row([
                            leading,
                            ft.Text(entry.name, selectable=True, expand=True,
                                    max_lines=3, overflow=ft.TextOverflow.ELLIPSIS),
                        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Text(subtitle, size=12, color=ft.Colors.GREY_400),
                        ft.Row([ft.ElevatedButton(
                            "Abrir pasta" if entry.is_dir else "Baixar arquivo",
                            icon=ft.Icons.FOLDER_OPEN if entry.is_dir else ft.Icons.DOWNLOAD,
                            on_click=action, expand=True,
                        )], spacing=0),
                    ], spacing=6),
                    padding=10,
                )))
        except Exception as ex:
            ftp_status.value = (
                f"Falha no FTP {ftp_host}:{ftp_port} ({type(ex).__name__}): {ex}"
            )
            ftp_status.color = ft.Colors.RED_400
            ftp_list.controls.clear()
            ftp_list.controls.append(ft.Container(
                content=ft.Text(
                    "Não foi possível acessar o FTP. Confirme se o serviço está ativo no PS5, "
                    "se o IP está correto e se o celular está na mesma rede.",
                    color=ft.Colors.GREY_400,
                ), padding=16,
            ))
        page.update()

    def on_ftp_upload_result(e: ft.FilePickerResultEvent):
        if not e.files:
            return
        try:
            uploaded = 0
            with create_ftp_client() as client:
                remote_dir = current_ftp_path()
                existing = {item.name for item in client.list_dir(remote_dir)}
                for selected in e.files:
                    if not selected.path or not os.path.isfile(selected.path):
                        continue
                    remote_name = os.path.basename(selected.name)
                    if remote_name in existing:
                        raise FileExistsError(f"Já existe '{remote_name}' na pasta remota; renomeie antes de enviar.")
                    client.upload_file(selected.path, posixpath.join(remote_dir.rstrip("/") or "/", remote_name))
                    uploaded += 1
            show_snack(f"{uploaded} arquivo(s) enviado(s) por FTP.")
            load_ftp_directory()
        except Exception as ex:
            show_snack(f"Falha no envio FTP: {ex}", is_error=True)

    ftp_upload_picker = ft.FilePicker(on_result=on_ftp_upload_result)
    page.overlay.append(ftp_upload_picker)

    def pick_ftp_upload(_):
        request_android_permissions()
        ftp_upload_picker.pick_files(allow_multiple=True, dialog_title="Selecione arquivos para enviar ao PS5 por FTP")

    ftp_panel = ft.Column([
        ft.Text("Gerenciador de arquivos do PS5", size=17, weight=ft.FontWeight.BOLD),
        ft.Text("FTP comum não é criptografado. Use apenas na sua rede local confiável.", size=12, color=ft.Colors.AMBER_200),
        ft.Column([
            ft.Row([ftp_ip_input], spacing=0),
            ft.Row([ftp_port_input], spacing=0),
            ft.Row([ftp_user_input], spacing=0),
            ft.Row([ftp_password_input], spacing=0),
        ], spacing=8),
        ft.Column([
            ft.Row([ft.ElevatedButton("Conectar / atualizar", icon=ft.Icons.WIFI,
                                      on_click=load_ftp_directory, expand=True)], spacing=0),
            ft.Row([ft.OutlinedButton("Enviar arquivo(s)", icon=ft.Icons.UPLOAD_FILE,
                                      on_click=pick_ftp_upload, expand=True)], spacing=0),
        ], spacing=8),
        ft.Row([ftp_path_input, ft.IconButton(icon=ft.Icons.ARROW_UPWARD, tooltip="Pasta acima", on_click=go_to_parent_ftp)]),
        ftp_status, ftp_list,
    ], spacing=10, scroll=ft.ScrollMode.AUTO)

    # ------------------------------ Capturas ------------------------------
    photo_root_input = ft.TextField(label="Pasta de screenshots", value="/user/av_contents/photo/NPXS40087", expand=True)
    video_root_input = ft.TextField(label="Pasta de vídeos", value="/user/av_contents/video/NPXS40087", expand=True)
    gallery_status = ft.Text("Conecte ao FTP e carregue Fotos ou Vídeos.", size=12, color=ft.Colors.GREY_400)
    gallery_count = ft.Text("", size=12, color=ft.Colors.GREY_400)
    gallery_grid = ft.GridView(controls=[], max_extent=210, child_aspect_ratio=0.50, spacing=12, run_spacing=14, height=680)

    def cache_media(entry: FTPEntry) -> str:
        cache_dir = os.path.join(tempfile.gettempdir(), "ps5_payload_sender_cache")
        os.makedirs(cache_dir, exist_ok=True)
        token = hashlib.sha1(entry.path.encode("utf-8", errors="replace")).hexdigest()[:12]
        name = os.path.basename(entry.name).replace("/", "_").replace("\\", "_")
        local_path = os.path.join(cache_dir, f"{token}_{name}")
        if not os.path.exists(local_path) or os.path.getsize(local_path) != entry.size:
            with create_ftp_client() as client:
                client.download_file(entry.path, local_path)
        return local_path

    def download_capture(entry: FTPEntry):
        try:
            local_path = download_remote_file(entry.path, entry.name)
            show_snack(f"Captura salva em: {local_path}")
        except Exception as ex:
            show_snack(f"Falha ao baixar captura: {ex}", is_error=True)

    def close_jxr_preview(token: str, dialog):
        gallery_preview_pending.pop(token, None)
        page.close(dialog)

    def save_jxr_preview_png(token: str):
        pending = gallery_preview_pending.get(token)
        if not pending:
            show_snack("A pr?via n?o est? mais dispon?vel.", is_error=True)
            return
        if gallery_thumb_webview is None:
            show_snack("O conversor JXR n?o est? dispon?vel neste aparelho.", is_error=True)
            return
        pending["status"].value = "Gerando PNG SDR da prévia…"
        pending["save_button"].disabled = True
        page.update()
        try:
            gallery_thumb_webview.run_javascript("window.ps5SavePng()")
        except Exception as ex:
            pending["save_button"].disabled = False
            pending["status"].value = f"N?o foi poss?vel exportar o PNG: {ex}"
            page.update()

    def preview_capture(entry: FTPEntry):
        ext = os.path.splitext(entry.name)[1].lower()
        try:
            local_path = cache_media(entry)
            details = gallery_details.get(entry.path, {})
            game_name = str(details.get("game_name", ""))
            title_id = str(details.get("title_id", ""))
            captured_at = str(details.get("captured_at", ""))
            app_version = str(details.get("app_version", ""))

            if ext == ".jxr" and FletWebView is not None and page.platform == ft.PagePlatform.ANDROID and gallery_thumb_webview is not None:
                token = hashlib.sha1(
                    (entry.path + str(os.path.getsize(local_path))).encode("utf-8", errors="replace")
                ).hexdigest()[:20]
                jxr_html = build_jxr_viewer_html(local_path, entry.name, result_token=token)
                preview_image = ft.Image(
                    src="", width=340, height=320, fit=ft.ImageFit.CONTAIN,
                    visible=False,
                    error_content=ft.Text("N?o foi poss?vel exibir a imagem convertida."),
                )
                preview_progress = ft.ProgressRing(width=28, height=28, stroke_width=3)
                preview_status = ft.Text(
                    "Decodificando a captura JXR 4K e preparando uma pr?via compat?vel?",
                    size=12, text_align=ft.TextAlign.CENTER,
                )
                save_button = ft.ElevatedButton(
                    "Salvar PNG SDR no celular", icon=ft.Icons.IMAGE,
                    disabled=True,
                    on_click=lambda _, t=token: save_jxr_preview_png(t),
                )
                info_text = "\n".join(line for line in [
                    game_name or title_id or "Jogo n?o identificado",
                    captured_at,
                    f"Vers?o do jogo: {app_version}" if app_version else "",
                    format_size(entry.size),
                ] if line)
                dialog = ft.AlertDialog(
                    modal=True,
                    title=ft.Text(game_name or entry.name, max_lines=2),
                    content=ft.Column([
                        ft.Row([preview_progress, preview_status], alignment=ft.MainAxisAlignment.CENTER),
                        preview_image,
                        ft.Text(info_text, size=11, color=ft.Colors.GREY_400),
                    ], tight=True, scroll=ft.ScrollMode.AUTO,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    actions=[
                        ft.TextButton("Fechar", on_click=lambda _, t=token, d=None: close_jxr_preview(t, dialog)),
                        save_button,
                        ft.OutlinedButton(
                            "Baixar JXR original", icon=ft.Icons.DOWNLOAD,
                            on_click=lambda _, item=entry: download_capture(item),
                        ),
                    ],
                    actions_alignment=ft.MainAxisAlignment.END,
                )
                gallery_preview_pending[token] = {
                    "entry": entry,
                    "image": preview_image,
                    "progress": preview_progress,
                    "status": preview_status,
                    "save_button": save_button,
                    "dialog": dialog,
                }
                page.open(dialog)
                try:
                    gallery_thumb_webview.load_html(jxr_html)
                except Exception as ex:
                    preview_progress.visible = False
                    preview_status.value = f"Falha ao iniciar a convers?o JXR: {ex}"
                    page.update()
                return

            if ext in (".jpg", ".jpeg", ".png"):
                preview = ft.Image(
                    src=local_path, width=340, height=390,
                    fit=ft.ImageFit.CONTAIN,
                    error_content=ft.Text("N?o foi poss?vel exibir a imagem neste aparelho."),
                )
            elif ext == ".jxr":
                preview = ft.Column([
                    ft.Icon(ft.Icons.HDR_ON, size=48, color=ft.Colors.AMBER_300),
                    ft.Text(
                        "JPEG XR ? o arquivo HDR original. A pr?via convertida est? dispon?vel no APK Android.",
                        text_align=ft.TextAlign.CENTER,
                    ),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True)
            elif ext in (".mp4", ".webm"):
                preview = build_video_player_control(
                    local_path,
                    on_error=lambda event: show_snack(
                        f"Falha ao reproduzir o vídeo: {event.data or 'erro não informado'}",
                        is_error=True,
                    ),
                )
            else:
                preview = ft.Text("Formato sem pr?-visualiza??o dispon?vel.")

            capture_info = [
                game_name or title_id or "Jogo n?o identificado",
                captured_at,
                f"Vers?o do jogo: {app_version}" if app_version else "",
                format_size(entry.size),
                entry.path,
            ]
            info_text = "\n".join(line for line in capture_info if line)
            download_label = "Baixar JXR original" if ext == ".jxr" else "Baixar no celular"
            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text(game_name or entry.name, max_lines=2),
                content=ft.Column([
                    preview,
                    ft.Text(info_text, size=11, color=ft.Colors.GREY_400),
                ], tight=True, scroll=ft.ScrollMode.AUTO),
                actions=[
                    ft.TextButton("Fechar", on_click=lambda _: page.close(dialog)),
                    ft.ElevatedButton(download_label, icon=ft.Icons.DOWNLOAD, on_click=lambda _: download_capture(entry)),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.open(dialog)
        except Exception as ex:
            show_snack(f"N?o foi poss?vel abrir a captura: {ex}", is_error=True)

    def update_gallery_count():
        title_ids = {
            str(item.get("title_id", ""))
            for item in gallery_details.values()
            if item.get("title_id")
        }
        with_dat = sum(1 for item in gallery_details.values() if item.get("has_dat"))
        with_meta = sum(1 for item in gallery_details.values() if item.get("has_meta"))
        preview_count = sum(1 for entry in gallery_entries if entry.path in gallery_thumbnail_paths)
        gallery_count.value = (
            f"{len(gallery_entries)} captura(s) · {len(title_ids)} jogo(s) · "
            f"{with_dat} .dat · {with_meta} .meta · {preview_count} miniatura(s)"
        )

    def render_gallery(entries: list[FTPEntry], thumbnails: dict[str, str] | None = None):
        gallery_grid.controls.clear()
        thumbnails = thumbnails or {}
        for entry in entries:
            ext = os.path.splitext(entry.name)[1].lower()
            is_video = ext in (".mp4", ".webm")
            thumbnail_path = thumbnails.get(entry.path)
            details = gallery_details.get(entry.path, {})
            title_id = str(details.get("title_id", ""))
            game_name = str(details.get("game_name", ""))
            game_label = game_name or (f"Jogo {title_id}" if title_id else "Jogo não identificado")
            captured_at = str(details.get("captured_at", ""))
            sidecars = []
            if details.get("has_dat"):
                sidecars.append(".dat")
            if details.get("has_meta"):
                sidecars.append(".meta")
            sidecar_label = " + ".join(sidecars) if sidecars else "sem sidecars"
            if thumbnail_path:
                media_preview = ft.Image(
                    src=thumbnail_path, width=148, height=104,
                    fit=ft.ImageFit.CONTAIN,
                )
            else:
                media_preview = ft.Icon(
                    ft.Icons.MOVIE_OUTLINED if is_video else ft.Icons.HDR_ON,
                    size=42, color=ft.Colors.PURPLE_300 if is_video else ft.Colors.AMBER_300,
                )
            gallery_grid.controls.append(ft.Card(content=ft.Container(
                content=ft.Column([
                    media_preview,
                    ft.Text(game_label, size=11, weight=ft.FontWeight.W_600,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                            text_align=ft.TextAlign.CENTER),
                    ft.Text(entry.name, size=12, weight=ft.FontWeight.W_600, max_lines=2,
                            overflow=ft.TextOverflow.ELLIPSIS, text_align=ft.TextAlign.CENTER),
                    ft.Text(captured_at or title_id, size=10, color=ft.Colors.GREY_400),
                    ft.Text(format_size(entry.size), size=10, color=ft.Colors.GREY_400),
                    ft.Text(f"Metadados: {sidecar_label}", size=9, color=ft.Colors.GREY_500),
                    ft.Row([
                        ft.IconButton(
                            icon=ft.Icons.PLAY_CIRCLE_OUTLINE if is_video else ft.Icons.VISIBILITY,
                            tooltip="Pré-visualizar", on_click=lambda _, item=entry: preview_capture(item),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DOWNLOAD, tooltip="Baixar no celular",
                            on_click=lambda _, item=entry: download_capture(item),
                        ),
                    ], alignment=ft.MainAxisAlignment.CENTER, spacing=2),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6),
                padding=10,
            )))
        update_gallery_count()
        page.update()

    def on_gallery_thumb_console(event):
        message = getattr(event, "message", "") or ""
        if message.startswith("PS5_JXR_PREVIEW:"):
            token = ""
            try:
                _, token, payload = message.split(":", 2)
                pending = gallery_preview_pending.get(token)
                if not pending:
                    return
                jpeg_data = decode_jpeg_preview_base64(payload.strip())
                cache_dir = os.path.join(tempfile.gettempdir(), "ps5_payload_sender_cache")
                os.makedirs(cache_dir, exist_ok=True)
                local_path = os.path.join(cache_dir, token + "_full_preview.jpg")
                partial_path = local_path + ".part"
                with open(partial_path, "wb") as output:
                    output.write(jpeg_data)
                os.replace(partial_path, local_path)
                pending["image"].src = local_path
                pending["image"].visible = True
                pending["progress"].visible = False
                pending["status"].value = "Prévia SDR pronta (até 1280×720). O JXR HDR original continua intacto."
                pending["save_button"].disabled = False
                pending["preview_path"] = local_path
                page.update()
            except Exception as ex:
                pending = gallery_preview_pending.get(token) if token else None
                if pending:
                    pending["progress"].visible = False
                    pending["status"].value = f"Falha na pr?via JXR: {ex}"
                    page.update()
                else:
                    show_snack(f"Falha ao montar a pr?via JXR: {ex}", is_error=True)
        elif message.startswith("PS5_JXR_SAVE_PNG:"):
            token = ""
            try:
                _, token, payload = message.split(":", 2)
                pending = gallery_preview_pending.get(token)
                if not pending:
                    return
                png_data = decode_png_preview_base64(payload.strip())
                entry = pending["entry"]
                file_name = os.path.splitext(entry.name)[0] + ".png"
                local_path = unique_download_path(file_name)
                partial_path = local_path + ".part"
                with open(partial_path, "wb") as output:
                    output.write(png_data)
                os.replace(partial_path, local_path)
                pending["save_button"].disabled = False
                pending["status"].value = f"PNG salvo no celular: {local_path}"
                show_snack(f"PNG salvo em: {local_path}")
                page.update()
            except Exception as ex:
                pending = gallery_preview_pending.get(token) if token else None
                if pending:
                    pending["save_button"].disabled = False
                    pending["status"].value = f"Falha ao salvar PNG: {ex}"
                    page.update()
                else:
                    show_snack(f"Falha ao salvar PNG: {ex}", is_error=True)
        elif message.startswith("PS5_JXR_ERROR:"):
            try:
                _, token, error_text = message.split(":", 2)
                pending = gallery_preview_pending.get(token)
                if pending:
                    pending["progress"].visible = False
                    pending["status"].value = f"O decoder n?o conseguiu abrir a captura: {error_text}"
                    page.update()
            except ValueError:
                pass
        elif message.startswith("PS5_THUMB:"):
            try:
                _, token, payload = message.split(":", 2)
                entry_path = gallery_thumb_lookup.get(token)
                if not entry_path:
                    return
                jpeg_data = decode_jpeg_preview_base64(payload.strip())
                cache_dir = os.path.join(tempfile.gettempdir(), "ps5_payload_sender_cache")
                os.makedirs(cache_dir, exist_ok=True)
                local_path = os.path.join(cache_dir, token + "_gallery.jpeg")
                partial_path = local_path + ".part"
                with open(partial_path, "wb") as output:
                    output.write(jpeg_data)
                os.replace(partial_path, local_path)
                gallery_thumbnail_paths[entry_path] = local_path
                gallery_thumb_completed.add(token)
                render_gallery(gallery_entries, gallery_thumbnail_paths)
                if gallery_thumb_expected.issubset(gallery_thumb_completed):
                    gallery_status.value = f"Origem: {gallery_thumb_root}"
                    page.update()
            except Exception as ex:
                show_snack(f"Falha ao preparar miniatura: {ex}", is_error=True)
        elif message.startswith("PS5_THUMB_ERROR:"):
            parts = message.split(":", 2)
            if len(parts) > 1:
                gallery_thumb_completed.add(parts[1])
            if gallery_thumb_expected.issubset(gallery_thumb_completed):
                gallery_status.value = f"Origem: {gallery_thumb_root} · algumas miniaturas não puderam ser convertidas"
                page.update()
        elif message.startswith("PS5_THUMB_BATCH_ERROR:"):
            gallery_status.value = f"Miniaturas: {message.partition(':')[2]}"
            gallery_status.color = ft.Colors.AMBER_300
            page.update()
        elif message.startswith("PS5_THUMB_DONE:"):
            _, converted, failed = (message.split(":", 2) + ["0", "0"])[:3]
            try:
                converted_count = int(converted)
                failed_count = int(failed)
            except ValueError:
                converted_count = len(gallery_thumb_completed)
                failed_count = max(0, len(gallery_thumb_expected) - converted_count)
            suffix = f"{converted_count} miniatura(s) pronta(s)"
            if failed_count:
                suffix += f" · {failed_count} falha(s)"
                gallery_status.color = ft.Colors.AMBER_300
            else:
                gallery_status.color = ft.Colors.GREEN_400
            gallery_status.value = f"Origem: {gallery_thumb_root} · {suffix}"
            update_gallery_count()
            page.update()

    def load_gallery(kind: str):
        nonlocal gallery_entries, gallery_details, gallery_thumbnail_paths, gallery_thumb_root
        root = photo_root_input.value.strip() if kind == "photo" else video_root_input.value.strip()
        extensions = (".jpg", ".jpeg", ".png", ".jxr") if kind == "photo" else (".mp4", ".webm")
        gallery_thumb_root = root
        gallery_thumb_lookup.clear()
        gallery_thumb_expected.clear()
        gallery_thumb_completed.clear()
        gallery_thumbnail_paths.clear()
        gallery_status.value = "Buscando capturas no PS5..."
        gallery_status.color = ft.Colors.BLUE_300
        gallery_grid.controls.clear()
        gallery_count.value = ""
        page.update()
        try:
            thumbnail_paths: dict[str, str] = {}
            photo_thumb_items: list[tuple[str, str]] = []
            cache_dir = os.path.join(tempfile.gettempdir(), "ps5_payload_sender_cache")
            os.makedirs(cache_dir, exist_ok=True)
            with create_ftp_client() as client:
                gallery_entries = client.walk_media(root, extensions, max_depth=4, max_items=1500)
                gallery_details = build_capture_details(client, gallery_entries)
                if kind == "photo" and gallery_thumb_webview is not None:
                    for entry in gallery_entries:
                        if not entry.name.lower().endswith(".jxr"):
                            continue
                        thumb_remote = entry.path.replace("/photo/", "/thumbnails/photo/", 1) + ".jxr"
                        token = hashlib.sha1(thumb_remote.encode("utf-8", errors="replace")).hexdigest()[:16]
                        thumb_local = os.path.join(cache_dir, token + "_source.jxr")
                        if not os.path.exists(thumb_local):
                            try:
                                client.download_file(thumb_remote, thumb_local)
                            except Exception:
                                continue
                        gallery_thumb_lookup[token] = entry.path
                        gallery_thumb_expected.add(token)
                        photo_thumb_items.append((token, thumb_local))
                elif kind == "video":
                    for entry in gallery_entries:
                        thumb_remote = entry.path.replace("/video/", "/thumbnails/video/", 1) + ".jpeg"
                        token = hashlib.sha1(thumb_remote.encode("utf-8", errors="replace")).hexdigest()[:16]
                        thumb_local = os.path.join(cache_dir, token + "_preview.jpeg")
                        if not os.path.exists(thumb_local):
                            try:
                                client.download_file(thumb_remote, thumb_local)
                            except Exception:
                                continue
                        thumbnail_paths[entry.path] = thumb_local
            gallery_thumbnail_paths.update(thumbnail_paths)
            gallery_status.value = f"Origem: {root}"
            gallery_status.color = ft.Colors.GREEN_400
            render_gallery(gallery_entries, gallery_thumbnail_paths)
            if not gallery_entries:
                gallery_count.value = "Nenhum arquivo compatível encontrado."
                page.update()
            elif photo_thumb_items and gallery_thumb_webview is not None:
                gallery_status.value = f"Origem: {root} · convertendo miniaturas JXR…"
                page.update()
                gallery_thumb_webview.load_html(build_jxr_thumbnails_html(photo_thumb_items))
        except Exception as ex:
            gallery_entries = []
            gallery_details = {}
            gallery_thumbnail_paths.clear()
            gallery_thumb_lookup.clear()
            gallery_thumb_expected.clear()
            gallery_thumb_completed.clear()
            gallery_status.value = (
                f"FTP {ftp_ip_input.value.strip()}:{ftp_port_input.value.strip()} - "
                f"{type(ex).__name__}: {ex}"
            )
            gallery_status.color = ft.Colors.RED_400
            gallery_count.value = "Confira o FTP e o caminho. NPXS40087 pode variar conforme o ambiente/firmware."
            page.update()

    gallery_panel = ft.Column([
        ft.Text("Screenshots e vídeos", size=17, weight=ft.FontWeight.BOLD),
        ft.Text(
            "Os caminhos seguem o layout documentado por um payload comunitário de galeria. "
            "Edite os campos se o seu PS5 usar outra pasta.",
            size=12, color=ft.Colors.GREY_400,
        ),
        photo_root_input,
        ft.ElevatedButton("Carregar screenshots", icon=ft.Icons.PHOTO_LIBRARY, on_click=lambda _: load_gallery("photo")),
        video_root_input,
        ft.ElevatedButton("Carregar vídeos", icon=ft.Icons.VIDEO_LIBRARY, on_click=lambda _: load_gallery("video")),
        gallery_status, gallery_count, gallery_grid,
    ], spacing=10, scroll=ft.ScrollMode.AUTO)

    if FletWebView is not None and page.platform == ft.PagePlatform.ANDROID:
        gallery_thumb_webview = FletWebView(
            url="about:blank",
            enable_javascript=True,
            width=2,
            height=2,
            on_console_message=on_gallery_thumb_console,
        )
        gallery_panel.controls.append(
            ft.Container(content=gallery_thumb_webview, width=2, height=2, opacity=0.01)
        )

    tabs = ft.Tabs(
        tabs=[
            ft.Tab(text="Payloads", icon=ft.Icons.SEND, content=payload_panel),
            ft.Tab(text="FTP", icon=ft.Icons.FOLDER, content=ftp_panel),
            ft.Tab(text="Capturas", icon=ft.Icons.PHOTO_LIBRARY, content=gallery_panel),
        ],
        selected_index=0,
        tab_alignment=ft.TabAlignment.FILL,
        expand=1,
        animation_duration=180,
    )
    # Give the TabView a bounded, full-height parent on mobile and desktop.
    page.add(ft.Column([tabs], expand=True, spacing=0))

    if os.path.exists(saved_folder):
        scan_directory(saved_folder)


if __name__ == "__main__":
    ft.app(target=main)
