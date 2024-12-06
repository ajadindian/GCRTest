#!/bin/bash
export PYTHONUNBUFFERED=1

# Exit immediately if a command exits with a non-zero status
set -e

# Define color codes for formatting
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Function to display a banner
function display_banner() {
    echo -e "${CYAN}"
    echo "==================================================="
    echo "         🚀 Green CodeRefiner is Starting  🚀        "
    echo "==================================================="
    echo -e "${NC}"
}

# Function to display success messages
function success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

# Function to display error messages
function error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to display info messages
function info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}
# Function to display note messages
function note() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

# Display the banner
display_banner

# Check if the Flask app has already started
if [ -z "$FLASK_STARTED" ]; then
    export FLASK_STARTED=true
    info "Starting Flask web app for configuration..."
    python /app/webapp/app.py &
else
    info "Flask web app already running."
fi

# Wait until .env file is updated by the web app
info "The Green CodeRefiner is early access version, kindly if you have any issue or suggestion please report to us on sustainability@techmahindra.com"
info "please go to ${YELLOW}http://127.0.0.1:5000${NC} and configure paths"
note "http://172.17.0.2:5000 is only for container use, please use the correct IP address for your environment"
while [ ! -f /app/run_scripts.flag ]; do
  sleep 1
done
# while [ ! -f /app/.env ]; do
#   sleep 1
# done

echo -e "${GREEN}[SUCCESS] User confirmed start. Proceeding to execute scripts...${NC}"

# Read user password from environment variable
USER_PASSWORD=${ENTER_PASSWORD}

# Read expected password from environment variable
EXPECTED_PASSWORD=${EXPECTED_PASSWORD}

# Check if both passwords are provided
if [ -z "$USER_PASSWORD" ] || [ -z "$EXPECTED_PASSWORD" ]; then
    error "USER_PASSWORD and EXPECTED_PASSWORD environment variables must be set."
    exit 1
fi

# Verify the password
if [ "$USER_PASSWORD" != "$EXPECTED_PASSWORD" ]; then
    error "Incorrect password. Exiting."
    exit 1
fi

success "Password verified successfully."

# Run Python scripts with unbuffered output
function run_python_script() {
    local script_name=$1
    info "Running ${script_name}..."
    python -u "${script_name}"  # Add -u to force unbuffered stdout/stderr
    success "${script_name} completed successfully."
}

# Run Python scripts sequentially after .env is updated
run_python_script "server_emissions.py"
run_python_script "AzureMarketplace.py"
run_python_script "track_emissions.py"

info "All scripts executed successfully."

echo -e "${YELLOW}Processing complete.${NC}"

# Optional: Display a footer message
echo -e "${CYAN}"
echo "=========================================================="
echo "        🟢 Green CodeRefiner Service is Completed 🟢           "
echo "=========================================================="
echo -e "${NC}"
