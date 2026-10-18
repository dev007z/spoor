// Fund-flow graph for a trace run: addresses in columns by hop, edges sized by amount.
(function () {
  "use strict";

  const container = document.getElementById("trace-graph");
  if (!container || typeof cytoscape === "undefined") return;

  const panel = document.getElementById("graph-panel");
  const css = getComputedStyle(document.documentElement);
  const token = (name) => css.getPropertyValue(name).trim();
  const short = (address) => `${address.slice(0, 6)}…${address.slice(-4)}`;
  const COLUMN_GAP = 260;
  const ROW_GAP = 80;

  let cy = null;
  let shownCount = -1;

  function nodeColor(node) {
    if (node.kind === "seed") return token("--node-seed");
    if (node.category) return token(`--node-${node.category}`) || token("--node-other");
    return token("--node-address");
  }

  function positions(nodes) {
    const columns = {};
    nodes.forEach((node) => (columns[node.hop] = columns[node.hop] || []).push(node));
    const placed = {};
    Object.entries(columns).forEach(([hop, column]) => {
      column.forEach((node, row) => {
        placed[node.id] = { x: Number(hop) * COLUMN_GAP, y: (row - (column.length - 1) / 2) * ROW_GAP };
      });
    });
    return placed;
  }

  function elements(data) {
    const placed = positions(data.nodes);
    const nodes = data.nodes.map((node) => ({
      group: "nodes",
      data: { ...node, name: node.label || short(node.id), color: nodeColor(node), flagged: node.fan_out_truncated || node.fetch_incomplete },
      position: placed[node.id],
    }));
    const edges = data.edges.map((edge) => ({
      group: "edges",
      data: { ...edge, caption: `${Number(edge.amount).toLocaleString(undefined, { maximumFractionDigits: 2 })} ${edge.symbol}` },
    }));
    return nodes.concat(edges);
  }

  function create() {
    return cytoscape({
      container,
      wheelSensitivity: 0.3,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)",
            label: "data(name)",
            color: token("--text"),
            "font-size": 11,
            "text-valign": "bottom",
            "text-margin-y": 6,
            width: 26,
            height: 26,
            "border-width": 2,
            "border-color": token("--surface"),
          },
        },
        { selector: "node[kind = 'seed']", style: { width: 34, height: 34, shape: "diamond" } },
        { selector: "node[kind = 'endpoint']", style: { shape: "round-rectangle" } },
        { selector: "node[?flagged]", style: { "border-color": token("--warn-text"), "border-style": "dashed", "border-width": 3 } },
        { selector: "node:selected", style: { "border-color": token("--accent"), "border-width": 4, "border-style": "solid" } },
        {
          selector: "edge",
          style: {
            width: "data(width)",
            "line-color": token("--edge"),
            "target-arrow-color": token("--edge"),
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            label: "data(caption)",
            "font-size": 9,
            color: token("--muted"),
            "text-rotation": "autorotate",
            "text-background-color": token("--surface"),
            "text-background-opacity": 0.85,
            "text-background-padding": 2,
          },
        },
        { selector: "edge:selected", style: { "line-color": token("--accent"), "target-arrow-color": token("--accent") } },
      ],
      layout: { name: "preset" },
    });
  }

  function row(term, value, href) {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    if (href) {
      const link = document.createElement("a");
      link.href = href;
      link.textContent = value;
      if (href.startsWith("http")) {
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
      dd.appendChild(link);
    } else {
      dd.textContent = value;
    }
    return [dt, dd];
  }

  function showDetails(title, rows) {
    panel.replaceChildren();
    const heading = document.createElement("h2");
    heading.textContent = title;
    const list = document.createElement("dl");
    list.className = "facts";
    rows.forEach(([term, value, href]) => list.append(...row(term, value, href)));
    panel.append(heading, list);
  }

  function showNode(node) {
    const flags = [node.fan_out_truncated && "More transfers than fan-out", node.fetch_incomplete && "Provider results incomplete"].filter(Boolean);
    showDetails(node.label || "Address", [
      ["Address", node.id],
      ["Hop", String(node.hop)],
      ["Outcome", node.outcome],
      ...(flags.length ? [["Flags", flags.join("; ")]] : []),
      ["Transfers", "Open in Transfers", node.transfers_url],
      ["Explorer", "View on explorer", node.explorer_url],
    ]);
  }

  function showEdge(edge) {
    showDetails("Flow", [
      ["From", edge.source],
      ["To", edge.target],
      ["Total", `${edge.amount} ${edge.symbol}`],
      ["Transfers", String(edge.count)],
    ]);
  }

  function render(data) {
    if (!cy) {
      cy = create();
      cy.on("tap", "node", (event) => showNode(event.target.data()));
      cy.on("tap", "edge", (event) => showEdge(event.target.data()));
    }
    const count = data.nodes.length + data.edges.length;
    if (count === shownCount) return;
    cy.elements().remove();
    cy.add(elements(data));
    cy.fit(undefined, 40);
    shownCount = count;
  }

  function load() {
    fetch(container.dataset.graphUrl, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then((response) => response.json())
      .then((body) => body.status && render(body.data))
      .catch(() => panel.replaceChildren(document.createTextNode("The graph could not be loaded.")));
  }

  // The trace body refreshes every few seconds while the run is live; redraw with it.
  document.body.addEventListener("htmx:afterSettle", load);
  load();
})();
