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

    // Client-side Instant Segmented Filter, Category Filter & Search
    const segmentedBtns = document.querySelectorAll(".segmented-btn[data-filter]");
    const categoryFilterSelect = document.getElementById("categoryFilterSelect");
    const instantSearchInput = document.getElementById("tableInstantSearch");

    let currentFilter = "ALL";
    let currentCategoryFilter = "ALL";
    let searchQuery = "";

    function sortTableAlphabetically() {
        const table = document.getElementById("domainsDataTable");
        if (!table) return;
        const tbody = table.querySelector("tbody");
        if (!tbody) return;
        const rows = Array.from(tbody.querySelectorAll(".table-row-item"));
        rows.sort((a, b) => {
            const domainA = (a.getAttribute("data-domain") || "").toLowerCase();
            const domainB = (b.getAttribute("data-domain") || "").toLowerCase();
            return domainA.localeCompare(domainB);
        });
        rows.forEach(row => tbody.appendChild(row));
    }

    function applyTableFilter() {
        const currentRows = document.querySelectorAll("#domainsDataTable tbody .table-row-item");
        let visibleCount = 0;
        currentRows.forEach(row => {
            const rowStatus = row.getAttribute("data-status") || "";
            const rowCf = row.getAttribute("data-cf") || "";
            const rowDomain = row.getAttribute("data-domain") || "";
            const rowCategory = (row.getAttribute("data-category") || "").toLowerCase();

            const matchesStatus = (currentFilter === "ALL") ||
                                  (currentFilter === "ERROR" && (rowStatus === "TIMEOUT" || rowStatus === "ERROR")) ||
                                  (currentFilter === "PHISHING" && rowCf === "PHISHING") ||
                                  (rowStatus === currentFilter);

            const matchesCategory = (currentCategoryFilter === "ALL") || 
                                    (rowCategory === currentCategoryFilter.toLowerCase());

            const matchesSearch = !searchQuery || rowDomain.includes(searchQuery) || rowCategory.includes(searchQuery);

            if (matchesStatus && matchesCategory && matchesSearch) {
                row.style.display = "";
                visibleCount++;
                const numCell = row.querySelector(".cell-number");
                if (numCell) {
                    numCell.textContent = visibleCount;
                }
            } else {
                row.style.display = "none";
            }
        });

        // Show / hide empty row if exists
        const emptyRow = document.getElementById("emptyTableRow");
        if (emptyRow) {
            emptyRow.style.display = (visibleCount === 0 && currentRows.length > 0) ? "" : "none";
        }
    }

    // Auto-sort alphabetically & apply initial numbering
    sortTableAlphabetically();
    applyTableFilter();

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

    if (categoryFilterSelect) {
        categoryFilterSelect.addEventListener("change", () => {
            currentCategoryFilter = categoryFilterSelect.value;
            applyTableFilter();
        });
    }

    if (instantSearchInput) {
        instantSearchInput.addEventListener("input", (e) => {
            searchQuery = e.target.value.trim().toLowerCase();
            applyTableFilter();
        });
    }

    // Click-to-copy Domain Link with visual feedback
    document.addEventListener("click", (e) => {
        const copyTarget = e.target.closest(".clickable-copy");
        if (copyTarget) {
            const textToCopy = copyTarget.getAttribute("data-copy") || copyTarget.innerText.trim();
            if (textToCopy) {
                const onCopySuccess = () => {
                    copyTarget.classList.add("copied");
                    setTimeout(() => copyTarget.classList.remove("copied"), 1500);
                    showToast(`Tersalin: ${textToCopy}`, "success");
                };

                if (navigator.clipboard && window.isSecureContext) {
                    navigator.clipboard.writeText(textToCopy)
                        .then(onCopySuccess)
                        .catch(() => fallbackCopyText(textToCopy, onCopySuccess));
                } else {
                    fallbackCopyText(textToCopy, onCopySuccess);
                }
            }
        }
    });

    function fallbackCopyText(text, cb) {
        const textArea = document.createElement("textarea");
        textArea.value = text;
        textArea.style.position = "fixed";
        textArea.style.left = "-999999px";
        textArea.style.top = "-999999px";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        try {
            document.execCommand("copy");
            if (cb) cb();
        } catch (err) {
            showToast("Gagal menyalin link.", "error");
        }
        document.body.removeChild(textArea);
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

    // ==========================================================================
    // Category Selection Pop-up Modal & Domain Batch Submission Flow
    // ==========================================================================
    const addTextForm = document.getElementById("addTextForm");
    const categoryModal = document.getElementById("categoryModal");
    const btnCloseCategoryModal = document.getElementById("btnCloseCategoryModal");
    const btnCancelCategoryModal = document.getElementById("btnCancelCategoryModal");
    const btnConfirmCategoryModal = document.getElementById("btnConfirmCategoryModal");
    const modalDomainCount = document.getElementById("modalDomainCount");
    const modalCustomCategoryWrapper = document.getElementById("modalCustomCategoryWrapper");
    const modalCustomCategoryInput = document.getElementById("modalCustomCategoryInput");
    const categoryRadios = document.querySelectorAll('input[name="modal_category_choice"]');

    // Handle Category Radio Option Toggle in Modal
    if (categoryRadios.length > 0) {
        categoryRadios.forEach(radio => {
            radio.addEventListener("change", () => {
                document.querySelectorAll(".category-radio-item").forEach(item => item.classList.remove("selected"));
                const parentLabel = radio.closest(".category-radio-item");
                if (parentLabel) parentLabel.classList.add("selected");

                if (radio.value === "__custom__") {
                    if (modalCustomCategoryWrapper) {
                        modalCustomCategoryWrapper.style.display = "block";
                    }
                    if (modalCustomCategoryInput) {
                        modalCustomCategoryInput.focus();
                    }
                } else {
                    if (modalCustomCategoryWrapper) {
                        modalCustomCategoryWrapper.style.display = "none";
                    }
                }
            });
        });
    }

    // Modal Close Logic
    const closeCategoryModal = () => {
        if (categoryModal) categoryModal.style.display = "none";
    };
    if (btnCloseCategoryModal) btnCloseCategoryModal.addEventListener("click", closeCategoryModal);
    if (btnCancelCategoryModal) btnCancelCategoryModal.addEventListener("click", closeCategoryModal);
    if (categoryModal) {
        categoryModal.addEventListener("click", (e) => {
            if (e.target === categoryModal) closeCategoryModal();
        });
    }

    // Intercept "Simpan & Proses Domain" to Show Category Pop-up Modal
    if (addTextForm) {
        addTextForm.addEventListener("submit", (e) => {
            e.preventDefault();

            const text = rawDomainsTextarea ? rawDomainsTextarea.value.trim() : "";
            const lines = text.split("\n").map(l => l.trim()).filter(l => l.length > 0 && l.includes("."));
            if (lines.length === 0) {
                showToast("Masukkan minimal 1 domain atau link valid terlebih dahulu!", "warning");
                if (rawDomainsTextarea) rawDomainsTextarea.focus();
                return;
            }

            if (categoryModal) {
                if (modalDomainCount) {
                    modalDomainCount.textContent = lines.length.toLocaleString();
                }
                categoryModal.style.display = "flex";
            } else {
                // Fallback if modal is absent
                submitDomainBatch("General");
            }
        });
    }

    // Modal Confirm & Save Domain Execution
    if (btnConfirmCategoryModal) {
        btnConfirmCategoryModal.addEventListener("click", async () => {
            const checkedRadio = document.querySelector('input[name="modal_category_choice"]:checked');
            let chosenCategory = checkedRadio ? checkedRadio.value : "General";

            if (chosenCategory === "__custom__") {
                const customVal = modalCustomCategoryInput ? modalCustomCategoryInput.value.trim() : "";
                if (!customVal) {
                    showToast("Silakan ketik nama kategori baru Anda!", "warning");
                    if (modalCustomCategoryInput) modalCustomCategoryInput.focus();
                    return;
                }
                chosenCategory = customVal;
            }

            await submitDomainBatch(chosenCategory);
        });
    }

    // Core Batch Domain Submission Helper
    async function submitDomainBatch(categoryName) {
        if (!addTextForm) return;

        const originalHTML = btnConfirmCategoryModal ? btnConfirmCategoryModal.innerHTML : "";
        if (btnConfirmCategoryModal) {
            btnConfirmCategoryModal.disabled = true;
            btnConfirmCategoryModal.innerHTML = `<span class="spinner"></span> Menyimpan...`;
        }

        const formData = new FormData(addTextForm);
        formData.set("category", categoryName);

        try {
            const res = await fetch("/api/domains/add", {
                method: "POST",
                body: formData
            });
            const data = await res.json();

            if (res.ok) {
                if (data.added > 0) {
                    if (categoryModal) categoryModal.style.display = "none";
                    showToast(`Berhasil menyimpan ${data.added} domain ke kategori "${categoryName}".`, "success");
                    addTextForm.reset();
                    const fileSelected = document.getElementById("fileSelectedName");
                    if (fileSelected) fileSelected.textContent = "";
                    const domainCounterEl = document.getElementById("domainCounter");
                    if (domainCounterEl) domainCounterEl.textContent = "0 domain terdeteksi";
                    setTimeout(() => window.location.reload(), 900);
                } else {
                    showToast(data.message || "Tidak ada domain baru yang ditambahkan.", "warning");
                    if (btnConfirmCategoryModal) {
                        btnConfirmCategoryModal.disabled = false;
                        btnConfirmCategoryModal.innerHTML = originalHTML;
                    }
                }
            } else {
                showToast("Gagal: " + (data.message || data.detail || "Terjadi kesalahan"), "error");
                if (btnConfirmCategoryModal) {
                    btnConfirmCategoryModal.disabled = false;
                    btnConfirmCategoryModal.innerHTML = originalHTML;
                }
            }
        } catch (err) {
            showToast("Kesalahan koneksi jaringan saat menyimpan domain.", "error");
            if (btnConfirmCategoryModal) {
                btnConfirmCategoryModal.disabled = false;
                btnConfirmCategoryModal.innerHTML = originalHTML;
            }
        }
    }

    // ==========================================
    // SINGLE DOMAIN CATEGORY EDIT MODAL
    // ==========================================
    const editSingleCategoryModal = document.getElementById("editSingleCategoryModal");
    const editSingleDomainName = document.getElementById("editSingleDomainName");
    const editSingleDomainId = document.getElementById("editSingleDomainId");
    const editSingleCategorySelect = document.getElementById("editSingleCategorySelect");
    const editSingleCustomWrapper = document.getElementById("editSingleCustomWrapper");
    const editSingleCustomInput = document.getElementById("editSingleCustomInput");
    const btnCloseEditSingleModal = document.getElementById("btnCloseEditSingleModal");
    const btnCancelEditSingleModal = document.getElementById("btnCancelEditSingleModal");
    const btnConfirmEditSingleModal = document.getElementById("btnConfirmEditSingleModal");

    // Open Single Domain Edit Modal on Category Badge Click
    document.addEventListener("click", (e) => {
        const badge = e.target.closest(".clickable-category-edit");
        if (badge && editSingleCategoryModal) {
            const domainId = badge.getAttribute("data-id");
            const domainName = badge.getAttribute("data-name") || "Domain";
            const currentCat = badge.getAttribute("data-category") || "General";

            if (editSingleDomainId) editSingleDomainId.value = domainId;
            if (editSingleDomainName) editSingleDomainName.textContent = domainName;

            // Set select value
            let foundOption = false;
            if (editSingleCategorySelect) {
                Array.from(editSingleCategorySelect.options).forEach(opt => {
                    if (opt.value.toLowerCase() === currentCat.toLowerCase()) {
                        opt.selected = true;
                        foundOption = true;
                    }
                });

                if (!foundOption) {
                    editSingleCategorySelect.value = "__custom__";
                    if (editSingleCustomWrapper) editSingleCustomWrapper.style.display = "block";
                    if (editSingleCustomInput) editSingleCustomInput.value = currentCat;
                } else {
                    if (editSingleCustomWrapper) editSingleCustomWrapper.style.display = "none";
                    if (editSingleCustomInput) editSingleCustomInput.value = "";
                }
            }

            editSingleCategoryModal.style.display = "flex";
        }
    });

    if (editSingleCategorySelect) {
        editSingleCategorySelect.addEventListener("change", () => {
            if (editSingleCategorySelect.value === "__custom__") {
                if (editSingleCustomWrapper) editSingleCustomWrapper.style.display = "block";
                if (editSingleCustomInput) {
                    editSingleCustomInput.focus();
                }
            } else {
                if (editSingleCustomWrapper) editSingleCustomWrapper.style.display = "none";
            }
        });
    }

    const closeEditSingleModal = () => {
        if (editSingleCategoryModal) editSingleCategoryModal.style.display = "none";
    };
    if (btnCloseEditSingleModal) btnCloseEditSingleModal.addEventListener("click", closeEditSingleModal);
    if (btnCancelEditSingleModal) btnCancelEditSingleModal.addEventListener("click", closeEditSingleModal);
    if (editSingleCategoryModal) {
        editSingleCategoryModal.addEventListener("click", (e) => {
            if (e.target === editSingleCategoryModal) closeEditSingleModal();
        });
    }

    if (btnConfirmEditSingleModal) {
        btnConfirmEditSingleModal.addEventListener("click", async () => {
            const domainId = editSingleDomainId ? editSingleDomainId.value : "";
            if (!domainId) return;

            let chosenCat = editSingleCategorySelect ? editSingleCategorySelect.value : "General";
            if (chosenCat === "__custom__") {
                const customVal = editSingleCustomInput ? editSingleCustomInput.value.trim() : "";
                if (!customVal) {
                    showToast("Silakan ketik nama kategori baru!", "warning");
                    if (editSingleCustomInput) editSingleCustomInput.focus();
                    return;
                }
                chosenCat = customVal;
            }

            const origHtml = btnConfirmEditSingleModal.innerHTML;
            btnConfirmEditSingleModal.disabled = true;
            btnConfirmEditSingleModal.innerHTML = `<span class="spinner"></span> Menyimpan...`;

            try {
                const formData = new FormData();
                formData.append("category", chosenCat);

                const res = await fetch(`/api/domains/${domainId}/category`, {
                    method: "POST",
                    body: formData
                });
                const data = await res.json();

                if (res.ok) {
                    showToast(data.message, "success");
                    closeEditSingleModal();

                    // Update row in table immediately
                    const badge = document.querySelector(`.clickable-category-edit[data-id="${domainId}"]`);
                    if (badge) {
                        badge.setAttribute("data-category", chosenCat);
                        const textSpan = badge.querySelector(".badge-category-text");
                        if (textSpan) textSpan.textContent = chosenCat;
                        const row = badge.closest(".table-row-item");
                        if (row) row.setAttribute("data-category", chosenCat.toLowerCase());
                    }

                    setTimeout(() => window.location.reload(), 600);
                } else {
                    showToast(data.message || "Gagal mengubah kategori.", "error");
                }
            } catch (err) {
                showToast("Kesalahan jaringan saat mengubah kategori.", "error");
            } finally {
                btnConfirmEditSingleModal.disabled = false;
                btnConfirmEditSingleModal.innerHTML = origHtml;
            }
        });
    }

    // ==========================================
    // GLOBAL RENAME CATEGORY MODAL
    // ==========================================
    const renameCategoryModal = document.getElementById("renameCategoryModal");
    const btnOpenRenameCategoryModal = document.getElementById("btnOpenRenameCategoryModal");
    const renameOldCategorySelect = document.getElementById("renameOldCategorySelect");
    const renameNewCategoryInput = document.getElementById("renameNewCategoryInput");
    const btnCloseRenameCategoryModal = document.getElementById("btnCloseRenameCategoryModal");
    const btnCancelRenameCategoryModal = document.getElementById("btnCancelRenameCategoryModal");
    const btnConfirmRenameCategoryModal = document.getElementById("btnConfirmRenameCategoryModal");

    if (btnOpenRenameCategoryModal && renameCategoryModal) {
        btnOpenRenameCategoryModal.addEventListener("click", () => {
            renameCategoryModal.style.display = "flex";
            if (renameNewCategoryInput) {
                renameNewCategoryInput.value = "";
                renameNewCategoryInput.focus();
            }
        });

        const closeRenameModal = () => {
            renameCategoryModal.style.display = "none";
        };
        if (btnCloseRenameCategoryModal) btnCloseRenameCategoryModal.addEventListener("click", closeRenameModal);
        if (btnCancelRenameCategoryModal) btnCancelRenameCategoryModal.addEventListener("click", closeRenameModal);
        renameCategoryModal.addEventListener("click", (e) => {
            if (e.target === renameCategoryModal) closeRenameModal();
        });
    }

    if (btnConfirmRenameCategoryModal) {
        btnConfirmRenameCategoryModal.addEventListener("click", async () => {
            const oldCat = renameOldCategorySelect ? renameOldCategorySelect.value.trim() : "";
            const newCat = renameNewCategoryInput ? renameNewCategoryInput.value.trim() : "";

            if (!oldCat || !newCat) {
                showToast("Nama kategori lama dan baru harus diisi!", "warning");
                if (renameNewCategoryInput) renameNewCategoryInput.focus();
                return;
            }

            if (oldCat.toLowerCase() === newCat.toLowerCase()) {
                showToast("Nama kategori baru tidak boleh sama dengan kategori lama!", "warning");
                return;
            }

            const origHtml = btnConfirmRenameCategoryModal.innerHTML;
            btnConfirmRenameCategoryModal.disabled = true;
            btnConfirmRenameCategoryModal.innerHTML = `<span class="spinner"></span> Menyimpan...`;

            try {
                const formData = new FormData();
                formData.append("old_category", oldCat);
                formData.append("new_category", newCat);

                const res = await fetch("/api/categories/rename", {
                    method: "POST",
                    body: formData
                });
                const data = await res.json();

                if (res.ok) {
                    showToast(data.message, "success");
                    if (renameCategoryModal) renameCategoryModal.style.display = "none";
                    setTimeout(() => window.location.reload(), 800);
                } else {
                    showToast(data.message || "Gagal mengubah nama kategori.", "error");
                }
            } catch (err) {
                showToast("Kesalahan jaringan saat mengubah nama kategori.", "error");
            } finally {
                btnConfirmRenameCategoryModal.disabled = false;
                btnConfirmRenameCategoryModal.innerHTML = origHtml;
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

    // ==========================================
    // SCHEDULER & PERFORMANCE PRESETS & ESTIMATOR
    // ==========================================
    const checkIntervalInput = document.getElementById("check_interval");
    const chunkSizeInput = document.getElementById("chunk_size");
    const concurrentChecksInput = document.getElementById("concurrent_checks");
    const chunkDelayInput = document.getElementById("chunk_delay");
    const presetBtns = document.querySelectorAll(".preset-btn");

    const estDuration = document.getElementById("estDuration");
    const estCpuLoad = document.getElementById("estCpuLoad");
    const estCycleFit = document.getElementById("estCycleFit");
    const estKomdigiSafety = document.getElementById("estKomdigiSafety");

    function updatePerformanceEstimates() {
        if (!checkIntervalInput || !chunkSizeInput || !concurrentChecksInput || !chunkDelayInput) return;

        const intervalMins = Math.max(1, parseInt(checkIntervalInput.value, 10) || 5);
        const chunkSize = Math.max(10, parseInt(chunkSizeInput.value, 10) || 1000);
        const concurrent = Math.max(5, parseInt(concurrentChecksInput.value, 10) || 30);
        const delay = Math.max(0, parseFloat(chunkDelayInput.value) || 0);

        // Simulation for 1.000 domains
        const simTotal = 1000;
        const totalBatches = Math.ceil(simTotal / chunkSize);
        const avgSecPerDomain = 1.8; // average DNS + HTTP + TrustPositif latency with parallelism
        const batchDuration = (Math.min(simTotal, chunkSize) / concurrent) * avgSecPerDomain;
        const totalDelays = (totalBatches - 1) * delay;
        const totalDurationSec = Math.round((totalBatches * batchDuration) + totalDelays);

        if (estDuration) {
            if (totalDurationSec < 60) {
                estDuration.textContent = `~${totalDurationSec} detik`;
            } else {
                const mins = Math.floor(totalDurationSec / 60);
                const secs = totalDurationSec % 60;
                estDuration.textContent = `~${mins}m ${secs}s`;
            }
        }

        if (estCpuLoad) {
            if (concurrent <= 35) {
                estCpuLoad.textContent = "Ringan (< 15% CPU)";
                estCpuLoad.style.color = "#34d399";
            } else if (concurrent <= 60) {
                estCpuLoad.textContent = "Sedang (15 - 30% CPU)";
                estCpuLoad.style.color = "#38bdf8";
            } else {
                estCpuLoad.textContent = "Tinggi (> 40% CPU)";
                estCpuLoad.style.color = "#f87171";
            }
        }

        if (estCycleFit) {
            const cycleSec = intervalMins * 60;
            if (totalDurationSec <= cycleSec * 0.7) {
                estCycleFit.textContent = "Leluasa (Selesai Cepat)";
                estCycleFit.style.color = "#34d399";
            } else if (totalDurationSec <= cycleSec) {
                estCycleFit.textContent = "Pas (Tepat Waktu)";
                estCycleFit.style.color = "#fbbf24";
            } else {
                estCycleFit.textContent = "⚠️ Melebihi Interval!";
                estCycleFit.style.color = "#f87171";
            }
        }

        const estKomdigiDesc = document.getElementById("estKomdigiDesc");

        // Komdigi TrustPositif Real Traffic Calculation:
        // Setiap domain melakukan 1 kueri REST API ke server trustpositif.komdigi.go.id
        const requestsPerHour = Math.round((chunkSize * 60) / intervalMins);
        const activeQps = Math.round((chunkSize / Math.max(1, totalDurationSec)) * 10) / 10;
        const cooldownSec = Math.max(0, (intervalMins * 60) - totalDurationSec);

        if (estKomdigiSafety) {
            if ((intervalMins <= 1 && chunkSize >= 500) || requestsPerHour >= 30000 || cooldownSec < 10) {
                estKomdigiSafety.textContent = "⚠️ Risiko Tinggi (WAF Komdigi)";
                estKomdigiSafety.style.color = "#f87171";
                if (estKomdigiDesc) {
                    estKomdigiDesc.textContent = `~${requestsPerHour.toLocaleString()} req/jam (${activeQps} req/dtk). Berpotensi terkena rate-limit / ban IP jika 24/7.`;
                    estKomdigiDesc.style.color = "#fca5a5";
                }
            } else if ((intervalMins <= 2 && chunkSize >= 500) || requestsPerHour >= 10000 || cooldownSec < 45) {
                estKomdigiSafety.textContent = "🟡 Beban Sedang / Waspada";
                estKomdigiSafety.style.color = "#fbbf24";
                if (estKomdigiDesc) {
                    estKomdigiDesc.textContent = `~${requestsPerHour.toLocaleString()} req/jam (${activeQps} req/dtk). Jeda istirahat singkat (${Math.round(cooldownSec)}s).`;
                    estKomdigiDesc.style.color = "#fde68a";
                }
            } else {
                estKomdigiSafety.textContent = "🟢 Aman & Wajar";
                estKomdigiSafety.style.color = "#34d399";
                if (estKomdigiDesc) {
                    const cooldownMins = Math.round(cooldownSec / 60 * 10) / 10;
                    estKomdigiDesc.textContent = `~${requestsPerHour.toLocaleString()} req/jam (${activeQps} req/dtk). Server Komdigi memiliki jeda istirahat ~${cooldownMins} mnt.`;
                    estKomdigiDesc.style.color = "var(--text-muted)";
                }
            }
        }
    }

    if (presetBtns.length > 0) {
        presetBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                presetBtns.forEach(b => b.classList.remove("active"));
                btn.classList.add("active");

                if (checkIntervalInput && btn.dataset.interval) checkIntervalInput.value = btn.dataset.interval;
                if (chunkSizeInput && btn.dataset.chunk) chunkSizeInput.value = btn.dataset.chunk;
                if (concurrentChecksInput && btn.dataset.concurrent) concurrentChecksInput.value = btn.dataset.concurrent;
                if (chunkDelayInput && btn.dataset.delay) chunkDelayInput.value = btn.dataset.delay;

                updatePerformanceEstimates();
                showToast("Preset diterapkan: " + btn.textContent.trim(), "info");
            });
        });
    }

    [checkIntervalInput, chunkSizeInput, concurrentChecksInput, chunkDelayInput].forEach(input => {
        if (input) {
            input.addEventListener("input", updatePerformanceEstimates);
        }
    });

    // Initial estimate calculation
    updatePerformanceEstimates();

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

    // ==========================================
    // Keamanan Akun: Logout Semua Sesi & Reset 2FA
    // ==========================================
    const btnLogoutAllSessions = document.getElementById("btnLogoutAllSessions");
    if (btnLogoutAllSessions) {
        btnLogoutAllSessions.addEventListener("click", async () => {
            if (!confirm("Apakah Anda yakin ingin mengakhiri dan me-logout seluruh sesi aktif akun ini di semua perangkat? Anda akan otomatis logout dari sesi saat ini.")) {
                return;
            }

            try {
                const res = await fetch("/api/auth/logout-all", { method: "POST" });
                const data = await res.json();
                if (res.ok) {
                    showToast(data.message || "Seluruh sesi telah diputus. Mengalihkan...", "success");
                    setTimeout(() => window.location.href = "/login?logged_out=1", 1000);
                } else {
                    showToast(data.message || "Gagal memutus sesi.", "error");
                }
            } catch (err) {
                showToast("Kesalahan jaringan saat memutus sesi.", "error");
            }
        });
    }

    const reset2faModal = document.getElementById("reset2faModal");
    const btnOpenReset2faModal = document.getElementById("btnOpenReset2faModal");
    const btnCloseReset2faModal = document.getElementById("btnCloseReset2faModal");
    const btnCancelReset2fa = document.getElementById("btnCancelReset2fa");
    const reset2faForm = document.getElementById("reset2faForm");
    const resetCurrentPassword = document.getElementById("resetCurrentPassword");

    if (btnOpenReset2faModal && reset2faModal) {
        btnOpenReset2faModal.addEventListener("click", () => {
            reset2faModal.style.display = "flex";
            if (resetCurrentPassword) {
                resetCurrentPassword.value = "";
                resetCurrentPassword.focus();
            }
        });

        const closeResetModal = () => { reset2faModal.style.display = "none"; };
        if (btnCloseReset2faModal) btnCloseReset2faModal.addEventListener("click", closeResetModal);
        if (btnCancelReset2fa) btnCancelReset2fa.addEventListener("click", closeResetModal);
        reset2faModal.addEventListener("click", (e) => {
            if (e.target === reset2faModal) closeResetModal();
        });
    }

    if (reset2faForm) {
        reset2faForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const password = resetCurrentPassword ? resetCurrentPassword.value : "";
            if (!password) {
                showToast("Masukkan password akun Anda untuk konfirmasi!", "warning");
                return;
            }

            const btnConfirm = document.getElementById("btnConfirmReset2fa");
            const originalText = btnConfirm ? btnConfirm.innerHTML : "";
            if (btnConfirm) {
                btnConfirm.disabled = true;
                btnConfirm.innerHTML = `<span class="spinner"></span> Mereset...`;
            }

            try {
                const formData = new FormData();
                formData.append("current_password", password);

                const res = await fetch("/api/auth/reset-2fa", {
                    method: "POST",
                    body: formData
                });
                const data = await res.json();

                if (res.ok) {
                    showToast(data.message || "2FA berhasil direset. Mengalihkan ke login...", "success");
                    setTimeout(() => window.location.href = "/login", 1200);
                } else {
                    showToast(data.message || "Gagal mereset 2FA. Password salah.", "error");
                    if (btnConfirm) {
                        btnConfirm.disabled = false;
                        btnConfirm.innerHTML = originalText;
                    }
                }
            } catch (err) {
                showToast("Kesalahan jaringan saat mereset 2FA.", "error");
                if (btnConfirm) {
                    btnConfirm.disabled = false;
                    btnConfirm.innerHTML = originalText;
                }
            }
        });
    }
});
