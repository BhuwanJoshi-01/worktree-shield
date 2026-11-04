// Worktree Shield project page: the map toggle, its table form on phones, and the copy button.
// SPDX-License-Identifier: MIT
//
// The values are those of examples/conflicting-worktrees: what `scan --scope static` finds
// there, and what the worktrees use after the changes `plan` suggests (a .env in app-billing
// and app-login). tests/unit/test_example.py checks that the second state passes --strict.

"use strict";

const WORKTREES = [
    { name: "app", scan: ["5173", "app_dev", "app"], plan: ["5173", "app_dev", "app"] },
    { name: "app-billing", scan: ["5173", "app_dev", "app"], plan: ["5174", "app_dev_app_billing", "app-billing"] },
    { name: "app-login", scan: ["5173", "app_dev", "app"], plan: ["5175", "app_dev_app_login", "app-login"] },
];

const VIEWS = {
    scan: {
        readout: "1 fail, 3 warn: port 5173, the database app_dev and the Compose project app are shared.",
        command: "worktree-shield scan --strict   # exit 1",
        desc: "Three lines, app, app-billing and app-login, run through the same three stations: port 5173, the database app_dev and the Compose project app. Port 5173 fails WTS-PORT-001; the database and the project warn.",
    },
    plan: {
        readout: "After the 6 changes plan suggests, in the .env of app-billing and app-login, nothing is shared.",
        command: "worktree-shield scan --strict --include-env   # exit 0",
        desc: "Three separate lines with their own stations: app keeps 5173, app_dev and app; app-billing gets 5174, app_dev_app_billing and app-billing; app-login gets 5175, app_dev_app_login and app-login.",
    },
};

const map = document.querySelector(".map");
const buttons = Array.from(document.querySelectorAll(".toggle button"));

function field(name) {
    return document.querySelector(`[data-field="${name}"]`);
}

function table(view) {
    const rows = WORKTREES.map((worktree) => {
        const row = document.createElement("tr");
        const name = document.createElement("th");
        name.scope = "row";
        name.textContent = worktree.name;
        row.append(name);
        worktree[view].forEach((value, column) => {
            const cell = document.createElement("td");
            cell.textContent = value;
            const shared = WORKTREES.filter((other) => other[view][column] === value).length > 1;
            if (shared) cell.className = "shared";
            else if (value !== worktree.scan[column]) cell.className = "changed";
            row.append(cell);
        });
        return row;
    });
    field("map-table").replaceChildren(...rows);
}

function show(view) {
    map.dataset.view = view;
    for (const button of buttons) button.setAttribute("aria-pressed", String(button.dataset.view === view));
    field("readout").textContent = VIEWS[view].readout;
    field("readout-command").textContent = VIEWS[view].command;
    field("map-desc").textContent = VIEWS[view].desc;
    table(view);
}

for (const button of buttons) button.addEventListener("click", () => show(button.dataset.view));
show(new URLSearchParams(location.search).get("view") === "plan" ? "plan" : "scan");

for (const button of document.querySelectorAll("[data-copy]")) {
    button.addEventListener("click", async () => {
        const text = document.getElementById(button.dataset.copy).textContent;
        try {
            await navigator.clipboard.writeText(text);
            button.textContent = "Copied";
            button.dataset.state = "done";
        } catch {
            button.textContent = "Select and copy";
        }
        setTimeout(() => {
            button.textContent = "Copy";
            delete button.dataset.state;
        }, 2000);
    });
}
