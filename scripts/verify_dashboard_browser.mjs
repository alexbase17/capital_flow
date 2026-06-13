#!/usr/bin/env node
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const BASE_URL = (process.env.BASE_URL || process.argv[2] || "http://127.0.0.1:5083").replace(/\/$/, "");
const CHROME_BIN = process.env.CHROME_BIN || DEFAULT_CHROME;
const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900, mobile: false, deviceScaleFactor: 1 },
  { name: "mobile", width: 390, height: 844, mobile: true, deviceScaleFactor: 2 },
];

class CdpClient {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.nextId = 1;
    this.pending = new Map();
    this.handlers = new Map();
    this.ws.addEventListener("message", event => this.handleMessage(event));
  }

  async ready() {
    if (this.ws.readyState === WebSocket.OPEN) return;
    await new Promise((resolve, reject) => {
      this.ws.addEventListener("open", resolve, { once: true });
      this.ws.addEventListener("error", reject, { once: true });
    });
  }

  handleMessage(event) {
    const message = JSON.parse(event.data);
    if (message.id && this.pending.has(message.id)) {
      const { resolve, reject } = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message || JSON.stringify(message.error)));
      else resolve(message.result || {});
      return;
    }
    const handlers = this.handlers.get(message.method) || [];
    handlers.forEach(handler => handler(message.params || {}, message.sessionId));
  }

  send(method, params = {}, sessionId = undefined) {
    const id = this.nextId++;
    const message = { id, method, params };
    if (sessionId) message.sessionId = sessionId;
    this.ws.send(JSON.stringify(message));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
  }

  on(method, handler) {
    const handlers = this.handlers.get(method) || [];
    handlers.push(handler);
    this.handlers.set(method, handlers);
  }

  close() {
    this.ws.close();
  }
}

async function main() {
  const chrome = await launchChrome();
  const client = await connectToChrome(chrome.port);
  const errors = [];
  try {
    await client.ready();
    for (const viewport of VIEWPORTS) {
      await runViewportRegression(client, viewport, errors);
    }
    const blockingErrors = errors.filter(item => item.level === "error");
    if (blockingErrors.length) {
      throw new Error(`Browser console errors:\n${blockingErrors.map(item => `- ${item.text}`).join("\n")}`);
    }
    console.log(`Dashboard browser regression passed for ${BASE_URL}`);
  } finally {
    client.close();
    await stopChrome(chrome.process);
    await rm(chrome.userDataDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }
}

async function launchChrome() {
  const userDataDir = await mkdtemp(path.join(tmpdir(), "capital-flow-chrome-"));
  const port = 9223 + Math.floor(Math.random() * 1000);
  const args = [
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${userDataDir}`,
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-networking",
    "about:blank",
  ];
  const chromeProcess = spawn(CHROME_BIN, args, { stdio: "ignore" });
  chromeProcess.on("exit", code => {
    if (code !== null && code !== 0) {
      console.error(`Chrome exited with code ${code}`);
    }
  });
  await waitFor(async () => {
    const response = await fetch(`http://127.0.0.1:${port}/json/version`);
    return response.ok;
  }, { timeoutMs: 10000, label: "Chrome DevTools endpoint" });
  return { process: chromeProcess, port, userDataDir };
}

async function connectToChrome(port) {
  const version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
  return new CdpClient(version.webSocketDebuggerUrl);
}

async function stopChrome(chromeProcess) {
  if (chromeProcess.exitCode !== null) return;
  const exited = new Promise(resolve => chromeProcess.once("exit", resolve));
  chromeProcess.kill("SIGTERM");
  const stopped = await Promise.race([
    exited.then(() => true),
    new Promise(resolve => setTimeout(() => resolve(false), 3000)),
  ]);
  if (stopped || chromeProcess.exitCode !== null) return;
  chromeProcess.kill("SIGKILL");
  await exited;
}

async function runViewportRegression(client, viewport, errors) {
  const { targetId } = await client.send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await client.send("Target.attachToTarget", { targetId, flatten: true });
  wireConsoleCapture(client, sessionId, errors, viewport.name);
  await client.send("Page.enable", {}, sessionId);
  await client.send("Runtime.enable", {}, sessionId);
  await client.send("Log.enable", {}, sessionId);
  await client.send("Fetch.enable", {
    patterns: [{ urlPattern: "*://*/api/capital-flow/ai-summary*", requestStage: "Request" }],
  }, sessionId);
  client.on("Fetch.requestPaused", async (params, eventSessionId) => {
    if (eventSessionId !== sessionId) return;
    const body = Buffer.from(JSON.stringify({ error: "browser regression forced AI failure" })).toString("base64");
    await client.send("Fetch.fulfillRequest", {
      requestId: params.requestId,
      responseCode: 502,
      responseHeaders: [{ name: "Content-Type", value: "application/json" }],
      body,
    }, sessionId);
  });
  await client.send("Emulation.setDeviceMetricsOverride", viewport, sessionId);
  await navigate(client, sessionId, `${BASE_URL}/?browser-regression=${viewport.name}`);
  await waitForPageCondition(client, sessionId, "document.querySelectorAll('#broadTable .data-row').length > 0");
  const pageState = await evaluate(client, sessionId, dashboardStateExpression());
  assert(pageState.title === "资金流向", `${viewport.name}: page title rendered`);
  assert(pageState.scriptCount === 6, `${viewport.name}: all split JS modules loaded`);
  assert(pageState.broadRows > 0, `${viewport.name}: broad table rendered`);
  assert(pageState.totalMatrix, `${viewport.name}: total flow matrix rendered`);
  assert(!pageState.loadingFailed, `${viewport.name}: no loading failure text`);
  assert(pageState.aiPanelHidden, `${viewport.name}: AI panel stays hidden when AI endpoint fails`);
  assert(pageState.stickyHeader, `${viewport.name}: table header remains sticky`);

  if (viewport.name === "desktop") {
    await evaluate(client, sessionId, "document.querySelector('#broadTable .data-row')?.click(); true");
    await waitForPageCondition(client, sessionId, "document.querySelectorAll('#broadTable .detail-row .flow-chart').length >= 4");
    const expandedState = await evaluate(client, sessionId, expandedChartStateExpression());
    assert(expandedState.chartCount >= 4, "desktop: expanded row renders four charts");
    assert(expandedState.chartTitles.includes("分天涨跌幅"), "desktop: daily return chart rendered");
    assert(expandedState.chartTitles.includes("5日滑动窗口成交均值占比"), "desktop: turnover chart rendered");
    assert(expandedState.tooltipVisible && expandedState.tooltipText, "desktop: chart tooltip works");
  }

  await client.send("Target.closeTarget", { targetId });
}

