// Mind Map Enhanced Features - Insert into app.js before renderLegalFiles

// Populate path finder dropdowns
function populatePathSelectors() {
  if (!networkData) return;
  
  const primaryNodes = networkData.nodes
    .filter(n => n.type === 'primary')
    .sort((a, b) => a.name.localeCompare(b.name));
  
  const fromSelect = document.getElementById('mm-path-from');
  const toSelect = document.getElementById('mm-path-to');
  
  if (!fromSelect || !toSelect) return;
  
  const options = primaryNodes.map(n => 
    `<option value="${n.id}">${esc(n.name)}</option>`
  ).join('');
  
  fromSelect.innerHTML = '<option value="">From...</option>' + options;
  toSelect.innerHTML = '<option value="">To...</option>' + options;
}

// Search and highlight
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
    networkInstance.focus(matches[0], { scale: 1.5, animation: { duration: 1000, easingFunction: 'easeInOutQuad' } });
  }
}

// Find shortest path (BFS)
function findPath(fromId, toId) {
  if (!networkData) return null;
  
  const graph = new Map();
  networkData.edges.forEach(e => {
    if (!graph.has(e.source)) graph.set(e.source, []);
    if (!graph.has(e.target)) graph.set(e.target, []);
    graph.get(e.source).push(e.target);
    graph.get(e.target).push(e.source);
  });

  const queue = [[fromId]];
  const visited = new Set([fromId]);

  while (queue.length > 0) {
    const path = queue.shift();
    const current = path[path.length - 1];

    if (current === toId) return path;

    const neighbors = graph.get(current) || [];
    for (const node of neighbors) {
      if (!visited.has(node)) {
        visited.add(node);
        queue.push([...path, node]);
      }
    }
  }

  return null;
}

// Highlight path
function findAndHighlightPath() {
  const fromId = document.getElementById('mm-path-from')?.value;
  const toId = document.getElementById('mm-path-to')?.value;
  
  if (!fromId || !toId) {
    alert('Please select both people');
    return;
  }

  const path = findPath(fromId, toId);
  
  if (!path) {
    alert('No path found between these people');
    return;
  }

  // Highlight nodes in path
  networkInstance.selectNodes(path);

  // Find and highlight edges in path
  const pathEdges = [];
  for (let i = 0; i < path.length - 1; i++) {
    const connectedEdges = networkInstance.getConnectedEdges(path[i]);
    for (const edgeId of connectedEdges) {
      const edge = networkInstance.body.data.edges.get(edgeId);
      if ((edge.from === path[i] && edge.to === path[i + 1]) ||
          (edge.to === path[i] && edge.from === path[i + 1])) {
        pathEdges.push(edgeId);
      }
    }
  }

  networkInstance.selectEdges(pathEdges);

  // Show path in sidebar
  const names = path.map(id => networkData.nodes.find(n => n.id === id)?.name || '?');
  document.getElementById('mm-details').innerHTML = `
    <h3>🔗 Path Found</h3>
    <div class="path-display">
      ${names.map((name, i) => `
        <div class="path-node">${esc(name)}</div>
        ${i < names.length - 1 ? '<div class="path-arrow">↓</div>' : ''}
      `).join('')}
    </div>
    <p class="text-sm text-gray-400 mt-3">Length: ${path.length - 1} hop${path.length !== 2 ? 's' : ''}</p>
  `;
}

