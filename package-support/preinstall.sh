
if ! id -u sideboard &>/dev/null; then
    groupadd --force -r sideboard -g 600
    useradd -r --shell /sbin/nologin  -uid 600 --gid sideboard sideboard
fi