function wireConsoleCapture(client, sessionId, errors, viewportName) {
  client.on("Runtime.exceptionThrown", (params, eventSessionId) => {
    if (eventSessionId === sessionId) {
      errors.push({ level: "error", text: `${viewportName}: ${params.exceptionDetails?.text || "runtime exception"}` });
    }
  });
  client.on("Log.entryAdded", (params, eventSessionId) => {
    if (eventSessionId !== sessionId) return;
    const entry = params.entry || {};
    if (entry.level === "error" && !isExpectedResourceError(entry)) {
      errors.push({ level: "error", text: `${viewportName}: ${entry.text}${entry.url ? ` (${entry.url})` : ""}` });
    }
  });
  client.on("Runtime.consoleAPICalled", (params, eventSessionId) => {
    if (eventSessionId !== sessionId) return;
    if (params.type === "error") {
      const text = (params.args || []).map(arg => arg.value || arg.description || "").join(" ");
      errors.push({ level: "error", text: `${viewportName}: ${text}` });
    }
  });
}

function isExpectedResourceError(entry) {
  const text = entry.text || "";
  const url = entry.url || "";
  return (
    url.includes("/favicon.ico")
    || url.includes("/api/capital-flow/ai-summary")
    || text.includes("favicon.ico")
    || text.includes("502 (Bad Gateway)")
  );
}

async function navigate(client, sessionId, url) {
  const loaded = new Promise(resolve => {
    client.on("Page.loadEventFired", (_params, eventSessionId) => {
      if (eventSessionId === sessionId) resolve();
    });
  });
  await client.send("Page.navigate", { url }, sessionId);
  await loaded;
}

async function evaluate(client, sessionId, expression) {
  const result = await client.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  }, sessionId);
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text || "Runtime.evaluate failed");
  }
  return result.result?.value;
}

async function waitForPageCondition(client, sessionId, expression, timeoutMs = 15000) {
  await waitFor(async () => Boolean(await evaluate(client, sessionId, `Boolean(${expression})`)), {
    timeoutMs,
    label: expression,
  });
}

async function waitFor(check, { timeoutMs, label }) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      if (await check()) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw new Error(`Timed out waiting for ${label}${lastError ? `: ${lastError.message}` : ""}`);
}

function dashboardStateExpression() {
  return `(() => {
    const bodyText = document.body.innerText || "";
    const th = document.querySelector('#broadTable thead th');
    return {
      title: document.querySelector('h1')?.textContent?.trim(),
      scriptCount: document.querySelectorAll('script[src*="capital_flow"]').length,
      totalMatrix: Boolean(document.querySelector('#totalFlowCards .flow-matrix')),
      broadRows: document.querySelectorAll('#broadTable .data-row').length,
      aRows: document.querySelectorAll('#aIndustryTable .data-row').length,
      hkRows: document.querySelectorAll('#hkIndustryTable .data-row').length,
      strategyRows: document.querySelectorAll('#strategyTable .data-row').length,
      loadingFailed: bodyText.includes('资金流向加载失败'),
      aiPanelHidden: document.querySelector('#aiSummaryPanel')?.hidden === true,
      stickyHeader: getComputedStyle(th).position === 'sticky',
    };
  })()`;
}

function expandedChartStateExpression() {
  return `(() => {
    const plot = document.querySelector('#broadTable .detail-row [data-chart-tooltips]');
    if (plot) {
      const rect = plot.getBoundingClientRect();
      plot.dispatchEvent(new PointerEvent('pointermove', {
        clientX: rect.left + rect.width / 2,
        clientY: rect.top + 10,
        bubbles: true,
      }));
    }
    const tooltip = plot?.querySelector('.chart-tooltip');
    return {
      chartCount: document.querySelectorAll('#broadTable .detail-row .flow-chart').length,
      chartTitles: Array.from(document.querySelectorAll('#broadTable .detail-row .chart-title')).map(item => item.textContent.trim()),
      tooltipVisible: Boolean(tooltip?.classList.contains('visible')),
      tooltipText: tooltip?.textContent || '',
    };
  })()`;
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(`Assertion failed: ${message}`);
  }
}

main().catch(error => {
  console.error(error.stack || error.message);
  process.exit(1);
});
