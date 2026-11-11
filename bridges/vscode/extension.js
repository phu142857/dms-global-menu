const fs = require("fs");
const net = require("net");
const os = require("os");
const path = require("path");
const vscode = require("vscode");

let server;
let socketPath;

function send(connection, payload) {
  connection.end(JSON.stringify(payload) + "\n");
}

function activate(context) {
  const mainPid = process.ppid;
  const runtimeDir = process.env.XDG_RUNTIME_DIR || `/run/user/${process.getuid()}`;
  socketPath = path.join(runtimeDir, `dms-global-menu-vscode-${mainPid}.sock`);
  try {
    fs.unlinkSync(socketPath);
  } catch (error) {
    if (error.code !== "ENOENT") {
      console.error("DMS Global Menu: cannot remove stale socket", error);
    }
  }

  server = net.createServer((connection) => {
    let input = "";
    connection.setEncoding("utf8");
    connection.on("data", (chunk) => {
      input += chunk;
      const newline = input.indexOf("\n");
      if (newline < 0) return;
      let request;
      try {
        request = JSON.parse(input.slice(0, newline));
      } catch (error) {
        send(connection, { ok: false, error: "invalid JSON" });
        return;
      }
      if (!request.command || typeof request.command !== "string") {
        send(connection, { ok: false, error: "missing command" });
        return;
      }
      vscode.commands.executeCommand(request.command).then(
        () => send(connection, { ok: true }),
        (error) => send(connection, { ok: false, error: String(error) })
      );
    });
  });

  server.listen(socketPath);
  context.subscriptions.push({
    dispose() {
      if (server) server.close();
      if (socketPath) {
        try { fs.unlinkSync(socketPath); } catch (_) {}
      }
    }
  });
}

function deactivate() {
  if (server) server.close();
  if (socketPath) {
    try { fs.unlinkSync(socketPath); } catch (_) {}
  }
}

module.exports = { activate, deactivate };
