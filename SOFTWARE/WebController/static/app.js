const state = {
    ports: [],
    status: null,
    syringes: [],
};

const API_BASE = "";
const DEFAULT_SPM = 800.0;

const pumpGrid = document.querySelector("#pump-grid");

async function apiRequest(path, { method = "GET", body = undefined } = {}) {
    const opts = {
        method,
        headers: {},
    };
    if (body !== undefined) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
    }
    const resp = await fetch(`${API_BASE}${path}`, opts);
    const text = await resp.text();
    if (!resp.ok) {
        let message = resp.statusText;
        if (text) {
            try {
                const err = JSON.parse(text);
                message = err.detail || err.message || text;
            } catch {
                message = text;
            }
        }
        throw new Error(message);
    }
    if (!text) {
        return {};
    }
    try {
        return JSON.parse(text);
    } catch {
        return {};
    }
}

const apiGet = (path) => apiRequest(path, { method: "GET" });
const apiPost = (path, body) => apiRequest(path, { method: "POST", body });
const apiPut = (path, body) => apiRequest(path, { method: "PUT", body });

function showToast(message, type = "info", timeout = 2600) {
    const container = document.querySelector("#toast-container");
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.remove();
    }, timeout);
}

function createPumpCards() {
    pumpGrid.innerHTML = "";
    for (let pid = 1; pid <= 4; pid += 1) {
        const card = document.createElement("div");
        card.className = "pump-card";
        card.dataset.pump = String(pid);
        card.innerHTML = `
            <div class="pump-header">
                <h3>Pump ${pid}</h3>
                <span data-field="remaining">余步 --</span>
            </div>

            <div class="control-group">
                <label>注射器型号</label>
                <div class="field-row">
                    <select class="syringe-select"></select>
                    <span data-field="syringe-diam" class="switch">Ø -- mm</span>
                </div>
            </div>

            <div class="control-group">
                <label>速度</label>
                <div class="field-row">
                    <input type="number" step="0.01" value="0.50" data-field="speed-value">
                    <select data-field="speed-unit">
                        <option value="mL/min">mL/min</option>
                        <option value="mL/s">mL/s</option>
                        <option value="mm/s">mm/s</option>
                    </select>
                    <button class="btn small-button" data-action="set-speed">设速度</button>
                </div>
            </div>

            <div class="control-group">
                <label>加速度</label>
                <div class="field-row">
                    <input type="number" step="0.01" value="5.0" data-field="accel-value">
                    <select data-field="accel-unit">
                        <option value="mL/s²">mL/s²</option>
                        <option value="mm/s²">mm/s²</option>
                    </select>
                    <button class="btn small-button" data-action="set-accel">设加速度</button>
                </div>
            </div>

            <div class="control-group">
                <label>体积/位移运行</label>
                <div class="field-row">
                    <input type="number" step="0.001" value="1.000" data-field="run-value">
                    <select data-field="run-unit">
                        <option value="mL">mL</option>
                        <option value="uL">uL</option>
                        <option value="mm">mm</option>
                    </select>
                    <button class="btn small-button stretch" data-action="run">运行</button>
                </div>
                <div class="field-row">
                    <button class="btn small-button" data-action="pause">暂停</button>
                    <button class="btn small-button" data-action="stop">停止</button>
                    <button class="btn small-button" data-action="resume">继续</button>
                </div>
            </div>

            <div class="control-group">
                <label>点动 (JOG)</label>
                <div class="field-row">
                    <input type="number" step="0.001" value="0.100" data-field="jog-value">
                    <select data-field="jog-unit">
                        <option value="mL">mL</option>
                        <option value="uL">uL</option>
                        <option value="mm">mm</option>
                    </select>
                    <button class="btn small-button" data-action="jog" data-direction="-1">◀︎</button>
                    <button class="btn small-button" data-action="jog" data-direction="1">▶︎</button>
                </div>
            </div>

            <div class="control-group">
                <label>步距校准</label>
                <div class="field-row">
                    <input type="number" step="0.001" min="0" data-field="steps-input" value="${DEFAULT_SPM.toFixed(3)}">
                    <span class="switch">当前：<span data-field="steps-display">--</span> steps/mm</span>
                </div>
                <div class="switch">
                    <input type="checkbox" data-field="invert-toggle" id="invert-${pid}">
                    <label for="invert-${pid}">反向</label>
                </div>
                <div class="field-row">
                    <button class="btn small-button" data-action="set-steps">保存步距</button>
                </div>
            </div>

            <details>
                <summary>校准向导</summary>
                <div class="control-group">
                    <label>行程校准</label>
                    <div class="field-row">
                        <input type="number" step="0.001" value="10.000" data-field="plan-mm">
                        <input type="number" step="0.001" value="10.000" data-field="meas-mm">
                        <button class="btn small-button" data-action="apply-travel">计算修正</button>
                    </div>
                </div>
                <div class="control-group">
                    <label>体积闭环</label>
                    <div class="field-row">
                        <input type="number" step="0.001" value="1.000" data-field="plan-ml">
                        <input type="number" step="0.001" value="1.000" data-field="meas-ml">
                        <select data-field="cal-syringe"></select>
                        <button class="btn small-button" data-action="apply-volume">体积修正</button>
                    </div>
                </div>
            </details>
        `;
        pumpGrid.appendChild(card);
    }
}

