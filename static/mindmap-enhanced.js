// Enhanced Mind Map Features

// Search and highlight nodes
function searchNetwork(query) {
  if (!networkInstance || !networkData) return;
  
  query = query.toLowerCase().trim();
  if (!query) {
    networkInstance.selectNodes([]);
    return;
  }

  const matches = networkData.nodes
    .filter(n => n.name.toLowerCase().includes(query))
    .map(n => n.id);
  
  if (matches.length > 0) {
    networkInstance.selectNodes(matches);
    networkInstance.focus(matches[0], { scale: 1.5, animation: true });
  }
}

// Find shortest path between two people
function findPath(fromId, toId) {
  if (!networkData) return null;
  
  // Build adjacency list
  const graph = new Map();
  networkData.edges.forEach(e => {
    if (!graph.has(e.source)) graph.set(e.source, []);
    if (!graph.has(e.target)) graph.set(e.target, []);
    graph.get(e.source).push({ node: e.target, edge: e });
    graph.get(e.target).push({ node: e.source, edge: e });
  });

  // BFS to find shortest path
  const queue = [[fromId]];
  const visited = new Set([fromId]);

  while (queue.length > 0) {
    const path = queue.shift();
    const current = path[path.length - 1];

    if (current === toId) {
      return path;
    }

    const neighbors = graph.get(current) || [];
    for (const { node } of neighbors) {
      if (!visited.has(node)) {
        visited.add(node);
        queue.push([...path, node]);
      }
    }
  }

  return null;
}

// Highlight path in network
function highlightPath(path) {
  if (!networkInstance || !path || path.length < 2) return;

  // Highlight nodes
  networkInstance.selectNodes(path);

  // Build edge list for path
  const pathEdges = [];
  for (let i = 0; i < path.length - 1; i++) {
    const edgeIds = networkInstance.getConnectedEdges(path[i])
      .filter(edgeId => {
        const edge = networkInstance.body.data.edges.get(edgeId);
        return (edge.from === path[i] && edge.to === path[i + 1]) ||
               (edge.to === path[i] && edge.from === path[i + 1]);
      });
    pathEdges.push(...edgeIds);
  }

  networkInstance.selectEdges(pathEdges);
}

// Detect communities using simple label propagation
function detectCommunities() {
  if (!networkData) return {};

  const nodes = networkData.nodes;
  const edges = networkData.edges;

  // Build adjacency list
  const adj = new Map();
  nodes.forEach(n => adj.set(n.id, []));
  edges.forEach(e => {
    adj.get(e.source).push(e.target);
    adj.get(e.target).push(e.source);
  });

  // Initialize: each node in its own community
  const labels = new Map();
  nodes.forEach(n => labels.set(n.id, n.id));

  // Iterate: adopt most common neighbor label
  for (let iter = 0; iter < 10; iter++) {
    let changed = false;
    nodes.forEach(n => {
      const neighbors = adj.get(n.id);
      if (neighbors.length === 0) return;

      const labelCounts = new Map();
      neighbors.forEach(nbr => {
        const lbl = labels.get(nbr);
        labelCounts.set(lbl, (labelCounts.get(lbl) || 0) + 1);
      });

      const mostCommon = [...labelCounts.entries()]
        .sort((a, b) => b[1] - a[1])[0][0];

      if (labels.get(n.id) !== mostCommon) {
        labels.set(n.id, mostCommon);
        changed = true;
      }
    });

    if (!changed) break;
  }

  // Group by community
  const communities = new Map();
  labels.forEach((community, nodeId) => {
    if (!communities.has(community)) communities.set(community, []);
    communities.get(community).push(nodeId);
  });

  return communities;
}

// Color nodes by community
function colorByCommunity() {
  if (!networkInstance || !networkData) return;

  const communities = detectCommunities();
  const colors = [
    '#E74C3C', '#3498DB', '#2ECC71', '#F39C12', '#9B59B6',
    '#1ABC9C', '#E67E22', '#95A5A6', '#34495E', '#16A085'
  ];

  let colorIdx = 0;
  const communityColors = new Map();
  communities.forEach((members, commId) => {
    communityColors.set(commId, colors[colorIdx % colors.length]);
    colorIdx++;
  });

  // Update node colors
  const updates = networkData.nodes.map(n => {
    const community = Array.from(communities.entries())
      .find(([_, members]) => members.includes(n.id))?.[0];
    const color = communityColors.get(community) || '#95A5A6';
    
    return {
      id: n.id,
      color: {
        background: color,
        border: '#2C3E50',
        highlight: { background: color, border: '#E67E22' }
      }
    };
  });

  networkInstance.body.data.nodes.update(updates);
}

