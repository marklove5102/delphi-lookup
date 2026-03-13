# Claude Code Setup for delphi-lookup

This guide configures Claude Code to use delphi-lookup for Pascal/Delphi development:

- **delphi-lookup skill** — teaches Claude Code to prefer `delphi-lookup.exe` over Grep for symbol searches
- **LSP plugin** — provides go-to-definition, hover, find-references, and document-symbols directly as Claude Code tools

## Prerequisites

1. **Build the tools** (requires RAD Studio 12):
   - `delphi-indexer.exe` — indexes your Pascal source code
   - `delphi-lookup.exe` — command-line symbol search
   - `delphi-lsp-server.exe` — LSP server (Win64 only)

2. **Create your index**:
   ```bash
   # Index your project (Windows paths for .exe arguments)
   delphi-indexer.exe "C:\YourProject\src" --category user

   # Index Delphi standard library (optional but recommended)
   delphi-indexer.exe "C:\Program Files (x86)\Embarcadero\Studio\23.0\source\rtl" --category stdlib
   delphi-indexer.exe "C:\Program Files (x86)\Embarcadero\Studio\23.0\source\vcl" --category stdlib
   ```

3. Note the absolute paths to:
   - `delphi-lsp-server.exe`
   - `delphi_symbols.db` (in Windows format, e.g., `C:\tools\delphi_symbols.db`)

---

## 1. Install the delphi-lookup Skill

The skill teaches Claude Code to use `delphi-lookup.exe` for symbol searches instead of Grep.

**WSL / Linux:**
```bash
mkdir -p ~/.claude/skills/delphi-lookup
cp claude-code/skill.md ~/.claude/skills/delphi-lookup/skill.md
```

**Windows (cmd):**
```cmd
mkdir "%USERPROFILE%\.claude\skills\delphi-lookup"
copy claude-code\skill.md "%USERPROFILE%\.claude\skills\delphi-lookup\skill.md"
```

Add to your CLAUDE.md (`~/.claude/CLAUDE.md` or `%USERPROFILE%\.claude\CLAUDE.md`):

```markdown
## Delphi Symbol Lookup

**CRITICAL**: To find WHERE a Pascal symbol is defined:
1. **FIRST**: Use delphi-lookup.exe
2. **FALLBACK**: Use Grep only if delphi-lookup returns no results

| Situation | Command |
|-----------|---------|
| "Undeclared identifier: X" error | `delphi-lookup.exe "X" -n 5` |
| Find function/type definition | `delphi-lookup.exe "SymbolName" -n 5` |

**Why**: Sub-millisecond cached FTS5 search vs sequential file scanning.
```

---

## 2. Install the LSP Plugin

The LSP plugin gives Claude Code native tool access to:

