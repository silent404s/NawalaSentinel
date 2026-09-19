/**
 * Interactive Frontend JavaScript for Nawala & Internet Positif Domain Monitor
 */

document.addEventListener("DOMContentLoaded", () => {
    console.log("NawalaSentinel Initialized");

    // Live Countdown Timer Logic
    const timerElem = document.getElementById("countdownTimer");
    if (timerElem) {
        let secondsLeft = parseInt(timerElem.dataset.seconds || "0", 10);

        function updateTimerDisplay() {
            if (secondsLeft <= 0) {
                timerElem.innerHTML = `<span class="spinner"></span> Memindai Nawala...`;
                setTimeout(() => { window.location.reload(); }, 6000);
                return;
            }

            const mins = Math.floor(secondsLeft / 60);
            const secs = secondsLeft % 60;
            const minsStr = String(mins).padStart(2, '0');
            const secsStr = String(secs).padStart(2, '0');

            timerElem.textContent = `${minsStr}m ${secsStr}s`;
            secondsLeft--;
        }

        updateTimerDisplay();
        setInterval(updateTimerDisplay, 1000);
    }


    // Handle Manual Check Now Button
    const btnCheckNow = document.getElementById("btnCheckNow");
    if (btnCheckNow) {
        btnCheckNow.addEventListener("click", async () => {
            if (confirm("Jalankan pengecekan massal sekarang untuk seluruh domain terdaftar?")) {
                const originalText = btnCheckNow.innerHTML;
                btnCheckNow.disabled = true;
                btnCheckNow.innerHTML = `<span class="spinner"></span> Memeriksa Domain...`;

                try {
                    const res = await fetch("/api/check-now", { method: "POST" });
                    const data = await res.json();
                    if (res.ok) {
                        alert("✅ " + data.message);
                        window.location.reload();
                    } else {
                        alert("❌ Gagal mengeksekusi pengecekan: " + (data.detail || data.message));
                    }
                } catch (err) {
                    alert("❌ Terjadi kesalahan jaringan saat mengeksekusi pengecekan.");
                } finally {
                    btnCheckNow.disabled = false;
                    btnCheckNow.innerHTML = originalText;
                }
            }
        });
    }

    // Handle Import Form Submission
    const importForm = document.getElementById("importForm");
    if (importForm) {
        importForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const formData = new FormData(importForm);
            const btnSubmit = importForm.querySelector("button[type='submit']");
            
            btnSubmit.disabled = true;
            btnSubmit.innerHTML = `<span class="spinner"></span> Mengimpor Domain...`;

            try {
                const res = await fetch("/api/domains/import", {
                    method: "POST",
                    body: formData
                });
                const data = await res.json();
                if (res.ok) {
                    alert(`✅ Import Berhasil!\nDomain Ditambahkan: ${data.added}\nDomain Duplikat/Dilewati: ${data.skipped}`);
                    window.location.reload();
                } else {
                    alert("❌ Gagal mengimpor domain.");
                }
            } catch (err) {
                alert("❌ Error mengunggah file.");
            } finally {
                btnSubmit.disabled = false;
                btnSubmit.innerHTML = `Unggah & Impor`;
            }
        });
    }

    // Handle Add Text Domains Form
    const addTextForm = document.getElementById("addTextForm");
    if (addTextForm) {
        addTextForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const formData = new FormData(addTextForm);
            const btnSubmit = addTextForm.querySelector("button[type='submit']");

            btnSubmit.disabled = true;
            btnSubmit.innerHTML = `<span class="spinner"></span> Menyimpan Domain...`;

            try {
                const res = await fetch("/api/domains/add", {
                    method: "POST",
                    body: formData
                });
                const data = await res.json();
                if (res.ok) {
                    alert(`✅ Domain Berhasil Ditambahkan!\nTotal Ditambahkan: ${data.added}`);
                    window.location.reload();
                } else {
                    alert("❌ Gagal menambahkan domain.");
                }
            } catch (err) {
                alert("❌ Error jaringan.");
            } finally {
                btnSubmit.disabled = false;
                btnSubmit.innerHTML = `Tambahkan Domain`;
            }
        });
    }

    // Handle Delete Domain
    document.querySelectorAll(".btn-delete-domain").forEach(btn => {
        btn.addEventListener("click", async () => {
            const domainId = btn.dataset.id;
            const domainName = btn.dataset.name;

            if (confirm(`Apakah Anda yakin ingin menghapus domain '${domainName}' dari pemantauan?`)) {
                try {
                    const res = await fetch(`/api/domains/${domainId}/delete`, { method: "POST" });
                    if (res.ok) {
                        const row = btn.closest("tr");
                        if (row) row.remove();
                    } else {
                        alert("❌ Gagal menghapus domain.");
                    }
                } catch (err) {
                    alert("❌ Error menghapus domain.");
                }
            }
        });
    });

    // Handle Single Domain Re-check
    document.querySelectorAll(".btn-recheck-domain").forEach(btn => {
        btn.addEventListener("click", async () => {
            const domainId = btn.dataset.id;
            const originalHTML = btn.innerHTML;

            btn.disabled = true;
            btn.innerHTML = `<span class="spinner"></span>`;

            try {
                const res = await fetch(`/api/check-domain/${domainId}`, { method: "POST" });
                if (res.ok) {
                    window.location.reload();
                } else {
                    alert("❌ Gagal mengecek domain.");
                }
            } catch (err) {
                alert("❌ Error mengecek domain.");
            } finally {
                btn.disabled = false;
                btn.innerHTML = originalHTML;
            }
        });
    });

    // Handle Test Telegram Alert Button
    const btnTestTelegram = document.getElementById("btnTestTelegram");
    if (btnTestTelegram) {
        btnTestTelegram.addEventListener("click", async () => {
            const tokenInput = document.getElementById("telegram_token");
            const chatIdInput = document.getElementById("telegram_chat_id");

            const formData = new FormData();
            if (tokenInput) formData.append("telegram_token", tokenInput.value);
            if (chatIdInput) formData.append("telegram_chat_id", chatIdInput.value);

            btnTestTelegram.disabled = true;
            btnTestTelegram.innerHTML = `<span class="spinner"></span> Mengirim Pesan...`;

            try {
                const res = await fetch("/api/settings/test-telegram", {
                    method: "POST",
                    body: formData
                });
                const data = await res.json();
                if (res.ok) {
                    alert("✅ " + data.message);
                } else {
                    alert("❌ " + (data.message || "Gagal mengirim notifikasi test."));
                }
            } catch (err) {
                alert("❌ Kesalahan koneksi saat tes Telegram.");
            } finally {
                btnTestTelegram.disabled = false;
                btnTestTelegram.innerHTML = `✈️ Tes Notifikasi Telegram`;
            }
        });
    }

    // Handle Settings Form Save
    const settingsForm = document.getElementById("settingsForm");
    if (settingsForm) {
        settingsForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const formData = new FormData(settingsForm);

            try {
                const res = await fetch("/api/settings/update", {
                    method: "POST",
                    body: formData
                });
                const data = await res.json();
                if (res.ok) {
                    alert("✅ " + data.message);
                    window.location.reload();
                } else {
                    alert("❌ Gagal menyimpan pengaturan.");
                }
            } catch (err) {
                alert("❌ Kesalahan jaringan saat menyimpan pengaturan.");
            }
        });
    }
});