function updateSyringeSelects() {
    const options = state.syringes.map((s) => `<option value="${s.name}">${s.name}</option>`).join("");
    document.querySelectorAll(".syringe-select").forEach((select) => {
        const previous = select.value;
        select.innerHTML = options;
        if (state.syringes.length === 0) {
            select.innerHTML = '<option value="">--</option>';
            return;
        }
        if (state.syringes.some((s) => s.name === previous)) {
            select.value = previous;
        } else {
            select.selectedIndex = 0;
        }
        const card = select.closest(".pump-card");
        updateSyringeDiameter(card);
    });

    document.querySelectorAll('[data-field="cal-syringe"]').forEach((select) => {
        const prev = select.value;
        select.innerHTML = options;
        if (state.syringes.length === 0) {
            select.innerHTML = '<option value="">--</option>';
            return;
        }
        if (state.syringes.some((s) => s.name === prev)) {
            select.value = prev;
        } else {
            select.selectedIndex = 0;
        }
    });
}

function updateSyringeDiameter(card) {
    if (!card) return;
    const select = card.querySelector(".syringe-select");
    const label = card.querySelector('[data-field="syringe-diam"]');
    if (!select || !label) return;
    const model = state.syringes.find((s) => s.name === select.value);
    if (model) {
        label.textContent = `Ø ${Number(model.inner_d_mm).toFixed(3)} mm`;
    } else {
        label.textContent = "Ø -- mm";
    }
}

function renderPorts() {
    const ports = state.ports;
    const portOptions = ['<option value="">请选择串口</option>', ...ports.map((p) => `<option value="${p}">${p}</option>`)].join("");
    [0, 1].forEach((idx) => {
        const select = document.querySelector(`#port-select-${idx}`);
        if (!select) return;
        const current = select.value;
        select.innerHTML = portOptions;
        const board = state.status?.boards?.find((b) => b.index === idx);
        const desired = board?.port || current;
        if (desired && ports.includes(desired)) {
            select.value = desired;
        }
        const baudSelect = document.querySelector(`#baud-select-${idx}`);
        if (board && baudSelect) {
            baudSelect.value = String(board.baud || baudSelect.value);
        }
    });
}