| Operation | What it does | Value |
|-----------|-------------|-------|
| `documentSymbol` | Lists all symbols in a file with types and line numbers | Best feature — structured file overview in one call |
| `hover` | Shows full class/function declaration as formatted markdown | Rich preview with comments |
| `goToDefinition` | Navigates to where a symbol is defined | Works, but `delphi-lookup.exe` is often better |
| `findReferences` | Finds files referencing a symbol | Works, but Grep is more reliable |
| `workspaceSymbol` | Searches symbols by name | Not functional in Claude Code (see [Known Issues](#known-issues)) |

### Automatic Installation

**Windows (cmd or PowerShell):**

```cmd
cd C:\path\to\delphi-lookup
claude-code\install-lsp-plugin.bat "C:\tools\delphi-lsp-server.exe" "C:\tools\delphi_symbols.db"
```

**WSL / Linux:**

```bash
cd /path/to/delphi-lookup
./claude-code/install-lsp-plugin.sh /mnt/w/tools/delphi-lsp-server.exe "W:\tools\delphi_symbols.db"
```

Both scripts:
1. Create the plugin directory structure under `%USERPROFILE%\.claude\skills\` (Windows) or `~/.claude/skills/` (WSL)
2. Generate `plugin.json` with your paths
3. Tell you what to add to `settings.json`

### Manual Installation

If you prefer to do it by hand:

#### Step 1: Create plugin directory structure

**Windows:** `%USERPROFILE%\.claude\skills\delphi-lsp\`
**WSL/Linux:** `~/.claude/skills/delphi-lsp/`

```
.claude/skills/delphi-lsp/
├── .claude-plugin/
│   └── marketplace.json
└── plugins/
    └── delphi-lsp/
        └── .claude-plugin/
            └── plugin.json
```

#### Step 2: Create marketplace.json

File: `~/.claude/skills/delphi-lsp/.claude-plugin/marketplace.json`

```json
{
  "name": "delphi-lsp-marketplace",
  "owner": {
    "name": "delphi-lookup"
  },
  "metadata": {
    "description": "Delphi/Pascal LSP server using delphi-lookup index"
  },
  "plugins": [
    {
      "name": "delphi-lsp",
      "source": "./plugins/delphi-lsp",
      "description": "Delphi/Pascal language server for go-to-definition, find-references, hover, and document symbols",
      "version": "1.1.0",
      "author": {
        "name": "delphi-lookup"
      }
    }
  ]
}
```

#### Step 3: Create plugin.json

File: `~/.claude/skills/delphi-lsp/plugins/delphi-lsp/.claude-plugin/plugin.json`

```json
{
  "name": "delphi-lsp",
  "version": "1.1.0",
  "description": "Delphi/Pascal language server using delphi-lookup index",
  "lspServers": {
    "delphi": {
      "command": "/path/to/delphi-lsp-server.exe",
      "args": ["--database", "C:\\path\\to\\delphi_symbols.db"],
      "extensionToLanguage": {
        ".pas": "pascal",
        ".dpr": "pascal",
        ".dpk": "pascal",
        ".inc": "pascal"
      },
      "startupTimeout": 10000
    }
  }
}
```

**Important**: Replace the paths:
- `command` — absolute path to `delphi-lsp-server.exe`
  - **Windows**: `"C:\\tools\\delphi-lsp-server.exe"`
  - **WSL**: `"/mnt/w/tools/delphi-lsp-server.exe"`
- `args` — database path in **Windows format** always (the `.exe` uses Windows path resolution)
  - `"C:\\tools\\delphi_symbols.db"` or `"W:\\tools\\delphi_symbols.db"`

#### Step 4: Register in settings.json

Add to `~/.claude/settings.json` (on Windows: `%USERPROFILE%\.claude\settings.json`):

```json
{
  "enabledPlugins": {
    "delphi-lsp@delphi-lsp-marketplace": true
  },
  "extraKnownMarketplaces": {
    "delphi-lsp-marketplace": {
      "source": {
        "source": "directory",
        "path": "<ABSOLUTE_PATH_TO>/.claude/skills/delphi-lsp"
      }
    }
  }
}
```

Replace `<ABSOLUTE_PATH_TO>` with your home directory using **forward slashes**:
- **Windows**: `C:/Users/john/.claude/skills/delphi-lsp`
- **WSL**: `/home/john/.claude/skills/delphi-lsp`

> **Tip**: The install scripts print the exact path to use. Run `install-lsp-plugin.bat` or `.sh` first and copy from there.

#### Step 5: Restart Claude Code

The LSP server starts automatically when you open a `.pas` file.

---

## 3. Optional: Auto-allow permissions

Add to your `settings.json` (same file from Step 4) under `permissions.allow`:

```json
"Bash(delphi-lookup.exe:*)",
"Bash(delphi-indexer.exe:*)"
```

---

## Verification

After installation, restart Claude Code and test:

```
# Test LSP — should show symbols with types and line numbers
Open any .pas file and ask Claude to list its symbols using documentSymbol

# Test LSP hover — should show formatted class declaration
Ask Claude to hover over a known symbol in a .pas file

# Test delphi-lookup skill — should use delphi-lookup.exe, not Grep
Ask: "Search for TStringList using delphi-lookup"
```

---

## Known Issues

### workspaceSymbol returns no results

**Status**: Claude Code bug ([#17149](https://github.com/anthropics/claude-code/issues/17149))

Claude Code sends `{"query":""}` for `workspace/symbol` requests instead of extracting the symbol name from the file position. The LSP server returns an error message guiding you to use `delphi-lookup.exe` as a workaround.

This cannot be fixed from the server side. Use `delphi-lookup.exe` for workspace-wide symbol search.

### Database path must be Windows format (WSL only)

When running under WSL, the `--database` argument in `plugin.json` must use Windows-format paths (`C:\...` or `W:\...`) because `delphi-lsp-server.exe` is a Windows executable. The `command` path can use WSL format (`/mnt/w/...`). On Windows native, all paths are already in the correct format.

### Server requires Win64

`delphi-lsp-server.exe` must be compiled as Win64 (for sqlite-vec compatibility). The project enforces this with a compile-time check.
