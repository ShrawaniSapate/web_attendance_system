function initializeThemeToggle() {
    const toggle = document.getElementById("theme-toggle");
    if (!toggle) return;

    const root = document.documentElement;
    const setTheme = (theme) => {
        const resolved = theme === "dark" ? "dark" : "light";
        root.setAttribute("data-theme", resolved);
        localStorage.setItem("app-theme", resolved);
        const isDark = resolved === "dark";
        toggle.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
        toggle.setAttribute("aria-pressed", isDark ? "true" : "false");
        toggle.innerHTML = isDark
            ? '<i class="bi bi-sunrise"></i><span id="theme-toggle-label">Light mode</span>'
            : '<i class="bi bi-moon-stars"></i><span id="theme-toggle-label">Dark mode</span>';
    };

    setTheme(root.getAttribute("data-theme") || "light");

    toggle.addEventListener("click", () => {
        const nextTheme = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
        setTheme(nextTheme);
    });
}
function startClock() {
    const clock = document.getElementById("live-clock");
    if (!clock) return;

    const render = () => {
        clock.textContent = new Date().toLocaleString();
    };

    render();
    setInterval(render, 1000);
}

function animateStatCards() {
    const cards = document.querySelectorAll(".stat-card, .role-card, .panel-card");
    cards.forEach((card, index) => {
        card.style.opacity = "0";
        card.style.transform = "translateY(14px)";
        setTimeout(() => {
            card.style.transition = "opacity 0.45s ease, transform 0.45s ease";
            card.style.opacity = "1";
            card.style.transform = "translateY(0)";
        }, index * 70);
    });
}

function initializePasswordToggles() {
    const passwordInputs = document.querySelectorAll('input[type="password"]');

    passwordInputs.forEach((input, index) => {
        if (input.dataset.passwordToggleReady === "true") return;
        if (input.closest(".password-toggle-group")) {
            input.dataset.passwordToggleReady = "true";
            return;
        }

        const wrapper = document.createElement("div");
        wrapper.className = "input-group password-toggle-group";

        const parent = input.parentNode;
        parent.insertBefore(wrapper, input);
        wrapper.appendChild(input);

        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn btn-outline-secondary password-toggle-btn";
        button.setAttribute("aria-label", "Show password");
        button.setAttribute("aria-pressed", "false");
        button.dataset.passwordToggleTarget = input.id || `password-field-${index}`;

        if (!input.id) {
            input.id = button.dataset.passwordToggleTarget;
        }

        button.innerHTML = '<i class="bi bi-eye"></i><span class="password-toggle-label">Show</span>';
        wrapper.appendChild(button);
        input.dataset.passwordToggleReady = "true";

        button.addEventListener("click", () => {
            const isHidden = input.type === "password";
            input.type = isHidden ? "text" : "password";
            button.setAttribute("aria-label", isHidden ? "Hide password" : "Show password");
            button.setAttribute("aria-pressed", isHidden ? "true" : "false");
            button.innerHTML = isHidden
                ? '<i class="bi bi-eye-slash"></i><span class="password-toggle-label">Hide</span>'
                : '<i class="bi bi-eye"></i><span class="password-toggle-label">Show</span>';
        });
    });
}

function formatAttendancePayload(payload) {
    if (!payload || typeof payload !== "object") {
        return String(payload || "No response");
    }

    const lines = [];
    if (payload.message) {
        lines.push(payload.message);
    }
    if (payload.subject) {
        lines.push(`Subject: ${payload.subject}`);
    }
    if (typeof payload.recognized_count === "number") {
        lines.push(`Recognized faces: ${payload.recognized_count}`);
    }
    if (typeof payload.marked_count === "number") {
        lines.push(`Newly marked: ${payload.marked_count}`);
    }
    if (typeof payload.duplicate_count === "number") {
        lines.push(`Already marked: ${payload.duplicate_count}`);
    }
    if (Array.isArray(payload.marked_students) && payload.marked_students.length) {
        lines.push(`Marked students: ${payload.marked_students.join(", ")}`);
    }
    if (Array.isArray(payload.duplicates) && payload.duplicates.length) {
        lines.push(`Duplicate students: ${payload.duplicates.join(", ")}`);
    }
    if (typeof payload.unknown_count === "number") {
        lines.push(`Unknown faces: ${payload.unknown_count}`);
    }
    if (!lines.length) {
        lines.push(JSON.stringify(payload, null, 2));
    }

    return lines.join("\n");
}

