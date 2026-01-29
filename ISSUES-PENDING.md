# Additional GitHub Issues to Create

## Documentation & Installation
**Priority: HIGH**
- [ ] Complete README.md with architecture overview
- [ ] Installation guide for Clawdbot/Moltbot users
- [ ] Configuration documentation (ports, paths, API keys)
- [ ] Deployment guide (systemd service, Docker, manual)
- [ ] Troubleshooting section
- [ ] Requirements.txt with version pins
- [ ] Example .env file with all config options

## Agent Chat Integration
**Priority: HIGH**
- [ ] Configurable agent endpoint (not hardcoded Ollama)
- [ ] Agent selector in UI (main agent, sub-agents, local models)
- [ ] Support Clawdbot gateway API (`sessions_send`)
- [ ] Support local Ollama
- [ ] Support remote agent sessions
- [ ] Session management for different agents
- [ ] Agent status indicator (online/offline, model info)
- [ ] Save agent preference per user

## Multi-Node Architecture
**Priority: MEDIUM**
- [ ] Document multi-node deployment patterns
- [ ] Load balancing across nodes
- [ ] Shared database vs per-node databases
- [ ] Node health monitoring
