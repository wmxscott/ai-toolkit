#!/usr/bin/env bash
# Makes the current repository commit, push and open pull requests as the GitHub App
# that gh-app-auth has configured for it.
#
#   setup [--coauthor "Name <email>"]   act as the app in this repository
#   status                              check the setup and mint a fresh token
#   rekey <private-key.pem>             store a new private key for the app
#   off                                 go back to your own identity
set -euo pipefail

SECTION=gh-app-auth
HELPER='!gh app-auth git-credential'

die() {
	printf 'gh-app-identity: %s\n' "$*" >&2
	exit 1
}

usage() {
	sed -n '4,7s/^#   //p' "$0" >&2
	exit 64
}

need() {
	command -v "$1" >/dev/null 2>&1 || die "$1 is not installed${2:+ ($2)}"
}

in_repo() {
	git rev-parse --git-dir >/dev/null 2>&1 || die "not inside a git repository"
}

# Sets HOST, OWNER, NAME and TARGET (host/owner/name) from the origin remote's fetch URL.
parse_remote() {
	local url rest path
	url=$(git remote get-url origin 2>/dev/null) || die "the repository has no origin remote"
	case $url in
	https://* | http://*)
		rest=${url#*://}
		rest=${rest#*@}
		;;
	ssh://*)
		rest=${url#ssh://}
		rest=${rest#*@}
		;;
	*@*:*)
		rest=${url#*@}
		rest=${rest/:/\/}
		;;
	*) die "can't read owner and repository from origin URL $url" ;;
	esac
	rest=${rest%/}
	rest=${rest%.git}
	HOST=${rest%%/*}
	HOST=${HOST%%:*}
	path=${rest#*/}
	OWNER=${path%%/*}
	NAME=${path#*/}
	if [[ -z $HOST || -z $OWNER || -z $NAME || $NAME == */* || $path == "$rest" ]]; then
		die "can't read owner and repository from origin URL $url"
	fi
	TARGET=$HOST/$OWNER/$NAME
}

helper_key() {
	printf 'credential.https://%s/%s.helper' "$HOST" "$OWNER"
}

# Prints "<login> <user id>" of whoever the app's installation token acts as.
app_identity() {
	gh app-auth exec --repo "$TARGET" -- \
		gh api graphql -f query='{viewer{login databaseId}}' \
		--jq '.data.viewer | "\(.login) \(.databaseId)"'
}

valid_coauthor() {
	local pattern='^[^<>]+ <[^<> ]+@[^<> ]+>$'
	[[ $1 =~ $pattern ]]
}

cmd_setup() {
	local coauthor="" login id identity
	while (($#)); do
		case $1 in
		--coauthor)
			(($# >= 2)) || usage
			coauthor=$2
			shift 2
			;;
		*) usage ;;
		esac
	done
	need gh
	in_repo
	parse_remote
	gh app-auth --help >/dev/null 2>&1 ||
		die "the gh-app-auth extension is missing: gh extension install AmadeusITGroup/gh-app-auth"

	identity=$(app_identity) ||
		die "no working GitHub App for $TARGET; run: gh app-auth test --repo $TARGET"
	login=${identity% *}
	id=${identity##* }
	[[ $login == *"[bot]" && $id =~ ^[0-9]+$ ]] ||
		die "$TARGET authenticates as '$login', not as a GitHub App; check gh app-auth list"

	if [[ -z $coauthor ]]; then
		coauthor=$(git config --local --get "$SECTION.coauthor" || true)
	fi
	if [[ -z $coauthor ]]; then
		local name email
		name=$(git config --get user.name || true)
		email=$(git config --get user.email || true)
		if [[ -n $name && -n $email && $name != "$login" ]]; then
			coauthor="$name <$email>"
		fi
	fi
	[[ -n $coauthor ]] || die "no git identity to credit; pass --coauthor \"Name <email>\""
	valid_coauthor "$coauthor" || die "--coauthor must look like \"Name <email>\", got: $coauthor"

	local key
	key=$(helper_key)
	git config --local user.name "$login"
	git config --local user.email "$id+$login@users.noreply.github.com"
	git config --local commit.gpgsign false
	# The empty value drops the helpers inherited from system and global config, so no
	# saved credential or stale app token is tried before gh-app-auth mints a fresh one.
	git config --local --replace-all "$key" ''
	git config --local --add "$key" "$HELPER"
	git config --local "credential.https://$HOST.useHttpPath" true
	git config --local "$SECTION.login" "$login"
	git config --local "$SECTION.userid" "$id"
	git config --local "$SECTION.coauthor" "$coauthor"
	git config --local "$SECTION.repo" "$TARGET"

	printf 'This repository now acts as %s.\n' "$login"
	printf '  author     %s <%s+%s@users.noreply.github.com>\n' "$login" "$id" "$login"
	printf '  co-author  %s\n' "$coauthor"
	printf '  signing    off\n'
	warn_push_url
}

warn_push_url() {
	local push
	push=$(git remote get-url --push origin)
	case $push in
	https://*) ;;
	*)
		printf 'warning: origin pushes over %s, as you rather than the app. To push as the app:\n' "$push"
		printf '  git remote set-url --push origin https://%s.git\n' "$TARGET"
		;;
	esac
}

cmd_status() {
	(($# == 0)) || usage
	in_repo
	local login
	login=$(git config --local --get "$SECTION.login" || true)
	if [[ -z $login ]]; then
		printf 'Not set up: this repository commits as %s.\n' "$(git config --get user.name || echo nobody)"
		exit 2
	fi
	need gh
	parse_remote

	local problems=0 id email key helpers identity
	id=$(git config --local --get "$SECTION.userid")
	email="$id+$login@users.noreply.github.com"
	key=$(helper_key)

	problem() {
		printf 'problem: %s\n' "$*"
		problems=$((problems + 1))
	}

	[[ $(git config --get user.name) == "$login" ]] ||
		problem "user.name is '$(git config --get user.name)', not $login"
	[[ $(git config --get user.email) == "$email" ]] ||
		problem "user.email is '$(git config --get user.email)', not $email"
	[[ $(git config --type=bool --get commit.gpgsign || echo false) == false ]] ||
		problem "commit.gpgsign is on; bot commits would show as Unverified"
	helpers=$(git config --local --get-all "$key" || true)
	[[ $helpers == $'\n'"$HELPER" ]] ||
		problem "credential helpers for https://$HOST/$OWNER are not reset to gh-app-auth alone"
	[[ $(git config --local --type=bool --get "credential.https://$HOST.useHttpPath" || true) == true ]] ||
		problem "credential.https://$HOST.useHttpPath is not on"
	[[ -n $(git config --local --get "$SECTION.coauthor" || true) ]] ||
		problem "no co-author recorded"
	local var
	for var in GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL; do
		[[ -z ${!var:-} ]] || problem "$var is set in the environment and overrides the app identity"
	done
	for var in GH_TOKEN GITHUB_TOKEN; do
		[[ -z ${!var:-} ]] || printf 'warning: %s is exported; plain gh calls use it instead of the app\n' "$var"
	done

	if identity=$(app_identity 2>&1); then
		[[ ${identity% *} == "$login" ]] ||
			problem "the app token for $TARGET acts as '${identity% *}', not $login"
	else
		problem "could not mint a token for $TARGET: $identity"
		printf '  diagnose with: gh app-auth test --repo %s --verbose\n' "$TARGET"
	fi
	warn_push_url

	if ((problems)); then
		exit 1
	fi
	printf 'OK: %s, fresh token minted for %s.\n' "$login" "$TARGET"
}

cmd_rekey() {
	(($# == 1)) || usage
	local pem=$1
	[[ -f $pem ]] || die "no such file: $pem"
	grep -q 'PRIVATE KEY-----' "$pem" || die "$pem is not a PEM private key"
	need gh
	need jq
	in_repo
	parse_remote

	# Ranks the apps whose patterns match this repository the way gh-app-auth routes:
	# highest priority, then longest pattern.
	local matches="" best priority selector value name patterns pattern
	while IFS=$'\t' read -r priority selector value name patterns pattern; do
		# shellcheck disable=SC2053
		if [[ $TARGET == $pattern || $TARGET == "${pattern%\*}"* ]]; then
			matches+="$priority"$'\t'"${#pattern}"$'\t'"$selector"$'\t'"$value"$'\t'"$name"$'\t'"$patterns"$'\n'
		fi
	done < <(gh app-auth list --format json | jq -r '
		[.. | objects | select(has("patterns") and (has("client_id") or has("app_id")))][]
		| . as $app
		| (if $app.client_id then ["--client-id", $app.client_id] else ["--app-id", ($app.app_id | tostring)] end) as $sel
		| $app.patterns[]
		| [($app.priority // 5 | tostring), $sel[0], $sel[1], ($app.name // "GitHub App \($sel[1])"),
		   ($app.patterns | join(",")), .]
		| @tsv')
	best=$(printf '%s' "$matches" | sort -t $'\t' -k1,1nr -k2,2nr | head -n 1)
	[[ -n $best ]] || die "no GitHub App in gh app-auth list matches $TARGET; run gh app-auth setup first"

	IFS=$'\t' read -r priority _ selector value name patterns <<<"$best"
	GH_APP_PRIVATE_KEY=$(<"$pem") gh app-auth setup "$selector" "$value" \
		--patterns "$patterns" --name "$name" --priority "$priority"
	gh app-auth test --repo "$TARGET"
	printf 'Stored the new key for %s in the keyring. %s can now be deleted.\n' "$name" "$pem"
}

cmd_off() {
	(($# == 0)) || usage
	in_repo
	local login key
	login=$(git config --local --get "$SECTION.login" || true)
	[[ -n $login ]] || die "this repository is not set up to act as a GitHub App"
	parse_remote
	key=$(helper_key)
	[[ $(git config --local --get user.name || true) != "$login" ]] || git config --local --unset user.name
	[[ $(git config --local --get user.email || true) != *"+$login@users.noreply.github.com" ]] ||
		git config --local --unset user.email
	git config --local --unset commit.gpgsign || true
	git config --local --unset-all "$key" || true
	git config --local --unset "credential.https://$HOST.useHttpPath" || true
	git config --local --remove-section "$SECTION"
	printf 'This repository commits as %s again.\n' "$(git config --get user.name || echo nobody)"
}

(($#)) || usage
command=$1
shift
case $command in
setup) cmd_setup "$@" ;;
status) cmd_status "$@" ;;
rekey) cmd_rekey "$@" ;;
off) cmd_off "$@" ;;
*) usage ;;
esac