function drawAttendanceOverlay(overlayCanvas, video, overlays = []) {
    if (!overlayCanvas || !video) return;

    const width = video.videoWidth || 640;
    const height = video.videoHeight || 480;
    overlayCanvas.width = width;
    overlayCanvas.height = height;

    const context = overlayCanvas.getContext("2d");
    context.clearRect(0, 0, width, height);
    context.lineWidth = 3;
    context.font = "16px 'Plus Jakarta Sans', sans-serif";
    context.textBaseline = "middle";

    overlays.forEach((overlay) => {
        const location = overlay.location || {};
        const left = location.left || 0;
        const top = location.top || 0;
        const right = location.right || 0;
        const bottom = location.bottom || 0;
        const boxWidth = Math.max(right - left, 0);
        const boxHeight = Math.max(bottom - top, 0);
        const palette = overlay.status === "marked"
            ? { stroke: "#22c55e", fill: "rgba(34, 197, 94, 0.18)" }
            : overlay.status === "duplicate"
                ? { stroke: "#facc15", fill: "rgba(250, 204, 21, 0.20)" }
                : { stroke: "#ef4444", fill: "rgba(239, 68, 68, 0.20)" };
        const stroke = palette.stroke;
        const fill = palette.fill;
        const label = `${overlay.name} (${overlay.roll_number})`;

        context.strokeStyle = stroke;
        context.fillStyle = fill;
        context.beginPath();
        context.rect(left, top, boxWidth, boxHeight);
        context.fill();
        context.stroke();

        const labelWidth = Math.max(context.measureText(label).width + 24, 120);
        const labelHeight = 28;
        const labelX = left;
        const labelY = Math.max(top - labelHeight - 6, 6);

        context.fillStyle = stroke;
        context.fillRect(labelX, labelY, labelWidth, labelHeight);
        context.fillStyle = "#ffffff";
        context.fillText(label, labelX + 12, labelY + labelHeight / 2 + 1);
    });
}

