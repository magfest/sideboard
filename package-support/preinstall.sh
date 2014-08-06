if ! id -u sideboard &>/dev/null; then
    adduser sideboard
fi

for dname in /var/run/sideboard /var/tmp/sideboard/sessions /opt/sideboard/db /opt/sideboard/plugins; do
    mkdir -p $dname
    chown sideboard.sideboard $dname
done
