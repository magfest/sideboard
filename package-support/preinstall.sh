if ! id -u sideboard &>/dev/null; then
    adduser sideboard
fi

mkdir -p /var/run/sideboard
chown sideboard.sideboard /var/run/sideboard
