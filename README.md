# Evidence Browser

**Forensic evidence browser for the Tina Peters legal case**

Modern web application for browsing devices, messages, and legal documents with AI-powered search and analysis.

## Features

- 📱 **Device Browser** - 23 forensically extracted devices
- 💬 **Message Search** - 345K+ messages across SMS, Signal, Telegram
- 🔍 **RAG-Powered Search** - Semantic search across all evidence
- 🕸️ **Mind Map** - Network visualization of people and connections
- ⚖️ **Legal Files** - Browse case documents and discovery
- 🤖 **AI Chat** - Ask questions about the evidence
- 🔥 **Discoveries** - Track and highlight key findings

## Tech Stack

- **Backend:** Python 3.12, FastAPI, Uvicorn
- **Frontend:** Tailwind CSS, Vanilla JavaScript
- **Database:** PostgreSQL with pgvector for embeddings
- **Search:** Full-text search + semantic RAG
- **Auth:** Role-based access control (admin/analyst/viewer)

## Installation

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install Tailwind CSS
npm install

# Build Tailwind CSS
npm run build

# Run the server
python3 -m uvicorn server:app --host 0.0.0.0 --port 8888
```

## Configuration

- **Port:** 8888 (default)
- **Database:** PostgreSQL at localhost:54322
- **Auth:** Set up users via admin panel

## Development

```bash
# Watch mode for Tailwind CSS
npm run watch

# Run server with auto-reload
uvicorn server:app --reload --port 8888
```

## Project Structure

```
evidence-browser/
├── server.py           # FastAPI backend
├── auth.py             # Authentication & authorization
├── db.py               # Database operations
├── search_api.py       # RAG search & AI chat
├── static/             # Frontend files
│   ├── index.html      # Main SPA
│   ├── app.js          # Frontend logic
│   └── style.css       # Generated Tailwind CSS
├── mockup/             # Tailwind prototypes
└── media/              # Evidence files (gitignored)
```

## License

Proprietary - Tina Peters Legal Defense

## Credits

Built with ❤️ by Bibbinz for Jared Cowart and the Tina Peters legal team.
