#!/usr/bin/env bash
set -euo pipefail

SERVICE_LABEL="${SERVICE_LABEL:-com.capital-flow.web}"
launchctl kickstart -k "gui/$(id -u)/$SERVICE_LABEL"
echo "Restarted $SERVICE_LABEL"