function renderStatus() {
    const status = state.status;
    const connected = status?.boards?.some((b) => b.is_open) ?? false;
    const statusEl = document.querySelector("#connection-status");
    statusEl.textContent = connected ? "串口已连接" : "未连接";
    statusEl.classList.toggle("status-connected", connected);
    statusEl.classList.toggle("status-disconnected", !connected);

    const boardStatus = document.querySelector("#board-status");
    boardStatus.innerHTML = "";
    status?.boards?.forEach((b) => {
        const elem = document.createElement("div");
        elem.className = `board-chip ${b.is_open ? "connected" : ""}`;
        const label = b.index === 0 ? "主板" : "副板";
        elem.textContent = `${label}: ${b.port || "未连接"}`;
        boardStatus.appendChild(elem);
    });

    const ack = status?.ack ?? [];
    const ackSummary = document.querySelector("#ack-summary");
    ackSummary.textContent = ack.length ? `剩余步数：${ack.map((v, i) => `P${i + 1}=${v}`).join(" / ")}` : "";

    document.querySelectorAll(".pump-card").forEach((card) => {
        const pid = Number(card.dataset.pump);
        const remaining = ack[pid - 1];
        const remEl = card.querySelector('[data-field="remaining"]');
        if (remEl) {
            remEl.textContent = Number.isFinite(remaining) ? `余步 ${remaining}` : "余步 --";
        }
        const cal = status?.calibration?.[pid];
        if (cal) {
            const steps = Number(cal.steps_per_mm) || 0;
            const stepsDisplay = card.querySelector('[data-field="steps-display"]');
            if (stepsDisplay) {
                stepsDisplay.textContent = steps.toFixed(3);
            }
            const stepsInput = card.querySelector('[data-field="steps-input"]');
            if (stepsInput && document.activeElement !== stepsInput) {
                stepsInput.value = steps.toFixed(3);
            }
            const invert = card.querySelector('[data-field="invert-toggle"]');
            if (invert) {
                invert.checked = Boolean(cal.invert_dir);
            }
        }
        updateSyringeDiameter(card);
    });

    renderPorts();
}

function renderSyringeTable() {
    const tbody = document.querySelector("#syringe-table-body");
    tbody.innerHTML = "";
    if (!state.syringes.length) {
        const row = document.createElement("tr");
        row.innerHTML = `<td colspan="3" style="text-align:center;color:var(--muted);">暂无数据</td>`;
        tbody.appendChild(row);
        return;
    }
    state.syringes.forEach((model, idx) => {
        const row = document.createElement("tr");
        row.dataset.index = String(idx);
        row.innerHTML = `
            <td><input type="text" data-field="syr-name" value="${model.name ?? ""}" placeholder="型号名称"></td>
            <td><input type="number" step="0.001" min="0" data-field="syr-diam" value="${Number(model.inner_d_mm ?? 0).toFixed(3)}"></td>
            <td>
                <div class="row-actions">
                    <button class="row-btn" data-action="syr-up">上移</button>
                    <button class="row-btn" data-action="syr-down">下移</button>
                    <button class="row-btn" data-action="syr-delete">删除</button>
                </div>
            </td>
        `;
        tbody.appendChild(row);
    });
}

async function refreshStatus() {
    try {
        const data = await apiGet("/api/status");
        state.status = data;
        renderStatus();
    } catch (err) {
        showToast(`刷新状态失败：${err.message}`, "error", 3000);
    }
}

async function refreshPorts() {
    try {
        const data = await apiGet("/api/ports");
        state.ports = data.ports || [];
        renderPorts();
    } catch (err) {
        showToast(`刷新串口失败：${err.message}`, "error", 3000);
    }
}

async function refreshSyringes() {
    try {
        const data = await apiGet("/api/syringes");
        state.syringes = data.models || [];
        renderSyringeTable();
        updateSyringeSelects();
    } catch (err) {
        showToast(`读取注射器列表失败：${err.message}`, "error", 3000);
    }
}

async function connectBoard(idx) {
    const port = document.querySelector(`#port-select-${idx}`)?.value;
    const baud = Number(document.querySelector(`#baud-select-${idx}`)?.value || "230400");
    if (!port) {
        showToast("请选择串口", "error");
        return;
    }
    await apiPost("/api/boards/open", { board_index: idx, port, baud });
    showToast(`${idx === 0 ? "主板" : "副板"}连接成功`, "success");
    await refreshStatus();
}

async function closeAllBoards() {
    await apiPost("/api/boards/close-all");
    showToast("串口已断开", "success");
    await refreshStatus();
}

