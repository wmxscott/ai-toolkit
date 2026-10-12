#!/usr/bin/env bash
# Sets up `git app`, a git alias that runs one git command as the GitHub App that
# gh-app-auth has configured for this repository. Plain git is left alone.
#
#   setup [--coauthor "Name <email>"]   add the alias and record the app's identity
#   status                              check the setup and mint a fresh token
#   rekey <private-key.pem>             store a new private key for the app
#   off                                 remove the alias and the recorded identity
set -euo pipefail

SECTION=gh-app-auth

# Runs from the directory git was called in, reads the identity at call time, credits
# the co-author on `commit`, and passes everything else to git as `-c` options:
# the bot as author and committer, no signing, gh-app-auth as the only credential
# helper for the owner, and HTTPS in place of SSH (insteadOf also rewrites a pushurl).
# shellcheck disable=SC2016
ALIAS='!f() { cd "${GIT_PREFIX:-.}" || return 1; login=$(git config --get gh-app-auth.login) && id=$(git config --get gh-app-auth.userid) && coauthor=$(git config --get gh-app-auth.coauthor) && repo=$(git config --get gh-app-auth.repo) || { echo "git app: not set up; run gh-app-identity.sh setup" >&2; return 1; }; host=${repo%%/*}; owner=${repo#*/}; owner=${owner%%/*}; if [ "$1" = commit ]; then shift; set -- commit --trailer "Co-authored-by: $coauthor" "$@"; fi; git -c user.name="$login" -c user.email="$id+$login@users.noreply.github.com" -c commit.gpgsign=false -c trailer.ifexists=addIfDifferent -c "credential.https://$host/$owner.helper=" -c "credential.https://$host/$owner.helper=!gh app-auth git-credential" -c "credential.https://$host.useHttpPath=true" -c "url.https://$host/.insteadOf=git@$host:" -c "url.https://$host/.insteadOf=ssh://git@$host/" "$@"; }; f'

die() {
	printf 'gh-app-identity: %s\n' "$*" >&2
	exit 1
}

usage() {
	sed -n '5,8s/^#   //p' "$0" >&2
	exit 64
}

need() {
	command -v "$1" >/dev/null 2>&1 || die "$1 is not installed"
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
		[[ -z $name || -z $email ]] || coauthor="$name <$email>"
	fi
	[[ -n $coauthor ]] || die "no git identity to credit; pass --coauthor \"Name <email>\""
	valid_coauthor "$coauthor" || die "--coauthor must look like \"Name <email>\", got: $coauthor"

	git config --local "$SECTION.login" "$login"
	git config --local "$SECTION.userid" "$id"
	git config --local "$SECTION.coauthor" "$coauthor"
	git config --local "$SECTION.repo" "$TARGET"
	git config --local alias.app "$ALIAS"

	printf '"git app <command>" now runs git as %s in this repository.\n' "$login"
	printf '  author     %s <%s+%s@users.noreply.github.com>\n' "$login" "$id" "$login"
	printf '  co-author  %s\n' "$coauthor"
	printf 'Plain git still runs as %s.\n' "$(git config --get user.name || echo you)"
}

cmd_status() {
	(($# == 0)) || usage
	in_repo
	local login
	login=$(git config --local --get "$SECTION.login" || true)
	if [[ -z $login ]]; then
		printf 'Not set up: this repository has no "git app".\n'
		exit 2
	fi
	need gh
	parse_remote

	local problems=0 identity var
	problem() {
		printf 'problem: %s\n' "$*"
		problems=$((problems + 1))
	}

	[[ $(git config --local --get alias.app || true) == "$ALIAS" ]] ||
		problem "the git app alias is missing or changed"
	[[ $(git config --local --get "$SECTION.repo" || true) == "$TARGET" ]] ||
		problem "$SECTION.repo is not $TARGET"
	[[ $(git config --local --get "$SECTION.userid" || true) =~ ^[0-9]+$ ]] ||
		problem "no bot user ID recorded"
	[[ -n $(git config --local --get "$SECTION.coauthor" || true) ]] ||
		problem "no co-author recorded"
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
	[[ -n $(git config --local --get "$SECTION.login" || true) ]] ||
		die "this repository has no git app to remove"
	git config --local --unset alias.app || true
	git config --local --remove-section "$SECTION"
	printf 'Removed "git app" from this repository.\n'
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
