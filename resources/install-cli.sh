#!/bin/sh
set -e
prefix=${1:?Usage: install-cli.sh PREFIX [BIN_PREFIX]}
bin_prefix=${2:-"$prefix"}
resource_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install -Dm755 "$resource_dir/pbox-proxy" "$bin_prefix/bin/pbox-proxy"
install -Dm644 "$resource_dir/completions/pbox.bash" "$prefix/share/bash-completion/completions/pbox"
ln -sfn pbox "$prefix/share/bash-completion/completions/phpbox"
ln -sfn pbox "$prefix/share/bash-completion/completions/pbox-proxy"
install -Dm644 "$resource_dir/completions/pbox.zsh" "$prefix/share/zsh/site-functions/_pbox"
install -Dm644 "$resource_dir/completions/pbox.fish" "$prefix/share/fish/vendor_completions.d/pbox.fish"
ln -sfn pbox.fish "$prefix/share/fish/vendor_completions.d/phpbox.fish"
ln -sfn pbox.fish "$prefix/share/fish/vendor_completions.d/pbox-proxy.fish"
install -Dm644 "$resource_dir/man/pbox.1" "$prefix/share/man/man1/pbox.1"
ln -sfn pbox.1 "$prefix/share/man/man1/phpbox.1"
ln -sfn pbox.1 "$prefix/share/man/man1/pbox-proxy.1"