async function zeroAll() {
    await apiPost("/api/boards/zero");
    showToast("已发送置零命令", "info");
}

async function estopAll() {
    await apiPost("/api/boards/estop");
    showToast("已发送紧急停止", "error");
}

async function handlePumpAction(card, action, target) {
    const pumpId = Number(card.dataset.pump);
    try {
        switch (action) {
            case "set-speed": {
                const value = Number(card.querySelector('[data-field="speed-value"]')?.value || "0");
                const unit = card.querySelector('[data-field="speed-unit"]')?.value;
                await apiPost(`/api/pumps/${pumpId}/speed`, { value, unit });
                showToast(`P${pumpId} 速度已更新`, "success");
                break;
            }
            case "set-accel": {
                const value = Number(card.querySelector('[data-field="accel-value"]')?.value || "0");
                const unit = card.querySelector('[data-field="accel-unit"]')?.value;
                await apiPost(`/api/pumps/${pumpId}/accel`, { value, unit });
                showToast(`P${pumpId} 加速度已更新`, "success");
                break;
            }
            case "run": {
                const value = Number(card.querySelector('[data-field="run-value"]')?.value || "0");
                const unit = card.querySelector('[data-field="run-unit"]')?.value;
                await apiPost(`/api/pumps/${pumpId}/run`, { value, unit });
                showToast(`P${pumpId} 已开始运行`, "info");
                break;
            }
            case "pause":
                await apiPost(`/api/pumps/${pumpId}/pause`);
                showToast(`P${pumpId} 已暂停`, "info");
                break;
            case "stop":
                await apiPost(`/api/pumps/${pumpId}/stop`);
                showToast(`P${pumpId} 已停止`, "info");
                break;
            case "resume":
                await apiPost(`/api/pumps/${pumpId}/resume`);
                showToast(`P${pumpId} 已继续`, "info");
                break;
            case "jog": {
                const delta = Number(card.querySelector('[data-field="jog-value"]')?.value || "0");
                const unit = card.querySelector('[data-field="jog-unit"]')?.value;
                const direction = Number(target.dataset.direction || "1");
                await apiPost(`/api/pumps/${pumpId}/jog`, { delta: direction * delta, unit });
                showToast(`P${pumpId} JOG 已发送`, "info");
                break;
            }
            case "set-steps": {
                const steps = Number(card.querySelector('[data-field="steps-input"]')?.value || "0");
                await apiPost(`/api/calibration/${pumpId}/steps`, { steps_per_mm: steps });
                showToast(`P${pumpId} 步距已保存`, "success");
                await refreshStatus();
                break;
            }
            case "apply-travel": {
                const plan = Number(card.querySelector('[data-field="plan-mm"]')?.value || "0");
                const meas = Number(card.querySelector('[data-field="meas-mm"]')?.value || "0");
                const res = await apiPost(`/api/calibration/${pumpId}/travel`, { plan_mm: plan, meas_mm: meas });
                showToast(`P${pumpId} 行程修正: ${Number(res.steps_per_mm).toFixed(3)}`, "success");
                await refreshStatus();
                break;
            }
            case "apply-volume": {
                const planMl = Number(card.querySelector('[data-field="plan-ml"]')?.value || "0");
                const measMl = Number(card.querySelector('[data-field="meas-ml"]')?.value || "0");
                const syringe = card.querySelector('[data-field="cal-syringe"]')?.value || "";
                const res = await apiPost(`/api/calibration/${pumpId}/volume`, {
                    target_ml: planMl,
                    meas_ml: measMl,
                    syringe_name: syringe,
                });
                showToast(`P${pumpId} 体积修正: ${Number(res.steps_per_mm).toFixed(3)}`, "success");
                await refreshStatus();
                break;
            }
            default:
                break;
        }
    } catch (err) {
        showToast(`操作失败：${err.message}`, "error", 3200);
    }
}

