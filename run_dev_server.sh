#!/bin/bash
# run a "dev" server (for local development)

set -e
cd /app/sideboard/

# TODO: need to add 'develop' in here
/app/env/bin/paver install_deps --env_path=/app/env/

bash ./run_server.sh