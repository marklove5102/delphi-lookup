#!/bin/bash
# install-lsp-plugin.sh — Install delphi-lsp plugin for Claude Code
#
# Usage:
#   ./install-lsp-plugin.sh <path-to-delphi-lsp-server.exe> <path-to-delphi_symbols.db>
#
# Both paths must be absolute. On WSL, the database path must be in Windows format (W:\...).
# The server path can be either Linux (/mnt/w/...) or Windows format.
#
# Example (WSL):
#   ./install-lsp-plugin.sh /mnt/w/tools/delphi-lsp-server.exe "W:\tools\delphi_symbols.db"
#
# Example (Windows Git Bash):
#   ./install-lsp-plugin.sh "C:/tools/delphi-lsp-server.exe" "C:\tools\delphi_symbols.db"

set -euo pipefail

# --- Validate arguments ---
if [ $# -ne 2 ]; then
    echo "Usage: $0 <path-to-delphi-lsp-server.exe> <path-to-delphi_symbols.db>"
    echo ""
    echo "Both paths must be absolute."
    echo "The database path must be in Windows format for .exe (e.g., W:\\tools\\delphi_symbols.db)"
    exit 1
fi

SERVER_PATH="$1"
DB_PATH="$2"

# --- Determine script directory (where template files are) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_DIR="$SCRIPT_DIR/plugin"

if [ ! -f "$TEMPLATE_DIR/marketplace.json" ]; then
    echo "Error: Template files not found in $TEMPLATE_DIR"
    echo "Make sure you run this script from the delphi-lookup/claude-code/ directory."
    exit 1
fi

# --- Target directory ---
PLUGIN_DIR="$HOME/.claude/skills/delphi-lsp"
PLUGIN_JSON_DIR="$PLUGIN_DIR/plugins/delphi-lsp/.claude-plugin"

echo "Installing delphi-lsp plugin for Claude Code..."
echo "  Server:   $SERVER_PATH"
echo "  Database: $DB_PATH"
echo "  Target:   $PLUGIN_DIR"
echo ""

# --- Create directory structure ---
mkdir -p "$PLUGIN_DIR/.claude-plugin"
mkdir -p "$PLUGIN_JSON_DIR"

# --- Copy marketplace.json ---
cp "$TEMPLATE_DIR/marketplace.json" "$PLUGIN_DIR/.claude-plugin/marketplace.json"

# --- Generate plugin.json with actual paths ---
# Escape backslashes for JSON
DB_PATH_ESCAPED=$(echo "$DB_PATH" | sed 's/\\/\\\\/g')
SERVER_PATH_ESCAPED=$(echo "$SERVER_PATH" | sed 's/\\/\\\\/g')

sed \
    -e "s|__DELPHI_LSP_SERVER_PATH__|$SERVER_PATH_ESCAPED|g" \
    -e "s|__DELPHI_SYMBOLS_DB_PATH__|$DB_PATH_ESCAPED|g" \
    "$TEMPLATE_DIR/plugins/delphi-lsp/.claude-plugin/plugin.json" \
    > "$PLUGIN_JSON_DIR/plugin.json"

echo "Generated plugin.json:"
cat "$PLUGIN_JSON_DIR/plugin.json"
echo ""

# --- Check if plugin is already enabled in settings ---
SETTINGS_FILE="$HOME/.claude/settings.json"
if [ -f "$SETTINGS_FILE" ]; then
    if grep -q "delphi-lsp@delphi-lsp-marketplace" "$SETTINGS_FILE"; then
        echo "Plugin already registered in settings.json."
    else
        echo ""
        echo "=== MANUAL STEP REQUIRED ==="
        echo ""
        echo "Add this to your ~/.claude/settings.json:"
        echo ""
        echo '  "enabledPlugins": {'
        echo '    "delphi-lsp@delphi-lsp-marketplace": true'
        echo '  },'
        echo '  "extraKnownMarketplaces": {'
        echo '    "delphi-lsp-marketplace": {'
        echo '      "source": {'
        echo '        "source": "directory",'
        echo "        \"path\": \"$PLUGIN_DIR\""
        echo '      }'
        echo '    }'
        echo '  }'
        echo ""
    fi
else
    echo ""
    echo "=== MANUAL STEP REQUIRED ==="
    echo ""
    echo "No settings.json found. Create ~/.claude/settings.json with:"
    echo ""
    echo '{'
    echo '  "enabledPlugins": {'
    echo '    "delphi-lsp@delphi-lsp-marketplace": true'
    echo '  },'
    echo '  "extraKnownMarketplaces": {'
    echo '    "delphi-lsp-marketplace": {'
    echo '      "source": {'
    echo '        "source": "directory",'
    echo "        \"path\": \"$PLUGIN_DIR\""
    echo '      }'
    echo '    }'
    echo '  }'
    echo '}'
    echo ""
fi

echo "Done. Restart Claude Code to activate the LSP server."
