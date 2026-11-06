#!/bin/sh
set -e
prefix=${1:?Usage: install-cli.sh PREFIX}
resource_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install -Dm644 "$resource_dir/completions/pbox.bash" "$prefix/share/bash-completion/completions/pbox"
ln -sfn pbox "$prefix/share/bash-completion/completions/phpbox"
install -Dm644 "$resource_dir/completions/pbox.zsh" "$prefix/share/zsh/site-functions/_pbox"
install -Dm644 "$resource_dir/completions/pbox.fish" "$prefix/share/fish/vendor_completions.d/pbox.fish"
ln -sfn pbox.fish "$prefix/share/fish/vendor_completions.d/phpbox.fish"
install -Dm644 "$resource_dir/man/pbox.1" "$prefix/share/man/man1/pbox.1"
ln -sfn pbox.1 "$prefix/share/man/man1/phpbox.1"
