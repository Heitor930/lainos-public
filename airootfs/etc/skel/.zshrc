# ‡ LainOS — zsh

# --- Histórico -----------------------------------------------------------
HISTFILE=~/.zsh_history
HISTSIZE=50000
SAVEHIST=50000
setopt share_history hist_ignore_dups hist_ignore_space hist_reduce_blanks
setopt auto_cd interactive_comments no_beep

# --- Completar -----------------------------------------------------------
autoload -Uz compinit && compinit -d "${XDG_CACHE_HOME:-$HOME/.cache}/zcompdump"
zstyle ':completion:*' menu select
zstyle ':completion:*' matcher-list 'm:{a-z}={A-Z}'
zstyle ':completion:*' list-colors ''

# --- Teclas --------------------------------------------------------------
bindkey -e
bindkey '^[[H' beginning-of-line
bindkey '^[[F' end-of-line
bindkey '^[[3~' delete-char
bindkey '^[[1;5C' forward-word
bindkey '^[[1;5D' backward-word
bindkey '^[[A' history-beginning-search-backward
bindkey '^[[B' history-beginning-search-forward

# --- Caminhos ------------------------------------------------------------
typeset -U path
path=("$HOME/.local/bin" $path)
export EDITOR="${EDITOR:-nvim}"
export VISUAL="$EDITOR"

# --- Atalhos -------------------------------------------------------------
if command -v eza >/dev/null; then
    alias ls='eza --group-directories-first'
    alias ll='eza -l --group-directories-first --git'
    alias la='eza -la --group-directories-first --git'
    alias tree='eza --tree --level=3'
else
    alias ls='ls --color=auto'
    alias ll='ls -lh'
    alias la='ls -lah'
fi
command -v bat >/dev/null && alias cat='bat --style=plain --paging=never'
alias grep='grep --color=auto'
alias ip='ip -color=auto'
alias px='proxychains4 -q'            # px curl ifconfig.me  -> sai pelo Tor
alias myip='curl -s https://check.torproject.org/api/ip'
alias atualizar='lain-update'
alias fetch='lain-fetch'

# Proxy ligado pelo lain-proxy vale para os terminais abertos depois
[[ -r "${XDG_RUNTIME_DIR:-/tmp}/lainos-proxy.env" ]] && source "${XDG_RUNTIME_DIR:-/tmp}/lainos-proxy.env"

# --- Plugins -------------------------------------------------------------
[[ -r /usr/share/zsh/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh ]] &&
    source /usr/share/zsh/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh
ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE='fg=#4a5046'
[[ -r /usr/share/zsh/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh ]] &&
    source /usr/share/zsh/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh

# --- Prompt --------------------------------------------------------------
if command -v starship >/dev/null; then
    eval "$(starship init zsh)"
else
    PROMPT='%F{#e8eae4}%B%~%b%f %F{#8a9a5b}❯%f '
fi

# --- Boas-vindas ---------------------------------------------------------
# Só no primeiro shell de cada janela de terminal; nunca em scripts, no
# VS Code ou em sessões SSH. Desligue com: touch ~/.config/lainos/no-fetch
if [[ -o interactive && $SHLVL -eq 1 && -z $SSH_CONNECTION && $TERM_PROGRAM != vscode \
      && ! -e ~/.config/lainos/no-fetch ]] && command -v lain-fetch >/dev/null; then
    lain-fetch
fi