async function saveInvert(card, invert) {
    const pumpId = Number(card.dataset.pump);
    try {
        await apiPost(`/api/calibration/${pumpId}/invert`, { invert });
        showToast(`P${pumpId} 方向已更新`, "success");
    } catch (err) {
        showToast(`更新方向失败：${err.message}`, "error", 3200);
        // revert toggle
        const toggle = card.querySelector('[data-field="invert-toggle"]');
        if (toggle) toggle.checked = !invert;
    }
}

function reorderSyringes(fromIdx, toIdx) {
    if (toIdx < 0 || toIdx >= state.syringes.length) return;
    const list = [...state.syringes];
    const [moved] = list.splice(fromIdx, 1);
    list.splice(toIdx, 0, moved);
    state.syringes = list;
    renderSyringeTable();
    updateSyringeSelects();
}

function deleteSyringe(idx) {
    state.syringes.splice(idx, 1);
    renderSyringeTable();
    updateSyringeSelects();
}

async function saveSyringes() {
    const rows = [...document.querySelectorAll("#syringe-table-body tr")];
    const models = [];
    for (const row of rows) {
        const name = row.querySelector('[data-field="syr-name"]')?.value.trim() ?? "";
        const diamStr = row.querySelector('[data-field="syr-diam"]')?.value ?? "0";
        const inner_d_mm = Number(diamStr);
        if (!name) {
            showToast("名称不能为空", "error");
            return;
        }
        if (!Number.isFinite(inner_d_mm) || inner_d_mm <= 0) {
            showToast("内径必须大于 0", "error");
            return;
        }
        models.push({ name, inner_d_mm });
    }
    await apiPut("/api/syringes", { models });
    showToast("注射器列表已保存", "success");
    await refreshSyringes();
}

async function init() {
    createPumpCards();
    pumpGrid.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;
        const action = target.dataset.action;
        if (!action) return;
        const card = target.closest(".pump-card");
        if (!card) return;
        handlePumpAction(card, action, target);
    });
    pumpGrid.addEventListener("change", (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;
        const card = target.closest(".pump-card");
        if (!card) return;
        if (target.matches('[data-field="invert-toggle"]')) {
            saveInvert(card, target.checked);
        } else if (target.matches(".syringe-select")) {
            updateSyringeDiameter(card);
        }
    });

    document.querySelector("#refresh-ports")?.addEventListener("click", () => {
        refreshPorts();
    });
    document.querySelector("#connect-board-0")?.addEventListener("click", () => connectBoard(0));
    document.querySelector("#connect-board-1")?.addEventListener("click", () => connectBoard(1));
    document.querySelector("#close-all")?.addEventListener("click", closeAllBoards);
    document.querySelector("#zero-all")?.addEventListener("click", zeroAll);
    document.querySelector("#estop")?.addEventListener("click", estopAll);

    document.querySelector("#add-syringe")?.addEventListener("click", () => {
        state.syringes.push({ name: "", inner_d_mm: 10.0 });
        renderSyringeTable();
        updateSyringeSelects();
    });
    document.querySelector("#save-syringes")?.addEventListener("click", () => {
        saveSyringes().catch((err) => showToast(`保存失败：${err.message}`, "error", 3200));
    });

    document.querySelector("#syringe-table-body")?.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;
        const row = target.closest("tr");
        if (!row) return;
        const idx = Number(row.dataset.index);
        if (Number.isNaN(idx)) return;
        if (target.dataset.action === "syr-up") {
            reorderSyringes(idx, idx - 1);
        } else if (target.dataset.action === "syr-down") {
            reorderSyringes(idx, idx + 1);
        } else if (target.dataset.action === "syr-delete") {
            deleteSyringesWithConfirm(idx);
        }
    });

    await Promise.all([refreshPorts(), refreshSyringes(), refreshStatus()]);
    setInterval(refreshStatus, 2000);
    setInterval(refreshPorts, 12000);
}

function deleteSyringesWithConfirm(idx) {
    if (state.syringes.length <= 1) {
        showToast("至少保留一个型号", "error");
        return;
    }
    deleteSyringe(idx);
}

document.addEventListener("DOMContentLoaded", () => {
    init().catch((err) => {
        console.error(err);
        showToast(`初始化失败：${err.message}`, "error", 5000);
    });
});
