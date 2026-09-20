/**
 * NawalaSentinel — Utilitarian Dashboard Logic (Linear / Cloudflare Style)
 * Client-Side Instant Filtering, Monospace Batch Counter, File Ingestion, Toast System
 */

const ICONS = {
    check: `<svg class="svg-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"></polyline></svg>`,
    alertTriangle: `<svg class="svg-icon" viewBox="0 0 24 24"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`,
    xCircle: `<svg class="svg-icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>`,
    info: `<svg class="svg-icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>`,
    close: `<svg class="svg-icon svg-icon-sm" viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>`
};

// Global Utilitarian Toast Notification
function showToast(message, type = "success", duration = 4000) {
    let container = document.getElementById("toastContainer");
    if (!container) {
        container = document.createElement("div");
        container.id = "toastContainer";
        container.className = "toast-container";
        document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    toast.className = `toast-item toast-${type}`;

    let iconSvg = ICONS.check;
    if (type === "warning") iconSvg = ICONS.alertTriangle;
    if (type === "info") iconSvg = ICONS.info;
    if (type === "error") iconSvg = ICONS.xCircle;

    toast.innerHTML = `
        <div style="flex-shrink: 0; display: flex; align-items: center;">${iconSvg}</div>
        <div class="toast-content">${message}</div>
        <button type="button" class="toast-close" aria-label="Tutup">${ICONS.close}</button>
    `;

    toast.querySelector(".toast-close").addEventListener("click", () => {
        toast.classList.add("toast-fadeout");
        setTimeout(() => toast.remove(), 150);
    });

    container.appendChild(toast);

    setTimeout(() => {
        if (toast.parentNode) {
            toast.classList.add("toast-fadeout");
            setTimeout(() => toast.remove(), 150);
        }
    }, duration);
}

// Utilitarian Confirmation Modal Dialog
function showConfirmDialog({ title, message, confirmText = "Konfirmasi", cancelText = "Batal", isDanger = false, onConfirm }) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";

    backdrop.innerHTML = `
        <div class="modal-box">
            <div class="modal-header">
                <div style="color: ${isDanger ? 'var(--status-blocked-text)' : 'var(--text-main)'};">
                    ${isDanger ? ICONS.alertTriangle : ICONS.info}
                </div>
                <h4 class="modal-title">${title}</h4>
            </div>
            <div class="modal-body">${message}</div>
            <div class="modal-actions">
                <button type="button" class="btn btn-secondary modal-btn-cancel">${cancelText}</button>
                <button type="button" class="btn ${isDanger ? 'btn-danger' : 'btn-primary'} modal-btn-confirm">${confirmText}</button>
            </div>
        </div>
    `;

    document.body.appendChild(backdrop);

    const closeDialog = () => {
        backdrop.style.opacity = "0";
        setTimeout(() => backdrop.remove(), 150);
    };

    backdrop.querySelector(".modal-btn-cancel").addEventListener("click", closeDialog);
    backdrop.addEventListener("click", (e) => {
        if (e.target === backdrop) closeDialog();
    });

    backdrop.querySelector(".modal-btn-confirm").addEventListener("click", () => {
        closeDialog();
        if (typeof onConfirm === "function") onConfirm();
    });
}