// Calculate centrality metrics
function calculateCentrality() {
  if (!networkData) return {};

  const nodes = networkData.nodes;
  const edges = networkData.edges;

  // Build adjacency
  const adj = new Map();
  nodes.forEach(n => adj.set(n.id, []));
  edges.forEach(e => {
    adj.get(e.source).push(e.target);
    adj.get(e.target).push(e.source);
  });

  // Degree centrality (simple)
  const degree = new Map();
  nodes.forEach(n => {
    degree.set(n.id, adj.get(n.id).length);
  });

  // Betweenness centrality (simplified)
  const betweenness = new Map();
  nodes.forEach(n => betweenness.set(n.id, 0));

  nodes.forEach(source => {
    const stack = [];
    const paths = new Map();
    const sigma = new Map();
    const d = new Map();

    nodes.forEach(n => {
      paths.set(n.id, []);
      sigma.set(n.id, 0);
      d.set(n.id, -1);
    });

    sigma.set(source.id, 1);
    d.set(source.id, 0);

    const queue = [source.id];

    while (queue.length > 0) {
      const v = queue.shift();
      stack.push(v);

      adj.get(v).forEach(w => {
        if (d.get(w) < 0) {
          queue.push(w);
          d.set(w, d.get(v) + 1);
        }

        if (d.get(w) === d.get(v) + 1) {
          sigma.set(w, sigma.get(w) + sigma.get(v));
          paths.get(w).push(v);
        }
      });
    }

    const delta = new Map();
    nodes.forEach(n => delta.set(n.id, 0));

    while (stack.length > 0) {
      const w = stack.pop();
      paths.get(w).forEach(v => {
        delta.set(v, delta.get(v) + (sigma.get(v) / sigma.get(w)) * (1 + delta.get(w)));
      });
      if (w !== source.id) {
        betweenness.set(w, betweenness.get(w) + delta.get(w));
      }
    }
  });

  return { degree, betweenness };
}

// Export network as image
async function exportNetwork() {
  if (!networkInstance) return;

  const canvas = networkInstance.canvas.frame.canvas;
  const dataUrl = canvas.toDataURL('image/png');
  
  const link = document.createElement('a');
  link.download = 'network-graph.png';
  link.href = dataUrl;
  link.click();
}

// Timeline filter
let currentTimeRange = null;

function filterByTimeRange(startDate, endDate) {
  if (!networkData) return;

  currentTimeRange = { start: startDate, end: endDate };

  // Filter edges by date range
  const filteredEdges = networkData.edges.filter(e => {
    // Check if edge has timestamp data
    if (!e.earliest_date && !e.latest_date) return true;
    
    const edgeDate = new Date(e.earliest_date || e.latest_date);
    return edgeDate >= startDate && edgeDate <= endDate;
  });

  // Rebuild graph with filtered edges
  updateMindMap();
}

// Get network statistics
function getNetworkStats() {
  if (!networkData) return null;

  const { degree, betweenness } = calculateCentrality();

  const stats = {
    totalNodes: networkData.nodes.length,
    totalEdges: networkData.edges.length,
    primaryNodes: networkData.nodes.filter(n => n.type === 'primary').length,
    secondaryNodes: networkData.nodes.filter(n => n.type === 'secondary').length,
    avgConnections: (networkData.edges.length * 2) / networkData.nodes.length,
    mostConnected: null,
    mostCentral: null,
  };

  if (degree.size > 0) {
    stats.mostConnected = [...degree.entries()]
      .sort((a, b) => b[1] - a[1])[0];
  }

  if (betweenness.size > 0) {
    stats.mostCentral = [...betweenness.entries()]
      .sort((a, b) => b[1] - a[1])[0];
  }

  return stats;
}