async function startTeacherCapture() {
    const startButton = document.getElementById("start-attendance-btn");
    const stopButton = document.getElementById("stop-attendance-btn");
    const video = document.getElementById("teacher-video");
    const result = document.getElementById("attendance-result");
    const overlayCanvas = document.getElementById("attendance-overlay");
    if (!startButton || !stopButton || !video || !result) return;

    const slotId = startButton.dataset.attendanceSlot;
    let stream = null;
    let intervalId = null;
    let isPosting = false;

    const stopCapture = () => {
        if (intervalId) {
            clearInterval(intervalId);
            intervalId = null;
        }
        if (stream) {
            stream.getTracks().forEach((track) => track.stop());
            stream = null;
        }
        video.srcObject = null;
        if (overlayCanvas) {
            const context = overlayCanvas.getContext("2d");
            context.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
        }
        startButton.disabled = false;
        stopButton.disabled = true;
    };

    const captureFrame = async () => {
        if (isPosting || !stream) return;
        isPosting = true;

        try {
            const canvas = document.createElement("canvas");
            canvas.width = video.videoWidth || 640;
            canvas.height = video.videoHeight || 480;
            canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);

            const response = await fetch(`/api/attendance/mark/${slotId}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ frame: canvas.toDataURL("image/jpeg") }),
            });
            const payload = await response.json();
            result.textContent = formatAttendancePayload(payload);
            drawAttendanceOverlay(overlayCanvas, video, payload.overlays || []);
        } catch (error) {
            result.textContent = error.message;
            drawAttendanceOverlay(overlayCanvas, video, []);
        } finally {
            isPosting = false;
        }
    };

    startButton.addEventListener("click", async () => {
        try {
            stream = await navigator.mediaDevices.getUserMedia({ video: true });
            video.srcObject = stream;
            result.textContent = "Camera started. Live face scans will run every 4 seconds and matched students will be highlighted on screen.";
            startButton.disabled = true;
            stopButton.disabled = false;

            setTimeout(captureFrame, 1500);
            intervalId = setInterval(captureFrame, 4000);
        } catch (error) {
            result.textContent = error.message;
            stopCapture();
        }
    });

    stopButton.addEventListener("click", () => {
        stopCapture();
        result.textContent = "Attendance session stopped.";
    });

    window.addEventListener("beforeunload", stopCapture);
}


function initializeSubjectClassFilter() {
    const config = window.subjectClassFilterConfig;
    if (!config) return;

    const courseSelect = document.querySelector(config.courseSelector);
    const classMenu = document.querySelector(config.menuSelector);
    const classToggle = document.querySelector(config.toggleSelector);
    const dropdown = document.querySelector(config.dropdownSelector);
    if (!courseSelect || !classMenu || !classToggle || !dropdown) return;

    const options = Array.from(classMenu.querySelectorAll('.multi-select-option'));

    const updateToggleLabel = () => {
        const checked = options.filter((option) => option.querySelector('input:checked'));
        if (!checked.length) {
            classToggle.textContent = 'Select classes';
            return;
        }
        if (checked.length === 1) {
            classToggle.textContent = checked[0].innerText.trim();
            return;
        }
        classToggle.textContent = `${checked.length} classes selected`;
    };

    const applyFilter = () => {
        const selectedCourseId = courseSelect.value;
        options.forEach((option) => {
            const checkbox = option.querySelector('input');
            const optionCourseId = option.dataset.courseId || '';
            const shouldShow = !selectedCourseId || !optionCourseId || optionCourseId === selectedCourseId;
            option.hidden = !shouldShow;
            if (!shouldShow) {
                checkbox.checked = false;
            }
        });
        updateToggleLabel();
    };

    classToggle.addEventListener('click', () => {
        const isOpen = dropdown.classList.toggle('is-open');
        classToggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    });

    options.forEach((option) => {
        const checkbox = option.querySelector('input');
        checkbox.addEventListener('change', updateToggleLabel);
    });

    document.addEventListener('click', (event) => {
        if (!dropdown.contains(event.target)) {
            dropdown.classList.remove('is-open');
            classToggle.setAttribute('aria-expanded', 'false');
        }
    });

    courseSelect.addEventListener('change', applyFilter);
    applyFilter();
}

function renderAttendanceChart() {
    const canvas = document.getElementById("attendanceChart");
    if (!canvas || !window.attendanceChartData) return;

    new Chart(canvas, {
        type: "bar",
        data: {
            labels: window.attendanceChartData.labels,
            datasets: [{
                label: "Attendance %",
                data: window.attendanceChartData.values,
                backgroundColor: ["#4338ca", "#2563eb", "#10b981", "#f59e0b", "#ec4899", "#0ea5e9"],
                borderRadius: 14,
                borderSkipped: false,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100,
                    grid: { color: "rgba(148, 163, 184, 0.18)" }
                },
                x: {
                    grid: { display: false }
                }
            }
        }
    });
}

function printTeacherDefaulters() {
    document.body.classList.add("print-defaulters-mode");
    const cleanup = () => {
        document.body.classList.remove("print-defaulters-mode");
        window.removeEventListener("afterprint", cleanup);
    };
    window.addEventListener("afterprint", cleanup);
    window.print();
}

initializeThemeToggle();
startClock();
animateStatCards();
initializePasswordToggles();
initializeSubjectClassFilter();
startTeacherCapture();
renderAttendanceChart();