document.addEventListener("DOMContentLoaded", () => {
    // Mobile Nav Toggle
    const mobileNavToggle = document.getElementById("mobileNavToggle");
    const navMenu = document.getElementById("navMenu");
    if (mobileNavToggle && navMenu) {
        mobileNavToggle.addEventListener("click", () => {
            navMenu.classList.toggle("is-open");
        });
    }

    // Monospace Textarea Real-time Counter
    const rawDomainsTextarea = document.getElementById("rawDomainsTextarea");
    const domainCounter = document.getElementById("domainCounter");
    if (rawDomainsTextarea && domainCounter) {
        function updateDomainCount() {
            const text = rawDomainsTextarea.value || "";
            const lines = text.split("\n").map(l => l.trim()).filter(l => l.length > 0 && l.includes("."));
            const count = lines.length;
            domainCounter.textContent = `${count.toLocaleString()} domain terdeteksi`;
        }

        rawDomainsTextarea.addEventListener("input", updateDomainCount);
        updateDomainCount();
    }

    // File Ingestion Direct to Monospace Textarea
    const fileInputDirect = document.getElementById("fileInputDirect");
    const fileSelectedName = document.getElementById("fileSelectedName");
    if (fileInputDirect && rawDomainsTextarea) {
        fileInputDirect.addEventListener("change", (e) => {
            const file = e.target.files[0];
            if (!file) return;

            if (fileSelectedName) {
                fileSelectedName.textContent = `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
            }

            const reader = new FileReader();
            reader.onload = (evt) => {
                const content = evt.target.result;
                // Append or replace
                if (rawDomainsTextarea.value.trim().length > 0) {
                    rawDomainsTextarea.value = rawDomainsTextarea.value.trim() + "\n" + content;
                } else {
                    rawDomainsTextarea.value = content;
                }
                rawDomainsTextarea.dispatchEvent(new Event("input"));
                showToast(`File ${file.name} berhasil dimuat ke editor.`, "info");
            };
            reader.readAsText(file);
        });
    }

    // Client-side Instant Segmented Filter & Search
    const segmentedBtns = document.querySelectorAll(".segmented-btn[data-filter]");
    const instantSearchInput = document.getElementById("tableInstantSearch");
    const tableRows = document.querySelectorAll(".table-row-item");

    let currentFilter = "ALL";
    let searchQuery = "";

    function applyTableFilter() {
        let visibleCount = 0;
        tableRows.forEach(row => {
            const rowStatus = row.getAttribute("data-status") || "";
            const rowCf = row.getAttribute("data-cf") || "";
            const rowDomain = row.getAttribute("data-domain") || "";

            const matchesStatus = (currentFilter === "ALL") ||
                                  (currentFilter === "ERROR" && (rowStatus === "TIMEOUT" || rowStatus === "ERROR")) ||
                                  (currentFilter === "PHISHING" && rowCf === "PHISHING") ||
                                  (rowStatus === currentFilter);

            const matchesSearch = !searchQuery || rowDomain.includes(searchQuery);

            if (matchesStatus && matchesSearch) {
                row.style.display = "";
                visibleCount++;
            } else {
                row.style.display = "none";
            }
        });

        // Show / hide empty row if exists
        const emptyRow = document.getElementById("emptyTableRow");
        if (emptyRow) {
            emptyRow.style.display = (visibleCount === 0 && tableRows.length > 0) ? "" : "none";
        }
    }

    if (segmentedBtns.length > 0) {
        segmentedBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                segmentedBtns.forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                currentFilter = btn.getAttribute("data-filter") || "ALL";
                applyTableFilter();
            });
        });
    }

    if (instantSearchInput) {
        instantSearchInput.addEventListener("input", (e) => {
            searchQuery = e.target.value.trim().toLowerCase();
            applyTableFilter();
        });
    }

    // Background Countdown Scheduler Logic (Continuous Endless 5-min Loop)
    const timerElems = document.querySelectorAll(".countdown-timer-display, #countdownTimer");
    const headerCountdown = document.getElementById("headerCountdown");

    let intervalSeconds = 300; // default 5 minutes
    let secondsLeft = 300;

    // Read initial data-seconds if available
    const firstTimer = document.querySelector("[data-seconds]");
    if (firstTimer && firstTimer.dataset.seconds) {
        const parsed = parseInt(firstTimer.dataset.seconds, 10);
        if (!isNaN(parsed) && parsed > 0) {
            secondsLeft = parsed;
        }
    }

    function formatTime(seconds) {
        const safeSeconds = Math.max(0, seconds);
        const mins = Math.floor(safeSeconds / 60);
        const secs = safeSeconds % 60;
        const minsStr = String(mins).padStart(2, '0');
        const secsStr = String(secs).padStart(2, '0');
        return `${minsStr}m ${secsStr}s`;
    }

    function renderTime(seconds) {
        const formatted = formatTime(seconds);
        timerElems.forEach(el => { el.textContent = formatted; });
        if (headerCountdown) headerCountdown.textContent = `(${formatted})`;
    }

    // Sync with backend API
    async function syncSchedulerStats() {
        try {
            const res = await fetch("/api/stats");
            if (res.ok) {
                const data = await res.json();
                if (typeof data.interval_minutes === "number" && data.interval_minutes > 0) {
                    intervalSeconds = data.interval_minutes * 60;
                }
                if (typeof data.next_check_seconds === "number" && data.next_check_seconds > 0) {
                    secondsLeft = data.next_check_seconds;
                    renderTime(secondsLeft);
                }
            }
        } catch (e) {
            // Silently ignore network blip
        }
    }

    function tick() {
        if (secondsLeft <= 0) {
            // Cycle reached 0! Immediately reset and restart next 5-min cycle
            secondsLeft = intervalSeconds;
            renderTime(secondsLeft);

            // Check if user is typing in textarea
            const textarea = document.getElementById("rawDomainsTextarea");
            const isUserEditing = textarea && textarea.value.trim().length > 0 && document.activeElement === textarea;

            if (!isUserEditing) {
                // Soft refresh to show latest scan results
                setTimeout(() => {
                    window.location.reload();
                }, 1500);
            } else {
                syncSchedulerStats();
            }
        } else {
            renderTime(secondsLeft);
            secondsLeft--;
        }
    }

    // Initial render & immediate sync
    renderTime(secondsLeft);
    syncSchedulerStats();

    // 1-second interval for smooth UI countdown
    setInterval(tick, 1000);

    // Periodic sync every 30s to keep in sync with server APScheduler
    setInterval(syncSchedulerStats, 30000);

    // Manual Mass Check Button
    const btnCheckNow = document.getElementById("btnCheckNow");
    if (btnCheckNow) {
        btnCheckNow.addEventListener("click", () => {
            showConfirmDialog({
                title: "Jalankan Pengecekan Massal",
                message: "Sistem akan segera memindai status pemblokiran seluruh domain terdaftar di 4 operator (Telkomsel, XL, IM3, Tri). Pengecekan berjalan di latar belakang.",
                confirmText: "Mulai Pemindaian",
                cancelText: "Batal",
                isDanger: false,
                onConfirm: async () => {
                    const originalHTML = btnCheckNow.innerHTML;
                    btnCheckNow.disabled = true;
                    btnCheckNow.innerHTML = `<span class="spinner"></span> Memeriksa Domain...`;

                    try {
                        const res = await fetch("/api/check-now", { method: "POST" });
                        const data = await res.json();
                        if (res.ok) {
                            showToast(data.message, "success");
                            setTimeout(() => window.location.reload(), 1200);
                        } else {
                            showToast("Gagal mengeksekusi pengecekan: " + (data.detail || data.message), "error");
                            btnCheckNow.disabled = false;
                            btnCheckNow.innerHTML = originalHTML;
                        }
                    } catch (err) {
                        showToast("Terjadi kesalahan jaringan saat mengeksekusi pengecekan.", "error");
                        btnCheckNow.disabled = false;
                        btnCheckNow.innerHTML = originalHTML;
                    }
                }
            });
        });
    }

    // Add Text / Batch Domains Form
    const addTextForm = document.getElementById("addTextForm");
    if (addTextForm) {
        addTextForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const formData = new FormData(addTextForm);
            const btnSubmit = addTextForm.querySelector("button[type='submit']");
            const originalHTML = btnSubmit.innerHTML;

            btnSubmit.disabled = true;
            btnSubmit.innerHTML = `<span class="spinner"></span> Memproses...`;

            try {
                const res = await fetch("/api/domains/add", {
                    method: "POST",
                    body: formData
                });
                const data = await res.json();

                if (res.ok) {
                    if (data.added > 0) {
                        showToast(data.message, "success");
                        addTextForm.reset();
                        setTimeout(() => window.location.reload(), 1000);
                    } else {
                        showToast(data.message, "warning");
                        btnSubmit.disabled = false;
                        btnSubmit.innerHTML = originalHTML;
                    }
                } else {
                    showToast("Gagal: " + (data.message || data.detail || "Terjadi kesalahan"), "error");
                    btnSubmit.disabled = false;
                    btnSubmit.innerHTML = originalHTML;
                }
            } catch (err) {
                showToast("Kesalahan koneksi jaringan saat menyimpan domain.", "error");
                btnSubmit.disabled = false;
                btnSubmit.innerHTML = originalHTML;
            }
        });
    }

    // Single Domain Delete
    document.querySelectorAll(".btn-delete-domain").forEach(btn => {
        btn.addEventListener("click", () => {
            const domainId = btn.dataset.id;
            const domainName = btn.dataset.name;

            showConfirmDialog({
                title: "Hapus Domain",
                message: `Hapus domain <code>${domainName}</code> dan riwayat pengecekannya dari database?`,
                confirmText: "Hapus",
                cancelText: "Batal",
                isDanger: true,
                onConfirm: async () => {
                    try {
                        const res = await fetch(`/api/domains/${domainId}/delete`, { method: "POST" });
                        if (res.ok) {
                            showToast(`Domain '${domainName}' berhasil dihapus.`, "info");
                            const row = btn.closest("tr");
                            if (row) row.remove();
                        } else {
                            showToast("Gagal menghapus domain.", "error");
                        }
                    } catch (err) {
                        showToast("Error koneksi saat menghapus domain.", "error");
                    }
                }
            });
        });
    });

    // Single Domain Re-check
    document.querySelectorAll(".btn-recheck-domain").forEach(btn => {
        btn.addEventListener("click", async () => {
            const domainId = btn.dataset.id;
            const originalHTML = btn.innerHTML;

            btn.disabled = true;
            btn.innerHTML = `<span class="spinner"></span>`;

            try {
                const res = await fetch(`/api/check-domain/${domainId}`, { method: "POST" });
                if (res.ok) {
                    showToast("Pengecekan domain selesai.", "success");
                    setTimeout(() => window.location.reload(), 800);
                } else {
                    showToast("Gagal mengecek domain.", "error");
                    btn.disabled = false;
                    btn.innerHTML = originalHTML;
                }
            } catch (err) {
                showToast("Error koneksi saat mengecek domain.", "error");
                btn.disabled = false;
                btn.innerHTML = originalHTML;
            }
        });
    });

    // Test Telegram Alert
    const btnTestTelegram = document.getElementById("btnTestTelegram");
    if (btnTestTelegram) {
        btnTestTelegram.addEventListener("click", async () => {
            const tokenInput = document.getElementById("telegram_token");
            const chatIdInput = document.getElementById("telegram_chat_id");

            const formData = new FormData();
            if (tokenInput) formData.append("telegram_token", tokenInput.value);
            if (chatIdInput) formData.append("telegram_chat_id", chatIdInput.value);

            const originalHTML = btnTestTelegram.innerHTML;
            btnTestTelegram.disabled = true;
            btnTestTelegram.innerHTML = `<span class="spinner"></span> Mengirim...`;

            try {
                const res = await fetch("/api/settings/test-telegram", {
                    method: "POST",
                    body: formData
                });
                const data = await res.json();
                if (res.ok) {
                    showToast(data.message, "success");
                } else {
                    showToast(data.message || "Gagal mengirim notifikasi.", "error");
                }
            } catch (err) {
                showToast("Kesalahan koneksi saat tes Telegram.", "error");
            } finally {
                btnTestTelegram.disabled = false;
                btnTestTelegram.innerHTML = originalHTML;
            }
        });
    }

    // Settings Form Save
    const settingsForm = document.getElementById("settingsForm");
    if (settingsForm) {
        settingsForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const formData = new FormData(settingsForm);
            const btnSubmit = settingsForm.querySelector("button[type='submit']");
            const originalHTML = btnSubmit.innerHTML;

            btnSubmit.disabled = true;
            btnSubmit.innerHTML = `<span class="spinner"></span> Menyimpan...`;

            try {
                const res = await fetch("/api/settings/update", {
                    method: "POST",
                    body: formData
                });
                const data = await res.json();
                if (res.ok) {
                    showToast(data.message, "success");
                    setTimeout(() => window.location.reload(), 900);
                } else {
                    showToast("Gagal menyimpan pengaturan: " + (data.message || ""), "error");
                    btnSubmit.disabled = false;
                    btnSubmit.innerHTML = originalHTML;
                }
            } catch (err) {
                showToast("Kesalahan jaringan saat menyimpan pengaturan.", "error");
                btnSubmit.disabled = false;
                btnSubmit.innerHTML = originalHTML;
            }
        });
    }

    // ==========================================
    // SYSTEM & GITHUB SAFE UPDATER LOGIC
    // ==========================================
    const btnOpenUpdateModal = document.getElementById("btnOpenUpdateModal");
    const updateConfirmModal = document.getElementById("updateConfirmModal");
    const btnCloseUpdateModal = document.getElementById("btnCloseUpdateModal");
    const btnCancelUpdate = document.getElementById("btnCancelUpdate");
    const btnStartUpdateExecution = document.getElementById("btnStartUpdateExecution");
    const btnCheckGitVersion = document.getElementById("btnCheckGitVersion");

    const updatePreConfirmation = document.getElementById("updatePreConfirmation");
    const updateConsoleWrapper = document.getElementById("updateConsoleWrapper");
    const updateConsoleOutput = document.getElementById("updateConsoleOutput");
    const updateProgressSpinner = document.getElementById("updateProgressSpinner");

    const gitBranchDisplay = document.getElementById("gitBranchDisplay");
    const gitCommitDisplay = document.getElementById("gitCommitDisplay");
    const gitLastUpdateDisplay = document.getElementById("gitLastUpdateDisplay");

    if (btnOpenUpdateModal && updateConfirmModal) {
        btnOpenUpdateModal.addEventListener("click", () => {
            updateConfirmModal.style.display = "flex";
            if (updatePreConfirmation) updatePreConfirmation.style.display = "block";
            if (updateConsoleWrapper) updateConsoleWrapper.style.display = "none";
            if (btnStartUpdateExecution) {
                btnStartUpdateExecution.disabled = false;
                btnStartUpdateExecution.style.display = "";
            }
            if (btnCancelUpdate) btnCancelUpdate.textContent = "Batal";
        });

        const closeUpdateModal = () => {
            updateConfirmModal.style.display = "none";
        };

        if (btnCloseUpdateModal) btnCloseUpdateModal.addEventListener("click", closeUpdateModal);
        if (btnCancelUpdate) btnCancelUpdate.addEventListener("click", closeUpdateModal);

        updateConfirmModal.addEventListener("click", (e) => {
            if (e.target === updateConfirmModal) closeUpdateModal();
        });
    }

    if (btnCheckGitVersion) {
        btnCheckGitVersion.addEventListener("click", async () => {
            const originalHTML = btnCheckGitVersion.innerHTML;
            btnCheckGitVersion.disabled = true;
            btnCheckGitVersion.innerHTML = `<span class="spinner"></span> Memeriksa...`;

            try {
                const res = await fetch("/api/system/version");
                const data = await res.json();
                if (data) {
                    if (gitBranchDisplay) gitBranchDisplay.textContent = data.branch;
                    if (gitCommitDisplay) gitCommitDisplay.textContent = data.local_commit;
                    if (gitLastUpdateDisplay && data.last_update_time) gitLastUpdateDisplay.textContent = data.last_update_time;
                    showToast(`Status Git: Branch ${data.branch} (${data.local_commit})`, "info");
                }
            } catch (e) {
                showToast("Gagal memeriksa status Git.", "error");
            } finally {
                btnCheckGitVersion.disabled = false;
                btnCheckGitVersion.innerHTML = originalHTML;
            }
        });
    }

    if (btnStartUpdateExecution) {
        btnStartUpdateExecution.addEventListener("click", async () => {
            btnStartUpdateExecution.disabled = true;
            btnStartUpdateExecution.style.display = "none";
            if (btnCancelUpdate) btnCancelUpdate.textContent = "Tutup";

            if (updatePreConfirmation) updatePreConfirmation.style.display = "none";
            if (updateConsoleWrapper) updateConsoleWrapper.style.display = "block";
            if (updateConsoleOutput) updateConsoleOutput.textContent = "Inisialisasi pipeline pembaruan sistem...\n";
            if (updateProgressSpinner) updateProgressSpinner.textContent = "Memproses Pembaruan...";

            try {
                const res = await fetch("/api/system/update", {
                    method: "POST"
                });
                const data = await res.json();

                if (updateConsoleOutput && data.logs) {
                    updateConsoleOutput.textContent = data.logs.join("\n");
                    updateConsoleOutput.scrollTop = updateConsoleOutput.scrollHeight;
                }

                if (data.success) {
                    if (updateProgressSpinner) {
                        updateProgressSpinner.textContent = "Pembaruan Selesai!";
                        updateProgressSpinner.style.color = "var(--accent-emerald)";
                    }
                    showToast(data.message, "success");

                    if (data.version) {
                        if (gitBranchDisplay) gitBranchDisplay.textContent = data.version.branch;
                        if (gitCommitDisplay) gitCommitDisplay.textContent = data.version.local_commit;
                    }
                } else {
                    if (updateProgressSpinner) {
                        updateProgressSpinner.textContent = "Pembaruan Gagal!";
                        updateProgressSpinner.style.color = "#f87171";
                    }
                    showToast(data.message, "error");
                }
            } catch (err) {
                if (updateConsoleOutput) updateConsoleOutput.textContent += `\n[ERROR]: Kesalahan jaringan saat menghubungi server: ${err.message}`;
                if (updateProgressSpinner) updateProgressSpinner.textContent = "Koneksi Terputus / Reloading";
                showToast("Sistem sedang me-reload proses...", "info");
            }
        });
    }
});
