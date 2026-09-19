import customtkinter as ctk
import requests
import webbrowser
import threading
from tkinter import messagebox

# Configuration
API_BASE_URL = "http://127.0.0.1:8000"
APP_VERSION = "1.0.0"

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

class NawalaClient(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("NawalaSentinel Client")
        self.geometry("400x500")
        self.resizable(False, False)

        # Main Frame
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.pack(pady=20, padx=20, fill="both", expand=True)

        self.label_title = ctk.CTkLabel(self.main_frame, text="NawalaSentinel", font=ctk.CTkFont(size=24, weight="bold"))
        self.label_title.pack(pady=20)

        self.status_label = ctk.CTkLabel(self.main_frame, text="Memeriksa pembaruan...", text_color="gray")
        self.status_label.pack(pady=10)

        # Check Version on Startup
        threading.Thread(target=self.check_version).start()

    def check_version(self):
        try:
            response = requests.get(f"{API_BASE_URL}/api/version", timeout=5)
            if response.status_code == 200:
                data = response.json()
                latest_version = data.get("latest_version")
                is_mandatory = data.get("is_mandatory", False)
                download_url = data.get("download_url")

                if latest_version != APP_VERSION and is_mandatory:
                    self.status_label.configure(text="Pembaruan Wajib Diperlukan!", text_color="red")
                    self.show_update_screen(latest_version, download_url)
                else:
                    self.status_label.configure(text="Sistem Siap.")
                    self.show_login_screen()
            else:
                self.status_label.configure(text="Gagal terhubung ke server.", text_color="red")
        except requests.exceptions.RequestException:
            self.status_label.configure(text="Server Offline.", text_color="red")

    def show_update_screen(self, latest_version, download_url):
        update_msg = ctk.CTkLabel(self.main_frame, text=f"Versi {latest_version} tersedia dan wajib diunduh.", wraplength=300)
        update_msg.pack(pady=10)

        def open_url():
            webbrowser.open(download_url)

        btn_download = ctk.CTkButton(self.main_frame, text="Download Update", command=open_url)
        btn_download.pack(pady=20)

    def show_login_screen(self):
        self.status_label.destroy()

        self.entry_username = ctk.CTkEntry(self.main_frame, placeholder_text="Username")
        self.entry_username.pack(pady=10, padx=20, fill="x")

        self.entry_password = ctk.CTkEntry(self.main_frame, placeholder_text="Password", show="*")
        self.entry_password.pack(pady=10, padx=20, fill="x")

        self.btn_login = ctk.CTkButton(self.main_frame, text="Login", command=self.perform_login)
        self.btn_login.pack(pady=20)

    def perform_login(self):
        username = self.entry_username.get()
        password = self.entry_password.get()

        if not username or not password:
            messagebox.showwarning("Peringatan", "Username dan Password wajib diisi.")
            return

        self.btn_login.configure(state="disabled", text="Loading...")
        threading.Thread(target=self._login_thread, args=(username, password)).start()

    def _login_thread(self, username, password):
        try:
            response = requests.post(
                f"{API_BASE_URL}/api/login",
                data={"username": username, "password": password},
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                self.show_dashboard(data["user"])
            else:
                error_msg = response.json().get("message", "Login Gagal")
                messagebox.showerror("Error", error_msg)
                self.btn_login.configure(state="normal", text="Login")
        except requests.exceptions.RequestException:
            messagebox.showerror("Error", "Gagal menghubungi server.")
            self.btn_login.configure(state="normal", text="Login")

    def show_dashboard(self, user_info):
        # Clear main frame
        for widget in self.main_frame.winfo_children():
            widget.destroy()

        self.label_title = ctk.CTkLabel(self.main_frame, text="Dashboard", font=ctk.CTkFont(size=24, weight="bold"))
        self.label_title.pack(pady=20)

        welcome_label = ctk.CTkLabel(self.main_frame, text=f"Selamat Datang, {user_info['username']}")
        welcome_label.pack(pady=10)

        role_label = ctk.CTkLabel(self.main_frame, text=f"Role: {user_info['role']} | Kuota: {user_info['domain_quota']} Domain")
        role_label.pack(pady=5)

        # Further dashboard implementation goes here
        btn_logout = ctk.CTkButton(self.main_frame, text="Logout", command=self.destroy)
        btn_logout.pack(pady=20, side="bottom")

if __name__ == "__main__":
    app = NawalaClient()
    app.mainloop()
