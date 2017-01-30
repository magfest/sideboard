
for dname in /var/run/sideboard /var/tmp/sideboard /var/tmp/sideboard/sessions /opt/sideboard /opt/sideboard/db /opt/sideboard/plugins; do
    mkdir -p $dname
    chmod 750 $dname
    chown sideboard.sideboard $dname
done

# unlike all of the other directories in the above loop, we want this directory (and also its contents) to be sideboard.root
chown -R root.sideboard /etc/sideboard

chown root.root /etc/init.d/sideboard
chown root.root /etc/sysconfig/sideboard

# TODO: instead of doing this in postinstall, we should eventually do --<type>-use-file-permissions
chmod 700 /etc/init.d/sideboard
chmod 600 /etc/sysconfig/sideboard