// Detect communities
function detectCommunities() {
  if (!networkData) return {};

  const adj = new Map();
  networkData.nodes.forEach(n => adj.set(n.id, []));
  networkData.edges.forEach(e => {
    adj.get(e.source).push(e.target);
    adj.get(e.target).push(e.source);
  });

  const labels = new Map();
  networkData.nodes.forEach(n => labels.set(n.id, n.id));

  for (let iter = 0; iter < 10; iter++) {
    let changed = false;
    networkData.nodes.forEach(n => {
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

  const communities = new Map();
  labels.forEach((community, nodeId) => {
    if (!communities.has(community)) communities.set(community, []);
    communities.get(community).push(nodeId);
  });

  return communities;
}

// Color by community
function colorByCommunity() {
  if (!networkInstance || !networkData) return;

  const communities = detectCommunities();
  const colors = [
    '#E74C3C', '#3498DB', '#2ECC71', '#F39C12', '#9B59B6',
    '#1ABC9C', '#E67E22', '#16A085', '#2980B9', '#8E44AD'
  ];

  let colorIdx = 0;
  const communityColors = new Map();
  const communityNames = new Map();
  
  communities.forEach((members, commId) => {
    communityColors.set(commId, colors[colorIdx % colors.length]);
    // Find the primary node in this community for naming
    const primaryInCommunity = members
      .map(id => networkData.nodes.find(n => n.id === id))
      .find(n => n?.type === 'primary');
    communityNames.set(commId, primaryInCommunity?.name || `Community ${colorIdx + 1}`);
    colorIdx++;
  });

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

  // Show communities in sidebar
  document.getElementById('mm-details').innerHTML = `
    <h3>🎨 Communities Detected</h3>
    <div class="community-list">
      ${Array.from(communities.entries()).map(([commId, members], idx) => `
        <div class="community-item" style="border-left: 4px solid ${communityColors.get(commId)}">
          <strong>${esc(communityNames.get(commId))}</strong>
          <div class="text-sm text-gray-400">${members.length} nodes</div>
        </div>
      `).join('')}
    </div>
  `;
}

// Reset colors
function resetNetworkColors() {
  if (!networkInstance) return;
  buildGraph(); // Rebuild with original colors
}

// Calculate centrality
function calculateCentrality() {
  if (!networkData) return {};

  const adj = new Map();
  networkData.nodes.forEach(n => adj.set(n.id, []));
  networkData.edges.forEach(e => {
    adj.get(e.source).push(e.target);
    adj.get(e.target).push(e.source);
  });

  // Degree centrality
  const degree = new Map();
  networkData.nodes.forEach(n => degree.set(n.id, adj.get(n.id).length));

  // Betweenness (simplified)
  const betweenness = new Map();
  networkData.nodes.forEach(n => betweenness.set(n.id, 0));

  return { degree, betweenness };
}

// Show network statistics
function showNetworkStats() {
  if (!networkData) return;

  const { degree } = calculateCentrality();

  const stats = {
    totalNodes: networkData.nodes.length,
    totalEdges: networkData.edges.length,
    primaryNodes: networkData.nodes.filter(n => n.type === 'primary').length,
    secondaryNodes: networkData.nodes.filter(n => n.type === 'secondary').length,
    avgConnections: networkData.edges.length > 0 ? (networkData.edges.length * 2 / networkData.nodes.length).toFixed(1) : 0,
  };

  const topConnected = [...degree.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([id, deg]) => {
      const node = networkData.nodes.find(n => n.id === id);
      return { name: node?.name || '?', degree: deg };
    });

  document.getElementById('mm-details').innerHTML = `
    <h3>📊 Network Statistics</h3>
    <div class="stats-list">
      <div class="stat-row"><span>Total Nodes:</span> <strong>${stats.totalNodes}</strong></div>
      <div class="stat-row"><span>Primary Nodes:</span> <strong>${stats.primaryNodes}</strong></div>
      <div class="stat-row"><span>Secondary Nodes:</span> <strong>${stats.secondaryNodes}</strong></div>
      <div class="stat-row"><span>Total Connections:</span> <strong>${stats.totalEdges}</strong></div>
      <div class="stat-row"><span>Avg Connections:</span> <strong>${stats.avgConnections}</strong></div>
    </div>
    <h4 class="mt-4">Most Connected</h4>
    <div class="top-nodes">
      ${topConnected.map((n, i) => `
        <div class="top-node-item">
          <span class="rank">${i + 1}.</span>
          <span class="name">${esc(n.name)}</span>
          <span class="degree">${n.degree} connections</span>
        </div>
      `).join('')}
    </div>
  `;
}

// Export as PNG
async function exportNetwork() {
  if (!networkInstance) return;

  const canvas = networkInstance.canvas.frame.canvas;
  const dataUrl = canvas.toDataURL('image/png');
  
  const link = document.createElement('a');
  link.download = `network-graph-${new Date().toISOString().split('T')[0]}.png`;
  link.href = dataUrl;
  link.click();
}
