
if ! id -u sideboard &>/dev/null; then
    groupadd --force -r sideboard
    useradd -r --shell /sbin/nologin --gid sideboard sideboard
fi
